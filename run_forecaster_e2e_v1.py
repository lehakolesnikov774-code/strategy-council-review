#!/usr/bin/env python3
"""Reproducible E2E runner for the canonical analog forecaster v11.

Input schema:
- timestamp, timeframe, session_bucket, secid, current_price, atr
- feature__<name> columns
- cross_session_<horizon>
- optional fwd_ret_<horizon>, fwd_available_at_<horizon>

The runner never synthesizes missing maturity timestamps. A label without a valid
fwd_available_at remains unavailable, matching the v11 fail-closed contract.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd

HORIZONS = ("30m", "60m", "90m", "120m")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("forecaster_v11_e2e", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    # dataclasses resolves module metadata through sys.modules during import.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def read_table(path: Path) -> pd.DataFrame:
    ext = path.suffix.lower()
    if ext == ".parquet":
        return pd.read_parquet(path)
    if ext in (".csv", ".txt"):
        return pd.read_csv(path)
    raise ValueError(f"Unsupported dataset extension: {ext}")


def parse_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if v == 1:
            return True
        if v == 0:
            return False
    if isinstance(v, str):
        s = v.strip().lower()
        if s == "true":
            return True
        if s == "false":
            return False
    raise ValueError(f"Not a strict bool: {v!r}")


def aware_dt(v: Any):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    t = pd.Timestamp(v)
    if t.tzinfo is None:
        raise ValueError(f"Naive timestamp is not allowed: {v!r}")
    return t.to_pydatetime()


def calibration_from_csv(path: Optional[Path]) -> Dict[str, Any]:
    if path is None:
        return {}
    simple: Dict[str, Any] = {}
    per_n: Dict[str, int] = {}
    per_ess: Dict[str, float] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("section") != "config":
                continue
            key = row.get("key", "")
            hz = row.get("horizon", "")
            val = row.get("value", "")
            if key == "min_n_independent" and hz:
                per_n[hz] = int(float(val))
            elif key == "min_weighted_ess" and hz:
                per_ess[hz] = float(val)
            elif key in ("top_k", "base_days"):
                simple[key] = int(float(val))
            elif key in ("sigma", "half_life_days", "drift_z_threshold"):
                simple[key] = float(val)
    if per_n:
        simple["min_n_independent"] = per_n
    if per_ess:
        simple["min_weighted_ess"] = per_ess
    return simple


def feature_schema(df: pd.DataFrame) -> List[str]:
    fs = [c[len("feature__") :] for c in df.columns if c.startswith("feature__")]
    if not fs:
        raise ValueError("No feature__* columns found")
    return fs


def row_features(row: pd.Series, schema: Iterable[str]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for f in schema:
        v = row.get("feature__" + f)
        if pd.isna(v):
            raise ValueError(f"Missing feature {f} at row {row.name}")
        out[f] = float(v)
    return out


def historical_state(mod, row: pd.Series, schema: List[str]):
    fwd: Dict[str, float] = {}
    avail: Dict[str, Any] = {}
    cross: Dict[str, bool] = {}
    for hz in HORIZONS:
        c = row.get(f"cross_session_{hz}")
        if pd.isna(c):
            raise ValueError(f"cross_session_{hz} missing at row {row.name}")
        cross[hz] = parse_bool(c)
        v = row.get(f"fwd_ret_{hz}")
        a = row.get(f"fwd_available_at_{hz}")
        # Fail closed: a numeric label without availability is not inserted.
        if v is not None and not pd.isna(v) and a is not None and not pd.isna(a):
            fwd[hz] = float(v)
            avail[hz] = aware_dt(a)
    return mod.HistoricalState(
        timestamp=aware_dt(row["timestamp"]),
        timeframe=str(row["timeframe"]),
        secid=str(row["secid"]),
        session_bucket=mod.SessionBucket(str(row["session_bucket"])),
        features=row_features(row, schema),
        cross_session=cross,
        fwd_ret=fwd,
        fwd_available_at=avail,
    )


def descriptor(mod, row: pd.Series, schema: List[str]):
    cross = {hz: parse_bool(row[f"cross_session_{hz}"]) for hz in HORIZONS}
    return mod.MarketDescriptor(
        timestamp=aware_dt(row["timestamp"]),
        timeframe=str(row["timeframe"]),
        secid=str(row["secid"]),
        session_bucket=mod.SessionBucket(str(row["session_bucket"])),
        features=row_features(row, schema),
        will_cross_session=cross,
        current_price=float(row["current_price"]),
        atr=float(row["atr"]),
    )


def choose_horizons(mod, timeframe: str) -> List[str]:
    return [hz for hz in HORIZONS if mod.HORIZON_TF[hz] == timeframe]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--forecaster", required=True, type=Path)
    ap.add_argument("--dataset", required=True, type=Path)
    ap.add_argument("--calibration-csv", type=Path)
    ap.add_argument("--expected-sha256")
    ap.add_argument("--max-cases", type=int, default=0, help="0 = all eligible rows")
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()

    actual_sha = sha256_file(args.forecaster)
    if args.expected_sha256 and actual_sha.lower() != args.expected_sha256.lower():
        raise SystemExit(
            f"SHA256 mismatch: expected={args.expected_sha256} actual={actual_sha}"
        )

    mod = load_module(args.forecaster)
    cfg = mod.ForecasterConfig()
    changes = calibration_from_csv(args.calibration_csv)
    if changes:
        cfg = replace(cfg, **changes)
    cal = mod.TradingCalendar()

    df = read_table(args.dataset).copy()
    required = {"timestamp", "timeframe", "session_bucket", "secid", "current_price", "atr"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise SystemExit(f"Dataset missing required columns: {missing}")
    schema = feature_schema(df)
    df["_ts"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values(["_ts", "secid", "timeframe"]).reset_index(drop=True)

    histories = [historical_state(mod, row, schema) for _, row in df.iterrows()]
    # One forecaster per secid: v11 contract keeps per-instrument pools isolated.
    by_secid: Dict[str, Any] = {}
    for secid in sorted(df["secid"].astype(str).unique()):
        fc = mod.Forecaster(cfg, cal)
        fc.set_feature_schema(schema)
        fc.history = [h for h in histories if h.secid == secid]
        by_secid[secid] = fc

    records: List[Dict[str, Any]] = []
    for _, row in df.iterrows():
        fc = by_secid[str(row["secid"])]
        cur = descriptor(mod, row, schema)
        for hz in choose_horizons(mod, cur.timeframe):
            card = fc.forecast(cur, hz)
            actual = row.get(f"fwd_ret_{hz}")
            actual_v = None if actual is None or pd.isna(actual) else float(actual)
            records.append(
                {
                    "timestamp": str(row["timestamp"]),
                    "secid": str(row["secid"]),
                    "timeframe": cur.timeframe,
                    "horizon": hz,
                    "gate_status": card.gate_status,
                    "n_independent": card.n_independent,
                    "weighted_ess": card.weighted_ess,
                    "center": card.center,
                    "q10": card.q10,
                    "q90": card.q90,
                    "actual_fwd_ret": actual_v,
                    "data_unmatured_fwd": card.data_unmatured_fwd,
                    "max_abs_z": card.max_abs_z,
                    "drift_flag": card.drift_flag,
                }
            )
            if args.max_cases and len(records) >= args.max_cases:
                break
        if args.max_cases and len(records) >= args.max_cases:
            break

    out = pd.DataFrame(records)
    summary: Dict[str, Any] = {
        "forecaster_sha256": actual_sha,
        "config": cfg.to_dict(),
        "dataset": str(args.dataset),
        "dataset_rows": int(len(df)),
        "forecast_cases": int(len(out)),
        "feature_schema": schema,
        "gate_counts": out["gate_status"].value_counts(dropna=False).to_dict() if len(out) else {},
        "by_horizon": {},
    }
    for hz, g in out.groupby("horizon"):
        valid = g[g["actual_fwd_ret"].notna() & g["center"].notna()].copy()
        if len(valid):
            valid["covered"] = (valid["actual_fwd_ret"] >= valid["q10"]) & (valid["actual_fwd_ret"] <= valid["q90"])
            valid["abs_error"] = (valid["center"] - valid["actual_fwd_ret"]).abs()
            valid["sign_ok"] = (valid["center"].apply(lambda x: 1 if x > 0 else -1 if x < 0 else 0) ==
                                valid["actual_fwd_ret"].apply(lambda x: 1 if x > 0 else -1 if x < 0 else 0))
        summary["by_horizon"][hz] = {
            "cases": int(len(g)),
            "pass_rate": float((g["gate_status"] == "PASS").mean()) if len(g) else None,
            "median_ess": float(g["weighted_ess"].median()) if len(g) else None,
            "valid_actual": int(len(valid)),
            "coverage_q10_q90": float(valid["covered"].mean()) if len(valid) else None,
            "median_abs_error_atr": float(valid["abs_error"].median()) if len(valid) else None,
            "sign_accuracy": float(valid["sign_ok"].mean()) if len(valid) else None,
        }

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.output.suffix.lower() == ".csv":
            out.to_csv(args.output, index=False)
        else:
            args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
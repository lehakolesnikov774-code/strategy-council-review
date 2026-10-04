"""forecaster_v11_marfa.py - цельный модуль прогноза по аналогам.

v11 Marfa (v10 + финальная календарная регрессия):
- BLOCKER: возвращён horizon-specific fwd_available_at (maturity contract из v8).
  Аналог участвует только при fwd_available_at[horizon] <= current.timestamp.
  Отсутствие ключа - fail-closed (data_missing_fwd);
  незрелая метка - отдельный счётчик data_unmatured_fwd, в прогноз не попадает.
- MAJOR: валидатор таблиц порогов принимает любой Mapping (включая
  MappingProxyType), поэтому dataclasses.replace(config, ...) работает;
  добавлен ForecasterConfig.to_dict() - сериализуемый снапшот для журналов
  walk-forward (JSON round-trip).

Сохранено из v9: per-instrument pools (обязательный secid), timezone-aware
контракты (UTC transport, exchange-local calendar), drift только на
достаточном пуле, per-horizon N/ESS gates в одном конфиге, каноническая
feature schema, fwd-фильтр до dedup, дискретные взвешенные квантили,
immutable config, empty forecast -> None + reason.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, date, time, timezone
from enum import Enum
from types import MappingProxyType
from typing import Dict, FrozenSet, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

import numpy as np

__all__ = [
    "DataContractError", "HorizonError", "SessionBucket",
    "ForecasterConfig", "TradingCalendar", "HistoricalState",
    "MarketDescriptor", "ForecastCard", "Standardizer", "Forecaster",
    "weighted_quantile", "HORIZONS", "HORIZON_TF", "HORIZON_MINUTES",
]


class DataContractError(ValueError):
    """Нарушение контракта данных."""


class HorizonError(DataContractError):
    """Несовместимость горизонта прогноза и таймфрейма данных."""


class SessionBucket(Enum):
    OPEN = "open"
    MID = "mid"
    PRE_CLOSE = "pre_close"
    EVENING = "evening"


HORIZONS: Tuple[str, ...] = ("30m", "60m", "90m", "120m")
HORIZON_TF: Dict[str, str] = {"30m": "M5", "60m": "M15", "90m": "M15", "120m": "M15"}
HORIZON_MINUTES: Dict[str, int] = {"30m": 30, "60m": 60, "90m": 90, "120m": 120}


def _finite_positive(name: str, value) -> None:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value <= 0):
        raise DataContractError(f"{name} must be finite > 0, got {value!r}")


def _finite_number(name: str, value) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise DataContractError(f"{name} must be finite number, got {value!r}")


def _strict_bool(name: str, value) -> None:
    if type(value) is not bool:
        raise DataContractError(f"{name} must be strict bool, got {type(value).__name__}")


def _strict_positive_int(name: str, value) -> None:
    if type(value) is not int or value <= 0:
        raise DataContractError(f"{name} must be int > 0 (bool forbidden), got {value!r}")


def _aware_dt(name: str, value) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise DataContractError(f"{name} must be timezone-aware datetime, got {value!r}")


def _validate_horizon_table(name: str, value, kind: str) -> MappingProxyType:
    """Принимает любой Mapping (dict, MappingProxyType, ...), не только dict."""
    if not isinstance(value, Mapping):
        raise DataContractError(f"{name} must be a Mapping of horizon -> {kind}, got {type(value).__name__}")
    keys = set(value.keys())
    if keys != set(HORIZONS):
        raise DataContractError(f"{name} must cover exactly {sorted(HORIZONS)}, got {sorted(keys)}")
    out: Dict[str, float] = {}
    for hz in HORIZONS:
        v = value[hz]
        if kind == "int":
            _strict_positive_int(f"{name}[{hz}]", v)
        else:
            if (isinstance(v, bool) or not isinstance(v, (int, float))
                    or not math.isfinite(v) or v < 0):
                raise DataContractError(f"{name}[{hz}] must be finite number >= 0, got {v!r}")
        out[hz] = v
    return MappingProxyType(out)


@dataclass(frozen=True)
class ForecasterConfig:
    """Immutable конфиг инстанса. Пороги N/ESS - per-horizon таблицы."""
    top_k: int = 20
    drift_z_threshold: float = 3.0
    half_life_days: float = 15.0
    sigma: float = 1.0
    base_days: int = 180
    min_n_independent: Mapping = field(default_factory=lambda: MappingProxyType(
        {"30m": 10, "60m": 10, "90m": 10, "120m": 10}))
    min_weighted_ess: Mapping = field(default_factory=lambda: MappingProxyType(
        {"30m": 6.0, "60m": 6.0, "90m": 6.0, "120m": 6.0}))

    def __post_init__(self):
        _strict_positive_int("top_k", self.top_k)
        _strict_positive_int("base_days", self.base_days)
        for n in ("drift_z_threshold", "half_life_days", "sigma"):
            _finite_positive(n, getattr(self, n))
        object.__setattr__(self, "min_n_independent",
                           _validate_horizon_table("min_n_independent", self.min_n_independent, "int"))
        object.__setattr__(self, "min_weighted_ess",
                           _validate_horizon_table("min_weighted_ess", self.min_weighted_ess, "float"))
        for hz in HORIZONS:
            if self.min_n_independent[hz] > self.top_k:
                raise DataContractError(
                    f"min_n_independent[{hz}] ({self.min_n_independent[hz]}) must be <= top_k ({self.top_k})")
            if self.min_weighted_ess[hz] > self.top_k:
                raise DataContractError(
                    f"min_weighted_ess[{hz}] ({self.min_weighted_ess[hz]}) must be <= top_k ({self.top_k})")

    def to_dict(self) -> Dict:
        """JSON-сериализуемый снапшот для журналирования walk-forward."""
        return {
            "top_k": self.top_k,
            "base_days": self.base_days,
            "drift_z_threshold": self.drift_z_threshold,
            "half_life_days": self.half_life_days,
            "sigma": self.sigma,
            "min_n_independent": dict(self.min_n_independent),
            "min_weighted_ess": dict(self.min_weighted_ess),
        }


@dataclass(frozen=True)
class TradingCalendar:
    """Единый источник торгового времени: cutoff и freshness.

    Контракт B: transport/storage timezone = UTC (aware); календарь сам
    конвертирует в exchange-local перед расчётом сессий/дней.
    Naive datetime -> DataContractError.
    """
    exchange_tz: str = "Europe/Moscow"
    sessions: Tuple[Tuple[int, int], ...] = ((600, 1125), (1140, 1430))
    holidays: FrozenSet[date] = frozenset()

    def __post_init__(self):
        try:
            object.__setattr__(self, "tzinfo", ZoneInfo(self.exchange_tz))
        except Exception:
            raise DataContractError(f"unknown exchange timezone {self.exchange_tz!r}")
        if not self.sessions:
            raise DataContractError("sessions must be non-empty")
        for s, e in self.sessions:
            if not (isinstance(s, int) and isinstance(e, int) and 0 <= s < e <= 1440):
                raise DataContractError(f"bad session window {(s, e)}")

    @property
    def normal_session_minutes(self) -> int:
        return sum(e - s for s, e in self.sessions)

    def _to_local(self, dt: datetime) -> datetime:
        _aware_dt("timestamp", dt)
        return dt.astimezone(self.tzinfo)

    def is_trading_day(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self.holidays

    def trading_minutes_between(self, a: datetime, b: datetime) -> int:
        """Реально прошедшие торговые минуты по сессионным окнам (exchange-local)."""
        la, lb = self._to_local(a), self._to_local(b)
        if lb <= la:
            return 0
        total = 0
        day = la.date()
        one = timedelta(days=1)
        while day <= lb.date():
            if self.is_trading_day(day):
                base = datetime.combine(day, time.min, tzinfo=self.tzinfo)
                for s, e in self.sessions:
                    lo = max(base + timedelta(minutes=s), la)
                    hi = min(base + timedelta(minutes=e), lb)
                    if hi > lo:
                        total += int((hi - lo).total_seconds() // 60)
            day += one
        return total

    def shift_trading_days(self, dt: datetime, offset_days: int) -> datetime:
        """Сдвиг на N торговых дней (не календарных). Возвращает aware datetime."""
        if type(offset_days) is not int:
            raise DataContractError("offset_days must be int")
        local = self._to_local(dt)
        if offset_days == 0:
            return local
        direction = -1 if offset_days < 0 else 1
        remaining = abs(offset_days)
        cur = local.date()
        step = timedelta(days=1)
        while remaining > 0:
            cur = cur + direction * step
            if self.is_trading_day(cur):
                remaining -= 1
        return datetime.combine(cur, local.time(), tzinfo=self.tzinfo)


@dataclass
class HistoricalState:
    timestamp: datetime
    timeframe: str
    secid: str
    session_bucket: SessionBucket
    features: Dict[str, float]
    cross_session: Dict[str, bool]
    fwd_ret: Dict[str, float]
    fwd_available_at: Dict[str, datetime] = field(default_factory=dict)

    def __post_init__(self):
        _aware_dt("timestamp", self.timestamp)
        if not isinstance(self.secid, str) or not self.secid.strip():
            raise DataContractError("secid must be non-empty string")
        if not isinstance(self.timeframe, str) or not self.timeframe.strip():
            raise DataContractError("timeframe must be non-empty string")
        if not isinstance(self.session_bucket, SessionBucket):
            raise DataContractError("session_bucket must be SessionBucket")
        for hz, v in self.cross_session.items():
            _strict_bool(f"cross_session[{hz}]", v)
        for hz, v in self.fwd_ret.items():
            _finite_number(f"fwd_ret[{hz}]", v)
        for hz, v in self.fwd_available_at.items():
            _aware_dt(f"fwd_available_at[{hz}]", v)
        for k, v in self.features.items():
            _finite_number(f"features[{k}]", v)


@dataclass
class MarketDescriptor:
    timestamp: datetime
    timeframe: str
    secid: str
    session_bucket: SessionBucket
    features: Dict[str, float]
    will_cross_session: Dict[str, bool]
    current_price: float
    atr: float

    def __post_init__(self):
        _aware_dt("timestamp", self.timestamp)
        if not isinstance(self.secid, str) or not self.secid.strip():
            raise DataContractError("secid must be non-empty string")
        if not isinstance(self.timeframe, str) or not self.timeframe.strip():
            raise DataContractError("timeframe must be non-empty string")
        if not isinstance(self.session_bucket, SessionBucket):
            raise DataContractError("session_bucket must be SessionBucket")
        for hz, v in self.will_cross_session.items():
            _strict_bool(f"will_cross_session[{hz}]", v)
        _finite_positive("current_price", self.current_price)
        _finite_positive("atr", self.atr)
        for k, v in self.features.items():
            _finite_number(f"features[{k}]", v)


@dataclass
class ForecastCard:
    horizon: str
    center: Optional[float]        # взвешенная медиана
    expected: Optional[float]      # взвешенное среднее (диагностика)
    q10: Optional[float]
    q90: Optional[float]
    price_center: Optional[float]
    price_low: Optional[float]
    price_high: Optional[float]
    n_independent: int
    weighted_ess: float
    ess_ratio: float
    weight_concentration_top10: float
    n_before_fwd_filter: int = 0
    data_missing_features: int = 0
    data_missing_fwd: int = 0
    data_unmatured_fwd: int = 0
    max_abs_z: Optional[float] = None
    drift_flag: Optional[bool] = None
    drift_status: Optional[str] = None   # "OK" | "INSUFFICIENT_SAMPLE"
    gate_status: str = "PASS"            # PASS/FAIL_N/FAIL_ESS/FAIL_BOTH/NO_DATA/NO_EFFECTIVE_WEIGHT
    reason: Optional[str] = None


class Standardizer:
    """Стандартизация по канонической схеме. zero-variance -> std=1."""

    def __init__(self, feature_schema: List[str]):
        self.feature_schema = list(feature_schema)
        self.means: Dict[str, float] = {}
        self.stds: Dict[str, float] = {}

    def fit(self, pool: Iterable[Dict[str, float]]) -> None:
        values: Dict[str, List[float]] = {f: [] for f in self.feature_schema}
        for row in pool:
            for f in self.feature_schema:
                v = row.get(f)
                if v is not None and math.isfinite(v):
                    values[f].append(float(v))
        for f in self.feature_schema:
            vals = values[f]
            if not vals:
                self.means[f] = 0.0
                self.stds[f] = 1.0
                continue
            m = sum(vals) / len(vals)
            var = sum((x - m) ** 2 for x in vals) / len(vals)
            std = math.sqrt(var)
            self.means[f] = m
            self.stds[f] = std if std > 0 else 1.0

    def transform(self, row: Dict[str, float]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for f in self.feature_schema:
            v = row.get(f)
            out[f] = (v - self.means[f]) / self.stds[f] if (v is not None and math.isfinite(v)) else float("nan")
        return out


def weighted_quantile(values, weights, q: float) -> float:
    """Дискретный взвешенный эмпирический квантиль.

    Возвращает первый v[i] (по возрастанию value), для которого
    накопленный вес >= q * total_weight. Без интерполяции: при равных
    весах сводится к обычной медиане.
    """
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    if values.size == 0:
        raise ValueError("weighted_quantile on empty input")
    if values.size != weights.size:
        raise ValueError("values and weights must have the same length")
    if (isinstance(q, bool) or not isinstance(q, (int, float))
            or not math.isfinite(q) or not (0.0 <= q <= 1.0)):
        raise DataContractError(f"q must be finite in [0, 1], got {q!r}")
    if np.any(~np.isfinite(weights)) or np.any(weights < 0):
        raise DataContractError("weights must be finite and non-negative")
    if np.any(~np.isfinite(values)):
        raise DataContractError("values must be finite")
    order = np.argsort(values, kind="stable")
    v = values[order]
    w = weights[order]
    cw = np.cumsum(w)
    total = float(cw[-1])
    if total <= 0:
        raise DataContractError("total weight must be > 0")
    target = q * total
    i = int(np.searchsorted(cw, target, side="left"))
    return float(v[min(i, len(v) - 1)])


class Forecaster:
    HORIZON_TF = HORIZON_TF
    HORIZON_MINUTES = HORIZON_MINUTES
    HORIZONS = HORIZONS

    def __init__(self, config: ForecasterConfig, calendar: TradingCalendar):
        if not isinstance(config, ForecasterConfig):
            raise DataContractError("config must be ForecasterConfig")
        if not isinstance(calendar, TradingCalendar):
            raise DataContractError("calendar must be TradingCalendar")
        self.config = config
        self.calendar = calendar
        self.history: List[HistoricalState] = []
        self.feature_schema: List[str] = []

    def set_feature_schema(self, schema: List[str]) -> None:
        if not schema:
            raise DataContractError("feature_schema must be non-empty")
        self.feature_schema = list(schema)

    def load_history(self, raw_history: Iterable[HistoricalState], now: datetime) -> None:
        """Cutoff - ровно base_days ТОРГОВЫХ дней через единый календарь."""
        cutoff = self.calendar.shift_trading_days(now, -int(self.config.base_days))
        self.history = [h for h in raw_history if cutoff <= h.timestamp <= now]

    @staticmethod
    def _rms_distance(a: Dict[str, float], b: Dict[str, float]) -> float:
        sq = 0.0
        for k in a:
            va, vb = a[k], b[k]
            if not (math.isfinite(va) and math.isfinite(vb)):
                return float("inf")
            sq += (va - vb) ** 2
        return math.sqrt(sq / max(len(a), 1))

    @staticmethod
    def _overlaps(a: HistoricalState, b: HistoricalState, window_minutes: int) -> bool:
        return abs((a.timestamp - b.timestamp).total_seconds()) < window_minutes * 60

    def _freshness_weight(self, ts: datetime, now: datetime) -> float:
        minutes = self.calendar.trading_minutes_between(ts, now)
        age_units = minutes / self.calendar.normal_session_minutes
        return 0.5 ** (age_units / self.config.half_life_days)

    def _similarity_kernel(self, dist: float) -> float:
        return math.exp(-0.5 * (dist / self.config.sigma) ** 2)

    def _failure_card(self, horizon: str, gate: str, reason: str,
                      n_independent: int = 0, ess: float = 0.0,
                      data_missing_features: int = 0, data_missing_fwd: int = 0,
                      data_unmatured_fwd: int = 0, n_before_fwd_filter: int = 0) -> ForecastCard:
        return ForecastCard(
            horizon=horizon, center=None, expected=None, q10=None, q90=None,
            price_center=None, price_low=None, price_high=None,
            n_independent=n_independent, weighted_ess=ess, ess_ratio=0.0,
            weight_concentration_top10=0.0,
            n_before_fwd_filter=n_before_fwd_filter,
            data_missing_features=data_missing_features,
            data_missing_fwd=data_missing_fwd,
            data_unmatured_fwd=data_unmatured_fwd,
            max_abs_z=None, drift_flag=None, drift_status=None,
            gate_status=gate, reason=reason,
        )

    def forecast(self, current: MarketDescriptor, horizon: str) -> ForecastCard:
        expected_tf = self.HORIZON_TF.get(horizon)
        if expected_tf is None:
            raise HorizonError(f"unknown horizon {horizon!r}")
        if current.timeframe != expected_tf:
            raise HorizonError(
                f"TF mismatch: current={current.timeframe}, "
                f"required={expected_tf} for horizon={horizon}")
        if not self.feature_schema:
            raise DataContractError("feature_schema not set")
        missing = [f for f in self.feature_schema
                   if f not in current.features or not math.isfinite(current.features[f])]
        if missing:
            raise DataContractError(f"current descriptor missing schema features: {missing}")
        wcs = current.will_cross_session.get(horizon)
        if wcs is None:
            raise DataContractError(f"will_cross_session[{horizon}] missing in current descriptor")

        # 1) secid -> TF -> bucket -> cross_session (DATA_MISSING не превращается в False)
        eligible: List[HistoricalState] = []
        for h in self.history:
            if h.timestamp > current.timestamp:
                continue
            if h.secid != current.secid:
                continue
            if h.timeframe != expected_tf:
                continue
            if h.session_bucket != current.session_bucket:
                continue
            cs = h.cross_session.get(horizon)
            if cs is None:
                continue  # DATA_MISSING
            if cs != wcs:
                continue
            eligible.append(h)

        # 2) каноническая completeness ДО fitting scaler
        complete: List[HistoricalState] = []
        data_missing_features = 0
        for h in eligible:
            if all(f in h.features and math.isfinite(h.features[f])
                   for f in self.feature_schema):
                complete.append(h)
            else:
                data_missing_features += 1

        std = Standardizer(self.feature_schema)
        std.fit([h.features for h in complete])
        cur_feat = std.transform(current.features)

        valid: List[Tuple[HistoricalState, float]] = []
        for h in complete:
            hf = std.transform(h.features)
            d = self._rms_distance(cur_feat, hf)
            valid.append((h, d))

        n_before_fwd_filter = len(valid)

        # 3) валидный fwd_ret + maturity (BLOCKER v10): только зрелые метки
        usable: List[Tuple[HistoricalState, float]] = []
        data_missing_fwd = 0
        data_unmatured_fwd = 0
        for h, d in valid:
            r = h.fwd_ret.get(horizon)
            if r is None or not math.isfinite(r):
                data_missing_fwd += 1
                continue
            av = h.fwd_available_at.get(horizon)
            if av is None:
                data_missing_fwd += 1  # fail-closed: нет доступности - нет метки
                continue
            if av > current.timestamp:
                data_unmatured_fwd += 1  # метка из будущего - look-ahead guard
                continue
            usable.append((h, d))

        # 4) horizon-aware overlap-dedup: жадно по dist, лучший аналог выживает
        horizon_min = self.HORIZON_MINUTES[horizon]
        usable.sort(key=lambda p: p[1])
        kept: List[Tuple[HistoricalState, float]] = []
        for h, d in usable:
            if not any(self._overlaps(h, kh, horizon_min) for kh, _ in kept):
                kept.append((h, d))

        # 5) top-k
        top = kept[:self.config.top_k]

        if not top:
            return self._failure_card(
                horizon, "NO_DATA",
                f"no eligible analogs with valid mature fwd_ret[{horizon}]",
                data_missing_features=data_missing_features,
                data_missing_fwd=data_missing_fwd,
                data_unmatured_fwd=data_unmatured_fwd,
                n_before_fwd_filter=n_before_fwd_filter)

        # 6) weights = freshness (торг. минуты) * similarity kernel
        now = current.timestamp
        weights_list, outcomes, top_feats = [], [], []
        for h, d in top:
            fw = self._freshness_weight(h.timestamp, now)
            sw = self._similarity_kernel(d)
            weights_list.append(fw * sw)
            outcomes.append(h.fwd_ret[horizon])
            top_feats.append(std.transform(h.features))

        weights = np.array(weights_list, dtype=float)
        outcomes = np.array(outcomes, dtype=float)
        n_independent = len(top)
        s = float(weights.sum())
        if s <= 0:
            return self._failure_card(
                horizon, "NO_EFFECTIVE_WEIGHT", "sum of weights underflowed to zero",
                n_independent=n_independent,
                data_missing_features=data_missing_features,
                data_missing_fwd=data_missing_fwd,
                data_unmatured_fwd=data_unmatured_fwd,
                n_before_fwd_filter=n_before_fwd_filter)

        ess = float(s * s / np.square(weights).sum())
        ess_ratio = ess / n_independent
        sorted_w = np.sort(weights)[::-1]
        conc = float(sorted_w[:10].sum() / s)

        # 7) дискретные квантили; центр = медиана; ожидание отдельно
        q10 = weighted_quantile(outcomes, weights, 0.10)
        q50 = weighted_quantile(outcomes, weights, 0.50)
        q90 = weighted_quantile(outcomes, weights, 0.90)
        expected = float(np.average(outcomes, weights=weights))
        center = q50

        min_n = int(self.config.min_n_independent[horizon])
        min_ess = float(self.config.min_weighted_ess[horizon])
        gate = "PASS"
        fail_n = n_independent < min_n
        fail_ess = ess < min_ess
        if fail_n and fail_ess:
            gate = "FAIL_BOTH"
        elif fail_n:
            gate = "FAIL_N"
        elif fail_ess:
            gate = "FAIL_ESS"

        # 8) drift только на достаточном пуле (решение C)
        if gate == "PASS":
            zs = []
            for f in self.feature_schema:
                vals = np.array([tf[f] for tf in top_feats], dtype=float)
                wm = float(np.average(vals, weights=weights))
                wvar = float(np.average((vals - wm) ** 2, weights=weights))
                wstd = math.sqrt(wvar)
                cv = cur_feat[f]
                if wstd <= 0:
                    z = 0.0 if abs(cv - wm) <= 1e-12 else float("inf")
                else:
                    z = abs(cv - wm) / wstd
                zs.append(z)
            max_abs_z = max(zs) if zs else 0.0
            drift_flag = bool(max_abs_z > self.config.drift_z_threshold)
            drift_status = "OK"
        else:
            max_abs_z = None
            drift_flag = None
            drift_status = "INSUFFICIENT_SAMPLE"

        price_c = current.current_price + current.atr * center
        price_l = current.current_price + current.atr * q10
        price_h = current.current_price + current.atr * q90

        return ForecastCard(
            horizon=horizon, center=center, expected=expected, q10=q10, q90=q90,
            price_center=price_c, price_low=price_l, price_high=price_h,
            n_independent=n_independent, weighted_ess=ess, ess_ratio=ess_ratio,
            weight_concentration_top10=conc,
            n_before_fwd_filter=n_before_fwd_filter,
            data_missing_features=data_missing_features,
            data_missing_fwd=data_missing_fwd,
            data_unmatured_fwd=data_unmatured_fwd,
            max_abs_z=max_abs_z, drift_flag=drift_flag, drift_status=drift_status,
            gate_status=gate, reason=None,
        )

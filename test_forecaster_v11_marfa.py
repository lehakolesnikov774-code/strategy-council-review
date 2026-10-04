"""test_forecaster_v11_marfa.py - adversarial + regression suite для forecaster_v11_marfa.

Совместим с pytest (обычные функции test_* с assert) и гоняется напрямую:
    python test_forecaster_v7_marfa.py
"""
import math
import json
import numpy as np
import sys
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, date, timezone

import forecaster_v11_marfa as fv6
from forecaster_v11_marfa import (
    Forecaster, ForecasterConfig, TradingCalendar, HistoricalState,
    MarketDescriptor, SessionBucket, DataContractError, HorizonError,
)

CAL = TradingCalendar()
NOW = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)  # 12:00 Europe/Moscow


def approx(a, b, tol=1e-6):
    return abs(a - b) < tol


def _horizon_map(value, cast=float):
    if isinstance(value, dict):
        return value
    return {hz: cast(value) for hz in fv6.HORIZONS}


def _cfg_kwargs(cfg):
    cfg = dict(cfg)
    if "min_n_independent" in cfg and not isinstance(cfg["min_n_independent"], dict):
        cfg["min_n_independent"] = _horizon_map(cfg["min_n_independent"], int)
    if "min_weighted_ess" in cfg and not isinstance(cfg["min_weighted_ess"], dict):
        cfg["min_weighted_ess"] = _horizon_map(cfg["min_weighted_ess"], float)
    return cfg


def make_current(tf="M5", bucket=SessionBucket.OPEN, features=None,
                 wcs=None, price=100.0, atr=1.0, ts=None, secid="SBER"):
    return MarketDescriptor(
        timestamp=ts or NOW, timeframe=tf, secid=secid, session_bucket=bucket,
        features=features if features is not None else {"f1": 0.0},
        will_cross_session=wcs if wcs is not None else {"30m": False, "60m": False, "90m": False, "120m": False},
        current_price=price, atr=atr,
    )


def make_hist(ts, tf="M5", bucket=SessionBucket.OPEN, features=None,
              cross=None, fwd=None, available=None, secid="SBER"):
    fwd_map = fwd if fwd is not None else {"30m": 0.01}
    available_map = available if available is not None else {k: ts for k in fwd_map}
    return HistoricalState(
        timestamp=ts, timeframe=tf, secid=secid, session_bucket=bucket,
        features=features if features is not None else {"f1": 0.0},
        cross_session=cross if cross is not None else {"30m": False, "60m": False, "90m": False, "120m": False},
        fwd_ret=fwd_map, fwd_available_at=available_map,
    )


def run(hist_states, current=None, horizon="30m", **cfg):
    f = Forecaster(ForecasterConfig(**_cfg_kwargs(cfg)), CAL)
    f.set_feature_schema(["f1"])
    f.load_history(hist_states, NOW)
    return f.forecast(current or make_current(), horizon)


# ---------- adversarial ----------

def test_a1_missing_feature_no_crash():
    h = make_hist(NOW - timedelta(minutes=10), features={"f1": 1.1})  # нет f2
    f = Forecaster(ForecasterConfig(), CAL)
    f.set_feature_schema(["f1", "f2"])
    f.load_history([h], NOW)
    card = f.forecast(make_current(features={"f1": 1.0, "f2": 2.0}), "30m")
    assert card.data_missing_features == 1
    assert card.n_independent == 0
    assert card.center is None and card.q10 is None and card.q90 is None
    assert card.gate_status == "NO_DATA" and card.reason is not None


def test_a2_distance_uses_only_schema():
    cur = make_current(features={"f1": 1.0, "noise": 100.0})
    h1 = make_hist(NOW - timedelta(minutes=10), features={"f1": 1.1, "noise": 100.0}, fwd={"30m": 0.07})
    h2 = make_hist(NOW - timedelta(minutes=10), features={"f1": 1.1, "noise": -100.0}, fwd={"30m": 0.07})
    c1 = run([h1], cur)
    c2 = run([h2], cur)
    assert approx(c1.center, c2.center) and approx(c1.expected, c2.expected)
    assert c1.n_independent == c2.n_independent == 1


def test_a3_backfill_unlabeled_not_displacing():
    # h1/h2 - ближайшие, но без fwd_ret; h1 к тому же перекрывается с h3.
    # unlabeled исключается ДО dedup и не вытесняет валидный аналог.
    h1 = make_hist(NOW - timedelta(minutes=10), fwd={})
    h2 = make_hist(NOW - timedelta(minutes=20), features={"f1": 0.1}, fwd={})
    h3 = make_hist(NOW - timedelta(minutes=30), features={"f1": 0.2}, fwd={"30m": 0.05})
    card = run([h1, h2, h3], top_k=2, min_n_independent=1, min_weighted_ess=0.0)
    assert card.n_before_fwd_filter == 3
    assert card.data_missing_fwd == 2
    assert card.n_independent == 1
    assert approx(card.center, 0.05)


def test_a4_instance_isolation_no_global_setters():
    assert not hasattr(fv6, "set_min_n_independent")
    assert not hasattr(fv6, "set_min_weighted_ess")
    c1 = ForecasterConfig(min_n_independent=_horizon_map(10, int))
    c2 = replace(c1, min_n_independent=_horizon_map(19, int))
    f1, f2 = Forecaster(c1, CAL), Forecaster(c2, CAL)
    assert f1.config.min_n_independent["30m"] == 10
    assert f2.config.min_n_independent["30m"] == 19
    try:
        c1.min_n_independent = _horizon_map(5, int)
        assert False, "frozen config must not be mutable"
    except FrozenInstanceError:
        pass


def test_a5_bool_contract_fail_closed():
    bad_values = ["False", 0, 1, None, "true"]
    for v in bad_values:
        try:
            make_hist(NOW - timedelta(minutes=10), cross={"30m": v})
            assert False, f"cross_session={v!r} must raise"
        except DataContractError:
            pass
        try:
            make_current(wcs={"30m": v})
            assert False, f"will_cross_session={v!r} must raise"
        except DataContractError:
            pass


def test_a6_config_validation_and_sigma_effect():
    for kwargs in [{"sigma": 0.0}, {"sigma": -1.0}, {"half_life_days": 0.0},
                   {"top_k": 0}, {"min_n_independent": {"30m": 0, "60m": 10, "90m": 10, "120m": 10}}, {"base_days": 0},
                   {"drift_z_threshold": 0.0}]:
        try:
            ForecasterConfig(**kwargs)
            assert False, f"{kwargs} must raise"
        except DataContractError:
            pass
    # sigma реально влияет на веса
    hist = [make_hist(NOW - timedelta(minutes=40 * i), features={"f1": float(i)},
                      fwd={"30m": 0.01}) for i in range(5)]
    cur = make_current()
    c_small = run(hist, cur, sigma=0.5)
    c_big = run(hist, cur, sigma=5.0)
    assert c_small.weighted_ess < c_big.weighted_ess


def test_a7_tf_mismatch_horizon_error():
    try:
        run([make_hist(NOW - timedelta(minutes=10), tf="M15")],
            make_current(tf="M15"), "30m")
        assert False, "M15 current with 30m horizon must raise"
    except HorizonError:
        pass
    # корректная пара M15/60m работает
    hist = [make_hist(NOW - timedelta(minutes=60), tf="M15",
                      cross={"60m": False}, fwd={"60m": 0.01})]
    card = run(hist, make_current(tf="M15", wcs={"60m": False}), "60m")
    assert card.n_independent == 1


def test_a8_quantiles_statistical_meaning():
    hist = []
    for i in range(29):
        hist.append(make_hist(NOW - timedelta(minutes=40 * i), fwd={"30m": 0.0}))
    hist.append(make_hist(NOW - timedelta(minutes=40 * 29), fwd={"30m": 100.0}))
    card = run(hist, top_k=100)
    assert approx(card.q90, 0.0)
    assert approx(card.center, 0.0)
    assert 3.0 < card.expected < 4.0
    assert card.q10 <= card.center <= card.q90  # математически, не заплаткой


# ---------- regression ----------

def test_r1_30m_never_m15():
    card = run([make_hist(NOW - timedelta(minutes=10), tf="M15")])
    assert card.n_independent == 0 and card.gate_status == "NO_DATA"


def test_r2_60m_never_m5():
    hist = [make_hist(NOW - timedelta(minutes=60), tf="M5", cross={"60m": False}, fwd={"60m": 0.01})]
    card = run(hist, make_current(tf="M15", wcs={"60m": False}), "60m")
    assert card.n_independent == 0 and card.gate_status == "NO_DATA"


def test_r3_session_bucket_isolation():
    card = run([make_hist(NOW - timedelta(minutes=10), bucket=SessionBucket.MID)])
    assert card.n_independent == 0 and card.gate_status == "NO_DATA"


def test_r4_cross_session_horizon_specific_and_missing():
    cur = make_current(wcs={"30m": True})
    h_match = make_hist(NOW - timedelta(minutes=60), cross={"30m": True}, fwd={"30m": 0.01})
    h_mismatch = make_hist(NOW - timedelta(minutes=120), cross={"30m": False}, fwd={"30m": 0.99})
    h_missing = make_hist(NOW - timedelta(minutes=180), cross={"60m": True}, fwd={"30m": 0.99})
    card = run([h_match, h_mismatch, h_missing], cur)
    assert card.n_independent == 1 and approx(card.center, 0.01)


def test_r5_will_cross_session_missing_raises():
    f = Forecaster(ForecasterConfig(), CAL)
    f.set_feature_schema(["f1"])
    f.load_history([make_hist(NOW - timedelta(minutes=10))], NOW)
    cur = make_current(wcs={})  # нет ключа 30m
    try:
        f.forecast(cur, "30m")
        assert False, "missing will_cross_session key must raise"
    except DataContractError:
        pass


def test_r6_best_overlapping_analog_wins():
    # A дальше по времени, но лучше по dist; B ближе по времени, но хуже - проигрывает
    a = make_hist(NOW - timedelta(minutes=20), features={"f1": 0.15}, fwd={"30m": 0.01})
    b = make_hist(NOW - timedelta(minutes=12), features={"f1": 2.1}, fwd={"30m": 0.99})
    card = run([a, b], top_k=10)
    assert card.n_independent == 1
    assert approx(card.center, 0.01)


def test_r7_chain_survives_independent_a_and_c():
    a = make_hist(NOW - timedelta(minutes=10), features={"f1": 0.1}, fwd={"30m": 0.01})
    b = make_hist(NOW - timedelta(minutes=25), features={"f1": 2.0}, fwd={"30m": 0.02})
    c = make_hist(NOW - timedelta(minutes=50), features={"f1": 0.2}, fwd={"30m": 0.03})
    card = run([a, b, c], top_k=10)
    assert card.n_independent == 2
    assert approx(card.center, 0.01)  # медиана из A и C, без B


def test_r8_trading_day_cutoff_boundary():
    # 250 последовательных торговых дней (будни), 12:00
    days = []
    d = date(2026, 10, 2)
    while len(days) < 250:
        if d.weekday() < 5:
            days.append(datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc).replace(hour=9))
        d -= timedelta(days=1)
    days.reverse()
    now = days[-1]
    hist = [make_hist(ts, fwd={"30m": 0.01}) for ts in days]
    f = Forecaster(ForecasterConfig(), CAL)
    f.set_feature_schema(["f1"])
    f.load_history(hist, now)
    kept = sorted(h.timestamp for h in f.history)
    assert days[-181] in kept          # ровно 180 торговых дней назад - внутри пула
    assert days[-182] not in kept      # 181-й торговый день назад - за cutoff
    assert len(kept) == 181            # cutoff-день включительно


def test_r9_price_projection():
    h = make_hist(NOW - timedelta(minutes=10), fwd={"30m": 0.02})
    card = run([h])
    assert approx(card.center, 0.02)
    assert approx(card.price_center, 100.0 + 1.0 * 0.02)
    assert approx(card.price_low, 100.0 + 1.0 * card.q10)
    assert approx(card.price_high, 100.0 + 1.0 * card.q90)


def test_r10_center_within_quantiles():
    hist = [make_hist(NOW - timedelta(minutes=40 * i), fwd={"30m": i * 0.001})
            for i in range(50)]
    card = run(hist, top_k=100)
    assert card.q10 <= card.center <= card.q90
    assert card.center is not None and card.q90 is not None


def test_r11_ess_concentration():
    # свежесть с half_life=2 дня концентрирует вес: ESS заметно меньше N
    hist = [make_hist(NOW - timedelta(days=i), fwd={"30m": 0.01}) for i in range(1, 22)]
    card = run(hist, half_life_days=2.0, top_k=30)
    assert card.n_independent == 21
    assert card.weighted_ess < 0.5 * card.n_independent
    assert card.ess_ratio < 0.5


def test_r12_n_not_inflated_by_missing_fwd():
    hist = [make_hist(NOW - timedelta(minutes=40 * i), fwd={}) for i in range(10)]
    card = run(hist, top_k=10)
    assert card.n_before_fwd_filter == 10
    assert card.data_missing_fwd == 10
    assert card.n_independent == 0
    assert card.gate_status == "NO_DATA"
    assert card.center is None


def test_r13_future_leak_ignored():
    h = make_hist(NOW + timedelta(minutes=10), fwd={"30m": 0.01})
    card = run([h])
    assert card.n_independent == 0 and card.gate_status == "NO_DATA"


def test_r14_calendar_trading_minutes_and_shift():
    fri = datetime(2026, 10, 2, 14, 0, tzinfo=timezone.utc)   # 17:00 Moscow, Friday
    mon = datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc)    # 11:00 Moscow, Monday
    # 105 (до конца осн. сессии) + 290 (вечер) + 60 (утро понедельника)
    assert CAL.trading_minutes_between(fri, mon) == 455
    assert approx(455 / CAL.normal_session_minutes, 0.5583, tol=1e-3)
    assert CAL.shift_trading_days(fri, -1).date() == date(2026, 10, 1)  # четверг
    hol = TradingCalendar(holidays=frozenset({date(2026, 10, 5)}))
    assert hol.shift_trading_days(fri, 1).date() == date(2026, 10, 6)   # праздник пропущен
    assert hol.is_trading_day(date(2026, 10, 3)) is False               # суббота


def test_r15_drift_zero_variance_fail_closed():
    hist = [make_hist(NOW - timedelta(minutes=40 * i), fwd={"30m": 0.01}) for i in range(5)]
    card = run(hist, make_current(features={"f1": 5.0}), top_k=10, min_n_independent=1, min_weighted_ess=0.0)
    assert card.drift_flag is True
    assert math.isinf(card.max_abs_z)          # fail-closed: z = inf, а не тихий пропуск
    card2 = run(hist, make_current(features={"f1": 0.0}), top_k=10, min_n_independent=1, min_weighted_ess=0.0)
    assert card2.drift_flag is False and card2.max_abs_z == 0.0


def test_r16_empty_forecast_no_fake_numbers():
    card = run([make_hist(NOW - timedelta(minutes=10), bucket=SessionBucket.EVENING)])
    assert card.center is None and card.expected is None
    assert card.q10 is None and card.q90 is None
    assert card.price_center is None and card.price_low is None and card.price_high is None
    assert card.gate_status == "NO_DATA" and card.reason is not None


def test_r17_no_effective_weight_fail_closed():
    hist = [make_hist(NOW - timedelta(minutes=40 * i + 1), fwd={"30m": 0.01}) for i in range(20)]
    card = run(hist, half_life_days=1e-9, top_k=10)
    assert card.gate_status == "NO_EFFECTIVE_WEIGHT"
    assert card.center is None and card.reason is not None


def test_m1_weighted_median_equal_weights():
    vals = np.array([0.0, 1.0, 2.0])
    w = np.array([1.0, 1.0, 1.0])
    assert fv6.weighted_quantile(vals, w, 0.5) == 1.0


def test_m2_incomplete_candidate_cannot_pollute_scaler():
    cfg = dict(top_k=10, min_n_independent=_horizon_map(1, int), min_weighted_ess=_horizon_map(0.0, float))
    cur = make_current(features={"f1": 0.0, "f2": 0.0})
    valid = [
        make_hist(NOW - timedelta(minutes=40), features={"f1": 0.0, "f2": 0.0}, fwd={"30m": 0.01}),
        make_hist(NOW - timedelta(minutes=80), features={"f1": 2.0, "f2": 2.0}, fwd={"30m": 0.09}),
    ]
    def go(hist):
        f = Forecaster(ForecasterConfig(**cfg), CAL)
        f.set_feature_schema(["f1", "f2"])
        f.load_history(hist, NOW)
        return f.forecast(cur, "30m")
    a = go(valid)
    incomplete = make_hist(NOW - timedelta(minutes=120), features={"f1": 10000.0}, fwd={"30m": 0.99})
    b = go(valid + [incomplete])
    assert approx(a.center, b.center)
    assert approx(a.expected, b.expected)
    assert approx(a.weighted_ess, b.weighted_ess)
    assert b.data_missing_features == a.data_missing_features + 1


def test_m3_integer_config_contract():
    for kwargs in ({"top_k": 2.5},
                   {"min_n_independent": {"30m": 2.5, "60m": 10, "90m": 10, "120m": 10}},
                   {"base_days": 180.5}, {"top_k": True},
                   {"min_n_independent": {"30m": True, "60m": 10, "90m": 10, "120m": 10}},
                   {"base_days": True}):
        try:
            ForecasterConfig(**kwargs)
            assert False, f"{kwargs} must raise"
        except DataContractError:
            pass



def test_m4_forward_label_maturity_blocks_lookahead():
    cur = make_current(ts=NOW)
    immature = make_hist(
        NOW - timedelta(minutes=10),
        fwd={"30m": 0.99},
        available={"30m": NOW + timedelta(minutes=20)},
    )
    mature = make_hist(
        NOW - timedelta(minutes=60),
        fwd={"30m": 0.01},
        available={"30m": NOW - timedelta(minutes=30)},
    )
    card = run([immature, mature], cur, min_n_independent=1, min_weighted_ess=0.0)
    assert card.n_independent == 1
    assert approx(card.center, 0.01)
    assert card.data_unmatured_fwd == 1


def test_v11_different_secid_never_mixes():
    wrong = make_hist(NOW - timedelta(minutes=60), secid="GAZP", fwd={"30m": 0.99})
    right = make_hist(NOW - timedelta(minutes=120), secid="SBER", fwd={"30m": 0.01})
    card = run([wrong, right], min_n_independent=1, min_weighted_ess=0.0)
    assert card.n_independent == 1 and approx(card.center, 0.01)


def test_v11_same_secid_remains_eligible():
    h = make_hist(NOW - timedelta(minutes=60), secid="SBER", fwd={"30m": 0.02})
    card = run([h], min_n_independent=1, min_weighted_ess=0.0)
    assert card.n_independent == 1 and approx(card.center, 0.02)


def test_v11_empty_secid_rejected():
    try:
        make_current(secid=" ")
        assert False
    except DataContractError:
        pass
    try:
        make_hist(NOW - timedelta(minutes=60), secid="")
        assert False
    except DataContractError:
        pass


def test_v11_naive_datetime_rejected():
    naive = datetime(2026, 10, 7, 12, 0)
    try:
        make_current(ts=naive)
        assert False
    except DataContractError:
        pass
    try:
        CAL.trading_minutes_between(naive, NOW)
        assert False
    except DataContractError:
        pass


def test_v11_horizon_specific_gates():
    cfg = ForecasterConfig(
        top_k=10,
        min_n_independent={"30m": 1, "60m": 2, "90m": 3, "120m": 4},
        min_weighted_ess={"30m": 0.0, "60m": 0.0, "90m": 0.0, "120m": 0.0},
    )
    assert cfg.min_n_independent["30m"] == 1
    assert cfg.min_n_independent["120m"] == 4


def test_v11_replace_config_works():
    cfg = ForecasterConfig()
    cfg2 = replace(cfg, sigma=2.0)
    assert cfg.sigma == 1.0 and cfg2.sigma == 2.0
    assert cfg2.min_n_independent["30m"] == cfg.min_n_independent["30m"]


def test_v11_config_json_snapshot():
    cfg = ForecasterConfig()
    snap = cfg.to_dict()
    encoded = json.dumps(snap, sort_keys=True)
    decoded = json.loads(encoded)
    assert decoded["top_k"] == 20
    assert decoded["min_n_independent"]["30m"] == 10


def test_v11_missing_availability_fails_closed():
    h = make_hist(NOW - timedelta(minutes=60), fwd={"30m": 0.55}, available={})
    card = run([h], min_n_independent=1, min_weighted_ess=0.0)
    assert card.n_independent == 0
    assert card.data_missing_fwd == 1
    assert card.gate_status == "NO_DATA"


def test_v11_immature_only_is_no_data():
    h = make_hist(NOW - timedelta(minutes=10), fwd={"30m": 0.55},
                  available={"30m": NOW + timedelta(minutes=20)})
    card = run([h], min_n_independent=1, min_weighted_ess=0.0)
    assert card.n_independent == 0
    assert card.data_unmatured_fwd == 1
    assert card.gate_status == "NO_DATA"


def test_v11_mature_label_passes():
    h = make_hist(NOW - timedelta(minutes=60), fwd={"30m": 0.55},
                  available={"30m": NOW - timedelta(minutes=30)})
    card = run([h], min_n_independent=1, min_weighted_ess=0.0)
    assert card.gate_status == "PASS" and approx(card.center, 0.55)


def test_v11_aware_utc_calendar_regression():
    fri = datetime(2026, 10, 2, 14, 0, tzinfo=timezone.utc)
    mon = datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc)
    assert CAL.trading_minutes_between(fri, mon) == 455


if __name__ == "__main__":
    fns = [(n, fn) for n, fn in sorted(globals().items())
           if n.startswith("test_") and callable(fn)]
    failed = 0
    for name, fn in fns:
        try:
            fn()
            print(f"{name} PASSED")
        except Exception as e:
            failed += 1
            print(f"{name} FAILED: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed} passed, {failed} failed, total {len(fns)}")
    sys.exit(1 if failed else 0)

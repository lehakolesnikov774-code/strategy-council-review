"""Reproduce runner-v1 defects without changing canonical Forecaster v11."""
from datetime import datetime, timedelta, timezone
from forecaster_v11_marfa import (
    Forecaster, ForecasterConfig, TradingCalendar, HistoricalState,
    MarketDescriptor, SessionBucket, HORIZONS,
)

now = datetime(2026, 10, 5, 9, tzinfo=timezone.utc)
cross = {h: False for h in HORIZONS}
current = MarketDescriptor(now, "M5", "SBER", SessionBucket.MID,
                           {"x": 1.0}, cross, 100.0, 1.0)

def history(ts):
    return HistoricalState(ts, "M5", "SBER", SessionBucket.MID,
                           {"x": 1.0}, cross, {"30m": 1.0},
                           {"30m": ts + timedelta(minutes=30)})

config = ForecasterConfig(top_k=1, half_life_days=10000,
    min_n_independent={h: 1 for h in HORIZONS},
    min_weighted_ess={h: 1 for h in HORIZONS})
fc = Forecaster(config, TradingCalendar())
fc.set_feature_schema(["x"])
old = history(datetime(2024, 1, 2, 9, tzinfo=timezone.utc))
fc.history = [old]
direct = fc.forecast(current, "30m")
fc.load_history([old], now)
bounded = fc.forecast(current, "30m")
assert direct.gate_status == "PASS" and bounded.gate_status == "NO_DATA"
print("MAJOR-1: direct history assignment PASS; load_history NO_DATA")

fc = Forecaster(ForecasterConfig(), TradingCalendar())
fc.set_feature_schema(["x"])
fc.load_history([history(now - timedelta(days=1))], now)
card = fc.forecast(current, "30m")
actual = 1.0
runner_valid = actual is not None and card.center is not None
correct_valid = runner_valid and card.gate_status == "PASS"
assert card.gate_status.startswith("FAIL") and runner_valid and not correct_valid
print(f"MAJOR-2: {card.gate_status} counted by runner-v1 quality predicate")

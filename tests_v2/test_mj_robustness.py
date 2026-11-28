import pandas as pd

from ry_apex_v2.mj_robustness import _simulate


def test_fixed_stop_exits_when_intraday_low_breaches_level():
    dates = pd.bdate_range("2025-01-01", periods=5)
    history = pd.DataFrame({
        "SYMBOL": ["AAA"] * 5, "DATE": dates,
        "OPEN": [100, 100, 90, 92, 94],
        "HIGH": [101, 101, 95, 95, 96],
        "LOW": [99, 99, 89, 91, 93],
        "CLOSE": [100, 100, 92, 94, 95],
        "VOLUME": [100000] * 5,
    })
    signals = pd.DataFrame([{
        "SYMBOL": "AAA", "STRATEGY": "M", "SIGNAL_DATE": dates[0],
        "SIGNAL_CLOSE": 100, "VOL_X": 1.5, "MOM_RANK": .95,
        "CLOSE_LOC": .8,
    }])
    result = _simulate(history, signals, "M", .60, "fixed_8")
    assert result["trades"] == 1
    assert result["stop_exits"] == 1
    assert result["time_exits"] == 0
    assert result["ending_equity"] < 500000


def test_cost_sensitivity_changes_result_without_changing_trade_count():
    dates = pd.bdate_range("2025-01-01", periods=45)
    history = pd.DataFrame({
        "SYMBOL": ["AAA"] * 45, "DATE": dates,
        "OPEN": [100.0] * 45, "HIGH": [102.0] * 45,
        "LOW": [99.0] * 45, "CLOSE": [101.0] * 45,
        "VOLUME": [100000] * 45,
    })
    signals = pd.DataFrame([{
        "SYMBOL": "AAA", "STRATEGY": "M", "SIGNAL_DATE": dates[0],
        "SIGNAL_CLOSE": 100, "VOL_X": 1.5, "MOM_RANK": .95,
        "CLOSE_LOC": .8,
    }])
    low_cost = _simulate(history, signals, "M", .35, "none")
    high_cost = _simulate(history, signals, "M", 1.00, "none")
    assert low_cost["trades"] == high_cost["trades"] == 1
    assert high_cost["ending_equity"] < low_cost["ending_equity"]


def test_trailing_stop_does_not_use_same_session_high_to_stop_same_session():
    dates = pd.bdate_range("2025-01-01", periods=3)
    history = pd.DataFrame({
        "SYMBOL": ["AAA"] * 3, "DATE": dates,
        "OPEN": [100.0, 100.0, 190.0],
        "HIGH": [200.0, 200.0, 195.0],
        "LOW": [95.0, 95.0, 180.0],
        "CLOSE": [150.0, 190.0, 185.0],
        "VOLUME": [100000] * 3,
    })
    signals = pd.DataFrame([{
        "SYMBOL": "AAA", "STRATEGY": "M", "SIGNAL_DATE": dates[0],
        "SIGNAL_CLOSE": 100, "VOL_X": 1.5, "MOM_RANK": .95,
        "CLOSE_LOC": .8,
    }])
    result = _simulate(history, signals, "M", .35, "trailing_8")
    # Day 1's 200 high must not create a 184 stop that is tested against
    # day 1's 95 low. The carried stop is 92; day 2 raises it to 184.
    assert result["trades"] == 1
    assert result["stop_exits"] == 1
    assert result["ending_equity"] > 500000

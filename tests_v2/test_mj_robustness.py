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

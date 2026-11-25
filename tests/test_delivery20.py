import pandas as pd
from delivery20 import backtest_delivery20, summarize_delivery20


def test_delivery20_target_and_stop_first():
    dates = pd.bdate_range("2025-01-01", periods=4)
    d = pd.DataFrame({
        "SYMBOL": ["AAA"] * 4, "DATE": dates,
        "OPEN": [100, 100, 100, 100], "HIGH": [101, 125, 110, 110],
        "LOW": [99, 99, 99, 99], "CLOSE": [100, 120, 105, 105],
        "D20_BUY": [True, False, False, False], "D20_STOP": [90] * 4,
        "D20_TARGET": [120] * 4, "D20_RISK_PCT": [10] * 4, "MOM_RANK": [95] * 4,
    })
    trades = backtest_delivery20(d, cost_pct=0.35)
    assert len(trades) == 1
    assert trades.iloc[0].REASON == "TARGET_20"
    assert round(trades.iloc[0].NET_RETURN_PCT, 2) == 19.65
    assert summarize_delivery20(trades)["target_hit_pct"] == 100


def test_delivery20_stop_first_if_both_touch():
    dates = pd.bdate_range("2025-01-01", periods=3)
    d = pd.DataFrame({
        "SYMBOL": ["AAA"] * 3, "DATE": dates,
        "OPEN": [100, 100, 100], "HIGH": [101, 125, 110],
        "LOW": [99, 85, 99], "CLOSE": [100, 110, 105],
        "D20_BUY": [True, False, False], "D20_STOP": [90] * 3,
        "D20_TARGET": [120] * 3, "D20_RISK_PCT": [10] * 3, "MOM_RANK": [95] * 3,
    })
    trades = backtest_delivery20(d, cost_pct=0)
    assert trades.iloc[0].REASON == "STOP"


def test_recent_unfinished_trade_is_not_counted_as_closed():
    dates = pd.bdate_range("2025-01-01", periods=3)
    d = pd.DataFrame({
        "SYMBOL": ["AAA"] * 3, "DATE": dates,
        "OPEN": [100, 100, 105], "HIGH": [101, 110, 112],
        "LOW": [99, 98, 103], "CLOSE": [100, 105, 110],
        "D20_BUY": [True, False, False], "D20_STOP": [90] * 3,
        "D20_TARGET": [120] * 3, "D20_RISK_PCT": [10] * 3, "D20_SCORE": [90] * 3,
    })
    trades = backtest_delivery20(d, cost_pct=0.35, max_hold=120)
    summary = summarize_delivery20(trades)
    assert len(trades) == 1
    assert trades.iloc[0].REASON == "OPEN"
    assert summary["trades"] == 0
    assert summary["open_positions"] == 1


def test_delivery20_target_is_configurable():
    dates = pd.bdate_range("2025-01-01", periods=3)
    d = pd.DataFrame({
        "SYMBOL": ["AAA"] * 3, "DATE": dates,
        "OPEN": [100, 100, 100], "HIGH": [101, 135, 110],
        "LOW": [99, 99, 99], "CLOSE": [100, 130, 105],
        "D20_BUY": [True, False, False], "D20_STOP": [90] * 3,
        "D20_TARGET": [120] * 3, "D20_RISK_PCT": [10] * 3,
        "MOM_RANK": [95] * 3,
    })
    trades = backtest_delivery20(d, cost_pct=0.35, target_pct=30)
    assert len(trades) == 1
    assert trades.iloc[0].REASON == "TARGET_30"
    assert round(trades.iloc[0].NET_RETURN_PCT, 2) == 29.65

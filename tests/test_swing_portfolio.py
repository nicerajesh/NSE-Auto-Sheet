import pandas as pd
from swing_portfolio import run_swing_portfolio_backtest


def sample():
    dates = pd.bdate_range("2024-01-01", periods=8)
    rows = []
    for i, dt in enumerate(dates):
        rows.append({"SYMBOL": "AAA", "DATE": dt, "OPEN": 100 if i == 1 else 100,
            "HIGH": 106 if i == 2 else 102, "LOW": 99, "CLOSE": 101,
            "ATR": 2.0, "RSI": 55.0, "TURN_BUY": i == 0,
            "TURN_PIVOT_LOW_PRICE": 95.0 if i == 0 else float("nan")})
    return pd.DataFrame(rows)


def test_enters_next_session_open_and_outputs_portfolio_metrics():
    trades, curve, stats = run_swing_portfolio_backtest(sample(), initial_capital=100000,
        max_positions=1, max_hold=4, cost_pct=0.0)
    assert len(trades) == 1
    assert trades.iloc[0].ENTRY_DATE == pd.Timestamp("2024-01-02")
    assert trades.iloc[0].ENTRY_PRICE == 100
    assert trades.iloc[0].EXIT_REASON in {"TARGET_3R", "TIME_EXIT", "END_OF_DATA", "STOP"}
    assert {"EQUITY", "DRAWDOWN_PCT"} <= set(curve.columns)
    assert set(stats.PERIOD) == {"FULL", "OOS_2023_PLUS"}


def test_stop_wins_when_stop_and_target_touch_same_bar():
    f = sample()
    f.loc[2, "HIGH"] = 120
    f.loc[2, "LOW"] = 90
    trades, _, _ = run_swing_portfolio_backtest(f, initial_capital=100000,
        max_positions=1, max_hold=4, cost_pct=0.0)
    assert trades.iloc[0].EXIT_REASON == "STOP"

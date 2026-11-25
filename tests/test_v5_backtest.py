"""Execution and accounting tests for the independent V5 backtest."""
import pandas as pd
from v5_backtest import simulate_v5_trade, run_v5_backtest, summarize_v5


def bars():
    return pd.DataFrame({
        "DATE": pd.bdate_range("2025-01-01", periods=5),
        "OPEN": [100, 101, 101, 101, 101],
        "HIGH": [101, 104, 105, 102, 102],
        "LOW": [99, 100, 100, 100, 100],
        "CLOSE": [100, 103, 104, 101, 101],
    })


def test_next_session_entry_and_target_exit():
    d = bars()
    trade = simulate_v5_trade(d, 0, 99, target_r=2, cost_pct=0)
    assert trade["ENTRY"] == 101
    assert trade["REASON"] == "TARGET_2R"
    assert trade["EXIT"] == 105


def test_stop_wins_when_stop_and_target_touch_same_bar():
    d = bars()
    d.loc[1, ["LOW", "HIGH"]] = [98, 110]
    trade = simulate_v5_trade(d, 0, 99, target_r=2, cost_pct=0)
    assert trade["REASON"] == "STOP"
    assert trade["EXIT"] == 99


def test_gap_filter_rejects_large_open_gap():
    d = bars()
    d.loc[1, "OPEN"] = 104
    assert simulate_v5_trade(d, 0, 99, max_gap_pct=2) is None


def test_summary_handles_empty_and_closed_trades():
    assert summarize_v5(pd.DataFrame())["trades"] == 0
    t = pd.DataFrame({"EXIT_DATE": pd.to_datetime(["2025-01-03", "2025-01-04"]),
                      "RET_PCT": [5.0, -2.0], "R": [2.0, -1.0]})
    s = summarize_v5(t)
    assert s["trades"] == 2 and s["pf"] == 2.5

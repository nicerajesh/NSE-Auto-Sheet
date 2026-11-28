import pandas as pd

from volume_reversal_portfolio import simulate_portfolio


def test_portfolio_enters_next_session_open_and_exits_after_horizon():
    dates = pd.bdate_range("2025-01-01", periods=5)
    hist = pd.DataFrame({
        "SYMBOL": ["ABC"] * 5, "DATE": dates,
        "OPEN": [10, 11, 12, 13, 14],
        "HIGH": [11, 12, 13, 14, 15],
        "LOW": [9, 10, 11, 12, 13],
        "CLOSE": [10, 12, 13, 14, 15],
        "VOLUME": [1000] * 5,
    })
    events = pd.DataFrame({
        "SYMBOL": ["ABC"], "TIER": ["A_DISCOVERY"],
        "SIGNAL_DATE": [dates[0]], "SIGNAL_CLOSE": [10.0],
    })
    metrics, curve, trades = simulate_portfolio(
        hist, events, "A_DISCOVERY", 2, initial_capital=10000,
        max_positions=1, max_entries_per_day=1, cost_pct=0.35,
    )
    assert metrics["TRADES"] == 1
    assert trades.iloc[0]["ENTRY_DATE"] == dates[1]
    assert trades.iloc[0]["ENTRY_PRICE"] == 11
    assert trades.iloc[0]["EXIT_DATE"] == dates[2]
    assert trades.iloc[0]["EXIT_PRICE"] == 13
    assert round(trades.iloc[0]["NET_RETURN_PCT"], 2) == 17.83


def test_portfolio_does_not_enter_when_next_day_horizon_is_incomplete():
    dates = pd.bdate_range("2025-01-01", periods=2)
    hist = pd.DataFrame({
        "SYMBOL": ["ABC"] * 2, "DATE": dates,
        "OPEN": [10, 11], "HIGH": [11, 12], "LOW": [9, 10],
        "CLOSE": [10, 11], "VOLUME": [1000, 1000],
    })
    events = pd.DataFrame({
        "SYMBOL": ["ABC"], "TIER": ["A_DISCOVERY"],
        "SIGNAL_DATE": [dates[0]], "SIGNAL_CLOSE": [10.0],
    })
    metrics, curve, trades = simulate_portfolio(hist, events, "A_DISCOVERY", 2)
    assert metrics["TRADES"] == 0

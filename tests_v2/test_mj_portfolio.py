import numpy as np
import pandas as pd

from ry_apex_v2.mj_portfolio import (
    COST_PCT, HOLD_SESSIONS, build_mj_signals, simulate_mj_portfolio,
)


def test_mj_signals_empty_on_flat_prices():
    dates = pd.bdate_range("2024-01-01", periods=300)
    rows = []
    for symbol in ("AAA", "BBB"):
        for day in dates:
            rows.append({
                "SYMBOL": symbol, "DATE": day, "OPEN": 100.0,
                "HIGH": 100.5, "LOW": 99.5, "CLOSE": 100.0,
                "VOLUME": 100_000,
            })
    signals = build_mj_signals(pd.DataFrame(rows))
    assert set(signals.columns) >= {"SYMBOL", "STRATEGY", "SIGNAL_DATE"}
    assert signals.empty


def test_mj_portfolio_enters_next_open_and_exits_40th_session_close():
    dates = pd.bdate_range("2025-01-01", periods=HOLD_SESSIONS + 1)
    history = pd.DataFrame({
        "SYMBOL": ["AAA"] * len(dates),
        "DATE": dates,
        "OPEN": [100.0] * len(dates),
        "HIGH": [111.0] * len(dates),
        "LOW": [99.0] * len(dates),
        "CLOSE": [100.0] + [110.0] * HOLD_SESSIONS,
        "VOLUME": [100_000] * len(dates),
    })
    signals = pd.DataFrame([{
        "SYMBOL": "AAA", "STRATEGY": "M",
        "SIGNAL_DATE": dates[0], "SIGNAL_CLOSE": 100.0,
        "VOL_X": 1.5, "MOM_RANK": 0.95, "CLOSE_LOC": 0.8,
    }])
    trades, equity, stats = simulate_mj_portfolio(history, signals, "M", 100_000)
    assert len(trades) == 1
    trade = trades.iloc[0]
    assert trade.ENTRY_DATE == dates[1]
    assert trade.EXIT_DATE == dates[HOLD_SESSIONS]
    assert trade.HOLD_SESSIONS == HOLD_SESSIONS
    assert trade.ENTRY == 100.0 and trade.EXIT == 110.0
    assert round(trade.NET_PNL, 2) == round(150 * 10 - 150 * 100 * COST_PCT / 100, 2)
    assert stats["completed_trades"] == 1
    assert stats["ending_equity"] > 100_000

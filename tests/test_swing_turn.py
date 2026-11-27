import numpy as np
import pandas as pd

from swing_turn import add_turn_signal_features, latest_turn_signals, backtest_turn_signals


def make_frame(n=100):
    dates = pd.bdate_range("2024-01-01", periods=n)
    # deterministic gentle wave with enough bars for EMA/RSI warmup
    x = np.arange(n)
    close = 100 + 0.12 * x + 5 * np.sin(x / 5)
    op = close - 0.4
    high = np.maximum(op, close) + 1
    low = np.minimum(op, close) - 1
    return pd.DataFrame({
        "SYMBOL": "TEST", "DATE": dates, "OPEN": op, "HIGH": high, "LOW": low,
        "CLOSE": close, "VOLUME": np.full(n, 100000.0),
        "EMA20": pd.Series(close).ewm(span=20, adjust=False).mean(),
        "RSI": np.full(n, 55.0), "ATR": np.full(n, 2.0),
    })


def test_pivot_is_confirmed_only_after_right_bars_and_not_lookahead():
    f = make_frame()
    full = add_turn_signal_features(f, left=3, right=2)
    cut = f.iloc[:75].copy()
    partial = add_turn_signal_features(cut, left=3, right=2)
    a = full[full.DATE == cut.DATE.iloc[-1]].iloc[0]
    b = partial[partial.DATE == cut.DATE.iloc[-1]].iloc[0]
    assert bool(a.TURN_PIVOT_LOW) == bool(b.TURN_PIVOT_LOW)
    assert bool(a.TURN_PIVOT_HIGH) == bool(b.TURN_PIVOT_HIGH)


def test_latest_turn_output_schema_when_no_signal():
    f = make_frame()
    f = add_turn_signal_features(f)
    out = latest_turn_signals(f)
    assert isinstance(out, pd.DataFrame)
    assert "SIGNAL" in out.columns



def test_turn_backtest_enters_next_session_open_and_counts_horizon_sessions():
    f = make_frame(40)
    f["TURN_BUY"] = False
    f.loc[20, "TURN_BUY"] = True
    events, stats = backtest_turn_signals(f, horizons=(5,), oos_start="2024-01-01")
    assert len(events) == 1
    row = events.iloc[0]
    assert row["ENTRY_DATE"] == f.loc[21, "DATE"]
    assert row["ENTRY_OPEN"] == f.loc[21, "OPEN"]
    assert row["EXIT_DATE"] == f.loc[25, "DATE"]
    assert row["HORIZON_SESSIONS"] == 5
    assert len(stats) == 1
    assert stats.iloc[0]["TRADES"] == 1

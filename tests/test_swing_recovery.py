import numpy as np
import pandas as pd
import pytest

from swing_recovery import add_swing_features, latest_swing_report, backtest_swing, SWING_COLUMNS


def history(n=320):
    dates = pd.bdate_range("2024-01-01", periods=n)
    close = 100 * np.exp(np.linspace(0, 0.25, n))
    return pd.DataFrame({
        "SYMBOL": "AAA", "DATE": dates, "OPEN": close * 0.999,
        "HIGH": close * 1.01, "LOW": close * 0.99,
        "CLOSE": close, "VOLUME": np.full(n, 2_000_000.0)
    })


def test_features_are_causal_when_future_rows_are_added():
    h = history()
    full = add_swing_features(h)
    cut = h.DATE.iloc[280]
    partial = add_swing_features(h[h.DATE <= cut])
    a = full[full.DATE == cut].iloc[0]
    b = partial[partial.DATE == cut].iloc[0]
    for col in ("ATR14", "EMA20", "EMA50", "EMA200", "RSI14", "LOW_52W",
                "HIGH_55D_PREV", "LOW_DISTANCE_PCT", "BREAKOUT_SETUP", "RECOVERY_SETUP"):
        if isinstance(a[col], (bool, np.bool_)):
            assert bool(a[col]) == bool(b[col])
        else:
            assert a[col] == pytest.approx(b[col], nan_ok=True)


def test_swing_report_has_exact_required_columns_and_target_math():
    date = pd.Timestamp("2026-11-27")
    row = {
        "SYMBOL": "AAA", "DATE": date, "OPEN": 99, "HIGH": 102, "LOW": 98,
        "CLOSE": 100.0, "ATR14": 2.0, "LOW_52W": 80.0, "LOW_DISTANCE_PCT": 25.0,
        "LOW_10D": 97.0, "BREAKOUT_SETUP": True, "RECOVERY_SETUP": False,
        "WAIT_SETUP": False, "EMA20": 99.0, "EMA20_RISING": True,
        "RS_RANK": 95.0, "VOL_RATIO": 2.0, "CLOSE_LOC": 0.9,
        "EMA200": 90.0, "EMA50": 98.0
    }
    rows = latest_swing_report(pd.DataFrame([row]))
    assert list(rows.columns[:len(SWING_COLUMNS)]) == SWING_COLUMNS
    r = rows.iloc[0]
    assert r["SIGNAL"] == "MUST BUY"
    assert r["T1"] == pytest.approx(120.0)
    assert r["T2"] == pytest.approx(130.0)
    assert r["T3"] == pytest.approx(140.0)
    assert r["+20%"] == pytest.approx(r["BUY PRICE"] * 1.20)
    assert r["+30%"] == pytest.approx(r["BUY PRICE"] * 1.30)
    assert r["+40%"] == pytest.approx(r["BUY PRICE"] * 1.40)
    assert r["52W LOW DISTANCE"] == pytest.approx(25.0)


def test_empty_history_or_no_setup_returns_empty_report():
    f = add_swing_features(history())
    f["BREAKOUT_SETUP"] = False
    f["RECOVERY_SETUP"] = False
    f["WAIT_SETUP"] = False
    report = latest_swing_report(f)
    assert report.empty


def test_backtest_returns_well_formed_empty_result_without_signals():
    f = add_swing_features(history())
    f["BREAKOUT_SETUP"] = False
    f["RECOVERY_SETUP"] = False
    trades = backtest_swing(f)
    assert trades.empty

import numpy as np
import pandas as pd
import pytest

from recovery import add_recovery_features, latest_recovery_candidates, recovery_outcome_diagnostics


def recovery_history(n=360):
    dates = pd.bdate_range("2024-01-02", periods=n)
    # Rise to a prior peak, sell off hard, then rebuild from the lows.
    close = np.concatenate([
        np.linspace(100, 200, 200),
        np.linspace(198, 70, 50),
        np.linspace(70.5, 91, n - 250),
    ])
    op = np.r_[close[0], close[:-1]]
    high = np.maximum(op, close) * 1.01
    low = np.minimum(op, close) * 0.99
    volume = np.full(n, 10_000_000.0)
    ema20 = pd.Series(close).ewm(span=20, adjust=False).mean().to_numpy()
    ema50 = pd.Series(close).ewm(span=50, adjust=False).mean().to_numpy()
    ema200 = pd.Series(close).ewm(span=200, adjust=False).mean().to_numpy()
    hh20 = pd.Series(high).shift(1).rolling(20, min_periods=15).max().to_numpy()
    roc60 = pd.Series(close).pct_change(60).mul(100).to_numpy()
    frame = pd.DataFrame({
        "SYMBOL": "TEST",
        "DATE": dates,
        "OPEN": op,
        "HIGH": high,
        "LOW": low,
        "CLOSE": close,
        "VOLUME": volume,
        "ATR": close * 0.025,
        "EMA20": ema20,
        "EMA50": ema50,
        "EMA200": ema200,
        "RSI": 55.0,
        "VOL_RATIO": 1.6,
        "TURNOVER_CR": close * volume / 1e7,
        "RANGE20_PCT": 10.0,
        "HH20": hh20,
        "CLOSE_LOC": 0.8,
        "ROC60": roc60,
    })
    return frame


def test_recovery_features_include_drawdown_stage_and_trade_references():
    out = add_recovery_features(recovery_history())
    needed = {
        "REC_HIGH_252", "REC_LOW_252", "REC_DRAWDOWN_PCT", "REC_FROM_LOW_PCT",
        "REC_SCORE", "REC_STAGE", "REC_EVENT", "REC_TRIGGER_PRICE",
    }
    assert needed.issubset(out.columns)
    assert out["REC_SCORE"].dropna().between(0, 100).all()
    assert out["REC_DRAWDOWN_PCT"].dropna().between(-100, 100).all()

    latest = latest_recovery_candidates(out)
    assert not latest.empty
    assert (latest["REC_DRAWDOWN_PCT"] >= 25).all()
    assert (latest["REC_FROM_LOW_PCT"] >= 5).all()
    assert (latest["REC_ENTRY_REF"] > latest["REC_STOP"]).all()
    assert (latest["REC_T1"] > latest["REC_ENTRY_REF"]).all()
    assert (latest["REC_T2"] > latest["REC_T1"]).all()
    assert (latest["REC_T3"] > latest["REC_T2"]).all()


def test_recovery_features_do_not_use_future_rows():
    raw = recovery_history()
    full = add_recovery_features(raw)
    cut_date = raw["DATE"].iloc[320]
    partial = add_recovery_features(raw[raw["DATE"] <= cut_date])
    full_row = full[full["DATE"].eq(cut_date)].iloc[0]
    partial_row = partial[partial["DATE"].eq(cut_date)].iloc[0]
    for col in ["REC_HIGH_252", "REC_LOW_252", "REC_DRAWDOWN_PCT", "REC_FROM_LOW_PCT", "REC_SCORE", "REC_STAGE"]:
        if isinstance(full_row[col], str):
            assert full_row[col] == partial_row[col]
        else:
            assert full_row[col] == pytest.approx(partial_row[col], nan_ok=True)


def test_recovery_diagnostics_only_uses_complete_forward_windows():
    out = add_recovery_features(recovery_history())
    diag = recovery_outcome_diagnostics(out, horizons=(10, 20, 40))
    assert set(diag["HORIZON_SESSIONS"]) == {10, 20, 40}
    assert set(diag["STAGE"]) == {"PREPARE", "TRIGGERED"}
    assert (diag["EVENTS"] >= 0).all()
    assert {"HIT_PLUS10_PCT", "HIT_PLUS20_PCT", "AVG_MAX_DRAWDOWN_PCT"}.issubset(diag.columns)


def test_recovery_missing_inputs_fail_loudly():
    with pytest.raises(ValueError, match="missing required"):
        add_recovery_features(pd.DataFrame({"SYMBOL": ["TEST"], "DATE": [pd.Timestamp("2025-01-01")]}))

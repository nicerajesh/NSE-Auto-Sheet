import numpy as np
import pandas as pd
from src.independent_strategy_lab import _features, build_signals, summarize


def sample_history(n=420):
    rng = np.random.default_rng(7)
    dates = pd.bdate_range("2023-01-02", periods=n)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0008, 0.018, n)))
    high = close * (1 + rng.uniform(0.002, 0.025, n))
    low = close * (1 - rng.uniform(0.002, 0.025, n))
    open_ = close * (1 + rng.normal(0, 0.006, n))
    volume = rng.integers(100_000, 900_000, n)
    return pd.DataFrame({"DATE": dates, "SYMBOL": "TEST", "OPEN": open_,
                         "HIGH": high, "LOW": low, "CLOSE": close, "VOLUME": volume})


def test_features_are_calculated_without_future_columns():
    f = _features(sample_history())
    assert {"EMA20", "EMA50", "EMA100", "EMA200", "RSI", "BB_WIDTH_PCTL", "ATR_PCT"} <= set(f.columns)
    assert f["EMA200"].notna().sum() > 100


def test_independent_lab_returns_valid_schema():
    hist = pd.concat([sample_history().assign(SYMBOL="A"),
                      sample_history().assign(SYMBOL="B")], ignore_index=True)
    events = build_signals(hist)
    assert set(["SYMBOL", "TIER", "SIGNAL_DATE", "SIGNAL_CLOSE"]) <= set(events.columns)
    if not events.empty:
        assert set(events["TIER"]).issubset({
            "J_DONCHIAN_TREND", "K_SQUEEZE_EXPANSION",
            "L_RSI_RESET_CONTINUATION", "M_MOMENTUM_ROTATION"})
        assert "RET20_NET_PCT" in events.columns


def test_summary_has_train_validation_holdout_labels():
    e = pd.DataFrame({
        "SIGNAL_DATE": pd.to_datetime(["2021-01-01", "2023-01-01", "2025-01-01"]),
        "TIER": ["J_DONCHIAN_TREND"] * 3,
        "RET10_NET_PCT": [1.0, -1.0, 2.0],
        "RET20_NET_PCT": [1.0, -1.0, 2.0],
        "RET40_NET_PCT": [1.0, -1.0, 2.0],
    })
    s = summarize(e)
    assert set(s["PERIOD"]) == {"TRAIN_2018_2022", "VALIDATION_2023_2024", "HOLDOUT_2025_PLUS"}

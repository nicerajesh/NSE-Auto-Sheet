"""Tests for the V5 multi-setup research layer."""
import numpy as np
import pandas as pd

from v5_strategy import add_v5_features, latest_v5_candidates


def synthetic_history(n=520, symbols=("AAA", "BBB", "CCC")):
    rng = np.random.default_rng(42)
    dates = pd.bdate_range("2023-01-02", periods=n)
    blocks = []
    for i, sym in enumerate(symbols):
        ret = rng.normal(0.0007 + i * 0.0002, 0.012, n)
        close = 100 * np.exp(np.cumsum(ret))
        open_ = close * (1 + rng.normal(0, 0.002, n))
        high = np.maximum(open_, close) * 1.008
        low = np.minimum(open_, close) * 0.992
        volume = rng.integers(500_000, 1_500_000, n)
        blocks.append(pd.DataFrame({
            "SYMBOL": sym, "DATE": dates, "OPEN": open_, "HIGH": high,
            "LOW": low, "CLOSE": close, "VOLUME": volume,
            "ATR": pd.Series(high-low).rolling(14, min_periods=14).mean().values,
            "EMA20": pd.Series(close).ewm(span=20, adjust=False).mean().values,
            "EMA50": pd.Series(close).ewm(span=50, adjust=False).mean().values,
            "EMA200": pd.Series(close).ewm(span=200, adjust=False).mean().values,
            "RSI": 55.0, "ADX": 25.0, "VOL_RATIO": 1.1,
            "TURNOVER_CR": 10.0, "MOM_RANK": 90.0,
        }))
    return pd.concat(blocks, ignore_index=True)


def test_v5_features_columns_and_no_future_rows():
    h = synthetic_history()
    f = add_v5_features(h)
    required = ["V5_SCORE", "V5_BUY", "V5_CUP_HANDLE", "V5_BULL_FLAG",
                "V5_VCP", "V5_STAGE2", "V5_WEEKLY_BULL", "V5_REACCUMULATION"]
    assert all(c in f.columns for c in required)
    assert len(f) <= len(h)
    assert f.groupby("SYMBOL").DATE.min().min() == h.DATE.min()


def test_missing_benchmark_is_not_faked_as_nifty():
    f = add_v5_features(synthetic_history())
    assert f["BENCH_ROC20"].isna().all()
    assert not f["V5_RS_STRONG"].any()


def test_benchmark_relative_strength_is_added():
    h = synthetic_history()
    b = pd.DataFrame({"DATE": sorted(h.DATE.unique()), "CLOSE": np.linspace(10000, 11000, h.DATE.nunique())})
    f = add_v5_features(h, benchmark=b)
    assert "BENCH_ROC20" in f and "STOCK_ROC20" in f and "V5_RS_STRONG" in f


def test_candidates_are_latest_date_only():
    f = add_v5_features(synthetic_history())
    out = latest_v5_candidates(f)
    assert out.empty or out.DATE.nunique() == 1

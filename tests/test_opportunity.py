import numpy as np
import pandas as pd

from engine import add_features
from opportunity import add_opportunity_features, latest_opportunities, evaluate_opportunity_setups


def sample_history(n=520):
    rng = np.random.default_rng(42)
    dates = pd.bdate_range("2023-01-02", periods=n)
    rows = []
    for k, sym in enumerate(("ALPHA", "BETA", "GAMMA")):
        ret = rng.normal(0.0007 + k * 0.0002, 0.012, n)
        close = 100 * np.exp(np.cumsum(ret))
        op = close * (1 + rng.normal(0, .002, n))
        hi = np.maximum(op, close) * 1.01
        lo = np.minimum(op, close) * .99
        vol = rng.integers(2_000_000, 5_000_000, n).astype(float)
        rows.append(pd.DataFrame({"SYMBOL": sym, "DATE": dates, "OPEN": op, "HIGH": hi,
                                  "LOW": lo, "CLOSE": close, "VOLUME": vol}))
    return pd.concat(rows, ignore_index=True)


def test_opportunity_engine_is_no_lookahead_and_outputs_valid_levels():
    hist = sample_history()
    full = add_opportunity_features(add_features(hist))
    cut = hist[hist.DATE <= sorted(hist.DATE.unique())[480]]
    partial = add_opportunity_features(add_features(cut))
    a = full[full.DATE == sorted(hist.DATE.unique())[480]].sort_values("SYMBOL")
    b = partial[partial.DATE == sorted(hist.DATE.unique())[480]].sort_values("SYMBOL")
    for col in ("HH252", "LL252", "LOW52W_DIST_PCT", "OPPORTUNITY_SCORE", "O_52W_RECOVERY"):
        np.testing.assert_allclose(a[col].to_numpy(dtype=float), b[col].to_numpy(dtype=float), equal_nan=True)
    radar = latest_opportunities(full)
    if not radar.empty:
        assert (radar.STOP_LOSS < radar.CLOSE).all()
        assert (radar.T1_2R > radar.CLOSE).all()
        assert radar.SCORE.between(0, 100).all()


def test_historical_setup_evaluator_returns_metrics_shape():
    f = add_opportunity_features(add_features(sample_history()))
    stats = evaluate_opportunity_setups(f)
    assert set(stats.columns) == {"SETUP", "TRADES", "WIN_PCT", "AVG_NET_PCT", "MEDIAN_NET_PCT", "PROFIT_FACTOR", "OOS_TRADES_2023_PLUS", "OOS_WIN_PCT_2023_PLUS", "OOS_AVG_NET_PCT_2023_PLUS", "OOS_PROFIT_FACTOR_2023_PLUS"}
    if not stats.empty:
        assert (stats.TRADES > 0).all()
        assert stats.WIN_PCT.between(0, 100).all()

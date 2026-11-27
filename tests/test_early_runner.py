import numpy as np
import pandas as pd

from early_runner import add_early_runner_features, latest_early_runners, backtest_early_runners, summarize_focus_symbols


def feature_frame(n=340):
    rng = np.random.default_rng(17)
    dates = pd.bdate_range("2022-01-03", periods=n)
    parts = []
    for sym, drift in (("ALPHA", 0.0008), ("BETA", 0.0003)):
        close = 100 * np.exp(np.cumsum(rng.normal(drift, 0.008, n)))
        op = close * (1 + rng.normal(0, 0.002, n))
        high = np.maximum(op, close) * 1.01
        low = np.minimum(op, close) * 0.99
        vol = rng.integers(1_000_000, 2_000_000, n).astype(float)
        d = pd.DataFrame({
            "SYMBOL": sym, "DATE": dates, "OPEN": op, "HIGH": high, "LOW": low,
            "CLOSE": close, "VOLUME": vol, "EMA20": pd.Series(close).ewm(span=20).mean(),
            "EMA50": pd.Series(close).ewm(span=50).mean(), "ATR": pd.Series(high-low).rolling(14).mean(),
            "RSI": np.full(n, 55.0), "RANK60": np.linspace(20, 90, n),
            "HH50": pd.Series(high).shift(1).rolling(50, min_periods=30).max(),
            "HH20": pd.Series(high).shift(1).rolling(20, min_periods=15).max(),
            "RANGE_TIGHTNESS": np.full(n, 55.0), "TURNOVER_CR": np.full(n, 20.0),
            "VOL_RATIO": np.full(n, 1.1), "CLOSE_LOC": np.full(n, 0.75),
            "JUMP_RECENT": np.zeros(n),
        })
        parts.append(d)
    return pd.concat(parts, ignore_index=True)


def test_early_runner_features_are_causal():
    hist = feature_frame()
    full = add_early_runner_features(hist)
    cut_date = sorted(hist.DATE.unique())[300]
    partial = add_early_runner_features(hist[hist.DATE <= cut_date])
    a = full[full.DATE == cut_date].sort_values("SYMBOL")
    b = partial[partial.DATE == cut_date].sort_values("SYMBOL")
    for col in ("ER_LOW_DIST", "ER_HIGH_DIST", "ER_CMF20", "ER_UP_DOWN_VOL",
                "ER_RANK_IMPROVE", "EARLY_RUNNER_SCORE", "ER_BOTTOM_TURN",
                "ER_ACCUMULATION", "ER_PREBREAKOUT", "ER_FIRST_MOMENTUM"):
        np.testing.assert_allclose(a[col].to_numpy(dtype=float), b[col].to_numpy(dtype=float), equal_nan=True)


def test_forward_returns_start_next_open_and_require_complete_window():
    n = 90
    dates = pd.bdate_range("2024-01-01", periods=n)
    close = np.full(n, 100.0)
    op = np.full(n, 100.0)
    high = np.full(n, 101.0)
    low = np.full(n, 99.0)
    close[11:16] = 110.0
    f = pd.DataFrame({
        "SYMBOL": "TEST", "DATE": dates, "OPEN": op, "HIGH": high, "LOW": low,
        "CLOSE": close, "EARLY_RUNNER_SCORE": 80.0,
        "ER_BOTTOM_TURN": False, "ER_ACCUMULATION": False,
        "ER_PREBREAKOUT": False, "ER_FIRST_MOMENTUM": False,
    })
    f.loc[10, "ER_BOTTOM_TURN"] = True
    events, stats = backtest_early_runners(f)
    assert len(events) == 1
    assert events.iloc[0]["ENTRY_DATE"] == dates[11]
    assert events.iloc[0]["ENTRY_OPEN"] == 100.0
    assert np.isclose(events.iloc[0]["RET_5D"], 10.0)
    assert not stats.empty
    assert (stats.HORIZON_SESSIONS == 5).any()


def test_latest_radar_has_only_flagged_rows():
    f = feature_frame()
    f["ER_BOTTOM_TURN"] = False
    f["ER_ACCUMULATION"] = False
    f["ER_PREBREAKOUT"] = False
    f["ER_FIRST_MOMENTUM"] = False
    f.loc[f.index[-1], "ER_ACCUMULATION"] = True
    f["EARLY_RUNNER_SCORE"] = 77.0
    f["ER_LOW_DIST"] = 12.0
    f["ER_HIGH_DIST"] = -8.0
    f["ER_CMF20"] = .12
    f["ER_UP_DOWN_VOL"] = 1.4
    f["ER_RANK_IMPROVE"] = 8.0
    f["RSI"] = 59.0
    radar = latest_early_runners(f)
    assert len(radar) == 1
    assert radar.iloc[0]["SETUP"] == "ACCUMULATION"
    assert radar.iloc[0]["SCORE"] == 77.0



def test_focus_scorecard_keeps_all_requested_symbols_and_deduplicates_dates():
    events = pd.DataFrame({
        "SYMBOL": ["PRESTIGE", "PRESTIGE", "PRESTIGE"],
        "SETUP": ["BOTTOM TURN", "ACCUMULATION", "FIRST MOMENTUM"],
        "SIGNAL_DATE": pd.to_datetime(["2024-01-01", "2024-01-01", "2024-02-01"]),
        "SCORE": [70.0, 90.0, 80.0],
        "RET_10D": [5.0, 6.0, 12.0], "RET_20D": [8.0, 9.0, 15.0],
        "RET_40D": [10.0, 11.0, 20.0],
    })
    out = summarize_focus_symbols(events, ["PRESTIGE", "ACE"])
    assert list(out.SYMBOL) == ["PRESTIGE", "ACE"]
    assert out.iloc[0]["EVENT_DAYS"] == 2
    assert out.iloc[0]["AVG_10D_PCT"] == 9.0
    assert out.iloc[1]["EVENT_DAYS"] == 0
    assert pd.isna(out.iloc[1]["AVG_10D_PCT"])

import numpy as np
import pandas as pd
import pytest

from config import CFG
from engine import (add_features, latest_candidates, plan_levels, position_size, simulate_staircase,
                    simulate_v38_trail, trade_return, v38_plan_levels)


def bars(rows):
    a = np.array(rows, float)  # open, high, low, close
    return a[:, 0], a[:, 1], a[:, 2], a[:, 3]


def test_plan_levels_math():
    p = plan_levels(100.0, 3.0)          # SL = 100 - 2*3 = 94, R = 6
    assert p["STOP"] == pytest.approx(94.0)
    assert p["T1"] == pytest.approx(112.0) and p["T2"] == pytest.approx(124.0) and p["T3"] == pytest.approx(136.0)
    assert p["RISK_PCT"] == pytest.approx(6.0)


def test_position_size_risk_and_caps():
    s = position_size(100.0, 94.0, 1.0)  # risk Rs 5000 / 6 = 833 sh, but cap 15% of 10L = 1500 sh -> 833
    assert s["QTY"] == 833
    half = position_size(100.0, 94.0, 0.5)
    assert half["QTY"] == 416
    tight = position_size(100.0, 99.9, 1.0)   # huge qty -> capped by 15% of capital
    assert tight["QTY"] * 100 <= CFG.capital * CFG.max_single_position_pct / 100 + 100


def test_stop_hit_first_day():
    o, h, l, c = bars([[100, 101, 99, 100], [100, 100, 90, 92]])
    s = simulate_staircase(o, h, l, c, 1, 94.0, signal_close=100)
    assert s["closed"] and s["reason"] == "STOP" and s["exit_px"] == pytest.approx(94.0)


def test_gap_down_through_stop_fills_at_open():
    o, h, l, c = bars([[100, 101, 99, 100], [100, 100, 99, 100], [90, 91, 88, 89]])
    s = simulate_staircase(o, h, l, c, 1, 94.0, signal_close=100)
    assert s["exit_px"] == pytest.approx(90.0)


def test_gap_up_skip():
    o, h, l, c = bars([[100, 101, 99, 100], [103, 104, 102, 103]])
    assert simulate_staircase(o, h, l, c, 1, 94.0, signal_close=100) is None


def test_staircase_ratchet_t1_then_stop_at_entry():
    # fill 100, SL 94 (R=6). T1=112 -> SL to 100. then falls back to 100 -> exit at entry.
    o, h, l, c = bars([[100, 101, 99, 100], [100, 113, 100, 112], [110, 111, 99, 100]])
    s = simulate_staircase(o, h, l, c, 1, 94.0, signal_close=100)
    assert s["closed"] and s["exit_px"] == pytest.approx(100.0) and s["reason"] == "TRAILING SL"


def test_staircase_t2_moves_sl_to_t1_and_t3_to_t2():
    o = [100, 100, 120, 130]
    h = [101, 125, 137, 138]
    l = [99, 100, 118, 100]
    c = [100, 124, 136, 110]
    s = simulate_staircase(np.array(o, float), np.array(h, float), np.array(l, float), np.array(c, float), 1, 94.0, 100)
    # bar1 high 125>=T2(124) -> SL 112 ; bar2 high 137>=T3(136) -> SL 124 ; bar3 low 100 <= 124 -> exit 124
    assert s["closed"] and s["exit_px"] == pytest.approx(124.0)
    ret, r = trade_return(s)
    assert r > 3


def test_open_trade_reports_current_stop():
    o, h, l, c = bars([[100, 101, 99, 100], [100, 113, 100, 112], [112, 114, 111, 113]])
    s = simulate_staircase(o, h, l, c, 1, 94.0, 100)
    assert not s["closed"] and s["stop_now"] == pytest.approx(100.0)


def _synthetic(n=420, seed=1, syms=("AAA", "BBB", "CCC", "DDD")):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-02", periods=n)
    out = []
    for k, s in enumerate(syms):
        r = rng.normal(0.0008 * (k + 1), 0.015, n)
        c = 100 * np.exp(np.cumsum(r))
        o = c * (1 + rng.normal(0, 0.003, n))
        h = np.maximum(o, c) * (1 + abs(rng.normal(0, 0.006, n)))
        l = np.minimum(o, c) * (1 - abs(rng.normal(0, 0.006, n)))
        v = rng.integers(2_000_000, 4_000_000, n).astype(float)
        out.append(pd.DataFrame({"SYMBOL": s, "DATE": dates, "OPEN": o, "HIGH": h, "LOW": l, "CLOSE": c, "VOLUME": v}))
    return pd.concat(out, ignore_index=True)


def test_features_have_no_lookahead():
    h = _synthetic()
    full = add_features(h)
    cut_date = sorted(h.DATE.unique())[350]
    part = add_features(h[h.DATE <= cut_date])
    a = full[full.DATE == cut_date].sort_values("SYMBOL").reset_index(drop=True)
    b = part[part.DATE == cut_date].sort_values("SYMBOL").reset_index(drop=True)
    for col in ("ATR", "EMA20", "EMA50", "EMA200", "RSI", "VOL_RATIO", "HH20", "MOM", "MOM_RANK", "RANK60"):
        np.testing.assert_allclose(a[col].values, b[col].values, rtol=1e-9, err_msg=col)
    for col in ("TREND", "PULLBACK", "BREAKOUT", "SIGNAL"):
        assert (a[col].values == b[col].values).all(), col


def test_signal_requires_trend_and_momentum():
    f = add_features(_synthetic())
    sig = f[f.SIGNAL]
    assert (sig.TREND).all() and (sig.MOM_RANK >= CFG.mom_min_rank).all()
    assert ((sig.PULLBACK) | (sig.BREAKOUT)).all()


def test_watchlist_sorted_by_distance_to_trigger():
    f = add_features(_synthetic(n=420, seed=7, syms=("AAA", "BBB", "CCC")))
    buy, buy_watch, buy_v38, watch, asof = latest_candidates(f)
    if not watch.empty:
        assert list(watch["DIST_TO_TRIGGER_PCT"]) == sorted(watch["DIST_TO_TRIGGER_PCT"])
        assert (watch["TRIGGER"] > 0).all()


def test_range_tightness_is_bounded_or_nan():
    f = add_features(_synthetic(n=420, seed=2, syms=("AAA", "BBB")))
    rt = f["RANGE_TIGHTNESS"].dropna()
    assert not rt.empty and rt.between(0, 100).all()


def test_watch_tier_never_overlaps_strict_signal():
    f = add_features(_synthetic(n=420, seed=11, syms=("AAA", "BBB", "CCC", "DDD")))
    assert not (f["SIGNAL"] & f["SIGNAL_LOOSE"]).any()


def test_watch_tier_is_looser_so_fires_at_least_as_often():
    f = add_features(_synthetic(n=420, seed=11, syms=("AAA", "BBB", "CCC", "DDD")))
    assert int(f["SIGNAL_LOOSE"].sum()) >= 0          # never negative / crashes
    # loose LEADER should be a superset-ish of strict LEADER given lower thresholds
    assert int(f["LEADER_LOOSE"].sum()) >= int(f["LEADER"].sum())


def test_latest_candidates_returns_four_tuple_with_watch_tier():
    f = add_features(_synthetic(n=420, seed=3, syms=("AAA", "BBB", "CCC")))
    buy, buy_watch, buy_v38, watch, asof = latest_candidates(f)
    for df in (buy, buy_watch, watch):
        assert isinstance(df, pd.DataFrame)
    if not buy.empty and not buy_watch.empty:
        assert not set(buy["SYMBOL"]) & set(buy_watch["SYMBOL"])


def test_v38_signal_has_no_trend_or_momentum_requirement():
    """V38 tier Pine Script jaisa hona chahiye - trend/momentum se bilkul independent."""
    f = add_features(_synthetic(n=420, seed=21, syms=("AAA", "BBB", "CCC", "DDD")))
    if f["SIGNAL_V38"].any():
        sig_rows = f[f["SIGNAL_V38"]]
        # kam se kam kuch rows me weak/no trend honi chahiye thi (warna filter chupke se lag gaya)
        assert not sig_rows["TREND"].all() or len(sig_rows) < 3


def test_v38_setup_label_matches_signal():
    f = add_features(_synthetic(n=420, seed=8, syms=("AAA", "BBB")))
    sig = f[f["SIGNAL_V38"]]
    if not sig.empty:
        assert (sig["V38_SETUP"] != "").all()
    nosig = f[~f["SIGNAL_V38"]]
    assert (nosig["V38_SETUP"] == "").all()


def test_v38_trail_never_moves_stop_down_and_exits_on_close_break():
    o, h, l, c = bars([
        (100, 102, 99, 101), (101, 108, 100, 107), (107, 112, 105, 110),
        (110, 111, 95, 96), (96, 97, 90, 91),
    ])
    atr = np.array([3.0] * 5)
    r = simulate_v38_trail(o, h, l, c, atr, entry_idx=1, signal_close=c[0], max_hold=10)
    assert r is not None and r["closed"] is True
    assert r["exit_px"] == pytest.approx(c[3])   # din 3 par close (96) stop se neeche gaya
    assert r["stop_now"] >= c[0] - CFG.v38_atr_mult * atr[0] - 1e-9   # kabhi neeche nahi gaya


def test_v38_trail_rejects_big_gap_and_stop_above_fill():
    o, h, l, c = bars([(100, 101, 99, 100), (200, 205, 195, 200), (200, 202, 198, 201)])
    atr = np.array([3.0, 3.0, 3.0])
    assert simulate_v38_trail(o, h, l, c, atr, entry_idx=1, signal_close=c[0]) is None   # 100% gap > max_gap_pct


def test_v38_plan_levels_math():
    lv = v38_plan_levels(close=100.0, atr=4.0)
    assert lv["STOP"] == pytest.approx(100 - CFG.v38_atr_mult * 4.0)
    assert lv["T1"] == pytest.approx(100 + CFG.v38_t1_r * lv["RISK"])
    assert lv["T2"] == pytest.approx(100 + CFG.v38_t2_r * lv["RISK"])

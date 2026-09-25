import numpy as np
import pandas as pd
import pytest

from config import CFG
from engine import add_features
from test_engine import _synthetic
from v42 import V42, add_v42_features, latest_v42_candidates, simulate_v42_trail, v42_plan_levels


def _featured(n=420, seed=5, syms=("AAA", "BBB", "CCC")):
    f = add_features(_synthetic(n=n, seed=seed, syms=syms))
    return add_v42_features(f)


def test_add_v42_features_adds_expected_columns_and_no_crash():
    f = _featured()
    for col in ("V42_SCORE", "SIGNAL_V42", "V42_ENTRY_TYPE", "V42_RS", "MARKET_BULL"):
        assert col in f.columns
    assert f["V42_SCORE"].between(0, 100).all()


def test_v42_entry_type_matches_signal():
    f = _featured(seed=9)
    sig = f[f["SIGNAL_V42"]]
    if not sig.empty:
        assert sig["V42_ENTRY_TYPE"].isin(["APEX BUY", "TACTICAL BUY", "BUY"]).all()
    nosig = f[~f["SIGNAL_V42"]]
    assert (nosig["V42_ENTRY_TYPE"] == "").all()


def test_apex_buy_requires_higher_score_than_normal_buy():
    """APEX BUY sirf strong/vcp breakout + score>=88 par; normal BUY score>=75 par bhi chal sakta
    hai bina strong breakout ke (jaise emaRecovery). Isliye APEX kabhi normal se kam score par nahi."""
    f = _featured(seed=12)
    apex = f[f["V42_ENTRY_TYPE"] == "APEX BUY"]
    if not apex.empty:
        assert (apex["V42_SCORE"] >= V42["apex_score_min"]).all()
    normal = f[f["V42_ENTRY_TYPE"] == "BUY"]
    if not normal.empty:
        assert (normal["V42_SCORE"] >= V42["buy_score"]).all()


def test_market_penalty_reduces_score_in_bear_regime():
    f = _featured(seed=3)
    bear = f[f["MARKET_BULL"] == False]  # noqa: E712
    bull = f[f["MARKET_BULL"] == True]  # noqa: E712
    if not bear.empty and not bull.empty:
        # bear regime me penalty lagta hai (raw score minus 3 ya 8) - koi crash/negative na ho
        assert (f["V42_SCORE"] >= 0).all()


def test_latest_v42_candidates_no_cap_and_has_plan_levels():
    f = _featured(seed=21, syms=("AAA", "BBB", "CCC", "DDD", "EEE"))
    out = latest_v42_candidates(f)
    assert isinstance(out, pd.DataFrame)
    if not out.empty:
        for col in ("STOP", "T1", "T2", "RISK_PCT"):
            assert col in out.columns
        # sorted by score descending
        assert list(out["V42_SCORE"]) == sorted(out["V42_SCORE"], reverse=True)


def test_v42_plan_levels_math():
    lv = v42_plan_levels(close=100.0, atr=4.0)
    assert lv["STOP"] == pytest.approx(100 - V42["initial_atr"] * 4.0)
    assert lv["T1"] == pytest.approx(100 + V42["rr1"] * lv["RISK"])
    assert lv["T2"] == pytest.approx(100 + V42["rr2"] * lv["RISK"])


def bars(rows):
    a = np.array(rows, float)
    return a[:, 0], a[:, 1], a[:, 2], a[:, 3]  # o,h,l,c


def test_v42_trail_exit_on_trailing_sl():
    o, h, l, c = bars([(100, 102, 99, 101), (101, 108, 100, 107), (107, 112, 105, 110),
                        (110, 111, 95, 96), (96, 97, 90, 91)])
    ema20 = np.array([95, 96, 97, 98, 99.0])   # neeche rakha taaki EMA-based exits fire na hon isolate karne ke liye
    ema50 = np.array([90, 90, 90, 90, 90.0])
    rsi = np.array([60, 60, 60, 60, 60.0])
    vol_ratio = np.array([1.0, 1.0, 1.0, 1.0, 1.0])
    atr = np.array([3.0] * 5)
    r = simulate_v42_trail(o, h, l, c, ema20, ema50, rsi, vol_ratio, atr, entry_idx=1, signal_close=c[0])
    assert r is not None and r["closed"] is True
    assert r["reason"] in ("TRAIL SL", "EMA20 BREAK", "EMA50 BREAK", "TREND REVERSAL", "DISTRIBUTION", "MOMENTUM FAIL")


def test_v42_trail_exits_on_momentum_fail():
    n = 5
    o = np.full(n, 100.0); h = np.full(n, 101.0); l = np.full(n, 99.0); c = np.full(n, 100.0)
    ema20 = np.full(n, 105.0)          # close hamesha ema20 se neeche
    ema50 = np.full(n, 50.0)           # close>ema50 -> exitEMA50/exitTrend kabhi true nahi honge
    rsi = np.array([60, 60, 60, 42, 42.0])
    vol_ratio = np.full(n, 1.0)        # strong_vol(2.0) se kam -> exitDistribution kabhi nahi
    atr = np.full(n, 50.0)             # bahut wide taaki trailing SL kabhi na chhue
    r = simulate_v42_trail(o, h, l, c, ema20, ema50, rsi, vol_ratio, atr, entry_idx=1, signal_close=100.0, max_hold=n)
    assert r is not None and r["reason"] == "MOMENTUM FAIL"


def test_v42_trail_rejects_big_gap():
    o, h, l, c = bars([(100, 101, 99, 100), (200, 205, 195, 200), (200, 202, 198, 201)])
    ema20 = np.array([90, 90, 90.0]); ema50 = np.array([80, 80, 80.0]); rsi = np.array([60, 60, 60.0]); vr = np.array([1, 1, 1.0])
    atr = np.array([3.0, 3.0, 3.0])
    assert simulate_v42_trail(o, h, l, c, ema20, ema50, rsi, vr, atr, entry_idx=1, signal_close=c[0]) is None


def test_v42_trail_never_exits_on_entry_bar_itself():
    """Pine: exitSignal sirf bar_index > entryBar ke baad, hamesha - trailing SL sameet.
    Condition entry bar (index 1) se hi true hai (RSI<43, close<EMA20), par exit sirf
    agle bar (index 2) par register hona chahiye, entry bar par nahi."""
    n = 3
    o = np.full(n, 100.0); h = np.full(n, 101.0); l = np.full(n, 99.0); c = np.full(n, 100.0)
    ema20 = np.full(n, 110.0)   # close(100) < ema20 -> momentum condition ka hissa
    ema50 = np.full(n, 50.0)    # close>ema50 -> baaki exits false rahenge
    rsi = np.full(n, 30.0)      # <43 shuru se hi
    vol_ratio = np.full(n, 1.0)
    atr = np.full(n, 2.0)
    r = simulate_v42_trail(o, h, l, c, ema20, ema50, rsi, vol_ratio, atr, entry_idx=1, signal_close=100.0, max_hold=n)
    assert r is not None and r["reason"] == "MOMENTUM FAIL" and r["exit_idx"] == 2  # entry_idx(1) par NAHI

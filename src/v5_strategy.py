"""RY APEX MATRIX V5 strategy research layer.

This module adds transparent, independently testable swing setups to the existing
NSE Auto Sheet engine. It does not replace the established strict signal tier.
All calculations use completed daily bars; weekly features are resampled from
available daily OHLCV and shifted to avoid using an unfinished week.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _wilder(x: pd.Series, n: int) -> pd.Series:
    return x.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def _pivot_low_flags(low: pd.Series, left: int = 3, right: int = 3) -> pd.Series:
    """Confirmed pivot lows; confirmation arrives 'right' bars after the low."""
    vals = low.to_numpy(dtype=float)
    out = np.zeros(len(vals), dtype=bool)
    for i in range(left, len(vals) - right):
        window = vals[i-left:i+right+1]
        if np.isfinite(vals[i]) and vals[i] == np.nanmin(window) and np.sum(window == vals[i]) == 1:
            out[i + right] = True
    return pd.Series(out, index=low.index)


def _weekly_bullish(d: pd.DataFrame) -> pd.Series:
    """Map last completed week's EMA25/Supertrend state onto each daily row."""
    x = d.set_index("DATE")[["OPEN", "HIGH", "LOW", "CLOSE"]].resample("W-FRI").agg(
        {"OPEN": "first", "HIGH": "max", "LOW": "min", "CLOSE": "last"}
    ).dropna()
    if x.empty:
        return pd.Series(False, index=d.index)
    x["WEMA25"] = x["CLOSE"].ewm(span=25, adjust=False, min_periods=25).mean()
    pc = x["CLOSE"].shift(1)
    tr = pd.concat([(x["HIGH"] - x["LOW"]), (x["HIGH"] - pc).abs(),
                    (x["LOW"] - pc).abs()], axis=1).max(axis=1)
    atr = _wilder(tr, 7)
    mid = (x["HIGH"] + x["LOW"]) / 2
    upper, lower = mid + 2 * atr, mid - 2 * atr
    final_upper = pd.Series(index=x.index, dtype=float)
    final_lower = pd.Series(index=x.index, dtype=float)
    st = pd.Series(index=x.index, dtype=float)
    bullish = pd.Series(index=x.index, dtype=bool)
    for i in range(len(x)):
        if not np.isfinite(atr.iloc[i]):
            continue
        basic_u, basic_l = upper.iloc[i], lower.iloc[i]
        if i == 0 or not np.isfinite(final_upper.iloc[i-1]):
            final_upper.iloc[i], final_lower.iloc[i] = basic_u, basic_l
            st.iloc[i], bullish.iloc[i] = basic_u, False
            continue
        prev_close = x["CLOSE"].iloc[i-1]
        prev_fu, prev_fl = final_upper.iloc[i-1], final_lower.iloc[i-1]
        final_upper.iloc[i] = basic_u if (basic_u < prev_fu or prev_close > prev_fu) else prev_fu
        final_lower.iloc[i] = basic_l if (basic_l > prev_fl or prev_close < prev_fl) else prev_fl
        prev_st = st.iloc[i-1]
        if prev_st == prev_fu:
            st.iloc[i] = final_upper.iloc[i] if x["CLOSE"].iloc[i] <= final_upper.iloc[i] else final_lower.iloc[i]
        else:
            st.iloc[i] = final_lower.iloc[i] if x["CLOSE"].iloc[i] >= final_lower.iloc[i] else final_upper.iloc[i]
        bullish.iloc[i] = st.iloc[i] == final_lower.iloc[i]
    # only previous completed weekly candle; merge_asof backward
    w = pd.DataFrame({"WEEK_BULL": (x["CLOSE"] > x["WEMA25"]) & bullish}).shift(1)
    daily = pd.DataFrame({"DATE": pd.to_datetime(d["DATE"]), "_i": d.index}).sort_values("DATE")
    weekly = w.reset_index().rename(columns={w.index.name or "index": "WEEK_DATE"})
    weekly["WEEK_DATE"] = pd.to_datetime(weekly.iloc[:, 0])
    weekly = weekly[["WEEK_DATE", "WEEK_BULL"]].dropna()
    mapped = pd.merge_asof(daily, weekly, left_on="DATE", right_on="WEEK_DATE", direction="backward")
    return mapped.set_index("_i")["WEEK_BULL"].reindex(d.index).fillna(False).astype(bool)


def _one_symbol(d: pd.DataFrame) -> pd.DataFrame:
    d = d.sort_values("DATE").reset_index(drop=True).copy()
    o, h, l, c, v = (d[k].astype(float) for k in ("OPEN", "HIGH", "LOW", "CLOSE", "VOLUME"))
    prev_c = c.shift(1)
    tr = pd.concat([h-l, (h-prev_c).abs(), (l-prev_c).abs()], axis=1).max(axis=1)
    atr = d["ATR"] if "ATR" in d else _wilder(tr, 14)
    e20 = d["EMA20"] if "EMA20" in d else c.ewm(span=20, adjust=False, min_periods=20).mean()
    e50 = d["EMA50"] if "EMA50" in d else c.ewm(span=50, adjust=False, min_periods=50).mean()
    e200 = d["EMA200"] if "EMA200" in d else c.ewm(span=200, adjust=False, min_periods=200).mean()
    rsi = d["RSI"] if "RSI" in d else pd.Series(np.nan, index=d.index)
    adx = d["ADX"] if "ADX" in d else pd.Series(np.nan, index=d.index)
    vr = d["VOL_RATIO"] if "VOL_RATIO" in d else v / v.rolling(20, min_periods=15).mean()

    trend = (c > e20) & (e20 > e50) & (e50 > e200)
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    hist = macd - macd.ewm(span=9, adjust=False).mean()
    d["V5_MACD_HIST"] = hist
    # Confirmed pivot events are causal: a low is marked only after 'right' bars.
    # Vectorized last-two-pivot comparison avoids an O(n^2) scan per symbol.
    piv = _pivot_low_flags(l)
    pivot_event = l.where(piv)
    last_pivot = pivot_event.ffill()
    pivot_group = piv.cumsum()
    previous_pivot = last_pivot.shift(1).groupby(pivot_group).transform("first")
    higher_low = last_pivot > previous_pivot

    d["V5_TREND"] = trend
    d["V5_HIGHER_LOW"] = higher_low
    d["V5_TRIPLE_CONFLUENCE"] = trend & higher_low & (hist > 0) & (hist > hist.shift(1)) & (adx >= 18)

    # True contraction is approximated by successively shrinking 10/10/10-bar ranges
    r10 = (h.rolling(10).max() - l.rolling(10).min()) / c
    d["V5_VCP"] = (r10 < r10.shift(10) * 0.85) & (r10.shift(10) < r10.shift(20) * 0.90) & (atr < atr.rolling(20).mean()) & (vr < 1.3) & trend
    resistance20 = h.shift(1).rolling(20, min_periods=15).max()
    d["V5_RESISTANCE20"] = resistance20
    d["V5_PRE_BREAKOUT"] = d["V5_VCP"] & ((resistance20 - c) / c).between(0, 0.03) & (hist > hist.shift(1)) & (rsi > 50)
    d["V5_BREAKOUT"] = (c > resistance20) & (c.shift(1) <= resistance20.shift(1)) & (vr >= 1.5) & trend

    # Pullback and EMA gap expansion
    touch = (l <= e20 * 1.01) | (l <= e50 * 1.01)
    d["V5_PULLBACK"] = trend & touch & (c > o) & (c > e20) & rsi.between(45, 68)
    gap = (e20 - e50) / e50
    d["V5_EMA_GAP_EXPANDING"] = trend & (gap > gap.shift(5))

    # Stage 2: rising 200 EMA and breakout of 50-session high
    d["V5_STAGE2"] = (c > e200) & (e200 > e200.shift(20)) & (e50 > e200) & (c > h.shift(1).rolling(50, min_periods=40).max()) & (vr >= 1.5)

    # Bull flag: pole over 10 bars, then tight 5-10 bar retracement, breakout over flag high
    pole_gain = c.shift(5) / c.shift(15) - 1
    flag_high = h.shift(1).rolling(8, min_periods=6).max()
    flag_low = l.shift(1).rolling(8, min_periods=6).min()
    pole_top = h.shift(5).rolling(5, min_periods=4).max()
    retrace = (pole_top - flag_low) / (pole_top - c.shift(15)).replace(0, np.nan)
    flag_setup = (pole_gain >= 0.08) & (retrace <= 0.50) & (vr < 1.3) & (c > e20)
    d["V5_BULL_FLAG"] = flag_setup.shift(1).fillna(False) & (c > flag_high) & (vr >= 1.5)

    # Cup & handle pattern approximation with causal rolling windows
    left_rim = h.shift(30).rolling(30, min_periods=25).max()
    cup_bottom = l.shift(5).rolling(25, min_periods=20).min()
    cup_depth = (left_rim - cup_bottom) / left_rim
    right_rim_ok = c >= left_rim * 0.95
    handle_low = l.rolling(5, min_periods=4).min()
    handle_ok = (handle_low >= left_rim * 0.90) & (c < left_rim)
    cup_setup = cup_depth.between(0.10, 0.35) & right_rim_ok & handle_ok
    d["V5_CUP_HANDLE"] = cup_setup.shift(1).fillna(False) & (c > left_rim) & (c.shift(1) <= left_rim.shift(1)) & (vr >= 1.5)

    # High-volume upper-range accumulation proxy (not a real tick/price-binned volume profile)
    midpoint = (h.rolling(30).max() + l.rolling(30).min()) / 2
    upper_volume = v.where(c >= midpoint, 0).rolling(30).sum()
    lower_volume = v.where(c < midpoint, 0).rolling(30).sum()
    d["V5_REACCUMULATION"] = (upper_volume > lower_volume * 1.5) & trend & (c > midpoint) & (vr < 1.5)

    # Risk engine: structure + ATR; no look-ahead for prior swing low
    swing_low = l.shift(1).rolling(10, min_periods=5).min()
    atr_stop = c - 2.0 * atr
    structural_stop = swing_low
    d["V5_STOP"] = np.maximum(atr_stop, structural_stop.where(structural_stop < c, atr_stop))
    d["V5_RISK_PCT"] = (c - d["V5_STOP"]) / c * 100
    d["V5_T1"] = c + 2 * (c - d["V5_STOP"])
    d["V5_T2"] = c + 3 * (c - d["V5_STOP"])
    d["V5_T3"] = c + 4 * (c - d["V5_STOP"])
    d["V5_RR"] = 3.0

    # Weekly trend uses completed weekly data, calculated outside symbol grouped frame
    d["V5_WEEKLY_BULL"] = False
    return d


def add_v5_features(features: pd.DataFrame, benchmark: pd.DataFrame | None = None) -> pd.DataFrame:
    """Add V5 features to multi-symbol OHLCV/features. Optional benchmark: DATE,CLOSE."""
    parts = [_one_symbol(g) for _, g in features.groupby("SYMBOL", sort=False) if len(g) >= 220]
    if not parts:
        raise ValueError("V5: insufficient symbol history")
    f = pd.concat(parts, ignore_index=True)
    weekly = []
    for sym, g in f.groupby("SYMBOL", sort=False):
        w = _weekly_bullish(g)
        x = g[["SYMBOL", "DATE"]].copy()
        x["V5_WEEKLY_BULL"] = w.to_numpy()
        weekly.append(x)
    wk = pd.concat(weekly, ignore_index=True)
    f = f.drop(columns=["V5_WEEKLY_BULL"]).merge(wk, on=["SYMBOL", "DATE"], how="left")
    if benchmark is not None and not benchmark.empty:
        b = benchmark[["DATE", "CLOSE"]].drop_duplicates("DATE").sort_values("DATE").copy()
        b["BENCH_ROC20"] = b.CLOSE.pct_change(20) * 100
        f = f.merge(b[["DATE", "BENCH_ROC20"]], on="DATE", how="left")
        f["STOCK_ROC20"] = f.groupby("SYMBOL").CLOSE.pct_change(20) * 100
        f["V5_RS_STRONG"] = (f["STOCK_ROC20"] > f["BENCH_ROC20"]) & (f["STOCK_ROC20"] > 0)
    else:
        # Never silently call a universe average "NIFTY 500"; expose unavailable benchmark honestly.
        f["BENCH_ROC20"] = np.nan
        f["STOCK_ROC20"] = f.groupby("SYMBOL").CLOSE.pct_change(20) * 100
        f["V5_RS_STRONG"] = False

    setup_cols = ["V5_TRIPLE_CONFLUENCE", "V5_BULL_FLAG", "V5_VCP", "V5_PRE_BREAKOUT",
                  "V5_PULLBACK", "V5_STAGE2", "V5_CUP_HANDLE", "V5_BREAKOUT",
                  "V5_REACCUMULATION", "V5_WEEKLY_BULL", "V5_RS_STRONG"]
    f["V5_SETUP_COUNT"] = f[setup_cols].fillna(False).astype(bool).sum(axis=1)
    f["V5_SCORE"] = (
        f["V5_TREND"].fillna(False).astype(int) * 15
        + f["V5_HIGHER_LOW"].fillna(False).astype(int) * 10
        + (f["V5_MACD_HIST"] > 0).fillna(False).astype(int) * 10
        + f["V5_VCP"].fillna(False).astype(int) * 10
        + (f["VOL_RATIO"] >= 1.5).fillna(False).astype(int) * 10
        + f["V5_RS_STRONG"].fillna(False).astype(int) * 10
        + f["V5_WEEKLY_BULL"].fillna(False).astype(int) * 10
        + f["V5_REACCUMULATION"].fillna(False).astype(int) * 10
        + (f["V5_SETUP_COUNT"] > 0).astype(int) * 10
        + (f["ADX"] >= 18).fillna(False).astype(int) * 5
    ).clip(0, 100)
    f["V5_BUY"] = (
        (f["V5_SCORE"] >= 75)
        & (f["V5_SETUP_COUNT"] >= 2)
        & f["V5_TREND"]
        & (f["V5_RISK_PCT"].between(0.5, 8.0))
        & (f["V5_T1"] > f["CLOSE"])
    )
    f["V5_SETUP"] = np.select(
        [f["V5_CUP_HANDLE"], f["V5_BULL_FLAG"], f["V5_STAGE2"], f["V5_BREAKOUT"],
         f["V5_PULLBACK"], f["V5_PRE_BREAKOUT"], f["V5_TRIPLE_CONFLUENCE"]],
        ["CUP & HANDLE", "BULL FLAG", "STAGE 2", "BREAKOUT", "EMA PULLBACK", "VCP PRE-BREAKOUT", "TRIPLE CONFLUENCE"],
        default="MULTI-CONFLUENCE"
    )
    return f


def latest_v5_candidates(f: pd.DataFrame) -> pd.DataFrame:
    d = f[f.DATE == f.DATE.max()].copy()
    d = d[d["V5_BUY"] & d["ATR"].notna() & (d["TURNOVER_CR"] >= 5)].copy()
    return d.sort_values(["V5_SCORE", "V5_SETUP_COUNT", "MOM_RANK"], ascending=False)

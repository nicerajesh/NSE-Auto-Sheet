"""V42 tier: Pine Script 'RY APEX MATRIX V42 - PRO SWING ENGINE' ka hoobehoo port.

IMPORTANT: V42 ka Market Regime aur Relative Strength NIFTY index se calculate hote hain. Is
environment me NIFTY index ka seedha data available nahi (sirf per-stock OHLCV milta hai NSE
bhavcopy se). Isliye yahan apna EQUAL-WEIGHT UNIVERSE PROXY use kiya gaya hai (jitne bhi tradable
stocks hain unka daily average return, cumulative index bana kar) - NIFTY ki jagah, wahi concept.
Ye proxy pehle bhi test hua tha (regime breadth filter) aur real edge dikha chuka hai.

Baaki sab - score engine, VCP/compression, accumulation, teen BUY tier (APEX/TACTICAL/BUY),
chhe exit conditions - Pine V42 jaisa hi hai.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import CFG

V42 = dict(
    rsi_min=50.0, rsi_max=72.0, adx_min=18.0,
    breakout_vol=1.30, strong_vol=2.00, dry_up_ratio=0.75,
    res_lookback=20, breakout_buffer_pct=0.10, near_res_pct=3.0,
    min_body_ratio=0.40, min_close_pos=0.65,
    vcp_len=20, compression_level=0.80, accum_lookback=10,
    initial_atr=2.5, trail_atr=2.5, max_ext_atr=3.0,
    rr1=2.0, rr2=3.0,
    buy_score=75, apex_score_min=88, tactical_score_min=82,
    cooldown_bars=5,
)


def _wilder(x: pd.Series, n: int) -> pd.Series:
    return x.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


# --------------------------------------------------------------------------- per-symbol features
def _symbol_v42(d: pd.DataFrame) -> pd.DataFrame:
    d = d.sort_values("DATE").reset_index(drop=True)
    o, h, l, c = d["OPEN"], d["HIGH"], d["LOW"], d["CLOSE"]
    atr, e20, e50, e200, rsi, vr = d["ATR"], d["EMA20"], d["EMA50"], d["EMA200"], d["RSI"], d["VOL_RATIO"]

    d["V42_STRONG_TREND"] = (c > e20) & (e20 > e50) & (e50 > e200) & (e20 > e20.shift(5)) & (e50 > e50.shift(5))
    d["V42_HEALTHY_TREND"] = (c > e50) & (e50 > e200)
    d["V42_BULL_TREND"] = c > e50

    rng = h - l
    body_ratio = (c - o).abs() / rng.replace(0, np.nan)
    close_pos = (c - l) / rng.replace(0, np.nan)
    bull_candle = c > o
    d["_BULL_QUALITY"] = bull_candle & (body_ratio >= V42["min_body_ratio"]) & (close_pos >= V42["min_close_pos"])
    d["_CLOSE_POS"] = close_pos

    resistance = h.shift(1).rolling(V42["res_lookback"], min_periods=15).max()
    breakout_level = resistance * (1 + V42["breakout_buffer_pct"] / 100)
    is_breakout = c > breakout_level
    res_dist = np.where(c >= resistance, (c - resistance) / resistance * 100, (resistance - c) / resistance * 100)
    d["_RESISTANCE"] = resistance
    d["V42_IS_BREAKOUT"] = is_breakout
    d["V42_NEAR_RESISTANCE"] = (c < resistance) & (res_dist <= V42["near_res_pct"])
    d["_RES_DIST"] = res_dist

    vol_strong = vr >= V42["strong_vol"]
    vol_confirmed = vr >= V42["breakout_vol"]
    vol_dry = vr <= V42["dry_up_ratio"]
    d["_VOL_STRONG"], d["_VOL_CONFIRMED"], d["_VOL_NORMAL"], d["_VOL_DRY"] = vol_strong, vol_confirmed, vr >= 0.80, vol_dry
    d["_VOL_EXPANSION"] = (vr.shift(1) <= V42["dry_up_ratio"]) & vol_confirmed
    d["_VOL_ACCEL"] = (vr > vr.shift(1)) & (vr >= 1.0)

    avg_range = rng.rolling(V42["vcp_len"], min_periods=10).mean()
    atr_fast = atr.rolling(5, min_periods=3).mean()
    atr_slow = atr.rolling(V42["vcp_len"], min_periods=10).mean()
    vcp_potential = (avg_range > 0) & (rng <= avg_range * V42["compression_level"]) & (atr_fast < atr_slow)
    vcp_confirmed = vcp_potential & vol_dry
    d["V42_VCP_POTENTIAL"], d["V42_VCP_CONFIRMED"] = vcp_potential, vcp_confirmed
    d["V42_VCP_BREAKOUT"] = vcp_confirmed & is_breakout & vol_confirmed

    recent_high = h.shift(1).rolling(V42["accum_lookback"], min_periods=5).max()
    recent_low = l.shift(1).rolling(V42["accum_lookback"], min_periods=5).min()
    range_width = np.where(recent_low > 0, (recent_high - recent_low) / recent_low * 100, 999.0)
    d["V42_ACCUMULATION"] = d["V42_HEALTHY_TREND"] & vol_dry & (range_width <= 12) & (c >= e50)

    rsi_healthy = rsi.between(V42["rsi_min"], V42["rsi_max"])
    rsi_recovery = (rsi > 50) & (rsi > rsi.shift(1))
    d["_RSI_HEALTHY"], d["_RSI_STRONG"], d["_RSI_RECOVERY"] = rsi_healthy, rsi.between(58, 72), rsi_recovery

    d["V42_PULLBACK"] = d["V42_HEALTHY_TREND"] & (l <= e20 * 1.03) & (c >= e20 * 0.98) & rsi_recovery
    d["V42_EMA_RECOVERY"] = (c > e20) & (c.shift(1) <= e20.shift(1)) & bull_candle & rsi_recovery & (vr >= 1.0)

    d["V42_STRONG_BREAKOUT"] = is_breakout & vol_strong & d["_BULL_QUALITY"] & (c > e20) & (c > e50)
    d["V42_CONFIRMED_BREAKOUT"] = is_breakout & vol_confirmed & bull_candle & (close_pos >= 0.60) & (c > e50)
    d["V42_EARLY_BREAKOUT"] = is_breakout & (vr >= 1.0) & bull_candle & (c > e20)

    ext_atr = (c - e20) / atr.replace(0, np.nan)
    d["_NOT_OVER_EXT"] = ext_atr <= V42["max_ext_atr"]
    d["_ATR_PCT"] = atr / c.replace(0, np.nan) * 100

    up_move, down_move = h.diff(), -l.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    atrw = _wilder(tr, 14)
    pdi = 100 * _wilder(plus_dm, 14) / atrw.replace(0, np.nan)
    mdi = 100 * _wilder(minus_dm, 14) / atrw.replace(0, np.nan)
    d["_ADX_GOOD"] = (d["ADX"] >= V42["adx_min"]) & (pdi > mdi)
    d["_ADX_STRONG"] = (d["ADX"] >= 25) & (pdi > mdi)

    d["_ROC20"] = c.pct_change(20) * 100
    return d


# --------------------------------------------------------------------------- market regime proxy
def _market_regime(f: pd.DataFrame) -> pd.DataFrame:
    """Apna equal-weight universe index - NIFTY ka proxy (upar docstring me wajah likhi hai)."""
    r = f[["SYMBOL", "DATE", "CLOSE", "JUMP"]].sort_values(["SYMBOL", "DATE"]).copy()
    r["RET1"] = r.groupby("SYMBOL")["CLOSE"].pct_change()
    r.loc[r["JUMP"] == 1, "RET1"] = np.nan
    ew = r.groupby("DATE")["RET1"].mean().fillna(0)
    idx = (1 + ew).cumprod() * 1000
    mkt = pd.DataFrame({"IDX": idx})
    mkt["IDX_EMA20"] = mkt["IDX"].ewm(span=20, adjust=False).mean()
    mkt["IDX_EMA50"] = mkt["IDX"].ewm(span=50, adjust=False).mean()
    mkt["IDX_EMA200"] = mkt["IDX"].ewm(span=200, adjust=False).mean()
    mkt["IDX_ROC20"] = mkt["IDX"].pct_change(20) * 100
    mkt["MARKET_BULL"] = (mkt.IDX > mkt.IDX_EMA20) & (mkt.IDX_EMA20 > mkt.IDX_EMA50) & (mkt.IDX_EMA50 > mkt.IDX_EMA200)
    mkt["MARKET_NEUTRAL"] = (mkt.IDX > mkt.IDX_EMA50) & ~mkt["MARKET_BULL"]
    return mkt.reset_index().rename(columns={"index": "DATE"})


# --------------------------------------------------------------------------- main entrypoint
def add_v42_features(f: pd.DataFrame) -> pd.DataFrame:
    """f: engine.add_features() ka output (SYMBOL, DATE, OHLCV, ATR, EMA20/50/200, RSI, ADX,
    VOL_RATIO, JUMP zaroori). Score, RS aur teeno BUY tier (APEX/TACTICAL/BUY) jodta hai."""
    parts = [_symbol_v42(g) for _, g in f.groupby("SYMBOL", sort=False)]
    f = pd.concat(parts, ignore_index=True)

    mkt = _market_regime(f)
    f = f.merge(mkt, on="DATE", how="left")
    f["V42_RS"] = f["_ROC20"] - f["IDX_ROC20"]
    rs_strong, rs_positive = f["V42_RS"] >= 5.0, f["V42_RS"] > 0
    rsi_recovery = f["_RSI_RECOVERY"]

    trend_score = np.select([f.V42_STRONG_TREND, f.V42_HEALTHY_TREND, f.V42_BULL_TREND], [25, 19, 12], default=0)
    rs_score = np.select([rs_strong, rs_positive, f.V42_RS > -3], [15, 11, 6], default=0)
    momentum_score = np.select(
        [f._ADX_STRONG & f._RSI_STRONG, f._ADX_GOOD & f._RSI_HEALTHY, f._RSI_HEALTHY | rsi_recovery],
        [15, 12, 8], default=3)
    volume_score = np.select(
        [f._VOL_STRONG, f._VOL_EXPANSION, f._VOL_CONFIRMED, f._VOL_ACCEL, f._VOL_DRY, f._VOL_NORMAL],
        [15, 15, 12, 9, 8, 5], default=2)
    structure_score = np.select(
        [f.V42_VCP_BREAKOUT, f.V42_STRONG_BREAKOUT, f.V42_CONFIRMED_BREAKOUT, f.V42_VCP_CONFIRMED, f.V42_ACCUMULATION,
         f.V42_NEAR_RESISTANCE, f.V42_PULLBACK, f.V42_EMA_RECOVERY],
        [15, 15, 13, 11, 10, 8, 8, 7], default=3)
    risk_score = np.where(f._NOT_OVER_EXT,
                           np.select([f._ATR_PCT <= 4, f._ATR_PCT <= 7, f._ATR_PCT <= 10], [15, 12, 9], default=6), 2)
    raw_score = trend_score + rs_score + momentum_score + volume_score + structure_score + risk_score
    market_penalty = np.select([f.MARKET_BULL, f.MARKET_NEUTRAL], [0, 3], default=8)
    f["V42_SCORE"] = np.clip(raw_score - market_penalty, 0, None)

    not_over_ext = f["_NOT_OVER_EXT"]
    normal_setup = f.V42_CONFIRMED_BREAKOUT | f.V42_STRONG_BREAKOUT | f.V42_VCP_BREAKOUT | f.V42_EMA_RECOVERY
    normal_buy = (f.V42_SCORE >= V42["buy_score"]) & normal_setup & not_over_ext
    apex_buy = (f.V42_SCORE >= V42["apex_score_min"]) & (f.V42_STRONG_BREAKOUT | f.V42_VCP_BREAKOUT) & not_over_ext
    tactical_buy = (f.V42_STRONG_BREAKOUT | f.V42_VCP_BREAKOUT) & (f.V42_SCORE >= V42["tactical_score_min"]) & not_over_ext
    f["SIGNAL_V42"] = apex_buy | tactical_buy | normal_buy
    f["V42_ENTRY_TYPE"] = np.select([apex_buy, tactical_buy, normal_buy], ["APEX BUY", "TACTICAL BUY", "BUY"], default="")
    return f


def v42_plan_levels(close: float, atr: float) -> dict:
    stop = close - V42["initial_atr"] * atr
    risk = close - stop
    return {"STOP": stop, "RISK": risk, "RISK_PCT": risk / close * 100 if close else np.nan,
            "T1": close + V42["rr1"] * risk, "T2": close + V42["rr2"] * risk}


def latest_v42_candidates(f: pd.DataFrame) -> pd.DataFrame:
    """Latest date ke SIGNAL_V42 rows, plan levels ke saath. Koi cap nahi - jitne bhi V42
    signal aayein, sab (user ne explicitly kaha: koi block nahi, sirf apni sheet me)."""
    asof = f["DATE"].max()
    d = f[f["DATE"] == asof].copy()
    tradable = (d["TURNOVER_CR"] >= CFG.min_turnover_cr) & (d["JUMP_RECENT"] == 0) & d["ATR"].notna()
    d = d[tradable & d["SIGNAL_V42"]].copy()
    if d.empty:
        return d
    lv = d.apply(lambda r: pd.Series(v42_plan_levels(r["CLOSE"], r["ATR"])), axis=1)
    d = pd.concat([d, lv], axis=1)
    d = d[(d["RISK_PCT"] >= CFG.min_risk_pct) & (d["RISK_PCT"] <= CFG.max_risk_pct)]
    return d.sort_values("V42_SCORE", ascending=False)


def simulate_v42_trail(o, h, l, c, ema20, ema50, rsi, vol_ratio, atr, entry_idx: int, signal_close: float,
                        max_hold: int = 252) -> dict | None:
    """V42 ka poora exit engine: trailing SL + EMA20 break (2 closes) + EMA50 break + trend
    reversal + distribution + momentum fail. Pehla jo bhi trigger ho, wahi exit reason."""
    n = len(o)
    if entry_idx >= n:
        return None
    fill = float(o[entry_idx])
    if not np.isfinite(fill):
        return None
    if (fill / signal_close - 1) * 100 > CFG.max_gap_pct:
        return None
    stop0 = signal_close - V42["initial_atr"] * atr[max(entry_idx - 1, 0)]
    if stop0 >= fill:
        return None
    trail = stop0
    last = min(n, entry_idx + max_hold)
    for j in range(entry_idx, last):
        calc_trail = float(c[j]) - V42["trail_atr"] * float(atr[j])
        if calc_trail > trail:
            trail = calc_trail
        exit_trail = float(c[j]) < trail
        exit_ema20 = j > entry_idx and c[j] < ema20[j] and c[j - 1] < ema20[j - 1] and c[j] < o[j]
        exit_ema50 = c[j] < ema50[j] and ema20[j] < ema50[j]
        exit_trend = j > 0 and ema20[j] < ema50[j] and ema50[j] < ema50[j - 1]
        exit_dist = j > 0 and c[j] < o[j] and vol_ratio[j] >= V42["strong_vol"] and c[j] < c[j - 1]
        exit_mom = rsi[j] < 43 and c[j] < ema20[j]
        if j > entry_idx and (exit_trail or exit_ema50 or exit_trend or exit_dist or exit_mom or exit_ema20):
            reason = ("TRAIL SL" if exit_trail else "EMA50 BREAK" if exit_ema50 else "TREND REVERSAL"
                       if exit_trend else "DISTRIBUTION" if exit_dist else "MOMENTUM FAIL" if exit_mom else "EMA20 BREAK")
            return dict(closed=True, exit_idx=j, exit_px=float(c[j]), stop_now=trail, fill=fill, risk=fill - stop0, reason=reason)
    j = last - 1
    return dict(closed=entry_idx + max_hold <= n, exit_idx=j, exit_px=float(c[j]), stop_now=trail, fill=fill,
                risk=fill - stop0, reason="TIME")

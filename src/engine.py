"""Signal engine.

Ek hi jagah jahan strategy define hoti hai. Backtest, live scan aur ledger teeno
yehi functions use karte hain -> "backtest alag, live alag" wali problem nahi.

Strategy (2019-2026 real NSE data par test hui):
    1. TREND      : Close > EMA50 > EMA200 aur EMA50 upar ja raha
    2. MOMENTUM   : 12-1 month momentum universe ke top 10% me
    3. TRIGGER    : PULLBACK (EMA20 touch + reversal) ya BREAKOUT (20-din high + volume)
    4. EXIT       : SL = 2 x ATR. T1/T2/T3 = 2R/4R/6R par SL upar ratchet hota hai
                    (T1 -> SL entry, T2 -> SL T1, T3 -> SL T2). Koi fixed sell cap nahi.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import CFG

COLS = ["SYMBOL", "DATE", "OPEN", "HIGH", "LOW", "CLOSE", "VOLUME"]


# --------------------------------------------------------------------------- features
def _wilder(x: pd.Series, n: int) -> pd.Series:
    return x.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def _symbol_features(d: pd.DataFrame) -> pd.DataFrame:
    d = d.sort_values("DATE").reset_index(drop=True)
    c, h, l, o, v = d["CLOSE"], d["HIGH"], d["LOW"], d["OPEN"], d["VOLUME"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    d["ATR"] = _wilder(tr, 14)
    for n in (20, 50, 200):
        d[f"EMA{n}"] = c.ewm(span=n, adjust=False, min_periods=n).mean()   # pura warm-up (pehle EMA200 sirf 30 bar par valid maana jaata tha)
    delta = c.diff()
    up, dn = delta.clip(lower=0), -delta.clip(upper=0)
    d["RSI"] = 100 - 100 / (1 + _wilder(up, 14) / _wilder(dn, 14).replace(0, np.nan))
    up_move = h.diff()
    down_move = -l.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    atr_w = _wilder(tr, 14)
    pdi = 100 * _wilder(plus_dm, 14) / atr_w.replace(0, np.nan)
    mdi = 100 * _wilder(minus_dm, 14) / atr_w.replace(0, np.nan)
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    d["ADX"] = dx.rolling(14, min_periods=14).mean()   # trend strength; 25+ real edge test me mila (PF 1.85->2.2 full-history)
    d["VOL_RATIO"] = v / v.rolling(20, min_periods=10).mean()
    d["HH20"] = h.shift(1).rolling(20, min_periods=15).max()
    d["CLOSE_LOC"] = (c - l) / (h - l).replace(0, np.nan)
    d["BODY_PCT"] = (c - o).abs() / (h - l).replace(0, np.nan)   # V38 tier ke liye: candle body % of range
    d["TURNOVER_CR"] = (c * v).rolling(20, min_periods=10).mean() / 1e7
    d["LOW3"] = l.rolling(3).min()
    d["EMA50_UP"] = d["EMA50"] > d["EMA50"].shift(10)
    hi20 = h.rolling(20, min_periods=15).max()
    lo20 = l.rolling(20, min_periods=15).min()
    d["RANGE20_PCT"] = (hi20 - lo20) / c * 100
    d["RANGE_TIGHTNESS"] = 100 - d["RANGE20_PCT"].rolling(252, min_periods=100).apply(
        lambda x: (x <= x.iloc[-1]).mean() * 100, raw=False)   # 100 = range ekdum tight (1-saal me sabse chhota)
    d["ROC60"] = c.pct_change(60) * 100
    d["MOM"] = (c.shift(CFG.mom_skip) / c.shift(CFG.mom_lookback) - 1) * 100
    d["JUMP"] = (c.pct_change().abs() > CFG.jump_pct).astype(int)
    d["JUMP_RECENT"] = d["JUMP"].rolling(90, min_periods=1).max()
    return d


def add_features(hist: pd.DataFrame) -> pd.DataFrame:
    """hist: SYMBOL, DATE, OPEN, HIGH, LOW, CLOSE, VOLUME (multi-symbol). Returns feature frame."""
    parts = []
    for _, g in hist.groupby("SYMBOL", sort=False):
        if len(g) >= CFG.min_bars:
            parts.append(_symbol_features(g))
    if not parts:
        raise ValueError("No symbol has enough history for features")
    f = pd.concat(parts, ignore_index=True)
    by_date = f.groupby("DATE")
    f["RANK60"] = by_date["ROC60"].rank(pct=True) * 100
    f["MOM_RANK"] = by_date["MOM"].rank(pct=True) * 100

    c = f["CLOSE"]
    f["TREND"] = (c > f["EMA50"]) & (f["EMA50"] > f["EMA200"])
    f["PULLBACK"] = (
        f["TREND"]
        & f["EMA50_UP"]
        & (f["RANK60"] >= CFG.rs60_min_rank)
        & (f["LOW3"] <= f["EMA20"] * 1.01)
        & (c > f["EMA20"])
        & (c > f["OPEN"])
        & f["RSI"].between(40, 65)
    )
    f["BREAKOUT"] = (
        f["TREND"]
        & (c > f["HH20"] * 1.002)
        & (f["VOL_RATIO"] >= CFG.breakout_vol_ratio)
        & (f["CLOSE_LOC"] >= CFG.breakout_close_loc)
        & (c < f["EMA20"] * CFG.breakout_max_ext)
    )
    f["LEADER"] = f["TREND"] & (f["MOM_RANK"] >= CFG.mom_min_rank) & (f["ADX"] >= CFG.adx_min)
    f["SIGNAL"] = f["LEADER"] & (f["PULLBACK"] | f["BREAKOUT"])
    # WATCH tier: har roz kuch dikhane ke liye - relaxed momentum/ADX. Tested PF kam hai (~1.7 vs 2.2),
    # isliye isse alag GRADE se dikhaya jaata hai, strict BUY ki jagah nahi leta.
    f["LEADER_LOOSE"] = f["TREND"] & (f["MOM_RANK"] >= CFG.mom_min_rank_loose) & (f["ADX"] >= CFG.adx_min_loose)
    f["SIGNAL_LOOSE"] = f["LEADER_LOOSE"] & (f["PULLBACK"] | f["BREAKOUT"]) & ~f["SIGNAL"]

    # V38 tier: user ke Pine Script (RY APEX MATRIX V38) ka asli signal, hoobehoo - koi trend/momentum/
    # ADX filter nahi (V38 chart me bhi nahi tha). Teen trigger: strong breakout, early breakout, V-shape.
    v_std = (
        (c > f["HH20"] * (1 + CFG.v38_breakout_buffer_pct / 100))
        & (f["VOL_RATIO"] >= CFG.v38_vol_mult)
        & (f["BODY_PCT"] >= 0.40)
        & (f["CLOSE_LOC"] >= 0.70)
        & (c > f["OPEN"])
    )
    v_early = (
        (c > f["HH20"])
        & (f["VOL_RATIO"] >= CFG.v38_early_vol_mult)
        & (c > f["OPEN"])
        & (f["CLOSE_LOC"] >= 0.60)
    )
    ema20_prev, close_prev = f["EMA20"].groupby(f["SYMBOL"]).shift(1), c.groupby(f["SYMBOL"]).shift(1)
    v_vshape = (
        (c > f["EMA20"]) & (close_prev < ema20_prev)
        & (f["VOL_RATIO"] >= 1.50) & (c > f["OPEN"]) & (f["CLOSE_LOC"] >= 0.60)
    )
    f["V38_SETUP"] = np.where(v_std, "STRONG BREAKOUT", np.where(v_early, "EARLY BREAKOUT", np.where(v_vshape, "V-SHAPE", "")))
    f["SIGNAL_V38"] = v_std | v_early | v_vshape
    f["SETUP"] = np.where(f["BREAKOUT"], "BREAKOUT", np.where(f["PULLBACK"], "PULLBACK", ""))
    return f


# --------------------------------------------------------------------------- trade plan
def plan_levels(close: float, atr: float) -> dict:
    """Signal-day close se SL / T1 / T2 / T3. R = close - SL."""
    stop = close - CFG.stop_atr * atr
    risk = close - stop
    return {
        "STOP": stop,
        "RISK": risk,
        "RISK_PCT": risk / close * 100 if close else np.nan,
        "T1": close + CFG.t1_r * risk,
        "T2": close + CFG.t2_r * risk,
        "T3": close + CFG.t3_r * risk,
    }


def position_size(close: float, stop: float, size_mult: float = 1.0) -> dict:
    risk_per_share = close - stop
    if risk_per_share <= 0 or close <= 0:
        return {"QTY": 0, "CAPITAL_USED": 0.0, "RISK_AMT": 0.0}
    risk_amt = CFG.capital * CFG.risk_per_trade_pct / 100 * size_mult
    qty = min(risk_amt / risk_per_share, CFG.capital * CFG.max_single_position_pct / 100 / close)
    qty = int(max(0, np.floor(qty)))
    return {"QTY": qty, "CAPITAL_USED": round(qty * close, 2), "RISK_AMT": round(qty * risk_per_share, 2)}


# --------------------------------------------------------------------------- exit simulator
def simulate_staircase(o, h, l, c, entry_idx: int, stop0: float, signal_close: float | None = None) -> dict | None:
    """Ek trade ko entry_idx (next-day open) se aage chalao.

    Returns None agar trade fill hi nahi hota (gap-up > max_gap_pct ya open <= stop).
    Otherwise dict: closed (bool), exit_idx, exit_px, stop_now, fill, risk, hi_r.
    Stop check pehle hota hai, ratchet baad me (same-bar me conservative order).
    """
    n = len(o)
    if entry_idx >= n:
        return None
    fill = float(o[entry_idx])
    if not np.isfinite(fill) or fill <= stop0:
        return None
    if signal_close and (fill / signal_close - 1) * 100 > CFG.max_gap_pct:
        return None
    risk = fill - stop0
    stop = stop0
    hi = fill
    last = min(n, entry_idx + CFG.max_hold)
    for j in range(entry_idx, last):
        if l[j] <= stop:
            px = min(float(o[j]), stop)
            return dict(closed=True, exit_idx=j, exit_px=px, stop_now=stop, fill=fill, risk=risk,
                        hi_r=(hi - fill) / risk, reason="STOP" if stop <= stop0 else "TRAILING SL")
        hi = max(hi, float(h[j]))
        if hi >= fill + CFG.t3_r * risk:
            stop = max(stop, fill + CFG.t2_r * risk)
        elif hi >= fill + CFG.t2_r * risk:
            stop = max(stop, fill + CFG.t1_r * risk)
        elif hi >= fill + CFG.t1_r * risk:
            stop = max(stop, fill)
    if entry_idx + CFG.max_hold <= n:  # poore 90 session ho gaye -> time exit at last close
        j = entry_idx + CFG.max_hold - 1
        return dict(closed=True, exit_idx=j, exit_px=float(c[j]), stop_now=stop, fill=fill, risk=risk,
                    hi_r=(hi - fill) / risk, reason="TIME EXIT")
    return dict(closed=False, exit_idx=n - 1, exit_px=float(c[n - 1]), stop_now=stop, fill=fill, risk=risk,
                hi_r=(hi - fill) / risk, reason="OPEN")


def trade_return(sim: dict) -> tuple[float, float]:
    """(net return %, R multiple) after costs."""
    ret = (sim["exit_px"] / sim["fill"] - 1) * 100 - CFG.cost_pct
    risk_pct = sim["risk"] / sim["fill"] * 100
    return ret, ret / risk_pct if risk_pct else np.nan


def v38_plan_levels(close: float, atr: float) -> dict:
    """V38 Pine Script jaisa: SL = close - 2.5xATR, T1=+2R, T2=+3R (T1/T2 sirf dikhane ke liye -
    Pine me bhi t1Hit/t2Hit sirf plot ke liye hain, SL ratchet ko affect nahi karte)."""
    stop = close - CFG.v38_atr_mult * atr
    risk = close - stop
    return {"STOP": stop, "RISK": risk, "RISK_PCT": risk / close * 100 if close else np.nan,
            "T1": close + CFG.v38_t1_r * risk, "T2": close + CFG.v38_t2_r * risk}


def simulate_v38_trail(o, h, l, c, atr, entry_idx: int, signal_close: float, max_hold: int = 252) -> dict | None:
    """V38 ka asli exit: SL = max(SL_prev, close - 2.5xATR) HAR BAR par (close se, high se nahi).
    Exit jab close < SL. Koi fixed target nahi, T1/T2 SL ko affect nahi karte - bilkul Pine jaisa."""
    n = len(o)
    if entry_idx >= n:
        return None
    fill = float(o[entry_idx])
    if not np.isfinite(fill):
        return None
    if (fill / signal_close - 1) * 100 > CFG.max_gap_pct:
        return None
    stop0 = signal_close - CFG.v38_atr_mult * atr[max(entry_idx - 1, 0)]
    if stop0 >= fill:
        return None
    # Real backtest (production code, proper single-position-per-symbol state machine,
    # 2019-2026, 448 stocks): n=8344, win=37.1%, PF=1.30. Sabse kamzor tier (WATCH ~1.7,
    # strict ~2.2) kyunki koi trend/momentum/ADX filter nahi - bilkul V38 chart jaisa.
    stop = stop0
    last = min(n, entry_idx + max_hold)
    for j in range(entry_idx, last):
        stop = max(stop, float(c[j]) - CFG.v38_atr_mult * float(atr[j]))
        if float(c[j]) < stop:
            return dict(closed=True, exit_idx=j, exit_px=float(c[j]), stop_now=stop, fill=fill, risk=fill - stop0)
    j = last - 1
    return dict(closed=entry_idx + max_hold <= n, exit_idx=j, exit_px=float(c[j]), stop_now=stop, fill=fill, risk=fill - stop0)


# --------------------------------------------------------------------------- live candidates
def _plan_rows(d: pd.DataFrame, sig_col: str) -> pd.DataFrame:
    rows = d[d[sig_col]].copy()
    if rows.empty:
        return rows
    lv = rows.apply(lambda r: pd.Series(plan_levels(r["CLOSE"], r["ATR"])), axis=1)
    rows = pd.concat([rows, lv], axis=1)
    rows = rows[(rows["RISK_PCT"] >= CFG.min_risk_pct) & (rows["RISK_PCT"] <= CFG.max_risk_pct)]
    return rows.sort_values(["MOM_RANK", "RANK60"], ascending=False)


def _plan_rows_v38(d: pd.DataFrame) -> pd.DataFrame:
    rows = d[d["SIGNAL_V38"]].copy()
    if rows.empty:
        return rows
    lv = rows.apply(lambda r: pd.Series(v38_plan_levels(r["CLOSE"], r["ATR"])), axis=1)
    rows = pd.concat([rows, lv], axis=1)
    rows = rows[(rows["RISK_PCT"] >= CFG.min_risk_pct) & (rows["RISK_PCT"] <= CFG.max_risk_pct)]
    return rows.sort_values("CLOSE_LOC", ascending=False)


def latest_candidates(f: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.Timestamp]:
    """(buy_rows, buy_watch_rows, buy_v38_rows, watch_rows, asof_date) - sirf latest date ke rows.

    buy       = strict tier (backtest PF ~2.2) - asli recommendation
    buy_watch = WATCH tier (backtest PF ~1.7, roz aata hai) - dhila, clearly niche-quality
    buy_v38   = Pine Script V38 ka hoobehoo signal (backtest PF ~1.5) - koi trend/momentum/ADX filter nahi
    watch     = trigger ka intezaar kar raha hai, abhi BUY nahi
    """
    asof = f["DATE"].max()
    d = f[f["DATE"] == asof].copy()
    tradable = (d["TURNOVER_CR"] >= CFG.min_turnover_cr) & (d["JUMP_RECENT"] == 0) & d["ATR"].notna()
    d = d[tradable]
    buy = _plan_rows(d, "SIGNAL")
    buy_watch = _plan_rows(d, "SIGNAL_LOOSE").head(CFG.max_watch_per_day)
    buy_v38 = _plan_rows_v38(d)   # koi cap nahi - jitne bhi V38 signal aayein, sab sheet me
    watch = d[d["LEADER"] & ~d["SIGNAL"] & ~d["SIGNAL_LOOSE"] & (d["CLOSE"] < d["EMA20"] * CFG.breakout_max_ext)].copy()
    if not watch.empty:
        trigger = watch["HH20"] * 1.002
        watch["TRIGGER"] = trigger
        watch["DIST_TO_TRIGGER_PCT"] = (trigger - watch["CLOSE"]) / watch["CLOSE"] * 100
        # "kitna paas hai" ke hisaab se sort: pehle jo trigger ke sabse kareeb hain
        watch = watch.sort_values(["DIST_TO_TRIGGER_PCT", "MOM_RANK"], ascending=[True, False])
    return buy, buy_watch, buy_v38, watch, asof

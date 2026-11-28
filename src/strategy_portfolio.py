"""One-best-BUY-per-validated-strategy selector.

Uses the same causal swing execution simulator for historical qualification and
only emits a latest-day candidate when its strategy passes walk-forward and
recent-history gates. This is a signal shortlist, not broker execution.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import swing_recovery as sr


def _pf(x: pd.Series) -> float:
    x = pd.to_numeric(x, errors="coerce").dropna()
    gains = float(x[x > 0].sum())
    losses = float(-x[x < 0].sum())
    return gains / losses if losses > 0 else (float("inf") if gains > 0 else 0.0)


def _masks(f: pd.DataFrame) -> dict[str, pd.Series]:
    g = f.groupby("SYMBOL", sort=False)
    c = f["CLOSE"]
    atr_pct = f["ATR14"] / c
    atr40 = g["ATR14"].transform(lambda s: (s / c.loc[s.index]).rolling(40, min_periods=30).mean())
    range20 = (g["HIGH"].transform(lambda s: s.rolling(20, min_periods=20).max()) -
               g["LOW"].transform(lambda s: s.rolling(20, min_periods=20).min())) / c
    range60 = (g["HIGH"].transform(lambda s: s.rolling(60, min_periods=60).max()) -
               g["LOW"].transform(lambda s: s.rolling(60, min_periods=60).min())) / c
    common = (c >= 50) & (f["TURNOVER_CR"] >= 10)
    trend = (c > f["EMA200"]) & (f["EMA50"] > f["EMA200"]) & f["EMA50_RISING"]
    vol = (f["VOL_RATIO"] >= 1.5) & (f["CLOSE_LOC"] >= 0.65)
    prev_close, prev_ema20 = g["CLOSE"].shift(1), g["EMA20"].shift(1)
    masks = {
      "TURTLE_55": common & (c > f["HIGH_55D_PREV"] * 1.002) & vol,
      "CANSLIM_PROXY": common & trend & (f["RS_RANK"] >= 80) & (c > f["HIGH_55D_PREV"] * 1.002) & (f["VOL_RATIO"] >= 1.5) & (f["CLOSE_LOC"] >= .75),
      "MINERVINI_VCP": common & trend & (f["EMA20"] > f["EMA50"]) & (atr_pct <= atr40 * .80) & (range20 <= range60 * .55) & (c > f["HIGH_20D_PREV"] * 1.002) & (f["VOL_RATIO"] >= 1.5) & (f["CLOSE_LOC"] >= .70),
      "RS_MOMENTUM": common & trend & (f["RS_RANK"] >= 80) & (g["CLOSE"].pct_change(20) > 0) & (c > f["HIGH_20D_PREV"] * 1.002) & (f["VOL_RATIO"] >= 1.25) & (f["CLOSE_LOC"] >= .65),
      "TREND_PULLBACK": common & trend & (f["EMA20"] > f["EMA50"]) & (prev_close <= prev_ema20 * 1.015) & (c > f["EMA20"]) & (f["RET5"] > 0) & f["RSI14"].between(48, 68) & (f["VOL_RATIO"] >= 1.10) & (f["CLOSE_LOC"] >= .60),
      "52W_LOW_RECOVERY": common & f["LOW_DISTANCE_PCT"].between(3, 35) & (c > f["EMA20"]) & f["EMA20_RISING"] & f["EMA50_RISING"] & (f["RS_RANK"] >= 60) & (f["RET5"] > 0) & f["RSI14"].between(45, 68) & (f["VOL_RATIO"] >= 1.15) & (f["CLOSE_LOC"] >= .60),
    }
    broad = (f["BREADTH_200"] >= 60) & (f["BREADTH_50"] >= 65)
    strict = trend & (f["EMA20"] > f["EMA50"]) & (f["RS_RANK"] >= 85) & broad
    masks.update({
      "TURTLE_20_STRICT": common & strict & (c > f["HIGH_20D_PREV"] * 1.002) & (f["VOL_RATIO"] >= 2) & (f["CLOSE_LOC"] >= .75),
      "TURTLE_55_STRICT": common & strict & (c > f["HIGH_55D_PREV"] * 1.002) & (f["VOL_RATIO"] >= 2) & (f["CLOSE_LOC"] >= .75),
      "CANSLIM_STRICT_PROXY": common & strict & (f["RS_RANK"] >= 90) & (c > f["HIGH_55D_PREV"] * 1.002) & (f["VOL_RATIO"] >= 2) & (f["CLOSE_LOC"] >= .80),
      "MINERVINI_VCP_STRICT": common & strict & (atr_pct <= atr40 * .75) & (range20 <= range60 * .50) & (c > f["HIGH_20D_PREV"] * 1.002) & (f["VOL_RATIO"] >= 1.8) & (f["CLOSE_LOC"] >= .75),
      "52W_HIGH_BREAKOUT": common & strict & (c > g["HIGH"].transform(lambda s: s.shift(1).rolling(252, min_periods=200).max()) * 1.002) & (f["VOL_RATIO"] >= 1.8) & (f["CLOSE_LOC"] >= .75),
      "52W_LOW_RECOVERY_STRICT": common & f["LOW_DISTANCE_PCT"].between(3, 25) & (c > f["EMA20"]) & f["EMA20_RISING"] & f["EMA50_RISING"] & (f["RS_RANK"] >= 80) & (f["BREADTH_200"] >= 55) & (f["BREADTH_50"] >= 60) & (f["RET5"] > 0) & f["RSI14"].between(50, 65) & (f["VOL_RATIO"] >= 1.5) & (f["CLOSE_LOC"] >= .70),
    })
    return {k: v.fillna(False).astype(bool) for k, v in masks.items()}


def build_strategy_buys(features: pd.DataFrame, max_buys: int = 15,
                        min_oos_trades: int = 15, min_recent_trades: int = 8,
                        min_oos_pf: float = 1.15, min_recent_pf: float = 1.0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (at-most-one BUY per qualified strategy, qualification audit)."""
    cols = ["STRATEGY", "STOCK", "SIGNAL_DATE", "BUY_PRICE", "STOP_LOSS",
            "T1", "T2", "T3", "RISK_PCT", "OOS_TRADES", "OOS_PF",
            "RECENT_TRADES", "RECENT_PF", "SCORE"]
    if features.empty:
        return pd.DataFrame(columns=cols), pd.DataFrame()
    f = features.sort_values(["SYMBOL", "DATE"]).copy()
    f["LOW_10D"] = f.groupby("SYMBOL")["LOW"].transform(lambda s: s.rolling(10, min_periods=5).min())
    asof = pd.to_datetime(f.DATE).max()
    masks = _masks(f)
    rows, audits = [], []
    for name, mask in masks.items():
        sim = f.copy()
        sim["BREAKOUT_SETUP"] = mask
        sim["RECOVERY_SETUP"] = False
        trades = sr.backtest_swing(sim)
        if trades.empty:
            oos = trades
            recent = trades
        else:
            signal_dates = pd.to_datetime(trades.SIGNAL_DATE)
            oos = trades[signal_dates >= pd.Timestamp("2025-01-01")]
            recent = trades[signal_dates >= asof - pd.Timedelta(days=730)]
        oos_pf, recent_pf = _pf(oos.get("RETURN_PCT", pd.Series(dtype=float))), _pf(recent.get("RETURN_PCT", pd.Series(dtype=float)))
        qualified = len(oos) >= min_oos_trades and len(recent) >= min_recent_trades and oos_pf >= min_oos_pf and recent_pf >= min_recent_pf
        audits.append({"STRATEGY": name, "OOS_TRADES": len(oos), "OOS_PF": round(oos_pf, 3),
                       "RECENT_TRADES": len(recent), "RECENT_PF": round(recent_pf, 3),
                       "QUALIFIED": bool(qualified)})
        if not qualified:
            continue
        today = f[(f.DATE == asof) & mask].copy()
        if today.empty:
            continue
        # Prefer relative strength, volume confirmation and close near day's high.
        today["SCORE"] = (today["RS_RANK"].fillna(0) * .45 +
                          today["VOL_RATIO"].fillna(0).clip(0, 3) * 10 +
                          today["CLOSE_LOC"].fillna(0) * 20 +
                          (today["CLOSE"] > today["EMA200"]).astype(int) * 10)
        r = today.sort_values(["SCORE", "SYMBOL"], ascending=[False, True]).iloc[0]
        lv = sr._levels(r)
        if not .5 <= lv["RISK_PCT"] <= 8:
            continue
        rows.append({"STRATEGY": name, "STOCK": str(r.SYMBOL), "SIGNAL_DATE": asof,
                     "BUY_PRICE": round(float(r.CLOSE), 2), "STOP_LOSS": round(float(lv["SL"]), 2),
                     "T1": round(float(lv["T1"]), 2), "T2": round(float(lv["T2"]), 2),
                     "T3": round(float(lv["T3"]), 2), "RISK_PCT": round(float(lv["RISK_PCT"]), 2),
                     "OOS_TRADES": len(oos), "OOS_PF": round(oos_pf, 3),
                     "RECENT_TRADES": len(recent), "RECENT_PF": round(recent_pf, 3),
                     "SCORE": round(float(r.SCORE), 2)})
    buys = pd.DataFrame(rows, columns=cols)
    if not buys.empty:
        # Keep at most one row per strategy and no duplicate stock across strategies.
        buys = buys.sort_values(["SCORE", "OOS_PF", "STRATEGY"], ascending=[False, False, True])
        buys = buys.drop_duplicates("STOCK", keep="first").head(max_buys).reset_index(drop=True)
    audit = pd.DataFrame(audits).sort_values(["QUALIFIED", "OOS_PF", "RECENT_PF"], ascending=[False, False, False])
    return buys, audit

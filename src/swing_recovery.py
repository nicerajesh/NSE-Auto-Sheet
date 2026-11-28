"""Unified swing engine: confirmed breakouts and 52-week-low recovery.

All features are calculated per symbol using data available on each date only.
Signals are research candidates, not promises of profit.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

REQUIRED = {"SYMBOL", "DATE", "OPEN", "HIGH", "LOW", "CLOSE", "VOLUME"}
SWING_COLUMNS = [
    "STOCK", "SIGNAL", "BUY PRICE", "SL", "T1", "T2", "T3",
    "52W LOW DISTANCE", "+20%", "+30%", "+40%"
]


def _wilder(s: pd.Series, n: int = 14) -> pd.Series:
    return s.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def add_swing_features(history: pd.DataFrame) -> pd.DataFrame:
    missing = REQUIRED - set(history.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")
    parts = []
    for symbol, raw in history.groupby("SYMBOL", sort=False):
        d = raw.sort_values("DATE").copy().reset_index(drop=True)
        c, h, low, o, v = (d[x].astype(float) for x in ("CLOSE", "HIGH", "LOW", "OPEN", "VOLUME"))
        pc = c.shift(1)
        tr = pd.concat([h - low, (h - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)
        d["ATR14"] = _wilder(tr)
        d["EMA20"] = c.ewm(span=20, adjust=False, min_periods=20).mean()
        d["EMA50"] = c.ewm(span=50, adjust=False, min_periods=50).mean()
        d["EMA200"] = c.ewm(span=200, adjust=False, min_periods=200).mean()
        delta = c.diff()
        rs = _wilder(delta.clip(lower=0)) / _wilder(-delta.clip(upper=0)).replace(0, np.nan)
        d["RSI14"] = (100 - 100 / (1 + rs)).where(_wilder(-delta.clip(upper=0)) != 0, np.where(_wilder(delta.clip(lower=0)) > 0, 100.0, 50.0))
        d["VOL_RATIO"] = v / v.rolling(20, min_periods=15).mean()
        d["LOW_52W"] = low.rolling(252, min_periods=252).min()
        d["HIGH_55D_PREV"] = h.shift(1).rolling(55, min_periods=55).max()
        d["HIGH_20D_PREV"] = h.shift(1).rolling(20, min_periods=20).max()
        d["EMA20_RISING"] = d["EMA20"] > d["EMA20"].shift(5)
        d["EMA50_RISING"] = d["EMA50"] > d["EMA50"].shift(10)
        d["CLOSE_LOC"] = (c - low) / (h - low).replace(0, np.nan)
        d["RET5"] = c.pct_change(5) * 100
        d["LOW_DISTANCE_PCT"] = (c / d["LOW_52W"] - 1) * 100
        d["BREAKOUT_SETUP"] = (
            (c > d["HIGH_55D_PREV"] * 1.002)
            & (d["VOL_RATIO"] >= 1.5)
            & (d["CLOSE_LOC"] >= 0.65)
            & (c > d["EMA50"])
            & d["EMA50_RISING"]
        )
        d["RECOVERY_SETUP"] = (
            d["LOW_DISTANCE_PCT"].between(3, 35)
            & (c > d["EMA20"])
            & d["EMA20_RISING"]
            & d["RET5"].gt(0)
            & d["RSI14"].between(45, 68)
            & (d["VOL_RATIO"] >= 1.15)
            & (d["CLOSE_LOC"] >= 0.60)
        )
        # WAIT is deliberately a weaker observation state, never an entry instruction.
        d["WAIT_SETUP"] = (
            d["LOW_DISTANCE_PCT"].between(0, 25)
            & (c > d["LOW_52W"] * 1.02)
            & d["RET5"].gt(0)
            & (d["RSI14"] >= 40)
            & ~d["RECOVERY_SETUP"]
            & ~d["BREAKOUT_SETUP"]
        )
        # Cross-sectional relative strength rank uses same-date, already-known 60-session return.
        d["RET60"] = c.pct_change(60) * 100
        parts.append(d)
    out = pd.concat(parts, ignore_index=True)
    out["RS_RANK"] = out.groupby("DATE")["RET60"].rank(pct=True) * 100
    return out


def _levels(row: pd.Series) -> dict:
    close, atr = float(row.CLOSE), float(row.ATR14)
    # Protective stop uses the tighter of a 2.2 ATR stop and a recent 10-session swing low,
    # but is always below the proposed entry. This caps pathological risk.
    recent_low = float(row.LOW_10D) if pd.notna(row.LOW_10D) else close - 2.2 * atr
    stop = max(recent_low * 0.995, close - 2.2 * atr)
    stop = min(stop, close - 0.5 * atr)
    risk_pct = (close - stop) / close * 100
    return {
        "BUY PRICE": close, "SL": round(stop, 2),
        "T1": round(close * 1.20, 2), "T2": round(close * 1.30, 2),
        "T3": round(close * 1.40, 2),
        "+20%": round(close * 1.20, 2), "+30%": round(close * 1.30, 2),
        "+40%": round(close * 1.40, 2), "RISK_PCT": risk_pct
    }


def latest_swing_report(features: pd.DataFrame) -> pd.DataFrame:
    if features.empty:
        return pd.DataFrame(columns=SWING_COLUMNS)
    f = features.sort_values(["SYMBOL", "DATE"]).copy()
    f["LOW_10D"] = f.groupby("SYMBOL")["LOW"].transform(lambda x: x.rolling(10, min_periods=5).min())
    asof = f.DATE.max()
    d = f[f.DATE == asof].copy()
    rows = []
    for _, r in d.iterrows():
        if not np.isfinite(r.get("ATR14", np.nan)) or r.ATR14 <= 0 or not np.isfinite(r.get("LOW_52W", np.nan)):
            continue
        setup = "BREAKOUT" if bool(r.BREAKOUT_SETUP) else ("RECOVERY" if bool(r.RECOVERY_SETUP) else ("WAIT" if bool(r.WAIT_SETUP) else ""))
        if not setup:
            continue
        lv = _levels(r)
        if not 0.5 <= lv["RISK_PCT"] <= 12:
            continue
        score = 0
        score += 25 if r.CLOSE > r.EMA20 else 0
        score += 20 if r.EMA20_RISING else 0
        score += 20 if r.RS_RANK >= 70 else (10 if r.RS_RANK >= 50 else 0)
        score += 20 if r.VOL_RATIO >= 1.5 else (10 if r.VOL_RATIO >= 1.15 else 0)
        score += 15 if r.CLOSE_LOC >= 0.75 else (8 if r.CLOSE_LOC >= 0.60 else 0)
        if setup == "WAIT":
            signal = "WAIT"
        elif score >= 90 and setup == "BREAKOUT" and r.CLOSE > r.EMA200 and r.EMA50 > r.EMA200:
            signal = "MUST BUY"
        elif score >= 65:
            signal = "BUY"
        else:
            signal = "WAIT"
        rows.append({
            "STOCK": str(r.SYMBOL), "SIGNAL": signal, **{k: lv[k] for k in
            ("BUY PRICE", "SL", "T1", "T2", "T3", "+20%", "+30%", "+40%")},
            "52W LOW DISTANCE": round(float(r.LOW_DISTANCE_PCT), 2),
            "SETUP": setup, "SCORE": score, "ASOF": asof
        })
    if not rows:
        return pd.DataFrame(columns=SWING_COLUMNS)
    out = pd.DataFrame(rows)
    priority = {"MUST BUY": 0, "BUY": 1, "WAIT": 2}
    out["_P"] = out.SIGNAL.map(priority)
    return out.sort_values(["_P", "SCORE", "STOCK"], ascending=[True, False, True]).drop(columns="_P").reset_index(drop=True)


def backtest_swing(features: pd.DataFrame, cost_pct: float = 0.35, max_hold: int = 126) -> pd.DataFrame:
    """Next-open, one position per symbol; conservative stop-first daily OHLC simulation."""
    f = features.sort_values(["SYMBOL", "DATE"]).copy()
    f["LOW_10D"] = f.groupby("SYMBOL")["LOW"].transform(lambda x: x.rolling(10, min_periods=5).min())
    trades = []
    for symbol, raw in f.groupby("SYMBOL", sort=False):
        g = raw.reset_index(drop=True)
        i = 0
        while i < len(g) - 1:
            r = g.iloc[i]
            if not (bool(r.BREAKOUT_SETUP) or bool(r.RECOVERY_SETUP)):
                i += 1
                continue
            lv = _levels(r)
            if not 0.5 <= lv["RISK_PCT"] <= 12:
                i += 1
                continue
            entry_i = i + 1
            entry = float(g.iloc[entry_i].OPEN)
            if not np.isfinite(entry) or entry <= lv["SL"] or entry > float(r.CLOSE) * 1.03:
                i += 1
                continue
            targets = (entry * 1.20, entry * 1.30, entry * 1.40)
            fractions = (1/3, 1/3, 1/3)
            sold = [False, False, False]
            realized, stop = 0.0, float(lv["SL"])
            exit_idx, reason = None, None
            end = min(len(g), entry_i + max_hold)
            for j in range(entry_i, end):
                bar = g.iloc[j]
                op, hi, lo, cl = map(float, (bar.OPEN, bar.HIGH, bar.LOW, bar.CLOSE))
                if op <= stop or lo <= stop:
                    px = op if op <= stop else stop
                    realized += sum(fractions[k] * (px / entry - 1) for k in range(3) if not sold[k])
                    exit_idx, reason = j, "SL GAP" if op <= stop else "SL"
                    break
                for k, target in enumerate(targets):
                    if not sold[k] and hi >= target:
                        realized += fractions[k] * (target / entry - 1)
                        sold[k] = True
                        if k == 0:
                            stop = max(stop, entry)
                        elif k == 1:
                            stop = max(stop, targets[0])
                if all(sold):
                    exit_idx, reason = j, "T3"
                    break
                if j == end - 1:
                    realized += sum(fractions[k] * (cl / entry - 1) for k in range(3) if not sold[k])
                    exit_idx, reason = j, "TIME/END"
            if exit_idx is None:
                i += 1
                continue
            trades.append({
                "STOCK": symbol, "SIGNAL_DATE": r.DATE, "ENTRY_DATE": g.iloc[entry_i].DATE,
                "ENTRY": entry, "EXIT_DATE": g.iloc[exit_idx].DATE, "EXIT_REASON": reason,
                "RETURN_PCT": realized * 100 - cost_pct,
                "SETUP": "BREAKOUT" if bool(r.BREAKOUT_SETUP) else "RECOVERY"
            })
            # No overlapping trades: next eligible signal only after the exit session.
            i = exit_idx + 1
    return pd.DataFrame(trades)

"""Research-only delivery scanner targeting a fixed +20% move.

No production sheet or BUY engine is changed. Signals use completed daily bars;
entries are next-session opens. Backtest is event-level, not a capital-constrained
portfolio simulation, and must not be treated as a live recommendation.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def add_delivery20_signals(f: pd.DataFrame) -> pd.DataFrame:
    required = {"SYMBOL", "DATE", "OPEN", "HIGH", "LOW", "CLOSE", "VOLUME",
                "EMA20", "EMA50", "EMA200", "ATR", "ADX", "VOL_RATIO",
                "MOM_RANK", "TURNOVER_CR", "JUMP_RECENT"}
    missing = required - set(f.columns)
    if missing:
        raise ValueError(f"Delivery20 missing columns: {sorted(missing)}")
    parts = []
    for _, raw in f.groupby("SYMBOL", sort=False):
        d = raw.sort_values("DATE").copy()
        c = d.CLOSE.astype(float)
        h = d.HIGH.astype(float)
        e20, e50, e200 = d.EMA20, d.EMA50, d.EMA200
        resistance = h.shift(1).rolling(55, min_periods=45).max()
        trend = (c > e20) & (e20 > e50) & (e50 > e200)
        rising = (e50 > e50.shift(20)) & (e200 > e200.shift(20))
        breakout = (c > resistance) & (c.shift(1) <= resistance.shift(1))
        not_extended = c <= e20 * 1.15
        quality = (
            trend & rising & breakout & not_extended
            & (d.VOL_RATIO >= 1.5) & (d.ADX >= 22)
            & d.MOM_RANK.ge(80) & (d.TURNOVER_CR >= 10)
            & (d.JUMP_RECENT == 0)
        )
        # Use prior 10-session structure and ATR; accept only 5%-10% initial risk.
        swing_low = d.LOW.shift(1).rolling(10, min_periods=8).min()
        atr_stop = c - 2.0 * d.ATR
        stop = np.maximum(atr_stop, swing_low.where(swing_low < c, atr_stop))
        risk_pct = (c - stop) / c * 100
        d["D20_STOP"] = stop
        d["D20_RISK_PCT"] = risk_pct
        d["D20_TARGET"] = c * 1.20
        d["D20_BUY"] = quality & risk_pct.between(5.0, 10.0)
        parts.append(d)
    return pd.concat(parts, ignore_index=True)


def backtest_delivery20(f: pd.DataFrame, cost_pct: float = 0.35,
                        max_hold: int = 120, max_gap_pct: float = 2.0,
                        target_pct: float = 20.0) -> pd.DataFrame:
    """One position per symbol at a time; next open; stop-first daily bars."""
    trades = []
    for symbol, raw in f.groupby("SYMBOL", sort=False):
        d = raw.sort_values("DATE").reset_index(drop=True)
        i = 0
        while i < len(d) - 1:
            row = d.iloc[i]
            if not bool(row.get("D20_BUY", False)):
                i += 1
                continue
            entry_row = d.iloc[i + 1]
            entry = float(entry_row.OPEN)
            signal_close = float(row.CLOSE)
            stop = float(row.D20_STOP)
            if (not np.isfinite(entry) or entry <= stop or
                (entry / signal_close - 1) * 100 > max_gap_pct):
                i += 1
                continue
            target = entry * (1 + target_pct / 100)
            exit_i = None
            exit_px = None
            reason = None
            last = min(len(d) - 1, i + 1 + max_hold - 1)
            for j in range(i + 1, last + 1):
                bar = d.iloc[j]
                op, hi, lo, cl = map(float, (bar.OPEN, bar.HIGH, bar.LOW, bar.CLOSE))
                if lo <= stop:
                    exit_i, exit_px, reason = j, min(op, stop), "STOP"
                    break
                if hi >= target:
                    exit_i, exit_px, reason = j, max(op, target), f"TARGET_{target_pct:g}"
                    break
            if exit_i is None:
                exit_i, exit_px = last, float(d.iloc[last].CLOSE)
                reason = "TIME_EXIT" if i + max_hold < len(d) else "OPEN"
            gross = (exit_px / entry - 1) * 100
            net = gross - cost_pct
            trades.append({
                "SYMBOL": symbol, "SIGNAL_DATE": row.DATE,
                "ENTRY_DATE": entry_row.DATE, "EXIT_DATE": d.iloc[exit_i].DATE,
                "ENTRY": entry, "EXIT": exit_px, "STOP": stop, "TARGET": target,
                "RISK_PCT_AT_SIGNAL": float(row.D20_RISK_PCT),
                "MOM_RANK": float(row.MOM_RANK), "TARGET_PCT": float(target_pct),
                "GROSS_RETURN_PCT": gross,
                "NET_RETURN_PCT": net, "REASON": reason,
                "HOLD_SESSIONS": exit_i - (i + 1),
            })
            i = exit_i + 1
    return pd.DataFrame(trades)


def summarize_delivery20(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {"trades": 0, "win_rate_pct": 0.0, "target_hit_pct": 0.0,
                "profit_factor": 0.0, "avg_net_return_pct": 0.0}
    closed = trades[trades.REASON != "OPEN"]
    wins = closed.loc[closed.NET_RETURN_PCT > 0, "NET_RETURN_PCT"].sum()
    losses = -closed.loc[closed.NET_RETURN_PCT < 0, "NET_RETURN_PCT"].sum()
    return {
        "trades": int(len(closed)),
        "open_positions": int((trades.REASON == "OPEN").sum()),
        "win_rate_pct": round(float((closed.NET_RETURN_PCT > 0).mean() * 100), 2) if not closed.empty else 0.0,
        "target_hit_pct": round(float(closed.REASON.str.startswith("TARGET_").mean() * 100), 2) if not closed.empty else 0.0,
        "profit_factor": round(float(wins / losses), 3) if losses else (float("inf") if wins else 0.0),
        "avg_net_return_pct": round(float(closed.NET_RETURN_PCT.mean()), 3) if not closed.empty else 0.0,
        "median_net_return_pct": round(float(closed.NET_RETURN_PCT.median()), 3) if not closed.empty else 0.0,
        "stop_pct": round(float((closed.REASON == "STOP").mean() * 100), 2) if not closed.empty else 0.0,
        "time_exit_pct": round(float((closed.REASON == "TIME_EXIT").mean() * 100), 2) if not closed.empty else 0.0,
    }

"""RY Quant Edge: proprietary trend-continuation hypothesis and walk-forward research.

The model combines cross-sectional leadership, primary trend, volatility
contraction, and a confirmed pivot. Execution is next-open with causal ATR
trailing stops. This is research, not a promise of performance.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _pf(values: pd.Series) -> float:
    x = pd.to_numeric(values, errors="coerce").dropna()
    gp = float(x[x > 0].sum())
    gl = float(-x[x < 0].sum())
    return gp / gl if gl else (float("inf") if gp else 0.0)


def _summarize(trades: pd.DataFrame, strategy: str, asof: pd.Timestamp) -> list[dict]:
    if trades.empty:
        groups = [("ALL", trades), ("TRAIN_THROUGH_2022", trades),
                  ("VALIDATION_2023_2024", trades), ("OOS_2025_PLUS", trades),
                  ("RECENT_730D", trades)]
    else:
        d = trades.copy()
        d["SIGNAL_DATE"] = pd.to_datetime(d["SIGNAL_DATE"])
        groups = [
            ("ALL", d),
            ("TRAIN_THROUGH_2022", d[d.SIGNAL_DATE < "2023-01-01"]),
            ("VALIDATION_2023_2024", d[d.SIGNAL_DATE.between("2023-01-01", "2024-12-31")]),
            ("OOS_2025_PLUS", d[d.SIGNAL_DATE >= "2025-01-01"]),
            ("RECENT_730D", d[d.SIGNAL_DATE >= asof - pd.Timedelta(days=730)]),
        ]
    out = []
    for period, g in groups:
        r = pd.to_numeric(g.get("RETURN_PCT", pd.Series(dtype=float)), errors="coerce").dropna()
        pf = _pf(r)
        out.append({
            "STRATEGY": strategy, "PERIOD": period, "TRADES": len(r),
            "WIN_PCT": round(float((r > 0).mean() * 100), 2) if len(r) else 0.0,
            "AVG_RETURN_PCT": round(float(r.mean()), 3) if len(r) else 0.0,
            "MEDIAN_RETURN_PCT": round(float(r.median()), 3) if len(r) else 0.0,
            "PROFIT_FACTOR": round(pf, 3) if np.isfinite(pf) else "INF",
        })
    return out


def _simulate(f: pd.DataFrame, entry_mask: pd.Series, trail_atr: float,
              cost_pct: float = 0.35, max_hold: int = 126) -> pd.DataFrame:
    """One position per symbol, next-open entry, causal stop updates, full exit."""
    d = f.copy()
    d["_ENTRY"] = entry_mask.fillna(False).astype(bool)
    out = []
    for symbol, raw in d.groupby("SYMBOL", sort=False):
        g = raw.sort_values("DATE").reset_index(drop=True)
        i = 0
        while i < len(g) - 1:
            if not bool(g.loc[i, "_ENTRY"]):
                i += 1
                continue
            sig = g.loc[i]
            entry_i = i + 1
            entry = float(g.loc[entry_i, "OPEN"])
            atr0 = float(sig["ATR14"])
            if not np.isfinite(entry) or not np.isfinite(atr0) or entry <= 0 or atr0 <= 0:
                i += 1
                continue
            initial_stop = entry - 2.2 * atr0
            # Reject setups with excessively wide initial risk.
            if (entry - initial_stop) / entry > 0.10:
                i += 1
                continue
            stop = initial_stop
            high_water = entry
            prev_atr = atr0
            exit_i, exit_price, reason = None, None, None
            end = min(len(g), entry_i + max_hold)
            for j in range(entry_i, end):
                bar = g.loc[j]
                op, hi, lo, cl = map(float, (bar.OPEN, bar.HIGH, bar.LOW, bar.CLOSE))
                # Stop known before today's bar; gap-through fills at open.
                if op <= stop:
                    exit_i, exit_price, reason = j, op, "GAP_STOP"
                    break
                if lo <= stop:
                    exit_i, exit_price, reason = j, stop, "ATR_TRAIL"
                    break
                # Today's close is known now; update stop for the NEXT session only.
                high_water = max(high_water, cl)
                current_atr = float(bar.ATR14) if np.isfinite(bar.ATR14) else prev_atr
                stop = max(stop, high_water - trail_atr * prev_atr)
                prev_atr = current_atr
                # Close-confirmed trend failure exits at this close (not at an earlier intraday price).
                if j > entry_i and np.isfinite(bar.EMA50) and cl < float(bar.EMA50):
                    exit_i, exit_price, reason = j, cl, "EMA50_CLOSE"
                    break
                if j == end - 1:
                    exit_i, exit_price, reason = j, cl, "TIME_EXIT"
                    break
            if exit_i is None:
                i += 1
                continue
            ret = (exit_price / entry - 1) * 100 - cost_pct
            out.append({
                "STOCK": symbol, "SIGNAL_DATE": sig.DATE,
                "ENTRY_DATE": g.loc[entry_i, "DATE"], "ENTRY": entry,
                "EXIT_DATE": g.loc[exit_i, "DATE"], "EXIT": exit_price,
                "EXIT_REASON": reason, "RETURN_PCT": ret,
            })
            i = exit_i + 1
    return pd.DataFrame(out)


def run_ry_quant_edge(features: pd.DataFrame, cost_pct: float = 0.35) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Test original RY setup across three entries and two trailing-stop widths."""
    if features.empty:
        return pd.DataFrame(), pd.DataFrame()
    f = features.sort_values(["SYMBOL", "DATE"]).copy()
    by = f.groupby("SYMBOL", sort=False)
    c = f["CLOSE"]
    f["ATR_PCT"] = f["ATR14"] / c
    f["ATR_PCT_MA40"] = f.groupby("SYMBOL")["ATR_PCT"].transform(lambda x: x.rolling(40, min_periods=30).mean())
    f["RANGE20"] = (
        f.groupby("SYMBOL")["HIGH"].transform(lambda x: x.rolling(20, min_periods=20).max())
        - f.groupby("SYMBOL")["LOW"].transform(lambda x: x.rolling(20, min_periods=20).min())
    ) / c
    f["RANGE60"] = (
        f.groupby("SYMBOL")["HIGH"].transform(lambda x: x.rolling(60, min_periods=60).max())
        - f.groupby("SYMBOL")["LOW"].transform(lambda x: x.rolling(60, min_periods=60).min())
    ) / c
    f["HIGH20_PREV"] = f.groupby("SYMBOL")["HIGH"].transform(lambda x: x.shift(1).rolling(20, min_periods=20).max())
    f["HIGH55_PREV"] = f.groupby("SYMBOL")["HIGH"].transform(lambda x: x.shift(1).rolling(55, min_periods=55).max())
    f["LOW5_PREV"] = f.groupby("SYMBOL")["LOW"].transform(lambda x: x.shift(1).rolling(5, min_periods=5).min())
    f["HIGH10_PREV"] = f.groupby("SYMBOL")["HIGH"].transform(lambda x: x.shift(1).rolling(10, min_periods=10).max())
    liquid = (c >= 50) & (f["TURNOVER_CR"] >= 10)
    trend = (c > f["EMA200"]) & (f["EMA20"] > f["EMA50"]) & (f["EMA50"] > f["EMA200"]) & f["EMA50_RISING"]
    leadership = (f["RS_RANK"] >= 80) & (f["RET60"] > 0)
    market_ok = (f["BREADTH_200"] >= 50) & (f["BREADTH_50"] >= 55)
    contraction = (f["ATR_PCT"] <= f["ATR_PCT_MA40"] * 0.90) & (f["RANGE20"] <= f["RANGE60"] * 0.60)
    volume_ok = (f["VOL_RATIO"] >= 1.5) & (f["CLOSE_LOC"] >= 0.70)

    # RY-1: leadership + orderly volatility contraction + decisive 55-session pivot.
    ry_vcp55 = liquid & trend & leadership & market_ok & contraction & volume_ok & (c > f["HIGH55_PREV"] * 1.002)
    # RY-2: earlier 20-session pivot, but stricter relative strength and volume confirmation.
    ry_early20 = liquid & trend & (f["RS_RANK"] >= 90) & market_ok & (f["ATR_PCT"] <= f["ATR_PCT_MA40"])
    ry_early20 &= (c > f["HIGH20_PREV"] * 1.003) & (f["VOL_RATIO"] >= 2.0) & (f["CLOSE_LOC"] >= 0.80)
    # RY-3: trend continuation after a pullback; requires a prior touch near EMA20 and a fresh 10-day pivot.
    recent_ema_touch = by["LOW"].transform(lambda x: x.rolling(5, min_periods=5).min()) <= f["EMA20"] * 1.015
    ry_pullback = liquid & trend & leadership & market_ok & recent_ema_touch
    ry_pullback &= (c > f["HIGH10_PREV"] * 1.002) & (f["RET5"] > 0) & f["RSI14"].between(50, 68)
    entries = {
        "RY_VCP55": ry_vcp55,
        "RY_EARLY20": ry_early20,
        "RY_PULLBACK10": ry_pullback,
    }
    asof = pd.to_datetime(f["DATE"]).max()
    summaries, all_trades = [], []
    for name, mask in entries.items():
        for trail in (2.5, 3.0):
            label = f"{name}_ATR{trail:.1f}"
            trades = _simulate(f, mask, trail, cost_pct=cost_pct)
            if not trades.empty:
                trades["STRATEGY"] = label
                all_trades.append(trades)
            summaries.extend(_summarize(trades, label, asof))
    summary = pd.DataFrame(summaries)
    trades_out = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    return summary, trades_out

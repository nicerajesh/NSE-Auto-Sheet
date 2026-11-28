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
              initial_atr: float = 2.2, cost_pct: float = 0.35,
              max_hold: int = 126, partial_targets: tuple[float, ...] | None = None,
              partial_fraction: float = 1 / 3) -> pd.DataFrame:
    """One position per symbol; optional equal tranches at fixed profit targets.

    Stop is evaluated before targets when both are touched in one OHLC bar
    (conservative ambiguity handling). Stop levels use only prior-known ATR.
    """
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
            initial_stop = entry - initial_atr * atr0
            if (entry - initial_stop) / entry > 0.10:
                i += 1
                continue
            stop = initial_stop
            high_water = entry
            prev_atr = atr0
            remaining = 1.0
            realized = 0.0
            targets_hit = []
            exit_i, exit_price, reason = None, None, None
            end = min(len(g), entry_i + max_hold)
            targets = tuple(sorted(float(x) for x in (partial_targets or ())))
            for j in range(entry_i, end):
                bar = g.loc[j]
                op, hi, lo, cl = map(float, (bar.OPEN, bar.HIGH, bar.LOW, bar.CLOSE))
                # Conservative: if stop and target both occur in one bar, assume stop first.
                if op <= stop:
                    exit_i, exit_price, reason = j, op, "GAP_STOP"
                    break
                if lo <= stop:
                    exit_i, exit_price, reason = j, stop, "ATR_TRAIL"
                    break
                if targets and remaining > 0:
                    for target_pct in targets:
                        target_price = entry * (1 + target_pct / 100)
                        if target_pct in targets_hit or hi < target_price:
                            continue
                        tranche = min(partial_fraction, remaining)
                        fill = max(op, target_price) if op >= target_price else target_price
                        realized += tranche * (fill / entry - 1) * 100
                        remaining -= tranche
                        targets_hit.append(target_pct)
                        if remaining <= 1e-9:
                            exit_i, exit_price, reason = j, entry * (1 + target_pct / 100), "ALL_TARGETS"
                            break
                    if exit_i is not None:
                        break
                high_water = max(high_water, cl)
                current_atr = float(bar.ATR14) if np.isfinite(bar.ATR14) else prev_atr
                stop = max(stop, high_water - trail_atr * prev_atr)
                prev_atr = current_atr
                if j > entry_i and np.isfinite(bar.EMA50) and cl < float(bar.EMA50):
                    exit_i, exit_price, reason = j, cl, "EMA50_CLOSE"
                    break
                if j == end - 1:
                    exit_i, exit_price, reason = j, cl, "TIME_EXIT"
                    break
            if exit_i is None:
                i += 1
                continue
            if remaining > 1e-9:
                realized += remaining * (exit_price / entry - 1) * 100
            ret = realized - cost_pct
            out.append({
                "STOCK": symbol, "SIGNAL_DATE": sig.DATE,
                "ENTRY_DATE": g.loc[entry_i, "DATE"], "ENTRY": entry,
                "EXIT_DATE": g.loc[exit_i, "DATE"], "EXIT": exit_price,
                "EXIT_REASON": reason, "RETURN_PCT": ret,
                "PARTIAL_TARGETS_HIT": ",".join(str(x) for x in targets_hit),
            })
            i = exit_i + 1
    return pd.DataFrame(out)

def run_ry_quant_edge(features: pd.DataFrame, cost_pct: float = 0.35) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Test original RY setup across selective entries and risk/exit combinations."""
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
    # High-selectivity variants: fewer but cleaner candidates in strong regimes.
    market_strong = (f["BREADTH_200"] >= 60) & (f["BREADTH_50"] >= 65)
    leadership_strong = (f["RS_RANK"] >= 90) & (f["RET60"] > 0)
    high252_prev = f.groupby("SYMBOL")["HIGH"].transform(lambda x: x.shift(1).rolling(252, min_periods=200).max())
    ry_breakout_strict = liquid & trend & leadership_strong & market_strong & (f["ATR_PCT"] <= f["ATR_PCT_MA40"] * 0.85)
    ry_breakout_strict &= (f["RANGE20"] <= f["RANGE60"] * 0.55) & (c > f["HIGH55_PREV"] * 1.003)
    ry_breakout_strict &= (f["VOL_RATIO"] >= 2.0) & (f["CLOSE_LOC"] >= 0.80)
    ry_52w_high = liquid & trend & leadership_strong & market_strong & (c > high252_prev * 1.002)
    ry_52w_high &= (f["VOL_RATIO"] >= 1.8) & (f["CLOSE_LOC"] >= 0.78)
    ry_momentum20 = liquid & trend & leadership_strong & market_strong & (c > f["HIGH20_PREV"] * 1.003)
    ry_momentum20 &= (f["VOL_RATIO"] >= 2.0) & (f["CLOSE_LOC"] >= 0.80)
    entries = {
        "RY_VCP55": ry_vcp55,
        "RY_EARLY20": ry_early20,
        "RY_PULLBACK10": ry_pullback,
        "RY_BREAKOUT_STRICT": ry_breakout_strict,
        "RY_52W_HIGH": ry_52w_high,
        "RY_MOMENTUM20": ry_momentum20,
    }
    asof = pd.to_datetime(f["DATE"]).max()
    summaries, all_trades = [], []
    # Compare risk models with identical signals. OOS and recent periods remain separate.
    for name, mask in entries.items():
        for initial_atr, trail in ((1.5, 2.5), (2.0, 2.5), (2.0, 3.0), (2.2, 3.0)):
            label = f"{name}_SL{initial_atr:.1f}_TR{trail:.1f}"
            trades = _simulate(f, mask, trail, initial_atr=initial_atr, cost_pct=cost_pct)
            if not trades.empty:
                trades["STRATEGY"] = label
                all_trades.append(trades)
            summaries.extend(_summarize(trades, label, asof))

            partial_label = f"{label}_PARTIAL20_30_40"
            partial_trades = _simulate(
                f, mask, trail, initial_atr=initial_atr, cost_pct=cost_pct,
                partial_targets=(20.0, 30.0, 40.0), partial_fraction=1 / 3,
            )
            if not partial_trades.empty:
                partial_trades["STRATEGY"] = partial_label
                all_trades.append(partial_trades)
            summaries.extend(_summarize(partial_trades, partial_label, asof))
    summary = pd.DataFrame(summaries)
    trades_out = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    return summary, trades_out

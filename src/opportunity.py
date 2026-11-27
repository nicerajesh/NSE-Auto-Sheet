"""Multi-strategy opportunity radar. Research signals are separated from validated BUYs."""
from __future__ import annotations

import numpy as np
import pandas as pd


SETUPS = (
    "52W BREAKOUT", "50D BREAKOUT", "52W LOW RECOVERY",
    "VOLUME EXPLOSION", "TIGHT BASE BREAKOUT", "TREND PULLBACK",
    "EARLY REVERSAL",
)


def add_opportunity_features(f: pd.DataFrame) -> pd.DataFrame:
    """Add independent, no-lookahead levels and setup flags to the existing feature frame."""
    parts = []
    for _, g in f.groupby("SYMBOL", sort=False):
        d = g.sort_values("DATE").copy()
        c, h, l, v = d["CLOSE"], d["HIGH"], d["LOW"], d["VOLUME"]
        prior_hi = h.shift(1)
        prior_lo = l.shift(1)
        d["HH50"] = prior_hi.rolling(50, min_periods=40).max()
        d["HH252"] = prior_hi.rolling(252, min_periods=200).max()
        d["LL252"] = prior_lo.rolling(252, min_periods=200).min()
        d["LOW52W_DIST_PCT"] = (c / d["LL252"] - 1) * 100
        d["HIGH52W_DIST_PCT"] = (c / d["HH252"] - 1) * 100
        d["RET5"] = c.pct_change(5) * 100
        d["EMA20_RISING"] = d["EMA20"] > d["EMA20"].shift(5)
        d["EMA50_RISING"] = d["EMA50"] > d["EMA50"].shift(10)
        loc = d.get("CLOSE_LOC", (c - l) / (h - l).replace(0, np.nan))
        green = c > d["OPEN"]
        liquid = d.get("TURNOVER_CR", (c * v).rolling(20, min_periods=10).mean() / 1e7) >= 5

        d["O_52W_BREAKOUT"] = (c > d["HH252"] * 1.001) & (d["VOL_RATIO"] >= 1.5) & (loc >= .65) & green
        d["O_50D_BREAKOUT"] = (c > d["HH50"] * 1.002) & (d["VOL_RATIO"] >= 1.5) & (loc >= .65) & green
        d["O_52W_RECOVERY"] = (
            d["LOW52W_DIST_PCT"].between(5, 35) & (c > d["EMA20"]) &
            d["EMA20_RISING"] & (d["RET5"] > 1.0) & (d["VOL_RATIO"] >= 1.2) &
            (loc >= .55) & green
        )
        d["O_VOLUME_EXPLOSION"] = (
            (d["VOL_RATIO"] >= 2.0) & (c.pct_change() >= .02) &
            (loc >= .65) & green & (c > d["EMA20"])
        )
        d["O_TIGHT_BASE_BREAKOUT"] = (
            (d["RANGE_TIGHTNESS"] >= 70) & (c > d["HH20"] * 1.001) &
            (d["VOL_RATIO"] >= 1.2) & (loc >= .60) & green
        )
        d["O_TREND_PULLBACK"] = (
            (c > d["EMA50"]) & (d["EMA50"] > d["EMA200"]) &
            (l <= d["EMA20"] * 1.015) & (c > d["EMA20"]) &
            d["EMA20_RISING"] & green & d["RSI"].between(45, 68) &
            (d["VOL_RATIO"] >= .8)
        )
        prev_c = c.shift(1)
        prev_e20 = d["EMA20"].shift(1)
        d["O_EARLY_REVERSAL"] = (
            (c > d["EMA20"]) & (prev_c <= prev_e20) & (c > d["OPEN"]) &
            (d["RSI"] >= 45) & (d["RSI"] > d["RSI"].shift(1)) &
            (d["VOL_RATIO"] >= 1.2) & (loc >= .60)
        )
        # transparent 0-100 score; score ranks candidates, it is not a win probability
        trend = ((c > d["EMA20"]).astype(int) + (c > d["EMA50"]).astype(int) +
                 (d["EMA50"] > d["EMA200"]).astype(int) + d["EMA50_RISING"].astype(int)) * 10
        volume_score = (d["VOL_RATIO"].clip(0, 3) / 3 * 25)
        candle_score = loc.clip(0, 1) * 15
        momentum_score = (d["RET5"].clip(-5, 10) + 5) / 15 * 20
        liquidity_score = liquid.astype(int) * 10
        d["OPPORTUNITY_SCORE"] = (trend * 0.75 + volume_score + candle_score + momentum_score + liquidity_score).clip(0, 100)
        d["OPPORTUNITY_LIQUID"] = liquid
        parts.append(d)
    return pd.concat(parts, ignore_index=True)


def latest_opportunities(f: pd.DataFrame, max_rows: int = 30) -> pd.DataFrame:
    """Latest-date radar. These are candidates to study, never automatic validated BUYs."""
    if f.empty:
        return pd.DataFrame()
    d = f[f["DATE"] == f["DATE"].max()].copy()
    flags = [f"O_{x}" for x in (
        "52W_BREAKOUT", "50D_BREAKOUT", "52W_RECOVERY", "VOLUME_EXPLOSION",
        "TIGHT_BASE_BREAKOUT", "TREND_PULLBACK", "EARLY_REVERSAL",
    )]
    rows = []
    for _, r in d.iterrows():
        if not bool(r.get("OPPORTUNITY_LIQUID", False)) or pd.isna(r.get("ATR")) or r["ATR"] <= 0:
            continue
        setups = [name for col, name in zip(flags, SETUPS) if bool(r.get(col, False))]
        if not setups:
            continue
        stop = float(r["CLOSE"] - 2 * r["ATR"])
        risk_pct = (float(r["CLOSE"]) - stop) / float(r["CLOSE"]) * 100
        if not 1.5 <= risk_pct <= 12:
            continue
        rows.append({
            "SYMBOL": r["SYMBOL"], "SETUP": " + ".join(setups),
            "CLOSE": float(r["CLOSE"]), "ENTRY_GUIDE": float(r["CLOSE"]),
            "STOP_LOSS": stop, "T1_2R": float(r["CLOSE"] + 2 * (r["CLOSE"] - stop)),
            "T2_3R": float(r["CLOSE"] + 3 * (r["CLOSE"] - stop)),
            "VOLUME_RATIO": float(r["VOL_RATIO"]), "LOW52W_DIST_PCT": float(r["LOW52W_DIST_PCT"]),
            "HIGH52W_DIST_PCT": float(r["HIGH52W_DIST_PCT"]),
            "SCORE": round(float(r["OPPORTUNITY_SCORE"]), 1),
            "RSI": round(float(r["RSI"]), 1), "STATUS": "RADAR ONLY - next-session confirmation required",
        })
    if not rows:
        return pd.DataFrame(columns=["SYMBOL", "SETUP", "CLOSE", "ENTRY_GUIDE", "STOP_LOSS",
                                     "T1_2R", "T2_3R", "VOLUME_RATIO", "LOW52W_DIST_PCT",
                                     "HIGH52W_DIST_PCT", "SCORE", "RSI", "STATUS"])
    out = pd.DataFrame(rows).sort_values(["SCORE", "VOLUME_RATIO"], ascending=False)
    return out.head(max_rows).reset_index(drop=True)


def evaluate_opportunity_setups(f: pd.DataFrame, max_hold: int = 20) -> pd.DataFrame:
    """Simple historical screening test: next open entry, 2-ATR initial stop, max-hold close exit.
    Conservative same-bar rule checks low against stop before any other outcome. Not a production BUY gate.
    """
    flag_names = [(f"O_{key}", label) for key, label in (
        ("52W_BREAKOUT", "52W BREAKOUT"), ("50D_BREAKOUT", "50D BREAKOUT"),
        ("52W_RECOVERY", "52W LOW RECOVERY"), ("VOLUME_EXPLOSION", "VOLUME EXPLOSION"),
        ("TIGHT_BASE_BREAKOUT", "TIGHT BASE BREAKOUT"), ("TREND_PULLBACK", "TREND PULLBACK"),
        ("EARLY_REVERSAL", "EARLY REVERSAL"),
    )]
    results = []
    for sym, g in f.sort_values("DATE").groupby("SYMBOL", sort=False):
        d = g.reset_index(drop=True)
        for col, label in flag_names:
            last = -999
            for i in np.flatnonzero(d[col].fillna(False).to_numpy()):
                if i - last < max_hold or i + 1 >= len(d):
                    continue
                close, atr = float(d.at[i, "CLOSE"]), float(d.at[i, "ATR"])
                if not np.isfinite(atr) or atr <= 0:
                    continue
                stop = close - 2 * atr
                fill = float(d.at[i + 1, "OPEN"])
                if not np.isfinite(fill) or fill <= stop or fill > close * 1.02:
                    continue
                end = min(len(d), i + 1 + max_hold)
                exit_px, exit_i = float(d.at[end - 1, "CLOSE"]), end - 1
                reason = "TIME"
                for j in range(i + 1, end):
                    if float(d.at[j, "LOW"]) <= stop:
                        exit_px, exit_i, reason = min(float(d.at[j, "OPEN"]), stop), j, "STOP"
                        break
                ret = (exit_px / fill - 1) * 100 - .35
                results.append((label, sym, d.at[i, "DATE"], d.at[exit_i, "DATE"], ret, reason))
                last = i
    if not results:
        return pd.DataFrame(columns=["SETUP", "TRADES", "WIN_PCT", "AVG_NET_PCT", "MEDIAN_NET_PCT", "PROFIT_FACTOR"])
    t = pd.DataFrame(results, columns=["SETUP", "SYMBOL", "SIGNAL_DATE", "EXIT_DATE", "NET_PCT", "REASON"])
    summaries = []
    for label, g in t.groupby("SETUP"):
        gains = g.loc[g.NET_PCT > 0, "NET_PCT"].sum()
        losses = -g.loc[g.NET_PCT < 0, "NET_PCT"].sum()
        oos = g[pd.to_datetime(g.SIGNAL_DATE) >= pd.Timestamp("2023-01-01")]
        oos_gains = oos.loc[oos.NET_PCT > 0, "NET_PCT"].sum()
        oos_losses = -oos.loc[oos.NET_PCT < 0, "NET_PCT"].sum()
        summaries.append({
            "SETUP": label, "TRADES": len(g),
            "WIN_PCT": round(float((g.NET_PCT > 0).mean() * 100), 1),
            "AVG_NET_PCT": round(float(g.NET_PCT.mean()), 2),
            "MEDIAN_NET_PCT": round(float(g.NET_PCT.median()), 2),
            "PROFIT_FACTOR": round(float(gains / losses), 2) if losses else (float("inf") if gains else 0.0),
            "OOS_TRADES_2023_PLUS": len(oos),
            "OOS_WIN_PCT_2023_PLUS": round(float((oos.NET_PCT > 0).mean() * 100), 1) if len(oos) else np.nan,
            "OOS_AVG_NET_PCT_2023_PLUS": round(float(oos.NET_PCT.mean()), 2) if len(oos) else np.nan,
            "OOS_PROFIT_FACTOR_2023_PLUS": round(float(oos_gains / oos_losses), 2) if oos_losses else (float("inf") if oos_gains else 0.0),
        })
    return pd.DataFrame(summaries).sort_values("OOS_PROFIT_FACTOR_2023_PLUS", ascending=False).reset_index(drop=True)

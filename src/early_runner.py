"""Early Runner Hunter: pre-breakout and early trend-turn research.

All signal features use data available at the signal-day close. Forward outcome
measurement begins at the next session OPEN. MFE/MAE are range excursions, not
proof that a target was executable before a stop on the same daily bar.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


SETUPS = ("BOTTOM TURN", "ACCUMULATION", "PRE-BREAKOUT", "FIRST MOMENTUM")
FOCUS_SYMBOLS = (
    "PRESTIGE", "ACE", "TORNTPHARM", "J&KBANK", "BRIGADE", "KFINTECH",
    "BAJAJHLDNG", "LODHA", "WOCKPHARMA", "MCX", "JWL", "TCS", "DOMS",
    "WIPRO", "PTCIL", "360ONE", "BRITANNIA", "RKFORGE", "SOBHA",
    "BALRAMCHIN", "CRAFTSMAN", "ZENTEC", "CHOICEIN", "KAJARIACER",
    "LTTS", "BAJAJ-AUTO", "KPRMILL", "HDFCBANK", "ENDURANCE", "HEGAM",
)


def add_early_runner_features(f: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for _, g in f.groupby("SYMBOL", sort=False):
        d = g.sort_values("DATE").copy()
        c, h, l, o, v = d["CLOSE"], d["HIGH"], d["LOW"], d["OPEN"], d["VOLUME"]
        prev = c.shift(1)
        d["ER_LOW252"] = l.shift(1).rolling(252, min_periods=180).min()
        d["ER_HIGH252"] = h.shift(1).rolling(252, min_periods=180).max()
        d["ER_LOW_DIST"] = (c / d["ER_LOW252"] - 1) * 100
        d["ER_HIGH_DIST"] = (c / d["ER_HIGH252"] - 1) * 100
        d["ER_EMA20_UP"] = d["EMA20"] > d["EMA20"].shift(5)
        d["ER_EMA50_UP"] = d["EMA50"] > d["EMA50"].shift(10)
        d["ER_RSI_UP"] = d["RSI"] > d["RSI"].shift(3)
        d["ER_RANK_IMPROVE"] = d["RANK60"] - d["RANK60"].shift(20)

        # Chaikin-style money-flow pressure and up/down volume balance.
        spread = (h - l).replace(0, np.nan)
        mf_mult = ((2 * c - h - l) / spread).clip(-1, 1).fillna(0)
        d["ER_CMF20"] = (mf_mult * v).rolling(20, min_periods=15).sum() / v.rolling(20, min_periods=15).sum().replace(0, np.nan)
        ret = c.pct_change()
        up_v = v.where(ret > 0, 0).rolling(20, min_periods=15).sum()
        dn_v = v.where(ret < 0, 0).rolling(20, min_periods=15).sum()
        d["ER_UP_DOWN_VOL"] = up_v / dn_v.replace(0, np.nan)
        signed_vol = np.sign(ret.fillna(0)) * v
        obv = signed_vol.cumsum()
        d["ER_OBV_DELTA20"] = obv - obv.shift(20)
        d["ER_VOL_DRYUP"] = v.rolling(10, min_periods=8).mean() / v.rolling(50, min_periods=30).mean()
        d["ER_ATR_PCT"] = d["ATR"] / c * 100
        d["ER_ATR_COMPRESSION"] = d["ER_ATR_PCT"] / d["ER_ATR_PCT"].rolling(50, min_periods=30).median()
        d["ER_NEAR_HH50"] = c / d["HH50"] - 1
        loc = d.get("CLOSE_LOC", (c - l) / spread)
        green = c > o
        liquid = d["TURNOVER_CR"] >= 5
        valid = liquid & d["ATR"].notna() & (d["JUMP_RECENT"] == 0)

        bottom = (
            d["ER_LOW_DIST"].between(2, 38) & (c > d["EMA20"]) &
            d["ER_EMA20_UP"] & (d["RSI"] >= 48) & d["ER_RSI_UP"] &
            (d["ER_CMF20"] > -0.08) & (d["ER_UP_DOWN_VOL"] > 0.95) & valid
        )
        accumulation = (
            (c > d["EMA20"]) & d["ER_EMA20_UP"] &
            (d["ER_CMF20"] >= 0.05) & (d["ER_UP_DOWN_VOL"] >= 1.10) &
            (d["ER_OBV_DELTA20"] > 0) & (d["ER_RANK_IMPROVE"] >= 3) & valid
        )
        prebreakout = (
            d["ER_NEAR_HH50"].between(-0.045, 0.005) &
            (c > d["EMA20"]) & d["ER_EMA20_UP"] &
            (d["RANGE_TIGHTNESS"] >= 45) &
            d["ER_ATR_COMPRESSION"].le(1.15) &
            (d["VOL_RATIO"].between(0.65, 1.8)) & valid
        )
        first_momentum = (
            (c > d["HH20"] * 1.001) & (d["VOL_RATIO"] >= 1.4) &
            (loc >= 0.60) & green & (c <= d["EMA20"] * 1.10) &
            (d["ER_LOW_DIST"].between(3, 55)) & valid
        )
        d["ER_BOTTOM_TURN"] = bottom
        d["ER_ACCUMULATION"] = accumulation
        d["ER_PREBREAKOUT"] = prebreakout
        d["ER_FIRST_MOMENTUM"] = first_momentum

        trend = (
            (c > d["EMA20"]).astype(int) +
            (d["EMA20"] > d["EMA50"]).astype(int) +
            d["ER_EMA20_UP"].astype(int) +
            d["ER_EMA50_UP"].astype(int)
        ) * 6.25
        low_score = (1 - ((d["ER_LOW_DIST"] - 5).abs() / 45)).clip(0, 1) * 15
        flow_score = (
            ((d["ER_CMF20"].clip(-0.2, 0.3) + 0.2) / 0.5) * 10 +
            ((d["ER_UP_DOWN_VOL"].clip(0.5, 2.0) - 0.5) / 1.5) * 8 +
            (d["ER_OBV_DELTA20"] > 0).astype(int) * 7
        )
        rs_score = (d["RANK60"].clip(0, 100) / 100 * 8 +
                    (d["ER_RANK_IMPROVE"].clip(-20, 30) + 20) / 50 * 7)
        compression_score = (1 - (d["ER_ATR_COMPRESSION"] - 0.7).abs().clip(0, 1) / 1) * 10
        trigger_score = (loc.clip(0, 1) * 10)
        d["EARLY_RUNNER_SCORE"] = (trend + low_score + flow_score + rs_score +
                                   compression_score + trigger_score).clip(0, 100)
        parts.append(d)
    return pd.concat(parts, ignore_index=True)


def latest_early_runners(f: pd.DataFrame, max_rows: int = 50) -> pd.DataFrame:
    if f.empty:
        return pd.DataFrame()
    d = f[f["DATE"] == f["DATE"].max()].copy()
    cols = ["ER_BOTTOM_TURN", "ER_ACCUMULATION", "ER_PREBREAKOUT", "ER_FIRST_MOMENTUM"]
    labels = list(SETUPS)
    rows = []
    for _, r in d.iterrows():
        setups = [label for col, label in zip(cols, labels) if bool(r.get(col, False))]
        if not setups:
            continue
        rows.append({
            "SYMBOL": r["SYMBOL"], "SETUP": " + ".join(setups),
            "CLOSE": float(r["CLOSE"]), "SCORE": round(float(r["EARLY_RUNNER_SCORE"]), 1),
            "LOW52W_DIST_PCT": round(float(r["ER_LOW_DIST"]), 1),
            "HIGH52W_DIST_PCT": round(float(r["ER_HIGH_DIST"]), 1),
            "CMF20": round(float(r["ER_CMF20"]), 3),
            "UP_DOWN_VOL": round(float(r["ER_UP_DOWN_VOL"]), 2) if np.isfinite(r["ER_UP_DOWN_VOL"]) else np.nan,
            "VOL_RATIO": round(float(r["VOL_RATIO"]), 2),
            "RS60": round(float(r["RANK60"]), 1),
            "RS60_CHANGE_20D": round(float(r["ER_RANK_IMPROVE"]), 1),
            "RSI": round(float(r["RSI"]), 1),
            "STATUS": "EARLY RADAR - wait for next-session confirmation",
        })
    if not rows:
        return pd.DataFrame(columns=["SYMBOL", "SETUP", "CLOSE", "SCORE", "LOW52W_DIST_PCT",
                                     "HIGH52W_DIST_PCT", "CMF20", "UP_DOWN_VOL", "VOL_RATIO",
                                     "RS60", "RS60_CHANGE_20D", "RSI", "STATUS"])
    return pd.DataFrame(rows).sort_values(["SCORE", "VOL_RATIO"], ascending=False).head(max_rows).reset_index(drop=True)


def backtest_early_runners(f: pd.DataFrame, cooldown: int = 20) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Next-session OPEN entry. Report forward close returns and range MFE/MAE.
    No same-day target/stop sequencing claims; overlapping same-symbol events are cooled down.
    Only complete 5/10/20/40-session windows enter each horizon's summary.
    """
    flags = [
        ("ER_BOTTOM_TURN", "BOTTOM TURN"),
        ("ER_ACCUMULATION", "ACCUMULATION"),
        ("ER_PREBREAKOUT", "PRE-BREAKOUT"),
        ("ER_FIRST_MOMENTUM", "FIRST MOMENTUM"),
    ]
    event_rows = []
    for sym, g in f.sort_values("DATE").groupby("SYMBOL", sort=False):
        d = g.reset_index(drop=True)
        for flag, label in flags:
            last = -cooldown
            hits = np.flatnonzero(d[flag].fillna(False).to_numpy())
            for i in hits:
                if i - last < cooldown or i + 1 >= len(d):
                    continue
                entry = float(d.at[i + 1, "OPEN"])
                if not np.isfinite(entry) or entry <= 0:
                    continue
                row = {
                    "SYMBOL": sym, "SETUP": label, "SIGNAL_DATE": d.at[i, "DATE"],
                    "ENTRY_DATE": d.at[i + 1, "DATE"], "ENTRY_OPEN": entry,
                    "SCORE": float(d.at[i, "EARLY_RUNNER_SCORE"]),
                }
                for n in (5, 10, 20, 40):
                    end = d.iloc[i + 1:i + 1 + n]
                    if len(end) != n:
                        row[f"RET_{n}D"] = np.nan
                        row[f"MFE_{n}D"] = np.nan
                        row[f"MAE_{n}D"] = np.nan
                        continue
                    row[f"RET_{n}D"] = (float(end.iloc[-1]["CLOSE"]) / entry - 1) * 100
                    row[f"MFE_{n}D"] = (float(end["HIGH"].max()) / entry - 1) * 100
                    row[f"MAE_{n}D"] = (float(end["LOW"].min()) / entry - 1) * 100
                event_rows.append(row)
                last = i
    events = pd.DataFrame(event_rows)
    if events.empty:
        return events, pd.DataFrame()
    summaries = []
    for (setup, horizon), g in (
        ( (s, n), events[(events["SETUP"] == s) & events[f"RET_{n}D"].notna()] )
        for s in SETUPS for n in (5, 10, 20, 40)
    ):
        if g.empty:
            continue
        oos = g[pd.to_datetime(g["SIGNAL_DATE"]) >= pd.Timestamp("2023-01-01")]
        ret = g[f"RET_{horizon}D"]
        oos_ret = oos[f"RET_{horizon}D"]
        summaries.append({
            "SETUP": setup, "HORIZON_SESSIONS": horizon, "TRADES": len(g),
            "WIN_PCT": round(float((ret > 0).mean() * 100), 1),
            "AVG_RETURN_PCT": round(float(ret.mean()), 2),
            "MEDIAN_RETURN_PCT": round(float(ret.median()), 2),
            "HIT_10PCT": round(float((ret >= 10).mean() * 100), 1),
            "HIT_20PCT": round(float((ret >= 20).mean() * 100), 1),
            "AVG_MFE_PCT": round(float(g[f"MFE_{horizon}D"].mean()), 2),
            "AVG_MAE_PCT": round(float(g[f"MAE_{horizon}D"].mean()), 2),
            "OOS_TRADES": len(oos),
            "OOS_WIN_PCT": round(float((oos_ret > 0).mean() * 100), 1) if len(oos) else np.nan,
            "OOS_AVG_RETURN_PCT": round(float(oos_ret.mean()), 2) if len(oos) else np.nan,
            "OOS_MEDIAN_RETURN_PCT": round(float(oos_ret.median()), 2) if len(oos) else np.nan,
            "OOS_HIT_10PCT": round(float((oos_ret >= 10).mean() * 100), 1) if len(oos) else np.nan,
            "OOS_HIT_20PCT": round(float((oos_ret >= 20).mean() * 100), 1) if len(oos) else np.nan,
        })
    summary = pd.DataFrame(summaries)
    return events, summary



def summarize_focus_symbols(events: pd.DataFrame, symbols=FOCUS_SYMBOLS) -> pd.DataFrame:
    """One row per user-supplied focus symbol; duplicate same-day setup events count once."""
    rows = []
    for sym in symbols:
        d = events[events["SYMBOL"] == sym].sort_values(["SIGNAL_DATE", "SCORE"], ascending=[True, False])
        if not d.empty:
            d = d.drop_duplicates("SIGNAL_DATE", keep="last")
        row = {
            "SYMBOL": sym, "EVENT_DAYS": len(d),
            "LAST_SIGNAL_DATE": d["SIGNAL_DATE"].max() if not d.empty else pd.NaT,
        }
        for n in (10, 20, 40):
            r = d[f"RET_{n}D"].dropna() if not d.empty else pd.Series(dtype=float)
            row[f"N_{n}D"] = len(r)
            row[f"AVG_{n}D_PCT"] = round(float(r.mean()), 2) if len(r) else np.nan
            row[f"MEDIAN_{n}D_PCT"] = round(float(r.median()), 2) if len(r) else np.nan
            row[f"WIN_{n}D_PCT"] = round(float((r > 0).mean() * 100), 1) if len(r) else np.nan
            row[f"HIT10_{n}D_PCT"] = round(float((r >= 10).mean() * 100), 1) if len(r) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)

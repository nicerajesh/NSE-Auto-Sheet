"""Independent strategy lab: four fresh, OHLCV-only swing systems.

Signals are formed using completed daily bars; execution proxy enters next session
OPEN and exits at the 10/20/40-session CLOSE. Current-universe survivorship bias
remains; this is research-only and never publishes production BUY signals.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
import pandas as pd

COST_PCT = 0.35
HORIZONS = (10, 20, 40)


def _features(g: pd.DataFrame) -> pd.DataFrame:
    d = g.sort_values("DATE").reset_index(drop=True).copy()
    c, h, l, o, v = (d[x].astype(float) for x in ("CLOSE", "HIGH", "LOW", "OPEN", "VOLUME"))
    d["EMA20"] = c.ewm(span=20, adjust=False, min_periods=20).mean()
    d["EMA50"] = c.ewm(span=50, adjust=False, min_periods=50).mean()
    d["EMA100"] = c.ewm(span=100, adjust=False, min_periods=100).mean()
    d["EMA200"] = c.ewm(span=200, adjust=False, min_periods=180).mean()
    d["VOL20"] = v.rolling(20, min_periods=20).mean()
    d["VOL_X"] = v / d["VOL20"].replace(0, np.nan)
    d["HIGH20_PREV"] = h.shift(1).rolling(20, min_periods=18).max()
    d["HIGH55_PREV"] = h.shift(1).rolling(55, min_periods=45).max()
    d["LOW10_PREV"] = l.shift(1).rolling(10, min_periods=8).min()
    d["LOW20_PREV"] = l.shift(1).rolling(20, min_periods=18).min()
    d["LOW55_PREV"] = l.shift(1).rolling(55, min_periods=45).min()
    d["RET63"] = c.pct_change(63)
    # Wilder-style RSI
    delta = c.diff()
    up = delta.clip(lower=0).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    dn = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    rs = up / dn.replace(0, np.nan)
    d["RSI"] = (100 - 100/(1+rs)).mask((dn == 0) & (up > 0), 100.0)
    # Bollinger bandwidth and its trailing percentile, strictly backward-looking
    mid = c.rolling(20, min_periods=20).mean()
    sd = c.rolling(20, min_periods=20).std(ddof=0)
    d["BB_WIDTH"] = (4 * sd / mid).replace([np.inf, -np.inf], np.nan)
    d["BB_WIDTH_PCTL"] = d["BB_WIDTH"].rolling(120, min_periods=80).rank(pct=True)
    # ATR percentage for volatility-normalized stop research later
    prev = c.shift(1)
    tr = pd.concat([(h-l), (h-prev).abs(), (l-prev).abs()], axis=1).max(axis=1)
    d["ATR"] = tr.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    d["ATR_PCT"] = d["ATR"] / c
    d["CLOSE_LOC"] = ((c-l)/(h-l).replace(0, np.nan)).fillna(0.5)
    return d


def build_signals(history: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for symbol, g in history.groupby("SYMBOL", sort=False):
        if len(g) < 260:
            continue
        d = _features(g)
        d["SYMBOL"] = symbol
        frames.append(d)
    if not frames:
        return pd.DataFrame()
    f = pd.concat(frames, ignore_index=True)
    # Cross-sectional momentum rank uses only same-date returns known at close.
    f["MOM_RANK"] = f.groupby("DATE")["RET63"].rank(pct=True)
    close = f["CLOSE"]
    trend = (close > f["EMA200"]) & (f["EMA50"] > f["EMA200"])
    # 1) Donchian trend: fresh 55-session breakout, trend filter and participation.
    donchian = trend & (close > f["HIGH55_PREV"]) & (f["VOL_X"] >= 1.3) & (f["CLOSE_LOC"] >= .65)
    # 2) Volatility expansion: compressed BB width, then close above 20-day range.
    squeeze = (f["BB_WIDTH_PCTL"] <= .20) & (close > f["HIGH20_PREV"]) & (f["VOL_X"] >= 1.4) & trend
    # 3) RSI reset continuation: bullish long-term regime, RSI crosses up through 45.
    rsi_reset = trend & (close > f["EMA20"]) & (f["RSI"] >= 45) & (f["RSI"].shift(1) < 45) & (f["VOL_X"] >= .9)
    # 4) Momentum rotation: top 15% 63-session relative strength, trend and 20-day breakout.
    rs_rotation = (f["MOM_RANK"] >= .85) & (close > f["EMA50"]) & (f["EMA50"] > f["EMA200"]) & (close > f["HIGH20_PREV"]) & (f["VOL_X"] >= 1.1)
    masks = {
        "J_DONCHIAN_TREND": donchian,
        "K_SQUEEZE_EXPANSION": squeeze,
        "L_RSI_RESET_CONTINUATION": rsi_reset,
        "M_MOMENTUM_ROTATION": rs_rotation,
    }
    records = []
    for tier, mask in masks.items():
        for symbol, g in f.groupby("SYMBOL", sort=False):
            ix = np.flatnonzero(mask.loc[g.index].fillna(False).to_numpy())
            last = None
            g = g.sort_values("DATE").reset_index(drop=True)
            for i in ix:
                row = g.iloc[i]
                if last is not None and (row["DATE"] - last).days < 15:
                    continue
                last = row["DATE"]
                rec = {"SYMBOL": symbol, "TIER": tier, "SIGNAL_DATE": row["DATE"],
                       "SIGNAL_CLOSE": float(row["CLOSE"]), "VOL_X": float(row["VOL_X"])}
                future = g.iloc[i+1:i+41]
                for n in HORIZONS:
                    if len(future) < n:
                        rec[f"RET{n}_NET_PCT"] = np.nan
                        continue
                    entry = float(future.iloc[0]["OPEN"])
                    exit_price = float(future.iloc[n-1]["CLOSE"])
                    rec[f"RET{n}_NET_PCT"] = (exit_price / entry - 1) * 100 - COST_PCT if entry > 0 else np.nan
                records.append(rec)
    columns = ["SYMBOL", "TIER", "SIGNAL_DATE", "SIGNAL_CLOSE", "VOL_X"] + [f"RET{n}_NET_PCT" for n in HORIZONS]
    return pd.DataFrame(records, columns=columns)


def summarize(events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if events.empty:
        return pd.DataFrame()
    e = events.copy()
    e["PERIOD"] = np.select(
        [e.SIGNAL_DATE.dt.year <= 2022,
         e.SIGNAL_DATE.dt.year.between(2023, 2024),
         e.SIGNAL_DATE.dt.year >= 2025],
        ["TRAIN_2018_2022", "VALIDATION_2023_2024", "HOLDOUT_2025_PLUS"],
        default="OUT_OF_RANGE")
    for (period, tier), g in e.groupby(["PERIOD", "TIER"]):
        for n in HORIZONS:
            x = g[f"RET{n}_NET_PCT"].dropna()
            if len(x) == 0:
                continue
            gains = x[x > 0].sum()
            losses = -x[x < 0].sum()
            rows.append({"PERIOD": period, "STRATEGY": tier, "HORIZON": n,
                         "TRADES": len(x), "WIN_RATE_PCT": round((x > 0).mean()*100, 2),
                         "AVG_NET_PCT": round(x.mean(), 3), "MEDIAN_NET_PCT": round(x.median(), 3),
                         "PROFIT_FACTOR": round(gains/losses, 3) if losses else np.inf})
    return pd.DataFrame(rows).sort_values(["PERIOD", "HORIZON", "PROFIT_FACTOR"], ascending=[True, True, False])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default="state/history.csv.gz")
    ap.add_argument("--out", default="artifacts/independent_strategy_lab")
    args = ap.parse_args()
    hist = pd.read_csv(args.state, parse_dates=["DATE"])
    events = build_signals(hist)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    events.to_csv(out / "events.csv", index=False)
    summary = summarize(events)
    summary.to_csv(out / "strategy_summary.csv", index=False)
    print(f"History {hist.DATE.min().date()} to {hist.DATE.max().date()} | symbols={hist.SYMBOL.nunique()}")
    print(f"Events: {len(events)} | cost: {COST_PCT:.2f}% round trip | entry next OPEN")
    print("Current-universe survivorship bias remains; event returns are not portfolio returns.")
    print(summary.to_string(index=False) if not summary.empty else "NO SIGNALS")


if __name__ == "__main__":
    main()

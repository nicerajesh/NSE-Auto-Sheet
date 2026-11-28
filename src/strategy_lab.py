"""Comparative strategy lab for price/volume swing models.

All candidate masks use information available at the signal close. Fundamental
CAN SLIM fields are intentionally not fabricated: this module tests only the
price/volume proxy until point-in-time fundamentals are supplied.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import swing_recovery as sr


def _profit_factor(returns: pd.Series) -> float:
    r = pd.to_numeric(returns, errors="coerce").dropna()
    gp = float(r[r > 0].sum())
    gl = float(-r[r < 0].sum())
    return gp / gl if gl > 0 else (float("inf") if gp > 0 else 0.0)


def _stats(trades: pd.DataFrame, label: str, cutoff: pd.Timestamp) -> list[dict]:
    if trades.empty:
        groups = [("ALL", trades), ("RECENT_730D", trades)]
    else:
        trades = trades.copy()
        trades["SIGNAL_DATE"] = pd.to_datetime(trades["SIGNAL_DATE"])
        groups = [("ALL", trades), ("RECENT_730D", trades[trades["SIGNAL_DATE"] >= cutoff])]
        groups.extend((f"YEAR_{int(y)}", g) for y, g in trades.groupby(pd.to_datetime(trades["EXIT_DATE"]).dt.year))
    rows = []
    for period, g in groups:
        r = pd.to_numeric(g.get("RETURN_PCT", pd.Series(dtype=float)), errors="coerce").dropna()
        rows.append({
            "STRATEGY": label, "PERIOD": period, "TRADES": int(len(r)),
            "WIN_PCT": round(float((r > 0).mean() * 100), 2) if len(r) else 0.0,
            "AVG_RETURN_PCT": round(float(r.mean()), 3) if len(r) else 0.0,
            "MEDIAN_RETURN_PCT": round(float(r.median()), 3) if len(r) else 0.0,
            "PROFIT_FACTOR": round(_profit_factor(r), 3) if np.isfinite(_profit_factor(r)) else "INF",
        })
    return rows


def run_strategy_lab(features: pd.DataFrame, cost_pct: float = 0.35) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run multiple entry models through the identical conservative execution engine."""
    if features.empty:
        return pd.DataFrame(), pd.DataFrame()
    f = features.sort_values(["SYMBOL", "DATE"]).copy()
    by_symbol = f.groupby("SYMBOL", sort=False)
    f["RET20"] = by_symbol["CLOSE"].pct_change(20) * 100
    f["ATR_PCT"] = f["ATR14"] / f["CLOSE"] * 100
    f["ATR_PCT_40"] = by_symbol["ATR_PCT"].shift(40)
    f["RANGE20_PCT"] = (by_symbol["HIGH"].transform(lambda x: x.rolling(20, min_periods=20).max())
                         - by_symbol["LOW"].transform(lambda x: x.rolling(20, min_periods=20).min())) / f["CLOSE"] * 100
    f["RANGE60_PCT"] = (by_symbol["HIGH"].transform(lambda x: x.rolling(60, min_periods=60).max())
                         - by_symbol["LOW"].transform(lambda x: x.rolling(60, min_periods=60).min())) / f["CLOSE"] * 100
    c = f["CLOSE"]
    common_liquid = (c >= 50) & (f["TURNOVER_CR"] >= 10)
    uptrend = (c > f["EMA200"]) & (f["EMA50"] > f["EMA200"]) & f["EMA50_RISING"]
    volume_confirm = (f["VOL_RATIO"] >= 1.5) & (f["CLOSE_LOC"] >= 0.65)

    # 1. Turtle: classic 55-session breakout; exit/position logic held constant.
    turtle55 = common_liquid & (c > f["HIGH_55D_PREV"] * 1.002) & volume_confirm

    # 2. CAN SLIM price/volume proxy: leadership + accumulation + breakout.
    # EPS/Sales growth are not in OHLCV and are not invented.
    canslim_proxy = (common_liquid & uptrend & (f["RS_RANK"] >= 80)
                     & (c > f["HIGH_55D_PREV"] * 1.002)
                     & (f["VOL_RATIO"] >= 1.5) & (f["CLOSE_LOC"] >= 0.75))

    # 3. Minervini/VCP-inspired: established uptrend, contracting range/ATR,
    # then a high-volume 20-session pivot breakout.
    vcp = (common_liquid & uptrend & (f["EMA20"] > f["EMA50"])
           & (f["ATR_PCT"] <= f["ATR_PCT_40"] * 0.80)
           & (f["RANGE20_PCT"] <= f["RANGE60_PCT"] * 0.55)
           & (c > f["HIGH_20D_PREV"] * 1.002)
           & (f["VOL_RATIO"] >= 1.5) & (f["CLOSE_LOC"] >= 0.70))

    # 4. Relative-strength momentum: top-quintile RS with 20-day price breakout.
    rs_momentum = (common_liquid & uptrend & (f["RS_RANK"] >= 80)
                   & (f["RET20"] > 0) & (c > f["HIGH_20D_PREV"] * 1.002)
                   & (f["VOL_RATIO"] >= 1.25) & (f["CLOSE_LOC"] >= 0.65))

    # 5. Trend pullback: strong primary trend, controlled pullback toward EMA20,
    # followed by a positive close and improving momentum.
    prev_close = by_symbol["CLOSE"].shift(1)
    prev_ema20 = by_symbol["EMA20"].shift(1)
    trend_pullback = (common_liquid & uptrend & (f["EMA20"] > f["EMA50"])
                      & (prev_close <= prev_ema20 * 1.015)
                      & (c > f["EMA20"]) & (f["RET5"] > 0)
                      & f["RSI14"].between(48, 68)
                      & (f["VOL_RATIO"] >= 1.10) & (f["CLOSE_LOC"] >= 0.60))

    # 6. 52-week low recovery, retained as a separate hypothesis.
    recovery = (common_liquid & f["LOW_DISTANCE_PCT"].between(3, 35)
                & (c > f["EMA20"]) & f["EMA20_RISING"] & f["EMA50_RISING"]
                & (f["RS_RANK"] >= 60) & (f["RET5"] > 0)
                & f["RSI14"].between(45, 68) & (f["VOL_RATIO"] >= 1.15)
                & (f["CLOSE_LOC"] >= 0.60))

    # Strict variants test selectivity and stronger market leadership filters.
    f["HIGH_252D_PREV"] = by_symbol["HIGH"].transform(lambda x: x.shift(1).rolling(252, min_periods=200).max())
    broad_market = (f["BREADTH_200"] >= 60) & (f["BREADTH_50"] >= 65)
    strict_trend = uptrend & (f["EMA20"] > f["EMA50"]) & (f["RS_RANK"] >= 85) & broad_market
    turtle20_strict = (common_liquid & strict_trend & (c > f["HIGH_20D_PREV"] * 1.002) & (f["VOL_RATIO"] >= 2.0) & (f["CLOSE_LOC"] >= 0.75))
    turtle55_strict = (common_liquid & strict_trend & (c > f["HIGH_55D_PREV"] * 1.002) & (f["VOL_RATIO"] >= 2.0) & (f["CLOSE_LOC"] >= 0.75))
    canslim_strict = (common_liquid & strict_trend & (f["RS_RANK"] >= 90) & (c > f["HIGH_55D_PREV"] * 1.002) & (f["VOL_RATIO"] >= 2.0) & (f["CLOSE_LOC"] >= 0.80))
    vcp_strict = (common_liquid & strict_trend & (f["ATR_PCT"] <= f["ATR_PCT_40"] * 0.75) & (f["RANGE20_PCT"] <= f["RANGE60_PCT"] * 0.50) & (c > f["HIGH_20D_PREV"] * 1.002) & (f["VOL_RATIO"] >= 1.8) & (f["CLOSE_LOC"] >= 0.75))
    high52_breakout = (common_liquid & strict_trend & (c > f["HIGH_252D_PREV"] * 1.002) & (f["VOL_RATIO"] >= 1.8) & (f["CLOSE_LOC"] >= 0.75))
    recovery_strict = (common_liquid & f["LOW_DISTANCE_PCT"].between(3, 25) & (c > f["EMA20"]) & f["EMA20_RISING"] & f["EMA50_RISING"] & (f["RS_RANK"] >= 80) & (f["BREADTH_200"] >= 55) & (f["BREADTH_50"] >= 60) & (f["RET5"] > 0) & f["RSI14"].between(50, 65) & (f["VOL_RATIO"] >= 1.5) & (f["CLOSE_LOC"] >= 0.70))
    models = {
        "TURTLE_55_BREAKOUT": turtle55,
        "CANSLIM_PRICE_VOLUME_PROXY": canslim_proxy,
        "MINERVINI_VCP_INSPIRED": vcp,
        "RELATIVE_STRENGTH_MOMENTUM": rs_momentum,
        "TREND_PULLBACK": trend_pullback,
        "52W_LOW_RECOVERY": recovery,
        "TURTLE_20_STRICT": turtle20_strict,
        "TURTLE_55_STRICT": turtle55_strict,
        "CANSLIM_STRICT_PROXY": canslim_strict,
        "MINERVINI_VCP_STRICT": vcp_strict,
        "52W_HIGH_BREAKOUT": high52_breakout,
        "52W_LOW_RECOVERY_STRICT": recovery_strict,
    }
    asof = pd.to_datetime(f["DATE"]).max()
    cutoff = asof - pd.Timedelta(days=730)
    summaries, all_trades = [], []
    for name, mask in models.items():
        candidate = f.copy()
        candidate["BREAKOUT_SETUP"] = mask.fillna(False).astype(bool)
        candidate["RECOVERY_SETUP"] = False
        trades = sr.backtest_swing(candidate, cost_pct=cost_pct)
        if not trades.empty:
            trades["STRATEGY"] = name
            all_trades.append(trades)
        summaries.extend(_stats(trades, name, cutoff))
    summary = pd.DataFrame(summaries)
    trades_out = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    return summary, trades_out

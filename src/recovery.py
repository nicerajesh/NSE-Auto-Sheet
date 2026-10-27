"""Deep-drawdown recovery radar.

Research-only scanner for stocks well below a prior 52-week high that show
early evidence of basing/recovery. A radar row is not an automatic BUY.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import CFG

HIGH_LOOKBACK = 252
MIN_HIGH_BARS = 180
MIN_DRAWDOWN_PCT = 25.0
MAX_DRAWDOWN_PCT = 70.0
MIN_FROM_LOW_PCT = 5.0
MAX_FROM_LOW_PCT = 35.0
MIN_RECOVERY_SCORE = 50.0
MAX_GAP_PCT = 2.0


def add_recovery_features(features: pd.DataFrame) -> pd.DataFrame:
    """Add point-in-time high-to-low recovery metrics and event markers."""
    if features is None or features.empty:
        return features.copy() if features is not None else pd.DataFrame()

    required = {
        "SYMBOL", "DATE", "OPEN", "HIGH", "LOW", "CLOSE", "VOLUME", "ATR",
        "EMA20", "EMA50", "EMA200", "RSI", "VOL_RATIO", "TURNOVER_CR",
        "RANGE20_PCT", "HH20", "CLOSE_LOC",
    }
    missing = required - set(features.columns)
    if missing:
        raise ValueError(f"Recovery radar missing required feature columns: {sorted(missing)}")

    f = features.copy().sort_values(["SYMBOL", "DATE"]).reset_index(drop=True)
    groups = f.groupby("SYMBOL", sort=False)
    f["REC_HIGH_252"] = groups["HIGH"].transform(
        lambda s: s.shift(1).rolling(HIGH_LOOKBACK, min_periods=MIN_HIGH_BARS).max()
    )
    f["REC_LOW_252"] = groups["LOW"].transform(
        lambda s: s.shift(1).rolling(HIGH_LOOKBACK, min_periods=MIN_HIGH_BARS).min()
    )
    f["REC_DRAWDOWN_PCT"] = (1.0 - f["CLOSE"] / f["REC_HIGH_252"]) * 100.0
    f["REC_FROM_LOW_PCT"] = (f["CLOSE"] / f["REC_LOW_252"] - 1.0) * 100.0

    prev_close = groups["CLOSE"].shift(1)
    f["REC_ROC20"] = groups["CLOSE"].pct_change(20) * 100.0
    f["REC_RS_IMPROVEMENT"] = f["REC_ROC20"] - f.get("ROC60", pd.Series(np.nan, index=f.index))

    f["REC_LOW10"] = groups["LOW"].transform(lambda s: s.rolling(10, min_periods=8).min())
    f["REC_PRIOR_LOW10"] = groups["LOW"].transform(
        lambda s: s.shift(10).rolling(10, min_periods=8).min()
    )
    f["REC_HIGHER_LOW"] = f["REC_LOW10"] > f["REC_PRIOR_LOW10"] * 1.005
    f["REC_EMA20_RISING"] = f["EMA20"] > groups["EMA20"].shift(5)
    f["REC_ABOVE_EMA20"] = f["CLOSE"] > f["EMA20"]

    up_volume = f["VOLUME"].where(f["CLOSE"] > prev_close, 0.0)
    down_volume = f["VOLUME"].where(f["CLOSE"] < prev_close, 0.0)
    f["REC_UP_VOLUME10"] = up_volume.groupby(f["SYMBOL"], sort=False).transform(
        lambda s: s.rolling(10, min_periods=7).sum()
    )
    f["REC_DOWN_VOLUME10"] = down_volume.groupby(f["SYMBOL"], sort=False).transform(
        lambda s: s.rolling(10, min_periods=7).sum()
    )
    f["REC_ACCUM_RATIO"] = f["REC_UP_VOLUME10"] / f["REC_DOWN_VOLUME10"].replace(0, np.nan)
    f["REC_ATR_PCT"] = f["ATR"] / f["CLOSE"] * 100.0
    f["REC_TRIGGER_PRICE"] = f["HH20"] * 1.002
    f["REC_TRIGGERED"] = (
        (f["CLOSE"] > f["REC_TRIGGER_PRICE"])
        & (f["VOL_RATIO"] >= 1.30)
        & (f["CLOSE_LOC"] >= 0.60)
        & (f["CLOSE"] > f["OPEN"])
        & (f["CLOSE"] <= f["EMA20"] * 1.12)
    )

    # A deep discount alone gets no score: require evidence of stabilization/recovery too.
    f["REC_SCORE"] = (
        np.select(
            [f["REC_DRAWDOWN_PCT"].between(25, 60), f["REC_DRAWDOWN_PCT"].between(60, 70)],
            [15, 8], default=0
        )
        + np.select([f["REC_FROM_LOW_PCT"].between(8, 30), f["REC_FROM_LOW_PCT"].between(5, 35)],
                    [10, 5], default=0)
        + f["REC_HIGHER_LOW"].fillna(False).astype(int) * 15
        + f["REC_ABOVE_EMA20"].fillna(False).astype(int) * 15
        + f["REC_EMA20_RISING"].fillna(False).astype(int) * 10
        + (f["REC_ACCUM_RATIO"] >= 1.15).fillna(False).astype(int) * 15
        + (f["REC_RS_IMPROVEMENT"] >= 5).fillna(False).astype(int) * 10
        + (f["VOL_RATIO"] >= 1.20).fillna(False).astype(int) * 5
        + (f["RANGE20_PCT"] <= 15).fillna(False).astype(int) * 5
        + f["REC_TRIGGERED"].fillna(False).astype(int) * 10
    ).clip(0, 100)

    f["REC_ELIGIBLE"] = (
        f["REC_DRAWDOWN_PCT"].between(MIN_DRAWDOWN_PCT, MAX_DRAWDOWN_PCT)
        & f["REC_FROM_LOW_PCT"].between(MIN_FROM_LOW_PCT, MAX_FROM_LOW_PCT)
        & (f["TURNOVER_CR"] >= CFG.min_turnover_cr)
        & f["REC_ATR_PCT"].between(1.0, 10.0)
    ).fillna(False)
    f["REC_STAGE"] = np.select(
        [
            f["REC_ELIGIBLE"] & f["REC_TRIGGERED"] & (f["REC_SCORE"] >= MIN_RECOVERY_SCORE),
            f["REC_ELIGIBLE"] & (f["REC_SCORE"] >= MIN_RECOVERY_SCORE)
              & (f["REC_HIGHER_LOW"] | (f["REC_ABOVE_EMA20"] & f["REC_EMA20_RISING"])),
        ],
        ["TRIGGERED", "PREPARE"],
        default="",
    )
    prev_stage = f.groupby("SYMBOL", sort=False)["REC_STAGE"].shift(1).fillna("")
    f["REC_EVENT"] = f["REC_STAGE"].ne("") & f["REC_STAGE"].ne(prev_stage)
    return f


def latest_recovery_candidates(features: pd.DataFrame, limit: int = 15) -> pd.DataFrame:
    """Return today's top recovery setups; PREPARE is watch-only, TRIGGERED is research-only."""
    if features is None or features.empty or "REC_STAGE" not in features:
        return pd.DataFrame()
    asof = features["DATE"].max()
    d = features[(features["DATE"] == asof) & features["REC_STAGE"].isin(["PREPARE", "TRIGGERED"])].copy()
    if d.empty:
        return d
    entry = pd.to_numeric(d["REC_TRIGGER_PRICE"], errors="coerce")
    stop = entry - 2.0 * pd.to_numeric(d["ATR"], errors="coerce")
    risk = entry - stop
    d["REC_ENTRY_REF"] = entry
    d["REC_MAX_BUY"] = entry * (1.0 + MAX_GAP_PCT / 100.0)
    d["REC_STOP"] = stop
    d["REC_T1"] = entry + 2.0 * risk
    d["REC_T2"] = entry + 4.0 * risk
    d["REC_T3"] = entry + 6.0 * risk
    d["REC_RISK_PCT"] = risk / entry.replace(0, np.nan) * 100.0
    d = d[(entry > 0) & (stop > 0) & d["REC_SCORE"].ge(MIN_RECOVERY_SCORE)]
    d["_STAGE_ORDER"] = d["REC_STAGE"].map({"TRIGGERED": 0, "PREPARE": 1})
    d = d.sort_values(["_STAGE_ORDER", "REC_SCORE", "REC_RS_IMPROVEMENT", "TURNOVER_CR"],
                      ascending=[True, False, False, False])
    return d.drop(columns="_STAGE_ORDER").head(limit).reset_index(drop=True)


def recovery_outcome_diagnostics(features: pd.DataFrame, horizons: tuple[int, ...] = (10, 20, 40)) -> pd.DataFrame:
    """Historical excursion diagnostics after distinct stage-entry events (not executable P&L)."""
    if features is None or features.empty or "REC_EVENT" not in features:
        return pd.DataFrame(columns=[
            "STAGE", "HORIZON_SESSIONS", "EVENTS", "HIT_PLUS10_PCT", "HIT_PLUS20_PCT",
            "AVG_MAX_UPSIDE_PCT", "MEDIAN_MAX_UPSIDE_PCT", "AVG_MAX_DRAWDOWN_PCT",
        ])
    f = features.sort_values(["SYMBOL", "DATE"]).copy()
    results: list[dict] = []
    for horizon in horizons:
        future_high = f.groupby("SYMBOL", sort=False)["HIGH"].transform(
            lambda s: s.shift(-1).iloc[::-1].rolling(horizon, min_periods=horizon).max().iloc[::-1]
        )
        future_low = f.groupby("SYMBOL", sort=False)["LOW"].transform(
            lambda s: s.shift(-1).iloc[::-1].rolling(horizon, min_periods=horizon).min().iloc[::-1]
        )
        f["_REC_FAV_PCT"] = (future_high / f["CLOSE"] - 1.0) * 100.0
        f["_REC_ADVERSE_PCT"] = (future_low / f["CLOSE"] - 1.0) * 100.0
        valid = f["REC_EVENT"] & f["REC_STAGE"].isin(["PREPARE", "TRIGGERED"]) & f["_REC_FAV_PCT"].notna() & f["_REC_ADVERSE_PCT"].notna()
        for stage in ("PREPARE", "TRIGGERED"):
            x = f.loc[valid & f["REC_STAGE"].eq(stage)]
            results.append({
                "STAGE": stage,
                "HORIZON_SESSIONS": horizon,
                "EVENTS": int(len(x)),
                "HIT_PLUS10_PCT": round(float((x["_REC_FAV_PCT"] >= 10).mean() * 100), 2) if len(x) else np.nan,
                "HIT_PLUS20_PCT": round(float((x["_REC_FAV_PCT"] >= 20).mean() * 100), 2) if len(x) else np.nan,
                "AVG_MAX_UPSIDE_PCT": round(float(x["_REC_FAV_PCT"].mean()), 2) if len(x) else np.nan,
                "MEDIAN_MAX_UPSIDE_PCT": round(float(x["_REC_FAV_PCT"].median()), 2) if len(x) else np.nan,
                "AVG_MAX_DRAWDOWN_PCT": round(float(x["_REC_ADVERSE_PCT"].mean()), 2) if len(x) else np.nan,
            })
    return pd.DataFrame(results)

"""DELIVERY sheet: monthly momentum rotation (positional / investing-style).

Research base (RESEARCH.md): 12-1 month momentum ke top decile me avg R ~0.5 vs bottom half ~0.3;
monthly rotation top-20 momentum ~30% CAGR vs equal-weight ~17% (survivorship se INFLATED).
Isliye yahan koi nayi "magic" nahi - sirf wahi jo test me bacha:

    BUY zone  : trend OK (Close > EMA50 > EMA200) aur momentum rank 1..delivery_top_n
    HOLD zone : rank delivery_top_n+1 .. delivery_hold_n  (hysteresis - baar-baar churn nahi)
    EXIT      : rank hold_n se bahar, ya Close < EMA200, ya disaster SL hit
    Rebalance : mahine ke pehle trading din list dekho (roz trade karne ki zaroorat nahi)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import CFG


def delivery_levels(close: float, atr: float) -> dict:
    """Disaster SL (3.5 ATR, 8-20% ke beech) aur T1/T2/T3 = 2R/4R/6R (staircase jaisa review levels)."""
    risk = CFG.delivery_atr_mult * atr
    risk = min(max(risk, close * CFG.delivery_min_risk_pct / 100), close * CFG.delivery_max_risk_pct / 100)
    stop = close - risk
    return {"STOP": stop, "RISK": risk, "RISK_PCT": risk / close * 100,
            "T1": close + 2 * risk, "T2": close + 4 * risk, "T3": close + 6 * risk}


def delivery_qty(close: float, stop: float) -> dict:
    """Equal-weight slot aur risk-limit me se jo chhota; stage_pct (25%) se shuru."""
    per_share_risk = close - stop
    if close <= 0 or per_share_risk <= 0:
        return {"QTY": 0, "CAPITAL_USED": 0.0, "RISK_AMT": 0.0}
    cap = CFG.delivery_capital * CFG.stage_pct / 100
    slot = cap / CFG.delivery_top_n
    risk_cap = cap * CFG.delivery_risk_pct / 100
    qty = int(max(0, np.floor(min(slot / close, risk_cap / per_share_risk))))
    return {"QTY": qty, "CAPITAL_USED": round(qty * close, 2), "RISK_AMT": round(qty * per_share_risk, 2)}


def delivery_candidates(f: pd.DataFrame) -> pd.DataFrame:
    """f = engine.add_features() output. Latest date ke top `hold_n` momentum stocks (trend OK), ZONE ke saath."""
    asof = f["DATE"].max()
    d = f[f["DATE"] == asof]
    ok = ((d["TURNOVER_CR"] >= CFG.delivery_min_turnover_cr) & (d["JUMP_RECENT"] == 0)
          & d["ATR"].notna() & d["MOM"].notna() & d["TREND"])
    d = d[ok].sort_values("MOM", ascending=False).head(CFG.delivery_hold_n).copy()
    if d.empty:
        return d
    d["RANK"] = np.arange(1, len(d) + 1)
    d["ZONE"] = np.where(d["RANK"] <= CFG.delivery_top_n, "BUY", "HOLD")
    lv = d.apply(lambda r: pd.Series(delivery_levels(r["CLOSE"], r["ATR"])), axis=1)
    sz = pd.concat([d.reset_index(drop=True), lv.reset_index(drop=True)], axis=1)
    q = sz.apply(lambda r: pd.Series(delivery_qty(r["CLOSE"], r["STOP"])), axis=1)
    out = pd.concat([sz, q], axis=1)
    out["EXIT_BELOW"] = out["EMA200"]
    return out


def next_rebalance(asof: pd.Timestamp) -> pd.Timestamp:
    """Agle mahine ka pehla weekday (holiday NSE calendar se alag ho sakta hai)."""
    first = (asof + pd.offsets.MonthBegin(1)).normalize()
    while first.weekday() >= 5:
        first += pd.Timedelta(days=1)
    return first

"""V2 single-source-of-truth decision engine.

Combines setup quality, entry quality, historical edge and portfolio risk.
It never upgrades a blocked signal to BUY.  Raw scanner actions remain in
ACTION; the only user-facing trading decision is FINAL_ACTION.
"""
from __future__ import annotations
import math
import pandas as pd

BUY_SETUP = {"PRE-BREAKOUT BUY", "BREAKOUT BUY", "SWING BUY"}
WATCH_SETUP = {"WATCH", "AVOID / CHASE"}


def _num(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except Exception:
        return None


def build_master(df: pd.DataFrame, market_regime: str = "UNKNOWN") -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["RANK", "SYMBOL", "FINAL_ACTION"])
    x = df.copy()
    actions = []
    reasons = []
    for _, r in x.iterrows():
        raw = str(r.get("ACTION", "WATCH"))
        gate = str(r.get("QUALITY_GATE", "UNKNOWN"))
        risk = str(r.get("RISK_MANAGER_STATUS", "N/A"))
        extension = _num(r.get("EXTENSION_PCT"))
        rr2 = None
        entry, stop, t2 = map(_num, (r.get("IDEAL_ENTRY", r.get("ENTRY_PRICE")), r.get("STOP_LOSS"), r.get("TARGET_2")))
        if entry and stop and t2 and entry > stop:
            rr2 = (t2-entry)/(entry-stop)
        if raw in BUY_SETUP:
            if gate != "PASS":
                actions.append("⛔ QUALITY BLOCKED")
                reasons.append(f"Historical edge gate: {gate}")
            elif risk not in {"PASS", "N/A", "N/A_GATE_BLOCKED"}:
                actions.append("⛔ RISK BLOCKED")
                reasons.append(f"Risk manager: {risk}")
            elif extension is not None and extension > 5:
                actions.append("🔴 AVOID — CHASING")
                reasons.append("Entry is extended above EMA20")
            elif rr2 is not None and rr2 < 2.5:
                actions.append("🟡 WAIT — RR LOW")
                reasons.append(f"R:R to Target 2 is only {rr2:.2f}")
            elif raw == "BREAKOUT BUY":
                actions.append("🟢 BUY ON BREAKOUT")
                reasons.append("Breakout setup + all release gates passed")
            elif raw == "PRE-BREAKOUT BUY":
                actions.append("🟡 BUY ON TRIGGER")
                reasons.append("Pre-breakout setup; wait for trigger")
            else:
                actions.append("🔵 BUY ON PULLBACK")
                reasons.append("Trend setup; prefer pullback entry")
        elif raw == "AVOID / CHASE":
            actions.append("🔴 AVOID — CHASING"); reasons.append("Scanner flagged chase risk")
        else:
            actions.append("⚪ WATCH"); reasons.append("Setup not yet actionable")
    x["FINAL_ACTION"] = actions
    x["DECISION_REASON"] = reasons
    x["MARKET_REGIME_V2"] = market_regime
    # User-facing confidence is deliberately not called probability unless it is
    # calibrated from sufficient historical samples.
    x["EDGE_CONFIDENCE"] = pd.to_numeric(x.get("BREAKOUT_CONFIDENCE", x.get("BREAKOUT_PROBABILITY", pd.Series(index=x.index))), errors="coerce")
    x["EDGE_CONFIDENCE_LABEL"] = "UNRELIABLE / NOT CALIBRATED"
    if "BREAKOUT_CONFIDENCE" in x.columns:
        x.loc[x["BREAKOUT_CONFIDENCE"].notna(), "EDGE_CONFIDENCE_LABEL"] = "HISTORICAL BUCKET RATE"
    priority={"🟢 BUY ON BREAKOUT":1,"🟡 BUY ON TRIGGER":2,"🔵 BUY ON PULLBACK":3,"🟡 WAIT — RR LOW":4,"⚪ WATCH":5,"⛔ QUALITY BLOCKED":6,"⛔ RISK BLOCKED":7,"🔴 AVOID — CHASING":8}
    x["_P"] = x["FINAL_ACTION"].map(priority).fillna(9)
    x["_S"] = pd.to_numeric(x.get("HUNTER_SCORE", 0), errors="coerce").fillna(0)
    x=x.sort_values(["_P","_S"], ascending=[True,False]).drop(columns=["_P","_S"])
    x.insert(0,"RANK",range(1,len(x)+1))
    return x.reset_index(drop=True)

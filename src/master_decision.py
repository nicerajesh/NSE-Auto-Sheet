"""V2 single-source-of-truth decision engine."""
from __future__ import annotations
import math
import pandas as pd

BUY_SETUP = {"PRE-BREAKOUT BUY", "BREAKOUT BUY", "SWING BUY"}

def _num(x):
    try:
        v=float(x); return v if math.isfinite(v) else None
    except Exception: return None

def build_master(df: pd.DataFrame, market_regime: str = "UNKNOWN") -> pd.DataFrame:
    required=["RANK","SYMBOL","FINAL_ACTION","QUALITY_GATE"]
    if df is None or df.empty:
        return pd.DataFrame(columns=required)
    x=df.copy()
    actions=[]; reasons=[]
    for _,r in x.iterrows():
        raw=str(r.get("ACTION","WATCH")); gate=str(r.get("QUALITY_GATE","UNKNOWN")); risk=str(r.get("RISK_MANAGER_STATUS","N/A"))
        extension=_num(r.get("EXTENSION_PCT")); rr2=None
        entry,stop,t2=map(_num,(r.get("IDEAL_ENTRY",r.get("ENTRY_PRICE")),r.get("STOP_LOSS"),r.get("TARGET_2")))
        if entry and stop and t2 and entry>stop: rr2=(t2-entry)/(entry-stop)
        if raw in BUY_SETUP:
            if gate!="PASS": action="⛔ QUALITY BLOCKED"; reason=f"Historical edge gate: {gate}"
            elif risk not in {"PASS","N/A","N/A_GATE_BLOCKED"}: action="⛔ RISK BLOCKED"; reason=f"Risk manager: {risk}"
            elif extension is not None and extension>5: action="🔴 AVOID — CHASING"; reason="Entry is extended above EMA20"
            elif rr2 is not None and rr2<2.5: action="🟡 WAIT — RR LOW"; reason=f"R:R to Target 2 is only {rr2:.2f}"
            elif raw=="BREAKOUT BUY": action="🟢 BUY ON BREAKOUT"; reason="Breakout setup + release gates passed"
            elif raw=="PRE-BREAKOUT BUY": action="🟡 BUY ON TRIGGER"; reason="Pre-breakout setup; wait for trigger"
            else: action="🔵 BUY ON PULLBACK"; reason="Trend setup; prefer pullback entry"
        elif raw=="AVOID / CHASE": action="🔴 AVOID — CHASING"; reason="Scanner flagged chase risk"
        elif raw in {"WATCH","WAIT","REVERSAL WATCH","STEALTH WATCH"}: action="⚪ WATCH"; reason="Setup is developing; wait for confirmation"
        else: action="⚪ WATCH"; reason="Setup not yet actionable"
        actions.append(action); reasons.append(reason)
    x["FINAL_ACTION"]=actions; x["DECISION_REASON"]=reasons; x["MARKET_REGIME_V2"]=market_regime
    x["QUALITY_GATE"]=x.get("QUALITY_GATE",pd.Series("UNKNOWN",index=x.index)).fillna("UNKNOWN")
    x["EDGE_CONFIDENCE"]=pd.to_numeric(x.get("BREAKOUT_CONFIDENCE",x.get("BREAKOUT_PROBABILITY",pd.Series(index=x.index))),errors="coerce")
    x["EDGE_CONFIDENCE_LABEL"]="UNRELIABLE / NOT CALIBRATED"
    if "BREAKOUT_CONFIDENCE" in x.columns: x.loc[x["BREAKOUT_CONFIDENCE"].notna(),"EDGE_CONFIDENCE_LABEL"]="HISTORICAL BUCKET RATE"
    priority={"🟢 BUY ON BREAKOUT":1,"🟡 BUY ON TRIGGER":2,"🔵 BUY ON PULLBACK":3,"🟡 WAIT — RR LOW":4,"⚪ WATCH":5,"⛔ QUALITY BLOCKED":6,"⛔ RISK BLOCKED":7,"🔴 AVOID — CHASING":8}
    x["_P"]=x["FINAL_ACTION"].map(priority).fillna(9); x["_S"]=pd.to_numeric(x.get("HUNTER_SCORE",0),errors="coerce").fillna(0)
    x=x.sort_values(["_P","_S"],ascending=[True,False]).drop(columns=["_P","_S"])
    x.insert(0,"RANK",range(1,len(x)+1)); return x.reset_index(drop=True)

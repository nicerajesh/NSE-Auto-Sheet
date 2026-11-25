from __future__ import annotations
import math
import pandas as pd

def allocate_candidates(signals:pd.DataFrame,capital:float,risk_pct:float,max_total_risk_pct:float,max_positions:int,max_position_pct:float)->pd.DataFrame:
    d=signals.copy(); d["QTY"]=0; d["CAPITAL_REQUIRED"]=0.0; d["RISK_RS"]=0.0; d["BUY_PRIORITY"]=0
    picks=d[d.SIGNAL.eq("APEX BUY")].sort_values(["SCORE","MOM_RANK","RS_RANK"],ascending=False)
    cash=float(capital); risk_left=float(capital)*max_total_risk_pct/100; accepted=0
    for idx,r in picks.iterrows():
        if accepted>=max_positions: d.loc[idx,["SIGNAL","REASON"]]=["WATCH","MAX OPEN SLOTS"]; continue
        per_share=float(r.CLOSE-r.STOP)
        if per_share<=0 or not math.isfinite(per_share): d.loc[idx,["SIGNAL","REASON"]]=["REJECT","INVALID STOP"]; continue
        risk_cash=min(capital*risk_pct/100,risk_left)
        qty=min(math.floor(risk_cash/per_share),math.floor(capital*max_position_pct/100/float(r.CLOSE)),math.floor(cash/float(r.CLOSE)))
        if qty<1: d.loc[idx,["SIGNAL","REASON"]]=["WATCH","RISK / CAPITAL BUDGET FULL"]; continue
        used=qty*float(r.CLOSE); risk=qty*per_share; d.loc[idx,["QTY","CAPITAL_REQUIRED","RISK_RS","BUY_PRIORITY"]]=[qty,round(used,2),round(risk,2),accepted+1]
        cash-=used; risk_left-=risk; accepted+=1
    return d.sort_values(["SIGNAL","SCORE"],ascending=[True,False])

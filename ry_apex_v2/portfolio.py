from __future__ import annotations
import math
import numpy as np
import pandas as pd
from .config import CFG
from .engine import score_row,score_relative_strength_row

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

def build_signal_cache(features:pd.DataFrame,strategy:str="apex")->dict:
    scorer=score_relative_strength_row if strategy=="relative_strength" else score_row
    cache={}
    for day,group in features.groupby("DATE",sort=True):
        picks=[]
        for _,r in group.iterrows():
            try: score,signal,_=scorer(r)
            except Exception: continue
            wanted="APEX RS BUY" if strategy=="relative_strength" else "APEX BUY"
            if signal==wanted:
                picks.append({"SYMBOL":r.SYMBOL,"SIGNAL_DATE":day,"SIGNAL_CLOSE":float(r.CLOSE),"STOP":float(r.CLOSE-CFG.stop_atr*r.ATR14),"SCORE":score})
        picks.sort(key=lambda x:(x["SCORE"],x["SYMBOL"]),reverse=True)
        cache[pd.Timestamp(day)]=picks
    return cache

def simulate_portfolio(features:pd.DataFrame,capital:float=500000.0,risk_pct:float=0.5,max_total_risk_pct:float=3.0,max_positions:int=8,max_position_pct:float=15.0,cost_pct:float=0.60,max_hold:int=60,strategy:str="apex",signal_cache:dict|None=None)->tuple[pd.DataFrame,pd.DataFrame,dict]:
    """Daily close signal -> next-session open entry, shared cash and risk, concurrent holdings."""
    required={"SYMBOL","DATE","OPEN","HIGH","LOW","CLOSE","ATR14"}
    if strategy=="relative_strength":
        required.update({"BREADTH50","BREADTH200"})
    missing=required-set(features.columns)
    if missing: raise ValueError(f"Missing portfolio columns: {sorted(missing)}")
    f=features.copy(); f["DATE"]=pd.to_datetime(f.DATE); f=f.sort_values(["DATE","SYMBOL"])
    dates=sorted(f.DATE.unique()); by_day={d:g.set_index("SYMBOL",drop=False) for d,g in f.groupby("DATE",sort=True)}
    if signal_cache is None: signal_cache=build_signal_cache(f,strategy)
    cash=float(capital); positions={}; pending=[]; trades=[]; curve=[]
    for day_i,day in enumerate(dates):
        today=by_day[day]
        # Process exits at today's OHLC before considering today's new entries.
        for sym in list(positions):
            p=positions[sym]
            if sym not in today.index: continue
            r=today.loc[sym]; op,hi,lo,cl=map(float,(r.OPEN,r.HIGH,r.LOW,r.CLOSE))
            p["bars"]+=1; stop=float(p["stop"]); exit_px=None; reason=None
            if lo<=stop:
                exit_px=min(op,stop); reason="STOP" if stop==p["initial_stop"] else "TRAIL"
            elif p["bars"]>=max_hold:
                exit_px=cl; reason="TIME"
            if exit_px is not None:
                qty=p["qty"]; gross=(exit_px-p["entry"])*qty; fees=p["entry"]*qty*cost_pct/100
                cash+=qty*exit_px-fees
                trades.append({"SYMBOL":sym,"SIGNAL_DATE":p["signal_date"],"ENTRY_DATE":p["entry_date"],"EXIT_DATE":day,"ENTRY":p["entry"],"EXIT":exit_px,"QTY":qty,"GROSS_PNL":gross,"COST_RS":fees,"NET_PNL":gross-fees,"RET_PCT":((exit_px/p["entry"]-1)*100)-cost_pct,"REASON":reason,"SCORE":p["score"]})
                del positions[sym]; continue
            p["high_water"]=max(p["high_water"],hi); risk=p["risk_per_share"]
            if p["high_water"]>=p["entry"]+3*risk:p["stop"]=max(p["stop"],p["entry"]+2*risk)
            elif p["high_water"]>=p["entry"]+2*risk:p["stop"]=max(p["stop"],p["entry"]+risk)
            elif p["high_water"]>=p["entry"]+risk:p["stop"]=max(p["stop"],p["entry"])
        # Enter yesterday's ranked signals at today's open; shared cash and risk constrain all symbols.
        for cand in pending:
            sym=cand["SYMBOL"]
            breadth50=float(today["BREADTH50"].iloc[0]) if strategy=="relative_strength" else 100.0
            breadth200=float(today["BREADTH200"].iloc[0]) if strategy=="relative_strength" else 100.0
            weak_regime = strategy=="relative_strength" and (not np.isfinite(breadth50) or not np.isfinite(breadth200) or breadth50<40 or breadth200<30)
            slot_limit = min(4,max_positions) if weak_regime else max_positions
            if sym in positions or sym not in today.index or len(positions)>=slot_limit: continue
            r=today.loc[sym]; entry=float(r.OPEN); stop=float(cand["STOP"])
            if not np.isfinite(entry) or entry<=0 or entry<=stop: continue
            gap=(entry/float(cand["SIGNAL_CLOSE"])-1)*100
            if gap>CFG.max_entry_gap_pct: continue
            equity=cash+sum(pos["qty"]*float(today.loc[s]["CLOSE"]) for s,pos in positions.items() if s in today.index)
            risk_used=sum(pos["qty"]*max(0,pos["entry"]-pos["stop"]) for pos in positions.values())
            active_risk_pct = (0.25 if weak_regime else risk_pct) if strategy=="relative_strength" else risk_pct
            active_total_risk_pct = (1.5 if weak_regime else max_total_risk_pct) if strategy=="relative_strength" else max_total_risk_pct
            risk_budget=max(0,min(equity*active_risk_pct/100,equity*active_total_risk_pct/100-risk_used))
            per_share=entry-stop
            qty=min(math.floor(risk_budget/per_share),math.floor(equity*max_position_pct/100/entry),math.floor(cash/entry))
            if qty<1: continue
            cash-=qty*entry
            positions[sym]={"qty":qty,"entry":entry,"entry_date":day,"signal_date":cand["SIGNAL_DATE"],"stop":stop,"initial_stop":stop,"risk_per_share":per_share,"high_water":entry,"bars":0,"score":cand["SCORE"]}
            # Apply stop on the entry session too; conservative stop-first OHLC ordering.
            if float(r.LOW)<=stop:
                exit_px=min(entry,stop); gross=(exit_px-entry)*qty; fees=entry*qty*cost_pct/100
                cash+=qty*exit_px-fees
                trades.append({"SYMBOL":sym,"SIGNAL_DATE":cand["SIGNAL_DATE"],"ENTRY_DATE":day,"EXIT_DATE":day,"ENTRY":entry,"EXIT":exit_px,"QTY":qty,"GROSS_PNL":gross,"COST_RS":fees,"NET_PNL":gross-fees,"RET_PCT":((exit_px/entry-1)*100)-cost_pct,"REASON":"ENTRY_DAY_STOP","SCORE":cand["SCORE"]})
                del positions[sym]
        pending=[]
        # Today's close generates orders for the next trading session only.
        if day_i<len(dates)-1:
            pending=list(signal_cache.get(pd.Timestamp(day),[]))
        equity=cash+sum(pos["qty"]*float(today.loc[s]["CLOSE"]) for s,pos in positions.items() if s in today.index)
        curve.append({"DATE":day,"CASH":cash,"OPEN_POSITIONS":len(positions),"EQUITY":equity,"OPEN_RISK_RS":sum(pos["qty"]*max(0,pos["entry"]-pos["stop"]) for pos in positions.values())})
    # Conservative end-of-test liquidation at final close.
    last=dates[-1]; last_day=by_day[last]
    for sym,p in list(positions.items()):
        if sym not in last_day.index: continue
        exit_px=float(last_day.loc[sym].CLOSE); qty=p["qty"]; gross=(exit_px-p["entry"])*qty; fees=p["entry"]*qty*cost_pct/100
        cash+=qty*exit_px-fees
        trades.append({"SYMBOL":sym,"SIGNAL_DATE":p["signal_date"],"ENTRY_DATE":p["entry_date"],"EXIT_DATE":last,"ENTRY":p["entry"],"EXIT":exit_px,"QTY":qty,"GROSS_PNL":gross,"COST_RS":fees,"NET_PNL":gross-fees,"RET_PCT":((exit_px/p["entry"]-1)*100)-cost_pct,"REASON":"END_OF_TEST","SCORE":p["score"]})
    if curve: curve[-1]["EQUITY"]=cash; curve[-1]["CASH"]=cash; curve[-1]["OPEN_POSITIONS"]=0; curve[-1]["OPEN_RISK_RS"]=0
    t=pd.DataFrame(trades); e=pd.DataFrame(curve)
    if not e.empty:
        e["PEAK"]=e.EQUITY.cummax(); e["DRAWDOWN_PCT"]=(e.EQUITY/e.PEAK-1)*100
    elapsed=max(1,(pd.Timestamp(dates[-1])-pd.Timestamp(dates[0])).days) if dates else 1
    final_equity=float(e.EQUITY.iloc[-1]) if not e.empty else float(capital)
    daily_ret=e.EQUITY.pct_change().dropna() if not e.empty else pd.Series(dtype=float)
    gross_win=float(t.loc[t.NET_PNL>0,"NET_PNL"].sum()) if not t.empty else 0.0
    gross_loss=float(-t.loc[t.NET_PNL<0,"NET_PNL"].sum()) if not t.empty else 0.0
    annual_returns={}
    if not e.empty:
        annual_end=e.assign(YEAR=pd.to_datetime(e.DATE).dt.year).groupby("YEAR").EQUITY.last()
        prev=float(capital)
        for yr,val in annual_end.items():
            annual_returns[str(int(yr))]=round((float(val)/prev-1)*100,2)
            prev=float(val)
    stats={"annual_returns_pct":annual_returns,"strategy":strategy,"starting_capital":round(capital,2),"ending_equity":round(final_equity,2),"net_pnl":round(final_equity-capital,2),"total_return_pct":round((final_equity/capital-1)*100,2) if capital else 0.0,"cagr_pct":round(((final_equity/capital)**(365.25/elapsed)-1)*100,2) if capital and final_equity>0 else -100.0,"trades":len(t),"win_rate_pct":round((t.NET_PNL>0).mean()*100,2) if not t.empty else 0.0,"profit_factor":round(gross_win/gross_loss,3) if gross_loss else (float("inf") if gross_win else 0.0),"avg_trade_pnl_rs":round(float(t.NET_PNL.mean()),2) if not t.empty else 0.0,"max_drawdown_pct":round(float(e.DRAWDOWN_PCT.min()),2) if not e.empty else 0.0,"max_open_positions":int(e.OPEN_POSITIONS.max()) if not e.empty else 0,"max_open_risk_rs":round(float(e.OPEN_RISK_RS.max()),2) if not e.empty else 0.0,"daily_volatility_pct":round(float(daily_ret.std()*np.sqrt(252)*100),2) if len(daily_ret)>1 else 0.0,"cost_pct_round_trip":cost_pct}
    return t,e,stats

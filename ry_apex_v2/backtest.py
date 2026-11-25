from __future__ import annotations
import numpy as np
import pandas as pd
from .config import CFG
from .engine import score_row
def simulate_symbol(g:pd.DataFrame)->list[dict]:
 g=g.sort_values("DATE").reset_index(drop=True); out=[]; active_until=-1
 for i in range(len(g)-1):
  r=g.iloc[i]; score,signal,_=score_row(r)
  if signal!="APEX BUY" or i<=active_until:continue
  entry=float(g.OPEN.iloc[i+1]); signal_close=float(r.CLOSE)
  if not np.isfinite(entry) or entry<=0 or (entry/signal_close-1)*100>CFG.max_entry_gap_pct:continue
  stop=signal_close-CFG.stop_atr*float(r.ATR14)
  if entry<=stop:continue
  risk=entry-stop; stop_now=stop; hi=entry; exit_i=None; exit_px=None; why="TIME"
  for j in range(i+1,min(len(g),i+1+CFG.max_hold)):
   op,high,low,close=map(float,(g.OPEN.iloc[j],g.HIGH.iloc[j],g.LOW.iloc[j],g.CLOSE.iloc[j]))
   if low<=stop_now:exit_i=j; exit_px=min(op,stop_now); why="STOP" if stop_now==stop else "TRAIL"; break
   hi=max(hi,high)
   if hi>=entry+3*risk:stop_now=max(stop_now,entry+2*risk)
   elif hi>=entry+2*risk:stop_now=max(stop_now,entry+risk)
   elif hi>=entry+risk:stop_now=max(stop_now,entry)
  if exit_i is None:
   exit_i=i+CFG.max_hold
   if exit_i<len(g):exit_px=float(g.CLOSE.iloc[exit_i]); why="TIME"
   else:continue
  ret=(exit_px/entry-1)*100-CFG.cost_pct; out.append({"SYMBOL":r.SYMBOL,"SIGNAL_DATE":r.DATE,"ENTRY_DATE":g.DATE.iloc[i+1],"EXIT_DATE":g.DATE.iloc[exit_i],"ENTRY":entry,"EXIT":exit_px,"RET_PCT":ret,"R":ret/((risk/entry)*100),"REASON":why,"SCORE":score}); active_until=exit_i
 return out
def run_backtest(f:pd.DataFrame)->pd.DataFrame:
 rows=[]
 for _,g in f.groupby("SYMBOL",sort=False):rows.extend(simulate_symbol(g))
 return pd.DataFrame(rows)
def metrics(t:pd.DataFrame)->dict:
 if t.empty:return {"trades":0,"win_rate":0.0,"profit_factor":0.0,"expectancy_pct":0.0,"max_loss_streak":0}
 x=t.sort_values("EXIT_DATE"); ret=pd.to_numeric(x.RET_PCT); wins=ret[ret>0].sum(); losses=-ret[ret<0].sum(); streak=best=0
 for v in ret.to_numpy():streak=streak+1 if v<=0 else 0; best=max(best,streak)
 return {"trades":len(t),"win_rate":round((ret>0).mean()*100,2),"profit_factor":round(wins/losses,3) if losses else float("inf"),"expectancy_pct":round(ret.mean(),3),"max_loss_streak":int(best)}
def walk_forward(t:pd.DataFrame)->dict:
 if t.empty:return {"train":metrics(t),"test_2023_plus":metrics(t),"test_2025_plus":metrics(t)}
 x=t.copy(); x["EXIT_DATE"]=pd.to_datetime(x.EXIT_DATE)
 return {"train":metrics(x[x.EXIT_DATE<"2023-01-01"]),"test_2023_plus":metrics(x[x.EXIT_DATE>="2023-01-01"]),"test_2025_plus":metrics(x[x.EXIT_DATE>="2025-01-01"])}

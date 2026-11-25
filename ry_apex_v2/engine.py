from __future__ import annotations
import numpy as np
import pandas as pd
from .config import CFG
REQ=["SYMBOL","DATE","OPEN","HIGH","LOW","CLOSE","VOLUME"]
def wilder(s:pd.Series,n:int)->pd.Series:return s.ewm(alpha=1/n,adjust=False,min_periods=n).mean()
def add_symbol_features(g:pd.DataFrame)->pd.DataFrame:
 d=g.sort_values("DATE").copy().reset_index(drop=True); c,h,l,o,v=(d[k].astype(float) for k in ("CLOSE","HIGH","LOW","OPEN","VOLUME")); pc=c.shift(1)
 tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1); d["ATR14"]=wilder(tr,14)
 for n in (20,50,200):d[f"EMA{n}"]=c.ewm(span=n,adjust=False,min_periods=n).mean()
 delta=c.diff(); gain=wilder(delta.clip(lower=0),14); loss=wilder(-delta.clip(upper=0),14); rs=gain/loss.replace(0,np.nan); d["RSI14"]=100-100/(1+rs)
 up=h.diff(); dn=-l.diff(); plus=up.where((up>dn)&(up>0),0.0); minus=dn.where((dn>up)&(dn>0),0.0); atr=wilder(tr,14)
 pdi=100*wilder(plus,14)/atr.replace(0,np.nan); mdi=100*wilder(minus,14)/atr.replace(0,np.nan); dx=100*(pdi-mdi).abs()/(pdi+mdi).replace(0,np.nan); d["ADX14"]=wilder(dx,14)
 d["VOL_AVG20"]=v.shift(1).rolling(20,min_periods=20).mean(); d["VOL_RATIO"]=v/d["VOL_AVG20"].replace(0,np.nan)
 d["TURNOVER_CR"]=(c*v).shift(1).rolling(20,min_periods=20).mean()/1e7; d["HH20_PREV"]=h.shift(1).rolling(20,min_periods=20).max(); d["HH252_PREV"]=h.shift(1).rolling(252,min_periods=200).max()
 d["LOW3"]=l.rolling(3,min_periods=3).min(); d["CLOSE_LOC"]=(c-l)/(h-l).replace(0,np.nan); d["ATR_PCT"]=d["ATR14"]/c*100; d["DIST_HIGH_PCT"]=(d["HH252_PREV"]-c)/d["HH252_PREV"]*100
 d["EMA50_RISING"]=d["EMA50"]>d["EMA50"].shift(10); d["ROC126"]=(c/c.shift(126)-1)*100; d["ROC252_SKIP21"]=(c.shift(21)/c.shift(252)-1)*100
 d["TREND"]=(c>d["EMA50"])&(d["EMA50"]>d["EMA200"])&d["EMA50_RISING"]
 d["BREAKOUT"]=(c>d["HH20_PREV"]*1.001)&(d["VOL_RATIO"]>=CFG.breakout_volume)&(d["CLOSE_LOC"]>=CFG.min_breakout_close_loc)
 d["PULLBACK"]=(d["LOW3"]<=d["EMA20"]*1.015)&(c>d["EMA20"])&(c>o)&d["RSI14"].between(45,67)&(c<d["EMA20"]*1.04)
 return d
def build_features(hist:pd.DataFrame)->pd.DataFrame:
 missing=set(REQ)-set(hist.columns)
 if missing:raise ValueError(f"Missing columns: {sorted(missing)}")
 parts=[add_symbol_features(g) for _,g in hist.groupby("SYMBOL",sort=False) if len(g)>=CFG.min_history]
 if not parts:raise ValueError("No symbols have enough valid history")
 f=pd.concat(parts,ignore_index=True); f["MOM_RANK"]=f.groupby("DATE")["ROC252_SKIP21"].rank(pct=True)*100; f["RS_RANK"]=f.groupby("DATE")["ROC126"].rank(pct=True)*100
 breadth=f.groupby("DATE").apply(lambda x:pd.Series({"BREADTH50":(x.CLOSE>x.EMA50).mean()*100,"BREADTH200":(x.CLOSE>x.EMA200).mean()*100}),include_groups=False)
 return f.merge(breadth,left_on="DATE",right_index=True,how="left")
def score_row(r:pd.Series)->tuple[int,str,str]:
 c=float(r.CLOSE); e20=float(r.EMA20); atrp=float(r.ATR_PCT); dist=float(r.DIST_HIGH_PCT); needed=[c,e20,atrp,dist,float(r.ADX14),float(r.MOM_RANK),float(r.RS_RANK),float(r.BREADTH50),float(r.BREADTH200),float(r.TURNOVER_CR),float(r.VOL_RATIO)]
 if not np.isfinite(needed).all():return 0,"REJECT","INSUFFICIENT DATA"
 breakout=bool(r.BREAKOUT); pullback=bool(r.PULLBACK); trend=bool(r.TREND); pts=20*trend+10*(c>r.EMA200 and r.EMA50>r.EMA200)
 pts+=10 if r.MOM_RANK>=85 else (7 if r.MOM_RANK>=CFG.min_momentum_rank else 0); pts+=10 if r.RS_RANK>=80 else (7 if r.RS_RANK>=70 else 0); pts+=10 if r.ADX14>=25 else (6 if r.ADX14>=CFG.min_adx else 0)
 pts+=15 if breakout else 0; pts+=10 if pullback else 0; pts+=5 if 1.5<=r.VOL_RATIO<=4 else 0; pts+=5 if 0<=dist<=CFG.max_high_distance_pct else 0; pts+=5 if 2<=atrp<=5 else 0
 setup="BREAKOUT" if breakout else "PULLBACK" if pullback else "NONE"
 if not trend or setup=="NONE":return int(pts),"WATCH","NO VALID TRIGGER"
 if r.BREADTH50<40 or r.BREADTH200<30:return int(pts),"REJECT","MARKET REGIME RISK-OFF"
 if c<CFG.min_price or r.TURNOVER_CR<CFG.min_turnover_cr:return int(pts),"REJECT","PRICE/LIQUIDITY FILTER"
 if not CFG.min_atr_pct<=atrp<=CFG.max_atr_pct:return int(pts),"REJECT","VOLATILITY FILTER"
 if c>e20*CFG.max_ema20_extension or dist>CFG.max_high_distance_pct:return int(pts),"REJECT","EXTENDED / FAR FROM HIGH"
 if r.ADX14<CFG.min_adx or r.MOM_RANK<CFG.min_momentum_rank:return int(pts),"WATCH","WEAK TREND / MOMENTUM"
 if pts>=CFG.buy_score:return int(pts),"APEX BUY",setup
 if pts>=CFG.watch_score:return int(pts),"WATCH",setup
 return int(pts),"REJECT","QUALITY SCORE TOO LOW"
def generate_signals(f:pd.DataFrame)->pd.DataFrame:
 d=f[f.DATE==f.DATE.max()].copy(); vals=d.apply(score_row,axis=1,result_type="expand"); vals.columns=["SCORE","SIGNAL","REASON"]; d=pd.concat([d,vals],axis=1)
 d["STOP"]=d.CLOSE-CFG.stop_atr*d.ATR14; d["STOP_PCT"]=(d.CLOSE-d.STOP)/d.CLOSE*100; d["ENTRY_TRIGGER"]=np.where(d.SIGNAL.eq("APEX BUY"),d.CLOSE*1.002,np.nan)
 d["T1"]=d.CLOSE+2*(d.CLOSE-d.STOP); d["T2"]=d.CLOSE+3*(d.CLOSE-d.STOP); d["T3"]=d.CLOSE+4*(d.CLOSE-d.STOP)
 d=d[(d.SIGNAL!="APEX BUY")|d.STOP_PCT.between(CFG.min_stop_pct,CFG.max_stop_pct)]; return d.sort_values(["SCORE","MOM_RANK","RS_RANK"],ascending=False)

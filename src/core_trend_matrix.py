from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
from indicator import add_indicators_all

WEIGHTS = {'EMA50':15,'EMA100':15,'EMA200':20,'RSI':10,'RS':15,'VOLUME':10,'ATR':5,'52W_HIGH':10}

def _num(x):
    try:
        v=float(x)
        return v if np.isfinite(v) else np.nan
    except Exception:
        return np.nan

def _score_row(r):
    close=_num(r.CLOSE_PRICE); e50=_num(r.EMA50); e100=_num(r.EMA100); e200=_num(r.EMA200)
    rsi=_num(r.RSI14); rs=_num(r.RS_VS_UNIVERSE); vol=_num(r.VOL_RATIO); atr=_num(r.ATR_PCT); d52=_num(r.DIST_52W_HIGH_PCT)
    s=0; parts={}
    parts['EMA50']=WEIGHTS['EMA50'] if np.isfinite(close) and np.isfinite(e50) and close>e50 and _num(r.EMA50_SLOPE_5)>0 else 0
    parts['EMA100']=WEIGHTS['EMA100'] if np.isfinite(close) and np.isfinite(e100) and close>e100 and _num(r.EMA100_SLOPE_5)>0 else 0
    parts['EMA200']=WEIGHTS['EMA200'] if np.isfinite(close) and np.isfinite(e200) and close>e200 and _num(r.EMA200_SLOPE_5)>0 else 0
    if np.isfinite(rsi):
        parts['RSI']=WEIGHTS['RSI'] if 50<=rsi<=65 else 7 if 45<=rsi<50 or 65<rsi<=70 else 0
    else: parts['RSI']=0
    if np.isfinite(rs): parts['RS']=WEIGHTS['RS'] if rs>=3 else 10 if rs>=1 else 5 if rs>=0 else 0
    else: parts['RS']=0
    if np.isfinite(vol): parts['VOLUME']=WEIGHTS['VOLUME'] if vol>=1.5 else 7 if vol>=1.15 else 3 if vol>=0.8 else 0
    else: parts['VOLUME']=0
    if np.isfinite(atr): parts['ATR']=WEIGHTS['ATR'] if 1<=atr<=4 else 3 if atr<=6 else 0
    else: parts['ATR']=0
    if np.isfinite(d52): parts['52W_HIGH']=WEIGHTS['52W_HIGH'] if -15<=d52<=0 else 7 if -25<d52<-15 else 3 if d52<-25 else 0
    else: parts['52W_HIGH']=0
    s=sum(parts.values())
    trend = np.isfinite(close) and all(np.isfinite(x) for x in (e50,e100,e200)) and close>e50>e100>e200
    rs_ok=np.isfinite(rs) and rs>=1
    risk_ok=np.isfinite(atr) and 1<=atr<=6
    near_high=np.isfinite(d52) and d52>=-20
    momentum_ok=np.isfinite(rsi) and 45<=rsi<=70
    if s>=85 and trend and rs_ok and risk_ok and momentum_ok and near_high:
        action='STRONG BUY'
    elif s>=75 and trend and rs_ok and risk_ok and momentum_ok:
        action='BUY ON PULLBACK'
    elif s>=60 and (trend or (np.isfinite(close) and np.isfinite(e200) and close>e200)):
        action='WATCH'
    else:
        action='AVOID'
    return s,action,parts

def build_core_matrix(hist: pd.DataFrame) -> pd.DataFrame:
    h=hist.copy()
    h['DATE']=pd.to_datetime(h['DATE'],errors='coerce')
    h=h.dropna(subset=['DATE','SYMBOL']).copy()
    if 'RS_VS_UNIVERSE' not in h.columns:
        pool=h[h.SYMBOL.astype(str).str.upper().ne('NIFTY 500')].copy()
        med=pool.groupby('DATE')['RET_20D'].median()
        h['RS_VS_UNIVERSE']=h['RET_20D']-h['DATE'].map(med)
    latest=h.DATE.max(); rows=[]
    for _,r in h[h.DATE.eq(latest)].iterrows():
        s,a,p=_score_row(r)
        rows.append({'RANK_SCORE':int(s),'SYMBOL':str(r.SYMBOL),'DATE':latest.strftime('%Y-%m-%d'),'CMP':_num(r.CLOSE_PRICE),'ACTION':a,
                     'EMA50':_num(r.EMA50),'EMA100':_num(r.EMA100),'EMA200':_num(r.EMA200),'EMA_ALIGNMENT':'BULLISH' if np.isfinite(r.CLOSE_PRICE) and r.CLOSE_PRICE>r.EMA50>r.EMA100>r.EMA200 else 'NOT_ALIGNED',
                     'RSI14':_num(r.RSI14),'RS_VS_UNIVERSE':_num(r.RS_VS_UNIVERSE),'RS_RANK':_num(r.get('RS_RANK',np.nan)),'VOLUME_RATIO':_num(r.VOL_RATIO),'ATR_PCT':_num(r.ATR_PCT),'DIST_52W_HIGH_PCT':_num(r.DIST_52W_HIGH_PCT),
                     'SCORE_EMA50':p['EMA50'],'SCORE_EMA100':p['EMA100'],'SCORE_EMA200':p['EMA200'],'SCORE_RSI':p['RSI'],'SCORE_RS':p['RS'],'SCORE_VOLUME':p['VOLUME'],'SCORE_ATR':p['ATR'],'SCORE_52W_HIGH':p['52W_HIGH']})
    return pd.DataFrame(rows).sort_values(['RANK_SCORE','RS_VS_UNIVERSE'],ascending=[False,False]).reset_index(drop=True)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--input',default='output/persistent_history.csv'); ap.add_argument('--output',default='output/core_trend_matrix.csv'); args=ap.parse_args()
    h=pd.read_csv(args.input)
    h=add_indicators_all(h)
    pool=h[h.SYMBOL.astype(str).str.upper().ne('NIFTY 500')].copy(); med=pool.groupby('DATE')['RET_20D'].median(); h['RS_VS_UNIVERSE']=h['RET_20D']-h['DATE'].map(med); h['RS_RANK']=h.groupby('DATE')['RET_20D'].rank(pct=True).mul(100)
    out=build_core_matrix(h); Path(args.output).parent.mkdir(parents=True,exist_ok=True); out.to_csv(args.output,index=False)
    summary=pd.DataFrame([{'DATE':out.DATE.iloc[0] if not out.empty else '', 'ROWS':len(out), 'STRONG_BUY':int((out.ACTION=='STRONG BUY').sum()), 'BUY_ON_PULLBACK':int((out.ACTION=='BUY ON PULLBACK').sum()), 'WATCH':int((out.ACTION=='WATCH').sum()), 'AVOID':int((out.ACTION=='AVOID').sum())}]); summary.to_csv(Path(args.output).with_name('core_trend_matrix_summary.csv'),index=False)
    print(summary.to_string(index=False))

if __name__=='__main__': main()

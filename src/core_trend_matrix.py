from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
from indicator import add_indicators_all

WEIGHTS={'EMA50':15,'EMA100':15,'EMA200':20,'RSI':10,'RS':15,'VOLUME':10,'ATR':5,'52W_HIGH':10}

def _n(x):
    try:
        v=float(x); return v if np.isfinite(v) else np.nan
    except Exception:return np.nan

def score_row(r):
    c,e50,e100,e200=map(_n,[r.get('CLOSE_PRICE'),r.get('EMA50'),r.get('EMA100'),r.get('EMA200')])
    rsi,rs,vol,atr,d52=map(_n,[r.get('RSI14'),r.get('RS_VS_UNIVERSE'),r.get('VOL_RATIO'),r.get('ATR_PCT'),r.get('DIST_52W_HIGH_PCT')])
    p={}
    p['EMA50']=15 if np.isfinite(c) and np.isfinite(e50) and c>e50 and _n(r.get('EMA50_SLOPE_5'))>0 else 0
    p['EMA100']=15 if np.isfinite(c) and np.isfinite(e100) and c>e100 and _n(r.get('EMA100_SLOPE_5'))>0 else 0
    p['EMA200']=20 if np.isfinite(c) and np.isfinite(e200) and c>e200 and _n(r.get('EMA200_SLOPE_5'))>0 else 0
    p['RSI']=10 if np.isfinite(rsi) and 50<=rsi<=65 else 7 if np.isfinite(rsi) and (45<=rsi<50 or 65<rsi<=70) else 0
    p['RS']=15 if np.isfinite(rs) and rs>=3 else 10 if np.isfinite(rs) and rs>=1 else 5 if np.isfinite(rs) and rs>=0 else 0
    p['VOLUME']=10 if np.isfinite(vol) and vol>=1.5 else 7 if np.isfinite(vol) and vol>=1.15 else 3 if np.isfinite(vol) and vol>=.8 else 0
    p['ATR']=5 if np.isfinite(atr) and 1<=atr<=4 else 3 if np.isfinite(atr) and atr<=6 else 0
    p['52W_HIGH']=10 if np.isfinite(d52) and -15<=d52<=0 else 7 if np.isfinite(d52) and -25<d52<-15 else 3 if np.isfinite(d52) and d52<-25 else 0
    s=sum(p.values()); trend=all(np.isfinite(x) for x in [c,e50,e100,e200]) and c>e50>e100>e200
    if s>=85 and trend and np.isfinite(rs) and rs>=1 and np.isfinite(atr) and 1<=atr<=6 and np.isfinite(rsi) and 45<=rsi<=70 and np.isfinite(d52) and d52>=-20:a='STRONG BUY'
    elif s>=75 and trend and np.isfinite(rs) and rs>=1 and np.isfinite(atr) and 1<=atr<=6 and np.isfinite(rsi) and 45<=rsi<=70:a='BUY ON PULLBACK'
    elif s>=60 and (trend or (np.isfinite(c) and np.isfinite(e200) and c>e200)):a='WATCH'
    else:a='AVOID'
    return int(s),a,p

def build(hist):
    h=hist.copy(); h['DATE']=pd.to_datetime(h['DATE'],errors='coerce'); h=h.dropna(subset=['DATE','SYMBOL'])
    if 'RS_VS_UNIVERSE' not in h: h['RS_VS_UNIVERSE']=h['RET_20D']-h.groupby('DATE')['RET_20D'].transform('median')
    latest=h['DATE'].max(); rows=[]
    for _,r in h[h.DATE.eq(latest)].iterrows():
        s,a,p=score_row(r); rows.append({'RANK_SCORE':s,'SYMBOL':str(r.SYMBOL),'DATE':latest.strftime('%Y-%m-%d'),'CMP':_n(r.get('CLOSE_PRICE')),'ACTION':a,'EMA50':_n(r.get('EMA50')),'EMA100':_n(r.get('EMA100')),'EMA200':_n(r.get('EMA200')),'EMA_ALIGNMENT':'BULLISH' if all(np.isfinite(_n(r.get(k))) for k in ['CLOSE_PRICE','EMA50','EMA100','EMA200']) and r.CLOSE_PRICE>r.EMA50>r.EMA100>r.EMA200 else 'NOT_ALIGNED','RSI14':_n(r.get('RSI14')),'RS_VS_UNIVERSE':_n(r.get('RS_VS_UNIVERSE')),'VOLUME_RATIO':_n(r.get('VOL_RATIO')),'ATR_PCT':_n(r.get('ATR_PCT')),'DIST_52W_HIGH_PCT':_n(r.get('DIST_52W_HIGH_PCT')),**{'SCORE_'+k:v for k,v in p.items()}})
    return pd.DataFrame(rows).sort_values(['RANK_SCORE','RS_VS_UNIVERSE'],ascending=False).reset_index(drop=True)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--input',default='output/persistent_history.csv'); ap.add_argument('--output',default='output/core_trend_matrix.csv'); a=ap.parse_args(); h=pd.read_csv(a.input); h=add_indicators_all(h); out=build(h); Path(a.output).parent.mkdir(parents=True,exist_ok=True); out.to_csv(a.output,index=False); pd.DataFrame([{'DATE':out.DATE.iloc[0] if not out.empty else '','ROWS':len(out),'STRONG_BUY':int((out.ACTION=='STRONG BUY').sum()),'BUY_ON_PULLBACK':int((out.ACTION=='BUY ON PULLBACK').sum()),'WATCH':int((out.ACTION=='WATCH').sum()),'AVOID':int((out.ACTION=='AVOID').sum())}]).to_csv(Path(a.output).with_name('core_trend_matrix_summary.csv'),index=False)
if __name__=='__main__':main()

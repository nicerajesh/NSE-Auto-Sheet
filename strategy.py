from __future__ import annotations
import numpy as np
import pandas as pd

# PRE-BREAKOUT ENGINE V2
# Causal daily NSE scanner. One unified 100-point score.
# Market 10 | Trend 15 | Accumulation 15 | Delivery 15 | Volume 10 |
# Compression 10 | Resistance 15 | Relative Strength 5 | Risk/Reward 5.

MIN_HISTORY=200; BUY_SCORE=80; STRONG_SCORE=90; ATR_STOP=1.5
RR1,RR2,RR3=2.0,3.0,4.0

def _f(v,default=np.nan):
    try:
        x=float(v); return x if np.isfinite(x) else default
    except Exception:return default

def _pct(a,b):return (a/b-1)*100 if np.isfinite(a) and np.isfinite(b) and b!=0 else np.nan

def _num(g,c):
    return pd.to_numeric(g[c],errors='coerce').astype(float) if c in g.columns else pd.Series(np.nan,index=g.index)

def _obv(g):
    c=_num(g,'CLOSE_PRICE'); v=_num(g,'TTL_TRD_QNTY').fillna(0)
    return (np.sign(c.diff()).fillna(0)*v).cumsum()

def _market_context(hist):
    d=hist[hist.DATE.eq(hist.DATE.max())].copy()
    if d.empty:return {'score':5,'regime':'NEUTRAL','breadth':np.nan}
    c=_num(d,'CLOSE_PRICE'); e20=_num(d,'EMA20'); e50=_num(d,'EMA50')
    b=((c>e20)&c.notna()&e20.notna()).mean()*100
    t=((e20>e50)&e20.notna()&e50.notna()).mean()*100
    n=d[d.SYMBOL.astype(str).str.upper().isin({'NIFTY','NIFTY50','NIFTY_50','NIFTY 50'})]
    if not n.empty:
        r=n.iloc[-1]; nc,ne20,ne50=_f(r.get('CLOSE_PRICE')),_f(r.get('EMA20')),_f(r.get('EMA50'))
        if nc>ne20>ne50:return {'score':10,'regime':'BULLISH','breadth':b}
        if nc<ne20<ne50:return {'score':2,'regime':'BEARISH','breadth':b}
    if b>=65 and t>=60:return {'score':10,'regime':'BULLISH','breadth':b}
    if b<=35 and t<=40:return {'score':2,'regime':'BEARISH','breadth':b}
    return {'score':6,'regime':'NEUTRAL','breadth':b}

def _row_features(g,i,market):
    g=g.sort_values('DATE').reset_index(drop=True); r=g.iloc[i]
    c=_num(g,'CLOSE_PRICE'); o=_num(g,'OPEN_PRICE'); h=_num(g,'HIGH_PRICE'); l=_num(g,'LOW_PRICE'); v=_num(g,'TTL_TRD_QNTY'); d=_num(g,'DELIV_PER')
    close=_f(r.get('CLOSE_PRICE')); open_=_f(r.get('OPEN_PRICE')); high=_f(r.get('HIGH_PRICE')); low=_f(r.get('LOW_PRICE'))
    e20,e50,e100,e200=[_f(r.get(x)) for x in ('EMA20','EMA50','EMA100','EMA200')]; atr=_f(r.get('ATR14')); rsi=_f(r.get('RSI14')); vol=_f(r.get('VOL_RATIO'))
    deliv_pct=_f(r.get('DELIV_PER')); deliv10=_f(r.get('DELIV_AVG10')); deliv20=_f(r.get('DELIV_AVG20'))
    prior20=_f(r.get('PRIOR_HIGH20')); prior55=_f(r.get('PRIOR_HIGH55'))
    prev_close=_f(c.iloc[i-1]) if i else np.nan; e20p=_f(g.EMA20.iloc[i-5]) if i>=5 else np.nan; e50p=_f(g.EMA50.iloc[i-5]) if i>=5 else np.nan; e100p=_f(g.EMA100.iloc[i-5]) if i>=5 else np.nan
    if not np.isfinite(prior20) and i>=20:prior20=_f(h.iloc[i-20:i].max())
    if not np.isfinite(prior55) and i>=55:prior55=_f(h.iloc[i-55:i].max())
    rng=high-low if np.isfinite(high) and np.isfinite(low) else np.nan; loc=(close-low)/rng if np.isfinite(rng) and rng>0 else np.nan
    bullish=np.isfinite(close) and np.isfinite(open_) and close>open_
    ema_stack=all(np.isfinite(x) for x in (close,e20,e50,e100,e200)) and close>e20>e50>e100>e200
    ema_slope=all(np.isfinite(x) for x in (e20,e50,e100,e20p,e50p,e100p)) and e20>e20p and e50>e50p and e100>=e100p
    trend=ema_stack and ema_slope; trend_ready=all(np.isfinite(x) for x in (close,e20,e50,e100)) and close>e50 and e20>e50 and e50>=e100*.995
    atr_pct=_f(r.get('ATR_PCT')); atr_avg=_f(r.get('ATR_PCT_AVG30')); atr_compress=np.isfinite(atr_pct) and np.isfinite(atr_avg) and atr_pct<atr_avg*.92
    mid=c.rolling(20,min_periods=20).mean(); std=c.rolling(20,min_periods=20).std(ddof=0); bbw=4*std/mid.replace(0,np.nan)*100
    bb_now=_f(bbw.iloc[i]); bb_prev=_f(bbw.iloc[i-5]) if i>=5 else np.nan; bb_compress=np.isfinite(bb_now) and np.isfinite(bb_prev) and bb_now<bb_prev*.90
    range20=(h.iloc[max(0,i-19):i+1].max()-l.iloc[max(0,i-19):i+1].min())/close*100 if np.isfinite(close) else np.nan
    range_tight=np.isfinite(range20) and range20<=8
    compression=(int(atr_compress)+int(bb_compress)+int(range_tight))>=2
    obv=_obv(g); obv_rising=i>=20 and _f(obv.iloc[i])>_f(obv.iloc[i-20])
    upv=v.where(c.diff()>0,0).rolling(10,min_periods=5).mean(); dnv=v.where(c.diff()<0,0).rolling(10,min_periods=5).mean(); up_down=_f(upv.iloc[i])>_f(dnv.iloc[i]) if np.isfinite(_f(upv.iloc[i])) and np.isfinite(_f(dnv.iloc[i])) else False
    base_move=_pct(close,_f(c.iloc[i-20])) if i>=20 else np.nan; price_base=np.isfinite(base_move) and abs(base_move)<=8
    accumulation=obv_rising and (up_down or price_base)
    delivery_good=np.isfinite(deliv_pct) and deliv_pct>=30; delivery_improving=np.isfinite(deliv10) and np.isfinite(deliv20) and deliv10>deliv20; delivery_ok=delivery_good or delivery_improving
    rs=_f(r.get('RS_VS_UNIVERSE')); rs_positive=np.isfinite(rs) and rs>=0; rs_strong=np.isfinite(rs) and rs>=1
    distance=_pct(prior20,close) if np.isfinite(prior20) else np.nan; near=np.isfinite(distance) and 0<=distance<=5; far=np.isfinite(distance) and distance>12
    breakout=np.isfinite(prior20) and close>prior20*1.002 and bullish and np.isfinite(loc) and loc>=.60 and (not np.isfinite(vol) or vol>=1.15)
    failed=np.isfinite(prior20) and prev_close>prior20 and close<prior20 and (not np.isfinite(vol) or vol>=1.15)
    extension=_pct(close,e20); ret5=_f(r.get('RET_5D')); not_extended=(not np.isfinite(extension) or extension<=4) and (not np.isfinite(ret5) or ret5<=8)
    # 100-point score
    market_score=int(_f(market.get('score'),5)); trend_score=15 if trend else 11 if trend_ready else 4; accum_score=15 if accumulation else 7 if obv_rising or up_down else 0
    delivery_score=15 if delivery_good and delivery_improving else 11 if delivery_ok else 3; volume_score=10 if np.isfinite(vol) and vol>=1.2 else 7 if np.isfinite(vol) and vol>=.85 else 2
    compression_score=10 if compression else 5 if atr_compress or bb_compress else 0; resistance_score=15 if breakout else 14 if near and not far else 7 if np.isfinite(distance) and distance<=8 else 2; rs_score=5 if rs_strong else 3 if rs_positive else 0
    stop=close-ATR_STOP*atr if np.isfinite(close) and np.isfinite(atr) and atr>0 else np.nan; low20=_f(r.get('PRIOR_LOW20')); stop=max(stop,low20*.985) if np.isfinite(stop) and np.isfinite(low20) else stop
    risk=close-stop if np.isfinite(close) and np.isfinite(stop) else np.nan; target=prior55 if np.isfinite(prior55) and prior55>close else close+(risk*RR2 if np.isfinite(risk) else np.nan); rr=(target-close)/risk if np.isfinite(target) and np.isfinite(risk) and risk>0 else np.nan; rr_score=5 if np.isfinite(rr) and rr>=3 else 4 if np.isfinite(rr) and rr>=2 else 2 if np.isfinite(rr) and rr>=1.5 else 0
    score=int(max(0,min(100,market_score+trend_score+accum_score+delivery_score+volume_score+compression_score+resistance_score+rs_score+rr_score)))
    if failed:action='SELL / EXIT'
    elif breakout and score>=BUY_SCORE and not_extended:action='BUY NOW'
    elif score>=STRONG_SCORE and near and trend_ready and not_extended:action='BREAKOUT IMMINENT'
    elif score>=BUY_SCORE and near and trend_ready and not_extended:action='BUY ON BREAKOUT'
    else:action='WATCH'
    trigger=prior20*1.005 if np.isfinite(prior20) else np.nan; entry_high=close if action=='BUY NOW' else trigger; entry_low=close if action=='BUY NOW' else prior20
    erisk=entry_high-stop if np.isfinite(entry_high) and np.isfinite(stop) else np.nan; t1=entry_high+erisk*RR1 if np.isfinite(erisk) and erisk>0 else np.nan; t2=entry_high+erisk*RR2 if np.isfinite(erisk) and erisk>0 else np.nan; t3=entry_high+erisk*RR3 if np.isfinite(erisk) and erisk>0 else np.nan; final_rr=(t2-entry_high)/erisk if np.isfinite(t2) and np.isfinite(erisk) and erisk>0 else np.nan
    reasons=[]
    if market_score>=8:reasons.append('Bullish market regime')
    if trend:reasons.append('EMA trend aligned')
    elif trend_ready:reasons.append('Trend developing')
    if accumulation:reasons.append('Accumulation/OBV positive')
    if delivery_improving:reasons.append('Delivery improving')
    if compression:reasons.append('Volatility compression')
    if near:reasons.append(f'Resistance {distance:.1f}% away')
    if rs_strong:reasons.append('Strong relative strength')
    if breakout:reasons.append('Confirmed breakout')
    if failed:reasons.append('Breakout failure')
    if not not_extended:reasons.append('Extended/chasing risk')
    return locals()

def analyze_stock(g,min_score=None,market=None):
    g=g.sort_values('DATE').reset_index(drop=True)
    if len(g)<MIN_HISTORY:return None
    f=_row_features(g,len(g)-1,market or {'score':5,'regime':'NEUTRAL','breadth':np.nan}); threshold=BUY_SCORE if min_score is None else max(60,int(min_score)); action=f['action'] if f['score']>=threshold or f['action']=='SELL / EXIT' else 'WATCH'
    def rv(x,d=2):return round(float(x),d) if np.isfinite(x) else ''
    return {'SYMBOL':str(g.iloc[-1].SYMBOL),'DATE':pd.Timestamp(g.iloc[-1].DATE).strftime('%d-%b-%Y'),'CMP':rv(f['close']),'ACTION':action,'STAGE':'BREAKOUT CONFIRMED' if f['breakout'] else 'PRE-BREAKOUT' if f['near'] and f['compression'] else 'BASE FORMING' if f['compression'] else 'DEVELOPING','HUNTER_SCORE':f['score'],'APEX_SCORE':f['score'],'BREAKOUT_CONFIDENCE':f['score'],'ENTRY_TYPE':'MARKET' if action=='BUY NOW' else 'BREAKOUT TRIGGER' if action in ('BUY ON BREAKOUT','BREAKOUT IMMINENT') else '','MARKET_REGIME':(market or {}).get('regime','NEUTRAL'),'MARKET_BREADTH':rv((market or {}).get('breadth')),'TREND':'STRONG BULLISH' if f['trend'] else 'DEVELOPING' if f['trend_ready'] else 'WEAK','ACCUMULATION':'STRONG' if f['accumulation'] else 'DEVELOPING' if f['obv_rising'] else 'WEAK','DELIVERY':'IMPROVING' if f['delivery_improving'] else 'GOOD' if f['delivery_good'] else 'WEAK','DELIVERY_PCT':rv(f['deliv_pct']),'DELIVERY_VALUE':rv(f['close']*_f(g.iloc[-1].get('DELIV_QTY'))),'VOLUME_RATIO':rv(f['vol']),'ATR_PCT':rv(f['atr_pct']),'ATR_COMPRESSION':'YES' if f['atr_compress'] else 'NO','BB_WIDTH':'COMPRESSING' if f['bb_compress'] else 'NORMAL','BASE_COMPRESSION':'STRONG' if f['compression'] else 'PARTIAL' if (f['atr_compress'] or f['bb_compress']) else 'NO','RESISTANCE':rv(f['prior20']),'RESISTANCE_DISTANCE_PCT':rv(f['distance']),'BREAKOUT_TRIGGER':rv(f['trigger']),'ENTRY_ZONE':f"{rv(f['entry_low'])} - {rv(f['entry_high'])}",'STOP_LOSS':rv(f['stop']),'TARGET_1':rv(f['t1']),'TARGET_2':rv(f['t2']),'TARGET_3':rv(f['t3']),'R_R':rv(f['final_rr']),'RS_VS_UNIVERSE':rv(f['rs']),'RELATIVE_STRENGTH':'STRONG' if f['rs_strong'] else 'POSITIVE' if f['rs_positive'] else 'WEAK','RSI14':rv(f['rsi']),'ADX14':rv(_f(g.iloc[-1].get('ADX14'))),'EMA20':rv(f['e20']),'EMA50':rv(f['e50']),'EMA100':rv(f['e100']),'EMA200':rv(f['e200']),'BREAKOUT_STATUS':'CONFIRMED' if f['breakout'] else 'READY' if f['near'] else 'NOT READY','QUALITY_GATE':'SETUP ENGINE','REASONS':' | '.join(f['reasons']) if f['reasons'] else 'No strong setup on latest confirmed candle'}

def scan_all(hist,min_score=None):
    h=hist.copy().sort_values(['SYMBOL','DATE']); market=_market_context(h); rows=[]
    for sym,g in h.groupby('SYMBOL',sort=False):
        try:
            r=analyze_stock(g,min_score,market)
            if r is not None:rows.append(r)
        except Exception as e:print('Strategy error',sym,e)
    out=pd.DataFrame(rows)
    if out.empty:return out
    order={'BUY NOW':0,'BREAKOUT IMMINENT':1,'BUY ON BREAKOUT':2,'WATCH':3,'SELL / EXIT':4}; out['_o']=out.ACTION.map(order).fillna(9); out=out.sort_values(['_o','HUNTER_SCORE'],ascending=[True,False]).drop(columns='_o').reset_index(drop=True); out.insert(0,'RANK',range(1,len(out)+1)); return out

from __future__ import annotations
import numpy as np
import pandas as pd
from config import STRAT

ACTIONABLE = {'BUY NOW','BUY ON BREAKOUT','BREAKOUT IMMINENT','SWING BUY'}
MIN_HISTORY = STRAT.min_history

def _f(v, default=np.nan):
    try:
        x=float(v); return x if np.isfinite(x) else default
    except Exception: return default

def _num(g,c):
    if c not in g.columns: return pd.Series(np.nan,index=g.index,dtype=float)
    return pd.to_numeric(g[c],errors='coerce').astype(float)

def _pct(a,b):
    a,b=_f(a),_f(b)
    return (a/b-1)*100 if np.isfinite(a) and np.isfinite(b) and b else np.nan

def _obv(g):
    c=_num(g,'CLOSE_PRICE'); v=_num(g,'TTL_TRD_QNTY').fillna(0)
    return (np.sign(c.diff()).fillna(0)*v).cumsum()

def _market_context(hist):
    d=hist[hist.DATE.eq(hist.DATE.max())]
    if d.empty:return {'score':5,'regime':'NEUTRAL','breadth':np.nan}
    c,e20,e50=_num(d,'CLOSE_PRICE'),_num(d,'EMA20'),_num(d,'EMA50'); ok=c.notna()&e20.notna()&e50.notna()
    breadth=float((c[ok]>e20[ok]).mean()*100) if ok.any() else np.nan
    trend=float((e20[ok]>e50[ok]).mean()*100) if ok.any() else np.nan
    if np.isfinite(breadth) and np.isfinite(trend):
        if breadth>=65 and trend>=60:return {'score':10,'regime':'BULLISH','breadth':breadth}
        if breadth<=35 and trend<=40:return {'score':2,'regime':'BEARISH','breadth':breadth}
    return {'score':6,'regime':'NEUTRAL','breadth':breadth}

def _features(g,i,market):
    g=g.sort_values('DATE').reset_index(drop=True); r=g.iloc[i]
    c,o,h,l,v=[_num(g,x) for x in ('CLOSE_PRICE','OPEN_PRICE','HIGH_PRICE','LOW_PRICE','TTL_TRD_QNTY')]
    close,open_,high,low=[_f(r.get(x)) for x in ('CLOSE_PRICE','OPEN_PRICE','HIGH_PRICE','LOW_PRICE')]
    e20,e50,e100,e200=[_f(r.get(x)) for x in ('EMA20','EMA50','EMA100','EMA200')]
    atr=_f(r.get('ATR14')); atr_pct=_f(r.get('ATR_PCT')); atr_avg=_f(r.get('ATR_PCT_AVG30'))
    vol=_f(r.get('VOL_RATIO')); deliv=_f(r.get('DELIV_PER')); d10=_f(r.get('DELIV_AVG10')); d20=_f(r.get('DELIV_AVG20'))
    rsi=_f(r.get('RSI14')); prior20=_f(r.get('PRIOR_HIGH20')); low20=_f(r.get('PRIOR_LOW20'))
    if not np.isfinite(prior20) and i>=20: prior20=_f(h.iloc[i-20:i].max())
    if not np.isfinite(low20) and i>=20: low20=_f(l.iloc[i-20:i].min())
    e20p=_f(g.EMA20.iloc[i-5]) if i>=5 and 'EMA20' in g else np.nan; e50p=_f(g.EMA50.iloc[i-5]) if i>=5 and 'EMA50' in g else np.nan
    trend_ready=all(np.isfinite(x) for x in (close,e20,e50,e100)) and close>e50 and e20>e50 and e50>=e100*.995
    trend_strong=all(np.isfinite(x) for x in (close,e20,e50,e100,e200,e20p,e50p)) and close>e20>e50>e100>e200 and e20>e20p and e50>e50p
    atr_compress=np.isfinite(atr_pct) and np.isfinite(atr_avg) and atr_pct<=atr_avg*.92
    mid=c.rolling(20,min_periods=20).mean(); std=c.rolling(20,min_periods=20).std(ddof=0); bbw=4*std/mid.replace(0,np.nan)*100
    bb_now=_f(bbw.iloc[i]); bb_prev=_f(bbw.iloc[i-5]) if i>=5 else np.nan; bb_compress=np.isfinite(bb_now) and np.isfinite(bb_prev) and bb_now<=bb_prev*.90
    r20=((h.iloc[max(0,i-19):i+1].max()-l.iloc[max(0,i-19):i+1].min())/close*100) if np.isfinite(close) else np.nan
    range_tight=np.isfinite(r20) and r20<=8; compression=int(atr_compress)+int(bb_compress)+int(range_tight)>=2
    obv=_obv(g); obv_rising=i>=20 and _f(obv.iloc[i])>_f(obv.iloc[i-20])
    upv=v.where(c.diff()>0,0).rolling(10,min_periods=5).mean(); dnv=v.where(c.diff()<0,0).rolling(10,min_periods=5).mean()
    volume_acc=np.isfinite(_f(upv.iloc[i])) and np.isfinite(_f(dnv.iloc[i])) and _f(upv.iloc[i])>_f(dnv.iloc[i])
    base_ret20=_pct(close,_f(c.iloc[i-20])) if i>=20 else np.nan; base=np.isfinite(base_ret20) and abs(base_ret20)<=8
    accumulation=obv_rising and (volume_acc or base)
    delivery_good=np.isfinite(deliv) and deliv>=STRAT.delivery_floor; delivery_improving=np.isfinite(d10) and np.isfinite(d20) and d10>d20; delivery_ok=delivery_good and delivery_improving
    rs=_f(r.get('RS_VS_UNIVERSE')); rs_positive=np.isfinite(rs) and rs>=STRAT.min_rs_spread_pct; rs_strong=np.isfinite(rs) and rs>=1
    distance=((prior20-close)/close*100) if np.isfinite(prior20) and close else np.nan; near_res=np.isfinite(distance) and 0<=distance<=STRAT.max_resistance_distance_pct
    confirmed=np.isfinite(prior20) and close>=prior20*1.002
    extension=_pct(close,e20); ret5=_f(r.get('RET_5D')); not_extended=(not np.isfinite(extension) or extension<=STRAT.max_entry_extension_pct) and (not np.isfinite(ret5) or ret5<=8)
    # Explicit 100-point pre-breakout score.
    pre=0
    pre+=15 if near_res else 0; pre+=10 if accumulation and base else 5 if accumulation else 0
    pre+=10 if (i>=3 and _f(l.iloc[i-1])>_f(l.iloc[i-3])) else 0
    pre+=10 if compression else 5 if atr_compress or bb_compress else 0
    pre+=15 if delivery_ok else 8 if delivery_good or delivery_improving else 0
    pre+=10 if obv_rising else 0; pre+=8 if volume_acc else 0; pre+=7 if rs_strong else 4 if rs_positive else 0
    pre+=8 if trend_strong else 5 if trend_ready else 0; pre+=7 if not_extended else 0
    pre=int(min(100,pre))
    # Breakout confirmation score.
    breakout_score=0
    breakout_score+=20 if confirmed else 0; breakout_score+=20 if np.isfinite(vol) and vol>=STRAT.volume_breakout_ratio else 8 if np.isfinite(vol) and vol>=1 else 0
    breakout_score+=15 if delivery_good else 0; breakout_score+=15 if trend_ready else 0; breakout_score+=10 if rs_positive else 0; breakout_score+=10 if close>e20 else 0; breakout_score+=10 if not_extended else 0
    breakout_score=int(min(100,breakout_score))
    # Swing score: trend + pullback + risk, independent of breakout.
    swing=0; swing+=25 if trend_strong else 18 if trend_ready else 0
    pullback=(np.isfinite(ret5) and -8<=ret5<=2) or (np.isfinite(extension) and extension<=2.5)
    swing+=20 if pullback else 8 if not_extended else 0; swing+=15 if rs_positive else 0; swing+=15 if accumulation else 0; swing+=10 if delivery_good else 0; swing+=15 if not_extended else 0
    swing=int(min(100,swing))
    trigger=prior20*1.003 if np.isfinite(prior20) else np.nan
    stop=close-1.5*atr if np.isfinite(close) and np.isfinite(atr) and atr>0 else np.nan
    if np.isfinite(low20) and np.isfinite(stop): stop=max(stop,low20*.985)
    risk=trigger-stop if np.isfinite(trigger) and np.isfinite(stop) else np.nan; risk_pct=risk/trigger*100 if np.isfinite(risk) and trigger else np.nan
    valid_risk=np.isfinite(risk_pct) and STRAT.min_stop_pct<=risk_pct<=STRAT.max_stop_pct
    t1=trigger+risk*STRAT.min_rr1 if np.isfinite(risk) and risk>0 else np.nan; t2=trigger+risk*STRAT.min_rr2 if np.isfinite(risk) and risk>0 else np.nan; t3=trigger+risk*STRAT.min_rr3 if np.isfinite(risk) and risk>0 else np.nan
    # Separate confirmed-breakout entry: never call an already extended breakout a buy.
    breakout_buy=confirmed and breakout_score>=75 and not_extended and valid_risk
    pre_buy=(not confirmed) and pre>=75 and near_res and delivery_ok and accumulation and compression and valid_risk
    imminent=(not confirmed) and pre>=85 and pre_buy
    swing_buy=(not confirmed) and swing>=75 and not_extended and valid_risk and not pre_buy
    if imminent: action='PRE-BREAKOUT BUY'
    elif pre_buy: action='PRE-BREAKOUT WATCH/BUY'
    elif breakout_buy: action='BREAKOUT BUY'
    elif swing_buy: action='SWING BUY'
    else: action='WATCH'
    if confirmed and not breakout_buy: action='AVOID / CHASE'
    probability=int(max(0,min(99,round(pre*.75 + (8 if delivery_ok else 0)+(7 if compression else 0)+(5 if accumulation else 0)+(5 if near_res else 0)))))
    if confirmed: probability=int(min(99,breakout_score))
    if action in ('WATCH','AVOID / CHASE'): probability=min(probability,69)
    reasons=[]
    if trend_strong: reasons.append('Strong trend')
    elif trend_ready: reasons.append('Trend aligned')
    if accumulation: reasons.append('Accumulation/OBV positive')
    if delivery_ok: reasons.append('Delivery strong + improving')
    if compression: reasons.append('Base/volatility compressed')
    if near_res: reasons.append(f'Resistance {distance:.1f}% away')
    if rs_strong: reasons.append('Relative strength strong')
    if not_extended: reasons.append('Not extended')
    if confirmed: reasons.append('Breakout confirmed')
    if not valid_risk: reasons.append('Risk outside configured range')
    return locals()

def analyze_stock(g,min_score=None,market=None):
    g=g.sort_values('DATE').reset_index(drop=True)
    if len(g)<MIN_HISTORY:return None
    market=market or {'score':5,'regime':'NEUTRAL','breadth':np.nan}; f=_features(g,len(g)-1,market); r=g.iloc[-1]
    def rv(x):
        x=_f(x); return round(x,2) if np.isfinite(x) else ''
    close=f['close']; qty=_f(r.get('DELIV_QTY')); delivery_value=close*qty if np.isfinite(close) and np.isfinite(qty) else np.nan
    zone_low=close*.995 if np.isfinite(close) else np.nan; zone_high=close*1.005 if np.isfinite(close) else np.nan
    return {
      'SYMBOL':str(r.SYMBOL),'DATE':pd.Timestamp(r.DATE).strftime('%d-%b-%Y'),'CMP':rv(close),'ACTION':f['action'],
      'CATEGORY':('PRE-BREAKOUT' if f['action'].startswith('PRE-BREAKOUT') else 'BREAKOUT' if f['action']=='BREAKOUT BUY' else 'SWING' if f['action']=='SWING BUY' else 'AVOID' if f['action']=='AVOID / CHASE' else 'WATCH'),
      'NEXT_DAY_ACTION':'BUY' if f['action'] in ('PRE-BREAKOUT BUY','PRE-BREAKOUT WATCH/BUY','BREAKOUT BUY','SWING BUY') else 'WATCH',
      'BUY_DATE':(pd.Timestamp(r.DATE)+pd.tseries.offsets.BDay(1)).strftime('%d-%b-%Y'),'STAGE':f['action'],
      'PRE_BREAKOUT_SCORE':f['pre'],'BREAKOUT_SCORE':f['breakout_score'],'SWING_SCORE':f['swing'],'HUNTER_SCORE':max(f['pre'],f['breakout_score'],f['swing']),'NEXT_DAY_SETUP_SCORE':f['pre'],'BREAKOUT_PROBABILITY':f['probability'],
      'MARKET_REGIME':market.get('regime','NEUTRAL'),'MARKET_BREADTH':rv(market.get('breadth')),'TREND':'STRONG BULLISH' if f['trend_strong'] else 'ALIGNED' if f['trend_ready'] else 'WEAK',
      'ACCUMULATION':'STRONG' if f['accumulation'] else 'WEAK','DELIVERY':'STRONG + IMPROVING' if f['delivery_ok'] else 'GOOD' if f['delivery_good'] else 'WEAK','DELIVERY_PCT':rv(f['deliv']),'DELIVERY_VALUE':rv(delivery_value),
      'VOLUME_RATIO':rv(f['vol']),'ATR_PCT':rv(f['atr_pct']),'ATR_COMPRESSION':'YES' if f['atr_compress'] else 'NO','BB_WIDTH':'COMPRESSING' if f['bb_compress'] else 'NORMAL','BASE_COMPRESSION':'STRONG' if f['compression'] else 'PARTIAL' if (f['atr_compress'] or f['bb_compress']) else 'NO',
      'RESISTANCE':rv(f['prior20']),'RESISTANCE_DISTANCE_PCT':rv(f['distance']),'BREAKOUT_TRIGGER':rv(f['trigger']),'ENTRY_TRIGGER':rv(f['trigger']),'ENTRY_ZONE':f'{rv(zone_low)} - {rv(zone_high)}','STOP_LOSS':rv(f['stop']),'RISK_PCT':rv(f['risk_pct']),'TARGET_1':rv(f['t1']),'TARGET_2':rv(f['t2']),'TARGET_3':rv(f['t3']),'R_R':rv(STRAT.min_rr2),
      'RS_VS_UNIVERSE':rv(f['rs']),'RELATIVE_STRENGTH':'STRONG' if f['rs_strong'] else 'POSITIVE' if f['rs_positive'] else 'WEAK','RSI14':rv(f['rsi']),'ADX14':rv(r.get('ADX14')),
      'EMA20':rv(f['e20']),'EMA50':rv(f['e50']),'EMA100':rv(f['e100']),'EMA200':rv(f['e200']),'BREAKOUT_STATUS':'CONFIRMED' if f['confirmed'] else 'NOT YET BROKEN','QUALITY_GATE':'MODEL RULES','REASONS':' | '.join(f['reasons']) if f['reasons'] else 'No qualified setup'
    }

def scan_all(hist,min_score=None):
    h=hist.copy().sort_values(['SYMBOL','DATE']); market=_market_context(h); rows=[]
    for sym,g in h.groupby('SYMBOL',sort=False):
        try:
            r=analyze_stock(g,min_score,market)
            if r is not None:rows.append(r)
        except Exception as e: print('Strategy error',sym,e)
    out=pd.DataFrame(rows)
    if out.empty:return out
    order={'PRE-BREAKOUT BUY':0,'PRE-BREAKOUT WATCH/BUY':1,'BREAKOUT BUY':2,'SWING BUY':3,'WATCH':4,'AVOID / CHASE':5}
    out['_o']=out.ACTION.map(order).fillna(9); out=out.sort_values(['_o','BREAKOUT_PROBABILITY','HUNTER_SCORE'],ascending=[True,False,False]).drop(columns='_o').reset_index(drop=True); out.insert(0,'RANK',range(1,len(out)+1)); return out

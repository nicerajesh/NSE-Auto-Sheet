from __future__ import annotations
import numpy as np
import pandas as pd
from config import STRAT

ACTIONABLE = {'PRE-BREAKOUT BUY','BREAKOUT BUY','SWING BUY'}
BUY_ACTIONS = ACTIONABLE
MIN_HISTORY = STRAT.min_history


def _f(v, default=np.nan):
    try:
        x=float(v)
        return x if np.isfinite(x) else default
    except Exception:
        return default


def _num(g,c):
    if c not in g.columns:
        return pd.Series(np.nan,index=g.index,dtype=float)
    return pd.to_numeric(g[c],errors='coerce').astype(float)


def _pct(a,b):
    a,b=_f(a),_f(b)
    return (a/b-1)*100 if np.isfinite(a) and np.isfinite(b) and b else np.nan


def _obv(g):
    c=_num(g,'CLOSE_PRICE'); v=_num(g,'TTL_TRD_QNTY').fillna(0)
    return (np.sign(c.diff()).fillna(0)*v).cumsum()


def _market_context(hist):
    d=hist[hist.DATE.eq(hist.DATE.max())]
    if d.empty:
        return {'score':5,'regime':'NEUTRAL','breadth':np.nan}
    c,e20,e50=_num(d,'CLOSE_PRICE'),_num(d,'EMA20'),_num(d,'EMA50')
    ok=c.notna()&e20.notna()&e50.notna()
    breadth=float((c[ok]>e20[ok]).mean()*100) if ok.any() else np.nan
    trend=float((e20[ok]>e50[ok]).mean()*100) if ok.any() else np.nan
    if np.isfinite(breadth) and np.isfinite(trend):
        if breadth>=65 and trend>=60:return {'score':10,'regime':'BULLISH','breadth':breadth}
        if breadth<=35 and trend<=40:return {'score':2,'regime':'BEARISH','breadth':breadth}
    return {'score':6,'regime':'NEUTRAL','breadth':breadth}


def _resistance_tests(g,i,resistance):
    if not np.isfinite(resistance) or i<10:
        return 0
    h=_num(g,'HIGH_PRICE')
    tol=STRAT.resistance_test_tolerance_pct/100.0
    start=max(0,i-40)
    tests=0
    last_test=-99
    for j in range(start,i):
        hv=_f(h.iloc[j])
        if np.isfinite(hv) and abs(hv/resistance-1)<=tol and j-last_test>=3:
            tests+=1
            last_test=j
    return tests


def _higher_low(g,i):
    l=_num(g,'LOW_PRICE')
    if i<8:return False
    a=_f(l.iloc[i-2]); b=_f(l.iloc[i-5]); c=_f(l.iloc[i-8])
    return all(np.isfinite(x) for x in (a,b,c)) and a>b>=c


def _features(g,i,market):
    g=g.sort_values('DATE').reset_index(drop=True)
    r=g.iloc[i]
    c,o,h,l,v=[_num(g,x) for x in ('CLOSE_PRICE','OPEN_PRICE','HIGH_PRICE','LOW_PRICE','TTL_TRD_QNTY')]
    close,open_,high,low=[_f(r.get(x)) for x in ('CLOSE_PRICE','OPEN_PRICE','HIGH_PRICE','LOW_PRICE')]
    e20,e50,e100,e200=[_f(r.get(x)) for x in ('EMA20','EMA50','EMA100','EMA200')]
    atr=_f(r.get('ATR14')); atr_pct=_f(r.get('ATR_PCT')); atr_avg=_f(r.get('ATR_PCT_AVG30'))
    vol=_f(r.get('VOL_RATIO')); deliv=_f(r.get('DELIV_PER')); d10=_f(r.get('DELIV_AVG10')); d20=_f(r.get('DELIV_AVG20'))
    rsi=_f(r.get('RSI14')); adx=_f(r.get('ADX14')); rs=_f(r.get('RS_VS_UNIVERSE'))
    prior20=_f(r.get('PRIOR_HIGH20')); low20=_f(r.get('PRIOR_LOW20'))
    if not np.isfinite(prior20) and i>=20: prior20=_f(h.iloc[i-20:i].max())
    if not np.isfinite(low20) and i>=20: low20=_f(l.iloc[i-20:i].min())

    e20p=_f(g.EMA20.iloc[i-5]) if i>=5 and 'EMA20' in g else np.nan
    e50p=_f(g.EMA50.iloc[i-5]) if i>=5 and 'EMA50' in g else np.nan
    trend_ready=all(np.isfinite(x) for x in (close,e20,e50,e100)) and close>e50 and e20>e50 and e50>=e100*.995
    trend_strong=all(np.isfinite(x) for x in (close,e20,e50,e100,e200,e20p,e50p)) and close>e20>e50>e100>e200 and e20>e20p and e50>e50p

    # Compression is causal and requires at least two independent signals.
    atr_compress=np.isfinite(atr_pct) and np.isfinite(atr_avg) and atr_pct<=atr_avg*.92
    mid=c.rolling(20,min_periods=20).mean(); std=c.rolling(20,min_periods=20).std(ddof=0)
    bbw=4*std/mid.replace(0,np.nan)*100
    bb_now=_f(bbw.iloc[i]); bb_prev=_f(bbw.iloc[i-5]) if i>=5 else np.nan
    bb_compress=np.isfinite(bb_now) and np.isfinite(bb_prev) and bb_now<=bb_prev*.90
    base_range=((h.iloc[max(0,i-STRAT.min_base_days+1):i+1].max()-l.iloc[max(0,i-STRAT.min_base_days+1):i+1].min())/close*100) if np.isfinite(close) else np.nan
    range_tight=np.isfinite(base_range) and base_range<=STRAT.max_base_range_pct
    compression=(int(atr_compress)+int(bb_compress)+int(range_tight)>=2)

    obv=_obv(g)
    obv_rising=i>=20 and _f(obv.iloc[i])>_f(obv.iloc[i-20])
    upv=v.where(c.diff()>0,0).rolling(10,min_periods=7).mean()
    dnv=v.where(c.diff()<0,0).rolling(10,min_periods=7).mean()
    up=_f(upv.iloc[i]); down=_f(dnv.iloc[i])
    volume_acc=np.isfinite(up) and np.isfinite(down) and up>down

    base_ret20=_pct(close,_f(c.iloc[i-20])) if i>=20 else np.nan
    base_stable=np.isfinite(base_ret20) and abs(base_ret20)<=8
    accumulation=obv_rising and (volume_acc or base_stable)

    delivery_good=np.isfinite(deliv) and deliv>=STRAT.delivery_floor
    delivery_improving=np.isfinite(d10) and np.isfinite(d20) and d10>d20
    delivery_ok=delivery_good and delivery_improving

    rs_positive=np.isfinite(rs) and rs>=STRAT.min_rs_spread_pct
    rs_strong=np.isfinite(rs) and rs>=1
    rs_improving=i>=10 and np.isfinite(_f(g.RS_VS_UNIVERSE.iloc[i-5])) and rs>_f(g.RS_VS_UNIVERSE.iloc[i-5]) if 'RS_VS_UNIVERSE' in g else False

    distance=((prior20-close)/close*100) if np.isfinite(prior20) and close else np.nan
    near_res=np.isfinite(distance) and 0<=distance<=STRAT.max_resistance_distance_pct
    tests=_resistance_tests(g,i,prior20)
    higher_low=_higher_low(g,i)
    confirmed=np.isfinite(prior20) and close>=prior20*1.002

    extension=_pct(close,e20)
    ret5=_f(r.get('RET_5D')); ret20=_f(r.get('RET_20D'))
    not_extended=(not np.isfinite(extension) or extension<=STRAT.max_entry_extension_pct) and (not np.isfinite(ret5) or ret5<=8)
    momentum_ok=(not np.isfinite(rsi) or 50<=rsi<=72) and (not np.isfinite(ret5) or ret5>=-1.5)
    close_strength=((close-low)/(high-low)) if np.isfinite(high) and np.isfinite(low) and high>low else np.nan
    breakout_candle=confirmed and np.isfinite(close_strength) and close_strength>=STRAT.breakout_min_close_strength
    breakout_volume=np.isfinite(vol) and vol>=STRAT.volume_breakout_ratio
    breakout_extension=not np.isfinite(extension) or extension<=STRAT.max_breakout_extension_pct

    # Explicit 100-point score. It is a setup score, NOT a literal statistical probability.
    pre=0
    pre+=15 if near_res else 0
    pre+=10 if tests>=STRAT.min_resistance_tests else 5 if tests==STRAT.min_resistance_tests-1 else 0
    pre+=10 if higher_low else 0
    pre+=10 if compression else 0
    pre+=15 if delivery_ok else 0
    pre+=10 if obv_rising else 0
    pre+=8 if volume_acc else 0
    pre+=7 if rs_strong else 4 if rs_positive else 0
    pre+=8 if trend_strong else 5 if trend_ready else 0
    pre+=7 if not_extended else 0
    pre=int(min(100,pre))

    breakout_score=0
    breakout_score+=20 if confirmed else 0
    breakout_score+=20 if breakout_volume else 0
    breakout_score+=15 if delivery_good else 0
    breakout_score+=15 if trend_ready else 0
    breakout_score+=10 if rs_positive else 0
    breakout_score+=10 if breakout_candle else 0
    breakout_score+=10 if breakout_extension else 0
    breakout_score=int(min(100,breakout_score))

    swing=0
    swing+=25 if trend_strong else 18 if trend_ready else 0
    pullback=(np.isfinite(ret5) and -8<=ret5<=2) or (np.isfinite(extension) and extension<=2.5)
    swing+=20 if pullback else 0
    swing+=15 if rs_positive else 0
    swing+=15 if accumulation else 0
    swing+=10 if delivery_good else 0
    swing+=15 if not_extended else 0
    swing=int(min(100,swing))

    # Hard gates. No score can override these.
    pre_gate=(
        not confirmed and near_res and tests>=STRAT.min_resistance_tests and
        higher_low and compression and delivery_ok and accumulation and
        trend_ready and rs_positive and rs_improving and momentum_ok and
        not_extended and np.isfinite(adx) and adx>=STRAT.min_adx and
        market.get('score',5)>=STRAT.min_regime_score
    )

    # Entry is the current close/zone for a pre-breakout trade; breakout trigger is separate.
    trigger=prior20*1.003 if np.isfinite(prior20) else np.nan
    entry=close
    stop=close-1.5*atr if np.isfinite(close) and np.isfinite(atr) and atr>0 else np.nan
    if np.isfinite(low20) and np.isfinite(stop): stop=max(stop,low20*.985)
    risk=entry-stop if np.isfinite(entry) and np.isfinite(stop) else np.nan
    risk_pct=risk/entry*100 if np.isfinite(risk) and entry else np.nan
    valid_risk=np.isfinite(risk_pct) and STRAT.min_stop_pct<=risk_pct<=STRAT.max_stop_pct

    # Targets are based on entry risk, not the breakout trigger, for pre-breakout trades.
    t1=entry+risk*STRAT.min_rr1 if np.isfinite(risk) and risk>0 else np.nan
    t2=entry+risk*STRAT.min_rr2 if np.isfinite(risk) and risk>0 else np.nan
    t3=entry+risk*STRAT.min_rr3 if np.isfinite(risk) and risk>0 else np.nan

    pre_buy=pre_gate and pre>=STRAT.buy_score and valid_risk
    breakout_buy=(confirmed and breakout_score>=STRAT.buy_score and breakout_volume and delivery_good and trend_ready and rs_positive and breakout_candle and breakout_extension and valid_risk)
    swing_buy=(not confirmed and swing>=STRAT.buy_score and trend_ready and rs_positive and not_extended and valid_risk and not pre_buy)

    if pre_buy: action='PRE-BREAKOUT BUY'
    elif breakout_buy: action='BREAKOUT BUY'
    elif swing_buy: action='SWING BUY'
    elif confirmed: action='AVOID / CHASE'
    else: action='WATCH'

    # Do not fabricate 99% probabilities. This is a capped model confidence score.
    probability=int(min(90,max(0,round(pre*0.90))))
    if confirmed: probability=int(min(90,breakout_score*0.90))
    if action in ('WATCH','AVOID / CHASE'): probability=min(probability,69)

    reasons=[]
    if trend_strong: reasons.append('Strong trend')
    elif trend_ready: reasons.append('Trend aligned')
    if higher_low: reasons.append('Higher-low structure')
    if tests>=STRAT.min_resistance_tests: reasons.append(f'{tests} resistance tests')
    if accumulation: reasons.append('Accumulation/OBV positive')
    if delivery_ok: reasons.append('Delivery strong + improving')
    if compression: reasons.append('Base/volatility compressed')
    if near_res: reasons.append(f'Resistance {distance:.1f}% away')
    if rs_strong: reasons.append('Relative strength strong')
    if not_extended: reasons.append('Not extended')
    if confirmed: reasons.append('Breakout confirmed')
    if not valid_risk: reasons.append('Risk outside configured range')
    if not rs_improving and STRAT.require_rs_improving: reasons.append('RS not improving')
    if tests<STRAT.min_resistance_tests and not confirmed: reasons.append('Insufficient resistance tests')

    return locals()


def analyze_stock(g,min_score=None,market=None):
    g=g.sort_values('DATE').reset_index(drop=True)
    if len(g)<MIN_HISTORY:return None
    market=market or {'score':5,'regime':'NEUTRAL','breadth':np.nan}
    f=_features(g,len(g)-1,market); r=g.iloc[-1]
    def rv(x):
        x=_f(x); return round(x,2) if np.isfinite(x) else ''
    close=f['close']
    qty=_f(r.get('DELIV_QTY')); delivery_value=close*qty if np.isfinite(close) and np.isfinite(qty) else np.nan
    zone_low=close*.995 if np.isfinite(close) else np.nan; zone_high=close*1.005 if np.isfinite(close) else np.nan
    category=('PRE-BREAKOUT' if f['action']=='PRE-BREAKOUT BUY' else 'BREAKOUT' if f['action']=='BREAKOUT BUY' else 'SWING' if f['action']=='SWING BUY' else 'AVOID' if f['action']=='AVOID / CHASE' else 'WATCH')
    return {
      'SYMBOL':str(r.SYMBOL),'DATE':pd.Timestamp(r.DATE).strftime('%d-%b-%Y'),'CMP':rv(close),'ACTION':f['action'],'CATEGORY':category,
      'NEXT_DAY_ACTION':'BUY' if f['action'] in BUY_ACTIONS else 'WATCH','BUY_DATE':(pd.Timestamp(r.DATE)+pd.tseries.offsets.BDay(1)).strftime('%d-%b-%Y'),'STAGE':f['action'],
      'PRE_BREAKOUT_SCORE':f['pre'],'BREAKOUT_SCORE':f['breakout_score'],'SWING_SCORE':f['swing'],'HUNTER_SCORE':max(f['pre'],f['breakout_score'],f['swing']),'NEXT_DAY_SETUP_SCORE':f['pre'],'BREAKOUT_PROBABILITY':f['probability'],
      'MARKET_REGIME':market.get('regime','NEUTRAL'),'MARKET_BREADTH':rv(market.get('breadth')),'TREND':'STRONG BULLISH' if f['trend_strong'] else 'ALIGNED' if f['trend_ready'] else 'WEAK',
      'ACCUMULATION':'STRONG' if f['accumulation'] else 'WEAK','DELIVERY':'STRONG + IMPROVING' if f['delivery_ok'] else 'GOOD' if f['delivery_good'] else 'WEAK','DELIVERY_PCT':rv(f['deliv']),'DELIVERY_VALUE':rv(delivery_value),
      'VOLUME_RATIO':rv(f['vol']),'ATR_PCT':rv(f['atr_pct']),'ATR_COMPRESSION':'YES' if f['atr_compress'] else 'NO','BB_WIDTH':'COMPRESSING' if f['bb_compress'] else 'NORMAL','BASE_COMPRESSION':'STRONG' if f['compression'] else 'PARTIAL' if (f['atr_compress'] or f['bb_compress']) else 'NO',
      'RESISTANCE':rv(f['prior20']),'RESISTANCE_DISTANCE_PCT':rv(f['distance']),'RESISTANCE_TESTS':f['tests'],'BREAKOUT_TRIGGER':rv(f['trigger']),'ENTRY_TRIGGER':rv(f['trigger']),'ENTRY_ZONE':f'{rv(zone_low)} - {rv(zone_high)}','ENTRY_PRICE':rv(close),'STOP_LOSS':rv(f['stop']),'RISK_PCT':rv(f['risk_pct']),'TARGET_1':rv(f['t1']),'TARGET_2':rv(f['t2']),'TARGET_3':rv(f['t3']),'R_R':rv(STRAT.min_rr2),
      'RS_VS_UNIVERSE':rv(f['rs']),'RELATIVE_STRENGTH':'STRONG' if f['rs_strong'] else 'POSITIVE' if f['rs_positive'] else 'WEAK','RSI14':rv(f['rsi']),'ADX14':rv(f['adx']),
      'EMA20':rv(f['e20']),'EMA50':rv(f['e50']),'EMA100':rv(f['e100']),'EMA200':rv(f['e200']),'BREAKOUT_STATUS':'CONFIRMED' if f['confirmed'] else 'NOT YET BROKEN','QUALITY_GATE':'MODEL RULES','REASONS':' | '.join(f['reasons']) if f['reasons'] else 'No qualified setup'
    }


def scan_all(hist,min_score=None):
    h=hist.copy().sort_values(['SYMBOL','DATE']); market=_market_context(h); rows=[]
    for sym,g in h.groupby('SYMBOL',sort=False):
        try:
            r=analyze_stock(g,min_score,market)
            if r is not None: rows.append(r)
        except Exception as e:
            print('Strategy error',sym,e)
    out=pd.DataFrame(rows)
    if out.empty:return out
    order={'PRE-BREAKOUT BUY':0,'BREAKOUT BUY':1,'SWING BUY':2,'WATCH':3,'AVOID / CHASE':4}
    out['_o']=out.ACTION.map(order).fillna(9)
    out=out.sort_values(['_o','BREAKOUT_PROBABILITY','HUNTER_SCORE'],ascending=[True,False,False]).drop(columns='_o').reset_index(drop=True)
    out.insert(0,'RANK',range(1,len(out)+1))
    return out

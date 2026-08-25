from __future__ import annotations
import numpy as np
import pandas as pd

# RY APEX MATRIX V42 — Python mirror of the supplied Pine Script.
# BUY is a SAME-CANDLE, confirmed-close signal. No future trigger search.
PINE_BUY_SCORE=75
PINE_APEX_SCORE=88
PINE_TACTICAL_SCORE=82
COOLDOWN_BARS=5
INITIAL_ATR=2.5
TRAIL_ATR=2.5
RR1,RR2=2.0,3.0

def _f(v,default=np.nan):
    try:
        x=float(v); return x if np.isfinite(x) else default
    except Exception:return default

def _features(w,i):
    r=w.iloc[i]; c=_f(r.CLOSE_PRICE); o=_f(r.OPEN_PRICE); h=_f(r.HIGH_PRICE); l=_f(r.LOW_PRICE)
    e20=_f(r.get('EMA20')); e50=_f(r.get('EMA50')); e200=_f(r.get('EMA200')); rsi=_f(r.get('RSI14')); atr=_f(r.get('ATR14')); vr=_f(r.get('VOL_RATIO')); adx=_f(r.get('ADX14')); plus=_f(r.get('PLUS_DI14')); minus=_f(r.get('MINUS_DI14'))
    prior20=_f(r.get('PRIOR_HIGH20'))
    if not np.isfinite(prior20) and i>=20:prior20=_f(w.HIGH_PRICE.iloc[i-20:i].max())
    resistance=prior20; is_breakout=np.isfinite(resistance) and c>resistance*1.001
    res_dist=abs(c-resistance)/resistance*100 if np.isfinite(resistance) and resistance>0 else 0
    near_res=c<resistance and res_dist<=3 if np.isfinite(resistance) else False
    rng=h-l; body=abs(c-o); body_ratio=body/rng if rng>0 else 0; close_pos=(c-l)/rng if rng>0 else 0; bullish=c>o; bull_quality=bullish and body_ratio>=.40 and close_pos>=.65
    e20p5=_f(w.EMA20.iloc[i-5]) if i>=5 else np.nan; e50p5=_f(w.EMA50.iloc[i-5]) if i>=5 else np.nan; e200p10=_f(w.EMA200.iloc[i-10]) if i>=10 else np.nan
    strong_trend=c>e20>e50>e200 and e20>e20p5 and e50>e50p5 if all(np.isfinite(x) for x in (c,e20,e50,e200,e20p5,e50p5)) else False
    healthy_trend=c>e50 and e50>e200 if all(np.isfinite(x) for x in (c,e50,e200)) else False
    bull_trend=c>e50 if np.isfinite(c) and np.isfinite(e50) else False
    mc=_f(r.get('MARKET_CLOSE')); me20=_f(r.get('MARKET_EMA20')); me50=_f(r.get('MARKET_EMA50')); me200=_f(r.get('MARKET_EMA200'))
    market_bull=mc>me20>me50>me200 if all(np.isfinite(x) for x in (mc,me20,me50,me200)) else False
    market_neutral=mc>me50 and not market_bull if np.isfinite(mc) and np.isfinite(me50) else False
    market_bear=mc<me50 if np.isfinite(mc) and np.isfinite(me50) else False
    penalty=0 if market_bull or not np.isfinite(mc) else 3 if market_neutral else 8
    market_regime='BULLISH' if market_bull else 'NEUTRAL' if market_neutral else 'BEARISH' if market_bear else 'UNAVAILABLE'
    c20=_f(w.CLOSE_PRICE.iloc[i-20]) if i>=20 else np.nan; mc20=_f(w.MARKET_CLOSE.iloc[i-20]) if i>=20 and 'MARKET_CLOSE' in w else np.nan
    stock_roc=(c/c20-1)*100 if np.isfinite(c20) and c20>0 else 0; market_roc=(mc/mc20-1)*100 if np.isfinite(mc20) and mc20>0 else 0; rs=stock_roc-market_roc if np.isfinite(mc20) else 0
    rs_strong=rs>=5; rs_positive=rs>0
    rsi1=_f(w.RSI14.iloc[i-1]) if i>=1 else np.nan; rsi_healthy=np.isfinite(rsi) and 50<=rsi<=72; rsi_strong=np.isfinite(rsi) and 58<=rsi<=72; rsi_recovery=np.isfinite(rsi) and np.isfinite(rsi1) and rsi>50 and rsi>rsi1
    adx_good=np.isfinite(adx) and np.isfinite(plus) and np.isfinite(minus) and adx>=18 and plus>minus; adx_strong=np.isfinite(adx) and np.isfinite(plus) and np.isfinite(minus) and adx>=25 and plus>minus
    vr1=_f(w.VOL_RATIO.iloc[i-1]) if i>=1 else np.nan; volume_strong=np.isfinite(vr) and vr>=2; volume_confirmed=np.isfinite(vr) and vr>=1.3; volume_normal=np.isfinite(vr) and vr>=.8; volume_dry=np.isfinite(vr) and vr<=.75; volume_expansion=np.isfinite(vr1) and vr1<=.75 and volume_confirmed; volume_acceleration=np.isfinite(vr) and np.isfinite(vr1) and vr>vr1 and vr>=1
    avg_range=(w.HIGH_PRICE-w.LOW_PRICE).rolling(20).mean().iloc[i] if i>=19 else np.nan; atr_fast=w.ATR14.rolling(5).mean().iloc[i] if i>=4 else np.nan; atr_slow=w.ATR14.rolling(20).mean().iloc[i] if i>=19 else np.nan
    vcp_potential=np.isfinite(avg_range) and rng<=avg_range*.8 and np.isfinite(atr_fast) and np.isfinite(atr_slow) and atr_fast<atr_slow; vcp_confirmed=vcp_potential and volume_dry; vcp_breakout=vcp_confirmed and is_breakout and volume_confirmed
    rh=w.HIGH_PRICE.iloc[max(0,i-10):i].max() if i>=10 else np.nan; rl=w.LOW_PRICE.iloc[max(0,i-10):i].min() if i>=10 else np.nan; width=(rh-rl)/rl*100 if np.isfinite(rl) and rl>0 else 999
    accumulation=healthy_trend and volume_dry and width<=12 and c>=e50 if np.isfinite(e50) else False
    pullback=healthy_trend and l<=e20*1.03 and c>=e20*.98 and rsi_recovery if np.isfinite(e20) else False
    e20p=_f(w.EMA20.iloc[i-1]) if i>=1 else np.nan; prevc=_f(w.CLOSE_PRICE.iloc[i-1]) if i>=1 else np.nan
    ema_recovery=c>e20 and np.isfinite(e20p) and prevc<=e20p and bullish and rsi_recovery and np.isfinite(vr) and vr>=1 if np.isfinite(e20) else False
    strong_breakout=is_breakout and volume_strong and bull_quality and c>e20 and c>e50
    confirmed_breakout=is_breakout and volume_confirmed and bullish and close_pos>=.60 and c>e50
    early_breakout=is_breakout and np.isfinite(vr) and vr>=1 and bullish and c>e20
    extension=(c-e20)/atr if np.isfinite(atr) and atr>0 and np.isfinite(e20) else np.nan; over_extended=np.isfinite(extension) and extension>3
    atr_pct=atr/c*100 if np.isfinite(atr) and c>0 else np.nan
    trend_score=25 if strong_trend else 19 if healthy_trend else 12 if bull_trend else 0
    rs_score=15 if rs_strong else 11 if rs_positive else 6 if rs>-3 else 0
    momentum_score=15 if adx_strong and rsi_strong else 12 if adx_good and rsi_healthy else 8 if rsi_healthy or rsi_recovery else 3
    volume_score=15 if volume_strong or volume_expansion else 12 if volume_confirmed else 9 if volume_acceleration else 8 if volume_dry else 5 if volume_normal else 2
    structure_score=15 if vcp_breakout or strong_breakout else 13 if confirmed_breakout else 11 if vcp_confirmed else 10 if accumulation else 8 if near_res or pullback else 7 if ema_recovery else 3
    risk_score=15 if np.isfinite(atr_pct) and atr_pct<=4 else 12 if np.isfinite(atr_pct) and atr_pct<=7 else 9 if np.isfinite(atr_pct) and atr_pct<=10 else 6 if np.isfinite(atr_pct) and not over_extended else 2
    raw_score=trend_score+rs_score+momentum_score+volume_score+structure_score+risk_score; apex_score=max(0,raw_score-penalty)
    accumulation_setup=accumulation and not is_breakout; pre_breakout=(near_res or vcp_confirmed or accumulation or pullback) and not is_breakout and healthy_trend and not over_extended; watch_setup=(healthy_trend or bull_trend) and (rs_positive or rsi_recovery or vcp_potential)
    normal_setup=confirmed_breakout or strong_breakout or vcp_breakout or ema_recovery; normal_buy=apex_score>=PINE_BUY_SCORE and normal_setup and not over_extended; apex_buy=apex_score>=PINE_APEX_SCORE and (strong_breakout or vcp_breakout) and not over_extended; tactical_buy=(strong_breakout or vcp_breakout) and apex_score>=PINE_TACTICAL_SCORE and not over_extended; final_buy=apex_buy or tactical_buy or normal_buy
    valid_risk=np.isfinite(atr) and (c-atr*INITIAL_ATR)<c
    return locals()

def analyze_stock(g,min_score=None):
    g=g.sort_values('DATE').reset_index(drop=True)
    if len(g)<200:return None
    state=False;entry_i=-1;last_exit=-10**9;latest=None
    for i in range(len(g)):
        f=_features(g,i)
        if state and i>entry_i:
            close=_f(g.CLOSE_PRICE.iloc[i]); e20=_f(g.EMA20.iloc[i]); e50=_f(g.EMA50.iloc[i]); e20p=_f(g.EMA20.iloc[i-1]) if i>=1 else np.nan; e50p=_f(g.EMA50.iloc[i-1]) if i>=1 else np.nan; vr=_f(g.VOL_RATIO.iloc[i]); op=_f(g.OPEN_PRICE.iloc[i]); prevclose=_f(g.CLOSE_PRICE.iloc[i-1]); rsi=_f(g.RSI14.iloc[i]); atr=_f(g.ATR14.iloc[i]); trail=close-atr*TRAIL_ATR if np.isfinite(atr) else -np.inf
            exit_trail=close<trail; exit_e20=np.isfinite(e20) and np.isfinite(e20p) and close<e20 and prevclose<e20p and close<op; exit_e50=np.isfinite(e50) and np.isfinite(e20) and close<e50 and e20<e50; exit_trend=np.isfinite(e20) and np.isfinite(e50) and np.isfinite(e50p) and e20<e50 and e50<e50p; exit_dist=close<op and np.isfinite(vr) and vr>=2 and close<prevclose; exit_mom=np.isfinite(rsi) and rsi<43 and np.isfinite(e20) and close<e20
            if exit_trail or exit_e20 or exit_e50 or exit_trend or exit_dist or exit_mom:state=False;last_exit=i;entry_i=-1
        f=_features(g,i)
        new_buy=(not state) and f['final_buy'] and (i-last_exit>COOLDOWN_BARS) and f['valid_risk']
        if new_buy:state=True;entry_i=i
        f['new_buy']=new_buy;latest=f
    if latest is None:return None
    f=latest;c=f['c'];atr=f['atr'];risk=atr*INITIAL_ATR if np.isfinite(atr) else np.nan;sl=c-risk if np.isfinite(risk) else np.nan
    typ='APEX BUY' if f['apex_buy'] else 'TACTICAL BUY' if f['tactical_buy'] else 'BUY'; stage='STRONG BREAKOUT' if f['strong_breakout'] else 'CONFIRMED BREAKOUT' if f['confirmed_breakout'] else 'VCP BREAKOUT' if f['vcp_breakout'] else 'EMA RECOVERY' if f['ema_recovery'] else 'PRE-BREAKOUT' if f['pre_breakout'] else 'WATCH';action='BUY' if f['new_buy'] else 'HOLD' if state else 'WATCH'
    def rv(x,d=2):return round(float(x),d) if np.isfinite(x) else ''
    return {'SYMBOL':str(g.iloc[-1].SYMBOL),'DATE':pd.Timestamp(g.iloc[-1].DATE).strftime('%d-%b-%Y'),'CMP':rv(c),'ACTION':action,'STAGE':stage,'HUNTER_SCORE':int(round(f['apex_score'])),'APEX_SCORE':int(round(f['apex_score'])),'ENTRY_TYPE':typ if f['new_buy'] else '','MARKET_REGIME':f['market_regime'],'INITIAL_SL':rv(sl),'STOP_LOSS':rv(sl),'TARGET_1':rv(c+risk*RR1 if np.isfinite(risk) else np.nan),'TARGET_2':rv(c+risk*RR2 if np.isfinite(risk) else np.nan),'TARGET_3':rv(c+risk*4 if np.isfinite(risk) else np.nan),'ENTRY_TRIGGER':rv(c),'RESISTANCE':rv(f['resistance']),'RESISTANCE_DISTANCE_PCT':rv(f['res_dist']),'RSI14':rv(f['rsi']),'ADX14':rv(f['adx']),'ATR_PCT':rv(f['atr_pct']),'VOLUME_RATIO':rv(f['vr']),'EMA20':rv(f['e20']),'EMA50':rv(f['e50']),'EMA200':rv(f['e200']),'SETUP':stage,'REASONS':'PINE CONFIRMED: '+typ if f['new_buy'] else 'No new Pine BUY on latest confirmed candle'}

def scan_all(hist,min_score=None):
    rows=[]
    for sym,g in hist.groupby('SYMBOL',sort=False):
        try:
            r=analyze_stock(g,min_score)
            if r and (r['ACTION'] in ('BUY','HOLD') or r['HUNTER_SCORE']>=72):rows.append(r)
        except Exception as e:print('Strategy error',sym,e)
    out=pd.DataFrame(rows)
    if out.empty:return out
    order={'BUY':0,'HOLD':1,'WATCH':2};out['_o']=out.ACTION.map(order).fillna(9);out=out.sort_values(['_o','HUNTER_SCORE'],ascending=[True,False]).drop(columns='_o');out.insert(0,'RANK',range(1,len(out)+1));return out

from __future__ import annotations
import numpy as np,pandas as pd
from config import STRAT

def finite(x):
    try:return np.isfinite(float(x))
    except:return False

def _swing_structure(c):
    lows=[];highs=[]
    for i in range(3,len(c)):
        p=c[max(0,i-3):i]
        if c[i]<=p.min():lows.append(i)
        if c[i]>=p.max():highs.append(i)
    return lows,highs

def analyze_stock(g,min_score=None):
    g=g.sort_values('DATE').reset_index(drop=True)
    if len(g)<STRAT.min_history:return None
    w=g.tail(min(140,len(g))).reset_index(drop=True); c=w.CLOSE_PRICE.astype(float).to_numpy(); n=len(c); cur=float(c[-1]); x=w.iloc[-1]
    lows,highs=_swing_structure(c); recent_lows=[i for i in lows if i>=max(0,n-55)]; low_idx=recent_lows[-1] if recent_lows else int(np.argmin(c[-55:]))+max(0,n-55); low=float(c[low_idx])
    prior_high=float(c[max(0,low_idx-25):low_idx].max()) if low_idx>0 else np.nan; hh_idx=None; hh=np.nan
    for i in range(low_idx+1,n):
        if finite(prior_high) and c[i]>prior_high*1.003:hh_idx=i;hh=float(c[i]);break
    hl_idx=None;hl=np.nan
    if hh_idx is not None and hh_idx<n-1:
        post=c[hh_idx+1:];j=int(np.argmin(post))+hh_idx+1
        if low*1.005<=c[j]<hh*.998:hl_idx=j;hl=float(c[j])
    second_hh=False;hh2=np.nan
    if hl_idx is not None and len(c[hl_idx+1:]):
        post=c[hl_idx+1:];j=int(np.argmax(post))+hl_idx+1
        if c[j]>hh*1.003:second_hh=True;hh2=float(c[j])
    # Resistance must be a genuine prior swing/high and MUST be above current price.
    prior_window=c[:-1][-40:]
    resistance=float(np.percentile(prior_window,95)) if len(prior_window) else cur
    if finite(x.get('PRIOR_HIGH20',np.nan)) and float(x.PRIOR_HIGH20)>cur*1.005:resistance=float(x.PRIOR_HIGH20)
    elif finite(hh) and hh>cur*1.005:resistance=max(resistance,hh)
    if resistance<=cur*1.005:resistance=float(c[:-1].max()) if len(c)>1 else cur*1.02
    res_dist=max(0,(resistance/cur-1)*100)
    rsi=x.get('RSI14',np.nan);adx=x.get('ADX14',np.nan);vol=x.get('VOL_RATIO',np.nan);deliv=x.get('DELIV_PER',np.nan);d10=x.get('DELIV_AVG10',np.nan);atrp=x.get('ATR_PCT',np.nan);atravg=x.get('ATR_PCT_AVG30',np.nan);mh3=x.get('MACD_HIST_SLOPE',np.nan);ema20=x.get('EMA20',np.nan);ema50=x.get('EMA50',np.nan);ema100=x.get('EMA100',np.nan);ema200=x.get('EMA200',np.nan);slope20=x.get('EMA20_SLOPE_5',np.nan);slope50=x.get('EMA50_SLOPE_5',np.nan);ret5=x.get('RET_5D',np.nan);ret20=x.get('RET_20D',np.nan);close_loc=x.get('CLOSE_LOCATION',np.nan);lower_wick=x.get('LOWER_WICK',np.nan)
    no_lower_low=cur>=float(c[-6:-1].min())*.997; low_dist=(cur/low-1)*100; bottom_hold=low_dist<=14 and no_lower_low
    exhaustion=finite(vol) and vol<=1.35 and (not finite(atravg) or atrp<=atravg*1.12); delivery_build=finite(deliv) and finite(d10) and deliv>=max(STRAT.delivery_floor,d10); rsi_recovery=finite(rsi) and 42<=rsi<=65; momentum_turn=finite(mh3) and mh3>0; ema_turn=finite(slope20) and slope20>-0.15 and (not finite(slope50) or slope50>-0.20); alignment=finite(ema20) and finite(ema50) and ema20>=ema50*.985; not_extended=(not finite(ret5) or ret5<=STRAT.max_entry_extension_pct) and (not finite(ret20) or ret20<=20); candle_demand=(finite(close_loc) and close_loc>=.60) or (finite(lower_wick) and lower_wick>=.35); volume_ok=finite(vol) and .65<=vol<=2.8
    score=0;reasons=[]
    def add(ok,pts,msg):
        nonlocal score
        if bool(ok):score+=pts;reasons.append(msg)
    add(bottom_hold,12,'Low holding');
    if not no_lower_low:score-=18;reasons.append('Lower-low risk')
    add(exhaustion,8,'Selling exhaustion');add(hh_idx is not None,14,'First HH');add(hl_idx is not None,24,'Higher Low');add(second_hh,12,'Second HH');add(delivery_build,7,'Delivery stable/improving');add(momentum_turn,5,'Momentum turning');add(rsi_recovery,4,'RSI recovery');add(ema_turn,5,'EMA slope improving');add(alignment,3,'EMA20/50 stabilised');add(candle_demand,3,'Demand candle');add(volume_ok,2,'Healthy liquidity');add(not_extended,4,'Not extended');add(finite(atrp) and finite(atravg) and atrp<atravg*.95,3,'ATR compression')
    if finite(adx) and adx>=18:add(True,2,'Trend strength building')
    if res_dist<2.0:score-=8;reasons.append('Resistance too close')
    if not not_extended:score-=15;reasons.append('Extended')
    if finite(atrp) and atrp>STRAT.max_atr_pct:score-=8;reasons.append('ATR too high')
    score=max(0,min(100,int(round(score)))); stage='EARLY TREND' if second_hh else 'HIGHER-LOW HUNTER' if hl_idx is not None else 'FIRST REVERSAL' if hh_idx is not None else 'BOTTOM FORMING' if bottom_hold else 'WATCH'
    atr=float(x.get('ATR14',cur*.03)) if finite(x.get('ATR14',np.nan)) else cur*.03
    # Structural stop: below higher-low / recent low, never above entry.
    anchor=hl if finite(hl) else low; stop=anchor-1.15*atr; stop=min(stop,cur*(1-0.01)); stop=max(stop,cur*(1-STRAT.max_stop_pct/100)); risk=cur-stop
    if risk<=0:stop=cur*(1-STRAT.max_stop_pct/100);risk=cur-stop
    # Entry trigger is a break of the actual setup high, not an arbitrary resistance value.
    setup_high=hh2 if finite(hh2) and hh2>cur else hh if finite(hh) and hh>cur else resistance
    trigger=max(cur*1.003,setup_high*1.003)
    if trigger>resistance*1.01:trigger=resistance*1.003
    zone_low=max(anchor*.997,cur*.985);zone_high=min(cur*1.02,trigger)
    # Targets are risk multiples first; resistance can cap a target, never create absurd upside.
    raw_t1=cur+risk*STRAT.min_rr1; raw_t2=cur+risk*STRAT.min_rr2; raw_t3=cur+risk*STRAT.min_rr3
    t1=raw_t1; t2=raw_t2; t3=raw_t3
    if resistance>cur and resistance<raw_t1*1.02:t1=resistance*.995
    if t1<=cur+risk*1.2:t1=cur+risk*STRAT.min_rr1
    if t2<=t1:t2=max(raw_t2,t1+risk*.5)
    if t3<=t2:t3=max(raw_t3,t2+risk*.5)
    high52=x.get('HIGH_52W',np.nan)
    if finite(high52) and high52>cur and high52<t3:t3=high52*.995
    rr1=(t1-cur)/risk;rr2=(t2-cur)/risk;rr3=(t3-cur)/risk;threshold=STRAT.min_score if min_score is None else min_score
    # BUY requires confirmed structure. First reversal is only a trigger candidate; bottom forming is never BUY.
    if second_hh and score>=STRAT.strong_score and not_extended:action='BUY'
    elif hl_idx is not None and score>=threshold and cur<=zone_high and res_dist>=2.0 and rr1>=STRAT.min_rr1:action='BUY'
    elif hh_idx is not None and score>=threshold and res_dist>=2.0:action='BUY ON TRIGGER'
    else:action='WATCH'
    structure='LOW → HH → HL → HH' if second_hh else 'LOW → HH → HL' if hl_idx is not None else 'LOW → HH' if hh_idx is not None else 'LOW HOLD' if bottom_hold else 'UNCONFIRMED'
    def rv(v,d=2):return round(v,d) if finite(v) else ''
    return {'SYMBOL':str(x.SYMBOL),'DATE':pd.Timestamp(x.DATE).strftime('%d-%b-%Y'),'CMP':rv(cur),'ACTION':action,'STAGE':stage,'HUNTER_SCORE':score,'STRUCTURE':structure,'RECENT_LOW':rv(low),'LOW_DISTANCE_PCT':rv(low_dist),'FIRST_HH':rv(hh),'HIGHER_LOW':rv(hl),'SECOND_HH':rv(hh2),'BUY_ZONE_LOW':rv(zone_low),'BUY_ZONE_HIGH':rv(zone_high),'ENTRY_TRIGGER':rv(trigger),'STOP_LOSS':rv(stop),'TARGET_1':rv(t1),'TARGET_2':rv(t2),'TARGET_3':rv(t3),'RR_T1':rv(rr1),'RR_T2':rv(rr2),'RR_T3':rv(rr3),'RESISTANCE':rv(resistance),'RESISTANCE_DISTANCE_PCT':rv(res_dist),'EMA20':rv(ema20),'EMA50':rv(ema50),'EMA100':rv(ema100),'EMA200':rv(ema200),'RSI14':rv(rsi),'MACD':rv(x.get('MACD',np.nan),4),'MACD_SIGNAL':rv(x.get('MACD_SIGNAL',np.nan),4),'MACD_HIST':rv(x.get('MACD_HIST',np.nan),4),'ADX14':rv(adx),'ATR_PCT':rv(atrp),'ATR_COMPRESSION':'YES' if finite(atrp) and finite(atravg) and atrp<atravg*.95 else 'NO','VOLUME_RATIO':rv(vol),'DELIVERY_PCT':rv(deliv),'DELIVERY_AVG10':rv(d10),'RET_5D_PCT':rv(ret5),'RET_20D_PCT':rv(ret20),'DIST_52W_HIGH_PCT':rv(x.get('DIST_52W_HIGH_PCT',np.nan)),'DIST_EMA200_PCT':rv(x.get('DIST_EMA200_PCT',np.nan)),'REASONS':', '.join(reasons)}

def scan_all(hist,min_score=None):
    rows=[]
    for sym,g in hist.groupby('SYMBOL'):
        try:
            r=analyze_stock(g,min_score)
            if r and r['HUNTER_SCORE']>=(STRAT.min_score if min_score is None else min_score):rows.append(r)
        except Exception as e:print('Strategy error',sym,e)
    out=pd.DataFrame(rows)
    if out.empty:return out
    order={'BUY':0,'BUY ON TRIGGER':1,'WATCH':2};out['_o']=out.ACTION.map(order).fillna(9);out=out.sort_values(['_o','HUNTER_SCORE','RESISTANCE_DISTANCE_PCT'],ascending=[True,False,True]).drop(columns='_o');out.insert(0,'RANK',range(1,len(out)+1));return out

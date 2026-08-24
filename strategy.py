from __future__ import annotations
import numpy as np,pandas as pd
from config import STRAT

def finite(x):
    try:return np.isfinite(float(x))
    except:return False

def analyze_stock(g,min_score=None):
    g=g.sort_values('DATE').reset_index(drop=True)
    if len(g)<STRAT.min_history:return None
    w=g.tail(min(180,len(g))).reset_index(drop=True)
    c=pd.to_numeric(w.CLOSE_PRICE,errors='coerce').to_numpy(dtype=float); n=len(c); cur=float(c[-1]); x=w.iloc[-1]
    if not finite(cur) or cur<=0:return None

    lookback=min(70,n-1); start=max(0,n-lookback); seg=c[start:]
    low_idx=start+int(np.nanargmin(seg)); low=float(c[low_idx])
    prior_start=max(0,low_idx-25); prior=c[prior_start:low_idx]
    prior_high=float(np.nanmax(prior)) if len(prior) else np.nan
    hh_idx=None; hh=np.nan
    if finite(prior_high):
        for i in range(low_idx+1,n):
            if c[i]>prior_high*1.003:hh_idx=i;hh=float(c[i]);break

    hl_idx=None;hl=np.nan;base_days=0
    if hh_idx is not None and hh_idx+2<n:
        post=c[hh_idx+1:];j=hh_idx+1+int(np.nanargmin(post));candidate=float(c[j])
        if candidate>low*1.01 and candidate<=hh*0.995:hl_idx=j;hl=c[j];base_days=n-j-1

    second_hh=False;hh2=np.nan
    if hl_idx is not None and hl_idx+1<n:
        post=c[hl_idx+1:];j=hl_idx+1+int(np.nanargmax(post))
        if c[j]>hh*1.003:second_hh=True;hh2=float(c[j])

    get=lambda k:x.get(k,np.nan)
    rsi=get('RSI14');adx=get('ADX14');vol=get('VOL_RATIO');deliv=get('DELIV_PER');d10=get('DELIV_AVG10');atrp=get('ATR_PCT');atravg=get('ATR_PCT_AVG30')
    mh3=get('MACD_HIST_SLOPE');macdh=get('MACD_HIST');ema20=get('EMA20');ema50=get('EMA50');ema100=get('EMA100');ema200=get('EMA200')
    slope20=get('EMA20_SLOPE_5');slope50=get('EMA50_SLOPE_5');ret5=get('RET_5D');ret20=get('RET_20D');ret50=get('RET_50D');close_loc=get('CLOSE_LOCATION');lower_wick=get('LOWER_WICK')
    high52=get('HIGH_52W');prior20=get('PRIOR_HIGH20');prior55=get('PRIOR_HIGH55');dist200=get('DIST_EMA200_PCT')

    no_lower_low=cur>=float(np.nanmin(c[-7:-1]))*.998 if n>=7 else True
    low_dist=(cur/low-1)*100 if low>0 else 999
    from_52=(cur/high52-1)*100 if finite(high52) and high52>0 else 0
    ret20_local=(c[-1]/c[-21]-1)*100 if n>=21 and c[-21]>0 else np.nan
    ret50_local=(c[-1]/c[-51]-1)*100 if n>=51 and c[-51]>0 else np.nan
    bottom_hold=low_dist<=16 and no_lower_low
    exhaustion=(finite(vol) and vol<=1.45) and ((not finite(atravg)) or atrp<=atravg*1.15)
    deep_fall=(ret20_local<=STRAT.max_fall_20d_pct if finite(ret20_local) else False) or (ret50_local<=STRAT.max_fall_50d_pct if finite(ret50_local) else False) or (from_52<=STRAT.max_52w_high_distance_pct if finite(from_52) else False)
    recovery=(finite(ret5) and ret5>=STRAT.min_recovery_5d_pct) and no_lower_low
    delivery_build=finite(deliv) and finite(d10) and deliv>=max(STRAT.delivery_floor,d10*.92)
    rsi_recovery=finite(rsi) and 42<=rsi<=68
    momentum_turn=finite(mh3) and mh3>0 and (not finite(macdh) or macdh>-0.5)
    ema_turn=finite(slope20) and slope20>-0.20 and (not finite(slope50) or slope50>-0.25)
    alignment=finite(ema20) and finite(ema50) and ema20>=ema50*.975
    not_extended=(not finite(ret5) or ret5<=STRAT.max_entry_extension_pct) and (not finite(ret20) or ret20<=22)
    demand=(finite(close_loc) and close_loc>=.60) or (finite(lower_wick) and lower_wick>=.30)
    healthy_volume=finite(vol) and .60<=vol<=3.0
    rs_improving=(not STRAT.require_rs_improving) or (finite(ret5) and finite(ret20) and ret5>=ret20-2.0)
    resistance=max([v for v in [prior20,prior55,hh] if finite(v) and v>cur*1.005] or [cur*1.05]);res_dist=(resistance/cur-1)*100
    breakout_volume=finite(vol) and vol>=STRAT.volume_breakout_ratio

    score=0;reasons=[]
    def add(ok,pts,msg):
        nonlocal score
        if bool(ok):score+=pts;reasons.append(msg)
    add(deep_fall,10,'Deep-fall candidate')
    add(bottom_hold,12,'Low holding')
    if not no_lower_low:score-=16;reasons.append('Lower-low risk')
    add(exhaustion,8,'Selling exhaustion');add(recovery,5,'Recovery started')
    add(hh_idx is not None,14,'First HH');add(hl_idx is not None,24,'Higher Low');add(second_hh,12,'Second HH');add(base_days>=STRAT.min_base_days,5,'Base holding')
    add(delivery_build,6,'Delivery stable/improving');add(momentum_turn,6,'Momentum turning');add(rsi_recovery,5,'RSI recovery');add(ema_turn,5,'EMA slope improving');add(alignment,3,'EMA20/50 stabilised');add(demand,3,'Demand candle');add(healthy_volume,2,'Healthy liquidity');add(not_extended,5,'Not extended');add(finite(atrp) and finite(atravg) and atrp<atravg*.97,3,'ATR compression')
    if finite(adx) and adx>=18:add(True,2,'Trend strength building')
    if breakout_volume:add(True,4,'Breakout volume')
    if not rs_improving:score-=6;reasons.append('Relative strength weak')
    if res_dist<STRAT.min_resistance_distance_pct:score-=8;reasons.append('Resistance too close')
    if not not_extended:score-=12;reasons.append('Extended')
    if finite(atrp) and atrp>STRAT.max_atr_pct:score-=8;reasons.append('ATR too high')
    score=max(0,min(100,int(round(score))))

    stage='CONFIRMED BREAKOUT' if second_hh and breakout_volume else 'PRE-BREAKOUT' if hl_idx is not None else 'FIRST REVERSAL' if hh_idx is not None else 'BOTTOM FORMING' if bottom_hold else 'WATCH'
    atr=float(get('ATR14')) if finite(get('ATR14')) else cur*.03;anchor=float(hl if finite(hl) else low);raw_stop=anchor-1.0*atr
    stop=max(raw_stop,cur*(1-STRAT.max_stop_pct/100));stop=min(stop,cur*(1-STRAT.min_stop_pct/100));risk=cur-stop
    if risk<=0:stop=cur*(1-STRAT.min_stop_pct/100);risk=cur-stop
    setup_high=hh2 if finite(hh2) and hh2>cur else hh if finite(hh) and hh>cur else resistance
    trigger=max(cur*1.002,setup_high*1.002)
    if trigger>resistance*1.01:trigger=resistance*1.003
    zone_low=max(anchor*.997,cur*.985);zone_high=min(cur*1.02,trigger)
    t1=cur+risk*STRAT.min_rr1;t2=cur+risk*STRAT.min_rr2;t3=cur+risk*STRAT.min_rr3
    if resistance>cur and resistance<t1*1.03:t1=max(cur+risk*STRAT.min_rr1,resistance*.995)
    if t2<=t1:t2=t1+risk*.6
    if t3<=t2:t3=t2+risk*.7
    if finite(high52) and high52>cur and high52<t3:t3=high52*.995
    rr1=(t1-cur)/risk;rr2=(t2-cur)/risk;rr3=(t3-cur)/risk

    threshold=STRAT.min_score if min_score is None else min_score;buy_gate=max(STRAT.buy_score,threshold);eligible=score>=buy_gate
    risk_ok=finite(risk) and risk/cur*100>=STRAT.min_stop_pct and risk/cur*100<=STRAT.max_stop_pct
    structural_buy=(hl_idx is not None and base_days>=STRAT.min_base_days)
    momentum_ok=rsi_recovery and momentum_turn and ema_turn and rs_improving
    location_ok=res_dist>=STRAT.min_resistance_distance_pct and not_extended and low_dist<=16
    deep_buy_ok=deep_fall and recovery
    if eligible and structural_buy and momentum_ok and location_ok and risk_ok and second_hh and breakout_volume and score>=STRAT.strong_score:action='BUY'
    elif eligible and structural_buy and momentum_ok and location_ok and risk_ok and deep_buy_ok:action='BUY ON TRIGGER'
    elif score>=threshold:action='WATCH'
    else:action='WATCH'
    structure='LOW → HH → HL → HH' if second_hh else 'LOW → HH → HL' if hl_idx is not None else 'LOW → HH' if hh_idx is not None else 'LOW HOLD' if bottom_hold else 'UNCONFIRMED'
    def rv(v,d=2):return round(float(v),d) if finite(v) else ''
    return {'SYMBOL':str(x.SYMBOL),'DATE':pd.Timestamp(x.DATE).strftime('%d-%b-%Y'),'CMP':rv(cur),'ACTION':action,'STAGE':stage,'HUNTER_SCORE':score,'STRUCTURE':structure,'RECENT_LOW':rv(low),'LOW_DISTANCE_PCT':rv(low_dist),'FIRST_HH':rv(hh),'HIGHER_LOW':rv(hl),'SECOND_HH':rv(hh2),'BUY_ZONE_LOW':rv(zone_low),'BUY_ZONE_HIGH':rv(zone_high),'ENTRY_TRIGGER':rv(trigger),'STOP_LOSS':rv(stop),'TARGET_1':rv(t1),'TARGET_2':rv(t2),'TARGET_3':rv(t3),'RR_T1':rv(rr1),'RR_T2':rv(rr2),'RR_T3':rv(rr3),'RESISTANCE':rv(resistance),'RESISTANCE_DISTANCE_PCT':rv(res_dist),'EMA20':rv(ema20),'EMA50':rv(ema50),'EMA100':rv(ema100),'EMA200':rv(ema200),'RSI14':rv(rsi),'MACD':rv(get('MACD'),4),'MACD_SIGNAL':rv(get('MACD_SIGNAL'),4),'MACD_HIST':rv(macdh,4),'ADX14':rv(adx),'ATR_PCT':rv(atrp),'ATR_COMPRESSION':'YES' if finite(atrp) and finite(atravg) and atrp<atravg*.97 else 'NO','VOLUME_RATIO':rv(vol),'DELIVERY_PCT':rv(deliv),'DELIVERY_AVG10':rv(d10),'RET_5D_PCT':rv(ret5),'RET_20D_PCT':rv(ret20),'DIST_52W_HIGH_PCT':rv(from_52),'DIST_EMA200_PCT':rv(dist200),'REASONS':', '.join(reasons)}

def scan_all(hist,min_score=None):
    threshold=STRAT.min_score if min_score is None else min_score;rows=[]
    for sym,g in hist.groupby('SYMBOL'):
        try:
            r=analyze_stock(g,threshold)
            if r and r['HUNTER_SCORE']>=threshold:rows.append(r)
        except Exception as e:print('Strategy error',sym,e)
    out=pd.DataFrame(rows)
    if out.empty:return out
    order={'BUY':0,'BUY ON TRIGGER':1,'WATCH':2};out['_o']=out.ACTION.map(order).fillna(9)
    out=out.sort_values(['_o','HUNTER_SCORE','RESISTANCE_DISTANCE_PCT'],ascending=[True,False,True]).drop(columns='_o')
    out.insert(0,'RANK',range(1,len(out)+1));return out

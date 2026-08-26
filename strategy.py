from __future__ import annotations
import math
import numpy as np
import pandas as pd
from config import STRAT

ACTIONABLE={'PRE-BREAKOUT BUY','BREAKOUT BUY','SWING BUY'}
BUY_ACTIONS=ACTIONABLE
MIN_HISTORY=STRAT.min_history


def _f(v, default=np.nan):
    try:
        x=float(v)
        return x if np.isfinite(x) else default
    except Exception:
        return default


def _num(g,c):
    return pd.to_numeric(g[c],errors='coerce') if c in g.columns else pd.Series(np.nan,index=g.index,dtype=float)


def _pct(a,b):
    a,b=_f(a),_f(b)
    return (a/b-1)*100 if np.isfinite(a) and np.isfinite(b) and b else np.nan


def market_context(hist):
    d=hist[hist.DATE.eq(hist.DATE.max())]
    if d.empty:return {'score':5,'regime':'NEUTRAL','breadth':np.nan}
    c,e20,e50=_num(d,'CLOSE_PRICE'),_num(d,'EMA20'),_num(d,'EMA50');ok=c.notna()&e20.notna()&e50.notna()
    breadth=float((c[ok]>e20[ok]).mean()*100) if ok.any() else 50.0
    trend=float((e20[ok]>e50[ok]).mean()*100) if ok.any() else 50.0
    if breadth>=70 and trend>=65:return {'score':10,'regime':'STRONG BULLISH','breadth':breadth}
    if breadth>=55 and trend>=50:return {'score':8,'regime':'BULLISH','breadth':breadth}
    if breadth<=30 and trend<=35:return {'score':2,'regime':'BEARISH','breadth':breadth}
    if breadth<=45 and trend<=45:return {'score':4,'regime':'WEAK','breadth':breadth}
    return {'score':6,'regime':'NEUTRAL','breadth':breadth}


def _higher_low(g,i):
    l=_num(g,'LOW_PRICE')
    if i<8:return False
    a,b,c=_f(l.iloc[i-2]),_f(l.iloc[i-5]),_f(l.iloc[i-8])
    return all(np.isfinite(x) for x in (a,b,c)) and a>b>=c


def _resistance_tests(g,i,res):
    if not np.isfinite(res) or i<10:return 0
    h=_num(g,'HIGH_PRICE');tol=STRAT.resistance_test_tolerance_pct/100;tests=0;last=-99
    for j in range(max(0,i-60),i):
        hv=_f(h.iloc[j])
        if np.isfinite(hv) and abs(hv/res-1)<=tol and j-last>=3:
            tests+=1;last=j
    return tests


def _features(g,i,market):
    g=g.sort_values('DATE').reset_index(drop=True);r=g.iloc[i]
    c,h,l,v=_num(g,'CLOSE_PRICE'),_num(g,'HIGH_PRICE'),_num(g,'LOW_PRICE'),_num(g,'TTL_TRD_QNTY').fillna(0)
    close,high,low=_f(r.get('CLOSE_PRICE')),_f(r.get('HIGH_PRICE')),_f(r.get('LOW_PRICE'))
    e20,e50,e100,e200=[_f(r.get(x)) for x in ('EMA20','EMA50','EMA100','EMA200')]
    atr,atr_pct,atr_avg=_f(r.get('ATR14')),_f(r.get('ATR_PCT')),_f(r.get('ATR_PCT_AVG30'))
    vol,deliv,d10,d20=_f(r.get('VOL_RATIO')),_f(r.get('DELIV_PER')),_f(r.get('DELIV_AVG10')),_f(r.get('DELIV_AVG20'))
    rsi,adx,rs=_f(r.get('RSI14')),_f(r.get('ADX14')),_f(r.get('RS_VS_UNIVERSE'))
    prior20=_f(r.get('PRIOR_HIGH20'));low20=_f(r.get('PRIOR_LOW20'))
    if not np.isfinite(prior20) and i>=20:prior20=_f(h.iloc[i-20:i].max())
    if not np.isfinite(low20) and i>=20:low20=_f(l.iloc[i-20:i].min())
    e20p=_f(g.EMA20.iloc[i-5]) if i>=5 and 'EMA20' in g else np.nan;e50p=_f(g.EMA50.iloc[i-5]) if i>=5 and 'EMA50' in g else np.nan
    trend_ready=all(np.isfinite(x) for x in (close,e20,e50,e100)) and close>e50 and e20>e50 and e50>=e100*.995
    trend_strong=all(np.isfinite(x) for x in (close,e20,e50,e100,e200,e20p,e50p)) and close>e20>e50>e100>e200 and e20>e20p and e50>e50p
    atr_compress=np.isfinite(atr_pct) and np.isfinite(atr_avg) and atr_pct<=atr_avg*.92
    mid=c.rolling(20,min_periods=20).mean();std=c.rolling(20,min_periods=20).std(ddof=0);bbw=4*std/mid.replace(0,np.nan)*100
    bb_now=_f(bbw.iloc[i]);bb_prev=_f(bbw.iloc[i-5]) if i>=5 else np.nan;bb_compress=np.isfinite(bb_now) and np.isfinite(bb_prev) and bb_now<=bb_prev*.90
    start=max(0,i-STRAT.min_base_days+1);base_range=((h.iloc[start:i+1].max()-l.iloc[start:i+1].min())/close*100) if np.isfinite(close) else np.nan;range_tight=np.isfinite(base_range) and base_range<=STRAT.max_base_range_pct
    old_start=max(0,i-STRAT.min_base_days*2+1);old_end=max(old_start+1,i-STRAT.min_base_days+1);old_range=((h.iloc[old_start:old_end].max()-l.iloc[old_start:old_end].min())/close*100) if np.isfinite(close) else np.nan;base_tightening=np.isfinite(old_range) and np.isfinite(base_range) and base_range<=old_range*(1-STRAT.min_base_tightening_pct/100)
    compression=(int(atr_compress)+int(bb_compress)+int(range_tight))>=2
    obv=(np.sign(c.diff()).fillna(0)*v).cumsum();obv_rising=i>=20 and _f(obv.iloc[i])>_f(obv.iloc[i-20])
    up=v.where(c.diff()>0,0).rolling(10,min_periods=7).mean();dn=v.where(c.diff()<0,0).rolling(10,min_periods=7).mean();volume_acc=np.isfinite(_f(up.iloc[i])) and np.isfinite(_f(dn.iloc[i])) and _f(up.iloc[i])>_f(dn.iloc[i])
    shortv=_f(v.iloc[i-4:i+1].mean()) if i>=4 else np.nan;basev=_f(v.iloc[i-24:i-4].mean()) if i>=24 else np.nan;dry_ratio=shortv/basev if np.isfinite(shortv) and np.isfinite(basev) and basev else np.nan;dryup=np.isfinite(dry_ratio) and STRAT.min_volume_dryup_ratio<=dry_ratio<=STRAT.max_volume_dryup_ratio;volume_expansion=np.isfinite(vol) and vol>=STRAT.volume_breakout_ratio
    accumulation=obv_rising and (volume_acc or dryup)
    delivery_good=np.isfinite(deliv) and deliv>=STRAT.delivery_floor;delivery_improving=np.isfinite(d10) and np.isfinite(d20) and d10>d20;delivery_ok=delivery_good and delivery_improving
    rs_positive=np.isfinite(rs) and rs>=STRAT.min_rs_spread_pct;rs_strong=np.isfinite(rs) and rs>=1;rs_improving=i>=5 and 'RS_VS_UNIVERSE' in g and np.isfinite(_f(g.RS_VS_UNIVERSE.iloc[i-5])) and rs>_f(g.RS_VS_UNIVERSE.iloc[i-5])
    distance=((prior20-close)/close*100) if np.isfinite(prior20) and close else np.nan;near_res=np.isfinite(distance) and 0<=distance<=STRAT.max_resistance_distance_pct;tests=_resistance_tests(g,i,prior20);higher_low=_higher_low(g,i);confirmed=np.isfinite(prior20) and close>=prior20*1.002
    extension=_pct(close,e20);ret5=_f(r.get('RET_5D'));ret20=_f(r.get('RET_20D'));not_extended=(not np.isfinite(extension) or extension<=STRAT.max_entry_extension_pct) and (not np.isfinite(ret20) or ret20<=15) and (not np.isfinite(rsi) or rsi<=78);momentum_ok=(not np.isfinite(rsi) or 50<=rsi<=72) and (not np.isfinite(ret5) or ret5>=STRAT.min_recovery_5d_pct)
    close_strength=((close-low)/(high-low)) if np.isfinite(high) and np.isfinite(low) and high>low else np.nan;breakout_candle=confirmed and np.isfinite(close_strength) and close_strength>=STRAT.breakout_min_close_strength;breakout_extension=(not np.isfinite(extension) or extension<=STRAT.max_breakout_extension_pct)
    sector_strength='UNAVAILABLE';sector_ok=True
    if 'SECTOR' in g.columns:
        sec=str(r.get('SECTOR',''));sg=g[g.SECTOR.astype(str).eq(sec)]
        if len(sg)>=20:
            sr=_f(sg.RET_20D.iloc[-1]);sector_strength='POSITIVE' if np.isfinite(sr) and sr>0 else 'WEAK';sector_ok=sector_strength=='POSITIVE'
    pre=15*int(near_res)+10*int(tests>=STRAT.min_resistance_tests)+10*int(higher_low)+10*int(compression and (base_tightening or range_tight))+15*int(delivery_ok)+10*int(obv_rising)+8*int(volume_acc)+7*int(rs_strong)+8*int(trend_strong)+7*int(not_extended)
    breakout=20*int(confirmed)+20*int(volume_expansion)+15*int(delivery_good)+15*int(trend_ready)+10*int(rs_positive)+10*int(breakout_candle)+10*int(breakout_extension)
    pullback=((np.isfinite(ret5) and -8<=ret5<=2) or (np.isfinite(extension) and extension<=2.5));swing=25*int(trend_strong)+20*int(pullback)+15*int(rs_positive)+15*int(accumulation)+10*int(delivery_good)+15*int(not_extended)
    pre=min(100,pre);breakout=min(100,breakout);swing=min(100,swing)
    trigger=prior20*1.003 if np.isfinite(prior20) else np.nan
    pre_zone_low=prior20*.985 if np.isfinite(prior20) else close*.99;pre_zone_high=prior20*.997 if np.isfinite(prior20) else close
    break_zone_low=trigger if np.isfinite(trigger) else close;break_zone_high=(trigger+min(.5*atr,trigger*.02)) if np.isfinite(trigger) and np.isfinite(atr) else close*1.01
    swing_zone_low=close*.985;swing_zone_high=close*1.005
    stop=close-1.5*atr if np.isfinite(close) and np.isfinite(atr) and atr>0 else np.nan
    if np.isfinite(low20) and np.isfinite(stop):stop=max(stop,low20*.985)
    risk=close-stop if np.isfinite(close) and np.isfinite(stop) else np.nan;risk_pct=risk/close*100 if np.isfinite(risk) and close else np.nan;valid_risk=np.isfinite(risk_pct) and STRAT.min_stop_pct<=risk_pct<=STRAT.max_stop_pct
    t1=close+risk*STRAT.min_rr1 if np.isfinite(risk) and risk>0 else np.nan;t2=close+risk*STRAT.min_rr2 if np.isfinite(risk) and risk>0 else np.nan;t3=close+risk*STRAT.min_rr3 if np.isfinite(risk) and risk>0 else np.nan
    pre_entry=(not confirmed) and np.isfinite(close) and pre_zone_low<=close<=pre_zone_high
    break_entry=confirmed and np.isfinite(close) and close<=break_zone_high
    swing_entry=np.isfinite(close) and swing_zone_low<=close<=swing_zone_high
    pre_gate=(not confirmed and pre>=STRAT.buy_score and pre_entry and near_res and tests>=STRAT.min_resistance_tests and higher_low and compression and delivery_ok and accumulation and trend_ready and rs_positive and rs_improving and momentum_ok and not_extended and np.isfinite(adx) and adx>=STRAT.min_adx and market.get('score',5)>=STRAT.min_regime_score and sector_ok and (dryup or not STRAT.require_volume_dryup) and valid_risk)
    breakout_gate=(confirmed and breakout>=STRAT.buy_score and break_entry and volume_expansion and delivery_good and trend_ready and rs_positive and breakout_candle and breakout_extension and not_extended and market.get('score',5)>=STRAT.min_regime_score and sector_ok and valid_risk)
    swing_gate=(not confirmed and swing>=STRAT.buy_score and swing_entry and trend_strong and rs_positive and rs_improving and accumulation and delivery_good and pullback and not_extended and market.get('score',5)>=STRAT.min_regime_score and sector_ok and valid_risk and not pre_gate)
    if pre_gate:action='PRE-BREAKOUT BUY';entry_zone=(pre_zone_low,pre_zone_high);max_buy=pre_zone_high
    elif breakout_gate:action='BREAKOUT BUY';entry_zone=(break_zone_low,break_zone_high);max_buy=break_zone_high
    elif swing_gate:action='SWING BUY';entry_zone=(swing_zone_low,swing_zone_high);max_buy=swing_zone_high
    elif confirmed:action='AVOID / CHASE';entry_zone=(break_zone_low,break_zone_high);max_buy=break_zone_high
    else:action='WATCH';entry_zone=(pre_zone_low,pre_zone_high);max_buy=pre_zone_high
    reasons=[]
    for ok,msg in [(trend_strong,'Strong trend'),(trend_ready,'Trend aligned'),(higher_low,'Higher-low'),(tests>=STRAT.min_resistance_tests,f'{tests} resistance tests'),(compression,'Compression'),(base_tightening,'Base tightening'),(dryup,'Volume dry-up'),(volume_expansion,'Volume expansion'),(accumulation,'Accumulation'),(delivery_ok,'Delivery improving'),(rs_strong,'Strong RS'),(rs_improving,'RS improving'),(sector_ok,'Sector supportive'),(confirmed,'Breakout confirmed'),(not_extended,'Not extended'),(valid_risk,'Risk within limit'),(pre_entry,'Pre-breakout entry zone'),(break_entry,'Breakout entry zone'),(swing_entry,'Swing entry zone')]:
        if ok:reasons.append(msg)
    return locals()


def _probability(g,action,score):
    table=g.attrs.get('BREAKOUT_EVENT_RATE_BY_SCORE')
    if not table or action not in ACTIONABLE:return ''
    try:
        for x in table:
            if x.get('ACTION')==action and x.get('SAMPLES',0)>=30 and x.get('LOW',-1)<=score<=x.get('HIGH',101):return round(float(x.get('RATE')),1)
    except Exception:pass
    return ''


def analyze_stock(g,min_score=None,market=None):
    g=g.sort_values('DATE').reset_index(drop=True)
    if len(g)<MIN_HISTORY:return None
    market=market or market_context(g);f=_features(g,len(g)-1,market);r=g.iloc[-1]
    def rv(x):
        x=_f(x);return round(x,2) if np.isfinite(x) else ''
    close=f['close'];qty=_f(r.get('DELIV_QTY'));delivery_value=close*qty if np.isfinite(close) and np.isfinite(qty) else np.nan;action=f['action'];category={'PRE-BREAKOUT BUY':'PRE-BREAKOUT','BREAKOUT BUY':'BREAKOUT','SWING BUY':'SWING','AVOID / CHASE':'AVOID'}.get(action,'WATCH')
    setup={'PRE-BREAKOUT BUY':f['pre'],'BREAKOUT BUY':f['breakout'],'SWING BUY':f['swing']}.get(action,max(f['pre'],f['breakout'],f['swing']))
    timing=100 if ((action=='PRE-BREAKOUT BUY' and f['pre_entry']) or (action=='BREAKOUT BUY' and f['break_entry']) or (action=='SWING BUY' and f['swing_entry'])) else 30
    confirm=100 if action=='BREAKOUT BUY' and f['breakout_candle'] and f['volume_expansion'] else 80 if action in {'PRE-BREAKOUT BUY','SWING BUY'} else 40
    final=int(round(min(99,max(0,.45*setup+.20*timing+.15*confirm+.10*(100 if f['delivery_ok'] else 45)+.05*(100 if f['rs_positive'] else 35)+.05*market.get('score',5)*10))))
    rr=(f['t1']-close)/f['risk'] if np.isfinite(f['risk']) and f['risk']>0 else np.nan
    return {'SYMBOL':str(r.SYMBOL),'DATE':pd.Timestamp(r.DATE).strftime('%d-%b-%Y'),'CMP':rv(close),'ACTION':action,'CATEGORY':category,'NEXT_DAY_ACTION':'BUY' if action in BUY_ACTIONS else 'WATCH','BUY_DATE':(pd.Timestamp(r.DATE)+pd.tseries.offsets.BDay(1)).strftime('%d-%b-%Y'),'STAGE':action,'PRE_BREAKOUT_SCORE':f['pre'],'BREAKOUT_SCORE':f['breakout'],'SWING_SCORE':f['swing'],'HUNTER_SCORE':final,'FINAL_TRADE_SCORE':final,'NEXT_DAY_SETUP_SCORE':setup,'MODEL_CONFIDENCE':final,'BREAKOUT_PROBABILITY':_probability(g,action,setup),'MARKET_REGIME':market.get('regime','NEUTRAL'),'MARKET_BREADTH':rv(market.get('breadth')),'TREND':'STRONG BULLISH' if f['trend_strong'] else 'ALIGNED' if f['trend_ready'] else 'WEAK','ACCUMULATION':'STRONG' if f['accumulation'] else 'WEAK','DELIVERY':'STRONG + IMPROVING' if f['delivery_ok'] else 'GOOD' if f['delivery_good'] else 'WEAK','DELIVERY_PCT':rv(f['deliv']),'DELIVERY_VALUE':rv(delivery_value),'VOLUME_RATIO':rv(f['vol']),'VOLUME_DRYUP':'YES' if f['dryup'] else 'NO','VOLUME_EXPANSION':'YES' if f['volume_expansion'] else 'NO','ATR_PCT':rv(f['atr_pct']),'ATR_COMPRESSION':'YES' if f['atr_compress'] else 'NO','BB_WIDTH':'COMPRESSING' if f['bb_compress'] else 'NORMAL','BASE_RANGE_PCT':rv(f['base_range']),'BASE_TIGHTENING':'YES' if f['base_tightening'] else 'NO','RESISTANCE':rv(f['prior20']),'RESISTANCE_DISTANCE_PCT':rv(f['distance']),'RESISTANCE_TESTS':int(f['tests']),'HIGHER_LOW':'YES' if f['higher_low'] else 'NO','RELATIVE_STRENGTH':'STRONG' if f['rs_strong'] else 'POSITIVE' if f['rs_positive'] else 'WEAK','RS_VS_UNIVERSE':rv(f['rs']),'RS_IMPROVING':'YES' if f['rs_improving'] else 'NO','SECTOR_STRENGTH':f['sector_strength'],'BREAKOUT_STATUS':'CONFIRMED' if f['confirmed'] else 'NOT YET BROKEN','ENTRY_PRICE':rv(close),'ENTRY_ZONE':f'{rv(f["entry_zone"][0])} - {rv(f["entry_zone"][1])}','BREAKOUT_TRIGGER':rv(f['trigger']),'MAX_BUY_PRICE':rv(f['max_buy']),'STOP_LOSS':rv(f['stop']),'TARGET_1':rv(f['t1']),'TARGET_2':rv(f['t2']),'TARGET_3':rv(f['t3']),'RISK_PCT':rv(f['risk_pct']),'RISK_REWARD_T1':rv(rr),'ENTRY_STATUS':'BUYABLE' if action in BUY_ACTIONS else 'WAIT','RELEASE_BLOCK_REASON':'' if action in BUY_ACTIONS else ('CHASE' if action=='AVOID / CHASE' else 'SETUP_NOT_READY'),'REASONS':' | '.join(f['reasons']),'QUALITY_GATE':'PENDING'}


def scan_all(hist,min_score=None):
    if hist is None or hist.empty:return pd.DataFrame()
    work=hist.sort_values(['SYMBOL','DATE']);market=market_context(work);rows=[]
    for sym,g in work.groupby('SYMBOL',sort=False):
        if len(g)<MIN_HISTORY:continue
        try:
            sig=analyze_stock(g,min_score,market)
            if sig:rows.append(sig)
        except Exception as exc:print(f'STRATEGY WARNING {sym}: {exc}')
    df=pd.DataFrame(rows)
    if df.empty:return df
    actionable=df[df.ACTION.isin(ACTIONABLE)].copy()
    if actionable.empty:return df.sort_values('HUNTER_SCORE',ascending=False).reset_index(drop=True)
    selected=[];sector_counts={}
    for _,row in actionable.sort_values(['HUNTER_SCORE','NEXT_DAY_SETUP_SCORE'],ascending=False).iterrows():
        sec=str(row.get('SECTOR_STRENGTH','UNAVAILABLE'))
        if sector_counts.get(sec,0)>=STRAT.max_sector_buy_count:continue
        selected.append(row);sector_counts[sec]=sector_counts.get(sec,0)+1
        if len(selected)>=5:break
    selected_df=pd.DataFrame(selected)
    excluded=set(selected_df.SYMBOL) if not selected_df.empty else set()
    rest=df[~df.SYMBOL.isin(excluded)].copy()
    return pd.concat([selected_df,rest],ignore_index=True)

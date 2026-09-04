from __future__ import annotations
import numpy as np
import pandas as pd
from config import STRAT, NIFTY_SYMBOL, APEX

ACTIONABLE={'PRE-BREAKOUT BUY','BREAKOUT BUY','SWING BUY'}
BUY_ACTIONS=ACTIONABLE
MIN_HISTORY=STRAT.min_history

def _f(v,default=np.nan):
    try:
        x=float(v); return x if np.isfinite(x) else default
    except Exception:return default

def _num(g,c):
    if c not in g.columns:return pd.Series(np.nan,index=g.index,dtype=float)
    return pd.to_numeric(g[c],errors='coerce')

def _pct(a,b):
    a,b=_f(a),_f(b)
    return (a/b-1)*100 if np.isfinite(a) and np.isfinite(b) and b else np.nan

def _market_context(hist):
    d=hist[hist.DATE.eq(hist.DATE.max())&hist.SYMBOL.ne(NIFTY_SYMBOL)]
    if d.empty:return {'score':5,'regime':'NEUTRAL','breadth':np.nan}
    c,e20,e50=_num(d,'CLOSE_PRICE'),_num(d,'EMA20'),_num(d,'EMA50');ok=c.notna()&e20.notna()&e50.notna()
    breadth=float((c[ok]>e20[ok]).mean()*100) if ok.any() else np.nan;trend=float((e20[ok]>e50[ok]).mean()*100) if ok.any() else np.nan
    if np.isfinite(breadth) and np.isfinite(trend):
        if breadth>=65 and trend>=60:return {'score':10,'regime':'BULLISH','breadth':breadth}
        if breadth<=35 and trend<=40:return {'score':2,'regime':'BEARISH','breadth':breadth}
    return {'score':6,'regime':'NEUTRAL','breadth':breadth}

def _resistance_tests(g,i,resistance):
    if not np.isfinite(resistance) or i<10:return 0
    h=_num(g,'HIGH_PRICE');tol=STRAT.resistance_test_tolerance_pct/100;tests=0;last=-99
    for j in range(max(0,i-40),i):
        hv=_f(h.iloc[j])
        if np.isfinite(hv) and abs(hv/resistance-1)<=tol and j-last>=3:tests+=1;last=j
    return tests

def _higher_low(g,i):
    l=_num(g,'LOW_PRICE')
    if i<8:return False
    a,b,c=[_f(l.iloc[x]) for x in (i-2,i-5,i-8)]
    return all(np.isfinite(x) for x in (a,b,c)) and a>b>=c

def _features(g,i,market):
    g=g.sort_values('DATE').reset_index(drop=True);r=g.iloc[i]
    c=_num(g,'CLOSE_PRICE');h=_num(g,'HIGH_PRICE');l=_num(g,'LOW_PRICE');v=_num(g,'TTL_TRD_QNTY').fillna(0)
    close,high,low=[_f(r.get(x)) for x in ('CLOSE_PRICE','HIGH_PRICE','LOW_PRICE')]
    e20,e50,e100,e200=[_f(r.get(x)) for x in ('EMA20','EMA50','EMA100','EMA200')]
    atr=_f(r.get('ATR14'));atr_pct=_f(r.get('ATR_PCT'));atr_avg=_f(r.get('ATR_PCT_AVG30'));vol=_f(r.get('VOL_RATIO'));deliv=_f(r.get('DELIV_PER'));d10=_f(r.get('DELIV_AVG10'));d20=_f(r.get('DELIV_AVG20'));rsi=_f(r.get('RSI14'));rs=_f(r.get('RS_VS_UNIVERSE'))
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
    compression=int(atr_compress)+int(bb_compress)+int(range_tight)>=2
    obv=(np.sign(c.diff()).fillna(0)*v).cumsum();obv_rising=i>=20 and _f(obv.iloc[i])>_f(obv.iloc[i-20])
    up=v.where(c.diff()>0,0).rolling(10,min_periods=7).mean();dn=v.where(c.diff()<0,0).rolling(10,min_periods=7).mean();volume_acc=np.isfinite(_f(up.iloc[i])) and np.isfinite(_f(dn.iloc[i])) and _f(up.iloc[i])>_f(dn.iloc[i])
    shortv=_f(v.iloc[i-4:i+1].mean()) if i>=4 else np.nan;basev=_f(v.iloc[i-24:i-4].mean()) if i>=24 else np.nan;dry_ratio=shortv/basev if np.isfinite(shortv) and np.isfinite(basev) and basev else np.nan;dryup=np.isfinite(dry_ratio) and STRAT.min_volume_dryup_ratio<=dry_ratio<=STRAT.max_volume_dryup_ratio;volume_expansion=np.isfinite(vol) and vol>=STRAT.volume_breakout_ratio
    accumulation=obv_rising and (volume_acc or dryup);delivery_good=np.isfinite(deliv) and deliv>=STRAT.delivery_floor;delivery_improving=np.isfinite(d10) and np.isfinite(d20) and d10>d20;delivery_ok=delivery_good and delivery_improving
    rs_positive=np.isfinite(rs) and rs>=STRAT.min_rs_spread_pct;rs_strong=np.isfinite(rs) and rs>=1;rs_improving=i>=5 and 'RS_VS_UNIVERSE' in g and np.isfinite(_f(g.RS_VS_UNIVERSE.iloc[i-5])) and rs>_f(g.RS_VS_UNIVERSE.iloc[i-5])
    distance=((prior20-close)/close*100) if np.isfinite(prior20) and close else np.nan;near_res=np.isfinite(distance) and 0<=distance<=STRAT.max_resistance_distance_pct;tests=_resistance_tests(g,i,prior20);higher_low=_higher_low(g,i);confirmed=np.isfinite(prior20) and close>=prior20*1.002
    extension=_pct(close,e20);ret5=_f(r.get('RET_5D'));not_extended=(not np.isfinite(extension) or extension<=STRAT.max_entry_extension_pct) and (not np.isfinite(ret5) or ret5<=8)
    close_strength=((close-low)/(high-low)) if np.isfinite(high) and np.isfinite(low) and high>low else np.nan;breakout_candle=confirmed and np.isfinite(close_strength) and close_strength>=STRAT.breakout_min_close_strength;breakout_extension=not np.isfinite(extension) or extension<=STRAT.max_breakout_extension_pct
    sector_strength='UNAVAILABLE';sector_ok=True
    if 'SECTOR' in g.columns:
        sector=str(r.get('SECTOR',''));sg=g[g.SECTOR.astype(str).eq(sector)]
        if len(sg)>=20:
            sr=_f(sg.RET_20D.iloc[-1]);sector_strength='POSITIVE' if np.isfinite(sr) and sr>0 else 'WEAK';sector_ok=sector_strength=='POSITIVE'
    pre=int(min(100,15*int(near_res)+10*int(tests>=STRAT.min_resistance_tests)+10*int(higher_low)+10*int(compression and (base_tightening or range_tight))+15*int(delivery_ok)+10*int(obv_rising)+8*int(volume_acc)+7*int(rs_strong)+8*int(trend_strong)+7*int(not_extended)))
    breakout=int(min(100,20*int(confirmed)+20*int(volume_expansion)+15*int(delivery_good)+15*int(trend_ready)+10*int(rs_positive)+10*int(breakout_candle)+10*int(breakout_extension)))
    pullback=(np.isfinite(ret5) and -8<=ret5<=2) or (np.isfinite(extension) and extension<=2.5);swing=int(min(100,(25 if trend_strong else 18 if trend_ready else 0)+(20 if pullback else 0)+(15 if rs_positive else 0)+(15 if accumulation else 0)+(10 if delivery_ok else 0)+(15 if not_extended else 0)))
    pre_gate=(not confirmed and market.get('score',5)>=STRAT.min_regime_score and sector_ok and rs_positive)
    trigger=prior20*1.003 if np.isfinite(prior20) else np.nan;entry=close;stop=close-1.5*atr if np.isfinite(close) and np.isfinite(atr) and atr>0 else np.nan
    if np.isfinite(low20) and np.isfinite(stop):stop=max(stop,low20*.985)
    risk=entry-stop if np.isfinite(entry) and np.isfinite(stop) else np.nan;risk_pct=risk/entry*100 if np.isfinite(risk) and entry else np.nan;valid_risk=np.isfinite(risk_pct) and STRAT.min_stop_pct<=risk_pct<=STRAT.max_stop_pct
    t1=entry+risk*STRAT.min_rr1 if np.isfinite(risk) and risk>0 else np.nan;t2=entry+risk*STRAT.min_rr2 if np.isfinite(risk) and risk>0 else np.nan;t3=entry+risk*STRAT.min_rr3 if np.isfinite(risk) and risk>0 else np.nan
    zone_low=entry*(1-STRAT.max_buy_zone_pct/100);zone_high=entry*(1+STRAT.max_buy_zone_pct/100);max_buy=min(zone_high,trigger*.997 if np.isfinite(trigger) else zone_high)
    pre_buy=pre_gate and pre>=STRAT.buy_score and valid_risk;breakout_buy=confirmed and breakout>=STRAT.buy_score and valid_risk;swing_buy=(not confirmed and swing>=STRAT.buy_score and valid_risk and not pre_buy)
    if pre_buy:action='PRE-BREAKOUT BUY'
    elif breakout_buy:action='BREAKOUT BUY'
    elif swing_buy:action='SWING BUY'
    elif confirmed:action='AVOID / CHASE'
    else:action='WATCH'
    confidence=int(min(90,max(0,round(max(pre,breakout)*.90)))) if action in ACTIONABLE else int(min(69,max(0,round(pre*.90))))
    reasons=[]
    for ok,msg in [(trend_strong,'Strong trend'),(trend_ready,'Trend aligned'),(higher_low,'Higher-low'),(tests>=STRAT.min_resistance_tests,f'{tests} resistance tests'),(compression,'Compression'),(base_tightening,'Base tightening'),(dryup,'Volume dry-up'),(volume_expansion,'Volume expansion'),(accumulation,'Accumulation/OBV'),(delivery_ok,'Delivery improving'),(rs_strong,'Strong RS'),(sector_strength=='POSITIVE','Sector positive'),(confirmed,'Breakout confirmed'),(not valid_risk,'Risk outside limits'),(not sector_ok,'Sector weak')]:
        if ok:reasons.append(msg)
    return locals()

def analyze_stock(g,min_score=None,market=None):
    g=g.sort_values('DATE').reset_index(drop=True)
    if len(g)<MIN_HISTORY:return None
    market=market or {'score':5,'regime':'NEUTRAL','breadth':np.nan};f=_features(g,len(g)-1,market);r=g.iloc[-1]
    def rv(x):
        x=_f(x);return round(x,2) if np.isfinite(x) else ''
    close=f['close'];qty=_f(r.get('DELIV_QTY'));delivery_value=close*qty if np.isfinite(close) and np.isfinite(qty) else np.nan;category={'PRE-BREAKOUT BUY':'PRE-BREAKOUT','BREAKOUT BUY':'BREAKOUT','SWING BUY':'SWING','AVOID / CHASE':'AVOID'}.get(f['action'],'WATCH')
    rr=(f['t1']-f['entry'])/f['risk'] if np.isfinite(f['risk']) and f['risk']>0 else np.nan
    return {'SYMBOL':str(r.SYMBOL),'DATE':pd.Timestamp(r.DATE).strftime('%d-%b-%Y'),'CMP':rv(close),'ACTION':f['action'],'CATEGORY':category,'NEXT_DAY_ACTION':'BUY' if f['action'] in BUY_ACTIONS else 'WATCH','BUY_DATE':(pd.Timestamp(r.DATE)+pd.tseries.offsets.BDay(1)).strftime('%d-%b-%Y'),'STAGE':f['action'],'PRE_BREAKOUT_SCORE':f['pre'],'BREAKOUT_SCORE':f['breakout'],'SWING_SCORE':f['swing'],'HUNTER_SCORE':max(f['pre'],f['breakout'],f['swing']),'NEXT_DAY_SETUP_SCORE':f['pre'],'BREAKOUT_PROBABILITY':f['confidence'],'MARKET_REGIME':market.get('regime','NEUTRAL'),'MARKET_BREADTH':rv(market.get('breadth')),'TREND':'STRONG BULLISH' if f['trend_strong'] else 'ALIGNED' if f['trend_ready'] else 'WEAK','ACCUMULATION':'STRONG' if f['accumulation'] else 'WEAK','DELIVERY':'STRONG + IMPROVING' if f['delivery_ok'] else 'GOOD' if f['delivery_good'] else 'WEAK','DELIVERY_PCT':rv(f['deliv']),'DELIVERY_VALUE':rv(delivery_value),'VOLUME_RATIO':rv(f['vol']),'VOLUME_DRYUP':'YES' if f['dryup'] else 'NO','VOLUME_EXPANSION':'YES' if f['volume_expansion'] else 'NO','ATR_PCT':rv(f['atr_pct']),'ATR_COMPRESSION':'YES' if f['atr_compress'] else 'NO','BB_WIDTH':'COMPRESSING' if f['bb_compress'] else 'NORMAL','BASE_RANGE_PCT':rv(f['base_range']),'BASE_TIGHTENING':'YES' if f['base_tightening'] else 'NO','RESISTANCE':rv(f['prior20']),'RESISTANCE_DISTANCE_PCT':rv(f['distance']),'RESISTANCE_TESTS':int(f['tests']),'HIGHER_LOW':'YES' if f['higher_low'] else 'NO','RELATIVE_STRENGTH':'STRONG' if f['rs_strong'] else 'POSITIVE' if f['rs_positive'] else 'WEAK','RS_VS_UNIVERSE':rv(f['rs']),'RS_IMPROVING':'YES' if f['rs_improving'] else 'NO','SECTOR_STRENGTH':f['sector_strength'],'BREAKOUT_STATUS':'CONFIRMED' if f['confirmed'] else 'NOT YET BROKEN','ENTRY_PRICE':rv(f['entry']),'ENTRY_ZONE':f"{rv(f['zone_low'])} - {rv(f['zone_high'])}",'MAX_BUY_PRICE':rv(f['max_buy']),'BREAKOUT_TRIGGER':rv(f['trigger']),'STOP_LOSS':rv(f['stop']),'TARGET_1':rv(f['t1']),'TARGET_2':rv(f['t2']),'TARGET_3':rv(f['t3']),'RISK_PCT':rv(f['risk_pct']),'R_R':rv(rr),'REASONS':'; '.join(f['reasons']),'QUALITY_GATE':'PENDING'}

def _low52_features(g,i):
    g=g.sort_values('DATE').reset_index(drop=True);r=g.iloc[i];close=_f(r.get('CLOSE_PRICE'));low52=_f(r.get('LOW_52W'));dist_low=_f(r.get('DIST_52W_LOW_PCT'));rsi=_f(r.get('RSI14'));vol=_f(r.get('VOL_RATIO'));deliv=_f(r.get('DELIV_PER'));d10=_f(r.get('DELIV_AVG10'));d20=_f(r.get('DELIV_AVG20'));adx=_f(r.get('ADX14'));plus_di=_f(r.get('PLUS_DI14'));minus_di=_f(r.get('MINUS_DI14'));e20=_f(r.get('EMA20'));ret5=_f(r.get('RET_5D'));atr=_f(r.get('ATR14'));lookback=min(15,i);rsi_hist=g.RSI14.iloc[max(0,i-lookback):i+1] if 'RSI14' in g else pd.Series(dtype=float);rsi_low=_f(rsi_hist.min()) if len(rsi_hist) else np.nan;was_oversold=np.isfinite(rsi_low) and rsi_low<=STRAT.low52_rsi_oversold;rsi_recovering=was_oversold and np.isfinite(rsi) and rsi>=STRAT.low52_rsi_recovery;near_low=np.isfinite(dist_low) and 0<=dist_low<=STRAT.low52_max_distance_pct;bounce_started=np.isfinite(dist_low) and dist_low>=STRAT.low52_min_bounce_pct;not_falling_knife=(not np.isfinite(ret5)) or ret5>=STRAT.low52_max_ret5d_down;higher_low=_higher_low(g,i);swing_high=_f(g.HIGH_PRICE.iloc[max(0,i-10):i].max()) if i>=1 else np.nan;structure_confirmed=np.isfinite(close) and np.isfinite(swing_high) and close>swing_high;volume_confirm=np.isfinite(vol) and vol>=STRAT.low52_min_volume_ratio;delivery_improving=np.isfinite(d10) and np.isfinite(d20) and d10>d20 and np.isfinite(deliv) and deliv>=STRAT.delivery_floor*0.6;trend_flip=np.isfinite(close) and np.isfinite(e20) and close>e20;di_flip=np.isfinite(plus_di) and np.isfinite(minus_di) and plus_di>minus_di;strength_ok=np.isfinite(adx) and adx>=STRAT.min_adx;score=int(min(100,15*int(near_low)+10*int(bounce_started)+15*int(rsi_recovering)+15*int(volume_confirm)+10*int(delivery_improving)+10*int(trend_flip)+10*int(di_flip)+8*int(strength_ok)+7*int(structure_confirmed))) if near_low else 0;gate_ok=near_low and higher_low and not_falling_knife and structure_confirmed;entry=close;stop=entry-1.6*atr if np.isfinite(entry) and np.isfinite(atr) and atr>0 else (low52*0.97 if np.isfinite(low52) else np.nan);risk=entry-stop if np.isfinite(entry) and np.isfinite(stop) else np.nan;risk_pct=risk/entry*100 if np.isfinite(risk) and entry else np.nan;t1=entry+risk*STRAT.min_rr1 if np.isfinite(risk) and risk>0 else np.nan;t2=entry+risk*STRAT.min_rr2 if np.isfinite(risk) and risk>0 else np.nan;t3=entry+risk*STRAT.min_rr3 if np.isfinite(risk) and risk>0 else np.nan
    if gate_ok and score>=STRAT.low52_buy_score:action='EARLY REVERSAL BUY'
    elif near_low and score>=STRAT.low52_min_score:action='REVERSAL WATCH'
    elif near_low:action='NEAR 52W LOW'
    else:action=None
    reasons=[]
    for ok,msg in [(near_low,'52W low ke paas'),(bounce_started,'Low se bounce shuru ho chuka'),(rsi_recovering,'RSI oversold se recover ho raha'),(structure_confirmed,'Swing high confirm tod diya — genuine reversal'),(volume_confirm,'Volume confirm'),(delivery_improving,'Delivery improving'),(trend_flip,'Close EMA20 ke upar aaya'),(di_flip,'+DI > -DI — trend flip confirmed'),(strength_ok,'ADX confirming'),(not not_falling_knife,'Abhi bhi girraha — falling knife risk')]:
        if ok:reasons.append(msg)
    return locals()

def scan_low52_reversal(hist,min_score=None):
    out=[]
    for sym,g in hist.groupby('SYMBOL',sort=False):
        if sym==NIFTY_SYMBOL:continue
        g=g.sort_values('DATE').reset_index(drop=True)
        if len(g)<MIN_HISTORY:continue
        try:f=_low52_features(g,len(g)-1)
        except Exception as e:print(f'Low52 scan error {sym}: {e}');continue
        if not f.get('near_low'):continue
        r=g.iloc[-1]
        def rv(x):
            x=_f(x);return round(x,2) if np.isfinite(x) else ''
        out.append({'SYMBOL':str(sym),'DATE':pd.Timestamp(r.DATE).strftime('%d-%b-%Y'),'CMP':rv(f['close']),'LOW_52W':rv(f['low52']),'DIST_FROM_52W_LOW_PCT':rv(f['dist_low']),'ACTION':f['action'] or 'NEAR 52W LOW','LOW52_SCORE':f['score'],'RSI14':rv(f['rsi']),'VOLUME_RATIO':rv(f['vol']),'VOLUME_CONFIRM':'YES' if f['volume_confirm'] else 'NO','DELIVERY_PCT':rv(f['deliv']),'DELIVERY_IMPROVING':'YES' if f['delivery_improving'] else 'NO','HIGHER_LOW':'YES' if f['higher_low'] else 'NO','TREND_FLIP_ABOVE_EMA20':'YES' if f['trend_flip'] else 'NO','DI_FLIP_BULLISH':'YES' if f['di_flip'] else 'NO','ADX14':rv(f['adx']),'ENTRY_PRICE':rv(f['entry']),'STOP_LOSS':rv(f['stop']),'TARGET_1':rv(f['t1']),'TARGET_2':rv(f['t2']),'TARGET_3':rv(f['t3']),'RISK_PCT':rv(f['risk_pct']),'REASONS':'; '.join(f['reasons'])})
    if not out:return pd.DataFrame()
    df=pd.DataFrame(out);order={'EARLY REVERSAL BUY':1,'REVERSAL WATCH':2,'NEAR 52W LOW':3};df['_PRI']=df.ACTION.map(order).fillna(9);df=df.sort_values(['_PRI','LOW52_SCORE'],ascending=[True,False]).drop(columns='_PRI').reset_index(drop=True);df.insert(0,'RANK',range(1,len(df)+1));return df

def _apex_market_regime(hist):
    nh=hist[hist.SYMBOL.eq(NIFTY_SYMBOL)].sort_values('DATE').reset_index(drop=True)
    if nh.empty:return None
    c,e20,e50,e200=_num(nh,'CLOSE_PRICE'),_num(nh,'EMA20'),_num(nh,'EMA50'),_num(nh,'EMA200');ok=c.notna()&e20.notna()&e50.notna()&e200.notna()
    if not ok.any():return None
    r=nh.loc[ok].iloc[-1];bull=float(r.CLOSE_PRICE)>float(r.EMA20)>float(r.EMA50)>float(r.EMA200);regime='BULLISH' if bull else 'NEUTRAL' if float(r.CLOSE_PRICE)>float(r.EMA50) else 'BEARISH';penalty=0 if regime=='BULLISH' else 3 if regime=='NEUTRAL' else 8
    nifty_df=nh[['DATE','RET_20D']].rename(columns={'RET_20D':'NIFTY_RET_20D'}) if 'RET_20D' in nh.columns else None
    return {'regime':regime,'penalty':penalty,'nifty_df':nifty_df}

def scan_apex_matrix(hist):
    info=_apex_market_regime(hist) or {'regime':'NEUTRAL','penalty':3,'nifty_df':None};out=[]
    for sym,g in hist.groupby('SYMBOL',sort=False):
        if sym==NIFTY_SYMBOL:continue
        g=g.sort_values('DATE').reset_index(drop=True)
        if len(g)<MIN_HISTORY:continue
        r=g.iloc[-1];close=_f(r.get('CLOSE_PRICE'));e20=_f(r.get('EMA20'));e50=_f(r.get('EMA50'));e200=_f(r.get('EMA200'));atr=_f(r.get('ATR14'));rsi=_f(r.get('RSI14'));vol=_f(r.get('VOL_RATIO'));rs=_f(r.get('RS_VS_UNIVERSE'));high=_f(r.get('HIGH_PRICE'));low=_f(r.get('LOW_PRICE'));res=_f(_num(g,'HIGH_PRICE').iloc[max(0,len(g)-20):len(g)-1].max()) if len(g)>1 else np.nan
        strong=np.isfinite(close) and np.isfinite(e20) and np.isfinite(e50) and np.isfinite(e200) and close>e20>e50>e200;positive_rs=np.isfinite(rs) and rs>0;breakout=np.isfinite(res) and close>res*1.003;volume_confirm=np.isfinite(vol) and vol>=APEX.breakout_vol;atr_pct=atr/close*100 if np.isfinite(atr) and close>0 else np.nan;not_extended=np.isfinite(atr) and atr>0 and np.isfinite(e20) and (close-e20)/atr<=APEX.max_extension_atr
        score=(25 if strong else 12)+(15 if rs>=5 else 11 if positive_rs else 0)+(15 if volume_confirm else 5)+(15 if breakout else 5)+(15 if np.isfinite(rsi) and APEX.rsi_min<=rsi<=APEX.rsi_max else 3)+(15 if not_extended else 2)-info['penalty'];score=int(max(0,min(100,score)))
        if breakout and volume_confirm and strong and score>=APEX.apex_score_min:signal='APEX BUY'
        elif breakout and volume_confirm and score>=APEX.tactical_score_min:signal='TACTICAL BUY'
        elif breakout and score>=APEX.buy_score:signal='BUY'
        elif breakout:signal='BREAKOUT READY'
        elif strong and positive_rs:signal='WATCH'
        else:continue
        if signal in {'APEX BUY','TACTICAL BUY','BUY'} and np.isfinite(rsi) and rsi>APEX.rsi_max:signal='BREAKOUT READY' if breakout else 'WATCH'
        initial_sl=close-atr*APEX.initial_atr if np.isfinite(close) and np.isfinite(atr) and atr>0 else np.nan;risk=close-initial_sl if np.isfinite(initial_sl) else np.nan
        out.append({'SYMBOL':str(sym),'DATE':pd.Timestamp(r.DATE).strftime('%d-%b-%Y'),'CMP':close,'SIGNAL':signal,'APEX_SCORE':score,'TREND':'STRONG BULL' if strong else 'BULL','RELATIVE_STRENGTH':rs,'RS_STATE':'POSITIVE' if positive_rs else 'WEAK','RSI14':rsi,'VOLUME_RATIO':vol,'VOLUME_STATE':'CONFIRMED' if volume_confirm else 'NORMAL','VCP_STATE':'NO','SETUP':'BREAKOUT' if breakout else 'WATCHING','RESISTANCE':res,'MARKET_REGIME':info['regime'],'ATR_PCT':atr_pct,'ENTRY_TYPE':signal if 'BUY' in signal else '','ENTRY_PRICE':close if 'BUY' in signal else '','INITIAL_SL':initial_sl,'TARGET_1':close+risk*APEX.rr1 if np.isfinite(risk) else np.nan,'TARGET_2':close+risk*APEX.rr2 if np.isfinite(risk) else np.nan,'REASONS':'; '.join(['Strong trend' if strong else '', 'Positive RS' if positive_rs else '', 'Breakout' if breakout else '', 'Volume confirmed' if volume_confirm else '']).strip('; ')})
    if not out:return pd.DataFrame()
    df=pd.DataFrame(out);order={'APEX BUY':1,'TACTICAL BUY':2,'BUY':3,'BREAKOUT READY':4,'WATCH':5};df['_PRI']=df.SIGNAL.map(order).fillna(9);df=df.sort_values(['_PRI','APEX_SCORE'],ascending=[True,False]).drop(columns='_PRI').reset_index(drop=True);df.insert(0,'RANK',range(1,len(df)+1));return df

def scan_stealth_accumulation(hist):
    out=[]
    for sym,g in hist.groupby('SYMBOL',sort=False):
        if sym==NIFTY_SYMBOL:continue
        g=g.sort_values('DATE').reset_index(drop=True)
        if len(g)<MIN_HISTORY:continue
        r=g.iloc[-1];close=_f(r.get('CLOSE_PRICE'));e50=_f(r.get('EMA50'));e100=_f(r.get('EMA100'));atr_pct=_f(r.get('ATR_PCT'));atr_avg=_f(r.get('ATR_PCT_AVG30'));deliv=_f(r.get('DELIV_PER'));d10=_f(r.get('DELIV_AVG10'));d20=_f(r.get('DELIV_AVG20'));rsi=_f(r.get('RSI14'));v=_num(g,'TTL_TRD_QNTY').fillna(0);c=_num(g,'CLOSE_PRICE');obv=(np.sign(c.diff()).fillna(0)*v).cumsum();lb=STRAT.stealth_lookback;obv_rising=len(g)>lb and _f(obv.iloc[-1])>_f(obv.iloc[-1-lb]);calm=np.isfinite(atr_pct) and np.isfinite(atr_avg) and atr_avg>0 and atr_pct<=atr_avg*STRAT.stealth_atr_compression;deliv_high=np.isfinite(deliv) and deliv>=STRAT.delivery_floor;deliv_rising=np.isfinite(d10) and np.isfinite(d20) and d10>d20;above50=np.isfinite(close) and np.isfinite(e50) and close>=e50*.98;not_hot=np.isfinite(rsi) and STRAT.stealth_rsi_min<=rsi<=STRAT.stealth_rsi_max;uptrend=np.isfinite(close) and np.isfinite(e100) and close>=e100*.97;score=int(min(100,20*int(calm)+20*int(obv_rising)+15*int(deliv_high)+15*int(deliv_rising)+10*int(above50)+10*int(not_hot)+10*int(uptrend)))
        if calm and obv_rising and uptrend and score>=STRAT.stealth_buy_score:action='STEALTH BUY'
        elif calm and obv_rising and score>=STRAT.stealth_min_score:action='STEALTH WATCH'
        else:continue
        out.append({'RANK':0,'SYMBOL':str(sym),'DATE':pd.Timestamp(r.DATE).strftime('%d-%b-%Y'),'CMP':close,'ACTION':action,'STEALTH_SCORE':score,'ATR_PCT':atr_pct,'ATR_AVG30':atr_avg,'DELIVERY_PCT':deliv,'DELIVERY_RISING':'YES' if deliv_rising else 'NO','OBV_RISING':'YES' if obv_rising else 'NO','RSI14':rsi,'BASE_RANGE_PCT':'','BASE_HIGH':'','BASE_LOW':'','ENTRY_PRICE':close,'STOP_LOSS':'','TARGET_1':'','TARGET_2':'','TARGET_3':'','RISK_PCT':'','REASONS':'; '.join([x for x in ['Volatility compressed' if calm else '', 'OBV rising' if obv_rising else '', 'Delivery rising' if deliv_rising else '', 'Above EMA50' if above50 else '', 'Long-term trend intact' if uptrend else ''] if x])})
    if not out:return pd.DataFrame()
    df=pd.DataFrame(out);df['_PRI']=df.ACTION.map({'STEALTH BUY':1,'STEALTH WATCH':2}).fillna(9);df=df.sort_values(['_PRI','STEALTH_SCORE'],ascending=[True,False]).drop(columns='_PRI').reset_index(drop=True);df['RANK']=range(1,len(df)+1);return df

def scan_all(hist,min_score=None):
    market=_market_context(hist);out=[]
    for sym,g in hist.groupby('SYMBOL',sort=False):
        if sym==NIFTY_SYMBOL:continue
        try:
            sig=analyze_stock(g,min_score,market)
            if sig is not None:out.append(sig)
        except Exception as e:print(f'Strategy error {sym}: {e}')
    return pd.DataFrame(out)

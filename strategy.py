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
    atr=_f(r.get('ATR14'));atr_pct=_f(r.get('ATR_PCT'));atr_avg=_f(r.get('ATR_PCT_AVG30'));vol=_f(r.get('VOL_RATIO'));deliv=_f(r.get('DELIV_PER'));d10=_f(r.get('DELIV_AVG10'));d20=_f(r.get('DELIV_AVG20'));rsi=_f(r.get('RSI14'));adx=_f(r.get('ADX14'));rs=_f(r.get('RS_VS_UNIVERSE'))
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
    accumulation=obv_rising and (volume_acc or dryup)
    delivery_good=np.isfinite(deliv) and deliv>=STRAT.delivery_floor;delivery_improving=np.isfinite(d10) and np.isfinite(d20) and d10>d20;delivery_ok=delivery_good and delivery_improving
    rs_positive=np.isfinite(rs) and rs>=STRAT.min_rs_spread_pct;rs_strong=np.isfinite(rs) and rs>=1;rs_improving=i>=5 and 'RS_VS_UNIVERSE' in g and np.isfinite(_f(g.RS_VS_UNIVERSE.iloc[i-5])) and rs>_f(g.RS_VS_UNIVERSE.iloc[i-5])
    distance=((prior20-close)/close*100) if np.isfinite(prior20) and close else np.nan;near_res=np.isfinite(distance) and 0<=distance<=STRAT.max_resistance_distance_pct;tests=_resistance_tests(g,i,prior20);higher_low=_higher_low(g,i);confirmed=np.isfinite(prior20) and close>=prior20*1.002
    extension=_pct(close,e20);ret5=_f(r.get('RET_5D'));not_extended=(not np.isfinite(extension) or extension<=STRAT.max_entry_extension_pct) and (not np.isfinite(ret5) or ret5<=8);momentum_ok=(not np.isfinite(rsi) or 50<=rsi<=72) and (not np.isfinite(ret5) or ret5>=STRAT.min_recovery_5d_pct)
    close_strength=((close-low)/(high-low)) if np.isfinite(high) and np.isfinite(low) and high>low else np.nan;breakout_candle=confirmed and np.isfinite(close_strength) and close_strength>=STRAT.breakout_min_close_strength;breakout_extension=not np.isfinite(extension) or extension<=STRAT.max_breakout_extension_pct
    sector_strength='UNAVAILABLE';sector_ok=True
    if 'SECTOR' in g.columns:
        sector=str(r.get('SECTOR',''));sg=g[g.SECTOR.astype(str).eq(sector)]
        if len(sg)>=20:
            sr=_f(sg.RET_20D.iloc[-1]);sector_strength='POSITIVE' if np.isfinite(sr) and sr>0 else 'WEAK';sector_ok=sector_strength=='POSITIVE'
    pre=15*int(near_res)+10*int(tests>=STRAT.min_resistance_tests)+10*int(higher_low)+10*int(compression and (base_tightening or range_tight))+15*int(delivery_ok)+10*int(obv_rising)+8*int(volume_acc)+7*int(rs_strong)+8*int(trend_strong)+7*int(not_extended);pre=int(min(100,pre))
    breakout=20*int(confirmed)+20*int(volume_expansion)+15*int(delivery_good)+15*int(trend_ready)+10*int(rs_positive)+10*int(breakout_candle)+10*int(breakout_extension);breakout=int(min(100,breakout))
    pullback=(np.isfinite(ret5) and -8<=ret5<=2) or (np.isfinite(extension) and extension<=2.5);swing=int(min(100,(25 if trend_strong else 18 if trend_ready else 0)+(20 if pullback else 0)+(15 if rs_positive else 0)+(15 if accumulation else 0)+(10 if delivery_good else 0)+(15 if not_extended else 0)))
    dryup_gate=(dryup or not STRAT.require_volume_dryup)
    pre_gate=(not confirmed and near_res and tests>=STRAT.min_resistance_tests and higher_low and compression and delivery_ok and accumulation and trend_ready and rs_positive and rs_improving and momentum_ok and not_extended and np.isfinite(adx) and adx>=STRAT.min_adx and market.get('score',5)>=STRAT.min_regime_score and sector_ok and dryup_gate)
    trigger=prior20*1.003 if np.isfinite(prior20) else np.nan;entry=close;stop=close-1.5*atr if np.isfinite(close) and np.isfinite(atr) and atr>0 else np.nan
    if np.isfinite(low20) and np.isfinite(stop):stop=max(stop,low20*.985)
    risk=entry-stop if np.isfinite(entry) and np.isfinite(stop) else np.nan;risk_pct=risk/entry*100 if np.isfinite(risk) and entry else np.nan;valid_risk=np.isfinite(risk_pct) and STRAT.min_stop_pct<=risk_pct<=STRAT.max_stop_pct
    t1=entry+risk*STRAT.min_rr1 if np.isfinite(risk) and risk>0 else np.nan;t2=entry+risk*STRAT.min_rr2 if np.isfinite(risk) and risk>0 else np.nan;t3=entry+risk*STRAT.min_rr3 if np.isfinite(risk) and risk>0 else np.nan
    zone_low=entry*(1-STRAT.max_buy_zone_pct/100);zone_high=entry*(1+STRAT.max_buy_zone_pct/100);max_buy=min(zone_high,trigger*.997 if np.isfinite(trigger) else zone_high)
    pre_buy=pre_gate and pre>=STRAT.buy_score and valid_risk;breakout_buy=confirmed and breakout>=STRAT.buy_score and volume_expansion and delivery_good and trend_ready and rs_positive and breakout_candle and breakout_extension and valid_risk;swing_buy=(not confirmed and swing>=STRAT.buy_score and trend_ready and rs_positive and not_extended and valid_risk and not pre_buy)
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
    g=g.sort_values('DATE').reset_index(drop=True);r=g.iloc[i]
    close=_f(r.get('CLOSE_PRICE'));low52=_f(r.get('LOW_52W'));dist_low=_f(r.get('DIST_52W_LOW_PCT'))
    rsi=_f(r.get('RSI14'));vol=_f(r.get('VOL_RATIO'));deliv=_f(r.get('DELIV_PER'));d10=_f(r.get('DELIV_AVG10'));d20=_f(r.get('DELIV_AVG20'))
    adx=_f(r.get('ADX14'));plus_di=_f(r.get('PLUS_DI14'));minus_di=_f(r.get('MINUS_DI14'))
    e20=_f(r.get('EMA20'));e50=_f(r.get('EMA50'));ret5=_f(r.get('RET_5D'));atr=_f(r.get('ATR14'))
    lookback=min(15,i);rsi_hist=g.RSI14.iloc[max(0,i-lookback):i+1] if 'RSI14' in g else pd.Series(dtype=float)
    rsi_low=_f(rsi_hist.min()) if len(rsi_hist) else np.nan
    was_oversold=np.isfinite(rsi_low) and rsi_low<=STRAT.low52_rsi_oversold
    rsi_recovering=was_oversold and np.isfinite(rsi) and rsi>=STRAT.low52_rsi_recovery
    near_low=np.isfinite(dist_low) and 0<=dist_low<=STRAT.low52_max_distance_pct
    bounce_started=np.isfinite(dist_low) and dist_low>=STRAT.low52_min_bounce_pct
    not_falling_knife=(not np.isfinite(ret5)) or ret5>=STRAT.low52_max_ret5d_down
    low5=_f(g.LOW_PRICE.iloc[max(0,i-5):i+1].min()) if i>=1 else np.nan
    higher_low=np.isfinite(close) and np.isfinite(low5) and close>=low5
    volume_confirm=np.isfinite(vol) and vol>=STRAT.low52_min_volume_ratio
    delivery_improving=np.isfinite(d10) and np.isfinite(d20) and d10>d20 and np.isfinite(deliv) and deliv>=STRAT.delivery_floor*0.6
    trend_flip=np.isfinite(close) and np.isfinite(e20) and close>e20
    di_flip=np.isfinite(plus_di) and np.isfinite(minus_di) and plus_di>minus_di
    strength_ok=np.isfinite(adx) and adx>=STRAT.min_adx
    score=int(min(100,20*int(near_low)+15*int(bounce_started)+15*int(rsi_recovering)+15*int(volume_confirm)+10*int(delivery_improving)+10*int(trend_flip)+8*int(di_flip)+7*int(strength_ok))) if near_low else 0
    gate_ok=near_low and bounce_started and rsi_recovering and not_falling_knife and higher_low and (volume_confirm or delivery_improving)
    entry=close
    stop=entry-1.6*atr if np.isfinite(entry) and np.isfinite(atr) and atr>0 else (low52*0.97 if np.isfinite(low52) else np.nan)
    risk=entry-stop if np.isfinite(entry) and np.isfinite(stop) else np.nan
    risk_pct=risk/entry*100 if np.isfinite(risk) and entry else np.nan
    t1=entry+risk*STRAT.min_rr1 if np.isfinite(risk) and risk>0 else np.nan
    t2=entry+risk*STRAT.min_rr2 if np.isfinite(risk) and risk>0 else np.nan
    t3=entry+risk*STRAT.min_rr3 if np.isfinite(risk) and risk>0 else np.nan
    if gate_ok and score>=STRAT.low52_buy_score:action='EARLY REVERSAL BUY'
    elif near_low and score>=STRAT.low52_min_score:action='REVERSAL WATCH'
    elif near_low:action='NEAR 52W LOW'
    else:action=None
    reasons=[]
    for ok,msg in [(near_low,'52W low ke paas'),(bounce_started,'Low se bounce shuru ho chuka'),(rsi_recovering,'RSI oversold se recover ho raha'),(volume_confirm,'Volume expansion'),(delivery_improving,'Delivery improving'),(trend_flip,'Close EMA20 ke upar aaya'),(di_flip,'+DI > -DI — early trend flip'),(strength_ok,'ADX confirming'),(not not_falling_knife,'Abhi bhi girraha — falling knife risk')]:
        if ok:reasons.append(msg)
    return locals()


def scan_low52_reversal(hist,min_score=None):
    """Separate scanner (not the breakout hunter): finds NIFTY500 stocks still trading
    near their 52-week low that show the first confirmed signs of a turn, so they can
    be watched/caught before the bulk of the move — not after. Not covered by the
    breakout-hunter backtest/quality-gate, so treat this list as a screening watchlist,
    not a gated buy signal."""
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
    df=pd.DataFrame(out)
    order={'EARLY REVERSAL BUY':1,'REVERSAL WATCH':2,'NEAR 52W LOW':3}
    df['_PRI']=df.ACTION.map(order).fillna(9)
    df=df.sort_values(['_PRI','LOW52_SCORE'],ascending=[True,False]).drop(columns='_PRI').reset_index(drop=True)
    df.insert(0,'RANK',range(1,len(df)+1))
    return df


def scan_all(hist,min_score=None):
    market=_market_context(hist);out=[]
    for sym,g in hist.groupby('SYMBOL',sort=False):
        if sym==NIFTY_SYMBOL:continue
        try:
            sig=analyze_stock(g,min_score,market)
            if sig is not None:out.append(sig)
        except Exception as e:print(f'Strategy error {sym}: {e}')
    return pd.DataFrame(out)


# ═══════════════════════════════════════════════════════════════════════════
# APEX MATRIX — faithful Python port of RY APEX MATRIX V42 (Pine Script).
# Independent of the breakout-hunter above: different score weights, different
# signal definitions, its own NIFTY-relative regime/RS. A stock can appear on
# this list, the hunter list, both, or neither — they are not merged.
# Not covered by quality_gate's backtest (no backtest exists for this scorer
# yet) — treat as a screening list mirroring the TradingView indicator,
# not a gated buy signal.
# ═══════════════════════════════════════════════════════════════════════════

def _apex_regime_series(hist):
    """Day-by-day NIFTY regime + penalty for every date NIFTY data exists —
    the backtest needs the regime AS OF each historical signal day, not just
    'today's' (a single latest-day regime would leak future market context
    into old signals). Returns None if no usable NIFTY rows are present."""
    nh=hist[hist.SYMBOL.eq(NIFTY_SYMBOL)].sort_values('DATE').reset_index(drop=True)
    if nh.empty or 'EMA20' not in nh.columns:return None
    c,e20,e50,e200=_num(nh,'CLOSE_PRICE'),_num(nh,'EMA20'),_num(nh,'EMA50'),_num(nh,'EMA200')
    bull=(c>e20)&(e20>e50)&(e50>e200)
    neutral=(c>e50)&(~bull)
    out=nh[['DATE']].copy()
    out['REGIME']=np.where(bull,'BULLISH',np.where(neutral,'NEUTRAL','BEARISH'))
    out['PENALTY']=np.where(bull,0,np.where(neutral,3,8))
    out.loc[~np.isfinite(c)|~np.isfinite(e20)|~np.isfinite(e50)|~np.isfinite(e200),['REGIME','PENALTY']]=[None,None]
    if 'RET_20D' in nh.columns:out['NIFTY_RET_20D']=nh['RET_20D']
    return out


def _apex_market_regime(hist):
    """Mirrors Pine's request.security(NIFTY,...) market-regime block, for the
    LIVE scanner (today's regime only). Returns None if no usable NIFTY row is
    present (fetch failed / not yet available) — callers must fall back
    gracefully, not crash."""
    series=_apex_regime_series(hist)
    if series is None or series.empty:return None
    r=series.iloc[-1]
    if r['REGIME'] is None or (isinstance(r['REGIME'],float) and pd.isna(r['REGIME'])):return None
    nifty_df=series[['DATE','NIFTY_RET_20D']] if 'NIFTY_RET_20D' in series.columns else None
    return {'regime':r['REGIME'],'penalty':int(r['PENALTY']),'nifty_df':nifty_df}


def _apex_features(g,i,regime_info):
    r=g.iloc[i]
    close,high,low,openp=[_f(r.get(x)) for x in ('CLOSE_PRICE','HIGH_PRICE','LOW_PRICE','OPEN_PRICE')]
    if not np.isfinite(close):return None
    e20,e50,e200=[_f(r.get(x)) for x in ('EMA20','EMA50','EMA200')]
    e20p=_f(g.EMA20.iloc[i-5]) if i>=5 and 'EMA20' in g else np.nan
    e50p=_f(g.EMA50.iloc[i-5]) if i>=5 and 'EMA50' in g else np.nan
    rsi=_f(r.get('RSI14'));adx=_f(r.get('ADX14'));plus_di=_f(r.get('PLUS_DI14'));minus_di=_f(r.get('MINUS_DI14'))
    atr=_f(r.get('ATR14'));vol_ratio=_f(r.get('VOL_RATIO'))
    vol_ratio_prev=_f(g.VOL_RATIO.iloc[i-1]) if i>=1 and 'VOL_RATIO' in g else np.nan
    rsi_prev=_f(g.RSI14.iloc[i-1]) if i>=1 and 'RSI14' in g else np.nan

    # 15. TREND
    ema20_rising=np.isfinite(e20) and np.isfinite(e20p) and e20>e20p
    ema50_rising=np.isfinite(e50) and np.isfinite(e50p) and e50>e50p
    strong_trend=all(np.isfinite(x) for x in (close,e20,e50,e200)) and close>e20 and e20>e50 and e50>e200 and ema20_rising and ema50_rising
    healthy_trend=np.isfinite(close) and np.isfinite(e50) and np.isfinite(e200) and close>e50 and e50>e200
    bull_trend=np.isfinite(close) and np.isfinite(e50) and close>e50

    # 17. RELATIVE STRENGTH vs NIFTY (falls back to universe-RS if NIFTY row missing)
    stock_roc=_f(r.get('RET_20D'));nifty_df=regime_info.get('nifty_df');nifty_roc=np.nan
    if nifty_df is not None:
        match=nifty_df[nifty_df.DATE.eq(r.DATE)]
        if not match.empty:nifty_roc=_f(match.iloc[0]['NIFTY_RET_20D'])
    relative_strength=(stock_roc-nifty_roc) if np.isfinite(nifty_roc) and np.isfinite(stock_roc) else _f(r.get('RS_VS_UNIVERSE'))
    rs_strong=np.isfinite(relative_strength) and relative_strength>=5.0
    rs_positive=np.isfinite(relative_strength) and relative_strength>0

    # 18. RSI / ADX
    rsi_healthy=np.isfinite(rsi) and APEX.rsi_min<=rsi<=APEX.rsi_max
    rsi_strong=np.isfinite(rsi) and 58<=rsi<=72
    rsi_recovery=np.isfinite(rsi) and np.isfinite(rsi_prev) and rsi>50 and rsi>rsi_prev
    adx_good=np.isfinite(adx) and np.isfinite(plus_di) and np.isfinite(minus_di) and adx>=APEX.adx_min and plus_di>minus_di
    adx_strong=np.isfinite(adx) and np.isfinite(plus_di) and np.isfinite(minus_di) and adx>=25 and plus_di>minus_di

    # 19. VOLUME
    volume_strong=np.isfinite(vol_ratio) and vol_ratio>=APEX.strong_vol
    volume_confirmed=np.isfinite(vol_ratio) and vol_ratio>=APEX.breakout_vol
    volume_normal=np.isfinite(vol_ratio) and vol_ratio>=0.80
    volume_dry=np.isfinite(vol_ratio) and vol_ratio<=APEX.dry_up_ratio
    prev_volume_dry=np.isfinite(vol_ratio_prev) and vol_ratio_prev<=APEX.dry_up_ratio
    volume_expansion=prev_volume_dry and volume_confirmed
    volume_acceleration=np.isfinite(vol_ratio) and np.isfinite(vol_ratio_prev) and vol_ratio>vol_ratio_prev and vol_ratio>=1.0

    # 20. VCP / COMPRESSION
    h=_num(g,'HIGH_PRICE');l=_num(g,'LOW_PRICE');atr_series=_num(g,'ATR14')
    avg_range_now=_f((h-l).rolling(APEX.vcp_lookback,min_periods=APEX.vcp_lookback).mean().iloc[i])
    today_range=(high-low) if np.isfinite(high) and np.isfinite(low) else np.nan
    range_compressed=np.isfinite(avg_range_now) and avg_range_now>0 and np.isfinite(today_range) and today_range<=avg_range_now*APEX.compression_level
    atr_fast=_f(atr_series.iloc[max(0,i-4):i+1].mean()) if i>=4 else np.nan
    atr_slow=_f(atr_series.iloc[max(0,i-APEX.vcp_lookback+1):i+1].mean()) if i>=APEX.vcp_lookback-1 else np.nan
    atr_compressed=np.isfinite(atr_fast) and np.isfinite(atr_slow) and atr_fast<atr_slow
    vcp_potential=range_compressed and atr_compressed
    vcp_confirmed=vcp_potential and volume_dry

    # 13/23. RESISTANCE + BREAKOUT (HIGH-based, matches Pine's ta.highest(high[1],20))
    resistance=_f(h.iloc[max(0,i-APEX.res_lookback):i].max()) if i>=1 else np.nan
    breakout_level=resistance*(1+APEX.breakout_buffer_pct/100) if np.isfinite(resistance) else np.nan
    is_breakout=np.isfinite(close) and np.isfinite(breakout_level) and close>breakout_level
    resistance_distance=np.nan
    if np.isfinite(resistance) and resistance:
        resistance_distance=((close-resistance)/resistance*100) if close>=resistance else ((resistance-close)/resistance*100)
    near_resistance=np.isfinite(close) and np.isfinite(resistance) and close<resistance and np.isfinite(resistance_distance) and resistance_distance<=APEX.near_resistance_pct
    vcp_breakout=vcp_confirmed and is_breakout and volume_confirmed

    candle_range=(high-low) if np.isfinite(high) and np.isfinite(low) else np.nan
    candle_body=abs(close-openp) if np.isfinite(close) and np.isfinite(openp) else np.nan
    body_ratio=(candle_body/candle_range) if np.isfinite(candle_body) and np.isfinite(candle_range) and candle_range>0 else np.nan
    close_position=((close-low)/candle_range) if np.isfinite(close) and np.isfinite(low) and np.isfinite(candle_range) and candle_range>0 else np.nan
    bullish_candle=np.isfinite(close) and np.isfinite(openp) and close>openp
    bull_quality=bullish_candle and np.isfinite(body_ratio) and body_ratio>=APEX.min_body_ratio and np.isfinite(close_position) and close_position>=APEX.min_close_position

    strong_breakout=is_breakout and volume_strong and bull_quality and np.isfinite(e20) and np.isfinite(e50) and close>e20 and close>e50
    confirmed_breakout=is_breakout and volume_confirmed and bullish_candle and np.isfinite(close_position) and close_position>=0.60 and np.isfinite(e50) and close>e50

    # 24. EXTENSION / RISK
    extension_atr=((close-e20)/atr) if np.isfinite(close) and np.isfinite(e20) and np.isfinite(atr) and atr>0 else np.nan
    not_over_extended=np.isfinite(extension_atr) and extension_atr<=APEX.max_extension_atr
    atr_pct=(atr/close*100) if np.isfinite(atr) and close>0 else np.nan

    # 21/22. ACCUMULATION / PULLBACK / EMA RECOVERY
    recent_high=_f(h.iloc[max(0,i-APEX.accumulation_lookback):i].max()) if i>=1 else np.nan
    recent_low=_f(l.iloc[max(0,i-APEX.accumulation_lookback):i].min()) if i>=1 else np.nan
    range_width=((recent_high-recent_low)/recent_low*100) if np.isfinite(recent_high) and np.isfinite(recent_low) and recent_low>0 else 999.0
    tight_range=range_width<=12
    accumulation=healthy_trend and volume_dry and tight_range and np.isfinite(e50) and close>=e50
    pullback=healthy_trend and np.isfinite(low) and np.isfinite(e20) and low<=e20*1.03 and close>=e20*0.98 and rsi_recovery
    e20_prev1=_f(g.EMA20.iloc[i-1]) if i>=1 and 'EMA20' in g else np.nan
    close_prev1=_f(g.CLOSE_PRICE.iloc[i-1]) if i>=1 else np.nan
    ema_recovery=np.isfinite(close) and np.isfinite(e20) and close>e20 and np.isfinite(close_prev1) and np.isfinite(e20_prev1) and close_prev1<=e20_prev1 and bullish_candle and rsi_recovery and np.isfinite(vol_ratio) and vol_ratio>=1.0

    # 25/26. SCORE ENGINE + MARKET PENALTY
    trend_score=25 if strong_trend else (19 if healthy_trend else (12 if bull_trend else 0))
    rs_score=15 if rs_strong else (11 if rs_positive else (6 if np.isfinite(relative_strength) and relative_strength>-3 else 0))
    momentum_score=15 if (adx_strong and rsi_strong) else (12 if (adx_good and rsi_healthy) else (8 if (rsi_healthy or rsi_recovery) else 3))
    volume_score=15 if volume_strong else (15 if volume_expansion else (12 if volume_confirmed else (9 if volume_acceleration else (8 if volume_dry else (5 if volume_normal else 2)))))
    structure_score=15 if vcp_breakout else 15 if strong_breakout else 13 if confirmed_breakout else 11 if vcp_confirmed else 10 if accumulation else 8 if near_resistance else 8 if pullback else 7 if ema_recovery else 3
    if np.isfinite(atr_pct):
        risk_score=(15 if atr_pct<=4 else 12 if atr_pct<=7 else 9 if atr_pct<=10 else 6) if not_over_extended else 2
    else:
        risk_score=2
    raw_score=trend_score+rs_score+momentum_score+volume_score+structure_score+risk_score
    market_penalty=regime_info.get('penalty',3)
    apex_score=max(0,raw_score-market_penalty)

    # 30. BUY LOGIC
    normal_buy_setup=confirmed_breakout or strong_breakout or vcp_breakout or ema_recovery
    normal_buy=apex_score>=APEX.buy_score and normal_buy_setup and (not APEX.require_breakout_for_buy or confirmed_breakout or strong_breakout or vcp_breakout) and not_over_extended
    apex_buy=apex_score>=APEX.apex_score_min and (strong_breakout or vcp_breakout) and not_over_extended
    tactical_buy=(strong_breakout or vcp_breakout) and apex_score>=APEX.tactical_score_min and not_over_extended
    pre_breakout_setup=(near_resistance or vcp_confirmed or accumulation or pullback) and not is_breakout and healthy_trend and not_over_extended
    accumulation_setup=accumulation and not is_breakout
    watch_setup=(healthy_trend or bull_trend) and (rs_positive or rsi_recovery or vcp_potential)

    if apex_buy:signal='APEX BUY'
    elif tactical_buy:signal='TACTICAL BUY'
    elif normal_buy:signal='BUY'
    elif vcp_breakout:signal='BREAKOUT READY'
    elif pre_breakout_setup:signal='PRE-BREAKOUT'
    elif accumulation_setup:signal='ACCUMULATION'
    elif watch_setup:signal='WATCH'
    else:signal='WAIT'

    # 31/33/40. RISK LEVELS (initial SL only — day-to-day trailing-SL/exit state
    # lives in trade_manager.py once a position is actually opened, not here)
    initial_sl=close-atr*APEX.initial_atr if np.isfinite(close) and np.isfinite(atr) and atr>0 else np.nan
    valid_risk=np.isfinite(initial_sl) and initial_sl<close
    risk_value=(close-initial_sl) if valid_risk else np.nan
    target1=close+risk_value*APEX.rr1 if np.isfinite(risk_value) else np.nan
    target2=close+risk_value*APEX.rr2 if np.isfinite(risk_value) else np.nan
    entry_type='APEX BUY' if apex_buy else ('TACTICAL BUY' if tactical_buy else ('BUY' if normal_buy else ''))

    reasons=[]
    for ok,msg in [(strong_trend,'Strong trend'),(healthy_trend and not strong_trend,'Healthy trend'),(rs_strong,'Strong RS vs NIFTY'),(rs_positive and not rs_strong,'Positive RS'),(adx_strong,'Strong ADX+DI'),(rsi_strong,'RSI strong zone'),(volume_strong,'High volume'),(volume_expansion,'Volume expansion (dry-up\u2192confirm)'),(vcp_breakout,'VCP breakout'),(strong_breakout and not vcp_breakout,'Strong breakout'),(confirmed_breakout and not strong_breakout and not vcp_breakout,'Confirmed breakout'),(accumulation,'Accumulation'),(pullback,'Pullback in trend'),(ema_recovery,'EMA20 recovery'),(not not_over_extended,'Over-extended from EMA20 \u2014 risk')]:
        if ok:reasons.append(msg)
    return locals()


def scan_apex_matrix(hist):
    """Python port of RY APEX MATRIX V42 (Pine Script) — same scoring/buy logic,
    run over the NIFTY500 universe so the setups that would fire APEX BUY /
    TACTICAL BUY / BUY on the TradingView indicator get surfaced here too.
    Independent of scan_all()'s breakout hunter: different weights, different
    definitions, no shared backtest — a stock can appear on either list, both,
    or neither. Not quality-gated (no backtest exists for this scorer yet)."""
    regime_info=_apex_market_regime(hist)
    if regime_info is None:
        print('APEX MATRIX: NIFTY index data unavailable this run — using NEUTRAL regime + universe-RS fallback')
        regime_info={'regime':'NEUTRAL (no NIFTY data)','penalty':3,'nifty_df':None}
    out=[]
    for sym,g in hist.groupby('SYMBOL',sort=False):
        if sym==NIFTY_SYMBOL:continue
        g=g.sort_values('DATE').reset_index(drop=True)
        if len(g)<MIN_HISTORY:continue
        try:f=_apex_features(g,len(g)-1,regime_info)
        except Exception as e:print(f'APEX scan error {sym}: {e}');continue
        if f is None or f.get('signal')=='WAIT':continue
        r=g.iloc[-1]
        def rv(x):
            x=_f(x);return round(x,2) if np.isfinite(x) else ''
        out.append({
            'SYMBOL':str(sym),'DATE':pd.Timestamp(r.DATE).strftime('%d-%b-%Y'),'CMP':rv(f['close']),
            'SIGNAL':f['signal'],'APEX_SCORE':f['apex_score'],
            'TREND':'STRONG BULL' if f['strong_trend'] else 'HEALTHY BULL' if f['healthy_trend'] else 'BULL' if f['bull_trend'] else 'WEAK',
            'RELATIVE_STRENGTH':rv(f['relative_strength']),'RS_STATE':'STRONG' if f['rs_strong'] else 'POSITIVE' if f['rs_positive'] else 'WEAK',
            'RSI14':rv(f['rsi']),'ADX14':rv(f['adx']),
            'VOLUME_RATIO':rv(f['vol_ratio']),'VOLUME_STATE':'HIGH' if f['volume_strong'] else 'EXPANSION' if f['volume_expansion'] else 'CONFIRMED' if f['volume_confirmed'] else 'DRY-UP' if f['volume_dry'] else 'NORMAL' if f['volume_normal'] else 'LOW',
            'VCP_STATE':'BREAKOUT' if f['vcp_breakout'] else 'READY' if f['vcp_confirmed'] else 'POTENTIAL' if f['vcp_potential'] else 'NO',
            'SETUP':'STRONG BREAKOUT' if f['strong_breakout'] else 'CONFIRMED BREAKOUT' if f['confirmed_breakout'] else 'VCP BREAKOUT' if f['vcp_breakout'] else 'VCP READY' if f['vcp_confirmed'] else 'ACCUMULATION' if f['accumulation'] else 'PULLBACK' if f['pullback'] else 'EMA RECOVERY' if f['ema_recovery'] else 'NEAR RESISTANCE' if f['near_resistance'] else 'WAITING',
            'RESISTANCE':rv(f['resistance']),'MARKET_REGIME':regime_info['regime'],'ATR_PCT':rv(f['atr_pct']),
            'ENTRY_TYPE':f['entry_type'],'ENTRY_PRICE':rv(f['close']) if f['entry_type'] else '',
            'INITIAL_SL':rv(f['initial_sl']),'TARGET_1':rv(f['target1']),'TARGET_2':rv(f['target2']),
            'REASONS':'; '.join(f['reasons']),
        })
    if not out:return pd.DataFrame()
    df=pd.DataFrame(out)
    order={'APEX BUY':1,'TACTICAL BUY':2,'BUY':3,'BREAKOUT READY':4,'PRE-BREAKOUT':5,'ACCUMULATION':6,'WATCH':7}
    df['_PRI']=df.SIGNAL.map(order).fillna(9)
    df=df.sort_values(['_PRI','APEX_SCORE'],ascending=[True,False]).drop(columns='_PRI').reset_index(drop=True)
    df.insert(0,'RANK',range(1,len(df)+1))
    return df

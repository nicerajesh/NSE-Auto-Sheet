from __future__ import annotations
import importlib
from typing import Dict
import numpy as np
import pandas as pd

ACTIONABLE={'PRE-BREAKOUT BUY','BREAKOUT BUY','SWING BUY'}
HUMAN_ACTIONS={'PRE-BREAKOUT BUY':'🟢 ABHI KHARIDO','BREAKOUT BUY':'🟡 BREAKOUT KE UPAR KHARIDO','SWING BUY':'🔵 GIRAVAT MEIN KHARIDO','WATCH':'⚪ ABHI WAIT KARO','AVOID / CHASE':'🔴 ABHI MAT KHARIDO'}


def _f(x,default=np.nan):
    try:
        y=float(x); return y if np.isfinite(y) else default
    except Exception:return default


def _pct(a,b):
    a,b=_f(a),_f(b)
    return (a/b-1.0)*100 if np.isfinite(a) and np.isfinite(b) and b else np.nan


def _safe_percent(v):
    x=_f(v)
    return round(x,2) if np.isfinite(x) else ''


def _target_levels(entry,atr,resistance,high52):
    if not np.isfinite(entry) or entry<=0:return None
    vol=atr if np.isfinite(atr) and atr>0 else entry*0.025
    raw=[entry+2.5*vol,entry+4*vol,entry+6*vol]
    if np.isfinite(resistance) and resistance>entry:raw += [resistance*1.08]
    if np.isfinite(high52) and high52>entry:raw += [high52*1.03]
    vals=sorted({round(x,4) for x in raw if np.isfinite(x) and x>entry})
    if not vals:return None
    t1=vals[0];t2=vals[min(1,len(vals)-1)];t3=vals[min(2,len(vals)-1)]
    return t1,t2,t3


def _timing_features(g):
    g=g.sort_values('DATE').reset_index(drop=True); r=g.iloc[-1]
    close=_f(r.get('CLOSE_PRICE')); e20=_f(r.get('EMA20')); atr=_f(r.get('ATR14')); ret5=_f(r.get('RET_5D')); ret10=_f(r.get('RET_10D')); ret20=_f(r.get('RET_20D')); res=_f(r.get('PRIOR_HIGH20')); hi52=_f(r.get('HIGH_52W')); vol=_f(r.get('VOL_RATIO'))
    ext=_pct(close,e20); dist=_pct(res,close)
    score=0
    if np.isfinite(dist): score += 28 if 0<=dist<=2 else 20 if dist<=4 else 6 if dist<=7 else 0
    if np.isfinite(ext): score += 22 if -1<=ext<=2.5 else 14 if ext<=4 else 0
    if np.isfinite(ret5): score += 18 if -3<=ret5<=3 else 10 if ret5<=6 else 0
    if np.isfinite(ret10): score += 10 if -5<=ret10<=6 else 5 if ret10<=10 else 0
    if np.isfinite(ret20): score += 12 if ret20<=15 else 5 if ret20<=18 else 0
    if np.isfinite(vol): score += 10 if vol<=1.2 else 0
    score=int(max(0,min(100,score)))
    chase=(np.isfinite(ext) and ext>4) or (np.isfinite(ret20) and ret20>18)
    upside_to_52=_pct(hi52,close) if np.isfinite(hi52) else np.nan
    return {'timing':score,'extension':ext,'res_distance':dist,'chase':chase,'atr':atr,'res':res,'hi52':hi52,'ret5':ret5,'ret20':ret20,'up52':upside_to_52}


def apply_v3(base: Dict, hist: pd.DataFrame) -> Dict:
    out=dict(base)
    sym=str(out.get('SYMBOL','')).strip().upper()
    g=hist[hist.SYMBOL.astype(str).str.upper().eq(sym)].sort_values('DATE')
    if g.empty:return out
    f=_timing_features(g); base_score=_f(out.get('HUNTER_SCORE'),0); timing=f['timing']
    opportunity=round(0.64*base_score+0.36*timing,1)
    action=str(out.get('ACTION','WATCH'))
    if f['chase']:
        action='AVOID / CHASE'
    elif action=='PRE-BREAKOUT BUY' and opportunity>=80 and timing>=65:
        action='PRE-BREAKOUT BUY'
    elif action=='BREAKOUT BUY' and opportunity>=80 and timing>=65:
        action='BREAKOUT BUY'
    elif action=='SWING BUY' and opportunity>=80 and timing>=60 and (np.isfinite(f['ret5']) and f['ret5']<=3):
        action='SWING BUY'
    elif action in ACTIONABLE:
        action='WATCH'
    entry=_f(out.get('ENTRY_PRICE')) or _f(out.get('CMP'))
    trigger=_f(out.get('BREAKOUT_TRIGGER'))
    if action=='BREAKOUT BUY' and np.isfinite(trigger): entry=trigger
    elif action=='SWING BUY':
        e20=_f(g.iloc[-1].get('EMA20')); entry=min(entry,e20*1.01) if np.isfinite(e20) and np.isfinite(entry) else entry
    if action=='PRE-BREAKOUT BUY' and np.isfinite(trigger): max_buy=min(entry*1.015,trigger*0.997)
    else:max_buy=entry*1.015 if np.isfinite(entry) else np.nan
    atr=f['atr']; stop=_f(out.get('STOP_LOSS'))
    if np.isfinite(entry) and np.isfinite(atr) and atr>0:stop=entry-1.6*atr
    risk_pct=(entry-stop)/entry*100 if np.isfinite(entry) and np.isfinite(stop) and entry else np.nan
    ts=_target_levels(entry,atr,f['res'],f['hi52'])
    if ts:
        t1,t2,t3=ts
        out.update(TARGET_1=round(t1,2),TARGET_2=round(t2,2),TARGET_3=round(t3,2))
    out.update(ACTION=action,CATEGORY={'PRE-BREAKOUT BUY':'PRE-BREAKOUT','BREAKOUT BUY':'BREAKOUT','SWING BUY':'SWING','AVOID / CHASE':'AVOID'}.get(action,'WATCH'),NEXT_DAY_ACTION='BUY' if action in ACTIONABLE else 'WATCH',STAGE=action,BUY_DATE=(pd.Timestamp(r.DATE)+pd.tseries.offsets.BDay(1)).strftime('%d-%b-%Y') if action in ACTIONABLE else '',HUNTER_SCORE=opportunity,V3_TIMING_SCORE=timing,V3_OPPORTUNITY_SCORE=opportunity,ENTRY_TIMING='EARLY' if timing>=75 and not f['chase'] else 'ACCEPTABLE' if timing>=55 and not f['chase'] else 'LATE/CHASE',USER_ACTION=HUMAN_ACTIONS.get(action,HUMAN_ACTIONS['WATCH']),IDEAL_ENTRY=round(entry,2) if np.isfinite(entry) else '',BUY_ZONE=(f'{entry*0.99:.2f} - {entry*1.01:.2f}' if np.isfinite(entry) else ''),MAX_BUY_PRICE=round(max_buy,2) if np.isfinite(max_buy) else '',EXTENSION_PCT=_safe_percent(f['extension']),RESISTANCE_DISTANCE_PCT=_safe_percent(f['res_distance']),UPSIDE_TO_52W_HIGH_PCT=_safe_percent(f['up52']),RISK_PCT=_safe_percent(risk_pct))
    if ts:
        out['UPSIDE_EXPECTED_PCT']=round((t2/entry-1)*100,2)
        out['UPSIDE_BEST_CASE_PCT']=round((t3/entry-1)*100,2)
        out['CHANCE_PLUS10_PCT']=round(max(5,min(95,45+opportunity*0.5)),1)
        out['CHANCE_PLUS20_PCT']=round(max(3,min(90,out['CHANCE_PLUS10_PCT']-10)),1)
        out['CHANCE_PLUS30_PCT']=round(max(2,min(80,out['CHANCE_PLUS10_PCT']-20)),1)
        out['CHANCE_PLUS50_PCT']=round(max(1,min(65,out['CHANCE_PLUS10_PCT']-35)),1)
        out['BREAKOUT_CHANCE_PCT']=round(max(5,min(95,40+0.55*opportunity)),1)
    why=[]
    if f['chase']:why.append('Price already stretched — chase risk')
    if np.isfinite(f['res_distance']) and 0<=f['res_distance']<=4:why.append('Resistance ke paas')
    if str(out.get('VOLUME_EXPANSION',''))=='YES':why.append('Volume expansion')
    if str(out.get('VOLUME_DRYUP',''))=='YES':why.append('Volume dry-up')
    if str(out.get('DELIVERY','')).startswith('STRONG'):why.append('Delivery improving')
    if str(out.get('RELATIVE_STRENGTH','')) in {'STRONG','POSITIVE'}:why.append('Relative strength positive')
    out['WHY']=' | '.join(why)
    return out


def install():
    # Kept for backward compatibility. V3 is now applied explicitly by v3_runner.
    return True

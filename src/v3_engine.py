from __future__ import annotations
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

def _timing_features(g):
    g=g.sort_values('DATE').reset_index(drop=True); r=g.iloc[-1]
    close=_f(r.get('CLOSE_PRICE')); e20=_f(r.get('EMA20')); atr=_f(r.get('ATR14')); ret5=_f(r.get('RET_5D')); ret10=_f(r.get('RET_10D')); ret20=_f(r.get('RET_20D')); res=_f(r.get('PRIOR_HIGH20')); hi52=_f(r.get('HIGH_52W')); vol=_f(r.get('VOL_RATIO'))
    ext=_pct(close,e20); dist=_pct(res,close); score=0
    if np.isfinite(dist): score += 28 if 0<=dist<=2 else 20 if dist<=4 else 6 if dist<=7 else 0
    if np.isfinite(ext): score += 22 if -1<=ext<=2.5 else 14 if ext<=4 else 0
    if np.isfinite(ret5): score += 18 if -3<=ret5<=3 else 10 if ret5<=6 else 0
    if np.isfinite(ret10): score += 10 if -5<=ret10<=6 else 5 if ret10<=10 else 0
    if np.isfinite(ret20): score += 12 if ret20<=15 else 5 if ret20<=18 else 0
    if np.isfinite(vol): score += 10 if vol<=1.2 else 0
    score=int(max(0,min(100,score)))
    chase=(np.isfinite(ext) and ext>4) or (np.isfinite(ret20) and ret20>18)
    return {'timing':score,'extension':ext,'res_distance':dist,'chase':chase,'atr':atr,'res':res,'hi52':hi52,'ret5':ret5,'ret20':ret20,'up52':_pct(hi52,close) if np.isfinite(hi52) else np.nan}

def apply_v3(base: Dict, hist: pd.DataFrame) -> Dict:
    """Add timing metadata without inventing a second price model.

    Entry/stop/targets are deliberately preserved from strategy.py, whose
    formulas are the ones covered by backtest.py. V3 may downgrade the action
    because of timing/chase conditions, but it must never silently replace the
    backtested trade levels with an unvalidated formula.
    """
    out=dict(base); sym=str(out.get('SYMBOL','')).strip().upper()
    g=hist[hist.SYMBOL.astype(str).str.upper().eq(sym)].sort_values('DATE')
    if g.empty:return out
    f=_timing_features(g); base_score=_f(out.get('HUNTER_SCORE'),0); timing=f['timing']; opportunity=round(0.64*base_score+0.36*timing,1)
    action=str(out.get('ACTION','WATCH'))
    if f['chase']: action='AVOID / CHASE'
    elif action=='PRE-BREAKOUT BUY' and opportunity<80: action='WATCH'
    elif action=='BREAKOUT BUY' and opportunity<80: action='WATCH'
    elif action=='SWING BUY' and (opportunity<80 or not (np.isfinite(f['ret5']) and f['ret5']<=3)): action='WATCH'
    last_date=g.iloc[-1].get('DATE')
    entry=_f(out.get('IDEAL_ENTRY',out.get('ENTRY_PRICE',out.get('CMP')))); stop=_f(out.get('STOP_LOSS')); t1=_f(out.get('TARGET_1')); t2=_f(out.get('TARGET_2')); t3=_f(out.get('TARGET_3'))
    risk_pct=(entry-stop)/entry*100 if np.isfinite(entry) and np.isfinite(stop) and entry else np.nan
    if np.isfinite(entry) and np.isfinite(stop): out['RISK_PCT']=round(risk_pct,2)
    if np.isfinite(entry) and np.isfinite(stop) and np.isfinite(t2) and entry>stop: out['UPSIDE_EXPECTED_PCT']=round((t2/entry-1)*100,2)
    if np.isfinite(entry) and np.isfinite(t3) and entry>0: out['UPSIDE_BEST_CASE_PCT']=round((t3/entry-1)*100,2)
    out.update(ACTION=action,CATEGORY={'PRE-BREAKOUT BUY':'PRE-BREAKOUT','BREAKOUT BUY':'BREAKOUT','SWING BUY':'SWING','AVOID / CHASE':'AVOID'}.get(action,'WATCH'),NEXT_DAY_ACTION='BUY' if action in ACTIONABLE else 'WATCH',STAGE=action,BUY_DATE=(pd.Timestamp(last_date)+pd.tseries.offsets.BDay(1)).strftime('%d-%b-%Y') if action in ACTIONABLE else '',HUNTER_SCORE=opportunity,V3_TIMING_SCORE=timing,V3_OPPORTUNITY_SCORE=opportunity,ENTRY_TIMING='EARLY' if timing>=75 and not f['chase'] else 'ACCEPTABLE' if timing>=55 and not f['chase'] else 'LATE/CHASE',USER_ACTION=HUMAN_ACTIONS.get(action,HUMAN_ACTIONS['WATCH']),EXTENSION_PCT=round(f['extension'],2) if np.isfinite(f['extension']) else '',RESISTANCE_DISTANCE_PCT=round(f['res_distance'],2) if np.isfinite(f['res_distance']) else '',UPSIDE_TO_52W_HIGH_PCT=round(f['up52'],2) if np.isfinite(f['up52']) else '')
    if np.isfinite(entry) and entry>0:
        out['BUY_ZONE']=out.get('BUY_ZONE') or f'{entry*0.99:.2f} - {entry*1.01:.2f}'
        out['MAX_BUY_PRICE']=out.get('MAX_BUY_PRICE') or round(entry*1.015,2)
    out['BREAKOUT_CHANCE_PCT']=round(max(5,min(95,40+0.55*opportunity)),1)
    out['CHANCE_PLUS10_PCT']=round(max(5,min(95,45+opportunity*0.5)),1)
    out['CHANCE_PLUS20_PCT']=round(max(3,min(90,out['CHANCE_PLUS10_PCT']-10)),1)
    out['CHANCE_PLUS30_PCT']=round(max(2,min(80,out['CHANCE_PLUS10_PCT']-20)),1)
    out['CHANCE_PLUS50_PCT']=round(max(1,min(65,out['CHANCE_PLUS10_PCT']-35)),1)
    why=[]
    if f['chase']: why.append('Price already stretched — chase risk')
    if np.isfinite(f['res_distance']) and 0<=f['res_distance']<=4: why.append('Resistance ke paas')
    if str(out.get('VOLUME_EXPANSION',''))=='YES': why.append('Volume expansion')
    if str(out.get('VOLUME_DRYUP',''))=='YES': why.append('Volume dry-up')
    if str(out.get('DELIVERY','')).startswith('STRONG'): why.append('Delivery improving')
    if str(out.get('RELATIVE_STRENGTH','')) in {'STRONG','POSITIVE'}: why.append('Relative strength positive')
    out['WHY']=' | '.join(why)
    return out

def install():
    return True

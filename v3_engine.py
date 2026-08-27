from __future__ import annotations
import numpy as np
import pandas as pd

_INSTALLED=False
_ORIGINAL=None


def _num(g,c):
    if c not in g.columns: return pd.Series(np.nan,index=g.index,dtype=float)
    return pd.to_numeric(g[c],errors='coerce')


def _f(x):
    try:
        x=float(x); return x if np.isfinite(x) else np.nan
    except Exception: return np.nan


def _timing(g):
    g=g.sort_values('DATE').reset_index(drop=True)
    r=g.iloc[-1]; c=_num(g,'CLOSE_PRICE'); h=_num(g,'HIGH_PRICE')
    close=_f(r.get('CLOSE_PRICE')); e20=_f(r.get('EMA20')); atr=_f(r.get('ATR14')); vol=_f(r.get('VOL_RATIO'))
    prior=_f(r.get('PRIOR_HIGH20'))
    if not np.isfinite(prior) and len(g)>=20: prior=_f(h.iloc[-20:].max())
    ext=((close/e20)-1)*100 if np.isfinite(close) and np.isfinite(e20) and e20 else np.nan
    dist=((prior-close)/close)*100 if np.isfinite(prior) and close else np.nan
    ret5=_f(r.get('RET_5D')); ret20=_f(r.get('RET_20D'))
    score=0
    if np.isfinite(dist): score += 25 if 0<=dist<=2 else 15 if dist<=4 else 0
    if np.isfinite(ext): score += 20 if ext<=2 else 10 if ext<=4 else 0
    if np.isfinite(ret5): score += 20 if -2<=ret5<=3 else 10 if ret5<=6 else 0
    if np.isfinite(ret20): score += 15 if ret20<=12 else 5 if ret20<=18 else 0
    if np.isfinite(vol): score += 10 if vol<=1.15 else 0
    gap_risk=False
    if np.isfinite(atr) and np.isfinite(close) and np.isfinite(prior):
        gap_risk=(close-prior) > max(0.0,0.75*atr)
    if gap_risk: score-=20
    score=int(max(0,min(100,score)))
    late=(np.isfinite(ext) and ext>4) or (np.isfinite(ret20) and ret20>18) or gap_risk
    return score,late


def _v3_analyze(g,min_score=None,market=None):
    out=_ORIGINAL(g,min_score=min_score,market=market)
    if out is None: return None
    timing,late=_timing(g)
    base=float(out.get('HUNTER_SCORE',0) or 0)
    opportunity=round(0.68*base+0.32*timing,2)
    action=str(out.get('ACTION','WATCH'))
    qualified=action in {'PRE-BREAKOUT BUY','BREAKOUT BUY','SWING BUY'} and opportunity>=78 and not late
    out['V3_TIMING_SCORE']=timing
    out['V3_OPPORTUNITY_SCORE']=opportunity
    out['ENTRY_TIMING']='EARLY' if timing>=75 and not late else 'ACCEPTABLE' if timing>=55 and not late else 'LATE/CHASE'
    out['V3_STATUS']='QUALIFIED' if qualified else 'WAIT'
    if action in {'PRE-BREAKOUT BUY','BREAKOUT BUY','SWING BUY'} and not qualified:
        out['ACTION']='WATCH'
        out['CATEGORY']='WATCH'
        out['NEXT_DAY_ACTION']='WATCH'
        out['STAGE']='WATCH'
        out['BUY_DATE']=''
    out['HUNTER_SCORE']=opportunity
    out['NEXT_DAY_SETUP_SCORE']=max(float(out.get('NEXT_DAY_SETUP_SCORE',0) or 0),timing)
    conf=float(out.get('BREAKOUT_PROBABILITY',0) or 0)
    out['BREAKOUT_CONFIDENCE']=int(max(0,min(90,round(0.7*conf+0.3*timing))))
    out['BREAKOUT_PROBABILITY']=out['BREAKOUT_CONFIDENCE']
    return out


def install():
    global _INSTALLED,_ORIGINAL
    if _INSTALLED: return
    import strategy
    _ORIGINAL=strategy.analyze_stock
    strategy.analyze_stock=_v3_analyze
    _INSTALLED=True

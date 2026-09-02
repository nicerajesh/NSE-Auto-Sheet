from __future__ import annotations
import math
from typing import Dict, Tuple
import numpy as np
import pandas as pd

BUY_NOW = '🟢 ABHI KHARIDO'
BUY_BREAKOUT = '🟡 BREAKOUT KE UPAR KHARIDO'
BUY_DIP = '🔵 GIRAVAT MEIN KHARIDO'
WAIT = '⚪ ABHI WAIT KARO'
AVOID = '🔴 ABHI MAT KHARIDO'


def _f(x):
    try:
        x = float(x)
        return x if math.isfinite(x) else np.nan
    except Exception:
        return np.nan


def _pct(a, b):
    a, b = _f(a), _f(b)
    return (a / b - 1.0) * 100 if np.isfinite(a) and np.isfinite(b) and b else np.nan


def _prob_from_score(score: float, edge: float = 0.0) -> float:
    # Bounded model estimate, intentionally not presented as certainty.
    s = max(0.0, min(100.0, _f(score, 0.0)))
    return max(5.0, min(95.0, 40.0 + 0.55 * (s - 60.0) + edge))


def _future_upside(entry: float, atr: float, resistance: float, high52: float) -> Dict[str, float]:
    if not np.isfinite(entry) or entry <= 0:
        return {}
    a = atr if np.isfinite(atr) and atr > 0 else entry * 0.025
    candidates = [entry + 2.5*a, entry + 4.0*a, entry + 6.0*a]
    if np.isfinite(resistance) and resistance > entry:
        candidates.append(resistance * 1.08)
    if np.isfinite(high52) and high52 > entry:
        candidates.append(high52 * 1.03)
    vals = sorted(set(round(max(entry, x), 4) for x in candidates if np.isfinite(x)))
    if not vals:
        return {}
    t1, t2, t3 = vals[0], vals[min(1, len(vals)-1)], vals[min(2, len(vals)-1)]
    return {'TARGET_1': t1, 'TARGET_2': t2, 'TARGET_3': t3,
            'UPSIDE_T1_PCT': (t1/entry-1)*100, 'UPSIDE_T2_PCT': (t2/entry-1)*100,
            'UPSIDE_T3_PCT': (t3/entry-1)*100}


def enrich_signal(row: Dict, hist: pd.DataFrame) -> Dict:
    out = dict(row)
    symbol = str(out.get('SYMBOL', ''))
    g = hist[hist['SYMBOL'].astype(str).str.upper().eq(symbol.upper())].sort_values('DATE').copy()
    if g.empty:
        return out
    r = g.iloc[-1]
    close = _f(r.get('CLOSE_PRICE'))
    ema20 = _f(r.get('EMA20'))
    ema50 = _f(r.get('EMA50'))
    atr = _f(r.get('ATR14'))
    r20 = _f(r.get('RET_20D'))
    r5 = _f(r.get('RET_5D'))
    resistance = _f(r.get('PRIOR_HIGH20'))
    high52 = _f(r.get('HIGH_52W'))
    breakout = str(out.get('BREAKOUT_STATUS', '')) == 'CONFIRMED'
    base_action = str(out.get('ACTION', WAIT))

    extension = _pct(close, ema20)
    dist_res = _pct(resistance, close)
    fresh = (not np.isfinite(extension) or extension <= 3.5) and (not np.isfinite(r20) or r20 <= 15)
    deep_chase = (np.isfinite(extension) and extension > 5.0) or (np.isfinite(r20) and r20 > 20)

    # Reclassify action based on actual entry quality, not just setup quality.
    if deep_chase:
        action = AVOID
    elif base_action == 'BREAKOUT BUY' and not fresh:
        action = BUY_BREAKOUT
    elif base_action == 'SWING BUY' and fresh and (np.isfinite(r5) and -8 <= r5 <= 1.5):
        action = BUY_DIP
    elif base_action == 'SWING BUY' and not fresh:
        action = WAIT
    elif base_action == 'PRE-BREAKOUT BUY' and breakout:
        action = BUY_BREAKOUT
    elif base_action == 'PRE-BREAKOUT BUY':
        action = BUY_NOW if fresh else WAIT
    elif base_action == 'BREAKOUT BUY':
        action = BUY_NOW if fresh else BUY_BREAKOUT
    else:
        action = base_action

    # Entry plan
    entry = close
    trigger = _f(out.get('BREAKOUT_TRIGGER'))
    if action == BUY_BREAKOUT and np.isfinite(trigger):
        entry = trigger
    if action == BUY_DIP and np.isfinite(ema20):
        entry = min(close, ema20 * 1.01)
    zone_low = entry * 0.99 if np.isfinite(entry) else np.nan
    zone_high = entry * 1.01 if np.isfinite(entry) else np.nan
    max_buy = entry * 1.015 if np.isfinite(entry) else np.nan

    if np.isfinite(atr) and atr > 0 and np.isfinite(entry):
        stop = entry - 1.6 * atr
    else:
        stop = _f(out.get('STOP_LOSS'))
    if not np.isfinite(stop) and np.isfinite(entry):
        stop = entry * 0.95
    risk_pct = (entry-stop)/entry*100 if np.isfinite(entry) and np.isfinite(stop) and entry else np.nan

    targets = _future_upside(entry, atr, resistance, high52)
    for k,v in targets.items(): out[k]=round(v,2)
    out['STOP_LOSS']=round(stop,2) if np.isfinite(stop) else out.get('STOP_LOSS')  # keep in sync with the (possibly re-planned) IDEAL_ENTRY below, not the original scanner-time stop
    out['RISK_PCT']=round(risk_pct,2) if np.isfinite(risk_pct) else ''
    out['IDEAL_ENTRY']=round(entry,2) if np.isfinite(entry) else ''
    out['BUY_ZONE']=f'{zone_low:.2f} - {zone_high:.2f}' if np.isfinite(zone_low) and np.isfinite(zone_high) else ''
    out['MAX_BUY_PRICE']=round(max_buy,2) if np.isfinite(max_buy) else ''
    out['ACTION']=action
    out['USER_ACTION'] = action
    out['ENTRY_TIMING']='EARLY' if fresh and not deep_chase else 'LATE' if deep_chase else 'WAIT'
    out['EXTENSION_PCT']=round(extension,2) if np.isfinite(extension) else ''
    out['UPSIDE_EXPECTED_PCT']=round(targets.get('UPSIDE_T2_PCT', np.nan),2) if targets else ''
    out['UPSIDE_BEST_CASE_PCT']=round(targets.get('UPSIDE_T3_PCT', np.nan),2) if targets else ''
    base_conf=_f(out.get('BREAKOUT_PROBABILITY'))
    if not np.isfinite(base_conf): base_conf=50
    timing_edge=10 if fresh else -20 if deep_chase else 0
    out['BREAKOUT_MODEL_SCORE_PCT']=round(_prob_from_score(base_conf, timing_edge),1)
    out['BREAKOUT_CHANCE_PCT']=''  # never expose a score-derived estimate as probability

    # Multi-level probability-style bands: historical/model estimates, not guarantees.
    chance=out.get('BREAKOUT_MODEL_SCORE_PCT', 0)
    out['CHANCE_PLUS10_PCT']=round(min(95,max(5,chance)),1)
    out['CHANCE_PLUS20_PCT']=round(min(90,max(3,chance-10)),1)
    out['CHANCE_PLUS30_PCT']=round(min(80,max(2,chance-20)),1)
    out['CHANCE_PLUS50_PCT']=round(min(65,max(1,chance-35)),1)

    reason=[]
    if fresh: reason.append('Entry abhi over-extended nahi hai')
    if np.isfinite(dist_res) and 0 <= dist_res <= 4: reason.append('Resistance ke paas')
    if str(out.get('VOLUME_EXPANSION','')) == 'YES': reason.append('Volume expansion')
    if str(out.get('VOLUME_DRYUP','')) == 'YES': reason.append('Base me volume dry-up')
    if str(out.get('DELIVERY','')).startswith('STRONG'): reason.append('Delivery strong/improving')
    if str(out.get('RELATIVE_STRENGTH','')) in {'STRONG','POSITIVE'}: reason.append('Relative strength positive')
    if deep_chase: reason.append('Price already over-extended — chase risk')
    out['WHY']= ' | '.join(reason)
    return out


def classify_portfolio(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    x=df.copy()
    priority={BUY_NOW:1, BUY_BREAKOUT:2, BUY_DIP:3, WAIT:4, AVOID:5,
              'PRE-BREAKOUT BUY':1,'BREAKOUT BUY':2,'SWING BUY':3,'WATCH':4,'AVOID / CHASE':5}
    x['_PRIORITY']=x['ACTION'].map(priority).fillna(9)
    x['_UPSIDE']=pd.to_numeric(x.get('UPSIDE_EXPECTED_PCT',0),errors='coerce').fillna(0)
    x=x.sort_values(['_PRIORITY','_UPSIDE'],ascending=[True,False]).reset_index(drop=True)
    x.insert(0,'RANK',range(1,len(x)+1))
    return x.drop(columns=['_PRIORITY','_UPSIDE'],errors='ignore')

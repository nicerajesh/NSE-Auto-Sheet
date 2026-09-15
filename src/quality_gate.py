import ast
import json
import re
import pandas as pd
from config import BT


def parse_action_stats(stats):
    """Restore action_stats after CSV serialization, including legacy NaN tokens."""
    v=(stats or {}).get('action_stats')
    if isinstance(v,list):
        return v
    if not isinstance(v,str):
        return []
    text=v.strip()
    if not text or text.lower() in {'nan','none','null'}:
        return []
    candidates=[text,
                re.sub(r'\b(?:NaN|nan|Infinity|-Infinity)\b','null',text),
                re.sub(r'\b(?:NaN|nan|Infinity|-Infinity)\b','None',text)]
    for candidate in candidates:
        for parser in (json.loads, ast.literal_eval):
            try:
                parsed=parser(candidate)
                if isinstance(parsed,list) and all(isinstance(x,dict) for x in parsed):
                    return parsed
            except Exception:
                pass
    return []


EDGE_REASONS={'LOW_PROFIT_FACTOR','NEGATIVE_MEDIAN_RETURN','LOW_WIN_RATE'}


def evaluate_action(row,min_trades=None):
    """Evaluate one action using its own historical sample; never lower thresholds."""
    required=BT.min_quality_trades if min_trades is None else int(min_trades)
    if not row or int(row.get('trades',0) or 0)<required:return False,'INSUFFICIENT_ACTION_TRADES'
    pf=float(row.get('profit_factor',0) or 0)
    median=float(row.get('median_return_pct',0) or 0)
    win=float(row.get('win_rate_pct',0) or 0)
    if pf<BT.min_quality_profit_factor:return False,'LOW_PROFIT_FACTOR'
    if median<=0:return False,'NEGATIVE_MEDIAN_RETURN'
    if win<BT.min_quality_win_rate:return False,'LOW_WIN_RATE'
    return True,'PASS'


def _validate_walk_forward():
    """Require real walk-forward evidence before any BUY release.

    A missing/empty summary is a hard failure.  At least 60% of judgeable
    windows must meet the core edge thresholds, and the most recent judgeable
    window must also pass.  This prevents a strong old period from masking a
    current regime failure.
    """
    from pathlib import Path
    wf_path=Path('output')/'walk_forward_summary.csv'
    if not wf_path.exists():
        return False,'MISSING_WALK_FORWARD_SUMMARY'
    try:
        wf=pd.read_csv(wf_path)
        required={'trades','profit_factor','median_return_pct','win_rate_pct','expectancy_pct'}
        if wf.empty or not required.issubset(wf.columns):
            return False,'MISSING_WALK_FORWARD_METRICS'
        for c in required:
            wf[c]=pd.to_numeric(wf[c],errors='coerce')
        eligible=wf[wf['trades']>=max(5,BT.min_oos_trades//10)].dropna(subset=['profit_factor','median_return_pct','win_rate_pct','expectancy_pct'])
        if eligible.empty:
            return False,'ALL_WALK_FORWARD_WINDOWS_TOO_THIN'
        passing=eligible[(eligible.profit_factor>=BT.min_quality_profit_factor)&
                         (eligible.median_return_pct>0)&
                         (eligible.win_rate_pct>=BT.min_oos_win_rate)&
                         (eligible.expectancy_pct>BT.min_oos_expectancy_pct)]
        pass_frac=len(passing)/len(eligible)
        if pass_frac<0.60:
            return False,f'INCONSISTENT_ACROSS_WINDOWS_{round(pass_frac*100,0)}PCT'
        latest=eligible.iloc[-1]
        if not (latest.profit_factor>=BT.min_oos_profit_factor and
                latest.median_return_pct>0 and
                latest.win_rate_pct>=BT.min_oos_win_rate and
                latest.expectancy_pct>BT.min_oos_expectancy_pct):
            return False,'LATEST_WALK_FORWARD_WINDOW_FAILED'
        return True,'PASS'
    except Exception:
        return False,'WALK_FORWARD_VALIDATION_ERROR'


def evaluate(stats,calibration=None,min_trades=None):
    """Release BUYs only when aggregate edge, calibration and OOS consistency pass."""
    required_trades=BT.min_quality_trades if min_trades is None else int(min_trades)
    if not stats or int(stats.get('trades',0) or 0)<required_trades:return False,'INSUFFICIENT_BACKTEST'
    pf=float(stats.get('profit_factor',0) or 0);median=float(stats.get('median_return_pct',0) or 0);win=float(stats.get('win_rate_pct',0) or 0)
    t1=float(stats.get('t1_hit_pct',0) or 0);t2=float(stats.get('t2_hit_pct',0) or 0);t3=float(stats.get('t3_hit_pct',0) or 0)
    if t2>t1+1e-9 or t3>t2+1e-9:return False,'INVALID_TARGET_CALIBRATION'
    if pf<BT.min_quality_profit_factor:return False,'LOW_PROFIT_FACTOR'
    if median<=0:return False,'NEGATIVE_MEDIAN_RETURN'
    if win<BT.min_quality_win_rate:return False,'LOW_WIN_RATE'
    if calibration is None or calibration.empty:return False,'MISSING_CALIBRATION'
    if 'ANALYSIS' not in calibration.columns:return False,'MISSING_CALIBRATION_ANALYSIS'
    q=calibration.copy();event=q[q['ANALYSIS'].eq('BREAKOUT_EVENT')]
    if event.empty or int(pd.to_numeric(event.TRADES,errors='coerce').fillna(0).sum())<BT.probability_min_samples:return False,'INSUFFICIENT_BREAKOUT_EVENT_SAMPLES'
    pre=event[event.ACTION.astype(str).str.contains('PRE-BREAKOUT',na=False)].copy()
    if pre.empty or int(pd.to_numeric(pre.TRADES,errors='coerce').fillna(0).sum())<BT.probability_min_samples:return False,'INSUFFICIENT_PRE_BREAKOUT_SAMPLES'
    weighted=float(pre.BREAKOUT_RATE.mul(pre.TRADES).sum()/max(1,pre.TRADES.sum()))
    if weighted<35:return False,'LOW_PRE_BREAKOUT_HIT_RATE'
    trade_q=q[q['ANALYSIS'].eq('TRADE_SCORE')].copy()
    if not trade_q.empty:
        trade_q['TRADES']=pd.to_numeric(trade_q['TRADES'],errors='coerce')
        trade_q['AVG_RETURN']=pd.to_numeric(trade_q['AVG_RETURN'],errors='coerce')
        core=trade_q[(trade_q.TRADES>=5)&trade_q.SCORE_BUCKET.astype(str).eq('82-89')]
        if not core.empty and float(core.AVG_RETURN.mean())<=0:return False,'CORE_SCORE_BAND_NEGATIVE'
    wf_ok,wf_reason=_validate_walk_forward()
    if not wf_ok:return False,wf_reason
    return True,'PASS'

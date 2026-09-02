import ast
import pandas as pd
from config import BT


def parse_action_stats(stats):
    """stats['action_stats'] is a list of dicts in memory, but after a CSV
    round-trip (backtest_summary.csv) pandas stores it as a stringified repr.
    Always go through this before iterating action_stats."""
    v=(stats or {}).get('action_stats')
    if isinstance(v,list):return v
    if isinstance(v,str) and v.strip():
        try:
            parsed=ast.literal_eval(v)
            return parsed if isinstance(parsed,list) else []
        except Exception:return []
    return []


EDGE_REASONS={'LOW_PROFIT_FACTOR','NEGATIVE_MEDIAN_RETURN','LOW_WIN_RATE'}


def evaluate_action(row,min_trades=None):
    """Core numeric gate (trades/PF/median/win-rate) scoped to ONE action's own trade
    sample. Used only as a fallback when the aggregate gate fails for an edge-quality
    reason — lets a genuinely edge-positive action publish even if a different,
    higher-volume action (typically SWING BUY) is dragging the blended average down."""
    required=BT.min_quality_trades if min_trades is None else int(min_trades)
    if not row or int(row.get('trades',0) or 0)<required:return False,'INSUFFICIENT_ACTION_TRADES'
    pf=float(row.get('profit_factor',0) or 0);median=float(row.get('median_return_pct',0) or 0);win=float(row.get('win_rate_pct',0) or 0)
    if pf<BT.min_quality_profit_factor:return False,'LOW_PROFIT_FACTOR'
    if median<=0:return False,'NEGATIVE_MEDIAN_RETURN'
    if win<BT.min_quality_win_rate:return False,'LOW_WIN_RATE'
    return True,'PASS'


def evaluate(stats,calibration=None,min_trades=None):
    """Release BUYs only when overall trading performance and pre-breakout event calibration pass."""
    required_trades=BT.min_quality_trades if min_trades is None else int(min_trades)
    if not stats or int(stats.get('trades',0) or 0)<required_trades:return False,'INSUFFICIENT_BACKTEST'
    pf=float(stats.get('profit_factor',0) or 0);median=float(stats.get('median_return_pct',0) or 0);win=float(stats.get('win_rate_pct',0) or 0)
    t1=float(stats.get('t1_hit_pct',0) or 0);t2=float(stats.get('t2_hit_pct',0) or 0);t3=float(stats.get('t3_hit_pct',0) or 0)
    if t2>t1+1e-9 or t3>t2+1e-9:return False,'INVALID_TARGET_CALIBRATION'
    if pf<BT.min_quality_profit_factor:return False,'LOW_PROFIT_FACTOR'
    if median<=0:return False,'NEGATIVE_MEDIAN_RETURN'
    if win<BT.min_quality_win_rate:return False,'LOW_WIN_RATE'
    if calibration is None or calibration.empty:return False,'MISSING_CALIBRATION'
    q=calibration.copy();event=q[q['ANALYSIS'].eq('BREAKOUT_EVENT')] if 'ANALYSIS' in q.columns else pd.DataFrame()
    if event.empty or int(event.TRADES.sum())<BT.probability_min_samples:return False,'INSUFFICIENT_BREAKOUT_EVENT_SAMPLES'
    pre=event[event.ACTION.astype(str).str.contains('PRE-BREAKOUT',na=False)].copy()
    if pre.empty or int(pre.TRADES.sum())<BT.probability_min_samples:return False,'INSUFFICIENT_PRE_BREAKOUT_SAMPLES'
    weighted=float(pre.BREAKOUT_RATE.mul(pre.TRADES).sum()/max(1,pre.TRADES.sum()))
    if weighted<35:return False,'LOW_PRE_BREAKOUT_HIT_RATE'
    trade_q=q[q['ANALYSIS'].eq('TRADE_SCORE')] if 'ANALYSIS' in q.columns else pd.DataFrame();trade_q=trade_q[trade_q.TRADES>=5].copy()
    if not trade_q.empty and {'ACTION','SCORE_BUCKET','AVG_RETURN'}.issubset(trade_q.columns):
        core=trade_q[trade_q.SCORE_BUCKET.astype(str).eq('82-89')]
        if not core.empty and float(core.AVG_RETURN.mean())<=0:return False,'CORE_SCORE_BAND_NEGATIVE'
    # V2: if a walk-forward summary is present, aggregate in-sample quality is
    # not enough. Require positive OOS expectancy and minimum OOS PF/win-rate.
    try:
        from pathlib import Path
        wf_path=Path('output')/'walk_forward_summary.csv'
        if wf_path.exists():
            wf=pd.read_csv(wf_path)
            if not wf.empty:
                numeric=lambda c: pd.to_numeric(wf[c],errors='coerce') if c in wf.columns else pd.Series(dtype=float)
                pf=numeric('profit_factor').dropna()
                wr=numeric('win_rate_pct').dropna()
                ex=numeric('expectancy_pct').dropna()
                if pf.empty or wr.empty or ex.empty:return False,'MISSING_OOS_METRICS'
                if float(pf.median())<BT.min_oos_profit_factor:return False,'LOW_OOS_PROFIT_FACTOR'
                if float(wr.median())<BT.min_oos_win_rate:return False,'LOW_OOS_WIN_RATE'
                if float(ex.median())<=BT.min_oos_expectancy_pct:return False,'NON_POSITIVE_OOS_EXPECTANCY'
    except Exception:
        return False,'OOS_VALIDATION_ERROR'
    return True,'PASS'

import pandas as pd
from config import BT


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
    return True,'PASS'

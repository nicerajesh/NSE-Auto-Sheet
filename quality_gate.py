from config import BT


def evaluate(stats,calibration=None,min_trades=None):
    """Strict quality gate: live BUYs are released only after a positive, calibrated backtest."""
    required_trades=BT.min_quality_trades if min_trades is None else int(min_trades)
    if not stats or int(stats.get('trades',0) or 0)<required_trades:
        return False,'INSUFFICIENT_BACKTEST'
    pf=float(stats.get('profit_factor',0) or 0)
    median=float(stats.get('median_return_pct',0) or 0)
    win=float(stats.get('win_rate_pct',0) or 0)
    t1=float(stats.get('t1_hit_pct',0) or 0); t2=float(stats.get('t2_hit_pct',0) or 0); t3=float(stats.get('t3_hit_pct',0) or 0)
    if t2>t1+1e-9 or t3>t2+1e-9:
        return False,'INVALID_TARGET_CALIBRATION'
    if pf<BT.min_quality_profit_factor:return False,'LOW_PROFIT_FACTOR'
    if median<=0:return False,'NEGATIVE_MEDIAN_RETURN'
    if win<BT.min_quality_win_rate:return False,'LOW_WIN_RATE'
    if calibration is None or calibration.empty:return False,'MISSING_CALIBRATION'

    q=calibration.copy()
    if 'ANALYSIS' in q.columns:q=q[q.ANALYSIS.eq('SCORE_BUCKET')]
    q=q[q.TRADES>=5].copy()
    if not q.empty and {'SCORE_BUCKET','AVG_RETURN'}.issubset(q.columns):
        bands={str(r.SCORE_BUCKET):float(r.AVG_RETURN) for _,r in q.iterrows() if r.TRADES>=5 and r.AVG_RETURN==r.AVG_RETURN}
        if '82-89' in bands and bands['82-89']<=0:return False,'CORE_SCORE_BAND_NEGATIVE'
        if '82-89' in bands and '90+' in bands and bands['90+']<bands['82-89']-0.50:return False,'HIGH_SCORE_DEGRADES'

    if 'HORIZON_DAYS' in calibration.columns:
        h=calibration[calibration.ANALYSIS.eq('HORIZON')] if 'ANALYSIS' in calibration.columns else calibration
        h=h.dropna(subset=['HORIZON_DAYS']) if not h.empty else h
        h={int(float(r.HORIZON_DAYS)):float(r.AVG_RETURN) for _,r in h.iterrows() if r.AVG_RETURN==r.AVG_RETURN}
        if 20 in h and 30 in h and (h[20]<=0 or h[30]<=0):return False,'LONG_HORIZON_NEGATIVE'
    return True,'PASS'

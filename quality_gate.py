def evaluate(stats,calibration=None,min_trades=25):
    """Return system quality status; do not silently rewrite live signals."""
    if not stats or stats.get('trades',0)<min_trades:
        return False,'INSUFFICIENT_BACKTEST'
    pf=float(stats.get('profit_factor',0) or 0)
    median=float(stats.get('median_return_pct',0) or 0)
    win=float(stats.get('win_rate_pct',0) or 0)
    t1=float(stats.get('t1_hit_pct',0) or 0)
    t2=float(stats.get('t2_hit_pct',0) or 0)
    t3=float(stats.get('t3_hit_pct',0) or 0)
    # T3 is nested inside T2, which is nested inside T1. If this is violated,
    # the backtest accounting is invalid and must not be used as a quality signal.
    if t2>t1+1e-9 or t3>t2+1e-9:
        return False,'INVALID_TARGET_CALIBRATION'
    if pf<1.15:return False,'LOW_PROFIT_FACTOR'
    if median<=0:return False,'NEGATIVE_MEDIAN_RETURN'
    if win<42:return False,'LOW_WIN_RATE'
    if calibration is not None and not calibration.empty and {'TRADES','AVG_RETURN'}.issubset(calibration.columns):
        q=calibration[calibration.TRADES>=5]
        if 'ANALYSIS' in q.columns:q=q[q.ANALYSIS.eq('SCORE_BUCKET')]
        if len(q)>=2 and float(q.iloc[-1].AVG_RETURN)<float(q.iloc[0].AVG_RETURN):
            return False,'SCORE_NOT_MONOTONIC'
    return True,'PASS'

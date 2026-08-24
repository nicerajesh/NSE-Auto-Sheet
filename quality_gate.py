def evaluate(stats,calibration=None,min_trades=25):
    """Return system quality status; do not silently rewrite live signals."""
    if not stats or stats.get('trades',0)<min_trades:
        return False,'INSUFFICIENT_BACKTEST'
    pf=float(stats.get('profit_factor',0) or 0)
    median=float(stats.get('median_return_pct',0) or 0)
    win=float(stats.get('win_rate_pct',0) or 0)
    if pf<1.15:return False,'LOW_PROFIT_FACTOR'
    if median<=0:return False,'NEGATIVE_MEDIAN_RETURN'
    if win<42:return False,'LOW_WIN_RATE'
    if calibration is not None and not calibration.empty and {'TRADES','AVG_RETURN'}.issubset(calibration.columns):
        q=calibration[calibration.TRADES>=5]
        # Only evaluate score calibration rows, not horizon rows.
        if 'ANALYSIS' in q.columns:q=q[q.ANALYSIS.eq('SCORE_BUCKET')]
        if len(q)>=2 and float(q.iloc[-1].AVG_RETURN)<float(q.iloc[0].AVG_RETURN):
            return False,'SCORE_NOT_MONOTONIC'
    return True,'PASS'

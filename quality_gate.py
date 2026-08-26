import pandas as pd
from config import BT


def _f(v, default=0.0):
    try:
        x = float(v)
        return x if pd.notna(x) else default
    except Exception:
        return default


def evaluate(stats, calibration=None, min_trades=None):
    """Release BUYs only when overall performance and signal-specific calibration support them."""
    required_trades = BT.min_quality_trades if min_trades is None else int(min_trades)
    if not stats or int(stats.get('trades', 0) or 0) < required_trades:
        return False, 'INSUFFICIENT_BACKTEST'

    pf = _f(stats.get('profit_factor'))
    median = _f(stats.get('median_return_pct'))
    win = _f(stats.get('win_rate_pct'))
    t1 = _f(stats.get('t1_hit_pct'))
    t2 = _f(stats.get('t2_hit_pct'))
    t3 = _f(stats.get('t3_hit_pct'))

    if t2 > t1 + 1e-9 or t3 > t2 + 1e-9:
        return False, 'INVALID_TARGET_CALIBRATION'
    if pf < BT.min_quality_profit_factor:
        return False, 'LOW_PROFIT_FACTOR'
    if median <= 0:
        return False, 'NEGATIVE_MEDIAN_RETURN'
    if win < BT.min_quality_win_rate:
        return False, 'LOW_WIN_RATE'
    if calibration is None or calibration.empty:
        return False, 'MISSING_CALIBRATION'

    q = calibration.copy()
    if 'ANALYSIS' not in q.columns:
        return False, 'MISSING_CALIBRATION_ANALYSIS'

    event = q[q['ANALYSIS'].eq('BREAKOUT_EVENT')].copy()
    if event.empty or int(pd.to_numeric(event.TRADES, errors='coerce').fillna(0).sum()) < BT.probability_min_samples:
        return False, 'INSUFFICIENT_BREAKOUT_EVENT_SAMPLES'

    pre = event[event.ACTION.astype(str).str.contains('PRE-BREAKOUT', na=False)].copy()
    pre_trades = int(pd.to_numeric(pre.TRADES, errors='coerce').fillna(0).sum()) if not pre.empty else 0
    if pre_trades < BT.probability_min_samples:
        return False, 'INSUFFICIENT_PRE_BREAKOUT_SAMPLES'

    pre_rate = float(
        pd.to_numeric(pre.BREAKOUT_RATE, errors='coerce').fillna(0).mul(
            pd.to_numeric(pre.TRADES, errors='coerce').fillna(0)
        ).sum() / max(1, pre_trades)
    )
    if pre_rate < 35.0:
        return False, 'LOW_PRE_BREAKOUT_HIT_RATE'

    trade_q = q[q['ANALYSIS'].eq('TRADE_SCORE')].copy()
    if not trade_q.empty and {'ACTION', 'SCORE_BUCKET', 'AVG_RETURN', 'TRADES'}.issubset(trade_q.columns):
        trade_q['TRADES'] = pd.to_numeric(trade_q['TRADES'], errors='coerce').fillna(0)
        trade_q['AVG_RETURN'] = pd.to_numeric(trade_q['AVG_RETURN'], errors='coerce').fillna(0)
        core = trade_q[(trade_q.TRADES >= 5) & trade_q.SCORE_BUCKET.astype(str).eq('82-89')]
        pre_core = trade_q[(trade_q.TRADES >= 5) & trade_q.ACTION.astype(str).str.contains('PRE-BREAKOUT', na=False)]
        if not core.empty and float((core.AVG_RETURN * core.TRADES).sum() / core.TRADES.sum()) <= 0:
            return False, 'CORE_SCORE_BAND_NEGATIVE'
        if not pre_core.empty and float((pre_core.AVG_RETURN * pre_core.TRADES).sum() / pre_core.TRADES.sum()) <= 0:
            return False, 'PRE_BREAKOUT_EXPECTANCY_NEGATIVE'

    return True, 'PASS'

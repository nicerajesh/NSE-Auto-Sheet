"""Prefer NO TRADE over low-quality live signals."""
def evaluate(stats,calibration=None,min_trades=25):
 if not stats or stats.get("trades",0)<min_trades:return False,"INSUFFICIENT_BACKTEST"
 if stats.get("profit_factor",0)<1.15:return False,"LOW_PROFIT_FACTOR"
 if stats.get("median_return_pct",0)<=0:return False,"NEGATIVE_MEDIAN_RETURN"
 if stats.get("win_rate_pct",0)<42:return False,"LOW_WIN_RATE"
 if calibration is not None and not calibration.empty:
  q=calibration[calibration.TRADES>=5]
  if len(q)>=2 and q.iloc[-1].AVG_RETURN<q.iloc[0].AVG_RETURN:return False,"SCORE_NOT_MONOTONIC"
 return True,"PASS"

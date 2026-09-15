import ast,json,re
from pathlib import Path
import pandas as pd
from config import BT

def parse_action_stats(stats):
 v=(stats or {}).get('action_stats')
 if isinstance(v,list): return v
 if not isinstance(v,str): return []
 t=v.strip()
 if not t or t.lower() in {'nan','none','null'}: return []
 for c in [t,re.sub(r'\b(?:NaN|nan|Infinity|-Infinity)\b','null',t),re.sub(r'\b(?:NaN|nan|Infinity|-Infinity)\b','None',t)]:
  for p in (json.loads,ast.literal_eval):
   try:
    x=p(c)
    if isinstance(x,list) and all(isinstance(i,dict) for i in x): return x
   except Exception: pass
 return []

EDGE_REASONS={'LOW_PROFIT_FACTOR','NEGATIVE_MEDIAN_RETURN','LOW_WIN_RATE'}

def evaluate_action(row,min_trades=None):
 n=BT.min_quality_trades if min_trades is None else int(min_trades)
 if not row or int(row.get('trades',0) or 0)<n:return False,'INSUFFICIENT_ACTION_TRADES'
 if float(row.get('profit_factor',0) or 0)<BT.min_quality_profit_factor:return False,'LOW_PROFIT_FACTOR'
 if float(row.get('median_return_pct',0) or 0)<=0:return False,'NEGATIVE_MEDIAN_RETURN'
 if float(row.get('win_rate_pct',0) or 0)<BT.min_quality_win_rate:return False,'LOW_WIN_RATE'
 return True,'PASS'

def _wf():
 p=Path('output')/'walk_forward_summary.csv'
 if not p.exists():return False,'MISSING_WALK_FORWARD_SUMMARY'
 try:
  d=pd.read_csv(p); req=['trades','profit_factor','median_return_pct','win_rate_pct','expectancy_pct']
  if d.empty or any(c not in d for c in req):return False,'MISSING_WALK_FORWARD_METRICS'
  for c in req:d[c]=pd.to_numeric(d[c],errors='coerce')
  e=d[d.trades>=max(5,BT.min_oos_trades//10)].dropna(subset=req)
  if e.empty:return False,'ALL_WALK_FORWARD_WINDOWS_TOO_THIN'
  good=e[(e.profit_factor>=BT.min_quality_profit_factor)&(e.median_return_pct>0)&(e.win_rate_pct>=BT.min_oos_win_rate)&(e.expectancy_pct>BT.min_oos_expectancy_pct)]
  if len(good)/len(e)<.60:return False,f'INCONSISTENT_ACROSS_WINDOWS_{round(100*len(good)/len(e),0)}PCT'
  z=e.iloc[-1]
  if not(z.profit_factor>=BT.min_oos_profit_factor and z.median_return_pct>0 and z.win_rate_pct>=BT.min_oos_win_rate and z.expectancy_pct>BT.min_oos_expectancy_pct):return False,'LATEST_WALK_FORWARD_WINDOW_FAILED'
  return True,'PASS'
 except Exception:return False,'WALK_FORWARD_VALIDATION_ERROR'

def evaluate(stats,calibration=None,min_trades=None):
 n=BT.min_quality_trades if min_trades is None else int(min_trades)
 if not stats or int(stats.get('trades',0) or 0)<n:return False,'INSUFFICIENT_BACKTEST'
 if float(stats.get('profit_factor',0) or 0)<BT.min_quality_profit_factor:return False,'LOW_PROFIT_FACTOR'
 if float(stats.get('median_return_pct',0) or 0)<=0:return False,'NEGATIVE_MEDIAN_RETURN'
 if float(stats.get('win_rate_pct',0) or 0)<BT.min_quality_win_rate:return False,'LOW_WIN_RATE'
 t1=float(stats.get('t1_hit_pct',0) or 0);t2=float(stats.get('t2_hit_pct',0) or 0);t3=float(stats.get('t3_hit_pct',0) or 0)
 if t2>t1+1e-9 or t3>t2+1e-9:return False,'INVALID_TARGET_CALIBRATION'
 if calibration is None or calibration.empty:return False,'MISSING_CALIBRATION'
 if 'ANALYSIS' not in calibration:return False,'MISSING_CALIBRATION_ANALYSIS'
 q=calibration.copy();e=q[q.ANALYSIS.eq('BREAKOUT_EVENT')]
 if e.empty or pd.to_numeric(e.TRADES,errors='coerce').fillna(0).sum()<BT.probability_min_samples:return False,'INSUFFICIENT_BREAKOUT_EVENT_SAMPLES'
 pre=e[e.ACTION.astype(str).str.contains('PRE-BREAKOUT',na=False)].copy()
 if pre.empty or pd.to_numeric(pre.TRADES,errors='coerce').fillna(0).sum()<BT.probability_min_samples:return False,'INSUFFICIENT_PRE_BREAKOUT_SAMPLES'
 pre['TRADES']=pd.to_numeric(pre.TRADES,errors='coerce').fillna(0);pre['BREAKOUT_RATE']=pd.to_numeric(pre.BREAKOUT_RATE,errors='coerce').fillna(0)
 if pre.BREAKOUT_RATE.mul(pre.TRADES).sum()/max(1,pre.TRADES.sum())<35:return False,'LOW_PRE_BREAKOUT_HIT_RATE'
 tq=q[q.ANALYSIS.eq('TRADE_SCORE')].copy()
 if not tq.empty and {'SCORE_BUCKET','AVG_RETURN','TRADES'}<=set(tq.columns):
  tq['TRADES']=pd.to_numeric(tq.TRADES,errors='coerce');tq['AVG_RETURN']=pd.to_numeric(tq.AVG_RETURN,errors='coerce');core=tq[(tq.TRADES>=5)&tq.SCORE_BUCKET.astype(str).eq('82-89')]
  if not core.empty and core.AVG_RETURN.mean()<=0:return False,'CORE_SCORE_BAND_NEGATIVE'
 return _wf()

from __future__ import annotations
import pandas as pd
from indicator import add_indicators
from strategy import ACTIONABLE, analyze_stock
from config import BT


def _levels(sig):
    trigger=float(sig.get('BREAKOUT_TRIGGER') or 0)
    stop=float(sig.get('STOP_LOSS') or 0)
    t1=float(sig.get('TARGET_1') or 0); t2=float(sig.get('TARGET_2') or 0); t3=float(sig.get('TARGET_3') or 0)
    return trigger,stop,t1,t2,t3


def outcome(g, entry_i, entry, stop, t1, t2, t3, horizon=30):
    f=g.iloc[entry_i:entry_i+horizon]
    if f.empty:return None
    rem=1.0; realised=0.0; hit1=hit2=hit3=False; stop_hit=False; initial_stop=True; exit_reason='TIME'; exit_idx=f.index[-1]
    risk=max(1e-9,entry-stop)
    active_stop=stop; max_high=entry; min_low=entry
    for j,row in f.iterrows():
        op=float(row.OPEN_PRICE); hi=float(row.HIGH_PRICE); lo=float(row.LOW_PRICE); cl=float(row.CLOSE_PRICE)
        max_high=max(max_high,hi); min_low=min(min_low,lo)
        # Triggered next-day breakout: entry occurs only when HIGH reaches trigger.
        if not hit1 and not hit2 and not hit3 and hi < entry:
            if j==f.index[-1]:
                exit_reason='TRIGGER_NOT_HIT'
            continue
        if not hit1 and not hit2 and not hit3:
            if hi >= entry:
                fill=max(entry,op) if op>entry else entry
            else:
                continue
        else:
            fill=entry
        if lo <= active_stop:
            realised += rem*(active_stop-fill)/fill*100; rem=0; stop_hit=True; exit_idx=j; exit_reason='STOP'; break
        if not hit1 and hi>=t1:
            realised += .40*(t1-fill)/fill*100; rem-=.40; hit1=True; active_stop=max(active_stop,fill+0.05*risk)
        if not hit2 and hi>=t2:
            realised += .30*(t2-fill)/fill*100; rem-=.30; hit2=True; active_stop=max(active_stop,fill+risk)
        if not hit3 and hi>=t3:
            realised += rem*(t3-fill)/fill*100; rem=0; hit3=True; exit_idx=j; exit_reason='T3'; break
        if hit1 and lo<=active_stop:
            realised += rem*(active_stop-fill)/fill*100; rem=0; stop_hit=True; exit_idx=j; exit_reason='PROTECTED_STOP'; break
        if rem>0 and j==f.index[-1]:
            realised += rem*(cl-fill)/fill*100; exit_idx=j; exit_reason='TIME'
    cost=(BT.commission_bps+BT.slippage_bps)*2/100
    return {'HIT_T1':hit1,'HIT_T2':hit2,'HIT_T3':hit3,'STOP_HIT':stop_hit,'INITIAL_STOP_HIT':initial_stop and stop_hit,'RETURN_PCT':realised-cost,'HOLD_DAYS':int(exit_idx-entry_i+1),'MFE_PCT':(max_high-entry)/entry*100,'MAE_PCT':(min_low-entry)/entry*100,'EXIT_REASON':exit_reason}


def run_backtest(hist,min_score=None,horizon=None):
    threshold=BT.min_score if min_score is None else int(min_score); horizon=BT.horizon if horizon is None else int(horizon); rows=[]
    for sym,raw in hist.groupby('SYMBOL'):
        g=add_indicators(raw).sort_values('DATE').reset_index(drop=True)
        if len(g)<BT.warmup+horizon+1: continue
        last=-999
        for i in range(BT.warmup,len(g)-horizon-1):
            if i-last<BT.min_gap_between_signals: continue
            sig=analyze_stock(g.iloc[:i+1],threshold)
            if not sig or sig.get('ACTION') not in ACTIONABLE or sig.get('ACTION')=='BUY NOW': continue
            # Signal is produced after today's completed candle. Tomorrow is i+1.
            entry_i=i+1
            trigger,stop,t1,t2,t3=_levels(sig)
            if trigger<=0 or stop<=0 or stop>=trigger or not (trigger<t1<t2<t3): continue
            o=outcome(g,entry_i,trigger,stop,t1,t2,t3,horizon)
            if o:
                rows.append({'SYMBOL':sym,'SIGNAL_DATE':g.iloc[i].DATE,'BUY_DATE':g.iloc[entry_i].DATE,'SCORE':sig['HUNTER_SCORE'],'ACTION':sig['ACTION'],'ENTRY':trigger,'ENTRY_INDEX':entry_i,'STOP':stop,'T1':t1,'T2':t2,'T3':t3,**o}); last=i
    trades=pd.DataFrame(rows)
    if trades.empty:return trades,{'trades':0},pd.DataFrame()
    pos=trades[trades.RETURN_PCT>0]; neg=trades[trades.RETURN_PCT<0]
    stats={'trades':len(trades),'win_rate_pct':round((trades.RETURN_PCT>0).mean()*100,2),'median_return_pct':round(trades.RETURN_PCT.median(),2),'avg_return_pct':round(trades.RETURN_PCT.mean(),2),'stop_rate_pct':round(trades.INITIAL_STOP_HIT.mean()*100,2),'t1_hit_pct':round(trades.HIT_T1.mean()*100,2),'t2_hit_pct':round(trades.HIT_T2.mean()*100,2),'t3_hit_pct':round(trades.HIT_T3.mean()*100,2),'profit_factor':round(pos.RETURN_PCT.sum()/max(1e-9,-neg.RETURN_PCT.sum()),2),'avg_hold_days':round(trades.HOLD_DAYS.mean(),1),'expectancy_pct':round(trades.RETURN_PCT.mean(),2),'trigger_hit_rate_pct':round((trades.EXIT_REASON!='TRIGGER_NOT_HIT').mean()*100,2)}
    buckets=pd.cut(trades.SCORE,[0,67,74,81,89,100],labels=['<68','68-74','75-81','82-89','90+'])
    cal=trades.assign(SCORE_BUCKET=buckets).groupby('SCORE_BUCKET',observed=False).agg(TRADES=('RETURN_PCT','size'),WIN_RATE=('RETURN_PCT',lambda s:round((s>0).mean()*100,2)),AVG_RETURN=('RETURN_PCT','mean'),MEDIAN_RETURN=('RETURN_PCT','median')).reset_index(); cal[['AVG_RETURN','MEDIAN_RETURN']]=cal[['AVG_RETURN','MEDIAN_RETURN']].round(2); cal['ANALYSIS']='SCORE_BUCKET'
    return trades,stats,cal

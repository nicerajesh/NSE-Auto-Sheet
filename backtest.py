from __future__ import annotations
import pandas as pd
from indicator import add_indicators
from strategy import ACTIONABLE, analyze_stock
from config import BT


def _levels(sig):
    trigger=float(sig.get('BREAKOUT_TRIGGER') or 0)
    entry=float(sig.get('ENTRY_PRICE') or sig.get('CMP') or 0)
    stop=float(sig.get('STOP_LOSS') or 0)
    t1=float(sig.get('TARGET_1') or 0); t2=float(sig.get('TARGET_2') or 0); t3=float(sig.get('TARGET_3') or 0)
    return entry,trigger,stop,t1,t2,t3


def outcome(g, entry_i, entry, stop, t1, t2, t3, horizon=30, trigger=None, require_trigger=False):
    f=g.iloc[entry_i:entry_i+horizon]
    if f.empty:return None
    rem=1.0; realised=0.0; hit1=hit2=hit3=False; stop_hit=False
    exit_reason='TIME'; exit_idx=f.index[-1]; risk=max(1e-9,entry-stop)
    active_stop=stop; max_high=entry; min_low=entry; entered=False; fill=entry

    for j,row in f.iterrows():
        op=float(row.OPEN_PRICE); hi=float(row.HIGH_PRICE); lo=float(row.LOW_PRICE); cl=float(row.CLOSE_PRICE)
        max_high=max(max_high,hi); min_low=min(min_low,lo)

        # Pre-breakout/swing: buy at the next day's open, but never if the opening gap
        # already jumps beyond the breakout trigger. That would no longer be an early entry.
        if require_trigger:
            trig=float(trigger or 0)
            if op>=trig:
                exit_reason='GAP_PAST_TRIGGER'; exit_idx=j; break
            if hi<trig:
                if j==f.index[-1]: exit_reason='TRIGGER_NOT_HIT'
                continue
            fill=max(op,trig)
        else:
            if not entered:
                fill=op if op>0 else entry
            entered=True

        if lo<=active_stop:
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

    if not entered and require_trigger and exit_reason in ('TRIGGER_NOT_HIT','GAP_PAST_TRIGGER'):
        return {'HIT_T1':False,'HIT_T2':False,'HIT_T3':False,'STOP_HIT':False,'INITIAL_STOP_HIT':False,'RETURN_PCT':-costs(),'HOLD_DAYS':int(exit_idx-entry_i+1),'MFE_PCT':(max_high-entry)/entry*100,'MAE_PCT':(min_low-entry)/entry*100,'EXIT_REASON':exit_reason}
    cost=costs()
    return {'HIT_T1':hit1,'HIT_T2':hit2,'HIT_T3':hit3,'STOP_HIT':stop_hit,'INITIAL_STOP_HIT':stop_hit and not hit1,'RETURN_PCT':realised-cost,'HOLD_DAYS':int(exit_idx-entry_i+1),'MFE_PCT':(max_high-entry)/entry*100,'MAE_PCT':(min_low-entry)/entry*100,'EXIT_REASON':exit_reason}


def costs():
    return (BT.commission_bps+BT.slippage_bps)*2/100


def run_backtest(hist,min_score=None,horizon=None):
    threshold=BT.min_score if min_score is None else int(min_score)
    horizon=BT.horizon if horizon is None else int(horizon)
    rows=[]
    for sym,raw in hist.groupby('SYMBOL'):
        g=add_indicators(raw).sort_values('DATE').reset_index(drop=True)
        if len(g)<BT.warmup+horizon+1: continue
        last=-999
        for i in range(BT.warmup,len(g)-horizon-1):
            if i-last<BT.min_gap_between_signals: continue
            sig=analyze_stock(g.iloc[:i+1],threshold)
            if not sig or sig.get('ACTION') not in ACTIONABLE: continue
            entry_i=i+1
            entry,trigger,stop,t1,t2,t3=_levels(sig)
            if entry<=0 or stop<=0 or stop>=entry or not (entry<t1<t2<t3): continue

            # PRE-BREAKOUT and SWING are tested as next-session open entries.
            # BREAKOUT BUY is tested only when the next session actually crosses trigger.
            is_breakout=sig.get('ACTION')=='BREAKOUT BUY'
            if is_breakout:
                if trigger<=entry or trigger>=t1: continue
                o=outcome(g,entry_i,trigger,stop,t1,t2,t3,horizon,trigger=trigger,require_trigger=True)
            else:
                o=outcome(g,entry_i,entry,stop,t1,t2,t3,horizon,require_trigger=False)
            if o:
                rows.append({'SYMBOL':sym,'SIGNAL_DATE':g.iloc[i].DATE,'BUY_DATE':g.iloc[entry_i].DATE,'SCORE':sig['HUNTER_SCORE'],'ACTION':sig['ACTION'],'ENTRY':trigger if is_breakout else entry,'ENTRY_INDEX':entry_i,'STOP':stop,'T1':t1,'T2':t2,'T3':t3,**o})
                last=i

    trades=pd.DataFrame(rows)
    if trades.empty:return trades,{'trades':0},pd.DataFrame()
    pos=trades[trades.RETURN_PCT>0]; neg=trades[trades.RETURN_PCT<0]
    stats={'trades':len(trades),'win_rate_pct':round((trades.RETURN_PCT>0).mean()*100,2),'median_return_pct':round(trades.RETURN_PCT.median(),2),'avg_return_pct':round(trades.RETURN_PCT.mean(),2),'stop_rate_pct':round(trades.INITIAL_STOP_HIT.mean()*100,2),'t1_hit_pct':round(trades.HIT_T1.mean()*100,2),'t2_hit_pct':round(trades.HIT_T2.mean()*100,2),'t3_hit_pct':round(trades.HIT_T3.mean()*100,2),'profit_factor':round(pos.RETURN_PCT.sum()/max(1e-9,-neg.RETURN_PCT.sum()),2),'avg_hold_days':round(trades.HOLD_DAYS.mean(),1),'expectancy_pct':round(trades.RETURN_PCT.mean(),2),'trigger_hit_rate_pct':round((~trades.EXIT_REASON.isin(['TRIGGER_NOT_HIT','GAP_PAST_TRIGGER'])).mean()*100,2)}
    buckets=pd.cut(trades.SCORE,[0,67,74,81,89,100],labels=['<68','68-74','75-81','82-89','90+'])
    cal=trades.assign(SCORE_BUCKET=buckets).groupby('SCORE_BUCKET',observed=False).agg(TRADES=('RETURN_PCT','size'),WIN_RATE=('RETURN_PCT',lambda s:round((s>0).mean()*100,2)),AVG_RETURN=('RETURN_PCT','mean'),MEDIAN_RETURN=('RETURN_PCT','median')).reset_index()
    cal[['AVG_RETURN','MEDIAN_RETURN']]=cal[['AVG_RETURN','MEDIAN_RETURN']].round(2); cal['ANALYSIS']='SCORE_BUCKET'
    return trades,stats,cal

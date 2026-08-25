from __future__ import annotations
import pandas as pd
from indicator import add_indicators
from strategy import ACTIONABLE, analyze_stock
from config import BT


def _num(v, default=0.0):
    try:
        x=float(v)
        return x if pd.notna(v) else default
    except Exception:
        return default


def _levels(sig):
    trigger=_num(sig.get('BREAKOUT_TRIGGER'))
    entry=_num(sig.get('ENTRY_PRICE') or sig.get('CMP'))
    stop=_num(sig.get('STOP_LOSS'))
    t1=_num(sig.get('TARGET_1')); t2=_num(sig.get('TARGET_2')); t3=_num(sig.get('TARGET_3'))
    return entry,trigger,stop,t1,t2,t3


def _costs():
    return (BT.commission_bps+BT.slippage_bps)*2/100


def outcome(g,entry_i,entry,stop,t1,t2,t3,horizon=30,trigger=None,require_trigger=False):
    f=g.iloc[entry_i:entry_i+horizon]
    if f.empty:return None
    rem=1.0; realised=0.0; hit1=hit2=hit3=False; stop_hit=False; entered=not require_trigger
    exit_reason='TIME'; exit_idx=f.index[-1]; risk=max(1e-9,entry-stop); active_stop=stop; fill=entry
    max_high=entry; min_low=entry
    for j,row in f.iterrows():
        op=_num(row.OPEN_PRICE); hi=_num(row.HIGH_PRICE); lo=_num(row.LOW_PRICE); cl=_num(row.CLOSE_PRICE)
        max_high=max(max_high,hi); min_low=min(min_low,lo)
        if require_trigger and not entered:
            trig=_num(trigger)
            if op>=trig: fill=op; entered=True
            elif hi>=trig: fill=trig; entered=True
            else: continue
        if lo<=active_stop:
            realised += rem*(active_stop-fill)/fill*100; rem=0; stop_hit=True; exit_idx=j
            exit_reason='STOP' if not hit1 else 'PROTECTED_STOP'; break
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
    if require_trigger and not entered:return None
    return {'HIT_T1':hit1,'HIT_T2':hit2,'HIT_T3':hit3,'STOP_HIT':stop_hit,'INITIAL_STOP_HIT':stop_hit and not hit1,'RETURN_PCT':realised-_costs(),'HOLD_DAYS':int(exit_idx-entry_i+1),'MFE_PCT':(max_high-entry)/entry*100,'MAE_PCT':(min_low-entry)/entry*100,'EXIT_REASON':exit_reason}


def _event_outcome(g,i,resistance,lookahead):
    """Label whether a pre-breakout setup actually breaks resistance before invalidation."""
    if i+1>=len(g) or not pd.notna(resistance): return None
    end=min(len(g),i+1+lookahead)
    future=g.iloc[i+1:end]
    if future.empty:return None
    r=float(resistance)
    max_high=float(future.HIGH_PRICE.max())
    hit_idx=None
    for j,row in future.iterrows():
        if _num(row.HIGH_PRICE)>=r*1.002:
            hit_idx=j; break
    if hit_idx is not None:
        return {'BREAKOUT_HIT':1,'DAYS_TO_BREAKOUT':int(hit_idx-(i+1)+1),'MAX_HIGH_PCT':(max_high-_num(g.iloc[i].CLOSE_PRICE))/_num(g.iloc[i].CLOSE_PRICE)*100}
    return {'BREAKOUT_HIT':0,'DAYS_TO_BREAKOUT':None,'MAX_HIGH_PCT':(max_high-_num(g.iloc[i].CLOSE_PRICE))/_num(g.iloc[i].CLOSE_PRICE)*100}


def _stats(trades):
    if trades.empty:return {'trades':0}
    pos=trades[trades.RETURN_PCT>0]; neg=trades[trades.RETURN_PCT<0]
    return {'trades':len(trades),'win_rate_pct':round((trades.RETURN_PCT>0).mean()*100,2),'median_return_pct':round(trades.RETURN_PCT.median(),2),'avg_return_pct':round(trades.RETURN_PCT.mean(),2),'stop_rate_pct':round(trades.INITIAL_STOP_HIT.mean()*100,2),'t1_hit_pct':round(trades.HIT_T1.mean()*100,2),'t2_hit_pct':round(trades.HIT_T2.mean()*100,2),'t3_hit_pct':round(trades.HIT_T3.mean()*100,2),'profit_factor':round(pos.RETURN_PCT.sum()/max(1e-9,-neg.RETURN_PCT.sum()),2),'avg_hold_days':round(trades.HOLD_DAYS.mean(),1),'expectancy_pct':round(trades.RETURN_PCT.mean(),2)}


def run_backtest(hist,min_score=None,horizon=None):
    threshold=BT.min_score if min_score is None else int(min_score)
    horizon=BT.horizon if horizon is None else int(horizon)
    rows=[]; events=[]; last_by_action={}
    for sym,raw in hist.groupby('SYMBOL'):
        g=add_indicators(raw).sort_values('DATE').reset_index(drop=True)
        if len(g)<BT.warmup+horizon+1: continue
        last=-999
        for i in range(BT.warmup,len(g)-horizon-1):
            if i-last<BT.min_gap_between_signals: continue
            sig=analyze_stock(g.iloc[:i+1],threshold)
            if not sig: continue
            action=sig.get('ACTION')
            if action in ('PRE-BREAKOUT BUY','PRE-BREAKOUT WATCH/BUY','WATCH'):
                try:
                    res=float(sig.get('RESISTANCE'))
                    ev=_event_outcome(g,i,res,BT.breakout_lookahead_days)
                    if ev:
                        events.append({'SYMBOL':sym,'SIGNAL_DATE':g.iloc[i].DATE,'ACTION':action,'SCORE':sig.get('PRE_BREAKOUT_SCORE',sig.get('HUNTER_SCORE',0)),**ev})
                except Exception: pass
            if action not in ACTIONABLE: continue
            entry_i=i+1
            entry,trigger,stop,t1,t2,t3=_levels(sig)
            if entry<=0 or stop<=0 or stop>=entry or not (entry<t1<t2<t3): continue
            is_breakout=action=='BREAKOUT BUY'
            if is_breakout:
                if trigger<=entry or trigger>=t1: continue
                o=outcome(g,entry_i,trigger,stop,t1,t2,t3,horizon,trigger=trigger,require_trigger=True)
            else:
                o=outcome(g,entry_i,entry,stop,t1,t2,t3,horizon,require_trigger=False)
            if o:
                rows.append({'SYMBOL':sym,'SIGNAL_DATE':g.iloc[i].DATE,'BUY_DATE':g.iloc[entry_i].DATE,'SCORE':sig.get('HUNTER_SCORE',0),'ACTION':action,'ENTRY':trigger if is_breakout else entry,'ENTRY_INDEX':entry_i,'STOP':stop,'T1':t1,'T2':t2,'T3':t3,**o})
                last=i
    trades=pd.DataFrame(rows)
    stats=_stats(trades)
    # Action-specific performance prevents a strong breakout bucket from hiding weak pre-breakout results.
    action_stats=[]
    if not trades.empty:
        for action,g in trades.groupby('ACTION'):
            s=_stats(g); s['ACTION']=action; action_stats.append(s)
    action_stats=pd.DataFrame(action_stats)
    # True event probability: historical breakout hit rate by action and score bucket.
    events_df=pd.DataFrame(events)
    calibration=[]
    if not events_df.empty:
        bins=[0,67,74,81,89,100]
        events_df['SCORE_BUCKET']=pd.cut(pd.to_numeric(events_df.SCORE,errors='coerce'),bins=bins,labels=['<68','68-74','75-81','82-89','90+'])
        q=events_df.groupby(['ACTION','SCORE_BUCKET'],observed=False).agg(TRADES=('BREAKOUT_HIT','size'),BREAKOUT_HITS=('BREAKOUT_HIT','sum'),BREAKOUT_RATE=('BREAKOUT_HIT','mean'),AVG_DAYS_TO_BREAKOUT=('DAYS_TO_BREAKOUT','mean'),AVG_MAX_MOVE=('MAX_HIGH_PCT','mean')).reset_index()
        q['BREAKOUT_RATE']=q.BREAKOUT_RATE*100; q['ANALYSIS']='BREAKOUT_EVENT'; calibration.append(q)
    if not trades.empty:
        buckets=pd.cut(trades.SCORE,[0,67,74,81,89,100],labels=['<68','68-74','75-81','82-89','90+'])
        q=trades.assign(SCORE_BUCKET=buckets).groupby(['ACTION','SCORE_BUCKET'],observed=False).agg(TRADES=('RETURN_PCT','size'),WIN_RATE=('RETURN_PCT',lambda s:round((s>0).mean()*100,2)),AVG_RETURN=('RETURN_PCT','mean'),MEDIAN_RETURN=('RETURN_PCT','median')).reset_index()
        q['AVG_RETURN']=q.AVG_RETURN.round(2);q['MEDIAN_RETURN']=q.MEDIAN_RETURN.round(2);q['ANALYSIS']='TRADE_SCORE';calibration.append(q)
        h=trades.groupby(['ACTION','HOLD_DAYS']).RETURN_PCT.mean().reset_index(name='AVG_RETURN');h['HORIZON_DAYS']=h.HOLD_DAYS;h['ANALYSIS']='HORIZON';calibration.append(h[['ACTION','HORIZON_DAYS','AVG_RETURN','ANALYSIS']])
    cal=pd.concat(calibration,ignore_index=True) if calibration else pd.DataFrame()
    stats['action_stats']=action_stats.to_dict('records') if not action_stats.empty else []
    stats['breakout_event_samples']=int(len(events_df))
    stats['breakout_event_rate_pct']=round(events_df.BREAKOUT_HIT.mean()*100,2) if not events_df.empty else 0.0
    stats['pre_breakout_event_rate_pct']=round(events_df.loc[events_df.ACTION.str.contains('PRE-BREAKOUT',na=False),'BREAKOUT_HIT'].mean()*100,2) if not events_df.empty and events_df.ACTION.str.contains('PRE-BREAKOUT',na=False).any() else 0.0
    return trades,stats,cal

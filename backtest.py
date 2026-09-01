from __future__ import annotations
import pandas as pd
from indicator import add_indicators
from strategy import ACTIONABLE, analyze_stock, _low52_features, _apex_features, _apex_regime_series, _stealth_features, MIN_HISTORY, NIFTY_SYMBOL
from config import BT, STRAT

def _num(v,default=0.0):
    try:
        x=float(v); return x if pd.notna(v) else default
    except Exception:return default

def _levels(sig):
    return (_num(sig.get('ENTRY_PRICE') or sig.get('CMP')),_num(sig.get('BREAKOUT_TRIGGER')),_num(sig.get('STOP_LOSS')),_num(sig.get('TARGET_1')),_num(sig.get('TARGET_2')),_num(sig.get('TARGET_3')))

def _costs():return (BT.commission_bps+BT.slippage_bps)*2/100

def outcome(g,entry_i,entry,stop,t1,t2,t3,horizon=30,trigger=None,require_trigger=False):
    f=g.iloc[entry_i:entry_i+horizon]
    if f.empty:return None
    rem=1.0;realised=0.0;hit1=hit2=hit3=False;stop_hit=False;entered=not require_trigger;exit_reason='TIME';exit_idx=f.index[-1];fill=entry;max_high=entry;min_low=entry
    first_open=_num(f.iloc[0].OPEN_PRICE)
    if not require_trigger and first_open>0:
        gap=(first_open/entry-1)*100
        if gap>STRAT.max_gap_entry_pct:return None
        fill=first_open
    risk=max(1e-9,fill-stop);active_stop=stop
    for j,row in f.iterrows():
        op=_num(row.OPEN_PRICE);hi=_num(row.HIGH_PRICE);lo=_num(row.LOW_PRICE);cl=_num(row.CLOSE_PRICE);max_high=max(max_high,hi);min_low=min(min_low,lo)
        if require_trigger and not entered:
            trig=_num(trigger)
            if op>=trig:fill=op;entered=True
            elif hi>=trig:fill=trig;entered=True
            else:continue
            risk=max(1e-9,fill-stop);active_stop=stop
        if lo<=active_stop:
            realised+=rem*(active_stop-fill)/fill*100;rem=0;stop_hit=True;exit_idx=j;exit_reason='STOP' if not hit1 else 'PROTECTED_STOP';break
        if not hit1 and hi>=t1:
            realised+=.40*(t1-fill)/fill*100;rem-=.40;hit1=True;active_stop=max(active_stop,fill+0.05*risk)
        if not hit2 and hi>=t2:
            realised+=.30*(t2-fill)/fill*100;rem-=.30;hit2=True;active_stop=max(active_stop,fill+risk)
        if not hit3 and hi>=t3:
            realised+=rem*(t3-fill)/fill*100;rem=0;hit3=True;exit_idx=j;exit_reason='T3';break
        if hit1 and lo<=active_stop:
            realised+=rem*(active_stop-fill)/fill*100;rem=0;stop_hit=True;exit_idx=j;exit_reason='PROTECTED_STOP';break
        if rem>0 and j==f.index[-1]:realised+=rem*(cl-fill)/fill*100;exit_idx=j
    if require_trigger and not entered:return None
    return {'FILL':fill,'HIT_T1':hit1,'HIT_T2':hit2,'HIT_T3':hit3,'STOP_HIT':stop_hit,'INITIAL_STOP_HIT':stop_hit and not hit1,'RETURN_PCT':realised-_costs(),'HOLD_DAYS':int(exit_idx-entry_i+1),'MFE_PCT':(max_high-fill)/fill*100,'MAE_PCT':(min_low-fill)/fill*100,'EXIT_REASON':exit_reason}

def _event_outcome(g,i,resistance,lookahead):
    if i+1>=len(g) or not pd.notna(resistance):return None
    future=g.iloc[i+1:min(len(g),i+1+lookahead)]
    if future.empty:return None
    r=float(resistance);max_high=float(future.HIGH_PRICE.max());hit_idx=None
    for j,row in future.iterrows():
        if _num(row.HIGH_PRICE)>=r*1.002:hit_idx=j;break
    return {'BREAKOUT_HIT':int(hit_idx is not None),'DAYS_TO_BREAKOUT':int(hit_idx-(i+1)+1) if hit_idx is not None else None,'MAX_HIGH_PCT':(max_high-_num(g.iloc[i].CLOSE_PRICE))/_num(g.iloc[i].CLOSE_PRICE)*100}

def _stats(trades):
    if trades.empty:return {'trades':0}
    pos=trades[trades.RETURN_PCT>0];neg=trades[trades.RETURN_PCT<0]
    return {'trades':len(trades),'win_rate_pct':round((trades.RETURN_PCT>0).mean()*100,2),'median_return_pct':round(trades.RETURN_PCT.median(),2),'avg_return_pct':round(trades.RETURN_PCT.mean(),2),'stop_rate_pct':round(trades.INITIAL_STOP_HIT.mean()*100,2),'t1_hit_pct':round(trades.HIT_T1.mean()*100,2),'t2_hit_pct':round(trades.HIT_T2.mean()*100,2),'t3_hit_pct':round(trades.HIT_T3.mean()*100,2),'profit_factor':round(pos.RETURN_PCT.sum()/max(1e-9,-neg.RETURN_PCT.sum()),2),'avg_hold_days':round(trades.HOLD_DAYS.mean(),1),'expectancy_pct':round(trades.RETURN_PCT.mean(),2)}

def run_backtest(hist,min_score=None,horizon=None):
    threshold=BT.min_score if min_score is None else int(min_score);horizon=BT.horizon if horizon is None else int(horizon);rows=[];events=[]
    for sym,raw in hist.groupby('SYMBOL'):
        g=add_indicators(raw).sort_values('DATE').reset_index(drop=True)
        if len(g)<BT.warmup+horizon+1:continue
        last=-999
        for i in range(BT.warmup,len(g)-horizon-1):
            if i-last<BT.min_gap_between_signals:continue
            sig=analyze_stock(g.iloc[:i+1],threshold)
            if not sig:continue
            action=sig.get('ACTION')
            if action in ('PRE-BREAKOUT BUY','PRE-BREAKOUT WATCH/BUY','WATCH'):
                try:
                    ev=_event_outcome(g,i,float(sig.get('RESISTANCE')),BT.breakout_lookahead_days)
                    if ev:events.append({'SYMBOL':sym,'SIGNAL_DATE':g.iloc[i].DATE,'ACTION':action,'SCORE':sig.get('PRE_BREAKOUT_SCORE',sig.get('HUNTER_SCORE',0)),**ev})
                except Exception:pass
            if action not in ACTIONABLE:continue
            entry_i=i+1;entry,trigger,stop,t1,t2,t3=_levels(sig)
            if entry<=0 or stop<=0 or stop>=entry or not(entry<t1<t2<t3):continue
            is_breakout=action=='BREAKOUT BUY'
            if is_breakout:
                if trigger<=entry or trigger>=t1:continue
                o=outcome(g,entry_i,trigger,stop,t1,t2,t3,horizon,trigger=trigger,require_trigger=True)
            else:o=outcome(g,entry_i,entry,stop,t1,t2,t3,horizon,require_trigger=False)
            if o:
                rows.append({'SYMBOL':sym,'SIGNAL_DATE':g.iloc[i].DATE,'BUY_DATE':g.iloc[entry_i].DATE,'SCORE':sig.get('HUNTER_SCORE',0),'ACTION':action,'ENTRY':trigger if is_breakout else o['FILL'],'ENTRY_INDEX':entry_i,'STOP':stop,'T1':t1,'T2':t2,'T3':t3,**o});last=i
    trades=pd.DataFrame(rows);stats=_stats(trades);action_stats=[]
    if not trades.empty:
        for action,g in trades.groupby('ACTION'):
            s=_stats(g);s['ACTION']=action;action_stats.append(s)
    action_stats=pd.DataFrame(action_stats);events_df=pd.DataFrame(events);calibration=[]
    if not events_df.empty:
        events_df['SCORE_BUCKET']=pd.cut(pd.to_numeric(events_df.SCORE,errors='coerce'),bins=[0,67,74,81,89,100],labels=['<68','68-74','75-81','82-89','90+'])
        q=events_df.groupby(['ACTION','SCORE_BUCKET'],observed=False).agg(TRADES=('BREAKOUT_HIT','size'),BREAKOUT_HITS=('BREAKOUT_HIT','sum'),BREAKOUT_RATE=('BREAKOUT_HIT','mean'),AVG_DAYS_TO_BREAKOUT=('DAYS_TO_BREAKOUT','mean'),AVG_MAX_MOVE=('MAX_HIGH_PCT','mean')).reset_index();q['BREAKOUT_RATE']*=100;q['ANALYSIS']='BREAKOUT_EVENT';calibration.append(q)
    if not trades.empty:
        buckets=pd.cut(trades.SCORE,[0,67,74,81,89,100],labels=['<68','68-74','75-81','82-89','90+']);q=trades.assign(SCORE_BUCKET=buckets).groupby(['ACTION','SCORE_BUCKET'],observed=False).agg(TRADES=('RETURN_PCT','size'),WIN_RATE=('RETURN_PCT',lambda s:round((s>0).mean()*100,2)),AVG_RETURN=('RETURN_PCT','mean'),MEDIAN_RETURN=('RETURN_PCT','median')).reset_index();q['AVG_RETURN']=q.AVG_RETURN.round(2);q['MEDIAN_RETURN']=q.MEDIAN_RETURN.round(2);q['ANALYSIS']='TRADE_SCORE';calibration.append(q)
        h=trades.groupby(['ACTION','HOLD_DAYS']).RETURN_PCT.mean().reset_index(name='AVG_RETURN');h['HORIZON_DAYS']=h.HOLD_DAYS;h['ANALYSIS']='HORIZON';calibration.append(h[['ACTION','HORIZON_DAYS','AVG_RETURN','ANALYSIS']])
    cal=pd.concat(calibration,ignore_index=True) if calibration else pd.DataFrame();stats['action_stats']=action_stats.to_dict('records') if not action_stats.empty else [];stats['breakout_event_samples']=len(events_df);stats['breakout_event_rate_pct']=round(events_df.BREAKOUT_HIT.mean()*100,2) if not events_df.empty else 0.0;stats['pre_breakout_event_rate_pct']=round(events_df.loc[events_df.ACTION.str.contains('PRE-BREAKOUT',na=False),'BREAKOUT_HIT'].mean()*100,2) if not events_df.empty and events_df.ACTION.str.contains('PRE-BREAKOUT',na=False).any() else 0.0
    return trades,stats,cal


def walk_forward_consistency(trades: pd.DataFrame, horizon=None) -> tuple[pd.DataFrame, bool, str]:
    """The single aggregate quality_gate.evaluate() call judges the WHOLE
    backtest history at once -- a strategy can pass that gate purely because
    one great 3-month stretch years ago drags the average up, while its
    actual OUT-OF-SAMPLE, RECENT behaviour has quietly stopped working
    (curve-fit / regime-shifted). walk_forward_train_days / test_days were
    already defined in BacktestConfig but never used anywhere -- this wires
    them up: bucket the (already no-lookahead) trades from run_backtest()
    into successive walk_forward_test_days-wide windows by SIGNAL_DATE and
    require the edge to show up consistently across windows, not just in
    aggregate.

    Returns (window_summary_df, ok, reason)."""
    from config import BT
    horizon = BT.horizon if horizon is None else int(horizon)
    if trades is None or trades.empty or "SIGNAL_DATE" not in trades.columns:
        return pd.DataFrame(), False, "NO_TRADES_FOR_WALK_FORWARD"
    t = trades.copy()
    t["SIGNAL_DATE"] = pd.to_datetime(t["SIGNAL_DATE"])
    start, end = t.SIGNAL_DATE.min(), t.SIGNAL_DATE.max()
    span_days = (end - start).days
    if span_days < BT.walk_forward_test_days * 2:
        return pd.DataFrame(), False, "INSUFFICIENT_HISTORY_FOR_WALK_FORWARD"

    windows = []
    cur = start
    while cur < end:
        stop = cur + pd.Timedelta(days=BT.walk_forward_test_days)
        wt = t[(t.SIGNAL_DATE >= cur) & (t.SIGNAL_DATE < stop)]
        if len(wt) > 0:
            s = _stats(wt)
            s["WINDOW_START"] = cur.strftime("%Y-%m-%d")
            s["WINDOW_END"] = min(stop, end).strftime("%Y-%m-%d")
            windows.append(s)
        cur = stop
    if not windows:
        return pd.DataFrame(), False, "NO_WALK_FORWARD_WINDOWS"

    wdf = pd.DataFrame(windows)
    eligible = wdf[wdf.trades >= max(5, BT.min_oos_trades // 10)]  # skip windows too thin to judge
    if eligible.empty:
        return wdf, False, "ALL_WALK_FORWARD_WINDOWS_TOO_THIN"
    passing = eligible[(eligible.profit_factor >= BT.min_quality_profit_factor) & (eligible.median_return_pct > 0)]
    pass_frac = len(passing) / len(eligible)
    ok = pass_frac >= 0.6  # edge must show up in at least 60% of judgeable windows, not just on average
    reason = "PASS" if ok else f"INCONSISTENT_ACROSS_WINDOWS_{round(pass_frac*100,0)}PCT"
    return wdf, ok, reason



    """Walk-forward backtest for the 52-week-low reversal scanner — same
    no-lookahead methodology as run_backtest() above (re-evaluate the signal
    at each historical day using only data available up to that day, enter
    next day's open, simulate the outcome), reusing the same outcome()/_stats()
    harness. This is what tells us whether EARLY REVERSAL BUY / REVERSAL WATCH
    have ever actually made money historically, vs just being a plausible
    pattern with no track record."""
    horizon=BT.horizon if horizon is None else int(horizon);rows=[]
    for sym,raw in hist.groupby('SYMBOL'):
        if sym==NIFTY_SYMBOL:continue
        g=add_indicators(raw).sort_values('DATE').reset_index(drop=True)
        if len(g)<MIN_HISTORY+horizon+1:continue
        last=-999
        for i in range(MIN_HISTORY,len(g)-horizon-1):
            if i-last<BT.min_gap_between_signals:continue
            try:f=_low52_features(g,i)
            except Exception:continue
            action=f.get('action')
            if action not in ('EARLY REVERSAL BUY','REVERSAL WATCH'):continue
            entry_i=i+1;entry=_num(f.get('entry'));stop=_num(f.get('stop'));t1=_num(f.get('t1'));t2=_num(f.get('t2'));t3=_num(f.get('t3'))
            if entry<=0 or stop<=0 or stop>=entry or not(entry<t1<t2<t3):continue
            o=outcome(g,entry_i,entry,stop,t1,t2,t3,horizon)
            if o:rows.append({'SYMBOL':sym,'SIGNAL_DATE':g.iloc[i].DATE,'BUY_DATE':g.iloc[entry_i].DATE,'SCORE':f.get('score',0),'ACTION':action,'ENTRY':o['FILL'],'STOP':stop,'T1':t1,'T2':t2,'T3':t3,**o});last=i
    trades=pd.DataFrame(rows);stats=_stats(trades);action_stats=[]
    if not trades.empty:
        for action,grp in trades.groupby('ACTION'):
            s=_stats(grp);s['ACTION']=action;action_stats.append(s)
    stats['action_stats']=[dict(a) for a in action_stats]
    return trades,stats


def run_backtest_apex(hist,horizon=None):
    """Walk-forward backtest for the APEX MATRIX (Pine Script port) scanner.
    Regime/penalty is looked up PER HISTORICAL DAY (via _apex_regime_series),
    not 'today's' regime, so old signals are judged against the market
    condition that actually existed on that day — using today's regime for a
    year-old signal would leak future information into the backtest.
    NOTE: Pine's own indicator only defines Target 1 (2R) and Target 2 (3R).
    A synthetic Target 3 (4R, matching the hunter's third-leg convention) is
    added here purely so the shared 3-target partial-exit outcome() model has
    somewhere to put the final scaled-out portion — it is NOT part of the
    original Pine logic, just a backtesting convenience for the "let the
    remainder run" tranche."""
    horizon=BT.horizon if horizon is None else int(horizon);rows=[]
    regime_series=_apex_regime_series(hist)
    if regime_series is None or regime_series.empty:
        return pd.DataFrame(),{'trades':0,'error':'NO_NIFTY_REGIME_DATA'}
    date_penalty=dict(zip(regime_series.DATE,regime_series.PENALTY))
    nifty_df=regime_series[['DATE','NIFTY_RET_20D']] if 'NIFTY_RET_20D' in regime_series.columns else None
    for sym,raw in hist.groupby('SYMBOL'):
        if sym==NIFTY_SYMBOL:continue
        g=add_indicators(raw).sort_values('DATE').reset_index(drop=True)
        if len(g)<MIN_HISTORY+horizon+1:continue
        last=-999
        for i in range(MIN_HISTORY,len(g)-horizon-1):
            if i-last<BT.min_gap_between_signals:continue
            day_date=g.iloc[i].DATE;penalty=date_penalty.get(day_date)
            if penalty is None or (isinstance(penalty,float) and pd.isna(penalty)):continue
            regime_info={'penalty':int(penalty),'nifty_df':nifty_df}
            try:f=_apex_features(g,i,regime_info)
            except Exception:continue
            if f is None or not f.get('entry_type'):continue
            entry_i=i+1;entry=_num(f.get('close'));stop=_num(f.get('initial_sl'));t1=_num(f.get('target1'));t2=_num(f.get('target2'))
            t3=entry+(entry-stop)*STRAT.min_rr3 if entry>stop else 0.0
            if entry<=0 or stop<=0 or stop>=entry or not(entry<t1<t2<t3):continue
            o=outcome(g,entry_i,entry,stop,t1,t2,t3,horizon)
            if o:rows.append({'SYMBOL':sym,'SIGNAL_DATE':day_date,'BUY_DATE':g.iloc[entry_i].DATE,'SCORE':f.get('apex_score',0),'ACTION':f['entry_type'],'ENTRY':o['FILL'],'STOP':stop,'T1':t1,'T2':t2,'T3':t3,**o});last=i
    trades=pd.DataFrame(rows);stats=_stats(trades);action_stats=[]
    if not trades.empty:
        for action,grp in trades.groupby('ACTION'):
            s=_stats(grp);s['ACTION']=action;action_stats.append(s)
    stats['action_stats']=[dict(a) for a in action_stats]
    return trades,stats


def run_backtest_stealth(hist,horizon=None):
    """Walk-forward backtest for the Stealth Accumulation scanner — same
    no-lookahead methodology as the other backtests (re-evaluate at each
    historical day using only data available up to that day, enter next day's
    open, simulate the outcome)."""
    horizon=BT.horizon if horizon is None else int(horizon);rows=[]
    for sym,raw in hist.groupby('SYMBOL'):
        if sym==NIFTY_SYMBOL:continue
        g=add_indicators(raw).sort_values('DATE').reset_index(drop=True)
        if len(g)<MIN_HISTORY+horizon+1:continue
        last=-999
        for i in range(MIN_HISTORY,len(g)-horizon-1):
            if i-last<BT.min_gap_between_signals:continue
            try:f=_stealth_features(g,i)
            except Exception:continue
            action=f.get('action')
            if action not in ('STEALTH BUY','STEALTH WATCH'):continue
            entry_i=i+1;entry=_num(f.get('entry'));stop=_num(f.get('stop'));t1=_num(f.get('t1'));t2=_num(f.get('t2'));t3=_num(f.get('t3'))
            if entry<=0 or stop<=0 or stop>=entry or not(entry<t1<t2<t3):continue
            o=outcome(g,entry_i,entry,stop,t1,t2,t3,horizon)
            if o:rows.append({'SYMBOL':sym,'SIGNAL_DATE':g.iloc[i].DATE,'BUY_DATE':g.iloc[entry_i].DATE,'SCORE':f.get('score',0),'ACTION':action,'ENTRY':o['FILL'],'STOP':stop,'T1':t1,'T2':t2,'T3':t3,**o});last=i
    trades=pd.DataFrame(rows);stats=_stats(trades);action_stats=[]
    if not trades.empty:
        for action,grp in trades.groupby('ACTION'):
            s=_stats(grp);s['ACTION']=action;action_stats.append(s)
    stats['action_stats']=[dict(a) for a in action_stats]
    return trades,stats

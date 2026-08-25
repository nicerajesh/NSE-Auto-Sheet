from __future__ import annotations
import pandas as pd
from indicator import add_indicators
from strategy import analyze_stock
from config import BT

def _rebase_levels(sig_price, entry, stop, t1, t2, t3):
    if sig_price<=0:return entry,stop,t1,t2,t3
    scale=entry/sig_price
    return entry,stop*scale,t1*scale,t2*scale,t3*scale

def outcome(g,entry_i,entry,stop,t1,t2,t3,horizon=30):
    f=g.iloc[entry_i:entry_i+horizon]
    if f.empty:return None
    active_stop=float(stop);rem=1.0;realised=0.0
    hit1=hit2=hit3=False;initial_stop_hit=False;breakeven_exit=False;stop_hit=False;exit_idx=None;exit_reason='TIME';max_high=entry;min_low=entry
    for j,row in f.iterrows():
        op=float(row.OPEN_PRICE);lo=float(row.LOW_PRICE);hi=float(row.HIGH_PRICE);cl=float(row.CLOSE_PRICE)
        max_high=max(max_high,hi);min_low=min(min_low,lo)
        if op<=active_stop:
            realised += rem*(op-entry)/entry*100
            if not hit1:initial_stop_hit=True
            else:breakeven_exit=True
            stop_hit=True;rem=0.0;exit_idx=j;exit_reason='GAP_STOP' if not hit1 else 'LOCKED_GAP_STOP';break
        if not hit1 and op>=t1:
            realised += .40*(op-entry)/entry*100;rem-=.40;hit1=True;active_stop=max(active_stop,entry)
        elif not hit1 and hi>=t1:
            realised += .40*(t1-entry)/entry*100;rem-=.40;hit1=True;active_stop=max(active_stop,entry)
        if lo<=active_stop:
            realised += rem*(active_stop-entry)/entry*100
            if not hit1:initial_stop_hit=True
            else:breakeven_exit=True
            stop_hit=True;rem=0.0;exit_idx=j;exit_reason='STOP' if not hit2 else 'LOCKED_T2';break
        if not hit2 and op>=t2:
            realised += .30*(op-entry)/entry*100;rem-=.30;hit2=True;active_stop=max(active_stop,t1)
        elif not hit2 and hi>=t2:
            realised += .30*(t2-entry)/entry*100;rem-=.30;hit2=True;active_stop=max(active_stop,t1)
        if lo<=active_stop:
            realised += rem*(active_stop-entry)/entry*100
            if not hit1:initial_stop_hit=True
            else:breakeven_exit=True
            stop_hit=True;rem=0.0;exit_idx=j;exit_reason='STOP' if not hit3 else 'LOCKED_T3';break
        if not hit3 and op>=t3:
            realised += rem*(op-entry)/entry*100;rem=0.0;hit3=True;exit_idx=j;exit_reason='T3_GAP';break
        if not hit3 and hi>=t3:
            realised += rem*(t3-entry)/entry*100;rem=0.0;hit3=True;exit_idx=j;exit_reason='T3';break
    if exit_idx is None:
        exit_idx=f.index[-1];realised += rem*(float(f.iloc[-1].CLOSE_PRICE)-entry)/entry*100
    if hit3:hit2=True;hit1=True
    if hit2:hit1=True
    cost=(BT.commission_bps+BT.slippage_bps)*2/100
    risk=max(1e-9,entry-stop)
    return {'HIT_T1':hit1,'HIT_T2':hit2,'HIT_T3':hit3,'STOP_HIT':stop_hit,'INITIAL_STOP_HIT':initial_stop_hit,'BREAKEVEN_EXIT':breakeven_exit,'RETURN_PCT':realised-cost,'GROSS_RETURN_PCT':realised,'HOLD_DAYS':int(exit_idx-entry_i+1),'MFE_PCT':(max_high-entry)/entry*100,'MAE_PCT':(min_low-entry)/entry*100,'MFE_R':(max_high-entry)/risk,'MAE_R':(min_low-entry)/risk}

def _horizon_rows(trades,hist,horizons=(5,10,15,20,30)):
    rows=[]
    if trades.empty:return pd.DataFrame()
    for h in horizons:
        vals=[]
        for _,r in trades.iterrows():
            g=hist[hist.SYMBOL.eq(r['SYMBOL'])].sort_values('DATE').reset_index(drop=True);j=int(r['ENTRY_INDEX'])+h-1
            if j>=len(g):continue
            vals.append((float(g.iloc[j].CLOSE_PRICE)-float(r.ENTRY))/float(r.ENTRY)*100)
        s=pd.Series(vals,dtype='float64')
        rows.append({'HORIZON_DAYS':h,'TRADES':len(s),'WIN_RATE':round((s>0).mean()*100,2) if len(s) else 0,'AVG_RETURN':round(s.mean(),2) if len(s) else 0,'MEDIAN_RETURN':round(s.median(),2) if len(s) else 0})
    return pd.DataFrame(rows)

def run_backtest(hist,min_score=None,horizon=None):
    threshold=BT.min_score if min_score is None else min_score;horizon=BT.horizon if horizon is None else horizon;rows=[]
    for sym,raw in hist.groupby('SYMBOL'):
        g=add_indicators(raw).sort_values('DATE').reset_index(drop=True)
        if len(g)<BT.warmup+horizon:continue
        last=-999
        for i in range(BT.warmup,len(g)-horizon):
            if i-last<BT.min_gap_between_signals:continue
            sig=analyze_stock(g.iloc[:i+1],threshold)
            if not sig or sig['HUNTER_SCORE']<threshold or sig['ACTION'] not in ('BUY','BUY ON TRIGGER'):continue
            signal_close=float(sig['CMP']);trigger=float(sig['ENTRY_TRIGGER'])
            if sig['ACTION']=='BUY ON TRIGGER':
                entry_i=None;entry=None
                for j in range(i+1,min(len(g),i+1+horizon)):
                    if float(g.iloc[j].HIGH_PRICE)>=trigger:entry_i=j;entry=trigger;break
                if entry_i is None:continue
            else:
                entry_i=i+1
                if entry_i>=len(g):continue
                entry=float(g.iloc[entry_i].OPEN_PRICE)
            entry,stop,t1,t2,t3=_rebase_levels(signal_close,entry,float(sig['STOP_LOSS']),float(sig['TARGET_1']),float(sig['TARGET_2']),float(sig['TARGET_3']))
            if entry<=0 or stop>=entry or t1<=entry or not (t1<t2<t3):continue
            available=min(horizon,len(g)-entry_i);o=outcome(g,entry_i,entry,stop,t1,t2,t3,available)
            if o:
                rows.append({'SYMBOL':sym,'SIGNAL_DATE':g.iloc[i].DATE,'SCORE':sig['HUNTER_SCORE'],'STAGE':sig['STAGE'],'ACTION':sig['ACTION'],'STRUCTURE':sig['STRUCTURE'],'ENTRY':entry,'ENTRY_INDEX':entry_i,'STOP':stop,'T1':t1,'T2':t2,'T3':t3,**o});last=entry_i
    trades=pd.DataFrame(rows)
    if trades.empty:return trades,{'trades':0},pd.DataFrame()
    pos=trades[trades.RETURN_PCT>0];neg=trades[trades.RETURN_PCT<0]
    stats={'trades':len(trades),'win_rate_pct':round((trades.RETURN_PCT>0).mean()*100,2),'median_return_pct':round(trades.RETURN_PCT.median(),2),'avg_return_pct':round(trades.RETURN_PCT.mean(),2),'stop_rate_pct':round(trades.INITIAL_STOP_HIT.mean()*100,2),'breakeven_exit_pct':round(trades.BREAKEVEN_EXIT.mean()*100,2),'total_stop_or_breakeven_pct':round(trades.STOP_HIT.mean()*100,2),'t1_hit_pct':round(trades.HIT_T1.mean()*100,2),'t2_hit_pct':round(trades.HIT_T2.mean()*100,2),'t3_hit_pct':round(trades.HIT_T3.mean()*100,2),'profit_factor':round(pos.RETURN_PCT.sum()/max(1e-9,-neg.RETURN_PCT.sum()),2),'avg_hold_days':round(trades.HOLD_DAYS.mean(),1),'expectancy_pct':round(trades.RETURN_PCT.mean(),2),'avg_mfe_pct':round(trades.MFE_PCT.mean(),2),'avg_mae_pct':round(trades.MAE_PCT.mean(),2),'median_mfe_pct':round(trades.MFE_PCT.median(),2),'median_mae_pct':round(trades.MAE_PCT.median(),2),'avg_mfe_r':round(trades.MFE_R.mean(),2),'avg_mae_r':round(trades.MAE_R.mean(),2)}
    buckets=pd.cut(trades.SCORE,[0,67,74,81,89,100],labels=['<68','68-74','75-81','82-89','90+'])
    cal=trades.assign(SCORE_BUCKET=buckets).groupby('SCORE_BUCKET',observed=False).agg(TRADES=('RETURN_PCT','size'),WIN_RATE=('RETURN_PCT',lambda s:round((s>0).mean()*100,2)),AVG_RETURN=('RETURN_PCT','mean'),MEDIAN_RETURN=('RETURN_PCT','median'),AVG_MFE=('MFE_PCT','mean'),AVG_MAE=('MAE_PCT','mean')).reset_index()
    cal[['AVG_RETURN','MEDIAN_RETURN','AVG_MFE','AVG_MAE']]=cal[['AVG_RETURN','MEDIAN_RETURN','AVG_MFE','AVG_MAE']].round(2)
    return trades,stats,pd.concat([cal.assign(ANALYSIS='SCORE_BUCKET'),_horizon_rows(trades,hist).assign(ANALYSIS='HORIZON')],ignore_index=True)

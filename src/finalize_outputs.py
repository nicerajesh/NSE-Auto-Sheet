from pathlib import Path
import pandas as pd
from quality_gate import evaluate, evaluate_action, parse_action_stats, EDGE_REASONS
from csv_utils import safe_to_csv, safe_read_csv
from risk_manager import apply_risk_management
from edge_monitor import compute_divergence

OUT=Path('output')


def _sector_map():
    p=OUT/'sector_map.csv'
    if not p.exists(): return {}
    df=safe_read_csv(p)
    if df.empty or 'SYMBOL' not in df.columns: return {}
    return dict(zip(df.SYMBOL.astype(str), df.SECTOR.astype(str)))


def main():
    hunter_path=OUT/'early_hunter.csv'
    stats_path=OUT/'backtest_summary.csv'
    cal_path=OUT/'score_calibration.csv'
    if not hunter_path.exists() or not stats_path.exists():
        raise RuntimeError('Required scanner outputs are missing')
    hunter=safe_read_csv(hunter_path)
    stats=safe_read_csv(stats_path).iloc[0].to_dict()
    cal=safe_read_csv(cal_path) if cal_path.exists() else pd.DataFrame()
    ok,reason=evaluate(stats,cal)
    hunter['QUALITY_GATE']='PASS' if ok else reason
    # Historical event confidence is used only when a bucket has enough observations.
    def confidence(r):
        try: score=float(r.get('PRE_BREAKOUT_SCORE',r.get('HUNTER_SCORE',0)))
        except Exception: score=0
        action=str(r.get('ACTION',''))
        if not cal.empty and {'ANALYSIS','ACTION','SCORE_BUCKET','BREAKOUT_RATE','TRADES'}.issubset(cal.columns):
            q=cal[(cal.ANALYSIS=='BREAKOUT_EVENT') & (cal.ACTION==action)].copy()
            bucket='90+' if score>=90 else '82-89' if score>=82 else '75-81' if score>=75 else '68-74' if score>=68 else '<68'
            q=q[(q.SCORE_BUCKET.astype(str)==bucket)&(q.TRADES>=5)]
            if not q.empty and pd.notna(q.BREAKOUT_RATE.iloc[0]): return round(float(q.BREAKOUT_RATE.iloc[0]),1)
        try:return min(90.0,max(0.0,float(r.get('BREAKOUT_PROBABILITY',0))))
        except Exception:return 0.0
    hunter['BREAKOUT_CONFIDENCE']=hunter.apply(confidence,axis=1) if not hunter.empty else pd.Series(dtype=float)
    # Never publish a model BUY when the historical quality gate fails — but a
    # systemic-vs-edge distinction matters: if the aggregate fails because the
    # blended profit-factor/win-rate/median is weak (usually the high-volume SWING
    # BUY category dragging the average down), gate PRE-BREAKOUT/BREAKOUT/SWING
    # independently on their own trade samples instead of blocking all three
    # together. A data-integrity failure (bad calibration, too few total trades)
    # still blocks everything, since that's a systemic problem, not one action's.
    action_stats={a.get('ACTION'):a for a in parse_action_stats(stats)}
    per_action_verdict={}
    if not ok and reason in EDGE_REASONS:
        for action in ('PRE-BREAKOUT BUY','BREAKOUT BUY','SWING BUY'):
            per_action_verdict[action]=evaluate_action(action_stats.get(action))
        print('PER-ACTION GATE:',{a:v for a,v in per_action_verdict.items()})
    def _gate_for(action):
        if ok:return 'PASS'
        if action in per_action_verdict:
            a_ok,a_reason=per_action_verdict[action]
            return 'PASS' if a_ok else a_reason
        return reason
    def _published(row):
        action=row.get('ACTION')
        if action not in {'PRE-BREAKOUT BUY','BREAKOUT BUY','SWING BUY'}:return action
        return action if _gate_for(action)=='PASS' else 'QUALITY BLOCKED'
    if not hunter.empty:
        hunter['QUALITY_GATE']=hunter['ACTION'].map(_gate_for).fillna('PASS' if ok else reason)
        hunter['PUBLISHED_ACTION']=hunter.apply(_published,axis=1)
    else:
        hunter['QUALITY_GATE']=pd.Series(dtype=object);hunter['PUBLISHED_ACTION']=pd.Series(dtype=object)

    # Money-management overlay: sizes every published BUY against real
    # capital/risk caps and the live drawdown kill-switch (risk_manager.py).
    # Purely additive -- never un-blocks anything quality_gate blocked above.
    ledger=safe_read_csv(OUT/'trade_ledger.csv') if (OUT/'trade_ledger.csv').exists() else pd.DataFrame()
    hunter=apply_risk_management(hunter,ledger,_sector_map())
    if not hunter.empty and 'RISK_MANAGER_STATUS' in hunter.columns:
        rblocked=hunter['PUBLISHED_ACTION'].isin({'PRE-BREAKOUT BUY','BREAKOUT BUY','SWING BUY'}) & ~hunter['RISK_MANAGER_STATUS'].isin({'PASS','N/A_GATE_BLOCKED','N/A'})
        if rblocked.any():
            print(f"RISK MANAGER: {int(rblocked.sum())} signal(s) cleared the quality gate but were blocked on money-management grounds (position caps / drawdown kill-switch) — see RISK_MANAGER_STATUS")
            hunter.loc[rblocked,'PUBLISHED_ACTION']='RISK BLOCKED (' + hunter.loc[rblocked,'RISK_MANAGER_STATUS'].astype(str) + ')'

    # Live-vs-backtest edge monitor: does real, realised performance still
    # match what the backtest promised? Purely diagnostic, blocks nothing.
    edge=compute_divergence(ledger,stats)
    safe_to_csv(edge,OUT/'edge_monitor.csv')
    decaying=edge[edge.get('EDGE_STATUS','')=='EDGE_DECAY_WARNING'] if not edge.empty else pd.DataFrame()
    if not decaying.empty:
        print(f"EDGE MONITOR WARNING: live results are underperforming the backtest for: {', '.join(decaying.ACTION.tolist())} — see edge_monitor.csv")

    safe_to_csv(hunter,hunter_path)
    safe_to_csv(hunter[hunter.get('PUBLISHED_ACTION','WATCH').isin({'PRE-BREAKOUT BUY','BREAKOUT BUY','SWING BUY'})],OUT/'buy_candidates.csv')
    stats['quality_gate']='PASS' if ok else reason
    safe_to_csv(pd.DataFrame([stats]),stats_path)
    print(f'FINAL QUALITY GATE={reason} | BUY PUBLISHED={int((hunter.PUBLISHED_ACTION.isin({"PRE-BREAKOUT BUY","BREAKOUT BUY","SWING BUY"})).sum()) if not hunter.empty else 0}')

if __name__=='__main__': main()

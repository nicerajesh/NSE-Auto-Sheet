from pathlib import Path
import pandas as pd
from quality_gate import evaluate, evaluate_action, parse_action_stats, EDGE_REASONS
from csv_utils import safe_to_csv, safe_read_csv
from risk_manager import apply_risk_management
from edge_monitor import compute_divergence
from master_decision import build_master

OUT=Path('output')

V2_COLUMNS = [
    'RANK','SYMBOL','FINAL_ACTION','CMP','IDEAL_ENTRY','BUY_ZONE','MAX_BUY_PRICE',
    'BREAKOUT_TRIGGER','STOP_LOSS','TARGET_1','TARGET_2','TARGET_3','RISK_PCT',
    'EDGE_CONFIDENCE','EDGE_CONFIDENCE_LABEL','POSITION_QTY','CAPITAL_ALLOCATED',
    'RISK_AMOUNT','RISK_MANAGER_STATUS','QUALITY_GATE','ACTION','WHY','DECISION_REASON'
]


def _sector_map():
    p=OUT/'sector_map.csv'
    if not p.exists(): return {}
    df=safe_read_csv(p)
    if df.empty or 'SYMBOL' not in df.columns: return {}
    return dict(zip(df.SYMBOL.astype(str), df.SECTOR.astype(str)))


def _load_hunter():
    """Load Early Hunter; on a legitimate zero-signal day use Core Trend as
    context so downstream user-facing outputs are not blank. This fallback
    never grants a BUY: all BUY actions still pass through the quality gate.
    """
    p=OUT/'early_hunter.csv'
    hunter=safe_read_csv(p) if p.exists() else pd.DataFrame()
    if not hunter.empty:
        return hunter, False
    cp=OUT/'core_trend_matrix.csv'
    if not cp.exists():
        return hunter, False
    core=safe_read_csv(cp)
    if core.empty or not {'SYMBOL','ACTION'}.issubset(core.columns):
        return hunter, False
    hunter=core.copy()
    if 'RANK_SCORE' in hunter.columns and 'HUNTER_SCORE' not in hunter.columns:
        hunter['HUNTER_SCORE']=hunter['RANK_SCORE']
    if 'ENTRY_PRICE' in hunter.columns and 'IDEAL_ENTRY' not in hunter.columns:
        hunter['IDEAL_ENTRY']=hunter['ENTRY_PRICE']
    hunter['SOURCE_CONTEXT']='CORE_TREND_FALLBACK_NO_SIGNAL'
    return hunter, True


def _write_v2_master():
    """Materialize V2 from the best available current candidate/context source."""
    preferred=OUT/'decision_candidates.csv'
    fallback=OUT/'early_hunter.csv'
    if preferred.exists():
        df=safe_read_csv(preferred)
        if df.empty and fallback.exists(): df=safe_read_csv(fallback)
    elif fallback.exists():
        df=safe_read_csv(fallback)
    else:
        raise RuntimeError('Neither decision_candidates.csv nor early_hunter.csv is available')

    regime=str(df.iloc[0].get('MARKET_REGIME','UNKNOWN')) if not df.empty else 'UNKNOWN'
    master=build_master(df, regime)
    for col in V2_COLUMNS:
        if col not in master.columns:
            if col == 'QUALITY_GATE': master[col] = 'PASS' if master.empty else 'BLOCK'
            elif col == 'FINAL_ACTION': master[col] = 'NO SETUP'
            elif col == 'ACTION': master[col] = 'WATCH'
            elif col == 'EDGE_CONFIDENCE_LABEL': master[col] = 'UNKNOWN'
            else: master[col] = pd.NA
    master=master[V2_COLUMNS]
    safe_to_csv(master,OUT/'master_buy_decision_v2.csv')
    print('V2 MASTER READY:',len(master),'rows | output/master_buy_decision_v2.csv | QUALITY_GATE=',master['QUALITY_GATE'].value_counts(dropna=False).to_dict())


def main():
    stats_path=OUT/'backtest_summary.csv'
    cal_path=OUT/'score_calibration.csv'
    if not stats_path.exists():
        raise RuntimeError('Required scanner outputs are missing')

    hunter,used_core_fallback=_load_hunter()
    stats=safe_read_csv(stats_path).iloc[0].to_dict()
    cal=safe_read_csv(cal_path) if cal_path.exists() else pd.DataFrame()
    ok,reason=evaluate(stats,cal)

    def confidence(r):
        try: score=float(r.get('PRE_BREAKOUT_SCORE',r.get('HUNTER_SCORE',0)))
        except Exception: score=0
        if not cal.empty and {'ANALYSIS','ACTION','SCORE_BUCKET','BREAKOUT_RATE','TRADES'}.issubset(cal.columns):
            q=cal[(cal.ANALYSIS=='BREAKOUT_EVENT') & (cal.ACTION==r.get('ACTION'))].copy()
            bucket='90+' if score>=90 else '82-89' if score>=82 else '75-81' if score>=75 else '68-74' if score>=68 else '<68'
            q=q[(q.SCORE_BUCKET.astype(str)==bucket)&(q.TRADES>=5)]
            if not q.empty and pd.notna(q.BREAKOUT_RATE.iloc[0]): return round(float(q.BREAKOUT_RATE.iloc[0]),1)
        try:return min(90.0,max(0.0,float(r.get('BREAKOUT_PROBABILITY',0))))
        except Exception:return 0.0

    hunter['BREAKOUT_CONFIDENCE']=hunter.apply(confidence,axis=1) if not hunter.empty else pd.Series(dtype=float)
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
        if used_core_fallback:
            # Core Trend context is explicitly marked; it is not an additional
            # release path and cannot turn a blocked setup into a live BUY.
            hunter['SOURCE_CONTEXT']='CORE_TREND_FALLBACK_NO_SIGNAL'
    else:
        hunter['QUALITY_GATE']=pd.Series(dtype=object)
        hunter['PUBLISHED_ACTION']=pd.Series(dtype=object)

    ledger=safe_read_csv(OUT/'trade_ledger.csv') if (OUT/'trade_ledger.csv').exists() else pd.DataFrame()
    hunter=apply_risk_management(hunter,ledger,_sector_map())
    if not hunter.empty and 'RISK_MANAGER_STATUS' in hunter.columns:
        rblocked=hunter['PUBLISHED_ACTION'].isin({'PRE-BREAKOUT BUY','BREAKOUT BUY','SWING BUY'}) & ~hunter['RISK_MANAGER_STATUS'].isin({'PASS','N/A_GATE_BLOCKED','N/A'})
        if rblocked.any():
            print(f"RISK MANAGER: {int(rblocked.sum())} signal(s) cleared the quality gate but were blocked on money-management grounds (position caps / drawdown kill-switch) — see RISK_MANAGER_STATUS")
            hunter.loc[rblocked,'PUBLISHED_ACTION']='RISK BLOCKED (' + hunter.loc[rblocked,'RISK_MANAGER_STATUS'].astype(str) + ')'

    edge=compute_divergence(ledger,stats)
    safe_to_csv(edge,OUT/'edge_monitor.csv')
    decaying=edge[edge.get('EDGE_STATUS','')=='EDGE_DECAY_WARNING'] if not edge.empty else pd.DataFrame()
    if not decaying.empty:
        print(f"EDGE MONITOR WARNING: live results are underperforming the backtest for: {', '.join(decaying.ACTION.tolist())} — see edge_monitor.csv")

    safe_to_csv(hunter,OUT/'early_hunter.csv')
    safe_to_csv(hunter[hunter.get('PUBLISHED_ACTION','WATCH').isin({'PRE-BREAKOUT BUY','BREAKOUT BUY','SWING BUY'})],OUT/'buy_candidates.csv')
    stats['quality_gate']='PASS' if ok else reason
    safe_to_csv(pd.DataFrame([stats]),stats_path)
    _write_v2_master()
    published=int(hunter.PUBLISHED_ACTION.isin({'PRE-BREAKOUT BUY','BREAKOUT BUY','SWING BUY'}).sum()) if not hunter.empty else 0
    print(f'FINAL QUALITY GATE={reason} | BUY PUBLISHED={published} | CORE_FALLBACK={used_core_fallback}')

if __name__=='__main__': main()

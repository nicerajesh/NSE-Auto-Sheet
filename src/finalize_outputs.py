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

BUY_ACTIONS={'PRE-BREAKOUT BUY','BREAKOUT BUY','SWING BUY'}


def _sector_map():
    p=OUT/'sector_map.csv'
    if not p.exists(): return {}
    df=safe_read_csv(p)
    if df.empty or 'SYMBOL' not in df.columns: return {}
    return dict(zip(df.SYMBOL.astype(str), df.SECTOR.astype(str)))


def _load_hunter():
    """Load candidate context without converting a failed quality gate into BUY."""
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

    # Canonicalize technical setup labels. These are NOT released BUY signals.
    if 'ACTION' in hunter.columns:
        hunter['TECHNICAL_ACTION']=hunter['ACTION'].astype(str)
        hunter['ACTION']=hunter['ACTION'].replace({
            'STRONG BUY':'SWING BUY',
            'BUY ON PULLBACK':'SWING BUY',
        })

    # Core Trend Matrix has no scanner-time trade plan. Build a deterministic
    # research plan from CMP + ATR; validation still happens downstream.
    cmpv=pd.to_numeric(hunter.get('CMP'),errors='coerce')
    atrp=pd.to_numeric(hunter.get('ATR_PCT'),errors='coerce')
    atr_abs=cmpv*atrp/100.0
    entry=cmpv
    stop=entry-1.6*atr_abs
    target1=entry+2.0*(entry-stop)
    target2=entry+3.0*(entry-stop)
    target3=entry+4.0*(entry-stop)
    hunter['IDEAL_ENTRY']=entry
    hunter['STOP_LOSS']=stop
    hunter['TARGET_1']=target1
    hunter['TARGET_2']=target2
    hunter['TARGET_3']=target3
    hunter['RISK_PCT']=((entry-stop)/entry*100).round(2)
    hunter['ATR_RISK_PCT']=atrp
    hunter['BUY_ZONE']=entry.map(lambda x: f'{x*0.99:.2f} - {x*1.01:.2f}' if pd.notna(x) else '')
    hunter['MAX_BUY_PRICE']=entry*1.015
    hunter['SOURCE_CONTEXT']='CORE_TREND_FALLBACK_TECHNICAL_CANDIDATE'
    return hunter, True


def _write_v2_master():
    """Materialize V2 from the same canonical source used by finalization."""
    # Never allow an empty/failed intermediate decision_candidates.csv to erase
    # a valid Core Trend fallback. This was the source of zero-row V2 failures.
    df, used_core = _load_hunter()
    if df.empty:
        raise RuntimeError('No candidate context available: early_hunter.csv and core_trend_matrix.csv are both empty')
    regime=str(df.iloc[0].get('MARKET_REGIME','UNKNOWN'))
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


def _safe_bool(v):
    if isinstance(v,bool): return v
    return str(v).strip().lower() in {'true','1','yes','y','pass'}


def _buy_quality_ok(row):
    """Second-stage candidate safety filter. It only removes BUYs; it never creates one."""
    # Require a complete executable trade plan.
    required=('CMP','IDEAL_ENTRY','STOP_LOSS','TARGET_1')
    try:
        vals=[float(row.get(c)) for c in required]
        if any(pd.isna(x) or x<=0 for x in vals): return False, 'INCOMPLETE_TRADE_PLAN'
    except Exception:
        return False, 'INCOMPLETE_TRADE_PLAN'

    try:
        entry=float(row.get('IDEAL_ENTRY'))
        stop=float(row.get('STOP_LOSS'))
        target=float(row.get('TARGET_1'))
        risk=entry-stop
        reward=target-entry
        if risk<=0 or reward<=0: return False, 'INVALID_RISK_REWARD'
        if reward/risk < 1.8: return False, 'LOW_RR'
    except Exception:
        return False, 'INVALID_RISK_REWARD'

    # If available, use technical confirmation fields as hard safety filters.
    for col in ('LIQUIDITY_STATUS','Liquidity Status'):
        if col in row and str(row.get(col)).strip() and str(row.get(col)).strip().upper() in {'LOW','POOR','FAIL'}:
            return False, 'LOW_LIQUIDITY'
    for col in ('ATR_RISK_PCT','ATR Risk %'):
        if col in row:
            try:
                atr=float(row.get(col))
                if pd.notna(atr) and not (0 < atr <= 5): return False, 'HIGH_ATR_RISK'
            except Exception: pass
    return True, 'PASS'


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
        for action in BUY_ACTIONS:
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
        if action not in BUY_ACTIONS:return action
        gate=_gate_for(action)
        if gate!='PASS': return 'QUALITY BLOCKED ('+str(gate)+')'
        safe,safe_reason=_buy_quality_ok(row)
        return action if safe else 'QUALITY BLOCKED ('+safe_reason+')'

    if not hunter.empty:
        hunter['QUALITY_GATE']=hunter['ACTION'].map(_gate_for).fillna('PASS' if ok else reason)
        hunter['PUBLISHED_ACTION']=hunter.apply(_published,axis=1)
        hunter['BUY_ELIGIBLE']=hunter['PUBLISHED_ACTION'].isin(BUY_ACTIONS)
        if used_core_fallback:
            hunter['SOURCE_CONTEXT']='CORE_TREND_FALLBACK_NO_SIGNAL'
    else:
        hunter['QUALITY_GATE']=pd.Series(dtype=object)
        hunter['PUBLISHED_ACTION']=pd.Series(dtype=object)
        hunter['BUY_ELIGIBLE']=pd.Series(dtype=bool)

    ledger=safe_read_csv(OUT/'trade_ledger.csv') if (OUT/'trade_ledger.csv').exists() else pd.DataFrame()
    hunter=apply_risk_management(hunter,ledger,_sector_map())
    if not hunter.empty and 'RISK_MANAGER_STATUS' in hunter.columns:
        rblocked=hunter['PUBLISHED_ACTION'].isin(BUY_ACTIONS) & ~hunter['RISK_MANAGER_STATUS'].isin({'PASS','N/A_GATE_BLOCKED','N/A'})
        if rblocked.any():
            print(f'RISK MANAGER: {int(rblocked.sum())} signal(s) blocked by position/drawdown controls')
            hunter.loc[rblocked,'PUBLISHED_ACTION']='RISK BLOCKED (' + hunter.loc[rblocked,'RISK_MANAGER_STATUS'].astype(str) + ')'
            hunter.loc[rblocked,'BUY_ELIGIBLE']=False

    edge=compute_divergence(ledger,stats)
    safe_to_csv(edge,OUT/'edge_monitor.csv')

    # User-facing BUY report: only executable BUY rows. Blocked/watch/context rows remain in Early Hunter.
    safe_to_csv(hunter,OUT/'early_hunter.csv')
    buy=hunter[hunter['BUY_ELIGIBLE']].copy() if not hunter.empty else pd.DataFrame(columns=hunter.columns)
    if not buy.empty:
        sort_cols=[c for c in ('EDGE_CONFIDENCE','HUNTER_SCORE','PRE_BREAKOUT_SCORE') if c in buy.columns]
        if sort_cols: buy=buy.sort_values(sort_cols,ascending=False,kind='mergesort')
        buy.insert(0,'BUY_RANK',range(1,len(buy)+1))
    safe_to_csv(buy,OUT/'buy_candidates.csv')

    stats['quality_gate']='PASS' if ok else reason
    safe_to_csv(pd.DataFrame([stats]),stats_path)
    _write_v2_master()
    published=int(hunter['BUY_ELIGIBLE'].sum()) if not hunter.empty else 0
    print(f'FINAL QUALITY GATE={reason} | BUY PUBLISHED={published} | CORE_FALLBACK={used_core_fallback}')

if __name__=='__main__': main()

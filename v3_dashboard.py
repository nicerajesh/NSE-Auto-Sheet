from __future__ import annotations
import pandas as pd
from pathlib import Path
from decision_engine import classify_portfolio
from v3_engine import apply_v3
from quality_gate import evaluate, evaluate_action, parse_action_stats, EDGE_REASONS
from csv_utils import safe_to_csv, safe_read_csv

OUT=Path('output')

# Columns the workflow's "Validate Decision Outputs" step explicitly requires
# to exist in decision_candidates.csv (see .github/workflows/main.yml). On a
# day with zero hunter candidates, `enriched` is just `base.copy()` and never
# goes through apply_v3(), so these columns would otherwise be missing and
# fail that check even though zero-candidates is a perfectly valid outcome.
REQUIRED_DECISION_COLS=['V3_TIMING_SCORE','V3_OPPORTUNITY_SCORE','BREAKOUT_CHANCE_PCT',
    'UPSIDE_EXPECTED_PCT','UPSIDE_BEST_CASE_PCT','USER_ACTION','IDEAL_ENTRY','BUY_ZONE','MAX_BUY_PRICE']

def _real_gate():
    """early_hunter.csv's QUALITY_GATE column is only set to its real PASS/FAIL
    value later by finalize_outputs.py, which runs *after* this script in the
    pipeline. Reading it here always sees the strategy.py default 'PENDING',
    which would incorrectly block every signal. Compute the real gate here
    from the backtest artifacts that already exist at this point instead.

    Also returns a per-action verdict dict: if the aggregate fails for an
    edge-quality reason (weak blended PF/win-rate/median — typically the
    high-volume SWING BUY category dragging the average down), each of
    PRE-BREAKOUT/BREAKOUT/SWING is evaluated independently on its own trade
    sample so a genuinely edge-positive action isn't blocked by a different
    one. A systemic/data-integrity failure still blocks everything."""
    stats_path=OUT/'backtest_summary.csv'; cal_path=OUT/'score_calibration.csv'
    if not stats_path.exists():
        return False,'MISSING_BACKTEST_SUMMARY',{}
    stats=safe_read_csv(stats_path).iloc[0].to_dict()
    cal=safe_read_csv(cal_path) if cal_path.exists() else pd.DataFrame()
    ok,reason=evaluate(stats,cal)
    per_action={}
    if not ok and reason in EDGE_REASONS:
        action_rows={a.get('ACTION'):a for a in parse_action_stats(stats)}
        for action in ('PRE-BREAKOUT BUY','BREAKOUT BUY','SWING BUY'):
            per_action[action]=evaluate_action(action_rows.get(action))
        print('PER-ACTION GATE:',per_action)
    return ok,reason,per_action


def _gate_for(action,ok,reason,per_action):
    if ok:return True,'PASS'
    if action in per_action:
        a_ok,a_reason=per_action[action]
        return a_ok,('PASS' if a_ok else a_reason)
    return False,reason


def main():
    src=OUT/'early_hunter.csv'; hist_path=OUT/'persistent_history.csv'
    if not src.exists(): raise RuntimeError('output/early_hunter.csv missing')
    if not hist_path.exists(): raise RuntimeError('output/persistent_history.csv missing')
    base=safe_read_csv(src); hist=pd.read_csv(hist_path,parse_dates=['DATE'])
    if 'SYMBOL' not in hist.columns: raise RuntimeError('persistent_history.csv missing SYMBOL')
    enriched=pd.DataFrame([apply_v3(r.to_dict(),hist) for _,r in base.iterrows()]) if not base.empty else base.copy()
    enriched=classify_portfolio(enriched)
    # Zero-candidate day: base never went through apply_v3(), so guarantee the
    # columns the workflow's validation step requires still exist (empty).
    for col in REQUIRED_DECISION_COLS:
        if col not in enriched.columns: enriched[col]=pd.Series(dtype=object)
    gate_ok,gate_reason,per_action=_real_gate()
    if not enriched.empty:
        verdicts=enriched['ACTION'].map(lambda a:_gate_for(a,gate_ok,gate_reason,per_action))
        enriched['QUALITY_GATE']=verdicts.map(lambda t:t[1])
        actionable=enriched['ACTION'].isin({'PRE-BREAKOUT BUY','BREAKOUT BUY','SWING BUY'})
        blocked=actionable & verdicts.map(lambda t:not t[0])
        if blocked.any():
            enriched.loc[blocked,'USER_ACTION']='🔴 ABHI MAT KHARIDO — QUALITY GATE BLOCKED (' + enriched.loc[blocked,'QUALITY_GATE'].astype(str) + ')'
    safe_to_csv(enriched,OUT/'decision_candidates.csv')
    cols=['RANK','SYMBOL','USER_ACTION','CMP','IDEAL_ENTRY','BUY_ZONE','MAX_BUY_PRICE','BREAKOUT_TRIGGER','STOP_LOSS','TARGET_1','TARGET_2','TARGET_3','RISK_PCT','BREAKOUT_CHANCE_PCT','UPSIDE_EXPECTED_PCT','UPSIDE_BEST_CASE_PCT','CHANCE_PLUS10_PCT','CHANCE_PLUS20_PCT','CHANCE_PLUS30_PCT','CHANCE_PLUS50_PCT','ENTRY_TIMING','V3_TIMING_SCORE','V3_OPPORTUNITY_SCORE','WHY']
    cols=[c for c in cols if c in enriched.columns]; top=enriched[cols].head(30)
    human=pd.DataFrame({
        'RANK':top.get('RANK',pd.Series(dtype=int)),
        'STOCK':top.get('SYMBOL',pd.Series(dtype=str)),
        'KYA KARNA HAI':top.get('USER_ACTION',pd.Series(dtype=str)),
        'CMP':top.get('CMP',pd.Series(dtype=float)),
        'KHARIDNE KA PRICE':top.get('BUY_ZONE',pd.Series(dtype=str)),
        'BREAKOUT PRICE':top.get('BREAKOUT_TRIGGER',pd.Series(dtype=float)),
        'STOP LOSS':top.get('STOP_LOSS',pd.Series(dtype=float)),
        'TARGET 1':top.get('TARGET_1',pd.Series(dtype=float)),
        'TARGET 2':top.get('TARGET_2',pd.Series(dtype=float)),
        'TARGET 3':top.get('TARGET_3',pd.Series(dtype=float)),
        'EXPECTED UPSIDE':top.get('UPSIDE_EXPECTED_PCT',pd.Series(dtype=float)),
        'BEST CASE UPSIDE':top.get('UPSIDE_BEST_CASE_PCT',pd.Series(dtype=float)),
        'BREAKOUT CHANCE':top.get('BREAKOUT_CHANCE_PCT',pd.Series(dtype=float)),
        '10% CHANCE':top.get('CHANCE_PLUS10_PCT',pd.Series(dtype=float)),
        '20% CHANCE':top.get('CHANCE_PLUS20_PCT',pd.Series(dtype=float)),
        '30% CHANCE':top.get('CHANCE_PLUS30_PCT',pd.Series(dtype=float)),
        '50% CHANCE':top.get('CHANCE_PLUS50_PCT',pd.Series(dtype=float)),
        'TIMING':top.get('ENTRY_TIMING',pd.Series(dtype=str)),
        'V3 OPPORTUNITY':top.get('V3_OPPORTUNITY_SCORE',pd.Series(dtype=float)),
        'WHY':top.get('WHY',pd.Series(dtype=str)),
    })
    safe_to_csv(human,OUT/'trading_commands.csv')
    counts=human['KYA KARNA HAI'].value_counts(dropna=False).to_dict() if not human.empty else {}
    print('TRADING COMMANDS READY:',len(human),'|',counts)
    if not human.empty: print(human.head(15).to_string(index=False))

if __name__=='__main__':main()

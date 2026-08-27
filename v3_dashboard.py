from __future__ import annotations
import pandas as pd
from pathlib import Path
from decision_engine import classify_portfolio
from v3_engine import apply_v3

OUT=Path('output')

def main():
    src=OUT/'early_hunter.csv'; hist_path=OUT/'persistent_history.csv'
    if not src.exists(): raise RuntimeError('output/early_hunter.csv missing')
    if not hist_path.exists(): raise RuntimeError('output/persistent_history.csv missing')
    base=pd.read_csv(src); hist=pd.read_csv(hist_path,parse_dates=['DATE'])
    if 'SYMBOL' not in hist.columns: raise RuntimeError('persistent_history.csv missing SYMBOL')
    enriched=pd.DataFrame([apply_v3(r.to_dict(),hist) for _,r in base.iterrows()]) if not base.empty else base.copy()
    enriched=classify_portfolio(enriched)
    if not enriched.empty and 'QUALITY_GATE' in enriched.columns:
        gate=enriched.QUALITY_GATE.astype(str).iloc[0]
        if gate!='PASS':
            enriched['USER_ACTION']='🔴 ABHI MAT KHARIDO — QUALITY GATE BLOCKED'
    enriched.to_csv(OUT/'decision_candidates.csv',index=False)
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
    human.to_csv(OUT/'trading_commands.csv',index=False)
    counts=human['KYA KARNA HAI'].value_counts(dropna=False).to_dict() if not human.empty else {}
    print('TRADING COMMANDS READY:',len(human),'|',counts)
    if not human.empty: print(human.head(15).to_string(index=False))

if __name__=='__main__':main()

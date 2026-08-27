from __future__ import annotations
import pandas as pd
from pathlib import Path
from decision_engine import classify_portfolio, BUY_NOW, BUY_BREAKOUT, BUY_DIP, WAIT, AVOID

OUT=Path('output')


def _money(v):
    try:return f'₹{float(v):,.2f}'
    except:return '—'

def _pct(v):
    try:return f'{float(v):+.1f}%'
    except:return '—'

def main():
    src=OUT/'early_hunter.csv'
    if not src.exists(): raise RuntimeError('output/early_hunter.csv missing')
    df=pd.read_csv(src)
    # The decision engine enriches the raw hunter output. It intentionally does
    # not weaken the upstream quality gate or manufacture a BUY when the gate fails.
    enriched=classify_portfolio(df)
    if not enriched.empty and 'QUALITY_GATE' in enriched.columns:
        gate=enriched.QUALITY_GATE.astype(str).iloc[0]
        if gate!='PASS':
            enriched['USER_ACTION']='🔴 ABHI MAT KHARIDO — MODEL QUALITY GATE BLOCKED'
    enriched.to_csv(OUT/'decision_candidates.csv',index=False)

    cols=['RANK','SYMBOL','USER_ACTION','CMP','IDEAL_ENTRY','BUY_ZONE','MAX_BUY_PRICE','BREAKOUT_TRIGGER','STOP_LOSS','TARGET_1','TARGET_2','TARGET_3','RISK_PCT','BREAKOUT_CHANCE_PCT','UPSIDE_EXPECTED_PCT','UPSIDE_BEST_CASE_PCT','CHANCE_PLUS10_PCT','CHANCE_PLUS20_PCT','CHANCE_PLUS30_PCT','CHANCE_PLUS50_PCT','ENTRY_TIMING','WHY']
    cols=[c for c in cols if c in enriched.columns]
    top=enriched[cols].copy().head(30)
    # Human-readable command table for the Google Sheet publisher.
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
        'WHY':top.get('WHY',pd.Series(dtype=str)),
    })
    human.to_csv(OUT/'trading_commands.csv',index=False)
    counts={str(a):int((enriched.get('USER_ACTION',pd.Series(dtype=str))==a).sum()) for a in [BUY_NOW,BUY_BREAKOUT,BUY_DIP,WAIT,AVOID]}
    print('TRADING COMMANDS:',counts)
    print('Decision candidates:',len(top))

if __name__=='__main__':main()

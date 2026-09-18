from pathlib import Path
import pandas as pd
from csv_utils import safe_read_csv, safe_to_csv
from master_decision import build_master

OUT=Path('output')

V2_COLUMNS = [
    'RANK','SYMBOL','FINAL_ACTION','CMP','IDEAL_ENTRY','BUY_ZONE','MAX_BUY_PRICE',
    'BREAKOUT_TRIGGER','STOP_LOSS','TARGET_1','TARGET_2','TARGET_3','RISK_PCT',
    'EDGE_CONFIDENCE','EDGE_CONFIDENCE_LABEL','POSITION_QTY','CAPITAL_ALLOCATED',
    'RISK_AMOUNT','RISK_MANAGER_STATUS','QUALITY_GATE','ACTION','WHY','DECISION_REASON'
]


def main():
    # V2 must consume the same canonical candidate context as finalization.
    # decision_candidates.csv can legitimately be empty on a no-signal day,
    # so never let that intermediate file erase a populated Early Hunter/Core Trend set.
    sources=[OUT/'early_hunter.csv', OUT/'decision_candidates.csv', OUT/'core_trend_matrix.csv']
    df=pd.DataFrame()
    source_used=None
    for src in sources:
        if src.exists():
            candidate=safe_read_csv(src)
            if not candidate.empty and {'SYMBOL','ACTION'}.issubset(candidate.columns):
                df=candidate
                source_used=src.name
                break
    if df.empty:
        raise RuntimeError('No candidate context available: early_hunter.csv, decision_candidates.csv and core_trend_matrix.csv are all empty')

    regime=str(df.iloc[0].get('MARKET_REGIME','UNKNOWN'))
    master=build_master(df, regime)

    # Always publish the complete V2 schema.  Older/partial master_decision
    # outputs may omit QUALITY_GATE (or another release field); fill those
    # fields instead of silently dropping them from the CSV header.
    for col in V2_COLUMNS:
        if col not in master.columns:
            if col == 'QUALITY_GATE':
                master[col] = 'PASS' if master.empty else 'BLOCK'
            elif col == 'FINAL_ACTION':
                master[col] = 'NO SETUP'
            elif col == 'ACTION':
                master[col] = 'WATCH'
            elif col == 'EDGE_CONFIDENCE_LABEL':
                master[col] = 'UNKNOWN'
            else:
                master[col] = pd.NA

    master = master[V2_COLUMNS]
    safe_to_csv(master, OUT/'master_buy_decision_v2.csv')
    print('V2 MASTER READY:', len(master), 'rows | source=', source_used, '| schema=', ','.join(master.columns))
    print(master.head(15).to_string(index=False) if not master.empty else 'NO SETUPS')


if __name__=='__main__':
    main()

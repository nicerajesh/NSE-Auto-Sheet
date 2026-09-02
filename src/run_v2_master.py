from pathlib import Path
import pandas as pd
from csv_utils import safe_read_csv, safe_to_csv
from master_decision import build_master

OUT=Path('output')

def main():
    src=OUT/'decision_candidates.csv'
    if not src.exists():
        raise RuntimeError('output/decision_candidates.csv missing')
    df=safe_read_csv(src)
    regime=str(df.iloc[0].get('MARKET_REGIME','UNKNOWN')) if not df.empty else 'UNKNOWN'
    master=build_master(df, regime)
    cols=['RANK','SYMBOL','FINAL_ACTION','CMP','IDEAL_ENTRY','BUY_ZONE','MAX_BUY_PRICE','BREAKOUT_TRIGGER','STOP_LOSS','TARGET_1','TARGET_2','TARGET_3','RISK_PCT','EDGE_CONFIDENCE','EDGE_CONFIDENCE_LABEL','POSITION_QTY','CAPITAL_ALLOCATED','RISK_AMOUNT','RISK_MANAGER_STATUS','QUALITY_GATE','ACTION','WHY','DECISION_REASON']
    cols=[c for c in cols if c in master.columns]
    safe_to_csv(master[cols], OUT/'master_buy_decision_v2.csv')
    print('V2 MASTER READY:', len(master), 'rows')
    print(master[cols].head(15).to_string(index=False) if not master.empty else 'NO SETUPS')

if __name__=='__main__': main()

from __future__ import annotations
import json, os
from pathlib import Path
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials

SPREADSHEET_ID=os.getenv('SPREADSHEET_ID','1U9j5fMZAWPUSwoP_U-GKdacVke9nUjspqPR3wGsWAUM')
OUT=Path('output')
BUY_ACTIONS={'PRE-BREAKOUT BUY','BREAKOUT BUY','SWING BUY'}

def scalar(v):
    if v is None:return ''
    if isinstance(v,(dict,list,tuple,set)):return json.dumps(v,default=str,sort_keys=True)
    try:
        if pd.isna(v):return ''
    except Exception:pass
    if hasattr(v,'item'):
        try:return v.item()
        except Exception:pass
    return v

def book():
    raw=os.getenv('GCP_CREDENTIALS')
    if not raw:raise RuntimeError('GCP_CREDENTIALS secret missing')
    c=ServiceAccountCredentials.from_json_keyfile_dict(json.loads(raw),['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive'])
    return gspread.authorize(c).open_by_key(SPREADSHEET_ID)

def ws(b,name,rows=3000,cols=100):
    try:return b.worksheet(name)
    except gspread.WorksheetNotFound:return b.add_worksheet(title=name,rows=rows,cols=cols)

def write(w,rows):
    rows=[[scalar(x) for x in r] for r in rows]
    width=max([len(r) for r in rows] or [1])
    if w.col_count<width:w.add_cols(width-w.col_count)
    w.clear();w.update(values=rows,range_name='A1',value_input_option='USER_ENTERED')
    try:w.freeze(rows=1)
    except Exception:pass

def main():
    hp=OUT/'early_hunter.csv'; sp=OUT/'backtest_summary.csv'; cp=OUT/'score_calibration.csv'
    if not hp.exists():raise RuntimeError('output/early_hunter.csv missing')
    h=pd.read_csv(hp); stats=pd.read_csv(sp).iloc[0].to_dict() if sp.exists() else {}; cal=pd.read_csv(cp) if cp.exists() else pd.DataFrame()
    # Remove duplicate RS fields and force every cell to a scalar.
    if 'RS_VS_UNIVERSE' not in h.columns:
        for c in ('RS_VS_UNIVERSE_x','RS_VS_UNIVERSE_y'):
            if c in h.columns:h['RS_VS_UNIVERSE']=h[c];break
    h=h.drop(columns=[c for c in ('RS_VS_UNIVERSE_x','RS_VS_UNIVERSE_y') if c in h.columns],errors='ignore')
    for c in ('CMP','ENTRY_PRICE','MAX_BUY_PRICE','BREAKOUT_TRIGGER','STOP_LOSS','TARGET_1','TARGET_2','TARGET_3','RISK_PCT','RISK_REWARD_T1','HUNTER_SCORE','PRE_BREAKOUT_SCORE','BREAKOUT_SCORE','SWING_SCORE','NEXT_DAY_SETUP_SCORE','BREAKOUT_PROBABILITY','RS_VS_UNIVERSE','RS_RANK'):
        if c in h.columns:h[c]=pd.to_numeric(h[c],errors='coerce')
    if 'MODEL_ACTION' not in h.columns:h['MODEL_ACTION']=h.get('ACTION','WATCH')
    gate=str(stats.get('quality_gate',stats.get('gate_reason','UNKNOWN')))
    # A failed gate cannot publish a BUY. Timing WAIT/CHASE also cannot publish a BUY.
    h['FINAL_ACTION']=h.get('ACTION','WATCH').astype(str)
    if 'ENTRY_STATUS' in h.columns:
        wait=h.ENTRY_STATUS.astype(str).str.upper().isin({'WAIT','CHASE','AVOID / CHASE','AVOID'})
        h.loc[wait & h.MODEL_ACTION.astype(str).isin(BUY_ACTIONS),'FINAL_ACTION']='AVOID / CHASE'
    if gate.upper() not in {'PASS','OK','TRUE'}:
        h.loc[h.MODEL_ACTION.astype(str).isin(BUY_ACTIONS),'FINAL_ACTION']='QUALITY BLOCKED'
    h['ACTION']=h['FINAL_ACTION']
    if 'SECTOR_STRENGTH' in h.columns:
        sec=h.SECTOR_STRENGTH.astype(str).str.upper()
        h.loc[sec.isin({'UNAVAILABLE','NAN','NONE',''}),'SECTOR_STRENGTH']='UNKNOWN'
    h.to_csv(hp,index=False)
    b=book(); hunter=ws(b,'Early Hunter',3000,max(100,len(h.columns)+2)); audit=ws(b,'Backtest Audit',3000,80)
    write(hunter,[h.columns.tolist()]+[[scalar(x) for x in r] for r in h.itertuples(index=False,name=None)])
    audit_rows=[['NSE EARLY HUNTER — BACKTEST AUDIT'],['QUALITY GATE',gate],['MODEL CANDIDATES',len(h)],['PUBLISHED BUY',int(h.FINAL_ACTION.isin(BUY_ACTIONS).sum())],['QUALITY BLOCKED',int((h.FINAL_ACTION=='QUALITY BLOCKED').sum())],[''],['BACKTEST SUMMARY']]
    for k,v in stats.items():
        if isinstance(v,(list,dict)):
            audit_rows.append([str(k),json.dumps(v,default=str,sort_keys=True)])
        else:audit_rows.append([str(k),scalar(v)])
    if not cal.empty:
        audit_rows += [[''],['SCORE/HORIZON CALIBRATION'],cal.columns.tolist()]
        audit_rows += [[scalar(x) for x in r] for r in cal.itertuples(index=False,name=None)]
    write(audit,audit_rows)
    print(f'SAFE SHEET WRITER OK | hunter={len(h)} | audit={len(audit_rows)}')

if __name__=='__main__':main()

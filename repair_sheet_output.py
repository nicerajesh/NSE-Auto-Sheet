from __future__ import annotations
import json, os
from pathlib import Path
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials

SPREADSHEET_ID=os.getenv('SPREADSHEET_ID','1U9j5fMZAWPUSwoP_U-GKdacVke9nUjspqPR3wGsWAUM')
OUT=Path('output')
BUY_ACTIONS={'PRE-BREAKOUT BUY','BREAKOUT BUY','SWING BUY'}
MIN_PROB_SAMPLES=int(os.getenv('MIN_PROB_SAMPLES','30'))


def scalar(v):
    if v is None: return ''
    if isinstance(v,pd.Timestamp): return v.strftime('%Y-%m-%d')
    try:
        if pd.isna(v): return ''
    except Exception: pass
    if hasattr(v,'item'):
        try: return v.item()
        except Exception: pass
    if isinstance(v,(dict,list,tuple,set)): return json.dumps(v,default=str)
    return v


def clean_numeric(df, cols):
    for c in cols:
        if c in df.columns:
            df[c]=pd.to_numeric(df[c],errors='coerce')
    return df


def confidence(samples):
    try:n=int(float(samples))
    except Exception:n=0
    if n < MIN_PROB_SAMPLES: return 'N/A - INSUFFICIENT SAMPLE'
    if n < 50: return 'LOW CONFIDENCE'
    if n < 100: return 'MODERATE CONFIDENCE'
    return 'VALIDATED SAMPLE'


def book():
    raw=os.getenv('GCP_CREDENTIALS')
    if not raw: raise RuntimeError('GCP_CREDENTIALS secret missing')
    creds=ServiceAccountCredentials.from_json_keyfile_dict(json.loads(raw),['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive'])
    return gspread.authorize(creds).open_by_key(SPREADSHEET_ID)


def ws_or_create(book,name,rows=3000,cols=100):
    try:return book.worksheet(name)
    except gspread.WorksheetNotFound:return book.add_worksheet(title=name,rows=rows,cols=cols)


def write(ws,rows):
    cols=max(ws.col_count,max((len(r) for r in rows),default=1))
    if ws.col_count<cols: ws.add_cols(cols-ws.col_count)
    ws.clear(); ws.update(values=rows,range_name='A1',value_input_option='USER_ENTERED')
    try:ws.freeze(rows=1)
    except Exception:pass


def main():
    hunter_p=OUT/'early_hunter.csv'; stats_p=OUT/'backtest_summary.csv'; cal_p=OUT/'score_calibration.csv'
    if not hunter_p.exists(): raise RuntimeError('output/early_hunter.csv missing')
    hunter=pd.read_csv(hunter_p); stats=pd.read_csv(stats_p).iloc[0].to_dict() if stats_p.exists() else {}; cal=pd.read_csv(cal_p) if cal_p.exists() else pd.DataFrame()

    # Canonical RS field; never expose _x/_y duplicates.
    if 'RS_VS_UNIVERSE' not in hunter.columns:
        for c in ('RS_VS_UNIVERSE_x','RS_VS_UNIVERSE_y'):
            if c in hunter.columns:hunter['RS_VS_UNIVERSE']=hunter[c];break
    hunter=hunter.drop(columns=[c for c in ('RS_VS_UNIVERSE_x','RS_VS_UNIVERSE_y') if c in hunter.columns],errors='ignore')
    numeric=['CMP','ENTRY_PRICE','MAX_BUY_PRICE','BREAKOUT_TRIGGER','STOP_LOSS','TARGET_1','TARGET_2','TARGET_3','RISK_PCT','R_R','HUNTER_SCORE','PRE_BREAKOUT_SCORE','BREAKOUT_SCORE','SWING_SCORE','NEXT_DAY_SETUP_SCORE','BREAKOUT_PROBABILITY','RESISTANCE_DISTANCE_PCT','RESISTANCE_TESTS','RS_VS_UNIVERSE','RS_RANK','VOLUME_RATIO']
    hunter=clean_numeric(hunter,numeric)

    # Keep model diagnosis and executable decision separate.
    if 'MODEL_ACTION' not in hunter.columns and 'ACTION' in hunter.columns:hunter['MODEL_ACTION']=hunter['ACTION']
    gate_text=str(stats.get('quality_gate',hunter.get('QUALITY_GATE','UNKNOWN')))
    gate_ok=gate_text.upper() in {'PASS','OK','TRUE','1'}
    if 'ENTRY_STATUS' in hunter.columns:
        entry=hunter.ENTRY_STATUS.astype(str).str.upper()
    else:entry=pd.Series('',index=hunter.index)
    model=hunter.MODEL_ACTION.astype(str)
    hunter['QUALITY_STATUS']=hunter.get('QUALITY_STATUS',pd.Series('UNKNOWN',index=hunter.index)).fillna('UNKNOWN')
    blocked=~gate_ok & model.isin(BUY_ACTIONS)
    hunter.loc[blocked,'QUALITY_STATUS']='BLOCKED'
    hunter['FINAL_ACTION']=model
    hunter.loc[blocked,'FINAL_ACTION']='NO BUY - QUALITY BLOCKED'
    chase=entry.isin({'WAIT','CHASE','AVOID','AVOID / CHASE'}) & model.isin(BUY_ACTIONS)
    hunter.loc[chase,'FINAL_ACTION']='NO BUY - '+entry[chase]
    hunter['ACTION']=hunter['FINAL_ACTION']

    # Unknown sector is never presented as supportive.
    if 'SECTOR_STRENGTH' in hunter.columns:
        sec=hunter.SECTOR_STRENGTH.astype(str).str.upper()
        hunter.loc[sec.isin({'UNAVAILABLE','NAN','NONE',''}),'SECTOR_STRENGTH']='UNKNOWN'
        hunter['SECTOR_STATUS']=hunter.SECTOR_STRENGTH
        hunter['SECTOR_REASON']=hunter.SECTOR_STATUS.map(lambda x:'Sector confirmation unavailable' if x=='UNKNOWN' else '')

    # Never call an event touch/cross a trade probability.
    if not cal.empty:
        if 'ANALYSIS' in cal.columns:
            cal.loc[cal.ANALYSIS.eq('BREAKOUT_EVENT'),'PROBABILITY_TYPE']='RESISTANCE EVENT HIT RATE — NOT TRADE PROBABILITY'
            cal.loc[cal.ANALYSIS.eq('TRADE_SCORE'),'PROBABILITY_TYPE']='TRADE OUTCOME RATE'
        if 'TRADES' in cal.columns:
            cal['CONFIDENCE']=cal['TRADES'].map(confidence)
            insufficient=cal['TRADES'].fillna(0).astype(float)<MIN_PROB_SAMPLES
            for c in ('BREAKOUT_RATE','WIN_RATE'):
                if c in cal.columns:cal.loc[insufficient,c]=pd.NA

    hunter.to_csv(hunter_p,index=False)
    b=book(); hs=ws_or_create(b,'Early Hunter',3000,max(40,len(hunter.columns)+2)); audit=ws_or_create(b,'Backtest Audit',3000,100)
    rows=[hunter.columns.tolist()]+[[scalar(v) for v in r] for r in hunter.itertuples(index=False,name=None)]
    write(hs,rows)
    # Explicit numeric formatting protects prices/targets from Excel serial-date rendering.
    try:
        headers=hunter.columns.tolist(); nrows=max(2,len(hunter)+1)
        for c in numeric:
            if c in headers:
                idx=headers.index(c)+1; letters=''; n=idx
                while n:n,rem=divmod(n-1,26);letters=chr(65+rem)+letters
                hs.format(f'{letters}2:{letters}{nrows}',{'numberFormat':{'type':'NUMBER','pattern':'0.00'}})
    except Exception as e:print('Numeric format warning:',repr(e))

    # Audit is deliberately separate from stock rows.
    rows=[['NSE EARLY HUNTER — BACKTEST AUDIT'],['QUALITY GATE',gate_text],['MODEL CANDIDATES',len(hunter)],['PUBLISHED BUY',int(hunter.FINAL_ACTION.isin(BUY_ACTIONS).sum())],['QUALITY BLOCKED',int((hunter.FINAL_ACTION=='NO BUY - QUALITY BLOCKED').sum())],['RESISTANCE EVENT HIT RATE','EVENT METRIC ONLY — NOT TRADE PROBABILITY'],['MIN PROBABILITY SAMPLES',MIN_PROB_SAMPLES],[],['BACKTEST SUMMARY']]
    for k,v in stats.items():
        if k=='action_stats' and isinstance(v,list):
            ad=pd.DataFrame(v)
            if not ad.empty:rows += [['ACTION STATS'],ad.columns.tolist()]+[[scalar(x) for x in r] for r in ad.itertuples(index=False,name=None)]
        elif not isinstance(v,(list,dict)):rows.append([str(k),scalar(v)])
    if not cal.empty:
        rows += [[],['CALIBRATION — EVENT RATE IS NOT TRADE PROBABILITY'],cal.columns.tolist()]
        rows += [[scalar(x) for x in r] for r in cal.itertuples(index=False,name=None)]
    write(audit,rows)
    try:audit.format('A1:Z1',{'textFormat':{'bold':True,'fontSize':14}})
    except Exception:pass
    print(f'SHEET REPAIR OK | rows={len(hunter)} | published_buy={int(hunter.FINAL_ACTION.isin(BUY_ACTIONS).sum())} | quality_blocked={int((hunter.FINAL_ACTION=="NO BUY - QUALITY BLOCKED").sum())}')

if __name__=='__main__':main()

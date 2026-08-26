from __future__ import annotations
import json, os
from pathlib import Path
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials

SPREADSHEET_ID=os.getenv('SPREADSHEET_ID','1U9j5fMZAWPUSwoP_U-GKdacVke9nUjspqPR3wGsWAUM')
OUT=Path('output')


def scalar(v):
    if v is None: return ''
    if isinstance(v,(pd.Timestamp,)): return v.strftime('%Y-%m-%d')
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


def book():
    raw=os.getenv('GCP_CREDENTIALS')
    if not raw: raise RuntimeError('GCP_CREDENTIALS secret missing')
    creds=ServiceAccountCredentials.from_json_keyfile_dict(json.loads(raw),['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive'])
    return gspread.authorize(creds).open_by_key(SPREADSHEET_ID)


def ws_or_create(book,name,rows=3000,cols=100):
    try: return book.worksheet(name)
    except gspread.WorksheetNotFound: return book.add_worksheet(title=name,rows=rows,cols=cols)


def write(ws, rows):
    cols=max(ws.col_count,max(len(r) for r in rows) if rows else 1)
    if ws.col_count<cols: ws.add_cols(cols-ws.col_count)
    ws.clear()
    ws.update(values=rows,range_name='A1',value_input_option='USER_ENTERED')
    try: ws.freeze(rows=1)
    except Exception: pass


def main():
    hunter_p=OUT/'early_hunter.csv'
    stats_p=OUT/'backtest_summary.csv'
    cal_p=OUT/'score_calibration.csv'
    if not hunter_p.exists(): raise RuntimeError('output/early_hunter.csv missing')
    hunter=pd.read_csv(hunter_p)
    stats=pd.read_csv(stats_p).iloc[0].to_dict() if stats_p.exists() else {}
    cal=pd.read_csv(cal_p) if cal_p.exists() else pd.DataFrame()

    # Canonicalise duplicate RS fields and all price/risk fields before Google Sheets upload.
    if 'RS_VS_UNIVERSE' not in hunter.columns:
        for c in ('RS_VS_UNIVERSE_x','RS_VS_UNIVERSE_y'):
            if c in hunter.columns:
                hunter['RS_VS_UNIVERSE']=hunter[c]
                break
    for c in ('RS_VS_UNIVERSE_x','RS_VS_UNIVERSE_y'):
        if c in hunter.columns: hunter=hunter.drop(columns=[c])
    numeric=['CMP','ENTRY_PRICE','MAX_BUY_PRICE','BREAKOUT_TRIGGER','STOP_LOSS','TARGET_1','TARGET_2','TARGET_3','RISK_PCT','R_R','HUNTER_SCORE','PRE_BREAKOUT_SCORE','BREAKOUT_SCORE','SWING_SCORE','NEXT_DAY_SETUP_SCORE','BREAKOUT_PROBABILITY','RESISTANCE_DISTANCE_PCT','RESISTANCE_TESTS','RS_VS_UNIVERSE','RS_RANK','VOLUME_RATIO']
    hunter=clean_numeric(hunter,numeric)

    # One unambiguous decision field. Model action remains available for audit.
    if 'MODEL_ACTION' not in hunter.columns and 'ACTION' in hunter.columns:
        hunter['MODEL_ACTION']=hunter['ACTION']
    if 'QUALITY_GATE' not in hunter.columns:
        hunter['QUALITY_GATE']='UNKNOWN'
    if 'PUBLISHED_ACTION' not in hunter.columns:
        hunter['PUBLISHED_ACTION']=hunter['ACTION'] if 'ACTION' in hunter.columns else 'WATCH'
    if 'ENTRY_STATUS' in hunter.columns:
        chase=hunter.ENTRY_STATUS.astype(str).str.upper().isin({'WAIT','CHASE','AVOID','AVOID / CHASE'})
        buy=hunter.MODEL_ACTION.astype(str).isin({'PRE-BREAKOUT BUY','BREAKOUT BUY','SWING BUY'})
        hunter.loc[chase & buy,'PUBLISHED_ACTION']='AVOID / CHASE'

    # A failed historical gate must never appear as a published BUY.
    blocked=hunter.QUALITY_GATE.astype(str).str.upper().ne('PASS') & hunter.MODEL_ACTION.astype(str).isin({'PRE-BREAKOUT BUY','BREAKOUT BUY','SWING BUY'})
    hunter.loc[blocked,'PUBLISHED_ACTION']='QUALITY BLOCKED'
    hunter['FINAL_ACTION']=hunter['PUBLISHED_ACTION']

    # Unknown sector is neutral/unknown, never supportive.
    if 'SECTOR_STRENGTH' in hunter.columns:
        sec=hunter.SECTOR_STRENGTH.astype(str).str.upper()
        hunter.loc[sec.isin({'UNAVAILABLE','NAN','NONE',''}),'SECTOR_STRENGTH']='UNKNOWN'

    hunter.to_csv(hunter_p,index=False)

    b=book(); hs=ws_or_create(b,'Early Hunter',3000,max(40,len(hunter.columns)+2)); audit=ws_or_create(b,'Backtest Audit',3000,80)
    stock_rows=[hunter.columns.tolist()]
    stock_rows += [[scalar(v) for v in row] for row in hunter.itertuples(index=False,name=None)]
    write(hs,stock_rows)

    # Numeric formatting for all price/score columns prevents Excel serial dates.
    try:
        headers=hunter.columns.tolist()
        for col in numeric:
            if col in headers:
                idx=headers.index(col)+1
                letter=''
                n=idx
                while n:
                    n,rem=divmod(n-1,26); letter=chr(65+rem)+letter
                hs.format(f'{letter}2:{letter}{max(2,len(hunter)+1)}',{'numberFormat':{'type':'NUMBER','pattern':'0.00'}})
    except Exception as e: print('Numeric format warning:',repr(e))

    # Separate audit/report information from the stock table.
    rows=[['NSE EARLY HUNTER — BACKTEST AUDIT'],['QUALITY GATE',stats.get('quality_gate','')],['TRADES',stats.get('trades','')],['WIN RATE %',stats.get('win_rate_pct','')],['AVG RETURN %',stats.get('avg_return_pct','')],['MEDIAN RETURN %',stats.get('median_return_pct','')],['EXPECTANCY %',stats.get('expectancy_pct','')],['PROFIT FACTOR',stats.get('profit_factor','')],['STOP RATE %',stats.get('stop_rate_pct','')],['BREAKOUT EVENT SAMPLES',stats.get('breakout_event_samples','')],['BREAKOUT EVENT RATE %',stats.get('breakout_event_rate_pct','')],['PRE-BREAKOUT EVENT RATE %',stats.get('pre_breakout_event_rate_pct','')],[],['ACTION STATS']]
    action=stats.get('action_stats') or stats.get('by_action')
    if isinstance(action,list) and action:
        ad=pd.DataFrame(action); rows.append(ad.columns.tolist()); rows += [[scalar(v) for v in r] for r in ad.itertuples(index=False,name=None)]
    if not cal.empty:
        rows += [[],['SCORE/HORIZON CALIBRATION'],cal.columns.tolist()]
        rows += [[scalar(v) for v in r] for r in cal.itertuples(index=False,name=None)]
    write(audit,rows)
    try:
        audit.format('A1:Z1',{'textFormat':{'bold':True,'fontSize':14}})
        audit.format('A14:Z14',{'textFormat':{'bold':True}})
    except Exception: pass

    print(f'SHEET REPAIR OK | Early Hunter rows={len(hunter)} | Backtest Audit rows={len(rows)-1} | numeric price fields protected')

if __name__=='__main__': main()

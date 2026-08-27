from __future__ import annotations
import os, json
from pathlib import Path
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

OUT=Path('output')
DEFAULT_SHEET_ID='1U9j5fMZAWPUSwoP_U-GKdacVke9nUjspqPR3wGsWAUM'


def _credentials():
    raw=os.getenv('GCP_CREDENTIALS','')
    if not raw: raise RuntimeError('GCP_CREDENTIALS missing')
    return Credentials.from_service_account_info(json.loads(raw),scopes=['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive'])

def _clean(v):
    if v is None:return ''
    if isinstance(v,(dict,list,tuple,set)):return json.dumps(v,sort_keys=True,default=str)
    try:
        if pd.isna(v):return ''
    except Exception:pass
    if hasattr(v,'item'):
        try:return v.item()
        except Exception:pass
    return v

def _matrix(df):
    if df.empty:return [['NO DATA']]
    return [[str(c) for c in df.columns]]+[[ _clean(v) for v in row] for row in df.itertuples(index=False,name=None)]

def _write(ws,df):
    ws.clear()
    ws.update(range_name='A1',values=_matrix(df),value_input_option='USER_ENTERED')
    try:ws.freeze(rows=1)
    except Exception:pass

def _open_sheet(gc):
    url=os.getenv('GOOGLE_SHEET_URL') or os.getenv('SHEET_URL')
    if url:return gc.open_by_url(url)
    return gc.open_by_key(os.getenv('SPREADSHEET_ID') or DEFAULT_SHEET_ID)

def _read(name,default=None):
    p=OUT/name
    if not p.exists():return default if default is not None else pd.DataFrame()
    return pd.read_csv(p)

def main():
    hunter=_read('decision_candidates.csv',_read('early_hunter.csv'))
    commands=_read('trading_commands.csv')
    buy=_read('buy_candidates.csv')
    dash=_read('dashboard.csv')
    low52=_read('low52_reversal.csv')
    if hunter.empty and commands.empty: raise RuntimeError('No scanner output available')
    gc=gspread.authorize(_credentials()); sh=_open_sheet(gc)
    def get_or_create(title,rows=3000,cols=100):
        try:return sh.worksheet(title)
        except gspread.WorksheetNotFound:return sh.add_worksheet(title=title,rows=rows,cols=cols)
    # User-facing command sheet is intentionally first and simple.
    _write(get_or_create('Aaj Kya Karna Hai',max(100,len(commands)+10),30),commands)
    _write(get_or_create('Buy Candidates',max(100,len(buy)+10),max(30,len(buy.columns)+2)),buy)
    _write(get_or_create('Early Hunter',max(100,len(hunter)+10),max(40,len(hunter.columns)+2)),hunter)
    _write(get_or_create('52 Week Low Rocket',max(100,len(low52)+10),max(25,len(low52.columns)+2 if not low52.empty else 25)),low52)
    if not dash.empty:_write(get_or_create('Dashboard',max(100,len(dash)+10),max(40,len(dash.columns)+2)),dash)
    print(f'SHEET PUBLISH OK: commands={len(commands)} buy={len(buy)} hunter={len(hunter)} low52={len(low52)}')

if __name__=='__main__':main()

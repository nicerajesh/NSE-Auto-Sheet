from __future__ import annotations
import os, json
from pathlib import Path
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from csv_utils import safe_to_csv, safe_read_csv
from simple_dashboard import build_action_plan

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
    matrix=_matrix(df); needed_rows=max(10,len(matrix)+5); needed_cols=max(20,max((len(r) for r in matrix),default=1)+2)
    try:
        if ws.row_count < needed_rows: ws.add_rows(needed_rows-ws.row_count)
        if ws.col_count < needed_cols: ws.add_cols(needed_cols-ws.col_count)
    except Exception as e: print(f'{ws.title}: grid expansion warning: {e}')
    try: ws.clear()
    except Exception as e: print(f'{ws.title}: clear warning: {e}')
    # Re-resolve by title before writing to avoid stale worksheet IDs.
    ws2=ws.spreadsheet.worksheet(ws.title)
    ws2.update(range_name='A1',values=matrix,value_input_option='USER_ENTERED')
    try: ws2.freeze(rows=1)
    except Exception: pass

def _open_sheet(gc):
    url=os.getenv('GOOGLE_SHEET_URL') or os.getenv('SHEET_URL')
    if url:return gc.open_by_url(url)
    return gc.open_by_key(os.getenv('SPREADSHEET_ID') or DEFAULT_SHEET_ID)

def _read(name,default=None):
    p=OUT/name
    if not p.exists():return default if default is not None else pd.DataFrame()
    return safe_read_csv(p)

def _extract(df,pub_col,action_col,buy_labels,source_name):
    """Normalize one scanner's finalized output into common columns, keeping
    only rows whose PUBLISHED action (i.e. quality-gate-passed, not blocked)
    is an actual buy-tier label — never a row the gate blocked."""
    if df is None or df.empty or pub_col not in df.columns:return pd.DataFrame()
    d=df[df[pub_col].isin(buy_labels)]
    if d.empty:return pd.DataFrame()
    def col(name,*alts):
        for c in (name,*alts):
            if c in d.columns:return d[c]
        return ''
    return pd.DataFrame({'SYMBOL':d['SYMBOL'],'CMP':col('CMP'),'SOURCE':source_name,'SIGNAL':d[action_col],
        'ENTRY':col('ENTRY_PRICE'),'STOP_LOSS':col('STOP_LOSS','INITIAL_SL'),'TARGET_1':col('TARGET_1'),'TARGET_2':col('TARGET_2')})

def build_master_buy_dashboard():
    """Consolidates every scanner's PUBLISHED (quality-gate-passed) buys into
    one sheet, tagged by source, so a stock that multiple independent scanners
    agree on (different logic, different data angles) stands out via
    CONFLUENCE_COUNT — genuinely higher conviction than any single scanner
    alone. Blocked/unpublished rows never make it in here."""
    hunter=_read('early_hunter.csv');low52=_read('low52_reversal.csv');apex=_read('apex_matrix.csv');stealth=_read('stealth_accumulation.csv')
    parts=[
        _extract(hunter,'PUBLISHED_ACTION','ACTION',{'PRE-BREAKOUT BUY','BREAKOUT BUY','SWING BUY'},'Early Hunter'),
        _extract(low52,'PUBLISHED_ACTION','ACTION',{'EARLY REVERSAL BUY','REVERSAL WATCH'},'52 Week Low Rocket'),
        _extract(apex,'PUBLISHED_SIGNAL','SIGNAL',{'APEX BUY','TACTICAL BUY','BUY'},'APEX Matrix'),
        _extract(stealth,'PUBLISHED_ACTION','ACTION',{'STEALTH BUY','STEALTH WATCH'},'Stealth Accumulation'),
    ]
    parts=[p for p in parts if not p.empty]
    if not parts:return pd.DataFrame()
    merged=pd.concat(parts,ignore_index=True)
    sources_per_symbol=merged.groupby('SYMBOL')['SOURCE'].apply(lambda s:', '.join(sorted(set(s))))
    merged['CONFLUENCE_COUNT']=merged.groupby('SYMBOL')['SOURCE'].transform('nunique')
    merged['ALL_SOURCES']=merged['SYMBOL'].map(sources_per_symbol)
    merged=merged.sort_values(['CONFLUENCE_COUNT','SYMBOL'],ascending=[False,True]).reset_index(drop=True)
    merged.insert(0,'RANK',range(1,len(merged)+1))
    return merged

def main():
    hunter=_read('decision_candidates.csv',_read('early_hunter.csv'))
    commands=_read('trading_commands.csv')
    buy=_read('buy_candidates.csv')
    dash=_read('dashboard.csv')
    low52=_read('low52_reversal.csv')
    apex=_read('apex_matrix.csv')
    stealth=_read('stealth_accumulation.csv')
    master=build_master_buy_dashboard(); safe_to_csv(master,OUT/'master_buy_dashboard.csv')
    plan=build_action_plan(); safe_to_csv(plan,OUT/'mera_action_plan.csv')
    if hunter.empty and commands.empty: raise RuntimeError('No scanner output available')
    gc=gspread.authorize(_credentials()); sh=_open_sheet(gc)
    def get_or_create(title,rows=3000,cols=100):
        try:return sh.worksheet(title)
        except gspread.WorksheetNotFound:return sh.add_worksheet(title=title,rows=rows,cols=cols)
    # This is THE sheet: one simple table, Buy/Sell/Hold all together, plain
    # language, most-urgent-first. Placed as the very first tab on purpose.
    ws_plan=get_or_create('MERA ACTION PLAN',max(100,len(plan)+10),12)
    _write(ws_plan,plan)
    try:
        ws_plan.format('A1:Z1',{'textFormat':{'bold':True,'fontSize':12},'backgroundColor':{'red':0.85,'green':0.85,'blue':0.85}})
        if not plan.empty and 'KYA KARU' in plan.columns:
            n=len(plan)
            for i,val in enumerate(plan['KYA KARU'].astype(str),start=2):
                if 'BECHO' in val or 'EXIT' in val: color={'red':1.0,'green':0.85,'blue':0.85}
                elif 'KHARIDO' in val: color={'red':0.83,'green':0.96,'blue':0.83}
                elif 'HOLD' in val: color={'red':1.0,'green':0.97,'blue':0.78}
                else: color={'red':0.93,'green':0.93,'blue':0.93}
                ws_plan.format(f'A{i}:Z{i}',{'backgroundColor':color})
        ws_plan.freeze(rows=1)
    except Exception as e:print('MERA ACTION PLAN format warning:',e)
    try:ws_plan.update_index(0)  # force it to be the first (leftmost) tab every run
    except Exception as e:print('MERA ACTION PLAN reorder warning:',e)
    # User-facing command sheet is intentionally first and simple.
    _write(get_or_create('Aaj Kya Karna Hai',max(100,len(commands)+10),30),commands)
    _write(get_or_create('Master Buy Dashboard',max(100,len(master)+10),max(20,len(master.columns)+2 if not master.empty else 20)),master)
    _write(get_or_create('Buy Candidates',max(100,len(buy)+10),max(30,len(buy.columns)+2)),buy)
    _write(get_or_create('Early Hunter',max(100,len(hunter)+10),max(40,len(hunter.columns)+2)),hunter)
    _write(get_or_create('52 Week Low Rocket',max(100,len(low52)+10),max(25,len(low52.columns)+2 if not low52.empty else 25)),low52)
    _write(get_or_create('APEX Matrix',max(100,len(apex)+10),max(25,len(apex.columns)+2 if not apex.empty else 25)),apex)
    _write(get_or_create('Stealth Accumulation',max(100,len(stealth)+10),max(25,len(stealth.columns)+2 if not stealth.empty else 25)),stealth)
    if not dash.empty:_write(get_or_create('Dashboard',max(100,len(dash)+10),max(40,len(dash.columns)+2)),dash)
    print(f'SHEET PUBLISH OK: plan={len(plan)} commands={len(commands)} master_buy={len(master)} buy={len(buy)} hunter={len(hunter)} low52={len(low52)} apex={len(apex)} stealth={len(stealth)}')

if __name__=='__main__':main()

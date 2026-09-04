from __future__ import annotations
import json, os
from pathlib import Path
import gspread, pandas as pd
from oauth2client.service_account import ServiceAccountCredentials
from csv_utils import safe_to_csv, safe_read_csv

SPREADSHEET_ID=os.getenv('SPREADSHEET_ID','1U9j5fMZAWPUSwoP_U-GKdacVke9nUjspqPR3wGsWAUM')
OUT=Path(os.getenv('NSE_OUTPUT_DIR','output'))
MAX_ROWS=60


def book():
    raw=os.getenv('GCP_CREDENTIALS')
    if not raw: raise RuntimeError('GCP_CREDENTIALS secret missing')
    creds=ServiceAccountCredentials.from_json_keyfile_dict(json.loads(raw),['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive'])
    return gspread.authorize(creds).open_by_key(SPREADSHEET_ID)


def _read(name):
    p=OUT/name
    try:return safe_read_csv(p) if p.exists() else pd.DataFrame()
    except Exception:return pd.DataFrame()


def _text(r,*cols,default=''):
    for c in cols:
        if c in r.index:
            v=str(r.get(c,'')).strip()
            if v and v.lower() not in {'nan','none'}: return v
    return default


def _num(v):
    try:return float(v)
    except Exception:return None


def _confidence(row,cal):
    score=_num(row.get('PRE_BREAKOUT_SCORE',row.get('HUNTER_SCORE',row.get('APEX_SCORE',row.get('STEALTH_SCORE',0)))))
    action=_text(row,'ACTION','SIGNAL')
    if score is not None and not cal.empty and {'ANALYSIS','ACTION','SCORE_BUCKET','BREAKOUT_RATE','TRADES'}.issubset(cal.columns):
        bucket='90+' if score>=90 else '82-89' if score>=82 else '75-81' if score>=75 else '68-74' if score>=68 else '<68'
        q=cal[(cal.ANALYSIS=='BREAKOUT_EVENT') & (cal.ACTION.astype(str)==action) & (cal.SCORE_BUCKET.astype(str)==bucket) & (pd.to_numeric(cal.TRADES,errors='coerce')>=5)]
        if not q.empty and pd.notna(q.BREAKOUT_RATE.iloc[0]): return round(float(q.BREAKOUT_RATE.iloc[0]),1)
    p=_num(row.get('BREAKOUT_PROBABILITY',0))
    return round(max(0,min(90,p or 0)),1)


def _status(r):
    gate=_text(r,'QUALITY_GATE',default='UNKNOWN').upper()
    action=_text(r,'PUBLISHED_ACTION','ACTION','SIGNAL',default='WATCH').upper()
    # BUY ON TRIGGER means the setup is waiting for the trigger; it is NOT a live BUY.
    if 'BUY ON TRIGGER' in action:return '🟡 WATCH / WAIT'
    if 'RISK BLOCKED' in action:return '⛔ RISK BLOCKED'
    live_buy=('BUY ON BREAKOUT' in action) or ('BUY ON PULLBACK' in action)
    legacy_buy=('BREAKOUT BUY' in action) or ('SWING BUY' in action) or ('PRE-BREAKOUT BUY' in action) or ('APEX BUY' in action) or ('TACTICAL BUY' in action) or ('STEALTH BUY' in action) or ('EARLY REVERSAL BUY' in action)
    if live_buy or legacy_buy:
        if gate=='PASS':return '🟢 BUY CANDIDATE'
        if 'BLOCK' in gate or 'LOW_PROFIT' in gate:return '⛔ QUALITY BLOCKED'
        return '🟠 NOT RELEASED'
    if 'READY' in action or 'PRE-BREAKOUT' in action or 'WATCH' in action or 'WAIT' in action or 'REVERSAL' in action or 'STEALTH' in action:return '🟡 WATCH / WAIT'
    return '⚪ WATCH'


def _normalize(df,source,cal):
    if df.empty or 'SYMBOL' not in df.columns:return pd.DataFrame()
    rows=[]
    for _,r in df.iterrows():
        action=_text(r,'PUBLISHED_ACTION','ACTION','SIGNAL',default='WATCH')
        score=_num(_text(r,'PRE_BREAKOUT_SCORE','HUNTER_SCORE','APEX_SCORE','STEALTH_SCORE',default='0')) or 0
        rows.append({'SOURCE':source,'SYMBOL':str(r.get('SYMBOL','')),'SIGNAL':action,'STATUS':_status(r),'SCORE':score,'CONFIDENCE %':_confidence(r,cal),'CMP':_text(r,'CMP','CURRENT_PRICE','LTP','CLOSE'),'ENTRY':_text(r,'IDEAL_ENTRY','ENTRY_PRICE','ENTRY'),'BUY ZONE':_text(r,'BUY_ZONE','ENTRY_ZONE'),'TRIGGER':_text(r,'BREAKOUT_TRIGGER','TRIGGER_PRICE','TRIGGER'),'STOP LOSS':_text(r,'STOP_LOSS','INITIAL_SL','STOP'),'TARGET 1':_text(r,'TARGET_1','TARGET'),'TARGET 2':_text(r,'TARGET_2'),'REASON':_text(r,'DECISION_REASON','REASONS','WHY',default='Scanner setup — confirmation required')})
    out=pd.DataFrame(rows)
    if out.empty:return out
    # Keep the strongest setup per symbol so the dashboard stays concise.
    return out.sort_values(['SCORE','CONFIDENCE %'],ascending=False).drop_duplicates('SYMBOL').head(MAX_ROWS)


def main():
    cal=_read('score_calibration.csv')
    sources=[('Early Hunter',_read('early_hunter.csv')),('52 Week Low',_read('low52_reversal.csv')),('APEX',_read('apex_matrix.csv')),('Stealth',_read('stealth_accumulation.csv')),('Decision Engine',_read('decision_candidates.csv'))]
    parts=[_normalize(df,name,cal) for name,df in sources]
    parts=[p for p in parts if not p.empty]
    c=pd.concat(parts,ignore_index=True) if parts else pd.DataFrame()
    if not c.empty:
        priority=c['STATUS'].map({'🟢 BUY CANDIDATE':1,'🟡 WATCH / WAIT':2,'🟠 NOT RELEASED':3,'⛔ QUALITY BLOCKED':4,'⛔ RISK BLOCKED':5,'⚪ WATCH':6}).fillna(9)
        c=c.assign(_P=priority).sort_values(['_P','SCORE','CONFIDENCE %'],ascending=[True,False,False]).drop(columns='_P').head(MAX_ROWS).reset_index(drop=True)
        c.insert(0,'RANK',range(1,len(c)+1))
    else:
        c=pd.DataFrame([{'RANK':1,'SOURCE':'SYSTEM','SYMBOL':'—','SIGNAL':'NO SCANNER ROWS','STATUS':'⚠️ DATA PIPELINE CHECK','SCORE':'','CONFIDENCE %':'','CMP':'','ENTRY':'','BUY ZONE':'','TRIGGER':'','STOP LOSS':'','TARGET 1':'','TARGET 2':'','REASON':'No scanner output was available.'}])
    safe_to_csv(c,OUT/'dashboard.csv')
    buys=int((c['STATUS']=='🟢 BUY CANDIDATE').sum())
    blocked=int(c['STATUS'].astype(str).str.contains('BLOCKED|NOT RELEASED',regex=True,na=False).sum())
    watch=int(c['STATUS'].astype(str).str.contains('WATCH|WAIT',regex=True,na=False).sum())
    dates=[]
    for _,df in sources:
        if not df.empty and 'DATE' in df.columns:dates.extend(df['DATE'].dropna().astype(str).tolist())
    date=max(dates) if dates else ''
    rows=[['NSE MASTER TRADING DASHBOARD'],['DATA DATE',date],['CONFIRMED BUY CANDIDATES',buys],['QUALITY / RISK BLOCKED OR NOT RELEASED',blocked],['WATCH / WAIT',watch],['RULE','Blocked/not-released setups are shown for audit visibility but are NOT live BUY signals.'],['RULE','A BUY is actionable only when the V2 quality/risk gates pass.'],['RULE','BUY ON TRIGGER is WAIT until the breakout trigger is confirmed.'],[],c.columns.tolist()]
    rows += [[('' if pd.isna(v) else v) for v in r] for r in c.itertuples(index=False,name=None)]
    w=book()
    try:ws=w.worksheet('Dashboard')
    except gspread.WorksheetNotFound:ws=w.add_worksheet(title='Dashboard',rows=3000,cols=max(30,len(c.columns)+2))
    needed_rows=max(100,len(rows)+10);needed_cols=max(30,len(c.columns)+2)
    if ws.row_count<needed_rows:ws.add_rows(needed_rows-ws.row_count)
    if ws.col_count<needed_cols:ws.add_cols(needed_cols-ws.col_count)
    ws.clear();ws.update(range_name='A1',values=rows,value_input_option='USER_ENTERED')
    try:
        ws.freeze(rows=10);ws.format('A1:Z1',{'textFormat':{'bold':True,'fontSize':14}});ws.format('A2:B8',{'textFormat':{'bold':True}});ws.format('A10:Z10',{'textFormat':{'bold':True}});ws.format('A1:Z200',{'wrapStrategy':'WRAP'})
    except Exception as e:print('Dashboard format warning:',e)
    print(f'Dashboard updated: displayed={len(c)} | buy={buys} blocked_or_not_released={blocked} watch_wait={watch} | date={date}')

if __name__=='__main__':main()

from __future__ import annotations
import json, os
from pathlib import Path
import gspread, pandas as pd
from oauth2client.service_account import ServiceAccountCredentials
SPREADSHEET_ID=os.getenv('SPREADSHEET_ID','1U9j5fMZAWPUSwoP_U-GKdacVke9nUjspqPR3wGsWAUM'); OUT=Path('output')
def book():
    raw=os.getenv('GCP_CREDENTIALS')
    if not raw: raise RuntimeError('GCP_CREDENTIALS secret missing')
    creds=ServiceAccountCredentials.from_json_keyfile_dict(json.loads(raw),['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive'])
    return gspread.authorize(creds).open_by_key(SPREADSHEET_ID)
def main():
    bf=OUT/'buy_candidates.csv'; hf=OUT/'early_hunter.csv'
    df=pd.read_csv(bf) if bf.exists() else pd.DataFrame()
    if df.empty and hf.exists(): df=pd.read_csv(hf)
    if df.empty: df=pd.DataFrame(columns=['SYMBOL','ACTION','CATEGORY'])
    actions={'PRE-BREAKOUT BUY','PRE-BREAKOUT WATCH/BUY','BREAKOUT BUY','SWING BUY','BUY NOW','BUY ON BREAKOUT','BREAKOUT IMMINENT'}
    c=df[df.ACTION.astype(str).isin(actions)].copy() if 'ACTION' in df.columns else df.copy()
    for col in ('PRE_BREAKOUT_SCORE','BREAKOUT_SCORE','SWING_SCORE','BREAKOUT_PROBABILITY'):
        if col not in c.columns:c[col]=0
        c[col]=pd.to_numeric(c[col],errors='coerce').fillna(0)
    if 'CATEGORY' not in c.columns:c['CATEGORY']='WATCH'
    c['_priority']=c.CATEGORY.map({'PRE-BREAKOUT':0,'BREAKOUT':1,'SWING':2}).fillna(9)
    c=c.sort_values(['_priority','BREAKOUT_PROBABILITY','PRE_BREAKOUT_SCORE','BREAKOUT_SCORE','SWING_SCORE'],ascending=[True,False,False,False,False]).head(40).drop(columns='_priority')
    cols=['RANK','SYMBOL','ACTION','CATEGORY','DATE','BUY_DATE','CMP','ENTRY_ZONE','BREAKOUT_TRIGGER','STOP_LOSS','TARGET_1','TARGET_2','TARGET_3','RISK_PCT','R_R','PRE_BREAKOUT_SCORE','BREAKOUT_SCORE','SWING_SCORE','BREAKOUT_PROBABILITY','TREND','ACCUMULATION','DELIVERY','VOLUME_RATIO','RESISTANCE_DISTANCE_PCT','RELATIVE_STRENGTH','BREAKOUT_STATUS','REASONS']; cols=[x for x in cols if x in c.columns]; t=c[cols].copy()
    if 'RANK' in t.columns:t['RANK']=range(1,len(t)+1)
    else:t.insert(0,'RANK',range(1,len(t)+1))
    pre=int((c.CATEGORY=='PRE-BREAKOUT').sum()); brk=int((c.CATEGORY=='BREAKOUT').sum()); sw=int((c.CATEGORY=='SWING').sum()); date=str(df.DATE.iloc[0]) if 'DATE' in df.columns and len(df) else ''
    rows=[['NSE EARLY HUNTER — TRADING DASHBOARD'],['DATA DATE',date],['TOTAL BUY CANDIDATES',len(c)],['🔥 TOP PRE-BREAKOUT',pre],['🚀 TOP BREAKOUT',brk],['📈 TOP SWING',sw],[],['BUY = Entry + SL + Targets are shown below'],[],t.columns.tolist()]; rows += [[('' if pd.isna(v) else v) for v in r] for r in t.itertuples(index=False,name=None)]
    w=book()
    try:ws=w.worksheet('Dashboard')
    except gspread.WorksheetNotFound:ws=w.add_worksheet(title='Dashboard',rows=3000,cols=max(40,len(t.columns)+2))
    ws.clear(); ws.update('A1',rows,value_input_option='USER_ENTERED'); ws.freeze(rows=10)
    try: ws.format('A1:Z1',{'textFormat':{'bold':True,'fontSize':14}}); ws.format('A10:Z10',{'textFormat':{'bold':True}}); ws.format('A1:B6',{'textFormat':{'bold':True}}); ws.format('A10:Z200',{'wrapStrategy':'WRAP'})
    except Exception as e: print('Dashboard format warning:',e)
    t.to_csv(OUT/'dashboard.csv',index=False); print(f'Dashboard updated: {len(t)} candidates | pre={pre} breakout={brk} swing={sw}')
if __name__=='__main__': main()

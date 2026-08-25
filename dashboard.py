from __future__ import annotations
import json, os
from pathlib import Path
import gspread, pandas as pd
from oauth2client.service_account import ServiceAccountCredentials

SPREADSHEET_ID=os.getenv('SPREADSHEET_ID','1U9j5fMZAWPUSwoP_U-GKdacVke9nUjspqPR3wGsWAUM')
OUT=Path('output')
PRE_MAX=10; BREAKOUT_MAX=5; SWING_MAX=5
BUY_ACTIONS={'PRE-BREAKOUT BUY','BREAKOUT BUY','SWING BUY'}

def book():
    raw=os.getenv('GCP_CREDENTIALS')
    if not raw: raise RuntimeError('GCP_CREDENTIALS secret missing')
    creds=ServiceAccountCredentials.from_json_keyfile_dict(json.loads(raw),['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive'])
    return gspread.authorize(creds).open_by_key(SPREADSHEET_ID)

def main():
    hf=OUT/'early_hunter.csv'
    if not hf.exists(): raise RuntimeError('output/early_hunter.csv not found')
    df=pd.read_csv(hf)
    if df.empty:
        c=df.copy()
    else:
        for col in ('PRE_BREAKOUT_SCORE','BREAKOUT_SCORE','SWING_SCORE','BREAKOUT_PROBABILITY','RISK_PCT','RESISTANCE_DISTANCE_PCT'):
            if col in df.columns: df[col]=pd.to_numeric(df[col],errors='coerce')
        pre=df[df.ACTION.eq('PRE-BREAKOUT BUY')].sort_values(['BREAKOUT_PROBABILITY','PRE_BREAKOUT_SCORE'],ascending=False).head(PRE_MAX)
        brk=df[df.ACTION.eq('BREAKOUT BUY')].sort_values(['BREAKOUT_PROBABILITY','BREAKOUT_SCORE'],ascending=False).head(BREAKOUT_MAX)
        sw=df[df.ACTION.eq('SWING BUY')].sort_values(['SWING_SCORE','BREAKOUT_PROBABILITY'],ascending=False).head(SWING_MAX)
        c=pd.concat([pre,brk,sw],ignore_index=True)
    c.to_csv(OUT/'buy_candidates.csv',index=False)
    if not c.empty:
        c['CATEGORY']=c['ACTION'].map({'PRE-BREAKOUT BUY':'PRE-BREAKOUT','BREAKOUT BUY':'BREAKOUT','SWING BUY':'SWING'})
        if 'RANK' in c.columns:
            c['RANK']=range(1,len(c)+1)
        else:
            c.insert(0,'RANK',range(1,len(c)+1))
    cols=['RANK','SYMBOL','ACTION','CATEGORY','DATE','BUY_DATE','CMP','ENTRY_PRICE','ENTRY_ZONE','BREAKOUT_TRIGGER','STOP_LOSS','TARGET_1','TARGET_2','TARGET_3','RISK_PCT','R_R','PRE_BREAKOUT_SCORE','BREAKOUT_SCORE','SWING_SCORE','BREAKOUT_PROBABILITY','TREND','ACCUMULATION','DELIVERY','VOLUME_RATIO','RESISTANCE','RESISTANCE_DISTANCE_PCT','RESISTANCE_TESTS','RELATIVE_STRENGTH','BREAKOUT_STATUS','REASONS']
    cols=[x for x in cols if x in c.columns]
    t=c[cols].copy() if not c.empty else pd.DataFrame(columns=cols)
    pre_n=int((df.ACTION=='PRE-BREAKOUT BUY').sum()) if not df.empty else 0
    brk_n=int((df.ACTION=='BREAKOUT BUY').sum()) if not df.empty else 0
    sw_n=int((df.ACTION=='SWING BUY').sum()) if not df.empty else 0
    date=str(df.DATE.iloc[0]) if 'DATE' in df.columns and len(df) else ''
    rows=[['NSE EARLY HUNTER — TRADING DASHBOARD'],['DATA DATE',date],['QUALIFIED PRE-BREAKOUT',pre_n],['QUALIFIED BREAKOUT',brk_n],['QUALIFIED SWING',sw_n],['DISPLAYED',f'{PRE_MAX} pre + {BREAKOUT_MAX} breakout + {SWING_MAX} swing maximum'],['NOTE','Model confidence is not a guaranteed probability.'],[],['BUY = Entry + SL + Targets are shown below'],[],t.columns.tolist()]
    rows += [[('' if pd.isna(v) else v) for v in r] for r in t.itertuples(index=False,name=None)]
    w=book()
    try: ws=w.worksheet('Dashboard')
    except gspread.WorksheetNotFound: ws=w.add_worksheet(title='Dashboard',rows=3000,cols=max(40,len(t.columns)+2))
    ws.clear(); ws.update('A1',rows,value_input_option='USER_ENTERED')
    try:
        ws.freeze(rows=11); ws.format('A1:Z1',{'textFormat':{'bold':True,'fontSize':14}}); ws.format('A11:Z11',{'textFormat':{'bold':True}}); ws.format('A1:B7',{'textFormat':{'bold':True}}); ws.format('A1:Z200',{'wrapStrategy':'WRAP'})
    except Exception as e: print('Dashboard format warning:',e)
    t.to_csv(OUT/'dashboard.csv',index=False)
    print(f'Dashboard updated: displayed={len(t)} | pre={pre_n} breakout={brk_n} swing={sw_n}')
if __name__=='__main__': main()

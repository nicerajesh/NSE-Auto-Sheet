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


def _calibration():
    p=OUT/'score_calibration.csv'
    if not p.exists(): return pd.DataFrame()
    try:return pd.read_csv(p)
    except Exception:return pd.DataFrame()


def _confidence(row,cal):
    # Prefer historical event calibration. Fall back to the capped model confidence only when no bucket has enough data.
    score=pd.to_numeric(pd.Series([row.get('PRE_BREAKOUT_SCORE',row.get('HUNTER_SCORE',0))]),errors='coerce').iloc[0]
    action=str(row.get('ACTION',''))
    if pd.notna(score) and not cal.empty and {'ANALYSIS','ACTION','SCORE_BUCKET','BREAKOUT_RATE','TRADES'}.issubset(cal.columns):
        q=cal[(cal.ANALYSIS=='BREAKOUT_EVENT') & (cal.ACTION==action)].copy()
        if not q.empty:
            if score>=90:bucket='90+'
            elif score>=82:bucket='82-89'
            elif score>=75:bucket='75-81'
            elif score>=68:bucket='68-74'
            else:bucket='<68'
            z=q[(q.SCORE_BUCKET.astype(str)==bucket) & (q.TRADES>=5)]
            if not z.empty and pd.notna(z.BREAKOUT_RATE.iloc[0]): return round(float(z.BREAKOUT_RATE.iloc[0]),1)
    try:return min(90.0,max(0.0,float(row.get('BREAKOUT_PROBABILITY',0))))
    except Exception:return 0.0


def main():
    hf=OUT/'early_hunter.csv'
    if not hf.exists(): raise RuntimeError('output/early_hunter.csv not found')
    df=pd.read_csv(hf); cal=_calibration()
    if df.empty:c=df.copy()
    else:
        for col in ('PRE_BREAKOUT_SCORE','BREAKOUT_SCORE','SWING_SCORE','BREAKOUT_PROBABILITY','RISK_PCT','RESISTANCE_DISTANCE_PCT'):
            if col in df.columns:df[col]=pd.to_numeric(df[col],errors='coerce')
        gate_pass=('QUALITY_GATE' not in df.columns) or df.QUALITY_GATE.astype(str).eq('PASS')
        eligible=df[gate_pass & df.ACTION.isin(BUY_ACTIONS)].copy()
        if not eligible.empty:eligible['BREAKOUT_CONFIDENCE']=eligible.apply(lambda r:_confidence(r,cal),axis=1)
        pre=eligible[eligible.ACTION.eq('PRE-BREAKOUT BUY')].sort_values(['BREAKOUT_CONFIDENCE','PRE_BREAKOUT_SCORE'],ascending=False).head(PRE_MAX)
        brk=eligible[eligible.ACTION.eq('BREAKOUT BUY')].sort_values(['BREAKOUT_CONFIDENCE','BREAKOUT_SCORE'],ascending=False).head(BREAKOUT_MAX)
        sw=eligible[eligible.ACTION.eq('SWING BUY')].sort_values(['SWING_SCORE','BREAKOUT_CONFIDENCE'],ascending=False).head(SWING_MAX)
        c=pd.concat([pre,brk,sw],ignore_index=True)
    c.to_csv(OUT/'buy_candidates.csv',index=False)
    if not c.empty:
        c['CATEGORY']=c['ACTION'].map({'PRE-BREAKOUT BUY':'PRE-BREAKOUT','BREAKOUT BUY':'BREAKOUT','SWING BUY':'SWING'})
        c['BREAKOUT_CONFIDENCE']=c.apply(lambda r:_confidence(r,cal),axis=1)
        if 'RANK' in c.columns:c['RANK']=range(1,len(c)+1)
        else:c.insert(0,'RANK',range(1,len(c)+1))
    cols=['RANK','SYMBOL','ACTION','CATEGORY','DATE','BUY_DATE','CMP','ENTRY_PRICE','ENTRY_ZONE','MAX_BUY_PRICE','BREAKOUT_TRIGGER','STOP_LOSS','TARGET_1','TARGET_2','TARGET_3','RISK_PCT','R_R','PRE_BREAKOUT_SCORE','BREAKOUT_SCORE','SWING_SCORE','BREAKOUT_CONFIDENCE','TREND','ACCUMULATION','DELIVERY','VOLUME_RATIO','RESISTANCE','RESISTANCE_DISTANCE_PCT','RESISTANCE_TESTS','RELATIVE_STRENGTH','BREAKOUT_STATUS','REASONS']
    cols=[x for x in cols if x in c.columns]
    t=c[cols].copy() if not c.empty else pd.DataFrame(columns=cols)
    pre_n=int((df.ACTION=='PRE-BREAKOUT BUY').sum()) if not df.empty and 'ACTION' in df.columns else 0
    brk_n=int((df.ACTION=='BREAKOUT BUY').sum()) if not df.empty and 'ACTION' in df.columns else 0
    sw_n=int((df.ACTION=='SWING BUY').sum()) if not df.empty and 'ACTION' in df.columns else 0
    gate=str(df.QUALITY_GATE.iloc[0]) if not df.empty and 'QUALITY_GATE' in df.columns else 'UNKNOWN';date=str(df.DATE.iloc[0]) if 'DATE' in df.columns and len(df) else ''
    event_rate='N/A'; pre_event='N/A'
    if not cal.empty and 'ANALYSIS' in cal.columns and 'BREAKOUT_RATE' in cal.columns:
        ev=cal[cal.ANALYSIS.eq('BREAKOUT_EVENT')]
        if not ev.empty:
            event_rate=f"{ev.BREAKOUT_RATE.mul(ev.TRADES).sum()/max(1,ev.TRADES.sum()):.1f}%"
            pe=ev[ev.ACTION.astype(str).str.contains('PRE-BREAKOUT',na=False)]
            if not pe.empty:pre_event=f"{pe.BREAKOUT_RATE.mul(pe.TRADES).sum()/max(1,pe.TRADES.sum()):.1f}%"
    rows=[['NSE EARLY HUNTER — TRADING DASHBOARD'],['DATA DATE',date],['QUALITY GATE',gate],['MODEL PRE-BREAKOUT',pre_n],['MODEL BREAKOUT',brk_n],['MODEL SWING',sw_n],['HISTORICAL EVENT BREAKOUT RATE',event_rate],['HISTORICAL PRE-BREAKOUT HIT RATE',pre_event],['DISPLAYED',f'{PRE_MAX} pre + {BREAKOUT_MAX} breakout + {SWING_MAX} swing maximum'],['NOTE','BREAKOUT_CONFIDENCE is historical event calibration when enough samples exist; otherwise it is capped model confidence.'],[],t.columns.tolist()]
    rows += [[('' if pd.isna(v) else v) for v in r] for r in t.itertuples(index=False,name=None)]
    w=book()
    try:ws=w.worksheet('Dashboard')
    except gspread.WorksheetNotFound:ws=w.add_worksheet(title='Dashboard',rows=3000,cols=max(40,len(t.columns)+2))
    ws.batch_clear(['A1:ZZ5000']);ws.update('A1',rows,value_input_option='USER_ENTERED')
    try:
        ws.freeze(rows=12);ws.format('A1:Z1',{'textFormat':{'bold':True,'fontSize':14}});ws.format('A12:Z12',{'textFormat':{'bold':True}});ws.format('A1:B10',{'textFormat':{'bold':True}});ws.format('A1:Z200',{'wrapStrategy':'WRAP'})
    except Exception as e:print('Dashboard format warning:',e)
    t.to_csv(OUT/'dashboard.csv',index=False)
    print(f'Dashboard updated: displayed={len(t)} | pre={pre_n} breakout={brk_n} swing={sw_n} | gate={gate} | event={event_rate} | pre_event={pre_event}')

if __name__=='__main__':main()

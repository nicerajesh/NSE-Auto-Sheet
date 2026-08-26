from __future__ import annotations
import json, os
from pathlib import Path
import gspread, pandas as pd
from oauth2client.service_account import ServiceAccountCredentials

SPREADSHEET_ID=os.getenv('SPREADSHEET_ID','1U9j5fMZAWPUSwoP_U-GKdacVke9nUjspqPR3wGsWAUM');OUT=Path('output')
PRE_MAX=10;BREAKOUT_MAX=5;SWING_MAX=5;BUY_ACTIONS={'PRE-BREAKOUT BUY','BREAKOUT BUY','SWING BUY'};MIN_PROB_SAMPLES=30

def book():
    raw=os.getenv('GCP_CREDENTIALS')
    if not raw:raise RuntimeError('GCP_CREDENTIALS secret missing')
    creds=ServiceAccountCredentials.from_json_keyfile_dict(json.loads(raw),['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive'])
    return gspread.authorize(creds).open_by_key(SPREADSHEET_ID)

def _calibration():
    p=OUT/'score_calibration.csv'
    if not p.exists():return pd.DataFrame()
    try:return pd.read_csv(p)
    except Exception:return pd.DataFrame()

def _confidence(row,cal):
    score=pd.to_numeric(pd.Series([row.get('PRE_BREAKOUT_SCORE',row.get('HUNTER_SCORE',0))]),errors='coerce').iloc[0];action=str(row.get('ACTION',''))
    if pd.notna(score) and not cal.empty and {'ANALYSIS','ACTION','SCORE_BUCKET','BREAKOUT_RATE','TRADES'}.issubset(cal.columns):
        q=cal[(cal.ANALYSIS=='BREAKOUT_EVENT')&(cal.ACTION==action)].copy()
        if not q.empty:
            bucket='90+' if score>=90 else '82-89' if score>=82 else '75-81' if score>=75 else '68-74' if score>=68 else '<68';z=q[(q.SCORE_BUCKET.astype(str)==bucket)&(q.TRADES>=MIN_PROB_SAMPLES)]
            if not z.empty and pd.notna(z.BREAKOUT_RATE.iloc[0]):return round(float(z.BREAKOUT_RATE.iloc[0]),1)
    return None

def main():
    hf=OUT/'early_hunter.csv'
    if not hf.exists():raise RuntimeError('output/early_hunter.csv not found')
    df=pd.read_csv(hf);cal=_calibration()
    for col in ('PRE_BREAKOUT_SCORE','BREAKOUT_SCORE','SWING_SCORE','BREAKOUT_PROBABILITY','RISK_PCT','RESISTANCE_DISTANCE_PCT'):
        if col in df.columns:df[col]=pd.to_numeric(df[col],errors='coerce')
    model=df[df.ACTION.isin(BUY_ACTIONS)].copy() if not df.empty and 'ACTION' in df.columns else pd.DataFrame(columns=df.columns)
    # Published BUY means a real executable BUY survived quality and entry gates.
    if 'FINAL_ACTION' in df.columns:published=df[df.FINAL_ACTION.isin(BUY_ACTIONS)].copy()
    else:published=model.copy()
    blocked=model[~model.SYMBOL.isin(published.SYMBOL)] if not model.empty else model.copy()
    eligible=published.copy()
    if not eligible.empty:eligible['BREAKOUT_CONFIDENCE']=eligible.apply(lambda r:_confidence(r,cal),axis=1)
    pre=eligible[eligible.ACTION.eq('PRE-BREAKOUT BUY')].sort_values(['BREAKOUT_CONFIDENCE','PRE_BREAKOUT_SCORE'],ascending=False,na_position='last').head(PRE_MAX)
    brk=eligible[eligible.ACTION.eq('BREAKOUT BUY')].sort_values(['BREAKOUT_CONFIDENCE','BREAKOUT_SCORE'],ascending=False,na_position='last').head(BREAKOUT_MAX)
    sw=eligible[eligible.ACTION.eq('SWING BUY')].sort_values(['SWING_SCORE','BREAKOUT_CONFIDENCE'],ascending=False,na_position='last').head(SWING_MAX)
    c=pd.concat([pre,brk,sw],ignore_index=True);c.to_csv(OUT/'buy_candidates.csv',index=False)
    if not c.empty:c.insert(0,'RANK',range(1,len(c)+1))
    cols=['RANK','SYMBOL','ACTION','CATEGORY','DATE','BUY_DATE','CMP','ENTRY_PRICE','ENTRY_ZONE','MAX_BUY_PRICE','BREAKOUT_TRIGGER','STOP_LOSS','TARGET_1','TARGET_2','TARGET_3','RISK_PCT','R_R','PRE_BREAKOUT_SCORE','BREAKOUT_SCORE','SWING_SCORE','BREAKOUT_CONFIDENCE','TREND','ACCUMULATION','DELIVERY','VOLUME_RATIO','RESISTANCE','RESISTANCE_DISTANCE_PCT','RESISTANCE_TESTS','RELATIVE_STRENGTH','BREAKOUT_STATUS','REASONS'];cols=[x for x in cols if x in c.columns];t=c[cols].copy() if not c.empty else pd.DataFrame(columns=cols)
    pre_n=int((model.ACTION=='PRE-BREAKOUT BUY').sum()) if not model.empty else 0;brk_n=int((model.ACTION=='BREAKOUT BUY').sum()) if not model.empty else 0;sw_n=int((model.ACTION=='SWING BUY').sum()) if not model.empty else 0
    gate=str(df.QUALITY_GATE.iloc[0]) if not df.empty and 'QUALITY_GATE' in df.columns else 'UNKNOWN';date=str(df.DATE.iloc[0]) if 'DATE' in df.columns and len(df) else ''
    blocked_n=len(blocked);published_n=len(published)
    event_rate='N/A';pre_event='N/A'
    if not cal.empty and {'ANALYSIS','BREAKOUT_RATE','TRADES'}.issubset(cal.columns):
        ev=cal[cal.ANALYSIS.eq('BREAKOUT_EVENT')]
        if not ev.empty:
            valid=ev[ev.TRADES>=MIN_PROB_SAMPLES]
            if not valid.empty:event_rate=f"{valid.BREAKOUT_RATE.mul(valid.TRADES).sum()/max(1,valid.TRADES.sum()):.1f}%"
            pe=valid[valid.ACTION.astype(str).str.contains('PRE-BREAKOUT',na=False)]
            if not pe.empty:pre_event=f"{pe.BREAKOUT_RATE.mul(pe.TRADES).sum()/max(1,pe.TRADES.sum()):.1f}%"
    rows=[['NSE EARLY HUNTER — TRADING DASHBOARD'],['DATA DATE',date],['QUALITY GATE',gate],['MODEL CANDIDATES',len(model)],['MODEL PRE-BREAKOUT',pre_n],['MODEL BREAKOUT',brk_n],['MODEL SWING',sw_n],['PUBLISHED BUY',published_n],['QUALITY / ENTRY BLOCKED',blocked_n],['RESISTANCE EVENT HIT RATE',event_rate],['PRE-BREAKOUT EVENT HIT RATE',pre_event],['NOTE','Event hit rate is NOT profitable trade probability. Minimum sample threshold is enforced.'],[],['PUBLISHED BUY TABLE']]
    rows += [t.columns.tolist()] + [[('' if pd.isna(v) else v) for v in r] for r in t.itertuples(index=False,name=None)]
    if blocked_n:
        bcols=[x for x in ['SYMBOL','ACTION','HUNTER_SCORE','ENTRY_STATUS','QUALITY_STATUS','FINAL_ACTION','RELEASE_BLOCK_REASON','SECTOR_STATUS','SECTOR_REASON'] if x in blocked.columns]
        rows += [[],['BLOCKED MODEL CANDIDATES'],bcols]+[[('' if pd.isna(v) else v) for v in r] for r in blocked[bcols].itertuples(index=False,name=None)]
    w=book()
    try:ws=w.worksheet('Dashboard')
    except gspread.WorksheetNotFound:ws=w.add_worksheet(title='Dashboard',rows=3000,cols=max(40,len(t.columns)+5))
    ws.clear();ws.update(values=rows,range_name='A1',value_input_option='USER_ENTERED')
    try:ws.freeze(rows=15);ws.format('A1:Z1',{'textFormat':{'bold':True,'fontSize':14}});ws.format('A1:B12',{'textFormat':{'bold':True}});ws.format('A15:Z15',{'textFormat':{'bold':True}});ws.format('A1:Z400',{'wrapStrategy':'WRAP'})
    except Exception as e:print('Dashboard format warning:',e)
    t.to_csv(OUT/'dashboard.csv',index=False)
    print(f'Dashboard updated | model={len(model)} published={published_n} blocked={blocked_n} | event={event_rate} | pre_event={pre_event}')

if __name__=='__main__':main()

from __future__ import annotations
import json, os, time
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
import gspread, pandas as pd, requests
from oauth2client.service_account import ServiceAccountCredentials
from indicator import add_indicators_all
from strategy import scan_all
from backtest import run_backtest
from trade_manager import update_ledger
from quality_gate import evaluate
from d1_database import sync_latest

SPREADSHEET_ID=os.getenv('SPREADSHEET_ID','1U9j5fMZAWPUSwoP_U-GKdacVke9nUjspqPR3wGsWAUM')
VOLUME_SHEET='Top 250 Stocks'; TURNOVER_SHEET='Top 250 Turnover'; HUNTER_SHEET='Early Hunter'
HISTORY_DAYS=int(os.getenv('HISTORY_DAYS','180')); MIN_TURNOVER_LACS=float(os.getenv('MIN_TURNOVER_LACS','1')); MIN_SCORE=int(os.getenv('MIN_SCORE','68'))
OUT=Path('output'); OUT.mkdir(exist_ok=True)

creds_json=os.getenv('GCP_CREDENTIALS')
if not creds_json: raise RuntimeError('GCP_CREDENTIALS secret missing')
creds=ServiceAccountCredentials.from_json_keyfile_dict(json.loads(creds_json),['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive'])
book=gspread.authorize(creds).open_by_key(SPREADSHEET_ID)
wv=book.worksheet(VOLUME_SHEET); wt=book.worksheet(TURNOVER_SHEET)
try: wh=book.worksheet(HUNTER_SHEET)
except gspread.WorksheetNotFound: wh=book.add_worksheet(title=HUNTER_SHEET,rows=3000,cols=100)

def sess():
    s=requests.Session(); s.headers.update({'User-Agent':'Mozilla/5.0 Chrome/151 Safari/537.36','Accept-Language':'en-US,en;q=0.9','Referer':'https://www.nseindia.com/'})
    try:s.get('https://www.nseindia.com',timeout=15)
    except Exception:pass
    return s

def normalize_headers(df):
    rename={}
    for c in df.columns:
        clean=str(c).replace('\ufeff','').strip().upper().replace(' ','_')
        rename[c]=clean
    return df.rename(columns=rename)

def fetch(s,d):
    url=f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d:%d%m%Y}.csv"
    try:
        r=s.get(url,timeout=25)
        if r.status_code!=200 or len(r.content)<500:return None
        df=pd.read_csv(StringIO(r.text),encoding='utf-8-sig'); df=normalize_headers(df)
        aliases={'OPEN':'OPEN_PRICE','HIGH':'HIGH_PRICE','LOW':'LOW_PRICE','CLOSE':'CLOSE_PRICE','VOLUME':'TTL_TRD_QNTY','DELIVERY_PCT':'DELIV_PER','DELIVERY_PERCENT':'DELIV_PER','DELIVERY_QUANTITY':'DELIV_QTY'}
        for old,new in aliases.items():
            if old in df.columns and new not in df.columns: df=df.rename(columns={old:new})
        need=['SYMBOL','SERIES','OPEN_PRICE','HIGH_PRICE','LOW_PRICE','CLOSE_PRICE','TTL_TRD_QNTY','TURNOVER_LACS','DELIV_QTY','DELIV_PER']
        missing=[c for c in need if c not in df.columns]
        if missing:
            print(f"Skip {d:%Y-%m-%d}: missing={missing}; columns={list(df.columns)[:30]}"); return None
        df=df[df.SERIES.astype(str).str.strip().eq('EQ')].copy()
        df=df[~df.SYMBOL.astype(str).str.contains('BEES|ETF|GOLD|LIQUID|SILVER|CASE',case=False,regex=True,na=False)]
        for c in need[2:]:df[c]=pd.to_numeric(df[c],errors='coerce')
        df=df.dropna(subset=['SYMBOL','OPEN_PRICE','HIGH_PRICE','LOW_PRICE','CLOSE_PRICE','TTL_TRD_QNTY','TURNOVER_LACS'])
        df['SYMBOL']=df['SYMBOL'].astype(str).str.strip().str.upper(); df=df[df.TURNOVER_LACS>=MIN_TURNOVER_LACS].copy(); df['DATE']=pd.Timestamp(d)
        return df
    except Exception as e: print('Fetch',d,e); return None

s=sess(); frames=[]; d=datetime.now(); attempts=0
while len(frames)<HISTORY_DAYS and attempts<HISTORY_DAYS+80:
    if d.weekday()<5:
        x=fetch(s,d)
        if x is not None and not x.empty:frames.append(x); print(f'Loaded {d:%Y-%m-%d}: {len(x)}')
        time.sleep(.20)
    d-=timedelta(days=1); attempts+=1
if not frames:raise RuntimeError('No NSE bhavcopy data found')
hist=pd.concat(frames,ignore_index=True); hist.columns=[str(c).replace('\ufeff','').strip().upper() for c in hist.columns]
if 'SYMBOL' not in hist.columns: raise RuntimeError(f'NSE history has no SYMBOL column; columns={list(hist.columns)}')
hist=hist.sort_values(['SYMBOL','DATE']).drop_duplicates(['SYMBOL','DATE']).reset_index(drop=True)
# Keep the original keys so downstream processing can never lose stock identity.
original_symbols=hist['SYMBOL'].astype(str).str.strip().str.upper().reset_index(drop=True)
hist=add_indicators_all(hist)
if 'SYMBOL' not in hist.columns:
    if len(hist) != len(original_symbols):
        raise RuntimeError(f'Indicator output lost SYMBOL and row count changed: input={len(original_symbols)} output={len(hist)}')
    hist['SYMBOL']=original_symbols.to_numpy()
hist['SYMBOL']=hist['SYMBOL'].astype(str).str.strip().str.upper()
if 'SYMBOL' not in hist.columns: raise RuntimeError(f'Historical indicator data has no SYMBOL; columns={list(hist.columns)}')
latest_date=hist.DATE.max(); latest=hist[hist.DATE.eq(latest_date)].copy()
med=hist.groupby('DATE')['RET_20D'].transform('median'); hist['RS_VS_UNIVERSE']=hist['RET_20D']-med; hist['RS_RANK']=hist.groupby('DATE')['RET_20D'].rank(pct=True)*100

hunter=scan_all(hist,MIN_SCORE)
if hunter.empty:hunter=pd.DataFrame()
if not hunter.empty:
    rs=hist[hist.DATE.eq(latest_date)][['SYMBOL','RS_VS_UNIVERSE','RS_RANK']]; hunter=hunter.merge(rs,on='SYMBOL',how='left')

bt=run_backtest(hist,MIN_SCORE,30)
if len(bt)==3: trades,stats,cal=bt
else: trades,stats=bt; cal=pd.DataFrame()
trades.to_csv(OUT/'backtest_trades.csv',index=False); pd.DataFrame([stats]).to_csv(OUT/'backtest_summary.csv',index=False); cal.to_csv(OUT/'score_calibration.csv',index=False)

ledger_path=OUT/'trade_ledger.csv'; old=pd.DataFrame(); ledger=update_ledger(old,{str(r['SYMBOL']):r.to_dict() for _,r in hunter.iterrows()} if not hunter.empty else {})
ledger.to_csv(ledger_path,index=False)
if not hunter.empty:
    pos=ledger[['SYMBOL','STATUS','EXIT_DATE','EXIT_PRICE','EXIT_REASON']].drop_duplicates('SYMBOL',keep='last') if not ledger.empty else pd.DataFrame()
    if not pos.empty:hunter=hunter.merge(pos,on='SYMBOL',how='left')

gate_ok,gate_reason=evaluate(stats,cal)
if not gate_ok and not hunter.empty:
    hunter['ACTION']=hunter['ACTION'].replace({'BUY':'WATCH','BUY ON TRIGGER':'WATCH'}); hunter['QUALITY_GATE']=gate_reason
elif not hunter.empty:hunter['QUALITY_GATE']='PASS'
buy=hunter[hunter.ACTION.isin(['BUY','BUY ON TRIGGER'])].copy() if not hunter.empty else pd.DataFrame()

latest.to_csv(OUT/'latest_market.csv',index=False); hist[hist.DATE.eq(latest_date)].to_csv(OUT/'indicators.csv',index=False); hunter.to_csv(OUT/'early_hunter.csv',index=False); buy.to_csv(OUT/'buy_candidates.csv',index=False)

sync_latest(latest,hunter,stats,latest_date.strftime('%Y-%m-%d'))

def ensure(ws,n):
    if ws.col_count<n:ws.add_cols(n-ws.col_count)
ensure(wv,12); ensure(wt,22); ensure(wh,max(100,len(hunter.columns) if not hunter.empty else 20))
vol=latest.nlargest(250,'TTL_TRD_QNTY'); turn=latest.nlargest(250,'TURNOVER_LACS')
wv.batch_clear(['A2:C251']); wv.update('A2',vol[['SYMBOL','TTL_TRD_QNTY','CLOSE_PRICE']].values.tolist())
wt.batch_clear(['A2:F251']); wt.update('A2',turn[['SYMBOL','TTL_TRD_QNTY','CLOSE_PRICE','TURNOVER_LACS','DELIV_QTY','DELIV_PER']].values.tolist())
wh.clear()
if not hunter.empty:rows=[hunter.columns.tolist()]+hunter.astype(object).where(pd.notna(hunter),'').values.tolist()
else:rows=[['NO QUALIFIED EARLY-HUNTER SETUP TODAY']]
rows += [[''],['BACKTEST SUMMARY']]+[[k,v] for k,v in stats.items()]+[['QUALITY_GATE',gate_reason]]
if not cal.empty:rows += [[''],['SCORE CALIBRATION']]+[cal.columns.tolist()]+cal.astype(object).where(pd.notna(cal),'').values.tolist()
wh.update('A1',rows)
try:wh.freeze(rows=1);wh.format('A1:CV1',{'textFormat':{'bold':True},'horizontalAlignment':'CENTER'})
except Exception as e:print('Format',e)
status=f"Data {latest_date:%d-%b-%Y} | BUY {len(buy)} | BT {stats.get('trades',0)} | Win {stats.get('win_rate_pct',0)}% | PF {stats.get('profit_factor',0)} | Gate {gate_reason}"
wv.update('L2',[[status]]); wt.update('V2',[[status]])
print(status)
if not buy.empty:print(buy[['SYMBOL','ACTION','STAGE','HUNTER_SCORE','CMP','BUY_ZONE_LOW','BUY_ZONE_HIGH','ENTRY_TRIGGER','STOP_LOSS','TARGET_1','TARGET_2','TARGET_3']].head(30).to_string(index=False))

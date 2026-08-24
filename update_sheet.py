from __future__ import annotations
import json, os, time, re
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
STOCKS_SHEET='Top 500 Stocks'; HUNTER_SHEET='Early Hunter'
HISTORY_DAYS=int(os.getenv('HISTORY_DAYS','180')); MIN_TURNOVER_LACS=float(os.getenv('MIN_TURNOVER_LACS','1')); MIN_SCORE=int(os.getenv('MIN_SCORE','72'))
OUT=Path('output'); OUT.mkdir(exist_ok=True)
creds_json=os.getenv('GCP_CREDENTIALS')
if not creds_json: raise RuntimeError('GCP_CREDENTIALS secret missing')
creds=ServiceAccountCredentials.from_json_keyfile_dict(json.loads(creds_json),['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive'])
book=gspread.authorize(creds).open_by_key(SPREADSHEET_ID)

def get_or_create(title,rows=3000,cols=100):
    try:return book.worksheet(title)
    except gspread.WorksheetNotFound:return book.add_worksheet(title=title,rows=rows,cols=cols)
ws_stocks=get_or_create(STOCKS_SHEET,1000,30); ws_hunter=get_or_create(HUNTER_SHEET,3000,100)
for old_name in ('Top 250 Stocks','Top 250 Turnover','Top 500 Turnover','Turnover'):
    try:
        old=book.worksheet(old_name)
        if old.id not in (ws_stocks.id,ws_hunter.id):book.del_worksheet(old)
    except gspread.WorksheetNotFound:pass

def sess():
    s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36','Accept-Language':'en-US,en;q=0.9','Referer':'https://www.nseindia.com/','Accept':'application/json,text/plain,*/*'})
    try:s.get('https://www.nseindia.com',timeout=20)
    except Exception:pass
    return s

def fetch_nifty500_symbols(s):
    urls=['https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv','https://www.niftyindices.com/IndexConstituent/ind_nifty500list.xlsx']
    h={'User-Agent':s.headers.get('User-Agent'),'Referer':'https://www.niftyindices.com/','Accept':'text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*'}
    for url in urls:
        try:
            r=s.get(url,headers=h,timeout=30)
            if not r.ok or len(r.content)<1000:continue
            if url.endswith('.csv'):df=pd.read_csv(StringIO(r.content.decode('utf-8-sig',errors='replace')))
            else:df=pd.read_excel(StringIO(r.content))
            cols={str(c).strip().upper().replace(' ','_'):c for c in df.columns};col=cols.get('SYMBOL') or cols.get('SYMBOLS') or cols.get('SECURITY')
            if not col:continue
            syms=df[col].astype(str).str.strip().str.upper();syms=[x for x in syms if re.fullmatch(r'[A-Z0-9&.-]+',x) and not any(k in x for k in ('ETF','BEES','GOLD','SILVER','LIQUID'))]
            if len(syms)>=450:print(f'NIFTY 500 universe loaded from official NSE Indices: {len(syms)} symbols');return set(syms)
        except Exception as e:print('Nifty500 official source failed:',e)
    raise RuntimeError('Unable to obtain NIFTY 500 constituents from official NSE Indices. No turnover fallback.')

def normalize_headers(df):return df.rename(columns={c:str(c).replace('\ufeff','').strip().upper().replace(' ','_') for c in df.columns})

def fetch_bhav(s,d):
    url=f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d:%d%m%Y}.csv"
    try:
        r=s.get(url,timeout=25)
        if r.status_code!=200 or len(r.content)<500:return None
        df=normalize_headers(pd.read_csv(StringIO(r.text),encoding='utf-8-sig'));aliases={'OPEN':'OPEN_PRICE','HIGH':'HIGH_PRICE','LOW':'LOW_PRICE','CLOSE':'CLOSE_PRICE','VOLUME':'TTL_TRD_QNTY','DELIVERY_PCT':'DELIV_PER','DELIVERY_PERCENT':'DELIV_PER','DELIVERY_QUANTITY':'DELIV_QTY'}
        for old,new in aliases.items():
            if old in df.columns and new not in df.columns:df=df.rename(columns={old:new})
        need=['SYMBOL','SERIES','OPEN_PRICE','HIGH_PRICE','LOW_PRICE','CLOSE_PRICE','TTL_TRD_QNTY','TURNOVER_LACS','DELIV_QTY','DELIV_PER'];missing=[c for c in need if c not in df.columns]
        if missing:print(f'Skip {d:%Y-%m-%d}: missing={missing}');return None
        df=df[df.SERIES.astype(str).str.strip().eq('EQ')].copy();df=df[~df.SYMBOL.astype(str).str.contains(r'BEES|ETF|GOLD|LIQUID|SILVER|CASE',case=False,regex=True,na=False)]
        for c in need[2:]:df[c]=pd.to_numeric(df[c],errors='coerce')
        df=df.dropna(subset=['SYMBOL','OPEN_PRICE','HIGH_PRICE','LOW_PRICE','CLOSE_PRICE','TTL_TRD_QNTY','TURNOVER_LACS']);df['SYMBOL']=df['SYMBOL'].astype(str).str.strip().str.upper();df=df[df.TURNOVER_LACS>=MIN_TURNOVER_LACS].copy();df['DATE']=pd.Timestamp(d);return df
    except Exception as e:print('Fetch',d,e);return None

s=sess();universe=fetch_nifty500_symbols(s);frames=[];d=datetime.now();attempts=0
while len(frames)<HISTORY_DAYS and attempts<HISTORY_DAYS+80:
    if d.weekday()<5:
        x=fetch_bhav(s,d)
        if x is not None and not x.empty:
            x=x[x.SYMBOL.isin(universe)].copy()
            if not x.empty:frames.append(x);print(f'Loaded {d:%Y-%m-%d}: {len(x)} NIFTY500 EQ rows')
        time.sleep(.20)
    d-=timedelta(days=1);attempts+=1
if not frames:raise RuntimeError('No NIFTY 500 NSE bhavcopy data found')
hist=pd.concat(frames,ignore_index=True);hist.columns=[str(c).replace('\ufeff','').strip().upper() for c in hist.columns]
if 'SYMBOL' not in hist.columns:raise RuntimeError(f'NSE history has no SYMBOL column; columns={list(hist.columns)}')
hist=hist.sort_values(['SYMBOL','DATE']).drop_duplicates(['SYMBOL','DATE']).reset_index(drop=True)
original_symbols=hist.SYMBOL.astype(str).str.strip().str.upper().reset_index(drop=True);hist=add_indicators_all(hist)
if 'SYMBOL' not in hist.columns:
    if len(hist)!=len(original_symbols):raise RuntimeError(f'Indicator output lost SYMBOL and row count changed: input={len(original_symbols)} output={len(hist)}')
    hist['SYMBOL']=original_symbols.to_numpy()
hist.SYMBOL=hist.SYMBOL.astype(str).str.strip().str.upper();latest_date=hist.DATE.max();latest=hist[hist.DATE.eq(latest_date)].copy()
med=hist.groupby('DATE')['RET_20D'].transform('median');hist['RS_VS_UNIVERSE']=hist.RET_20D-med;hist['RS_RANK']=hist.groupby('DATE').RET_20D.rank(pct=True)*100
hunter=scan_all(hist,MIN_SCORE);hunter=pd.DataFrame() if hunter is None else hunter
if not hunter.empty:
    rs=hist[hist.DATE.eq(latest_date)][['SYMBOL','RS_VS_UNIVERSE','RS_RANK']];hunter=hunter.merge(rs,on='SYMBOL',how='left')
trades,stats,cal=run_backtest(hist,MIN_SCORE,30);stats=stats or {};cal=cal if cal is not None else pd.DataFrame()
trades.to_csv(OUT/'backtest_trades.csv',index=False);pd.DataFrame([stats]).to_csv(OUT/'backtest_summary.csv',index=False);cal.to_csv(OUT/'score_calibration.csv',index=False)
ledger=update_ledger(pd.DataFrame(),{str(r['SYMBOL']):r.to_dict() for _,r in hunter.iterrows()} if not hunter.empty else {});ledger.to_csv(OUT/'trade_ledger.csv',index=False)
if not hunter.empty and not ledger.empty:
    pos=ledger[['SYMBOL','STATUS','EXIT_DATE','EXIT_PRICE','EXIT_REASON']].drop_duplicates('SYMBOL',keep='last');hunter=hunter.merge(pos,on='SYMBOL',how='left')
gate_ok,gate_reason=evaluate(stats,cal)
# IMPORTANT: backtest quality never silently converts a valid live setup into WATCH.
# It is exposed as a separate QUALITY_GATE status. The strategy itself decides BUY/WAIT.
if not hunter.empty:hunter['QUALITY_GATE']='PASS' if gate_ok else gate_reason
buy=hunter[hunter.ACTION.isin(['BUY','BUY ON TRIGGER'])].copy() if not hunter.empty else pd.DataFrame()
latest.to_csv(OUT/'latest_market.csv',index=False);hist[hist.DATE.eq(latest_date)].to_csv(OUT/'indicators.csv',index=False);hunter.to_csv(OUT/'early_hunter.csv',index=False);buy.to_csv(OUT/'buy_candidates.csv',index=False)
sync_latest(latest,hunter,stats,latest_date.strftime('%Y-%m-%d'))

def ensure(ws,n):
    if ws.col_count<n:ws.add_cols(n-ws.col_count)
ensure(ws_stocks,30);ensure(ws_hunter,max(100,len(hunter.columns) if not hunter.empty else 20))
view=latest.copy();
def bull(r):
    e50,e200=r.get('EMA50'),r.get('EMA200');
    try:
        if pd.notna(e50) and pd.notna(e200):return 'In Bull Run' if float(r.CLOSE_PRICE)>float(e50)>float(e200) else ('In Bear Run' if float(r.CLOSE_PRICE)<float(e50)<float(e200) else 'Unconfirmed')
    except:pass
    return 'Unconfirmed'
view['Bull Run']=view.apply(bull,axis=1);hmap=hunter.set_index('SYMBOL').to_dict('index') if not hunter.empty else {}
def drow(sym):
    r=hmap.get(sym)
    if not r:return ('NO BUY','No Early Hunter setup')
    a=str(r.get('ACTION','WATCH'));return (a,str(r.get('REASONS','Setup requires confirmation')))
view[['Decision','Decision Reason']]=view.SYMBOL.map(drow).apply(pd.Series)
for outcol,hcol in [('Hunter Score','HUNTER_SCORE'),('Stage','STAGE'),('Entry Trigger','ENTRY_TRIGGER'),('Stop Loss','STOP_LOSS'),('Target 1','TARGET_1'),('Target 2','TARGET_2'),('Target 3','TARGET_3')]:view[outcol]=view.SYMBOL.map(lambda x:hmap.get(x,{}).get(hcol,''))
view=view.sort_values(['Decision','Hunter Score'],ascending=[True,False],na_position='last').head(500)
headers=['NSE Code','Volume','Close Price','CMP','50 DMA','100 DMA','200 DMA','Bull Run','Decision','Decision Reason','Hunter Score','Stage','Entry Trigger','Stop Loss','Target 1','Target 2','Target 3','Quality Gate']
rows=[headers]+[[r.SYMBOL,r.TTL_TRD_QNTY,r.CLOSE_PRICE,r.CLOSE_PRICE,getattr(r,'EMA50',''),getattr(r,'EMA100',''),getattr(r,'EMA200',''),r['Bull Run'],r['Decision'],r['Decision Reason'],r['Hunter Score'],r['Stage'],r['Entry Trigger'],r['Stop Loss'],r['Target 1'],r['Target 2'],r['Target 3'],hmap.get(r.SYMBOL,{}).get('QUALITY_GATE',gate_reason)] for _,r in view.iterrows()]
ws_stocks.clear();ws_hunter.clear();ws_stocks.update('A1',rows,value_input_option='USER_ENTERED')
if not hunter.empty:hrows=[hunter.columns.tolist()]+hunter.astype(object).where(pd.notna(hunter),'').values.tolist()
else:hrows=[['NO QUALIFIED EARLY-HUNTER SETUP TODAY']]
hrows += [[''],['UNIVERSE','NIFTY 500'],['DATA DATE',latest_date.strftime('%d-%b-%Y')],['QUALITY GATE',gate_reason],['BUY CANDIDATES',len(buy)],[''],['BACKTEST SUMMARY']]+[[k,v] for k,v in stats.items()]
if not cal.empty:hrows += [[''],['SCORE/HORIZON CALIBRATION']]+[cal.columns.tolist()]+cal.astype(object).where(pd.notna(cal),'').values.tolist()
ws_hunter.update('A1',hrows,value_input_option='USER_ENTERED')
for ws in (ws_stocks,ws_hunter):
    try:ws.freeze(rows=1)
    except Exception:pass
status=f'NIFTY500 | Data {latest_date:%d-%b-%Y} | Universe {len(universe)} | BUY {len(buy)} | BT {stats.get("trades",0)} | Win {stats.get("win_rate_pct",0)}% | PF {stats.get("profit_factor",0)} | Gate {gate_reason}'
ws_stocks.update('T1',[['STATUS']]);ws_stocks.update('T2',[[status]])
print(status)
if not buy.empty:print(buy[['SYMBOL','ACTION','STAGE','HUNTER_SCORE','CMP','BUY_ZONE_LOW','BUY_ZONE_HIGH','ENTRY_TRIGGER','STOP_LOSS','TARGET_1','TARGET_2','TARGET_3']].head(30).to_string(index=False))

from __future__ import annotations
import json, os, time, re
from datetime import datetime, timedelta
from io import StringIO, BytesIO
from pathlib import Path
import gspread, pandas as pd, requests
from oauth2client.service_account import ServiceAccountCredentials
from indicator import add_indicators_all
from strategy import scan_all, BUY_ACTIONS, scan_low52_reversal, scan_apex_matrix
from backtest import run_backtest
from trade_manager import update_ledger
from quality_gate import evaluate
from d1_database import sync_latest, load_open_trades, setup, query
from config import STRAT, BT, NIFTY_SYMBOL
SPREADSHEET_ID=os.getenv('SPREADSHEET_ID','1U9j5fMZAWPUSwoP_U-GKdacVke9nUjspqPR3wGsWAUM'); STOCKS_SHEET='Top 500 Stocks'; HUNTER_SHEET='Early Hunter'
HISTORY_DAYS=int(os.getenv('HISTORY_DAYS','480')); MIN_TURNOVER_LACS=float(os.getenv('MIN_TURNOVER_LACS','1')); MIN_SCORE=int(os.getenv('WATCH_MIN_SCORE','72')); OUT=Path('output'); OUT.mkdir(exist_ok=True)
creds_json=os.getenv('GCP_CREDENTIALS')
if not creds_json: raise RuntimeError('GCP_CREDENTIALS secret missing')
creds=ServiceAccountCredentials.from_json_keyfile_dict(json.loads(creds_json),['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']); book=gspread.authorize(creds).open_by_key(SPREADSHEET_ID)
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
    urls=['https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv','https://www.niftyindices.com/IndexConstituent/ind_nifty500list.xlsx']; h={'User-Agent':s.headers.get('User-Agent'),'Referer':'https://www.niftyindices.com/','Accept':'text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*'}
    for url in urls:
        try:
            r=s.get(url,headers=h,timeout=30)
            if not r.ok or len(r.content)<1000:continue
            if url.endswith('.csv'):df=pd.read_csv(StringIO(r.content.decode('utf-8-sig',errors='replace')))
            else:df=pd.read_excel(BytesIO(r.content),engine='openpyxl')
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
        if missing:return None
        df=df[df.SERIES.astype(str).str.strip().eq('EQ')].copy();df=df[~df.SYMBOL.astype(str).str.contains(r'BEES|ETF|GOLD|LIQUID|SILVER|CASE',case=False,regex=True,na=False)]
        for c in need[2:]:df[c]=pd.to_numeric(df[c],errors='coerce')
        df=df.dropna(subset=['SYMBOL','OPEN_PRICE','HIGH_PRICE','LOW_PRICE','CLOSE_PRICE','TTL_TRD_QNTY','TURNOVER_LACS']);df['SYMBOL']=df['SYMBOL'].astype(str).str.strip().str.upper();df=df[df.TURNOVER_LACS>=MIN_TURNOVER_LACS].copy();df['DATE']=pd.Timestamp(d);return df
    except Exception as e:print('Fetch',d,e);return None

def load_d1_history():
    if not os.getenv('CLOUDFLARE_API_TOKEN') or not os.getenv('CLOUDFLARE_ACCOUNT_ID'): return pd.DataFrame()
    setup(); q=query("SELECT MIN(trade_date) AS min_date, MAX(trade_date) AS max_date, COUNT(*) AS n FROM bhavcopy",required=True); meta=(q.get('result',[{}])[0].get('results') or [{}])[0]
    if not meta.get('max_date'): return pd.DataFrame()
    chunks=[]; cur=pd.Timestamp(meta['min_date']); hi=pd.Timestamp(meta['max_date'])
    while cur<=hi:
        stop=min(cur+pd.Timedelta(days=59),hi); q=query("SELECT symbol,trade_date,open,high,low,close,volume,turnover_lacs,delivery_qty,delivery_pct FROM bhavcopy WHERE trade_date>=? AND trade_date<=? ORDER BY trade_date,symbol",[cur.strftime('%Y-%m-%d'),stop.strftime('%Y-%m-%d')],required=True); rows=(q.get('result',[{}])[0].get('results') or [])
        if rows:chunks.append(pd.DataFrame(rows))
        cur=stop+pd.Timedelta(days=1)
    if not chunks:return pd.DataFrame()
    df=pd.concat(chunks,ignore_index=True).rename(columns={'symbol':'SYMBOL','trade_date':'DATE','open':'OPEN_PRICE','high':'HIGH_PRICE','low':'LOW_PRICE','close':'CLOSE_PRICE','volume':'TTL_TRD_QNTY','turnover_lacs':'TURNOVER_LACS','delivery_qty':'DELIV_QTY','delivery_pct':'DELIV_PER'}); df['DATE']=pd.to_datetime(df['DATE']); return df

s=sess();universe=fetch_nifty500_symbols(s);hist=load_d1_history();frames=[]
latest_stored=pd.to_datetime(hist['DATE']).max() if not hist.empty else None
d=(latest_stored.to_pydatetime()+timedelta(days=1)) if latest_stored is not None else datetime.now()-timedelta(days=HISTORY_DAYS+30); end=datetime.now(); attempts=0
while d.date()<=end.date() and attempts<1000:
    if d.weekday()<5:
        x=fetch_bhav(s,d)
        if x is not None and not x.empty:
            x=x[x.SYMBOL.isin(universe)].copy()
            if not x.empty:frames.append(x);print(f'Incremental load {d:%Y-%m-%d}: {len(x)} NIFTY500 EQ rows')
        time.sleep(.20)
    d+=timedelta(days=1);attempts+=1
if frames:
    new=pd.concat(frames,ignore_index=True); sync_latest(new,pd.DataFrame(),{},pd.to_datetime(new.DATE).max().strftime('%Y-%m-%d'),gate_ok=False); hist=pd.concat([hist,new],ignore_index=True) if not hist.empty else new
if hist.empty:raise RuntimeError('No NIFTY 500 history available in D1 or NSE bhavcopy')
hist=hist[hist.SYMBOL.isin(universe)|hist.SYMBOL.eq(NIFTY_SYMBOL)].sort_values(['SYMBOL','DATE']).drop_duplicates(['SYMBOL','DATE']).reset_index(drop=True); hist=add_indicators_all(hist)
print(f'PERSISTENT HISTORY: {len(hist)} rows | {hist.DATE.nunique()} sessions | latest={hist.DATE.max():%Y-%m-%d}')
latest_date=hist.DATE.max(); latest=hist[hist.DATE.eq(latest_date)].copy(); _rs_pool=hist[hist.SYMBOL.ne(NIFTY_SYMBOL)]; hist['RS_VS_UNIVERSE']=hist.RET_20D-hist.DATE.map(_rs_pool.groupby('DATE')['RET_20D'].median()); hist['RS_RANK']=_rs_pool.groupby('DATE').RET_20D.rank(pct=True).mul(100).reindex(hist.index)
rs_latest=hist.loc[hist.DATE.eq(latest_date),'RS_VS_UNIVERSE'].dropna()
if len(rs_latest)<max(50,int(len(latest)*.25)):print(f'WARNING: RS coverage low: {len(rs_latest)} / {len(latest)}')
hunter=scan_all(hist,MIN_SCORE); hunter=pd.DataFrame() if hunter is None else hunter
if not hunter.empty:hunter=hunter.merge(hist[hist.DATE.eq(latest_date)][['SYMBOL','RS_VS_UNIVERSE','RS_RANK']],on='SYMBOL',how='left')
low52=scan_low52_reversal(hist); low52=pd.DataFrame() if low52 is None else low52
low52.to_csv(OUT/'low52_reversal.csv',index=False)
print(f'LOW52 REVERSAL SCAN: {len(low52)} near 52W low | BUY {int((low52.ACTION=="EARLY REVERSAL BUY").sum()) if not low52.empty else 0} | WATCH {int((low52.ACTION=="REVERSAL WATCH").sum()) if not low52.empty else 0}')
if not low52.empty:print(low52.head(20).to_string(index=False))
apex=scan_apex_matrix(hist); apex=pd.DataFrame() if apex is None else apex
apex.to_csv(OUT/'apex_matrix.csv',index=False)
print(f'APEX MATRIX SCAN: {len(apex)} setups | APEX BUY {int((apex.SIGNAL=="APEX BUY").sum()) if not apex.empty else 0} | TACTICAL BUY {int((apex.SIGNAL=="TACTICAL BUY").sum()) if not apex.empty else 0} | BUY {int((apex.SIGNAL=="BUY").sum()) if not apex.empty else 0}')
if not apex.empty:print(apex.head(20).to_string(index=False))
trades,stats,cal=run_backtest(hist,MIN_SCORE,BT.horizon); stats=stats or {}; cal=cal if cal is not None else pd.DataFrame();
if int(stats.get('trades',0))==0:print(f'BACKTEST DIAGNOSTIC: zero trades | rows={len(hist)} symbols={hist.SYMBOL.nunique()} sessions={hist.DATE.nunique()} threshold={MIN_SCORE} warmup={BT.warmup} horizon={BT.horizon}')
trades.to_csv(OUT/'backtest_trades.csv',index=False);pd.DataFrame([stats]).to_csv(OUT/'backtest_summary.csv',index=False);cal.to_csv(OUT/'score_calibration.csv',index=False);gate_ok,gate_reason=evaluate(stats,cal)
old_rows=[]
try:old_rows=load_open_trades(required=False) or []
except Exception as e:print('D1 ledger load warning:',e)
old=[]
for r in old_rows:old.append({'SYMBOL':r.get('symbol',''),'ENTRY_DATE':r.get('entry_date',''),'ENTRY':r.get('entry_price',''),'STOP_LOSS':r.get('stop_loss',''),'TARGET_1':r.get('target1',''),'TARGET_2':r.get('target2',''),'TARGET_3':r.get('target3',''),'STATUS':r.get('status','OPEN'),'LAST_DATE':r.get('entry_date',''),'LAST_CLOSE':r.get('entry_price',''),'EXIT_DATE':r.get('exit_date',''),'EXIT_PRICE':r.get('exit_price',''),'EXIT_REASON':r.get('exit_reason','')})
hmap=hunter.set_index('SYMBOL').to_dict('index') if not hunter.empty else {}; current={}
for r in latest.itertuples(index=False):
    sym=str(r.SYMBOL);current[sym]={'SYMBOL':sym,'DATE':latest_date.strftime('%Y-%m-%d'),'CMP':float(r.CLOSE_PRICE),'ACTION':'WATCH','STOP_LOSS':None,'TARGET_1':None,'TARGET_2':None,'TARGET_3':None}
for sym,r in hmap.items():current[str(sym)]={**current.get(str(sym),{}),**r,'DATE':latest_date.strftime('%Y-%m-%d')}
ledger=update_ledger(pd.DataFrame(old),current,allow_new=gate_ok);ledger.to_csv(OUT/'trade_ledger.csv',index=False)
if not hunter.empty:hunter=hunter.merge(ledger[['SYMBOL','STATUS','EXIT_DATE','EXIT_PRICE','EXIT_REASON']].drop_duplicates('SYMBOL',keep='last'),on='SYMBOL',how='left')
buy=hunter[hunter.ACTION.isin(BUY_ACTIONS)].copy() if not hunter.empty else pd.DataFrame(columns=hunter.columns if not hunter.empty else []);latest.to_csv(OUT/'latest_market.csv',index=False);hist[hist.DATE.eq(latest_date)].to_csv(OUT/'indicators.csv',index=False);hunter.to_csv(OUT/'early_hunter.csv',index=False);buy.to_csv(OUT/'buy_candidates.csv',index=False)
try:sync_latest(latest,hunter,stats,latest_date.strftime('%Y-%m-%d'),gate_ok=gate_ok)
except Exception as e:print('WARNING: D1 sync failed; continuing with Google Sheet update:',repr(e))
def sheet_scalar(v):
    if v is None:return ''
    if isinstance(v,(dict,list,tuple,set)):return json.dumps(v,sort_keys=True,default=str) if isinstance(v,dict) else ', '.join(map(str,v))
    if isinstance(v,(pd.Timestamp,datetime)):return v.strftime('%Y-%m-%d')
    try:
        if pd.isna(v):return ''
    except Exception:pass
    try:
        if hasattr(v,'item'):return v.item()
    except Exception:pass
    return v
def flat_frame_rows(df):
    if df is None or df.empty:return [['NO QUALIFIED SETUP TODAY']]
    cols=list(df.columns);out=[cols]
    for row in df.itertuples(index=False,name=None):out.append([sheet_scalar(v) for v in row])
    return out
ensure=lambda ws,n: ws.add_cols(n-ws.col_count) if ws.col_count<n else None
ensure(ws_stocks,30);ensure(ws_hunter,max(100,len(hunter.columns) if not hunter.empty else 20));view=latest.copy()
def bull(r):
    try:
        if pd.notna(r.get('EMA50')) and pd.notna(r.get('EMA200')):return 'In Bull Run' if float(r.CLOSE_PRICE)>float(r.EMA50)>float(r.EMA200) else ('In Bear Run' if float(r.CLOSE_PRICE)<float(r.EMA50)<float(r.EMA200) else 'Unconfirmed')
    except Exception:pass
    return 'Unconfirmed'
view['Bull Run']=view.apply(bull,axis=1)
def drow(sym):
    r=hmap.get(sym)
    if not r:return ('NO BUY','No qualified setup')
    action=str(r.get('ACTION','WATCH'))
    if not gate_ok and action in BUY_ACTIONS:return ('QUALITY BLOCKED',f'Model {action}; historical gate: {gate_reason}')
    return (action,str(r.get('REASONS','Setup requires confirmation')))
view[['Decision','Decision Reason']]=view.SYMBOL.map(drow).apply(pd.Series)
for outcol,hcol in [('Hunter Score','HUNTER_SCORE'),('Stage','STAGE'),('Entry Price','ENTRY_PRICE'),('Entry Zone','ENTRY_ZONE'),('Entry Trigger','BREAKOUT_TRIGGER'),('Stop Loss','STOP_LOSS'),('Target 1','TARGET_1'),('Target 2','TARGET_2'),('Target 3','TARGET_3')]:view[outcol]=view.SYMBOL.map(lambda x:hmap.get(x,{}).get(hcol,''))
view=view.sort_values(['Decision','Hunter Score'],ascending=[True,False],na_position='last').head(500)
headers=['NSE Code','Volume','Close Price','CMP','50 DMA','100 DMA','200 DMA','Bull Run','Decision','Decision Reason','Hunter Score','Stage','Entry Price','Entry Zone','Entry Trigger','Stop Loss','Target 1','Target 2','Target 3','Quality Gate'];rows=[headers]+[[sheet_scalar(v) for v in [r.SYMBOL,r.TTL_TRD_QNTY,r.CLOSE_PRICE,r.CLOSE_PRICE,getattr(r,'EMA50',''),getattr(r,'EMA100',''),getattr(r,'EMA200',''),r['Bull Run'],r['Decision'],r['Decision Reason'],r['Hunter Score'],r['Stage'],r['Entry Price'],r['Entry Zone'],r['Entry Trigger'],r['Stop Loss'],r['Target 1'],r['Target 2'],r['Target 3'],hmap.get(r.SYMBOL,{}).get('QUALITY_GATE',gate_reason)]] for _,r in view.iterrows()]
ws_stocks.batch_clear(['A1:ZZ5000']);ws_hunter.batch_clear(['A1:ZZ5000']);ws_stocks.update(values=rows,range_name='A1',value_input_option='USER_ENTERED'); hrows=flat_frame_rows(hunter); ws_hunter.update(values=hrows,range_name='A1',value_input_option='USER_ENTERED')
try:
    def fmt_range(a1,typ='NUMBER',pattern='0.00'):ws_hunter.format(a1,{'numberFormat':{'type':typ,'pattern':pattern}})
    fmt_range('B2:B501','NUMBER','0');fmt_range('C2:G501','NUMBER','0.00');fmt_range('K2:K501','NUMBER','0')
except Exception as e:print('Sheet format warning:',e)
for ws in (ws_stocks,ws_hunter):
    try:ws.freeze(rows=1)
    except Exception:pass
status=f'NIFTY500 | Data {latest_date:%d-%b-%Y} | Universe {len(universe)} | MODEL BUY {len(buy)} | PRE {int((hunter.ACTION=="PRE-BREAKOUT BUY").sum())} | BREAKOUT {int((hunter.ACTION=="BREAKOUT BUY").sum())} | SWING {int((hunter.ACTION=="SWING BUY").sum())} | WATCH gate {MIN_SCORE} | BUY gate {STRAT.buy_score} | BT {stats.get("trades",0)} | Win {stats.get("win_rate_pct",0)}% | PF {stats.get("profit_factor",0)} | Gate {gate_reason} | D1 sessions {hist.DATE.nunique()}'
_astats={a.get('ACTION'):a for a in (stats.get('action_stats') or [])}
_abits=' | '.join(f"{_a} BT{_astats[_a].get('trades',0)} Win{_astats[_a].get('win_rate_pct',0)}% PF{_astats[_a].get('profit_factor',0)}" for _a in ('PRE-BREAKOUT BUY','BREAKOUT BUY','SWING BUY') if _a in _astats)
if _abits:status=status+' || '+_abits
ws_stocks.update(values=[['STATUS']],range_name='T1');ws_stocks.update(values=[[status]],range_name='T2');print(status)
if not buy.empty:
    cols=[c for c in ['SYMBOL','ACTION','CATEGORY','HUNTER_SCORE','CMP','ENTRY_PRICE','ENTRY_ZONE','BREAKOUT_TRIGGER','STOP_LOSS','TARGET_1','TARGET_2','TARGET_3'] if c in buy.columns];print(buy[cols].head(30).to_string(index=False))

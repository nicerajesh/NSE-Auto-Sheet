from __future__ import annotations
import os, sys, subprocess, tempfile, time
from datetime import datetime, timedelta
from io import StringIO, BytesIO
from pathlib import Path
import pandas as pd
import requests
from d1_database import setup, query, batch
ROOT=Path(__file__).resolve().parent; OUT=ROOT/'output'; OUT.mkdir(exist_ok=True)
HISTORY_DAYS=int(os.getenv('HISTORY_DAYS','480')); MIN_TURNOVER_LACS=float(os.getenv('MIN_TURNOVER_LACS','1'))
def session():
 s=requests.Session(); s.headers.update({'User-Agent':'Mozilla/5.0','Accept-Language':'en-US,en;q=0.9','Referer':'https://www.nseindia.com/','Accept':'application/json,text/plain,*/*'}); 
 try:s.get('https://www.nseindia.com',timeout=20)
 except Exception:pass
 return s
def universe(s):
 for url in ('https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv','https://www.niftyindices.com/IndexConstituent/ind_nifty500list.xlsx'):
  try:
   r=s.get(url,headers={'User-Agent':s.headers['User-Agent'],'Referer':'https://www.niftyindices.com/'},timeout=30)
   if not r.ok or len(r.content)<1000:continue
   df=pd.read_csv(StringIO(r.content.decode('utf-8-sig',errors='replace'))) if url.endswith('.csv') else pd.read_excel(BytesIO(r.content),engine='openpyxl'); cols={str(c).strip().upper().replace(' ','_'):c for c in df.columns}; col=cols.get('SYMBOL') or cols.get('SYMBOLS') or cols.get('SECURITY')
   if col:
    syms=df[col].astype(str).str.strip().str.upper(); syms=[x for x in syms if len(x)>0 and not any(k in x for k in ('ETF','BEES','GOLD','SILVER','LIQUID'))]
    if len(syms)>=450:return set(syms)
  except Exception as e:print('NIFTY500 source warning:',e)
 raise RuntimeError('Unable to obtain NIFTY500 universe')
def fetch_bhav(s,d):
 try:
  r=s.get(f'https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d:%d%m%Y}.csv',timeout=25)
  if r.status_code!=200 or len(r.content)<500:return None
  df=pd.read_csv(StringIO(r.text),encoding='utf-8-sig'); df.columns=[str(c).replace('\ufeff','').strip().upper().replace(' ','_') for c in df.columns]
  for a,b in {'OPEN':'OPEN_PRICE','HIGH':'HIGH_PRICE','LOW':'LOW_PRICE','CLOSE':'CLOSE_PRICE','VOLUME':'TTL_TRD_QNTY','DELIVERY_PCT':'DELIV_PER','DELIVERY_PERCENT':'DELIV_PER','DELIVERY_QUANTITY':'DELIV_QTY'}.items():
   if a in df.columns and b not in df.columns:df=df.rename(columns={a:b})
  need=['SYMBOL','SERIES','OPEN_PRICE','HIGH_PRICE','LOW_PRICE','CLOSE_PRICE','TTL_TRD_QNTY','TURNOVER_LACS','DELIV_QTY','DELIV_PER']
  if any(c not in df.columns for c in need):return None
  df=df[df.SERIES.astype(str).str.strip().eq('EQ')].copy();
  for c in need[2:]:df[c]=pd.to_numeric(df[c],errors='coerce')
  df=df.dropna(subset=['SYMBOL','OPEN_PRICE','HIGH_PRICE','LOW_PRICE','CLOSE_PRICE','TTL_TRD_QNTY','TURNOVER_LACS']); df['SYMBOL']=df.SYMBOL.astype(str).str.strip().str.upper(); df=df[df.TURNOVER_LACS>=MIN_TURNOVER_LACS].copy(); df['DATE']=pd.Timestamp(d); return df
 except Exception as e:print('Fetch warning',d,e); return None
def d1_state():
 setup(); data=query('SELECT COUNT(*) AS n, COUNT(DISTINCT trade_date) AS sessions, MAX(trade_date) AS max_date FROM bhavcopy',required=True); row=(data.get('result',[{}])[0].get('results') or [{}])[0]; return int(row.get('n') or 0),int(row.get('sessions') or 0),row.get('max_date')
def load_history():
 n,sess,max_date=d1_state()
 if not max_date:return pd.DataFrame(),None,n,sess
 end=pd.Timestamp(max_date); start=end-pd.Timedelta(days=800); parts=[]; cur=start
 while cur<=end:
  stop=min(cur+pd.Timedelta(days=89),end); data=query('SELECT symbol,trade_date,open,high,low,close,volume,turnover_lacs,delivery_qty,delivery_pct FROM bhavcopy WHERE trade_date>=? AND trade_date<=? ORDER BY trade_date,symbol',[cur.strftime('%Y-%m-%d'),stop.strftime('%Y-%m-%d')],required=True); rows=(data.get('result',[{}])[0].get('results') or [])
  if rows:parts.append(pd.DataFrame(rows))
  cur=stop+pd.Timedelta(days=1)
 if not parts:return pd.DataFrame(),max_date,n,sess
 df=pd.concat(parts,ignore_index=True).drop_duplicates(['symbol','trade_date']); df=df.rename(columns={'symbol':'SYMBOL','trade_date':'DATE','open':'OPEN_PRICE','high':'HIGH_PRICE','low':'LOW_PRICE','close':'CLOSE_PRICE','volume':'TTL_TRD_QNTY','turnover_lacs':'TURNOVER_LACS','delivery_qty':'DELIV_QTY','delivery_pct':'DELIV_PER'}); df['DATE']=pd.to_datetime(df.DATE); return df,max_date,n,sess
def sync(df):
 if df.empty:return
 items=[]
 for r in df.itertuples(index=False):
  def num(v):
   try:return float(v) if pd.notna(v) else None
   except:return None
  items.append({'sql':'INSERT INTO bhavcopy(symbol,trade_date,open,high,low,close,volume,turnover_lacs,delivery_qty,delivery_pct) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(symbol,trade_date) DO UPDATE SET open=excluded.open,high=excluded.high,low=excluded.low,close=excluded.close,volume=excluded.volume,turnover_lacs=excluded.turnover_lacs,delivery_qty=excluded.delivery_qty,delivery_pct=excluded.delivery_pct','params':[str(r.SYMBOL),str(r.DATE)[:10],num(r.OPEN_PRICE),num(r.HIGH_PRICE),num(r.LOW_PRICE),num(r.CLOSE_PRICE),int(num(r.TTL_TRD_QNTY) or 0),num(r.TURNOVER_LACS),int(num(r.DELIV_QTY) or 0),num(r.DELIV_PER)]})
 for i in range(0,len(items),50):batch(items[i:i+50],required=True)
 print(f'D1 market sync: upserted {len(df)} rows')
def make_runner():
 src=(ROOT/'update_sheet.py').read_text(encoding='utf-8'); start='s=sess();universe=fetch_nifty500_symbols(s);frames=[];d=datetime.now();attempts=0'; end="if not frames:raise RuntimeError('No NIFTY 500 NSE bhavcopy data found')"; a=src.find(start); b=src.find(end,a)
 if a<0 or b<0:raise RuntimeError('Legacy history loader not found')
 b+=len(end); src=src[:a]+"frames=[pd.read_csv(OUT/'persistent_history.csv',parse_dates=['DATE'])]; print(f'PERSISTENT D1 INPUT: {len(frames[0])} rows')"+src[b:]
 # Remove every aggregate object from the Hunter sheet. It must be a flat stock table only.
 src=src.replace('hrows += summary_rows','summary_rows=[]')
 cal="if not cal.empty:\n    hrows += [[''],['SCORE/HORIZON CALIBRATION'],cal.columns.tolist()]+[[scalarize(x) for x in row] for row in cal.astype(object).where(pd.notna(cal),'').itertuples(index=False,name=None)]"
 src=src.replace(cal,'# Calibration is kept in CSV/Backtest Audit, never in Early Hunter.')
 return src
def run():
 src=make_runner()
 with tempfile.NamedTemporaryFile('w',suffix='.py',delete=False,dir=ROOT) as f:f.write(src); p=f.name
 try:return subprocess.run([sys.executable,p],env=os.environ.copy()).returncode
 finally:
  try:Path(p).unlink()
  except:pass
def main():
 s=session(); uni=universe(s); hist,last,n,sessions=load_history(); bootstrap=(n==0 or sessions<300)
 if bootstrap:
  print(f'PERSISTENT D1: BOOTSTRAP rows={n} sessions={sessions}'); frames=[]; d=datetime.now(); attempts=0
  while len(frames)<HISTORY_DAYS and attempts<HISTORY_DAYS+120:
   if d.weekday()<5:
    x=fetch_bhav(s,d)
    if x is not None:
     x=x[x.SYMBOL.isin(uni)].copy()
     if not x.empty:frames.append(x); print(f'Bootstrap load {d:%Y-%m-%d}: {len(x)} rows')
   d-=timedelta(days=1); attempts+=1
  if not frames:raise RuntimeError('Bootstrap NSE history unavailable')
  hist=pd.concat(frames,ignore_index=True)
 else:
  hist=hist[hist.SYMBOL.isin(uni)].copy(); latest=pd.to_datetime(hist.DATE).max(); frames=[]; d=latest.to_pydatetime()+timedelta(days=1); today=datetime.now()
  while d.date()<=today.date():
   if d.weekday()<5:
    x=fetch_bhav(s,d)
    if x is not None:
     x=x[x.SYMBOL.isin(uni)].copy()
     if not x.empty:frames.append(x); print(f'Incremental NSE load {d:%Y-%m-%d}: {len(x)} rows')
   d+=timedelta(days=1)
  if frames: new=pd.concat(frames,ignore_index=True); sync(new); hist=pd.concat([hist,new],ignore_index=True)
  else:print('PERSISTENT D1: no new NSE session to add')
 hist=hist.sort_values(['SYMBOL','DATE']).drop_duplicates(['SYMBOL','DATE']).reset_index(drop=True); hist.to_csv(OUT/'persistent_history.csv',index=False)
 if bootstrap:sync(hist)
 print(f'PERSISTENT D1 READY: {len(hist)} rows | {hist.DATE.nunique()} sessions | latest={pd.to_datetime(hist.DATE).max():%Y-%m-%d}')
 rc=run()
 if rc:raise SystemExit(rc)
if __name__=='__main__':raise SystemExit(main())

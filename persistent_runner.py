from __future__ import annotations
import os, sys, subprocess, tempfile
from datetime import datetime, timedelta
from io import StringIO, BytesIO
from pathlib import Path
import pandas as pd
import requests
from d1_database import setup, query, batch
from config import NIFTY_SYMBOL

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'output'; OUT.mkdir(exist_ok=True)
HISTORY_DAYS=int(os.getenv('HISTORY_DAYS','480'))
MIN_TURNOVER_LACS=float(os.getenv('MIN_TURNOVER_LACS','1'))

def session():
    s=requests.Session(); s.headers.update({'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36','Accept-Language':'en-US,en;q=0.9','Referer':'https://www.nseindia.com/','Accept':'application/json,text/plain,*/*'})
    try:s.get('https://www.nseindia.com',timeout=20)
    except Exception:pass
    return s

def universe(s):
    for url in ('https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv','https://www.niftyindices.com/IndexConstituent/ind_nifty500list.xlsx'):
        try:
            r=s.get(url,headers={'User-Agent':s.headers['User-Agent'],'Referer':'https://www.niftyindices.com/'},timeout=30)
            if not r.ok or len(r.content)<1000: continue
            df=pd.read_csv(StringIO(r.content.decode('utf-8-sig',errors='replace'))) if url.endswith('.csv') else pd.read_excel(BytesIO(r.content),engine='openpyxl')
            cols={str(c).strip().upper().replace(' ','_'):c for c in df.columns}; col=cols.get('SYMBOL') or cols.get('SYMBOLS') or cols.get('SECURITY')
            if col:
                syms=df[col].astype(str).str.strip().str.upper(); syms=[x for x in syms if x and not any(k in x for k in ('ETF','BEES','GOLD','SILVER','LIQUID'))]
                if len(syms)>=450:return set(syms)
        except Exception as e: print('NIFTY500 source warning:',e)
    raise RuntimeError('Unable to obtain NIFTY500 universe')

def fetch_bhav(s,d):
    try:
        r=s.get(f'https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d:%d%m%Y}.csv',timeout=25)
        if r.status_code!=200 or len(r.content)<500:return None
        df=pd.read_csv(StringIO(r.text),encoding='utf-8-sig'); df.columns=[str(c).replace('\ufeff','').strip().upper().replace(' ','_') for c in df.columns]
        for a,b in {'OPEN':'OPEN_PRICE','HIGH':'HIGH_PRICE','LOW':'LOW_PRICE','CLOSE':'CLOSE_PRICE','VOLUME':'TTL_TRD_QNTY','DELIVERY_PCT':'DELIV_PER','DELIVERY_PERCENT':'DELIV_PER','DELIVERY_QUANTITY':'DELIV_QTY'}.items():
            if a in df.columns and b not in df.columns: df=df.rename(columns={a:b})
        need=['SYMBOL','SERIES','OPEN_PRICE','HIGH_PRICE','LOW_PRICE','CLOSE_PRICE','TTL_TRD_QNTY','TURNOVER_LACS','DELIV_QTY','DELIV_PER']
        if any(c not in df.columns for c in need):return None
        df=df[df.SERIES.astype(str).str.strip().eq('EQ')].copy()
        for c in need[2:]:df[c]=pd.to_numeric(df[c],errors='coerce')
        df=df.dropna(subset=['SYMBOL','OPEN_PRICE','HIGH_PRICE','LOW_PRICE','CLOSE_PRICE','TTL_TRD_QNTY','TURNOVER_LACS']); df['SYMBOL']=df.SYMBOL.astype(str).str.strip().str.upper(); df=df[df.TURNOVER_LACS>=MIN_TURNOVER_LACS].copy(); df['DATE']=pd.Timestamp(d); return df
    except Exception as e: print('Fetch warning',d,e); return None

def fetch_nifty_index(s,d):
    """Best-effort NIFTY 50 index OHLC for one date, shaped like a normal bhavcopy
    row (SYMBOL='NIFTY 50') so it flows through the same D1/history pipeline as any
    stock. This powers the APEX MATRIX scanner's NIFTY-relative market regime and
    relative-strength calculation.

    Primary source: NSE's daily market-summary CSV
    (archives/equities/mkt/MA{DDMMYY}.csv), which contains a small table:
        ,INDEX,PREVIOUS CLOSE,OPEN,HIGH,LOW,CLOSE,GAIN/LOSS
        ,Nifty 50,     25790.25,     25897.35, ...
    This exact structure was confirmed by fetching and inspecting a real file
    (13-Jan-2026) directly — not a guess. A second, unverified URL is kept as a
    fallback only. ANY failure (wrong URL, renamed columns, network hiccup,
    weekend/holiday with no file) is logged and swallowed — callers must treat a
    missing NIFTY row as normal and fall back (e.g. to universe breadth or
    NEUTRAL regime) rather than failing the run.
    """
    mkt_url=f'https://nsearchives.nseindia.com/archives/equities/mkt/MA{d:%d%m%y}.csv'
    try:
        r=s.get(mkt_url,timeout=20)
        if r.status_code==200 and len(r.content)>200:
            lines=r.text.splitlines(); header_idx=None
            for idx,line in enumerate(lines):
                cells=[c.strip().upper() for c in line.split(',')]
                if 'INDEX' in cells and 'CLOSE' in cells and 'OPEN' in cells:header_idx=idx;break
            if header_idx is None:
                print(f'NIFTY index fetch: header row not found in {mkt_url}')
            else:
                header=[c.strip().upper() for c in lines[header_idx].split(',')]
                row=None
                for line in lines[header_idx+1:header_idx+300]:
                    cells=[c.strip() for c in line.split(',')]
                    if len(cells)<len(header):break
                    idx_col=header.index('INDEX')
                    if idx_col<len(cells) and cells[idx_col].upper()=='NIFTY 50':row=dict(zip(header,cells));break
                if row is None:
                    print(f'NIFTY index fetch: "Nifty 50" row not found in {mkt_url}')
                else:
                    def pick(*keys):
                        for k in keys:
                            v=row.get(k)
                            if v not in (None,''):
                                try:return float(v)
                                except Exception:pass
                        return None
                    o,h,l,c=pick('OPEN'),pick('HIGH'),pick('LOW'),pick('CLOSE')
                    if any(v is None for v in (o,h,l,c)):
                        print(f'NIFTY index fetch: missing OHLC in row {row}')
                    else:
                        return pd.DataFrame([{'SYMBOL':NIFTY_SYMBOL,'DATE':pd.Timestamp(d),'OPEN_PRICE':o,'HIGH_PRICE':h,'LOW_PRICE':l,'CLOSE_PRICE':c,'TTL_TRD_QNTY':0.0,'TURNOVER_LACS':0.0,'DELIV_QTY':0.0,'DELIV_PER':0.0}])
        else:
            print(f'NIFTY index fetch: {mkt_url} status={r.status_code} len={len(r.content)}')
    except Exception as e:
        print('NIFTY index fetch warning (primary)',d,e)
    # Fallback: unverified alternate endpoint, tried only if the primary source failed.
    fallback_url=f'https://nsearchives.nseindia.com/content/indices/ind_close_all_{d:%d%m%Y}.csv'
    try:
        r=s.get(fallback_url,timeout=20)
        if r.status_code!=200 or len(r.content)<200:
            print(f'NIFTY index fetch: fallback {fallback_url} status={r.status_code}');return None
        df=pd.read_csv(StringIO(r.text),encoding='utf-8-sig'); df.columns=[str(c).replace('\ufeff','').strip().upper().replace(' ','_') for c in df.columns]
        name_col=next((c for c in df.columns if 'INDEX' in c and 'NAME' in c),None)
        if not name_col:
            print(f'NIFTY index fetch: fallback {fallback_url} has no index-name column, cols={list(df.columns)}');return None
        row=df[df[name_col].astype(str).str.strip().str.upper().eq('NIFTY 50')]
        if row.empty:
            print(f'NIFTY index fetch: fallback {fallback_url} has no Nifty 50 row');return None
        row=row.iloc[0]
        def pick2(*keys):
            for k in keys:
                if k in row.index and pd.notna(row[k]):return row[k]
            return None
        o,h,l,c=pick2('OPEN_INDEX_VALUE','OPEN'),pick2('HIGH_INDEX_VALUE','HIGH'),pick2('LOW_INDEX_VALUE','LOW'),pick2('CLOSING_INDEX_VALUE','CLOSE','CLOSE_INDEX_VALUE')
        if any(v is None for v in (o,h,l,c)):
            print(f'NIFTY index fetch: fallback missing OHLC values');return None
        return pd.DataFrame([{'SYMBOL':NIFTY_SYMBOL,'DATE':pd.Timestamp(d),'OPEN_PRICE':float(o),'HIGH_PRICE':float(h),'LOW_PRICE':float(l),'CLOSE_PRICE':float(c),'TTL_TRD_QNTY':0.0,'TURNOVER_LACS':0.0,'DELIV_QTY':0.0,'DELIV_PER':0.0}])
    except Exception as e:
        print('NIFTY index fetch warning (fallback)',d,e)
    return None


def d1_state():
    setup(); data=query('SELECT COUNT(*) AS n, COUNT(DISTINCT trade_date) AS sessions, MAX(trade_date) AS max_date FROM bhavcopy',required=True); row=(data.get('result',[{}])[0].get('results') or [{}])[0]; return int(row.get('n') or 0),int(row.get('sessions') or 0),row.get('max_date')

def load_history():
    n,sess,max_date=d1_state()
    if not max_date:return pd.DataFrame(),None,n,sess
    end=pd.Timestamp(max_date); start=end-pd.Timedelta(days=max(800,HISTORY_DAYS+60)); parts=[]; cur=start
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
    src=(ROOT/'update_sheet.py').read_text(encoding='utf-8')
    start='s=sess();universe=fetch_nifty500_symbols(s);hist=load_d1_history();frames=[]'
    end="if hist.empty:raise RuntimeError('No NIFTY 500 history available in D1 or NSE bhavcopy')"
    a=src.find(start); b=src.find(end,a)
    if a<0 or b<0:raise RuntimeError('Legacy history loader not found in update_sheet.py')
    b+=len(end)
    safe=("import pandas as pd;""_persistent_hist=pd.read_csv('output/persistent_history.csv',parse_dates=['DATE']);""universe=set(_persistent_hist['SYMBOL'].astype(str).str.upper())-{'"+NIFTY_SYMBOL+"'};""hist=_persistent_hist.copy();""frames=[g.copy() for _,g in hist.groupby('DATE',sort=True)];""print(f'PERSISTENT D1 INPUT: {len(hist)} rows | {len(frames)} sessions');""del _persistent_hist")
    src=src[:a]+safe+src[b:]
    src=src.replace("ws_hunter.update(values=hrows,range_name='A1',value_input_option='USER_ENTERED')","print('SAFE SHEET PATH: skipping legacy Early Hunter write; repair_sheet_output.py will publish flat rows')")
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
                    ni=fetch_nifty_index(s,d)
                    if ni is not None:x=pd.concat([x,ni],ignore_index=True)
                    if not x.empty:frames.append(x); print(f'Bootstrap load {d:%Y-%m-%d}: {len(x)} rows')
            d-=timedelta(days=1); attempts+=1
        if not frames:raise RuntimeError('Bootstrap NSE history unavailable')
        hist=pd.concat(frames,ignore_index=True)
    else:
        hist=hist[hist.SYMBOL.isin(uni)|hist.SYMBOL.eq(NIFTY_SYMBOL)].copy(); latest=pd.to_datetime(hist.DATE).max(); frames=[]; d=latest.to_pydatetime()+timedelta(days=1); today=datetime.now()
        while d.date()<=today.date():
            if d.weekday()<5:
                x=fetch_bhav(s,d)
                if x is not None:
                    x=x[x.SYMBOL.isin(uni)].copy()
                    ni=fetch_nifty_index(s,d)
                    if ni is not None:x=pd.concat([x,ni],ignore_index=True)
                    if not x.empty:frames.append(x); print(f'Incremental NSE load {d:%Y-%m-%d}: {len(x)} rows')
            d+=timedelta(days=1)
        if frames:
            new=pd.concat(frames,ignore_index=True); sync(new); hist=pd.concat([hist,new],ignore_index=True)
        else:print('PERSISTENT D1: no new NSE session to add')
    hist=hist.sort_values(['SYMBOL','DATE']).drop_duplicates(['SYMBOL','DATE']).reset_index(drop=True); hist.to_csv(OUT/'persistent_history.csv',index=False)
    if bootstrap:sync(hist)
    print(f'PERSISTENT D1 READY: {len(hist)} rows | {hist.DATE.nunique()} sessions | latest={pd.to_datetime(hist.DATE).max():%Y-%m-%d}')
    rc=run()
    if rc:raise SystemExit(rc)

if __name__=='__main__':raise SystemExit(main())

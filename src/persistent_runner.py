from __future__ import annotations
import os, sys, subprocess, tempfile, re
from datetime import datetime, timedelta
from io import StringIO, BytesIO
from pathlib import Path
import pandas as pd
import requests
from d1_database import setup, query, batch
from config import NIFTY_SYMBOL

# Repository root is one level above src/. Keep generated CSVs in root/output so
# GitHub Actions and the dynamically generated runner use the same path.
ROOT=Path(__file__).resolve().parents[1]
SRC=Path(__file__).resolve().parent
OUT=Path(os.getenv('NSE_OUTPUT_DIR', str(ROOT/'output'))).resolve(); OUT.mkdir(parents=True, exist_ok=True)
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
    """Best-effort NIFTY 50 index OHLC for one date, shaped like a normal bhavcopy row."""
    mkt_url=f'https://nsearchives.nseindia.com/archives/equities/mkt/MA{d:%d%m%y}.csv'
    try:
        r=s.get(mkt_url,timeout=20)
        if r.status_code==200 and len(r.content)>200:
            lines=r.text.splitlines(); header_idx=None
            for idx,line in enumerate(lines):
                cells=[c.strip().upper() for c in line.split(',')]
                if 'INDEX' in cells and 'CLOSE' in cells and 'OPEN' in cells:header_idx=idx;break
            if header_idx is not None:
                header=[c.strip().upper() for c in lines[header_idx].split(',')]; row=None; idx_col=header.index('INDEX')
                for line in lines[header_idx+1:header_idx+300]:
                    cells=[c.strip() for c in line.split(',')]
                    if len(cells)<len(header):break
                    if idx_col<len(cells) and cells[idx_col].upper()=='NIFTY 50':row=dict(zip(header,cells));break
                if row is not None:
                    def pick(*keys):
                        for k in keys:
                            v=row.get(k)
                            if v not in (None,''):
                                try:return float(v)
                                except Exception:pass
                        return None
                    o,h,l,c=pick('OPEN'),pick('HIGH'),pick('LOW'),pick('CLOSE')
                    if all(v is not None for v in (o,h,l,c)):
                        return pd.DataFrame([{'SYMBOL':NIFTY_SYMBOL,'DATE':pd.Timestamp(d),'OPEN_PRICE':o,'HIGH_PRICE':h,'LOW_PRICE':l,'CLOSE_PRICE':c,'TTL_TRD_QNTY':0.0,'TURNOVER_LACS':0.0,'DELIV_QTY':0.0,'DELIV_PER':0.0}])
    except Exception as e: print('NIFTY index fetch warning (primary)',d,e)
    fallback_url=f'https://nsearchives.nseindia.com/content/indices/ind_close_all_{d:%d%m%Y}.csv'
    try:
        r=s.get(fallback_url,timeout=20)
        if r.status_code!=200 or len(r.content)<200:return None
        df=pd.read_csv(StringIO(r.text),encoding='utf-8-sig'); df.columns=[str(c).replace('\ufeff','').strip().upper().replace(' ','_') for c in df.columns]
        name_col=next((c for c in df.columns if 'INDEX' in c and 'NAME' in c),None)
        if not name_col:return None
        row=df[df[name_col].astype(str).str.strip().str.upper().eq('NIFTY 50')]
        if row.empty:return None
        row=row.iloc[0]
        def pick2(*keys):
            for k in keys:
                if k in row.index and pd.notna(row[k]):return row[k]
            return None
        o,h,l,c=pick2('OPEN_INDEX_VALUE','OPEN'),pick2('HIGH_INDEX_VALUE','HIGH'),pick2('LOW_INDEX_VALUE','LOW'),pick2('CLOSING_INDEX_VALUE','CLOSE','CLOSE_INDEX_VALUE')
        if any(v is None for v in (o,h,l,c)):return None
        return pd.DataFrame([{'SYMBOL':NIFTY_SYMBOL,'DATE':pd.Timestamp(d),'OPEN_PRICE':float(o),'HIGH_PRICE':float(h),'LOW_PRICE':float(l),'CLOSE_PRICE':float(c),'TTL_TRD_QNTY':0.0,'TURNOVER_LACS':0.0,'DELIV_QTY':0.0,'DELIV_PER':0.0}])
    except Exception as e: print('NIFTY index fetch warning (fallback)',d,e)
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

def _find_update_sheet():
    # Compatibility resolver: the engine can be launched from repo root, src/,
    # a GitHub Actions working directory, or another cwd. Prefer src/ but accept
    # a root copy for older layouts.
    candidates = [SRC / 'update_sheet.py', ROOT / 'update_sheet.py', Path.cwd() / 'src' / 'update_sheet.py', Path.cwd() / 'update_sheet.py']
    seen=set()
    for candidate in candidates:
        candidate=candidate.resolve()
        if candidate in seen: continue
        seen.add(candidate)
        if candidate.is_file(): return candidate
    raise FileNotFoundError('update_sheet.py not found. Checked: ' + ', '.join(str(x.resolve()) for x in candidates))

def make_runner():
    update_sheet_path=_find_update_sheet()
    print(f'PERSISTENT RUNNER: using update_sheet.py = {update_sheet_path}')
    src=update_sheet_path.read_text(encoding='utf-8')
    m=re.search(r"s=sess\(\);universe(?:\s*,\s*\w+)?\s*=\s*fetch_nifty500_symbols\(s\);hist=load_d1_history\(\);frames=\[\]",src)
    if not m:raise RuntimeError('Legacy history loader not found in update_sheet.py')
    a=m.start(); end="if hist.empty:raise RuntimeError('No NIFTY 500 history available in D1 or NSE bhavcopy')"; b=src.find(end,a)
    if b<0:raise RuntimeError('Legacy history loader end-marker not found in update_sheet.py')
    b+=len(end)
    persistent_path=str((OUT/'persistent_history.csv').resolve()).replace('\\','/')
    safe=("import pandas as pd;"f"_persistent_hist=pd.read_csv(r'{persistent_path}',parse_dates=['DATE']);""universe=set(_persistent_hist['SYMBOL'].astype(str).str.upper())-{'"+NIFTY_SYMBOL+"'};""sector_map={};""hist=_persistent_hist.copy();""frames=[g.copy() for _,g in hist.groupby('DATE',sort=True)];""print(f'PERSISTENT D1 INPUT: {len(hist)} rows | {len(frames)} sessions');""del _persistent_hist")
    src=src[:a]+safe+src[b:]
    # IMPORTANT: do not replace the normal CSV writes. The scanner CSVs, including
    # early_hunter.csv, must be created before finalization/validation.
    src=src.replace("ws_hunter.update(values=hrows,range_name='A1',value_input_option='USER_ENTERED')","print('SAFE SHEET PATH: skipping legacy Early Hunter write; CSV outputs remain canonical')")
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
                    x=x[x.SYMBOL.isin(uni)].copy(); ni=fetch_nifty_index(s,d)
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
                    x=x[x.SYMBOL.isin(uni)].copy(); ni=fetch_nifty_index(s,d)
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
    if rc:
        print(f'PERSISTENT RUNNER: update_sheet.py subprocess exited with code {rc}')
        return rc
    return 0

if __name__=='__main__':raise SystemExit(main())

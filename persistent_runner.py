from __future__ import annotations
import os, re, sys, subprocess, tempfile, json, time
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
from d1_database import query, setup

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'output'; OUT.mkdir(exist_ok=True)

def status():
    setup()
    data=query('SELECT COUNT(*) AS n, MAX(trade_date) AS max_date FROM bhavcopy',required=True)
    row=(data.get('result',[{}])[0].get('results') or [{}])[0]
    return int(row.get('n') or 0), row.get('max_date')

def d1_history():
    n,max_date=status()
    if n==0:return None,None
    end=pd.Timestamp(max_date); start=end-pd.Timedelta(days=720)
    parts=[]; cur=start
    cols=['symbol','trade_date','open','high','low','close','volume','turnover_lacs','delivery_qty','delivery_pct']
    while cur<=end:
        stop=min(cur+pd.Timedelta(days=89),end)
        sql='SELECT symbol,trade_date,open,high,low,close,volume,turnover_lacs,delivery_qty,delivery_pct FROM bhavcopy WHERE trade_date>=? AND trade_date<=? ORDER BY trade_date,symbol'
        data=query(sql,[cur.strftime('%Y-%m-%d'),stop.strftime('%Y-%m-%d')],required=True)
        rows=(data.get('result',[{}])[0].get('results') or [])
        if rows: parts.append(pd.DataFrame(rows,columns=cols))
        cur=stop+pd.Timedelta(days=1)
    if not parts:return None,max_date
    df=pd.concat(parts,ignore_index=True).drop_duplicates(['symbol','trade_date']).copy()
    df=df.rename(columns={'symbol':'SYMBOL','trade_date':'DATE','open':'OPEN_PRICE','high':'HIGH_PRICE','low':'LOW_PRICE','close':'CLOSE_PRICE','volume':'TTL_TRD_QNTY','turnover_lacs':'TURNOVER_LACS','delivery_qty':'DELIV_QTY','delivery_pct':'DELIV_PER'})
    df['DATE']=pd.to_datetime(df['DATE']); return df,max_date

def patched_source(incremental: bool):
    src=(ROOT/'update_sheet.py').read_text(encoding='utf-8')
    # Save the complete history before the legacy writer can fail. This is used only on bootstrap.
    src=src.replace("latest_date=hist.DATE.max();latest=hist[hist.DATE.eq(latest_date)].copy()", "hist.to_csv(OUT/'history_full.csv',index=False);latest_date=hist.DATE.max();latest=hist[hist.DATE.eq(latest_date)].copy()")
    if not incremental:return src
    marker=re.compile(r"s=sess\(\);universe=fetch_nifty500_symbols\(s\);frames=\[\];d=datetime\.now\(\);attempts=0.*?if not frames:raise RuntimeError\('No NIFTY 500 NSE bhavcopy data found'\)",re.S)
    replacement='''s=sess();universe=fetch_nifty500_symbols(s); frames=[]\n# Persistent D1 is the source of historical market data. Fetch only sessions missing after D1.\n_d1hist=pd.read_csv(OUT/'d1_history.csv',parse_dates=['DATE'])\nframes=[_d1hist.copy()] if not _d1hist.empty else []\n_d1max=pd.to_datetime(_d1hist.DATE).max() if frames else pd.Timestamp(datetime.now().date())-timedelta(days=1)\nd=_d1max.to_pydatetime()+timedelta(days=1); end=datetime.now()\nwhile d.date()<=end.date():\n    if d.weekday()<5:\n        x=fetch_bhav(s,d)\n        if x is not None and not x.empty:\n            x=x[x.SYMBOL.isin(universe)].copy()\n            if not x.empty: frames.append(x); print(f'Incremental load {d:%Y-%m-%d}: {len(x)} NIFTY500 EQ rows')\n    d+=timedelta(days=1)\nif not frames:raise RuntimeError('No NIFTY 500 NSE bhavcopy data found')'''
    new, count=marker.subn(replacement,src,count=1)
    if count!=1:raise RuntimeError('Could not locate NSE history loader block for incremental patch')
    return new

def run_source(src):
    with tempfile.NamedTemporaryFile('w',suffix='.py',delete=False,dir=ROOT) as f:
        f.write(src); path=f.name
    try:return subprocess.run([sys.executable,path],env=os.environ.copy()).returncode
    finally:
        try:Path(path).unlink()
        except OSError:pass

def main():
    n,max_date=status()
    # Bootstrap once if the database contains only the single-day data left by the old reset workflow.
    bootstrap=n < 100000
    if bootstrap:
        print(f'PERSISTENT D1: bootstrap required (currently {n} bhavcopy rows, latest={max_date})')
        rc=run_source(patched_source(False))
        # Even if the legacy Sheets writer fails, history_full.csv must be backfilled before recovery.
        if (OUT/'history_full.csv').exists():
            print('PERSISTENT D1: backfilling complete historical market set')
            brc=subprocess.run([sys.executable,'d1_backfill.py'],env=os.environ.copy()).returncode
            if brc!=0: return brc
        if rc!=0:
            print('PERSISTENT D1: bootstrap scanner exited',rc,'; safe writer may recover later')
            return 0
        return 0
    df,newest=d1_history();
    if df is None or df.empty:raise RuntimeError('Persistent D1 history could not be loaded')
    df.to_csv(OUT/'d1_history.csv',index=False)
    print(f'PERSISTENT D1: loaded {len(df)} historical rows through {newest}; fetching only missing sessions')
    rc=run_source(patched_source(True))
    return rc

if __name__=='__main__': raise SystemExit(main())

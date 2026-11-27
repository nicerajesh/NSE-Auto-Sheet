from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta
from io import BytesIO,StringIO
from pathlib import Path
import urllib.parse
import pandas as pd
import requests
from .config import CFG
UA={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36","Referer":"https://www.nseindia.com/"}
def universe()->list[str]:
 r=requests.get("https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",headers=UA,timeout=30); r.raise_for_status(); d=pd.read_csv(BytesIO(r.content)); col=next(c for c in d.columns if c.strip().upper() in ("SYMBOL","SYMBOLS")); return sorted(set(d[col].astype(str).str.strip().str.upper()))
def _history_one(sym:str):
 try:
  r=requests.get(CFG.history_url+urllib.parse.quote(sym.lower(),safe="")+".csv",timeout=35)
  if not r.ok or len(r.content)<1000:return None
  d=pd.read_csv(BytesIO(r.content)); d["Date"]=pd.to_datetime(d.Date,errors="coerce")
  if "Series" in d:d=d[d.Series.astype(str).str.strip().eq("EQ")]
  d=d[d.Date>=CFG.history_start]; return pd.DataFrame({"SYMBOL":sym,"DATE":d.Date,"OPEN":d.Open,"HIGH":d.High,"LOW":d.Low,"CLOSE":d.Close,"VOLUME":d.Volume}).dropna()
 except Exception:return None
def load_history(symbols:list[str],cache:str="state_v2/history.csv.gz")->pd.DataFrame:
 p=Path(cache); p.parent.mkdir(parents=True,exist_ok=True)
 if p.exists():
  try:hist=pd.read_csv(p,parse_dates=["DATE"])
  except Exception:hist=pd.DataFrame()
 else:
  # Reuse the already-populated production history cache before any network
  # bootstrap. GitHub Actions restores this cache from the existing scanner.
  legacy=Path("state/history.csv.gz")
  try:
   hist=pd.read_csv(legacy,parse_dates=["DATE"]) if legacy.exists() else pd.DataFrame()
   required={"SYMBOL","DATE","OPEN","HIGH","LOW","CLOSE","VOLUME"}
   if not required.issubset(hist.columns):hist=pd.DataFrame()
  except Exception:hist=pd.DataFrame()
 have=set(hist.SYMBOL.unique()) if not hist.empty else set(); missing=[s for s in symbols if s not in have]
 if missing:
  with ThreadPoolExecutor(max_workers=12) as ex:parts=[x for x in ex.map(_history_one,missing) if x is not None and not x.empty]
  if parts:hist=pd.concat([hist,*parts],ignore_index=True)
 if hist.empty:raise RuntimeError("Historical EOD data download failed")
 last=pd.to_datetime(hist.DATE).max(); sess=requests.Session(); sess.headers.update(UA)
 try:sess.get("https://www.nseindia.com",timeout=15)
 except requests.RequestException:pass
 add=[]; day=last.to_pydatetime()+timedelta(days=1)
 while day.date()<=datetime.now().date():
  if day.weekday()<5:
   try:
    r=sess.get(f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{day:%d%m%Y}.csv",timeout=20)
    if r.ok and len(r.content)>500:
     d=pd.read_csv(StringIO(r.text)); d.columns=[str(c).strip().upper().replace(" ","_") for c in d.columns]; d=d[d.SERIES.astype(str).str.strip().eq("EQ")]
     x=pd.DataFrame({"SYMBOL":d.SYMBOL.astype(str).str.upper().str.strip(),"DATE":pd.Timestamp(day),"OPEN":d.OPEN_PRICE,"HIGH":d.HIGH_PRICE,"LOW":d.LOW_PRICE,"CLOSE":d.CLOSE_PRICE,"VOLUME":d.TTL_TRD_QNTY}); add.append(x[x.SYMBOL.isin(symbols)].dropna())
   except Exception:pass
  day+=timedelta(days=1)
 if add:hist=pd.concat([hist,*add],ignore_index=True)
 hist=hist[hist.SYMBOL.isin(symbols)].copy(); hist.DATE=pd.to_datetime(hist.DATE); hist=hist.drop_duplicates(["SYMBOL","DATE"],keep="last").sort_values(["SYMBOL","DATE"]); hist.to_csv(p,index=False,compression="gzip"); return hist

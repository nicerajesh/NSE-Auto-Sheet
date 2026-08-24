from __future__ import annotations
import os,json,time
from datetime import datetime,timedelta
from io import StringIO
from pathlib import Path
import gspread, numpy as np, pandas as pd, requests
from oauth2client.service_account import ServiceAccountCredentials
from indicator import add_indicators_all
from strategy import scan_all
from backtest import run_backtest
from trade_manager import update_ledger
from quality_gate import evaluate

SPREADSHEET_ID=os.getenv("SPREADSHEET_ID","1U9j5fMZAWPUSwoP_U-GKdacVke9nUjspqPR3wGsWAUM")
VOLUME_SHEET="Top 250 Stocks"; TURNOVER_SHEET="Top 250 Turnover"; HUNTER_SHEET="Early Hunter"
HISTORY_DAYS=int(os.getenv("HISTORY_DAYS","300")); MIN_TURNOVER_LACS=float(os.getenv("MIN_TURNOVER_LACS","2")); MIN_SCORE=int(os.getenv("MIN_SCORE","68"))
OUT=Path("output"); OUT.mkdir(exist_ok=True)
try: import boto3
except ImportError: boto3=None
R2A=os.getenv("R2_ACCOUNT_ID",""); R2K=os.getenv("R2_ACCESS_KEY_ID",""); R2S=os.getenv("R2_SECRET_ACCESS_KEY",""); R2B=os.getenv("R2_BUCKET",""); R2P=os.getenv("R2_PREFIX","nse-auto-sheet").strip("/")

def r2():
    if not (boto3 and R2A and R2K and R2S and R2B): return None
    return boto3.client("s3",endpoint_url=f"https://{R2A}.r2.cloudflarestorage.com",aws_access_key_id=R2K,aws_secret_access_key=R2S,region_name="auto")
def r2up(path,key):
    c=r2()
    if c:
        try: c.upload_file(str(path),R2B,f"{R2P}/{key}" if R2P else key,ExtraArgs={"ContentType":"text/csv"})
        except Exception as e: print("R2:",e)

creds_json=os.getenv("GCP_CREDENTIALS")
if not creds_json: raise RuntimeError("GCP_CREDENTIALS secret missing")
creds=ServiceAccountCredentials.from_json_keyfile_dict(json.loads(creds_json),["https://spreadsheets.google.com/feeds","https://www.googleapis.com/auth/drive"])
book=gspread.authorize(creds).open_by_key(SPREADSHEET_ID)
wv=book.worksheet(VOLUME_SHEET); wt=book.worksheet(TURNOVER_SHEET)
try: wh=book.worksheet(HUNTER_SHEET)
except gspread.WorksheetNotFound: wh=book.add_worksheet(title=HUNTER_SHEET,rows=3000,cols=100)

def sess():
    s=requests.Session(); s.headers.update({"User-Agent":"Mozilla/5.0 Chrome/151 Safari/537.36","Accept-Language":"en-US,en;q=0.9","Referer":"https://www.nseindia.com/"})
    try:s.get("https://www.nseindia.com",timeout=15)
    except:pass
    return s

def fetch(s,d):
    ds=d.strftime("%d%m%Y"); url=f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{ds}.csv"
    try:
        r=s.get(url,timeout=25)
        if r.status_code!=200 or len(r.content)<500:return None
        df=pd.read_csv(StringIO(r.text)); df.columns=[str(c).strip() for c in df.columns]
        need=["SYMBOL","SERIES","OPEN_PRICE","HIGH_PRICE","LOW_PRICE","CLOSE_PRICE","TTL_TRD_QNTY","TURNOVER_LACS","DELIV_QTY","DELIV_PER"]
        if not all(c in df.columns for c in need):return None
        df=df[df.SERIES.astype(str).str.strip()=="EQ"].copy()
        df=df[~df.SYMBOL.astype(str).str.contains("BEES|ETF|GOLD|LIQUID|SILVER|CASE",case=False,regex=True,na=False)]
        for c in need[2:]:df[c]=pd.to_numeric(df[c],errors="coerce")
        df=df.dropna(subset=["CLOSE_PRICE","HIGH_PRICE","LOW_PRICE","TTL_TRD_QNTY","TURNOVER_LACS"])
        df=df[df.TURNOVER_LACS>MIN_TURNOVER_LACS]; df["DATE"]=pd.Timestamp(d); return df
    except Exception as e: print("Fetch",d,e); return None

s=sess(); frames=[]; d=datetime.now()
for _ in range(HISTORY_DAYS+60):
    if d.weekday()<5:
        x=fetch(s,d)
        if x is not None and not x.empty:frames.append(x); print(d.strftime("%d-%m-%Y"),len(x))
        if len(frames)>=HISTORY_DAYS:break
        time.sleep(.18)
    d-=timedelta(days=1)
if not frames:raise RuntimeError("No NSE data")
hist=pd.concat(frames,ignore_index=True).sort_values(["SYMBOL","DATE"]).drop_duplicates(["SYMBOL","DATE"]).reset_index(drop=True)
latest_date=hist.DATE.max(); latest_day=hist[hist.DATE==latest_date].copy()
hist=add_indicators_all(hist)
med=hist.groupby("DATE")["RET_20D"].transform("median"); hist["RS_VS_UNIVERSE"]=hist["RET_20D"]-med; hist["RS_RANK"]=hist.groupby("DATE")["RET_20D"].rank(pct=True)*100
hunter=scan_all(hist,MIN_SCORE)
if hunter.empty:hunter=pd.DataFrame()
if not hunter.empty:
    rs=hist[hist.DATE==latest_date][["SYMBOL","RS_VS_UNIVERSE","RS_RANK"]]; hunter=hunter.merge(rs,on="SYMBOL",how="left")

bt=run_backtest(hist,MIN_SCORE,30)
if len(bt)==3: trades,stats,cal=bt
else: trades,stats=bt; cal=pd.DataFrame()
trades.to_csv(OUT/"backtest_trades.csv",index=False); pd.DataFrame([stats]).to_csv(OUT/"backtest_summary.csv",index=False); cal.to_csv(OUT/"score_calibration.csv",index=False)

ledger_path=OUT/"trade_ledger.csv"; old=pd.DataFrame(); c=r2()
if c:
    try:c.download_file(R2B,f"{R2P}/trade_ledger.csv",str(ledger_path)); old=pd.read_csv(ledger_path)
    except:pass
current={str(r["SYMBOL"]):r.to_dict() for _,r in hunter.iterrows()} if not hunter.empty else {}
ledger=update_ledger(old,current); ledger.to_csv(ledger_path,index=False)
if not hunter.empty:
    pos=ledger[["SYMBOL","STATUS","EXIT_DATE","EXIT_PRICE","EXIT_REASON"]].drop_duplicates("SYMBOL",keep="last") if not ledger.empty else pd.DataFrame()
    if not pos.empty:hunter=hunter.merge(pos,on="SYMBOL",how="left")

gate_ok,gate_reason=evaluate(stats,cal)
if not gate_ok and not hunter.empty:
    hunter["ACTION"]=hunter["ACTION"].replace({"BUY":"WATCH","BUY ON TRIGGER":"WATCH"}); hunter["QUALITY_GATE"]=gate_reason
elif not hunter.empty:hunter["QUALITY_GATE"]="PASS"
buy=hunter[hunter.ACTION.isin(["BUY","BUY ON TRIGGER"])].copy() if not hunter.empty else pd.DataFrame()

latest_day.to_csv(OUT/"latest_market.csv",index=False); hist[hist.DATE==latest_date].to_csv(OUT/"indicators.csv",index=False); hunter.to_csv(OUT/"early_hunter.csv",index=False); buy.to_csv(OUT/"buy_candidates.csv",index=False); ledger.to_csv(OUT/"trade_signals.csv",index=False)
db=OUT/"buy_database.csv"; olddb=pd.DataFrame()
if c:
    try:c.download_file(R2B,f"{R2P}/buy_database.csv",str(db)); olddb=pd.read_csv(db)
    except:pass
combined=pd.concat([olddb,buy],ignore_index=True) if not olddb.empty else buy.copy()
if not combined.empty and "DATE" in combined and "SYMBOL" in combined:
    combined.drop_duplicates(["DATE","SYMBOL"],keep="last").sort_values(["DATE","HUNTER_SCORE"],ascending=[False,False]).to_csv(db,index=False)
for fn in OUT.glob("*.csv"):r2up(fn,fn.name)
tag=latest_date.strftime("%Y-%m-%d")
for fn in ["early_hunter.csv","buy_candidates.csv","indicators.csv","trade_ledger.csv","backtest_summary.csv","score_calibration.csv"]:
    p=OUT/fn
    if p.exists():r2up(p,f"history/{tag}/{fn}")

def ensure(ws,n):
    if ws.col_count<n:ws.add_cols(n-ws.col_count)
ensure(wv,12); ensure(wt,22); ensure(wh,max(100,len(hunter.columns) if not hunter.empty else 20))
vol=latest_day.sort_values("TTL_TRD_QNTY",ascending=False).head(250); turn=latest_day.sort_values("TURNOVER_LACS",ascending=False).head(250)
wv.batch_clear(["A2:C251"]); wv.update("A2",vol[["SYMBOL","TTL_TRD_QNTY","CLOSE_PRICE"]].values.tolist())
wt.batch_clear(["A2:F251"]); wt.update("A2",turn[["SYMBOL","TTL_TRD_QNTY","CLOSE_PRICE","TURNOVER_LACS","DELIV_QTY","DELIV_PER"]].values.tolist())
wh.clear()
if not hunter.empty: rows=[hunter.columns.tolist()]+hunter.astype(object).where(pd.notna(hunter),"").values.tolist()
else: rows=[["NO QUALIFIED EARLY-HUNTER SETUP TODAY"]]
rows += [[""],["BACKTEST SUMMARY"]]+[[k,v] for k,v in stats.items()]+[["QUALITY_GATE",gate_reason]]
if not cal.empty:rows += [[""],["SCORE CALIBRATION"]]+[cal.columns.tolist()]+cal.astype(object).where(pd.notna(cal),"").values.tolist()
wh.update("A1",rows)
try: wh.freeze(rows=1); wh.format("A1:CV1",{"textFormat":{"bold":True},"horizontalAlignment":"CENTER"})
except Exception as e:print("Format",e)
status=f"Data {latest_date:%d-%b-%Y} | BUY {len(buy)} | BT {stats.get('trades',0)} | Win {stats.get('win_rate_pct',0)}% | PF {stats.get('profit_factor',0)} | Gate {gate_reason}"
wv.update("L2",[[status]]); wt.update("V2",[[status]])
print(status)
if not buy.empty:print(buy[["SYMBOL","ACTION","STAGE","HUNTER_SCORE","CMP","BUY_ZONE_LOW","BUY_ZONE_HIGH","ENTRY_TRIGGER","STOP_LOSS","TARGET_1","TARGET_2","TARGET_3"]].head(30).to_string(index=False))

"""Historical research test for 52-week-low heavy-volume reversal candidates.

Uses only data available on the signal date. Reports forward 20/40/60-session
returns and adverse/favourable excursion. Current-universe history has
survivorship bias; results are exploratory, not production BUY signals.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import data as dt

def features_one(g: pd.DataFrame) -> pd.DataFrame:
    d = g.sort_values("DATE").copy().reset_index(drop=True)
    c, h, l, v = (d[x].astype(float) for x in ("CLOSE","HIGH","LOW","VOLUME"))
    d["LOW252"] = l.rolling(252, min_periods=200).min()
    d["DIST_LOW_PCT"] = (c / d["LOW252"] - 1) * 100
    d["VOL20"] = v.rolling(20, min_periods=20).mean()
    d["VOL_X"] = v / d["VOL20"]
    rng = (h-l).replace(0, np.nan)
    d["CLOSE_LOC"] = ((c-l)/rng).fillna(0.5)
    signed = v * np.sign(c.diff()).fillna(0)
    d["OBV"] = signed.cumsum()
    d["OBV_RISE20"] = d["OBV"] > d["OBV"].shift(20)
    tp = (h+l+c)/3
    flow = tp*v
    pos = flow.where(tp.diff()>0,0).rolling(14,min_periods=14).sum()
    neg = flow.where(tp.diff()<0,0).rolling(14,min_periods=14).sum()
    ratio = pos / neg.replace(0,np.nan)
    mfi = 100 - 100/(1+ratio)
    # No negative money flow with positive flow is a valid MFI reading of 100.
    mfi = mfi.mask((neg == 0) & (pos > 0), 100.0)
    d["MFI14"] = mfi
    d["MFI_RISE3"] = d["MFI14"] > d["MFI14"].shift(3)
    d["EMA20"] = c.ewm(span=20,adjust=False,min_periods=20).mean()
    d["EMA50"] = c.ewm(span=50,adjust=False,min_periods=50).mean()
    d["HIGH10_PREV"] = h.shift(1).rolling(10,min_periods=8).max()
    d["BREAK10"] = c > d["HIGH10_PREV"]
    d["RET1"] = c.pct_change()*100
    return d

def build_events(hist: pd.DataFrame) -> pd.DataFrame:
    frames=[]
    for sym,g in hist.groupby("SYMBOL",sort=False):
        if len(g)<252: continue
        d=features_one(g)
        d["SYMBOL"]=sym
        frames.append(d)
    if not frames: return pd.DataFrame()
    f=pd.concat(frames,ignore_index=True)
    # signal definitions: discovery, absorption, and confirmation tiers
    near=f.DIST_LOW_PCT.between(0,10)
    spike=f.VOL_X>=1.5
    heavy=f.VOL_X>=2.0
    absorption=(f.CLOSE_LOC>=0.70)&(f.RET1>0)
    obv=f.OBV_RISE20.fillna(False)
    mfi=f.MFI14.ge(50)&f.MFI_RISE3.fillna(False)
    confirm=(f.CLOSE>f.EMA20)&(f.CLOSE>f.HIGH10_PREV)
    tiers={
      "A_DISCOVERY":near&spike,
      "B_ABSORPTION":near&heavy&absorption,
      "C_OBV_MFI":near&spike&absorption&obv&mfi,
      "D_CONFIRMED":near&spike&absorption&obv&mfi&confirm,
      "E_OBV_ONLY":near&spike&absorption&obv,
      "F_MFI_ONLY":near&spike&absorption&mfi,
    }
    out=[]
    last_signal={}
    symbol_frames={s:g.sort_values("DATE").reset_index(drop=True) for s,g in f.groupby("SYMBOL",sort=False)}
    for tier,mask in tiers.items():
      for sym, group in f.groupby("SYMBOL",sort=False):
        local_mask=mask.loc[group.index].fillna(False).to_numpy()
        ix=np.flatnonzero(local_mask)
        d=symbol_frames[sym]
        for i in ix:
          row=d.iloc[i]
          key=(sym,tier)
          if key in last_signal and (row.DATE-last_signal[key]).days<14: continue
          last_signal[key]=row.DATE
          rec={"SYMBOL":sym,"TIER":tier,"SIGNAL_DATE":row.DATE,
               "SIGNAL_CLOSE":float(row.CLOSE),"VOL_X":float(row.VOL_X),
               "DIST_LOW_PCT":float(row.DIST_LOW_PCT),"CLOSE_LOC":float(row.CLOSE_LOC),
               "MFI14":float(row.MFI14) if pd.notna(row.MFI14) else np.nan}
          future=d.iloc[i+1:i+61]
          for n in (20,40,60):
            fw=future.head(n)
            if len(fw)<n:
              rec[f"FWD{n}_RET_PCT"]=np.nan; rec[f"FWD{n}_MAX_HIGH_PCT"]=np.nan
              rec[f"FWD{n}_MIN_LOW_PCT"]=np.nan
            else:
              rec[f"FWD{n}_RET_PCT"]=(float(fw.iloc[-1].CLOSE)/rec["SIGNAL_CLOSE"]-1)*100
              rec[f"FWD{n}_MAX_HIGH_PCT"]=(float(fw.HIGH.max())/rec["SIGNAL_CLOSE"]-1)*100
              rec[f"FWD{n}_MIN_LOW_PCT"]=(float(fw.LOW.min())/rec["SIGNAL_CLOSE"]-1)*100
          out.append(rec)
    return pd.DataFrame(out)

def summarize(events: pd.DataFrame, period_col: str | None = None) -> pd.DataFrame:
    rows=[]
    group_cols = ["TIER"] if period_col is None else [period_col, "TIER"]
    for keys,g in events.groupby(group_cols):
      if period_col is None:
        period, tier = "ALL", keys
      else:
        period, tier = keys
      for n in (20,40,60):
        x=g[f"FWD{n}_RET_PCT"].dropna()
        if x.empty: continue
        pos=x[x>0].sum(); neg=-x[x<0].sum()
        rows.append({"PERIOD":period,"TIER":tier,"HORIZON":n,"N":len(x),
          "WIN_RATE_PCT":round((x>0).mean()*100,2),
          "AVG_RETURN_PCT":round(x.mean(),2),"MEDIAN_RETURN_PCT":round(x.median(),2),
          "PROFIT_FACTOR":round(pos/neg,3) if neg else np.inf,
          "AVG_MAX_HIGH_PCT":round(g.loc[x.index,f"FWD{n}_MAX_HIGH_PCT"].mean(),2),
          "AVG_MAX_DRAWDOWN_PCT":round(g.loc[x.index,f"FWD{n}_MIN_LOW_PCT"].mean(),2),
          "HIT_20PCT_HIGH_PCT":round((g.loc[x.index,f"FWD{n}_MAX_HIGH_PCT"]>=20).mean()*100,2)})
    return pd.DataFrame(rows).sort_values(["HORIZON","PROFIT_FACTOR"],ascending=[True,False])

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--state",default="state/history.csv.gz")
    ap.add_argument("--out",default="artifacts/52w_volume_backtest")
    a=ap.parse_args()
    p=Path(a.state)
    hist=pd.read_csv(p,parse_dates=["DATE"])
    events=build_events(hist)
    summary=summarize(events) if not events.empty else pd.DataFrame()
    segmented = pd.DataFrame()
    if not events.empty:
        events["PERIOD"] = np.select(
            [events.SIGNAL_DATE.dt.year <= 2022,
             events.SIGNAL_DATE.dt.year.between(2023, 2024),
             events.SIGNAL_DATE.dt.year >= 2025],
            ["TRAIN_2018_2022", "VALIDATION_2023_2024", "HOLDOUT_2025_PLUS"],
            default="OUT_OF_RANGE")
        segmented = summarize(events, "PERIOD")
    out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
    events.to_csv(out/"events.csv",index=False)
    summary.to_csv(out/"summary.csv",index=False)
    segmented.to_csv(out/"period_summary.csv",index=False)
    print("UNIVERSE: current Nifty 500 constituents only; survivorship bias remains.")
    print(f"History: {hist.DATE.min().date()} to {hist.DATE.max().date()} | symbols={hist.SYMBOL.nunique()}")
    print(f"Events: {len(events)}")
    print("POOLED SUMMARY")
    print(summary.to_string(index=False) if not summary.empty else "NO EVENTS")
    print("OUT-OF-SAMPLE PERIOD SUMMARY (train <=2022; validation 2023-24; holdout 2025+)")
    print(segmented.to_string(index=False) if not segmented.empty else "NO PERIOD RESULTS")
if __name__=="__main__": main()

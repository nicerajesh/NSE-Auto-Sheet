"""Causal indicator engine for NSE OHLCV + delivery data."""
from __future__ import annotations
import numpy as np
import pandas as pd


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    g = df.copy(); rename = {}
    for c in g.columns:
        rename[c] = str(c).replace("\ufeff", "").strip().upper().replace(" ", "_")
    g = g.rename(columns=rename)
    aliases = {"SYMBOL_NAME":"SYMBOL","SECURITY_SYMBOL":"SYMBOL","TRADE_DATE":"DATE","TIMESTAMP":"DATE","OPEN":"OPEN_PRICE","HIGH":"HIGH_PRICE","LOW":"LOW_PRICE","CLOSE":"CLOSE_PRICE","VOLUME":"TTL_TRD_QNTY","DELIVERY_PERCENT":"DELIV_PER","DELIVERY_PCT":"DELIV_PER","DELIVERY_QUANTITY":"DELIV_QTY"}
    for old,new in aliases.items():
        if old in g.columns and new not in g.columns: g=g.rename(columns={old:new})
    return g


def _num(s): return pd.to_numeric(s,errors="coerce").astype(float)

def rsi(c,p=14):
    d=c.diff(); up=d.clip(lower=0); dn=-d.clip(upper=0); ag=up.ewm(alpha=1/p,adjust=False,min_periods=p).mean(); al=dn.ewm(alpha=1/p,adjust=False,min_periods=p).mean(); rs=ag/al.replace(0,np.nan); return 100-100/(1+rs)

def atr(g,p=14):
    c=_num(g["CLOSE_PRICE"]); h=_num(g["HIGH_PRICE"]); l=_num(g["LOW_PRICE"]); pc=c.shift(1); tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1); return tr.ewm(alpha=1/p,adjust=False,min_periods=p).mean()

def adx(g,p=14):
    c=_num(g["CLOSE_PRICE"]); h=_num(g["HIGH_PRICE"]); l=_num(g["LOW_PRICE"]); pc=c.shift(1); tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1); up=h.diff(); dn=-l.diff(); plus=np.where((up>dn)&(up>0),up,0.0); minus=np.where((dn>up)&(dn>0),dn,0.0); a=pd.Series(tr,index=g.index).ewm(alpha=1/p,adjust=False,min_periods=p).mean(); pi=100*pd.Series(plus,index=g.index).ewm(alpha=1/p,adjust=False,min_periods=p).mean()/a.replace(0,np.nan); mi=100*pd.Series(minus,index=g.index).ewm(alpha=1/p,adjust=False,min_periods=p).mean()/a.replace(0,np.nan); dx=100*(pi-mi).abs()/(pi+mi).replace(0,np.nan); return dx.ewm(alpha=1/p,adjust=False,min_periods=p).mean(),pi,mi

def add_indicators(df):
    g=normalize_columns(df).sort_values("DATE").copy(); required=["DATE","CLOSE_PRICE","HIGH_PRICE","LOW_PRICE","OPEN_PRICE","TTL_TRD_QNTY","DELIV_PER"]; missing=[c for c in required if c not in g.columns]
    if missing: raise ValueError(f"Missing indicator columns: {missing}; received={list(g.columns)}")
    c=_num(g["CLOSE_PRICE"]); h=_num(g["HIGH_PRICE"]); l=_num(g["LOW_PRICE"]); v=_num(g["TTL_TRD_QNTY"]); d=_num(g["DELIV_PER"])
    for n in [20,50,100,200]: g[f"EMA{n}"]=c.ewm(span=n,adjust=False,min_periods=min(n,30)).mean(); g[f"EMA{n}_SLOPE_5"]=g[f"EMA{n}"].pct_change(5)*100
    g["RSI14"]=rsi(c); e12=c.ewm(span=12,adjust=False).mean(); e26=c.ewm(span=26,adjust=False).mean(); g["MACD"]=e12-e26; g["MACD_SIGNAL"]=g.MACD.ewm(span=9,adjust=False).mean(); g["MACD_HIST"]=g.MACD-g.MACD_SIGNAL; g["MACD_HIST_SLOPE"]=g.MACD_HIST.diff(3)
    g["ATR14"]=atr(g); g["ATR_PCT"]=g.ATR14/c.replace(0,np.nan)*100; g["ATR_PCT_AVG30"]=g.ATR_PCT.rolling(30,min_periods=15).mean(); g["ATR_COMPRESSION"]=g.ATR_PCT<g.ATR_PCT_AVG30*.92
    g["VOL_AVG20"]=v.rolling(20,min_periods=10).mean(); g["VOL_RATIO"]=v/g.VOL_AVG20.replace(0,np.nan); g["DELIV_AVG10"]=d.rolling(10,min_periods=5).mean(); g["DELIV_AVG20"]=d.rolling(20,min_periods=10).mean(); g["DELIV_TREND"]=g.DELIV_AVG10-g.DELIV_AVG20
    for n in [5,10,20,50]: g[f"RET_{n}D"]=c.pct_change(n)*100
    # All price-location levels are causal: today's row only sees completed prior bars.
    g["HIGH_52W"]=h.shift(1).rolling(252,min_periods=40).max(); g["LOW_52W"]=l.shift(1).rolling(252,min_periods=40).min(); g["DIST_52W_HIGH_PCT"]=(c/g.HIGH_52W-1)*100; g["DIST_52W_LOW_PCT"]=(c/g.LOW_52W-1)*100; g["DIST_EMA200_PCT"]=(c/g.EMA200-1)*100
    g["ADX14"],g["PLUS_DI14"],g["MINUS_DI14"]=adx(g); g["DI_SPREAD"]=g.PLUS_DI14-g.MINUS_DI14
    g["PRIOR_HIGH20"]=h.shift(1).rolling(20,min_periods=10).max(); g["PRIOR_LOW20"]=l.shift(1).rolling(20,min_periods=10).min(); g["PRIOR_HIGH55"]=h.shift(1).rolling(55,min_periods=20).max(); g["PRIOR_LOW55"]=l.shift(1).rolling(55,min_periods=20).min(); g["DIST_PRIOR_HIGH_PCT"]=(g.PRIOR_HIGH20/c-1)*100; g["DIST_PRIOR_LOW_PCT"]=(c/g.PRIOR_LOW20-1)*100
    o=_num(g["OPEN_PRICE"]); rng=(h-l).replace(0,np.nan); g["BODY_PCT"]=(c-o).abs()/c*100; g["CLOSE_LOCATION"]=(c-l)/rng; g["UPPER_WICK"]=(h-np.maximum(o,c))/rng; g["LOWER_WICK"]=(np.minimum(o,c)-l)/rng; g["RANGE_ATR"]=rng/g.ATR14.replace(0,np.nan); g["BULL_CANDLE"]=c>o
    return g

def add_indicators_all(hist):
    g=normalize_columns(hist); required=["SYMBOL","DATE","CLOSE_PRICE","HIGH_PRICE","LOW_PRICE","OPEN_PRICE","TTL_TRD_QNTY","DELIV_PER"]; missing=[c for c in required if c not in g.columns]
    if missing: raise ValueError(f"Historical dataset missing columns: {missing}; received={list(g.columns)}")
    g["SYMBOL"]=g["SYMBOL"].astype(str).str.strip().str.upper(); g["DATE"]=pd.to_datetime(g["DATE"],errors="coerce"); g=g.dropna(subset=["SYMBOL","DATE"]).copy(); parts=[]
    for symbol,group in g.groupby("SYMBOL",sort=False):
        if len(group)<2: continue
        result=add_indicators(group.copy()); result["SYMBOL"]=str(symbol).strip().upper(); parts.append(result)
    if not parts: raise ValueError("No valid SYMBOL groups available for indicator calculation")
    out=pd.concat(parts,ignore_index=True); out["SYMBOL"]=out["SYMBOL"].astype(str).str.strip().str.upper()

    # Relative strength vs NIFTY: stock 20D return minus NIFTY 20D return.
    # Calculated only from data available on the same date (no look-ahead).
    nifty = out[out["SYMBOL"].eq(NIFTY_SYMBOL if "NIFTY_SYMBOL" in globals() else "NIFTY 50")][["DATE","RET_20D"]].copy()
    if not nifty.empty:
        nifty = nifty.rename(columns={"RET_20D":"NIFTY_RET_20D"}).drop_duplicates("DATE")
        out = out.merge(nifty, on="DATE", how="left")
        out["RS_VS_UNIVERSE"] = out["RET_20D"] - out["NIFTY_RET_20D"]
    elif "RS_VS_UNIVERSE" not in out.columns:
        out["RS_VS_UNIVERSE"] = np.nan

    # Standard Supertrend (10, 3) for trend confirmation.
    period, multiplier = 10, 3.0
    hl2 = (out["HIGH_PRICE"] + out["LOW_PRICE"]) / 2
    atr10 = out.groupby("SYMBOL", group_keys=False)["ATR14"].transform(
        lambda s: s.rolling(period, min_periods=period).mean()
    )
    basic_upper = hl2 + multiplier * atr10
    basic_lower = hl2 - multiplier * atr10
    out["SUPERTREND"] = np.nan
    out["SUPERTREND_DIRECTION"] = np.nan
    for symbol, idx in out.groupby("SYMBOL", sort=False).groups.items():
        ix = list(idx)
        fu, fl, st, direction = [], [], [], []
        for pos, row_idx in enumerate(ix):
            bu = basic_upper.loc[row_idx]; bl = basic_lower.loc[row_idx]
            close = out.at[row_idx, "CLOSE_PRICE"]
            if pos == 0 or pd.isna(bu) or pd.isna(bl):
                fu.append(bu); fl.append(bl); st.append(np.nan); direction.append(np.nan); continue
            prev_fu, prev_fl, prev_st = fu[-1], fl[-1], st[-1]
            fu_val = bu if pd.isna(prev_fu) or bu < prev_fu or close > prev_fu else prev_fu
            fl_val = bl if pd.isna(prev_fl) or bl > prev_fl or close < prev_fl else prev_fl
            if pd.isna(prev_st):
                st_val = fl_val if close >= fl_val else fu_val
            elif prev_st == prev_fu:
                st_val = fl_val if close > fu_val else fu_val
            else:
                st_val = fl_val if close >= fl_val else fu_val
            fu.append(fu_val); fl.append(fl_val); st.append(st_val)
            direction.append(1 if close >= st_val else -1)
        out.loc[ix, "SUPERTREND"] = st
        out.loc[ix, "SUPERTREND_DIRECTION"] = direction
    return out

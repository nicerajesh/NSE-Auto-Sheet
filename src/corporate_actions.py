"""Conservative heuristic split/bonus detection and back-adjustment."""
from __future__ import annotations
import numpy as np
import pandas as pd

# POST/PRE price ratio -> explicit, non-contradictory label.
# A bonus and a split can share the same price ratio, so the label deliberately
# says SPLIT/BONUS unless an authoritative corporate-action feed is available.
_CLEAN_RATIOS=[
    (1/2,"1:2 SPLIT/BONUS"),(1/3,"1:3 SPLIT/BONUS"),(1/5,"1:5 SPLIT/BONUS"),(1/10,"1:10 SPLIT/BONUS"),
    (2/3,"2:3 SPLIT/BONUS"),(1/4,"1:4 SPLIT/BONUS"),(3/4,"3:4 SPLIT/BONUS"),(4/5,"4:5 SPLIT/BONUS"),
]
_TOL=0.03; _VOL_TOL=0.35; _MIN_JUMP_PCT=15.0

def _match_ratio(price_ratio:float):
    if not np.isfinite(price_ratio) or price_ratio<=0 or price_ratio>=1:return None
    for target,label in _CLEAN_RATIOS:
        if abs(price_ratio-target)<=_TOL:return target,label
    return None

def detect_and_adjust(hist:pd.DataFrame)->tuple[pd.DataFrame,pd.DataFrame]:
    if hist is None or hist.empty:return hist,pd.DataFrame(columns=["SYMBOL","DATE","RATIO","LABEL","PREV_CLOSE","CLOSE","ADJUSTED"])
    out=hist.copy(); price_cols=[c for c in ("OPEN_PRICE","HIGH_PRICE","LOW_PRICE","CLOSE_PRICE") if c in out.columns]
    for c in price_cols:out[c]=pd.to_numeric(out[c],errors="coerce")
    log=[]
    for sym,g in out.groupby("SYMBOL",sort=False):
        g=g.sort_values("DATE"); close=g.CLOSE_PRICE.to_numpy(float); vol=g.TTL_TRD_QNTY.to_numpy(float) if "TTL_TRD_QNTY" in g else np.full(len(g),np.nan); idx=g.index.to_numpy()
        if len(close)<2:continue
        for i in range(1,len(close)):
            if not np.isfinite(close[i]) or not np.isfinite(close[i-1]) or close[i-1]<=0:continue
            pct_jump=(close[i]-close[i-1])/close[i-1]*100
            if pct_jump>-_MIN_JUMP_PCT:continue
            ratio=close[i]/close[i-1]; m=_match_ratio(ratio)
            if not m:continue
            target,label=m; vol_ok=True
            if np.isfinite(vol[i]) and np.isfinite(vol[i-1]) and vol[i-1]>0:
                expected=1/target; actual=vol[i]/vol[i-1]; vol_ok=abs(actual-expected)<=expected*_VOL_TOL*3
            adjusted=bool(vol_ok)
            log.append({"SYMBOL":sym,"DATE":g.iloc[i]["DATE"],"RATIO":round(target,4),"LABEL":label,"PREV_CLOSE":round(close[i-1],2),"CLOSE":round(close[i],2),"ADJUSTED":adjusted})
            if adjusted:
                prior_mask=out.index.isin(idx[:i]) & out.SYMBOL.eq(sym)
                for c in price_cols:out.loc[prior_mask,c]=pd.to_numeric(out.loc[prior_mask,c],errors="coerce")*target
    cols=["SYMBOL","DATE","RATIO","LABEL","PREV_CLOSE","CLOSE","ADJUSTED"]
    return out,pd.DataFrame(log,columns=cols)

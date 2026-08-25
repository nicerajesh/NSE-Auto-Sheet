import pandas as pd

COLS=["SYMBOL","ENTRY_DATE","ENTRY","STOP_LOSS","TARGET_1","TARGET_2","TARGET_3","STATUS","LAST_DATE","LAST_CLOSE","EXIT_DATE","EXIT_PRICE","EXIT_REASON"]

def _num(v):
    try:
        x=float(v)
        return x if pd.notna(x) else None
    except Exception:
        return None

def update_ledger(old,current,allow_new=True):
    ledger=old.copy() if old is not None and not old.empty else pd.DataFrame(columns=COLS)
    for c in COLS:
        if c not in ledger.columns: ledger[c]=""
    ledger=ledger[COLS].copy()
    existing=set(ledger.SYMBOL.astype(str)) if not ledger.empty else set()
    rows=[]
    for _,r in ledger.iterrows():
        d=r.to_dict(); sym=str(d.get("SYMBOL","")); c=current.get(sym)
        if c is None:
            rows.append(d); continue
        status=str(d.get("STATUS","OPEN"))
        px=_num(c.get("CMP"))
        stop=_num(d.get("STOP_LOSS")); t1=_num(d.get("TARGET_1")); t2=_num(d.get("TARGET_2")); t3=_num(d.get("TARGET_3"))
        if status in ("EXIT","T3 HIT / EXIT"):
            rows.append(d); continue
        if px is not None:
            if stop is not None and px<=stop:
                status="EXIT"; d.update(EXIT_DATE=c.get("DATE",""),EXIT_PRICE=px,EXIT_REASON="Structure/stop")
            elif t3 is not None and px>=t3:
                status="T3 HIT / EXIT"; d.update(EXIT_DATE=c.get("DATE",""),EXIT_PRICE=px,EXIT_REASON="Target 3")
            elif t2 is not None and px>=t2: status="T2 HIT / TRAIL"
            elif t1 is not None and px>=t1: status="T1 HIT / TRAIL"
            else: status="HOLD"
            d.update(STATUS=status,LAST_DATE=c.get("DATE",""),LAST_CLOSE=px)
        rows.append(d)
    if allow_new:
        for sym,c in current.items():
            if str(c.get("ACTION")) not in ("BUY","BUY ON TRIGGER") or str(sym) in existing: continue
            rows.append({"SYMBOL":sym,"ENTRY_DATE":c.get("DATE",""),"ENTRY":c.get("CMP"),"STOP_LOSS":c.get("STOP_LOSS"),"TARGET_1":c.get("TARGET_1"),"TARGET_2":c.get("TARGET_2"),"TARGET_3":c.get("TARGET_3"),"STATUS":"OPEN","LAST_DATE":c.get("DATE",""),"LAST_CLOSE":c.get("CMP"),"EXIT_DATE":"","EXIT_PRICE":"","EXIT_REASON":""})
    return pd.DataFrame(rows,columns=COLS)

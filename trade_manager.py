"""Persistent BUY -> HOLD -> T1 -> T2 -> T3/EXIT state machine."""
import pandas as pd

def update_ledger(old,current):
 cols=["SYMBOL","ENTRY_DATE","ENTRY","STOP_LOSS","TARGET_1","TARGET_2","TARGET_3","STATUS","LAST_DATE","LAST_CLOSE","EXIT_DATE","EXIT_PRICE","EXIT_REASON"]
 ledger=old.copy() if old is not None and not old.empty else pd.DataFrame(columns=cols);existing=set(ledger.SYMBOL.astype(str)) if "SYMBOL" in ledger else set();rows=[]
 for _,r in ledger.iterrows():
  d=r.to_dict();sym=str(d["SYMBOL"]);c=current.get(sym)
  if c is None:rows.append(d);continue
  px=float(c["CMP"]);status=str(d.get("STATUS","OPEN"));stop=float(d["STOP_LOSS"]);t1=float(d["TARGET_1"]);t2=float(d["TARGET_2"]);t3=float(d["TARGET_3"])
  if status=="EXIT":rows.append(d);continue
  if px<=stop:status="EXIT";d.update(EXIT_DATE=c["DATE"],EXIT_PRICE=px,EXIT_REASON="Structure/stop")
  elif px>=t3:status="T3 HIT / EXIT";d.update(EXIT_DATE=c["DATE"],EXIT_PRICE=px,EXIT_REASON="Target 3")
  elif px>=t2:status="T2 HIT / TRAIL"
  elif px>=t1:status="T1 HIT / TRAIL"
  else:status="HOLD"
  d.update(STATUS=status,LAST_DATE=c["DATE"],LAST_CLOSE=px);rows.append(d)
 for _,c in current.items():
  if c["ACTION"] not in ("BUY","BUY ON TRIGGER") or str(c["SYMBOL"]) in existing:continue
  rows.append({"SYMBOL":c["SYMBOL"],"ENTRY_DATE":c["DATE"],"ENTRY":c["CMP"],"STOP_LOSS":c["STOP_LOSS"],"TARGET_1":c["TARGET_1"],"TARGET_2":c["TARGET_2"],"TARGET_3":c["TARGET_3"],"STATUS":"OPEN","LAST_DATE":c["DATE"],"LAST_CLOSE":c["CMP"],"EXIT_DATE":"","EXIT_PRICE":"","EXIT_REASON":""})
 return pd.DataFrame(rows,columns=cols)

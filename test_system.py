import numpy as np,pandas as pd
from indicator import add_indicators
from strategy import analyze_stock
def synthetic():
 n=260;dates=pd.bdate_range("2025-01-01",periods=n);p=[]
 for i in range(n):
  if i<90:v=140-i*.45
  elif i<120:v=99+(i-90)*.03
  elif i<140:v=100+(i-120)*1.0
  elif i<155:v=120-(i-140)*.45
  else:v=113.2+(i-155)*.65
  p.append(v+.2*np.sin(i))
 p=np.array(p);return pd.DataFrame({"SYMBOL":"TEST","DATE":dates,"OPEN_PRICE":p*.998,"HIGH_PRICE":p*1.01,"LOW_PRICE":p*.99,"CLOSE_PRICE":p,"TTL_TRD_QNTY":100000+np.arange(n)*50,"DELIV_PER":55+np.sin(np.arange(n))*2})
def main():
 df=synthetic();ind=add_indicators(df);sig=analyze_stock(ind,55);assert sig and sig["STOP_LOSS"]<sig["CMP"]<sig["TARGET_1"]<sig["TARGET_2"]<sig["TARGET_3"];assert len(ind)==len(df);print("PASS strategy:",sig["STRUCTURE"],sig["ACTION"],sig["HUNTER_SCORE"])
if __name__=="__main__":main()

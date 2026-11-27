import pandas as pd
from ry_apex_v2.portfolio import allocate_candidates,simulate_portfolio

def test_position_sizing_obeys_risk_and_slot_caps():
 d=pd.DataFrame([{"SYMBOL":"AAA","SIGNAL":"APEX BUY","SCORE":95,"MOM_RANK":90,"RS_RANK":90,"CLOSE":100.0,"STOP":95.0},{"SYMBOL":"BBB","SIGNAL":"APEX BUY","SCORE":90,"MOM_RANK":85,"RS_RANK":85,"CLOSE":100.0,"STOP":95.0}])
 x=allocate_candidates(d,100000,0.5,1.0,1,20)
 assert x.SIGNAL.eq("APEX BUY").sum()==1
 assert x.loc[x.SIGNAL.eq("APEX BUY"),"RISK_RS"].iloc[0]<=500.0
 assert x.loc[x.SIGNAL.eq("APEX BUY"),"QTY"].iloc[0]>0

def test_shared_cash_portfolio_respects_concurrent_slot_cap(monkeypatch):
 import ry_apex_v2.portfolio as p
 dates=pd.bdate_range("2025-01-01",periods=3)
 rows=[]
 for sym in ("AAA","BBB","CCC"):
  for i,day in enumerate(dates):
   rows.append({"SYMBOL":sym,"DATE":day,"OPEN":100.0,"HIGH":102.0,"LOW":99.0,"CLOSE":101.0+i,"ATR14":2.0,"SCORE":90})
 f=pd.DataFrame(rows)
 monkeypatch.setattr(p,"score_row",lambda r:(90,"APEX BUY","TEST") if r.DATE==dates[0] else (0,"WATCH","NO"))
 trades,curve,stats=simulate_portfolio(f,capital=100000,risk_pct=1.0,max_total_risk_pct=3.0,max_positions=1,max_position_pct=20.0,cost_pct=0.6,max_hold=99)
 assert stats["max_open_positions"]<=1
 assert len(trades)==1
 assert trades.iloc[0].QTY<=200
 assert stats["ending_equity"]>0
 assert stats["max_drawdown_pct"]<=0

def test_portfolio_rejects_missing_ohlc_columns():
 try:
  simulate_portfolio(pd.DataFrame([{"SYMBOL":"AAA","DATE":"2025-01-01"}]))
  assert False,"expected ValueError"
 except ValueError as e:
  assert "Missing portfolio columns" in str(e)

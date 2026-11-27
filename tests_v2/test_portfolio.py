import pandas as pd
from ry_apex_v2.portfolio import allocate_candidates

def test_position_sizing_obeys_risk_and_slot_caps():
 d=pd.DataFrame([{"SYMBOL":"AAA","SIGNAL":"APEX BUY","SCORE":95,"MOM_RANK":90,"RS_RANK":90,"CLOSE":100.0,"STOP":95.0},{"SYMBOL":"BBB","SIGNAL":"APEX BUY","SCORE":90,"MOM_RANK":85,"RS_RANK":85,"CLOSE":100.0,"STOP":95.0}])
 x=allocate_candidates(d,100000,0.5,1.0,1,20)
 assert x.SIGNAL.eq("APEX BUY").sum()==1
 assert x.loc[x.SIGNAL.eq("APEX BUY"),"RISK_RS"].iloc[0]<=500.0
 assert x.loc[x.SIGNAL.eq("APEX BUY"),"QTY"].iloc[0]>0

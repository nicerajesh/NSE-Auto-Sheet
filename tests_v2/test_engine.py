import pandas as pd
from ry_apex_v2.engine import add_symbol_features
def test_feature_warmup_and_prior_high():
 dates=pd.bdate_range("2020-01-01",periods=400); close=pd.Series(range(100,500),dtype=float); d=pd.DataFrame({"DATE":dates,"OPEN":close,"HIGH":close+1,"LOW":close-1,"CLOSE":close,"VOLUME":100000}); f=add_symbol_features(d)
 assert pd.isna(f.EMA200.iloc[198]) and pd.notna(f.EMA200.iloc[199]); assert f.HH20_PREV.iloc[20]==f.CLOSE.iloc[20]; assert pd.isna(f.VOL_AVG20.iloc[19]); assert f.VOL_AVG20.iloc[20]==100000
def test_stop_parameters_are_positive():
 from ry_apex_v2.config import CFG
 assert CFG.stop_atr>0 and CFG.max_positions>0 and CFG.cost_pct>0

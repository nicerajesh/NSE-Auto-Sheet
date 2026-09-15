import pandas as pd
from core_trend_matrix import score_row

def row(**kw):
    x={'CLOSE_PRICE':120,'EMA50':110,'EMA100':105,'EMA200':95,'EMA50_SLOPE_5':1,'EMA100_SLOPE_5':1,'EMA200_SLOPE_5':1,'RSI14':58,'RS_VS_UNIVERSE':4,'VOL_RATIO':1.6,'ATR_PCT':2.5,'DIST_52W_HIGH_PCT':-8}; x.update(kw); return pd.Series(x)

def test_strong_buy(): assert score_row(row())[1]=='STRONG BUY'
def test_avoid(): assert score_row(row(CLOSE_PRICE=80,EMA50=90,EMA100=95,EMA200=100,RSI14=32,RS_VS_UNIVERSE=-4,VOL_RATIO=.5,ATR_PCT=9,DIST_52W_HIGH_PCT=-45))[1]=='AVOID'
def test_overheated_rsi(): assert score_row(row(RSI14=78))[2]['RSI']==0

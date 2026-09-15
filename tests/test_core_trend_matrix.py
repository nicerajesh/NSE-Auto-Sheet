import numpy as np
import pandas as pd
from src.core_trend_matrix import _score_row

def row(**kw):
    base={'CLOSE_PRICE':120,'EMA50':110,'EMA100':105,'EMA200':95,'EMA50_SLOPE_5':1,'EMA100_SLOPE_5':1,'EMA200_SLOPE_5':1,'RSI14':58,'RS_VS_UNIVERSE':4,'VOL_RATIO':1.6,'ATR_PCT':2.5,'DIST_52W_HIGH_PCT':-8}
    base.update(kw); return pd.Series(base)

def test_strong_buy_score():
    s,a,_=_score_row(row()); assert s==100; assert a=='STRONG BUY'

def test_weak_stock_is_avoid():
    s,a,_=_score_row(row(CLOSE_PRICE=80,EMA50=90,EMA100=95,EMA200=100,RSI14=32,RS_VS_UNIVERSE=-4,VOL_RATIO=.5,ATR_PCT=9,DIST_52W_HIGH_PCT=-45)); assert a=='AVOID'

def test_rsi_overheated_does_not_get_full_points():
    s,a,p=_score_row(row(RSI14=78)); assert p['RSI']==0

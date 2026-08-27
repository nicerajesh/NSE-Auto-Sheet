import numpy as np
import pandas as pd
from indicator import add_indicators
from strategy import analyze_stock, ACTIONABLE
from backtest import run_backtest


def synthetic():
    n=320;dates=pd.bdate_range('2025-01-01',periods=n);p=[]
    for i in range(n):
        if i<120:v=100+i*0.04
        elif i<210:v=104+0.10*(i-120)+1.2*np.sin(i/5)
        elif i<270:v=113+0.05*(i-210)+0.7*np.sin(i/4)
        else:v=116+0.08*(i-270)+0.3*np.sin(i/3)
        p.append(v)
    p=np.asarray(p)
    return pd.DataFrame({'SYMBOL':'TEST','DATE':dates,'OPEN_PRICE':p*.998,'HIGH_PRICE':p*1.012,'LOW_PRICE':p*.988,'CLOSE_PRICE':p,'TTL_TRD_QNTY':100000+np.arange(n)*150,'DELIV_PER':50+np.linspace(0,5,n)})


def main():
    df=synthetic();ind=add_indicators(df);ind['RS_VS_UNIVERSE']=1.5
    sig=analyze_stock(ind,72,{'score':6,'regime':'NEUTRAL','breadth':55})
    assert sig is not None
    assert sig['STOP_LOSS'] < sig['CMP'] < sig['TARGET_1'] < sig['TARGET_2'] < sig['TARGET_3']
    assert 0 <= sig['HUNTER_SCORE'] <= 100
    assert sig['ACTION'] in ACTIONABLE | {'WATCH','AVOID / CHASE'}
    assert sig['STAGE']==sig['ACTION']
    assert sig.get('NEXT_DAY_ACTION','WATCH') in {'BUY','WATCH'}
    assert 0 <= float(sig.get('BREAKOUT_PROBABILITY',0)) <= 90
    assert 'ENTRY_ZONE' in sig and 'MAX_BUY_PRICE' in sig
    assert 'VOLUME_DRYUP' in sig and 'BASE_TIGHTENING' in sig
    if sig['ACTION']=='PRE-BREAKOUT BUY':
        assert sig['BREAKOUT_STATUS']=='NOT YET BROKEN'
        assert float(sig['RESISTANCE_DISTANCE_PCT']) <= 3.0
        assert int(sig['RESISTANCE_TESTS']) >= 2
        assert sig['TREND'] in {'ALIGNED','STRONG BULLISH'}
        assert sig['DELIVERY']=='STRONG + IMPROVING'
        assert sig['RELATIVE_STRENGTH'] in {'POSITIVE','STRONG'}
        assert sig['VOLUME_DRYUP']=='YES'
    weak=ind.copy();weak['RS_VS_UNIVERSE']=-5.0
    weak_sig=analyze_stock(weak,72,{'score':6,'regime':'NEUTRAL','breadth':55})
    assert weak_sig['ACTION']!='PRE-BREAKOUT BUY'
    trades,stats,cal=run_backtest(ind,72,10)
    assert isinstance(stats,dict);assert int(stats.get('trades',0))>=0;assert isinstance(cal,pd.DataFrame);assert len(ind)==len(df)
    assert isinstance(stats.get('action_stats',[]),list)
    assert 'breakout_event_samples' in stats and 'pre_breakout_event_rate_pct' in stats
    if not cal.empty:
        assert 'ANALYSIS' in cal.columns
    print('PASS strict four-bucket strategy/backtest/event-calibration regression')
    print('ACTION=',sig['ACTION'],'SCORE=',sig['HUNTER_SCORE'],'CONF=',sig.get('BREAKOUT_PROBABILITY'))

if __name__=='__main__':main()

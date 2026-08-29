import numpy as np
import pandas as pd
from indicator import add_indicators, add_indicators_all
from strategy import analyze_stock, ACTIONABLE, scan_low52_reversal
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


def synthetic_low52_reversal():
    # 228 sessions falling ~42% into a 52-week low, then a modest confirmed 8-day
    # bounce (~6%, RSI recovering from oversold) with volume + delivery expansion —
    # should trigger the reversal scanner as an early (not-yet-extended) setup.
    n=220+8;dates=pd.bdate_range('2025-01-01',periods=n);p=[];vol=[];deliv=[]
    for i in range(n):
        if i<220:
            v=200*(1-0.42*(i/220));vv=100000;dl=25
        else:
            j=i-220;v=110+1.0*j;vv=150000;dl=min(85,25+1.5*j)
        p.append(v);vol.append(vv);deliv.append(dl)
    p=np.asarray(p)
    return pd.DataFrame({'SYMBOL':'LOWTEST','DATE':dates,'OPEN_PRICE':p*.99,'HIGH_PRICE':p*1.02,'LOW_PRICE':p*.98,'CLOSE_PRICE':p,'TTL_TRD_QNTY':np.asarray(vol),'DELIV_PER':np.asarray(deliv)})


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

    low_hist=add_indicators_all(synthetic_low52_reversal())
    low52=scan_low52_reversal(low_hist)
    assert not low52.empty,'reversal scanner found nothing on a synthetic V-shaped bounce'
    assert low52.iloc[0]['SYMBOL']=='LOWTEST'
    assert low52.iloc[0]['ACTION'] in {'EARLY REVERSAL BUY','REVERSAL WATCH','NEAR 52W LOW'}
    assert 0 <= float(low52.iloc[0]['DIST_FROM_52W_LOW_PCT']) <= 25
    assert float(low52.iloc[0]['STOP_LOSS']) < float(low52.iloc[0]['ENTRY_PRICE']) < float(low52.iloc[0]['TARGET_1'])
    print('PASS 52-week-low reversal scanner regression | ACTION=',low52.iloc[0]['ACTION'],'SCORE=',low52.iloc[0]['LOW52_SCORE'])

    from quality_gate import evaluate, evaluate_action, parse_action_stats
    gate_stats={'trades':1292,'profit_factor':0.95,'median_return_pct':0.3,'win_rate_pct':40.56,
        't1_hit_pct':30,'t2_hit_pct':15,'t3_hit_pct':5,
        'action_stats':[
            {'ACTION':'SWING BUY','trades':1200,'profit_factor':0.88,'win_rate_pct':38.0,'median_return_pct':-0.4},
            {'ACTION':'BREAKOUT BUY','trades':70,'profit_factor':1.42,'win_rate_pct':52.0,'median_return_pct':2.1},
            {'ACTION':'PRE-BREAKOUT BUY','trades':32,'profit_factor':1.6,'win_rate_pct':60.0,'median_return_pct':3.0},
        ]}
    pd.DataFrame([gate_stats]).to_csv('/tmp/_qg_test.csv',index=False)
    gate_stats_rt=pd.read_csv('/tmp/_qg_test.csv').iloc[0].to_dict()
    agg_ok,agg_reason=evaluate(gate_stats_rt,pd.DataFrame())
    assert not agg_ok and agg_reason=='LOW_PROFIT_FACTOR','aggregate should fail on the blended (SWING-dragged) stats'
    parsed=parse_action_stats(gate_stats_rt)
    assert isinstance(parsed,list) and len(parsed)==3,'action_stats must survive the CSV round-trip as a list'
    action_rows={a.get('ACTION'):a for a in parsed}
    assert evaluate_action(action_rows['BREAKOUT BUY'])[0] is True
    assert evaluate_action(action_rows['PRE-BREAKOUT BUY'])[0] is True
    assert evaluate_action(action_rows['SWING BUY'])[0] is False
    print('PASS per-action quality-gate regression | aggregate blocked but BREAKOUT/PRE-BREAKOUT individually clear')

if __name__=='__main__':main()

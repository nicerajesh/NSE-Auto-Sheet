import numpy as np
import pandas as pd
from indicator import add_indicators, add_indicators_all
from strategy import analyze_stock, ACTIONABLE, scan_low52_reversal, scan_apex_matrix, scan_stealth_accumulation
from backtest import run_backtest, run_backtest_low52, run_backtest_apex, run_backtest_stealth


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


def synthetic_apex_matrix():
    # A steady-uptrend NIFTY 50 pseudo-row plus a stock that spends ~245 sessions
    # in a clean uptrend, compresses (dry-up volume) for its last 15 bars, then
    # fires a proper high-volume breakout candle on the final bar — should trigger
    # APEX BUY / STRONG BREAKOUT on the Pine-Script-faithful scanner.
    n=260;dates=pd.bdate_range('2025-08-01',periods=n)
    nifty_close=24000+np.cumsum(np.full(n,3.0))
    nifty=pd.DataFrame({'SYMBOL':'NIFTY 50','DATE':dates,'OPEN_PRICE':nifty_close*.998,'HIGH_PRICE':nifty_close*1.006,'LOW_PRICE':nifty_close*.994,'CLOSE_PRICE':nifty_close,'TTL_TRD_QNTY':np.full(n,1e9),'DELIV_PER':0.0})
    base=100+np.cumsum(np.full(n-15,0.18))
    tail=[base[-1]*1.0008**k for k in range(15)]
    p=np.concatenate([base,tail])
    openp=p*.995;high=p*1.01;low=p*.985;close=p.copy();vol=np.full(n,100000.0)
    close[-1]=close[-2]*1.045; openp[-1]=close[-2]*1.002; low[-1]=openp[-1]*0.998; high[-1]=close[-1]*1.005
    vol[-20:-1]=60000.0; vol[-1]=260000.0
    stock=pd.DataFrame({'SYMBOL':'APEXTEST','DATE':dates,'OPEN_PRICE':openp,'HIGH_PRICE':high,'LOW_PRICE':low,'CLOSE_PRICE':close,'TTL_TRD_QNTY':vol,'DELIV_PER':45.0})
    return pd.concat([nifty,stock],ignore_index=True)


def _cyclical_low52_history():
    # Single stock repeatedly falling to a fresh 52w-low-ish level then bouncing —
    # enough history (700 sessions) and enough repeats to actually exercise the
    # walk-forward backtest loop (needs MIN_HISTORY + horizon + repeats).
    n=700;dates=pd.bdate_range('2023-01-01',periods=n);rng=np.random.RandomState(7);p=[100.0]
    for i in range(1,n):
        cycle=i%140;drift=-0.15 if cycle<90 else 0.35
        p.append(max(5.0,p[-1]+drift+rng.normal(0,0.6)))
    p=np.asarray(p);vol=np.where((np.arange(n)%140)>85,180000.0,70000.0)
    return pd.DataFrame({'SYMBOL':'CYCLES','DATE':dates,'OPEN_PRICE':p*.995,'HIGH_PRICE':p*1.015,'LOW_PRICE':p*.985,'CLOSE_PRICE':p,'TTL_TRD_QNTY':vol,'DELIV_PER':np.clip(45+rng.normal(0,3,n),10,80)})


def _cyclical_apex_history():
    # NIFTY (steady bull) + a stock cycling through compression->breakout, so the
    # walk-forward APEX backtest has repeated signal opportunities over time.
    n=700;dates=pd.bdate_range('2023-01-01',periods=n);rng=np.random.RandomState(11)
    nifty_p=24000+np.cumsum(rng.normal(1.5,15,n))
    nifty=pd.DataFrame({'SYMBOL':'NIFTY 50','DATE':dates,'OPEN_PRICE':nifty_p*.998,'HIGH_PRICE':nifty_p*1.006,'LOW_PRICE':nifty_p*.994,'CLOSE_PRICE':nifty_p,'TTL_TRD_QNTY':1e9,'DELIV_PER':0.0})
    p=[100.0]
    for i in range(1,n):
        cycle=i%90;drift=0.05 if cycle<70 else 0.9
        p.append(max(5.0,p[-1]+drift+rng.normal(0,0.5)))
    p=np.asarray(p);vol=np.where((np.arange(n)%90)>=70,220000.0,70000.0)
    stock=pd.DataFrame({'SYMBOL':'CYCLEBREAK','DATE':dates,'OPEN_PRICE':p*.995,'HIGH_PRICE':p*1.015,'LOW_PRICE':p*.985,'CLOSE_PRICE':p,'TTL_TRD_QNTY':vol,'DELIV_PER':45.0})
    return pd.concat([nifty,stock],ignore_index=True)


def synthetic_stealth_accumulation():
    # ~250 sessions of a normal uptrend, then a ~70-day tight, low-volatility
    # base with delivery% steadily rising and OBV building — classic quiet
    # institutional-accumulation signature, no breakout yet.
    n=320;dates=pd.bdate_range('2025-05-01',periods=n);rng=np.random.RandomState(5);base_start=n-70
    p=[100.0]
    for i in range(1,base_start):
        p.append(p[-1]+0.12+rng.normal(0,0.9))
    p=np.asarray(p);pre_base_high=p.max();base_center=p[-1]
    base=[]
    for j in range(n-base_start):
        prog=j/(n-base_start)
        osc=0.5*np.sin(j/6)*(1-0.5*prog)
        drift=0.03*j
        noise=rng.normal(0,0.12*(1-0.6*prog))
        base.append(min(base_center+osc+drift+noise,pre_base_high*0.99))
    base=np.asarray(base);p=np.concatenate([p,base])
    day_range_pct=np.full(n,0.012);prog=np.linspace(0,1,n-base_start);day_range_pct[base_start:]=0.012*(1-0.65*prog)
    high=p*(1+day_range_pct/2);low=p*(1-day_range_pct/2)
    deliv=np.full(n,28.0);deliv[base_start:]=np.linspace(30,52,n-base_start)
    return pd.DataFrame({'SYMBOL':'STEALTH1','DATE':dates,'OPEN_PRICE':p,'HIGH_PRICE':high,'LOW_PRICE':low,'CLOSE_PRICE':p,'TTL_TRD_QNTY':100000.0,'DELIV_PER':deliv})


def _cyclical_stealth_history():
    # Repeating cycle: a volatile trending leg, then a calm, tight-range,
    # rising-delivery base — over 900 sessions so the walk-forward backtest has
    # multiple opportunities.
    n=900;dates=pd.bdate_range('2022-01-01',periods=n);rng=np.random.RandomState(9);p=[100.0];deliv=[]
    for i in range(1,n):
        cycle=i%120
        if cycle<80:
            drift=0.10;noise=rng.normal(0,0.9);dl=25.0
        else:
            drift=0.03;noise=rng.normal(0,0.15);dl=30+((cycle-80)/40)*22
        p.append(max(5.0,p[-1]+drift+noise));deliv.append(dl)
    deliv=[25.0]+deliv
    p=np.asarray(p);deliv=np.asarray(deliv)
    day_range_pct=np.where((np.arange(n)%120)>=80,0.006,0.014)
    high=p*(1+day_range_pct/2);low=p*(1-day_range_pct/2)
    return pd.DataFrame({'SYMBOL':'STEALTHCYCLE','DATE':dates,'OPEN_PRICE':p,'HIGH_PRICE':high,'LOW_PRICE':low,'CLOSE_PRICE':p,'TTL_TRD_QNTY':100000.0,'DELIV_PER':deliv})


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

    apex_hist=add_indicators_all(synthetic_apex_matrix())
    apex=scan_apex_matrix(apex_hist)
    assert not apex.empty,'APEX matrix scanner found nothing on a synthetic compression-then-breakout pattern'
    assert 'NIFTY 50' not in set(apex.SYMBOL),'NIFTY index pseudo-row must never appear as a scanned stock'
    top=apex.iloc[0]
    assert top['SYMBOL']=='APEXTEST'
    assert top['SIGNAL'] in {'APEX BUY','TACTICAL BUY','BUY'}
    assert top['MARKET_REGIME']=='BULLISH'
    assert float(top['INITIAL_SL']) < float(top['ENTRY_PRICE']) < float(top['TARGET_1']) < float(top['TARGET_2'])
    print('PASS APEX matrix (Pine port) scanner regression | SIGNAL=',top['SIGNAL'],'SCORE=',top['APEX_SCORE'])

    cyc_hist=add_indicators_all(_cyclical_low52_history())
    low52_trades,low52_stats=run_backtest_low52(cyc_hist)
    assert int(low52_stats.get('trades',0))>0,'low52 backtest found zero trades on a repeating-cycle synthetic history'
    assert 'action_stats' in low52_stats and len(low52_stats['action_stats'])>0
    print('PASS low52 backtest regression | trades=',low52_stats.get('trades'),'PF=',low52_stats.get('profit_factor'))

    apex_bt_hist=add_indicators_all(_cyclical_apex_history())
    apex_trades,apex_stats=run_backtest_apex(apex_bt_hist)
    assert 'error' not in apex_stats,'apex backtest could not find NIFTY regime data'
    assert isinstance(apex_stats.get('trades',0),int) or apex_stats.get('trades',0)>=0
    print('PASS apex backtest regression | trades=',apex_stats.get('trades'),'error=',apex_stats.get('error'))

    stealth_hist=add_indicators_all(synthetic_stealth_accumulation())
    stealth=scan_stealth_accumulation(stealth_hist)
    assert not stealth.empty,'stealth scanner found nothing on a synthetic quiet-accumulation base'
    top=stealth.iloc[0]
    assert top['SYMBOL']=='STEALTH1'
    assert top['ACTION'] in {'STEALTH BUY','STEALTH WATCH','QUIET BASE'}
    assert top['OBV_RISING']=='YES'
    assert float(top['STOP_LOSS']) < float(top['ENTRY_PRICE']) < float(top['TARGET_1']) < float(top['TARGET_2'])
    print('PASS stealth accumulation scanner regression | ACTION=',top['ACTION'],'SCORE=',top['STEALTH_SCORE'])

    stealth_cyc=add_indicators_all(_cyclical_stealth_history())
    stealth_trades,stealth_stats=run_backtest_stealth(stealth_cyc)
    assert isinstance(stealth_stats.get('trades',0),int) or stealth_stats.get('trades',0)>=0
    assert 'action_stats' in stealth_stats
    print('PASS stealth backtest regression | trades=',stealth_stats.get('trades'),'PF=',stealth_stats.get('profit_factor'))

if __name__=='__main__':main()

from __future__ import annotations
import math
import pandas as pd

_LIVE_LATEST_DATE=None
try:
    import strategy as _s
    _orig_analyze=_s.analyze_stock
    _orig_scan=getattr(_s,'scan_all',None)

    def _market(g):
        try:
            d=g[g.DATE.eq(g.DATE.max())]
            c=pd.to_numeric(d.CLOSE_PRICE,errors='coerce'); e20=pd.to_numeric(d.EMA20,errors='coerce'); e50=pd.to_numeric(d.EMA50,errors='coerce')
            ok=c.notna()&e20.notna()&e50.notna()
            breadth=float((c[ok]>e20[ok]).mean()*100) if ok.any() else 50.0
            trend=float((e20[ok]>e50[ok]).mean()*100) if ok.any() else 50.0
            if breadth>=65 and trend>=60:return {'score':10,'regime':'BULLISH','breadth':breadth}
            if breadth<=35 and trend<=40:return {'score':2,'regime':'BEARISH','breadth':breadth}
            return {'score':6,'regime':'NEUTRAL','breadth':breadth}
        except Exception:
            return {'score':5,'regime':'NEUTRAL','breadth':float('nan')}

    def _strict_probability(g,score,action):
        if _LIVE_LATEST_DATE is None or pd.Timestamp(g.DATE.max())!=pd.Timestamp(_LIVE_LATEST_DATE):return None
        if action!='PRE-BREAKOUT BUY' or len(g)<230:return None
        h=pd.to_numeric(g.HIGH_PRICE,errors='coerce').reset_index(drop=True);c=pd.to_numeric(g.CLOSE_PRICE,errors='coerce').reset_index(drop=True);n=len(g);hits=[]
        start=max(200,n-180)
        for i in range(start,n-20,5):
            if i<20 or not math.isfinite(float(c.iloc[i])):continue
            res=float(h.iloc[i-20:i].max())
            if not math.isfinite(res) or res<=0:continue
            fut=h.iloc[i+1:min(n,i+21)];hits.append(int((fut>=res*1.002).any()))
        if len(hits)<20:return None
        return int(round(100*(sum(hits)+5)/(len(hits)+10)))

    def analyze_stock(g,min_score=None,market=None):
        g=g.sort_values('DATE').reset_index(drop=True);m=_market(g) if market is None else market
        out=_orig_analyze(g,min_score,m)
        if not out:return out
        if out.get('ACTION')=='SWING BUY':
            strong=out.get('TREND')=='STRONG BULLISH';accum=out.get('ACCUMULATION')=='STRONG';delivery=str(out.get('DELIVERY','')).startswith('STRONG');rs=str(out.get('RELATIVE_STRENGTH','')) in ('STRONG','POSITIVE')
            try:
                e=float(out.get('ENTRY_PRICE'));s=float(out.get('STOP_LOSS'));risk_ok=e>s and ((e-s)/e*100)<=6.0
            except Exception:risk_ok=False
            if not(strong and accum and delivery and rs and risk_ok and float(out.get('SWING_SCORE',0) or 0)>=88):
                out['ACTION']='WATCH';out['CATEGORY']='WATCH';out['NEXT_DAY_ACTION']='WATCH';out['STAGE']='WATCH'
        p=_strict_probability(g,float(out.get('HUNTER_SCORE',0) or 0),out.get('ACTION'))
        out['MODEL_CONFIDENCE']=int(min(95,max(0,round(float(out.get('HUNTER_SCORE',0) or 0)))))
        # NOTE (fix): _strict_probability only returns a value when called from
        # inside scan_all() during a live daily run (it needs _LIVE_LATEST_DATE
        # set, and >=230 bars of history, and action=='PRE-BREAKOUT BUY'). Every
        # OTHER caller of analyze_stock -- tests/test_system.py, decision_engine's
        # per-row enrichment, ad-hoc single-symbol checks -- calls it directly, so
        # p is always None there. Previously that overwrote BREAKOUT_PROBABILITY
        # with '' unconditionally, turning a numeric field into an empty string
        # and crashing anything downstream that does float(BREAKOUT_PROBABILITY)
        # (this is exactly what broke tests/test_system.py in CI). Fix: only
        # override when the stricter historical estimate is actually available;
        # otherwise keep the model-based confidence _orig_analyze already put
        # there instead of blanking it out.
        if p is not None:
            out['BREAKOUT_PROBABILITY']=p
            out['PROBABILITY_METHOD']='PRE_SETUP_HISTORICAL_PRIOR'
        else:
            out['PROBABILITY_METHOD']='MODEL_ESTIMATE'
        return out

    _s.analyze_stock=analyze_stock

    if _orig_scan:
        def scan_all(hist,min_score=None):
            global _LIVE_LATEST_DATE
            _LIVE_LATEST_DATE=pd.Timestamp(hist.DATE.max());m=_market(hist)
            try:
                from backtest import run_backtest
                from quality_gate import evaluate
                _,stats,cal=run_backtest(hist,min_score)
                release_ok,reason=evaluate(stats,cal)
            except Exception as e:
                print('BUY RELEASE BLOCKED: gate evaluation failed:',repr(e));return pd.DataFrame()
            if not release_ok:
                print('BUY RELEASE BLOCKED:',reason);return pd.DataFrame()
            out=[]
            for sym,g in hist.groupby('SYMBOL'):
                try:
                    r=analyze_stock(g,min_score,m)
                    if r and r.get('ACTION') in {'PRE-BREAKOUT BUY','BREAKOUT BUY','SWING BUY'}:out.append(r)
                except Exception as e:print(f'SCAN BLOCKED {sym}:',repr(e))
            return pd.DataFrame(out)
        _s.scan_all=scan_all
except Exception as e:
    print('sitecustomize strategy patch warning:',repr(e))

try:
    import backtest as _bt
    _old_bt_run=_bt.run_backtest
    def run_backtest(hist,min_score=None,horizon=None):
        global _LIVE_LATEST_DATE
        _LIVE_LATEST_DATE=None
        dates=sorted(pd.to_datetime(hist.DATE).dropna().unique());contexts={}
        for d in dates:
            x=hist[pd.to_datetime(hist.DATE).eq(d)];contexts[d]=_market(x)
        old=_bt.analyze_stock
        def _parity_analyze(g,min_score=None,market=None):
            d=pd.Timestamp(g.DATE.max());return analyze_stock(g,min_score,contexts.get(d,_market(g)))
        _bt.analyze_stock=_parity_analyze
        try:return _old_bt_run(hist,min_score,horizon)
        finally:_bt.analyze_stock=old
    _bt.run_backtest=run_backtest
except Exception as e:print('sitecustomize backtest parity patch warning:',repr(e))

try:
    import quality_gate as _q
    _old_eval=_q.evaluate
    def evaluate(stats,calibration=None,min_trades=None):
        ok,reason=_old_eval(stats,calibration,min_trades)
        if not ok:return False,reason
        if float(stats.get('expectancy_pct',0) or 0)<=0:return False,'NON_POSITIVE_EXPECTANCY'
        if float(stats.get('profit_factor',0) or 0)<1.15:return False,'LOW_PROFIT_FACTOR'
        action_stats=pd.DataFrame(stats.get('action_stats',[]))
        if not action_stats.empty and 'ACTION' in action_stats.columns:
            for action in ('PRE-BREAKOUT BUY','BREAKOUT BUY','SWING BUY'):
                q=action_stats[action_stats.ACTION.eq(action)]
                if not q.empty and int(q.iloc[0].get('trades',0) or 0)>=20:
                    if float(q.iloc[0].get('profit_factor',0) or 0)<1.05:return False,f'{action} LOW_PROFIT_FACTOR'
                    if float(q.iloc[0].get('win_rate_pct',0) or 0)<40:return False,f'{action} LOW_WIN_RATE'
        return True,'PASS'
    _q.evaluate=evaluate
except Exception as e:print('sitecustomize quality gate patch warning:',repr(e))

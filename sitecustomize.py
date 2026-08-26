from __future__ import annotations
import math
import pandas as pd

_LIVE_LATEST_DATE=None


def _market(g):
    try:
        d=g[g.DATE.eq(g.DATE.max())]
        c=pd.to_numeric(d.CLOSE_PRICE,errors='coerce'); e20=pd.to_numeric(d.EMA20,errors='coerce'); e50=pd.to_numeric(d.EMA50,errors='coerce')
        ok=c.notna()&e20.notna()&e50.notna()
        breadth=float((c[ok]>e20[ok]).mean()*100) if ok.any() else 50.0
        trend=float((e20[ok]>e50[ok]).mean()*100) if ok.any() else 50.0
        if breadth>=70 and trend>=65:return {'score':10,'regime':'STRONG BULLISH','breadth':breadth}
        if breadth>=55 and trend>=50:return {'score':8,'regime':'BULLISH','breadth':breadth}
        if breadth<=30 and trend<=35:return {'score':2,'regime':'BEARISH','breadth':breadth}
        if breadth<=45 and trend<=45:return {'score':4,'regime':'WEAK','breadth':breadth}
        return {'score':6,'regime':'NEUTRAL','breadth':breadth}
    except Exception:
        return {'score':5,'regime':'NEUTRAL','breadth':float('nan')}


def _f(v, default=float('nan')):
    try:
        x=float(v)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def _liquidity_ok(g):
    try:
        q=pd.to_numeric(g.TTL_TRD_QNTY,errors='coerce')
        if len(q)<20:return True
        cur=_f(q.iloc[-1]);med=_f(q.iloc[-20:].median())
        return math.isfinite(cur) and math.isfinite(med) and cur>=max(1000,med*0.35)
    except Exception:return True


def _entry_ok(out):
    """Reject late/chasing entries even when the underlying setup score is high."""
    cmpv=_f(out.get('CMP')); max_buy=_f(out.get('MAX_BUY_PRICE')); entry=_f(out.get('ENTRY_PRICE'))
    if math.isfinite(cmpv) and math.isfinite(max_buy) and max_buy>0 and cmpv>max_buy*1.001:
        return False,'ABOVE_MAX_BUY_PRICE'
    if math.isfinite(cmpv) and math.isfinite(entry) and entry>0 and cmpv>entry*1.01:
        return False,'ENTRY_CHASE'
    r20=_f(out.get('RET_20D_PCT'))
    if math.isfinite(r20) and r20>15:
        return False,'EXTENDED_20D'
    rsi=_f(out.get('RSI'))
    if math.isfinite(rsi) and rsi>78:
        return False,'RSI_EXTREME'
    return True,''


def _final_trade_score(out, market):
    """Action-specific score. A 100 in an unrelated bucket cannot inflate the final score."""
    action=str(out.get('ACTION','WATCH'))
    pre=_f(out.get('PRE_BREAKOUT_SCORE'),0); br=_f(out.get('BREAKOUT_SCORE'),0); sw=_f(out.get('SWING_SCORE'),0)
    if action=='PRE-BREAKOUT BUY': setup=pre
    elif action=='BREAKOUT BUY': setup=br
    elif action=='SWING BUY': setup=sw
    else: setup=max(pre,br,sw)

    delivery=100 if str(out.get('DELIVERY','')).startswith('STRONG') else 65 if str(out.get('DELIVERY',''))=='GOOD' else 0
    accum=100 if out.get('ACCUMULATION')=='STRONG' else 0
    rs=100 if out.get('RELATIVE_STRENGTH')=='STRONG' else 70 if out.get('RELATIVE_STRENGTH')=='POSITIVE' else 0
    trend=100 if out.get('TREND')=='STRONG BULLISH' else 70 if out.get('TREND')=='ALIGNED' else 0
    dry=100 if out.get('VOLUME_DRYUP')=='YES' else 0
    expansion=100 if out.get('VOLUME_EXPANSION')=='YES' else 0
    sector=100 if out.get('SECTOR_STRENGTH')=='POSITIVE' else 45 if out.get('SECTOR_STRENGTH')=='UNAVAILABLE' else 0
    regime=float(market.get('score',5) or 5)*10
    risk=_f(out.get('RISK_PCT'))
    risk_score=max(0,min(100,(7.5-risk)/5.5*100)) if math.isfinite(risk) else 0
    entry_ok,_=_entry_ok(out)
    entry=100 if entry_ok else 0

    if action=='PRE-BREAKOUT BUY':
        final=.50*setup+.10*delivery+.10*accum+.10*rs+.08*trend+.04*dry+.03*sector+.03*regime+.02*entry
    elif action=='BREAKOUT BUY':
        final=.45*setup+.15*expansion+.10*delivery+.10*rs+.08*trend+.05*sector+.04*regime+.03*entry
    elif action=='SWING BUY':
        final=.48*setup+.14*trend+.10*rs+.10*delivery+.08*accum+.04*sector+.03*regime+.03*entry
    else:
        final=.50*setup+.15*trend+.15*rs+.10*delivery+.10*regime
    return int(round(max(0,min(100,final))))

try:
    import strategy as _s
    _orig_analyze=_s.analyze_stock
    _orig_scan=getattr(_s,'scan_all',None)

    def _strict_probability(g,score,action):
        if _LIVE_LATEST_DATE is None or pd.Timestamp(g.DATE.max())!=pd.Timestamp(_LIVE_LATEST_DATE):return None
        if action!='PRE-BREAKOUT BUY' or len(g)<230:return None
        h=pd.to_numeric(g.HIGH_PRICE,errors='coerce').reset_index(drop=True);c=pd.to_numeric(g.CLOSE_PRICE,errors='coerce').reset_index(drop=True);n=len(g);hits=[]
        start=max(200,n-180)
        for i in range(start,n-20,5):
            if i<20 or not math.isfinite(_f(c.iloc[i])):continue
            res=_f(h.iloc[i-20:i].max())
            if not math.isfinite(res) or res<=0:continue
            fut=h.iloc[i+1:min(n,i+21)];hits.append(int((fut>=res*1.002).any()))
        if len(hits)<30:return None
        return int(round(100*(sum(hits)+5)/(len(hits)+10)))

    def analyze_stock(g,min_score=None,market=None):
        g=g.sort_values('DATE').reset_index(drop=True);m=_market(g) if market is None else market
        out=_orig_analyze(g,min_score,m)
        if not out:return out
        final=_final_trade_score(out,m)
        out['FINAL_TRADE_SCORE']=final
        out['MODEL_CONFIDENCE']=min(95,final)
        out['HUNTER_SCORE']=final
        out['NEXT_DAY_SETUP_SCORE']=final
        out['MARKET_REGIME']=m.get('regime','NEUTRAL');out['MARKET_BREADTH']=round(_f(m.get('breadth'),50),2)

        action=out.get('ACTION')
        if action in {'PRE-BREAKOUT BUY','BREAKOUT BUY','SWING BUY'}:
            risk=_f(out.get('RISK_PCT')); sector=out.get('SECTOR_STRENGTH','UNAVAILABLE')
            liquidity=_liquidity_ok(g); regime_ok=float(m.get('score',5) or 5)>=6
            entry_ok,entry_reason=_entry_ok(out)
            # BUY release is intentionally much stricter than WATCH scoring.
            if final<88 or not liquidity or not regime_ok or not entry_ok or (math.isfinite(risk) and risk>7.0) or sector=='WEAK':
                out['ACTION']='WATCH';out['CATEGORY']='WATCH';out['NEXT_DAY_ACTION']='WATCH';out['STAGE']='WATCH'
                reasons=[]
                if final<88: reasons.append('FINAL_SCORE')
                if not liquidity: reasons.append('LIQUIDITY')
                if not regime_ok: reasons.append('MARKET_REGIME')
                if not entry_ok: reasons.append(entry_reason or 'ENTRY')
                if math.isfinite(risk) and risk>7.0: reasons.append('RISK')
                if sector=='WEAK': reasons.append('SECTOR')
                out['RELEASE_BLOCK_REASON']='|'.join(reasons)
        p=_strict_probability(g,final,out.get('ACTION'))
        out['BREAKOUT_PROBABILITY']=p if p is not None else ''
        out['PROBABILITY_METHOD']='PRE_SETUP_HISTORICAL_PRIOR' if p is not None else 'INSUFFICIENT_SETUP_HISTORY'
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
            for sym,g in hist.groupby('SYMBOL',sort=False):
                try:
                    r=analyze_stock(g,min_score,m)
                    if r and r.get('ACTION') in {'PRE-BREAKOUT BUY','BREAKOUT BUY','SWING BUY'}:out.append(r)
                except Exception as e:print(f'SCAN BLOCKED {sym}:',repr(e))
            if not out:return pd.DataFrame()
            df=pd.DataFrame(out)
            if 'SECTOR_STRENGTH' in df.columns:
                selected=[];counts={}
                for _,row in df.sort_values(['FINAL_TRADE_SCORE','BREAKOUT_SCORE','PRE_BREAKOUT_SCORE'],ascending=False).iterrows():
                    sec=str(row.get('SECTOR_STRENGTH','UNAVAILABLE'))
                    if counts.get(sec,0)>=2:continue
                    selected.append(row);counts[sec]=counts.get(sec,0)+1
                    if len(selected)>=5:break
                df=pd.DataFrame(selected)
            else:
                df=df.sort_values('FINAL_TRADE_SCORE',ascending=False).head(5)
            return df.reset_index(drop=True)
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

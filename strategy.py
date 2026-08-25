from __future__ import annotations

import numpy as np
import pandas as pd

# PRE-BREAKOUT ENGINE V2
# Causal daily NSE scanner. No future candles are used.
# One unified 100-point engine: Market -> Trend -> Accumulation -> Delivery ->
# Volume -> Compression -> Resistance -> Relative Strength -> Risk/Reward.
# Output buckets: BUY NOW / BUY ON BREAKOUT / BREAKOUT IMMINENT / WATCH / SELL / EXIT.

MIN_HISTORY = 200
BUY_SCORE = 80
STRONG_SCORE = 90
ATR_STOP = 1.5
RR1, RR2, RR3 = 2.0, 3.0, 4.0


def _f(v, default=np.nan):
    try:
        x = float(v)
        return x if np.isfinite(x) else default
    except Exception:
        return default


def _pct(a, b):
    return (a / b - 1.0) * 100.0 if np.isfinite(a) and np.isfinite(b) and b != 0 else np.nan


def _series_num(g, col):
    if col not in g.columns:
        return pd.Series(np.nan, index=g.index, dtype=float)
    return pd.to_numeric(g[col], errors='coerce').astype(float)


def _obv(g):
    c = _series_num(g, 'CLOSE_PRICE')
    v = _series_num(g, 'TTL_TRD_QNTY').fillna(0)
    direction = np.sign(c.diff()).fillna(0)
    return (direction * v).cumsum()


def _market_context(hist: pd.DataFrame) -> dict:
    latest_date = hist['DATE'].max()
    d = hist[hist['DATE'].eq(latest_date)].copy()
    if d.empty:
        return {'score': 5, 'regime': 'NEUTRAL', 'breadth': np.nan, 'reason': 'No market breadth data'}

    c = _series_num(d, 'CLOSE_PRICE')
    e20 = _series_num(d, 'EMA20')
    e50 = _series_num(d, 'EMA50')
    above20 = (c > e20).mean() * 100 if e20.notna().any() else 50.0
    trend50 = ((e20 > e50) & e20.notna() & e50.notna()).mean() * 100 if e50.notna().any() else 50.0

    nifty = d[d['SYMBOL'].astype(str).str.upper().isin({'NIFTY','NIFTY50','NIFTY_50','NIFTY 50'})]
    if not nifty.empty:
        nr = nifty.iloc[-1]
        nc, ne20, ne50 = _f(nr.get('CLOSE_PRICE')), _f(nr.get('EMA20')), _f(nr.get('EMA50'))
        if np.isfinite(nc) and np.isfinite(ne20) and np.isfinite(ne50):
            if nc > ne20 > ne50:
                return {'score': 10, 'regime': 'BULLISH', 'breadth': above20, 'reason': 'NIFTY > EMA20 > EMA50'}
            if nc < ne20 < ne50:
                return {'score': 2, 'regime': 'BEARISH', 'breadth': above20, 'reason': 'NIFTY < EMA20 < EMA50'}

    if above20 >= 65 and trend50 >= 60:
        return {'score': 10, 'regime': 'BULLISH', 'breadth': above20, 'reason': 'Breadth strong'}
    if above20 <= 35 and trend50 <= 40:
        return {'score': 2, 'regime': 'BEARISH', 'breadth': above20, 'reason': 'Breadth weak'}
    return {'score': 6, 'regime': 'NEUTRAL', 'breadth': above20, 'reason': 'Mixed market breadth'}


def _row_features(g: pd.DataFrame, i: int, market: dict | None = None) -> dict:
    g = g.sort_values('DATE').reset_index(drop=True)
    r = g.iloc[i]
    close = _f(r.get('CLOSE_PRICE')); open_ = _f(r.get('OPEN_PRICE'))
    high = _f(r.get('HIGH_PRICE')); low = _f(r.get('LOW_PRICE'))
    e20 = _f(r.get('EMA20')); e50 = _f(r.get('EMA50')); e100 = _f(r.get('EMA100')); e200 = _f(r.get('EMA200'))
    atr = _f(r.get('ATR14')); rsi = _f(r.get('RSI14')); vol = _f(r.get('VOL_RATIO'))
    delivery = _f(r.get('DELIV_PER')); deliv10 = _f(r.get('DELIV_AVG10')); deliv20 = _f(r.get('DELIV_AVG20'))
    prior20 = _f(r.get('PRIOR_HIGH20')); prior55 = _f(r.get('PRIOR_HIGH55'))
    if not np.isfinite(prior20) and i >= 20: prior20 = _f(g.HIGH_PRICE.iloc[i-20:i].max())
    if not np.isfinite(prior55) and i >= 55: prior55 = _f(g.HIGH_PRICE.iloc[i-55:i].max())

    prev_close = _f(g.CLOSE_PRICE.iloc[i-1]) if i >= 1 else np.nan
    e20p = _f(g.EMA20.iloc[i-5]) if i >= 5 else np.nan
    e50p = _f(g.EMA50.iloc[i-5]) if i >= 5 else np.nan
    e100p = _f(g.EMA100.iloc[i-5]) if i >= 5 else np.nan
    rsi_prev = _f(g.RSI14.iloc[i-1]) if i >= 1 else np.nan

    rng = high-low if np.isfinite(high) and np.isfinite(low) else np.nan
    close_location = (close-low)/rng if np.isfinite(rng) and rng > 0 else np.nan
    bullish = np.isfinite(close) and np.isfinite(open_) and close > open_

    ema_stack = all(np.isfinite(x) for x in (close,e20,e50,e100,e200)) and close > e20 > e50 > e100 > e200
    ema_slope = all(np.isfinite(x) for x in (e20,e50,e100,e20p,e50p,e100p)) and e20 > e20p and e50 > e50p and e100 >= e100p
    trend = ema_stack and ema_slope
    trend_ready = all(np.isfinite(x) for x in (close,e20,e50,e100)) and close > e50 and e20 > e50 and e50 >= e100*0.995

    # Base / compression: shrinking ATR + shrinking daily range + Bollinger width contraction.
    c = _series_num(g,'CLOSE_PRICE')
    bb_mid = c.rolling(20,min_periods=20).mean()
    bb_std = c.rolling(20,min_periods=20).std(ddof=0)
    bb_width = (4*bb_std/bb_mid.replace(0,np.nan))*100
    bb_now = _f(bb_width.iloc[i]); bb_prev = _f(bb_width.iloc[i-5]) if i >= 5 else np.nan
    atr_pct = _f(r.get('ATR_PCT')) if np.isfinite(_f(r.get('ATR_PCT'))) else _pct(atr,close)
    atr_avg = _f(r.get('ATR_PCT_AVG30'))
    atr_compress = np.isfinite(atr_pct) and np.isfinite(atr_avg) and atr_pct < atr_avg*0.92
    bb_compress = np.isfinite(bb_now) and np.isfinite(bb_prev) and bb_now < bb_prev*0.90
    range20 = _f((g.HIGH_PRICE.iloc[max(0,i-19):i+1].max()-g.LOW_PRICE.iloc[max(0,i-19):i+1].min())/close*100) if np.isfinite(close) else np.nan
    prior_range20 = np.nan
    if i >= 40:
        ph = _f(g.HIGH_PRICE.iloc[i-40:i-20].max()); pl = _f(g.LOW_PRICE.iloc[i-40:i-20].min())
        prior_range20 = _pct(ph-pl, close) if np.isfinite(ph) and np.isfinite(pl) else np.nan
    range_tight = np.isfinite(range20) and (not np.isfinite(prior_range20) or range20 <= prior_range20*0.80)
    compression = int(atr_compress) + int(bb_compress) + int(range_tight) >= 2

    # Accumulation: OBV rising while price is flat/up, down-volume less aggressive than up-volume.
    obv = _obv(g)
    obv_now = _f(obv.iloc[i]); obv_prev20 = _f(obv.iloc[i-20]) if i >= 20 else np.nan
    obv_rising = np.isfinite(obv_now) and np.isfinite(obv_prev20) and obv_now > obv_prev20
    upv = _series_num(g,'TTL_TRD_QNTY').where(c.diff() > 0, 0).rolling(10,min_periods=5).mean()
    dnv = _series_num(g,'TTL_TRD_QNTY').where(c.diff() < 0, 0).rolling(10,min_periods=5).mean()
    up_down_volume = _f(upv.iloc[i]) > _f(dnv.iloc[i]) if np.isfinite(_f(upv.iloc[i])) and np.isfinite(_f(dnv.iloc[i])) else False
    price_base = np.isfinite(_pct(close, _f(g.CLOSE_PRICE.iloc[i-20]) if i>=20 else np.nan)) and abs(_pct(close, _f(g.CLOSE_PRICE.iloc[i-20]))) <= 8
    accumulation = obv_rising and (up_down_volume or price_base)

    delivery_improving = np.isfinite(deliv10) and np.isfinite(deliv20) and deliv10 > deliv20
    delivery_good = np.isfinite(delivery) and delivery >= 30
    delivery = delivery_good or delivery_improving

    rs = np.nan
    if 'RS_VS_UNIVERSE' in r.index: rs = _f(r.get('RS_VS_UNIVERSE'))
    elif i >= 20: rs = _f(r.get('RET_20D'))
    rs_positive = np.isfinite(rs) and rs >= 0
    rs_strong = np.isfinite(rs) and rs >= 1.0

    resistance = prior20
    distance = _pct(resistance, close) if np.isfinite(resistance) else np.nan
    near_resistance = np.isfinite(distance) and 0 <= distance <= 5.0
    resistance_far = np.isfinite(distance) and distance > 12.0
    breakout = np.isfinite(resistance) and close > resistance*1.002 and bullish and np.isfinite(close_location) and close_location >= 0.60 and (not np.isfinite(vol) or vol >= 1.15)
    failed_breakout = np.isfinite(resistance) and prev_close > resistance and close < resistance and (not np.isfinite(vol) or vol >= 1.15)

    extension = _pct(close,e20) if np.isfinite(close) and np.isfinite(e20) else np.nan
    ret5 = _f(r.get('RET_5D'))
    not_extended = (not np.isfinite(extension) or extension <= 4.0) and (not np.isfinite(ret5) or ret5 <= 8.0)
    healthy_rsi = np.isfinite(rsi) and 50 <= rsi <= 72
    momentum = np.isfinite(rsi) and rsi > 52 and (not np.isfinite(rsi_prev) or rsi >= rsi_prev)
    volume_support = np.isfinite(vol) and vol >= 0.85

    # Exact 100-point model.
    market_score = int(_f((market or {}).get('score'), 5))
    trend_score = 15 if trend else 11 if trend_ready else 4
    accum_score = 15 if accumulation else 7 if obv_rising or up_down_volume else 0
    delivery_score = 15 if (delivery_good and delivery_improving) else 11 if delivery_good or delivery_improving else 3
    volume_score = 10 if np.isfinite(vol) and vol >= 1.20 else 7 if volume_support else 2
    compression_score = 10 if compression else 5 if atr_compress or bb_compress else 0
    resistance_score = 15 if breakout else 14 if near_resistance and not resistance_far else 7 if np.isfinite(distance) and distance <= 8 else 2
    rs_score = 5 if rs_strong else 3 if rs_positive else 0

    # Risk/reward uses structural/ATR stop and next resistance target.
    if np.isfinite(close) and np.isfinite(atr) and atr > 0:
        stop = close - ATR_STOP*atr
    else:
        stop = np.nan
    if np.isfinite(g.PRIOR_LOW20.iloc[i]): stop = max(stop, _f(g.PRIOR_LOW20.iloc[i])*0.985) if np.isfinite(stop) else np.nan
    risk = close-stop if np.isfinite(close) and np.isfinite(stop) else np.nan
    target_base = prior55 if np.isfinite(prior55) and prior55 > close else close + (risk*RR2 if np.isfinite(risk) else np.nan)
    rr2 = (target_base-close)/risk if np.isfinite(target_base) and np.isfinite(risk) and risk > 0 else np.nan
    rr_score = 5 if np.isfinite(rr2) and rr2 >= 3 else 4 if np.isfinite(rr2) and rr2 >= 2 else 2 if np.isfinite(rr2) and rr2 >= 1.5 else 0

    score = int(max(0,min(100, market_score+trend_score+accum_score+delivery_score+volume_score+compression_score+resistance_score+rs_score+rr_score)))
    reasons=[]
    if market_score >= 8: reasons.append('Bullish market regime')
    elif market_score <= 3: reasons.append('Weak market regime')
    if trend: reasons.append('EMA trend aligned')
    elif trend_ready: reasons.append('Trend developing')
    if accumulation: reasons.append('Accumulation/OBV positive')
    if delivery_improving: reasons.append('Delivery improving')
    if compression: reasons.append('Volatility compression')
    if near_resistance: reasons.append(f'Resistance {distance:.1f}% away')
    if rs_strong: reasons.append('Strong relative strength')
    if breakout: reasons.append('Confirmed breakout')
    if not not_extended: reasons.append('Extended / chasing risk')
    if failed_breakout: reasons.append('Breakout failure')

    # Bucket logic is deliberately different from the old EMA-only BUY trigger.
    if failed_breakout or (not trend_ready and score < 60):
        action = 'SELL / EXIT' if failed_breakout else 'WATCH'
    elif breakout and score >= BUY_SCORE and not_extended:
        action = 'BUY NOW'
    elif score >= STRONG_SCORE and near_resistance and trend_ready and not_extended:
        action = 'BREAKOUT IMMINENT'
    elif score >= BUY_SCORE and near_resistance and trend_ready and not_extended:
        action = 'BUY ON BREAKOUT'
    elif score >= 70:
        action = 'WATCH'
    else:
        action = 'WATCH'

    trigger = resistance*1.005 if np.isfinite(resistance) else np.nan
    entry_low = resistance if np.isfinite(resistance) else close
    entry_high = trigger if np.isfinite(trigger) else close
    if action == 'BUY NOW': entry_low = close; entry_high = close
    risk_entry = entry_high-stop if np.isfinite(entry_high) and np.isfinite(stop) else np.nan
    t1 = entry_high + risk_entry*RR1 if np.isfinite(risk_entry) and risk_entry > 0 else np.nan
    t2 = entry_high + risk_entry*RR2 if np.isfinite(risk_entry) and risk_entry > 0 else np.nan
    t3 = entry_high + risk_entry*RR3 if np.isfinite(risk_entry) and risk_entry > 0 else np.nan
    final_rr = (t2-entry_high)/risk_entry if np.isfinite(t2) and np.isfinite(risk_entry) and risk_entry>0 else np.nan

    stage = 'BREAKOUT CONFIRMED' if breakout else 'PRE-BREAKOUT' if near_resistance and compression else 'BASE FORMING' if compression else 'DEVELOPING'
    return locals()


def analyze_stock(g, min_score=None, market=None):
    g = g.sort_values('DATE').reset_index(drop=True)
    if len(g) < MIN_HISTORY: return None
    f = _row_features(g,len(g)-1,market)
    threshold = BUY_SCORE if min_score is None else max(60,int(min_score))
    score = int(f['score'])
    # Do not use the old score as a gate; bucket thresholds are now defined by V2.
    if f['action'] in ('BUY NOW','BUY ON BREAKOUT','BREAKOUT IMMINENT') and score < threshold:
        f['action'] = 'WATCH'
    close=f['close']
    def rv(x,d=2): return round(float(x),d) if np.isfinite(x) else ''
    return {
        'SYMBOL':str(g.iloc[-1].SYMBOL),'DATE':pd.Timestamp(g.iloc[-1].DATE).strftime('%d-%b-%Y'),
        'CMP':rv(close),'ACTION':f['action'],'STAGE':f['stage'],'HUNTER_SCORE':score,'APEX_SCORE':score,
        'BREAKOUT_CONFIDENCE':score,'ENTRY_TYPE':'MARKET' if f['action']=='BUY NOW' else 'BREAKOUT TRIGGER' if f['action'] in ('BUY ON BREAKOUT','BREAKOUT IMMINENT') else '',
        'MARKET_REGIME':(market or {}).get('regime','NEUTRAL'),'MARKET_BREADTH':rv((market or {}).get('breadth')),
        'TREND':'STRONG BULLISH' if f['trend'] else 'DEVELOPING' if f['trend_ready'] else 'WEAK',
        'ACCUMULATION':'STRONG' if f['accumulation'] else 'DEVELOPING' if f['obv_rising'] else 'WEAK',
        'DELIVERY':'IMPROVING' if f['delivery_improving'] else 'GOOD' if f['delivery_good'] else 'WEAK',
        'DELIVERY_PCT':rv(f['delivery'] if isinstance(f['delivery'],(int,float,np.floating)) else _f(g.iloc[-1].get('DELIV_PER'))),
        'DELIVERY_VALUE':rv(_f(g.iloc[-1].get('CLOSE_PRICE'))*_f(g.iloc[-1].get('DELIV_QTY'))),
        'VOLUME_RATIO':rv(f['vol']),'ATR_PCT':rv(f['atr_pct']),'ATR_COMPRESSION':'YES' if f['atr_compress'] else 'NO',
        'BB_WIDTH':'COMPRESSING' if f['bb_compress'] else 'NORMAL','BASE_COMPRESSION':'STRONG' if f['compression'] else 'PARTIAL' if (f['atr_compress'] or f['bb_compress']) else 'NO',
        'RESISTANCE':rv(f['resistance']),'RESISTANCE_DISTANCE_PCT':rv(f['distance']),'BREAKOUT_TRIGGER':rv(f['trigger']),
        'ENTRY_ZONE':f"{rv(f['entry_low'])} - {rv(f['entry_high'])}",'STOP_LOSS':rv(f['stop']),'TARGET_1':rv(f['t1']),'TARGET_2':rv(f['t2']),'TARGET_3':rv(f['t3']),'R_R':rv(f['final_rr'],2),
        'RS_VS_UNIVERSE':rv(f['rs']),'RELATIVE_STRENGTH':'STRONG' if f['rs_strong'] else 'POSITIVE' if f['rs_positive'] else 'WEAK',
        'RSI14':rv(f['rsi']),'ADX14':rv(_f(g.iloc[-1].get('ADX14'))),'EMA20':rv(f['e20']),'EMA50':rv(f['e50']),'EMA100':rv(f['e100']),'EMA200':rv(f['e200']),
        'BREAKOUT_STATUS':'CONFIRMED' if f['breakout'] else 'READY' if f['near_resistance'] else 'NOT READY',
        'QUALITY_GATE':'SETUP ENGINE','REASONS':' | '.join(f['reasons']) if f['reasons'] else 'No strong setup on latest confirmed candle'
    }


def scan_all(hist, min_score=None):
    h=hist.copy().sort_values(['SYMBOL','DATE'])
    market=_market_context(h)
    rows=[]
    for sym,g in h.groupby('SYMBOL',sort=False):
        try:
            r=analyze_stock(g,min_score,market)
            if r is not None:
                # Keep all five buckets visible; do not carry stale/previous rows forward.
                rows.append(r)
        except Exception as e:
            print('Strategy error',sym,e)
    out=pd.DataFrame(rows)
    if out.empty:return out
    order={'BUY NOW':0,'BREAKOUT IMMINENT':1,'BUY ON BREAKOUT':2,'WATCH':3,'SELL / EXIT':4}
    out['_o']=out.ACTION.map(order).fillna(9)
    out=out.sort_values(['_o','HUNTER_SCORE'],ascending=[True,False]).drop(columns='_o').reset_index(drop=True)
    out.insert(0,'RANK',range(1,len(out)+1))
    return out

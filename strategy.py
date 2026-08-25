from __future__ import annotations

import numpy as np
import pandas as pd

# RY EMA TREND SYSTEM V1
# Clean, causal, daily swing system.
# Primary decision engine = EMA structure. RSI/volume are only confirmation filters.
# No future candles are inspected and BUY is generated only on the confirmed candle.

MIN_HISTORY = 200
BUY_SCORE = 80
COOLDOWN_BARS = 5
ATR_STOP = 2.0
RR1, RR2, RR3 = 1.5, 2.5, 4.0


def _f(v, default=np.nan):
    try:
        x = float(v)
        return x if np.isfinite(x) else default
    except Exception:
        return default


def _safe_pct(a, b):
    return (a / b - 1.0) * 100.0 if np.isfinite(a) and np.isfinite(b) and b != 0 else np.nan


def _row_features(g: pd.DataFrame, i: int) -> dict:
    r = g.iloc[i]
    close = _f(r.get('CLOSE_PRICE'))
    open_ = _f(r.get('OPEN_PRICE'))
    high = _f(r.get('HIGH_PRICE'))
    low = _f(r.get('LOW_PRICE'))
    e20 = _f(r.get('EMA20'))
    e50 = _f(r.get('EMA50'))
    e100 = _f(r.get('EMA100'))
    e200 = _f(r.get('EMA200'))
    atr = _f(r.get('ATR14'))
    rsi = _f(r.get('RSI14'))
    vol = _f(r.get('VOL_RATIO'))

    e20p = _f(g.EMA20.iloc[i - 5]) if i >= 5 else np.nan
    e50p = _f(g.EMA50.iloc[i - 5]) if i >= 5 else np.nan
    e100p = _f(g.EMA100.iloc[i - 5]) if i >= 5 else np.nan
    e200p = _f(g.EMA200.iloc[i - 10]) if i >= 10 else np.nan
    prev_close = _f(g.CLOSE_PRICE.iloc[i - 1]) if i >= 1 else np.nan
    prev_e20 = _f(g.EMA20.iloc[i - 1]) if i >= 1 else np.nan
    prev_e50 = _f(g.EMA50.iloc[i - 1]) if i >= 1 else np.nan
    prev_rsi = _f(g.RSI14.iloc[i - 1]) if i >= 1 else np.nan

    prior20 = _f(r.get('PRIOR_HIGH20'))
    if not np.isfinite(prior20) and i >= 20:
        prior20 = _f(g.HIGH_PRICE.iloc[i - 20:i].max())

    rng = high - low if np.isfinite(high) and np.isfinite(low) else np.nan
    body_ratio = abs(close - open_) / rng if np.isfinite(rng) and rng > 0 else 0.0
    close_location = (close - low) / rng if np.isfinite(rng) and rng > 0 else 0.0
    bullish = np.isfinite(close) and np.isfinite(open_) and close > open_

    # The heart of the system: clean EMA hierarchy + rising slopes.
    ema_stack = all(np.isfinite(x) for x in (close, e20, e50, e100, e200)) and close > e20 > e50 > e100 > e200
    ema_slope = all(np.isfinite(x) for x in (e20, e50, e100, e20p, e50p, e100p)) and e20 > e20p and e50 > e50p and e100 >= e100p
    long_trend = ema_stack and ema_slope

    # Allow a small transition phase when price is above EMA50 and EMA20 is above EMA50.
    trend_ready = all(np.isfinite(x) for x in (close, e20, e50, e100)) and close > e50 and e20 > e50 and e50 >= e100 * 0.995

    # Two clean EMA entry patterns.
    pullback = (
        trend_ready
        and np.isfinite(prev_close) and np.isfinite(prev_e20)
        and prev_close <= prev_e20 * 1.006
        and close > e20
        and close >= e20 * 0.995
        and np.isfinite(rsi) and rsi >= 52
        and (not np.isfinite(prev_rsi) or rsi >= prev_rsi)
    )

    breakout = (
        long_trend
        and np.isfinite(prior20)
        and close > prior20 * 1.002
        and bullish
        and close_location >= 0.60
        and (not np.isfinite(vol) or vol >= 1.15)
    )

    ema50_reclaim = (
        np.isfinite(close) and np.isfinite(prev_close) and np.isfinite(e20) and np.isfinite(e50)
        and np.isfinite(prev_e50)
        and close > e50 and prev_close <= prev_e50
        and e20 > e50 and e50 >= e100 * 0.995 if np.isfinite(e100) else False
    )

    # Do not buy a stock that has already run too far from its fast EMA.
    extension_atr = (close - e20) / atr if all(np.isfinite(x) for x in (close, e20, atr)) and atr > 0 else np.nan
    ret5 = _f(r.get('RET_5D'))
    not_chasing = (not np.isfinite(extension_atr) or extension_atr <= 2.25) and (not np.isfinite(ret5) or ret5 <= 8.0)

    healthy_rsi = np.isfinite(rsi) and 52 <= rsi <= 70
    volume_ok = not np.isfinite(vol) or vol >= 0.85

    # 100-point score. EMA structure deliberately dominates the score.
    score = 0
    reasons = []

    def add(ok, pts, text):
        nonlocal score
        if bool(ok):
            score += pts
            reasons.append(text)

    add(ema_stack, 35, 'EMA 20>50>100>200')
    add(ema_slope, 20, 'EMA slopes rising')
    add(close > e20 if np.isfinite(close) and np.isfinite(e20) else False, 10, 'Price above EMA20')
    add(close > e50 if np.isfinite(close) and np.isfinite(e50) else False, 5, 'Price above EMA50')
    add(pullback, 12, 'EMA20 pullback reclaim')
    add(breakout, 12, '20D breakout')
    add(ema50_reclaim, 8, 'EMA50 reclaim')
    add(healthy_rsi, 4, 'RSI healthy')
    add(volume_ok, 4, 'Volume acceptable')
    add(not_chasing, 5, 'Not extended')

    score = int(max(0, min(100, score)))

    # Signal quality: trend-first. A breakout may enter only in a clean trend;
    # a pullback may enter in a developing trend once EMA20/50 alignment is good.
    setup = breakout or pullback or ema50_reclaim
    signal = setup and not_chasing and volume_ok and (
        (long_trend and score >= BUY_SCORE) or
        (pullback and trend_ready and score >= BUY_SCORE)
    )

    # Risk is anchored to EMA50 and ATR. Never use a future level.
    if np.isfinite(close) and np.isfinite(atr) and atr > 0:
        atr_stop = close - ATR_STOP * atr
        ema_stop = e50 * 0.985 if np.isfinite(e50) else -np.inf
        stop = max(atr_stop, ema_stop)
        if stop >= close:
            stop = close - ATR_STOP * atr
    else:
        stop = np.nan

    risk = close - stop if np.isfinite(close) and np.isfinite(stop) else np.nan
    risk_ok = np.isfinite(risk) and risk > 0 and risk / close * 100 <= 8.5

    return {
        'close': close, 'open': open_, 'high': high, 'low': low,
        'e20': e20, 'e50': e50, 'e100': e100, 'e200': e200,
        'atr': atr, 'rsi': rsi, 'vol': vol, 'prior20': prior20,
        'ema_stack': ema_stack, 'ema_slope': ema_slope,
        'long_trend': long_trend, 'trend_ready': trend_ready,
        'pullback': pullback, 'breakout': breakout,
        'ema50_reclaim': ema50_reclaim, 'not_chasing': not_chasing,
        'healthy_rsi': healthy_rsi, 'volume_ok': volume_ok,
        'extension_atr': extension_atr, 'score': score,
        'signal': signal and risk_ok, 'risk_ok': risk_ok,
        'stop': stop, 'risk': risk, 'reasons': reasons,
    }


def analyze_stock(g, min_score=None):
    g = g.sort_values('DATE').reset_index(drop=True)
    if len(g) < MIN_HISTORY:
        return None

    threshold = BUY_SCORE if min_score is None else max(BUY_SCORE, int(min_score))
    f = _row_features(g, len(g) - 1)
    close = f['close']
    risk = f['risk']
    score = f['score']

    buy = f['signal'] and score >= threshold

    if f['breakout']:
        stage = 'EMA TREND BREAKOUT'
    elif f['pullback']:
        stage = 'EMA20 PULLBACK'
    elif f['ema50_reclaim']:
        stage = 'EMA50 RECLAIM'
    elif f['long_trend']:
        stage = 'EMA TREND'
    elif f['trend_ready']:
        stage = 'EMA SETUP'
    else:
        stage = 'WAIT'

    if buy:
        entry_type = 'BREAKOUT' if f['breakout'] else 'PULLBACK' if f['pullback'] else 'EMA50 RECLAIM'
        action = 'BUY'
    else:
        entry_type = ''
        action = 'WATCH'

    stop = f['stop']
    t1 = close + risk * RR1 if np.isfinite(risk) else np.nan
    t2 = close + risk * RR2 if np.isfinite(risk) else np.nan
    t3 = close + risk * RR3 if np.isfinite(risk) else np.nan

    def rv(x, d=2):
        return round(float(x), d) if np.isfinite(x) else ''

    return {
        'SYMBOL': str(g.iloc[-1].SYMBOL),
        'DATE': pd.Timestamp(g.iloc[-1].DATE).strftime('%d-%b-%Y'),
        'CMP': rv(close),
        'ACTION': action,
        'STAGE': stage,
        'HUNTER_SCORE': score,
        'APEX_SCORE': score,
        'ENTRY_TYPE': entry_type,
        'MARKET_REGIME': 'EMA BULL' if f['long_trend'] else 'EMA DEVELOPING' if f['trend_ready'] else 'EMA WEAK',
        'INITIAL_SL': rv(stop),
        'STOP_LOSS': rv(stop),
        'TARGET_1': rv(t1),
        'TARGET_2': rv(t2),
        'TARGET_3': rv(t3),
        'ENTRY_TRIGGER': rv(close),
        'RESISTANCE': rv(f['prior20']),
        'RESISTANCE_DISTANCE_PCT': rv(_safe_pct(f['prior20'], close)),
        'RSI14': rv(f['rsi']),
        'ADX14': rv(_f(g.iloc[-1].get('ADX14'))),
        'ATR_PCT': rv(_safe_pct(f['atr'], close)),
        'VOLUME_RATIO': rv(f['vol']),
        'EMA20': rv(f['e20']),
        'EMA50': rv(f['e50']),
        'EMA100': rv(f['e100']),
        'EMA200': rv(f['e200']),
        'SETUP': stage,
        'REASONS': ' | '.join(f['reasons']) if buy else 'No fresh EMA entry on latest confirmed candle',
    }


def scan_all(hist, min_score=None):
    threshold = BUY_SCORE if min_score is None else max(BUY_SCORE, int(min_score))
    rows = []
    for sym, g in hist.groupby('SYMBOL', sort=False):
        try:
            r = analyze_stock(g, threshold)
            if r and (r['ACTION'] == 'BUY' or r['HUNTER_SCORE'] >= threshold - 5):
                rows.append(r)
        except Exception as e:
            print('Strategy error', sym, e)

    out = pd.DataFrame(rows)
    if out.empty:
        return out

    order = {'BUY': 0, 'WATCH': 1}
    out['_o'] = out.ACTION.map(order).fillna(9)
    out = out.sort_values(['_o', 'HUNTER_SCORE'], ascending=[True, False]).drop(columns='_o')
    out.insert(0, 'RANK', range(1, len(out) + 1))
    return out

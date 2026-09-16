"""RY APEX MATRIX - Intraday Cash Equity Engine.

Designed as a separate intraday research/output path. It never converts a
missing/weak setup into BUY. It produces only executable intraday candidates
when all hard gates pass; otherwise the row remains WATCH/NO TRADE.
"""
from pathlib import Path
import pandas as pd
from csv_utils import safe_read_csv, safe_to_csv

OUT = Path('output')
BUY_ACTIONS = {'INTRADAY BUY'}

# Conservative defaults. These are deliberately hard gates, not scores.
MIN_RR = 1.8
MIN_VOLUME_RATIO = 1.5
MIN_ADX = 18.0
MAX_ATR_PCT = 2.5
MIN_RS = 0.0


def _num(row, *names):
    for name in names:
        if name in row.index:
            try:
                v = float(row.get(name))
                if pd.notna(v):
                    return v
            except Exception:
                pass
    return None


def _text(row, *names):
    for name in names:
        if name in row.index:
            return str(row.get(name)).strip().upper()
    return ''


def evaluate_row(row):
    reasons = []
    price = _num(row, 'CMP', 'Close', 'CLOSE', 'LTP')
    ema20 = _num(row, 'EMA20', 'EMA_20')
    ema50 = _num(row, 'EMA50', 'EMA_50')
    ema200 = _num(row, 'EMA200', 'EMA_200')
    rsi = _num(row, 'RSI14', 'RSI')
    adx = _num(row, 'ADX14', 'ADX')
    vol = _num(row, 'VOLUME_RATIO', 'Volume Ratio', 'VOL_RATIO')
    rs = _num(row, 'RELATIVE_STRENGTH', 'RS', 'RS_NIFTY')
    atr = _num(row, 'ATR_RISK_PCT', 'ATR Risk %', 'ATR_PCT')
    entry = _num(row, 'IDEAL_ENTRY', 'ENTRY_PRICE', 'Entry')
    stop = _num(row, 'STOP_LOSS', 'STOP', 'SL')
    target = _num(row, 'TARGET_1', 'TARGET', 'T1')

    if price is None or price <= 0: reasons.append('NO_PRICE')
    if ema20 is not None and price is not None and price <= ema20: reasons.append('BELOW_EMA20')
    if ema50 is not None and price is not None and price <= ema50: reasons.append('BELOW_EMA50')
    if ema200 is not None and price is not None and price <= ema200: reasons.append('BELOW_EMA200')
    if rsi is not None and not (50 <= rsi <= 72): reasons.append('RSI_NOT_IN_MOMENTUM_ZONE')
    if adx is not None and adx < MIN_ADX: reasons.append('WEAK_ADX')
    if vol is not None and vol < MIN_VOLUME_RATIO: reasons.append('LOW_RELATIVE_VOLUME')
    if rs is not None and rs < MIN_RS: reasons.append('WEAK_RELATIVE_STRENGTH')
    if atr is not None and not (0 < atr <= MAX_ATR_PCT): reasons.append('ATR_TOO_HIGH')
    if _text(row, 'LIQUIDITY_STATUS', 'Liquidity Status') in {'LOW', 'POOR', 'FAIL'}: reasons.append('LOW_LIQUIDITY')

    rr = None
    if entry is not None and stop is not None and target is not None:
        risk = entry - stop
        reward = target - entry
        if risk <= 0 or reward <= 0:
            reasons.append('INVALID_TRADE_PLAN')
        else:
            rr = reward / risk
            if rr < MIN_RR: reasons.append('LOW_RR')
    else:
        reasons.append('MISSING_ENTRY_SL_TARGET')

    # Avoid chasing: entry should not be materially above the current price.
    if entry is not None and price is not None and entry > price * 1.015:
        reasons.append('CHASE_RISK')

    return ('INTRADAY BUY' if not reasons else 'NO TRADE'), '|'.join(reasons) if reasons else 'ALL_INTRADAY_GATES_PASS', rr


def main():
    sources = [OUT/'core_trend_matrix.csv', OUT/'early_hunter.csv', OUT/'decision_candidates.csv']
    source = next((p for p in sources if p.exists()), None)
    if source is None:
        raise RuntimeError('No scanner source available for intraday engine')
    df = safe_read_csv(source)
    if df.empty:
        safe_to_csv(pd.DataFrame(), OUT/'intraday_buy_signals.csv')
        return

    rows=[]
    for _, row in df.iterrows():
        action, reason, rr = evaluate_row(row)
        out=row.to_dict()
        out['INTRADAY_ACTION']=action
        out['INTRADAY_REASON']=reason
        out['INTRADAY_RR']=round(rr,2) if rr is not None else pd.NA
        rows.append(out)
    result=pd.DataFrame(rows)
    result=result.sort_values(['INTRADAY_ACTION','INTRADAY_RR'], ascending=[True,False], na_position='last')
    buy=result[result['INTRADAY_ACTION'].eq('INTRADAY BUY')].copy()
    buy.insert(0,'INTRADAY_RANK',range(1,len(buy)+1))
    safe_to_csv(result, OUT/'intraday_watchlist.csv')
    safe_to_csv(buy, OUT/'intraday_buy_signals.csv')
    print('INTRADAY ENGINE:', len(buy), 'BUY candidates | watchlist:', len(result))

if __name__ == '__main__':
    main()

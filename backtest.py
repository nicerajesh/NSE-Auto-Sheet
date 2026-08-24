from __future__ import annotations
import pandas as pd
from indicator import add_indicators
from strategy import analyze_stock
from config import BT


def outcome(g, entry_i, entry, stop, t1, t2, t3, horizon=30):
    f = g.iloc[entry_i + 1:entry_i + 1 + horizon]
    if f.empty:
        return None
    stop_hit = hit1 = hit2 = hit3 = False
    exit_price = None
    exit_idx = None
    exit_reason = 'TIME'
    max_high = entry
    min_low = entry
    for j, row in f.iterrows():
        lo = float(row.LOW_PRICE)
        hi = float(row.HIGH_PRICE)
        max_high = max(max_high, hi)
        min_low = min(min_low, lo)
        # Conservative daily-bar ordering: if both stop and target are touched,
        # stop wins because intraday ordering is unknown.
        if lo <= stop:
            stop_hit = True
            exit_price = stop
            exit_idx = j
            exit_reason = 'STOP'
            break
        if not hit1 and hi >= t1:
            hit1 = True
        if not hit2 and hi >= t2:
            hit2 = True
        if not hit3 and hi >= t3:
            hit3 = True
        if hit3:
            exit_price = t3
            exit_idx = j
            exit_reason = 'T3'
            break
    if exit_idx is None:
        exit_idx = f.index[-1]
        exit_price = float(f.iloc[-1].CLOSE_PRICE)
    gross = (exit_price - entry) / entry * 100
    cost = (BT.commission_bps + BT.slippage_bps) * 2 / 100
    risk = max(1e-9, entry - stop)
    return {
        'HIT_T1': hit1, 'HIT_T2': hit2, 'HIT_T3': hit3,
        'STOP_HIT': stop_hit, 'RETURN_PCT': gross - cost,
        'GROSS_RETURN_PCT': gross, 'HOLD_DAYS': int(exit_idx - entry_i),
        'EXIT_REASON': exit_reason,
        'MFE_PCT': (max_high - entry) / entry * 100,
        'MAE_PCT': (min_low - entry) / entry * 100,
        'MFE_R': (max_high - entry) / risk,
        'MAE_R': (min_low - entry) / risk,
    }


def _horizon_rows(trades, hist, horizons=(5, 10, 15, 20, 30)):
    rows = []
    if trades.empty:
        return pd.DataFrame()
    for h in horizons:
        vals = []
        for _, r in trades.iterrows():
            sym = r['SYMBOL']
            g = hist[hist.SYMBOL.eq(sym)].sort_values('DATE').reset_index(drop=True)
            idx = int(r['ENTRY_INDEX'])
            if idx >= len(g):
                continue
            j = idx + h
            if j >= len(g):
                continue
            px = float(g.iloc[j].CLOSE_PRICE)
            entry = float(r['ENTRY'])
            vals.append((px - entry) / entry * 100)
        s = pd.Series(vals, dtype='float64')
        rows.append({
            'HORIZON_DAYS': h,
            'TRADES': int(s.size),
            'WIN_RATE': round(float((s > 0).mean() * 100), 2) if len(s) else 0,
            'AVG_RETURN': round(float(s.mean()), 2) if len(s) else 0,
            'MEDIAN_RETURN': round(float(s.median()), 2) if len(s) else 0,
        })
    return pd.DataFrame(rows)


def run_backtest(hist, min_score=None, horizon=None):
    threshold = BT.min_score if min_score is None else min_score
    horizon = BT.horizon if horizon is None else horizon
    rows = []
    for sym, raw in hist.groupby('SYMBOL'):
        g = add_indicators(raw).sort_values('DATE').reset_index(drop=True)
        if len(g) < BT.warmup + horizon:
            continue
        last = -999
        for i in range(BT.warmup, len(g) - horizon):
            if i - last < BT.min_gap_between_signals:
                continue
            sig = analyze_stock(g.iloc[:i + 1], threshold)
            if not sig or sig['ACTION'] not in ('BUY', 'BUY ON TRIGGER'):
                continue

            # BUY uses the signal-day close. BUY ON TRIGGER must actually wait
            # for the stated trigger; the old version incorrectly entered at CMP.
            if sig['ACTION'] == 'BUY ON TRIGGER':
                trigger = float(sig['ENTRY_TRIGGER'])
                trigger_i = None
                for j in range(i + 1, min(len(g), i + 1 + horizon)):
                    if float(g.iloc[j].HIGH_PRICE) >= trigger:
                        trigger_i = j
                        break
                if trigger_i is None:
                    continue
                entry_i = trigger_i
                entry = trigger
            else:
                entry_i = i
                entry = float(sig['CMP'])

            stop = float(sig['STOP_LOSS'])
            t1 = float(sig['TARGET_1'])
            t2 = float(sig['TARGET_2'])
            t3 = float(sig['TARGET_3'])
            # A triggered trade needs enough bars remaining after the trigger.
            if entry_i + 1 >= len(g):
                continue
            o = outcome(g, entry_i, entry, stop, t1, t2, t3,
                        min(horizon, len(g) - entry_i - 1))
            if o:
                rows.append({
                    'SYMBOL': sym,
                    'SIGNAL_DATE': g.iloc[i].DATE,
                    'SCORE': sig['HUNTER_SCORE'],
                    'STAGE': sig['STAGE'],
                    'ACTION': sig['ACTION'],
                    'STRUCTURE': sig['STRUCTURE'],
                    'ENTRY': entry,
                    'ENTRY_INDEX': entry_i,
                    'STOP': stop, 'T1': t1, 'T2': t2, 'T3': t3,
                    **o,
                })
                last = entry_i

    trades = pd.DataFrame(rows)
    if trades.empty:
        return trades, {'trades': 0}, pd.DataFrame()

    pos = trades[trades.RETURN_PCT > 0]
    neg = trades[trades.RETURN_PCT < 0]
    stats = {
        'trades': len(trades),
        'win_rate_pct': round((trades.RETURN_PCT > 0).mean() * 100, 2),
        'median_return_pct': round(trades.RETURN_PCT.median(), 2),
        'avg_return_pct': round(trades.RETURN_PCT.mean(), 2),
        'stop_rate_pct': round(trades.STOP_HIT.mean() * 100, 2),
        't1_hit_pct': round(trades.HIT_T1.mean() * 100, 2),
        't2_hit_pct': round(trades.HIT_T2.mean() * 100, 2),
        't3_hit_pct': round(trades.HIT_T3.mean() * 100, 2),
        'profit_factor': round(pos.RETURN_PCT.sum() / max(1e-9, -neg.RETURN_PCT.sum()), 2),
        'avg_hold_days': round(trades.HOLD_DAYS.mean(), 1),
        'expectancy_pct': round(trades.RETURN_PCT.mean(), 2),
        'avg_mfe_pct': round(trades.MFE_PCT.mean(), 2),
        'avg_mae_pct': round(trades.MAE_PCT.mean(), 2),
        'median_mfe_pct': round(trades.MFE_PCT.median(), 2),
        'median_mae_pct': round(trades.MAE_PCT.median(), 2),
        'avg_mfe_r': round(trades.MFE_R.mean(), 2),
        'avg_mae_r': round(trades.MAE_R.mean(), 2),
    }

    buckets = pd.cut(
        trades.SCORE, [0, 67, 74, 81, 89, 100],
        labels=['<68', '68-74', '75-81', '82-89', '90+']
    )
    cal = trades.assign(SCORE_BUCKET=buckets).groupby(
        'SCORE_BUCKET', observed=False
    ).agg(
        TRADES=('RETURN_PCT', 'size'),
        WIN_RATE=('RETURN_PCT', lambda s: round((s > 0).mean() * 100, 2)),
        AVG_RETURN=('RETURN_PCT', 'mean'),
        MEDIAN_RETURN=('RETURN_PCT', 'median'),
        AVG_MFE=('MFE_PCT', 'mean'),
        AVG_MAE=('MAE_PCT', 'mean'),
    ).reset_index()

    horizon_df = _horizon_rows(trades, hist)
    return trades, stats, pd.concat(
        [cal.assign(ANALYSIS='SCORE_BUCKET'),
         horizon_df.assign(ANALYSIS='HORIZON')],
        ignore_index=True,
    )

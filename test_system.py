import numpy as np
import pandas as pd
from indicator import add_indicators
from strategy import analyze_stock


def synthetic():
    n = 260
    dates = pd.bdate_range('2025-01-01', periods=n)
    p = []
    for i in range(n):
        if i < 90:
            v = 140 - i * .45
        elif i < 120:
            v = 99 + (i - 90) * .03
        elif i < 140:
            v = 100 + (i - 120) * 1.0
        elif i < 155:
            v = 120 - (i - 140) * .45
        else:
            v = 113.2 + (i - 155) * .65
        p.append(v + .2 * np.sin(i))

    p = np.array(p)
    return pd.DataFrame({
        'SYMBOL': 'TEST',
        'DATE': dates,
        'OPEN_PRICE': p * .998,
        'HIGH_PRICE': p * 1.01,
        'LOW_PRICE': p * .99,
        'CLOSE_PRICE': p,
        'TTL_TRD_QNTY': 100000 + np.arange(n) * 50,
        'DELIV_PER': 55 + np.sin(np.arange(n)) * 2,
    })


def main():
    df = synthetic()
    ind = add_indicators(df)
    sig = analyze_stock(ind, 55)

    assert sig is not None
    assert sig['STOP_LOSS'] < sig['CMP'] < sig['TARGET_1'] < sig['TARGET_2'] < sig['TARGET_3']
    assert 0 <= sig['HUNTER_SCORE'] <= 100

    valid_actions = {
        'NEXT DAY PRE-BREAKOUT BUY',
        'NEXT DAY BREAKOUT BUY',
        'PRE-BREAKOUT BUY',
        'PRE-BREAKOUT WATCH/BUY',
        'BREAKOUT BUY',
        'SWING BUY',
        'BUY NOW',
        'BUY ON BREAKOUT',
        'BREAKOUT IMMINENT',
        'SWING BUY',
        'WATCH',
        'AVOID',
        'AVOID / CHASE',
        'SELL / EXIT',
    }
    assert sig['ACTION'] in valid_actions, sig['ACTION']

    valid_stages = {
        'NEXT-DAY PRE-BREAKOUT',
        'PRE-BREAKOUT',
        'PRE-BREAKOUT BUY',
        'PRE-BREAKOUT WATCH/BUY',
        'BREAKOUT CONFIRMED',
        'BREAKOUT BUY',
        'SWING',
        'SWING BUY',
        'WATCH',
        'BASE FORMING',
        'DEVELOPING',
        'AVOID / CHASE',
    }
    assert sig['STAGE'] in valid_stages, sig['STAGE']

    # NEXT_DAY_ACTION is a normalized execution flag: BUY or WATCH.
    assert sig.get('NEXT_DAY_ACTION', 'WATCH') in {'BUY', 'WATCH'}, sig.get('NEXT_DAY_ACTION')

    assert 0 <= float(sig.get('BREAKOUT_PROBABILITY', 0)) <= 100
    assert len(ind) == len(df)

    print(
        'PASS strategy:',
        sig['STAGE'],
        sig['ACTION'],
        sig['HUNTER_SCORE'],
        'next_day=', sig.get('NEXT_DAY_ACTION'),
        'prob=', sig.get('BREAKOUT_PROBABILITY'),
    )


if __name__ == '__main__':
    main()

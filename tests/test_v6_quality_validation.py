import pandas as pd

from v6_quality_validation import action_walk_forward


def test_action_walk_forward_passes_stable_action():
    dates = pd.bdate_range('2024-01-01', periods=240)
    rows = []
    for i, dt in enumerate(dates):
        rows.append({'ACTION':'SWING BUY','SIGNAL_DATE':dt,'RETURN_PCT':0.8 if i % 3 else -0.2})
    p = '/tmp/v6_action_trades.csv'
    pd.DataFrame(rows).to_csv(p, index=False)
    out, summary = action_walk_forward(p)
    assert not out.empty
    assert summary['actions']['SWING BUY']['windows'] >= 2


def test_action_walk_forward_rejects_missing_file():
    out, summary = action_walk_forward('/tmp/definitely_missing_v6_trades.csv')
    assert out.empty
    assert summary['ok'] is False
    assert summary['reason'] == 'MISSING_BACKTEST_TRADES'

from quality_gate import parse_action_stats


def test_parse_action_stats_handles_legacy_nan_repr():
    stats={
        'action_stats': "[{'ACTION': 'PRE-BREAKOUT BUY', 'trades': 31, 'profit_factor': 1.22, 'median_return_pct': 0.8, 'win_rate_pct': 48.0, 'extra': nan}]"
    }
    parsed=parse_action_stats(stats)
    assert len(parsed)==1
    assert parsed[0]['ACTION']=='PRE-BREAKOUT BUY'
    assert parsed[0]['trades']==31


def test_parse_action_stats_handles_json_cache():
    stats={
        'action_stats': '[{"ACTION":"SWING BUY","trades":35,"profit_factor":1.18}]'
    }
    parsed=parse_action_stats(stats)
    assert parsed==[{'ACTION':'SWING BUY','trades':35,'profit_factor':1.18}]


def test_parse_action_stats_rejects_malformed_records():
    stats={'action_stats': "{'ACTION':'BROKEN'}"}
    assert parse_action_stats(stats)==[]

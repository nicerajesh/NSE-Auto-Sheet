import pandas as pd
from quality_gate import parse_action_stats, evaluate


def test_parse_action_stats_handles_legacy_nan_repr():
    stats={'action_stats': "[{'ACTION': 'PRE-BREAKOUT BUY', 'trades': 31, 'profit_factor': 1.22, 'median_return_pct': 0.8, 'win_rate_pct': 48.0, 'extra': nan}]"}
    parsed=parse_action_stats(stats)
    assert len(parsed)==1
    assert parsed[0]['ACTION']=='PRE-BREAKOUT BUY'
    assert parsed[0]['trades']==31


def test_parse_action_stats_handles_json_cache():
    stats={'action_stats': '[{"ACTION":"SWING BUY","trades":35,"profit_factor":1.18}]'}
    parsed=parse_action_stats(stats)
    assert parsed==[{'ACTION':'SWING BUY','trades':35,'profit_factor':1.18}]


def test_parse_action_stats_rejects_malformed_records():
    stats={'action_stats': "{'ACTION':'BROKEN'}"}
    assert parse_action_stats(stats)==[]


def _good_stats():
    return {'trades':100,'profit_factor':1.30,'median_return_pct':0.40,'win_rate_pct':52.0,
            't1_hit_pct':60.0,'t2_hit_pct':45.0,'t3_hit_pct':25.0}


def test_quality_gate_requires_walk_forward_file(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    ok,reason=evaluate(_good_stats(),pd.DataFrame({'ANALYSIS':['BREAKOUT_EVENT'],'ACTION':['PRE-BREAKOUT BUY'],'TRADES':[20],'BREAKOUT_RATE':[50.0]}))
    assert not ok
    assert reason=='MISSING_WALK_FORWARD_SUMMARY'


def test_quality_gate_rejects_inconsistent_walk_forward(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    wf=pd.DataFrame([
        {'trades':20,'profit_factor':1.20,'median_return_pct':0.3,'win_rate_pct':50,'expectancy_pct':0.3},
        {'trades':20,'profit_factor':0.80,'median_return_pct':-0.2,'win_rate_pct':35,'expectancy_pct':-0.2},
        {'trades':20,'profit_factor':0.90,'median_return_pct':-0.1,'win_rate_pct':38,'expectancy_pct':-0.1},
        {'trades':20,'profit_factor':1.25,'median_return_pct':0.4,'win_rate_pct':48,'expectancy_pct':0.4},
    ])
    (tmp_path/'output').mkdir()
    wf.to_csv(tmp_path/'output'/'walk_forward_summary.csv',index=False)
    cal=pd.DataFrame([
        {'ANALYSIS':'BREAKOUT_EVENT','ACTION':'PRE-BREAKOUT BUY','TRADES':20,'BREAKOUT_RATE':50.0},
    ])
    ok,reason=evaluate(_good_stats(),cal)
    assert not ok
    assert reason.startswith('INCONSISTENT_ACROSS_WINDOWS_')

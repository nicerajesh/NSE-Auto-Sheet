import numpy as np
import pandas as pd
import pytest

import intraday as it
from config import CFG


def make_day(date="2026-11-18", base=1000.0, or_hi=1004.0, or_lo=996.0, rest=None, vol=1000):
    """3 OR bars (09:15-09:30) + `rest` = list of (o,h,l,c,v) bars from 09:30."""
    ts0 = pd.Timestamp(f"{date} 09:15")
    bars = [(base, or_hi, or_lo, base, vol), (base, or_hi - 1, or_lo + 1, base + 1, vol), (base + 1, or_hi, or_lo + 2, base, vol)]
    bars += list(rest or [])
    rows = [dict(TS=ts0 + pd.Timedelta(minutes=5 * i), OPEN=o, HIGH=h, LOW=l, CLOSE=c, VOLUME=v) for i, (o, h, l, c, v) in enumerate(bars)]
    return pd.DataFrame(rows)


def nifty_up(date="2026-11-18", n=60):
    ts0 = pd.Timestamp(f"{date} 09:15")
    return pd.DataFrame([dict(TS=ts0 + pd.Timedelta(minutes=5 * i), OPEN=24000 + i, HIGH=24005 + i, LOW=23995 + i,
                              CLOSE=24003 + i, VOLUME=0) for i in range(n)])


def nifty_down(date="2026-11-18", n=60):
    d = nifty_up(date, n)
    d["OPEN"] = 24000 - np.arange(n)
    d["CLOSE"] = 23997 - np.arange(n)
    d["HIGH"], d["LOW"] = d["OPEN"] + 5, d["CLOSE"] - 5
    return d


LONG_BREAK = [(1000, 1007, 999, 1006, 3000)]      # close 1006 > or_hi 1004*1.0005, big volume, above vwap


def test_long_signal_basic():
    s = it.build_signal("ABC", make_day(rest=LONG_BREAK), 995.0, nifty_up())
    assert s is not None and s.side == "LONG"
    assert s.close == 1006 and s.ts == pd.Timestamp("2026-11-18 09:35")
    assert s.stop < s.close < s.t1 < s.t2 < s.t3
    assert abs(s.t1 - s.close - s.risk) < 1e-9 and abs(s.t3 - s.close - 3 * s.risk) < 1e-9
    assert CFG.intraday_min_stop_pct / 100 * s.close - 1e-9 <= s.risk <= CFG.intraday_max_stop_pct / 100 * s.close + 1e-9


def test_short_signal_basic():
    rest = [(1000, 1001, 993, 994, 3000)]
    s = it.build_signal("ABC", make_day(rest=rest), 1005.0, nifty_down())
    assert s is not None and s.side == "SHORT" and s.stop > s.close > s.t3


def test_no_signal_without_volume():
    rest = [(1000, 1007, 999, 1006, 900)]
    assert it.build_signal("ABC", make_day(rest=rest), 995.0, nifty_up()) is None


def test_index_filter_blocks_counter_trend():
    assert it.build_signal("ABC", make_day(rest=LONG_BREAK), 995.0, nifty_down()) is None
    # index data na ho to filter skip (signal aata hai)
    assert it.build_signal("ABC", make_day(rest=LONG_BREAK), 995.0, None) is not None


def test_prev_close_filter():
    assert it.build_signal("ABC", make_day(rest=LONG_BREAK), 1010.0, nifty_up()) is None


def test_or_too_tight_or_too_wide_rejected():
    assert it.build_signal("ABC", make_day(or_hi=1000.5, or_lo=999.5, rest=LONG_BREAK), 995, nifty_up()) is None
    assert it.build_signal("ABC", make_day(or_hi=1030, or_lo=980, rest=[(1000, 1040, 999, 1035, 3000)]), 995, nifty_up()) is None


def test_cutoff_no_late_signal():
    quiet = [(1000, 1001, 999, 1000, 1000)] * 24          # 09:30 -> 11:30 shaant
    day = make_day(rest=quiet + LONG_BREAK)               # breakout 11:30 bar -> end 11:35 > cutoff
    assert it.build_signal("ABC", day, 995, nifty_up()) is None


def test_partial_data_rejected():
    d = make_day(rest=LONG_BREAK).iloc[1:].reset_index(drop=True)    # 09:15 bar missing
    assert it.build_signal("ABC", d, 995, nifty_up()) is None


def test_no_lookahead_signal_same_when_future_truncated():
    full = make_day(rest=LONG_BREAK + [(1006, 1020, 1005, 1018, 2000)] * 5)
    cut = full.iloc[:4]
    a, b = it.build_signal("ABC", full, 995, nifty_up()), it.build_signal("ABC", cut, 995, nifty_up())
    assert a is not None and b is not None and (a.close, a.stop, a.ts) == (b.close, b.stop, b.ts)


def _sim(rest_after, side_rest=LONG_BREAK, **kw):
    day = make_day(rest=side_rest + rest_after, **kw)
    s = it.build_signal("ABC", day, 995, nifty_up())
    return s, it.simulate(day, s)


def test_sim_pending_until_next_bar():
    s, r = _sim([])
    assert r["status"] == "PENDING"


def test_sim_stop_hit():
    s, r = _sim([(1006, 1007, 990, 991, 1500)])
    assert r["status"] == "STOPPED" and r["closed"] and r["r"] < -0.9


def test_sim_target3_full_exit():
    s, r = _sim([(1006, s_hi := 1040, 1005, 1038, 1500)])
    assert r["status"] == "TARGET 3" and r["closed"] and r["r"] > 2.5


def test_sim_t1_then_breakeven():
    s = it.build_signal("ABC", make_day(rest=LONG_BREAK), 995, nifty_up())
    t1 = s.t1
    after = [(1006, t1 + 0.01, 1005, t1, 1500), (t1, t1, 1005.0, 1005.5, 1500)]   # T1 chhua, phir entry (fill~1006) ke neeche
    _, r = _sim(after)
    assert r["status"] == "BREAKEVEN" and abs(r["r"]) < 0.2


def test_sim_same_bar_stop_before_target():
    s = it.build_signal("ABC", make_day(rest=LONG_BREAK), 995, nifty_up())
    _, r = _sim([(1006, s.t3 + 1, s.stop - 1, 1000, 1500)])      # ek hi bar me dono -> conservative: STOPPED
    assert r["status"] == "STOPPED"


def test_sim_skip_on_big_gap():
    s = it.build_signal("ABC", make_day(rest=LONG_BREAK), 995, nifty_up())
    gap_open = s.close + 0.6 * s.risk
    _, r = _sim([(gap_open, gap_open + 1, gap_open - 1, gap_open, 1500)])
    assert r["status"] == "SKIPPED"


def test_sim_square_off():
    quiet = [(1006, 1007, 1005, 1006, 800)] * 4
    day = make_day(rest=LONG_BREAK + quiet)
    # 15:15 bar tak pahunchane ke liye lambi series
    n_more = (15 * 60 + 15 - (9 * 60 + 15)) // 5 - len(day) + 1
    day = make_day(rest=LONG_BREAK + quiet + [(1006, 1007, 1005, 1006.5, 800)] * n_more)
    s = it.build_signal("ABC", day, 995, nifty_up())
    r = it.simulate(day, s)
    assert r["status"] == "SQUARED OFF" and r["closed"]
    assert r["exit_ts"].strftime("%H:%M") == CFG.intraday_square_off


def test_short_target_and_cost_applied():
    rest = [(1000, 1001, 993, 994, 3000)]
    day = make_day(rest=rest + [(994, 995, 950, 951, 1500)])
    s = it.build_signal("ABC", day, 1005, nifty_down())
    r = it.simulate(day, s)
    assert r["status"] == "TARGET 3"
    risk = abs(r["fill"] - s.stop)
    gross = 3.0 if abs(r["fill"] - s.close) < 1e-9 else (r["fill"] - s.t3) / risk
    assert r["r"] < gross                                           # cost kata hai


def test_size_respects_risk_and_leverage(monkeypatch):
    sz = it.intraday_size(1000, 990)
    assert sz["RISK_AMT"] <= CFG.intraday_capital * CFG.intraday_risk_pct / 100 + 1e-6
    assert sz["CAPITAL_USED"] <= CFG.intraday_capital * CFG.intraday_max_leverage + 1e-6
    assert it.intraday_size(1000, 1000)["QTY"] == 0


def test_replay_limits_trades_and_orders_by_time():
    days, prev = {}, {}
    for k in range(6):
        extra = [(1000, 1001, 999, 1000, 1000)] * k       # k bar baad breakout -> alag time
        days[f"S{k}"] = make_day(rest=extra + LONG_BREAK)
        prev[f"S{k}"] = 995.0
    out = it.replay_day(days, prev, nifty_up(), now=None)
    assert len(out) == CFG.intraday_max_trades
    assert [o["symbol"] for o in out] == ["S0", "S1", "S2"]


def test_replay_now_hides_incomplete_bar():
    day = make_day(rest=LONG_BREAK)                      # breakout bar 09:30-09:35
    prev = {"ABC": 995.0}
    assert it.replay_day({"ABC": day}, prev, nifty_up(), now=pd.Timestamp("2026-11-18 09:33")) == []
    out = it.replay_day({"ABC": day}, prev, nifty_up(), now=pd.Timestamp("2026-11-18 09:36"))
    assert len(out) == 1 and out[0]["status"] == "PENDING"


def test_backtest_and_summary():
    hist = {}
    for d in ("2026-11-16", "2026-11-17", "2026-11-18"):
        hist.setdefault("ABC", []).append(make_day(date=d, rest=LONG_BREAK + [(1006, 1040, 1005, 1038, 1500)]))
    hist["ABC"] = pd.concat(hist["ABC"], ignore_index=True)
    nif = pd.concat([nifty_up(d) for d in ("2026-11-16", "2026-11-17", "2026-11-18")], ignore_index=True)
    t = it.backtest(hist, nif)
    # din-1: prev_close nahi -> signal; din 2-3: prev close 1038 > breakout close 1006 -> long filter reject (sahi)
    assert len(t) == 1 and t["DATE"].iloc[0] == pd.Timestamp("2026-11-16")
    s = it.summarize(t)
    assert s["trades"] == len(t) and s["win_pct"] == 100.0 and s["pf"] == float("inf")


def _rand_day(rng, date, p0=1000.0, vol_pct=0.15):
    ts = pd.date_range(f"{date} 09:15", periods=75, freq="5min")
    close = p0 * np.exp(np.cumsum(rng.normal(0, vol_pct / 100, 75)))
    open_ = np.r_[p0, close[:-1]]
    hi = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, vol_pct / 200, 75)))
    lo = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, vol_pct / 200, 75)))
    vol = rng.lognormal(10, 0.7, 75) * np.r_[3, 2, 1.5, np.ones(72)]
    return pd.DataFrame(dict(TS=ts, OPEN=open_, HIGH=hi, LOW=lo, CLOSE=close, VOLUME=vol))


def test_property_signal_depends_only_on_past_bars():
    rng = np.random.default_rng(11)
    nifty = nifty_up(n=75)
    found = 0
    for k in range(600):
        full = _rand_day(rng, "2026-11-18", p0=rng.uniform(150, 3000))
        prev = full["OPEN"].iloc[0] * rng.uniform(0.99, 1.01)
        nd = nifty if k % 2 == 0 else nifty_down(n=75)
        s = it.build_signal("X", full, prev, nd)
        if s is None:
            continue
        found += 1
        cut = full.iloc[: s.bar_idx + 1]
        s2 = it.build_signal("X", cut, prev, nd)
        assert s2 is not None and (s2.side, s2.close, s2.stop, s2.ts) == (s.side, s.close, s.stop, s.ts)
        if s.bar_idx > 3:                                    # isse pehle ke bars tak data ho to signal nahi aana chahiye
            assert it.build_signal("X", full.iloc[: s.bar_idx], prev, nd) is None
    assert found > 20


def test_property_midday_replays_are_prefixes_of_later_replays():
    rng = np.random.default_rng(5)
    days = {f"S{i}": _rand_day(rng, "2026-11-18", p0=rng.uniform(150, 3000)) for i in range(40)}
    prev = {k: v["OPEN"].iloc[0] for k, v in days.items()}
    nifty = nifty_up(n=75)
    times = ["2026-11-18 09:50", "2026-11-18 10:30", "2026-11-18 11:10", "2026-11-18 15:40"]
    outs = [[(o["symbol"], o["ts"]) for o in it.replay_day(days, prev, nifty, now=pd.Timestamp(t))] for t in times]
    for a, b in zip(outs, outs[1:]):
        assert b[: len(a)] == a, (a, b)

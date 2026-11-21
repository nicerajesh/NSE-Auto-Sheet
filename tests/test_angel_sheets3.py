import json

import numpy as np
import pandas as pd

import angel
import delivery as dv
import intraday as it
import intraday_run as ir
import sheets3 as s3
from config import CFG
from test_intraday import LONG_BREAK, make_day, nifty_up


# ----------------------------------------------------------------------------- angel
class FakeSmart:
    def __init__(self, script):
        self.script, self.calls = list(script), []

    def getCandleData(self, params):
        self.calls.append(params)
        return self.script.pop(0) if self.script else {"status": True, "data": []}


def test_candles_to_df_converts_tz_to_naive_ist():
    df = angel.candles_to_df([["2026-11-19T09:15:00+05:30", 1, 2, 0.5, 1.5, 100]])
    assert df["TS"].iloc[0] == pd.Timestamp("2026-11-19 09:15")
    assert angel.candles_to_df(None).empty


def test_client_retries_on_rate_limit_then_succeeds():
    rows = [["2026-11-19T09:15:00+05:30", 1, 2, 0.5, 1.5, 100]]
    fake = FakeSmart([{"status": False, "message": "Access denied because of exceeding access rate"},
                      {"status": True, "data": rows}])
    cl = angel.AngelClient(smart=fake, sleep=0)
    df = cl._get("123", "NSE", "FIVE_MINUTE", pd.Timestamp("2026-11-19 09:00").to_pydatetime(), pd.Timestamp("2026-11-19 15:30").to_pydatetime())
    assert len(df) == 1 and len(fake.calls) == 2


def test_client_gives_up_on_non_retryable_error_returns_empty():
    fake = FakeSmart([{"status": False, "message": "Invalid Token"}])
    cl = angel.AngelClient(smart=fake, sleep=0)
    assert cl._get("1", "NSE", "FIVE_MINUTE", pd.Timestamp("2026-11-19").to_pydatetime(), pd.Timestamp("2026-11-20").to_pydatetime()).empty


def test_candles_chunk_in_30_day_windows():
    fake = FakeSmart([])
    cl = angel.AngelClient(smart=fake, sleep=0)
    cl.candles("X", pd.Timestamp("2026-08-01").to_pydatetime(), pd.Timestamp("2026-11-01").to_pydatetime(), token="9")
    assert len(fake.calls) == 4                                   # 92 din / 30 = 4 chunks


def test_unknown_symbol_returns_empty(tmp_path):
    cl = angel.AngelClient(smart=FakeSmart([]), sleep=0, state_dir=tmp_path)
    cl._tokens = {"RELIANCE": ("2885", "RELIANCE-EQ")}
    assert cl.token_for("reliance") == ("2885", "RELIANCE-EQ") and cl.token_for("NOPE") is None
    assert cl.candles("NOPE", pd.Timestamp("2026-11-18").to_pydatetime(), pd.Timestamp("2026-11-19").to_pydatetime()).empty


# ----------------------------------------------------------------------------- sheets3
def _ctx():
    return dict(asof=pd.Timestamp("2026-11-13"), breadth50=50.0, breadth200=40.0, health_label="HEALTHY")


def test_delivery_rows_shape_and_slot_label():
    cand = pd.DataFrame([
        dict(RANK=1, ZONE="BUY", SYMBOL="AAA", CLOSE=100.0, MOM=50.0, STOP=88.0, RISK_PCT=12.0, T1=124.0, T2=148.0, T3=172.0,
             QTY=10, CAPITAL_USED=1000.0, RISK_AMT=120.0, EXIT_BELOW=80.0, ADX=30.0),
        dict(RANK=21, ZONE="HOLD", SYMBOL="BBB", CLOSE=9000.0, MOM=20.0, STOP=8000.0, RISK_PCT=11.0, T1=11000.0, T2=13000.0, T3=15000.0,
             QTY=0, CAPITAL_USED=0.0, RISK_AMT=0.0, EXIT_BELOW=7000.0, ADX=22.0)])
    rows, marks = s3.build_delivery_rows(_ctx(), cand)
    assert len({len(r) for r in rows}) == 1                       # sab rows same width
    flat = [str(x) for r in rows for x in r]
    assert "AAA" in flat and "BBB" in flat and "SLOT CHHOTA" in flat
    assert marks["title"] and marks["header"]
    rows2, _ = s3.build_delivery_rows(_ctx(), pd.DataFrame())
    assert any("nahi" in str(x) for r in rows2 for x in r)


def test_delivery_candidates_zone_split_on_synthetic_features():
    n = 60
    f = pd.DataFrame({"SYMBOL": [f"S{i}" for i in range(n)], "DATE": pd.Timestamp("2026-11-13"), "CLOSE": 100.0 + np.arange(n),
                      "ATR": 3.0, "MOM": np.linspace(100, 1, n), "TREND": True, "TURNOVER_CR": 50.0, "JUMP_RECENT": 0,
                      "EMA200": 80.0, "ADX": 25.0})
    c = dv.delivery_candidates(f)
    assert len(c) == CFG.delivery_hold_n and (c["ZONE"] == "BUY").sum() == CFG.delivery_top_n
    assert c["RANK"].tolist() == list(range(1, CFG.delivery_hold_n + 1))
    assert ((c["RISK_PCT"] >= CFG.delivery_min_risk_pct - 1e-9) & (c["RISK_PCT"] <= CFG.delivery_max_risk_pct + 1e-9)).all()
    assert (c["STOP"] < c["CLOSE"]).all() and (c["T1"] < c["T2"]).all()
    f.loc[:9, "TREND"] = False                                      # trend fail -> bahar
    assert "S0" not in dv.delivery_candidates(f)["SYMBOL"].tolist()


def test_next_rebalance_is_weekday_first_of_next_month():
    d = dv.next_rebalance(pd.Timestamp("2026-11-19"))
    assert d == pd.Timestamp("2026-12-01") and d.weekday() < 5
    assert dv.next_rebalance(pd.Timestamp("2027-01-20")).weekday() < 5       # 1 Feb 2027 = Monday


def test_intraday_rows_no_signal_and_with_signal():
    meta = dict(now=pd.Timestamp("2026-11-18 10:05"), bias=1, scanned=48, missing=["FOO"], error=None, backtest=None, market_open=True)
    rows, _ = s3.build_intraday_rows([], meta)
    flat = " ".join(str(x) for r in rows for x in r)
    assert "NO SIGNAL" in flat.upper() and "FOO" in flat and "BACKTEST: abhi nahi chala" in flat
    day = make_day(rest=LONG_BREAK)
    out = it.replay_day({"ABC": day}, {"ABC": 995.0}, nifty_up(), now=pd.Timestamp("2026-11-18 09:36"))
    rows, _ = s3.build_intraday_rows(out, {**meta, "backtest": dict(trades=200, days=60, pf=1.4, win_pct=40.0, avg_r=0.2, max_dd_r=-9.0)})
    flat = " ".join(str(x) for r in rows for x in r)
    assert "ABC" in flat and "BUY" in flat and "PENDING" in flat and "PF 1.4" in flat
    assert len({len(r) for r in rows}) == 1


def test_intraday_rows_market_closed():
    rows, _ = s3.build_intraday_rows([], dict(now=pd.Timestamp("2026-11-21 10:00"), bias=None, scanned=0, market_open=False))
    assert any("market band" in str(x).lower() for r in rows for x in r)


# ----------------------------------------------------------------------------- end-to-end offline
def _write_csvs(tmp, days=("2026-11-16", "2026-11-17", "2026-11-18")):
    syms = ["AAA", "BBB"]
    for s in syms:
        parts = []
        for d in days:
            rest = LONG_BREAK + [(1006, 1040, 1005, 1038, 1500)] if d == days[0] else [(1000, 1001, 999, 1000, 1000)] * 3
            parts.append(make_day(date=d, rest=rest))
        pd.concat(parts).to_csv(tmp / f"{s}.csv", index=False)
    pd.concat([nifty_up(d) for d in days]).to_csv(tmp / "NIFTY.csv", index=False)


def test_runner_offline_backtest_and_live_replay(tmp_path, monkeypatch):
    _write_csvs(tmp_path)
    monkeypatch.setenv("INTRADAY_SYMBOLS", "AAA,BBB,MISSING")
    monkeypatch.setattr(ir, "OUT", tmp_path / "out")
    monkeypatch.setattr(ir, "STATE", tmp_path / "state")
    monkeypatch.setattr(ir, "BT_FILE", tmp_path / "state" / "bt.json")
    summ = ir.run_backtest(0, tmp_path)
    assert summ["trades"] == 2 and summ["win_pct"] == 100.0
    assert json.loads((tmp_path / "state" / "bt.json").read_text())["trades"] == 2
    sigs = ir.live_scan(pd.Timestamp("2026-11-16 09:36"), tmp_path, publish=False)
    assert {s["symbol"] for s in sigs} == {"AAA", "BBB"} and all(s["status"] == "PENDING" for s in sigs)
    later = ir.live_scan(pd.Timestamp("2026-11-16 15:40"), tmp_path, publish=False)
    assert all(s["status"] == "TARGET 3" for s in later)
    assert ir.live_scan(pd.Timestamp("2026-11-17 09:36"), tmp_path, publish=False) == []     # prev_close filter
    assert (tmp_path / "out" / "intraday_signals.csv").exists()


def test_runner_data_error_is_reported_not_crash(monkeypatch, tmp_path):
    monkeypatch.setattr(ir, "OUT", tmp_path)
    monkeypatch.setattr(ir, "fetch_angel", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("login fail")))
    published = {}
    monkeypatch.setattr(s3, "publish_tab", lambda title, built, book=None: published.setdefault("rows", built[0]))
    assert ir.live_scan(pd.Timestamp("2026-11-18 10:00"), None, publish=True) == []
    assert any("DATA ERROR" in str(x) for r in published["rows"] for x in r)


def test_clean_extra_tabs_keeps_delivery_and_intraday(monkeypatch):
    from unittest.mock import MagicMock
    import publish as pb
    from test_pipeline import _ctx
    monkeypatch.setenv("CLEAN_EXTRA_TABS", "1")
    book = MagicMock()
    ws = MagicMock(); ws.row_count = 500; ws.col_count = 30; ws.id = 1
    book.worksheet.return_value = ws
    tabs = []
    for t in (CFG.action_tab, CFG.status_tab, CFG.positions_tab, CFG.delivery_tab, CFG.intraday_tab, "ACTION PLAN", "OLD JUNK"):
        m = MagicMock(); m.title = t; tabs.append(m)
    book.worksheets.return_value = tabs
    pb.publish(pb.build_action_rows(_ctx()), pb.build_status_rows(_ctx()), book=book)
    assert sorted(c.args[0].title for c in book.del_worksheet.call_args_list) == ["ACTION PLAN", "OLD JUNK"]


def test_intraday_publish_path_with_fake_book(tmp_path, monkeypatch):
    from unittest.mock import MagicMock
    book = MagicMock()
    ws = MagicMock(); ws.row_count = 500; ws.col_count = 30; ws.id = 7
    book.worksheet.return_value = ws
    _write_csvs(tmp_path)
    monkeypatch.setenv("INTRADAY_SYMBOLS", "AAA,BBB")
    monkeypatch.setattr(ir, "OUT", tmp_path / "out")
    monkeypatch.setattr(ir, "BT_FILE", tmp_path / "nobt.json")
    sigs = ir.live_scan(pd.Timestamp("2026-11-16 09:36"), tmp_path, publish=True, book=book)
    assert len(sigs) == 2
    kw = ws.update.call_args.kwargs
    assert kw["value_input_option"] == "RAW" and kw["range_name"] == "A1"
    flat = " ".join(str(x) for r in kw["values"] for x in r)
    assert "AAA" in flat and "PENDING" in flat and "RY INTRADAY" in flat

import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock

import backtest as bt
import ledger as lg
import publish as pb
from engine import add_features
from test_engine import _synthetic


def _ctx(buy_ok=True):
    buy = pd.DataFrame([{"SYMBOL": "AAA", "SETUP": "PULLBACK", "CLOSE": 100.0, "STOP": 94.0, "T1": 112.0, "T2": 124.0, "T3": 136.0,
                         "RISK_PCT": 6.0, "QTY": 100, "CAPITAL_USED": 10000.0, "RISK_AMT": 600.0, "MOM_RANK": 97.0}])
    buy_watch = pd.DataFrame([{"SYMBOL": "WWW", "SETUP": "BREAKOUT", "CLOSE": 60.0, "STOP": 56.0, "T1": 68.0, "T2": 76.0, "T3": 84.0,
                               "RISK_PCT": 6.7, "QTY": 50, "CAPITAL_USED": 3000.0, "RISK_AMT": 200.0, "MOM_RANK": 62.0}])
    buy_v38 = pd.DataFrame([{"SYMBOL": "VVV", "V38_SETUP": "STRONG BREAKOUT", "CLOSE": 40.0, "STOP": 36.0, "T1": 48.0, "T2": 52.0,
                             "RISK_PCT": 10.0, "QTY": 30, "CAPITAL_USED": 1200.0, "RISK_AMT": 120.0}])
    buy_v42 = pd.DataFrame([{"SYMBOL": "UUU", "V42_ENTRY_TYPE": "APEX BUY", "V42_SCORE": 91, "CLOSE": 80.0, "STOP": 74.0,
                             "T1": 92.0, "T2": 98.0, "RISK_PCT": 7.5, "QTY": 20, "CAPITAL_USED": 1600.0, "RISK_AMT": 120.0}])
    watch = pd.DataFrame([{"SYMBOL": "BBB", "CLOSE": 50.0, "MOM_RANK": 95.0, "EMA20": 49.0, "HH20": 52.0, "RSI": 55.0,
                          "TRIGGER": 52.1, "DIST_TO_TRIGGER_PCT": 4.2, "RANGE_TIGHTNESS": 82.0}])
    yearly = pd.DataFrame([{"YEAR": 2024, "trades": 10, "win_pct": 30.0, "avg_r": 0.2, "pf": 1.4}])
    return dict(asof=pd.Timestamp("2026-09-11"), banner="BUY ACTIVE", buy_ok=buy_ok, mult=1.0, health_label="HEALTHY", health=dict(label="HEALTHY", n=40, avg_r=0.2),
                buy=buy, buy_watch=buy_watch, buy_v38=buy_v38, buy_v42=buy_v42, watch=watch, open=pd.DataFrame(), slots_free=12, bt=dict(trades=10, win_pct=30.0, avg_r=0.2, avg_ret=2.0, median_ret=-5.0, pf=1.4, max_loss_streak=8),
                by_year=yearly, score=dict(closed=0, active=0, win_pct=np.nan, avg_r=np.nan, pf=np.nan),
                n_symbols=400, n_sessions=1900, breadth50=40.0, breadth200=55.0, notes=["x"])


def test_action_rows_rectangular_and_content():
    rows, marks = pb.build_action_rows(_ctx())
    assert len({len(r) for r in rows}) == 1
    flat = [str(x) for r in rows for x in r]
    assert "AAA" in flat and "BBB" in flat and "WWW" in flat
    assert marks["header"] and marks["title"]


def test_action_rows_blocked_shows_reason_not_buys():
    rows, _ = pb.build_action_rows(_ctx(buy_ok=False))
    flat = [str(x) for r in rows for x in r]
    assert "AAA" not in flat and any("BUY BAND" in x for x in flat)


def test_status_rows_rectangular():
    rows, _ = pb.build_status_rows(_ctx())
    assert len({len(r) for r in rows}) == 1


def test_publish_writes_two_tabs_with_fake_book():
    book = MagicMock()
    ws = MagicMock(); ws.row_count = 500; ws.col_count = 30; ws.id = 1
    book.worksheet.return_value = ws
    assert pb.publish(pb.build_action_rows(_ctx()), pb.build_status_rows(_ctx()), book=book)
    assert ws.update.call_count == 2 and ws.batch_clear.call_count == 2


def test_publish_without_credentials_is_skipped(monkeypatch):
    monkeypatch.delenv("GCP_CREDENTIALS", raising=False)
    assert pb.publish(pb.build_action_rows(_ctx()), pb.build_status_rows(_ctx())) is False


def test_backtest_and_ledger_run_on_synthetic():
    f = add_features(_synthetic(n=700, seed=3, syms=tuple(f"S{i}" for i in range(30))))
    t = bt.run_backtest(f, start="2023-01-01")
    s = bt.summarize(t)
    assert s["trades"] == len(t)
    if len(t):
        assert (t.EXIT_DATE >= t.ENTRY_DATE).all()
        assert bt.health(t, f.DATE.max())["mult"] in (0.5, 1.0)
    gate_ok, reason = bt.edge_gate(t)
    assert isinstance(gate_ok, bool) and isinstance(reason, str)


def test_ledger_lifecycle():
    f = add_features(_synthetic(n=450, seed=5))
    sym = "DDD"
    g = f[f.SYMBOL == sym].sort_values("DATE").reset_index(drop=True)
    sig_i = 400
    row = g.iloc[sig_i]
    buy = pd.DataFrame([{"SYMBOL": sym, "SETUP": "PULLBACK", "CLOSE": row.CLOSE, "STOP": row.CLOSE - 2 * row.ATR,
                         "T1": row.CLOSE + 4 * row.ATR, "T2": row.CLOSE + 8 * row.ATR, "T3": row.CLOSE + 12 * row.ATR}])
    led = lg.add_signals(pd.DataFrame(columns=lg.LEDGER_COLS), buy, row.DATE)
    # sirf signal date tak data -> PENDING
    led = lg.update(led, f[f.DATE <= row.DATE])
    assert led.iloc[0].STATUS == "PENDING"
    # duplicate signal 3 din baad -> cooldown se skip
    again = lg.add_signals(led, buy, row.DATE + pd.Timedelta(days=3))
    assert len(again) == 1
    led = lg.update(led, f)
    assert led.iloc[0].STATUS in ("ACTIVE", "CLOSED", "SKIPPED")
    tbl = lg.open_table(led, f.DATE.max())
    sb = lg.scoreboard(led)
    assert "closed" in sb


def test_edge_gate_blocks_when_out_of_sample_is_negative():
    import backtest as bt
    rng = np.random.default_rng(1)
    d_is = pd.date_range("2019-03-01", periods=350, freq="3D")
    d_oos = pd.date_range("2023-03-01", periods=120, freq="5D")
    win_is = rng.random(350) < 0.6
    ret_is = np.where(win_is, 8.0, -3.0)
    ret_oos = np.where(rng.random(120) < 0.2, 5.0, -4.0)            # OOS me edge gayab
    t = pd.DataFrame({"EXIT_DATE": list(d_is) + list(d_oos), "RET_PCT": list(ret_is) + list(ret_oos),
                      "R": list(ret_is / 4) + list(ret_oos / 4)})
    ok, why = bt.edge_gate(t)
    assert not ok and "OUT-OF-SAMPLE" in why
    ok2, _ = bt.edge_gate(t[t.EXIT_DATE < "2023-01-01"])
    assert ok2                                                      # sirf in-sample dekho to gate pass (yahi circular problem tha)

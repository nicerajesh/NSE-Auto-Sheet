import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock

import notify as nt
import positions as ps
import publish as pb
from config import CFG


def mk(sym, rows, start="2026-06-01", atr=3.0):
    """rows: (open, high, low, close) per session."""
    d = pd.bdate_range(start, periods=len(rows))
    a = np.array(rows, float)
    return pd.DataFrame({"SYMBOL": sym, "DATE": d, "OPEN": a[:, 0], "HIGH": a[:, 1], "LOW": a[:, 2], "CLOSE": a[:, 3], "ATR": atr})


def pos_df(sym="AAA", date="2026-06-01", price=100.0, qty=10, stop=np.nan):
    return pd.DataFrame([{"SYMBOL": sym, "BUY DATE": pd.Timestamp(date), "BUY PRICE": price, "QTY": qty, "MY STOP": stop, "NOTES": ""}])


def flat(n, px=100.0):
    return [(px, px + 1, px - 1, px)] * n


def test_parse_handles_indian_formats_and_flags_bad_rows():
    raw = [["Symbol", "Buy Date", "Buy Price", "Qty", "My Stop", "Notes"],
           ["reliance", "05-09-2026", "₹1,250.50", "10", "", "ok"],
           ["TCS", "garbage", "3500", "5", "", ""],
           ["INFY", "01-09-2026", "1500", "5", "1600", ""],       # stop >= price
           ["", "", "", "", "", ""],
           ["SBIN", "02-09-2026", "800", "0", "", ""]]
    d, problems = ps.parse(raw)
    assert list(d.SYMBOL) == ["RELIANCE"] and d.iloc[0]["BUY PRICE"] == pytest.approx(1250.5)
    assert d.iloc[0]["BUY DATE"] == pd.Timestamp("2026-09-05")       # dayfirst
    assert len(problems) == 3


def test_parse_missing_header_gives_problem():
    d, problems = ps.parse([["FOO", "BAR"], ["a", "b"]])
    assert d.empty and problems


def test_hold_when_nothing_happens():
    f = mk("AAA", flat(10))
    r = ps.evaluate(pos_df(), f, f.DATE.max()).iloc[0]
    assert r.STATE == "OPEN" and r.ACTION.startswith("HOLD") and r["SL NOW"] == pytest.approx(94.0)   # 100 - 2*3
    assert r["RISK RS"] == pytest.approx(10 * (100 - 94))


def test_sl_hit_today_is_flagged_urgent():
    rows = flat(5) + [(99, 100, 93, 95)]                              # low 93 <= 94
    f = mk("AAA", rows)
    r = ps.evaluate(pos_df(), f, f.DATE.max()).iloc[0]
    assert r.STATE == "EXITED" and r.PRIORITY == 0 and "SL HIT aaj" in r.ACTION
    assert r["PNL RS"] == pytest.approx(10 * (94 - 100))


def test_gap_down_through_stop_exits_at_open():
    rows = flat(3) + [(90, 91, 88, 89)]
    f = mk("AAA", rows)
    r = ps.evaluate(pos_df(), f, f.DATE.max()).iloc[0]
    assert r["PNL RS"] == pytest.approx(10 * (90 - 100))


def test_t1_touch_raises_sl_to_entry_and_says_raise():
    rows = flat(2) + [(101, 113, 100, 112)]                           # T1 = 100 + 2*6 = 112
    f = mk("AAA", rows)
    r = ps.evaluate(pos_df(), f, f.DATE.max()).iloc[0]
    assert r.TIER == "T1" and r["SL NOW"] == pytest.approx(100.0)
    assert r.ACTION.startswith("SL RAISE") and r.PRIORITY == 1


def test_t2_then_t3_ratchet():
    f2 = mk("AAA", flat(2) + [(101, 125, 100, 124)])                  # T2 = 124
    assert ps.evaluate(pos_df(), f2, f2.DATE.max()).iloc[0]["SL NOW"] == pytest.approx(112.0)
    f3 = mk("AAA", flat(2) + [(101, 137, 100, 136)])                  # T3 = 136
    assert ps.evaluate(pos_df(), f3, f3.DATE.max()).iloc[0]["SL NOW"] == pytest.approx(124.0)


def test_my_stop_overrides_atr_stop():
    f = mk("AAA", flat(4))
    r = ps.evaluate(pos_df(stop=97.0), f, f.DATE.max()).iloc[0]
    assert r["SL NOW"] == pytest.approx(97.0) and r["T1"] == pytest.approx(106.0)


def test_time_exit_after_max_hold():
    f = mk("AAA", flat(CFG.max_hold + 3))
    r = ps.evaluate(pos_df(), f, f.DATE.max()).iloc[0]
    assert r.STATE == "TIME" and r.PRIORITY == 2


def test_unknown_symbol_flagged():
    f = mk("AAA", flat(5))
    r = ps.evaluate(pos_df(sym="ZZZ"), f, f.DATE.max()).iloc[0]
    assert r.STATE == "NO DATA"


def test_summary_and_drawdown_guard():
    f = mk("AAA", flat(3) + [(90, 91, 89, 90)])  # stop hit -> closed, not counted as open
    mine = ps.evaluate(pos_df(), f, f.DATE.max())
    assert ps.summarize(mine)["n_open"] == 0
    # big open loss but above stop: qty large so unrealized loss exceeds guard
    big = pos_df(qty=int(CFG.capital * (CFG.dd_guard_pct / 100 + 0.02) / 4), stop=90.0)
    f2 = mk("AAA", flat(3) + [(96, 97, 95, 96)])
    s = ps.summarize(ps.evaluate(big, f2, f2.DATE.max()))
    assert s["n_open"] == 1 and s["dd_guard"] is True


def _buy(rows):
    return pd.DataFrame([{"SYMBOL": s, "CLOSE": 100.0, "STOP": 94.0, "QTY": q, "CAPITAL_USED": q * 100.0, "RISK_AMT": q * 6.0} for s, q in rows])


def test_fit_skips_held_and_respects_slots():
    out = ps.fit_to_portfolio(_buy([("A", 100), ("B", 100), ("C", 100)]), {"A"}, 1, 1e9, 1e9)
    assert list(out.SYMBOL) == ["B"]


def test_fit_scales_qty_to_risk_budget_and_cash():
    out = ps.fit_to_portfolio(_buy([("A", 1000), ("B", 1000)]), set(), 5, budget_rs=6000.0, cash_rs=1e9)
    assert list(out.SYMBOL) == ["A"] and out.iloc[0].QTY == 1000 and out.iloc[0].RISK_AMT == pytest.approx(6000.0)   # budget gone after A
    out2 = ps.fit_to_portfolio(_buy([("A", 1000)]), set(), 5, budget_rs=1e9, cash_rs=25_000.0)
    assert out2.iloc[0].QTY == 250


def test_fit_empty_when_no_budget():
    assert ps.fit_to_portfolio(_buy([("A", 10)]), set(), 5, 0.0, 1e9).empty


def test_notify_message_only_when_actionable(monkeypatch):
    ctx = dict(asof=pd.Timestamp("2026-09-11"), mult_total=0.25, buy_ok=True, banner="ok", buy=_buy([]).assign(SETUP=[], T1=[], T2=[], T3=[]),
               mine=pd.DataFrame(columns=ps.EVAL_COLS))
    assert nt.build_message(ctx) is None
    ctx["mine"] = pd.DataFrame([{"SYMBOL": "AAA", "ACTION": "SL RAISE karo -> 100.00", "PRIORITY": 1}])
    msg = nt.build_message(ctx)
    assert "AAA" in msg and "SL RAISE" in msg
    ctx["buy_ok"] = False; ctx["banner"] = "DATA STALE"
    assert "BUY BAND" in nt.build_message(ctx)


def test_notify_send_needs_env_and_posts(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert nt.send("hello") is False
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t"); monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    import requests
    m = MagicMock(); m.return_value.status_code = 200
    monkeypatch.setattr(requests, "post", m)
    assert nt.send("hello") is True and m.call_args.kwargs["json"]["chat_id"] == "c"
    m.return_value.status_code = 400
    assert nt.send("hello") is False


def test_positions_tab_created_when_missing_and_never_overwritten():
    import gspread
    book = MagicMock()
    ws_new = MagicMock()
    book.worksheet.side_effect = gspread.WorksheetNotFound("x")
    book.add_worksheet.return_value = ws_new
    assert pb.read_positions_rows(book) == []
    assert ws_new.update.call_count == 1
    book2 = MagicMock(); ws = MagicMock(); ws.get_all_values.return_value = [["SYMBOL"], ["AAA"]]
    book2.worksheet.return_value = ws
    assert pb.read_positions_rows(book2) == [["SYMBOL"], ["AAA"]]
    ws.update.assert_not_called(); ws.batch_clear.assert_not_called()


def test_clean_extra_tabs_keeps_positions_tab(monkeypatch):
    monkeypatch.setenv("CLEAN_EXTRA_TABS", "1")
    book = MagicMock()
    ws = MagicMock(); ws.row_count = 500; ws.col_count = 30; ws.id = 1
    book.worksheet.return_value = ws
    tabs = []
    for t in (CFG.action_tab, "SYSTEM STATUS", "MY POSITIONS", "OLD JUNK"):
        m = MagicMock(); m.title = t; tabs.append(m)
    book.worksheets.return_value = tabs
    from test_pipeline import _ctx
    pb.publish(pb.build_action_rows(_ctx()), pb.build_status_rows(_ctx()), book=book)
    deleted = [c.args[0].title for c in book.del_worksheet.call_args_list]
    assert deleted == ["OLD JUNK"]


def test_action_rows_show_my_positions_section():
    from test_pipeline import _ctx
    ctx = _ctx()
    ctx["mine"] = pd.DataFrame([{"SYMBOL": "MYSTK", "STATE": "OPEN", "QTY": 10, "BUY PRICE": 100.0, "LAST CLOSE": 105.0, "PNL %": 5.0,
                                 "PNL RS": 50.0, "R NOW": 0.8, "SL NOW": 94.0, "T1": 112.0, "T2": 124.0, "T3": 136.0, "ACTION": "HOLD, SL 94.00"}])
    ctx["mine_sum"] = dict(deployed=1050.0, open_risk=110.0, pnl_open=50.0, dd_pct=0.0)
    ctx["mine_problems"] = ["Row 3 (X): bad"]
    rows, _ = pb.build_action_rows(ctx)
    flat_ = [str(x) for r in rows for x in r]
    assert "MYSTK" in flat_ and any("WARNING" in x for x in flat_) and len({len(r) for r in rows}) == 1


def test_publish_uses_raw_input_not_user_entered():
    """USER_ENTERED date-strings ko khud reparse kar deta hai (21-Sep-2026 -> 2026-09-21 00:00:00)
    aur us column ka date-format agle plain number par bhi chipak jaata hai (jaise 'Stocks in
    universe' 1901-05-14 dikha - real bug jo production run me mila). RAW iska fix hai - isse
    Sheets kuch bhi khud parse nahi karta."""
    from test_pipeline import _ctx
    book = MagicMock()
    ws = MagicMock(); ws.row_count = 500; ws.col_count = 30
    book.worksheet.return_value = ws
    book.worksheets.return_value = []
    pb.publish(pb.build_action_rows(_ctx()), pb.build_status_rows(_ctx()), book=book)
    for call in ws.update.call_args_list:
        assert call.kwargs.get("value_input_option") == "RAW", \
            "USER_ENTERED date-strings ko reparse karta hai -> galat format sheet me jaata hai"


def test_date_like_strings_stay_as_formatted_text_not_reparsed():
    """_v() ne jo 'DD-Mon-YYYY' banaya, wahi final row me jaana chahiye - koi ISO/raw datetime nahi."""
    ctx = __import__("test_pipeline")._ctx()
    rows, _ = pb.build_action_rows(ctx)
    flat_ = [str(x) for r in rows for x in r]
    assert not any(" 00:00:00" in x for x in flat_), "raw datetime leak - USER_ENTERED bug wapas aaya"


def test_ry_tab_lists_buys_and_urgent_sells():
    from test_pipeline import _ctx
    ctx = _ctx()
    ctx["mine"] = pd.DataFrame([
        {"SYMBOL": "SOLDOUT", "LAST CLOSE": 94.0, "SL NOW": 94.0, "ACTION": "SL HIT aaj (~94.00)", "PRIORITY": 0},
        {"SYMBOL": "HOLDER", "LAST CLOSE": 110.0, "SL NOW": 100.0, "ACTION": "HOLD, SL 100.00", "PRIORITY": 3},
    ])
    rows, marks = pb.build_ry_rows(ctx)
    flat_ = [str(x) for r in rows for x in r]
    assert any("BUY" in x for x in flat_)              # from ctx buy df
    assert "SOLDOUT" in flat_ and "SELL" in flat_
    assert "HOLDER" not in flat_                        # HOLD wala SELL me nahi aana chahiye
    assert len({len(r) for r in rows}) == 1


def test_ry_tab_empty_says_no_buy_sell():
    from test_pipeline import _ctx
    ctx = _ctx()
    ctx["buy_ok"] = False
    ctx["mine"] = pd.DataFrame(columns=ps.EVAL_COLS)
    rows, _ = pb.build_ry_rows(ctx)
    flat_ = [str(x) for r in rows for x in r]
    assert any("koi BUY ya SELL nahi" in x for x in flat_)


def test_publish_writes_ry_tab_and_keeps_it_on_clean(monkeypatch):
    monkeypatch.setenv("CLEAN_EXTRA_TABS", "1")
    from test_pipeline import _ctx
    ctx = _ctx()
    book = MagicMock()
    ws = MagicMock(); ws.row_count = 500; ws.col_count = 30; ws.id = 1
    book.worksheet.return_value = ws
    tabs = []
    for t in (CFG.action_tab, "SYSTEM STATUS", "MY POSITIONS", "RY", "JUNK"):
        m = MagicMock(); m.title = t; tabs.append(m)
    book.worksheets.return_value = tabs
    pb.publish(pb.build_action_rows(ctx), pb.build_status_rows(ctx), pb.build_ry_rows(ctx), book=book)
    titles_written = [c.args[1] for c in book.worksheet.call_args_list] if False else None
    deleted = [c.args[0].title for c in book.del_worksheet.call_args_list]
    assert deleted == ["JUNK"]
    assert book.worksheet.call_count >= 3   # action, status, ry


def test_v38_tab_lists_setup_and_pf_caveat():
    from test_pipeline import _ctx
    rows, marks = pb.build_v38_rows(_ctx())
    flat_ = [str(x) for r in rows for x in r]
    assert "VVV" in flat_ and "STRONG BREAKOUT" in flat_
    assert any("1.30" in x for x in flat_)          # honest PF caveat present


def test_v38_tab_empty_says_no_signal():
    from test_pipeline import _ctx
    ctx = _ctx()
    ctx["buy_v38"] = pd.DataFrame()
    rows, _ = pb.build_v38_rows(ctx)
    flat_ = [str(x) for r in rows for x in r]
    assert any("koi V38 signal nahi" in x for x in flat_)


def test_publish_writes_v38_tab_and_keeps_it_on_clean(monkeypatch):
    monkeypatch.setenv("CLEAN_EXTRA_TABS", "1")
    from test_pipeline import _ctx
    ctx = _ctx()
    book = MagicMock()
    ws = MagicMock(); ws.row_count = 500; ws.col_count = 30; ws.id = 1
    book.worksheet.return_value = ws
    tabs = []
    for t in (CFG.action_tab, "SYSTEM STATUS", "MY POSITIONS", "RY", "RY V38", "JUNK"):
        m = MagicMock(); m.title = t; tabs.append(m)
    book.worksheets.return_value = tabs
    pb.publish(pb.build_action_rows(ctx), pb.build_status_rows(ctx), pb.build_ry_rows(ctx), pb.build_v38_rows(ctx), book=book)
    deleted = [c.args[0].title for c in book.del_worksheet.call_args_list]
    assert deleted == ["JUNK"]
    assert book.worksheet.call_count >= 4   # action, status, ry, v38


def test_ry_tab_includes_v38_tier_too():
    from test_pipeline import _ctx
    rows, _ = pb.build_ry_rows(_ctx())
    flat_ = [str(x) for r in rows for x in r]
    assert "VVV" in flat_ and "BUY (V38)" in flat_
    assert any("1.30" in x for x in flat_)   # PF caveat visible in RY tab too


def test_ry_tab_v38_row_has_no_t3():
    from test_pipeline import _ctx
    rows, marks = pb.build_ry_rows(_ctx())
    hdr_i = marks["header"][0]
    header = rows[hdr_i]
    v38_row = next(r for r in rows if "VVV" in r)
    t3_col = header.index("T3 (6R)")
    assert v38_row[t3_col] == ""


def test_ry_tab_includes_v42_tier_too():
    from test_pipeline import _ctx
    rows, _ = pb.build_ry_rows(_ctx())
    flat_ = [str(x) for r in rows for x in r]
    assert "UUU" in flat_ and any("BUY (V42" in x for x in flat_)
    assert any("1.19" in x for x in flat_)   # PF caveat visible in RY tab too


def test_v42_tab_lists_entry_type_score_and_pf_caveat():
    from test_pipeline import _ctx
    rows, marks = pb.build_v42_rows(_ctx())
    flat_ = [str(x) for r in rows for x in r]
    assert "UUU" in flat_ and "APEX BUY" in flat_ and "91" in flat_
    assert any("1.19" in x for x in flat_)


def test_v42_tab_empty_says_no_signal():
    from test_pipeline import _ctx
    ctx = _ctx()
    ctx["buy_v42"] = pd.DataFrame()
    rows, _ = pb.build_v42_rows(ctx)
    flat_ = [str(x) for r in rows for x in r]
    assert any("koi V42 signal nahi" in x for x in flat_)


def test_publish_writes_v42_tab_and_keeps_it_on_clean(monkeypatch):
    monkeypatch.setenv("CLEAN_EXTRA_TABS", "1")
    from test_pipeline import _ctx
    ctx = _ctx()
    book = MagicMock()
    ws = MagicMock(); ws.row_count = 500; ws.col_count = 30; ws.id = 1
    book.worksheet.return_value = ws
    tabs = []
    for t in (CFG.action_tab, "SYSTEM STATUS", "MY POSITIONS", "RY", "RY V38", "RY V42", "JUNK"):
        m = MagicMock(); m.title = t; tabs.append(m)
    book.worksheets.return_value = tabs
    pb.publish(pb.build_action_rows(ctx), pb.build_status_rows(ctx), pb.build_ry_rows(ctx),
               pb.build_v38_rows(ctx), pb.build_v42_rows(ctx), book=book)
    deleted = [c.args[0].title for c in book.del_worksheet.call_args_list]
    assert deleted == ["JUNK"]
    assert book.worksheet.call_count >= 5   # action, status, ry, v38, v42

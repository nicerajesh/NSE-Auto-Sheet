"""Google Sheet publisher - sirf 2 tab: ACTION PLAN aur SYSTEM STATUS.

Rows pehle plain python lists me banti hain (testable), phir ek-ek update call me likhi jaati hain.
429/5xx par exponential backoff. Extra tabs tab tak nahi hatate jab tak CLEAN_EXTRA_TABS=1 na ho.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime

import numpy as np
import pandas as pd

from config import CFG


def _v(x):
    if x is None:
        return ""
    if isinstance(x, (pd.Timestamp, datetime)):
        return x.strftime("%d-%b-%Y")
    if isinstance(x, (np.floating, float)):
        return "" if not np.isfinite(x) else round(float(x), 2)
    if isinstance(x, (np.integer,)):
        return int(x)
    try:
        if pd.isna(x):
            return ""
    except Exception:  # noqa: BLE001
        pass
    return x


def _pad(rows: list[list], width: int) -> list[list]:
    return [[_v(x) for x in r] + [""] * (width - len(r)) for r in rows]


# --------------------------------------------------------------------------- ACTION PLAN
def build_action_rows(ctx: dict) -> tuple[list[list], dict]:
    """ctx keys: asof, banner, buy_ok, mult, health_label, buy(df), watch(df), open(df), slots_free"""
    rows: list[list] = []
    marks = {"title": [], "header": []}

    def add(r, kind=None):
        rows.append(r)
        if kind:
            marks[kind].append(len(rows) - 1)

    add([f"RY APEX v2 | Data: {ctx['asof']:%d-%b-%Y} | {ctx['banner']}"], "title")
    add([f"Size multiplier {ctx.get('mult_total', ctx['mult'])}x ({ctx['health_label']}; stage {CFG.stage_pct:.0f}%) | "
         f"Free slots {ctx['slots_free']}/{CFG.max_positions} | Capital Rs {CFG.capital:,.0f} | Risk/trade {CFG.risk_per_trade_pct}%"])
    add([""])

    mine = ctx.get("mine")
    add(["A) MERI POSITIONS - AAJ KA KAAM (SL order broker me tum khud update karo)"], "title")
    add(["STOCK", "STATE", "QTY", "BUY PRICE", "LAST CLOSE", "P&L %", "P&L Rs", "R NOW", "CURRENT SL", "T1", "T2", "T3", "ACTION"], "header")
    if mine is not None and not mine.empty:
        for _, r in mine.iterrows():
            add([r["SYMBOL"], r["STATE"], r["QTY"], r["BUY PRICE"], r["LAST CLOSE"], r["PNL %"], r["PNL RS"], r["R NOW"],
                 r["SL NOW"], r["T1"], r["T2"], r["T3"], r["ACTION"]])
        ms = ctx.get("mine_sum") or {}
        add([f"TOTAL: deployed Rs {ms.get('deployed', 0):,.0f} | open risk Rs {ms.get('open_risk', 0):,.0f} "
             f"({ms.get('open_risk', 0) / CFG.capital * 100:.1f}% of capital, limit {CFG.max_open_risk_pct}%) | "
             f"unrealized P&L Rs {ms.get('pnl_open', 0):,.0f} ({ms.get('dd_pct', 0):.1f}%)"])
    else:
        add([f"Koi position nahi. Kharidne ke baad '{CFG.positions_tab}' tab me row daalo (SYMBOL, BUY DATE, BUY PRICE, QTY)."])
    for msg in ctx.get("mine_problems") or []:
        add(["WARNING: " + msg])
    add([""])

    add(["B) NAYE BUY - agle session ke OPEN par kharido (open signal close se 2% se upar ho to SKIP)"], "title")
    hdr = ["#", "STOCK", "SETUP", "BUY PRICE (approx)", "MAX BUY", "STOP LOSS", "T1 (2R)", "T2 (4R)", "T3 (6R)",
           "RISK %", "QTY", "CAPITAL Rs", "RISK Rs", "MOMENTUM RANK", "EXIT PLAN"]
    add(hdr, "header")
    buy = ctx["buy"]
    if ctx["buy_ok"] and buy is not None and not buy.empty:
        for i, (_, r) in enumerate(buy.head(CFG.max_new_per_day).iterrows(), 1):
            plan = ("T1 touch -> SL entry par | T2 touch -> SL T1 par | T3 touch -> SL T2 par. "
                    "Koi fixed target nahi; SL hit hone tak hold (max 90 din).")
            add([i, r["SYMBOL"], r["SETUP"], r["CLOSE"], r["CLOSE"] * (1 + CFG.max_gap_pct / 100), r["STOP"], r["T1"],
                 r["T2"], r["T3"], r["RISK_PCT"], r["QTY"], r["CAPITAL_USED"], r["RISK_AMT"], r["MOM_RANK"], plan])
    else:
        add(["", "KOI NAYA BUY NAHI" if ctx["buy_ok"] else "BUY BAND: " + ctx["banner"]])
    add([""])

    add(["B2) WATCH BUY - dhila filter, roz aane ki koshish karta hai (backtest PF ~1.7, strict wale ~2.2 se KAM). "
         "Size jaan-bujhkar aadha hai. Ye 'kuch dikhane ke liye' list hai, guaranteed edge nahi."], "title")
    add(hdr, "header")
    bw = ctx.get("buy_watch")
    if ctx["buy_ok"] and bw is not None and not bw.empty:
        for i, (_, r) in enumerate(bw.iterrows(), 1):
            plan = "T1/T2/T3 ka staircase SL - jaisa strict BUY me hai. Size aadha rakha gaya hai (kam PF ki wajah se)."
            add([i, r["SYMBOL"], r["SETUP"], r["CLOSE"], r["CLOSE"] * (1 + CFG.max_gap_pct / 100), r["STOP"], r["T1"],
                 r["T2"], r["T3"], r["RISK_PCT"], r["QTY"], r["CAPITAL_USED"], r["RISK_AMT"], r["MOM_RANK"], plan])
    else:
        add(["", "Aaj koi WATCH BUY bhi nahi (bahut kamzor din)" if ctx["buy_ok"] else "BUY BAND: " + ctx["banner"]])
    add([""])

    add(["C) PAPER SIGNALS - system ke published signals ka scoreboard (real trade nahi; sirf evidence ke liye)"], "title")
    add(["STOCK", "STATE", "SIGNAL DATE", "ENTRY", "CURRENT SL", "LAST CLOSE", "R SO FAR", "ACTION"], "header")
    op = ctx["open"]
    if op is not None and not op.empty:
        for _, r in op.iterrows():
            add([r["STOCK"], r["STATE"], r["SIGNAL DATE"], r["ENTRY"], r["CURRENT SL"], r["LAST CLOSE"], r["R SO FAR"], r["ACTION"]])
    else:
        add(["Abhi koi open signal nahi"])
    add([""])

    add(["D) WATCHLIST - jitna kam DIST TO TRIGGER, utna paas (koi guarantee nahi - roz ka sirf naya data hai, kal ka nahi)"], "title")
    add(["STOCK", "CLOSE", "TRIGGER (breakout)", "DIST TO TRIGGER %", "RANGE TIGHT (0-100)", "MOMENTUM RANK", "EMA20 (pullback zone)", "RSI"], "header")
    w = ctx["watch"]
    if w is not None and not w.empty:
        for _, r in w.head(CFG.watch_rows).iterrows():
            add([r["SYMBOL"], r["CLOSE"], r["TRIGGER"], r["DIST_TO_TRIGGER_PCT"], r["RANGE_TIGHTNESS"], r["MOM_RANK"], r["EMA20"], r["RSI"]])
    else:
        add(["Watchlist khaali"])
    width = max(len(r) for r in rows)
    return _pad(rows, width), marks


# --------------------------------------------------------------------------- RY (quick view)
def build_ry_rows(ctx: dict) -> tuple[list[list], dict]:
    """Ek-nazar tab: sirf aaj ka BUY ya SELL, entry/exit price, SL, T1/T2/T3. Baaki detail ACTION PLAN me hai."""
    rows: list[list] = []
    marks = {"title": [], "header": []}

    def add(r, kind=None):
        rows.append(r)
        if kind:
            marks[kind].append(len(rows) - 1)

    add([f"RY | Data: {ctx['asof']:%d-%b-%Y} | {ctx['banner']}"], "title")
    add(["STOCK", "SIGNAL", "PRICE", "STOP LOSS", "T1 (2R)", "T2 (4R)", "T3 (6R)", "NOTE"], "header")

    any_row = False
    buy = ctx.get("buy")
    if ctx.get("buy_ok") and buy is not None and not buy.empty:
        for _, r in buy.head(CFG.max_new_per_day).iterrows():
            add([r["SYMBOL"], "BUY", r["CLOSE"], r["STOP"], r["T1"], r["T2"], r["T3"],
                 "Kal OPEN par kharido (gap>2% ho to skip)"])
            any_row = True

    bw = ctx.get("buy_watch")
    if ctx.get("buy_ok") and bw is not None and not bw.empty:
        for _, r in bw.iterrows():
            add([r["SYMBOL"], "BUY (WATCH)", r["CLOSE"], r["STOP"], r["T1"], r["T2"], r["T3"],
                 "Dhila signal, PF kam (~1.7) - size aadha"])
            any_row = True

    mine = ctx.get("mine")
    if mine is not None and not mine.empty:
        sell = mine[mine["PRIORITY"] == 0] if "PRIORITY" in mine else mine.iloc[0:0]
        for _, r in sell.iterrows():
            add([r["SYMBOL"], "SELL", r.get("LAST CLOSE", ""), r.get("SL NOW", ""), "", "", "", r["ACTION"]])
            any_row = True

    if not any_row:
        add(["", "Aaj koi BUY ya SELL nahi", "", "", "", "", "", ""])

    width = max(len(r) for r in rows)
    return _pad(rows, width), marks
def build_status_rows(ctx: dict) -> tuple[list[list], dict]:
    rows: list[list] = []
    marks = {"title": [], "header": []}

    def add(r, kind=None):
        rows.append(r)
        if kind:
            marks[kind].append(len(rows) - 1)

    s, sb = ctx["bt"], ctx["score"]
    add(["SYSTEM STATUS"], "title")
    add(["Data date", ctx["asof"]])
    add(["Stocks in universe", ctx["n_symbols"]])
    add(["History (sessions)", ctx["n_sessions"]])
    add(["Signal verdict", ctx["banner"]])
    add(["Recent health (last %d din)" % CFG.health_window_days, f"{ctx['health']['label']} | closed trades {ctx['health']['n']} | avg R {ctx['health']['avg_r']}"])
    add(["Market breadth", f"{ctx['breadth50']:.0f}% stocks > EMA50 | {ctx['breadth200']:.0f}% > EMA200"])
    add([""])
    add(["BACKTEST (real NSE data, 2019 se, same engine)"], "title")
    add(["Trades", "Win %", "Avg R", "Avg ret %", "Median ret %", "Profit factor", "Max losing streak"], "header")
    add([s["trades"], s["win_pct"], s["avg_r"], s["avg_ret"], s["median_ret"], s["pf"], s["max_loss_streak"]])
    add([""])
    add(["Saal-wise (exit year)"], "title")
    add(["Year", "Trades", "Win %", "Avg R", "Profit factor"], "header")
    for _, r in ctx["by_year"].iterrows():
        add([int(r["YEAR"]), r["trades"], r["win_pct"], r["avg_r"], r["pf"]])
    add([""])
    add(["LIVE SCOREBOARD (jo signals is system ne publish kiye)"], "title")
    add(["Closed", "Active/Pending", "Win %", "Avg R", "Profit factor"], "header")
    add([sb["closed"], sb["active"], sb["win_pct"], sb["avg_r"], sb["pf"]])
    add([""])
    add(["SACH (padh lo)"], "title")
    for line in ctx["notes"]:
        add([line])
    width = max(len(r) for r in rows)
    return _pad(rows, width), marks


# --------------------------------------------------------------------------- Google Sheets I/O
def _retry(fn, *a, **k):
    import gspread
    delay = 5
    for attempt in range(6):
        try:
            return fn(*a, **k)
        except gspread.exceptions.APIError as e:
            code = getattr(getattr(e, "response", None), "status_code", 0)
            if code in (429, 500, 502, 503) and attempt < 5:
                print(f"Sheets API {code}: {delay}s wait, retry {attempt + 1}")
                time.sleep(delay)
                delay = min(delay * 3, 90)
                continue
            raise


def _write_tab(book, title: str, rows: list[list], marks: dict) -> None:
    import gspread
    try:
        ws = _retry(book.worksheet, title)
    except gspread.WorksheetNotFound:
        ws = _retry(book.add_worksheet, title=title, rows=max(100, len(rows) + 20), cols=max(20, len(rows[0]) + 2))
    if ws.row_count < len(rows) + 5:
        _retry(ws.add_rows, len(rows) + 5 - ws.row_count)
    if ws.col_count < len(rows[0]):
        _retry(ws.add_cols, len(rows[0]) - ws.col_count)
    _retry(ws.batch_clear, ["A1:Z1000"])          # bare ws.clear() spaces wali sheet names par fail hota tha
    # RAW zaroori hai: USER_ENTERED hamari date-strings ("21-Sep-2026") ko khud reparse karke
    # apne default datetime format me badal deta tha, aur us column ka date-format agle plain
    # number (jaise stock count) par bhi chipak jaata tha -> "1901-05-14" jaisा bekar output.
    _retry(ws.update, values=rows, range_name="A1", value_input_option="RAW")
    reqs = []
    for i in marks.get("title", []):
        reqs.append({"repeatCell": {"range": {"sheetId": ws.id, "startRowIndex": i, "endRowIndex": i + 1},
                                    "cell": {"userEnteredFormat": {"textFormat": {"bold": True, "fontSize": 11}}},
                                    "fields": "userEnteredFormat.textFormat"}})
    for i in marks.get("header", []):
        reqs.append({"repeatCell": {"range": {"sheetId": ws.id, "startRowIndex": i, "endRowIndex": i + 1},
                                    "cell": {"userEnteredFormat": {"textFormat": {"bold": True},
                                                                   "backgroundColor": {"red": 0.9, "green": 0.93, "blue": 0.98}}},
                                    "fields": "userEnteredFormat(textFormat,backgroundColor)"}})
    if reqs:
        _retry(book.batch_update, {"requests": reqs})


def open_book(creds_json: str | None = None):
    """GCP_CREDENTIALS se spreadsheet kholo. Creds na ho to None (tab CSV-only mode)."""
    import gspread
    creds_json = creds_json or os.getenv("GCP_CREDENTIALS")
    if not creds_json:
        return None
    gc = gspread.service_account_from_dict(json.loads(creds_json))
    return _retry(gc.open_by_key, CFG.spreadsheet_id)


def read_positions_rows(book) -> list[list]:
    """MY POSITIONS tab ki raw rows. Tab na ho to header ke saath bana do (kabhi overwrite nahi)."""
    import gspread
    try:
        ws = _retry(book.worksheet, CFG.positions_tab)
    except gspread.WorksheetNotFound:
        ws = _retry(book.add_worksheet, title=CFG.positions_tab, rows=200, cols=10)
        _retry(ws.update, values=[["SYMBOL", "BUY DATE", "BUY PRICE", "QTY", "MY STOP", "NOTES", "",
                                   "<- apne asli trades yahan likho: date dd-mm-yyyy, price/qty number. MY STOP optional (khali = 2 ATR)."]],
               range_name="A1")
        return []
    return _retry(ws.get_all_values)


def publish(action: tuple, status: tuple, ry: tuple | None = None, creds_json: str | None = None, book=None) -> bool:
    """book inject ho sakta hai (tests). Warna GCP_CREDENTIALS se gspread client banta hai."""
    import gspread
    if book is None:
        book = open_book(creds_json)
        if book is None:
            print("PUBLISH SKIPPED: GCP_CREDENTIALS set nahi (sirf CSV output bana)")
            return False
    _write_tab(book, CFG.action_tab, *action)
    _write_tab(book, CFG.status_tab, *status)
    if ry is not None:
        _write_tab(book, CFG.ry_tab, *ry)
    if os.getenv("CLEAN_EXTRA_TABS", "0") == "1":
        keep = {CFG.action_tab, CFG.status_tab, CFG.positions_tab, CFG.ry_tab}
        for ws in _retry(book.worksheets):
            if ws.title not in keep:
                try:
                    _retry(book.del_worksheet, ws)
                    time.sleep(1.5)
                except Exception as e:  # noqa: BLE001
                    print("extra tab delete warning:", ws.title, e)
    print("PUBLISHED: ACTION PLAN + SYSTEM STATUS + RY")
    return True

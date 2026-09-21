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
    add([f"Size multiplier {ctx['mult']}x ({ctx['health_label']}) | Free slots {ctx['slots_free']}/{CFG.max_positions} | "
         f"Capital Rs {CFG.capital:,.0f} | Risk/trade {CFG.risk_per_trade_pct}%"])
    add([""])

    add(["A) NAYE BUY - agle session ke OPEN par kharido (open signal close se 2% se upar ho to SKIP)"], "title")
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

    add(["B) OPEN SIGNALS - pichhle published signals ka status (SL raise / hold / exit)"], "title")
    add(["STOCK", "STATE", "SIGNAL DATE", "ENTRY", "CURRENT SL", "LAST CLOSE", "R SO FAR", "ACTION"], "header")
    op = ctx["open"]
    if op is not None and not op.empty:
        for _, r in op.iterrows():
            add([r["STOCK"], r["STATE"], r["SIGNAL DATE"], r["ENTRY"], r["CURRENT SL"], r["LAST CLOSE"], r["R SO FAR"], r["ACTION"]])
    else:
        add(["Abhi koi open signal nahi"])
    add([""])

    add(["C) WATCHLIST - top momentum leaders jinka trigger abhi nahi bana (BUY nahi, sirf nazar rakho)"], "title")
    add(["STOCK", "CLOSE", "MOMENTUM RANK", "EMA20 (pullback zone)", "20-DIN HIGH (breakout level)", "RSI"], "header")
    w = ctx["watch"]
    if w is not None and not w.empty:
        for _, r in w.head(CFG.watch_rows).iterrows():
            add([r["SYMBOL"], r["CLOSE"], r["MOM_RANK"], r["EMA20"], r["HH20"], r["RSI"]])
    else:
        add(["Watchlist khaali"])
    width = max(len(r) for r in rows)
    return _pad(rows, width), marks


# --------------------------------------------------------------------------- SYSTEM STATUS
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
    _retry(ws.update, values=rows, range_name="A1", value_input_option="USER_ENTERED")
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


def publish(action: tuple, status: tuple, creds_json: str | None = None, book=None) -> bool:
    """book inject ho sakta hai (tests). Warna GCP_CREDENTIALS se gspread client banta hai."""
    import gspread
    if book is None:
        creds_json = creds_json or os.getenv("GCP_CREDENTIALS")
        if not creds_json:
            print("PUBLISH SKIPPED: GCP_CREDENTIALS set nahi (sirf CSV output bana)")
            return False
        gc = gspread.service_account_from_dict(json.loads(creds_json))
        book = _retry(gc.open_by_key, CFG.spreadsheet_id)
    _write_tab(book, CFG.action_tab, *action)
    _write_tab(book, CFG.status_tab, *status)
    if os.getenv("CLEAN_EXTRA_TABS", "0") == "1":
        keep = {CFG.action_tab, CFG.status_tab}
        for ws in _retry(book.worksheets):
            if ws.title not in keep:
                try:
                    _retry(book.del_worksheet, ws)
                    time.sleep(1.5)
                except Exception as e:  # noqa: BLE001
                    print("extra tab delete warning:", ws.title, e)
    print("PUBLISHED: ACTION PLAN + SYSTEM STATUS")
    return True

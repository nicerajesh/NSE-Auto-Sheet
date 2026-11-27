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
           "RISK %", "QTY", "CAPITAL Rs", "RISK Rs", "MOMENTUM RANK",
           "T1 MOVE %", "T2 MOVE %", "T3 MOVE %", "HIST SAMPLE (2023+)", "HIST WIN % (2023+)",
           "HIST AVG NET % (2023+)", "MEDIAN HOLD (SESSIONS)", "2025+ AVG NET %", "EXIT PLAN"]
    add(hdr, "header")
    buy = ctx["buy"]
    if ctx["buy_ok"] and buy is not None and not buy.empty:
        for i, (_, r) in enumerate(buy.head(CFG.max_new_per_day).iterrows(), 1):
            plan = ("T1 touch -> SL entry par | T2 touch -> SL T1 par | T3 touch -> SL T2 par. "
                    "Koi fixed target nahi; SL hit hone tak hold (max 90 din).")
            add([i, r["SYMBOL"], r["SETUP"], r["CLOSE"], r["CLOSE"] * (1 + CFG.max_gap_pct / 100), r["STOP"], r["T1"],
                 r["T2"], r["T3"], r["RISK_PCT"], r["QTY"], r["CAPITAL_USED"], r["RISK_AMT"], r["MOM_RANK"],
                 r.get("T1_MOVE_PCT", ""), r.get("T2_MOVE_PCT", ""), r.get("T3_MOVE_PCT", ""),
                 r.get("HIST_SAMPLE_2023_PLUS", ""), r.get("HIST_WIN_PCT_2023_PLUS", ""),
                 r.get("HIST_AVG_RETURN_PCT_2023_PLUS", ""), r.get("HIST_MEDIAN_HOLD_SESSIONS", ""),
                 r.get("HIST_2025_PLUS_AVG_RETURN_PCT", ""), plan])
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
                 r["T2"], r["T3"], r["RISK_PCT"], r["QTY"], r["CAPITAL_USED"], r["RISK_AMT"], r["MOM_RANK"],
                 r.get("T1_MOVE_PCT", ""), r.get("T2_MOVE_PCT", ""), r.get("T3_MOVE_PCT", ""),
                 r.get("HIST_SAMPLE_2023_PLUS", ""), r.get("HIST_WIN_PCT_2023_PLUS", ""),
                 r.get("HIST_AVG_RETURN_PCT_2023_PLUS", ""), r.get("HIST_MEDIAN_HOLD_SESSIONS", ""),
                 r.get("HIST_2025_PLUS_AVG_RETURN_PCT", ""), plan])
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
    add([""])
    add(["E) MULTI-STRATEGY HUNTER - RADAR ONLY; ye validated BUY nahi, next-session confirmation zaroori"], "title")
    add(["STOCK", "SETUP(S)", "CLOSE", "ENTRY GUIDE", "STOP LOSS", "T1 (2R)", "T2 (3R)",
         "VOLUME X", "52W LOW SE %", "52W HIGH SE %", "SCORE /100", "RSI", "STATUS"], "header")
    radar = ctx.get("opportunity_radar")
    if ctx.get("buy_ok") and radar is not None and not radar.empty:
        for _, r in radar.iterrows():
            add([r["SYMBOL"], r["SETUP"], r["CLOSE"], r["ENTRY_GUIDE"], r["STOP_LOSS"], r["T1_2R"],
                 r["T2_3R"], r["VOLUME_RATIO"], r["LOW52W_DIST_PCT"], r["HIGH52W_DIST_PCT"],
                 r["SCORE"], r["RSI"], r["STATUS"]])
    else:
        add(["", "Aaj koi qualified radar setup nahi" if ctx.get("buy_ok") else "BUY BAND: " + ctx.get("banner", "")])
    add([""])
    add(["F) MULTI-STRATEGY HISTORICAL SCREEN - simplified next-open / 2-ATR stop / 20-session exit; costs 0.35%; research only"], "title")
    add(["STRATEGY", "TRADES", "WIN %", "AVG NET %", "MEDIAN NET %", "PF FULL", "OOS TRADES (2023+)", "OOS WIN %", "OOS AVG NET %", "OOS PF (2023+)"], "header")
    stats = ctx.get("opportunity_stats")
    if stats is not None and not stats.empty:
        for _, r in stats.iterrows():
            add([r["SETUP"], r["TRADES"], r["WIN_PCT"], r["AVG_NET_PCT"], r["MEDIAN_NET_PCT"], r["PROFIT_FACTOR"], r["OOS_TRADES_2023_PLUS"], r["OOS_WIN_PCT_2023_PLUS"], r["OOS_AVG_NET_PCT_2023_PLUS"], r["OOS_PROFIT_FACTOR_2023_PLUS"]])
    else:
        add(["Abhi historical sample nahi"])

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

    bv = ctx.get("buy_v38")
    if ctx.get("buy_ok") and bv is not None and not bv.empty:
        for _, r in bv.iterrows():
            add([r["SYMBOL"], "BUY (V38)", r["CLOSE"], r["STOP"], r["T1"], r["T2"], "",
                 f"Pine V38 signal ({r['V38_SETUP']}) - PF sabse kam (~1.30), size sabse chhota. Detail: RY V38 tab"])
            any_row = True

    b42 = ctx.get("buy_v42")
    if ctx.get("buy_ok") and b42 is not None and not b42.empty:
        for _, r in b42.iterrows():
            add([r["SYMBOL"], f"BUY (V42 {r['V42_ENTRY_TYPE']})", r["CLOSE"], r["STOP"], r["T1"], r["T2"], "",
                 f"Pine V42 signal, score {r['V42_SCORE']}/100 - PF sabse kam (~1.19), size sabse chhota. Detail: RY V42 tab"])
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
    width = max(len(r) for r in rows)
    return _pad(rows, width), marks


# --------------------------------------------------------------------------- RY V38 (Pine Script tier)
def build_v38_rows(ctx: dict) -> tuple[list[list], dict]:
    """Pine Script 'RY APEX MATRIX V38' ka hoobehoo signal - koi trend/momentum/ADX filter nahi.
    Backtest (production code, 2019-2026, 448 stocks, proper 1-trade-at-a-time per stock):
    n=8344, win=37.1%, PF=1.30. Ye sabse kamzor tier hai (strict ~2.2, WATCH ~1.7) - isliye
    size sabse chhota (v38_size_mult) aur alag sheet, taaki strict BUY ke saath mix na ho."""
    rows: list[list] = []
    marks = {"title": [], "header": []}

    def add(r, kind=None):
        rows.append(r)
        if kind:
            marks[kind].append(len(rows) - 1)

    add([f"RY V38 | Data: {ctx['asof']:%d-%b-%Y} | Pine Script V38 ka hoobehoo signal - koi trend/momentum/ADX filter nahi"], "title")
    add(["Backtest (2019-2026, 448 stocks): win 37.1%, Profit Factor 1.30 - strict BUY tab (PF ~2.2) se KAM. "
         "Size jaan-bujhkar sabse chhota rakha gaya hai."])
    add(["STOCK", "SETUP", "PRICE", "STOP LOSS (trailing, roz update)", "T1 (2R, dikhane ke liye)",
         "T2 (3R, dikhane ke liye)", "RISK %", "QTY", "CAPITAL Rs", "RISK Rs"], "header")
    bv = ctx.get("buy_v38")
    if ctx.get("buy_ok") and bv is not None and not bv.empty:
        for _, r in bv.iterrows():
            add([r["SYMBOL"], r["V38_SETUP"], r["CLOSE"], r["STOP"], r["T1"], r["T2"], r["RISK_PCT"],
                 r["QTY"], r["CAPITAL_USED"], r["RISK_AMT"]])
    else:
        add(["", "Aaj koi V38 signal nahi" if ctx.get("buy_ok") else "BUY BAND: " + ctx.get("banner", ""), "", "", "", "", "", "", "", ""])
    add([""])
    add(["NOTE: SL yahan roz update hoti hai (close - 2.5xATR, sirf upar). T1/T2 sirf reference hain - "
         "Pine V38 me bhi ye SL ko affect nahi karte. Exit jab close SL se neeche jaaye."])

    width = max(len(r) for r in rows)
    return _pad(rows, width), marks


# --------------------------------------------------------------------------- RY V42 (Pine Script tier)
def build_v42_rows(ctx: dict) -> tuple[list[list], dict]:
    """Pine Script 'RY APEX MATRIX V42 - PRO SWING ENGINE' ka hoobehoo signal.
    NOTE: V42 ka Market Regime aur Relative Strength NIFTY index se calculate hote hain. Yahan
    NIFTY index ka seedha data available nahi, isliye apna equal-weight universe proxy use kiya
    gaya hai (concept wahi, NIFTY ki jagah). Baaki - score engine, VCP/compression, teen BUY tier
    (APEX/TACTICAL/BUY), chhe exit conditions - Pine V42 jaisa hi hai.
    Backtest (production code, proper state machine + 5-bar cooldown, 2019-2026, 448 stocks):
    n=6653, win=35.1%, PF=1.19. Sabse kamzor tier - size sabse chhota."""
    rows: list[list] = []
    marks = {"title": [], "header": []}

    def add(r, kind=None):
        rows.append(r)
        if kind:
            marks[kind].append(len(rows) - 1)

    add([f"RY V42 | Data: {ctx['asof']:%d-%b-%Y} | Pine Script V42 ka hoobehoo signal (NIFTY ki jagah apna universe-regime proxy)"], "title")
    add(["Backtest (2019-2026, 448 stocks): win 35.1%, Profit Factor 1.19 - sabse kamzor teeno V-tier me. "
         "Size jaan-bujhkar sabse chhota rakha gaya hai."])
    add(["STOCK", "ENTRY TYPE", "APEX SCORE", "PRICE", "STOP LOSS (trailing, roz update)", "T1 (2R)", "T2 (3R)",
         "RISK %", "QTY", "CAPITAL Rs", "RISK Rs"], "header")
    bv = ctx.get("buy_v42")
    if ctx.get("buy_ok") and bv is not None and not bv.empty:
        for _, r in bv.iterrows():
            add([r["SYMBOL"], r["V42_ENTRY_TYPE"], r["V42_SCORE"], r["CLOSE"], r["STOP"], r["T1"], r["T2"],
                 r["RISK_PCT"], r["QTY"], r["CAPITAL_USED"], r["RISK_AMT"]])
    else:
        add(["", "Aaj koi V42 signal nahi" if ctx.get("buy_ok") else "BUY BAND: " + ctx.get("banner", ""), "", "", "", "", "", "", "", "", ""])
    add([""])
    add(["NOTE: Exit chhe condition me se koi bhi pehle trigger ho (trailing SL / EMA20 break / EMA50 break / "
         "trend reversal / distribution / momentum fail). T1/T2 sirf reference hain, SL ko affect nahi karte."])

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
    add(["Recent health (last %d din)" % CFG.health_window_days, f"{ctx['health']['label']} | closed trades {ctx['health']['n']} | avg R {_v(ctx['health']['avg_r']) or 'n/a'}"])
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


def publish(action: tuple, status: tuple, ry: tuple | None = None, v38: tuple | None = None,
            v42: tuple | None = None, creds_json: str | None = None, book=None) -> bool:
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
    if v38 is not None:
        _write_tab(book, CFG.v38_tab, *v38)
    if v42 is not None:
        _write_tab(book, CFG.v42_tab, *v42)
    if os.getenv("CLEAN_EXTRA_TABS", "0") == "1":
        keep = {CFG.action_tab, CFG.status_tab, CFG.positions_tab, CFG.delivery_tab, CFG.intraday_tab,
                CFG.ry_tab, CFG.v38_tab, CFG.v42_tab}
        for ws in _retry(book.worksheets):
            if ws.title not in keep:
                try:
                    _retry(book.del_worksheet, ws)
                    time.sleep(1.5)
                except Exception as e:  # noqa: BLE001
                    print("extra tab delete warning:", ws.title, e)
    print(f"PUBLISHED: {CFG.action_tab} + {CFG.status_tab}" + (" + research tabs" if (ry or v38 or v42) else ""))
    return True

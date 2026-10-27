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


    # Decision-first summary: only V43 candidates that passed the existing safety gates.
    qs_simple = ctx.get("qp_summary") or {}
    qbuy_simple = ctx.get("buy_v43")
    add(["AAJ KA SIMPLE DECISION"], "title")
    if not ctx.get("buy_ok"):
        add(["WAIT - abhi BUY nahi", ctx.get("banner", "Safety gate active")])
    elif qbuy_simple is not None and not qbuy_simple.empty:
        add(["CHECK V43 BUY CANDIDATES - next session OPEN par; MAX BUY se upar ho to SKIP"])
        add(["STOCK", "ENTRY REF", "MAX BUY", "STOP LOSS", "T1", "T2", "T3", "QTY", "V43 T1 HIT %", "V43 T2 HIT %", "V43 T3 HIT %"], "header")
        sample = int(qs_simple.get("trades", 0) or 0)
        for _, qr in qbuy_simple.head(3).iterrows():
            rates = [qs_simple.get("t1_hit_pct"), qs_simple.get("t2_hit_pct"), qs_simple.get("t3_hit_pct")]
            rate_text = rates if sample >= 30 else ["LOW SAMPLE"] * 3
            add([qr["SYMBOL"], qr["CLOSE"], qr["QP_MAX_BUY"], qr["STOP"], qr["T1"], qr["T2"], qr["T3"], qr.get("QTY", ""),
                 *rate_text])
        add([f"Target hit % = past V43 trades only ({sample} trades); overall strategy rate, NOT stock-specific prediction or guarantee."])
    else:
        add(["WAIT - aaj koi qualified V43 BUY nahi. WATCHLIST ko BUY signal na samjhein."])
    add([""])

    # Deep-drawdown recovery radar: explicitly separated from the normal BUY engine.
    rec = ctx.get("recovery_radar")
    add(["A2) HIGH-SE NEEche GIRE STOCKS - RECOVERY RADAR (research/watch only; automatic BUY nahi)"], "title")
    add(["STOCK", "STAGE", "SCORE /100", "52W HIGH SE DOWN %", "52W LOW SE UP %", "PRICE", "ENTRY TRIGGER",
         "MAX BUY", "REF STOP", "T1", "T2", "T3", "UP/DOWN VOL RATIO", "ACTION"], "header")
    if rec is not None and not rec.empty:
        for _, rr in rec.iterrows():
            if not ctx.get("buy_ok"):
                action = "BLOCKED - global BUY safety gate"
            elif rr["REC_STAGE"] == "TRIGGERED":
                action = "TRIGGERED - PAPER/VERIFY ONLY"
            else:
                action = "WAIT FOR volume-confirmed breakout"
            add([rr["SYMBOL"], rr["REC_STAGE"], rr["REC_SCORE"], rr["REC_DRAWDOWN_PCT"], rr["REC_FROM_LOW_PCT"],
                 rr["CLOSE"], rr["REC_ENTRY_REF"], rr["REC_MAX_BUY"], rr["REC_STOP"], rr["REC_T1"],
                 rr["REC_T2"], rr["REC_T3"], rr["REC_ACCUM_RATIO"], action])
        add(["Entry/SL/T1-T3 are trigger-based references; PREPARE is not a BUY. A triggered row is research/paper-only until separately validated."])
    else:
        add(["Aaj koi eligible deep-drawdown recovery setup nahi mila. Falling stock ko sirf discount samajhkar mat kharido."])
    rd = ctx.get("recovery_diagnostics")
    if rd is not None and not rd.empty:
        add(["HISTORICAL RECOVERY DIAGNOSTIC - future high/low excursions after distinct signals (not trade P&L)"], "title")
        add(["STAGE", "NEXT SESSIONS", "EVENTS", "+10% HIGH TOUCH %", "+20% HIGH TOUCH %",
             "AVG BEST HIGH %", "MEDIAN BEST HIGH %", "AVG WORST LOW %"], "header")
        for _, dr in rd.iterrows():
            add([dr["STAGE"], dr["HORIZON_SESSIONS"], dr["EVENTS"], dr["HIT_PLUS10_PCT"], dr["HIT_PLUS20_PCT"],
                 dr["AVG_MAX_UPSIDE_PCT"], dr["MEDIAN_MAX_UPSIDE_PCT"], dr["AVG_MAX_DRAWDOWN_PCT"]])
        add(["This is the later high/low seen inside each window; not an executable return. Overlapping regimes and today's Nifty-500 survivorship bias remain."])
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

    add(["B2) WATCH ONLY - ise automatic BUY na samjhein. Filter dhila hai; historical backtest strict BUY se kamzor (~PF 1.7 vs ~2.2)."], "title")
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
    add([""])
    add(["E) RY APEX QUANT PRO V43 - quality score (probability nahi); regime = available-stock universe proxy, NIFTY index nahi"], "title")
    qs = ctx.get("qp_summary") or {}
    add([f"Backtest closed trades: {qs.get('trades', 0)} | Win %: {qs.get('win_pct', '')} | Avg net %/trade: {qs.get('avg_net_pct', '')} | "
         f"Profit Factor: {qs.get('profit_factor', '')} | Max drawdown % (trade-sequence equity): {qs.get('max_drawdown_pct', '')}"])
    add(["Costs: 0.35% round trip assumption | Entry: next session OPEN | Stop: 2 ATR | T1/T2/T3: 2R/4R/6R staircase | "
         "Daily OHLC backtest is approximate; no guaranteed fills/profits."])
    qy = ctx.get("qp_yearly")
    if qy is not None and not qy.empty:
        add(["YEAR-WISE V43 CLOSED-TRADE DIAGNOSTIC"], "title")
        add(["YEAR", "TRADES", "WIN %", "AVG NET %", "PROFIT FACTOR", "MAX DRAWDOWN %"], "header")
        for _, yr in qy.iterrows():
            add([yr["YEAR"], yr["trades"], yr["win_pct"], yr["avg_net_pct"], yr["profit_factor"], yr["max_drawdown_pct"]])
    qp = ctx.get("qp_periods")
    if qp is not None and not qp.empty:
        add(["PERIOD SPLIT (2024+ is a later-period diagnostic, not an untouched holdout)"], "title")
        add(["PERIOD", "TRADES", "WIN %", "AVG NET %", "PROFIT FACTOR", "MAX DRAWDOWN %"], "header")
        for _, period in qp.iterrows():
            add([period["PERIOD"], period["trades"], period["win_pct"], period["avg_net_pct"], period["profit_factor"], period["max_drawdown_pct"]])
    add(["STOCK", "SETUP", "SCORE /100", "MARKET REGIME PROXY", "CLOSE REF", "MAX BUY (+2%)", "STOP", "T1", "T2", "T3",
         "RISK %", "QTY", "CAPITAL Rs", "RISK Rs"], "header")
    qbuy = ctx.get("buy_v43")
    if ctx.get("buy_ok") and qbuy is not None and not qbuy.empty:
        for _, r in qbuy.iterrows():
            add([r["SYMBOL"], r["QP_SETUP"], r["QP_SCORE"], r["QP_MARKET_REGIME"], r["CLOSE"], r["QP_MAX_BUY"],
                 r["STOP"], r["T1"], r["T2"], r["T3"], r["RISK_PCT"], r["QTY"], r["CAPITAL_USED"], r["RISK_AMT"]])
    else:
        add(["", "KOI QUALIFIED V43 BUY NAHI" if ctx.get("buy_ok") else "BUY BAND: " + ctx.get("banner", "")])
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

    b43 = ctx.get("buy_v43")
    if ctx.get("buy_ok") and b43 is not None and not b43.empty:
        for _, r in b43.iterrows():
            add([r["SYMBOL"], f"BUY (V43 {r['QP_SETUP']})", r["CLOSE"], r["STOP"], r["T1"], r["T2"], r["T3"],
                 f"Quant Pro score {r['QP_SCORE']}/100; universe-proxy regime; backtest metrics shown in ACTION PLAN"])
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
        keep = {CFG.action_tab, CFG.status_tab, CFG.positions_tab, CFG.ry_tab, CFG.v38_tab, CFG.v42_tab}
        for ws in _retry(book.worksheets):
            if ws.title not in keep:
                try:
                    _retry(book.del_worksheet, ws)
                    time.sleep(1.5)
                except Exception as e:  # noqa: BLE001
                    print("extra tab delete warning:", ws.title, e)
    print("PUBLISHED: ACTION PLAN + SYSTEM STATUS + RY + RY V38")
    return True

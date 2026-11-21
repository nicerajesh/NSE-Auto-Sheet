"""DELIVERY aur INTRADAY tabs ke rows (plain lists - testable) + Sheet publish helpers.

SWING tab publish.build_action_rows se banta hai (CFG.action_tab = "SWING").
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

import publish as pb
from config import CFG
from delivery import next_rebalance


def _qty(q) -> object:
    return "SLOT CHHOTA" if (q is None or (isinstance(q, (int, float, np.integer, np.floating)) and q <= 0)) else int(q)


# --------------------------------------------------------------------------- DELIVERY
def build_delivery_rows(ctx: dict, cand: pd.DataFrame, detail: bool | None = None) -> tuple[list[list], dict]:
    """Default = SIMPLE view (sirf wo stocks jo abhi kharide ja sakte hain). DELIVERY_DETAIL=1 -> poora purana table."""
    if detail is None:
        detail = os.getenv("DELIVERY_DETAIL", "0") == "1"
    return (_delivery_detail if detail else _delivery_simple)(ctx, cand)


def _delivery_simple(ctx: dict, cand: pd.DataFrame) -> tuple[list[list], dict]:
    rows: list[list] = []
    marks = {"title": [], "header": []}

    def add(r, kind=None):
        rows.append(r)
        if kind:
            marks[kind].append(len(rows) - 1)

    asof = ctx["asof"]
    show = int(os.getenv("DELIVERY_SHOW", "10") or 10)
    add([f"DELIVERY - AAJ KYA KHARIDNA HAI | Data: {asof:%d-%b-%Y} | Agla rebalance: {next_rebalance(asof):%d-%b-%Y}"], "title")
    add([f"Market: {ctx.get('health_label', '')} | {ctx.get('breadth200', float('nan')):.0f}% stocks EMA200 ke upar | "
         f"Capital Rs {CFG.delivery_capital:,.0f} (abhi {CFG.stage_pct:.0f}% use)"])
    if ctx.get("stale"):
        add(["DATA PURANA HAI - aaj kharidne ki list band."])
    add([""])
    add(["KHARIDO (mahine ke pehle trading din; jo pehle se hai use dobara mat kharido)"], "title")
    add(["#", "STOCK", "KHARIDO (~)", "STOP LOSS", "TARGET 1", "TARGET 2", "TARGET 3", "QTY", "RISK Rs"], "header")
    skipped = []
    n = 0
    if cand is not None and not cand.empty:
        for _, r in cand[cand["ZONE"] == "BUY"].iterrows():
            if not (isinstance(r["QTY"], (int, float, np.integer, np.floating)) and r["QTY"] >= 1):
                skipped.append(str(r["SYMBOL"]))
                continue
            if n >= show:
                break
            n += 1
            add([n, r["SYMBOL"], r["CLOSE"], r["STOP"], r["T1"], r["T2"], r["T3"], int(r["QTY"]), r["RISK_AMT"]])
    if n == 0:
        add(["", "Aaj kharidne layak koi stock nahi."])
    add([""])
    if cand is not None and not cand.empty:
        hold = cand[cand["ZONE"] == "HOLD"]["SYMBOL"].tolist()
        if hold:
            add(["Pehle se hai to HOLD rakho (rank 21-40): " + ", ".join(map(str, hold))])
        if skipped:
            add([f"Slot chhota hone se list me nahi aaye ({len(skipped)}): " + ", ".join(skipped) + " - capital/stage badhao to aayenge."])
        if (cand[cand["ZONE"] == "BUY"]["MOM"] > 300).any():
            add(["Dhyan: 300%+ momentum wale small-cap bahut volatile hote hain - unka size aur chhota rakho."])
    add([""])
    add(["KAISE BECHNA HAI"], "title")
    for t in (
        "1) STOP LOSS ka order kharidte hi lagao. SL touch hua to bech do - bahas nahi.",
        "2) Target 1 chhua to SL ko kharid bhav par le aao. Target 2 par SL Target 1 par. Target 3 par SL Target 2 par. Jab tak SL na toote, hold.",
        f"3) Rank {CFG.delivery_hold_n} se bahar nikle ya Close EMA200 ke neeche gaya to bech do (mahine me ek baar dekho).",
        "4) 100% kaam karne wali koi strategy nahi hoti. Kai stocks SL par jayenge - kamai kuch bade winners se aati hai, isliye SL lagao aur size chhota rakho.",
    ):
        add([t])
    width = max(len(r) for r in rows)
    return pb._pad(rows, width), marks


def _delivery_detail(ctx: dict, cand: pd.DataFrame) -> tuple[list[list], dict]:
    rows: list[list] = []
    marks = {"title": [], "header": []}

    def add(r, kind=None):
        rows.append(r)
        if kind:
            marks[kind].append(len(rows) - 1)

    asof = ctx["asof"]
    stage_cap = CFG.delivery_capital * CFG.stage_pct / 100
    add([f"RY DELIVERY | Data: {asof:%d-%b-%Y} | Monthly momentum rotation | Agla rebalance: {next_rebalance(asof):%d-%b-%Y}"], "title")
    add([f"Delivery capital Rs {CFG.delivery_capital:,.0f} x stage {CFG.stage_pct:.0f}% = Rs {stage_cap:,.0f} | "
         f"slot Rs {stage_cap / CFG.delivery_top_n:,.0f} x {CFG.delivery_top_n} stocks | risk/stock max {CFG.delivery_risk_pct}% | "
         f"Universe: Nifty 500 (turnover >= Rs {CFG.delivery_min_turnover_cr:.0f} cr)"])
    add([f"Breadth: {ctx.get('breadth50', float('nan')):.0f}% stocks > EMA50 | {ctx.get('breadth200', float('nan')):.0f}% > EMA200 | "
         f"Swing health: {ctx.get('health_label', '')}"])
    if ctx.get("stale"):
        add(["DATA STALE - delivery candidates band (data 3+ session purana). Pehle data refresh hone do."])
    add([""])
    hdr = ["RANK", "STOCK", "CLOSE", "MOMENTUM 12-1 %", "DISASTER SL", "RISK %", "T1 (2R)", "T2 (4R)", "T3 (6R)",
           "QTY", "CAPITAL Rs", "RISK Rs", "TREND EXIT (close < EMA200)", "ADX", "ACTION"]

    def block(title, df, action):
        add([title], "title")
        add(hdr, "header")
        if df is None or df.empty:
            add(["", "Koi stock nahi"])
            return
        for _, r in df.iterrows():
            add([int(r["RANK"]), r["SYMBOL"], r["CLOSE"], r["MOM"], r["STOP"], r["RISK_PCT"], r["T1"], r["T2"], r["T3"],
                 _qty(r["QTY"]), r["CAPITAL_USED"], r["RISK_AMT"], r["EXIT_BELOW"], r["ADX"], action])
        add([""])

    if cand is None or cand.empty:
        add(["Aaj koi delivery candidate nahi (trend filter ke baad kuch bacha nahi)"])
    else:
        block(f"A) BUY ZONE - momentum rank 1-{CFG.delivery_top_n} (mahine ke pehle trading din in me se kharido jo abhi na ho)",
              cand[cand["ZONE"] == "BUY"], "BUY / HOLD")
        block(f"B) HOLD ZONE - rank {CFG.delivery_top_n + 1}-{CFG.delivery_hold_n} (naya mat kharido; jo already hai use hold karo)",
              cand[cand["ZONE"] == "HOLD"], "HOLD only")
    add(["RULES"], "title")
    for t in (
        f"1) EXIT: rank {CFG.delivery_hold_n} se bahar nikle, ya Close < EMA200, ya disaster SL hit. Rebalance mahine me ek baar - roz trade mat karo.",
        "2) T1/T2/T3 = 2R/4R/6R review levels hain: T1 par SL cost par, T2 par SL T1 par, T3 par SL T2 par (swing jaisa staircase). Fixed sell target nahi.",
        "3) Evidence (RESEARCH.md): momentum top decile ka avg R ~0.5 vs bottom half ~0.3; top-20 monthly rotation ~30% CAGR vs equal-weight ~17% - "
        "par ye survivorship-bias se INFLATED hai (universe aaj ka Nifty 500). Asli return kam hoga; 2025-26 me momentum kamzor raha.",
        "4) Delivery %, volume dry-up, index regime filter test me random se behtar nahi nikle - isliye yahan use nahi kiye.",
        "5) 'SLOT CHHOTA' = stage size me ek share ka risk-limit/slot se zyada hai; capital badhao ya stage % badhao, ya skip karo.",
        "6) Research tool hai, advice nahi. Size aisa rakho ki 25-30% drawdown jhel sako (portfolio-level backtest me DD -21% se -33% aaya).",
    ):
        add([t])
    width = max(len(r) for r in rows)
    return pb._pad(rows, width), marks


# --------------------------------------------------------------------------- INTRADAY
_ACTION = {
    "PENDING": "ABHI ORDER: agle 5-min bar ke open par {side} (entry se 0.5R se zyada door khule to SKIP). SL turant lagao.",
    "ACTIVE": "HOLD. SL {stop}. 15:15 par band.",
    "T1 HIT": "SL ko entry par laao ({stop}). 15:15 par band.",
    "T2 HIT": "SL ko T1 par laao ({stop}). 15:15 par band.",
    "TARGET 3": "CLOSED - T3 par poora exit.",
    "STOPPED": "CLOSED - SL hit.",
    "BREAKEVEN": "CLOSED - T1 ke baad entry par exit.",
    "SQUARED OFF": "CLOSED - 15:15 square-off.",
    "SKIPPED": "SKIP - gap/SL ke paar khula, chase mat karo.",
}


def build_intraday_rows(sigs: list[dict], meta: dict) -> tuple[list[list], dict]:
    """meta: now, bias(+1/-1/0/None), scanned, missing(list), error(str|None), backtest(dict|None), market_open(bool)"""
    rows: list[list] = []
    marks = {"title": [], "header": []}

    def add(r, kind=None):
        rows.append(r)
        if kind:
            marks[kind].append(len(rows) - 1)

    now = meta["now"]
    bias = meta.get("bias")
    bias_txt = {1: "UP (long only)", -1: "DOWN (short only)", 0: "FLAT/unknown"}.get(bias, "NO DATA")
    add([f"RY INTRADAY | {now:%d-%b-%Y %H:%M} IST | NIFTY: {bias_txt} | Signals {len(sigs)}/{CFG.intraday_max_trades} | "
         f"Naya signal {CFG.intraday_entry_cutoff} tak | Square-off {CFG.intraday_square_off}"], "title")
    risk_amt = CFG.intraday_capital * CFG.intraday_risk_pct / 100
    add([f"Capital Rs {CFG.intraday_capital:,.0f} | risk/trade {CFG.intraday_risk_pct}% = Rs {risk_amt:,.0f} | max leverage {CFG.intraday_max_leverage:g}x | "
         f"din ka max loss ~ Rs {risk_amt * CFG.intraday_max_trades:,.0f} (3 SL) | scanned {meta.get('scanned', 0)} stocks"])
    bt = meta.get("backtest")
    if bt and bt.get("trades"):
        add([f"BACKTEST ({bt['days']} din, {bt['trades']} trades): PF {bt['pf']} | win {bt['win_pct']}% | avg R {bt['avg_r']} | max DD {bt['max_dd_r']}R"
             f"  -> PF < 1.2 ya trades < 150 ho to LIVE mat chalao, sirf paper."])
    else:
        add(["BACKTEST: abhi nahi chala. Pehle `python src/intraday_run.py --backtest 60` chalao; jab tak 150+ trades aur PF > 1.2 na dikhe, sirf paper trade."])
    if meta.get("error"):
        add(["WARNING: " + str(meta["error"])])
    if meta.get("missing"):
        add(["Symbol Angel master me nahi mile (skip): " + ", ".join(meta["missing"][:15])])
    add([""])

    hdr = ["#", "SIGNAL TIME", "STOCK", "SIDE", "ENTRY (approx)", "STOP LOSS", "T1 (1R)", "T2 (2R)", "T3 (3R)", "RISK/SHARE",
           "QTY", "CAPITAL Rs", "RISK Rs", "VOL x", "STATUS", "LTP", "R NOW / RESULT", "ACTION"]
    add(["SIGNALS - ORB 15-min + VWAP + volume + NIFTY direction"], "title")
    add(hdr, "header")
    if not meta.get("market_open", True):
        add(["", "Aaj market band hai ya data nahi mila."])
    elif not sigs:
        add(["", "ABHI KOI SIGNAL NAHI - no signal = no trade."])
    for i, s in enumerate(sigs, 1):
        side = "BUY" if s["side"] == "LONG" else "SELL (short, MIS)"
        stop_now = s.get("stop_now", s["stop"])
        act = _ACTION.get(s["status"], s["status"]).format(side=side, stop=round(float(stop_now), 2) if stop_now == stop_now else "")
        entry = s["fill"] if s.get("fill") == s.get("fill") and s.get("fill") else s["close"]
        add([i, pd.Timestamp(s["ts"]).strftime("%H:%M"), s["symbol"], side, entry, s["stop"], s["t1"], s["t2"], s["t3"],
             s["risk"], _qty(s["QTY"]), s["CAPITAL_USED"], s["RISK_AMT"], s["vol_ratio"], s["status"], s.get("ltp", ""),
             s["r"] if s["r"] == s["r"] else "", act])
    add([""])
    add(["RULES"], "title")
    for t in (
        "1) Signal = pehle 15 min (09:15-09:30) ki range ka breakout, 5-min bar close par, VWAP ke sahi taraf, volume >= "
        f"{CFG.intraday_vol_mult}x, prev-close ke sahi taraf, aur NIFTY din ke open ke sahi taraf.",
        "2) Order tum khud lagate ho (system order nahi lagata). SL order PEHLE lagao, phir target. 15:15 tak sab band - overnight kabhi nahi.",
        f"3) Din me max {CFG.intraday_max_trades} trade. 2 SL ke baad bhi signal aaye to size aadha ya us din band - revenge trade nahi.",
        "4) T1 par SL entry par, T2 par SL T1 par, T3 par poora exit. Ek hi bar me SL aur target dono chhute to SL mana jata hai (conservative).",
        f"5) Cost assumption {CFG.intraday_cost_pct}% round-trip (STT + charges + slippage). Apne broker ke asli charges se match karo.",
        "6) SEBI ke studies me zyadatar retail intraday traders ne paisa gawaya. Pehle paper trade, phir chhoti size.",
    ):
        add([t])
    width = max(len(r) for r in rows)
    return pb._pad(rows, width), marks


# --------------------------------------------------------------------------- publish
def publish_tab(title: str, built: tuple, book=None) -> bool:
    if book is None:
        book = pb.open_book()
        if book is None:
            print(f"PUBLISH SKIPPED ({title}): GCP_CREDENTIALS set nahi")
            return False
    pb._write_tab(book, title, *built)
    print(f"PUBLISHED: {title}")
    return True

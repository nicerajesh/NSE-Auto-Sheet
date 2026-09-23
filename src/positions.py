"""Tumhari ASLI positions ka tracker.

Google Sheet ke "MY POSITIONS" tab me tum apne asli trades likhte ho:
    SYMBOL | BUY DATE | BUY PRICE | QTY | MY STOP (optional) | NOTES
Engine roz:
  * staircase rule se SL kahan hona chahiye (T1 -> entry, T2 -> T1, T3 -> T2) nikalta hai,
  * batata hai HOLD / SL RAISE / EXIT,
  * total deployed capital, open risk aur unrealized P&L nikalta hai,
  * naye BUY ko slots / risk budget / cash ke hisaab se chhota ya band karta hai.
Engine kabhi order nahi lagata. SL order broker me tumhe khud update karna hai.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from config import CFG

POS_COLS = ["SYMBOL", "BUY DATE", "BUY PRICE", "QTY", "MY STOP", "NOTES"]
_HEAD_ALIASES = {
    "SYMBOL": "SYMBOL", "STOCK": "SYMBOL", "SCRIP": "SYMBOL",
    "BUY DATE": "BUY DATE", "DATE": "BUY DATE", "ENTRY DATE": "BUY DATE",
    "BUY PRICE": "BUY PRICE", "PRICE": "BUY PRICE", "ENTRY": "BUY PRICE", "ENTRY PRICE": "BUY PRICE", "AVG PRICE": "BUY PRICE",
    "QTY": "QTY", "QUANTITY": "QTY", "SHARES": "QTY",
    "MY STOP": "MY STOP", "STOP": "MY STOP", "SL": "MY STOP", "STOP LOSS": "MY STOP",
    "NOTES": "NOTES", "NOTE": "NOTES",
}
EVAL_COLS = ["SYMBOL", "STATE", "QTY", "BUY DATE", "BUY PRICE", "LAST CLOSE", "PNL %", "PNL RS", "R NOW",
             "SL NOW", "T1", "T2", "T3", "TIER", "VALUE RS", "RISK RS", "ACTION", "PRIORITY"]


def _num(x):
    if x is None:
        return np.nan
    if isinstance(x, (int, float, np.integer, np.floating)):
        return float(x)
    t = re.sub(r"[₹,\s]|Rs\.?|INR", "", str(x), flags=re.I)
    if t == "":
        return np.nan
    try:
        return float(t)
    except ValueError:
        return np.nan


def load_csv(path: str | Path | None) -> list[list]:
    """Sheet na ho to (ya test me) CSV se wahi format ki rows."""
    if not path or not Path(path).exists():
        return []
    d = pd.read_csv(path, dtype=str, keep_default_na=False)
    return [list(d.columns)] + d.values.tolist()


def parse(raw: list[list] | None) -> tuple[pd.DataFrame, list[str]]:
    """Sheet ki raw rows -> (valid positions df, problems list)."""
    if not raw:
        return pd.DataFrame(columns=POS_COLS), []
    head = [_HEAD_ALIASES.get(str(h).strip().upper(), "") for h in raw[0]]
    if "SYMBOL" not in head or "BUY PRICE" not in head or "QTY" not in head:
        return pd.DataFrame(columns=POS_COLS), ["Header row me SYMBOL, BUY DATE, BUY PRICE, QTY columns chahiye"]
    rows, problems = [], []
    for k, r in enumerate(raw[1:], start=2):
        rec = {h: (r[i] if i < len(r) else "") for i, h in enumerate(head) if h}
        if not str(rec.get("SYMBOL", "")).strip():
            continue
        sym = str(rec["SYMBOL"]).strip().upper()
        price, qty, stop = _num(rec.get("BUY PRICE")), _num(rec.get("QTY")), _num(rec.get("MY STOP"))
        dt = pd.to_datetime(rec.get("BUY DATE", ""), dayfirst=True, errors="coerce")
        err = None
        if not (price > 0):
            err = "BUY PRICE samajh nahi aaya"
        elif not (qty >= 1):
            err = "QTY samajh nahi aaya"
        elif pd.isna(dt):
            err = "BUY DATE samajh nahi aaya (dd-mm-yyyy likho)"
        elif np.isfinite(stop) and stop >= price:
            err = "MY STOP buy price se neeche hona chahiye"
        if err:
            problems.append(f"Row {k} ({sym}): {err} - ye row ignore hui")
            continue
        rows.append({"SYMBOL": sym, "BUY DATE": dt.normalize(), "BUY PRICE": price, "QTY": int(qty),
                     "MY STOP": stop if np.isfinite(stop) else np.nan, "NOTES": rec.get("NOTES", "")})
    return pd.DataFrame(rows, columns=POS_COLS), problems


def _one(r: pd.Series, g: pd.DataFrame, asof: pd.Timestamp) -> dict:
    o, h, l, c = (g[x].values.astype(float) for x in ("OPEN", "HIGH", "LOW", "CLOSE"))
    n = len(g)
    ib = int(np.searchsorted(g["DATE"].values, np.datetime64(r["BUY DATE"]), side="right") - 1)
    if ib < 0:
        return {"STATE": "NO DATA", "ACTION": "Buy date se pehle ka data nahi - manual check", "PRIORITY": 2}
    buy, qty = float(r["BUY PRICE"]), int(r["QTY"])
    atr = g["ATR"].iloc[max(ib - 1, 0)]
    stop0 = float(r["MY STOP"]) if pd.notna(r["MY STOP"]) else (buy - CFG.stop_atr * atr if pd.notna(atr) else np.nan)
    if not np.isfinite(stop0) or stop0 >= buy:
        return {"STATE": "NO DATA", "ACTION": "ATR/stop nahi nikal paya - MY STOP column bharo", "PRIORITY": 2}
    risk = buy - stop0
    stop, hi, tier = stop0, buy, "-"
    state, exit_idx, exit_px, reason = "OPEN", None, None, ""
    for j in range(ib + 1, n):
        if l[j] <= stop:
            state, exit_idx, exit_px = "EXITED", j, min(o[j], stop)
            reason = "STOP" if stop <= stop0 + 1e-9 else "TRAILING SL"
            break
        hi = max(hi, h[j])
        if hi >= buy + CFG.t3_r * risk:
            stop, tier = max(stop, buy + CFG.t2_r * risk), "T3"
        elif hi >= buy + CFG.t2_r * risk:
            stop, tier = max(stop, buy + CFG.t1_r * risk), "T2"
        elif hi >= buy + CFG.t1_r * risk:
            stop, tier = max(stop, buy), "T1"
        if j - ib >= CFG.max_hold:
            state, exit_idx, exit_px, reason = "TIME", j, float(c[j]), "TIME"
            break
    last_close, last_date = float(c[-1]), g["DATE"].iloc[-1]
    px = exit_px if exit_px is not None else last_close
    out = {"STATE": state, "QTY": qty, "BUY DATE": r["BUY DATE"], "BUY PRICE": buy, "LAST CLOSE": last_close,
           "PNL %": (px / buy - 1) * 100, "PNL RS": qty * (px - buy), "R NOW": (px - buy) / risk, "SL NOW": stop,
           "T1": buy + CFG.t1_r * risk, "T2": buy + CFG.t2_r * risk, "T3": buy + CFG.t3_r * risk, "TIER": tier,
           "VALUE RS": qty * last_close if state == "OPEN" else 0.0,
           "RISK RS": qty * max(0.0, last_close - stop) if state == "OPEN" else 0.0}
    if state == "EXITED":
        d = g["DATE"].iloc[exit_idx]
        if d == asof:
            out.update(ACTION=f"SL HIT aaj (~{px:.2f}). SL order tha to nikal chuka; warna kal open par SELL", PRIORITY=0)
        elif (asof - d).days <= 5:
            out.update(ACTION=f"SL hit {d:%d-%b} (~{px:.2f}). Agar abhi tak nahi becha to bech do, phir row hata do", PRIORITY=0)
        else:
            out.update(ACTION=f"Closed {d:%d-%b} ({reason}). Row hata do", PRIORITY=4)
    elif state == "TIME":
        out.update(ACTION=f"{CFG.max_hold} session pure - review karo ya exit", PRIORITY=2)
    elif (asof - last_date).days > 4:
        out.update(ACTION=f"Is stock ka data {last_date:%d-%b} tak hi hai - manual check", PRIORITY=2)
    elif stop > stop0 + 1e-9:
        out.update(ACTION=f"SL RAISE karo -> {stop:.2f} ({tier} touch ho chuka)", PRIORITY=1)
    else:
        out.update(ACTION=f"HOLD, SL {stop:.2f}", PRIORITY=3)
    return out


def evaluate(pos: pd.DataFrame, f: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    if pos is None or pos.empty:
        return pd.DataFrame(columns=EVAL_COLS)
    sub = f[f["SYMBOL"].isin(pos["SYMBOL"])]
    bars = {s: g.sort_values("DATE").reset_index(drop=True) for s, g in sub.groupby("SYMBOL")}
    rows = []
    for _, r in pos.iterrows():
        g = bars.get(r["SYMBOL"])
        if g is None or g.empty:
            rows.append({"SYMBOL": r["SYMBOL"], "STATE": "NO DATA", "QTY": r["QTY"], "BUY DATE": r["BUY DATE"],
                         "BUY PRICE": r["BUY PRICE"], "ACTION": "Universe me ye symbol nahi mila - spelling check", "PRIORITY": 2})
            continue
        res = _one(r, g, asof)
        res["SYMBOL"] = r["SYMBOL"]
        res.setdefault("QTY", r["QTY"]); res.setdefault("BUY DATE", r["BUY DATE"]); res.setdefault("BUY PRICE", r["BUY PRICE"])
        rows.append(res)
    d = pd.DataFrame(rows).reindex(columns=EVAL_COLS)
    return d.sort_values(["PRIORITY", "SYMBOL"]).reset_index(drop=True)


def summarize(mine: pd.DataFrame) -> dict:
    op = mine[mine["STATE"] == "OPEN"] if not mine.empty else mine
    if op is None or op.empty:
        return dict(n_open=0, deployed=0.0, open_risk=0.0, pnl_open=0.0, dd_pct=0.0, dd_guard=False)
    pnl = float(pd.to_numeric(op["PNL RS"]).sum())
    dd_pct = pnl / CFG.capital * 100
    return dict(n_open=len(op), deployed=float(op["VALUE RS"].sum()), open_risk=float(op["RISK RS"].sum()),
                pnl_open=pnl, dd_pct=dd_pct, dd_guard=dd_pct <= -CFG.dd_guard_pct)


def fit_to_portfolio(buy: pd.DataFrame, held: set[str], slots_free: int, budget_rs: float, cash_rs: float) -> pd.DataFrame:
    """Naye BUY ko real portfolio me fit karo: already-held skip, slots, total-risk budget aur cash ke hisaab se qty kam."""
    if buy is None or buy.empty:
        return buy
    keep = []
    for _, r in buy.iterrows():
        if len(keep) >= slots_free:
            break
        if r["SYMBOL"] in held:
            continue
        rps = r["CLOSE"] - r["STOP"]
        if rps <= 0:
            continue
        qty = int(r["QTY"])
        qty = min(qty, int(np.floor(budget_rs / rps)) if budget_rs > 0 else 0, int(np.floor(cash_rs / r["CLOSE"])) if cash_rs > 0 else 0)
        if qty < 1:
            continue
        r = r.copy()
        r["QTY"], r["CAPITAL_USED"], r["RISK_AMT"] = qty, round(qty * r["CLOSE"], 2), round(qty * rps, 2)
        budget_rs -= qty * rps
        cash_rs -= qty * r["CLOSE"]
        keep.append(r)
    return pd.DataFrame(keep).reset_index(drop=True) if keep else buy.head(0)

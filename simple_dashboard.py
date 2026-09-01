"""One single, plain-language sheet: "MERA ACTION PLAN".

Every other tab in this project (Early Hunter, APEX Matrix, 52 Week Low
Rocket, Stealth Accumulation, Dashboard...) is organised by SCANNER, in
technical columns (DELIVERY_PCT, ATR_COMPRESSION, RESISTANCE_TESTS...). A
non-technical user has no way to answer "so what do I actually DO today" from
that without piecing together 5+ tabs themselves.

This module builds exactly one table that answers that question directly:
  - Naye BUY signals, from every scanner combined (not just Early Hunter)
  - Currently open positions that should be HELD
  - Positions that hit their stop-loss or target TODAY and should be SOLD/EXITED
sorted so the most urgent thing (SELL/EXIT) is always at the top, in simple
Hindi-English, with real position sizing (QTY / CAPITAL / RISK) reused from
risk_manager.py so it's consistent with every other risk-aware output.
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd
from csv_utils import safe_to_csv, safe_read_csv
from risk_manager import apply_risk_management
from config import RISK

OUT = Path("output")
OPEN_STATUSES = {"OPEN", "HOLD", "T1 HIT / TRAIL", "T2 HIT / TRAIL"}
EXIT_STATUSES = {"EXIT", "T3 HIT / EXIT"}


def _read(name):
    p = OUT / name
    return safe_read_csv(p) if p.exists() else pd.DataFrame()


def _sector_map():
    df = _read("sector_map.csv")
    if df.empty or "SYMBOL" not in df.columns:
        return {}
    return dict(zip(df.SYMBOL.astype(str), df.SECTOR.astype(str)))


def _num(v, default=0.0):
    try:
        x = float(v)
        return x if pd.notna(x) else default
    except Exception:
        return default


def _sell_rows(ledger: pd.DataFrame, latest_date: str) -> pd.DataFrame:
    """Positions whose STATUS just flipped to an exit state as of TODAY's
    run -- these are new, actionable "sell now" alerts, not old history."""
    if ledger.empty or "STATUS" not in ledger.columns:
        return pd.DataFrame()
    exits = ledger[ledger.STATUS.astype(str).isin(EXIT_STATUSES)].copy()
    if exits.empty:
        return pd.DataFrame()
    if "EXIT_DATE" in exits.columns and latest_date:
        exits = exits[exits.EXIT_DATE.astype(str) == str(latest_date)]
    if exits.empty:
        return pd.DataFrame()
    entry = exits["ENTRY"].apply(_num)
    exitp = exits["EXIT_PRICE"].apply(_num)
    pnl_pct = ((exitp - entry) / entry.replace(0, pd.NA) * 100).round(2)
    return pd.DataFrame({
        "SYMBOL": exits["SYMBOL"],
        "KYA KARU": "🔴 BECHO / EXIT KARO",
        "PRIORITY": 1,
        "PRICE": exitp,
        "QTY": exits.get("POSITION_QTY", 0),
        "STOP LOSS": exits.get("STOP_LOSS", ""),
        "TARGET": "",
        "PROFIT/LOSS %": pnl_pct,
        "WHY": "Reason: " + exits.get("EXIT_REASON", "").astype(str),
    })


def _hold_rows(ledger: pd.DataFrame) -> pd.DataFrame:
    if ledger.empty or "STATUS" not in ledger.columns:
        return pd.DataFrame()
    open_ = ledger[ledger.STATUS.astype(str).isin(OPEN_STATUSES)].copy()
    if open_.empty:
        return pd.DataFrame()
    entry = open_["ENTRY"].apply(_num)
    cmp_ = open_["LAST_CLOSE"].apply(_num)
    pnl_pct = ((cmp_ - entry) / entry.replace(0, pd.NA) * 100).round(2)
    status_label = open_["STATUS"].map({
        "OPEN": "🟡 HOLD RAKHO (naya)", "HOLD": "🟡 HOLD RAKHO",
        "T1 HIT / TRAIL": "🟡 HOLD RAKHO (Target 1 ho gaya)",
        "T2 HIT / TRAIL": "🟡 HOLD RAKHO (Target 2 ho gaya)",
    }).fillna("🟡 HOLD RAKHO")
    return pd.DataFrame({
        "SYMBOL": open_["SYMBOL"],
        "KYA KARU": status_label,
        "PRIORITY": 3,
        "PRICE": cmp_,
        "QTY": open_.get("POSITION_QTY", 0),
        "STOP LOSS": open_.get("STOP_LOSS", ""),
        "TARGET": open_.get("TARGET_1", ""),
        "PROFIT/LOSS %": pnl_pct,
        "WHY": "Entry price tha " + entry.round(2).astype(str),
    })


def _buy_rows(master: pd.DataFrame, ledger: pd.DataFrame, sector_map: dict) -> pd.DataFrame:
    """Every scanner's PUBLISHED buy, combined, then sized through
    risk_manager.py against whatever is ALREADY open in the ledger -- so this
    is portfolio-aware across ALL scanners together, not just one at a time."""
    if master.empty:
        return pd.DataFrame()
    already_open = set(ledger[ledger.STATUS.astype(str).isin(OPEN_STATUSES)].SYMBOL.astype(str)) if not ledger.empty and "STATUS" in ledger.columns else set()
    m = master[~master.SYMBOL.astype(str).isin(already_open)].copy()  # don't suggest buying something you already hold
    if m.empty:
        return pd.DataFrame()
    # master_buy_dashboard.csv has one row PER SOURCE (Early Hunter, APEX
    # Matrix, ...) for confluence tracking -- dedupe to one row per SYMBOL
    # here, or a stock with 2+ agreeing scanners would get sized/suggested
    # as two separate "buy" rows and silently eat the portfolio risk budget
    # twice for the same position.
    m = m.sort_values("CONFLUENCE_COUNT", ascending=False).drop_duplicates("SYMBOL", keep="first")
    sizing_input = pd.DataFrame({
        "SYMBOL": m["SYMBOL"], "ACTION": "PRE-BREAKOUT BUY", "QUALITY_GATE": "PASS",
        "IDEAL_ENTRY": m["ENTRY"].apply(_num), "STOP_LOSS": m["STOP_LOSS"].apply(_num),
    })
    sized = apply_risk_management(sizing_input, ledger, sector_map)
    sized = sized.merge(m[["SYMBOL", "SOURCE", "TARGET_1", "CONFLUENCE_COUNT", "ALL_SOURCES"]], on="SYMBOL", how="left")
    label = sized["RISK_MANAGER_STATUS"].apply(
        lambda s: "🟢 KHARIDO" if s == "PASS" else "⚪ WAIT (risk limit ke wajah se)")
    why = "Signal: " + sized["ALL_SOURCES"].astype(str)
    conf = sized["CONFLUENCE_COUNT"].fillna(1).astype(int)
    why = why.where(conf <= 1, why + " (" + conf.astype(str) + " scanners agree)")
    return pd.DataFrame({
        "SYMBOL": sized["SYMBOL"],
        "KYA KARU": label,
        "PRIORITY": sized["RISK_MANAGER_STATUS"].apply(lambda s: 2 if s == "PASS" else 4),
        "PRICE": sized["IDEAL_ENTRY"],
        "QTY": sized["POSITION_QTY"],
        "STOP LOSS": sized["STOP_LOSS"],
        "TARGET": sized["TARGET_1"],
        "PROFIT/LOSS %": "",
        "WHY": why,
    })


def build_action_plan() -> pd.DataFrame:
    ledger = _read("trade_ledger.csv")
    master = _read("master_buy_dashboard.csv")
    latest = _read("latest_market.csv")
    latest_date = str(latest["DATE"].iloc[0]) if not latest.empty and "DATE" in latest.columns else ""
    sector_map = _sector_map()

    sell = _sell_rows(ledger, latest_date)
    hold = _hold_rows(ledger)
    buy = _buy_rows(master, ledger, sector_map)

    parts = [p for p in (sell, buy, hold) if not p.empty]
    if not parts:
        return pd.DataFrame(columns=["SYMBOL", "KYA KARU", "PRICE", "QTY", "STOP LOSS", "TARGET", "PROFIT/LOSS %", "WHY", "MODE"])
    plan = pd.concat(parts, ignore_index=True)
    plan = plan.sort_values(["PRIORITY", "SYMBOL"]).reset_index(drop=True)
    plan["MODE"] = "PAPER" if RISK.paper_mode else "LIVE"
    plan = plan.drop(columns=["PRIORITY"])
    for c in ("PRICE", "STOP LOSS", "TARGET", "QTY"):
        plan[c] = pd.to_numeric(plan[c], errors="coerce").round(2)
    return plan


def main():
    plan = build_action_plan()
    safe_to_csv(plan, OUT / "mera_action_plan.csv")
    counts = plan["KYA KARU"].value_counts().to_dict() if not plan.empty else {}
    print(f"MERA ACTION PLAN ready: {len(plan)} rows | {counts}")
    if not plan.empty:
        print(plan.to_string(index=False))


if __name__ == "__main__":
    main()

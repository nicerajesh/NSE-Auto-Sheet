"""User-facing action plan with BUY, WAIT/WATCH, HOLD and EXIT signals."""
from __future__ import annotations
from pathlib import Path
import pandas as pd
from csv_utils import safe_to_csv, safe_read_csv
from risk_manager import apply_risk_management
from config import RISK

OUT = Path("output")
OPEN_STATUSES = {"OPEN", "HOLD", "T1 HIT / TRAIL", "T2 HIT / TRAIL"}
EXIT_STATUSES = {"EXIT", "T3 HIT / EXIT"}
BUY_LABELS = {
    "PRE-BREAKOUT BUY", "BREAKOUT BUY", "SWING BUY", "APEX BUY", "TACTICAL BUY",
    "BUY", "EARLY REVERSAL BUY", "STEALTH BUY"
}


def _read(name):
    p = OUT / name
    return safe_read_csv(p) if p.exists() else pd.DataFrame()


def _sector_map():
    df = _read("sector_map.csv")
    if df.empty or "SYMBOL" not in df.columns or "SECTOR" not in df.columns:
        return {}
    return dict(zip(df.SYMBOL.astype(str), df.SECTOR.astype(str)))


def _num(v, default=0.0):
    try:
        x = float(v)
        return x if pd.notna(x) else default
    except Exception:
        return default


def _text(row, *cols, default=""):
    for c in cols:
        if c in row.index:
            v = str(row[c]).strip()
            if v and v.lower() not in {"nan", "none"}:
                return v
    return default


def _sell_rows(ledger, latest_date):
    if ledger.empty or "STATUS" not in ledger.columns:
        return pd.DataFrame()
    exits = ledger[ledger.STATUS.astype(str).isin(EXIT_STATUSES)].copy()
    if "EXIT_DATE" in exits.columns and latest_date:
        exits = exits[exits.EXIT_DATE.astype(str) == str(latest_date)]
    if exits.empty:
        return pd.DataFrame()
    entry = exits.get("ENTRY", 0).apply(_num)
    exitp = exits.get("EXIT_PRICE", 0).apply(_num)
    pnl = ((exitp - entry) / entry.replace(0, pd.NA) * 100).round(2)
    return pd.DataFrame({
        "SYMBOL": exits["SYMBOL"], "KYA KARU": "🔴 BECHO / EXIT KARO", "PRIORITY": 1,
        "PRICE": exitp, "QTY": exits.get("POSITION_QTY", 0),
        "STOP LOSS": exits.get("STOP_LOSS", ""), "TARGET": "", "PROFIT/LOSS %": pnl,
        "WHY": "Reason: " + exits.get("EXIT_REASON", "").astype(str)
    })


def _hold_rows(ledger):
    if ledger.empty or "STATUS" not in ledger.columns:
        return pd.DataFrame()
    open_ = ledger[ledger.STATUS.astype(str).isin(OPEN_STATUSES)].copy()
    if open_.empty:
        return pd.DataFrame()
    entry = open_.get("ENTRY", 0).apply(_num)
    cmp_ = open_.get("LAST_CLOSE", 0).apply(_num)
    pnl = ((cmp_ - entry) / entry.replace(0, pd.NA) * 100).round(2)
    labels = open_["STATUS"].map({
        "OPEN": "🟡 HOLD RAKHO (naya)", "HOLD": "🟡 HOLD RAKHO",
        "T1 HIT / TRAIL": "🟡 HOLD RAKHO (Target 1 ho gaya)",
        "T2 HIT / TRAIL": "🟡 HOLD RAKHO (Target 2 ho gaya)"
    }).fillna("🟡 HOLD RAKHO")
    return pd.DataFrame({
        "SYMBOL": open_["SYMBOL"], "KYA KARU": labels, "PRIORITY": 3,
        "PRICE": cmp_, "QTY": open_.get("POSITION_QTY", 0),
        "STOP LOSS": open_.get("STOP_LOSS", ""), "TARGET": open_.get("TARGET_1", ""),
        "PROFIT/LOSS %": pnl, "WHY": "Entry price tha " + entry.round(2).astype(str)
    })


def _buy_rows(master, ledger, sector_map):
    if master.empty or "SYMBOL" not in master.columns:
        return pd.DataFrame()
    already = set(ledger[ledger.STATUS.astype(str).isin(OPEN_STATUSES)].SYMBOL.astype(str)) if not ledger.empty and "STATUS" in ledger.columns and "SYMBOL" in ledger.columns else set()
    m = master.copy()
    signal_col = next((c for c in ("SIGNAL_TYPE", "PUBLISHED_ACTION", "ACTION", "SIGNAL", "FINAL_ACTION") if c in m.columns), None)
    if signal_col:
        m = m[m[signal_col].astype(str).str.upper().isin(BUY_LABELS)].copy()
    if m.empty:
        return pd.DataFrame()
    m = m[~m.SYMBOL.astype(str).isin(already)].copy()
    if m.empty:
        return pd.DataFrame()
    if "CONFLUENCE_COUNT" in m.columns:
        m = m.sort_values("CONFLUENCE_COUNT", ascending=False)
    m = m.drop_duplicates("SYMBOL", keep="first")
    entry_col = "ENTRY" if "ENTRY" in m.columns else "IDEAL_ENTRY"
    sizing_input = pd.DataFrame({
        "SYMBOL": m["SYMBOL"], "ACTION": "PRE-BREAKOUT BUY", "QUALITY_GATE": "PASS",
        "IDEAL_ENTRY": m[entry_col].apply(_num), "STOP_LOSS": m.get("STOP_LOSS", 0).apply(_num)
    })
    sized = apply_risk_management(sizing_input, ledger, sector_map)
    keep = [c for c in ("SYMBOL", "SOURCE", "TARGET_1", "CONFLUENCE_COUNT", "ALL_SOURCES") if c in m.columns]
    if keep:
        sized = sized.merge(m[keep], on="SYMBOL", how="left")
    label = sized["RISK_MANAGER_STATUS"].apply(lambda s: "🟢 KHARIDO" if s == "PASS" else "⚪ WAIT (risk limit)")
    sources = sized.get("ALL_SOURCES", pd.Series("BUY SIGNAL", index=sized.index)).astype(str)
    return pd.DataFrame({
        "SYMBOL": sized["SYMBOL"], "KYA KARU": label,
        "PRIORITY": sized["RISK_MANAGER_STATUS"].apply(lambda s: 2 if s == "PASS" else 4),
        "PRICE": sized["IDEAL_ENTRY"], "QTY": sized["POSITION_QTY"],
        "STOP LOSS": sized["STOP_LOSS"], "TARGET": sized.get("TARGET_1", ""),
        "PROFIT/LOSS %": "", "WHY": "Signal: " + sources
    })


def _watch_rows(master, decision, ledger):
    """Show useful candidates even when there are no confirmed BUYs.
    WATCH/WAIT rows never receive position sizing and are never relabeled BUY.
    """
    src = decision if not decision.empty else master
    if src.empty or "SYMBOL" not in src.columns:
        return pd.DataFrame()
    already = set(ledger[ledger.STATUS.astype(str).isin(OPEN_STATUSES)].SYMBOL.astype(str)) if not ledger.empty and "STATUS" in ledger.columns and "SYMBOL" in ledger.columns else set()
    rows = src[~src.SYMBOL.astype(str).isin(already)].copy()
    action_col = next((c for c in ("FINAL_ACTION", "ACTION", "PUBLISHED_ACTION", "SIGNAL", "USER_ACTION") if c in rows.columns), None)
    if action_col:
        actions = rows[action_col].astype(str).str.upper()
        rows = rows[~actions.isin(BUY_LABELS)].copy()
    if rows.empty:
        return pd.DataFrame()
    score_cols = [c for c in ("V3_OPPORTUNITY_SCORE", "V3_TIMING_SCORE", "NEXT_DAY_SETUP_SCORE", "HUNTER_SCORE", "SCORE") if c in rows.columns]
    if score_cols:
        rows["_score"] = rows[score_cols].apply(pd.to_numeric, errors="coerce").max(axis=1).fillna(0)
        rows = rows.sort_values("_score", ascending=False)
    rows = rows.drop_duplicates("SYMBOL", keep="first").head(15)
    out = []
    for _, r in rows.iterrows():
        action = _text(r, "USER_ACTION", "FINAL_ACTION", "ACTION", "PUBLISHED_ACTION", "SIGNAL", default="WATCH")
        upper = action.upper()
        if "WAIT" in upper or "TRIGGER" in upper or "READY" in upper:
            label = "🟡 WAIT / TRIGGER KA WAIT"
        else:
            label = "🔵 WATCH"
        price = _text(r, "CMP", "CURRENT_PRICE", "LTP", "CLOSE", "ENTRY", "IDEAL_ENTRY", default="")
        entry = _text(r, "IDEAL_ENTRY", "ENTRY", default=price)
        stop = _text(r, "STOP_LOSS", "STOP", default="")
        target = _text(r, "TARGET_1", "TARGET", default="")
        score = _text(r, *score_cols, default="") if score_cols else ""
        why = "Action: " + action
        if score:
            why += " | Score: " + score
        trigger = _text(r, "BREAKOUT_TRIGGER", "TRIGGER_PRICE", default="")
        if trigger:
            why += " | Trigger: " + trigger
        out.append({"SYMBOL": str(r["SYMBOL"]), "KYA KARU": label, "PRIORITY": 4 if label.startswith("🟡") else 5,
                    "PRICE": _num(price, default=0) if price else "", "QTY": "", "STOP LOSS": stop,
                    "TARGET": target, "PROFIT/LOSS %": "", "WHY": why})
    return pd.DataFrame(out)


def build_action_plan():
    ledger = _read("trade_ledger.csv")
    master = _read("master_buy_dashboard.csv")
    decision = _read("decision_candidates.csv")
    latest = _read("latest_market.csv")
    latest_date = str(latest["DATE"].iloc[0]) if not latest.empty and "DATE" in latest.columns else ""
    sector_map = _sector_map()
    sell = _sell_rows(ledger, latest_date)
    buy = _buy_rows(master, ledger, sector_map)
    watch = _watch_rows(master, decision, ledger)
    hold = _hold_rows(ledger)
    parts = [p for p in (sell, buy, watch, hold) if not p.empty]
    columns = ["SYMBOL", "KYA KARU", "PRICE", "QTY", "STOP LOSS", "TARGET", "PROFIT/LOSS %", "WHY", "MODE"]
    if not parts:
        return pd.DataFrame(columns=columns)
    plan = pd.concat(parts, ignore_index=True)
    plan = plan.sort_values(["PRIORITY", "SYMBOL"]).reset_index(drop=True)
    plan["MODE"] = "PAPER" if RISK.paper_mode else "LIVE"
    plan = plan.drop(columns=["PRIORITY"])
    for c in ("PRICE", "STOP LOSS", "TARGET", "QTY"):
        plan[c] = pd.to_numeric(plan[c], errors="coerce").round(2)
    return plan[columns]


def main():
    plan = build_action_plan()
    safe_to_csv(plan, OUT / "mera_action_plan.csv")
    print(f"MERA ACTION PLAN ready: {len(plan)} rows")
    if not plan.empty:
        print(plan.to_string(index=False))


if __name__ == "__main__":
    main()

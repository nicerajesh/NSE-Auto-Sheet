"""Canonical Google Sheets publisher.

Exactly two user-facing tabs are maintained:
1. ACTION PLAN - executable BUY setups only.
2. SYSTEM STATUS - compact health summary.

All research, indicators, backtests, OOS validation and diagnostics remain
backend CSV artifacts and are never published as extra tabs.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import gspread
import numpy as np
import pandas as pd
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError, WorksheetNotFound

from csv_utils import safe_read_csv

OUT = Path(os.getenv("NSE_OUTPUT_DIR", "output"))
DEFAULT_SHEET_ID = "1U9j5fMZAWPUSwoP_U-GKdacVke9nUjspqPR3wGsWAUM"
KEEP_SHEETS = {"ACTION PLAN", "SYSTEM STATUS"}
BUY_ACTIONS = {"PRE-BREAKOUT BUY", "BREAKOUT BUY", "SWING BUY"}


def clean(value):
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return value.item() if hasattr(value, "item") else value


def num(row, *names):
    for name in names:
        if name in row.index:
            try:
                value = float(row.get(name))
                if np.isfinite(value):
                    return value
            except Exception:
                pass
    return np.nan


def read_csv(name):
    path = OUT / name
    return safe_read_csv(path) if path.exists() else pd.DataFrame()


def build_action_plan(hunter: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "RANK", "BUY", "ENTRY", "STOP LOSS", "T1", "T2", "T3",
        "T1 R:R", "T2 R:R", "T3 R:R", "RISK %", "QTY",
        "CAPITAL", "RISK AMOUNT", "WHY",
    ]
    if hunter.empty or "SYMBOL" not in hunter.columns:
        return pd.DataFrame(columns=columns)

    x = hunter.copy()
    action = x.get("ACTION", "").astype(str).str.upper().str.strip()
    x["ACTION"] = action

    # Only final quality/risk-cleared BUYs are allowed onto the user sheet.
    if "BUY_ELIGIBLE" not in x.columns:
        return pd.DataFrame(columns=columns)
    x["BUY_ELIGIBLE"] = x["BUY_ELIGIBLE"].astype(bool)
    x = x[x["BUY_ELIGIBLE"] & x["ACTION"].isin(BUY_ACTIONS)].copy()

    if "RISK_MANAGER_STATUS" in x.columns:
        x = x[x["RISK_MANAGER_STATUS"].astype(str).str.upper().isin(
            {"PASS", "N/A", "N/A_GATE_BLOCKED", ""}
        )].copy()

    if x.empty:
        return pd.DataFrame(columns=columns)

    score = pd.to_numeric(
        x.get("HUNTER_SCORE", x.get("PRE_BREAKOUT_SCORE", 0)),
        errors="coerce",
    ).fillna(0)
    x["_score"] = score
    x = x.sort_values("_score", ascending=False, kind="mergesort")
    x = x.drop_duplicates("SYMBOL", keep="first")

    entry = pd.to_numeric(x.get("IDEAL_ENTRY", x.get("ENTRY_PRICE")), errors="coerce")
    stop = pd.to_numeric(x.get("STOP_LOSS"), errors="coerce")
    t1 = pd.to_numeric(x.get("TARGET_1"), errors="coerce")
    t2 = pd.to_numeric(x.get("TARGET_2"), errors="coerce")
    t3 = pd.to_numeric(x.get("TARGET_3"), errors="coerce")
    risk = entry - stop

    valid = (
        entry.notna() & stop.notna() & t1.notna() & t2.notna() & t3.notna()
        & (entry > 0) & (stop > 0) & (risk > 0)
        & (t1 > entry) & (t2 > t1) & (t3 > t2)
    )
    x = x[valid].copy()
    entry, stop, t1, t2, t3, risk = (
        s[valid] for s in (entry, stop, t1, t2, t3, risk)
    )

    if x.empty:
        return pd.DataFrame(columns=columns)

    rr1 = (t1 - entry) / risk
    rr2 = (t2 - entry) / risk
    rr3 = (t3 - entry) / risk

    # Hard minimum reward floor: the first target must be at least 2.5R.
    valid_rr = rr1 >= 2.5
    x = x[valid_rr].copy()
    entry, stop, t1, t2, t3, risk = (
        s[valid_rr] for s in (entry, stop, t1, t2, t3, risk)
    )
    rr1, rr2, rr3 = rr1[valid_rr], rr2[valid_rr], rr3[valid_rr]

    if x.empty:
        return pd.DataFrame(columns=columns)

    def why(row):
        parts = []
        for col, label in (
            ("TREND", "Trend"),
            ("RELATIVE_STRENGTH", "RS"),
            ("RS_VS_UNIVERSE", "RS"),
            ("VOLUME_RATIO", "Volume"),
            ("RSI14", "RSI"),
            ("BREAKOUT_STATUS", "Breakout"),
        ):
            value = str(row.get(col, "")).strip()
            if value and value.lower() not in {"nan", "none"}:
                parts.append(f"{label}: {value}")
        return " | ".join(dict.fromkeys(parts))[:220] or "Technical + risk/reward gates passed"

    qty = pd.to_numeric(x.get("POSITION_QTY", 0), errors="coerce").fillna(0)
    capital = pd.to_numeric(x.get("CAPITAL_ALLOCATED", 0), errors="coerce").fillna(0)
    risk_amount = pd.to_numeric(x.get("RISK_AMOUNT", 0), errors="coerce").fillna(0)

    result = pd.DataFrame({
        "RANK": range(1, len(x) + 1),
        "BUY": x["SYMBOL"].astype(str).str.upper().values,
        "ENTRY": entry.round(2).values,
        "STOP LOSS": stop.round(2).values,
        "T1": t1.round(2).values,
        "T2": t2.round(2).values,
        "T3": t3.round(2).values,
        "T1 R:R": rr1.round(2).values,
        "T2 R:R": rr2.round(2).values,
        "T3 R:R": rr3.round(2).values,
        "RISK %": ((risk / entry) * 100).round(2).values,
        "QTY": qty.loc[x.index].astype(int).values,
        "CAPITAL": capital.loc[x.index].round(2).values,
        "RISK AMOUNT": risk_amount.loc[x.index].round(2).values,
        "WHY": [why(row) for _, row in x.iterrows()],
    })
    return result.head(10).reset_index(drop=True)


def build_status(plan, hunter, backtest, oos, v7):
    data_date = ""
    if not hunter.empty and "DATE" in hunter.columns:
        dates = pd.to_datetime(hunter["DATE"], errors="coerce").dropna()
        if not dates.empty:
            data_date = dates.max().strftime("%Y-%m-%d")

    regime = ""
    if not hunter.empty and "MARKET_REGIME" in hunter.columns:
        vals = hunter["MARKET_REGIME"].dropna().astype(str)
        if not vals.empty:
            regime = vals.mode().iloc[0]

    rows = [
        ["RY APEX MATRIX — SYSTEM STATUS"],
        ["STATUS", "READY"],
        ["DATA DATE", data_date],
        ["MARKET REGIME", regime or "UNKNOWN"],
        ["VALID BUY SETUPS", len(plan)],
        ["HUNTER ROWS", len(hunter)],
        ["BACKTEST TRADES", int(pd.to_numeric(backtest.get("trades", 0), errors="coerce") or 0)],
        ["OOS STATUS", oos],
        ["V7 STATUS", v7],
        ["UPDATED UTC", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")],
    ]
    return rows


def open_book():
    raw = os.getenv("GCP_CREDENTIALS", "")
    if not raw:
        raise RuntimeError("GCP_CREDENTIALS missing")
    creds = Credentials.from_service_account_info(
        json.loads(raw),
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    gc = gspread.authorize(creds)
    url = os.getenv("GOOGLE_SHEET_URL") or os.getenv("SHEET_URL")
    return gc.open_by_url(url) if url else gc.open_by_key(
        os.getenv("SPREADSHEET_ID") or DEFAULT_SHEET_ID
    )


def ensure_sheet(book, title, rows=100, cols=20):
    try:
        return book.worksheet(title)
    except WorksheetNotFound:
        return book.add_worksheet(title=title, rows=rows, cols=cols)


def write_sheet(ws, values, freeze_rows):
    rows_needed = max(20, len(values) + 5)
    cols_needed = max(20, max(len(row) for row in values) + 2)
    if ws.row_count < rows_needed:
        ws.add_rows(rows_needed - ws.row_count)
    if ws.col_count < cols_needed:
        ws.add_cols(cols_needed - ws.col_count)

    last_error = None
    for attempt in range(5):
        try:
            ws.clear()
            ws.update(range_name="A1", values=values, value_input_option="USER_ENTERED")
            ws.freeze(rows=freeze_rows)
            return
        except APIError as exc:
            last_error = exc
            if "429" not in str(exc):
                raise
            time.sleep(min(30, 2 ** attempt * 2))
    raise last_error


def remove_extra_sheets(book):
    # Delete every old user-facing tab. Backend CSV artifacts are untouched.
    for ws in list(book.worksheets()):
        if ws.title not in KEEP_SHEETS:
            try:
                book.del_worksheet(ws)
                print("DELETED OLD SHEET:", ws.title)
            except APIError as exc:
                # Do not fail the entire trading pipeline if a stale/locked tab
                # cannot be deleted; the canonical tabs are still published.
                print("WARNING: could not delete sheet", ws.title, exc)


def main():
    hunter = read_csv("early_hunter.csv")
    plan = build_action_plan(hunter)

    backtest_df = read_csv("backtest_summary.csv")
    backtest = backtest_df.iloc[0].to_dict() if not backtest_df.empty else {}

    oos = "UNKNOWN"
    aq = read_csv("action_quality_summary.csv")
    if not aq.empty:
        if "status" in aq.columns and aq["status"].astype(str).str.upper().eq("WAITING_FOR_DATA").any():
            oos = "WAITING FOR DATA"
        elif "ok" in aq.columns:
            oos = "PASS" if aq["ok"].astype(str).str.lower().eq("true").any() else "BLOCKED"

    v7_df = read_csv("v7_false_breakout_validation.csv")
    v7 = "AVAILABLE" if not v7_df.empty else "NOT AVAILABLE"

    book = open_book()
    remove_extra_sheets(book)

    action_values = [["RY APEX MATRIX — ACTION PLAN"],
                     ["ONLY FINAL QUALITY/RISK-CLEARED BUY SETUPS"]]
    if plan.empty:
        action_values.append(["NO VALID BUY TODAY"])
    else:
        action_values.append(list(plan.columns))
        action_values.extend([[clean(v) for v in row] for row in plan.itertuples(index=False, name=None)])

    write_sheet(ensure_sheet(book, "ACTION PLAN", 100, 20), action_values, 2)

    status_values = build_status(plan, hunter, backtest, oos, v7)
    write_sheet(ensure_sheet(book, "SYSTEM STATUS", 30, 10), status_values, 1)

    print(f"CANONICAL SHEETS PUBLISHED | ACTION PLAN={len(plan)} | SYSTEM STATUS=1 | EXTRA TABS REMOVED")


if __name__ == "__main__":
    main()

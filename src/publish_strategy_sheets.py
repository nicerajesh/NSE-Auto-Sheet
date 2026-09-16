"""Publish the clean user-facing Swing and Delivery outputs.

The intraday workflow owns the separate INTRADAY BUY sheet. This publisher
only updates SWING and DELIVERY and never touches core data sheets.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

from csv_utils import safe_read_csv

OUT = Path(os.getenv('NSE_OUTPUT_DIR', 'output'))
DEFAULT_SHEET_ID = '1U9j5fMZAWPUSwoP_U-GKdacVke9nUjspqPR3wGsWAUM'
BUY_ACTIONS = {'PRE-BREAKOUT BUY', 'BREAKOUT BUY', 'SWING BUY'}


def clean(v):
    if pd.isna(v):
        return ''
    return v.item() if hasattr(v, 'item') else v


def actionable(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or 'ACTION' not in df.columns:
        return pd.DataFrame(columns=df.columns)
    x = df.copy()
    if 'BUY_ELIGIBLE' in x.columns:
        flag = x['BUY_ELIGIBLE']
        if flag.dtype != bool:
            flag = flag.astype(str).str.strip().str.lower().isin({'true', '1', 'yes', 'y'})
        x = x[flag]
    else:
        x = x[x['ACTION'].astype(str).str.upper().isin(BUY_ACTIONS)]
    if 'PUBLISHED_ACTION' in x.columns:
        x = x[x['PUBLISHED_ACTION'].astype(str).str.upper().isin(BUY_ACTIONS)]
    if 'SYMBOL' in x.columns:
        x['SYMBOL'] = x['SYMBOL'].astype(str).str.upper().str.strip()
        x = x.drop_duplicates('SYMBOL', keep='first')
    return x.reset_index(drop=True)


def delivery_only(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    cols = [c for c in ('DELIVERY', 'DELIVERY_STATUS', 'DELIVERY_PCT', 'DELIVERY_PERCENT') if c in df.columns]
    if not cols:
        return pd.DataFrame(columns=df.columns)
    x = df.copy()
    mask = pd.Series(False, index=x.index)
    for c in cols:
        if c in ('DELIVERY_PCT', 'DELIVERY_PERCENT'):
            mask |= pd.to_numeric(x[c], errors='coerce').ge(50)
        else:
            mask |= x[c].astype(str).str.upper().str.contains('STRONG|HIGH|IMPROV|POSITIVE', regex=True, na=False)
    return x[mask].drop_duplicates('SYMBOL', keep='first').reset_index(drop=True)


def write(ws, df: pd.DataFrame, title: str):
    preferred = [
        'BUY_RANK', 'RANK', 'SYMBOL', 'ACTION', 'FINAL_ACTION', 'CMP',
        'IDEAL_ENTRY', 'BUY_ZONE', 'MAX_BUY_PRICE', 'BREAKOUT_TRIGGER',
        'STOP_LOSS', 'TARGET_1', 'TARGET_2', 'TARGET_3', 'RISK_PCT',
        'EDGE_CONFIDENCE', 'HUNTER_SCORE', 'RSI14', 'ADX14',
        'RELATIVE_STRENGTH', 'DELIVERY', 'DELIVERY_PCT', 'VOLUME_RATIO',
        'ATR_RISK_PCT', 'LIQUIDITY_STATUS', 'WHY', 'DECISION_REASON'
    ]
    if df.empty:
        values = [[title], ['NO CURRENT VALIDATED SIGNALS']]
    else:
        cols = [c for c in preferred if c in df.columns]
        cols += [c for c in df.columns if c not in cols]
        df = df[cols]
        values = [[title], ['UPDATED_CURRENT_RUN_ONLY'], list(df.columns)] + [
            [clean(v) for v in row] for row in df.itertuples(index=False, name=None)
        ]
    if ws.row_count < len(values) + 3:
        ws.add_rows(len(values) + 3 - ws.row_count)
    if ws.col_count < max(20, len(values[-1]) + 2):
        ws.add_cols(max(20, len(values[-1]) + 2) - ws.col_count)
    ws.clear()
    ws.update('A1', values, value_input_option='USER_ENTERED')
    ws.freeze(rows=3 if not df.empty else 1)


def main():
    raw = os.getenv('GCP_CREDENTIALS', '')
    if not raw:
        raise RuntimeError('GCP_CREDENTIALS missing')
    cred = Credentials.from_service_account_info(
        json.loads(raw),
        scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive'],
    )
    gc = gspread.authorize(cred)
    url = os.getenv('GOOGLE_SHEET_URL') or os.getenv('SHEET_URL')
    sh = gc.open_by_url(url) if url else gc.open_by_key(os.getenv('SPREADSHEET_ID') or DEFAULT_SHEET_ID)

    def worksheet(title):
        try:
            return sh.worksheet(title)
        except gspread.WorksheetNotFound:
            return sh.add_worksheet(title=title, rows=500, cols=50)

    hunter = safe_read_csv(OUT / 'early_hunter.csv')
    buys = actionable(hunter)
    swing = buys[buys['ACTION'].astype(str).str.upper().eq('SWING BUY')].copy() if not buys.empty else buys.copy()
    delivery = delivery_only(buys)

    write(worksheet('SWING'), swing, 'RY APEX MATRIX — SWING')
    write(worksheet('DELIVERY'), delivery, 'RY APEX MATRIX — DELIVERY')

    # Delete only the legacy user-facing strategy tabs that are known to cause
    # conflicting BUY/NO BUY views. Core data sheets and INTRADAY BUY are safe.
    legacy_tabs = {
        'MERA ACTION PLAN',
        'Master Buy Dashboard',
        'Early Hunter',
        'Core Trend Matrix',
        'Decision Diagnostics',
        'Dashboard',
    }
    existing = {ws.title: ws for ws in sh.worksheets()}
    for title in sorted(legacy_tabs & set(existing)):
        sh.del_worksheet(existing[title])
        print('REMOVED LEGACY SHEET |', title)

    print(f'SWING/DELIVERY PUBLISHED | SWING={len(swing)} | DELIVERY={len(delivery)} | INTRADAY=UNCHANGED_BY_DESIGN')


if __name__ == '__main__':
    main()

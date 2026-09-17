"""Publish the single clean user-facing Swing/Delivery views.

Design goals:
- VALIDATED BUY remains the strict, historically validated signal.
- RESEARCH BUY surfaces technically strong candidates when the historical
  release gate is blocked, instead of hiding them as NO BUY.
- Risk/incomplete-plan candidates are never promoted to RESEARCH BUY.
- Core data/diagnostic CSVs stay in the artifact; Google Sheets stays simple.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import gspread
import numpy as np
import pandas as pd
from google.oauth2.service_account import Credentials

from csv_utils import safe_read_csv

OUT = Path(os.getenv('NSE_OUTPUT_DIR', 'output'))
DEFAULT_SHEET_ID = '1U9j5fMZAWPUSwoP_U-GKdacVke9nUjspqPR3wGsWAUM'
BUY_ACTIONS = {'PRE-BREAKOUT BUY', 'BREAKOUT BUY', 'SWING BUY'}
BLOCK_WORDS = {'QUALITY BLOCKED', 'RISK BLOCKED'}


def clean(v):
    if pd.isna(v):
        return ''
    return v.item() if hasattr(v, 'item') else v


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


def technical_research_ok(row) -> bool:
    """Conservative research candidate filter.

    This is deliberately independent of the historical release gate, but it
    still requires a usable trade plan and several technical confirmations.
    """
    action = str(row.get('ACTION', '')).strip().upper()
    if action not in BUY_ACTIONS:
        return False

    published = str(row.get('PUBLISHED_ACTION', '')).strip().upper()
    if published.startswith('RISK BLOCKED'):
        return False
    if published in BUY_ACTIONS:
        return True
    if not published.startswith('QUALITY BLOCKED'):
        return False

    cmp_ = num(row, 'CMP', 'CLOSE_PRICE')
    entry = num(row, 'IDEAL_ENTRY', 'ENTRY_PRICE')
    stop = num(row, 'STOP_LOSS')
    target = num(row, 'TARGET_1')
    score = num(row, 'HUNTER_SCORE', 'PRE_BREAKOUT_SCORE', 'RANK_SCORE')
    rsi = num(row, 'RSI14')
    rs = num(row, 'RELATIVE_STRENGTH', 'RS_VS_UNIVERSE')
    vol = num(row, 'VOLUME_RATIO', 'VOL_RATIO')
    atr = num(row, 'ATR_RISK_PCT', 'ATR_PCT')
    ema200 = num(row, 'EMA200')

    if not all(np.isfinite(x) for x in (cmp_, entry, stop, target, score)):
        return False
    risk = entry - stop
    reward = target - entry
    if risk <= 0 or reward <= 0 or reward / risk < 1.5:
        return False
    if score < 72:
        return False
    if np.isfinite(rsi) and not (45 <= rsi <= 72):
        return False
    if np.isfinite(rs) and rs < 0:
        return False
    if np.isfinite(vol) and vol < 0.9:
        return False
    if np.isfinite(atr) and not (0 < atr <= 6.5):
        return False
    if np.isfinite(ema200) and cmp_ <= ema200:
        return False
    return True


def build_buy_view(hunter: pd.DataFrame) -> pd.DataFrame:
    if hunter.empty or 'ACTION' not in hunter.columns:
        return pd.DataFrame(columns=hunter.columns)
    x = hunter.copy()
    x['SYMBOL'] = x.get('SYMBOL', '').astype(str).str.upper().str.strip()
    x = x[x['ACTION'].astype(str).str.upper().isin(BUY_ACTIONS)].copy()
    if x.empty:
        return x

    validated = x[x.get('BUY_ELIGIBLE', False).astype(bool)].copy() if 'BUY_ELIGIBLE' in x.columns else pd.DataFrame()
    validated['SIGNAL_STATUS'] = 'VALIDATED BUY'

    research = x[x.apply(technical_research_ok, axis=1)].copy()
    research['SIGNAL_STATUS'] = 'RESEARCH BUY'
    research['BUY_ELIGIBLE'] = False

    # Never duplicate a symbol; validated takes precedence over research.
    out = pd.concat([validated, research], ignore_index=True, sort=False)
    if out.empty:
        return out
    out['_priority'] = out['SIGNAL_STATUS'].map({'VALIDATED BUY': 0, 'RESEARCH BUY': 1}).fillna(9)
    score_col = 'HUNTER_SCORE' if 'HUNTER_SCORE' in out.columns else 'RANK_SCORE'
    if score_col in out.columns:
        out[score_col] = pd.to_numeric(out[score_col], errors='coerce')
    out = out.sort_values(['_priority', score_col] if score_col in out.columns else ['_priority'], ascending=True, kind='mergesort')
    out = out.drop_duplicates('SYMBOL', keep='first').drop(columns=['_priority'])
    out.insert(0, 'BUY_RANK', range(1, len(out) + 1))
    return out.reset_index(drop=True)


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
        'BUY_RANK', 'SIGNAL_STATUS', 'SYMBOL', 'ACTION', 'CMP',
        'IDEAL_ENTRY', 'BUY_ZONE', 'MAX_BUY_PRICE', 'BREAKOUT_TRIGGER',
        'STOP_LOSS', 'TARGET_1', 'TARGET_2', 'TARGET_3', 'RISK_PCT',
        'EDGE_CONFIDENCE', 'HUNTER_SCORE', 'PRE_BREAKOUT_SCORE', 'RSI14',
        'ADX14', 'RELATIVE_STRENGTH', 'RS_VS_UNIVERSE', 'DELIVERY',
        'DELIVERY_PCT', 'VOLUME_RATIO', 'ATR_RISK_PCT', 'ATR_PCT',
        'LIQUIDITY_STATUS', 'QUALITY_GATE', 'PUBLISHED_ACTION', 'WHY',
        'DECISION_REASON'
    ]
    if df.empty:
        values = [[title], ['NO CURRENT BUY CANDIDATES']]
    else:
        cols = [c for c in preferred if c in df.columns]
        cols += [c for c in df.columns if c not in cols]
        df = df[cols]
        values = [[title], ['VALIDATED BUY + TECHNICAL RESEARCH BUY | CURRENT RUN'], list(df.columns)] + [
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
    buys = build_buy_view(hunter)
    swing = buys.copy()
    delivery = delivery_only(buys)

    write(worksheet('SWING'), swing, 'RY APEX MATRIX — SWING BUY HUNTER')
    write(worksheet('DELIVERY'), delivery, 'RY APEX MATRIX — DELIVERY BUY HUNTER')

    # Keep the Google Sheet intentionally small. Diagnostics remain available
    # as workflow artifacts/CSV and are not competing user-facing decisions.
    legacy_tabs = {
        'MERA ACTION PLAN', 'Master Buy Dashboard', 'Early Hunter',
        'Core Trend Matrix', 'Decision Diagnostics', 'Dashboard',
        'INTRADAY WATCHLIST', 'Action Plan', 'Trading Dashboard',
    }
    existing = {ws.title: ws for ws in sh.worksheets()}
    for title in sorted(legacy_tabs & set(existing)):
        sh.del_worksheet(existing[title])
        print('REMOVED LEGACY SHEET |', title)

    print(f'CLEAN STRATEGY PUBLISH | SWING={len(swing)} | DELIVERY={len(delivery)} | VALIDATED={int((buys.SIGNAL_STATUS == "VALIDATED BUY").sum()) if not buys.empty else 0} | RESEARCH={int((buys.SIGNAL_STATUS == "RESEARCH BUY").sum()) if not buys.empty else 0}')


if __name__ == '__main__':
    main()

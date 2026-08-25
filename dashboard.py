from __future__ import annotations

import json
import os
from pathlib import Path

import gspread
import pandas as pd
from oauth2client.service_account import ServiceAccountCredentials

SPREADSHEET_ID = os.getenv('SPREADSHEET_ID', '1U9j5fMZAWPUSwoP_U-GKdacVke9nUjspqPR3wGsWAUM')
DASHBOARD_SHEET = 'Dashboard'
HUNTER_FILE = Path('output/early_hunter.csv')
BUY_FILE = Path('output/buy_candidates.csv')


def _sheet():
    raw = os.getenv('GCP_CREDENTIALS')
    if not raw:
        raise RuntimeError('GCP_CREDENTIALS secret missing')
    creds = ServiceAccountCredentials.from_json_keyfile_dict(
        json.loads(raw),
        ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive'],
    )
    return gspread.authorize(creds).open_by_key(SPREADSHEET_ID)


def _num(df, col):
    if col not in df.columns:
        return pd.Series('', index=df.index)
    return pd.to_numeric(df[col], errors='coerce')


def build_dashboard():
    if BUY_FILE.exists():
        df = pd.read_csv(BUY_FILE)
    elif HUNTER_FILE.exists():
        df = pd.read_csv(HUNTER_FILE)
    else:
        raise RuntimeError('No scanner CSV found for dashboard')

    if df.empty:
        df = pd.DataFrame(columns=['SYMBOL', 'ACTION'])

    action_col = 'NEXT_DAY_ACTION' if 'NEXT_DAY_ACTION' in df.columns else 'ACTION'
    if action_col not in df.columns:
        df[action_col] = 'WATCH'

    actionable = {
        'NEXT DAY PRE-BREAKOUT BUY',
        'NEXT DAY BREAKOUT BUY',
        'PRE-BREAKOUT BUY',
        'BREAKOUT BUY',
        'BUY NOW',
        'BUY ON BREAKOUT',
        'BREAKOUT IMMINENT',
        'SWING BUY',
    }
    candidates = df[df[action_col].astype(str).str.upper().isin(actionable)].copy()

    if candidates.empty and 'ACTION' in df.columns:
        candidates = df[df['ACTION'].astype(str).isin(['BUY NOW', 'BUY ON BREAKOUT', 'BREAKOUT IMMINENT', 'SWING BUY'])].copy()

    score_col = 'BREAKOUT_PROBABILITY' if 'BREAKOUT_PROBABILITY' in candidates.columns else 'NEXT_DAY_SETUP_SCORE'
    if score_col not in candidates.columns:
        score_col = 'HUNTER_SCORE' if 'HUNTER_SCORE' in candidates.columns else None
    if score_col:
        candidates['_score'] = _num(candidates, score_col).fillna(0)
    else:
        candidates['_score'] = 0
    candidates = candidates.sort_values(['_score'], ascending=False).head(25)

    cols = [
        'RANK', 'SYMBOL', action_col, 'BUY_DATE', 'CMP', 'ENTRY_ZONE',
        'BREAKOUT_TRIGGER', 'STOP_LOSS', 'TARGET_1', 'TARGET_2', 'TARGET_3',
        'R_R', 'RISK_PCT', 'NEXT_DAY_SETUP_SCORE', 'BREAKOUT_PROBABILITY',
        'TREND', 'ACCUMULATION', 'DELIVERY', 'VOLUME_RATIO',
        'RESISTANCE_DISTANCE_PCT', 'RELATIVE_STRENGTH', 'REASONS'
    ]
    cols = [c for c in cols if c in candidates.columns]
    table = candidates[cols].copy()
    if 'RANK' in table.columns:
        table['RANK'] = range(1, len(table) + 1)
    else:
        table.insert(0, 'RANK', range(1, len(table) + 1))

    book = _sheet()
    try:
        ws = book.worksheet(DASHBOARD_SHEET)
    except gspread.WorksheetNotFound:
        ws = book.add_worksheet(title=DASHBOARD_SHEET, rows=100, cols=max(25, len(cols) + 2))

    ws.clear()
    if ws.col_count < max(25, len(cols) + 2):
        ws.add_cols(max(25, len(cols) + 2) - ws.col_count)

    today = str(df['DATE'].iloc[0]) if 'DATE' in df.columns and len(df) else ''
    buy_count = len(candidates)
    pre_count = int(candidates[action_col].astype(str).str.contains('PRE-BREAKOUT|NEXT DAY', case=False, regex=True).sum()) if buy_count else 0
    breakout_count = int(candidates[action_col].astype(str).str.contains('BREAKOUT', case=False, regex=True).sum()) if buy_count else 0
    swing_count = int(candidates[action_col].astype(str).str.contains('SWING', case=False, regex=True).sum()) if buy_count else 0

    rows = [
        ['NSE EARLY HUNTER — BUY DASHBOARD'],
        ['Data Date', today],
        ['Purpose', 'Stocks to consider for BUY with entry, stop-loss and targets'],
        ['Total BUY Candidates', buy_count],
        ['Pre-Breakout / Next-Day', pre_count],
        ['Breakout BUY', breakout_count],
        ['Swing BUY', swing_count],
        [],
        ['TOP BUY CANDIDATES'],
    ]
    rows.append(table.columns.tolist())
    for _, r in table.iterrows():
        vals = []
        for c in table.columns:
            v = r[c]
            if pd.isna(v):
                v = ''
            vals.append(v)
        rows.append(vals)

    ws.update('A1', rows, value_input_option='USER_ENTERED')
    ws.freeze(rows=10)

    # Compact formatting: title, header and key price/target columns.
    try:
        ws.format('A1:Z1', {'textFormat': {'bold': True, 'fontSize': 14}})
        ws.format(f'A10:{chr(64 + min(len(table.columns), 26))}10', {'textFormat': {'bold': True}})
        header_row = 10
        end_row = max(header_row + 1, 9 + len(table))
        ws.format(f'A{header_row}:Z{end_row}', {'wrapStrategy': 'WRAP'})
        ws.format('A1:B7', {'textFormat': {'bold': True}})
        for c in ('CMP', 'BREAKOUT_TRIGGER', 'STOP_LOSS', 'TARGET_1', 'TARGET_2', 'TARGET_3', 'RISK_PCT', 'BREAKOUT_PROBABILITY'):
            if c in table.columns:
                idx = table.columns.get_loc(c) + 1
                letter = gspread.utils.rowcol_to_a1(1, idx)[:-1]
                ws.format(f'{letter}{header_row+1}:{letter}{end_row}', {'numberFormat': {'type': 'NUMBER', 'pattern': '0.00'}})
    except Exception as exc:
        print('Dashboard formatting warning:', exc)

    print(f'Dashboard updated: {buy_count} BUY candidates')


if __name__ == '__main__':
    build_dashboard()

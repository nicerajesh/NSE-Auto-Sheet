from __future__ import annotations

import json
import os
from pathlib import Path

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

from csv_utils import safe_read_csv, safe_to_csv

OUT = Path(os.getenv('NSE_OUTPUT_DIR', str(Path(__file__).resolve().parents[1] / 'output')))
SHEET_ID = os.getenv('SPREADSHEET_ID', '1U9j5fMZAWPUSwoP_U-GKdacVke9nUjspqPR3wGsWAUM')


def read(name: str) -> pd.DataFrame:
    p = OUT / name
    return safe_read_csv(p) if p.exists() else pd.DataFrame()


def publish(plan: pd.DataFrame) -> None:
    raw = os.getenv('GCP_CREDENTIALS', '')
    if not raw:
        raise RuntimeError('GCP_CREDENTIALS missing')
    gc = gspread.authorize(
        Credentials.from_service_account_info(
            json.loads(raw),
            scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive'],
        )
    )
    sh = gc.open_by_key(SHEET_ID)
    matrix = [list(plan.columns)] + [
        [v.item() if hasattr(v, 'item') else ('' if pd.isna(v) else v) for v in row]
        for row in plan.itertuples(index=False, name=None)
    ]
    for title in ('MERA ACTION PLAN', 'Aaj Kya Karna Hai'):
        try:
            ws = sh.worksheet(title)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=title, rows=max(100, len(matrix) + 10), cols=max(20, len(matrix[0]) + 2))
        if ws.row_count < len(matrix) + 5:
            ws.add_rows(len(matrix) + 5 - ws.row_count)
        if ws.col_count < len(matrix[0]) + 2:
            ws.add_cols(len(matrix[0]) + 2 - ws.col_count)
        ws.clear()
        ws.update(range_name='A1', values=matrix, value_input_option='USER_ENTERED')
        try:
            ws.freeze(rows=1)
        except Exception:
            pass


def main() -> None:
    existing = read('mera_action_plan.csv')
    if not existing.empty:
        print('ACTION PLAN FALLBACK: existing plan has rows; nothing to do')
        return

    rows = []
    sources = [
        ('low52_reversal.csv', '52W LOW WATCH', '52 Week Low'),
        ('apex_matrix.csv', 'APEX WATCH', 'APEX'),
        ('stealth_accumulation.csv', 'STEALTH WATCH', 'Stealth'),
    ]
    for filename, default_action, mode in sources:
        df = read(filename)
        if df.empty or 'SYMBOL' not in df.columns:
            continue
        for _, r in df.head(20).iterrows():
            action = str(r.get('ACTION', r.get('SIGNAL', default_action)) or default_action)
            if 'BUY' in action.upper():
                action = 'WAIT — QUALITY GATE'
            price = r.get('CMP', r.get('ENTRY_PRICE', r.get('ENTRY', '')))
            stop = r.get('STOP_LOSS', r.get('INITIAL_SL', ''))
            target = r.get('TARGET_1', r.get('TARGET', ''))
            reason = r.get('REASONS', 'Scanner setup — confirmation required')
            rows.append({
                'SYMBOL': r.get('SYMBOL', ''),
                'KYA KARU': '🟡 ' + action,
                'PRICE': price,
                'QTY': '',
                'STOP LOSS': stop,
                'TARGET': target,
                'PROFIT/LOSS %': '',
                'WHY': reason,
                'MODE': mode,
            })

    if rows:
        plan = pd.DataFrame(rows).drop_duplicates('SYMBOL').head(50)
    else:
        plan = pd.DataFrame([{
            'TYPE': 'TODAY SUMMARY',
            'STATUS': 'NO CONFIRMED BUY — CHECK SCANNER TABS',
            'NOTE': 'No scanner watch rows were available. This is a valid no-signal day, not a data failure.',
        }])

    safe_to_csv(plan, OUT / 'mera_action_plan.csv')
    publish(plan)
    print('ACTION PLAN FALLBACK: published', len(plan), 'rows')


if __name__ == '__main__':
    main()

from __future__ import annotations
import os
from pathlib import Path
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

OUT = Path('output')


def _credentials():
    raw = os.getenv('GCP_CREDENTIALS', '')
    if not raw:
        raise RuntimeError('GCP_CREDENTIALS missing')
    import json
    info = json.loads(raw)
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    return Credentials.from_service_account_info(info, scopes=scopes)


def _clean(v):
    if pd.isna(v):
        return ''
    if isinstance(v, (dict, list, tuple, set)):
        return str(v)
    if hasattr(v, 'item'):
        try:
            return v.item()
        except Exception:
            pass
    return v


def _matrix(df):
    if df.empty:
        return [['NO DATA']]
    cols = [str(c) for c in df.columns]
    rows = [[_clean(v) for v in row] for row in df.itertuples(index=False, name=None)]
    return [cols] + rows


def _write(ws, df):
    values = _matrix(df)
    ws.clear()
    ws.update(range_name='A1', values=values, value_input_option='USER_ENTERED')
    try:
        ws.freeze(rows=1)
    except Exception:
        pass


def main():
    hunter_path = OUT / 'early_hunter.csv'
    buy_path = OUT / 'buy_candidates.csv'
    dash_path = OUT / 'dashboard.csv'
    if not hunter_path.exists():
        raise RuntimeError('output/early_hunter.csv missing')

    hunter = pd.read_csv(hunter_path)
    buy = pd.read_csv(buy_path) if buy_path.exists() else hunter.iloc[0:0].copy()
    dash = pd.read_csv(dash_path) if dash_path.exists() else pd.DataFrame()

    gc = gspread.authorize(_credentials())
    sheet_url = os.getenv('GOOGLE_SHEET_URL', '')
    if not sheet_url:
        sheet_url = os.getenv('SHEET_URL', '')
    if not sheet_url:
        raise RuntimeError('GOOGLE_SHEET_URL/SHEET_URL missing')
    sh = gc.open_by_url(sheet_url)

    def get_or_create(title):
        try:
            return sh.worksheet(title)
        except gspread.WorksheetNotFound:
            return sh.add_worksheet(title=title, rows=max(100, len(hunter)+10), cols=max(20, len(hunter.columns)+2))

    _write(get_or_create('Early Hunter'), hunter)
    _write(get_or_create('Buy Candidates'), buy)
    if not dash.empty:
        _write(get_or_create('Dashboard'), dash)
    print(f'SHEET PUBLISH OK: hunter={len(hunter)} buy_candidates={len(buy)}')


if __name__ == '__main__':
    main()

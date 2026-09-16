import json
import os
from pathlib import Path

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

from csv_utils import safe_read_csv

OUT = Path(os.getenv('NSE_OUTPUT_DIR', 'output'))
DEFAULT_SHEET_ID = '1U9j5fMZAWPUSwoP_U-GKdacVke9nUjspqPR3wGsWAUM'


def clean(v):
    if pd.isna(v):
        return ''
    return v.item() if hasattr(v, 'item') else v


def write(ws, df):
    if df.empty:
        values = [['NO INTRADAY BUY SIGNALS']] 
    else:
        preferred = [
            'INTRADAY_RANK','SYMBOL','INTRADAY_ACTION','CMP','IDEAL_ENTRY',
            'STOP_LOSS','TARGET_1','TARGET_2','INTRADAY_RR','RSI14','ADX14',
            'VOLUME_RATIO','RELATIVE_STRENGTH','ATR_RISK_PCT',
            'LIQUIDITY_STATUS','WHY','INTRADAY_REASON'
        ]
        cols = [c for c in preferred if c in df.columns]
        cols += [c for c in df.columns if c not in cols]
        df = df[cols]
        values = [list(df.columns)] + [[clean(v) for v in row] for row in df.itertuples(index=False, name=None)]
    if ws.row_count < len(values) + 3:
        ws.add_rows(len(values) + 3 - ws.row_count)
    if ws.col_count < max(20, len(values[0]) + 2):
        ws.add_cols(max(20, len(values[0]) + 2) - ws.col_count)
    ws.clear()
    ws.update('A1', values, value_input_option='USER_ENTERED')
    ws.freeze(rows=1)


def main():
    raw = os.getenv('GCP_CREDENTIALS', '')
    if not raw:
        raise RuntimeError('GCP_CREDENTIALS missing')
    cred = Credentials.from_service_account_info(
        json.loads(raw),
        scopes=['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive'],
    )
    gc = gspread.authorize(cred)
    url = os.getenv('GOOGLE_SHEET_URL') or os.getenv('SHEET_URL')
    sh = gc.open_by_url(url) if url else gc.open_by_key(os.getenv('SPREADSHEET_ID') or DEFAULT_SHEET_ID)

    def worksheet(title):
        try:
            return sh.worksheet(title)
        except gspread.WorksheetNotFound:
            return sh.add_worksheet(title=title, rows=500, cols=50)

    buy = safe_read_csv(OUT / 'intraday_buy_signals.csv')
    watch = safe_read_csv(OUT / 'intraday_watchlist.csv')
    write(worksheet('INTRADAY BUY SIGNALS'), buy)
    write(worksheet('INTRADAY WATCHLIST'), watch)
    print('INTRADAY SHEETS PUBLISHED | BUY=', len(buy), '| WATCHLIST=', len(watch))


if __name__ == '__main__':
    main()

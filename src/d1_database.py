from __future__ import annotations
import math, os
from pathlib import Path
import pandas as pd

# D1 was removed from the runtime. This module is kept only as a compatibility
# shim because older modules import these function names. All persistence is
# local in output/persistent_history.csv; no Cloudflare API is contacted.
ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.getenv('NSE_OUTPUT_DIR', str(ROOT / 'output'))).resolve()
HISTORY = OUT / 'persistent_history.csv'


def _history():
    if not HISTORY.is_file():
        return pd.DataFrame(columns=['SYMBOL','DATE','OPEN_PRICE','HIGH_PRICE','LOW_PRICE','CLOSE_PRICE','TTL_TRD_QNTY','TURNOVER_LACS','DELIV_QTY','DELIV_PER'])
    try:
        df = pd.read_csv(HISTORY)
        if 'DATE' in df.columns:
            df['DATE'] = pd.to_datetime(df['DATE'], errors='coerce')
        return df
    except Exception as e:
        print('LOCAL HISTORY warning:', e)
        return pd.DataFrame()


def setup():
    # Compatibility only: intentionally does not call Cloudflare D1.
    OUT.mkdir(parents=True, exist_ok=True)
    df = _history()
    print('LOCAL HISTORY READY:', len(df), 'rows |', df['DATE'].nunique() if 'DATE' in df.columns else 0, 'sessions')
    return True


def query(sql, params=None, required=False):
    """Small compatibility layer for the two history queries used by the runner."""
    df = _history()
    q = ' '.join(str(sql).lower().split())
    if 'count(*) as n' in q and 'count(distinct trade_date)' in q:
        n = len(df)
        sessions = int(df['DATE'].nunique()) if 'DATE' in df.columns else 0
        max_date = None
        if 'DATE' in df.columns and not df.empty:
            max_date = pd.to_datetime(df['DATE'], errors='coerce').max()
            max_date = None if pd.isna(max_date) else max_date.strftime('%Y-%m-%d')
        return {'success': True, 'result': [{'results': [{'n': n, 'sessions': sessions, 'max_date': max_date}]}]}
    if 'select symbol,trade_date,open,high,low,close,volume,turnover_lacs,delivery_qty,delivery_pct' in q:
        if df.empty:
            rows = []
        else:
            rows_df = df.copy()
            p = params or []
            start = pd.to_datetime(p[0], errors='coerce') if len(p) > 0 else None
            end = pd.to_datetime(p[1], errors='coerce') if len(p) > 1 else None
            if start is not None and not pd.isna(start): rows_df = rows_df[rows_df['DATE'] >= start]
            if end is not None and not pd.isna(end): rows_df = rows_df[rows_df['DATE'] <= end]
            rename = {'SYMBOL':'symbol','DATE':'trade_date','OPEN_PRICE':'open','HIGH_PRICE':'high','LOW_PRICE':'low','CLOSE_PRICE':'close','TTL_TRD_QNTY':'volume','TURNOVER_LACS':'turnover_lacs','DELIV_QTY':'delivery_qty','DELIV_PER':'delivery_pct'}
            rows_df = rows_df.rename(columns=rename)
            for c in ['trade_date']:
                if c in rows_df: rows_df[c] = pd.to_datetime(rows_df[c]).dt.strftime('%Y-%m-%d')
            rows = rows_df.to_dict('records')
        return {'success': True, 'result': [{'results': rows}]}
    if required:
        # Do not fail the run merely because an old caller asks for a D1-only query.
        return {'success': True, 'result': [{'results': []}]}
    return None


def batch(items, required=False):
    # D1 batch writes are intentionally disabled. Persistent runner writes the
    # canonical local CSV directly after fetching NSE data.
    return {'success': True, 'result': []}


def load_open_trades(required=False):
    # Local trade ledger is maintained by the newer pipeline; there is no D1.
    return []


def sync_ledger(ledger, required=False):
    return None


def sync_latest(latest, hunter, stats, run_date, gate_ok=False):
    # Retained for callers that still invoke it. No remote database write.
    print(f'LOCAL HISTORY: D1 sync skipped | market rows={len(latest)} | signals={len(hunter)} | gate_ok={gate_ok}')
    return None

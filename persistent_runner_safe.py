from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd
import persistent_runner as pr

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'output'

def make_runner_safe():
    """Generate the legacy scanner with persistent D1 data and all legacy scope names intact."""
    src = (ROOT / 'update_sheet.py').read_text(encoding='utf-8')
    start = 's=sess();universe=fetch_nifty500_symbols(s);frames=[];d=datetime.now();attempts=0'
    end = "if not frames:raise RuntimeError('No NIFTY 500 NSE bhavcopy data found')"
    a = src.find(start)
    b = src.find(end, a)
    if a < 0 or b < 0:
        raise RuntimeError('Legacy history loader not found in update_sheet.py')
    b += len(end)
    hist_path = OUT / 'persistent_history.csv'
    if not hist_path.exists():
        raise RuntimeError('persistent_history.csv missing')
    hist = pd.read_csv(hist_path, parse_dates=['DATE'])
    if hist.empty:
        raise RuntimeError('persistent_history.csv is empty')
    # The legacy script expects these names later for status/diagnostics.
    # IMPORTANT: frames must be one DataFrame per trading session, not one giant DataFrame.
    safe = (
        "_persistent_hist=pd.read_csv('output/persistent_history.csv',parse_dates=['DATE']);"
        "universe=set(_persistent_hist['SYMBOL'].astype(str).str.upper());"
        "frames=[g.copy() for _,g in _persistent_hist.groupby('DATE',sort=True)];"
        "print(f'PERSISTENT D1 INPUT: {len(_persistent_hist)} rows | {len(frames)} sessions');"
        "del _persistent_hist"
    )
    src = src[:a] + safe + src[b:]
    # Never let the legacy script write nested backtest/calibration dictionaries into Hunter.
    src = src.replace(
        "ws_hunter.update(values=hrows,range_name='A1',value_input_option='USER_ENTERED')",
        "print('SAFE SHEET PATH: skipping legacy Early Hunter write; repair_sheet_output.py will publish flat rows')"
    )
    return src

def main():
    # Reuse the already-fixed D1 incremental loader, but replace only the unsafe legacy wrapper.
    pr.make_runner = make_runner_safe
    return pr.main()

if __name__ == '__main__':
    raise SystemExit(main())

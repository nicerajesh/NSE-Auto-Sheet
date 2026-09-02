from __future__ import annotations
from pathlib import Path
import persistent_runner as pr

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'output'


def make_runner_safe():
    """Run the current scanner against the already-built persistent D1 history.

    Do not depend on the old history-loader source text: update_sheet.py has its
    own D1/incremental loader now, so matching the former code block is brittle.
    """
    src = (ROOT / 'update_sheet.py').read_text(encoding='utf-8')
    hist_path = OUT / 'persistent_history.csv'
    if not hist_path.exists():
        raise RuntimeError('persistent_history.csv missing')

    # Current update_sheet.py starts its market-history loading here. Replace
    # that whole loader through the existing empty-history guard with the
    # persistent CSV prepared by persistent_runner.py.
    start = "s=sess();universe=fetch_nifty500_symbols(s);hist=load_d1_history();frames=[]"
    end = "if hist.empty:raise RuntimeError('No NIFTY 500 history available in D1 or NSE bhavcopy')"
    a = src.find(start)
    b = src.find(end, a)
    if a < 0 or b < 0:
        raise RuntimeError('Current persistent loader anchor not found in update_sheet.py')
    b += len(end)

    safe = (
        "import pandas as pd;"
        "_persistent_hist=pd.read_csv('output/persistent_history.csv',parse_dates=['DATE']);"
        "universe=set(_persistent_hist['SYMBOL'].astype(str).str.upper());"
        "hist=_persistent_hist.copy();"
        "frames=[g.copy() for _,g in hist.groupby('DATE',sort=True)];"
        "print(f'PERSISTENT D1 INPUT: {len(hist)} rows | {len(frames)} sessions');"
        "del _persistent_hist"
    )
    src = src[:a] + safe + src[b:]

    # The legacy direct Hunter write is intentionally bypassed. The dedicated
    # repair_sheet_output.py step publishes only flat scalar cells.
    legacy_write = "ws_hunter.update(values=hrows,range_name='A1',value_input_option='USER_ENTERED')"
    src = src.replace(
        legacy_write,
        "print('SAFE SHEET PATH: skipping legacy Early Hunter write; repair_sheet_output.py will publish flat rows')"
    )
    return src


def main():
    pr.make_runner = make_runner_safe
    return pr.main()


if __name__ == '__main__':
    raise SystemExit(main())

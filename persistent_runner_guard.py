from __future__ import annotations
import runpy
from pathlib import Path

p=Path(__file__).with_name('persistent_runner.py')
s=p.read_text(encoding='utf-8')
# The generated legacy runner must retain the NIFTY500 universe variable.
s=s.replace(
    "frames=[pd.read_csv(OUT/'persistent_history.csv',parse_dates=['DATE'])];print(f'PERSISTENT D1 INPUT: {len(frames[0])} rows')",
    "universe=fetch_nifty500_symbols(s);frames=[pd.read_csv(OUT/'persistent_history.csv',parse_dates=['DATE'])];print(f'PERSISTENT D1 INPUT: {len(frames[0])} rows | {frames[0].DATE.nunique()} sessions')"
)
# Prevent the old nested Hunter payload from ever reaching gspread.
s=s.replace(
    "ws_hunter.update(values=hrows,range_name='A1',value_input_option='USER_ENTERED')",
    "print('SAFE SHEET PATH: skipping legacy Early Hunter write; repair_sheet_output.py will publish flat rows')"
)
# The old status used len(frames), which is 1 because persistent history is one DataFrame.
s=s.replace("History {len(frames)} days", "History {hist.DATE.nunique()} sessions")
# Refuse to publish if the persistent history was accidentally reduced to a single session.
needle="hist.to_csv(OUT/'persistent_history.csv',index=False)"
replacement="hist.to_csv(OUT/'persistent_history.csv',index=False)\n    _sessions=int(pd.to_datetime(hist.DATE).nunique())\n    if _sessions < 300: raise RuntimeError(f'PERSISTENT D1 integrity failure: only {_sessions} sessions available')"
s=s.replace(needle,replacement)
# Execute the patched source in the same process/environment.
tmp=p.with_name('_persistent_runner_patched.py'); tmp.write_text(s,encoding='utf-8')
try:
    runpy.run_path(str(tmp),run_name='__main__')
finally:
    try: tmp.unlink()
    except OSError: pass

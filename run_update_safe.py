from __future__ import annotations
import subprocess, sys, os

print('SAFE RUNNER: starting update_sheet.py')
proc=subprocess.run([sys.executable,'update_sheet.py'],env=os.environ.copy())
if proc.returncode==0:
    print('SAFE RUNNER: update_sheet.py completed successfully')
    raise SystemExit(0)

print(f'SAFE RUNNER: update_sheet.py failed with exit code {proc.returncode}')
required=['output/early_hunter.csv','output/backtest_summary.csv']
missing=[p for p in required if not os.path.exists(p)]
if missing:
    print('SAFE RUNNER: cannot recover; missing:', ', '.join(missing))
    raise SystemExit(proc.returncode)

# The scanner has already produced the CSV outputs. Never let the legacy
# Google-Sheets writer crash the whole pipeline because of nested summary rows.
# Rebuild the Sheets from the scalarized CSV outputs instead.
for script in ('sheet_writer_hotfix.py','repair_sheet_output.py'):
    if os.path.exists(script):
        print('SAFE RUNNER: executing',script)
        rc=subprocess.run([sys.executable,script],env=os.environ.copy()).returncode
        if rc==0:
            print('SAFE RUNNER: recovery completed with',script)
            raise SystemExit(0)
        print('SAFE RUNNER:',script,'failed with exit code',rc)

print('SAFE RUNNER: all recovery writers failed')
raise SystemExit(proc.returncode)

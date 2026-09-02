from __future__ import annotations
import os
from pathlib import Path
import persistent_runner as pr


def preflight():
    repo=Path(__file__).resolve().parents[1]
    src=Path(__file__).resolve().parent
    out=Path(os.getenv('NSE_OUTPUT_DIR', str(repo/'output'))).resolve()
    expected=src/'update_sheet.py'
    legacy=repo/'update_sheet.py'
    out.mkdir(parents=True, exist_ok=True)
    if not expected.is_file():
        raise RuntimeError(f'update_sheet.py missing at expected path: {expected}. This repo must keep update_sheet.py under src/. Legacy root path exists={legacy.is_file()}')
    print(f'V3 PREFLIGHT: repo={repo}')
    print(f'V3 PREFLIGHT: src={src}')
    print(f'V3 PREFLIGHT: NSE_OUTPUT_DIR={out}')
    print(f'V3 PREFLIGHT: update_sheet={expected}')

_ORIGINAL_MAKE_RUNNER=pr.make_runner


def make_runner_v3():
    src=_ORIGINAL_MAKE_RUNNER()
    needle='from __future__ import annotations\n'
    patch=needle+'import v3_engine\nv3_engine.install()\n'
    if needle not in src:
        raise RuntimeError('Runner bootstrap marker missing')
    return src.replace(needle,patch,1)


def main():
    preflight()
    original=pr.make_runner
    pr.make_runner=make_runner_v3
    try:
        rc=pr.main()
    finally:
        pr.make_runner=original
    if rc:
        print(f'V3 RUNNER: persistent_runner.main() reported failure (rc={rc}); skipping dashboard build')
        return rc
    out=Path(os.getenv('NSE_OUTPUT_DIR', str(Path(__file__).resolve().parents[1]/'output'))).resolve()
    hunter_csv=out/'early_hunter.csv'
    if not hunter_csv.is_file():
        # update_sheet.py's subprocess reported success (rc=0) but the file
        # it's supposed to always write is missing. Fail loudly here with a
        # clear reason instead of letting a downstream `test -f ...` check
        # fail with no context.
        raise RuntimeError(
            f'V3 RUNNER: update_sheet.py subprocess exited 0 but {hunter_csv} was never written. '
            'This means the subprocess exited before reaching its CSV-write step '
            '(e.g. Google Sheets auth/API error, or an early exit) without a nonzero '
            'return code being surfaced. Check the printed output above this line for '
            'the last thing update_sheet.py logged before it stopped.'
        )
    from v3_dashboard import main as build_dashboard
    build_dashboard()
    return 0


if __name__=='__main__':
    raise SystemExit(main())

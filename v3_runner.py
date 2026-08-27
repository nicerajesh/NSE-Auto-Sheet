from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    """Run V3 without monkey-patching or source-code rewriting.

    update_sheet.py owns persistent D1 history and produces the canonical
    scanner/backtest outputs. v3_dashboard.py then converts those outputs into
    the user-facing V3 decision/trading-command files.
    """
    runner = ROOT / 'persistent_runner.py'
    dashboard = ROOT / 'v3_dashboard.py'
    if not runner.exists():
        raise RuntimeError(f'Persistent runner missing: {runner}')
    if not dashboard.exists():
        raise RuntimeError(f'V3 dashboard missing: {dashboard}')
    env = os.environ.copy()
    env.setdefault('PERSISTENT_D1', '1')
    env.setdefault('PYTHONUNBUFFERED', '1')
    rc = subprocess.run([sys.executable, str(runner)], cwd=str(ROOT), env=env).returncode
    if rc:
        return rc
    return subprocess.run([sys.executable, str(dashboard)], cwd=str(ROOT), env=env).returncode


if __name__ == '__main__':
    raise SystemExit(main())

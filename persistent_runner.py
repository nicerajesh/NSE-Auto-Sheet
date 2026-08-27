from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    """Run the canonical pipeline directly.

    The old implementation dynamically rewrote update_sheet.py by searching for
    a fragile source-code text anchor. update_sheet.py is now the canonical
    persistent-D1 pipeline itself, so source rewriting is both unnecessary and
    unsafe. Keeping this runner as a thin process wrapper makes it resilient to
    refactors in update_sheet.py.
    """
    script = ROOT / 'update_sheet.py'
    if not script.exists():
        raise RuntimeError(f'Canonical pipeline missing: {script}')
    env = os.environ.copy()
    env.setdefault('PERSISTENT_D1', '1')
    env.setdefault('PYTHONUNBUFFERED', '1')
    print('PERSISTENT RUNNER: executing canonical update_sheet.py')
    return subprocess.run([sys.executable, str(script)], cwd=str(ROOT), env=env).returncode


if __name__ == '__main__':
    raise SystemExit(main())

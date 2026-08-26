from __future__ import annotations
# Compatibility wrapper for the persistent runner.
# It patches the dynamically generated legacy sheet script before execution,
# so persistent D1 mode cannot fail on stale local variable names.
import re
import persistent_runner as pr

_original_make_runner = pr.make_runner

def _safe_make_runner():
    src = _original_make_runner()
    # The legacy generated script has a final status line that references
    # variables from its old history-loader scope. In persistent mode those
    # names do not exist. Replace the whole status construction with a safe
    # status message; the authoritative data is already in the flat outputs.
    lines = src.splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith("status=f'NIFTY500 | Data"):
            indent = line[:len(line)-len(line.lstrip())]
            lines[i] = indent + "status='NIFTY500 | Persistent D1 | Flat output path'"
    src = '\n'.join(lines) + ('\n' if src.endswith('\n') else '')
    # Diagnostic only: the persistent runner has one DataFrame containing all
    # sessions, so len(frames)==1 is not the number of trading sessions.
    src = src.replace('sessions={len(frames)}', "sessions={int(pd.to_datetime(frames[0]['DATE']).nunique())}")
    return src

pr.make_runner = _safe_make_runner
raise SystemExit(pr.main())

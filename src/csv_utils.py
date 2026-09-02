"""Shared CSV write/read helpers.

pandas writes a fully empty (zero-row, zero-column) DataFrame as a single
blank line. pandas.read_csv() cannot parse that file at all -- it raises
`pandas.errors.EmptyDataError: No columns to parse from file`.

Several scanners in this project can legitimately find zero candidates on a
given trading day (scan_apex_matrix / scan_stealth_accumulation /
scan_low52_reversal all `return pd.DataFrame()` when nothing matches, and
build_master_buy_dashboard() does the same when no scanner published a buy).
Downstream code -- including the GitHub Actions workflow's own "Show ..."
steps -- was written to handle that as `if df.empty: print('NO ... TODAY')`,
but pd.read_csv() blows up before that check ever runs, crashing the whole
job with EmptyDataError.

safe_to_csv() / safe_read_csv() close that gap: a zero-column DataFrame is
written with one placeholder column so the file always has a header row.
`.empty` is still True for a 0-row DataFrame regardless of whether it has
this placeholder column, so no existing `if df.empty:` / `if not df.empty:`
logic anywhere else needs to change.
"""
from pathlib import Path
import pandas as pd

_PLACEHOLDER_COL = "_NO_RESULTS"


def safe_to_csv(df, path, index=False, **kwargs):
    """Write df to CSV, guaranteeing the file is never a truly empty
    (zero-column) file that pandas.read_csv() cannot parse."""
    if df is None:
        df = pd.DataFrame()
    if df.shape[1] == 0:
        df = pd.DataFrame({_PLACEHOLDER_COL: []})
    df.to_csv(path, index=index, **kwargs)
    return df


def safe_read_csv(path, **kwargs):
    """Read a CSV, tolerating a missing/zero-byte/columnless file by
    returning an empty DataFrame instead of raising EmptyDataError."""
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return pd.DataFrame()
    try:
        df = pd.read_csv(p, **kwargs)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()
    if list(df.columns) == [_PLACEHOLDER_COL]:
        return df.drop(columns=[_PLACEHOLDER_COL])
    return df

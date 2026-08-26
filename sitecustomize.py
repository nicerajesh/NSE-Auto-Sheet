"""Process-wide compatibility shim for the legacy gspread update calls.

The scanner still contains older Worksheet.update('A1', values, ...) calls.
New gspread versions expect update(values=..., range_name=...).  More importantly,
backtest summary dictionaries can otherwise reach the Sheets API as struct/list
values and produce HTTP 400 errors.  This shim normalizes both issues without
changing the trading logic.
"""
from __future__ import annotations

import json
from datetime import date, datetime


def _scalar(value):
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return json.dumps({str(k): _scalar(v) for k, v in value.items()}, sort_keys=True, default=str)
    if isinstance(value, (list, tuple, set)):
        # Sheets cells must be scalar; preserve nested diagnostics as JSON text.
        return json.dumps([_scalar(v) for v in value], default=str)
    try:
        import pandas as pd
        if pd.isna(value):
            return ""
        if hasattr(value, "item"):
            return _scalar(value.item())
    except Exception:
        pass
    return str(value)


def _normalize_rows(values):
    if values is None:
        return values
    if not isinstance(values, (list, tuple)):
        return _scalar(values)
    return [[_scalar(cell) for cell in row] if isinstance(row, (list, tuple)) else [_scalar(row)] for row in values]

try:
    from gspread.worksheet import Worksheet
    _original_update = Worksheet.update

    def _safe_update(self, *args, **kwargs):
        # Legacy: update(range_name, values, ...)
        if len(args) >= 2 and isinstance(args[0], str):
            range_name = args[0]
            values = _normalize_rows(args[1])
            extra = dict(kwargs)
            extra.pop("value_input_option", None)
            extra["range_name"] = range_name
            extra["values"] = values
            # gspread accepts value_input_option as a named argument.
            if "value_input_option" in kwargs:
                extra["value_input_option"] = kwargs["value_input_option"]
            return _original_update(self, **extra)

        if "values" in kwargs:
            kwargs["values"] = _normalize_rows(kwargs["values"])
        return _original_update(self, *args, **kwargs)

    Worksheet.update = _safe_update
except Exception:
    # Never prevent the scanner from starting if gspread is unavailable during
    # static tooling/import checks.
    pass

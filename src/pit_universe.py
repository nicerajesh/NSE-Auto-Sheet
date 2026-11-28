"""Point-in-time Nifty 500 membership utilities.

Membership is usable only from pit_available_date onward. This module deliberately
requires an explicit ISIN -> NSE symbol validity map before OHLCV can be joined;
it never guesses a ticker from a company name.
"""
from __future__ import annotations

from pathlib import Path
from typing import Union

import pandas as pd

PIT_URL = (
    "https://raw.githubusercontent.com/prathmeshgupta/"
    "nifty-pit-universe/main/output/pit_nifty_500.csv"
)
REQUIRED = {
    "as_of_date", "pit_available_date", "year_month", "index_name",
    "isin", "company_name",
}


def load_pit_membership(source: Union[str, Path] = PIT_URL) -> pd.DataFrame:
    """Load and validate monthly PIT membership from CSV path or URL."""
    frame = pd.read_csv(source, dtype={"isin": "string"})
    missing = REQUIRED - set(frame.columns)
    if missing:
        raise ValueError(f"PIT membership missing columns: {sorted(missing)}")
    frame = frame.copy()
    frame["as_of_date"] = pd.to_datetime(frame["as_of_date"], errors="coerce")
    frame["pit_available_date"] = pd.to_datetime(
        frame["pit_available_date"], errors="coerce"
    )
    if frame[["as_of_date", "pit_available_date", "isin"]].isna().any().any():
        raise ValueError("PIT membership contains invalid dates or blank ISINs")
    if (frame["pit_available_date"] < frame["as_of_date"]).any():
        raise ValueError("PIT availability cannot precede the membership snapshot")
    frame["index_name"] = frame["index_name"].astype(str).str.upper()
    frame["isin"] = frame["isin"].astype(str).str.strip().str.upper()
    frame = frame[frame["index_name"] == "NIFTY_500"]
    if frame.empty:
        raise ValueError("PIT file contains no NIFTY_500 rows")
    if frame.duplicated(["as_of_date", "isin"]).any():
        raise ValueError("Duplicate ISIN within a PIT Nifty 500 snapshot")
    return frame.sort_values(["pit_available_date", "isin"]).reset_index(drop=True)


def membership_available_on(
    membership: pd.DataFrame, trade_date: Union[str, pd.Timestamp]
) -> pd.DataFrame:
    """Return the latest disclosed membership known on trade_date (no look-ahead)."""
    date = pd.Timestamp(trade_date).normalize()
    known = membership[membership["pit_available_date"] <= date]
    if known.empty:
        return membership.iloc[0:0].copy()
    snapshot_date = known["pit_available_date"].max()
    snapshot = known[known["pit_available_date"] == snapshot_date].copy()
    if snapshot["isin"].duplicated().any():
        raise ValueError("Ambiguous PIT snapshot: duplicate ISINs")
    return snapshot


def attach_point_in_time_symbols(
    membership: pd.DataFrame,
    security_map: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Attach symbols using an explicit ISIN + effective-date map.

    security_map columns: isin, symbol, valid_from, valid_to (blank valid_to=open).
    Returns (mapped rows, unmapped rows). Mapping is evaluated at as_of_date.
    """
    required = {"isin", "symbol", "valid_from", "valid_to"}
    missing = required - set(security_map.columns)
    if missing:
        raise ValueError(f"Security map missing columns: {sorted(missing)}")
    m = membership.copy()
    s = security_map.copy()
    for col in ("valid_from", "valid_to"):
        s[col] = pd.to_datetime(s[col], errors="coerce")
    s["valid_from"] = s["valid_from"].fillna(pd.Timestamp("1900-01-01"))
    s["isin"] = s["isin"].astype(str).str.strip().str.upper()
    s["symbol"] = s["symbol"].astype(str).str.strip().str.upper()
    joined = m.merge(s, on="isin", how="left", suffixes=("", "_map"))
    valid = (
        joined["symbol"].notna()
        & joined["symbol"].ne("")
        & (joined["valid_from"] <= joined["as_of_date"])
        & (joined["valid_to"].isna() | (joined["as_of_date"] < joined["valid_to"]))
    )
    mapped = joined[valid].copy()
    unmapped = joined[~valid].copy()
    if mapped.duplicated(["as_of_date", "isin"]).any():
        raise ValueError("Security map resolves one ISIN to multiple symbols on a date")
    return mapped, unmapped


def mapping_coverage(mapped: pd.DataFrame, unmapped: pd.DataFrame) -> dict:
    total = len(mapped) + len(unmapped)
    return {
        "membership_rows": total,
        "mapped_rows": len(mapped),
        "unmapped_rows": len(unmapped),
        "coverage_pct": round(100 * len(mapped) / total, 2) if total else 0.0,
        "mapped_isins": int(mapped["isin"].nunique()) if total else 0,
        "unmapped_isins": int(unmapped["isin"].nunique()) if total else 0,
    }

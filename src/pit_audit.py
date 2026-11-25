"""Audit PIT Nifty 500 membership snapshots; never imply price-history coverage."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pit_universe import load_pit_membership  # noqa: E402

OUT = ROOT / "output" / "pit_audit"
OUT.mkdir(parents=True, exist_ok=True)
membership = load_pit_membership()
membership["month"] = membership["as_of_date"].dt.to_period("M").astype(str)
membership["availability_lag_days"] = (
    membership["pit_available_date"] - membership["as_of_date"]
).dt.days

snapshots = (
    membership.groupby(["as_of_date", "pit_available_date", "month"], as_index=False)
    .agg(rows=("isin", "size"), unique_isins=("isin", "nunique"),
         min_lag_days=("availability_lag_days", "min"),
         median_lag_days=("availability_lag_days", "median"),
         max_lag_days=("availability_lag_days", "max"))
    .sort_values("as_of_date")
)
snapshots["duplicate_isins"] = snapshots["rows"] - snapshots["unique_isins"]
snapshots.to_csv(OUT / "pit_monthly_snapshot_audit.csv", index=False)

months = sorted(membership["month"].unique())
expected = pd.period_range(months[0], months[-1], freq="M").astype(str)
missing_months = sorted(set(expected) - set(months))
mapping_path = ROOT / "data" / "pit_security_map.csv"
mapping_present = mapping_path.exists()
mapping_rows = None
mapping_coverage_pct = None
if mapping_present:
    security_map = pd.read_csv(mapping_path, dtype={"isin": "string"})
    required = {"isin", "symbol", "valid_from", "valid_to"}
    if not required.issubset(security_map.columns):
        raise ValueError(f"Security map missing columns: {sorted(required - set(security_map.columns))}")
    from pit_universe import attach_point_in_time_symbols, mapping_coverage
    mapped, unmapped = attach_point_in_time_symbols(membership, security_map)
    coverage = mapping_coverage(mapped, unmapped)
    mapping_rows = coverage["mapped_rows"]
    mapping_coverage_pct = coverage["coverage_pct"]
    unmapped.to_csv(OUT / "pit_unmapped_membership_rows.csv", index=False)

summary = {
    "source": "prathmeshgupta/nifty-pit-universe/output/pit_nifty_500.csv",
    "index": "NIFTY_500",
    "first_snapshot": str(membership["as_of_date"].min().date()),
    "last_snapshot": str(membership["as_of_date"].max().date()),
    "snapshot_count": int(len(snapshots)),
    "membership_rows": int(len(membership)),
    "unique_isins": int(membership["isin"].nunique()),
    "missing_calendar_months": missing_months,
    "duplicate_isins": int(snapshots["duplicate_isins"].sum()),
    "availability_lag_days": {
        "min": int(membership["availability_lag_days"].min()),
        "median": float(membership["availability_lag_days"].median()),
        "max": int(membership["availability_lag_days"].max()),
    },
    "security_map_present": mapping_present,
    "mapped_membership_rows": mapping_rows,
    "mapping_coverage_pct": mapping_coverage_pct,
    "price_history_coverage": "NOT MEASURED: no verified PIT ISIN OHLCV dataset supplied",
    "survivorship_bias_gate": "BLOCKED",
    "reason": "Membership snapshots alone do not establish historical security mapping or delisted/fallen-constituent OHLCV coverage.",
}
(OUT / "pit_audit_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps(summary, indent=2))

import pandas as pd
import pytest

from pit_universe import (
    load_pit_membership, membership_available_on,
    attach_point_in_time_symbols, mapping_coverage,
)


def sample_membership():
    return pd.DataFrame([
        {"as_of_date": pd.Timestamp("2024-01-31"), "pit_available_date": pd.Timestamp("2024-02-10"),
         "year_month": "2024-01", "index_name": "NIFTY_500", "isin": "INE000A01001", "company_name": "A"},
        {"as_of_date": pd.Timestamp("2024-01-31"), "pit_available_date": pd.Timestamp("2024-02-10"),
         "year_month": "2024-01", "index_name": "NIFTY_500", "isin": "INE000B01001", "company_name": "B"},
        {"as_of_date": pd.Timestamp("2024-02-29"), "pit_available_date": pd.Timestamp("2024-03-10"),
         "year_month": "2024-02", "index_name": "NIFTY_500", "isin": "INE000B01001", "company_name": "B"},
        {"as_of_date": pd.Timestamp("2024-02-29"), "pit_available_date": pd.Timestamp("2024-03-10"),
         "year_month": "2024-02", "index_name": "NIFTY_500", "isin": "INE000C01001", "company_name": "C"},
    ])


def test_membership_uses_only_disclosed_snapshot():
    m = sample_membership()
    assert membership_available_on(m, "2024-02-09").empty
    feb = membership_available_on(m, "2024-02-10")
    assert set(feb["isin"]) == {"INE000A01001", "INE000B01001"}
    mar = membership_available_on(m, "2024-03-10")
    assert set(mar["isin"]) == {"INE000B01001", "INE000C01001"}


def test_loader_rejects_future_availability_before_snapshot(tmp_path):
    p = tmp_path / "bad.csv"
    pd.DataFrame([{
        "as_of_date": "2024-01-31", "pit_available_date": "2024-01-30",
        "year_month": "2024-01", "index_name": "NIFTY_500",
        "isin": "INE000A01001", "company_name": "A",
    }]).to_csv(p, index=False)
    with pytest.raises(ValueError, match="cannot precede"):
        load_pit_membership(p)


def test_symbol_map_is_effective_date_aware_and_reports_gaps():
    m = sample_membership().iloc[:2].copy()
    sm = pd.DataFrame([
        {"isin": "INE000A01001", "symbol": "AAA", "valid_from": "2020-01-01", "valid_to": ""},
        {"isin": "INE000B01001", "symbol": "BBB", "valid_from": "2020-01-01", "valid_to": ""},
    ])
    mapped, missing = attach_point_in_time_symbols(m, sm)
    assert set(mapped.symbol) == {"AAA", "BBB"}
    assert missing.empty
    assert mapping_coverage(mapped, missing)["coverage_pct"] == 100.0


def test_symbol_map_rejects_ambiguous_mapping():
    m = sample_membership().iloc[:1].copy()
    sm = pd.DataFrame([
        {"isin": "INE000A01001", "symbol": "AAA", "valid_from": "2020-01-01", "valid_to": ""},
        {"isin": "INE000A01001", "symbol": "AAB", "valid_from": "2020-01-01", "valid_to": ""},
    ])
    with pytest.raises(ValueError, match="multiple symbols"):
        attach_point_in_time_symbols(m, sm)

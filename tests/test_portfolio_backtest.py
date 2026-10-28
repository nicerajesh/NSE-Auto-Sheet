import pandas as pd
import pytest

from portfolio_backtest import audit_universe_history, robustness_scenarios, run_concurrent_portfolio_backtest


def trades(rows):
    return pd.DataFrame(rows, columns=["SYMBOL", "SIGNAL_DATE", "ENTRY_DATE", "EXIT_DATE", "ENTRY", "INITIAL_STOP", "EXIT", "NET_RETURN_PCT", "SCORE"])


def test_concurrent_portfolio_limits_positions_and_sizes_risk():
    t = trades([
        ("AAA", "2024-01-01", "2024-01-02", "2024-01-05", 100, 95, 110, 5.0, 90),
        ("BBB", "2024-01-01", "2024-01-02", "2024-01-06", 100, 95, 90, -10.0, 80),
        ("CCC", "2024-01-01", "2024-01-02", "2024-01-07", 100, 95, 105, 3.0, 70),
    ])
    out, summary = run_concurrent_portfolio_backtest(
        t, initial_capital=100_000, risk_per_trade_pct=0.5, max_positions=2,
        max_open_risk_pct=1.0, max_single_position_pct=15, cost_pct=0.35,
    )
    assert len(out) == 2
    assert summary["skipped"] == 1
    assert (out["RISK_RS"] <= 500).all()
    assert summary["drawdown_basis"].startswith("CONCURRENT")


def test_cost_and_gap_stress_do_not_improve_returns():
    t = trades([("AAA", "2024-01-01", "2024-01-02", "2024-01-05", 100, 95, 110, 5.0, 90)])
    scenarios = robustness_scenarios(t, initial_capital=100_000, risk_per_trade_pct=0.5,
                                     max_positions=2, max_open_risk_pct=1.0, max_single_position_pct=15)
    base = scenarios.loc[scenarios.SCENARIO == "BASE_0.35_COST", "ending_equity"].iloc[0]
    high = scenarios.loc[scenarios.SCENARIO == "SLIPPAGE_STRESS_0.75_TOTAL_COST", "ending_equity"].iloc[0]
    gap = scenarios.loc[scenarios.SCENARIO == "COST_0.50_PLUS_1PCT_GAP_STRESS", "ending_equity"].iloc[0]
    broker = scenarios.loc[scenarios.SCENARIO == "BROKERAGE_STRESS_0.50_TOTAL_COST", "ending_equity"].iloc[0]\n    assert high <= broker <= base and gap <= broker


def test_universe_audit_explicitly_flags_survivorship_bias():
    h = pd.DataFrame({"SYMBOL": ["AAA", "AAA", "BBB"], "DATE": pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-02"])})
    report = audit_universe_history(h, ["AAA", "BBB", "CCC"])
    checks = report.set_index("CHECK")
    assert checks.loc["SURVIVORSHIP_BIAS", "STATUS"] == "PRESENT"
    assert checks.loc["POINT_IN_TIME_UNIVERSE", "STATUS"] == "NOT_VALIDATED"
    assert checks.loc["MISSING_REQUESTED_SYMBOLS", "STATUS"] == "WARN"

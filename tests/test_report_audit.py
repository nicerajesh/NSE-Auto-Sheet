import pandas as pd

import publish as pb
from test_pipeline import _ctx


def test_action_plan_surfaces_approval_status_and_portfolio_summary():
    ctx = _ctx()
    ctx["signal_review"] = pd.DataFrame([{
        "SYMBOL": "AAA", "TIER": "STRICT BUY", "APPROVAL_STATUS": "APPROVED",
        "CLOSE": 100.0, "STOP": 95.0, "QTY": 10, "RISK_AMT": 50.0,
        "APPROVAL_REASON": "Within slots/cash/open-risk limits",
    }, {
        "SYMBOL": "BBB", "TIER": "V38", "APPROVAL_STATUS": "SIGNAL ONLY - RISK LIMIT",
        "CLOSE": 50.0, "STOP": 45.0, "QTY": 0, "RISK_AMT": 0,
        "APPROVAL_REASON": "No slot, cash or risk budget left",
    }])
    ctx["portfolio_summary"] = {"trades": 25, "total_return_pct": 8.2, "max_drawdown_pct": -7.1, "profit_factor": 1.3}
    rows, marks = pb.build_action_rows(ctx)
    flat = [str(x) for row in rows for x in row]
    assert "SIGNAL APPROVAL - signal != approved trade" in flat
    assert "APPROVED" in flat and "SIGNAL ONLY - RISK LIMIT" in flat
    assert "SURVIVORSHIP BIAS PRESENT" in flat
    assert len({len(row) for row in rows}) == 1
    assert marks["title"] and marks["header"]


def test_status_tab_includes_portfolio_stress_and_universe_audit():
    ctx = _ctx()
    ctx["portfolio_summary"] = {"trades": 25, "skipped": 4, "ending_equity": 108200,
                                "total_return_pct": 8.2, "max_drawdown_pct": -7.1, "profit_factor": 1.3}
    ctx["cost_scenarios"] = pd.DataFrame([{"SCENARIO": "BASE_0.35_COST", "cost_pct": 0.35,
                                           "total_return_pct": 8.2, "max_drawdown_pct": -7.1, "profit_factor": 1.3}])
    ctx["universe_audit"] = pd.DataFrame([{"CHECK": "SURVIVORSHIP_BIAS", "STATUS": "PRESENT",
                                           "DETAIL": "Historical constituents not reconstructed"}])
    rows, _ = pb.build_status_rows(ctx)
    flat = [str(x) for row in rows for x in row]
    assert "CONCURRENT PORTFOLIO BACKTEST" in flat
    assert "BASE_0.35_COST" in flat
    assert "SURVIVORSHIP_BIAS" in flat
    assert len({len(row) for row in rows}) == 1

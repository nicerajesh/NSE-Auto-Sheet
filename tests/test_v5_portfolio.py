import pandas as pd
from v5_portfolio import run_portfolio_v5


def sample():
    dates = pd.bdate_range("2025-01-01", periods=5)
    return pd.DataFrame({
        "SYMBOL": ["AAA"] * 5,
        "DATE": dates,
        "OPEN": [100, 100, 100, 100, 100],
        "HIGH": [101, 131, 105, 105, 105],
        "LOW": [99, 99, 99, 99, 99],
        "CLOSE": [100, 125, 103, 104, 105],
        "TURNOVER_CR": [20] * 5,
        "ATR": [5] * 5,
        "V5_BUY": [True, False, False, False, False],
        "V5_STOP": [90] * 5,
        "V5_SCORE": [85] * 5,
        "V5_SETUP": ["TEST"] * 5,
    })


def test_portfolio_next_open_target_and_costs():
    trades, equity, yearly, opened, summary = run_portfolio_v5(
        sample(), initial_capital=100_000, risk_per_trade_pct=0.5,
        max_positions=2, max_position_pct=50, max_open_risk_pct=2,
        max_new_per_day=2, cost_pct=0.35, start="2025-01-01",
    )
    assert len(trades) == 1
    assert trades.iloc[0]["ENTRY"] == 100
    assert trades.iloc[0]["REASON"] == "TARGET_3R"
    assert trades.iloc[0]["NET_PNL"] > 0
    assert summary["closed_trades"] == 1
    assert summary["max_portfolio_drawdown_pct"] >= -100
    assert len(equity) == 5
    assert len(yearly) == 1
    assert opened.empty


def test_portfolio_stop_first_when_both_levels_touch():
    d = sample()
    d.loc[1, "HIGH"] = 140
    d.loc[1, "LOW"] = 80
    trades, _, _, _, _ = run_portfolio_v5(
        d, initial_capital=100_000, risk_per_trade_pct=0.5,
        max_positions=2, max_position_pct=50, max_open_risk_pct=2,
        max_new_per_day=2, cost_pct=0.0, start="2025-01-01",
    )
    assert len(trades) == 1
    assert trades.iloc[0]["REASON"] == "STOP"


def test_portfolio_respects_position_and_open_risk_caps():
    d = sample()
    d2 = sample()
    d2["SYMBOL"] = "BBB"
    d2["V5_SCORE"] = 84
    combined = pd.concat([d, d2], ignore_index=True)
    _, equity, _, _, summary = run_portfolio_v5(
        combined, initial_capital=100_000, risk_per_trade_pct=0.5,
        max_positions=1, max_position_pct=10, max_open_risk_pct=0.5,
        max_new_per_day=5, cost_pct=0.0, start="2025-01-01",
    )
    assert summary["max_concurrent_positions"] <= 1
    assert equity["OPEN_RISK"].max() <= 500.01

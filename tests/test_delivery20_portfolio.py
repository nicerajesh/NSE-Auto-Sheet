import pandas as pd
from delivery20_portfolio import run_delivery20_portfolio


def sample():
    dates = pd.bdate_range("2025-01-01", periods=5)
    rows = []
    for symbol in ("AAA", "BBB"):
        for i, date in enumerate(dates):
            rows.append({
                "SYMBOL": symbol, "DATE": date,
                "OPEN": 100, "HIGH": [101, 101, 125, 105, 105][i],
                "LOW": [99, 99, 99, 99, 99][i],
                "CLOSE": [100, 100, 120, 103, 104][i],
                "D20_BUY": i == 0, "D20_STOP": 90, "MOM_RANK": 95 if symbol == "AAA" else 90,
            })
    return pd.DataFrame(rows)


def test_portfolio_next_open_target_fees_and_equity():
    trades, equity, yearly, opened, summary = run_delivery20_portfolio(
        sample(), initial_capital=100_000, risk_per_trade_pct=1,
        max_positions=2, max_position_pct=50, max_open_risk_pct=5,
        max_new_per_day=2, cost_pct=0.35, target_pct=20,
    )
    assert len(trades) == 2
    assert set(trades.REASON) == {"TARGET_20"}
    assert trades.ENTRY_DATE.min() == pd.Timestamp("2025-01-02")
    assert summary["total_fees"] > 0
    assert summary["max_concurrent_positions"] <= 2
    assert not equity.empty and len(yearly) == 1
    assert opened.empty


def test_portfolio_stop_first_when_both_levels_touch():
    d = sample()
    d.loc[(d.SYMBOL == "AAA") & (d.DATE == pd.Timestamp("2025-01-02")), "HIGH"] = 125
    d.loc[(d.SYMBOL == "AAA") & (d.DATE == pd.Timestamp("2025-01-02")), "LOW"] = 85
    trades, _, _, _, _ = run_delivery20_portfolio(
        d, initial_capital=100_000, risk_per_trade_pct=1,
        max_positions=1, max_position_pct=50, max_open_risk_pct=5,
        max_new_per_day=1, cost_pct=0, target_pct=20,
    )
    assert len(trades) == 1
    assert trades.iloc[0].REASON == "STOP"


def test_portfolio_respects_position_cap_and_risk_budget():
    d = sample()
    trades, equity, _, _, summary = run_delivery20_portfolio(
        d, initial_capital=100_000, risk_per_trade_pct=0.5,
        max_positions=1, max_position_pct=10, max_open_risk_pct=0.5,
        max_new_per_day=5, cost_pct=0,
    )
    assert summary["max_concurrent_positions"] <= 1
    assert equity.OPEN_RISK.max() <= 500.01

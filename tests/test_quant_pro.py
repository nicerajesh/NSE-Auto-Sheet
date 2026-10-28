import numpy as np
import pandas as pd
import pytest

from quant_pro import (
    add_quant_pro_features,
    simulate_quant_pro_trade,
    summarize_quant_pro,
    summarize_quant_pro_by_year,
    summarize_quant_pro_periods,
)


def synthetic_features(n=260, symbols=("AAA", "BBB", "CCC")):
    rng = np.random.default_rng(7)
    dates = pd.bdate_range("2023-01-02", periods=n)
    rows = []
    for j, sym in enumerate(symbols):
        ret = rng.normal(0.001 + j * 0.0002, 0.008, n)
        close = 100 * np.exp(np.cumsum(ret))
        op = close * (1 + rng.normal(0, 0.002, n))
        high = np.maximum(op, close) * 1.01
        low = np.minimum(op, close) * 0.99
        for i in range(n):
            rows.append({
                "SYMBOL": sym, "DATE": dates[i], "OPEN": op[i], "HIGH": high[i], "LOW": low[i],
                "CLOSE": close[i], "VOLUME": 3_000_000.0, "ATR": close[i] * 0.025,
                "EMA20": close[i] * 0.99, "EMA50": close[i] * 0.97, "EMA200": close[i] * 0.90,
                "RSI": 55.0, "VOL_RATIO": 1.6, "RANK60": 85.0, "MOM_RANK": 92.0,
                "EMA50_UP": True, "LOW3": close[i] * 0.985, "CLOSE_LOC": 0.8, "BODY_PCT": 0.6,
                "TURNOVER_CR": close[i] * 3_000_000 / 1e7, "HH20": close[i] * 0.995,
                "TREND": True, "PULLBACK": False, "BREAKOUT": True, "SIGNAL": True,
            })
    return pd.DataFrame(rows)


def test_features_have_bounded_score_and_named_proxy():
    f = add_quant_pro_features(synthetic_features())
    assert f["QP_SCORE"].between(0, 100).all()
    assert set(f["QP_MARKET_REGIME"].dropna().unique()).issubset(
        {"BULLISH_PROXY", "NEUTRAL_PROXY", "DEFENSIVE_PROXY"}
    )
    assert {"QP_SIGNAL", "QP_STOP", "QP_T1", "QP_T2", "QP_T3"}.issubset(f.columns)


def test_simulator_checks_stop_conservatively():
    o = np.array([100.0, 100.0, 90.0])
    h = np.array([101.0, 102.0, 92.0])
    l = np.array([99.0, 95.0, 88.0])
    c = np.array([100.0, 101.0, 89.0])
    sim = simulate_quant_pro_trade(o, h, l, c, 1, 96.0, signal_close=100.0)
    assert sim["closed"] is True
    assert sim["exit_px"] == pytest.approx(96.0)
    assert sim["T1_HIT"] is False and sim["T2_HIT"] is False and sim["T3_HIT"] is False



def test_simulator_records_each_target_touch():
    sim = simulate_quant_pro_trade(
        np.array([100.0, 100.0, 121.0, 141.0, 161.0]),
        np.array([101.0, 125.0, 145.0, 165.0, 166.0]),
        np.array([99.0, 95.0, 110.0, 130.0, 150.0]),
        np.array([100.0, 120.0, 140.0, 160.0, 155.0]),
        1, 90.0, signal_close=100.0,
    )
    assert sim is not None
    assert sim["T1_HIT"] is True
    assert sim["T2_HIT"] is True
    assert sim["T3_HIT"] is True

def test_simulator_skips_gap_up():
    sim = simulate_quant_pro_trade(
        np.array([100.0, 103.0]), np.array([101.0, 104.0]),
        np.array([99.0, 102.0]), np.array([100.0, 103.0]), 1, 96.0, signal_close=100.0,
    )
    assert sim is None


def test_summary_uses_net_returns():
    trades = pd.DataFrame({"NET_RETURN_PCT": [5.0, -2.0, 1.0]})
    summary = summarize_quant_pro(trades)
    assert summary["trades"] == 3
    assert summary["drawdown_basis"] == "SEQUENTIAL_CLOSED_TRADE_EQUITY_NOT_PORTFOLIO"
    assert summary["win_pct"] == pytest.approx(66.67, abs=0.01)
    assert summary["profit_factor"] == pytest.approx(3.0)
    target_trades = pd.DataFrame({
        "NET_RETURN_PCT": [2.0, -1.0, 3.0],
        "T1_HIT": [True, False, True],
        "T2_HIT": [True, False, True],
        "T3_HIT": [False, False, True],
    })
    target_summary = summarize_quant_pro(target_trades)
    assert target_summary["t1_hit_pct"] == pytest.approx(66.67, abs=0.01)
    assert target_summary["t2_hit_pct"] == pytest.approx(66.67, abs=0.01)
    assert target_summary["t3_hit_pct"] == pytest.approx(33.33, abs=0.01)


def test_missing_features_fail_loudly():
    with pytest.raises(ValueError, match="missing required"):
        add_quant_pro_features(pd.DataFrame({"SYMBOL": ["A"], "DATE": [pd.Timestamp("2024-01-01")]}))


def test_yearly_and_period_summaries_are_reported():
    trades = pd.DataFrame({
        "EXIT_DATE": pd.to_datetime(["2023-12-01", "2024-02-01", "2025-03-01"]),
        "NET_RETURN_PCT": [4.0, -2.0, 3.0],
    })
    yearly = summarize_quant_pro_by_year(trades)
    periods = summarize_quant_pro_periods(trades, split_year=2024)
    assert yearly["YEAR"].tolist() == [2023, 2024, 2025]
    assert periods["PERIOD"].tolist() == ["EARLIER_THAN_2024", "2024_ONWARD_DIAGNOSTIC"]
    assert periods.iloc[1]["trades"] == 2


def test_market_proxy_features_do_not_use_future_rows():
    raw = synthetic_features(n=260)
    full = add_quant_pro_features(raw)
    cut_date = sorted(raw["DATE"].unique())[220]
    partial = add_quant_pro_features(raw[raw["DATE"] <= cut_date])
    a = full[full["DATE"] == cut_date].sort_values("SYMBOL").reset_index(drop=True)
    b = partial[partial["DATE"] == cut_date].sort_values("SYMBOL").reset_index(drop=True)
    for col in ["QP_PROXY_CLOSE", "QP_PROXY_EMA50", "QP_PROXY_EMA200", "QP_SCORE", "QP_SIGNAL", "QP_MARKET_REGIME"]:
        if col == "QP_SIGNAL":
            assert (a[col].fillna(False).values == b[col].fillna(False).values).all()
        elif col == "QP_MARKET_REGIME":
            assert (a[col].fillna("").values == b[col].fillna("").values).all()
        else:
            np.testing.assert_allclose(a[col].values, b[col].values, equal_nan=True, rtol=1e-9, err_msg=col)

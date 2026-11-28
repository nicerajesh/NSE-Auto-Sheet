import numpy as np
import pandas as pd

from volume_reversal_backtest import features_one, summarize, execution_metrics, summarize_execution, build_events


def test_mfi_is_100_when_positive_flow_has_no_negative_flow():
    n = 30
    close = np.arange(100.0, 100.0 + n)
    frame = pd.DataFrame({
        "DATE": pd.bdate_range("2025-01-01", periods=n),
        "OPEN": close - 0.2,
        "HIGH": close + 1.0,
        "LOW": close - 1.0,
        "CLOSE": close,
        "VOLUME": np.full(n, 10000),
    })
    result = features_one(frame)
    assert result["MFI14"].iloc[-1] == 100.0


def test_summary_can_segment_by_period_without_mixing_samples():
    events = pd.DataFrame({
        "TIER": ["A_DISCOVERY"] * 4,
        "PERIOD": ["TRAIN", "TRAIN", "HOLDOUT", "HOLDOUT"],
        "FWD20_RET_PCT": [10.0, -5.0, 20.0, -10.0],
        "FWD20_MAX_HIGH_PCT": [12.0, 2.0, 25.0, 3.0],
        "FWD20_MIN_LOW_PCT": [-2.0, -8.0, -1.0, -12.0],
        "FWD40_RET_PCT": [np.nan] * 4,
        "FWD40_MAX_HIGH_PCT": [np.nan] * 4,
        "FWD40_MIN_LOW_PCT": [np.nan] * 4,
        "FWD60_RET_PCT": [np.nan] * 4,
        "FWD60_MAX_HIGH_PCT": [np.nan] * 4,
        "FWD60_MIN_LOW_PCT": [np.nan] * 4,
    })
    result = summarize(events, "PERIOD")
    twenty = result[result["HORIZON"] == 20].set_index("PERIOD")
    assert set(twenty.index) == {"TRAIN", "HOLDOUT"}
    assert twenty.loc["TRAIN", "N"] == 2
    assert twenty.loc["HOLDOUT", "N"] == 2
    assert twenty.loc["TRAIN", "AVG_RETURN_PCT"] == 2.5
    assert twenty.loc["HOLDOUT", "AVG_RETURN_PCT"] == 5.0



def test_execution_uses_next_open_and_deducts_round_trip_costs():
    future = pd.DataFrame({
        "OPEN": [100.0] + [101.0] * 19,
        "HIGH": [103.0] * 20,
        "LOW": [99.0] * 20,
        "CLOSE": [102.0] * 19 + [110.0],
    })
    result = execution_metrics(future, 20, cost_pct=0.35)
    assert round(result["EXEC20_RET_NET_PCT"], 2) == 9.65
    assert round(result["EXEC20_MAX_HIGH_PCT"], 2) == 3.0
    assert round(result["EXEC20_MIN_LOW_PCT"], 2) == -1.0


def test_execution_does_not_report_incomplete_horizon():
    future = pd.DataFrame({
        "OPEN": [100.0], "HIGH": [101.0], "LOW": [99.0], "CLOSE": [100.5]
    })
    result = execution_metrics(future, 20)
    assert np.isnan(result["EXEC20_RET_NET_PCT"])


def test_execution_summary_keeps_holdout_separate():
    events = pd.DataFrame({
        "TIER": ["A_DISCOVERY"] * 4,
        "PERIOD": ["TRAIN", "TRAIN", "HOLDOUT", "HOLDOUT"],
        "EXEC20_RET_NET_PCT": [5.0, -2.0, 10.0, -4.0],
        "EXEC20_MAX_HIGH_PCT": [8.0, 2.0, 12.0, 3.0],
        "EXEC20_MIN_LOW_PCT": [-1.0, -5.0, -2.0, -7.0],
        "EXEC40_RET_NET_PCT": [np.nan] * 4,
        "EXEC40_MAX_HIGH_PCT": [np.nan] * 4,
        "EXEC40_MIN_LOW_PCT": [np.nan] * 4,
        "EXEC60_RET_NET_PCT": [np.nan] * 4,
        "EXEC60_MAX_HIGH_PCT": [np.nan] * 4,
        "EXEC60_MIN_LOW_PCT": [np.nan] * 4,
    })
    result = summarize_execution(events, "PERIOD")
    twenty = result[result["HORIZON"] == 20].set_index("PERIOD")
    assert twenty.loc["TRAIN", "AVG_NET_RETURN_PCT"] == 1.5
    assert twenty.loc["HOLDOUT", "AVG_NET_RETURN_PCT"] == 3.0



def test_new_strategy_features_are_calculated_without_future_data():
    n = 320
    close = np.linspace(100, 220, n)
    frame = pd.DataFrame({
        "DATE": pd.bdate_range("2024-01-01", periods=n),
        "OPEN": close * 0.995,
        "HIGH": close * 1.015,
        "LOW": close * 0.985,
        "CLOSE": close,
        "VOLUME": np.full(n, 100000),
        "SYMBOL": ["ABC"] * n,
    })
    result = features_one(frame)
    for column in ("EMA200", "RSI14", "ATR14", "ATR_PCT_MED60",
                   "RET63", "HIGH20_PREV", "HIGH55_PREV"):
        assert column in result.columns
        assert result[column].notna().any()
    # Prior-high reference must exclude the current candle.
    assert result.loc[100, "HIGH55_PREV"] < result.loc[100, "HIGH"]

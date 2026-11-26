import numpy as np
import pandas as pd

from volume_reversal_backtest import features_one, summarize


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

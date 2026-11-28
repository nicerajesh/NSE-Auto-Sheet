import numpy as np
import pandas as pd

import strategy_lab as lab
import swing_recovery as sr


def test_strategy_lab_emits_all_six_models_and_two_core_periods():
    dates = pd.bdate_range("2024-01-01", periods=330)
    close = 100 * np.exp(np.linspace(0, 0.30, len(dates)))
    history = pd.DataFrame({
        "SYMBOL": "AAA", "DATE": dates,
        "OPEN": close * 0.998, "HIGH": close * 1.012,
        "LOW": close * 0.988, "CLOSE": close,
        "VOLUME": np.full(len(dates), 2_000_000.0),
    })
    features = sr.add_swing_features(history)
    summary, trades = lab.run_strategy_lab(features)
    assert set(summary["STRATEGY"]) == {
        "TURTLE_55_BREAKOUT", "CANSLIM_PRICE_VOLUME_PROXY",
        "MINERVINI_VCP_INSPIRED", "RELATIVE_STRENGTH_MOMENTUM",
        "TREND_PULLBACK", "52W_LOW_RECOVERY",
    }
    assert set(summary["PERIOD"]) >= {"ALL", "RECENT_730D"}
    assert {"STRATEGY", "PERIOD", "TRADES", "PROFIT_FACTOR"} <= set(summary.columns)

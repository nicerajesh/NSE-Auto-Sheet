import numpy as np
import pandas as pd

import ry_quant_edge as rqe
import swing_recovery as sr


def test_ry_quant_edge_returns_three_entry_models_and_walk_forward_segments():
    dates = pd.bdate_range("2024-01-01", periods=340)
    close = 100 * np.exp(np.linspace(0, 0.45, len(dates)))
    history = pd.DataFrame({
        "SYMBOL": "AAA", "DATE": dates,
        "OPEN": close * 0.999, "HIGH": close * 1.012,
        "LOW": close * 0.988, "CLOSE": close,
        "VOLUME": np.full(len(dates), 2_000_000.0),
    })
    features = sr.add_swing_features(history)
    summary, trades = rqe.run_ry_quant_edge(features)
    assert set(summary["STRATEGY"]) == {
        "RY_VCP55_ATR2.5", "RY_VCP55_ATR3.0",
        "RY_EARLY20_ATR2.5", "RY_EARLY20_ATR3.0",
        "RY_PULLBACK10_ATR2.5", "RY_PULLBACK10_ATR3.0",
    }
    assert {"ALL", "TRAIN_THROUGH_2022", "VALIDATION_2023_2024",
            "OOS_2025_PLUS", "RECENT_730D"} <= set(summary["PERIOD"])
    assert {"STRATEGY", "TRADES", "PROFIT_FACTOR"} <= set(summary.columns)
    if not trades.empty:
        assert {"SIGNAL_DATE", "ENTRY_DATE", "EXIT_DATE", "EXIT_REASON", "RETURN_PCT"} <= set(trades.columns)

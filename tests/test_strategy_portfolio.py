import numpy as np
import pandas as pd

import swing_recovery as sr
from strategy_portfolio import build_strategy_buys


def test_strategy_portfolio_returns_one_per_strategy_and_audit():
    dates = pd.bdate_range("2024-01-01", periods=330)
    frames = []
    for j, symbol in enumerate(("AAA", "BBB", "CCC")):
        close = (100 + j * 20) * np.exp(np.linspace(0, 0.25, len(dates)))
        frames.append(pd.DataFrame({
            "SYMBOL": symbol, "DATE": dates,
            "OPEN": close * 0.999, "HIGH": close * 1.012,
            "LOW": close * 0.988, "CLOSE": close,
            "VOLUME": np.full(len(dates), 2_000_000.0),
        }))
    features = sr.add_swing_features(pd.concat(frames, ignore_index=True))
    buys, audit = build_strategy_buys(features)
    assert len(audit) == 12
    assert buys.empty  # no 2025+ OOS trades in this 2024-only fixture
    assert buys.columns.tolist()[:3] == ["STRATEGY", "STOCK", "SIGNAL_DATE"]

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from indicator import add_indicators


def _bars(n=70):
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    close = np.full(n, 100.0)
    high = np.full(n, 101.0)
    low = np.full(n, 99.0)
    open_ = np.full(n, 100.0)
    volume = np.full(n, 1000.0)
    delivery = np.full(n, 40.0)
    return pd.DataFrame({
        "DATE": dates,
        "OPEN_PRICE": open_,
        "HIGH_PRICE": high,
        "LOW_PRICE": low,
        "CLOSE_PRICE": close,
        "TTL_TRD_QNTY": volume,
        "DELIV_PER": delivery,
    })


def test_prior_resistance_uses_high_and_excludes_current_bar():
    df = _bars()
    # A close-based implementation would miss this 120 intraday high.
    df.loc[40, "HIGH_PRICE"] = 120.0
    df.loc[40, "CLOSE_PRICE"] = 100.0
    out = add_indicators(df)

    # On bar 41 the prior high must be 120.
    assert out.loc[41, "PRIOR_HIGH20"] == 120.0
    # On the same bar, changing today's high must not change today's level.
    original = out.loc[41, "PRIOR_HIGH20"]
    df2 = df.copy()
    df2.loc[41, "HIGH_PRICE"] = 200.0
    out2 = add_indicators(df2)
    assert out2.loc[41, "PRIOR_HIGH20"] == original


def test_prior_support_uses_low_and_excludes_current_bar():
    df = _bars()
    df.loc[40, "LOW_PRICE"] = 80.0
    df.loc[40, "CLOSE_PRICE"] = 100.0
    out = add_indicators(df)
    assert out.loc[41, "PRIOR_LOW20"] == 80.0


def test_52_week_levels_are_causal():
    df = _bars(270)
    df.loc[250, "HIGH_PRICE"] = 150.0
    df.loc[250, "LOW_PRICE"] = 70.0
    out = add_indicators(df)

    # The extreme becomes visible on the following bar, not on the bar itself.
    assert pd.isna(out.loc[250, "HIGH_52W"]) or out.loc[250, "HIGH_52W"] != 150.0
    assert out.loc[251, "HIGH_52W"] == 150.0
    assert out.loc[251, "LOW_52W"] == 70.0

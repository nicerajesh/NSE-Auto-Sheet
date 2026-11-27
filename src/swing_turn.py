"""Confirmed swing-turn signals. Signals are emitted only after right-bars confirmation."""
from __future__ import annotations

import numpy as np
import pandas as pd


def add_turn_signal_features(frame: pd.DataFrame, left: int = 4, right: int = 3) -> pd.DataFrame:
    """Add causal pivot-confirmation BUY/SELL signals to an existing feature frame.

    A pivot at t-right is only knowable on row t. The signal is recorded on t
    (confirmation date), never backdated to the pivot date.
    """
    parts = []
    width = left + right + 1
    for _, group in frame.groupby("SYMBOL", sort=False):
        d = group.sort_values("DATE").copy()
        lo, hi = d["LOW"], d["HIGH"]
        low_window_min = lo.rolling(width, min_periods=width).min()
        high_window_max = hi.rolling(width, min_periods=width).max()
        low_count = lo.rolling(width, min_periods=width).apply(
            lambda x: float(np.sum(x == np.min(x))), raw=True
        )
        high_count = hi.rolling(width, min_periods=width).apply(
            lambda x: float(np.sum(x == np.max(x))), raw=True
        )
        d["TURN_PIVOT_LOW"] = lo.shift(right).eq(low_window_min) & low_count.eq(1)
        d["TURN_PIVOT_HIGH"] = hi.shift(right).eq(high_window_max) & high_count.eq(1)
        d["TURN_PIVOT_LOW_PRICE"] = lo.shift(right).where(d["TURN_PIVOT_LOW"])
        d["TURN_PIVOT_HIGH_PRICE"] = hi.shift(right).where(d["TURN_PIVOT_HIGH"])
        rsi = d["RSI"]
        ema10 = d["CLOSE"].ewm(span=10, adjust=False, min_periods=10).mean()
        d["TURN_EMA10"] = ema10
        d["TURN_BUY"] = (
            d["TURN_PIVOT_LOW"] & (d["CLOSE"] > d["EMA20"]) &
            (d["CLOSE"] > d["CLOSE"].shift(1)) &
            (rsi >= 45) & (rsi > rsi.shift(3)) &
            (d["CLOSE"] > d["OPEN"])
        ).fillna(False)
        d["TURN_SELL"] = (
            d["TURN_PIVOT_HIGH"] & (d["CLOSE"] < ema10) &
            (rsi < 55) & (rsi < rsi.shift(3)) &
            (d["CLOSE"] < d["OPEN"])
        ).fillna(False)
        d["TURN_SIGNAL"] = np.select(
            [d["TURN_BUY"], d["TURN_SELL"]], ["BUY", "SELL"], default=""
        )
        pivot_date = d["DATE"].shift(right)
        d["TURN_PIVOT_DATE"] = pivot_date.where(d["TURN_BUY"] | d["TURN_SELL"])
        parts.append(d)
    return pd.concat(parts, ignore_index=True)


def latest_turn_signals(frame: pd.DataFrame) -> pd.DataFrame:
    """Latest-date confirmed turn signals with risk and target levels."""
    if frame.empty:
        return pd.DataFrame()
    d = frame[(frame["DATE"] == frame["DATE"].max()) & frame["TURN_SIGNAL"].ne("")].copy()
    if d.empty:
        return pd.DataFrame(columns=[
            "SYMBOL", "SIGNAL", "SIGNAL_DATE", "PIVOT_DATE", "PIVOT_PRICE",
            "CLOSE", "STOP_LOSS", "TARGET_1", "TARGET_2", "RSI", "CONFIRMATION"
        ])
    rows = []
    for _, r in d.iterrows():
        signal = r["TURN_SIGNAL"]
        close, atr = float(r["CLOSE"]), float(r["ATR"])
        pivot = float(r["TURN_PIVOT_LOW_PRICE"] if signal == "BUY" else r["TURN_PIVOT_HIGH_PRICE"])
        if signal == "BUY":
            stop = min(pivot, close - 1.8 * atr)
            risk = close - stop
            t1, t2 = close + 2 * risk, close + 3 * risk
        else:
            stop, t1, t2 = pivot, np.nan, np.nan
        rows.append({
            "SYMBOL": r["SYMBOL"], "SIGNAL": signal, "SIGNAL_DATE": r["DATE"],
            "PIVOT_DATE": r["TURN_PIVOT_DATE"], "PIVOT_PRICE": round(pivot, 2),
            "CLOSE": round(close, 2), "STOP_LOSS": round(stop, 2),
            "TARGET_1": round(t1, 2) if np.isfinite(t1) else np.nan,
            "TARGET_2": round(t2, 2) if np.isfinite(t2) else np.nan,
            "RSI": round(float(r["RSI"]), 1),
            "CONFIRMATION": "CONFIRMED AT CLOSE; next-session entry only",
        })
    return pd.DataFrame(rows).sort_values(["SIGNAL", "SYMBOL"]).reset_index(drop=True)

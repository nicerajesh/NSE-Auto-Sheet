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



def backtest_turn_signals(frame: pd.DataFrame, horizons=(5, 10, 20, 40), oos_start="2023-01-01"):
    """Event study for BUY signals: next-session OPEN entry, horizon CLOSE exit.

    Overlapping events are retained; this is not a portfolio simulation. MFE/MAE
    are observed daily-range excursions and do not imply target/stop execution.
    """
    events = []
    for _, group in frame.groupby("SYMBOL", sort=False):
        d = group.sort_values("DATE").reset_index(drop=True)
        signal_idx = np.flatnonzero(d["TURN_BUY"].fillna(False).to_numpy())
        for i in signal_idx:
            entry_idx = i + 1
            if entry_idx >= len(d):
                continue
            entry = float(d.loc[entry_idx, "OPEN"])
            if not np.isfinite(entry) or entry <= 0:
                continue
            for h in horizons:
                end_idx = entry_idx + int(h) - 1
                if end_idx >= len(d):
                    continue
                window = d.iloc[entry_idx:end_idx + 1]
                exit_close = float(d.loc[end_idx, "CLOSE"])
                events.append({
                    "SYMBOL": d.loc[i, "SYMBOL"],
                    "SIGNAL_DATE": d.loc[i, "DATE"],
                    "ENTRY_DATE": d.loc[entry_idx, "DATE"],
                    "ENTRY_OPEN": entry,
                    "HORIZON_SESSIONS": int(h),
                    "EXIT_DATE": d.loc[end_idx, "DATE"],
                    "EXIT_CLOSE": exit_close,
                    "RETURN_PCT": (exit_close / entry - 1) * 100,
                    "MFE_PCT": (float(window["HIGH"].max()) / entry - 1) * 100,
                    "MAE_PCT": (float(window["LOW"].min()) / entry - 1) * 100,
                    "OOS": d.loc[entry_idx, "DATE"] >= pd.Timestamp(oos_start),
                })
    events_df = pd.DataFrame(events)
    columns = ["HORIZON_SESSIONS", "TRADES", "WIN_PCT", "AVG_RETURN_PCT", "MEDIAN_RETURN_PCT",
               "HIT_10PCT", "HIT_20PCT", "AVG_MFE_PCT", "AVG_MAE_PCT",
               "OOS_TRADES", "OOS_WIN_PCT", "OOS_AVG_RETURN_PCT", "OOS_MEDIAN_RETURN_PCT",
               "OOS_HIT_10PCT", "OOS_HIT_20PCT"]
    if events_df.empty:
        return events_df, pd.DataFrame(columns=columns)

    def summarize(g):
        r = g["RETURN_PCT"]
        return {
            "TRADES": len(g), "WIN_PCT": round((r > 0).mean() * 100, 2),
            "AVG_RETURN_PCT": round(r.mean(), 2), "MEDIAN_RETURN_PCT": round(r.median(), 2),
            "HIT_10PCT": round((r >= 10).mean() * 100, 2),
            "HIT_20PCT": round((r >= 20).mean() * 100, 2),
            "AVG_MFE_PCT": round(g["MFE_PCT"].mean(), 2), "AVG_MAE_PCT": round(g["MAE_PCT"].mean(), 2),
        }

    rows = []
    for h, g in events_df.groupby("HORIZON_SESSIONS"):
        all_stats = summarize(g)
        oos = g[g["OOS"]]
        os_stats = summarize(oos) if not oos.empty else {}
        rows.append({
            "HORIZON_SESSIONS": int(h), **all_stats,
            "OOS_TRADES": len(oos), "OOS_WIN_PCT": os_stats.get("WIN_PCT", np.nan),
            "OOS_AVG_RETURN_PCT": os_stats.get("AVG_RETURN_PCT", np.nan),
            "OOS_MEDIAN_RETURN_PCT": os_stats.get("MEDIAN_RETURN_PCT", np.nan),
            "OOS_HIT_10PCT": os_stats.get("HIT_10PCT", np.nan),
            "OOS_HIT_20PCT": os_stats.get("HIT_20PCT", np.nan),
        })
    return events_df, pd.DataFrame(rows, columns=columns).sort_values("HORIZON_SESSIONS").reset_index(drop=True)

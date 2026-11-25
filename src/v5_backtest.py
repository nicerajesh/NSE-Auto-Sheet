"""Independent V5 research backtest. Never changes the production V2/V4 signal engine.

Execution assumptions: signal after close, enter next session open, reject gaps >2%,
initial stop from signal close (2 ATR), conservative stop-first intraday ordering,
single full exit at 3R target or stop, max 60 sessions, 0.35% round-trip costs.
Open trades are reported separately and excluded from closed-trade performance.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def simulate_v5_trade(d: pd.DataFrame, signal_idx: int, stop: float,
                      target_r: float = 3.0, max_hold: int = 60,
                      cost_pct: float = 0.35, max_gap_pct: float = 2.0):
    """Return one closed trade dict or None. d must be one symbol, sorted by DATE."""
    entry_idx = signal_idx + 1
    if entry_idx >= len(d):
        return None
    fill = float(d.iloc[entry_idx]["OPEN"])
    signal_close = float(d.iloc[signal_idx]["CLOSE"])
    if not np.isfinite(fill) or fill <= stop or signal_close <= 0:
        return None
    if (fill / signal_close - 1) * 100 > max_gap_pct:
        return None
    risk = fill - stop
    target = fill + target_r * risk
    end = min(len(d), entry_idx + max_hold)
    for j in range(entry_idx, end):
        row = d.iloc[j]
        # Conservative: if both stop and target trade inside one daily candle, assume stop first.
        if float(row["LOW"]) <= stop:
            exit_px, reason = min(float(row["OPEN"]), stop), "STOP"
            return _trade_result(d, signal_idx, entry_idx, j, fill, exit_px, risk, reason, cost_pct)
        if float(row["HIGH"]) >= target:
            exit_px, reason = max(float(row["OPEN"]), target), "TARGET_3R"
            return _trade_result(d, signal_idx, entry_idx, j, fill, exit_px, risk, reason, cost_pct)
    if entry_idx + max_hold <= len(d):
        j = end - 1
        return _trade_result(d, signal_idx, entry_idx, j, fill, float(d.iloc[j]["CLOSE"]),
                             risk, "TIME_EXIT", cost_pct)
    return None


def _trade_result(d, si, ei, xi, fill, exit_px, risk, reason, cost_pct):
    gross = (exit_px / fill - 1) * 100
    net = gross - cost_pct
    return {
        "SIGNAL_DATE": pd.Timestamp(d.iloc[si]["DATE"]),
        "ENTRY_DATE": pd.Timestamp(d.iloc[ei]["DATE"]),
        "EXIT_DATE": pd.Timestamp(d.iloc[xi]["DATE"]),
        "ENTRY": fill, "EXIT": exit_px, "STOP": fill - risk,
        "R": net / (risk / fill * 100), "RET_PCT": net,
        "HOLD": xi - ei + 1, "REASON": reason,
    }


def run_v5_backtest(features: pd.DataFrame, start="2019-01-01", target_r=3.0,
                    max_hold=60, cost_pct=0.35, max_gap_pct=2.0,
                    min_turnover_cr=5.0, cooldown=10) -> pd.DataFrame:
    """Per-symbol non-overlapping event backtest; current-universe survivorship bias remains."""
    rows = []
    start = pd.Timestamp(start)
    for symbol, raw in features.groupby("SYMBOL", sort=False):
        d = raw.sort_values("DATE").reset_index(drop=True)
        dates = pd.to_datetime(d["DATE"])
        signal = (d["V5_BUY"].fillna(False).astype(bool)
                  & (d["TURNOVER_CR"] >= min_turnover_cr)
                  & d["ATR"].notna() & (dates >= start))
        last_exit = -1
        for i in np.flatnonzero(signal.to_numpy()):
            if i <= last_exit or i + 1 >= len(d):
                continue
            close, atr = float(d.iloc[i]["CLOSE"]), float(d.iloc[i]["ATR"])
            stop = close - 2.0 * atr
            if not np.isfinite(stop) or stop <= 0 or stop >= close:
                continue
            trade = simulate_v5_trade(d, int(i), stop, target_r, max_hold, cost_pct, max_gap_pct)
            if trade is None:
                continue
            trade["SYMBOL"] = symbol
            trade["SETUP"] = d.iloc[i].get("V5_SETUP", "V5")
            trade["V5_SCORE"] = float(d.iloc[i]["V5_SCORE"])
            rows.append(trade)
            last_exit = int(i) + cooldown
    cols = ["SYMBOL", "SIGNAL_DATE", "ENTRY_DATE", "EXIT_DATE", "ENTRY", "EXIT",
            "STOP", "RET_PCT", "R", "HOLD", "REASON", "SETUP", "V5_SCORE"]
    out = pd.DataFrame(rows, columns=cols)
    if not out.empty:
        out = out.sort_values(["ENTRY_DATE", "SYMBOL"]).reset_index(drop=True)
    return out


def summarize_v5(trades: pd.DataFrame) -> dict:
    if trades is None or trades.empty:
        return {"trades": 0, "win_pct": np.nan, "pf": np.nan, "avg_r": np.nan,
                "avg_ret_pct": np.nan, "max_drawdown_pct": np.nan}
    t = trades.sort_values(["EXIT_DATE", "SYMBOL"]).copy()
    wins = t.loc[t.RET_PCT > 0, "RET_PCT"].sum()
    losses = -t.loc[t.RET_PCT < 0, "RET_PCT"].sum()
    # Trade-sequence equity curve is illustrative (not portfolio-weighted due to overlapping symbols).
    equity = (1 + t.RET_PCT / 100).cumprod()
    peak = equity.cummax()
    dd = (equity / peak - 1) * 100
    return {
        "trades": int(len(t)),
        "win_pct": round(float((t.RET_PCT > 0).mean() * 100), 2),
        "pf": round(float(wins / losses), 3) if losses > 0 else float("inf"),
        "avg_r": round(float(t.R.mean()), 3),
        "avg_ret_pct": round(float(t.RET_PCT.mean()), 3),
        "max_drawdown_pct": round(float(dd.min()), 2),
    }


def yearly_v5(trades: pd.DataFrame) -> pd.DataFrame:
    if trades is None or trades.empty:
        return pd.DataFrame(columns=["YEAR", "trades", "win_pct", "pf", "avg_r", "avg_ret_pct", "max_drawdown_pct"])
    rows = []
    for year, group in trades.groupby(pd.to_datetime(trades.EXIT_DATE).dt.year):
        rows.append({"YEAR": int(year), **summarize_v5(group)})
    return pd.DataFrame(rows).sort_values("YEAR").reset_index(drop=True)

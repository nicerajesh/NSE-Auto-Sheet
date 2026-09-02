"""Live-vs-backtest divergence tracking.

The quality gate (quality_gate.py) only ever checks the BACKTEST's numbers.
It has no idea whether the strategy is actually still working right now.
A backtest can look great for months while the live edge has already quietly
decayed (regime shift, crowding, data changes) -- this module is the early
warning for that: it compares each CLOSED ledger trade's REALISED return
against the backtest's expected return for that action, and flags when live
performance has drifted meaningfully worse than what the backtest promised.

This does not block anything by itself (that's what the drawdown kill-switch
in risk_manager.py does, on live results only). It produces
output/edge_monitor.csv as a standing diagnostic so a human reviewing the run
can see edge decay before it becomes a real drawdown.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

CLOSED_STATUSES = {"EXIT", "T3 HIT / EXIT"}


def _num(v, default=np.nan):
    try:
        x = float(v)
        return x if np.isfinite(x) else default
    except Exception:
        return default


def compute_divergence(ledger: pd.DataFrame, backtest_stats: dict) -> pd.DataFrame:
    """ledger: trade_ledger.csv contents (needs ACTION, ENTRY, EXIT_PRICE,
    STATUS -- ACTION may be absent on older ledger rows, handled below).
    backtest_stats: the dict loaded from backtest_summary.csv, whose
    'action_stats' field (via quality_gate.parse_action_stats) holds
    per-ACTION expected win_rate_pct / avg_return_pct / profit_factor."""
    from quality_gate import parse_action_stats

    if ledger is None or ledger.empty:
        return pd.DataFrame(columns=["ACTION", "LIVE_TRADES", "LIVE_WIN_RATE_PCT", "LIVE_AVG_RETURN_PCT",
                                      "BACKTEST_WIN_RATE_PCT", "BACKTEST_AVG_RETURN_PCT",
                                      "WIN_RATE_DELTA", "AVG_RETURN_DELTA", "EDGE_STATUS"])

    closed = ledger[ledger["STATUS"].astype(str).isin(CLOSED_STATUSES)].copy()
    if closed.empty or "ACTION" not in closed.columns:
        return pd.DataFrame(columns=["ACTION", "LIVE_TRADES", "LIVE_WIN_RATE_PCT", "LIVE_AVG_RETURN_PCT",
                                      "BACKTEST_WIN_RATE_PCT", "BACKTEST_AVG_RETURN_PCT",
                                      "WIN_RATE_DELTA", "AVG_RETURN_DELTA", "EDGE_STATUS"])

    def _ret(r):
        entry, exitp = _num(r.get("ENTRY")), _num(r.get("EXIT_PRICE"))
        if not (np.isfinite(entry) and np.isfinite(exitp)) or entry <= 0:
            return np.nan
        return (exitp - entry) / entry * 100

    closed["RETURN_PCT"] = closed.apply(_ret, axis=1)
    closed = closed.dropna(subset=["RETURN_PCT"])
    if closed.empty:
        return pd.DataFrame(columns=["ACTION", "LIVE_TRADES", "LIVE_WIN_RATE_PCT", "LIVE_AVG_RETURN_PCT",
                                      "BACKTEST_WIN_RATE_PCT", "BACKTEST_AVG_RETURN_PCT",
                                      "WIN_RATE_DELTA", "AVG_RETURN_DELTA", "EDGE_STATUS"])

    bt_by_action = {a.get("ACTION"): a for a in parse_action_stats(backtest_stats)}
    rows = []
    for action, g in closed.groupby("ACTION"):
        live_trades = len(g)
        live_win_rate = round((g.RETURN_PCT > 0).mean() * 100, 2)
        live_avg_return = round(g.RETURN_PCT.mean(), 2)
        bt = bt_by_action.get(action, {})
        bt_win_rate = float(bt.get("win_rate_pct", np.nan)) if bt else np.nan
        bt_avg_return = float(bt.get("avg_return_pct", np.nan)) if bt else np.nan
        win_delta = round(live_win_rate - bt_win_rate, 2) if np.isfinite(bt_win_rate) else np.nan
        ret_delta = round(live_avg_return - bt_avg_return, 2) if np.isfinite(bt_avg_return) else np.nan
        # Only call it out once there's enough live sample to mean something.
        if live_trades < 8 or not np.isfinite(win_delta):
            status = "INSUFFICIENT_LIVE_SAMPLE"
        elif win_delta <= -15 or (np.isfinite(ret_delta) and ret_delta <= -3):
            status = "EDGE_DECAY_WARNING"
        else:
            status = "IN_LINE_WITH_BACKTEST"
        rows.append({
            "ACTION": action, "LIVE_TRADES": live_trades, "LIVE_WIN_RATE_PCT": live_win_rate,
            "LIVE_AVG_RETURN_PCT": live_avg_return, "BACKTEST_WIN_RATE_PCT": bt_win_rate,
            "BACKTEST_AVG_RETURN_PCT": bt_avg_return, "WIN_RATE_DELTA": win_delta,
            "AVG_RETURN_DELTA": ret_delta, "EDGE_STATUS": status,
        })
    return pd.DataFrame(rows)

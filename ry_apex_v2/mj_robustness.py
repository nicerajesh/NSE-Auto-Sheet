"""M/J stop and transaction-cost robustness matrix.

The original no-stop M/J portfolio remains the control. These are explicitly
modified exit overlays, not the original strategy. Entry rules, next-open fills,
40-session time exit, cooldown and 8-slot/15%-initial-capital sizing are kept.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .mj_portfolio import build_mj_signals

CAPITAL = 500_000
MAX_POSITIONS = 8
MAX_TICKET_PCT = 15.0
HOLD_SESSIONS = 40
COSTS = (0.35, 0.60, 1.00)
STOP_MODES = ("none", "fixed_8", "fixed_12", "trailing_8", "trailing_10")


def _simulate(history: pd.DataFrame, signals: pd.DataFrame, strategy: str,
              cost_pct: float, stop_mode: str) -> dict:
    d = history.copy()
    d["DATE"] = pd.to_datetime(d.DATE)
    d = d.sort_values(["DATE", "SYMBOL"])
    by_day = {day: g.set_index("SYMBOL", drop=False)
              for day, g in d.groupby("DATE", sort=True)}
    dates = sorted(by_day)
    s = signals[signals.STRATEGY.eq(strategy)].copy()
    s["SIGNAL_DATE"] = pd.to_datetime(s.SIGNAL_DATE)
    by_signal = {day: g.copy() for day, g in s.groupby("SIGNAL_DATE")}
    cash = float(CAPITAL)
    positions: dict[str, dict] = {}
    pending = pd.DataFrame()
    trades, curve = [], []
    max_ticket = CAPITAL * MAX_TICKET_PCT / 100.0

    for day in dates:
        today = by_day[day]
        if not pending.empty:
            sort_cols = (["MOM_RANK", "VOL_X", "SYMBOL"] if strategy == "M"
                         else ["CLOSE_LOC", "VOL_X", "SYMBOL"])
            ascending = ([False, False, True])
            pending = pending.sort_values(sort_cols, ascending=ascending)
            for _, sig in pending.iterrows():
                sym = sig.SYMBOL
                if len(positions) >= MAX_POSITIONS or sym in positions or sym not in today.index:
                    continue
                row = today.loc[sym]
                entry = float(row.OPEN)
                if not np.isfinite(entry) or entry <= 0:
                    continue
                qty = int(min(max_ticket, cash) // entry)
                if qty < 1:
                    continue
                cash -= qty * entry
                positions[sym] = {
                    "qty": qty, "entry": entry, "entry_date": day,
                    "signal_date": sig.SIGNAL_DATE, "bars": 0,
                    # A trailing stop starts below entry; today's high is only
                    # allowed to raise tomorrow's stop after today's stop check.
                    "high_water": entry,
                    "stop": entry * (1 - (0.08 if stop_mode.endswith("8") else 0.12))
                            if stop_mode.startswith("fixed") else (
                                entry * (1 - (0.08 if stop_mode == "trailing_8" else 0.10))
                                if stop_mode.startswith("trailing") else None
                            ),
                }

        for sym in list(positions):
            if sym not in today.index:
                continue
            p = positions[sym]
            row = today.loc[sym]
            p["bars"] += 1
            high, low, opn, close = map(float, (row.HIGH, row.LOW, row.OPEN, row.CLOSE))
            # Evaluate the stop carried into this session before incorporating
            # today's high; OHLC alone cannot reveal whether high preceded low.
            stop = p["stop"]
            exit_px, reason = None, None
            if stop is not None and low <= stop:
                exit_px = min(opn, stop) if opn < stop else stop
                reason = "STOP"
            elif p["bars"] >= HOLD_SESSIONS:
                exit_px, reason = close, "TIME"
            if exit_px is None and stop_mode.startswith("trailing"):
                trail = 0.08 if stop_mode == "trailing_8" else 0.10
                p["high_water"] = max(p["high_water"], high)
                p["stop"] = max(stop, p["high_water"] * (1 - trail))
            if exit_px is not None:
                qty = p["qty"]
                gross = (exit_px - p["entry"]) * qty
                fee = p["entry"] * qty * cost_pct / 100.0
                cash += qty * exit_px - fee
                trades.append({
                    "strategy": strategy, "symbol": sym,
                    "signal_date": p["signal_date"], "entry_date": p["entry_date"],
                    "exit_date": day, "entry": p["entry"], "exit": exit_px,
                    "qty": qty, "gross_pnl": gross, "cost_rs": fee,
                    "net_pnl": gross - fee, "exit_reason": reason,
                    "net_return_pct": (exit_px / p["entry"] - 1) * 100 - cost_pct,
                })
                del positions[sym]

        equity = cash + sum(p["qty"] * float(today.loc[sym].CLOSE)
                            for sym, p in positions.items() if sym in today.index)
        curve.append({"date": day, "equity": equity})
        pending = by_signal.get(day, pd.DataFrame()).copy()

    t, e = pd.DataFrame(trades), pd.DataFrame(curve)
    if e.empty:
        return {"strategy": strategy, "stop_mode": stop_mode, "cost_pct": cost_pct,
                "ending_equity": CAPITAL, "return_pct": 0, "cagr_pct": 0,
                "max_drawdown_pct": 0, "trades": 0, "win_rate_pct": 0,
                "profit_factor": 0, "holdout_return_2025_plus_pct": 0}
    e["peak"] = e.equity.cummax()
    e["dd"] = (e.equity / e.peak - 1) * 100
    final = float(e.equity.iloc[-1])
    elapsed = max(1, (pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days)
    wins = float(t.loc[t.net_pnl > 0, "net_pnl"].sum()) if not t.empty else 0
    losses = float(-t.loc[t.net_pnl < 0, "net_pnl"].sum()) if not t.empty else 0
    pre = e[pd.to_datetime(e.date) < "2025-01-01"]
    post = e[pd.to_datetime(e.date) >= "2025-01-01"]
    base = float(pre.equity.iloc[-1]) if not pre.empty else CAPITAL
    return {
        "strategy": strategy, "stop_mode": stop_mode, "cost_pct": cost_pct,
        "starting_capital": CAPITAL, "ending_equity": round(final, 2),
        "net_pnl": round(final-CAPITAL, 2),
        "return_pct": round((final/CAPITAL-1)*100, 2),
        "cagr_pct": round(((final/CAPITAL)**(365.25/elapsed)-1)*100, 2) if final > 0 else -100,
        "max_drawdown_pct": round(float(e.dd.min()), 2),
        "trades": len(t),
        "win_rate_pct": round(float((t.net_pnl > 0).mean()*100), 2) if not t.empty else 0,
        "profit_factor": round(wins/losses, 3) if losses else (float("inf") if wins else 0),
        "avg_trade_pct": round(float(t.net_return_pct.mean()), 3) if not t.empty else 0,
        "stop_exits": int((t.exit_reason == "STOP").sum()) if not t.empty else 0,
        "time_exits": int((t.exit_reason == "TIME").sum()) if not t.empty else 0,
        "holdout_return_2025_plus_pct": round((float(post.equity.iloc[-1])/base-1)*100, 2)
                                        if not post.empty and base else 0,
        "holdout_signal_trades": int((pd.to_datetime(t.signal_date) >= "2025-01-01").sum())
                                  if not t.empty else 0,
    }


def run_robustness_matrix(history: pd.DataFrame, out_dir) -> dict:
    from pathlib import Path
    out = Path(out_dir)
    signals = build_mj_signals(history)
    rows = []
    for strategy in ("M", "J"):
        for stop_mode in STOP_MODES:
            for cost_pct in COSTS:
                rows.append(_simulate(history, signals, strategy, cost_pct, stop_mode))
    result = pd.DataFrame(rows)
    result.to_csv(out / "mj_robustness_matrix.csv", index=False)
    result = result.sort_values(["strategy", "cost_pct", "cagr_pct"], ascending=[True, True, False])
    return {
        "capital": CAPITAL,
        "cost_scenarios_pct": list(COSTS),
        "stop_modes": list(STOP_MODES),
        "results": result.to_dict(orient="records"),
        "method": (
            "Same M/J entry signals, next-open entry, shared cash, max 8 positions, "
            "15% initial-capital ticket, 40-session time exit, integer shares. "
            "Fixed stops are 8%/12% below entry; trailing stops trail the highest "
            "intraday high by 8%/10%; stop gap fills use the open. Costs are charged "
            "as a round-trip percentage of entry notional. Open positions are marked "
            "to market, not forcibly liquidated. This is a modified-exit robustness "
            "test, not the original no-stop M/J strategy."
        ),
    }

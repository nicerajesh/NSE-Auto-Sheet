"""Concurrent-position portfolio backtest and robustness diagnostics.

Uses next-session entries and trade-level net returns from Quant Pro. This is a
daily-bar research simulation, not broker execution or a point-in-time universe.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

BASE_COST_PCT = 0.35


def _metrics(equity: pd.Series, pnl: pd.Series, trades: pd.DataFrame) -> dict:
    if equity.empty:
        return {"trades": 0, "ending_equity": np.nan, "total_return_pct": np.nan,
                "max_drawdown_pct": np.nan, "profit_factor": np.nan, "win_pct": np.nan,
                "avg_exposure_pct": np.nan}
    peak = equity.cummax()
    dd = (equity / peak - 1.0) * 100
    wins = pnl[pnl > 0].sum()
    losses = -pnl[pnl < 0].sum()
    return {
        "trades": int(len(trades)),
        "ending_equity": round(float(equity.iloc[-1]), 2),
        "total_return_pct": round(float((equity.iloc[-1] / equity.iloc[0] - 1) * 100), 3),
        "max_drawdown_pct": round(float(dd.min()), 3),
        "profit_factor": round(float(wins / losses), 3) if losses > 0 else (float("inf") if wins > 0 else np.nan),
        "win_pct": round(float((pnl > 0).mean() * 100), 2),
        "avg_exposure_pct": round(float(trades.get("CAPITAL_PCT", pd.Series(dtype=float)).mean()), 2),
    }


def run_concurrent_portfolio_backtest(
    trades: pd.DataFrame,
    initial_capital: float = 1_000_000.0,
    risk_per_trade_pct: float = 0.5,
    max_positions: int = 12,
    max_open_risk_pct: float = 6.0,
    max_single_position_pct: float = 15.0,
    cost_pct: float = BASE_COST_PCT,
    gap_down_stress_pct: float = 0.0,
) -> tuple[pd.DataFrame, dict]:
    """Simulate overlapping trades with risk sizing, cash, slots, costs and gap stress.

    Trade returns are price-path returns from the OHLC simulator. The baseline NET_RETURN_PCT
    already subtracts BASE_COST_PCT, so only incremental cost is deducted here. Gap stress
    adds an adverse percentage loss on each stopped trade; it is a sensitivity, not a forecast.
    """
    cols = ["SYMBOL", "SIGNAL_DATE", "ENTRY_DATE", "EXIT_DATE", "ENTRY", "INITIAL_STOP",
            "EXIT", "NET_RETURN_PCT"]
    if trades is None or trades.empty:
        return pd.DataFrame(), {"trades": 0, "skipped": 0, "initial_capital": initial_capital,
                                "ending_equity": initial_capital, "max_drawdown_pct": 0.0,
                                "total_return_pct": 0.0, "profit_factor": np.nan, "win_pct": np.nan,
                                "avg_exposure_pct": 0.0}
    missing = set(cols) - set(trades.columns)
    if missing:
        raise ValueError(f"portfolio backtest missing columns: {sorted(missing)}")
    t = trades.copy()
    for c in ("SIGNAL_DATE", "ENTRY_DATE", "EXIT_DATE"):
        t[c] = pd.to_datetime(t[c], errors="coerce")
    t = t.dropna(subset=["ENTRY_DATE", "EXIT_DATE", "ENTRY", "INITIAL_STOP", "NET_RETURN_PCT"])
    t = t.sort_values(["ENTRY_DATE", "SCORE" if "SCORE" in t.columns else "SYMBOL"], ascending=[True, False] if "SCORE" in t.columns else [True, True])
    equity = float(initial_capital)
    peak = equity
    max_dd = 0.0
    open_positions: list[dict] = []
    completed: list[dict] = []
    skipped = 0
    dates = sorted(t["ENTRY_DATE"].unique())
    for day in dates:
        day = pd.Timestamp(day)
        # Realize exits at their simulated exit dates before admitting new positions.
        closing = [p for p in open_positions if p["EXIT_DATE"] < day or p["EXIT_DATE"] == day]
        for p in closing:
            pnl = p["CAPITAL_USED"] * p["NET_RETURN_PCT"] / 100.0
            equity += pnl
            p["PNL_RS"] = round(pnl, 2)
            p["EQUITY_AFTER"] = round(equity, 2)
            completed.append(p)
            open_positions.remove(p)
            peak = max(peak, equity)
            max_dd = min(max_dd, (equity / peak - 1) * 100 if peak else 0.0)
        candidates = t[t["ENTRY_DATE"] == day]
        for _, row in candidates.iterrows():
            if len(open_positions) >= max_positions:
                skipped += 1
                continue
            sym = str(row["SYMBOL"])
            if any(p["SYMBOL"] == sym for p in open_positions):
                skipped += 1
                continue
            entry = float(row["ENTRY"])
            stop = float(row["INITIAL_STOP"])
            risk_per_share = entry - stop
            if not np.isfinite(entry) or not np.isfinite(stop) or entry <= 0 or risk_per_share <= 0 or equity <= 0:
                skipped += 1
                continue
            open_risk = sum(p["RISK_RS"] for p in open_positions)
            risk_budget = max(0.0, equity * risk_per_trade_pct / 100.0)
            portfolio_budget = max(0.0, equity * max_open_risk_pct / 100.0 - open_risk)
            cash_used = sum(p["CAPITAL_USED"] for p in open_positions)
            cash = max(0.0, equity - cash_used)
            qty = min(
                int(risk_budget // risk_per_share),
                int(portfolio_budget // risk_per_share),
                int((equity * max_single_position_pct / 100.0) // entry),
                int(cash // entry),
            )
            if qty < 1:
                skipped += 1
                continue
            net_ret = float(row["NET_RETURN_PCT"]) - (float(cost_pct) - BASE_COST_PCT) - float(gap_down_stress_pct)
            p = row.to_dict()
            p.update({"QTY": qty, "CAPITAL_USED": round(qty * entry, 2),
                      "CAPITAL_PCT": round(qty * entry / equity * 100, 3),
                      "RISK_RS": round(qty * risk_per_share, 2), "NET_RETURN_PCT": net_ret,
                      "PORTFOLIO_ENTRY_EQUITY": equity, "STRESS_COST_PCT": float(cost_pct),
                      "GAP_DOWN_STRESS_PCT": float(gap_down_stress_pct)})
            open_positions.append(p)
    # Close remaining open trades at their simulated EXIT prices so the run is closed-trade complete.
    for p in sorted(open_positions, key=lambda x: x["EXIT_DATE"]):
        pnl = p["CAPITAL_USED"] * p["NET_RETURN_PCT"] / 100.0
        equity += pnl
        p["PNL_RS"] = round(pnl, 2)
        p["EQUITY_AFTER"] = round(equity, 2)
        completed.append(p)
        peak = max(peak, equity)
        max_dd = min(max_dd, (equity / peak - 1) * 100 if peak else 0.0)
    out = pd.DataFrame(completed)
    if not out.empty:
        out = out.sort_values(["EXIT_DATE", "SYMBOL"]).reset_index(drop=True)
        eq = pd.to_numeric(out["EQUITY_AFTER"], errors="coerce")
        pnl = pd.to_numeric(out["PNL_RS"], errors="coerce")
        summary = _metrics(eq, pnl, out)
        summary.update({"skipped": int(skipped), "initial_capital": float(initial_capital),
                        "risk_per_trade_pct": float(risk_per_trade_pct), "max_positions": int(max_positions),
                        "max_open_risk_pct": float(max_open_risk_pct), "max_single_position_pct": float(max_single_position_pct),
                        "cost_pct": float(cost_pct), "gap_down_stress_pct": float(gap_down_stress_pct),
                        "max_drawdown_pct": round(float(max_dd), 3),
                        "drawdown_basis": "CONCURRENT_SIZED_CLOSED_TRADE_EQUITY; OPEN TRADES MARKED AT SIMULATED EXIT"})
    else:
        summary = {"trades": 0, "skipped": int(skipped), "initial_capital": float(initial_capital),
                   "ending_equity": float(initial_capital), "total_return_pct": 0.0, "max_drawdown_pct": 0.0,
                   "profit_factor": np.nan, "win_pct": np.nan, "avg_exposure_pct": 0.0,
                   "cost_pct": float(cost_pct), "gap_down_stress_pct": float(gap_down_stress_pct)}
    return out, summary


def robustness_scenarios(trades: pd.DataFrame, **kwargs) -> pd.DataFrame:
    """Baseline and adverse cost/gap sensitivity; not a substitute for real fills."""
    rows = []
    for cost, gap, label in [
        (0.35, 0.0, "BASE_0.35_COST"),
        (0.50, 0.0, "COST_0.50"),
        (0.75, 0.0, "COST_0.75"),
        (0.50, 1.0, "COST_0.50_PLUS_1PCT_GAP_STRESS"),
    ]:
        _, summary = run_concurrent_portfolio_backtest(trades, cost_pct=cost, gap_down_stress_pct=gap, **kwargs)
        rows.append({"SCENARIO": label, **summary})
    return pd.DataFrame(rows)


def audit_universe_history(history: pd.DataFrame, requested_symbols: list[str] | None = None) -> pd.DataFrame:
    """Coverage diagnostics only; historical constituent membership cannot be inferred from OHLCV."""
    if history is None or history.empty or not {"SYMBOL", "DATE"}.issubset(history.columns):
        return pd.DataFrame([{"CHECK": "HISTORY_AVAILABLE", "STATUS": "FAIL", "DETAIL": "Missing SYMBOL/DATE history"}])
    h = history.copy()
    h["DATE"] = pd.to_datetime(h["DATE"], errors="coerce")
    first, last = h["DATE"].min(), h["DATE"].max()
    counts = h.groupby("SYMBOL")["DATE"].agg(["min", "max", "count"])
    requested = set(requested_symbols or h["SYMBOL"].dropna().unique())
    missing = sorted(requested - set(counts.index))
    rows = [
        {"CHECK": "HISTORY_COVERAGE", "STATUS": "INFO", "DETAIL": f"{first:%Y-%m-%d} to {last:%Y-%m-%d}; {len(counts)} symbols; {h['DATE'].nunique()} sessions"},
        {"CHECK": "MISSING_REQUESTED_SYMBOLS", "STATUS": "WARN" if missing else "PASS", "DETAIL": ", ".join(missing[:30]) if missing else "None"},
        {"CHECK": "POINT_IN_TIME_UNIVERSE", "STATUS": "NOT_VALIDATED", "DETAIL": "Current/requested universe membership is not historical membership; delisted/removed symbols are not reconstructed."},
        {"CHECK": "SURVIVORSHIP_BIAS", "STATUS": "PRESENT", "DETAIL": "Historical performance must be treated as survivorship-biased until dated historical constituents and delisted securities are sourced."},
        {"CHECK": "DATA_GAPS", "STATUS": "WARN" if counts["count"].min() < h["DATE"].nunique() * 0.5 else "INFO",
         "DETAIL": f"per-symbol rows min={int(counts['count'].min())}, median={int(counts['count'].median())}; listing dates and trading holidays vary"},
    ]
    return pd.DataFrame(rows)

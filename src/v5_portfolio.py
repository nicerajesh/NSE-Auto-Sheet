"""Portfolio-level V5 backtest with cash, risk sizing, concurrency and daily equity.

Signals are generated on a completed close and entered at the next available
symbol session open. This remains a research simulation, not broker-grade fills.
"""
from __future__ import annotations

import math
import numpy as np
import pandas as pd


def run_portfolio_v5(
    features: pd.DataFrame,
    initial_capital: float = 1_000_000.0,
    risk_per_trade_pct: float = 0.5,
    max_positions: int = 12,
    max_position_pct: float = 15.0,
    max_open_risk_pct: float = 6.0,
    max_new_per_day: int = 5,
    target_r: float = 3.0,
    max_hold: int = 60,
    max_gap_pct: float = 2.0,
    min_turnover_cr: float = 5.0,
    cost_pct: float = 0.35,
    cooldown: int = 10,
    start: str = "2019-01-01",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    """Return closed trades, daily equity, yearly stats, open positions, summary."""
    required = {"SYMBOL", "DATE", "OPEN", "HIGH", "LOW", "CLOSE", "TURNOVER_CR",
                "ATR", "V5_BUY", "V5_STOP", "V5_SCORE"}
    missing = required - set(features.columns)
    if missing:
        raise ValueError(f"Portfolio backtest missing columns: {sorted(missing)}")
    f = features.sort_values(["DATE", "SYMBOL"]).copy()
    f["DATE"] = pd.to_datetime(f["DATE"]).dt.normalize()
    f = f[f["DATE"] >= pd.Timestamp(start)]
    if f.empty:
        raise ValueError("No V5 feature rows in requested portfolio backtest period")

    # Build daily symbol lookup and next-session signal queue.
    day_rows = {}
    for date, group in f.groupby("DATE", sort=True):
        day_rows[date] = group.set_index("SYMBOL").to_dict("index")
    entry_queue: dict[pd.Timestamp, list[dict]] = {}
    for symbol, group in f.groupby("SYMBOL", sort=False):
        g = group.sort_values("DATE").reset_index(drop=True)
        for i in range(len(g) - 1):
            row = g.iloc[i]
            if not bool(row["V5_BUY"]) or pd.isna(row["TURNOVER_CR"]) or row["TURNOVER_CR"] < min_turnover_cr:
                continue
            nxt = g.iloc[i + 1]
            stop = float(row["V5_STOP"])
            close = float(row["CLOSE"])
            if not np.isfinite(stop) or stop <= 0 or stop >= close:
                continue
            entry_queue.setdefault(pd.Timestamp(nxt["DATE"]).normalize(), []).append({
                "SYMBOL": symbol, "SIGNAL_DATE": pd.Timestamp(row["DATE"]),
                "ENTRY": float(nxt["OPEN"]), "SIGNAL_CLOSE": close, "STOP": stop,
                "SCORE": float(row["V5_SCORE"]),
                "SETUP": str(row.get("V5_SETUP", "V5")),
                "TURNOVER_CR": float(row["TURNOVER_CR"]),
            })

    cash = float(initial_capital)
    positions: dict[str, dict] = {}
    last_exit_date: dict[str, pd.Timestamp] = {}
    trades: list[dict] = []
    equity_rows: list[dict] = []
    max_concurrent = 0
    total_entry_fees = 0.0
    total_exit_fees = 0.0
    dates = sorted(day_rows)

    def mark_equity(rows):
        value = cash
        for sym, pos in positions.items():
            bar = rows.get(sym)
            px = float(bar["CLOSE"]) if bar and np.isfinite(float(bar["CLOSE"])) else pos["LAST_CLOSE"]
            value += pos["QTY"] * px
        return value

    def close_position(sym, pos, date, px, reason):
        nonlocal cash, total_exit_fees
        notional = pos["QTY"] * px
        fee = notional * cost_pct / 20000.0
        pnl_gross = pos["QTY"] * (px - pos["ENTRY"])
        cash += notional - fee
        total_exit_fees += fee
        pnl_net = pnl_gross - pos["ENTRY_FEE"] - fee
        risk_cash = pos["QTY"] * (pos["ENTRY"] - pos["STOP"])
        trades.append({
            "SYMBOL": sym, "SIGNAL_DATE": pos["SIGNAL_DATE"],
            "ENTRY_DATE": pos["ENTRY_DATE"], "EXIT_DATE": date,
            "ENTRY": pos["ENTRY"], "EXIT": px, "STOP": pos["STOP"],
            "QTY": pos["QTY"], "CAPITAL_USED": pos["QTY"] * pos["ENTRY"],
            "GROSS_PNL": pnl_gross, "FEES": pos["ENTRY_FEE"] + fee,
            "NET_PNL": pnl_net,
            "RET_PCT": pnl_net / (pos["QTY"] * pos["ENTRY"]) * 100,
            "R": pnl_net / risk_cash if risk_cash > 0 else np.nan,
            "HOLD": pos["BARS_HELD"], "REASON": reason,
            "SETUP": pos["SETUP"], "V5_SCORE": pos["SCORE"],
        })
        last_exit_date[sym] = date

    for date in dates:
        rows = day_rows[date]

        # Existing positions: conservative stop-first daily-bar execution.
        for sym in list(positions):
            pos = positions[sym]
            bar = rows.get(sym)
            if bar is None:
                continue
            op, hi, lo, cl = (float(bar[k]) for k in ("OPEN", "HIGH", "LOW", "CLOSE"))
            pos["LAST_CLOSE"] = cl
            pos["BARS_HELD"] += 1
            if lo <= pos["STOP"]:
                close_position(sym, pos, date, min(op, pos["STOP"]), "STOP")
                del positions[sym]
            elif hi >= pos["TARGET"]:
                close_position(sym, pos, date, max(op, pos["TARGET"]), f"TARGET_{target_r:g}R")
                del positions[sym]
            elif pos["BARS_HELD"] >= max_hold:
                close_position(sym, pos, date, cl, "TIME_EXIT")
                del positions[sym]

        # Rank same-day entries; do not let low-quality duplicates crowd out stronger signals.
        candidates = sorted(entry_queue.get(date, []),
                            key=lambda x: (x["SCORE"], x["TURNOVER_CR"], x["SYMBOL"]), reverse=True)
        new_count = 0
        for c in candidates:
            sym = c["SYMBOL"]
            if new_count >= max_new_per_day or len(positions) >= max_positions:
                break
            if sym in positions:
                continue
            prev_exit = last_exit_date.get(sym)
            if prev_exit is not None and (date - prev_exit).days < cooldown * 1.4:
                continue
            entry, stop = c["ENTRY"], c["STOP"]
            if not np.isfinite(entry) or entry <= stop or entry <= 0:
                continue
            if (entry / c["SIGNAL_CLOSE"] - 1) * 100 > max_gap_pct:
                continue
            bar = rows.get(sym)
            if bar is None:
                continue
            equity_now = mark_equity(rows)
            risk_per_share = entry - stop
            risk_budget = equity_now * risk_per_trade_pct / 100
            open_risk = sum(p["QTY"] * (p["ENTRY"] - p["STOP"]) for p in positions.values())
            remaining_risk = max(0.0, equity_now * max_open_risk_pct / 100 - open_risk)
            max_value = equity_now * max_position_pct / 100
            qty_risk = math.floor(min(risk_budget, remaining_risk) / risk_per_share)
            qty_value = math.floor(max_value / entry)
            qty_cash = math.floor(cash / (entry * (1 + cost_pct / 20000.0)))
            qty = min(qty_risk, qty_value, qty_cash)
            if qty <= 0:
                continue
            used = qty * entry
            entry_fee = used * cost_pct / 20000.0
            cash -= used + entry_fee
            total_entry_fees += entry_fee
            pos = {
                "SIGNAL_DATE": c["SIGNAL_DATE"], "ENTRY_DATE": date,
                "ENTRY": entry, "STOP": stop,
                "TARGET": entry + target_r * risk_per_share,
                "QTY": qty, "ENTRY_FEE": entry_fee, "BARS_HELD": 0,
                "LAST_CLOSE": float(bar["CLOSE"]),
                "SETUP": c["SETUP"], "SCORE": c["SCORE"],
            }
            positions[sym] = pos
            new_count += 1
            max_concurrent = max(max_concurrent, len(positions))

            # New entry can hit stop/target on its entry session.
            op, hi, lo, cl = (float(bar[k]) for k in ("OPEN", "HIGH", "LOW", "CLOSE"))
            pos["LAST_CLOSE"] = cl
            pos["BARS_HELD"] = 1
            if lo <= stop:
                close_position(sym, pos, date, min(op, stop), "STOP")
                del positions[sym]
            elif hi >= pos["TARGET"]:
                close_position(sym, pos, date, max(op, pos["TARGET"]), f"TARGET_{target_r:g}R")
                del positions[sym]

        eq = mark_equity(rows)
        gross_exposure = sum(p["QTY"] * p["LAST_CLOSE"] for p in positions.values())
        open_risk = sum(p["QTY"] * (p["ENTRY"] - p["STOP"]) for p in positions.values())
        equity_rows.append({
            "DATE": date, "EQUITY": eq, "CASH": cash,
            "OPEN_POSITIONS": len(positions), "GROSS_EXPOSURE": gross_exposure,
            "OPEN_RISK": open_risk,
        })

    # Mark remaining positions at final available close; do not pretend they are closed trades.
    final_date = dates[-1]
    final_rows = day_rows[final_date]
    open_rows = []
    for sym, pos in positions.items():
        bar = final_rows.get(sym)
        last_px = float(bar["CLOSE"]) if bar else pos["LAST_CLOSE"]
        open_rows.append({
            "SYMBOL": sym, "ENTRY_DATE": pos["ENTRY_DATE"], "ENTRY": pos["ENTRY"],
            "LAST_CLOSE": last_px, "STOP": pos["STOP"], "TARGET": pos["TARGET"],
            "QTY": pos["QTY"], "UNREALIZED_PNL_BEFORE_EXIT_FEE": pos["QTY"] * (last_px - pos["ENTRY"]) - pos["ENTRY_FEE"],
            "HOLD": pos["BARS_HELD"], "SETUP": pos["SETUP"], "V5_SCORE": pos["SCORE"],
        })

    eq = pd.DataFrame(equity_rows)
    if not eq.empty:
        eq["PEAK"] = eq["EQUITY"].cummax().clip(lower=initial_capital)
        eq["DRAWDOWN_PCT"] = (eq["EQUITY"] / eq["PEAK"] - 1) * 100
        eq["DAILY_RETURN_PCT"] = eq["EQUITY"].pct_change().fillna(0) * 100
    t = pd.DataFrame(trades)
    if t.empty:
        t = pd.DataFrame(columns=["SYMBOL", "SIGNAL_DATE", "ENTRY_DATE", "EXIT_DATE", "ENTRY", "EXIT", "STOP", "QTY", "CAPITAL_USED", "GROSS_PNL", "FEES", "NET_PNL", "RET_PCT", "R", "HOLD", "REASON", "SETUP", "V5_SCORE"])
    if not t.empty:
        t = t.sort_values(["ENTRY_DATE", "SYMBOL"]).reset_index(drop=True)

    wins = float(t.loc[t.NET_PNL > 0, "NET_PNL"].sum()) if not t.empty else 0.0
    losses = float(-t.loc[t.NET_PNL < 0, "NET_PNL"].sum()) if not t.empty else 0.0
    ending_equity = float(eq.iloc[-1]["EQUITY"]) if not eq.empty else initial_capital
    years = max((dates[-1] - dates[0]).days / 365.25, 1 / 365.25)
    cagr = ((ending_equity / initial_capital) ** (1 / years) - 1) * 100 if ending_equity > 0 else -100.0
    summary = {
        "initial_capital": round(initial_capital, 2),
        "ending_equity_mark_to_market": round(ending_equity, 2),
        "net_return_pct_mark_to_market": round((ending_equity / initial_capital - 1) * 100, 2),
        "cagr_pct_mark_to_market": round(cagr, 2),
        "closed_trades": int(len(t)),
        "open_positions_at_end": int(len(open_rows)),
        "win_pct_closed_trades": round(float((t.NET_PNL > 0).mean() * 100), 2) if not t.empty else np.nan,
        "profit_factor_closed_trades": round(wins / losses, 3) if losses > 0 else (float("inf") if wins > 0 else np.nan),
        "avg_net_trade_pnl": round(float(t.NET_PNL.mean()), 2) if not t.empty else np.nan,
        "max_portfolio_drawdown_pct": round(float(eq.DRAWDOWN_PCT.min()), 2) if not eq.empty else np.nan,
        "max_concurrent_positions": int(max_concurrent),
        "total_entry_fees": round(total_entry_fees, 2),
        "total_exit_fees": round(total_exit_fees, 2),
        "average_gross_exposure_pct": round(float((eq.GROSS_EXPOSURE / eq.EQUITY * 100).mean()), 2) if not eq.empty else np.nan,
        "max_gross_exposure_pct": round(float((eq.GROSS_EXPOSURE / eq.EQUITY * 100).max()), 2) if not eq.empty else np.nan,
        "max_open_risk_pct": round(float((eq.OPEN_RISK / eq.EQUITY * 100).max()), 2) if not eq.empty else np.nan,
        "assumptions": "0.5% risk/trade; max 12 positions; max 15% capital/position; max 6% open risk; 3R target; 60-session max hold; 0.35% round-trip costs; stop-first daily bars",
    }
    yearly_rows = []
    if not eq.empty:
        q = eq.copy()
        q["YEAR"] = pd.to_datetime(q.DATE).dt.year
        prev_equity = initial_capital
        for year, g in q.groupby("YEAR", sort=True):
            end_eq = float(g.iloc[-1].EQUITY)
            ytrades = t[pd.to_datetime(t.EXIT_DATE).dt.year == year] if not t.empty else t
            ywin = float((ytrades.NET_PNL > 0).mean() * 100) if not ytrades.empty else np.nan
            yloss = -float(ytrades.loc[ytrades.NET_PNL < 0, "NET_PNL"].sum()) if not ytrades.empty else 0.0
            ywin_sum = float(ytrades.loc[ytrades.NET_PNL > 0, "NET_PNL"].sum()) if not ytrades.empty else 0.0
            yearly_rows.append({
                "YEAR": int(year), "START_EQUITY": round(prev_equity, 2),
                "END_EQUITY": round(end_eq, 2),
                "PORTFOLIO_RETURN_PCT": round((end_eq / prev_equity - 1) * 100, 2) if prev_equity else np.nan,
                "TRADES_CLOSED": int(len(ytrades)), "WIN_PCT": round(ywin, 2) if np.isfinite(ywin) else np.nan,
                "PROFIT_FACTOR": round(ywin_sum / yloss, 3) if yloss > 0 else (float("inf") if ywin_sum > 0 else np.nan),
                "MAX_DRAWDOWN_WITHIN_YEAR_PCT": round(float(g.DRAWDOWN_PCT.min()), 2),
            })
            prev_equity = end_eq
    yearly = pd.DataFrame(yearly_rows)
    open_df = pd.DataFrame(open_rows)
    return t, eq, yearly, open_df, summary

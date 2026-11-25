"""Capital-constrained delivery portfolio backtest.

Signals are generated on a completed daily close and filled at the next session open.
Daily OHLC exits use stop-first handling when stop and target are both touched.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def run_delivery20_portfolio(
    f: pd.DataFrame,
    initial_capital: float = 500_000.0,
    risk_per_trade_pct: float = 0.5,
    max_positions: int = 10,
    max_position_pct: float = 10.0,
    max_open_risk_pct: float = 5.0,
    max_new_per_day: int = 3,
    cost_pct: float = 0.35,
    max_hold: int = 120,
    max_gap_pct: float = 2.0,
    target_pct: float = 20.0,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    required = {"SYMBOL", "DATE", "OPEN", "HIGH", "LOW", "CLOSE",
                "D20_BUY", "D20_STOP", "MOM_RANK"}
    missing = required - set(f.columns)
    if missing:
        raise ValueError(f"Delivery portfolio missing columns: {sorted(missing)}")
    if initial_capital <= 0 or max_positions < 1 or max_new_per_day < 1:
        raise ValueError("Capital, max_positions and max_new_per_day must be positive")

    d = f.sort_values(["SYMBOL", "DATE"]).copy()
    d["DATE"] = pd.to_datetime(d["DATE"])
    d["NEXT_DATE"] = d.groupby("SYMBOL")["DATE"].shift(-1)
    d["NEXT_OPEN"] = d.groupby("SYMBOL")["OPEN"].shift(-1)
    entries: dict[pd.Timestamp, list[dict]] = {}
    for r in d[d["D20_BUY"].fillna(False) & d["NEXT_DATE"].notna()].itertuples(index=False):
        entries.setdefault(pd.Timestamp(r.NEXT_DATE), []).append({
            "symbol": r.SYMBOL, "signal_date": pd.Timestamp(r.DATE),
            "signal_close": float(r.CLOSE), "stop": float(r.D20_STOP),
            "mom_rank": float(r.MOM_RANK),
        })

    bars: dict[pd.Timestamp, dict[str, tuple[float, float, float, float]]] = {}
    for r in d.itertuples(index=False):
        bars.setdefault(pd.Timestamp(r.DATE), {})[r.SYMBOL] = (
            float(r.OPEN), float(r.HIGH), float(r.LOW), float(r.CLOSE)
        )
    dates = sorted(bars)
    if not dates:
        empty = pd.DataFrame()
        return empty, empty, empty, empty, {"trades": 0, "ending_equity": initial_capital}

    cash = float(initial_capital)
    positions: dict[str, dict] = {}
    closed: list[dict] = []
    equity_rows: list[dict] = []
    fee_side = cost_pct / 200.0
    max_concurrent = 0
    total_entry_fees = 0.0
    total_exit_fees = 0.0

    def mark_equity() -> tuple[float, float, float]:
        exposure = 0.0
        open_risk = 0.0
        market_value = 0.0
        for p in positions.values():
            px = p["last_close"]
            value = p["qty"] * px
            market_value += value
            exposure += value
            open_risk += p["qty"] * max(0.0, p["entry"] - p["stop"])
        estimated_exit_fee = market_value * fee_side
        return cash + market_value - estimated_exit_fee, exposure, open_risk

    def close_position(symbol: str, date: pd.Timestamp, exit_px: float, reason: str) -> None:
        nonlocal cash, total_exit_fees
        p = positions.pop(symbol)
        exit_notional = p["qty"] * exit_px
        exit_fee = exit_notional * fee_side
        total_exit_fees += exit_fee
        cash += exit_notional - exit_fee
        net_pnl = exit_notional - p["qty"] * p["entry"] - p["entry_fee"] - exit_fee
        closed.append({
            "SYMBOL": symbol, "SIGNAL_DATE": p["signal_date"],
            "ENTRY_DATE": p["entry_date"], "EXIT_DATE": date,
            "ENTRY": p["entry"], "EXIT": exit_px, "STOP": p["stop"],
            "TARGET": p["target"], "QTY": p["qty"],
            "CAPITAL_USED": round(p["qty"] * p["entry"], 2),
            "MOM_RANK": p["mom_rank"], "TARGET_PCT": target_pct,
            "NET_PNL": round(net_pnl, 2),
            "NET_RETURN_PCT": round(net_pnl / (p["qty"] * p["entry"]) * 100, 4),
            "REASON": reason, "HOLD_SESSIONS": p["held_sessions"],
            "ENTRY_FEE": round(p["entry_fee"], 2), "EXIT_FEE": round(exit_fee, 2),
        })

    for date in dates:
        today = bars[date]

        # Existing positions: gap exits first, then conservative intraday stop/target.
        for symbol in list(positions):
            if symbol not in today:
                continue
            op, hi, lo, cl = today[symbol]
            p = positions[symbol]
            p["last_close"] = cl
            if op <= p["stop"]:
                close_position(symbol, date, op, "STOP_GAP")
            elif op >= p["target"]:
                close_position(symbol, date, op, "TARGET_GAP")
            elif lo <= p["stop"]:
                close_position(symbol, date, p["stop"], "STOP")
            elif hi >= p["target"]:
                close_position(symbol, date, p["target"], f"TARGET_{target_pct:g}")
            elif p["held_sessions"] + 1 >= max_hold:
                close_position(symbol, date, cl, "TIME_EXIT")
            else:
                p["held_sessions"] += 1

        # New signals from previous session, ranked by momentum strength.
        candidates = sorted(entries.get(date, []), key=lambda x: (-x["mom_rank"], x["symbol"]))
        opened_today = 0
        for sig in candidates:
            if opened_today >= max_new_per_day or len(positions) >= max_positions:
                break
            symbol = sig["symbol"]
            if symbol in positions or symbol not in today:
                continue
            op, hi, lo, cl = today[symbol]
            stop = sig["stop"]
            if not np.isfinite(op) or op <= stop or op <= 0:
                continue
            if (op / sig["signal_close"] - 1) * 100 > max_gap_pct:
                continue
            risk_per_share = op - stop
            if risk_per_share <= 0:
                continue
            equity_now, _, open_risk = mark_equity()
            risk_budget = equity_now * risk_per_trade_pct / 100
            risk_room = max(0.0, equity_now * max_open_risk_pct / 100 - open_risk)
            position_cap = equity_now * max_position_pct / 100
            qty_capital = cash / (op * (1 + fee_side))
            qty = int(max(0, np.floor(min(
                risk_budget / risk_per_share,
                risk_room / risk_per_share,
                position_cap / op,
                qty_capital,
            ))))
            if qty < 1:
                continue
            notional = qty * op
            entry_fee = notional * fee_side
            cash -= notional + entry_fee
            total_entry_fees += entry_fee
            target = op * (1 + target_pct / 100)
            positions[symbol] = {
                "signal_date": sig["signal_date"], "entry_date": date,
                "entry": op, "stop": stop, "target": target,
                "qty": qty, "entry_fee": entry_fee,
                "mom_rank": sig["mom_rank"], "last_close": cl,
                "held_sessions": 1,
            }
            opened_today += 1
            max_concurrent = max(max_concurrent, len(positions))

            # Entry-day intraday movement also counts; stop-first if both levels touch.
            if lo <= stop:
                close_position(symbol, date, stop, "STOP")
            elif hi >= target:
                close_position(symbol, date, target, f"TARGET_{target_pct:g}")

        equity, exposure, open_risk = mark_equity()
        equity_rows.append({
            "DATE": date, "CASH": round(cash, 2),
            "EQUITY": round(equity, 2), "GROSS_EXPOSURE": round(exposure, 2),
            "OPEN_RISK": round(open_risk, 2), "OPEN_POSITIONS": len(positions),
        })

    open_rows = []
    for symbol, p in positions.items():
        open_rows.append({
            "SYMBOL": symbol, "SIGNAL_DATE": p["signal_date"],
            "ENTRY_DATE": p["entry_date"], "ENTRY": p["entry"],
            "LTP": p["last_close"], "STOP": p["stop"], "TARGET": p["target"],
            "QTY": p["qty"], "UNREALIZED_PNL": round(
                p["qty"] * (p["last_close"] - p["entry"]) - p["entry_fee"]
                - p["qty"] * p["last_close"] * fee_side, 2
            ),
            "MOM_RANK": p["mom_rank"], "HOLD_SESSIONS": p["held_sessions"],
        })
    trades = pd.DataFrame(closed)
    equity_curve = pd.DataFrame(equity_rows)
    open_positions = pd.DataFrame(open_rows)

    if not equity_curve.empty:
        equity_curve["PEAK"] = np.maximum(equity_curve["EQUITY"].cummax(), initial_capital)
        equity_curve["DRAWDOWN_PCT"] = (
            equity_curve["EQUITY"] / equity_curve["PEAK"] - 1
        ) * 100
        equity_curve["INITIAL_DD_PCT"] = (
            equity_curve["EQUITY"] / initial_capital - 1
        ) * 100
        ending_equity = float(equity_curve["EQUITY"].iloc[-1])
        max_dd = float(equity_curve["DRAWDOWN_PCT"].min())
        days_held = max(1, (dates[-1] - dates[0]).days)
        cagr = ((ending_equity / initial_capital) ** (365.25 / days_held) - 1) * 100 if ending_equity > 0 else -100.0
    else:
        ending_equity, max_dd, cagr = initial_capital, 0.0, 0.0

    if not trades.empty:
        winners = trades.loc[trades.NET_PNL > 0, "NET_PNL"].sum()
        losers = -trades.loc[trades.NET_PNL < 0, "NET_PNL"].sum()
        win_rate = float((trades.NET_PNL > 0).mean() * 100)
        pf = float(winners / losers) if losers else (float("inf") if winners else 0.0)
        target_hit = float(trades.REASON.str.startswith("TARGET_").mean() * 100)
        avg_trade = float(trades.NET_PNL.mean())
    else:
        win_rate, pf, target_hit, avg_trade = 0.0, 0.0, 0.0, 0.0

    summary = {
        "initial_capital": round(initial_capital, 2),
        "ending_equity_mtm": round(ending_equity, 2),
        "net_return_pct": round((ending_equity / initial_capital - 1) * 100, 2),
        "cagr_pct": round(cagr, 2),
        "max_portfolio_drawdown_pct": round(max_dd, 2),
        "closed_trades": int(len(trades)),
        "open_positions": int(len(open_positions)),
        "win_rate_pct": round(win_rate, 2),
        "target_hit_pct": round(target_hit, 2),
        "profit_factor": round(pf, 3),
        "average_net_pnl_per_trade": round(avg_trade, 2),
        "max_concurrent_positions": int(max_concurrent),
        "total_entry_fees": round(total_entry_fees, 2),
        "total_exit_fees": round(total_exit_fees, 2),
        "total_fees": round(total_entry_fees + total_exit_fees, 2),
        "max_gross_exposure_pct": round(float((equity_curve.GROSS_EXPOSURE / equity_curve.EQUITY.replace(0, np.nan)).max() * 100), 2) if not equity_curve.empty else 0.0,
        "max_open_risk_pct": round(float((equity_curve.OPEN_RISK / equity_curve.EQUITY.replace(0, np.nan)).max() * 100), 2) if not equity_curve.empty else 0.0,
        "average_gross_exposure_pct": round(float((equity_curve.GROSS_EXPOSURE / equity_curve.EQUITY.replace(0, np.nan)).mean() * 100), 2) if not equity_curve.empty else 0.0,
    }

    yearly_rows = []
    if not equity_curve.empty:
        eq = equity_curve.copy()
        eq["YEAR"] = pd.to_datetime(eq["DATE"]).dt.year
        for year, group in eq.groupby("YEAR"):
            start_equity = initial_capital if year == int(pd.to_datetime(dates[0]).year) else float(
                equity_curve.loc[pd.to_datetime(equity_curve["DATE"]).dt.year < year, "EQUITY"].iloc[-1]
            )
            end_equity = float(group["EQUITY"].iloc[-1])
            year_trades = trades[pd.to_datetime(trades["EXIT_DATE"]).dt.year == year] if not trades.empty else trades
            yearly_rows.append({
                "YEAR": int(year),
                "PORTFOLIO_RETURN_PCT": round((end_equity / start_equity - 1) * 100, 2) if start_equity else 0.0,
                "CLOSED_TRADES": int(len(year_trades)),
                "WIN_RATE_PCT": round(float((year_trades.NET_PNL > 0).mean() * 100), 2) if not year_trades.empty else 0.0,
            })
    yearly = pd.DataFrame(yearly_rows)
    return trades, equity_curve, yearly, open_positions, summary

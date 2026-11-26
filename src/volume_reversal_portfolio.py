"""Portfolio-level simulation for 52-week-low reversal signals.

Uses next-session OPEN entries, fixed holding-period CLOSE exits, 0.35%
round-trip costs, equal-weight position sizing, and finite portfolio capacity.
This is a research simulation, not a production trading engine.
"""
from __future__ import annotations
import numpy as np
import pandas as pd


def simulate_portfolio(hist: pd.DataFrame, events: pd.DataFrame, tier: str,
                       horizon: int, initial_capital: float = 500000.0,
                       max_positions: int = 10, max_entries_per_day: int = 3,
                       cost_pct: float = 0.35) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    if horizon < 1 or max_positions < 1 or max_entries_per_day < 1:
        raise ValueError("horizon and portfolio limits must be positive")
    prices = {}
    calendar = set()
    for sym, g in hist.groupby("SYMBOL"):
        g = g.sort_values("DATE").reset_index(drop=True)
        g["DATE"] = pd.to_datetime(g["DATE"])
        prices[sym] = g
        calendar.update(g["DATE"].tolist())
    dates = sorted(calendar)
    date_pos = {d: i for i, d in enumerate(dates)}
    scheduled = {}
    sig = events[events["TIER"] == tier].copy()
    for row in sig.itertuples(index=False):
        g = prices.get(row.SYMBOL)
        if g is None:
            continue
        loc = g.index[g["DATE"] == pd.Timestamp(row.SIGNAL_DATE)]
        if len(loc) == 0 or int(loc[0]) + 1 >= len(g):
            continue
        entry_i = int(loc[0]) + 1
        if entry_i + horizon - 1 >= len(g):
            continue
        entry_date = g.iloc[entry_i]["DATE"]
        scheduled.setdefault(entry_date, []).append((row.SYMBOL, entry_i, row.SIGNAL_DATE))
    cash = float(initial_capital)
    positions = []
    curve, trades = [], []
    for day in dates:
        # Exit positions at today's close before processing new entries.
        still_open = []
        for p in positions:
            g = prices[p["symbol"]]
            if p["exit_i"] == p["entry_i"] + horizon - 1 and g.iloc[p["exit_i"]]["DATE"] == day:
                exit_price = float(g.iloc[p["exit_i"]]["CLOSE"])
                gross = (exit_price / p["entry_price"] - 1.0) * 100.0
                net = gross - cost_pct
                proceeds = p["shares"] * exit_price
                cash += proceeds
                trades.append({"SYMBOL": p["symbol"], "SIGNAL_DATE": p["signal_date"],
                    "ENTRY_DATE": p["entry_date"], "EXIT_DATE": day, "TIER": tier,
                    "HORIZON": horizon, "ENTRY_PRICE": p["entry_price"],
                    "EXIT_PRICE": exit_price, "GROSS_RETURN_PCT": gross,
                    "NET_RETURN_PCT": net, "P_AND_L": proceeds - p["notional"]})
            else:
                still_open.append(p)
        positions = still_open
        # Signals are known after the previous close; enter at today's open.
        candidates = sorted(scheduled.get(day, []), key=lambda x: (str(x[2]), x[0]))
        opened = 0
        held_symbols = {p["symbol"] for p in positions}
        for sym, entry_i, signal_date in candidates:
            if opened >= max_entries_per_day or len(positions) >= max_positions:
                break
            if sym in held_symbols:
                continue
            g = prices[sym]
            entry_price = float(g.iloc[entry_i]["OPEN"])
            if not np.isfinite(entry_price) or entry_price <= 0:
                continue
            # Equal-weight target based on current marked equity; never borrow.
            marked = cash
            for p in positions:
                pg = prices[p["symbol"]]
                ploc = pg.index[pg["DATE"] == day]
                if len(ploc):
                    marked += p["shares"] * float(pg.iloc[int(ploc[0])]["CLOSE"])
            notional = min(marked / max_positions, cash)
            if notional <= 0:
                break
            shares = notional / entry_price
            cash -= notional
            positions.append({"symbol": sym, "entry_i": entry_i,
                "exit_i": entry_i + horizon - 1, "entry_price": entry_price,
                "entry_date": day, "signal_date": signal_date,
                "shares": shares, "notional": notional})
            held_symbols.add(sym)
            opened += 1
        # Mark open positions to close; price series may end on different dates.
        market_value = 0.0
        for p in positions:
            g = prices[p["symbol"]]
            loc = g.index[g["DATE"] == day]
            if len(loc):
                market_value += p["shares"] * float(g.iloc[int(loc[0])]["CLOSE"])
        equity = cash + market_value
        curve.append({"DATE": day, "EQUITY": equity, "CASH": cash,
                      "OPEN_POSITIONS": len(positions)})
    curve_df = pd.DataFrame(curve)
    trades_df = pd.DataFrame(trades)
    if curve_df.empty:
        return {"TRADES": 0}, curve_df, trades_df
    daily_ret = curve_df["EQUITY"].pct_change().dropna()
    years = max((curve_df["DATE"].iloc[-1] - curve_df["DATE"].iloc[0]).days / 365.25, 1/365.25)
    final_equity = float(curve_df["EQUITY"].iloc[-1])
    peak = curve_df["EQUITY"].cummax()
    drawdown = (curve_df["EQUITY"] / peak - 1) * 100
    wins = trades_df.loc[trades_df["NET_RETURN_PCT"] > 0, "P_AND_L"].sum() if not trades_df.empty else 0.0
    losses = -trades_df.loc[trades_df["NET_RETURN_PCT"] < 0, "P_AND_L"].sum() if not trades_df.empty else 0.0
    metrics = {"TIER": tier, "HORIZON": horizon, "INITIAL_CAPITAL": initial_capital,
        "FINAL_EQUITY": round(final_equity, 2),
        "TOTAL_RETURN_PCT": round((final_equity / initial_capital - 1) * 100, 2),
        "CAGR_PCT": round(((final_equity / initial_capital) ** (1 / years) - 1) * 100, 2) if final_equity > 0 else -100.0,
        "MAX_DRAWDOWN_PCT": round(float(drawdown.min()), 2),
        "TRADES": len(trades_df),
        "TRADE_WIN_RATE_PCT": round(float((trades_df["NET_RETURN_PCT"] > 0).mean() * 100), 2) if not trades_df.empty else 0.0,
        "TRADE_PROFIT_FACTOR": round(float(wins / losses), 3) if losses > 0 else (float("inf") if wins > 0 else 0.0),
        "AVG_EXPOSURE_POSITIONS": round(float(curve_df["OPEN_POSITIONS"].mean()), 2)}
    return metrics, curve_df, trades_df

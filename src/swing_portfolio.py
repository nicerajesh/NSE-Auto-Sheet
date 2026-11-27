"""Research-only portfolio simulation for confirmed Swing Turn signals."""
from __future__ import annotations
import numpy as np
import pandas as pd


def run_swing_portfolio_backtest(frame, initial_capital=1_000_000.0, max_positions=5,
                                 max_hold=40, cost_pct=0.35, oos_start="2023-01-01"):
    """Next-session OPEN entry; equal-weight slots; 2R partial, 3R final.

    Conservative daily OHLC rule: stop wins if stop and target touch same bar.
    Gap-through stop fills at OPEN. Round-trip cost is charged pro-rata.
    """
    need = {"SYMBOL", "DATE", "OPEN", "HIGH", "LOW", "CLOSE", "ATR", "RSI",
            "TURN_BUY", "TURN_PIVOT_LOW_PRICE"}
    missing = need - set(frame.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")
    if initial_capital <= 0 or max_positions < 1 or max_hold < 1 or cost_pct < 0:
        raise ValueError("Invalid portfolio parameters")
    d = frame.sort_values(["DATE", "SYMBOL"]).copy()
    d["DATE"] = pd.to_datetime(d["DATE"])
    groups = {s: g.sort_values("DATE").reset_index(drop=True) for s, g in d.groupby("SYMBOL")}
    daily = {dt: g.set_index("SYMBOL") for dt, g in d.groupby("DATE", sort=True)}
    signals = {}
    for sym, g in groups.items():
        for i, row in g.iterrows():
            if bool(row.TURN_BUY) and i + 1 < len(g):
                nxt = g.iloc[i + 1]
                signals.setdefault(nxt.DATE, []).append({
                    "symbol": sym, "signal_date": row.DATE, "entry": float(nxt.OPEN),
                    "signal_close": float(row.CLOSE), "atr": float(row.ATR),
                    "pivot": float(row.TURN_PIVOT_LOW_PRICE), "rsi": float(row.RSI)})
    cash, positions, trades, curve = float(initial_capital), {}, [], []
    fee = cost_pct / 100.0
    dates = sorted(daily)

    def finish(sym, p, date, price, reason):
        nonlocal cash
        qty = p["qty"]
        gross = qty * price
        exit_fee = gross * fee
        cash += gross - exit_fee
        p["realized"] += gross - exit_fee - qty * p["entry"]
        p["cost"] += exit_fee
        trades.append({"SYMBOL": sym, "SIGNAL_DATE": p["signal_date"], "ENTRY_DATE": p["entry_date"],
            "ENTRY_PRICE": p["entry"], "EXIT_DATE": date, "EXIT_REASON": reason,
            "REALIZED_PNL": p["realized"], "RETURN_PCT": p["realized"] / p["allocated"] * 100,
            "HOLD_SESSIONS": p["age"], "COST_PAID": p["cost"],
            "OOS": p["entry_date"] >= pd.Timestamp(oos_start)})

    for date in dates:
        today = daily[date]
        # Exits first; all decisions use only today's OHLC.
        for sym in list(positions):
            if sym not in today.index:
                continue
            p, r = positions[sym], today.loc[sym]
            op, hi, lo, cl = map(float, (r.OPEN, r.HIGH, r.LOW, r.CLOSE))
            stop = p["stop"]
            if op <= stop:
                finish(sym, p, date, op, "STOP_GAP"); del positions[sym]; continue
            if lo <= stop:
                finish(sym, p, date, stop, "STOP"); del positions[sym]; continue
            if not p["t1_done"] and hi >= p["t1"]:
                qty = p["qty"] * 0.5
                gross = qty * p["t1"]
                exit_fee = gross * fee
                cash += gross - exit_fee
                p["realized"] += gross - exit_fee - qty * p["entry"]
                p["cost"] += exit_fee
                p["qty"] -= qty
                p["t1_done"] = True
                p["stop"] = p["entry"]
            elif p["t1_done"] and hi >= p["t2"]:
                finish(sym, p, date, p["t2"], "TARGET_3R"); del positions[sym]; continue
            p["age"] += 1
            if p["age"] >= max_hold:
                finish(sym, p, date, cl, "TIME_EXIT"); del positions[sym]

        # Candidate ranking is deterministic, with no future data.
        candidates = sorted(signals.get(date, []), key=lambda x: (-x["rsi"], x["symbol"]))
        for c in candidates:
            if len(positions) >= max_positions or c["symbol"] in positions:
                continue
            if not all(np.isfinite(c[k]) for k in ("entry", "atr", "pivot")) or c["entry"] <= 0 or c["atr"] <= 0:
                continue
            stop = min(c["pivot"], c["signal_close"] - 1.8 * c["atr"])
            risk = c["entry"] - stop
            if risk <= 0 or cash <= 0:
                continue
            allocation = min(cash, initial_capital / max_positions)
            qty = allocation / c["entry"]
            entry_fee = allocation * fee
            cash -= allocation + entry_fee
            positions[c["symbol"]] = {"signal_date": c["signal_date"], "entry_date": date,
                "entry": c["entry"], "qty": qty, "allocated": allocation, "stop": stop,
                "t1": c["entry"] + 2 * risk, "t2": c["entry"] + 3 * risk,
                "t1_done": False, "realized": -entry_fee, "cost": entry_fee, "age": 1}

        market_value = sum(p["qty"] * float(today.loc[s, "CLOSE"])
                           for s, p in positions.items() if s in today.index)
        curve.append({"DATE": date, "EQUITY": cash + market_value, "CASH": cash,
                      "OPEN_POSITIONS": len(positions)})

    if dates:
        last_date, last = dates[-1], daily[dates[-1]]
        for sym, p in list(positions.items()):
            if sym in last.index:
                finish(sym, p, last_date, float(last.loc[sym].CLOSE), "END_OF_DATA")
        if curve:
            curve[-1]["EQUITY"], curve[-1]["CASH"], curve[-1]["OPEN_POSITIONS"] = cash, cash, 0
    t, eq = pd.DataFrame(trades), pd.DataFrame(curve)
    if not eq.empty:
        eq["DRAWDOWN_PCT"] = (eq.EQUITY / eq.EQUITY.cummax() - 1) * 100
    stats = summarize_swing_portfolio(t, eq, initial_capital)
    return t, eq, stats


def summarize_swing_portfolio(trades, curve, initial_capital):
    rows = []
    for label, g in [("FULL", trades),
                     ("OOS_2023_PLUS", trades[trades.OOS] if not trades.empty else trades)]:
        if g.empty:
            rows.append({"PERIOD": label, "TRADES": 0, "WIN_PCT": np.nan,
                         "AVG_RETURN_PCT": np.nan, "PROFIT_FACTOR": np.nan, "NET_PNL": 0.0})
        else:
            wins = g.loc[g.REALIZED_PNL > 0, "REALIZED_PNL"].sum()
            losses = -g.loc[g.REALIZED_PNL < 0, "REALIZED_PNL"].sum()
            rows.append({"PERIOD": label, "TRADES": len(g),
                "WIN_PCT": round((g.REALIZED_PNL > 0).mean() * 100, 2),
                "AVG_RETURN_PCT": round(g.RETURN_PCT.mean(), 2),
                "PROFIT_FACTOR": round(wins / losses, 3) if losses else np.inf,
                "NET_PNL": round(g.REALIZED_PNL.sum(), 2),
                "AVG_HOLD_SESSIONS": round(g.HOLD_SESSIONS.mean(), 2)})
    if not curve.empty:
        final = float(curve.EQUITY.iloc[-1])
        days = max((pd.Timestamp(curve.DATE.iloc[-1]) - pd.Timestamp(curve.DATE.iloc[0])).days, 1)
        cagr = ((final / initial_capital) ** (365.25 / days) - 1) * 100 if final > 0 else -100.0
        rows[0].update({"FINAL_EQUITY": round(final, 2),
            "TOTAL_RETURN_PCT": round((final / initial_capital - 1) * 100, 2),
            "CAGR_PCT": round(cagr, 2),
            "MAX_DRAWDOWN_PCT": round(float(curve.DRAWDOWN_PCT.min()), 2)})
    return pd.DataFrame(rows)

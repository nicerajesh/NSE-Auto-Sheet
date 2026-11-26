"""Portfolio-level simulation for the exact M/J independent lab signals.

Signal definitions, 15-calendar-day per-symbol cooldown, next-session OPEN entry,
40th future-session CLOSE exit, and 0.35% round-trip cost match
src/independent_strategy_lab.py. Portfolio overlay is explicitly separate:
8 concurrent positions, max 15% of initial capital per position, shared cash,
integer shares, and deterministic same-day signal priority. No stop-loss is
invented because the original M/J event test has none.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

COST_PCT = 0.35
HOLD_SESSIONS = 40
MAX_POSITIONS = 8
MAX_POSITION_PCT = 15.0
CAPITALS = (100_000, 300_000, 500_000, 1_000_000)


def build_mj_signals(history: pd.DataFrame) -> pd.DataFrame:
    required = {"SYMBOL", "DATE", "OPEN", "HIGH", "LOW", "CLOSE", "VOLUME"}
    missing = required - set(history.columns)
    if missing:
        raise ValueError(f"Missing history columns: {sorted(missing)}")
    frames = []
    for symbol, group in history.groupby("SYMBOL", sort=False):
        if len(group) < 260:
            continue
        d = group.sort_values("DATE").reset_index(drop=True).copy()
        c, h, l, v = (d[x].astype(float) for x in ("CLOSE", "HIGH", "LOW", "VOLUME"))
        d["EMA50"] = c.ewm(span=50, adjust=False, min_periods=50).mean()
        d["EMA200"] = c.ewm(span=200, adjust=False, min_periods=180).mean()
        d["VOL20"] = v.rolling(20, min_periods=20).mean()
        d["VOL_X"] = v / d["VOL20"].replace(0, np.nan)
        d["HIGH20_PREV"] = h.shift(1).rolling(20, min_periods=18).max()
        d["HIGH55_PREV"] = h.shift(1).rolling(55, min_periods=45).max()
        d["RET63"] = c.pct_change(63)
        d["CLOSE_LOC"] = ((c - l) / (h - l).replace(0, np.nan)).fillna(0.5)
        d["SYMBOL"] = str(symbol)
        frames.append(d)
    cols = ["SYMBOL", "DATE", "OPEN", "HIGH", "LOW", "CLOSE", "VOL_X",
            "MOM_RANK", "CLOSE_LOC", "STRATEGY"]
    if not frames:
        return pd.DataFrame(columns=cols)
    f = pd.concat(frames, ignore_index=True)
    f["MOM_RANK"] = f.groupby("DATE")["RET63"].rank(pct=True)
    trend = (f.CLOSE > f.EMA200) & (f.EMA50 > f.EMA200)
    masks = {
        "M": ((f.MOM_RANK >= 0.85) & (f.CLOSE > f.EMA50) &
              (f.EMA50 > f.EMA200) & (f.CLOSE > f.HIGH20_PREV) &
              (f.VOL_X >= 1.1)),
        "J": (trend & (f.CLOSE > f.HIGH55_PREV) &
              (f.VOL_X >= 1.3) & (f.CLOSE_LOC >= 0.65)),
    }
    out = []
    for strategy, mask in masks.items():
        for symbol, g in f.groupby("SYMBOL", sort=False):
            valid = mask.loc[g.index].fillna(False).to_numpy()
            last_signal = None
            for i in np.flatnonzero(valid):
                row = g.iloc[i]
                date = pd.Timestamp(row.DATE)
                if last_signal is not None and (date - last_signal).days < 15:
                    continue
                last_signal = date
                out.append({
                    "SYMBOL": symbol, "STRATEGY": strategy,
                    "SIGNAL_DATE": date, "SIGNAL_CLOSE": float(row.CLOSE),
                    "VOL_X": float(row.VOL_X), "MOM_RANK": float(row.MOM_RANK),
                    "CLOSE_LOC": float(row.CLOSE_LOC),
                })
    return pd.DataFrame(out, columns=cols)


def simulate_mj_portfolio(history: pd.DataFrame, signals: pd.DataFrame,
                          strategy: str, capital: float) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    if strategy not in {"M", "J"}:
        raise ValueError("strategy must be M or J")
    d = history.copy()
    d["DATE"] = pd.to_datetime(d.DATE)
    d = d.sort_values(["DATE", "SYMBOL"])
    by_day = {day: group.set_index("SYMBOL", drop=False)
              for day, group in d.groupby("DATE", sort=True)}
    dates = sorted(by_day)
    s = signals[signals.STRATEGY.eq(strategy)].copy()
    s["SIGNAL_DATE"] = pd.to_datetime(s.SIGNAL_DATE)
    by_signal = {day: g.copy() for day, g in s.groupby("SIGNAL_DATE")}
    cash = float(capital)
    positions: dict[str, dict] = {}
    pending = pd.DataFrame()
    trades, curve = [], []
    max_ticket = capital * MAX_POSITION_PCT / 100.0

    for day in dates:
        today = by_day[day]
        # Yesterday's close signals are filled at today's OPEN.
        if not pending.empty:
            if strategy == "M":
                pending = pending.sort_values(["MOM_RANK", "VOL_X", "SYMBOL"],
                                              ascending=[False, False, True])
            else:
                pending = pending.sort_values(["CLOSE_LOC", "VOL_X", "SYMBOL"],
                                              ascending=[False, False, True])
            for _, sig in pending.iterrows():
                sym = sig.SYMBOL
                if len(positions) >= MAX_POSITIONS or sym in positions or sym not in today.index:
                    continue
                entry = float(today.loc[sym].OPEN)
                if not np.isfinite(entry) or entry <= 0:
                    continue
                budget = min(max_ticket, cash)
                qty = int(budget // entry)
                if qty < 1:
                    continue
                notional = qty * entry
                cash -= notional
                positions[sym] = {
                    "qty": qty, "entry": entry, "entry_date": day,
                    "signal_date": sig.SIGNAL_DATE, "bars": 0,
                    "vol_x": float(sig.VOL_X),
                    "mom_rank": float(sig.MOM_RANK),
                    "close_loc": float(sig.CLOSE_LOC),
                }
        # Close-based holding count: entry session is session 1; exit on session 40 close.
        for sym in list(positions):
            if sym not in today.index:
                continue
            p = positions[sym]
            p["bars"] += 1
            if p["bars"] >= HOLD_SESSIONS:
                exit_px = float(today.loc[sym].CLOSE)
                qty = p["qty"]
                gross = (exit_px - p["entry"]) * qty
                fee = p["entry"] * qty * COST_PCT / 100.0
                cash += qty * exit_px - fee
                trades.append({
                    "STRATEGY": strategy, "SYMBOL": sym,
                    "SIGNAL_DATE": p["signal_date"], "ENTRY_DATE": p["entry_date"],
                    "EXIT_DATE": day, "ENTRY": p["entry"], "EXIT": exit_px,
                    "QTY": qty, "HOLD_SESSIONS": p["bars"],
                    "GROSS_PNL": gross, "COST_RS": fee,
                    "NET_PNL": gross - fee,
                    "NET_RETURN_PCT": ((exit_px / p["entry"] - 1) * 100) - COST_PCT,
                })
                del positions[sym]
        equity = cash + sum(p["qty"] * float(today.loc[sym].CLOSE)
                            for sym, p in positions.items() if sym in today.index)
        curve.append({"DATE": day, "CASH": cash, "OPEN_POSITIONS": len(positions),
                      "EQUITY": equity})

        # Today's completed close creates next-session orders.
        pending = by_signal.get(day, pd.DataFrame()).copy()

    # No artificial early liquidation: only completed 40-session trades are counted.
    e = pd.DataFrame(curve)
    t = pd.DataFrame(trades)
    if not e.empty:
        e["PEAK"] = e.EQUITY.cummax()
        e["DRAWDOWN_PCT"] = (e.EQUITY / e.PEAK - 1) * 100
    wins = float(t.loc[t.NET_PNL > 0, "NET_PNL"].sum()) if not t.empty else 0.0
    losses = float(-t.loc[t.NET_PNL < 0, "NET_PNL"].sum()) if not t.empty else 0.0
    final = float(e.EQUITY.iloc[-1]) if not e.empty else capital
    elapsed = max(1, (pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days) if dates else 1
    daily = e.EQUITY.pct_change().dropna() if not e.empty else pd.Series(dtype=float)
    stats = {
        "strategy": strategy, "starting_capital": round(capital, 2),
        "ending_equity": round(final, 2), "net_pnl": round(final-capital, 2),
        "total_return_pct": round((final/capital-1)*100, 2) if capital else 0,
        "cagr_pct": round(((final/capital)**(365.25/elapsed)-1)*100, 2)
                    if capital and final > 0 else -100,
        "completed_trades": len(t),
        "win_rate_pct": round((t.NET_PNL > 0).mean()*100, 2) if not t.empty else 0,
        "profit_factor": round(wins/losses, 3) if losses else (float("inf") if wins else 0),
        "avg_net_trade_pct": round(float(t.NET_RETURN_PCT.mean()), 3) if not t.empty else 0,
        "max_drawdown_pct": round(float(e.DRAWDOWN_PCT.min()), 2) if not e.empty else 0,
        "daily_volatility_pct": round(float(daily.std()*np.sqrt(252)*100), 2)
                                if len(daily) > 1 else 0,
        "max_positions": MAX_POSITIONS, "max_position_pct_initial_capital": MAX_POSITION_PCT,
        "holding_sessions": HOLD_SESSIONS, "round_trip_cost_pct": COST_PCT,
    }
    if not e.empty:
        pre = e[pd.to_datetime(e.DATE) < pd.Timestamp("2025-01-01")]
        post = e[pd.to_datetime(e.DATE) >= pd.Timestamp("2025-01-01")]
        base = float(pre.EQUITY.iloc[-1]) if not pre.empty else capital
        stats["holdout_2025_plus_return_pct"] = round(
            (float(post.EQUITY.iloc[-1])/base-1)*100, 2) if not post.empty and base else 0
        holdout_trades = t[pd.to_datetime(t.SIGNAL_DATE) >= pd.Timestamp("2025-01-01")] if not t.empty else t
        stats["holdout_2025_plus_trades"] = len(holdout_trades)
        stats["holdout_2025_plus_win_rate_pct"] = round(
            (holdout_trades.NET_PNL > 0).mean()*100, 2) if not holdout_trades.empty else 0
        hw = float(holdout_trades.loc[holdout_trades.NET_PNL > 0, "NET_PNL"].sum()) if not holdout_trades.empty else 0
        hl = float(-holdout_trades.loc[holdout_trades.NET_PNL < 0, "NET_PNL"].sum()) if not holdout_trades.empty else 0
        stats["holdout_2025_plus_profit_factor"] = round(hw/hl, 3) if hl else (float("inf") if hw else 0)
    return t, e, stats


def run_mj_scenarios(history: pd.DataFrame, out_dir) -> dict:
    from pathlib import Path
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    signals = build_mj_signals(history)
    signals.to_csv(out / "mj_signals.csv", index=False)
    results = {}
    for strategy in ("M", "J"):
        results[strategy] = {}
        for capital in CAPITALS:
            trades, equity, stats = simulate_mj_portfolio(history, signals, strategy, capital)
            tag = f"{capital//1000}k"
            trades.to_csv(out / f"mj_{strategy}_trades_{tag}.csv", index=False)
            equity.to_csv(out / f"mj_{strategy}_equity_{tag}.csv", index=False)
            results[strategy][str(capital)] = stats
    results["method"] = (
        "Exact independent lab M/J entry signals, next-session OPEN entry, "
        "40th future-session CLOSE exit, 15-calendar-day per-symbol cooldown, "
        "0.35% round-trip cost. Separate disclosed portfolio overlay: shared cash, "
        "max 8 concurrent positions, max 15% of initial capital per position, "
        "integer shares. No stop loss. Incomplete 40-session trades are excluded, "
        "not prematurely liquidated. Same-day priority: M by 63-session momentum "
        "rank then volume ratio; J by close-location then volume ratio."
    )
    results["signal_counts"] = signals.groupby("STRATEGY").size().to_dict()
    return results

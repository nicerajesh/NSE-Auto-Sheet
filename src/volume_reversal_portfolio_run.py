from __future__ import annotations
import argparse
from pathlib import Path
import pandas as pd
from volume_reversal_portfolio import simulate_portfolio


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default="state/history.csv.gz")
    ap.add_argument("--events", default="artifacts/52w_volume_backtest/events.csv")
    ap.add_argument("--out", default="artifacts/52w_volume_backtest/portfolio")
    ap.add_argument("--capital", type=float, default=500000)
    ap.add_argument("--max-positions", type=int, default=10)
    ap.add_argument("--max-entries-per-day", type=int, default=3)
    args = ap.parse_args()
    hist = pd.read_csv(args.state, parse_dates=["DATE"])
    events = pd.read_csv(args.events, parse_dates=["SIGNAL_DATE"])
    summaries, curves, trades = [], [], []
    for tier in ("A_DISCOVERY", "B_ABSORPTION", "G_TREND_PULLBACK", "H_CONTRACTION_BREAKOUT", "I_RS_LEADER_BREAKOUT"):
        for horizon in (20, 40, 60):
            metrics, curve, ledger = simulate_portfolio(
                hist, events, tier, horizon, initial_capital=args.capital,
                max_positions=args.max_positions,
                max_entries_per_day=args.max_entries_per_day)
            summaries.append(metrics)
            if not curve.empty:
                curve["TIER"], curve["HORIZON"] = tier, horizon
                curves.append(curve)
            if not ledger.empty:
                trades.append(ledger)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(summaries).to_csv(out / "portfolio_summary.csv", index=False)
    (pd.concat(curves, ignore_index=True) if curves else pd.DataFrame()).to_csv(out / "equity_curves.csv", index=False)
    (pd.concat(trades, ignore_index=True) if trades else pd.DataFrame()).to_csv(out / "portfolio_trades.csv", index=False)
    print("Portfolio simulation: next-session OPEN, fixed holding-period CLOSE, 0.35% round-trip costs.")
    print("Limits: 500,000 initial capital, 10 concurrent positions, max 3 new entries/day, equal-weight sizing.")
    print(pd.DataFrame(summaries).to_string(index=False))


if __name__ == "__main__":
    main()

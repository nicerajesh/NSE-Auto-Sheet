"""Run isolated 20% delivery research; does not publish or modify production signals."""
from pathlib import Path
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import data as dt
from engine import add_features
from delivery20 import add_delivery20_signals, backtest_delivery20, summarize_delivery20
from delivery20_portfolio import run_delivery20_portfolio
from config import CFG

state = ROOT / "state"
out = ROOT / "output"
state.mkdir(exist_ok=True)
out.mkdir(exist_ok=True)
symbols = dt.fetch_universe()
hist = dt.load_history(state / "history.csv.gz", symbols)
base = add_features(hist)
research = add_delivery20_signals(base)
trades = backtest_delivery20(research, target_pct=20.0)
latest = research[research.DATE == research.DATE.max()].copy()
latest = latest[latest.D20_BUY].sort_values("MOM_RANK", ascending=False)
trades.to_csv(out / "delivery20_trades.csv", index=False)
latest.to_csv(out / "delivery20_latest_candidates.csv", index=False)
summary = summarize_delivery20(trades)
sensitivity_rows = []
for target_pct in (20.0, 30.0, 40.0):
    target_trades = trades if target_pct == 20.0 else backtest_delivery20(research, target_pct=target_pct)
    target_summary = summarize_delivery20(target_trades)
    sensitivity_rows.append({"TARGET_PCT": target_pct, **target_summary})
pd.DataFrame(sensitivity_rows).to_csv(out / "delivery20_target_sensitivity.csv", index=False)

# Cash-constrained portfolio validation: 5L capital, 0.5% equity risk/trade,
# max 10 positions, max 10% capital/stock, max 5% aggregate open risk.
portfolio_summaries, portfolio_years, portfolio_trades, portfolio_equities, portfolio_open = [], [], [], [], []
for target_pct in (20.0, 30.0, 40.0):
    p_trades, p_equity, p_yearly, p_open, p_summary = run_delivery20_portfolio(
        research, initial_capital=CFG.delivery_capital,
        risk_per_trade_pct=0.5, max_positions=10, max_position_pct=10.0,
        max_open_risk_pct=5.0, max_new_per_day=3,
        cost_pct=0.35, max_hold=120, max_gap_pct=2.0,
        target_pct=target_pct,
    )
    portfolio_summaries.append({"TARGET_PCT": target_pct, **p_summary})
    if not p_yearly.empty:
        p_yearly.insert(0, "TARGET_PCT", target_pct)
        portfolio_years.append(p_yearly)
    if not p_trades.empty:
        p_trades.insert(0, "TARGET_PCT", target_pct)
        portfolio_trades.append(p_trades)
    if not p_equity.empty:
        p_equity.insert(0, "TARGET_PCT", target_pct)
        portfolio_equities.append(p_equity)
    if not p_open.empty:
        p_open.insert(0, "TARGET_PCT", target_pct)
        portfolio_open.append(p_open)

pd.DataFrame(portfolio_summaries).to_csv(out / "delivery20_portfolio_summary.csv", index=False)
pd.concat(portfolio_years, ignore_index=True).to_csv(out / "delivery20_portfolio_yearly.csv", index=False) if portfolio_years else pd.DataFrame().to_csv(out / "delivery20_portfolio_yearly.csv", index=False)
pd.concat(portfolio_trades, ignore_index=True).to_csv(out / "delivery20_portfolio_trades.csv", index=False) if portfolio_trades else pd.DataFrame().to_csv(out / "delivery20_portfolio_trades.csv", index=False)
pd.concat(portfolio_equities, ignore_index=True).to_csv(out / "delivery20_portfolio_equity.csv", index=False) if portfolio_equities else pd.DataFrame().to_csv(out / "delivery20_portfolio_equity.csv", index=False)
pd.concat(portfolio_open, ignore_index=True).to_csv(out / "delivery20_portfolio_open_positions.csv", index=False) if portfolio_open else pd.DataFrame().to_csv(out / "delivery20_portfolio_open_positions.csv", index=False)
pd.DataFrame([{"METRIC": k, "VALUE": v} for k, v in summary.items()]).to_csv(
    out / "delivery20_summary.csv", index=False
)
closed = trades[trades.REASON != "OPEN"].copy() if not trades.empty else trades.copy()
if not closed.empty:
    closed["YEAR"] = pd.to_datetime(closed["EXIT_DATE"]).dt.year
    yearly_rows = []
    for year, group in closed.groupby("YEAR"):
        wins = group.loc[group.NET_RETURN_PCT > 0, "NET_RETURN_PCT"].sum()
        losses = -group.loc[group.NET_RETURN_PCT < 0, "NET_RETURN_PCT"].sum()
        yearly_rows.append({
            "YEAR": int(year), "TRADES": len(group),
            "WIN_RATE_PCT": round(float((group.NET_RETURN_PCT > 0).mean() * 100), 2),
            "TARGET_HIT_PCT": round(float((group.REASON == "TARGET_20").mean() * 100), 2),
            "PROFIT_FACTOR": round(float(wins / losses), 3) if losses else (float("inf") if wins else 0.0),
            "AVG_NET_RETURN_PCT": round(float(group.NET_RETURN_PCT.mean()), 3),
        })
    yearly = pd.DataFrame(yearly_rows)
else:
    yearly = pd.DataFrame(columns=["YEAR", "TRADES", "WIN_RATE_PCT", "TARGET_HIT_PCT",
                                   "PROFIT_FACTOR", "AVG_NET_RETURN_PCT"])
yearly.to_csv(out / "delivery20_yearly.csv", index=False)
print("DELIVERY20 EVENT-LEVEL SUMMARY", summary)
print("ASOF", hist.DATE.max(), "SYMBOLS", hist.SYMBOL.nunique(), "CANDIDATES", len(latest))
print("NOTE: event-level results are separate from the capital-constrained portfolio simulation.")\nprint("DELIVERY20 PORTFOLIO:", portfolio_summaries)

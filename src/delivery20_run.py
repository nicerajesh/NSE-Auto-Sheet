"""Run isolated 20% delivery research; does not publish or modify production signals."""
from pathlib import Path
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import data as dt
from engine import add_features
from delivery20 import add_delivery20_signals, backtest_delivery20, summarize_delivery20

state = ROOT / "state"
out = ROOT / "output"
state.mkdir(exist_ok=True)
out.mkdir(exist_ok=True)
symbols = dt.fetch_universe()
hist = dt.load_history(state / "history.csv.gz", symbols)
base = add_features(hist)
research = add_delivery20_signals(base)
trades = backtest_delivery20(research)
latest = research[research.DATE == research.DATE.max()].copy()
latest = latest[latest.D20_BUY].sort_values(["D20_SCORE", "MOM_RANK"], ascending=False)
trades.to_csv(out / "delivery20_trades.csv", index=False)
latest.to_csv(out / "delivery20_latest_candidates.csv", index=False)
summary = summarize_delivery20(trades)
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
            "COMPOUNDED_EVENT_RETURN_PCT": round(float(((1 + group.NET_RETURN_PCT / 100).prod() - 1) * 100), 2),
        })
    yearly = pd.DataFrame(yearly_rows)
else:
    yearly = pd.DataFrame(columns=["YEAR", "TRADES", "WIN_RATE_PCT", "TARGET_HIT_PCT",
                                   "PROFIT_FACTOR", "AVG_NET_RETURN_PCT", "COMPOUNDED_EVENT_RETURN_PCT"])
yearly.to_csv(out / "delivery20_yearly.csv", index=False)
print("DELIVERY20 EVENT-LEVEL SUMMARY", summary)
print("ASOF", hist.DATE.max(), "SYMBOLS", hist.SYMBOL.nunique(), "CANDIDATES", len(latest))
print("NOTE: event-level results; overlapping stocks are not capital-constrained portfolio returns.")

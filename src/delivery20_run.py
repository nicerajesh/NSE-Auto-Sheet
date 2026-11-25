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
pd.DataFrame([{"METRIC": k, "VALUE": v} for k, v in summarize_delivery20(trades).items()]).to_csv(
    out / "delivery20_summary.csv", index=False
)
print("DELIVERY20 SUMMARY", summarize_delivery20(trades))
print("ASOF", hist.DATE.max(), "SYMBOLS", hist.SYMBOL.nunique(), "CANDIDATES", len(latest))

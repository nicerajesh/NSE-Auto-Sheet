"""Research-only Delivery20 daily scan publisher to a separate Google Sheets tab."""
from pathlib import Path
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import data as dt
import publish as pb
from engine import add_features
from delivery20 import add_delivery20_signals
from config import CFG

STATE = ROOT / "state"
STATE.mkdir(exist_ok=True)

symbols = dt.fetch_universe()
hist = dt.load_history(STATE / "history.csv.gz", symbols)
features = add_features(hist)
signals = add_delivery20_signals(features)
asof = pd.Timestamp(signals["DATE"].max())
latest = signals[signals["DATE"] == asof].copy()
latest = latest[latest["D20_BUY"]].sort_values(
    ["MOM_RANK", "VOL_RATIO"], ascending=False
)

rows = [
    [f"RY DELIVERY20 RESEARCH | Data: {asof:%d-%b-%Y} | Research only; NOT production BUY"],
    ["Universe limitation: current universe/history is not yet fully PIT mapped; survivorship-bias audit is incomplete."],
    ["Entry: next session OPEN; skip if gap-up >2% vs signal close or open <= stop. No auto orders."],
    ["T1/T2/T3 are risk-multiple levels (2R/4R/6R). 20/30/40% are separate fixed-price target levels from signal close."],
    ["STOCK", "SIGNAL", "SIGNAL CLOSE", "NEXT OPEN ENTRY (approx)", "STOP LOSS",
     "T1 (2R)", "T2 (4R)", "T3 (6R)", "TARGET +20%", "TARGET +30%", "TARGET +40%",
     "RISK %", "MOM RANK", "VOLUME x", "ADX", "AVG TURNOVER Cr", "SETUP", "DATA DATE"]
]
for _, r in latest.iterrows():
    close = float(r["CLOSE"])
    stop = float(r["D20_STOP"])
    risk = close - stop
    rows.append([
        str(r["SYMBOL"]), "BUY (RESEARCH)", close, "Next session OPEN",
        stop, close + 2*risk, close + 4*risk, close + 6*risk,
        close*1.20, close*1.30, close*1.40,
        float(r["D20_RISK_PCT"]), float(r["MOM_RANK"]),
        float(r["VOL_RATIO"]), float(r["ADX"]), float(r["TURNOVER_CR"]),
        "55D BREAKOUT", asof.strftime("%d-%b-%Y")
    ])
if latest.empty:
    rows.append(["", "NO BUY SETUP TODAY", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""])

book = pb.open_book()
if book is None:
    raise RuntimeError("Google Sheets publish skipped: GCP_CREDENTIALS missing or invalid")
pb._write_tab(book, "DELIVERY20", rows, {"title": [0, 1, 2, 3], "header": [4]})
print(f"PUBLISHED DELIVERY20: {len(latest)} research candidates | {asof:%Y-%m-%d}")

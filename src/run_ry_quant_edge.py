"""Focused RY Quant Edge research runner (no legacy backtests, no Sheet publishing)."""
from __future__ import annotations

import os
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import data as dt
import swing_recovery as sr
import ry_quant_edge as rqe

STATE = Path(os.getenv("NSE_STATE_DIR", ROOT / "state"))
OUT = Path(os.getenv("NSE_OUTPUT_DIR", ROOT / "output"))


def main() -> int:
    STATE.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    symbols = dt.fetch_universe()
    history = dt.load_history(STATE / "history.csv.gz", symbols, offline=False)
    print(f"RY EDGE DATA | {history.SYMBOL.nunique()} symbols | {history.DATE.nunique()} sessions | {history.DATE.max()}")
    features = sr.add_swing_features(history)
    summary, trades = rqe.run_ry_quant_edge(features)
    summary.to_csv(OUT / "ry_quant_edge_summary.csv", index=False)
    trades.to_csv(OUT / "ry_quant_edge_trades.csv", index=False)
    print("RY QUANT EDGE SUMMARY")
    if not summary.empty:
        print(summary.to_string(index=False))
    print(f"RY EDGE DONE | trades={len(trades)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

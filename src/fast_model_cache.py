from __future__ import annotations

import os
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path(os.getenv("NSE_MODEL_CACHE_DIR", str(ROOT / "model_cache"))).resolve()
FAST_MODE = os.getenv("FAST_MODE", "0").strip().lower() in {"1", "true", "yes", "on"}


def _summary(name: str) -> tuple[pd.DataFrame, dict]:
    p = CACHE / name
    if not p.is_file() or p.stat().st_size == 0:
        raise FileNotFoundError(f"FAST MODEL CACHE MISSING: {p}")
    d = pd.read_csv(p)
    if d.empty:
        raise RuntimeError(f"FAST MODEL CACHE EMPTY: {p}")
    return d, d.iloc[0].to_dict()


def _trades(name: str) -> pd.DataFrame:
    p = CACHE / name
    if not p.is_file() or p.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(p)


def _cached_or(full_fn, summary_name: str, trade_name: str):
    if not FAST_MODE:
        return full_fn()
    try:
        _, stats = _summary(summary_name)
        trades = _trades(trade_name)
        print(f"FAST MODEL CACHE: reused {summary_name}")
        return trades, stats
    except Exception as exc:
        print(f"FAST MODEL CACHE WARNING: {exc}; falling back to full backtest")
        return full_fn()


def low52(full_fn):
    return _cached_or(full_fn, "low52_backtest_summary.csv", "low52_backtest_trades.csv")


def apex(full_fn):
    return _cached_or(full_fn, "apex_backtest_summary.csv", "apex_backtest_trades.csv")


def stealth(full_fn):
    return _cached_or(full_fn, "stealth_backtest_summary.csv", "stealth_backtest_trades.csv")


def main_backtest(full_fn):
    if not FAST_MODE:
        return full_fn()
    try:
        _, stats = _summary("backtest_summary.csv")
        cal_p = CACHE / "score_calibration.csv"
        cal = pd.read_csv(cal_p) if cal_p.is_file() and cal_p.stat().st_size else pd.DataFrame()
        trades = _trades("backtest_trades.csv")
        print("FAST MODEL CACHE: reused backtest_summary.csv + score_calibration.csv")
        return trades, stats, cal
    except Exception as exc:
        print(f"FAST MODEL CACHE WARNING: {exc}; falling back to full backtest")
        return full_fn()


def cached_walk_forward(full_fn, trades):
    if not FAST_MODE:
        return full_fn(trades)
    p = CACHE / "walk_forward_summary.csv"
    if p.is_file() and p.stat().st_size:
        wf = pd.read_csv(p)
        print("FAST MODEL CACHE: reused walk_forward_summary.csv")
        return wf, True, "CACHED_VALIDATION"
    return full_fn(trades)


def copy_current_to_cache(output_dir: str | Path) -> None:
    out = Path(output_dir)
    CACHE.mkdir(parents=True, exist_ok=True)
    names = [
        "backtest_summary.csv", "score_calibration.csv", "backtest_trades.csv",
        "walk_forward_summary.csv", "low52_backtest_summary.csv", "low52_backtest_trades.csv",
        "apex_backtest_summary.csv", "apex_backtest_trades.csv",
        "stealth_backtest_summary.csv", "stealth_backtest_trades.csv",
    ]
    for name in names:
        src = out / name
        if src.is_file() and src.stat().st_size:
            (CACHE / name).write_bytes(src.read_bytes())

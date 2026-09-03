from __future__ import annotations

import json
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


def _gate() -> tuple[bool, str, bool, str]:
    p = CACHE / "model_gate.json"
    if not p.is_file() or p.stat().st_size == 0:
        raise FileNotFoundError(f"FAST MODEL CACHE MISSING: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    return bool(data.get("gate_ok", False)), str(data.get("gate_reason", "CACHED_MODEL")), bool(data.get("wf_ok", False)), str(data.get("wf_reason", "CACHED_MODEL"))


def _cached_or(full_fn, summary_name: str, trade_name: str):
    if not FAST_MODE:
        return full_fn()
    try:
        _, stats = _summary(summary_name)
        trades = _trades(trade_name)
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
        return (*full_fn(), None)
    try:
        stats_df, stats = _summary("backtest_summary.csv")
        cal_p = CACHE / "score_calibration.csv"
        cal = pd.read_csv(cal_p) if cal_p.is_file() and cal_p.stat().st_size else pd.DataFrame()
        trades = _trades("backtest_trades.csv")
        gate_ok, gate_reason, wf_ok, wf_reason = _gate()
        wf_p = CACHE / "walk_forward_summary.csv"
        wf = pd.read_csv(wf_p) if wf_p.is_file() and wf_p.stat().st_size else pd.DataFrame()
        print(f"FAST MODEL CACHE: reused validation model | gate={gate_reason} | wf={wf_reason}")
        return trades, stats, cal, (wf, wf_ok, wf_reason, gate_ok, gate_reason)
    except Exception as exc:
        print(f"FAST MODEL CACHE WARNING: {exc}; falling back to full backtest")
        trades, stats, cal = full_fn()
        return trades, stats, cal, None


def cached_walk_forward(full_fn, trades):
    if not FAST_MODE:
        return full_fn(trades)
    try:
        p = CACHE / "walk_forward_summary.csv"
        wf = pd.read_csv(p) if p.is_file() and p.stat().st_size else pd.DataFrame()
        _, _, wf_ok, wf_reason = _gate()
        return wf, wf_ok, wf_reason
    except Exception as exc:
        print(f"FAST MODEL CACHE WARNING: walk-forward cache unavailable: {exc}; using current trades")
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


def write_gate(output_dir: str | Path) -> None:
    out = Path(output_dir)
    gate = os.getenv("MODEL_GATE_OK", "0").strip().lower() in {"1", "true", "yes", "on"}
    reason = os.getenv("MODEL_GATE_REASON", "UNKNOWN")
    wf_ok = os.getenv("MODEL_WF_OK", "0").strip().lower() in {"1", "true", "yes", "on"}
    wf_reason = os.getenv("MODEL_WF_REASON", "UNKNOWN")
    (CACHE / "model_gate.json").write_text(json.dumps({"gate_ok": gate, "gate_reason": reason, "wf_ok": wf_ok, "wf_reason": wf_reason}, indent=2), encoding="utf-8")

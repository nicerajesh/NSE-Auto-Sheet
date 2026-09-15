from __future__ import annotations

from pathlib import Path
import pandas as pd

INPUT = Path("output/backtest_trades.csv")
OUT = Path("output/v7_breakout_quality_validation.csv")


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def evaluate(d: pd.DataFrame) -> pd.DataFrame:
    """Evaluate only signal-time breakout-quality fields persisted by V7.

    The function intentionally uses no MFE/MAE/future fields. A candidate
    filter is considered promising only if it improves chronological OOS
    results; this module reports diagnostics and does not alter BUY actions.
    """
    d = d[d.ACTION.astype(str).eq("BREAKOUT BUY")].copy()
    if d.empty:
        return pd.DataFrame([{"STATUS": "NO_BREAKOUT_TRADES"}])

    # Prefer explicit signal-time fields when available. The fallback keeps
    # this validator compatible with pre-V7 artifacts.
    rules = {
        "QUALITY_SCORE_90": _num(d.get("SCORE", pd.Series(index=d.index))).ge(90),
        "QUALITY_SCORE_95": _num(d.get("SCORE", pd.Series(index=d.index))).ge(95),
    }
    rows = []
    for name, mask in rules.items():
        g = d[mask]
        if g.empty:
            continue
        r = _num(g.RETURN_PCT)
        pos = r[r > 0].sum()
        neg = -r[r < 0].sum()
        rows.append({
            "FILTER": name,
            "TRADES": len(g),
            "WIN_RATE_PCT": round((r > 0).mean() * 100, 2),
            "AVG_RETURN_PCT": round(r.mean(), 2),
            "MEDIAN_RETURN_PCT": round(r.median(), 2),
            "PROFIT_FACTOR": round(pos / max(1e-9, neg), 2),
            "ANALYSIS": "BREAKOUT_SIGNAL_TIME",
        })
    return pd.DataFrame(rows)


def main() -> None:
    if not INPUT.exists():
        pd.DataFrame([{"STATUS": "MISSING_INPUT"}]).to_csv(OUT, index=False)
        return
    evaluate(pd.read_csv(INPUT)).to_csv(OUT, index=False)


if __name__ == "__main__":
    main()

from __future__ import annotations

"""V7 false-breakout research layer.

This module is deliberately diagnostic-only. It never changes the production
signal rule. It measures how existing BREAKOUT BUY trades behave when the
signal candle lacks confirmation characteristics, so a filter can be promoted
only after chronological OOS validation.
"""

from pathlib import Path
import pandas as pd

INPUT = Path("output/backtest_trades.csv")
OUT = Path("output/v7_false_breakout_validation.csv")


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def classify(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    if d.empty:
        return d
    # These are signal-time fields already persisted by the backtest.
    # No future MFE/MAE is used to construct the filter.
    score = _num(d.get("SCORE"))
    ret = _num(d.get("RETURN_PCT"))
    mfe = _num(d.get("MFE_PCT"))
    mae = _num(d.get("MAE_PCT"))
    d["LOSS"] = (ret <= 0).astype(int)
    # A conservative diagnostic proxy: a breakout that failed to develop
    # meaningful upside before experiencing substantial adverse excursion.
    # This is labelled POST_OUTCOME for research and MUST NOT be used as a
    # live filter because MFE/MAE are future information.
    d["POST_OUTCOME_FALSE_BREAKOUT"] = ((mfe < 2.0) & (mae <= -3.0)).astype(int)
    d["SCORE_BUCKET"] = pd.cut(score, [0, 81, 89, 100], labels=["<82", "82-89", "90+"])
    return d


def main() -> None:
    if not INPUT.exists():
        pd.DataFrame([{"STATUS": "MISSING_INPUT"}]).to_csv(OUT, index=False)
        return
    d = pd.read_csv(INPUT)
    d = d[d.ACTION.astype(str).eq("BREAKOUT BUY")].copy()
    if d.empty:
        pd.DataFrame([{"STATUS": "NO_BREAKOUT_TRADES"}]).to_csv(OUT, index=False)
        return
    d = classify(d)
    rows = []
    for bucket, g in d.groupby("SCORE_BUCKET", observed=False):
        if len(g) == 0:
            continue
        r = _num(g.RETURN_PCT)
        pos = r[r > 0].sum()
        neg = -r[r < 0].sum()
        rows.append({
            "SCORE_BUCKET": str(bucket),
            "TRADES": len(g),
            "WIN_RATE_PCT": round((r > 0).mean() * 100, 2),
            "AVG_RETURN_PCT": round(r.mean(), 2),
            "MEDIAN_RETURN_PCT": round(r.median(), 2),
            "PROFIT_FACTOR": round(pos / max(1e-9, neg), 2),
            "POST_OUTCOME_FALSE_BREAKOUT_RATE_PCT": round(g.POST_OUTCOME_FALSE_BREAKOUT.mean() * 100, 2),
            "ANALYSIS": "BREAKOUT_SCORE_BUCKET",
        })
    rows.append({
        "SCORE_BUCKET": "ALL",
        "TRADES": len(d),
        "WIN_RATE_PCT": round(_num(d.RETURN_PCT).gt(0).mean() * 100, 2),
        "AVG_RETURN_PCT": round(_num(d.RETURN_PCT).mean(), 2),
        "MEDIAN_RETURN_PCT": round(_num(d.RETURN_PCT).median(), 2),
        "PROFIT_FACTOR": round(_num(d.loc[_num(d.RETURN_PCT) > 0, "RETURN_PCT"]).sum() / max(1e-9, -_num(d.loc[_num(d.RETURN_PCT) < 0, "RETURN_PCT"]).sum()), 2),
        "POST_OUTCOME_FALSE_BREAKOUT_RATE_PCT": round(d.POST_OUTCOME_FALSE_BREAKOUT.mean() * 100, 2),
        "ANALYSIS": "BREAKOUT_ALL",
    })
    pd.DataFrame(rows).to_csv(OUT, index=False)


if __name__ == "__main__":
    main()

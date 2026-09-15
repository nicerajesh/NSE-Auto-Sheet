from __future__ import annotations

from pathlib import Path
import pandas as pd


def _pf(s: pd.Series) -> float:
    s = pd.to_numeric(s, errors="coerce").dropna()
    pos = s[s > 0].sum()
    neg = -s[s < 0].sum()
    return round(float(pos / max(1e-9, neg)), 4)


def validate(path: str | Path = "output/low52_backtest_trades.csv") -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        return pd.DataFrame([{"STATUS": "MISSING_BACKTEST"}])
    d = pd.read_csv(p)
    d["SIGNAL_DATE"] = pd.to_datetime(d["SIGNAL_DATE"], errors="coerce")
    d["RETURN_PCT"] = pd.to_numeric(d["RETURN_PCT"], errors="coerce")
    d["SCORE"] = pd.to_numeric(d["SCORE"], errors="coerce")
    d = d.dropna(subset=["SIGNAL_DATE", "RETURN_PCT", "SCORE"])
    buys = d[d.ACTION.eq("EARLY REVERSAL BUY")].copy()
    rows = []
    for label, lo, hi in [("CURRENT_75_PLUS", 75, 1000), ("V6_75_84", 75, 84.999), ("V6_75_80", 75, 80.999)]:
        x = buys[buys.SCORE.between(lo, hi)].sort_values("SIGNAL_DATE")
        cut = x.SIGNAL_DATE.quantile(0.60) if len(x) >= 5 else pd.Timestamp.max
        oos = x[x.SIGNAL_DATE >= cut]
        rows.append({
            "BAND": label,
            "TRADES": len(x),
            "PF": _pf(x.RETURN_PCT),
            "AVG_RETURN": round(float(x.RETURN_PCT.mean()), 4) if len(x) else 0.0,
            "WIN_RATE": round(float((x.RETURN_PCT > 0).mean() * 100), 2) if len(x) else 0.0,
            "OOS_TRADES": len(oos),
            "OOS_PF": _pf(oos.RETURN_PCT),
            "OOS_AVG_RETURN": round(float(oos.RETURN_PCT.mean()), 4) if len(oos) else 0.0,
            "OOS_WIN_RATE": round(float((oos.RETURN_PCT > 0).mean() * 100), 2) if len(oos) else 0.0,
        })
    return pd.DataFrame(rows)


def main() -> None:
    Path("output").mkdir(parents=True, exist_ok=True)
    out = validate()
    out.to_csv("output/low52_v6_score_validation.csv", index=False)
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()

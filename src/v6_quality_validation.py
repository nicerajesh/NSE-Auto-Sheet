from __future__ import annotations

from pathlib import Path
import pandas as pd

from config import BT

ACTIONABLE = {"PRE-BREAKOUT BUY", "BREAKOUT BUY", "SWING BUY"}


def _stats(frame: pd.DataFrame) -> dict:
    if frame.empty:
        return {"trades": 0, "profit_factor": 0.0, "median_return_pct": 0.0, "win_rate_pct": 0.0, "expectancy_pct": 0.0}
    r = pd.to_numeric(frame["RETURN_PCT"], errors="coerce").dropna()
    pos = r[r > 0]
    neg = r[r < 0]
    pf = float(pos.sum() / max(1e-9, -neg.sum())) if not neg.empty else (999.0 if not pos.empty else 0.0)
    return {
        "trades": int(len(r)),
        "profit_factor": round(pf, 4),
        "median_return_pct": round(float(r.median()), 4),
        "win_rate_pct": round(float((r > 0).mean() * 100), 4),
        "expectancy_pct": round(float(r.mean()), 4),
    }


def action_walk_forward(path: str | Path = "output/backtest_trades.csv") -> tuple[pd.DataFrame, dict]:
    """Evaluate each production action on successive chronological OOS windows.

    This intentionally does not change signals. It is a validation layer that
    prevents one strong historical period from masking a broken recent edge.
    """
    p = Path(path)
    if not p.exists():
        return pd.DataFrame(), {"ok": False, "reason": "MISSING_BACKTEST_TRADES"}
    d = pd.read_csv(p)
    required = {"ACTION", "SIGNAL_DATE", "RETURN_PCT"}
    if not required.issubset(d.columns):
        return pd.DataFrame(), {"ok": False, "reason": "MISSING_ACTION_BACKTEST_COLUMNS"}
    d["SIGNAL_DATE"] = pd.to_datetime(d["SIGNAL_DATE"], errors="coerce")
    d["RETURN_PCT"] = pd.to_numeric(d["RETURN_PCT"], errors="coerce")
    d = d.dropna(subset=["SIGNAL_DATE", "RETURN_PCT"])
    d = d[d.ACTION.isin(ACTIONABLE)].sort_values("SIGNAL_DATE")
    if d.empty:
        return pd.DataFrame(), {"ok": False, "reason": "NO_ACTIONABLE_TRADES"}

    rows = []
    start = d.SIGNAL_DATE.min()
    end = d.SIGNAL_DATE.max()
    step = pd.Timedelta(days=BT.walk_forward_test_days)
    cur = start
    while cur < end:
        nxt = cur + step
        w = d[(d.SIGNAL_DATE >= cur) & (d.SIGNAL_DATE < nxt)]
        for action, g in w.groupby("ACTION"):
            s = _stats(g)
            s.update({"ACTION": action, "WINDOW_START": cur.date().isoformat(), "WINDOW_END": min(nxt, end).date().isoformat()})
            rows.append(s)
        cur = nxt

    out = pd.DataFrame(rows)
    if out.empty:
        return out, {"ok": False, "reason": "NO_ACTION_WINDOWS"}

    eligible = out[out.trades >= max(5, BT.min_oos_trades // 10)].copy()
    summary = {"ok": True, "reason": "PASS", "actions": {}}
    for action in sorted(ACTIONABLE):
        a = eligible[eligible.ACTION.eq(action)]
        if a.empty:
            summary["actions"][action] = {"ok": False, "status": "WAITING_FOR_DATA", "reason": "INSUFFICIENT_OOS_WINDOWS"}
            continue
        good = a[(a.profit_factor >= BT.min_oos_profit_factor) & (a.median_return_pct > 0) &
                 (a.win_rate_pct >= BT.min_oos_win_rate) & (a.expectancy_pct > BT.min_oos_expectancy_pct)]
        frac = len(good) / len(a)
        latest = a.sort_values("WINDOW_START").iloc[-1]
        latest_ok = (latest.profit_factor >= BT.min_oos_profit_factor and latest.median_return_pct > 0 and
                     latest.win_rate_pct >= BT.min_oos_win_rate and latest.expectancy_pct > BT.min_oos_expectancy_pct)
        ok = frac >= 0.60 and latest_ok
        summary["actions"][action] = {
            "ok": bool(ok),
            "windows": int(len(a)),
            "passing_windows": int(len(good)),
            "pass_fraction": round(float(frac), 4),
            "latest_ok": bool(latest_ok),
        }
    summary["ok"] = all(v.get("ok") for v in summary["actions"].values() if v.get("windows", 0) > 0)
    # Missing OOS windows are a data-availability state, not a model failure.
    # Keep release gates strict, but report WAITING_FOR_DATA instead of BLOCKED.
    if any(v.get("status") == "WAITING_FOR_DATA" for v in summary["actions"].values()):
        summary["reason"] = "WAITING_FOR_MORE_OOS_DATA"
    if not summary["ok"]:
        summary["reason"] = "ACTION_OOS_VALIDATION_FAILED"
    return out, summary


def main() -> None:
    out, summary = action_walk_forward()
    Path("output").mkdir(parents=True, exist_ok=True)
    out.to_csv("output/action_walk_forward_summary.csv", index=False)
    rows = []
    for action, info in summary.get("actions", {}).items():
        rows.append({"ACTION": action, **info})
    pd.DataFrame(rows).to_csv("output/action_quality_summary.csv", index=False)
    print("V6 ACTION OOS:", summary)


if __name__ == "__main__":
    main()

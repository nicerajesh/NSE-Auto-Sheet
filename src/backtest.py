"""Deep backtest - live engine ke exact same signal + exit functions par chalta hai.

Sirf CLOSED trades count hote hain (jo abhi khule hain wo live ledger ka hissa hain).
Universe = aaj ka Nifty 500 -> survivorship bias hai; numbers thode zyada achhe dikhte hain.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import CFG
from engine import simulate_staircase, trade_return


def run_backtest(f: pd.DataFrame, start: str = "2019-01-01") -> pd.DataFrame:
    rows = []
    start_np = np.datetime64(start)
    for sym, d in f.groupby("SYMBOL", sort=False):
        d = d.reset_index(drop=True)
        dates = d["DATE"].values
        sig = (
            d["SIGNAL"].values
            & (d["TURNOVER_CR"].values >= CFG.min_turnover_cr)
            & (d["JUMP_RECENT"].values == 0)
            & (dates >= start_np)
            & np.isfinite(d["ATR"].values)
        )
        if not sig.any():
            continue
        o, h, l, c = (d[x].values.astype(float) for x in ("OPEN", "HIGH", "LOW", "CLOSE"))
        atr, jump, setup = d["ATR"].values, d["JUMP"].values, d["SETUP"].values
        last = -999
        for i in np.flatnonzero(sig):
            if i - last < CFG.signal_gap or i + 1 >= len(d):
                continue
            stop0 = c[i] - CFG.stop_atr * atr[i]
            risk_pct = (c[i] - stop0) / c[i] * 100
            if not (CFG.min_risk_pct <= risk_pct <= CFG.max_risk_pct):
                continue
            sim = simulate_staircase(o, h, l, c, i + 1, stop0, signal_close=c[i])
            if sim is None or not sim["closed"]:
                continue
            if jump[i + 1: sim["exit_idx"] + 1].any():
                continue
            ret, r_mult = trade_return(sim)
            rows.append(dict(SYMBOL=sym, SIGNAL_DATE=dates[i], ENTRY_DATE=dates[i + 1],
                             EXIT_DATE=dates[sim["exit_idx"]], SETUP=setup[i], FILL=sim["fill"],
                             STOP=stop0, RET_PCT=ret, R=r_mult, HOLD=sim["exit_idx"] - i,
                             REASON=sim["reason"]))
            last = i
    t = pd.DataFrame(rows)
    for c_ in ("SIGNAL_DATE", "ENTRY_DATE", "EXIT_DATE"):
        if c_ in t:
            t[c_] = pd.to_datetime(t[c_])
    return t


def summarize(t: pd.DataFrame) -> dict:
    if t is None or t.empty:
        return dict(trades=0, win_pct=np.nan, avg_r=np.nan, avg_ret=np.nan, median_ret=np.nan, pf=np.nan, max_loss_streak=0)
    win = t[t.RET_PCT > 0].RET_PCT.sum()
    loss = -t[t.RET_PCT < 0].RET_PCT.sum()
    seq = (t.sort_values("EXIT_DATE").RET_PCT <= 0).astype(int).values
    streak = best = 0
    for x in seq:
        streak = streak + 1 if x else 0
        best = max(best, streak)
    return dict(trades=len(t), win_pct=round((t.RET_PCT > 0).mean() * 100, 1), avg_r=round(t.R.mean(), 3),
                avg_ret=round(t.RET_PCT.mean(), 2), median_ret=round(t.RET_PCT.median(), 2),
                pf=round(win / loss, 2) if loss > 0 else np.inf, max_loss_streak=int(best))


def by_year(t: pd.DataFrame) -> pd.DataFrame:
    if t is None or t.empty:
        return pd.DataFrame()
    x = t.assign(YEAR=t.EXIT_DATE.dt.year)
    return pd.DataFrame([{"YEAR": y, **summarize(g)} for y, g in x.groupby("YEAR")])


def health(t: pd.DataFrame, asof: pd.Timestamp) -> dict:
    """Recent closed-trade expectancy. avg R <= 0 -> size throttle (signal band nahi, size kam)."""
    if t is None or t.empty:
        return dict(mult=1.0, n=0, avg_r=np.nan, label="NA (kam data)")
    w = t[(t.EXIT_DATE < asof) & (t.EXIT_DATE >= asof - pd.Timedelta(days=CFG.health_window_days))]
    if len(w) < CFG.health_min_trades:
        return dict(mult=1.0, n=len(w), avg_r=np.nan, label="NA (kam trades)")
    avg_r = float(w.R.mean())
    if avg_r > 0:
        return dict(mult=1.0, n=len(w), avg_r=round(avg_r, 3), label="HEALTHY - full size")
    return dict(mult=CFG.health_size_mult, n=len(w), avg_r=round(avg_r, 3), label="WEAK REGIME - half size")


def split_summary(t: pd.DataFrame, split: str | None = None) -> tuple[dict, dict]:
    """(in-sample, out-of-sample) summary. Split date se pehle exit hue trades = in-sample."""
    split = pd.Timestamp(split or CFG.oos_start)
    if t is None or t.empty:
        return summarize(None), summarize(None)
    return summarize(t[t.EXIT_DATE < split]), summarize(t[t.EXIT_DATE >= split])



def forecast_profiles(t: pd.DataFrame, asof: pd.Timestamp) -> dict:
    """Historical context for today's signal; descriptive only, never a promised forecast.
    Uses completed, out-of-sample trades since 2023 grouped by the same setup.
    """
    result = {}
    if t is None or t.empty:
        return result
    x = t.copy()
    x["SIGNAL_DATE"] = pd.to_datetime(x["SIGNAL_DATE"])
    x["EXIT_DATE"] = pd.to_datetime(x["EXIT_DATE"])
    x = x[(x["SIGNAL_DATE"] >= pd.Timestamp("2023-01-01")) & (x["EXIT_DATE"] < pd.Timestamp(asof))]
    for setup, g in x.groupby("SETUP"):
        recent = g[g["SIGNAL_DATE"] >= pd.Timestamp("2025-01-01")]
        result[str(setup)] = {
            "sample": int(len(g)),
            "win_pct": round(float((g["RET_PCT"] > 0).mean()) * 100, 1),
            "avg_ret_pct": round(float(g["RET_PCT"].mean()), 2),
            "median_hold_sessions": round(float(g["HOLD"].median()), 1),
            "recent_sample": int(len(recent)),
            "recent_avg_ret_pct": round(float(recent["RET_PCT"].mean()), 2) if len(recent) else np.nan,
        }
    return result


def edge_gate(t: pd.DataFrame) -> tuple[bool, str]:
    s = summarize(t)
    if s["trades"] < CFG.edge_min_trades:
        return False, f"INSUFFICIENT HISTORY ({s['trades']} trades < {CFG.edge_min_trades})"
    if not (s["pf"] >= CFG.edge_min_pf):
        return False, f"NO EDGE (profit factor {s['pf']} < {CFG.edge_min_pf})"
    # walk-forward: parameters in-sample par chune gaye the, isliye gate sirf poore-sample PF par nahi - OOS par bhi
    if "EXIT_DATE" in t:
        _, oos = split_summary(t)
        if oos["trades"] >= CFG.oos_min_trades and not (oos["pf"] >= CFG.oos_min_pf):
            return False, f"NO EDGE OUT-OF-SAMPLE (PF {oos['pf']} since {CFG.oos_start}, {oos['trades']} trades)"
    return True, "PASS"

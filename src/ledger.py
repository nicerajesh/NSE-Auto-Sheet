"""Live signal ledger = "paper trading" record of har published BUY.

Isse do kaam hote hain:
  1. OPEN SIGNALS: har din pata chalta hai SL kahan raise karna hai / kab exit.
  2. LIVE SCOREBOARD: backtest jo bhi kahe, asli published signals ka result yahan dikhta hai.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from config import CFG
from engine import simulate_staircase, trade_return

LEDGER_COLS = ["SYMBOL", "SIGNAL_DATE", "SETUP", "SIGNAL_CLOSE", "STOP0", "T1", "T2", "T3",
               "STATUS", "FILL", "FILL_DATE", "STOP_NOW", "LAST_CLOSE", "LAST_DATE", "HI_R",
               "EXIT_DATE", "EXIT_PX", "RET_PCT", "R", "REASON"]


def load(path: Path) -> pd.DataFrame:
    if not Path(path).exists() or Path(path).stat().st_size == 0:
        return pd.DataFrame(columns=LEDGER_COLS)
    d = pd.read_csv(path, parse_dates=["SIGNAL_DATE", "FILL_DATE", "LAST_DATE", "EXIT_DATE"])
    for c in LEDGER_COLS:
        if c not in d:
            d[c] = np.nan
    return d[LEDGER_COLS]


def save(d: pd.DataFrame, path: Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    d.to_csv(path, index=False)


def add_signals(led: pd.DataFrame, buy: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    """Aaj ke naye BUY signals ko ledger me daalo (duplicate / 10-session cooldown skip)."""
    if buy is None or buy.empty:
        return led
    rows = []
    for _, r in buy.iterrows():
        prev = led[led.SYMBOL == r["SYMBOL"]]
        if not prev.empty:
            gap = (asof - pd.to_datetime(prev.SIGNAL_DATE).max()).days
            if gap < CFG.signal_gap * 1.4:  # ~10 sessions
                continue
        rows.append({"SYMBOL": r["SYMBOL"], "SIGNAL_DATE": asof, "SETUP": r["SETUP"], "SIGNAL_CLOSE": r["CLOSE"],
                     "STOP0": r["STOP"], "T1": r["T1"], "T2": r["T2"], "T3": r["T3"], "STATUS": "PENDING"})
    if not rows:
        return led
    new = pd.DataFrame(rows).reindex(columns=LEDGER_COLS)
    return new if led.empty else pd.concat([led, new], ignore_index=True)


def update(led: pd.DataFrame, f: pd.DataFrame) -> pd.DataFrame:
    """Har non-closed entry ko latest bars tak simulate karo."""
    if led.empty:
        return led
    led = led.copy().astype(object)   # pandas 3: float column me Timestamp assign nahi hota
    bars = {s: g.sort_values("DATE").reset_index(drop=True) for s, g in f.groupby("SYMBOL")}
    for i, r in led.iterrows():
        if r["STATUS"] in ("CLOSED", "SKIPPED"):
            continue
        g = bars.get(r["SYMBOL"])
        if g is None:
            continue
        after = g[g.DATE > pd.Timestamp(r["SIGNAL_DATE"])]
        if after.empty:
            led.at[i, "STATUS"] = "PENDING"
            continue
        # entry bar = signal ke baad pehla session
        pos0 = after.index[0]
        o, h, l, c = (g[x].values.astype(float) for x in ("OPEN", "HIGH", "LOW", "CLOSE"))
        sim = simulate_staircase(o, h, l, c, pos0, float(r["STOP0"]), signal_close=float(r["SIGNAL_CLOSE"]))
        if sim is None:
            led.at[i, "STATUS"] = "SKIPPED"      # gap-up ya SL ke neeche khula
            led.at[i, "REASON"] = "GAP SKIP"
            continue
        led.at[i, "FILL"] = sim["fill"]
        led.at[i, "FILL_DATE"] = g.DATE.iloc[pos0]
        led.at[i, "STOP_NOW"] = sim["stop_now"]
        led.at[i, "LAST_CLOSE"] = float(c[-1])
        led.at[i, "LAST_DATE"] = g.DATE.iloc[-1]
        led.at[i, "HI_R"] = round(sim["hi_r"], 2)
        if sim["closed"]:
            ret, rm = trade_return(sim)
            led.at[i, "STATUS"] = "CLOSED"
            led.at[i, "EXIT_DATE"] = g.DATE.iloc[sim["exit_idx"]]
            led.at[i, "EXIT_PX"] = sim["exit_px"]
            led.at[i, "RET_PCT"] = round(ret, 2)
            led.at[i, "R"] = round(rm, 3)
            led.at[i, "REASON"] = sim["reason"]
        else:
            led.at[i, "STATUS"] = "ACTIVE"
    return led


def open_table(led: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    """User ke liye: kaunsa position hold / SL raise / exit."""
    rows = []
    if led.empty:
        return pd.DataFrame()
    for _, r in led.iterrows():
        if r["STATUS"] == "PENDING":
            rows.append({"STOCK": r["SYMBOL"], "STATE": "PENDING ENTRY", "SIGNAL DATE": r["SIGNAL_DATE"],
                         "ENTRY": r["SIGNAL_CLOSE"], "CURRENT SL": r["STOP0"], "LAST CLOSE": "",
                         "R SO FAR": "", "ACTION": "Agle open par kharido (signal close se 2% upar khule to skip)"})
        elif r["STATUS"] == "ACTIVE":
            risk = r["FILL"] - r["STOP0"]
            now_r = (r["LAST_CLOSE"] - r["FILL"]) / risk if risk else np.nan
            raised = r["STOP_NOW"] > r["STOP0"] + 1e-9
            act = f"SL raise karke {r['STOP_NOW']:.2f} karo" if raised else f"HOLD, SL {r['STOP_NOW']:.2f}"
            rows.append({"STOCK": r["SYMBOL"], "STATE": "ACTIVE", "SIGNAL DATE": r["SIGNAL_DATE"],
                         "ENTRY": r["FILL"], "CURRENT SL": r["STOP_NOW"], "LAST CLOSE": r["LAST_CLOSE"],
                         "R SO FAR": round(now_r, 2), "ACTION": act})
        elif r["STATUS"] == "CLOSED" and pd.notna(r["EXIT_DATE"]) and (asof - r["EXIT_DATE"]).days <= 5:
            rows.append({"STOCK": r["SYMBOL"], "STATE": "EXITED", "SIGNAL DATE": r["SIGNAL_DATE"],
                         "ENTRY": r["FILL"], "CURRENT SL": r["STOP_NOW"], "LAST CLOSE": r["EXIT_PX"],
                         "R SO FAR": r["R"], "ACTION": f"EXIT ({r['REASON']}) {pd.Timestamp(r['EXIT_DATE']):%d-%b}"})
    return pd.DataFrame(rows)


def scoreboard(led: pd.DataFrame) -> dict:
    c = led[led.STATUS == "CLOSED"] if not led.empty else led
    if c is None or c.empty:
        return dict(closed=0, active=int((led.STATUS.isin(["ACTIVE", "PENDING"])).sum()) if not led.empty else 0,
                    win_pct=np.nan, avg_r=np.nan, pf=np.nan)
    ret = pd.to_numeric(c.RET_PCT)
    loss = -ret[ret < 0].sum()
    return dict(closed=len(c), active=int(led.STATUS.isin(["ACTIVE", "PENDING"]).sum()),
                win_pct=round((ret > 0).mean() * 100, 1), avg_r=round(pd.to_numeric(c.R).mean(), 3),
                pf=round(ret[ret > 0].sum() / loss, 2) if loss > 0 else np.inf)

"""INTRADAY engine: 5-min Opening Range Breakout + VWAP + volume + index bias.

Sab kuch PURE functions hain (broker/network se alag) - isliye wahi code
  * live scan (intraday_run.py),
  * backtest (intraday_run.py --backtest),
  * tests
teeno me chalta hai. "Backtest alag, live alag" wali problem nahi.

STATELESS REPLAY: har run din ke saare *completed* bars se signals dobara nikalta hai.
Signal sirf us bar tak ke data se bana hota hai (no look-ahead), isliye roz ke 10 baar run karne par
bhi wahi signals aate hain - state file ya cache ki zaroorat nahi.

Rules (config.py):
  setup  : pehle 15 min (3 bars) ki range = OR. Uske baad pehla 5-min bar jo OR high (long) / OR low (short)
           buffer ke saath close kare, VWAP ke sahi taraf ho, volume >= 1.5x din ke avg bar volume, bar ka rang
           candle direction me ho, prev-close ke sahi taraf ho, aur NIFTY din ke open ke sahi taraf ho.
  window : 09:30 - 11:30 (iske baad naya signal nahi)
  stop   : OR ki doosri taraf, par 0.4% - 1.0% ke beech clip
  exit   : T1=1R (SL -> entry), T2=2R (SL -> T1), T3=3R (poora exit), nahi to 15:15 square-off
  fill   : signal bar ke NEXT bar ka open (bar-close par order lagana = realistic)
  size   : risk = capital x 0.25%, leverage cap 3x, din me max 3 trades
Ye backtest kiye bina live paisa lagane layak NAHI hai - pehle `--backtest` chalao.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from config import CFG

DEFAULT_UNIVERSE = (
    "RELIANCE HDFCBANK ICICIBANK SBIN INFY TCS AXISBANK KOTAKBANK LT ITC BHARTIARTL TATASTEEL JSWSTEEL HINDALCO "
    "ADANIENT ADANIPORTS BAJFINANCE BAJAJFINSV M&M MARUTI SUNPHARMA DRREDDY CIPLA HCLTECH WIPRO TECHM ONGC NTPC "
    "POWERGRID COALINDIA BPCL IOC GRASIM ULTRACEMCO TITAN EICHERMOT INDUSINDBK SBILIFE HDFCLIFE TRENT BEL HAL PFC "
    "RECLTD CANBK BANKBARODA PNB DLF INDIGO VEDL GAIL"
).split()


def _hhmm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _mins(ts: pd.Series | pd.DatetimeIndex) -> np.ndarray:
    ts = pd.DatetimeIndex(ts)
    return (ts.hour * 60 + ts.minute).to_numpy()


def clean_day(df: pd.DataFrame) -> pd.DataFrame:
    """Columns: TS (bar START time, naive IST), OPEN HIGH LOW CLOSE VOLUME. Sort + duplicate hatao."""
    d = df.copy()
    d["TS"] = pd.to_datetime(d["TS"])
    d = d.sort_values("TS").drop_duplicates("TS", keep="last").reset_index(drop=True)
    return d.dropna(subset=["OPEN", "HIGH", "LOW", "CLOSE"])


def completed_only(df: pd.DataFrame, now: pd.Timestamp | None) -> pd.DataFrame:
    """Abhi ban rahe (adhoore) bar ko hatao: bar tabhi complete jab start + bar_minutes <= now."""
    if now is None or df.empty:
        return df
    end = df["TS"] + pd.Timedelta(minutes=CFG.intraday_bar_minutes)
    return df[end <= now].reset_index(drop=True)


def add_vwap(d: pd.DataFrame) -> pd.DataFrame:
    tp = (d["HIGH"] + d["LOW"] + d["CLOSE"]) / 3
    pv = (tp * d["VOLUME"]).cumsum()
    vv = d["VOLUME"].cumsum().replace(0, np.nan)
    d = d.copy()
    d["VWAP"] = pv / vv
    return d


def index_bias_at(nifty_day: pd.DataFrame | None, ts_end: pd.Timestamp) -> int:
    """+1: NIFTY din ke open se upar, -1: neeche, 0: pata nahi / flat. Sirf ts_end tak ka data."""
    if nifty_day is None or nifty_day.empty:
        return 0
    n = nifty_day[nifty_day["TS"] + pd.Timedelta(minutes=CFG.intraday_bar_minutes) <= ts_end]
    if n.empty:
        return 0
    o, c = float(n["OPEN"].iloc[0]), float(n["CLOSE"].iloc[-1])
    return 1 if c > o else -1 if c < o else 0


@dataclass
class Signal:
    symbol: str
    side: str            # "LONG" / "SHORT"
    bar_idx: int         # signal bar ka index (day df me)
    ts: pd.Timestamp     # signal bar ka END time (jab signal pata chala)
    close: float
    stop: float
    risk: float
    t1: float
    t2: float
    t3: float
    or_high: float
    or_low: float
    vol_ratio: float
    vwap: float
    index_bias: int


def build_signal(symbol: str, day: pd.DataFrame, prev_close: float | None, nifty_day: pd.DataFrame | None = None,
                 require_index: bool = True) -> Signal | None:
    """Ek symbol ke ek din ka PEHLA valid signal (long ya short). day: completed bars only."""
    d = clean_day(day)
    bm = CFG.intraday_bar_minutes
    n_or = CFG.intraday_orb_minutes // bm
    if len(d) <= n_or:
        return None
    mins = _mins(d["TS"])
    if mins[0] != 9 * 60 + 15:                     # din ka pehla bar 09:15 ka hona chahiye (partial data reject)
        return None
    orb = d.iloc[:n_or]
    if len(orb) < n_or or (mins[:n_or] != 555 + bm * np.arange(n_or)).any():
        return None
    or_high, or_low = float(orb["HIGH"].max()), float(orb["LOW"].min())
    mid = (or_high + or_low) / 2
    or_pct = (or_high - or_low) / mid * 100
    if not (CFG.intraday_min_or_pct <= or_pct <= CFG.intraday_max_or_pct) or mid < CFG.intraday_min_price:
        return None
    d = add_vwap(d)
    cutoff = _hhmm(CFG.intraday_entry_cutoff)
    buf = CFG.intraday_breakout_buf_pct / 100
    for i in range(n_or, len(d)):
        end_min = mins[i] + bm
        if end_min > cutoff:
            break
        r = d.iloc[i]
        prior_vol = d["VOLUME"].iloc[:i].mean()
        vr = float(r["VOLUME"] / prior_vol) if prior_vol and prior_vol > 0 else 0.0
        if vr < CFG.intraday_vol_mult:
            continue
        ts_end = r["TS"] + pd.Timedelta(minutes=bm)
        bias = index_bias_at(nifty_day, ts_end)
        c, o, vwap = float(r["CLOSE"]), float(r["OPEN"]), float(r["VWAP"])
        long_ok = (c > or_high * (1 + buf) and c > o and c > vwap and (prev_close is None or c > prev_close)
                   and (not require_index or nifty_day is None or bias == 1))
        short_ok = (c < or_low * (1 - buf) and c < o and c < vwap and (prev_close is None or c < prev_close)
                    and (not require_index or nifty_day is None or bias == -1))
        if not (long_ok or short_ok):
            continue
        side = "LONG" if long_ok else "SHORT"
        raw = (c - or_low) if side == "LONG" else (or_high - c)
        risk = min(max(raw, c * CFG.intraday_min_stop_pct / 100), c * CFG.intraday_max_stop_pct / 100)
        sgn = 1 if side == "LONG" else -1
        return Signal(symbol, side, i, ts_end, c, c - sgn * risk, risk,
                      c + sgn * CFG.intraday_t1_r * risk, c + sgn * CFG.intraday_t2_r * risk,
                      c + sgn * CFG.intraday_t3_r * risk, or_high, or_low, round(vr, 2), vwap, bias)
    return None


def simulate(day: pd.DataFrame, sig: Signal, now: pd.Timestamp | None = None) -> dict:
    """Signal ko NEXT bar ke open se chalao. Conservative: ek bar me pehle stop check, phir targets.

    Returns dict: status (PENDING / ACTIVE / T1 HIT / T2 HIT / TARGET 3 / STOPPED / BREAKEVEN / SQUARED OFF / SKIPPED),
    fill, exit_px, exit_ts, r (net R after cost), ltp, closed(bool)
    """
    d = clean_day(day)
    sgn = 1 if sig.side == "LONG" else -1
    j0 = sig.bar_idx + 1
    if j0 >= len(d):
        return dict(status="PENDING", fill=np.nan, exit_px=np.nan, exit_ts=pd.NaT, r=np.nan, ltp=sig.close, closed=False)
    fill = float(d["OPEN"].iloc[j0])
    # bar khulte hi SL ke paar ya 0.5R se zyada gap -> trade skip (chase nahi)
    if sgn * (fill - sig.stop) <= 0 or sgn * (fill - sig.close) > 0.5 * sig.risk:
        return dict(status="SKIPPED", fill=fill, exit_px=np.nan, exit_ts=pd.NaT, r=np.nan, ltp=float(d["CLOSE"].iloc[-1]), closed=True)
    risk = abs(fill - sig.stop)
    stop, level = sig.stop, 0
    sq = _hhmm(CFG.intraday_square_off)
    mins = _mins(d["TS"])
    cost_r = (fill * CFG.intraday_cost_pct / 100) / risk if risk else 0.0
    status = "ACTIVE"
    for j in range(j0, len(d)):
        o, h, l, c = (float(d[x].iloc[j]) for x in ("OPEN", "HIGH", "LOW", "CLOSE"))
        if mins[j] >= sq:                                           # square-off bar ke open par
            return _done(d, j, o, fill, sgn, risk, cost_r, "SQUARED OFF")
        hit_stop = (l <= stop) if sgn > 0 else (h >= stop)
        if hit_stop:
            px = min(o, stop) if sgn > 0 else max(o, stop)
            st = "BREAKEVEN" if level == 1 else "STOPPED" if level == 0 else f"T{level} HIT (trail exit)"
            return _done(d, j, px, fill, sgn, risk, cost_r, st)
        best = h if sgn > 0 else l
        if (best - sig.t3) * sgn >= 0:
            return _done(d, j, sig.t3, fill, sgn, risk, cost_r, "TARGET 3")
        if (best - sig.t2) * sgn >= 0 and level < 2:
            level, stop, status = 2, sig.t1, "T2 HIT"
        elif (best - sig.t1) * sgn >= 0 and level < 1:
            level, stop, status = 1, fill, "T1 HIT"
    last = float(d["CLOSE"].iloc[-1])
    return dict(status=status, fill=fill, exit_px=np.nan, exit_ts=pd.NaT, r=round(sgn * (last - fill) / risk, 2),
                ltp=last, closed=False, stop_now=stop)


def _done(d, j, px, fill, sgn, risk, cost_r, status) -> dict:
    r = sgn * (px - fill) / risk - cost_r
    return dict(status=status, fill=fill, exit_px=px, exit_ts=d["TS"].iloc[j], r=round(r, 3),
                ltp=float(d["CLOSE"].iloc[-1]), closed=True)


def intraday_size(entry: float, stop: float) -> dict:
    risk_ps = abs(entry - stop)
    if risk_ps <= 0 or entry <= 0:
        return dict(QTY=0, CAPITAL_USED=0.0, RISK_AMT=0.0)
    qty = min(CFG.intraday_capital * CFG.intraday_risk_pct / 100 / risk_ps,
              CFG.intraday_capital * CFG.intraday_max_leverage / entry)
    qty = int(max(0, np.floor(qty)))
    return dict(QTY=qty, CAPITAL_USED=round(qty * entry, 2), RISK_AMT=round(qty * risk_ps, 2))


def replay_day(days: dict[str, pd.DataFrame], prev_close: dict[str, float], nifty_day: pd.DataFrame | None,
               now: pd.Timestamp | None = None) -> list[dict]:
    """Din ke saare symbols ka stateless replay -> signals (time order), max `intraday_max_trades`, status ke saath.

    days: {symbol: bars of ONE trading day}. now=None => poora din (backtest).
    """
    nd = completed_only(clean_day(nifty_day), now) if nifty_day is not None and len(nifty_day) else None
    found = []
    for sym, df in days.items():
        if df is None or df.empty:
            continue
        d = completed_only(clean_day(df), now)
        s = build_signal(sym, d, prev_close.get(sym), nd)
        if s is not None:
            found.append((s, d))
    found.sort(key=lambda x: (x[0].ts, -x[0].vol_ratio))
    out = []
    for s, d in found[: CFG.intraday_max_trades]:
        sim = simulate(d, s, now)
        sz = intraday_size(s.close, s.stop)
        out.append({**s.__dict__, **sim, **sz})
    return out


# --------------------------------------------------------------------------- backtest
def backtest(history: dict[str, pd.DataFrame], nifty: pd.DataFrame | None) -> pd.DataFrame:
    """history: {symbol: multi-day 5-min bars (TS, OHLCV)}. Har din replay_day (poora din) -> trades."""
    by_day: dict[pd.Timestamp, dict[str, pd.DataFrame]] = {}
    prev: dict[pd.Timestamp, dict[str, float]] = {}
    for sym, df in history.items():
        df = clean_day(df)
        df["D"] = df["TS"].dt.normalize()
        last_close = None
        for day, g in df.groupby("D"):
            by_day.setdefault(day, {})[sym] = g.drop(columns="D").reset_index(drop=True)
            prev.setdefault(day, {})[sym] = last_close
            last_close = float(g["CLOSE"].iloc[-1])
    nby = {}
    if nifty is not None and len(nifty):
        nn = clean_day(nifty)
        nn["D"] = nn["TS"].dt.normalize()
        nby = {k: g.drop(columns="D").reset_index(drop=True) for k, g in nn.groupby("D")}
    rows = []
    for day in sorted(by_day):
        for t in replay_day(by_day[day], {k: v for k, v in prev[day].items() if v is not None}, nby.get(day), now=None):
            if t["status"] in ("SKIPPED", "PENDING"):
                continue
            rows.append(dict(DATE=day, SYMBOL=t["symbol"], SIDE=t["side"], SIGNAL_TIME=t["ts"], FILL=t["fill"],
                             STATUS=t["status"], R=t["r"], VOL_RATIO=t["vol_ratio"]))
    return pd.DataFrame(rows)


def summarize(t: pd.DataFrame) -> dict:
    if t is None or t.empty:
        return dict(trades=0)
    r = t["R"].astype(float)
    pf = r[r > 0].sum() / -r[r < 0].sum() if (r < 0).any() else np.inf
    eq = r.cumsum()
    dd = float((eq - eq.cummax()).min())
    return dict(trades=len(t), win_pct=round((r > 0).mean() * 100, 1), avg_r=round(r.mean(), 3), pf=round(float(pf), 2),
                total_r=round(float(r.sum()), 1), max_dd_r=round(dd, 1), days=int(t["DATE"].nunique()),
                long_avg_r=round(float(r[t.SIDE == "LONG"].mean()), 3) if (t.SIDE == "LONG").any() else None,
                short_avg_r=round(float(r[t.SIDE == "SHORT"].mean()), 3) if (t.SIDE == "SHORT").any() else None)

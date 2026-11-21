"""INTRADAY runner.

    python src/intraday_run.py                      # ek live scan -> INTRADAY tab
    python src/intraday_run.py --loop               # 09:20-15:30 har 5 min (server par)
    python src/intraday_run.py --backtest 60        # pichhle 60 din ka backtest (Angel 5-min data)
    python src/intraday_run.py --csv-dir data/ --backtest 0   # apna 5-min CSV data (SYMBOL.csv, NIFTY.csv) se backtest
    python src/intraday_run.py --csv-dir data/ --now "2026-11-18 10:05" --no-publish   # offline replay

Order kabhi nahi lagta. Sirf signal + levels + qty.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import intraday as it              # noqa: E402
import publish as pb               # noqa: E402
import sheets3 as s3               # noqa: E402
from config import CFG             # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
STATE = Path(os.getenv("NSE_STATE_DIR", ROOT / "state"))
OUT = Path(os.getenv("NSE_OUTPUT_DIR", ROOT / "output"))
CACHE = STATE / "intraday_cache"
BT_FILE = STATE / "intraday_backtest.json"
IST = ZoneInfo("Asia/Kolkata")


def now_ist() -> pd.Timestamp:
    return pd.Timestamp(datetime.now(IST).replace(tzinfo=None))


def universe() -> list[str]:
    env = os.getenv("INTRADAY_SYMBOLS", "").strip()
    return [s.strip().upper() for s in env.split(",") if s.strip()] if env else list(it.DEFAULT_UNIVERSE)


# --------------------------------------------------------------------------- data sources
def read_csv_dir(path: Path, symbols: list[str]) -> tuple[dict, pd.DataFrame | None, list[str]]:
    data, missing = {}, []
    for s in symbols:
        p = path / f"{s.replace('&', '_AND_')}.csv"
        if not p.exists():
            missing.append(s)
            continue
        data[s] = it.clean_day(pd.read_csv(p, parse_dates=["TS"]))
    nf = path / "NIFTY.csv"
    return data, (it.clean_day(pd.read_csv(nf, parse_dates=["TS"])) if nf.exists() else None), missing


def fetch_angel(symbols: list[str], start: datetime, end: datetime, use_cache: bool = False):
    from angel import AngelClient
    cl = AngelClient().login()
    data, missing = {}, []
    CACHE.mkdir(parents=True, exist_ok=True)
    for k, s in enumerate(symbols, 1):
        if cl.token_for(s) is None:
            missing.append(s)
            continue
        cached = pd.DataFrame()
        cp = CACHE / f"{s.replace('&', '_AND_')}.csv.gz"
        s_from = start
        if use_cache and cp.exists():
            cached = pd.read_csv(cp, parse_dates=["TS"])
            if len(cached):
                s_from = max(start, cached["TS"].max().to_pydatetime() - timedelta(days=1))
        fresh = cl.candles(s, s_from, end)
        df = pd.concat([cached, fresh], ignore_index=True) if len(cached) else fresh
        if len(df):
            df = it.clean_day(df)
            if use_cache:
                df.to_csv(cp, index=False, compression="gzip")
            data[s] = df
        else:
            missing.append(s)
        if k % 10 == 0:
            print(f"  fetched {k}/{len(symbols)}")
    return data, cl.nifty(start, end), missing


# --------------------------------------------------------------------------- live
def split_today(data: dict[str, pd.DataFrame], today: pd.Timestamp):
    days, prev = {}, {}
    for s, df in data.items():
        d = df["TS"].dt.normalize()
        t = df[d == today].reset_index(drop=True)
        p = df[d < today]
        if len(p):
            prev[s] = float(p["CLOSE"].iloc[-1])
        if len(t):
            days[s] = t
    return days, prev


def live_scan(now: pd.Timestamp, csv_dir: Path | None, publish: bool = True, book=None) -> list[dict]:
    syms = universe()
    today = now.normalize()
    err = None
    try:
        if csv_dir:
            data, nifty, missing = read_csv_dir(csv_dir, syms)
        else:
            data, nifty, missing = fetch_angel(syms, (today - timedelta(days=6)).to_pydatetime().replace(hour=9, minute=0),
                                               now.to_pydatetime())
    except Exception as e:     # noqa: BLE001
        data, nifty, missing, err = {}, None, [], f"DATA ERROR: {e}"
        print(err)
    days, prev = split_today(data, today)
    nday = None
    if nifty is not None and len(nifty):
        nday = nifty[nifty["TS"].dt.normalize() == today].reset_index(drop=True)
    sigs = it.replay_day(days, prev, nday, now=now)
    bias = it.index_bias_at(nday, now) if nday is not None and len(nday) else None
    bt = json.loads(BT_FILE.read_text()) if BT_FILE.exists() else None
    meta = dict(now=now, bias=bias, scanned=len(days), missing=missing, error=err, backtest=bt, market_open=bool(days))
    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(sigs).to_csv(OUT / "intraday_signals.csv", index=False)
    print(f"INTRADAY {now:%Y-%m-%d %H:%M} | scanned {len(days)} | signals {len(sigs)} | bias {bias}")
    for s in sigs:
        print(f"  {s['ts']:%H:%M} {s['symbol']:<12} {s['side']:<5} entry~{s['close']:.2f} SL {s['stop']:.2f} T1 {s['t1']:.2f} "
              f"T3 {s['t3']:.2f} qty {s['QTY']} -> {s['status']}")
    if publish:
        s3.publish_tab(CFG.intraday_tab, s3.build_intraday_rows(sigs, meta), book=book)
    return sigs


def loop(csv_dir: Path | None, publish: bool):
    book = pb.open_book() if publish else None
    while True:
        n = now_ist()
        hm = n.hour * 60 + n.minute
        if n.weekday() >= 5 or hm > 15 * 60 + 35:
            print("Market band - loop khatam")
            return
        if hm >= 9 * 60 + 20:
            try:
                live_scan(n, csv_dir, publish, book)
            except Exception as e:      # noqa: BLE001
                print("scan error:", e)
        nxt = (n.floor("5min") + pd.Timedelta(minutes=5, seconds=20)).to_pydatetime()
        time.sleep(max(5, (nxt - n.to_pydatetime()).total_seconds()))


# --------------------------------------------------------------------------- backtest
def run_backtest(days: int, csv_dir: Path | None, publish_book=None) -> dict:
    syms = universe()
    if csv_dir:
        data, nifty, missing = read_csv_dir(csv_dir, syms)
    else:
        end = now_ist().to_pydatetime()
        data, nifty, missing = fetch_angel(syms, end - timedelta(days=days), end, use_cache=True)
    print(f"BACKTEST data: {len(data)} symbols, missing {len(missing)}")
    t = it.backtest(data, nifty)
    summ = it.summarize(t)
    OUT.mkdir(parents=True, exist_ok=True)
    t.to_csv(OUT / "intraday_backtest_trades.csv", index=False)
    print("BACKTEST |", summ)
    if len(t):
        m = t.assign(M=t["DATE"].dt.to_period("M")).groupby("M")["R"].agg(["count", "sum", "mean"]).round(2)
        print(m.to_string())
        for c in (0.12, 0.25, 0.40):                         # cost sensitivity: extra cost R me (approx avg risk 0.7%)
            extra = (c - CFG.intraday_cost_pct) / 0.7
            print(f"  cost {c:.2f}% -> avg R {t['R'].mean() - extra:.3f}")
    STATE.mkdir(parents=True, exist_ok=True)
    BT_FILE.write_text(json.dumps({k: (None if v is None else int(v) if k in ("trades", "days") else float(v)) for k, v in summ.items()}))
    return summ


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--backtest", type=int, default=None, metavar="DAYS")
    ap.add_argument("--csv-dir", default="")
    ap.add_argument("--now", default="", help='simulate time "YYYY-MM-DD HH:MM" (offline test)')
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    csv_dir = Path(a.csv_dir) if a.csv_dir else None
    if a.backtest is not None:
        run_backtest(a.backtest, csv_dir)
        return 0
    if a.loop:
        loop(csv_dir, not a.no_publish)
        return 0
    live_scan(pd.Timestamp(a.now) if a.now else now_ist(), csv_dir, not a.no_publish)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

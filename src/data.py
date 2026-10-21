"""Data layer.

History  : pehli baar (ya cache khatam hone par) ~8 saal ka data eod2_data GitHub repo se
           (public, GitHub Actions se hamesha reachable). Iske baad rozana sirf naye din
           NSE bhavcopy se jode jate hain. Isse backtest ko 2019+ ka deep sample milta hai
           (purana system sirf ~6 mahine par gate laga raha tha).
Local    : HISTORY_SOURCE_BASE me local folder path do to wahin se CSV padhe jaate hain
           (testing / offline).
"""
from __future__ import annotations

import concurrent.futures as cf
import os
import re
import urllib.parse
from datetime import datetime, timedelta
from io import BytesIO, StringIO
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from config import CFG
from engine import COLS

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.nseindia.com/"}
BAD_NAME = ("ETF", "BEES", "GOLD", "SILVER", "LIQUID")


# --------------------------------------------------------------------------- universe
def fetch_universe() -> list[str]:
    s = requests.Session()
    s.headers.update(UA)
    for url in ("https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
                "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.xlsx"):
        try:
            r = s.get(url, headers={**UA, "Referer": "https://www.niftyindices.com/"}, timeout=30)
            if not r.ok or len(r.content) < 1000:
                continue
            df = pd.read_csv(StringIO(r.content.decode("utf-8-sig", errors="replace"))) if url.endswith(".csv") \
                else pd.read_excel(BytesIO(r.content), engine="openpyxl")
            cols = {str(c).strip().upper().replace(" ", "_"): c for c in df.columns}
            col = cols.get("SYMBOL") or cols.get("SYMBOLS") or cols.get("SECURITY")
            if not col:
                continue
            syms = [x for x in df[col].astype(str).str.strip().str.upper()
                    if re.fullmatch(r"[A-Z0-9&.\-]+", x) and not any(k in x for k in BAD_NAME)]
            if len(syms) >= 450:
                print(f"UNIVERSE: {len(syms)} Nifty 500 symbols")
                return sorted(set(syms))
        except Exception as e:  # noqa: BLE001
            print("universe source warning:", e)
    raise RuntimeError("Nifty 500 list nahi mili (niftyindices.com). Thodi der baad dobara run karo.")


# --------------------------------------------------------------------------- deep history
def _read_eod2(sym: str, base: str) -> pd.DataFrame | None:
    fname = urllib.parse.quote(sym.lower(), safe="") + ".csv"
    try:
        if base.startswith("http"):
            r = requests.get(base + fname, timeout=40)
            if r.status_code != 200 or len(r.content) < 2000:
                return None
            raw = pd.read_csv(BytesIO(r.content))
        else:
            p = Path(base) / (sym.replace("&", "_AND_") + ".csv")
            if not p.exists():
                p = Path(base) / (sym.lower() + ".csv")
            if not p.exists():
                return None
            raw = pd.read_csv(p)
        raw["Date"] = pd.to_datetime(raw["Date"], errors="coerce")
        if "Series" in raw:
            raw = raw[raw["Series"].astype(str).str.strip().eq("EQ")]
        raw = raw[raw["Date"] >= CFG.history_start]
        out = pd.DataFrame({"SYMBOL": sym, "DATE": raw["Date"], "OPEN": raw["Open"], "HIGH": raw["High"],
                            "LOW": raw["Low"], "CLOSE": raw["Close"], "VOLUME": raw["Volume"]})
        return out.dropna()
    except Exception:  # noqa: BLE001
        return None


def bootstrap_history(symbols: list[str], base: str | None = None, workers: int = 16) -> pd.DataFrame:
    base = base or CFG.history_source_base
    print(f"BOOTSTRAP: {len(symbols)} symbols <- {base[:60]}")
    parts, missing = [], []
    with cf.ThreadPoolExecutor(workers) as ex:
        for sym, d in zip(symbols, ex.map(lambda s: _read_eod2(s, base), symbols)):
            (parts.append(d) if d is not None and len(d) else missing.append(sym))
    if not parts:
        raise RuntimeError("History bootstrap fail: koi symbol load nahi hua")
    print(f"BOOTSTRAP: loaded {len(parts)} | missing {len(missing)}")
    return pd.concat(parts, ignore_index=True)


# --------------------------------------------------------------------------- NSE incremental
def fetch_bhav(session: requests.Session, d: datetime) -> pd.DataFrame | None:
    url = f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d:%d%m%Y}.csv"
    try:
        r = session.get(url, timeout=25)
        if r.status_code != 200 or len(r.content) < 500:
            return None
        df = pd.read_csv(StringIO(r.text), encoding="utf-8-sig")
        df.columns = [str(c).replace("\ufeff", "").strip().upper().replace(" ", "_") for c in df.columns]
        need = ["SYMBOL", "SERIES", "OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE", "CLOSE_PRICE", "TTL_TRD_QNTY"]
        if any(c not in df.columns for c in need):
            return None
        df = df[df.SERIES.astype(str).str.strip().eq("EQ")]
        out = pd.DataFrame({"SYMBOL": df.SYMBOL.astype(str).str.strip().str.upper(), "DATE": pd.Timestamp(d),
                            "OPEN": pd.to_numeric(df.OPEN_PRICE, errors="coerce"),
                            "HIGH": pd.to_numeric(df.HIGH_PRICE, errors="coerce"),
                            "LOW": pd.to_numeric(df.LOW_PRICE, errors="coerce"),
                            "CLOSE": pd.to_numeric(df.CLOSE_PRICE, errors="coerce"),
                            "VOLUME": pd.to_numeric(df.TTL_TRD_QNTY, errors="coerce")})
        return out.dropna()
    except Exception as e:  # noqa: BLE001
        print("bhav fetch warning", d.date(), e)
        return None


def top_up(hist: pd.DataFrame, symbols: list[str]) -> pd.DataFrame:
    last = pd.to_datetime(hist["DATE"]).max()
    s = requests.Session()
    s.headers.update(UA)
    try:
        s.get("https://www.nseindia.com", timeout=20)
    except Exception:  # noqa: BLE001
        pass
    new, d, today = [], last.to_pydatetime() + timedelta(days=1), datetime.now()
    while d.date() <= today.date():
        if d.weekday() < 5:
            x = fetch_bhav(s, d)
            if x is not None:
                x = x[x.SYMBOL.isin(symbols)]
                if not x.empty:
                    new.append(x)
                    print(f"NSE top-up {d:%Y-%m-%d}: {len(x)} rows")
        d += timedelta(days=1)
    if not new:
        print("NSE top-up: koi naya session nahi mila")
        return hist
    return pd.concat([hist, *new], ignore_index=True)


# --------------------------------------------------------------------------- state (cache)
def load_state(path: Path) -> pd.DataFrame | None:
    if not Path(path).exists():
        return None
    try:
        d = pd.read_csv(path, parse_dates=["DATE"])
        return d if set(COLS) <= set(d.columns) else None
    except Exception as e:  # noqa: BLE001
        print("state load warning:", e)
        return None


def save_state(hist: pd.DataFrame, path: Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    hist[COLS].to_csv(path, index=False, compression="gzip" if str(path).endswith(".gz") else None)


def load_history(state_path: Path, symbols: list[str], rebuild: bool = False, offline: bool = False) -> pd.DataFrame:
    hist = None if rebuild else load_state(state_path)
    if hist is None or hist["SYMBOL"].nunique() < 300:
        hist = bootstrap_history(symbols)
    if not offline:
        hist = top_up(hist, symbols)
    hist = hist[hist["SYMBOL"].isin(symbols)]
    hist = hist.sort_values(["SYMBOL", "DATE"]).drop_duplicates(["SYMBOL", "DATE"], keep="last").reset_index(drop=True)
    save_state(hist, state_path)
    return hist


def load_positions_history(symbols: list[str], offline: bool = False) -> pd.DataFrame:
    """Load history for user-held stocks outside the scan universe.

    These bars are used ONLY for MY POSITIONS monitoring; callers must not mix
    them into the signal universe/backtest because that would alter cross-sectional ranks.
    Missing symbols remain absent and are reported, never filled with fabricated prices.
    """
    symbols = sorted({str(s).strip().upper() for s in symbols if str(s).strip()})
    cols = ["SYMBOL", "DATE", "OPEN", "HIGH", "LOW", "CLOSE", "VOLUME"]
    if not symbols:
        return pd.DataFrame(columns=cols)
    try:
        hist = bootstrap_history(symbols)
    except RuntimeError as e:
        print(f"POSITIONS HISTORY: bootstrap unavailable for {symbols}: {e}")
        return pd.DataFrame(columns=cols)
    if hist is None or hist.empty:
        return pd.DataFrame(columns=cols)
    if not offline:
        try:
            hist = top_up(hist, symbols)
        except Exception as e:  # noqa: BLE001
            print("POSITIONS HISTORY: NSE top-up warning:", e)
    hist = hist[hist["SYMBOL"].isin(symbols)].copy()
    hist["DATE"] = pd.to_datetime(hist["DATE"], errors="coerce")
    hist = hist.dropna(subset=["DATE", "OPEN", "HIGH", "LOW", "CLOSE"])
    hist = hist.sort_values(["SYMBOL", "DATE"]).drop_duplicates(["SYMBOL", "DATE"], keep="last").reset_index(drop=True)
    found = set(hist["SYMBOL"].unique())
    missing = sorted(set(symbols) - found)
    print(f"POSITIONS HISTORY: loaded {len(found)}/{len(symbols)} held symbols"
          + (f"; no history: {', '.join(missing)}" if missing else ""))
    return hist


def sessions_behind(last: pd.Timestamp, today: datetime | None = None) -> int:
    today = pd.Timestamp(today or datetime.now()).normalize()
    if last >= today:
        return 0
    return max(0, len(pd.bdate_range(last + pd.Timedelta(days=1), today)))

"""Angel One SmartAPI wrapper - sirf HISTORICAL candles (data). Isse kabhi order nahi lagta.

Env (GitHub Secrets ya server .env):
    ANGEL_API_KEY, ANGEL_CLIENT_CODE, ANGEL_PIN, ANGEL_TOTP_SECRET
Install: pip install -r requirements-intraday.txt   (smartapi-python, pyotp)

Rate limit: getCandleData ~3 req/sec -> hum ~2.5/sec par chalte hain, error par backoff + retry.
Candle limits (Angel docs): 1-min ~30 din, 5-min ~100 din, 15-min ~200 din per request -> hum 30-din chunks lete hain.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

SCRIP_MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_Files/OpenAPIScripMaster.json"
NIFTY_INDEX = ("Nifty 50", "99926000", "NSE")        # (name, token, exchange) - NIFTY 50 index
INTERVAL_5M = "FIVE_MINUTE"
_COLS = ["TS", "OPEN", "HIGH", "LOW", "CLOSE", "VOLUME"]


def candles_to_df(rows: list | None) -> pd.DataFrame:
    """Angel ke candle rows [[iso_ts, o, h, l, c, v], ...] -> DataFrame (TS = naive IST bar-start)."""
    if not rows:
        return pd.DataFrame(columns=_COLS)
    df = pd.DataFrame(rows, columns=_COLS)
    ts = pd.to_datetime(df["TS"], errors="coerce")
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    df["TS"] = ts
    for c in _COLS[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=["TS", "OPEN", "HIGH", "LOW", "CLOSE"]).reset_index(drop=True)


class AngelClient:
    def __init__(self, smart=None, sleep: float = 0.4, state_dir: Path | None = None):
        self.smart = smart
        self.sleep = sleep
        self.state_dir = Path(state_dir or os.getenv("NSE_STATE_DIR", Path(__file__).resolve().parents[1] / "state"))
        self._tokens: dict[str, tuple[str, str]] | None = None

    # ------------------------------------------------------------------ login
    def login(self) -> "AngelClient":
        if self.smart is not None:
            return self
        try:
            from SmartApi import SmartConnect          # smartapi-python
        except ImportError as e:                       # noqa: BLE001
            raise RuntimeError("smartapi-python install nahi hai: pip install -r requirements-intraday.txt") from e
        import pyotp
        need = ["ANGEL_API_KEY", "ANGEL_CLIENT_CODE", "ANGEL_PIN", "ANGEL_TOTP_SECRET"]
        miss = [k for k in need if not os.getenv(k)]
        if miss:
            raise RuntimeError("Angel env missing: " + ", ".join(miss))
        s = SmartConnect(api_key=os.environ["ANGEL_API_KEY"])
        totp = pyotp.TOTP(os.environ["ANGEL_TOTP_SECRET"].replace(" ", "")).now()
        r = s.generateSession(os.environ["ANGEL_CLIENT_CODE"], os.environ["ANGEL_PIN"], totp)
        if not r or not r.get("status"):
            raise RuntimeError(f"Angel login fail: {(r or {}).get('message')}")
        self.smart = s
        return self

    # ------------------------------------------------------------------ tokens
    def _load_master(self) -> list[dict]:
        cache = self.state_dir / "scrip_master.json"
        if cache.exists() and datetime.fromtimestamp(cache.stat().st_mtime).date() == datetime.now().date():
            return json.loads(cache.read_text())
        import requests
        r = requests.get(SCRIP_MASTER_URL, timeout=60)
        r.raise_for_status()
        data = r.json()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps([x for x in data if x.get("exch_seg") == "NSE" and str(x.get("symbol", "")).endswith("-EQ")]))
        return json.loads(cache.read_text())

    def token_for(self, symbol: str) -> tuple[str, str] | None:
        """(token, tradingsymbol) NSE EQ ke liye. Nahi mila to None (symbol badla / delist)."""
        if self._tokens is None:
            self._tokens = {x["name"].upper(): (str(x["token"]), x["symbol"]) for x in self._load_master()}
        return self._tokens.get(symbol.upper())

    # ------------------------------------------------------------------ candles
    def _get(self, token: str, exchange: str, interval: str, start: datetime, end: datetime) -> pd.DataFrame:
        params = {"exchange": exchange, "symboltoken": token, "interval": interval,
                  "fromdate": start.strftime("%Y-%m-%d %H:%M"), "todate": end.strftime("%Y-%m-%d %H:%M")}
        delay = 1.0
        for attempt in range(5):
            time.sleep(self.sleep)
            try:
                res = self.smart.getCandleData(params)
            except Exception as e:                                         # noqa: BLE001
                res = {"status": False, "message": str(e)}
            if res and res.get("status"):
                return candles_to_df(res.get("data"))
            msg = str((res or {}).get("message", "")).lower()
            if "rate" in msg or "access denied" in msg or "exceed" in msg or "timeout" in msg or "connection" in msg:
                time.sleep(delay)
                delay *= 2
                continue
            return pd.DataFrame(columns=_COLS)                             # data nahi (holiday / invalid token)
        return pd.DataFrame(columns=_COLS)

    def candles(self, symbol: str, start: datetime, end: datetime, interval: str = INTERVAL_5M,
                exchange: str = "NSE", token: str | None = None) -> pd.DataFrame:
        if token is None:
            t = self.token_for(symbol)
            if t is None:
                return pd.DataFrame(columns=_COLS)
            token = t[0]
        parts, cur = [], start
        while cur < end:
            nxt = min(cur + timedelta(days=30), end)
            parts.append(self._get(token, exchange, interval, cur, nxt))
            cur = nxt
        parts = [p for p in parts if len(p)]
        if not parts:
            return pd.DataFrame(columns=_COLS)
        return pd.concat(parts, ignore_index=True).drop_duplicates("TS").sort_values("TS").reset_index(drop=True)

    def nifty(self, start: datetime, end: datetime) -> pd.DataFrame:
        return self.candles(NIFTY_INDEX[0], start, end, token=NIFTY_INDEX[1], exchange=NIFTY_INDEX[2])

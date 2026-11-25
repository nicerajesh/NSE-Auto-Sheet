"""Research-only Delivery20 publisher with transparent near-miss watchlist."""
from pathlib import Path
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import data as dt
import publish as pb
from engine import add_features
from delivery20 import add_delivery20_signals

STATE = ROOT / "state"
STATE.mkdir(exist_ok=True)
symbols = dt.fetch_universe()
hist = dt.load_history(STATE / "history.csv.gz", symbols)
features = add_features(hist)
signals = add_delivery20_signals(features)
asof = pd.Timestamp(signals["DATE"].max())
latest_all = signals[signals["DATE"] == asof].copy()

# Strict BUY logic remains unchanged. This ranking only explains near-misses.
diagnostics = []
for symbol, raw in signals.groupby("SYMBOL", sort=False):
    d = raw.sort_values("DATE")
    r = d.iloc[-1]
    if pd.Timestamp(r["DATE"]) != asof:
        continue
    close = float(r["CLOSE"])
    e20, e50, e200 = (float(r[x]) for x in ("EMA20", "EMA50", "EMA200"))
    resistance = float(d["HIGH"].shift(1).rolling(55, min_periods=45).max().iloc[-1])
    trend = close > e20 > e50 > e200
    rising = (len(d) > 20 and e50 > float(d["EMA50"].iloc[-21])
              and e200 > float(d["EMA200"].iloc[-21]))
    checks = [
        trend, rising, close > resistance, float(r["VOL_RATIO"]) >= 1.5,
        float(r["ADX"]) >= 22, float(r["MOM_RANK"]) >= 80,
        float(r["TURNOVER_CR"]) >= 10, close <= e20 * 1.15,
        float(r["JUMP_RECENT"]) == 0,
        5.0 <= float(r["D20_RISK_PCT"]) <= 10.0,
    ]
    labels = ["TREND", "RISING EMA", "55D BREAKOUT", "VOLUME>=1.5x",
              "ADX>=22", "MOM>=80", "TURNOVER>=10Cr", "NOT EXTENDED",
              "NO RECENT JUMP", "RISK 5-10%"]
    diagnostics.append({
        "symbol": symbol, "row": r, "score": sum(checks) * 10,
        "failed": [name for name, ok in zip(labels, checks) if not ok],
    })

buy_symbols = set(latest_all.loc[latest_all["D20_BUY"].fillna(False), "SYMBOL"].astype(str))
watch = sorted(
    (x for x in diagnostics if x["symbol"] not in buy_symbols),
    key=lambda x: (x["score"], float(x["row"]["MOM_RANK"]), float(x["row"]["VOL_RATIO"])),
    reverse=True,
)[:20]
buys = latest_all[latest_all["D20_BUY"].fillna(False)].sort_values(
    ["MOM_RANK", "VOL_RATIO"], ascending=False
)

rows = [
    [f"RY DELIVERY20 RESEARCH | Data: {asof:%d-%b-%Y} | Research only; NOT production BUY"],
    ["Universe limitation: current universe/history is not yet fully PIT mapped; survivorship-bias audit is incomplete."],
    ["Entry: next session OPEN; skip if gap-up >2% vs signal close or open <= stop. No auto orders."],
    ["T1/T2/T3 are risk-multiple levels (2R/4R/6R). 20/30/40% targets are reference levels from signal close."],
    ["WATCHLIST is diagnostic only: filter score and failed conditions are shown. It is NOT a BUY signal."],
    ["STOCK", "STATUS", "SIGNAL CLOSE", "NEXT OPEN ENTRY", "STOP LOSS",
     "T1 (2R)", "T2 (4R)", "T3 (6R)", "TARGET +20%", "TARGET +30%", "TARGET +40%",
     "RISK %", "MOM RANK", "VOLUME x", "ADX", "AVG TURNOVER Cr",
     "FILTER SCORE", "FAILED CONDITIONS", "DATA DATE"]
]
for _, r in buys.iterrows():
    close, stop = float(r["CLOSE"]), float(r["D20_STOP"])
    risk = close - stop
    rows.append([
        str(r["SYMBOL"]), "BUY (RESEARCH)", close, "Next session OPEN", stop,
        close + 2*risk, close + 4*risk, close + 6*risk,
        close*1.20, close*1.30, close*1.40, float(r["D20_RISK_PCT"]),
        float(r["MOM_RANK"]), float(r["VOL_RATIO"]), float(r["ADX"]),
        float(r["TURNOVER_CR"]), 100, "", asof.strftime("%d-%b-%Y")
    ])
if buys.empty:
    rows.append(["", "NO BUY SETUP TODAY"] + [""] * 17)
rows.append(["", "TOP WATCHLIST (NOT BUY)"] + [""] * 17)
for item in watch:
    r = item["row"]
    close, stop = float(r["CLOSE"]), float(r["D20_STOP"])
    risk = close - stop
    rows.append([
        item["symbol"], "WATCHLIST ONLY", close, "Wait for valid BUY close", stop,
        close + 2*risk, close + 4*risk, close + 6*risk,
        close*1.20, close*1.30, close*1.40, float(r["D20_RISK_PCT"]),
        float(r["MOM_RANK"]), float(r["VOL_RATIO"]), float(r["ADX"]),
        float(r["TURNOVER_CR"]), item["score"], ", ".join(item["failed"]),
        asof.strftime("%d-%b-%Y")
    ])
if not watch and buys.empty:
    rows.append(["", "NO VALID WATCHLIST DATA"] + [""] * 17)


# Separate 52-week-low + heavy-volume monitor. This is a reversal watch,
# not a BUY signal: high volume near lows can mean accumulation OR distribution.
low_volume_rows = [
    [f"RY 52-WEEK LOW + HEAVY VOLUME | Data: {asof:%d-%b-%Y}"],
    ["Purpose: identify stocks near their 252-session low with unusually high volume; NOT a BUY recommendation."],
    ["Rule: close within 10% of rolling 252-session lowest LOW; volume ratio >= 1.5x; at least 200 sessions of history."],
    ["Review price action/support and company news separately. High volume near lows can mean accumulation OR distribution."],
    ["STOCK", "CLOSE", "52W LOW", "DISTANCE FROM 52W LOW %", "VOLUME", "20D AVG VOLUME", "VOLUME RATIO", "DAY CHANGE %", "AVG TURNOVER Cr", "ADX", "DATA DATE"]
]
low_candidates = []
for symbol, raw in signals.groupby("SYMBOL", sort=False):
    d = raw.sort_values("DATE")
    if pd.Timestamp(d.iloc[-1]["DATE"]) != asof or len(d) < 200:
        continue
    r = d.iloc[-1]
    low_52 = float(d["LOW"].tail(252).min())
    close = float(r["CLOSE"])
    vol_ratio = float(r["VOL_RATIO"])
    distance = (close / low_52 - 1.0) * 100 if low_52 > 0 else float("inf")
    if 0 <= distance <= 10 and vol_ratio >= 1.5:
        prev_close = float(d.iloc[-2]["CLOSE"]) if len(d) > 1 else close
        day_change = (close / prev_close - 1.0) * 100 if prev_close else 0.0
        avg_vol = float(r["VOLUME"]) / vol_ratio if vol_ratio > 0 else 0.0
        low_candidates.append({
            "symbol": symbol, "close": close, "low": low_52,
            "distance": distance, "volume": float(r["VOLUME"]),
            "avg_volume": avg_vol, "vol_ratio": vol_ratio,
            "day_change": day_change, "turnover": float(r["TURNOVER_CR"]),
            "adx": float(r["ADX"])
        })
low_candidates.sort(key=lambda x: (x["vol_ratio"], -x["distance"]), reverse=True)
for x in low_candidates:
    low_volume_rows.append([
        x["symbol"], x["close"], x["low"], round(x["distance"], 2),
        x["volume"], round(x["avg_volume"]), round(x["vol_ratio"], 2),
        round(x["day_change"], 2), round(x["turnover"], 2), round(x["adx"], 2),
        asof.strftime("%d-%b-%Y")
    ])
if not low_candidates:
    low_volume_rows.append(["", "NO STOCK MATCHED TODAY"] + [""] * 9)

book = pb.open_book()
if book is None:
    raise RuntimeError("Google Sheets publish skipped: GCP_CREDENTIALS missing or invalid")
pb._write_tab(book, "DELIVERY20", rows, {"title": [0, 1, 2, 3, 4], "header": [5]})
pb._write_tab(book, "52W LOW VOLUME", low_volume_rows, {"title": [0, 1, 2, 3], "header": [4]})
print(f"PUBLISHED DELIVERY20: {len(buys)} research BUY candidates | {len(watch)} watchlist names | {asof:%Y-%m-%d}")
print(f"PUBLISHED 52W LOW VOLUME: {len(low_candidates)} candidates | {asof:%Y-%m-%d}")

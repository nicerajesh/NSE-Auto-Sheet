import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import requests
import numpy as np
from datetime import datetime, timedelta
from io import StringIO
import os, json, time, math

# =========================================================
# CONFIG
# =========================================================
SPREADSHEET_ID = "1U9j5fMZAWPUSwoP_U-GKdacVke9nUjspqPR3wGsWAUM"

VOLUME_SHEET = "Top 250 Stocks"
TURNOVER_SHEET = "Top 250 Turnover"
HUNTER_SHEET = "Early Hunter"

HISTORY_DAYS = 90
MIN_TURNOVER_LACS = 1

# Early Hunter thresholds
MIN_SCORE = 65
STRONG_SCORE = 80
MAX_DISTANCE_FROM_RECENT_LOW_PCT = 12.0
MAX_DISTANCE_FROM_RESISTANCE_PCT = 4.0
MIN_RESISTANCE_DISTANCE_PCT = 0.25

# =========================================================
# GOOGLE AUTH
# =========================================================
creds_json = os.environ.get("GCP_CREDENTIALS")
if not creds_json:
    raise RuntimeError("CRITICAL: GCP_CREDENTIALS secret missing!")

creds_dict = json.loads(creds_json)
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

book = client.open_by_key(SPREADSHEET_ID)

try:
    ws_volume = book.worksheet(VOLUME_SHEET)
    ws_turnover = book.worksheet(TURNOVER_SHEET)
except Exception as e:
    raise RuntimeError(f"Sheet Connection Error: {e}")

try:
    ws_hunter = book.worksheet(HUNTER_SHEET)
except gspread.WorksheetNotFound:
    ws_hunter = book.add_worksheet(title=HUNTER_SHEET, rows=1000, cols=30)

# =========================================================
# NSE SESSION
# =========================================================
def get_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    try:
        session.get("https://www.nseindia.com", timeout=10)
    except Exception:
        pass
    return session

def fetch_full_bhavdata(session, date_obj):
    date_str = date_obj.strftime("%d%m%Y")
    url = f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{date_str}.csv"
    print(f"Checking {date_obj:%d-%m-%Y}: {url}")

    try:
        r = session.get(url, timeout=25)
        if r.status_code != 200 or len(r.content) < 500:
            return None

        df = pd.read_csv(StringIO(r.text))
        df.columns = [str(c).strip() for c in df.columns]

        for col in ["SYMBOL", "SERIES"]:
            if col in df.columns:
                df[col] = df[col].astype(str).str.strip()

        required = [
            "SYMBOL", "SERIES", "CLOSE_PRICE", "TTL_TRD_QNTY",
            "TURNOVER_LACS", "DELIV_QTY", "DELIV_PER"
        ]
        if not all(c in df.columns for c in required):
            return None

        df = df[df["SERIES"] == "EQ"].copy()

        filter_keywords = "BEES|ETF|GOLD|LIQUID|CASE|SILVER|LIQ"
        df = df[~df["SYMBOL"].str.contains(
            filter_keywords, case=False, na=False, regex=True
        )]

        numeric_cols = [
            "CLOSE_PRICE", "TTL_TRD_QNTY", "TURNOVER_LACS",
            "DELIV_QTY", "DELIV_PER"
        ]
        for c in numeric_cols:
            df[c] = pd.to_numeric(df[c], errors="coerce")

        df["DELIV_PER"] = df["DELIV_PER"].fillna(0)
        df = df.dropna(subset=["CLOSE_PRICE", "TTL_TRD_QNTY", "TURNOVER_LACS"])
        df = df[df["TURNOVER_LACS"] > MIN_TURNOVER_LACS].copy()

        df["DATE"] = date_obj.strftime("%Y-%m-%d")
        return df

    except Exception as e:
        print(f"Fetch error {date_obj:%d-%m-%Y}: {e}")
        return None

# =========================================================
# FETCH LAST TRADING DAYS
# =========================================================
session = get_session()
frames = []
today = datetime.now()

for i in range(HISTORY_DAYS + 15):
    d = today - timedelta(days=i)
    if d.weekday() >= 5:
        continue

    df = fetch_full_bhavdata(session, d)
    if df is not None and not df.empty:
        frames.append(df)
        print(f"Loaded {d:%d-%m-%Y}: {len(df)} rows")
    time.sleep(0.35)

    if len(frames) >= HISTORY_DAYS:
        break

if not frames:
    raise RuntimeError("No NSE bhavcopy data found.")

hist = pd.concat(frames, ignore_index=True)
hist["DATE"] = pd.to_datetime(hist["DATE"])
hist = hist.sort_values(["SYMBOL", "DATE"]).reset_index(drop=True)

latest_date = hist["DATE"].max()
latest = hist[hist["DATE"] == latest_date].copy()

# =========================================================
# BASIC INDICATORS
# =========================================================
def calc_indicators(g):
    g = g.sort_values("DATE").copy()
    close = g["CLOSE_PRICE"]
    volume = g["TTL_TRD_QNTY"]

    g["EMA20"] = close.ewm(span=20, adjust=False).mean()
    g["EMA50"] = close.ewm(span=50, adjust=False).mean()

    g["RET_5D"] = close.pct_change(5) * 100
    g["RET_10D"] = close.pct_change(10) * 100

    g["VOL_AVG20"] = volume.rolling(20, min_periods=5).mean()
    g["VOL_RATIO"] = volume / g["VOL_AVG20"].replace(0, np.nan)

    g["DELIV_AVG10"] = g["DELIV_PER"].rolling(10, min_periods=3).mean()

    # True Range / ATR14
    prev_close = close.shift(1)
    tr = pd.concat([
        (close - close.shift(1)).abs(),
        (close - prev_close).abs(),
    ], axis=1).max(axis=1)
    g["ATR14"] = tr.rolling(14, min_periods=5).mean()
    g["ATR_PCT"] = (g["ATR14"] / close) * 100
    g["ATR_AVG30"] = g["ATR_PCT"].rolling(30, min_periods=10).mean()
    g["ATR_COMPRESSION"] = (
        g["ATR_PCT"] < g["ATR_AVG30"] * 0.85
    )

    # Relative strength proxy versus broad market is not available in
    # NSE bhavcopy alone. We therefore use cross-sectional 20D strength.
    g["RS_PROXY"] = close.pct_change(20) * 100

    return g

hist = hist.groupby("SYMBOL", group_keys=False).apply(calc_indicators)
hist = hist.reset_index(drop=True)

# =========================================================
# SWING STRUCTURE / EARLY HUNTER ENGINE
# =========================================================
def _pct(a, b):
    """Percent distance from b to a."""
    if b is None or pd.isna(b) or b == 0:
        return np.nan
    return (a / b - 1.0) * 100.0


def _pivot_indices(values, left=2, right=2):
    """
    Confirmed swing pivots. A pivot needs bars on both sides, so the
    latest 2 sessions are never falsely treated as confirmed pivots.
    """
    lows, highs = [], []
    n = len(values)
    for i in range(left, n - right):
        window = values[i-left:i+right+1]
        if values[i] <= np.min(window):
            lows.append(i)
        if values[i] >= np.max(window):
            highs.append(i)
    return lows, highs


def analyze_stock(g):
    """
    Early Hunter objective:
      1) Detect a recent low / low-hold.
      2) Prefer FIRST_REVERSAL and HIGHER-LOW HUNTER over confirmed breakout.
      3) Confirm LOW -> HH -> HL, and optionally -> HH.
      4) Reject extended moves and stocks that have already broken out.
      5) Give the highest priority to the first confirmed Higher Low zone.

    This is intentionally a STRUCTURE detector, not a "buy at the exact
    bottom" detector. A real-time exact bottom cannot be known in advance.
    """
    g = g.sort_values("DATE").reset_index(drop=True)
    if len(g) < 30:
        return None

    w = g.tail(min(60, len(g))).copy().reset_index(drop=True)
    c = w["CLOSE_PRICE"].to_numpy(dtype=float)
    n = len(w)
    current = float(c[-1])

    lows, highs = _pivot_indices(c, 2, 2)

    # Candidate bottom: the most recent meaningful 30-session low.
    lookback_low_n = min(30, n)
    low_start = n - lookback_low_n
    candidate_rel = int(np.argmin(c[low_start:]))
    low_idx = low_start + candidate_rel
    low_price = float(c[low_idx])

    # Avoid a candidate that is too old to be useful.
    low_age = n - 1 - low_idx
    if low_age > 25:
        # Fall back to the most recent confirmed pivot low, if available.
        valid_lows = [i for i in lows if n - 1 - i <= 25]
        if valid_lows:
            low_idx = valid_lows[-1]
            low_price = float(c[low_idx])
            low_age = n - 1 - low_idx

    low_distance_pct = _pct(current, low_price)

    # Previous resistance BEFORE the candidate low.
    prior_highs = [i for i in highs if i < low_idx]
    prior_minor_high = float(c[prior_highs[-1]]) if prior_highs else np.nan

    # First HH: first confirmed pivot high after the low that clears
    # the pre-bottom minor high. If there is no prior high, use the
    # first post-low pivot high as a weaker reversal clue.
    hh_idx = None
    hh_price = np.nan
    post_low_highs = [i for i in highs if i > low_idx]
    for i in post_low_highs:
        if not np.isnan(prior_minor_high):
            if c[i] > prior_minor_high * 1.005:
                hh_idx, hh_price = i, float(c[i])
                break
        elif c[i] > low_price * 1.03:
            hh_idx, hh_price = i, float(c[i])
            break

    # First Higher Low after the first HH.
    hl_idx = None
    hl_price = np.nan
    if hh_idx is not None:
        post_hh_lows = [i for i in lows if i > hh_idx]
        for i in post_hh_lows:
            if c[i] > low_price * 1.01:
                hl_idx, hl_price = i, float(c[i])
                break

    # Second HH after the Higher Low.
    second_hh = False
    second_hh_idx = None
    second_hh_price = np.nan
    if hl_idx is not None:
        for i in highs:
            if i > hl_idx and c[i] > hh_price * 1.005:
                second_hh = True
                second_hh_idx = i
                second_hh_price = float(c[i])
                break

    # Recent resistance must EXCLUDE today's close; otherwise the current
    # price itself can make resistance distance = 0 and falsely penalize.
    pre_current = w.iloc[:-1]
    resistance = float(pre_current["CLOSE_PRICE"].tail(20).max())
    resistance_distance_pct = _pct(resistance, current)

    recent20_low = float(w["CLOSE_PRICE"].tail(20).min())
    recent20_high = float(w["CLOSE_PRICE"].tail(20).max())

    latest = g.iloc[-1]
    prev5 = g.tail(5)

    vol_ratio = float(latest.get("VOL_RATIO", np.nan))
    delivery = float(latest.get("DELIV_PER", 0))
    delivery_avg = float(latest.get("DELIV_AVG10", np.nan))
    ret5 = float(latest.get("RET_5D", np.nan))
    ret10 = float(latest.get("RET_10D", np.nan))
    atr_comp = bool(latest.get("ATR_COMPRESSION", False))
    ema20 = float(latest.get("EMA20", np.nan))
    ema50 = float(latest.get("EMA50", np.nan))
    rs20 = float(latest.get("RS_PROXY", np.nan))

    ema_distance_pct = abs(_pct(current, ema20)) if not np.isnan(ema20) else np.nan
    ema20_slope = (
        _pct(float(g["EMA20"].iloc[-1]), float(g["EMA20"].iloc[-6]))
        if len(g) >= 6 else np.nan
    )

    # 1) No lower-low: last 5 closes hold above candidate bottom.
    no_new_lower_low = float(prev5["CLOSE_PRICE"].min()) >= low_price * 0.995

    # 2) Low hold: close is above candidate low, but still close enough
    # to be considered early. Prefer 0-8%; allow up to configured 12%.
    bottom_hold = (
        current > low_price and
        low_distance_pct >= 0 and
        low_distance_pct <= MAX_DISTANCE_FROM_RECENT_LOW_PCT
    )

    # 3) Selling pressure is weakening when volume is not panic-high and
    # the latest 5-session range is holding the low.
    vol_panic = not np.isnan(vol_ratio) and vol_ratio > 2.5
    volume_build = not np.isnan(vol_ratio) and 0.90 <= vol_ratio <= 1.80
    delivery_build = (
        not np.isnan(delivery_avg) and delivery >= delivery_avg * 1.05
    )

    # 4) Momentum should be improving, but not already extended.
    rs_improving = not np.isnan(rs20) and rs20 > 0
    ema_improving = not np.isnan(ema20_slope) and ema20_slope > 0
    not_extended = (
        (np.isnan(ret5) or ret5 <= 7.0) and
        (np.isnan(ret10) or ret10 <= 12.0) and
        low_distance_pct <= MAX_DISTANCE_FROM_RECENT_LOW_PCT
    )

    # 5) Breakout already happened? If current is above prior resistance
    # by >1%, downgrade heavily; Hunter should find the move BEFORE it.
    already_breakout = (
        not np.isnan(resistance_distance_pct) and
        resistance_distance_pct < -1.0
    )

    score = 0
    reasons = []

    # Core structure carries the largest weight.
    if bottom_hold:
        score += 15
        reasons.append("Low holding")

    if no_new_lower_low:
        score += 15
        reasons.append("No lower-low")

    if hh_idx is not None:
        score += 18
        reasons.append("First Higher High")

    if hl_idx is not None:
        score += 27
        reasons.append("Higher Low")

    if second_hh:
        score += 8
        reasons.append("Second Higher High")

    # Supporting evidence.
    if volume_build and not vol_panic:
        score += 5
        reasons.append("Selling pressure easing")

    if delivery_build:
        score += 4
        reasons.append("Delivery improving")

    if atr_comp:
        score += 3
        reasons.append("Range contracting")

    if rs_improving:
        score += 3
        reasons.append("RS improving")

    if ema_improving:
        score += 2
        reasons.append("EMA slope improving")

    if not_extended:
        score += 5
        reasons.append("Not extended")

    # Penalties: protect against false bottoms / late entries.
    if vol_panic:
        score -= 10
        reasons.append("Panic volume")

    if not no_new_lower_low:
        score -= 20
        reasons.append("Lower-low risk")

    if already_breakout:
        score -= 25
        reasons.append("Already above resistance")

    if not not_extended:
        score -= 20
        reasons.append("Already extended")

    # If current is extremely close to the old resistance, it is less of
    # an early entry even though the structure may be strong.
    if (
        not np.isnan(resistance_distance_pct) and
        0 <= resistance_distance_pct < MIN_RESISTANCE_DISTANCE_PCT
    ):
        score -= 5
        reasons.append("At resistance")

    score = int(max(0, min(100, round(score))))

    # Stage priority is intentionally EARLY-first.
    if hl_idx is not None and not already_breakout and not_extended:
        stage = "HIGHER-LOW HUNTER"
    elif hh_idx is not None and not already_breakout and not_extended:
        stage = "FIRST REVERSAL"
    elif bottom_hold and no_new_lower_low and not already_breakout:
        stage = "BOTTOM FORMING"
    elif second_hh and not already_breakout:
        stage = "EARLY TREND"
    else:
        stage = "WATCH"

    # Trigger is the next structural confirmation, not a generic breakout.
    if hl_idx is not None:
        trigger = hh_price * 1.002
    elif hh_idx is not None:
        trigger = hh_price * 1.002
    else:
        trigger = resistance * 1.002

    invalidation = low_price * 0.995

    # Entry-zone distance from Higher Low where available.
    hl_distance_pct = (
        _pct(current, hl_price) if not np.isnan(hl_price) else np.nan
    )

    return {
        "SYMBOL": latest["SYMBOL"],
        "DATE": latest["DATE"].strftime("%d-%b-%Y"),
        "CMP": round(current, 2),
        "RECENT_LOW": round(low_price, 2),
        "LOW_AGE_DAYS": int(low_age),
        "LOW_DISTANCE_PCT": round(low_distance_pct, 2),
        "FIRST_HH": round(hh_price, 2) if not np.isnan(hh_price) else "",
        "HIGHER_LOW": round(hl_price, 2) if not np.isnan(hl_price) else "",
        "HL_DISTANCE_PCT": round(hl_distance_pct, 2) if not np.isnan(hl_distance_pct) else "",
        "SECOND_HH": round(second_hh_price, 2) if not np.isnan(second_hh_price) else "",
        "STRUCTURE": (
            "LOW → HH → HL → HH" if second_hh else
            "LOW → HH → HL" if hl_idx is not None else
            "LOW → HH" if hh_idx is not None else
            "LOW HOLD" if bottom_hold else
            "NO CONFIRMATION"
        ),
        "RESISTANCE": round(resistance, 2),
        "RESISTANCE_DISTANCE_PCT": round(resistance_distance_pct, 2),
        "VOLUME_RATIO": round(vol_ratio, 2) if not np.isnan(vol_ratio) else "",
        "DELIVERY_PCT": round(delivery, 2),
        "DELIVERY_AVG10": round(delivery_avg, 2) if not np.isnan(delivery_avg) else "",
        "RET_5D_PCT": round(ret5, 2) if not np.isnan(ret5) else "",
        "RET_10D_PCT": round(ret10, 2) if not np.isnan(ret10) else "",
        "EMA20": round(ema20, 2) if not np.isnan(ema20) else "",
        "EMA50": round(ema50, 2) if not np.isnan(ema50) else "",
        "EMA20_SLOPE_PCT": round(ema20_slope, 2) if not np.isnan(ema20_slope) else "",
        "EMA_DISTANCE_PCT": round(ema_distance_pct, 2) if not np.isnan(ema_distance_pct) else "",
        "RS20_PCT": round(rs20, 2) if not np.isnan(rs20) else "",
        "ATR_COMPRESSION": "YES" if atr_comp else "NO",
        "STAGE": stage,
        "HUNTER_SCORE": score,
        "TRIGGER": round(float(trigger), 2) if not np.isnan(trigger) else "",
        "INVALIDATION": round(float(invalidation), 2),
        "REASONS": ", ".join(reasons),
    }

# =========================================================
# BUILD HUNTER LIST
# =========================================================
results = []

for symbol, g in hist.groupby("SYMBOL"):
    try:
        item = analyze_stock(g)
        if item and item["HUNTER_SCORE"] >= MIN_SCORE:
            results.append(item)
    except Exception as e:
        print(f"Analysis error {symbol}: {e}")

hunter = pd.DataFrame(results)

if hunter.empty:
    hunter = pd.DataFrame(columns=[
        "RANK", "SYMBOL", "DATE", "CMP", "RECENT_LOW", "LOW_AGE_DAYS",
        "LOW_DISTANCE_PCT", "FIRST_HH", "HIGHER_LOW", "HL_DISTANCE_PCT",
        "SECOND_HH", "STRUCTURE", "RESISTANCE", "RESISTANCE_DISTANCE_PCT",
        "VOLUME_RATIO", "DELIVERY_PCT", "DELIVERY_AVG10",
        "RET_5D_PCT", "RET_10D_PCT", "EMA20", "EMA50", "EMA20_SLOPE_PCT",
        "EMA_DISTANCE_PCT", "RS20_PCT", "ATR_COMPRESSION", "STAGE",
        "HUNTER_SCORE", "TRIGGER", "INVALIDATION", "REASONS"
    ])
else:
    # Strongest early structure first, then highest score.
    stage_order = {
        "HIGHER-LOW HUNTER": 5,
        "FIRST REVERSAL": 4,
        "BOTTOM FORMING": 3,
        "EARLY TREND": 2,
        "WATCH": 0,
    }
    hunter["_stage_order"] = hunter["STAGE"].map(stage_order).fillna(0)
    hunter = hunter.sort_values(
        ["_stage_order", "HUNTER_SCORE", "LOW_DISTANCE_PCT"],
        ascending=[False, False, True]
    ).drop(columns=["_stage_order"])
    hunter.insert(0, "RANK", range(1, len(hunter) + 1))

# =========================================================
# UPDATE ORIGINAL TWO SHEETS
# =========================================================
latest_day = hist[hist["DATE"] == latest_date].copy()

df_vol = latest_day.sort_values(
    "TTL_TRD_QNTY", ascending=False
).head(250)

df_turnover = latest_day.sort_values(
    "TURNOVER_LACS", ascending=False
).head(250)

cols_out_vol = ["SYMBOL", "TTL_TRD_QNTY", "CLOSE_PRICE"]
cols_out_turnover = [
    "SYMBOL", "TTL_TRD_QNTY", "CLOSE_PRICE",
    "TURNOVER_LACS", "DELIV_QTY", "DELIV_PER"
]

def ensure_min_cols(worksheet, min_cols):
    if worksheet.col_count < min_cols:
        worksheet.add_cols(min_cols - worksheet.col_count)

ensure_min_cols(ws_volume, 12)
ensure_min_cols(ws_turnover, 22)

ws_volume.batch_clear(["A2:C251"])
ws_volume.update(
    range_name="A2",
    values=df_vol[cols_out_vol].values.tolist()
)

ws_turnover.batch_clear(["A2:F251"])
ws_turnover.update(
    range_name="A2",
    values=df_turnover[cols_out_turnover].values.tolist()
)

ist_now = (
    datetime.utcnow() + timedelta(hours=5, minutes=30)
).strftime("%d-%b %H:%M")

status_msg = (
    f"Data Date: {latest_date:%d-%b-%Y} | "
    f"Last Update: {ist_now} (IST)"
)

ws_volume.update(range_name="L2", values=[[status_msg]])
ws_turnover.update(range_name="V2", values=[[status_msg]])

# =========================================================
# UPDATE EARLY HUNTER SHEET
# =========================================================
headers = list(hunter.columns)

# Make enough rows/columns
ensure_min_cols(ws_hunter, len(headers))

if ws_hunter.row_count < max(1000, len(hunter) + 10):
    ws_hunter.add_rows(max(1000, len(hunter) + 10) - ws_hunter.row_count)

ws_hunter.clear()

ws_hunter.update(
    range_name="A1",
    values=[headers] + hunter.astype(object).where(
        pd.notna(hunter), ""
    ).values.tolist()
)

# Freeze header row and basic formatting
try:
    ws_hunter.freeze(rows=1)
    last_col_letter = chr(64 + min(len(headers), 26))
    ws_hunter.format(f"A1:{last_col_letter}1", {
        "textFormat": {"bold": True},
        "horizontalAlignment": "CENTER"
    })
except Exception as e:
    print(f"Formatting warning: {e}")

print("=" * 70)
print("SUCCESS")
print(f"NSE data date       : {latest_date:%d-%b-%Y}")
print(f"Early Hunter count  : {len(hunter)}")
if not hunter.empty:
    print("TOP 10 EARLY HUNTERS:")
    print(
        hunter[
            ["RANK", "SYMBOL", "CMP", "STRUCTURE",
             "HUNTER_SCORE", "TRIGGER", "INVALIDATION"]
        ].head(10).to_string(index=False)
    )
print("=" * 70)

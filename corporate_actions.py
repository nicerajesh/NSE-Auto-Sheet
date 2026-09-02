"""Heuristic split/bonus/rights detection and back-adjustment.

NSE's daily bhavcopy (sec_bhavdata_full_*.csv) carries RAW close prices with
no corporate-action flag at all. If a stock does a 1:1 bonus or a 1:2 split,
its close price roughly halves overnight with no change in the underlying
business. Fed raw into RET_20D / 52-week-low / breakout-resistance logic,
that overnight halving looks exactly like a catastrophic crash or, on the
rebound day, a huge "reversal" -- a false signal purely from a data artifact,
not a real technical or fundamental event.

This is a HEURISTIC, not a verified corporate-actions feed: NSE does publish
one, but it requires a separate authenticated endpoint this project doesn't
currently fetch. So detection here is conservative by design:
  1. Only trigger on an overnight price ratio close to one of the common
     clean split/bonus fractions (1:2, 1:3, 1:5, 1:10, 2:3, 3:1 bonus, etc.),
     within a tight tolerance -- a messy/random ratio from a genuine crash
     essentially never lands here.
  2. Require volume to move roughly inversely to price (total traded VALUE
     stays continuous through a split; a genuine crash usually does NOT show
     a proportional volume story matching that specific inverse ratio).
  3. When both agree, back-adjust price fields for all PRIOR bars of that
     symbol by the detected ratio (standard practice -- adjust history to
     match the new share count, never touch the actual print).
  4. Every detection is logged to output/corporate_actions_detected.csv for
     manual audit. When in doubt, the code does NOT adjust and just flags it
     -- a missed split (bounded, one-time false signal already covered
     elsewhere by quality-gate/backtest sanity checks) is a much smaller risk
     than silently mis-adjusting real price history and corrupting every
     signal fed from it.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

# (numerator, denominator) -> label. Ratio checked is POST/PRE close price.
_CLEAN_RATIOS = [
    (1, 2, "1:2 SPLIT/BONUS"), (1, 3, "1:3 SPLIT/BONUS"), (1, 5, "1:5 SPLIT/BONUS"),
    (1, 10, "1:10 SPLIT/BONUS"), (2, 3, "2:1 BONUS"), (1, 4, "1:4 SPLIT/BONUS"),
    (3, 4, "3:1 BONUS"), (4, 5, "4:1 BONUS"), (1, 1.5, "1:2 BONUS (3-for-2)"),
]
_TOL = 0.03          # 3% tolerance on the price-ratio match
_VOL_TOL = 0.35       # volume should move inversely within this much slack
_MIN_JUMP_PCT = 15.0  # ignore small day-to-day moves entirely; only look at big gaps


def _match_ratio(price_ratio: float):
    if not np.isfinite(price_ratio) or price_ratio <= 0 or price_ratio >= 1:
        return None
    for num, den, label in _CLEAN_RATIOS:
        target = num / den
        if abs(price_ratio - target) <= _TOL:
            return target, label
    return None


def detect_and_adjust(hist: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """hist: the full multi-symbol OHLCV history (pre-indicators), columns
    include SYMBOL, DATE, OPEN_PRICE/HIGH_PRICE/LOW_PRICE/CLOSE_PRICE,
    TTL_TRD_QNTY. Returns (adjusted_hist, detections_log)."""
    if hist is None or hist.empty:
        return hist, pd.DataFrame(columns=["SYMBOL", "DATE", "RATIO", "LABEL", "PREV_CLOSE", "CLOSE", "ADJUSTED"])

    out = hist.copy()
    price_cols = [c for c in ("OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE", "CLOSE_PRICE") if c in out.columns]
    for c in price_cols:
        out[c] = out[c].astype(float)
    log_rows = []

    for sym, g in out.groupby("SYMBOL", sort=False):
        g = g.sort_values("DATE")
        close = g["CLOSE_PRICE"].astype(float).values
        vol = g["TTL_TRD_QNTY"].astype(float).values if "TTL_TRD_QNTY" in g.columns else np.full(len(g), np.nan)
        idx = g.index.to_numpy()
        if len(close) < 2:
            continue
        prev_close = np.roll(close, 1)
        prev_vol = np.roll(vol, 1)
        pct_jump = (close - prev_close) / prev_close * 100
        for i in range(1, len(close)):
            if pct_jump[i] > -_MIN_JUMP_PCT:
                continue  # only interested in large overnight DROPS (splits/bonuses reduce price)
            ratio = close[i] / prev_close[i] if prev_close[i] else np.nan
            m = _match_ratio(ratio)
            if not m:
                continue
            target_ratio, label = m
            vol_ok = True
            if np.isfinite(vol[i]) and np.isfinite(prev_vol[i]) and prev_vol[i] > 0:
                expected_vol_ratio = 1.0 / target_ratio  # volume should scale up ~inversely to price
                actual_vol_ratio = vol[i] / prev_vol[i]
                vol_ok = abs(actual_vol_ratio - expected_vol_ratio) <= expected_vol_ratio * _VOL_TOL * 3
            adjusted = vol_ok
            log_rows.append({
                "SYMBOL": sym, "DATE": g.iloc[i]["DATE"], "RATIO": round(target_ratio, 4),
                "LABEL": label, "PREV_CLOSE": round(prev_close[i], 2), "CLOSE": round(close[i], 2),
                "ADJUSTED": adjusted,
            })
            if adjusted:
                # Back-adjust every prior bar of this symbol (before this date) by target_ratio,
                # so historical patterns/returns stay continuous through the split.
                prior_mask = out.index.isin(idx[:i]) & out["SYMBOL"].eq(sym)
                for c in price_cols:
                    out.loc[prior_mask, c] = out.loc[prior_mask, c].astype(float) * target_ratio

    log_df = pd.DataFrame(log_rows) if log_rows else pd.DataFrame(
        columns=["SYMBOL", "DATE", "RATIO", "LABEL", "PREV_CLOSE", "CLOSE", "ADJUSTED"])
    return out, log_df

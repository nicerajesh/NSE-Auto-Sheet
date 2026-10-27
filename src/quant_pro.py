"""RY APEX MATRIX Quant Pro V43.

Rule-based swing-trading research layer built on the existing NSE OHLCV pipeline.
Not a black-box predictor; no profit guarantee. Market regime uses an equal-weight
universe proxy, NOT the NIFTY index.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from config import CFG

MIN_SCORE = 75.0
BREAKOUT_VOL = 1.50
BREAKOUT_BUFFER_PCT = 0.20
STOP_ATR = 2.0
T1_R, T2_R, T3_R = 2.0, 4.0, 6.0
MAX_HOLD = 90
MAX_GAP_PCT = 2.0
ROUND_TRIP_COST_PCT = 0.35


def add_quant_pro_features(features: pd.DataFrame) -> pd.DataFrame:
    """Add point-in-time cross-sectional scores and an explicitly labelled market proxy."""
    if features is None or features.empty:
        return features.copy() if features is not None else pd.DataFrame()
    f = features.copy()
    required = {"SYMBOL", "DATE", "OPEN", "HIGH", "LOW", "CLOSE", "VOLUME", "ATR", "EMA20", "EMA50",
                "EMA200", "RSI", "VOL_RATIO", "RANK60", "MOM_RANK", "EMA50_UP", "LOW3", "CLOSE_LOC",
                "BODY_PCT", "TURNOVER_CR", "HH20"}
    missing = required - set(f.columns)
    if missing:
        raise ValueError(f"Quant Pro missing required feature columns: {sorted(missing)}")
    f = f.sort_values(["SYMBOL", "DATE"]).reset_index(drop=True)
    f["QP_PREV_CLOSE"] = f.groupby("SYMBOL", sort=False)["CLOSE"].shift(1)
    f["QP_DAILY_RETURN"] = f["CLOSE"] / f["QP_PREV_CLOSE"] - 1.0

    # Median daily return across available symbols: a transparent proxy, not an index.
    daily = f.groupby("DATE", sort=True)["QP_DAILY_RETURN"].median().to_frame("QP_PROXY_RETURN")
    breadth = f.assign(_ABOVE200=f["CLOSE"] > f["EMA200"]).groupby("DATE")["_ABOVE200"].mean()
    daily["QP_BREADTH200"] = breadth
    daily["QP_PROXY_CLOSE"] = (1.0 + daily["QP_PROXY_RETURN"].fillna(0.0)).cumprod()
    daily["QP_PROXY_EMA50"] = daily["QP_PROXY_CLOSE"].ewm(span=50, adjust=False, min_periods=30).mean()
    daily["QP_PROXY_EMA200"] = daily["QP_PROXY_CLOSE"].ewm(span=200, adjust=False, min_periods=100).mean()
    daily["QP_MARKET_REGIME"] = np.select(
        [(daily["QP_PROXY_CLOSE"] > daily["QP_PROXY_EMA200"]) & (daily["QP_BREADTH200"] >= 0.50),
         (daily["QP_PROXY_CLOSE"] > daily["QP_PROXY_EMA200"]) | (daily["QP_BREADTH200"] >= 0.50)],
        ["BULLISH_PROXY", "NEUTRAL_PROXY"], default="DEFENSIVE_PROXY")
    f = f.merge(daily.reset_index(), on="DATE", how="left", validate="many_to_one")

    f["QP_TREND"] = (f["CLOSE"] > f["EMA200"]) & (f["EMA50"] > f["EMA200"]) & f["EMA50_UP"]
    f["QP_BREAKOUT"] = (
        f["QP_TREND"] & (f["CLOSE"] > f["HH20"] * (1 + BREAKOUT_BUFFER_PCT / 100))
        & (f["VOL_RATIO"] >= BREAKOUT_VOL) & (f["CLOSE_LOC"] >= 0.65)
        & (f["BODY_PCT"] >= 0.40) & (f["CLOSE"] > f["OPEN"])
        & (f["CLOSE"] <= f["EMA20"] * 1.12))
    f["QP_PULLBACK"] = (
        f["QP_TREND"] & (f["MOM_RANK"] >= 70) & (f["RANK60"] >= 70)
        & (f["LOW3"] <= f["EMA20"] * 1.01) & (f["CLOSE"] > f["EMA20"])
        & (f["CLOSE"] > f["OPEN"]) & f["RSI"].between(40, 65) & (f["VOL_RATIO"] >= 0.80))
    f["QP_SETUP"] = np.select([f["QP_BREAKOUT"], f["QP_PULLBACK"]], ["BREAKOUT", "PULLBACK"], default="")

    # Quality score is a ranking aid, not a probability of winning.
    f["QP_SCORE_TREND"] = np.select([f["QP_TREND"] & (f["CLOSE"] > f["EMA20"]), f["QP_TREND"]], [25, 18], default=0)
    f["QP_SCORE_RS"] = np.select([f["MOM_RANK"] >= 90, f["MOM_RANK"] >= 80, f["MOM_RANK"] >= 70], [20, 16, 12], default=0)
    f["QP_SCORE_SETUP"] = np.select([f["QP_BREAKOUT"], f["QP_PULLBACK"]], [20, 16], default=0)
    f["QP_SCORE_VOLUME"] = np.select([f["VOL_RATIO"] >= 2.0, f["VOL_RATIO"] >= BREAKOUT_VOL, f["VOL_RATIO"] >= 1.0], [10, 8, 5], default=0)
    f["QP_SCORE_LIQUIDITY"] = np.select(
        [f["TURNOVER_CR"] >= 25, f["TURNOVER_CR"] >= 10, f["TURNOVER_CR"] >= CFG.min_turnover_cr],
        [5, 4, 2], default=0)
    f["QP_HH55"] = f.groupby("SYMBOL", sort=False)["HIGH"].transform(
        lambda s: s.shift(1).rolling(55, min_periods=40).max())
    f["QP_HEADROOM_R"] = np.where(
        f["QP_HH55"].notna() & (f["QP_HH55"] > f["CLOSE"]) & (f["ATR"] > 0),
        (f["QP_HH55"] - f["CLOSE"]) / (STOP_ATR * f["ATR"]), 99.0)
    f["QP_SCORE_RR"] = np.select([f["QP_HEADROOM_R"] >= 2, f["QP_HEADROOM_R"] >= 1], [10, 5], default=0)
    f["QP_ATR_PCT"] = f["ATR"] / f["CLOSE"] * 100
    f["QP_SCORE_VOLATILITY"] = np.select(
        [f["QP_ATR_PCT"].between(1, 5), f["QP_ATR_PCT"].between(0.5, 7)], [5, 3], default=0)
    f["QP_SCORE_REGIME"] = np.select(
        [f["QP_MARKET_REGIME"] == "BULLISH_PROXY", f["QP_MARKET_REGIME"] == "NEUTRAL_PROXY"], [5, 2], default=0)
    score_cols = ["QP_SCORE_TREND", "QP_SCORE_RS", "QP_SCORE_SETUP", "QP_SCORE_VOLUME",
                  "QP_SCORE_LIQUIDITY", "QP_SCORE_RR", "QP_SCORE_VOLATILITY", "QP_SCORE_REGIME"]
    f["QP_SCORE"] = f[score_cols].sum(axis=1).clip(0, 100)
    f["QP_SIGNAL"] = (
        f["QP_SETUP"].ne("") & (f["QP_SCORE"] >= MIN_SCORE)
        & (f["QP_MARKET_REGIME"] != "DEFENSIVE_PROXY")
        & (f["TURNOVER_CR"] >= CFG.min_turnover_cr)
        & (f["ATR"] > 0) & f["QP_ATR_PCT"].between(1, 7))
    f["QP_STOP"] = f["CLOSE"] - STOP_ATR * f["ATR"]
    f["QP_RISK_PCT"] = (f["CLOSE"] - f["QP_STOP"]) / f["CLOSE"] * 100
    f["QP_T1"] = f["CLOSE"] + T1_R * (f["CLOSE"] - f["QP_STOP"])
    f["QP_T2"] = f["CLOSE"] + T2_R * (f["CLOSE"] - f["QP_STOP"])
    f["QP_T3"] = f["CLOSE"] + T3_R * (f["CLOSE"] - f["QP_STOP"])
    return f


def latest_quant_pro_candidates(features: pd.DataFrame) -> pd.DataFrame:
    if features is None or features.empty:
        return pd.DataFrame()
    asof = features["DATE"].max()
    d = features[(features["DATE"] == asof) & features["QP_SIGNAL"]].copy()
    if d.empty:
        return d
    d = d.sort_values(["QP_SCORE", "MOM_RANK", "TURNOVER_CR"], ascending=False)
    d["QP_ENTRY_REF"] = d["CLOSE"]
    d["QP_MAX_BUY"] = d["CLOSE"] * (1 + MAX_GAP_PCT / 100)
    return d.reset_index(drop=True)


def position_size_quant_pro(entry_ref: float, stop: float, size_mult: float = 1.0) -> dict:
    risk_per_share = float(entry_ref) - float(stop)
    if not np.isfinite(risk_per_share) or risk_per_share <= 0 or not np.isfinite(entry_ref) or entry_ref <= 0:
        return {"QTY": 0, "CAPITAL_USED": 0.0, "RISK_AMT": 0.0}
    risk_amt = CFG.capital * CFG.risk_per_trade_pct / 100 * size_mult
    qty_by_risk = int(np.floor(risk_amt / risk_per_share))
    qty_by_capital = int(np.floor(CFG.capital * CFG.max_single_position_pct / 100 / entry_ref))
    qty = max(0, min(qty_by_risk, qty_by_capital))
    return {"QTY": qty, "CAPITAL_USED": round(qty * entry_ref, 2), "RISK_AMT": round(qty * risk_per_share, 2)}


def simulate_quant_pro_trade(o, h, l, c, entry_idx: int, stop0: float, signal_close: float | None = None) -> dict | None:
    """Conservative OHLC simulation: next-open entry; stop checked before target ratchet."""
    n = len(o)
    if entry_idx >= n:
        return None
    fill = float(o[entry_idx])
    if not np.isfinite(fill) or fill <= stop0:
        return None
    if signal_close is not None and signal_close > 0 and (fill / signal_close - 1) * 100 > MAX_GAP_PCT:
        return None
    risk = fill - stop0
    if risk <= 0:
        return None
    stop, hi = float(stop0), fill
    end = min(n, entry_idx + MAX_HOLD)
    for j in range(entry_idx, end):
        if float(l[j]) <= stop:
            px = min(float(o[j]), stop) if np.isfinite(o[j]) else stop
            return {"closed": True, "exit_idx": j, "exit_px": px, "fill": fill, "stop_now": stop,
                    "risk": risk, "reason": "STOP" if stop == stop0 else "TRAILING SL"}
        hi = max(hi, float(h[j]))
        if hi >= fill + T3_R * risk:
            stop = max(stop, fill + T2_R * risk)
        elif hi >= fill + T2_R * risk:
            stop = max(stop, fill + T1_R * risk)
        elif hi >= fill + T1_R * risk:
            stop = max(stop, fill)
    if entry_idx + MAX_HOLD <= n:
        j = entry_idx + MAX_HOLD - 1
        return {"closed": True, "exit_idx": j, "exit_px": float(c[j]), "fill": fill, "stop_now": stop,
                "risk": risk, "reason": "TIME EXIT"}
    return {"closed": False, "exit_idx": n - 1, "exit_px": float(c[-1]), "fill": fill, "stop_now": stop,
            "risk": risk, "reason": "OPEN"}


def run_quant_pro_backtest(features: pd.DataFrame) -> pd.DataFrame:
    """One trade at a time per symbol; signal at close, entry next open, transaction costs included."""
    rows: list[dict] = []
    if features is None or features.empty:
        return pd.DataFrame()
    for sym, d in features.sort_values("DATE").groupby("SYMBOL", sort=False):
        d = d.reset_index(drop=True)
        dates = d["DATE"].values
        sig = d["QP_SIGNAL"].fillna(False).to_numpy(dtype=bool)
        o, h, l, c = (d[x].to_numpy(dtype=float) for x in ("OPEN", "HIGH", "LOW", "CLOSE"))
        atr = d["ATR"].to_numpy(dtype=float)
        score, setup = d["QP_SCORE"].to_numpy(dtype=float), d["QP_SETUP"].to_numpy()
        last_exit, i = -1, 0
        while i < len(d) - 1:
            if not sig[i] or i <= last_exit or not np.isfinite(atr[i]) or atr[i] <= 0:
                i += 1
                continue
            stop0 = c[i] - STOP_ATR * atr[i]
            sim = simulate_quant_pro_trade(o, h, l, c, i + 1, stop0, signal_close=c[i])
            if sim is None:
                i += 1
                continue
            if not sim["closed"]:
                i += 1
                continue
            raw_ret = (sim["exit_px"] / sim["fill"] - 1) * 100
            net_ret = raw_ret - ROUND_TRIP_COST_PCT
            risk = sim["fill"] - stop0
            rows.append({
                "SYMBOL": sym, "SIGNAL_DATE": pd.Timestamp(dates[i]), "ENTRY_DATE": pd.Timestamp(dates[i + 1]),
                "EXIT_DATE": pd.Timestamp(dates[sim["exit_idx"]]), "SETUP": setup[i], "SCORE": round(float(score[i]), 1),
                "ENTRY": round(float(sim["fill"]), 4), "INITIAL_STOP": round(float(stop0), 4),
                "EXIT": round(float(sim["exit_px"]), 4), "EXIT_REASON": sim["reason"],
                "GROSS_RETURN_PCT": round(raw_ret, 4), "NET_RETURN_PCT": round(net_ret, 4),
                "R_MULTIPLE_NET": round((net_ret / 100 * sim["fill"]) / risk, 4),
                "HOLD_SESSIONS": int(sim["exit_idx"] - i),
            })
            last_exit = int(sim["exit_idx"])
            i = last_exit + 1
    out = pd.DataFrame(rows)
    return out.sort_values(["EXIT_DATE", "SYMBOL"]).reset_index(drop=True) if not out.empty else out



def summarize_quant_pro_by_year(trades: pd.DataFrame) -> pd.DataFrame:
    """Yearly closed-trade summaries. This is not a portfolio-level concurrent-position backtest."""
    if trades is None or trades.empty:
        return pd.DataFrame(columns=["YEAR", "trades", "win_pct", "avg_net_pct", "profit_factor", "max_drawdown_pct"])
    t = trades.copy()
    t["EXIT_DATE"] = pd.to_datetime(t["EXIT_DATE"], errors="coerce")
    rows = []
    for year, group in t.dropna(subset=["EXIT_DATE"]).groupby(t["EXIT_DATE"].dt.year):
        rows.append({"YEAR": int(year), **summarize_quant_pro(group)})
    return pd.DataFrame(rows).sort_values("YEAR").reset_index(drop=True) if rows else pd.DataFrame()


def summarize_quant_pro_periods(trades: pd.DataFrame, split_year: int = 2024) -> pd.DataFrame:
    """Time-split diagnostic. Treat 2024+ as a later-period check, not a pristine holdout."""
    if trades is None or trades.empty:
        return pd.DataFrame(columns=["PERIOD", "trades", "win_pct", "avg_net_pct", "profit_factor", "max_drawdown_pct"])
    t = trades.copy()
    t["EXIT_DATE"] = pd.to_datetime(t["EXIT_DATE"], errors="coerce")
    periods = [
        (f"EARLIER_THAN_{split_year}", t[t["EXIT_DATE"].dt.year < split_year]),
        (f"{split_year}_ONWARD_DIAGNOSTIC", t[t["EXIT_DATE"].dt.year >= split_year]),
    ]
    return pd.DataFrame([{"PERIOD": label, **summarize_quant_pro(group)} for label, group in periods])


def summarize_quant_pro(trades: pd.DataFrame) -> dict:
    if trades is None or trades.empty:
        return {"trades": 0, "win_pct": np.nan, "avg_net_pct": np.nan, "profit_factor": np.nan, "max_drawdown_pct": np.nan}
    ret = pd.to_numeric(trades["NET_RETURN_PCT"], errors="coerce").dropna()
    wins, losses = ret[ret > 0].sum(), -ret[ret < 0].sum()
    equity = (1 + ret / 100).cumprod()
    dd = (equity / equity.cummax() - 1) * 100
    return {
        "trades": int(len(ret)), "win_pct": round(float((ret > 0).mean() * 100), 2),
        "avg_net_pct": round(float(ret.mean()), 4),
        "profit_factor": round(float(wins / losses), 4) if losses > 0 else (float("inf") if wins > 0 else np.nan),
        "max_drawdown_pct": round(float(dd.min()), 4),
    }

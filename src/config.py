"""Saari settings ek jagah. Env variable se override ho sakti hain (GitHub -> Settings -> Variables)."""
from __future__ import annotations
import os
from dataclasses import dataclass


def _env(name: str, default):
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return type(default)(raw)


@dataclass(frozen=True)
class Config:
    # ---------------- data ----------------
    history_start: str = "2018-06-01"      # deep history: indicators warm-up + 7 saal ka backtest
    min_bars: int = 300                    # isse kam history wale stock ignore
    min_turnover_cr: float = 5.0           # 20-din avg turnover >= Rs 5 crore (tradable liquidity)
    jump_pct: float = 0.30                 # 1-din me 30%+ move = corporate action / bad data -> stock skip
    stale_sessions: int = 3                # data itna purana ho to BUY publish nahi hoga

    # ---------------- signal (backtest me test hua) ----------------
    mom_lookback: int = 252                # 12-1 month momentum: close[t-21] / close[t-252]
    mom_skip: int = 21
    mom_min_rank: float = 90.0             # sirf top 10% momentum stocks
    rs60_min_rank: float = 70.0            # pullback setup ke liye 60-din RS rank
    breakout_vol_ratio: float = 1.5
    breakout_close_loc: float = 0.65
    breakout_max_ext: float = 1.12         # close < EMA20 * 1.12 (chase mat karo)

    # ---------------- trade plan ----------------
    stop_atr: float = 2.0                  # SL = close - 2 x ATR14
    t1_r: float = 2.0                      # T1 = +2R   (SL -> entry)
    t2_r: float = 4.0                      # T2 = +4R   (SL -> T1)
    t3_r: float = 6.0                      # T3 = +6R   (SL -> T2)
    max_hold: int = 90                     # sessions
    max_gap_pct: float = 2.0               # next open signal close se 2% upar ho to trade skip
    min_risk_pct: float = 2.0
    max_risk_pct: float = 10.0
    cost_pct: float = 0.35                 # round-trip brokerage + slippage assumption
    signal_gap: int = 10                   # ek stock par 2 signal ke beech min sessions

    # ---------------- position sizing ----------------
    capital: float = _env("CAPITAL_BASE", 1_000_000.0)
    risk_per_trade_pct: float = _env("RISK_PER_TRADE_PCT", 0.5)
    max_positions: int = _env("MAX_CONCURRENT_POSITIONS", 12)
    max_single_position_pct: float = _env("MAX_SINGLE_POSITION_PCT", 15.0)
    max_new_per_day: int = _env("MAX_NEW_PER_DAY", 5)
    watch_rows: int = 10

    # ---------------- honesty gates ----------------
    edge_min_trades: int = 300             # full-history backtest me itne trades
    edge_min_pf: float = 1.15              # aur itna profit factor, warna BUY band
    health_window_days: int = 120          # recent-performance window (health throttle)
    health_min_trades: int = 30
    health_size_mult: float = 0.5          # recent expectancy <= 0 ho to size aadha

    # ---------------- sheets ----------------
    spreadsheet_id: str = _env("SPREADSHEET_ID", "1U9j5fMZAWPUSwoP_U-GKdacVke9nUjspqPR3wGsWAUM")
    action_tab: str = "ACTION PLAN"
    status_tab: str = "SYSTEM STATUS"
    history_source_base: str = _env(
        "HISTORY_SOURCE_BASE",
        "https://raw.githubusercontent.com/BennyThadikaran/eod2_data/main/daily/",
    )


CFG = Config()

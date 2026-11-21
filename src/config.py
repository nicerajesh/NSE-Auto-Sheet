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
    adx_min: float = 25.0                  # trend strength; ADX>=25 filter real-data test me PF 1.85->2.2 (full-history) tha
    mom_min_rank_loose: float = 50.0       # WATCH tier: top-50% momentum (strict ka top-10% nahi)
    adx_min_loose: float = 15.0            # WATCH tier: dhili ADX seema - roz signal dene ke liye, par PF ~1.7 (strict se kam)
    max_watch_per_day: int = 5             # WATCH BUY list itni lambi tak dikhao

    # ---------------- V38 tier (Rajesh ke Pine Script se, hoobehoo) ----------------
    v38_vol_mult: float = 1.30             # Strong Breakout volume multiplier (V38 default)
    v38_early_vol_mult: float = 1.10       # Early Breakout volume multiplier (V38 default)
    v38_breakout_buffer_pct: float = 0.10  # Breakout Buffer % (V38 default)
    v38_atr_mult: float = 2.5              # trailing SL = close - 2.5*ATR, roz ratchet (V38 default)
    v38_t1_r: float = 2.0                  # T1 dikhane ke liye (V38 me SL ratchet ko affect nahi karta)
    v38_t2_r: float = 3.0                  # T2 dikhane ke liye (V38 me SL ratchet ko affect nahi karta)
    v38_size_mult: float = 0.35            # bina trend/momentum/ADX filter -> sabse kam tested tier, size sabse chhota
    v42_size_mult: float = 0.25            # V42 backtest PF sabse kam (~1.19) - size sabse chhota
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
    max_open_risk_pct: float = _env("MAX_OPEN_RISK_PCT", 6.0)   # sab open positions ka total risk (SL tak) capital ka itna % se zyada nahi
    stage_pct: float = _env("SIZE_STAGE_PCT", 25.0)             # real money ka stage: 25 -> normal size ka 25% se shuru karo
    dd_guard_pct: float = _env("DD_GUARD_PCT", 8.0)             # open positions ka unrealized loss capital ka itna % ho to naye BUY band

    # ---------------- honesty gates ----------------
    edge_min_trades: int = 300             # full-history backtest me itne trades
    edge_min_pf: float = 1.15              # aur itna profit factor, warna BUY band
    oos_start: str = "2023-01-01"           # walk-forward: is date ke baad ke trades 'out-of-sample' maane jaate hain
    oos_min_trades: int = 50
    oos_min_pf: float = 1.0                # OOS PF isse neeche -> BUY band
    health_window_days: int = 120          # recent-performance window (health throttle)
    health_min_trades: int = 30
    health_size_mult: float = 0.5          # recent expectancy <= 0 ho to size aadha

    # ---------------- DELIVERY (monthly momentum rotation) ----------------
    delivery_capital: float = _env("DELIVERY_CAPITAL", 500_000.0)    # delivery/positional ke liye alag capital
    delivery_top_n: int = 20               # BUY zone: momentum rank 1..20
    delivery_hold_n: int = 40              # HOLD zone: rank 21..40 (isse bahar -> exit)
    delivery_min_turnover_cr: float = 10.0
    delivery_atr_mult: float = 3.5         # disaster SL = close - 3.5 ATR
    delivery_min_risk_pct: float = 8.0
    delivery_max_risk_pct: float = 20.0
    delivery_risk_pct: float = _env("DELIVERY_RISK_PCT", 0.4)       # ek position par capital ka max risk %

    # ---------------- INTRADAY (Angel One SmartAPI, 5-min ORB + VWAP) ----------------
    intraday_capital: float = _env("INTRADAY_CAPITAL", 200_000.0)
    intraday_risk_pct: float = _env("INTRADAY_RISK_PCT", 0.25)      # ek trade par capital ka max risk %
    intraday_max_leverage: float = _env("INTRADAY_MAX_LEVERAGE", 3.0)
    intraday_max_trades: int = 3           # din me max signals
    intraday_orb_minutes: int = 15         # opening range = 09:15-09:30
    intraday_bar_minutes: int = 5
    intraday_entry_cutoff: str = "11:30"   # iske baad naya signal nahi
    intraday_square_off: str = "15:15"     # sab position band
    intraday_vol_mult: float = 1.5         # breakout bar volume >= 1.5x din ke ab tak ke avg bar volume
    intraday_breakout_buf_pct: float = 0.05
    intraday_min_or_pct: float = 0.25      # opening range % of price: isse patli = noise
    intraday_max_or_pct: float = 1.5       # isse chaudi = pehle hi move ho chuka
    intraday_min_stop_pct: float = 0.4
    intraday_max_stop_pct: float = 1.0
    intraday_t1_r: float = 1.0
    intraday_t2_r: float = 2.0
    intraday_t3_r: float = 3.0             # T3 par poora exit
    intraday_cost_pct: float = 0.12        # round-trip: STT + charges + slippage (assumption - apne broker se match karo)
    intraday_min_price: float = 100.0

    # ---------------- sheets ----------------
    spreadsheet_id: str = _env("SPREADSHEET_ID", "1U9j5fMZAWPUSwoP_U-GKdacVke9nUjspqPR3wGsWAUM")
    positions_tab: str = "MY POSITIONS"
    action_tab: str = "SWING"              # (pehle "ACTION PLAN") - swing report
    status_tab: str = "SYSTEM STATUS"
    delivery_tab: str = "DELIVERY"
    intraday_tab: str = "INTRADAY"
    publish_research_tabs: bool = _env("PUBLISH_RESEARCH_TABS", "0") == "1"   # RY / RY V38 / RY V42 (research-only)
    ry_tab: str = "RY"                     # ek-nazar quick view: aaj ka BUY/SELL, entry, SL, T1/T2/T3
    v38_tab: str = "RY V38"                # Pine Script V38 ke hoobehoo signal - alag sheet
    v42_tab: str = "RY V42"                # Pine Script V42 ke hoobehoo signal - alag sheet
    history_source_base: str = _env(
        "HISTORY_SOURCE_BASE",
        "https://raw.githubusercontent.com/BennyThadikaran/eod2_data/main/daily/",
    )


CFG = Config()

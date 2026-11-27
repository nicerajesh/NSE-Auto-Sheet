from dataclasses import dataclass
import os
@dataclass(frozen=True)
class Config:
    history_start:str="2018-01-01"
    min_history:int=260
    min_price:float=50.0
    min_turnover_cr:float=10.0
    min_atr_pct:float=1.5
    max_atr_pct:float=6.5
    max_ema20_extension:float=1.08
    max_high_distance_pct:float=18.0
    breakout_volume:float=1.5
    min_breakout_close_loc:float=0.70
    min_adx:float=18.0
    min_momentum_rank:float=70.0
    buy_score:int=80
    watch_score:int=68
    stop_atr:float=2.2
    max_stop_pct:float=9.0
    min_stop_pct:float=2.0
    max_entry_gap_pct:float=1.0
    max_hold:int=60
    cost_pct:float=0.60
    risk_per_trade_pct:float=0.50
    max_positions:int=8
    max_portfolio_risk_pct:float=3.0
    max_position_pct:float=15.0
    starting_capital:float=500000.0
    stale_sessions:int=3
    history_url:str="https://raw.githubusercontent.com/BennyThadikaran/eod2_data/main/daily/"
    output_dir:str="output_v2"
CFG=Config(starting_capital=float(os.getenv("V2_CAPITAL","500000")),buy_score=int(os.getenv("V2_BUY_SCORE","80")))

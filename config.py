from dataclasses import dataclass
@dataclass(frozen=True)
class IndicatorConfig:
 ema_fast:int=20; ema_mid:int=50; ema_intermediate:int=100; ema_slow:int=200; rsi_period:int=14; atr_period:int=14; adx_period:int=14; macd_fast:int=12; macd_slow:int=26; macd_signal:int=9; volume_avg:int=20; delivery_avg:int=20; swing_left:int=3; swing_right:int=2; range_lookback:int=20; high52:int=252
@dataclass(frozen=True)
class StrategyConfig:
 min_history:int=120; min_score:int=72; strong_score:int=86; max_entry_extension_pct:float=3.0; max_stop_pct:float=7.0; min_rr1:float=1.8; min_rr2:float=2.5; min_rr3:float=3.5; volume_breakout_ratio:float=1.35; delivery_floor:float=35.0; max_atr_pct:float=6.5
 # v6 confirmation gates: favor structure over raw score and reject unstable setups
 require_higher_low_for_buy:bool=True; require_rs_improving:bool=True; require_not_extended:bool=True; min_quality_score:int=72
@dataclass(frozen=True)
class BacktestConfig:
 horizon:int=30; warmup:int=120; min_score:int=72; min_gap_between_signals:int=8; commission_bps:float=10.0; slippage_bps:float=5.0
IND=IndicatorConfig(); STRAT=StrategyConfig(); BT=BacktestConfig()

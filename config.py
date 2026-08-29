from dataclasses import dataclass

@dataclass(frozen=True)
class IndicatorConfig:
    ema_fast:int=20; ema_mid:int=50; ema_intermediate:int=100; ema_slow:int=200
    rsi_period:int=14; atr_period:int=14; adx_period:int=14
    macd_fast:int=12; macd_slow:int=26; macd_signal:int=9
    volume_avg:int=20; delivery_avg:int=20; swing_left:int=3; swing_right:int=2
    range_lookback:int=20; high52:int=252

@dataclass(frozen=True)
class StrategyConfig:
    min_history:int=200
    min_score:int=72
    buy_score:int=82
    strong_score:int=90
    max_entry_extension_pct:float=4.0
    max_stop_pct:float=8.5
    min_stop_pct:float=2.0
    min_rr1:float=1.50
    min_rr2:float=2.50
    min_rr3:float=4.00
    volume_breakout_ratio:float=1.20
    delivery_floor:float=30.0
    max_atr_pct:float=6.5
    require_higher_low_for_buy:bool=True
    require_rs_improving:bool=True
    require_not_extended:bool=True
    require_volume_confirmation:bool=True
    require_positive_momentum:bool=True
    min_quality_score:int=82
    min_buy_quality_score:int=82
    max_buy_score:int=100
    max_resistance_distance_pct:float=3.0
    min_resistance_tests:int=2
    resistance_test_tolerance_pct:float=1.5
    min_base_days:int=8
    max_base_range_pct:float=9.0
    max_fall_20d_pct:float=-22.0
    max_fall_50d_pct:float=-35.0
    min_recovery_5d_pct:float=-1.5
    min_rs_spread_pct:float=0.0
    min_regime_score:int=4
    min_adx:float=15.0
    late_ret20_pct:float=15.0
    late_low_distance_pct:float=24.0
    max_breakout_extension_pct:float=6.0
    breakout_min_close_strength:float=0.65
    # Advanced pre-breakout controls
    min_volume_dryup_ratio:float=0.80
    max_volume_dryup_ratio:float=1.05
    require_volume_dryup:bool=True
    min_base_tightening_pct:float=5.0
    max_buy_zone_pct:float=1.5
    max_gap_entry_pct:float=2.0
    # 52-week-low early-reversal scanner (separate from the breakout hunter above)
    low52_max_distance_pct:float=20.0
    low52_min_bounce_pct:float=2.0
    low52_rsi_oversold:float=35.0
    low52_rsi_recovery:float=42.0
    low52_max_ret5d_down:float=-6.0
    low52_min_volume_ratio:float=1.3
    low52_min_score:int=55
    low52_buy_score:int=75

@dataclass(frozen=True)
class ApexConfig:
    """Mirrors RY APEX MATRIX V42 Pine Script's input() defaults exactly, so the
    Python port fires on the same setups the indicator does on TradingView."""
    ema_fast:int=20; ema_mid:int=50; ema_slow:int=200
    rsi_len:int=14; rsi_min:float=50.0; rsi_max:float=72.0
    adx_len:int=14; adx_min:float=18.0
    volume_avg:int=20; breakout_vol:float=1.30; strong_vol:float=2.00; dry_up_ratio:float=0.75
    res_lookback:int=20; breakout_buffer_pct:float=0.10; near_resistance_pct:float=3.0
    min_body_ratio:float=0.40; min_close_position:float=0.65
    vcp_lookback:int=20; compression_level:float=0.80; accumulation_lookback:int=10
    atr_len:int=14; initial_atr:float=2.5; trail_atr:float=2.5; max_extension_atr:float=3.0
    rr1:float=2.0; rr2:float=3.0
    buy_score:int=75; apex_score_min:int=88; tactical_score_min:int=82
    cooldown_bars:int=5
    require_breakout_for_buy:bool=False

NIFTY_SYMBOL='NIFTY 50'

@dataclass(frozen=True)
class BacktestConfig:
    horizon:int=30
    warmup:int=252
    min_score:int=72
    buy_score:int=82
    min_gap_between_signals:int=10
    commission_bps:float=10.0
    slippage_bps:float=5.0
    walk_forward_train_days:int=180
    walk_forward_test_days:int=60
    min_oos_trades:int=100
    min_quality_trades:int=30
    min_quality_profit_factor:float=1.15
    min_quality_win_rate:float=45.0
    target_win_rate:float=65.0
    strong_target_win_rate:float=72.0
    breakout_lookahead_days:int=20
    probability_min_samples:int=20
    probability_smoothing:int=5

IND=IndicatorConfig()
STRAT=StrategyConfig()
BT=BacktestConfig()
APEX=ApexConfig()

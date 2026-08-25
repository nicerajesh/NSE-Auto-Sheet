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

    # Risk / entry
    max_entry_extension_pct:float=4.0
    max_stop_pct:float=8.5
    min_stop_pct:float=2.0
    min_rr1:float=1.50
    min_rr2:float=2.50
    min_rr3:float=4.00

    # Confirmation
    volume_breakout_ratio:float=1.20
    delivery_floor:float=30.0
    max_atr_pct:float=6.5
    require_higher_low_for_buy:bool=True
    require_rs_improving:bool=True
    require_not_extended:bool=True
    require_volume_confirmation:bool=True
    require_positive_momentum:bool=True

    # PRE-BREAKOUT: deliberately strict. A candidate must be close to resistance.
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

    # Do not call a late/extended breakout a BUY.
    late_ret20_pct:float=15.0
    late_low_distance_pct:float=24.0
    max_breakout_extension_pct:float=6.0
    breakout_min_close_strength:float=0.65

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

IND=IndicatorConfig()
STRAT=StrategyConfig()
BT=BacktestConfig()

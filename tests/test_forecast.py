import pandas as pd

from backtest import forecast_profiles


def test_forecast_profiles_are_setup_matched_and_use_completed_oos_trades():
    trades = pd.DataFrame([
        {"SETUP": "BREAKOUT", "SIGNAL_DATE": "2023-01-02", "EXIT_DATE": "2023-01-10",
         "RET_PCT": 4.0, "HOLD": 7},
        {"SETUP": "BREAKOUT", "SIGNAL_DATE": "2025-01-02", "EXIT_DATE": "2025-01-10",
         "RET_PCT": -2.0, "HOLD": 5},
        {"SETUP": "PULLBACK", "SIGNAL_DATE": "2024-01-02", "EXIT_DATE": "2024-01-10",
         "RET_PCT": 3.0, "HOLD": 6},
        # Incomplete/current trade must not be counted.
        {"SETUP": "BREAKOUT", "SIGNAL_DATE": "2026-01-02", "EXIT_DATE": "2026-12-01",
         "RET_PCT": 99.0, "HOLD": 2},
        # Pre-2023 trade must not be counted.
        {"SETUP": "BREAKOUT", "SIGNAL_DATE": "2022-01-02", "EXIT_DATE": "2022-01-10",
         "RET_PCT": 99.0, "HOLD": 2},
    ])
    profiles = forecast_profiles(trades, pd.Timestamp("2026-11-26"))
    assert profiles["BREAKOUT"]["sample"] == 2
    assert profiles["BREAKOUT"]["win_pct"] == 50.0
    assert profiles["BREAKOUT"]["avg_ret_pct"] == 1.0
    assert profiles["BREAKOUT"]["median_hold_sessions"] == 6.0
    assert profiles["BREAKOUT"]["recent_sample"] == 1
    assert profiles["BREAKOUT"]["recent_avg_ret_pct"] == -2.0
    assert profiles["PULLBACK"]["sample"] == 1


def test_forecast_profiles_empty_input():
    assert forecast_profiles(pd.DataFrame(), pd.Timestamp("2026-11-26")) == {}

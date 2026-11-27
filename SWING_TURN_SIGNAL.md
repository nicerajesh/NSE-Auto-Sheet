# RY SWING TURN SIGNAL

Python scanner module: `src/swing_turn.py`  
TradingView indicator: `tradingview/RY_SWING_TURN_SIGNAL.pine`

## Signal rules (daily timeframe default)
- BUY: confirmed pivot low (4 bars left / 3 bars right), then on the confirmation close price is above EMA20, above prior close, green candle, RSI >= 45 and RSI rising versus 3 bars ago.
- SELL: confirmed pivot high, then on the confirmation close price is below EMA10, red candle, RSI < 55 and falling versus 3 bars ago.
- A pivot is not knowable until the right-side confirmation bars close. The chart marker is visually offset back to the pivot candle, but alerts and Python records occur on the confirmation date. Do not treat the historical marker location as the entry date.
- Python BUY plan: signal close as reference; stop = min(pivot low, close - 1.8 ATR); targets = 2R and 3R. Actual entry should be next session and levels rechecked for gaps.
- SELL is an exit warning for an existing long, not a short-entry recommendation.

This module is research-only and does not change the production strict BUY, WATCH, V38, V42, ledger, or broker execution logic. Confirm with historical tests and paper trading before using capital.

# Intraday Google Sheet Layout

The intraday output should be published as a separate report/tab and must not mix with delivery/swing BUYs.

## Primary tab: INTRADAY BUY SIGNALS

Columns:
- INTRADAY_RANK
- SYMBOL
- INTRADAY_ACTION
- CMP / LTP
- IDEAL_ENTRY
- STOP_LOSS
- TARGET_1
- TARGET_2
- INTRADAY_RR
- RSI14
- ADX14
- VOLUME_RATIO
- RELATIVE_STRENGTH
- ATR_RISK_PCT
- LIQUIDITY_STATUS
- WHY
- INTRADAY_REASON

Only `INTRADAY BUY` rows belong here.

## Secondary tab: INTRADAY WATCHLIST

Contains all evaluated candidates, including `NO TRADE` and the exact rejection reason. This is for diagnostics and future model calibration, not for immediate execution.

## Operating rule
Do not mix intraday signals with delivery/swing signals. Intraday signals are session-specific and should be evaluated with realistic spread, slippage, brokerage, taxes and execution latency before live use.

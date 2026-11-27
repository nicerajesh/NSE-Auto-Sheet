 # RY APEX V2 — Quality-first NSE swing scanner

A clean, isolated rebuild. It does not overwrite the existing scanner or Google Sheet publisher. Run it in paper/research mode first.

## Philosophy
- Fewer, higher-quality setups; no daily BUY quota.
- Long-only swing trading using end-of-day NSE OHLCV.
- No fabricated fundamentals: this feed has OHLCV only. Fundamental filters are excluded until a verified feed is configured.
- One strict tier (APEX BUY), separate WATCH and REJECT states.
- No live broker orders and no guaranteed returns.

## Strategy
Trend (Close > EMA50 > EMA200, EMA50 rising); 12–1 month momentum and 6-month relative-strength ranks; 20-session breakout with volume/close-location confirmation or EMA20 pullback reversal; Wilder ADX; liquidity, ATR%, extension, 52-week-high distance and market breadth filters; ATR stop, next-session entry, gap filter, staged trailing stop and transaction costs.

## Run
Install requirements-v2.txt, then run pytest on tests_v2 and execute python -m ry_apex_v2.run.

Outputs: output_v2/signals.csv, backtest_trades.csv, report.json.

## Validation gates
Actionable BUY is blocked unless 2023+ out-of-sample has at least 60 closed trades, PF >= 1.15 and positive expectancy, and 2025+ has at least 20 trades and positive expectancy. These are research gates, not proof of future returns. Current Nifty 500 constituents create survivorship bias.

## Limitations
Fundamentals are not included; vendor coverage/adjustments require verification; the backtest is per-symbol and not a cash-constrained portfolio simulation; OHLC cannot reveal intraday stop/target order so conservative stop-first sequencing is used. Do not connect automated order placement to this research build.

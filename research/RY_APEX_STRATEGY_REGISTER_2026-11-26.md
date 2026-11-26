# RY APEX MATRIX — Strategy Register
**Research snapshot:** 26 November 2026  
**Branch:** `ry-apex-v2-rebuild`  
**Status:** Research only. No strategy is approved for live deployment.

## Count
Six distinct strategy models have been developed or independently tested:

| # | Strategy | Core idea | Current evidence / status |
|---:|---|---|---|
| 1 | APEX Quality Trend | Trend quality, EMA structure, ADX, momentum, breakout/pullback and liquidity filters | Full portfolio simulation exists. Latest prior run: 2025+ event holdout PF 0.867 and expectancy -0.602%; BUY gate correctly failed. Not approved. |
| 2 | Momentum Rotation M | Cross-sectional momentum leadership, 40-session exit horizon | Independent event test: PF 1.330, average net return +1.735%, win rate 51.39%. Event-level result only; not yet validated as a cash-constrained portfolio. |
| 3 | Donchian Trend J | Donchian channel breakout / trend continuation, 40-session horizon | Independent event test: PF 1.146, average net return +0.751%. Event-level result only; not yet validated as a cash-constrained portfolio. |
| 4 | RSI Reset L | RSI pullback/reset entry | Prior independent event test was negative. Do not deploy. |
| 5 | Squeeze Expansion K | Volatility compression followed by expansion | Prior independent event test was negative. Do not deploy. |
| 6 | Relative Strength Growth | Cross-sectional 126d/252d ranks, rising EMA50, ADX, breakout/pullback and liquidity/ATR filters; reduce risk in weak breadth | New engine. V2 tests passed on latest tested commit; full portfolio backtest across ₹1L/₹3L/₹5L/₹10L still pending. |

## APEX baseline portfolio result (prior completed run)
The previous 2.1.0 run used daily close signals, next-session open entries, shared cash, 0.5% equity risk per trade, 3% aggregate open stop risk, max 8 positions, max 15% capital per position and 0.60% round-trip cost.

| Starting capital | Ending equity | CAGR | Max drawdown | Trades | PF |
|---:|---:|---:|---:|---:|---:|
| ₹1,00,000 | ₹1,52,974 | 5.14% | -19.57% | 500 | 1.301 |
| ₹3,00,000 | ₹4,65,349 | 5.31% | -21.83% | 504 | 1.307 |
| ₹5,00,000 | ₹7,76,588 | 5.32% | -21.25% | 506 | 1.308 |
| ₹10,00,000 | ₹15,62,943 | 5.40% | -20.91% | 506 | 1.306 |

Important: although the all-period portfolio simulation was positive, the recent 2025+ event holdout was negative (PF 0.867, expectancy -0.602%, 304 events). The live BUY gate therefore remained **false** and allocated BUYs were zero. This is why the all-period return is not sufficient to approve the strategy.

## Research limitations
- The equity universe is the current 497-symbol history universe; historical point-in-time index constituents are not available. Survivorship bias is possible.
- Momentum ranks are cross-sectional ranks within the available universe. A true Nifty 50/Nifty 500 benchmark-relative strength series still needs a clean index total-return history.
- Corporate actions/dividends and market impact are not fully audited/modelled.
- Historical tests do not guarantee future performance. Continue with paper trading and out-of-sample validation only.

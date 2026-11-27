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

## Exact rules recovered for the two leading independent models

These are copied from the independent strategy lab implementation, not reconstructed guesses:

- **M — Momentum Rotation:** 63-session return ranked cross-sectionally on each signal date; rank must be at least the 85th percentile; close above EMA50; EMA50 above EMA200; close above the prior 20-session high; volume divided by its 20-session average at least 1.1.
- **J — Donchian Trend:** close above EMA200; EMA50 above EMA200; close above the prior 55-session high; volume divided by its 20-session average at least 1.3; close location within the daily range at least 0.65.
- Both models use a 15-calendar-day per-symbol signal cooldown. Signal is calculated after the completed close; entry is next session OPEN; event exits are the 10th, 20th or 40th future session CLOSE; 0.35% round-trip cost is deducted. There is no stop-loss or portfolio sizing rule in this independent event-test code.

### 40-session event holdout results

| Period | Strategy | Events | Win rate | Average net return | Profit factor |
|---|---|---:|---:|---:|---:|
| 2018–2022 train | M Momentum Rotation | 2,043 | 54.87% | +5.909% | 2.077 |
| 2018–2022 train | J Donchian Trend | 2,978 | 53.96% | +4.767% | 1.909 |
| 2023–2024 validation | M Momentum Rotation | 1,433 | 62.25% | +8.618% | 3.230 |
| 2023–2024 validation | J Donchian Trend | 2,624 | 62.16% | +7.273% | 3.116 |
| 2025+ holdout | M Momentum Rotation | 1,148 | 51.39% | +1.735% | 1.330 |
| 2025+ holdout | J Donchian Trend | 1,304 | 46.55% | +0.751% | 1.146 |

These are overlapping event returns, not portfolio returns. The very high 2023–24 validation results and current-universe survivorship bias require caution. The 2025+ holdout is more recent and is positive for M/J, but does not establish investable portfolio performance.

## Portfolio simulation comparison (V2.2, ₹5 lakh scenario)

This is the daily, cash-constrained simulation using next-session OPEN entries, ATR stop/trailing exits, 0.5% equity risk per trade, 3% aggregate open stop risk, max 8 positions, max 15% per position and 0.60% round-trip cost. It is a different model from the independent M/J fixed-horizon event test above.

| Metric | APEX Quality Trend | Relative Strength Growth |
|---|---:|---:|
| Ending equity | ₹7,76,588 | ₹9,78,749 |
| Net profit | ₹2,76,588 | ₹4,78,749 |
| Total return | 55.32% | 95.75% |
| CAGR | 5.32% | 8.24% |
| Trades | 506 | 615 |
| Win rate | 31.23% | 30.24% |
| Profit factor | 1.308 | 1.453 |
| Max drawdown | -21.25% | -20.28% |
| Annualised daily volatility | 11.50% | 15.11% |

Recent holdout (trades exiting in 2025 onward): APEX 125 trades, PF 0.887, net trade P&L -₹27,990; Relative Strength 172 trades, PF 1.123, net trade P&L +₹42,242. Relative Strength 2025 return was -3.16%, followed by +6.06% in 2026. The stronger return comes with higher daily volatility; it is not a risk-free improvement.

**Decision:** Relative Strength is the current research leader, not a live-approved strategy. The 497-stock current-universe ranking is not a true Nifty benchmark-relative strength measure. Point-in-time constituents, corporate actions/dividends and realistic market impact remain unresolved.

## Research limitations
- The equity universe is the current 497-symbol history universe; historical point-in-time index constituents are not available. Survivorship bias is possible.
- Momentum ranks are cross-sectional ranks within the available universe. A true Nifty 50/Nifty 500 benchmark-relative strength series still needs a clean index total-return history.
- Corporate actions/dividends and market impact are not fully audited/modelled.
- Historical tests do not guarantee future performance. Continue with paper trading and out-of-sample validation only.

# RY APEX V2 — live research audit (2026-11-26)

## Execution status
- GitHub Actions run: https://github.com/nicerajesh/NSE-Auto-Sheet/actions/runs/45842559349
- V2 tests: PASS (3 tests)
- Full V2 research pipeline: PASS
- History cache restore: PASS
- Data as-of: 2026-11-26; 497 symbols
- Artifact: `ry-apex-v2-research` (signals.csv, backtest_trades.csv, report.json)

## Backtest results
Assumed transaction cost: 0.60% round trip. Entry is next session open. Exit uses ATR-based stop/trailing logic or 60-session time exit.

| Period | Trades | Win rate | Profit factor | Mean net return |
|---|---:|---:|---:|---:|
| Train (before 2023) | 361 | 32.41% | 1.627 | +2.497% |
| OOS 2023+ | 599 | 31.72% | 1.414 | +1.721% |
| OOS 2025+ | 304 | 25.00% | 0.867 | -0.602% |

Full sample: 960 trades, 31.98% wins, PF 1.492, mean net return +2.013%.
2025: 153 trades, PF 0.75, mean -1.13%.
2026: 151 trades, PF 0.98, mean -0.07%.

## Decision
**NOT APPROVED for actionable/live BUY signals.** The 2025+ holdout fails: PF below 1 and negative expectancy. The scanner correctly blocks BUYs: 467 WATCH, 11 REJECT, 0 allocated BUY.

Do not loosen the gate to force signals. Keep this branch in research/paper mode.

## Important limitations / next work
1. Current Nifty 500 universe creates survivorship bias; historical point-in-time constituents are not available in this run.
2. Trade-level per-symbol results are not a cash-constrained portfolio backtest. Portfolio overlap, capital usage, exposure, drawdown and daily signal ranking still need a portfolio simulator.
3. Gap-through-stop losses are possible; a few large losses dominate downside. Validate gap/slippage modelling and corporate-action adjustments.
4. OHLC daily bars cannot determine intraday stop/target order. Intraday sequencing assumptions can materially change results.
5. Compare the V2 strategy against the independent strategy lab and a simple Nifty benchmark on identical dates/cost assumptions before any production decision.
6. Require a fresh untouched holdout after any parameter change. Do not tune thresholds to the 2025+ holdout.

## Recommendation
Keep the existing production scanner untouched. Continue paper research only; first implement a date-by-date, cash-constrained portfolio simulator with max positions, risk sizing, liquidity/turnover caps, concurrent positions, realistic gap fills, and portfolio equity/drawdown metrics. Re-run all tests and walk-forward validation after that.

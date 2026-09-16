# RY APEX MATRIX — Intraday Cash Equity Engine

## Research basis
The intraday path is intentionally separate from delivery/swing. SEBI's July 2024 study reported that 7 out of 10 individual traders in equity cash intraday trading incurred losses, so the engine is designed around selectivity, risk controls and cost-aware validation rather than signal frequency. Academic evidence on momentum/trend strategies also shows that trading costs can materially reduce short-horizon profitability.

## Strategy architecture
1. Market regime gate: do not trade every session.
2. Trend gate: price/EMA alignment where available.
3. Momentum gate: RSI and ADX confirmation where available.
4. Relative-volume gate: require abnormal participation rather than ordinary volume.
5. Relative-strength gate versus the market where available.
6. Volatility gate: reject excessive ATR risk.
7. Liquidity gate: reject poor-liquidity names.
8. Executable trade plan: entry, stop and target must exist.
9. Minimum reward/risk: 1.8R by default.
10. Anti-chase gate: reject entries materially above current price.
11. Output separation: `intraday_buy_signals.csv` contains only rows passing all hard gates; `intraday_watchlist.csv` retains the full diagnostic universe.

## Important limitation
The engine cannot guarantee profit. Intraday results must be validated with realistic brokerage, taxes, spread and slippage assumptions before live capital is used. The engine should be paper-traded first and its own realized edge monitored over time.

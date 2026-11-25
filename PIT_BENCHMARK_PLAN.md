# PIT / Benchmark Validation Plan

## Why this work is mandatory
The existing history bootstrap starts from the current Nifty 500 list and applies it
backwards. That is survivorship-biased. This branch introduces a monthly point-in-time
membership source with a separate disclosure-availability date and refuses to guess
ISIN-to-symbol mappings.

## Candidate source and limitations
- PIT membership: `prathmeshgupta/nifty-pit-universe`, Nifty 500 CSV, Jan 2005–Sep 2026.
- Its README describes 261 monthly snapshots, ISIN/company/industry fields and a
  `pit_available_date` intended to prevent look-ahead.
- The upstream README reports its own audit, but this project must independently
  validate row counts, continuity, duplicate ISINs, availability lags and historical
  fallen-constituent examples before accepting it.
- Membership alone does not create a survivorship-free backtest. We also need a
  point-in-time ISIN-to-symbol/security map and OHLCV for excluded, delisted, merged
  and renamed companies. Missing price histories must be counted, not silently dropped.
- Current Nifty 500 members projected backwards remain prohibited for PIT performance
  claims.

## Benchmark rules
- Use Nifty 500 TRI (not price-only Nifty 500) as the primary passive benchmark.
- Use matching daily dates and identical starting capital/cash-flow assumptions.
- Compare CAGR, annual returns, max drawdown, volatility, Sharpe, turnover and costs.
- Report strategy excess return and information ratio; do not compare an event-level
  trade average with an index CAGR.
- Benchmark data must be independently sourced from NSE Indices and timestamped.

## Acceptance gates before paper trading
1. PIT membership coverage and point-in-time security mapping >= 99% of stock-month rows;
   all unmapped rows listed in an audit artifact.
2. Include delisted/fallen names where price data exists; no silent deletion.
3. Corporate actions, symbol changes, mergers and delistings have explicit handling.
4. No look-ahead: universe membership is usable only from `pit_available_date`.
5. Walk-forward evaluation: train through 2022; validate 2023–2024; untouched test 2025–2026.
6. Compare old production strategy, new candidate strategy and Nifty 500 TRI on the
   same point-in-time universe/date range and realistic costs.
7. Report all years, rolling 12-month results, drawdown and exposure. If recent OOS
   results fail, scanner remains research-only.

No production workflow, Google Sheet publishing, or live order logic is changed here.

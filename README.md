# RY APEX MATRIX — NSE Delivery Research

## Current structure

### Existing production workflow (unchanged)
`.github/workflows/daily.yml` runs the existing daily reports:
- SWING
- DELIVERY (monthly momentum rotation)
- INTRADAY (separate Angel One data workflow; see its dedicated workflow/configuration)

The existing production signal engine and Google Sheet publishing are not changed by Delivery 20 research.

### New isolated Delivery 20 research
Purpose: find historical NSE delivery setups where a stock may reach a **+20% target** after entry.

Files:
- `src/delivery20.py` — signal rules, next-session entry backtest and summary.
- `src/delivery20_run.py` — runs research using the existing cached NSE/EOD history and feature engine.
- `tests/test_delivery20.py` — tests target, stop-first execution and unfinished positions.
- `.github/workflows/delivery20-research.yml` — runs tests, then historical research, and uploads CSV results.

Outputs:
- `delivery20_trades.csv`
- `delivery20_latest_candidates.csv`
- `delivery20_summary.csv`

### Delivery 20 rules (research hypotheses, not guaranteed returns)
- Trend: Close > EMA20 > EMA50 > EMA200, with EMA50 and EMA200 rising.
- Trigger: 55-session closing breakout.
- Confirmation: volume ratio >= 1.5, ADX >= 22, momentum rank >= 80.
- Liquidity: average turnover >= ₹10 crore.
- Avoid chasing: signal close no more than 15% above EMA20.
- Initial stop risk: 5%–10%; target: 20% from actual next-session entry.
- Entry: next session open; skip if gap-up exceeds 2%.
- Conservative daily-bar simulation: stop is checked before target if both are touched.
- Estimated round-trip costs: 0.35%; maximum holding period: 120 sessions.

A 20% target is an objective, **not a promise**. Backtest outputs must be reviewed for sample size, profit factor, stop rate, drawdown, recent-year performance, data quality and survivorship bias before paper trading. No live order execution is implemented by this research module.

## Run manually

From the repository root:
```bash
pip install -r requirements.txt
python -m pytest -q tests
python src/delivery20_run.py
```

## Data and limitations
- Uses the repository's existing EOD history pipeline; no new BhavCopy downloader is added.
- Current Nifty 500 constituents can create survivorship bias in historical tests.
- Historical corporate-action adjustment and point-in-time index membership must be verified.
- A strategy can lose money; do not deploy real capital based on a target percentage alone.

## Historical notes
- `AUDIT.md` records previous production-engine audit findings.
- `RESEARCH.md` records earlier strategy research and its limitations.

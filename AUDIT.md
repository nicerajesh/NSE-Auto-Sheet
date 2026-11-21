# Audit - RY APEX v2 (NSE-Auto-Sheet), 19 Nov 2026

Maine production code real NSE data (eod2, 146 liquid stocks, 2019-2026) par chalaya. Pehle 70 tests pass the.

## Verified numbers (146 stocks - mere chune hue aaj ke bade naam, isliye survivorship aur zyada)
| Test | Result |
|---|---|
| Base (strict tier) | 432 trades, PF 2.76, win 32.9%, avg R +0.85 |
| In-sample (exit < 2023) | PF 3.77 |
| Out-of-sample (2023+) | PF 1.94, win 26.6% |
| 2025-26 signals | PF 0.75, win 14% |
| Top 5% winners hata do | PF 1.67 (21 trades = 39% gross profit) |
| Cost 0.35% -> 1.35% | PF 2.27 (cost asli kamzori nahi) |
| JUMP exclusion (look-ahead rule) | PF 2.76 -> 2.65 (chhota) |

`RESEARCH.md` (448 stocks): staircase-exit PF 1.5-1.8, portfolio CAGR 10-19% (equal-weight se behtar nahi), 2025-26 kamzor. Edge chhota, regime-dependent.

## Findings
1. Edge gate circular tha (parameters usi sample par chune, usi par gate). **Fix:** walk-forward OOS gate (`CFG.oos_*`), SYSTEM STATUS note.
2. Survivorship bias (aaj ka Nifty 500; momentum rank bhi jeete hue stocks me). **Open** - point-in-time constituents chahiye.
3. 4 tiers (strict/WATCH/V38/V42): weak tiers (PF 1.3, 1.19) noise + risk cap tod sakte hain. **Fix:** RY/V38/V42 tabs default band.
4. PF trade-level % par; portfolio drawdown production run me nahi. **Open.**
5. Ledger + history sirf Actions cache me. **Fix:** ledger roz `data/signal_ledger.csv` me commit (cache evict + 60-din inactivity dono se bachav).
6. EMA200 30 bar par valid maana jaata tha. **Fix:** `min_periods=n`.
7. NSE bhavcopy GitHub IPs par aksar block - single point. **Open:** eod2 se daily fallback.
8. Intraday module tha hi nahi. **Added:** `intraday.py`, `angel.py`, `intraday_run.py`.
9. Spreadsheet ID config me hard-coded - Sheet ki sharing check karo.

## Jo kaam NAHI aaya (RESEARCH.md) - isliye use nahi kiya
Delivery %, volume dry-up, index-regime filter, 52w-low reversal, ranking by RS/low-vol.

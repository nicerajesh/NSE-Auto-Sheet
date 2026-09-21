# RY APEX v2 (NSE Auto Sheet) - saaf-suthra version

## Kya badla (39 files -> 8 files, 4 yml -> 1 yml)
- **Sirf `daily.yml` chahiye.** Purani `main.yml`, `trigger-main-once.yml`, `repair-strategy-syntax.yml`, `intraday-report.yml` sab delete.
  (`trigger-main-once` har push par main ko dobara chala deta tha, `repair-strategy-syntax` ChatGPT ke toote code ko patch karke commit push karta tha -> aur runs.)
- `sitecustomize.py` (chhupa hua monkey-patch) aur `persistent_runner.py` (runtime par source code rewrite) hata diye. Ab strategy sirf `src/engine.py` me hai.
- Google Sheet: sirf **ACTION PLAN** aur **SYSTEM STATUS**.

## Files
| File | Kaam |
|---|---|
| `src/config.py` | saari settings |
| `src/engine.py` | signal + SL/T1/T2/T3 + exit simulator (backtest aur live dono yehi use karte hain) |
| `src/backtest.py` | 2019+ deep backtest, saal-wise, health, edge gate |
| `src/ledger.py` | published signals ka live track (SL raise / exit / scoreboard) |
| `src/data.py` | Nifty 500 list, 8 saal history (eod2_data), rozana NSE bhavcopy top-up |
| `src/publish.py` | Google Sheet (retry ke saath) |
| `src/run.py` | poora pipeline |
| `tests/` | 17 tests |

## Install (5 minute)
1. Purane repo me `src/`, `tests/`, `.github/workflows/` ki saari purani files delete karo. `requirements.txt` replace.
2. Is zip ki files copy karo, commit + push.
3. Secret `GCP_CREDENTIALS` wahi rahega. (Optional Variables: `CAPITAL_BASE`, `RISK_PER_TRADE_PCT`, `MAX_CONCURRENT_POSITIONS`.)
4. Actions -> **RY APEX Daily** -> Run workflow. Pehli run me `clean_extra_tabs` tick karo (baaki purane tabs hat jayenge).
5. Pehli run me 8 saal ki history download hoti hai (~2-4 min), phir cache me rehti hai.

## Strategy (jo backtest me chali)
Trend (Close > EMA50 > EMA200) + top-10% 12-1 month momentum + trigger (EMA20 pullback ya 20-din breakout on volume).
SL = 2 ATR. T1/T2/T3 = 2R/4R/6R; T1 par SL entry par, T2 par SL T1 par, T3 par SL T2 par. Koi fixed sell target nahi. Max 90 din.

## Sach
- Purane fixed 2.5R/3.5R/5R ladder + tight SL ne edge maar diya tha. Entry filters ka random "trend me koi bhi stock" se koi khaas fark nahi tha.
- Backtest me kamai 2020/2021/2023 se aayi; 2025-26 negative. Win rate ~26%, median trade -6%.
- Survivorship bias: universe aaj ka Nifty 500 hai. Asli results kam honge.
- Sheet me "WEAK REGIME - half size" dikhe to size aadha rakho ya paper trade karo. LIVE SCOREBOARD 4-6 hafte dekho.
- Data 3+ session purana ho to BUY apne aap band.

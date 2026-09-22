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
| `src/positions.py` | tumhari asli positions: HOLD / SL RAISE / EXIT, risk budget, drawdown guard |
| `src/notify.py` | Telegram alerts (optional) |
| `src/publish.py` | Google Sheet (retry ke saath) |
| `src/run.py` | poora pipeline |
| `tests/` | 36 tests |

## Install (5 minute)
1. Purane repo me `src/`, `tests/`, `.github/workflows/` ki saari purani files delete karo. `requirements.txt` replace.
2. Is zip ki files copy karo, commit + push.
3. Secret `GCP_CREDENTIALS` wahi rahega. (Optional Variables: `CAPITAL_BASE`, `RISK_PER_TRADE_PCT`, `MAX_CONCURRENT_POSITIONS`.)
4. Actions -> **RY APEX Daily** -> Run workflow. Pehli run me `clean_extra_tabs` tick karo (baaki purane tabs hat jayenge).
5. Pehli run me 8 saal ki history download hoti hai (~2-4 min), phir cache me rehti hai.

## Sheet formatting bug fix (Sept 22, 2026)
Live run me "Stocks in universe" ek bekar date (1901-05-14) dikha raha tha, aur date columns
("Data date", "SIGNAL DATE") ISO+time format me the (21-Sep-2026 ki jagah 2026-09-21 00:00:00).
Wajah: `USER_ENTERED` mode se Sheets date-jaisi strings ko khud reparse kar deta tha, aur us column
ka date-format agle plain number (stock count) par bhi chipak jaata tha. Fix: `RAW` mode - ab Sheets
kuch bhi khud parse nahi karta. 2 regression tests jode gaye hain isse dobara pakadne ke liye.

## ADX filter joda (Sept 2026)
Retailer/ChatGPT ke 8-layer score wale idea ko individually test kiya:
  - ADX >= 25 (trend strength): full-history backtest PF 1.9 -> 2.04 (983 trades). Engine me joda (`CFG.adx_min`).
  - MACD histogram > 0: PF girta hai (1.77 -> 1.66 train). NAHI joda.
  - RSI 40-65 zone breakout par: koi improvement nahi. NAHI joda.
  - **Note:** ADX formula me pehle ek bug tha (+DM/-DM comparison galat tha) jo maine research script se match karke pakda aur
    fix kiya - production backtest chalakar hi confirm kiya, sirf research proxy par bharosa nahi kiya. Isliye tests +
    ek asli backtest run dono zaroori hain, na ki sirf "code likha aur test hara".
  - 2025-2026 abhi bhi kamzor hain (PF 0.5-0.6) - ADX ne overall PF sudhara hai, regime-risk khatam nahi kiya.

## Pehle se pata karna (breakout ke ek din pehle)
Maine ye asli 2019-2026 data par test kiya. Sach: koi bhi "kal ye stock bhagega" wala reliable signal nahi mila.
  - Tight-range/volume-dry-up "coiling" score banaya jo breakout se PEHLE fire kare -> sirf 26% coil-din 10 session ke andar
    breakout dete hain, aur jo breakout coil ke baad aaya wo bina-coil breakout se KAMZOR tha (PF 1.48 vs 1.64).
  - Isliye maine koi naya "pehle se batao" signal nahi joda - wo random guess jaisa hota.
  - Jo hua: WATCHLIST ab "DIST TO TRIGGER %" se sort hoti hai - jo stock breakout price ke sabse paas hai wo sabse upar.
    RANGE TIGHT (0-100) column bhi hai (100 = pichhle 1 saal me range sabse tight) - sirf context ke liye, prediction nahi.
    Trigger cross hone par BUY tab hi aata hai jab ACTION PLAN me row aaye - watchlist khud BUY signal nahi hai.

## Real money ke liye (v2.1)
1. **MY POSITIONS tab**: pehli run me Sheet me khud ban jata hai. Har kharid ke baad ek row: `SYMBOL | BUY DATE (dd-mm-yyyy) | BUY PRICE | QTY | MY STOP (optional)`. Bech do to row hata do.
   ACTION PLAN ke section A me roz dikhega: HOLD / SL RAISE karo / SL HIT. **SL order broker me tum khud lagaoge/badloge** - engine order nahi lagata.
2. **Size stage**: `SIZE_STAGE_PCT` (default 25). Normal size ka 25% se shuru karo. 4-6 hafte LIVE SCOREBOARD aur apni positions dekh kar hi 50 -> 100 karo. `CAPITAL_BASE` apni asli trading capital rakho.
3. **Risk limits (automatic)**: sab open positions ka total risk <= `MAX_OPEN_RISK_PCT` (6%), max `MAX_CONCURRENT_POSITIONS` (12), already-held stock dobara nahi, cash se zyada qty nahi.
4. **Drawdown guard**: open positions ka unrealized loss `DD_GUARD_PCT` (8%) capital se zyada ho to naye BUY band.
5. **Telegram (optional)**: BotFather se bot banao -> Secrets me `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. Sirf kaam ki cheez aati hai (SL raise, exit, naye BUY, warning).
6. Ye kabhi guarantee nahi: 10 SL lagataar hit ho sakte hain. Us haalat me bhi total loss sahne layak hi size rakho.

## Strategy (jo backtest me chali)
Trend (Close > EMA50 > EMA200) + top-10% 12-1 month momentum + trigger (EMA20 pullback ya 20-din breakout on volume).
SL = 2 ATR. T1/T2/T3 = 2R/4R/6R; T1 par SL entry par, T2 par SL T1 par, T3 par SL T2 par. Koi fixed sell target nahi. Max 90 din.

## Sach
- Purane fixed 2.5R/3.5R/5R ladder + tight SL ne edge maar diya tha. Entry filters ka random "trend me koi bhi stock" se koi khaas fark nahi tha.
- Backtest me kamai 2020/2021/2023 se aayi; 2025-26 negative. Win rate ~26%, median trade -6%.
- Survivorship bias: universe aaj ka Nifty 500 hai. Asli results kam honge.
- Sheet me "WEAK REGIME - half size" dikhe to size aadha rakho ya paper trade karo. LIVE SCOREBOARD 4-6 hafte dekho.
- Data 3+ session purana ho to BUY apne aap band.

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
| `src/publish.py` | Google Sheet: ACTION PLAN, SYSTEM STATUS, RY (retry ke saath) |
| `src/run.py` | poora pipeline |
| `tests/` | 36 tests |

## Install (5 minute)
1. Purane repo me `src/`, `tests/`, `.github/workflows/` ki saari purani files delete karo. `requirements.txt` replace.
2. Is zip ki files copy karo, commit + push.
3. Secret `GCP_CREDENTIALS` wahi rahega. (Optional Variables: `CAPITAL_BASE`, `RISK_PER_TRADE_PCT`, `MAX_CONCURRENT_POSITIONS`.)
4. Actions -> **RY APEX Daily** -> Run workflow. Pehli run me `clean_extra_tabs` tick karo (baaki purane tabs hat jayenge).
5. Pehli run me 8 saal ki history download hoti hai (~2-4 min), phir cache me rehti hai.


## RY APEX MATRIX Quant Pro V43 (research tier)

V43 existing data pipeline ko reuse karta hai; BhavCopy/history source ya existing Sheet tabs ko rename/delete nahi karta. Iska score 0-100 ranking aid hai, win probability nahi. Entry candidates ACTION PLAN ke naye section "E) RY APEX QUANT PRO V43" aur existing RY quick-view tab me dikhte hain. Naye Google Sheet tabs add nahi hote.

- **Market regime limitation:** historical data me direct NIFTY index series use nahi ki gayi. Regime available stocks ke median daily return aur EMA200 breadth se banta hai; ise clearly PROXY label kiya gaya hai, NIFTY nahi.
- **Setups:** trend-confirmed breakout aur pullback; volume, relative-strength rank, liquidity, ATR risk aur overhead-resistance headroom scoring.
- **Risk:** initial stop 2 ATR; reference targets 2R/4R/6R; conservative daily OHLC stop handling; next-session OPEN entry; gap-up >2% skip; 0.35% round-trip transaction-cost assumption.
- **Portfolio fit:** V43 candidates existing strict and WATCH candidates ke baad remaining slots, cash and open-risk budget se fit hote hain.
- **Outputs:** output/action_plan_buy_v43_quant_pro.csv, output/backtest_trades_v43_quant_pro.csv, and output/backtest_summary_v43_quant_pro.csv.
- **Validation status:** automated unit tests cover score bounds, proxy labels, stop simulation, gap filter, net-return summary, and missing-feature handling. Full GitHub Actions run + real historical backtest must pass before considering live use.

**No profit guarantee:** V43 is a research candidate, not a promise of profit. Results have current-universe survivorship bias, the market proxy is not NIFTY, and daily OHLC bars cannot reproduce every real fill. Inspect yearly/out-of-sample results, fees, slippage and drawdown; paper-trade before risking capital.

## RY V42 - naya tier, Pine Script V42 "PRO SWING ENGINE" ka hoobehoo (Sept 24, 2026)
User ne V42 Pine Script diya (score engine, 3 BUY tier: APEX/TACTICAL/BUY, VCP/compression,
accumulation, 6-condition exit) aur kaha "jitne BUY aayein sab do, koi block nahi, sirf apni sheet".

**Zaroori disclosure**: V42 ka Market Regime aur Relative Strength NIFTY index se calculate hote
hain. Is environment me NIFTY index ka seedha data nahi mila (sirf per-stock NSE bhavcopy) - isliye
apna EQUAL-WEIGHT UNIVERSE PROXY use kiya gaya hai (jitne tradable stocks hain unka daily average
return se ek cumulative index) - NIFTY ki jagah, wahi concept. Baaki sab (score engine formula,
VCP/compression, teen BUY tier, chhe exit conditions) Pine V42 se hoobehoo match karta hai.

Naya module `src/v42.py`. Backtest (production code, proper state-machine + 5-bar cooldown,
2019-2026, 448 stocks): n=6653, win=35.1%, **PF=1.19** - teeno V-tier me sabse kamzor (V38 ~1.30,
WATCH ~1.7, strict ~2.2), isliye size sabse chhota (`v42_size_mult=0.25`).

Naya "RY V42" tab (poora detail: entry type, score, SL, T1/T2, QTY) + RY tab me bhi "BUY (V42 ...)"
entries jud gayi hain. V38 ki tarah koi cap nahi, koi portfolio-fit narrowing nahi is tier par bhi.

Ab 6 sheet tabs: ACTION PLAN, SYSTEM STATUS, MY POSITIONS, RY, RY V38, RY V42.

## RY V38 - koi cap nahi (Sept 24, 2026)
Pehle V38 tier max 5/din tak simit tha, aur portfolio-budget se aur bhi kat jaata tha. User ne
kaha "jitne bhi BUY aayein sab sheet me aayein" - ab koi cap nahi, koi portfolio-fit narrowing
nahi is tier par. Har V38 signal apni QTY/CAPITAL dikhata hai (v38_size_mult se), poore signal
count ke against nahi kaate jaate. Agar sab le lo to total risk MAX_OPEN_RISK_PCT se zyada ho
sakta hai - ye tier informational hai (Pine chart jaisa "sab dikhao"), khud chun kar lena hai.

## RY tab me V38 tier bhi joda (Sept 23, 2026)
RY (quick view) tab pehle sirf strict + WATCH BUY dikhata tha, V38 wale signal chhoot jaate the.
Ab RY tab me teeno tier ek sath: "BUY", "BUY (WATCH)", "BUY (V38)" - har ek apne PF caveat ke
saath. "RY V38" ka alag detailed tab bhi wahi rehta hai poori jaankari ke liye.

## RY V38 tab - Pine Script V38 ka hoobehoo signal, alag sheet (Sept 23, 2026)
User ke Pine Script (RY APEX MATRIX V38) ka BUY/exit/T1/T2 logic bina kisi trend/momentum/ADX
filter ke, hoobehoo Python me daala - ek bilkul naye "RY V38" tab me, strict BUY ("hard" wala) ko
bina chhue. Teen trigger (STRONG BREAKOUT, EARLY BREAKOUT, V-SHAPE) V38 jaisa hi. Exit V38 jaisa
hi - roz SL = max(SL_prev, close - 2.5xATR), sirf upar; T1/T2 sirf dikhane ke liye, SL ko affect
nahi karte (Pine me bhi t1Hit/t2Hit sirf plot ke liye the).

Real backtest (production code, proper 1-trade-at-a-time per stock, 2019-2026, 448 stocks):
n=8344, win=37.1%, Profit Factor=1.30 - teeno tier me sabse kamzor (strict ~2.2, WATCH ~1.7),
kyunki koi quality filter nahi hai. Isliye size bhi sabse chhota (`v38_size_mult=0.35`).

Ab 4 sheet tabs: ACTION PLAN, SYSTEM STATUS, MY POSITIONS, RY (quick view), RY V38 (naya).

## WATCH BUY tier - roz kuch dikhane ke liye (Sept 22-23, 2026)
Strict BUY sirf ~1.8/din aata hai (30% din 0 signal - jaan-bujhkar, quality ke liye). User ne kaha
"roz de" - test kiya ki dhila karne se kya hota hai:
  - Strict (abhi): avg 1.8 BUY/din, 30% din khali, PF 2.20
  - Loose (top-50% momentum, ADX>=15): avg 13.3/din, 0.8% din khali, PF 1.70
  - Bilkul filter-free (V38 jaisa): avg 24/din, 0% din khali, PF 1.61

Fix: naya "WATCH BUY" tier joda (`SIGNAL_LOOSE` - loose thresholds, strict se kabhi overlap nahi
karta). ACTION PLAN me B) STRICT BUY ke neeche B2) WATCH BUY dikhta hai, saaf caveat ke saath ki
iska PF kam hai. Size bhi jaan-bujhkar aadha (`position_size` me 0.5x extra). RY tab me bhi
"BUY (WATCH)" tag se alag dikhta hai. Paper-signal scoreboard sirf strict BUY track karta hai -
dono tier ka edge mix nahi hota.

## RY quick-view tab (Sept 22, 2026)
Sheet me ab 4 tabs: ACTION PLAN, SYSTEM STATUS, MY POSITIONS, aur naya **RY** - sirf ek-nazar me
aaj ka BUY ya SELL, price, SL, T1/T2/T3. Pine script (V39) me bhi "EXIT" label ko "SELL" kar diya,
taaki chart aur sheet dono me wahi BUY/SELL bhasha ho.

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

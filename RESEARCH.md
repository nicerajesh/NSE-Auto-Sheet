# Research notes (real NSE data, 448 stocks, 2019-2026, eod2_data)

Sab numbers survivorship-biased hain (universe = aaj ke Nifty 500 jaise naam). Relative comparison valid hai, absolute profit nahi.

## 1. Purana engine (tumhara asli code, real data)
14 stocks, Jan-2023 se Sep-2026: 220 trades, win 25.9%, **PF 0.62**, avg -1.54%/trade, 69.6% trades seedhe SL par, T1 sirf 16%, T3 2.7%.
(Live log ka PF 0.40-0.50 isi tarah ka tha.)

## 2. Exit ka asar (same entries, alag exit) - profit factor
| Entry | Purana ladder 2.5/3.5/5R, SL 1.5 ATR, 30 din | Staircase 2/4/6R, SL 2 ATR, 90 din |
|---|---|---|
| Koi bhi stock, koi bhi din | 1.11 | 1.44-1.74 |
| Bas trend (C>EMA50>EMA200) | 1.14 | 1.62-1.85 |
| Pullback / Breakout / RS-leader / Tight base / Delivery | 1.04-1.10 | 1.5-1.8 |

Matlab: elaborate entry filters ("random trend stock" se behtar nahi) + tight fixed targets = zero edge. Exit badalne se sabse zyada fark aaya.

## 3. Momentum
Trend stocks ko 12-1 month momentum decile se baanto: top 10% ka avg R 0.59/0.48 (train/test) vs bottom half 0.36/0.32 - halka par consistent gradient. Isliye engine me momentum rank filter hai.
Monthly rotation (top-20 momentum, bina SL) 2019-26: ~30% CAGR vs equal-weight universe 17% (8 me se 7 saal EW se behtar; 2025 me -11.5% vs -1.3%). Survivorship se ye bahut inflated hai.

## 4. Kya kaam NAHI aaya
- Index-trend regime filter (EMA200/EMA50 par EW index) - performance behtar nahi hui.
- Delivery %, volume dry-up, 52-week-low reversal, stealth accumulation - random baseline se behtar nahi.
- Ranking (RS / low-vol / volume) portfolio me random selection se behtar nahi.

## 5. Saal-wise (engine ke closed trades)
2019 PF 0.19 | 2020 3.14 | 2021 4.68 | 2022 1.10 | 2023 3.70 | 2024 1.97 | **2025 0.47 | 2026 0.69**
Last 120 din ka avg R negative -> "WEAK REGIME, half size".
Portfolio-level (0.5% risk, 12 positions) event-driven version: CAGR ~10-19%, max DD -21% se -33% - EW universe se behtar nahi. Edge chhota aur regime-dependent hai.

"""Rozana ka poora pipeline: data -> features -> backtest -> aaj ke BUY -> ledger -> Sheet + CSV."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backtest as bt          # noqa: E402
import data as dt              # noqa: E402
import ledger as lg            # noqa: E402
import publish as pb           # noqa: E402
from config import CFG         # noqa: E402
from engine import add_features, latest_candidates, position_size  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
STATE = Path(os.getenv("NSE_STATE_DIR", ROOT / "state"))
OUT = Path(os.getenv("NSE_OUTPUT_DIR", ROOT / "output"))


def notes(by_year: pd.DataFrame, summ: dict) -> list[str]:
    weak = by_year[(by_year["pf"] < 1.0)]["YEAR"].astype(int).tolist() if not by_year.empty else []
    return [
        "1) Backtest universe AAJ ka Nifty 500 hai (jo stocks fail/delist hue wo nahi) -> numbers asli se zyada achhe dikhte hain.",
        f"2) Kamai kuch hi saalon se aayi. Jin saalon me PF < 1 tha: {', '.join(map(str, weak)) or 'koi nahi'}. Regime kharab ho to lambe losing patch aate hain "
        f"(backtest me lagataar {summ['max_loss_streak']} closed trades tak profit nahi bana; trades overlap karte hain).",
        f"3) Win rate ~{summ['win_pct']}% aur median trade {summ['median_ret']}% - 4 me se 3 trade SL par band honge. Profit kam bade winners se aata hai.",
        "4) Chalu saal ki row adhoori hai: jo winners abhi khule hain wo closed-trade stats me nahi aate, sirf jaldi SL hue losers aate hain.",
        "5) Health 'WEAK REGIME' ho to size aadha (ya paper trade). Pehle 4-6 hafte LIVE SCOREBOARD dekho, phir size badhao.",
        "6) Ye research tool hai, investment advice nahi. Position size aisa rakho ki lagataar 10 SL hit bhi jhel sako.",
    ]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="NSE top-up aur stale-check skip (testing)")
    ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("--rebuild-history", action="store_true")
    ap.add_argument("--symbols", default="", help="comma list (testing); default Nifty 500")
    a = ap.parse_args(argv)

    OUT.mkdir(parents=True, exist_ok=True)
    STATE.mkdir(parents=True, exist_ok=True)

    symbols = [s.strip().upper() for s in a.symbols.split(",") if s.strip()] or dt.fetch_universe()
    hist = dt.load_history(STATE / "history.csv.gz", symbols, rebuild=a.rebuild_history, offline=a.offline)
    f = add_features(hist)
    asof = f["DATE"].max()
    print(f"DATA: {hist.SYMBOL.nunique()} symbols | {hist.DATE.nunique()} sessions | latest {asof:%Y-%m-%d}")

    trades = bt.run_backtest(f)
    summ = bt.summarize(trades)
    yearly = bt.by_year(trades)
    gate_ok, gate_reason = bt.edge_gate(trades)
    hl = bt.health(trades, asof)
    behind = 0 if a.offline else dt.sessions_behind(asof)
    stale = behind > CFG.stale_sessions
    buy_ok = gate_ok and not stale
    if stale:
        banner = f"DATA STALE ({behind} sessions purana) - BUY band"
    elif not gate_ok:
        banner = f"BUY BAND: {gate_reason}"
    else:
        banner = "BUY ACTIVE | " + hl["label"]

    buy, watch, _ = latest_candidates(f)
    if not buy.empty:
        sz = buy.apply(lambda r: pd.Series(position_size(r["CLOSE"], r["STOP"], hl["mult"])), axis=1)
        buy = pd.concat([buy, sz], axis=1)
        buy = buy[buy["QTY"] > 0]

    led = lg.load(STATE / "signal_ledger.csv")
    if buy_ok:
        led = lg.add_signals(led, buy.head(CFG.max_new_per_day), asof)
    led = lg.update(led, f)
    lg.save(led, STATE / "signal_ledger.csv")
    open_t = lg.open_table(led, asof)
    score = lg.scoreboard(led)
    slots_free = max(0, CFG.max_positions - int(led.STATUS.isin(["ACTIVE", "PENDING"]).sum()))

    last = f[f.DATE == asof]
    ctx = dict(asof=asof, banner=banner, buy_ok=buy_ok, mult=hl["mult"], health_label=hl["label"], health=hl,
               buy=buy, watch=watch, open=open_t, slots_free=slots_free, bt=summ, by_year=yearly, score=score,
               n_symbols=hist.SYMBOL.nunique(), n_sessions=hist.DATE.nunique(),
               breadth50=float((last.CLOSE > last.EMA50).mean() * 100), breadth200=float((last.CLOSE > last.EMA200).mean() * 100),
               notes=notes(yearly, summ))

    # CSV artifacts (hamesha)
    (buy if buy_ok else buy.head(0)).to_csv(OUT / "action_plan_buy.csv", index=False)
    watch.head(CFG.watch_rows).to_csv(OUT / "watchlist.csv", index=False)
    open_t.to_csv(OUT / "open_signals.csv", index=False)
    trades.to_csv(OUT / "backtest_trades.csv", index=False)
    yearly.to_csv(OUT / "backtest_by_year.csv", index=False)
    led.to_csv(OUT / "signal_ledger.csv", index=False)
    print(f"RESULT | {banner} | new BUY {len(buy) if buy_ok else 0} | watch {len(watch)} | open {int(led.STATUS.isin(['ACTIVE','PENDING']).sum())}")
    print(f"BACKTEST | {summ}")

    if not a.no_publish:
        ok = pb.publish(pb.build_action_rows(ctx), pb.build_status_rows(ctx))
        if not ok and os.getenv("GITHUB_ACTIONS"):
            print("ERROR: GitHub Actions me GCP_CREDENTIALS zaroori hai")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

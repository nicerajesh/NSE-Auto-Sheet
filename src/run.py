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
import notify as nt            # noqa: E402
import positions as ps         # noqa: E402
import publish as pb           # noqa: E402
from config import CFG         # noqa: E402
from engine import add_features, latest_candidates, position_size  # noqa: E402
from v42 import add_v42_features, latest_v42_candidates            # noqa: E402
from quant_pro import (add_quant_pro_features, latest_quant_pro_candidates, position_size_quant_pro,
                      run_quant_pro_backtest, summarize_quant_pro, summarize_quant_pro_by_year, summarize_quant_pro_periods)  # noqa: E402
from recovery import add_recovery_features, latest_recovery_candidates, recovery_outcome_diagnostics  # noqa: E402
from portfolio_backtest import run_concurrent_portfolio_backtest, robustness_scenarios, audit_universe_history  # noqa: E402

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
        "5) Health 'WEAK REGIME' ho to size aadha. Real money me SIZE_STAGE_PCT se chhote size (25%) se shuru karo; 4-6 hafte LIVE SCOREBOARD dekh kar badhao.",
        "6) Ye research tool hai, investment advice nahi. Position size aisa rakho ki lagataar 10 SL hit bhi jhel sako.",
    ]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="NSE top-up aur stale-check skip (testing)")
    ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("--rebuild-history", action="store_true")
    ap.add_argument("--positions-csv", default=os.getenv("POSITIONS_CSV", ""), help="Sheet ke bina positions (testing)")
    ap.add_argument("--symbols", default="", help="comma list (testing); default Nifty 500")
    a = ap.parse_args(argv)

    OUT.mkdir(parents=True, exist_ok=True)
    STATE.mkdir(parents=True, exist_ok=True)

    symbols = [s.strip().upper() for s in a.symbols.split(",") if s.strip()] or dt.fetch_universe()
    hist = dt.load_history(STATE / "history.csv.gz", symbols, rebuild=a.rebuild_history, offline=a.offline)
    f = add_features(hist)
    f = add_v42_features(f)
    f = add_quant_pro_features(f)
    f = add_recovery_features(f)
    asof = f["DATE"].max()
    print(f"DATA: {hist.SYMBOL.nunique()} symbols | {hist.DATE.nunique()} sessions | latest {asof:%Y-%m-%d}")

    trades = bt.run_backtest(f)
    summ = bt.summarize(trades)
    yearly = bt.by_year(trades)
    gate_ok, gate_reason = bt.edge_gate(trades)
    hl = bt.health(trades, asof)
    behind = 0 if a.offline else dt.sessions_behind(asof)
    stale = behind > CFG.stale_sessions

    # ---- tumhari asli positions (Sheet ka MY POSITIONS tab ya CSV) ----
    book = None if a.no_publish else pb.open_book()
    raw_pos = pb.read_positions_rows(book) if book is not None else ps.load_csv(a.positions_csv)
    pos, pos_problems = ps.parse(raw_pos)
    mine = ps.evaluate(pos, f, asof)
    msum = ps.summarize(mine)
    guard = msum["dd_guard"]
    buy_ok = gate_ok and not stale and not guard
    if stale:
        banner = f"DATA STALE ({behind} sessions purana) - BUY band"
    elif not gate_ok:
        banner = f"BUY BAND: {gate_reason}"
    elif guard:
        banner = f"DRAWDOWN GUARD: open positions {msum['dd_pct']:.1f}% (limit -{CFG.dd_guard_pct}%) - naye BUY band"
    else:
        banner = "BUY ACTIVE | " + hl["label"]

    mult_total = round(hl["mult"] * CFG.stage_pct / 100, 3)
    buy, buy_watch, buy_v38, watch, _ = latest_candidates(f)
    if not buy.empty:
        sz = buy.apply(lambda r: pd.Series(position_size(r["CLOSE"], r["STOP"], mult_total)), axis=1)
        buy = pd.concat([buy, sz], axis=1)
        buy = buy[buy["QTY"] > 0]
    if not buy_watch.empty:
        # WATCH tier ka backtest PF kam hai (~1.7 vs strict ~2.2) - isliye size bhi jaan-bujhkar aadha
        sz = buy_watch.apply(lambda r: pd.Series(position_size(r["CLOSE"], r["STOP"], mult_total * 0.5)), axis=1)
        buy_watch = pd.concat([buy_watch, sz], axis=1)
        buy_watch = buy_watch[buy_watch["QTY"] > 0]
    if not buy_v38.empty:
        # V38 tier: koi trend/momentum/ADX filter nahi, backtest PF sabse kam (~1.3) - size sabse chhota
        sz = buy_v38.apply(lambda r: pd.Series(position_size(r["CLOSE"], r["STOP"], mult_total * CFG.v38_size_mult)), axis=1)
        buy_v38 = pd.concat([buy_v38, sz], axis=1)
        buy_v38 = buy_v38[buy_v38["QTY"] > 0]
    buy_v42 = latest_v42_candidates(f)
    if not buy_v42.empty:
        # V42 tier: apna score-engine (0-100), NIFTY ki jagah apna equal-weight universe regime proxy.
        # Backtest PF sabse kam (~1.19, production code) - size sabse chhota.
        sz = buy_v42.apply(lambda r: pd.Series(position_size(r["CLOSE"], r["STOP"], mult_total * CFG.v42_size_mult)), axis=1)
        buy_v42 = pd.concat([buy_v42, sz], axis=1)
        buy_v42 = buy_v42[buy_v42["QTY"] > 0]
    # Quant Pro V43: score + cost-aware backtest; market regime is a universe proxy, not NIFTY.
    buy_v43 = latest_quant_pro_candidates(f)
    if not buy_v43.empty:
        buy_v43 = buy_v43.copy()
        buy_v43["STOP"] = buy_v43["QP_STOP"]
        buy_v43["T1"], buy_v43["T2"], buy_v43["T3"] = buy_v43["QP_T1"], buy_v43["QP_T2"], buy_v43["QP_T3"]
        buy_v43["RISK_PCT"] = buy_v43["QP_RISK_PCT"]
        sz = buy_v43.apply(lambda r: pd.Series(position_size_quant_pro(r["CLOSE"], r["STOP"], mult_total)), axis=1)
        buy_v43 = pd.concat([buy_v43, sz], axis=1)
        buy_v43 = buy_v43[buy_v43["QTY"] > 0]
    qp_trades = run_quant_pro_backtest(f)
    qp_summary = summarize_quant_pro(qp_trades)
    qp_yearly = summarize_quant_pro_by_year(qp_trades)
    qp_periods = summarize_quant_pro_periods(qp_trades, split_year=2024)
    portfolio_trades, portfolio_summary = run_concurrent_portfolio_backtest(
        qp_trades, initial_capital=CFG.capital, risk_per_trade_pct=CFG.risk_per_trade_pct,
        max_positions=CFG.max_positions, max_open_risk_pct=CFG.max_open_risk_pct,
        max_single_position_pct=CFG.max_single_position_pct, cost_pct=0.35)
    cost_scenarios = robustness_scenarios(
        qp_trades, initial_capital=CFG.capital, risk_per_trade_pct=CFG.risk_per_trade_pct,
        max_positions=CFG.max_positions, max_open_risk_pct=CFG.max_open_risk_pct,
        max_single_position_pct=CFG.max_single_position_pct)
    universe_audit = audit_universe_history(hist, symbols)
    recovery_radar = latest_recovery_candidates(f)
    recovery_diagnostics = recovery_outcome_diagnostics(f)

    signals = buy                                    # paper ledger me sab signals (portfolio limit se pehle)

    # Keep every raw candidate for the report, but approve actionable rows through ONE shared risk gate.
    raw_tiers = {
        "STRICT BUY": buy.copy(), "WATCH": buy_watch.copy(), "V42": buy_v42.copy(),
        "V38": buy_v38.copy(), "V43 QUANT PRO": buy_v43.copy(),
    }
    held = set(pos["SYMBOL"]) if not pos.empty else set()
    slots_left = max(0, CFG.max_positions - msum["n_open"])
    budget_left = max(0.0, CFG.capital * CFG.max_open_risk_pct / 100 - msum["open_risk"])
    cash_left = max(0.0, CFG.capital - msum["deployed"])
    approved_tiers = {}
    # Priority: strict > watch > V42 > V38 > V43.
    for tier_name, frame in [("STRICT BUY", buy), ("WATCH", buy_watch), ("V42", buy_v42), ("V38", buy_v38), ("V43 QUANT PRO", buy_v43)]:
        approved = ps.fit_to_portfolio(frame, held, slots_left, budget_left, cash_left)
        approved_tiers[tier_name] = approved
        if not approved.empty:
            held.update(approved["SYMBOL"].astype(str))
            slots_left = max(0, slots_left - len(approved))
            budget_left = max(0.0, budget_left - float(approved["RISK_AMT"].sum()))
            cash_left = max(0.0, cash_left - float(approved["CAPITAL_USED"].sum()))
    buy = approved_tiers["STRICT BUY"]
    buy_watch = approved_tiers["WATCH"]
    buy_v42 = approved_tiers["V42"]
    buy_v38 = approved_tiers["V38"]
    buy_v43 = approved_tiers["V43 QUANT PRO"]

    review_rows = []
    for tier_name, raw in raw_tiers.items():
        accepted = approved_tiers[tier_name]
        accepted_map = accepted.set_index("SYMBOL").to_dict("index") if not accepted.empty else {}
        if raw is None or raw.empty:
            continue
        for _, candidate in raw.iterrows():
            row = candidate.to_dict()
            sym = str(row.get("SYMBOL", ""))
            approved = sym in accepted_map
            row["TIER"] = tier_name
            row["APPROVAL_STATUS"] = "APPROVED" if approved and buy_ok else ("BLOCKED - GLOBAL SAFETY GATE" if not buy_ok else "SIGNAL ONLY - RISK LIMIT")
            row["APPROVAL_REASON"] = ("Within slots/cash/open-risk limits" if approved and buy_ok else (banner if not buy_ok else "Held symbol, no slot, cash or risk budget left"))
            if approved:
                row.update(accepted_map[sym])
            review_rows.append(row)
    signal_review = pd.DataFrame(review_rows)
    led = lg.load(STATE / "signal_ledger.csv")
    if gate_ok and not stale:
        led = lg.add_signals(led, signals.head(CFG.max_new_per_day), asof)
    led = lg.update(led, f)
    lg.save(led, STATE / "signal_ledger.csv")
    open_t = lg.open_table(led, asof)
    score = lg.scoreboard(led)

    last = f[f.DATE == asof]
    ctx = dict(asof=asof, banner=banner, buy_ok=buy_ok, mult=hl["mult"], mult_total=mult_total, mine=mine, mine_sum=msum, mine_problems=pos_problems, health_label=hl["label"], health=hl,
               buy=buy, buy_watch=buy_watch, buy_v38=buy_v38, buy_v42=buy_v42, watch=watch, open=open_t, slots_free=slots_free, bt=summ, by_year=yearly, score=score,
               n_symbols=hist.SYMBOL.nunique(), n_sessions=hist.DATE.nunique(),
               breadth50=float((last.CLOSE > last.EMA50).mean() * 100), breadth200=float((last.CLOSE > last.EMA200).mean() * 100),
               notes=notes(yearly, summ), buy_v43=buy_v43, qp_summary=qp_summary, qp_trades=qp_trades, qp_yearly=qp_yearly, qp_periods=qp_periods,
               recovery_radar=recovery_radar, recovery_diagnostics=recovery_diagnostics,
               portfolio_summary=portfolio_summary, universe_audit=universe_audit, cost_scenarios=cost_scenarios,
               signal_review=signal_review)

    # CSV artifacts (hamesha)
    (buy if buy_ok else buy.head(0)).to_csv(OUT / "action_plan_buy.csv", index=False)
    (buy_watch if buy_ok else buy_watch.head(0)).to_csv(OUT / "action_plan_buy_watch.csv", index=False)
    (buy_v38 if buy_ok else buy_v38.head(0)).to_csv(OUT / "action_plan_buy_v38.csv", index=False)
    (buy_v42 if buy_ok else buy_v42.head(0)).to_csv(OUT / "action_plan_buy_v42.csv", index=False)
    (buy_v43 if buy_ok else buy_v43.head(0)).to_csv(OUT / "action_plan_buy_v43_quant_pro.csv", index=False)
    qp_trades.to_csv(OUT / "backtest_trades_v43_quant_pro.csv", index=False)
    pd.DataFrame([qp_summary]).to_csv(OUT / "backtest_summary_v43_quant_pro.csv", index=False)
    qp_yearly.to_csv(OUT / "backtest_by_year_v43_quant_pro.csv", index=False)
    qp_periods.to_csv(OUT / "backtest_period_split_v43_quant_pro.csv", index=False)
    portfolio_trades.to_csv(OUT / "backtest_concurrent_portfolio_v43.csv", index=False)
    pd.DataFrame([portfolio_summary]).to_csv(OUT / "backtest_concurrent_summary_v43.csv", index=False)
    cost_scenarios.to_csv(OUT / "backtest_cost_gap_stress_v43.csv", index=False)
    universe_audit.to_csv(OUT / "historical_universe_audit.csv", index=False)
    signal_review.to_csv(OUT / "signal_approval_review.csv", index=False)
    recovery_radar.to_csv(OUT / "recovery_radar.csv", index=False)
    recovery_diagnostics.to_csv(OUT / "recovery_history_diagnostic.csv", index=False)
    watch.head(CFG.watch_rows).to_csv(OUT / "watchlist.csv", index=False)
    open_t.to_csv(OUT / "open_signals.csv", index=False)
    mine.to_csv(OUT / "my_positions_status.csv", index=False)
    trades.to_csv(OUT / "backtest_trades.csv", index=False)
    yearly.to_csv(OUT / "backtest_by_year.csv", index=False)
    led.to_csv(OUT / "signal_ledger.csv", index=False)
    print(f"RESULT | {banner} | new BUY {len(buy) if buy_ok else 0} | watch {len(watch)} | open {int(led.STATUS.isin(['ACTIVE','PENDING']).sum())}")
    print(f"BACKTEST | {summ}")
    print(f"QUANT PRO V43 BACKTEST | {qp_summary}")

    if not a.no_publish:
        ok = pb.publish(pb.build_action_rows(ctx), pb.build_status_rows(ctx), pb.build_ry_rows(ctx),
                        pb.build_v38_rows(ctx), pb.build_v42_rows(ctx), book=book)
        if nt.send(nt.build_message(ctx)):
            print("TELEGRAM: alert bheja")
        if not ok and os.getenv("GITHUB_ACTIONS"):
            print("ERROR: GitHub Actions me GCP_CREDENTIALS zaroori hai")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

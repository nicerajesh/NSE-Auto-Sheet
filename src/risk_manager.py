"""Money-management layer, sitting ON TOP of the strategy/quality-gate layer.

Nothing here decides WHICH stocks are good setups (strategy.py / backtest.py /
quality_gate.py already do that). This module decides HOW MUCH to put behind
each signal and WHEN to stop putting new money in at all — position sizing,
portfolio-level exposure caps, and a drawdown kill-switch. A system that only
ever validates signal quality but sizes every trade the same and never caps
total exposure can still lose real money even when every individual signal
had a genuine statistical edge, simply from over-concentration or fat-tail
correlated losses.

Everything here is additive: it never changes ACTION/PUBLISHED_ACTION from
quality_gate.py or decision_engine.py. It only ever adds new columns
(POSITION_QTY, CAPITAL_ALLOCATED, RISK_AMOUNT, SECTOR, RISK_MANAGER_STATUS)
-- callers decide how/whether to reflect a non-PASS status in whatever
user-facing action text they use for that particular file.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from config import RISK

OPEN_STATUSES = {"OPEN", "HOLD", "T1 HIT / TRAIL", "T2 HIT / TRAIL"}
BUY_ACTIONS = {"PRE-BREAKOUT BUY", "BREAKOUT BUY", "SWING BUY"}


def _num(v, default=np.nan):
    try:
        x = float(v)
        return x if np.isfinite(x) else default
    except Exception:
        return default


def size_position(entry, stop, capital=None, risk_pct=None):
    """Fixed-fractional position sizing: risk a fixed % of capital on the
    entry-to-stop distance of THIS trade, not a fixed rupee amount or a fixed
    quantity. A wide-stop stock automatically gets a smaller quantity than a
    tight-stop stock for the same rupee risk.

    Returns (qty, capital_allocated, risk_amount). qty=0 if entry/stop are
    invalid (entry<=0, stop>=entry) — caller should treat that as "cannot
    size this trade", not "size 0 and proceed"."""
    capital = RISK.capital_base if capital is None else capital
    risk_pct = RISK.risk_per_trade_pct if risk_pct is None else risk_pct
    entry, stop = _num(entry), _num(stop)
    if not (np.isfinite(entry) and np.isfinite(stop)) or entry <= 0 or stop >= entry:
        return 0, 0.0, 0.0
    risk_per_share = entry - stop
    risk_amount = capital * (risk_pct / 100.0)
    qty = int(risk_amount // risk_per_share)
    if qty <= 0:
        return 0, 0.0, 0.0
    # Never let one position exceed max_single_position_pct of capital,
    # even if the stop is so tight that risk-based sizing would ask for it.
    max_capital_for_position = capital * (RISK.max_single_position_pct / 100.0)
    max_qty_by_capital = int(max_capital_for_position // entry)
    qty = min(qty, max_qty_by_capital) if max_qty_by_capital > 0 else 0
    if qty <= 0:
        return 0, 0.0, 0.0
    capital_allocated = round(qty * entry, 2)
    risk_amount = round(qty * risk_per_share, 2)
    return qty, capital_allocated, risk_amount


def _open_risk_from_ledger(ledger: pd.DataFrame) -> tuple[float, dict, int]:
    """Sum up risk-at-stake and sector exposure already committed by
    currently-open ledger positions, so new signals are sized against what's
    ALREADY on the book, not evaluated in isolation."""
    if ledger is None or ledger.empty:
        return 0.0, {}, 0
    open_rows = ledger[ledger["STATUS"].astype(str).isin(OPEN_STATUSES)]
    total_risk = 0.0
    sector_capital: dict = {}
    for _, r in open_rows.iterrows():
        entry, stop = _num(r.get("ENTRY")), _num(r.get("STOP_LOSS"))
        qty = _num(r.get("POSITION_QTY"), 0) or 0
        if np.isfinite(entry) and np.isfinite(stop) and qty > 0:
            total_risk += max(0.0, (entry - stop)) * qty
        sector = str(r.get("SECTOR", "") or "UNKNOWN")
        if np.isfinite(entry) and qty > 0:
            sector_capital[sector] = sector_capital.get(sector, 0.0) + entry * qty
    return total_risk, sector_capital, len(open_rows)


def check_drawdown_kill_switch(ledger: pd.DataFrame, risk=None) -> tuple[bool, str]:
    """Looks at the most recently CLOSED trades in the ledger (real, realised
    outcomes -- not backtest) and pauses new BUY publishing if the system has
    just been on a bad recent run, even if the long-run backtest still looks
    fine. A good long-run edge doesn't protect you from a live regime shift;
    this is the safety net for that.

    Returns (paused, reason). paused=False, reason='OK' when there isn't
    enough closed-trade history yet to judge (fails open, not closed --
    otherwise a brand-new deployment would permanently block itself)."""
    risk = RISK if risk is None else risk
    if ledger is None or ledger.empty or "EXIT_PRICE" not in ledger.columns:
        return False, "OK"
    closed = ledger[ledger["STATUS"].astype(str).isin({"EXIT", "T3 HIT / EXIT"})].copy()
    if closed.empty:
        return False, "OK"
    if "EXIT_DATE" in closed.columns:
        closed = closed.sort_values("EXIT_DATE")
    closed = closed.tail(risk.drawdown_lookback_trades)
    if len(closed) < 3:
        return False, "OK"

    def _ret(r):
        entry, exitp = _num(r.get("ENTRY")), _num(r.get("EXIT_PRICE"))
        if not (np.isfinite(entry) and np.isfinite(exitp)) or entry <= 0:
            return np.nan
        return (exitp - entry) / entry * 100

    rets = closed.apply(_ret, axis=1).dropna()
    if rets.empty:
        return False, "OK"

    consecutive_losses = 0
    for v in rets.iloc[::-1]:
        if v < 0:
            consecutive_losses += 1
        else:
            break
    if consecutive_losses >= risk.drawdown_max_consecutive_losses:
        return True, f"CONSECUTIVE_LOSSES_{consecutive_losses}"
    if rets.sum() <= risk.drawdown_max_recent_loss_pct:
        return True, f"RECENT_DRAWDOWN_{round(rets.sum(),1)}PCT"
    return False, "OK"


def apply_risk_management(df: pd.DataFrame, ledger: pd.DataFrame, sector_map: dict | None = None, risk=None) -> pd.DataFrame:
    """Main entry point. Adds POSITION_QTY / CAPITAL_ALLOCATED / RISK_AMOUNT /
    SECTOR / RISK_MANAGER_STATUS to every actionable row, enforces:
      - per-trade sizing (fixed-fractional risk)
      - max concurrent open positions (existing open ledger + new adds today)
      - max sector exposure (only enforced when a sector is actually known --
        never silently blocks everything just because sector data is missing)
      - max total portfolio risk-at-stake
      - the drawdown kill-switch above
    RISK_MANAGER_STATUS is 'PASS' when sized and cleared, or a BLOCKED_* /
    N/A_* reason otherwise -- callers reflect that in their own action text
    (e.g. appending it to USER_ACTION) rather than this function silently
    rewriting a column another module owns."""
    risk = RISK if risk is None else risk
    sector_map = sector_map or {}
    if df is None or df.empty:
        return df

    out = df.copy()
    for col in ("POSITION_QTY", "CAPITAL_ALLOCATED", "RISK_AMOUNT"):
        out[col] = 0
    out["SECTOR"] = out["SYMBOL"].astype(str).map(sector_map).fillna("UNKNOWN") if "SYMBOL" in out.columns else "UNKNOWN"
    out["RISK_MANAGER_STATUS"] = "N/A"

    kill_switch_on, kill_reason = check_drawdown_kill_switch(ledger, risk)
    open_risk, sector_capital, open_positions = _open_risk_from_ledger(ledger)
    max_portfolio_risk_amt = risk.capital_base * (risk.max_portfolio_risk_pct / 100.0)
    max_sector_amt = risk.capital_base * (risk.max_sector_exposure_pct / 100.0)
    remaining_slots = max(0, risk.max_concurrent_positions - open_positions)

    action_col = "PUBLISHED_ACTION" if "PUBLISHED_ACTION" in out.columns else ("ACTION" if "ACTION" in out.columns else None)
    if action_col is None:
        return out

    running_risk = open_risk
    running_sector = dict(sector_capital)
    slots_used = 0

    for idx, row in out.iterrows():
        action = str(row.get(action_col, ""))
        if action not in BUY_ACTIONS:
            continue
        gate_val = row.get("QUALITY_GATE")
        if gate_val is not None and str(gate_val) != "PASS":
            # quality_gate.py already blocked this signal on backtest/edge
            # grounds -- risk-manager only sizes/caps signals that already
            # cleared that bar, it never re-judges signal quality itself.
            out.at[idx, "RISK_MANAGER_STATUS"] = "N/A_GATE_BLOCKED"
            continue
        if kill_switch_on:
            out.at[idx, "RISK_MANAGER_STATUS"] = f"BLOCKED_DRAWDOWN_{kill_reason}"
            continue
        entry = row.get("IDEAL_ENTRY") or row.get("ENTRY_PRICE") or row.get("CMP")
        stop = row.get("STOP_LOSS")
        qty, cap_alloc, risk_amt = size_position(entry, stop, risk.capital_base, risk.risk_per_trade_pct)
        if qty <= 0:
            out.at[idx, "RISK_MANAGER_STATUS"] = "BLOCKED_UNSIZEABLE"
            continue
        if slots_used >= remaining_slots:
            out.at[idx, "RISK_MANAGER_STATUS"] = "BLOCKED_MAX_POSITIONS"
            continue
        if running_risk + risk_amt > max_portfolio_risk_amt:
            out.at[idx, "RISK_MANAGER_STATUS"] = "BLOCKED_MAX_PORTFOLIO_RISK"
            continue
        sector = str(row.get("SECTOR", "UNKNOWN"))
        if sector != "UNKNOWN" and running_sector.get(sector, 0.0) + cap_alloc > max_sector_amt:
            out.at[idx, "RISK_MANAGER_STATUS"] = f"BLOCKED_SECTOR_CAP_{sector}"
            continue
        out.at[idx, "POSITION_QTY"] = qty
        out.at[idx, "CAPITAL_ALLOCATED"] = cap_alloc
        out.at[idx, "RISK_AMOUNT"] = risk_amt
        out.at[idx, "RISK_MANAGER_STATUS"] = "PASS"
        running_risk += risk_amt
        running_sector[sector] = running_sector.get(sector, 0.0) + cap_alloc
        slots_used += 1

    return out

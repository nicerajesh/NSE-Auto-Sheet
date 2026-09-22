"""Telegram alerts (optional). TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID set ho tabhi chalta hai.

Sirf kaam ki cheezein bhejta hai: SL raise / exit / naye BUY / data ya gate ki warning.
Kuch actionable na ho to koi message nahi (spam nahi).
"""
from __future__ import annotations

import os

import pandas as pd


def build_message(ctx: dict) -> str | None:
    lines: list[str] = []
    mine = ctx.get("mine")
    if mine is not None and not mine.empty:
        act = mine[mine["PRIORITY"].isin([0, 1, 2])]
        for _, r in act.iterrows():
            lines.append(f"- {r['SYMBOL']}: {r['ACTION']}")
    if lines:
        lines.insert(0, "MERI POSITIONS - KAAM:")
    buy = ctx.get("buy")
    buy_lines = []
    if ctx.get("buy_ok") and buy is not None and not buy.empty:
        for _, r in buy.iterrows():
            buy_lines.append(f"- {r['SYMBOL']} ({r['SETUP']}) buy ~{r['CLOSE']:.2f} (max {r['CLOSE'] * 1.02:.2f}) | SL {r['STOP']:.2f} | "
                             f"T1 {r['T1']:.2f} T2 {r['T2']:.2f} T3 {r['T3']:.2f} | qty {int(r['QTY'])}")
    if buy_lines:
        lines += ["", "NAYE BUY (agle open par, gap > 2% ho to skip):"] + buy_lines
    if not ctx.get("buy_ok"):
        lines += ["", f"BUY BAND: {ctx.get('banner', '')}"]
    if not lines:
        return None
    head = f"RY APEX | data {pd.Timestamp(ctx['asof']):%d-%b-%Y} | size {ctx.get('mult_total', ctx.get('mult'))}x"
    return (head + "\n" + "\n".join(lines))[:3800]


def send(text: str | None) -> bool:
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not text or not token or not chat:
        return False
    try:
        import requests
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat, "text": text}, timeout=20)
        if r.status_code != 200:
            print("Telegram warning:", r.status_code, r.text[:120])
            return False
        return True
    except Exception as e:  # noqa: BLE001
        print("Telegram warning:", e)
        return False

"""Intraday artifact validator.

Intraday research stays in GitHub Actions artifacts. It deliberately does not
create or modify Google Sheets, so the workbook remains limited to the two
canonical daily tabs.
"""
from pathlib import Path
import os
import pandas as pd
from csv_utils import safe_read_csv

OUT = Path(os.getenv("NSE_OUTPUT_DIR", "output"))

def main():
    path = OUT / "intraday_buy_signals.csv"
    buy = safe_read_csv(path) if path.exists() else pd.DataFrame()
    if not buy.empty and "INTRADAY_ACTION" in buy.columns:
        buy = buy[buy["INTRADAY_ACTION"].astype(str).str.upper().eq("INTRADAY BUY")]
    if not buy.empty and "SYMBOL" in buy.columns:
        buy = buy.drop_duplicates("SYMBOL", keep="first")
    print(f"INTRADAY ARTIFACT READY | BUY={len(buy)} | GOOGLE_SHEETS_WRITE=DISABLED")

if __name__ == "__main__":
    main()

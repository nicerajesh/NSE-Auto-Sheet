from __future__ import annotations
import os, sys
from datetime import datetime, timedelta
from d1_database import setup, query

# Persistent D1 policy: never delete historical market data during normal runs.
# The scanner should fetch only dates missing after D1's latest trade_date.

def latest_trade_date():
    data=query("SELECT MAX(trade_date) AS max_date, COUNT(*) AS rows FROM bhavcopy",required=True)
    row=(data.get('result',[{}])[0].get('results') or [{}])[0]
    return row.get('max_date'), int(row.get('rows') or 0)

def bootstrap_needed():
    d,n=latest_trade_date()
    return not d or n == 0

def main():
    setup()
    d,n=latest_trade_date()
    if not d:
        print('D1 INCREMENTAL: EMPTY — bootstrap full history is required on first run')
        print('D1_FETCH_MODE=BOOTSTRAP')
        return 0
    print(f'D1 INCREMENTAL: retained {n} bhavcopy rows through {d}')
    print('D1_FETCH_MODE=DAILY_ONLY')
    print(f'D1_LATEST_DATE={d}')
    return 0

if __name__=='__main__': raise SystemExit(main())

from __future__ import annotations
import os
from d1_database import query, setup

# Destructive reset requested for the D1 trading database.
# Drops only application tables; setup() recreates and verifies the canonical schema.
TABLES=['trades','signals','indicators','daily_snapshots','backtest_results','bhavcopy']

def main():
    if not os.getenv('CLOUDFLARE_API_TOKEN') or not os.getenv('CLOUDFLARE_ACCOUNT_ID'):
        raise RuntimeError('Cloudflare D1 credentials missing')
    for table in TABLES:
        query(f'DROP TABLE IF EXISTS {table}', required=True)
        print(f'D1 RESET: dropped {table}')
    setup()
    print('D1 RESET COMPLETE: fresh canonical schema created and verified')

if __name__=='__main__': main()

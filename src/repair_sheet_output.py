from __future__ import annotations
import os, json
from pathlib import Path
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from csv_utils import safe_to_csv, safe_read_csv
from simple_dashboard import build_action_plan

OUT = Path('output')
DEFAULT_SHEET_ID = '1U9j5fMZAWPUSwoP_U-GKdacVke9nUjspqPR3wGsWAUM'


def _credentials():
    raw = os.getenv('GCP_CREDENTIALS', '')
    if not raw: raise RuntimeError('GCP_CREDENTIALS missing')
    return Credentials.from_service_account_info(json.loads(raw), scopes=['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive'])


def _clean(v):
    if v is None: return ''
    if isinstance(v, (dict, list, tuple, set)): return json.dumps(v, sort_keys=True, default=str)
    try:
        if pd.isna(v): return ''
    except Exception: pass
    if hasattr(v, 'item'):
        try: return v.item()
        except Exception: pass
    return v


def _matrix(df):
    if df is None or df.empty: return [['NO DATA']]
    return [[str(c) for c in df.columns]] + [[_clean(v) for v in row] for row in df.itertuples(index=False, name=None)]


def _write(ws, df):
    matrix = _matrix(df)
    needed_rows = max(10, len(matrix) + 5)
    needed_cols = max(20, max((len(r) for r in matrix), default=1) + 2)
    try:
        if ws.row_count < needed_rows: ws.add_rows(needed_rows - ws.row_count)
        if ws.col_count < needed_cols: ws.add_cols(needed_cols - ws.col_count)
    except Exception as e: print(f'{ws.title}: grid expansion warning: {e}')
    try: ws.clear()
    except Exception as e: print(f'{ws.title}: clear warning: {e}')
    ws.update(range_name='A1', values=matrix, value_input_option='USER_ENTERED')
    try: ws.freeze(rows=1)
    except Exception: pass


def _open_sheet(gc):
    url = os.getenv('GOOGLE_SHEET_URL') or os.getenv('SHEET_URL')
    return gc.open_by_url(url) if url else gc.open_by_key(os.getenv('SPREADSHEET_ID') or DEFAULT_SHEET_ID)


def _read(name, default=None):
    p = OUT / name
    if not p.exists(): return default if default is not None else pd.DataFrame()
    return safe_read_csv(p)


def _v2_master():
    p = OUT / 'master_buy_decision_v2.csv'
    if not p.exists(): raise RuntimeError('output/master_buy_decision_v2.csv missing; finalize_outputs.py must run first')
    df = safe_read_csv(p)
    if df.empty: return pd.DataFrame(columns=['RANK','SYMBOL','FINAL_ACTION','QUALITY_GATE','SIGNAL_TYPE'])
    if 'SYMBOL' not in df.columns: raise RuntimeError('master_buy_decision_v2.csv has no SYMBOL column')
    if 'FINAL_ACTION' not in df.columns: df['FINAL_ACTION'] = '⚪ WATCH'
    if 'QUALITY_GATE' not in df.columns: df['QUALITY_GATE'] = 'UNKNOWN'
    final = df['FINAL_ACTION'].astype(str).str.upper()
    # V2 is the single source of truth. BUY ON BREAKOUT/PULLBACK are actionable
    # BUYs, BUY ON TRIGGER and RR-low are WAIT, everything else is WATCH/blocked.
    df['SIGNAL_TYPE'] = 'WATCH'
    df.loc[final.str.contains('BUY ON BREAKOUT|BUY ON PULLBACK', regex=True, na=False), 'SIGNAL_TYPE'] = 'BUY'
    df.loc[final.str.contains('BUY ON TRIGGER', regex=True, na=False), 'SIGNAL_TYPE'] = 'WAIT'
    df.loc[final.str.contains('WAIT', regex=False, na=False), 'SIGNAL_TYPE'] = 'WAIT'
    df.loc[final.str.contains('WATCH|BLOCKED|AVOID', regex=True, na=False), 'SIGNAL_TYPE'] = 'WATCH'
    priority = {'BUY':1, 'WAIT':2, 'WATCH':3}
    df['_P'] = df['SIGNAL_TYPE'].map(priority).fillna(9)
    score = pd.to_numeric(df.get('HUNTER_SCORE', pd.Series(0, index=df.index)), errors='coerce').fillna(0)
    df['_S'] = score
    df = df.sort_values(['_P','_S'], ascending=[True,False]).drop(columns=['_P','_S'])
    if 'RANK' in df.columns: df['RANK'] = range(1, len(df)+1)
    return df.reset_index(drop=True)


def build_master_buy_dashboard():
    v2 = _v2_master()
    if v2.empty: return v2
    cols = ['RANK','SYMBOL','SIGNAL_TYPE','FINAL_ACTION','CMP','IDEAL_ENTRY','BUY_ZONE','MAX_BUY_PRICE','BREAKOUT_TRIGGER','STOP_LOSS','TARGET_1','TARGET_2','TARGET_3','RISK_PCT','EDGE_CONFIDENCE','EDGE_CONFIDENCE_LABEL','POSITION_QTY','CAPITAL_ALLOCATED','RISK_AMOUNT','RISK_MANAGER_STATUS','QUALITY_GATE','ACTION','WHY','DECISION_REASON','MARKET_REGIME_V2']
    cols = [c for c in cols if c in v2.columns]
    return v2[cols].copy()


def _summary_row(master, plan):
    empty = pd.Series(dtype=object)
    buys = int((master.get('SIGNAL_TYPE', empty) == 'BUY').sum()) if not master.empty else 0
    waits = int((master.get('SIGNAL_TYPE', empty) == 'WAIT').sum()) if not master.empty else 0
    watches = int((master.get('SIGNAL_TYPE', empty) == 'WATCH').sum()) if not master.empty else 0
    exits = int(plan.get('KYA KARU', empty).astype(str).str.contains('EXIT|BECHO', regex=True).sum()) if not plan.empty else 0
    return pd.DataFrame([{'TYPE':'TODAY SUMMARY','CONFIRMED BUY':buys,'WAIT/TRIGGER':waits,'WATCH':watches,'EXIT':exits,'STATUS':'ACTION PLAN AVAILABLE' if not plan.empty else 'NO CONFIRMED ACTIONS'}])


def main():
    master = build_master_buy_dashboard()
    safe_to_csv(master, OUT / 'master_buy_dashboard.csv')
    plan = build_action_plan()
    safe_to_csv(plan, OUT / 'mera_action_plan.csv')
    hunter = _read('decision_candidates.csv', _read('early_hunter.csv'))
    commands = _read('trading_commands.csv')
    buy = _read('buy_candidates.csv')
    dash = _read('dashboard.csv')
    low52 = _read('low52_reversal.csv')
    apex = _read('apex_matrix.csv')
    stealth = _read('stealth_accumulation.csv')
    action_sheet = commands if not commands.empty else plan
    if action_sheet.empty: action_sheet = _summary_row(master, plan)
    gc = gspread.authorize(_credentials())
    sh = _open_sheet(gc)
    def get_or_create(title, rows=3000, cols=100):
        try: return sh.worksheet(title)
        except gspread.WorksheetNotFound: return sh.add_worksheet(title=title, rows=rows, cols=cols)
    ws_plan = get_or_create('MERA ACTION PLAN', max(100,len(plan)+10), 20)
    _write(ws_plan, plan if not plan.empty else _summary_row(master, plan))
    try:
        ws_plan.format('A1:Z1', {'textFormat': {'bold': True, 'fontSize': 12}, 'backgroundColor': {'red':0.85,'green':0.85,'blue':0.85}})
        if not plan.empty and 'KYA KARU' in plan.columns:
            for i,val in enumerate(plan['KYA KARU'].astype(str), start=2):
                if 'BECHO' in val or 'EXIT' in val: color={'red':1.0,'green':0.85,'blue':0.85}
                elif 'KHARIDO' in val: color={'red':0.83,'green':0.96,'blue':0.83}
                elif 'WAIT' in val or 'TRIGGER' in val: color={'red':1.0,'green':0.95,'blue':0.75}
                elif 'HOLD' in val: color={'red':1.0,'green':0.97,'blue':0.78}
                else: color={'red':0.93,'green':0.93,'blue':0.93}
                ws_plan.format(f'A{i}:Z{i}', {'backgroundColor':color})
    except Exception as e: print('MERA ACTION PLAN format warning:', e)
    try: ws_plan.update_index(0)
    except Exception as e: print('MERA ACTION PLAN reorder warning:', e)
    _write(get_or_create('Aaj Kya Karna Hai', max(100,len(action_sheet)+10), 30), action_sheet)
    _write(get_or_create('Master Buy Dashboard', max(100,len(master)+10), max(30,len(master.columns)+2 if not master.empty else 30)), master if not master.empty else _summary_row(master,plan))
    _write(get_or_create('Buy Candidates', max(100,len(buy)+10), max(30,len(buy.columns)+2 if not buy.empty else 30)), buy if not buy.empty else pd.DataFrame([{'STATUS':'NO CONFIRMED BUY TODAY','NOTE':'See Master Buy Dashboard / MERA ACTION PLAN for WAIT and WATCH setups.'}]))
    _write(get_or_create('Early Hunter', max(100,len(hunter)+10), max(40,len(hunter.columns)+2 if not hunter.empty else 40)), hunter)
    _write(get_or_create('52 Week Low Rocket', max(100,len(low52)+10), max(25,len(low52.columns)+2 if not low52.empty else 25)), low52)
    _write(get_or_create('APEX Matrix', max(100,len(apex)+10), max(25,len(apex.columns)+2 if not apex.empty else 25)), apex)
    _write(get_or_create('Stealth Accumulation', max(100,len(stealth)+10), max(25,len(stealth.columns)+2 if not stealth.empty else 25)), stealth)
    if not dash.empty: _write(get_or_create('Dashboard', max(100,len(dash)+10), max(40,len(dash.columns)+2)), dash)
    print('SHEET PUBLISH OK:', {'plan':len(plan),'commands':len(commands),'action_sheet':len(action_sheet),'master_buy_dashboard':len(master),'confirmed_buy_candidates':len(buy),'decision_candidates':len(hunter),'low52':len(low52),'apex':len(apex),'stealth':len(stealth)})


if __name__ == '__main__': main()

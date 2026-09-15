import os,json
from pathlib import Path
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
OUT=Path('output'); DEFAULT='1U9j5fMZAWPUSwoP_U-GKdacVke9nUjspqPR3wGsWAUM'

def df(name):
 p=OUT/name; return pd.read_csv(p) if p.exists() else pd.DataFrame()
def clean(x):
 try:return '' if pd.isna(x) else x.item() if hasattr(x,'item') else x
 except Exception:return x
def write(ws,d):
 m=[list(d.columns)]+[[clean(x) for x in r] for r in d.itertuples(index=False,name=None)] if not d.empty else [['NO DATA']]
 if ws.row_count<len(m)+2:ws.add_rows(len(m)+2-ws.row_count)
 if ws.col_count<max(20,len(m[0])+2):ws.add_cols(max(20,len(m[0])+2)-ws.col_count)
 ws.clear();ws.update('A1',m,value_input_option='USER_ENTERED');ws.freeze(rows=1)
def main():
 raw=os.getenv('GCP_CREDENTIALS',''); assert raw,'GCP_CREDENTIALS missing'
 cred=Credentials.from_service_account_info(json.loads(raw),scopes=['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive'])
 gc=gspread.authorize(cred); url=os.getenv('GOOGLE_SHEET_URL') or os.getenv('SHEET_URL'); sh=gc.open_by_url(url) if url else gc.open_by_key(os.getenv('SPREADSHEET_ID') or DEFAULT)
 def ws(n):
  try:return sh.worksheet(n)
  except gspread.WorksheetNotFound:return sh.add_worksheet(title=n,rows=500,cols=50)
 core=df('core_trend_matrix.csv'); diag=df('decision_diagnostic_report.csv')
 write(ws('Core Trend Matrix'),core.head(250)); write(ws('Decision Diagnostics'),diag)
 print('DIAGNOSTIC SHEETS PUBLISHED',len(core),len(diag))
if __name__=='__main__':main()

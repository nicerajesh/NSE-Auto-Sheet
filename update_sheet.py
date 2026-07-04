import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import requests
from datetime import datetime, timedelta
import os
import json
import time
# =========================================================
# 1. Credentials Setup
# =========================================================
creds_json = os.environ.get('GCP_CREDENTIALS')
if not creds_json:
    print("CRITICAL: GCP_CREDENTIALS secret missing!")
    exit(1)
creds_dict = json.loads(creds_json)
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)
# ⚠️ अपनी गूगल शीट की ID यहाँ डालें (URL के बीच का हिस्सा)
spreadsheet_id = "1U9j5fMZAWPUSwoP_U-GKdacVke9nUjspqPR3wGsWAUM"
try:
    ws_volume = client.open_by_key(spreadsheet_id).worksheet("Top 250 Stocks")
    ws_turnover = client.open_by_key(spreadsheet_id).worksheet("Top 250 Turnover")
except Exception as e:
    print(f"Sheet Connection Error: {e}")
    exit(1)
# =========================================================
# 2. NSE "Full Bhavcopy + Deliverable Data" fetcher
#    इस एक फाइल में Volume, Turnover और Delivery% तीनों मिलते हैं
# =========================================================
def get_session():
    """NSE कभी-कभी बिना cookie के block कर देता है, इसलिए पहले होमपेज खोलकर cookie ले लेते हैं"""
    session = requests.Session()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    session.headers.update(headers)
    try:
        session.get("https://www.nseindia.com", timeout=10)
    except Exception:
        pass
    return session
def fetch_full_bhavdata(session, date_obj):
    date_str = date_obj.strftime("%d%m%Y")
    url = f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{date_str}.csv"
    print(f"--- तारीख {date_obj.strftime('%d-%m-%Y')} चेक कर रहे हैं: {url}")
    try:
        response = session.get(url, timeout=20)
        if response.status_code != 200 or len(response.content) < 500:
            print(f"   NSE ने {response.status_code} दिया / फाइल खाली है।")
            return None
        from io import StringIO
        df = pd.read_csv(StringIO(response.text))
        # NSE की फाइल में column names के आगे-पीछे स्पेस होते हैं, उन्हें साफ करना
        df.columns = [c.strip() for c in df.columns]
        for col in ['SYMBOL', 'SERIES']:
            if col in df.columns:
                df[col] = df[col].astype(str).str.strip()
        required = ['SYMBOL', 'SERIES', 'CLOSE_PRICE', 'TTL_TRD_QNTY', 'TURNOVER_LACS', 'DELIV_QTY', 'DELIV_PER']
        if not all(c in df.columns for c in required):
            print(f"   ज़रूरी कॉलम नहीं मिले। मिले कॉलम: {list(df.columns)}")
            return None
        # सिर्फ EQ सीरीज (असली इक्विटी शेयर, डेरिवेटिव/बॉन्ड नहीं)
        df = df[df['SERIES'] == 'EQ']
        # ETF / Gold / Silver / Liquid फंड्स हटाना — ये "स्टॉक" नहीं हैं
        filter_keywords = 'BEES|ETF|GOLD|LIQUID|CASE|SILVER|LIQ'
        df = df[~df['SYMBOL'].str.contains(filter_keywords, case=False, na=False)]
        # numeric conversion (DELIV_PER अक्सर '-' होता है जब delivery data उपलब्ध नहीं)
        for c in ['CLOSE_PRICE', 'TTL_TRD_QNTY', 'TURNOVER_LACS', 'DELIV_QTY', 'DELIV_PER']:
            df[c] = pd.to_numeric(df[c], errors='coerce')
        df['DELIV_PER'] = df['DELIV_PER'].fillna(0)
        df = df.dropna(subset=['CLOSE_PRICE', 'TTL_TRD_QNTY', 'TURNOVER_LACS'])
        # बहुत छोटे/illiquid शेयर हटाना (₹1 लाख से कम टर्नओवर वाले दिन में मायने नहीं रखते)
        df = df[df['TURNOVER_LACS'] > 1]
        # -----------------------------------------------------------------
        # ध्यान दें: दोनों शीट्स का column-structure अलग है, इसलिए दोनों के
        # लिए अलग-अलग column set भेजना ज़रूरी है:
        #
        # "Top 250 Stocks" शीट में A-C raw data है (Code, Volume, Close Price),
        #   D से आगे (CMP, DMA, Bull Run, CAR...) सारे formulas हैं —
        #   उन्हें छेड़ना नहीं है, वरना formulas डिलीट हो जाएँगे।
        #
        # "Top 250 Turnover" शीट में A-F raw data है (Code, Volume, Close,
        #   Turnover, Delivery Qty, Delivery %), G से आगे formulas हैं।
        # -----------------------------------------------------------------
        cols_out_vol = ['SYMBOL', 'TTL_TRD_QNTY', 'CLOSE_PRICE']
        cols_out_turnover = ['SYMBOL', 'TTL_TRD_QNTY', 'CLOSE_PRICE', 'TURNOVER_LACS', 'DELIV_QTY', 'DELIV_PER']
        # लिस्ट A: Volume के आधार पर टॉप 250
        df_vol = df.sort_values(by='TTL_TRD_QNTY', ascending=False).head(250)
        data_vol = df_vol[cols_out_vol].values.tolist()
        # लिस्ट B: Turnover के आधार पर टॉप 250 (Delivery% साथ में)
        df_turnover = df.sort_values(by='TURNOVER_LACS', ascending=False).head(250)
        data_turnover = df_turnover[cols_out_turnover].values.tolist()
        return data_vol, data_turnover
    except Exception as e:
        print(f"   Error: {e}")
        return None
# =========================================================
# 3. Execution Logic — पिछले 10 दिन तक चेक करना (छुट्टियों के लिए बफर)
# =========================================================
session = get_session()
date = datetime.now()
data_vol_to_insert = None
data_turnover_to_insert = None
fetched_date_str = ""
for i in range(10):
    test_date = date - timedelta(days=i)
    if test_date.weekday() >= 5:  # शनि/रवि छोड़ें
        continue
    result = fetch_full_bhavdata(session, test_date)
    if result:
        data_vol_to_insert, data_turnover_to_insert = result
        fetched_date_str = test_date.strftime('%d-%b-%Y')
        break
    time.sleep(1)  # NSE सर्वर पर एक साथ बहुत सारे रिक्वेस्ट न जाएं
def ensure_min_cols(worksheet, min_cols):
    """अगर शीट में status message वाले कॉलम तक जगह नहीं है, तो जरूरत भर कॉलम जोड़ दो
    (यह मौजूदा A-J / A-T formulas को नहीं छेड़ता, सिर्फ आगे नए खाली कॉलम जोड़ता है)"""
    if worksheet.col_count < min_cols:
        worksheet.add_cols(min_cols - worksheet.col_count)
# =========================================================
# 4. Google Sheet अपडेट
#    "Top 250 Stocks"   -> A:C राव डेटा (D से आगे formulas हैं, छूना नहीं)
#    "Top 250 Turnover" -> A:F राव डेटा (G से आगे formulas हैं, छूना नहीं)
#    Status message दोनों शीट्स में formulas वाले कॉलमों के आगे, खाली कॉलम में डाला जाता है
# =========================================================
STATUS_COL_VOLUME = 'L'      # Top 250 Stocks: formulas A-J तक हैं, इसलिए L सुरक्षित है
STATUS_COL_TURNOVER = 'V'    # Top 250 Turnover: formulas A-T तक हैं, इसलिए V सुरक्षित है
if data_vol_to_insert and data_turnover_to_insert:
    try:
        # शीट में जगह पक्का करें — status column लिखने से पहले (वरना "exceeds grid limits" एरर आता है)
        ensure_min_cols(ws_volume, 12)     # L = 12वाँ कॉलम
        ensure_min_cols(ws_turnover, 22)   # V = 22वाँ कॉलम
        # केवल raw-data कॉलम ही क्लियर करें, formula कॉलम नहीं
        ws_volume.batch_clear(['A2:C251'])
        ws_volume.update(range_name='A2', values=data_vol_to_insert)
        ws_turnover.batch_clear(['A2:F251'])
        ws_turnover.update(range_name='A2', values=data_turnover_to_insert)
        ist_now = (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime('%d-%b %H:%M')
        status_msg = f"Data Date: {fetched_date_str} | Last Update: {ist_now} (IST)"
        ws_volume.update(range_name=f'{STATUS_COL_VOLUME}2', values=[[status_msg]])
        ws_turnover.update(range_name=f'{STATUS_COL_TURNOVER}2', values=[[status_msg]])
        print(f"SUCCESS: दोनों शीट्स {fetched_date_str} के डेटा से अपडेट हो गई हैं (Volume + Turnover + Delivery% सहित)!")
    except Exception as e:
        print(f"Google Sheet अपडेट करने में एरर: {e}")
        exit(1)
else:
    print("FAILED: पिछले 10 दिनों में से किसी भी दिन की फाइल नहीं मिली।")
    exit(1)

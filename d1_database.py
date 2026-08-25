from __future__ import annotations
import json, math, os, urllib.request, urllib.error
from pathlib import Path
API='https://api.cloudflare.com/client/v4'
DB_ID=os.getenv('D1_DATABASE_ID','e6652e85-b927-4f11-b790-45fb6ee818f2')
ACTIONABLE={'BUY NOW','BUY ON BREAKOUT','BREAKOUT IMMINENT'}

def _cfg():
    token=os.getenv('CLOUDFLARE_API_TOKEN','').strip(); account=os.getenv('CLOUDFLARE_ACCOUNT_ID','').strip()
    return (token,account) if token and account else None

def _clean(v):
    if v is None:return None
    try:
        if hasattr(v,'item'):v=v.item()
        if isinstance(v,float) and not math.isfinite(v):return None
        return v
    except Exception:return None

def _clean_params(params):return [_clean(v) for v in (params or [])]

def _post(url,token,payload,timeout=120):
    payload=json.loads(json.dumps(payload,separators=(',',':'),allow_nan=False))
    req=urllib.request.Request(url,data=json.dumps(payload,separators=(',',':'),allow_nan=False).encode('utf-8'),method='POST',headers={'Authorization':f'Bearer {token}','Content-Type':'application/json','Accept':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r:data=json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:raise RuntimeError(f'D1 HTTP {e.code}: {e.read().decode(errors="replace")}')
    if not data.get('success'):raise RuntimeError(json.dumps(data))
    return data

def query(sql,params=None,required=False):
    cfg=_cfg()
    if not cfg:
        if required:raise RuntimeError('CLOUDFLARE_API_TOKEN/CLOUDFLARE_ACCOUNT_ID missing')
        return None
    token,account=cfg; url=f'{API}/accounts/{account}/d1/database/{DB_ID}/query'; body={'sql':sql}
    if params is not None:body['params']=_clean_params(params)
    return _post(url,token,body,120)

def load_open_trades(required=False):
    try:
        data=query("SELECT id,symbol,signal_date,entry_date,entry_price,stop_loss,target1,target2,target3,exit_date,exit_price,exit_reason,status FROM trades WHERE status NOT IN ('EXIT','T3 HIT / EXIT') ORDER BY id",required=required)
        if not data:return []
        return data.get('result',[{}])[0].get('results',[]) or []
    except Exception:
        if required: raise
        return []

def sync_ledger(ledger,required=False):
    if ledger is None or len(ledger)==0:return
    items=[]
    for _,r in ledger.iterrows():
        sym=str(r.get('SYMBOL','')).strip()
        if not sym:continue
        status=str(r.get('STATUS','OPEN'))
        items.append({'sql':"UPDATE trades SET exit_date=?,exit_price=?,exit_reason=?,status=? WHERE symbol=? AND status NOT IN ('EXIT','T3 HIT / EXIT')",'params':[str(r.get('EXIT_DATE','') or '') or None,_clean(r.get('EXIT_PRICE')),str(r.get('EXIT_REASON','') or '') or None,status,sym]})
    for i in range(0,len(items),50):batch(items[i:i+50],required=required)

def batch(items,required=False):
    cfg=_cfg()
    if not cfg:
        if required:raise RuntimeError('CLOUDFLARE_API_TOKEN/CLOUDFLARE_ACCOUNT_ID missing')
        return None
    clean=[]
    for item in items:
        sql=str(item.get('sql','')).strip().rstrip(';'); params=_clean_params(item.get('params') or [])
        if not sql:continue
        if len(params)>90:raise RuntimeError(f'D1 statement has {len(params)} bound parameters; maximum is 100')
        clean.append({'sql':sql,'params':params})
    if not clean:return None
    token,account=cfg; url=f'{API}/accounts/{account}/d1/database/{DB_ID}/raw'
    return _post(url,token,{'batch':clean},120)

def setup():
    schema=Path(__file__).with_name('d1_schema.sql').read_text(encoding='utf-8'); query(schema,required=True)
    rows=query("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name",required=True)['result'][0].get('results',[])
    found={r['name'] for r in rows}; expected={'bhavcopy','indicators','signals','trades','backtest_results','daily_snapshots'}
    missing=expected-found
    if missing:raise RuntimeError('D1 schema verification failed: '+', '.join(sorted(missing)))
    print('D1 schema OK:',', '.join(sorted(found)))

def _f(v):
    try:
        if v in ('',None):return None
        x=float(v);return x if math.isfinite(x) else None
    except Exception:return None

def sync_latest(latest,hunter,stats,run_date,gate_ok=False):
    if _cfg() is None:print('D1 disabled: Cloudflare secrets not configured');return
    setup();items=[]
    for r in latest.itertuples(index=False):
        items.append({'sql':'INSERT INTO bhavcopy(symbol,trade_date,open,high,low,close,volume,turnover_lacs,delivery_qty,delivery_pct) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(symbol,trade_date) DO UPDATE SET open=excluded.open,high=excluded.high,low=excluded.low,close=excluded.close,volume=excluded.volume,turnover_lacs=excluded.turnover_lacs,delivery_qty=excluded.delivery_qty,delivery_pct=excluded.delivery_pct','params':[str(r.SYMBOL),str(r.DATE)[:10],_f(r.OPEN_PRICE),_f(r.HIGH_PRICE),_f(r.LOW_PRICE),_f(r.CLOSE_PRICE),int(_f(r.TTL_TRD_QNTY) or 0),_f(r.TURNOVER_LACS),int(_f(r.DELIV_QTY) or 0),_f(r.DELIV_PER)]})
    for r in hunter.itertuples(index=False):
        vals=lambda n:_f(getattr(r,n,'')); action=str(r.ACTION)
        items.append({'sql':'INSERT INTO signals(symbol,signal_date,action,stage,score,structure,cmp,recent_low,first_hh,higher_low,second_hh,buy_zone_low,buy_zone_high,entry_trigger,stop_loss,target1,target2,target3,rr1,rr2,rr3,resistance,reasons) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(symbol,signal_date) DO UPDATE SET action=excluded.action,stage=excluded.stage,score=excluded.score,structure=excluded.structure,cmp=excluded.cmp,recent_low=excluded.recent_low,first_hh=excluded.first_hh,higher_low=excluded.higher_low,second_hh=excluded.second_hh,buy_zone_low=excluded.buy_zone_low,buy_zone_high=excluded.buy_zone_high,entry_trigger=excluded.entry_trigger,stop_loss=excluded.stop_loss,target1=excluded.target1,target2=excluded.target2,target3=excluded.target3,rr1=excluded.rr1,rr2=excluded.rr2,rr3=excluded.rr3,resistance=excluded.resistance,reasons=excluded.reasons','params':[str(r.SYMBOL),str(run_date),action,str(r.STAGE),int(_f(r.HUNTER_SCORE) or 0),str(getattr(r,'STRUCTURE','')),vals('CMP'),vals('RECENT_LOW'),vals('FIRST_HH'),vals('HIGHER_LOW'),vals('SECOND_HH'),vals('BUY_ZONE_LOW'),vals('BUY_ZONE_HIGH'),vals('ENTRY_TRIGGER'),vals('STOP_LOSS'),vals('TARGET_1'),vals('TARGET_2'),vals('TARGET_3'),vals('RR_T1'),vals('RR_T2'),vals('RR_T3'),vals('RESISTANCE'),str(getattr(r,'REASONS',''))]})
        items.append({'sql':'INSERT INTO daily_snapshots(symbol,snapshot_date,action,stage,score,cmp,entry_trigger,stop_loss,target1,target2,target3,structure) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(symbol,snapshot_date) DO UPDATE SET action=excluded.action,stage=excluded.stage,score=excluded.score,cmp=excluded.cmp,entry_trigger=excluded.entry_trigger,stop_loss=excluded.stop_loss,target1=excluded.target1,target2=excluded.target2,target3=excluded.target3,structure=excluded.structure','params':[str(r.SYMBOL),str(run_date),action,str(r.STAGE),int(_f(r.HUNTER_SCORE) or 0),vals('CMP'),vals('ENTRY_TRIGGER'),vals('STOP_LOSS'),vals('TARGET_1'),vals('TARGET_2'),vals('TARGET_3'),str(getattr(r,'STRUCTURE',''))]})
        if gate_ok and action in ACTIONABLE:
            entry=vals('ENTRY_TRIGGER') if action in ('BUY ON BREAKOUT','BREAKOUT IMMINENT') else vals('CMP')
            items.append({'sql':"INSERT INTO trades(symbol,signal_date,entry_date,entry_price,stop_loss,target1,target2,target3,status) SELECT ?,?,?,?,?,?,?,?,'OPEN' WHERE NOT EXISTS(SELECT 1 FROM trades WHERE symbol=? AND status NOT IN ('EXIT','T3 HIT / EXIT'))",'params':[str(r.SYMBOL),str(run_date),str(run_date),entry,vals('STOP_LOSS'),vals('TARGET_1'),vals('TARGET_2'),vals('TARGET_3'),str(r.SYMBOL)]})
    for i in range(0,len(items),10):batch(items[i:i+10],required=True)
    if stats:
        min_score=int(os.getenv('MIN_SCORE','82'))
        query('INSERT INTO backtest_results(run_date,min_score,trades,win_rate_pct,avg_return_pct,median_return_pct,stop_rate_pct,target1_hit_pct,target2_hit_pct,target3_hit_pct,profit_factor,avg_hold_days) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',[str(run_date),min_score,int(stats.get('trades',0)),_f(stats.get('win_rate_pct',0)),_f(stats.get('avg_return_pct',0)),_f(stats.get('median_return_pct',0)),_f(stats.get('stop_rate_pct',0)),_f(stats.get('t1_hit_pct',0)),_f(stats.get('t2_hit_pct',0)),_f(stats.get('t3_hit_pct',0)),_f(stats.get('profit_factor',0)),_f(stats.get('avg_hold_days',0))],required=True)
    print(f'D1 sync complete: {len(latest)} market rows + {len(hunter)} signals | gate_ok={gate_ok}')

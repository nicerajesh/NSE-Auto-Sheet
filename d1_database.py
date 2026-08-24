from __future__ import annotations
import json, os, urllib.request, urllib.error
from pathlib import Path

API='https://api.cloudflare.com/client/v4'
DB_ID=os.getenv('D1_DATABASE_ID','e6652e85-b927-4f11-b790-45fb6ee818f2')


def _cfg():
    token=os.getenv('CLOUDFLARE_API_TOKEN','').strip()
    account=os.getenv('CLOUDFLARE_ACCOUNT_ID','').strip()
    if not token or not account:
        return None
    return token, account


def query(sql, params=None, *, required=False):
    cfg=_cfg()
    if not cfg:
        if required: raise RuntimeError('CLOUDFLARE_API_TOKEN/CLOUDFLARE_ACCOUNT_ID missing')
        return None
    token,account=cfg
    url=f'{API}/accounts/{account}/d1/database/{DB_ID}/query'
    body={'sql':sql}
    if params is not None: body['params']=list(params)
    req=urllib.request.Request(url,data=json.dumps(body).encode(),method='POST',headers={'Authorization':f'Bearer {token}','Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=60) as r: data=json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        detail=e.read().decode(errors='replace')
        raise RuntimeError(f'Cloudflare D1 HTTP {e.code}: {detail}')
    if not data.get('success'):
        raise RuntimeError(json.dumps(data))
    return data


def batch(items, *, required=False):
    cfg=_cfg()
    if not cfg:
        if required: raise RuntimeError('CLOUDFLARE_API_TOKEN/CLOUDFLARE_ACCOUNT_ID missing')
        return None
    token,account=cfg
    url=f'{API}/accounts/{account}/d1/database/{DB_ID}/query'
    req=urllib.request.Request(url,data=json.dumps({'batch':items}).encode(),method='POST',headers={'Authorization':f'Bearer {token}','Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=90) as r: data=json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f'Cloudflare D1 HTTP {e.code}: {e.read().decode(errors="replace")}')
    if not data.get('success'):
        raise RuntimeError(json.dumps(data))
    return data


def setup():
    schema=Path(__file__).with_name('d1_schema.sql').read_text(encoding='utf-8')
    query(schema,required=True)
    rows=query("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name",required=True)['result'][0].get('results',[])
    found={r['name'] for r in rows}
    expected={'bhavcopy','indicators','signals','trades','backtest_results','daily_snapshots'}
    missing=expected-found
    if missing: raise RuntimeError('D1 schema verification failed: '+', '.join(sorted(missing)))
    print('D1 schema OK:', ', '.join(sorted(found)))


def sync_latest(latest,hunter,stats,run_date):
    if _cfg() is None:
        print('D1 disabled: Cloudflare secrets not configured')
        return
    setup()
    # Keep D1 writes bounded: current-day market data + qualified signal history.
    items=[]
    for r in latest.itertuples(index=False):
        items.append({'sql':'''INSERT INTO bhavcopy(symbol,trade_date,open,high,low,close,volume,turnover_lacs,delivery_qty,delivery_pct) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(symbol,trade_date) DO UPDATE SET open=excluded.open,high=excluded.high,low=excluded.low,close=excluded.close,volume=excluded.volume,turnover_lacs=excluded.turnover_lacs,delivery_qty=excluded.delivery_qty,delivery_pct=excluded.delivery_pct''','params':[str(r.SYMBOL),str(r.DATE)[:10],float(r.OPEN_PRICE),float(r.HIGH_PRICE),float(r.LOW_PRICE),float(r.CLOSE_PRICE),int(r.TTL_TRD_QNTY),float(r.TURNOVER_LACS),int(r.DELIV_QTY) if str(r.DELIV_QTY)!='nan' else 0,float(r.DELIV_PER)]})
    for r in hunter.itertuples(index=False):
        def f(name):
            v=getattr(r,name,'')
            try:return float(v) if v not in ('',None) else None
            except:return None
        items.append({'sql':'''INSERT INTO signals(symbol,signal_date,action,stage,score,structure,cmp,recent_low,first_hh,higher_low,second_hh,buy_zone_low,buy_zone_high,entry_trigger,stop_loss,target1,target2,target3,rr1,rr2,rr3,resistance,reasons) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(symbol,signal_date) DO UPDATE SET action=excluded.action,stage=excluded.stage,score=excluded.score,structure=excluded.structure,cmp=excluded.cmp,recent_low=excluded.recent_low,first_hh=excluded.first_hh,higher_low=excluded.higher_low,second_hh=excluded.second_hh,buy_zone_low=excluded.buy_zone_low,buy_zone_high=excluded.buy_zone_high,entry_trigger=excluded.entry_trigger,stop_loss=excluded.stop_loss,target1=excluded.target1,target2=excluded.target2,target3=excluded.target3,rr1=excluded.rr1,rr2=excluded.rr2,rr3=excluded.rr3,resistance=excluded.resistance,reasons=excluded.reasons''','params':[str(r.SYMBOL),str(run_date),str(r.ACTION),str(r.STAGE),int(r.HUNTER_SCORE),str(r.STRUCTURE),f('CMP'),f('RECENT_LOW'),f('FIRST_HH'),f('HIGHER_LOW'),f('SECOND_HH'),f('BUY_ZONE_LOW'),f('BUY_ZONE_HIGH'),f('ENTRY_TRIGGER'),f('STOP_LOSS'),f('TARGET_1'),f('TARGET_2'),f('TARGET_3'),f('RR_T1'),f('RR_T2'),f('RR_T3'),f('RESISTANCE'),str(getattr(r,'REASONS',''))]})
        items.append({'sql':'''INSERT INTO daily_snapshots(symbol,snapshot_date,action,stage,score,cmp,entry_trigger,stop_loss,target1,target2,target3,structure) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(symbol,snapshot_date) DO UPDATE SET action=excluded.action,stage=excluded.stage,score=excluded.score,cmp=excluded.cmp,entry_trigger=excluded.entry_trigger,stop_loss=excluded.stop_loss,target1=excluded.target1,target2=excluded.target2,target3=excluded.target3,structure=excluded.structure''','params':[str(r.SYMBOL),str(run_date),str(r.ACTION),str(r.STAGE),int(r.HUNTER_SCORE),f('CMP'),f('ENTRY_TRIGGER'),f('STOP_LOSS'),f('TARGET_1'),f('TARGET_2'),f('TARGET_3'),str(r.STRUCTURE)]})
    for i in range(0,len(items),50): batch(items[i:i+50],required=True)
    if stats:
        query('''INSERT INTO backtest_results(run_date,min_score,trades,win_rate_pct,avg_return_pct,median_return_pct,stop_rate_pct,target1_hit_pct,target2_hit_pct,target3_hit_pct,profit_factor,avg_hold_days) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',[str(run_date),68,int(stats.get('trades',0)),float(stats.get('win_rate_pct',0)),float(stats.get('avg_return_pct',0)),float(stats.get('median_return_pct',0)),float(stats.get('stop_rate_pct',0)),float(stats.get('t1_hit_pct',0)),float(stats.get('t2_hit_pct',0)),float(stats.get('t3_hit_pct',0)),float(stats.get('profit_factor',0)),float(stats.get('avg_hold_days',0))],required=True)
    print(f'D1 sync complete: {len(latest)} market rows + {len(hunter)} signals')

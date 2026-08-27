from pathlib import Path
import pandas as pd
from quality_gate import evaluate

OUT=Path('output')


def main():
    hunter_path=OUT/'early_hunter.csv'
    stats_path=OUT/'backtest_summary.csv'
    cal_path=OUT/'score_calibration.csv'
    if not hunter_path.exists() or not stats_path.exists():
        raise RuntimeError('Required scanner outputs are missing')
    hunter=pd.read_csv(hunter_path)
    stats=pd.read_csv(stats_path).iloc[0].to_dict()
    cal=pd.read_csv(cal_path) if cal_path.exists() else pd.DataFrame()
    ok,reason=evaluate(stats,cal)
    hunter['QUALITY_GATE']='PASS' if ok else reason
    # Historical event confidence is used only when a bucket has enough observations.
    def confidence(r):
        try: score=float(r.get('PRE_BREAKOUT_SCORE',r.get('HUNTER_SCORE',0)))
        except Exception: score=0
        action=str(r.get('ACTION',''))
        if not cal.empty and {'ANALYSIS','ACTION','SCORE_BUCKET','BREAKOUT_RATE','TRADES'}.issubset(cal.columns):
            q=cal[(cal.ANALYSIS=='BREAKOUT_EVENT') & (cal.ACTION==action)].copy()
            bucket='90+' if score>=90 else '82-89' if score>=82 else '75-81' if score>=75 else '68-74' if score>=68 else '<68'
            q=q[(q.SCORE_BUCKET.astype(str)==bucket)&(q.TRADES>=5)]
            if not q.empty and pd.notna(q.BREAKOUT_RATE.iloc[0]): return round(float(q.BREAKOUT_RATE.iloc[0]),1)
        try:return min(90.0,max(0.0,float(r.get('BREAKOUT_PROBABILITY',0))))
        except Exception:return 0.0
    hunter['BREAKOUT_CONFIDENCE']=hunter.apply(confidence,axis=1) if not hunter.empty else pd.Series(dtype=float)
    # Never publish a model BUY when the historical quality gate fails.
    if not ok and not hunter.empty:
        mask=hunter.ACTION.isin({'PRE-BREAKOUT BUY','BREAKOUT BUY','SWING BUY'})
        hunter.loc[mask,'PUBLISHED_ACTION']='QUALITY BLOCKED'
    else:
        hunter['PUBLISHED_ACTION']=hunter.get('ACTION','WATCH')
    hunter.to_csv(hunter_path,index=False)
    hunter[hunter.get('PUBLISHED_ACTION','WATCH').isin({'PRE-BREAKOUT BUY','BREAKOUT BUY','SWING BUY'})].to_csv(OUT/'buy_candidates.csv',index=False)
    stats['quality_gate']='PASS' if ok else reason
    pd.DataFrame([stats]).to_csv(stats_path,index=False)
    print(f'FINAL QUALITY GATE={reason} | BUY PUBLISHED={int((hunter.PUBLISHED_ACTION.isin({"PRE-BREAKOUT BUY","BREAKOUT BUY","SWING BUY"})).sum()) if not hunter.empty else 0}')

if __name__=='__main__': main()

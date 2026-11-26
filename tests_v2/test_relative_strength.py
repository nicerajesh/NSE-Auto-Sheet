import pandas as pd
import ry_apex_v2.portfolio as p

def test_relative_strength_keeps_leaders_during_weak_breadth(monkeypatch):
    from ry_apex_v2.engine import score_relative_strength_row
    row=pd.Series({
        "CLOSE":120.0,"EMA20":115.0,"EMA50":110.0,"EMA50_RISING":True,
        "ATR_PCT":3.0,"ADX14":25.0,"MOM_RANK":92.0,"RS_RANK":96.0,
        "ROC126":24.0,"TURNOVER_CR":5.0,"VOL_RATIO":2.0,
        "BREADTH50":22.0,"BREADTH200":18.0,"BREAKOUT":True,"PULLBACK":False
    })
    score,signal,reason=score_relative_strength_row(row)
    assert signal=="APEX RS BUY"
    assert score>=80
    assert reason=="RELATIVE STRENGTH LEADER"

def test_relative_strength_reduces_risk_when_market_breadth_is_weak(monkeypatch):
    dates=pd.bdate_range("2025-01-01",periods=3)
    rows=[]
    for sym in ("AAA","BBB","CCC"):
        for i,day in enumerate(dates):
            rows.append({
                "SYMBOL":sym,"DATE":day,"OPEN":100.0,"HIGH":102.0,"LOW":99.0,
                "CLOSE":101.0+i,"ATR14":2.0,"BREADTH50":20.0,"BREADTH200":15.0
            })
    f=pd.DataFrame(rows)
    monkeypatch.setattr(p,"score_relative_strength_row",lambda r:(95,"APEX RS BUY","TEST") if r.DATE==dates[0] else (0,"WATCH","NO"))
    trades,curve,stats=p.simulate_portfolio(
        f,capital=100000,risk_pct=1.0,max_total_risk_pct=3.0,
        max_positions=8,max_position_pct=20.0,cost_pct=0.6,max_hold=99,
        strategy="relative_strength"
    )
    assert stats["max_open_risk_rs"]<=1500.0
    assert stats["max_open_positions"]<=4

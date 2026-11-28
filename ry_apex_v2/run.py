from __future__ import annotations
import json,os
from pathlib import Path
import pandas as pd
from .config import CFG
from .data import universe,load_history
from .engine import build_features,generate_signals
from .backtest import run_backtest,metrics,walk_forward
from .portfolio import allocate_candidates,simulate_portfolio,build_signal_cache
from .mj_portfolio import run_mj_scenarios
from .mj_robustness import run_robustness_matrix

def main():
 out=Path(CFG.output_dir); out.mkdir(parents=True,exist_ok=True); syms=universe(); hist=load_history(syms); f=build_features(hist); asof=pd.to_datetime(f.DATE).max()
 behind=max(0,len(pd.bdate_range(asof+pd.Timedelta(days=1),pd.Timestamp.now().normalize())))
 signals=generate_signals(f); trades=run_backtest(f); m=metrics(trades); wf=walk_forward(trades); test=wf["test_2023_plus"]; recent=wf["test_2025_plus"]
 gate=(test["trades"]>=60 and test["profit_factor"]>=1.15 and test["expectancy_pct"]>0 and recent["trades"]>=20 and recent["expectancy_pct"]>0)
 if behind>CFG.stale_sessions:signals.loc[signals.SIGNAL.eq("APEX BUY"),["SIGNAL","REASON"]]=["REJECT","STALE DATA"]
 elif not gate:signals.loc[signals.SIGNAL.eq("APEX BUY"),["SIGNAL","REASON"]]=["WATCH","BACKTEST GATE FAILED - PAPER ONLY"]
 signals=allocate_candidates(signals,CFG.starting_capital,CFG.risk_per_trade_pct,CFG.max_portfolio_risk_pct,CFG.max_positions,CFG.max_position_pct)
 signals.to_csv(out/"signals.csv",index=False); trades.to_csv(out/"backtest_trades.csv",index=False)
 # Precompute rankings once, then reuse them across capital scenarios.
 apex_cache=build_signal_cache(f,"apex")
 rs_cache=build_signal_cache(f,"relative_strength")
 # User has not specified deployable capital: publish a capital sensitivity grid, not an assumed account size.
 scenarios={}
 for capital in (100000,300000,500000,1000000):
  pt,curve,stats=simulate_portfolio(f,capital=capital,risk_pct=CFG.risk_per_trade_pct,max_total_risk_pct=CFG.max_portfolio_risk_pct,max_positions=CFG.max_positions,max_position_pct=CFG.max_position_pct,cost_pct=CFG.cost_pct,max_hold=CFG.max_hold,signal_cache=apex_cache)
  tag=f"{capital//1000}k"
  pt.to_csv(out/f"portfolio_trades_{tag}.csv",index=False); curve.to_csv(out/f"portfolio_equity_{tag}.csv",index=False)
  scenarios[str(capital)]=stats
 relative_strength_scenarios={}
 for capital in (100000,300000,500000,1000000):
  rpt,req,rs_stats=simulate_portfolio(f,capital=capital,risk_pct=CFG.risk_per_trade_pct,max_total_risk_pct=CFG.max_portfolio_risk_pct,max_positions=CFG.max_positions,max_position_pct=CFG.max_position_pct,cost_pct=CFG.cost_pct,max_hold=CFG.max_hold,strategy="relative_strength",signal_cache=rs_cache)
  tag=f"{capital//1000}k"
  rpt.to_csv(out/f"rs_portfolio_trades_{tag}.csv",index=False); req.to_csv(out/f"rs_portfolio_equity_{tag}.csv",index=False)
  relative_strength_scenarios[str(capital)]=rs_stats
 mj_portfolio_scenarios=run_mj_scenarios(hist,out)
 mj_robustness=run_robustness_matrix(hist,out)
 report={"version":"2.3.0","as_of":str(asof.date()),"sessions_behind":behind,"universe_symbols":int(hist.SYMBOL.nunique()),"event_backtest":m,"walk_forward":wf,"live_buy_gate":bool(gate and behind<=CFG.stale_sessions),"signal_counts":signals.SIGNAL.value_counts().to_dict(),"allocated_buys":int(signals.SIGNAL.eq("APEX BUY").sum()),"portfolio_backtest_scenarios":scenarios,"relative_strength_portfolio_scenarios":relative_strength_scenarios,"m_j_portfolio_scenarios":mj_portfolio_scenarios,"m_j_robustness":mj_robustness,"portfolio_method":"Daily ranked signals at close; next-session open fills; shared cash; 0.5% equity risk per trade; 3% aggregate open stop risk; max 8 concurrent positions; max 15% capital per position; 0.60% round-trip cost; stop gap fills at open; end-of-test liquidation.","relative_strength_method":"Cross-sectional 126d and 252d momentum ranks; price above rising EMA50; ADX >=18; breakout or pullback trigger; liquidity and ATR filters. Does not reject a stock solely because market breadth is weak. In weak breadth (<40% above EMA50 or <30% above EMA200), risk is reduced to 0.25% per position, 1.5% aggregate stop risk, max 4 concurrent positions; otherwise standard risk limits apply.","m_j_portfolio_method":mj_portfolio_scenarios["method"],"note":"Research only. Current-universe survivorship bias remains. No point-in-time constituents, full corporate-action/dividend audit or market-impact model. OHLC stop ordering is conservative. Not a promise of future returns."}
 (out/"report.json").write_text(json.dumps(report,indent=2,default=str)); print(json.dumps(report,indent=2,default=str))
 if os.getenv("GITHUB_ACTIONS") and behind>CFG.stale_sessions:raise SystemExit("Refusing to publish actionable signals: stale market data")
if __name__=="__main__":main()

CREATE TABLE IF NOT EXISTS bhavcopy (symbol TEXT NOT NULL, trade_date TEXT NOT NULL, open REAL, high REAL, low REAL, close REAL NOT NULL, volume INTEGER, turnover_lacs REAL, delivery_qty INTEGER, delivery_pct REAL, PRIMARY KEY(symbol, trade_date));
CREATE INDEX IF NOT EXISTS idx_bhavcopy_date ON bhavcopy(trade_date);
CREATE INDEX IF NOT EXISTS idx_bhavcopy_symbol_date ON bhavcopy(symbol, trade_date);

CREATE TABLE IF NOT EXISTS indicators (symbol TEXT NOT NULL, trade_date TEXT NOT NULL, close REAL, ema20 REAL, ema50 REAL, ema100 REAL, ema200 REAL, rsi14 REAL, macd REAL, macd_signal REAL, macd_hist REAL, adx14 REAL, atr14 REAL, atr_pct REAL, volume_ratio REAL, delivery_pct REAL, delivery_avg10 REAL, ret5 REAL, ret20 REAL, distance_52w_high REAL, distance_ema200 REAL, PRIMARY KEY(symbol, trade_date));
CREATE INDEX IF NOT EXISTS idx_indicators_date ON indicators(trade_date);

CREATE TABLE IF NOT EXISTS signals (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, signal_date TEXT NOT NULL, action TEXT, stage TEXT, score INTEGER, structure TEXT, cmp REAL, recent_low REAL, first_hh REAL, higher_low REAL, second_hh REAL, buy_zone_low REAL, buy_zone_high REAL, entry_trigger REAL, stop_loss REAL, target1 REAL, target2 REAL, target3 REAL, rr1 REAL, rr2 REAL, rr3 REAL, resistance REAL, reasons TEXT, UNIQUE(symbol, signal_date));
CREATE INDEX IF NOT EXISTS idx_signals_date ON signals(signal_date);
CREATE INDEX IF NOT EXISTS idx_signals_action ON signals(action);

CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, signal_date TEXT, entry_date TEXT, entry_price REAL, stop_loss REAL, target1 REAL, target2 REAL, target3 REAL, exit_date TEXT, exit_price REAL, exit_reason TEXT, status TEXT DEFAULT 'OPEN', target1_hit INTEGER DEFAULT 0, target2_hit INTEGER DEFAULT 0, target3_hit INTEGER DEFAULT 0, stop_hit INTEGER DEFAULT 0, net_return_pct REAL, holding_days INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);

CREATE TABLE IF NOT EXISTS backtest_results (id INTEGER PRIMARY KEY AUTOINCREMENT, run_date TEXT NOT NULL, min_score INTEGER, trades INTEGER, win_rate_pct REAL, avg_return_pct REAL, median_return_pct REAL, stop_rate_pct REAL, target1_hit_pct REAL, target2_hit_pct REAL, target3_hit_pct REAL, profit_factor REAL, avg_hold_days REAL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS daily_snapshots (symbol TEXT NOT NULL, snapshot_date TEXT NOT NULL, action TEXT, stage TEXT, score INTEGER, cmp REAL, entry_trigger REAL, stop_loss REAL, target1 REAL, target2 REAL, target3 REAL, structure TEXT, PRIMARY KEY(symbol, snapshot_date));
CREATE INDEX IF NOT EXISTS idx_snapshots_date ON daily_snapshots(snapshot_date);

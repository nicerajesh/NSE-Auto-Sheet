import pandas as pd

import data as dt


def _bars(symbols):
    rows = []
    for symbol in symbols:
        for date, close in [("2026-10-19", 10.0), ("2026-10-20", 11.0)]:
            rows.append({
                "SYMBOL": symbol, "DATE": pd.Timestamp(date), "OPEN": close,
                "HIGH": close + 1, "LOW": close - 1, "CLOSE": close, "VOLUME": 1000,
            })
    return pd.DataFrame(rows)


def test_positions_history_loads_held_symbols_separately(monkeypatch):
    monkeypatch.setattr(dt, "bootstrap_history", lambda symbols: _bars(["BIKAJI"]))
    monkeypatch.setattr(dt, "top_up", lambda hist, symbols: hist)
    result = dt.load_positions_history(["BIKAJI", "KELLTONTEC"], offline=True)
    assert set(result["SYMBOL"]) == {"BIKAJI"}
    assert result["DATE"].max() == pd.Timestamp("2026-10-20")


def test_positions_history_skips_top_up_offline(monkeypatch):
    monkeypatch.setattr(dt, "bootstrap_history", lambda symbols: _bars(symbols))
    def fail_top_up(*args, **kwargs):
        raise AssertionError("offline mode must not call NSE top-up")
    monkeypatch.setattr(dt, "top_up", fail_top_up)
    result = dt.load_positions_history(["BIKAJI"], offline=True)
    assert len(result) == 2


def test_positions_history_handles_no_available_symbols(monkeypatch):
    def fail_bootstrap(symbols):
        raise RuntimeError("no files")
    monkeypatch.setattr(dt, "bootstrap_history", fail_bootstrap)
    result = dt.load_positions_history(["NOTFOUND"], offline=True)
    assert result.empty
    assert list(result.columns) == ["SYMBOL", "DATE", "OPEN", "HIGH", "LOW", "CLOSE", "VOLUME"]

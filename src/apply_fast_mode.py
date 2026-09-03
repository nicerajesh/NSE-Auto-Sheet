from __future__ import annotations

import os
from pathlib import Path


def main() -> None:
    if os.getenv("FAST_MODE", "0").strip().lower() not in {"1", "true", "yes", "on"}:
        print("FAST MODE: disabled (full audit)")
        return

    path = Path(__file__).resolve().parent / "update_sheet.py"
    text = path.read_text(encoding="utf-8")
    if "from fast_model_cache import" in text:
        print("FAST MODE: patch already present")
        return

    marker = "from csv_utils import safe_to_csv\n"
    if marker not in text:
        raise RuntimeError("FAST MODE patch marker missing in update_sheet.py")
    imports = marker + "from fast_model_cache import low52 as fast_low52, apex as fast_apex, stealth as fast_stealth, main_backtest as fast_main_backtest, cached_walk_forward\n"
    text = text.replace(marker, imports, 1)

    replacements = {
        "low52_trades,low52_stats=run_backtest_low52(hist)": "low52_trades,low52_stats=fast_low52(lambda: run_backtest_low52(hist))",
        "apex_trades,apex_stats=run_backtest_apex(hist)": "apex_trades,apex_stats=fast_apex(lambda: run_backtest_apex(hist))",
        "stealth_trades,stealth_stats=run_backtest_stealth(hist)": "stealth_trades,stealth_stats=fast_stealth(lambda: run_backtest_stealth(hist))",
        "trades,stats,cal=run_backtest(hist,MIN_SCORE,BT.horizon)": "trades,stats,cal=fast_main_backtest(lambda: run_backtest(hist,MIN_SCORE,BT.horizon))",
        "wf_summary,wf_ok,wf_reason=walk_forward_consistency(trades)": "wf_summary,wf_ok,wf_reason=cached_walk_forward(walk_forward_consistency,trades)",
    }
    missing = [old for old in replacements if old not in text]
    if missing:
        raise RuntimeError("FAST MODE patch targets missing: " + " | ".join(missing))
    for old, new in replacements.items():
        text = text.replace(old, new, 1)

    path.write_text(text, encoding="utf-8")
    print("FAST MODE: daily scanner will reuse cached backtest/validation and skip expensive backtests")


if __name__ == "__main__":
    main()

import pandas as pd
from v7_false_breakout_validation import classify


def test_classify_marks_only_breakout_diagnostics():
    d = pd.DataFrame({
        "ACTION": ["BREAKOUT BUY", "BREAKOUT BUY"],
        "SCORE": [90, 82],
        "RETURN_PCT": [2.0, -3.0],
        "MFE_PCT": [1.0, 4.0],
        "MAE_PCT": [-4.0, -1.0],
    })
    out = classify(d)
    assert list(out.SCORE_BUCKET.astype(str)) == ["90+", "82-89"]
    assert out.POST_OUTCOME_FALSE_BREAKOUT.tolist() == [1, 0]

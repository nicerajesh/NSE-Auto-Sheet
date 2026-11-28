import pandas as pd
from unittest.mock import MagicMock

import publish as pb


def test_swing_rows_are_single_clean_table_with_exact_headers():
    report = pd.DataFrame([{
        "STOCK": "AAA", "SIGNAL": "MUST BUY", "BUY PRICE": 100,
        "SL": 95, "T1": 120, "T2": 130, "T3": 140,
        "52W LOW DISTANCE": 12.5, "+20%": 120, "+30%": 130, "+40%": 140
    }])
    rows, marks = pb.build_swing_rows(report)
    assert rows[0] == ["STOCK", "SIGNAL", "BUY PRICE", "SL", "T1", "T2", "T3",
                       "52W LOW DISTANCE", "+20%", "+30%", "+40%"]
    assert len(rows) == 2
    assert rows[1][0:2] == ["AAA", "MUST BUY"]
    assert marks["header"] == [0]


def test_swing_publisher_writes_only_swing_tab(monkeypatch):
    book = MagicMock()
    ws = MagicMock()
    ws.row_count, ws.col_count, ws.id = 500, 20, 123
    book.worksheet.return_value = ws
    monkeypatch.setattr(pb, "open_book", lambda: book)
    report = pd.DataFrame(columns=[
        "STOCK", "SIGNAL", "BUY PRICE", "SL", "T1", "T2", "T3",
        "52W LOW DISTANCE", "+20%", "+30%", "+40%"
    ])
    assert pb.publish_swing(report)
    book.worksheet.assert_called_once_with("SWING")
    book.add_worksheet.assert_not_called()
    book.del_worksheet.assert_not_called()

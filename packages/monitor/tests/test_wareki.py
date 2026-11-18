import datetime as dt

import pytest

from okura_monitor.wareki import kanji_number, parse_wareki


@pytest.mark.parametrize("text, value", [
    ("九十九", 99), ("十二", 12), ("三十一", 31), ("十", 10), ("二百二十六", 226), ("元", 1),
    ("１１", 11), ("８", 8), ("二〇二六", 2026),
])
def test_kanji_number(text, value):
    assert kanji_number(text) == value


def test_csv_date_is_read():
    d = parse_wareki("令和八年十一月一日")
    assert d.date == dt.date(2026, 11, 1) and not d.provisional


def test_reiwa_99_is_provisional_not_a_real_date():
    # 日次 CSV の施行日未定の改正（実測 §5：R070401.csv の消費税法・地方税法など）
    for raw in ("令和九十九年十二月三十一日", "令和九十九年十二月三十日"):
        d = parse_wareki(raw)
        assert d.provisional and d.date is None and d.iso() is None


def test_fullwidth_posted_date_and_gannen():
    assert parse_wareki("令和８年１１月６日掲載").date == dt.date(2026, 11, 6)
    assert parse_wareki("平成元年一月八日").date == dt.date(1989, 1, 8)
    assert parse_wareki("施行日なし") is None

"""和暦の日付（漢数字・全角数字）の解析。

一括ダウンロードの日次 CSV の日付は「令和八年十一月一日」の形（docs/measurements/20261109_R1-laws_egov-api-monitoring.md §5）。
施行日が決まっていない改正には「令和九十九年十二月三十一日」「令和九十九年十二月三十日」のような仮の日付が入っている
（同 §5。行の本文URLは 21171231_… で、未施行の欄が ○、施行日備考に「…の施行の日」などの実際の定めがある）。
仕様で確かめた扱いではない（推測）ので、元号の年が 99 の日付は「仮の日付」として、実在の施行日として扱わない。
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

ERA_START = {"明治": 1868, "大正": 1912, "昭和": 1926, "平成": 1989, "令和": 2019}
PROVISIONAL_ERA_YEAR = 99

_KANJI_DIGITS = {"〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_KANJI_UNITS = {"十": 10, "百": 100, "千": 1000}
_ZEN = str.maketrans("０１２３４５６７８９", "0123456789")

_DATE_RE = re.compile(
    r"(明治|大正|昭和|平成|令和)\s*([元〇零一二三四五六七八九十百千0-9０-９]+)\s*年\s*"
    r"([〇零一二三四五六七八九十0-9０-９]+)\s*月\s*([〇零一二三四五六七八九十0-9０-９]+)\s*日"
)


def kanji_number(text: str) -> int:
    """漢数字・全角数字・半角数字を整数にする。「元」は 1。位取りの漢数字（二〇二六）と十百千の両方を読む。"""
    s = text.strip().translate(_ZEN)
    if not s:
        raise ValueError("empty number")
    if s == "元":
        return 1
    if s.isdigit():
        return int(s)
    if any(ch in _KANJI_UNITS for ch in s):
        total, current = 0, 0
        for ch in s:
            if ch in _KANJI_DIGITS:
                current = current * 10 + _KANJI_DIGITS[ch] if current else _KANJI_DIGITS[ch]
            elif ch in _KANJI_UNITS:
                total += (current or 1) * _KANJI_UNITS[ch]
                current = 0
            else:
                raise ValueError(f"not a number: {text!r}")
        return total + current
    value = 0
    for ch in s:
        if ch not in _KANJI_DIGITS:
            raise ValueError(f"not a number: {text!r}")
        value = value * 10 + _KANJI_DIGITS[ch]
    return value


@dataclass(frozen=True)
class WarekiDate:
    raw: str
    era: str
    era_year: int
    month: int
    day: int
    provisional: bool  # 元号の年が 99（施行日未定の仮の日付）
    date: dt.date | None  # 仮の日付・実在しない日付なら None

    def iso(self) -> str | None:
        return self.date.isoformat() if self.date else None


def parse_wareki(text: str) -> WarekiDate | None:
    """文字列の中の最初の和暦の日付を読む。見つからなければ None。"""
    if not text:
        return None
    m = _DATE_RE.search(text)
    if not m:
        return None
    era = m.group(1)
    era_year = kanji_number(m.group(2))
    month = kanji_number(m.group(3))
    day = kanji_number(m.group(4))
    provisional = era_year == PROVISIONAL_ERA_YEAR
    date = None
    if not provisional:
        try:
            date = dt.date(ERA_START[era] + era_year - 1, month, day)
        except ValueError:
            date = None
    return WarekiDate(m.group(0), era, era_year, month, day, provisional, date)


def to_wareki_year(year: int) -> str:
    """西暦の年を「令和X年（YYYY）」の形にする（表示用）。"""
    for era, start in sorted(ERA_START.items(), key=lambda kv: -kv[1]):
        if year >= start:
            n = year - start + 1
            return f"{era}{'元' if n == 1 else n}年（{year}）"
    return str(year)

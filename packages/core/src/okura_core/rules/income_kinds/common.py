"""規則モジュール income_kinds の入力の組み立てで共有する小さな道具（法令の値を持たない）。"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable, Mapping
from typing import Any

from ...registry import RECORD_SECTIONS, YearContext
from ...result import OutOfScopeCategory, OutOfScopeReason, State

NI = OutOfScopeCategory.NOT_IMPLEMENTED


class Indexed:
    """YearContext に、記録の種類ごとの索引を足したもの（1回の組み立ての間だけ使う）。

    YearContext.records は呼ぶたびに全部の記録をなめるので、人ごとに呼ぶと人数 × 記録の数になる（人 2,000 人の評価で数十秒かかった）。
    """

    def __init__(self, ctx: YearContext) -> None:
        self._ctx = ctx
        self._by_kind: dict[str, list[Mapping[str, Any]]] = {}
        for section in RECORD_SECTIONS:
            for rec in ctx.ir[section]:
                self._by_kind.setdefault(rec["kind"], []).append(rec)

    def records(self, kind: str) -> list[Mapping[str, Any]]:
        return self._by_kind.get(kind, [])

    def __getattr__(self, name: str) -> Any:
        return getattr(self._ctx, name)


def reason(text: str, ids: Iterable[str] = ()) -> OutOfScopeReason:
    return OutOfScopeReason(NI, text, tuple(sorted(set(ids))))


def date_of(s: str) -> _dt.date:
    return _dt.date.fromisoformat(s)


def states_of(recs: Iterable[Mapping[str, Any]]) -> set[State]:
    return {State.from_mark(r["mark"]) for r in recs if "mark" in r}


def year_of(rec: Mapping[str, Any], attr: str | None = None) -> int:
    on = rec.get("attributes", {}).get(attr) if attr else None
    return date_of(on or rec["when"]["on"]).year


def check_amount(total: int, what: str) -> None:
    if type(total) is not int or total < 0:
        raise TypeError(f"{what} が0以上の整数でない")


def add_months(d: _dt.date, months: int) -> _dt.date:
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    last = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return _dt.date(y, m, min(d.day, last))


def calendar_months(start: _dt.date, end: _dt.date) -> int:
    """start から end まで（両端を含む）の月数：暦に従って数え、1月に満たない端数は1月（所令132②・所令59③）。"""
    if end < start:
        return 0
    stop = end + _dt.timedelta(days=1)
    n = (stop.year - start.year) * 12 + stop.month - start.month
    while add_months(start, n) > stop:
        n -= 1
    return n if add_months(start, n) == stop else n + 1


def first_year_months(placed_on: _dt.date, year: int) -> int:
    """業務の用に供した年の月数（所令132①一イ・②：供用した日からその年12月31日まで。暦に従い1月未満は1月）。"""
    return calendar_months(placed_on, _dt.date(year, 12, 31))


def undetermined(sid: str, means: Any, target: Mapping[str, Any], candidates: Iterable[str] = ()) -> Any:
    """決まらない1か所（入力の値が候補で分かれた：D21 R6・D22 S1）。入力の値に付けると、依存する値が未確定になり、
    target に何を入力すれば決まるか（「入力」）を書く。candidates は評価した候補の名前。"""
    from ...result import Split

    return Split(id=sid, means=means, target=dict(target), candidates=tuple(candidates), splits_conclusion=True)


# ---------------------------------------------------------------------------
# 期間（所基通30−13：暦に従って計算し、1月に満たない期間は日をもって数え、日数は30日をもって1月、月数は12月をもって1年）
# ---------------------------------------------------------------------------

Interval = tuple[_dt.date, _dt.date]  # 両端を含む


def ymd(start: _dt.date, end: _dt.date) -> tuple[int, int, int]:
    """start〜end（両端を含む）の期間を暦に従って (年, 月, 日) で数える。"""
    if end < start:
        return (0, 0, 0)
    stop = end + _dt.timedelta(days=1)
    n = (stop.year - start.year) * 12 + stop.month - start.month
    while n > 0 and add_months(start, n) > stop:
        n -= 1
    days = (stop - add_months(start, n)).days
    return (n // 12, n % 12, days)


def sum_ymd(parts: Iterable[tuple[int, int, int]]) -> tuple[int, int, int]:
    """年数・月数・日数をそれぞれ合計し、日数は30日を1月、月数は12月を1年にする（所基通30−13）。"""
    y = m = d = 0
    for a, b, c in parts:
        y, m, d = y + a, m + b, d + c
    m += d // 30
    d %= 30
    y += m // 12
    m %= 12
    return (y, m, d)


def measure(intervals: Iterable[Interval]) -> tuple[int, int, int]:
    return sum_ymd(ymd(a, b) for a, b in intervals)


def years_ceil(v: tuple[int, int, int]) -> int:
    """1年未満の端数は1年（所令69②、71の2⑩・69の2④で準用）。"""
    return v[0] + (1 if v[1] or v[2] else 0)


def years_floor(v: tuple[int, int, int]) -> int:
    """1年未満の端数は切り捨てる（所令70③）。"""
    return v[0]


def normalize(intervals: Iterable[Interval]) -> list[Interval]:
    """重なり・隣接する期間をまとめる。"""
    out: list[Interval] = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1] + _dt.timedelta(days=1):
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def intersect(xs: Iterable[Interval], ys: Iterable[Interval]) -> list[Interval]:
    out = []
    ys = normalize(ys)
    for a, b in normalize(xs):
        for c, d in ys:
            lo, hi = max(a, c), min(b, d)
            if lo <= hi:
                out.append((lo, hi))
    return normalize(out)


def subtract(xs: Iterable[Interval], ys: Iterable[Interval]) -> list[Interval]:
    out = normalize(xs)
    one = _dt.timedelta(days=1)
    for c, d in normalize(ys):
        nxt = []
        for a, b in out:
            if d < a or c > b:
                nxt.append((a, b))
                continue
            if a < c:
                nxt.append((a, c - one))
            if d < b:
                nxt.append((d + one, b))
        out = nxt
    return out

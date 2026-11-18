"""繰り返しの行の割当て（design-output UO23。2026-11-12）：誰を様式のどの行に載せるかを、判定コアの結果の値から決める純粋関数。

様式の繰り返しの行（第二表の「配偶者や親族に関する事項」など）は、行ごとに人（区画の行の人）がいる。対応表の欄に `人: <区画>` を書くと、
行 i の欄はこの関数が i 番目に割り当てた人の値を写す（table.py の docstring）。割当ては計算ではなく、結果の値の選び方と並べ方。

規則（根拠は REFERENCES の docs の節）：
  配偶者や親族（第二表。5行）
    - 1行目＝配偶者：申告者の法律婚の相手（所得税.法律婚の相手）で、申告者の同一生計配偶者に当たるか、配偶者特別控除の額が正のとき
      （手引き 3-3_27「最上段に配偶者」、※3 年末調整を受けていても同一生計配偶者を省略しない）。
    - 2行目以後＝扶養親族（16歳未満を含む）又は特定親族：その人の 所得税.扶養親族等とする申告者 が申告者で、扶養親族に当たるか特定親族に当たるか
      （手引き 3-3_27「2行目以降に扶養親族又は特定親族」、※3「16歳未満の扶養親族…を記入」）。
    - 2行目以後の順は様式・手引きに定めがないので、既定の並べ方（ORDER_RULE：生年月日の早い順、同じなら人の ID 順）。表示だけの既定で税額は変わらない
      （design-output §6.4 D18 と同じ扱い。印は付けない）。
    - 行の数を超える人は切り捨てず、overflow に全部を出す（yoshiki-mapping-table H2「あふれ」。適宜の用紙に書く）。
  退職所得のある配偶者・親族（第二表 住民税に関する事項。1行）
    - 上の「配偶者や親族」に載せる人（あふれを含む）のうち、退職所得の金額が正の人を同じ順で。
  事業専従者（第二表。2行）
    - その人の 所得税.事業専従者の事業主 が申告者の人を、人の ID 順（様式に順の定めがない。既定）。

値がない（問いで求めていない）・未確定・対象外の値に割当てが左右されるときは、割当て全体を「値なし」「未確定」にする（行の欄も同じ状態になる）。
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ..money import YenRange
from ..result import Category, Count, DateValue, Flag, ResultValue, State, YenAmount

ASSIGNED = "決定"
UNDETERMINED = "未確定"
MISSING = "値なし"

ORDER_RULE = "既定の並べ方：生年月日の早い順、同じなら人の ID 順（様式・手引きに定めがない。表示だけで税額は変わらない）"

REFERENCES: tuple[str, ...] = (
    "docs/public-sources/20261109_impl-prep_output-forms-and-specs.md#2.5",
    "docs/public-sources/20261109_round2_yoshiki-forms-r07.md#3",
    "docs/hypotheses/20261109_round2_yoshiki-mapping-table.md#H2",
)

# 割当てが読む概念
C_SPOUSE_OF = "所得税.法律婚の相手"
C_SAME_LIVELIHOOD = "所得税.同一生計配偶者に当たるか"
C_SPOUSE_SPECIAL = "所得税.配偶者特別控除の額"
C_CLAIMANT = "所得税.扶養親族等とする申告者"
C_DEPENDENT = "所得税.扶養親族に当たるか"
C_SPECIFIED = "所得税.特定親族に当たるか"
C_BIRTH = "所得税.生年月日"
C_RETIREMENT = "所得税.退職所得の金額"
C_EMPLOYER = "所得税.事業専従者の事業主"

#: 人の ID の区分の値で「いない」を表す値（規則モジュールの NO_PERSON。空の区分は結果に出せないので「なし」）。
NO_PERSON_VALUES = frozenset({"", "なし"})


@dataclass(frozen=True)
class RowAssignment:
    """区画の行の割当て。persons は行の数の長さ（人がいない行は None）。status が決定でなければ persons は全部 None。"""

    section: str
    capacity: int
    status: str
    persons: tuple[str | None, ...]
    overflow: tuple[str, ...] = ()
    value_ids: tuple[str, ...] = ()
    states: frozenset[State] = frozenset()
    reason: str | None = None
    rule: str = ""

    def person_at(self, row: int) -> str | None:
        return self.persons[row - 1] if 1 <= row <= len(self.persons) else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "section": self.section,
            "capacity": self.capacity,
            "status": self.status,
            "persons": list(self.persons),
            "overflow": list(self.overflow),
            "value_ids": list(self.value_ids),
            "reason": self.reason,
            "rule": self.rule,
            "references": list(REFERENCES),
        }


class _Undecided(Exception):
    def __init__(self, status: str, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


@dataclass
class _Reader:
    """人 × 概念 の値を読み、使った値の ID と状態を集める。"""

    values: Mapping[str, Mapping[str, ResultValue]]
    ids: list[str] = field(default_factory=list)
    states: set[State] = field(default_factory=set)

    def raw(self, person: str, concept: str) -> ResultValue | None:
        return self.values.get(person, {}).get(concept)

    def get(self, person: str, concept: str) -> Any:
        """値（Python の値）。値がない・未確定・対象外なら _Undecided。"""
        rv = self.raw(person, concept)
        if rv is None:
            raise _Undecided(MISSING, f"結果に {concept}（{person}）の値がない")
        if rv.id not in self.ids:
            self.ids.append(rv.id)
        self.states |= set(rv.states)
        if State.OUT_OF_SCOPE in rv.states:
            raise _Undecided(UNDETERMINED, f"{concept}（{person}）が対象外")
        v = rv.value
        if v is None or isinstance(v, YenRange) or State.UNDETERMINED in rv.states:
            raise _Undecided(UNDETERMINED, f"{concept}（{person}）が未確定")
        if isinstance(v, (YenAmount, Flag, Count, Category)):
            return v.amount if isinstance(v, YenAmount) else v.value
        if isinstance(v, DateValue):
            return v.on
        raise TypeError(f"割当てに使えない値: {type(v).__name__}")


def _by_person(values: Iterable[ResultValue]) -> dict[str, dict[str, ResultValue]]:
    out: dict[str, dict[str, ResultValue]] = {}
    for v in values:
        if v.person is not None:
            out.setdefault(v.person, {}).setdefault(v.concept, v)
    return out


def _order_key(r: _Reader, person: str) -> tuple[_dt.date, str]:
    """ORDER_RULE。生年月日の値がなければ未確定にせず、ID の順で後ろに置く（並べ方は税額に効かない）。"""
    rv = r.raw(person, C_BIRTH)
    born = rv.value.on if rv is not None and isinstance(rv.value, DateValue) else _dt.date.max
    return (born, person)


def _relatives(r: _Reader, filer: str) -> tuple[str | None, list[str]]:
    """（1行目の配偶者、2行目以後の人の並び）。"""
    spouse = r.get(filer, C_SPOUSE_OF)
    first: str | None = None
    if spouse not in NO_PERSON_VALUES:
        same = r.get(filer, C_SAME_LIVELIHOOD)
        special = r.get(filer, C_SPOUSE_SPECIAL)
        if same is True or (isinstance(special, int) and special > 0):
            first = str(spouse)
    others: list[str] = []
    claimants = {p: c for p, vs in r.values.items() if p != filer and (c := vs.get(C_CLAIMANT)) is not None}
    if not claimants and r.raw(filer, C_CLAIMANT) is None:
        raise _Undecided(MISSING, f"結果に {C_CLAIMANT} の値がない（扶養親族等を決められない）")
    for p in sorted(claimants):
        if r.get(p, C_CLAIMANT) != filer:
            continue
        if r.get(p, C_DEPENDENT) is True or r.get(p, C_SPECIFIED) is True:
            others.append(p)
    others.sort(key=lambda p: _order_key(r, p))
    return first, others


def _assign_relatives(r: _Reader, filer: str, capacity: int) -> tuple[list[str | None], list[str]]:
    first, others = _relatives(r, filer)
    rows: list[str | None] = [first, *others[: capacity - 1]]
    return rows, others[capacity - 1 :]


def _assign_retirement(r: _Reader, filer: str, capacity: int) -> tuple[list[str | None], list[str]]:
    first, others = _relatives(r, filer)
    listed = [p for p in [first, *others] if p is not None]
    hits = [p for p in listed if (amount := r.get(p, C_RETIREMENT)) is not None and amount > 0]
    return list(hits[:capacity]), hits[capacity:]


def _assign_employees(r: _Reader, filer: str, capacity: int) -> tuple[list[str | None], list[str]]:
    candidates = {p: vs.get(C_EMPLOYER) for p, vs in r.values.items() if p != filer}
    if all(v is None for v in candidates.values()):
        raise _Undecided(MISSING, f"結果に {C_EMPLOYER} の値がない（事業専従者を決められない）")
    hits = [p for p in sorted(candidates) if candidates[p] is not None and r.get(p, C_EMPLOYER) == filer]
    return list(hits[:capacity]), hits[capacity:]


#: 区画の名前 → （割当ての関数、規則の説明）。
SECTIONS: Mapping[str, tuple[Callable[[_Reader, str, int], tuple[list[str | None], list[str]]], str]] = {
    "配偶者や親族": (
        _assign_relatives,
        "1行目は配偶者（同一生計配偶者か配偶者特別控除の対象）、2行目以後は扶養親族（16歳未満を含む）・特定親族（手引き 3-3_27）。" + ORDER_RULE,
    ),
    "退職所得のある配偶者・親族": (_assign_retirement, "配偶者や親族の行に載せる人のうち退職所得の金額が正の人。" + ORDER_RULE),
    "事業専従者": (_assign_employees, "申告者の事業専従者（所得税.事業専従者の事業主）。既定の並べ方：人の ID 順（様式に定めがない）"),
}


def assign_rows(section: str, capacity: int, values: Iterable[ResultValue], filer: str) -> RowAssignment:
    """区画の行の割当て（純粋関数）。values はその年分の全員の結果の値（時点で絞ったもの）。"""
    if section not in SECTIONS:
        raise KeyError(section)
    fn, rule = SECTIONS[section]
    r = _Reader(_by_person(values))
    try:
        rows, overflow = fn(r, filer, capacity)
    except _Undecided as e:
        return RowAssignment(section, capacity, e.status, (None,) * capacity, (), tuple(r.ids), frozenset(r.states), e.reason, rule)
    rows = rows + [None] * (capacity - len(rows))
    return RowAssignment(section, capacity, ASSIGNED, tuple(rows), tuple(overflow), tuple(r.ids), frozenset(r.states), None, rule)

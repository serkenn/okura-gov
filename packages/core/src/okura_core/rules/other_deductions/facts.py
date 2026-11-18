"""規則モジュール other_deductions の、中間表現を読む共通の道具（判断・選択の1か所の宣言、生計を一にするかの時点ごとの判断、
入力の積み上げと対象外の理由）。法令の値は持たない。
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ...registry import Decided, DecisionSlot, ModuleInputs, StageValue, YearContext
from ...result import Means, OutOfScopeCategory, OutOfScopeReason, Split, State
from .kinship import Kinship, RelationIndex, kinship

# 判断・選択の種類（中間表現の語彙：packages/ir/README.md §3.3）
J_SEIKEI = "判断.生計を一にする"
J_RANGE = "判断.医療費の範囲"
J_REIMB = "判断.補塡の対象"
J_SELFMED = "判断.セルフメディケーション表示の上書き"
J_LIFE = "判断.生命保険の区分"
J_DONATION = "判断.寄附の性質"
J_CASUALTY = "判断.雑損の計算"
P_ESTIMATE = "見積り.補塡の見込額"
C_SELFMED = "選択.医療費控除かセルフメディケーション税制か"
C_INSURANCE = "選択.保険料控除の区分"
C_DONATION = "選択.寄附金の控除の方式"
C_PREPAID = "選択.前納した社会保険料の控除の年分"


def d(s: str) -> _dt.date:
    return _dt.date.fromisoformat(s)


def states_of(rec: Mapping[str, Any]) -> frozenset[State]:
    return frozenset({State.from_mark(rec["mark"])}) if "mark" in rec else frozenset()


def on_year(rec: Mapping[str, Any]) -> int:
    return d(rec["when"]["on"]).year


def year_end(ctx: YearContext) -> _dt.date:
    return _dt.date(ctx.year, 12, 31)


def covers(when: Mapping[str, Any] | None, on: _dt.date) -> bool:
    """区間の when（from_on・to_on）がその日を含むか。when がなければ含むものとする（時を持たない判断）。"""
    if not when:
        return True
    if "on" in when:
        return d(when["on"]) == on
    if "from_on" in when:
        start = d(when["from_on"])
        end = d(when["to_on"]) if when.get("to_on") else None
        return start <= on and (end is None or on <= end)
    if "tax_year" in when:
        return when["tax_year"] == on.year
    return True


def not_implemented(reason: str, ids: Iterable[str] = ()) -> OutOfScopeReason:
    return OutOfScopeReason(OutOfScopeCategory.NOT_IMPLEMENTED, reason, tuple(sorted(set(ids))))


def reading_split(
    topic: str, key: str, target: Mapping[str, Any], candidates: tuple[str, ...], *, means: Means = Means.PRIMARY_SOURCE
) -> Split:
    """一次情報で決まらない読み（means=一次情報）か、語彙にない事実（means=事実）の分かれ目（D22 S1・D21 R6）。

    モジュールは候補の全部の値を計算し、値が分かれるときだけ入力の missing に渡す（Acc.undetermined）。依存する値は未確定になり、
    分かれ目の対象（論点・記録）が「何を決めれば（入力すれば）決まるか」になる（outcomes は空。insurance.timing_split と同じ形）。
    """
    prefix = "読み" if means is Means.PRIMARY_SOURCE else "事実"
    return Split(
        id=f"{prefix}:{topic}:{key}",
        means=means,
        target={**dict(target), "論点": topic},
        candidates=candidates,
        splits_conclusion=True,
    )


# ---------------------------------------------------------------------------
# 判断.生計を一にする（時点ごと。所得税基本通達73−1 などの「その時の現況」）
# ---------------------------------------------------------------------------


def _pair(rec: Mapping[str, Any], a: str, b: str) -> bool:
    s = rec["subject"]
    return {s["person"], s["other_person"]} == {a, b}


def seikei_key(a: str, b: str, on: _dt.date) -> str:
    """1か所の key：支払者:相手@日付。personal_deductions の年分の1か所（"<person>:<other_person>"）とは別の問い（その日の現況）。"""
    return f"{a}:{b}@{on.isoformat()}"


def seikei_slot(a: str, b: str, on: _dt.date, purpose: str, persons: tuple[str, ...] | None = None) -> DecisionSlot:
    """persons：関係する人（省略は target から導く。その年分に生存していない相手のときは支払者だけを渡す）。"""
    return DecisionSlot(
        key=seikei_key(a, b, on),
        target={"person": a, "other_person": b, "on": on.isoformat(), "purpose": purpose},
        matches=lambda r, a=a, b=b, on=on: _pair(r, a, b) and covers(r.get("when"), on),
        year_filter=False,  # その日を含む判断を見る（支払の年分と重ならない前年の受診日の判断も使う）
        persons=persons,
    )


def known_seikei(ctx: YearContext, a: str, b: str, on: _dt.date) -> bool | None:
    """中間表現の判断だけで決まる値（resolve_decisions と同じ絞り方：置き換えの連鎖の先頭・その日を含む）。"""
    vals = {
        bool(r["value"])
        for r in ctx.judgments(J_SEIKEI)
        if _pair(r, a, b) and covers(r.get("when"), on)
    }
    return vals.pop() if len(vals) == 1 else None


# ---------------------------------------------------------------------------
# 親族と生計の判定の材料（支払者 a と相手 b の、日付ごとの親族の判定）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Relative:
    """日付ごとの親族の判定（kinship.Kinship）。"""

    by_date: Mapping[_dt.date, Kinship]

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(sorted({i for k in self.by_date.values() for i in k.record_ids}))

    @property
    def states(self) -> frozenset[State]:
        return frozenset(s for k in self.by_date.values() for s in k.states)

    def dates_where(self, value: bool | None) -> list[_dt.date]:
        return [on for on, k in self.by_date.items() if k.relative is value]

    @property
    def notes(self) -> str:
        return "・".join(dict.fromkeys(k.note for k in self.by_date.values() if k.note))


def relative_on(idx: RelationIndex, a: str, b: str, dates: Iterable[_dt.date]) -> Relative:
    return Relative({on: kinship(idx, a, b, on) for on in dict.fromkeys(dates)})


# ---------------------------------------------------------------------------
# 入力の積み上げ
# ---------------------------------------------------------------------------


@dataclass
class Acc:
    """入力変数 × 人 の値・由来・対象外を積み上げ、最後に ModuleInputs に書く。"""

    persons: tuple[str, ...]
    amounts: dict[tuple[str, str], int] = field(default_factory=dict)
    values: dict[tuple[str, str], Any] = field(default_factory=dict)
    ids: dict[tuple[str, str], set[str]] = field(default_factory=dict)
    states: dict[tuple[str, str], set[State]] = field(default_factory=dict)
    excluded: dict[tuple[str, str], list[OutOfScopeReason]] = field(default_factory=dict)
    #: 段階評価の段（StageSpec(run=None)）の値を読んで書く入力の由来（読んだ値）。ここに書いた変数は、読まなかった人も空の由来にする。
    uses: dict[tuple[str, str], list[StageValue]] = field(default_factory=dict)
    stage_vars: set[str] = field(default_factory=set)
    #: 一次情報で決まらない読みの分かれ目（D22 S1：読みで値が分かれる入力。依存する値を未確定にする）。
    missing: dict[tuple[str, str], list[Split]] = field(default_factory=dict)

    def add(self, var: str, pid: str, amount: int, ids: Iterable[str] = (), states: Iterable[State] = ()) -> None:
        if type(amount) is not int:
            raise TypeError("金額は整数の円")
        k = (var, pid)
        self.amounts[k] = self.amounts.get(k, 0) + amount
        self.note(var, pid, ids, states)

    def set_value(self, var: str, pid: str, value: Any, ids: Iterable[str] = (), states: Iterable[State] = ()) -> None:
        self.values[(var, pid)] = value
        self.note(var, pid, ids, states)

    def note(self, var: str, pid: str, ids: Iterable[str] = (), states: Iterable[State] = ()) -> None:
        self.ids.setdefault((var, pid), set()).update(ids)
        self.states.setdefault((var, pid), set()).update(states)

    def note_decided(self, var: str, pid: str, dec: Decided) -> None:
        self.note(var, pid, dec.record_ids, dec.states)

    def use(self, var: str, pid: str, values: Iterable[StageValue]) -> None:
        self.stage_vars.add(var)
        self.uses.setdefault((var, pid), []).extend(values)

    def undetermined(self, var: str, pid: str, split: Split) -> None:
        self.missing.setdefault((var, pid), []).append(split)

    def exclude(self, var: str, pid: str, reason: OutOfScopeReason) -> None:
        if pid not in self.persons:
            return
        self.excluded.setdefault((var, pid), []).append(reason)
        self.note(var, pid, reason.record_ids)

    def write(self, out: ModuleInputs, int_vars: Iterable[str], other_defaults: Mapping[str, Any]) -> None:
        for var in int_vars:
            for pid in self.persons:
                k = (var, pid)
                total = self.amounts.get(k, 0)
                bad = k in self.excluded
                if not bad and (total < 0 or total > 2**31 - 1):
                    self.exclude(
                        var, pid, not_implemented(f"{var} の合計が判定コアの整数の範囲（0〜{2**31 - 1:,}円）の外", sorted(self.ids.get(k, ())))
                    )
                    bad = True
                out.set(
                    var, pid, 0 if bad else total, sorted(self.ids.get(k, ())), self.states.get(k, ()),
                    uses=tuple(self.uses.get(k, ())) if var in self.stage_vars else None,
                    missing=self.missing.get(k, ()),
                )  # fmt: skip
        for var, default in other_defaults.items():
            for pid in self.persons:
                k = (var, pid)
                out.set(var, pid, self.values.get(k, default), sorted(self.ids.get(k, ())), self.states.get(k, ()))
        for (var, pid), reasons in sorted(self.excluded.items()):
            for r in reasons:
                out.exclude(pid, r, var)


def heads_for(ctx: YearContext, kind: str, key: str, value: str) -> list[Mapping[str, Any]]:
    """判断・選択（置き換えの連鎖の先頭）のうち、subject[key] == value のもの。"""
    section = ctx.choices if kind.startswith("選択.") else ctx.judgments
    return [r for r in section(kind) if r["subject"].get(key) == value]

__all__ = [
    "Acc",
    "C_INSURANCE",
    "C_SELFMED",
    "C_DONATION",
    "J_CASUALTY",
    "J_DONATION",
    "J_LIFE",
    "J_RANGE",
    "J_REIMB",
    "J_SEIKEI",
    "J_SELFMED",
    "P_ESTIMATE",
    "Relative",
    "covers",
    "d",
    "heads_for",
    "known_seikei",
    "not_implemented",
    "on_year",
    "reading_split",
    "relative_on",
    "seikei_key",
    "seikei_slot",
    "states_of",
    "year_end",
]

"""人をまたぐ関係の窓口（D23 K1・SCOPE §6-3）：中間表現の関係（区間つき）を、人から引く。

段階の間の関数（registry.StageSpec）と build_inputs から `ctx.relations` で使う。法令の解釈（親族の範囲、誰を「有する」か、
扶養親族に当たるか）は持たず、記録と判断台帳の事実だけを返す。1人が複数の人の「扶養親族」に当たりうること（所得金額調整控除の第1項の
「有する」）は、グループを使わずにこの窓口と前の段の値（StageContext.value）で表す。

中間表現の関係（packages/ir/README.md §3.3）：parentage（親子の成立の日）・adoption（期間＝縁組から離縁まで）・
marriage（期間）・foster_placement（期間）・cohabitation（期間）・separation_reason（期間）・heirship（相続の開始の日）。
`when` が `{"on": 日付}` の記録（親子関係の成立など）は、その日に始まって続く関係として扱う。
"""

from __future__ import annotations

import datetime as _dt
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .result import State


#: 親族の候補をたどる関係（親子・養子縁組・婚姻・里親委託）。親族かどうかの判定はしない（所得税法の親族の範囲はモジュールの責務）。
KIN_KINDS: tuple[str, ...] = ("parentage", "adoption", "marriage", "foster_placement")

#: kin が既定でたどる段数の上限（親族の範囲の法令の値ではなく、組合せの爆発を抑える値）。
KIN_MAX_HOPS = 6


def _date(s: str | None) -> _dt.date | None:
    return _dt.date.fromisoformat(s) if s else None


def _period_of(when: Mapping[str, Any] | None) -> tuple[_dt.date | None, _dt.date | None]:
    if not when:
        return None, None
    if "on" in when:
        return _date(when["on"]), None
    if "from_on" in when:
        return _date(when["from_on"]), _date(when.get("to_on"))
    return None, None


@dataclass(frozen=True)
class Relation:
    """ある人（me）から見た関係1件。record は元の記録（読むだけ）。"""

    kind: str
    me: str
    other: str
    my_role: str
    other_role: str
    record_id: str
    from_on: _dt.date | None
    to_on: _dt.date | None
    states: frozenset[State]
    record: Mapping[str, Any]

    def active_on(self, on: _dt.date) -> bool:
        return (self.from_on is None or self.from_on <= on) and (self.to_on is None or on <= self.to_on)

    def overlaps(self, start: _dt.date, end: _dt.date) -> bool:
        return (self.from_on is None or self.from_on <= end) and (self.to_on is None or self.to_on >= start)


@dataclass(frozen=True)
class KinPath:
    """親族の候補へのたどり方（最短）。relations は me から順に。"""

    person: str
    relations: tuple[Relation, ...]

    @property
    def hops(self) -> int:
        return len(self.relations)


class RelationView:
    """中間表現の関係の索引。同じ ir について呼び出しごとに使い回してよい（書き換えない）。"""

    def __init__(self, ir: Mapping[str, Any]) -> None:
        self._ir = ir
        self._by_person: dict[str, list[Relation]] = {}
        for rec in ir["relations"]:
            roles = list(rec["roles"].items())
            if len(roles) != 2:
                continue
            (ra, a), (rb, b) = roles
            start, end = _period_of(rec.get("when"))
            states = frozenset({State.from_mark(rec["mark"])}) if "mark" in rec else frozenset()
            self._by_person.setdefault(a, []).append(Relation(rec["kind"], a, b, ra, rb, rec["id"], start, end, states, rec))
            self._by_person.setdefault(b, []).append(Relation(rec["kind"], b, a, rb, ra, rec["id"], start, end, states, rec))
        for rels in self._by_person.values():
            rels.sort(key=lambda r: (r.kind, r.record_id, r.other))

    def of(
        self,
        person: str,
        kinds: Iterable[str] | None = None,
        *,
        on: _dt.date | None = None,
        overlaps: tuple[_dt.date, _dt.date] | None = None,
    ) -> tuple[Relation, ...]:
        """person の関係。kinds で種類を絞る。on はその日に続いているもの、overlaps は (開始, 終了) と重なるもの。"""
        want = None if kinds is None else frozenset(kinds)
        out: list[Relation] = []
        for r in self._by_person.get(person, ()):
            if want is not None and r.kind not in want:
                continue
            if on is not None and not r.active_on(on):
                continue
            if overlaps is not None and not r.overlaps(*overlaps):
                continue
            out.append(r)
        return tuple(out)

    def between(
        self,
        a: str,
        b: str,
        kinds: Iterable[str] | None = None,
        *,
        on: _dt.date | None = None,
        overlaps: tuple[_dt.date, _dt.date] | None = None,
    ) -> tuple[Relation, ...]:
        """a と b の間の関係（a から見た向き）。"""
        return tuple(r for r in self.of(a, kinds, on=on, overlaps=overlaps) if r.other == b)

    def spouses(self, person: str, on: _dt.date) -> tuple[Relation, ...]:
        """その日に続いている婚姻の相手。"""
        return self.of(person, ("marriage",), on=on)

    def parents(self, person: str, on: _dt.date) -> tuple[Relation, ...]:
        """その日の親（親子関係の成立・続いている養子縁組の親の側）。"""
        return tuple(r for r in self.of(person, ("parentage", "adoption"), on=on) if r.my_role in ("child", "adoptee"))

    def children(self, person: str, on: _dt.date) -> tuple[Relation, ...]:
        """その日の子（親子関係の成立・続いている養子縁組の子の側）。"""
        return tuple(r for r in self.of(person, ("parentage", "adoption"), on=on) if r.my_role in ("parent", "adoptive_parent"))

    def kin(self, person: str, on: _dt.date, *, max_hops: int = KIN_MAX_HOPS) -> tuple[KinPath, ...]:
        """その日の親子・養子縁組・婚姻・里親委託の関係をたどって届く人（最短のたどり方。本人を除く）。

        たどり方を返すだけで、親族の範囲（親等・姻族の終了など）の判定はしない。呼び出す側のモジュールが法令に従って決める。
        """
        seen: dict[str, tuple[Relation, ...]] = {person: ()}
        queue: deque[str] = deque([person])
        while queue:
            x = queue.popleft()
            path = seen[x]
            if len(path) >= max_hops:
                continue
            for r in self.of(x, KIN_KINDS, on=on):
                if r.other not in seen:
                    seen[r.other] = path + (r,)
                    queue.append(r.other)
        return tuple(KinPath(p, rels) for p, rels in sorted(seen.items()) if p != person)

    def judgments(self, kind: str, person: str, other: str | None = None, *, on: _dt.date | None = None) -> tuple[Mapping[str, Any], ...]:
        """判断（置き換えの連鎖の先頭）のうち、subject の person が person で（other を渡せば other_person が other か、その逆）、
        on を渡せば when がその日を含むもの。未入力の判断の候補の評価は DecisionSpec と ctx.decision で行う（ここでは記録を読むだけ）。
        """
        records = [j for j in self._ir["judgments"] if j["kind"] == kind]
        replaced = {j["replaces"] for j in records if j.get("replaces")}
        out: list[Mapping[str, Any]] = []
        for j in records:
            if j["id"] in replaced:
                continue
            s = j.get("subject", {})
            pair = {s.get("person"), s.get("other_person")}
            if other is None:
                if s.get("person") != person:
                    continue
            elif pair != {person, other}:
                continue
            if on is not None and not _covers(j.get("when"), on):
                continue
            out.append(j)
        return tuple(sorted(out, key=lambda j: j["id"]))


def _covers(when: Mapping[str, Any] | None, on: _dt.date) -> bool:
    if not when:
        return True
    if "on" in when:
        return _date(when["on"]) == on
    if "from_on" in when:
        start = _date(when["from_on"])
        end = _date(when.get("to_on"))
        return (start is None or start <= on) and (end is None or on <= end)
    if "tax_year" in when:
        return when["tax_year"] == on.year
    return True


__all__ = ["KIN_KINDS", "KIN_MAX_HOPS", "KinPath", "Relation", "RelationView"]

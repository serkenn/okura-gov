"""規則モジュール other_deductions：支払者とほかの人が「配偶者その他の親族」か（ある日の現況）を、中間表現の関係の記録から導く。

所得税法は「親族」の定義を置かない。国税庁の説明（質疑応答事例・タックスアンサー）と最高裁判決は民法の親族と読む
（docs/public-sources/20261109_impl-prep_misc-age-kinship-attribution.md §2.2・§2.3）。この読みで判定し、根拠に「法令の読み」と
記録する（HANDOFF D22 S1）。民法の規定は docs/public-sources/20261109_R4-modeling_concepts.md §3.1：

- 第725条：6親等内の血族・配偶者・3親等内の姻族。第726条：親等は世代数で数え、傍系は同一の祖先にさかのぼって下る。
- 第727条：養子と養親及びその血族との間は、縁組の日から血族と同一の親族関係。第729条：離縁で終了。
- 第728条：姻族関係は離婚で終了。配偶者の死亡後は、生存配偶者が終了の意思を表示したときに終了。

中間表現の関係（packages/ir/README.md §3.3）：parentage（on＝成立の日）・adoption（期間＝縁組から離縁まで）・
marriage（期間、ended_by、affinity_termination_on）。続柄そのものは記録しない（出来事から導く）。

結論は3つ：True（親族）・False（記録の関係から親族と導けない）・None（決められない。次の場合）。
- 養子縁組の関係を、養子が当事者でない形でたどる（縁組の前に生まれた養子の子など。第727条の範囲を判定しない）。
- 婚姻が取消し・終わり方の記録なしで終わった後の姻族関係（第728条の当てはめを決めない）。
False は「親族でない」の断定ではない（記録の書き忘れと区別できない）。呼び出し側は False も対象外にする（黙って控除から外さない）。

純粋関数だけ。法令の値（6・3）は民法の条文の数で、年分で変わらない。
"""

from __future__ import annotations

import datetime as _dt
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ...result import State

#: 民法第725条第1号・第3号の親等（血族は6親等内、姻族は3親等内）。
BLOOD_DEGREE_MAX = 6
AFFINITY_DEGREE_MAX = 3


def _date(s: str) -> _dt.date:
    return _dt.date.fromisoformat(s)


def _state_of(rec: Mapping[str, Any]) -> frozenset[State]:
    return frozenset({State.from_mark(rec["mark"])}) if "mark" in rec else frozenset()


@dataclass(frozen=True)
class Kinship:
    """ある日の、人 a から見た人 b の関係。relative は True・False・None（モジュールの先頭の説明）。"""

    relative: bool | None
    kind: str  # 本人・配偶者・血族・姻族・""（親族でない・決められない）
    degree: int | None
    record_ids: tuple[str, ...] = ()
    states: frozenset[State] = frozenset()
    note: str = ""


@dataclass
class _Edge:
    parent: str
    child: str
    rid: str
    adoption: bool
    states: frozenset[State]
    when: Mapping[str, Any]


@dataclass
class RelationIndex:
    """中間表現の関係の記録の索引（年分の評価ごとに1回作る）。"""

    parent_edges: list[_Edge] = field(default_factory=list)
    marriages: list[Mapping[str, Any]] = field(default_factory=list)

    @classmethod
    def of(cls, ir: Mapping[str, Any]) -> RelationIndex:
        idx = cls()
        for r in ir["relations"]:
            if r["kind"] == "parentage":
                idx.parent_edges.append(
                    _Edge(r["roles"]["parent"], r["roles"]["child"], r["id"], False, _state_of(r), r["when"])
                )
            elif r["kind"] == "adoption":
                idx.parent_edges.append(
                    _Edge(r["roles"]["adoptive_parent"], r["roles"]["adoptee"], r["id"], True, _state_of(r), r["when"])
                )
            elif r["kind"] == "marriage":
                idx.marriages.append(r)
        return idx

    # --- 血族（民法第726条・第727条） ---

    def _edges_on(self, on: _dt.date, ends: frozenset[str], allow_any_adoption: bool) -> list[_Edge]:
        out = []
        for e in self.parent_edges:
            rec_when = e.when
            if e.adoption:
                start = _date(rec_when["from_on"])
                end = _date(rec_when["to_on"]) if rec_when.get("to_on") else None
                if not (start <= on and (end is None or on <= end)):
                    continue
                if not allow_any_adoption and e.child not in ends:
                    continue  # 第727条：養子と、養親及びその血族との間（養子が当事者のときだけ使う）
            elif _date(rec_when["on"]) > on:
                continue
            out.append(e)
        return out

    def blood(self, a: str, b: str, on: _dt.date, *, allow_any_adoption: bool = False) -> tuple[int, list[_Edge]] | None:
        """a と b の血族の親等（最も近いもの）と、たどった関係。なければ None。"""
        edges = self._edges_on(on, frozenset({a, b}), allow_any_adoption)
        parents: dict[str, list[_Edge]] = {}
        children: dict[str, list[_Edge]] = {}
        for e in edges:
            parents.setdefault(e.child, []).append(e)
            children.setdefault(e.parent, []).append(e)
        # a から上へ（祖先と世代数、たどった関係）
        up: dict[str, tuple[int, list[_Edge]]] = {a: (0, [])}
        q: deque[str] = deque([a])
        while q:
            x = q.popleft()
            d, path = up[x]
            if d >= BLOOD_DEGREE_MAX:
                continue
            for e in sorted(parents.get(x, []), key=lambda e: e.rid):
                if e.parent not in up:
                    up[e.parent] = (d + 1, path + [e])
                    q.append(e.parent)
        best: tuple[int, list[_Edge]] | None = None
        for anc, (u, upath) in sorted(up.items(), key=lambda kv: (kv[1][0], kv[0])):
            # 祖先から下へ b まで（第726条第2項：同一の祖先にさかのぼり、他の一人に下る）
            down: dict[str, tuple[int, list[_Edge]]] = {anc: (0, [])}
            q = deque([anc])
            while q:
                x = q.popleft()
                d, path = down[x]
                if x == b:
                    break
                if u + d >= BLOOD_DEGREE_MAX:
                    continue
                for e in sorted(children.get(x, []), key=lambda e: e.rid):
                    if e.child not in down:
                        down[e.child] = (d + 1, path + [e])
                        q.append(e.child)
            if b in down:
                total = u + down[b][0]
                if best is None or total < best[0]:
                    best = (total, upath + down[b][1])
        if best is None or best[0] > BLOOD_DEGREE_MAX:
            return None
        return best

    # --- 配偶者・姻族（民法第725条・第728条） ---

    def spouse_record(self, a: str, b: str, on: _dt.date) -> Mapping[str, Any] | None:
        """a と b の婚姻で、その日に続いているもの（法律上の配偶者）。"""
        for m in sorted(self.marriages, key=lambda r: r["id"]):
            pair = {m["roles"]["spouse_a"], m["roles"]["spouse_b"]}
            if pair == {a, b} and _in_marriage(m, on):
                return m
        return None

    def affinity_marriages(self, person: str, on: _dt.date) -> list[tuple[Mapping[str, Any], str, bool | None]]:
        """person の婚姻のうち、その日に姻族関係を生じさせうるもの：(記録, 相手, 姻族関係が続くか〔None は決めない〕)。"""
        out = []
        for m in sorted(self.marriages, key=lambda r: r["id"]):
            a, b = m["roles"]["spouse_a"], m["roles"]["spouse_b"]
            if person not in (a, b):
                continue
            other = b if person == a else a
            if _date(m["when"]["from_on"]) > on:
                continue
            out.append((m, other, _affinity_continues(m, on)))
        return out


def _in_marriage(m: Mapping[str, Any], on: _dt.date) -> bool:
    w = m["when"]
    start = _date(w["from_on"])
    end = _date(w["to_on"]) if w.get("to_on") else None
    return start <= on and (end is None or on <= end)


def _affinity_continues(m: Mapping[str, Any], on: _dt.date) -> bool | None:
    """婚姻による姻族関係がその日に続くか（民法第728条）。婚姻中なら True。"""
    if _in_marriage(m, on):
        return True
    ended_by = m.get("attributes", {}).get("ended_by")
    if ended_by == "divorce":
        return False  # 第728条第1項
    if ended_by == "death":
        t = m.get("attributes", {}).get("affinity_termination_on")
        return not (t is not None and _date(t) <= on)  # 第728条第2項
    return None  # 取消し・終わり方の記録なし：この版では決めない


def relation_index(ir: Mapping[str, Any]) -> RelationIndex:
    return RelationIndex.of(ir)


def _ids_states(edges: Iterable[_Edge], extra: Iterable[Mapping[str, Any]] = ()) -> tuple[tuple[str, ...], frozenset[State]]:
    ids = {e.rid for e in edges}
    states: set[State] = set()
    for e in edges:
        states |= e.states
    for r in extra:
        ids.add(r["id"])
        states |= _state_of(r)
    return tuple(sorted(ids)), frozenset(states)


def kinship(idx: RelationIndex, a: str, b: str, on: _dt.date) -> Kinship:
    """その日の現況で、b が a の「自己」「配偶者」「6親等内の血族」「3親等内の姻族」か（民法第725条）。"""
    if a == b:
        return Kinship(True, "本人", 0)
    m = idx.spouse_record(a, b, on)
    if m is not None:
        ids, states = _ids_states((), (m,))
        return Kinship(True, "配偶者", 0, ids, states)
    found = idx.blood(a, b, on)
    if found is not None:
        ids, states = _ids_states(found[1])
        return Kinship(True, "血族", found[0], ids, states)
    undecided: list[str] = []
    if idx.blood(a, b, on, allow_any_adoption=True) is not None:
        undecided.append("養子縁組の当事者でない人の間の関係（民法第727条の範囲）を判定しない")
    # 姻族：配偶者の血族（a の婚姻の相手 s と b が血族）・自己の血族の配偶者（b の婚姻の相手 s と a が血族）
    for person, other_end in ((a, b), (b, a)):
        for rec, spouse, cont in idx.affinity_marriages(person, on):
            hit = idx.blood(spouse, other_end, on) if spouse != other_end else None
            if hit is None or hit[0] > AFFINITY_DEGREE_MAX:
                continue
            if cont is True:
                ids, states = _ids_states(hit[1], (rec,))
                return Kinship(True, "姻族", hit[0], ids, states)
            if cont is None:
                undecided.append(f"婚姻 {rec['id']} の終わった後の姻族関係（民法第728条）を判定しない")
    if undecided:
        return Kinship(None, "", None, note="・".join(dict.fromkeys(undecided)))
    return Kinship(False, "", None)


__all__ = ["AFFINITY_DEGREE_MAX", "BLOOD_DEGREE_MAX", "Kinship", "RelationIndex", "kinship", "relation_index"]

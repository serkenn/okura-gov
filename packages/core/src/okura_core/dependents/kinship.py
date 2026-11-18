"""人と人の親族の関係を、中間表現の関係の記録から導く（ある日の現況）。

2026-11-12：rules/personal_deductions/kinship.py から共有の場所（okura_core/dependents）に移した（扶養の割当てを所得税と住民税で使う：
juminzei README JM-24〜26）。personal_deductions/kinship.py は名前を写すだけのファイルとして残す。

所得税法は「親族」の定義を置かない。最高裁判決と国税庁の説明は民法の親族と読む（docs/public-sources/20261109_impl-prep_misc-age-kinship-attribution.md §2.2・§2.3）。
民法の規定は docs/public-sources/20261109_R4-modeling_concepts.md §3.1：第725条（6親等内の血族・配偶者・3親等内の姻族）、第726条（親等の数え方）、
第727条（養子と養親及びその血族）、第728条（離婚で姻族関係は終了し、死亡では生存配偶者の意思表示で終了）、第729条（離縁）。

親族の判定の道具（relative）と、親族の候補の列挙（relatives_of）を持つ。結論は True（親族）・False（記録の関係から導けない）・None（決められない：
養子縁組を養子が当事者でない形でたどる場合、婚姻が取消し・終わり方の記録なしで終わった後の姻族関係）。
法令の値は民法の条文の親等（6・3）と、里子・養護受託老人の年齢（所基通2−49）だけで、どれも年分で変わらない。
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .ir_facts import IrIndex, covers, date_of

#: 民法第725条第1号・第3号の親等（docs/public-sources/20261109_R4-modeling_concepts.md §3.1）。
BLOOD_DEGREE_MAX = 6
AFFINITY_DEGREE_MAX = 3
#: 里子の年齢の上限（未満。所基通2−49「原則18歳未満」）と養護受託老人の年齢の下限（以上。原則65歳以上）：§3.1。
FOSTER_CHILD_AGE_LIMIT = 18
ELDERLY_ENTRUSTED_AGE_MIN = 65


@dataclass(frozen=True)
class Kin:
    """a から見た b の関係（ある日の現況）。"""

    relative: bool | None
    kind: str = ""  # 血族・配偶者・姻族・里子・養護受託老人
    degree: int | None = None
    record_ids: tuple[str, ...] = ()
    b_is_child: bool = False  # b が a の子（出生・養子縁組）
    b_is_ascendant: bool = False  # b が a の直系の尊属（出生・養子縁組の連なり）


NOT_KIN = Kin(False)


@dataclass(frozen=True)
class _Edge:
    parent: str
    child: str
    rid: str
    adoption: bool


def parent_edges(idx: IrIndex, person: str, on: _dt.date) -> list[_Edge]:
    """person が親か子である、on に続いている親子の関係（出生・認知は on 以前に成立、養子縁組は期間の中）。"""
    out: list[_Edge] = []
    for r in idx.of("parentage", person):
        if date_of(r["when"]["on"]) <= on:
            out.append(_Edge(r["roles"]["parent"], r["roles"]["child"], r["id"], False))
    for r in idx.of("adoption", person):
        w = r["when"]
        start = date_of(w["from_on"])
        end = date_of(w["to_on"]) if w.get("to_on") else None
        if start <= on and (end is None or on <= end):
            out.append(_Edge(r["roles"]["adoptive_parent"], r["roles"]["adoptee"], r["id"], True))
    return out


def _search_blood(idx: IrIndex, a: str, on: _dt.date, limit: int) -> dict[str, tuple[int, list[_Edge], bool, bool]]:
    """a から血族の親等 limit まで届く人 → (親等, たどった関係, 上りだけか, 下りだけか)。a 自身は含まない（第726条：同一の祖先にさかのぼり、下る）。"""
    # 状態：(人, 0=まだ上ってよい, 1=下りに入った)。値：(親等, たどった関係, 上ったか)
    seen: dict[tuple[str, int], tuple[int, list[_Edge], bool]] = {(a, 0): (0, [], False)}
    frontier: list[tuple[str, int]] = [(a, 0)]
    found: dict[str, tuple[int, list[_Edge], bool, bool]] = {}
    while frontier:
        nxt: list[tuple[str, int]] = []
        for state in frontier:
            x, phase = state
            d, path, went_up = seen[state]
            if d >= limit:
                continue
            for e in sorted(parent_edges(idx, x, on), key=lambda e: e.rid):
                options: list[tuple[str, int, bool]] = []
                if e.child == x and phase == 0:  # 親へ上る
                    options.append((e.parent, 0, True))
                if e.parent == x:  # 子へ下る
                    options.append((e.child, 1, went_up))
                for y, new_phase, new_up in options:
                    ns = (y, new_phase)
                    if ns in seen or y == a:
                        continue
                    new_path = path + [e]
                    seen[ns] = (d + 1, new_path, new_up)
                    nxt.append(ns)
                    prev = found.get(y)
                    if prev is None or d + 1 < prev[0]:
                        found[y] = (d + 1, new_path, new_phase == 0, new_phase == 1 and not new_up)
        frontier = nxt
    return found


def _blood(idx: IrIndex, a: str, b: str, on: _dt.date, limit: int = BLOOD_DEGREE_MAX) -> Kin | None:
    """a と b の血族の関係（最も近いもの）。なければ None。縁組の関係を養子が当事者でない形でたどるなら relative は None（第727条の範囲を決めない）。"""
    found = _search_blood(idx, a, on, limit).get(b)
    if found is None:
        return None
    degree, path, up, down = found
    ids = tuple(sorted({e.rid for e in path}))
    if any(e.adoption and e.child not in (a, b) for e in path):
        return Kin(None, "血族", degree, ids)
    return Kin(True, "血族", degree, ids, b_is_child=down and degree == 1, b_is_ascendant=up)


def marriage_active(rec: Mapping[str, Any], on: _dt.date) -> bool:
    w = rec["when"]
    start = date_of(w["from_on"])
    end = date_of(w["to_on"]) if w.get("to_on") else None
    return start <= on and (end is None or on <= end)


def other_spouse(rec: Mapping[str, Any], person: str) -> str:
    roles = rec["roles"]
    return roles["spouse_b"] if roles["spouse_a"] == person else roles["spouse_a"]


def _affinity_continues(rec: Mapping[str, Any], on: _dt.date) -> bool | None:
    """姻族関係がその日に続くか（民法第728条）。"""
    if marriage_active(rec, on):
        return True
    if date_of(rec["when"]["from_on"]) > on:
        return False
    a = rec.get("attributes", {})
    if a.get("ended_by") == "divorce":
        return False
    if a.get("ended_by") == "death":
        t = a.get("affinity_termination_on")
        return not (t is not None and date_of(t) <= on)
    return None


def _spouse_rec(idx: IrIndex, a: str, b: str, on: _dt.date) -> Mapping[str, Any] | None:
    for m in idx.of("marriage", a):
        if other_spouse(m, a) == b and marriage_active(m, on):
            return m
    return None


def _birth(idx: IrIndex, pid: str) -> _dt.date:
    return next(_dt.date.fromisoformat(p["birth_on"]) for p in idx.ir["persons"] if p["id"] == pid)


def age_on(birth: _dt.date, on: _dt.date) -> int:
    """on の終了時の年齢（年齢計算ニ関スル法律。翌日の暦の上の満年齢）。"""
    nxt = on + _dt.timedelta(days=1)
    return nxt.year - birth.year - ((nxt.month, nxt.day) < (birth.month, birth.day))


def foster_of(idx: IrIndex, caregiver: str, placed: str, on: _dt.date) -> Kin | None:
    """里親に委託された児童・養護受託者に委託された老人（所法2①三十四、所基通2−49）。親族でないが扶養親族の対象。"""
    for r in idx.of("foster_placement", caregiver):
        if r["roles"]["caregiver"] != caregiver or r["roles"]["placed_person"] != placed or not covers(r.get("when"), on):
            continue
        age = age_on(_birth(idx, placed), on)
        if r["attributes"]["placement"] == "foster_child" and age < FOSTER_CHILD_AGE_LIMIT:
            return Kin(True, "里子", None, (r["id"],))
        if r["attributes"]["placement"] == "elderly_entrustment" and age >= ELDERLY_ENTRUSTED_AGE_MIN:
            return Kin(True, "養護受託老人", None, (r["id"],))
    return None


def kin(idx: IrIndex, a: str, b: str, on: _dt.date) -> Kin:
    """on の a から見た b の親族関係。"""
    if a == b:
        return NOT_KIN
    sp = _spouse_rec(idx, a, b, on)
    if sp is not None:
        return Kin(True, "配偶者", 0, (sp["id"],))
    blood = _blood(idx, a, b, on)
    if blood is not None:
        return blood
    best: Kin | None = None
    for side, me, other in ((0, a, b), (1, b, a)):
        for m in idx.of("marriage", me):
            s = other_spouse(m, me)
            if s == other or date_of(m["when"]["from_on"]) > on:
                continue
            cont = _affinity_continues(m, on)
            if cont is False:
                continue
            via = _blood(idx, s, other, on, AFFINITY_DEGREE_MAX)
            if via is None:
                continue
            ids = tuple(sorted({m["id"], *via.record_ids}))
            if via.relative is True and cont is True:
                return Kin(True, "姻族", via.degree, ids, b_is_ascendant=via.b_is_ascendant and side == 0)
            if best is None:
                best = Kin(None, "姻族", via.degree, ids)
    return best if best is not None else NOT_KIN


def relatives_of(idx: IrIndex, a: str, on: _dt.date, persons: Iterable[str]) -> dict[str, Kin]:
    """persons のうち、a の親族・里子・養護受託老人（True）か、決められない（None）人 → Kin。"""
    out: dict[str, Kin] = {}
    for b in persons:
        if b == a:
            continue
        k = foster_of(idx, a, b, on) or kin(idx, a, b, on)
        if k.relative is not False:
            out[b] = k
    return out

"""規則モジュール hifuyosha：被保険者から見た被扶養者の続柄の区分（判定日の現況）。

健保法第3条第7項第1号〜第4号と、国共済法・地共済法 第2条第1項第2号イ〜ハ（私学は国共済法の準用）の範囲：
docs/public-sources/20261109_round2_kyosai-law-and-criteria.md §1.1・§1.2、docs/public-sources/20261109_round2_kyosai-separate-address.md §1.1。

- 健保：直系尊属・配偶者（事実婚を含む）・子・孫・兄弟姉妹は同居を要しない（第1号）。それ以外の三親等内の親族（第2号）、
  事実婚の配偶者の父母・子（第3号）、その配偶者の死亡後の父母・子（第4号）は同一の世帯に属することを要する。
- 共済：配偶者・子・父母・孫・祖父母・兄弟姉妹は同居を要しない（イ）。それ以外の三親等内の親族（ロ。曾祖父母を含む）、
  事実婚の配偶者の父母・子と死亡後の父母・子（ハ）は同一の世帯に属することを要する。
- 三親等内の親族は民法第725条・第726条（血族は親等、姻族は配偶者の血族と血族の配偶者）。親族のたどり方は relations.RelationView。
  姻族関係は離婚で終わり、死亡では生存配偶者の意思表示（affinity_termination_on）で終わる（民法第728条。読み：記録の欄で判定）。
- 第4号の「引き続き」（健保）は、事実婚が配偶者の死亡まで続いていたことだけを見る（同一の世帯が引き続いたかは同一の世帯の判定に任せる）。
"""

from __future__ import annotations

import datetime as _dt
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from ...relations import RelationView
from .calc import COHABITATION, KYOSAI, NO_COHABITATION, OUTSIDE

#: 血族の親等の上限（三親等内の親族）と、直系尊属をたどる段数の上限（健保の直系尊属は親等を問わない。たどる上限は組合せの爆発を抑える値）。
DEGREE_MAX = 3
ASCENDANT_MAX = 6


@dataclass(frozen=True)
class Kinship:
    """被保険者から見た人の区分。"""

    category: str
    spouse: bool
    record_ids: tuple[str, ...] = ()


def _blood(view: RelationView, start: str, on: _dt.date, limit: int) -> dict[str, tuple[int, int, tuple[str, ...]]]:
    """start から血族をたどる：人 → (上った数, 下った数, 使った記録の ID)。同じ祖先にさかのぼってから下る（民法第726条）。"""
    found: dict[str, tuple[int, int, tuple[str, ...]]] = {}
    seen: set[tuple[str, int]] = {(start, 0)}
    queue: deque[tuple[str, int, int, int, tuple[str, ...]]] = deque([(start, 0, 0, 0, ())])
    while queue:
        x, phase, up, down, ids = queue.popleft()
        if x != start and x not in found:
            found[x] = (up, down, ids)
        if up + down >= limit:
            continue
        nexts: list[tuple[str, int, int, int, str]] = []
        if phase == 0:
            nexts += [(r.other, 0, up + 1, down, r.record_id) for r in view.parents(x, on)]
        nexts += [(r.other, 1, up, down + 1, r.record_id) for r in view.children(x, on)]
        for other, ph, u, d, rid in nexts:
            if (other, ph) in seen or other == start:
                continue
            seen.add((other, ph))
            queue.append((other, ph, u, d, ids + (rid,)))
    return found


def _spouses_for_affinity(view: RelationView, person: str, on: _dt.date) -> list[tuple[str, str]]:
    """姻族をたどる配偶者（続いている婚姻と、死亡で終わり姻族関係の終了の意思表示がない婚姻）：(配偶者, 記録の ID)。"""
    out: list[tuple[str, str]] = []
    for r in view.of(person, ("marriage",)):
        if r.from_on is not None and r.from_on > on:
            continue
        attrs = r.record.get("attributes", {})
        if r.active_on(on):
            out.append((r.other, r.record_id))
        elif attrs.get("ended_by") == "death":
            term = attrs.get("affinity_termination_on")
            if term is None or _dt.date.fromisoformat(term) > on:
                out.append((r.other, r.record_id))
    return out


def classify(
    view: RelationView,
    insured: str,
    person: str,
    on: _dt.date,
    scheme: str,
    *,
    de_facto: Callable[[str, str, _dt.date], tuple[bool, tuple[str, ...]]],
    death_on: Mapping[str, _dt.date | None],
) -> Kinship:
    """insured（被保険者・組合員）から見た person の区分（NO_COHABITATION・COHABITATION・OUTSIDE）と、配偶者か。

    de_facto(a, b, 日)：a と b がその日に事実婚の関係にあるか（判断.事実婚）と、その判断の ID。
    death_on：人 → 死亡日（事実婚の配偶者の死亡後の父母・子の判定に使う）。
    """
    kyosai = scheme in KYOSAI
    legal = [rid for other, rid in ((r.other, r.record_id) for r in view.spouses(insured, on)) if other == person]
    defacto, dj = de_facto(insured, person, on)
    if legal or defacto:
        return Kinship(NO_COHABITATION, True, tuple(legal) + dj)
    blood = _blood(view, insured, on, ASCENDANT_MAX)
    if person in blood:
        up, down, ids = blood[person]
        degree = up + down
        if down == 0:  # 直系尊属
            if not kyosai or up <= 2:
                return Kinship(NO_COHABITATION, False, ids)
            return Kinship(COHABITATION if degree <= DEGREE_MAX else OUTSIDE, False, ids)
        if up == 0 and down <= 2:  # 子・孫
            return Kinship(NO_COHABITATION, False, ids)
        if up == 1 and down == 1:  # 兄弟姉妹
            return Kinship(NO_COHABITATION, False, ids)
        if degree <= DEGREE_MAX:
            return Kinship(COHABITATION, False, ids)
    # 姻族（配偶者の血族）
    for spouse, rid in _spouses_for_affinity(view, insured, on):
        if spouse == person:
            continue
        sb = _blood(view, spouse, on, DEGREE_MAX)
        if person in sb and sb[person][0] + sb[person][1] <= DEGREE_MAX:
            return Kinship(COHABITATION, False, (rid,) + sb[person][2])
    # 姻族（血族の配偶者）
    for relative, (up, down, ids) in sorted(blood.items()):
        if up + down > DEGREE_MAX:
            continue
        for spouse, rid in _spouses_for_affinity(view, relative, on):
            if spouse == person:
                return Kinship(COHABITATION, False, ids + (rid,))
    # 事実婚の配偶者の父母・子（健保第3号・第4号、共済ハ）
    candidates = {r.other for r in view.of(insured)} | {p for p in death_on}
    for partner in sorted(candidates):
        if partner in (insured, person):
            continue
        dead = death_on.get(partner)
        when = dead if dead is not None and dead <= on else on
        ok, pj = de_facto(insured, partner, when)
        if not ok:
            continue
        near = [r for r in view.parents(partner, on)] + [r for r in view.children(partner, on)]
        for r in near:
            if r.other == person:
                return Kinship(COHABITATION, False, pj + (r.record_id,))
    return Kinship(OUTSIDE, False)


#: 配偶者の「親等」（配偶者は親族の中で最も優先する扶養義務者：PMAC-01。血族・姻族の1親等より近いとして 0 とする）。
SPOUSE_DEGREE = 0


def degrees_from(view: RelationView, person: str, on: _dt.date) -> dict[str, tuple[int, tuple[str, ...]]]:
    """person から見た三親等内の親族の親等（民法第726条。配偶者は SPOUSE_DEGREE）と、使った記録の ID。
    血族は親等、姻族は配偶者の血族の親等と、血族の配偶者の親等（民法第725条・第726条の読み）。同じ人は近い方。"""
    out: dict[str, tuple[int, tuple[str, ...]]] = {}

    def put(p: str, d: int, ids: tuple[str, ...]) -> None:
        if p != person and (p not in out or d < out[p][0]):
            out[p] = (d, ids)

    for r in view.spouses(person, on):
        put(r.other, SPOUSE_DEGREE, (r.record_id,))
    blood = _blood(view, person, on, DEGREE_MAX)
    for p, (up, down, ids) in blood.items():
        put(p, up + down, ids)
    for spouse, rid in _spouses_for_affinity(view, person, on):
        for p, (up, down, ids) in _blood(view, spouse, on, DEGREE_MAX).items():
            put(p, up + down, (rid,) + ids)
    for relative, (up, down, ids) in blood.items():
        for spouse, rid in _spouses_for_affinity(view, relative, on):
            put(spouse, up + down, ids + (rid,))
    return out


__all__ = ["Kinship", "SPOUSE_DEGREE", "classify", "degrees_from"]

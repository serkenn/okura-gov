"""扶養親族等の所属を決める純粋関数（2026-11-12。juminzei README JM-24〜26。rules/personal_deductions/allocation.py から移して一般にした）。

同じ人が二以上の人の扶養親族等に当たりうるとき、いずれの人の扶養親族等とするか：

- 所得税（Rule.INCOME_TAX。所得税法施行令第218条〜第219条。docs/public-sources/20261109_impl-prep_misc-age-kinship-attribution.md §3.2）：
  配偶者が同一生計配偶者（又は配偶者特別控除の対象）にも当たるときは、他の人だけが記載していればその人、双方・どちらもなければ配偶者（218・218の2）。
  扶養親族等の記載が1人ならその人、2人以上なら既に記載している人（最も早い提出日）、それでも決まらなければ所得の合計額が最も大きい人（219②）。
- 住民税（Rule.LOCAL_TAX。地方税法施行令第46条の3〜第46条の5。docs/public-sources/20261109_impl-prep_juminzei-hikazei-fuyo-shinkoku.md §4.2）：
  配偶者の扱いは同じ形（46の3・46の4）。記載（申告書・給与支払報告書等、申請書があれば申請書）が1人ならその人、2人以上・記載がなく決まらないときは
  前年の総所得金額・退職所得金額・山林所得金額の合計額が最も大きい人（46の5②。所得税の「既に記載している人」の段はない）。

所得の比べ方（どの額で比べ、同額のときどうするか）は呼ぶ側が pick で渡す（所得税は選択.扶養の所属、住民税は一次情報の分かれ目）。
扶養親族等の候補（親族・生計・事業専従者・合計所得金額の上限）の判定も呼ぶ側が Candidacy で渡す（所得税と住民税で合計所得金額が違う：地法第328条）。
"""

from __future__ import annotations

import datetime as _dt
import enum
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..registry import Decided, StageValue, overlaps_year
from ..result import Split, State
from .family import (
    C_SPOUSE,
    DEP_SECTIONS,
    REMITTANCE_DOCUMENTS,
    REMITTANCE_SPECIAL,
    Family,
    is_senju,
    marks,
)
from .ir_facts import date_of
from .kinship import other_spouse


class Rule(enum.Enum):
    """所属を決める規則。"""

    INCOME_TAX = "所得税法施行令第218条〜第219条"
    LOCAL_TAX = "地方税法施行令第46条の3〜第46条の5"


@dataclass(frozen=True)
class Candidacy:
    """c が d の扶養親族等（扶養親族・特定親族）の申告者・納税義務者になりうるか（所属を除く要件）と、その材料。"""

    ok: bool
    uses: tuple[StageValue, ...] = ()
    ids: frozenset[str] = frozenset()
    states: frozenset[State] = frozenset()


@dataclass(frozen=True)
class DepListing:
    """d を扶養親族・特定親族として記載した書類（又は選択）1件。on は提出日（住民税の規則では使わない）。"""

    filer: str
    on: _dt.date | None
    record_id: str


@dataclass
class Alloc:
    """d ごとの割当ての結果。"""

    claimant: str | None = None
    uses: list[StageValue] = field(default_factory=list)
    ids: set[str] = field(default_factory=set)
    states: set[State] = field(default_factory=set)
    problems: list[str] = field(default_factory=list)
    missing: list[Split] = field(default_factory=list)


#: 所得の比べ方（候補の人 → 決まった人。同額で決まらなければ選択・分かれ目を Alloc に足して候補の1人を返す）。
Pick = Callable[[list[str], Alloc], "str | None"]


def allocate_one(
    eligible: Mapping[str, Candidacy],
    spouse: str | None,
    spouse_ok: bool,
    spouse_uses: Sequence[StageValue],
    spouse_listing_ids: Sequence[str],
    dep_listings: Sequence[DepListing],
    other_listing_ids: Mapping[str, Iterable[str]],
    pick: Pick,
    rule: Rule,
) -> Alloc:
    """1人の扶養親族等の所属（所得税：所令218・218の2・219、住民税：地令46の3〜46の5）。

    eligible：申告者・納税義務者になりうる人 → 候補か（ok）と材料。spouse：d を配偶者とする人（いなければ None）、spouse_ok：d がその人の
    同一生計配偶者か配偶者特別控除の対象に当たりうるか、spouse_listing_ids：その人が d を配偶者として記載した記録（なければ空）。
    dep_listings：d を扶養親族等として記載した書類（候補でない人の記載を含んでよい）。other_listing_ids：記載した人 → d についての記録の ID（根拠に足す）。
    """
    a = Alloc()
    for e in eligible.values():
        a.ids |= e.ids
        a.states |= e.states
    cand = sorted(c for c, e in eligible.items() if e.ok)
    for c in cand:
        a.uses += eligible[c].uses
    listed = [l for l in dep_listings if l.filer in cand]
    dep_listers = sorted({l.filer for l in listed})
    for c in cand:
        a.ids |= set(other_listing_ids.get(c, ()))
    if spouse is not None and spouse_ok:
        a.uses += list(spouse_uses)
        a.ids |= set(spouse_listing_ids)
        if not dep_listers or spouse_listing_ids:
            return a  # 配偶者（所令218②・218の2②、地令46の3・46の4：双方の記載・定められないときは夫又は妻の同一生計配偶者）
    if not cand:
        return a
    if len(cand) == 1 and not dep_listers:
        a.claimant = cand[0]
        return a
    if len(dep_listers) == 1:
        a.claimant = dep_listers[0]
        return a
    if len(dep_listers) >= 2:
        if rule is Rule.INCOME_TAX:  # 所令219②一：既に申告書等の記載によりその居住者の扶養親族等としている居住者（最も早い提出日）
            earliest = min(l.on for l in listed if l.on is not None)
            first = sorted({l.filer for l in listed if l.on == earliest})
            if len(first) == 1:
                a.claimant = first[0]
                return a
            a.claimant = pick(first, a)
            return a
        a.claimant = pick(dep_listers, a)  # 地令46の5②：記載が2人以上なら所得の合計額が最も大きい納税義務者
        return a
    a.claimant = pick(cand, a)  # 所令219②二・地令46の5②：記載がなく決まらないときは所得の合計額が最も大きい人
    return a


def largest(amounts: Mapping[str, int]) -> list[str]:
    """所得の合計額が最も大きい人（同額なら全員。並びは名前の順）。"""
    if not amounts:
        return []
    top = max(amounts.values())
    return sorted(p for p, v in amounts.items() if v == top)


# ---------------------------------------------------------------------------
# 配偶者の選び方（所令220①③。年の中途の死亡と再婚）
# ---------------------------------------------------------------------------


def rule_220_3(fam: Family, a: str, names: list[str]) -> tuple[str | None, tuple[str, ...]] | None:
    """所令220③：死亡した配偶者が、その死亡の日までに提出された申告書等の記載に従って他の居住者の扶養親族とされていたときは、
    死亡した配偶者はその他の居住者の扶養親族、再婚した配偶者は a の同一生計配偶者（又は他の居住者の扶養親族）とする。当たらなければ None。

    死亡の日までに提出期限が来ていない申告書等の場合の「前年分の最後に提出した申告書等」は、その年分の記載だけを見る（前年分の書類は年分の situation にない）。
    """
    for b in names:
        death = fam.deaths[b]
        if death is None or death.year != fam.ctx.year:
            continue
        early = [l for l in fam.listing if l.person == b and l.filer != a and l.section in DEP_SECTIONS and not l.planned and l.on <= death]
        if not early:
            continue
        others = [n for n in names if n != b]
        return (others[0] if len(others) == 1 else None), tuple(sorted(l.record_id for l in early))
    return None


def choose_spouses(fam: Family, decide: Callable[[str, str], Decided], states: dict[str, set[State]], ids: dict[str, set[str]]) -> dict[str, str | None]:
    """人 → その人の配偶者（法律婚のグループの相手。いなければ None）。死亡と再婚が同じ年なら所令220① で一人に絞る。

    decide は判断・選択の値を読む窓口（ctx.decision）。
    """
    chosen: dict[str, str | None] = {}
    for a in fam.ctx.persons:
        cand = fam.spouse_candidates[a]
        if not cand:
            chosen[a] = None
            continue
        if len(cand) == 1:
            chosen[a] = other_spouse(cand[0], a)
            ids[a] |= {cand[0]["id"]}
            continue
        names = [other_spouse(m, a) for m in cand]
        for m in cand:
            ids[a] |= {m["id"]}
        third = rule_220_3(fam, a, names)
        if third is not None:
            chosen[a] = third[0]
            ids[a] |= set(third[1])
            continue
        listed = sorted({l.person for l in fam.listing if l.filer == a and l.section == "spouse" and l.person in names})
        if len(listed) == 1:
            chosen[a] = listed[0]
            continue
        d = decide(C_SPOUSE, f"所令220:{a}")
        ids[a] |= set(d.record_ids)
        states[a] |= d.states
        chosen[a] = d.value if d.value else None
    return chosen


# ---------------------------------------------------------------------------
# 申告者・納税義務者との関係の事実（申告者が決まった後の、組ごとの材料）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RelationFacts:
    """申告者 c から見た扶養親族等 d の、組ごとの事実（所法2①三十四の二・措法41の16・所法79③・所令262④）。"""

    kin: bool
    child: bool
    cohab: bool  # 申告者又はその配偶者と同居を常況としているか（措法41の16：同居老親等）
    cohab_etc: bool  # 申告者・配偶者・申告者と生計を一にする親族のいずれかと同居（所法79③：同居特別障害者）
    ascendant: bool  # 申告者又はその配偶者の直系尊属か
    doc: bool  # 国外居住親族の親族関係書類と送金関係書類（所令262④一）
    doc_study: bool  # 留学の区分の書類（所令262④二）
    doc_38: bool  # 38万円以上の区分の書類（所令262④三）
    remit: int  # 申告者から受けた生活費等の支払の額（その年）
    ids: tuple[str, ...]
    cohab_ids: tuple[str, ...]
    doc_ids: tuple[str, ...]
    study_ids: tuple[str, ...]
    doc38_ids: tuple[str, ...]
    remit_ids: tuple[str, ...]
    states: frozenset[State]
    cohab_states: frozenset[State]
    remit_states: frozenset[State]


def relation_facts(fam: Family, c: str, d: str, spouse_of_c: str | None, ids: Iterable[str] = (), on: _dt.date | None = None) -> RelationFacts:
    """c を申告者（住民税では納税義務者）とする d の組ごとの事実。on は書類の日付を比べる判定の時（なければ組の判定の時 fam.t）。"""
    year = fam.ctx.year
    base = set(ids)
    rel = fam.relation(c, d)
    ascendant = rel.b_is_ascendant
    if spouse_of_c is not None and spouse_of_c != d:
        ascendant = ascendant or fam.relation(spouse_of_c, d).b_is_ascendant
    cohab, dec_uses = fam.cohabits(c, d)
    if spouse_of_c is not None and spouse_of_c != d:
        v, more = fam.cohabits(spouse_of_c, d)
        cohab = cohab or v
        dec_uses = dec_uses + more
    cohab_etc = cohab
    for x in fam.neighbours[c]:
        if x in (d, spouse_of_c) or not fam.live_true(c, x):
            continue
        v, more = fam.cohabits(x, d)
        cohab_etc = cohab_etc or v
        dec_uses = dec_uses + more
    extra_ids = {i for dec in dec_uses for i in dec.record_ids}
    extra_states = {s for dec in dec_uses for s in dec.states}
    docs = [r for r in fam.idx.of("foreign_kin_document", d) if r["roles"].get("holder") == c]
    kin_docs = [r["id"] for r in docs if r["attributes"]["document_type"] == "kinship_document"]
    remit_docs = [r["id"] for r in docs if r["attributes"]["document_type"] in REMITTANCE_DOCUMENTS and overlaps_year(r.get("when"), year)]
    t = on if on is not None else fam.t(c, d)
    visa_docs = [r["id"] for r in docs if r["attributes"]["document_type"] == "student_visa_document" and date_of(r["when"]["on"]) <= t]
    special_docs = [r["id"] for r in docs if r["attributes"]["document_type"] == REMITTANCE_SPECIAL and overlaps_year(r.get("when"), year)]
    doc_ids = tuple(sorted(base | set(kin_docs) | set(remit_docs)))
    remits = [r for r in fam.idx.of("remittance", d) if r["roles"].get("sender") == c and r["roles"].get("recipient") == d and overlaps_year(r.get("when"), year)]
    return RelationFacts(
        kin=rel.relative is True,
        child=bool(rel.b_is_child),
        cohab=cohab,
        cohab_etc=cohab_etc,
        ascendant=bool(ascendant),
        doc=bool(kin_docs) and bool(remit_docs),
        doc_study=bool(kin_docs) and bool(remit_docs) and bool(visa_docs),
        doc_38=bool(kin_docs) and bool(special_docs),
        remit=int(sum(r["amounts"]["amount"] for r in remits)),
        ids=tuple(sorted(base)),
        cohab_ids=tuple(sorted(base | extra_ids)),
        doc_ids=doc_ids,
        study_ids=tuple(sorted(set(doc_ids) | set(visa_docs))),
        doc38_ids=tuple(sorted(base | set(kin_docs) | set(special_docs))),
        remit_ids=tuple(sorted(base | {r["id"] for r in remits})),
        states=frozenset(),
        cohab_states=frozenset(extra_states),
        remit_states=marks(remits),
    )


def pair_candidacy(fam: Family, c: str, d: str) -> tuple[bool, set[str], set[State]]:
    """c と d が扶養親族・特定親族の関係に当たりうるか（親族・生計を一にする・事業専従者でない。所得と居住者・納税義務者の要件は呼ぶ側）。"""
    ids: set[str] = set()
    states: set[State] = set()
    if c == d or not fam.is_related(c, d):
        return False, ids, states
    rel = fam.relation(c, d)
    if rel.relative is not True or rel.kind == "配偶者":
        return False, ids, states
    ids |= set(rel.record_ids)
    live = fam.live_decided(c, d)
    if live is None:  # 判断の1か所を置かない傍系の親族の組（Family.slotted）は候補にしない
        return False, ids, states
    states |= live.states
    ids |= set(live.record_ids)
    if live.value is not True:
        return False, ids, states
    if is_senju(fam, c, d):
        return False, ids, states
    return True, ids, states


# ---------------------------------------------------------------------------
# 扶養の区分（控除対象扶養親族・特定扶養親族・老人扶養親族・同居老親等・特定親族・同居特別障害者）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DependentLimits:
    """扶養の区分の年齢・額の基準（パラメータの値を呼ぶ側が渡す。所得税の値：所法2①三十四の二〜四、措法41の16、所法84の2）。"""

    resident_age_min: int
    nr_age_min: int
    nr_plain_age_max: int
    nr_plain_high_min: int
    nr_remit_min: int
    specific_low: int
    specific_high: int
    elderly_min: int
    spec_rel_low: int
    spec_rel_high: int
    spec_rel_cap: int


@dataclass(frozen=True)
class DependentCategories:
    dependent: bool
    control: bool
    specific: bool
    elderly: bool
    cohab_elderly: bool
    specified_relative: bool
    cohab_special: bool


def categorize(
    *,
    allocated: bool,
    dependent_income_ok: bool,
    income: int,
    age: int,
    resident: bool,
    study_abroad: bool,
    disabled: bool,
    special: bool,
    facts: RelationFacts | None,
    lim: DependentLimits,
) -> DependentCategories:
    """申告者・納税義務者に割り当てた d の扶養の区分（personal_deductions/judgments.py の式と同じ要件を1人分の値で書いたもの）。

    allocated：d がその人の扶養親族等に割り当てられたか。dependent_income_ok：扶養親族の合計所得金額の要件を満たすか（所得税と住民税で額が違いうる）。
    """
    if not allocated or facts is None:
        return DependentCategories(False, False, False, False, False, False, False)
    dependent = facts.kin and dependent_income_ok
    plain = (lim.nr_age_min <= age < lim.nr_plain_age_max) or age >= lim.nr_plain_high_min
    banded = lim.nr_plain_age_max <= age < lim.nr_plain_high_min and (
        (study_abroad and facts.doc_study) or (disabled and facts.doc) or (facts.remit >= lim.nr_remit_min and facts.doc_38)
    )
    as_nonresident = (plain and facts.doc) or banded
    control = dependent and (age >= lim.resident_age_min if resident else as_nonresident)
    specific = control and lim.specific_low <= age < lim.specific_high
    elderly = control and age >= lim.elderly_min
    cohab_elderly = elderly and facts.ascendant and facts.cohab
    specified_relative = (
        facts.kin and lim.spec_rel_low <= age < lim.spec_rel_high and income <= lim.spec_rel_cap and not control
    )
    cohab_special = special and dependent and facts.cohab_etc
    return DependentCategories(dependent, control, specific, elderly, cohab_elderly, specified_relative, cohab_special)


__all__ = [
    "Alloc",
    "Candidacy",
    "DepListing",
    "DependentCategories",
    "DependentLimits",
    "Pick",
    "RelationFacts",
    "Rule",
    "allocate_one",
    "categorize",
    "choose_spouses",
    "largest",
    "pair_candidacy",
    "relation_facts",
    "rule_220_3",
]

"""年分の人の組ごとの親族・判断の材料と、申告書等の記載（2026-11-12 に rules/personal_deductions/allocation.py から移した）。

所得税の扶養の割当て（personal_deductions の段）と住民税の扶養の割当て（juminzei の段）が同じ材料を使う（juminzei README JM-24〜26）。
判断・選択の1か所（判断.生計を一にする など）の宣言は personal_deductions が持つ（同じ kind と key を読めば同じ分かれ目：packages/core/README.md §10）。
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ..registry import Decided, StageContext, StageValue, YearContext, heads, overlaps_year
from ..result import OutOfScopeCategory, OutOfScopeReason, Split, State
from .ir_facts import (
    IrIndex,
    covers,
    cut_date,
    date_of,
    departure_day,
    foreign_period_ids,
    income_record_ids,
    judgment_date,
    nonresident_income_split,
)
from .kinship import Kin, kin, marriage_active, other_spouse

# ---------------------------------------------------------------------------
# 名前
# ---------------------------------------------------------------------------

J_SEIKEI = "判断.生計を一にする"
J_DOUKYO = "判断.同居を常況"
C_ATTR = "選択.扶養の所属"
C_SPOUSE = "選択.配偶者の記載"
K_EST = "見積り.親族の合計所得金額"
#: 非居住者の期間の国内源泉所得以外の所得の金額（PD-06。2026-11-12 に中間表現の語彙を足した）。
K_DOMESTIC = "判断.国内源泉所得の内訳"
J_ADDRESS = "判断.住所の所在"

#: 所令218① の申告書等（配偶者控除等申告書を除く：所令219① の申告書等。特定親族特別控除申告書を含む）。
DEP_DOCUMENTS = frozenset(
    {
        "final_return",
        "quasi_final_return",
        "loss_return",
        "employee_dependents_declaration",
        "secondary_salary_dependents_declaration",
        "specific_relative_deduction_declaration",
    }
)
#: 配偶者の記載を見る申告書等（所令218① の列挙）。
SPOUSE_DOCUMENTS = DEP_DOCUMENTS | {"spouse_deduction_declaration"}
#: 確定申告書（年末調整・確定申告をした場合の除外の判定に使う）。
RETURN_DOCUMENTS = frozenset({"final_return", "quasi_final_return", "loss_return"})
#: 源泉徴収の扶養控除等申告書（所法194・195）。
WITHHOLDING_DECLARATIONS = frozenset({"employee_dependents_declaration", "secondary_salary_dependents_declaration"})
DEP_SECTIONS = frozenset({"dependent_relative", "specific_relative"})
#: 国外居住親族の生計を一にすることを明らかにする書類（所令262④一ロ・三ロ、所規47の2）：送金関係書類と38万円送金書類。
REMITTANCE_DOCUMENTS = frozenset({"remittance_document", "remittance_document_special"})
#: 38万円送金書類（所規47の2⑩）。
REMITTANCE_SPECIAL = "remittance_document_special"


def pair_key(a: str, b: str) -> str:
    return f"{min(a, b)}:{max(a, b)}"


def not_implemented(text: str, ids: Iterable[str] = ()) -> OutOfScopeReason:
    return OutOfScopeReason(OutOfScopeCategory.NOT_IMPLEMENTED, text, tuple(sorted(set(ids))))


def marks(records: Iterable[Mapping[str, Any]]) -> frozenset[State]:
    return frozenset(State.from_mark(r["mark"]) for r in records if "mark" in r)


# ---------------------------------------------------------------------------
# 提出した書類の記載（選択を含む）：所得税（所令218〜220）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Listing:
    """申告書等の記載（又は記載するとした選択）1件。section は dependent_relative・specific_relative・spouse。"""

    filer: str
    person: str
    section: str
    on: _dt.date
    record_id: str
    planned: bool  # 選択（提出前）か


def listings(ctx: YearContext) -> list[Listing]:
    """その年分の申告書等の記載（提出した書類と選択）。提出した書類が主で、選択は同じ記載者・相手について提出した書類がないときに使う。"""
    out: list[Listing] = []
    filed_pairs: set[tuple[str, str, str]] = set()
    docs = [r for r in ctx.records("filed_document") if r["attributes"].get("tax_year") == ctx.year and "entries" in r["attributes"]]
    for rec in docs:
        a = rec["attributes"]
        filer = rec["roles"]["filer"]
        doc = a["document_type"]
        on = date_of(rec["when"]["on"])
        for e in a["entries"]:
            sec = e["section"]
            if (sec in DEP_SECTIONS and doc in DEP_DOCUMENTS) or (sec == "spouse" and doc in SPOUSE_DOCUMENTS):
                group = "spouse" if sec == "spouse" else "dep"
                filed_pairs.add((filer, e["person"], group))
                if withdrawn(docs, filer, e["person"], group, on):
                    continue  # 所令218①・219① ただし書、所基通85−2：後に提出した申告書等で異なる記載をした（その記載はもう使わない）
                out.append(Listing(filer, e["person"], sec, on, rec["id"], False))
    for c in ctx.choices(C_ATTR):
        if not overlaps_year(c.get("when"), ctx.year):
            continue
        v = c["value"]
        if v["section"] not in DEP_SECTIONS or v["document_type"] not in DEP_DOCUMENTS:
            continue
        key = (v["filer"], c["subject"]["person"], "dep")
        if key not in filed_pairs:
            out.append(Listing(v["filer"], c["subject"]["person"], v["section"], date_of(c["chosen_at"][:10]), c["id"], True))
    for c in ctx.choices(C_SPOUSE):
        if not overlaps_year(c.get("when"), ctx.year):
            continue
        v = c["value"]
        if v["listed"] is not True or v["document_type"] not in SPOUSE_DOCUMENTS:
            continue
        key = (v["filer"], c["subject"]["spouse"], "spouse")
        if key not in filed_pairs:
            out.append(Listing(v["filer"], c["subject"]["spouse"], "spouse", date_of(c["chosen_at"][:10]), c["id"], True))
    return sorted(out, key=lambda x: (x.person, x.on, x.filer, x.record_id))


def withdrawn(docs: list[Mapping[str, Any]], filer: str, person: str, group: str, on: _dt.date) -> bool:
    """filer が on に記載した person を、その後に提出した申告書等（同じ区分の書類で記載の欄のあるもの）で記載しなかったか。

    所令218①・219① ただし書（後に提出する申告書等にこれと異なる記載をすることにより、区分・所属を変更することを妨げない）と
    所基通85−2（変更は、増加させる者と減少させる者の全員が変更を記載した申告書等を提出する）の読み：記載を減らす者の後の書類に
    記載がなければ、その者の前の記載は使わない。増やす者の記載は、その者の書類の記載として別に数える（法令の読み）。
    """
    allowed = SPOUSE_DOCUMENTS if group == "spouse" else DEP_DOCUMENTS
    sections = {"spouse"} if group == "spouse" else DEP_SECTIONS
    for r in docs:
        a = r["attributes"]
        if r["roles"]["filer"] != filer or a["document_type"] not in allowed or date_of(r["when"]["on"]) <= on:
            continue
        if not any(e["person"] == person and e["section"] in sections for e in a["entries"]):
            return True
    return False


# ---------------------------------------------------------------------------
# 年分の状況（親族の組・配偶者の候補・判断の1か所）
# ---------------------------------------------------------------------------


@dataclass
class Family:
    """年分の中間表現から作る、人の組ごとの親族・判断の材料（段の関数・判断の宣言で共有）。"""

    ctx: YearContext
    idx: IrIndex
    alive: frozenset[str]
    deaths: Mapping[str, _dt.date | None]
    related: Mapping[tuple[str, str], Kin]  # (a, b)（a < b の順）→ 親族関係。a から見た b（None を含む）
    neighbours: Mapping[str, tuple[str, ...]]  # 人 → 親族の候補の人（related のもう一方）
    slotted: frozenset[tuple[str, str]]  # (a, b)（a < b）：判断.生計を一にする の1か所を置く親族の組（Family.judgeable）
    listing: list[Listing]
    spouse_candidates: Mapping[str, list[Mapping[str, Any]]]  # 人 → その年分の配偶者の候補の婚姻の記録（所令220：2人以上は死亡と再婚）
    parent_edges_cache: dict[tuple[str, _dt.date], list[Any]] = field(default_factory=dict)
    #: 判定の時を決める日（死亡の日・出国の日の前日の早い方：ir_facts.cut_date）と、その年の中途の出国の日（PD-05）。
    cuts: Mapping[str, _dt.date | None] = field(default_factory=dict)
    departures: Mapping[str, _dt.date | None] = field(default_factory=dict)

    def cut(self, p: str) -> _dt.date | None:
        return self.cuts.get(p, self.deaths[p])

    def t(self, a: str, b: str) -> _dt.date:
        """判定の時：その年12月31日（当事者が死亡・出国したときはその時。所法85③）。"""
        return on_pair(self.cuts or self.deaths, self.ctx.year, a, b)

    def judge_time(self, judge: str, person: str) -> _dt.date:
        """judge（申告者・配偶者とする人）が person を扶養親族等・配偶者として判定する時（所法85③）：judge のその年12月31日
        （judge がその年の中途で死亡・出国するときはその時）。person がそれより前に死亡していれば死亡の時（同項ただし書）。
        person の出国は判定の時を変えない（出国するのは判定される親族の側：PD-05。2026-11-12）。"""
        t = judgment_date(self.ctx.year, self.cut(judge))
        d = self.deaths.get(person)
        return d if d is not None and d < t else t

    def is_related(self, a: str, b: str) -> bool:
        return (min(a, b), max(a, b)) in self.related

    def relation(self, a: str, b: str) -> Kin:
        """a から見た b の親族関係（向きつき）。"""
        return kin_for(self.idx, a, b, self.t(a, b))

    def judgeable(self, a: str, b: str) -> bool:
        """判断.生計を一にする の1か所がある親族の組か（宣言した1か所だけを聞く。宣言は Family.slotted）。"""
        return (min(a, b), max(a, b)) in self.slotted

    def live_decided(self, a: str, b: str) -> Decided | None:
        if not self.judgeable(a, b):
            return None
        return self.ctx.decision(J_SEIKEI, pair_key(a, b))

    def live_true(self, a: str, b: str) -> bool:
        d = self.live_decided(a, b)
        return d is not None and d.value is True

    def cohabit_decided(self, a: str, b: str) -> Decided | None:
        try:
            return self.ctx.decision(J_DOUKYO, pair_key(a, b))
        except KeyError:
            return None

    def cohabits(self, a: str, b: str) -> tuple[bool, list[Decided]]:
        d = self.cohabit_decided(a, b)
        return (d is not None and d.value is True), ([d] if d is not None else [])


def kin_for(idx: IrIndex, a: str, b: str, on: _dt.date) -> Kin:
    """親族（foster を含む）。a から見た b。里子・養護受託老人は親族ではないが扶養親族の対象になる。"""
    from .kinship import foster_of  # noqa: PLC0415

    return foster_of(idx, a, b, on) or kin(idx, a, b, on)


def spouse_candidates(
    ctx: YearContext, idx: IrIndex, deaths: Mapping[str, _dt.date | None], alive: frozenset[str], cuts: Mapping[str, _dt.date | None] | None = None
) -> dict[str, list[Mapping[str, Any]]]:
    out: dict[str, list[Mapping[str, Any]]] = {}
    year_end = _dt.date(ctx.year, 12, 31)
    for a in ctx.persons:
        t_a = judgment_date(ctx.year, (cuts or deaths)[a])  # 判定の時は死亡・出国の時、配偶者の死亡は死亡だけ
        items: list[Mapping[str, Any]] = []
        for m in idx.of("marriage", a):
            b = other_spouse(m, a)
            if b not in alive:
                continue
            d_b = deaths[b]
            on = t_a if d_b is None or d_b >= t_a else d_b  # 配偶者が既に死亡していれば死亡の時（所法85③）
            if on < _dt.date(ctx.year, 1, 1) or on > year_end:
                continue
            if marriage_active(m, on):
                items.append(m)
        out[a] = items
    return out


def relation_groups(ctx: YearContext, alive: frozenset[str]) -> list[list[str]]:
    """親子・養子縁組・婚姻・里親委託の記録でつながった、その年分に生存している人の集まり（2人以上）。関係の記録がない人は親族の候補にならない。

    つながりは、その年分に生存していない人（死亡した親・配偶者）を通ってもよい（例：死亡した配偶者の父母は姻族のまま〔民法728②〕、
    死亡した親を通した祖父母と孫は血族。2026-11-11 の結合のレビュー：以前は生存している人どうしの記録だけでつなぎ、死亡した人を通る親族を落としていた）。
    """
    parent = {p["id"]: p["id"] for p in ctx.ir["persons"]}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for kind in ("parentage", "adoption", "marriage", "foster_placement"):
        for r in ctx.records(kind):
            ps = sorted(set(r["roles"].values()) & set(parent))
            for a, b in zip(ps, ps[1:]):
                parent[find(a)] = find(b)
    groups: dict[str, list[str]] = {}
    for p in ctx.persons:
        groups.setdefault(find(p), []).append(p)
    return [g for g in groups.values() if len(g) >= 2]


def build_family(ctx: YearContext) -> Family:
    idx = IrIndex(ctx.ir)
    alive = frozenset(ctx.persons)
    deaths = {p: idx.death(p) for p in ctx.persons}
    departures = person_departures(ctx)
    cuts = {p: cut_date(deaths[p], departures[p]) for p in ctx.persons}
    related: dict[tuple[str, str], Kin] = {}
    for group in relation_groups(ctx, alive):
        for i, a in enumerate(group):
            for b in group[i + 1 :]:
                on = on_pair(cuts, ctx.year, a, b)
                k = kin_for(idx, a, b, on)
                r = kin_for(idx, b, a, on)
                if k.relative is not False or r.relative is not False:
                    related[(min(a, b), max(a, b))] = k if k.relative is not False else r
    neighbours: dict[str, list[str]] = {p: [] for p in ctx.persons}
    for a, b in related:
        neighbours[a].append(b)
        neighbours[b].append(a)
    lst = listings(ctx)
    candidates = spouse_candidates(ctx, idx, deaths, alive, cuts)
    slotted = judgeable_pairs(ctx, idx, cuts, related, lst, candidates)
    return Family(
        ctx, idx, alive, deaths, related, {p: tuple(sorted(v)) for p, v in neighbours.items()}, slotted, lst, candidates, cuts=cuts, departures=departures
    )


def person_departures(ctx: Any) -> dict[str, _dt.date | None]:
    """人 → その年の中途の出国の日（ir_facts.departure_day。PD-05）。ctx は ir・year・persons を持つ窓口（YearContext・CheckContext）。"""
    judgments = [j for j in heads(ctx.ir["judgments"]) if j["kind"] == J_ADDRESS]
    notices = [r for r in ctx.ir["facts"] if r["kind"] == "tax_agent_notice"]
    return {p: departure_day(ctx.year, judgments, notices, p) for p in ctx.persons}


def on_pair(deaths: Mapping[str, _dt.date | None], year: int, a: str, b: str) -> _dt.date:
    end = _dt.date(year, 12, 31)
    for p in (a, b):
        d = deaths[p]
        if d is not None and d < end:
            end = d
    return end


def judgeable_pairs(
    ctx: YearContext,
    idx: IrIndex,
    deaths: Mapping[str, _dt.date | None],
    related: Mapping[tuple[str, str], Kin],
    lst: list[Listing],
    candidates: Mapping[str, list[Mapping[str, Any]]],
) -> frozenset[tuple[str, str]]:
    """判断.生計を一にする の1か所を置く親族の組。

    直系の血族（親子・祖父母と孫など）と法律婚の相手は常に置く。それ以外の親族（兄弟姉妹・おじおば・姻族など）は、組の判断の記録・同じ世帯の住民票・
    申告書等の記載のどれかがあるときだけ置く（未入力の判断は候補の全部で評価するが、組の数が増えると候補の直積が上限を超えて、関係のない値まで未確定になるため。
    材料のない親族の組は「扶養親族等の候補にしない」＝判断.生計を一にする を入力すれば候補になる：README §4）。
    """
    judged = {(min(j["subject"]["person"], j["subject"]["other_person"]), max(j["subject"]["person"], j["subject"]["other_person"])) for j in ctx.judgments(J_SEIKEI)}
    listed = {(min(l.filer, l.person), max(l.filer, l.person)) for l in lst}
    spouses = {(min(a, other_spouse(m, a)), max(a, other_spouse(m, a))) for a, ms in candidates.items() for m in ms}
    out: set[tuple[str, str]] = set()
    for (a, b) in related:
        on = on_pair(deaths, ctx.year, a, b)
        rel_ab = kin_for(idx, a, b, on)
        rel_ba = kin_for(idx, b, a, on)
        lineal = (rel_ab.kind == "血族" and (rel_ab.b_is_ascendant or rel_ab.b_is_child)) or (rel_ba.kind == "血族" and (rel_ba.b_is_ascendant or rel_ba.b_is_child))
        foster = rel_ab.kind in ("里子", "養護受託老人") or rel_ba.kind in ("里子", "養護受託老人")
        evidence = (a, b) in judged or (a, b) in listed or same_household(idx, a, b, on)
        if lineal or foster or (a, b) in spouses or evidence:
            out.add((a, b))
    return frozenset(out)


def same_household(idx: IrIndex, a: str, b: str, on: _dt.date) -> bool:
    ha = {r["attributes"]["household_id"] for r in idx.of("resident_record", a) if covers(r.get("when"), on)}
    return any(covers(r.get("when"), on) and r["attributes"]["household_id"] in ha for r in idx.of("resident_record", b))


def pair_match(a: str, b: str, on: _dt.date) -> Any:
    def match(rec: Mapping[str, Any]) -> bool:
        s = rec["subject"]
        return {s["person"], s["other_person"]} == {a, b} and covers(rec.get("when"), on)

    return match


def age_of(fam: Family, pid: str, on: _dt.date) -> int:
    from .kinship import age_on  # noqa: PLC0415

    return age_on(fam.ctx.birth_on(pid), on)


# ---------------------------------------------------------------------------
# 申告者になりうる人・居住者・生計（中間表現だけで決まるもの）
# ---------------------------------------------------------------------------


def potential_claimants(fam: Family, d: str) -> list[str]:
    """扶養親族等の申告者になりうる人（親族の組で、判断で生計が別と決まっていない人。配偶者を除く）。判断・選択を決める前に呼ぶ（中間表現だけを見る）。"""
    out: list[str] = []
    for c in fam.neighbours[d]:
        if not fam.judgeable(c, d):
            continue
        rel = fam.relation(c, d)
        if rel.relative is False or rel.kind == "配偶者":
            continue
        if known_not_living_together(fam, c, d):
            continue
        if c in employers_of(fam, d):  # d は c の事業専従者（所基通2−48）：c の扶養親族等にならない
            continue
        if known_non_resident(fam, c):  # 非居住者は扶養親族等を有する居住者にならない
            continue
        out.append(c)
    return out


def known_non_resident(fam: Family, c: str) -> bool:
    """判断.住所の所在 がすべて国外で、その年の1月1日から判定の時までを覆う（中間表現だけで居住者でないと決まる。inputs.py の居住者の入力と同じ読み）。"""
    year = fam.ctx.year
    t = judgment_date(year, fam.cut(c))
    js = [j for j in fam.ctx.judgments(J_ADDRESS) if j["subject"]["person"] == c and overlaps_year(j.get("when"), year)]
    if not js or any(j.get("value") != "foreign" for j in js):
        return False
    start = _dt.date(year, 1, 1)
    cur = start
    for a, b in sorted((date_of(w["from_on"]) if "from_on" in (w := j.get("when") or {}) else start, date_of(w["to_on"]) if w.get("to_on") else t) for j in js):
        if a > cur:
            return False
        cur = max(cur, b + _dt.timedelta(days=1))
    return cur > t


def known_not_living_together(fam: Family, a: str, b: str) -> bool:
    """判断.生計を一にする の記録で「生計を一にしない」と決まっている（判定の時を含む判断がすべて偽）。未入力・食い違いは決まっていない。"""
    on = fam.t(a, b)
    values = [r["value"] for r in fam.ctx.judgments(J_SEIKEI) if pair_match(a, b, on)(r)]
    return bool(values) and all(v is False for v in values)


def nonresident_income_splits(fam: Family) -> dict[str, tuple[Split, frozenset[str]]]:
    """非居住者の期間がある（判定の時までに住所が国外と判断された）所得の記録のある親族 d → (読みの分かれ目, d の申告者・配偶者になりうる人)。

    d の合計所得金額は読み (a) 国内源泉所得だけ・(b) 全世界の所得 で違いうる（impl-research3 H2）。(a) の値を出す語彙がないので、d を扶養親族等・配偶者として
    判定しうる人がいれば、関係の入力を未確定にする（決める手段は一次情報）。
    """
    out: dict[str, tuple[Split, frozenset[str]]] = {}
    year = fam.ctx.year
    for d in fam.ctx.persons:
        t = judgment_date(year, fam.cut(d))
        foreign = foreign_period_ids(fam.ctx.ir, d, year, t)
        if not foreign:
            continue
        income = income_record_ids(fam.ctx.ir, d, year)
        if not income:
            continue
        claimants = set(potential_claimants(fam, d)) | {other_spouse(m, d) for m in fam.spouse_candidates[d]}
        claimants = {c for c in claimants if not known_non_resident(fam, c)}
        if claimants and not no_non_domestic_income(fam, d):
            out[d] = (nonresident_income_split(d, (*foreign, *income)), frozenset(claimants))
    return out


def no_non_domestic_income(fam: Family, d: str) -> bool:
    """非居住者の期間の国内源泉所得以外の所得が0と判断されている（読み (a)・(b) で d の合計所得金額が同じ。impl-research3 H2）。

    印（予測など）のある判断は、分かれ目を外すと状態が伝わらないので使わない（安全側：分かれ目を残す）。
    """
    try:
        dec = fam.ctx.decision(K_DOMESTIC, d)
    except KeyError:
        return False
    return not dec.states and dec.value == 0


# ---------------------------------------------------------------------------
# 年の中途で死亡・出国した申告者のための見積り（所基通85−1(2)）
# ---------------------------------------------------------------------------


def dies_in_year(fam: Family, c: str) -> bool:
    """c がその年の中途（12月31日を含む）に死亡したか、出国したか（所基通85−1 の「年の中途において死亡し又は出国をした者」。出国は PD-05）。"""
    d = fam.deaths[c]
    return (d is not None and d.year == fam.ctx.year) or fam.departures.get(c) is not None


def estimate_key(d: str, c: str) -> str:
    return f"{d}:{c}"


def relative_value(fam: Family, ctx: StageContext, var: str, owner: str, d: str) -> StageValue:
    """owner から見た親族 d の合計所得金額（var）。owner が年の中途で死亡したときは、見積り.親族の合計所得金額 があればその額（状態「見積り」）。

    所基通85−1(2)：年の中途で死亡した者の親族の合計所得金額は、死亡の時の現況により見積もったその年1月1日から12月31日までの額。
    見積りがなければ実際の額を返す（checks.py が owner の親族に関する控除を対象外にする）。
    """
    v = ctx.value(var, d)
    if not dies_in_year(fam, owner):
        return v
    try:
        est = ctx.decision(K_EST, estimate_key(d, owner))
    except KeyError:
        return v
    return dataclasses.replace(v, value=int(est.value), states=v.states | est.states, facts=tuple(sorted(set(v.facts) | set(est.record_ids))))


# ---------------------------------------------------------------------------
# 事業専従者（所法2①三十三・三十四、所基通2−48）
# ---------------------------------------------------------------------------


def employers_of(fam: Family, person: str) -> set[str]:
    """person がその年分に専従者として従事・給与の支払を受けた事業主（届出・給与の支払・従事の記録があるもの）。

    青色事業専従者は給与の支払を受けることが要件（所法2①三十三）。白色の事業専従者（所法57③）は従事の記録（business_engagement）。
    届出だけで給与の支払がない人は当たらない（所法2①三十三「給与の支払を受けるもの」）。
    """
    year = fam.ctx.year
    out: set[str] = set()
    for r in fam.idx.of("payroll_paid", person):
        if r["roles"].get("recipient") == person and r["attributes"]["pay_type"] == "family_employee_salary" and overlaps_year(r.get("when"), year):
            out.add(r["roles"]["employer"])
    for r in fam.idx.of("business_engagement", person):
        if r["roles"]["relative"] == person and overlaps_year(r.get("when"), year):
            out.add(r["roles"]["business_owner"])
    return out


def is_senju(fam: Family, owner_side: str, person: str) -> bool:
    """person が owner_side 又は owner_side と生計を一にする居住者の青色事業専従者等か（所基通2−48）。"""
    for e in employers_of(fam, person):
        if e == owner_side or (e in fam.alive and fam.live_true(owner_side, e)):
            return True
    return False


__all__ = [
    "C_ATTR",
    "C_SPOUSE",
    "DEP_DOCUMENTS",
    "DEP_SECTIONS",
    "Family",
    "J_ADDRESS",
    "J_DOUKYO",
    "J_SEIKEI",
    "K_DOMESTIC",
    "K_EST",
    "Listing",
    "REMITTANCE_DOCUMENTS",
    "REMITTANCE_SPECIAL",
    "RETURN_DOCUMENTS",
    "SPOUSE_DOCUMENTS",
    "WITHHOLDING_DECLARATIONS",
    "build_family",
    "dies_in_year",
    "employers_of",
    "estimate_key",
    "is_senju",
    "kin_for",
    "listings",
    "nonresident_income_splits",
    "pair_key",
    "person_departures",
    "potential_claimants",
    "relative_value",
]

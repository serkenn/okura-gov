"""規則モジュール personal_deductions の situation への写し方と対象外の検出（中間表現 → 事実の層の入力変数）。

判定の時（ir_facts.judgment_date：その年12月31日・死亡の日）に有効な記録と判断を、事実の層の入力に写す。
法令の判定そのもの（障害者に当たるか・年齢など）は変数の式に置き、ここでは材料の取り出しと、材料が足りないときの対象外だけをする。

対象外（黙って近似しない）：
- その年分の中に国外へ移る日がある人（出国の年）：その人・年分の全部。国外転出時課税に当たらないことを確かめる入力が中間表現にない（D22 S11）。
- 住所が年分を通じて国外の人・年の途中に非居住者の期間がある人（入国の年。期間の重ならない国内・国外の判断）は、人の全部を止めない
  （2026-11-11）。その人自身の所得控除の額は非居住者本人の申告として範囲外（checks.py）、親族としての合計所得金額は読みの分かれ目（allocation.py）。
- 判定の時に続いている婚姻が2つ以上ある人（重婚の記録：所令220 の死亡と再婚は allocation.py が解く）。
- 配偶者の生死が明らかでない婚姻で、所令11 の各号に当たるかを決める欄（事由・危難が去った日）がない人（入力すれば決まる）。

未入力の判断（D21 R6）：
- 判断.住所の所在：国外の滞在があって判断がない（又は判断が食い違う）人は、候補を評価せずに対象外にする。国外の候補は対象外になるので、
  候補の全部で評価しても結論は対象外で変わらない（D21 R6）。判断がそろっている人だけに1か所（"<人>:<年分>"）を置いて値と由来を受ける。
- 判断.障害の程度：知的障害の判定・手帳の申請の記録があるか、判断がある人の、その側面だけに1か所（"<人>:<側面>"）。
- 判断.自己の勤労に基づく：判断があるか、業務の記録がある人だけに1か所（"<人>:<年分>"）。
材料の事実がない人に分かれ目を作らない（作ると家族の全員に候補の直積が増え、上限を超える）。
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable, Mapping
from typing import Any

from ...candidates import Candidate
from ...registry import DecisionSlot, DecisionSpec, ModuleInputs, RecordKind, YearContext, overlaps_year
from ...basis import BasisEntry, BasisType, ReadingFlag, SourceKind
from ...result import Means, OutOfScopeCategory, OutOfScopeReason, Split, State
from .allocation import DECISIONS as ALLOCATION_DECISIONS, SPOUSE_DOCUMENTS
from .cohab_fx import DECISIONS as COHAB_FX_DECISIONS
from . import jan1
from .facts import NOT_DEAD
from .ir_facts import (
    DOMESTIC,
    FOREIGN,
    IrIndex,
    cut_date,
    departure_day,
    application_special,
    certificate_grade,
    course_student,
    cohabitation,
    covers,
    date_of,
    disability_bases,
    ended_marriages,
    enrollments,
    interval_in_year,
    missing_spouses,
    judgment_date,
    other_party,
    union_covers,
    war_special,
)

#: このモジュールが使う記録の種類（registry の record_kinds）。
RECORD_KINDS = frozenset(
    {
        "abroad_stay",
        "disability_basis",
        "enrollment",
        "marriage",
        "resident_record",
        "legal_sex",
        "parentage",
        "adoption",
        "foster_placement",
        "payroll_paid",
        "business_engagement",
        "foreign_kin_document",
        "remittance",
        "withholding_slip",
        "institution_stay",  # 同居老親等の老人ホーム等（cohab_fx.py。2026-11-12）
        RecordKind("filed_document", "document_type", frozenset(SPOUSE_DOCUMENTS)),
    }
)

K_ADDRESS = "判断.住所の所在"
K_DISABILITY = "判断.障害の程度"
K_LABOR = "判断.自己の勤労に基づく"

_BOOL = (Candidate(True, "true"), Candidate(False, "false"))
#: 判断.障害の程度 のうち、所得税の判定に使う側面。
ASPECT_LACKS_CAPACITY = "lacks_capacity"
ASPECT_SEVERE = "severe_intellectual_disability"
ASPECT_BEDRIDDEN = "bedridden_requiring_complex_care"
ASPECT_PENDING = "evidently_disabled_pending_application"
#: 判断を要する側面と、判断が未入力でも分かれ目にする材料の記録の根拠（disability_basis の basis）。None は材料の記録がない側面。
ASPECT_TRIGGERS: Mapping[str, str | None] = {
    ASPECT_LACKS_CAPACITY: None,
    ASPECT_SEVERE: "intellectual_disability_assessment",
    ASPECT_BEDRIDDEN: None,
    ASPECT_PENDING: "application",
}
#: 判断.自己の勤労に基づく の分かれ目を作る、業務の記録の種類。
LABOR_TRIGGER_KINDS = ("business", "business_receipt")

NON_RESIDENT_REASON = (
    "この年分の判定の時に住所が国外と判断され、年の途中に居住者の期間がある（出国の年）。居住者の判定は判断.住所の所在（D4）による"
)
EMIGRATION_NOTE = (
    "。この年分の中に国外へ移る日がある。納税管理人の届出の後に移った（所法2①四十二の「出国」に当たらない）なら、年末は非居住者で、"
    "居住者の期間と非居住者の期間がある年分の計算（所法102・165）は非居住者本人の申告として範囲外（D20）。届出なしの出国の年は出国の時で判定する（PD-05）"
)
#: 出国の年の国外転出時課税（PD-05、2026-11-12 に語彙を足した）。
K_EXIT_TAX = "判断.国外転出時課税の対象"
EXIT_TAX_REASON = "出国の年に国外転出時課税（所得税法第60条の2 など）の対象になると判断された。国外転出時課税は範囲外（HANDOFF D22 S11）"
EMIGRATION_RULE = BasisEntry(
    type=BasisType.RULE,
    name="年の中途の出国（納税管理人の届出なし）：判定の時は出国の時（国外へ移る日の前日の現況）で、その時は居住者",
    source_kind=SourceKind.LAW,
    law="所得税法第2条第1項第42号・第85条第1項・第3項（「その死亡又は出国の時」）、所得税基本通達85−1。出国の時の現況を国外へ移る日の前日の現況と読む（法令の読み）",
    references=("docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.3", "docs/public-sources/20261109_R3-tsutatsu_nta.md#1.6"),
    flags=(ReadingFlag.LEGAL_READING,),
)
UNDECIDED_ADDRESS_REASON = (
    "国外の滞在があるが、判断.住所の所在（D4）が未入力か、食い違っている。居住者か（所得税法第2条第1項第3号）を決められない。"
    "住所が国外なら、非居住者の期間がある年分の計算と非居住者本人の申告は未実装・範囲外（D20、SH8）で、どちらの候補でも値を出せない。"
    "滞在の期間の全部について住所が国内と判断するなら、判断.住所の所在を入力すれば計算する"
)
ADDRESS_COVERAGE_REASON = (
    "判断.住所の所在 の期間が、国外の滞在の期間（又はその年の1月1日から判定の時まで）の全部を覆っていない。覆っていない期間は居住者か判定できない"
    "（所得税法第2条第1項第3号）。覆っていない期間の 判断.住所の所在 を入力すれば決まる"
)
REMARRIAGE_REASON = "判定の時に続いている婚姻が2つ以上ある（記録の矛盾）。配偶者を決められない。婚姻の記録の期間（to_on）・終了の理由（ended_by）を直せば決まる"
SPOUSE_MISSING_REASON = (
    "配偶者の生死が明らかでない記録があるが、政令で定める者（所得税法施行令第11条の各号）に当たるかを決める欄がない。次を入力すれば決まる"
)

V_BIRTH = "所得税_生年月日"
V_DEATH = "所得税_死亡日"
V_ADDRESS = "所得税_判定の時に住所が国内にあるか"
V_STUDY = "所得税_留学により国内に住所及び居所を有しなくなった者か"
V_PHYSICAL = "所得税_身体障害者手帳の障害の程度の級"
V_MENTAL = "所得税_精神障害者保健福祉手帳の障害等級"
V_INTELLECTUAL = "所得税_知的障害者と判定されているか"
V_SEVERE = "所得税_重度の知的障害者と判定されているか"
V_LACKS = "所得税_事理を弁識する能力を欠く常況にあるか"
V_WAR = "所得税_戦傷病者手帳の交付を受けているか"
V_ATOMIC = "所得税_原子爆弾被爆者の認定を受けているか"
V_BEDRIDDEN = "所得税_常に就床を要し複雑な介護を要するか"
V_MUNICIPAL = "所得税_市町村長等の障害者の認定を受けているか"
V_PENDING = "所得税_手帳の申請中で障害が明らかか"
V_ARTICLE1 = "所得税_学校教育法第1条の学校の学生等か"
V_COURSE = "所得税_政令で定める課程を履修する専修学校等の学生等か"
V_WAR_SPECIAL = "所得税_戦傷病者手帳に特別項症から第三項症までと記載されているか"
V_MUNICIPAL_SPECIAL = "所得税_市町村長等の特別障害者に準ずる認定を受けているか"
V_PENDING_SPECIAL = "所得税_申請中の障害の程度が特別障害者の程度か"
V_MARRIED = "所得税_判定の時に婚姻をしているか"
V_MISSING = "所得税_配偶者の生死が明らかでない者か"
V_COHAB = "所得税_住民票に事実婚の続柄の記載がある相手がいるか"
V_LABOR = "所得税_事業所得等が自己の勤労に基づくか"
V_DIVORCED = "所得税_夫と離婚した後婚姻をしていない者か"
V_WIDOWED = "所得税_夫と死別した後婚姻をしていない者又は夫の生死の明らかでない者か"


def _not_implemented(reason: str, ids: Iterable[str] = ()) -> OutOfScopeReason:
    return OutOfScopeReason(OutOfScopeCategory.NOT_IMPLEMENTED, reason, tuple(sorted(set(ids))))


def _marks(records: Iterable[Mapping[str, Any]]) -> frozenset[State]:
    return frozenset(State.from_mark(r["mark"]) for r in records if "mark" in r)


class _Source:
    """1回の呼び出しで使う索引（記録と判断を人で引く）。"""

    def __init__(self, ctx: YearContext) -> None:
        self.ctx = ctx
        self.idx = IrIndex(ctx.ir)
        self.address: dict[str, list[Mapping[str, Any]]] = {}
        self.aspects: dict[str, list[Mapping[str, Any]]] = {}
        self.labor: dict[str, list[Mapping[str, Any]]] = {}
        for kind, target, in_year in ((K_ADDRESS, self.address, True), (K_DISABILITY, self.aspects, False), (K_LABOR, self.labor, True)):
            for j in sorted(ctx.judgments(kind), key=lambda r: r["id"]):
                if not in_year or overlaps_year(j.get("when"), ctx.year):
                    target.setdefault(j["subject"]["person"], []).append(j)
        self._departures: dict[str, _dt.date | None] | None = None
        self.resident_by_household: dict[str, list[Mapping[str, Any]]] = {}
        for r in self.idx.of_kind("resident_record"):
            self.resident_by_household.setdefault(r["attributes"]["household_id"], []).append(r)

    def departure(self, pid: str) -> _dt.date | None:
        """その年の中途の出国の日（所法2①四十二。ir_facts.departure_day）。"""
        if self._departures is None:
            notices = self.ctx.records("tax_agent_notice")
            self._departures = {p: departure_day(self.ctx.year, self.address.get(p, []), notices, p) for p in self.ctx.persons}
        return self._departures.get(pid)

    def t(self, pid: str) -> _dt.date:
        """判定の時：その年12月31日。年の中途の死亡・出国はその時（所法85①③。出国は国外へ移る日の前日の現況：ir_facts.cut_date）。"""
        return judgment_date(self.ctx.year, cut_date(self.idx.death(pid), self.departure(pid)))

    def stays(self, pid: str) -> list[Mapping[str, Any]]:
        return [r for r in self.idx.of("abroad_stay", pid) if overlaps_year(r.get("when"), self.ctx.year)]

    def aspect_judgments(self, pid: str, aspect: str, t: _dt.date) -> list[Mapping[str, Any]]:
        return [j for j in self.aspects.get(pid, []) if j["value"]["aspect"] == aspect and covers(j.get("when"), t)]

    def aspect_needed(self, pid: str, aspect: str, t: _dt.date) -> bool:
        if self.aspect_judgments(pid, aspect, t):
            return True
        trigger = ASPECT_TRIGGERS[aspect]
        return trigger is not None and any(r["attributes"]["basis"] == trigger for r in disability_bases(self.idx, pid, t))

    def labor_needed(self, pid: str) -> bool:
        if self.labor.get(pid):
            return True
        return any(overlaps_year(r.get("when"), self.ctx.year) for kind in LABOR_TRIGGER_KINDS for r in self.idx.of(kind, pid))


# ---------------------------------------------------------------------------
# 判断・選択の1か所
# ---------------------------------------------------------------------------


def _year_key(ctx: YearContext, pid: str) -> str:
    return f"{pid}:{ctx.year}"


def _aspect_key(pid: str, aspect: str) -> str:
    return f"{pid}:{aspect}"


def _unanimous(judgments: list[Mapping[str, Any]]) -> bool:
    return bool(judgments) and len({j["value"] for j in judgments}) == 1


def _address_slots(ctx: YearContext) -> Iterable[DecisionSlot]:
    src = _Source(ctx)
    for pid in ctx.persons:
        if not _unanimous(src.address.get(pid, [])):
            continue
        yield DecisionSlot(
            key=_year_key(ctx, pid),
            target={"person": pid, "tax_year": ctx.year, "abroad_stay_ids": [r["id"] for r in src.stays(pid)]},
            matches=lambda j, p=pid: j["subject"]["person"] == p,
        )


def _disability_slots(ctx: YearContext) -> Iterable[DecisionSlot]:
    src = _Source(ctx)
    for pid in ctx.persons:
        t = src.t(pid)
        for aspect in ASPECT_TRIGGERS:
            if not src.aspect_needed(pid, aspect, t):
                continue
            yield DecisionSlot(
                key=_aspect_key(pid, aspect),
                target={"person": pid, "tax_year": ctx.year, "aspect": aspect},
                matches=lambda j, p=pid, a=aspect, d=t: (
                    j["subject"]["person"] == p and j["value"]["aspect"] == a and covers(j.get("when"), d)
                ),
                candidates=_BOOL,
            )


def _labor_slots(ctx: YearContext) -> Iterable[DecisionSlot]:
    src = _Source(ctx)
    for pid in ctx.persons:
        if src.labor_needed(pid):
            yield DecisionSlot(
                key=_year_key(ctx, pid),
                target={"person": pid, "tax_year": ctx.year},
                matches=lambda j, p=pid: j["subject"]["person"] == p,
            )


DECISIONS: tuple[DecisionSpec, ...] = (
    DecisionSpec(K_ADDRESS, _address_slots),
    DecisionSpec(K_DISABILITY, _disability_slots, value_of=lambda rec: rec["value"]["applies"]),
    DecisionSpec(K_LABOR, _labor_slots),
    # 判断.国外転出時課税の対象：1か所を置かず _write_emigrant が直接読む（未入力は分かれ目〔判断〕）。種類を「使う判断」として登録する宣言
    DecisionSpec(K_EXIT_TAX, lambda ctx: ()),
    *ALLOCATION_DECISIONS,
    *COHAB_FX_DECISIONS,  # 判断.老人ホーム等・選択.円換算の方法（2026-11-12。cohab_fx.py）
)


# ---------------------------------------------------------------------------
# 入力の組み立て
# ---------------------------------------------------------------------------


def _write_birth_and_death(src: _Source, pid: str, out: ModuleInputs) -> None:
    birth = src.ctx.birth_on(pid)
    death = src.idx.death(pid)
    out.set(V_BIRTH, pid, birth)
    out.set(V_DEATH, pid, death if death is not None else NOT_DEAD)


def _emigrates_in_year(year: int, stays: list[Mapping[str, Any]], judgments: list[Mapping[str, Any]]) -> bool:
    """その年分の中に国外へ移る日があるか（年の初めより後に始まる国外の滞在・国外の住所の判断）。"""
    jan1 = _dt.date(year, 1, 1)
    starts = [date_of(r["when"]["from_on"]) for r in stays]
    starts += [date_of(j["when"]["from_on"]) for j in judgments if j.get("value") == FOREIGN and "from_on" in (j.get("when") or {})]
    return any(jan1 < s and s.year == year for s in starts)


def _consistent(judgments: list[Mapping[str, Any]], year: int, t: _dt.date) -> bool:
    """判断.住所の所在 の期間どうしで、違う値の判断が重ならない（年の途中で住所が変わった記録として読める）か。"""
    spans = [(iv, j.get("value")) for j in judgments if (iv := interval_in_year(j.get("when"), year, t)) is not None]
    for i, (a, va) in enumerate(spans):
        for b, vb in spans[i + 1 :]:
            if va != vb and a[0] <= b[1] and b[0] <= a[1]:
                return False
    return True


def _write_residence(src: _Source, pid: str, t: _dt.date, out: ModuleInputs) -> bool:
    """判定の時に住所が国内にあるかを書く。戻り値は国外と判断された（非居住者として扱う）か。

    年の途中に非居住者の期間がある人（入国の年）は、判定の時の住所で居住者かを決める。その人自身の申告（非居住者の期間の計算：所法102・165）は
    範囲外（D20）として checks.py が所得控除の額を止め、親族としての合計所得金額は allocation.py が読みの分かれ目にする（impl-research3 H2）。
    """
    ctx = src.ctx
    stays = src.stays(pid)
    judgments = src.address.get(pid, [])
    if src.departure(pid) is not None:
        return _write_emigrant(src, pid, t, out, stays, judgments)
    if not stays and not judgments:
        out.set(V_ADDRESS, pid, True)
        out.set(V_STUDY, pid, False)
        return False
    ids = tuple(r["id"] for r in [*stays, *judgments])
    states = _marks([*stays, *judgments])
    if not _unanimous(judgments):
        at = [j for j in judgments if covers(j.get("when"), t)]
        if judgments and _consistent(judgments, ctx.year, t) and at:
            return _write_changed_residence(src, pid, t, out, stays, judgments, at[0].get("value"), ids, states)
        reason = UNDECIDED_ADDRESS_REASON + (EMIGRATION_NOTE if _emigrates_in_year(ctx.year, stays, judgments) else "")
        out.exclude(pid, _not_implemented(reason, ids))
        out.set(V_ADDRESS, pid, False, ids, states)
        out.set(V_STUDY, pid, False, ids)
        return False
    decided = ctx.decision(K_ADDRESS, _year_key(ctx, pid))
    ids = tuple(r["id"] for r in stays) + decided.record_ids
    states = _marks(stays) | decided.states
    if decided.value == DOMESTIC:
        intervals = [iv for j in judgments if (iv := interval_in_year(j.get("when"), ctx.year, t)) is not None]
        for stay in stays:
            target = interval_in_year(stay.get("when"), ctx.year, t)
            if target is not None and not union_covers(intervals, target):
                out.exclude(pid, _not_implemented(ADDRESS_COVERAGE_REASON, ids))
                break
        out.set(V_ADDRESS, pid, True, ids, states)
        out.set(V_STUDY, pid, False, ids, states)
        return False
    # 住所が国外の判断：この年分に非居住者の期間がある
    emigrates = _emigrates_in_year(ctx.year, stays, judgments)
    if emigrates:  # 納税管理人の届出の後に国外へ移った：範囲外（所法102・165。届出なしの出国は _write_emigrant）
        out.exclude(pid, OutOfScopeReason(OutOfScopeCategory.OUT_OF_RANGE, NON_RESIDENT_REASON + EMIGRATION_NOTE, tuple(sorted(set(ids)))))
    elif not _foreign_whole_year(ctx.year, judgments, t):
        out.exclude(pid, _not_implemented(ADDRESS_COVERAGE_REASON, ids))
    out.set(V_ADDRESS, pid, False, ids, states)
    study = any(r["attributes"]["purpose"] == "study" and covers(r.get("when"), t) for r in stays)
    out.set(V_STUDY, pid, study, ids, states)
    return True


def _write_emigrant(src: _Source, pid: str, t: _dt.date, out: ModuleInputs, stays: list, judgments: list) -> bool:
    """その年の中途に出国する人（所法2①四十二。PD-05、2026-11-12）。判定の時（出国の時：t は国外へ移る日の前日）は居住者。

    国外転出時課税（所得税法第60条の2 など。範囲外：D22 S11）に当たらないことを 判断.国外転出時課税の対象 で確かめる：
    true なら範囲外、false なら計算、未入力・食い違いなら居住者かの入力に分かれ目（決める手段：判断）を付けて未確定にする。
    """
    ctx = src.ctx
    exit_js = [j for j in ctx.judgments(K_EXIT_TAX) if j["subject"]["person"] == pid and overlaps_year(j.get("when"), ctx.year)]
    ids = tuple(r["id"] for r in [*stays, *judgments, *exit_js])
    states = _marks([*stays, *judgments, *exit_js])
    intervals = [iv for j in judgments if j.get("value") == DOMESTIC and (iv := interval_in_year(j.get("when"), ctx.year, t)) is not None]
    for stay in stays:
        target = interval_in_year(stay.get("when"), ctx.year, t)
        if target is not None and not union_covers(intervals, target):
            out.exclude(pid, _not_implemented(ADDRESS_COVERAGE_REASON, ids))
            break
    values = {bool(j["value"]) for j in exit_js}
    missing = []
    if values == {True}:
        out.exclude(pid, OutOfScopeReason(OutOfScopeCategory.OUT_OF_RANGE, EXIT_TAX_REASON, ids))
    elif values != {False}:
        missing.append(exit_tax_split(pid, ctx.year, [j["id"] for j in exit_js]))
    out.set(V_ADDRESS, pid, True, ids, states, missing=missing, basis=[EMIGRATION_RULE])
    out.set(V_STUDY, pid, False, ids, states)
    return False


def exit_tax_split(pid: str, year: int, ids: list[str]) -> Split:
    """出国の年に国外転出時課税の対象になるかが入力されていない（又は食い違う）：決める手段は判断（判断.国外転出時課税の対象）。"""
    return Split(
        id=f"判断:国外転出時課税の対象:{pid}:{year}",
        means=Means.JUDGMENT,
        target={"person": pid, "tax_year": year, "記録": sorted(ids), "決めるもの": f"{K_EXIT_TAX}（false なら計算する。true は範囲外：D22 S11）"},
        candidates=("対象にならない", "対象になる（範囲外）"),
        splits_conclusion=True,
    )


def _write_changed_residence(
    src: _Source, pid: str, t: _dt.date, out: ModuleInputs, stays: list, judgments: list, value: Any, ids: tuple[str, ...], states: frozenset[State]
) -> bool:
    """年の途中で住所の所在が変わった（期間の重ならない国内・国外の判断がある）人。判定の時の判断の値で居住者かを決める。"""
    ctx = src.ctx
    intervals = [iv for j in judgments if (iv := interval_in_year(j.get("when"), ctx.year, t)) is not None]
    for stay in stays:
        target = interval_in_year(stay.get("when"), ctx.year, t)
        if target is not None and not union_covers(intervals, target):
            out.exclude(pid, _not_implemented(ADDRESS_COVERAGE_REASON, ids))
            break
    if value == FOREIGN:  # 年の途中で納税管理人の届出の後に国外へ移った（届出なしの出国は _write_emigrant）：非居住者の期間の計算は範囲外
        out.exclude(pid, OutOfScopeReason(OutOfScopeCategory.OUT_OF_RANGE, NON_RESIDENT_REASON + EMIGRATION_NOTE, tuple(sorted(set(ids)))))
        out.set(V_ADDRESS, pid, False, ids, states)
        study = any(r["attributes"]["purpose"] == "study" and covers(r.get("when"), t) for r in stays)
        out.set(V_STUDY, pid, study, ids, states)
        return True
    out.set(V_ADDRESS, pid, True, ids, states)
    out.set(V_STUDY, pid, False, ids, states)
    return False


def _foreign_whole_year(year: int, judgments: list[Mapping[str, Any]], t: _dt.date) -> bool:
    """判断.住所の所在（国外）の期間が、その年1月1日から判定の時までを覆うか（年の途中で国外へ移った人は、その年分に居住者の期間がある）。"""
    intervals = [iv for j in judgments if j.get("value") == FOREIGN and (iv := interval_in_year(j.get("when"), year, t)) is not None]
    return union_covers(intervals, (_dt.date(year, 1, 1), t))


def _write_disability(src: _Source, pid: str, t: _dt.date, out: ModuleInputs) -> None:
    bases = disability_bases(src.idx, pid, t)
    for var, basis in ((V_PHYSICAL, "physical_disability_certificate"), (V_MENTAL, "mental_disability_certificate")):
        grade, ids = certificate_grade(bases, basis)
        out.set(var, pid, grade, ids, _marks(r for r in bases if r["id"] in ids))
    for var, basis in (
        (V_INTELLECTUAL, "intellectual_disability_assessment"),
        (V_WAR, "war_injury_certificate"),
        (V_ATOMIC, "atomic_bomb_survivor_certification"),
        (V_MUNICIPAL, "municipal_certification"),
    ):
        hits = [r for r in bases if r["attributes"]["basis"] == basis]
        out.set(var, pid, bool(hits), tuple(r["id"] for r in hits), _marks(hits))
    war = [r for r in bases if r["attributes"]["basis"] == "war_injury_certificate" and war_special(r) is True]
    out.set(V_WAR_SPECIAL, pid, bool(war), tuple(r["id"] for r in war), _marks(war))
    muni = [r for r in bases if r["attributes"]["basis"] == "municipal_certification" and r["attributes"].get("certified_severity") == "severe"]
    out.set(V_MUNICIPAL_SPECIAL, pid, bool(muni), tuple(r["id"] for r in muni), _marks(muni))
    physical_max = int(src.ctx.parameters.所得税.特別障害者.身体障害者手帳の級の上限)
    app = [r for r in bases if r["attributes"]["basis"] == "application" and application_special(r, physical_max) is True]
    out.set(V_PENDING_SPECIAL, pid, bool(app), tuple(r["id"] for r in app), _marks(app))
    for var, aspect in (
        (V_SEVERE, ASPECT_SEVERE),
        (V_LACKS, ASPECT_LACKS_CAPACITY),
        (V_BEDRIDDEN, ASPECT_BEDRIDDEN),
        (V_PENDING, ASPECT_PENDING),
    ):
        if src.aspect_needed(pid, aspect, t):
            d = src.ctx.decision(K_DISABILITY, _aspect_key(pid, aspect))
            out.set(var, pid, bool(d.value), d.record_ids, d.states)
        else:
            out.set(var, pid, False)


def _write_school(src: _Source, pid: str, t: _dt.date, out: ModuleInputs) -> None:
    now = enrollments(src.idx, pid, t)
    hits = [r for r in now if r["attributes"]["school_type"] == "school_act_article1"]
    out.set(V_ARTICLE1, pid, bool(hits), tuple(r["id"] for r in hits), _marks(hits))
    courses = [r for r in now if course_student(r)[0] is True]
    out.set(V_COURSE, pid, bool(courses), tuple(r["id"] for r in courses), _marks(courses))


def _write_marriage(src: _Source, pid: str, t: _dt.date, out: ModuleInputs) -> None:
    mine = src.idx.of("marriage", pid)
    active = []
    for r in mine:
        other_death = src.idx.death(other_party(r, pid))
        if covers(r.get("when"), t) and (other_death is None or other_death >= t):
            active.append(r)
    if len(active) >= 2:
        out.exclude(pid, _not_implemented(REMARRIAGE_REASON, tuple(r["id"] for r in active)), V_MARRIED)
    out.set(V_MARRIED, pid, bool(active), tuple(r["id"] for r in active), _marks(active))
    # 寡婦の「夫」（所法2①三十）：相手の法令上の性別（legal_sex）が male の婚姻。female の婚姻は当たらない。
    # 性別の記録がない婚姻は当たりうるものとして入力し、寡婦に当たると判定されたときだけ checks.py が対象外にする（性別は要件を狭める向きにだけ効く）
    ended = [e for e in ended_marriages(src.idx, pid, t) if e.husband is not False]
    # 配偶者の生死が明らかでない者（所令11・11の2①）：判定の時に続いている婚姻の spouse_missing を所令11 の各号で判定する
    missing = missing_spouses(src.idx, pid, t)
    hit_missing = [m for m in missing if m.applies is True]
    unknown = [m for m in missing if m.applies is None]
    for var, divorced in ((V_DIVORCED, True), (V_WIDOWED, False)):
        hits = [e for e in ended if e.divorced is divorced]
        recs = [e.record for e in hits]
        ids = tuple(r["id"] for r in recs) + tuple(i for e in hits for i in e.sex_ids)
        if var == V_WIDOWED:  # 寡婦のロ「夫の生死の明らかでない者で政令で定めるもの」（相手の性別がない婚姻は checks.py が止める）
            husbands = [m for m in hit_missing if m.husband is not False]
            recs += [m.record for m in husbands]
            ids += tuple(m.record["id"] for m in husbands) + tuple(i for m in husbands for i in m.sex_ids)
            hits = [*hits, *husbands]
        out.set(var, pid, bool(hits), ids, _marks(recs))
    ids = tuple(m.record["id"] for m in missing)
    if unknown and not hit_missing:
        reason = SPOUSE_MISSING_REASON + "：" + "・".join(sorted({m.needs for m in unknown}))
        for var in (V_MISSING, V_WIDOWED):
            out.exclude(pid, _not_implemented(reason, ids), var)
    out.set(V_MISSING, pid, bool(hit_missing), ids, _marks(m.record for m in missing))


def _write_cohabitation(src: _Source, pid: str, t: _dt.date, out: ModuleInputs) -> None:
    """住民票に事実婚の続柄の記載がある相手がいるか。記載を確かめられない人（住民票の記録がない・続柄の記載がない）の対象外は、
    寡婦・ひとり親に当たると判定された人だけに checks.py が付ける（記載は要件を狭める向きにだけ効くので、当たらない人は記載によらず当たらない）。"""
    c = cohabitation(src.idx, pid, t)
    out.set(V_COHAB, pid, c.found, c.ids, _marks(c.records))


def _write_labor(src: _Source, pid: str, out: ModuleInputs) -> None:
    if not src.labor_needed(pid):
        out.set(V_LABOR, pid, False)
        return
    d = src.ctx.decision(K_LABOR, _year_key(src.ctx, pid))
    out.set(V_LABOR, pid, d.value == "based", d.record_ids, d.states)


def build_inputs(ctx: YearContext) -> ModuleInputs:
    out = ModuleInputs()
    src = _Source(ctx)
    for pid in ctx.persons:
        t = src.t(pid)
        _write_birth_and_death(src, pid, out)
        _write_residence(src, pid, t, out)
        _write_disability(src, pid, t, out)
        _write_school(src, pid, t, out)
        _write_marriage(src, pid, t, out)
        _write_cohabitation(src, pid, t, out)
        _write_labor(src, pid, out)
    jan1.write(ctx, out, src.aspect_judgments)  # 住民税への窓口：翌年の1月1日の障害者・婚姻の現況（JM-03）
    return out

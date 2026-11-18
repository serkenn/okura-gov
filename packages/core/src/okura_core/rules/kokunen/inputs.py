"""規則モジュール kokunen の入力の組み立て：第3号被保険者の判定日の事実、判断の1か所、免除の世帯主・配偶者の所得の審査（段階評価）。

- 判定日 D（第3号）：ctx.window("国年", "判定日").judgment_on。D の属する暦年の situation で計算する。
- 年度 F（免除等）：ctx.window("国年", "年度")。世帯主・配偶者は免除等の期間の初日（F年7月1日）の住民票の世帯・婚姻で決める
  （審査の対象の時点は docs で未確認。期間の初日を使う：README §4）。
- 配偶者は事実上婚姻関係と同様の事情にある者を含む（国民年金法第5条第7項）。婚姻の届出の記録か 判断.事実婚。住民票に「未届の配偶者」の
  続柄がある組で判断がなければ、判断の候補の全部で評価する（D21 R6）。証拠のない組は事実婚としない。
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from ...basis import BasisEntry, BasisType, ReadingFlag, SourceKind
from ...candidates import Candidate
from ...registry import (
    DecisionSlot,
    DecisionSpec,
    ModuleInputs,
    StageContext,
    StageOutput,
    StageSpec,
    YearContext,
)
from ...result import Means, Split, State
from .calc import (
    LaborContract,
    chain_addition,
    SpouseSupport,
    age_on,
    contract_annual_income,
    meets_full,
    needs_overall_judgment,
    partial_tier_with_status,
    stricter,
    PartialRules,
    四分の三,
)
from .periods import (
    additional_premium_count,
    additional_premium_paid_count,
    childcare_count,
    exemption_months,
    fiscal_months,
    perinatal_count,
    student_months,
)

V_AGE = "年金_判定日の年齢"
V_SELF2 = "年金_本人が第2号被保険者か"
V_SP2 = "年金_配偶者が第2号被保険者か"
V_DOM = "年金_国内居住の要件を満たすか"
V_INC = "年金_被扶養配偶者の年間収入"
V_SPINC = "年金_第2号被保険者の年間収入"
V_SAME = "年金_第2号被保険者と同一の世帯に属するか"
V_AID = "年金_第2号被保険者からの援助による収入額"
V_HH_FULL = "年金_世帯主及び配偶者が全額免除の所得基準を満たすか"
V_SP_FULL = "年金_配偶者が全額免除の所得基準を満たすか"
V_HH_PART = "年金_世帯主及び配偶者が満たす一部免除の区分"
V_MENJO = "年金_免除判定所得"
V_FULL_THR = "年金_全額免除の所得基準額"
V_PART_INC = "年金_一部免除判定所得"
V_ADD = "年金_一部免除の加算額"
V_DISABLED = "所得税_障害者に当たるか"
V_WIDOW = "所得税_寡婦に当たるか"
V_SINGLE = "所得税_ひとり親に当たるか"
V_ST_EX = "年金_免除等の期間の学生等である月数"
V_ST_SP = "年金_学生納付特例の期間の学生等である月数"
V_PERI = "年金_産前産後の免除の月数"
V_CARE = "年金_育児期間の免除の月数"
V_FUKA = "年金_付加保険料を納付する者となることができる月数"
V_FUKA_PAID = "年金_付加保険料を納付する者である月数"
#: 2026-11-12（語彙の突き合わせ）：選択.国民年金の免除の申請（C-17）で申請する免除等の種類
V_APPLY = "年金_申請する免除等の種類"
FISCAL_INPUTS = (V_ST_EX, V_ST_SP, V_PERI, V_CARE, V_FUKA, V_FUKA_PAID)

K_FACTO = "判断.事実婚"
K_ABROAD5 = "判断.国内居住の例外第5号"
K_DEGREE = "判断.障害の程度"
K_INCOME = "見込み.年間収入"
K_INSURED_INCOME = "見込み.被保険者の年間収入"
K_AID = "見込み.援助額"
ASPECT = "pension_disability_level_for_health_insurance"
#: 国民年金法施行規則第1条の3 第1号〜第3号に当たる国外での滞在の目的（docs/public-sources/20261109_round2_spouse-laws-and-sources.md §5.1）。
ABROAD_EXCEPTIONS = {"study": "第1号（留学）", "accompanying_assignment": "第2号（赴任に同行）", "tourism": "第3号（観光・保養など一時的な渡航）"}
#: 労働契約の内容による判定を使う認定日（docs/public-sources/20261109_R3-tsutatsu_shakaihoken-juminzei.md §1.3：令和8年4月1日から）。
CONTRACT_FROM = _dt.date(2026, 4, 1)

STAGE = "国年の世帯主と配偶者の所得の審査"

_KN3 = "docs/public-sources/20261111_impl-research3_kokunen-laws.md"
#: 一部免除・学生納付特例・納付猶予の第2号「第九十条第一項第二号及び第三号に該当するとき」を、どちらかに当たればよいと読む
#: （docs/hypotheses/20261111_impl-research3_all-model.md H8 の読み(a)：日本年金機構の説明「地方税法に定める障害者、寡婦またはひとり親の場合、基準額が変わります」）。
ROUTE_135_BASIS = BasisEntry(
    BasisType.RULE,
    "国年の第90条第1項第3号の経路（135万円）",
    SourceKind.LAW,
    (f"{_KN3}#1",),
    flags=(ReadingFlag.LEGAL_READING,),
    law=(
        "国民年金法第90条の2第1項〜第3項の第2号・第90条の3第1項第2号・平成16年法律第104号附則第19条第2項第2号・平成26年法律第64号附則第14条第1項第2号"
        "（「第九十条第一項第二号及び第三号に該当するとき」をどちらかに当たればよいと読む。法令の読み＋日本年金機構の説明）、国年令第6条の7の2・第6条の8（135万円）"
    ),
)


def _d(s: str | None) -> _dt.date | None:
    return _dt.date.fromisoformat(s) if s else None


def _covers(when: Mapping[str, Any] | None, on: _dt.date) -> bool:
    if not when:
        return True
    if "on" in when:
        return _d(when["on"]) == on
    a, b = _d(when.get("from_on")), _d(when.get("to_on"))
    return (a is None or a <= on) and (b is None or on <= b)


def _states(recs: Iterable[Mapping[str, Any]]) -> set[State]:
    return {State.from_mark(r["mark"]) for r in recs if "mark" in r}


def _split(sid: str, means: Means, target: Mapping[str, Any]) -> Split:
    return Split(id=sid, means=means, target=dict(target), candidates=(), splits_conclusion=True)


# ---------------------------------------------------------------------------
# 配偶者（届出と事実婚）
# ---------------------------------------------------------------------------


def _resident(ctx: YearContext, pid: str, on: _dt.date) -> Mapping[str, Any] | None:
    for r in ctx.records("resident_record"):
        if r["roles"]["person"] == pid and _covers(r.get("when"), on):
            return r
    return None


def facto_pairs(ctx: YearContext, on: _dt.date) -> list[tuple[str, str]]:
    """事実婚の判断の1か所を置く組：住民票の未届の配偶者の続柄（世帯主との組）と、その日を含む 判断.事実婚 の記録の組。"""
    pairs: set[tuple[str, str]] = set()
    for p in ctx.persons:
        r = _resident(ctx, p, on)
        if r is None or r["attributes"].get("relation_to_householder") != "unregistered_spouse":
            continue
        hh = r["attributes"]["household_id"]
        for q in ctx.persons:
            rq = _resident(ctx, q, on)
            if q != p and rq is not None and rq["attributes"]["household_id"] == hh and rq["attributes"]["householder"]:
                pairs.add(tuple(sorted((p, q))))  # type: ignore[arg-type]
    alive = set(ctx.persons)
    for j in ctx.judgments(K_FACTO):
        s = j["subject"]
        a, b = s.get("person"), s.get("other_person")
        if a in alive and b in alive and _covers(j.get("when"), on):
            pairs.add(tuple(sorted((a, b))))  # type: ignore[arg-type]
    return sorted(pairs)


def _facto_key(a: str, b: str, on: _dt.date) -> str:
    return f"{a}:{b}:{on.isoformat()}"


@dataclass
class Spouses:
    persons: list[str] = field(default_factory=list)
    record_ids: list[str] = field(default_factory=list)
    states: set[State] = field(default_factory=set)


def spouses(ctx: YearContext, pid: str, on: _dt.date) -> Spouses:
    out = Spouses()
    for r in ctx.relations.spouses(pid, on):
        out.persons.append(r.other)
        out.record_ids.append(r.record_id)
        out.states |= set(r.states)
    for a, b in facto_pairs(ctx, on):
        if pid not in (a, b):
            continue
        other = b if pid == a else a
        dec = ctx.decision(K_FACTO, _facto_key(a, b, on))
        out.record_ids += list(dec.record_ids)
        out.states |= set(dec.states)
        if dec.value is True and other not in out.persons:
            out.persons.append(other)
    return out


def _dates(ctx: YearContext) -> list[_dt.date]:
    out = []
    w = ctx.window("国年", "判定日")
    if w is not None and w.judgment_on is not None:
        out.append(w.judgment_on)
    f = ctx.window("国年", "年度")
    if f is not None:
        out.append(f.date("免除等の期間の初日"))
    return out


def _facto_slots(ctx: YearContext) -> list[DecisionSlot]:
    out = []
    for on in _dates(ctx):
        for a, b in facto_pairs(ctx, on):
            out.append(
                DecisionSlot(
                    _facto_key(a, b, on),
                    {"person": a, "other_person": b, "on": on.isoformat()},
                    _match_pair(a, b, on),
                    persons=(a, b),
                )
            )
    return out


def _match_pair(a: str, b: str, on: _dt.date) -> Any:
    def m(rec: Mapping[str, Any]) -> bool:
        s = rec.get("subject", {})
        return {s.get("person"), s.get("other_person")} == {a, b} and _covers(rec.get("when"), on)

    return m


# ---------------------------------------------------------------------------
# 第3号被保険者の判定日の事実
# ---------------------------------------------------------------------------


def _member(ctx: YearContext, kind: str, pid: str, on: _dt.date) -> list[Mapping[str, Any]]:
    return [r for r in ctx.records(kind) if r["roles"]["member"] == pid and _covers(r.get("when"), on)]


def is_second(ctx: YearContext, pid: str, on: _dt.date) -> tuple[bool, list[Mapping[str, Any]]]:
    """第2号被保険者か（厚生年金保険の被保険者。65歳以上で老齢・退職の年金の受給権がある人を除く：国民年金法附則第3条）。"""
    ep = _member(ctx, "employees_pension", pid, on) + [
        r for r in _member(ctx, "national_pension", pid, on) if r["attributes"]["category"] == "second"
    ]
    if not ep:
        return False, []
    if age_on(ctx.birth_on(pid), on) >= 65:
        old = [r for r in _member(ctx, "pension_entitlement", pid, on) if r["attributes"]["benefit"] == "old_age"]
        if old:
            return False, ep + old
    return True, ep


def _abroad(ctx: YearContext, pid: str, on: _dt.date) -> list[Mapping[str, Any]]:
    return [r for r in ctx.records("abroad_stay") if r["roles"]["person"] == pid and _covers(r.get("when"), on)]


def _abroad5_slots(ctx: YearContext) -> list[DecisionSlot]:
    w = ctx.window("国年", "判定日")
    if w is None or w.judgment_on is None:
        return []
    on = w.judgment_on
    out = []
    for p in ctx.persons:
        if _resident(ctx, p, on) is not None:
            continue
        stays = _abroad(ctx, p, on)
        if stays and not any(s["attributes"]["purpose"] in ABROAD_EXCEPTIONS for s in stays):
            out.append(DecisionSlot(f"{p}:{on.isoformat()}", {"person": p, "on": on.isoformat()}, _match_one(p, on), persons=(p,)))
    return out


def _match_one(p: str, on: _dt.date) -> Any:
    def m(rec: Mapping[str, Any]) -> bool:
        return rec.get("subject", {}).get("person") == p and _covers(rec.get("when"), on)

    return m


def _disabled_evidence(ctx: YearContext, pid: str, on: _dt.date) -> list[Mapping[str, Any]]:
    basis = [r for r in ctx.records("disability_basis") if r["roles"]["person"] == pid and _covers(r.get("when"), on)]
    pens = [r for r in _member(ctx, "pension_entitlement", pid, on) if r["attributes"]["benefit"] == "disability"]
    return basis + pens


def degree_key(p: str, on: _dt.date) -> str:
    """判断.障害の程度（aspect＝pension_disability_level_for_health_insurance）の1か所の key。hifuyosha と同じ形にして、
    同じ1か所として1回だけ評価する（健保_障害を支給事由とする給付の受給要件に該当する程度の障害を有するか が読む）。"""
    return f"{p}:{on.isoformat()}"


def _degree_slots(ctx: YearContext) -> list[DecisionSlot]:
    """第3号の収入の基準（健保.配偶者の収入の基準額）が障害者の区分になるかの判断。障害の年金の受給権があれば判断は要らない
    （hifuyosha の事実の決め方と同じ）。第3号に当たりうる人（20歳以上60歳未満で配偶者が第2号）だけに置く。"""
    w = ctx.window("国年", "判定日")
    if w is None or w.judgment_on is None:
        return []
    on = w.judgment_on
    out = []
    for p in ctx.persons:
        if not _third_candidate(ctx, p, on):
            continue
        pens = [r for r in _member(ctx, "pension_entitlement", p, on) if r["attributes"]["benefit"] == "disability"]
        existing = [j for j in ctx.judgments(K_DEGREE) if _degree_match(p, on)(j)]
        if not pens and (existing or _disabled_evidence(ctx, p, on)):
            out.append(
                DecisionSlot(
                    degree_key(p, on),
                    {"person": p, "on": on.isoformat(), "aspect": ASPECT},
                    _degree_match(p, on),
                    candidates=(Candidate(True, "true"), Candidate(False, "false")),
                    year_filter=False,
                    persons=(p,),
                )
            )
    return out


def _third_candidate(ctx: YearContext, p: str, on: _dt.date) -> bool:
    age = age_on(ctx.birth_on(p), on)
    if not 20 <= age < 60 or is_second(ctx, p, on)[0]:
        return False
    # 宣言の段では判断.事実婚 の値はまだ決まっていないので、事実婚の判断の1か所を置く組の相手も配偶者になりうる人に含める
    possible = {r.other for r in ctx.relations.spouses(p, on)}
    possible |= {b if p == a else a for a, b in facto_pairs(ctx, on) if p in (a, b)}
    return any(is_second(ctx, q, on)[0] for q in possible)


def _degree_match(p: str, on: _dt.date) -> Any:
    def m(rec: Mapping[str, Any]) -> bool:
        v = rec.get("value")
        return (
            rec.get("subject", {}).get("person") == p
            and isinstance(v, Mapping)
            and v.get("aspect") == ASPECT
            and _covers(rec.get("when"), on)
        )

    return m


def _applies(value: Any) -> bool:
    """判断.障害の程度 の値（記録の value か、候補の真偽）。"""
    return bool(value["applies"]) if isinstance(value, Mapping) else bool(value)


# ---------------------------------------------------------------------------
# 選択.国民年金の免除の申請（C-17。年度）
# ---------------------------------------------------------------------------
# 全額免除・一部免除・学生納付特例・納付猶予は「…被保険者等から申請があつたとき」に限る（国年法第90条第1項・第90条の2第1項〜第3項・
# 第90条の3第1項、平成16年法律第104号附則第19条第2項、平成26年法律第64号附則第14条第1項：[PS3-KN] §1）。承認は npi_exemption（F-D09）。
# 産前産後の免除は申請ではなく法律上当然（第88条の2：[PS3-KN] §4）。選択は「申請する種類」の事実だけを入れ、承認されたものとはしない
# （付加保険料などの「納付することを要しないものとされている者」は承認の記録 npi_exemption で決める）。
# 選択がない人には1か所を置かない（申請する種類の所得の基準は、選択がなければ問われない。種類ごとの所得の基準は別の概念が全員に出す）。

K_APPLY = "選択.国民年金の免除の申請"
NO_CHOICE = "選択なし"
NOT_APPLY = "申請しない"
UNSPECIFIED = "種類の指定なし"
#: exemption_type（okura_ir.vocabulary.NPI_EXEMPTION_TYPE）→ 申請する免除等の種類の名前
APPLY_TYPES = {
    "full": "全額免除",
    "three_quarters": "4分の3免除",
    "half": "半額免除",
    "one_quarter": "4分の1免除",
    "payment_deferral": "納付猶予",
    "student_special": "学生納付特例",
    "perinatal": "産前産後",
}


def apply_key(p: str, fiscal_year: int) -> str:
    return f"{p}:FY{fiscal_year}"


def _apply_match(p: str, fiscal_year: int) -> Any:
    def m(rec: Mapping[str, Any]) -> bool:
        return rec.get("subject", {}).get("person") == p and (rec.get("when") or {}).get("fiscal_year") == fiscal_year

    return m


def _apply_slots(ctx: YearContext) -> list[DecisionSlot]:
    f = ctx.window("国年", "年度")
    if f is None:
        return []
    fy = int(f.time.value)
    chosen = ctx.choices(K_APPLY)
    return [
        DecisionSlot(apply_key(p, fy), {"person": p, "年度": fy}, _apply_match(p, fy), year_filter=False, persons=(p,))
        for p in ctx.persons
        if any(_apply_match(p, fy)(c) for c in chosen)
    ]


def apply_kind(value: Any) -> str:
    """選択の value（{apply, exemption_type?}）→ 申請する免除等の種類の名前。"""
    if not isinstance(value, Mapping) or not value.get("apply"):
        return NOT_APPLY
    t = value.get("exemption_type")
    return APPLY_TYPES[t] if t else UNSPECIFIED


DECISIONS = (
    DecisionSpec(K_FACTO, _facto_slots),
    DecisionSpec(K_ABROAD5, _abroad5_slots),
    DecisionSpec(K_DEGREE, _degree_slots),
    DecisionSpec(K_APPLY, _apply_slots),
)


def _judgment_on(ctx: YearContext, kind: str, on: _dt.date, **subject: str) -> list[Mapping[str, Any]]:
    return [
        j for j in ctx.judgments(kind)
        if j.get("when", {}).get("on") == on.isoformat() and all(j["subject"].get(k) == v for k, v in subject.items())
    ]


def _contract(ctx: YearContext, pid: str, on: _dt.date) -> tuple[int | None, list[str]]:
    """労働契約の内容による年間収入（令和8年4月1日以後の判定日だけ）。使えなければ None。"""
    if on < CONTRACT_FROM:
        return None, []
    for r in ctx.records("labor_contract"):
        if r["roles"]["worker"] != pid or not _covers(r.get("when"), on):
            continue
        a, am = r["attributes"], r.get("amounts", {})
        to_on = _d(r.get("when", {}).get("to_on"))
        long_enough = to_on is None or not a.get("fixed_term", False) or to_on >= _add_year(on) - _dt.timedelta(days=1)
        c = LaborContract(
            monthly_wage=am.get("monthly_wage"),
            monthly_allowances=int(am.get("monthly_allowances", 0)),
            monthly_commuting=am.get("monthly_commuting_allowance"),
            commuting_stated=bool(a.get("commuting_allowance_stated", False)),
            bonus=am.get("bonus"),
            bonus_stated=bool(a.get("bonus_stated", False)),
            notice=bool(a.get("labor_conditions_notice", False)),
            salary_only=bool(a.get("salary_income_only_statement", False)),
            shift_based=bool(a.get("shift_based", False)),
            long_enough=long_enough,
        )
        annual = contract_annual_income(c)
        if annual is not None:
            return annual, [r["id"]]
    return None, []


def _add_year(day: _dt.date) -> _dt.date:
    try:
        return day.replace(year=day.year + 1)
    except ValueError:
        return _dt.date(day.year + 1, 3, 1)


_DEFAULTS: dict[str, Any] = {
    V_AGE: 0,
    V_SELF2: False,
    V_SP2: False,
    V_DOM: False,
    V_INC: 0,
    V_SPINC: 0,
    V_SAME: False,
    V_AID: 0,
}


def _health(ctx: YearContext, on: _dt.date) -> Any:
    """健保の基準のパラメータ（hifuyosha の木）。入力の段では分かれ目を置くかの判定にだけ使い、判定の値は式が健保の概念から引く。"""
    return ctx.parameters_at(on).健保


def _limit(ctx: YearContext, p: str, on: _dt.date, age: int) -> int:
    """健保.配偶者の収入の基準額 と同じ区分の額（障害の年金の受給権か 判断.障害の程度 で 60歳以上又は障害者の区分）。"""
    pens = [r for r in _member(ctx, "pension_entitlement", p, on) if r["attributes"]["benefit"] == "disability"]
    disabled = bool(pens)
    if not pens:
        js = [j for j in ctx.judgments(K_DEGREE) if _degree_match(p, on)(j)]
        if js or _disabled_evidence(ctx, p, on):
            try:
                disabled = _applies(ctx.decision(K_DEGREE, degree_key(p, on)).value)
            except KeyError:  # 1か所を宣言していない人（第3号に当たりえない）：判断があればその値
                disabled = bool(js) and all(_applies(j["value"]) for j in js)
    h = _health(ctx, on)
    node = h.被扶養者の収入の基準額["健康保険"]
    senior = int(h.被扶養者の年齢の区分["60歳以上"])
    return int(node["60歳以上又は障害者"] if disabled or age >= senior else node["原則"])


def _half(ctx: YearContext, on: _dt.date) -> Fraction:
    """健保.同一の世帯の収入の割合 と同じ割合（分かれ目を置くかの判定にだけ使う）。"""
    r = _health(ctx, on).生計維持の比較.同一の世帯の収入の割合
    return Fraction(int(r.分子), int(r.分母))


def fiscal_inputs(ctx: YearContext, out: ModuleInputs) -> None:
    """年度 F の月ごとの事実（学生等である月・産前産後・育児期間・付加保険料。periods.py）。窓口がなければ 0。"""
    f = ctx.window("国年", "年度")
    if f is None:
        for q in ctx.persons:
            for v in FISCAL_INPUTS:
                out.set(v, q, 0)
            out.set(V_APPLY, q, NO_CHOICE)
        return
    fy = int(f.time.value)
    applying = {s.key for s in _apply_slots(ctx)}
    for p in ctx.persons:
        if apply_key(p, fy) in applying:
            dec = ctx.decision(K_APPLY, apply_key(p, fy))
            out.set(V_APPLY, p, apply_kind(dec.value), dec.record_ids, dec.states)
        else:
            out.set(V_APPLY, p, NO_CHOICE)
        for var, c in (
            (V_ST_EX, student_months(ctx, p, exemption_months(fy), "免除等の期間")),
            (V_ST_SP, student_months(ctx, p, fiscal_months(fy), "学生納付特例の期間")),
        ):
            out.set(var, p, c.value, c.record_ids, c.states, missing=c.missing)
        peri = perinatal_count(ctx, p, fy)
        care = childcare_count(ctx, p, fy)
        fuka = additional_premium_count(ctx, p, fy, peri.months | care.months)
        out.set(V_PERI, p, peri.value, peri.record_ids, peri.states, missing=peri.missing)
        out.set(V_CARE, p, care.value, care.record_ids, care.states, missing=care.missing)
        out.set(V_FUKA, p, fuka.value, fuka.record_ids + peri.record_ids + care.record_ids, fuka.states, missing=fuka.missing + peri.missing + care.missing)
        paid = additional_premium_paid_count(ctx, p, fuka)
        out.set(V_FUKA_PAID, p, paid.value, paid.record_ids + peri.record_ids + care.record_ids, paid.states, missing=paid.missing + peri.missing + care.missing)


def build_inputs(ctx: YearContext) -> ModuleInputs:
    out = ModuleInputs()
    fiscal_inputs(ctx, out)
    w = ctx.window("国年", "判定日")
    on = None if w is None else w.judgment_on
    if on is None:
        for q in ctx.persons:
            for v, x in _DEFAULTS.items():
                out.set(v, q, x)
        return out
    for p in ctx.persons:
        age = age_on(ctx.birth_on(p), on)
        out.set(V_AGE, p, age)
        self2, recs = is_second(ctx, p, on)
        out.set(V_SELF2, p, self2, [r["id"] for r in recs], _states(recs))
        sp = spouses(ctx, p, on)
        second = [(q, is_second(ctx, q, on)) for q in sp.persons]
        second_q = [q for q, (ok, _) in second if ok]
        sp_recs = [r for _, (_, rs) in second for r in rs]
        out.set(V_SP2, p, bool(second_q), sp.record_ids + [r["id"] for r in sp_recs], sp.states | _states(sp_recs))
        # 国内居住の要件（国民年金法第7条第1項第3号、国年則第1条の3）
        rr = _resident(ctx, p, on)
        missing_dom: list[Split] = []
        if rr is not None:
            out.set(V_DOM, p, True, [rr["id"]], _states([rr]))
        else:
            stays = _abroad(ctx, p, on)
            if any(s["attributes"]["purpose"] in ABROAD_EXCEPTIONS for s in stays):
                out.set(V_DOM, p, True, [s["id"] for s in stays], _states(stays))
            elif stays:
                dec = ctx.decision(K_ABROAD5, f"{p}:{on.isoformat()}")
                out.set(V_DOM, p, bool(dec.value), [s["id"] for s in stays] + list(dec.record_ids), _states(stays) | set(dec.states))
            else:
                missing_dom.append(_split(f"事実:住所:{p}:{on.isoformat()}", Means.FACT, {"person": p, "on": on.isoformat(), "事項": "判定日の住所（住民票の記録か国外での滞在の記録）"}))
                out.set(V_DOM, p, False, missing=missing_dom)
        # 収入の基準額（分かれ目を置くかを決めるためだけに使う。式は健保.配偶者の収入の基準額を引く）
        limit = _limit(ctx, p, on, age)
        relevant = 20 <= age < 60 and bool(second_q) and not self2
        # 年間収入（労働契約による判定 → 見込み.年間収入）
        income: int | None = None
        grant = False
        inc_ids: list[str] = []
        inc_states: set[State] = set()
        contract, cids = _contract(ctx, p, on)
        if contract is not None and contract < limit:
            income, inc_ids = contract, cids
        else:
            js = _judgment_on(ctx, K_INCOME, on, person=p)
            if js:
                v = js[0]["value"]
                # 奨学金（2026-11-11 に語彙を足した）：貸与型は含めない（健保の取扱いの勘案。hifuyosha と同じ読み）。給付型は扱いが決まらないので未確定
                income = sum(int(x["amount"]) for x in v["amounts"] if x["income_type"] != "scholarship_loan") - int(v.get("temporary_increase_excluded", 0))
                inc_ids, inc_states = [js[0]["id"]], _states(js)
                grant = any(x["income_type"] == "scholarship_grant" and x["amount"] for x in v["amounts"])
        # 第2号被保険者の年間収入・同一の世帯・援助
        q = second_q[0] if second_q else None
        sp_income: int | None = None
        same = False
        aid: int | None = None
        sp_ids: list[str] = []
        sp_states: set[State] = set()
        aid_ids: list[str] = []
        aid_states: set[State] = set()
        same_ids: list[str] = []
        if q is not None:
            js = _judgment_on(ctx, K_INSURED_INCOME, on, insured=q)
            if js:
                sp_income, sp_ids, sp_states = int(js[0]["value"]["annual_amount"]), [js[0]["id"]], _states(js)
            co = ctx.relations.between(p, q, ("cohabitation",), on=on)
            same = bool(co)
            same_ids = [r.record_id for r in co]
            if not same:
                dw_p = {r["attributes"]["dwelling_id"] for r in ctx.records("dwelling_stay") if r["roles"]["person"] == p and _covers(r.get("when"), on)}
                dw_q = {r["attributes"]["dwelling_id"] for r in ctx.records("dwelling_stay") if r["roles"]["person"] == q and _covers(r.get("when"), on)}
                same = bool(dw_p & dw_q)
            js = _judgment_on(ctx, K_AID, on, supporter=q, person=p)
            if js:
                aid, aid_ids, aid_states = int(js[0]["value"]["annual_amount"]), [js[0]["id"]], _states(js)
        miss_inc: list[Split] = []
        if income is not None and grant and relevant:
            miss_inc.append(_split(f"判断:給付型の奨学金:{p}:{on.isoformat()}", Means.PRIMARY_SOURCE, {"person": p, "on": on.isoformat(), "事項": "給付型の奨学金を被扶養配偶者の年間収入に含めるか"}))
        miss_sp: list[Split] = []
        miss_aid: list[Split] = []
        if relevant:
            tgt = {"person": p, "on": on.isoformat()}
            if income is None:
                miss_inc.append(_split(f"判断:見込み.年間収入:{p}:{on.isoformat()}", Means.JUDGMENT, {**tgt, "kind": K_INCOME}))
            elif income < limit:
                if same and sp_income is None:
                    miss_sp.append(_split(f"判断:見込み.被保険者の年間収入:{q}:{on.isoformat()}", Means.JUDGMENT, {**tgt, "kind": K_INSURED_INCOME, "insured": q}))
                if not same and aid is None:
                    miss_aid.append(_split(f"判断:見込み.援助額:{q}:{p}:{on.isoformat()}", Means.JUDGMENT, {**tgt, "kind": K_AID, "supporter": q}))
                if same and sp_income is not None:
                    s = SpouseSupport(income, limit, True, sp_income, 0, _half(ctx, on))
                    if needs_overall_judgment(s):
                        miss_inc.append(
                            _split(
                                f"判断:生計維持の総合的な勘案:{p}:{on.isoformat()}",
                                Means.JUDGMENT,
                                {**tgt, "事項": "年間収入が第2号被保険者の2分の1以上で、第2号の年間収入を上回らない：機構が世帯の生計の状況を総合的に勘案する"},
                            )
                        )
        out.set(V_INC, p, income or 0, inc_ids, inc_states, missing=miss_inc)
        out.set(V_SPINC, p, sp_income or 0, sp_ids, sp_states, missing=miss_sp)
        out.set(V_SAME, p, same, same_ids)
        out.set(V_AID, p, aid or 0, aid_ids, aid_states, missing=miss_aid)
    return out


# ---------------------------------------------------------------------------
# 段階評価の段：世帯主・配偶者の所得の審査（全額免除・一部免除のただし書、納付猶予の配偶者）
# ---------------------------------------------------------------------------


def head_of(ctx: YearContext, pid: str, on: _dt.date) -> tuple[str | None, bool, list[str]]:
    """その日の住民票の世帯の世帯主（本人なら None）。世帯主が中間表現の人にいなければ (None, True, …)。"""
    r = _resident(ctx, pid, on)
    if r is None:
        return None, False, []
    if r["attributes"]["householder"]:
        return None, False, [r["id"]]
    hh = r["attributes"]["household_id"]
    for q in ctx.persons:
        rq = _resident(ctx, q, on)
        if rq is not None and rq["attributes"]["household_id"] == hh and rq["attributes"]["householder"]:
            return q, False, [r["id"], rq["id"]]
    return None, True, [r["id"]]


def run_review(ctx: StageContext) -> StageOutput:
    out = StageOutput()
    w = ctx.window("国年", "年度")
    if w is None:
        for p in ctx.persons:
            out.set(V_HH_FULL, p, True, uses=())
            out.set(V_SP_FULL, p, True, uses=())
            out.set(V_HH_PART, p, 四分の三, uses=())
        return out
    on = w.date("免除等の期間の初日")
    pf = ctx.parameters.国年
    status_limit = int(pf.全額免除の所得基準.障害者等の所得の上限)
    rules = PartialRules(int(pf.一部免除の所得基準.四分の三免除), int(pf.一部免除の所得基準.半額免除), int(pf.一部免除の所得基準.四分の一免除))
    for p in ctx.persons:
        sp = spouses(ctx, p, on)
        head, unknown, head_ids = head_of(ctx, p, on)
        others = [q for q in sp.persons if q in ctx.persons]
        hh_others = sorted(set(others) | ({head} if head and head != p else set()))
        used = []
        full_hh = True
        part = 四分の三
        for q in hh_others:
            inc, thr = ctx.value(V_MENJO, q), ctx.value(V_FULL_THR, q)
            stat = [ctx.value(V_DISABLED, q), ctx.value(V_WIDOW, q), ctx.value(V_SINGLE, q)]
            pinc, add = ctx.value(V_PART_INC, q), ctx.value(V_ADD, q)
            used += [inc, thr, pinc, add, *stat]
            status = any(bool(s.value) for s in stat)
            full_hh = full_hh and meets_full(int(inc.value), int(thr.value), status, status_limit)
            # 第90条の2 各項の第2号（第90条第1項第3号の経路。H8 の読み(a)）
            part = stricter(part, partial_tier_with_status(int(pinc.value), int(add.value), rules, status, int(inc.value), status_limit))
        full_sp = True
        sp_used = []
        for q in others:
            inc, thr = ctx.value(V_MENJO, q), ctx.value(V_FULL_THR, q)
            stat = [ctx.value(V_DISABLED, q), ctx.value(V_WIDOW, q), ctx.value(V_SINGLE, q)]
            sp_used += [inc, thr, *stat]
            # 納付猶予の第2号（第90条第1項第3号の経路。H8 の読み(a)）
            full_sp = full_sp and meets_full(int(inc.value), int(thr.value), any(bool(s.value) for s in stat), status_limit)
        missing = []
        if unknown:
            missing.append(
                _split(
                    f"事実:国年の世帯主:{p}:{on.isoformat()}",
                    Means.FACT,
                    {"person": p, "on": on.isoformat(), "事項": "住民票の世帯の世帯主が中間表現の人にいない（世帯主の前年の所得が要る：国民年金法第90条第1項ただし書）"},
                )
            )
        ids = sp.record_ids + head_ids
        basis = [ctx.parameter_basis("国年.全額免除の所得基準.障害者等の所得の上限"), ROUTE_135_BASIS]
        out.set(V_HH_FULL, p, full_hh, ids, sp.states, uses=used, basis=basis, missing=missing)
        out.set(V_SP_FULL, p, full_sp, sp.record_ids, sp.states, uses=sp_used, basis=basis)
        out.set(V_HH_PART, p, part, ids, sp.states, uses=used, basis=basis, missing=missing)
    return out


# ---------------------------------------------------------------------------
# 段階評価の段：扶養の連鎖の人を扶養親族等に数える
# ---------------------------------------------------------------------------

STAGE_CHAIN = "国年の扶養の連鎖の扶養親族等"
C_CLAIMANT = "所得税_扶養親族等の申告者"
C_CHAIN = "所得税_連鎖の扶養親族等か"
C_DEP = "所得税_扶養親族に当たるか"
C_AGE = "所得税_年齢"
C_DEDUCTIBLE = "所得税_控除対象扶養親族に当たるか"
C_SPECIFIC = "所得税_特定扶養親族に当たるか"
C_ELDERLY = "所得税_老人扶養親族に当たるか"
C_SPECIAL = "所得税_特別障害者に当たるか"
CHAIN_READS = (C_CLAIMANT, C_CHAIN, C_DEP, C_AGE, C_DEDUCTIBLE, C_SPECIFIC, C_ELDERLY, V_DISABLED, C_SPECIAL)
W_COUNT = "年金_連鎖の扶養親族等の数"
W_ADD = "年金_連鎖の扶養親族等の加算額"
W_DIS = "年金_連鎖の扶養親族等の障害者の額"
CHAIN_WRITES = (W_COUNT, W_ADD, W_DIS)


def run_chain(ctx: StageContext) -> StageOutput:
    """扶養の連鎖の人（所得税で他の人の扶養親族等とされ、自分も申告者である人：扶養所属のグループでは自分のインスタンスの申告者）を、
    その申告者の扶養親族等の数・一部免除の加算額・一部免除判定所得の障害者の額に足す（personal_deductions・juminzei の連鎖と同じ表し方）。"""
    out = StageOutput()
    pf = ctx.parameters.国年
    add = pf.一部免除の所得基準.加算
    ded = pf.一部免除判定所得
    sums: dict[str, list[int]] = {p: [0, 0, 0] for p in ctx.persons}
    uses: dict[str, list[Any]] = {p: [] for p in ctx.persons}
    for x in ctx.persons:
        chain, claimant = ctx.value(C_CHAIN, x), ctx.value(C_CLAIMANT, x)
        c = claimant.value
        if not chain.value or not c or c not in sums:
            continue
        vals = {v: ctx.value(v, x) for v in (C_DEP, C_AGE, C_DEDUCTIBLE, C_SPECIFIC, C_ELDERLY, V_DISABLED, C_SPECIAL)}
        uses[c] += [chain, claimant, *vals.values()]
        n, a, d = chain_addition(
            dependent=bool(vals[C_DEP].value),
            age=int(vals[C_AGE].value),
            deductible=bool(vals[C_DEDUCTIBLE].value),
            specific=bool(vals[C_SPECIFIC].value),
            elderly=bool(vals[C_ELDERLY].value),
            disabled=bool(vals[V_DISABLED].value),
            special=bool(vals[C_SPECIAL].value),
            general=int(add.一般),
            elderly_amount=int(add.老人等),
            specific_amount=int(add.特定扶養親族等),
            disabled_amount=int(ded.障害者),
            special_amount=int(ded.特別障害者),
        )
        sums[c][0] += n
        sums[c][1] += a
        sums[c][2] += d
    for p in ctx.persons:
        for var, val in zip(CHAIN_WRITES, sums[p]):
            out.set(var, p, val, uses=uses[p])
    return out


STAGES = (
    StageSpec(
        name=STAGE_CHAIN,
        title="国民年金の扶養親族等に、扶養の連鎖の人（他の人の扶養親族等で、自分も申告者である人）を数える",
        reads=CHAIN_READS,
        writes=CHAIN_WRITES,
        run=run_chain,
    ),
    StageSpec(
        name=STAGE,
        title="国民年金の免除・納付猶予で、世帯主・配偶者の前年の所得が基準を満たすか（前の段で計算した所得と基準額から決める）",
        reads=(V_MENJO, V_FULL_THR, V_PART_INC, V_ADD, V_DISABLED, V_WIDOW, V_SINGLE),
        writes=(V_HH_FULL, V_SP_FULL, V_HH_PART),
        run=run_review,
    ),
)

RECORD_KINDS = frozenset(
    {
        "kokuho_event",
        "childbirth",
        "npi_exemption",
        "npi_application",
        "national_pension_fund",
        "special_adoption_petition",
        "enrollment",
        "public_assistance",
        "social_insurance_payment",
        "parentage",
        "adoption",
        "foster_placement",
        "employees_pension",
        "national_pension",
        "pension_entitlement",
        "abroad_stay",
        "labor_contract",
        "cohabitation",
        "marriage",
        "resident_record",
        "dwelling_stay",
        "disability_basis",
    }
)

__all__ = ["DECISIONS", "RECORD_KINDS", "STAGES", "build_inputs", "fiscal_inputs", "run_chain", "facto_pairs", "head_of", "is_second", "spouses"]

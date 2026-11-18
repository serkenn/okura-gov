"""規則モジュール hifuyosha：中間表現と判定日 D から、事実の層の入力・健康保険のグループ・判断と注入データの1か所を作る。

判定日の窓口（ctx.window("健保", "判定日")）がある単位でだけ中身を書き、ない単位（所得税の年分など）は全員に仮の値を書く。
法令・通知の値は parameters/健保/（ctx.parameters_at(D)）と注入データから受け、規則の形は calc.py の純粋関数に置く。
判断・選択・注入データの1か所は DecisionSpec・InjectionSpec で宣言し、未入力・未注入なら候補の全部で評価する（D21 R6）。
候補を持てない材料（金額の見込みなど）がないときは、その入力に分かれ目（missing）を付けて未確定にする（何を入力すれば決まるかを返す）。
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from ...candidates import Candidate
from ...injection_points import POINTS
from ...registry import (
    Decided,
    DecisionSlot,
    DecisionSpec,
    GroupInstance,
    InjectionSlot,
    InjectionSpec,
    ModuleInputs,
    YearContext,
    injection_key,
)
from ...result import Means, OutOfScopeCategory, OutOfScopeReason, Split, State
from . import calc as c
from .kinship import SPOUSE_DEGREE, classify, degrees_from

INST = "健保"
P_SAME = "健保.同一の世帯の運用"
P_TYPE = "健保.年間収入の見込みの型"
P_COMMUTE = "健保.通勤手当の扱い"
P_EXPENSE = "健保.事業収入から差し引ける経費"
P_SUPPORT = "健保.別居の仕送りの基準"
#: 給付型の奨学金を年間収入に含めるか（保険者の運用。2026-11-12 に注入点を足した：README の対象外の一覧 HF-03）
P_SCHOLARSHIP = "健保.給付型の奨学金の扱い"
K_LIVELIHOOD_KYOSAI = "判断.共済の生計を共にする"
K_MAIN = "判断.主たる扶養者"
K_NOTICE = "選択.夫婦共同扶養の届出"
K_ABROAD5 = "判断.国内居住の例外第5号"
K_DISABILITY = "判断.障害の程度"
K_EXPENSE_ITEM = "判断.健保の経費の費目"
#: 実績の窓の例外（FUKUOKA-KIJUN 第3 5(1) のただし書、文部科学省共済組合広島大学支部の申立書〔判断を申立てとして読む〕。
#: 注入点 健保.年間収入の見込みの型 の欄が真のときだけ読む。2026-11-12：HF-08）
K_OBVIOUS = "判断.収入が基準額以上とならないことが明らか"
F_OBVIOUS = "基準額以上とならないことが明らかな場合の例外"
#: 収入の記録が一時的か恒常的か（J-29。年間収入は「恒常的な収入の状況」で算定し、一時的な収入は含めない：
#: docs/public-sources/20261109_round2_gaps-sources.md#6.3、docs/public-sources/20261109_round2_kyosai-law-and-criteria.md#6.2・#6.3）。
#: 記録の実績から年間収入を作る箇所（直近の確定申告の運用の事業収入）でだけ読む。2026-11-12：README の対象外の一覧 HF-14
K_CONSTANCY = "判断.収入の恒常性"
CONSTANCY_TEMPORARY = "temporary"
#: 直接読む判断・選択（1か所の候補の評価をしないもの。使う種類として宣言する）。
DIRECT_KINDS = (
    "判断.健保の同一の世帯",
    "判断.一時的な別居",
    "判断.事実婚",
    "判断.住所の所在",
    "判断.按分の割合",
    "見込み.年間収入",
    "見込み.援助額",
    "見込み.被保険者の年間収入",
    "選択.被扶養者の届出",
)
ROUNDING_CONTRACT = "労働契約による年間収入の1円未満"
DISABILITY_ASPECT = "pension_disability_level_for_health_insurance"

RECORD_KINDS = frozenset(
    {
        "medical_insurance",
        "insurer_decision",
        "pension_entitlement",
        "disability_basis",
        "resident_record",
        "abroad_stay",
        "cohabitation",
        "separation_reason",
        "dwelling_stay",
        "institution_stay",
        "labor_contract",
        "employer_attestation",
        "business_expense",
        "business_receipt",
        "salary_payment",
        "commuting_status",
        "remittance",
        "dependent_allowance",
        "parentage",
        "adoption",
        "marriage",
        "civil_status",
        "childcare_leave",
        "income_certificate",
    }
)


# ---------------------------------------------------------------------------
# 道具
# ---------------------------------------------------------------------------


def judgment_on(ctx: YearContext) -> _dt.date | None:
    w = ctx.window(INST, "判定日")
    return None if w is None else w.judgment_on


def _date(s: str | None) -> _dt.date | None:
    return _dt.date.fromisoformat(s) if s else None


def covers(when: Mapping[str, Any] | None, on: _dt.date) -> bool:
    """when（日付・区間）が on を含むか。時を持たないものは含むとする。"""
    if not when:
        return True
    if "on" in when:
        return _date(when["on"]) == on
    if "from_on" in when:
        end = _date(when.get("to_on"))
        return _date(when["from_on"]) <= on and (end is None or on <= end)  # type: ignore[operator]
    return True


def _in(day: str | None, start: _dt.date, end: _dt.date) -> bool:
    d = _date(day)
    return d is not None and start <= d <= end


def _states(*recs: Mapping[str, Any]) -> frozenset[State]:
    return frozenset(State.from_mark(r["mark"]) for r in recs if r.get("mark"))


def _year_after(on: _dt.date) -> _dt.date:
    return c._anniversary(on, 1) - _dt.timedelta(days=1)


def _year_before(on: _dt.date) -> _dt.date:
    try:
        return on.replace(year=on.year - 1)
    except ValueError:
        return _dt.date(on.year - 1, 3, 1)


@dataclass
class Origin:
    """入力の値の由来（記録・判断の ID、状態、未確定の分かれ目）。"""

    ids: set[str] = field(default_factory=set)
    states: set[State] = field(default_factory=set)
    missing: list[Split] = field(default_factory=list)
    basis: list[Any] = field(default_factory=list)

    def add(self, *recs: Mapping[str, Any]) -> None:
        for r in recs:
            self.ids.add(r["id"])
            self.states |= _states(r)

    def decided(self, d: Decided) -> None:
        self.ids |= set(d.record_ids)
        self.states |= set(d.states)
        self.missing += list(d.missing)
        self.basis += [b for b in d.basis if b not in self.basis]


def _missing(sid: str, means: Means, target: Mapping[str, Any]) -> Split:
    return Split(id=sid, means=means, target=dict(target), candidates=(), splits_conclusion=True)


# ---------------------------------------------------------------------------
# 医療保険の資格（medical_insurance）
# ---------------------------------------------------------------------------


def memberships(ctx: YearContext, pid: str, on: _dt.date) -> list[Mapping[str, Any]]:
    return [r for r in ctx.records("medical_insurance") if r["roles"]["member"] == pid and covers(r.get("when"), on)]


def insured_membership(ctx: YearContext, pid: str, on: _dt.date) -> Mapping[str, Any] | None:
    """判定日に、被扶養者を持てる制度（または船員保険・国保）の被保険者本人としての資格。複数なら被扶養者を持てる制度を先に。"""
    found = [r for r in memberships(ctx, pid, on) if r["attributes"]["capacity"] == "insured"]
    found.sort(key=lambda r: (r["attributes"]["scheme"] not in c.DEPENDENT_SCHEMES, r["id"]))
    return found[0] if found else None


def excluding_membership(ctx: YearContext, pid: str, on: _dt.date) -> list[Mapping[str, Any]]:
    """被扶養者にならない資格（被保険者・組合員本人、後期高齢者医療）。"""
    return [
        r
        for r in memberships(ctx, pid, on)
        if (r["attributes"]["capacity"] == "insured" and r["attributes"]["scheme"] in c.EXCLUDING_INSURED_SCHEMES)
        or r["attributes"]["scheme"] in c.EXCLUDING_ANY_SCHEMES
    ]


# ---------------------------------------------------------------------------
# 夫婦共同扶養（令和3年4月30日の通知）
# ---------------------------------------------------------------------------


def _forecast(ctx: YearContext, kind: str, on: _dt.date, **subject: str) -> list[Mapping[str, Any]]:
    """判定日 on の見込み（when.on が判定日。置き換えの連鎖の先頭）で、subject の欄が合うもの。新しい判断の順。"""
    out = [j for j in ctx.judgments(kind) if covers(j.get("when"), on) and all(j["subject"].get(k) == v for k, v in subject.items())]
    return sorted(out, key=lambda j: (j["judged_at"], j["id"]), reverse=True)


def de_facto(ctx: YearContext) -> Any:
    def f(a: str, b: str, on: _dt.date) -> tuple[bool, tuple[str, ...]]:
        js = [j for j in ctx.relations.judgments("判断.事実婚", a, b, on=on)]
        return (any(j["value"] is True for j in js), tuple(j["id"] for j in js if j["value"] is True))

    return f


def _spouses(ctx: YearContext, pid: str, on: _dt.date) -> list[tuple[str, tuple[str, ...]]]:
    out = [(r.other, (r.record_id,)) for r in ctx.relations.spouses(pid, on)]
    for j in ctx.judgments("判断.事実婚"):
        s = j["subject"]
        if pid in (s.get("person"), s.get("other_person")) and covers(j.get("when"), on) and j["value"] is True:
            other = s["other_person"] if s["person"] == pid else s["person"]
            out.append((other, (j["id"],)))
    return out


def _child_of(ctx: YearContext, child: str, parent: str, on: _dt.date) -> bool:
    return any(r.other == parent for r in ctx.relations.parents(child, on))


@dataclass(frozen=True)
class KyodoInfo:
    """夫婦共同扶養の材料（中間表現だけから。判断・選択の値を使わない）。"""

    spouse: str
    spouse_is_employee: bool
    insured_income: int | None
    spouse_income: int | None
    allowance_holder: str | None
    record_ids: tuple[str, ...]
    states: frozenset[State]


def kyodo_info(ctx: YearContext, on: _dt.date, dep: str, insured: str) -> KyodoInfo | None:
    """dep が insured とその配偶者（事実婚を含む）の両方の子で、配偶者も被用者保険（健保・共済）か国保の被保険者なら材料を返す。"""
    for spouse, sids in _spouses(ctx, insured, on):
        if not (_child_of(ctx, dep, insured, on) and _child_of(ctx, dep, spouse, on)):
            continue
        m = insured_membership(ctx, spouse, on)
        if m is None:
            continue
        scheme = m["attributes"]["scheme"]
        if scheme in c.DEPENDENT_SCHEMES:
            employee = True
        elif scheme == "national_health_insurance":
            employee = False
        else:
            continue
        recs: list[Mapping[str, Any]] = [m]
        incomes: list[int | None] = []
        for who in (insured, spouse):
            f = _forecast(ctx, "見込み.被保険者の年間収入", on, insured=who)
            incomes.append(f[0]["value"]["annual_amount"] if f else None)
            recs += f[:1]
        holder = None
        for a in ctx.records("dependent_allowance"):
            if a["roles"]["subject_person"] == dep and covers(a.get("when"), on) and a["roles"]["recipient"] in (insured, spouse):
                who = a["roles"]["recipient"]
                wm = insured_membership(ctx, who, on)
                if wm is not None and c.DEPENDENT_SCHEMES.get(wm["attributes"]["scheme"]) in c.KYOSAI:
                    holder = who
                    recs.append(a)
        ids = tuple(sorted({r["id"] for r in recs} | set(sids)))
        return KyodoInfo(spouse, employee, incomes[0], incomes[1], holder, ids, _states(*recs))
    return None


def notice_key(dep: str, a: str, b: str, on: _dt.date) -> str:
    x, y = sorted((a, b))
    return f"{dep}:{x}:{y}:{on.isoformat()}"


def _near_share(ctx: YearContext, on: _dt.date) -> Fraction:
    p = ctx.parameters_at(on).健保.夫婦共同扶養.届出による差の割合
    return Fraction(int(p.分子), int(p.分母))


def _leaves(ctx: YearContext, pid: str, on: _dt.date) -> list[Mapping[str, Any]]:
    """判定日に pid が取得している育児休業等（childcare_leave。健保法第43条の2）。leave_type の other も育児休業等の記録とする（記録の種類が育児休業等）。"""
    return [r for r in ctx.records("childcare_leave") if r["roles"]["person"] == pid and covers(r.get("when"), on)]


def _date_of(r: Mapping[str, Any]) -> _dt.date:
    return _date(r["attributes"].get("effective_on")) or _date(r["when"]["on"])  # type: ignore[return-value]


def _disputes(ctx: YearContext, on: _dt.date, dep: str, pair: set[str]) -> list[Mapping[str, Any]]:
    """夫婦共同扶養の保険者間の協議が整わなかった記録（insurer_decision.attributes.joint_support_agreement が偽。判定日までのもの）。"""
    return [
        r
        for r in ctx.records("insurer_decision")
        if r["roles"]["dependent"] == dep
        and r["roles"]["insured"] in pair
        and r["attributes"].get("joint_support_agreement") is False
        and _date_of(r) <= on
    ]


def _first_filing(ctx: YearContext, on: _dt.date, dep: str, pair: set[str]) -> Mapping[str, Any] | None:
    """初めに届出を受理した保険者等への届出（insurer_decision の notification_filed のうち最も早いもの）。"""
    fs = [
        r
        for r in ctx.records("insurer_decision")
        if r["roles"]["dependent"] == dep
        and r["roles"]["insured"] in pair
        and r["attributes"]["decision"] == "notification_filed"
        and _date(r["when"]["on"]) <= on  # type: ignore[operator]
    ]
    return min(fs, key=lambda r: (r["when"]["on"], r["id"])) if fs else None


def _latest_certificate(ctx: YearContext, pid: str, on: _dt.date) -> Mapping[str, Any] | None:
    """判定日までに発行された直近の課税（非課税）証明書（income_certificate。証明の年度・発行日の新しいもの）。"""
    fs = [r for r in ctx.records("income_certificate") if r["roles"]["person"] == pid and _date(r["when"]["on"]) <= on]  # type: ignore[operator]
    return max(fs, key=lambda r: (r["attributes"]["fiscal_year"], r["when"]["on"], r["id"])) if fs else None


def _kyodo_rule(ctx: YearContext, on: _dt.date, dep: str, insured: str, info: KyodoInfo, *, freeze: bool) -> tuple[str | None, Origin]:
    """夫婦共同扶養の主として生計を維持する者（insured・配偶者・c.KYODO_NEEDS_NOTICE）。材料が足りなければ None と missing。判断・選択を読まない。

    1. freeze（届け出ている被保険者 insured から見るとき）：insured が育児休業等の期間中なら被扶養者を異動しない（別紙3）。
       その休業の子（child_ids）は「新たに誕生した子」として改めて 2 以下で判定する。child_ids がなければ、異動しない場合と改めて判定する場合で
       結論が違うときだけ分かれ目（決める手段＝事実 childcare_leave.attributes.child_ids）。
    2. 共済の組合員で扶養手当等の認定を受けている者（別紙1(3)）。
    3. 保険者間の協議が整わない（別紙1(5)・別紙2(3)）：夫婦とも被用者保険なら、初めの届出の日の属する月の標準報酬月額が高い方（同額は届出）。
       一方が国保なら直近の課税（非課税）証明書（income_certificate）の所得金額が多い方（README の対象外の一覧 HF-04）。
    4. 年間収入の多い方（別紙1(1)(2)・別紙2(1)）。
    """
    o = Origin()
    if freeze:
        leaves = _leaves(ctx, insured, on)
        if leaves:
            o.add(*leaves)
            newborn = [r for r in leaves if dep in (r["attributes"].get("child_ids") or ())]
            unknown = [r for r in leaves if r["attributes"].get("child_ids") is None]
            if not newborn:
                if not unknown:
                    return insured, o
                again, oa = _kyodo_rule(ctx, on, dep, insured, info, freeze=False)
                o.ids |= oa.ids
                o.states |= oa.states
                if again != insured:
                    o.missing.append(
                        _missing(
                            f"育児休業等の子:{insured}:{dep}:{on.isoformat()}",
                            Means.FACT,
                            {
                                "kind": "childcare_leave",
                                "person": insured,
                                "欄": "attributes.child_ids",
                                "child": dep,
                                "reason": "育児休業等の期間中は異動しないが、その休業の子（新たに誕生した子）なら改めて認定する（別紙3）",
                            },
                        )
                    )
                return insured, o
    if info.allowance_holder is not None:
        return info.allowance_holder, o
    pair = {insured, info.spouse}
    disputes = _disputes(ctx, on, dep, pair)
    if disputes:
        o.add(*disputes)
        if not info.spouse_is_employee:
            certs = {who: _latest_certificate(ctx, who, on) for who in sorted(pair)}
            lacking = [who for who, r in certs.items() if r is None]
            if lacking:
                o.missing.append(
                    _missing(
                        f"課税証明書の所得金額:{dep}:{on.isoformat()}",
                        Means.FACT,
                        {"kind": "income_certificate", "person": dep, "insured_candidates": sorted(pair), "記録のない人": lacking,
                         "事項": "直近の課税（非課税）証明書の所得金額（別紙2(3)）"},
                    )
                )
                return None, o
            o.add(*(r for r in certs.values() if r is not None))
            amt = {who: int(r["amounts"]["total_income"]) for who, r in certs.items() if r is not None}
            main = c.kyodo_by_certificate(insured, info.spouse, amt[insured], amt[info.spouse])
            if main is None:
                o.missing.append(
                    _missing(
                        f"課税証明書の所得金額が同額:{dep}:{on.isoformat()}",
                        Means.PRIMARY_SOURCE,
                        {"person": dep, "insured_candidates": sorted(pair), "事項": "直近の課税（非課税）証明書の所得金額が同額のときの扱い（別紙2(3) に書かれていない）"},
                    )
                )
            return main, o
        filed = _first_filing(ctx, on, dep, pair)
        if filed is None:
            o.missing.append(
                _missing(
                    f"初めの届出:{dep}:{on.isoformat()}",
                    Means.FACT,
                    {"kind": "insurer_decision", "person": dep, "decision": "notification_filed", "reason": "協議が整わないときは初めの届出の日の属する月の標準報酬月額で比べる"},
                )
            )
            return None, o
        o.add(filed)
        day = _date(filed["when"]["on"])
        assert day is not None
        smr: dict[str, int] = {}
        for who in sorted(pair):
            m = insured_membership(ctx, who, day)
            v = None if m is None else m.get("amounts", {}).get("standard_monthly_remuneration")
            if m is None or v is None:
                o.missing.append(
                    _missing(
                        f"標準報酬月額:{who}:{day.isoformat()}",
                        Means.FACT,
                        {"kind": "medical_insurance", "person": who, "欄": "amounts.standard_monthly_remuneration", "on": day.isoformat()},
                    )
                )
            else:
                o.add(m)
                smr[who] = int(v)
        if len(smr) < 2:
            return None, o
        return c.kyodo_by_remuneration(insured, info.spouse, smr[insured], smr[info.spouse]), o
    if info.insured_income is None or info.spouse_income is None:
        for who, inc in ((insured, info.insured_income), (info.spouse, info.spouse_income)):
            if inc is None:
                o.missing.append(
                    _missing(f"見込み.被保険者の年間収入:{who}:{on.isoformat()}", Means.JUDGMENT, {"kind": "見込み.被保険者の年間収入", "insured": who, "on": on.isoformat()})
                )
        return None, o
    return c.kyodo_main(insured, info.spouse, info.insured_income, info.spouse_income, info.spouse_is_employee, _near_share(ctx, on)), o


def kyodo_main(ctx: YearContext, on: _dt.date, dep: str, insured: str, *, freeze: bool = True) -> tuple[str | None, KyodoInfo | None, Origin]:
    """夫婦共同扶養のとき、主として生計を維持する者（None は共同扶養でない）。決まらなければ missing つきで insured を返す。
    freeze：insured が届け出ている被保険者（育児休業等の期間中は異動しない：別紙3）。同じ順位の重複の届出を解くときは偽。"""
    info = kyodo_info(ctx, on, dep, insured)
    o = Origin()
    if info is None:
        return None, None, o
    o.ids |= set(info.record_ids)
    o.states |= set(info.states)
    main, ro = _kyodo_rule(ctx, on, dep, insured, info, freeze=freeze)
    o.ids |= ro.ids
    o.states |= ro.states
    o.missing += ro.missing
    if main is None:
        return insured, info, o
    if main == c.KYODO_NEEDS_NOTICE:
        d = ctx.decision(K_NOTICE, notice_key(dep, insured, info.spouse, on))
        o.decided(d)
        v = str(d.value)
        if v.startswith("!"):
            main = info.spouse if v[1:] == insured else insured
        else:
            main = v
    return main, info, o


def _notice_slots(ctx: YearContext) -> list[DecisionSlot]:
    on = judgment_on(ctx)
    if on is None:
        return []
    out: dict[str, DecisionSlot] = {}
    for dep, a in assignments(ctx, on, resolve=False).items():
        for insured in (a.insured, *a.conflict):
            info = kyodo_info(ctx, on, dep, insured)
            if info is None:
                continue
            main, _o = _kyodo_rule(ctx, on, dep, insured, info, freeze=not a.conflict)
            if main != c.KYODO_NEEDS_NOTICE:
                continue
            key = notice_key(dep, insured, info.spouse, on)
            pair = {insured, info.spouse}
            out[key] = DecisionSlot(
                key=key,
                target={"person": dep, "insured_candidates": sorted(pair), "on": on.isoformat()},
                matches=lambda r, dep=dep, pair=pair: r["subject"]["person"] == dep and r["subject"]["insured"] in pair and covers(r.get("when"), on),
                candidates=tuple(Candidate(x, x) for x in sorted(pair)),
                year_filter=False,
                persons=(dep, *sorted(pair)),
            )
    return [out[k] for k in sorted(out)]


# ---------------------------------------------------------------------------
# 被扶養者の割当て（健康保険のグループ）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Assignment:
    """dep を誰の被扶養者として判定するか。conflict は同じ順位の届出がほかにもある被保険者（重複。決まらない）。"""

    insured: str
    record_ids: tuple[str, ...]
    states: frozenset[State]
    conflict: tuple[str, ...] = ()
    missing: tuple[Split, ...] = ()


def _claims(ctx: YearContext, on: _dt.date) -> dict[str, dict[int, dict[str, list[Mapping[str, Any]]]]]:
    """人 → 順位 → 被保険者 → 根拠の記録。順位：0 届出の選択、1 医療保険の被扶養者の資格、2 保険者の決定・届出（最新）。"""
    out: dict[str, dict[int, dict[str, list[Mapping[str, Any]]]]] = {}

    def add(dep: str, level: int, insured: str, rec: Mapping[str, Any]) -> None:
        out.setdefault(dep, {}).setdefault(level, {}).setdefault(insured, []).append(rec)

    for ch in ctx.choices("選択.被扶養者の届出"):
        if ch["value"] is True and covers(ch.get("when"), on):
            add(ch["subject"]["person"], 0, ch["subject"]["insured"], ch)
    for r in ctx.records("medical_insurance"):
        if r["attributes"]["capacity"] == "dependent" and covers(r.get("when"), on) and r["roles"].get("insured"):
            add(r["roles"]["member"], 1, r["roles"]["insured"], r)
    latest: dict[tuple[str, str], Mapping[str, Any]] = {}
    for r in ctx.records("insurer_decision"):
        eff = _date(r["attributes"].get("effective_on")) or _date(r["when"]["on"])
        if eff is None or eff > on:
            continue
        k = (r["roles"]["dependent"], r["roles"]["insured"])
        if k not in latest or (eff, r["id"]) > (_date(latest[k]["attributes"].get("effective_on")) or _date(latest[k]["when"]["on"]), latest[k]["id"]):  # type: ignore[operator]
            latest[k] = r
    for (dep, insured), r in sorted(latest.items()):
        if r["attributes"]["decision"] in ("recognized", "notification_filed"):
            add(dep, 2, insured, r)
    return out


def assignments(ctx: YearContext, on: _dt.date, *, resolve: bool = True) -> dict[str, Assignment]:
    """判定日の被扶養者の割当て。同じ順位で2人の被保険者に届け出ていれば、夫婦共同扶養なら主として生計を維持する者に、
    それ以外は決まらない（最初の被保険者に置き、分かれ目を付ける。1人が2人の被扶養者になることはない：
    docs/public-sources/20261109_impl-prep_kenpo-dependent-practice.md §4.2）。resolve が偽なら夫婦共同扶養で解かない（宣言の段階）。"""
    alive = set(ctx.persons)
    out: dict[str, Assignment] = {}
    for dep, levels in sorted(_claims(ctx, on).items()):
        if dep not in alive:
            continue
        level = min(levels)
        cands = {i: recs for i, recs in levels[level].items() if i in alive and i != dep}
        if not cands:
            continue
        names = sorted(cands)
        recs = [r for i in names for r in cands[i]]
        ids = tuple(sorted({r["id"] for r in recs}))
        states = _states(*recs)
        if len(names) == 1:
            out[dep] = Assignment(names[0], ids, states)
            continue
        if resolve and len(names) == 2:
            main, info, o = kyodo_main(ctx, on, dep, names[0], freeze=False)
            if info is not None and info.spouse == names[1]:
                if main in names and not o.missing:
                    out[dep] = Assignment(main, tuple(sorted(set(ids) | o.ids)), states | frozenset(o.states))
                    continue
                out[dep] = Assignment(names[0], ids, states, (names[1],), tuple(o.missing))
                continue
        miss = _missing(
            f"選択.被扶養者の届出:{dep}:{on.isoformat()}",
            Means.JUDGMENT,
            {"kind": "選択.被扶養者の届出", "person": dep, "insured_candidates": names, "on": on.isoformat(), "reason": "2人以上の被保険者の被扶養者として届け出ている（重複は認められない）"},
        )
        out[dep] = Assignment(names[0], ids, states, tuple(names[1:]), (miss,))
    # 被扶養者を持つ被保険者は、ほかの人の被扶養者の役割に置けない（その人は被保険者等で被扶養者にならない）
    heads = {a.insured for a in out.values()}
    return {d: a for d, a in out.items() if d not in heads}


def build_groups(ctx: YearContext) -> list[GroupInstance]:
    on = judgment_on(ctx)
    persons = list(ctx.persons)
    if on is None:
        return [GroupInstance(f"健康保険一覧:{p}", {"対象外一覧": (p,)}) for p in persons]
    deps: dict[str, list[str]] = {}
    ids: dict[str, set[str]] = {}
    states: dict[str, set[State]] = {}
    for dep, a in assignments(ctx, on).items():
        deps.setdefault(a.insured, []).append(dep)
        ids.setdefault(a.insured, set()).update(a.record_ids)
        states.setdefault(a.insured, set()).update(a.states)
    out: list[GroupInstance] = []
    placed: set[str] = set()
    for insured in sorted(deps):
        members = tuple(sorted(deps[insured]))
        out.append(
            GroupInstance(
                f"健康保険一覧:{insured}",
                {"被保険者一覧": (insured,), "被扶養者一覧": members},
                tuple(sorted(ids[insured])),
                frozenset(states[insured]),
            )
        )
        placed |= {insured, *members}
    out += [GroupInstance(f"健康保険一覧:{p}", {"対象外一覧": (p,)}) for p in persons if p not in placed]
    return out


# ---------------------------------------------------------------------------
# 私学共済の「優先する扶養義務者」（PMAC-01）
# ---------------------------------------------------------------------------


def priority_blocked(ctx: YearContext, on: _dt.date, dep: str, insured: str, o: Origin) -> bool:
    """認定対象者から見て加入者（insured）より近い親族等（配偶者〔事実婚を含む〕が最も近い）が、被用者保険の被保険者本人か、
    国保の被保険者で収入が加入者より多いなら、その扶養義務が優先して認定できない（PMAC-01。私学共済だけ）。
    年間収入は 見込み.被保険者の年間収入（判定日）。分からなければ分かれ目を付ける（結論が決まるときは付けない）。"""
    degrees = dict(degrees_from(ctx.relations, dep, on))
    for sp, ids in _spouses(ctx, dep, on):
        degrees[sp] = (SPOUSE_DEGREE, ids)
    if insured not in degrees:
        return False
    mine = degrees[insured][0]
    alive = set(ctx.persons)
    rels: list[c.CloserRelative] = []
    recs: dict[str, list[Mapping[str, Any]]] = {}
    ids: dict[str, tuple[str, ...]] = {}
    for p, (d, rids) in sorted(degrees.items()):
        if p in (insured, dep) or p not in alive or d >= mine:
            continue
        m = insured_membership(ctx, p, on)
        if m is None:
            continue
        scheme = m["attributes"]["scheme"]
        employee = scheme in c.EXCLUDING_INSURED_SCHEMES
        nhi = scheme == "national_health_insurance"
        f = _forecast(ctx, "見込み.被保険者の年間収入", on, insured=p) if nhi else []
        rels.append(c.CloserRelative(p, employee, nhi, f[0]["value"]["annual_amount"] if f else None))
        recs[p] = [m, *f[:1]]
        ids[p] = rids
    if not rels:
        return False
    fm = _forecast(ctx, "見込み.被保険者の年間収入", on, insured=insured)
    blocked, unknown = c.priority_blocks(rels, fm[0]["value"]["annual_amount"] if fm else None)
    for r in rels:
        o.add(*recs[r.person])
        o.ids |= set(ids[r.person])
    o.add(*fm[:1])
    if blocked:
        return True
    need = sorted({p for p in unknown if not recs[p][1:]} | ({insured} if unknown and not fm else set()))
    for who in need:
        o.missing.append(
            _missing(
                f"見込み.被保険者の年間収入:{who}:{on.isoformat()}",
                Means.JUDGMENT,
                {"kind": "見込み.被保険者の年間収入", "insured": who, "on": on.isoformat(), "reason": "私学共済の優先する扶養義務者（PMAC-01）の収入の比較"},
            )
        )
    return False


def designated_activity_records(ctx: YearContext, pid: str, on: _dt.date) -> list[Mapping[str, Any]]:
    """判定日に、健保則第37条の3（共済も同じ2号）の除外に当たる civil_status の記録（日本の国籍を有しない特定活動の者）。"""
    return [
        r
        for r in ctx.records("civil_status")
        if r["roles"]["person"] == pid
        and covers(r.get("when"), on)
        and c.excluded_designated_activity(r["attributes"].get("japanese_national"), r["attributes"].get("designated_activity"))
    ]


# ---------------------------------------------------------------------------
# 人の事実（年齢・障害・国内居住）
# ---------------------------------------------------------------------------

#: 国内居住の要件の例外（健保則第37条の2、国共済則第2条の5第2項など：docs/public-sources/20261109_round2_kyosai-law-and-criteria.md §1.2）。
#: 第1号 留学、第2号 赴任に同行、第3号 観光・保養・ボランティアなど就労以外の目的での一時的な渡航。第4号・第5号は判断（第5号）で受ける。
ABROAD_EXCEPTIONS = frozenset({"study", "accompanying_assignment", "tourism"})


def _abroad(ctx: YearContext, pid: str, on: _dt.date) -> tuple[bool, list[Mapping[str, Any]]]:
    """判定日に国内に住所がないか（判断.住所の所在 が優先。なければ住民票の記録がなく国外での滞在がある）。"""
    js = [j for j in ctx.judgments("判断.住所の所在") if j["subject"]["person"] == pid and covers(j.get("when"), on)]
    if js:
        return any(j["value"] == "foreign" for j in js), js
    rr = [r for r in ctx.records("resident_record") if r["roles"]["person"] == pid and covers(r.get("when"), on)]
    if rr:
        return False, rr
    st = [r for r in ctx.records("abroad_stay") if r["roles"]["person"] == pid and covers(r.get("when"), on)]
    return bool(st), st


def abroad_needs_judgment(ctx: YearContext, pid: str, on: _dt.date) -> bool:
    abroad, recs = _abroad(ctx, pid, on)
    if not abroad:
        return False
    stays = [r for r in ctx.records("abroad_stay") if r["roles"]["person"] == pid and covers(r.get("when"), on)]
    return not any(s["attributes"]["purpose"] in ABROAD_EXCEPTIONS for s in stays)


def domestic(ctx: YearContext, pid: str, on: _dt.date, o: Origin) -> bool:
    abroad, recs = _abroad(ctx, pid, on)
    o.add(*recs)
    if not abroad:
        return True
    stays = [r for r in ctx.records("abroad_stay") if r["roles"]["person"] == pid and covers(r.get("when"), on)]
    if any(s["attributes"]["purpose"] in ABROAD_EXCEPTIONS for s in stays):
        return True
    try:
        d = ctx.decision(K_ABROAD5, f"{pid}:{on.isoformat()}")
    except KeyError:  # 被扶養者でない人（宣言していない）：判断があればその値、なければ要件を満たさない
        js = [j for j in ctx.judgments(K_ABROAD5) if j["subject"]["person"] == pid and covers(j.get("when"), on)]
        o.add(*js)
        return bool(js) and all(j["value"] is True for j in js)
    o.decided(d)
    return bool(d.value)


def _disability_records(ctx: YearContext, pid: str, on: _dt.date) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    pens = [
        r
        for r in ctx.records("pension_entitlement")
        if r["roles"]["member"] == pid and r["attributes"]["benefit"] == "disability" and covers(r.get("when"), on)
    ]
    js = [
        j
        for j in ctx.judgments(K_DISABILITY)
        if j["subject"]["person"] == pid and covers(j.get("when"), on) and j["value"]["aspect"] == DISABILITY_ASPECT
    ]
    basis = [r for r in ctx.records("disability_basis") if r["roles"]["person"] == pid and covers(r.get("when"), on)]
    return pens, js, basis


def disabled(ctx: YearContext, pid: str, on: _dt.date, o: Origin) -> bool:
    """障害を支給事由とする給付の受給要件に該当する程度の障害を有するか：障害の年金の受給権があれば真。なければ判断
    （判断.障害の程度 の aspect＝pension_disability_level_for_health_insurance）。障害の根拠（手帳など）だけで判断がなければ候補で評価。"""
    pens, js, basis = _disability_records(ctx, pid, on)
    if pens:
        o.add(*pens)
        return True
    if basis or js:
        try:
            d = ctx.decision(K_DISABILITY, f"{pid}:{on.isoformat()}")
        except KeyError:  # 被扶養者でない人（宣言していない）：判断があればその値
            o.add(*js)
            return bool(js) and all(j["value"]["applies"] for j in js)
        o.decided(d)
        o.add(*basis)
        v = d.value
        return bool(v["applies"]) if isinstance(v, Mapping) else bool(v)
    return False


# ---------------------------------------------------------------------------
# 同一の世帯（注入点 健保.同一の世帯の運用、判断.健保の同一の世帯、共済は 判断.共済の生計を共にする）
# ---------------------------------------------------------------------------


def _pair_rel(ctx: YearContext, kind: str, a: str, b: str, on: _dt.date) -> list[Mapping[str, Any]]:
    return [r.record for r in ctx.relations.between(a, b) if r.kind == kind and r.active_on(on)]


def _j04(ctx: YearContext, insured: str, dep: str, on: _dt.date) -> list[Mapping[str, Any]]:
    return [
        j
        for j in ctx.judgments("判断.健保の同一の世帯")
        if j["subject"]["insured"] == insured and j["subject"]["person"] == dep and covers(j.get("when"), on)
    ]


def same_household(ctx: YearContext, on: _dt.date, insured: str, dep: str, scheme: str, insurer: str | None, o: Origin) -> bool:
    j04 = _j04(ctx, insured, dep, on)
    if j04:
        o.add(*j04)
        return all(j["value"]["same_household"] for j in j04)
    rule = _inject(ctx, P_SAME, insurer, on, o) or {}
    cohab = _pair_rel(ctx, "cohabitation", insured, dep, on)
    o.add(*cohab)
    living = bool(cohab)
    if rule.get("同居の判定") == "住民票の世帯に記載され実態も同居":
        rr = {
            p: [r for r in ctx.records("resident_record") if r["roles"]["person"] == p and covers(r.get("when"), on)] for p in (insured, dep)
        }
        o.add(*rr[insured], *rr[dep])
        hh = {p: {r["attributes"]["household_id"] for r in rs} for p, rs in rr.items()}
        living = living and bool(hh[insured] & hh[dep])
    if not living:
        temp: list[Mapping[str, Any]] = []
        if scheme in c.KYOSAI:
            temp = [
                j
                for j in ctx.judgments("判断.一時的な別居")
                if j["subject"]["member"] == insured and j["subject"]["person"] == dep and covers(j.get("when"), on) and j["value"] is True
            ]
        temp += [
            r for r in _pair_rel(ctx, "separation_reason", insured, dep, on) if r["attributes"]["reason"] in ("member_transfer", "work_related")
        ]
        stay = [r for r in ctx.records("institution_stay") if r["roles"]["person"] == dep and covers(r.get("when"), on)]
        site = _same_site(ctx, insured, dep, on)
        if temp and rule.get("転勤等による一時的な別居を同一の世帯とする"):
            o.add(*temp)
            living = True
        elif stay and rule.get("施設入所を同一の世帯とする"):
            o.add(*stay)
            living = True
        elif site and rule.get("同一敷地内の別棟を同一の世帯とする"):
            o.add(*site)
            living = True
    if scheme in c.KYOSAI:
        d = ctx.decision(K_LIVELIHOOD_KYOSAI, f"{insured}:{dep}:{on.isoformat()}")
        o.decided(d)
        living = living and bool(d.value)
    return living


def _same_site(ctx: YearContext, a: str, b: str, on: _dt.date) -> list[Mapping[str, Any]]:
    ds = {p: [r for r in ctx.records("dwelling_stay") if r["roles"]["person"] == p and covers(r.get("when"), on)] for p in (a, b)}
    out = []
    for x in ds[a]:
        for y in ds[b]:
            sx, sy = x["attributes"].get("site_id"), y["attributes"].get("site_id")
            if sx and sx == sy and x["attributes"]["dwelling_id"] != y["attributes"]["dwelling_id"]:
                out += [x, y]
    return out


def same_household_possible(ctx: YearContext, insured: str, dep: str, on: _dt.date) -> bool | None:
    """宣言の段階で：判断.健保の同一の世帯 があればその値、なければ None（運用で決まる）。"""
    j04 = _j04(ctx, insured, dep, on)
    if j04:
        return all(j["value"]["same_household"] for j in j04)
    return None


# ---------------------------------------------------------------------------
# 注入データ（保険者の運用）
# ---------------------------------------------------------------------------


def _inject(ctx: YearContext, point: str, insurer: str | None, on: _dt.date, o: Origin) -> Mapping[str, Any] | None:
    """宣言した保険者の運用の1か所の値（宣言していなければ None）。"""
    if insurer is None:
        return None
    try:
        d = ctx.injection(point, injection_key("insurer", insurer, on))
    except KeyError:
        return None
    o.decided(d)
    return d.value


# ---------------------------------------------------------------------------
# 年間収入（従来の方法・労働契約による判定・実績の窓）
# ---------------------------------------------------------------------------


@dataclass
class Income:
    forecast: int = 0  # 従来の方法の年間収入
    use_contract: bool = False
    contract: int = 0
    window: int = 0
    o_forecast: Origin = field(default_factory=Origin)
    o_contract: Origin = field(default_factory=Origin)
    o_window: Origin = field(default_factory=Origin)
    raw_types: frozenset[str] = frozenset()

    @property
    def income(self) -> int:
        return self.contract if self.use_contract else self.forecast


def _salary_records(ctx: YearContext, pid: str, start: _dt.date, end: _dt.date) -> list[Mapping[str, Any]]:
    return [r for r in ctx.records("salary_payment") if r["roles"]["recipient"] == pid and _in(r["attributes"]["due_on"], start, end)]


def commuting_evidence(ctx: YearContext, pid: str, on: _dt.date) -> list[Mapping[str, Any]]:
    """通勤手当がある（ありうる）ことを示す記録：判定日の前の1年の給与の通勤手当、判定日の通勤の状況・労働契約の通勤手当。"""
    out = [r for r in _salary_records(ctx, pid, _year_before(on), on - _dt.timedelta(days=1)) if r["amounts"].get("commuting_allowance")]
    out += [r for r in ctx.records("commuting_status") if r["roles"]["worker"] == pid and covers(r.get("when"), on)]
    for r in _contracts(ctx, pid, on):
        if r["amounts"].get("monthly_commuting_allowance") or r["attributes"].get("commuting_allowance_stated"):
            out.append(r)
    return out


def _contracts(ctx: YearContext, pid: str, on: _dt.date) -> list[Mapping[str, Any]]:
    return [r for r in ctx.records("labor_contract") if r["roles"]["worker"] == pid and covers(r.get("when"), on)]


def _expense_window(on: _dt.date, kind: str | None) -> tuple[_dt.date, _dt.date]:
    if kind == "直近の確定申告":
        y = c.latest_return_year(on)
        return _dt.date(y, 1, 1), _dt.date(y, 12, 31)
    return on, _year_after(on)


def expense_records(ctx: YearContext, pid: str, start: _dt.date, end: _dt.date) -> list[Mapping[str, Any]]:
    return [r for r in ctx.records("business_expense") if r["roles"]["payer"] == pid and _in(r["when"]["on"], start, end)]


def _mapping(ctx: YearContext, pid: str) -> tuple[dict[str, str], list[Mapping[str, Any]]]:
    js = [j for j in ctx.judgments(K_EXPENSE_ITEM) if j["subject"]["person"] == pid]
    out: dict[str, str] = {}
    for j in sorted(js, key=lambda j: j["judged_at"]):
        for m in j["value"]["mappings"]:
            out[m["expense_category"]] = m["item"]
    return out, js


def expense_slot_key(pid: str, category: str, on: _dt.date) -> str:
    return f"{pid}:{category}:{on.isoformat()}"


def _deductible(
    ctx: YearContext, pid: str, on: _dt.date, rec: Mapping[str, Any], rule: Mapping[str, Any], mapping: Mapping[str, str], o: Origin, insurer: str
) -> bool:
    cat = rec["attributes"]["expense_category"]
    item = mapping.get(cat)
    treat, cond = c.expense_treatment(item, rule)
    if rule.get("方式") == "費目の表" and item is None:
        d = ctx.decision(K_EXPENSE_ITEM, expense_slot_key(pid, cat, on))
        o.decided(d)
        return bool(d.value) if d.open else False
    if treat == c.DEDUCT:
        return True
    if treat == c.NO_DEDUCT:
        return False
    if cond == "同一生計・生計維持関係の者への支出でない":
        return not rec["roles"].get("payee")
    if cond == "事業分と家計分が明確に区分されている":
        js = [j for j in ctx.judgments("判断.按分の割合") if rec["id"] in j["subject"].get("record_ids", ()) and "clearly_separable" in j["value"]]
        if js:
            o.add(*js)
            return all(j["value"]["clearly_separable"] for j in js)
    o.missing.append(
        _missing(
            f"経費の扱い:{insurer}:{rec['id']}",
            Means.FACT,
            {"kind": "insurer_decision", "person": pid, "record_id": rec["id"], "item": item, "condition": cond, "reason": "保険者が個別に判断する経費"},
        )
    )
    return False


def income_of(ctx: YearContext, on: _dt.date, pid: str, insurer: str | None) -> Income:
    inc = Income()
    of = inc.o_forecast
    typ = _inject(ctx, P_TYPE, insurer, on, of) or {}
    commute = _inject(ctx, P_COMMUTE, insurer, on, of) or {}
    fs = _forecast(ctx, "見込み.年間収入", on, person=pid)
    amounts: dict[str, int] = {}
    temp = 0
    if fs:
        of.add(fs[0])
        for a in fs[0]["value"]["amounts"]:
            amounts[a["income_type"]] = amounts.get(a["income_type"], 0) + a["amount"]
        temp = fs[0]["value"].get("temporary_increase_excluded", 0)
    inc.raw_types = frozenset(k for k, v in amounts.items() if v)
    # 労働契約による判定（認定日が2026-04-01以後。給与収入のみ）
    if on >= _dt.date.fromisoformat(str(ctx.parameters_at(on).健保.労働契約による判定.適用開始日)):
        contracts = _contracts(ctx, pid, on)
        others = inc.raw_types - {"salary"}
        if contracts and not others:
            oc = inc.o_contract
            rule = (_inject(ctx, P_COMMUTE, insurer, on, oc) or {}).get("労働契約による判定")
            years = int(ctx.parameters_at(on).健保.労働契約による判定.契約期間の年数)
            parts = [
                c.contract_income(r["amounts"], r["attributes"], contract_end=_date(r["when"].get("to_on")), on=on, commuting_rule=rule, min_years=years)
                for r in contracts
            ]
            if all(p.usable for p in parts):
                total = sum((p.amount for p in parts), Fraction(0))
                oc.add(*contracts)
                inc.use_contract = True
                inc.contract = int(total) if total.denominator == 1 else ctx.round_unfounded(ROUNDING_CONTRACT, total)
    # 従来の方法
    salary = amounts.get("salary", 0)
    if salary and commute.get("従来の方法") == "含まない":
        contracts = [r for r in _contracts(ctx, pid, on) if r["amounts"].get("monthly_commuting_allowance") is not None]
        if contracts:
            of.add(*contracts)
            salary = max(0, salary - 12 * sum(r["amounts"]["monthly_commuting_allowance"] for r in contracts))
        elif commuting_evidence(ctx, pid, on):
            of.missing.append(
                _missing(
                    f"通勤手当の年額:{pid}:{on.isoformat()}",
                    Means.FACT,
                    {"kind": "labor_contract", "person": pid, "欄": "amounts.monthly_commuting_allowance", "reason": "通勤手当を含まない保険者の運用で、通勤手当の額が分からない"},
                )
            )
    gross = amounts.get("business", 0) + amounts.get("real_estate", 0)
    start, end = _expense_window(on, typ.get("事業収入"))
    if typ.get("事業収入") == "直近の確定申告":
        receipts = [r for r in ctx.records("business_receipt") if r["roles"]["recipient"] == pid and _in(r["when"]["on"], start, end)]
        if receipts:
            of.add(*receipts)
            # 判断.収入の恒常性 が一時的（temporary）とした受取は、今後も同程度の収入が見込まれる恒常的な収入でないので除く
            # （判断がなければ、運用の定めどおり確定申告の総収入に含める。HF-14）
            gross = sum(r["amounts"]["amount"] for r in receipts if not temporary_record(ctx, pid, r, of))
    expenses = 0
    if gross:
        rule = _inject(ctx, P_EXPENSE, insurer, on, of) or {"方式": "費目を限定しない"}
        mapping, mjs = _mapping(ctx, pid)
        of.add(*mjs)
        for r in expense_records(ctx, pid, start, end):
            of.add(r)
            if _deductible(ctx, pid, on, r, rule, mapping, of, insurer or ""):
                expenses += r["amounts"]["amount"]
    business = max(0, gross - expenses)
    # 奨学金：貸与型は年間収入に含めない（協会けんぽ K-FAQ 20・共済 MIYAGI 基準-9 のどちらも）。給付型は保険者で扱いが
    # 違う（含まれる場合がある：K-FAQ 20、含まない：MIYAGI）ので保険者の運用（注入点 P_SCHOLARSHIP。未注入なら2つの型の候補）で決める。
    # 保険者が分からず1か所を宣言できないときだけ、額に入れたうえで分かれ目（決める手段＝注入）を付ける
    others_total = sum(v for k, v in amounts.items() if k not in ("salary", "business", "real_estate", "scholarship_loan", "scholarship_grant"))
    grant = amounts.get("scholarship_grant", 0)
    if grant:
        rule = _inject(ctx, P_SCHOLARSHIP, insurer, on, of)
        if rule is None:
            of.missing.append(
                _missing(
                    f"保険者の運用:給付型の奨学金:{pid}:{on.isoformat()}",
                    Means.INJECTION,
                    {"注入点": P_SCHOLARSHIP, "person": pid, "on": on.isoformat(), "事項": "給付型の奨学金を年間収入に含めるか（保険者の運用）"},
                )
            )
        if rule is None or c.scholarship_grant_included(rule):
            others_total += grant
    if temp:
        atts = [
            r
            for r in ctx.records("employer_attestation")
            if r["roles"]["person"] == pid and r["attributes"]["attestation_type"] == "temporary_income_increase"
        ]
        p = ctx.parameters_at(on).健保.事業主の証明
        ok = c.attestation_allowed((_date(r["when"]["on"]) for r in atts), on, int(p.連続の回数の上限), _dt.date.fromisoformat(str(p.数える証明の始まり)))  # type: ignore[misc]
        of.add(*atts)
        if not ok:
            salary += temp
    inc.forecast = salary + business + others_total
    if not fs and not inc.use_contract:
        of.missing.append(
            _missing(f"見込み.年間収入:{pid}:{on.isoformat()}", Means.JUDGMENT, {"kind": "見込み.年間収入", "person": pid, "on": on.isoformat()})
        )
    # 実績の窓
    window_rule = typ.get("月額の連続超過")
    any_twelve = typ.get("見込みの方法") == "任意の連続する12か月"
    if not inc.use_contract and (window_rule or any_twelve):
        ow = inc.o_window
        _inject(ctx, P_TYPE, insurer, on, ow)
        months = c.months_before(on, 12)
        start_m = _dt.date(months[0][0], months[0][1], 1)
        monthly: dict[tuple[int, int], int] = {}
        for r in _salary_records(ctx, pid, start_m, on - _dt.timedelta(days=1)):
            d = _dt.date.fromisoformat(r["attributes"]["due_on"])
            amt = r["amounts"]["gross"] - (r["amounts"].get("commuting_allowance", 0) if commute.get("従来の方法") == "含まない" else 0)
            monthly[(d.year, d.month)] = monthly.get((d.year, d.month), 0) + max(0, amt)
            ow.add(r)
        inc.window = min(c.window_annual(monthly, on, window_rule, any_twelve), 2**31 - 1)
        if window_rule and typ.get(F_OBVIOUS) and c.window_annual(monthly, on, window_rule, False):
            # 今後1年間の収入が基準額以上とならないことが明らか（FUKUOKA-KIJUN 第3 5(1) ただし書）・どの月から起算した12か月も基準未満の見込みの申立て
            # （文部科学省共済組合広島大学支部の申立書）なら、月額の連続超過の窓で超えても恒常的に超えるとみなさない。任意の連続する12か月の実績は当てたまま
            # （calc.window_after_exception。2026-11-12：HF-08）
            try:
                d = ctx.decision(K_OBVIOUS, obvious_key(pid, on))
            except KeyError:
                ow.missing.append(
                    _missing(f"{K_OBVIOUS}:{pid}:{on.isoformat()}", Means.JUDGMENT, {"kind": K_OBVIOUS, "person": pid, "on": on.isoformat()})
                )
            else:
                ow.decided(d)
                if d.value is True:
                    inc.window = min(c.window_after_exception(monthly, on, window_rule, any_twelve, True), 2**31 - 1)
    return inc


def obvious_key(pid: str, on: _dt.date) -> str:
    return f"{pid}:{on.isoformat()}"


def constancy_key(pid: str, record_id: str) -> str:
    return f"{pid}:{record_id}"


def _constancy_judgments(ctx: YearContext, pid: str, record_id: str) -> list[Mapping[str, Any]]:
    return [j for j in ctx.judgments(K_CONSTANCY) if j["subject"]["person"] == pid and record_id in j["subject"]["record_ids"]]


def temporary_record(ctx: YearContext, pid: str, rec: Mapping[str, Any], o: Origin) -> bool:
    """収入の記録を一時的な収入として年間収入から除くか（判断.収入の恒常性。判断がなければ除かない）。"""
    if not _constancy_judgments(ctx, pid, rec["id"]):
        return False
    d = ctx.decision(K_CONSTANCY, constancy_key(pid, rec["id"]))
    o.decided(d)
    return d.value == CONSTANCY_TEMPORARY


# ---------------------------------------------------------------------------
# 援助（見込み.援助額・送金）
# ---------------------------------------------------------------------------


def support_of(ctx: YearContext, on: _dt.date, insured: str, dep: str, insurer: str | None, o: Origin) -> tuple[int | None, int]:
    """被保険者からの援助の年額（分からなければ None）と、ほかの者からの援助の年額。"""
    rule = _inject(ctx, P_SUPPORT, insurer, on, o) or {}
    mine = _forecast(ctx, "見込み.援助額", on, supporter=insured, person=dep)
    others = [j for j in _forecast(ctx, "見込み.援助額", on, person=dep) if j["subject"]["supporter"] != insured]
    o.add(*others)
    other = sum(j["value"]["annual_amount"] for j in others)
    past = [
        r
        for r in ctx.records("remittance")
        if r["roles"]["sender"] == insured
        and (r["roles"]["recipient"] == dep or dep in r["attributes"].get("beneficiaries", ()))
        and _in(r["when"]["on"], _year_before(on), on - _dt.timedelta(days=1))
    ]
    hand = [r for r in past if r["attributes"]["method"] in ("cash", "in_kind")]
    if rule.get("手渡しを認める") is False and hand:
        o.add(*past)
        return sum(r["amounts"]["amount"] for r in past if r not in hand), other
    if mine:
        o.add(mine[0])
        return mine[0]["value"]["annual_amount"], other
    if past:
        o.add(*past)
        return sum(r["amounts"]["amount"] for r in past), other
    return None, other


# ---------------------------------------------------------------------------
# build_inputs
# ---------------------------------------------------------------------------

V = {
    "判定日": "健保_判定日",
    "年齢": "健保_判定日の年齢",
    "年末": "健保_判定日の属する年の12月31日の年齢",
    "障害": "健保_障害を支給事由とする給付の受給要件に該当する程度の障害を有するか",
    "国内": "健保_国内居住の要件を満たすか",
    "範囲": "健保_被扶養者の範囲の親族か",
    "同一": "健保_同一の世帯に属するか",
    "配偶者": "健保_被保険者の配偶者か",
    "制度": "健保_被保険者の制度",
    "除外": "健保_被扶養者から除かれる資格を有するか",
    "見込み": "健保_収入の見込みによる年間収入",
    "契約を使う": "健保_労働契約による判定を使うか",
    "契約": "健保_労働契約による年間収入",
    "窓": "健保_実績による年額",
    "本人": "健保_被保険者本人の年間収入の見込み",
    "援助": "健保_援助の見込み額",
    "他の援助": "健保_他の者からの援助の見込み額",
    "型": "健保_別居の仕送りの基準の型",
    "主でない": "健保_主たる扶養者でないか",
    "中心": "健保_被保険者が生計維持の中心的役割を果たすか",
}
DEFAULTS: Mapping[str, Any] = {
    "判定日": _dt.date(2025, 1, 1),
    "年齢": 0,
    "年末": 0,
    "障害": False,
    "国内": False,
    "範囲": c.OUTSIDE,
    "同一": False,
    "配偶者": False,
    "制度": "",
    "除外": False,
    "見込み": 0,
    "契約を使う": False,
    "契約": 0,
    "窓": 0,
    "本人": 0,
    "援助": 0,
    "他の援助": 0,
    "型": "",
    "主でない": False,
    "中心": False,
}


def _int(v: int) -> int:
    return max(0, min(int(v), 2**31 - 1))


def _base(ctx: YearContext, on: _dt.date, scheme: str, age: int, dec31: int, dis: bool, spouse: bool) -> int:
    from .variables import base_amount, base_category_of  # 式と同じ関数で決める

    p = ctx.parameters_at(on).健保
    lim = c.AgeLimits(int(p.被扶養者の年齢の区分["60歳以上"]), int(p.被扶養者の年齢の区分["19歳以上"]), int(p.被扶養者の年齢の区分["23歳未満"]))
    node = p.被扶養者の収入の基準額[scheme or "健康保険"]
    return base_amount(node, on.isoformat(), base_category_of(age, dec31, dis, spouse, lim, node, on.isoformat()))


def build_inputs(ctx: YearContext) -> ModuleInputs:
    out = ModuleInputs()
    on = judgment_on(ctx)
    vals: dict[tuple[str, str], tuple[Any, Origin]] = {}

    def put(key: str, pid: str, value: Any, o: Origin | None = None) -> None:
        vals[(key, pid)] = (value, o or Origin())

    if on is not None:
        death = {p["id"]: _date(p.get("death_on")) for p in ctx.ir["persons"]}
        assigned = assignments(ctx, on)
        for pid in ctx.persons:
            birth = ctx.birth_on(pid)
            put("判定日", pid, on)
            put("年齢", pid, c.age_on(birth, on))
            put("年末", pid, c.age_on(birth, _dt.date(on.year, 12, 31)))
            o = Origin()
            put("障害", pid, disabled(ctx, pid, on, o), o)
            o = Origin()
            put("国内", pid, domestic(ctx, pid, on, o), o)
        need_insured: dict[str, bool] = {}
        for dep, a in sorted(assigned.items()):
            _dependent(ctx, on, dep, a, death, put, vals, need_insured, out)
        for pid in ctx.persons:
            fs = _forecast(ctx, "見込み.被保険者の年間収入", on, insured=pid)
            o = Origin()
            if fs:
                o.add(fs[0])
                put("本人", pid, _int(fs[0]["value"]["annual_amount"]), o)
            elif need_insured.get(pid):
                o.missing.append(
                    _missing(
                        f"見込み.被保険者の年間収入:{pid}:{on.isoformat()}",
                        Means.JUDGMENT,
                        {"kind": "見込み.被保険者の年間収入", "insured": pid, "on": on.isoformat()},
                    )
                )
                put("本人", pid, 0, o)
    for pid in ctx.persons:
        for key, var in V.items():
            value, o = vals.get((key, pid), (DEFAULTS[key], Origin()))
            out.set(var, pid, value, o.ids, o.states, missing=o.missing, basis=o.basis)
    return out


def _dependent(
    ctx: YearContext,
    on: _dt.date,
    dep: str,
    a: Assignment,
    death: Mapping[str, _dt.date | None],
    put: Any,
    vals: Mapping[tuple[str, str], tuple[Any, Origin]],
    need_insured: dict[str, bool],
    out: ModuleInputs,
) -> None:
    insured = a.insured
    m = insured_membership(ctx, insured, on)
    raw = None if m is None else m["attributes"]["scheme"]
    if raw == "seamen_insurance":
        out.exclude(dep, OutOfScopeReason(OutOfScopeCategory.OUT_OF_RANGE, "船員保険の被扶養者は対象外（SCOPE §5.5：健康保険法の健康保険と共済組合）", (m["id"],)))  # type: ignore[index]
        return
    scheme = c.DEPENDENT_SCHEMES.get(raw or "", "")
    insurer = None if m is None or not scheme else m["attributes"]["insurer_id"]
    o_scheme = Origin()
    o_scheme.ids |= set(a.record_ids)
    o_scheme.states |= set(a.states)
    o_scheme.missing += list(a.missing)
    if m is not None:
        o_scheme.add(m)
    put("制度", dep, scheme, o_scheme)
    # 続柄
    k = classify(ctx.relations, insured, dep, on, scheme, de_facto=de_facto(ctx), death_on=death)
    ok_ = Origin()
    ok_.ids |= set(k.record_ids)
    ok_.missing += list(a.missing)
    put("範囲", dep, k.category if scheme else c.OUTSIDE, ok_)
    put("配偶者", dep, k.spouse, ok_)
    # 被保険者等・後期高齢者医療
    ex = excluding_membership(ctx, dep, on) + designated_activity_records(ctx, dep, on)
    oe = Origin()
    oe.add(*ex)
    put("除外", dep, bool(ex), oe)
    if not scheme:
        return
    # 同一の世帯
    os_ = Origin()
    same = same_household(ctx, on, insured, dep, scheme, insurer, os_)
    put("同一", dep, same, os_)
    # 年間収入
    inc = income_of(ctx, on, dep, insurer)
    put("見込み", dep, _int(inc.forecast), inc.o_forecast)
    put("契約を使う", dep, inc.use_contract, inc.o_contract)
    put("契約", dep, _int(inc.contract), inc.o_contract)
    put("窓", dep, _int(inc.window), inc.o_window)
    # 主たる扶養者でない
    on_ = Origin()
    not_main = False
    main, _info, ok = kyodo_main(ctx, on, dep, insured)
    on_.ids |= ok.ids
    on_.states |= ok.states
    on_.missing += ok.missing
    if main is not None and main != insured:
        not_main = True
    if scheme in c.KYOSAI:
        allow = [
            r
            for r in ctx.records("dependent_allowance")
            if r["roles"]["subject_person"] == dep and r["roles"]["recipient"] != insured and covers(r.get("when"), on)
        ]
        mains = [
            j for j in ctx.judgments(K_MAIN) if j["subject"]["person"] == dep and j["subject"]["supporter"] == insured and covers(j.get("when"), on)
        ]
        on_.add(*allow, *mains)
        if allow or any(j["value"] is False for j in mains):
            not_main = True
    if scheme == "私学共済" and not not_main and priority_blocked(ctx, on, dep, insured, on_):
        not_main = True
    put("主でない", dep, not_main, on_)
    # 援助
    o_sup = Origin()
    support, other = support_of(ctx, on, insured, dep, insurer, o_sup)
    kind = (_inject(ctx, P_SUPPORT, insurer, on, o_sup) or {}).get("型", "")
    put("型", dep, kind, o_sup)
    put("他の援助", dep, _int(other), o_sup)
    # 必要な材料の分かれ目（その材料で結論が変わりうるときだけ）
    base = _base(ctx, on, scheme, vals[("年齢", dep)][0], vals[("年末", dep)][0], vals[("障害", dep)][0], k.spouse)
    income = inc.income
    live = income < base and not (inc.window and inc.window >= base) and not not_main
    if same and live:
        need_insured[insured] = True
    oc = Origin()
    central = False
    if same and live:
        fs = _forecast(ctx, "見込み.被保険者の年間収入", on, insured=insured)
        if fs:
            ins = fs[0]["value"]["annual_amount"]
            p = ctx.parameters_at(on).健保.生計維持の比較.同一の世帯の収入の割合
            half = Fraction(int(p.分子), int(p.分母))
            if not Fraction(income) < Fraction(ins) * half and income <= ins:
                key = f"{dep}:{insured}:{on.isoformat()}"
                try:
                    d = ctx.decision(K_MAIN, key)
                    oc.decided(d)
                    central = bool(d.value)
                except KeyError:
                    js = [j for j in ctx.judgments(K_MAIN) if j["subject"]["person"] == dep and j["subject"]["supporter"] == insured and covers(j.get("when"), on)]
                    if js:
                        oc.add(*js)
                        central = all(j["value"] is True for j in js)
                    else:
                        oc.missing.append(
                            _missing(f"{K_MAIN}:{key}", Means.JUDGMENT, {"kind": K_MAIN, "person": dep, "supporter": insured, "on": on.isoformat()})
                        )
    put("中心", dep, central, oc)
    if support is None and not same and live:
        o_sup.missing.append(
            _missing(f"見込み.援助額:{insured}:{dep}:{on.isoformat()}", Means.JUDGMENT, {"kind": "見込み.援助額", "supporter": insured, "person": dep, "on": on.isoformat()})
        )
    put("援助", dep, _int(support or 0), o_sup)


# ---------------------------------------------------------------------------
# 判断・選択の1か所と、注入データの1か所の宣言
# ---------------------------------------------------------------------------


def _deps_with_insurer(ctx: YearContext) -> list[tuple[_dt.date, str, Assignment, str, str]]:
    """(判定日, 被扶養者, 割当て, 制度, 保険者) の一覧（宣言の段階。夫婦共同扶養では解かない）。"""
    on = judgment_on(ctx)
    if on is None:
        return []
    out = []
    for dep, a in sorted(assignments(ctx, on, resolve=False).items()):
        for insured in (a.insured, *a.conflict):
            m = insured_membership(ctx, insured, on)
            if m is None or m["attributes"]["scheme"] not in c.DEPENDENT_SCHEMES:
                continue
            out.append((on, dep, Assignment(insured, a.record_ids, a.states), c.DEPENDENT_SCHEMES[m["attributes"]["scheme"]], m["attributes"]["insurer_id"]))
    return out


def _bool_candidates() -> tuple[Candidate, ...]:
    return (Candidate(True, "true"), Candidate(False, "false"))


def _kyosai_slots(ctx: YearContext) -> list[DecisionSlot]:
    out = []
    for on, dep, a, scheme, _ins in _deps_with_insurer(ctx):
        if scheme not in c.KYOSAI or _j04(ctx, a.insured, dep, on):
            continue
        insured = a.insured
        out.append(
            DecisionSlot(
                key=f"{insured}:{dep}:{on.isoformat()}",
                target={"member": insured, "person": dep, "on": on.isoformat()},
                matches=lambda r, i=insured, d=dep, on=on: r["subject"]["member"] == i and r["subject"]["person"] == d and covers(r.get("when"), on),
                year_filter=False,
                persons=(insured, dep),
            )
        )
    return out


def _raw_total(ctx: YearContext, on: _dt.date, pid: str) -> int | None:
    fs = _forecast(ctx, "見込み.年間収入", on, person=pid)
    if not fs:
        return None
    return sum(a["amount"] for a in fs[0]["value"]["amounts"]) + fs[0]["value"].get("temporary_increase_excluded", 0)


def _main_slots(ctx: YearContext) -> list[DecisionSlot]:
    """S52 記1 のただし書（被保険者が世帯の生計維持の中心的役割を果たすか）の材料の判断（判断.主たる扶養者）。
    同一の世帯でありえて、見込みの総額の2倍が被保険者の年間収入以上のときだけ宣言する。"""
    out = []
    for on, dep, a, _scheme, _ins in _deps_with_insurer(ctx):
        insured = a.insured
        if same_household_possible(ctx, insured, dep, on) is False:
            continue
        raw = _raw_total(ctx, on, dep)
        fs = _forecast(ctx, "見込み.被保険者の年間収入", on, insured=insured)
        if raw is None or not fs or 2 * raw < fs[0]["value"]["annual_amount"]:
            continue
        out.append(
            DecisionSlot(
                key=f"{dep}:{insured}:{on.isoformat()}",
                target={"person": dep, "supporter": insured, "on": on.isoformat(), "use": "S52 記1 ただし書（世帯の生計維持の中心的役割）"},
                matches=lambda r, i=insured, d=dep, on=on: r["subject"]["person"] == d and r["subject"]["supporter"] == i and covers(r.get("when"), on),
                year_filter=False,
                persons=(insured, dep),
            )
        )
    return out


def _dep_ids(ctx: YearContext) -> list[str]:
    return sorted({dep for _on, dep, *_ in _deps_with_insurer(ctx)})


def _abroad_slots(ctx: YearContext) -> list[DecisionSlot]:
    on = judgment_on(ctx)
    if on is None:
        return []
    return [
        DecisionSlot(
            key=f"{p}:{on.isoformat()}",
            target={"person": p, "on": on.isoformat()},
            matches=lambda r, p=p, on=on: r["subject"]["person"] == p and covers(r.get("when"), on),
            year_filter=False,
            persons=(p,),
        )
        for p in _dep_ids(ctx)
        if abroad_needs_judgment(ctx, p, on)
    ]


def _disability_slots(ctx: YearContext) -> list[DecisionSlot]:
    on = judgment_on(ctx)
    if on is None:
        return []
    out = []
    for p in _dep_ids(ctx):
        pens, js, basis = _disability_records(ctx, p, on)
        if pens or not (basis or js):
            continue
        out.append(
            DecisionSlot(
                key=f"{p}:{on.isoformat()}",
                target={"person": p, "on": on.isoformat(), "aspect": DISABILITY_ASPECT},
                matches=lambda r, p=p, on=on: r["subject"]["person"] == p and covers(r.get("when"), on) and r["value"]["aspect"] == DISABILITY_ASPECT,
                candidates=_bool_candidates(),
                year_filter=False,
                persons=(p,),
            )
        )
    return out


def _expense_slots(ctx: YearContext) -> list[DecisionSlot]:
    """費目の対応（判断.健保の経費の費目）がない業務の支出の費目：差し引く・差し引かないの両端で評価する（単調：差し引くほど年間収入が減る）。"""
    out: dict[str, DecisionSlot] = {}
    for on, dep, _a, _scheme, _ins in _deps_with_insurer(ctx):
        mapping, _js = _mapping(ctx, dep)
        for kind in ("直近の確定申告", None):
            s, e = _expense_window(on, kind)
            for r in expense_records(ctx, dep, s, e):
                cat = r["attributes"]["expense_category"]
                if cat in mapping:
                    continue
                key = expense_slot_key(dep, cat, on)
                out.setdefault(
                    key,
                    DecisionSlot(
                        key=key,
                        target={"person": dep, "expense_category": cat, "on": on.isoformat()},
                        matches=lambda r, d=dep, cat=cat: r["subject"]["person"] == d and any(m["expense_category"] == cat for m in r["value"]["mappings"]),
                        candidates=(Candidate(False, "差し引かない"), Candidate(True, "差し引く")),
                        year_filter=False,
                        persons=(dep,),
                        monotone=f"健保の経費:{dep}:{on.isoformat()}",
                    ),
                )
    return [out[k] for k in sorted(out)]


def _obvious_slots(ctx: YearContext) -> list[DecisionSlot]:
    """判断.収入が基準額以上とならないことが明らか（判定日・認定対象者）。実績の窓の例外のある運用で月額の連続超過の窓が値を持つときだけ読む（lazy）。

    FUKUOKA の型では「当該3か月を含む今後1年間の収入が収入基準額以上とならないことが明らか」、広島大学支部の型では「扶養認定日以降どの月から起算しても
    12か月間の収入が基準未満の見込み」の申立て（docs/public-sources/20261112_impl-research4_hifuyosha-insurers.md#1・#2）。
    """
    out: dict[str, DecisionSlot] = {}
    for on, dep, _a, _scheme, _ins in _deps_with_insurer(ctx):
        if not _salary_records(ctx, dep, _year_before(on), on - _dt.timedelta(days=1)):
            continue
        key = obvious_key(dep, on)
        out.setdefault(
            key,
            DecisionSlot(
                key=key,
                target={"person": dep, "on": on.isoformat()},
                matches=lambda r, d=dep, on=on: r["subject"]["person"] == d and covers(r.get("when"), on),
                candidates=_bool_candidates(),
                year_filter=False,
                persons=(dep,),
                lazy=True,
            ),
        )
    return [out[k] for k in sorted(out)]


def _constancy_slots(ctx: YearContext) -> list[DecisionSlot]:
    """判断.収入の恒常性（認定対象者・収入の記録）：直近の確定申告の運用で事業収入の実績に数えうる受取に判断があるときだけ宣言する（lazy：
    その運用で読んだときだけ開く。食い違う判断があれば違う値だけを候補にする）。"""
    out: dict[str, DecisionSlot] = {}
    for on, dep, _a, _scheme, _ins in _deps_with_insurer(ctx):
        start, end = _expense_window(on, "直近の確定申告")
        for r in ctx.records("business_receipt"):
            if r["roles"]["recipient"] != dep or not _in(r["when"]["on"], start, end) or not _constancy_judgments(ctx, dep, r["id"]):
                continue
            key = constancy_key(dep, r["id"])
            out.setdefault(
                key,
                DecisionSlot(
                    key=key,
                    target={"person": dep, "record_id": r["id"], "use": "健保の年間収入（直近の確定申告の事業収入）に含める恒常的な収入か"},
                    matches=lambda j, d=dep, rid=r["id"]: j["subject"]["person"] == d and rid in j["subject"]["record_ids"],
                    candidates=(Candidate("recurring", "恒常的（含める）"), Candidate(CONSTANCY_TEMPORARY, "一時的（含めない）")),
                    year_filter=False,
                    persons=(dep,),
                    lazy=True,
                ),
            )
    return [out[k] for k in sorted(out)]


def _none(ctx: YearContext) -> list[DecisionSlot]:
    return []


DECISIONS: tuple[DecisionSpec, ...] = (
    DecisionSpec(K_LIVELIHOOD_KYOSAI, _kyosai_slots),
    DecisionSpec(K_MAIN, _main_slots),
    DecisionSpec(K_NOTICE, _notice_slots, value_of=lambda r: r["subject"]["insured"] if r["value"] else "!" + r["subject"]["insured"]),
    DecisionSpec(K_ABROAD5, _abroad_slots),
    DecisionSpec(K_DISABILITY, _disability_slots),
    DecisionSpec(K_EXPENSE_ITEM, _expense_slots),
    DecisionSpec(K_OBVIOUS, _obvious_slots),
    DecisionSpec(K_CONSTANCY, _constancy_slots),
    *(DecisionSpec(k, _none) for k in DIRECT_KINDS),
)


def _effect_candidates(point: str, effect: Any) -> tuple[Candidate, ...]:
    """注入点の候補を、この規則モジュールでの効き方が同じものでまとめる（名前は「・」でつなぐ。候補の範囲は変えない）。"""
    groups: dict[str, list[Any]] = {}
    for cand in POINTS[point].candidates:
        groups.setdefault(repr(effect(cand.data)), []).append(cand)
    return tuple(Candidate(items[0].data, "・".join(x.label for x in items)) for items in groups.values())


def _type_effect(d: Mapping[str, Any]) -> Any:
    return (d.get("月額の連続超過"), d.get("見込みの方法") == "任意の連続する12か月", d.get("事業収入"), bool(d.get(F_OBVIOUS)))


def _injection_slots(point: str) -> Any:
    def slots(ctx: YearContext) -> list[InjectionSlot]:
        found: dict[str, InjectionSlot] = {}
        by_insurer: dict[tuple[str, str], list[tuple[_dt.date, str, Assignment]]] = {}
        for on, dep, a, _scheme, ins in _deps_with_insurer(ctx):
            by_insurer.setdefault((ins, a.insured), []).append((on, dep, a))
        for (ins, insured), items in sorted(by_insurer.items()):
            on = items[0][0]
            deps = [d for _o, d, _a in items]
            if not any(_needs(ctx, point, on, insured, d) for d in deps):
                continue
            key = injection_key("insurer", ins, on)
            cands = _effect_candidates(point, _type_effect) if point == P_TYPE else None
            prev = found.get(key)
            persons = tuple(sorted({insured, *deps} | set(prev.persons if prev and prev.persons else ())))
            found[key] = InjectionSlot(key, "insurer", ins, on, target={"insured": insured}, candidates=cands, persons=persons)
        return [found[k] for k in sorted(found)]

    return slots


def _needs(ctx: YearContext, point: str, on: _dt.date, insured: str, dep: str) -> bool:
    """その注入点の運用で、この被扶養者の値が変わりうるか（変わらない注入点は宣言しない：候補の直積を小さくする）。"""
    if point == P_SAME:
        return not _j04(ctx, insured, dep, on)
    if point == P_SUPPORT:
        return same_household_possible(ctx, insured, dep, on) is not True
    if point == P_COMMUTE:
        return bool(commuting_evidence(ctx, dep, on))
    fs = _forecast(ctx, "見込み.年間収入", on, person=dep)
    if point == P_SCHOLARSHIP:
        return bool(fs) and any(a["income_type"] == "scholarship_grant" and a["amount"] for a in fs[0]["value"]["amounts"])
    types = {a["income_type"] for a in fs[0]["value"]["amounts"] if a["amount"]} if fs else set()
    business = bool(types & {"business", "real_estate"})
    if not business:  # 直近の確定申告の型では見込みに事業がなくても実績の売上を数える
        y = c.latest_return_year(on)
        business = any(
            r["roles"]["recipient"] == dep and _in(r["when"]["on"], _dt.date(y, 1, 1), _dt.date(y, 12, 31)) for r in ctx.records("business_receipt")
        )
    if point == P_EXPENSE:
        return business
    if point == P_TYPE:
        recent = _salary_records(ctx, dep, _year_before(on), on - _dt.timedelta(days=1))
        return business or bool(recent)
    return False


#: 使う注入点（概念辞書の 注入データ にも書く。書かなければ登録の検査 undeclared_injection_point が止める）。
INJECTIONS: tuple[InjectionSpec, ...] = tuple(
    InjectionSpec(p, _injection_slots(p)) for p in (P_SAME, P_TYPE, P_COMMUTE, P_EXPENSE, P_SUPPORT, P_SCHOLARSHIP)
)


__all__ = ["DECISIONS", "INJECTIONS", "RECORD_KINDS", "ROUNDING_CONTRACT", "assignments", "build_groups", "build_inputs"]

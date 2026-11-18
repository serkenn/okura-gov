"""規則モジュール kokuho：中間表現から、年度 F の世帯と人の事実を読む（法令の解釈は calc.py と inputs.py の説明に書いた範囲だけ）。

- 世帯：賦課期日（F年4月1日。料は年度の初日、税は4月1日：[KHP] §1.1・§1.2）の住民票の世帯（resident_record の household_id・
  householder）。国保の被保険者でない世帯主（擬制世帯主）も世帯主（packages/ir/README.md §6.2、[KHP] §1.1・§1.2）。
- 被保険者：medical_insurance の scheme＝national_health_insurance（資格の区間は両端を含む）。
- 年齢：誕生日の前日に年齢を加える（docs/public-sources/20261109_R1-laws_social-insurance-age-records.md §3）。
  介護納付金賦課被保険者は介護保険法第9条第2号（40歳以上65歳未満）、18歳以上被保険者・未就学児は「…に達する日以後の最初の3月31日」
  （[KHP] §3.1・§7・§9）。3月31日の区切りは年度の区切りと同じなので、年度を通じて同じ区分になる。
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ...injection_points import KOKUHO_CHILD_HOUSEHOLD
from ...registry import YearContext
from ...result import Means, State

NHI = "national_health_insurance"
#: 市町村・保険者の個別の処分（authority_decision の decision）のうち、このモジュールが使うもの（2026-11-12）。
#: taxation_at_non_resident_record_municipality（住民票と違う住所での課税）は住民税（juminzei）の事実。
REDUCTION_APPROVED = "reduction_approved"
STUDENT_RECOGNIZED = "kokuho_student_special_case_recognized"
AUTHORITY_DECISIONS = frozenset({REDUCTION_APPROVED, STUDENT_RECOGNIZED})
#: 2026-11-12：処分の税目（authority_decision の tax_item）。このモジュールは国民健康保険料（税）の処分だけを読む
#: （住民税の減免・住民票と違う市町村での課税は juminzei。docs/hypotheses/20261112_impl-research8_tokutei-shishutsu-reading.md H8）。
AUTHORITY_TAX_ITEM = "national_health_insurance"


def d(s: str | None) -> _dt.date | None:
    return _dt.date.fromisoformat(s) if s else None


def period_of(when: Mapping[str, Any] | None) -> tuple[_dt.date | None, _dt.date | None]:
    """記録の when の区間（on はその日に始まって続くもの）。"""
    if not when:
        return None, None
    if "on" in when:
        return d(when["on"]), None
    if "from_on" in when:
        return d(when["from_on"]), d(when.get("to_on"))
    return None, None


def covers(when: Mapping[str, Any] | None, on: _dt.date) -> bool:
    a, b = period_of(when)
    return (a is None or a <= on) and (b is None or on <= b)


def reach_date(birth: _dt.date, years: int) -> _dt.date:
    """年齢 years に達する日（誕生日の前日。2月29日生まれは平年の3月1日の前日）。"""
    try:
        anniversary = birth.replace(year=birth.year + years)
    except ValueError:
        anniversary = _dt.date(birth.year + years, 3, 1)
    return anniversary - _dt.timedelta(days=1)


def first_march31_on_or_after(day: _dt.date) -> _dt.date:
    m = _dt.date(day.year, 3, 31)
    return m if day <= m else _dt.date(day.year + 1, 3, 31)


def fiscal_months(fiscal_year: int) -> list[tuple[_dt.date, _dt.date]]:
    """年度 F の各月（4月〜翌3月）の初日と末日。"""
    out = []
    for i in range(12):
        y, m = (fiscal_year, 4 + i) if i < 9 else (fiscal_year + 1, i - 8)
        start = _dt.date(y, m, 1)
        end = (_dt.date(y + (m == 12), m % 12 + 1, 1)) - _dt.timedelta(days=1)
        out.append((start, end))
    return out


def fully_covered(periods: Iterable[tuple[_dt.date | None, _dt.date | None]], start: _dt.date, end: _dt.date) -> bool:
    """区間の和が [start, end] の全部の日を覆うか。"""
    day = start
    ps = sorted(((a or _dt.date.min), (b or _dt.date.max)) for a, b in periods)
    for a, b in ps:
        if a > day:
            break
        if b >= day:
            if b >= end:
                return True
            day = b + _dt.timedelta(days=1)
    return day > end


def overlaps(periods: Iterable[tuple[_dt.date | None, _dt.date | None]], start: _dt.date, end: _dt.date) -> bool:
    return any((a is None or a <= end) and (b is None or b >= start) for a, b in periods)


def states_of(records: Iterable[Mapping[str, Any]]) -> frozenset[State]:
    return frozenset(State.from_mark(r["mark"]) for r in records if "mark" in r)


@dataclass
class PersonFacts:
    """1人分の年度 F の事実。record_ids・states は入力の由来。"""

    pid: str
    insured: bool = False
    months: int = 0
    kaigo_months: int = 0
    kaigo: bool = False
    adult18: bool = False
    preschool: bool = False
    specified: bool = False
    asset: int = 0
    asset_other_municipality: bool = False
    unemployed: bool = False
    childbirth: bool = False
    special_case: str | None = None
    #: 2026-11-12：市町村がみなした世帯（kokuho_event の deemed_household_id。第116条・第116条の2）
    special_household: str | None = None
    #: 2026-11-11：月割り（取得した月から喪失した月の前月まで）で数えた年度の月（0〜11 の添字。4月が0）と、介護納付金賦課被保険者の月
    rule_months: frozenset[int] = frozenset()
    rule_kaigo_months: frozenset[int] = frozenset()
    #: 産前産後の減額の期間の月（年度の月の添字。被保険者である月だけ）
    birth_months: frozenset[int] = frozenset()
    #: 特定同一世帯所属者になった日（特定月の判定）
    specified_on: _dt.date | None = None
    #: 国保法第116条（修学中の特例）でみなされる世帯（住民票の household_id）。第116条の2（入院等）で児童福祉施設に措置入所した子を
    #: 入所前の扶養義務者の世帯（親元）として扱う候補のときもここに入れる（2026-11-12）
    deemed_household: str | None = None
    #: 決まらない理由（分かれ目の ID の頭・決める手段・事項）
    problems: list[tuple[str, Means, str]] = field(default_factory=list)
    #: 2026-11-12：第116条の2（入院等の特例）の材料：特例の始まりの日（kokuho_event の when）・入院等の種類（admission_type）
    special_from: _dt.date | None = None
    admission_type: str | None = None
    #: 第116条の2 でみなされる住所の市町村（入院等の前の市町村。病院等と同じ市町村なら None）
    deemed_municipality: str | None = None
    #: 児童福祉施設に措置入所した扶養義務者のいる子の、入所前の世帯（親元）の候補（市町村の運用で分かれる：注入）
    child_home: str | None = None
    #: その子について引いた注入データの1か所の値（registry.Decided。由来と根拠を入力に入れる）
    child_choice: Any = None
    #: 2026-11-12：その年度の減免の承認（authority_decision の reduction_approved）の記録
    reduction: list[Mapping[str, Any]] = field(default_factory=list)
    household: str | None = None
    head: bool = False
    municipality: str | None = None
    depreciable: bool = False
    record_ids: dict[str, list[str]] = field(default_factory=dict)
    states: dict[str, set[State]] = field(default_factory=dict)

    def note(self, what: str, recs: Iterable[Mapping[str, Any]]) -> None:
        recs = list(recs)
        self.record_ids.setdefault(what, []).extend(r["id"] for r in recs)
        self.states.setdefault(what, set()).update(states_of(recs))


@dataclass
class HouseholdPlan:
    """国保の世帯1つ：key（グループのインスタンスの ID の元）、世帯主、世帯員、市町村、住民票の記録の ID。"""

    key: str
    head: str | None
    members: list[str]
    municipality: str | None
    record_ids: list[str] = field(default_factory=list)
    states: set[State] = field(default_factory=set)

    @property
    def persons(self) -> list[str]:
        return ([self.head] if self.head else []) + [m for m in self.members if m != self.head]


def person_facts(ctx: YearContext, pid: str, fiscal_year: int) -> PersonFacts:
    f = PersonFacts(pid)
    start, end = _dt.date(fiscal_year, 4, 1), _dt.date(fiscal_year + 1, 3, 31)
    levy_day = start
    # 住民票の世帯（賦課期日）
    rr = [r for r in ctx.records("resident_record") if r["roles"]["person"] == pid and covers(r.get("when"), levy_day)]
    if rr:
        a = rr[0]["attributes"]
        f.household, f.head, f.municipality = a["household_id"], bool(a["householder"]), a["municipality_code"]
        f.note("世帯", rr[:1])
    # 被保険者
    mi = [
        r for r in ctx.records("medical_insurance")
        if r["roles"]["member"] == pid and r["attributes"]["scheme"] == NHI and not r["attributes"].get("nhi_association")
        and overlaps([period_of(r.get("when"))], start, end)
    ]
    periods = [period_of(r.get("when")) for r in mi]
    f.insured = bool(mi)
    f.note("被保険者", mi)
    birth = ctx.birth_on(pid)
    r40, r65 = reach_date(birth, 40), reach_date(birth, 65)
    for m_start, m_end in fiscal_months(fiscal_year):
        if fully_covered(periods, m_start, m_end):
            f.months += 1
            if r40 <= m_start and m_end < r65:
                f.kaigo_months += 1
    f.rule_months = rule_months(periods, fiscal_year)
    f.rule_kaigo_months = f.rule_months & rule_months([(r40, r65 - _dt.timedelta(days=1))], fiscal_year)
    # 介護納付金賦課被保険者（年度の中で、被保険者である日に40歳以上65歳未満の日があるか）
    k_start, k_end = max(start, r40), min(end, r65 - _dt.timedelta(days=1))
    f.kaigo = f.insured and k_start <= k_end and overlaps(periods, k_start, k_end)
    # 18歳以上被保険者・未就学児（3月31日の区切りは年度の区切りと同じ）
    f.adult18 = f.insured and first_march31_on_or_after(reach_date(birth, 18)) < start
    f.preschool = f.insured and first_march31_on_or_after(reach_date(birth, 6)) >= end
    # 国保の特例と事由
    for e in ctx.records("kokuho_event"):
        if e["roles"]["person"] != pid:
            continue
        ev = e["attributes"]["event"]
        a, b = period_of(e.get("when"))
        if ev == "specified_same_household_member" and covers(e.get("when"), levy_day):
            f.specified = True
            f.specified_on = a
            f.note("特定同一世帯所属者", [e])
        elif ev in ("student_special_case", "institution_special_case") and overlaps([(a, b)], start, end):
            f.special_case = ev
            f.special_household = e["attributes"].get("deemed_household_id") or f.special_household
            if ev == "institution_special_case":
                f.special_from = a
                f.admission_type = e["attributes"].get("admission_type")
            f.note("特例", [e])
        elif ev == "involuntary_unemployment":
            sep = d(e["attributes"].get("separated_on")) or a
            if sep is not None:
                first = _fiscal_year_of(sep + _dt.timedelta(days=1))
                if first <= fiscal_year <= first + 1:
                    f.unemployed = True
                    f.note("非自発的失業", [e])
    # 2026-11-12（語彙の突き合わせ）：市町村の個別の処分 authority_decision（F-D19）の「国保の修学中の特例の認定」（その年度）。
    # kokuho_event の student_special_case と同じ事実（市町村の認定：仮説 round2 kokuho-core-vs-injected H2 の「第116条の修学中の特例の適用
    # （市町村の認定）」）。どちらで書いてもよく、両方あれば1つの特例として扱う。入院等の特例（institution_special_case）があればそちらを残す
    for e in ctx.records("authority_decision"):
        if (
            e["roles"]["person"] == pid
            and e["attributes"]["decision"] == STUDENT_RECOGNIZED
            and e["attributes"].get("tax_item") == AUTHORITY_TAX_ITEM
            and (e.get("when") or {}).get("fiscal_year") == fiscal_year
        ):
            if f.special_case is None:
                f.special_case = "student_special_case"
            f.note("特例", [e])
    # 減免の承認（authority_decision の reduction_approved。国保法第77条・地方税法第717条：条例による個別の処分。額は記録にない）
    # 2026-11-12：税目（tax_item）が国民健康保険のものだけ（住民税の減免は juminzei）。以前は税目の欄がなく、語彙の文書（VOC F-D19 の［KH］§1.1）どおり
    # 減免の承認を全部国保料（税）の減免として読んでいた
    f.reduction = [
        e for e in ctx.records("authority_decision")
        if e["roles"]["person"] == pid and e["attributes"]["decision"] == REDUCTION_APPROVED
        and e["attributes"].get("tax_item") == AUTHORITY_TAX_ITEM
        and (e.get("when") or {}).get("fiscal_year") == fiscal_year
    ]  # fmt: skip
    # 出産（2026-11-12：共通の種類 childbirth。以前の書き方 kokuho_event の childbirth も読む。同じ出産予定月の記録は1つの出産）
    if f.insured:
        for e in births_of(ctx, pid):
            due = d(e["attributes"].get("expected_delivery_on")) or d(e["attributes"].get("delivered_on")) or period_of(e.get("when"))[0]
            if due is not None:
                before = 3 if e["attributes"].get("multiple_birth") else 1
                p_start = _add_months(_dt.date(due.year, due.month, 1), -before)
                p_end = _add_months(_dt.date(due.year, due.month, 1), 3) - _dt.timedelta(days=1)
                if overlaps([(p_start, p_end)], start, end):
                    f.childbirth = True
                    f.birth_months = f.birth_months | (rule_months([(p_start, p_end)], fiscal_year) & f.rule_months)
                    f.note("出産", [e])
    # 資産割の基礎（その年度の固定資産税額のうち土地・家屋に係る部分）
    pt = [r for r in ctx.records("property_tax") if r["roles"]["taxpayer"] == pid and r.get("when", {}).get("fiscal_year") == fiscal_year]
    for r in pt:
        if f.municipality is not None and r["attributes"]["municipality_code"] != f.municipality:
            f.asset_other_municipality = True
            continue
        f.asset += int(r["amounts"].get("land", 0)) + int(r["amounts"].get("building", 0))
    f.note("資産", pt)
    f.depreciable = any(r["roles"].get("owner") == pid for r in ctx.records("depreciable_asset"))
    return f


def births_of(ctx: YearContext, pid: str) -> list[Mapping[str, Any]]:
    """pid の出産の記録（共通の種類 childbirth と、以前の書き方 kokuho_event の childbirth）。"""
    return [e for e in ctx.records("childbirth") if e["roles"]["person"] == pid] + [
        e for e in ctx.records("kokuho_event") if e["roles"]["person"] == pid and e["attributes"]["event"] == "childbirth"
    ]


def month_index(day: _dt.date, fiscal_year: int) -> int:
    """年度 F の月の添字（F年4月が0、F+1年3月が11。範囲の外は負か12以上）。"""
    return (day.year - fiscal_year) * 12 + day.month - 4


def rule_months(periods: Iterable[tuple[_dt.date | None, _dt.date | None]], fiscal_year: int) -> frozenset[int]:
    """資格の区間（両端を含む。終わりは資格を有する最後の日）から、取得した月から喪失した月（最後の日の翌日の月）の前月までの
    年度の月の添字（注入データ 国保.年度の途中の資格の月割り の「取得した月から喪失した月の前月まで」の数え方）。"""
    out: set[int] = set()
    for a, b in periods:
        first = 0 if a is None else max(0, month_index(a, fiscal_year))
        last = 11 if b is None else min(11, month_index(b + _dt.timedelta(days=1), fiscal_year) - 1)
        out.update(range(first, last + 1))
    return frozenset(out)


def _fiscal_year_of(day: _dt.date) -> int:
    return day.year if day.month >= 4 else day.year - 1


def _add_months(day: _dt.date, n: int) -> _dt.date:
    k = day.year * 12 + day.month - 1 + n
    return _dt.date(k // 12, k % 12 + 1, 1)


def deem_student(ctx: YearContext, facts: Mapping[str, PersonFacts], levy_day: _dt.date) -> None:
    """国保法第116条（修学中の被保険者の特例：[KHP] §1.1）：修学のため別の市町村に住所を有する被保険者は、修学していないとすれば
    同一の世帯に属すると認められる他人の世帯に属するものとみなす。市町村の認定の事実（kokuho_event の student_special_case）がある人を、
    賦課期日に住民票の世帯がある親（親子・養子縁組の関係）の世帯に入れる（法令の読み：みなされる世帯は親の世帯。仮説
    docs/hypotheses/20261109_round2_kokuho-core-vs-injected.md の「親の世帯に属するものとみなされる」）。市町村がみなした世帯の事実
    （kokuho_event の deemed_household_id。2026-11-12）があればそれを使い（第116条の2 の人も）、なく親の世帯が1つに決まらなければ problems に
    理由を書く（分かれ目：事実）。第116条の2 の住所と世帯は deem_institution。"""
    for pid in ctx.persons:
        f = facts[pid]
        if f.special_case and f.special_household:
            # 市町村がみなした世帯（kokuho_event の deemed_household_id）があればそれを使う（2026-11-12）
            if f.special_household != f.household:
                f.deemed_household = f.special_household
            continue
        if f.special_case != "student_special_case":
            continue
        homes = _parent_homes(ctx, facts, pid, levy_day)
        if len(homes) == 1:
            f.deemed_household = next(iter(homes))
        else:
            f.problems.append(
                (
                    "事実:みなされる世帯",
                    Means.FACT,
                    "国保法第116条でみなされる世帯（親の世帯が1つに決まらない。kokuho_event の attributes.deemed_household_id に市町村がみなした世帯を書けば決まる）",
                )
            )


def _parent_homes(ctx: YearContext, facts: Mapping[str, PersonFacts], pid: str, levy_day: _dt.date) -> set[str]:
    """賦課期日に、本人と別の住民票の世帯にいる親（親子・養子縁組）の世帯。"""
    f = facts[pid]
    return {
        facts[r.other].household  # type: ignore[misc]
        for r in ctx.relations.parents(pid, levy_day)
        if r.other in facts and facts[r.other].household is not None and facts[r.other].household != f.household
    }


#: 注入点 国保.児童福祉施設に措置入所した子の世帯 の値（事実の世帯・親元の世帯）
CHILD_FACT, CHILD_HOME = KOKUHO_CHILD_HOUSEHOLD


def deem_institution(
    ctx: YearContext, facts: Mapping[str, PersonFacts], levy_day: _dt.date, home_of: Callable[[PersonFacts], bool]
) -> None:
    """国保法第116条の2（入院等の特例：docs/public-sources/20261112_impl-research4_kokuho-laws.md §1、仮説 H7）。

    - 住所（市町村）：入院等をした際に他の市町村に住所を有していた被保険者は、その市町村の区域内に住所を有するものとみなす（第1項）。
      入院等の前の市町村は、特例の始まりの日（kokuho_event の when の始まり）の前日の住民票の市町村（法令の読み：継続して入院等をしている
      人〔第2項〕は、特例の始まりの日を最初の病院等への入院等の日として記録するので、第2項第1号の「最初の病院等に入院等をした際」の市町村と同じ）。
      前日の住民票がなければ分かれ目（事実）。前日と賦課期日の市町村が同じなら、みなさない（第116条の2 は他の市町村の住所だけ）。
    - 世帯：第116条の2 は住所だけをみなし、第116条の「かつ、当該世帯に属するものとみなす」の文言がない。だから事実の世帯（入院等により
      属することとなった世帯。国保則第5条の2 の語）で計算する（法令の読み）。
      ただし児童福祉施設への措置入所（第1項第2号。admission_type が child_welfare_placement）で扶養義務者（親）がほかの世帯にいる子は、
      親元の世帯として扱う市町村の運用がある（柏市：§1.2）ので、home_of(f)（注入点 国保.児童福祉施設に措置入所した子の世帯 の値。
      未注入なら2つの型の候補）が真なら入所前の世帯（親元）に入れる。admission_type の欄がなく親がほかの世帯にいる人は分かれ目（事実）。
    - 市町村がみなした世帯（deemed_household_id）があれば世帯はそれを使う（deem_student が入れる）。住所の市町村はこの関数で決める。
    """
    for pid in ctx.persons:
        f = facts[pid]
        if f.special_case != "institution_special_case":
            continue
        before = None if f.special_from is None else f.special_from - _dt.timedelta(days=1)
        rr = [] if before is None else [r for r in ctx.records("resident_record") if r["roles"]["person"] == pid and covers(r.get("when"), before)]
        pre_household: str | None = None
        if not rr:
            f.problems.append(
                (
                    "事実:第116条の2の入院等の前の住所",
                    Means.FACT,
                    "国保法第116条の2 でみなされる住所の市町村（入院等の前日の住民票の記録〔resident_record〕がない。kokuho_event の when の始まりは入院等の日）",
                )
            )
        else:
            f.note("特例", rr[:1])
            a = rr[0]["attributes"]
            pre_household = a["household_id"]
            if a["municipality_code"] != f.municipality:
                f.deemed_municipality = a["municipality_code"]
        if f.special_household or f.deemed_municipality is None:
            continue
        homes = _parent_homes(ctx, facts, pid, levy_day)
        if not homes:
            continue  # 扶養義務者（親）がほかの世帯にいない：事実の世帯
        if f.admission_type is None:
            f.problems.append(
                (
                    "事実:第116条の2の入院等の種類",
                    Means.FACT,
                    "入院等の種類（kokuho_event の attributes.admission_type。児童福祉施設への措置入所なら、親元の世帯として扱うかが市町村の運用で分かれる）",
                )
            )
            continue
        if f.admission_type != "child_welfare_placement":
            continue
        home = pre_household if pre_household in homes else next(iter(homes)) if len(homes) == 1 else None
        if home is None:
            f.problems.append(
                (
                    "事実:みなされる世帯",
                    Means.FACT,
                    "児童福祉施設に措置入所した子の扶養義務者の世帯（親の世帯が1つに決まらない。kokuho_event の attributes.deemed_household_id に市町村が扱う世帯を書けば決まる）",
                )
            )
            continue
        f.child_home = home
        if home_of(f):
            f.deemed_household = home


def households(ctx: YearContext, facts: Mapping[str, PersonFacts]) -> list[HouseholdPlan]:
    """生存している全員を、国保の世帯に1回ずつ入れる。住民票の世帯がない人は自分だけの世帯。
    第116条でみなされる世帯がある人はその世帯の世帯員（市町村はその世帯のもの）。第116条の2 の人の市町村はみなされる住所の市町村。
    同じ世帯の被保険者で市町村が違う（第116条の2 の住所と世帯の市町村が違う）ときは、その人に分かれ目（一次情報）を付ける。"""
    by_key: dict[str, HouseholdPlan] = {}
    out: list[HouseholdPlan] = []
    for pid in ctx.persons:
        f = facts[pid]
        home = f.deemed_household or f.household
        if home is None:
            out.append(HouseholdPlan(f"solo:{pid}", pid, [pid], f.deemed_municipality or f.municipality))
            continue
        h = by_key.get(home)
        if h is None:
            h = HouseholdPlan(f"hh:{home}", None, [], None)
            by_key[home] = h
            out.append(h)
        h.members.append(pid)
        h.record_ids += f.record_ids.get("世帯", []) + f.record_ids.get("特例", [])
        h.states |= f.states.get("世帯", set()) | f.states.get("特例", set())
        if f.deemed_household is None:
            h.municipality = h.municipality or f.deemed_municipality or f.municipality
            if f.head:
                h.head = pid
    for h in out:
        if h.municipality is None:
            h.municipality = next((facts[m].municipality for m in h.members if facts[m].municipality), None)
        for m in h.members:
            f = facts[m]
            if f.insured and f.deemed_municipality is not None and f.deemed_municipality != h.municipality:
                f.problems.append(
                    (
                        "一次情報:第116条の2の世帯の市町村",
                        Means.PRIMARY_SOURCE,
                        f"国保法第116条の2 でみなされる住所の市町村（{f.deemed_municipality}）と、属する世帯の市町村（{h.municipality}）が違う（賦課の世帯の決め方の一次情報がない）",
                    )
                )
    return out


__all__ = [
    "AUTHORITY_DECISIONS",
    "AUTHORITY_TAX_ITEM",
    "REDUCTION_APPROVED",
    "STUDENT_RECOGNIZED",
    "CHILD_FACT",
    "CHILD_HOME",
    "HouseholdPlan",
    "NHI",
    "PersonFacts",
    "deem_institution",
    "covers",
    "first_march31_on_or_after",
    "fiscal_months",
    "fully_covered",
    "deem_student",
    "households",
    "overlaps",
    "period_of",
    "person_facts",
    "reach_date",
]

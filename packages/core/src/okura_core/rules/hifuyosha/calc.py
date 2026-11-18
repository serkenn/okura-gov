"""規則モジュール hifuyosha の純粋関数（法令の値は持たない。値はパラメータ〔rules/hifuyosha/parameters/健保/〕と注入データから受ける）。

どれも中間表現・OpenFisca を知らない関数で、ユニットテストから直接呼ぶ（tests/rules/hifuyosha/test_calc.py）。
出典は各関数の docstring の docs の節。読み（出典が直接は決めていない箇所）は「読み：」と書き、根拠の印は basis.py に置く。
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

# ---------------------------------------------------------------------------
# 制度（中間表現の medical_insurance.attributes.scheme → パラメータの木の名前）
# ---------------------------------------------------------------------------

#: 被扶養者を持てる制度（SCOPE §5.5：健康保険法の健康保険と、国家公務員・地方公務員・私学の共済）。
DEPENDENT_SCHEMES: Mapping[str, str] = {
    "kyokai_kenpo": "健康保険",
    "health_insurance_society": "健康保険",
    "national_public_servants_mutual_aid": "国家公務員共済",
    "local_public_servants_mutual_aid": "地方公務員共済",
    "private_school_mutual_aid": "私学共済",
}
#: 共済（被扶養者の定義は国共済法・地共済法 第2条第1項第2号。私学は国共済法の準用：docs/public-sources/20261109_round2_kyosai-law-and-criteria.md §1.1）。
KYOSAI: frozenset[str] = frozenset({"国家公務員共済", "地方公務員共済", "私学共済"})
#: 被保険者・組合員であれば被扶養者にならない資格（運用方針 第2条関係 1、厚労省 Q&A A4-1、健保法第3条第7項ただし書の後期高齢者医療：
#: docs/public-sources/20261109_impl-prep_kenpo-dependent-practice.md §4、docs/public-sources/20261109_round2_kyosai-law-and-criteria.md §3.1）。
EXCLUDING_INSURED_SCHEMES: frozenset[str] = frozenset(
    {
        "kyokai_kenpo",
        "health_insurance_society",
        "seamen_insurance",
        "national_public_servants_mutual_aid",
        "local_public_servants_mutual_aid",
        "private_school_mutual_aid",
    }
)
#: 資格の種類を問わず被扶養者にならない制度（後期高齢者医療の被保険者等：健保法第3条第7項ただし書・国共済法第2条第1項第2号の括弧書き）。
EXCLUDING_ANY_SCHEMES: frozenset[str] = frozenset({"late_stage_elderly_medical"})

#: 被扶養者の範囲の親族の区分（概念 健保.被扶養者の範囲の親族か の値）。
NO_COHABITATION = "同居を要しない親族"
COHABITATION = "同居を要する親族"
OUTSIDE = "範囲外"


# ---------------------------------------------------------------------------
# 年齢（年齢計算ニ関スル法律・民法第143条：docs/public-sources/20261109_R1-laws_social-insurance-age-records.md §3。
# 誕生日の前日に加算：docs/public-sources/20261109_impl-prep_kenpo-dependent-practice.md §5.5）
# ---------------------------------------------------------------------------


def _anniversary(birth: _dt.date, years: int) -> _dt.date:
    """生年月日から years 年目の応当日。応当日がない（2月29日生まれ）ときは翌日の3月1日（民法第143条第2項：前日〔2月28日〕に満了）。"""
    try:
        return birth.replace(year=birth.year + years)
    except ValueError:
        return _dt.date(birth.year + years, 3, 1)


def age_on(birth: _dt.date, on: _dt.date) -> int:
    """on の日の年齢（応当日の前日に1つ加わる）。生まれる前は 0。"""
    if on < birth:
        return 0
    age = on.year - birth.year
    while age > 0 and _anniversary(birth, age) - _dt.timedelta(days=1) > on:
        age -= 1
    while _anniversary(birth, age + 1) - _dt.timedelta(days=1) <= on:
        age += 1
    return age


# ---------------------------------------------------------------------------
# 収入の基準額（S52 記1・記2、令和7年7月4日 保発0704第1号・第2号、運用方針 第2条関係 2(3)・文部大臣裁定 3）
# ---------------------------------------------------------------------------

BASE_DEFAULT = "原則"
BASE_YOUNG = "19歳以上23歳未満"
BASE_SENIOR = "60歳以上又は障害者"


@dataclass(frozen=True)
class AgeLimits:
    """年齢の区分（パラメータ 健保.被扶養者の年齢の区分）。"""

    senior_from: int  # 60（以上）
    young_from: int  # 19（以上）
    young_below: int  # 23（未満）


def base_category(age_on_date: int, age_dec31: int, disabled: bool, spouse: bool, limits: AgeLimits, young_applies: bool = True) -> str:
    """基準額の区分。

    - 60歳以上（判定日の年齢。60歳の判定の時点は通知に書かれていない：docs/public-sources/20261109_impl-prep_kenpo-dependent-practice.md §5.5。
      読み：判定日の年齢）又は障害者 → 180万円の区分。
    - 19歳以上23歳未満（判定日の属する年の12月31日現在の年齢。被保険者・組合員の配偶者を除く）→ 150万円の区分
      （docs/public-sources/20261109_R3-tsutatsu_shakaihoken-juminzei.md §1.2）。
    - 19歳以上23歳未満で障害者は 180万円（読み：通知は 130万円の区分だけを 150万円に読み替える。共済は組合の案内 KT-943：
      docs/public-sources/20261109_round3_kyosai-b-ministerial-criteria.md §2.3）。
    - young_applies：判定日が19歳以上23歳未満の区分の適用開始日（2025-10-01）以後か。前なら原則の区分。
    """
    if disabled or age_on_date >= limits.senior_from:
        return BASE_SENIOR
    if young_applies and not spouse and limits.young_from <= age_dec31 < limits.young_below:
        return BASE_YOUNG
    return BASE_DEFAULT


# ---------------------------------------------------------------------------
# 生計維持の比較（S52：docs/public-sources/20261109_R3-tsutatsu_shakaihoken-juminzei.md §1.1）
# ---------------------------------------------------------------------------


def same_household_ok(income: int, insured_income: int, base: int, central_role: bool, ratio: Fraction) -> bool:
    """同一の世帯：年間収入が被保険者の年間収入の ratio（2分の1）未満。以上でも、基準額未満で被保険者の年間収入を上回らず、
    被保険者が世帯の生計維持の中心的役割を果たしていると認められるときは可（S52 記1 のただし書）。"""
    if Fraction(income) < Fraction(insured_income) * ratio:
        return True
    return income < base and income <= insured_income and central_role


#: 別居の仕送りの基準の型（注入点 健保.別居の仕送りの基準 の「型」の値）。
SUPPORT_S52 = "援助による収入額より少ない"
SUPPORT_THIRD = "送金が全収入の3分の1以上"
SUPPORT_EXCEED_OR_THIRD = "送金が本人の収入を超えるか全収入の3分の1以上"
SUPPORT_MONTHLY = "月収10万円未満は月5万円以上・以上は月収の2分の1以上"
SUPPORT_AT_LEAST_AND_MIN = "送金が本人の収入以上かつ年65万円以上"
SUPPORT_TYPES = (SUPPORT_S52, SUPPORT_THIRD, SUPPORT_EXCEED_OR_THIRD, SUPPORT_MONTHLY, SUPPORT_AT_LEAST_AND_MIN)


@dataclass(frozen=True)
class SupportRules:
    """型の中の数値の規則（パラメータ 健保.別居の仕送りの基準。出典：docs/public-sources/20261109_round2_kyosai-separate-address.md §2）。"""

    share_of_total: Fraction  # 全収入に占める送金の割合の下限（3分の1）
    monthly_income_border: int  # 月収の境（10万円）
    monthly_minimum: int  # 月の送金の最低額（5万円）
    monthly_share: Fraction  # 月収に対する送金の割合（2分の1）
    monthly_unit: int  # 必要な送金の額の端数の単位（千円未満切捨て）
    annual_minimum: int  # 年の送金の最低額（65万円）


def support_ok(kind: str, income: int, support: int, other_support: int, insured_income: int, rules: SupportRules) -> bool:
    """同一の世帯に属しない人の仕送りの基準（型ごと）。income は本人の年間収入（仕送りを含まない）、support は被保険者からの援助の年額、
    other_support は被保険者以外の者からの援助の年額。insured_income は被保険者の年間収入（月額の型の上限の検査に使う）。"""
    total = income + support + other_support
    if kind == SUPPORT_S52:
        return income < support
    if kind == SUPPORT_THIRD:
        return Fraction(support) >= Fraction(total) * rules.share_of_total
    if kind == SUPPORT_EXCEED_OR_THIRD:
        return support > income or Fraction(support) >= Fraction(total) * rules.share_of_total
    if kind == SUPPORT_MONTHLY:
        # MIYAGI 基準-10：月収（仕送りを除く）が10万円未満なら月5万円以上、以上なら月収の2分の1以上（千円未満切捨て）。
        # 本人の収入と仕送りの合計が組合員の収入を上回れば該当しない
        monthly_income = Fraction(income, 12)
        monthly_support = Fraction(support, 12)
        if monthly_income < rules.monthly_income_border:
            need = Fraction(rules.monthly_minimum)
        else:
            need = Fraction((monthly_income * rules.monthly_share) // rules.monthly_unit * rules.monthly_unit)
        return monthly_support >= need and income + support <= insured_income
    if kind == SUPPORT_AT_LEAST_AND_MIN:
        # FUKUOKA-KIJUN 第4 4：別居の認定対象者の収入（組合員以外の者からの仕送り等を含む）以上かつ年65万円以上
        return support >= income + other_support and support >= rules.annual_minimum
    raise ValueError(f"知らない仕送りの基準の型: {kind!r}")


@dataclass(frozen=True)
class Livelihood:
    """生計維持の判定の材料（1人分。式 健保_主として被保険者により生計を維持するか と build_inputs が同じ関数を使う）。"""

    income: int  # 年間収入
    base: int  # 収入の基準額
    window: int  # 実績の窓による年額（0 なら窓で超えない）
    same_household: bool
    insured_income: int  # 被保険者の年間収入
    central_role: bool  # 被保険者が世帯の生計維持の中心的役割を果たすか（S52 記1 のただし書）
    support_kind: str  # 別居の仕送りの基準の型
    support: int  # 被保険者からの援助による収入額
    other_support: int  # 被保険者以外の者からの援助
    not_main: bool  # 主たる扶養者でない（夫婦共同扶養・共済の他の者の扶養手当・共同扶養）


def livelihood(x: Livelihood, half: Fraction, rules: SupportRules) -> bool:
    """主として被保険者により生計を維持するか（S52 記1・記2、運用方針 第2条関係 2）。

    年間収入が基準額未満（実績の窓でも超えない）で、同一の世帯なら被保険者の年間収入の2分の1未満（ただし書を含む）、
    同一の世帯でなければ仕送りの基準（型ごと）を満たし、主たる扶養者でないとされないこと。
    """
    if x.not_main or x.income >= x.base or (x.window and x.window >= x.base):
        return False
    if x.same_household:
        return same_household_ok(x.income, x.insured_income, x.base, x.central_role, half)
    return support_ok(x.support_kind or SUPPORT_S52, x.income, x.support, x.other_support, x.insured_income, rules)


# ---------------------------------------------------------------------------
# 夫婦共同扶養（令和3年4月30日 保保発0430第2号・保国発0430第1号：docs/public-sources/20261109_impl-prep_kenpo-dependent-practice.md §3）
# ---------------------------------------------------------------------------

#: 主として生計を維持する者が決まらない（届出が要る）。
KYODO_NEEDS_NOTICE = "届出"


def kyodo_main(
    insured: str,
    spouse: str,
    insured_income: int,
    spouse_income: int,
    spouse_is_employee: bool,
    near_share: Fraction,
    allowance_holder: str | None = None,
) -> str:
    """夫婦の一方 insured の被扶養者として届け出る子について、主として生計を維持する者（insured か spouse）を返す。

    - 共済組合の組合員で扶養手当等の認定を受けている者がいれば、その者（別紙1(3)。「差し支えない」：読み）。
    - 夫婦とも被用者保険：年間収入の多い方。差が多い方の1割（near_share）以内なら届出（KYODO_NEEDS_NOTICE を返す。別紙1(1)(2)）。
    - 一方が国保（spouse_is_employee が偽）：被用者保険の年間収入と、国保の側の直近の年間所得で見込んだ年間収入の多い方（別紙2(1)）。
      同じ額は読み：届け出た側（insured）。
    """
    if allowance_holder in (insured, spouse):
        return allowance_holder  # type: ignore[return-value]
    high = max(insured_income, spouse_income)
    if spouse_is_employee:
        if Fraction(abs(insured_income - spouse_income)) <= Fraction(high) * near_share:
            return KYODO_NEEDS_NOTICE
        return insured if insured_income > spouse_income else spouse
    return insured if insured_income >= spouse_income else spouse


def kyodo_by_remuneration(insured: str, spouse: str, insured_monthly: int, spouse_monthly: int) -> str:
    """夫婦とも被用者保険で、保険者間の協議が整わないとき（別紙1(5)）：初めに届出を受理した保険者等に届出が提出された日の属する月の
    標準報酬月額が高い方。同額なら被保険者の届出（KYODO_NEEDS_NOTICE）。"""
    if insured_monthly == spouse_monthly:
        return KYODO_NEEDS_NOTICE
    return insured if insured_monthly > spouse_monthly else spouse


def kyodo_by_certificate(insured: str, spouse: str, insured_income: int, spouse_income: int) -> str | None:
    """夫婦の一方が国保で、保険者間の協議が整わないとき（別紙2(3)）：直近の課税（非課税）証明書の所得金額が多い方。
    同額の扱いは通知に書かれていない（None：決める手段は一次情報）。"""
    if insured_income == spouse_income:
        return None
    return insured if insured_income > spouse_income else spouse


# ---------------------------------------------------------------------------
# 健保則第37条の3 など（被扶養者の除外：日本の国籍を有しない特定活動の者。
# docs/public-sources/20261109_impl-prep_kenpo-dependent-practice.md §4.1、docs/public-sources/20261109_round2_elderly-abroad-laws.md、
# docs/public-sources/20261109_round2_kyosai-law-and-criteria.md §1.2 の表「除外」：共済の規則も同じ2号）
# ---------------------------------------------------------------------------

#: civil_status.attributes.designated_activity のうち除外に当たる活動（医療を受ける活動等・観光保養等〔1年を超えない滞在〕）。
EXCLUDED_DESIGNATED_ACTIVITIES = frozenset({"medical_care_or_attendance", "sightseeing_or_recreation"})


def excluded_designated_activity(japanese_national: bool | None, activity: str | None) -> bool:
    """日本の国籍を有しない者で、特定活動のうち医療を受ける活動等・観光保養等を行う者か（健保則第37条の3 の2号）。
    特定活動は在留資格（日本の国籍を有しない者だけの資格）なので、国籍の欄が「日本の国籍を有する」と明記されていなければ活動で決める。"""
    return japanese_national is not True and activity in EXCLUDED_DESIGNATED_ACTIVITIES


#: 注入点 健保.給付型の奨学金の扱い の欄と値（貸与型は含めない：K-FAQ 20・MIYAGI 基準-9。給付型は「含まれる場合がある」〔K-FAQ 20〕と
#: 「含まない」〔MIYAGI 基準-9〕：docs/public-sources/20261109_impl-prep_kenpo-dependent-practice.md §1.2、docs/public-sources/20261109_round2_kyosai-law-and-criteria.md §6.2）。
SCHOLARSHIP_FIELD = "給付型の奨学金"
SCHOLARSHIP_INCLUDE = "含む"
SCHOLARSHIP_EXCLUDE = "含まない"


def scholarship_grant_included(rule: Mapping[str, Any]) -> bool:
    """保険者の運用で、給付型の奨学金を年間収入に含めるか。"""
    return rule.get(SCHOLARSHIP_FIELD) == SCHOLARSHIP_INCLUDE


# ---------------------------------------------------------------------------
# 私学共済の「優先する扶養義務者」（組合の案内 PMAC-01：docs/public-sources/20261109_round2_kyosai-law-and-criteria.md §5）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CloserRelative:
    """認定対象者から見て加入者より近い親族等の医療保険の資格（employee：被用者保険〔任意継続を含む〕の被保険者本人、
    nhi：国保の被保険者。income は国保のときの年間収入の見込み〔なければ None〕）。"""

    person: str
    employee: bool
    nhi: bool
    income: int | None = None


def priority_blocks(relatives: Iterable[CloserRelative], member_income: int | None) -> tuple[bool, tuple[str, ...]]:
    """近い親族等の扶養義務が優先して認定できないか（PMAC-01）と、決めるのに年間収入の見込みが要る人。

    被用者保険の被保険者がいれば認定できない。国保なら収入が加入者より多ければ認定できない（収入が分からなければ分からない人として返す）。
    """
    rel = tuple(relatives)
    if any(r.employee for r in rel):
        return True, ()
    unknown: list[str] = []
    for r in rel:
        if not r.nhi:
            continue
        if r.income is None or member_income is None:
            unknown.append(r.person)
        elif r.income > member_income:
            return True, ()
    return False, tuple(unknown)


# ---------------------------------------------------------------------------
# 境目の説明の基準（SCOPE §2-6）
# ---------------------------------------------------------------------------


def ceil_fraction(x: Fraction) -> int:
    return -((-x.numerator) // x.denominator)


def half_threshold(insured_income: int, ratio: Fraction) -> int:
    """同一の世帯の比較の基準の額：被保険者の年間収入 × ratio（2分の1）の1円未満を切り上げた額。
    整数の年間収入 x について「x ＜ 被保険者の年間収入 × ratio」と「x ＜ この額」は同じ（境目の説明の基準。比較は変えない）。"""
    return ceil_fraction(Fraction(insured_income) * ratio)


def support_minimum(kind: str, income: int, other_support: int, rules: SupportRules) -> int:
    """仕送りの基準（型ごと）を満たす被保険者からの援助の年額の下限（この額以上で support_ok の援助の側の条件を満たす）。

    - S52：援助 ＞ 年間収入 → 年間収入＋1。
    - 全収入の3分の1以上：援助 ≥ (年間収入＋援助＋他の援助)×1/3 ⟺ 援助 ≥ (年間収入＋他の援助)×(1/3)/(1−1/3)。
    - 本人の収入を超えるか3分の1以上：上の2つの小さい方。
    - 月額の型：月の必要額×12（「本人の収入と仕送りの合計が被保険者の年間収入以下」の上限の条件は含まない）。
    - 本人の収入以上かつ年65万円以上：max(年間収入＋他の援助, 65万円)。
    """
    third = ceil_fraction((Fraction(income + other_support) * rules.share_of_total) / (1 - rules.share_of_total))
    if kind == SUPPORT_S52:
        return income + 1
    if kind == SUPPORT_THIRD:
        return third
    if kind == SUPPORT_EXCEED_OR_THIRD:
        return min(income + 1, third)
    if kind == SUPPORT_MONTHLY:
        monthly_income = Fraction(income, 12)
        if monthly_income < rules.monthly_income_border:
            need = Fraction(rules.monthly_minimum)
        else:
            need = Fraction((monthly_income * rules.monthly_share) // rules.monthly_unit * rules.monthly_unit)
        return ceil_fraction(need * 12)
    if kind == SUPPORT_AT_LEAST_AND_MIN:
        return max(income + other_support, rules.annual_minimum)
    raise ValueError(f"知らない仕送りの基準の型: {kind!r}")


# ---------------------------------------------------------------------------
# 労働契約の内容による年間収入（令和7年10月1日 保保発1001第3号・年管管発1001第3号、令和8年3月9日 Q&A 第2版：
# docs/public-sources/20261109_R3-tsutatsu_shakaihoken-juminzei.md §1.3、docs/public-sources/20261109_impl-prep_kenpo-dependent-practice.md §1.2・§8 #10）
# ---------------------------------------------------------------------------

#: 1年の週の数（読み：換算式は出典に示されていない〔R8QA2 Q2「時給・労働時間・日数等を用いて算出」〕。52週とする）。
WEEKS_PER_YEAR = 52
MONTHS_PER_YEAR = 12


@dataclass(frozen=True)
class ContractIncome:
    """労働契約から見込んだ年間収入（有理数）。usable が偽なら使えない理由 reason（従来の方法で判定する）。"""

    usable: bool
    amount: Fraction = Fraction(0)
    reason: str = ""


def contract_income(
    amounts: Mapping[str, int],
    attributes: Mapping[str, Any],
    *,
    contract_end: _dt.date | None,
    on: _dt.date,
    commuting_rule: str | None,
    min_years: int,
) -> ContractIncome:
    """労働契約の記載から年間収入を見込む。使えない場合（機構 0501 の (ア)〜(ウ)、R8QA2 Q2-2）は usable=False。

    - 契約期間：判定日（被扶養者になった日）から起算して min_years 年未満で終わる契約は使えない（(ア)）。
    - シフト制など労働時間の記載が不明確なら使えない（(イ)）。
    - 「通勤手当有」等で金額が不明確なら使えない（(ウ)）。実費弁償の形で記載された手当を含まない保険者の運用
      （commuting_rule＝「実費弁償として記載された手当は含まない」：KOURITU-480 別紙2〈その他〉）では、その手当を足さない。
    - 賃金は労働基準法第11条の賃金（諸手当・賞与を含む）。時間外労働の賃金は含まない（R8QA2 Q1・Q2）。
    - 「給与収入のみである」旨の申立てがなければ使えない。
    """
    if not attributes.get("salary_income_only_statement"):
        return ContractIncome(False, reason="「給与収入のみである」旨の申立てがない")
    if contract_end is not None:
        limit = _anniversary(on, min_years) - _dt.timedelta(days=1)
        if contract_end < limit:
            return ContractIncome(False, reason="判定日から起算した契約期間が1年未満")
    if attributes.get("shift_based"):
        return ContractIncome(False, reason="シフト制など労働時間の記載が不明確")
    commuting = amounts.get("monthly_commuting_allowance")
    if attributes.get("commuting_allowance_stated") and commuting is None:
        if not (attributes.get("commuting_allowance_as_reimbursement") and commuting_rule == "実費弁償として記載された手当は含まない"):
            return ContractIncome(False, reason="通勤手当の金額が不明確")
    if attributes.get("bonus_stated") and amounts.get("bonus") is None:
        return ContractIncome(False, reason="賞与の金額が不明確")
    weekly: Fraction | None = None
    if amounts.get("hourly_wage") is not None:
        minutes = attributes.get("scheduled_minutes_per_week")
        if minutes is None:
            return ContractIncome(False, reason="所定労働時間の記載がない")
        weekly = Fraction(amounts["hourly_wage"] * minutes, 60)
    elif amounts.get("daily_wage") is not None:
        days = attributes.get("scheduled_days_per_week")
        if days is None:
            return ContractIncome(False, reason="所定労働日数の記載がない")
        weekly = Fraction(amounts["daily_wage"] * days)
    total = Fraction(0)
    if weekly is not None:
        total += weekly * WEEKS_PER_YEAR
    if amounts.get("monthly_wage") is not None:
        total += Fraction(amounts["monthly_wage"] * MONTHS_PER_YEAR)
    if weekly is None and amounts.get("monthly_wage") is None:
        return ContractIncome(False, reason="賃金の額の記載がない")
    total += Fraction(amounts.get("monthly_allowances", 0) * MONTHS_PER_YEAR)
    if commuting is not None and not (
        attributes.get("commuting_allowance_as_reimbursement") and commuting_rule == "実費弁償として記載された手当は含まない"
    ):
        total += Fraction(commuting * MONTHS_PER_YEAR)
    total += Fraction(amounts.get("bonus", 0))
    return ContractIncome(True, total)


# ---------------------------------------------------------------------------
# 実績の窓（組合の案内：docs/public-sources/20261109_round2_kyosai-law-and-criteria.md §6.4。注入点 健保.年間収入の見込みの型）
# ---------------------------------------------------------------------------


def months_before(on: _dt.date, n: int) -> list[tuple[int, int]]:
    """判定日の属する月の前の n か月（古い順。(年, 月)）。"""
    out: list[tuple[int, int]] = []
    y, m = on.year, on.month
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append((y, m))
    return list(reversed(out))


def window_annual(monthly: Mapping[tuple[int, int], int], on: _dt.date, rule: Mapping[str, Any] | None, any_twelve: bool) -> int:
    """実績の窓による年額換算（0 なら窓の規則で超えない）。基準額と比べる値：

    - 「各月の額」N か月連続：判定日の前の N か月の各月の額の最小 × 12（各月 ≥ 基準額÷12 ⟺ 12×最小 ≥ 基準額）。
    - 「連続する月の平均」：N か月の合計 × 12 ÷ N の切捨て（整数の基準額との比較は切捨てで変わらない）。
    - 任意の連続する12か月（any_twelve）：判定日の前の12か月の合計。
    月の記録が1つもない窓は 0（超えない）。
    """
    best = 0
    if rule:
        n = int(rule["月数"])
        ms = months_before(on, n)
        if all(k in monthly for k in ms):
            values = [monthly[k] for k in ms]
            if rule.get("比べる値") == "連続する月の平均":
                best = max(best, sum(values) * 12 // n)
            else:
                best = max(best, min(values) * 12)
    if any_twelve:
        ms = months_before(on, 12)
        if any(k in monthly for k in ms):
            best = max(best, sum(monthly.get(k, 0) for k in ms))
    return best


def window_after_exception(monthly: Mapping[tuple[int, int], int], on: _dt.date, rule: Mapping[str, Any] | None, any_twelve: bool, excepted: bool) -> int:
    """実績の窓の例外（判断.収入が基準額以上とならないことが明らか が真：excepted）を当てた後の年額換算（2026-11-12。HF-08）。

    例外は月額の連続超過の窓（rule：3か月の平均など）にだけ当て、任意の連続する12か月（any_twelve）の実績は当てたままにする。
    - FUKUOKA-KIJUN 第3 5(1) ただし書：窓で超えても今後1年間の収入が基準額以上とならないことが明らかなら恒常的に超えるとみなさない（any_twelve はない）。
    - 文部科学省共済組合広島大学支部の申立書：3か月平均が月額基準以上でも、どの月から起算した12か月も基準未満の見込みを申し立てれば被扶養者のまま。
      結果的に超えれば取消し（docs/public-sources/20261112_impl-research4_hifuyosha-insurers.md#2）なので、12か月の実績の窓は申立てでも当てる。
    """
    if not excepted:
        return window_annual(monthly, on, rule, any_twelve)
    return window_annual(monthly, on, None, any_twelve)


# ---------------------------------------------------------------------------
# 事業収入から差し引ける経費（注入点 健保.事業収入から差し引ける経費：docs/public-sources/20261109_impl-prep_kenpo-dependent-practice.md §1.2、
# docs/public-sources/20261109_round2_kyosai-law-and-criteria.md §6.3）
# ---------------------------------------------------------------------------

DEDUCT = "差し引ける"
NO_DEDUCT = "差し引けない"
INDIVIDUAL = "保険者が個別に判断"


def expense_treatment(item: str | None, rule: Mapping[str, Any]) -> tuple[str, str | None]:
    """費目 item の扱い（DEDUCT・NO_DEDUCT・INDIVIDUAL と、条件つきなら条件の名前）。item が None は費目が分からない（判断がない）。

    - 方式「費目を限定しない」：全部差し引ける。
    - 方式「費目の表」：認める費目 → 差し引ける、認めない費目 → 差し引けない、条件つきで認める費目 → 条件（呼び出す側が判定）、
      表にない費目 → 注入データの「表にない費目」。書いていなければ保険者が個別に判断（表は例示：K-LEAF「例」）。
    """
    if rule.get("方式") == "費目を限定しない":
        return DEDUCT, None
    if item is None:
        return INDIVIDUAL, None
    if item in rule.get("認める費目", ()):
        return DEDUCT, None
    if item in rule.get("認めない費目", ()):
        return NO_DEDUCT, None
    for cond in rule.get("条件つきで認める費目", ()):
        if item in cond["費目"]:
            return INDIVIDUAL, cond["条件"]
    return rule.get("表にない費目", INDIVIDUAL), None


# ---------------------------------------------------------------------------
# 事業主の証明による一時的な収入増（令和5年10月20日 保保発1020第3号の Q&A、令和7年10月1日 保保発1001第1号：
# docs/public-sources/20261109_R3-tsutatsu_shakaihoken-juminzei.md §1.5、docs/public-sources/20261109_impl-prep_kenpo-dependent-practice.md §1.2）
# ---------------------------------------------------------------------------


def attestation_allowed(dates: Iterable[_dt.date], on: _dt.date, max_consecutive: int, since: _dt.date) -> bool:
    """判定日の確認で事業主の証明を使えるか（原則として連続 max_consecutive 回まで）。

    読み：判定日の前の1年以内（判定日を含む）に証明があることを今回の確認の証明とし、証明の年（暦年）が1年ずつ続く数を連続の回数とする
    （「収入確認を年1回行う場合は、連続する2年間の各年の確認で事業主証明を用いることが連続2回」）。since より前の証明は数えない。
    """
    ds = sorted((d for d in dates if since <= d <= on), reverse=True)
    if not ds or ds[0] < _anniversary(on, -1):
        return False
    years = sorted({d.year for d in ds}, reverse=True)
    count = 1
    for prev, cur in zip(years, years[1:]):
        if prev - cur != 1:
            break
        count += 1
    return count <= max_consecutive


# ---------------------------------------------------------------------------
# 確定申告の年（組合の案内：確定申告の受付締切日 3月15日：docs/public-sources/20261109_round2_kyosai-law-and-criteria.md §6.3）
# ---------------------------------------------------------------------------


def latest_return_year(on: _dt.date) -> int:
    """判定日に「直近の確定申告」の年分（3月15日までは前々年分、3月16日からは前年分。読み）。"""
    return on.year - 1 if on > _dt.date(on.year, 3, 15) else on.year - 2


__all__ = [
    "AgeLimits",
    "BASE_DEFAULT",
    "BASE_SENIOR",
    "BASE_YOUNG",
    "COHABITATION",
    "ContractIncome",
    "DEPENDENT_SCHEMES",
    "KYOSAI",
    "Livelihood",
    "KYODO_NEEDS_NOTICE",
    "NO_COHABITATION",
    "OUTSIDE",
    "SUPPORT_TYPES",
    "SupportRules",
    "age_on",
    "attestation_allowed",
    "base_category",
    "contract_income",
    "expense_treatment",
    "kyodo_main",
    "latest_return_year",
    "livelihood",
    "months_before",
    "same_household_ok",
    "support_ok",
    "window_after_exception",
    "window_annual",
]

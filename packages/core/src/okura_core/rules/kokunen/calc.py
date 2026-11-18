"""規則モジュール kokunen の純粋関数（国民年金：保険料の月額、免除・納付猶予・学生納付特例の所得基準、第3号被保険者）。
OpenFisca を知らない。整数の円と Fraction だけ。

出典（docs/public-sources/20261109_round2_kokuho-premium-structure.md。以下 [KHP]）：
  - 保険料の額（法定額×保険料改定率、5円未満切捨て・5円以上10円未満は10円に切上げ）：[KHP] §11.1・§10
  - 免除・納付猶予・学生納付特例の所得基準：[KHP] §12.1・§12.2・§12.3、学生納付特例：docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md §8.1
  - 第3号被保険者：国民年金法第7条第1項第3号・第5条第7項・附則第3条、国年令第4条（docs/public-sources/20261109_round2_spouse-laws-and-sources.md §5.1）、
    収入の基準（年金局の資料と昭和52年通知の抜粋：docs/public-sources/20261109_round3_dai3go-notice-search.md §3・§3.1）、
    労働契約の内容による判定（令和8年4月以後の認定日：docs/public-sources/20261109_R3-tsutatsu_shakaihoken-juminzei.md §1.3）
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from fractions import Fraction

#: 一部免除の区分（寛大な順）。
四分の三 = "4分の3免除"
半額 = "半額免除"
四分の一 = "4分の1免除"
なし = "なし"
PARTIAL_TIERS = (四分の三, 半額, 四分の一, なし)


def monthly_premium(statutory: int, rate: Fraction) -> int:
    """保険料の月額（国民年金法第87条第3項）：法定額×保険料改定率。5円未満の端数は切り捨て、5円以上10円未満は10円に切り上げる。"""
    x = Fraction(statutory) * rate
    tens = x // 10
    rest = x - tens * 10
    return int(tens * 10 + (10 if rest >= 5 else 0))


def listed_before_carry(dividend: int, gain_or_loss: int, offset: bool) -> int:
    """上場株式等に係る配当所得等・譲渡所得等のうち合計所得金額に入る額（損益通算の後・繰越控除の前）。
    措法第37条の12の2第1項（offset：譲渡損失を配当所得等から控除する旨の記載）。income_totals の合計所得金額と同じ規則
    （docs/public-sources/20261109_round2b_kabu-law-and-nta.md §6。モジュールどうしは import しないので同じ式をここに持つ）。"""
    d = max(dividend, 0)
    g = max(gain_or_loss, 0)
    if offset:
        d -= min(d, max(-gain_or_loss, 0))
    return d + g


def full_exemption_threshold(dependents: int, per_person: int, addition: int) -> int:
    """全額免除・納付猶予の所得の基準額（国年令第6条の7、H16経過令第22条・H26経過令第11条で準用）：(扶養親族等の数＋1)×35万円＋32万円。"""
    return (dependents + 1) * per_person + addition


@dataclass(frozen=True)
class PartialRules:
    """一部免除・学生納付特例の基準額（国年令第6条の8の2・第6条の9・第6条の9の2）。"""

    three_quarters: int
    half: int
    quarter: int


def partial_tier(income: int, addition: int, rules: PartialRules) -> str:
    """一部免除の所得の基準を満たす最も寛大な区分（所得が基準額＋加算額「以下」）。"""
    if income <= rules.three_quarters + addition:
        return 四分の三
    if income <= rules.half + addition:
        return 半額
    if income <= rules.quarter + addition:
        return 四分の一
    return なし


def partial_tier_with_status(income: int, addition: int, rules: PartialRules, status: bool, exempt_income: int, status_limit: int) -> str:
    """一部免除の区分：第90条の2 各項の第1号（一部免除判定所得が基準額＋加算額以下）か、第2号（第90条第1項第3号：地方税法の障害者・寡婦・ひとり親で
    国年令第6条の11 の所得が135万円以下）。第2号に当たれば第1項〜第3項の全部に当たるので最も寛大な区分（H8 の読み(a)）。"""
    if status and exempt_income <= status_limit:
        return 四分の三
    return partial_tier(income, addition, rules)


def stricter(a: str, b: str) -> str:
    """2つの区分のうち寛大でないほう（本人・世帯主・配偶者の全員が満たす区分）。"""
    return PARTIAL_TIERS[max(PARTIAL_TIERS.index(a), PARTIAL_TIERS.index(b))]


# 申請する免除等の所得の基準（2026-11-12。選択.国民年金の免除の申請 C-17）
満たす = "満たす"
満たさない = "満たさない"
前半だけ = "4月〜6月分だけ満たす"
後半だけ = "7月以後の月分だけ満たす"
申請の対象でない = "申請の対象でない（産前産後の免除は法律上当然：第88条の2）"


def applied_criterion(kind: str, full: bool, tier: str, student: bool, student_early: bool, deferral: bool) -> str:
    """申請する種類（inputs.apply_kind の名前）について、その所得の基準を審査される人の全員が満たすか。

    全額免除・一部免除は本人・世帯主・配偶者、納付猶予は本人・配偶者、学生納付特例は本人（各概念の値をそのまま使う）。一部免除は、
    申請する区分の基準額は寛大な区分ほど低い（88万・128万・168万円＋同じ加算額。135万円の経路は全部の区分に当たる）ので、
    満たす最も寛大な区分（一部免除の区分）が申請する区分と同じか寛大なら満たす。学生納付特例の年度の4月〜6月分と7月以後の月分の
    判定が違えば（令和8年度：令和7年政令第355号附則第2条第2項）、どちらの月分だけ満たすかを返す。
    選択がない・申請しない・種類の指定がない・産前産後は、その名前（産前産後は所得の基準を問わない申請の対象でない免除）をそのまま返す。
    """
    if kind == "全額免除":
        return 満たす if full else 満たさない
    if kind in (四分の三, 半額, 四分の一):
        return 満たす if PARTIAL_TIERS.index(tier) <= PARTIAL_TIERS.index(kind) else 満たさない
    if kind == "納付猶予":
        return 満たす if deferral else 満たさない
    if kind == "学生納付特例":
        if student == student_early:
            return 満たす if student else 満たさない
        return 後半だけ if student else 前半だけ
    if kind == "産前産後":
        return 申請の対象でない
    return kind


def dependent_addition(category: str, *, general: int, elderly: int, specified: int) -> int:
    """一部免除・学生納付特例の扶養親族等1人あたりの加算額。category は "特定扶養親族等"・"老人等"・"一般"。"""
    return {"特定扶養親族等": specified, "老人等": elderly, "一般": general}[category]


def chain_addition(
    *,
    dependent: bool,
    age: int,
    deductible: bool,
    specific: bool,
    elderly: bool,
    disabled: bool,
    special: bool,
    general: int,
    elderly_amount: int,
    specific_amount: int,
    disabled_amount: int,
    special_amount: int,
) -> tuple[int, int, int]:
    """扶養の連鎖の人1人の分：(扶養親族等の数, 一部免除の加算額, 一部免除判定所得から差し引く障害者の額)。
    variables.py の扶養所属のグループの式と同じ規則（特定年齢扶養親族は控除対象扶養親族に限る、特定扶養親族等 63万円・老人扶養親族 48万円・その他 38万円、
    障害者 27万円・特別障害者 40万円）を1人に当てる。"""
    if not dependent:
        return 0, 0, 0
    counted = counts_as_dependent(True, age, deductible)
    if not counted:
        n, a = 0, 0
    elif specific or (deductible and age < 19):
        n, a = 1, specific_amount
    elif elderly:
        n, a = 1, elderly_amount
    else:
        n, a = 1, general
    d = special_amount if special else disabled_amount if disabled else 0
    return n, a, d


def counts_as_dependent(is_dependent: bool, age: int, deductible: bool) -> bool:
    """扶養親族等として数えるか（特定年齢扶養親族〔30歳以上70歳未満の扶養親族〕は控除対象扶養親族に限る：国年令第6条の7など）。"""
    if not is_dependent:
        return False
    if 30 <= age < 70:
        return deductible
    return True


def meets_full(income: int, threshold: int, status: bool, status_limit: int) -> bool:
    """全額免除の所得の基準（国民年金法第90条第1項第1号、又は第3号：地方税法の障害者・寡婦・ひとり親で所得が135万円以下）。"""
    return income <= threshold or (status and income <= status_limit)


# ---------------------------------------------------------------------------
# 第3号被保険者
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SpouseSupport:
    """被扶養配偶者の生計維持の材料（判定日）。"""

    income: int
    limit: int
    same_household: bool
    insured_income: int
    support: int
    half: Fraction  # 同一世帯の割合（健保.同一の世帯の収入の割合。kokunen では値を持たない）


def supported_principle(s: SpouseSupport) -> bool:
    """主として第2号被保険者の収入により生計を維持するか（原則の基準。年金局の資料と昭和52年通知の抜粋）。

    同一世帯：年間収入が基準額未満で、かつ第2号被保険者の年間収入の2分の1未満。別世帯：基準額未満で、かつ援助による収入額より少ない。
    """
    if s.income >= s.limit:
        return False
    if s.same_household:
        return Fraction(s.income) < s.half * s.insured_income
    return s.income < s.support


def needs_overall_judgment(s: SpouseSupport) -> bool:
    """同一世帯で2分の1以上だが第2号の年間収入を上回らない（基準額未満）：機構が世帯の生計の状況を総合的に勘案して決める場合。"""
    return s.same_household and s.income < s.limit and not Fraction(s.income) < s.half * s.insured_income and s.income <= s.insured_income


def age_on(birth: _dt.date, on: _dt.date) -> int:
    """on の日の年齢（誕生日の前日に1歳を加える：docs/public-sources/20261109_R1-laws_social-insurance-age-records.md §3）。"""
    n = on.year - birth.year + 1
    while n > 0 and reach_date(birth, n) > on:
        n -= 1
    return n


def reach_date(birth: _dt.date, years: int) -> _dt.date:
    """年齢 years に達する日（誕生日の前日。2月29日生まれは平年の3月1日の前日）。"""
    try:
        anniversary = birth.replace(year=birth.year + years)
    except ValueError:
        anniversary = _dt.date(birth.year + years, 3, 1)
    return anniversary - _dt.timedelta(days=1)


@dataclass(frozen=True)
class LaborContract:
    """労働契約の内容（判定日に有効なもの）。金額が分からないもの（時給・日給だけ）は monthly_wage が None。"""

    monthly_wage: int | None
    monthly_allowances: int
    monthly_commuting: int | None
    commuting_stated: bool
    bonus: int | None
    bonus_stated: bool
    notice: bool
    salary_only: bool
    shift_based: bool
    long_enough: bool


def contract_annual_income(c: LaborContract) -> int | None:
    """労働契約で定められた賃金から見込まれる年間収入（令和8年4月以後の認定日。諸手当・賞与を含む）。
    この取扱いで認定できない契約（労働条件の書面・給与収入のみの申立てがない、シフト制、手当・賞与の金額が不明確、契約期間が1年未満）、
    月額で書かれていない契約（時給・日給からの換算は根拠の資料に方法がない）は None。"""
    if c.monthly_wage is None or not c.notice or not c.salary_only or c.shift_based or not c.long_enough:
        return None
    if c.commuting_stated and c.monthly_commuting is None:
        return None
    if c.bonus_stated and c.bonus is None:
        return None
    return 12 * (c.monthly_wage + c.monthly_allowances + (c.monthly_commuting or 0)) + (c.bonus or 0)


__all__ = [
    "LaborContract",
    "PARTIAL_TIERS",
    "PartialRules",
    "SpouseSupport",
    "age_on",
    "applied_criterion",
    "chain_addition",
    "contract_annual_income",
    "counts_as_dependent",
    "dependent_addition",
    "full_exemption_threshold",
    "listed_before_carry",
    "meets_full",
    "monthly_premium",
    "needs_overall_judgment",
    "partial_tier",
    "partial_tier_with_status",
    "stricter",
    "supported_principle",
]

"""規則モジュール other_deductions の計算の純粋関数（OpenFisca の式とテストの両方が使う）。

金額は整数の円、途中の値は Fraction（packages/core/README.md §5）。丸めは呼び出し側が名前つきの規則で渡す
（rounding.FUNCTIONS の関数、又は basis.py の根拠つきの端数処理）。パラメータの木（OpenFisca の ParameterNodeAtInstant）
から段階の式を読む関数もここに置く（法令の値は parameters/ にだけある）。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from ...money import rate as _rate
from ...rounding import floor_to_unit

Rounder = Callable[[int | Fraction], int]


@dataclass(frozen=True)
class Step:
    """段階の式の1段：支払った金額の合計 x が at_most 以下なら base ＋（x − minus）× ratio。at_most が None なら最後の段（base）。"""

    at_most: int | None
    base: int
    minus: int
    ratio: Fraction


def staged(x: int, steps: Sequence[Step]) -> Fraction:
    """段階の式（所得税法第76条第1項〜第3項の各号、平成18年法律第10号附則第10条第2項第2号）の値。x は0以上。"""
    if type(x) is not int or x < 0:
        raise ValueError("支払った金額の合計は0以上の整数の円")
    for s in steps:
        if s.at_most is None or x <= s.at_most:
            return Fraction(s.base) + (Fraction(x) - s.minus) * s.ratio
    raise ValueError("段階の式の最後の段（上限の額）がない")


def _rate_of(node: Any) -> Fraction:
    return _rate(int(node.分子), int(node.分母))


def steps_from(node: Any) -> tuple[Step, ...]:
    """パラメータの節（イ・ロ・ハ・ニ の号。最初の号は「以下」だけ、途中の号は 以下・加算額・控除する金額・率、最後は「額」）から段階の式を作る。"""
    out: list[Step] = []
    present = set(iter(node))
    for key in ("イ", "ロ", "ハ", "ニ"):
        if key not in present:
            break
        sub = node[key]
        names = set(iter(sub))
        if "額" in names:
            out.append(Step(None, int(sub.額), 0, Fraction(0)))
            break
        if names == {"以下"}:
            out.append(Step(int(sub.以下), 0, 0, Fraction(1)))
            continue
        out.append(Step(int(sub.以下), int(sub.加算額), int(sub.控除する金額), _rate_of(sub.率)))
    if not out or out[-1].at_most is not None:
        raise ValueError("段階の式のパラメータに最後の号（額）がない")
    return tuple(out)


# ---------------------------------------------------------------------------
# 医療費控除（所得税法第73条第1項）とセルフメディケーション税制（租税特別措置法第41条の17第1項の読替え）
# ---------------------------------------------------------------------------


def medical_deduction(
    expense: int, total_income: int, rounder: Rounder, *, rate: Fraction, threshold_cap: int, cap: int
) -> int:
    """医療費控除の額：補塡後の医療費の合計 − min(総所得金額等 × 5%〔円未満は rounder〕, 10万円)、0〜200万円。

    総所得金額等が負なら 5% の額は0（様式の E 欄「赤字のときは0円」：docs/public-sources/20261109_impl-prep_iryohi-nta-mhlw.md §2.2）。
    """
    if expense <= 0:
        return 0
    five = rounder(Fraction(max(total_income, 0)) * rate)
    return min(max(expense - min(five, threshold_cap), 0), cap)


def fraction_matters(expense: int, total_income: int, rate: Fraction, threshold_cap: int) -> bool:
    """総所得金額等の百分の五の1円未満の端数が、医療費控除の額を変えうるか（整数でなく、10万円の上限に届かず、医療費がその額を超える）。"""
    five = Fraction(max(total_income, 0)) * rate
    return expense > 0 and five.denominator != 1 and five < threshold_cap and expense > five.__floor__()


def self_medication_deduction(purchase: int, *, floor: int, cap: int) -> int:
    """特定一般用医薬品等購入費（補塡後）の合計 − 1万2千円、0〜8万8千円（措法第41条の17第1項の読替え）。"""
    return min(max(purchase - floor, 0), cap)


# ---------------------------------------------------------------------------
# 寄附金控除（所得税法第78条第1項）
# ---------------------------------------------------------------------------


def donation_deduction(total: int, total_income: int, rounder: Rounder, *, rate: Fraction, floor: int) -> int:
    """寄附金控除の額：min(特定寄附金の合計, 総所得金額等 × 40%〔円未満は rounder〕) − 2千円（0未満は0）。"""
    if total <= floor:
        return 0
    limit = rounder(Fraction(max(total_income, 0)) * rate)
    return max(min(total, limit) - floor, 0)


def limit_fraction_matters(total: int, total_income: int, rate: Fraction) -> bool:
    """総所得金額等の百分の四十の1円未満の端数が、寄附金控除の額を変えうるか（整数でなく、特定寄附金の合計がその額を超える）。"""
    limit = Fraction(max(total_income, 0)) * rate
    return limit.denominator != 1 and total > limit.__floor__()


# ---------------------------------------------------------------------------
# 生命保険料控除（所得税法第76条、租税特別措置法第41条の15の5）
# ---------------------------------------------------------------------------

#: 新旧の選択（中間表現の 選択.保険料控除の区分 の life_insurance_regime）。
REGIMES = ("new_only", "old_only", "both")


@dataclass(frozen=True)
class LifeRules:
    """生命保険料控除の式（その年分・その人に当てはまる版）。"""

    new_life: tuple[Step, ...]
    old_life: tuple[Step, ...]
    care: tuple[Step, ...]
    new_annuity: tuple[Step, ...]
    old_annuity: tuple[Step, ...]
    general_both_cap: int  # 第1項第3号（措法第41条の15の5 の読替えで6万円）
    annuity_both_cap: int  # 第3項第3号
    total_cap: int  # 第4項


def _pair(new: int, old: int, new_steps: Sequence[Step], old_steps: Sequence[Step], both_cap: int, regime: str, up: Rounder) -> int:
    """一般（又は個人年金）の生命保険料の控除額。新のみ・旧のみ・両方（所法76①一〜三、③一〜三）。

    regime は納税者の選択（質疑応答事例 05/74〜05/76：docs/public-sources/20261109_round2_hoken-kifu-nta-soumu.md §1.4）。
    新のみ・旧のみを選んだら、選ばなかった方の支払は計算に入れない。
    """
    if regime not in REGIMES:
        raise ValueError(f"生命保険料の新旧の選択として知らない値: {regime!r}")
    use_new = new if regime in ("new_only", "both") else 0
    use_old = old if regime in ("old_only", "both") else 0
    a = up(staged(use_new, new_steps)) if use_new > 0 else 0
    b = up(staged(use_old, old_steps)) if use_old > 0 else 0
    if use_new > 0 and use_old > 0:
        return min(a + b, both_cap)  # 第3号：両方を支払った場合
    return a + b


def life_insurance_deduction(
    new_life: int, old_life: int, care: int, new_annuity: int, old_annuity: int, regime: str, rules: LifeRules, up: Rounder
) -> int:
    """生命保険料控除の額（所法76①〜④）。区分ごとの式の1円未満は up で丸める（basis.py の根拠つきの切上げ）。"""
    general = _pair(new_life, old_life, rules.new_life, rules.old_life, rules.general_both_cap, regime, up)
    care_amount = up(staged(care, rules.care)) if care > 0 else 0
    annuity = _pair(new_annuity, old_annuity, rules.new_annuity, rules.old_annuity, rules.annuity_both_cap, regime, up)
    return min(general + care_amount + annuity, rules.total_cap)


def life_rules_from_parameters(p: Any, *, special: bool) -> LifeRules:
    """パラメータの木（所得税.生命保険料控除 の節）から式を作る。special は措法第41条の15の5 を当てるか。"""
    sp = p.措法第41条の15の5
    return LifeRules(
        new_life=steps_from(sp.新生命保険料 if special else p.新生命保険料),
        old_life=steps_from(p.旧生命保険料),
        care=steps_from(p.介護医療保険料),
        new_annuity=steps_from(p.新個人年金保険料),
        old_annuity=steps_from(p.旧個人年金保険料),
        general_both_cap=int(sp.一般の生命保険料の新旧合計の上限 if special else p.一般の生命保険料の新旧合計の上限),
        annuity_both_cap=int(p.個人年金保険料の新旧合計の上限),
        total_cap=int(p.合計の上限),
    )


# ---------------------------------------------------------------------------
# 地震保険料控除（所得税法第77条第1項、平成18年法律第10号附則第10条第2項）
# ---------------------------------------------------------------------------


def earthquake_deduction(quake: int, old_long: int, *, quake_cap: int, old_long_steps: Sequence[Step], total_cap: int, up: Rounder) -> int:
    """地震保険料控除の額。第1号：地震保険料だけ（上限5万円）、第2号：旧長期損害保険料だけ（段階の式）、第3号：両方（合計で5万円）。"""
    a = min(quake, quake_cap) if quake > 0 else 0
    b = up(staged(old_long, old_long_steps)) if old_long > 0 else 0
    if quake > 0 and old_long > 0:
        return min(a + b, total_cap)
    return a + b




# ---------------------------------------------------------------------------
# 雑損控除（所得税法第72条第1項）
# ---------------------------------------------------------------------------


def casualty_carryforward(deduction: int, income: int) -> int:
    """その年分に控除しきれない雑損失の金額（翌年以後に繰り越す額：所法2①二十六・71①）。

    雑損控除は所得控除の最初に（所法87①）、総所得金額・上場株式等の所得・退職所得金額（＝総所得金額等。山林所得は範囲外）から順次控除する
    （所法87②・措通31・32共−4）。控除しきれない額＝雑損控除の額 − 総所得金額等（0未満にしない）。総所得金額等が負なら0として扱う。
    """
    if deduction < 0:
        raise ValueError("雑損控除の額が負")
    return max(deduction - max(income, 0), 0)


def casualty_deduction(loss: int, related: int, total_income: int, rounder: Rounder, *, rate: Fraction, related_limit: int) -> int:
    """雑損控除の額（第1項）：損失の金額の合計額 − 足切りの額（0未満は0）。

    足切りの額：第1号（災害関連支出の金額が5万円以下）は総所得金額等の10分の1、第2号（5万円超）は「損失の金額の合計額 −（災害関連支出のうち5万円を
    超える部分）」と第1号の額のいずれか低い額、第3号（損失の金額がすべて災害関連支出）は5万円と第1号の額のいずれか低い額（10分の1の1円未満の端数は rounder）。
    """
    if loss <= 0:
        return 0
    tenth = rounder(Fraction(max(total_income, 0)) * rate)
    if related <= related_limit:
        threshold = tenth
    elif related < loss:
        threshold = min(loss - (related - related_limit), tenth)
    else:
        threshold = min(related_limit, tenth)
    return max(loss - threshold, 0)


def tenth_fraction_matters(loss: int, related: int, total_income: int, rate: Fraction, related_limit: int) -> bool:
    """総所得金額等の10分の1の1円未満の端数が雑損控除の額を変えうるか（整数でなく、足切りの額に効く場合）。"""
    if loss <= 0:
        return False
    tenth = Fraction(max(total_income, 0)) * rate
    if tenth.denominator == 1:
        return False
    if related <= related_limit:
        return loss > tenth.__floor__()
    if related < loss:
        return (loss - (related - related_limit)) > tenth.__floor__() and loss > tenth.__floor__()
    return related_limit > tenth.__floor__() and loss > tenth.__floor__()


# ---------------------------------------------------------------------------
# 政党等寄附金特別控除等（租税特別措置法第41条の18第2項・第41条の18の2第2項・第41条の18の3第1項）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DonationCreditRules:
    seito_rate: Fraction
    npo_rate: Fraction
    koeki_rate: Fraction
    income_rate: Fraction  # 百分の四十
    floor_amount: int  # 二千円
    tax_rate: Fraction  # 百分の二十五
    unit: int  # 百円未満切捨て


def donation_credit_rules_from_parameters(p: Any) -> DonationCreditRules:
    return DonationCreditRules(
        seito_rate=_rate_of(p.政党等の率),
        npo_rate=_rate_of(p.認定NPO法人等の率),
        koeki_rate=_rate_of(p.公益社団法人等の率),
        income_rate=_rate_of(p.総所得金額等の率),
        floor_amount=int(p.足切り),
        tax_rate=_rate_of(p.税額の上限の率),
        unit=int(p.控除額の端数の単位),
    )


def _credit_before_limit(amount: int, others: int, base: Fraction, rate: Fraction, rules: DonationCreditRules) -> int:
    """控除額（上限の前）：min(その種類の寄附金の額, max(0, 総所得金額等 × 40% − 他の寄附)) − max(0, 2千円 − 他の寄附)、× 率、百円未満切捨て。"""
    b = min(Fraction(amount), max(Fraction(0), base - others))
    d = max(0, rules.floor_amount - others)
    excess = max(Fraction(0), b - d)
    return floor_to_unit(excess * rate, rules.unit)


def donation_credits(
    seito: int, npo: int, koeki: int, special: int, total_income: int, tax: int, rules: DonationCreditRules
) -> tuple[int, int, int]:
    """(公益社団法人等, 認定NPO法人等, 政党等) の特別控除の額（様式の計算順）。

    - 他の寄附（特定寄附金等）：公益は所得控除対象寄附金（special：第78条の特定寄附金のうち公益の税額控除の対象を除いたもの）、
      認定NPOはそれに公益の税額控除の対象を足した額、政党等はさらに認定NPOの税額控除の対象を足した額（各条の定義：seito-kifu §1〜§3）。
    - 限度：その年分の所得税の額（税額控除の前：通達41の18−3）の25%（百円未満切捨て）。認定NPOは公益の控除額を引いた残り、政党等は別枠。
    """
    if min(seito, npo, koeki, special, tax) < 0:
        raise ValueError("寄附金の額・税額は0以上の整数の円")
    base = Fraction(max(total_income, 0)) * rules.income_rate
    limit = floor_to_unit(Fraction(tax) * rules.tax_rate, rules.unit)
    k_before = _credit_before_limit(koeki, special, base, rules.koeki_rate, rules)
    k = min(k_before, limit)
    n_before = _credit_before_limit(npo, special + koeki, base, rules.npo_rate, rules)
    n_limit = floor_to_unit(max(Fraction(0), Fraction(tax) * rules.tax_rate - k), rules.unit)
    n = min(n_before, n_limit)
    s_before = _credit_before_limit(seito, special + koeki + npo, base, rules.seito_rate, rules)
    s = min(s_before, limit)
    return k, n, s


__all__ = [
    "DonationCreditRules",
    "LifeRules",
    "REGIMES",
    "Step",
    "casualty_deduction",
    "donation_credit_rules_from_parameters",
    "donation_credits",
    "donation_deduction",
    "earthquake_deduction",
    "fraction_matters",
    "life_insurance_deduction",
    "life_rules_from_parameters",
    "limit_fraction_matters",
    "medical_deduction",
    "self_medication_deduction",
    "staged",
    "steps_from",
    "tenth_fraction_matters",
]

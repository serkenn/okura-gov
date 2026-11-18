"""住民税への窓口（2026-11-12 の3回目。rules/juminzei/README.md JM-42）：特定支出控除を当てた場合の公的年金等に係る雑所得の金額。

地方税法第313条第11項（住民税の申告書だけで受ける特定支出控除）の前年の所得は「所得税の計算の例」（第313条第2項）で計算するので、公的年金等控除額の区分
（所得税法第35条第4項の公的年金等に係る雑所得以外の合計所得金額：1,000万円・2,000万円）も、特定支出控除を当てた給与所得で求め直す
（docs/public-sources/20261112_impl-research8_tokutei-shishutsu-laws.md §6）。区分の基になる額は income_totals の窓口（rules/income_totals/tokutei.py）。
式は 所得税_公的年金等控除額・所得税_公的年金等に係る雑所得の金額 と同じ関数・パラメータ・端数（手引き 3-2_07 の切捨て）で、区分の基になる額だけを変える
（uncollectible.py・jumin.py と同じ形）。公的年金等の収入のない人は0。
"""

from __future__ import annotations

import numpy as np
from openfisca_core.model_api import YEAR, Variable

from ...country.entities import 人物
from .calc import PENSION_FLOOR, pension_deduction, pension_income, pension_rules

_NENKIN = "docs/public-sources/20261109_round2b_nenkin-laws-and-guidance.md"
_PS8 = "docs/public-sources/20261112_impl-research8_tokutei-shishutsu-laws.md#6"


def _pension(収入: object, 年齢: object, 以外: object, r: object) -> np.ndarray:
    out = [pension_income(int(a), pension_deduction(int(a), int(o), int(g), r), PENSION_FLOOR.apply) for a, o, g in zip(収入, 以外, 年齢)]  # type: ignore[call-overload, arg-type]
    return np.array(out, dtype=np.int32)


class 所得税_特定支出控除を当てた場合の回収不能額等の前の公的年金等に係る雑所得の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "公的年金等控除額の区分を、給与所得を特定支出控除を当てた場合の所得税法第64条第1項の前の額にして求めた公的年金等に係る雑所得の金額"
        "（地方税法第313条第11項の前年の所得の所令180②一の材料：juminzei JM-42）"
    )
    reference = [f"{_NENKIN}#2.1", f"{_NENKIN}#2.2", "docs/public-sources/20261112_impl-research4_shotoku-laws-and-nta.md#1.1", _PS8]

    def formula_2025_01_01(人, period, parameters):
        収入 = 人("所得税_公的年金等の収入金額", period)
        if not np.any(収入 > 0):
            return np.zeros(len(収入), dtype=np.int32)
        年齢 = 人("所得税_年齢", period)
        以外 = 人("所得税_特定支出控除を当てた場合の回収不能額等の前の公的年金等に係る雑所得以外の合計所得金額", period)
        return _pension(収入, 年齢, 以外, pension_rules(parameters(period)))


class 所得税_特定支出控除を当てた場合の公的年金等に係る雑所得の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "公的年金等控除額の区分を、特定支出控除を当てた場合の公的年金等に係る雑所得以外の合計所得金額で求めた公的年金等に係る雑所得の金額（地方税法第313条第11項：JM-42）"
    reference = [f"{_NENKIN}#2.1", f"{_NENKIN}#2.2", _PS8]

    def formula_2025_01_01(人, period, parameters):
        収入 = 人("所得税_公的年金等の収入金額", period)
        if not np.any(収入 > 0):
            return np.zeros(len(収入), dtype=np.int32)
        年齢 = 人("所得税_年齢", period)
        以外 = 人("所得税_特定支出控除を当てた場合の公的年金等に係る雑所得以外の合計所得金額", period)
        return _pension(収入, 年齢, 以外, pension_rules(parameters(period)))


class 所得税_特定支出控除を当てた場合の退職所得を除いた区分による公的年金等に係る雑所得の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "公的年金等控除額の区分を、特定支出控除を当てた場合の退職所得を除いた公的年金等に係る雑所得以外の合計所得金額で求めた公的年金等に係る雑所得の金額"
        "（住民税の分離課税に係る退職所得のある人：JM-23・JM-42）"
    )
    reference = [f"{_NENKIN}#2.1", f"{_NENKIN}#2.2", "docs/public-sources/20261109_round2b_taishoku-laws-and-guidance.md#6.3", _PS8]

    def formula_2025_01_01(人, period, parameters):
        収入 = 人("所得税_公的年金等の収入金額", period)
        if not np.any(収入 > 0):
            return np.zeros(len(収入), dtype=np.int32)
        年齢 = 人("所得税_年齢", period)
        以外 = 人("所得税_特定支出控除を当てた場合の退職所得を除いた公的年金等に係る雑所得以外の合計所得金額", period)
        return _pension(収入, 年齢, 以外, pension_rules(parameters(period)))


VARIABLES = (
    所得税_特定支出控除を当てた場合の回収不能額等の前の公的年金等に係る雑所得の金額,
    所得税_特定支出控除を当てた場合の公的年金等に係る雑所得の金額,
    所得税_特定支出控除を当てた場合の退職所得を除いた区分による公的年金等に係る雑所得の金額,
)

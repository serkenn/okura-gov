"""kyuyo への窓口（2026-11-12。rules/kyuyo/README.md KY-08）：未払の給与の回収不能（所得税法第64条第1項）の上限（施行令第180条第2項第1号）の基礎。

所令180②一の総所得金額は「回収不能額等が生じた時の直前において確定している」額なので、公的年金等控除額の区分（所法35④ の公的年金等に係る雑所得以外の
合計所得金額：1,000万円・2,000万円）も、給与所得を回収不能額等の前の額にして求める（income_totals の 所得税_回収不能額等の前の公的年金等に係る雑所得以外の合計所得金額）。
式は 所得税_公的年金等控除額・所得税_公的年金等に係る雑所得の金額 と同じ関数・パラメータ・端数（手引き 3-2_07 の切捨て）で、区分の基になる額だけを変える。
"""

from __future__ import annotations

import numpy as np
from openfisca_core.model_api import YEAR, Variable

from ...country.entities import 人物
from .calc import PENSION_FLOOR, pension_deduction, pension_income, pension_rules

_NENKIN = "docs/public-sources/20261109_round2b_nenkin-laws-and-guidance.md"


class 所得税_回収不能額等の前の公的年金等に係る雑所得の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "公的年金等控除額の区分を、給与所得を所得税法第64条第1項を当てる前の額にした公的年金等に係る雑所得以外の合計所得金額で求めた公的年金等に係る雑所得の金額（kyuyo KY-08）"
    reference = [f"{_NENKIN}#2.1", f"{_NENKIN}#2.2", "docs/public-sources/20261112_impl-research4_shotoku-laws-and-nta.md#1.1"]

    def formula_2025_01_01(人, period, parameters):
        収入 = 人("所得税_公的年金等の収入金額", period)
        if not np.any(収入 > 0):
            return np.zeros(len(収入), dtype=np.int32)
        年齢 = 人("所得税_年齢", period)
        以外 = 人("所得税_回収不能額等の前の公的年金等に係る雑所得以外の合計所得金額", period)
        r = pension_rules(parameters(period))
        out = [pension_income(int(a), pension_deduction(int(a), int(o), int(g), r), PENSION_FLOOR.apply) for a, o, g in zip(収入, 以外, 年齢)]
        return np.array(out, dtype=np.int32)


VARIABLES = (所得税_回収不能額等の前の公的年金等に係る雑所得の金額,)

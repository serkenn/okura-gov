"""住民税への窓口（2026-11-12。rules/juminzei/README.md JM-23）：公的年金等控除額の区分を、分離課税に係る退職所得を除いて求めた公的年金等に係る雑所得の金額。

住民税の所得の計算は所得税の計算の例による（地方税法第313条第2項）が、公的年金等控除額の区分（所得税法第35条第4項の公的年金等に係る雑所得以外の
合計所得金額：1,000万円・2,000万円）は、分離課税に係る退職所得を除いた住民税の合計所得金額で読む（地方税法施行令第48条の5の2 の読替え：
rules/juminzei/README.md §6）。式は 所得税_公的年金等控除額・所得税_公的年金等に係る雑所得の金額 と同じ関数・パラメータ・端数（手引き 3-2_07 の切捨て）で、
区分の基になる額だけを income_totals の窓口 所得税_退職所得を除いた公的年金等に係る雑所得以外の合計所得金額 にする。
"""

from __future__ import annotations

import numpy as np
from openfisca_core.model_api import YEAR, Variable

from ...country.entities import 人物
from .calc import PENSION_FLOOR, pension_deduction, pension_income, pension_rules

_NENKIN = "docs/public-sources/20261109_round2b_nenkin-laws-and-guidance.md"


class 所得税_退職所得を除いた区分による公的年金等に係る雑所得の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "公的年金等控除額の区分を退職所得を除いた公的年金等に係る雑所得以外の合計所得金額で求めた公的年金等に係る雑所得の金額（住民税への窓口：JM-23）"
    reference = [f"{_NENKIN}#2.1", f"{_NENKIN}#2.2", "docs/public-sources/20261109_round2b_taishoku-laws-and-guidance.md#6.3"]

    def formula_2025_01_01(人, period, parameters):
        収入 = 人("所得税_公的年金等の収入金額", period)
        if not np.any(収入 > 0):
            return np.zeros(len(収入), dtype=np.int32)
        年齢 = 人("所得税_年齢", period)
        以外 = 人("所得税_退職所得を除いた公的年金等に係る雑所得以外の合計所得金額", period)
        r = pension_rules(parameters(period))
        out = [pension_income(int(a), pension_deduction(int(a), int(o), int(g), r), PENSION_FLOOR.apply) for a, o, g in zip(収入, 以外, 年齢)]
        return np.array(out, dtype=np.int32)


VARIABLES = (所得税_退職所得を除いた区分による公的年金等に係る雑所得の金額,)

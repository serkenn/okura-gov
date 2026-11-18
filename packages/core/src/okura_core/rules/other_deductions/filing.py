"""規則モジュール other_deductions：医療費控除の明細書の計算欄の途中の値（2026-11-12。様式の対応表 forms の KOB560-01 の E・F と、
「1 医療費通知に記載された事項」の3欄の入力変数）。

医療費控除の額の式（variables.所得税_医療費控除の額・calc.medical_deduction）と同じ材料・同じ端数の候補で、足切りの額を値として返す：
  E 総所得金額等 × 5%（赤字のときは0円：様式の E 欄。1円未満は根拠のない端数で候補の全部：D22 S3）
  F E と 10万円のいずれか少ない方の金額（所法73①）
"""

from __future__ import annotations

from fractions import Fraction

import numpy as np
from openfisca_core.model_api import YEAR, Variable

from ...country.entities import 人物
from ...money import rate as _rate
from ...rounding import FUNCTIONS

_IRL = "docs/public-sources/20261109_impl-prep_iryohi-law-text.md"
_IRN = "docs/public-sources/20261109_impl-prep_iryohi-nta-mhlw.md"


class 所得税_医療費控除の足切りの基準の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "総所得金額等の百分の五（赤字のときは0。医療費控除の明細書の E。1円未満は根拠のない端数の候補）"
    reference = [f"{_IRL}#1", f"{_IRN}#2.2"]

    def formula_2025_01_01(人, period, parameters):
        p = parameters(period).所得税.医療費控除
        r = _rate(int(p.足切りの率.分子), int(p.足切りの率.分母))
        総所得金額等 = 人("所得税_総所得金額等", period)
        five = [Fraction(max(int(t), 0)) * r for t in 総所得金額等]
        # 根拠のない端数の候補は、端数が出る人がいるときだけ引く（医療費控除の額の式と同じ）
        if any(f.denominator != 1 for f in five):
            候補 = [FUNCTIONS[str(c)] for c in 人("所得税_医療費控除の足切りの端数", period)]
        else:
            候補 = [FUNCTIONS["floor"]] * len(five)
        return np.array([int(f(x)) for x, f in zip(five, 候補)], dtype=np.int64)


class 所得税_医療費控除の足切りの額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "総所得金額等の百分の五と10万円のいずれか少ない方の金額（医療費控除の明細書の F。所法73①）"
    reference = [f"{_IRL}#1", f"{_IRN}#2.2"]

    def formula_2025_01_01(人, period, parameters):
        p = parameters(period).所得税.医療費控除
        return np.minimum(人("所得税_医療費控除の足切りの基準の額", period), int(p.足切りの上限)).astype(np.int64)


_TSUCHI = "docs/public-sources/20261112_impl-research6_forms-iryohi-tsuchi.md"


# 医療費控除の明細書の「1 医療費通知に記載された事項」の3欄（2026-11-12）。入力変数：medical.py が医療費通知（medical_expense_notice）の
# 記録のうち、受診者の要件（支払者自身か生計を一にする親族）を満たすものを支払者ごとに合計する（手引き 6_01 ❶「通知が複数ある場合は、全て合計」）。


class 所得税_医療費通知に記載された医療費の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "医療費控除の明細書に記入する医療費通知に記載された医療費の額（自己負担額。前年支払分を含みうる。支払者ごとの合計）"
    reference = [f"{_TSUCHI}#2", f"{_IRN}#5.2"]


class 所得税_医療費通知のその年中に実際に支払った医療費の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "医療費通知に記載された医療費のうち、その年中に実際に支払った医療費の額（明細書の㋐。支払者ごとの合計）"
    reference = [f"{_TSUCHI}#2", f"{_IRN}#5.2"]


class 所得税_医療費通知の補塡される金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "㋐のうち生命保険や社会保険などで補塡される金額（明細書の㋑。通知の記録ごとに㋐を限度とした額の、支払者ごとの合計）"
    reference = [f"{_TSUCHI}#2", f"{_TSUCHI}#3"]


VARIABLES = (
    所得税_医療費控除の足切りの基準の額,
    所得税_医療費控除の足切りの額,
    所得税_医療費通知に記載された医療費の額,
    所得税_医療費通知のその年中に実際に支払った医療費の額,
    所得税_医療費通知の補塡される金額,
)

"""規則モジュール kyuyo の変数：給与等の収入金額（入力）→ 給与所得の金額。

金額の変数は int（numpy.int32）。有理数の途中の値は変数をまたがせず、式の中の純粋関数（calc.py・rounding.py）で
Fraction のまま計算して、整数の円にしてから返す（float は使わない。docs/measurements/20261109_impl-prep_tools-openfisca-probe.md §6）。
"""

from __future__ import annotations

import numpy as np
from openfisca_core.model_api import YEAR, Variable

from ...country.entities import 人物
from ...money import INT32_MAX
from ...rounding import FUNCTIONS, floor_yen
from .calc import deduction_rules_from_parameters, kyuyo_deduction, kyuyo_shotoku, rules_from_parameters
from .tokutei import FORM_COLUMNS, FORM_ROWS, finish, form_row_variable, needs_rounding, tokutei_raw

_PS8 = "docs/public-sources/20261112_impl-research8_tokutei-shishutsu-laws.md"


def _raws(p, incomes, totals, applies) -> list:  # noqa: ANN001
    """特定支出控除（所法57の2①）を当てた給与所得の金額の有理数（当たらない人は None。tokutei.tokutei_raw）。p は parameters(period)。"""
    if applies is None:
        return [None] * len(incomes)
    rules, drules = rules_from_parameters(p), deduction_rules_from_parameters(p)
    return [tokutei_raw(int(x), int(t), rules, drules) if a else None for x, t, a in zip(incomes, totals, applies)]


def _g_values(p, incomes, raws, candidates) -> list[int]:  # noqa: ANN001
    """給与所得の金額（所法64① を当てる前。特定支出控除を含む：tokutei.finish）。candidates は端数の候補（1円未満の出る人がいなければ None）。"""
    rules = rules_from_parameters(p)
    rounders = [FUNCTIONS[str(c)] for c in candidates] if candidates is not None else [floor_yen] * len(raws)
    values = [kyuyo_shotoku(int(x), rules).value if r is None else finish(r, f) for x, r, f in zip(incomes, raws, rounders)]
    if any(v > INT32_MAX for v in values):
        raise OverflowError("給与所得の金額が int32 の範囲を超える")
    return values


class 所得税_給与等の収入金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "その年中の給与等の収入金額（支払者が複数でも合計。所得税法第28条第4項・措置法第29条の4第2項の「その年中の給与等の収入金額」）"
    reference = [
        "docs/public-sources/20261109_impl-prep_kyuyo-sources.md#1.1",
        "docs/public-sources/20261109_impl-prep_kyuyo-sources.md#4.1",
    ]


class 所得税_給与所得(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "給与所得の金額（所得税法第28条、租税特別措置法第29条の4第2項。所得金額調整控除の前）"
    reference = [
        "docs/public-sources/20261109_impl-prep_kyuyo-sources.md#1",
        "docs/public-sources/20261109_impl-prep_kyuyo-sources.md#2",
        "docs/measurements/20261109_impl-prep_kyuyo-beppyo5.md",
        f"{_PS8}#1",
    ]

    def formula_2025_01_01(人, period, parameters):
        収入 = 人("所得税_給与等の収入金額", period)
        # 特定支出控除（所法57の2①。KY-11、2026-11-12）：適用を受け2分の1を超える人は tokutei の額（1円未満が出るときだけ候補を引く）
        総額 = 人("所得税_特定支出の額の合計額", period)
        適用 = 人("所得税_特定支出控除の適用を受けるか", period) if np.any(総額 > 0) else None
        raws = _raws(parameters(period), 収入, 総額, 適用)
        候補 = 人("所得税_特定支出控除の後の給与所得の端数の候補", period) if any(needs_rounding(r) for r in raws) else None
        values = _g_values(parameters(period), 収入, raws, 候補)
        # 所法64①・所令180②（KY-08）：回収不能額等があれば、令180②一（段が書く上限）と二（差額）のいずれか低い金額を、
        # 給与所得の金額の計算上なかったものとみなす（uncollectible.py の docstring）。回収不能額等のない評価では上限を引かない
        差額 = 人("所得税_回収不能額等に係る給与所得の金額の差額", period)
        if np.any(差額 > 0):
            上限 = 人("所得税_給与の回収不能額等の上限", period)
            values = [v - min(int(d), int(c)) for v, d, c in zip(values, 差額, 上限)]
        return np.array(values, dtype=np.int32)


class 所得税_回収することができないこととなった給与等の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "その年分の給与等の収入金額のうち回収することができないこととなった金額（所得税法第64条第1項の回収不能額等。"
        "未払の給与の uncollectible_amount の合計：inputs.py）"
    )
    reference = ["docs/public-sources/20261112_impl-research4_shotoku-laws-and-nta.md#1"]


class 所得税_回収不能額等に係る給与所得の金額の差額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "所得税法施行令第180条第2項第2号の額：給与所得の金額から、回収不能額等に相当する収入金額がなかったものとした場合の給与所得の金額を控除した残額"
    )
    reference = ["docs/public-sources/20261112_impl-research4_shotoku-laws-and-nta.md#1.1"]

    def formula_2025_01_01(人, period, parameters):
        回収不能 = 人("所得税_回収することができないこととなった給与等の金額", period)
        if not np.any(回収不能 > 0):
            return np.zeros(len(回収不能), dtype=np.int32)
        収入 = 人("所得税_給与等の収入金額", period)
        # 特定支出控除（所法57の2①）を含む給与所得の金額の差（2026-11-12：KY-11）
        総額 = 人("所得税_特定支出の額の合計額", period)
        適用 = 人("所得税_特定支出控除の適用を受けるか", period) if np.any(総額 > 0) else None
        p = parameters(period)
        残り = [max(0, int(s) - int(u)) for s, u in zip(収入, 回収不能)]
        raws_b, raws_a = _raws(p, 収入, 総額, 適用), _raws(p, 残り, 総額, 適用)
        候補 = 人("所得税_特定支出控除の後の給与所得の端数の候補", period) if any(needs_rounding(r) for r in raws_b + raws_a) else None
        before, after = _g_values(p, 収入, raws_b, 候補), _g_values(p, 残り, raws_a, 候補)
        out = [b - a if u > 0 else 0 for b, a, u in zip(before, after, 回収不能)]
        return np.array(out, dtype=np.int32)


class 所得税_所得税法第64条第1項を当てる前の給与所得の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "所得税法第64条第1項（回収不能額等）を当てる前の給与所得の金額（所令180②一の「直前において確定している」総所得金額の基礎。"
        "income_totals の 所得税_回収不能額等の前の総所得金額と退職所得金額の合計額 が使う）"
    )
    reference = ["docs/public-sources/20261109_impl-prep_kyuyo-sources.md#1", "docs/public-sources/20261112_impl-research4_shotoku-laws-and-nta.md#1.1"]

    def formula_2025_01_01(人, period, parameters):
        収入 = 人("所得税_給与等の収入金額", period)
        総額 = 人("所得税_特定支出の額の合計額", period)  # 特定支出控除を含む（KY-11）
        適用 = 人("所得税_特定支出控除の適用を受けるか", period) if np.any(総額 > 0) else None
        raws = _raws(parameters(period), 収入, 総額, 適用)
        候補 = 人("所得税_特定支出控除の後の給与所得の端数の候補", period) if any(needs_rounding(r) for r in raws) else None
        return np.array(_g_values(parameters(period), 収入, raws, 候補), dtype=np.int32)


class 所得税_特定支出の額の合計額が給与所得控除額の2分の1を超えるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = (
        "その年中の特定支出の額の合計額が給与所得控除額（第28条第3項。令和8・9年は措法29の4①）の2分の1に相当する金額を超えるか"
        "（所得税法第57条第1項・地方税法第313条第11項の要件。適用を受けるかの選択によらない）"
    )
    reference = [f"{_PS8}#1", f"{_PS8}#6"]

    def formula_2025_01_01(人, period, parameters):
        総額 = 人("所得税_特定支出の額の合計額", period)
        if not np.any(総額 > 0):
            return np.zeros(len(総額), dtype=bool)
        raws = _raws(parameters(period), 人("所得税_給与等の収入金額", period), 総額, [True] * len(総額))
        return np.array([r is not None for r in raws], dtype=bool)


class 所得税_特定支出控除を当てた場合の給与所得の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "特定支出控除（所得税法第57条の2第1項・措法29の4③）を当てた場合の給与所得の金額（適用を受けるかの選択によらない。2分の1を超えなければ第28条・"
        "措法29の4②の額。所法64① の前）。地方税法第313条第11項（住民税の申告書だけで受ける特定支出控除）の給与所得の計算に juminzei が使う"
    )
    reference = [f"{_PS8}#1", f"{_PS8}#4", f"{_PS8}#6"]

    def formula_2025_01_01(人, period, parameters):
        収入 = 人("所得税_給与等の収入金額", period)
        総額 = 人("所得税_特定支出の額の合計額", period)
        applies = [True] * len(総額) if np.any(総額 > 0) else None
        raws = _raws(parameters(period), 収入, 総額, applies)
        候補 = 人("所得税_特定支出控除の後の給与所得の端数の候補", period) if any(needs_rounding(r) for r in raws) else None
        return np.array(_g_values(parameters(period), 収入, raws, 候補), dtype=np.int32)


class 所得税_特定支出控除を当てた場合の回収不能額等に係る給与所得の金額の差額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "特定支出控除（所得税法第57条の2第1項）を当てた場合の、所得税法施行令第180条第2項第2号の額（特定支出控除を当てた給与所得の金額から、"
        "回収不能額等に相当する収入金額がなかったものとした場合の特定支出控除を当てた給与所得の金額を控除した残額）。地方税法第313条第11項の窓口（juminzei JM-42）"
    )
    reference = [f"{_PS8}#1", f"{_PS8}#6", "docs/public-sources/20261112_impl-research4_shotoku-laws-and-nta.md#1.1"]

    def formula_2025_01_01(人, period, parameters):
        回収不能 = 人("所得税_回収することができないこととなった給与等の金額", period)
        総額 = 人("所得税_特定支出の額の合計額", period)
        if not np.any((回収不能 > 0) & (総額 > 0)):
            return np.zeros(len(回収不能), dtype=np.int32)
        収入 = 人("所得税_給与等の収入金額", period)
        p = parameters(period)
        applies = [True] * len(総額)
        残り = [max(0, int(s) - int(u)) for s, u in zip(収入, 回収不能)]
        raws_b, raws_a = _raws(p, 収入, 総額, applies), _raws(p, 残り, 総額, applies)
        候補 = 人("所得税_特定支出控除の後の給与所得の端数の候補", period) if any(needs_rounding(r) for r in raws_b + raws_a) else None
        before, after = _g_values(p, 収入, raws_b, 候補), _g_values(p, 残り, raws_a, 候補)
        out = [b - a if u > 0 else 0 for b, a, u in zip(before, after, 回収不能)]
        return np.array(out, dtype=np.int32)


class 所得税_給与所得控除後の給与等の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "給与所得控除後の給与等の金額（租税特別措置法第41条の3の11第4項第5号：給与等の収入金額から第28条第3項の給与所得控除額を控除した残額。"
        "第28条第4項〔別表第五〕・令和8年分以後は措令第19条の4の2〔措法29の4② の額〕を含む。特定支出控除・所法64① の前）"
    )
    reference = [f"{_PS8}#5", "docs/public-sources/20261109_round2_gaps-sources.md#3.1", "docs/public-sources/20261109_round2_gaps-sources.md#3.3"]

    def formula_2025_01_01(人, period, parameters):
        収入 = 人("所得税_給与等の収入金額", period)
        rules = rules_from_parameters(parameters(period))
        values = [kyuyo_shotoku(int(x), rules).value for x in 収入]
        if any(v > INT32_MAX for v in values):
            raise OverflowError("給与所得控除後の給与等の金額が int32 の範囲を超える")
        return np.array(values, dtype=np.int32)


class 所得税_特定支出の額の合計額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "その年中の特定支出の額の合計額（所得税法第57条の2第1項・第2項。specific_expense から inputs.py が組み立てる入力）"
    reference = [f"{_PS8}#1", f"{_PS8}#2", f"{_PS8}#3"]


class 所得税_特定支出控除の適用を受けるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "その年分の申告書等に特定支出控除の適用を受ける旨を記載し、明細書と証明書を添付するか（所得税法第57条の2第3項。選択.特定支出控除）"
    reference = [f"{_PS8}#1", f"{_PS8}#7.1"]


class 所得税_特定支出控除の後の給与所得の端数の候補(Variable):
    value_type = str
    entity = 人物
    definition_period = YEAR
    label = "特定支出控除を当てた給与所得の金額の1円未満の端数の候補（根拠のない端数：evaluate が floor・ceil・half_up を入れる。D21 R5・D22 S3）"
    reference = [f"{_PS8}#9"]


_PS9 = "docs/public-sources/20261112_impl-research9_tokutei-jumin-sources.md"


def _form_input(name: str, label: str, value_type: type = int) -> type:
    return type(
        name,
        (Variable,),
        {"value_type": value_type, "entity": 人物, "definition_period": YEAR, "label": label, "reference": [f"{_PS9}#5.2", f"{_PS8}#1"], "__module__": __name__},
    )


#: 給与所得者の特定支出に関する明細書（KOB070）の欄の材料（2026-11-12 の3回目。inputs.py の _tokutei_inputs が tokutei.collect から書く入力。様式の対応表 forms が写す）
FORM_VARIABLES: tuple[type, ...] = tuple(
    _form_input(form_row_variable(k, col), f"給与所得者の特定支出に関する明細書の区分の行{k}（{row}）の{col}（政令の範囲・上限の後。KY-11）")
    for k, (row, _, _) in enumerate(FORM_ROWS, start=1)
    for col in FORM_COLUMNS
) + (
    _form_input("所得税_特定支出に関する明細書の勤務必要経費の小計", "給与所得者の特定支出に関する明細書の ⑩ 小計（図書費・衣服費・交際費等の差引金額の和。65万円まで：所法57の2②七）"),
    _form_input(
        "所得税_適用を受ける特定支出の区分の合計",
        "給与所得者の特定支出に関する明細書の ⑫ 適用を受ける特定支出の区分の合計（差引金額が正の区分の区分番号の和を10進の文字列で。第一表 ⑥ の区分 G16）",
        str,
    ),
)


class 所得税_給与の回収不能額等の上限(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "所得税法施行令第180条第2項第1号の額：回収不能額等が生じた時の直前において確定している総所得金額・退職所得金額（山林所得は範囲外）の合計額"
        "（段 未払の給与の回収不能 が income_totals の値を写す入力。回収不能額等のない人は0）"
    )
    reference = ["docs/public-sources/20261112_impl-research4_shotoku-laws-and-nta.md#1.1", "docs/public-sources/20261112_impl-research4_shotoku-laws-and-nta.md#1.3"]


class 所得税_給与所得控除額の端数の候補(Variable):
    value_type = str
    entity = 人物
    definition_period = YEAR
    label = "給与所得控除額の1円未満の端数の候補（根拠のない端数：evaluate が floor・ceil・half_up を入れる。D21 R5・D22 S3）"
    reference = ["docs/public-sources/20261109_impl-prep_kyuyo-sources.md#1.1"]


class 所得税_給与所得控除額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "給与所得控除額（所得税法第28条第3項・租税特別措置法第29条の4第1項。第28条第2項に規定するもの）"
    reference = [
        "docs/public-sources/20261109_impl-prep_kyuyo-sources.md#2.1",
        "docs/public-sources/20261109_impl-prep_kyuyo-sources.md#2.4",
    ]

    def formula_2025_01_01(人, period, parameters):
        収入 = 人("所得税_給与等の収入金額", period)
        rules = deduction_rules_from_parameters(parameters(period))
        details = [kyuyo_deduction(int(x), rules) for x in 収入]
        if any(d.amount.denominator != 1 for d in details):  # 端数が出ないなら候補に依存しない
            funcs = [FUNCTIONS[str(c)] for c in 人("所得税_給与所得控除額の端数の候補", period)]
        else:
            funcs = [floor_yen] * len(details)
        values = [f(d.amount) for d, f in zip(details, funcs)]
        if any(v > INT32_MAX for v in values):
            raise OverflowError("給与所得控除額が int32 の範囲を超える")
        return np.array(values, dtype=np.int32)


VARIABLES = (
    所得税_給与等の収入金額,
    所得税_給与所得控除後の給与等の金額,
    所得税_特定支出の額の合計額,
    所得税_特定支出控除の適用を受けるか,
    所得税_特定支出控除の後の給与所得の端数の候補,
    所得税_特定支出の額の合計額が給与所得控除額の2分の1を超えるか,
    所得税_特定支出控除を当てた場合の給与所得の金額,
    所得税_特定支出控除を当てた場合の回収不能額等に係る給与所得の金額の差額,
    所得税_給与所得,
    所得税_給与所得控除額の端数の候補,
    所得税_給与所得控除額,
    所得税_回収することができないこととなった給与等の金額,
    所得税_回収不能額等に係る給与所得の金額の差額,
    所得税_所得税法第64条第1項を当てる前の給与所得の金額,
    所得税_給与の回収不能額等の上限,
) + FORM_VARIABLES

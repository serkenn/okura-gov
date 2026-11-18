"""規則モジュール tax の変数：所得控除の合計 → 課税所得 → 税額 → 精算・申告の要否・期限。

金額の変数は int（numpy.int32）。途中の値は式の中の純粋関数（calc.py）で Fraction のまま計算し、整数の円にしてから返す
（float は使わない）。式は上流の変数を名前で引く（まだない上流の概念は仮置きの変数が受ける：packages/core/README.md §10）。
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Mapping
from typing import Any

import numpy as np
from openfisca_core.model_api import YEAR, Variable

from ...country.entities import 人物
from ...money import INT32_MAX
from ...rounding import FUNCTIONS
from .calc import (
    FUKKO_ROUNDING_YEARS,
    Calendar,
    CalendarUnknown,
    PensionFacts,
    RetirementFacts,
    SalaryFacts,
    Obligation,
    allocate_deductions,
    brackets_from_parameters,
    business_credit_category,
    calendar_from_parameters,
    death_deadline,
    deduct_credits,
    dividend_credit,
    dividend_credit_computed,
    dividend_credit_rules_from_parameters,
    filing_obligation,
    fukko_tax,
    housing_credit_category,
    normal_deadline,
    progressive_tax,
    rate_of,
    refund_amount,
    shinkoku_nozei,
    shinkoku_nozei_field,
    third_installment,
)
from .inputs import KIND_DEATH, KIND_DEATH_NEXT_YEAR, KIND_DEPARTURE, KIND_NORMAL, NO_DATE

#: 期限が一次情報で決まらない（暦要項が未発表の暦年にかかる）ときに式が返す日。checks.py が対象外にする（結果には出ない）。
UNKNOWN_DEADLINE = _dt.date(9999, 12, 31)

_DOCS = "docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md"
_R121 = "docs/public-sources/20261111_impl-research_121-laws-and-nta.md#1"
_HAITO = "docs/public-sources/20261111_impl-research_haito-laws-and-nta.md"


def _yen(values: list[int], what: str) -> np.ndarray:
    if any(v < 0 or v > INT32_MAX for v in values):
        raise OverflowError(f"{what}が 0〜int32 の範囲の外")
    return np.array(values, dtype=np.int32)


# ---------------------------------------------------------------------------
# 事実（入力変数。inputs.py が中間表現から作る）
# ---------------------------------------------------------------------------


class 所得税_源泉徴収税額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "源泉徴収税額（所得税及び復興特別所得税の合計。この版は給与の支払の記録だけから作る）"
    reference = [f"{_DOCS}#4.1", f"{_DOCS}#3.1"]


class 所得税_予定納税額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "予定納税額（第1期・第2期の合計。予定納税の通知書の合計額）"
    reference = [f"{_DOCS}#4.3"]


class 所得税_住宅借入金等特別控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "住宅借入金等特別控除の額（外部で計算した額）"
    reference = [f"{_DOCS}#5.1"]


_CREDITS = "docs/public-sources/20261112_impl-research6_forms-tax-credits.md"


class 所得税_事業所得等の特例に係る税額控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "事業所得等の特例に係る税額控除の額（第一表 ㉞ の投資税額等。外部で計算した額：external_tax_credit の business_income_special）"
    reference = [f"{_CREDITS}#2"]


class 所得税_住宅耐震改修特別控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "住宅耐震改修特別控除の額（外部で計算した額：external_tax_credit の seismic_retrofit）"
    reference = [f"{_CREDITS}#3"]


class 所得税_住宅特定改修特別税額控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "住宅特定改修特別税額控除の額（外部で計算した額：external_tax_credit の specified_housing_renovation）"
    reference = [f"{_CREDITS}#3"]


class 所得税_認定住宅等新築等特別税額控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "認定住宅等新築等特別税額控除の額（外部で計算した額：external_tax_credit の certified_housing_new_build）"
    reference = [f"{_CREDITS}#3"]


class 所得税_申告の種類(Variable):
    value_type = str
    entity = 人物
    definition_period = YEAR
    label = "確定申告書の種類（期限の規定：第120条・第125条・第125条で知った日が決まらない・出国又は非居住者）"
    reference = ["docs/public-sources/20261109_round3_shibo-shukkoku-laws-and-nta.md#2.1"]


class 所得税_相続の開始があったことを知った日(Variable):
    value_type = _dt.date
    entity = 人物
    definition_period = YEAR
    label = "相続の開始があったことを知った日（年の中途で死亡した人について、相続人等の記録から。申告の種類が第125条の人だけが使う）"
    reference = ["docs/public-sources/20261109_round3_shibo-shukkoku-laws-and-nta.md#2.1"]


class 所得税_出国の日(Variable):
    value_type = _dt.date
    entity = 人物
    definition_period = YEAR
    label = "「出国」（納税管理人の届出をしないで国内に住所及び居所を有しないこととなること）の日（申告の種類が出国の人だけが使う）"
    reference = ["docs/public-sources/20261109_round3_shibo-shukkoku-laws-and-nta.md#3.1"]


class 所得税_給与等の支払者の数(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "その年中に給与等の支払を受けた支払者の数（第121条第1項第1号・第2号の区分）"
    reference = [_R121]


class 所得税_給与等の全部が源泉徴収の対象か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "給与等の全部について第183条・第190条の規定による所得税の徴収をされた又はされるべきか（源泉徴収税額の欄が記録にあるか）"
    reference = [_R121]


class 所得税_給与等の全部が年末調整の対象か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "給与等の全部について第190条（年末調整）の規定が適用されるか（基通121−4：源泉徴収票の year_end_adjusted）"
    reference = [_R121]


class 所得税_従たる給与等の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "第195条第1項の従たる給与等の支払者から支払を受ける給与等の金額（源泉徴収票の secondary_column）"
    reference = [_R121]


class 所得税_従たる給与等の金額が分かるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "給与の支払者ごとの源泉徴収票の記載から従たる給与等の金額を決められるか"
    reference = [_R121]


class 所得税_公的年金等の全部が源泉徴収の対象か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "公的年金等の全部について第203条の2 の規定による所得税の徴収をされた又はされるべきか（源泉徴収税額の欄が記録にあるか）"
    reference = [_R121, "docs/public-sources/20261109_round2b_nenkin-laws-and-guidance.md#6"]


class 所得税_退職手当等の全部が源泉徴収の対象か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "退職手当等の全部について第199条・第201条第1項の規定による所得税の徴収をされた又はされるべきか（退職所得の受給に関する申告書の提出と源泉徴収税額の欄）"
    reference = [_R121, "docs/public-sources/20261109_round2b_taishoku-laws-and-guidance.md#4.1"]


class 所得税_退職手当等の源泉徴収税額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "退職手当等の源泉徴収税額の合計（第121条第2項第2号：課税退職所得金額に係る税額と比べる）"
    reference = [_R121, "docs/public-sources/20261109_round2b_taishoku-laws-and-guidance.md#4.1"]


class 所得税_給与等が第121条第1項の適用除外か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = (
        "第121条第1項（給与所得者の確定申告不要）を適用しない給与等の支払を受けたか（基通121−5(1)(3)：家事使用人のみに支払う者・国外の支払、"
        "所令262の2：同族会社の役員等がその支払者から貸付金の利子・資産の対価などを受ける）"
    )
    reference = [f"{_R121.split('#')[0]}#2", f"{_R121.split('#')[0]}#3"]


class 所得税_年末調整で控除された住宅借入金等特別控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "年末調整で租税特別措置法第41条の2の2第1項により控除された住宅借入金等特別控除の額（所得税法第120条第1項の比較で配当控除の額に加える：措法41の2の2⑥二）"
    reference = ["docs/public-sources/20261111_impl-research3_joto-junjo-laws-and-nta.md#4"]


class 所得税_上場株式等の所得控除の順序(Variable):
    value_type = str
    entity = 人物
    definition_period = YEAR
    label = "所得控除を上場株式等に係る配当所得等・譲渡所得等の金額に当てる順序（措通31・32共−4 の順か、ただし書の納税者の選択）"
    reference = ["docs/public-sources/20261111_impl-research3_joto-junjo-laws-and-nta.md#3"]


class 所得税_復興特別所得税額の端数の候補(Variable):
    value_type = str
    entity = 人物
    definition_period = YEAR
    label = "復興特別所得税額の1円未満の端数の候補の名前（根拠のない端数の候補評価。evaluate が入れる）"
    reference = [f"{_DOCS}#3.3", f"{_DOCS}#11"]


# ---------------------------------------------------------------------------
# 所得控除の合計・課税所得
# ---------------------------------------------------------------------------


class 所得税_所得控除の合計(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "所得控除の額の合計（所得税法第87条。集約点）"
    reference = [f"{_DOCS}#1.1"]

    def formula_2025_01_01(人, period, parameters):
        parts = [
            人("所得税_雑損控除の額", period),
            人("所得税_医療費控除の額", period),
            人("所得税_セルフメディケーション税制による医療費控除の額", period),
            人("所得税_社会保険料控除の額", period),
            人("所得税_小規模企業共済等掛金控除の額", period),
            人("所得税_生命保険料控除の額", period),
            人("所得税_地震保険料控除の額", period),
            人("所得税_寄附金控除の額", period),
            人("所得税_障害者控除の額", period),
            人("所得税_寡婦控除の額", period),
            人("所得税_ひとり親控除の額", period),
            人("所得税_勤労学生控除の額", period),
            人("所得税_配偶者控除の額", period),
            人("所得税_配偶者特別控除の額", period),
            人("所得税_扶養控除の額", period),
            人("所得税_特定親族特別控除の額", period),
            人("所得税_基礎控除の額", period),
        ]
        total = [sum(int(a[i]) for a in parts) for i in range(len(parts[0]))]
        return _yen(total, "所得控除の合計")


def _allocation(総所得, 配当, 譲渡, 退職, 控除, unit) -> list:  # noqa: ANN001
    return [
        allocate_deductions(int(a), int(b), int(c), int(d), int(e), unit) for a, b, c, d, e in zip(総所得, 配当, 譲渡, 退職, 控除)
    ]


def _reorder(out: list, 総所得, 配当, 譲渡, 控除, 順序, unit) -> list:  # noqa: ANN001
    """2つの順序で結果が違う人だけ、選んだ順序（措通31・32共−4 の順か、ただし書の納税者の選択）で割り振り直す。"""
    return [
        allocate_deductions(int(a), int(b), int(c), 0, int(e), unit, str(o)) if x.stock_order_matters else x
        for a, b, c, e, o, x in zip(総所得, 配当, 譲渡, 控除, 順序, out)
    ]


class 所得税_課税総所得金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "課税総所得金額（総所得金額から所得控除を控除した残額。千円未満切捨て）"
    reference = [f"{_DOCS}#1.1", f"{_DOCS}#1.2"]

    def formula_2025_01_01(人, period, parameters):
        総所得 = 人("所得税_総所得金額", period)
        控除 = 人("所得税_所得控除の合計", period)
        unit = parameters(period).所得税.端数計算.課税標準の単位
        zero = [0] * len(総所得)
        return _yen([a.総所得 for a in _allocation(総所得, zero, zero, zero, 控除, unit)], "課税総所得金額")


class 所得税_課税退職所得金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "課税退職所得金額（総所得金額・上場株式等に係る所得で控除しきれない所得控除を退職所得金額から控除した残額。千円未満切捨て）"
    reference = [f"{_DOCS}#1.1", "docs/public-sources/20261109_round2b_taishoku-laws-and-guidance.md#4.1"]

    def formula_2025_01_01(人, period, parameters):
        総所得 = 人("所得税_総所得金額", period)
        配当 = 人("所得税_申告分離課税の上場株式等に係る配当所得等の金額", period)
        譲渡 = 人("所得税_申告分離課税の上場株式等に係る譲渡所得等の金額", period)
        退職 = 人("所得税_退職所得金額", period)  # 所法22③・89②：損益通算・繰越控除の後（所得の種類の「退職所得の金額」ではない）
        控除 = 人("所得税_所得控除の合計", period)
        unit = parameters(period).所得税.端数計算.課税標準の単位
        return _yen([a.退職 for a in _allocation(総所得, 配当, 譲渡, 退職, 控除, unit)], "課税退職所得金額")


class 所得税_上場株式等に係る課税配当所得等の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "上場株式等に係る課税配当所得等の金額（千円未満切捨て）"
    reference = ["docs/public-sources/20261109_round2b_kabu-law-and-nta.md#1.1", "docs/public-sources/20261109_round2b_kabu-law-and-nta.md#1.3"]

    def formula_2025_01_01(人, period, parameters):
        総所得 = 人("所得税_総所得金額", period)
        配当 = 人("所得税_申告分離課税の上場株式等に係る配当所得等の金額", period)
        譲渡 = 人("所得税_申告分離課税の上場株式等に係る譲渡所得等の金額", period)
        控除 = 人("所得税_所得控除の合計", period)
        unit = parameters(period).所得税.端数計算.課税標準の単位
        out = _allocation(総所得, 配当, 譲渡, [0] * len(総所得), 控除, unit)
        if any(a.stock_order_matters for a in out):  # 2つの順序で結果が違う人がいるときだけ順序の選択を引く
            out = _reorder(out, 総所得, 配当, 譲渡, 控除, 人("所得税_上場株式等の所得控除の順序", period), unit)
        return _yen([a.配当 for a in out], "上場株式等に係る課税配当所得等の金額")


class 所得税_上場株式等に係る課税譲渡所得等の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "上場株式等に係る課税譲渡所得等の金額（千円未満切捨て）"
    reference = ["docs/public-sources/20261109_round2b_kabu-law-and-nta.md#4"]

    def formula_2025_01_01(人, period, parameters):
        総所得 = 人("所得税_総所得金額", period)
        配当 = 人("所得税_申告分離課税の上場株式等に係る配当所得等の金額", period)
        譲渡 = 人("所得税_申告分離課税の上場株式等に係る譲渡所得等の金額", period)
        控除 = 人("所得税_所得控除の合計", period)
        unit = parameters(period).所得税.端数計算.課税標準の単位
        out = _allocation(総所得, 配当, 譲渡, [0] * len(総所得), 控除, unit)
        if any(a.stock_order_matters for a in out):  # 2つの順序で結果が違う人がいるときだけ順序の選択を引く
            out = _reorder(out, 総所得, 配当, 譲渡, 控除, 人("所得税_上場株式等の所得控除の順序", period), unit)
        return _yen([a.譲渡 for a in out], "上場株式等に係る課税譲渡所得等の金額")


# ---------------------------------------------------------------------------
# 税額
# ---------------------------------------------------------------------------


class 所得税_課税総所得金額に対する税額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "課税総所得金額に対する所得税の額（所得税法第89条第1項の超過累進税率）"
    reference = [f"{_DOCS}#2"]

    def formula_2025_01_01(人, period, parameters):
        課税 = 人("所得税_課税総所得金額", period)
        brackets = brackets_from_parameters(parameters(period).所得税.税率)
        return _yen([progressive_tax(int(x), brackets)[0] for x in 課税], "課税総所得金額に対する税額")


class 所得税_課税退職所得金額に対する税額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "課税退職所得金額に対する所得税の額（所得税法第89条第1項）"
    reference = [f"{_DOCS}#2", "docs/public-sources/20261109_round2b_taishoku-laws-and-guidance.md#4.1"]

    def formula_2025_01_01(人, period, parameters):
        課税 = 人("所得税_課税退職所得金額", period)
        brackets = brackets_from_parameters(parameters(period).所得税.税率)
        return _yen([progressive_tax(int(x), brackets)[0] for x in 課税], "課税退職所得金額に対する税額")


def _flat_tax(base, rate, what: str) -> np.ndarray:  # noqa: ANN001
    out = []
    for x in base:
        t = int(x) * rate
        if t.denominator != 1:
            raise ValueError(f"{what}が整数にならない（課税標準の千円未満の切捨てか率を確かめる）")
        out.append(int(t))
    return _yen(out, what)


class 所得税_上場株式等に係る課税配当所得等の金額に対する税額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "上場株式等に係る課税配当所得等の金額に対する所得税の額（百分の十五）"
    reference = ["docs/public-sources/20261109_round2b_kabu-law-and-nta.md#1.1"]

    def formula_2025_01_01(人, period, parameters):
        課税 = 人("所得税_上場株式等に係る課税配当所得等の金額", period)
        率 = rate_of(parameters(period).所得税.分離課税の税率.上場株式等に係る課税配当所得等の金額, "上場株式等の配当所得等の税率")
        return _flat_tax(課税, 率, "上場株式等に係る課税配当所得等の金額に対する税額")


class 所得税_上場株式等に係る課税譲渡所得等の金額に対する税額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "上場株式等に係る課税譲渡所得等の金額に対する所得税の額（百分の十五）"
    reference = ["docs/public-sources/20261109_round2b_kabu-law-and-nta.md#4"]

    def formula_2025_01_01(人, period, parameters):
        課税 = 人("所得税_上場株式等に係る課税譲渡所得等の金額", period)
        率 = rate_of(parameters(period).所得税.分離課税の税率.上場株式等に係る課税譲渡所得等の金額, "上場株式等の譲渡所得等の税率")
        return _flat_tax(課税, 率, "上場株式等に係る課税譲渡所得等の金額に対する税額")


class 所得税_算出税額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "算出税額（税額控除の前の所得税の額の合計。所得税法第21条第1項第4号）"
    reference = [f"{_DOCS}#1.1"]

    def formula_2025_01_01(人, period, parameters):
        a = 人("所得税_課税総所得金額に対する税額", period)
        b = 人("所得税_課税退職所得金額に対する税額", period)
        c = 人("所得税_上場株式等に係る課税配当所得等の金額に対する税額", period)
        d = 人("所得税_上場株式等に係る課税譲渡所得等の金額に対する税額", period)
        return _yen([int(w) + int(x) + int(y) + int(z) for w, x, y, z in zip(a, b, c, d)], "算出税額")


class 所得税_配当控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "配当控除の額（所得税法第92条・租税特別措置法第9条第3項・第4項。総合課税の配当所得の金額を剰余金の配当等・証券投資信託・一般外貨建等証券投資信託の"
        "区分ごとに income_kinds から受け、課税総所得金額等で区分する。1円未満は切捨て、限度は算出税額）"
    )
    reference = [f"{_HAITO}#2", f"{_HAITO}#3", f"{_HAITO}#3.1", f"{_HAITO}#4", f"{_DOCS}#1.1"]

    def formula_2025_01_01(人, period, parameters):
        a = 人("所得税_配当控除の対象の剰余金の配当等に係る配当所得の金額", period)
        b = 人("所得税_配当控除の対象の証券投資信託の収益の分配に係る配当所得の金額", period)
        c = 人("所得税_配当控除の対象の一般外貨建等証券投資信託の収益の分配に係る配当所得の金額", period)
        if not ((a > 0) | (b > 0) | (c > 0)).any():
            return np.zeros(len(a), dtype=np.int32)
        課税 = 人("所得税_課税総所得金額", period)
        配当課税 = 人("所得税_上場株式等に係る課税配当所得等の金額", period)
        譲渡課税 = 人("所得税_上場株式等に係る課税譲渡所得等の金額", period)
        算出 = 人("所得税_算出税額", period)
        rules = dividend_credit_rules_from_parameters(parameters(period).所得税.配当控除)
        return _yen(
            [
                dividend_credit(int(k) + int(d) + int(g), max(int(x), 0), max(int(y), 0), int(t), rules, max(int(z), 0))
                if int(x) > 0 or int(y) > 0 or int(z) > 0
                else 0
                for x, y, z, k, d, g, t in zip(a, b, c, 課税, 配当課税, 譲渡課税, 算出)
            ],
            "配当控除の額",
        )


class 所得税_申告書の配当控除の欄の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "申告書 第一表 ㉝ の欄の額（配当控除額の計算欄G＝E＋F。所得税額の限度の前。2026-11-13）"
    reference = [f"{_HAITO}#2", f"{_HAITO}#3", f"{_DOCS}#1.1"]

    def formula_2025_01_01(人, period, parameters):
        a = 人("所得税_配当控除の対象の剰余金の配当等に係る配当所得の金額", period)
        b = 人("所得税_配当控除の対象の証券投資信託の収益の分配に係る配当所得の金額", period)
        c = 人("所得税_配当控除の対象の一般外貨建等証券投資信託の収益の分配に係る配当所得の金額", period)
        if not ((a > 0) | (b > 0) | (c > 0)).any():
            return np.zeros(len(a), dtype=np.int32)
        課税 = 人("所得税_課税総所得金額", period)
        配当課税 = 人("所得税_上場株式等に係る課税配当所得等の金額", period)
        譲渡課税 = 人("所得税_上場株式等に係る課税譲渡所得等の金額", period)
        rules = dividend_credit_rules_from_parameters(parameters(period).所得税.配当控除)
        return _yen(
            [
                dividend_credit_computed(int(k) + int(d) + int(g), max(int(x), 0), max(int(y), 0), rules, max(int(z), 0))
                if int(x) > 0 or int(y) > 0 or int(z) > 0
                else 0
                for x, y, z, k, d, g in zip(a, b, c, 課税, 配当課税, 譲渡課税)
            ],
            "申告書の配当控除の欄の額",
        )


class 所得税_事業所得等の特例に係る税額控除の区分(Variable):
    value_type = str
    entity = 人物
    definition_period = YEAR
    label = "第一表 ㉞ の区分（事業所得等の特例に係る税額控除があれば「1」、なければ「なし」。手引き 3-4_29）"
    reference = [f"{_CREDITS}#2"]

    def formula_2025_01_01(人, period, parameters):
        額 = 人("所得税_事業所得等の特例に係る税額控除の額", period)
        return np.array([business_credit_category(int(a)) for a in 額], dtype=object)


class 所得税_住宅耐震改修特別控除等の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "住宅耐震改修特別控除等の額（第一表 ㊴〜㊶：住宅耐震改修特別控除・住宅特定改修特別税額控除・認定住宅等新築等特別税額控除の合計。手引き 3-4_32）"
    reference = [f"{_CREDITS}#3"]

    def formula_2025_01_01(人, period, parameters):
        耐震 = 人("所得税_住宅耐震改修特別控除の額", period)
        特定 = 人("所得税_住宅特定改修特別税額控除の額", period)
        認定 = 人("所得税_認定住宅等新築等特別税額控除の額", period)
        return _yen([int(a) + int(b) + int(c) for a, b, c in zip(耐震, 特定, 認定)], "住宅耐震改修特別控除等の額")


class 所得税_住宅耐震改修特別控除等の区分(Variable):
    value_type = str
    entity = 人物
    definition_period = YEAR
    label = "第一表 ㊴〜㊶ の区分（住宅耐震改修 1・住宅特定改修 2・認定住宅等新築等 3・複数 4。なければ「なし」。手引き 3-4_32）"
    reference = [f"{_CREDITS}#3"]

    def formula_2025_01_01(人, period, parameters):
        耐震 = 人("所得税_住宅耐震改修特別控除の額", period)
        特定 = 人("所得税_住宅特定改修特別税額控除の額", period)
        認定 = 人("所得税_認定住宅等新築等特別税額控除の額", period)
        return np.array([housing_credit_category(int(a), int(b), int(c)) for a, b, c in zip(耐震, 特定, 認定)], dtype=object)


class 所得税_基準所得税額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "基準所得税額（算出税額から配当控除・事業所得等の特例に係る税額控除・住宅借入金等特別控除・政党等寄附金特別控除等・住宅耐震改修特別控除等を"
        "手引きの順に控除した額。0未満にしない）"
    )
    reference = [f"{_DOCS}#3.1", f"{_DOCS}#1.1", f"{_CREDITS}#4"]

    def formula_2025_01_01(人, period, parameters):
        算出 = 人("所得税_算出税額", period)
        # 手引き 3-4_36 の順（calc.CREDIT_ORDER）：㉝ 配当控除 → ㉞ → ㉟ 住宅借入金等 → ㊱〜㊳ 政党等寄附金等 → ㊴〜㊶ 住宅耐震改修等
        控除 = (
            人("所得税_配当控除の額", period),
            人("所得税_事業所得等の特例に係る税額控除の額", period),
            人("所得税_住宅借入金等特別控除の額", period),
            人("所得税_政党等寄附金特別控除等の額", period),
            人("所得税_住宅耐震改修特別控除等の額", period),
        )
        return _yen(
            [deduct_credits(int(a), [int(c[i]) for c in 控除]).差引所得税額 for i, a in enumerate(算出)], "基準所得税額"
        )


class 所得税_復興特別所得税額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "復興特別所得税額（基準所得税額×2.1%。1円未満は令和7年分は手引き、令和8年分は国税通則法基本通達の読みで切捨て）"
    reference = [f"{_DOCS}#3.1", f"{_DOCS}#3.3"]

    def formula_2025_01_01(人, period, parameters):
        基準 = 人("所得税_基準所得税額", period)
        率 = rate_of(parameters(period).所得税.復興特別所得税.税率, "復興特別所得税の税率")
        rule = FUKKO_ROUNDING_YEARS.get(period.start.year)
        if rule is not None:
            return _yen([fukko_tax(int(x), 率, rule.apply) for x in 基準], "復興特別所得税額")
        金額 = [int(x) for x in 基準]
        if not any((x * 率).denominator != 1 for x in 金額):  # 1円未満の端数が出ないなら候補を引かない（候補の評価の分かれ目を開かない）
            return _yen([fukko_tax(x, 率, FUNCTIONS["floor"]) for x in 金額], "復興特別所得税額")
        候補 = 人("所得税_復興特別所得税額の端数の候補", period)
        return _yen([fukko_tax(x, 率, FUNCTIONS[str(c)]) for x, c in zip(金額, 候補)], "復興特別所得税額")


class 所得税_所得税及び復興特別所得税の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "所得税及び復興特別所得税の額（基準所得税額＋復興特別所得税額）"
    reference = [f"{_DOCS}#3.1", f"{_DOCS}#5.4"]

    def formula_2025_01_01(人, period, parameters):
        a = 人("所得税_基準所得税額", period)
        b = 人("所得税_復興特別所得税額", period)
        return _yen([int(x) + int(y) for x, y in zip(a, b)], "所得税及び復興特別所得税の額")


class 所得税_申告納税額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "申告納税額（所得税及び復興特別所得税の額 − 源泉徴収税額。黒字は百円未満切捨て、赤字は0）"
    reference = [f"{_DOCS}#4.1", f"{_DOCS}#3.3"]

    def formula_2025_01_01(人, period, parameters):
        total = 人("所得税_所得税及び復興特別所得税の額", period)
        源泉 = 人("所得税_源泉徴収税額", period)
        unit = parameters(period).所得税.端数計算.確定金額の単位
        return _yen([shinkoku_nozei(int(t), int(w), unit) for t, w in zip(total, 源泉)], "申告納税額")


class 所得税_申告書の申告納税額の欄の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "申告書 第一表 ㊿ の欄の額（所得税及び復興特別所得税の額 − 源泉徴収税額。黒字は百円未満切捨て、赤字はそのまま。2026-11-13）"
    reference = [f"{_DOCS}#4.1", f"{_DOCS}#3.3"]

    def formula_2025_01_01(人, period, parameters):
        total = 人("所得税_所得税及び復興特別所得税の額", period)
        源泉 = 人("所得税_源泉徴収税額", period)
        unit = parameters(period).所得税.端数計算.確定金額の単位
        values = [shinkoku_nozei_field(int(t), int(w), unit) for t, w in zip(total, 源泉)]
        if any(abs(v) > INT32_MAX for v in values):
            raise OverflowError("申告書の申告納税額の欄の額が int32 の範囲の外")
        return np.array(values, dtype=np.int32)


class 所得税_還付される税額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "還付される税額（控除しきれない源泉徴収税額・予定納税額）"
    reference = [f"{_DOCS}#4.2", f"{_DOCS}#3.3"]

    def formula_2025_01_01(人, period, parameters):
        total = 人("所得税_所得税及び復興特別所得税の額", period)
        源泉 = 人("所得税_源泉徴収税額", period)
        予定 = 人("所得税_予定納税額", period)
        unit = parameters(period).所得税.端数計算.確定金額の単位
        return _yen([refund_amount(int(t), int(w), int(p), unit) for t, w, p in zip(total, 源泉, 予定)], "還付される税額")


class 所得税_第3期分の税額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "第3期分の税額（申告納税額 − 予定納税額。黒字は百円未満切捨て、赤字は0）"
    reference = [f"{_DOCS}#4.3", f"{_DOCS}#3.3"]

    def formula_2025_01_01(人, period, parameters):
        申告 = 人("所得税_申告納税額", period)
        予定 = 人("所得税_予定納税額", period)
        unit = parameters(period).所得税.端数計算.確定金額の単位
        return _yen([third_installment(int(s), int(p), unit) for s, p in zip(申告, 予定)], "第3期分の税額")


# ---------------------------------------------------------------------------
# 申告の要否・期限
# ---------------------------------------------------------------------------


def _calendars(year: int, *nodes: object) -> dict[int, Calendar]:
    """その年分の年と続く2年の休日（第125条の期限は、知った日が翌年なら翌々年にかかりうる）。"""
    return {year + i: calendar_from_parameters(year + i, h) for i, h in enumerate(nodes)}


def _deadline(kind: str, known: _dt.date, year: int, 期限: object, cals: dict[int, Calendar], departure: _dt.date | None = None) -> _dt.date:
    """申告の種類ごとの期限。決まらなければ UNKNOWN_DEADLINE（入力の分かれ目〔公表待ち・事実・一次情報〕か対象外で、結果には値として出ない）。

    死亡の場合の departure は相続人の出国の日（第124条第1項・第125条第1項の括弧：その前に出国をするなら出国の時）。
    """
    try:
        if kind == KIND_NORMAL:
            return normal_deadline(year, 期限.第三期の末日, cals)  # type: ignore[attr-defined]
        if kind in (KIND_DEATH, KIND_DEATH_NEXT_YEAR):
            if known == NO_DATE:
                return UNKNOWN_DEADLINE
            return death_deadline(known, 期限.死亡の場合の月数, cals, departure)  # type: ignore[attr-defined]
    except CalendarUnknown:
        pass
    return UNKNOWN_DEADLINE


def other_income_basis(合計, 給与, 調整, 退職, 青色) -> list[int]:  # noqa: ANN001
    """基通121−6 の所得金額の基礎：合計所得金額（損益通算の後・繰越控除の前）から給与所得と退職所得を引き、確定申告を要件とする青色申告特別控除を足し戻す。"""
    return [int(a) - int(b) + int(c) - int(d) + int(e) for a, b, c, d, e in zip(合計, 給与, 調整, 退職, 青色)]


#: 第2号ロの所得控除の額（所法121①二ロ）を合計する変数。
LO_DEDUCTIONS = (
    "所得税_社会保険料控除の額",
    "所得税_小規模企業共済等掛金控除の額",
    "所得税_生命保険料控除の額",
    "所得税_地震保険料控除の額",
    "所得税_障害者控除の額",
    "所得税_寡婦控除の額",
    "所得税_ひとり親控除の額",
    "所得税_勤労学生控除の額",
    "所得税_配偶者控除の額",
    "所得税_配偶者特別控除の額",
    "所得税_扶養控除の額",
    "所得税_特定親族特別控除の額",
)


def obligations_of(v: Mapping[str, Any], p: Any) -> list[Obligation]:
    """第120条第1項・第121条の判定を人ごとに行う（式と計算の後の検出の両方が使う）。v は変数の値の配列（給与の事実がない状況では一部を持たない）。"""
    n = len(v["税総"])
    上限 = int(p.給与所得及び退職所得以外の所得金額の上限)
    年金上限 = int(p.公的年金等に係る雑所得以外の所得金額の上限)
    小額 = int(p.第2号ロの給与等の金額の基準)
    基礎 = v.get("基礎")
    out: list[Obligation] = []
    for i in range(n):
        salary_f = None
        pension_f = None
        if 基礎 is not None:
            salary_f = SalaryFacts(
                payers=int(v["支払者"][i]),
                all_withheld=bool(v["全部源泉"][i]),
                all_year_end_adjusted=bool(v["全部年調"][i]),
                secondary_salary=int(v["従たる給与"][i]),
                secondary_known=bool(v["従たる判明"][i]),
                other_income=max(基礎[i], 0),
                deductions=int(v["控除ロ"][i]),
                other_limit=上限,
                small_salary_limit=小額,
                excluded=bool(v["除外"][i]),
            )
            pension_f = PensionFacts(
                all_withheld=bool(v["年金全部"][i]),
                other_income=max(基礎[i] + int(v["給与所得"][i]) - int(v["調整"][i]) - int(v["年金雑"][i]), 0),
                other_limit=年金上限,
            )
        retirement_f = RetirementFacts(all_withheld=bool(v["退職全部"][i]), withheld=int(v["退職源泉"][i]))
        out.append(
            filing_obligation(
                tax_total_income=int(v["税総"][i]),
                tax_retirement=int(v["税退"][i]),
                tax_separate_dividend=int(v["税配当"][i]),
                tax_separate_gain=int(v["税譲渡"][i]),
                dividend_credit=int(v["配当控除"][i]),
                year_end_housing_credit=int(v["住宅"][i]),
                refund=int(v["還付"][i]),
                salary=int(v["給与"][i]),
                pension=int(v["年金"][i]),
                salary_limit=p.給与等の金額の上限,
                pension_limit=p.公的年金等の収入金額の上限,
                salary_facts=salary_f,
                pension_facts=pension_f,
                retirement_facts=retirement_f,
            )
        )
    return out


class 所得税_確定申告書の提出義務があるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "確定申告書を提出しなければならないか（所得税法第120条第1項・第121条。措令4の2⑧・25の8⑮の読替えで分離課税の税額も比べる）"
    reference = [f"{_DOCS}#5.1", f"{_DOCS}#5.2", _R121]

    def formula_2025_01_01(人, period, parameters):
        税総 = 人("所得税_課税総所得金額に対する税額", period)
        税退 = 人("所得税_課税退職所得金額に対する税額", period)
        税配当 = 人("所得税_上場株式等に係る課税配当所得等の金額に対する税額", period)
        税譲渡 = 人("所得税_上場株式等に係る課税譲渡所得等の金額に対する税額", period)
        配当控除 = 人("所得税_配当控除の額", period)
        住宅 = 人("所得税_年末調整で控除された住宅借入金等特別控除の額", period)
        還付 = 人("所得税_還付される税額", period)
        給与 = 人("所得税_給与等の収入金額", period)
        年金 = 人("所得税_公的年金等の収入金額", period)
        v: dict[str, Any] = {
            "税総": 税総, "税退": 税退, "税配当": 税配当, "税譲渡": 税譲渡, "配当控除": 配当控除, "住宅": 住宅, "還付": 還付, "給与": 給与, "年金": 年金,
        }  # fmt: skip
        n = len(税総)
        v["退職全部"] = np.ones(n, dtype=bool)
        v["退職源泉"] = np.zeros(n, dtype=np.int32)
        if (税退 > 0).any():
            v["退職全部"] = 人("所得税_退職手当等の全部が源泉徴収の対象か", period)
            v["退職源泉"] = 人("所得税_退職手当等の源泉徴収税額", period)
        if (給与 > 0).any() or (年金 > 0).any():
            合計 = 人("所得税_合計所得金額", period)
            給与所得 = 人("所得税_給与所得", period)
            調整 = 人("所得税_所得金額調整控除", period)
            退職 = 人("所得税_退職所得の金額", period)
            青色 = 人("所得税_青色申告特別控除額", period)
            v.update(
                {
                    "基礎": other_income_basis(合計, 給与所得, 調整, 退職, 青色),
                    "給与所得": 給与所得,
                    "調整": 調整,
                    "年金雑": 人("所得税_公的年金等に係る雑所得の金額", period),
                    "支払者": 人("所得税_給与等の支払者の数", period),
                    "全部源泉": 人("所得税_給与等の全部が源泉徴収の対象か", period),
                    "全部年調": 人("所得税_給与等の全部が年末調整の対象か", period),
                    "従たる給与": 人("所得税_従たる給与等の金額", period),
                    "従たる判明": 人("所得税_従たる給与等の金額が分かるか", period),
                    "年金全部": 人("所得税_公的年金等の全部が源泉徴収の対象か", period),
                    "除外": 人("所得税_給与等が第121条第1項の適用除外か", period),
                    "控除ロ": np.zeros(n, dtype=np.int32),
                }
            )
            if (v["支払者"] >= 2).any():
                v["控除ロ"] = (
                    人("所得税_社会保険料控除の額", period)
                    + 人("所得税_小規模企業共済等掛金控除の額", period)
                    + 人("所得税_生命保険料控除の額", period)
                    + 人("所得税_地震保険料控除の額", period)
                    + 人("所得税_障害者控除の額", period)
                    + 人("所得税_寡婦控除の額", period)
                    + 人("所得税_ひとり親控除の額", period)
                    + 人("所得税_勤労学生控除の額", period)
                    + 人("所得税_配偶者控除の額", period)
                    + 人("所得税_配偶者特別控除の額", period)
                    + 人("所得税_扶養控除の額", period)
                    + 人("所得税_特定親族特別控除の額", period)
                )
        p = parameters(period).所得税.確定申告を要しない場合
        return np.array([o.value for o in obligations_of(v, p)], dtype=bool)


class 所得税_還付申告ができるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "還付等を受けるための申告書を提出できるか（所得税法第122条第1項。還付される税額が0超）"
    reference = [f"{_DOCS}#5.3", f"{_DOCS}#4.2"]

    def formula_2025_01_01(人, period, parameters):
        return 人("所得税_還付される税額", period) > 0


class 所得税_還付申告の選択(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "還付等を受けるための申告書を提出する選択（選択.還付申告、又は提出した確定申告書の記録。段 還付申告の選択 が書く：refund.py）"
    reference = [f"{_DOCS}#4.2", f"{_DOCS}#5.3"]


class 所得税_還付を受けるための申告書を提出するか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "控除しきれない源泉徴収税額・予納税額の還付を受けるための申告書（所得税法第122条）を提出するか"
    reference = [f"{_DOCS}#4.2", f"{_DOCS}#5.3"]

    def formula_2025_01_01(人, period, parameters):
        return 人("所得税_還付申告ができるか", period) * 人("所得税_還付申告の選択", period)


class 所得税_申告期限(Variable):
    value_type = _dt.date
    entity = 人物
    definition_period = YEAR
    label = "確定申告書の提出期限（第120条：第三期の末日、第124条・第125条：知った日の翌日から4月を経過した日の前日、第126条・第127条：出国の時。休日なら国税通則法第10条第2項で繰り下げる。出国の時は繰り下げない）"
    reference = [f"{_DOCS}#5.1", "docs/public-sources/20261109_round3_shibo-shukkoku-laws-and-nta.md#6"]

    def formula_2025_01_01(人, period, parameters):
        種類 = 人("所得税_申告の種類", period)
        知った日 = 人("所得税_相続の開始があったことを知った日", period)
        出国の日 = 人("所得税_出国の日", period)
        期限 = parameters(period).所得税.申告期限
        year = period.start.year
        cals = _calendars(
            year,
            parameters(period).所得税.休日,
            parameters(period.offset(1)).所得税.休日,
            parameters(period.offset(2)).所得税.休日,
        )
        return np.array(
            [
                np.datetime64(e, "D").astype(object)
                if str(k) == KIND_DEPARTURE
                else _deadline(str(k), np.datetime64(d, "D").astype(object), year, 期限, cals, _date_or_none(np.datetime64(e, "D").astype(object)))
                for k, d, e in zip(種類, 知った日, 出国の日)
            ],
            dtype="datetime64[D]",
        )


def _date_or_none(d: _dt.date) -> _dt.date | None:
    return None if d == NO_DATE else d


VARIABLES = (
    所得税_源泉徴収税額,
    所得税_予定納税額,
    所得税_住宅借入金等特別控除の額,
    所得税_事業所得等の特例に係る税額控除の額,
    所得税_住宅耐震改修特別控除の額,
    所得税_住宅特定改修特別税額控除の額,
    所得税_認定住宅等新築等特別税額控除の額,
    所得税_申告の種類,
    所得税_相続の開始があったことを知った日,
    所得税_出国の日,
    所得税_給与等の支払者の数,
    所得税_給与等の全部が源泉徴収の対象か,
    所得税_給与等の全部が年末調整の対象か,
    所得税_従たる給与等の金額,
    所得税_従たる給与等の金額が分かるか,
    所得税_公的年金等の全部が源泉徴収の対象か,
    所得税_退職手当等の全部が源泉徴収の対象か,
    所得税_退職手当等の源泉徴収税額,
    所得税_給与等が第121条第1項の適用除外か,
    所得税_年末調整で控除された住宅借入金等特別控除の額,
    所得税_上場株式等の所得控除の順序,
    所得税_復興特別所得税額の端数の候補,
    所得税_所得控除の合計,
    所得税_課税総所得金額,
    所得税_課税退職所得金額,
    所得税_上場株式等に係る課税配当所得等の金額,
    所得税_上場株式等に係る課税譲渡所得等の金額,
    所得税_課税総所得金額に対する税額,
    所得税_課税退職所得金額に対する税額,
    所得税_上場株式等に係る課税配当所得等の金額に対する税額,
    所得税_上場株式等に係る課税譲渡所得等の金額に対する税額,
    所得税_算出税額,
    所得税_配当控除の額,
    所得税_申告書の配当控除の欄の額,
    所得税_事業所得等の特例に係る税額控除の区分,
    所得税_住宅耐震改修特別控除等の額,
    所得税_住宅耐震改修特別控除等の区分,
    所得税_基準所得税額,
    所得税_復興特別所得税額,
    所得税_所得税及び復興特別所得税の額,
    所得税_申告納税額,
    所得税_申告書の申告納税額の欄の額,
    所得税_還付される税額,
    所得税_第3期分の税額,
    所得税_確定申告書の提出義務があるか,
    所得税_還付申告ができるか,
    所得税_還付申告の選択,
    所得税_還付を受けるための申告書を提出するか,
    所得税_申告期限,
)

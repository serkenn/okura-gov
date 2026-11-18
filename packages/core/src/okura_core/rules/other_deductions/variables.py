"""規則モジュール other_deductions の変数：前処理の結果（入力変数）と、各控除の額（式）。

金額の変数は int（numpy.int32）。途中の値は calc.py の純粋関数の中で Fraction のまま持ち、整数の円にしてから返す。
式は、ほかのモジュールのまだない概念（総所得金額等・年齢23歳未満の扶養親族を有するか）を、それが値を変えうるときだけ引く
（例：補塡後の医療費が全員0なら医療費控除の額は総所得金額等によらず0。トレースの依存が値の依存と一致する）。
"""

from __future__ import annotations

import numpy as np
from openfisca_core.model_api import YEAR, Variable

from ...country.entities import 人物
from ...money import INT32_MAX
from ...money import rate as _rate
from ...rounding import FUNCTIONS
from .basis import HOKEN_CEIL
from .calc import (
    casualty_carryforward,
    casualty_deduction,
    donation_credit_rules_from_parameters,
    donation_credits,
    donation_deduction,
    earthquake_deduction,
    fraction_matters,
    life_insurance_deduction,
    life_rules_from_parameters,
    limit_fraction_matters,
    medical_deduction,
    self_medication_deduction,
    steps_from,
    tenth_fraction_matters,
)

_IRL = "docs/public-sources/20261109_impl-prep_iryohi-law-text.md"
_IRN = "docs/public-sources/20261109_impl-prep_iryohi-nta-mhlw.md"
_HKL = "docs/public-sources/20261109_round2_hoken-kifu-laws.md"
_HKN = "docs/public-sources/20261109_round2_hoken-kifu-nta-soumu.md"
_ZG = "docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md"
_SK = "docs/public-sources/20261111_impl-research_seito-kifu-laws-and-nta.md"


def _int32(values: list[int]) -> np.ndarray:
    if any(v < 0 or v > INT32_MAX for v in values):
        raise OverflowError("控除の額が 0〜int32 の範囲の外")
    return np.array(values, dtype=np.int32)


# ---------------------------------------------------------------------------
# 入力変数（inputs.py が中間表現から作る。事実の層）
# ---------------------------------------------------------------------------


class 所得税_補塡後の医療費の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "その年中に支払った、控除の対象となる医療費の額（自己と生計を一にする親族の分。補塡を医療費ごとに限度として差し引いた後。支払者ごと）"
    reference = [f"{_IRL}#1", f"{_IRL}#2.1", f"{_IRN}#1", f"{_IRN}#4"]


class 所得税_特定一般用医薬品等購入費の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "その年中に支払った特定一般用医薬品等購入費の額（本人の取組があり、対象の表示がある購入。自己と生計を一にする親族の分）"
    reference = [f"{_IRL}#4.1", f"{_IRN}#6.1", f"{_IRN}#6.4"]


class 所得税_セルフメディケーション税制の選択(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "医療費控除の特例（セルフメディケーション税制）を選択したか（選択.医療費控除かセルフメディケーション税制か。未入力なら両方で評価）"
    reference = [f"{_IRL}#4.1", f"{_IRN}#6.1"]


class 所得税_医療費控除の足切りの端数(Variable):
    value_type = str
    entity = 人物
    definition_period = YEAR
    label = "総所得金額等の百分の五の1円未満の端数の候補（根拠なし。evaluate が floor・ceil・half_up を入れる）"
    reference = [f"{_IRL}#6", f"{_IRN}#9"]


class 所得税_支払った社会保険料の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "その年中に支払った（給与から控除されたものを含む）自己又は生計を一にする親族の負担すべき社会保険料の額"
    reference = [f"{_ZG}#7.1", f"{_ZG}#7.2"]


class 所得税_支払った小規模企業共済等掛金の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "その年中に支払った小規模企業共済等掛金の額（加入者本人の支払）"
    reference = [f"{_HKL}#5", f"{_HKN}#4"]


class 所得税_新生命保険料の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "その年中に支払った新生命保険料の金額の合計額（剰余金・割戻金を差し引いた残額）"
    reference = [f"{_HKL}#2.1", f"{_HKL}#2.2"]


class 所得税_旧生命保険料の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "その年中に支払った旧生命保険料の金額の合計額（剰余金・割戻金を差し引いた残額）"
    reference = [f"{_HKL}#2.1", f"{_HKL}#2.2"]


class 所得税_介護医療保険料の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "その年中に支払った介護医療保険料の金額の合計額（剰余金・割戻金を差し引いた残額）"
    reference = [f"{_HKL}#2.1", f"{_HKL}#2.2"]


class 所得税_新個人年金保険料の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "その年中に支払った新個人年金保険料の金額の合計額（剰余金・割戻金を差し引いた残額）"
    reference = [f"{_HKL}#2.1", f"{_HKL}#2.2"]


class 所得税_旧個人年金保険料の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "その年中に支払った旧個人年金保険料の金額の合計額（剰余金・割戻金を差し引いた残額）"
    reference = [f"{_HKL}#2.1", f"{_HKL}#2.2"]


class 所得税_生命保険料の新旧の選択(Variable):
    value_type = str
    entity = 人物
    definition_period = YEAR
    default_value = "both"
    label = "一般・個人年金の生命保険料について新のみ・旧のみ・両方のどれで控除額を計算するか（new_only・old_only・both。選択.保険料控除の区分）"
    reference = [f"{_HKL}#2.1", f"{_HKN}#1.4"]


class 所得税_地震保険料の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "その年中に支払った地震保険料の金額の合計額（剰余金・割戻金を差し引いた残額）"
    reference = [f"{_HKL}#3", f"{_HKN}#2.1"]


class 所得税_旧長期損害保険料の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "その年中に支払った旧長期損害保険料の金額の合計額（平成18年法律第10号附則第10条第2項）"
    reference = [f"{_HKL}#3", f"{_HKN}#2.1"]


class 所得税_特定寄附金の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "その年中に支出した特定寄附金の額の合計額（この版は国又は地方公共団体に対する寄附金だけ）"
    reference = [f"{_HKL}#4", f"{_HKN}#3.1"]


class 所得税_寄附金控除の上限の端数(Variable):
    value_type = str
    entity = 人物
    definition_period = YEAR
    label = "総所得金額等の百分の四十の1円未満の端数の候補（根拠なし。evaluate が floor・ceil・half_up を入れる）"
    reference = [f"{_HKL}#4"]


class 所得税_雑損の損失の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "その年の雑損控除の損失の金額の合計額（資産の損失の金額＋災害等関連支出の金額−保険金等で補塡される部分。所得税法第72条第1項）"
    reference = [f"{_HKL}#6", f"{_HKN}#5.1"]


class 所得税_雑損の災害関連支出の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "損失の金額に含まれる災害関連支出の金額（所得税法第72条第1項第1号・第2号・所令第206条第2項。保険金等で補塡される部分を除く）"
    reference = [f"{_HKL}#6", f"{_HKN}#5.1"]


class 所得税_雑損控除の足切りの端数(Variable):
    value_type = str
    entity = 人物
    definition_period = YEAR
    label = "総所得金額等の10分の1の1円未満の端数の候補（根拠なし。evaluate が floor・ceil・half_up を入れる）"
    reference = [f"{_HKL}#6"]


class 所得税_税額控除を受ける政党等寄附金の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "税額控除を受けるとした政党等に対する寄附金の額の合計額（租税特別措置法第41条の18第2項）"
    reference = [f"{_SK}#1", f"{_SK}#4"]


class 所得税_税額控除を受ける認定NPO法人等寄附金の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "税額控除を受けるとした特定非営利活動に関する寄附金の額の合計額（租税特別措置法第41条の18の2第2項）"
    reference = [f"{_SK}#2"]


class 所得税_税額控除を受ける公益社団法人等寄附金の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "税額控除を受けるとした税額控除対象寄附金の額の合計額（租税特別措置法第41条の18の3第1項）"
    reference = [f"{_SK}#3"]


class 所得税_年齢23歳未満の扶養親族を有するか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "年齢23歳未満の扶養親族を有するか（租税特別措置法第41条の15の5。段階評価で親族・生計・合計所得金額の要件から決める）"
    reference = [f"{_HKL}#2.3", f"{_HKN}#1.6"]


# ---------------------------------------------------------------------------
# 所得控除の額（式）
# ---------------------------------------------------------------------------


class 所得税_医療費控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "医療費控除の額（所得税法第73条。セルフメディケーション税制を選択した人は0）"
    reference = [f"{_IRL}#1", f"{_IRL}#3.1", f"{_IRN}#2.2"]

    def formula_2025_01_01(人, period, parameters):
        p = parameters(period).所得税.医療費控除
        医療費 = 人("所得税_補塡後の医療費の額", period)
        選択 = 人("所得税_セルフメディケーション税制の選択", period)
        if ((医療費 > 0) & ~選択).any():
            総所得金額等 = 人("所得税_総所得金額等", period)
        else:
            総所得金額等 = np.zeros(len(医療費), dtype=np.int64)
        r = _rate(int(p.足切りの率.分子), int(p.足切りの率.分母))
        上限 = int(p.足切りの上限)
        対象 = [int(m) if not s else 0 for m, s in zip(医療費, 選択)]
        # 根拠のない端数の候補は、1円未満の端数が値を変えうる人がいるときだけ引く（端数が出ない評価で分かれ目に入れない）
        if any(fraction_matters(m, int(t), r, 上限) for m, t in zip(対象, 総所得金額等)):
            候補 = [FUNCTIONS[str(c)] for c in 人("所得税_医療費控除の足切りの端数", period)]
        else:
            候補 = [FUNCTIONS["floor"]] * len(対象)
        values = [
            medical_deduction(m, int(t), f, rate=r, threshold_cap=上限, cap=int(p.控除の上限))
            for m, t, f in zip(対象, 総所得金額等, 候補)
        ]
        return _int32(values)


class 所得税_セルフメディケーション税制による医療費控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "特定一般用医薬品等購入費を支払った場合の医療費控除の特例の額（租税特別措置法第41条の17。選択した人だけ）"
    reference = [f"{_IRL}#4.1", f"{_IRN}#5.4", f"{_IRN}#6.1"]

    def formula_2025_01_01(人, period, parameters):
        p = parameters(period).所得税.セルフメディケーション税制
        購入費 = 人("所得税_特定一般用医薬品等購入費の額", period)
        選択 = 人("所得税_セルフメディケーション税制の選択", period)
        values = [
            self_medication_deduction(int(x), floor=int(p.足切り), cap=int(p.控除の上限)) if s else 0
            for x, s in zip(購入費, 選択)
        ]
        return _int32(values)


class 所得税_社会保険料控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "社会保険料控除の額（所得税法第74条：支払った金額又は給与から控除される金額の全額）"
    reference = [f"{_ZG}#7.1", f"{_ZG}#7.2"]

    def formula_2025_01_01(人, period, parameters):
        return 人("所得税_支払った社会保険料の額", period)


class 所得税_小規模企業共済等掛金控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "小規模企業共済等掛金控除の額（所得税法第75条：支払った金額の全額）"
    reference = [f"{_HKL}#5", f"{_HKN}#4"]

    def formula_2025_01_01(人, period, parameters):
        return 人("所得税_支払った小規模企業共済等掛金の額", period)


class 所得税_生命保険料控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "生命保険料控除の額（所得税法第76条、租税特別措置法第41条の15の5。区分ごとの式の1円未満は切上げ：国税庁の年末調整のしかた）"
    reference = [f"{_HKL}#2.1", f"{_HKL}#2.3", f"{_HKN}#1.6"]

    def formula_2025_01_01(人, period, parameters):
        p = parameters(period).所得税.生命保険料控除
        新 = 人("所得税_新生命保険料の額", period)
        旧 = 人("所得税_旧生命保険料の額", period)
        介護 = 人("所得税_介護医療保険料の額", period)
        新年金 = 人("所得税_新個人年金保険料の額", period)
        旧年金 = 人("所得税_旧個人年金保険料の額", period)
        選択 = 人("所得税_生命保険料の新旧の選択", period)
        特例の年 = bool(p.措法第41条の15の5.適用)
        if 特例の年 and (新 > 0).any():
            有する = 人("所得税_年齢23歳未満の扶養親族を有するか", period)
        else:
            有する = np.zeros(len(新), dtype=bool)
        normal = life_rules_from_parameters(p, special=False)
        special = life_rules_from_parameters(p, special=True) if 特例の年 else normal
        values = [
            life_insurance_deduction(int(a), int(b), int(c), int(d), int(e), str(r), special if h else normal, HOKEN_CEIL.apply)
            for a, b, c, d, e, r, h in zip(新, 旧, 介護, 新年金, 旧年金, 選択, 有する)
        ]
        return _int32(values)


class 所得税_地震保険料控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "地震保険料控除の額（所得税法第77条、平成18年法律第10号附則第10条）"
    reference = [f"{_HKL}#3", f"{_HKN}#2.1"]

    def formula_2025_01_01(人, period, parameters):
        p = parameters(period).所得税.地震保険料控除
        地震 = 人("所得税_地震保険料の額", period)
        旧長期 = 人("所得税_旧長期損害保険料の額", period)
        steps = steps_from(p.旧長期損害保険料)
        values = [
            earthquake_deduction(
                int(a), int(b), quake_cap=int(p.地震保険料の上限), old_long_steps=steps, total_cap=int(p.合計の上限), up=HOKEN_CEIL.apply
            )
            for a, b in zip(地震, 旧長期)
        ]
        return _int32(values)


class 所得税_寄附金控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "寄附金控除の額（所得税法第78条第1項）"
    reference = [f"{_HKL}#4", f"{_HKN}#3.1"]

    def formula_2025_01_01(人, period, parameters):
        p = parameters(period).所得税.寄附金控除
        寄附 = 人("所得税_特定寄附金の額", period)
        足切り = int(p.足切り)
        if (寄附 > 足切り).any():
            総所得金額等 = 人("所得税_総所得金額等", period)
        else:
            総所得金額等 = np.zeros(len(寄附), dtype=np.int64)
        r = _rate(int(p.総所得金額等の率.分子), int(p.総所得金額等の率.分母))
        # 根拠のない端数の候補は、1円未満の端数が値を変えうる人がいるときだけ引く
        if any(int(x) > 足切り and limit_fraction_matters(int(x), int(t), r) for x, t in zip(寄附, 総所得金額等)):
            候補 = [FUNCTIONS[str(c)] for c in 人("所得税_寄附金控除の上限の端数", period)]
        else:
            候補 = [FUNCTIONS["floor"]] * len(寄附)
        values = [donation_deduction(int(x), int(t), f, rate=r, floor=足切り) for x, t, f in zip(寄附, 総所得金額等, 候補)]
        return _int32(values)


class 所得税_雑損控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "雑損控除の額（所得税法第72条第1項）。損失の金額の合計額のうち足切りの額を超える部分"
    reference = [f"{_HKL}#6", f"{_HKN}#5.1"]

    def formula_2025_01_01(人, period, parameters):
        p = parameters(period).所得税.雑損控除
        損失 = 人("所得税_雑損の損失の金額", period)
        関連支出 = 人("所得税_雑損の災害関連支出の金額", period)
        if (損失 > 0).any():
            総所得金額等 = 人("所得税_総所得金額等", period)
        else:
            総所得金額等 = np.zeros(len(損失), dtype=np.int64)
        r = _rate(int(p.総所得金額等の率.分子), int(p.総所得金額等の率.分母))
        基準 = int(p.災害関連支出の額)
        if any(tenth_fraction_matters(int(a), int(e), int(t), r, 基準) for a, e, t in zip(損失, 関連支出, 総所得金額等)):
            候補 = [FUNCTIONS[str(c)] for c in 人("所得税_雑損控除の足切りの端数", period)]
        else:
            候補 = [FUNCTIONS["floor"]] * len(損失)
        values = [
            casualty_deduction(int(a), int(e), int(t), f, rate=r, related_limit=基準)
            for a, e, t, f in zip(損失, 関連支出, 総所得金額等, 候補)
        ]
        return _int32(values)


class 所得税_翌年以後に繰り越す雑損失の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "その年に生じた雑損失の金額（所得税法第2条第1項第26号）のうち、その年分に控除しきれず翌年以後に繰り越す金額"
        "（雑損控除の額 − 雑損控除を当てる所得の合計。所得控除は雑損控除から：所法87①、総所得金額 → 上場株式等の所得 → 退職所得金額の順：所法87②・措通31・32共−4）"
    )
    reference = [f"{_HKL}#6", f"{_HKN}#5.1", "docs/public-sources/20261111_impl-research3_joto-junjo-laws-and-nta.md#3"]

    def formula_2025_01_01(人, period, parameters):
        控除 = 人("所得税_雑損控除の額", period)
        if (控除 > 0).any():
            総所得金額等 = 人("所得税_総所得金額等", period)
        else:
            総所得金額等 = np.zeros(len(控除), dtype=np.int64)
        return _int32([casualty_carryforward(int(a), int(t)) for a, t in zip(控除, 総所得金額等)])


class 所得税_政党等寄附金特別控除等の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "政党等寄附金特別控除・認定NPO法人等寄附金特別控除・公益社団法人等寄附金特別控除の額の合計（租税特別措置法第41条の18第2項・"
        "第41条の18の2第2項・第41条の18の3第1項）"
    )
    reference = [f"{_SK}#1", f"{_SK}#2", f"{_SK}#3", f"{_SK}#6", f"{_SK}#7"]

    def formula_2025_01_01(人, period, parameters):
        政党 = 人("所得税_税額控除を受ける政党等寄附金の額", period)
        認定 = 人("所得税_税額控除を受ける認定NPO法人等寄附金の額", period)
        公益 = 人("所得税_税額控除を受ける公益社団法人等寄附金の額", period)
        if not ((政党 > 0) | (認定 > 0) | (公益 > 0)).any():
            return np.zeros(len(政党), dtype=np.int32)
        特定 = 人("所得税_特定寄附金の額", period)
        総所得金額等 = 人("所得税_総所得金額等", period)
        税額 = 人("所得税_算出税額", period)
        rules = donation_credit_rules_from_parameters(parameters(period).所得税.政党等寄附金特別控除等)
        values = [
            sum(donation_credits(int(a), int(b), int(c), int(g), int(t), int(x), rules))
            for a, b, c, g, t, x in zip(政党, 認定, 公益, 特定, 総所得金額等, 税額)
        ]
        return _int32(values)


INPUT_VARIABLES = (
    所得税_補塡後の医療費の額,
    所得税_特定一般用医薬品等購入費の額,
    所得税_セルフメディケーション税制の選択,
    所得税_医療費控除の足切りの端数,
    所得税_支払った社会保険料の額,
    所得税_支払った小規模企業共済等掛金の額,
    所得税_新生命保険料の額,
    所得税_旧生命保険料の額,
    所得税_介護医療保険料の額,
    所得税_新個人年金保険料の額,
    所得税_旧個人年金保険料の額,
    所得税_生命保険料の新旧の選択,
    所得税_地震保険料の額,
    所得税_旧長期損害保険料の額,
    所得税_特定寄附金の額,
    所得税_寄附金控除の上限の端数,
    所得税_雑損の損失の金額,
    所得税_雑損の災害関連支出の金額,
    所得税_雑損控除の足切りの端数,
    所得税_税額控除を受ける政党等寄附金の額,
    所得税_税額控除を受ける認定NPO法人等寄附金の額,
    所得税_税額控除を受ける公益社団法人等寄附金の額,
    所得税_年齢23歳未満の扶養親族を有するか,
)

DEDUCTION_VARIABLES = (
    所得税_医療費控除の額,
    所得税_セルフメディケーション税制による医療費控除の額,
    所得税_社会保険料控除の額,
    所得税_小規模企業共済等掛金控除の額,
    所得税_生命保険料控除の額,
    所得税_地震保険料控除の額,
    所得税_寄附金控除の額,
    所得税_雑損控除の額,
    所得税_翌年以後に繰り越す雑損失の金額,
    所得税_政党等寄附金特別控除等の額,
)

VARIABLES = INPUT_VARIABLES + DEDUCTION_VARIABLES

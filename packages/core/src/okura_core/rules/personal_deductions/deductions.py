"""規則モジュール personal_deductions の変数：所得控除の層（人的控除の額）と、条文の段階の計算。

金額はすべて整数の円で計算する（float を経由しない）。条文が定める切下げ・切上げ（配偶者特別控除の第1号ロ・第2号・第3号、
特定親族特別控除の第2号）はここの関数で、条文どおりに整数で行う。根拠は basis.py。
グループの合計（人.<グループ>.sum）は float64 を返すので、額にするときに整数へ戻す。
"""

from __future__ import annotations

import numpy
from openfisca_core.model_api import YEAR, Variable

from ...country.entities import 人物, 扶養所属


def round_down_to_step(x, step, minus):  # noqa: ANN001, ANN202
    """「step の整数倍の金額から minus を控除した金額」で x を超えないもののうち最も多い金額（x がその形ならそのまま）。"""
    return ((x + minus) // step) * step - minus


def ceil_ratio_to_unit(x, numerator, denominator, unit):  # noqa: ANN001, ANN202
    """x に 分子/分母 を乗じた金額の、unit 未満の端数を切り上げた金額（x は0以上の整数の配列）。"""
    d = denominator * unit
    return ((x * numerator + d - 1) // d) * unit


def spouse_special_first_item(spouse_income, p):  # noqa: ANN001, ANN202
    """配偶者特別控除の第1号の額（配偶者の合計所得金額の区分イ・ロ・ハ）。"""
    ロ = p.第1号.ロ
    超える部分 = spouse_income - ロ.超える部分の起点
    return numpy.select(
        [spouse_income <= p.第1号.イ.上限, spouse_income <= ロ.上限],
        [p.第1号.イ.額, ロ.基準の額 - round_down_to_step(超える部分, ロ.刻み, ロ.刻みから引く額)],
        p.第1号.ハ.額,
    )


def specified_relative_amount(income, p):  # noqa: ANN001, ANN202
    """特定親族特別控除の、特定親族1人の額（その特定親族の合計所得金額の区分）。"""
    二 = p.第2号
    乗じた金額 = (income - 二.超える部分の起点) * 二.乗数
    return numpy.select(
        [income <= p.第1号.上限, income <= 二.上限, income <= p.第3号.上限],
        [p.第1号.額, 二.基準の額 - round_down_to_step(乗じた金額, 二.刻み, 二.刻みから引く額), p.第3号.額],
        p.第4号.額,
    )


def _as_yen(x):  # noqa: ANN001, ANN202
    """金額の配列を整数にする（bincount の float64 は整数の値だけを持つ）。"""
    return numpy.asarray(x).round().astype(numpy.int64)


class 所得税_障害者控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "障害者控除の額（本人・同一生計配偶者・扶養親族の分の合計。所得税法第79条）"
    reference = ["docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.2"]

    def formula(人, period, parameters):
        p = parameters(period).所得税.障害者控除
        本人 = numpy.select(
            [人("所得税_特別障害者に当たるか", period), 人("所得税_障害者に当たるか", period)],
            [p.特別障害者の額, p.障害者の額],
            0,
        )
        # 配偶者の障害は、判定する人（相手）の判定の時の現況（所法85③。判定の時が違えば段が書いたその時の値：PD-05）
        自分の配偶者としての額 = numpy.select(
            [人("所得税_同居特別障害者に当たるか", period), 人("所得税_扶養等の判定に使う特別障害者か", period), 人("所得税_扶養等の判定に使う障害者か", period)],
            [p.同居特別障害者の額, p.特別障害者の額, p.障害者の額],
            0,
        )
        配偶者の額 = 人.法律婚.sum(
            numpy.select(
                [人("所得税_同居特別障害者に当たるか", period), 人("所得税_扶養等の判定に使う特別障害者か", period), 人("所得税_扶養等の判定に使う障害者か", period)],
                [p.同居特別障害者の額, p.特別障害者の額, p.障害者の額],
                0,
            )
        ) - 自分の配偶者としての額
        区分 = 人("所得税_グループ外の配偶者の障害の区分", period)
        外の額 = numpy.select([区分 == 3, 区分 == 2, 区分 == 1], [p.同居特別障害者の額, p.特別障害者の額, p.障害者の額], 0)
        配偶者の額 = numpy.where(人("所得税_法律婚のグループ外の配偶者がいるか", period), 外の額, 配偶者の額)
        配偶者の分 = numpy.where(人("所得税_同一生計配偶者に当たるか", period), 配偶者の額, 0)
        扶養親族の分 = 人.扶養所属.sum(人("所得税_障害者控除の扶養親族の1人分の額", period) * 人.has_role(扶養所属.扶養親族等)) * 人.has_role(扶養所属.申告者)
        return _as_yen(本人 + 配偶者の分 + 扶養親族の分) + 人("所得税_連鎖の扶養親族の障害者控除の額", period)


class 所得税_障害者控除の扶養親族の1人分の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "障害者控除の、その人が扶養親族に当たるときの1人分の額（申告者に集める。所法79）"
    reference = ["docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.2"]

    def formula(人, period, parameters):
        p = parameters(period).所得税.障害者控除
        return numpy.where(
            人("所得税_扶養親族に当たるか", period),
            numpy.select(
                [人("所得税_同居特別障害者に当たるか", period), 人("所得税_扶養等の判定に使う特別障害者か", period), 人("所得税_扶養等の判定に使う障害者か", period)],
                [p.同居特別障害者の額, p.特別障害者の額, p.障害者の額],
                0,
            ),
            0,
        )


class 所得税_寡婦控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "寡婦控除の額（所得税法第80条）"
    reference = ["docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.2"]

    def formula(人, period, parameters):
        return numpy.where(人("所得税_寡婦に当たるか", period), parameters(period).所得税.寡婦控除.額, 0)


class 所得税_ひとり親控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "ひとり親控除の額（所得税法第81条）"
    reference = ["docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.2"]

    def formula(人, period, parameters):
        return numpy.where(人("所得税_ひとり親に当たるか", period), parameters(period).所得税.ひとり親控除.額, 0)


class 所得税_勤労学生控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "勤労学生控除の額（所得税法第82条）"
    reference = ["docs/public-sources/20261109_R1-laws_income-tax.md#2"]

    def formula(人, period, parameters):
        return numpy.where(人("所得税_勤労学生に当たるか", period), parameters(period).所得税.勤労学生控除.額, 0)


class 所得税_配偶者控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "配偶者控除の額（所得税法第83条）"
    reference = ["docs/public-sources/20261109_round2_spouse-laws-and-sources.md#1.2"]

    def formula(人, period, parameters):
        p = parameters(period).所得税.配偶者控除
        合計 = 人("所得税_合計所得金額", period)
        老人 = 人("所得税_老人控除対象配偶者に当たるか", period)
        額 = numpy.select(
            [合計 <= p.第1号.居住者の合計所得金額の上限, 合計 <= p.第2号.居住者の合計所得金額の上限, 合計 <= p.第3号.居住者の合計所得金額の上限],
            [
                numpy.where(老人, p.第1号.老人の額, p.第1号.額),
                numpy.where(老人, p.第2号.老人の額, p.第2号.額),
                numpy.where(老人, p.第3号.老人の額, p.第3号.額),
            ],
            0,
        )
        return numpy.where(人("所得税_控除対象配偶者に当たるか", period), 額, 0)


class 所得税_配偶者特別控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "配偶者特別控除の額（所得税法第83条の2）"
    reference = ["docs/public-sources/20261109_round2_spouse-laws-and-sources.md#1.3"]

    def formula(人, period, parameters):
        p = parameters(period).所得税.配偶者特別控除
        本人 = 人("所得税_合計所得金額", period)
        外 = 人("所得税_法律婚のグループ外の配偶者がいるか", period)  # 所令220①：相手が別の人を配偶者とした
        グループの配偶者 = 人.法律婚.sum(人("所得税_扶養等の判定に使う合計所得金額", period)) - 人("所得税_扶養等の判定に使う合計所得金額", period)
        配偶者 = numpy.where(外, 人("所得税_グループ外の配偶者の合計所得金額", period), グループの配偶者.round()).astype(numpy.int64)
        配偶者が扶養親族等 = numpy.where(
            外,
            人("所得税_グループ外の配偶者が他の居住者の扶養親族等とされているか", period),
            人.法律婚.sum(人("所得税_他の居住者の扶養親族等とされているか", period)) - 人("所得税_他の居住者の扶養親族等とされているか", period),
        )
        対象 = (
            ((人.法律婚.nb_persons() == 2) | 外)
            & 人("所得税_配偶者と生計を一にするか", period)
            & ~人("所得税_配偶者が青色事業専従者等か", period)
            & (配偶者 <= p.配偶者の合計所得金額の上限)
            & ~人("所得税_控除対象配偶者に当たるか", period)
            & (本人 <= p.居住者の合計所得金額の上限)
            & ~人("所得税_配偶者特別控除の適用除外に当たるか", period)
            & (配偶者が扶養親族等 == 0)
        )
        第1号の額 = spouse_special_first_item(配偶者, p)
        額 = numpy.select(
            [本人 <= p.第1号.居住者の合計所得金額の上限, 本人 <= p.第2号.居住者の合計所得金額の上限, 本人 <= p.第3号.居住者の合計所得金額の上限],
            [
                第1号の額,
                ceil_ratio_to_unit(第1号の額, p.第2号.率.分子, p.第2号.率.分母, p.端数を切り上げる単位),
                ceil_ratio_to_unit(第1号の額, p.第3号.率.分子, p.第3号.率.分母, p.端数を切り上げる単位),
            ],
            0,
        )
        return numpy.where(対象, 額, 0)


class 所得税_扶養控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "扶養控除の額（所得税法第84条、租税特別措置法第41条の16。申告者の扶養親族等の分の合計）"
    reference = ["docs/public-sources/20261109_round2_elderly-abroad-laws.md#1.1"]

    def formula(人, period, parameters):
        合計 = 人.扶養所属.sum(人("所得税_扶養控除の1人分の額", period) * 人.has_role(扶養所属.扶養親族等))
        return _as_yen(合計 * 人.has_role(扶養所属.申告者)) + 人("所得税_連鎖の扶養親族の扶養控除の額", period)


class 所得税_扶養控除の1人分の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "扶養控除の、その人が控除対象扶養親族に当たるときの1人分の額（申告者に集める。所法84、措法41の16）"
    reference = ["docs/public-sources/20261109_round2_elderly-abroad-laws.md#1.1"]

    def formula(人, period, parameters):
        p = parameters(period).所得税.扶養控除
        return numpy.select(
            [
                人("所得税_同居老親等に当たるか", period),
                人("所得税_老人扶養親族に当たるか", period),
                人("所得税_特定扶養親族に当たるか", period),
                人("所得税_控除対象扶養親族に当たるか", period),
            ],
            [p.老人扶養親族の額 + p.同居老親等の加算額, p.老人扶養親族の額, p.特定扶養親族の額, p.一般の額],
            0,
        )


class 所得税_特定親族特別控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "特定親族特別控除の額（所得税法第84条の2。申告者の扶養親族等の分の合計）"
    reference = ["docs/public-sources/20261109_R1-laws_income-tax.md#3"]

    def formula(人, period, parameters):
        合計 = 人.扶養所属.sum(人("所得税_特定親族特別控除の1人分の額", period) * 人.has_role(扶養所属.扶養親族等))
        return _as_yen(合計 * 人.has_role(扶養所属.申告者)) + 人("所得税_連鎖の扶養親族の特定親族特別控除の額", period)


class 所得税_特定親族特別控除の1人分の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "特定親族特別控除の、その人が特定親族に当たるときの1人分の額（申告者に集める。所法84の2）"
    reference = ["docs/public-sources/20261109_R1-laws_income-tax.md#3"]

    def formula(人, period, parameters):
        p = parameters(period).所得税.特定親族特別控除
        return _as_yen(
            (人("所得税_特定親族に当たるか", period) & ~人("所得税_特定親族特別控除の適用除外に当たるか", period))
            * specified_relative_amount(numpy.asarray(人("所得税_扶養等の判定に使う合計所得金額", period), dtype=numpy.int64), p)
        )


class 所得税_基礎控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "基礎控除の額（所得税法第86条と租税特別措置法第41条の16の2の加算）"
    reference = ["docs/public-sources/20261109_round2_gaps-sources.md#4.1"]

    def formula_2025_01_01(人, period, parameters):
        p = parameters(period).所得税.基礎控除
        特例 = parameters(period).所得税.基礎控除の特例
        加算 = 特例.令和7年分
        合計 = 人("所得税_合計所得金額", period)
        本則 = numpy.select(
            [合計 <= p.第1号.上限, 合計 <= p.第2号.上限, 合計 <= p.第3号.上限, 合計 <= p.第4号.上限],
            [p.第1号.額, p.第2号.額, p.第3号.額, p.第4号.額],
            0,
        )
        加算額 = numpy.select(
            [合計 <= 加算.イ.上限, 合計 <= 加算.ロ.上限, 合計 <= 加算.ハ.上限, 合計 <= 特例.合計所得金額の上限],
            [加算.イ.加算額, 加算.ロ.加算額, 加算.ハ.加算額, 加算.ニ.加算額],
            0,
        )
        return 本則 + 加算額

    def formula_2026_01_01(人, period, parameters):
        p = parameters(period).所得税.基礎控除
        特例 = parameters(period).所得税.基礎控除の特例
        加算 = 特例.令和8年分
        合計 = 人("所得税_合計所得金額", period)
        本則 = numpy.select(
            [合計 <= p.第1号.上限, 合計 <= p.第2号.上限, 合計 <= p.第3号.上限, 合計 <= p.第4号.上限],
            [p.第1号.額, p.第2号.額, p.第3号.額, p.第4号.額],
            0,
        )
        加算額 = numpy.select(
            [合計 <= 加算.イ.上限, 合計 <= 特例.合計所得金額の上限],
            [加算.イ.加算額, 加算.ロ.加算額],
            0,
        )
        return 本則 + 加算額


DEDUCTION_VARIABLES = (
    所得税_障害者控除の額,
    所得税_障害者控除の扶養親族の1人分の額,
    所得税_寡婦控除の額,
    所得税_ひとり親控除の額,
    所得税_勤労学生控除の額,
    所得税_配偶者控除の額,
    所得税_配偶者特別控除の額,
    所得税_扶養控除の額,
    所得税_扶養控除の1人分の額,
    所得税_特定親族特別控除の額,
    所得税_特定親族特別控除の1人分の額,
    所得税_基礎控除の額,
)

"""規則モジュール personal_deductions の変数：人の区分の層（その人だけで決まるもの）。

年齢・居住者・障害者・特別障害者・学生・配偶者の有無。材料は事実の層の入力（facts.py）。
"""

from __future__ import annotations

import numpy
from openfisca_core.model_api import YEAR, Variable

from ...country.entities import 人物, 扶養所属


def _ymd(d):  # noqa: ANN001, ANN202
    """datetime64[D] の配列を（年, 月, 日）の整数の配列にする。"""
    months = d.astype("datetime64[M]")
    y = d.astype("datetime64[Y]").astype(int) + 1970
    m = months.astype(int) % 12 + 1
    day = (d - months).astype(int) + 1
    return y, m, day


def age_at_end_of(birth, day):  # noqa: ANN001, ANN202
    """判定の日の終了時までに達した年齢（年齢計算ニ関スル法律・民法第143条）。

    年齢 n には、出生の日から起算した n 年目の応当する日の前日の終了時に達する（応当する日がない2月29日生まれは、平年の2月28日の終了時）。
    判定の日の翌日の暦の上の満年齢と同じになる：翌日が誕生日（応当する日）なら加わっている。
    1月1日生まれは、前年の12月31日の終了時に1つ加わる（国税庁の生年月日の範囲と全日付で一致：
    docs/measurements/20261109_impl-prep_misc-fetch-and-age-check.md §4.2）。
    """
    next_day = day + numpy.timedelta64(1, "D")
    y1, m1, d1 = _ymd(next_day)
    y0, m0, d0 = _ymd(birth)
    before_birthday = (m1 < m0) | ((m1 == m0) & (d1 < d0))
    return y1 - y0 - before_birthday.astype(int)


class 所得税_他の居住者の扶養親族等とされているか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "扶養の割当てで他の居住者の扶養親族等とされているか（扶養所属のグループの扶養親族等の役割か、連鎖の扶養親族等）"
    reference = ["docs/public-sources/20261109_impl-prep_misc-age-kinship-attribution.md#3.2"]

    def formula(人, period, parameters):
        return 人.has_role(扶養所属.扶養親族等) | 人("所得税_連鎖の扶養親族等か", period)


class 所得税_年齢(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "年齢（その年12月31日の現況。死亡したときは死亡の時の現況）"
    reference = ["docs/public-sources/20261109_impl-prep_misc-age-kinship-attribution.md#1.3", "docs/public-sources/20261111_impl-research3_kojo-misc-laws-and-nta.md#4"]

    def formula(人, period, parameters):
        # 12月31日の現況はその日の終了時の年齢。死亡の時の現況は、死亡の「時」がその日の途中なので、その日の終了時に加わる1歳を含めない
        # （前日の終了時までに達した年齢。所法85③ ただし書と年齢計算ニ関スル法律の法令の読み：docs/hypotheses/20261111_impl-research3_all-model.md H6）
        年末 = numpy.datetime64(f"{period.start.year}-12-31", "D")
        死亡日 = 人("所得税_死亡日", period)
        判定の日 = numpy.where(死亡日 <= 年末, 死亡日 - numpy.timedelta64(1, "D"), 年末)
        return age_at_end_of(人("所得税_生年月日", period), 判定の日)


class 所得税_居住者か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "居住者か（所得税法第2条第1項第3号。判定の時の住所の所在から）"
    reference = ["docs/public-sources/20261109_round2_elderly-abroad-laws.md#4"]

    def formula(人, period, parameters):
        return 人("所得税_判定の時に住所が国内にあるか", period)


class 所得税_障害者に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "障害者に当たるか（特別障害者を含む。所得税法施行令第10条第1項、所得税基本通達2−38）"
    reference = ["docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.5"]

    def formula(人, period, parameters):
        p = parameters(period).所得税.障害者
        市町村長等の認定 = 人("所得税_市町村長等の障害者の認定を受けているか", period) & (人("所得税_年齢", period) >= p.市町村長等の認定の年齢の下限)
        return (
            (人("所得税_身体障害者手帳の障害の程度の級", period) > 0)
            | (人("所得税_精神障害者保健福祉手帳の障害等級", period) > 0)
            | 人("所得税_知的障害者と判定されているか", period)
            | 人("所得税_重度の知的障害者と判定されているか", period)
            | 人("所得税_事理を弁識する能力を欠く常況にあるか", period)
            | 人("所得税_戦傷病者手帳の交付を受けているか", period)
            | 人("所得税_原子爆弾被爆者の認定を受けているか", period)
            | 人("所得税_常に就床を要し複雑な介護を要するか", period)
            | 市町村長等の認定
            | 人("所得税_手帳の申請中で障害が明らかか", period)
        )


class 所得税_特別障害者に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "特別障害者に当たるか（所得税法施行令第10条第2項）"
    reference = ["docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.5"]

    def formula(人, period, parameters):
        p = parameters(period).所得税.特別障害者
        身体 = 人("所得税_身体障害者手帳の障害の程度の級", period)
        市町村長等 = 人("所得税_市町村長等の特別障害者に準ずる認定を受けているか", period) & (
            人("所得税_年齢", period) >= parameters(period).所得税.障害者.市町村長等の認定の年齢の下限
        )
        return (
            ((身体 >= 1) & (身体 <= p.身体障害者手帳の級の上限))
            | 人("所得税_戦傷病者手帳に特別項症から第三項症までと記載されているか", period)
            | 市町村長等
            | (人("所得税_手帳の申請中で障害が明らかか", period) & 人("所得税_申請中の障害の程度が特別障害者の程度か", period))
            | (人("所得税_精神障害者保健福祉手帳の障害等級", period) == p.精神障害者保健福祉手帳の等級)
            | 人("所得税_重度の知的障害者と判定されているか", period)
            | 人("所得税_事理を弁識する能力を欠く常況にあるか", period)
            | 人("所得税_原子爆弾被爆者の認定を受けているか", period)
            | 人("所得税_常に就床を要し複雑な介護を要するか", period)
        )


class 所得税_学生に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "勤労学生の「学生」に当たるか（所得税法第2条第1項第32号イ・ロ・ハ）"
    reference = ["docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md#6.1"]

    def formula(人, period, parameters):
        return 人("所得税_学校教育法第1条の学校の学生等か", period) | 人("所得税_政令で定める課程を履修する専修学校等の学生等か", period)


class 所得税_配偶者がいるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "判定の時に法律上の配偶者がいるか"
    reference = ["docs/public-sources/20261109_round2_spouse-laws-and-sources.md#1.1"]

    def formula(人, period, parameters):
        return 人("所得税_判定の時に婚姻をしているか", period)


# 以下の5つ（扶養等の判定に使う…）：判定する人の判定の時が違う人は段が書いたその時の値、それ以外はその人自身の判定の時の値（PD-05）。


class 所得税_扶養等の判定に使う年齢(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "扶養親族等・配偶者として判定されるときの年齢（判定する人の判定の時の現況：所得税法第85条第3項。PD-05）"
    reference = ["docs/public-sources/20261109_impl-prep_misc-age-kinship-attribution.md#1.1"]

    def formula(人, period, parameters):
        return numpy.where(人("所得税_判定する人の判定の時の値を使うか", period), 人("所得税_判定する人の判定の時の年齢", period), 人("所得税_年齢", period))


class 所得税_扶養等の判定に使う居住者か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "扶養親族等として判定されるときに居住者か（判定する人の判定の時の住所：所得税法第85条第3項。PD-05）"
    reference = ["docs/public-sources/20261109_round2_elderly-abroad-laws.md#4"]

    def formula(人, period, parameters):
        return numpy.where(人("所得税_判定する人の判定の時の値を使うか", period), 人("所得税_判定する人の判定の時に居住者か", period), 人("所得税_居住者か", period))


class 所得税_扶養等の判定に使う留学により国内に住所及び居所を有しなくなった者か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "扶養親族等として判定されるときに留学により国内に住所及び居所を有しなくなった者か（判定する人の判定の時：PD-05）"
    reference = ["docs/public-sources/20261109_round2_elderly-abroad-laws.md#3.1"]

    def formula(人, period, parameters):
        return numpy.where(
            人("所得税_判定する人の判定の時の値を使うか", period),
            人("所得税_判定する人の判定の時に留学により国内に住所及び居所を有しなくなった者か", period),
            人("所得税_留学により国内に住所及び居所を有しなくなった者か", period),
        )


class 所得税_扶養等の判定に使う障害者か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "扶養親族等・配偶者として判定されるときに障害者に当たるか（判定する人の判定の時：PD-05）"
    reference = ["docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.5"]

    def formula(人, period, parameters):
        return numpy.where(人("所得税_判定する人の判定の時の値を使うか", period), 人("所得税_判定する人の判定の時に障害者に当たるか", period), 人("所得税_障害者に当たるか", period))


class 所得税_扶養等の判定に使う特別障害者か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "扶養親族等・配偶者として判定されるときに特別障害者に当たるか（判定する人の判定の時：PD-05）"
    reference = ["docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.5"]

    def formula(人, period, parameters):
        return numpy.where(人("所得税_判定する人の判定の時の値を使うか", period), 人("所得税_判定する人の判定の時に特別障害者に当たるか", period), 人("所得税_特別障害者に当たるか", period))


CLASSIFY_VARIABLES = (
    所得税_他の居住者の扶養親族等とされているか,
    所得税_年齢,
    所得税_居住者か,
    所得税_障害者に当たるか,
    所得税_特別障害者に当たるか,
    所得税_学生に当たるか,
    所得税_配偶者がいるか,
    所得税_扶養等の判定に使う年齢,
    所得税_扶養等の判定に使う居住者か,
    所得税_扶養等の判定に使う留学により国内に住所及び居所を有しなくなった者か,
    所得税_扶養等の判定に使う障害者か,
    所得税_扶養等の判定に使う特別障害者か,
)

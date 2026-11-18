"""規則モジュール personal_deductions の変数：人的控除・扶養の判定の層。

グループ（扶養所属・法律婚）は与えられた前提で書く（この版ではグループを組み立てない：concepts.yaml の先頭の注）。
扶養親族等の役割の人について「その申告者の」要件を判定し、法律婚の中の「自分でない配偶者」の値は 人.法律婚.sum(…) − 自分 で引く。
"""

from __future__ import annotations

import numpy
from openfisca_core.model_api import YEAR, Variable

from ...country.entities import 人物, 扶養所属


class 所得税_扶養等の判定に使う合計所得金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "扶養親族・同一生計配偶者などの判定に使う、その人の合計所得金額（判定する申告者が年の中途で死亡したときは、"
        "死亡の時の現況で見積もったその年の額：所得税基本通達85−1(2)）"
    )
    reference = ["docs/public-sources/20261111_impl-research3_kojo-misc-laws-and-nta.md#4"]

    def formula(人, period, parameters):
        return numpy.where(
            人("所得税_死亡した申告者のための見積りを使うか", period),
            人("所得税_死亡した申告者のための合計所得金額の見積額", period),
            人("所得税_合計所得金額", period),
        )


class 所得税_扶養親族の合計所得金額要件(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "扶養親族の要件のうち、合計所得金額が上限以下であること（所得税法第2条第1項第34号）。ほかの要件（生計・親族など）は含まない"
    reference = ["docs/public-sources/20261109_R1-laws_income-tax.md#2"]

    def formula_2025_01_01(人, period, parameters):
        上限 = parameters(period).所得税.扶養親族.合計所得金額の上限
        # 扶養等の判定に使う合計所得金額 と同じ（死亡した申告者のための見積り：所基通85−1(2)）。合計所得金額からの縦の1本を式に残す
        合計 = numpy.where(
            人("所得税_死亡した申告者のための見積りを使うか", period),
            人("所得税_死亡した申告者のための合計所得金額の見積額", period),
            人("所得税_合計所得金額", period),
        )
        return 合計 <= 上限


class 所得税_扶養親族に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "扶養所属の申告者の扶養親族に当たるか（所得税法第2条第1項第34号。16歳未満を含む）"
    reference = ["docs/public-sources/20261109_R1-laws_income-tax.md#4"]

    def formula(人, period, parameters):
        return (
            人("所得税_他の居住者の扶養親族等とされているか", period)
            & 人("所得税_申告者の親族か", period)
            & 人("所得税_申告者と生計を一にするか", period)
            & ~人("所得税_申告者等の事業専従者か", period)
            & 人("所得税_扶養親族の合計所得金額要件", period)
        )


class 所得税_控除対象扶養親族に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "控除対象扶養親族に当たるか（所得税法第2条第1項第34号の2）"
    reference = ["docs/public-sources/20261109_round2_elderly-abroad-laws.md#3.1"]

    def formula(人, period, parameters):
        p = parameters(period).所得税.控除対象扶養親族
        # 年齢・住所・留学・障害は、判定する申告者の判定の時の現況（所法85③。申告者の判定の時が違う人は段が書いたその時の値：PD-05）
        年齢 = 人("所得税_扶養等の判定に使う年齢", period)
        非 = p.非居住者
        区分の要件なし = ((年齢 >= 非.年齢の下限) & (年齢 < 非.区分の要件のない年齢の上限)) | (年齢 >= 非.区分の要件のない高い年齢の下限)
        書類 = 人("所得税_国外居住親族の書類の要件を満たすか", period)
        # 30歳以上70歳未満は区分ごとに書類が違う（所法120③三、所令262④）：障害者は第1号（親族関係書類・送金関係書類）、
        # 留学は第2号（第1号の書類と留学ビザ等書類）、38万円以上は第3号（親族関係書類と38万円送金書類）。どれか1つの区分の要件と書類があれば当たる
        区分の要件あり = (
            (年齢 >= 非.区分の要件のない年齢の上限)
            & (年齢 < 非.区分の要件のない高い年齢の下限)
            & (
                (人("所得税_扶養等の判定に使う留学により国内に住所及び居所を有しなくなった者か", period) & 人("所得税_国外居住親族の留学の区分の書類の要件を満たすか", period))
                | (人("所得税_扶養等の判定に使う障害者か", period) & 書類)
                | (
                    (人("所得税_申告者から受けた生活費等の支払の額", period) >= 非.生活費等の支払の額の下限)
                    & 人("所得税_国外居住親族の38万円以上の区分の書類の要件を満たすか", period)
                )
            )
        )
        非居住者として当たる = (区分の要件なし & 書類) | 区分の要件あり
        居住者として当たる = 年齢 >= p.居住者の年齢の下限
        return 人("所得税_扶養親族に当たるか", period) & numpy.where(人("所得税_扶養等の判定に使う居住者か", period), 居住者として当たる, 非居住者として当たる)


class 所得税_特定扶養親族に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "特定扶養親族に当たるか（所得税法第2条第1項第34号の3）"
    reference = ["docs/public-sources/20261109_R1-laws_income-tax.md#4"]

    def formula(人, period, parameters):
        p = parameters(period).所得税.特定扶養親族
        年齢 = 人("所得税_扶養等の判定に使う年齢", period)
        return 人("所得税_控除対象扶養親族に当たるか", period) & (年齢 >= p.年齢の下限) & (年齢 < p.年齢の上限)


class 所得税_老人扶養親族に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "老人扶養親族に当たるか（所得税法第2条第1項第34号の4）"
    reference = ["docs/public-sources/20261109_round2_elderly-abroad-laws.md#1.1"]

    def formula(人, period, parameters):
        p = parameters(period).所得税.老人扶養親族
        return 人("所得税_控除対象扶養親族に当たるか", period) & (人("所得税_扶養等の判定に使う年齢", period) >= p.年齢の下限)


class 所得税_同居老親等に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "同居老親等に当たるか（租税特別措置法第41条の16第1項）"
    reference = ["docs/public-sources/20261109_round2_elderly-abroad-laws.md#2.1"]

    def formula(人, period, parameters):
        return (
            人("所得税_老人扶養親族に当たるか", period)
            & 人("所得税_申告者の直系尊属か", period)
            & 人("所得税_申告者と同居を常況としているか", period)
        )


class 所得税_特定親族に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "特定親族に当たるか（所得税法第84条の2第1項）"
    reference = ["docs/public-sources/20261109_R1-laws_income-tax.md#3"]

    def formula(人, period, parameters):
        p = parameters(period).所得税.特定親族
        年齢 = 人("所得税_扶養等の判定に使う年齢", period)
        return (
            人("所得税_他の居住者の扶養親族等とされているか", period)
            & (年齢 >= p.年齢の下限)
            & (年齢 < p.年齢の上限)
            & 人("所得税_申告者の親族か", period)
            & 人("所得税_申告者と生計を一にするか", period)
            & ~人("所得税_申告者等の事業専従者か", period)
            & 人("所得税_特定親族の合計所得金額要件", period)
            & ~人("所得税_控除対象扶養親族に当たるか", period)
        )


class 所得税_特定親族の合計所得金額要件(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "特定親族の要件のうち、合計所得金額が上限以下であること（所得税法第84条の2第1項。境目の説明の判定。ほかの要件は含まない）"
    reference = ["docs/public-sources/20261109_R1-laws_income-tax.md#3"]

    def formula(人, period, parameters):
        return 人("所得税_扶養等の判定に使う合計所得金額", period) <= parameters(period).所得税.特定親族.合計所得金額の上限


def step_upper(x, origin, multiplier, step, minus):  # noqa: ANN001, ANN202
    """「(x − origin)×multiplier を step の整数倍から minus を引いた額に切り下げる」区分で、x と同じ額になる x の上限（境目の説明の基準）。

    切り下げた額（deductions.round_down_to_step）は (x − origin)×multiplier + minus が step の整数倍に達したときに変わるので、
    次に変わる x は origin + ceil(((k+1)×step − minus) / multiplier)（k は今の倍数）で、その1円前が上限。
    """
    k = ((x - origin) * multiplier + minus) // step
    nxt = (k + 1) * step - minus
    return origin + (nxt + multiplier - 1) // multiplier - 1


def tier_upper(x, bounds):  # noqa: ANN001, ANN202
    """段階の上限の列 bounds（昇順）のうち、x 以下にならない最初のもの（全部を超えれば最後のもの）。"""
    out = numpy.full(numpy.shape(x), bounds[-1], dtype=numpy.int64)
    for b in reversed(bounds):
        out = numpy.where(x <= b, b, out)
    return out


class 所得税_特定親族特別控除の段階の上限(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "特定親族特別控除の額（所得税法第84条の2第1項各号）が今の額のままである、その人の合計所得金額の上限"
        "（第2号の中は十万円の刻みで変わる額の段。特定親族の上限を超えれば特定親族の上限。境目の説明の基準）"
    )
    reference = ["docs/public-sources/20261109_R1-laws_income-tax.md#3"]

    def formula(人, period, parameters):
        p = parameters(period).所得税.特定親族特別控除
        上限 = int(parameters(period).所得税.特定親族.合計所得金額の上限)
        x = numpy.asarray(人("所得税_扶養等の判定に使う合計所得金額", period), dtype=numpy.int64)
        二 = p.第2号
        第2号の段 = numpy.minimum(step_upper(x, int(二.超える部分の起点), int(二.乗数), int(二.刻み), int(二.刻みから引く額)), int(二.上限))
        return numpy.select(
            [x <= p.第1号.上限, x <= 二.上限, x <= p.第3号.上限],
            [int(p.第1号.上限), 第2号の段, int(p.第3号.上限)],
            上限,
        )


class 所得税_特定親族の合計所得金額が特定親族特別控除の段階の上限以下か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "合計所得金額が、特定親族特別控除の額が今の額のままである上限以下か（境目の説明の判定。特定親族の上限を超えれば偽）"
    reference = ["docs/public-sources/20261109_R1-laws_income-tax.md#3"]

    def formula(人, period, parameters):
        return 人("所得税_扶養等の判定に使う合計所得金額", period) <= 人("所得税_特定親族特別控除の段階の上限", period)


class 所得税_同一生計配偶者に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "同一生計配偶者に当たるか（本人から見た配偶者について。所得税法第2条第1項第33号）"
    reference = ["docs/public-sources/20261109_round2_spouse-laws-and-sources.md#1.1"]

    def formula(人, period, parameters):
        外 = 人("所得税_法律婚のグループ外の配偶者がいるか", period)  # 所令220①：相手が別の人を配偶者とした（グループの代わりに段の入力を使う）
        配偶者が扶養親族等 = numpy.where(
            外,
            人("所得税_グループ外の配偶者が他の居住者の扶養親族等とされているか", period),
            人.法律婚.sum(人("所得税_他の居住者の扶養親族等とされているか", period)) - 人("所得税_他の居住者の扶養親族等とされているか", period),
        )
        return (
            ((人.法律婚.nb_persons() == 2) | 外)
            & 人("所得税_配偶者と生計を一にするか", period)
            & ~人("所得税_配偶者が青色事業専従者等か", period)
            & 人("所得税_同一生計配偶者の合計所得金額要件", period)
            & (配偶者が扶養親族等 == 0)
        )


class 所得税_同一生計配偶者の合計所得金額要件(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = (
        "同一生計配偶者の要件のうち、配偶者の合計所得金額が上限以下であること（本人から見た配偶者について。所得税法第2条第1項第33号。"
        "境目の説明の判定。配偶者がいなければ比べる額は0）"
    )
    reference = ["docs/public-sources/20261109_round2_spouse-laws-and-sources.md#1.1"]

    def formula(人, period, parameters):
        return 人("所得税_配偶者の合計所得金額", period) <= parameters(period).所得税.同一生計配偶者.合計所得金額の上限


class 所得税_控除対象配偶者に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "控除対象配偶者に当たるか（本人の合計所得金額1,000万円以下。所得税法第2条第1項第33号の2）"
    reference = ["docs/public-sources/20261109_round2_spouse-laws-and-sources.md#1.1"]

    def formula(人, period, parameters):
        return 人("所得税_同一生計配偶者に当たるか", period) & 人("所得税_控除対象配偶者の本人の合計所得金額要件", period)


class 所得税_控除対象配偶者の本人の合計所得金額要件(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "控除対象配偶者の要件のうち、本人（居住者）の合計所得金額が上限以下であること（所得税法第2条第1項第33号の2。境目の説明の判定）"
    reference = ["docs/public-sources/20261109_round2_spouse-laws-and-sources.md#1.1"]

    def formula(人, period, parameters):
        return 人("所得税_合計所得金額", period) <= parameters(period).所得税.控除対象配偶者.居住者の合計所得金額の上限


class 所得税_配偶者特別控除の配偶者の段階の上限(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "配偶者特別控除の第1号の額（所得税法第83条の2第1項第1号イ・ロ・ハ）が今の額のままである、配偶者の合計所得金額の上限"
        "（ロの中は五万円の刻みで変わる額の段。配偶者の上限を超えれば配偶者の上限。境目の説明の基準）"
    )
    reference = ["docs/public-sources/20261109_round2_spouse-laws-and-sources.md#1.3"]

    def formula(人, period, parameters):
        p = parameters(period).所得税.配偶者特別控除
        x = numpy.asarray(人("所得税_配偶者の合計所得金額", period), dtype=numpy.int64)
        イ, ロ = p.第1号.イ, p.第1号.ロ
        ロの段 = numpy.minimum(step_upper(x, int(ロ.超える部分の起点), 1, int(ロ.刻み), int(ロ.刻みから引く額)), int(ロ.上限))
        return numpy.select([x <= イ.上限, x <= ロ.上限], [int(イ.上限), ロの段], int(p.配偶者の合計所得金額の上限))


class 所得税_配偶者の合計所得金額が配偶者特別控除の段階の上限以下か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "配偶者の合計所得金額が、配偶者特別控除の第1号の額が今の額のままである上限以下か（境目の説明の判定。配偶者の上限を超えれば偽）"
    reference = ["docs/public-sources/20261109_round2_spouse-laws-and-sources.md#1.3"]

    def formula(人, period, parameters):
        return 人("所得税_配偶者の合計所得金額", period) <= 人("所得税_配偶者特別控除の配偶者の段階の上限", period)


class 所得税_配偶者控除等の本人の段階の上限(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "配偶者控除・配偶者特別控除の額の号（所得税法第83条第1項各号・第83条の2第1項各号：本人の合計所得金額900万円・950万円・1,000万円）が"
        "今の号のままである、本人の合計所得金額の上限（全部を超えれば最後の上限。境目の説明の基準）"
    )
    reference = ["docs/public-sources/20261109_round2_spouse-laws-and-sources.md#1.1", "docs/public-sources/20261109_round2_spouse-laws-and-sources.md#1.3"]

    def formula(人, period, parameters):
        p = parameters(period).所得税.配偶者控除
        q = parameters(period).所得税.配偶者特別控除
        bounds = sorted(
            {int(p.第1号.居住者の合計所得金額の上限), int(p.第2号.居住者の合計所得金額の上限), int(p.第3号.居住者の合計所得金額の上限)}
            | {int(q.第1号.居住者の合計所得金額の上限), int(q.第2号.居住者の合計所得金額の上限), int(q.第3号.居住者の合計所得金額の上限)}
        )
        return tier_upper(numpy.asarray(人("所得税_合計所得金額", period), dtype=numpy.int64), bounds)


class 所得税_合計所得金額が配偶者控除等の本人の段階の上限以下か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "本人の合計所得金額が、配偶者控除・配偶者特別控除の額の号が今の号のままである上限以下か（境目の説明の判定。1,000万円を超えれば偽）"
    reference = ["docs/public-sources/20261109_round2_spouse-laws-and-sources.md#1.1"]

    def formula(人, period, parameters):
        return 人("所得税_合計所得金額", period) <= 人("所得税_配偶者控除等の本人の段階の上限", period)


class 所得税_老人控除対象配偶者に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "老人控除対象配偶者に当たるか（配偶者の年齢70歳以上。所得税法第2条第1項第33号の3）"
    reference = ["docs/public-sources/20261109_round2_spouse-laws-and-sources.md#1.1"]

    def formula(人, period, parameters):
        p = parameters(period).所得税.老人控除対象配偶者
        配偶者の年齢 = numpy.where(
            人("所得税_法律婚のグループ外の配偶者がいるか", period),
            人("所得税_グループ外の配偶者の年齢", period),
            人.法律婚.sum(人("所得税_扶養等の判定に使う年齢", period)) - 人("所得税_扶養等の判定に使う年齢", period),
        )
        return 人("所得税_控除対象配偶者に当たるか", period) & (配偶者の年齢 >= p.年齢の下限)


class 所得税_同居特別障害者に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "同居特別障害者に当たるか（障害者である本人の側。所得税法第79条第3項）"
    reference = ["docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.2"]

    def formula(人, period, parameters):
        扶養親族として = 人("所得税_扶養親族に当たるか", period) & 人("所得税_申告者等と同居を常況としているか", period)
        相手の同一生計配偶者か = (人.法律婚.sum(人("所得税_同一生計配偶者に当たるか", period)) - 人("所得税_同一生計配偶者に当たるか", period)) > 0
        配偶者として = 相手の同一生計配偶者か & 人("所得税_配偶者等と同居を常況としているか", period)
        return 人("所得税_扶養等の判定に使う特別障害者か", period) & (扶養親族として | 配偶者として)


class 所得税_ひとり親に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "ひとり親に当たるか（所得税法第2条第1項第31号）"
    reference = ["docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.1"]

    def formula(人, period, parameters):
        本人の要件 = (
            (~人("所得税_配偶者がいるか", period) | 人("所得税_配偶者の生死が明らかでない者か", period))
            & 人("所得税_ひとり親の合計所得金額要件", period)
            & ~人("所得税_住民票に事実婚の続柄の記載がある相手がいるか", period)
            & 人.has_role(扶養所属.申告者)
        )
        連鎖 = 人("所得税_連鎖のひとり親の子がいるか", period)
        if not (人("所得税_他の居住者の扶養親族等とされているか", period).any() or 連鎖.any()):
            # 扶養親族等の役割の子がいないので当たらない。総所得金額等 を引かない（引くと、子のいない人まで対象外の伝搬が起こる）
            return 本人の要件 & False
        子の数 = 人.扶養所属.sum(人("所得税_ひとり親の子に当たるか", period) * 人.has_role(扶養所属.扶養親族等))
        return 本人の要件 & ((子の数 > 0) | 連鎖)


class 所得税_ひとり親の子に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "ひとり親の要件の子に当たるか（扶養親族等の役割の人で、申告者の子、総所得金額等が基準以下。所法2①三十一イ、所令11の2②）"
    reference = ["docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.1"]

    def formula(人, period, parameters):
        return (
            人("所得税_他の居住者の扶養親族等とされているか", period)
            & 人("所得税_申告者の子か", period)
            & 人("所得税_ひとり親の子の総所得金額等要件", period)
        )


class 所得税_ひとり親の合計所得金額要件(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "ひとり親の要件のうち、本人の合計所得金額が上限以下であること（所得税法第2条第1項第31号ハ。境目の説明の判定）"
    reference = ["docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.1"]

    def formula(人, period, parameters):
        return 人("所得税_合計所得金額", period) <= parameters(period).所得税.ひとり親.合計所得金額の上限


class 所得税_ひとり親の子の総所得金額等要件(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "ひとり親の要件の子のうち、その子の総所得金額等が基準以下であること（所得税法施行令第11条の2第2項。境目の説明の判定）"
    reference = ["docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.1"]

    def formula(人, period, parameters):
        return 人("所得税_総所得金額等", period) <= parameters(period).所得税.ひとり親.子の総所得金額等の上限


class 所得税_寡婦に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "寡婦に当たるか（所得税法第2条第1項第30号）"
    reference = ["docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.1"]

    def formula(人, period, parameters):
        扶養親族を有する = ((人.扶養所属.sum(人("所得税_扶養親族に当たるか", period) * 人.has_role(扶養所属.扶養親族等)) > 0) & 人.has_role(扶養所属.申告者)) | 人("所得税_連鎖の扶養親族がいるか", period)
        イ = 人("所得税_夫と離婚した後婚姻をしていない者か", period) & ~人("所得税_配偶者がいるか", period) & 扶養親族を有する
        ロ = 人("所得税_夫と死別した後婚姻をしていない者又は夫の生死の明らかでない者か", period)
        return (
            (イ | ロ)
            & 人("所得税_寡婦の合計所得金額要件", period)
            & ~人("所得税_住民票に事実婚の続柄の記載がある相手がいるか", period)
            & ~人("所得税_ひとり親に当たるか", period)
        )


class 所得税_勤労学生に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "勤労学生に当たるか（所得税法第2条第1項第32号）"
    reference = ["docs/public-sources/20261109_round2_gaps-sources.md#1.1"]

    def formula(人, period, parameters):
        事業所得等 = 人("所得税_事業所得の金額", period) + 人("所得税_雑所得の金額", period)
        勤労の事業所得等 = numpy.where(人("所得税_事業所得等が自己の勤労に基づくか", period), 事業所得等, 0)
        給与所得等を有する = (人("所得税_給与等の収入金額", period) > 0) | (人("所得税_退職所得の金額", period) != 0) | (勤労の事業所得等 != 0)
        return (
            人("所得税_学生に当たるか", period)
            & 給与所得等を有する
            & 人("所得税_勤労学生の合計所得金額要件", period)
            & 人("所得税_勤労学生の給与所得等以外の所得要件", period)
        )


class 所得税_寡婦の合計所得金額要件(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "寡婦の要件のうち、合計所得金額が上限以下であること（所得税法第2条第1項第30号。境目の説明の判定）"
    reference = ["docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.1"]

    def formula(人, period, parameters):
        return 人("所得税_合計所得金額", period) <= parameters(period).所得税.寡婦.合計所得金額の上限


class 所得税_勤労学生の合計所得金額要件(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "勤労学生の要件のうち、合計所得金額が上限以下であること（所得税法第2条第1項第32号。境目の説明の判定）"
    reference = ["docs/public-sources/20261109_R1-laws_income-tax.md#2"]

    def formula(人, period, parameters):
        return 人("所得税_合計所得金額", period) <= parameters(period).所得税.勤労学生.合計所得金額の上限


class 所得税_勤労学生の給与所得等以外の所得の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "合計所得金額のうち給与所得等（自己の勤労に基づく給与所得・退職所得・事業所得・雑所得）以外の所得に係る部分の金額"
        "（所得税法第2条第1項第32号、所得税基本通達2−44。給与所得・退職所得は勤労に基づくとする法令の読み）"
    )
    reference = ["docs/public-sources/20261109_round2_gaps-sources.md#1.1", "docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md#6.2"]

    def formula(人, period, parameters):
        事業所得等 = 人("所得税_事業所得の金額", period) + 人("所得税_雑所得の金額", period)
        勤労の事業所得等 = numpy.where(人("所得税_事業所得等が自己の勤労に基づくか", period), 事業所得等, 0)
        給与所得等の金額 = 人("所得税_給与所得", period) + 人("所得税_退職所得の金額", period) + 勤労の事業所得等
        return 人("所得税_合計所得金額", period) - 給与所得等の金額


class 所得税_勤労学生の給与所得等以外の所得要件(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "勤労学生の要件のうち、給与所得等以外の所得に係る部分の金額が上限以下であること（所得税法第2条第1項第32号。境目の説明の判定）"
    reference = ["docs/public-sources/20261109_round2_gaps-sources.md#1.1"]

    def formula(人, period, parameters):
        return 人("所得税_勤労学生の給与所得等以外の所得の金額", period) <= parameters(period).所得税.勤労学生.給与所得等以外の所得の上限


def _basic_bounds(p, 特例, 加算_上限):  # noqa: ANN001, ANN202
    """基礎控除の額が変わる合計所得金額の上限の列（本則の各号と、特例〔措法41の16の2〕の区分の上限。昇順）。"""
    本則 = [int(p.第1号.上限), int(p.第2号.上限), int(p.第3号.上限), int(p.第4号.上限)]
    return sorted({*本則, *(int(x) for x in 加算_上限), int(特例.合計所得金額の上限)})


class 所得税_基礎控除の段階の上限(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "基礎控除の額（所得税法第86条第1項各号と租税特別措置法第41条の16の2の加算の区分）が今の額のままである、その人の合計所得金額の上限"
        "（全部を超えれば最後の上限。境目の説明の基準）"
    )
    reference = ["docs/public-sources/20261109_R1-laws_income-tax.md#2"]

    def formula_2025_01_01(人, period, parameters):
        p = parameters(period).所得税.基礎控除
        特例 = parameters(period).所得税.基礎控除の特例
        加算 = 特例.令和7年分
        bounds = _basic_bounds(p, 特例, (加算.イ.上限, 加算.ロ.上限, 加算.ハ.上限))
        return tier_upper(numpy.asarray(人("所得税_合計所得金額", period), dtype=numpy.int64), bounds)

    def formula_2026_01_01(人, period, parameters):
        p = parameters(period).所得税.基礎控除
        特例 = parameters(period).所得税.基礎控除の特例
        bounds = _basic_bounds(p, 特例, (特例.令和8年分.イ.上限,))
        return tier_upper(numpy.asarray(人("所得税_合計所得金額", period), dtype=numpy.int64), bounds)


class 所得税_合計所得金額が基礎控除の段階の上限以下か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "合計所得金額が、基礎控除の額が今の額のままである上限以下か（境目の説明の判定。2,500万円を超えれば偽）"
    reference = ["docs/public-sources/20261109_R1-laws_income-tax.md#2"]

    def formula(人, period, parameters):
        return 人("所得税_合計所得金額", period) <= 人("所得税_基礎控除の段階の上限", period)


JUDGMENT_VARIABLES = (
    所得税_扶養等の判定に使う合計所得金額,
    所得税_扶養親族の合計所得金額要件,
    所得税_扶養親族に当たるか,
    所得税_控除対象扶養親族に当たるか,
    所得税_特定扶養親族に当たるか,
    所得税_老人扶養親族に当たるか,
    所得税_同居老親等に当たるか,
    所得税_特定親族に当たるか,
    所得税_同一生計配偶者に当たるか,
    所得税_控除対象配偶者に当たるか,
    所得税_老人控除対象配偶者に当たるか,
    所得税_同居特別障害者に当たるか,
    所得税_ひとり親の子に当たるか,
    所得税_ひとり親に当たるか,
    所得税_寡婦に当たるか,
    所得税_勤労学生に当たるか,
    所得税_特定親族の合計所得金額要件,
    所得税_特定親族特別控除の段階の上限,
    所得税_特定親族の合計所得金額が特定親族特別控除の段階の上限以下か,
    所得税_同一生計配偶者の合計所得金額要件,
    所得税_控除対象配偶者の本人の合計所得金額要件,
    所得税_配偶者特別控除の配偶者の段階の上限,
    所得税_配偶者の合計所得金額が配偶者特別控除の段階の上限以下か,
    所得税_配偶者控除等の本人の段階の上限,
    所得税_合計所得金額が配偶者控除等の本人の段階の上限以下か,
    所得税_ひとり親の合計所得金額要件,
    所得税_ひとり親の子の総所得金額等要件,
    所得税_寡婦の合計所得金額要件,
    所得税_勤労学生の合計所得金額要件,
    所得税_勤労学生の給与所得等以外の所得の金額,
    所得税_勤労学生の給与所得等以外の所得要件,
    所得税_基礎控除の段階の上限,
    所得税_合計所得金額が基礎控除の段階の上限以下か,
)

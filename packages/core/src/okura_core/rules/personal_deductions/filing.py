"""規則モジュール personal_deductions：申告書の欄が使う人をまたぐ値（2026-11-12。forms の行の割当て・第一表 57・人数・国外居住の区分）。

- 所得税_法律婚の相手：段 扶養の割当て が書く入力（allocation._spouse_inputs が決めた法律婚の相手の人の ID。いなければ「なし」）。
  様式の対応表が第二表の1行目（配偶者）に載せる人を決める（forms/rows.py）。
- 所得税_扶養親族等とする申告者：所得税_扶養親族等の申告者（段の入力。いなければ空）の空を「なし」にした値（結果の区分の値は空にできない）。
  様式の対応表が第二表の2行目以後に載せる人を決める。
- 所得税_連鎖の特定親族特別控除の人数：段 扶養の連鎖の合計 が書く入力（連鎖の人のうち特定親族特別控除の1人分の額が正の人の数）。
- 所得税_配偶者の合計所得金額：配偶者特別控除の額の式（deductions.py）が使う配偶者の合計所得金額と同じ値（第一表 57。手引き 3-5_01）。
- 所得税_特定親族特別控除を受ける人数：申告者の扶養所属の特定親族特別控除の1人分の額が正の人の数（連鎖の人を含む。第一表 G109。手引き 3-3_20）。
- 所得税_国外居住親族の区分：第二表「国外居住」欄の区分（TB27：elderly-abroad-guidance §3.2）。所法2①三十四の二ロ の年齢と区分の要件に当てる。
"""

from __future__ import annotations

import numpy
from openfisca_core.model_api import YEAR, Variable

from ...country.entities import 人物, 扶養所属

_SPOUSE = "docs/public-sources/20261109_round2_spouse-laws-and-sources.md#1.3"
_FORMS = "docs/public-sources/20261109_round2_yoshiki-forms-r07.md#2"
_ABROAD_LAW = "docs/public-sources/20261109_round2_elderly-abroad-laws.md#3.1"
_ABROAD_FORM = "docs/public-sources/20261109_round2_elderly-abroad-guidance.md#3.2"
_MISC = "docs/public-sources/20261109_impl-prep_misc-age-kinship-attribution.md#3.2"

#: 人の ID の値がないとき（結果の区分の値は空でない文字列：result.Category。人の ID は ASCII なので衝突しない）。
NO_PERSON = "なし"

#: 国外居住親族の区分（TB27 の 1〜5 の区分の名前。様式の番号への対応は様式の対応表）。
ABROAD_NONE = "居住者"
ABROAD_UNDER16 = "16歳未満"
ABROAD_GENERAL = "16歳以上30歳未満又は70歳以上"
ABROAD_STUDY = "留学"
ABROAD_DISABLED = "障害者"
ABROAD_380K = "38万円以上"
ABROAD_STUDY_AND_380K = "留学及び38万円以上"  # TB27（注2）：添付・提示する書類で 2 か 4（書類の選び方は入力の事実）
ABROAD_OTHER = "該当なし"


class 所得税_法律婚の相手(Variable):
    value_type = str
    entity = 人物
    default_value = NO_PERSON
    definition_period = YEAR
    label = "法律婚の相手の人の ID（段 扶養の割当て が決めた配偶者。いなければ「なし」。様式の配偶者の行に使う）"
    reference = [_MISC]


class 所得税_連鎖の特定親族特別控除の人数(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "連鎖の扶養親族等のうち特定親族特別控除の1人分の額が正の人の数（段 扶養の連鎖の合計 が書く入力）"
    reference = [_MISC]


class 所得税_扶養親族等とする申告者(Variable):
    value_type = str
    entity = 人物
    default_value = NO_PERSON
    definition_period = YEAR
    label = "扶養の割当てで決まった申告者の人の ID（いなければ「なし」。所得税_扶養親族等の申告者 の空を「なし」にした値：結果の区分の値は空にできない）"
    reference = [_MISC]

    def formula(人, period, parameters):
        c = 人("所得税_扶養親族等の申告者", period)
        return numpy.array([str(x) if str(x) else NO_PERSON for x in c], dtype=object)


class 所得税_配偶者の合計所得金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "配偶者の合計所得金額（配偶者特別控除の額の判定に使う額。第一表 57）"
    reference = [_SPOUSE, _FORMS]

    def formula(人, period, parameters):
        外 = 人("所得税_法律婚のグループ外の配偶者がいるか", period)
        グループの配偶者 = 人.法律婚.sum(人("所得税_扶養等の判定に使う合計所得金額", period)) - 人("所得税_扶養等の判定に使う合計所得金額", period)
        いる = (人.法律婚.nb_persons() == 2) | 外
        額 = numpy.where(外, 人("所得税_グループ外の配偶者の合計所得金額", period), numpy.asarray(グループの配偶者).round())
        return numpy.where(いる, 額, 0).astype(numpy.int64)


class 所得税_特定親族特別控除を受ける人数(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "特定親族特別控除を受ける特定親族の人数（申告者の扶養所属の、1人分の額が正の人。連鎖の人を含む。第一表 G109）"
    reference = ["docs/public-sources/20261109_R1-laws_income-tax.md#3", _FORMS]

    def formula(人, period, parameters):
        数 = 人.扶養所属.sum((人("所得税_特定親族特別控除の1人分の額", period) > 0) * 人.has_role(扶養所属.扶養親族等))
        return (numpy.asarray(数).round().astype(numpy.int64) * 人.has_role(扶養所属.申告者)) + 人("所得税_連鎖の特定親族特別控除の人数", period)


class 所得税_国外居住親族の区分(Variable):
    value_type = str
    entity = 人物
    definition_period = YEAR
    label = "国外居住親族の区分（第二表の国外居住の欄。居住者なら「居住者」）"
    reference = [_ABROAD_LAW, _ABROAD_FORM]

    def formula(人, period, parameters):
        p = parameters(period).所得税.控除対象扶養親族.非居住者
        居住者 = 人("所得税_扶養等の判定に使う居住者か", period)
        年齢 = 人("所得税_扶養等の判定に使う年齢", period)
        # 30歳以上70歳未満の区分は、控除対象扶養親族に当たるかの式（judgments.py）と同じ要件と書類で読む（所法120③三、所令262④）
        留学 = 人("所得税_扶養等の判定に使う留学により国内に住所及び居所を有しなくなった者か", period) & 人(
            "所得税_国外居住親族の留学の区分の書類の要件を満たすか", period
        )
        障害者 = 人("所得税_扶養等の判定に使う障害者か", period)
        送金38 = (人("所得税_申告者から受けた生活費等の支払の額", period) >= p.生活費等の支払の額の下限) & 人(
            "所得税_国外居住親族の38万円以上の区分の書類の要件を満たすか", period
        )
        return numpy.select(
            [
                居住者,
                年齢 < p.年齢の下限,
                (年齢 < p.区分の要件のない年齢の上限) | (年齢 >= p.区分の要件のない高い年齢の下限),
                障害者,
                留学 & 送金38,
                留学,
                送金38,
            ],
            [ABROAD_NONE, ABROAD_UNDER16, ABROAD_GENERAL, ABROAD_DISABLED, ABROAD_STUDY_AND_380K, ABROAD_STUDY, ABROAD_380K],
            ABROAD_OTHER,
        ).astype(object)


#: 段 扶養の割当て・扶養の連鎖の合計 が書く入力（allocation.py の ALLOC_WRITES・run_chain）。
STAGE_INPUT_VARIABLES = (所得税_法律婚の相手, 所得税_連鎖の特定親族特別控除の人数)

FILING_VARIABLES = (
    *STAGE_INPUT_VARIABLES,
    所得税_扶養親族等とする申告者,
    所得税_配偶者の合計所得金額,
    所得税_特定親族特別控除を受ける人数,
    所得税_国外居住親族の区分,
)

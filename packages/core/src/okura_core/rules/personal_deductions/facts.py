"""規則モジュール personal_deductions の事実の層の入力変数（式を持たない。inputs.py が中間表現から書く）。

evaluate は全員の値を必ず書く（registry の約束）。既定値は、OpenFisca を直接使うテスト・トレースの検査のためのもの。
"""

from __future__ import annotations

import datetime as _dt

from openfisca_core.model_api import YEAR, Variable

from ...country.entities import 人物

#: 死亡していない人の死亡日（式は年分の12月31日との早い方を判定の時にする）。
NOT_DEAD = _dt.date(9999, 12, 31)

_JINTEKI_15 = "docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.5"


class 所得税_生年月日(Variable):
    value_type = _dt.date
    entity = 人物
    definition_period = YEAR
    label = "生年月日（中間表現の persons[].birth_on）"
    reference = ["docs/public-sources/20261109_impl-prep_misc-age-kinship-attribution.md#1.3"]


class 所得税_死亡日(Variable):
    value_type = _dt.date
    entity = 人物
    definition_period = YEAR
    default_value = NOT_DEAD
    label = "死亡日（中間表現の persons[].death_on。死亡していなければ 9999-12-31）"
    reference = ["docs/public-sources/20261109_impl-prep_misc-age-kinship-attribution.md#1.1"]


class 所得税_判定の時に住所が国内にあるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    default_value = True
    label = "判定の時（その年12月31日・死亡の時）に国内に住所を有するか（国外の滞在と判断.住所の所在から）"
    reference = ["docs/public-sources/20261109_round2_elderly-abroad-laws.md#4"]


class 所得税_留学により国内に住所及び居所を有しなくなった者か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "留学により国内に住所及び居所を有しなくなった者か（所得税法第2条第1項第34号の2ロ(1)）"
    reference = ["docs/public-sources/20261109_round2_elderly-abroad-laws.md#3.1"]


class 所得税_身体障害者手帳の障害の程度の級(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "判定の時の身体障害者手帳の障害の程度の級（なければ0、級の記載がなければ99）"
    reference = [_JINTEKI_15]


class 所得税_精神障害者保健福祉手帳の障害等級(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "判定の時の精神障害者保健福祉手帳の障害等級（なければ0、等級の記載がなければ99）"
    reference = [_JINTEKI_15]


class 所得税_知的障害者と判定されているか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "知的障害者と判定されているか（所得税法施行令第10条第1項第1号）"
    reference = [_JINTEKI_15]


class 所得税_重度の知的障害者と判定されているか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "重度の知的障害者とされているか（所得税法施行令第10条第2項第1号。判断.障害の程度）"
    reference = [_JINTEKI_15]


class 所得税_事理を弁識する能力を欠く常況にあるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "精神上の障害により事理を弁識する能力を欠く常況にあるか（判断.障害の程度）"
    reference = [_JINTEKI_15]


class 所得税_戦傷病者手帳の交付を受けているか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "戦傷病者手帳の交付を受けているか（所得税法施行令第10条第1項第4号）"
    reference = [_JINTEKI_15]


class 所得税_原子爆弾被爆者の認定を受けているか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "原子爆弾被爆者に対する援護に関する法律第11条第1項の認定を受けているか（所得税法施行令第10条第1項第5号）"
    reference = [_JINTEKI_15]


class 所得税_常に就床を要し複雑な介護を要するか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "常に就床を要し、複雑な介護を要するか（所得税法施行令第10条第1項第6号。判断.障害の程度）"
    reference = [_JINTEKI_15]


class 所得税_市町村長等の障害者の認定を受けているか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "市町村長等の障害者の認定を受けているか（所得税法施行令第10条第1項第7号）"
    reference = [_JINTEKI_15]


class 所得税_手帳の申請中で障害が明らかか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "手帳の交付を申請中で、明らかに手帳に記載される程度の障害があるか（所得税基本通達2−38。判断.障害の程度）"
    reference = ["docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.7"]


class 所得税_戦傷病者手帳に特別項症から第三項症までと記載されているか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "戦傷病者手帳に恩給法別表第一号表ノ二の特別項症から第三項症までである者として記載されているか（所得税法施行令第10条第2項第4号。war_injury_class）"
    reference = [_JINTEKI_15]


class 所得税_市町村長等の特別障害者に準ずる認定を受けているか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "障害の程度が特別障害者（所令10②一・三）に準ずるものとして市町村長等の認定を受けているか（所得税法施行令第10条第2項第6号。certified_severity が severe）"
    reference = [_JINTEKI_15]


class 所得税_申請中の障害の程度が特別障害者の程度か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "手帳の申請中の障害の程度が明らかに特別障害者の程度か（所得税基本通達2−38：身体障害者手帳の1級・2級、戦傷病者手帳の特別項症〜第三項症。application の grade・war_injury_class）"
    reference = ["docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.7"]


class 所得税_政令で定める課程を履修する専修学校等の学生等か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = (
        "判定の時に、所得税法第2条第1項第32号ロの設置者の専修学校・各種学校、又はハの認定職業訓練で、政令で定める課程（所令11の3②）を履修する者か"
        "（課程の要件は所規47の2⑪の証明書の交付の有無で受ける）"
    )
    reference = ["docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md#6.2", "docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md#6.3"]


class 所得税_学校教育法第1条の学校の学生等か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "判定の時に学校教育法第1条の学校の学生・生徒・児童か（所得税法第2条第1項第32号イ）"
    reference = ["docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md#6.1"]


class 所得税_判定の時に婚姻をしているか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "判定の時（その年12月31日・死亡の時）に婚姻の届出による配偶者がいるか"
    reference = ["docs/public-sources/20261109_R4-modeling_concepts.md#3.1"]


class 所得税_翌年1月1日に障害者に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "翌年の1月1日（住民税の賦課期日）の記録で障害者（所得税法施行令第10条第1項の区分）に当たるか（住民税への窓口：jan1.py）"
    reference = ["docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.5", "docs/public-sources/20261109_impl-prep_juminzei-hikazei-fuyo-shinkoku.md#3.1"]


class 所得税_翌年1月1日に婚姻の状況が判定の時と違うか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "婚姻・配偶者の生死不明・夫との離婚又は死別・事実婚の記載が、判定の時と翌年の1月1日で違うか（住民税への窓口：jan1.py）"
    reference = ["docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.1", "docs/public-sources/20261109_impl-prep_juminzei-hikazei-fuyo-shinkoku.md#3.1"]


class 所得税_翌年1月1日に婚姻又は事実婚をしているか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "翌年の1月1日に婚姻が続いている（配偶者の生死不明を除く）か住民票に事実婚の記載がある（寡婦・ひとり親の本人の要件を欠く。住民税への窓口：jan1.py）"
    reference = ["docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.1", "docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.6"]


class 所得税_配偶者の生死が明らかでない者か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "配偶者の生死の明らかでない者で政令で定めるものか（所得税法施行令第11条・第11条の2第1項）"
    reference = ["docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.6"]


class 所得税_住民票に事実婚の続柄の記載がある相手がいるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "住民票の世帯主との続柄に未届の夫・未届の妻などの記載がある相手がいるか（所得税法施行規則第1条の3・第1条の4）"
    reference = ["docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.6"]


class 所得税_事業所得等が自己の勤労に基づくか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "事業所得・雑所得が自己の勤労に基づいて得たものか（判断.自己の勤労に基づく）"
    reference = ["docs/public-sources/20261109_round2_gaps-sources.md#1.1"]


# ---------------------------------------------------------------------------
# 段階評価の段が書く入力（allocation.py）：親族・扶養の割当て・配偶者の関係（D23 K1）
# ---------------------------------------------------------------------------

_MISC_32 = "docs/public-sources/20261109_impl-prep_misc-age-kinship-attribution.md#3.2"
_CON_47 = "docs/public-sources/20261109_R4-modeling_concepts.md#4.7"
_GAPS_31 = "docs/public-sources/20261109_round2_gaps-sources.md#3.1"
_SPOUSE_14 = "docs/public-sources/20261109_round2_spouse-laws-and-sources.md#1.4"


class 所得税_申告者の親族か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "扶養の割当てで決まった申告者の親族（里子・養護受託老人を含む）か（段階評価の段が書く入力）"
    reference = ["docs/public-sources/20261109_R4-modeling_concepts.md#3.1", "docs/public-sources/20261109_impl-prep_misc-age-kinship-attribution.md#2.1"]


class 所得税_申告者の子か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "扶養の割当てで決まった申告者の子か（段階評価の段が書く入力）"
    reference = ["docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.1"]


class 所得税_申告者と生計を一にするか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "扶養の割当てで決まった申告者と生計を一にするか（判断.生計を一にする。段階評価の段が書く入力）"
    reference = ["docs/public-sources/20261109_R4-modeling_concepts.md#4.1"]


class 所得税_申告者と同居を常況としているか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "申告者又はその配偶者と同居を常況としているか（措法41の16。段階評価の段が書く入力）"
    reference = ["docs/public-sources/20261109_round2_elderly-abroad-laws.md#2.1"]


class 所得税_申告者等と同居を常況としているか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "申告者又はその配偶者若しくは申告者と生計を一にするその他の親族のいずれかと同居を常況としているか（所法79③。段階評価の段が書く入力）"
    reference = ["docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.2"]


class 所得税_配偶者等と同居を常況としているか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "法律婚の相手（居住者）又はその居住者と生計を一にするその他の親族のいずれかと同居を常況としているか（所法79③。段階評価の段が書く入力）"
    reference = ["docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.2"]


class 所得税_申告者の直系尊属か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "申告者又はその配偶者の直系尊属か（措法41の16。段階評価の段が書く入力）"
    reference = ["docs/public-sources/20261109_round2_elderly-abroad-laws.md#2.1"]


class 所得税_申告者等の事業専従者か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "申告者又は申告者と生計を一にする居住者の青色事業専従者等か（所基通2−48。段階評価の段が書く入力）"
    reference = ["docs/public-sources/20261109_R4-modeling_concepts.md#3.4"]


class 所得税_国外居住親族の書類の要件を満たすか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "国外居住親族の親族関係書類の記録があるか（申告者が保有するもの。段階評価の段が書く入力）"
    reference = ["docs/public-sources/20261109_round2_elderly-abroad-laws.md#3.2"]


class 所得税_国外居住親族の留学の区分の書類の要件を満たすか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "留学の区分（所法2①三十四の二ロ(1)）で扶養控除を受ける国外居住親族の書類（親族関係書類・送金関係書類・留学ビザ等書類：所令262④二）の記録があるか（段階評価の段が書く入力）"
    reference = ["docs/public-sources/20261109_round2_elderly-abroad-laws.md#3.2"]


class 所得税_国外居住親族の38万円以上の区分の書類の要件を満たすか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "38万円以上の支払の区分（所法2①三十四の二ロ(3)）で扶養控除を受ける国外居住親族の書類（親族関係書類・38万円送金書類：所令262④三）の記録があるか（段階評価の段が書く入力）"
    reference = ["docs/public-sources/20261109_round2_elderly-abroad-laws.md#3.2"]


class 所得税_申告者から受けた生活費等の支払の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "その年に申告者から受けた生活費又は教育費に充てるための支払の額（送金の記録の合計。段階評価の段が書く入力）"
    reference = ["docs/public-sources/20261109_round2_elderly-abroad-laws.md#3.1"]


class 所得税_配偶者と生計を一にするか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "法律婚の配偶者と生計を一にするか（判断.生計を一にする。段階評価の段が書く入力）"
    reference = ["docs/public-sources/20261109_round2_spouse-laws-and-sources.md#1.1"]


class 所得税_配偶者が青色事業専従者等か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "法律婚の配偶者が、本人又は本人と生計を一にする居住者の青色事業専従者等か（所基通2−48。段階評価の段が書く入力）"
    reference = ["docs/public-sources/20261109_round2_spouse-laws-and-sources.md#1.8"]


class 所得税_配偶者特別控除の適用除外に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "本人の配偶者特別控除に所法83の2②の除外が当たるか（配偶者の適用・源泉控除対象配偶者としての源泉徴収。段階評価の段が書く入力）"
    reference = [_SPOUSE_14]


class 所得税_特定親族特別控除の適用除外に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "特定親族について所法84の2②・所令217の2 の除外が当たるか（段階評価の段が書く入力）"
    reference = ["docs/public-sources/20261109_impl-prep_misc-age-kinship-attribution.md#4.2"]


class 所得税_連鎖の扶養親族等か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "他の人の扶養親族等で、自分も申告者である人か（扶養の連鎖：グループの1つの所属では表せない。段階評価の段が書く入力）"
    reference = [_MISC_32, _CON_47]


class 所得税_扶養親族等の申告者(Variable):
    value_type = str
    entity = 人物
    default_value = ""
    definition_period = YEAR
    label = "扶養の割当てで決まった申告者の人の ID（いなければ空。扶養の連鎖の合計の段が読む）"
    reference = [_MISC_32, _CON_47]


class 所得税_所得金額調整控除の対象の親族等を有するか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "年齢23歳未満の扶養親族・特別障害者である同一生計配偶者又は扶養親族を有するか（措法41の3の11①。段階評価の段が書く入力）"
    reference = [_GAPS_31]


class 所得税_連鎖の扶養親族の扶養控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "連鎖の扶養親族等（自分も申告者である人）の分の扶養控除の額（段階評価の段が書く入力）"
    reference = [_MISC_32, "docs/public-sources/20261109_R1-laws_income-tax.md#2"]


class 所得税_連鎖の扶養親族の特定親族特別控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "連鎖の扶養親族等の分の特定親族特別控除の額（段階評価の段が書く入力）"
    reference = [_MISC_32, "docs/public-sources/20261109_R1-laws_income-tax.md#3"]


class 所得税_連鎖の扶養親族の障害者控除の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "連鎖の扶養親族等の分の障害者控除の額（段階評価の段が書く入力）"
    reference = [_MISC_32, "docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.2"]


class 所得税_連鎖の扶養親族がいるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "連鎖の扶養親族等に扶養親族に当たる人がいるか（寡婦のイの「扶養親族を有する」。段階評価の段が書く入力）"
    reference = [_MISC_32, "docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.1"]


class 所得税_連鎖のひとり親の子がいるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "連鎖の扶養親族等に、ひとり親の要件の子がいるか（段階評価の段が書く入力）"
    reference = [_MISC_32, "docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.1"]


class 所得税_死亡した申告者のための見積りを使うか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "扶養等の判定に、死亡した申告者のための合計所得金額の見積額を使うか（所基通85−1(2)。段階評価の段が書く入力）"
    reference = ["docs/public-sources/20261111_impl-research3_kojo-misc-laws-and-nta.md#4"]


class 所得税_死亡した申告者のための合計所得金額の見積額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "年の中途で死亡した申告者の親族の、死亡の時の現況で見積もったその年の合計所得金額（見積り.親族の合計所得金額。段階評価の段が書く入力）"
    reference = ["docs/public-sources/20261111_impl-research3_kojo-misc-laws-and-nta.md#4"]


class 所得税_法律婚のグループ外の配偶者がいるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "配偶者が別の人を所令220① の配偶者としたため、法律婚のグループに入れない配偶者がいるか（段階評価の段が書く入力）"
    reference = ["docs/public-sources/20261109_impl-prep_misc-age-kinship-attribution.md#3.2"]


class 所得税_グループ外の配偶者の合計所得金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "法律婚のグループ外の配偶者の、扶養等の判定に使う合計所得金額（段階評価の段が書く入力）"
    reference = ["docs/public-sources/20261109_impl-prep_misc-age-kinship-attribution.md#3.2"]


class 所得税_グループ外の配偶者の年齢(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "法律婚のグループ外の配偶者の年齢（段階評価の段が書く入力）"
    reference = ["docs/public-sources/20261109_impl-prep_misc-age-kinship-attribution.md#3.2"]


class 所得税_グループ外の配偶者が他の居住者の扶養親族等とされているか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "法律婚のグループ外の配偶者が、扶養の割当てで他の居住者の扶養親族等とされているか（段階評価の段が書く入力）"
    reference = ["docs/public-sources/20261109_impl-prep_misc-age-kinship-attribution.md#3.2"]


class 所得税_グループ外の配偶者の障害の区分(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "法律婚のグループ外の配偶者の障害の区分（0 なし・1 障害者・2 特別障害者・3 同居特別障害者。段階評価の段が書く入力）"
    reference = ["docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.2"]


class 所得税_判定する人の判定の時の値を使うか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = (
        "その人を扶養親族等・配偶者として判定する人（申告者・配偶者）の判定の時が、その人自身の判定の時と違うか（所得税法第85条第3項：出国する人を出国しない"
        "居住者が判定する・年の中途で死亡した人が判定するなど。PD-05。段階評価の段が書く入力）"
    )
    reference = ["docs/public-sources/20261109_impl-prep_misc-age-kinship-attribution.md#1.1"]


class 所得税_判定する人の判定の時の年齢(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "判定する人の判定の時（死亡の時はその前日の終了時）のその人の年齢（PD-05。段階評価の段が書く入力。判定の時が同じなら 所得税_年齢 と同じ）"
    reference = ["docs/public-sources/20261109_impl-prep_misc-age-kinship-attribution.md#1.3"]


class 所得税_判定する人の判定の時に居住者か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "判定する人の判定の時に、その人が国内に住所を有するか（PD-05。段階評価の段が書く入力）"
    reference = ["docs/public-sources/20261109_round2_elderly-abroad-laws.md#4"]


class 所得税_判定する人の判定の時に留学により国内に住所及び居所を有しなくなった者か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "判定する人の判定の時に、その人が留学により国内に住所及び居所を有しなくなった者か（PD-05。段階評価の段が書く入力）"
    reference = ["docs/public-sources/20261109_round2_elderly-abroad-laws.md#3.1"]


class 所得税_判定する人の判定の時に障害者に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "判定する人の判定の時に、その人が障害者に当たるか（所令10①。PD-05。段階評価の段が書く入力）"
    reference = ["docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.5"]


class 所得税_判定する人の判定の時に特別障害者に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "判定する人の判定の時に、その人が特別障害者に当たるか（所令10②。PD-05。段階評価の段が書く入力）"
    reference = ["docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.5"]


class 所得税_夫と離婚した後婚姻をしていない者か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "夫（相手の legal_sex が male）と離婚した後婚姻をしていない者か（寡婦のイの材料。性別の記録がない相手は当たりうるものとし、checks.py が止める）"
    reference = ["docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.1"]


class 所得税_夫と死別した後婚姻をしていない者又は夫の生死の明らかでない者か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "夫（相手の legal_sex が male）と死別した後婚姻をしていない者又は夫の生死の明らかでない者（所令11）か（寡婦のロの材料。性別の記録がない相手は当たりうるものとし、checks.py が止める）"
    reference = ["docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md#1.1"]


RELATION_INPUT_VARIABLES = (
    所得税_申告者の親族か,
    所得税_申告者の子か,
    所得税_申告者と生計を一にするか,
    所得税_申告者と同居を常況としているか,
    所得税_申告者等と同居を常況としているか,
    所得税_配偶者等と同居を常況としているか,
    所得税_申告者の直系尊属か,
    所得税_申告者等の事業専従者か,
    所得税_国外居住親族の書類の要件を満たすか,
    所得税_国外居住親族の留学の区分の書類の要件を満たすか,
    所得税_国外居住親族の38万円以上の区分の書類の要件を満たすか,
    所得税_申告者から受けた生活費等の支払の額,
    所得税_配偶者と生計を一にするか,
    所得税_配偶者が青色事業専従者等か,
    所得税_配偶者特別控除の適用除外に当たるか,
    所得税_特定親族特別控除の適用除外に当たるか,
    所得税_連鎖の扶養親族等か,
    所得税_扶養親族等の申告者,
    所得税_所得金額調整控除の対象の親族等を有するか,
    所得税_連鎖の扶養親族の扶養控除の額,
    所得税_連鎖の扶養親族の特定親族特別控除の額,
    所得税_連鎖の扶養親族の障害者控除の額,
    所得税_連鎖の扶養親族がいるか,
    所得税_連鎖のひとり親の子がいるか,
    所得税_夫と離婚した後婚姻をしていない者か,
    所得税_夫と死別した後婚姻をしていない者又は夫の生死の明らかでない者か,
    所得税_死亡した申告者のための見積りを使うか,
    所得税_死亡した申告者のための合計所得金額の見積額,
    所得税_法律婚のグループ外の配偶者がいるか,
    所得税_グループ外の配偶者の合計所得金額,
    所得税_グループ外の配偶者の年齢,
    所得税_グループ外の配偶者が他の居住者の扶養親族等とされているか,
    所得税_グループ外の配偶者の障害の区分,
    所得税_判定する人の判定の時の値を使うか,
    所得税_判定する人の判定の時の年齢,
    所得税_判定する人の判定の時に居住者か,
    所得税_判定する人の判定の時に留学により国内に住所及び居所を有しなくなった者か,
    所得税_判定する人の判定の時に障害者に当たるか,
    所得税_判定する人の判定の時に特別障害者に当たるか,
)


FACT_VARIABLES = (
    所得税_生年月日,
    所得税_死亡日,
    所得税_判定の時に住所が国内にあるか,
    所得税_留学により国内に住所及び居所を有しなくなった者か,
    所得税_身体障害者手帳の障害の程度の級,
    所得税_精神障害者保健福祉手帳の障害等級,
    所得税_知的障害者と判定されているか,
    所得税_重度の知的障害者と判定されているか,
    所得税_事理を弁識する能力を欠く常況にあるか,
    所得税_戦傷病者手帳の交付を受けているか,
    所得税_原子爆弾被爆者の認定を受けているか,
    所得税_常に就床を要し複雑な介護を要するか,
    所得税_市町村長等の障害者の認定を受けているか,
    所得税_手帳の申請中で障害が明らかか,
    所得税_戦傷病者手帳に特別項症から第三項症までと記載されているか,
    所得税_市町村長等の特別障害者に準ずる認定を受けているか,
    所得税_申請中の障害の程度が特別障害者の程度か,
    所得税_学校教育法第1条の学校の学生等か,
    所得税_政令で定める課程を履修する専修学校等の学生等か,
    所得税_判定の時に婚姻をしているか,
    所得税_配偶者の生死が明らかでない者か,
    所得税_住民票に事実婚の続柄の記載がある相手がいるか,
    所得税_事業所得等が自己の勤労に基づくか,
    所得税_翌年1月1日に障害者に当たるか,
    所得税_翌年1月1日に婚姻の状況が判定の時と違うか,
    所得税_翌年1月1日に婚姻又は事実婚をしているか,
) + RELATION_INPUT_VARIABLES

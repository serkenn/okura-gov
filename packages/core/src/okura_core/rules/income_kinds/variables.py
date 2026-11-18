"""規則モジュール income_kinds の変数（入力変数と式）。

金額の変数は int（numpy.int32）。有理数の途中の値は変数をまたがせず、式の中の純粋関数（calc.py）で Fraction のまま計算して、
整数の円にしてから返す（float は使わない）。円未満の端数の根拠がない値は、入力 所得税_所得の金額の端数の候補
（evaluate が候補ごとに入れる。RoundingSlotSpec）の関数で所得の金額の側を丸める（calc.py の docstring）。

ほかのモジュールの未実装の概念（所得税_年齢・所得税_公的年金等に係る雑所得以外の合計所得金額・所得税_給与所得控除額）は仮置きの変数で受ける。
公的年金等控除額は、公的年金等の収入がある人が状況の中にいるときだけ年齢などを引く（いなければ、ほかの人の値が仮置きの変数に依存しないようにする）。
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

import numpy as np
from openfisca_core.model_api import YEAR, Variable

from ...country.entities import 人物
from ...money import INT32_MAX
from ...rounding import FUNCTIONS, floor_yen
from .calc import (
    BLUE_APPROVED,
    BLUE_NOT_APPROVED,
    FILING_OTHER,
    PENSION_FLOOR,
    RETIRE_GENERAL,
    blue_deduction_split,
    blue_rules,
    home_worker_expenses,
    rental_loss_excluded,
    pension_deduction,
    pension_deduction_yen,
    pension_rules,
    retirement_deduction,
    retirement_has_fraction,
    retirement_income,
    retirement_income_multi,
    retirement_rules,
    windfall_income,
)

NENKIN = "docs/public-sources/20261109_round2b_nenkin-laws-and-guidance.md"
TAISHOKU = "docs/public-sources/20261109_round2b_taishoku-laws-and-guidance.md"
JIGYO = "docs/public-sources/20261109_impl-prep_jigyo-laws-and-nta.md"
AOIRO = "docs/public-sources/20261109_round2_aoiro-laws-and-nta.md"
KABU = "docs/public-sources/20261109_round2b_kabu-law-and-nta.md"
FUDOSAN = "docs/public-sources/20261109_round2b_fudosan-laws-and-nta.md"
FUDOSAN5 = "docs/public-sources/20261112_impl-research5_fudosan-special-losses.md"
GENKA = "docs/public-sources/20261109_round2_genka-laws-and-nta.md"
HAITO = "docs/public-sources/20261111_impl-research_haito-laws-and-nta.md"
GENSEN = "docs/public-sources/20261111_impl-research_gensen-laws-and-nta.md"


def _yen(values: list[int], what: str) -> np.ndarray:
    if any(abs(v) > INT32_MAX for v in values):
        raise OverflowError(f"{what} が int32 の範囲を超える")
    return np.array(values, dtype=np.int32)


def _input(name: str, label: str, refs: list[str], vt: type = int, default: object | None = None) -> type:
    attrs = {"value_type": vt, "entity": 人物, "definition_period": YEAR, "label": label, "reference": refs, "__module__": __name__}
    if default is not None:
        attrs["default_value"] = default
    return type(name, (Variable,), attrs)


# ---------------------------------------------------------------------------
# 入力変数（事実）
# ---------------------------------------------------------------------------

所得税_公的年金等の収入金額 = _input(
    "所得税_公的年金等の収入金額",
    "その年中の公的年金等の収入金額（所得税法第35条第2項第1号・第3項。非課税の障害・遺族の年金を除く）",
    [f"{NENKIN}#1.1", f"{NENKIN}#4.1"],
)
所得税_一時所得の総収入金額 = _input("所得税_一時所得の総収入金額", "その年中の一時所得に係る総収入金額（所得税法第34条第2項）", [f"{JIGYO}#6"])
所得税_一時所得の支出した金額 = _input(
    "所得税_一時所得の支出した金額", "その収入を得るために支出した金額の合計額（所得税法第34条第2項。直接要した金額に限る）", [f"{JIGYO}#6"]
)
所得税_退職手当等の収入金額 = _input("所得税_退職手当等の収入金額", "その年中の退職手当等の収入金額（所得税法第30条第2項）", [f"{TAISHOKU}#2.1"])
所得税_退職所得の勤続年数 = _input(
    "所得税_退職所得の勤続年数", "退職所得控除額の勤続年数（所得税法施行令第69条。1年未満の端数は1年）", [f"{TAISHOKU}#2.2"], default=1
)
所得税_退職手当等の区分 = _input(
    "所得税_退職手当等の区分",
    "退職手当等の区分（一般・短期〔所法30④〕・特定役員〔所法30⑤〕）",
    [f"{TAISHOKU}#2.1"],
    vt=str,
    default=RETIRE_GENERAL,
)
所得税_障害者になったことに直接基因する退職か = _input(
    "所得税_障害者になったことに直接基因する退職か", "障害者になったことに直接基因して退職したか（所得税法第30条第6項第3号・施行令第71条）", [f"{TAISHOKU}#2.4"], vt=bool
)
所得税_前の退職手当等との重複年数 = _input(
    "所得税_前の退職手当等との重複年数",
    "その年の退職手当等の勤続期間等のうち前の退職手当等の勤続期間等と重複している期間の年数と、所得税法施行令第70条第1項第1号の期間の年数の合計（所得税法第30条第6項第1号、所得税法施行令第70条第1項第1号・第2号・第3項。1年未満切捨て。③の額が年数について足し算になる範囲でだけ合わせる）",
    [f"{TAISHOKU}#2.3"],
)
所得税_短期退職手当等の収入金額 = _input(
    "所得税_短期退職手当等の収入金額", "その年中に二以上の区分の退職手当等があるときの短期退職手当等の収入金額（所得税法第30条第7項。一つの区分だけなら0）", [f"{TAISHOKU}#2.4"]
)
所得税_特定役員退職手当等の収入金額 = _input(
    "所得税_特定役員退職手当等の収入金額", "その年中に二以上の区分の退職手当等があるときの特定役員退職手当等の収入金額（所得税法第30条第7項。一つの区分だけなら0）", [f"{TAISHOKU}#2.4"]
)
所得税_短期退職所得控除額 = _input(
    "所得税_短期退職所得控除額", "短期退職所得控除額（所得税法施行令第71条の2第1項第1号イ・第7項第2号イ・第11項。一般と短期・三つともの場合だけ）", [f"{TAISHOKU}#2.4"]
)
所得税_特定役員退職所得控除額 = _input(
    "所得税_特定役員退職所得控除額", "特定役員退職所得控除額（所得税法施行令第71条の2第3項第1号・第5項第1号・第7項第1号・第12項）", [f"{TAISHOKU}#2.4"]
)
所得税_事業所得の総収入金額 = _input(
    "所得税_事業所得の総収入金額", "事業所得に係る総収入金額（判断.事業と称するに至る程度で事業に区分した業務の売上）", [f"{JIGYO}#1.1"]
)
所得税_事業所得の必要経費 = _input(
    "所得税_事業所得の必要経費",
    "事業所得の必要経費（所法37①・45①、所令96。減価償却費・専従者給与等・家内労働者等の特例の前）",
    [f"{JIGYO}#1.1", f"{JIGYO}#1.2"],
)
所得税_業務に係る雑所得の総収入金額 = _input(
    "所得税_業務に係る雑所得の総収入金額", "業務に係る雑所得の総収入金額（所法35②二。業務に区分した売上）", [f"{JIGYO}#1.1"]
)
所得税_業務に係る雑所得の必要経費 = _input(
    "所得税_業務に係る雑所得の必要経費", "業務に係る雑所得の必要経費（所法37①・45①、所令96第1号。家内労働者等の特例の前）", [f"{JIGYO}#1.1", f"{JIGYO}#1.2"]
)
所得税_家内労働者等か = _input("所得税_家内労働者等か", "家内労働者等に当たるか（租税特別措置法第27条、同施行令第18条の2第1項）", [f"{JIGYO}#2.1"], vt=bool)
所得税_青色申告の承認の状態 = _input(
    "所得税_青色申告の承認の状態",
    "その年分について青色申告の承認があるか（承認・承認なし。所法143〜147・150・151 を手続の記録に当てた結果）",
    [f"{AOIRO}#1.4", f"{AOIRO}#1.6"],
    vt=str,
    default=BLUE_NOT_APPROVED,
)
所得税_正規の簿記の要件 = _input(
    "所得税_正規の簿記の要件", "事業の取引を正規の簿記で記録・作成しているか（措法25の2③、措規9の6①）", [f"{AOIRO}#3.1"], vt=bool
)
所得税_青色申告特別控除の申告の要件 = _input(
    "所得税_青色申告特別控除の申告の要件",
    "青色申告特別控除の申告の要件（期限内の電子申告・期限内の書面の申告・期限内の申告でない。措法25の2④二・⑥）",
    [f"{AOIRO}#3.1"],
    vt=str,
    default=FILING_OTHER,
)
所得税_所得の金額の端数の候補 = _input(
    "所得税_所得の金額の端数の候補",
    "所得の金額の1円未満の端数の候補（根拠のない端数：evaluate が floor・ceil・half_up を入れる。D21 R5・D22 S3）",
    [f"{NENKIN}#2.1", f"{TAISHOKU}#2.1"],
    vt=str,
)

所得税_総合課税の配当等の収入金額 = _input(
    "所得税_総合課税の配当等の収入金額", "総合課税を選んだ上場株式等の配当等の収入金額（所得税法第24条、措法8の4②）", [f"{KABU}#1.2", f"{KABU}#2.1"]
)
所得税_申告分離課税の配当等の収入金額 = _input(
    "所得税_申告分離課税の配当等の収入金額", "申告分離課税を選んだ上場株式等の配当等の収入金額（措法8の4①）", [f"{KABU}#1.1"]
)
所得税_上場株式等の譲渡の収入金額 = _input(
    "所得税_上場株式等の譲渡の収入金額", "上場株式等の譲渡の収入金額（一般の口座の譲渡の対価と、特定口座の年間の利益）", [f"{KABU}#4", f"{KABU}#5.2"]
)
所得税_上場株式等の譲渡の取得費等 = _input(
    "所得税_上場株式等の譲渡の取得費等", "上場株式等の譲渡の取得費等（一般の口座の取得価額と譲渡の費用、特定口座の年間の損失）", [f"{KABU}#4", f"{KABU}#5.2"]
)

所得税_その他の雑所得の総収入金額 = _input(
    "所得税_その他の雑所得の総収入金額", "その他の雑所得（公的年金等・業務に係るもの以外）の総収入金額（所法35②二：生命保険契約等の年金、公的な制度でない外国の年金など）", [f"{NENKIN}#1.1", f"{NENKIN}#1.2"]
)
所得税_その他の雑所得の必要経費 = _input(
    "所得税_その他の雑所得の必要経費", "その他の雑所得の必要経費（判断.年金の性質の本人の負担分：所令183 の保険料に対応する金額など）", [f"{NENKIN}#1.1", f"{NENKIN}#1.2"]
)
所得税_不動産所得の総収入金額 = _input(
    "所得税_不動産所得の総収入金額", "不動産所得の総収入金額（所法26②：賃料・共益費・礼金・更新料など。受取日の年分。敷金の預りは含めない）", [f"{FUDOSAN}#2.2"]
)
所得税_不動産所得の必要経費 = _input(
    "所得税_不動産所得の必要経費", "不動産所得の必要経費（減価償却費・専従者給与等を除く）", [f"{FUDOSAN}#2.3"]
)
所得税_不動産所得の減価償却費 = _input("所得税_不動産所得の減価償却費", "不動産所得の金額の計算上必要経費に算入する減価償却費", [f"{GENKA}#2.1"])
所得税_事業所得の減価償却費 = _input("所得税_事業所得の減価償却費", "事業所得の金額の計算上必要経費に算入する減価償却費", [f"{GENKA}#2.1"])
所得税_業務に係る雑所得の減価償却費 = _input("所得税_業務に係る雑所得の減価償却費", "業務に係る雑所得の金額の計算上必要経費に算入する減価償却費", [f"{GENKA}#2.1"])
所得税_不動産の貸付けが事業として行われているか = _input(
    "所得税_不動産の貸付けが事業として行われているか", "不動産の貸付けが事業として行われているか（判断.不動産の事業的規模。所基通26−9）", [f"{FUDOSAN}#3.1"], vt=bool
)
所得税_土地等を取得するために要した負債の利子の額 = _input(
    "所得税_土地等を取得するために要した負債の利子の額", "不動産所得の必要経費に算入した土地等を取得するために要した負債の利子の額（措法41の4①）", [f"{FUDOSAN}#4.3"]
)
所得税_不動産所得の貸付けがすべて別荘等か = _input(
    "所得税_不動産所得の貸付けがすべて別荘等か", "その年分の貸付けがすべて別荘等の生活に通常必要でない資産の貸付けか（所法69②）", [f"{FUDOSAN}#4.1"], vt=bool
)
所得税_事業所得の青色事業専従者給与の額 = _input("所得税_事業所得の青色事業専従者給与の額", "事業所得の必要経費に算入する青色事業専従者給与の額（所法57①）", [f"{AOIRO}#4.1"])
所得税_不動産所得の青色事業専従者給与の額 = _input("所得税_不動産所得の青色事業専従者給与の額", "不動産所得の必要経費に算入する青色事業専従者給与の額（所法57①）", [f"{AOIRO}#4.1"])
所得税_事業所得の事業専従者控除額 = _input("所得税_事業所得の事業専従者控除額", "事業所得の金額の計算上控除する事業専従者控除額（所法57③）", [f"{FUDOSAN}#5.1"])
所得税_不動産所得の事業専従者控除額 = _input("所得税_不動産所得の事業専従者控除額", "不動産所得の金額の計算上控除する事業専従者控除額（所法57③）", [f"{FUDOSAN}#5.1"])
所得税_別荘等の貸付けに係る損失の額 = _input(
    "所得税_別荘等の貸付けに係る損失の額",
    "別荘等とそれ以外の貸付けがともに損失のときの、別荘等の貸付けの損失の額（所法69②。物件ごとの収支：business_expense・depreciable_asset・rent_flow の property_id）",
    [f"{FUDOSAN}#4.1"],
)
所得税_組合事業等と国外中古建物の不動産所得の損失のうち生じなかったものとみなす金額 = _input(
    "所得税_組合事業等と国外中古建物の不動産所得の損失のうち生じなかったものとみなす金額",
    "特定組合員・特定受益者の組合事業・信託ごとの不動産所得の損失（措法41の4の2・措令26の6の2④）と国外不動産所得の損失の金額（措法41の4の3・措令26の6の3）の合計。"
    "所法26② と69① の適用で生じなかったものとみなす（不動産所得の計算の中で他の黒字とも通算しない。IK-104）",
    [f"{FUDOSAN5}#2", f"{FUDOSAN5}#3"],
)
所得税_事業専従者としてみなされる給与の収入金額 = _input(
    "所得税_事業専従者としてみなされる給与の収入金額", "事業専従者控除額のうち、専従者の給与所得の収入金額とみなされる額（所法57④）", [f"{FUDOSAN}#5.1"]
)
所得税_生計を一にする親族の事業から受けた給与のうち収入金額に含めない額 = _input(
    "所得税_生計を一にする親族の事業から受けた給与のうち収入金額に含めない額",
    "生計を一にする親族の事業から受けた給与のうち、所法56 によりないものとみなす額（所法57① の青色事業専従者給与として必要経費に算入される額を除く）",
    [f"{FUDOSAN}#5.1", f"{AOIRO}#4.1"],
)
所得税_退職手当等に当たらないとした給与等の収入金額 = _input(
    "所得税_退職手当等に当たらないとした給与等の収入金額",
    "判断.退職の性質 で退職手当等に当たらず給与（所基通30−1）とした退職手当等の支払の額（支払の日の年分。kyuyo が段で読んで給与等の収入金額に足す：IK-25）",
    ["docs/public-sources/20261109_round2b_taishoku-laws-and-guidance.md#1.2", "docs/public-sources/20261111_impl-research_kyuyo-jiki-laws-and-nta.md#2.1"],
)
所得税_総合課税の配当等の負債の利子 = _input(
    "所得税_総合課税の配当等の負債の利子", "総合課税の配当所得の負債の利子（所法24②、所令59）", [f"{HAITO}#1"]
)
所得税_申告分離課税の配当等の負債の利子 = _input(
    "所得税_申告分離課税の配当等の負債の利子", "申告分離課税の配当所得等の負債の利子（所法24②、所令59）", [f"{HAITO}#1"]
)
所得税_公的年金等の源泉徴収税額 = _input("所得税_公的年金等の源泉徴収税額", "公的年金等について源泉徴収をされた又はされるべき所得税及び復興特別所得税の額（所法120①四）", [f"{GENSEN}#1", f"{GENSEN}#3"])
所得税_退職所得の源泉徴収税額 = _input("所得税_退職所得の源泉徴収税額", "退職手当等について源泉徴収をされた又はされるべき所得税及び復興特別所得税の額（所法120①四）", [f"{GENSEN}#1", f"{GENSEN}#4"])
所得税_配当控除の対象の剰余金の配当等に係る配当所得の金額 = _input(
    "所得税_配当控除の対象の剰余金の配当等に係る配当所得の金額",
    "総合課税の配当所得の金額のうち、剰余金の配当等（特定株式投資信託の収益の分配を含む）に係るもの（所法92①一イ、TA1250）",
    [f"{HAITO}#2", f"{HAITO}#4"],
)
所得税_配当控除の対象の証券投資信託の収益の分配に係る配当所得の金額 = _input(
    "所得税_配当控除の対象の証券投資信託の収益の分配に係る配当所得の金額",
    "総合課税の配当所得の金額のうち、証券投資信託の収益の分配に係るもの（所法92①一ロ）",
    [f"{HAITO}#2"],
)
所得税_配当控除の対象の一般外貨建等証券投資信託の収益の分配に係る配当所得の金額 = _input(
    "所得税_配当控除の対象の一般外貨建等証券投資信託の収益の分配に係る配当所得の金額",
    "総合課税の配当所得の金額のうち、一般外貨建等証券投資信託の収益の分配に係るもの（措法9、TA1250）",
    [f"{HAITO}#4"],
)
所得税_配当等の源泉徴収税額 = _input("所得税_配当等の源泉徴収税額", "申告する配当等について源泉徴収をされた所得税及び復興特別所得税の額（申告不要を選んだものを除く）", [f"{GENSEN}#1", f"{GENSEN}#3"])
所得税_上場株式等の譲渡の源泉徴収税額 = _input(
    "所得税_上場株式等の譲渡の源泉徴収税額", "申告する源泉徴収選択口座の源泉徴収税額（年間取引報告書の額。譲渡と配当を分ける資料がないので一緒に出す）", [f"{GENSEN}#3", f"{KABU}#5.2"]
)


# ---------------------------------------------------------------------------
# 公的年金等
# ---------------------------------------------------------------------------


class 所得税_公的年金等控除額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "公的年金等控除額（所得税法第35条第4項、租税特別措置法第41条の15の3）。所得の金額が正なら収入金額−丸めた所得の金額"
    reference = [f"{NENKIN}#2.1", f"{NENKIN}#2.2"]

    def formula_2025_01_01(人, period, parameters):
        収入 = 人("所得税_公的年金等の収入金額", period)
        if not np.any(収入 > 0):
            return np.zeros(len(収入), dtype=np.int32)
        年齢 = 人("所得税_年齢", period)
        以外 = 人("所得税_公的年金等に係る雑所得以外の合計所得金額", period)
        r = pension_rules(parameters(period))
        金額 = [int(x) for x in 収入]
        控除 = [pension_deduction(a, int(o), int(g), r) for a, o, g in zip(金額, 以外, 年齢)]
        # 公的年金等に係る雑所得の金額の1円未満は切捨て（手引き 3-2_07。calc.PENSION_FLOOR）
        return _yen([pension_deduction_yen(a, d, PENSION_FLOOR.apply) for a, d in zip(金額, 控除)], "公的年金等控除額")


class 所得税_65歳以上の者に係る公的年金等控除額の控除を受けたか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "年齢65歳以上である者に係る公的年金等控除額の控除を受けたか（公的年金等の収入があり、その年12月31日の年齢が65歳以上。措法41の15の3）"
    reference = [f"{NENKIN}#2.2"]

    def formula_2025_01_01(人, period, parameters):
        年齢の境 = int(parameters(period).所得税.公的年金等控除額.六十五歳以上の特例.年齢)
        return (人("所得税_公的年金等の収入金額", period) > 0) & (人("所得税_年齢", period) >= 年齢の境)


class 所得税_公的年金等に係る雑所得の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "公的年金等に係る雑所得の金額（所得税法第35条第2項第1号：収入金額から公的年金等控除額を控除した残額）"
    reference = [f"{NENKIN}#1.1", f"{NENKIN}#2.1"]

    def formula_2025_01_01(人, period, parameters):
        収入 = 人("所得税_公的年金等の収入金額", period)
        控除 = 人("所得税_公的年金等控除額", period)
        return np.maximum(収入 - 控除, 0).astype(np.int32)


# ---------------------------------------------------------------------------
# 一時所得・退職所得
# ---------------------------------------------------------------------------


class 所得税_一時所得の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "一時所得の金額（所得税法第34条第2項・第3項。2分の1にする前）"
    reference = [f"{JIGYO}#6"]

    def formula_2025_01_01(人, period, parameters):
        総収入 = 人("所得税_一時所得の総収入金額", period)
        支出 = 人("所得税_一時所得の支出した金額", period)
        special = parameters(period).所得税.一時所得.特別控除額
        return _yen([windfall_income(int(t), int(e), int(special)) for t, e in zip(総収入, 支出)], "一時所得の金額")


class 所得税_退職所得の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "退職所得の金額（所得税法第30条第2項〜第6項）"
    reference = [f"{TAISHOKU}#2.1", f"{TAISHOKU}#2.4"]

    def formula_2025_01_01(人, period, parameters):
        収入 = 人("所得税_退職手当等の収入金額", period)
        if not np.any(収入 > 0):
            return np.zeros(len(収入), dtype=np.int32)
        年数 = 人("所得税_退職所得の勤続年数", period)
        区分 = 人("所得税_退職手当等の区分", period)
        障害 = 人("所得税_障害者になったことに直接基因する退職か", period)
        前 = 人("所得税_前の退職手当等との重複年数", period)
        短期額 = 人("所得税_短期退職手当等の収入金額", period)
        役員額 = 人("所得税_特定役員退職手当等の収入金額", period)
        短期控除 = 人("所得税_短期退職所得控除額", period)
        役員控除 = 人("所得税_特定役員退職所得控除額", period)
        r = retirement_rules(parameters(period))
        金額 = [int(x) for x in 収入]
        種類 = [str(k) for k in 区分]
        控除 = [retirement_deduction(max(1, int(y)), bool(d), r, int(q)) for y, d, q in zip(年数, 障害, 前)]
        raw: list[Fraction | None] = []
        for a, dd, k, s, o, sd, od in zip(金額, 控除, 種類, 短期額, 役員額, 短期控除, 役員控除):
            s, o = int(s), int(o)
            if a and (s or o):  # 二以上の区分（所法30⑦・所令71の2）
                raw.append(retirement_income_multi(a - s - o, s, o, dd, int(sd), int(od), r))
            else:
                raw.append(None)
        if any(retirement_has_fraction(a, d, k, r) for a, d, k, m in zip(金額, 控除, 種類, raw) if m is None) or any(
            m is not None and m.denominator != 1 for m in raw
        ):  # 端数が出ないなら候補に依存しない
            候補 = [FUNCTIONS[str(c)] for c in 人("所得税_所得の金額の端数の候補", period)]
        else:
            候補 = [floor_yen] * len(金額)
        out = []
        for a, d, k, f, m in zip(金額, 控除, 種類, 候補, raw):
            if not a:
                out.append(0)
            elif m is not None:
                out.append(int(m) if m.denominator == 1 else f(m))
            else:
                out.append(retirement_income(a, d, k, r, f))
        return _yen(out, "退職所得の金額")


# ---------------------------------------------------------------------------
# 事業所得・業務に係る雑所得・雑所得
# ---------------------------------------------------------------------------


class 所得税_青色申告の承認を受けているか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "その年分について青色申告の承認を受けているか（所得税法第143条〜第147条・第150条・第151条）"
    reference = [f"{AOIRO}#1.1", f"{AOIRO}#1.4"]

    def formula_2025_01_01(人, period, parameters):
        return 人("所得税_青色申告の承認の状態", period) == BLUE_APPROVED


def home_worker_amounts(額: int, 家内: Any, 給与: Any, 控除: Any) -> list[int]:
    """家内労働者等の特例の額（措法27）。給与所得を有する人は「特例の額 − 給与所得控除額」（給与所得控除額のほうが大きければ0）。

    差し引く給与所得控除額は、給与等の収入金額を限度にする（国税庁の計算書の④「給与所得の収入金額」：jigyo-laws-and-nta §2.3・§2.4。
    令和7年分は所法28③一の文言〔収入にかかわらず65万円〕と食い違うので、公式の説明の読み（D22 S1）で計算し根拠に「法令の読み」を付ける。
    令和8年分は措法29の4① の給与所得控除額が収入金額を超えないので同じ値：jigyo-calculation-model H2。2026-11-11 の結合のレビューで、
    文言どおりの値を印なしで出していたのを直した）。
    """
    return [max(0, 額 - min(int(c), int(s))) if bool(k) and int(s) > 0 else 額 for k, s, c in zip(家内, 給与, 控除)]


def _zeros(n: int) -> np.ndarray:
    return np.zeros(n, dtype=np.int32)


class 所得税_青色申告特別控除前の事業所得の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "青色申告特別控除の前の事業所得の金額（総収入金額−必要経費〔家内労働者等の特例・減価償却費・専従者給与等を含む〕）"
    reference = [f"{JIGYO}#1.1", f"{JIGYO}#2.1"]

    def formula_2025_01_01(人, period, parameters):
        事業収入 = 人("所得税_事業所得の総収入金額", period)
        事業経費 = 人("所得税_事業所得の必要経費", period)
        雑収入 = 人("所得税_業務に係る雑所得の総収入金額", period)
        雑経費 = 人("所得税_業務に係る雑所得の必要経費", period)
        家内 = 人("所得税_家内労働者等か", period)
        減価 = 人("所得税_事業所得の減価償却費", period)
        専従給与 = 人("所得税_事業所得の青色事業専従者給与の額", period)
        専従控除 = 人("所得税_事業所得の事業専従者控除額", period)
        雑減価 = 人("所得税_業務に係る雑所得の減価償却費", period)
        額 = int(parameters(period).所得税.家内労働者等の必要経費の特例.額)
        給与 = 人("所得税_給与等の収入金額", period) if np.any(家内) else _zeros(len(家内))
        控除 = 人("所得税_給与所得控除額", period) if np.any(家内 & (給与 > 0)) else _zeros(len(家内))
        額一覧 = home_worker_amounts(額, 家内, 給与, 控除)
        out = []
        for rb, eb, rm, em, k, dep, s1, s2, md, a in zip(事業収入, 事業経費, 雑収入, 雑経費, 家内, 減価, 専従給与, 専従控除, 雑減価, 額一覧):
            other = int(dep) + int(s1) + int(s2)
            e = home_worker_expenses(int(rb), int(eb) + other, int(rm), int(em) + int(md), a, bool(k))
            out.append(int(rb) - e.business)
        return _yen(out, "青色申告特別控除前の事業所得の金額")


class 所得税_業務に係る雑所得の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "業務に係る雑所得の金額（所得税法第35条第2項第2号のうち業務に係るもの：総収入金額−必要経費。負になりうる）"
    reference = [f"{JIGYO}#1.1", f"{JIGYO}#2.1"]

    def formula_2025_01_01(人, period, parameters):
        雑収入 = 人("所得税_業務に係る雑所得の総収入金額", period)
        雑経費 = 人("所得税_業務に係る雑所得の必要経費", period)
        雑減価 = 人("所得税_業務に係る雑所得の減価償却費", period)
        家内 = 人("所得税_家内労働者等か", period)
        if not np.any(家内):
            return (雑収入 - 雑経費 - 雑減価).astype(np.int32)
        事業収入 = 人("所得税_事業所得の総収入金額", period)
        事業経費 = 人("所得税_事業所得の必要経費", period)
        減価 = 人("所得税_事業所得の減価償却費", period)
        専従給与 = 人("所得税_事業所得の青色事業専従者給与の額", period)
        専従控除 = 人("所得税_事業所得の事業専従者控除額", period)
        額 = int(parameters(period).所得税.家内労働者等の必要経費の特例.額)
        給与 = 人("所得税_給与等の収入金額", period)
        控除 = 人("所得税_給与所得控除額", period) if np.any(家内 & (給与 > 0)) else _zeros(len(家内))
        額一覧 = home_worker_amounts(額, 家内, 給与, 控除)
        out = []
        for rb, eb, rm, em, md, k, dep, s1, s2, a in zip(事業収入, 事業経費, 雑収入, 雑経費, 雑減価, 家内, 減価, 専従給与, 専従控除, 額一覧):
            other = int(dep) + int(s1) + int(s2)
            e = home_worker_expenses(int(rb), int(eb) + other, int(rm), int(em) + int(md), a, bool(k))
            out.append(int(rm) - e.misc)
        return _yen(out, "業務に係る雑所得の金額")


class 所得税_青色申告特別控除前の不動産所得の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "青色申告特別控除の前の不動産所得の金額（総収入金額−必要経費−減価償却費−専従者給与等。組合事業等・国外中古建物の損失で生じなかったものと"
        "みなす金額〔措法41の4の2・41の4の3〕は除く。負になりうる）"
    )
    reference = [f"{FUDOSAN}#2.1", f"{FUDOSAN}#2.3", f"{FUDOSAN5}#2", f"{FUDOSAN5}#3"]

    def formula_2025_01_01(人, period, parameters):
        return (
            人("所得税_不動産所得の総収入金額", period)
            - 人("所得税_不動産所得の必要経費", period)
            - 人("所得税_不動産所得の減価償却費", period)
            - 人("所得税_不動産所得の青色事業専従者給与の額", period)
            - 人("所得税_不動産所得の事業専従者控除額", period)
            + 人("所得税_組合事業等と国外中古建物の不動産所得の損失のうち生じなかったものとみなす金額", period)
        ).astype(np.int32)


class 所得税_青色申告特別控除額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "青色申告特別控除額（租税特別措置法第25条の2。不動産所得の金額・事業所得の金額から順次控除する額の合計）"
    reference = [f"{AOIRO}#3.1", f"{AOIRO}#3.2"]

    def formula_2025_01_01(人, period, parameters):
        承認 = 人("所得税_青色申告の承認を受けているか", period)
        不動産 = 人("所得税_青色申告特別控除前の不動産所得の金額", period)
        事業 = 人("所得税_青色申告特別控除前の事業所得の金額", period)
        簿記 = 人("所得税_正規の簿記の要件", period)
        申告 = 人("所得税_青色申告特別控除の申告の要件", period)
        r = blue_rules(parameters(period))
        return _yen([blue_deduction_split(bool(a), int(b), int(c), bool(d), str(e), r)[0] for a, b, c, d, e in zip(承認, 不動産, 事業, 簿記, 申告)], "青色申告特別控除額")


class 所得税_不動産所得から控除する青色申告特別控除額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "青色申告特別控除額のうち不動産所得の金額から控除する額（措法25の2②・⑤の順次控除）"
    reference = [f"{FUDOSAN}#3.4", f"{AOIRO}#3.1"]

    def formula_2025_01_01(人, period, parameters):
        総額 = 人("所得税_青色申告特別控除額", period)
        不動産 = 人("所得税_青色申告特別控除前の不動産所得の金額", period)
        return np.minimum(総額, np.maximum(不動産, 0)).astype(np.int32)


class 所得税_事業所得から控除する青色申告特別控除額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "青色申告特別控除額のうち事業所得の金額から控除する額（措法25の2②・⑤の順次控除）"
    reference = [f"{FUDOSAN}#3.4", f"{AOIRO}#3.1"]

    def formula_2025_01_01(人, period, parameters):
        総額 = 人("所得税_青色申告特別控除額", period)
        不動産分 = 人("所得税_不動産所得から控除する青色申告特別控除額", period)
        return (総額 - 不動産分).astype(np.int32)


class 所得税_事業所得の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "事業所得の金額（所得税法第27条第2項、租税特別措置法第25条の2：青色申告特別控除の後。負になりうる）"
    reference = [f"{JIGYO}#1.1", f"{AOIRO}#3.1"]

    def formula_2025_01_01(人, period, parameters):
        前 = 人("所得税_青色申告特別控除前の事業所得の金額", period)
        控除 = 人("所得税_事業所得から控除する青色申告特別控除額", period)
        return (前 - 控除).astype(np.int32)


class 所得税_不動産所得の損失のうち生じなかったものとみなす金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "不動産所得の損失のうち生じなかったものとみなす金額（措法41の4・所法69②：損失が土地等の負債の利子・別荘等の貸付けによるものの部分）"
    reference = [f"{FUDOSAN}#4.1", f"{FUDOSAN}#4.3"]

    def formula_2025_01_01(人, period, parameters):
        前 = 人("所得税_青色申告特別控除前の不動産所得の金額", period)
        控除 = 人("所得税_不動産所得から控除する青色申告特別控除額", period)
        利子 = 人("所得税_土地等を取得するために要した負債の利子の額", period)
        別荘 = 人("所得税_不動産所得の貸付けがすべて別荘等か", period)
        別荘損失 = 人("所得税_別荘等の貸付けに係る損失の額", period)
        return _yen(
            [rental_loss_excluded(int(b) - int(c), int(l), bool(v), int(w)) for b, c, l, v, w in zip(前, 控除, 利子, 別荘, 別荘損失)], "生じなかったものとみなす金額"
        )


class 所得税_不動産所得の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "不動産所得の金額（所得税法第26条第2項、租税特別措置法第25条の2：青色申告特別控除の後。損失のうち通算できない部分〔措法41の4・所法69②〕を除く。負になりうる）"
    reference = [f"{FUDOSAN}#2.1", f"{FUDOSAN}#4.3"]

    def formula_2025_01_01(人, period, parameters):
        前 = 人("所得税_青色申告特別控除前の不動産所得の金額", period)
        控除 = 人("所得税_不動産所得から控除する青色申告特別控除額", period)
        除外 = 人("所得税_不動産所得の損失のうち生じなかったものとみなす金額", period)
        return (前 - 控除 + 除外).astype(np.int32)


class 所得税_減価償却費の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "必要経費に算入する減価償却費の額（事業所得・不動産所得・業務に係る雑所得の合計）"
    reference = [f"{GENKA}#2.1", f"{GENKA}#3.1"]

    def formula_2025_01_01(人, period, parameters):
        return (
            人("所得税_事業所得の減価償却費", period)
            + 人("所得税_不動産所得の減価償却費", period)
            + 人("所得税_業務に係る雑所得の減価償却費", period)
        ).astype(np.int32)


class 所得税_青色事業専従者給与の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "必要経費に算入する青色事業専従者給与の額（所得税法第57条第1項。事業所得と不動産所得の合計）"
    reference = [f"{AOIRO}#4.1"]

    def formula_2025_01_01(人, period, parameters):
        return (人("所得税_事業所得の青色事業専従者給与の額", period) + 人("所得税_不動産所得の青色事業専従者給与の額", period)).astype(np.int32)


class 所得税_事業専従者控除額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "事業専従者控除額（所得税法第57条第3項。事業所得と不動産所得の合計）"
    reference = [f"{FUDOSAN}#5.1"]

    def formula_2025_01_01(人, period, parameters):
        return (人("所得税_事業所得の事業専従者控除額", period) + 人("所得税_不動産所得の事業専従者控除額", period)).astype(np.int32)


class 所得税_その他の雑所得の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "その他の雑所得の金額（公的年金等・業務に係るもの以外：所得税法第35条第2項第2号。負になりうる）"
    reference = [f"{NENKIN}#1.1", f"{NENKIN}#1.2"]

    def formula_2025_01_01(人, period, parameters):
        return (人("所得税_その他の雑所得の総収入金額", period) - 人("所得税_その他の雑所得の必要経費", period)).astype(np.int32)


class 所得税_雑所得の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "雑所得の金額（所得税法第35条第2項：公的年金等に係るものと、それ以外〔業務・その他〕の合計額）"
    reference = [f"{NENKIN}#1.1"]

    def formula_2025_01_01(人, period, parameters):
        公的 = 人("所得税_公的年金等に係る雑所得の金額", period)
        業務 = 人("所得税_業務に係る雑所得の金額", period)
        その他 = 人("所得税_その他の雑所得の金額", period)
        return (公的 + 業務 + その他).astype(np.int32)


class 所得税_配当所得の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "配当所得の金額（総合課税によるもの。所得税法第24条）"
    reference = [f"{KABU}#1.2", f"{KABU}#2.1"]

    def formula_2025_01_01(人, period, parameters):
        return np.maximum(人("所得税_総合課税の配当等の収入金額", period) - 人("所得税_総合課税の配当等の負債の利子", period), 0).astype(np.int32)


class 所得税_上場株式等に係る配当所得等の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "上場株式等に係る配当所得等の金額（申告分離課税を選んだもの。措法8の4①）"
    reference = [f"{KABU}#1.1", f"{KABU}#1.3"]

    def formula_2025_01_01(人, period, parameters):
        return np.maximum(人("所得税_申告分離課税の配当等の収入金額", period) - 人("所得税_申告分離課税の配当等の負債の利子", period), 0).astype(np.int32)


class 所得税_上場株式等に係る譲渡所得等の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "上場株式等に係る譲渡所得等の金額（損益通算・繰越控除の前。負になりうる。措法37の11）"
    reference = [f"{KABU}#4"]

    def formula_2025_01_01(人, period, parameters):
        収入 = 人("所得税_上場株式等の譲渡の収入金額", period)
        費用 = 人("所得税_上場株式等の譲渡の取得費等", period)
        return (収入 - 費用).astype(np.int32)


VARIABLES = (
    所得税_公的年金等の収入金額,
    所得税_その他の雑所得の総収入金額,
    所得税_その他の雑所得の必要経費,
    所得税_不動産所得の総収入金額,
    所得税_不動産所得の必要経費,
    所得税_不動産所得の減価償却費,
    所得税_事業所得の減価償却費,
    所得税_業務に係る雑所得の減価償却費,
    所得税_不動産の貸付けが事業として行われているか,
    所得税_土地等を取得するために要した負債の利子の額,
    所得税_不動産所得の貸付けがすべて別荘等か,
    所得税_別荘等の貸付けに係る損失の額,
    所得税_組合事業等と国外中古建物の不動産所得の損失のうち生じなかったものとみなす金額,
    所得税_事業所得の青色事業専従者給与の額,
    所得税_不動産所得の青色事業専従者給与の額,
    所得税_事業所得の事業専従者控除額,
    所得税_不動産所得の事業専従者控除額,
    所得税_事業専従者としてみなされる給与の収入金額,
    所得税_生計を一にする親族の事業から受けた給与のうち収入金額に含めない額,
    所得税_退職手当等に当たらないとした給与等の収入金額,
    所得税_総合課税の配当等の負債の利子,
    所得税_申告分離課税の配当等の負債の利子,
    所得税_公的年金等の源泉徴収税額,
    所得税_退職所得の源泉徴収税額,
    所得税_配当等の源泉徴収税額,
    所得税_配当控除の対象の剰余金の配当等に係る配当所得の金額,
    所得税_配当控除の対象の証券投資信託の収益の分配に係る配当所得の金額,
    所得税_配当控除の対象の一般外貨建等証券投資信託の収益の分配に係る配当所得の金額,
    所得税_上場株式等の譲渡の源泉徴収税額,
    所得税_一時所得の総収入金額,
    所得税_一時所得の支出した金額,
    所得税_退職手当等の収入金額,
    所得税_退職所得の勤続年数,
    所得税_退職手当等の区分,
    所得税_障害者になったことに直接基因する退職か,
    所得税_前の退職手当等との重複年数,
    所得税_短期退職手当等の収入金額,
    所得税_特定役員退職手当等の収入金額,
    所得税_短期退職所得控除額,
    所得税_特定役員退職所得控除額,
    所得税_事業所得の総収入金額,
    所得税_事業所得の必要経費,
    所得税_業務に係る雑所得の総収入金額,
    所得税_業務に係る雑所得の必要経費,
    所得税_家内労働者等か,
    所得税_青色申告の承認の状態,
    所得税_正規の簿記の要件,
    所得税_青色申告特別控除の申告の要件,
    所得税_所得の金額の端数の候補,
    所得税_総合課税の配当等の収入金額,
    所得税_申告分離課税の配当等の収入金額,
    所得税_上場株式等の譲渡の収入金額,
    所得税_上場株式等の譲渡の取得費等,
    所得税_公的年金等控除額,
    所得税_65歳以上の者に係る公的年金等控除額の控除を受けたか,
    所得税_公的年金等に係る雑所得の金額,
    所得税_一時所得の金額,
    所得税_退職所得の金額,
    所得税_青色申告の承認を受けているか,
    所得税_青色申告特別控除前の事業所得の金額,
    所得税_業務に係る雑所得の金額,
    所得税_青色申告特別控除額,
    所得税_事業所得の金額,
    所得税_不動産所得から控除する青色申告特別控除額,
    所得税_事業所得から控除する青色申告特別控除額,
    所得税_青色申告特別控除前の不動産所得の金額,
    所得税_不動産所得の損失のうち生じなかったものとみなす金額,
    所得税_不動産所得の金額,
    所得税_減価償却費の額,
    所得税_青色事業専従者給与の額,
    所得税_事業専従者控除額,
    所得税_その他の雑所得の金額,
    所得税_雑所得の金額,
    所得税_配当所得の金額,
    所得税_上場株式等に係る配当所得等の金額,
    所得税_上場株式等に係る譲渡所得等の金額,
)

"""規則モジュール kokunen の変数（国民年金）。

- 年度 F の値（免除・納付猶予・学生納付特例の所得基準、保険料の月額）は所得の年分 F−1 の situation で計算する。所得は前年の所得
  （F年7月〜F+1年6月の月分。学生納付特例は F年4月〜F+1年3月：[KHP] §12.3）。政令の値・保険料改定率のパラメータの日付のキーは
  所得の年分の1月1日（年度 F の値は F−1 年1月1日。juminzei と同じ約束：parameters/国年/index.yaml）で、式は同じ期間で引く。
- 判定日 D の値（第3号被保険者）は D の属する暦年の situation で計算する。
- 扶養親族等（所得税法に規定する同一生計配偶者及び扶養親族：国民年金法第36条の3第1項）は所得税の扶養所属・法律婚のグループの値を数える
  （配偶者は扶養所属のグループに入らない。所得税_同一生計配偶者に当たるか は本人から見た配偶者についての値で本人の側に立つので、
  そのまま数え、配偶者の年齢・障害は 人.法律婚.sum(…) − 自分 で引く）。扶養の連鎖の人は段 国年の扶養の連鎖の扶養親族等 が書く入力で足す。
- 一部免除判定所得で差し引く控除のうち、住民税と所得税で額が同じ規定のもの（社会保険料控除・小規模企業共済等掛金控除は全額、雑損控除・
  医療費控除は同じ計算）は所得税の値で引き（法令の読み。README §4）、額が違う配偶者特別控除・特定親族特別控除は住民税の額（juminzei）を引く。
- 国年令第6条の11・第6条の12 の所得の列挙に、上場株式等に係る配当所得等・譲渡所得等（地方税法附則第33条の2第5項・第35条の2の2第5項）はない
  （原文：scripts/results/IMPL3_egov_fetch/kokunen/grep_kokunenrei_2027-04-01.txt の Num=6_11・6_12）。住民税の合計所得金額・総所得金額等から除く。
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

import numpy as np
from openfisca_core.model_api import YEAR, Variable

from ...country.entities import 人物, 扶養所属
from ...money import INT32_MAX
from .calc import (
    SpouseSupport,
    applied_criterion,
    full_exemption_threshold,
    listed_before_carry,
    monthly_premium,
    stricter,
    supported_principle,
    なし,
    半額,
    四分の一,
    四分の三,
)

_KHP = "docs/public-sources/20261109_round2_kokuho-premium-structure.md"
_ZG = "docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md#8.1"
_SP = "docs/public-sources/20261109_round2_spouse-laws-and-sources.md"
_D3 = "docs/public-sources/20261109_round3_dai3go-notice-search.md"
_KN3 = "docs/public-sources/20261111_impl-research3_kokunen-laws.md"
_ZGV = "docs/measurements/20261109_impl-prep_zeigaku-verify.md"
#: 国年令第6条の12第2項第1号の特定親族特別控除額を差し引くのは、令和8年度の基準月（6月）の翌月以後の月分から
#: （令和7年政令第355号附則第2条第2項：docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md §8.1）。
SPECIFIC_RELATIVE_FROM_FY = 2026


def _年度(period: Any) -> int:
    """年度 F の値は所得の年分 F−1 の期間で計算する。"""
    return int(period.start.year) + 1


def _yen(values: Any) -> np.ndarray:
    """整数の円の配列（int32）。int32 を超える値は、int32 を超える入力（evaluate は OpenFisca に渡さず対象外にする：packages/core/README.md §5）か、
    人の数の上限（2,000 人）を超える扶養親族等の数からしか生じないので、端で止める（構造の検査の架空の大きな入力で式が落ちないため。juminzei と同じ）。"""
    arr = np.array([int(v) for v in values], dtype=np.int64)
    return np.clip(arr, -INT32_MAX, INT32_MAX).astype(np.int32)


# ---------------------------------------------------------------------------
# 入力変数（判定日の事実。inputs.build_inputs が書く）
# ---------------------------------------------------------------------------


class 年金_判定日の年齢(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "判定日の年齢（誕生日の前日に1歳を加える）"
    reference = [f"{_SP}#5.1", "docs/public-sources/20261109_R1-laws_social-insurance-age-records.md#3"]


class 年金_本人が第2号被保険者か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "判定日に本人が第2号被保険者か（第2号被保険者は第3号被保険者から除かれる：国民年金法第7条第1項第3号）"
    reference = [f"{_SP}#5.1"]


class 年金_配偶者が第2号被保険者か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "判定日に配偶者（事実婚を含む）が第2号被保険者か（65歳以上で老齢・退職の年金の受給権がある人を除く：附則第3条）"
    reference = [f"{_SP}#5.1"]


class 年金_国内居住の要件を満たすか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "判定日に国内に住所を有するか、国年則第1条の3 の例外（留学・同行・一時的な渡航・その他生活の基礎が国内）に当たるか"
    reference = [f"{_SP}#5.1"]


class 年金_被扶養配偶者の年間収入(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "被扶養配偶者の認定の年間収入（判定日以降の年間の見込み。令和8年4月以後は労働契約の内容による年収）"
    reference = [f"{_D3}#3", f"{_D3}#3.1", "docs/public-sources/20261109_R3-tsutatsu_shakaihoken-juminzei.md#1.3"]


class 年金_第2号被保険者の年間収入(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "配偶者である第2号被保険者の年間収入の見込み（同一世帯の2分の1の比較に使う）"
    reference = [f"{_D3}#3", f"{_D3}#3.1"]


class 年金_第2号被保険者と同一の世帯に属するか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "判定日に配偶者である第2号被保険者と同居しているか（cohabitation・dwelling_stay）"
    reference = [f"{_D3}#1.1", f"{_D3}#3"]


class 年金_第2号被保険者からの援助による収入額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "別世帯の場合の、第2号被保険者からの援助による収入額の見込み（年額）"
    reference = [f"{_D3}#3", f"{_D3}#3.1"]


class 年金_免除等の期間の学生等である月数(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "年度 F の免除等の期間（F年7月〜F+1年6月）の月のうち学生等である月の数（全額免除・一部免除・納付猶予の期間から除かれる：国民年金法第90条第1項柱書）"
    reference = [f"{_KN3}#2"]


class 年金_学生納付特例の期間の学生等である月数(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "年度 F の学生納付特例の期間（F年4月〜F+1年3月）の月のうち学生等である月の数（学生納付特例はこの月に限る：国民年金法第90条の3第1項）"
    reference = [f"{_KN3}#2"]


class 年金_産前産後の免除の月数(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "年度 F の月（F年4月〜F+1年3月）のうち、第1号被保険者で産前産後の期間（国民年金法第88条の2）として保険料の納付を要しない月の数"
    reference = [f"{_KN3}#4"]


class 年金_育児期間の免除の月数(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "年度 F の月のうち、第1号被保険者で育児期間（国民年金法第88条の3。2026年10月以後の月：令和6年法律第47号附則第10条）として保険料の納付を要しない月の数"
    reference = [f"{_KN3}#4", "docs/public-sources/20261112_impl-research4_kokunen-laws.md#2"]


class 年金_付加保険料を納付する者となることができる月数(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "年度 F の月のうち、申出をすれば付加保険料を納付できる月の数（第1号被保険者で、法定免除・全額免除・一部免除・学生納付特例・納付猶予の月でなく、"
        "国民年金基金の加入員でない月。産前産後・育児期間の月を含む：国民年金法第87条の2）"
    )
    reference = [f"{_KN3}#3"]


class 年金_申請する免除等の種類(Variable):
    value_type = str
    entity = 人物
    definition_period = YEAR
    default_value = "選択なし"
    label = (
        "選択.国民年金の免除の申請（年度）で申請する免除等の種類（全額免除・4分の3免除・半額免除・4分の1免除・納付猶予・学生納付特例・産前産後・"
        "種類の指定なし・申請しない・選択なし）"
    )
    reference = [f"{_KN3}#1", f"{_KN3}#4"]


class 年金_申請する免除等の所得の基準(Variable):
    value_type = str
    entity = 人物
    definition_period = YEAR
    label = (
        "申請する免除等の種類の所得の基準を、審査される人の全員が満たすか（満たす・満たさない・4月〜6月分だけ満たす・7月以後の月分だけ満たす、"
        "又は申請する種類の名前・申請しない・選択なし）。承認されるかではない（承認は npi_exemption）"
    )
    reference = [f"{_KN3}#1", f"{_KN3}#4"]

    def formula(人, period, parameters):
        種類 = 人("年金_申請する免除等の種類", period)
        全額 = 人("年金_全額免除の所得基準を満たすか", period)
        一部 = 人("年金_一部免除の区分", period)
        学生 = 人("年金_学生納付特例の所得基準を満たすか", period)
        学生_前 = 人("年金_令和8年6月以前の月分の学生納付特例の所得基準を満たすか", period)
        猶予 = 人("年金_納付猶予の所得基準を満たすか", period)
        return np.array(
            [
                applied_criterion(str(k), bool(f), str(t), bool(s), bool(e), bool(d))
                for k, f, t, s, e, d in zip(種類, 全額, 一部, 学生, 学生_前, 猶予)
            ],
            dtype=object,
        )


class 年金_付加保険料を納付する者である月数(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "年度 F の月のうち、付加保険料を納付する者である月の数（納付する者となることができる月のうち、付加保険料の納付の申出〔npi_application〕をした日の"
        "属する月以後で辞退の申出をするまでの月：国民年金法第87条の2第1項・第3項）"
    )
    reference = [f"{_KN3}#3"]


class 年金_連鎖の扶養親族等の数(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "扶養の連鎖の人（他の人の扶養親族等で、自分も申告者である人）のうち、この人の扶養親族等に数える人の数（段が書く）"
    reference = [f"{_KHP}#12.1", f"{_KHP}#12.2"]


class 年金_連鎖の扶養親族等の加算額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "扶養の連鎖の人の分の一部免除・学生納付特例の加算額（段が書く）"
    reference = [f"{_KHP}#12.2"]


class 年金_連鎖の扶養親族等の障害者の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "扶養の連鎖の人の分の、一部免除判定所得から差し引く障害者の額（27万円・特別障害者40万円。段が書く）"
    reference = [_ZG]


class 年金_世帯主及び配偶者が全額免除の所得基準を満たすか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "免除等の期間の初日の世帯主・配偶者（本人を除く）の全員が、全額免除の所得の基準（第90条第1項第1号・第3号）を満たすか（段が書く）"
    reference = [f"{_KHP}#12.1"]


class 年金_配偶者が全額免除の所得基準を満たすか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "免除等の期間の初日の配偶者が、納付猶予の所得の基準（全額免除と同じ式）を満たすか（段が書く）"
    reference = [f"{_KHP}#12.1", f"{_KHP}#12.2"]


class 年金_世帯主及び配偶者が満たす一部免除の区分(Variable):
    value_type = str
    entity = 人物
    definition_period = YEAR
    label = "世帯主・配偶者（本人を除く）の全員が満たす一部免除の区分（4分の3免除・半額免除・4分の1免除・なし。段が書く）"
    reference = [f"{_KHP}#12.1", f"{_KHP}#12.2"]


# ---------------------------------------------------------------------------
# 中心の概念（前年の所得）
# ---------------------------------------------------------------------------


class 年金_免除判定所得(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "全額免除・納付猶予の判定に使う所得（地方税法第313条第8項・第9項の繰越控除の前の総所得金額等＝住民税の合計所得金額）"
    reference = [f"{_KHP}#12.3"]

    def formula(人, period):
        # 住民税の合計所得金額（繰越控除の前）から、上場株式等の所得（損益通算の後・繰越控除の前：合計所得金額に入る額）を除く
        合計 = 人("住民税_合計所得金額", period)
        配当 = 人("所得税_上場株式等に係る配当所得等の金額", period)
        譲渡 = 人("所得税_上場株式等に係る譲渡所得等の金額", period)
        通算 = 人("所得税_上場株式等の譲渡損失の損益通算を適用するか", period)
        return _yen(int(g) - listed_before_carry(int(d), int(t), bool(o)) for g, d, t, o in zip(合計, 配当, 譲渡, 通算))


# ---------------------------------------------------------------------------
# 扶養親族等と基準額
# ---------------------------------------------------------------------------


class 年金_扶養親族等の数(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "所得税法に規定する同一生計配偶者及び扶養親族の数（特定年齢扶養親族〔30歳以上70歳未満〕は控除対象扶養親族に限る）"
    reference = [f"{_KHP}#12.1", f"{_KHP}#12.2"]

    def formula(人, period):
        扶養親族 = 人.扶養所属.sum(
            人("所得税_扶養親族に当たるか", period)
            * ~((人("所得税_年齢", period) >= 30) & (人("所得税_年齢", period) < 70) & ~人("所得税_控除対象扶養親族に当たるか", period))
            * 人.has_role(扶養所属.扶養親族等)
        ) * 人.has_role(扶養所属.申告者)
        # 所得税_同一生計配偶者に当たるか は「本人から見た配偶者について」の値（本人の側に立つ）
        配偶者 = 人("所得税_同一生計配偶者に当たるか", period) * 1
        連鎖 = 人("年金_連鎖の扶養親族等の数", period)
        return (扶養親族 + 配偶者 + 連鎖).astype(np.int32)


class 年金_全額免除の所得基準額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "全額免除・納付猶予の所得の基準額（(扶養親族等の数＋1)×35万円＋32万円）"
    reference = [f"{_KHP}#12.2"]

    def formula(人, period, parameters):
        数 = 人("年金_扶養親族等の数", period)
        p = parameters(period).国年.全額免除の所得基準
        return _yen(full_exemption_threshold(int(n), int(p.一人当たりの額), int(p.加算額)) for n in 数)


class 年金_一部免除の加算額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "一部免除・学生納付特例の基準額に加える扶養親族等の加算額（1人38万円。70歳以上の同一生計配偶者・老人扶養親族48万円、特定扶養親族等63万円）"
    reference = [f"{_KHP}#12.2", _ZG]

    def formula(人, period, parameters):
        p = parameters(period).国年.一部免除の所得基準.加算
        一般, 老人, 特定 = int(p.一般), int(p.老人等), int(p.特定扶養親族等)
        扶養親族 = 人.扶養所属.sum(
            人("所得税_扶養親族に当たるか", period)
            * ~((人("所得税_年齢", period) >= 30) & (人("所得税_年齢", period) < 70) & ~人("所得税_控除対象扶養親族に当たるか", period))
            * np.where(
                人("所得税_特定扶養親族に当たるか", period) | (人("所得税_控除対象扶養親族に当たるか", period) & (人("所得税_年齢", period) < 19)),
                特定,
                np.where(人("所得税_老人扶養親族に当たるか", period), 老人, 一般),
            )
            * 人.has_role(扶養所属.扶養親族等)
        ) * 人.has_role(扶養所属.申告者)
        # 同一生計配偶者の値は本人の側に立つ。配偶者の年齢は法律婚のグループの合計から自分を引く
        配偶者の年齢 = 人.法律婚.sum(人("所得税_年齢", period)) - 人("所得税_年齢", period)
        配偶者 = 人("所得税_同一生計配偶者に当たるか", period) * np.where(配偶者の年齢 >= 70, 老人, 一般)
        return _yen(扶養親族 + 配偶者 + 人("年金_連鎖の扶養親族等の加算額", period))


# ---------------------------------------------------------------------------
# 一部免除判定所得（住民税の総所得金額等から所得控除に相当する額を差し引く）
# ---------------------------------------------------------------------------


class 年金_一部免除判定所得(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "一部免除・学生納付特例の判定に使う所得（総所得金額等から雑損・医療費・社会保険料・小規模企業共済等掛金の控除と、障害者・寡婦・ひとり親・勤労学生の額を差し引く）"
    reference = [f"{_KHP}#12.3", _ZG]

    def formula(人, period, parameters):
        p = parameters(period).国年.一部免除判定所得
        障害, 特別, 寡婦, ひとり親, 勤労学生 = int(p.障害者), int(p.特別障害者), int(p.寡婦), int(p.ひとり親), int(p.勤労学生)
        控除 = (
            人("所得税_社会保険料控除の額", period)
            + 人("所得税_小規模企業共済等掛金控除の額", period)
            + 人("所得税_雑損控除の額", period)
            + 人("所得税_医療費控除の額", period)
            + 人("所得税_セルフメディケーション税制による医療費控除の額", period)
        )
        本人 = (
            np.where(人("所得税_特別障害者に当たるか", period), 特別, np.where(人("所得税_障害者に当たるか", period), 障害, 0))
            + np.where(人("所得税_寡婦に当たるか", period), 寡婦, 0)
            + np.where(人("所得税_ひとり親に当たるか", period), ひとり親, 0)
            + np.where(人("所得税_勤労学生に当たるか", period), 勤労学生, 0)
        )
        # 同一生計配偶者の値は本人の側に立つ。配偶者の障害者の額は法律婚のグループの合計から自分の分を引く
        自分の障害者の額 = np.where(人("所得税_特別障害者に当たるか", period), 特別, np.where(人("所得税_障害者に当たるか", period), 障害, 0))
        配偶者の障害者の額 = (
            人.法律婚.sum(np.where(人("所得税_特別障害者に当たるか", period), 特別, np.where(人("所得税_障害者に当たるか", period), 障害, 0)))
            - 自分の障害者の額
        )
        配偶者 = 人("所得税_同一生計配偶者に当たるか", period) * 配偶者の障害者の額
        扶養親族 = 人.扶養所属.sum(
            人("所得税_扶養親族に当たるか", period)
            * np.where(人("所得税_特別障害者に当たるか", period), 特別, np.where(人("所得税_障害者に当たるか", period), 障害, 0))
            * 人.has_role(扶養所属.扶養親族等)
        ) * 人.has_role(扶養所属.申告者)
        連鎖 = 人("年金_連鎖の扶養親族等の障害者の額", period)
        # 国年令第6条の12第2項第1号：市町村民税の配偶者特別控除額・特定親族特別控除額（特定親族は令和8年度の基準月の翌月以後の月分から）
        住民税の控除 = 人("住民税_配偶者特別控除の額", period) + 人("住民税_特定親族特別控除の額", period) * (_年度(period) >= SPECIFIC_RELATIVE_FROM_FY)
        # 上場株式等の所得は第6条の12第1項の列挙にない（総所得金額等には繰越控除の後の額が入っている）
        総所得金額等 = 人("住民税_総所得金額等", period) - 人("住民税_上場株式等に係る分離課税の所得の金額", period)
        return _yen(np.maximum(0, 総所得金額等 - 控除 - 本人 - 配偶者 - 扶養親族 - 連鎖 - 住民税の控除))


class 年金_令和8年6月以前の月分の一部免除判定所得(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "年度 F の月のうち令和8年6月以前の月分（学生納付特例の令和8年度の4月〜6月分）の一部免除判定所得：特定親族特別控除額を差し引かない従前の例"
        "（令和7年政令第355号附則第2条第2項）。その月がない年度は一部免除判定所得と同じ値"
    )
    reference = [_ZG, _ZGV]

    def formula(人, period):
        本則 = 人("年金_一部免除判定所得", period)
        特定親族 = 人("住民税_特定親族特別控除の額", period)
        return _yen(本則 + 特定親族 * (_年度(period) == SPECIFIC_RELATIVE_FROM_FY))


# ---------------------------------------------------------------------------
# 免除・納付猶予・学生納付特例の所得基準
# ---------------------------------------------------------------------------


class 年金_全額免除の所得基準を満たすか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "全額免除の所得の基準を、本人・世帯主・配偶者の全員が満たすか（第90条第1項第1号、又は第3号の障害者・寡婦・ひとり親で135万円以下）"
    reference = [f"{_KHP}#12.1", f"{_KHP}#12.2"]

    def formula(人, period, parameters):
        # 第1号（基準額以下）か第3号（地方税法に定める障害者・寡婦・ひとり親で135万円以下）：calc.meets_full と同じ
        該当 = 人("所得税_障害者に当たるか", period) | 人("所得税_寡婦に当たるか", period) | 人("所得税_ひとり親に当たるか", period)
        本人 = 人("年金_免除判定所得が全額免除の所得基準額以下か", period) | (該当 & 人("年金_免除判定所得が障害者等の所得の上限以下か", period))
        return 本人 & 人("年金_世帯主及び配偶者が全額免除の所得基準を満たすか", period)


class 年金_免除判定所得が全額免除の所得基準額以下か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "本人の免除判定所得が全額免除・納付猶予の所得の基準額以下か（国民年金法第90条第1項第1号、国年令第6条の7。境目の説明の判定）"
    reference = [f"{_KHP}#12.1", f"{_KHP}#12.2"]

    def formula(人, period):
        return 人("年金_免除判定所得", period) <= 人("年金_全額免除の所得基準額", period)


class 年金_免除判定所得が障害者等の所得の上限以下か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = (
        "本人の免除判定所得が、地方税法に定める障害者・寡婦・ひとり親の所得の上限（135万円）以下か"
        "（国民年金法第90条第1項第3号、国年令第6条の8。障害者等に当たるかは含まない。境目の説明の判定）"
    )
    reference = [f"{_KHP}#12.1", f"{_KN3}#1"]

    def formula(人, period, parameters):
        return 人("年金_免除判定所得", period) <= parameters(period).国年.全額免除の所得基準.障害者等の所得の上限


class 年金_4分の3免除の所得基準額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "4分の3免除の所得の基準額（88万円＋扶養親族等の加算額。国年令第6条の8の2。境目の説明の基準）"
    reference = [f"{_KHP}#12.2"]

    def formula(人, period, parameters):
        加算 = 人("年金_一部免除の加算額", period)
        基準 = int(parameters(period).国年.一部免除の所得基準.四分の三免除)
        return _yen(int(a) + 基準 for a in 加算)


class 年金_半額免除の所得基準額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "半額免除・学生納付特例の所得の基準額（128万円＋扶養親族等の加算額。国年令第6条の9。境目の説明の基準）"
    reference = [f"{_KHP}#12.2", _ZG]

    def formula(人, period, parameters):
        加算 = 人("年金_一部免除の加算額", period)
        基準 = int(parameters(period).国年.一部免除の所得基準.半額免除)
        return _yen(int(a) + 基準 for a in 加算)


class 年金_4分の1免除の所得基準額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "4分の1免除の所得の基準額（168万円＋扶養親族等の加算額。国年令第6条の9の2。境目の説明の基準）"
    reference = [f"{_KHP}#12.2"]

    def formula(人, period, parameters):
        加算 = 人("年金_一部免除の加算額", period)
        基準 = int(parameters(period).国年.一部免除の所得基準.四分の一免除)
        return _yen(int(a) + 基準 for a in 加算)


class 年金_一部免除判定所得が4分の3免除の所得基準額以下か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "本人の一部免除判定所得が4分の3免除の所得の基準額以下か（国民年金法第90条の2第1項第1号。境目の説明の判定）"
    reference = [f"{_KHP}#12.1", f"{_KHP}#12.2"]

    def formula(人, period):
        return 人("年金_一部免除判定所得", period) <= 人("年金_4分の3免除の所得基準額", period)


class 年金_一部免除判定所得が半額免除の所得基準額以下か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "本人の一部免除判定所得が半額免除・学生納付特例の所得の基準額以下か（国民年金法第90条の2第2項第1号・第90条の3第1項第1号。境目の説明の判定）"
    reference = [f"{_KHP}#12.1", f"{_KHP}#12.2", _ZG]

    def formula(人, period):
        return 人("年金_一部免除判定所得", period) <= 人("年金_半額免除の所得基準額", period)


class 年金_一部免除判定所得が4分の1免除の所得基準額以下か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "本人の一部免除判定所得が4分の1免除の所得の基準額以下か（国民年金法第90条の2第3項第1号。境目の説明の判定）"
    reference = [f"{_KHP}#12.1", f"{_KHP}#12.2"]

    def formula(人, period):
        return 人("年金_一部免除判定所得", period) <= 人("年金_4分の1免除の所得基準額", period)


class 年金_令和8年6月以前の月分の一部免除判定所得が半額免除の所得基準額以下か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "令和8年6月以前の月分の一部免除判定所得が学生納付特例の所得の基準額以下か（令和7年政令第355号附則第2条第2項。境目の説明の判定）"
    reference = [_ZG, _ZGV]

    def formula(人, period):
        return 人("年金_令和8年6月以前の月分の一部免除判定所得", period) <= 人("年金_半額免除の所得基準額", period)


class 年金_納付猶予の所得基準を満たすか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "納付猶予の所得の基準（全額免除と同じ式）を本人・配偶者が満たすか（世帯主は問わない）"
    reference = [f"{_KHP}#12.1", f"{_KHP}#12.2", f"{_KHP}#12.4"]

    def formula(人, period, parameters):
        # 第1号（全額免除と同じ式）か第2号（第90条第1項第3号の経路：障害者・寡婦・ひとり親で135万円以下。H8 の読み(a)）
        該当 = 人("所得税_障害者に当たるか", period) | 人("所得税_寡婦に当たるか", period) | 人("所得税_ひとり親に当たるか", period)
        本人 = 人("年金_免除判定所得が全額免除の所得基準額以下か", period) | (該当 & 人("年金_免除判定所得が障害者等の所得の上限以下か", period))
        return 本人 & 人("年金_配偶者が全額免除の所得基準を満たすか", period)


class 年金_一部免除の区分(Variable):
    value_type = str
    entity = 人物
    definition_period = YEAR
    label = "一部免除の所得の基準を本人・世帯主・配偶者の全員が満たす区分（4分の3免除・半額免除・4分の1免除・なし）"
    reference = [f"{_KHP}#12.1", f"{_KHP}#12.2"]

    def formula(人, period, parameters):
        ほか = 人("年金_世帯主及び配偶者が満たす一部免除の区分", period)
        # 第2号（第90条第1項第3号の経路。H8 の読み(a)）に当たれば第1項〜第3項の全部に当たる（calc.partial_tier_with_status と同じ順）
        該当 = 人("所得税_障害者に当たるか", period) | 人("所得税_寡婦に当たるか", period) | 人("所得税_ひとり親に当たるか", period)
        第2号 = 該当 & 人("年金_免除判定所得が障害者等の所得の上限以下か", period)
        四分の三_ = 人("年金_一部免除判定所得が4分の3免除の所得基準額以下か", period)
        半額_ = 人("年金_一部免除判定所得が半額免除の所得基準額以下か", period)
        四分の一_ = 人("年金_一部免除判定所得が4分の1免除の所得基準額以下か", period)
        return np.array(
            [
                stricter(四分の三 if (s or a) else 半額 if b else 四分の一 if c else なし, str(o) or 四分の三)
                for s, a, b, c, o in zip(第2号, 四分の三_, 半額_, 四分の一_, ほか)
            ],
            dtype=object,
        )


class 年金_学生納付特例の所得基準を満たすか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "学生納付特例の所得の基準を本人が満たすか（128万円＋扶養親族等の加算額以下、又は障害者・寡婦・ひとり親で135万円以下）"
    reference = [_ZG, f"{_KHP}#12.1"]

    def formula(人, period, parameters):
        第1号 = 人("年金_一部免除判定所得が半額免除の所得基準額以下か", period)
        該当 = 人("所得税_障害者に当たるか", period) | 人("所得税_寡婦に当たるか", period) | 人("所得税_ひとり親に当たるか", period)
        第2号 = 該当 & 人("年金_免除判定所得が障害者等の所得の上限以下か", period)
        return 第1号 | 第2号


class 年金_令和8年6月以前の月分の学生納付特例の所得基準を満たすか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "学生納付特例の所得の基準を本人が満たすか（年度 F の令和8年6月以前の月分：特定親族特別控除額を差し引かない一部免除判定所得で判定）"
    reference = [_ZG, _ZGV, f"{_KHP}#12.1"]

    def formula(人, period, parameters):
        第1号 = 人("年金_令和8年6月以前の月分の一部免除判定所得が半額免除の所得基準額以下か", period)
        該当 = 人("所得税_障害者に当たるか", period) | 人("所得税_寡婦に当たるか", period) | 人("所得税_ひとり親に当たるか", period)
        第2号 = 該当 & 人("年金_免除判定所得が障害者等の所得の上限以下か", period)
        return 第1号 | 第2号


class 年金_付加保険料の月額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "付加保険料の月額（国民年金法第87条の2第1項：400円）"
    reference = [f"{_KN3}#3"]

    def formula(人, period, parameters):
        return int(parameters(period).国年.付加保険料の額)


class 年金_保険料の月額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "国民年金保険料の月額（年度 F に属する月分。法定額×保険料改定率、5円未満切捨て・5円以上10円未満は10円に切上げ）"
    reference = [f"{_KHP}#11.1", f"{_KHP}#10"]

    def formula(人, period, parameters):
        p = parameters(period).国年.保険料の額
        # 全員に同じ値（OpenFisca が人の数の配列にする）
        return monthly_premium(int(p.法定額), Fraction(int(p.保険料改定率.分子), int(p.保険料改定率.分母)))


# ---------------------------------------------------------------------------
# 第3号被保険者（判定日）
# ---------------------------------------------------------------------------


class 年金_第3号被保険者に当たるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "判定日に第3号被保険者に当たるか（第2号被保険者の配偶者で、主として第2号の収入により生計を維持する20歳以上60歳未満の国内居住者）"
    reference = [f"{_SP}#5.1", f"{_SP}#5.2", f"{_D3}#3.1", f"{_D3}#6"]

    def formula(人, period):
        # 収入の基準の値（130万円・180万円・2分の1）は健保の約束の概念を引く（国年令第4条：健保の認定の取扱いを勘案。structure.yaml）
        年齢 = 人("年金_判定日の年齢", period)
        基準額 = 人("健保_配偶者の収入の基準額", period)
        割合 = 人("健保_同一の世帯の収入の割合", period)
        年間収入 = 人("年金_被扶養配偶者の年間収入", period)
        同一世帯 = 人("年金_第2号被保険者と同一の世帯に属するか", period)
        第2号の収入 = 人("年金_第2号被保険者の年間収入", period)
        援助 = 人("年金_第2号被保険者からの援助による収入額", period)
        生計維持 = np.array(
            [
                supported_principle(SpouseSupport(int(i), int(b), bool(s), int(q), int(a), Fraction(str(r))))
                for i, b, s, q, a, r in zip(年間収入, 基準額, 同一世帯, 第2号の収入, 援助, 割合)
            ],
            dtype=bool,
        )
        return (
            (年齢 >= 20)
            & (年齢 < 60)
            & 人("年金_配偶者が第2号被保険者か", period)
            & 人("年金_国内居住の要件を満たすか", period)
            & ~人("年金_本人が第2号被保険者か", period)
            & 生計維持
        )


VARIABLES: tuple[type, ...] = (
    年金_判定日の年齢,
    年金_本人が第2号被保険者か,
    年金_配偶者が第2号被保険者か,
    年金_国内居住の要件を満たすか,
    年金_被扶養配偶者の年間収入,
    年金_第2号被保険者の年間収入,
    年金_第2号被保険者と同一の世帯に属するか,
    年金_第2号被保険者からの援助による収入額,
    年金_免除等の期間の学生等である月数,
    年金_学生納付特例の期間の学生等である月数,
    年金_産前産後の免除の月数,
    年金_育児期間の免除の月数,
    年金_付加保険料を納付する者となることができる月数,
    年金_付加保険料を納付する者である月数,
    年金_申請する免除等の種類,
    年金_申請する免除等の所得の基準,
    年金_連鎖の扶養親族等の数,
    年金_連鎖の扶養親族等の加算額,
    年金_連鎖の扶養親族等の障害者の額,
    年金_世帯主及び配偶者が全額免除の所得基準を満たすか,
    年金_配偶者が全額免除の所得基準を満たすか,
    年金_世帯主及び配偶者が満たす一部免除の区分,
    年金_免除判定所得,
    年金_扶養親族等の数,
    年金_全額免除の所得基準額,
    年金_一部免除の加算額,
    年金_一部免除判定所得,
    年金_免除判定所得が全額免除の所得基準額以下か,
    年金_免除判定所得が障害者等の所得の上限以下か,
    年金_4分の3免除の所得基準額,
    年金_半額免除の所得基準額,
    年金_4分の1免除の所得基準額,
    年金_一部免除判定所得が4分の3免除の所得基準額以下か,
    年金_一部免除判定所得が半額免除の所得基準額以下か,
    年金_一部免除判定所得が4分の1免除の所得基準額以下か,
    年金_令和8年6月以前の月分の一部免除判定所得が半額免除の所得基準額以下か,
    年金_全額免除の所得基準を満たすか,
    年金_納付猶予の所得基準を満たすか,
    年金_一部免除の区分,
    年金_令和8年6月以前の月分の一部免除判定所得,
    年金_学生納付特例の所得基準を満たすか,
    年金_令和8年6月以前の月分の学生納付特例の所得基準を満たすか,
    年金_付加保険料の月額,
    年金_保険料の月額,
    年金_第3号被保険者に当たるか,
)

__all__ = ["VARIABLES"]

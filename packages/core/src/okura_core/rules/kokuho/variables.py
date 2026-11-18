"""規則モジュール kokuho の変数（国民健康保険料〔税〕。年度 F の値を所得の年分 F−1 の situation で計算する）。

- 変数は全部 人物 のエンティティ（evaluate の出力は人ごと）。世帯の値（軽減判定所得・被保険者等の数・軽減の区分）は世帯の全員に同じ値、
  世帯の保険料（税）の額は世帯主（納付義務者：[KHP] §1.1・§1.2）に置き、世帯員は 0。世帯の合算は 人.国保世帯.sum(…)。
- 政令の値（軽減の基準・賦課限度額）は年度ごとのパラメータで、日付のキーは所得の年分の1月1日（年度 F の値は F−1 年1月1日。juminzei と同じ約束：
  parameters/国保/index.yaml）。式は同じ期間のパラメータを引く。
- 式は calc.py の純粋関数を1人（1世帯）ずつ当てる。float は使わない。
"""

from __future__ import annotations

from typing import Any

import numpy as np
from openfisca_core.model_api import YEAR, Variable

from ...country.entities import 人物, 国保世帯
from ...money import INT32_MAX
from .calc import (
    Household,
    household_premium,
    is_earner,
    keigen_income,
    personal_income_levy,
    軽減_2割,
    軽減_5割,
    軽減_7割,
    軽減_なし,
    resident_basic_deduction,
    resident_income,
    rules_from_json,
    shotokuwari_base,
)
from .inputs import kubun_names

_KHP = "docs/public-sources/20261109_round2_kokuho-premium-structure.md"
_PS3 = "docs/public-sources/20261111_impl-research3_kokuho-laws.md"
NO_NHI = "被保険者がいない"


def _年度(period: Any) -> int:
    return period.start.year + 1


def _yen(values: list[int]) -> np.ndarray:
    for v in values:
        if not -INT32_MAX <= v <= INT32_MAX:
            raise OverflowError(f"金額が int32 の範囲の外: {v}")
    return np.array(values, dtype=np.int32)


def _deduction_table(p: Any) -> list[tuple[int | None, int]]:
    return [(int(p.第1段.上限), int(p.第1段.控除額)), (int(p.第2段.上限), int(p.第2段.控除額)), (int(p.第3段.上限), int(p.第3段.控除額))]


# ---------------------------------------------------------------------------
# 入力変数（事実。inputs.build_inputs・段 国保の端数の判定 が書く）
# ---------------------------------------------------------------------------


class 国保_被保険者か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "年度 F に国民健康保険の被保険者である期間があるか（medical_insurance の scheme＝national_health_insurance）"
    reference = [f"{_KHP}#1.1", f"{_KHP}#1.2"]


class 国保_被保険者である月数(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "年度 F の月のうち、月の全部の日で国民健康保険の被保険者である月の数（12 でなければ保険料は月割りの条例が要り未確定）"
    reference = [f"{_KHP}#13"]


class 国保_介護納付金賦課被保険者である月数(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "年度 F の月のうち、月の全部の日で被保険者かつ介護保険法第9条第2号の被保険者（40歳以上65歳未満）である月の数"
    reference = [f"{_KHP}#1.1", f"{_KHP}#13"]


class 国保_十八歳以上被保険者か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "18歳に達する日以後の最初の3月31日の翌日以後である被保険者か（子ども・子育て支援納付金賦課額の18歳以上被保険者均等割）"
    reference = [f"{_KHP}#3.1", f"{_KHP}#9"]


class 国保_特定同一世帯所属者か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "賦課期日に特定同一世帯所属者か（kokuho_event の specified_same_household_member）"
    reference = [f"{_KHP}#6.1", f"{_KHP}#6.2"]


class 国保_未就学児か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "6歳に達する日以後の最初の3月31日以前である被保険者か（年度を通じて）"
    reference = [f"{_KHP}#7"]


class 国保_資産割の基礎の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "年度 F の固定資産税額のうち土地・家屋に係る部分（property_tax の land＋building。世帯の市町村のもの）"
    reference = [f"{_KHP}#3.1", f"{_KHP}#3.2"]


class 国保_非自発的失業者の特例の対象か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "国保令第29条の7の2・地方税法第703条の5の2 の特例対象被保険者等か（離職の日の翌日の属する年度とその翌年度）"
    reference = [f"{_KHP}#4.3"]


class 国保_減免の承認があるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = (
        "世帯に、その年度の保険料（税）の減免の承認（市町村・保険者の個別の処分。国保法第77条・地方税法第717条）があるか"
        "（世帯の全員に同じ値。国保_保険料の額 は減免の前の賦課額）"
    )
    reference = [f"{_KHP}#1.1"]


class 国保_賦課の定め(Variable):
    value_type = str
    entity = 人物
    definition_period = YEAR
    label = "世帯の市町村の賦課の定め（料か税か・区分ごとの方式・率と額・限度額・軽減の割合・未就学児の減額の割合。注入データを JSON にしたもの）"
    reference = [f"{_KHP}#1.1", f"{_KHP}#3.1", f"{_KHP}#5", f"{_KHP}#6.1", f"{_KHP}#7"]


class 国保_年度の政令の基準が登録されているか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "年度 F の政令の基準（軽減の基準額・賦課限度額）が docs で確かめた版に登録されているか（令和9年度は未登録：公表待ち）"
    reference = [f"{_KHP}#13"]


class 国保_保険料の額が端数の定めなしで決まるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "世帯の保険料（税）・所得割額の計算に1円未満の端数や国保税の課税標準の千円未満が生じないか（段 国保の端数の判定 が書く）"
    reference = [f"{_KHP}#10"]


class 国保_保険料の額が月割りと限度額の順序で変わらないか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "月割りの世帯で、賦課限度額を月割りの後の額に当てるか年額に当てるかで保険料の額が変わらないか（段 国保の端数の判定 が書く。変わりうれば分かれ目）"
    reference = [f"{_PS3}#2", f"{_KHP}#5"]


class 国保_月割りの月数(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "所得割・資産割・均等割を月割りする月数（注入データの月割りで「取得した月から喪失した月の前月まで」。月割りしない世帯の被保険者は 12）"
    reference = [f"{_PS3}#2", f"{_KHP}#13"]


class 国保_介護の月割りの月数(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "介護納付金賦課額を月割りする月数（40歳に達した月から65歳に達した月の前月まで。月割りしない世帯は介護納付金賦課被保険者なら 12）"
    reference = [f"{_PS3}#2", f"{_KHP}#13"]


class 国保_産前産後の減額の月数(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "産前産後の減額の期間（出産予定月の前月〔多胎は3月前〕から翌々月まで）のうち年度の被保険者である月の数（注入データの算定があるときだけ。なければ 0）"
    reference = [f"{_PS3}#3", f"{_KHP}#8"]


class 国保_介護の産前産後の減額の月数(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "産前産後の減額の期間のうち、介護納付金賦課被保険者である月の数"
    reference = [f"{_PS3}#3", f"{_KHP}#8"]


class 国保_非自発的失業者の特例で総所得金額から減る額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "非自発的失業者の特例で、給与所得を100分の30にして総所得金額から減る額（所得割の基礎。段 国保の所得の段階 が書く）"
    reference = [f"{_KHP}#4.3"]


class 国保_非自発的失業者の特例で軽減判定の所得から減る額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "非自発的失業者の特例で、軽減の判定の総所得金額（専従者給与を差し引かない）から減る額（段 国保の所得の段階 が書く）"
    reference = [f"{_KHP}#4.3"]


# ---------------------------------------------------------------------------
# 人の区分
# ---------------------------------------------------------------------------


class 国保_被保険者等の数(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "世帯に属する被保険者と特定同一世帯所属者の数（軽減の判定の n。世帯の全員に同じ値）"
    reference = [f"{_KHP}#6.1", f"{_KHP}#6.2"]

    def formula(人, period):
        return 人.国保世帯.sum((人("国保_被保険者か", period) | 人("国保_特定同一世帯所属者か", period)) * 1)


# ---------------------------------------------------------------------------
# 中心の概念
# ---------------------------------------------------------------------------


class 国保_基礎控除後の総所得金額等(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "基礎控除後の総所得金額等（所得割の算定の基礎。住民税の総所得金額等＋分離課税の所得−住民税の基礎控除。雑損失の繰越控除をしない）"
    reference = [f"{_KHP}#4.1", f"{_KHP}#4.2"]

    def formula(人, period, parameters):
        総所得金額等 = 人("住民税_総所得金額等", period)
        合計所得金額 = 人("住民税_合計所得金額", period)
        分離 = 人("住民税_上場株式等に係る分離課税の所得の金額", period)
        退職 = 人("住民税_総所得金額等に含まれる退職所得金額", period)
        雑損失 = 人("住民税_雑損失の繰越控除額", period)
        減る額 = 人("国保_非自発的失業者の特例で総所得金額から減る額", period)
        table = _deduction_table(parameters(period).国保.所得割の基礎.住民税の基礎控除)
        return _yen(
            [
                shotokuwari_base(resident_income(int(t), int(r), int(s), casualty=int(c)), resident_basic_deduction(int(g), table), int(cut))
                for t, g, s, r, c, cut in zip(総所得金額等, 合計所得金額, 分離, 退職, 雑損失, 減る額)
            ]
        )


class 国保_軽減判定に使う所得(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "軽減の判定で合算する1人分の所得（世帯主・被保険者・特定同一世帯所属者だけ。専従者給与を差し引かない総所得金額等＋分離課税の所得）"
    reference = [f"{_KHP}#6.1", f"{_KHP}#6.2"]

    def formula(人, period, parameters):
        数える = 人.has_role(国保世帯.世帯主) | 人("国保_被保険者か", period) | 人("国保_特定同一世帯所属者か", period)
        総所得金額等 = 人("住民税_総所得金額等", period)
        分離 = 人("住民税_上場株式等に係る分離課税の所得の金額", period)
        退職 = 人("住民税_総所得金額等に含まれる退職所得金額", period)
        専従者 = 人("住民税_事業専従者給与等の額", period)
        年金所得 = 人("住民税_公的年金等に係る所得の金額", period)
        年金65 = 人("住民税_65歳以上の者に係る公的年金等控除額の控除を受けたか", period)
        減る額 = 人("国保_非自発的失業者の特例で軽減判定の所得から減る額", period)
        特例 = int(parameters(period).国保.軽減.公的年金等の特例の控除額)
        return _yen(
            [
                keigen_income(
                    resident_income(int(t), int(r), int(s), family_employee=int(f), pension_income=int(y), pension_65=bool(o)),
                    特例,
                    int(cut),
                )
                if c
                else 0
                for t, s, r, f, y, o, c, cut in zip(総所得金額等, 分離, 退職, 専従者, 年金所得, 年金65, 数える, 減る額)
            ]
        )


class 国保_軽減の判定で数える給与所得者等か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "世帯主・被保険者・特定同一世帯所属者のうち給与所得者等か（給与等の収入金額55万円超、又は公的年金等の収入金額60万円超〔65歳以上は125万円超〕）"
    reference = [f"{_KHP}#6.1", f"{_KHP}#6.2"]

    def formula(人, period, parameters):
        数える = 人.has_role(国保世帯.世帯主) | 人("国保_被保険者か", period) | 人("国保_特定同一世帯所属者か", period)
        p = parameters(period).国保.軽減.給与所得者等の基準
        給与 = 人("住民税_給与等の収入金額", period)
        年金 = 人("住民税_公的年金等の収入金額", period)
        年金65 = 人("住民税_65歳以上の者に係る公的年金等控除額の控除を受けたか", period)
        rules = {
            "kyuyo_min": int(p.給与等の収入金額),
            "pension_min_under65": int(p.公的年金等の収入金額_65歳未満),
            "pension_min_65": int(p.公的年金等の収入金額_65歳以上),
        }
        earner = np.array([is_earner(int(k), int(n), bool(o), **rules) for k, n, o in zip(給与, 年金, 年金65)], dtype=bool)
        return 数える & earner


class 国保_軽減判定所得(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "低所得者の軽減（7割・5割・2割）の判定に使う世帯の所得の合算額（世帯の全員に同じ値）"
    reference = [f"{_KHP}#6.1", f"{_KHP}#6.2"]

    def formula(人, period):
        return 人.国保世帯.sum(人("国保_軽減判定に使う所得", period))


# ---------------------------------------------------------------------------
# 軽減の判定
# ---------------------------------------------------------------------------


class 国保_軽減の区分(Variable):
    value_type = str
    entity = 人物
    definition_period = YEAR
    label = "被保険者均等割・世帯別平等割の軽減の区分（7割・5割・2割・なしの段階。実際の割合は市町村の選ぶ組で決まる）"
    reference = [f"{_KHP}#6.1", f"{_KHP}#6.2"]

    def formula(人, period, parameters):
        人数 = 人("国保_被保険者等の数", period)
        # 年度の政令の版が未登録なら未確定（公表待ち）。読むことで依存する値へ伝える
        人("国保_年度の政令の基準が登録されているか", period)
        # 各段の所得基準（合算額が基準額を「超えない」：calc.keigen_tier と同じ順。基準額は 7割 ≦ 5割 ≦ 2割）
        七 = 人("国保_7割軽減の所得基準を満たすか", period)
        五 = 人("国保_5割軽減の所得基準を満たすか", period)
        二 = 人("国保_2割軽減の所得基準を満たすか", period)
        return np.array(
            [
                NO_NHI if n <= 0 else 軽減_7割 if a else 軽減_5割 if b else 軽減_2割 if c else 軽減_なし
                for n, a, b, c in zip(人数, 七, 五, 二)
            ],
            dtype=object,
        )


def _seven(k: Any, p: Any) -> np.ndarray:
    """7割の基準額：43万円＋10万円×(k−1)（k＝世帯の給与所得者等の数。k が2以上のとき加算。[KHP] §6.1。calc.keigen_thresholds と同じ）。"""
    return int(p.基準額) + int(p.給与所得者等の加算額) * np.maximum(0, np.asarray(k, dtype=np.int64) - 1)


class 国保_7割軽減の基準額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "7割軽減の所得の基準額（43万円＋10万円×(給与所得者等の数−1)。この額を超えない世帯が該当。世帯の全員に同じ値。境目の説明の基準）"
    reference = [f"{_KHP}#6.1", f"{_KHP}#6.2"]

    def formula(人, period, parameters):
        # 年度の政令の版が未登録なら未確定（公表待ち）。読むことで依存する値へ伝える
        人("国保_年度の政令の基準が登録されているか", period)
        k = 人.国保世帯.sum(人("国保_軽減の判定で数える給与所得者等か", period) * 1)
        return _yen([int(x) for x in _seven(k, parameters(period).国保.軽減)])


class 国保_5割軽減の基準額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "5割軽減の所得の基準額（7割の基準額＋被保険者等の数×a。この額を超えない世帯が該当。世帯の全員に同じ値。境目の説明の基準）"
    reference = [f"{_KHP}#6.1", f"{_KHP}#6.2"]

    def formula(人, period, parameters):
        人("国保_年度の政令の基準が登録されているか", period)
        k = 人.国保世帯.sum(人("国保_軽減の判定で数える給与所得者等か", period) * 1)
        p = parameters(period).国保.軽減
        n = np.asarray(人("国保_被保険者等の数", period), dtype=np.int64)
        return _yen([int(x) for x in _seven(k, p) + n * int(p.五割の被保険者等1人あたりの額)])


class 国保_2割軽減の基準額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "2割軽減の所得の基準額（7割の基準額＋被保険者等の数×b。この額を超えない世帯が該当。世帯の全員に同じ値。境目の説明の基準）"
    reference = [f"{_KHP}#6.1", f"{_KHP}#6.2"]

    def formula(人, period, parameters):
        人("国保_年度の政令の基準が登録されているか", period)
        k = 人.国保世帯.sum(人("国保_軽減の判定で数える給与所得者等か", period) * 1)
        p = parameters(period).国保.軽減
        n = np.asarray(人("国保_被保険者等の数", period), dtype=np.int64)
        return _yen([int(x) for x in _seven(k, p) + n * int(p.二割の被保険者等1人あたりの額)])


class 国保_7割軽減の所得基準を満たすか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "軽減判定所得が7割軽減の基準額を超えないか（境目の説明の判定。被保険者がいるかは含まない）"
    reference = [f"{_KHP}#6.1", f"{_KHP}#6.2"]

    def formula(人, period):
        return 人("国保_軽減判定所得", period) <= 人("国保_7割軽減の基準額", period)


class 国保_5割軽減の所得基準を満たすか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "軽減判定所得が5割軽減の基準額を超えないか（境目の説明の判定。被保険者がいるかは含まない）"
    reference = [f"{_KHP}#6.1", f"{_KHP}#6.2"]

    def formula(人, period):
        return 人("国保_軽減判定所得", period) <= 人("国保_5割軽減の基準額", period)


class 国保_2割軽減の所得基準を満たすか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "軽減判定所得が2割軽減の基準額を超えないか（境目の説明の判定。被保険者がいるかは含まない）"
    reference = [f"{_KHP}#6.1", f"{_KHP}#6.2"]

    def formula(人, period):
        return 人("国保_軽減判定所得", period) <= 人("国保_2割軽減の基準額", period)


# ---------------------------------------------------------------------------
# 税額（所得割額・保険料の額）
# ---------------------------------------------------------------------------


class 国保_所得割額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "その人の所得割額（区分ごとの所得割の合計。介護納付金賦課額は介護納付金賦課被保険者だけ）"
    reference = [f"{_KHP}#3.1", f"{_KHP}#3.2"]

    def formula(人, period):
        基礎 = 人("国保_基礎控除後の総所得金額等", period)
        被保険者 = 人("国保_被保険者か", period)
        介護 = 人("国保_介護納付金賦課被保険者である月数", period)
        月数 = 人("国保_月割りの月数", period)
        介護の月数 = 人("国保_介護の月割りの月数", period)
        産前産後 = 人("国保_産前産後の減額の月数", period)
        介護の産前産後 = 人("国保_介護の産前産後の減額の月数", period)
        定め = 人("国保_賦課の定め", period)
        人("国保_保険料の額が端数の定めなしで決まるか", period)
        names = kubun_names(_年度(period))
        out = []
        for b, ins, k, m, km, bm, bkm, text in zip(基礎, 被保険者, 介護, 月数, 介護の月数, 産前産後, 介護の産前産後, 定め):
            r = rules_from_json(str(text))
            if not ins or r is None or not set(names) <= set(r.kubun):
                out.append(0)
                continue
            weight = int(m) * r.month_ratio - int(bm) * r.birth_ratio
            kaigo_weight = int(km) * r.month_ratio - int(bkm) * r.birth_ratio
            out.append(int(personal_income_levy(int(b) * weight, int(k) > 0, r, names, int(b) * kaigo_weight) // 1))
        return _yen(out)


class 国保_保険料の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "世帯主（納付義務者）に課される世帯の国民健康保険料（税）の年額（区分ごとの賦課額の合計。世帯員は 0）"
    reference = [f"{_KHP}#2.1", f"{_KHP}#5", f"{_KHP}#6.1", f"{_KHP}#7", f"{_KHP}#9", f"{_KHP}#10", f"{_PS3}#2", f"{_PS3}#3", f"{_PS3}#4"]

    def formula(人, period):
        # 世帯の合算は 人.国保世帯.sum(…) の引数の中で人の値を引く（人をまたぐ依存を構造の検査が読めるように）。
        # 月割り・産前産後の減額の重み（月数×1月分の割合）は、世帯の合計を月数で重みづけしてから割合を掛ける（calc.Household の説明）。
        # 所得割の基礎×月数は int32 を超えうるので int64 にしてから掛ける
        所得割の月 = 人.国保世帯.sum(
            人("国保_基礎控除後の総所得金額等", period).astype(np.int64) * 人("国保_月割りの月数", period) * 人("国保_被保険者か", period)
        )
        所得割の産前産後 = 人.国保世帯.sum(
            人("国保_基礎控除後の総所得金額等", period).astype(np.int64) * 人("国保_産前産後の減額の月数", period) * 人("国保_被保険者か", period)
        )
        介護の所得割の月 = 人.国保世帯.sum(
            人("国保_基礎控除後の総所得金額等", period).astype(np.int64) * 人("国保_介護の月割りの月数", period) * 人("国保_被保険者か", period)
        )
        介護の所得割の産前産後 = 人.国保世帯.sum(
            人("国保_基礎控除後の総所得金額等", period).astype(np.int64) * 人("国保_介護の産前産後の減額の月数", period) * 人("国保_被保険者か", period)
        )
        資産割の月 = 人.国保世帯.sum(人("国保_資産割の基礎の額", period).astype(np.int64) * 人("国保_月割りの月数", period) * 人("国保_被保険者か", period))
        介護の資産割の月 = 人.国保世帯.sum(
            人("国保_資産割の基礎の額", period).astype(np.int64) * 人("国保_介護の月割りの月数", period) * 人("国保_被保険者か", period)
        )
        被保険者の月 = 人.国保世帯.sum(人("国保_月割りの月数", period) * 人("国保_被保険者か", period))
        被保険者の産前産後 = 人.国保世帯.sum(人("国保_産前産後の減額の月数", period) * 人("国保_被保険者か", period))
        介護の月 = 人.国保世帯.sum(人("国保_介護の月割りの月数", period) * 人("国保_被保険者か", period))
        介護の産前産後 = 人.国保世帯.sum(人("国保_介護の産前産後の減額の月数", period) * 人("国保_被保険者か", period))
        十八歳以上の月 = 人.国保世帯.sum(人("国保_月割りの月数", period) * 人("国保_十八歳以上被保険者か", period))
        十八歳以上の産前産後 = 人.国保世帯.sum(人("国保_産前産後の減額の月数", period) * 人("国保_十八歳以上被保険者か", period))
        未就学児の月 = 人.国保世帯.sum(人("国保_月割りの月数", period) * 人("国保_未就学児か", period))
        区分 = 人("国保_軽減の区分", period)
        定め = 人("国保_賦課の定め", period)
        人("国保_保険料の額が端数の定めなしで決まるか", period)
        人("国保_保険料の額が月割りと限度額の順序で変わらないか", period)
        人("国保_年度の政令の基準が登録されているか", period)
        世帯主 = 人.has_role(国保世帯.世帯主)
        names = kubun_names(_年度(period))
        out = []
        rows = zip(
            世帯主, 定め, 区分, 所得割の月, 所得割の産前産後, 介護の所得割の月, 介護の所得割の産前産後, 資産割の月, 介護の資産割の月,
            被保険者の月, 被保険者の産前産後, 介護の月, 介護の産前産後, 十八歳以上の月, 十八歳以上の産前産後, 未就学児の月,
        )  # fmt: skip
        for head, text, tier, b, bb, bk, bkb, a, ak, n, nb, nk, nkb, na, nab, npre in rows:
            r = rules_from_json(str(text))
            if not head or r is None or _i(n) == 0 or not set(names) <= set(r.kubun):
                out.append(0)
                continue
            m, birth = r.month_ratio, r.birth_ratio
            h = Household(
                base=_i(b) * m - _i(bb) * birth,
                base_kaigo=_i(bk) * m - _i(bkb) * birth,
                asset=_i(a) * m,
                asset_kaigo=_i(ak) * m,
                insured=_i(n) * m - _i(nb) * birth,
                kaigo=_i(nk) * m - _i(nkb) * birth,
                adults=_i(na) * m - _i(nab) * birth,
                preschool=_i(npre) * m,
                household=r.household_months * m,
                household_kaigo=r.household_kaigo_months * m,
            )
            out.append(household_premium(h, str(tier), r, names).total)
        return _yen(out)


def _i(x: Any) -> int:
    """世帯の合計（OpenFisca の sum は float64 を返しうる。値は整数）を整数にする。"""
    return int(round(float(x)))


VARIABLES: tuple[type, ...] = (
    国保_被保険者か,
    国保_被保険者である月数,
    国保_介護納付金賦課被保険者である月数,
    国保_十八歳以上被保険者か,
    国保_特定同一世帯所属者か,
    国保_未就学児か,
    国保_資産割の基礎の額,
    国保_非自発的失業者の特例の対象か,
    国保_減免の承認があるか,
    国保_賦課の定め,
    国保_年度の政令の基準が登録されているか,
    国保_保険料の額が端数の定めなしで決まるか,
    国保_保険料の額が月割りと限度額の順序で変わらないか,
    国保_月割りの月数,
    国保_介護の月割りの月数,
    国保_産前産後の減額の月数,
    国保_介護の産前産後の減額の月数,
    国保_非自発的失業者の特例で総所得金額から減る額,
    国保_非自発的失業者の特例で軽減判定の所得から減る額,
    国保_被保険者等の数,
    国保_基礎控除後の総所得金額等,
    国保_軽減判定に使う所得,
    国保_軽減の判定で数える給与所得者等か,
    国保_軽減判定所得,
    国保_7割軽減の基準額,
    国保_5割軽減の基準額,
    国保_2割軽減の基準額,
    国保_7割軽減の所得基準を満たすか,
    国保_5割軽減の所得基準を満たすか,
    国保_2割軽減の所得基準を満たすか,
    国保_軽減の区分,
    国保_所得割額,
    国保_保険料の額,
)

__all__ = ["NO_NHI", "VARIABLES"]

"""規則モジュール other_deductions の式と境目（令和7年分・令和8年分）。テストのデータは金額だけの架空の人（個人の情報を使わない）。

期待値の出典はコメントの docs の節。OpenFisca の式を単独で確かめる：まだない上流（総所得金額等・年齢23歳未満の扶養親族を有するか）は入力として与える。
"""

from __future__ import annotations

import unittest
from fractions import Fraction
from typing import Any

from openfisca_core.simulation_builder import SimulationBuilder

from okura_core.rounding import FUNCTIONS, ceil_yen
from okura_core.rules.other_deductions.calc import (
    LifeRules,
    donation_deduction,
    life_insurance_deduction,
    medical_deduction,
    self_medication_deduction,
    staged,
    steps_from,
)

from .support import system

YEARS = (2025, 2026)
MEDICAL_ROUND = "所得税_医療費控除の足切りの端数"
DONATION_ROUND = "所得税_寄附金控除の上限の端数"


def calc(year: int, variable: str, **inputs: Any) -> int:
    """1人の架空の人の入力を与えて、変数の値を返す。"""
    person = {k: {str(year): v} for k, v in inputs.items()}
    sim = SimulationBuilder().build_from_entities(system(), {"人物一覧": {"p": person}})
    return sim.calculate(variable, str(year))[0].item()


def medical(year: int, expense: int, income: int, rounding: str = "floor", chosen: bool = False) -> int:
    return calc(
        year,
        "所得税_医療費控除の額",
        **{
            "所得税_補塡後の医療費の額": expense,
            "所得税_総所得金額等": income,
            MEDICAL_ROUND: rounding,
            "所得税_セルフメディケーション税制の選択": chosen,
        },
    )


def life(year: int, *, new: int = 0, old: int = 0, care: int = 0, new_a: int = 0, old_a: int = 0, regime: str = "both", u23: bool = False) -> int:
    return calc(
        year,
        "所得税_生命保険料控除の額",
        **{
            "所得税_新生命保険料の額": new,
            "所得税_旧生命保険料の額": old,
            "所得税_介護医療保険料の額": care,
            "所得税_新個人年金保険料の額": new_a,
            "所得税_旧個人年金保険料の額": old_a,
            "所得税_生命保険料の新旧の選択": regime,
            "所得税_年齢23歳未満の扶養親族を有するか": u23,
        },
    )


def quake(year: int, q: int = 0, old_long: int = 0) -> int:
    return calc(year, "所得税_地震保険料控除の額", **{"所得税_地震保険料の額": q, "所得税_旧長期損害保険料の額": old_long})


def donation(year: int, total: int, income: int, rounding: str = "floor") -> int:
    return calc(
        year,
        "所得税_寄附金控除の額",
        **{"所得税_特定寄附金の額": total, "所得税_総所得金額等": income, DONATION_ROUND: rounding},
    )


class TestMedicalDeduction(unittest.TestCase):
    """医療費控除（所法73①）：docs/public-sources/20261109_impl-prep_iryohi-law-text.md §1、様式の A〜G は …iryohi-nta-mhlw.md §2.2。"""

    def test_examples_s3(self) -> None:
        # docs/measurements/20261109_impl-prep_iryohi-verification.md §5.1 の S3-1（父 C 240,000・D 5,000,000 → G 140,000、母 C 90,000・D 1,150,000 → G 32,500）
        for y in YEARS:
            with self.subTest(year=y):
                self.assertEqual(medical(y, 240_000, 5_000_000), 140_000)
                self.assertEqual(medical(y, 90_000, 1_150_000), 32_500)

    def test_threshold_boundaries(self) -> None:
        # 足切りは 総所得金額等×5% と10万円の低い方（§1）：総所得金額等 200万円で5%＝10万円、ちょうど境目。300,000円の医療費
        for y in YEARS:
            with self.subTest(year=y):
                self.assertEqual(medical(y, 300_000, 2_000_000), 200_000)  # 5%＝100,000
                self.assertEqual(medical(y, 300_000, 2_000_020), 200_000)  # 5%＝100,001 → 10万円の上限
                self.assertEqual(medical(y, 300_000, 1_999_980), 200_001)  # 5%＝99,999
                self.assertEqual(medical(y, 100_000, 2_000_000), 0)  # 足切りちょうど：超える部分がない
                self.assertEqual(medical(y, 100_001, 2_000_000), 1)

    def test_cap_two_million(self) -> None:
        # 控除の上限 200万円（§1）
        for y in YEARS:
            with self.subTest(year=y):
                self.assertEqual(medical(y, 2_100_000, 5_000_000), 2_000_000)  # 超える部分＝200万円ちょうど
                self.assertEqual(medical(y, 2_100_001, 5_000_000), 2_000_000)  # 超える部分＝2,000,001 → 上限
                self.assertEqual(medical(y, 2_099_999, 5_000_000), 1_999_999)

    def test_negative_income_means_zero_threshold(self) -> None:
        # 様式の E 欄「赤字のときは0円」（…iryohi-nta-mhlw.md §2.2）
        self.assertEqual(medical_deduction(50_000, -100, FUNCTIONS["floor"], rate=Fraction(5, 100), threshold_cap=100_000, cap=2_000_000), 50_000)

    def test_unfounded_rounding_candidates(self) -> None:
        # 5%の円未満の端数は根拠なし（…iryohi-law-text.md §6）。候補ごとの値は docs/measurements/20261109_impl-prep_iryohi-verification.md §5.1 の S3-2
        cases = {
            1_150_000: (32_500, 32_500, 32_500),  # (a) 端数なし
            1_150_001: (32_500, 32_500, 32_499),  # (b) 57,500.05
            1_150_019: (32_500, 32_499, 32_499),  # (c) 57,500.95
        }
        for y in YEARS:
            for income, (floor, half_up, ceil) in cases.items():
                with self.subTest(year=y, income=income):
                    self.assertEqual(medical(y, 90_000, income, "floor"), floor)
                    self.assertEqual(medical(y, 90_000, income, "half_up"), half_up)
                    self.assertEqual(medical(y, 90_000, income, "ceil"), ceil)

    def test_choosing_self_medication_makes_regular_zero(self) -> None:
        # 選択適用で併用できない（TA1131：…iryohi-nta-mhlw.md §6.1）
        self.assertEqual(medical(2026, 240_000, 5_000_000, chosen=True), 0)

    def test_no_expense_does_not_need_total_income(self) -> None:
        # 医療費が全員0なら総所得金額等によらず0（総所得金額等を引かない。variables.py の説明）
        sim = SimulationBuilder().build_from_entities(system(), {"人物一覧": {"p": {MEDICAL_ROUND: {"2026": "floor"}}}})
        sim.trace = True
        sim.calculate("所得税_医療費控除の額", "2026")
        names = {n.name for n in sim.tracer.browse_trace()}
        self.assertNotIn("所得税_総所得金額等", names)


class TestSelfMedication(unittest.TestCase):
    """措法41の17① の読替え（1万2千円・8万8千円）：…iryohi-law-text.md §4.1。様式の C・D は …iryohi-nta-mhlw.md §5.4。"""

    def _v(self, year: int, purchase: int, chosen: bool = True) -> int:
        return calc(
            year,
            "所得税_セルフメディケーション税制による医療費控除の額",
            **{"所得税_特定一般用医薬品等購入費の額": purchase, "所得税_セルフメディケーション税制の選択": chosen},
        )

    def test_boundaries(self) -> None:
        for y in YEARS:
            with self.subTest(year=y):
                self.assertEqual(self._v(y, 12_000), 0)  # ちょうど足切り
                self.assertEqual(self._v(y, 12_001), 1)
                self.assertEqual(self._v(y, 30_000), 18_000)  # S3-5（実測 …iryohi-verification.md §5.1）
                self.assertEqual(self._v(y, 100_000), 88_000)  # ちょうど上限
                self.assertEqual(self._v(y, 100_001), 88_000)

    def test_not_chosen_is_zero(self) -> None:
        self.assertEqual(self._v(2026, 30_000, chosen=False), 0)

    def test_pure_function(self) -> None:
        self.assertEqual(self_medication_deduction(30_000, floor=12_000, cap=88_000), 18_000)


class TestLifeInsurance(unittest.TestCase):
    """生命保険料控除（所法76）：docs/public-sources/20261109_round2_hoken-kifu-laws.md §2.1、検算は docs/measurements/20261109_round2_hoken-kifu-formula-checks.md §1。"""

    def test_boundaries_new_formula(self) -> None:
        # 実測 §1：新の境目 2万・4万・8万円で 20,000／30,000／40,000、次の1円で値が飛ばない
        for y in YEARS:
            for x, expected in ((20_000, 20_000), (40_000, 30_000), (80_000, 40_000), (80_001, 40_000)):
                with self.subTest(year=y, x=x):
                    self.assertEqual(life(y, new=x), expected)

    def test_boundaries_old_formula(self) -> None:
        # 実測 §1：旧の境目 2万5千・5万・10万円で 25,000／37,500／50,000
        for y in YEARS:
            for x, expected in ((25_000, 25_000), (50_000, 37_500), (100_000, 50_000), (100_001, 50_000)):
                with self.subTest(year=y, x=x):
                    self.assertEqual(life(y, old=x), expected)

    def test_rounding_up_fraction(self) -> None:
        # 実測 §2：新 20,001 円の式の値は 40001/2 円。国税庁「年末調整のしかた」p.24 注2 は切上げ（…hoken-kifu-nta-soumu.md §1.6）
        self.assertEqual(life(2025, new=20_001), 20_001)
        self.assertEqual(life(2025, new=40_003), 30_001)  # 120003/4 円（実測 §2）を切上げ

    def test_rounding_is_applied_per_section(self) -> None:
        # 区分ごとの式の値に当てる（法令の読み：仮説 H4。合計に当てると 50,001）
        self.assertEqual(life(2025, new=30_001, new_a=30_001), 25_001 + 25_001)

    def test_nta_example_05_74(self) -> None:
        # 質疑応答事例 05/74（新4万円・旧10万円）。新のみ 30,000、旧のみ 50,000、両方 40,000（実測 §1）
        for y in YEARS:
            with self.subTest(year=y):
                self.assertEqual(life(y, new=40_000, old=100_000, regime="new_only"), 30_000)
                self.assertEqual(life(y, new=40_000, old=100_000, regime="old_only"), 50_000)
                self.assertEqual(life(y, new=40_000, old=100_000, regime="both"), 40_000)

    def test_nta_example_05_76_total_cap(self) -> None:
        # 質疑応答事例 05/76（一般5万・介護医療2万5千・個人年金5万）→ 合計 125,000 → 12万円（実測 §1）
        # 一般と個人年金は旧の式で5万円：旧 10万円で 50,000、介護医療は新の式で 25,000 になる支払（4万円超 30,000 の手前）
        for y in YEARS:
            with self.subTest(year=y):
                self.assertEqual(life(y, old=100_000, care=30_000, old_a=100_000), 120_000)

    def test_cap_boundaries_total(self) -> None:
        # 第4項の合計の上限 12万円（§2.1）：一般4万＋介護4万＋年金4万＝12万円ちょうど
        for y in YEARS:
            with self.subTest(year=y):
                self.assertEqual(life(y, new=80_000, care=80_000, new_a=80_000), 120_000)

    def test_special_applies_only_from_2026(self) -> None:
        # 措法41の15の5（令和8年分・令和9年分。§2.3）：令和7年分には当たらない
        self.assertEqual(life(2025, new=30_000, u23=True), 25_000)  # 通常の式
        # 実測 §1：特例の境目 3万・6万・12万円で 30,000／45,000／60,000
        for x, expected in ((30_000, 30_000), (60_000, 45_000), (120_000, 60_000), (120_001, 60_000)):
            with self.subTest(x=x):
                self.assertEqual(life(2026, new=x, u23=True), expected)

    def test_special_formula_rounding(self) -> None:
        # 特例の第2段の端数も切上げ：30,001 → 30,000＋1/2＝30,000.5 → 30,001（…hoken-kifu-nta-soumu.md §1.6 の計算式Ⅱ）
        self.assertEqual(life(2026, new=30_001, u23=True), 30_001)

    def test_special_with_both_new_and_old(self) -> None:
        # 実測 §1：新4万・旧10万で特例：新のみ 35,000、旧のみ 50,000、両方 min(85,000, 60,000)＝60,000
        self.assertEqual(life(2026, new=40_000, old=100_000, regime="new_only", u23=True), 35_000)
        self.assertEqual(life(2026, new=40_000, old=100_000, regime="old_only", u23=True), 50_000)
        self.assertEqual(life(2026, new=40_000, old=100_000, regime="both", u23=True), 60_000)

    def test_special_does_not_change_other_sections(self) -> None:
        # 読替えは第1項第1号・第3号だけ（§2.3）：介護医療・個人年金は通常の式
        self.assertEqual(life(2026, care=30_000, u23=True), life(2025, care=30_000))
        self.assertEqual(life(2026, new_a=30_000, u23=True), life(2025, new_a=30_000))

    def test_steps_from_parameters(self) -> None:
        p = system().get_parameters_at_instant("2026-01-01").所得税.生命保険料控除
        self.assertEqual(ceil_yen(staged(30_000, steps_from(p.新生命保険料))), 25_000)
        self.assertEqual(ceil_yen(staged(30_000, steps_from(p.措法第41条の15の5.新生命保険料))), 30_000)

    def test_pure_function_regime_is_checked(self) -> None:
        step = steps_from(system().get_parameters_at_instant("2026-01-01").所得税.生命保険料控除.新生命保険料)
        rules = LifeRules(step, step, step, step, step, 40_000, 40_000, 120_000)
        with self.assertRaises(ValueError):
            life_insurance_deduction(1, 0, 0, 0, 0, "unknown", rules, ceil_yen)


class TestEarthquake(unittest.TestCase):
    """地震保険料控除（所法77）・旧長期（平18附則10）：…hoken-kifu-laws.md §3、実測 …formula-checks.md §3。"""

    def test_quake_cap(self) -> None:
        for y in YEARS:
            with self.subTest(year=y):
                self.assertEqual(quake(y, 50_000), 50_000)
                self.assertEqual(quake(y, 50_001), 50_000)

    def test_old_long_term_boundaries(self) -> None:
        # 附則10②二（実測 §3）：1万円以下 全額、2万円以下 1万円＋(x−1万円)/2、2万円超 1万5千円
        for y in YEARS:
            for x, expected in ((10_000, 10_000), (10_001, 10_001), (20_000, 15_000), (20_001, 15_000)):
                with self.subTest(year=y, x=x):
                    self.assertEqual(quake(y, 0, x), expected)

    def test_nta_example_05_68_each_alone(self) -> None:
        # 質疑応答事例 05/68（一の契約で地震保険料 1万円と旧長期損害保険料 1万7千円）：地震だけ 10,000、旧長期だけ 13,500（実測 §3）
        self.assertEqual(quake(2026, 10_000, 0), 10_000)
        self.assertEqual(quake(2026, 0, 17_000), 13_500)

    def test_both_total_cap(self) -> None:
        # 附則10②三：両方あるときの合計の上限 5万円（…hoken-kifu-laws.md §3）
        self.assertEqual(quake(2026, 40_000, 20_000), 50_000)
        self.assertEqual(quake(2026, 30_000, 20_000), 45_000)


class TestDonation(unittest.TestCase):
    """寄附金控除（所法78①）：…hoken-kifu-laws.md §4、式からの値は 実測 …formula-checks.md §5。"""

    def test_examples(self) -> None:
        for y in YEARS:
            with self.subTest(year=y):
                self.assertEqual(donation(y, 30_000, 3_000_000), 28_000)
                self.assertEqual(donation(y, 1_500_000, 3_000_000), 1_198_000)  # 40% の 120万円が上限
                self.assertEqual(donation(y, 2_000, 3_000_000), 0)
                self.assertEqual(donation(y, 2_001, 3_000_000), 1)

    def test_forty_percent_boundary(self) -> None:
        for y in YEARS:
            with self.subTest(year=y):
                self.assertEqual(donation(y, 1_200_000, 3_000_000), 1_198_000)  # ちょうど上限
                self.assertEqual(donation(y, 1_200_001, 3_000_000), 1_198_000)
                self.assertEqual(donation(y, 1_199_999, 3_000_000), 1_197_999)

    def test_unfounded_rounding(self) -> None:
        # 百分の四十の1円未満の定めは docs にない（§4）：総所得金額等 1,000,001 円の 40%＝400,000.4 円
        self.assertEqual(donation(2026, 500_000, 1_000_001, "floor"), 398_000)
        self.assertEqual(donation(2026, 500_000, 1_000_001, "ceil"), 398_001)
        self.assertEqual(donation(2026, 500_000, 1_000_001, "half_up"), 398_000)

    def test_small_donation_does_not_need_total_income(self) -> None:
        sim = SimulationBuilder().build_from_entities(
            system(), {"人物一覧": {"p": {"所得税_特定寄附金の額": {"2026": 2_000}, DONATION_ROUND: {"2026": "floor"}}}}
        )
        sim.trace = True
        self.assertEqual(sim.calculate("所得税_寄附金控除の額", "2026")[0], 0)
        self.assertNotIn("所得税_総所得金額等", {n.name for n in sim.tracer.browse_trace()})

    def test_pure_function_negative_income(self) -> None:
        self.assertEqual(donation_deduction(10_000, -5, FUNCTIONS["floor"], rate=Fraction(40, 100), floor=2_000), 0)


class TestFullDeductions(unittest.TestCase):
    """全額控除の2つ（上限・端数なし）。"""

    def test_social_insurance(self) -> None:
        for y in YEARS:
            with self.subTest(year=y):
                self.assertEqual(calc(y, "所得税_社会保険料控除の額", **{"所得税_支払った社会保険料の額": 123_456}), 123_456)

    def test_mutual_aid(self) -> None:
        for y in YEARS:
            with self.subTest(year=y):
                self.assertEqual(calc(y, "所得税_小規模企業共済等掛金控除の額", **{"所得税_支払った小規模企業共済等掛金の額": 276_000}), 276_000)


if __name__ == "__main__":
    unittest.main()

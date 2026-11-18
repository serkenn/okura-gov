"""income_kinds の純粋関数の境目・計算例のテスト（D15 ②）。期待値のコメントに出典の docs の節。

パラメータは TaxBenefitSystem の木から年分ごとに読む（値を書き写さない）。テストのデータは架空。
"""

from __future__ import annotations

import datetime as dt
import unittest
from fractions import Fraction

from okura_core.rounding import ceil_yen, floor_yen, half_up_yen
from okura_core.rules.income_kinds.calc import (
    FILING_ETAX,
    FILING_OTHER,
    FILING_PAPER,
    RETIRE_GENERAL,
    RETIRE_OFFICER,
    RETIRE_SHORT,
    blue_deduction,
    blue_rules,
    home_worker_expenses,
    pension_deduction,
    pension_deduction_yen,
    pension_income,
    pension_rules,
    retirement_deduction,
    retirement_income,
    retirement_rules,
    windfall_income,
)
from okura_core.rules.income_kinds.inputs import OFFICER_SERVICE_LIMIT, SHORT_SERVICE_LIMIT, service_years

from ...support import system

YEARS = ("2025-01-01", "2026-01-01")


def params(at: str):
    return system().parameters(at)


class TestPensionDeduction(unittest.TestCase):
    """公的年金等控除額：所法35④・措法41の15の3（nenkin §2.1・§2.2）。速算表は nenkin §2.3（TA No.1600）。"""

    def income(self, a: int, other: int, age: int, at: str, f=floor_yen) -> int:
        r = pension_rules(params(at))
        return pension_income(a, pension_deduction(a, other, age, r), f)

    def test_ta_example(self) -> None:
        # nenkin §2.3 の計算例：65歳以上、公的年金等に係る雑所得以外の合計所得金額 500万円、収入 350万円 → 3,500,000×75%−275,000＝2,350,000
        for at in YEARS:
            self.assertEqual(self.income(3_500_000, 5_000_000, 70, at), 2_350_000)

    def test_quick_table_under_65(self) -> None:
        # nenkin §2.3 の速算表（1,000万円以下、65歳未満）。(収入, 雑所得)
        cases = [
            (600_000, 0),  # 60万円以下：0
            (600_001, 1),  # 60万円超 130万円未満：A−60万円
            (1_299_999, 699_999),
            (1_300_000, 700_000),  # 130万円以上 410万円未満：A×0.75−27.5万円
            (4_099_996, 2_799_997),
            (4_100_000, 2_800_000),  # 410万円以上 770万円未満：A×0.85−68.5万円
            (7_700_000, 5_860_000),  # 770万円以上 1,000万円未満：A×0.95−145.5万円
            (9_999_980, 8_044_981),
            (10_000_000, 8_045_000),  # 1,000万円以上：A−195.5万円
            (12_345_678, 10_390_678),
        ]
        for at in YEARS:
            for a, want in cases:
                with self.subTest(at=at, a=a):
                    self.assertEqual(self.income(a, 0, 64, at), want)

    def test_quick_table_65_or_older(self) -> None:
        # nenkin §2.3 の速算表（1,000万円以下、65歳以上）
        cases = [(1_100_000, 0), (1_100_001, 1), (3_299_996, 2_199_996), (3_300_000, 2_200_000), (4_100_000, 2_800_000)]
        for at in YEARS:
            for a, want in cases:
                with self.subTest(at=at, a=a):
                    self.assertEqual(self.income(a, 0, 65, at), want)

    def test_age_boundary(self) -> None:
        # 措法41の15の3①：65歳以上で最低額 110万円（nenkin §2.2）。64歳は60万円（§2.1）
        self.assertEqual(self.income(1_000_000, 0, 64, "2026-01-01"), 400_000)
        self.assertEqual(self.income(1_000_000, 0, 65, "2026-01-01"), 0)

    def test_other_income_brackets(self) -> None:
        # nenkin §2.3：1,000万円超 2,000万円以下は 0.75−17.5万円・2,000万円超は 0.75−7.5万円（最低額 50万／40万）
        a = 2_000_000
        for other, want in (
            (10_000_000, 1_225_000),  # 第1号：×0.75−27.5万円（1,000万円以下）
            (10_000_001, 1_325_000),  # 第2号：×0.75−17.5万円
            (20_000_000, 1_325_000),
            (20_000_001, 1_425_000),  # 第3号：×0.75−7.5万円
        ):
            self.assertEqual(self.income(a, other, 40, "2026-01-01"), want)
        # 最低額（第2号 50万円・第3号 40万円。65歳以上は 100万円・90万円）
        self.assertEqual(self.income(500_001, 10_000_001, 40, "2026-01-01"), 1)
        self.assertEqual(self.income(400_001, 20_000_001, 40, "2026-01-01"), 1)
        self.assertEqual(self.income(1_000_001, 10_000_001, 65, "2026-01-01"), 1)
        self.assertEqual(self.income(900_001, 20_000_001, 65, "2026-01-01"), 1)

    def test_fraction_candidates(self) -> None:
        # 1,300,001×0.75−275,000＝700,000.75：端数の定めがない（nenkin §10 の1）→ 候補で幅
        a = 1_300_001
        r = pension_rules(params("2026-01-01"))
        d = pension_deduction(a, 0, 40, r)
        self.assertEqual(pension_income(a, d, floor_yen), 700_000)
        self.assertEqual(pension_income(a, d, ceil_yen), 700_001)
        self.assertEqual(pension_income(a, d, half_up_yen), 700_001)
        self.assertEqual(pension_deduction_yen(a, d, floor_yen), a - 700_000)
        self.assertEqual(pension_deduction_yen(a, d, ceil_yen), a - 700_001)

    def test_deduction_over_income_is_integral_minimum(self) -> None:
        # 控除額が収入金額以上のときは最低額（整数）
        r = pension_rules(params("2026-01-01"))
        d = pension_deduction(599_999, 0, 40, r)
        self.assertEqual(d, Fraction(600_000))
        self.assertEqual(pension_deduction_yen(599_999, d, floor_yen), 600_000)


class TestWindfall(unittest.TestCase):
    """一時所得：所法34②③（jigyo §6）。"""

    def test_boundaries(self) -> None:
        for at in YEARS:
            s = int(params(at).所得税.一時所得.特別控除額)
            self.assertEqual(s, 500_000)
            self.assertEqual(windfall_income(500_000, 0, s), 0)  # 残額が50万円：特別控除額は50万円
            self.assertEqual(windfall_income(500_001, 0, s), 1)
            self.assertEqual(windfall_income(100_000, 200_000, s), 0)  # 残額が負：一時所得は0

    def test_shitsugi_example(self) -> None:
        # jigyo §6 質疑応答事例 02/04：(100万+2,000万)−(200万+1,200万)−50万＝650万円
        self.assertEqual(windfall_income(21_000_000, 14_000_000, 500_000), 6_500_000)


class TestRetirement(unittest.TestCase):
    """退職所得：所法30②③⑥（taishoku §2.1）、TA2732 の例（§4.2）、別表第六（§2.5）。"""

    def setUp(self) -> None:
        self.r = retirement_rules(params("2026-01-01"))

    def test_service_limits_match_parameters(self) -> None:
        # taishoku §2.1：所法30④（短期勤続年数 五年以下）・⑤（役員等勤続年数 五年以下）。入力の段（inputs.py）の定数がパラメータと同じ
        for at in YEARS:
            with self.subTest(at=at):
                n = params(at).所得税.退職所得
                self.assertEqual(int(n.短期退職手当等.勤続年数の上限), SHORT_SERVICE_LIMIT)
                self.assertEqual(int(n.特定役員退職手当等.役員等勤続年数の上限), OFFICER_SERVICE_LIMIT)

    def test_deduction_table(self) -> None:
        # taishoku §2.5 別表第六：2年以下 800千円／障害 1,800千円、20年 8,000千円、21年 8,700千円、40年 22,000千円
        self.assertEqual(retirement_deduction(1, False, self.r), 800_000)
        self.assertEqual(retirement_deduction(2, False, self.r), 800_000)
        self.assertEqual(retirement_deduction(2, True, self.r), 1_800_000)
        self.assertEqual(retirement_deduction(3, False, self.r), 1_200_000)
        self.assertEqual(retirement_deduction(20, False, self.r), 8_000_000)
        self.assertEqual(retirement_deduction(21, False, self.r), 8_700_000)
        self.assertEqual(retirement_deduction(40, False, self.r), 22_000_000)

    def test_ta2732_examples(self) -> None:
        # taishoku §4.2 TA2732：800万円・10年2か月→11年、控除 440万円、課税退職所得金額 180万円
        ded = retirement_deduction(service_years(dt.date(2016, 1, 1), dt.date(2026, 2, 28)), False, self.r)
        self.assertEqual(ded, 4_400_000)
        self.assertEqual(retirement_income(8_000_000, ded, RETIRE_GENERAL, self.r, floor_yen), 1_800_000)
        # 2,300万円・29年2か月→30年、控除 1,500万円、400万円
        ded = retirement_deduction(30, False, self.r)
        self.assertEqual(ded, 15_000_000)
        self.assertEqual(retirement_income(23_000_000, ded, RETIRE_GENERAL, self.r, floor_yen), 4_000_000)

    def test_short_term_boundary(self) -> None:
        # 所法30②一・二（taishoku §2.1）：控除 200万円（5年）
        ded = retirement_deduction(5, False, self.r)
        self.assertEqual(ded, 2_000_000)
        self.assertEqual(retirement_income(5_000_000, ded, RETIRE_SHORT, self.r, floor_yen), 1_500_000)  # 残額300万円：1/2
        self.assertEqual(retirement_income(5_000_001, ded, RETIRE_SHORT, self.r, floor_yen), 1_500_001)  # 超：150万円＋超える部分
        self.assertEqual(retirement_income(5_000_001, ded, RETIRE_GENERAL, self.r, floor_yen), 1_500_000)  # 一般なら 1/2（端数は候補）
        self.assertEqual(retirement_income(5_000_001, ded, RETIRE_GENERAL, self.r, ceil_yen), 1_500_001)

    def test_officer_has_no_half(self) -> None:
        # 所法30②本文かっこ書（特定役員退職手当等は残額そのもの）
        self.assertEqual(retirement_income(5_000_000, 2_000_000, RETIRE_OFFICER, self.r, floor_yen), 3_000_000)

    def test_below_deduction_is_zero(self) -> None:
        self.assertEqual(retirement_income(700_000, 800_000, RETIRE_GENERAL, self.r, floor_yen), 0)

    def test_service_years(self) -> None:
        # 所令69②・所基通30−13（taishoku §2.2）：暦に従って数え、1年未満の端数は1年
        self.assertEqual(service_years(dt.date(2016, 4, 1), dt.date(2026, 3, 31)), 10)  # ちょうど10年
        self.assertEqual(service_years(dt.date(2016, 4, 1), dt.date(2026, 4, 1)), 11)  # 1日超える
        self.assertEqual(service_years(dt.date(2026, 4, 1), dt.date(2026, 4, 1)), 1)


class TestHomeWorker(unittest.TestCase):
    """家内労働者等の特例：措法27・措令18の2②（jigyo §2.1・§2.3 の計算書）。65万円（令和7年分）・69万円（令和8年分）。"""

    def test_amount_by_year(self) -> None:
        self.assertEqual(int(params("2025-01-01").所得税.家内労働者等の必要経費の特例.額), 650_000)
        self.assertEqual(int(params("2026-01-01").所得税.家内労働者等の必要経費の特例.額), 690_000)

    def test_not_home_worker(self) -> None:
        e = home_worker_expenses(1_000_000, 100_000, 0, 0, 690_000, False)
        self.assertEqual((e.business, e.misc, e.special_applied), (100_000, 0, False))

    def test_business_only(self) -> None:
        # jigyo §2.4 の2(1)：事業所得の総収入金額と特例の額のいずれか少ない方
        self.assertEqual(home_worker_expenses(1_000_000, 100_000, 0, 0, 690_000, True).business, 690_000)
        self.assertEqual(home_worker_expenses(500_000, 100_000, 0, 0, 690_000, True).business, 500_000)
        # 必要経費が特例の額以上なら特例は使わない（69万円ちょうど・1円下）
        self.assertFalse(home_worker_expenses(2_000_000, 690_000, 0, 0, 690_000, True).special_applied)
        self.assertTrue(home_worker_expenses(2_000_000, 689_999, 0, 0, 690_000, True).special_applied)

    def test_misc_only(self) -> None:
        self.assertEqual(home_worker_expenses(0, 0, 300_000, 10_000, 650_000, True).misc, 300_000)
        self.assertEqual(home_worker_expenses(0, 0, 900_000, 10_000, 650_000, True).misc, 650_000)

    def test_both_form(self) -> None:
        # jigyo §2.3 の計算書（給与なし）：⑤＝T−②、⑥＝T−③、③≤⑤なら事業＝min(①, ⑥)、③＞⑤なら事業＝②、雑＝min(③, ⑤)
        t = 650_000
        # ③(100,000) ≤ ⑤(650,000−50,000=600,000)：事業＝min(1,000,000, 650,000−100,000)＝550,000、雑＝100,000
        e = home_worker_expenses(1_000_000, 50_000, 100_000, 0, t, True)
        self.assertEqual((e.business, e.misc), (550_000, 100_000))
        # ③(700,000) ＞ ⑤(600,000)：事業＝②＝50,000、雑＝min(700,000, 600,000)＝600,000
        e = home_worker_expenses(1_000_000, 50_000, 700_000, 0, t, True)
        self.assertEqual((e.business, e.misc), (50_000, 600_000))

    def test_business_deficit_form(self) -> None:
        # IK-100（D22 S1：計算書の読み）。事業所得が赤字（②200,000＞①100,000）、⑤＝650,000−200,000＝450,000
        t = 650_000
        # ③(450,001) ＞ ⑤：事業＝⑧＝②＝200,000（赤字のまま）、雑＝⑤＝450,000
        e = home_worker_expenses(100_000, 200_000, 450_001, 0, t, True)
        self.assertEqual((e.business, e.misc), (200_000, 450_000))
        # ③(450,000) ＝ ⑤：事業＝⑦＝min(①, ⑥＝200,000)＝100,000、雑＝450,000
        e = home_worker_expenses(100_000, 200_000, 450_000, 0, t, True)
        self.assertEqual((e.business, e.misc), (100_000, 450_000))


class TestBlueDeduction(unittest.TestCase):
    """青色申告特別控除：措法25の2①③④⑥（aoiro §3.1）。限度は黒字の金額（措通25の2−1：aoiro §3.2）。"""

    def setUp(self) -> None:
        self.r = blue_rules(params("2026-01-01"))

    def test_amounts(self) -> None:
        self.assertEqual((self.r.basic, self.r.full, self.r.etax), (100_000, 550_000, 650_000))
        self.assertEqual(blue_deduction(True, 3_000_000, True, FILING_ETAX, self.r), 650_000)
        self.assertEqual(blue_deduction(True, 3_000_000, True, FILING_PAPER, self.r), 550_000)
        self.assertEqual(blue_deduction(True, 3_000_000, True, FILING_OTHER, self.r), 100_000)  # 期限後：第1項
        self.assertEqual(blue_deduction(True, 3_000_000, False, FILING_ETAX, self.r), 100_000)  # 簡易な記帳：第1項

    def test_limit_and_no_approval(self) -> None:
        self.assertEqual(blue_deduction(True, 400_000, True, FILING_ETAX, self.r), 400_000)
        self.assertEqual(blue_deduction(True, 0, True, FILING_ETAX, self.r), 0)
        self.assertEqual(blue_deduction(True, -5, True, FILING_ETAX, self.r), 0)
        self.assertEqual(blue_deduction(False, 3_000_000, True, FILING_ETAX, self.r), 0)


if __name__ == "__main__":
    unittest.main()

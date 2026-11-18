"""規則モジュール juminzei（rules/juminzei/）のユニットテスト（D24：関数・表・1つの変数の式を直接呼ぶ。上流はスタブ）。

テストのデータはどれも架空の金額・架空の人。期待値の出典（docs のファイルと節）：
  [LAW] docs/public-sources/20261109_round2_juminzei-tax-law-text.md、[PSJ] docs/public-sources/20261109_impl-prep_juminzei-hikazei-fuyo-shinkoku.md、
  [SP] docs/public-sources/20261109_round2_spouse-laws-and-sources.md §3.2、[ADM] docs/public-sources/20261109_round2_juminzei-tax-admin-and-municipal.md §2
  （自治体の計算例。法令の式で再現できることを確かめた：docs/measurements/20261109_round2_juminzei-tax-fetch-and-checks.md §3.7）、
  [EXTRA] docs/public-sources/20261109_round3_juminzei-extra-law-text.md、[JINTEKI] docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md、
  [JM3] docs/public-sources/20261111_impl-research3_juminzei-laws-and-soumu.md、[M3F] docs/measurements/20261111_impl-research3_all-fetch-and-checks.md、
  [KIFU4] docs/public-sources/20261112_impl-research4_juminzei-kifu-laws-and-kokuji.md（仮説 H10・推測 I9 は docs/hypotheses・docs/inferences の 20261112_impl-research4_*）。
"""

from __future__ import annotations

import datetime as _dt
import unittest
from fractions import Fraction
from typing import Any

from openfisca_core.simulation_builder import SimulationBuilder

from okura_core.injection import EMPTY
from okura_core.registry import Decided, YearContext, YearWindow, injection_key, injection_kind
from okura_core.result import Means, Split
from okura_core.rules.juminzei import calc, inputs
from okura_core.timepoints import resident_tax_window

from .support import make_ir, person, system

R8 = "2025-01-01"  # 令和8年度分のパラメータの日付のキー（所得の年分の1月1日）


def _p(instant: str = R8) -> Any:
    return system().parameters(instant).住民税


def _rules(instant: str = R8) -> calc.ChainRules:
    p = _p(instant)
    return calc.ChainRules(adjust=p.調整控除, credits=p.税額控除, rates=p.税率)


def _chain(**kw: Any) -> calc.ChainInput:
    base: dict[str, Any] = dict(
        taxable=0, taxable_dividend=0, taxable_gain=0, total_income=0, gross_income=0, personal_diff=50000, personal_adjust=50000,
        surplus_dividend=0, trust_dividend=0, foreign_dividend=0, housing_credit=0, income_tax_before=0, housing_base=0,
        donation_total=0, special_donation=0, filing_special=False, withheld_local=0, exemption_line=450000, designated=False,
        rate_m=Fraction(6, 100), rate_p=Fraction(4, 100),
    )
    base.update(kw)
    return calc.ChainInput(**base)


class TestDeductionBoundaries(unittest.TestCase):
    """所得控除の額の境目（地方税法第314条の2）。"""

    def test_spouse_special_steps(self) -> None:
        # [SP]：配偶者 100万円以下 33万円、100万円超からは「38万円−（93万1円を超える部分を5万円の整数倍−3万円に切下げ）」、130万円超 3万円、133万円超 0
        p = _p().所得控除.配偶者特別控除
        cases = [(1_000_000, 330_000), (1_000_001, 310_000), (1_050_000, 310_000), (1_050_001, 260_000), (1_300_000, 60_000), (1_300_001, 30_000), (1_330_000, 30_000), (1_330_001, 0)]
        for income, want in cases:
            with self.subTest(income=income):
                self.assertEqual(calc.spouse_special_deduction(5_000_000, income, p), want)
        # 本人 900万円超950万円以下：2/3（1万円未満切上げ）、1,000万円超は0
        self.assertEqual(calc.spouse_special_deduction(9_000_001, 1_050_001, p), 180_000)  # 26万×2/3＝173,333 → 18万
        self.assertEqual(calc.spouse_special_deduction(10_000_001, 800_000, p), 0)

    def test_specified_relative_and_basic(self) -> None:
        # [PSJ]§5：特定親族特別控除 95万円以下 45万、95万超100万以下 41万 … 120万超123万以下 3万。基礎控除 2,400万以下 43万 … 2,500万超 0
        sp = _p().所得控除.特定親族特別控除
        for income, want in [(950_000, 450_000), (950_001, 410_000), (1_150_001, 60_000), (1_230_000, 30_000), (1_230_001, 0)]:
            with self.subTest(income=income):
                self.assertEqual(calc.specified_relative_amount(income, sp), want)
        b = _p().所得控除.基礎控除
        for income, want in [(24_000_000, 430_000), (24_000_001, 290_000), (25_000_000, 150_000), (25_000_001, 0)]:
            with self.subTest(income=income):
                self.assertEqual(calc.basic_deduction(income, b), want)

    def test_life_and_earthquake_exact(self) -> None:
        # [HOKEN]§7：新契約 3万2千円超5万6千円以下は 2万2千円＋超える部分の1/4（1円未満は有理数のまま）。地震保険料は1/2（上限2万5千円）
        p = _p().所得控除
        general, care, annuity = calc.life_insurance_exact(40_001, 0, 0, 0, 0, "both", p.生命保険料控除)
        self.assertEqual(general, Fraction(22_000) + Fraction(8_001, 4))
        self.assertEqual(calc.earthquake_exact(30_001, 0, p.地震保険料控除), Fraction(30_001, 2))
        self.assertEqual(calc.earthquake_exact(60_000, 20_000, p.地震保険料控除), Fraction(25_000))


class TestExemptionLines(unittest.TestCase):
    """非課税の基準（附則第3条の3第4項、施行令第47条の3・施行規則第9条の21、第295条第1項）。"""

    def test_income_levy_line(self) -> None:
        # [PSJ]§2.1：35万円×（数＋1）＋10万円（数が1以上なら＋32万円）
        q = _p().非課税.所得割
        line = lambda n: calc.exemption_line(n, int(q.人数ごとの額), int(q.定額), int(q.扶養がある場合の加算額))  # noqa: E731
        self.assertEqual((line(0), line(1), line(3)), (450_000, 1_120_000, 1_820_000))

    def test_per_capita_levy_line_by_grade(self) -> None:
        # [PSJ]§1.4：政令の基準どおりの基本額・加算額は 1級地 35万・21万、2級地 31万5千・18万9千、3級地 28万・16万8千（定額10万円）
        q = _p().非課税.均等割
        want = {"一級地": (350_000, 210_000), "二級地": (315_000, 189_000), "三級地": (280_000, 168_000)}
        for grade, (base, add) in want.items():
            r = q.級地の率[grade]
            got = (int(q.基本額の上限) * int(r.分子) // int(r.分母), int(q.加算額の上限) * int(r.分子) // int(r.分母))
            with self.subTest(grade=grade):
                self.assertEqual(got, (base, add))
                self.assertEqual(calc.exemption_line(0, base, int(q.定額), add), base + 100_000)
                self.assertEqual(calc.exemption_line(1, base, int(q.定額), add), 2 * base + 100_000 + add)

    def test_variables_at_the_lines(self) -> None:
        # 135万円（第295条第1項第2号）と、2級地の均等割の非課税（41万5千円）の境目を、式を直接計算して確かめる（上流は入力で与える）
        def person_(total: int, minor: bool) -> dict[str, Any]:
            return {
                "住民税_賦課期日に住所を有する市町村": {"2026": "990001"},
                "住民税_未成年者か": {"2026": minor},
                "住民税_合計所得金額": {"2026": total},
                "住民税_総所得金額等": {"2026": total},
                "住民税_同一生計配偶者及び扶養親族の数": {"2026": 0},
                "住民税_均等割の非課税の基本額": {"2026": 315_000},
                "住民税_均等割の非課税の加算額": {"2026": 189_000},
            }

        people = {"a": person_(1_350_000, True), "b": person_(1_350_001, True), "c": person_(415_000, False), "d": person_(415_001, False)}
        sim = SimulationBuilder().build_from_entities(system(), {"人物一覧": people})
        self.assertEqual(list(sim.calculate("住民税_第295条第1項の非課税に当たるか", "2026")), [True, False, False, False])
        self.assertEqual(list(sim.calculate("住民税_均等割を課さない者か", "2026")), [False, False, True, False])

    def test_boundary_criteria_of_exemptions(self) -> None:
        # 境目の説明の基準の概念（2026-11-12）：[PSJ]§2.1 所得割の非課税は 35万円×（数＋1）＋10万円（扶養があれば＋32万円）以下、
        # [PSJ]§1.1・§1.4 均等割の非課税は 条例の基本額×（数＋1）＋10万円（扶養があれば＋加算額）以下（2級地の型 31万5千・18万9千）
        def person_(total: int, n: int) -> dict[str, Any]:
            return {
                "住民税_合計所得金額": {"2026": total},
                "住民税_総所得金額等": {"2026": total},
                "住民税_同一生計配偶者及び扶養親族の数": {"2026": n},
                "住民税_均等割の非課税の基本額": {"2026": 315_000},
                "住民税_均等割の非課税の加算額": {"2026": 189_000},
            }

        people = {"a": person_(450_000, 0), "b": person_(450_001, 0), "c": person_(415_000, 0), "d": person_(1_119_000, 1)}
        sim = SimulationBuilder().build_from_entities(system(), {"人物一覧": people})
        self.assertEqual(list(sim.calculate("住民税_所得割の非課税の基準の額", "2026")), [450_000, 450_000, 450_000, 1_120_000])
        self.assertEqual(list(sim.calculate("住民税_所得割を課さない者か", "2026")), [True, False, True, True])
        self.assertEqual(list(sim.calculate("住民税_均等割の非課税の基準の額", "2026")), [415_000, 415_000, 415_000, 919_000])
        self.assertEqual(list(sim.calculate("住民税_均等割の非課税の合計所得金額要件", "2026")), [False, False, True, False])

    def test_widow_bearing_part_of_support(self) -> None:
        # [JINTEKI]§2.5 取扱通知 第2章第1節第1の3：扶養親族が他の納税義務者の扶養親族でも、扶養費の一部を負担する離婚した者は非課税の判定で寡婦（所得税の寡婦ではない）
        def person_(bears: bool, remarried: bool) -> dict[str, Any]:
            return {
                "住民税_扶養費の一部を負担しているか": {"2026": bears},
                "所得税_夫と離婚した後婚姻をしていない者か": {"2026": True},
                "所得税_配偶者がいるか": {"2026": remarried},
            }

        sim = SimulationBuilder().build_from_entities(system(), {"人物一覧": {"a": person_(True, False), "b": person_(False, False), "c": person_(True, True)}})
        self.assertEqual(list(sim.calculate("住民税_非課税の判定で寡婦に当たるか", "2026")), [True, False, False])

    def test_separate_retirement_income_is_excluded(self) -> None:
        # [TA]§6.3：住民税の合計所得金額に源泉徴収された退職所得を含めない（扶養の要件の 62万円などに使う）。分離課税に係る退職所得は
        # 損益通算の前の退職所得の金額（§6.1：第328条の2）で、合計所得金額は退職所得がないものとして計算した窓口の値（JM-20）。
        # c は損益通算で所得税の退職所得金額が 0 になった人（所得税の合計所得金額 0、住民税では分離課税 300,000・合計所得金額 0）
        def p_(total: int, kind: int, after: int, whole: bool, window: int) -> dict[str, Any]:
            return {
                "所得税_合計所得金額": {"2026": total}, "所得税_退職所得の金額": {"2026": kind}, "所得税_退職所得金額": {"2026": after},
                "所得税_退職手当等の全部が源泉徴収の対象か": {"2026": whole}, "所得税_分離課税の退職所得を除いた合計所得金額": {"2026": window},
            }

        people = {"a": p_(700_000, 200_000, 200_000, True, 500_000), "b": p_(700_000, 200_000, 200_000, False, 500_000), "c": p_(0, 300_000, 0, True, 0)}
        sim = SimulationBuilder().build_from_entities(system(), {"人物一覧": people})
        self.assertEqual(list(sim.calculate("住民税_合計所得金額", "2026")), [500_000, 700_000, 0])
        self.assertEqual(list(sim.calculate("住民税_分離課税に係る退職所得の金額", "2026")), [200_000, 0, 300_000])
        self.assertEqual(list(sim.calculate("住民税_総所得金額等に含まれる退職所得金額", "2026")), [0, 200_000, 0])


class TestReadingsAndWindows(unittest.TestCase):
    """2026-11-12：JM-22（読みの候補）・JM-03（賦課期日の現況）・JM-18（特例法）。"""

    def test_taxable_rounding_readings(self) -> None:
        # [LAW]§15・§16、hypotheses juminzei-tax-calc-model H5：総所得金額 3,000,500・所得控除 1,000,700
        # 控除後に当てる：1,999,800 → 1,999,000。控除前に当てる：3,000,000 − 1,000,700 = 1,999,300
        self.assertEqual(calc.floor_unit(3_000_500 - 1_000_700, 1000), 1_999_000)
        self.assertEqual(calc.taxable_floor_before_deduction(3_000_500, 1_000_700, 1000), 1_999_300)
        self.assertEqual(calc.taxable_floor_before_deduction(500, 1_000, 1000), 0)
        people = {
            k: {"所得税_総所得金額": {"2026": 3_000_500}, "住民税_所得控除の合計": {"2026": 1_000_700}, "住民税_課税標準の千円未満の切捨ての当て先の読み": {"2026": r}}
            for k, r in (("a", calc.READING_AFTER_DEDUCTION), ("b", calc.READING_BEFORE_DEDUCTION))
        }
        sim = SimulationBuilder().build_from_entities(system(), {"人物一覧": people})
        self.assertEqual(list(sim.calculate("住民税_課税総所得金額等", "2026")), [1_999_000, 1_999_300])

    def test_nontaxable_at_jan1(self) -> None:
        # 判定の時点を賦課期日とする候補：障害者は翌年1月1日の現況、賦課期日に婚姻している人は寡婦・ひとり親に当たらない（JM-03）
        def p_(now: bool, dis_dec: bool, dis_jan: bool, single: bool, changed: bool, married: bool) -> dict[str, Any]:
            return {
                "住民税_賦課期日に住所を有する市町村": {"2026": "990001"}, "住民税_合計所得金額": {"2026": 1_000_000},
                "住民税_非課税の判定を賦課期日の現況で行うか": {"2026": now}, "所得税_障害者に当たるか": {"2026": dis_dec},
                "所得税_翌年1月1日に障害者に当たるか": {"2026": dis_jan}, "所得税_ひとり親に当たるか": {"2026": single},
                "所得税_翌年1月1日に婚姻の状況が判定の時と違うか": {"2026": changed}, "所得税_翌年1月1日に婚姻又は事実婚をしているか": {"2026": married},
            }

        people = {
            "a": p_(True, False, True, False, False, False),  # 1月1日に障害者になった
            "b": p_(False, False, True, False, False, False),  # 12月31日の現況で判定する市町村
            "c": p_(True, False, False, True, True, True),  # 12月31日はひとり親、1月1日に婚姻
            "d": p_(False, False, False, True, True, True),
        }
        sim = SimulationBuilder().build_from_entities(system(), {"人物一覧": people})
        self.assertEqual(list(sim.calculate("住民税_第295条第1項の非課税に当たるか", "2026")), [True, False, False, True])

    def test_housing_special_acts(self) -> None:
        # [EXTRA]§3.5：震災特例法（附則第45条第6項）は平成26年4月1日以後〜令和3年の居住で区分を問わず 4.2%、新型コロナ特例法で令和4年まで
        self.assertEqual(inputs.housing_version(2018, None, ("great_east_japan_earthquake",), _dt.date(2018, 5, 1)), (True, True))
        self.assertEqual(inputs.housing_version(2014, None, ("great_east_japan_earthquake",), _dt.date(2014, 3, 31)), (False, False))
        self.assertEqual(inputs.housing_version(2022, None, ("great_east_japan_earthquake",), _dt.date(2022, 6, 1)), (True, False))
        self.assertEqual(inputs.housing_version(2022, None, ("great_east_japan_earthquake", "covid19"), _dt.date(2022, 6, 1)), (True, True))
        self.assertEqual(inputs.housing_version(2022, "specified_acquisition", ("covid19",)), (True, True))
        self.assertEqual(inputs.housing_version(2022, "specified_acquisition"), (True, False))


class TestChain(unittest.TestCase):
    """所得割の額の連鎖（第314条の3・第314条の6〜第314条の9、附則第3条の3第5項・第5条の4・第7条の2）。"""

    def test_municipal_examples(self) -> None:
        # [ADM]§2.1 名古屋市（指定都市、市 7.7%・県 2%、人的控除差 33万円、課税総所得金額 156万2千円）：市 107,074 → 107,000、県 27,940 → 27,900
        r = calc.compute_chain(
            _chain(taxable=1_562_000, total_income=3_963_200, gross_income=3_963_200, personal_diff=330_000, designated=True, rate_m=Fraction(77, 1000), rate_p=Fraction(2, 100)),
            _rules(),
        )
        self.assertEqual((r.municipal.adjustment, r.prefectural.adjustment), (13_200, 3_300))
        self.assertEqual((r.municipal.final, r.prefectural.final), (107_000, 27_900))
        # [ADM]§2.2 横浜市（指定都市、市 8%・県 2.025%、200万円超で調整控除は5万円の5%）：192,960 → 192,900、48,849.25 → 48,800
        r = calc.compute_chain(
            _chain(taxable=2_437_000, total_income=3_960_000, gross_income=3_960_000, personal_diff=150_000, designated=True, rate_m=Fraction(8, 100), rate_p=Fraction(2025, 100000)),
            _rules(),
        )
        self.assertEqual((r.municipal.adjustment, r.prefectural.adjustment), (2_000, 500))
        self.assertEqual((r.municipal.final, r.prefectural.final), (192_900, 48_800))

    def test_border_adjustment(self) -> None:
        # [LAW]§10 附則第3条の3第5項：総所得金額等 113万円、扶養1人（基準 112万円）。調整の後の所得割の合計は 総所得金額等−基準＝1万円（B:C で按分）
        r = calc.compute_chain(
            _chain(taxable=370_000, total_income=1_130_000, gross_income=1_130_000, personal_diff=100_000, exemption_line=1_120_000),
            _rules(),
        )
        self.assertEqual((r.municipal.border, r.prefectural.border), (13_200, 8_800))
        self.assertEqual((r.municipal.final, r.prefectural.final), (6_000, 4_000))

    def test_furusato_with_filing_special(self) -> None:
        # [LAW]§8：寄附 3万円（全額が特例控除対象）、課税総所得金額−人的控除差調整額 295万円（79.79%・申告特例 10.21/79.79）。
        # 基本控除（10%）＋特例控除（79.79%）＋申告特例控除（10.21%）＝ 寄附−2,000円 の全額
        r = calc.compute_chain(
            _chain(taxable=3_000_000, total_income=4_000_000, gross_income=4_000_000, donation_total=30_000, special_donation=30_000, filing_special=True),
            _rules(),
        )
        self.assertEqual(r.total("donation") + r.total("filing_special"), 28_000)
        self.assertEqual(r.total("filing_special"), Fraction(28_000) * Fraction(1021, 10000))

    def test_withheld_local_tax_is_last_and_shortfall(self) -> None:
        # [EXTRA]§2.1：配当割額×3/5・2/5 を最後に控除し、控除しきれない額は控除不足額
        r = calc.compute_chain(_chain(taxable=10_000, total_income=480_000, gross_income=480_000, exemption_line=0, withheld_local=5_000), _rules())
        self.assertEqual(r.total("withheld") + r.total("shortfall"), 5_000)
        self.assertEqual((r.municipal.final, r.prefectural.final), (0, 0))
        self.assertGreater(r.total("shortfall"), 0)

    def test_separate_retirement_tax(self) -> None:
        # [LAW]§12：退職所得の金額（千円未満切捨て）×6%・4%、それぞれ百円未満切捨て
        self.assertEqual(calc.retirement_separate_tax(1_234_567, _p().税率), 74_000 + 49_300)

    def test_special_ratio_with_separate_income(self) -> None:
        # [JM3]§2・[LAW]§8.2 附則第5条の5第2項第5号：課税総所得金額−人的控除差調整額が0未満で上場株式等の分離課税があれば 75%（附則第5条の6 で 74.685%）。
        # 0以上なら第11項第1号の表のまま、分離課税がなければ第2号の 90%
        k = _p().税額控除.寄附金税額控除
        self.assertEqual(calc.special_ratio_with_separate(0, 50_000, True, k), Fraction(74_685, 100_000))
        self.assertEqual(calc.special_ratio_with_separate(0, 50_000, False, k), Fraction(90, 100))
        self.assertEqual(calc.special_ratio_with_separate(50_000, 50_000, True, k), Fraction(84_895, 100_000))
        # 推測 J-1 の形（課税総所得金額なし、上場配当の所得割）：(50,000−2,000)×74.685%×3/5、所得割の額の20%が上限
        r = calc.compute_chain(_chain(taxable_dividend=10_000_000, total_income=10_000_000, gross_income=10_000_000, donation_total=50_000, special_donation=50_000, exemption_line=0, separate_income=True), _rules())
        self.assertEqual(r.municipal.donation, Fraction(48_000) * Fraction(6, 100) + Fraction(48_000) * Fraction(74_685, 100_000) * Fraction(3, 5))
        r = calc.compute_chain(_chain(taxable_dividend=2_000_000, total_income=2_000_000, gross_income=2_000_000, donation_total=50_000, special_donation=50_000, exemption_line=0, separate_income=True), _rules())
        self.assertEqual(r.municipal.donation, Fraction(48_000) * Fraction(6, 100) + Fraction(60_000) * Fraction(20, 100))

    def test_donations_by_entity_and_specified_acquisition(self) -> None:
        # [JM3]§1：第3号・第4号は市町村・道府県それぞれの条例。市町村の条例だけにある寄附 1万円は市町村民税だけ（1万円−2千円）×6%
        r = calc.compute_chain(_chain(taxable=3_000_000, total_income=4_000_000, gross_income=4_000_000, donation_extra_m=10_000), _rules())
        self.assertEqual((r.municipal.donation, r.prefectural.donation), (Fraction(480), Fraction(0)))
        # [EXTRA]§3.2 附則第5条の4第7項：特定取得なら控除限度は 4.2%・81,900円（2.8%・54,600円）。基が大きければ上限
        big = dict(taxable=8_000_000, total_income=9_000_000, gross_income=9_000_000, housing_credit=400_000, income_tax_before=0, housing_base=10_000_000)
        normal = calc.compute_chain(_chain(**big), _rules())
        special = calc.compute_chain(_chain(**big, housing_specified=True), _rules())
        self.assertEqual((normal.municipal.housing, normal.prefectural.housing), (58_500, 39_000))
        self.assertEqual((special.municipal.housing, special.prefectural.housing), (81_900, 54_600))

    def test_per_capita_rounding_with_income_levy(self) -> None:
        # [LAW]§15 第20条の4の2第3項：確定金額（均等割＋所得割）の百円未満を切り捨てる。均等割 3,050円は所得割の百円未満の部分が 50円以上なら繰り上がる
        self.assertEqual(calc.levy_fraction(Fraction(12_349, 1) + Fraction(1, 3), 100), 49)
        self.assertEqual([calc.per_capita_with_income_levy(3_050, f, 100) for f in (0, 49, 50)], [3_000, 3_000, 3_100])
        self.assertEqual(calc.per_capita_with_income_levy(3_000, 99, 100), 3_000)


class TestCodesAndOrders(unittest.TestCase):
    """団体コード・分離課税の所得への所得控除の順序・第311条の軽減（純粋関数）。"""

    def test_prefecture_code(self) -> None:
        # [JM3]§4・[M3F]§5（推測 J-4）：131016 → 130001、仕様の例 062014 の検査数字 4、01 は積の和が11未満
        self.assertEqual(calc.check_digit("06201"), 4)
        self.assertEqual(calc.prefecture_code("131016"), "130001")
        self.assertEqual(calc.prefecture_code("011002"), "010006")
        with self.assertRaises(ValueError):
            calc.prefecture_code("001000")  # 積の和0：仕様で決まらない
        self.assertEqual(inputs.issuer_code("prefecture", "001000"), "00000?")

    def test_separate_deduction_order(self) -> None:
        # 引ききれない 1,500円を配当 1,000,500・譲渡 1,000,700 から：配当が先なら 999,000＋1,000,000、譲渡が先なら 1,000,000＋999,000（合計同じ）
        o1, o2 = calc.ORDER_DIVIDEND_FIRST, calc.ORDER_GAIN_FIRST
        self.assertEqual(calc.separate_deductions(1_500, 1_000_500, 1_000_700, o1), (1_500, 0))
        self.assertEqual(calc.separate_deductions(1_500, 1_000_500, 1_000_700, o2), (0, 1_500))
        self.assertEqual(calc.separate_taxable_total(1_500, 1_000_500, 1_000_700, o1, 1000), calc.separate_taxable_total(1_500, 1_000_500, 1_000_700, o2, 1000))
        # 600円なら 999,000＋1,000,000 と 1,000,000＋1,000,000：順序で分かれる
        self.assertNotEqual(calc.separate_taxable_total(600, 1_000_500, 1_000_700, o1, 1000), calc.separate_taxable_total(600, 1_000_500, 1_000_700, o2, 1000))

    def test_reduced_per_capita(self) -> None:
        # [LAW]§13 第311条：第1号・第2号に当たり、条例が軽減を定めていればその額。欄がない・両方で額が違えば決まらない
        data = {"軽減する": True, "第1号の均等割の額": 1_500}
        self.assertEqual(calc.reduced_per_capita(3_000, True, False, data), (1_500, None))
        self.assertEqual(calc.reduced_per_capita(3_000, False, True, data), (3_000, "第2号の均等割の額"))
        self.assertEqual(calc.reduced_per_capita(3_000, True, True, {**data, "第2号の均等割の額": 2_000})[1] is not None, True)
        self.assertEqual(calc.reduced_per_capita(3_000, True, False, {"軽減する": False}), (3_000, None))
        self.assertEqual(calc.reduced_per_capita(3_000, False, False, None), (3_000, None))


class TestInputs(unittest.TestCase):
    """build_inputs：時点（未成年者）と注入データの有無。"""

    def test_minor_age_at_end_of_day(self) -> None:
        # [PSJ]§3.2：令和8年度の賦課期日（2026-01-01）の未成年者は 2008-01-03 以後に生まれた人（誕生日の前日の終了時に加齢）
        self.assertEqual(inputs.age_at_end_of(_dt.date(2008, 1, 2), _dt.date(2026, 1, 1)), 18)
        self.assertEqual(inputs.age_at_end_of(_dt.date(2008, 1, 3), _dt.date(2026, 1, 1)), 17)

    def _ctx(self, rate: dict[str, Any] | None) -> YearContext:
        ir = make_ir(
            [person("a", "1980-05-01")],
            [],
            residences=[{"id": "r1", "kind": "resident_record", "roles": {"person": "a"}, "when": {"from_on": "2020-01-01"}, "attributes": {"municipality_code": "990001", "household_id": "h1", "householder": True}}],
        )
        jan1, dec31 = _dt.date(2027, 1, 1), _dt.date(2026, 12, 31)
        split = Split(id="注入:x", means=Means.INJECTION, target={}, candidates=(), splits_conclusion=True)

        def dec(value: Any) -> Decided:
            return Decided(value, (), frozenset(), False) if value is not None else Decided(None, (), frozenset(), False, missing=(split,))

        decided = {
            (injection_kind(inputs.P_KYUCHI), injection_key("municipality", "990001", dec31)): dec({"級地": "2級地"}),
            (injection_kind(inputs.P_TIMING), injection_key("municipality", "990001", jan1)): dec({"時点": inputs.TIMING_JAN1}),
            (injection_kind(inputs.P_SHOTOKU), injection_key("municipality", "990001", jan1)): dec(rate),
            (injection_kind(inputs.P_SHOTOKU), injection_key("prefecture", "990001", jan1)): dec(None if rate is None else {"税率": {"num": 4, "den": 100}}),
            (injection_kind(inputs.P_KINTO), injection_key("municipality", "990001", jan1)): dec(None if rate is None else {"税率": 3000}),
            (injection_kind(inputs.P_KINTO), injection_key("prefecture", "990001", jan1)): dec(None if rate is None else {"税率": 1000}),
        }
        window = YearWindow(parameters_at=lambda s: system().parameters(s), parameter_root=system().parameters, windows=(resident_tax_window(2027),), injected=EMPTY)
        return YearContext(ir, 2026, ("a",), decided, window=window)

    def test_injected_rates_and_grade(self) -> None:
        out = inputs.build_inputs(self._ctx({"税率": {"num": 6, "den": 100}, "指定都市": False}))
        v = {k[0]: iv for k, iv in out.values.items()}
        self.assertEqual(v["住民税_賦課期日に住所を有する市町村"].value, "990001")
        self.assertEqual((v["住民税_市町村民税の所得割の税率の分子"].value, v["住民税_市町村民税の所得割の税率の分母"].value), (6, 100))
        self.assertEqual(v["住民税_市町村民税の所得割の税率の分子"].missing, ())
        # 均等割の非課税の額が注入されていなければ、級地（2級地）の政令の基準どおりの額
        self.assertEqual((v["住民税_均等割の非課税の基本額"].value, v["住民税_均等割の非課税の加算額"].value), (315_000, 189_000))
        self.assertEqual((v["住民税_森林環境税の非課税の基本額"].value, v["住民税_森林環境税の非課税の加算額"].value), (315_000, 189_000))

    def test_missing_rates_mark_undetermined(self) -> None:
        out = inputs.build_inputs(self._ctx(None))
        v = {k[0]: iv for k, iv in out.values.items()}
        self.assertEqual(v["住民税_市町村民税の所得割の税率の分子"].value, 0)
        self.assertTrue(v["住民税_市町村民税の所得割の税率の分子"].missing)
        self.assertTrue(v["住民税_市町村民税の均等割の税率"].missing)

    def test_designation_of_the_donee_is_an_injection_slot(self) -> None:
        # 特例控除対象寄附金（第314条の7第2項）：寄附先の団体ごと・寄附をした日の注入点。値が「指定」なら特例控除の対象、
        # 団体コードがない寄附は未確定（決める手段＝事実）
        ctx = self._ctx({"税率": {"num": 6, "den": 100}, "指定都市": False})
        don = lambda i, code: {  # noqa: E731
            "id": f"d{i}", "kind": "donation", "roles": {"donor": "a"}, "when": {"on": "2026-06-01"}, "amounts": {"amount": 30000},
            "attributes": {"recipient_name": f"架空{i}", "recipient_type": "local_government",
                           **({"recipient_local_government_code": code, "recipient_local_government_kind": "municipality"} if code else {})},
        }
        ctx.ir["facts"].extend([don(1, "990011"), don(2, "990012")])
        slots = inputs._designation_slots(ctx)
        self.assertEqual([s.issuer_code for s in slots], ["990011", "990012"])
        for code, flag in (("990011", True), ("990012", False)):
            ctx._decided[(injection_kind(inputs.P_DESIGNATION), injection_key("municipality", code, _dt.date(2026, 6, 1)))] = Decided({"指定": flag}, (f"inj-{code}",), frozenset(), False)
        ctx._decided[(inputs.C_ONESTOP, "a:2026")] = Decided(False, (), frozenset(), False)
        v = {k[0]: iv for k, iv in inputs.build_inputs(ctx).values.items()}
        self.assertEqual(v["住民税_都道府県等に対する寄附金の額"].value, 60000)
        self.assertEqual(v["住民税_特例控除対象寄附金の額"].value, 30000)
        self.assertEqual(v["住民税_特例控除対象寄附金の額"].missing, ())
        ctx.ir["facts"].append(don(3, None))
        v = {k[0]: iv for k, iv in inputs.build_inputs(ctx).values.items()}
        self.assertEqual([s.means for s in v["住民税_特例控除対象寄附金の額"].missing], [Means.FACT])

    def test_resident_return_choice_voids_onestop(self) -> None:
        # 附則第7条第13項第2号（[JTL] §8.3）：その年度分の住民税の申告書を提出すれば申告特例はなかったものとみなす。
        # 選択.住民税の申告 は申告特例を求めた人だけ読み、提出の記録がある人には1か所を置かない（2026-11-12：JM-39）
        ctx = self._ctx({"税率": {"num": 6, "den": 100}, "指定都市": False})
        ctx.ir["facts"].append({
            "id": "d1", "kind": "donation", "roles": {"donor": "a"}, "when": {"on": "2026-06-01"}, "amounts": {"amount": 30000},
            "attributes": {"recipient_name": "架空1", "recipient_type": "local_government",
                           "recipient_local_government_code": "990011", "recipient_local_government_kind": "municipality"},
        })
        ctx._decided[(injection_kind(inputs.P_DESIGNATION), injection_key("municipality", "990011", _dt.date(2026, 6, 1)))] = Decided({"指定": True}, (), frozenset(), False)
        ctx._decided[(inputs.C_ONESTOP, "a:2026")] = Decided(True, ("c-os",), frozenset(), False)
        slots = inputs.resident_return_slots(ctx)
        self.assertEqual([(s.key, s.lazy) for s in slots], [("a:2027", True)])
        choice = {"id": "c-rr", "kind": "選択.住民税の申告", "subject": {"person": "a"}, "when": {"fiscal_year": 2027},
                  "value": {"file_resident_tax_return": True}}
        self.assertTrue(slots[0].matches(choice))
        self.assertFalse(slots[0].matches({**choice, "when": {"fiscal_year": 2026}}))
        self.assertFalse(slots[0].matches({**choice, "value": {"collection_method_other_income": "ordinary_collection"}}))
        for filed, expected in ((False, True), (True, False)):
            ctx._decided[(inputs.C_RESIDENT_RETURN, "a:2027")] = Decided(filed, ("c-rr",), frozenset(), False)
            v = {k[0]: iv for k, iv in inputs.build_inputs(ctx).values.items()}
            self.assertEqual(v["住民税_申告特例控除の対象か"].value, expected)
            self.assertIn("c-rr", v["住民税_申告特例控除の対象か"].record_ids)
        ctx.ir["filed_documents"].append({"id": "f1", "kind": "filed_document", "roles": {"filer": "a"}, "when": {"on": "2027-03-01"},
                                          "attributes": {"document_type": "resident_tax_return", "recipient": "municipality", "fiscal_year": 2027}})
        self.assertEqual(inputs.resident_return_slots(ctx), [])

    def test_authority_decision_sets_taxing_municipality(self) -> None:
        # 第294条第3項・第4項（[PS3-JM] §1.3）：住民票と違う市町村での課税の決定は、その年度の住所の市町村にする（2026-11-12：JM-38）
        ctx = self._ctx({"税率": {"num": 6, "den": 100}, "指定都市": False})
        dec = {"id": "ad1", "kind": "authority_decision", "roles": {"person": "a"}, "when": {"fiscal_year": 2027},
               "attributes": {"decision": "taxation_at_non_resident_record_municipality", "authority": "municipality", "tax_item": "resident_tax",
                              "municipality_code": "990002"}}
        ctx.ir["facts"].append(dec)
        d = inputs.domicile_on(ctx, "a", _dt.date(2027, 1, 1), 2027)
        self.assertEqual((d.code, d.record_ids, d.conflict), ("990002", ("ad1",), None))
        self.assertEqual(inputs.domicile_on(ctx, "a", _dt.date(2026, 1, 1), 2026).code, "990001")  # ほかの年度は住民票
        del dec["attributes"]["municipality_code"]
        self.assertEqual(inputs.domicile_on(ctx, "a", _dt.date(2027, 1, 1), 2027).conflict, inputs.AUTHORITY_DECISION_REASON)
        # 2026-11-12 の2回目（JM-40）：記録の宣言は税目（tax_item）で絞る。国保の処分は kokuho
        kinds = [k for k in inputs.RECORD_KINDS if not isinstance(k, str) and k.kind == "authority_decision"]
        self.assertTrue(kinds[0].matches({**dec, "attributes": {"decision": "taxation_at_non_resident_record_municipality", "tax_item": "resident_tax"}}))
        self.assertTrue(kinds[0].matches({**dec, "attributes": {"decision": "reduction_approved", "tax_item": "resident_tax"}}))
        self.assertFalse(kinds[0].matches({**dec, "attributes": {"decision": "reduction_approved", "tax_item": "national_health_insurance"}}))

    def test_resident_tax_reduction_is_read_by_tax_item(self) -> None:
        # 第323条・第45条（[PS8] §8）：住民税の減免の承認は、税目 resident_tax・その年度のものだけ（2026-11-12：JM-40）
        ctx = self._ctx({"税率": {"num": 6, "den": 100}, "指定都市": False})
        base = {"kind": "authority_decision", "roles": {"person": "a"}, "when": {"fiscal_year": 2027}}
        ctx.ir["facts"] += [
            {**base, "id": "ad-r", "attributes": {"decision": "reduction_approved", "authority": "municipality", "tax_item": "resident_tax"}},
            {**base, "id": "ad-k", "attributes": {"decision": "reduction_approved", "authority": "municipality", "tax_item": "national_health_insurance"}},
            {**base, "id": "ad-old", "when": {"fiscal_year": 2026}, "attributes": {"decision": "reduction_approved", "authority": "municipality", "tax_item": "resident_tax"}},
        ]
        self.assertEqual([r["id"] for r in inputs.reduction_records(ctx, "a", 2027)], ["ad-r"])

    def test_ordinance_donations_by_entity(self) -> None:
        # [JM3]§1：第3号・第4号は住所の市町村・道府県の条例（注入データの寄附先の名称）。道府県は未注入なら未確定（決める手段＝注入）
        ctx = self._ctx({"税率": {"num": 6, "den": 100}, "指定都市": False})
        ctx.ir["facts"].append({
            "id": "d9", "kind": "donation", "roles": {"donor": "a"}, "when": {"on": "2026-06-01"}, "amounts": {"amount": 20000},
            "attributes": {"recipient_name": "架空NPO", "recipient_type": "certified_npo"},
        })
        jan1 = _dt.date(2027, 1, 1)
        split = Split(id="注入:県", means=Means.INJECTION, target={}, candidates=(), splits_conclusion=True)
        ctx._decided[(injection_kind(inputs.P_JOREI), injection_key("municipality", "990001", jan1))] = Decided({"寄附先の名称": ["架空NPO"]}, ("inj-j",), frozenset(), False)
        ctx._decided[(injection_kind(inputs.P_JOREI), injection_key("prefecture", "990001", jan1))] = Decided(None, (), frozenset(), False, missing=(split,))
        self.assertEqual([s.issuer_code for s in inputs._jorei_slots(ctx)], ["990001", "990001"])
        v = {k[0]: iv for k, iv in inputs.build_inputs(ctx).values.items()}
        m, p = v["住民税_市町村民税の第2号から第4号までの寄附金の額"], v["住民税_道府県民税の第2号から第4号までの寄附金の額"]
        self.assertEqual((m.value, m.missing), (20000, ()))
        self.assertEqual((p.value, [s.means for s in p.missing]), (0, [Means.INJECTION]))

    def test_chest_and_red_cross_second_item(self) -> None:
        # [KIFU4]§1 施行令第48条の8 → 第7条の17、法第314条の7第1項第2号の所在の条件（仮説 H10、推測 I9）
        q = inputs.chest_qualifies
        home = "990001"
        chest = lambda **a: {"recipient_type": "community_chest", "recipient_office_prefecture_code": home, **a}  # noqa: E731
        red = lambda **a: {"recipient_type": "japanese_red_cross", "recipient_office_prefecture_code": home, **a}  # noqa: E731
        # 第1号：承認を受けた募集の共同募金会への寄附金は当たる（例：告示383号の令和8年10月〜の共同募金：§1.1）
        self.assertEqual(q(chest(mic_approved_solicitation=True), home), (True, ()))
        # 承認でない・記載なし：第2号（総務大臣が定めるもの）の告示が docs にない（§3）→ 一次情報の分かれ目（記載なしは事実も）
        self.assertEqual(q(chest(mic_approved_solicitation=False), home), (None, (inputs.CHEST_OPEN_SECOND,)))
        self.assertEqual(q(chest(), home), (None, (inputs.CHEST_OPEN_SECOND, inputs.CHEST_OPEN_APPROVAL)))
        # 第3号：日本赤十字社は承認の募集だけ（偽なら当たらない、記載なしは事実の分かれ目）
        self.assertEqual(q(red(mic_approved_solicitation=True), home), (True, ()))
        self.assertEqual(q(red(mic_approved_solicitation=False), home), (False, ()))
        self.assertEqual(q(red(), home), (None, (inputs.CHEST_OPEN_APPROVAL,)))
        # 所在の道府県：住所の道府県の外は当たらない（承認によらない）、記載なしは事実の分かれ目
        self.assertEqual(q(chest(mic_approved_solicitation=True, recipient_office_prefecture_code="980005"), home), (False, ()))
        self.assertEqual(q({"recipient_type": "japanese_red_cross", "mic_approved_solicitation": True}, home), (None, (inputs.CHEST_OPEN_PREFECTURE,)))

    def test_chest_amounts_and_splits(self) -> None:
        # [KIFU4]§1：決まった寄附金は分かれ目なし、決まらない寄附金は額を当たる候補で書き、一次情報・事実の分かれ目を分ける
        ctx = self._ctx({"税率": {"num": 6, "den": 100}, "指定都市": False})
        pref = inputs.issuer_code("prefecture", "990001")
        don = lambda i, kind, amount, **a: {  # noqa: E731
            "id": f"c{i}", "kind": "donation", "roles": {"donor": "a"}, "when": {"on": "2026-11-10"}, "amounts": {"amount": amount},
            "attributes": {"recipient_name": f"架空{i}", "recipient_type": kind, "recipient_office_prefecture_code": pref, **a},
        }
        ctx.ir["facts"].extend([don(1, "community_chest", 10000, mic_approved_solicitation=True), don(2, "japanese_red_cross", 5000, mic_approved_solicitation=False)])
        v = {k[0]: iv for k, iv in inputs.build_inputs(ctx).values.items()}
        m = v["住民税_市町村民税の第2号から第4号までの寄附金の額"]
        self.assertEqual((m.value, m.missing), (10000, ()))
        ctx.ir["facts"].append(don(3, "community_chest", 3000))
        v = {k[0]: iv for k, iv in inputs.build_inputs(ctx).values.items()}
        m = v["住民税_市町村民税の第2号から第4号までの寄附金の額"]
        self.assertEqual(m.value, 13000)
        self.assertEqual(sorted((s.means.value, tuple(s.target["寄附金"])) for s in m.missing), [("一次情報", ("c3",)), ("事実", ("c3",))])
        # 第2号の額だけの入力（第二表の欄を分ける）：同じ額・同じ分かれ目
        second = v["住民税_第2号の寄附金の額"]
        self.assertEqual((second.value, second.missing), (13000, m.missing))

    def test_withholding_account_local_tax(self) -> None:
        # [EXTRA]§2.1 第314条の9：源泉徴収選択口座で申告した配当の配当割額（年間取引報告書の dividend_local_tax）は控除の対象。欄がなければ未確定（事実）
        ctx = self._ctx({"税率": {"num": 6, "den": 100}, "指定都市": False})
        rec = {"id": "b1", "kind": "brokerage_annual", "roles": {"holder": "a"}, "when": {"tax_year": 2026},
               "amounts": {"dividends_received": 100000, "withholding_tax": 20315, "dividend_local_tax": 5000},
               "attributes": {"account_id": "acc1", "withholding_elected": True}}
        ctx.ir["facts"].append(rec)
        ctx._decided[(inputs.C_STOCK, "a:配当:acc1")] = Decided({"declare": True}, (), frozenset(), False)
        v = {k[0]: iv for k, iv in inputs.build_inputs(ctx).values.items()}
        self.assertEqual((v["住民税_控除の対象の配当割額等"].value, v["住民税_控除の対象の配当割額等"].missing), (5000, ()))
        del rec["amounts"]["dividend_local_tax"]
        v = {k[0]: iv for k, iv in inputs.build_inputs(ctx).values.items()}
        self.assertEqual([s.means for s in v["住民税_控除の対象の配当割額等"].missing], [Means.FACT])

    def test_housing_version(self) -> None:
        # [EXTRA]§3.2：加算は居住年 平成28年〜令和7年、特定取得の読替えは平成26年〜令和3年（区分の記載がなければ None）
        self.assertEqual(inputs.housing_version(2015, "specified_acquisition"), (False, True))
        self.assertEqual(inputs.housing_version(2016, None), (True, None))
        self.assertEqual(inputs.housing_version(2021, "other"), (True, False))
        self.assertEqual(inputs.housing_version(2022, None), (True, False))
        self.assertEqual(inputs.housing_version(2013, None), (False, False))


class TestFormDonationFields(unittest.TestCase):
    """確定申告書 第二表「住民税に関する事項」の寄附の4欄の式（2026-11-12）。

    [FKIFU] docs/public-sources/20261112_impl-research6_forms-jumin-kifu.md §1・§2（令和7年分 確定申告の手引き 手順6 の記載例）。上流の寄附金の額は入力で与える。
    """

    def test_fields_from_the_tebiki_example(self) -> None:
        # [FKIFU]§2 の記載例：①②ふるさと納税 120,000（指定あり）、③日赤 90,000・④共同募金 20,000（第2号）、⑤県の条例 55,000、⑥県・市の両方の条例 15,000
        # → a 120,000、b 110,000、c 70,000、d 15,000。b は「総務大臣の指定がない団体への寄附」10,000 を足した人（x）も確かめる（A ではなく B）
        def p_(local: int, special: int, second: int, muni: int, pref: int) -> dict[str, Any]:
            return {
                "住民税_都道府県等に対する寄附金の額": {"2025": local},
                "住民税_特例控除対象寄附金の額": {"2025": special},
                "住民税_第2号の寄附金の額": {"2025": second},
                "住民税_市町村民税の第2号から第4号までの寄附金の額": {"2025": muni},
                "住民税_道府県民税の第2号から第4号までの寄附金の額": {"2025": pref},
            }

        people = {"ex": p_(120_000, 120_000, 110_000, 110_000 + 15_000, 110_000 + 70_000), "x": p_(130_000, 120_000, 110_000, 110_000, 110_000)}
        sim = SimulationBuilder().build_from_entities(system(), {"人物一覧": people})
        got = {
            name: list(sim.calculate(f"住民税_第二表の{name}", "2025"))
            for name in ("特例控除対象の寄附金の額", "共同募金日赤その他の寄附金の額", "都道府県条例指定寄附の額", "市区町村条例指定寄附の額")
        }
        self.assertEqual(got["特例控除対象の寄附金の額"], [120_000, 120_000])
        self.assertEqual(got["共同募金日赤その他の寄附金の額"], [110_000, 120_000])  # x：指定のない団体 10,000 が B に回る
        # 第2号（共同募金・日赤）は市町村民税・道府県民税の両方の第2号〜第4号の額に入っているので、両方の条例の欄から引く
        self.assertEqual(got["都道府県条例指定寄附の額"], [70_000, 0])
        self.assertEqual(got["市区町村条例指定寄附の額"], [15_000, 0])


if __name__ == "__main__":
    unittest.main()

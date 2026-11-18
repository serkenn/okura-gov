"""規則モジュール tax（rules/tax/）のテスト：所得控除の合計・課税所得・税額・精算・申告の要否・期限（D15 ①②）。

上流の概念（総所得金額・各控除の額など）は入力として与えて単独で確かめる（packages/core/README.md §10。上流が実装されても入力で上書きできる）。
テストのデータはどれも架空の金額・架空の人（個人の情報を使わない）。

期待値の出典（docs のファイルと節）：
  [ZG] docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md、[ZE] docs/inferences/20261109_impl-prep_zeigaku-examples.md、
  [MZ] docs/measurements/20261109_impl-prep_zeigaku-fetch.md §6（ZE の手計算の検算）、
  [TA] docs/public-sources/20261109_round2b_taishoku-laws-and-guidance.md §4.2、
  [SS] docs/public-sources/20261109_round3_shibo-shukkoku-laws-and-nta.md、[MS] docs/measurements/20261109_round3_shibo-shukkoku-fetch-and-calc.md §4。
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import unittest
from fractions import Fraction
from typing import Any

import numpy as np
from openfisca_core.simulation_builder import SimulationBuilder

from okura_core import evaluate
from okura_core.basis import BasisType, SourceKind
from okura_core.registry import BasisContext, CheckContext
from okura_core.result import OutOfScopeCategory, State, TimeKey, YenAmount, check_result_json
from okura_core.rounding import floor_yen
from okura_core.rules.tax import calc
from okura_core.rules.tax.basis import BASIS, RULES
from okura_core.rules.tax.calc import (
    allocate_deductions,
    brackets_from_parameters,
    calendar_from_parameters,
    death_deadline,
    filing_obligation,
    fukko_tax,
    months_later_expiry,
    next_open_day,
    normal_deadline,
    progressive_tax,
    settle,
    shinkoku_nozei_field,
    substitute_holidays,
)
from okura_core.rules.tax.checks import filing_obligation_undetermined
from okura_core.rules.tax.inputs import KIND_ABROAD, KIND_DEATH, KIND_DEATH_UNDETERMINED, KIND_DEPARTURE, KIND_NORMAL
from okura_core.rules.tax.variables import UNKNOWN_DEADLINE

from .support import make_ir, make_query, person, salary, system

T25 = TimeKey("tax_year", 2025)
T26 = TimeKey("tax_year", 2026)

DEDUCTIONS = (
    "所得税_雑損控除の額",
    "所得税_医療費控除の額",
    "所得税_セルフメディケーション税制による医療費控除の額",
    "所得税_社会保険料控除の額",
    "所得税_小規模企業共済等掛金控除の額",
    "所得税_生命保険料控除の額",
    "所得税_地震保険料控除の額",
    "所得税_寄附金控除の額",
    "所得税_障害者控除の額",
    "所得税_寡婦控除の額",
    "所得税_ひとり親控除の額",
    "所得税_勤労学生控除の額",
    "所得税_配偶者控除の額",
    "所得税_配偶者特別控除の額",
    "所得税_扶養控除の額",
    "所得税_特定親族特別控除の額",
    "所得税_基礎控除の額",
)

#: 上流の概念の値（0）。上流が実装済みでも入力で上書きして、このモジュールの式だけを確かめる。
UPSTREAM_ZERO: dict[str, Any] = {
    "所得税_総所得金額": 0,
    "所得税_申告分離課税の上場株式等に係る配当所得等の金額": 0,
    "所得税_申告分離課税の上場株式等に係る譲渡所得等の金額": 0,
    "所得税_退職所得金額": 0,
    "所得税_配当所得の金額": 0,
    "所得税_給与等の収入金額": 0,
    "所得税_公的年金等の収入金額": 0,
    "所得税_政党等寄附金特別控除等の額": 0,
    "所得税_源泉徴収税額": 0,
    "所得税_予定納税額": 0,
    "所得税_住宅借入金等特別控除の額": 0,
    "所得税_申告の種類": KIND_NORMAL,
    "所得税_相続の開始があったことを知った日": "1970-01-01",
}


def sim(year: int, **inputs: Any):
    """1人分の simulation。deductions を含め上流の値は全部入力で与える（部分は UPSTREAM_ZERO で埋める）。"""
    period = str(year)
    values = {**UPSTREAM_ZERO, **inputs}
    person_data = {k: {period: v} for k, v in values.items()}
    return SimulationBuilder().build_from_entities(system(), {"人物一覧": {"p": person_data}})


def value(s, var: str, year: int) -> int:
    return int(s.calculate(var, str(year))[0])


def _ok(res):
    if not res.ok:
        raise AssertionError(res.to_dict())
    problems = check_result_json(res.to_dict())
    if problems:
        raise AssertionError(problems)
    return res


def params(year: int):
    return system().get_parameters_at_instant(f"{year}-01-01")


def calendars(*years: int) -> dict[int, calc.Calendar]:
    return {y: calendar_from_parameters(y, params(y).所得税.休日) for y in years}


# ---------------------------------------------------------------------------
# 税率（所得税法第89条第1項）：境目の前後。期待値は国税庁の速算表（[ZG] §2：TA2260・手引き p.24）で検算した値
# ---------------------------------------------------------------------------


class TestProgressiveTax(unittest.TestCase):
    #: (課税総所得金額, 税額)。[ZG] §2 の速算表の「率 × 課税所得 − 控除額」と一致する。
    CASES = (
        (0, 0),
        (1_000, 50),
        (1_949_000, 97_450),  # 速算表の第1段の上端の千円下
        (1_950_000, 97_500),  # 195万円以下：5%
        (1_951_000, 97_600),  # 195万円超の部分に10%（1,951,000×10%−97,500）
        (3_299_000, 232_400),
        (3_300_000, 232_500),
        (3_301_000, 232_700),  # 3,301,000×20%−427,500
        (6_949_000, 962_300),
        (6_950_000, 962_500),
        (6_951_000, 962_730),  # 6,951,000×23%−636,000
        (8_999_000, 1_433_770),
        (9_000_000, 1_434_000),
        (9_001_000, 1_434_330),  # 9,001,000×33%−1,536,000
        (17_999_000, 4_403_670),
        (18_000_000, 4_404_000),
        (18_001_000, 4_404_400),  # 18,001,000×40%−2,796,000
        (39_999_000, 13_203_600),
        (40_000_000, 13_204_000),
        (40_001_000, 13_204_450),  # 40,001,000×45%−4,796,000
    )
    #: 速算表の控除額（[ZG] §2）。
    QUICK = ((1_950_000, 5, 0), (3_300_000, 10, 97_500), (6_950_000, 20, 427_500), (9_000_000, 23, 636_000), (18_000_000, 33, 1_536_000), (40_000_000, 40, 2_796_000))

    def _brackets(self, year: int):
        return brackets_from_parameters(params(year).所得税.税率)

    def test_boundaries_r7_r8(self) -> None:
        for year in (2025, 2026):
            brackets = self._brackets(year)
            for base, expected in self.CASES:
                with self.subTest(year=year, base=base):
                    self.assertEqual(progressive_tax(base, brackets)[0], expected)

    def test_matches_quick_table(self) -> None:
        brackets = self._brackets(2026)
        lower = 0
        for upper, rate, ded in self.QUICK:
            for base in (lower + 1_000, upper - 1_000, upper):
                self.assertEqual(progressive_tax(base, brackets)[0], Fraction(base * rate, 100) - ded, base)
            lower = upper
        self.assertEqual(progressive_tax(50_000_000, brackets)[0], Fraction(50_000_000 * 45, 100) - 4_796_000)

    def test_taishoku_examples(self) -> None:
        """退職所得の税額の設例（[TA] §4.2：TA2732。所得税の部分）。"""
        brackets = self._brackets(2026)
        self.assertEqual(progressive_tax(1_800_000, brackets)[0], 90_000)  # 180万円 × 5%
        self.assertEqual(progressive_tax(4_000_000, brackets)[0], 372_500)  # 400万円 × 20% − 427,500
        self.assertEqual(progressive_tax(7_000_000, brackets)[0], 974_000)  # 700万円 × 23% − 636,000

    def test_used_brackets(self) -> None:
        brackets = self._brackets(2026)
        self.assertEqual(progressive_tax(0, brackets)[1], ())
        self.assertEqual([b.number for b in progressive_tax(1_950_000, brackets)[1]], [1])
        self.assertEqual([b.number for b in progressive_tax(1_951_000, brackets)[1]], [1, 2])
        self.assertEqual([b.number for b in progressive_tax(50_000_000, brackets)[1]], [1, 2, 3, 4, 5, 6, 7])

    def test_rejects_negative_and_non_integer_results(self) -> None:
        with self.assertRaises(ValueError):
            progressive_tax(-1, self._brackets(2026))
        with self.assertRaises(ValueError):  # 千円未満の端数が残っていれば税額が整数にならない（課税標準の切捨て忘れを止める）
            progressive_tax(1_001 + 9, (calc.Bracket(1, None, Fraction(5, 100)),))


# ---------------------------------------------------------------------------
# 所得控除の当て方と課税標準（所得税法第87条第2項・第89条第2項、通則法第118条第1項）
# ---------------------------------------------------------------------------


class TestAllocation(unittest.TestCase):
    def test_thousand_floor_boundary(self) -> None:
        """[ZG] §1.2：千円未満の端数は切捨て、全額が千円未満なら0。手引き p.24（§1.3）：赤字も0。"""
        for income, deduction, expected in (
            (1_000, 0, 1_000),
            (999, 0, 0),
            (1_999, 0, 1_000),
            (2_000, 0, 2_000),
            (1_000, 1, 0),  # 差引 999
            (100, 200, 0),  # 赤字
            (1_160_000, 1_040_000, 120_000),  # [ZE] Z2
        ):
            with self.subTest(income=income, deduction=deduction):
                self.assertEqual(allocate_deductions(income, 0, 0, 0, deduction, 1000).総所得, expected)

    def test_order_total_then_retirement(self) -> None:
        """[ZG] §1.1（第87条第2項）：総所得金額 → 退職所得金額の順。総所得金額で控除しきれない分を退職所得金額から控除する。"""
        a = allocate_deductions(100_000, 0, 0, 1_000_000, 300_000, 1000)
        self.assertEqual((a.総所得, a.退職), (0, 800_000))
        b = allocate_deductions(1_000_000, 0, 0, 1_000_000, 300_000, 1000)
        self.assertEqual((b.総所得, b.退職), (700_000, 1_000_000))

    def test_stock_income_comes_before_retirement(self) -> None:
        """[kabu] §1.3（第87条の「総所得金額」の読替え）：総所得金額の直後に上場株式等に係る所得が入る。"""
        a = allocate_deductions(0, 200_000, 0, 1_000_000, 300_000, 1000)
        self.assertEqual((a.配当, a.退職), (0, 900_000))
        self.assertFalse(a.stock_order_matters)

    def test_stock_order_matters(self) -> None:
        a = allocate_deductions(0, 500_000, 500_000, 0, 200_000, 1000)
        self.assertTrue(a.stock_order_matters)
        one_only = allocate_deductions(0, 500_000, 0, 0, 200_000, 1000)
        self.assertFalse(one_only.stock_order_matters)
        self.assertEqual(one_only.配当, 300_000)
        # 控除が2つを覆えば順序によらない
        covered = allocate_deductions(0, 500_000, 500_000, 0, 1_500_000, 1000)
        self.assertFalse(covered.stock_order_matters)
        self.assertEqual((covered.配当, covered.譲渡), (0, 0))
        # 控除がなければ順序によらない
        self.assertFalse(allocate_deductions(0, 500_000, 500_000, 0, 0, 1000).stock_order_matters)

    def test_negative_bases_are_zero(self) -> None:
        a = allocate_deductions(-100_000, 0, 0, 50_000, 10_000, 1000)
        self.assertEqual((a.総所得, a.退職), (0, 40_000))

    def test_rejects_bad_input(self) -> None:
        with self.assertRaises(ValueError):
            allocate_deductions(0, 0, 0, 0, -1, 1000)
        with self.assertRaises(TypeError):
            allocate_deductions(0.5, 0, 0, 0, 0, 1000)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 精算（手引きの順：[ZG] §3.3、通則法第119条・第120条、復興法第24条）
# ---------------------------------------------------------------------------


class TestSettlement(unittest.TestCase):
    def test_hundred_yen_floor_boundary(self) -> None:
        for total, expected in ((99, 0), (100, 100), (199, 100), (200, 200), (6_126, 6_100)):  # [ZE] Z3：6,126 → 6,100
            with self.subTest(total=total):
                self.assertEqual(settle(total, 0, 0, 100).申告納税額, expected)

    def test_refund_of_withholding(self) -> None:
        # [ZE] Z1：税額0、源泉徴収税額40,000 → 還付 40,000
        s = settle(0, 40_000, 0, 100)
        self.assertEqual((s.申告納税額, s.第3期分, s.還付), (0, 0, 40_000))
        # [ZE] Z2：6,126 − 101,260 → 還付 95,134
        self.assertEqual(settle(6_126, 101_260, 0, 100).還付, 95_134)
        # [ZE] Z5-R7（手引きの順）：6,177 − 101,260 → 還付 95,083（[MZ] §6）
        self.assertEqual(settle(6_177, 101_260, 0, 100).還付, 95_083)

    def test_prepayment(self) -> None:
        # 第3期分＝申告納税額 − 予定納税額（[ZG] §3.3）
        s = settle(100_000, 20_000, 30_000, 100)
        self.assertEqual((s.申告納税額, s.第3期分, s.還付), (80_000, 50_000, 0))
        # 予定納税額が申告納税額を超える：赤字は還付
        s = settle(100_000, 20_000, 90_000, 100)
        self.assertEqual((s.申告納税額, s.第3期分, s.還付), (80_000, 0, 10_000))

    def test_refund_uses_floored_filing_tax_in_the_guide_order(self) -> None:
        """黒字の申告納税額は百円未満を切り捨ててから予定納税額を引く（手引き ㊿ → 51 → 52・53）。"""
        s = settle(10_050, 0, 10_100, 100)
        self.assertEqual((s.申告納税額, s.第3期分, s.還付), (10_000, 0, 100))

    def test_withholding_excess_and_prepayment_are_both_refunded(self) -> None:
        # 赤字の申告納税額（㊿）はそのまま：還付 ＝ 予定納税額 ＋ 控除しきれない源泉徴収税額
        s = settle(1_000, 5_000, 2_000, 100)
        self.assertEqual((s.申告納税額, s.第3期分, s.還付), (0, 0, 6_000))

    def test_field_value_of_filing_tax_keeps_the_deficit(self) -> None:
        """2026-11-13：第一表 ㊿ の欄は赤字をそのまま書く（申告納税額は0。作成コーナーとの照合 A01・C01 の -61231・-7760）。黒字は百円未満切捨て。"""
        self.assertEqual(shinkoku_nozei_field(81_169, 142_400, 100), -61_231)
        self.assertEqual(shinkoku_nozei_field(104_550, 112_310, 100), -7_760)
        self.assertEqual(shinkoku_nozei_field(212_776, 204_200, 100), 8_500)
        self.assertEqual(shinkoku_nozei_field(5_000, 5_000, 100), 0)

    def test_exact_zero(self) -> None:
        s = settle(5_000, 5_000, 0, 100)
        self.assertEqual((s.申告納税額, s.第3期分, s.還付), (0, 0, 0))

    def test_rejects_negative(self) -> None:
        with self.assertRaises(ValueError):
            settle(-1, 0, 0, 100)


# ---------------------------------------------------------------------------
# 復興特別所得税
# ---------------------------------------------------------------------------


class TestFukko(unittest.TestCase):
    RATE = Fraction(21, 1000)

    def test_rate_is_parameter(self) -> None:
        for y in (2025, 2026):
            p = params(y).所得税.復興特別所得税.税率
            self.assertEqual((p.分子, p.分母), (21, 1000))  # [ZG] §3.1 第13条、§3.2 附則88①：令和8年分以前は 2.1%

    def test_handbook_example(self) -> None:
        # [ZG] §3.3（手引き p.27 の設例）：176,500円 × 0.021 ＝ 3,706円（1円未満切捨て）
        self.assertEqual(fukko_tax(176_500, self.RATE, floor_yen), 3_706)

    def test_z5_rounding_candidates(self) -> None:
        # [MZ] §6・[ZE] Z5-R7：6,050 × 2.1% ＝ 127.05
        self.assertEqual(fukko_tax(6_050, self.RATE, calc.FUKKO_TEBIKI_FLOOR_R7.apply), 127)
        self.assertEqual(fukko_tax(6_050, self.RATE, lambda x: int(x) + 1 if x != int(x) else int(x)), 128)

    def test_r7_uses_handbook_floor_and_is_marked_as_handbook(self) -> None:
        s = sim(2025, 所得税_基準所得税額=6_050)
        self.assertEqual(value(s, "所得税_復興特別所得税額", 2025), 127)
        entry = BASIS["所得税_復興特別所得税額"](self._ctx(s, 2025))
        rounding = [b for b in entry if b.type is BasisType.ROUNDING]
        self.assertEqual([b.source_kind for b in rounding], [SourceKind.GUIDE_OR_FORM_NOTE])
        self.assertEqual(rounding[0].name, "floor_yen_fukko_tokubetsu_shotokuzei_tebiki_r7")

    def test_r8_uses_circular_floor_with_reading_flag(self) -> None:
        # 令和8年分：国税通則法基本通達第119条関係6 の切捨て（docs/public-sources/20261111_impl-research_hasu-tebiki-and-nta.md §5）。候補の入力によらない
        for candidate in ("floor", "ceil", "half_up"):
            with self.subTest(candidate=candidate):
                s = sim(2026, 所得税_基準所得税額=6_050, 所得税_復興特別所得税額の端数の候補=candidate)
                self.assertEqual(value(s, "所得税_復興特別所得税額", 2026), 127)
        entry = BASIS["所得税_復興特別所得税額"](self._ctx(sim(2026, 所得税_基準所得税額=6_000), 2026))
        rounding = [b for b in entry if b.type is BasisType.ROUNDING]
        self.assertEqual([b.source_kind for b in rounding], [SourceKind.CIRCULAR])
        self.assertEqual(rounding[0].name, "floor_yen_fukko_tokubetsu_shotokuzei_tsutatsu_r8")

    def test_no_fraction_is_same_for_all_candidates(self) -> None:
        for candidate in ("floor", "ceil", "half_up"):
            s = sim(2026, 所得税_基準所得税額=6_000, 所得税_復興特別所得税額の端数の候補=candidate)  # [ZE] Z2：6,000 × 2.1% ＝ 126
            self.assertEqual(value(s, "所得税_復興特別所得税額", 2026), 126)

    def _ctx(self, s, year: int) -> BasisContext:
        sys_ = system()
        return BasisContext(year, f"{year}-01-01", sys_.parameters, params(year), lambda v: s.calculate(v, str(year)), 0, "p")


# ---------------------------------------------------------------------------
# 変数をつないだ計算例（[ZE] の設例）
# ---------------------------------------------------------------------------


class TestWorkedExamples(unittest.TestCase):
    def _chain(self, year: int, **inputs: Any):
        return sim(year, 所得税_復興特別所得税額の端数の候補="floor", **inputs)

    def test_z1_r8_refund_only(self) -> None:
        # [ZE] Z1（令和8年分）：総所得 660,000、控除 1,310,000、源泉 40,000 → 課税 0、還付 40,000、義務なし、還付申告できる
        s = self._chain(2026, 所得税_総所得金額=660_000, 所得税_所得控除の合計=1_310_000, 所得税_源泉徴収税額=40_000, 所得税_給与等の収入金額=1_400_000)
        self.assertEqual(value(s, "所得税_課税総所得金額", 2026), 0)
        self.assertEqual(value(s, "所得税_算出税額", 2026), 0)
        self.assertEqual(value(s, "所得税_還付される税額", 2026), 40_000)
        self.assertFalse(s.calculate("所得税_確定申告書の提出義務があるか", "2026")[0])
        self.assertTrue(s.calculate("所得税_還付申告ができるか", "2026")[0])

    def test_z1_r7(self) -> None:
        # [ZE] Z1-R7（令和7年分）：総所得 750,000、控除 1,220,000 → 課税 0、還付 40,000
        s = self._chain(2025, 所得税_総所得金額=750_000, 所得税_所得控除の合計=1_220_000, 所得税_源泉徴収税額=40_000)
        self.assertEqual(value(s, "所得税_課税総所得金額", 2025), 0)
        self.assertEqual(value(s, "所得税_還付される税額", 2025), 40_000)

    def test_z2_refund_excess_withholding(self) -> None:
        # [ZE] Z2（令和8年分）：総所得 1,160,000、控除 1,040,000 → 課税 120,000、税 6,000、復興 126、還付 95,134、A 真・B 真で義務なし
        s = self._chain(2026, 所得税_総所得金額=1_160_000, 所得税_所得控除の合計=1_040_000, 所得税_源泉徴収税額=101_260, 所得税_給与等の収入金額=1_400_000)
        self.assertEqual(value(s, "所得税_課税総所得金額", 2026), 120_000)
        self.assertEqual(value(s, "所得税_課税総所得金額に対する税額", 2026), 6_000)
        self.assertEqual(value(s, "所得税_基準所得税額", 2026), 6_000)
        self.assertEqual(value(s, "所得税_復興特別所得税額", 2026), 126)
        self.assertEqual(value(s, "所得税_所得税及び復興特別所得税の額", 2026), 6_126)
        self.assertEqual(value(s, "所得税_還付される税額", 2026), 95_134)
        self.assertFalse(s.calculate("所得税_確定申告書の提出義務があるか", "2026")[0])

    def test_z3_payment(self) -> None:
        # [ZE] Z3（令和8年分）：源泉 0 → 申告納税額 6,100（百円未満切捨て）
        s = self._chain(2026, 所得税_総所得金額=1_160_000, 所得税_所得控除の合計=1_040_000)
        self.assertEqual(value(s, "所得税_申告納税額", 2026), 6_100)
        self.assertEqual(value(s, "所得税_第3期分の税額", 2026), 6_100)
        self.assertEqual(value(s, "所得税_還付される税額", 2026), 0)
        # 給与がない人：第121条が当たらないので義務あり
        self.assertTrue(s.calculate("所得税_確定申告書の提出義務があるか", "2026")[0])

    def test_z5_r7(self) -> None:
        # [ZE] Z5-R7（令和7年分）：総所得 1,071,000、控除 950,000 → 課税 121,000、税 6,050、復興 127（手引き：切捨て）、還付 95,083
        s = self._chain(2025, 所得税_総所得金額=1_071_000, 所得税_所得控除の合計=950_000, 所得税_源泉徴収税額=101_260)
        self.assertEqual(value(s, "所得税_課税総所得金額", 2025), 121_000)
        self.assertEqual(value(s, "所得税_課税総所得金額に対する税額", 2025), 6_050)
        self.assertEqual(value(s, "所得税_復興特別所得税額", 2025), 127)
        self.assertEqual(value(s, "所得税_還付される税額", 2025), 95_083)

    def test_sum_of_deductions(self) -> None:
        # 第87条：全部の控除を足す（[ZG] §1.1）
        inputs = {name: 1_000 * (i + 1) for i, name in enumerate(DEDUCTIONS)}
        s = sim(2026, **inputs)
        self.assertEqual(value(s, "所得税_所得控除の合計", 2026), sum(inputs.values()))

    def test_retirement_and_separate_taxes(self) -> None:
        # 退職：総所得 100,000、控除 300,000、退職 1,800,000 → 課税退職 1,600,000 → 80,000
        s = self._chain(2026, 所得税_総所得金額=100_000, 所得税_所得控除の合計=300_000, 所得税_退職所得金額=1_800_000)
        self.assertEqual(value(s, "所得税_課税退職所得金額", 2026), 1_600_000)
        self.assertEqual(value(s, "所得税_課税退職所得金額に対する税額", 2026), 80_000)

    def test_retirement_base_is_after_loss_offset(self) -> None:
        # 所得税法第22条第3項・第89条第2項（taishoku §4.1）：課税退職所得金額は「退職所得金額」（損益通算・繰越控除の後）から求める。
        # 所得の種類の「退職所得の金額」（第30条）ではない。退職所得の金額 3,000,000、損益通算の後の退職所得金額 2,000,000 → 課税 2,000,000 − 500,000
        for year in (2025, 2026):
            with self.subTest(year=year):
                s = self._chain(year, 所得税_総所得金額=0, 所得税_所得控除の合計=500_000, 所得税_退職所得の金額=3_000_000, 所得税_退職所得金額=2_000_000)
                self.assertEqual(value(s, "所得税_課税退職所得金額", year), 1_500_000)
        # 分離課税：配当 1,000,000 × 15%、譲渡 2,000,000 × 15%（[kabu] §1.1・§4）。控除なし
        s = self._chain(2026, 所得税_申告分離課税の上場株式等に係る配当所得等の金額=1_000_000, 所得税_申告分離課税の上場株式等に係る譲渡所得等の金額=2_000_000, 所得税_所得控除の合計=0)
        self.assertEqual(value(s, "所得税_上場株式等に係る課税配当所得等の金額に対する税額", 2026), 150_000)
        self.assertEqual(value(s, "所得税_上場株式等に係る課税譲渡所得等の金額に対する税額", 2026), 300_000)
        self.assertEqual(value(s, "所得税_算出税額", 2026), 450_000)

    def test_credits_limited_to_tax(self) -> None:
        s = self._chain(2026, 所得税_総所得金額=1_160_000, 所得税_所得控除の合計=1_040_000, 所得税_住宅借入金等特別控除の額=100_000)
        self.assertEqual(value(s, "所得税_基準所得税額", 2026), 0)  # 6,000 − 100,000 → 0未満にしない
        s = self._chain(2026, 所得税_総所得金額=1_160_000, 所得税_所得控除の合計=1_040_000, 所得税_住宅借入金等特別控除の額=1_000, 所得税_政党等寄附金特別控除等の額=500)
        self.assertEqual(value(s, "所得税_基準所得税額", 2026), 4_500)


# ---------------------------------------------------------------------------
# 申告の要否（所得税法第120条第1項・第121条）
# ---------------------------------------------------------------------------


class TestFilingObligation(unittest.TestCase):
    BASE: dict[str, int] = {
        "tax_total_income": 0,
        "tax_retirement": 0,
        "tax_separate_dividend": 0,
        "tax_separate_gain": 0,
        "dividend_credit": 0,
        "year_end_housing_credit": 0,
        "refund": 0,
        "salary": 0,
        "pension": 0,
        "salary_limit": 20_000_000,
        "pension_limit": 4_000_000,
    }

    def ob(self, **kw: int) -> calc.Obligation:
        return filing_obligation(**{**self.BASE, **kw})

    def test_no_tax_no_obligation(self) -> None:
        o = self.ob()
        self.assertEqual((o.value, o.unresolved), (False, ()))

    def test_tax_over_dividend_credit_is_a_boundary(self) -> None:
        # 第120条第1項：税額が配当控除の額を「超える」とき（[ZG] §5.1）
        self.assertFalse(self.ob(tax_total_income=5_000, dividend_credit=5_000).value)
        self.assertTrue(self.ob(tax_total_income=5_001, dividend_credit=5_000).value)

    def test_excess_withholding_removes_obligation(self) -> None:
        # [ZG] §5.1 かっこ書き・[ZE] Z2
        o = self.ob(tax_total_income=6_000, refund=95_134, salary=1_400_000)
        self.assertEqual((o.value, o.unresolved), (False, ()))

    def test_person_without_salary_or_pension_must_file(self) -> None:
        o = self.ob(tax_total_income=6_000)
        self.assertEqual((o.value, o.unresolved), (True, ()))

    def test_section_121_salary_is_unresolved_up_to_the_limit(self) -> None:
        # 第121条第1項：給与等の金額が2,000万円以下（[ZG] §5.2）。この額以下は判定できない、超えれば第1項は当たらない
        o = self.ob(tax_total_income=6_000, salary=20_000_000)
        self.assertEqual(o.unresolved, (calc.REASON_121_SALARY,))
        o = self.ob(tax_total_income=6_000, salary=20_000_001)
        self.assertEqual((o.value, o.unresolved), (True, ()))

    def test_section_121_pension_is_unresolved_up_to_the_limit(self) -> None:
        # 第121条第3項：公的年金等の収入金額が400万円以下（docs/public-sources/20261109_round2b_nenkin-laws-and-guidance.md §6）
        o = self.ob(tax_total_income=6_000, pension=4_000_000)
        self.assertEqual(o.unresolved, (calc.REASON_121_PENSION,))
        o = self.ob(tax_total_income=6_000, pension=4_000_001)
        self.assertEqual((o.value, o.unresolved), (True, ()))

    def test_section_121_retirement_is_unresolved(self) -> None:
        o = self.ob(tax_retirement=90_000)
        self.assertEqual(o.unresolved, (calc.REASON_121_RETIREMENT,))

    def test_separate_stock_tax_counts_in_section_120(self) -> None:
        # 措令4の2⑧・25の8⑮：第120条第1項の税額の比較に分離課税の税額を含める（[JJ] §2.1）
        o = self.ob(tax_separate_dividend=1)
        self.assertEqual((o.value, o.unresolved), (True, ()))
        o = self.ob(tax_separate_gain=1, dividend_credit=1)
        self.assertEqual((o.value, o.unresolved), (False, ()))

    # 第121条：判定の事実（[121] §1・§3）
    SF = calc.SalaryFacts(payers=1, all_withheld=True, all_year_end_adjusted=False, secondary_salary=0, secondary_known=True, other_income=0, deductions=0, other_limit=200_000, small_salary_limit=1_500_000)

    def ob121(self, *, sf=None, pf=None, rf=None, **kw) -> calc.Obligation:
        return filing_obligation(**{**self.BASE, "tax_total_income": 6_000, "salary": 1_000_000, **kw}, salary_facts=sf or self.SF, pension_facts=pf, retirement_facts=rf)

    def test_first_item_single_payer(self) -> None:
        # 第121条第1項第1号：一の支払者・全部が源泉徴収の対象・その他の所得20万円以下なら提出を要しない
        self.assertEqual(self.ob121().value, False)
        from dataclasses import replace

        self.assertEqual(self.ob121(sf=replace(self.SF, other_income=200_000)).value, False)
        self.assertEqual(self.ob121(sf=replace(self.SF, other_income=200_001)).value, True)  # [121] §3 121−6 の所得金額の基礎
        self.assertEqual(self.ob121(sf=replace(self.SF, all_withheld=False)).value, True)  # 全部が徴収の対象でない
        self.assertEqual(self.ob121(salary=20_000_001).value, True)  # 第1項本文の2,000万円

    def test_second_item_two_payers(self) -> None:
        from dataclasses import replace

        two = replace(self.SF, payers=2, secondary_salary=150_000, other_income=40_000)
        self.assertFalse(self.ob121(sf=two, salary=4_000_000).value)  # イ：従たる給与等＋その他の所得が20万円以下
        over = replace(two, secondary_salary=160_001)
        self.assertTrue(self.ob121(sf=over, salary=4_000_000).value)
        # ロ：給与等の金額 ≦ 150万円＋控除の額の合計 かつ その他の所得 ≦ 20万円
        self.assertFalse(self.ob121(sf=replace(over, deductions=1_000_000, other_income=0, secondary_salary=300_000), salary=2_500_000).value)
        self.assertTrue(self.ob121(sf=replace(over, deductions=1_000_000, other_income=0, secondary_salary=300_000), salary=2_500_001).value)
        # 基通121−4：全部が年末調整の対象なら第1号
        self.assertFalse(self.ob121(sf=replace(two, all_year_end_adjusted=True), salary=4_000_000).value)
        # 従たる給与等の金額が分からず、ロにも当たらなければ判定できない
        o = self.ob121(sf=replace(two, secondary_known=False), salary=4_000_000)
        self.assertEqual(o.unresolved, (calc.REASON_121_SECONDARY,))
        o = self.ob121(sf=replace(two, secondary_known=False, deductions=3_000_000), salary=4_000_000)
        self.assertEqual((o.value, o.unresolved), (False, ()))  # ロに当たれば従たる給与等の金額は要らない

    def test_pension_paragraph_3(self) -> None:
        pf = calc.PensionFacts(all_withheld=True, other_income=200_000, other_limit=200_000)
        o = filing_obligation(**{**self.BASE, "tax_total_income": 6_000, "pension": 3_000_000}, pension_facts=pf)
        self.assertEqual(o.value, False)
        pf2 = calc.PensionFacts(all_withheld=True, other_income=200_001, other_limit=200_000)
        o = filing_obligation(**{**self.BASE, "tax_total_income": 6_000, "pension": 3_000_000}, pension_facts=pf2)
        self.assertEqual(o.value, True)

    def test_retirement_paragraph_2(self) -> None:
        # 第2項第1号：全部について第199条・第201条第1項の徴収。第2号：課税退職所得金額に係る税額が源泉徴収税額以下
        self.assertFalse(filing_obligation(**{**self.BASE, "tax_retirement": 90_000}, retirement_facts=calc.RetirementFacts(True, 0)).value)
        self.assertFalse(filing_obligation(**{**self.BASE, "tax_retirement": 90_000}, retirement_facts=calc.RetirementFacts(False, 90_000)).value)
        self.assertTrue(filing_obligation(**{**self.BASE, "tax_retirement": 90_000}, retirement_facts=calc.RetirementFacts(False, 89_999)).value)

    def test_section_121_covers_only_its_part(self) -> None:
        # 第1項が当たっても退職所得の税額の部分は第2項が要る
        o = self.ob121(tax_retirement=90_000, rf=calc.RetirementFacts(False, 0))
        self.assertEqual(o.value, True)

    def test_year_end_housing_credit_is_added_to_dividend_credit(self) -> None:
        # 措法41の2の2⑥二：所法120① の「配当控除の額」を年末調整の住宅借入金等特別控除の額との合計額と読む（［PS3-JJ］§4、推測 R-1）
        o = self.ob(tax_total_income=1_000, year_end_housing_credit=1_000)
        self.assertEqual((o.value, o.unresolved), (False, ()))
        o = self.ob(tax_total_income=1_001, year_end_housing_credit=1_000)
        self.assertEqual((o.value, o.unresolved), (True, ()))

    def test_section_121_excluded_payment(self) -> None:
        # 基通121−5・所令262の2：第1項を適用しない給与を受けたら第1号に当たっても申告不要にならない
        f = dataclasses.replace(self.SF, excluded=True)
        self.assertEqual(calc.salary_return_not_required(1_000_000, 20_000_000, f), False)
        self.assertEqual(calc.salary_return_not_required(1_000_000, 20_000_000, self.SF), True)


# ---------------------------------------------------------------------------
# 休日と期限（[SS] §6・§6.1、[MS] §4）
# ---------------------------------------------------------------------------


class TestCalendar(unittest.TestCase):
    #: 暦要項の「…は休日になる」（[SS] §6.1 の表）。振替休日・国民の休日と一致する。
    EXTRA = {
        2025: {(2, 24), (5, 6), (11, 24)},
        2026: {(5, 6), (9, 22)},
        2027: {(3, 22)},
    }
    EQUINOX = {2025: ((3, 20), (9, 23)), 2026: ((3, 20), (9, 23)), 2027: ((3, 21), (9, 23))}

    def test_substitute_holidays_match_koyomi(self) -> None:
        for y, extra in self.EXTRA.items():
            with self.subTest(year=y):
                cal = calendars(y)[y]
                self.assertEqual({(d.month, d.day) for d in cal.substitute}, extra)

    def test_equinoxes(self) -> None:
        for y, (spring, autumn) in self.EQUINOX.items():
            with self.subTest(year=y):
                cal = calendars(y)[y]
                self.assertIn(_dt.date(y, *spring), cal.national)
                self.assertIn(_dt.date(y, *autumn), cal.national)

    def test_happy_mondays_are_computed(self) -> None:
        cal = calendars(2026)[2026]
        self.assertIn(_dt.date(2026, 1, 12), cal.national)  # 1月の第2月曜日
        self.assertIn(_dt.date(2026, 7, 20), cal.national)  # 7月の第3月曜日
        self.assertIn(_dt.date(2026, 9, 21), cal.national)  # 9月の第3月曜日
        self.assertIn(_dt.date(2026, 10, 12), cal.national)  # 10月の第2月曜日

    def test_closed_days(self) -> None:
        cals = calendars(2026, 2027)
        # 土曜（通則令2②）・日曜（通則法10②）・12月29〜31日（通則令2②）・1月2日・3日（通達）・祝日
        self.assertEqual(next_open_day(_dt.date(2026, 8, 29), cals), _dt.date(2026, 8, 31))  # 土曜 → 月曜（[MS] §4 [3]）
        self.assertEqual(next_open_day(_dt.date(2026, 5, 10), cals), _dt.date(2026, 5, 11))  # 日曜 → 月曜（[MS] §4 [3]）
        self.assertEqual(next_open_day(_dt.date(2026, 12, 29), cals), _dt.date(2027, 1, 4))  # 年末年始（2027-01-04 は月曜）
        self.assertEqual(next_open_day(_dt.date(2026, 10, 20), cals), _dt.date(2026, 10, 20))

    def test_unpublished_year_is_unknown_only_in_march_and_september(self) -> None:
        # [SS] §6.1：2028年の暦要項は未発表。決まらないのは春分日・秋分日のある3月・9月だけ
        cals = calendars(2028)
        self.assertEqual(cals[2028].unknown_months, frozenset({3, 9}))
        with self.assertRaises(calc.CalendarUnknown):
            next_open_day(_dt.date(2028, 3, 15), cals)
        with self.assertRaises(calc.CalendarUnknown):
            next_open_day(_dt.date(2028, 9, 15), cals)
        self.assertEqual(next_open_day(_dt.date(2028, 1, 1), cals), _dt.date(2028, 1, 4))  # 元日・1月2日・3日（2028-01-04 は火曜）
        with self.assertRaises(calc.CalendarUnknown):  # その暦年のパラメータがない
            next_open_day(_dt.date(2028, 3, 15), calendars(2027))

    def test_substitute_holiday_skips_consecutive_national_holidays(self) -> None:
        # 2026-05-03（日）の振替は 5/4・5/5 が国民の祝日なので 5/6（祝日法第3条第2項）
        nat = {_dt.date(2026, 5, 3), _dt.date(2026, 5, 4), _dt.date(2026, 5, 5)}
        self.assertEqual(substitute_holidays(nat), {_dt.date(2026, 5, 6)})


class TestDeadlines(unittest.TestCase):
    def test_normal_deadline_r7_is_moved_to_monday(self) -> None:
        # [ZG] §5.1：手引き p.1・p.2「令和8年3月16日（月）まで」（2026-03-15 は日曜）。[MZ] §6 の曜日
        self.assertEqual(normal_deadline(2025, "03-15", calendars(2026)), _dt.date(2026, 3, 16))

    def test_normal_deadline_r8(self) -> None:
        # [ZE] Z3：2027-03-15 は月曜（[MZ] §6）
        self.assertEqual(normal_deadline(2026, "03-15", calendars(2027)), _dt.date(2027, 3, 15))

    def test_months_later_expiry(self) -> None:
        # [MS] §4 [2]：読みA。6月20日に死亡（同日に知った）→ 10月20日（付表の書き方の例）
        self.assertEqual(months_later_expiry(_dt.date(2026, 6, 21), 4), _dt.date(2026, 10, 20))
        # 通則法第10条第1項第3号：応当する日がなければその月の末日（2027年2月に29日がない）
        self.assertEqual(months_later_expiry(_dt.date(2026, 10, 29), 4), _dt.date(2027, 2, 28))
        self.assertEqual(months_later_expiry(_dt.date(2026, 10, 31), 4), _dt.date(2027, 2, 28))
        self.assertEqual(months_later_expiry(_dt.date(2026, 11, 2), 4), _dt.date(2027, 3, 1))

    def test_death_deadline_examples(self) -> None:
        # [MS] §4 [3]：知った日 → 期限（休日の繰下げつき）。[9]：2027-02-10 → 2027-06-10
        cals = calendars(2026, 2027)
        for known, expected in (
            (_dt.date(2026, 6, 20), _dt.date(2026, 10, 20)),
            (_dt.date(2026, 1, 10), _dt.date(2026, 5, 11)),  # 5/10（日）→ 5/11
            (_dt.date(2026, 4, 29), _dt.date(2026, 8, 31)),  # 8/29（土）→ 8/31
            (_dt.date(2026, 7, 2), _dt.date(2026, 11, 2)),
            (_dt.date(2026, 8, 28), _dt.date(2026, 12, 28)),
            (_dt.date(2027, 2, 10), _dt.date(2027, 6, 10)),
            (_dt.date(2026, 10, 28), _dt.date(2027, 3, 1)),  # 2/28（日）→ 3/1（[SS] §6.1 で3月の日が決まる）
        ):
            with self.subTest(known=known):
                self.assertEqual(death_deadline(known, 4, cals), expected)

    def test_heir_departure_is_not_moved(self) -> None:
        # 第125条第1項括弧：相続人が出国するならその時。出国の時は休日でも繰り下げない（通則令第2条第1項第1号：[SS] §6）
        cals = calendars(2026, 2027)
        self.assertEqual(death_deadline(_dt.date(2026, 6, 20), 4, cals, heir_departure_on=_dt.date(2026, 8, 29)), _dt.date(2026, 8, 29))
        self.assertEqual(death_deadline(_dt.date(2026, 6, 20), 4, cals, heir_departure_on=_dt.date(2026, 12, 1)), _dt.date(2026, 10, 20))

    def test_variable_gives_normal_deadlines(self) -> None:
        d = lambda s, y: _dt.date.fromisoformat(str(s.calculate("所得税_申告期限", str(y))[0]))  # noqa: E731
        self.assertEqual(d(sim(2025), 2025), _dt.date(2026, 3, 16))
        self.assertEqual(d(sim(2026), 2026), _dt.date(2027, 3, 15))

    def test_variable_unknown_for_unpublished_calendar_year(self) -> None:
        # 令和9年分の期限（2028年）：暦要項が未発表（[SS] §6.1）
        s = sim(2027)
        self.assertEqual(_dt.date.fromisoformat(str(s.calculate("所得税_申告期限", "2027")[0])), UNKNOWN_DEADLINE)


# ---------------------------------------------------------------------------
# 計算の後の検出
# ---------------------------------------------------------------------------


class TestChecks(unittest.TestCase):
    def _ctx(self, year: int, sim_, ir=None) -> CheckContext:
        ir = ir or make_ir([person("p")], [])
        return CheckContext(year, ("p",), lambda v: sim_.calculate(v, str(year)), params(year), ir)

    def test_stock_order_follows_the_choice(self) -> None:
        # 措通31・32共−4：通達の順は配当所得等が先、ただし書の選択で譲渡所得等が先（推測 O-1）
        base = dict(所得税_申告分離課税の上場株式等に係る配当所得等の金額=500_000, 所得税_申告分離課税の上場株式等に係る譲渡所得等の金額=500_000, 所得税_所得控除の合計=700_000)
        for order, want in ((calc.ORDER_TSUTATSU, (0, 300_000)), (calc.ORDER_ALT, (300_000, 0))):
            with self.subTest(order=order):
                s = sim(2026, 所得税_上場株式等の所得控除の順序=order, **base)
                got = (int(s.calculate("所得税_上場株式等に係る課税配当所得等の金額", "2026")[0]), int(s.calculate("所得税_上場株式等に係る課税譲渡所得等の金額", "2026")[0]))
                self.assertEqual(got, want)

    def test_filing_obligation_unresolved(self) -> None:
        # 二以上の支払者で従たる給与等の金額が分からず、第2号ロに当たらない
        s = sim(
            2026,
            所得税_総所得金額=1_160_000,
            所得税_所得控除の合計=1_040_000,
            所得税_給与等の収入金額=2_000_000,
            所得税_給与等の支払者の数=2,
            所得税_給与等の全部が源泉徴収の対象か=True,
            所得税_従たる給与等の金額が分かるか=False,
            所得税_復興特別所得税額の端数の候補="floor",
        )
        out = list(filing_obligation_undetermined(self._ctx(2026, s)))
        self.assertEqual([e.variable for e in out], ["所得税_確定申告書の提出義務があるか"])
        self.assertIn("第2号イ", out[0].reason.reason)



# ---------------------------------------------------------------------------
# 配当控除（所得税法第92条。[HT] docs/public-sources/20261111_impl-research_haito-laws-and-nta.md §2、docs/inferences/20261111_impl-research_haito-cases.md）
# ---------------------------------------------------------------------------


class TestDividendCredit(unittest.TestCase):
    def rules(self, year: int = 2026) -> calc.DividendCreditRules:
        return calc.dividend_credit_rules_from_parameters(params(year).所得税.配当控除)

    def test_cases(self) -> None:
        # (T, A, B, 税額の限度, 期待値)：[HT] §2 の第1号〜第3号、haito-cases H-1〜H-6
        for t, a, b, tax, want in (
            (8_000_000, 300_000, 0, 1_000_000, 30_000),
            (10_500_000, 300_000, 0, 1_000_000, 15_000),
            (10_500_000, 0, 600_000, 1_000_000, 17_500),
            (15_000_000, 300_000, 200_000, 1_000_000, 20_000),
            (5_000_000, 12_345, 0, 1_000_000, 1_234),
            (8_000_000, 300_000, 0, 7_000, 7_000),
            (10_000_000, 300_000, 0, 1_000_000, 30_000),  # 境目：千万円以下は第1号
            (10_000_001, 300_000, 0, 1_000_000, 15_000 + 300_000 * 0),  # 第3号（X=1 → 5%が1円分、残り10%）。下の式で確かめる
        ):
            with self.subTest(t=t, a=a, b=b):
                got = calc.dividend_credit(t, a, b, tax, self.rules())
                if t == 10_000_001:
                    self.assertEqual(got, 29_999)  # 1円×5% ＋ 299,999円×10% ＝ 29,999.95 → 切捨て
                else:
                    self.assertEqual(got, want)

    def test_field_value_is_before_the_tax_limit(self) -> None:
        """2026-11-13：第一表 ㉝ は計算欄G（限度の前）。配当控除の額は所得税額が限度（作成コーナーとの照合 B01：㉝ 20,000・税額 10,050）。"""
        r = self.rules()
        self.assertEqual(calc.dividend_credit_computed(67_000, 200_000, 0, r), 20_000)
        self.assertEqual(calc.dividend_credit(67_000, 200_000, 0, 10_050, r), 10_050)

    def test_both_years_same(self) -> None:
        self.assertEqual(self.rules(2025), self.rules(2026))

    def test_variable_uses_taxable_total_with_separate(self) -> None:
        s = sim(
            2026,
            所得税_配当控除の対象の剰余金の配当等に係る配当所得の金額=300_000,
            所得税_課税総所得金額=9_800_000,
            所得税_上場株式等に係る課税配当所得等の金額=700_000,
            所得税_算出税額=3_000_000,
        )
        # T=1050万（分離の加算）→ 第3号：X=50万超の分 A=30万 は 5%
        self.assertEqual(value(s, "所得税_配当控除の額", 2026), 15_000)

    def test_foreign_currency_trust_half_rates(self) -> None:
        # 措法9④（[HT] §3.1）の読替え。c は一般外貨建等証券投資信託、b はそれ以外の証券投資信託
        r = self.rules()
        # 第1号：c 2.5%、b 5%
        self.assertEqual(calc.dividend_credit(8_000_000, 0, 100_000, 10**7, r, 200_000), 5_000 + 5_000)
        # 第2号・T−c ≦ 千万円：c のうち T−千万円 は 1.25%、残り 2.5%、b 5%
        self.assertEqual(calc.dividend_credit(10_100_000, 0, 100_000, 10**7, r, 200_000), 1_250 + 2_500 + 5_000)
        # 第2号・T−c ＞ 千万円：c は全部 1.25%、b のうち T−千万円−c は 2.5%、残り 5%
        self.assertEqual(calc.dividend_credit(10_250_000, 0, 100_000, 10**7, r, 200_000), 2_500 + 1_250 + 2_500)
        # 第3号：b 2.5%、c 1.25%、a のうち T−千万円−(b＋c) は 5%
        self.assertEqual(calc.dividend_credit(10_400_000, 200_000, 100_000, 10**7, r, 200_000), 2_500 + 2_500 + 5_000 + 10_000)
        # c がなければ従来の第2号と同じ
        self.assertEqual(calc.dividend_credit(10_500_000, 0, 600_000, 10**7, r), 17_500)


# ---------------------------------------------------------------------------
# パラメータ・根拠の組み立て
# ---------------------------------------------------------------------------


class TestParametersAndBasis(unittest.TestCase):
    def test_rate_table_same_in_both_years(self) -> None:
        b25 = brackets_from_parameters(params(2025).所得税.税率)
        b26 = brackets_from_parameters(params(2026).所得税.税率)
        self.assertEqual(b25, b26)
        # [ZG] §2 の表
        self.assertEqual([b.up_to for b in b26], [1_950_000, 3_300_000, 6_950_000, 9_000_000, 18_000_000, 40_000_000, None])
        self.assertEqual([b.rate * 100 for b in b26], [5, 10, 20, 23, 33, 40, 45])

    def test_rounding_units_and_rates(self) -> None:
        p = params(2026).所得税
        self.assertEqual((p.端数計算.課税標準の単位, p.端数計算.確定金額の単位), (1000, 100))  # [ZG] §1.2
        self.assertEqual(calc.rate_of(p.分離課税の税率.上場株式等に係る課税配当所得等の金額, "x"), Fraction(15, 100))  # [kabu] §1.1
        self.assertEqual(calc.rate_of(p.分離課税の税率.上場株式等に係る課税譲渡所得等の金額, "x"), Fraction(15, 100))  # [kabu] §4
        self.assertEqual(p.確定申告を要しない場合.給与等の金額の上限, 20_000_000)  # [ZG] §5.2
        self.assertEqual(p.確定申告を要しない場合.公的年金等の収入金額の上限, 4_000_000)  # nenkin §6

    def test_progressive_basis_lists_only_used_brackets(self) -> None:
        s = sim(2026, 所得税_課税総所得金額=2_000_000)
        ctx = BasisContext(2026, "2026-01-01", system().parameters, params(2026), lambda v: s.calculate(v, "2026"), 0, "p")
        names = [b.name for b in BASIS["所得税_課税総所得金額に対する税額"](ctx)]
        self.assertIn("所得税.税率.第1段.以下", names)
        self.assertIn("所得税.税率.第2段.率.分子", names)
        self.assertNotIn("所得税.税率.第3段.以下", names)

    def test_rules_have_references(self) -> None:
        for var, entries in RULES.items():
            for e in entries:
                with self.subTest(variable=var, rule=e.name):
                    self.assertTrue(e.references)


# ---------------------------------------------------------------------------
# 入力（中間表現 → 事実の層）：evaluate を通して確かめる
# ---------------------------------------------------------------------------


def withheld(rid: str, pid: str, on: str, gross: int, tax: int | None, **kw: Any) -> dict[str, Any]:
    rec = salary(rid, pid, on, gross, **kw)
    if tax is not None:
        rec["amounts"]["withholding_tax"] = tax
    return rec


def notice(rid: str, pid: str, year: int, amount: int) -> dict[str, Any]:
    return {"id": rid, "kind": "prepayment_notice", "roles": {"taxpayer": pid}, "when": {"tax_year": year}, "amounts": {"prepayment_total": amount}}


def housing(rid: str, pid: str, year: int, amount: int) -> dict[str, Any]:
    return {"id": rid, "kind": "housing_loan_credit", "roles": {"person": pid}, "when": {"tax_year": year}, "amounts": {"credit_amount": amount}}


def dead(pid: str, on: str) -> dict[str, Any]:
    return {"id": pid, "birth_on": "1950-01-01", "death_on": on}


def heir(rid: str, decedent: str, who: str, known_on: str, **attrs: Any) -> dict[str, Any]:
    return {"id": rid, "kind": "heirship", "roles": {"decedent": decedent, "heir": who}, "when": {"on": known_on}, "attributes": {"heir_type": "heir", **attrs}}


class TestInputs(unittest.TestCase):
    def _scenario(self, ir: dict[str, Any], years: tuple[int, ...] = (2026,)):
        return _ok(evaluate(ir, make_query(years), system=system())).scenario("base")





















    def test_withholding_after_death_follows_due_on(self) -> None:
        # 所基通9−17・36−9 と所法120①四の読み（inputs.AFTER_DEATH_RULE）：支給期が死亡の前なら死亡後の支払でも数え、後なら数えない。
        # 同じ日は kyuyo の 判断.給与の支給期が死亡前か の1か所に従う
        from okura_core.registry import Decided, ModuleInputs, YearContext
        from okura_core.rules.tax.inputs import K_DEATH, V_WITHHOLDING, _withholding, _year_records

        def pay(rid: str, on: str, due: str, tax: int) -> dict[str, Any]:
            r = salary(rid, "p", on, 100_000, due_on=due)
            r["amounts"]["withholding_tax"] = tax
            return r

        ir = make_ir([dead("p", "2026-06-10")], [pay("a", "2026-06-25", "2026-05-25", 100), pay("b", "2026-06-25", "2026-06-25", 20), pay("c", "2026-06-25", "2026-06-10", 3)])
        for same_day, want in ((True, 103), (False, 100)):
            with self.subTest(same_day=same_day):
                ctx = YearContext(ir, 2026, ("p",), {(K_DEATH, "c"): Decided(same_day, (), frozenset(), False)})
                out = ModuleInputs()
                _withholding(out, ctx, "p", _year_records(ctx))
                self.assertEqual(out.exclusions, [])
                v = out.values[(V_WITHHOLDING, "p")]
                self.assertEqual(v.value, want)
                self.assertTrue(v.basis)

    def test_unpaid_salary_is_evaluated_in_both_readings(self) -> None:
        # ［H3］H7：(a) 別表で計算した額を入れる・(b) 入れない。(a) の入力が語彙にないので分かれ目（一次情報）。甲欄で日額表の最初の帯より下なら (a) も0
        from okura_core.registry import ModuleInputs, YearContext
        from okura_core.result import Means
        from okura_core.rules.tax.inputs import V_WITHHOLDING, _withholding, _year_records

        def run(gross: int, declared: bool, **attrs: Any) -> Any:
            r = salary("u", "p", "2026-12-25", gross)
            r["attributes"]["unpaid"] = True
            r["attributes"].update(attrs)
            docs = [{"id": "d", "kind": "filed_document", "roles": {"filer": "p"}, "when": {"on": "2026-01-05"},
                     "attributes": {"document_type": "employee_dependents_declaration", "tax_year": 2026, "recipient": "employer", "recipient_name": r["attributes"]["counterparty"]}}]  # fmt: skip
            ctx = YearContext(make_ir([person("p")], [r] + (docs if declared else [])), 2026, ("p",))
            out = ModuleInputs()
            _withholding(out, ctx, "p", _year_records(ctx))
            self.assertEqual(out.exclusions, [])
            return out.values[(V_WITHHOLDING, "p")]

        v = run(100_000, True)
        self.assertEqual(v.value, 0)
        self.assertEqual([(m.means, m.candidates) for m in v.missing], [(Means.PRIMARY_SOURCE, ("(a) 別表で計算した額を入れる", "(b) 入れない"))])
        self.assertEqual(run(3_499, True).missing, ())  # 令和8年の日額表の最初の帯 3,500円より下・甲欄
        self.assertEqual(len(run(3_499, False).missing), 1)  # 乙欄なら3％がかかりうる
        # 支給期の区分（2026-11-12 の語彙）：毎月なら月額表。令和8年の最初の帯 105,000円より下の甲欄は (a) も0、帯の中なら (a)>0 で分かれ目
        self.assertEqual(run(104_999, True, pay_period="monthly").missing, ())
        self.assertEqual(len(run(105_000, True, pay_period="monthly").missing), 1)
        self.assertEqual(run(52_499, True, pay_period="semimonthly").missing, ())  # 毎半月：2倍の 104,998円の月額表の税額（0）の1/2

    def test_no_withholding_payer_counts_zero(self) -> None:
        # 所法184（家事使用人のみに支払う者）・国外の支払：源泉徴収の欄がなくても対象外にせず0
        from okura_core.registry import ModuleInputs, YearContext
        from okura_core.rules.tax.inputs import V_121_EXCLUDED, V_WITHHOLDING, _section121_facts, _withholding, _year_records

        r = salary("h", "p", "2026-05-25", 100_000)
        r["attributes"]["payer_withholding_exempt_household"] = True
        ctx = YearContext(make_ir([person("p")], [r]), 2026, ("p",))
        out = ModuleInputs()
        _withholding(out, ctx, "p", _year_records(ctx))
        _section121_facts(out, ctx, "p", _year_records(ctx))
        self.assertEqual(out.exclusions, [])
        self.assertEqual(out.values[(V_WITHHOLDING, "p")].value, 0)
        self.assertIs(out.values[(V_121_EXCLUDED, "p")].value, True)

    def test_year_end_housing_credit_from_slip(self) -> None:
        # 措法41の2の2①⑥二：居住の年分は0。翌年以後は源泉徴収票の housing_loan_credit（2026-11-12 の語彙）、記載がなければ分かれ目（事実）
        from okura_core.registry import ModuleInputs, YearContext
        from okura_core.result import Means
        from okura_core.rules.tax.inputs import V_NENMATSU_HOUSING, _nenmatsu_housing, _year_records

        def run(moved: str, slip_amounts: dict[str, Any] | None) -> Any:
            credit = {"id": "h", "kind": "housing_loan_credit", "roles": {"person": "p"}, "when": {"tax_year": 2026}, "amounts": {"credit_amount": 100_000}, "attributes": {"moved_in_on": moved}}
            recs = [salary("s", "p", "2026-05-25", 300_000), credit]
            if slip_amounts is not None:
                recs.append({"id": "ws", "kind": "withholding_slip", "roles": {"recipient": "p"}, "when": {"tax_year": 2026},
                             "amounts": {"payment_amount": 300_000, **slip_amounts}, "attributes": {"slip_type": "salary", "counterparty": "架空の会社", "year_end_adjusted": True}})
            ctx = YearContext(make_ir([person("p")], recs), 2026, ("p",))
            out = ModuleInputs()
            _nenmatsu_housing(out, ctx, "p", [credit], _year_records(ctx))
            return out.values[(V_NENMATSU_HOUSING, "p")]

        self.assertEqual((run("2026-03-01", None).value, run("2026-03-01", None).missing), (0, ()))
        v = run("2024-03-01", {"housing_loan_credit": 80_000})
        self.assertEqual((v.value, v.missing), (80_000, ()))
        self.assertEqual([m.means for m in run("2024-03-01", None).missing], [Means.FACT])

    def test_heirs_with_different_deadlines_split(self) -> None:
        # 相続人ごとの期限が違えば分かれ目（一次情報）、全員が放棄なら清算人が確定した日（事実）。どちらも対象外にしない
        from okura_core.registry import ModuleInputs, YearContext, YearWindow
        from okura_core.result import Means
        from okura_core.rules.tax.inputs import KIND_DEATH, V_KNOWN, _death_kind

        def heir(hid: str, on: str, **attrs: Any) -> dict[str, Any]:
            return {"id": hid, "kind": "heirship", "roles": {"decedent": "p", "heir": "q"}, "when": {"on": on}, "attributes": {"heir_type": "heir", **attrs}}

        for recs, means in (
            ([heir("h1", "2026-06-20"), heir("h2", "2026-07-20")], Means.PRIMARY_SOURCE),
            ([heir("h1", "2026-06-20", renounced=True)], Means.FACT),
            ([heir("h1", "2026-06-20"), heir("h2", "2026-06-20")], None),
            # 全員が放棄で清算人が確定した日（estate_liquidator。2026-11-12 の語彙）があれば、その日で期限が決まる（質疑07-15）
            ([heir("h1", "2026-06-20", renounced=True),
              {"id": "lq", "kind": "estate_liquidator", "roles": {"decedent": "p"}, "when": {"on": "2026-09-01"}}], None),
        ):
            with self.subTest(means=means):
                win = YearWindow(parameters_at=lambda d: system().parameters(d))
                ctx = YearContext(make_ir([dead("p", "2026-06-10"), person("q")], recs), 2026, ("p", "q"), window=win)
                out = ModuleInputs()
                _death_kind(out, ctx, "p", _dt.date(2026, 6, 10), KIND_DEATH)
                self.assertEqual(out.exclusions, [])
                self.assertEqual([m.means for m in out.values[(V_KNOWN, "p")].missing], [] if means is None else [means])

    def test_deadline_kind_for_departure(self) -> None:
        # 第127条第1項：出国の時（繰り下げない）。納税管理人の届出があれば出国に当たらない（[SS] §3.1）
        s = sim(2026, 所得税_申告の種類=KIND_DEPARTURE, 所得税_出国の日="2026-09-05")  # 土曜日でも繰り下げない
        self.assertEqual(np.datetime64(s.calculate("所得税_申告期限", "2026")[0], "D"), np.datetime64("2026-09-05"))

    def test_domestic_judgment_must_cover_the_stay(self) -> None:
        from okura_core.registry import YearContext
        from okura_core.rules.tax.inputs import _departure_on

        stay = {"id": "st", "kind": "abroad_stay", "roles": {"person": "p"}, "when": {"from_on": "2026-02-01", "to_on": "2026-03-01"}, "attributes": {"country": "US", "purpose": "tourism"}}
        def j(from_on: str, to_on: str) -> dict[str, Any]:
            return {"id": "j", "kind": "判断.住所の所在", "judged_by": {"person": "p"}, "judged_at": "2026-01-01T00:00:00+09:00", "subject": {"person": "p"}, "when": {"from_on": from_on, "to_on": to_on}, "value": "domestic"}
        covered = make_ir([person("p")], [stay], judgments=[j("2026-01-01", "2026-12-31")])
        self.assertEqual(_departure_on(YearContext(covered, 2026, ("p",)), "p", _dt.date(2027, 3, 15))[2], False)
        partial = make_ir([person("p")], [stay], judgments=[j("2026-02-15", "2026-12-31")])
        self.assertEqual(_departure_on(YearContext(partial, 2026, ("p",)), "p", _dt.date(2027, 3, 15))[2], True)
        no_stay = make_ir([person("p")], [], judgments=[j("2026-01-01", "2026-12-31")])  # 国内という判断だけなら出国の問題はない
        self.assertEqual(_departure_on(YearContext(no_stay, 2026, ("p",)), "p", _dt.date(2027, 3, 15)), (None, ("j",), False))

    def test_departure_needs_foreign_judgment_and_no_agent(self) -> None:
        from okura_core.registry import YearContext
        from okura_core.rules.tax.inputs import _departure_on

        stay = {"id": "st", "kind": "abroad_stay", "roles": {"person": "p"}, "when": {"from_on": "2026-09-05"}, "attributes": {"country": "US", "purpose": "assignment"}}
        j = {"id": "j", "kind": "判断.住所の所在", "judged_by": {"person": "p"}, "judged_at": "2026-09-01T00:00:00+09:00", "subject": {"person": "p"}, "when": {"from_on": "2026-09-05"}, "value": "foreign"}
        ir = make_ir([person("p")], [stay], judgments=[j])
        ctx = YearContext(ir, 2026, ("p",))
        day, _, und = _departure_on(ctx, "p", _dt.date(2027, 3, 15))
        self.assertEqual((day, und), (_dt.date(2026, 9, 5), False))
        ir2 = make_ir([person("p")], [stay])  # 住所の判断がなければ決まらない
        self.assertTrue(_departure_on(YearContext(ir2, 2026, ("p",)), "p", _dt.date(2027, 3, 15))[2])
        notice = {"id": "n", "kind": "tax_agent_notice", "roles": {"taxpayer": "p"}, "when": {"on": "2026-08-31"}, "attributes": {"action": "appointment"}}
        ir3 = make_ir([person("p")], [stay, notice], judgments=[j])  # 納税管理人の届出があれば出国でない
        self.assertEqual(_departure_on(YearContext(ir3, 2026, ("p",)), "p", _dt.date(2027, 3, 15))[:2][0], None)


if __name__ == "__main__":
    unittest.main()


class SalaryDueTest(unittest.TestCase):
    def test_officer_bonus_year_follows_resolution(self) -> None:
        # 所基通36−9(2)：役員の利益連動の賞与は決議等の日・各人の支給金額が定められた日の年分（kyuyo の due_date と同じ。2026-11-12）
        from okura_core.rules.tax.inputs import salary_due, section121_excluded

        r = salary("b", "p", "2027-01-10", 100_000)
        r["attributes"].update(payment_type="officer_bonus_by_resolution", due_on="2027-01-10", resolution_on="2026-12-20")
        self.assertEqual(salary_due(r), _dt.date(2026, 12, 20))
        r["attributes"]["amount_fixed_on"] = "2027-01-05"
        self.assertEqual(salary_due(r), _dt.date(2027, 1, 5))
        m = salary("m", "p", "2026-05-25", 100_000)
        self.assertFalse(section121_excluded(m))
        m["attributes"]["paid_by_foreign_mission"] = True  # 所基通121−5(2)
        self.assertTrue(section121_excluded(m))

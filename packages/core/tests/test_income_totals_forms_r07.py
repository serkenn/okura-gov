"""第三表・第四表の欄に写す途中の値の純粋関数（income_totals/filing.py・income_kinds/filing.py）のユニットテスト。境目だけ。"""

from __future__ import annotations

import unittest
from fractions import Fraction

from okura_core.rules.income_kinds.calc import RetirementRules
from okura_core.rules.income_kinds.filing import _retirement_rows
from okura_core.rules.income_totals.filing import first_offset, keijo_before, listed_split, oldest_first

# 所法30③⑥・30②・30④（docs/public-sources/20261109_round2b_taishoku-laws-and-guidance.md §2.1）
_R = RetirementRules(
    years_split=20, per_year=400_000, base_over=8_000_000, per_year_over=700_000, minimum=800_000,
    disability_add=1_000_000, half=Fraction(1, 2), short_split=3_000_000, short_base=1_500_000,
)


def _rows(total, years, kind, short=0, officer=0, short_ded=0, officer_ded=0):
    return _retirement_rows([total], [years], [kind], [False], [0], [short], [officer], [short_ded], [officer_ded], _R)[0]


class LossOffsetStages(unittest.TestCase):
    def test_keijo_ignores_dividend_and_misc_losses(self):
        self.assertEqual(keijo_before(-10, -500_000, 0, 300_000, -20), -200_000)

    def test_first_offset_boundary(self):
        self.assertEqual(first_offset(-500_000, 200_000), (-300_000, 0))
        self.assertEqual(first_offset(-200_000, 200_000), (0, 0))  # ちょうど控除しきる
        self.assertEqual(first_offset(-100_000, 300_000), (0, 200_000))
        self.assertEqual(first_offset(0, 300_000), (0, 300_000))  # 黒字（0）はそのまま


class CarryforwardByYear(unittest.TestCase):
    def test_oldest_first(self):
        self.assertEqual(oldest_first(500_000, (300_000, 400_000, 100_000)), [300_000, 200_000, 0])
        self.assertEqual(oldest_first(800_000, (300_000, 400_000, 100_000)), [300_000, 400_000, 100_000])
        self.assertEqual(oldest_first(0, (300_000, 0, 0)), [0, 0, 0])

    def test_oldest_first_rejects_overflow(self):
        with self.assertRaises(ValueError):
            oldest_first(800_001, (300_000, 400_000, 100_000))


class ListedSplit(unittest.TestCase):
    def test_gain_first_then_dividend(self):
        # 実測 kabu §6 の S4：繰越損失 400,000・譲渡益 300,000・配当 200,000 → 譲渡から 300,000、配当から 100,000
        self.assertEqual(listed_split(200_000, 300_000, 400_000, offset=True, carry=True), (300_000, 100_000, 0))

    def test_new_loss_after_offset(self):
        # S3：譲渡損 300,000・配当 100,000 を通算 → 繰り越す新しい損失は 200,000。通算しなければ 300,000
        self.assertEqual(listed_split(100_000, -300_000, 0, offset=True, carry=False), (0, 0, 200_000))
        self.assertEqual(listed_split(100_000, -300_000, 0, offset=False, carry=False), (0, 0, 300_000))


class RetirementRows(unittest.TestCase):
    def test_single_kind_goes_to_its_row(self):
        r = _rows(5_000_000, 3, "短期")
        self.assertEqual(r["短期"], (5_000_000, 1_200_000))
        self.assertEqual((r["一般"], r["特定役員"]), ((0, 0), (0, 0)))

    def test_general_and_officer_ta2737_example2(self):
        # TA2737 例2：使用人退職金 800万・役員退職金 500万、退職所得控除額 520万、特定役員退職所得控除額 120万 → 一般の控除 400万
        r = _rows(13_000_000, 13, "一般", officer=5_000_000, officer_ded=1_200_000)
        self.assertEqual(r["一般"], (8_000_000, 4_000_000))
        self.assertEqual(r["特定役員"], (5_000_000, 1_200_000))

    def test_short_and_officer_ta2741(self):
        # TA2741：短期 500万・特定役員 1,500万、勤続5年（控除 200万）、特定役員退職所得控除額 120万 → 短期の控除 80万
        r = _rows(20_000_000, 5, "短期", short=5_000_000, officer=15_000_000, officer_ded=1_200_000)
        self.assertEqual(r["短期"], (5_000_000, 800_000))
        self.assertEqual(r["一般"], (0, 0))


if __name__ == "__main__":
    unittest.main()

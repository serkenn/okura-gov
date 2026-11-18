"""rules/tax/gensen.py（所得税法 別表第二〜第四の源泉徴収税額表）のテスト：写した表の SHA-256 と、帯の境目・令和7年と令和8年の違い。

期待値の出典：docs/public-sources/20261111_impl-research3_gensen-laws.md §2、docs/inferences/20261111_impl-research3_all-cases.md §2（S-1〜S-6）。
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import unittest
from fractions import Fraction

from okura_core.rules.tax.gensen import DATA_DIR, KO, OTSU, bonus_rate, sources, wage_tax

from .support import REPO

R7 = _dt.date(2025, 6, 25)  # 令和7年中の支払：2025-12-31 の版
R8 = _dt.date(2026, 6, 25)  # 令和8年中の支払：2026-01-01 の版


class TestGensenData(unittest.TestCase):
    def test_sha256_matches_record_and_original(self) -> None:
        for name, info in sources()["files"].items():
            with self.subTest(name=name):
                self.assertEqual(hashlib.sha256((DATA_DIR / name).read_bytes()).hexdigest(), info["sha256"])
                original = REPO / info["original"]
                if original.exists():
                    self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), info["sha256"])


class TestWageTax(unittest.TestCase):
    def test_first_band_boundary_r7_r8(self) -> None:
        # 最初の帯：R7 88,000円以上 甲0人 130、R8 105,000円以上 甲0人 170。より下は甲0・乙3％
        self.assertEqual(wage_tax("getsugaku", R7, 87_999, KO), 0)
        self.assertEqual(wage_tax("getsugaku", R7, 88_000, KO), 130)
        self.assertEqual(wage_tax("getsugaku", R8, 104_999, KO), 0)
        self.assertEqual(wage_tax("getsugaku", R8, 105_000, KO), 170)
        self.assertEqual(wage_tax("getsugaku", R8, 104_999, OTSU), Fraction(104_999 * 3, 100))

    def test_inference_cases(self) -> None:
        # 推測 S-1〜S-5
        self.assertEqual(wage_tax("getsugaku", R8, 106_000, KO, 0), 170)
        self.assertEqual(wage_tax("getsugaku", R7, 88_500, KO, 0), 130)
        self.assertEqual(wage_tax("getsugaku", R8, 300_000, KO, 2), 4_600)
        self.assertEqual(wage_tax("getsugaku", R7, 300_000, KO, 2), 5_020)
        self.assertEqual(wage_tax("getsugaku", R8, 300_000, OTSU), 52_500)

    def test_more_than_seven_dependents(self) -> None:
        # 推測 S-6：7人を超える1人ごとに 1,580円（月額表）
        self.assertEqual(wage_tax("getsugaku", R8, 700_000, KO, 8), wage_tax("getsugaku", R8, 700_000, KO, 7) - 1_580)

    def test_formula_rows_are_not_in_the_table(self) -> None:
        self.assertIsNone(wage_tax("getsugaku", R8, 740_000, KO))
        self.assertIsNone(wage_tax("nichigaku", R8, 24_000, KO))
        with self.assertRaises(ValueError):
            wage_tax("getsugaku", _dt.date(2027, 1, 25), 300_000, KO)


class TestBonusRate(unittest.TestCase):
    def test_boundaries(self) -> None:
        # 別表第四：R7 甲0人 68千円未満 0％・68千円以上 2％、R8 は 82千円。乙は 222千円未満 10％（R7）
        self.assertEqual(bonus_rate(R7, 67_999, KO), 0)
        self.assertEqual(bonus_rate(R7, 68_000, KO), Fraction(2, 100))
        self.assertEqual(bonus_rate(R8, 81_999, KO), 0)
        self.assertEqual(bonus_rate(R8, 82_000, KO), Fraction(2, 100))
        self.assertEqual(bonus_rate(R7, 221_999, OTSU), Fraction(10, 100))
        self.assertEqual(bonus_rate(R7, 222_000, OTSU), Fraction(20, 100))


if __name__ == "__main__":
    unittest.main()

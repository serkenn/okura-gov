"""給与所得の金額（所得税法第28条・別表第五、措置法第29条の4第2項）の境目のテスト（D15 ②）。

期待値の出典：
  - BOUNDARIES：docs/measurements/20261109_impl-prep_kyuyo-thresholds.md §2 の表（国税庁の資料の 35 項目と照合済み）。
    「給与所得 ≤ 所得要件」となる最大の給与収入。境目の給与収入で要件以下、その1円上で要件を超えることを確かめる。
  - NTA_R7・NTA_R8：国税庁「年末調整等のための給与所得控除後の給与等の金額の表」を人が書き写した区分
    （docs/public-sources/20261109_impl-prep_kyuyo-sources.md §4.5、scripts/IMPL_kyuyo_spotcheck.py の NTA_R7・NTA_R8。
    令和8年分の表は措置法第29条の4第2項を織り込んだもの）。
  - SPOT：docs/measurements/20261109_impl-prep_kyuyo-beppyo5.md §5・kyuyo-thresholds.md §4 の値。
  - 実測の出力 scripts/results/IMPL_kyuyo_thresholds/kyuyo_shotoku_samples.csv（令和7年分・令和8年分の 117 行）。
"""

from __future__ import annotations

import csv
import unittest

from okura_core import evaluate
from okura_core.rules.kyuyo.calc import KyuyoPath, kyuyo_shotoku, rules_from_parameters
from okura_core.result import YenAmount

from .support import REPO, make_ir, make_query, person, salary, system, wages_ir

# (年分, 項目, 合計所得金額の要件, 給与収入の上限)
BOUNDARIES = [
    (2025, "扶養親族", 580_000, 1_230_000),
    (2025, "勤労学生", 850_000, 1_500_000),
    (2025, "特定親族 85万", 850_000, 1_500_000),
    (2025, "特定親族 90万", 900_000, 1_550_000),
    (2025, "特定親族 95万", 950_000, 1_600_000),
    (2025, "特定親族 100万", 1_000_000, 1_650_000),
    (2025, "特定親族 105万", 1_050_000, 1_700_000),
    (2025, "特定親族 110万", 1_100_000, 1_750_000),
    (2025, "特定親族 115万", 1_150_000, 1_800_000),
    (2025, "特定親族 120万", 1_200_000, 1_850_000),
    (2025, "特定親族 123万", 1_230_000, 1_880_000),
    (2025, "源泉控除対象親族 100万", 1_000_000, 1_650_000),
    (2025, "配偶者特別控除の上限 133万", 1_330_000, 2_015_999),
    (2025, "基礎控除 132万", 1_320_000, 2_003_999),
    (2025, "基礎控除 336万", 3_360_000, 4_751_999),
    (2025, "基礎控除 489万", 4_890_000, 6_655_556),
    (2025, "基礎控除 655万", 6_550_000, 8_500_000),
    (2025, "基礎控除 2350万", 23_500_000, 25_450_000),
    (2026, "扶養親族", 620_000, 1_360_000),
    (2026, "勤労学生", 890_000, 1_630_000),
    (2026, "特定親族 85万", 850_000, 1_590_000),
    (2026, "特定親族 90万", 900_000, 1_640_000),
    (2026, "特定親族 95万", 950_000, 1_690_000),
    (2026, "特定親族 100万", 1_000_000, 1_740_000),
    (2026, "特定親族 105万", 1_050_000, 1_790_000),
    (2026, "特定親族 110万", 1_100_000, 1_840_000),
    (2026, "特定親族 115万", 1_150_000, 1_890_000),
    (2026, "特定親族 120万", 1_200_000, 1_940_000),
    (2026, "特定親族 123万", 1_230_000, 1_970_000),
    (2026, "配偶者特別控除の上限 133万", 1_330_000, 2_070_000),
    (2026, "基礎控除 132万", 1_320_000, 2_060_000),
    (2026, "基礎控除 336万", 3_360_000, 4_751_999),
    (2026, "基礎控除 489万", 4_890_000, 6_655_556),
    (2026, "基礎控除 655万", 6_550_000, 8_500_000),
    (2026, "基礎控除 2350万", 23_500_000, 25_450_000),
]

# 国税庁の表（下限, 上限, 値）。値は金額か ("minus", c) か ("rate_minus", 率%, c)。
NTA_R7 = [
    (0, 651_000, 0),
    (651_000, 1_900_000, ("minus", 650_000)),
    (1_900_000, 1_904_000, 1_250_000),
    (1_936_000, 1_940_000, 1_275_200),
    (2_000_000, 2_004_000, 1_320_000),
    (2_056_000, 2_060_000, 1_359_200),
    (2_060_000, 2_064_000, 1_362_000),
    (2_296_000, 2_300_000, 1_527_200),
    (2_456_000, 2_460_000, 1_639_200),
    (6_060_000, 6_064_000, 4_408_000),
    (6_256_000, 6_260_000, 4_564_800),
    (6_456_000, 6_460_000, 4_724_800),
    (6_596_000, 6_600_000, 4_836_800),
    (6_600_000, 8_500_000, ("rate_minus", 90, 1_100_000)),
    (8_500_000, 20_000_000, ("minus", 1_950_000)),
]
NTA_R8 = [
    (0, 741_000, 0),
    (741_000, 2_191_000, ("minus", 740_000)),
    (2_191_000, 2_193_000, 1_451_000),
    (2_193_000, 2_196_000, 1_453_000),
    (2_196_000, 2_200_000, 1_456_000),
    (2_200_000, 2_204_000, 1_460_000),
    (2_204_000, 2_208_000, 1_462_800),
    (2_380_000, 2_384_000, 1_586_000),
    (2_384_000, 2_388_000, 1_588_800),
    (2_580_000, 2_584_000, 1_726_000),
    (2_584_000, 2_588_000, 1_728_800),
    (2_780_000, 2_784_000, 1_866_000),
    (2_984_000, 2_988_000, 2_008_800),
    (3_180_000, 3_184_000, 2_146_000),
]

# (年分, 給与収入, 給与所得)
SPOT = [
    (2026, 690_999, 0),
    (2026, 691_000, 0),
    (2026, 740_999, 0),
    (2026, 741_000, 1_000),
    (2026, 1_360_000, 620_000),
    (2026, 2_190_999, 1_450_999),
    (2026, 2_199_999, 1_456_000),
    (2026, 2_200_000, 1_460_000),
    (2026, 2_036_000, 1_296_000),
    (2026, 1_900_000, 1_160_000),
    (2025, 1_230_000, 580_000),
    (2025, 650_999, 0),
    (2025, 651_000, 1_000),
    (2025, 20_000_000, 18_050_000),
    (2026, 20_000_000, 18_050_000),
    (2025, 25_450_000, 23_500_000),
]


def _expected(v: object, x: int) -> int:
    if isinstance(v, int):
        return v
    assert isinstance(v, tuple)
    if v[0] == "minus":
        return x - v[1]
    return x * v[1] // 100 - v[2]


def _rules(year: int):
    return rules_from_parameters(system().get_parameters_at_instant(f"{year}-01-01"))


class TestBoundaries(unittest.TestCase):
    def test_all_boundaries_of_the_thresholds_table(self) -> None:
        for year, item, req, max_wage in BOUNDARIES:
            with self.subTest(year=year, item=item):
                r = _rules(year)
                self.assertLessEqual(kyuyo_shotoku(max_wage, r).value, req)
                self.assertGreater(kyuyo_shotoku(max_wage + 1, r).value, req)

    def test_exact_values_named_in_the_task(self) -> None:
        self.assertEqual(kyuyo_shotoku(1_230_000, _rules(2025)).value, 580_000)
        self.assertEqual(kyuyo_shotoku(1_230_001, _rules(2025)).value, 580_001)
        self.assertEqual(kyuyo_shotoku(1_360_000, _rules(2026)).value, 620_000)
        self.assertEqual(kyuyo_shotoku(1_360_001, _rules(2026)).value, 620_001)



class TestAgainstNtaTables(unittest.TestCase):
    def _check(self, year: int, bands: list) -> None:
        r = _rules(year)
        for lo, up, v in bands:
            for x in sorted({lo, lo + 1, (lo + up) // 2, up - 1}):
                with self.subTest(year=year, x=x):
                    self.assertEqual(kyuyo_shotoku(x, r).value, _expected(v, x))

    def test_r7(self) -> None:
        self._check(2025, NTA_R7)

    def test_r8(self) -> None:
        self._check(2026, NTA_R8)

    def test_spot_values(self) -> None:
        for year, x, y in SPOT:
            with self.subTest(year=year, x=x):
                self.assertEqual(kyuyo_shotoku(x, _rules(year)).value, y)

    def test_measurement_samples(self) -> None:
        path = REPO / "scripts" / "results" / "IMPL_kyuyo_thresholds" / "kyuyo_shotoku_samples.csv"
        if not path.exists():
            self.skipTest(f"実測の出力がない: {path}")
        n = 0
        with path.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                year = int(row["income_year"])
                if year not in (2025, 2026):
                    continue
                n += 1
                with self.subTest(year=year, wage=row["wage"]):
                    self.assertEqual(kyuyo_shotoku(int(row["wage"]), _rules(year)).value, int(row["kyuyo_shotoku"]))
        self.assertEqual(n, 117)


class TestRules(unittest.TestCase):
    def test_paths(self) -> None:
        r7, r8 = _rules(2025), _rules(2026)
        self.assertEqual(kyuyo_shotoku(1_000_000, r7).path, KyuyoPath.BEPPYO5)
        self.assertEqual(kyuyo_shotoku(1_000_000, r8).path, KyuyoPath.SOCHI_29_4_2)
        self.assertEqual(kyuyo_shotoku(690_999, r8).path, KyuyoPath.BEPPYO5)
        self.assertEqual(kyuyo_shotoku(2_200_000, r8).path, KyuyoPath.BEPPYO5)
        self.assertEqual(kyuyo_shotoku(6_599_999, r8).path, KyuyoPath.BEPPYO5)
        self.assertEqual(kyuyo_shotoku(6_600_000, r8).path, KyuyoPath.ART28_2_3)

    def test_sochi_takes_precedence_over_beppyo5_in_r8(self) -> None:
        """令和8年分の別表第五（e-Gov）だけなら 1,360,000 → 670,000。措置法が優先して 620,000。"""
        r8 = _rules(2026)
        row = r8.table.row_for(1_360_000)
        self.assertEqual(1_360_000 - row.c, 670_000)
        self.assertEqual(kyuyo_shotoku(1_360_000, r8).value, 620_000)

    def test_660man_or_more_rounds_down_with_named_rule(self) -> None:
        r = _rules(2026)
        d = kyuyo_shotoku(6_655_556, r)  # 0.9 × 6,655,556 − 1,100,000 = 4,890,000.4
        self.assertEqual(d.value, 4_890_000)
        self.assertEqual(d.rounding.name, "floor_yen_kyuyo_shotoku_660man_or_more")
        self.assertEqual(kyuyo_shotoku(6_655_557, r).value, 4_890_001)
        self.assertEqual(kyuyo_shotoku(6_600_001, r).value, 4_840_000)
        self.assertEqual(kyuyo_shotoku(8_500_001, r).value, 6_550_001)

    def test_table_below_660man_has_only_fixed_and_minus(self) -> None:
        for year in (2025, 2026):
            t = _rules(year).table
            kinds = {row.kind for row in t.rows if row.lower < 6_600_000}
            self.assertEqual(kinds, {"fixed", "minus"})

    def test_rejects_non_integer_income(self) -> None:
        r = _rules(2026)
        for bad in (1.5, True, "100", -1):
            with self.subTest(bad=bad), self.assertRaises((ValueError, TypeError)):
                kyuyo_shotoku(bad, r)  # type: ignore[arg-type]




if __name__ == "__main__":
    unittest.main()

"""組合事業・信託（措法41の4の2）と国外中古建物（措法41の4の3）の不動産所得の損失（rental_special.py。IK-104）の境目。

期待値：docs/inferences/20261112_impl-research5_fudosan-special-cases.md（式は docs/public-sources/20261112_impl-research5_fudosan-special-losses.md
§2〜§4：措令26の6の2④、26の6の3①②、措通41の4−4）。
"""

from __future__ import annotations

import unittest

from okura_core.rules.income_kinds import rental_special as rsp

U = rsp.Unit


class TestArrangement(unittest.TestCase):
    def test_specified_member_loss_per_arrangement(self) -> None:
        units = [
            U("p1", rsp.ARRANGEMENT, -300, arrangement="partnership:A", specified=True),
            U("p2", rsp.ARRANGEMENT, 100, arrangement="partnership:A", specified=True),
            U("p3", rsp.ARRANGEMENT, 50, arrangement="trust:B", specified=True),
            U("d1", rsp.DOMESTIC, 500),
        ]
        # 組合A は 総収入金額の合計が必要経費の合計に 200 満たない。信託B は黒字。国内の黒字とは通算しない
        self.assertEqual(rsp.deemed(units).by_arrangement, {"partnership:A": 200})

    def test_not_specified_member(self) -> None:
        units = [U("p1", rsp.ARRANGEMENT, -300, arrangement="partnership:A", specified=False)]
        self.assertEqual(rsp.deemed(units).total, 0)  # 重要業務の執行に関与し自ら執行：特定組合員でない


class TestForeignUsed(unittest.TestCase):
    def test_example_with_other_foreign_income(self) -> None:
        units = [
            U("A", rsp.FOREIGN_USED, -300, building_dep=200),  # 損失≧償却費：償却費 200（②二の超過 100）
            U("B", rsp.FOREIGN_USED, -50, building_dep=100),  # 償却費＞損失：損失 50
            U("C", rsp.FOREIGN_OTHER, 150),  # 国外不動産等の所得 150 → 150−100＝50 を控除
            U("D", rsp.DOMESTIC, 1000),
        ]
        self.assertEqual(rsp.foreign_used_loss(units), 200)

    def test_other_foreign_loss_does_not_reduce(self) -> None:
        units = [U("A", rsp.FOREIGN_USED, -300, building_dep=200), U("C", rsp.FOREIGN_OTHER, -10)]
        self.assertEqual(rsp.foreign_used_loss(units), 200)

    def test_profit_building(self) -> None:
        self.assertEqual(rsp.foreign_used_loss([U("A", rsp.FOREIGN_USED, 10, building_dep=200)]), 0)


class TestLandInterest(unittest.TestCase):
    def test_tsutatsu_41_4_4(self) -> None:
        # 措通41の4−4：利子 80 が生じなかったものとみなされる金額 200 以下なら利子はなかったもの（80 を差し引く）、利子 300 なら超える 100 だけ残す
        self.assertEqual(rsp.land_interest_after_arrangements({"partnership:A": 80}, {"partnership:A": 200}), 80)
        self.assertEqual(rsp.land_interest_after_arrangements({"partnership:A": 300}, {"partnership:A": 200}), 200)
        self.assertEqual(rsp.land_interest_after_arrangements({"partnership:A": 300}, {}), 0)


if __name__ == "__main__":
    unittest.main()

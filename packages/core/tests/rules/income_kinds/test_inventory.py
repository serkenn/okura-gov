"""income_kinds の棚卸資産・家事消費等・貸倒れの純粋関数の境目（inventory.py。IK-108〜IK-110）。

出典：docs/public-sources/20261112_impl-research6_tanaoroshi-laws-and-nta.md（PS）、仮説 docs/hypotheses/20261112_impl-research6_tanaoroshi-model.md（H）。
テストのデータは架空。
"""

from __future__ import annotations

import datetime as dt
import unittest
from typing import Any

from okura_core.rules.income_kinds import inventory as inv


def notice(nid: str, on: str, procedure: str, method: str, lower: bool = False, asset_class: str | None = None) -> dict[str, Any]:
    a: dict[str, Any] = {"business_id": "b1", "procedure": procedure, "method": method, "lower_of_cost": lower}
    if asset_class:
        a["asset_class"] = asset_class
    return {"id": nid, "kind": "inventory_method_notice", "roles": {"person": "p1"}, "when": {"on": on}, "attributes": a}


def count(cid: str, on: str, value: int, method: str = "final_purchase_cost", lower: bool = False, opening: bool = False) -> dict[str, Any]:
    a: dict[str, Any] = {"business_id": "b1", "valuation_method": method, "lower_of_cost": lower}
    if opening:
        a["count_type"] = "opening"
    return {"id": cid, "kind": "inventory_count", "roles": {"owner": "p1"}, "when": {"on": on}, "amounts": {"valuation": value}, "attributes": a}


START = dt.date(2020, 4, 1)


class TestMethodInForce(unittest.TestCase):
    """所令100②・101・99の2・102①（PS §2.2・§2.3、H2）。"""

    def test_no_notice_is_final_purchase_cost(self) -> None:
        self.assertEqual(inv.method_in_force([], START, 2025, None), (("final_purchase_cost", False), ()))

    def test_selection_deadline_is_return_deadline_of_start_year(self) -> None:
        # 2021-03-15 は月曜日：その日までの届出は選定、翌日は選定しなかった（法定の方法）
        on_time = notice("n1", "2021-03-15", "selection_notice", "total_average")
        late = notice("n2", "2021-03-16", "selection_notice", "total_average")
        self.assertEqual(inv.method_in_force([on_time], START, 2025, None)[0], ("total_average", False))
        self.assertEqual(inv.method_in_force([late], START, 2025, None)[0], ("final_purchase_cost", False))

    def test_selection_deadline_moves_past_weekend(self) -> None:
        # 2025-03-15 は土曜日：期限は 2025-03-17（月）。業務の開始は 2024 年
        n = notice("n1", "2025-03-17", "selection_notice", "fifo")
        self.assertEqual(inv.method_in_force([n], dt.date(2024, 6, 1), 2025, None)[0], ("fifo", False))

    def test_change_application_by_march_15_applies_that_year_unless_rejected(self) -> None:
        app = notice("n1", "2025-03-15", "change_application", "moving_average")
        self.assertEqual(inv.method_in_force([app], START, 2025, None)[0], ("moving_average", False))  # 所令101⑤：処分がなければ承認とみなす
        after = notice("n2", "2025-03-16", "change_application", "moving_average")
        self.assertEqual(inv.method_in_force([after], START, 2025, None)[0], ("final_purchase_cost", False))
        self.assertEqual(inv.method_in_force([after], START, 2026, None)[0], ("moving_average", False))
        rejected = notice("n3", "2025-06-01", "change_rejected", "moving_average")
        self.assertEqual(inv.method_in_force([app, rejected], START, 2025, None)[0], ("final_purchase_cost", False))

    def test_special_method_from_year_of_approval(self) -> None:
        n = notice("n1", "2025-11-01", "special_method_approved", "special_approved")
        self.assertEqual(inv.method_in_force([n], START, 2024, None)[0], ("final_purchase_cost", False))
        self.assertEqual(inv.method_in_force([n], START, 2025, None)[0], ("special_approved", False))


class TestValueCounts(unittest.TestCase):
    def test_business_needs_the_method_in_force(self) -> None:
        c = [count("c1", "2025-12-31", 300_000, method="fifo")]
        v = inv.value_counts(c, business=True, notices=[], start=START, year=2025, blue=False)
        self.assertIsNone(v.value)
        self.assertEqual(v.reason, inv.METHOD_MISSING_REASON)
        c.append(count("c2", "2025-12-31", 280_000))
        self.assertEqual(inv.value_counts(c, business=True, notices=[], start=START, year=2025, blue=False).value, 280_000)

    def test_lower_of_cost_only_with_blue(self) -> None:
        # 所令99① かっこ書：青色申告の承認がない年分は原価法だけ（届出の低価法の基礎の原価法の額：H2-3）
        n = [notice("n1", "2021-03-01", "selection_notice", "total_average", lower=True)]
        c = [count("c1", "2025-12-31", 90_000, method="total_average", lower=True), count("c2", "2025-12-31", 100_000, method="total_average")]
        self.assertEqual(inv.value_counts(c, business=True, notices=n, start=START, year=2025, blue=True).value, 90_000)
        white = inv.value_counts(c, business=True, notices=n, start=START, year=2025, blue=False)
        self.assertEqual((white.value, white.reading), (100_000, True))

    def test_misc_two_methods_with_different_amounts(self) -> None:
        c = [count("c1", "2025-12-31", 100, method="fifo"), count("c2", "2025-12-31", 120)]
        self.assertEqual(inv.value_counts(c, business=False, notices=[], start=START, year=2025, blue=False).reason, inv.MISC_METHODS_REASON)


class TestInventoryFor(unittest.TestCase):
    """売上原価＝期首＋仕入－期末（所法37①・47①：PS §1.1・§1.2、H1）。"""

    def run_for(self, counts: list[dict[str, Any]], judgments: dict[int, tuple[bool, str]] | None = None, start: dt.date = START, activity: bool = True) -> inv.InventoryResult:
        return inv.inventory_for(
            counts=counts, notices=[], judgments=judgments or {}, business=True, start=start, year=2025,
            year_end=dt.date(2025, 12, 31), blue={}, has_activity=activity,
        )  # fmt: skip

    def test_purchases_without_any_count_are_not_expensed_silently(self) -> None:
        self.assertEqual(self.run_for([]).problem, inv.UNKNOWN_CLOSING_REASON)

    def test_no_activity_no_record_is_not_relevant(self) -> None:
        r = self.run_for([], activity=False)
        self.assertEqual((r.relevant, r.problem, r.opening, r.closing), (False, None, 0, 0))

    def test_judgment_no_inventory_gives_zero_closing(self) -> None:
        r = self.run_for([count("c0", "2024-12-31", 50_000)], judgments={2025: (False, "j1")})
        self.assertEqual((r.problem, r.opening, r.closing), (None, 50_000, 0))

    def test_opening_from_prior_year_end_and_started_this_year(self) -> None:
        r = self.run_for([count("c0", "2024-12-31", 40_000), count("c1", "2025-12-31", 70_000)])
        self.assertEqual((r.opening, r.closing), (40_000, 70_000))
        new = self.run_for([count("c1", "2025-12-31", 70_000)], start=dt.date(2025, 5, 1))
        self.assertEqual((new.problem, new.opening, new.closing), (None, 0, 70_000))

    def test_unknown_opening(self) -> None:
        self.assertEqual(self.run_for([count("c1", "2025-12-31", 70_000)]).problem, inv.UNKNOWN_OPENING_REASON)
        r = self.run_for([count("c1", "2025-12-31", 70_000)], judgments={2024: (False, "j0")})
        self.assertEqual((r.problem, r.opening), (None, 0))

    def test_year_end_is_death_date(self) -> None:
        r = inv.inventory_for(
            counts=[count("c0", "2024-12-31", 10), count("c1", "2025-08-31", 30)], notices=[], judgments={}, business=True, start=START,
            year=2025, year_end=dt.date(2025, 8, 31), blue={}, has_activity=True,
        )  # fmt: skip
        self.assertEqual((r.opening, r.closing), (10, 30))


class TestHouseholdAndBadDebts(unittest.TestCase):
    def rec(self, price: int | None, booked: int | None = None, cost: int | None = None) -> dict[str, Any]:
        a = {k: v for k, v in (("normal_sales_price", price), ("recorded_amount", booked), ("acquisition_cost", cost)) if v is not None}
        return {"id": "h1", "amounts": a, "attributes": {"business_id": "b1", "event": "household_use"}}

    def test_seventy_percent_boundary(self) -> None:
        # 所基通39−2：取得価額以上で、通常の販売価額のおおむね70%以上なら帳簿の額（ちょうど70%は認める読み：H5）
        self.assertEqual(inv.household_amount(self.rec(10_000, 7_000, 6_000), business=True), (7_000, True))
        self.assertEqual(inv.household_amount(self.rec(10_000, 6_999, 6_000), business=True), (10_000, False))
        self.assertEqual(inv.household_amount(self.rec(10_000, 8_000, 8_001), business=True), (10_000, False))  # 取得価額未満
        self.assertEqual(inv.household_amount(self.rec(10_000, 8_000, 6_000), business=False), (10_000, False))  # 業務は 39−1
        self.assertEqual(inv.household_amount(self.rec(None, 8_000, 6_000), business=True), (None, False))

    def test_bad_debt_routes_and_cap(self) -> None:
        sales = {"attributes": {"event": "uncollectible", "receivable_type": "sales"}}
        loan = {"attributes": {"event": "uncollectible", "receivable_type": "loan"}}
        self.assertEqual(inv.bad_debt_route(sales, business_scale=True), "51-2")
        self.assertEqual(inv.bad_debt_route(sales, business_scale=False), "64-1")
        self.assertEqual(inv.bad_debt_route(loan, business_scale=False), "51-4")
        # 所令180②二：その所得の黒字の額が上限、赤字なら0（PS §1.4）
        self.assertEqual(inv.deemed_uncollectible(50_000, 80_000), 50_000)
        self.assertEqual(inv.deemed_uncollectible(50_000, 30_000), 30_000)
        self.assertEqual(inv.deemed_uncollectible(50_000, -1), 0)


if __name__ == "__main__":
    unittest.main()

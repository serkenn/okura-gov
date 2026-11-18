"""給与の年分（所基通36−9）、死亡後の給与（所基通9−17）、通勤手当の非課税（所令20の2）、源泉徴収票の優先（D23 K4）、給与所得控除額のテスト。

期待値の出典：
  - 年分・死亡：docs/public-sources/20261111_impl-research_kyuyo-jiki-laws-and-nta.md §2・§3、docs/inferences/20261111_impl-research_kyuyo-jiki-cases.md IJ1〜IJ3。
  - 通勤手当：docs/public-sources/20261111_impl-research_tsukin-laws-and-nta.md §2.2・§2.3・§4.4（R8QA のケースA〜E、Q4-2）、
    docs/inferences/20261111_impl-research_tsukin-cases.md IT1〜IT4。
  - 給与所得控除額：docs/public-sources/20261109_impl-prep_kyuyo-sources.md §2.1（措法第29条の4第1項）、所得税法第28条第3項（scripts/results/IMPL_kyuyo_fetch/articles_shotoku_*.txt）。
テストのデータはすべて架空。
"""

from __future__ import annotations

import datetime as _dt
import unittest
from fractions import Fraction
from typing import Any

from openfisca_core.simulation_builder import SimulationBuilder

from okura_core import evaluate
from okura_core.money import YenRange
from okura_core.result import State, TimeKey, YenAmount
from okura_core.rules.kyuyo.calc import deduction_rules_from_parameters, kyuyo_deduction
from okura_core.rules.kyuyo.inputs import _death_class
from okura_core.rules.kyuyo.tsukin import Item, monthly_limit, nontaxable_bounds, parking_monthly, version_for, versions_from_parameters

from .support import make_ir, make_query, person, salary, system

T26 = TimeKey("tax_year", 2026)
T25 = TimeKey("tax_year", 2025)
INCOME = "所得税.給与等の収入金額"


def _ok(res: Any) -> Any:
    if not res.ok:
        raise AssertionError(res.to_dict())
    return res


def _value(ir: dict[str, Any], year: int, pid: str = "p-1", concept: str = INCOME) -> Any:
    return _ok(evaluate(ir, make_query((year,)), system=system())).scenario("base").value(concept, pid, TimeKey("tax_year", year))


def _versions(year: int = 2026) -> Any:
    return versions_from_parameters(system().get_parameters_at_instant(f"{year}-01-01"))


def _status(rid: str, pid: str, means: str, *, km: tuple[int, int] | None = None, parkings: list[dict[str, Any]] | None = None, payer: str = "架空の会社", from_on: str = "2025-01-01") -> dict[str, Any]:
    attrs: dict[str, Any] = {"counterparty": payer, "means": means}
    if km is not None:
        attrs["one_way_km"] = {"num": km[0], "den": km[1]}
    if parkings is not None:
        attrs["parkings"] = parkings
    return {"id": rid, "kind": "commuting_status", "roles": {"worker": pid}, "when": {"from_on": from_on}, "attributes": attrs}


def _fare(jid: str, pid: str, amount: int, *, from_on: str = "2025-01-01", payer: str = "架空の会社") -> dict[str, Any]:
    return {
        "id": jid, "kind": "判断.通勤の合理的な運賃", "judged_by": {"person": pid}, "judged_at": "2026-02-01T09:00:00+09:00",
        "subject": {"person": pid, "counterparty": payer}, "when": {"from_on": from_on}, "value": {"monthly_amount": amount},
    }  # fmt: skip


def _paid(on: str, gross: int, allowance: int, *, rid: str = "s", pid: str = "p-1", due_on: str | None = None, payer: str = "架空の会社", **attrs: Any) -> dict[str, Any]:
    rec = salary(rid, pid, on, gross, due_on=due_on, counterparty=payer)
    rec["amounts"]["commuting_allowance"] = allowance
    rec["attributes"].update(attrs)
    return rec




class AfterDeathTest(unittest.TestCase):
    """死亡後に支給期の到来する給与（所基通9−17、質疑応答事例 7/05）。"""

    deceased = {"id": "p-1", "birth_on": "1950-01-01", "death_on": "2026-03-15"}






    def test_death_class_pure_function(self) -> None:
        death = _dt.date(2026, 3, 15)
        for due, stipulated, expected in (
            ("2026-03-14", True, "before"), ("2026-03-15", True, "open"), ("2026-03-16", True, "after"),
            ("2026-03-14", False, "before"), ("2026-03-16", False, "open"),
        ):  # fmt: skip
            rec = {"attributes": {"due_on": due, "due_stipulated": stipulated}}
            self.assertEqual(_death_class(rec, death), expected, (due, stipulated))
        self.assertEqual(_death_class({"attributes": {"due_on": "2026-05-01"}}, None), "before")


class CommutingLimitTest(unittest.TestCase):
    """限度額（所令20の2。支給日で表を選ぶ）。"""

    def test_version_selected_by_due_date(self) -> None:
        v = _versions()
        self.assertEqual(version_for(v, _dt.date(2025, 3, 31)).key, "改正前")
        self.assertEqual(version_for(v, _dt.date(2025, 4, 1)).key, "令和7年4月以後")
        self.assertEqual(version_for(v, _dt.date(2026, 3, 31)).key, "令和7年4月以後")
        self.assertEqual(version_for(v, _dt.date(2026, 4, 1)).key, "令和8年4月以後")

    def test_distance_table_values(self) -> None:
        # §2.2 の表
        table = {
            "改正前": [(Fraction(2), 4200), (Fraction(10), 7100), (Fraction(50), 28000), (Fraction(55), 31600), (Fraction(100), 31600)],
            "令和7年4月以後": [(Fraction(10), 7300), (Fraction(50), 32300), (Fraction(55), 38700), (Fraction(100), 38700)],
            "令和8年4月以後": [(Fraction(55), 38700), (Fraction(65), 45700), (Fraction(75), 52700), (Fraction(85), 59600), (Fraction(95), 66400)],
        }
        versions = {v.key: v for v in _versions()}
        for key, rows in table.items():
            for km, amount in rows:
                self.assertEqual(versions[key].amount_for(km), amount, (key, km))
        self.assertIsNone(versions["令和8年4月以後"].amount_for(Fraction(199, 100)))  # 2km 未満は第2号の対象外
        self.assertEqual(versions["令和8年4月以後"].amount_for(Fraction(2)), 4200)

    def _r8(self) -> Any:
        return next(v for v in _versions() if v.key == "令和8年4月以後")

    def test_transit_limit_is_the_fare_up_to_the_cap(self) -> None:
        v = self._r8()
        self.assertEqual(monthly_limit({"means": "transit"}, 6_000, v).low, 6_000)
        self.assertEqual(monthly_limit({"means": "transit"}, 200_000, v).high, 150_000)
        unknown = monthly_limit({"means": "transit"}, None, v)
        self.assertEqual((unknown.low, unknown.high, unknown.needs_fare), (0, 150_000, True))

    def test_vehicle_limit(self) -> None:
        v = self._r8()
        st = {"means": "vehicle", "one_way_km": {"num": 50, "den": 1}}
        self.assertEqual(monthly_limit(st, None, v).low, 32_300)
        short = {"means": "vehicle", "one_way_km": {"num": 1, "den": 1}}
        self.assertEqual(monthly_limit(short, None, v).high, 0)

    def test_nta_cases(self) -> None:
        # R8QA ケース A〜E・Q4-2（§4.4）
        v = self._r8()
        parking = lambda fee: [{"location": "near_workplace", "fee_unit": "month", "fee": fee}]  # noqa: E731
        car = lambda fee: {"means": "vehicle", "one_way_km": {"num": 50, "den": 1}, "parkings": parking(fee)}  # noqa: E731
        cases = [
            ("A", car(8_000), None, 40_300, 37_300),
            ("B", car(8_000), None, 36_000, 37_300),
            ("C", car(4_400), None, 37_400, 36_700),
            ("D", car(8_000), None, 35_000, 37_300),
            ("Q4-2", car(6_000), None, 38_300, 37_300),
            ("E", {"means": "transit_and_vehicle", "one_way_km": {"num": 50, "den": 1}, "parkings": parking(4_000)}, 115_000, 151_300, 150_000),
        ]
        for name, status, fare, allowance, limit_expected in cases:
            with self.subTest(case=name):
                lim = monthly_limit(status, fare, v)
                self.assertEqual(lim.high, limit_expected)
                self.assertEqual(min(allowance, lim.high), min(allowance, limit_expected))

    def test_parking_equivalent(self) -> None:
        v = self._r8()
        self.assertEqual(parking_monthly([{"location": "home", "fee_unit": "month", "fee": 8000}], v)[0], 0)
        lots = [
            {"location": "near_workplace", "fee_unit": "month", "fee": 2000},
            {"location": "near_transit_facility", "fee_unit": "year", "fee": 12000},
        ]
        self.assertEqual(parking_monthly(lots, v)[0], 3000)
        # Q3-3 例2：1,200円 ÷ 11枚 × 20日 → 1円未満切上げ
        per_use = [{"location": "near_workplace", "fee_unit": "per_use", "fee": 1200, "uses_per_month": 20}]
        self.assertEqual(parking_monthly(per_use, v)[0], 5000)  # 上限
        cheap = [{"location": "near_workplace", "fee_unit": "other", "fee": 100, "fee_period_days": 365}]
        self.assertEqual(parking_monthly(cheap, v), (9, ("ceil_yen_commuting_parking",)))
        # 改正前・R7 は駐車場等の号がない
        r7 = next(x for x in _versions() if x.key == "令和7年4月以後")
        self.assertEqual(parking_monthly(lots, r7)[0], 0)


class NontaxableReadingsTest(unittest.TestCase):
    """読みの分かれるところ（UT1〜UT3）は両端で評価する。"""

    def test_multi_month(self) -> None:
        # 1か月分と6か月分：通勤手当 60,000 を6か月分で一度に支給、月の限度額 10,000
        item = Item(60_000, 10_000, 6, "A", (2026, 4), (2026, 4))
        self.assertEqual(nontaxable_bounds([item]), (10_000, 60_000))

    def test_two_payers(self) -> None:
        a = Item(30_000, 20_000, 1, "A", (2026, 5), (2026, 5))
        b = Item(5_000, 20_000, 1, "B", (2026, 5), (2026, 5))
        # 支払者ごとなら 20,000+5,000、合計なら min(35,000, 20,000)=20,000
        self.assertEqual(nontaxable_bounds([a, b]), (20_000, 25_000))

    def test_paid_month_differs(self) -> None:
        a = Item(10_000, 10_000, 1, "A", (2026, 5), (2026, 6))
        b = Item(10_000, 10_000, 1, "A", (2026, 6), (2026, 6))
        self.assertEqual(nontaxable_bounds([a, b]), (10_000, 20_000))

    def test_no_gap_when_equal(self) -> None:
        a = Item(5_000, 20_000, 1, "A", (2026, 5), (2026, 5))
        self.assertEqual(nontaxable_bounds([a]), (5_000, 5_000))






class DeductionTest(unittest.TestCase):
    """所得税_給与所得控除額（所得税法第28条第3項、措置法第29条の4第1項）。"""

    def _deduction(self, year: int, income: int) -> Fraction:
        rules = deduction_rules_from_parameters(system().get_parameters_at_instant(f"{year}-01-01"))
        return kyuyo_deduction(income, rules).amount

    def test_r7(self) -> None:
        for income, expected in (
            (100_000, 650_000), (1_900_000, 650_000), (2_500_000, 650_000 + 600_000 * Fraction(30, 100)),
            (3_600_000, 650_000 + 1_700_000 * Fraction(30, 100)), (6_600_000, 1_160_000 + 3_000_000 * Fraction(20, 100)),
            (7_000_000, 1_760_000 + 400_000 * Fraction(10, 100)), (9_000_000, 1_950_000),
        ):  # fmt: skip
            self.assertEqual(self._deduction(2025, income), expected, income)

    def test_r8_sochi_and_base(self) -> None:
        for income, expected in (
            (700_000, 700_000), (740_000, 740_000), (2_200_000, 740_000),
            (2_500_000, 80_000 + 2_500_000 * Fraction(30, 100)), (3_600_000, 80_000 + 3_600_000 * Fraction(30, 100)),
            (5_000_000, 1_160_000 + 1_400_000 * Fraction(20, 100)),
        ):  # fmt: skip
            self.assertEqual(self._deduction(2026, income), expected, income)

    def test_variable_rounds_with_the_candidate(self) -> None:
        for year, income, candidate, expected in ((2026, 3_000_001, "floor", 980_000), (2026, 3_000_001, "ceil", 980_001), (2026, 2_500_000, "ceil", 830_000)):
            sim = SimulationBuilder().build_from_entities(
                system(),
                {
                    "人物一覧": {"p": {"所得税_給与等の収入金額": {str(year): income}, "所得税_給与所得控除額の端数の候補": {str(year): candidate}}},
                    "扶養所属一覧": {"h": {"申告者一覧": ["p"]}},
                    "法律婚一覧": {"m": {"配偶者一覧": ["p"]}},
                    "健康保険一覧": {"k": {"対象外一覧": ["p"]}},
                },
            )
            self.assertEqual(int(sim.calculate("所得税_給与所得控除額", str(year))[0]), expected, (income, candidate))


if __name__ == "__main__":
    unittest.main()

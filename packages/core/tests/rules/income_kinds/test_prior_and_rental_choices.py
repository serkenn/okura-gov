"""income_kinds の前々年分の収入金額・現金主義の選択（prior_years.py）と、不動産所得の区分の材料・計上の方法（rental_choices.py）の境目。

IK-64・IK-114〜IK-120（2026-11-12）。出典：docs/public-sources/20261109_impl-prep_jigyo-laws-and-nta.md §4.1・§4.3（所令196の2 の300万円、所法120⑥ の1,000万円）、
docs/public-sources/20261109_round2b_fudosan-laws-and-nta.md §1.2（所令79①一）・§1.3（基通27−2）・§2.2（直所2−78 3(1)（注）の11か月分）・§4.3（措令26の6②・措通41の4−3）。
上流の値（判断の値・パラメータ）はスタブで与える。テストのデータは架空。
"""

from __future__ import annotations

import datetime as dt
import unittest
from types import SimpleNamespace
from typing import Any

from openfisca_core.simulation_builder import SimulationBuilder

from okura_core.registry import ModuleInputs
from okura_core.rules.income_kinds import prior_years as py
from okura_core.rules.income_kinds import rental_choices as rc

from ...support import system

RENT_VARS = ("所得税_不動産所得の総収入金額", "所得税_不動産所得の必要経費", "所得税_不動産所得の減価償却費")
SIDE_VARS = {"biz": ("b",), "misc": ("m",), "rental": RENT_VARS}


class Ctx:
    """YearContext のスタブ（build_inputs の窓口のうち使うものだけ）。"""

    def __init__(self, year: int, records: list[dict[str, Any]], choices: list[dict[str, Any]] = (), judgments: list[dict[str, Any]] = (),
                 scale: bool = False, filing_on: str | None = None) -> None:  # fmt: skip
        self.year = year
        self.persons = ("p1",)
        self._records = records
        self.ir = {"facts": [r for r in records if r["kind"] not in ("rental_property", "lease", "loan")],
                   "assets": [r for r in records if r["kind"] in ("rental_property", "lease", "loan")],
                   "relations": [], "residences": [], "insurance_memberships": [], "filed_documents": [],
                   "choices": list(choices), "judgments": list(judgments)}  # fmt: skip
        self.parameters = SimpleNamespace(所得税=SimpleNamespace(業務に係る雑所得の前々年分の収入金額の基準=SimpleNamespace(現金主義の上限=3_000_000)))
        self.filing_date = SimpleNamespace(on=dt.date.fromisoformat(filing_on)) if filing_on else None
        self._scale = scale

    def records(self, kind: str) -> list[dict[str, Any]]:
        return [r for r in self._records if r["kind"] == kind]

    def choices(self, kind: str) -> list[dict[str, Any]]:
        return [c for c in self.ir["choices"] if c["kind"] == kind]

    def judgments(self, kind: str) -> list[dict[str, Any]]:
        return [j for j in self.ir["judgments"] if j["kind"] == kind]

    def decision(self, kind: str, key: str) -> Any:
        assert kind == rc.K_RENT_SCALE
        return SimpleNamespace(value=self._scale, record_ids=(), states=())


def prior(rid: str, year: int, revenue: int, fixed_on: str | None = None, bid: str | None = "b1") -> dict[str, Any]:
    a: dict[str, Any] = {"income_source": "miscellaneous_business"}
    if bid:
        a["business_id"] = bid
    if fixed_on:
        a["fixed_on"] = fixed_on
    return {"id": rid, "kind": "prior_income_fixed", "roles": {"person": "p1"}, "when": {"tax_year": year}, "amounts": {"revenue": revenue}, "attributes": a}


def cash_choice(value: bool, year: int = 2026) -> dict[str, Any]:
    return {"id": f"c-cash-{value}", "kind": py.K_CASH, "subject": {"person": "p1", "business_id": "b1"}, "when": {"tax_year": year}, "value": value}


def flow(rid: str, on: str, amount: int, period: tuple[str, str] | None = None, ftype: str = "rent", prop: str = "prop1") -> dict[str, Any]:
    a: dict[str, Any] = {"flow_type": ftype, "property_id": prop}
    if period:
        a["covered_period"] = {"from_on": period[0], "to_on": period[1]}
    return {"id": rid, "kind": "rent_flow", "roles": {"recipient": "p1"}, "when": {"on": on}, "amounts": {"amount": amount}, "attributes": a}


def prop(pid: str = "prop1", ptype: str = "building", **attrs: Any) -> dict[str, Any]:
    return {"id": pid, "kind": "rental_property", "roles": {"owner": "p1"}, "when": {"from_on": "2020-01-01"}, "amounts": attrs.pop("amounts", {}),
            "attributes": {"property_type": ptype, **attrs}}  # fmt: skip


def period_choice(year: int, target: str = "prop1", apply: bool = True, rule: str = rc.RULE_PERIOD) -> dict[str, Any]:
    return {"id": f"c-{rule}-{year}-{target}", "kind": rc.K_RENT_TIMING, "subject": {"record_id": target}, "when": {"tax_year": year},
            "value": {"rule": rule, "apply": apply}}  # fmt: skip


def material(target: str, **value: Any) -> dict[str, Any]:
    return {"id": f"j-{target}", "kind": rc.K_RENT_MATERIAL, "subject": {"record_id": target}, "value": value}


class TestCashBasis(unittest.TestCase):
    """所法67②・所令196の2（300万円以下）・所基通67−6（前年末現在で確定）。現金主義は後の段（D21 R3）。"""

    def run_(self, recs: list[dict[str, Any]], choice: dict[str, Any], side: str = "misc") -> list[str]:
        problems: list[Any] = []
        py.cash_basis(Ctx(2026, recs, [choice]), "p1", problems, {"b1": side}, SIDE_VARS, {})
        return [t for t, _, _ in problems]

    def test_limit_is_inclusive(self) -> None:
        self.assertEqual(self.run_([prior("f1", 2024, 3_000_000)], cash_choice(True)), [py.CASH_BASIS_REASON])
        self.assertEqual(self.run_([prior("f1", 2024, 3_000_001)], cash_choice(True)), [py.CASH_INELIGIBLE_REASON])

    def test_fixed_after_prior_year_end_is_not_counted(self) -> None:
        self.assertEqual(self.run_([prior("f1", 2024, 5_000_000, fixed_on="2026-01-10")], cash_choice(True)), [py.CASH_BASIS_REASON])

    def test_false_choice_and_business_income(self) -> None:
        self.assertEqual(self.run_([], cash_choice(False)), [])
        self.assertEqual(self.run_([], cash_choice(True), side="biz"), [py.CASH_NOT_MISC_REASON])


class TestPriorRevenue(unittest.TestCase):
    """所法120⑥（1,000万円超）・所基通120−4の2（提出の時までに確定）。"""

    def test_source_value_is_in_the_vocabulary(self) -> None:
        # 2026-11-13：実際の家庭を通したとき、語彙の値（miscellaneous_business）と読む値（misc_business）が違い、記録を読めなかった
        from okura_ir.vocabulary import FACT_KINDS

        kind = next(k for k in FACT_KINDS if k.kind == "prior_income_fixed")
        self.assertIn(py.MISC_SOURCE, kind.attributes["income_source"].schema["enum"])

    def test_missing_record_is_undetermined_only_with_misc_business(self) -> None:
        out = ModuleInputs()
        py.write_prior(Ctx(2026, []), out, "p1", has_misc=True)
        self.assertTrue(out.values[(py.V_PRIOR, "p1")].missing)
        out = ModuleInputs()
        py.write_prior(Ctx(2026, []), out, "p1", has_misc=False)
        self.assertFalse(out.values[(py.V_PRIOR, "p1")].missing)

    def test_sum_and_filing_date(self) -> None:
        recs = [prior("f1", 2024, 6_000_000), prior("f2", 2024, 5_000_000, fixed_on="2027-04-01", bid="b2"), prior("f3", 2023, 9_000_000)]
        out = ModuleInputs()
        py.write_prior(Ctx(2026, recs, filing_on="2027-03-10"), out, "p1", has_misc=True)
        self.assertEqual(out.values[(py.V_PRIOR, "p1")].value, 6_000_000)

    def test_attach_formula_boundary(self) -> None:
        def calc(prior_rev: int, misc_rev: int) -> bool:
            data = {py.V_PRIOR: {"2026": prior_rev}, "所得税_業務に係る雑所得の総収入金額": {"2026": misc_rev}}
            sim = SimulationBuilder().build_from_entities(system(), {"人物一覧": {"p": data}})
            return bool(sim.calculate("所得税_業務に係る雑所得の収支内訳書の添付を要するか", "2026")[0])

        self.assertFalse(calc(10_000_000, 1))
        self.assertTrue(calc(10_000_001, 1))
        self.assertFalse(calc(10_000_001, 0))  # その年分に業務に係る雑所得がない


class TestPeriodMatching(unittest.TestCase):
    """直所2−78（期間対応）。"""

    def amounts(self, ctx: Ctx) -> dict[str, int]:
        view = rc.RentView(ctx)
        return {f["id"]: f["amounts"]["amount"] for f in view.records("rent_flow") if f["when"]["on"].startswith(str(ctx.year))}

    def test_first_year_counts_eleven_months_of_prepaid_monthly_rent(self) -> None:
        # 前月払の月額賃貸料：期間対応を始めた年分は11か月分（直所2−78 3(1)（注））
        recs = [prop()] + [flow("f2025-12", "2025-12-25", 100_000, ("2026-01-01", "2026-01-31"))]
        recs += [flow(f"f2026-{m:02d}", f"2026-{m:02d}-25", 100_000, (f"2026-{m + 1:02d}-01", f"2026-{m + 1:02d}-28")) for m in range(1, 12)]
        recs += [flow("f2026-12", "2026-12-25", 100_000, ("2027-01-01", "2027-01-31"))]
        ctx = Ctx(2026, recs, [period_choice(2026), period_choice(2027)])
        got = self.amounts(ctx)
        self.assertEqual(sum(got.values()), 1_100_000)
        self.assertNotIn("f2026-12", got)  # 翌年1月分は翌年分

    def test_months_proration_across_years(self) -> None:
        recs = [prop(), flow("f1", "2026-10-01", 600_000, ("2026-10-01", "2027-03-31"))]
        choices = [period_choice(2026), period_choice(2027)]
        self.assertEqual(self.amounts(Ctx(2026, recs, choices)), {"f1": 300_000})
        self.assertEqual(self.amounts(Ctx(2027, recs, choices)), {"f1": 300_000})

    def test_all_rents_must_be_covered(self) -> None:
        recs = [prop(), prop("prop2"), flow("f1", "2026-05-01", 1, ("2026-05-01", "2026-05-31")), flow("f2", "2026-05-01", 1, ("2026-05-01", "2026-05-31"), prop="prop2")]
        view = rc.RentView(Ctx(2026, recs, [period_choice(2026)]))
        view.records("rent_flow")
        self.assertEqual([t for t, _ in view.people["p1"].problems], [rc.PERIOD_ALL_REASON])

    def test_long_period_needs_business_scale(self) -> None:
        # 事業的規模でなければ1年以内の期間の賃貸料だけ（直所2−78 2）：2年分の前払は受取の年分
        recs = [prop(), flow("f1", "2026-01-01", 2_400_000, ("2026-01-01", "2027-12-31"))]
        choices = [period_choice(2026), period_choice(2027)]
        self.assertEqual(self.amounts(Ctx(2026, recs, choices)), {"f1": 2_400_000})
        self.assertEqual(self.amounts(Ctx(2026, recs, choices, scale=True)), {"f1": 1_200_000})


class TestMaterials(unittest.TestCase):
    def contribute(self, recs: list[dict[str, Any]], judgments: list[dict[str, Any]] = (), choices: list[dict[str, Any]] = ()) -> tuple[list[str], list[str]]:
        problems: list[Any] = []
        missing: list[Any] = []
        rc.contribute(rc.RentView(Ctx(2026, recs, choices, judgments)), "p1", problems, missing, set(), RENT_VARS)
        return [t for t, _, _ in problems], [sp.id for sp, _ in missing]

    def test_custodial_parking(self) -> None:
        recs = [prop(ptype="parking"), flow("f1", "2026-05-01", 10_000)]
        self.assertEqual(self.contribute(recs, [material("prop1", custodial_parking=True)])[0], [rc.CUSTODIAL_REASON])
        self.assertEqual(self.contribute(recs, [material("prop1", custodial_parking=False)]), ([], []))
        _, missing = self.contribute(recs)  # 判断がない駐車場：両方で評価（D21 R6）
        self.assertEqual(missing, ["判断:駐車場の保管責任:prop1:2026"])

    def test_land_value_half(self) -> None:
        # 所令79①一：対価が土地の価額の10分の5を超えれば譲渡所得（範囲外：D20）
        recs = [prop(ptype="land"), flow("k1", "2026-05-01", 5_000_000, ftype="key_money")]
        self.assertEqual(self.contribute(recs, [material("k1", land_market_value=10_000_000)])[0], [])
        recs[1]["amounts"]["amount"] = 5_000_001
        self.assertEqual(self.contribute(recs, [material("k1", land_market_value=10_000_000)])[0], [rc.LAND_TRANSFER_REASON])

    def test_villa_flag_and_conflict(self) -> None:
        p = prop(held_as_villa=False)
        ctx = Ctx(2026, [p], judgments=[material("prop1", villa_purpose=True)])
        self.assertEqual(rc.villa_flag(ctx, p), (True, ("j-prop1",)))
        self.assertEqual(self.contribute([p, flow("f1", "2026-05-01", 1)], [material("prop1", villa_purpose=True)])[0], [rc.VILLA_CONFLICT_REASON])


class TestLandInterestAllocation(unittest.TestCase):
    """措令26の6②・措通41の4−3：負債はまず建物、次に土地等の取得の対価に充てる。"""

    def test_debt_goes_to_building_first(self) -> None:
        recs = [
            prop("bld", "building", acquisition_contract="k-1", amounts={"acquisition_cost": 30_000_000}),
            prop("lnd", "land", acquisition_contract="k-1", amounts={"acquisition_cost": 20_000_000}),
            {"id": "loan1", "kind": "loan", "roles": {"borrower": "p1"}, "when": {"from_on": "2020-01-01"}, "amounts": {"principal": 40_000_000},
             "attributes": {"purpose_asset_id": "bld"}},
        ]  # fmt: skip
        interest = [{"id": "e1", "kind": "business_expense", "roles": {"payer": "p1"}, "amounts": {"amount": 400_000}, "attributes": {"loan_id": "loan1"}}]
        got = rc.land_interest_choice(Ctx(2026, recs, [period_choice(2026, "loan1", rule=rc.RULE_LOAN)]), "p1", interest)
        # 土地等に充てた負債 4,000万−3,000万＝1,000万：利子 40万 × 1,000万/4,000万 ＝ 10万
        self.assertEqual((got[0], got[2], got[3]), (100_000, (), []))
        self.assertIsNone(rc.land_interest_choice(Ctx(2026, recs), "p1", interest))


if __name__ == "__main__":
    unittest.main()

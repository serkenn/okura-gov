"""income_kinds の「範囲内なのに未対応」の解消（D24③）のユニットテスト：配当控除の区分、少額・一括償却資産の売却（所令81）、
業務用の資産の災害等の損失（所法51）、事業専従者のみなし給与（所法57④）の事業主の対象外の伝搬。上流はスタブ。

期待値の出典：docs/public-sources/20261111_impl-research_haito-laws-and-nta.md §2〜§4（所法92①、TA1250）、
docs/public-sources/20261109_round2_genka-laws-and-nta.md §5.1・§5.2（所法51、所令81、決算の手引き p.4）、
docs/public-sources/20261109_round2b_fudosan-laws-and-nta.md §5.1（所法57④）。テストのデータは架空。
"""

from __future__ import annotations

import unittest
from typing import Any

from okura_core.registry import Decided, ModuleInputs, YearContext
from okura_core.rules.income_kinds.assets import SALE_ESSENTIAL_MISSING_REASON, SALE_TRANSFER_REASON, AssetResult, _small_sale
from okura_core.rules.income_kinds.inputs import (
    CASUALTY_UNRECORDED_REASON,
    CREDIT_INTEREST_REASON,
    CREDIT_UNKNOWN_REASON,
    V_CREDIT_FX_TRUST,
    V_CREDIT_SURPLUS,
    V_CREDIT_TRUST,
    SIDE_VARS,
    _business_casualties,
    _credit_classes,
    _Sides,
    DEATH_RETIREMENT_RULE,
    K_RETIRE,
    V_RET_INCOME,
    _retirement,
    credit_amounts,
    retire_year,
)

from ...support import make_ir, person


def _div(rid: str, gross: int, dtype: str | None) -> dict[str, Any]:
    attrs: dict[str, Any] = {"security_class": "listed_investment_trust", "account_type": "other_account"}
    if dtype is not None:
        attrs["distribution_type"] = dtype
    return {"id": rid, "kind": "dividend", "roles": {"recipient": "p-1"}, "when": {"on": "2026-06-30"}, "amounts": {"gross": gross}, "attributes": attrs}


class CreditClassTest(unittest.TestCase):
    def test_amounts_by_class_without_interest(self) -> None:
        # 特定株式投資信託は剰余金の配当等に含める（TA1250）。投資法人は対象外の区分
        got = credit_amounts([("surplus", 100_000), ("trust", 50_000), ("fx_trust", 20_000), ("none", 30_000)], 0)
        self.assertEqual(got, {"surplus": 100_000, "trust": 50_000, "fx_trust": 20_000})

    def test_interest_single_class_is_deducted_and_floored(self) -> None:
        self.assertEqual(credit_amounts([("trust", 50_000)], 60_000), {"surplus": 0, "trust": 0, "fx_trust": 0})
        self.assertEqual(credit_amounts([("surplus", 50_000)], 10_000)["surplus"], 40_000)

    def test_interest_with_two_classes_is_undecided(self) -> None:
        self.assertIsNone(credit_amounts([("surplus", 50_000), ("none", 10_000)], 1))

    def _run(self, parts: list[tuple[dict[str, Any], int]], interest: int = 0) -> ModuleInputs:
        out = ModuleInputs()
        _credit_classes(out, "p-1", parts, [], [], interest, False, [], set())
        return out

    def test_classes_from_distribution_type(self) -> None:
        out = self._run([(_div("d1", 100_000, "specified_stock_investment_trust"), 100_000), (_div("d2", 40_000, "foreign_currency_securities_investment_trust"), 40_000), (_div("d3", 9_000, "investment_corporation"), 9_000)])
        self.assertEqual(out.values[(V_CREDIT_SURPLUS, "p-1")].value, 100_000)
        self.assertEqual(out.values[(V_CREDIT_TRUST, "p-1")].value, 0)
        self.assertEqual(out.values[(V_CREDIT_FX_TRUST, "p-1")].value, 40_000)
        self.assertEqual(out.exclusions, [])

    def test_missing_type_and_mixed_interest_are_excluded(self) -> None:
        out = self._run([(_div("d1", 100_000, None), 100_000)])
        self.assertEqual({e.reason.reason for e in out.exclusions}, {CREDIT_UNKNOWN_REASON})
        # 区分が2つで負債の利子：当て方の候補で分かれるので対象外でなく未確定（2026-11-12。仮説 H3）
        out = self._run([(_div("d1", 100_000, "surplus_dividend"), 100_000), (_div("d2", 1_000, "securities_investment_trust"), 1_000)], interest=500)
        self.assertEqual(out.exclusions, [])
        self.assertEqual(out.values[(V_CREDIT_SURPLUS, "p-1")].missing[0].target["事項"], CREDIT_INTEREST_REASON)


def _asset(*, disposal: str | None = "sale", proceeds: int | None = 30_000) -> dict[str, Any]:
    amounts: dict[str, Any] = {"acquisition_cost": 80_000}
    if proceeds is not None:
        amounts["disposal_proceeds"] = proceeds
    when = {"from_on": "2025-04-01", "to_on": "2026-05-10"}
    attrs: dict[str, Any] = {"name": "架空の器具", "business_id": "b-1"}
    if disposal:
        attrs["disposal_type"] = disposal
    return {"id": "a-1", "kind": "depreciable_asset", "roles": {"owner": "p-1"}, "when": when, "amounts": amounts, "attributes": attrs}


class SmallAssetSaleTest(unittest.TestCase):
    def test_not_essential_proceeds_are_business_revenue(self) -> None:
        out = AssetResult()
        _small_sale(out, _asset(), "biz", ("a-1",), set(), 2026, essential_matters=True, essential=False)
        self.assertEqual(out.revenue, {"biz": 30_000})
        self.assertEqual(out.problems, [])

    def test_essential_is_transfer_income_and_missing_judgment_is_reported(self) -> None:
        out = AssetResult()
        _small_sale(out, _asset(), "biz", ("a-1",), set(), 2026, essential_matters=True, essential=True)
        self.assertEqual(out.problems[0][0], SALE_TRANSFER_REASON)
        out = AssetResult()
        _small_sale(out, _asset(), "biz", ("a-1",), set(), 2026, essential_matters=True, essential=None)
        self.assertEqual(out.problems[0][0], SALE_ESSENTIAL_MISSING_REASON)

    def test_usable_period_under_one_year_ignores_essential(self) -> None:
        out = AssetResult()
        _small_sale(out, _asset(), "biz", ("a-1",), set(), 2026, essential_matters=False, essential=None)
        self.assertEqual(out.revenue, {"biz": 30_000})

    def test_other_year_or_scrapping_does_nothing(self) -> None:
        out = AssetResult()
        _small_sale(out, _asset(), "biz", ("a-1",), set(), 2025, essential_matters=True, essential=False)
        _small_sale(out, _asset(disposal="scrapping"), "biz", ("a-1",), set(), 2026, essential_matters=True, essential=False)
        self.assertEqual((out.revenue, out.problems), ({}, []))


class BusinessCasualtyTest(unittest.TestCase):
    def _ctx(self, asset: dict[str, Any] | None) -> YearContext:
        cas = {
            "id": "c-1", "kind": "casualty", "roles": {"owner": "p-1"}, "when": {"on": "2026-05-10"},
            "amounts": {}, "attributes": {"cause": "storm_or_flood", "business_use": True, "asset_id": "a-1"},
        }  # fmt: skip
        ir = make_ir([person("p-1")], [cas], assets=[asset] if asset else [])
        return YearContext(ir, 2026, ("p-1",))

    def test_recorded_loss_in_asset_ledger_is_not_excluded(self) -> None:
        s = _Sides()
        _business_casualties(self._ctx(_asset(disposal="loss")), "p-1", s, ("x",), {"b-1": "biz"})
        self.assertEqual(s.problems, [])

    def test_unrecorded_loss_makes_that_side_undetermined(self) -> None:
        # 損失の金額（所令142）の一次情報がなく候補を作れない：対象外でなく未確定（何が要るかを返す。D22 S1）
        s = _Sides()
        _business_casualties(self._ctx(_asset(disposal=None)), "p-1", s, ("x",), {"b-1": "biz"})
        self.assertEqual(s.problems, [])
        [(split, variables)] = s.missing
        self.assertEqual((split.target["事項"], variables), (CASUALTY_UNRECORDED_REASON, tuple(SIDE_VARS["biz"])))


class RetirementYearTest(unittest.TestCase):
    """所基通36−10 の本文：退職手当等の収入すべき時期は、その支給の基因となった退職の日（kyuyo-jiki §2.1）。"""

    def test_year_is_retirement_date(self) -> None:
        r = {"when": {"on": "2026-01-20"}, "attributes": {"retired_on": "2025-12-31"}}
        self.assertEqual(retire_year(r), 2025)
        self.assertEqual(retire_year({"when": {"on": "2026-01-20"}, "attributes": {}}), 2026)

    def test_resolution_and_two_payments(self) -> None:
        # TA2728：役員の決議を要するものは決議の日。所令77：2以上の支払は最初に支払を受けるべき日の年
        r = {"when": {"on": "2026-07-01"}, "attributes": {"retired_on": "2025-12-31", "resolution_on": "2026-06-25"}}
        self.assertEqual(retire_year(r), 2026)
        g = [{"when": {"on": "2026-01-10"}, "attributes": {"retired_on": "2025-12-31"}}, {"when": {"on": "2027-01-10"}, "attributes": {"retired_on": "2025-12-31"}}]
        self.assertEqual(retire_year(g[1], g), 2026)

    def test_death_retirement_after_death_is_not_income(self) -> None:
        # TA2732：死亡退職で相続税の対象になる退職手当等は所得税の対象でない
        dead = {"id": "p-1", "birth_on": "1960-01-01", "death_on": "2026-03-01"}
        pay = {
            "id": "rp-1", "kind": "retirement_payment", "roles": {"recipient": "p-1"}, "when": {"on": "2026-04-10"},
            "amounts": {"gross": 3_000_000, "withholding_tax": 0}, "attributes": {"counterparty": "架空の会社", "retired_on": "2026-03-01"},
        }  # fmt: skip
        ctx = YearContext(make_ir([dead], [pay]), 2026, ("p-1",), {(K_RETIRE, "p-1"): Decided({"is_retirement_allowance": True}, (), frozenset(), True)})
        out = ModuleInputs()
        _retirement(ctx, out)
        v = out.values[(V_RET_INCOME, "p-1")]
        self.assertEqual((v.value, v.basis), (0, (DEATH_RETIREMENT_RULE,)))
        self.assertEqual(out.exclusions, [])


if __name__ == "__main__":
    unittest.main()

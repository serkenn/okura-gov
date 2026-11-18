"""減価償却の特別な方法（assets_special.py。IK-103）の境目：生産高比例法・旧生産高比例法・リース期間定額法・経過リース期間定額法・旧国外リース期間定額法。

期待値：docs/inferences/20261112_impl-research5_genka-special-cases.md（式は docs/public-sources/20261112_impl-research5_genka-special-methods.md
§2〜§5：所令120①三ハ・六、120の2①三イ(2)・六、134①②、令和7年政令第120号附則7②④⑥）。1円未満は年ごとに切上げ（他の方法と同じ）。
"""

from __future__ import annotations

import datetime as dt
import unittest
from fractions import Fraction
from types import SimpleNamespace

from okura_core.rules.income_kinds import assets_special as sp
from okura_core.rules.income_kinds.assets import (
    M_DB,
    M_ODB,
    M_OSL,
    M_SL,
    AssetResult,
    CostInfo,
    asset_year,
    method_candidates,
)

from .test_depreciation_old import _ctx

D = dt.date


def _cls(asset_class: str, **value: object) -> dict:
    return {"id": "j1", "subject": {"asset_id": "a1"}, "value": {"asset_class": asset_class, **value}}


def _asset(acquired: str, **attrs: object) -> dict:
    amounts = {"acquisition_cost": 1_000_000, **attrs.pop("amounts", {})}
    return {"id": "a1", "roles": {"owner": "p"}, "when": {"from_on": acquired}, "attributes": dict(attrs), "amounts": amounts}


def _ctx_d(**kw: object) -> object:
    """選択.減価償却 の1か所を未入力（値なし）で返す ctx。"""
    ctx = _ctx(**kw)  # type: ignore[arg-type]
    ctx.decision = lambda kind, key: SimpleNamespace(value={}, record_ids=(), states=set(), open=False)
    return ctx


class TestCandidates(unittest.TestCase):
    def test_mining_statutory_and_choices(self) -> None:
        n = _ctx(notices=(2020,))
        self.assertEqual(method_candidates(_ctx(), _asset("2007-03-31"), _cls("mining_asset")), (sp.M_OUOP,))  # 所令125①一ロ
        self.assertEqual(method_candidates(_ctx(), _asset("2007-04-01"), _cls("mining_right")), (sp.M_UOP,))  # 125①二ロ・ハ
        self.assertEqual(method_candidates(n, _asset("2007-03-31"), _cls("mining_asset")), (sp.M_OUOP, M_OSL, M_ODB))  # 120①三
        self.assertEqual(method_candidates(n, _asset("2007-03-31"), _cls("mining_right")), (sp.M_OUOP, M_OSL))  # 120①五
        self.assertEqual(method_candidates(n, _asset("2016-03-31"), _cls("mine_tunnel")), (sp.M_UOP, M_SL, M_DB))  # 120の2①三ロ
        self.assertEqual(method_candidates(n, _asset("2016-04-01"), _cls("mine_tunnel")), (sp.M_UOP, M_SL))  # 三イ（坑道は構築物）
        self.assertEqual(method_candidates(n, _asset("2016-04-01"), _cls("mining_asset", building_or_structure=True)), (sp.M_UOP, M_SL))
        self.assertEqual(method_candidates(n, _asset("2016-04-01"), _cls("mining_asset", building_or_structure=False)), (sp.M_UOP, M_SL, M_DB))

    def test_lease(self) -> None:
        n = _ctx(notices=(2020,))
        rvg = _asset("2025-04-15", amounts={"residual_value_guarantee": 200_000})
        self.assertEqual(method_candidates(n, _asset("2006-01-01"), _cls("foreign_lease_asset")), (sp.M_FLEASE,))
        self.assertEqual(method_candidates(_ctx(year=2025, notices=(2020,)), rvg, _cls("lease_asset")), (sp.M_LEASE,))  # 経過は令和8年分から
        self.assertEqual(method_candidates(n, rvg, _cls("lease_asset")), (sp.M_LEASE, sp.M_TLEASE))
        self.assertEqual(method_candidates(_ctx(), rvg, _cls("lease_asset")), (sp.M_LEASE,))  # 届出の記録がない
        self.assertEqual(method_candidates(n, _asset("2025-04-15"), _cls("lease_asset")), (sp.M_LEASE,))  # 残価保証額なし：経過リース資産でない


def _special(cls: str, method: str, placed: dt.date, up_to: int, cost: int = 1_000_000) -> sp.Special:
    return sp.Special(cls, method, cost, placed, None, up_to)


class TestProduction(unittest.TestCase):
    def test_new_tangible_cap_cost_minus_one(self) -> None:
        q = {2024: (Fraction(300), None), 2025: (Fraction(500), None), 2026: (Fraction(300), None)}
        got, problem = sp.production_schedule(_special("mining_asset", sp.M_UOP, D(2024, 1, 1), 2026), Fraction(1000), q, 0, None)
        self.assertIsNone(problem)
        self.assertEqual([a for _, a, _ in got], [300_000, 500_000, 199_999])  # 134①二イ：取得価額−1円まで

    def test_old_tangible_95_then_five_years(self) -> None:
        q = {2005: (Fraction(600), None), 2006: (Fraction(500), None), 2007: (Fraction(10), None)}
        got, problem = sp.production_schedule(_special("mining_asset", sp.M_OUOP, D(2005, 1, 1), 2007), Fraction(1000), q, 10, 95)
        self.assertIsNone(problem)
        # (1,000,000−100,000)/1000＝900/単位：540,000、450,000 は95%（950,000）で 410,000、次は（1,000,000−950,000−1）÷5 の切上げ
        self.assertEqual([a for _, a, _ in got], [540_000, 410_000, 10_000])

    def test_old_right_no_residual_cap_cost(self) -> None:
        q = {2005: (Fraction(400), None), 2006: (Fraction(700), None)}
        got, _ = sp.production_schedule(_special("mining_right", sp.M_OUOP, D(2005, 1, 1), 2006), Fraction(1000), q, 10, 95)
        self.assertEqual([a for _, a, _ in got], [400_000, 600_000])  # 134①一ロ：取得価額まで（残存価額0）

    def test_missing_year_quantity(self) -> None:
        got, problem = sp.production_schedule(_special("mining_asset", sp.M_UOP, D(2024, 1, 1), 2025), Fraction(1000), {2024: (Fraction(1), None)}, 0, None)
        self.assertEqual(problem, sp.MINING_QUANTITY_REASON)


class TestLease(unittest.TestCase):
    ASSET = _asset(
        "2025-04-15", lease_term={"from_on": "2025-04-15", "to_on": "2030-04-14"}, amounts={"residual_value_guarantee": 200_000}
    )

    def test_lease_term_straight_line(self) -> None:
        got, problem = sp.lease_schedule(sp.Special("lease_asset", sp.M_LEASE, 1_200_000, D(2025, 4, 15), None, 2026), self.ASSET, None)
        self.assertIsNone(problem)
        # (1,200,000−200,000)÷60月：2025年は4月15日〜12月31日の9月（1月未満は1月）、2026年は12月
        self.assertEqual([a for _, a, _ in got], [150_000, 200_000])

    def test_transitional_from_2026(self) -> None:
        got, _ = sp.lease_schedule(sp.Special("lease_asset", sp.M_TLEASE, 1_200_000, D(2025, 4, 15), None, 2026), self.ASSET, 2026)
        # 改定取得価額 1,200,000−150,000＝1,050,000、改定リース期間 2026-01-01〜2030-04-14 の52月：×12/52 の切上げ
        self.assertEqual([a for _, a, _ in got], [150_000, 242_308])

    def test_foreign_lease(self) -> None:
        a = _asset("2006-01-01", lease_term={"from_on": "2006-01-01", "to_on": "2015-12-31"}, amounts={"estimated_residual_value": 100_000})
        got, _ = sp.lease_schedule(sp.Special("foreign_lease_asset", sp.M_FLEASE, 1_000_000, D(2006, 1, 1), None, 2016), a, None)
        self.assertEqual([x for _, x, _ in got], [90_000] * 10)  # (1,000,000−100,000)×12/120、期間の後はない
        no_res = _asset("2006-01-01", lease_term={"from_on": "2006-01-01", "to_on": "2015-12-31"})
        self.assertEqual(sp.lease_schedule(sp.Special("foreign_lease_asset", sp.M_FLEASE, 1, D(2006, 1, 1), None, 2007), no_res, None)[1], sp.FOREIGN_RESIDUAL_REASON)


class TestAssetYear(unittest.TestCase):
    def _run(self, judgment: dict, asset: dict, year: int = 2026) -> AssetResult:
        out = AssetResult()
        asset_year(_ctx_d(year=year, judgments=(judgment,)), out, asset, "biz", CostInfo(1_000_000, 0), lambda y: False, None, (), set(), (D(2020, 1, 1), None))
        return out

    def test_mining_asset_statutory_units_of_production(self) -> None:
        asset = _asset("2025-07-01", extraction_quantities=[{"tax_year": 2025, "quantity": {"num": 100, "den": 1}}, {"tax_year": 2026, "quantity": {"num": 250, "den": 1}}])
        out = self._run(_cls("mining_asset", planned_extraction_quantity={"num": 1000, "den": 1}), asset)
        self.assertEqual((out.problems, out.expense), ([], {"biz": 250_000}))  # 1,000,000÷1000×250

    def test_mining_without_planned_quantity(self) -> None:
        out = self._run(_cls("mining_asset"), _asset("2025-07-01"))
        self.assertEqual([p[0] for p in out.problems], [sp.MINING_PLANNED_REASON])

    def test_lease_asset_excluded_from_small_amount(self) -> None:
        # 所令138①：リース資産は少額の減価償却資産の対象外。取得価額 80,000 でもリース期間定額法
        out = AssetResult()
        asset = _asset("2026-01-01", lease_term={"from_on": "2026-01-01", "to_on": "2027-12-31"}, amounts={"acquisition_cost": 80_000})
        asset_year(_ctx_d(judgments=(_cls("lease_asset"),)), out, asset, "biz", CostInfo(80_000, 0), lambda y: False, None, (), set(), (D(2020, 1, 1), None))
        self.assertEqual(out.expense, {"biz": 40_000})  # 80,000×12/24


if __name__ == "__main__":
    unittest.main()

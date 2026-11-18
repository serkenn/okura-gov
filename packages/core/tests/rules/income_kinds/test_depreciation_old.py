"""減価償却の旧定額法・旧定率法・定率法（assets.py）の境目。

期待値：docs/inferences/20261111_impl-research3_all-cases.md §1 G-1〜G-4（1円未満は年ごとに切上げ：
docs/public-sources/20261111_impl-research_genka-hasu-nta.md §2）。率は parameters/所得税/減価償却.yaml の末尾
（docs/public-sources/20261111_impl-research3_genka-laws.md §5、scripts/results/IMPL3_genka_tables/）。
"""

from __future__ import annotations

import datetime as dt
import unittest
from functools import cache
from pathlib import Path
from types import SimpleNamespace

from openfisca_core.parameters import ParameterNode

from fractions import Fraction

from okura_core.rules.income_kinds.assets import (
    ANNUAL_LIMIT_REASON,
    M_DB,
    M_ODB,
    M_OSL,
    M_SL,
    METHOD_MISMATCH_REASON,
    AssetResult,
    _check_annual_limit,
    asset_year,
    depreciation_schedule,
    method_candidates,
    method_rates,
)
from okura_core.rules.income_kinds.inputs import _share_for_asset

JAN = dt.date
PARAMS = Path(__file__).resolve().parents[3] / "src" / "okura_core" / "rules" / "income_kinds" / "parameters"


@cache
def _params() -> ParameterNode:
    return ParameterNode("", directory_path=str(PARAMS))


def _ctx(year: int = 2026, notices: tuple[int, ...] = (), judgments: tuple = (), choices: tuple = ()) -> SimpleNamespace:
    recs = [
        {"id": f"bk{y}", "roles": {"person": "p"}, "when": {"tax_year": y}, "attributes": {"depreciation_method_notice": "器具備品 定率法"}}
        for y in notices
    ]
    return SimpleNamespace(
        year=year,
        parameters=_params()(f"{year}-01-01"),
        records=lambda kind: recs if kind == "bookkeeping_status" else [],
        judgments=lambda kind: list(judgments),
        choices=lambda kind: list(choices),
    )


def _asset(acquired: str) -> dict:
    return {"id": "a1", "roles": {"owner": "p"}, "when": {"from_on": acquired}, "attributes": {}, "amounts": {}}


def _amounts(method: str, years: int, acquired: dt.date, up_to: int, intangible: bool = False) -> list[int]:
    rates = method_rates(_ctx(), method, years, acquired, intangible)
    assert rates is not None
    return [s.amount for s in depreciation_schedule(1_000_000, rates, JAN(acquired.year, 1, 1), None, up_to, intangible)]


class TestSchedules(unittest.TestCase):
    def test_g1_old_straight_line_95_then_five_years(self) -> None:
        got = _amounts(M_OSL, 10, JAN(2006, 1, 1), 2006 + 17)
        self.assertEqual(got[:10], [90_000] * 10)
        self.assertEqual(got[10], 50_000)  # 累計 950,000（95%）で止める
        self.assertEqual(got[11:16], [10_000, 10_000, 10_000, 10_000, 9_999])  # (1,000,000−950,000−1)/5 の切上げ、累計は取得価額−1円まで
        self.assertEqual(got[16:], [0, 0])
        self.assertEqual(sum(got), 999_999)

    def test_g2_old_declining(self) -> None:
        self.assertEqual(_amounts(M_ODB, 5, JAN(2006, 1, 1), 2008), [369_000, 232_839, 146_922])

    def test_g3_declining_200(self) -> None:
        self.assertEqual(_amounts(M_DB, 5, JAN(2012, 4, 1), 2016), [400_000, 240_000, 144_000, 108_000, 107_999])

    def test_g4_declining_250(self) -> None:
        self.assertEqual(_amounts(M_DB, 5, JAN(2012, 3, 31), 2016), [500_000, 250_000, 125_000, 62_500, 62_499])

    def test_old_intangible_no_residual_no_95(self) -> None:
        got = _amounts(M_OSL, 5, JAN(2006, 1, 1), 2011, intangible=True)
        self.assertEqual(got, [200_000] * 5 + [0])


class TestMethodCandidates(unittest.TestCase):
    def test_statutory_without_notice(self) -> None:
        self.assertEqual(method_candidates(_ctx(), _asset("2007-03-31"), None), (M_OSL,))
        self.assertEqual(method_candidates(_ctx(), _asset("2007-04-01"), None), (M_SL,))

    def test_notice_opens_declining(self) -> None:
        self.assertEqual(method_candidates(_ctx(notices=(2020,)), _asset("2007-03-31"), None), (M_OSL, M_ODB))
        self.assertEqual(method_candidates(_ctx(notices=(2020,)), _asset("2007-04-01"), None), (M_SL, M_DB))
        self.assertEqual(method_candidates(_ctx(year=2025, notices=(2026,)), _asset("2007-04-01"), None), (M_SL,))  # 後の年分の届出は見ない

    def test_intangible_only_straight(self) -> None:
        sw = {"value": {"useful_life_table_row": "ソフトウエアその他"}}
        self.assertEqual(method_candidates(_ctx(notices=(2020,)), _asset("2007-04-01"), sw), (M_SL,))


    def test_asset_class_limits(self) -> None:
        # 所令120①一（建物は平成10年3月31日以前の取得だけ旧定率法）・120の2①一（建物は定額法だけ、附属設備・構築物は平成28年3月31日以前だけ定率法）
        cls = lambda c: {"value": {"asset_class": c}}  # noqa: E731
        n = _ctx(notices=(2020,))
        self.assertEqual(method_candidates(n, _asset("1998-03-31"), cls("building")), (M_OSL, M_ODB))
        self.assertEqual(method_candidates(n, _asset("1998-04-01"), cls("building")), (M_OSL,))
        self.assertEqual(method_candidates(n, _asset("2007-04-01"), cls("building")), (M_SL,))
        self.assertEqual(method_candidates(n, _asset("2016-03-31"), cls("structure")), (M_SL, M_DB))
        self.assertEqual(method_candidates(n, _asset("2016-04-01"), cls("building_attachment")), (M_SL,))
        self.assertEqual(method_candidates(n, _asset("2006-01-01"), cls("intangible")), (M_OSL,))

    def test_h3_pre_2007_statutory_by_class(self) -> None:
        # 所令125①一イ：120①一イ（平成10年3月31日以前の建物）・二（附属設備・構築物・機械・車両・器具備品）の法定償却方法は旧定額法。
        # 120①一ロ（平成10年4月1日以後の建物）・四（無形・生物）は選べる方法が旧定額法だけ
        # （docs/public-sources/20261112_impl-research4_shotoku-laws-and-nta.md §3、推測 I3 の表）
        cls = lambda c: {"value": {"asset_class": c}}  # noqa: E731
        for c in ("building", "building_attachment", "structure", "machinery_equipment", "intangible", "other"):
            self.assertEqual(method_candidates(_ctx(), _asset("1997-06-01"), cls(c)), (M_OSL,))
        n = _ctx(notices=(2020,))
        self.assertEqual(method_candidates(n, _asset("2000-06-01"), cls("building")), (M_OSL,))  # I3：平成12年の建物は旧定額法だけ
        self.assertEqual(method_candidates(n, _asset("2006-06-01"), cls("machinery_equipment")), (M_OSL, M_ODB))


def _scrapped(proceeds: int) -> dict:
    return {
        "id": "a1", "roles": {"owner": "p"}, "when": {"from_on": "2026-01-01", "to_on": "2026-12-31"},
        "attributes": {"disposal_type": "scrapping"}, "amounts": {"acquisition_cost": 1_000_000, "disposal_proceeds": proceeds},
    }


J10 = {"id": "j1", "subject": {"asset_id": "a1"}, "value": {"useful_life_years": 10}}


def _run(asset: dict, choices: tuple = ()) -> AssetResult:
    from okura_core.rules.income_kinds.assets import CostInfo

    out = AssetResult()
    asset_year(_ctx(judgments=(J10,), choices=choices), out, asset, "biz", CostInfo(1_000_000, 0), lambda y: False, None, (), set(), (JAN(2020, 1, 1), None))
    return out


class TestDisposalAndChoices(unittest.TestCase):
    def test_disposal_excess_is_split(self) -> None:
        # IK-49：定額法 10年（0.100）の12月分 100,000、未償却残高 900,000。処分価額 900,000 は損失0、900,001 は超える部分の分かれ目（一次情報）
        self.assertEqual((_run(_scrapped(900_000)).missing, _run(_scrapped(900_000)).disposal_loss), ([], {}))
        out = _run(_scrapped(900_001))
        self.assertEqual([sp.id for sp, _ in out.missing], ["一次情報:除却の処分価額等が未償却残高を超える部分:a1"])
        self.assertEqual(out.problems, [])

    def test_method_choice_without_notice_is_input_error(self) -> None:
        c = {"id": "c1", "subject": {"asset_id": "a1"}, "value": {"depreciation_method": "declining_balance"}}
        asset = {**_scrapped(0), "when": {"from_on": "2026-01-01"}, "attributes": {}}
        out = _run(asset, choices=(c,))
        self.assertEqual(len(out.problems), 1)
        self.assertTrue(out.problems[0][0].startswith(METHOD_MISMATCH_REASON.split("（")[0]))

    def test_annual_limit(self) -> None:
        # IK-50：措法28の2① の年300万円。入力した選択で超える → 入力の矛盾、未入力の候補で超える → 分かれ目（判断）
        for open_, problems, missing in ((False, 1, 0), (True, 0, 1)):
            out = AssetResult(special_total=3_000_001, special_open=open_)
            _check_annual_limit(_ctx(), out, JAN(2026, 5, 1), (JAN(2020, 1, 1), None), "a1", "biz", "p")
            self.assertEqual((len(out.problems), len(out.missing)), (problems, missing))
        out = AssetResult(special_total=3_000_000, special_open=False)
        _check_annual_limit(_ctx(), out, JAN(2026, 5, 1), (JAN(2020, 1, 1), None), "a1", "biz", "p")
        self.assertEqual((out.problems, out.missing), ([], []))
        self.assertIn("措法28の2", ANNUAL_LIMIT_REASON)


class TestFamilyUseShare(unittest.TestCase):
    def test_family_use_only_gives_business_part(self) -> None:
        # IK-66（語彙の約束）：家族の使用の割合 1/4 だけなら業務の部分は 3/4。業務の割合があればそちら
        d = SimpleNamespace(value={"purpose": "family_use_share", "ratio": {"num": 1, "den": 4}}, record_ids=("j1",), states=frozenset())
        fam = ({"purpose": "family_use_share", "record_ids": ["a1"]}, d)
        self.assertEqual(_share_for_asset("a1", [fam])[0], Fraction(3, 4))
        b = SimpleNamespace(value={"purpose": "asset_business_share", "ratio": {"num": 1, "den": 2}}, record_ids=("j2",), states=frozenset())
        self.assertEqual(_share_for_asset("a1", [fam, ({"purpose": "asset_business_share", "record_ids": ["a1"]}, b)])[0], Fraction(1, 2))


if __name__ == "__main__":
    unittest.main()

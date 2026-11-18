"""減価償却費の計算の資産ごとの行（asset_rows.py・assets.py の AssetResult.rows）：行の並べ方とあふれ、定率法の改定償却率に切り替わる年の償却率、
取得の年の月数、事業専用割合を掛けた必要経費算入額。

期待値：定率法（200%・5年：償却率 0.400・改定償却率 0.500・保証率 0.10800）は docs/inferences/20261111_impl-research3_all-cases.md §1 G-3
（docs/public-sources/20261111_impl-research3_genka-laws.md §2・§5）。月数は所令132（月の中途は1月：docs/public-sources/20261109_round2_genka-laws-and-nta.md §2.3）。
事業専用割合は償却費の全額に掛ける（docs/hypotheses/20261109_round2_genka-model.md H4 案A）。
"""

from __future__ import annotations

import datetime as dt
import unittest
from fractions import Fraction

from okura_core.registry import ModuleInputs
from okura_core.rules.income_kinds.asset_rows import NO_ASSET, ROWS, V_COUNT, AssetRow, rate_text, row_variable, write_rows
from okura_core.rules.income_kinds.assets import M_DB, AssetResult, CostInfo, asset_year, depreciation_schedule, method_rates

from .test_depreciation_old import _ctx

D = dt.date
J10 = {"id": "j1", "subject": {"asset_id": "a1"}, "value": {"useful_life_years": 10}}


def _row(asset_id: str, acquired: dt.date) -> AssetRow:
    return AssetRow(asset_id, "biz", acquired, "定額法", 100, 10, Fraction(100, 1000), 12, 10, None, 10, 90, ids=(asset_id,))


def _value(out: ModuleInputs, k: int, column: str) -> object:
    return out.values[(row_variable(k, column), "p")].value


class TestOrderAndOverflow(unittest.TestCase):
    def test_order_by_acquired_then_id_and_overflow(self) -> None:
        # 取得の日の早い順、同じなら資産の ID 順。8つ目の資産は行に載せない（あふれ）が、資産の数には数える
        rows = [_row(f"a{i}", D(2020, 1, 1)) for i in (5, 3)] + [_row(f"b{i}", D(2019, 6, i)) for i in range(1, 7)]
        out = ModuleInputs()
        write_rows(out, "p", rows, (), ())
        self.assertEqual([_value(out, k, "資産のID") for k in range(1, ROWS + 1)], ["b1", "b2", "b3", "b4", "b5", "b6", "a3"])
        self.assertEqual(out.values[(V_COUNT, "p")].value, 8)
        self.assertEqual(out.values[(row_variable(1, "資産のID"), "p")].record_ids, ("b1",))

    def test_empty_rows_and_other_sides(self) -> None:
        # 行に資産がなければ ID は「なし」（様式の欄は空欄）。事業所得の側でない資産は載せない
        out = ModuleInputs()
        write_rows(out, "p", [_row("a1", D(2020, 1, 1)), AssetRow("m1", "misc", D(2019, 1, 1), "定額法", 1, 2, None, 12, 1, None, 1, 0)], (), ())
        self.assertEqual([_value(out, k, "資産のID") for k in (1, 2)], ["a1", NO_ASSET])
        self.assertEqual((_value(out, 2, "償却率"), _value(out, 2, "本年分の必要経費算入額")), ("なし", 0))
        self.assertEqual(out.values[(V_COUNT, "p")].value, 1)


class TestRevisedRate(unittest.TestCase):
    def test_declining_switches_to_revised_rate(self) -> None:
        # G-3：取得価額 1,000,000、200%・5年。4年目の調整前償却額 216,000×0.400＝86,400 が償却保証額 108,000 に満たない
        # → 改定取得価額 216,000 × 改定償却率 0.500。3年目までは償却率 0.400 で、基礎は期首未償却残高
        rates = method_rates(_ctx(), M_DB, 5, D(2012, 4, 1), False)
        assert rates is not None
        s = depreciation_schedule(1_000_000, rates, D(2012, 1, 1), None, 2016, False)
        self.assertEqual([(y.base, rate_text(y.rate), y.amount) for y in s[2:4]], [(360_000, "0.400", 144_000), (216_000, "0.500", 108_000)])
        self.assertEqual((s[4].base, rate_text(s[4].rate)), (216_000, "0.500"))  # 改定の後は改定取得価額のまま（所令120の2②二ロ）


def _run(placed: str, share: Fraction | None) -> AssetResult:
    asset = {"id": "a1", "roles": {"owner": "p"}, "when": {"from_on": placed}, "attributes": {}, "amounts": {"acquisition_cost": 1_000_000}}
    out = AssetResult()
    asset_year(_ctx(judgments=(J10,)), out, asset, "biz", CostInfo(1_000_000, 0), lambda y: False, share, (), set(), (D(2020, 1, 1), None))
    return out


class TestFirstYearAndShare(unittest.TestCase):
    def test_first_year_months(self) -> None:
        # 2026-04-15 に業務の用に供した定額法 10年（0.100）：4月〜12月の9月（月の中途は1月）。1,000,000×0.100×9/12＝75,000
        row = _run("2026-04-15", None).rows["a1"]
        self.assertEqual((row.months, row.base, rate_text(row.rate), row.ordinary, row.unamortized), (9, 1_000_000, "0.100", 75_000, 925_000))

    def test_share_applies_to_expense_only(self) -> None:
        # 事業専用割合 60%：必要経費算入額は償却費合計×割合、未償却残高は償却費の全額で減らす（案A）
        res = _run("2026-04-15", Fraction(3, 5))
        row = res.rows["a1"]
        self.assertEqual((row.ordinary, row.expense, row.unamortized), (75_000, 45_000, 925_000))
        self.assertEqual(res.expense["biz"], 45_000)
        out = ModuleInputs()
        write_rows(out, "p", res.rows.values(), (), ())
        self.assertEqual((_value(out, 1, "事業専用割合"), _value(out, 1, "本年分の必要経費算入額")), ("60%", 45_000))


if __name__ == "__main__":
    unittest.main()

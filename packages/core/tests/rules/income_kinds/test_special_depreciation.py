"""割増償却・特別償却（special_dep.py・assets.py。IK-112。2026-11-12）：外部で計算した額を普通償却と合わせること、未償却残高への反映、
青色申告書を提出する個人の要件、条・所得の側・第19条・繰越の確かめ。

根拠：docs/public-sources/20261112_impl-research7_tokubetsu-shokyaku.md（§1 条の表〔第11条の2 だけ青色の要件がない、10_4_2→10_5 の番号の移り〕、
§2 翌年分への繰越、§4 第19条③、§5 様式の償却費合計＝普通償却費＋割増（特別）償却費）。普通償却の期待値は定額法 10年 0.100・定率法 5年 0.400
（docs/public-sources/20261111_impl-research3_genka-laws.md §2）。
"""

from __future__ import annotations

import datetime as dt
import unittest
from fractions import Fraction
from types import SimpleNamespace

from okura_core.rules.income_kinds import special_dep as sd
from okura_core.rules.income_kinds.assets import M_DB, AssetResult, CostInfo, asset_year, depreciation_schedule, method_rates

from .test_depreciation_old import _params

D = dt.date
J10 = {"id": "j1", "subject": {"asset_id": "a1"}, "value": {"useful_life_years": 10}}


def _ctx(year: int, specials: list[dict]) -> SimpleNamespace:
    return SimpleNamespace(
        year=year,
        parameters=_params()(f"{year}-01-01"),
        records=lambda kind: list(specials) if kind == sd.K_SPECIAL else [],
        judgments=lambda kind: [J10],
        choices=lambda kind: [],
        decision=lambda kind, key: SimpleNamespace(value={}, record_ids=(), states=(), open=False),  # 選択.減価償却：一括・措法28の2 を選ばない
    )


def _sp(rid: str, year: int, amount: int, article: str = "10_3", carry: bool = False, owner: str = "p") -> dict:
    a = {"asset_id": "a1", "article": article, "method": "special"}
    if carry:
        a["shortfall_carryover"] = True
    return {"id": rid, "kind": sd.K_SPECIAL, "roles": {"owner": owner}, "when": {"tax_year": year}, "amounts": {"amount": amount}, "attributes": a}


def _run(year: int, specials: list[dict], *, cost: int = 1_000_000, blue: tuple[bool, bool] = (True, False), share: Fraction | None = None, side: str = "biz") -> AssetResult:
    asset = {"id": "a1", "roles": {"owner": "p"}, "when": {"from_on": "2025-01-01"}, "attributes": {}, "amounts": {"acquisition_cost": cost}}
    out = AssetResult()
    asset_year(_ctx(year, specials), out, asset, side, CostInfo(cost, 0), lambda y: blue[0], share, (), set(), (D(2020, 1, 1), None), blue_now=lambda: blue)
    return out


class TestSchedule(unittest.TestCase):
    def test_declining_balance_base_reduced_by_special(self) -> None:
        # 定率法 5年（0.400）：1年目 普通 400,000＋特別 300,000 → 2年目の期首未償却残高 300,000×0.400＝120,000（償却保証額 108,000 以上なので償却率のまま）
        rates = method_rates(_ctx(2026, []), M_DB, 5, D(2025, 1, 1), False)
        assert rates is not None
        s = depreciation_schedule(1_000_000, rates, D(2025, 1, 1), None, 2026, False, {2025: 300_000})
        self.assertEqual([(y.amount, y.special, y.accum) for y in s], [(400_000, 300_000, 700_000), (120_000, 0, 820_000)])


class TestAssetYear(unittest.TestCase):
    def test_first_year_expense_row_and_basis(self) -> None:
        # 定額法 10年：普通 100,000＋特別 300,000。必要経費は合計×事業専用割合 60%＝240,000。未償却残高は合計で減らす
        out = _run(2025, [_sp("s1", 2025, 300_000)], share=Fraction(3, 5))
        row = out.rows["a1"]
        self.assertEqual((row.ordinary, row.special, row.expense, row.unamortized), (100_000, 300_000, 240_000, 600_000))
        self.assertEqual(out.expense["biz"], 240_000)
        (basis,) = out.basis["biz"]
        self.assertEqual((basis.value, basis.detail["外部の値"], basis.detail["区分"]), (300_000, True, "特別償却"))

    def test_next_year_ordinary_only_and_unamortized(self) -> None:
        # 2年目：記録は前年分だけ。定額法の普通償却 100,000、未償却残高は 1,000,000−400,000−100,000
        out = _run(2026, [_sp("s1", 2025, 300_000)])
        row = out.rows["a1"]
        self.assertEqual((row.ordinary, row.special, row.unamortized), (100_000, 0, 500_000))

    def test_white_filer_requires_blue(self) -> None:
        # 第10条の3 は青色申告書を提出する個人の要件（§1）。承認がなければ入力の矛盾
        out = _run(2025, [_sp("s1", 2025, 300_000)], blue=(False, False))
        self.assertEqual(out.problems[0][0], sd.SPECIAL_BLUE_REASON)
        self.assertEqual(out.expense, {})

    def test_hisai_daitai_without_blue_and_rental(self) -> None:
        # 第11条の2（被災代替資産等）は青色の要件がなく、不動産所得にも当たる（§1）
        out = _run(2025, [_sp("s1", 2025, 150_000, article="11_2")], blue=(False, False), side="rental")
        self.assertEqual((out.problems, out.expense["rental"]), ([], 250_000))

    def test_blue_open_uses_zero_in_first_candidate(self) -> None:
        # 承認が読みで分かれる：承認なしの候補では適用しない（分かれ目は呼び出し側が付ける）。対象外にしない
        out = _run(2025, [_sp("s1", 2025, 300_000)], blue=(False, True))
        self.assertEqual((out.problems, out.rows["a1"].special, out.expense["biz"]), ([], 0, 100_000))

    def test_article_side_and_year_checks(self) -> None:
        self.assertEqual(_run(2025, [_sp("s1", 2025, 1, article="10_5_6")]).problems[0][0], sd.SPECIAL_ARTICLE_REASON)  # 令和8年の版だけの条
        self.assertEqual(_run(2025, [_sp("s1", 2025, 1)], side="rental").problems[0][0], sd.SPECIAL_SIDE_REASON)  # 第10条の3 は事業所得だけ
        self.assertEqual(_run(2025, [_sp("s1", 2024, 1)]).problems[0][0], sd.SPECIAL_YEAR_REASON)  # 業務の用に供した年より前
        self.assertEqual(_run(2025, [_sp("s1", 2025, 1), _sp("s2", 2025, 1, article="11")]).problems[0][0], sd.SPECIAL_DUPLICATE_REASON)

    def test_section19_3_compares_titles_across_renumbering(self) -> None:
        # 第19条③：前年に適用を受けた規定以外は適用しない。10_4_2（令和7年の版）と 10_5（令和8年の版）は同じ規定（見出しが同じ）
        same = _run(2026, [_sp("s1", 2025, 200_000, article="10_4_2"), _sp("s2", 2026, 50_000, article="10_5", carry=True)])
        self.assertEqual((same.problems, same.rows["a1"].special), ([], 50_000))
        other = _run(2026, [_sp("s1", 2025, 200_000, article="10_3"), _sp("s2", 2026, 50_000, article="11")])
        self.assertEqual(other.problems[0][0], sd.SPECIAL_MULTIPLE_REASON)

    def test_carryover_needs_prior_year_record(self) -> None:
        # 償却不足額を繰り越せるのは適用を受けた年の翌年分だけ（§2）
        self.assertEqual(_run(2026, [_sp("s2", 2026, 50_000, carry=True)]).problems[0][0], sd.SPECIAL_CARRYOVER_REASON)

    def test_excess_over_remaining(self) -> None:
        # 普通償却 100,000 の後に残る 899,999（取得価額−1円まで）を超える額は入力の矛盾
        self.assertEqual(_run(2025, [_sp("s1", 2025, 900_000)]).problems[0][0], sd.SPECIAL_EXCESS_REASON)

    def test_small_asset_and_owner(self) -> None:
        self.assertEqual(_run(2025, [_sp("s1", 2025, 1)], cost=50_000).problems[0][0], sd.SPECIAL_FULL_EXPENSE_REASON)  # 少額（所令138）
        self.assertEqual(_run(2025, [_sp("s1", 2025, 1, owner="q")]).problems[0][0], sd.SPECIAL_OWNER_REASON)


if __name__ == "__main__":
    unittest.main()

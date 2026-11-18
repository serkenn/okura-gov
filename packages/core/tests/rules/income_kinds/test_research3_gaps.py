"""income_kinds の「範囲内なのに未対応」の解消（2026-11-12、D24③）のユニットテスト：退職所得の二以上の区分・前の退職手当等・複数の支払者
（所法30⑥⑦、所令69〜71の2）、配当の負債の利子（所令59）と配当控除の区分への当て方（仮説 H3）、1回の支払ごとの配当の申告の選択（措法8の5④）。

期待値の出典：docs/public-sources/20261109_round2b_taishoku-laws-and-guidance.md §2.2〜§2.4（TA2737 例2・例3、TA2741）、
docs/hypotheses/20261111_impl-research3_all-model.md H3、docs/inferences/20261111_impl-research3_all-cases.md D-1、
docs/public-sources/20261109_round2b_kabu-law-and-nta.md §2.1（措法8の5④・①一）。テストのデータは架空。
"""

from __future__ import annotations

import datetime as _dt
import unittest
from fractions import Fraction
from typing import Any

from okura_core.registry import Decided, ModuleInputs, YearContext, YearWindow
from okura_core.rules.income_kinds.calc import RetirementRules, retirement_deduction, retirement_income_multi
from okura_core.rules.income_kinds.common import measure, sum_ymd, ymd
from okura_core.rules.income_kinds.inputs import (
    K_RETIRE,
    V_CREDIT_SURPLUS,
    V_RET_INCOME,
    V_RET_KIND,
    V_RET_OFFICER_DED,
    V_RET_PRIOR_YEARS,
    V_RET_SHORT_DED,
    V_RET_SHORT_INCOME,
    V_RET_YEARS,
    _credit_classes,
    _retirement,
    credit_amount_candidates,
)

from ...support import make_ir, person, system

R = RetirementRules(20, 400_000, 8_000_000, 700_000, 800_000, 1_000_000, Fraction(1, 2), 3_000_000, 1_500_000)
D = _dt.date


class RetirementMultiTest(unittest.TestCase):
    def test_general_and_officer_ta2737(self) -> None:
        # TA2737 例2：控除額520万円、特定役員退職所得控除額120万円 → (500万−120万)＋{800万−(520万−120万)}×1/2＝580万円
        self.assertEqual(retirement_income_multi(8_000_000, 0, 5_000_000, 5_200_000, 0, 1_200_000, R), 5_800_000)

    def test_short_and_officer_ta2741(self) -> None:
        # TA2741：(1,500万−120万)＋150万＋{500万−(300万＋80万)}＝1,650万円（短期退職所得控除額＝200万−120万）
        self.assertEqual(retirement_income_multi(0, 5_000_000, 15_000_000, 2_000_000, 0, 1_200_000, R), 16_500_000)

    def test_shortfall_moves_to_the_other_part(self) -> None:
        # 所令71の2①一イ：一般の収入金額が一般退職所得控除額に満たない部分は短期の残額から控除する
        self.assertEqual(retirement_income_multi(100_000, 1_000_000, 0, 1_000_000, 400_000, 0, R), Fraction(600_000 - 500_000, 2))

    def test_prior_overlap_reduces_deduction_with_minimum(self) -> None:
        # 所法30⑥一・二：③の額から重複期間（年）の③の額を引き、80万円未満なら80万円
        self.assertEqual(retirement_deduction(10, False, R, 3), 2_800_000)
        self.assertEqual(retirement_deduction(3, False, R, 3), 800_000)


class PeriodTest(unittest.TestCase):
    def test_ymd_by_calendar_and_30_days(self) -> None:
        # 所基通30−13：暦に従い、1月未満は日、30日で1月
        self.assertEqual(ymd(D(2020, 4, 1), D(2025, 3, 31)), (5, 0, 0))
        self.assertEqual(ymd(D(2020, 4, 1), D(2025, 4, 15)), (5, 0, 15))
        self.assertEqual(sum_ymd([(1, 11, 20), (0, 0, 15)]), (2, 0, 5))
        self.assertEqual(measure([]), (0, 0, 0))


def _pay(rid: str, gross: int, payer: str, retired: str, on: str) -> dict[str, Any]:
    return {"id": rid, "kind": "retirement_payment", "roles": {"recipient": "p-1"}, "when": {"on": on},
            "amounts": {"gross": gross, "withholding_tax": 0}, "attributes": {"counterparty": payer, "retired_on": retired}}  # fmt: skip


def _rec(rid: str, payer: str, start: str, end: str) -> dict[str, Any]:
    return {"id": rid, "kind": "retirement_record", "roles": {"recipient": "p-1"}, "when": {"from_on": start, "to_on": end},
            "attributes": {"counterparty": payer, "declaration_submitted": True}}  # fmt: skip


def _run(facts: list[dict[str, Any]]) -> ModuleInputs:
    window = YearWindow(parameters_at=lambda s: system().parameters(s), parameter_root=system().parameters)
    ctx = YearContext(make_ir([person("p-1", "1960-01-01")], facts), 2026, ("p-1",),
                      {(K_RETIRE, "p-1"): Decided({"is_retirement_allowance": True}, (), frozenset(), True)}, window=window)  # fmt: skip
    out = ModuleInputs()
    _retirement(ctx, out)
    return out


class RetirementPlanTest(unittest.TestCase):
    def test_two_payers_general_and_short(self) -> None:
        # 所令69①三：最も長い期間（10年）に重複しない期間（3月）を加算 → 10年3月 → 11年。一般（10年）と短期（3年、うち重複1年）の二以上（所令71の2①）
        out = _run([
            _pay("a", 5_000_000, "甲", "2026-03-31", "2026-04-10"), _rec("ra", "甲", "2016-04-01", "2026-03-31"),
            _pay("b", 1_000_000, "乙", "2026-06-30", "2026-07-10"), _rec("rb", "乙", "2023-07-01", "2026-06-30"),
        ])  # fmt: skip
        self.assertEqual(out.exclusions, [])
        v = {k[0]: x.value for k, x in out.values.items()}
        self.assertEqual((v[V_RET_INCOME], v[V_RET_YEARS], v[V_RET_SHORT_INCOME], v[V_RET_PRIOR_YEARS]), (6_000_000, 11, 1_000_000, 0))
        # 短期退職所得控除額（所令71の2①一イ・⑩）：短期3年、一般との重複 2023-07-01〜2026-03-31 は2年9月 → 3年。40万円×(3−3)＋20万円×3
        self.assertEqual(v[V_RET_SHORT_DED], 400_000 * (3 - 3) + 200_000 * 3)
        self.assertEqual(v[V_RET_KIND], "一般")

    def test_prior_payment_within_four_years_overlaps(self) -> None:
        # 所令70①二イ：前年以前4年内の退職手当等の勤続期間と重複する期間（1年未満切捨て）
        out = _run([
            _pay("old", 5_000_000, "甲", "2024-03-31", "2024-04-10"), _rec("rold", "甲", "2014-04-01", "2024-03-31"),
            _pay("new", 2_000_000, "乙", "2026-03-31", "2026-04-10"), _rec("rnew", "乙", "2020-10-01", "2026-03-31"),
        ])  # fmt: skip
        self.assertEqual(out.exclusions, [])
        self.assertEqual(out.values[(V_RET_PRIOR_YEARS, "p-1")].value, 3)  # 2020-10-01〜2024-03-31 は3年6月 → 3年
        self.assertEqual(out.values[(V_RET_OFFICER_DED, "p-1")].value, 0)


class DividendInterestTest(unittest.TestCase):
    def test_candidates_d1(self) -> None:
        # 推測 D-1：剰余金の配当 300,000・証券投資信託 100,000、負債の利子 60,000。区分の順と按分で分かれる
        cands = credit_amount_candidates([("surplus", 300_000), ("trust", 100_000)], 60_000)
        self.assertIn({"surplus": 240_000, "trust": 100_000, "fx_trust": 0}, cands)
        self.assertIn({"surplus": 255_000, "trust": 85_000, "fx_trust": 0}, cands)
        self.assertEqual(credit_amount_candidates([("surplus", 30_000), ("trust", 10_000)], 50_000), [{"surplus": 0, "trust": 0, "fx_trust": 0}] * 4)

    def test_split_classes_are_undetermined_not_excluded(self) -> None:
        div = lambda rid, t: {"id": rid, "kind": "dividend", "attributes": {"distribution_type": t}}  # noqa: E731
        out = ModuleInputs()
        _credit_classes(out, "p-1", [(div("d1", "surplus_dividend"), 300_000), (div("d2", "securities_investment_trust"), 100_000)], [], [], 60_000, False, [], set())
        self.assertEqual(out.exclusions, [])
        self.assertTrue(out.values[(V_CREDIT_SURPLUS, "p-1")].missing)


if __name__ == "__main__":
    unittest.main()

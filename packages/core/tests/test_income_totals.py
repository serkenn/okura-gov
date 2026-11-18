"""規則モジュール income_totals（rules/income_totals/）のテスト。令和7年分・令和8年分の両方で、docs の境目・計算例を期待値にする。

- 純粋関数（calc.py）：所得金額調整控除の第1項・第2項、損益通算、繰越控除（雑損失の順序を含む）、上場株式等の譲渡損失。
- OpenFisca の式（variables.py）：上流の概念（income_kinds の所得など）を入力として与えて単独で確かめる。
- 入力の組み立て（inputs.py）は tests/test_income_totals_inputs.py。
テストのデータは架空の金額だけ。
"""

from __future__ import annotations

import unittest
from fractions import Fraction
from typing import Any

from openfisca_core.simulation_builder import SimulationBuilder

from okura_core import evaluate
from okura_core.result import OutOfScopeCategory, TimeKey, YenAmount, check_result_json
from okura_core.registry import CheckContext
from okura_core.rules.income_totals.calc import (
    Adjustment1Rules,
    Adjustment2Rules,
    CarrybackRules,
    Incomes,
    adjustment_1,
    adjustment_2,
    apply_carryforwards,
    carryback_refund,
    second_prior_refund,
    half_ichiji,
    listed,
    offset_losses,
    split_casualty,
)
from okura_core.rules.income_totals.checks import carryback_exceeds_taxable
from okura_core.rounding import FUNCTIONS

from .support import make_ir, make_query, person, salary, system

YEARS = (2025, 2026)
RULES1 = Adjustment1Rules(base=8_500_000, top=10_000_000, numerator=10, denominator=100)
RULES2 = Adjustment2Rules(kyuyo_cap=100_000, nenkin_cap=100_000, deduct=100_000)
V_TOTAL = "所得税_合計所得金額"
V_SOU = "所得税_総所得金額"
V_ADJ = "所得税_所得金額調整控除"


def _ok(res: Any) -> Any:
    if not res.ok:
        raise AssertionError(res.to_dict())
    problems = check_result_json(res.to_dict())
    if problems:
        raise AssertionError(problems)
    return res


def _sim(year: int, people: dict[str, dict[str, Any]]) -> Any:
    """上流の概念に値を与えた Simulation（式の単独の確認。上流が式を持っていても与えた値を使う）。"""
    situation = {"人物一覧": {p: {v: {str(year): x} for v, x in d.items()} for p, d in people.items()}}
    return SimulationBuilder().build_from_entities(system(), situation)


def _calc(year: int, var: str, **vars_: Any) -> int:
    return int(_sim(year, {"p": vars_}).calculate(var, str(year))[0])


# 変数名を短く書くための別名（テストの中だけ）
_V = {
    "配当": "所得税_配当所得の金額",
    "不動産": "所得税_不動産所得の金額",
    "事業": "所得税_事業所得の金額",
    "給与": "所得税_給与所得",
    "雑": "所得税_雑所得の金額",
    "一時": "所得税_一時所得の金額",
    "退職": "所得税_退職所得の金額",
    "年金雑": "所得税_公的年金等に係る雑所得の金額",
    "上場配当": "所得税_上場株式等に係る配当所得等の金額",
    "上場譲渡": "所得税_上場株式等に係る譲渡所得等の金額",
    "繰越純損失": "所得税_繰り越された純損失の金額",
    "繰越雑損失": "所得税_繰り越された雑損失の金額",
    "繰越上場": "所得税_繰り越された上場株式等の譲渡損失の金額",
    "通算": "所得税_上場株式等の譲渡損失の損益通算を適用するか",
    "繰越適用": "所得税_上場株式等の譲渡損失の繰越控除を適用するか",
    "端数": "所得税_一時所得の2分の1の端数の候補",
}


def _p(**kw: Any) -> dict[str, Any]:
    """所得の値の入力（事業・不動産などの別名）。渡さない所得は0（上流が未実装でも実装済みでも、値を明示する）。"""
    out = {
        _V[k]: 0
        for k in ("配当", "不動産", "事業", "給与", "雑", "一時", "退職", "年金雑", "上場配当", "上場譲渡", "繰越純損失", "繰越雑損失", "繰越上場")
    }
    out[_V["通算"]] = False
    out[_V["繰越適用"]] = False
    for k, v in kw.items():
        out[_V[k]] = v
    # 2026-11-12（kyuyo KY-11）：所得金額調整控除の第2項は 所得税_給与所得控除後の給与等の金額（特定支出控除の前）を引く。
    # 特定支出控除のない人では給与所得の金額と同じなので、同じ値を入力にする
    out["所得税_給与所得控除後の給与等の金額"] = out[_V["給与"]]
    return out


class TestAdjustment2(unittest.TestCase):
    """所得金額調整控除の第2項（措法41の3の11②）。計算例：docs/measurements/20261109_round2_gaps-fetch-and-checks.md C3。"""

    CASES = [(50_000, 40_000, 0), (50_000, 80_000, 30_000), (200_000, 300_000, 100_000), (100_000, 1, 1), (0, 500_000, 0)]

    def test_examples(self) -> None:
        for k, n, want in self.CASES:
            with self.subTest(k=k, n=n):
                self.assertEqual(adjustment_2(k, n, RULES2), want)

    def test_boundary_of_the_sum(self) -> None:
        # 合計額が10万円を超える（措法41の3の11②）：10万円ちょうどは0、10万1円は1（docs/public-sources/20261109_round2_gaps-sources.md §3.1）
        self.assertEqual(adjustment_2(60_000, 40_000, RULES2), 0)
        self.assertEqual(adjustment_2(60_000, 40_001, RULES2), 1)

    def test_variable_both_years_and_flows_to_totals(self) -> None:
        for y in YEARS:
            for k, n, want in self.CASES:
                with self.subTest(year=y, k=k, n=n):
                    self.assertEqual(_calc(y, V_ADJ, **_p(給与=k, 年金雑=n)), want)
                    # 第2項の残額が給与所得の金額になり（§3.1 第5項）、合計所得金額・総所得金額に入る
                    self.assertEqual(_calc(y, V_TOTAL, **_p(給与=k, 年金雑=n, 雑=n)), k - want + n)
                    self.assertEqual(_calc(y, V_SOU, **_p(給与=k, 年金雑=n, 雑=n)), k - want + n)


class TestOffset(unittest.TestCase):
    """損益通算（所法69①、所令198）。計算例：docs/measurements/20261109_round2_genka-fetch-and-checks.md §5.4 E6〜E8。"""

    def test_e6_pure(self) -> None:
        a = offset_losses(Incomes(0, 0, -500_000, 300_000, 100_000, 200_000))
        self.assertEqual((a.keijo, a.ichiji, a.taishoku, a.net_loss), (0, 100_000, 0, 0))

    def test_e6_order_of_sum_differs_from_simple_total(self) -> None:
        for y in YEARS:
            with self.subTest(year=y):
                # E6：事業 −500,000、給与 300,000、雑 100,000、一時 200,000 → 総所得金額 50,000（順序を無視した単純な合計は0）
                self.assertEqual(_calc(y, V_SOU, **_p(事業=-500_000, 給与=300_000, 雑=100_000, 一時=200_000)), 50_000)

    def test_e7_misc_loss_is_not_offset(self) -> None:
        for y in YEARS:
            with self.subTest(year=y):
                # E7：雑所得の損失は通算しない → 給与 300,000 ＋ 一時 200,000×1/2 ＝ 400,000（TA No.2250 注2）
                self.assertEqual(_calc(y, V_SOU, **_p(雑=-400_000, 給与=300_000, 一時=200_000)), 400_000)

    def test_e8_dependents_boundary_r7(self) -> None:
        # E8（令和7年分）：給与所得 700,000 と事業 −200,000 → 500,000（58万円以下で扶養親族の要件を満たす）
        sim = _sim(2025, {"p": _p(給与=700_000, 事業=-200_000)})
        self.assertEqual(int(sim.calculate(V_TOTAL, "2025")[0]), 500_000)
        self.assertTrue(bool(sim.calculate("所得税_扶養親族の合計所得金額要件", "2025")[0]))
        # 同じ額が業務に係る雑所得の損失なら 700,000（満たさない）
        sim2 = _sim(2025, {"p": _p(給与=700_000, 雑=-200_000)})
        self.assertEqual(int(sim2.calculate(V_TOTAL, "2025")[0]), 700_000)
        self.assertFalse(bool(sim2.calculate("所得税_扶養親族の合計所得金額要件", "2025")[0]))

    def test_dependents_income_boundary_after_offset(self) -> None:
        # 扶養親族の合計所得金額の上限：令和7年分 58万円以下、令和8年分 62万円以下（docs/public-sources/20261109_R1-laws_income-tax.md §2）
        cases = {2025: 580_000, 2026: 620_000}
        for y, limit in cases.items():
            for amount, want in ((limit, True), (limit + 1, False)):
                with self.subTest(year=y, amount=amount):
                    sim = _sim(y, {"p": _p(給与=amount + 300_000, 事業=-300_000)})
                    self.assertEqual(int(sim.calculate(V_TOTAL, str(y))[0]), amount)
                    self.assertEqual(bool(sim.calculate("所得税_扶養親族の合計所得金額要件", str(y))[0]), want)

    def test_order_ichiji_then_retirement_and_net_loss(self) -> None:
        # 所令198 一・三・五：経常 → 一時 → 退職。事業 −1,000,000、給与 200,000、一時 300,000、退職 100,000 → 純損失 400,000
        a = offset_losses(Incomes(0, 0, -1_000_000, 200_000, 0, 300_000, 100_000))
        self.assertEqual((a.keijo, a.ichiji, a.taishoku, a.net_loss), (0, 0, 0, 400_000))
        for y in YEARS:
            with self.subTest(year=y):
                self.assertEqual(
                    _calc(y, "所得税_純損失の金額", **_p(事業=-1_000_000, 給与=200_000, 一時=300_000, 退職=100_000)), 400_000
                )

    def test_rental_and_business_net_within_ordinary_income(self) -> None:
        # 不動産の損失は事業の黒字から（経常所得の中：所令198一）
        for y in YEARS:
            self.assertEqual(_calc(y, V_SOU, **_p(不動産=-100_000, 事業=300_000)), 200_000)


class TestHalfIchiji(unittest.TestCase):
    """一時所得の2分の1（所法22②二）。条文に1円未満の端数の定めがなく（jigyo §11）、令和7年分は手引きの切捨て（yoshiki §2 の⑪）、令和8年分は候補で評価する。"""

    def test_even_needs_no_rounding(self) -> None:
        self.assertEqual(half_ichiji(200_000, FUNCTIONS["floor"]), 100_000)

    def test_odd_with_candidates(self) -> None:
        self.assertEqual(half_ichiji(100_001, FUNCTIONS["floor"]), 50_000)
        self.assertEqual(half_ichiji(100_001, FUNCTIONS["ceil"]), 50_001)
        self.assertEqual(half_ichiji(100_001, FUNCTIONS["half_up"]), 50_001)

    def test_variable_reads_the_candidate_only_when_odd(self) -> None:
        for y in YEARS:
            with self.subTest(year=y):
                self.assertEqual(_calc(y, V_SOU, **_p(一時=200_000)), 100_000)  # 候補の入力なし（既定の空文字）でも丸めない

    def test_r7_truncates_per_tebiki_and_ignores_candidates(self) -> None:
        # 令和7年分の手引き 第一表⑪の計算欄「（B＋G）×0.5 … 1円未満の端数があるときは、その端数を切り捨てます。」
        # （docs/public-sources/20261109_round2_yoshiki-forms-r07.md §2）。候補の入力があっても手引きの切捨て
        self.assertEqual(_calc(2025, V_SOU, **_p(一時=100_001, 端数="ceil")), 50_000)
        self.assertEqual(_calc(2025, V_SOU, **_p(一時=100_001)), 50_000)

    def test_r8_uses_candidates(self) -> None:
        # 令和8年分の手引きは未公表で、法令にも定めがない（jigyo §11）→ 候補で評価する（D22 S3）
        self.assertEqual(_calc(2026, V_SOU, **_p(一時=100_001, 端数="floor")), 50_000)
        self.assertEqual(_calc(2026, V_SOU, **_p(一時=100_001, 端数="ceil")), 50_001)


class TestCarryforward(unittest.TestCase):
    """純損失・雑損失の繰越控除（所法70・71、所令201・204）。"""

    def test_c1_pure_and_variable(self) -> None:
        # docs/measurements/20261109_round2_aoiro-fetch-and-checks.md §4.3 C1：純損失 100万円、総所得金額 60万円 → 60万円を控除
        r = apply_carryforwards(600_000, 0, 1_000_000, 0)
        self.assertEqual((r.net, r.total_income), (600_000, 0))
        for y in YEARS:
            with self.subTest(year=y):
                people = _p(給与=600_000, 繰越純損失=1_000_000)
                self.assertEqual(_calc(y, "所得税_純損失の繰越控除額", **people), 600_000)
                self.assertEqual(_calc(y, V_SOU, **people), 0)
                # 合計所得金額は繰越控除の前（所法2①三十イ(2)、docs/public-sources/20261109_R1-laws_income-tax.md §4）
                self.assertEqual(_calc(y, V_TOTAL, **people), 600_000)

    def test_shibo_7_casualty_carryforward(self) -> None:
        # docs/measurements/20261109_round3_shibo-shukkoku-fetch-and-calc.md §4 [7]：繰越し 800,000、総所得 300,000、退職 100,000 → 400,000 を控除
        r = apply_carryforwards(300_000, 100_000, 0, 800_000)
        self.assertEqual((r.casualty, r.total_income, r.retirement), (400_000, 0, 0))
        for y in YEARS:
            with self.subTest(year=y):
                people = _p(給与=300_000, 退職=100_000, 繰越雑損失=800_000)
                self.assertEqual(_calc(y, "所得税_雑損失の繰越控除額", **people), 400_000)
                self.assertEqual(_calc(y, V_SOU, **people), 0)
                self.assertEqual(_calc(y, "所得税_退職所得金額", **people), 0)
                self.assertEqual(_calc(y, "所得税_総所得金額等", **people), 0)

    def test_net_loss_before_casualty_loss(self) -> None:
        # 所令204②：まず純損失、次に雑損失
        r = apply_carryforwards(500_000, 0, 300_000, 400_000)
        self.assertEqual((r.net, r.casualty, r.total_income), (300_000, 200_000, 0))
        for y in YEARS:
            with self.subTest(year=y):
                people = _p(給与=500_000, 繰越純損失=300_000, 繰越雑損失=400_000)
                self.assertEqual(_calc(y, "所得税_純損失の繰越控除額", **people), 300_000)
                self.assertEqual(_calc(y, "所得税_雑損失の繰越控除額", **people), 200_000)

    def test_c3_sum_of_two_years(self) -> None:
        # §4.3 C3 の年をずらした形：純損失 50万円ずつ（合計100万円）、総所得 70万円 → 70万円を控除
        for y in YEARS:
            self.assertEqual(_calc(y, "所得税_純損失の繰越控除額", **_p(給与=700_000, 繰越純損失=1_000_000)), 700_000)


class TestListed(unittest.TestCase):
    """上場株式等の譲渡損失（措法37の12の2）。計算例：docs/measurements/20261109_round2b_kabu-fetch-and-verify.md §6。"""

    def test_s3_offset(self) -> None:
        ls = listed(100_000, -300_000, 0, offset=True, carry=False)
        self.assertEqual((ls.dividend_offset, ls.gain), (0, 0))
        for y in YEARS:
            with self.subTest(year=y):
                people = _p(上場配当=100_000, 上場譲渡=-300_000, 通算=True)
                self.assertEqual(_calc(y, V_TOTAL, **people), 0)
                self.assertEqual(_calc(y, "所得税_総所得金額等", **people), 0)

    def test_offset_not_elected_leaves_dividend_and_loss_is_nil(self) -> None:
        # 適用の記載がなければ損益通算しない（第3項）。譲渡損失は生じなかったものとみなす（措法37の11①後段）
        for y in YEARS:
            self.assertEqual(_calc(y, V_TOTAL, **_p(上場配当=100_000, 上場譲渡=-300_000, 通算=False)), 100_000)

    def test_s4_carryforward(self) -> None:
        # S4：繰越損失 40万円、譲渡益 30万円、分離の配当 20万円 → 合計所得金額 50万円（適用前）、総所得金額等 10万円（適用後）
        ls = listed(200_000, 300_000, 400_000, offset=False, carry=True)
        self.assertEqual((ls.carry, ls.gain_final, ls.dividend_final), (400_000, 0, 100_000))
        for y in YEARS:
            with self.subTest(year=y):
                people = _p(上場配当=200_000, 上場譲渡=300_000, 繰越上場=400_000, 繰越適用=True)
                self.assertEqual(_calc(y, V_TOTAL, **people), 500_000)
                self.assertEqual(_calc(y, "所得税_上場株式等の譲渡損失の繰越控除額", **people), 400_000)
                self.assertEqual(_calc(y, "所得税_総所得金額等", **people), 100_000)
                self.assertEqual(_calc(y, "所得税_申告分離課税の上場株式等に係る配当所得等の金額", **people), 100_000)
                self.assertEqual(_calc(y, "所得税_申告分離課税の上場株式等に係る譲渡所得等の金額", **people), 0)

    def test_carry_not_elected(self) -> None:
        for y in YEARS:
            people = _p(上場配当=200_000, 上場譲渡=300_000, 繰越上場=400_000, 繰越適用=False)
            self.assertEqual(_calc(y, "所得税_上場株式等の譲渡損失の繰越控除額", **people), 0)
            self.assertEqual(_calc(y, "所得税_総所得金額等", **people), 500_000)


class TestPensionExcludedTotal(unittest.TestCase):
    """公的年金等に係る雑所得以外の合計所得金額（所法35④）。第2項の適用はないものとして計算する（所基通35−8）。"""

    def test_second_paragraph_not_applied_and_pension_excluded(self) -> None:
        for y in YEARS:
            with self.subTest(year=y):
                people = {
                    **_p(給与=300_000, 年金雑=200_000, 雑=200_000),
                    "所得税_業務に係る雑所得の金額": 0,
                    "所得税_その他の雑所得の金額": 0,
                }
                self.assertEqual(_calc(y, "所得税_公的年金等に係る雑所得以外の合計所得金額", **people), 300_000)
                # 第2項は合計所得金額には効く（給与 100,000 ＋ 年金 100,000 − 100,000 ＝ 100,000 を控除）
                self.assertEqual(_calc(y, V_ADJ, **people), 100_000)
                self.assertEqual(_calc(y, V_TOTAL, **people), 400_000)


class TestCarryback(unittest.TestCase):
    """純損失の繰戻しによる還付（所法140①②④）。計算例：docs/measurements/20261109_round2_aoiro-fetch-and-checks.md §4.3 K1〜K3、
    docs/measurements/20261109_round3_shibo-shukkoku-fetch-and-calc.md §4 [6]。税率：docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md §2。"""

    RULES = CarrybackRules(
        1000,
        100,
        (
            (1_950_000, Fraction(5, 100)),
            (3_300_000, Fraction(10, 100)),
            (6_950_000, Fraction(20, 100)),
            (9_000_000, Fraction(23, 100)),
            (18_000_000, Fraction(33, 100)),
            (40_000_000, Fraction(40, 100)),
            (None, Fraction(45, 100)),
        ),
    )

    def test_examples_pure(self) -> None:
        self.assertEqual(carryback_refund(3_000_000, 1_000_000, 10**9, self.RULES), 100_000)  # K1
        self.assertEqual(carryback_refund(1_500_000, 3_000_000, 10**9, self.RULES), 75_000)  # K2（前年の税 75,000 → 0）
        self.assertEqual(carryback_refund(3_000_000, 1_000_000, 50_000, self.RULES), 50_000)  # K3
        self.assertEqual(carryback_refund(4_000_000, 1_500_000, 10**9, self.RULES), 220_000)  # [6] 372,500 − 152,500
        self.assertEqual(carryback_refund(4_000_000, 1_500_000, 100_000, self.RULES), 100_000)  # [6] の限度

    def test_remainder_from_retirement(self) -> None:
        # 所令271①三（[AO] §5.3）：課税総所得金額で控除しきれない残りは課税退職所得金額から。前年の税 75,000＋50,000、後 0＋25,000（課税退職 50万円）
        self.assertEqual(carryback_refund(1_500_000, 2_000_000, 10**9, self.RULES, 1_000_000), 100_000)
        # 境目：残りがなければ課税退職所得金額の税は変わらない
        self.assertEqual(carryback_refund(1_500_000, 1_500_000, 10**9, self.RULES, 1_000_000), 75_000)

    def test_second_prior_refund(self) -> None:
        # 所令272②（[AO] §5.3・shibo-shukkoku §9）：前々年分の課税総所得金額 400万円に 150万円を繰り戻す（[6] と同じ 220,000）
        self.assertEqual(second_prior_refund(4_000_000, 1_500_000, 10**9, self.RULES), 220_000)
        # 後段：前年分の申告で前々年分に 100万円を繰り戻していた（還付 372,500 − 202,500 ＝ 170,000）→ 基礎は 300万円：202,500 − 75,000
        self.assertEqual(second_prior_refund(4_000_000, 1_500_000, 10**9, self.RULES, 0, 1_000_000), 127_500)
        # 限度：税額控除後の所得税の額 200,000 から前の還付 170,000 を引いた 30,000
        self.assertEqual(second_prior_refund(4_000_000, 1_500_000, 200_000, self.RULES, 0, 1_000_000), 30_000)

    def _people(self, **kw: Any) -> dict[str, Any]:
        base = {
            "所得税_純損失の金額": 1_000_000,
            "所得税_青色申告の承認を受けているか": True,
            "所得税_前年分の課税総所得金額": 3_000_000,
            "所得税_前年分の税額控除後の所得税の額": 202_500,
            "所得税_前年分に青色申告書を提出したか": True,
            "所得税_繰り戻す純損失の金額の選択": 1_000_000,
            "所得税_その年分の確定申告書を期限内に提出するか": True,
        }
        base.update(kw)
        return base

    def test_variable_both_years(self) -> None:
        for y in YEARS:
            with self.subTest(year=y):
                self.assertEqual(_calc(y, "所得税_純損失の繰戻しによる還付請求額", **self._people()), 100_000)

    def test_whole_amount_candidate_is_cut_to_the_net_loss(self) -> None:
        # 全額の候補は int の上限の値で表し、式で純損失の金額に切り詰める（一部だけの繰戻しは入力の額：所法140① の「全部又は一部」）
        for y in YEARS:
            self.assertEqual(_calc(y, "所得税_純損失の繰戻しによる還付請求額", **self._people(所得税_繰り戻す純損失の金額の選択=2**31 - 1)), 100_000)
            self.assertEqual(_calc(y, "所得税_純損失の繰戻しによる還付請求額", **self._people(所得税_繰り戻す純損失の金額の選択=500_000)), 50_000)

    def test_requirements(self) -> None:
        # 所法140①④：その年分・前年分が青色、期限内の提出。どれかが欠ければ還付はない
        for y in YEARS:
            for k in ("所得税_青色申告の承認を受けているか", "所得税_前年分に青色申告書を提出したか", "所得税_その年分の確定申告書を期限内に提出するか"):
                with self.subTest(year=y, missing=k):
                    self.assertEqual(_calc(y, "所得税_純損失の繰戻しによる還付請求額", **self._people(**{k: False})), 0)
            self.assertEqual(_calc(y, "所得税_純損失の繰戻しによる還付請求額", **self._people(所得税_繰り戻す純損失の金額の選択=0)), 0)


class TestAdjustmentFirstItem(unittest.TestCase):
    """第1項（措法41の3の11①、docs/public-sources/20261109_round2_gaps-sources.md §3.1・§3.5）の額。1円未満は TA No.1411 の切上げ。"""

    def test_amounts(self) -> None:
        cases = [
            (8_500_000, True, 0),
            (8_500_001, True, 1),  # 0.1 円の切上げ
            (9_000_000, True, 50_000),
            (9_500_000, True, 100_000),
            (10_000_000, True, 150_000),
            (12_000_000, True, 150_000),
            (9_000_000, False, 0),
        ]
        for wage, qualifies, want in cases:
            with self.subTest(wage=wage, qualifies=qualifies):
                self.assertEqual(adjustment_1(wage, qualifies, RULES1), want)


class TestCasualtyOrder(unittest.TestCase):
    """雑損失の繰越控除の順序（所令204①二の読替え：措令4の2⑨・25の11の2⑳、docs/public-sources/20261111_impl-research_joto-junjo-laws.md §2）。"""

    def test_split(self) -> None:
        # 総所得 → 上場配当 → 上場譲渡 → 退職（docs/inferences/20261111_impl-research_joto-junjo-cases.md I2：総合 0・配当100万・譲渡100万・雑損失150万）
        s = split_casualty(0, 0, 1_000_000, 1_000_000, 0, 1_500_000)
        self.assertEqual((s.from_total, s.from_dividend, s.from_gain, s.from_retirement, s.casualty), (0, 1_000_000, 500_000, 0, 1_500_000))
        # 退職所得へは上場分の後
        s = split_casualty(100_000, 200_000, 50_000, 30_000, 0, 500_000)
        self.assertEqual((s.from_total, s.from_dividend, s.from_gain, s.from_retirement, s.casualty), (100_000, 50_000, 30_000, 200_000, 380_000))
        # 純損失は上場分に及ばない（総所得 → 退職だけ）
        s = split_casualty(100_000, 200_000, 50_000, 0, 150_000, 500_000)
        self.assertEqual((s.from_total, s.from_retirement, s.from_dividend, s.casualty), (0, 150_000, 50_000, 200_000))

    def test_variables_both_years(self) -> None:
        people = _p(配当=0, 給与=0, 上場配当=300_000, 上場譲渡=200_000, 退職=100_000, 繰越雑損失=450_000, 通算=True)
        for y in YEARS:
            with self.subTest(year=y):
                self.assertEqual(_calc(y, "所得税_雑損失の繰越控除額", **people), 450_000)
                self.assertEqual(_calc(y, "所得税_申告分離課税の上場株式等に係る配当所得等の金額", **people), 0)
                self.assertEqual(_calc(y, "所得税_申告分離課税の上場株式等に係る譲渡所得等の金額", **people), 50_000)
                self.assertEqual(_calc(y, "所得税_退職所得金額", **people), 100_000)
                self.assertEqual(_calc(y, "所得税_総所得金額等", **people), 150_000)


class TestChecks(unittest.TestCase):
    """計算の後の対象外の検出（rules/income_totals/checks.py）。"""

    def _ctx(self, year: int, values: dict[str, list[Any]]) -> CheckContext:
        return CheckContext(year, ("p",), lambda v: values[v], system().get_parameters_at_instant(f"{year}-01-01"), {})

    def test_carryback_exceeds_taxable(self) -> None:
        values = {
            "所得税_純損失の金額": [3_000_000],
            "所得税_繰り戻す純損失の金額の選択": [3_000_000],
            "所得税_前年分の課税総所得金額": [1_500_000],
            "所得税_青色申告の承認を受けているか": [True],
            "所得税_前年分に青色申告書を提出したか": [True],
            "所得税_その年分の確定申告書を期限内に提出するか": [True],
        }
        values.update({"所得税_前年分の課税山林所得金額": [0], "所得税_前年分の課税退職所得金額等の記載があるか": [False]})
        out = list(carryback_exceeds_taxable(self._ctx(2026, values)))
        self.assertEqual([(e.variable, e.reason.category) for e in out], [("所得税_純損失の繰戻しによる還付請求額", OutOfScopeCategory.NOT_IMPLEMENTED)])
        self.assertEqual(list(carryback_exceeds_taxable(self._ctx(2026, {**values, "所得税_繰り戻す純損失の金額の選択": [1_500_000]}))), [])
        # 記載があれば課税退職所得金額から控除して計算する（対象外にしない）。課税山林所得金額があれば範囲外（D20）
        self.assertEqual(list(carryback_exceeds_taxable(self._ctx(2026, {**values, "所得税_前年分の課税退職所得金額等の記載があるか": [True]}))), [])
        out = list(carryback_exceeds_taxable(self._ctx(2026, {**values, "所得税_前年分の課税山林所得金額": [1]})))
        self.assertEqual([e.reason.category for e in out], [OutOfScopeCategory.OUT_OF_RANGE])




if __name__ == "__main__":
    unittest.main()

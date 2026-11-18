"""住民税の申告書だけで受ける特定支出控除（地方税法第313条第11項・第32条第11項。juminzei の JM-41・JM-42）のユニットテスト。

期待値の出典：docs/public-sources/20261112_impl-research8_tokutei-shishutsu-laws.md（［PS8］）§6（第313条第2項・第11項）、
docs/public-sources/20261112_impl-research9_tokutei-jumin-sources.md（［PS9］）§2.2（所得税法第120条第1項：所得税の額が配当控除の額を超えるとき）、
docs/public-sources/20261109_round2_genka-laws-and-nta.md §6.1（所得税法施行令第198条の損益通算の順）、
docs/public-sources/20261112_impl-research4_shotoku-laws-and-nta.md §1.1（所得税法施行令第180条第2項：一号と二号のいずれか低い金額）、
docs/public-sources/20261109_round2b_nenkin-laws-and-guidance.md §2.1・§2.2（公的年金等控除額：65歳以上・収入330万円以下は、公的年金等に係る雑所得以外の
合計所得金額 1,000万円以下で 110万円、1,000万円超 2,000万円以下で 100万円）、docs/public-sources/20261109_round2_gaps-sources.md §3.1（所得金額調整控除の第2項）。
仮説 impl-research8 H6・H7・H10。上流の値（所得税の値・段が書く値）は入力として与える（D24）。テストのデータは架空。
"""

from __future__ import annotations

import unittest
from typing import Any

from openfisca_core.simulation_builder import SimulationBuilder

from okura_core.injection import EMPTY
from okura_core.registry import Decided, StageContext, StageValue, YearContext, YearWindow
from okura_core.rules.juminzei import MODULE
from okura_core.rules.juminzei import tokutei as tk
from okura_core.rules.juminzei.tokutei import (
    READING_AFTER_CREDITS,
    READING_BEFORE_CREDITS,
    READING_DIVIDEND_CREDIT,
    READING_DIVIDEND_HOUSING_CREDIT,
    owes_income_tax,
)
from okura_core.timepoints import resident_tax_window

from .support import make_ir, person, system


class TestObligation(unittest.TestCase):
    def test_readings_only_matter_when_credits_make_tax_zero(self) -> None:
        # 「前年分の所得税につき納税義務を負わない」：税額控除の後の所得税の額が正なら負う。算出税額も0なら負わない。間だけ読みで分かれる
        self.assertTrue(owes_income_tax(1, 1, 0, None))
        self.assertFalse(owes_income_tax(0, 0, 0, None))
        self.assertIsNone(owes_income_tax(0, 5_000, 0, None))
        self.assertFalse(owes_income_tax(0, 5_000, 0, READING_AFTER_CREDITS))
        self.assertTrue(owes_income_tax(0, 5_000, 0, READING_BEFORE_CREDITS))

    def test_dividend_credit_reading_boundary(self) -> None:
        # 所得税法第120条第1項の基準（［PS9］§2.2：所得税の額が配当控除の額を超えるとき申告の義務）。配当控除の額は算出税額が限度なので、
        # 配当控除だけで0になる人（算出税額＝配当控除の額）は負わない。配当控除が1円足りず残りを住宅借入金等特別控除で0にした人は負う
        self.assertFalse(owes_income_tax(0, 5_000, 5_000, READING_DIVIDEND_CREDIT))
        self.assertTrue(owes_income_tax(0, 5_000, 4_999, READING_DIVIDEND_CREDIT))
        self.assertTrue(owes_income_tax(0, 5_000, 0, READING_DIVIDEND_CREDIT))

    def test_dividend_and_year_end_housing_credit_reading_boundary(self) -> None:
        # 4つ目の候補（措法41の2の2⑥二の読替え：「配当控除の額」を年末調整で控除された住宅借入金等特別控除の額との合計額とする。
        # docs/public-sources/20261111_impl-research3_joto-junjo-laws-and-nta.md §4）。境目は 算出税額 = 合計額 で負わない、1円超えれば負う
        self.assertFalse(owes_income_tax(0, 5_000, 1_000, READING_DIVIDEND_HOUSING_CREDIT, 4_000))
        self.assertTrue(owes_income_tax(0, 5_000, 1_000, READING_DIVIDEND_HOUSING_CREDIT, 3_999))
        self.assertFalse(owes_income_tax(0, 5_000, 0, READING_DIVIDEND_HOUSING_CREDIT, 5_000))  # 年末調整の住宅借入金等特別控除だけで0
        self.assertTrue(owes_income_tax(0, 5_000, 0, READING_DIVIDEND_CREDIT, 5_000))  # 3つ目の候補は住宅借入金等特別控除を加えない


YEAR = 2025  # 令和8年度分（所得の年分 2025）


def _run_stage(values: dict[str, Any], choice: Any = True, reading: str = READING_AFTER_CREDITS) -> Any:
    """段 住民税の特定支出控除の申告 を直接呼ぶ（前の段の値はスタブ。選択は Decided で与える）。"""
    ir = make_ir([person("p", "1985-01-01")], [])
    decided = {(tk.C_RESIDENT_RETURN, tk.specific_key("p", YEAR + 1)): Decided(choice, ("c-1",) if choice is True else (), frozenset(), False)}
    window = YearWindow(
        parameters_at=lambda s: system().parameters(s),
        parameter_root=system().parameters,
        windows=(resident_tax_window(YEAR + 1),),
        injected=EMPTY,
        rounding={tk.READING: reading},
    )
    base = YearContext(ir, YEAR, ("p",), decided, window=window)
    defaults: dict[str, Any] = {v: 0 for v in tk.READS}
    defaults.update({tk.R_OVER: True, tk.R_APPLY_IT: False})
    defaults.update(values)
    stage_values = {(v, "p"): StageValue(v, "p", x) for v, x in defaults.items()}
    spec = next(s for s in MODULE.stages if s.name == tk.STAGE)
    return tk.run(StageContext(base, spec, stage_values)).inputs


class TestStage(unittest.TestCase):
    BASE = {tk.R_G313: 1_700_000, tk.R_TOTAL: 1_700_000, tk.R_TOTAL_SEP: 1_200_000, tk.R_TAISHOKU: 300_000}

    def test_applies_when_no_income_tax_and_return_says_so(self) -> None:
        o = _run_stage(self.BASE)
        self.assertTrue(o.values[(tk.W_APPLY, "p")].value)
        self.assertEqual(o.values[(tk.W_KYUYO, "p")].value, 1_700_000)
        self.assertEqual(o.values[(tk.W_TOTAL, "p")].value, 1_700_000)
        self.assertEqual(o.values[(tk.W_TAISHOKU, "p")].value, 300_000)
        self.assertEqual(o.exclusions, [])

    def test_separate_retirement_income_uses_the_window_without_it(self) -> None:
        # 分離課税に係る退職所得のある人（JM-20）：退職所得を除いた窓口の合計所得金額、退職所得は0
        o = _run_stage({**self.BASE, tk.R_SEPARATE: 500_000})
        self.assertEqual(o.values[(tk.W_TOTAL, "p")].value, 1_200_000)
        self.assertEqual(o.values[(tk.W_TAISHOKU, "p")].value, 0)

    def test_not_applied(self) -> None:
        for extra, choice in (
            ({tk.R_APPLY_IT: True}, True),  # 所得税の申告書等で受けた（第313条第2項の計算の例で所得税の給与所得に従う）
            ({tk.R_OVER: False}, True),  # 2分の1を超えない
            ({tk.R_TAX_AFTER: 1, tk.R_TAX_BEFORE: 1}, True),  # 前年分の所得税の納税義務を負う
            ({}, False),  # 住民税の申告書に記載しない
        ):
            with self.subTest(extra=extra, choice=choice):
                o = _run_stage({**self.BASE, **extra}, choice)
                self.assertFalse(o.values[(tk.W_APPLY, "p")].value)
                self.assertEqual(o.values[(tk.W_TOTAL, "p")].value, 0)

    def test_reading_of_tax_obligation(self) -> None:
        vals = {**self.BASE, tk.R_TAX_BEFORE: 30_000}  # 税額控除で0になった
        self.assertTrue(_run_stage(vals, reading=READING_AFTER_CREDITS).values[(tk.W_APPLY, "p")].value)
        self.assertFalse(_run_stage(vals, reading=READING_BEFORE_CREDITS).values[(tk.W_APPLY, "p")].value)
        # 3つ目の候補（所得税法第120条第1項の基準）：段が配当控除の額を読む
        self.assertTrue(_run_stage({**vals, tk.R_DIVIDEND: 30_000}, reading=READING_DIVIDEND_CREDIT).values[(tk.W_APPLY, "p")].value)
        self.assertFalse(_run_stage({**vals, tk.R_DIVIDEND: 29_999}, reading=READING_DIVIDEND_CREDIT).values[(tk.W_APPLY, "p")].value)
        # 4つ目の候補：段が年末調整で控除された住宅借入金等特別控除の額も読む
        both = {**vals, tk.R_DIVIDEND: 10_000, tk.R_HOUSING_YEAR_END: 20_000}
        self.assertTrue(_run_stage(both, reading=READING_DIVIDEND_HOUSING_CREDIT).values[(tk.W_APPLY, "p")].value)
        self.assertFalse(_run_stage(both, reading=READING_DIVIDEND_CREDIT).values[(tk.W_APPLY, "p")].value)
        short = {**both, tk.R_HOUSING_YEAR_END: 19_999}
        self.assertFalse(_run_stage(short, reading=READING_DIVIDEND_HOUSING_CREDIT).values[(tk.W_APPLY, "p")].value)


def _calc(var: str, values: dict[str, Any], year: int = 2025) -> int:
    situation = {"人物一覧": {"p": {v: {str(year): x} for v, x in values.items()}}}
    return int(SimulationBuilder().build_from_entities(system(), situation).calculate(var, str(year))[0])


class TestWindows(unittest.TestCase):
    """所得税の各モジュールの窓口（JM-42）：特定支出控除を当てた場合の給与所得から始まる連鎖を、所得税と同じ関数で計算し直す。"""

    OVER = "所得税_特定支出の額の合計額が給与所得控除額の2分の1を超えるか"
    G_PRE = "所得税_特定支出控除を当てた場合の給与所得の金額"
    G_POST = "所得税_特定支出控除を当てた場合の回収不能額等の後の給与所得の金額"
    TOTAL = "所得税_特定支出控除を当てた場合の合計所得金額"

    def test_second_item_difference_in_kyuyo(self) -> None:
        # 令和7年分：給与所得控除額は 300万円 → 980,000（30%＋8万円）、200万円 → 680,000。特定支出 60万円はどちらも2分の1 を超える。
        # G'(300万) ＝ 3,000,000 − 980,000 − (600,000 − 490,000) ＝ 1,910,000、G'(200万) ＝ 2,000,000 − 680,000 − (600,000 − 340,000) ＝ 1,060,000
        values = {"所得税_給与等の収入金額": 3_000_000, "所得税_特定支出の額の合計額": 600_000, "所得税_回収することができないこととなった給与等の金額": 1_000_000}
        self.assertEqual(_calc("所得税_特定支出控除を当てた場合の回収不能額等に係る給与所得の金額の差額", values), 1_910_000 - 1_060_000)
        self.assertEqual(_calc("所得税_特定支出控除を当てた場合の回収不能額等に係る給与所得の金額の差額", {**values, "所得税_回収することができないこととなった給与等の金額": 0}), 0)

    def test_uncollectible_cap_is_the_lower_of_two_items(self) -> None:
        # 一号（直前の総所得金額）：事業 −150万円 ＋ 給与 191万円 ＝ 41万円 ＜ 二号 85万円 → 給与所得から 41万円を引く（JM-42 の以前の c-限界）
        base = {
            self.OVER: True, self.G_PRE: 1_910_000, "所得税_回収することができないこととなった給与等の金額": 1_000_000,
            "所得税_特定支出控除を当てた場合の回収不能額等に係る給与所得の金額の差額": 850_000, "所得税_事業所得の金額": -1_500_000,
        }  # fmt: skip
        self.assertEqual(_calc("所得税_特定支出控除を当てた場合の回収不能額等の前の総所得金額と退職所得金額の合計額", base), 410_000)
        self.assertEqual(_calc(self.G_POST, base), 1_910_000 - 410_000)
        self.assertEqual(_calc(self.TOTAL, base), 0)
        # 二号が低い（事業の損失なし：一号 191万円）→ 二号の 85万円を引く
        self.assertEqual(_calc(self.G_POST, {**base, "所得税_事業所得の金額": 0}), 1_910_000 - 850_000)

    def test_without_uncollectible_and_not_over(self) -> None:
        self.assertEqual(_calc(self.G_POST, {self.OVER: True, self.G_PRE: 1_700_000}), 1_700_000)
        self.assertEqual(_calc(self.G_POST, {self.OVER: False, self.G_PRE: 1_700_000}), 0)
        self.assertEqual(_calc(self.TOTAL, {self.OVER: False, self.G_PRE: 1_700_000, "所得税_事業所得の金額": 100_000}), 0)

    def test_pension_bracket_changes_with_the_salary(self) -> None:
        # 70歳・公的年金等の収入 200万円。所得税の値は区分が 1,000万円超（控除 100万円 → 雑所得 100万円）。特定支出控除の後は給与 970万円 ＋ 事業 20万円 ＝ 990万円
        # ≦ 1,000万円 なので控除 110万円 → 雑所得 90万円（JM-42 の以前の c-限界）。所得金額調整控除の第2項は 10万円のまま（両方とも 10万円以上）。
        values = {
            self.OVER: True, self.G_PRE: 9_700_000, "所得税_事業所得の金額": 200_000, "所得税_公的年金等の収入金額": 2_000_000, "所得税_年齢": 70,
            "所得税_公的年金等に係る雑所得の金額": 1_000_000, "所得税_雑所得の金額": 1_000_000, "所得税_所得金額調整控除": 100_000,
            "所得税_給与所得控除後の給与等の金額": 10_000_000,
        }  # fmt: skip
        self.assertEqual(_calc("所得税_特定支出控除を当てた場合の公的年金等に係る雑所得以外の合計所得金額", values), 9_900_000)
        self.assertEqual(_calc("所得税_特定支出控除を当てた場合の公的年金等に係る雑所得の金額", values), 900_000)
        self.assertEqual(_calc(self.TOTAL, values), 200_000 + (9_700_000 - 100_000) + 900_000)

    def test_adjustment_second_paragraph_follows_the_pension(self) -> None:
        # 給与所得控除後の給与等の金額 5万円・公的年金等に係る雑所得の所得税の値 8万円 → 第2項 3万円。特定支出控除の後の区分の雑所得が 6万円なら 1万円
        values = {
            self.OVER: True, self.G_PRE: 40_000, "所得税_事業所得の金額": 300_000, "所得税_公的年金等の収入金額": 1_160_000, "所得税_年齢": 70,
            "所得税_公的年金等に係る雑所得の金額": 80_000, "所得税_雑所得の金額": 80_000, "所得税_所得金額調整控除": 30_000,
            "所得税_給与所得控除後の給与等の金額": 50_000, "所得税_特定支出控除を当てた場合の公的年金等に係る雑所得の金額": 60_000,
        }  # fmt: skip
        # 給与所得 4万円 − 第2項 1万円（所得税の値の 3万円ではない）＋ 事業 30万円 ＋ 雑 6万円
        self.assertEqual(_calc(self.TOTAL, values), 30_000 + 300_000 + 60_000)
        # 給与所得が第2項の額より小さければ、負の給与所得は損益通算しない（0）
        self.assertEqual(_calc(self.TOTAL, {**values, self.G_PRE: 5_000}), 300_000 + 60_000)

    def test_separate_retirement_window(self) -> None:
        # 分離課税に係る退職所得のある人：退職所得を除き、公的年金等は退職所得を除いた区分の額
        values = {
            self.OVER: True, self.G_PRE: 1_000_000, "所得税_退職所得の金額": 2_000_000, "所得税_事業所得の金額": -300_000,
        }  # fmt: skip
        self.assertEqual(_calc("所得税_特定支出控除を当てた場合の分離課税の退職所得を除いた合計所得金額", values), 700_000)
        self.assertEqual(_calc(self.TOTAL, values), 700_000 + 2_000_000)
        # 損失が経常所得を超えると退職所得から控除する（所令198 五号）
        values = {**values, "所得税_事業所得の金額": -1_300_000}
        self.assertEqual(_calc("所得税_特定支出控除を当てた場合の損益通算の後の退職所得の金額", values), 2_000_000 - 300_000)
        self.assertEqual(_calc("所得税_特定支出控除を当てた場合の分離課税の退職所得を除いた合計所得金額", values), 0)


class TestVariables(unittest.TestCase):
    """住民税の前年の所得の窓口：段が書いた第313条第11項の値を、当たる人だけ使う。"""

    def _calc(self, var: str, applies: bool) -> int:
        values = {
            "所得税_給与所得": 2_000_000,
            "所得税_合計所得金額": 2_000_000,
            "所得税_総所得金額等": 2_000_000,
            "所得税_総所得金額": 2_000_000,
            "住民税_住民税の申告書で特定支出控除を受けるか": applies,
            "住民税_第313条第11項の給与所得の金額": 1_700_000,
            "住民税_第313条第11項の合計所得金額": 1_700_000,
        }
        situation = {"人物一覧": {"p": {v: {"2025": x} for v, x in values.items()}}}
        return int(SimulationBuilder().build_from_entities(system(), situation).calculate(var, "2025")[0])

    def test_kyuyo_and_totals(self) -> None:
        self.assertEqual(self._calc("住民税_給与所得の金額", True), 1_700_000)
        self.assertEqual(self._calc("住民税_給与所得の金額", False), 2_000_000)
        self.assertEqual(self._calc("住民税_合計所得金額", True), 1_700_000)
        self.assertEqual(self._calc("住民税_合計所得金額", False), 2_000_000)
        # 繰越控除の後の総所得金額等は住民税の繰越の計算（calc.jumin_casualty_carryforward）で計算し直す（繰越がなければ合計所得金額と同じ）
        self.assertEqual(self._calc("住民税_総所得金額等", True), 1_700_000)
        self.assertEqual(self._calc("住民税_総所得金額等", False), 2_000_000)


if __name__ == "__main__":
    unittest.main()

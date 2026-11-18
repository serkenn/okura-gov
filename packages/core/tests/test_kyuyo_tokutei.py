"""給与所得者の特定支出控除（所得税法第57条の2・措法29の4③。kyuyo の KY-11、2026-11-12）のユニットテスト。

期待値の出典：docs/public-sources/20261112_impl-research8_tokutei-shishutsu-laws.md（［PS8］）§1（第57条の2）・§2（施行令第167条の3）・§3（施行規則第36条の5）・
§4（措法29の4）・§7.3（情報の算式「収入 − 給与所得控除額 − （特定支出の額の合計額 − 給与所得控除額の1/2）」）。仮説 H1〜H6。
上流の値（給与等の収入金額・特定支出の額の合計額・適用を受けるか）は入力として与える（D24）。
"""

from __future__ import annotations

import unittest
from fractions import Fraction
from typing import Any

from openfisca_core.simulation_builder import SimulationBuilder

from okura_core.rounding import ceil_yen, floor_yen
from okura_core.rules.income_totals.calc import Incomes, offset_losses
from okura_core.rules.kyuyo.calc import deduction_rules_from_parameters, kyuyo_deduction, kyuyo_shotoku, rules_from_parameters
from okura_core.rules.kyuyo.tokutei import (
    CONSULTANT_REASON,
    PASS_REASON,
    TRANSFER_REASON,
    category_code_sum,
    collect,
    expense_year,
    finish,
    form_rows,
    needs_route_judgment,
    tokutei_raw,
)

from okura_core.rules.income_kinds.forms_items import join_articles, tokutei_text

from .support import system

CAP, SLEEPER = 650_000, 6_600  # ［PS8］§1（第2項第7号）・§3（所規36の5③）


def _se(rid: str, category: str, amount: int, on: str = "2026-06-01", certified_by: str = "payer", **kw: Any) -> dict[str, Any]:
    amounts = {"amount": amount, **kw.pop("amounts", {})}
    return {"id": rid, "kind": "specific_expense", "roles": {"payer": "p"}, "when": {"on": on}, "amounts": amounts,
            "attributes": {"category": category, "certified_by": certified_by, **kw}}  # fmt: skip


def _rules(year: int) -> tuple[Any, Any]:
    p = system().get_parameters_at_instant(f"{year}-01-01")
    return rules_from_parameters(p), deduction_rules_from_parameters(p)


class TestCollect(unittest.TestCase):
    """特定支出の額の合計額（所法57の2②・所令167の3・所規36の5）。"""

    def _total(self, recs: list[dict[str, Any]]) -> int:
        c = collect(recs, books_cap=CAP, sleeper_cap=SLEEPER)
        self.assertEqual(c.problems, [])
        return c.total

    def test_certification_and_consultant_scope(self) -> None:
        # 証明のない支出は特定支出でない。キャリアコンサルタントの証明は研修費・資格取得費の教育訓練に係る部分だけ（第2項第4号・第5号）
        self.assertEqual(self._total([_se("a", "books", 10_000, certified_by="none")]), 0)
        self.assertEqual(self._total([_se("a", "books", 10_000, certified_by="career_consultant", education_training=True)]), 0)
        self.assertEqual(self._total([_se("a", "training", 10_000, certified_by="career_consultant", education_training=False)]), 0)
        self.assertEqual(self._total([_se("a", "training", 10_000, certified_by="career_consultant", education_training=True)]), 10_000)
        c = collect([_se("a", "qualification", 10_000, certified_by="career_consultant")], books_cap=CAP, sleeper_cap=SLEEPER)
        self.assertEqual([r.reason for r in c.problems], [CONSULTANT_REASON])

    def test_transit_is_capped_by_commuter_pass_then_reimbursement_is_removed(self) -> None:
        # 所令167の3①一：運賃の合計が定期乗車券等の価額の合計を超えるときはその合計。補塡（非課税）はその後に引く（明細書のⒶ−Ⓑ）
        rec = _se("a", "commuting_transit", 100_000, amounts={"commuter_pass_value": 80_000, "reimbursed_nontaxable": 30_000})
        self.assertEqual(self._total([rec]), 50_000)
        c = collect([_se("b", "commuting_transit", 100_000)], books_cap=CAP, sleeper_cap=SLEEPER)
        self.assertEqual([r.reason for r in c.problems], [PASS_REASON])
        # 通勤費は航空機の利用に係るものを除く
        self.assertEqual(self._total([_se("c", "commuting_transit", 50_000, air_travel=True, amounts={"commuter_pass_value": 50_000})]), 0)

    def test_special_seat_and_sleeper_fees(self) -> None:
        # 特別車両料金等を除く。寝台料金は 6,600円以下のものを除かない（所規36の5③④）
        rec = _se("a", "business_travel", 50_000, amounts={"special_seat_fee": 5_000}, sleeper_fees=[6_600, 6_601])
        self.assertEqual(self._total([rec]), 50_000 - 5_000 - 6_601)
        # 研修費などの運賃でない区分は除かない
        self.assertEqual(self._total([_se("b", "training", 50_000, amounts={"special_seat_fee": 5_000})]), 50_000)

    def test_relocation_within_one_year_of_transfer(self) -> None:
        # 所令167の3③：転任の事実が生じた日以後1年以内（初日を算入：法令の読み）
        ok = _se("a", "relocation", 100_000, on="2026-03-31", transfer_on="2025-04-01")
        late = _se("b", "relocation", 100_000, on="2026-04-01", transfer_on="2025-04-01")
        before = _se("c", "relocation", 100_000, on="2025-03-31", transfer_on="2025-04-01")
        self.assertEqual(self._total([ok, late, before]), 100_000)
        c = collect([_se("d", "relocation", 100_000)], books_cap=CAP, sleeper_cap=SLEEPER)
        self.assertEqual([r.reason for r in c.problems], [TRANSFER_REASON])

    def test_work_needs_are_capped_at_650000(self) -> None:
        # 第2項第7号：図書・衣服・交際費等の合計は65万円まで（補塡を引いた後の合計に当てる：明細書の⑩）
        recs = [_se("a", "books", 400_000), _se("b", "clothing", 200_000), _se("c", "entertainment", 100_000, amounts={"reimbursed_nontaxable": 20_000})]
        self.assertEqual(self._total(recs), 650_000)
        self.assertEqual(self._total(recs + [_se("d", "training", 10_000)]), 660_000)

    def test_form_rows_and_category_codes(self) -> None:
        # 明細書 KOB070 の区分の行（2026-11-12 の3回目）：Ⓐ は上限の後の支出金額、Ⓑ は補塡、Ⓒ＝Ⓐ−Ⓑ。⑩ は勤務必要経費の小計（65万円まで）。
        # ⑫ は差引金額が正の区分の区分番号の和（通勤費1・転居費2・研修費4・資格取得費8・帰宅旅費16・図書費32・衣服費64・交際費等128・職務上の旅費256：
        # docs/public-sources/20261112_impl-research9_tokutei-jumin-sources.md §4.3、仮説 impl-research9 H4）
        recs = [
            _se("a", "commuting_transit", 100_000, amounts={"commuter_pass_value": 80_000, "reimbursed_nontaxable": 30_000}),
            _se("b", "books", 400_000), _se("c", "clothing", 200_000),
            _se("d", "entertainment", 100_000, amounts={"reimbursed_nontaxable": 100_000}),
            _se("e", "business_travel", 10_000),
        ]  # fmt: skip
        c = collect(recs, books_cap=CAP, sleeper_cap=SLEEPER)
        rows = form_rows(c)
        self.assertEqual(rows[0], (80_000, 30_000, 50_000))  # 通勤費（定期乗車券等の価額の合計まで）
        self.assertEqual(rows[1], (10_000, 0, 10_000))  # 職務上の旅費
        self.assertEqual(rows[8], (100_000, 100_000, 0))  # 交際費等：差引金額0
        self.assertEqual(c.work, 600_000)
        self.assertEqual(c.total, 50_000 + 10_000 + 600_000)
        self.assertEqual(category_code_sum(c), 1 + 256 + 32 + 64)  # 交際費等（差引金額0）は数えない
        self.assertEqual(category_code_sum(collect([], books_cap=CAP, sleeper_cap=SLEEPER)), 0)

    def test_route_judgment_caps_after_special_fees(self) -> None:
        # KY-13（2026-11-12 の2回目）：旅費・帰宅旅費・転居の運賃と宿泊費は、通常の範囲の額（判断）までを数える（所令167の3②③⑤）。
        # 特別車両料金等を除いた額をその額で抑える（法令の読み）。None（判断の端：全部）は抑えない、0 は数えない
        trip = _se("a", "business_travel", 90_000, amounts={"special_seat_fee": 8_000})
        self.assertEqual(collect([trip], books_cap=CAP, sleeper_cap=SLEEPER, caps={"a": 70_000}).total, 70_000)
        self.assertEqual(collect([trip], books_cap=CAP, sleeper_cap=SLEEPER, caps={"a": 85_000}).total, 82_000)
        self.assertEqual(collect([trip], books_cap=CAP, sleeper_cap=SLEEPER, caps={"a": None}).total, 82_000)
        self.assertEqual(collect([trip], books_cap=CAP, sleeper_cap=SLEEPER, caps={"a": 0}).total, 0)

    def test_which_expenses_need_the_route_judgment(self) -> None:
        self.assertTrue(needs_route_judgment(_se("a", "business_travel", 1)))
        self.assertTrue(needs_route_judgment(_se("a", "home_leave", 1)))
        self.assertTrue(needs_route_judgment(_se("a", "relocation", 1, relocation_item="lodging")))
        self.assertTrue(needs_route_judgment(_se("a", "relocation", 1)))  # 支出の別がなければ運賃・宿泊費でありうる
        self.assertFalse(needs_route_judgment(_se("a", "relocation", 1, relocation_item="vehicle")))  # 所令167の3③二・四
        self.assertFalse(needs_route_judgment(_se("a", "relocation", 1, relocation_item="moving")))
        self.assertFalse(needs_route_judgment(_se("a", "business_travel", 1, certified_by="none")))
        self.assertFalse(needs_route_judgment(_se("a", "commuting_transit", 1)))  # 通勤は支払者の証明した経路（所令167の3①）

    def test_expense_year(self) -> None:
        self.assertEqual(expense_year(_se("a", "books", 1, on="2026-12-31")), 2026)
        self.assertEqual(expense_year(_se("a", "commuting_transit", 1, on="2026-04-01", attributed_year=2027)), 2027)


class TestTokuteiShotoku(unittest.TestCase):
    """給与所得の金額（所法57の2①・措法29の4③）。"""

    def test_threshold_is_more_than_half_of_deduction(self) -> None:
        # 令和7年分：収入 500万円 の給与所得控除額は 116万＋（500万−360万）×20％＝144万円（第28条第3項）。2分の1＝72万円
        rules, drules = _rules(2025)
        self.assertEqual(kyuyo_deduction(5_000_000, drules).amount, 1_440_000)
        self.assertIsNone(tokutei_raw(5_000_000, 720_000, rules, drules))  # 「超える」とき（ちょうど2分の1は当たらない）
        self.assertEqual(tokutei_raw(5_000_000, 720_001, rules, drules), 5_000_000 - 1_440_000 - 1)

    def test_beppyo5_is_not_used(self) -> None:
        # 第1項「同条第四項の規定にかかわらず、同条第二項の残額から」：別表第五（区分の下限で計算）ではなく収入 − 控除額
        rules, drules = _rules(2025)
        income = 3_001_234
        ded = kyuyo_deduction(income, drules).amount
        raw = tokutei_raw(income, 2_000_000, rules, drules)
        self.assertEqual(raw, income - ded - (2_000_000 - ded / 2))
        self.assertNotEqual(kyuyo_shotoku(income, rules).value, floor_yen(income - ded))  # 別表第五の額は式の額と違う収入

    def test_sochi_29_4_reading_in_2026(self) -> None:
        # 令和8年分：収入 200万円 は措法29の4② 第2号で 200万−74万＝126万円。給与所得控除額は措法29の4① の 74万円、2分の1＝37万円。
        # 第3項の読替え：同項の給与所得の金額から超える部分を控除する
        rules, drules = _rules(2026)
        self.assertEqual(kyuyo_shotoku(2_000_000, rules).value, 1_260_000)
        self.assertEqual(kyuyo_deduction(2_000_000, drules).amount, 740_000)
        self.assertIsNone(tokutei_raw(2_000_000, 370_000, rules, drules))
        self.assertEqual(tokutei_raw(2_000_000, 500_000, rules, drules), 1_260_000 - 130_000)

    def test_fraction_and_negative(self) -> None:
        # 1円未満は候補で丸める（定めがない）。負なら0（H3）
        self.assertEqual(finish(Fraction(7, 2), floor_yen), 3)
        self.assertEqual(finish(Fraction(7, 2), ceil_yen), 4)
        self.assertEqual(finish(Fraction(-5), floor_yen), 0)

    def test_variable_applies_only_when_chosen(self) -> None:
        # 所得税_給与所得：適用を受けるか（所法57の2③）が偽なら第28条の額のまま。給与所得控除後の給与等の金額（措法41の3の11④五）は特定支出控除の前
        def calc(var: str, apply: bool) -> int:
            values = {"所得税_給与等の収入金額": 5_000_000, "所得税_特定支出の額の合計額": 1_000_000, "所得税_特定支出控除の適用を受けるか": apply}
            situation = {"人物一覧": {"p": {v: {"2025": x} for v, x in values.items()}}}
            return int(SimulationBuilder().build_from_entities(system(), situation).calculate(var, "2025")[0])

        self.assertEqual(calc("所得税_給与所得", True), 5_000_000 - 1_440_000 - (1_000_000 - 720_000))
        self.assertEqual(calc("所得税_給与所得", False), 3_560_000)
        self.assertEqual(calc("所得税_給与所得控除後の給与等の金額", True), 3_560_000)
        # 地方税法第313条第11項のための、選択によらない特定支出控除の後の額と「2分の1を超えるか」（2026-11-12 の2回目）
        self.assertEqual(calc("所得税_特定支出控除を当てた場合の給与所得の金額", False), 5_000_000 - 1_440_000 - (1_000_000 - 720_000))
        self.assertEqual(calc("所得税_特定支出の額の合計額が給与所得控除額の2分の1を超えるか", False), 1)

    def test_half_threshold_variable_at_exactly_half(self) -> None:
        values = {"所得税_給与等の収入金額": 5_000_000, "所得税_特定支出の額の合計額": 720_000}
        situation = {"人物一覧": {"p": {v: {"2025": x} for v, x in values.items()}}}
        sim = SimulationBuilder().build_from_entities(system(), situation)
        self.assertFalse(bool(sim.calculate("所得税_特定支出の額の合計額が給与所得控除額の2分の1を超えるか", "2025")[0]))
        self.assertEqual(int(sim.calculate("所得税_特定支出控除を当てた場合の給与所得の金額", "2025")[0]), 3_560_000)


class TestOffsetWithNegativeKyuyo(unittest.TestCase):
    def test_negative_salary_income_is_not_offset(self) -> None:
        # 所得金額調整控除の第2項（特定支出控除の前の額で計算）を引いて給与所得が負になっても、損益通算しない（所法69①：H3・H6）
        self.assertEqual(offset_losses(Incomes(0, 0, 300_000, -50_000, 0, 0)).keijo, 300_000)


def _value(var: str, values: dict[str, Any]) -> Any:
    situation = {"人物一覧": {"p": {v: {"2025": x} for v, x in values.items()}}}
    return SimulationBuilder().build_from_entities(system(), situation).calculate(var, "2025")[0]


class TestFormConcepts(unittest.TestCase):
    """様式の欄の材料（2026-11-12 の3回目）。期待値の出典：docs/public-sources/20261112_impl-research9_tokutei-jumin-sources.md §4.1（手引き 3-2_06）・§6（明細書の注記）、
    docs/public-sources/20261109_round2_gaps-sources.md §3.1（所得金額調整控除：第1項は収入850万円超、第2項は {min(給与,10万)＋min(年金,10万)}−10万）。上流はスタブ。"""

    def test_adjustment_kubun_for_g13(self) -> None:
        # ㋔ の区分 G13：Step3 の(1)（第1項）→1、(2)（第2項）→2、両方→3、なし
        base = {"所得税_給与等の収入金額": 9_000_000, "所得税_給与所得控除後の給与等の金額": 7_050_000, "所得税_所得金額調整控除の対象の親族等を有するか": True}
        self.assertEqual(_value("所得税_所得金額調整控除の区分", base), "1")
        self.assertEqual(_value("所得税_所得金額調整控除の区分", {**base, "所得税_公的年金等に係る雑所得の金額": 1}), "3")
        small = {"所得税_給与等の収入金額": 700_000, "所得税_給与所得控除後の給与等の金額": 50_000, "所得税_公的年金等に係る雑所得の金額": 80_000}
        self.assertEqual(_value("所得税_所得金額調整控除の区分", small), "2")
        self.assertEqual(_value("所得税_所得金額調整控除の区分", {**small, "所得税_公的年金等に係る雑所得の金額": 50_000}), "なし")  # 合計 10万円ちょうどは超えない
        self.assertEqual(_value("所得税_所得金額調整控除の区分", {**base, "所得税_所得金額調整控除の対象の親族等を有するか": False}), "なし")

    def test_salary_after_adjustment_for_box_6(self) -> None:
        # ⑥：手引きの計算欄 J＝C−(F＋I)。負なら0
        self.assertEqual(int(_value("所得税_所得金額調整控除の後の給与所得の金額", {"所得税_給与所得": 7_050_000, "所得税_所得金額調整控除": 50_000})), 7_000_000)
        self.assertEqual(int(_value("所得税_所得金額調整控除の後の給与所得の金額", {"所得税_給与所得": 5_000, "所得税_所得金額調整控除": 10_000})), 0)

    def test_tokurei_article_for_table_2(self) -> None:
        # 第二表「特例適用条文等」：特定支出控除を受けるときだけ「所法57の2 」と ⑪ 特定支出の合計額（3桁ごとのカンマ）
        base = {"所得税_特定支出の額の合計額": 1_234_567, "所得税_特定支出控除の適用を受けるか": True, "所得税_特定支出の額の合計額が給与所得控除額の2分の1を超えるか": True}
        self.assertEqual(_value("所得税_第二表の特例適用条文等", base), "所法57の2 1,234,567円")
        self.assertEqual(_value("所得税_第二表の特例適用条文等", {**base, "所得税_特定支出控除の適用を受けるか": False}), "なし")
        self.assertEqual(_value("所得税_第二表の特例適用条文等", {**base, "所得税_特定支出の額の合計額が給与所得控除額の2分の1を超えるか": False}), "なし")
        self.assertEqual(join_articles("措法27", tokutei_text(300_000)), "措法27、所法57の2 300,000円")
        self.assertEqual(join_articles(None, None), "なし")


if __name__ == "__main__":
    unittest.main()

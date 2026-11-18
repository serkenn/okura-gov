"""未払のまま回収できなくなった給与（所得税法第64条第1項・施行令第180条第2項。kyuyo の README KY-08）のユニットテスト。上流はスタブ。

期待値の出典：docs/public-sources/20261112_impl-research4_shotoku-laws-and-nta.md §1（法64①：給与所得は除かれていない、「各種所得の金額の計算上
なかつたものとみなす」）・§1.1（令180②一・二のいずれか低い金額）・§1.3（所基通64−3：損益通算・繰越控除の後の総所得金額）、推測
docs/inferences/20261112_impl-research4_all-cases.md I1（給与の収入 300万円・回収不能 30万円で、二号＝G(300万)−G(270万)）。
給与所得の金額は別表第五（令和8年分。docs/public-sources/20261109_impl-prep_kyuyo-sources.md §1）：300万円 → 2,020,000、270万円 → 1,810,000、
900万円 → 7,050,000、800万円 → 6,050,000。所得金額調整控除の第1項（docs/public-sources/20261109_round2_gaps-sources.md §3.1）：900万円 → 50,000。
テストのデータは架空。
"""

from __future__ import annotations

import unittest
from typing import Any

from openfisca_core.simulation_builder import SimulationBuilder

from okura_core.registry import StageContext, StageValue, YearContext
from okura_core.rules.kyuyo.inputs import V_INCOME, V_UNCOLLECTIBLE, _uncollectible, build_inputs
from okura_core.rules.kyuyo.uncollectible import ORDER_LIMIT_REASON, STAGE, V_CAP, V_DIFF, V_HAS, V_TOTAL, V_TOTAL_WITH_1, run

from .support import make_ir, person, system

V_SHOTOKU = "所得税_給与所得"


def _sim(year: int, values: dict[str, Any]) -> Any:
    situation = {"人物一覧": {"p": {v: {str(year): x} for v, x in values.items()}}}
    return SimulationBuilder().build_from_entities(system(), situation)


def _calc(var: str, **values: Any) -> int:
    return int(_sim(2026, values).calculate(var, "2026")[0])


def _pay(**kw: Any) -> dict[str, Any]:
    amounts = {"gross": 3_000_000, **kw.pop("amounts", {})}
    return {"id": "s-1", "kind": "salary_payment", "roles": {"recipient": "p-1"}, "when": {"on": "2026-12-25"},
            "attributes": {"counterparty": "架空の会社", "due_on": "2026-12-25", **kw}, "amounts": amounts}  # fmt: skip


class SalaryFormulaTest(unittest.TestCase):
    """所得税_給与所得 ＝ 64①の前の給与所得 − min(令180②一〔段が書く上限〕, 令180②二〔差額〕)。"""

    BASE = {"所得税_給与等の収入金額": 3_000_000, V_UNCOLLECTIBLE: 300_000}

    def test_second_item_is_the_difference(self) -> None:
        # 令180②二：G(300万) − G(270万) ＝ 2,020,000 − 1,810,000（I1）
        self.assertEqual(_calc(V_DIFF, **self.BASE), 210_000)

    def test_lower_of_two_items(self) -> None:
        # 上限（一号）が二号以上：収入から30万円を除いたのと同じ G(270万)（I1）
        self.assertEqual(_calc(V_SHOTOKU, **self.BASE, **{V_CAP: 5_000_000}), 1_810_000)
        self.assertEqual(_calc(V_SHOTOKU, **self.BASE, **{V_CAP: 210_000}), 1_810_000)  # 境目：一号＝二号
        # 一号が二号より低い：その額だけ給与所得の金額から引く（法64①「各種所得の金額の計算上」：収入金額を減らす読みにしない）
        self.assertEqual(_calc(V_SHOTOKU, **self.BASE, **{V_CAP: 209_999}), 2_020_000 - 209_999)
        self.assertEqual(_calc(V_SHOTOKU, **self.BASE, **{V_CAP: 0}), 2_020_000)

    def test_without_uncollectible_cap_is_not_used(self) -> None:
        self.assertEqual(_calc(V_SHOTOKU, **{"所得税_給与等の収入金額": 3_000_000, V_CAP: 0}), 2_020_000)


class PreTotalTest(unittest.TestCase):
    """income_totals の 所令180②一の合計額（回収不能額等の前。損益通算・繰越控除の後：所基通64−3）。"""

    def test_after_loss_offset_and_carryforward(self) -> None:
        base = {"所得税_給与等の収入金額": 3_000_000, V_UNCOLLECTIBLE: 300_000, "所得税_事業所得の金額": -1_950_000, "所得税_特別障害者に当たるか": False}
        self.assertEqual(_calc(V_TOTAL, **base), 70_000)  # 2,020,000 − 1,950,000（給与所得は回収不能額等の前の額）
        self.assertEqual(_calc(V_TOTAL, **base, **{"所得税_繰り越された純損失の金額": 50_000}), 20_000)  # 純損失の繰越控除の後
        self.assertEqual(_calc(V_TOTAL, **{**base, "所得税_事業所得の金額": -3_000_000}), 0)  # 赤字なら0（質疑応答事例：PS4-SH §1.3）

    def test_first_paragraph_variants(self) -> None:
        # 収入900万円：第1項 50,000 は「有するか」が真のときだけ（本人が特別障害者でない）
        base = {"所得税_給与等の収入金額": 9_000_000, V_UNCOLLECTIBLE: 1_000_000, "所得税_事業所得の金額": -7_000_000, "所得税_特別障害者に当たるか": False}
        self.assertEqual(_calc(V_TOTAL, **base), 50_000)
        self.assertEqual(_calc(V_TOTAL_WITH_1, **base), 0)
        self.assertEqual(_calc(V_TOTAL, **{**base, "所得税_特別障害者に当たるか": True}), 0)

    def test_zero_without_uncollectible(self) -> None:
        self.assertEqual(_calc(V_TOTAL, **{"所得税_給与等の収入金額": 3_000_000}), 0)


class StageTest(unittest.TestCase):
    def _run(self, u: int, diff: int, t0: int, t1: int, has: bool | None = None) -> Any:
        base = YearContext(make_ir([person("p")], []), 2026, ("p",))
        values = {(V_UNCOLLECTIBLE, "p"): StageValue(V_UNCOLLECTIBLE, "p", u, facts=("s-1",)), (V_DIFF, "p"): StageValue(V_DIFF, "p", diff),
                  (V_TOTAL, "p"): StageValue(V_TOTAL, "p", t0), (V_TOTAL_WITH_1, "p"): StageValue(V_TOTAL_WITH_1, "p", t1)}  # fmt: skip
        late = None if has is None else {(V_HAS, "p"): StageValue(V_HAS, "p", has, facts=("rel-1",))}
        return run(StageContext(base, STAGE, values, late)).inputs

    def test_no_uncollectible_writes_zero_without_uses(self) -> None:
        out = self._run(0, 0, 0, 0)
        self.assertEqual((out.values[(V_CAP, "p")].value, out.values[(V_CAP, "p")].uses), (0, ()))

    def test_copies_the_first_item(self) -> None:
        out = self._run(300_000, 210_000, 70_000, 70_000)
        self.assertEqual(out.values[(V_CAP, "p")].value, 70_000)
        self.assertEqual(out.exclusions, [])

    def test_first_paragraph_changes_result_is_excluded(self) -> None:
        # 900万円の例：二号 1,000,000（G(900万)−G(800万)）、一号は第1項の「有するか」で 50,000 か 0 → 段の順序で決められない（c-限界）
        out = self._run(1_000_000, 1_000_000, 50_000, 0)
        self.assertEqual([e.reason.reason for e in out.exclusions], [ORDER_LIMIT_REASON])
        # 二号がどちらの一号よりも低ければ、第1項によらず決まる
        self.assertEqual(self._run(1_000_000, 10_000, 50_000, 20_000).exclusions, [])

    def test_first_paragraph_from_late_read(self) -> None:
        # KY-10（段の late_reads の不動点の繰り返し）：最後の計算の「有するか」が渡されれば、その値の側の一号を上限にする
        has = self._run(1_000_000, 1_000_000, 50_000, 0, has=True)
        self.assertEqual((has.values[(V_CAP, "p")].value, has.exclusions), (0, []))
        self.assertIn(V_HAS, [u.variable for u in has.values[(V_CAP, "p")].uses])  # 「有するか」の由来を伝える
        self.assertEqual(self._run(1_000_000, 1_000_000, 50_000, 0, has=False).values[(V_CAP, "p")].value, 50_000)
        self.assertEqual(STAGE.late_reads, (V_HAS,))


class InputsTest(unittest.TestCase):
    def _ctx(self, recs: list[dict[str, Any]]) -> YearContext:
        return YearContext(make_ir([person("p-1", "1980-01-01")], recs), 2026, ("p-1",))

    def test_income_is_not_reduced(self) -> None:
        # 給与等の収入金額は変えず、回収不能額等を別の入力にする（法64①は所得の金額の計算の特例）
        pay = _pay(unpaid=True, amounts={"uncollectible_amount": 300_000})
        out = build_inputs(self._ctx([pay]))
        self.assertEqual((out.values[(V_INCOME, "p-1")].value, out.values[(V_UNCOLLECTIBLE, "p-1")].value), (3_000_000, 300_000))
        self.assertEqual(out.exclusions, [])

    def test_input_errors(self) -> None:
        # 未払でない支払に書いた・総支給額を超える：入力の矛盾（c-入力）。損失を生じうる所得の記録があっても対象外にしない
        paid = _pay(amounts={"uncollectible_amount": 1})
        self.assertIsNotNone(_uncollectible(self._ctx([paid]), "p-1", [paid]).reason)
        over = _pay(unpaid=True, amounts={"uncollectible_amount": 3_000_001})
        self.assertIsNotNone(_uncollectible(self._ctx([over]), "p-1", [over]).reason)
        pay = _pay(unpaid=True, amounts={"uncollectible_amount": 300_000})
        biz = {"id": "b-1", "kind": "business", "roles": {"owner": "p-1"}, "when": {"from_on": "2020-01-01"}, "attributes": {}}
        self.assertIsNone(_uncollectible(self._ctx([pay, biz]), "p-1", [pay]).reason)
        out = build_inputs(self._ctx([paid]))
        self.assertEqual({e.variable for e in out.exclusions}, {V_UNCOLLECTIBLE})


if __name__ == "__main__":
    unittest.main()

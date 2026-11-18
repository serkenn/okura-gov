"""tax の 選択.還付申告（VOC C-13。2026-11-12：rules/tax/README.md TX-27）。段の関数と式を直接呼ぶ（上流の値は入力で与える）。

根拠：所得税法第122条第1項（還付等を受けるための申告書を提出することができる）・所得税基本通達121−1
（docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md §4.2・§5.3）。
"""

from __future__ import annotations

import unittest

from openfisca_core.simulation_builder import SimulationBuilder

from okura_core.registry import Decided, StageContext, StageValue, YearContext
from okura_core.rules.tax import refund

from .support import make_ir, person, system


def _ctx(filed: bool = False) -> YearContext:
    docs = []
    if filed:
        docs.append({"id": "f1", "kind": "filed_document", "roles": {"filer": "b"}, "when": {"on": "2027-02-20"},
                     "attributes": {"document_type": "final_return", "recipient": "tax_office", "tax_year": 2026}})
    ir = make_ir([person("a"), person("b"), person("c")], [], filed_documents=docs)
    decided = {(refund.K_REFUND, refund.refund_key(p)): Decided(v, ids, frozenset(), False)
               for p, v, ids in (("a", True, ("c-a",)), ("b", False, ()), ("c", True, ("c-c",)))}
    return YearContext(ir, 2026, ("a", "b", "c"), decided)


def _run(ctx: YearContext, can: dict[str, bool]) -> dict[str, tuple[bool, tuple[str, ...]]]:
    values = {(refund.R_CAN_REFUND, p): StageValue(refund.R_CAN_REFUND, p, v) for p, v in can.items()}
    out = refund.run_refund(StageContext(ctx, refund.STAGE, values))
    return {k[1]: (iv.value, tuple(iv.record_ids)) for k, iv in out.inputs.values.items()}


class TestRefundChoice(unittest.TestCase):
    def test_choice_read_only_when_refund_possible(self) -> None:
        # 還付申告ができない人（c）は選択を読まず偽。できる人は選択の値（a は提出、b は未入力の候補の偽）
        got = _run(_ctx(), {"a": True, "b": True, "c": False})
        self.assertEqual(got, {"a": (True, ("c-a",)), "b": (False, ()), "c": (False, ())})

    def test_filed_return_counts_as_filing(self) -> None:
        # 通達121−1：その年分の確定申告書を出していれば、選択を読まずに提出したとする
        self.assertEqual(_run(_ctx(filed=True), {"a": False, "b": True, "c": False})["b"], (True, ("f1",)))

    def test_slots_are_lazy(self) -> None:
        slots = list(refund.refund_slots(_ctx()))
        self.assertEqual([(s.key, s.lazy) for s in slots], [("a", True), ("b", True), ("c", True)])
        self.assertEqual([c.value for c in slots[0].candidates], [False, True])

    def test_formula(self) -> None:
        for can, chose, expected in ((True, True, True), (True, False, False), (False, True, False)):
            s = SimulationBuilder().build_from_entities(
                system(), {"人物一覧": {"p": {"所得税_還付申告ができるか": {"2026": can}, "所得税_還付申告の選択": {"2026": chose}}}}
            )
            self.assertEqual(bool(s.calculate("所得税_還付を受けるための申告書を提出するか", "2026")[0]), expected)


if __name__ == "__main__":
    unittest.main()

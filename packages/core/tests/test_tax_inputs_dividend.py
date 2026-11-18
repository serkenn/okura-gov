"""tax の入力：配当等の源泉徴収税額と、支払ごとの 選択.株式等の申告（措法8の5④。2026-11-13）。

作成コーナーとの照合 B01 で、配当等の支払ごとの選択（subject.record_id）を income_kinds は読むのに tax は読まず、
源泉徴収税額が人の1か所の候補で分かれていた。支払ごとの選択はその支払には人の1か所より優先する。ユニットテストだけ（D24）。
"""
from __future__ import annotations

import unittest
from typing import Any

from okura_core.registry import Decided, YearContext
from okura_core.rules.tax.inputs import K_ORDER, V_WITHHOLDING, build_inputs

from .support import make_ir, person


def dividend(rid: str, withholding: int) -> dict[str, Any]:
    return {
        "id": rid, "kind": "dividend", "roles": {"recipient": "p"}, "when": {"on": "2025-06-20"},
        "amounts": {"gross": 200_000, "withholding_tax": withholding},
        "attributes": {"security_class": "listed_stock", "account_type": "other_account", "distribution_type": "surplus_dividend"},
    }


def choice(cid: str, rid: str, declare: bool) -> dict[str, Any]:
    return {
        "id": cid, "kind": "選択.株式等の申告", "chosen_by": "p", "chosen_at": "2026-02-01T09:00:00+09:00",
        "subject": {"person": "p", "record_id": rid}, "when": {"tax_year": 2025},
        "value": {"target": "dividend", "declare": declare, **({"taxation": "aggregate"} if declare else {})},
    }


def ctx(facts: list, choices: list) -> YearContext:
    # 人の1か所（"p:配当"）は決めない（decided に入れない）：支払ごとの選択だけで決まることを確かめる
    decided = {(K_ORDER, "p"): Decided("dividends_first", (), frozenset(), open=False)}  # 所得控除の順序（この確かめには関係しない）
    return YearContext(make_ir([person("p")], facts, choices=choices), 2025, ("p",), decided)


class TestPerPaymentDividendChoice(unittest.TestCase):
    def test_declared_payment_is_counted_without_the_person_level_choice(self) -> None:
        out = build_inputs(ctx([dividend("d1", 30_630)], [choice("c1", "d1", True)]))
        v = out.values[(V_WITHHOLDING, "p")]
        self.assertEqual(v.value, 30_630)
        self.assertIn("c1", v.record_ids)
        self.assertEqual([e for e in out.exclusions if V_WITHHOLDING in str(e)], [])

    def test_payment_not_declared_is_not_counted(self) -> None:
        out = build_inputs(ctx([dividend("d1", 30_630), dividend("d2", 15_315)], [choice("c1", "d1", True), choice("c2", "d2", False)]))
        self.assertEqual(out.values[(V_WITHHOLDING, "p")].value, 30_630)


if __name__ == "__main__":
    unittest.main()

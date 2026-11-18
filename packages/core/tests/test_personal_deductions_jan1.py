"""personal_deductions の住民税への窓口（jan1.py。2026-11-12、juminzei JM-03）：翌年の1月1日の障害者・婚姻の現況。テストのデータは架空の家庭。"""

from __future__ import annotations

import unittest

from okura_core.registry import ModuleInputs, YearContext, YearWindow
from okura_core.rules.personal_deductions import jan1

from .support import make_ir, person, system


def _ctx(facts: list, relations: list) -> YearContext:
    ir = make_ir([person("a", "1960-01-01"), person("b", "1960-01-01")], facts, relations=relations)
    return YearContext(ir, 2026, ("a", "b"), {}, window=YearWindow(parameters_at=lambda s: system().parameters(s)))


class TestJan1(unittest.TestCase):
    def test_disability_and_marriage_change_on_jan1(self) -> None:
        cert = {"id": "d1", "kind": "disability_basis", "roles": {"person": "a"}, "when": {"from_on": "2027-01-01"},
                "attributes": {"basis": "physical_disability_certificate", "grade": 3}}
        marriage = {"id": "m1", "kind": "marriage", "roles": {"spouse_a": "a", "spouse_b": "b"}, "when": {"from_on": "2027-01-01"}}
        out = ModuleInputs()
        jan1.write(_ctx([cert], [marriage]), out, lambda p, a, d: [])
        v = {k: iv.value for k, iv in out.values.items()}
        self.assertTrue(v[(jan1.V_JAN1_DISABLED, "a")])
        self.assertFalse(v[(jan1.V_JAN1_DISABLED, "b")])
        self.assertTrue(v[(jan1.V_JAN1_MARITAL_CHANGED, "a")])
        self.assertTrue(v[(jan1.V_JAN1_MARRIED, "a")])


if __name__ == "__main__":
    unittest.main()

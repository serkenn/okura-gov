"""事業専従者控除額のみなし給与（所得税法第57条第4項）を給与等の収入金額に足すことのテスト（kyuyo の build_inputs。上流はスタブ）。

期待値の出典：docs/public-sources/20261109_round2b_fudosan-laws-and-nta.md §5.1（所法57④：専従者の給与所得に係る収入金額とみなす）。
テストのデータはすべて架空。
"""

from __future__ import annotations

import unittest

from okura_core.registry import StageValue, YearContext, YearWindow
from okura_core.result import OutOfScopeCategory, OutOfScopeReason
from okura_core.rules.kyuyo.inputs import STAGE_DEEMED, V_DEEMED, V_FAMILY_OUT, V_INCOME, V_RETIRE_SALARY, build_inputs

from .support import make_ir, person


def _ctx(
    value: int, *, pending: bool = False, reasons: tuple[OutOfScopeReason, ...] = (), facts: list | None = None, family_out: int = 0, retire_salary: int = 0
) -> YearContext:
    ir = make_ir([person("p-1")], facts or [])
    sv = StageValue(V_DEEMED, "p-1", value, pending=pending, reasons=reasons)
    fo = StageValue(V_FAMILY_OUT, "p-1", family_out, pending=pending)
    rs = StageValue(V_RETIRE_SALARY, "p-1", retire_salary, pending=pending)
    values = {(V_DEEMED, "p-1"): sv, (V_FAMILY_OUT, "p-1"): fo, (V_RETIRE_SALARY, "p-1"): rs}
    return YearContext(ir, 2026, ("p-1",), window=YearWindow(stage_values={STAGE_DEEMED: values}))


class DeemedSalaryTest(unittest.TestCase):
    def test_deemed_amount_is_added(self) -> None:
        out = build_inputs(_ctx(500_000))
        v = out.values[(V_INCOME, "p-1")]
        self.assertEqual(v.value, 500_000)
        self.assertEqual(len(v.uses or ()), 1)
        self.assertTrue(any("第57条第4項" in (b.law or "") for b in v.basis))

    def test_pending_round_reads_nothing(self) -> None:
        out = build_inputs(_ctx(0, pending=True))
        self.assertEqual(out.values[(V_INCOME, "p-1")].value, 0)
        self.assertEqual(out.values[(V_INCOME, "p-1")].uses, ())

    def test_excluded_deemed_propagates_through_uses(self) -> None:
        r = OutOfScopeReason(OutOfScopeCategory.NOT_IMPLEMENTED, "事業主の事業所得が対象外", ("x",))
        v = build_inputs(_ctx(0, reasons=(r,))).values[(V_INCOME, "p-1")]
        self.assertEqual(v.uses[0].reasons, (r,))


    def test_family_business_salary_is_subtracted(self) -> None:
        # 所法56：生計を一にする親族の事業から受けた給与のうち青色事業専従者給与を超える部分（income_kinds の値）は給与等の収入金額から除く（fudosan §5.1）
        pay = {"id": "sp-1", "kind": "salary_payment", "roles": {"recipient": "p-1"}, "when": {"on": "2026-12-20"}, "amounts": {"gross": 1_000_000},
               "attributes": {"counterparty": "架空の父の商店", "due_on": "2026-12-20"}}
        v = build_inputs(_ctx(0, facts=[pay], family_out=400_000)).values[(V_INCOME, "p-1")]
        self.assertEqual(v.value, 600_000)
        self.assertTrue(any("第56条" in (b.law or "") for b in v.basis))

    def test_retirement_payment_judged_salary_is_added(self) -> None:
        # IK-25：判断.退職の性質 で退職手当等に当たらず給与（所基通30−1：docs/public-sources/20261109_round2b_taishoku-laws-and-guidance.md §1.2）とした支払
        # （income_kinds の値）は給与等の収入金額に足す
        v = build_inputs(_ctx(0, retire_salary=1_000_000)).values[(V_INCOME, "p-1")]
        self.assertEqual(v.value, 1_000_000)
        self.assertEqual(len(v.uses or ()), 1)
        self.assertTrue(any("30−1" in (b.law or "") for b in v.basis))

if __name__ == "__main__":
    unittest.main()

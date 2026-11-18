"""規則モジュール other_deductions：医療費通知（medical_expense_notice）の前処理の境目（2026-11-12）。テストのデータは架空の家庭。

期待値の出典：令和7年分 確定申告の手引き「医療費控除の明細書」❶・❷（docs/public-sources/20261112_impl-research6_forms-iryohi-tsuchi.md §2〜§4）。
生計の判定日を通知の対象の期間の終わりの日とするのは法令の読み（同 §6、basis.MEDICAL_NOTICE_RULE）。
"""

from __future__ import annotations

import unittest
from typing import Any

from .support import make_ir, person
from .test_other_deductions_inputs import J_SEIKEI, V_MED, medical, parentage, open_slots, reasons, reimbursement, run, seikei, val

V_N_AMOUNT = "所得税_医療費通知に記載された医療費の額"
V_N_PAID = "所得税_医療費通知のその年中に実際に支払った医療費の額"
V_N_REIMB = "所得税_医療費通知の補塡される金額"


def notice(
    rid: str, payer: str, patient: str, amount: int, paid: int, reimbursed: int | None = None, *,
    from_on: str = "2025-01-01", to_on: str | None = "2025-12-31", year: int = 2025,
) -> dict[str, Any]:  # fmt: skip
    amounts: dict[str, Any] = {"notice_amount": amount, "paid_in_year": paid}
    if reimbursed is not None:
        amounts["reimbursed"] = reimbursed
    when: dict[str, Any] = {"from_on": from_on}
    if to_on:
        when["to_on"] = to_on
    return {
        "id": rid, "kind": "medical_expense_notice", "roles": {"payer": payer, "patient": patient}, "when": when,
        "amounts": amounts, "attributes": {"payment_year": year, "issuer": "架空の健康保険組合"},
    }  # fmt: skip


def family(facts: list[dict[str, Any]], judgments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return make_ir(
        [person("p-f", "1970-01-01"), person("p-c", "2005-04-01")], facts,
        relations=[parentage("r", "p-f", "p-c", "2005-04-01")], judgments=judgments or [],
    )  # fmt: skip


class TestMedicalNotice(unittest.TestCase):
    def test_reimbursed_over_paid_is_capped_at_paid(self) -> None:
        # 手引き ❶(3)：補塡はその給付の目的となった医療費を限度とし、ほかの医療費から差し引かない。㋑ 50,000 ＞ ㋐ 30,000 → 通知の分は 0、
        # 明細の 100,000 はそのまま（ほかから差し引くと 80,000 になる：反証の目印）。㋑の欄は限度を当てた 30,000
        ir = family([notice("n1", "p-f", "p-f", 40_000, 30_000, 50_000), medical("a", "p-f", "p-f", "2025-05-01", "2025-05-01", 100_000)])
        out = run(ir, 2025)
        self.assertEqual(val(out, V_MED, "p-f"), 100_000)
        self.assertEqual((val(out, V_N_AMOUNT, "p-f"), val(out, V_N_PAID, "p-f"), val(out, V_N_REIMB, "p-f")), (40_000, 30_000, 30_000))
        # ㋑ が ㋐ より 1 円少なければ 1 円が残る
        out = run(family([notice("n1", "p-f", "p-f", 40_000, 30_000, 29_999)]), 2025)
        self.assertEqual((val(out, V_MED, "p-f"), val(out, V_N_REIMB, "p-f")), (1, 29_999))
        self.assertEqual(out.exclusions, [])

    def test_patient_livelihood_is_judged_at_period_end(self) -> None:
        # 手引き ❶※2：生計を一にする親族の分に限る。判定日は通知の対象の期間の終わりの日（法令の読み）
        ir = family([notice("n1", "p-f", "p-c", 20_000, 20_000)])
        sid = f"{J_SEIKEI}:p-f:p-c@2025-12-31"
        self.assertIn(sid, open_slots(ir, 2025))
        yes, no = run(ir, 2025, {sid: True}), run(ir, 2025, {sid: False})
        self.assertEqual((val(yes, V_MED, "p-f"), val(yes, V_N_AMOUNT, "p-f")), (20_000, 20_000))
        self.assertEqual((val(no, V_MED, "p-f"), val(no, V_N_AMOUNT, "p-f"), val(no, V_N_PAID, "p-f")), (0, 0, 0))
        # 9月30日まで生計を一にし、10月から別：期間の終わり（12月31日）では生計を一にしないので数えない
        split = family([notice("n1", "p-f", "p-c", 20_000, 20_000)], [seikei("j1", "p-f", "p-c", "2025-01-01", "2025-09-30"), seikei("j2", "p-f", "p-c", "2025-10-01", "2025-12-31", value=False)])
        self.assertEqual(val(run(split, 2025), V_MED, "p-f"), 0)
        # 期間を9月30日で区切った記録なら数える
        part = family([notice("n1", "p-f", "p-c", 20_000, 20_000, to_on="2025-09-30")], [seikei("j1", "p-f", "p-c", "2025-01-01", "2025-09-30")])
        self.assertEqual(val(run(part, 2025), V_MED, "p-f"), 20_000)

    def test_payment_year_decides_the_year(self) -> None:
        ir = family([notice("n1", "p-f", "p-f", 20_000, 5_000, from_on="2024-11-01", to_on="2025-10-31", year=2025)])
        self.assertEqual(val(run(ir, 2024), V_MED, "p-f"), 0)
        self.assertEqual(val(run(ir, 2025), V_MED, "p-f"), 5_000)

    def test_linked_payment_is_not_counted_twice(self) -> None:
        # 手引き ❷：❶に記入したものは明細に記入しない。notice_id を書いた支払は明細から除く（30,000＋明細の 10,000。60,000 なら二重：反証の目印）
        facts = [
            notice("n1", "p-f", "p-f", 30_000, 30_000),
            medical("a", "p-f", "p-f", "2025-05-01", "2025-04-20", 30_000, notice_id="n1"),
            medical("b", "p-f", "p-f", "2025-06-01", "2025-06-01", 10_000),
        ]
        out = run(family(facts), 2025)
        self.assertEqual(val(out, V_MED, "p-f"), 40_000)
        self.assertEqual(out.exclusions, [])

    def test_contradictions_are_input_errors(self) -> None:
        cases = {
            # notice_id の通知と受診者が違う
            "支払者・受診者・年": [notice("n1", "p-f", "p-f", 30_000, 30_000), medical("a", "p-f", "p-c", "2025-05-01", "2025-05-01", 30_000, notice_id="n1")],
            # 通知に載った支払を対象にする補塡（通知の ㋑ と二重に差し引きうる）
            "二重に差し引かない": [
                notice("n1", "p-f", "p-f", 30_000, 30_000, 10_000),
                medical("a", "p-f", "p-f", "2025-05-01", "2025-05-01", 30_000, notice_id="n1"),
                reimbursement("u", "p-f", "2025-07-01", 10_000, ("a",), "high_cost_medical_care_benefit"),
            ],
            # ㋐ が通知に記載された医療費の額を超える
            "を超える": [notice("n1", "p-f", "p-f", 30_000, 30_001)],
        }
        for text, facts in cases.items():
            with self.subTest(text=text):
                out = run(family(facts), 2025)
                self.assertTrue(any(text in r for r in reasons(out, V_MED, "p-f")), reasons(out, V_MED, "p-f"))
        # ㋐ が通知の額と同じなら矛盾でない
        self.assertEqual(reasons(run(family([notice("n1", "p-f", "p-f", 30_000, 30_000)]), 2025), V_MED, "p-f"), [])


if __name__ == "__main__":
    unittest.main()

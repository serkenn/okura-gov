"""住民税の雑損失の繰越控除（rules/juminzei：calc.jumin_casualty_carryforward・inputs._casualty_carry。README JM-32）のユニットテスト。

期待値：docs/inferences/20261112_impl-research5_juminzei-zasson-cases.md（式は docs/public-sources/20261112_impl-research5_juminzei-zasson-and-46-5.md §1：
地方税法第313条第9項・第317条の3、同施行令第48条の3第1項）。テストのデータは架空。
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any

from okura_core.registry import ModuleInputs
from okura_core.rules.juminzei import inputs as ji
from okura_core.rules.juminzei.calc import jumin_casualty_carryforward as carry


class CarryforwardTest(unittest.TestCase):
    def test_same_as_income_tax_without_separate_retirement(self) -> None:
        # 総所得 300,000・退職 100,000、雑損失 800,000 → 400,000 を控除（所得税の計算例と同じ：income_totals calc.apply_carryforwards）
        r = carry(400_000, 100_000, 0, 0, False, 0, 0, 800_000)
        self.assertEqual((r.deducted, r.total, r.retirement), (400_000, 0, 0))

    def test_separate_retirement_is_not_a_base(self) -> None:
        # 分離課税に係る退職所得は前年の所得に入らない：総所得 300,000 だけから控除し、500,000 が残る（所得税は 400,000 を控除）
        r = carry(300_000, 0, 0, 0, False, 0, 0, 800_000)
        self.assertEqual((r.deducted, r.total), (300_000, 0))

    def test_listed_after_total(self) -> None:
        # 総所得 0・上場配当 1,000,000・上場譲渡 1,000,000、雑損失 1,500,000 → 配当 0・譲渡 500,000（所得税の順の読み）
        r = carry(2_000_000, 0, 1_000_000, 1_000_000, False, 0, 0, 1_500_000)
        self.assertEqual((r.total, r.dividend, r.gain), (0, 0, 500_000))

    def test_net_loss_first(self) -> None:
        # 純損失 1,000,000 が総所得 600,000 と退職 200,000 を使い切る：雑損失は控除できない（施行令第48条の3第1項第2号イ・ハ・ホ）
        r = carry(800_000, 200_000, 0, 0, False, 0, 1_000_000, 300_000)
        self.assertEqual((r.deducted, r.total, r.retirement), (0, 0, 0))
        # 純損失 500,000：総所得の残り 100,000、次に退職 200,000 から雑損失 300,000
        r = carry(800_000, 200_000, 0, 0, False, 0, 500_000, 300_000)
        self.assertEqual((r.deducted, r.total, r.retirement), (300_000, 0, 0))


def _doc(rid: str, fiscal: int | None, origin: int | None, amount: int, doc: str = "resident_tax_return", tax_year: int | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"item": ji.CASUALTY_ITEM, "amount": amount}
    if origin is not None:
        item["origin_tax_year"] = origin
    attrs: dict[str, Any] = {"document_type": doc, "reported_amounts": [item]}
    if fiscal is not None:
        attrs["fiscal_year"] = fiscal
    if tax_year is not None:
        attrs["tax_year"] = tax_year
    return {"id": rid, "kind": "filed_document", "roles": {"filer": "p"}, "attributes": attrs}


def _inputs(docs: list[dict[str, Any]], fiscal: int = 2027) -> ModuleInputs:
    ctx = SimpleNamespace(year=fiscal - 1, records=lambda kind: docs if kind == "filed_document" else [])
    out = ModuleInputs()
    ji._casualty_carry(ctx, out, ji._Writer(out, "p"), "p", fiscal)  # type: ignore[arg-type]
    return out


class RecordTest(unittest.TestCase):
    def test_previous_fiscal_year_record(self) -> None:
        # 令和9年度分（前年 2026）：令和8年度の記録の 2024 年・2025 年の損失（前年前3年内）。2024 年の損失は令和7年度・令和8年度の申告書が要る
        docs = [_doc("r8", 2026, 2025, 300_000), _doc("r8b", 2026, 2024, 100_000), _doc("r7", 2025, None, 0)]
        docs[2]["attributes"]["reported_amounts"] = []
        out = _inputs(docs)
        self.assertEqual(out.values[(ji.V_CASUALTY_CARRIED, "p")].value, 400_000)
        self.assertTrue(out.values[(ji.V_CASUALTY_RECORDED, "p")].value)
        self.assertEqual(out.exclusions, [])

    def test_missing_filing_breaks_the_carry(self) -> None:
        # 2023 年の損失：令和6年度〜令和8年度の申告書が要るが、令和6年度・令和7年度の記録がない（第313条第9項：連続して提出しているときに限る）
        out = _inputs([_doc("r8", 2026, 2023, 300_000)])
        self.assertEqual(out.values[(ji.V_CASUALTY_CARRIED, "p")].value, 0)
        self.assertEqual(len(out.exclusions), 1)
        # 所得税の確定申告書は住民税の申告書とみなす（第317条の3）
        docs = [_doc("r8", 2026, 2023, 300_000), _doc("f23", None, None, 0, "final_return", tax_year=2023), _doc("f24", None, None, 0, "final_return", tax_year=2024)]
        self.assertEqual(_inputs(docs).values[(ji.V_CASUALTY_CARRIED, "p")].value, 300_000)


if __name__ == "__main__":
    unittest.main()

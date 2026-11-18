"""income_kinds の申告書の欄の材料の式の境目（breakdown.py の売上原価・forms_items.py。IK-108・IK-111）。上流の値は入力で与える。テストのデータは架空。"""

from __future__ import annotations

import unittest
from typing import Any

from openfisca_core.simulation_builder import SimulationBuilder

from ...support import system


def calc(variable: str, year: int, person: dict[str, Any]) -> Any:
    data = {name: {str(year): value} for name, value in person.items()}
    sim = SimulationBuilder().build_from_entities(system(), {"人物一覧": {"p": data}})
    return sim.calculate(variable, str(year)).tolist()[0]


class TestCostOfSalesFormulas(unittest.TestCase):
    def test_difference_and_other_expenses(self) -> None:
        # 総収入金額 3,000,000、必要経費 1,540,000（仕入 1,000,000＋期首－期末 40,000＋その他 500,000）、売上原価 1,040,000、減価償却費 60,000
        p = {
            "所得税_事業所得の総収入金額": 3_000_000, "所得税_事業所得の必要経費": 1_540_000, "所得税_事業所得の売上原価": 1_040_000,
            "所得税_事業所得の減価償却費": 60_000,
        }  # fmt: skip
        self.assertEqual(calc("所得税_事業所得の差引金額", 2025, p), 1_960_000)  # 収支内訳書⑩＝④－⑨
        self.assertEqual(calc("所得税_事業所得の売上原価以外の経費の計", 2025, p), 560_000)  # ⑱＝⑪〜⑯の計＋⑰（売上原価を除く）


class TestSpecialProvisionArticle(unittest.TestCase):
    """第二表 特例適用条文等：家内労働者等の特例（措法27）を当てたときだけ（docs/public-sources/20261112_impl-research6_forms-tebiki.md §1）。"""

    def test_home_worker_special_applied_or_not(self) -> None:
        base = {"所得税_家内労働者等か": True, "所得税_事業所得の総収入金額": 1_000_000}
        # 令和7年分の特例の額は65万円（パラメータ 所得税.家内労働者等の必要経費の特例.額）。必要経費がそれに満たなければ当てる、以上なら当てない
        self.assertEqual(calc("所得税_第二表の特例適用条文等", 2025, {**base, "所得税_事業所得の必要経費": 649_999}), "措法27")
        self.assertEqual(calc("所得税_第二表の特例適用条文等", 2025, {**base, "所得税_事業所得の必要経費": 650_000}), "なし")
        self.assertEqual(calc("所得税_第二表の特例適用条文等", 2025, {"所得税_事業所得の必要経費": 100_000}), "なし")


if __name__ == "__main__":
    unittest.main()

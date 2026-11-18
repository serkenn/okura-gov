"""hifuyosha の式（OpenFisca の変数）のユニットテスト。事実の層の入力はスタブとして与える。出典は各テストのコメントの docs の節。データは架空。"""

from __future__ import annotations

import unittest
from typing import Any

from openfisca_core.simulation_builder import SimulationBuilder

from ...support import system


def calc(variable: str, on: str, people: dict[str, dict[str, Any]], *, insured: str | None = None, deps: tuple[str, ...] = ()) -> list[Any]:
    """判定日 on の単位の situation（その年の期間）で変数を計算する。insured・deps を渡せば健康保険のグループを組む。"""
    year = on[:4]
    data = {p: {k: {year: v} for k, v in {"健保_判定日": on, **vals}.items()} for p, vals in people.items()}
    situation: dict[str, Any] = {"人物一覧": data}
    if insured is not None:
        others = [p for p in people if p != insured and p not in deps]
        situation["健康保険一覧"] = {"g": {"被保険者一覧": [insured], "被扶養者一覧": list(deps)}}
        situation["健康保険一覧"].update({f"solo-{p}": {"対象外一覧": [p]} for p in others})
    sim = SimulationBuilder().build_from_entities(system(), situation)
    return sim.calculate(variable, year).tolist()


class TestBase(unittest.TestCase):
    """収入の基準額：判定日で版を選ぶ（SH §1.2：令和7年10月1日から）。年齢は判定日の属する年の12月31日現在（PSK §5.5）。"""

    def test_young_switch_on_judgment_date(self) -> None:
        for scheme in ("健康保険", "国家公務員共済", "地方公務員共済", "私学共済"):
            p = {"健保_判定日の年齢": 19, "健保_判定日の属する年の12月31日の年齢": 20, "健保_被保険者の制度": scheme}
            with self.subTest(scheme=scheme):
                self.assertEqual(calc("健保_収入の基準額", "2025-09-30", {"c": p}), [1_300_000])
                self.assertEqual(calc("健保_収入の基準額", "2025-10-01", {"c": p}), [1_500_000])

    def test_categories(self) -> None:
        on = "2026-06-01"
        young = {"健保_判定日の年齢": 22, "健保_判定日の属する年の12月31日の年齢": 22, "健保_被保険者の制度": "健康保険"}
        self.assertEqual(calc("健保_収入の基準額", on, {"c": young}), [1_500_000])
        self.assertEqual(calc("健保_収入の基準額", on, {"c": {**young, "健保_判定日の属する年の12月31日の年齢": 23}}), [1_300_000])
        self.assertEqual(calc("健保_収入の基準額", on, {"c": {**young, "健保_被保険者の配偶者か": True}}), [1_300_000])
        disabled = "健保_障害を支給事由とする給付の受給要件に該当する程度の障害を有するか"
        self.assertEqual(calc("健保_収入の基準額", on, {"c": {**young, disabled: True}}), [1_800_000])
        self.assertEqual(calc("健保_収入の基準額", on, {"c": {**young, "健保_判定日の年齢": 60, "健保_判定日の属する年の12月31日の年齢": 60}}), [1_800_000])


class TestLivelihood(unittest.TestCase):
    """主として被保険者により生計を維持するか（SH §1.1）：同一の世帯は被保険者の年間収入の2分の1未満、別居は援助額より少ない。"""

    def run_(self, dep: dict[str, Any], insured_income: int = 2_400_000) -> bool:
        base = {"健保_被保険者の制度": "健康保険", "健保_被扶養者の範囲の親族か": "同居を要しない親族", "健保_国内居住の要件を満たすか": True}
        people = {"a": {"健保_被保険者本人の年間収入の見込み": insured_income}, "c": {**base, **dep}}
        out = calc("健保_被扶養者に当たるか", "2026-06-01", people, insured="a", deps=("c",))
        return out[1]

    def test_half_boundary(self) -> None:
        same = {"健保_同一の世帯に属するか": True}
        self.assertTrue(self.run_({**same, "健保_収入の見込みによる年間収入": 1_199_999}))
        self.assertFalse(self.run_({**same, "健保_収入の見込みによる年間収入": 1_200_000}))
        # ただし書（中心的役割）
        self.assertTrue(self.run_({**same, "健保_収入の見込みによる年間収入": 1_200_000, "健保_被保険者が生計維持の中心的役割を果たすか": True}))
        # 基準額（130万円）以上は不可
        self.assertFalse(self.run_({**same, "健保_収入の見込みによる年間収入": 1_300_000}, 10_000_000))

    def test_support_boundary(self) -> None:
        self.assertTrue(self.run_({"健保_収入の見込みによる年間収入": 999_999, "健保_援助の見込み額": 1_000_000}))
        self.assertFalse(self.run_({"健保_収入の見込みによる年間収入": 1_000_000, "健保_援助の見込み額": 1_000_000}))

    def test_contract_and_window_and_range(self) -> None:
        same = {"健保_同一の世帯に属するか": True, "健保_収入の見込みによる年間収入": 0}
        # 労働契約による判定を使うときはその額（SH §1.3）
        self.assertFalse(self.run_({**same, "健保_労働契約による判定を使うか": True, "健保_労働契約による年間収入": 1_300_000}, 10_000_000))
        # 実績の窓で基準額以上なら不可（KY §6.4）
        self.assertFalse(self.run_({**same, "健保_実績による年額": 1_300_000}, 10_000_000))
        # 同居を要する親族は同一の世帯でなければ当たらない（KY §1.1）
        self.assertFalse(self.run_({"健保_被扶養者の範囲の親族か": "同居を要する親族", "健保_援助の見込み額": 1_000_000}))
        # 被保険者等は当たらない（PSK §4.2）
        self.assertFalse(self.run_({**same, "健保_被扶養者から除かれる資格を有するか": True}))


class TestBoundaryDeclarations(unittest.TestCase):
    """境目の説明（D19。2026-11-12）：健保.被扶養者に当たるか は、収入の基準・同一の世帯の2分の1・別居の仕送りの下限の判定を直接の依存に持つ。"""

    def test_direct_boundaries(self) -> None:
        from okura_core.boundaries import declarations, undeclared
        from okura_core.evaluate import REGISTRY

        direct = set(REGISTRY.dictionary.concept("健保.被扶養者に当たるか").depends_on)
        got = {b.judgment: (b.compared, b.criterion, b.comparison) for b in declarations(REGISTRY) if b.judgment in direct}
        self.assertEqual(
            got,
            {
                "健保.年間収入が収入の基準額未満か": ("健保.年間収入", "健保.収入の基準額", "未満"),
                "健保.年間収入が同一の世帯の比較の基準額未満か": ("健保.年間収入", "健保.同一の世帯の比較の基準額", "未満"),
                "健保.援助による収入額が仕送りの基準の下限額以上か": ("健保.援助による収入額", "健保.仕送りの基準の下限額", "以上"),
            },
        )
        self.assertNotIn("被扶養者", undeclared(REGISTRY))


if __name__ == "__main__":
    unittest.main()

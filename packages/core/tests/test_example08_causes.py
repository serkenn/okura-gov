"""例 08（packages/ir/src/okura_ir/examples/valid/08_vocabulary_additions_2026_11_12.json）の評価を止めていた3つの原因の関数（2026-11-12）。

評価が通ることは手で確かめた（evaluate を通すテストは作らない：D24）。ここは原因の関数だけを直接呼ぶ。
1. personal_deductions の 判断.国内源泉所得の内訳 の1か所：ほかの年分の判断しかない人にも1か所を置き、候補を作れずに止まっていた。
2. juminzei の 住民税_賦課期日に住所を有する市町村：住所がない人の値が空の文字列で、結果の区分の値（空でない文字列）にできなかった。
3. income_kinds の受取側の給与の分かれ目の重なりの除去：Split（target が dict）を dict.fromkeys で hash しようとして止まっていた。
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from okura_core.result import Means, Split
from okura_core.rules.income_kinds.inputs import unique_splits
from okura_core.rules.juminzei import calc as jcalc
from okura_core.rules.juminzei.variables import _domiciled
from okura_core.rules.personal_deductions.allocation import domestic_source_slots


def _judgment(rid: str, year: int) -> dict:
    return {"id": rid, "kind": "判断.国内源泉所得の内訳", "subject": {"person": "p-s"}, "when": {"tax_year": year}, "value": {"non_domestic_income": 0}}


class DomesticSourceSlotTest(unittest.TestCase):
    def _slots(self, year: int, judgments: list[dict]) -> list:
        ctx = SimpleNamespace(year=year, persons=("p-s",), judgments=lambda kind: judgments)
        return list(domestic_source_slots(ctx))

    def test_only_years_with_a_judgment(self) -> None:
        self.assertEqual(self._slots(2025, [_judgment("j1", 2026)]), [])  # 2026年分の判断だけ：2025年分には1か所を置かない
        (slot,) = self._slots(2026, [_judgment("j1", 2026)])
        self.assertEqual(slot.key, "p-s")


class NoDomicileTest(unittest.TestCase):
    def test_no_domicile_value_is_nonempty(self) -> None:
        self.assertEqual(jcalc.NO_DOMICILE, "なし")
        self.assertEqual([jcalc.has_domicile(x) for x in ("990061", jcalc.NO_DOMICILE, "")], [True, False, False])
        self.assertEqual(list(_domiciled(["990061", jcalc.NO_DOMICILE, ""])), [True, False, False])


class UniqueSplitsTest(unittest.TestCase):
    def test_dict_target_dedup_keeps_order(self) -> None:
        a = Split("読み:所法56:a", Means.PRIMARY_SOURCE, {"payer": "p", "record": "r1"}, ("当てる", "当てない"), True)
        b = Split("事実:b", Means.FACT, {"person": "q"}, (), True)
        a2 = Split("読み:所法56:a", Means.PRIMARY_SOURCE, {"payer": "p", "record": "r1"}, ("当てる", "当てない"), True)
        self.assertEqual(unique_splits([a, b, a2]), (a, b))


if __name__ == "__main__":
    unittest.main()

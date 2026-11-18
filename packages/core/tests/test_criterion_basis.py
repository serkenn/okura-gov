"""境目の説明の基準の根拠（evaluate.criterion_basis）。2026-11-13：基準の額が注入データで決まるとき。ユニットテストだけ（D24）。

実際の家庭を通したとき、注入データ（級地）を渡すと、基準の根拠に「自治体の資料」の種類が付いて BasisEntry の検査で evaluate が例外で止まった。
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from okura_core.basis import BasisEntry, BasisType, SourceKind
from okura_core.evaluate import criterion_basis


class TestCriterionBasis(unittest.TestCase):
    def test_injection_source_kind_is_not_used_for_the_rule(self) -> None:
        injected = BasisEntry(BasisType.INJECTION, "住民税.級地", SourceKind.MUNICIPAL_MATERIAL, ("https://example.invalid/kyuchi",), value="1級地")
        law = BasisEntry(BasisType.RULE, "地方税法施行令第46条の2", SourceKind.LAW, ("docs/public-sources/x.md#1",))
        cv = SimpleNamespace(basis=(injected, law), concept="住民税.均等割の非課税の基準の額", id="v:1")
        b = criterion_basis(cv, 450_000)
        self.assertIs(b.type, BasisType.RULE)
        self.assertIs(b.source_kind, SourceKind.LAW)
        self.assertEqual(b.value, 450_000)

    def test_only_injection_basis_falls_back_to_law(self) -> None:
        injected = BasisEntry(BasisType.INJECTION, "住民税.級地", SourceKind.MUNICIPAL_MATERIAL, ("https://example.invalid/kyuchi",), value="1級地")
        cv = SimpleNamespace(basis=(injected,), concept="住民税.均等割の非課税の基準の額", id="v:1")
        self.assertIs(criterion_basis(cv, 450_000).source_kind, SourceKind.LAW)


if __name__ == "__main__":
    unittest.main()

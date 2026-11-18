"""丸め（rounding.py）と金額・率（money.py）のテスト（D21 R5・D22 S3）。"""

from __future__ import annotations

import unittest
from fractions import Fraction

from okura_core import money, rounding
from okura_core.basis import BasisType, ReadingFlag, SourceKind
from okura_core.money import YenRange
from okura_core.result import Means


class TestFunctions(unittest.TestCase):
    def test_floor_ceil_half_up(self) -> None:
        cases = [
            # x, floor, ceil, half_up
            (Fraction(49_000_009, 10), 4_900_000, 4_900_001, 4_900_001),
            (Fraction(1, 2), 0, 1, 1),
            (Fraction(-1, 2), -1, 0, 0),
            (Fraction(-3, 2), -2, -1, -1),
            (Fraction(7, 3), 2, 3, 2),
            (5, 5, 5, 5),
        ]
        for x, f, c, h in cases:
            with self.subTest(x=x):
                self.assertEqual(rounding.floor_yen(x), f)
                self.assertEqual(rounding.ceil_yen(x), c)
                self.assertEqual(rounding.half_up_yen(x), h)

    def test_floor_to_unit(self) -> None:
        self.assertEqual(rounding.floor_to_unit(1_234_999, 1000), 1_234_000)
        self.assertEqual(rounding.floor_to_unit(Fraction(999, 1), 1000), 0)
        with self.assertRaises(ValueError):
            rounding.floor_to_unit(1, 0)

    def test_rejects_float_and_bool(self) -> None:
        for bad in (1.5, True, "1"):
            with self.subTest(bad=bad), self.assertRaises(TypeError):
                rounding.floor_yen(bad)  # type: ignore[arg-type]

    def test_exactness_where_float_fails(self) -> None:
        """float64 では 1500 × 0.29 の切捨てが 434 になる（docs/measurements/20261109_impl-prep_tools-openfisca-probe.md §6）。"""
        self.assertEqual(rounding.floor_yen(money.times_rate(1500, money.rate(29, 100))), 435)
        self.assertEqual(rounding.floor_yen(money.times_rate(3495273, money.rate(3, 10))), 1048581)


class TestNamedRule(unittest.TestCase):
    def test_kyuyo_rule_has_basis(self) -> None:
        r = rounding.KYUYO_SHOTOKU_660MAN_FLOOR
        self.assertEqual(r.apply(Fraction(48_900_004, 10)), 4_890_000)
        b = r.basis_entry()
        self.assertEqual(b.type, BasisType.ROUNDING)
        self.assertEqual(b.source_kind, SourceKind.LAW)
        self.assertIn(ReadingFlag.LEGAL_READING, b.flags)
        self.assertTrue(b.references)

    def test_rule_requires_known_function_and_references(self) -> None:
        with self.assertRaises(ValueError):
            rounding.RoundingRule("x", "x", "nope", SourceKind.LAW, ("docs/a.md",), "law")
        with self.assertRaises(ValueError):
            rounding.RoundingRule("x", "x", "floor", SourceKind.LAW, (), "law")


class TestUnfounded(unittest.TestCase):
    def test_amount_only_differs_gives_range_not_undetermined(self) -> None:
        out = rounding.evaluate_unfounded("試験の端数", lambda f: f(Fraction(10_001, 2)))
        self.assertFalse(out.agree)
        self.assertEqual(out.as_amount(), YenRange(5_000, 5_001))
        self.assertEqual(dict(out.values), {"floor": 5_000, "ceil": 5_001, "half_up": 5_001})
        b = out.basis_entry()
        self.assertIsNone(b.source_kind)
        self.assertEqual(b.detail["title"], "根拠なし（候補で評価）")

    def test_same_amount_in_all_candidates_is_exact(self) -> None:
        out = rounding.evaluate_unfounded("試験の端数", lambda f: f(Fraction(10_000, 2)))
        self.assertEqual(out.as_amount(), 5_000)

    def test_judgment_split_gives_undetermined(self) -> None:
        # 端数の候補で「5,000 以下か」が分かれる
        out = rounding.evaluate_unfounded("試験の端数", lambda f: f(Fraction(10_001, 2)) <= 5_000)
        value, und = out.as_judgment(split_id="u1", target={"person": "p-1"})
        self.assertIsNone(value)
        assert und is not None
        self.assertEqual(und.splits[0].means, Means.PRIMARY_SOURCE)
        self.assertEqual(und.splits[0].candidates, ("floor", "ceil", "half_up"))
        self.assertEqual([o.value for o in und.outcomes], [True, False, False])

    def test_judgment_same_is_determined(self) -> None:
        out = rounding.evaluate_unfounded("試験の端数", lambda f: f(Fraction(10_001, 2)) <= 6_000)
        self.assertEqual(out.as_judgment(split_id="u1", target={}), (True, None))


class TestMoney(unittest.TestCase):
    def test_rate_from_ir(self) -> None:
        self.assertEqual(money.rate_from_ir({"num": 3, "den": 10}), Fraction(3, 10))
        for bad in ({"num": 1.5, "den": 2}, {"num": 1, "den": 0}, {"num": 1}, {"num": True, "den": 2}):
            with self.subTest(bad=bad), self.assertRaises((TypeError, ValueError)):
                money.rate_from_ir(bad)

    def test_require_yen(self) -> None:
        self.assertEqual(money.require_yen(10), 10)
        for bad in (1.0, True, "1", None):
            with self.subTest(bad=bad), self.assertRaises(TypeError):
                money.require_yen(bad)

    def test_range(self) -> None:
        self.assertTrue(YenRange(3, 3).is_exact)
        with self.assertRaises(ValueError):
            YenRange(4, 3)
        self.assertEqual(YenRange.of([5, 2, 9]).to_dict(), {"type": "yen_range", "min": 2, "max": 9})


class TestSourceKind(unittest.TestCase):
    def test_order(self) -> None:
        S = SourceKind
        self.assertTrue(S.LAW.stronger_than(S.PUBLIC_NOTICE))
        self.assertTrue(S.PUBLIC_NOTICE.stronger_than(S.CIRCULAR))
        self.assertTrue(S.CIRCULAR.stronger_than(S.GUIDE_OR_FORM_NOTE))
        self.assertTrue(S.GUIDE_OR_FORM_NOTE.stronger_than(S.NTA_EXPLANATION))
        self.assertTrue(S.NTA_EXPLANATION.stronger_than(S.INSURER_GUIDANCE))
        self.assertTrue(S.INSURER_GUIDANCE.stronger_than(S.MUNICIPAL_MATERIAL))
        self.assertEqual(S.LAW.rank, S.CABINET_ORDER.rank)
        self.assertTrue(S.MINISTERIAL_ORDINANCE.is_statute())
        self.assertFalse(S.CIRCULAR.is_statute())
        from okura_core.basis import strongest

        self.assertEqual(strongest([S.NTA_EXPLANATION, S.CIRCULAR, S.INSURER_GUIDANCE]), S.CIRCULAR)

    def test_municipal_material_only_for_injection(self) -> None:
        from okura_core.basis import BasisEntry

        with self.assertRaises(ValueError):
            BasisEntry(BasisType.PARAMETER, "x", SourceKind.MUNICIPAL_MATERIAL, ("docs/a.md",))
        BasisEntry(BasisType.INJECTION, "x", SourceKind.MUNICIPAL_MATERIAL, ("https://example.invalid/",))


if __name__ == "__main__":
    unittest.main()

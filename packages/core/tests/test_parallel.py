"""候補の組のプロセスの並列（parallel.py。packages/core/README.md §5.4 の5回目）の仕組みのユニットテスト。

プロセスは起動しない（評価の全体を通すテストは作らない：AGENTS.md）。並列と直列で同じ結果になるための部品（組の分け方の順、
入力の番号の付け替え、ワーカーが返す最後の situation の入力の違いの比べ方、問いの workers）を直接呼んで確かめる。
"""

from __future__ import annotations

import importlib
import unittest

from okura_core.parallel import Dispatcher, _Remap, chunks
from okura_core.query import parse_query
from okura_core.registry import Exclusion, GroupInstance, InputValue
from okura_core.result import OutOfScopeCategory, OutOfScopeReason
from okura_core.situation import YearBuild

E = importlib.import_module("okura_core.evaluate")


def _query(**extra: object) -> dict[str, object]:
    return {
        "income_tax_years": [2026],
        "resident_tax_fiscal_years": [],
        "kokuho_fiscal_years": [],
        "dependent_judgment_dates": [],
        "scenarios": [],
        **extra,
    }


def _build(values: dict[tuple[str, str], object], parts: int = 2, excl: tuple[Exclusion, ...] = (), groups: dict | None = None) -> YearBuild:
    """入力の部分（モジュールごと）の形を持つ situation（build_year が付ける _input_parts と同じ形）。"""
    ivs = {k: InputValue(v) for k, v in values.items()}
    b = YearBuild({}, ("p", "q"), ivs, excl, groups or {})
    keys = sorted(ivs)
    split = [dict((k, ivs[k]) for k in keys[i::parts]) for i in range(parts)]
    b.__dict__["_input_parts"] = (tuple(split), {})
    return b


def _slim(b: YearBuild) -> YearBuild:
    """ワーカーが親に返す形（evaluate._pack）にしたもの。"""
    sim = E._Sim(b, None, {}, frozenset(), raws={})
    sim.__dict__["assembled"] = None
    return E._pack(sim, {})["build"]


class TestChunks(unittest.TestCase):
    def test_chunks_keep_order_and_cover_all(self) -> None:
        for n in (0, 1, 5, 31, 32, 33, 100):
            items = list(range(n))
            parts = chunks(items, 16)
            self.assertEqual([x for p in parts for x in p], items)  # 並びの順（結果を求めた順に入れる）
            self.assertLessEqual(len(parts), 32)
            self.assertTrue(all(parts))


class TestRemap(unittest.TestCase):
    def test_worker_bits_are_renumbered_to_parent_keys(self) -> None:
        parent = E._InputIndex()
        for k in [("a", "p"), ("b", "p"), ("c", "q")]:
            parent.of(k)
        worker = E._InputIndex()
        worker_keys = [("a", "p"), ("c", "q"), ("d", "p"), ("b", "p")]  # 2番目から親と違う並び。d は親にない
        for k in worker_keys:
            worker.of(k)
        rm = _Remap(parent)
        rm.absorb("w1", 0, worker_keys)
        for subset in ([("a", "p")], [("c", "q"), ("d", "p")], worker_keys, []):
            b = 0
            for k in subset:
                b |= worker.of(k)
            self.assertEqual(parent.to_set(rm.convert("w1", b)), frozenset(subset))

    def test_shared_raw_objects_are_converted_once(self) -> None:
        # ワーカーは前の組で集めた値（_Raw）を使い回すので、1つのまとまりの結果の複数の組が同じオブジェクトを持つ（pickle は共有を保つ）。
        # 2回付け替えると別の入力を指す（2026-11-12：並列の結果が直列と違った原因）
        parent = E._InputIndex()
        for k in [("x", "p"), ("y", "p")]:
            parent.of(k)
        worker = E._InputIndex()
        worker_keys = [("y", "p"), ("z", "q"), ("x", "p")]
        for k in worker_keys:
            worker.of(k)
        d = Dispatcher(2, ())
        d.attach(parent)
        d.remap.absorb("w", 0, worker_keys)
        shared = E._Raw(None, set(), set(), set(), [], [], False, worker.of(("x", "p")) | worker.of(("z", "q")), extra=worker.of(("y", "p")))
        packed = [{"raws": {("v", "p"): shared}, "check_bits": {}, "attribution": None} for _ in range(3)]
        done: set[int] = set()
        for p in packed:
            d._convert("w", p, done)
        self.assertEqual(parent.to_set(shared.inputs), frozenset({("x", "p"), ("z", "q")}))
        self.assertEqual(parent.to_set(shared.extra), frozenset({("y", "p")}))

    def test_same_prefix_is_not_converted(self) -> None:
        parent = E._InputIndex()
        keys = [("a", "p"), ("b", "p")]
        for k in keys:
            parent.of(k)
        rm = _Remap(parent)
        rm.absorb("w", 0, keys)
        self.assertEqual(rm.ident["w"], 2)
        self.assertEqual(rm.convert("w", 0b11), 0b11)
        with self.assertRaises(AssertionError):
            rm.absorb("w", 5, [])  # 送った番号の続きが合わない


class TestPackedBuildDiff(unittest.TestCase):
    """ワーカーが返す最後の situation（入力の値・対象外・グループだけ）でも、組どうしの入力の違い（_diff_bits）は親の situation と同じ。"""

    def test_diff_bits_same_for_packed_builds(self) -> None:
        reason = OutOfScopeReason(OutOfScopeCategory.NOT_IMPLEMENTED, "テスト")
        g1 = {"法律婚": (GroupInstance("m1", {"配偶者": ("p", "q")}),)}
        g2 = {"法律婚": (GroupInstance("m1", {"配偶者": ("p",)}), GroupInstance("m2", {"配偶者": ("q",)}))}
        base = {("v1", "p"): 1, ("v2", "p"): True, ("v3", "q"): "x", ("v4", "q"): 10}
        cases = [
            (_build(base), _build(base)),
            (_build(base), _build({**base, ("v1", "p"): 2})),
            (_build(base), _build({**base, ("v2", "p"): 1})),  # True と 1 は型が違う
            (_build(base), _build({**base, ("v5", "p"): 0})),
            (_build(base), _build(base, excl=(Exclusion("q", reason, "v3"),))),
            (_build(base), _build(base, excl=(Exclusion("q", reason),))),
            (_build(base, groups=g1), _build(base, groups=g2)),
        ]
        for a, b in cases:
            ix = E._InputIndex()
            bits = E._Bits(ix)
            want = ix.to_set(E._diff_bits(a, b, ix, bits.person))
            ix2 = E._InputIndex()
            got = ix2.to_set(E._diff_bits(_slim(a), _slim(b), ix2, E._Bits(ix2).person))
            self.assertEqual(got, want)
            ix3 = E._InputIndex()
            mixed = ix3.to_set(E._diff_bits(a, _slim(b), ix3, E._Bits(ix3).person))  # 親の基準の組とワーカーの組
            self.assertEqual(mixed, want)
        self.assertEqual(want, frozenset({("group:法律婚", "p"), ("group:法律婚", "q")}))


class TestWorkersOption(unittest.TestCase):
    def test_workers_is_parsed_and_not_echoed(self) -> None:
        q, problems = parse_query(_query(workers=1))
        self.assertEqual(problems, [])
        assert q is not None
        self.assertEqual(q.workers, 1)
        self.assertNotIn("workers", q.to_dict())  # 結果の query に出さない（並列の数で結果が変わらない）
        q2, _ = parse_query(_query())
        assert q2 is not None
        self.assertIsNone(q2.workers)
        self.assertEqual(q.to_dict(), q2.to_dict())

    def test_invalid_workers(self) -> None:
        for bad in (0, -1, 1.5, "4", True, 10_000):
            with self.subTest(bad=bad):
                q, problems = parse_query(_query(workers=bad))
                self.assertIsNone(q)
                self.assertEqual([p.path for p in problems], ["$.workers"])

    def test_input_hash_ignores_workers(self) -> None:
        self.assertEqual(E.without_execution_options(_query(workers=8)), _query())
        self.assertEqual(E.canonical_sha256(E.without_execution_options(_query(workers=8))), E.canonical_sha256(_query()))


if __name__ == "__main__":
    unittest.main()

"""値ごとの候補の評価（2026-11-12 の4回目）の仕組み：作り手の出力が依存する分かれ目の決め方と、値ごとの組合せの分解。

関数を直接呼ぶユニットテスト（D24）。OpenFisca の計算と situation の組み立てはスタブにする。
- _producer_dependencies：作り手を、読んだ分かれ目の直積の全部の組で呼び、出力ごとに依存する分かれ目を正確に決める
  （2つの分かれ目が同時に変わるときだけ変わる出力、ある候補のときだけ読む分かれ目）。
- _resolve_dependencies：値ごとに依存する分かれ目の直積だけを評価し（関係のない分かれ目の組合せは計算しない）、2つの分かれ目が同時に
  効く値はその2つの直積の全部で評価して未確定にする。
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from okura_core.candidates import Candidate, Slot
from okura_core.evaluate import (
    _InputIndex,
    _merge_value,
    _producer_dependencies,
    _Raw,
    _resolve_dependencies,
    _Run,
    _Sim,
    _ValuePlan,
)
from okura_core.registry import InputValue, ModuleInputs, OutputSpec, StagePlan
from okura_core.result import Means, State
from okura_core.situation import YearBuild


def _slot(sid: str) -> Slot:
    return Slot(sid, Means.JUDGMENT, {"試験": sid}, (Candidate(False, "false"), Candidate(True, "true")))


SLOTS = {s.id: s for s in (_slot("A"), _slot("B"), _slot("C"))}
ORDER = {"A": 0, "B": 1, "C": 2}
#: 計算の後の検出を持たない登録（_resolve_dependencies が検出の対象外の候補を引く）
NO_CHECKS = SimpleNamespace(modules=(), variable_module={})


class ProducerDependenciesTest(unittest.TestCase):
    def test_joint_effect_and_conditional_read(self) -> None:
        def producer(comb):  # A と B は常に読む。C は A が真のときだけ読む
            a, b = comb["A"].value, comb["B"].value
            read = {"A", "B"}
            c = False
            if a:
                read.add("C")
                c = comb["C"].value if "C" in comb else False
            out = ModuleInputs()
            out.set("両方", "p", a and b)  # 2つが同時に真のときだけ変わる
            out.set("Aだけ", "p", a)
            out.set("定数", "p", 0)
            out.set("Aのとき C", "p", c)
            return out, read

        found = _producer_dependencies(producer, [SLOTS["A"], SLOTS["B"]], SLOTS, ORDER.__getitem__)
        assert found is not None
        self.assertEqual(found[("v", ("両方", "p"))], {"A", "B"})
        self.assertEqual(found[("v", ("Aだけ", "p"))], {"A"})
        self.assertNotIn(("v", ("定数", "p")), found)
        self.assertEqual(found[("v", ("Aのとき C", "p"))], {"A", "C"})  # A が真のときだけ読む C も、読んだら足して評価し直す

    def test_too_many_combinations_gives_none(self) -> None:
        def producer(comb):
            out = ModuleInputs()
            out.set("x", "p", 0)
            return out, {"A", "B", "C"}

        self.assertIsNone(_producer_dependencies(producer, [SLOTS["A"]], SLOTS, ORDER.__getitem__, limit=4))


class ResolveDependenciesTest(unittest.TestCase):
    """入力 kAB = A かつ B、kC = C。値 v1 は kAB だけ、v2 は kC だけを読み、v3 は入力を読まない。"""

    def setUp(self) -> None:
        self.index = _InputIndex()
        self.calls: list[tuple[tuple[str, str], ...]] = []

    def _run(self, a) -> _Sim:
        ix = self.index
        val = {sid: (a[sid].value if sid in a else False) for sid in SLOTS}
        inputs = {("kAB", "p"): InputValue(val["A"] and val["B"]), ("kC", "p"): InputValue(val["C"])}
        build = YearBuild({}, ("p",), inputs, (), {})
        raws = {
            ("v1", "p"): _Raw(inputs[("kAB", "p")].value, set(), set(), set(), [], [], False, ix.of(("v1", "p")) | ix.of(("kAB", "p"))),
            ("v2", "p"): _Raw(inputs[("kC", "p")].value, set(), set(), set(), [], [], False, ix.of(("v2", "p")) | ix.of(("kC", "p"))),
            ("v3", "p"): _Raw(7, set(), set(), set(), [], [], False, ix.of(("v3", "p"))),
        }
        sim = _Sim(build, None, {}, frozenset(), raws=raws, reads={})
        sim.__dict__["assembled"] = None
        sim.__dict__["builds"] = (a, ())
        return sim

    def test_each_value_is_evaluated_over_its_own_slots(self) -> None:
        runs: dict = {}
        new_runs: list = []
        default = {sid: "false" for sid in SLOTS}

        def canon(a):
            return tuple(sorted((sid, c.label) for sid, c in a.items() if c.label != default[sid]))

        def simulate(a, needed=None):
            key = canon(a)
            if key not in runs:
                self.calls.append(key)
                runs[key] = self._run(a)
                new_runs.append(key)
            return runs[key]

        def exact_deps(run, bit_of, person_bits, key_bits):
            # 作り手が A・B を読んで kAB を、C を読んで kC を書く（_producer_dependencies が出すのと同じ形）
            return {"A": bit_of(("kAB", "p")), "B": bit_of(("kAB", "p")), "C": bit_of(("kC", "p"))}

        def simulate_many(items):
            # 互いに独立な組の並び（evaluate の simulate_many と同じ形：並べた順に計算する）
            for a, needed in items:
                simulate(a, needed)

        simulate({})
        keys = [("v1", "p"), ("v2", "p"), ("v3", "p")]
        deps_of = {k: frozenset() for k in keys}
        over: dict = {}
        affected: dict = {}
        _resolve_dependencies(
            keys, deps_of, over, affected, runs, new_runs, simulate_many, SLOTS, ORDER, default,
            {}, {}, StagePlan(), NO_CHECKS, self.index, ("p",), exact_deps,  # type: ignore[arg-type]
        )
        self.assertEqual(deps_of[("v1", "p")], frozenset({"A", "B"}))
        self.assertEqual(deps_of[("v2", "p")], frozenset({"C"}))
        self.assertEqual(deps_of[("v3", "p")], frozenset())
        self.assertEqual(over, {})
        # A・B の直積（4組）と C の候補（基準と C だけ真）：A・B と C の組合せ（8組）は計算しない
        self.assertEqual(sorted(runs), sorted([(), (("A", "true"),), (("B", "true"),), (("A", "true"), ("B", "true")), (("C", "true"),)]))

        # v1 は A と B が同時に真のときだけ真：2つの分かれ目の直積の全部で評価し、未確定（2つとも結論を分ける）
        slots_v1 = [SLOTS["A"], SLOTS["B"]]
        combos = [{"A": x, "B": y} for x in SLOTS["A"].candidates for y in SLOTS["B"].candidates]
        plan = _ValuePlan(
            slots_v1,
            [_Run(c, runs[canon(c)].build, runs[canon(c)], raws=runs[canon(c)].raws, index=self.index) for c in combos],
            None,
            {s.id: affected.get(s.id, 0) for s in slots_v1},
        )
        v1 = _merge_value(OutputSpec("v1", "所得税.試験_v1", "真偽", False, False), "p", plan, 2026, index=self.index)
        self.assertIn(State.UNDETERMINED, v1.states)
        self.assertEqual([s.id for s in v1.undetermined.splits], ["A", "B"])
        self.assertEqual({tuple(sorted(o.conditions.items())): o.value for o in v1.undetermined.outcomes}[(("A", "true"), ("B", "true"))], True)

    def test_dependencies_over_the_limit_are_not_evaluated(self) -> None:
        slots = {f"S{i}": _slot(f"S{i}") for i in range(7)}  # 2の7乗 = 128 > 64
        order = {sid: i for i, sid in enumerate(slots)}
        default = {sid: "false" for sid in slots}
        runs: dict = {}
        new_runs: list = []
        ix = self.index

        def simulate(a, needed=None):
            key = tuple(sorted((sid, c.label) for sid, c in a.items() if c.label != "false"))
            if key not in runs:
                raw = _Raw(0, set(), set(), set(), [], [], False, ix.of(("v", "p")) | ix.of(("k", "p")))
                sim = _Sim(YearBuild({}, ("p",), {("k", "p"): InputValue(0)}, (), {}), None, {}, frozenset(), raws={("v", "p"): raw}, reads={})
                sim.__dict__["assembled"] = None
                runs[key] = sim
                new_runs.append(key)
            return runs[key]

        simulate({})
        deps_of = {("v", "p"): frozenset()}
        over: dict = {}
        _resolve_dependencies(
            [("v", "p")], deps_of, over, {}, runs, new_runs, simulate, slots, order, default, {}, {}, StagePlan(), NO_CHECKS, ix, ("p",),
            lambda run, bit_of, pb, kb: {sid: bit_of(("k", "p")) for sid in slots},  # type: ignore[arg-type]
        )
        self.assertEqual(over, {("v", "p"): 128})
        self.assertEqual(deps_of[("v", "p")], frozenset(slots))
        self.assertEqual(list(runs), [()])  # 基準の組だけ（上限を超える組合せは計算しない）


if __name__ == "__main__":
    unittest.main()

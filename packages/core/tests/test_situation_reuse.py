"""situation の使い回し（計算の速さのため。2026-11-12 の3回目。packages/core/README.md §5.4）の仕組みのユニットテスト。

使い回したときに、計算し直したときと同じ結果（同じオブジェクト）と副作用（読んだ記録）になること、読んだものが変われば
計算し直すことだけを確かめる。テストのデータは架空の人だけ。
"""

from __future__ import annotations

import unittest

from okura_core.registry import Decided, StageOutput, StageSpec, StageValue, YearContext, YearWindow
from okura_core.situation import StageState, _reuse, apply_stage

PERSONS = ("p-a", "p-b")
IR = {"persons": [{"id": p, "birth_on": "1990-01-01"} for p in PERSONS]}


def _ctx(decided: dict, stage_values: dict | None = None, reads: set | None = None) -> YearContext:
    window = YearWindow(stage_values=stage_values or {}, lazy_decisions={("判断.x", "k"): "slot-x"}, decision_reads=reads)
    return YearContext(IR, 2026, PERSONS, decided, window=window)


def _open(value: object) -> Decided:
    return Decided(value, (), frozenset(), open=True)


class ReuseTest(unittest.TestCase):
    def test_build_inputs_reading_stage_values_reused_only_for_the_same_objects(self) -> None:
        calls: list[int] = []

        def fn(ctx: YearContext) -> object:
            calls.append(1)
            ctx.decision("判断.x", "k")
            return ("result", ctx.stage_value("段", "v", "p-a").value)

        sv = StageValue("v", "p-a", 1)
        memo: dict = {}
        ctx1 = _ctx({("判断.x", "k"): _open(True)}, {"段": {("v", "p-a"): sv}})
        first = _reuse(memo, "key", ctx1, fn)
        ctx2 = _ctx({("判断.x", "k"): _open(True)}, {"段": {("v", "p-a"): sv}}, reads=set())
        again = _reuse(memo, "key", ctx2, fn)
        self.assertIs(first, again)
        self.assertEqual(len(calls), 1)
        # 使い回したときも、読んだ記録（段の値・読んだときだけ開く1か所）は計算したときと同じ
        self.assertEqual(ctx2.stage_reads, [sv])
        self.assertTrue(ctx2.stage_touched)
        self.assertEqual(ctx2._window.decision_reads, {"slot-x"})
        # 等しくても別のオブジェクトの段の値なら計算し直す（由来の重なりの扱いがオブジェクトに依存するので）
        ctx3 = _ctx({("判断.x", "k"): _open(True)}, {"段": {("v", "p-a"): StageValue("v", "p-a", 1)}})
        _reuse(memo, "key", ctx3, fn)
        self.assertEqual(len(calls), 2)
        # 判断が違えば計算し直す
        ctx4 = _ctx({("判断.x", "k"): _open(False)}, {"段": {("v", "p-a"): sv}})
        _reuse(memo, "key", ctx4, fn)
        self.assertEqual(len(calls), 3)

    def test_apply_stage_memo_returns_the_same_outputs_and_recomputes_on_other_decisions(self) -> None:
        calls: list[int] = []

        def run(sc) -> StageOutput:  # type: ignore[no-untyped-def]
            calls.append(1)
            flag = sc.decision("判断.x", "k").value
            out = StageOutput()
            for p in PERSONS:
                out.set("w", p, int(flag) + sc.value("v", p).value)
            return out

        stage = StageSpec(name="段", title="", reads=("v",), writes=("w",), run=run)
        values = {("v", p): StageValue("v", p, 10) for p in PERSONS}
        memo: dict = {}
        s1, s2 = StageState(), StageState()
        apply_stage(stage, _ctx({("判断.x", "k"): _open(True)}), values, s1, None, memo)
        reads: set = set()
        apply_stage(stage, _ctx({("判断.x", "k"): _open(True)}, reads=reads), values, s2, None, memo)
        self.assertEqual(len(calls), 1)
        self.assertEqual(reads, {"slot-x"})  # 読んだときだけ開く1か所を読んだ記録は、使い回しでも残す
        for k, iv in s1.inputs.items():
            self.assertIs(s2.inputs[k], iv)
        self.assertEqual(s1.inputs[("w", "p-a")].value, 11)
        s3 = StageState()
        apply_stage(stage, _ctx({("判断.x", "k"): _open(False)}), values, s3, None, memo)
        self.assertEqual(len(calls), 2)
        self.assertEqual(s3.inputs[("w", "p-a")].value, 10)
        # 段の値の表が別のオブジェクト（別の回の節）なら計算し直す
        apply_stage(stage, _ctx({("判断.x", "k"): _open(True)}), dict(values), StageState(), None, memo)
        self.assertEqual(len(calls), 3)


if __name__ == "__main__":
    unittest.main()

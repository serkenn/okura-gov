"""結果の出力の仕組み（2026-11-12）：根拠の一覧と番号の参照、シナリオの差、境目の形と宣言の一覧、欄の値の組み込み、
段の late_reads、Simulation の使い回し（evaluate._Engine）。どれも関数を直接呼ぶユニットテスト（上流の値はスタブ。D24）。"""

from __future__ import annotations

import datetime as _dt
import unittest
from types import SimpleNamespace

from okura_core.basis import BasisEntry, BasisType, SourceKind
from okura_core.boundaries import declarations, undeclared
from okura_core.evaluate import _Engine, _period, new_simulation
from okura_core.explain import trace_graph
from okura_core.forms import FormsRefusal, RefusalCategory
from okura_core.forms_output import form_concepts, forms_for
from okura_core.registry import InputValue, StageContext, StageSpec, StageValue, YearContext
from okura_core.result import (
    BasisTable,
    Boundary,
    Comparison,
    EvaluationResult,
    Flag,
    ResultValue,
    ScenarioResult,
    State,
    TimeKey,
    YenAmount,
    check_result_json,
    scenario_differences,
)
from okura_core.situation import YearBuild

from .support import make_ir, person, system

T = TimeKey("tax_year", 2025)


def _param(name: str, value: int, enforced_on: str = "2025-01-01") -> BasisEntry:
    return BasisEntry(
        BasisType.PARAMETER, name, SourceKind.LAW, ("docs/public-sources/x.md#1",), value=value, instant="2025-01-01",
        effective_from="2025-01-01", enforced_on=enforced_on, detail={"比較": "以下"},
    )  # fmt: skip


A = _param("所得税.甲", 1)
B = _param("所得税.乙", 2)


def rv(vid: str, value, states=(), *, basis=(A,), person="p-1", filing_item=False, filing_scope=False) -> ResultValue:
    return ResultValue(
        id=vid, concept=f"所得税.{vid}", variable=None, person=person, time=T, value=value, states=frozenset(states),
        basis=basis, filing_item=filing_item, filing_scope=filing_scope,
    )  # fmt: skip


def scenario(sid: str, values, boundaries=(), **kw) -> ScenarioResult:
    return ScenarioResult(sid, None, tuple(values), tuple(boundaries), (), (), (), **kw)


VERSIONS = {
    "okura_core": "0", "openfisca_core": "0", "numpy": "0", "python": "3", "ir_schema": "0", "result_schema": "1",
    "parameters_sha256": {}, "data_sha256": {}, "input_sha256": "f" * 64,
}  # fmt: skip
QUERY = {
    "income_tax_years": [2025], "filing_date": None, "resident_tax_fiscal_years": [], "kokuho_fiscal_years": [],
    "dependent_judgment_dates": [], "scenarios": [],
}  # fmt: skip


class BasisReferenceTest(unittest.TestCase):
    """根拠は結果の一覧 basis に1回だけ置き、値・境目からは番号で引く。"""

    def test_same_entry_has_one_index(self) -> None:
        table = BasisTable()
        copy_of_a = _param("所得税.甲", 1)  # 別のオブジェクトでも内容が同じなら同じ番号
        self.assertEqual([table.ref(A), table.ref(B), table.ref(A), table.ref(copy_of_a)], [0, 1, 0, 0])
        self.assertEqual([e["name"] for e in table.to_list()], ["所得税.甲", "所得税.乙"])

    def test_result_json_refers_by_index(self) -> None:
        values = (rv("v1", YenAmount(10), basis=(B,)), rv("v2", Flag(True), basis=(A, B)))
        b = Boundary(
            id="b1", concept="所得税.境目", person="p-1", time=T, judgment_value_id="v2", judgment=True, compared_value_id="v1",
            compared_concept="所得税.v1", current=10, criterion=A, criterion_value=10, comparison=Comparison.AT_MOST,
            crossing_value=11, difference=1, states=frozenset(),
        )  # fmt: skip
        d = EvaluationResult(VERSIONS, QUERY, (), (scenario("base", values, (b,)), scenario("s1", values[:1]))).to_dict()
        self.assertEqual(check_result_json(d), [])
        table = d["basis"]
        self.assertEqual(len(table), 2)  # シナリオをまたいで共有する
        v2 = d["scenarios"][0]["values"][1]
        self.assertEqual([table[i]["name"] for i in v2["basis"]], ["所得税.甲", "所得税.乙"])
        crit = d["scenarios"][0]["boundaries"][0]["criterion"]
        self.assertEqual((table[crit["basis"]]["name"], d["scenarios"][0]["boundaries"][0]["kind"]), ("所得税.甲", "上限"))
        self.assertEqual(d["scenarios"][1]["values"][0]["basis"], d["scenarios"][0]["values"][0]["basis"])


class ScenarioDifferenceTest(unittest.TestCase):
    """複数シナリオの一括評価：base との値の差（値・状態・片方にしかない値。根拠の違いは差にしない）。"""

    def test_differences(self) -> None:
        base = [rv("a", YenAmount(1)), rv("b", YenAmount(2)), rv("c", YenAmount(3)), rv("d", YenAmount(4))]
        other = [
            rv("a", YenAmount(1), basis=(B,)),  # 根拠だけ違う：差にしない
            rv("b", YenAmount(5)),
            rv("c", YenAmount(3), [State.FORECAST]),
            rv("e", YenAmount(6)),
        ]
        diffs = scenario_differences(base, other)
        self.assertEqual([(x.value_id, x.fields) for x in diffs], [("b", ("value",)), ("c", ("states",)), ("e", ("present",)), ("d", ("present",))])
        self.assertEqual(diffs[0].to_dict()["base"], {"value": {"type": "yen", "amount": 2}, "states": []})
        self.assertIsNone(diffs[2].to_dict()["base"])
        self.assertEqual(scenario_differences(base, base), ())


class BoundaryDeclarationTest(unittest.TestCase):
    """境目の宣言の一覧と、主要な判定に宣言がないものの検出（判定そのものか直接の依存に宣言があれば宣言あり）。"""

    def _reg(self):
        concepts = {
            "所得税.扶養親族に当たるか": SimpleNamespace(id="所得税.扶養親族に当たるか", module="m", declared_targets=lambda: ("所得税.要件",)),
            "所得税.要件": SimpleNamespace(id="所得税.要件", module="m", declared_targets=lambda: ()),
            "所得税.合計所得金額": SimpleNamespace(id="所得税.合計所得金額", module="t", declared_targets=lambda: ()),
            "所得税.勤労学生に当たるか": SimpleNamespace(id="所得税.勤労学生に当たるか", module="m", declared_targets=lambda: ()),
        }
        by_var = {"v_要件": concepts["所得税.要件"], "v_合計": concepts["所得税.合計所得金額"]}
        d = SimpleNamespace(by_variable=by_var.get, get=concepts.get)
        return SimpleNamespace(dictionary=d, boundaries=(("v_要件", "v_合計", "所得税.扶養親族.上限", "所得税.扶養の境目", None),))

    def test_declarations_and_undeclared(self) -> None:
        reg = self._reg()
        self.assertEqual(
            [b.to_dict() for b in declarations(reg)],
            [{"module": "m", "judgment": "所得税.要件", "boundary_id": "所得税.扶養の境目", "compared": "所得税.合計所得金額",
              "criterion": "所得税.扶養親族.上限", "comparison": None}],
        )  # fmt: skip
        judgments = {"扶養": ("所得税.扶養親族に当たるか",), "勤労学生": ("所得税.勤労学生に当たるか",), "なし": ("所得税.辞書にない",)}
        self.assertEqual(undeclared(reg, judgments), {"勤労学生": ("所得税.勤労学生に当たるか",)})


class FormsOutputTest(unittest.TestCase):
    """欄の値の組み込み：施行日前の提出は build_filing と同じ判定で止める・値のない人は作らない・対応表が読む概念。"""

    def test_before_enforcement_is_refused(self) -> None:
        late = _param("所得税.丙", 3, enforced_on="2026-12-01")
        values = [rv("x", YenAmount(1), basis=(late,), filing_item=True, filing_scope=True)]
        out = forms_for(values, ["p-1", "p-2"], [2025], _dt.date(2026, 3, 10))
        self.assertEqual(len(out), 1)  # p-2 は値がないので作らない
        self.assertIsInstance(out[0], FormsRefusal)
        self.assertEqual((out[0].category, out[0].blocking_value_ids), (RefusalCategory.BEFORE_ENFORCEMENT, ("x",)))
        self.assertNotIsInstance(forms_for(values, ["p-1"], [2025], _dt.date(2027, 3, 10))[0], type(None))

    def test_form_concepts(self) -> None:
        cs = form_concepts(2025)
        self.assertIn("所得税.総所得金額", cs)  # 欄
        self.assertIn("所得税.純損失の金額", cs)  # 申告の型
        self.assertEqual(form_concepts(2040), frozenset())


class LateReadTest(unittest.TestCase):
    """段の late_reads（不動点の繰り返し）：渡されなければ pending の既定値、宣言していない変数は読めない、読んだ値を記録する。"""

    def test_late(self) -> None:
        stage = StageSpec(name="段", title="", reads=(), late_reads=("所得税_甲",))
        base = YearContext(make_ir([person("p")], []), 2026, ("p",))
        ctx = StageContext(base, stage, {})
        v = ctx.late("所得税_甲", "p")
        self.assertTrue(v.pending)
        with self.assertRaises(KeyError):
            ctx.late("所得税_乙", "p")
        given = StageValue("所得税_甲", "p", True)
        ctx2 = StageContext(base, stage, {}, {("所得税_甲", "p"): given})
        self.assertIs(ctx2.late("所得税_甲", "p"), given)
        self.assertEqual(ctx2.late_log, [given])


class EngineTest(unittest.TestCase):
    """Simulation の使い回し：入力を変えた後の値とトレースの依存が、新しい Simulation と同じ。グループが変われば別の Simulation。"""

    WAGE = "所得税_給与等の収入金額"
    OUT = "所得税_給与所得"

    def _build(self, wage: int, persons=("p",)) -> YearBuild:
        inputs = {(self.WAGE, p): InputValue(wage) for p in persons}
        return YearBuild({"人物一覧": {p: {} for p in persons}}, tuple(persons), inputs, (), {})

    def test_reuse_matches_a_new_simulation(self) -> None:
        sys_ = system()
        period = _period("2026")
        engine = _Engine(sys_)
        for wage in (3_000_000, 9_000_000, 3_000_000):
            build = self._build(wage)
            sim = engine.prepare(build, period)
            got = sim.calculate(self.OUT, period)
            fresh = new_simulation(sys_, build, period)
            fresh.trace = True
            want = fresh.calculate(self.OUT, period)
            self.assertEqual(int(got[0]), int(want[0]))
            self.assertEqual(set(engine.round_graph()), set(trace_graph(fresh.tracer)))
        self.assertEqual(engine.fresh, 1)
        engine.prepare(self._build(1, ("p", "q")), period)  # 人が変われば別の Simulation
        self.assertEqual(engine.fresh, 2)


if __name__ == "__main__":
    unittest.main()

"""問いの時点（timepoints.py）と、評価の単位の値の組み立て（evaluate の unit_outputs・_prune・_merge_value の未注入の扱い）。

関数を直接呼ぶユニットテスト（D24）。
"""

from __future__ import annotations

import datetime as _dt
import unittest

from okura_core.candidates import Candidate, Slot
from okura_core.evaluate import _merge_value, _prune, _Raw, _Run, _ValuePlan, unit_outputs
from okura_core.query import parse_query
from okura_core.registry import OutputSpec, YearContext, YearWindow
from okura_core.result import Means, OutOfScopeCategory, ResultValue, Split, State, TimeKey, YenAmount
from okura_core.timepoints import (
    Unit,
    income_tax_window,
    judgment_window,
    kokunen_window,
    plan_units,
    resident_tax_window,
)

from .fixture_modules import fixture_registry
from .support import make_ir, make_query, person

ALL = frozenset({("住民税", "年度"), ("国保", "年度"), ("国年", "年度"), ("健保", "判定日"), ("国年", "判定日")})


class TestWindows(unittest.TestCase):
    def test_fiscal_year_is_computed_in_the_previous_income_year(self) -> None:
        w = resident_tax_window(2027)
        self.assertEqual(w.income_year, 2026)
        self.assertEqual(w.time, TimeKey("fiscal_year", 2027))
        self.assertEqual(w.date("賦課期日"), _dt.date(2027, 1, 1))  # 地方税法第318条
        self.assertEqual(w.date("前年の12月31日"), _dt.date(2026, 12, 31))  # 同第314条の2第8項
        n = kokunen_window(2026)
        self.assertEqual((n.income_year, n.date("免除等の期間の初日"), n.date("免除等の期間の末日")), (2025, _dt.date(2026, 7, 1), _dt.date(2027, 6, 30)))
        self.assertEqual(n.date("学生納付特例の期間の初日"), _dt.date(2026, 4, 1))
        with self.assertRaises(KeyError):
            w.date("判定日")

    def test_plan_puts_the_fiscal_year_into_the_same_unit_as_the_previous_tax_year(self) -> None:
        units, items = plan_units([2025], {"resident_tax_fiscal_years": [2026], "kokuho_fiscal_years": [2026]}, [], ALL)
        self.assertEqual(items, ())
        self.assertEqual(len(units), 1)
        u = units[0]
        self.assertEqual((u.income_year, u.on), (2025, None))
        self.assertEqual({(w.institution, w.question) for w in u.windows}, {("所得税", "年分"), ("住民税", "年度"), ("国保", "年度")})

    def test_judgment_dates_are_separate_units(self) -> None:
        d1, d2 = _dt.date(2026, 4, 1), _dt.date(2026, 10, 1)
        units, _ = plan_units([2026], {}, [d2, d1], ALL)
        self.assertEqual([(u.income_year, u.on) for u in units], [(2026, None), (2026, d1), (2026, d2)])
        self.assertEqual({w.institution for w in units[1].windows}, {"健保", "国年"})
        self.assertEqual(units[1].window_for("健保", "判定日").judgment_on, d1)

    def test_out_of_years_and_not_implemented(self) -> None:
        units, items = plan_units(
            [2024], {"resident_tax_fiscal_years": [2025, 2027], "kokunen_fiscal_years": [2027]}, [_dt.date(2024, 12, 31), _dt.date(2026, 1, 1)],
            frozenset({("住民税", "年度")}),
        )
        cats = [(i.target["query"], i.target["value"], i.category) for i in items]
        self.assertIn(("income_tax_years", 2024, OutOfScopeCategory.OUT_OF_YEARS), cats)
        self.assertIn(("resident_tax_fiscal_years", 2025, OutOfScopeCategory.OUT_OF_YEARS), cats)
        self.assertIn(("kokunen_fiscal_years", 2027, OutOfScopeCategory.NOT_IMPLEMENTED), cats)  # 担当のモジュールが未登録
        self.assertIn(("dependent_judgment_dates", "2024-12-31", OutOfScopeCategory.OUT_OF_YEARS), cats)
        self.assertIn(("dependent_judgment_dates", "2026-01-01", OutOfScopeCategory.NOT_IMPLEMENTED), cats)
        self.assertEqual([(u.income_year, [w.institution for w in u.windows]) for u in units], [(2026, ["住民税"])])

    def test_time_keys_and_value_id_tags(self) -> None:
        u = Unit(2025, None, (income_tax_window(2025), resident_tax_window(2026)))
        self.assertEqual(u.time_of("所得税", "年分"), TimeKey("tax_year", 2025))
        self.assertEqual(u.tag(u.time_of("所得税", "年分")), "2025")  # 所得税の値の ID は従来どおり
        self.assertEqual(u.tag(u.time_of("住民税", "年度")), "FY2026")
        self.assertEqual(u.tag(u.time_of("国保", "年度")), "FY2026")  # 窓口がなくても問いから導く（依存先として出す値）
        d = _dt.date(2026, 3, 1)
        j = Unit(2026, d, (judgment_window("健保", d),))
        self.assertEqual(j.time_of("健保", "判定日"), TimeKey("on", "2026-03-01"))
        self.assertEqual(j.tag(j.time_of("健保", "判定日")), "2026-03-01")
        self.assertEqual(j.tag(j.time_of("所得税", "年分")), "2026-03-01@2026")  # 判定日の単位の、判定日でない値

    def test_year_context_window(self) -> None:
        ctx = YearContext(make_ir([person("p")], []), 2025, ("p",), window=YearWindow(windows=(resident_tax_window(2026),)))
        self.assertEqual(ctx.window("住民税", "年度").date("賦課期日"), _dt.date(2026, 1, 1))
        self.assertIsNone(ctx.window("国保", "年度"))
        self.assertEqual(ctx.injected.entries, ())

    def test_query_kokunen_fiscal_years_is_optional(self) -> None:
        q, p = parse_query(make_query((2026,)))
        self.assertEqual((p, q.kokunen_fiscal_years), ([], ()))
        q, p = parse_query(make_query((2026,), kokunen_fiscal_years=[2027, 2026]))
        self.assertEqual((p, q.kokunen_fiscal_years), ([], (2026, 2027)))
        self.assertEqual(q.to_dict()["kokunen_fiscal_years"], [2026, 2027])
        _, p = parse_query(make_query((2026,), kokunen_fiscal_years=["2026"]))
        self.assertIn(("$.kokunen_fiscal_years[0]", "type"), [(x.path, x.code) for x in p])


class TestUnitValues(unittest.TestCase):
    def test_unit_outputs_asks_only_the_windows_and_their_dependencies(self) -> None:
        # 登録済みのモジュールの一覧を決め打ちしない：期待値は登録の概念辞書から求める（ほかの担当が住民税の出力を足しても直さずに済む）
        fixture_vars = frozenset({"住民税_試験_級地の番号", "住民税_試験_均等割の税率"})
        for reg in (fixture_registry("test_injection"),):
            d = reg.dictionary
            fiscal_only = Unit(2025, None, (resident_tax_window(2026),))
            specs, asked = unit_outputs(reg, fiscal_only)
            want = frozenset(
                o.variable for o in reg.outputs
                if (d.concept(o.concept).institution, d.concept(o.concept).timing.question) == ("住民税", "年度")
            )
            self.assertEqual(asked, want)
            self.assertLessEqual(fixture_vars, asked)
            reach = {c.id for o in reg.outputs if o.variable in asked for c in d.closure(o.concept)}
            tax_outputs = {o.variable for o in reg.outputs if d.concept(o.concept).institution == "所得税"}
            if any(d.concept(c).institution == "所得税" for c in reach):
                self.assertLessEqual(tax_outputs, {s.variable for s in specs})  # 所得税に届くなら所得税の出力の全部を計算する
            else:
                self.assertEqual({s.variable for s in specs}, set(asked))  # 届かなければ所得税の出力を計算しない
            # 試験の概念は所得税に依存しない（宣言した依存に所得税の概念がない）
            for o in reg.outputs:
                if o.variable in fixture_vars:
                    self.assertFalse(any(c.institution == "所得税" for c in d.closure(o.concept)))
            tax = Unit(2025, None, (income_tax_window(2025),))
            specs, asked = unit_outputs(reg, tax)
            self.assertTrue(fixture_vars.isdisjoint(asked))
            self.assertEqual(asked, frozenset(
                o.variable for o in reg.outputs
                if (d.concept(o.concept).institution, d.concept(o.concept).timing.question) == ("所得税", "年分")
            ))

    def test_prune_keeps_asked_values_and_their_dependencies(self) -> None:
        def v(vid: str, var: str, deps: tuple[str, ...] = ()) -> ResultValue:
            return ResultValue(vid, "住民税.x", var, "p", TimeKey("fiscal_year", 2026), YenAmount(1), frozenset(), (), depends_on=deps)

        values = [v("a", "所得税_x"), v("b", "所得税_y"), v("c", "住民税_z", ("a",))]
        kept, asked = _prune(values, frozenset({"住民税_z"}))
        self.assertEqual([x.id for x in kept], ["a", "c"])
        self.assertEqual(asked, frozenset({"c"}))

    def test_merge_marks_values_that_depend_on_missing_injection_undetermined(self) -> None:
        missing = Split("注入.住民税.均等割の税率:k", Means.INJECTION, {"注入点": "住民税.均等割の税率"}, (), True)
        spec = OutputSpec("住民税_試験_均等割の税率", "住民税.試験_均等割の税率", "円", False, False)
        raw = _Raw(0, set(), set(), set(), [], [], False, frozenset(), {missing.id: missing})
        plan = _ValuePlan([], [_Run({}, None, raws={(spec.variable, "p"): raw})])  # type: ignore[arg-type]
        value = _merge_value(spec, "p", plan, 2025, lambda c, p: f"v:FY2026:{p}:{c}", lambda c: TimeKey("fiscal_year", 2026))
        self.assertIsNone(value.value)
        self.assertIn(State.UNDETERMINED, value.states)
        self.assertEqual([s.id for s in value.undetermined.splits], [missing.id])
        self.assertEqual(value.undetermined.outcomes, ())
        self.assertEqual((value.id, value.time), ("v:FY2026:p:住民税.試験_均等割の税率", TimeKey("fiscal_year", 2026)))
        # 候補のある注入点の分かれ目は、判断と同じ道具でまとめる（結論が違えば未確定、決める手段は注入）
        slot = Slot("注入.住民税.級地:k", Means.INJECTION, {}, (Candidate({"級地": "1級地"}, "1級地"), Candidate({"級地": "2級地"}, "2級地")))
        spec2 = OutputSpec("住民税_試験_級地の番号", "住民税.試験_級地の番号", "整数", False, False)
        runs = [
            _Run({slot.id: c}, None, raws={(spec2.variable, "p"): _Raw(n, set(), set(), set(), [], [], False, frozenset({(spec2.variable, "p")}))})  # type: ignore[arg-type]
            for n, c in ((1, slot.candidates[0]), (2, slot.candidates[1]))
        ]
        plan2 = _ValuePlan([slot], runs, affected={slot.id: frozenset({(spec2.variable, "p")})})
        value2 = _merge_value(spec2, "p", plan2, 2025)
        self.assertIn(State.UNDETERMINED, value2.states)
        self.assertIs(value2.undetermined.splits[0].means, Means.INJECTION)


class TestBoundaryWithCriterionConcept(unittest.TestCase):
    """境目の基準を概念の値で出す共有の仕組み（2026-11-11）：基準が判定日・年齢・制度で変わる被扶養者の収入の基準。"""

    def test_boundary_uses_the_criterion_value_and_its_parameter_basis(self) -> None:
        from types import SimpleNamespace

        from okura_core.basis import BasisEntry, BasisType, SourceKind
        from okura_core.evaluate import _boundaries
        from okura_core.result import Comparison, Flag

        d = _dt.date(2026, 4, 1)
        unit = Unit(2026, d, (judgment_window("健保", d),))
        t = TimeKey("on", "2026-04-01")
        param = BasisEntry(BasisType.PARAMETER, "健保.被扶養者の収入の基準額.健康保険.19歳以上23歳未満.額", SourceKind.NOTIFICATION, ("docs/x.md#1",), value=1_500_000)

        def v(var: str, value: object, basis: tuple = ()) -> ResultValue:
            return ResultValue(f"v:{var}", var.replace("_", ".", 1), var, "p", t, value, frozenset(), basis)  # type: ignore[arg-type]

        by_key = {
            ("健保_年間収入が収入の基準額未満か", "p"): v("健保_年間収入が収入の基準額未満か", Flag(True)),
            ("健保_年間収入", "p"): v("健保_年間収入", YenAmount(1_400_000)),
            ("健保_収入の基準額", "p"): v("健保_収入の基準額", YenAmount(1_500_000), (param,)),
        }
        reg = SimpleNamespace(boundaries=(("健保_年間収入が収入の基準額未満か", "健保_年間収入", "健保_収入の基準額", "健保.被扶養者の年間収入の基準", "未満"),))
        (b,) = _boundaries(by_key, ["p"], unit, reg)  # type: ignore[arg-type]
        self.assertEqual((b.criterion_value, b.comparison, b.crossing_value, b.difference), (1_500_000, Comparison.LESS_THAN, 1_500_000, 100_000))
        self.assertIs(b.criterion, param)  # 基準の額を決めたパラメータの根拠（判定日・年齢で選ばれた葉）
        self.assertEqual(b.id, "b:2026-04-01:p:健保.被扶養者の年間収入の基準")
        # 基準の値が出ていなければ境目を出さない
        del by_key[("健保_収入の基準額", "p")]
        self.assertEqual(_boundaries(by_key, ["p"], unit, reg), [])  # type: ignore[arg-type]

    def test_dictionary_rejects_ill_formed_criterion_concepts(self) -> None:
        from okura_core.concepts import ConceptDictionaryError, check_dictionary, parse_dictionary, read_files

        structure, files = read_files()
        f = files["rules/hifuyosha/concepts.yaml"]
        concepts = [dict(c) for c in f["概念"]]
        i = next(k for k, c in enumerate(concepts) if c["id"] == "健保.年間収入が収入の基準額未満か")

        def parsed(boundaries: list) -> object:
            cs = list(concepts)
            cs[i] = {**cs[i], "境目": boundaries}
            return parse_dictionary(structure, {**files, "rules/hifuyosha/concepts.yaml": {**f, "概念": cs}})

        with self.assertRaises(ConceptDictionaryError):  # 比較がない
            parsed([{"id": "健保.x1", "比べる概念": "健保.年間収入", "基準の概念": "健保.収入の基準額"}])
        with self.assertRaises(ConceptDictionaryError):  # 基準と基準の概念の両方
            parsed([{"id": "健保.x1", "比べる概念": "健保.年間収入", "基準": "健保.a", "基準の概念": "健保.収入の基準額", "比較": "未満"}])
        d = parsed([
            {"id": "健保.x2", "比べる概念": "健保.年間収入", "基準の概念": "健保.被扶養者に当たるか", "比較": "未満"},  # 円でない
            {"id": "健保.x3", "比べる概念": "健保.年間収入", "基準の概念": "健保.収入の基準額", "比較": "ちょうど"},
        ])
        msgs = [p.message for p in check_dictionary(d) if p.code == "boundary"]  # type: ignore[arg-type]
        self.assertTrue(any("比較は" in m for m in msgs))
        self.assertTrue(any("基準の概念は円の出力" in m for m in msgs))


if __name__ == "__main__":
    unittest.main()

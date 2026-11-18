"""結果のモデル（result.py）：不変条件、JSON への直列化、result.schema.json、申告用の値の規則（D19・D21 R2・D22）。"""

from __future__ import annotations

import datetime as _dt
import json
import unittest

from okura_ir.jsonschema_subset import check_schema

from okura_core.basis import BasisEntry, BasisType, SourceKind
from okura_core.money import YenRange
from okura_core.result import (
    Boundary,
    Comparison,
    EvaluationFailure,
    EvaluationResult,
    FilingEntry,
    Flag,
    Means,
    OutOfScopeCategory,
    OutOfScopeItem,
    OutOfScopeReason,
    Problem,
    ResultValue,
    ScenarioResult,
    Split,
    State,
    TimeKey,
    Undetermined,
    YenAmount,
    build_filing,
    check_result_json,
    dumps,
    load_result_schema,
)

T = TimeKey("tax_year", 2026)
PARAM = BasisEntry(
    BasisType.PARAMETER,
    "所得税.試験",
    SourceKind.LAW,
    ("docs/public-sources/x.md#1",),
    value=620000,
    instant="2026-01-01",
    effective_from="2026-01-01",
    enforced_on="2026-12-01",
    detail={"比較": "以下"},
)


def rv(vid: str, value, states=(), *, person="p-1", concept=None, filing_item=True, filing_scope=True, **kw) -> ResultValue:
    return ResultValue(
        id=vid,
        concept=concept or f"所得税.{vid}",
        variable=None,
        person=person,
        time=T,
        value=value,
        states=frozenset(states),
        basis=(PARAM,),
        filing_item=filing_item,
        filing_scope=filing_scope,
        **kw,
    )


class TestInvariants(unittest.TestCase):
    def test_out_of_scope_has_no_value(self) -> None:
        reason = OutOfScopeReason(OutOfScopeCategory.NOT_IMPLEMENTED, "未対応")
        rv("a", None, [State.OUT_OF_SCOPE], out_of_scope=reason)
        with self.assertRaises(ValueError):
            rv("a", YenAmount(1), [State.OUT_OF_SCOPE], out_of_scope=reason)
        with self.assertRaises(ValueError):
            rv("a", None, [State.OUT_OF_SCOPE])

    def test_undetermined_needs_split(self) -> None:
        und = Undetermined((Split("u1", Means.INJECTION, {"point": "x"}, ("a", "b"), True),), ())
        rv("a", None, [State.UNDETERMINED], undetermined=und)
        rv("a", YenRange(1, 2), [State.UNDETERMINED], undetermined=und)
        with self.assertRaises(ValueError):
            rv("a", None, [State.UNDETERMINED])
        with self.assertRaises(ValueError):
            rv("a", YenAmount(1), [], undetermined=und)

    def test_missing_value_needs_state(self) -> None:
        with self.assertRaises(ValueError):
            rv("a", None, [])

    def test_amount_types(self) -> None:
        with self.assertRaises(TypeError):
            YenAmount(1.0)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            YenAmount(True)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            Flag(1)  # type: ignore[arg-type]

    def test_state_from_mark(self) -> None:
        self.assertEqual(State.from_mark("予測"), State.FORECAST)
        self.assertEqual(State.from_mark("見積り"), State.ESTIMATE)
        self.assertEqual(State.from_mark("計画"), State.PLAN)
        with self.assertRaises(ValueError):
            State.from_mark("未確定")


class TestComparison(unittest.TestCase):
    def test_crossing_values(self) -> None:
        c = 620_000
        self.assertEqual(Comparison.AT_MOST.crossing_value(600_000, c), 620_001)
        self.assertEqual(Comparison.AT_MOST.crossing_value(620_000, c), 620_001)
        self.assertEqual(Comparison.AT_MOST.crossing_value(620_001, c), 620_000)
        self.assertEqual(Comparison.LESS_THAN.crossing_value(1, c), 620_000)
        self.assertEqual(Comparison.LESS_THAN.crossing_value(620_000, c), 619_999)
        self.assertEqual(Comparison.MORE_THAN.crossing_value(620_001, c), 620_000)
        self.assertEqual(Comparison.MORE_THAN.crossing_value(1, c), 620_001)
        self.assertEqual(Comparison.AT_LEAST.crossing_value(620_000, c), 619_999)
        self.assertEqual(Comparison.AT_LEAST.crossing_value(1, c), 620_000)
        for comp in Comparison:
            for q in (0, c - 1, c, c + 1, 10**7):
                x = comp.crossing_value(q, c)
                self.assertNotEqual(comp.holds(q, c), comp.holds(x, c), (comp, q))

    def test_boundary_checks_consistency(self) -> None:
        kw = dict(
            id="b1", concept="所得税.試験の境目", person="p-1", time=T, judgment_value_id="j", compared_value_id="c",
            compared_concept="所得税.合計所得金額", criterion=PARAM, criterion_value=620_000,
            comparison=Comparison.AT_MOST, states=frozenset(),
        )
        Boundary(judgment=True, current=600_000, crossing_value=620_001, difference=20_001, **kw)
        with self.assertRaises(ValueError):
            Boundary(judgment=False, current=600_000, crossing_value=620_001, difference=20_001, **kw)
        with self.assertRaises(ValueError):
            Boundary(judgment=True, current=600_000, crossing_value=620_000, difference=20_000, **kw)


class TestFiling(unittest.TestCase):
    def test_forecast_blocks_the_whole_person_year(self) -> None:
        a = rv("a", YenAmount(100), [State.FORECAST])
        b = rv("b", YenAmount(200), [])
        other = rv("c", YenAmount(300), [], person="p-2")
        entries, withheld = build_filing([a, b, other])
        self.assertEqual([e.value_id for e in entries], ["c"])
        self.assertEqual(sorted(w.value_id for w in withheld), ["a", "b"])
        self.assertEqual(withheld[0].reasons, ("予測",))
        self.assertEqual(withheld[0].blocking_value_ids, ("a",))

    def test_aggregation_point_in_scope_blocks(self) -> None:
        reason = OutOfScopeReason(OutOfScopeCategory.NOT_IMPLEMENTED, "未対応")
        agg = rv("g", None, [State.OUT_OF_SCOPE], filing_item=False, out_of_scope=reason)
        item = rv("i", YenAmount(1), [])
        entries, withheld = build_filing([agg, item])
        self.assertEqual(entries, ())
        self.assertEqual(withheld[0].reasons, ("対象外",))

    def test_estimate_and_plan_are_allowed_with_conditions(self) -> None:
        e = rv("e", YenAmount(1), [State.ESTIMATE, State.PLAN])
        entries, withheld = build_filing([e])
        self.assertEqual(withheld, ())
        d = entries[0].to_dict()
        self.assertEqual(d["states"], ["見積り", "計画"])
        self.assertEqual(len(d["conditions"]), 2)

    def test_range_is_withheld(self) -> None:
        r = rv("r", YenRange(1, 2), [])
        entries, withheld = build_filing([r])
        self.assertEqual(entries, ())
        self.assertEqual(withheld[0].reasons, ("幅",))

    def test_filing_before_enforcement_is_withheld(self) -> None:
        a = rv("a", YenAmount(1), [])
        entries, withheld = build_filing([a], filing_date=_dt.date(2026, 11, 30))
        self.assertEqual(entries, ())
        self.assertIn("施行日前の提出", withheld[0].reasons[0])
        entries, withheld = build_filing([a], filing_date=_dt.date(2026, 12, 1))
        self.assertEqual(len(entries), 1)

    def test_filing_entry_cannot_be_made_directly(self) -> None:
        with self.assertRaises(PermissionError):
            FilingEntry("a", "x", "p", T, 1, frozenset())

    def test_scenario_rejects_blocked_filing(self) -> None:
        a = rv("a", YenAmount(1), [])
        entries, _ = build_filing([a])
        forecast = rv("a", YenAmount(1), [State.FORECAST])
        with self.assertRaises(ValueError):
            ScenarioResult("base", None, (forecast,), (), (), entries, ())


class TestSerialization(unittest.TestCase):
    def _sample(self) -> EvaluationResult:
        und = Undetermined(
            (Split("u1", Means.PRIMARY_SOURCE, {"rounding": "試験"}, ("floor", "ceil"), True),),
            (),
        )
        values = (
            rv("v1", YenAmount(620_000), [State.ESTIMATE], facts=("f-1",)),
            rv("v2", Flag(True), [], filing_item=False, filing_scope=False, depends_on=("v1",)),
            rv("v3", YenRange(1, 3), [], filing_item=False, filing_scope=False),
            rv("v4", None, [State.UNDETERMINED], filing_item=False, filing_scope=False, undetermined=und),
        )
        b = Boundary(
            id="b1", concept="所得税.扶養親族の所得要件", person="p-1", time=T, judgment_value_id="v2", judgment=True,
            compared_value_id="v1", compared_concept="所得税.合計所得金額", current=620_000, criterion=PARAM,
            criterion_value=620_000, comparison=Comparison.AT_MOST, crossing_value=620_001, difference=1,
            states=frozenset({State.ESTIMATE}),
        )
        entries, withheld = build_filing(values)
        sc = ScenarioResult(
            "base", "差分なし", values, (b,),
            (OutOfScopeItem({"query": "income_tax_years", "value": 2024}, (), OutOfScopeCategory.OUT_OF_YEARS, "年分外"),),
            entries, withheld,
        )
        versions = {
            "okura_core": "0", "openfisca_core": "0", "numpy": "0", "python": "3", "ir_schema": "0", "result_schema": "0",
            "parameters_sha256": {"a.yaml": "0" * 64}, "data_sha256": {}, "input_sha256": "f" * 64,
        }
        query = {
            "income_tax_years": [2026], "filing_date": None, "resident_tax_fiscal_years": [], "kokuho_fiscal_years": [],
            "dependent_judgment_dates": [], "scenarios": [],
        }
        return EvaluationResult(versions, query, (), (sc,))

    def test_schema_is_in_subset(self) -> None:
        self.assertEqual(check_schema(load_result_schema()), [])

    def test_result_matches_schema(self) -> None:
        d = self._sample().to_dict()
        self.assertEqual(check_result_json(d), [])
        json.loads(dumps(self._sample()))

    def test_failure_matches_schema(self) -> None:
        f = EvaluationFailure((Problem("$.query", "type", "x"),))
        self.assertEqual(check_result_json(f.to_dict()), [])
        with self.assertRaises(ValueError):
            EvaluationFailure(())

    def test_schema_rejects_float_amount(self) -> None:
        d = self._sample().to_dict()
        d["scenarios"][0]["values"][0]["value"]["amount"] = 1.5
        self.assertTrue(check_result_json(d))

    def test_dumps_is_deterministic(self) -> None:
        self.assertEqual(dumps(self._sample()), dumps(self._sample()))
        self.assertTrue(dumps(self._sample()).endswith("\n"))


if __name__ == "__main__":
    unittest.main()

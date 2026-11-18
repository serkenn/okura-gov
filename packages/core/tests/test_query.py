"""問い（query.py）と注入データ（injection.py）の検査。"""

from __future__ import annotations

import datetime as _dt
import unittest

from okura_core.basis import SourceKind
from okura_core.injection import parse_injected
from okura_core.query import BASE_SCENARIO_ID, parse_query

from .support import make_query


class TestQuery(unittest.TestCase):
    def test_minimal(self) -> None:
        q, p = parse_query(make_query((2026, 2025)))
        self.assertEqual(p, [])
        assert q is not None
        self.assertEqual(q.income_tax_years, (2025, 2026))
        self.assertIsNone(q.filing_date)
        self.assertEqual([s.id for s in q.all_scenarios()], [BASE_SCENARIO_ID])

    def test_full(self) -> None:
        raw = make_query(
            (2026,),
            filing_date={"on": "2027-02-20", "planned": True},
            resident_tax_fiscal_years=[2027],
            kokuho_fiscal_years=[2027],
            dependent_judgment_dates=["2026-10-01", "2026-04-01"],
            scenarios=[{"id": "s1", "label": "別の見込み", "judgments": [], "choices": []}],
        )
        q, p = parse_query(raw)
        self.assertEqual(p, [])
        assert q is not None
        self.assertEqual(q.filing_date.on, _dt.date(2027, 2, 20))
        self.assertTrue(q.filing_date.planned)
        self.assertEqual(q.dependent_judgment_dates, (_dt.date(2026, 4, 1), _dt.date(2026, 10, 1)))
        self.assertEqual([s.id for s in q.all_scenarios()], ["base", "s1"])
        self.assertEqual(q.to_dict()["dependent_judgment_dates"], ["2026-04-01", "2026-10-01"])

    def _codes(self, raw) -> list[tuple[str, str]]:
        q, p = parse_query(raw)
        self.assertIsNone(q)
        return [(x.path, x.code) for x in p]

    def test_errors(self) -> None:
        self.assertEqual(self._codes([]), [("$", "type")])
        raw = make_query()
        del raw["scenarios"]
        self.assertIn(("$.scenarios", "required"), self._codes(raw))
        self.assertIn(("$.extra", "additional_property"), self._codes({**make_query(), "extra": 1}))
        self.assertIn(("$.income_tax_years[0]", "type"), self._codes(make_query((True,))))  # type: ignore[arg-type]
        self.assertIn(("$.income_tax_years[0]", "type"), self._codes({**make_query(), "income_tax_years": ["2026"]}))
        self.assertIn(("$.income_tax_years[0]", "type"), self._codes({**make_query(), "income_tax_years": [2026.0]}))
        self.assertIn(("$.income_tax_years[1]", "duplicate"), self._codes(make_query((2026, 2026))))
        self.assertIn(("$.income_tax_years[0]", "range"), self._codes(make_query((1999,))))
        self.assertIn(
            ("$.dependent_judgment_dates[0]", "format"),
            self._codes(make_query(dependent_judgment_dates=["2026-02-30"])),
        )
        self.assertIn(
            ("$.dependent_judgment_dates[0]", "format"),
            self._codes(make_query(dependent_judgment_dates=["20260201"])),
        )
        self.assertIn(
            ("$.filing_date.planned", "type"),
            self._codes(make_query(filing_date={"on": "2027-03-15", "planned": "yes"})),
        )
        self.assertIn(("$.filing_date.on", "required"), self._codes(make_query(filing_date={"planned": True})))

    def test_scenario_errors(self) -> None:
        sc = lambda **kw: {"id": "s1", "judgments": [], "choices": [], **kw}  # noqa: E731
        self.assertIn(("$.scenarios[0].id", "reserved"), self._codes(make_query(scenarios=[sc(id="base")])))
        self.assertIn(("$.scenarios[0].id", "pattern"), self._codes(make_query(scenarios=[sc(id="シナリオ")])))
        self.assertIn(("$.scenarios[1].id", "duplicate"), self._codes(make_query(scenarios=[sc(), sc()])))
        self.assertIn(("$.scenarios[0].judgments", "type"), self._codes(make_query(scenarios=[sc(judgments=[1])])))
        self.assertIn(("$.scenarios[0].facts", "additional_property"), self._codes(make_query(scenarios=[sc(facts=[])])))


GOOD_INJECTION = {
    "id": "inj-1",
    "point": "住民税.均等割の税率",
    "issuer": {"kind": "municipality", "code": "990001"},
    "applies": {"from_on": "2026-04-01", "to_on": "2027-03-31"},
    "source": {"url": "https://example.invalid/kakuu.html", "retrieved_on": "2026-11-01", "source_kind": "自治体の資料"},
    "data": {"税率": 3000},
}


class TestInjection(unittest.TestCase):
    def test_none_and_empty(self) -> None:
        self.assertEqual(parse_injected(None)[0].entries, ())
        self.assertEqual(parse_injected([])[0].entries, ())

    def test_good(self) -> None:
        inj, p = parse_injected([GOOD_INJECTION])
        self.assertEqual(p, [])
        e = inj.entries[0]
        self.assertEqual(e.source.source_kind, SourceKind.MUNICIPAL_MATERIAL)
        self.assertEqual(e.applies_to, _dt.date(2027, 3, 31))
        self.assertNotIn("data", e.to_summary())

    def _codes(self, entry) -> list[tuple[str, str]]:
        inj, p = parse_injected([entry])
        self.assertIsNone(inj)
        return [(x.path, x.code) for x in p]

    def test_source_url_retrieved_on_and_period_are_required(self) -> None:
        for key in ("url", "retrieved_on", "source_kind"):
            src = {k: v for k, v in GOOD_INJECTION["source"].items() if k != key}
            with self.subTest(key=key):
                self.assertIn((f"$[0].source.{key}", "required"), self._codes({**GOOD_INJECTION, "source": src}))
        self.assertIn(("$[0].applies", "required"), self._codes({k: v for k, v in GOOD_INJECTION.items() if k != "applies"}))
        self.assertIn(("$[0].applies.from_on", "required"), self._codes({**GOOD_INJECTION, "applies": {"to_on": "2027-03-31"}}))

    def test_bad_values(self) -> None:
        bad_url = {**GOOD_INJECTION["source"], "url": "file:///C:/secret"}
        self.assertIn(("$[0].source.url", "pattern"), self._codes({**GOOD_INJECTION, "source": bad_url}))
        bad_kind = {**GOOD_INJECTION["source"], "source_kind": "ブログ"}
        self.assertIn(("$[0].source.source_kind", "enum"), self._codes({**GOOD_INJECTION, "source": bad_kind}))
        rev = {"from_on": "2027-04-01", "to_on": "2027-03-31"}
        self.assertIn(("$[0].applies.to_on", "period_reversed"), self._codes({**GOOD_INJECTION, "applies": rev}))
        self.assertIn(("$[0].data", "type"), self._codes({**GOOD_INJECTION, "data": [1]}))
        inj, p = parse_injected([GOOD_INJECTION, GOOD_INJECTION])
        self.assertIn(("$[1].id", "duplicate_id"), [(x.path, x.code) for x in p])
        self.assertEqual([(x.path, x.code) for x in parse_injected({})[1]], [("$", "type")])


if __name__ == "__main__":
    unittest.main()

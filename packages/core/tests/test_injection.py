"""注入データ（injection.py・injection_points.py）と、未注入のときの範囲評価の窓口（registry.InjectionSpec・situation.resolve_decisions）。

関数を直接呼ぶユニットテスト（D24）。架空の団体のデータだけを使う。
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import unittest

from okura_core.basis import BasisType, SourceKind
from okura_core.concepts import check_dictionary, load_dictionary, parse_dictionary, read_files
from okura_core.injection import DataField, InjectionPoint, NamedCandidate, check_catalog, parse_injected
from okura_core.injection_points import POINTS
from okura_core.registry import InjectionSpec, RegistryError, YearContext, YearWindow, build_registry, injection_key
from okura_core.result import Means
from okura_core.scope import input_scope
from okura_core.situation import resolve_decisions
from okura_core.timepoints import income_tax_window, resident_tax_window

from .fixture_modules import TEST_INJECTION, fixture_registry, fixture_system
from .support import make_ir, person
from .test_architecture import reference_problem


def entry(point: str, data: dict, *, eid: str = "inj-1", kind: str = "municipality", code: str = "990001",
          from_on: str = "2026-01-01", to_on: str | None = "2027-03-31") -> dict:
    applies = {"from_on": from_on} if to_on is None else {"from_on": from_on, "to_on": to_on}
    return {
        "id": eid,
        "point": point,
        "issuer": {"kind": kind, "code": code},
        "applies": applies,
        "source": {"url": "https://example.invalid/kakuu.html", "retrieved_on": "2026-11-01", "source_kind": "自治体の資料"},
        "data": data,
    }


def codes(raw: list) -> list[tuple[str, str]]:
    inj, problems = parse_injected(raw)
    if problems:
        assert inj is None
    return [(p.path, p.code) for p in problems]


class TestCatalog(unittest.TestCase):
    def test_catalog_is_consistent_and_references_exist(self) -> None:
        self.assertEqual(check_catalog(POINTS), [])
        for p in POINTS.values():
            for ref in p.references + tuple(r for c in p.candidates for r in c.references):
                with self.subTest(point=p.name, ref=ref):
                    self.assertIsNone(reference_problem(ref))

    def test_candidates_are_ranges_or_collected_types_never_a_single_default(self) -> None:
        # 候補は2つ以上か、持たない（1つだけの候補は既定値になる：D19）
        for p in POINTS.values():
            with self.subTest(point=p.name):
                self.assertNotEqual(len(p.candidates), 1)
        self.assertEqual([c.label for c in POINTS["住民税.級地"].candidates], ["1級地", "2級地", "3級地"])
        # 税率・率・額は範囲が有限でないので候補を持たない（標準税率で計算しない）
        for name in ("住民税.均等割の税率", "住民税.所得割の税率", "国保.率と額", "国保.賦課限度額"):
            self.assertEqual(POINTS[name].candidates, (), name)

    def test_point_definition_errors(self) -> None:
        f = (DataField("x", "enum", "x", values=("a", "b")),)
        with self.assertRaises(ValueError):
            InjectionPoint("住民税.試験", "住民税", "t", ("municipality",), f, "t", ("r",), candidates=(NamedCandidate("a", {"x": "a"}, ("r",)),))
        with self.assertRaises(ValueError):
            InjectionPoint("国保.試験", "住民税", "t", ("municipality",), f, "t", ("r",))
        with self.assertRaises(ValueError):
            DataField("x", "enum", "x")
        bad = InjectionPoint(
            "住民税.試験", "住民税", "t", ("municipality",), f, "t", ("r",),
            candidates=(NamedCandidate("a", {"x": "a"}, ("r",)), NamedCandidate("c", {"x": "c"}, ("r",))),
        )
        self.assertTrue(any("住民税.試験.候補[c].x" in m for m in check_catalog({"住民税.試験": bad})))


class TestParseInjected(unittest.TestCase):
    def test_good_entries(self) -> None:
        inj, p = parse_injected([
            entry("住民税.級地", {"級地": "2級地"}),
            entry("住民税.均等割の税率", {"税率": 3500}, eid="inj-2", kind="prefecture", code="990000"),
            entry("健保.通勤手当の扱い", {"従来の方法": "含まない"}, eid="inj-3", kind="insurer", code="ins-1", to_on=None),
        ])
        self.assertEqual(p, [])
        assert inj is not None
        self.assertEqual(len(inj.entries), 3)
        found = inj.find("住民税.級地", "municipality", "990001", _dt.date(2026, 12, 31))
        self.assertIsNotNone(found)
        self.assertIsNone(inj.find("住民税.級地", "municipality", "990001", _dt.date(2027, 4, 1)))  # 適用期間の外
        self.assertIsNone(inj.find("住民税.級地", "municipality", "990002", _dt.date(2026, 12, 31)))  # 別の団体
        self.assertIsNotNone(inj.find("健保.通勤手当の扱い", "insurer", "ins-1", _dt.date(2030, 1, 1)))  # 終わりのない期間

    def test_prefecture_issuer_needs_a_prefecture_code(self) -> None:
        # 道府県の注入データの鍵は都道府県の団体コード（上2桁＋000＋検査数字。2026-11-12 の整理）。市町村のコードは誤り
        self.assertEqual(codes([entry("住民税.均等割の税率", {"税率": 1000}, kind="prefecture", code="990011")]), [("$[0].issuer.code", "prefecture_code")])
        self.assertEqual(codes([entry("住民税.均等割の税率", {"税率": 1000}, kind="prefecture", code="990000")]), [])

    def test_basis_points_to_the_injected_source(self) -> None:
        inj, _ = parse_injected([entry("住民税.級地", {"級地": "3級地"})])
        assert inj is not None
        b = inj.entries[0].basis(_dt.date(2025, 12, 31))
        self.assertIs(b.type, BasisType.INJECTION)
        self.assertIs(b.source_kind, SourceKind.MUNICIPAL_MATERIAL)
        self.assertEqual(b.references, ("https://example.invalid/kakuu.html",))
        self.assertEqual(b.value, {"級地": "3級地"})
        self.assertEqual(b.detail["injection_id"], "inj-1")

    def test_unknown_point_issuer_kind_and_schema(self) -> None:
        self.assertIn(("$[0].point", "unknown_point"), codes([entry("住民税.ない注入点", {})]))
        self.assertIn(("$[0].issuer.kind", "issuer_kind"), codes([entry("住民税.級地", {"級地": "1級地"}, kind="insurer")]))
        self.assertIn(("$[0].data.級地", "enum"), codes([entry("住民税.級地", {"級地": "4級地"})]))
        self.assertIn(("$[0].data.級地", "required"), codes([entry("住民税.級地", {})]))
        self.assertIn(("$[0].data.余分", "additional_property"), codes([entry("住民税.級地", {"級地": "1級地", "余分": 1})]))
        # 数の欄の文字列・小数・真偽値は拒否する（中間表現と同じ規則）
        for bad in ("3000", 3000.0, True):
            with self.subTest(value=bad):
                self.assertIn(("$[0].data.税率", "type"), codes([entry("住民税.均等割の税率", {"税率": bad})]))
        self.assertIn(("$[0].data.税率", "ratio_out_of_range"), codes([entry("住民税.所得割の税率", {"税率": {"num": 3, "den": 2}})]))
        kubun = {"区分": [{"区分": "基礎賦課額", "所得割率": {"num": 7, "den": 100}, "被保険者均等割額": "x"}]}
        self.assertIn(("$[0].data.区分[0].被保険者均等割額", "type"), codes([entry("国保.率と額", kubun)]))

    def test_overlapping_periods_of_the_same_point_and_issuer_are_rejected(self) -> None:
        a = entry("住民税.級地", {"級地": "1級地"}, from_on="2025-01-01", to_on="2025-12-31")
        b = entry("住民税.級地", {"級地": "2級地"}, eid="inj-2", from_on="2025-12-31", to_on=None)
        self.assertIn(("$[1].applies", "overlapping_period"), codes([a, b]))
        c = entry("住民税.級地", {"級地": "2級地"}, eid="inj-2", from_on="2026-01-01", to_on=None)
        self.assertEqual(codes([a, c]), [])  # 重ならない
        d = entry("住民税.級地", {"級地": "2級地"}, eid="inj-2", code="990002", from_on="2025-01-01")
        self.assertEqual(codes([a, d]), [])  # 別の団体


class TestResolveInjection(unittest.TestCase):
    """InjectionSpec の1か所：注入されていればその値、なければ候補で分かれ目、候補がなければ missing（D19・D21 R6）。"""

    IR = make_ir(
        [person("p-a")],
        [],
        residences=[
            {"id": "res-a", "kind": "resident_record", "roles": {"person": "p-a"}, "when": {"from_on": "2020-01-01"},
             "attributes": {"municipality_code": "990001", "household_id": "hh-a", "householder": True}}
        ],
    )

    def ctx(self, injected: list | None, windows: tuple = (resident_tax_window(2026),)) -> YearContext:
        inj, p = parse_injected(injected)
        self.assertEqual(p, [])
        sys_ = fixture_system("test_injection")
        win = YearWindow(parameters_at=sys_.get_parameters_at_instant, parameter_root=sys_.parameters, windows=windows, injected=inj)
        return YearContext(self.IR, 2025, ("p-a",), window=win)

    def test_not_injected_opens_a_slot_of_the_candidates_or_marks_missing(self) -> None:
        reg = fixture_registry("test_injection")
        dec = resolve_decisions(self.ctx(None), reg)
        kyuchi_key = ("注入.住民税.級地", injection_key("municipality", "990001", _dt.date(2025, 12, 31)))
        slot = next(s for s in dec.open if dec.slot_keys[s.id] == kyuchi_key)
        self.assertIs(slot.means, Means.INJECTION)
        self.assertEqual([c.label for c in slot.candidates], ["1級地", "2級地", "3級地"])
        self.assertEqual(slot.target["注入点"], "住民税.級地")
        self.assertEqual(slot.target["団体"], {"kind": "municipality", "code": "990001"})
        self.assertEqual(slot.target["適用の日"], "2025-12-31")
        # 候補のない注入点：値は None、依存する値を未確定にする分かれ目（決める手段＝注入）
        rate = dec.fixed[("注入.住民税.均等割の税率", injection_key("municipality", "990001", _dt.date(2026, 1, 1)))]
        self.assertIsNone(rate.value)
        self.assertEqual(len(rate.missing), 1)
        self.assertIs(rate.missing[0].means, Means.INJECTION)
        self.assertEqual(rate.missing[0].candidates, ())

    def test_injected_values_are_fixed_with_their_source(self) -> None:
        reg = fixture_registry("test_injection")
        dec = resolve_decisions(
            self.ctx([entry("住民税.級地", {"級地": "2級地"}, from_on="2025-04-01"), entry("住民税.均等割の税率", {"税率": 3500}, eid="inj-2")]),
            reg,
        )
        # 試験のモジュールが宣言した注入点だけを見る（登録済みのほかのモジュールの注入点は、この注入データでは決まらない）
        own = tuple(f"注入.{s.point}" for s in TEST_INJECTION.injections)
        self.assertEqual([s for s in dec.open if s.id.startswith(own)], [])
        kyuchi = dec.fixed[("注入.住民税.級地", injection_key("municipality", "990001", _dt.date(2025, 12, 31)))]
        self.assertEqual(kyuchi.value, {"級地": "2級地"})
        self.assertEqual(kyuchi.record_ids, ("inj-1",))
        self.assertIs(kyuchi.basis[0].type, BasisType.INJECTION)
        rate = dec.fixed[("注入.住民税.均等割の税率", injection_key("municipality", "990001", _dt.date(2026, 1, 1)))]
        self.assertEqual((rate.value, rate.missing), ({"税率": 3500}, ()))

    def test_no_window_no_slots(self) -> None:
        dec = resolve_decisions(self.ctx(None, windows=(income_tax_window(2025),)), fixture_registry("test_injection"))
        self.assertFalse(any(k[0].startswith("注入.") for k in dec.fixed))
        self.assertFalse(any(s.id.startswith("注入.") for s in dec.open))


class TestRegistryAndScope(unittest.TestCase):
    def test_registry_rejects_unknown_or_undeclared_points(self) -> None:
        from okura_core.rules import MODULES

        unknown = dataclasses.replace(TEST_INJECTION, injections=(InjectionSpec("住民税.ない注入点", lambda ctx: []),))
        with self.assertRaises(RegistryError) as e:
            build_registry(MODULES + (unknown,))
        self.assertIn("unknown_injection_point", str(e.exception))
        undeclared = dataclasses.replace(TEST_INJECTION, injections=(InjectionSpec("国保.料か税か", lambda ctx: []),))
        with self.assertRaises(RegistryError) as e:
            build_registry(MODULES + (undeclared,))
        self.assertIn("undeclared_injection_point", str(e.exception))

    def test_used_points_are_not_out_of_scope(self) -> None:
        # 登録済みのモジュールの一覧や未使用の注入点を決め打ちしない：使うかどうかは登録から求める。
        # 未使用の側も確かめるため、使う注入点を減らした登録（試験のモジュールの使う注入点だけ）でも見る。
        ir = make_ir([person("p-a")], [])
        samples = {
            "住民税.級地": {"級地": "1級地"},
            "国保.料か税か": {"賦課": "税"},
            "健保.通勤手当の扱い": {"従来の方法": "含まない"},
        }
        kinds = {"住民税": "municipality", "国保": "municipality", "健保": "insurer"}
        raw = [
            entry(p, d, eid=f"inj-{i}", kind=kinds[p.split(".")[0]], code="990001" if p[:2] != "健保" else "ins-1")
            for i, (p, d) in enumerate(samples.items())
        ]
        inj, problems = parse_injected(raw)
        self.assertEqual(problems, [])
        assert inj is not None
        from okura_core.rules import MODULES

        # 実のモジュールの注入点を外した登録（試験のモジュールの注入点だけを使う）
        only_fixture = build_registry(tuple(dataclasses.replace(m, injections=()) for m in MODULES) + (TEST_INJECTION,))
        for reg in (fixture_registry("test_injection"), only_fixture):
            with self.subTest(used=sorted(reg.used_injection_points)):
                scope = input_scope(ir, inj.entries, reg)
                injected_items = {i.target["record_id"] for i in scope.items if i.target.get("section") == "injected"}
                expected = {e.id for e in inj.entries if e.point not in reg.used_injection_points}
                self.assertEqual(injected_items, expected)  # 使う注入点は対象外にせず、使わない注入点だけを対象外にする
        self.assertIn("住民税.級地", only_fixture.used_injection_points)
        self.assertNotIn("国保.料か税か", only_fixture.used_injection_points)

    def test_concept_dictionary_checks_injection_data(self) -> None:
        structure, files = read_files()
        f = files["rules/juminzei/concepts.yaml"]
        concepts = [dict(c) for c in f["概念"]]
        concepts[0] = {**concepts[0], "注入データ": ["住民税.ない注入点"]}
        concepts[1] = {**concepts[1], "注入データ": ["健保.通勤手当の扱い"]}  # 住民税は健保に依存してよい制度でない
        d = parse_dictionary(structure, {**files, "rules/juminzei/concepts.yaml": {**f, "概念": concepts}})
        found = {p.code for p in check_dictionary(d)}
        self.assertIn("unknown_injection_point", found)
        self.assertIn("injection_institution", found)
        self.assertEqual(check_dictionary(load_dictionary()), [])


if __name__ == "__main__":
    unittest.main()

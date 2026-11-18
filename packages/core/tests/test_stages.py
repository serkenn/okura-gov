"""段階評価（D23 K1）・人をまたぐ関係の窓口・候補の評価の強化・モジュールの窓口（packages/core/README.md §5・§10）。

テストの道具の規則モジュール（tests/fixture_modules.py。法令の規則ではない）で、evaluate を通して確かめる。
テストのデータは架空の家庭だけ。
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import unittest

from okura_core import candidates, evaluate
from okura_core.concepts import check_variables
from okura_core.candidates import Candidate, Policy, Slot
from okura_core.money import YenRange
from okura_core.registry import RegistryError, RoundingSlotSpec, RuleModule, StageSpec, build_registry
from okura_core.relations import RelationView
from okura_core.result import Count, Flag, Means, State, TimeKey, YenAmount, check_result_json
from okura_core.rules import MODULES

from .fixture_modules import (
    FIXTURES,
    TEST_CYCLE,
    TEST_MISDECLARED,
    TEST_MONOTONE,
    TEST_PARTS,
    TEST_PARTS_CROSS,
    TEST_STAGES,
    TEST_WINDOWS,
    V_WAGE,
    YEARLY_RULE,
    fixture_system,
)
from .support import make_ir, make_query, person, salary
from .test_architecture import variable_infos

T26 = TimeKey("tax_year", 2026)


def _ok(res):
    if not res.ok:
        raise AssertionError(res.to_dict())
    problems = check_result_json(res.to_dict())
    if problems:
        raise AssertionError(problems)
    return res


def _marriage(rid: str, a: str, b: str, *, mark: str | None = None, frm: str = "2020-04-01") -> dict:
    rec = {"id": rid, "kind": "marriage", "roles": {"spouse_a": a, "spouse_b": b}, "when": {"from_on": frm}}
    if mark is not None:
        rec["mark"] = mark
    return rec


def _seikei(jid: str, head: str, other: str, value: bool, *, mark: str | None = None) -> dict:
    j = {
        "id": jid,
        "kind": "判断.生計を一にする",
        "judged_by": {"person": head},
        "judged_at": "2026-08-01T10:00:00+09:00",
        "subject": {"person": head, "other_person": other},
        "when": {"from_on": "2026-01-01"},
        "value": value,
    }
    if mark is not None:
        j["mark"] = mark
    return j


def _windfall(rid: str, p: str, amount: int) -> dict:
    return {
        "id": rid,
        "kind": "windfall_receipt",
        "roles": {"recipient": p},
        "when": {"on": "2026-07-01"},
        "amounts": {"amount": amount},
        "attributes": {"reason": "prize"},
    }


def _related(jid: str, rid: str, value: bool) -> dict:
    return {
        "id": jid,
        "kind": "判断.業務関連性",
        "judged_by": {"label": "架空の判断者"},
        "judged_at": "2026-08-01T10:00:00+09:00",
        "subject": {"record_id": rid},
        "value": value,
    }


class TestStagePlan(unittest.TestCase):
    """段の順序は宣言から決まる。循環は登録の時点で止める。"""

    def test_order_comes_from_declared_dependencies(self) -> None:
        reg = fixture_system("test_stages").registry
        # 登録済みのモジュールの段（扶養の割当てなど）も同じ計算の回に入るので、道具の段だけを見る
        ranks = [[s.name for s in r if s.name.startswith("試験_")] for r in reg.stages.ranks]
        ranks = [r for r in ranks if r]
        self.assertEqual(len(ranks), 2)
        self.assertIn("試験_相手の給与", ranks[0])
        self.assertEqual(ranks[1], ["試験_二段目"])  # 宣言の順は二段目が先だが、依存で後ろへ
        self.assertGreaterEqual(reg.stages.rounds, 2)

    def test_cycle_is_detected_and_stopped(self) -> None:
        with self.assertRaises(RegistryError) as cm:
            build_registry(MODULES + (TEST_CYCLE,))
        self.assertEqual({p.code for p in cm.exception.problems}, {"stage_cycle"})

    def test_stage_fixtures_pass_the_structural_checks(self) -> None:
        for name in ("test_stages", "test_parts", "test_monotone", "test_windows"):
            with self.subTest(fixture=name):
                sys_ = fixture_system(name)
                self.assertEqual(check_variables(sys_.registry.dictionary, variable_infos(sys_)), [])



class TestStageDeclarationProblems(unittest.TestCase):
    def _err(self, *modules: RuleModule) -> set[str]:
        with self.assertRaises(RegistryError) as cm:
            build_registry(MODULES + modules)
        return {p.code for p in cm.exception.problems}

    def test_write_must_be_an_own_input_variable(self) -> None:
        spec = dataclasses.replace(TEST_STAGES.stages[0], writes=("所得税_試験_段階の控除",))
        codes = self._err(dataclasses.replace(TEST_STAGES, stages=(spec,) + TEST_STAGES.stages[1:]))
        self.assertIn("stage_write", codes)

    def test_written_variable_needs_the_concept_declaration(self) -> None:
        spec = dataclasses.replace(TEST_STAGES.stages[1], name="試験_別の名前")
        codes = self._err(dataclasses.replace(TEST_STAGES, stages=(TEST_STAGES.stages[0], spec, *TEST_STAGES.stages[2:])))
        self.assertIn("stage_concept", codes)

    def test_read_must_exist(self) -> None:
        spec = dataclasses.replace(TEST_STAGES.stages[1], reads=("所得税_試験_ない変数",))
        codes = self._err(dataclasses.replace(TEST_STAGES, stages=(TEST_STAGES.stages[0], spec, *TEST_STAGES.stages[2:])))
        self.assertIn("stage_read", codes)

    def test_group_stage_and_group_builder_conflict(self) -> None:
        module = dataclasses.replace(TEST_STAGES, groups={"法律婚一覧": lambda ctx: ()})
        self.assertIn("stage_group", self._err(module))




class TestRelationView(unittest.TestCase):
    def setUp(self) -> None:
        self.ir = make_ir(
            [person("p-a"), person("p-b"), person("p-c"), person("p-d")],
            [],
            relations=[
                _marriage("m-1", "p-a", "p-b"),
                {"id": "c-1", "kind": "parentage", "roles": {"parent": "p-a", "child": "p-c"}, "when": {"on": "2010-05-05"}, "attributes": {"basis": "birth_mother"}},
                {"id": "c-2", "kind": "parentage", "roles": {"parent": "p-b", "child": "p-c"}, "when": {"on": "2010-05-05"}, "attributes": {"basis": "birth_in_marriage"}},
                {"id": "co-1", "kind": "cohabitation", "roles": {"person": "p-a", "other_person": "p-d"}, "when": {"from_on": "2026-02-01", "to_on": "2026-03-31"}},
            ],
            judgments=[_seikei("j-1", "p-a", "p-c", True), _seikei("j-2", "p-a", "p-d", False)],
        )

    def test_relations_of_a_person_with_intervals(self) -> None:
        view = RelationView(self.ir)
        on = dt.date(2026, 12, 31)
        self.assertEqual({r.other for r in view.spouses("p-a", on)}, {"p-b"})
        self.assertEqual({r.other for r in view.parents("p-c", on)}, {"p-a", "p-b"})
        self.assertEqual({r.other for r in view.children("p-a", on)}, {"p-c"})
        self.assertEqual(view.between("p-a", "p-d", ("cohabitation",), on=dt.date(2026, 3, 1))[0].record_id, "co-1")
        self.assertEqual(view.between("p-a", "p-d", ("cohabitation",), on=dt.date(2026, 4, 1)), ())
        self.assertEqual(view.of("p-a", ("cohabitation",), overlaps=(dt.date(2026, 3, 15), dt.date(2026, 5, 1)))[0].record_id, "co-1")

    def test_one_person_can_be_the_dependent_of_two_people(self) -> None:
        """同じ子を夫婦の両方が持つ：グループではなく関係の窓口で引ける（所得金額調整控除の第1項の「有する」）。"""
        view = RelationView(self.ir)
        on = dt.date(2026, 12, 31)
        self.assertEqual({p.person for p in view.kin("p-a", on)}, {"p-b", "p-c"})
        self.assertEqual({p.person for p in view.kin("p-b", on)}, {"p-a", "p-c"})
        self.assertEqual({p.person for p in view.kin("p-c", on)}, {"p-a", "p-b"})

    def test_kin_path_gives_the_shortest_hops(self) -> None:
        view = RelationView(self.ir)
        paths = {p.person: p for p in view.kin("p-c", dt.date(2026, 12, 31))}
        self.assertEqual(paths["p-a"].hops, 1)

    def test_judgments_window(self) -> None:
        view = RelationView(self.ir)
        self.assertEqual([j["id"] for j in view.judgments("判断.生計を一にする", "p-a", "p-c", on=dt.date(2026, 6, 1))], ["j-1"])
        self.assertEqual([j["id"] for j in view.judgments("判断.生計を一にする", "p-c", "p-a")], ["j-1"])  # 両方の向き
        self.assertEqual({j["id"] for j in view.judgments("判断.生計を一にする", "p-a")}, {"j-1", "j-2"})




class TestMonotone(unittest.TestCase):
    """単調な判断の両端評価（D21 R6）。"""

    def setUp(self) -> None:
        self.sys = fixture_system("test_monotone")





    def test_merge_policy_tool(self) -> None:
        s = Slot("u", Means.JUDGMENT, {}, (Candidate(0, "true"), Candidate(1, "false")), Policy.MONOTONE)
        m = candidates.merge([s], [({"u": s.candidates[0]}, 10), ({"u": s.candidates[1]}, 0)], amount=True)
        self.assertEqual(m.value, YenRange(0, 10))
        m2 = candidates.merge([s], [({"u": s.candidates[0]}, True), ({"u": s.candidates[1]}, False)], amount=False)
        self.assertIsNone(m2.value)
        assert m2.undetermined is not None
        self.assertEqual([x.id for x in m2.undetermined.splits], ["u"])


class TestModuleWindows(unittest.TestCase):
    """build_inputs の窓口（パラメータ・端数の候補・提出日・段の値）、種類より細かい record_kinds、年分別の根拠。"""

    def setUp(self) -> None:
        self.sys = fixture_system("test_windows")






    def _reg_without_whole_filed_document(self):
        # 道具の宣言（書類の種別で絞る）だけを見るために、種類の全部を使う宣言を外した登録の一覧を作る
        real = tuple(dataclasses.replace(m, record_kinds=frozenset(k for k in m.record_kinds if k != "filed_document")) for m in MODULES)
        return build_registry(real + (TEST_WINDOWS,))

    def test_record_kind_finer_than_the_kind(self) -> None:
        reg = self._reg_without_whole_filed_document()
        used = {"id": "d-1", "kind": "filed_document", "attributes": {"document_type": "final_return"}}
        # resident_tax_return は 2026-11-12 から juminzei が使う（JM-32・JM-33）。どのモジュールも使わない種別で確かめる
        unused = {"id": "d-2", "kind": "filed_document", "attributes": {"document_type": "basic_deduction_declaration"}}
        self.assertTrue(reg.uses_record(used))
        self.assertFalse(reg.uses_record(unused))
        self.assertIn("filed_document", reg.used_record_kinds)



class TestRoundingSpecWithoutVariable(unittest.TestCase):
    def test_module_without_a_rounding_variable_is_registered(self) -> None:
        spec = RoundingSlotSpec(name="試験_変数なし", variable=None, title="試験")
        module = RuleModule(name="test_windows", title="試験", directory=FIXTURES / "test_windows", variables=TEST_WINDOWS.variables, build_inputs=TEST_WINDOWS.build_inputs, roundings=(spec,), stages=TEST_WINDOWS.stages)
        self.assertIsNotNone(build_registry(MODULES + (module,)))


if __name__ == "__main__":
    unittest.main()

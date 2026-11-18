"""規則モジュールの登録（registry.py・rules/）と、状態の伝搬・対象外の検出の共通の部分（scope.py）。

- 共有のファイルを触らずに、テストの道具のモジュールを登録して評価できる（tests/fixture_modules.py）。
- 登録の一覧と概念辞書の食い違いを止める。仮置きの変数（未実装の概念）の扱い。
- 状態の伝搬（D21 R2）：予測・見積り・計画の印のついた判断に依存する値に状態が付く（トレースの依存に沿って）。
- レビューの指摘：生存していない人の扱い、所得に関係しない記録で合計所得金額を止めないこと、中間表現の項目の数の上限。
テストのデータは架空の家庭だけ。
"""

from __future__ import annotations

import dataclasses
import unittest

from okura_core import evaluate
from okura_core.concepts import load_dictionary
from okura_core.registry import RegistryError, RuleModule, build_registry, default_registry
from okura_core.result import EvaluationFailure, Flag, OutOfScopeCategory, State, TimeKey, YenAmount, check_result_json
from okura_core.rules import MODULES
from okura_core.scope import MAX_PERSONS, MAX_RECORDS

from .fixture_modules import TEST_DECISIONS, fixture_system
from .support import make_ir, make_query, person, salary, system
from .test_candidates import _seikei

T26 = TimeKey("tax_year", 2026)
T25 = TimeKey("tax_year", 2025)


def _ok(res):
    if not res.ok:
        raise AssertionError(res.to_dict())
    problems = check_result_json(res.to_dict())
    if problems:
        raise AssertionError(problems)
    return res


class TestRegistration(unittest.TestCase):
    def test_registered_modules_and_concept_owners(self) -> None:
        reg = default_registry()
        # 並行の担当がモジュールを登録しても直さずに済むように、今あるものを含むことだけを確かめる（並びは test_architecture_modules）
        self.assertLessEqual({"kyuyo", "income_totals", "personal_deductions"}, {m.name for m in reg.modules})
        d = reg.dictionary
        owners = {c.module for c in d.concepts if c.module}
        self.assertLessEqual({"kyuyo", "income_kinds", "income_totals", "personal_deductions", "other_deductions", "tax"}, owners)
        for c in d.concepts:
            if c.implemented and c.module:
                self.assertIn(c.module, [m.name for m in reg.modules], c.id)

    def test_placeholders_are_input_variables_for_unimplemented_concepts(self) -> None:
        sys_ = system()
        reg = sys_.registry
        d = reg.dictionary
        for c in d.concepts:  # 辞書から決める（特定の未実装の概念の名前に結びつけない）
            for v in c.variables:
                with self.subTest(concept=c.id):
                    if c.implemented or c.module is None:
                        self.assertNotIn(v, sys_.placeholder_variables)
                    elif c.entity in {"人物", "扶養所属", "法律婚", "健康保険"}:
                        self.assertIn(v, sys_.placeholder_variables)
        self.assertNotIn("所得税_給与所得", sys_.placeholder_variables)
        for name in sys_.placeholder_variables:
            with self.subTest(variable=name):
                c = reg.placeholders[name]
                self.assertFalse(c.implemented)
                self.assertFalse(sys_.variables[name].formulas)
        # エンティティがまだない概念・変数のない概念（グループ）は仮置きにしない
        self.assertNotIn("所得税_扶養の割当て", sys_.variables)


    def test_registry_rejects_mismatches(self) -> None:
        # 変数の担当が違う（kyuyo の変数を別のモジュールに入れる）
        kyuyo = MODULES[0]
        wrong = dataclasses.replace(TEST_DECISIONS, variables=TEST_DECISIONS.variables + (kyuyo.variables[0],))
        with self.assertRaises(RegistryError) as cm:
            build_registry(MODULES + (wrong,))
        self.assertIn("duplicate_variable", {p.code for p in cm.exception.problems})
        # 実装済みの概念の担当のモジュールが登録されていない
        with self.assertRaises(RegistryError) as cm:
            build_registry(MODULES[:1])
        self.assertIn("implemented_not_registered", {p.code for p in cm.exception.problems})
        # ディレクトリの名前とモジュールの名前が違う
        renamed = dataclasses.replace(TEST_DECISIONS, name="other_name")
        with self.assertRaises(Exception):
            build_registry(MODULES + (renamed,))

    def test_module_concept_files_declare_their_owner(self) -> None:
        d = load_dictionary()
        for c in d.concepts:
            if c.module is not None:
                self.assertEqual(c.source_file, f"rules/{c.module}/concepts.yaml")
        self.assertIsInstance(MODULES[0], RuleModule)




class TestScopeReviewFixes(unittest.TestCase):



    def test_aggregation_point_does_not_silently_drop_other_income(self) -> None:
        """合計所得金額は、集めない所得（事業所得など）がその人で0と言えなければ対象外（使わない記録の検出とは別の守り）。"""
        reg = default_registry()
        from okura_core.evaluate import _coverage, _zero_index

        # 賃料の受取：不動産所得の金額（未実装の間）の材料。未実装のときは合計所得金額を対象外にする
        ir = make_ir([person("p-a")], [{"id": "w-1", "kind": "rent_flow", "roles": {"recipient": "p-a"},
                                        "when": {"on": "2026-04-01"}, "amounts": {"amount": 600_000},
                                        "attributes": {"flow_type": "rent"}}])
        found = _coverage(reg, lambda v: [0], ["p-a"], _zero_index(reg, ir, 2026))
        reasons = found.get(("所得税_合計所得金額", "p-a"), [])
        # 集める先に合計所得金額を書いた未実装の概念で、材料（rent_flow）がこの人にあるもの（並行の担当が実装したら空になってよい）
        expected = {
            k.id for k in reg.dictionary.concepts
            if "所得税.合計所得金額" in k.collected_by and not k.implemented and k.unimplemented is not None
            and "rent_flow" in k.unimplemented.zero_record_kinds
        }
        self.assertEqual({k for k in expected if any(k in r.reason for r in reasons)}, expected)
        self.assertEqual(_coverage(reg, lambda v: [0], ["p-a"], _zero_index(reg, make_ir([person("p-a")], []), 2026)), {})



if __name__ == "__main__":
    unittest.main()

"""構造の検査（SCOPE §6・§7、packages/core/README.md §10）：規則モジュールの登録の仕組み。

(f) rules/ の下の各モジュールのディレクトリに README.md・__init__.py・concepts.yaml がある。登録したモジュールは MODULE を持ち、
    名前がディレクトリと同じ。概念辞書の概念の担当はファイルの置き場所と同じ。
(g) モジュールどうしが直接 import しない（つながりは概念辞書の変数名だけ）。共有のファイル（evaluate.py など）は個別のモジュールを
    import しない（登録の一覧 rules/__init__.py を通す）。
(h) パラメータの葉は、そのパラメータを持つモジュールが担当する概念に宣言されている（ほかのモジュールの木に置かない）。
(i) テストの道具のモジュール（tests/fixture_modules.py）を足した TaxBenefitSystem でも、変数と辞書の対応・式の依存の検査が働く。
(j) 概念辞書の新しい項目（期間・値の型・担当・未実装のとき・集める先）の矛盾を検査の道具が見つけること（作った違反で）。
"""

from __future__ import annotations

import ast
import copy
import re
import unittest
from typing import Any

from okura_core.concepts import (
    RULES_DIR,
    VariableInfo,
    check_dictionary,
    check_edges,
    check_group_uses,
    check_variables,
    load_dictionary,
    parse_dictionary,
)
from okura_core.country import parameter_dirs
from okura_core.registry import default_registry

from .fixture_modules import fixture_system
from .support import CORE_SRC, system
from .test_architecture import _REF, _concept, _mini, parameter_leaves, static_graph, variable_infos

MODULE_DIRS = sorted(p for p in RULES_DIR.iterdir() if p.is_dir() and not p.name.startswith(("_", ".")))
REGISTERED = [m.name for m in default_registry().modules]
SKELETONS = ("income_kinds", "income_totals", "personal_deductions", "other_deductions", "tax")


class TestModuleLayout(unittest.TestCase):
    def test_every_module_directory_has_the_files(self) -> None:
        names = [p.name for p in MODULE_DIRS]
        for name in ("kyuyo",) + SKELETONS:
            self.assertIn(name, names)
        for d in MODULE_DIRS:
            with self.subTest(module=d.name):
                for f in ("README.md", "__init__.py", "concepts.yaml"):
                    self.assertTrue((d / f).is_file(), f)
                text = (d / "concepts.yaml").read_text(encoding="utf-8")
                self.assertRegex(text, rf"(?m)^担当: {d.name}$")
                self.assertIsNone(re.search(r"(^|[\s:\[{,-])!", text), "YAML にタグを書かない")

    def test_registered_modules_match_directories(self) -> None:
        for m in default_registry().modules:
            with self.subTest(module=m.name):
                self.assertEqual(m.directory, RULES_DIR / m.name)
        # 登録の一覧の書き方：1モジュール1行（`from .<名前> import MODULE as <名前>`）
        text = (RULES_DIR / "__init__.py").read_text(encoding="utf-8")
        lines = re.findall(r"(?m)^from \.(\w+) import MODULE as (\w+)", text)
        self.assertEqual([a for a, b in lines], REGISTERED)
        self.assertTrue(all(a == b for a, b in lines))

    def test_concept_owner_is_the_file_location(self) -> None:
        d = load_dictionary()
        for c in d.concepts:
            if c.source_file.startswith("rules/"):
                self.assertEqual(c.module, c.source_file.split("/")[1], c.id)
            else:
                self.assertIsNone(c.module, c.id)


def _imports(path: Any) -> list[tuple[int, str | None, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            out.append((node.level, node.module, node.lineno))
        elif isinstance(node, ast.Import):
            for a in node.names:
                out.append((0, a.name, node.lineno))
    return out


class TestModuleIsolation(unittest.TestCase):
    def test_modules_do_not_import_each_other(self) -> None:
        for d in MODULE_DIRS:
            for path in sorted(d.rglob("*.py")):
                for level, module, line in _imports(path):
                    with self.subTest(file=path.relative_to(CORE_SRC).as_posix(), line=line):
                        if level == 0:
                            self.assertFalse((module or "").startswith("okura_core.rules"), module)
                            continue
                        depth = len(path.relative_to(RULES_DIR).parts) - 1  # rules/<m>/x.py → 1
                        if level > depth:  # rules の外か、rules/__init__ へ上がる
                            up = level - depth  # 1 なら rules パッケージ、2 なら okura_core
                            self.assertNotEqual(up, 1, f"ほかのモジュールを import している: {'.' * level}{module}")

    def test_shared_files_do_not_import_individual_modules(self) -> None:
        for path in sorted(CORE_SRC.rglob("*.py")):
            rel = path.relative_to(CORE_SRC)
            if rel.parts[0] == "rules":
                continue
            for level, module, line in _imports(path):
                with self.subTest(file=rel.as_posix(), line=line):
                    name = module or ""
                    self.assertFalse(re.match(r"^(okura_core\.)?rules\.", name) and level in (0, 1), name)
                    if level >= 1:
                        self.assertFalse(name.startswith("rules."), name)


class TestParameterOwnership(unittest.TestCase):
    def test_parameter_leaves_belong_to_the_module_that_holds_them(self) -> None:
        d = load_dictionary()
        sys_ = system()
        leaves = [leaf.name for leaf in parameter_leaves(sys_.parameters)]
        owners = {}
        for pdir in parameter_dirs():
            module = pdir.parent.name
            for f in pdir.rglob("*.yaml"):
                if f.stem == "index":
                    continue
                prefix = ".".join(f.relative_to(pdir).with_suffix("").parts)
                owners[prefix] = module
        for leaf in leaves:
            with self.subTest(parameter=leaf):
                module = next(m for p, m in owners.items() if leaf == p or leaf.startswith(p + "."))
                claimed = [c for c in d.concepts if any(leaf == x or leaf.startswith(x + ".") for x in c.parameters)]
                self.assertTrue(claimed)
                self.assertTrue(all(c.module == module for c in claimed), [(c.id, c.module, module) for c in claimed])


class TestFixtureModulesAreChecked(unittest.TestCase):
    """足したモジュールにも、同じ構造の検査が働く。"""

    def test_fixture_system_passes_the_structural_checks(self) -> None:
        sys_ = fixture_system("test_decisions", "test_rounding")
        d = sys_.registry.dictionary
        self.assertEqual(check_dictionary(d), [])
        self.assertEqual(check_variables(d, variable_infos(sys_)), [])
        g = static_graph(sys_)
        self.assertEqual(list(g.problems), [])
        self.assertEqual(check_edges(d, g.edges), [])
        self.assertIn(("所得税_試験_扶養の目安", "所得税_扶養親族の合計所得金額要件"), {(e.source, e.target) for e in g.edges})

    def test_group_and_coverage_fixtures_pass_the_structural_checks(self) -> None:
        """グループの組み方と人をまたぐ依存（test_groups）・対象外の伝わり方（test_coverage）の道具も同じ検査を通る。"""
        sys_ = fixture_system("test_groups", "test_coverage")
        d = sys_.registry.dictionary
        self.assertEqual(check_dictionary(d), [])
        self.assertEqual(check_variables(d, variable_infos(sys_)), [])
        g = static_graph(sys_)
        self.assertEqual(list(g.problems), [])
        self.assertEqual(check_edges(d, g.edges), [])
        self.assertEqual(check_group_uses(d, g.group_uses), [])
        edge = {(e.source, e.target): e for e in g.edges}[("所得税_試験_相手の合計所得金額", "所得税_合計所得金額")]
        self.assertTrue(edge.cross_person)  # 人.法律婚.sum(人("…")) は人をまたぐ
        self.assertLessEqual({("所得税_試験_相手の合計所得金額", "法律婚"), ("所得税_試験_法律婚の人数", "法律婚")},
                             {(u.variable, u.group) for u in g.group_uses})

    def test_variable_in_the_wrong_module_is_found(self) -> None:
        sys_ = fixture_system("test_decisions")
        infos = [
            VariableInfo(i.name, i.entity, i.is_person, i.has_formula, i.period, i.value_type, i.placeholder,
                         "kyuyo" if i.name == "所得税_試験_扶養の目安" else i.module)
            for i in variable_infos(sys_)
        ]
        self.assertIn("module_mismatch", {p.code for p in check_variables(sys_.registry.dictionary, infos)})
        infos = [
            VariableInfo(i.name, i.entity, i.is_person, i.has_formula, i.period, i.value_type,
                         i.placeholder or i.name == "所得税_給与所得", i.module)
            for i in variable_infos(sys_)
        ]
        self.assertIn("placeholder_for_implemented", {p.code for p in check_variables(sys_.registry.dictionary, infos)})


class TestNewDictionaryChecks(unittest.TestCase):
    def _codes(self, change) -> set[str]:
        s, f = copy.deepcopy(_mini())
        change(s, f)
        return {p.code for p in check_dictionary(parse_dictionary(s, f))}

    def test_detects(self) -> None:
        def add(c: dict[str, Any]):
            return lambda s, f: f["a.yaml"]["概念"].append(c)

        cases = {
            "period": lambda s, f: f["a.yaml"]["概念"][1].update(期間="週"),
            "value_type": lambda s, f: f["a.yaml"]["概念"][1].update(値の型="小数"),
            "collected_by": lambda s, f: f["a.yaml"]["概念"][1].update(集める先=["所得税.判定"]),
            "unimplemented": add(
                _concept("所得税.未実装", "所得の種類ごとの所得", 実装済み=False,
                         未実装のとき={"零とする記録の種類": ["no_such_kind"], "説明": "x"})
            ),
        }
        for code, change in cases.items():
            with self.subTest(code=code):
                self.assertIn(code, self._codes(change))

    def test_module_file_owner_must_match_directory(self) -> None:
        s, f = copy.deepcopy(_mini())
        f["rules/x/concepts.yaml"] = {"制度": "所得税", "担当": "y", "概念": [_concept("所得税.モジュールの", "事実")]}
        from okura_core.concepts import ConceptDictionaryError

        with self.assertRaises(ConceptDictionaryError) as cm:
            parse_dictionary(s, f)
        self.assertIn("module", {p.code for p in cm.exception.problems})
        f["rules/x/concepts.yaml"]["担当"] = "x"
        d = parse_dictionary(s, f)
        self.assertEqual(d.concept("所得税.モジュールの").module, "x")
        self.assertTrue(_REF)


if __name__ == "__main__":
    unittest.main()

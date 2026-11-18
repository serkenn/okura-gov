"""構造の検査（SCOPE §6・§7）：概念辞書と、OpenFisca の変数・式・パラメータの対応。

(a) OpenFisca の全変数が概念辞書に対応し、名前の接頭辞と制度が合う（エンティティ・期間・型・入力変数か式か も合う）。
(b) 変数の式から依存を AST で抽出し（人("…", period)、人.扶養所属("…", period) などの呼び出し、
    parameters(period).所得税.… の属性）、層の逆向き・循環・辞書に宣言のない依存（制度・人・年をまたぐものを含む）・
    集約点を通らない依存・宣言だけで使っていない依存を検出する。抽出が漏れていないことを OpenFisca のトレースと突き合わせて確かめる。
(c) すべてのパラメータの葉に metadata（reference・source_kind・適用開始日）があり、reference のファイル（と節の見出し）が実在する。
ほかに：辞書の出典のファイルと節、結果に出る ID が辞書にあること、コードに書いた変数名・パラメータ名・概念 ID が実在すること。
検査の道具（okura_core.concepts.check_*、AST の読み取り）が違反を見つけられることも、作った違反で確かめる（TestCheckersDetect）。

テストのデータは架空の人だけ（給与の額だけを持つ）。
"""

from __future__ import annotations

import ast
import copy
import datetime
import functools
import inspect
import re
import sys
import textwrap
import unittest
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openfisca_core.parameters import Parameter, ParameterNode
from openfisca_core.simulation_builder import SimulationBuilder

from okura_core.basis import INJECTION_ONLY_KINDS, ReadingFlag, SourceKind
from okura_core.concepts import (
    ConceptDictionary,
    ConceptDictionaryError,
    GroupUse,
    ParameterUse,
    VariableEdge,
    VariableInfo,
    check_dictionary,
    check_edges,
    check_group_uses,
    check_parameter_use,
    check_parameters,
    check_variables,
    load_dictionary,
    parse_dictionary,
    read_files,
    read_yaml,
)
from okura_core.country import OkuraTaxBenefitSystem
from okura_core.country.entities import ENTITIES
from okura_core.injection_points import POINTS
from okura_core.explain import period_key
from okura_core.registry import default_registry
from okura_core.result import EvaluationResult

from .support import CORE_SRC, REPO, make_ir, make_query, person, salary, system

_EVALUATE = sys.modules["okura_core.evaluate"]
#: 規則モジュールの規則の根拠（変数名 → 根拠の項目）。以前の explain.RULES。
RULES = default_registry().rules  # okura_core.evaluate は関数の名前でもあるので、モジュールは sys.modules から取る


# ---------------------------------------------------------------------------
# 式の AST から依存を読む
# ---------------------------------------------------------------------------

#: グループの集約の演算（配列を受け取る。変数名を受け取らない）。
GROUP_METHODS = frozenset(
    {
        "sum", "any", "all", "max", "min", "reduce", "nb_persons", "value_from_person", "value_nth_person",
        "value_from_first_person", "value_from_partner", "project", "has_role", "get_rank",
    }
)  # fmt: skip
#: 同じ期間とみなす period の書き方（period そのもの・その年・期間の初日）。
SAME_PERIOD_ATTRS = frozenset({"this_year", "start"})
#: グループのエンティティのキー（人.<キー>… でグループの組み方を使う）。
GROUP_KEYS = frozenset(e.key for e in ENTITIES if not e.is_person)


@dataclass(frozen=True)
class FormulaRef:
    target: str
    cross_person: bool
    cross_year: bool
    line: int


@dataclass
class FormulaReading:
    """1つの式から読んだもの。param_paths の None は、parameters(...) を属性でたどらずに丸ごと使ったこと（トレースで確かめる）。"""

    refs: list[FormulaRef] = field(default_factory=list)
    param_paths: list[tuple[str | None, bool, int]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    groups: set[str] = field(default_factory=set)  # 組み方（役割・所属）を使ったグループのエンティティのキー


def _base(node: ast.AST) -> tuple[ast.AST, list[str]]:
    attrs: list[str] = []
    while isinstance(node, ast.Attribute):
        attrs.append(node.attr)
        node = node.value
    return node, list(reversed(attrs))


class _FormulaReader(ast.NodeVisitor):
    def __init__(self, ent: str, per: str, par: str | None, where: str) -> None:
        self.ent, self.per, self.par, self.where = ent, per, par, where
        self.out = FormulaReading()
        self._consumed_param_calls: set[int] = set()
        self._through_group = 0  # グループの集約の演算（人.<グループ>.sum(…) など）の引数の中か
        # 2026-11-13：エンティティから引いた値（人の配列）を入れた局所の名前。グループの集約の引数に渡すと、引数の外で引いた値が
        # ほかの人の値として読まれる（人をまたぐ依存）のに、引いた所では同じ人の読み方に見える。集約の引数の中で引かせる
        self._person_arrays: set[str] = set()

    def _same(self, expr: ast.AST | None) -> bool:
        if isinstance(expr, ast.Name):
            return expr.id == self.per
        if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name):
            return expr.value.id == self.per and expr.attr in SAME_PERIOD_ATTRS
        return False

    def _problem(self, node: ast.AST, message: str) -> None:
        self.out.problems.append(f"{self.where}:{getattr(node, 'lineno', '?')}: {message}")

    def visit_Call(self, node: ast.Call) -> None:
        base, attrs = _base(node.func)
        if isinstance(base, ast.Name) and base.id == self.ent:
            first = node.args[0] if node.args else None
            rest: list[ast.AST] = list(node.args[1:])
            through_group = False
            if attrs and attrs[0] in GROUP_KEYS:
                self.out.groups.add(attrs[0])
            elif attrs and attrs != ["has_role"]:
                # 2026-11-13：人をまたぐ読み方は、必ずグループ（エンティティのキー）を通す。evaluate は、値に由来を付けるグループを
                # 概念辞書の宣言したグループだけにし（evaluate.attached_groups）、本人についてだけ読む変数をほかの人の分まで依存に
                # 数えない（_Closure.crossed）。どちらも「人をまたぐ読み方は静的に読めて、宣言がある」ことに拠る
                self._problem(node, "エンティティの属性を通した読み方が <グループ> で始まっていない（使うグループを静的に読めない）")
            if attrs == ["has_role"] and first is not None:
                role_base, _ = _base(first)
                if isinstance(role_base, ast.Name) and role_base.id in GROUP_KEYS:
                    self.out.groups.add(role_base.id)
                else:
                    self._problem(node, "has_role の役割を <グループ>.<役割> の形で書いていない（使うグループを静的に読めない）")
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                period = node.args[1] if len(node.args) > 1 else next((k.value for k in node.keywords if k.arg == "period"), None)
                cross = bool(attrs) or self._through_group > 0
                self.out.refs.append(FormulaRef(first.value, cross, not self._same(period), node.lineno))
            elif attrs and attrs[-1] in GROUP_METHODS:
                rest = list(node.args)  # 配列を受け取る集約の演算。引数の中の呼び出しを読む
                # 人.<グループ>.sum(人("…", period)) のように、グループを通した集約に渡した人の配列は、ほかの人の値（人をまたぐ依存）
                through_group = len(attrs) >= 2
            else:
                self._problem(node, "変数名が文字列の定数でない呼び出し（依存を静的に読めない）")
                rest = list(node.args)
            self._through_group += 1 if through_group else 0
            for a in rest:
                self.visit(a)
            for k in node.keywords:
                self.visit(k.value)
            self._through_group -= 1 if through_group else 0
            return
        if self.par is not None and isinstance(base, ast.Name) and base.id == self.par and not attrs:
            if id(node) not in self._consumed_param_calls:
                self.out.param_paths.append((None, not self._same(node.args[0] if node.args else None), node.lineno))
            for a in node.args:
                self.visit(a)
            return
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        base, attrs = _base(node)
        if isinstance(base, ast.Call) and self.par is not None:
            inner, inner_attrs = _base(base.func)
            if isinstance(inner, ast.Name) and inner.id == self.par and not inner_attrs:
                self._consumed_param_calls.add(id(base))
                self.out.param_paths.append((".".join(attrs), not self._same(base.args[0] if base.args else None), node.lineno))
                for a in base.args:
                    self.visit(a)
                return
        if isinstance(base, ast.Name) and base.id == self.ent:
            self._problem(node, "エンティティを呼び出し以外で使っている（別名・受け渡しは依存を静的に読めない）")
            return
        self.generic_visit(node)

    def _from_entity(self, expr: ast.AST) -> bool:
        """式が、エンティティから引いた値（人(…)・人.<グループ>…(…)）か、それを入れた局所の名前を含むか。"""
        for n in ast.walk(expr):
            if isinstance(n, ast.Name) and (n.id == self.ent or n.id in self._person_arrays):
                return True
        return False

    def _bind(self, targets: Iterable[ast.AST], value: ast.AST | None) -> None:
        if value is None or not self._from_entity(value):
            return
        for t in targets:
            for n in ast.walk(t):
                if isinstance(n, ast.Name):
                    self._person_arrays.add(n.id)

    def visit_Assign(self, node: ast.Assign) -> None:
        self.generic_visit(node)
        self._bind(node.targets, node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self.generic_visit(node)
        self._bind([node.target], node.value)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.generic_visit(node)
        self._bind([node.target], node.value)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.generic_visit(node)
        self._bind([node.target], node.value)

    def visit_For(self, node: ast.For) -> None:
        self._bind([node.target], node.iter)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if self._through_group > 0 and isinstance(node.ctx, ast.Load) and node.id in self._person_arrays:
            self._problem(
                node,
                f"グループの集約の引数に、引数の外でエンティティから引いた値 {node.id} を渡している"
                "（ほかの人の値として読むのに、人をまたぐ依存を静的に読めない。集約の引数の中で引く）",
            )
        if node.id == self.ent:
            self._problem(node, "エンティティを呼び出し以外で使っている（関数への受け渡しは依存を静的に読めない）")
        elif self.par is not None and node.id == self.par:
            self._problem(node, "parameters を呼び出さずに使っている（参照する時点を静的に読めない）")


def read_formula(func: Callable[..., Any], where: str) -> FormulaReading:
    """式の関数のソースを AST で読む。引数は（エンティティ, period[, parameters]）。"""
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    fn = tree.body[0]
    if not isinstance(fn, ast.FunctionDef):
        return FormulaReading(problems=[f"{where}: 式が def の関数でない"])
    names = [a.arg for a in fn.args.args]
    if len(names) < 2 or fn.args.vararg or fn.args.kwarg:
        return FormulaReading(problems=[f"{where}: 式の引数が（エンティティ, period[, parameters]）の形でない"])
    reader = _FormulaReader(names[0], names[1], names[2] if len(names) > 2 else None, where)
    for stmt in fn.body:
        reader.visit(stmt)
    return reader.out


@dataclass(frozen=True)
class StaticGraph:
    edges: tuple[VariableEdge, ...]
    parameter_uses: tuple[ParameterUse, ...]
    whole_tree: frozenset[str]  # parameters(...) を丸ごと使う変数（トレースで確かめる）
    problems: tuple[str, ...]
    group_uses: tuple[GroupUse, ...] = ()


def static_graph(sys_: OkuraTaxBenefitSystem) -> StaticGraph:
    edges: set[VariableEdge] = set()
    uses: set[ParameterUse] = set()
    whole: set[str] = set()
    problems: list[str] = []
    groups: set[GroupUse] = set()
    for name, var in sorted(sys_.variables.items()):
        for start, func in sorted(var.formulas.items()):
            r = read_formula(func, f"{name}.formula_{start}")
            problems += r.problems
            groups |= {GroupUse(name, g) for g in r.groups}
            for ref in r.refs:
                if ref.target not in sys_.variables:
                    problems.append(f"{name}:{ref.line}: 知らない変数 {ref.target}")
                    continue
                edges.add(VariableEdge(name, ref.target, ref.cross_person, ref.cross_year))
            for path, cross_year, line in r.param_paths:
                if path is None:
                    whole.add(name)
                elif not _parameter_exists(sys_.parameters, path):
                    problems.append(f"{name}:{line}: 知らないパラメータ {path}")
                else:
                    uses.add(ParameterUse(name, path, cross_year))
    return StaticGraph(
        tuple(sorted(edges, key=repr)),
        tuple(sorted(uses, key=repr)),
        frozenset(whole),
        tuple(problems),
        tuple(sorted(groups, key=repr)),
    )


# ---------------------------------------------------------------------------
# パラメータの木・トレース・docs の見出し
# ---------------------------------------------------------------------------


def parameter_leaves(node: ParameterNode) -> Iterator[Any]:
    for child in node.children.values():
        if isinstance(child, ParameterNode):
            yield from parameter_leaves(child)
        else:
            yield child


def _parameter_exists(root: ParameterNode, path: str) -> bool:
    node: Any = root
    for part in path.split("."):
        if not isinstance(node, ParameterNode) or part not in node.children:
            return False
        node = node.children[part]
    return True


#: トレースで全部の式を通すための架空の給与等の収入金額（給与所得の規定の分かれ目を全部通る）。
TRACE_WAGES = (0, 600_000, 700_000, 1_000_000, 2_192_000, 3_000_000, 5_000_000, 7_000_000, 9_000_000)
TRACE_YEARS = (2025, 2026, 2027)


@dataclass(frozen=True)
class TraceGraph:
    edges: frozenset[tuple[str, str, bool]]  # (変数, 引いた変数, 別の期間か)
    parameter_uses: frozenset[ParameterUse]
    traced: frozenset[str]


@functools.cache
def traced_graph() -> TraceGraph:
    """架空の人の状況で、式を持つ変数を全部計算し、トレースから依存とパラメータの使用を集める。"""
    sys_ = system()
    inputs = sorted(
        n for n, v in sys_.variables.items() if not v.formulas and v.entity.is_person and v.value_type is int
    )
    # 根拠のない端数の候補の名前を渡す文字列の入力（RoundingSlotSpec）には候補の名前を入れる（既定の "" では式が丸められない）
    rounding_vars = sorted({r.variable for m in sys_.registry.modules for r in m.roundings if r.variable is not None})
    persons = {
        f"p{i}": {
            **{n: {str(y): w for y in TRACE_YEARS} for n in inputs},
            **{n: {str(y): "floor" for y in TRACE_YEARS} for n in rounding_vars},
        }
        for i, w in enumerate(TRACE_WAGES)
    }
    sim = SimulationBuilder().build_from_entities(sys_, {"人物一覧": persons})
    sim.trace = True
    for y in TRACE_YEARS:
        for n, v in sorted(sys_.variables.items()):
            if v.formulas:
                sim.calculate(n, str(y))
    edges: set[tuple[str, str, bool]] = set()
    uses: set[ParameterUse] = set()
    traced: set[str] = set()
    for node in sim.tracer.browse_trace():
        traced.add(node.name)
        for child in node.children:
            edges.add((node.name, child.name, period_key(child.period) != period_key(node.period)))
        for p in node.parameters:
            uses.add(ParameterUse(node.name, p.name, str(p.period) != str(node.period.start)))
    return TraceGraph(frozenset(edges), frozenset(uses), frozenset(traced))


_HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*$")


@functools.cache
def _headings(path: str) -> tuple[str, ...]:
    text = (REPO / path).read_text(encoding="utf-8")
    return tuple(m.group(1) for line in text.splitlines() if (m := _HEADING.match(line)))


def _anchor_ends(rest: str) -> bool:
    """見出しの、節の文字列の後ろ：空か、英数字でも「.数字」（下の節）でもない文字で始まる。"""
    return rest == "" or (not (rest[0].isascii() and rest[0].isalnum()) and re.match(r"\.[0-9]", rest) is None)


def reference_problem(ref: str) -> str | None:
    """出典（ファイル#節）が実在するか。節は、見出しがその文字列で始まり、続く文字が英数字でないものがあれば実在とする。"""
    path, _, anchor = ref.partition("#")
    if not path or ".." in Path(path).parts or Path(path).is_absolute():
        return f"相対パスでない: {ref}"
    if not (REPO / path).is_file():
        return f"ファイルがない: {ref}"
    if anchor and path.endswith(".md"):
        ok = any(h.startswith(anchor) and _anchor_ends(h[len(anchor):]) for h in _headings(path))
        if not ok:
            return f"節の見出しがない: {ref}"
    return None


def variable_infos(sys_: OkuraTaxBenefitSystem) -> list[VariableInfo]:
    return [
        VariableInfo(
            name=n,
            entity=v.entity.key,
            is_person=v.entity.is_person,
            has_formula=bool(v.formulas),
            period=str(v.definition_period),
            value_type=v.value_type.__name__,
            placeholder=sys_.is_placeholder(n),
            module=sys_.registry.variable_module.get(n),
        )
        for n, v in sorted(sys_.variables.items())
    ]


def _fmt(problems: list[Any]) -> str:
    return "\n".join(str(p) for p in problems)


# ---------------------------------------------------------------------------
# (a) 変数と概念辞書の対応
# ---------------------------------------------------------------------------


class TestConceptDictionary(unittest.TestCase):
    def test_dictionary_is_consistent(self) -> None:
        d = load_dictionary()
        self.assertEqual(check_dictionary(d), [])
        self.assertGreaterEqual(len(d.concepts), 10)

    def test_dictionary_references_exist(self) -> None:
        for c in load_dictionary().concepts:
            for ref in c.references():
                with self.subTest(concept=c.id, ref=ref):
                    self.assertIsNone(reference_problem(ref))

    def test_every_variable_maps_to_a_concept(self) -> None:
        problems = check_variables(load_dictionary(), variable_infos(system()))
        self.assertEqual(problems, [], _fmt(problems))

    def test_outputs_come_from_dictionary(self) -> None:
        d = load_dictionary()
        specs = _EVALUATE.OUTPUTS
        self.assertEqual([s.concept for s in specs], [c.id for c in d.outputs()])
        for s in specs:
            with self.subTest(variable=s.variable):
                c = d.by_variable(s.variable)
                self.assertIsNotNone(c)
                assert c is not None
                self.assertEqual(c.id, s.concept)
                self.assertTrue(c.implemented)
                self.assertEqual(s.needs_complete_income, d.depends_on_all_income(c.id))
        # 依存の順（依存先が先）：evaluate は OUTPUTS の順に全員を評価する
        position = {s.variable: i for i, s in enumerate(specs)}
        for e in static_graph(system()).edges:
            if e.source in position and e.target in position:
                self.assertLess(position[e.target], position[e.source], f"{e.source} → {e.target}")
        for judgment, compared, criterion, bid, comparison in _EVALUATE.BOUNDARIES:
            self.assertIn(bid, d.ids())
            self.assertIn(judgment, position)
            self.assertIn(compared, position)
            if comparison is None:  # 基準がパラメータの葉
                self.assertTrue(_parameter_exists(system().parameters, criterion))
            else:  # 基準の概念（2026-11-11）：基準の変数も出力で、判定より先に計算する
                self.assertIn(criterion, position)
                self.assertLess(position[criterion], position[judgment])
                self.assertIn(comparison, ("以下", "未満", "超", "以上"))


    def test_rules_name_known_variables(self) -> None:
        for name, entries in RULES.items():
            with self.subTest(variable=name):
                self.assertIn(name, system().variables)
                for e in entries:
                    for ref in e.references:
                        self.assertIsNone(reference_problem(ref))
        # 年分別の規則の根拠（RuleModule.rules_by_year）と、段階の段の根拠（StageSpec.basis）も同じ
        registry = default_registry()
        by_year = [(f"{y}:{k}", es) for y, t in registry.rules_by_year.items() for k, es in t.items()]
        stages = [(s.name, s.basis) for m in registry.modules for s in m.stages]
        for name, entries in by_year + stages:
            with self.subTest(name=name):
                for e in entries:
                    for ref in e.references:
                        self.assertIsNone(reference_problem(ref))

    def test_names_written_in_code_exist(self) -> None:
        """コードに書いた変数名・パラメータ名・概念 ID の文字列が実在する（名前を変えたときの書き残しを見つける）。"""
        sys_ = system()
        d = load_dictionary()
        prefixes = tuple(i.variable_prefix for i in d.institutions)
        dotted = re.compile(r"^(" + "|".join(re.escape(i.id) for i in d.institutions) + r")\.[^\s。、（）()]+$")
        planned = {v for c in d.concepts for v in c.variables}
        for path in sorted(CORE_SRC.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                    continue
                s = node.value
                where = f"{path.relative_to(CORE_SRC).as_posix()}:{node.lineno}"
                if s.startswith(prefixes) and re.fullmatch(r"[^\s。、（）()]+", s):
                    with self.subTest(where=where, name=s):
                        self.assertIn(s, sys_.variables.keys() | planned)
                elif dotted.match(s):
                    with self.subTest(where=where, name=s):
                        # 注入点の名前（injection_points.POINTS）も ID として実在を確かめる
                        self.assertTrue(s in d.ids() or s in POINTS or _parameter_exists(sys_.parameters, s), s)


# ---------------------------------------------------------------------------
# (b) 式の依存
# ---------------------------------------------------------------------------


class TestFormulaDependencies(unittest.TestCase):
    def test_formulas_are_statically_readable(self) -> None:
        g = static_graph(system())
        self.assertEqual(list(g.problems), [])
        self.assertTrue(g.edges)

    def test_dependencies_follow_layers_and_declarations(self) -> None:
        g = static_graph(system())
        problems = check_edges(load_dictionary(), g.edges) + check_group_uses(load_dictionary(), g.group_uses)
        self.assertEqual(problems, [], _fmt(problems))

    def test_expected_chain(self) -> None:
        """今の縦の1本（README §7）：給与等の収入金額 → 給与所得 → 合計所得金額（集約点）→ 扶養親族の要件。"""
        edges = {(e.source, e.target) for e in static_graph(system()).edges}
        self.assertLessEqual(  # 並行の担当が式を足しても直さずに済むように、含むことだけを確かめる
            {
                ("所得税_給与所得", "所得税_給与等の収入金額"),
                ("所得税_合計所得金額", "所得税_給与所得"),
                ("所得税_扶養親族の合計所得金額要件", "所得税_合計所得金額"),
            },
            edges,
        )

    def test_static_reading_covers_trace(self) -> None:
        """トレースで見えた依存は、全部 AST からも読めている（読み漏れがない）。別の期間の依存は AST でも別の期間。"""
        g = static_graph(system())
        static = {(e.source, e.target): e for e in g.edges}
        t = traced_graph()
        for src, dst, other_period in sorted(t.edges):
            with self.subTest(edge=f"{src} → {dst}"):
                self.assertIn((src, dst), static)
                if other_period:
                    self.assertTrue(static[(src, dst)].cross_year)
        with_formula = {n for n, v in system().variables.items() if v.formulas}
        self.assertEqual(with_formula - t.traced, set(), "トレースで計算していない式がある（TRACE_WAGES に足す）")

    def test_parameter_use_is_declared(self) -> None:
        """式が使うパラメータ（AST で読めたもの・トレースで見えたもの）は、その変数の概念に宣言してある。"""
        d = load_dictionary()
        g = static_graph(system())
        t = traced_graph()
        self.assertTrue(g.whole_tree <= t.traced)
        problems = check_parameter_use(d, list(g.parameter_uses) + sorted(t.parameter_uses, key=repr))
        self.assertEqual(problems, [], _fmt(problems))
        used = {u.parameter for u in t.parameter_uses}
        self.assertIn("所得税.扶養親族.合計所得金額の上限", used)


# ---------------------------------------------------------------------------
# (c) パラメータのメタデータ
# ---------------------------------------------------------------------------

_REFERENCE_ROOTS = ("docs/public-sources/", "docs/measurements/", "scripts/results/")
_PRIMARY_ROOTS = ("docs/public-sources/", "docs/measurements/")
_READING_ROOTS = ("docs/hypotheses/", "docs/inferences/")


class TestParameterMetadata(unittest.TestCase):
    def test_every_leaf_has_basis_metadata(self) -> None:
        leaves = list(parameter_leaves(system().parameters))
        self.assertGreater(len(leaves), 20)
        for leaf in leaves:
            with self.subTest(parameter=leaf.name):
                self.assertIsInstance(leaf, Parameter, "未対応の葉の型（検査を足す）")
                self.assertTrue(leaf.values_list, "値がない")
                for at in leaf.values_list:
                    meta = {**leaf.metadata, **at.metadata}
                    where = f"{leaf.name}@{at.instant_str}"
                    # 適用開始日（日付のキー）
                    start = datetime.date.fromisoformat(at.instant_str)
                    if leaf.name.split(".")[0] == "所得税":
                        self.assertEqual((start.month, start.day), (1, 1), f"{where}: 所得税の適用開始日は年分の1月1日")
                    if "施行日" in meta:
                        datetime.date.fromisoformat(str(meta["施行日"]))
                    # 根拠の種類
                    self.assertIn("source_kind", meta, where)
                    kind = SourceKind.from_label(meta["source_kind"])
                    self.assertNotIn(kind, INJECTION_ONLY_KINDS, where)
                    self.assertTrue(meta.get("law"), f"{where}: law がない")
                    for f in meta.get("flags", []):
                        ReadingFlag.from_label(f)
                    # 出典
                    refs = meta.get("reference")
                    self.assertIsInstance(refs, list, f"{where}: reference がない")
                    self.assertTrue(refs, f"{where}: reference が空")
                    self.assertTrue(any(r.startswith(_PRIMARY_ROOTS) for r in refs), f"{where}: 一次情報（公開資料・実測）の出典がない")
                    for ref in refs:
                        self.assertTrue(ref.startswith(_REFERENCE_ROOTS), f"{where}: 出典の場所 {ref}")
                        self.assertIsNone(reference_problem(ref), where)
                    for ref in meta.get("reading", []):
                        self.assertTrue(ref.startswith(_READING_ROOTS), f"{where}: 読みの文書の場所 {ref}")
                        self.assertIsNone(reference_problem(ref), where)
                    self.assertNotIsInstance(at.value, float, where)

    def test_parameters_map_to_concepts(self) -> None:
        names = [leaf.name for leaf in parameter_leaves(system().parameters)]
        problems = check_parameters(load_dictionary(), names)
        self.assertEqual(problems, [], _fmt(problems))

    def test_variable_references_exist(self) -> None:
        for name, var in sorted(system().variables.items()):
            refs = var.reference if isinstance(var.reference, list) else [var.reference] if var.reference else []
            with self.subTest(variable=name):
                self.assertTrue(refs, "変数に出典（reference）がない")
                for ref in refs:
                    self.assertIsNone(reference_problem(ref))


# ---------------------------------------------------------------------------
# 検査の道具が違反を見つけること（作った違反で）
# ---------------------------------------------------------------------------

_REF = "docs/public-sources/20261109_R1-laws_income-tax.md#4"


def _concept(cid: str, layer: str, deps: list[str] | None = None, var: str | None = None, **extra: Any) -> dict[str, Any]:
    c: dict[str, Any] = {
        "id": cid,
        "名称": cid,
        "定義": {"条文": "架空", "根拠の種類": "法律", "出典": [_REF]},
        "判定の時点": {"問い": "年分", "説明": "架空", "出典": [_REF]},
        "層": layer,
        "エンティティ": "人物",
        "期間": "年",
        "値の型": "円",
        "依存する概念": deps or [],
        "変数": [var or cid.replace(".", "_")],
        "注入点": False,
        "実装済み": True,
    }
    c.update(extra)
    return c


def _mini() -> tuple[dict[str, Any], dict[str, Any]]:
    """架空の小さな辞書：所得税（事実 → 所得 → 合計〔集約点〕→ 判定）と、所得税に依存してよい住民税。"""
    structure = {
        "層": [
            {"id": "事実", "順位": 1, "説明": "x"},
            {"id": "所得の種類ごとの所得", "順位": 2, "説明": "x"},
            {"id": "中心の概念", "順位": 3, "説明": "x"},
            {"id": "人的控除・扶養の判定", "順位": 4, "説明": "x"},
        ],
        "制度": [
            {"id": "所得税", "変数の接頭辞": "所得税_", "依存してよい制度": [], "説明": "x"},
            {"id": "住民税", "変数の接頭辞": "住民税_", "依存してよい制度": ["所得税"], "説明": "x"},
        ],
    }
    files = {
        "a.yaml": {
            "制度": "所得税",
            "概念": [
                _concept("所得税.収入", "事実"),
                _concept("所得税.所得", "所得の種類ごとの所得", ["所得税.収入"]),
                _concept("所得税.合計", "中心の概念", ["所得税.所得"], 集約点="所得の種類ごとの所得"),
                _concept("所得税.判定", "人的控除・扶養の判定", ["所得税.合計"]),
            ],
        },
        "b.yaml": {
            "制度": "住民税",
            "概念": [
                _concept(
                    "住民税.合計",
                    "中心の概念",
                    制度をまたぐ依存=[{"概念": "所得税.合計", "出典": [_REF]}],
                    年をまたぐ依存=[{"概念": "所得税.合計", "時点": "前年", "出典": [_REF]}],
                ),
            ],
        },
    }
    return structure, files


_GOOD_EDGES = [
    VariableEdge("所得税_所得", "所得税_収入"),
    VariableEdge("所得税_合計", "所得税_所得"),
    VariableEdge("所得税_判定", "所得税_合計"),
    VariableEdge("住民税_合計", "所得税_合計", cross_year=True),
]


def _codes(problems: list[Any]) -> set[str]:
    return {p.code for p in problems}


def _edit(change: Callable[[dict[str, Any], dict[str, Any]], None]) -> ConceptDictionary:
    s, f = copy.deepcopy(_mini())
    change(s, f)
    return parse_dictionary(s, f)


def _concepts_of(f: dict[str, Any], name: str) -> list[dict[str, Any]]:
    return f[name]["概念"]


# 式の読み取りの検査用（AST で読むだけで、呼ばない）。
def _formula_good(人, period, parameters):  # noqa: ANN001, ANN202, N803
    上限 = parameters(period).所得税.扶養親族.合計所得金額の上限
    return 人("所得税_合計所得金額", period) <= 上限


def _formula_bad(人, period, parameters):  # noqa: ANN001, ANN202, N803
    a = 人("所得税_給与所得", period.last_year)  # 別の年
    b = 人.扶養所属("所得税_合計所得金額", period)  # ほかの人（グループ経由）
    c = 人.扶養所属.sum(人.扶養所属.members("所得税_給与所得", period))  # 集約
    name = "所得税_" + "給与所得"
    d = 人(name, period)  # 変数名が定数でない
    e = helper(人)  # エンティティの受け渡し  # noqa: F821
    f = rules(parameters(period))  # 丸ごと（トレースで確かめる）  # noqa: F821
    g = parameters(period.last_year).所得税.扶養親族.合計所得金額の上限  # 別の年のパラメータ
    return a + b + c + d + e + f + g


def _formula_group_sum(人, period, parameters):  # noqa: ANN001, ANN202, N803
    相手 = 人.法律婚.sum(人("所得税_合計所得金額", period)) - 人("所得税_給与所得", period)  # 人の配列をグループで集約
    申告者か = 人.has_role(扶養所属.申告者)  # noqa: F821  グループの役割
    return 相手 * 申告者か


class TestCheckersDetect(unittest.TestCase):
    def test_mini_dictionary_is_clean(self) -> None:
        d = parse_dictionary(*_mini())
        self.assertEqual(check_dictionary(d), [])
        self.assertEqual(check_edges(d, _GOOD_EDGES), [])

    def test_edges_against_layers_and_declarations(self) -> None:
        d = parse_dictionary(*_mini())
        cases = {
            "layer_order": [VariableEdge("所得税_所得", "所得税_判定")],
            "cycle": [VariableEdge("所得税_所得", "所得税_判定")],
            "undeclared_dependency": [VariableEdge("所得税_判定", "所得税_収入")],
            "bypass_aggregation": [VariableEdge("所得税_判定", "所得税_所得")],
            "undeclared_cross_institution": [VariableEdge("所得税_合計", "住民税_合計")],
            "direction": [VariableEdge("所得税_合計", "住民税_合計")],
            "undeclared_cross_person": [VariableEdge("所得税_判定", "所得税_合計", cross_person=True)],
            "undeclared_cross_year": [VariableEdge("所得税_判定", "所得税_合計", cross_year=True)],
        }
        for code, extra in cases.items():
            with self.subTest(code=code):
                self.assertIn(code, _codes(check_edges(d, _GOOD_EDGES + extra)))
        unused = [e for e in _GOOD_EDGES if e.source != "所得税_判定"]
        self.assertIn("unused_declaration", _codes(check_edges(d, unused)))

    def test_variables_against_dictionary(self) -> None:
        d = parse_dictionary(*_mini())
        ok = VariableInfo("所得税_所得", "人物", True, True, "year", "int")
        self.assertEqual(
            [p for p in check_variables(d, [ok]) if p.code != "implemented_but_missing"], []
        )
        cases = {
            "unregistered_variable": VariableInfo("所得税_未登録", "人物", True, True, "year", "int"),
            "variable_prefix": VariableInfo("税_所得", "人物", True, True, "year", "int"),
            "float": VariableInfo("所得税_所得", "人物", True, True, "year", "float"),
            "entity": VariableInfo("所得税_所得", "扶養所属", False, True, "year", "int"),
            "period": VariableInfo("所得税_所得", "人物", True, True, "month", "int"),
            "fact_with_formula": VariableInfo("所得税_収入", "人物", True, True, "year", "int"),
            "formula_missing": VariableInfo("所得税_所得", "人物", True, False, "year", "int"),
        }
        for code, info in cases.items():
            with self.subTest(code=code):
                self.assertIn(code, _codes(check_variables(d, [info])))
        stale = _edit(lambda s, f: _concepts_of(f, "a.yaml")[1].update(実装済み=False))
        self.assertIn("stale_not_implemented", _codes(check_variables(stale, [ok])))
        moved = _edit(lambda s, f: _concepts_of(f, "b.yaml")[0].update(変数=["所得税_住民税の合計"]))
        self.assertIn("variable_prefix", _codes(check_dictionary(moved)))

    def test_dictionary_contradictions(self) -> None:
        cases: dict[str, Callable[[dict[str, Any], dict[str, Any]], None]] = {
            "fact_with_dependencies": lambda s, f: _concepts_of(f, "a.yaml")[0].update(依存する概念=["所得税.判定"]),
            "layer_order": lambda s, f: _concepts_of(f, "a.yaml")[1].update(依存する概念=["所得税.判定"]),
            "cycle": lambda s, f: _concepts_of(f, "a.yaml")[1].update(依存する概念=["所得税.判定"]),
            "bypass_aggregation": lambda s, f: _concepts_of(f, "a.yaml")[3].update(依存する概念=["所得税.合計", "所得税.所得"]),
            "cross_institution_in_depends_on": lambda s, f: _concepts_of(f, "a.yaml")[3].update(依存する概念=["住民税.合計"]),
            "direction": lambda s, f: _concepts_of(f, "a.yaml")[3].update(
                制度をまたぐ依存=[{"概念": "住民税.合計", "出典": [_REF]}]
            ),
            "unknown_concept": lambda s, f: _concepts_of(f, "a.yaml")[3].update(依存する概念=["所得税.ない"]),
            "qualifier_not_declared": lambda s, f: _concepts_of(f, "a.yaml")[3].update(
                人をまたぐ依存=[{"概念": "所得税.収入", "出典": [_REF]}]
            ),
            "duplicate_id": lambda s, f: _concepts_of(f, "a.yaml").append(_concept("所得税.収入", "事実", var="所得税_収入2")),
            "prefix_mismatch": lambda s, f: _concepts_of(f, "a.yaml").append(_concept("住民税.紛れ", "事実", var="所得税_紛れ")),
            "reference_format": lambda s, f: _concepts_of(f, "a.yaml")[0]["定義"].update(
                出典=["docs/hypotheses/20261109_R4-modeling_entity-model.md#H1"]
            ),
            "parameter_root": lambda s, f: _concepts_of(f, "a.yaml")[1].update(パラメータ=["住民税.税率"]),
            "injection_with_parameters": lambda s, f: _concepts_of(f, "a.yaml")[1].update(注入点=True, パラメータ=["所得税.x"]),
            "aggregation_layer": lambda s, f: _concepts_of(f, "a.yaml")[1].update(集約点="人的控除・扶養の判定"),
            "unknown_question": lambda s, f: _concepts_of(f, "a.yaml")[0]["判定の時点"].update(問い="月"),
        }
        for code, change in cases.items():
            with self.subTest(code=code):
                self.assertIn(code, _codes(check_dictionary(_edit(change))))

    def test_shape_errors_and_unsafe_yaml(self) -> None:
        with self.assertRaises(ConceptDictionaryError) as cm:
            _edit(lambda s, f: _concepts_of(f, "a.yaml")[0].update(知らないキー=1))
        self.assertIn("shape", _codes(list(cm.exception.problems)))
        with self.assertRaises(ConceptDictionaryError):
            _edit(lambda s, f: _concepts_of(f, "a.yaml")[0].pop("層"))
        with self.assertRaises(ConceptDictionaryError):
            read_yaml("a: 1\na: 2\n", "dup.yaml")
        with self.assertRaises(ConceptDictionaryError):
            read_yaml("a: !!python/object/apply:builtins.len [[1, 2]]\n", "tag.yaml")

    def test_concept_files_parse_without_tags(self) -> None:
        structure, files = read_files()
        self.assertTrue(files)
        self.assertEqual(parse_dictionary(structure, files), load_dictionary())

    def test_formula_reader(self) -> None:
        good = read_formula(_formula_good, "good")
        self.assertEqual(good.problems, [])
        self.assertEqual([(r.target, r.cross_person, r.cross_year) for r in good.refs], [("所得税_合計所得金額", False, False)])
        self.assertEqual([(p, y) for p, y, _ in good.param_paths], [("所得税.扶養親族.合計所得金額の上限", False)])

        bad = read_formula(_formula_bad, "bad")
        refs = {(r.target, r.cross_person, r.cross_year) for r in bad.refs}
        self.assertIn(("所得税_給与所得", False, True), refs)
        self.assertIn(("所得税_合計所得金額", True, False), refs)
        self.assertIn(("所得税_給与所得", True, False), refs)
        self.assertEqual(bad.groups, {"扶養所属"})
        # グループを通した集約に人の配列を渡す（2026-11-11 のレビュー：以前は人をまたぐ依存として読めていなかった）
        via_sum = read_formula(_formula_group_sum, "via_sum")
        self.assertEqual(via_sum.problems, [])
        self.assertEqual({(r.target, r.cross_person) for r in via_sum.refs}, {("所得税_合計所得金額", True), ("所得税_給与所得", False)})
        self.assertEqual(via_sum.groups, {"法律婚", "扶養所属"})
        d = load_dictionary()
        self.assertIn(
            "undeclared_cross_person",
            _codes(check_edges(d, [VariableEdge("所得税_扶養親族の合計所得金額要件", "所得税_合計所得金額", cross_person=True)])),
        )
        self.assertIn("undeclared_group_use", _codes(check_group_uses(d, [GroupUse("所得税_扶養親族の合計所得金額要件", "法律婚")])))
        self.assertEqual(len(bad.problems), 2, bad.problems)  # 定数でない変数名・エンティティの受け渡し
        params = {(p, y) for p, y, _ in bad.param_paths}
        self.assertIn((None, False), params)
        self.assertIn(("所得税.扶養親族.合計所得金額の上限", True), params)
        d = load_dictionary()
        uses = [ParameterUse("所得税_扶養親族の合計所得金額要件", "所得税.扶養親族.合計所得金額の上限", True)]
        self.assertIn("undeclared_cross_year", _codes(check_parameter_use(d, uses)))
        uses = [ParameterUse("所得税_扶養親族の合計所得金額要件", "所得税.給与所得.別表第五")]
        self.assertIn("undeclared_parameter", _codes(check_parameter_use(d, uses)))
        self.assertIn("unclaimed_parameter", _codes(check_parameters(d, ["所得税.どこにもない"])))


if __name__ == "__main__":
    unittest.main()

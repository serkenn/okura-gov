"""根拠の項目（basis.BasisEntry）の項目の型の静的な検査（2026-11-12）。

rules/tax/refund.py が `detail` に文字列を渡し、結果の JSON を作るところ（BasisEntry.to_dict の dict(detail)）で止まった。
BasisEntry の __post_init__ は references・flags しか見ないので、同じ誤りがほかのモジュールにないかをソースの構文木で確かめる
（関数の中で作る項目は、その道を通る評価をしないと実行されないので、構文で見る）。あわせて、モジュールの最上位に置いた項目
（import しただけで作られるもの）が JSON にできることを確かめる。
"""

from __future__ import annotations

import ast
import importlib
import json
import pkgutil
import unittest
from typing import Any

import okura_core
from okura_core.basis import BasisEntry

from .support import CORE_SRC

#: BasisEntry のフィールドの並び（位置引数の番号 → 名前）
FIELDS = ("type", "name", "source_kind", "references", "flags", "law", "value", "instant", "effective_from", "enforced_on", "detail")
#: 文字列そのもの（dict・タプルでない）になる式の形
STRING_NODES = (ast.JoinedStr,)


def _is_string(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (str, bytes))
    if isinstance(node, STRING_NODES):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
        return _is_string(node.left)
    return False


def _detail_problem(node: ast.AST) -> str | None:
    """detail は JSON にできる Mapping か None。dict でないことが構文で分かる形を返す。"""
    if isinstance(node, ast.Constant):
        return None if node.value is None else f"定数 {type(node.value).__name__}"
    if _is_string(node):
        return "文字列"
    if isinstance(node, (ast.List, ast.Tuple, ast.Set, ast.ListComp, ast.SetComp, ast.GeneratorExp)):
        return type(node).__name__
    return None


def _sequence_problem(node: ast.AST) -> str | None:
    """references・flags はタプル。文字列・リストを渡していないか。"""
    if _is_string(node):
        return "文字列"
    if isinstance(node, (ast.List, ast.ListComp, ast.Set, ast.Dict)):
        return type(node).__name__
    return None


def _callee(node: ast.Call) -> str | None:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def scan(source: str, filename: str) -> list[str]:
    """ソース1つの BasisEntry(...)・replace(..., detail=...) の呼び出しで、型が違うと構文で分かる項目。"""
    problems: list[str] = []
    for node in ast.walk(ast.parse(source, filename)):
        if not isinstance(node, ast.Call):
            continue
        name = _callee(node)
        args: dict[str, ast.AST] = {}
        if name == "BasisEntry":
            for i, a in enumerate(node.args):
                if i < len(FIELDS):
                    args[FIELDS[i]] = a
        elif name != "replace":
            continue
        for kw in node.keywords:
            if kw.arg is not None:
                args[kw.arg] = kw.value
        where = f"{filename}:{node.lineno}"
        if "detail" in args:
            p = _detail_problem(args["detail"])
            if p is not None:
                problems.append(f"{where} detail が {p}（dict か None）")
        if name == "BasisEntry":
            for f in ("references", "flags"):
                if f in args:
                    p = _sequence_problem(args[f])
                    if p is not None:
                        problems.append(f"{where} {f} が {p}（タプル）")
    return problems


class TestBasisEntryTypes(unittest.TestCase):
    def test_scanner_finds_the_refund_mistake(self) -> None:
        # 直す前の rules/tax/refund.py の形と、似た誤り
        bad = (
            'R = BasisEntry(type=T, name="n", source_kind=S, references=("a",), detail="説明")\n'
            'R2 = BasisEntry(T, "n", S, ("a",), (), None, None, None, None, None, f"{x}")\n'
            'R3 = replace(R, detail="a" + b)\n'
            'R4 = BasisEntry(type=T, name="n", source_kind=S, references="docs/a.md#1")\n'
        )
        found = scan(bad, "bad.py")
        self.assertEqual(len(found), 4, found)
        ok = (
            'R = BasisEntry(type=T, name="n", source_kind=S, references=("a",), detail={"note": "説明"})\n'
            "R2 = BasisEntry(type=T, name=n, source_kind=S, references=refs, detail=detail or None)\n"
            "R3 = replace(R, detail=None)\n"
        )
        self.assertEqual(scan(ok, "ok.py"), [])

    def test_no_basis_entry_with_wrong_field_types_in_source(self) -> None:
        problems: list[str] = []
        files = sorted(CORE_SRC.rglob("*.py"))
        self.assertTrue(files)
        for path in files:
            problems += scan(path.read_text(encoding="utf-8"), str(path.relative_to(CORE_SRC)))
        self.assertEqual(problems, [])

    def test_module_level_entries_serialize_to_json(self) -> None:
        # import しただけで作られる項目（モジュールの最上位の定数と、そのタプル・リスト）は結果の JSON にできる
        seen = 0
        for info in pkgutil.walk_packages(okura_core.__path__, okura_core.__name__ + "."):
            if info.name.endswith((".cli", ".__main__")):
                continue
            mod = importlib.import_module(info.name)
            for attr, obj in sorted(vars(mod).items()):
                entries: list[Any] = [obj] if isinstance(obj, BasisEntry) else []
                if isinstance(obj, (tuple, list)):
                    entries = [e for e in obj if isinstance(e, BasisEntry)]
                for e in entries:
                    seen += 1
                    with self.subTest(module=info.name, attr=attr):
                        if e.detail is not None:
                            self.assertTrue(hasattr(e.detail, "keys"), f"detail が Mapping でない: {type(e.detail).__name__}")
                        json.dumps(e.to_dict(), ensure_ascii=False, allow_nan=False)
        self.assertGreater(seen, 0)


if __name__ == "__main__":
    unittest.main()

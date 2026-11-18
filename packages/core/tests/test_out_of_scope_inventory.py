"""完成の判定の道具（HANDOFF D24③：範囲内なのに未対応の「対象外」を0件にする）。各規則モジュールの README の「対象外の一覧」を読むだけの静的なテスト。

- 各 README の「対象外の一覧」の節には、行ごとの表（先頭の列がコード：KY-01 など）と、機械で数える表「### 集計」（| 分類 | 件数 | コード |）を置く。
  集計の分類は CATEGORIES のどれか。行の表のコードは集計のちょうど1つの分類に入り、集計のコードは行の表にある（数え漏れ・二重の数えを止める）。
- 分類「(c)」（範囲内なのに未対応）が1件でもあれば失敗する（test_no_unimplemented_in_scope）。
- コードの中で対象外を返す理由の定数（名前が *_REASON・REASON_*・R_*・T_* で、値が理由の文のもの）が、そのモジュールの README の
  「対象外の一覧」の節に名前で載っていることを確かめる（README に載らない対象外を作らない）。

分類（README の凡例と同じ意味）：
  (a) 範囲の外（SCOPE §4・D20）／(b) ユーザーが後の段とした（D21 R3・D22 S12・S19）／(c) 範囲内なのに未対応／
  c-入力 語彙はあり、記録・判断・選択を直せば決まる入力の不足・矛盾／c-限界 判定コアの整数（int32）の上限（共有の制約）／
  上流 ほかのモジュールの対象外に従う／一次情報なしで候補評価 一次情報（又は公表）で決まらないので候補の全部で評価する（対象外にしない）／
  実装済み／内部の誤りの検出 宣言の漏れなど判定コアの誤りを止める検出（範囲の対象外ではない）。
"""

from __future__ import annotations

import ast
import re
import unittest
from collections import Counter
from pathlib import Path

RULES = Path(__file__).resolve().parents[1] / "src" / "okura_core" / "rules"

CATEGORIES = ("(a)", "(b)", "(c)", "c-入力", "c-限界", "上流", "一次情報なしで候補評価", "実装済み", "内部の誤りの検出")
CODE = re.compile(r"^[A-Z]{2}-\d+[a-z]?$")
#: 理由の定数の名前の形。値が OpenFisca の変数名（制度の接頭辞）や短い文字列のものは理由でない（段が読む変数の名前など）。
REASON_NAME = re.compile(r"[A-Z][A-Z0-9_]*_REASON|REASON_[A-Z0-9_]+|[RT]_[A-Z0-9_]+")
VARIABLE_VALUE = re.compile(r"^(所得税|住民税|国保|健保|年金)_")


def module_dirs() -> list[Path]:
    return sorted(p for p in RULES.iterdir() if p.is_dir() and (p / "README.md").exists())


def section(readme: str) -> str:
    """README の「対象外の一覧」の節（その見出しから次の ## の見出しまで）。"""
    lines = readme.splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("## ") and "対象外の一覧" in l)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return "\n".join(lines[start:end])


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def row_codes(sec: str) -> list[str]:
    """行の表（見出しの最初の列が「コード」の表）のコード。"""
    out: list[str] = []
    in_table = False
    for line in sec.splitlines():
        if line.startswith("|") and _cells(line)[0] == "コード":
            in_table = True
            continue
        if in_table:
            if not line.startswith("|"):
                in_table = False
                continue
            first = _cells(line)[0]
            if CODE.match(first):
                out.append(first)
    return out


def summary(sec: str) -> dict[str, tuple[int, list[str]]]:
    """「### 集計」の表：分類 → (件数, コード)。"""
    lines = sec.splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("### 集計"))
    out: dict[str, tuple[int, list[str]]] = {}
    for line in lines[start + 1 :]:
        if line.startswith("#"):
            break
        if not line.startswith("|"):
            continue
        cells = _cells(line)
        if cells[0] in ("分類", "") or set(cells[0]) <= {"-"}:
            continue
        codes = [] if cells[2] in ("—", "-", "") else [c.strip() for c in re.split(r"[・、,]", cells[2]) if c.strip()]
        out[cells[0]] = (int(cells[1]), codes)
    return out


def inventory() -> dict[str, dict[str, tuple[int, list[str]]]]:
    """モジュール → 分類 → (件数, コード)。"""
    return {d.name: summary(section((d / "README.md").read_text(encoding="utf-8"))) for d in module_dirs()}


def _str_value(v: ast.AST) -> str | None:
    if isinstance(v, ast.Constant) and isinstance(v.value, str):
        return v.value
    if isinstance(v, ast.BinOp):
        a, b = _str_value(v.left), _str_value(v.right)
        return (a or "") + (b or "") if (a is not None or b is not None) else None
    if isinstance(v, ast.JoinedStr):
        return "".join(x.value for x in v.values if isinstance(x, ast.Constant) and isinstance(x.value, str))
    return None


def reason_constants(module: Path) -> list[tuple[str, str]]:
    """モジュールの .py の、対象外の理由の定数（ファイル名, 名前）。"""
    out: list[tuple[str, str]] = []
    for f in sorted(module.rglob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in tree.body:
            if not (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)):
                continue
            name = node.targets[0].id
            text = _str_value(node.value)
            if text is None or len(text) < 15 or VARIABLE_VALUE.match(text) or not REASON_NAME.fullmatch(name):
                continue
            out.append((f.relative_to(module).as_posix(), name))
    return out


class InventoryTest(unittest.TestCase):
    def test_every_module_has_rows_and_summary(self) -> None:
        dirs = module_dirs()
        self.assertGreaterEqual(len(dirs), 10)
        for d in dirs:
            with self.subTest(module=d.name):
                sec = section((d / "README.md").read_text(encoding="utf-8"))
                self.assertTrue(row_codes(sec), "行の表がない")
                self.assertTrue(summary(sec), "### 集計 の表がない")

    def test_summary_matches_rows(self) -> None:
        for d in module_dirs():
            sec = section((d / "README.md").read_text(encoding="utf-8"))
            rows = row_codes(sec)
            summ = summary(sec)
            with self.subTest(module=d.name):
                self.assertEqual(len(rows), len(set(rows)), f"行の表のコードが重複: {[c for c, n in Counter(rows).items() if n > 1]}")
                self.assertLessEqual(set(summ), set(CATEGORIES), f"知らない分類: {set(summ) - set(CATEGORIES)}")
                listed = [c for _, codes in summ.values() for c in codes]
                self.assertEqual(Counter(listed), Counter(set(listed)), f"集計で2回数えたコード: {[c for c, n in Counter(listed).items() if n > 1]}")
                self.assertEqual(set(listed), set(rows), f"行の表にだけある: {sorted(set(rows) - set(listed))}、集計にだけある: {sorted(set(listed) - set(rows))}")
                for cat, (count, codes) in summ.items():
                    self.assertEqual(count, len(codes), f"{cat} の件数が数と合わない")

    def test_no_unimplemented_in_scope(self) -> None:
        """D24③：完成の時点で、範囲内なのに未対応の「対象外」（分類 (c)）を0件にする。"""
        remaining = {m: s["(c)"][1] for m, s in inventory().items() if s.get("(c)", (0, []))[0]}
        self.assertEqual(remaining, {}, f"範囲内なのに未対応の (c) が残っている: {remaining}")

    def test_reason_constants_are_listed(self) -> None:
        for d in module_dirs():
            sec = section((d / "README.md").read_text(encoding="utf-8"))
            for f, name in reason_constants(d):
                with self.subTest(module=d.name, file=f, name=name):
                    self.assertTrue(name in sec, f"{d.name}/{f} の対象外の理由 {name} が README の「対象外の一覧」に載っていない")

    def test_totals(self) -> None:
        """全モジュールの合計（README の行の数と集計の合計が合う）。"""
        inv = inventory()
        total = Counter({cat: sum(s.get(cat, (0, []))[0] for s in inv.values()) for cat in CATEGORIES})
        rows = sum(len(row_codes(section((d / "README.md").read_text(encoding="utf-8")))) for d in module_dirs())
        self.assertEqual(sum(total.values()), rows)


if __name__ == "__main__":
    unittest.main()

"""層と依存の検査（SCOPE §6）：記録層は判定コア（OpenFisca、AGPL）を import しない。
台帳の畳み込みと中間表現の作成は beancount（GPL）なしで動く（アダプタの向こうに閉じ込める。D11）。"""

from __future__ import annotations

import ast
import pathlib
import subprocess
import sys
import unittest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "okura_records"
PURE_MODULES = ("problem", "meta_vocabulary", "ledger_map", "jsonl_ledger", "facts_ledger", "judgments_ledger", "build_ir")


def imported_modules(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


class LayeringTests(unittest.TestCase):
    def test_no_core_or_openfisca_imports(self):
        for path in SRC.glob("*.py"):
            for module in imported_modules(path):
                with self.subTest(file=path.name, module=module):
                    self.assertFalse(module.split(".")[0] in ("okura_core", "openfisca_core", "openfisca"), module)

    def test_pure_modules_do_not_import_beancount(self):
        for name in PURE_MODULES:
            for module in imported_modules(SRC / f"{name}.py"):
                with self.subTest(file=name, module=module):
                    self.assertNotEqual(module.split(".")[0], "beancount")

    def test_pure_modules_load_without_beancount(self):
        code = (
            "import sys\n"
            + "".join(f"import okura_records.{name}\n" for name in PURE_MODULES)
            + "print(sorted(m for m in sys.modules if m.split('.')[0] in ('beancount', 'beanquery', 'okura_core', 'openfisca_core')))\n"
        )
        done = subprocess.run([sys.executable, "-I", "-X", "utf8", "-c", code], capture_output=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr.decode("utf-8", "replace"))
        self.assertEqual(done.stdout.strip(), b"[]")


if __name__ == "__main__":
    unittest.main()

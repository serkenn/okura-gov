"""構造の検査（SCOPE §6-1・§6-2、§3 の「ネットワークに出るのは監視のパッケージだけ」）：import の向き。

(d) okura_core は beancount・beanquery・okura_records を import しない（GPL と AGPL を同じプロセスに混ぜない）。
    okura_records は openfisca_core・okura_core を import しない（ファイルを読むだけで確かめる。実行は記録層の venv の担当）。
    okura_ir は標準ライブラリだけ。どのパッケージも、許したサードパーティのパッケージの外を import しない（新しい依存を足したら
    ここで止まる）。動的な import（__import__・importlib.import_module・exec・eval）を使わない。
(e) okura_core はネットワークのモジュール（socket・ssl・urllib・http など）を import しない。
    実行時にも：ソケットを開こうとすると失敗する状態で、判定コアのコマンドの処理（cli.run）が最後まで動く。

実行時の検査は、判定コアの venv の python（sys.executable）を -I -X utf8 で別のプロセスとして起動する。
注：openfisca_core が import する psutil は、import のときに socket を読み込む（判定コアのコードではない）。
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

from .support import REPO, make_ir, make_query, person, salary

PACKAGES: dict[str, Path] = {
    "okura_ir": REPO / "packages" / "ir" / "src" / "okura_ir",
    "okura_core": REPO / "packages" / "core" / "src" / "okura_core",
    "okura_records": REPO / "packages" / "records" / "src" / "okura_records",
}

#: 標準ライブラリのほかに import してよいもの（自分のパッケージを含む）。
ALLOWED: dict[str, frozenset[str]] = {
    "okura_ir": frozenset({"okura_ir"}),
    # yaml（PyYAML）は openfisca_core の依存として入っているもの。概念辞書の安全な読み込みに使う。
    "okura_core": frozenset({"okura_core", "okura_ir", "openfisca_core", "numpy", "yaml"}),
    "okura_records": frozenset({"okura_records", "okura_ir", "beancount", "beanquery"}),
}

#: 名指しで禁止するもの（許すものの一覧を広げても、これは通さない）。
FORBIDDEN: dict[str, frozenset[str]] = {
    "okura_ir": frozenset({"okura_core", "okura_records", "openfisca_core", "openfisca", "beancount", "beanquery"}),
    "okura_core": frozenset({"okura_records", "beancount", "beanquery", "openfisca_web_api"}),
    "okura_records": frozenset({"okura_core", "openfisca_core", "openfisca", "openfisca_web_api"}),
}

#: ネットワークのモジュール（標準ライブラリとサードパーティ）。
NETWORK: frozenset[str] = frozenset(
    {
        "socket", "_socket", "ssl", "_ssl", "urllib", "http", "ftplib", "smtplib", "poplib", "imaplib", "nntplib",
        "telnetlib", "socketserver", "xmlrpc", "asyncio", "selectors", "webbrowser", "requests", "urllib3", "httpx",
        "aiohttp", "websocket", "websockets", "flask", "flask_cors", "gunicorn", "werkzeug", "openfisca_web_api",
    }
)  # fmt: skip

_DYNAMIC_NAMES = frozenset({"__import__", "exec", "eval", "compile"})


@dataclass(frozen=True)
class Imported:
    module: str  # 最上位の名前
    file: str
    line: int


def scan(package: str) -> tuple[list[Imported], list[str]]:
    """パッケージの全 .py の import（絶対 import の最上位の名前）と、動的な import・実行の箇所。"""
    root = PACKAGES[package]
    found: list[Imported] = []
    dynamic: list[str] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root.parent).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found += [Imported(a.name.split(".")[0], rel, node.lineno) for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    found.append(Imported(node.module.split(".")[0], rel, node.lineno))
                    if node.module == "importlib" and any(a.name == "import_module" for a in node.names):
                        dynamic.append(f"{rel}:{node.lineno}: from importlib import import_module")
            elif isinstance(node, ast.Call):
                f = node.func
                if isinstance(f, ast.Name) and f.id in _DYNAMIC_NAMES:
                    dynamic.append(f"{rel}:{node.lineno}: {f.id}(...)")
                elif isinstance(f, ast.Attribute) and f.attr == "import_module":
                    dynamic.append(f"{rel}:{node.lineno}: ….import_module(...)")
    return found, dynamic


def _is_stdlib(name: str) -> bool:
    return name in sys.stdlib_module_names or name == "__future__"


class TestImportDirections(unittest.TestCase):
    def test_packages_exist(self) -> None:
        for name, path in PACKAGES.items():
            with self.subTest(package=name):
                self.assertTrue((path / "__init__.py").is_file(), path)

    def test_only_allowed_imports(self) -> None:
        for package in PACKAGES:
            found, _ = scan(package)
            self.assertTrue(found, package)
            for imp in found:
                with self.subTest(package=package, module=imp.module, at=f"{imp.file}:{imp.line}"):
                    self.assertNotIn(imp.module, FORBIDDEN[package])
                    self.assertTrue(
                        _is_stdlib(imp.module) or imp.module in ALLOWED[package],
                        f"{package} が許していないパッケージを import している: {imp.module}",
                    )

    def test_ir_is_standard_library_only(self) -> None:
        found, _ = scan("okura_ir")
        outside = sorted({i.module for i in found if not _is_stdlib(i.module) and i.module != "okura_ir"})
        self.assertEqual(outside, [])

    def test_core_and_records_do_not_import_each_other(self) -> None:
        core, _ = scan("okura_core")
        records, _ = scan("okura_records")
        self.assertEqual(sorted({i.module for i in core} & {"okura_records", "beancount", "beanquery"}), [])
        self.assertEqual(sorted({i.module for i in records} & {"okura_core", "openfisca_core", "openfisca"}), [])

    def test_no_dynamic_import_or_exec(self) -> None:
        for package in PACKAGES:
            _, dynamic = scan(package)
            with self.subTest(package=package):
                self.assertEqual(dynamic, [])

    def test_core_has_no_network_imports(self) -> None:
        found, _ = scan("okura_core")
        hits = [f"{i.file}:{i.line}: {i.module}" for i in found if i.module in NETWORK]
        self.assertEqual(hits, [])


def _run(code: str, stdin: bytes = b"") -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-I", "-X", "utf8", "-c", code], input=stdin, capture_output=True, timeout=180, check=False
    )


class TestImportsAtRuntime(unittest.TestCase):
    def test_ir_loads_only_standard_library(self) -> None:
        code = (
            "import sys\n"
            "before = set(sys.modules)\n"
            "import okura_ir, okura_ir.validate, okura_ir.jsonio, okura_ir.jsonschema_subset, okura_ir.vocabulary\n"
            "new = sorted({m.split('.')[0] for m in set(sys.modules) - before})\n"
            "print('\\n'.join(m for m in new if m not in sys.stdlib_module_names and m != 'okura_ir'))\n"
        )
        done = _run(code)
        self.assertEqual(done.returncode, 0, done.stderr.decode("utf-8", "replace"))
        self.assertEqual(done.stdout.decode("utf-8").strip(), "")

    def test_core_does_not_load_records_side(self) -> None:
        code = (
            "import sys\n"
            "import okura_core, okura_core.cli, okura_core.evaluate, okura_core.concepts\n"
            "print(sorted(m for m in sys.modules if m.split('.')[0] in ('beancount', 'beanquery', 'okura_records')))\n"
        )
        done = _run(code)
        self.assertEqual(done.returncode, 0, done.stderr.decode("utf-8", "replace"))
        self.assertEqual(done.stdout.strip(), b"[]")

    def test_core_runs_without_network(self) -> None:
        """ソケットの作成・名前解決・接続を失敗させても、cli.run（中間表現の検査 → 評価 → 結果の JSON）が最後まで動く。"""
        data = json.dumps(
            {
                "ir": make_ir([person("p-1")], [salary("s-1", "p-1", "2026-06-25", 2_000_000)]),
                "query": make_query((2025, 2026)),
            },
            ensure_ascii=False,
        ).encode("utf-8")
        code = (
            "import socket, sys\n"
            "tried = []\n"
            "def deny(*a, **k):\n"
            "    tried.append('call')\n"
            "    raise OSError('ネットワークはこの検査で禁止')\n"
            "class Guard(socket.socket):\n"
            "    def __init__(self, *a, **k):\n"
            "        tried.append('socket')\n"
            "        raise OSError('ネットワークはこの検査で禁止')\n"
            "socket.socket = Guard\n"
            "for name in ('create_connection', 'getaddrinfo', 'gethostbyname', 'socketpair', 'fromfd'):\n"
            "    setattr(socket, name, deny)\n"
            "from okura_core.cli import run\n"
            "code, result = run(sys.stdin.buffer.read())\n"
            "print(code, type(result).__name__, len(tried))\n"
        )
        done = _run(code, stdin=data)
        self.assertEqual(done.returncode, 0, done.stderr.decode("utf-8", "replace"))
        self.assertEqual(done.stdout.decode("utf-8").split(), ["0", "EvaluationResult", "0"])


if __name__ == "__main__":
    unittest.main()

"""コンテナの入口（Containerfile の ENTRYPOINT。標準ライブラリだけ）。

    podman run --rm -i okura-gov core < input.json > result.json
    podman run --rm okura-gov records build-ir --ledger …
    podman run --rm okura-gov monitor targets
    podman run --rm okura-gov test [core|ir|records|monitor]…

どのコマンドも、パッケージごとの仮想環境の Python を `-I -X utf8` で起動し直すだけ（AGENTS.md「仮想環境の作り方」）。
このファイルは okura_core・okura_records・okura_monitor を import しない（層と依存の規則）。
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
VENVS = ROOT / ".work" / "venvs"

USAGE = """使い方：
  core                     判定コア（標準入力の JSON → 標準出力の JSON）。python -m okura_core.cli と同じ
  records <引数>…          記録層。python -m okura_records.cli と同じ（build-ir・transactions・append）
  monitor <引数>…          監視。python -m okura_monitor と同じ（targets・run）
  test [名前]…             テスト（core・ir・records・monitor。名前がなければ全部）
  python <名前> <引数>…    仮想環境（core・records・monitor）の Python を -I -X utf8 で起動する
  help                     この説明
"""


def py(name: str) -> str:
    return str(VENVS / name / "bin" / "python")


def launch(name: str, *args: str) -> list[str]:
    return [py(name), "-I", "-X", "utf8", *args]


def tests() -> dict[str, list[list[str]]]:
    """AGENTS.md「テストの動かし方」の表と同じコマンド（パッケージごとに別のプロセス）。"""
    pytest = ["-m", "pytest", "-q", "-p", "no:cacheprovider"]
    return {
        "core": [launch("core", *pytest, "packages/core/tests")],
        "ir": [
            launch("core", *pytest, "packages/ir/tests"),
            launch("records", "-m", "unittest", "discover", "-s", "packages/ir/tests", "-t", "packages/ir"),
        ],
        "records": [launch("records", "-m", "unittest", "discover", "-s", "packages/records/tests", "-t", "packages/records")],
        "monitor": [launch("core", *pytest, "packages/monitor/tests")],
    }


def run_tests(names: list[str]) -> int:
    table = tests()
    unknown = [n for n in names if n not in table]
    if unknown:
        sys.stderr.write(f"知らないテストの名前：{'・'.join(unknown)}（{'・'.join(table)} から選ぶ）\n")
        return 2
    failed = []
    for name in names or list(table):
        for cmd in table[name]:
            print("+", " ".join(cmd[cmd.index("utf8") + 1 :]), f"（{Path(cmd[0]).parent.parent.name}）", flush=True)
            if subprocess.run(cmd, cwd=ROOT, check=False).returncode != 0:
                failed.append(name)
    if failed:
        sys.stderr.write(f"失敗：{'・'.join(dict.fromkeys(failed))}\n")
        return 1
    return 0


def main(argv: list[str]) -> int:
    if not sys.flags.isolated:
        sys.stderr.write("python -I で起動する\n")
        return 2
    cmd, rest = (argv[0], argv[1:]) if argv else ("help", [])
    if cmd == "core":
        os.execv(py("core"), launch("core", "-m", "okura_core.cli", *rest))
    if cmd == "records":
        os.execv(py("records"), launch("records", "-m", "okura_records.cli", *rest))
    if cmd == "monitor":
        os.execv(py("monitor"), launch("monitor", "-m", "okura_monitor", *rest))
    if cmd == "python" and rest and rest[0] in ("core", "records", "monitor"):
        os.execv(py(rest[0]), launch(rest[0], *rest[1:]))
    if cmd == "test":
        return run_tests(rest)
    sys.stdout.write(USAGE)
    return 0 if cmd in ("help", "-h", "--help") else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

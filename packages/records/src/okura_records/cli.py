"""記録層のコマンド。必ず `-I`（隔離モード）で起動する。

  python -I -X utf8 -m okura_records.cli build-ir --ledger main.beancount --facts facts.jsonl --judgments judgments.jsonl [--root DIR]
      → 標準出力に中間表現の JSON（UTF-8、LF）。
  python -I -X utf8 -m okura_records.cli transactions --ledger main.beancount [--root DIR]
      → 標準出力に正規化した取引 JSON。
  python -I -X utf8 -m okura_records.cli append (--facts facts.jsonl | --judgments judgments.jsonl) --draft draft.json
      → 手で書いた下書き（prev_sha256 なし）に prev_sha256 を入れて台帳の末尾に足す（台帳全体を検査してから）。

終了コード：0 成功、1 入力に問題がある（標準エラー出力に {"ok": false, "problems": [...]} の JSON）、
2 使い方の誤り・`-I` なしで起動した。
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from typing import Any, Sequence

from .problem import Problem

MAX_JSONL_BYTES = 64 * 2**20


def _dump(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=1, allow_nan=False) + "\n").encode("utf-8")


def _write(stream: Any, data: bytes) -> None:
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        buffer.write(data)
        buffer.flush()
    else:  # テストで差し替えた文字列のストリーム
        stream.write(data.decode("utf-8"))


def _fail(problems: Sequence[Problem]) -> int:
    _write(sys.stderr, _dump({"ok": False, "problems": [p.to_dict() for p in problems]}))
    return 1


def _read_jsonl(path: str) -> tuple[bytes | None, list[Problem]]:
    try:
        st = os.stat(path)
    except OSError as exc:
        return None, [Problem(path, "io_error", f"開けない（{type(exc).__name__}）")]
    if not stat.S_ISREG(st.st_mode):
        return None, [Problem(path, "not_regular_file", "通常のファイルでない")]
    if st.st_size > MAX_JSONL_BYTES:
        return None, [Problem(path, "ledger_too_large", f"大きすぎる（上限 {MAX_JSONL_BYTES} バイト）")]
    try:
        with open(path, "rb") as fh:
            data = fh.read(MAX_JSONL_BYTES + 1)
    except OSError as exc:
        return None, [Problem(path, "io_error", f"読めない（{type(exc).__name__}）")]
    if len(data) > MAX_JSONL_BYTES:
        return None, [Problem(path, "ledger_too_large", f"大きすぎる（上限 {MAX_JSONL_BYTES} バイト）")]
    return data, []


def _transactions(ledger_path: str, root: str | None) -> tuple[dict[str, Any] | None, list[Problem]]:
    from .adapter import normalize
    from .safe_loader import load_ledger

    loaded = load_ledger(ledger_path, root=root)
    if loaded.ledger is None or loaded.problems:
        return None, list(loaded.problems)
    return normalize(loaded.ledger)


def _cmd_transactions(args: argparse.Namespace) -> int:
    doc, problems = _transactions(args.ledger, args.root)
    if problems or doc is None:
        return _fail(problems)
    _write(sys.stdout, _dump(doc))
    return 0


def _cmd_build_ir(args: argparse.Namespace) -> int:
    from . import facts_ledger, judgments_ledger
    from .build_ir import build_ir

    problems: list[Problem] = []
    doc, tx_problems = _transactions(args.ledger, args.root)
    problems.extend(tx_problems)
    states = []
    for path, module in ((args.facts, facts_ledger), (args.judgments, judgments_ledger)):
        data, read_problems = _read_jsonl(path)
        problems.extend(read_problems)
        if data is None:
            states.append(None)
            continue
        state, ledger_problems = module.read(data, path)
        problems.extend(ledger_problems)
        states.append(state)
    if problems or doc is None or None in states:
        return _fail(problems)
    result = build_ir(doc, states[0], states[1])
    if not result.ok or result.ir is None:
        return _fail(result.problems)
    _write(sys.stdout, _dump(result.ir))
    return 0


def _cmd_append(args: argparse.Namespace) -> int:
    from okura_ir import loads

    from . import facts_ledger, judgments_ledger

    path, module = (args.facts, facts_ledger) if args.facts else (args.judgments, judgments_ledger)
    draft_bytes, problems = _read_jsonl(args.draft)
    if draft_bytes is None:
        return _fail(problems)
    drafts, load_problems = loads(draft_bytes)
    if load_problems:
        return _fail([Problem(args.draft, p.code, p.message) for p in load_problems])
    exists = os.path.lexists(path)
    existing = b""
    if exists:
        data, problems = _read_jsonl(path)
        if data is None:
            return _fail(problems)
        existing = data
    added, problems = module.append_drafts(existing, drafts, path)
    if added is None:
        return _fail(problems)
    try:
        with open(path, "ab" if exists else "xb") as fh:
            if fh.tell() != len(existing):  # 読んだ後に書き換えられた
                return _fail([Problem(path, "changed_during_read", "読んだ後に台帳が変わった（もう一度実行する）")])
            fh.write(added)
    except OSError as exc:
        return _fail([Problem(path, "io_error", f"書けない（{type(exc).__name__}）")])
    _write(sys.stdout, _dump({"ok": True, "appended_lines": added.count(b"\n")}))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="okura_records.cli", description="okura-gov の記録層")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-ir", help="台帳・事実台帳・判断台帳から中間表現を作る")
    build.add_argument("--ledger", required=True, help="beancount の最上位の台帳（.beancount）")
    build.add_argument("--facts", required=True, help="事実台帳（JSON Lines）")
    build.add_argument("--judgments", required=True, help="判断台帳（JSON Lines）")
    build.add_argument("--root", default=None, help="台帳を読んでよいディレクトリ（既定は --ledger のディレクトリ）")
    build.set_defaults(func=_cmd_build_ir)
    tx = sub.add_parser("transactions", help="台帳を正規化した取引 JSON にする")
    tx.add_argument("--ledger", required=True)
    tx.add_argument("--root", default=None)
    tx.set_defaults(func=_cmd_transactions)
    append = sub.add_parser("append", help="手で書いた下書き（prev_sha256 なし）を事実台帳・判断台帳の末尾に足す")
    target = append.add_mutually_exclusive_group(required=True)
    target.add_argument("--facts", help="事実台帳（JSON Lines。無ければ作る）")
    target.add_argument("--judgments", help="判断台帳（JSON Lines。無ければ作る）")
    append.add_argument("--draft", required=True, help="下書き：行のオブジェクトか、その配列の JSON（複数行で書いてよい）")
    append.set_defaults(func=_cmd_append)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    if not sys.flags.isolated:
        sys.stderr.write("python -I（隔離モード）で起動すること（台帳のディレクトリの .py を読み込ませないため）\n")
        return 2
    args = _parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

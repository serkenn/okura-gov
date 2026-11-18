"""判定コアのコマンド（D7 改）：標準入力の JSON → 標準出力の結果 JSON。

    <venv の python.exe> -I -X utf8 -m okura_core.cli < input.json > result.json

入力：{"ir": 中間表現, "query": 問い, "injected": 注入データ（任意。null か配列）}
出力：結果の JSON（result.schema.json。キーを並べ替えた決定的な JSON。時間や絶対パスを含めない）。
終了コード：
  0 結果を出した（ok: true）
  2 入力の誤り（ok: false。errors に場所と内容）
  3 判定コアの誤り（ok: false、code internal_error）
  4 起動のしかたの誤り（-I と -X utf8 が要る。Windows の cp932 では日本語の YAML を読めない：
    docs/measurements/20261109_R2-tools_openfisca-core-runtime.md T00）
"""

from __future__ import annotations

import sys
from typing import Any, BinaryIO

from okura_ir import loads

from .result import EvaluationFailure, Problem, dumps

MAX_INPUT_BYTES = 16 * 1024 * 1024
EXIT_OK = 0
EXIT_INPUT = 2
EXIT_INTERNAL = 3
EXIT_ENVIRONMENT = 4
_KEYS_REQUIRED = ("ir", "query")
_KEYS_OPTIONAL = ("injected",)


def _write(out: BinaryIO, result: Any) -> None:
    out.write(dumps(result).encode("utf-8"))
    out.flush()


def run(data: bytes) -> tuple[int, Any]:
    """入力のバイト列から（終了コード, 結果）を作る。例外を送出しない。"""
    value, problems = loads(data, max_bytes=MAX_INPUT_BYTES)
    if problems:
        return EXIT_INPUT, EvaluationFailure(tuple(Problem(p.path, p.code, p.message) for p in problems))
    if not isinstance(value, dict):
        return EXIT_INPUT, EvaluationFailure((Problem("$", "type", "入力は {ir, query, injected} のオブジェクト"),))
    errs = [Problem(f"$.{k}", "required", f"{k} がない") for k in _KEYS_REQUIRED if k not in value]
    errs += [
        Problem(f"$.{k}", "additional_property", f"知らないキー: {k}")
        for k in value
        if k not in _KEYS_REQUIRED and k not in _KEYS_OPTIONAL
    ]
    if errs:
        return EXIT_INPUT, EvaluationFailure(tuple(errs))
    try:
        from .evaluate import evaluate

        result = evaluate(value["ir"], value["query"], value.get("injected"))
    except Exception as exc:  # 判定コアの誤り。入力の誤りと分けて返す
        return EXIT_INTERNAL, EvaluationFailure(
            (Problem("$", "internal_error", f"判定コアの誤り: {type(exc).__name__}: {exc}"),)
        )
    return (EXIT_OK if result.ok else EXIT_INPUT), result


def main() -> int:
    out = sys.stdout.buffer
    if not sys.flags.utf8_mode or not sys.flags.isolated:
        _write(
            out,
            EvaluationFailure(
                (Problem("$", "environment", "python -I -X utf8 -m okura_core.cli で起動する（-I と UTF-8 モードが要る）"),)
            ),
        )
        return EXIT_ENVIRONMENT
    data = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    code, result = run(data)
    try:
        text = dumps(result)  # 書き出す前に全体を直列化する（途中まで書いた JSON を出さない）
    except Exception as exc:  # 直列化できない値（判定コアの誤り）。標準エラーに traceback を出さず、失敗の JSON で返す
        code = EXIT_INTERNAL
        text = dumps(
            EvaluationFailure((Problem("$", "internal_error", f"結果を JSON にできない: {type(exc).__name__}: {exc}"),))
        )
    out.write(text.encode("utf-8"))
    out.flush()
    return code


if __name__ == "__main__":
    sys.exit(main())

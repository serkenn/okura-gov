"""中間表現の JSON を厳密に読む（標準ライブラリだけ）。

json.loads のままでは次のものが黙って通るので、ここで止める：
  - 重複したキー（後の値で上書きされる）
  - NaN・Infinity・-Infinity（JSON の仕様の外）
  - BOM、UTF-8 として正しくないバイト列
  - 深すぎる入れ子（RecursionError）、大きすぎる入力
数の欄に文字列や小数が来たことは、ここではなく validate() のスキーマの検査で止める。
"""

from __future__ import annotations

import json
import re
from typing import Any

from .problem import ROOT, Problem

DEFAULT_MAX_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_DEPTH = 64


class _DuplicateKey(Exception):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


class _BadConstant(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


def _pairs_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def _reject_constant(name: str) -> Any:
    raise _BadConstant(name)


# 文字列の字句（読み飛ばす）か括弧
_TOKENS = re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*"|[\[\]{}]', re.DOTALL)


def _max_nesting(text: str) -> int:
    """文字列の外の [ と { の入れ子の深さの最大（json.loads の前に安く数える）。"""
    depth = 0
    deepest = 0
    for match in _TOKENS.finditer(text):
        token = match.group()
        if token in "[{":
            depth += 1
            if depth > deepest:
                deepest = depth
        elif token in "]}":
            depth -= 1
    return deepest


def loads(
    data: str | bytes, *, max_bytes: int = DEFAULT_MAX_BYTES, max_depth: int = DEFAULT_MAX_DEPTH
) -> tuple[Any, list[Problem]]:
    """JSON を読み、(値, 問題の一覧) を返す。問題があるときの値は None。例外は送出しない。"""
    if isinstance(data, bytes):
        if len(data) > max_bytes:
            return None, [Problem(ROOT, "json_too_large", f"入力が大きすぎる（{len(data)} バイト。上限 {max_bytes}）")]
        if data.startswith(b"\xef\xbb\xbf"):
            return None, [Problem(ROOT, "json_bom", "BOM つきの入力は受け付けない")]
        try:
            text = data.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            return None, [Problem(ROOT, "json_not_utf8", f"UTF-8 として正しくない（{exc.start} バイト目）")]
    elif isinstance(data, str):
        text = data
        if len(text) > max_bytes:
            return None, [Problem(ROOT, "json_too_large", f"入力が大きすぎる（{len(text)} 文字。上限 {max_bytes}）")]
        if text.startswith("﻿"):
            return None, [Problem(ROOT, "json_bom", "BOM つきの入力は受け付けない")]
    else:
        return None, [Problem(ROOT, "json_syntax", "入力は str か bytes でなければならない")]

    if _max_nesting(text) > max_depth:
        return None, [Problem(ROOT, "json_too_deep", f"入れ子が深すぎる（上限 {max_depth}）")]
    try:
        value = json.loads(text, object_pairs_hook=_pairs_without_duplicates, parse_constant=_reject_constant)
    except _DuplicateKey as exc:
        return None, [Problem(ROOT, "json_duplicate_key", f"重複したキー: {exc.key}")]
    except _BadConstant as exc:
        return None, [Problem(ROOT, "json_constant", f"JSON にない数: {exc.name}")]
    except json.JSONDecodeError as exc:
        return None, [Problem(ROOT, "json_syntax", f"JSON として読めない（{exc.lineno} 行 {exc.colno} 列: {exc.msg}）")]
    except RecursionError:
        return None, [Problem(ROOT, "json_too_deep", "入れ子が深すぎる")]
    except ValueError as exc:  # 桁の多すぎる整数など
        return None, [Problem(ROOT, "json_syntax", f"JSON として読めない（{exc}）")]
    return value, []

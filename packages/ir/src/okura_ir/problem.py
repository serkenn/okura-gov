"""検査で見つかった問題の型と、インスタンスの場所（path）の書き方。

path は「$」を根とし、オブジェクトのキーは `.key`（英数字と _ だけのキー）か
`["キー"]`（それ以外）、配列の添字は `[0]` で書く。例：`$.facts[3].roles.payer`。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*", re.ASCII)

ROOT = "$"


@dataclass(frozen=True, slots=True)
class Problem:
    """検査で見つかった1つの問題。

    - path：問題のある場所（インスタンスの中。スキーマの検査ではスキーマの中の JSON Pointer）。
    - code：機械が読む分類（README の「問題の code」の表）。
    - message：人が読む説明（日本語）。
    """

    path: str
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "code": self.code, "message": self.message}


def child_key(path: str, key: str) -> str:
    """オブジェクトのキー key の場所。"""
    if _IDENTIFIER.fullmatch(key):
        return f"{path}.{key}"
    return f"{path}[{json.dumps(key, ensure_ascii=False)}]"


def child_index(path: str, index: int) -> str:
    """配列の添字 index の場所。"""
    return f"{path}[{index}]"

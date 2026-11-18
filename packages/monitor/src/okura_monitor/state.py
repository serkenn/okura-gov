"""前回の状態の保存。利用側が渡すディレクトリ（--state-dir）の中に JSON で置く。ライブラリ自身はデータを持たない。"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

_SAFE = re.compile(r"^[A-Za-z0-9_.-]+$")


class StateStore:
    """名前（`egov_revisions/340AC0000000033` のような / 区切り）ごとに1つの JSON を読み書きする。"""

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def _path(self, name: str) -> Path:
        parts = name.split("/")
        if not parts or any(not _SAFE.match(p) or p in (".", "..") for p in parts):
            raise ValueError(f"状態の名前に使えない文字がある: {name!r}")
        return self.root.joinpath(*parts[:-1], parts[-1] + ".json")

    def load(self, name: str) -> Any | None:
        p = self._path(name)
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def save(self, name: str, data: Any) -> None:
        p = self._path(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, p)

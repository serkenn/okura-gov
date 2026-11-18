"""事実台帳：取引でない事実（人・関係・住所・保険・人の属性・書類・資産・提出した書類）を追記のみの JSON Lines で持つ。

行の形と畳み込みの規則は jsonl_ledger（README §4）。この台帳の `section` は中間表現の配列の名前：
persons・relations・residences・insurance_memberships・facts・assets・filed_documents。
`record` は中間表現のその配列の1件をそのまま書く（中身の検査は build_ir の最後の okura_ir.validate で行う）。
`record.recorded_at` は書かない（行の `recorded_at` を build_ir が写す）。
"""

from __future__ import annotations

from typing import Any

from .jsonl_ledger import CurrentRecord, Entry, LedgerSpec, LedgerState, append_entry, encode_entry
from .jsonl_ledger import append_drafts as _append_drafts
from .jsonl_ledger import fold as _fold
from .jsonl_ledger import parse as _parse
from .jsonl_ledger import read as _read
from .problem import Problem

__all__ = [
    "LEDGER",
    "SECTIONS",
    "SPEC",
    "CurrentRecord",
    "LedgerState",
    "append_drafts",
    "append_entry",
    "encode_entry",
    "fold",
    "parse",
    "read",
]

LEDGER = "okura-facts/0"
SECTIONS = ("persons", "relations", "residences", "insurance_memberships", "facts", "assets", "filed_documents")


def _check_record(entry: Entry, where: str) -> list[Problem]:
    if entry.record is not None and "recorded_at" in entry.record:
        return [Problem(f"{where}.record.recorded_at", "record_has_recorded_at", "record に recorded_at を書かない（行の recorded_at を使う）")]
    return []


SPEC = LedgerSpec(LEDGER, SECTIONS, _check_record)


def parse(data: bytes, source: str) -> tuple[tuple[Entry, ...], list[Problem]]:
    return _parse(data, SPEC, source)


def fold(entries: tuple[Entry, ...], source: str) -> tuple[LedgerState, list[Problem]]:
    return _fold(entries, SPEC, source)


def read(data: bytes, source: str) -> tuple[LedgerState, list[Problem]]:
    """事実台帳のバイト列 → (現在の状態, 問題)。純粋関数。"""
    return _read(data, SPEC, source)


def append_drafts(existing: bytes, drafts: Any, source: str) -> tuple[bytes | None, list[Problem]]:
    """下書きの行（prev_sha256 なし）を既存の事実台帳につなぐ。足す分のバイト列か None と問題。純粋関数。"""
    return _append_drafts(existing, drafts, SPEC, source)

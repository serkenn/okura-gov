"""判断台帳：人の判断（判断.*）・予測（見込み.*）・法令が求める見積り（見積り.*）・申告の計画（計画.*）と、
納税者の選択（選択.*）を追記のみの JSON Lines で持つ（D4・D12）。

行の形と畳み込みの規則は jsonl_ledger（README §4）。`section` は judgments か choices。
`record` は中間表現の判断・選択の1件（judged_by・judged_at・subject・value・basis・replaces など）をそのまま書く。

2つの「置き換え」を区別する：
- 行の `replaces`（op が correct・delete）：記録の誤りの訂正・取り消し。現在の状態から古い行は消える。
- record の `replaces`（中間表現の欄）：判断が変わったこと（按分の割合を見直したなど）。古い判断も中間表現に残り、
  判定コアが連鎖の先頭を使う（okura_ir README §3.2）。連鎖の整合（分岐・循環・日時の逆転）は okura_ir.validate が確かめる。
  連鎖の先頭だけがほしいときは current_values を使う。
"""

from __future__ import annotations

from typing import Any, Mapping

from .jsonl_ledger import CurrentRecord, Entry, LedgerSpec, LedgerState, append_entry, encode_entry, parse_datetime
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
    "current_values",
    "encode_entry",
    "fold",
    "parse",
    "read",
]

LEDGER = "okura-judgments/0"
SECTIONS = ("judgments", "choices")
_TIME_KEY = {"judgments": "judged_at", "choices": "chosen_at"}


def _check_record(entry: Entry, where: str) -> list[Problem]:
    record = entry.record
    if record is None:
        return []
    problems: list[Problem] = []
    if "recorded_at" in record:
        problems.append(Problem(f"{where}.record.recorded_at", "record_has_recorded_at", "record に recorded_at を書かない（行の recorded_at を使う）"))
    key = _TIME_KEY[entry.section]
    decided = parse_datetime(record.get(key)) if isinstance(record.get(key), str) else None
    recorded = parse_datetime(entry.recorded_at)
    if decided is not None and recorded is not None and decided > recorded:
        problems.append(Problem(f"{where}.record.{key}", "judged_after_recorded", f"{key} が記録日時より後（まだしていない判断は記録できない）"))
    return problems


SPEC = LedgerSpec(LEDGER, SECTIONS, _check_record)


def parse(data: bytes, source: str) -> tuple[tuple[Entry, ...], list[Problem]]:
    return _parse(data, SPEC, source)


def fold(entries: tuple[Entry, ...], source: str) -> tuple[LedgerState, list[Problem]]:
    return _fold(entries, SPEC, source)


def read(data: bytes, source: str) -> tuple[LedgerState, list[Problem]]:
    """判断台帳のバイト列 → (現在の状態, 問題)。純粋関数。"""
    return _read(data, SPEC, source)


def append_drafts(existing: bytes, drafts: Any, source: str) -> tuple[bytes | None, list[Problem]]:
    """下書きの行（prev_sha256 なし）を既存の判断台帳につなぐ。足す分のバイト列か None と問題。純粋関数。"""
    return _append_drafts(existing, drafts, SPEC, source)


def current_values(state: LedgerState, section: str = "judgments") -> list[Mapping[str, Any]]:
    """record の replaces の連鎖の先頭（どの record からも置き換えられていないもの）だけを返す。純粋関数。"""
    records = [r.record for r in state.in_section(section)]
    replaced = {r.get("replaces") for r in records if isinstance(r.get("replaces"), str)}
    return [r for r in records if r.get("id") not in replaced]

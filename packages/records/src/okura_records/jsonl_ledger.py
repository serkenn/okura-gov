"""追記のみの JSON Lines の台帳（事実台帳・判断台帳の共通部分）。標準ライブラリと okura_ir だけ。

1行が1件。行の形（キーの順は自由。書くときは encode_entry がキーを並べる）：

```json
{"ledger": "okura-facts/0", "entry_id": "fe-0002", "recorded_at": "2026-02-11T21:00:00+09:00",
 "recorded_by": {"person": "p-a"}, "op": "correct", "replaces": "fe-0001", "reason": "生年月日の打ち間違い",
 "section": "persons", "record": {"id": "p-c", "birth_on": "2006-05-05"},
 "prev_sha256": "…前の行のバイト列の SHA-256…"}
```

- `ledger`：台帳の種類と版（事実台帳 `okura-facts/0`、判断台帳 `okura-judgments/0`）。別の台帳の行の取り違えを止める。
- `entry_id`：行の ID（台帳の中で一意）。`record.id`（中間表現の ID）とは別。訂正しても record.id は変えなくてよい。
- `recorded_at`：記録した日時（秒まで・時差つき）。前の行より前にはできない。`recorded_by`：記録した人（`{"person": id}` か `{"label": 名前}`）。
- `op`：`add`（新しい記録）・`correct`（`replaces` の行の記録を差し替える）・`delete`（`replaces` の行の記録を取り消す）。
  `correct`・`delete` には `replaces` と `reason`（訂正・削除の理由）が必須。`replaces` は前の行だけを指せる（追記のみ）。
- `section`：中間表現のどの配列に入る記録か。`record`：中間表現の1件（`delete` では書かない）。
- `prev_sha256`：前の行のバイト列（行末の LF を除く）の SHA-256。最初の行は null。行の書き換え・削除・並べ替えを見つける
  （改ざんの検出。本人がすべてを作り直すことは防げない）。

現在の状態（fold）：置き換えの連鎖の先頭の記録だけを残し、`delete` で終わる連鎖は除く。順序は連鎖の最初の行の順。
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from okura_ir import loads
from okura_ir.vocabulary import COMMON_DEFS

from .ledger_map import PLACE_NAMES, PLACEMENTS, SECTION_OF_KIND
from .problem import Problem

__all__ = [
    "CurrentRecord",
    "Entry",
    "LedgerSpec",
    "LedgerState",
    "append_drafts",
    "append_entry",
    "encode_entry",
    "fold",
    "parse",
    "parse_datetime",
    "read",
    "section_problems",
]

MAX_LEDGER_BYTES = 64 * 2**20
MAX_LINE_BYTES = 1 * 2**20
_ID_RE = re.compile(COMMON_DEFS["id"]["pattern"].strip("^$"), re.ASCII)
_DATETIME_RE = re.compile(COMMON_DEFS["datetime"]["pattern"].strip("^$"), re.ASCII)
_NAME_RE = re.compile(COMMON_DEFS["name"]["pattern"].strip("^$"))
_TEXT_RE = re.compile(COMMON_DEFS["text"]["pattern"].strip("^$"))
_SHA_RE = re.compile(r"[0-9a-f]{64}", re.ASCII)
_OPS = ("add", "correct", "delete")
_KEYS = frozenset(
    {"ledger", "entry_id", "recorded_at", "recorded_by", "op", "replaces", "reason", "section", "record", "prev_sha256"}
)


@dataclass(frozen=True)
class Entry:
    """台帳の1行（検査に通ったもの）。"""

    line: int
    entry_id: str
    recorded_at: str
    recorded_by: Mapping[str, str]
    op: str
    section: str
    replaces: str | None
    reason: str | None
    record: Mapping[str, Any] | None
    prev_sha256: str | None
    line_sha256: str


@dataclass(frozen=True)
class CurrentRecord:
    """現在の状態の1件。record は中間表現の1件（呼び出し側は書き換えない）。"""

    section: str
    record: Mapping[str, Any]
    entry_id: str  # 連鎖の先頭（今の記録を書いた行）
    recorded_at: str  # 先頭の行の記録日時
    origin: str  # 例 "facts.jsonl:5 (fe-0005)"
    history: tuple[str, ...]  # 連鎖の行の ID（古い順）


@dataclass(frozen=True)
class LedgerState:
    ledger: str
    records: tuple[CurrentRecord, ...]

    def in_section(self, section: str) -> list[CurrentRecord]:
        return [r for r in self.records if r.section == section]


@dataclass(frozen=True)
class LedgerSpec:
    """台帳の種類ごとの約束。check_record は1件の記録の追加の検査（問題の一覧を返す）。"""

    name: str
    sections: tuple[str, ...]
    check_record: Callable[[Entry, str], list[Problem]]


def parse_datetime(text: str) -> _dt.datetime | None:
    """`YYYY-MM-DDTHH:MM:SS(Z|±HH:MM)` の実在する日時か。そうでなければ None。"""
    if not isinstance(text, str) or not _DATETIME_RE.fullmatch(text):
        return None
    try:
        return _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_PRIMARY_OF_KIND = {p.kind: p.primary for p in PLACEMENTS}


def section_problems(section: str, record: Any, where: str) -> list[Problem]:
    """record の kind が語彙の表で別の配列の種類なら、書く場所の案内つきの問題（record_section_mismatch）。

    build_ir が現在の状態の記録に当てる（違う section に書いて取り消した行は問題にしない）。
    知らない kind・kind の無い record はここでは見ない（build_ir の最後の okura_ir.validate が unknown_kind などにする）。
    """
    kind = record.get("kind") if isinstance(record, Mapping) else None
    expected = SECTION_OF_KIND.get(kind) if isinstance(kind, str) else None
    if expected is None or expected == section:
        return []
    place = PLACE_NAMES[_PRIMARY_OF_KIND[kind]]
    return [
        Problem(
            f"{where}.section",
            "record_section_mismatch",
            f"kind {kind!r} は section {expected!r} の種類（{place}に書く。README §4.3 の表）",
        )
    ]


def _split_lines(data: bytes, source: str) -> tuple[list[bytes], list[Problem]]:
    if len(data) > MAX_LEDGER_BYTES:
        return [], [Problem(source, "ledger_too_large", f"台帳が大きすぎる（上限 {MAX_LEDGER_BYTES} バイト）")]
    if data.startswith(b"\xef\xbb\xbf"):
        return [], [Problem(source, "ledger_bom", "BOM がある（BOM なしの UTF-8 にする）")]
    try:
        data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        return [], [Problem(source, "ledger_not_utf8", f"UTF-8 として正しくない（{exc.start} バイト目）")]
    if b"\r" in data:
        return [], [Problem(source, "ledger_cr", "CR がある（改行は LF だけ）")]
    if not data:
        return [], []
    if not data.endswith(b"\n"):
        return [], [Problem(source, "ledger_no_final_newline", "最後の行が LF で終わっていない（書きかけの行か）")]
    return data[:-1].split(b"\n"), []


def _field_problem(where: str, message: str) -> Problem:
    return Problem(where, "entry_field", message)


def _check_entry(obj: Any, line_no: int, where: str, spec: LedgerSpec) -> tuple[Entry | None, list[Problem]]:
    if not isinstance(obj, dict):
        return None, [_field_problem(where, "行は JSON のオブジェクトでなければならない")]
    problems: list[Problem] = []
    for key in sorted(set(obj) - _KEYS):
        problems.append(_field_problem(f"{where}.{key}", f"知らないキー {key!r}"))
    for key in ("ledger", "entry_id", "recorded_at", "recorded_by", "op", "section", "prev_sha256"):
        if key not in obj:
            problems.append(_field_problem(f"{where}.{key}", f"{key} が必要"))
    if problems:
        return None, problems

    if obj["ledger"] != spec.name:
        problems.append(Problem(f"{where}.ledger", "entry_ledger_mismatch", f"この台帳の行ではない（{spec.name!r} が必要）"))
    entry_id = obj["entry_id"]
    if not (isinstance(entry_id, str) and _ID_RE.fullmatch(entry_id)):
        problems.append(_field_problem(f"{where}.entry_id", "entry_id は ASCII の ID（英数字で始まり英数字と _ . : - で64文字まで）"))
    if parse_datetime(obj["recorded_at"]) is None:
        problems.append(_field_problem(f"{where}.recorded_at", "recorded_at は実在する日時（YYYY-MM-DDTHH:MM:SS と時差）"))
    by = obj["recorded_by"]
    if not (
        isinstance(by, dict)
        and len(by) == 1
        and (
            ("person" in by and isinstance(by["person"], str) and _ID_RE.fullmatch(by["person"]))
            or ("label" in by and isinstance(by["label"], str) and _NAME_RE.fullmatch(by["label"]))
        )
    ):
        problems.append(_field_problem(f"{where}.recorded_by", 'recorded_by は {"person": 人の ID} か {"label": 名前}'))
    op = obj["op"]
    if op not in _OPS:
        problems.append(Problem(f"{where}.op", "entry_op", "op は add・correct・delete のどれか"))
    section = obj["section"]
    if section not in spec.sections:
        problems.append(_field_problem(f"{where}.section", f"section は {', '.join(spec.sections)} のどれか"))
    replaces = obj.get("replaces")
    reason = obj.get("reason")
    record = obj.get("record")
    if op == "add":
        if "replaces" in obj:
            problems.append(Problem(f"{where}.replaces", "entry_op", "add の行は replaces を持たない（訂正は correct）"))
        if "reason" in obj:
            problems.append(Problem(f"{where}.reason", "entry_op", "reason は correct・delete の行だけ"))
    elif op in ("correct", "delete"):
        if not (isinstance(replaces, str) and _ID_RE.fullmatch(replaces)):
            problems.append(Problem(f"{where}.replaces", "entry_op", f"{op} の行には replaces（置き換える行の entry_id）が必要"))
        if not (isinstance(reason, str) and _TEXT_RE.fullmatch(reason)):
            problems.append(Problem(f"{where}.reason", "entry_op", f"{op} の行には reason（訂正・削除の理由）が必要"))
    if op == "delete":
        if "record" in obj:
            problems.append(Problem(f"{where}.record", "entry_op", "delete の行は record を持たない"))
    elif op in ("add", "correct"):
        if not isinstance(record, dict):
            problems.append(_field_problem(f"{where}.record", "record（中間表現の1件のオブジェクト）が必要"))
        elif not (isinstance(record.get("id"), str) and _ID_RE.fullmatch(record["id"])):
            problems.append(_field_problem(f"{where}.record.id", "record.id は ASCII の ID"))
    prev = obj["prev_sha256"]
    if not (prev is None or (isinstance(prev, str) and _SHA_RE.fullmatch(prev))):
        problems.append(_field_problem(f"{where}.prev_sha256", "prev_sha256 は null か小文字の16進64桁"))
    if problems:
        return None, problems
    entry = Entry(
        line=line_no,
        entry_id=entry_id,
        recorded_at=obj["recorded_at"],
        recorded_by=dict(by),
        op=op,
        section=section,
        replaces=replaces if op != "add" else None,
        reason=reason if op != "add" else None,
        record=record if op != "delete" else None,
        prev_sha256=prev,
        line_sha256="",
    )
    return entry, spec.check_record(entry, where)


def parse(data: bytes, spec: LedgerSpec, source: str) -> tuple[tuple[Entry, ...], list[Problem]]:
    """台帳のバイト列を行に分けて検査する。(検査に通った行, 問題)。純粋関数。

    行ごとの検査（JSON の厳密な読み込み・キーと型）と、行どうしの検査（entry_id の重複、記録日時の順、
    prev_sha256 の連鎖）を行う。置き換えの整合は fold で確かめる。
    """
    lines, problems = _split_lines(data, source)
    entries: list[Entry] = []
    seen_ids: dict[str, int] = {}
    previous_line: bytes | None = None
    previous_time: _dt.datetime | None = None
    for index, raw in enumerate(lines):
        line_no = index + 1
        where = f"{source}:{line_no}"
        expected_prev = None if previous_line is None else _sha(previous_line)
        previous_line = raw
        if not raw:
            problems.append(Problem(where, "ledger_blank_line", "空の行がある"))
            continue
        if len(raw) > MAX_LINE_BYTES:
            problems.append(Problem(where, "ledger_line_too_long", f"行が長すぎる（上限 {MAX_LINE_BYTES} バイト）"))
            continue
        obj, load_problems = loads(raw, max_bytes=MAX_LINE_BYTES)
        if load_problems:
            problems.extend(Problem(where, p.code, p.message) for p in load_problems)
            continue
        entry, entry_problems = _check_entry(obj, line_no, where, spec)
        if isinstance(obj, dict) and "prev_sha256" in obj and obj["prev_sha256"] != expected_prev:
            entry_problems.append(
                Problem(
                    f"{where}.prev_sha256",
                    "chain_broken",
                    "前の行の SHA-256 と合わない（前の行が書き換えられた・消された・並べ替えられたか）"
                    if expected_prev is not None
                    else "最初の行の prev_sha256 は null",
                )
            )
        if entry is None:
            problems.extend(entry_problems)
            continue
        if entry.entry_id in seen_ids:
            entry_problems.append(
                Problem(f"{where}.entry_id", "entry_id_duplicate", f"entry_id {entry.entry_id!r} が重複（{source}:{seen_ids[entry.entry_id]} と）")
            )
        recorded = parse_datetime(entry.recorded_at)
        if previous_time is not None and recorded is not None and recorded < previous_time:
            entry_problems.append(Problem(f"{where}.recorded_at", "entry_time_order", "記録日時が前の行より前（追記のみ）"))
        if recorded is not None and (previous_time is None or recorded > previous_time):
            previous_time = recorded
        problems.extend(entry_problems)
        if entry_problems:
            continue
        seen_ids[entry.entry_id] = line_no
        entries.append(dataclasses.replace(entry, line_sha256=_sha(raw)))
    return tuple(entries), problems


def fold(entries: Iterable[Entry], spec: LedgerSpec, source: str) -> tuple[LedgerState, list[Problem]]:
    """行の列を現在の状態に畳み込む。純粋関数。

    置き換えの検査：replaces の行が無い（前の行だけを指せる）、section が違う、delete の行を置き換える、
    1つの行を2つの行が置き換える（分岐）。現在の状態で record.id が重複していれば問題にする。
    """
    problems: list[Problem] = []
    by_id: dict[str, Entry] = {}
    replaced_by: dict[str, str] = {}
    accepted: list[Entry] = []
    for entry in entries:
        where = f"{source}:{entry.line}"
        if entry.replaces is not None:
            target = by_id.get(entry.replaces)
            if target is None:
                problems.append(Problem(f"{where}.replaces", "entry_replaces_unknown", f"置き換える行 {entry.replaces!r} が前に無い"))
                continue
            if target.section != entry.section:
                problems.append(Problem(f"{where}.replaces", "entry_replaces_section", f"置き換える行と section が違う（{target.section}）"))
                continue
            if target.op == "delete":
                problems.append(Problem(f"{where}.replaces", "entry_replaces_deleted", "取り消しの行は置き換えられない（新しく add する）"))
                continue
            if entry.replaces in replaced_by:
                problems.append(
                    Problem(f"{where}.replaces", "entry_fork", f"行 {entry.replaces!r} はすでに {replaced_by[entry.replaces]!r} が置き換えた（分岐）")
                )
                continue
            replaced_by[entry.replaces] = entry.entry_id
        by_id[entry.entry_id] = entry
        accepted.append(entry)

    records: list[tuple[int, CurrentRecord]] = []
    for entry in accepted:
        if entry.entry_id in replaced_by or entry.op == "delete" or entry.record is None:
            continue
        history = [entry.entry_id]
        root = entry
        while root.replaces is not None:
            root = by_id[root.replaces]
            history.append(root.entry_id)
        records.append(
            (
                root.line,
                CurrentRecord(
                    section=entry.section,
                    record=entry.record,
                    entry_id=entry.entry_id,
                    recorded_at=entry.recorded_at,
                    origin=f"{source}:{entry.line} ({entry.entry_id})",
                    history=tuple(reversed(history)),
                ),
            )
        )
    records.sort(key=lambda item: item[0])
    current = tuple(r for _, r in records)

    seen_records: dict[str, str] = {}
    for rec in current:
        rid = rec.record.get("id")
        if isinstance(rid, str):
            if rid in seen_records:
                problems.append(
                    Problem(rec.origin.split(" ")[0], "record_id_duplicate", f"現在の状態で record.id {rid!r} が重複（{seen_records[rid]} と）")
                )
            else:
                seen_records[rid] = rec.origin
    return LedgerState(spec.name, current), problems


def read(data: bytes, spec: LedgerSpec, source: str) -> tuple[LedgerState, list[Problem]]:
    """parse と fold をまとめて行う。"""
    entries, problems = parse(data, spec, source)
    state, fold_problems = fold(entries, spec, source)
    return state, problems + fold_problems


def _last_line(existing: bytes) -> bytes | None:
    if not existing:
        return None
    body = existing[:-1] if existing.endswith(b"\n") else existing
    return body.rsplit(b"\n", 1)[-1]


def encode_entry(entry: Mapping[str, Any], previous_line: bytes | None) -> bytes:
    """1件を台帳の1行（LF つき）にする。prev_sha256 は previous_line（LF を除く）から計算して入れる。"""
    obj = dict(entry)
    obj["prev_sha256"] = None if previous_line is None else _sha(previous_line)
    text = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return text.encode("utf-8") + b"\n"


def append_entry(existing: bytes, entry: Mapping[str, Any]) -> bytes:
    """既存の台帳のバイト列の後ろに1行を足したバイト列を返す（純粋関数。書き込みは呼び出し側）。"""
    return existing + encode_entry(entry, _last_line(existing))


def append_drafts(existing: bytes, drafts: Any, spec: LedgerSpec, source: str) -> tuple[bytes | None, list[Problem]]:
    """手で書いた下書きの行の列を、既存の台帳の後ろにつなぐ。(足す分のバイト列, 問題)。問題があれば None。純粋関数。

    下書きは行のオブジェクト（README §4.2）から `prev_sha256` を除いたもの。`ledger` は省いてよい（この台帳の名前を入れる）。
    `prev_sha256` は前の行から計算して入れる。つないだ後の台帳全体を parse・fold で検査し、既存の行に問題があればつながない。
    record の中身（中間表現の1件）の検査は build_ir の最後の okura_ir.validate で行う。
    """
    if isinstance(drafts, Mapping):
        drafts = [drafts]
    if not isinstance(drafts, list) or not drafts:
        return None, [Problem(source, "draft_shape", "下書きは行のオブジェクトか、その空でない配列")]
    problems: list[Problem] = []
    for index, draft in enumerate(drafts):
        where = f"{source}[{index}]"
        if not isinstance(draft, Mapping):
            problems.append(Problem(where, "draft_shape", "下書きの行は JSON のオブジェクト"))
        elif "prev_sha256" in draft:
            problems.append(Problem(f"{where}.prev_sha256", "draft_shape", "prev_sha256 は書かない（前の行から計算して入れる）"))
    if problems:
        return None, problems
    data = existing
    for draft in drafts:
        entry = dict(draft)
        entry.setdefault("ledger", spec.name)
        try:
            data = append_entry(data, entry)
        except (TypeError, ValueError) as exc:  # JSON にできない値（下書きは okura_ir.loads で読んだものなら起きない）
            return None, [Problem(source, "draft_shape", f"JSON にできない値がある（{type(exc).__name__}）")]
    _, problems = read(data, spec, source)
    if problems:
        return None, problems
    return data[len(existing) :], []

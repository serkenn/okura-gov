"""vocabulary.py の表から schema/ir.schema.json を作る。

使い方（packages/ir で）：
  <python> -I -X utf8 -m okura_ir.build_schema --check   # ファイルが表と一致するかだけ確かめる（終了コード 0/1）
  <python> -I -X utf8 -m okura_ir.build_schema --write   # ファイルを書き直す

ir.schema.json を直接編集しない。語彙を変えるときは vocabulary.py を直して --write する。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

from . import vocabulary as v

SCHEMA_PATH = Path(__file__).resolve().parent / "schema" / "ir.schema.json"


def _roles_schema(roles: dict[str, bool] | Any) -> dict[str, Any]:
    return v.obj({name: v.Field(v.PERSON, required) for name, required in roles.items()})


def _when_schema(when: str | None) -> Any:
    if when is None:
        return False
    return v.ref(v.WHEN_DEFS[when])


def _record_branch(kind: v.RecordKind) -> dict[str, Any]:
    required: list[str] = []
    if any(f.required for f in kind.amounts.values()):
        required.append("amounts")
    if any(f.required for f in kind.attributes.values()):
        required.append("attributes")
    branch: dict[str, Any] = {"$comment": f"{kind.vocab} {kind.title}"}
    if required:
        branch["required"] = required
    branch["properties"] = {
        "kind": {"const": kind.kind},
        "roles": _roles_schema(kind.roles),
        "when": _when_schema(kind.when),
        "amounts": v.obj(kind.amounts) if kind.amounts else False,
        "attributes": v.obj(kind.attributes) if kind.attributes else False,
    }
    return branch


def _record_def(description: str, kinds: Iterable[v.RecordKind], *, allow_mark: bool) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "id": v.ID,
        "kind": {"type": "string"},
        "roles": {},
        "when": {},
        "amounts": {},
        "attributes": {},
    }
    if allow_mark:
        properties["mark"] = v.ref("mark")
    properties.update({"source": v.ref("source"), "recorded_at": v.DATETIME, "note": v.TEXT})
    return {
        "description": description,
        "type": "object",
        "required": ["id", "kind", "roles", "when"],
        "additionalProperties": False,
        "properties": properties,
        "oneOf": [_record_branch(k) for k in kinds],
    }


def _ledger_branch(kind: v.LedgerKind, *, has_mark: bool) -> dict[str, Any]:
    required: list[str] = []
    if kind.when is not None:
        required.append("when")
    properties: dict[str, Any] = {
        "kind": {"const": kind.kind},
        "subject": v.obj(kind.subject),
        "when": _when_schema(kind.when),
        "value": kind.value,
    }
    if has_mark:
        if kind.mark is not None:
            required.append("mark")
            properties["mark"] = v.enum(kind.mark)
        else:
            properties["mark"] = v.enum(v.MARK_FORECAST)
    branch: dict[str, Any] = {"$comment": f"{kind.vocab} {kind.title}"}
    if required:
        branch["required"] = required
    branch["properties"] = properties
    return branch


def _ledger_def(
    description: str,
    kinds: Iterable[v.LedgerKind],
    *,
    actor_key: str,
    actor_schema: Any,
    time_key: str,
    replaces_ref: str,
    has_mark: bool,
) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "id": v.ID,
        "kind": {"type": "string"},
        actor_key: actor_schema,
        time_key: v.DATETIME,
        "subject": {},
        "when": {},
        "value": {},
    }
    if has_mark:
        properties["mark"] = {}
    properties.update(
        {"basis": v.ref("basis"), "replaces": v.ref(replaces_ref), "recorded_at": v.DATETIME, "note": v.TEXT}
    )
    return {
        "description": description,
        "type": "object",
        "required": ["id", "kind", actor_key, time_key, "subject", "value"],
        "additionalProperties": False,
        "properties": properties,
        "oneOf": [_ledger_branch(k, has_mark=has_mark) for k in kinds],
    }


_SECTION_DESCRIPTIONS = {
    "relations": "人と人の関係（区間つき。VOC §1.2）",
    "residences": "各人の住所の市町村（住民票の記録・住民税を課す市町村）",
    "insurance_memberships": "加入している保険と保険者（医療保険・年金）",
    "facts": "役割つきの事実（人の属性・取引・書類・処分。VOC §1.1・§1.3・§1.4）",
    "assets": "資産・物件・契約の台帳（VOC §1.5）",
    "filed_documents": "提出した書類の記載（VOC F-D01・F-D02）",
}
_SECTION_DEFS = {
    "relations": "relation",
    "residences": "residence",
    "insurance_memberships": "insurance_membership",
    "facts": "fact",
    "assets": "asset",
    "filed_documents": "filed_document",
    "judgments": "judgment",
    "choices": "choice",
}


def _collect_refs(node: Any, found: set[str]) -> None:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            found.add(ref)
        for value in node.values():
            _collect_refs(value, found)
    elif isinstance(node, list):
        for value in node:
            _collect_refs(value, found)


def build_schema() -> dict[str, Any]:
    """語彙の表から JSON Schema（dict）を作る。決定的（同じ表なら同じ結果）。"""
    defs: dict[str, Any] = dict(v.COMMON_DEFS)
    for section, kinds in v.RECORD_SECTIONS.items():
        defs[_SECTION_DEFS[section]] = _record_def(
            _SECTION_DESCRIPTIONS[section], kinds, allow_mark=section != "filed_documents"
        )
    defs["judgment"] = _ledger_def(
        "判断台帳：人の判断（判断.*）・予測（見込み.*）・法令が求める見積り（見積り.*）・申告の計画（計画.*）",
        v.JUDGMENT_KINDS,
        actor_key="judged_by",
        actor_schema=v.ref("judge"),
        time_key="judged_at",
        replaces_ref="ref_judgment",
        has_mark=True,
    )
    defs["choice"] = _ledger_def(
        "納税者の選択（選択.*）。提出した後は filed_documents の記載になる",
        v.CHOICE_KINDS,
        actor_key="chosen_by",
        actor_schema=v.PERSON,
        time_key="chosen_at",
        replaces_ref="ref_choice",
        has_mark=False,
    )

    # 使われている ref_kind_<kind> の定義を足す
    used: set[str] = set()
    _collect_refs(defs, used)
    prefix = "#/$defs/ref_kind_"
    all_kinds = {k.kind for kinds in v.RECORD_SECTIONS.values() for k in kinds}
    for ref in sorted(used):
        if ref.startswith(prefix):
            kind = ref[len(prefix) :]
            if kind not in all_kinds:
                raise ValueError(f"知らない kind への参照: {kind}")
            defs[f"ref_kind_{kind}"] = {"description": f"kind が {kind} の記録の id への参照", "$ref": "#/$defs/id"}

    sections = list(v.RECORD_SECTIONS) + list(v.LEDGER_SECTIONS)
    properties: dict[str, Any] = {
        "schema_version": {"type": "string", "const": v.SCHEMA_VERSION},
        "persons": v.array(v.ref("person")),
    }
    for section in sections:
        properties[section] = v.array(v.ref(_SECTION_DEFS[section]), min_items=0)
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:okura-gov:ir:0",
        "title": "okura-gov 中間表現（版 0）",
        "description": (
            "記録・事実台帳・判断台帳から作る、判定コアへの入力。役割つきの事実を明細の粒度で持ち、"
            "法令の区分を含めない（HANDOFF D3・D5 改）。金額は整数の円、率は {num, den} の整数の分数で、"
            "数の欄に文字列を置かない。"
        ),
        "type": "object",
        "required": ["schema_version", "persons", *sections],
        "additionalProperties": False,
        "properties": properties,
        "$defs": defs,
    }


def render(schema: dict[str, Any]) -> str:
    return json.dumps(schema, ensure_ascii=False, indent=1) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ir.schema.json を語彙の表から作る")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="ファイルが表と一致するかを確かめる")
    group.add_argument("--write", action="store_true", help="ファイルを書き直す")
    args = parser.parse_args(argv)
    text = render(build_schema())
    if args.write:
        SCHEMA_PATH.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {SCHEMA_PATH.name} ({len(text.encode('utf-8'))} bytes)")
        return 0
    current = SCHEMA_PATH.read_text(encoding="utf-8") if SCHEMA_PATH.exists() else ""
    if current != text:
        print("ir.schema.json は vocabulary.py と一致しない（--write で作り直す）", file=sys.stderr)
        return 1
    print("ir.schema.json は vocabulary.py と一致する")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

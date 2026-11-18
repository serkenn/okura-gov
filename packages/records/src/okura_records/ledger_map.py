"""語彙の種類ごとの書く場所（台帳の取引・事実台帳・判断台帳）と、書き方の表（README の生成した節）。標準ライブラリと okura_ir だけ。

書く場所の決め方（語彙の表 `okura_ir.vocabulary` から機械的に決める。種類ごとの手書きの対応表は持たない）：
  - 取引（VOC の ID が F-T で始まる facts の種類）：台帳（beancount）の取引のメタデータ `fact_kind` に書く。
    家計の台帳に記帳していない入出金（家族の別の人の口座、台帳を付け始める前の分など）は、事実台帳の facts にも書ける。
  - それ以外の記録（relations・residences・insurance_memberships・facts・assets・filed_documents）と人（persons）：事実台帳。
  - 判断・予測・見積り・計画（judgments）と選択（choices）：判断台帳。

`python -I -X utf8 -m okura_records.ledger_map --check README.md`（`--write` で書き換える）で README の生成した節を確かめる。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from okura_ir import vocabulary as irv

__all__ = [
    "FACTS_LEDGER",
    "GUIDE_BEGIN",
    "GUIDE_END",
    "JUDGMENTS_LEDGER",
    "PLACEMENTS",
    "Placement",
    "SECTION_OF_KIND",
    "TRANSACTION",
    "guide_markdown",
    "replace_guide",
]

TRANSACTION = "transaction"  # 台帳（beancount）の取引のメタデータ
FACTS_LEDGER = "facts"  # 事実台帳（okura-facts/0）
JUDGMENTS_LEDGER = "judgments"  # 判断台帳（okura-judgments/0）
PLACE_NAMES = {TRANSACTION: "台帳の取引", FACTS_LEDGER: "事実台帳", JUDGMENTS_LEDGER: "判断台帳"}

GUIDE_BEGIN = "<!-- BEGIN ledger_guide（python -I -X utf8 -m okura_records.ledger_map --write README.md で作る。手で直さない） -->"
GUIDE_END = "<!-- END ledger_guide -->"


@dataclass(frozen=True)
class Placement:
    """種類の書く場所。primary が原則の場所、also はほかに書ける場所。"""

    section: str  # 中間表現の配列の名前
    kind: str
    vocab: str
    title: str
    primary: str
    also: tuple[str, ...] = ()


def _placements() -> tuple[Placement, ...]:
    out: list[Placement] = []
    for section, kinds in irv.RECORD_SECTIONS.items():
        for k in kinds:
            if section == "facts" and k.vocab.startswith("F-T"):
                out.append(Placement(section, k.kind, k.vocab, k.title, TRANSACTION, (FACTS_LEDGER,)))
            else:
                out.append(Placement(section, k.kind, k.vocab, k.title, FACTS_LEDGER))
    for section, ledger_kinds in irv.LEDGER_SECTIONS.items():
        for lk in ledger_kinds:
            out.append(Placement(section, lk.kind, lk.vocab, lk.title, JUDGMENTS_LEDGER))
    return tuple(out)


PLACEMENTS: tuple[Placement, ...] = _placements()
SECTION_OF_KIND: Mapping[str, str] = MappingProxyType({p.kind: p.section for p in PLACEMENTS})

if len(SECTION_OF_KIND) != len(PLACEMENTS):  # 語彙の表で kind の名前が配列をまたいで重なったら気づく
    raise RuntimeError("kind の名前が配列をまたいで重なっている")


# ---------------------------------------------------------------------------
# 欄の型の短い説明（README の表）
# ---------------------------------------------------------------------------

_REF_WORDS = {
    "date": "日付",
    "datetime": "日時",
    "year": "年",
    "yen": "円",
    "signed_yen": "円（負も可）",
    "count": "整数",
    "name": "名称",
    "text": "文",
    "code": "符号",
    "id": "ID",
    "transaction_id": "取引ID",
    "sha256": "SHA-256",
    "municipality_code": "団体コード",
    "country_code": "国の符号",
    "currency_code": "通貨の符号",
    "fraction": "分数",
    "rate": "率",
    "ratio": "割合",
    "period": "区間",
    "ref_person": "人",
    "ref_record": "記録のID",
    "ref_fact": "factsのID",
    "ref_asset": "assetsのID",
    "ref_judgment": "judgmentsのID",
    "ref_choice": "choicesのID",
}
_WHEN_WORDS = {
    irv.WHEN_ON: "日付",
    irv.WHEN_PERIOD: "区間",
    irv.WHEN_ON_OR_PERIOD: "日付か区間",
    irv.WHEN_TAX_YEAR: "年分",
    irv.WHEN_FISCAL_YEAR: "年度",
    None: "なし",
}


def _type_word(schema: Any) -> str:
    if not isinstance(schema, Mapping):
        return "?"
    ref = schema.get("$ref")
    if isinstance(ref, str):
        name = ref.rsplit("/", 1)[-1]
        if name.startswith("ref_kind_"):
            return f"{name[len('ref_kind_'):]}のID"
        return _REF_WORDS.get(name, name)
    if "enum" in schema:
        return "列挙（" + "・".join(f"`{v}`" for v in schema["enum"]) + "）"
    kind = schema.get("type")
    if kind == "boolean":
        return "真偽"
    if kind == "string":
        return "文字列"
    if kind == "array":
        return _type_word(schema.get("items")) + "の並び"
    if kind == "object":
        if "oneOf" in schema:
            return "／".join(_type_word(s) for s in schema["oneOf"])
        props = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        parts = [f"{name}: {_type_word(sub)}" for name, sub in props.items() if name in required]
        optional = [name for name in props if name not in required]
        if optional:
            parts.append("任意 " + "・".join(optional))
        return "{" + "; ".join(parts) + "}"
    return "?"


def _fields(groups: Sequence[tuple[str, Mapping[str, Any]]]) -> tuple[str, str]:
    """(必須の欄, 任意の欄) の説明。groups は (接頭辞, 名前 → Field か 必須の真偽)。"""
    required: list[str] = []
    optional: list[str] = []
    for prefix, fields in groups:
        for name, f in fields.items():
            if isinstance(f, bool):  # roles（役割 → 必須か）。値は人の ID
                (required if f else optional).append(f"{prefix}{name}" + (": 人" if f else ""))
            elif f.required:
                required.append(f"{prefix}{name}: {_type_word(f.schema)}")
            else:
                optional.append(f"{prefix}{name}")
    return ("<br>".join(required) or "—"), ("・".join(optional) or "—")


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def _record_row(p: Placement, k: irv.RecordKind) -> str:
    req, opt = _fields((("roles.", k.roles), ("amounts.", k.amounts), ("attributes.", k.attributes)))
    place = PLACE_NAMES[p.primary] + "".join(f"（{PLACE_NAMES[a]}にも書ける）" for a in p.also)
    when = _WHEN_WORDS[k.when]
    if p.primary == TRANSACTION:
        when = "取引の日付" + ("（区間はメタデータ period）" if k.when in (irv.WHEN_ON_OR_PERIOD, irv.WHEN_PERIOD) else "")
    return f"| {p.section} | `{p.kind}` | {p.vocab} | {place} | {when} | {_cell(req)} | {_cell(opt)} |"


def _ledger_row(p: Placement, k: irv.LedgerKind) -> str:
    req, opt = _fields((("subject.", k.subject),))
    value = _type_word(k.value) if k.value is not False else "なし"
    mark = f"`{k.mark}`（必須）" if k.mark else "—"
    return f"| {p.section} | `{p.kind}` | {p.vocab} | {_WHEN_WORDS[k.when]} | {_cell(req)} | {_cell(opt)} | {_cell(value)} | {mark} |"


def guide_markdown() -> str:
    """種類ごとの書く場所と必須の欄の表（README の生成した節の中身）。語彙の表から決定的に作る。"""
    records = {k.kind: k for kinds in irv.RECORD_SECTIONS.values() for k in kinds}
    ledgers = {k.kind: k for kinds in irv.LEDGER_SECTIONS.values() for k in kinds}
    tx = [p for p in PLACEMENTS if p.primary == TRANSACTION]
    facts = [p for p in PLACEMENTS if p.primary == FACTS_LEDGER]
    judg = [p for p in PLACEMENTS if p.primary == JUDGMENTS_LEDGER]
    record_head = "| 配列 | kind | VOC | 書く場所 | when | 必須の欄 | 任意の欄 |\n|---|---|---|---|---|---|---|"
    lines = [
        f"種類の数：台帳の取引 {len(tx)}、事実台帳 {len(facts)}（ほかに persons）、判断台帳 {len(judg)}（judgments "
        f"{sum(1 for p in judg if p.section == 'judgments')}・choices {sum(1 for p in judg if p.section == 'choices')}）、合計 {len(PLACEMENTS)}。",
        "型の語：人＝persons の id、`<kind>のID`＝その種類の記録の id、円＝整数の円、割合・率・分数＝`{\"num\": 整数, \"den\": 整数}`、"
        "区間＝`{\"from_on\": 日付, \"to_on\": 日付}`（`to_on` は任意）、並び＝配列。",
        "",
        "#### 台帳の取引（beancount のメタデータ。値の書き方は §4.1）",
        "",
        record_head,
        *(_record_row(p, records[p.kind]) for p in tx),
        "",
        "#### 事実台帳（`record` に中間表現の1件を書く。§4.2）",
        "",
        record_head,
        "| persons | （種類なし） | F-P01〜F-P03 | 事実台帳 | なし | id: ID<br>birth_on: 日付 | death_on |",
        *(_record_row(p, records[p.kind]) for p in facts),
        "",
        "#### 判断台帳（`record` に判断・選択の1件を書く。§4.2）",
        "",
        "| 配列 | kind | VOC | when | 必須の欄 | 任意の欄 | value | mark |\n|---|---|---|---|---|---|---|---|",
        *(_ledger_row(p, ledgers[p.kind]) for p in judg),
    ]
    return "\n".join(lines) + "\n"


def replace_guide(readme: str) -> str | None:
    """README の生成した節（GUIDE_BEGIN〜GUIDE_END）を今の表で置き換えた文字列。印が無ければ None。"""
    start = readme.find(GUIDE_BEGIN)
    end = readme.find(GUIDE_END)
    if start < 0 or end < start:
        return None
    body = "\n\n" + guide_markdown() + "\n"
    if "\r\n" in readme:  # README の改行（CRLF か LF）に合わせる
        body = body.replace("\n", "\r\n")
    return readme[: start + len(GUIDE_BEGIN)] + body + readme[end:]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="okura_records.ledger_map", description="README の種類ごとの書き方の表を作る・確かめる")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", metavar="README", help="生成した節が今の語彙の表と一致するか確かめる")
    group.add_argument("--write", metavar="README", help="生成した節を書き換える")
    args = parser.parse_args(argv)
    path = args.check or args.write
    with open(path, "rb") as fh:
        text = fh.read().decode("utf-8")
    updated = replace_guide(text)
    if updated is None:
        sys.stderr.write("README に生成した節の印が無い\n")
        return 1
    if args.check:
        if updated != text:
            sys.stderr.write("README の表が語彙の表と一致しない（--write で作り直す）\n")
            return 1
        return 0
    with open(path, "wb") as fh:
        fh.write(updated.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

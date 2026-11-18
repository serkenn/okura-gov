"""beancount の台帳に書くメタデータの語彙（キーの一覧と、値の書き方）。

語彙の元は okura_ir の語彙の表（`okura_ir.vocabulary`。VOC＝docs/hypotheses/20261109_round3_design-vocabulary.md）。
取引から作れる事実の種類は、VOC §1.3 の取引（ID が F-T で始まるもの）だけ。人の属性・関係・書類・資産などは事実台帳に書く。

取引のメタデータのキー：
  id          取引 ID（必須。中間表現の ID と同じ形：英数字で始まる ASCII、64文字まで）。事実の ID にもなる
  fact_kind   事実の種類（F-T の kind。例 medical_payment）。無い取引は事実にしない（ただの記帳）
  mark        状態の印（"見積り"・"計画"・"予測"）
  note        中間表現の note に写す説明。narration・payee は中間表現に写さない（人の名前を含みうるため）
  period      時を区間で持つ種類（benefit_receipt）のときの区間 "YYYY-MM-DD/YYYY-MM-DD"（終わりが無ければ "YYYY-MM-DD/.."）
  memo        自由な覚え書き（中間表現に写さない）
  x_*・x-*    利用者の自由なキー（中間表現に写さない）
  その他      fact_kind の種類の役割（payer・patient など。値は人の ID）・attributes・amounts の欄の名前
posting のメタデータのキー：fact_amount（その posting の金額を入れる amounts の欄の名前）、memo、x_*。
document のメタデータのキー：transaction_id（証憑が属する取引 ID）、memo、x_*。

値の書き方（欄の型ごと。build_ir が変換する）：
  人・記録の ID、名称、説明、符号、列挙   文字列 "…"（名称・説明は日本語でよい）
  日付                                   2026-02-10（beancount の日付）
  真偽                                   TRUE / FALSE
  個数・年                               整数 3
  金額（整数の円）                        1500 JPY（JPY の整数だけ）
  割合・率・分数                          文字列 "3/10"
  区間                                   文字列 "2026-01-01/2026-03-31"（終わりが無ければ "2026-01-01/.."）
  ID・列挙の並び                          空白で区切った文字列 "medical_treatment hospitalization"
  日付の並び（prepaid_due_dates など）     空白で区切った文字列 "2026-11-30 2026-12-31"（各日付は YYYY-MM-DD。並びは書いた順のまま）
  外貨の額（foreign_amount）              12.34 USD（beancount の金額。小数は分数に直す）
"""

from __future__ import annotations

import re
from types import MappingProxyType
from typing import Any, Mapping

from okura_ir import vocabulary as irv

__all__ = [
    "DOCUMENT_KEYS",
    "FACT_KEYS",
    "POSTING_KEYS",
    "RESERVED_TRANSACTION_KEYS",
    "TRANSACTION_FACT_KINDS",
    "TRANSACTION_KEYS",
    "fact_keys",
    "field_shape",
    "is_auto_key",
    "is_free_key",
]

TRANSACTION_FACT_KINDS: Mapping[str, irv.RecordKind] = MappingProxyType(
    {k.kind: k for k in irv.FACT_KINDS if k.vocab.startswith("F-T")}
)

RESERVED_TRANSACTION_KEYS = frozenset({"id", "fact_kind", "mark", "note", "period", "memo"})
POSTING_KEYS = frozenset({"fact_amount", "memo"})
DOCUMENT_KEYS = frozenset({"transaction_id", "memo"})
_FREE_KEY = re.compile(r"x[-_][A-Za-z0-9_\-]+", re.ASCII)


def fact_keys(kind: irv.RecordKind) -> frozenset[str]:
    """その種類の事実で取引のメタデータに書けるキー（役割・attributes・amounts の欄）。"""
    return frozenset(kind.roles) | frozenset(kind.attributes) | frozenset(kind.amounts)


FACT_KEYS: frozenset[str] = frozenset().union(*(fact_keys(k) for k in TRANSACTION_FACT_KINDS.values()))
TRANSACTION_KEYS: frozenset[str] = RESERVED_TRANSACTION_KEYS | FACT_KEYS

if RESERVED_TRANSACTION_KEYS & FACT_KEYS:  # 語彙の表が変わって名前がぶつかったら気づく
    raise RuntimeError(f"予約したキーと事実の欄の名前がぶつかる: {sorted(RESERVED_TRANSACTION_KEYS & FACT_KEYS)}")


def is_free_key(key: str) -> bool:
    """利用者の自由なキー（memo、x_*、x-*）。中間表現には写さない。"""
    return key == "memo" or bool(_FREE_KEY.fullmatch(key))


def is_auto_key(key: str) -> bool:
    """beancount が自動で付けるメタデータ（filename・lineno・__*__）。"""
    return key in ("filename", "lineno") or key.startswith("__")


# 欄のスキーマ → 値の書き方（shape）
_STRING_DEFS = frozenset(
    {
        "id",
        "transaction_id",
        "name",
        "text",
        "code",
        "sha256",
        "municipality_code",
        "country_code",
        "currency_code",
        "datetime",
    }
)
_INT_DEFS = frozenset({"year", "count"})
_YEN_DEFS = frozenset({"yen", "signed_yen"})
_FRACTION_DEFS = frozenset({"ratio", "rate", "fraction"})


def _ref_name(schema: Mapping[str, Any]) -> str | None:
    ref = schema.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/$defs/"):
        return ref[len("#/$defs/") :]
    return None


def field_shape(schema: Any) -> str:
    """欄のスキーマから、メタデータでの書き方の種類を返す。

    string・date・bool・int・yen・fraction・period・string_list・date_list・foreign_amount・unsupported のどれか。
    """
    if not isinstance(schema, Mapping):
        return "unsupported"
    name = _ref_name(schema)
    if name is not None:
        if name == "date":
            return "date"
        if name in _INT_DEFS:
            return "int"
        if name in _YEN_DEFS:
            return "yen"
        if name in _FRACTION_DEFS:
            return "fraction"
        if name == "period":
            return "period"
        if name in _STRING_DEFS or name.startswith("ref_"):
            return "string"
        return "unsupported"
    kind = schema.get("type")
    if kind == "boolean":
        return "bool"
    if kind == "string":
        return "string"
    if kind == "array":
        item_shape = field_shape(schema.get("items"))
        if item_shape == "string":
            return "string_list"
        if item_shape == "date":
            return "date_list"
        return "unsupported"
    if kind == "object":
        props = schema.get("properties")
        if isinstance(props, Mapping) and set(props) == {"currency", "value"}:
            return "foreign_amount"
    return "unsupported"

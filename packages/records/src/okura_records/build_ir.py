"""中間表現の作成：(正規化した取引 JSON, 事実台帳の状態, 判断台帳の状態) → 中間表現。純粋関数。

**法令の解釈をしない**（D5 改）。所得区分を決めない、合計しない、按分しない、扶養などを判定しない。行うのは：
- 事実台帳・判断台帳の現在の記録を、中間表現の配列にそのまま写す（行の recorded_at を record の recorded_at に写す）。
- `fact_kind` のある取引を、中間表現の事実（facts）の1件にする（明細の粒度。1取引＝1件。事実の ID＝取引 ID）：
  - 役割・attributes：メタデータの値を欄の型に変える（日付・整数・"3/10" → {num, den}・区間・空白区切りの並び〔文字列・日付〕・外貨の額）。
  - amounts：`fact_amount` を付けた posting の金額の絶対値（記帳の向きの符号を捨てる）か、メタデータの `1500 JPY`。
    費用（expenses）の勘定の負の金額・収益（income）の勘定の正の金額（返金・取消しの記帳）には付けられない。
  - when：取引の日付（区間を持つ種類でメタデータ period があれば区間）。
  - source：取引 ID と、その取引を指す document の証憑の SHA-256。
  - narration・payee・勘定科目名は写さない（勘定科目名に法的な意味を持たせない D3・D11、人の名前を写さない）。
- 最後に okura_ir.validate で検査する。問題には出どころ（台帳の行・取引の位置）を付ける。
"""

from __future__ import annotations

import copy
import datetime
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from okura_ir import SCHEMA_VERSION, validate
from okura_ir.vocabulary import RECORD_SECTIONS, WHEN_ON, WHEN_ON_OR_PERIOD, WHEN_PERIOD, YEN_MAX

from . import facts_ledger, judgments_ledger
from .jsonl_ledger import LedgerState, section_problems
from .meta_vocabulary import (
    RESERVED_TRANSACTION_KEYS,
    TRANSACTION_FACT_KINDS,
    FACT_KEYS,
    fact_keys,
    field_shape,
    is_free_key,
)
from .problem import Problem

__all__ = ["BuildResult", "IR_SECTIONS", "build_ir"]

TRANSACTIONS_FORMAT = "okura-transactions/0"  # adapter.FORMAT（adapter は beancount を読み込むので import しない）
IR_SECTIONS: tuple[str, ...] = ("persons", *RECORD_SECTIONS, "judgments", "choices")
_FRACTION_RE = re.compile(r"(-?[0-9]{1,13})/([0-9]{1,13})", re.ASCII)
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", re.ASCII)
_PERIOD_RE = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2})/([0-9]{4}-[0-9]{2}-[0-9]{2}|\.\.)", re.ASCII)
_IR_PATH_RE = re.compile(r"\$\.([a-z_]+)\[([0-9]+)\]")
_FAILED = object()


@dataclass(frozen=True)
class BuildResult:
    """ir は問題が無いときだけ入る（問題があれば None）。"""

    ir: dict[str, Any] | None
    problems: tuple[Problem, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.ir is not None and not self.problems


# ---------------------------------------------------------------------------
# メタデータの値 → 中間表現の欄の値
# ---------------------------------------------------------------------------


def _decimal(text: Any) -> Decimal | None:
    if not isinstance(text, str):
        return None
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() else None


def _integer(value: Decimal | None) -> int | None:
    """小数点の無い整数で、桁あふれしない大きさのものだけ int にする。"""
    if value is None or abs(value) > YEN_MAX:
        return None
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < 0:
        return None
    return int(value)


def _is_date(text: str) -> bool:
    """YYYY-MM-DD の形で実在する日付か（okura_ir の format: date と同じ範囲）。"""
    if not _DATE_RE.fullmatch(text):
        return False
    try:
        datetime.date.fromisoformat(text)
    except ValueError:
        return False
    return True


def _convert(shape: str, typed: Any) -> Any:
    """型つきのメタデータの値を欄の値にする。できなければ _FAILED。"""
    if not isinstance(typed, Mapping) or len(typed) != 1:
        return _FAILED
    (tag, raw), = typed.items()
    if shape == "string":
        return raw if tag == "string" and isinstance(raw, str) else _FAILED
    if shape == "date":
        return raw if tag == "date" and isinstance(raw, str) else _FAILED
    if shape == "bool":
        return raw if tag == "bool" and isinstance(raw, bool) else _FAILED
    if shape == "int":
        number = _integer(_decimal(raw)) if tag == "decimal" else None
        return _FAILED if number is None else number
    if shape == "yen":
        if tag != "amount" or not isinstance(raw, Mapping) or raw.get("currency") != "JPY":
            return _FAILED
        number = _integer(_decimal(raw.get("number")))
        return _FAILED if number is None else number
    if shape == "fraction":
        match = _FRACTION_RE.fullmatch(raw) if tag == "string" and isinstance(raw, str) else None
        return {"num": int(match.group(1)), "den": int(match.group(2))} if match else _FAILED
    if shape == "period":
        match = _PERIOD_RE.fullmatch(raw) if tag == "string" and isinstance(raw, str) else None
        if not match:
            return _FAILED
        period = {"from_on": match.group(1)}
        if match.group(2) != "..":
            period["to_on"] = match.group(2)
        return period
    if shape == "string_list":
        items = raw.split() if tag == "string" and isinstance(raw, str) else []
        return items if items else _FAILED
    if shape == "date_list":
        # 空白区切りの日付。並べ替え・重複の除去はしない（書いた順のまま。数えるのは判定コア）
        items = raw.split() if tag == "string" and isinstance(raw, str) else []
        return items if items and all(_is_date(item) for item in items) else _FAILED
    if shape == "foreign_amount":
        if tag != "amount" or not isinstance(raw, Mapping) or not isinstance(raw.get("currency"), str):
            return _FAILED
        number = _decimal(raw.get("number"))
        if number is None or abs(number) > YEN_MAX:
            return _FAILED
        num, den = number.as_integer_ratio()
        if abs(num) > YEN_MAX or den > YEN_MAX:
            return _FAILED
        return {"currency": raw["currency"], "value": {"num": num, "den": den}}
    return _FAILED


_SHAPE_HINTS = {
    "string": '文字列 "…"',
    "date": "日付 2026-02-10",
    "bool": "TRUE か FALSE",
    "int": "小数点の無い整数",
    "yen": "JPY の整数の金額（1500 JPY）",
    "fraction": '文字列 "分子/分母"（例 "3/10"）',
    "period": '文字列 "YYYY-MM-DD/YYYY-MM-DD"（終わりが無ければ "YYYY-MM-DD/.."）',
    "string_list": '空白で区切った文字列 "a b"',
    "date_list": '空白で区切った日付の文字列 "2026-11-30 2026-12-31"',
    "foreign_amount": "外貨の金額（12.34 USD）",
}


def _value_problem(where: str, key: str, shape: str) -> Problem:
    if shape == "unsupported":
        return Problem(where, "fact_value_type", f"欄 {key!r} は台帳のメタデータに書けない（事実台帳に書く）")
    return Problem(where, "fact_value_type", f"欄 {key!r} の値の書き方が違う（{_SHAPE_HINTS[shape]}）")


# ---------------------------------------------------------------------------
# 取引 → 事実
# ---------------------------------------------------------------------------


def _ref_name(schema: Any) -> str | None:
    if isinstance(schema, Mapping) and isinstance(schema.get("$ref"), str):
        return schema["$ref"].rsplit("/", 1)[-1]
    return None


def _fact_from_transaction(tx: Mapping[str, Any], evidence: Mapping[str, list[str]], problems: list[Problem]) -> dict[str, Any] | None:
    src = tx["source"]
    where = f"{src['file']}:{src['line']}"
    meta: Mapping[str, Any] = tx["meta"]
    postings = tx["postings"]
    marked = [p for p in postings if "fact_amount" in p["meta"]]
    kind_value = meta.get("fact_kind")
    if kind_value is None:
        stray = sorted(k for k in meta if k in FACT_KEYS or k in ("mark", "note", "period"))
        if stray or marked:
            names = stray + (["fact_amount"] if marked else [])
            problems.append(Problem(where, "fact_keys_without_kind", f"fact_kind が無いのに事実の欄がある（{', '.join(names)}）"))
        return None
    kind_name = _convert("string", kind_value)
    if kind_name is _FAILED or kind_name not in TRANSACTION_FACT_KINDS:
        problems.append(
            Problem(where, "fact_kind_unknown", f"取引から作れる事実の種類ではない（{kind_value!r}。F-T の種類：{', '.join(TRANSACTION_FACT_KINDS)}）")
        )
        return None
    kind = TRANSACTION_FACT_KINDS[kind_name]
    before = len(problems)
    if tx["flag"] != "*":
        problems.append(Problem(where, "fact_flag_pending", f"フラグ {tx['flag']!r} の取引は事実にしない（確かめてから * にする）"))
    allowed = fact_keys(kind)
    roles: dict[str, Any] = {}
    amounts: dict[str, Any] = {}
    attributes: dict[str, Any] = {}
    for key in sorted(meta):
        if key in RESERVED_TRANSACTION_KEYS or is_free_key(key):
            continue
        if key not in allowed:
            problems.append(Problem(where, "fact_key_not_for_kind", f"{key!r} は {kind_name} の欄ではない"))
            continue
        if key in kind.roles:
            target, shape = roles, "string"
        elif key in kind.amounts:
            target, shape = amounts, field_shape(kind.amounts[key].schema)
        else:
            target, shape = attributes, field_shape(kind.attributes[key].schema)
        value = _convert(shape, meta[key])
        if value is _FAILED:
            problems.append(_value_problem(where, key, shape))
            continue
        target[key] = value

    for posting in marked:
        field_value = _convert("string", posting["meta"]["fact_amount"])
        if field_value is _FAILED or field_value not in kind.amounts:
            problems.append(
                Problem(where, "fact_amount_field", f"fact_amount は {kind_name} の amounts の欄の名前（{', '.join(kind.amounts)}）")
            )
            continue
        if _ref_name(kind.amounts[field_value].schema) != "yen":
            problems.append(Problem(where, "fact_amount_field", f"{field_value!r} は符号つきの欄なので posting から入れない（メタデータに書く）"))
            continue
        amount = posting["amount"]
        root = posting.get("account_root")
        if (root == "expenses" and amount < 0) or (root == "income" and amount > 0):
            problems.append(
                Problem(
                    where,
                    "fact_amount_reversed",
                    f"費用の減少・収益の減少の posting（{posting['account']} {amount}）に fact_amount は付けられない（返金・取消しを事実の金額にしない）",
                )
            )
            continue
        if field_value in amounts:
            problems.append(Problem(where, "fact_amount_duplicate", f"amounts の {field_value!r} を2か所から入れている（合計しない）"))
            continue
        amounts[field_value] = abs(amount)

    period_value = meta.get("period")
    if period_value is not None:
        period = _convert("period", period_value)
        if kind.when not in (WHEN_ON_OR_PERIOD, WHEN_PERIOD):
            problems.append(Problem(where, "fact_when", f"{kind_name} は日付で持つ種類なので period を書かない（取引の日付を使う）"))
        elif period is _FAILED:
            problems.append(_value_problem(where, "period", "period"))
        when: Any = period
    elif kind.when in (WHEN_ON, WHEN_ON_OR_PERIOD):
        when = {"on": tx["date"]}
    else:
        problems.append(Problem(where, "fact_when", f"{kind_name} は区間で持つ種類なので period が必要"))
        when = None

    fact: dict[str, Any] = {"id": tx["id"], "kind": kind_name, "roles": roles, "when": when}
    if amounts:
        fact["amounts"] = amounts
    if attributes:
        fact["attributes"] = attributes
    for key in ("mark", "note"):
        if key in meta:
            value = _convert("string", meta[key])
            if value is _FAILED:
                problems.append(_value_problem(where, key, "string"))
            else:
                fact[key] = value
    source: dict[str, Any] = {"transaction_ids": [tx["id"]]}
    if evidence.get(tx["id"]):
        source["evidence_sha256"] = sorted(set(evidence[tx["id"]]))
    fact["source"] = source
    return None if len(problems) != before else fact


# ---------------------------------------------------------------------------
# まとめ
# ---------------------------------------------------------------------------


def _copy_state(
    state: LedgerState,
    allowed: tuple[str, ...],
    sections: dict[str, list[Any]],
    origins: dict[str, list[str]],
    problems: list[Problem],
) -> None:
    for current in state.records:
        if current.section not in allowed:
            problems.append(Problem(current.origin, "input_shape", f"この台帳に置けない section {current.section!r}"))
            continue
        mismatch = section_problems(current.section, current.record, current.origin.split(" ")[0])
        if mismatch:
            problems.extend(mismatch)
            continue
        record = copy.deepcopy(dict(current.record))
        if current.section != "persons":
            if "recorded_at" in record:
                problems.append(Problem(current.origin, "record_has_recorded_at", "record に recorded_at を書かない"))
                continue
            record["recorded_at"] = current.recorded_at
        sections[current.section].append(record)
        origins[current.section].append(current.origin)


def _written_twice(facts: list[Any], origins: list[str]) -> list[Problem]:
    """同じ取引を台帳の取引と事実台帳の両方に書いたもの（事実台帳の取引の種類の記録の source.transaction_ids が、
    事実にした台帳の取引を指す）。合計の二重を防ぐための重複の検出で、法令の解釈ではない。"""
    def tx_ids(fact: Any) -> list[Any]:
        source = fact.get("source") if isinstance(fact, Mapping) else None
        ids = source.get("transaction_ids") if isinstance(source, Mapping) else None
        return ids if isinstance(ids, list) else []

    # 台帳の取引から作った事実は id＝取引 ID で、source.transaction_ids がその1つだけ
    from_transactions = {f["id"]: f["kind"] for f in facts if isinstance(f, Mapping) and tx_ids(f) == [f.get("id")]}
    problems: list[Problem] = []
    for fact, origin in zip(facts, origins):
        if not isinstance(fact, Mapping) or fact.get("kind") not in TRANSACTION_FACT_KINDS or fact.get("id") in from_transactions:
            continue
        for tx_id in tx_ids(fact):
            if from_transactions.get(tx_id) == fact["kind"]:
                problems.append(
                    Problem(
                        origin.split(" ")[0],
                        "fact_written_twice",
                        f"取引 {tx_id!r} は台帳の取引から {fact['kind']} の事実にしている（事実台帳に同じ事実を書かない）",
                        origin,
                    )
                )
    return problems


def _origin_for(path: str, origins: Mapping[str, list[str]]) -> str | None:
    match = _IR_PATH_RE.match(path)
    if not match:
        return None
    items = origins.get(match.group(1)) or []
    index = int(match.group(2))
    return items[index] if index < len(items) else None


def build_ir(transactions: Mapping[str, Any], facts: LedgerState, judgments: LedgerState) -> BuildResult:
    """中間表現を作る。純粋関数（入力を書き換えない。同じ入力なら同じ出力）。"""
    problems: list[Problem] = []
    if not isinstance(transactions, Mapping) or transactions.get("format") != TRANSACTIONS_FORMAT:
        problems.append(Problem("(transactions)", "input_shape", f"正規化した取引 JSON（format {TRANSACTIONS_FORMAT!r}）ではない"))
    if not isinstance(facts, LedgerState) or facts.ledger != facts_ledger.LEDGER:
        problems.append(Problem("(facts)", "input_shape", f"事実台帳（{facts_ledger.LEDGER}）の状態ではない"))
    if not isinstance(judgments, LedgerState) or judgments.ledger != judgments_ledger.LEDGER:
        problems.append(Problem("(judgments)", "input_shape", f"判断台帳（{judgments_ledger.LEDGER}）の状態ではない"))
    if problems:
        return BuildResult(None, tuple(problems))

    sections: dict[str, list[Any]] = {name: [] for name in IR_SECTIONS}
    origins: dict[str, list[str]] = {name: [] for name in IR_SECTIONS}
    _copy_state(facts, facts_ledger.SECTIONS, sections, origins, problems)
    _copy_state(judgments, judgments_ledger.SECTIONS, sections, origins, problems)

    try:
        evidence: dict[str, list[str]] = {}
        for doc in transactions.get("documents") or []:
            if "transaction_id" in doc:
                evidence.setdefault(doc["transaction_id"], []).append(doc["sha256"])
        for tx in transactions.get("transactions") or []:
            fact = _fact_from_transaction(tx, evidence, problems)
            if fact is not None:
                sections["facts"].append(fact)
                origins["facts"].append(f"{tx['source']['file']}:{tx['source']['line']} ({tx['id']})")
    except (KeyError, TypeError, AttributeError, IndexError) as exc:
        problems.append(Problem("(transactions)", "input_shape", f"正規化した取引 JSON の形が違う（{type(exc).__name__}: {exc}）"))
    if not problems:
        problems.extend(_written_twice(sections["facts"], origins["facts"]))
    if problems:
        return BuildResult(None, tuple(problems))

    ir: dict[str, Any] = {"schema_version": SCHEMA_VERSION}
    ir.update(sections)
    ir_problems = [Problem(p.path, p.code, p.message, _origin_for(p.path, origins)) for p in validate(ir)]
    if ir_problems:
        return BuildResult(None, tuple(ir_problems))
    return BuildResult(ir, ())

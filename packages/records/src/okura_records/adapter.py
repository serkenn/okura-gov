"""アダプタ：安全に読み込んだ台帳 → 正規化した取引 JSON（形式 `okura-transactions/0`）。

純粋関数（ファイルを読まない。証憑の SHA-256 は safe_loader が取ったものを使う）。法令の解釈をしない：
勘定科目名に意味を持たせず（D3・D11）、所得区分を決めず、合計しない。行うのは型の明示・整数の円への統一・
並べ替え・パスの相対化だけ。

出力の形：

```json
{"format": "okura-transactions/0", "currency": "JPY", "main": "main.beancount",
 "source_files": [{"path": "main.beancount", "sha256": "…", "bytes": 1234}],
 "transactions": [
   {"id": "tx-…", "date": "2026-02-10", "flag": "*", "payee": "…", "narration": "…", "tags": [], "links": [],
    "meta": {"fact_kind": {"string": "medical_payment"}, "incurred_on": {"date": "2026-02-01"}, …},
    "postings": [{"account": "Expenses:Medical", "account_root": "expenses", "amount": 1500, "currency": "JPY",
                  "interpolated": false, "meta": {"fact_amount": {"string": "amount"}}}],
    "source": {"file": "main.beancount", "line": 12}}],
 "documents": [{"date": "2026-02-10", "account": "Expenses:Medical", "path": "receipts/….pdf", "sha256": "…",
                "bytes": 1234, "transaction_id": "tx-…", "tags": [], "links": [], "meta": {}, "source": {…}}]}
```

メタデータの値は型つき：`{"string": …}`・`{"decimal": "…"}`・`{"date": "…"}`・`{"bool": …}`・
`{"amount": {"number": "…", "currency": "…"}}`・`{"null": true}`。
拒否するもの：取引 ID が無い・文字列でない・形が違う・重複、JPY 以外の金額・通貨、小数（`1000.00` の書き方を含む）、
取得価額・価格つきの posting、語彙にないメタデータのキー、`pad`・`price`・`query`・`custom`、
`*`・`!` 以外のフラグ、存在しない取引 ID を指す document。
"""

from __future__ import annotations

import datetime as _dt
import os
import re
from decimal import Decimal
from typing import Any, Mapping

from beancount.core import data as bc_data
from beancount.core.amount import Amount
from okura_ir.vocabulary import COMMON_DEFS, YEN_MAX

from .meta_vocabulary import DOCUMENT_KEYS, POSTING_KEYS, TRANSACTION_KEYS, is_auto_key, is_free_key
from .problem import Problem
from .safe_loader import LoadedLedger

__all__ = ["FORMAT", "normalize", "typed_value"]

FORMAT = "okura-transactions/0"
CURRENCY = "JPY"
_ID_RE = re.compile(COMMON_DEFS["transaction_id"]["pattern"].strip("^$"), re.ASCII)
_SKIPPED = (bc_data.Close, bc_data.Note, bc_data.Event)


def _dec_str(number: Decimal) -> str:
    return str(number)


def typed_value(value: Any) -> dict[str, Any] | None:
    """beancount のメタデータの値を型つきの JSON にする。扱えない型なら None。"""
    if isinstance(value, bool):
        return {"bool": value}
    if isinstance(value, str):
        return {"string": value}
    if isinstance(value, Decimal):
        return {"decimal": _dec_str(value)} if value.is_finite() else None
    if isinstance(value, _dt.date) and not isinstance(value, _dt.datetime):
        return {"date": value.isoformat()}
    if isinstance(value, Amount):
        number, currency = value.number, value.currency
        if isinstance(number, Decimal) and number.is_finite() and isinstance(currency, str):
            return {"amount": {"number": _dec_str(number), "currency": currency}}
        return None
    if value is None:
        return {"null": True}
    return None


def _jpy_int(number: Any) -> tuple[int | None, str | None]:
    """JPY の金額を整数の円にする。(値, 問題の code)。"""
    if not isinstance(number, Decimal) or not number.is_finite():
        return None, "amount_not_integer"
    if abs(number) > YEN_MAX:
        return None, "amount_out_of_range"
    exponent = number.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < 0:
        return None, "amount_not_integer"  # 1000.50 も 1000.00 も拒否する（小数点を書かない）
    return int(number), None


def _where(meta: Mapping[str, Any] | None, ledger: LoadedLedger) -> tuple[str, dict[str, Any]]:
    filename = (meta or {}).get("filename")
    lineno = (meta or {}).get("lineno")
    rel = ledger.relpath(filename) if isinstance(filename, str) and os.path.isabs(filename) else str(filename)
    line = lineno if isinstance(lineno, int) else 0
    return f"{rel}:{line}", {"file": rel, "line": line}


def _meta(
    meta: Mapping[str, Any] | None, allowed: frozenset[str], where: str, problems: list[Problem]
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in sorted(meta or {}):
        if is_auto_key(key):
            continue
        if key not in allowed and not is_free_key(key):
            problems.append(Problem(where, "meta_unknown_key", f"語彙にないメタデータのキー {key!r}（書き間違いか。自由なキーは memo か x_ で始める）"))
            continue
        typed = typed_value(meta[key])  # type: ignore[index]
        if typed is None:
            problems.append(Problem(where, "meta_type", f"メタデータ {key!r} の値の型を扱えない（{type(meta[key]).__name__}）"))  # type: ignore[index]
            continue
        out[key] = typed
    return out


def _amount_problem(code: str, where: str, label: str) -> Problem:
    messages = {
        "amount_not_integer": f"{label}が整数の円でない（小数点を書かない）",
        "amount_out_of_range": f"{label}が大きすぎる（上限 {YEN_MAX} 円）",
    }
    return Problem(where, code, messages[code])


def _posting(posting: Any, ledger: LoadedLedger, where: str, problems: list[Problem]) -> dict[str, Any] | None:
    units = posting.units
    if units is None or not isinstance(units.number, Decimal):
        problems.append(Problem(where, "amount_not_integer", f"金額の無い posting（{posting.account}）"))
        return None
    if units.currency != CURRENCY:
        problems.append(Problem(where, "currency_not_jpy", f"JPY 以外の金額（{units.currency}、{posting.account}）"))
        return None
    amount, code = _jpy_int(units.number)
    if code is not None or amount is None:
        problems.append(_amount_problem(code or "amount_not_integer", where, f"金額（{posting.account}）"))
        return None
    if posting.cost is not None or posting.price is not None:
        problems.append(Problem(where, "cost_or_price", f"取得価額・価格つきの posting は扱わない（{posting.account}）"))
        return None
    meta = posting.meta or {}
    out: dict[str, Any] = {
        "account": posting.account,
        "account_root": ledger.account_roots.get(posting.account.split(":", 1)[0]),
        "amount": amount,
        "currency": CURRENCY,
        "interpolated": bool(meta.get("__automatic__")),
        "meta": _meta(meta, POSTING_KEYS, where, problems),
    }
    if posting.flag:
        out["flag"] = posting.flag
    return out


def _transaction(entry: Any, ledger: LoadedLedger, problems: list[Problem]) -> dict[str, Any] | None:
    where, source = _where(entry.meta, ledger)
    before = len(problems)
    if entry.flag not in ("*", "!"):
        problems.append(Problem(where, "flag_not_supported", f"フラグ {entry.flag!r} の取引は扱わない（* か ! だけ）"))
    tx_id = (entry.meta or {}).get("id")
    if tx_id is None:
        problems.append(Problem(where, "transaction_id_missing", "取引 ID（メタデータ id）が無い"))
    elif not isinstance(tx_id, str):
        problems.append(Problem(where, "transaction_id_type", f"取引 ID が文字列でない（{type(tx_id).__name__}。\"…\" で囲む）"))
    elif not _ID_RE.fullmatch(tx_id):
        problems.append(Problem(where, "transaction_id_pattern", f"取引 ID の形が違う（{tx_id[:80]!r}。英数字で始まり英数字と _ . : - で64文字まで）"))
    meta = _meta(entry.meta, TRANSACTION_KEYS, where, problems)
    postings = []
    for posting in entry.postings:
        p_where, _ = _where(posting.meta, ledger) if posting.meta else (where, None)
        normalized = _posting(posting, ledger, p_where, problems)
        if normalized is not None:
            postings.append(normalized)
    if len(problems) != before:
        return None
    return {
        "id": tx_id,
        "date": entry.date.isoformat(),
        "flag": entry.flag,
        "payee": entry.payee,
        "narration": entry.narration,
        "tags": sorted(entry.tags or ()),
        "links": sorted(entry.links or ()),
        "meta": meta,
        "postings": postings,
        "source": source,
    }


def _document(entry: Any, ledger: LoadedLedger, problems: list[Problem]) -> dict[str, Any] | None:
    where, source = _where(entry.meta, ledger)
    evidence = ledger.evidence_for(entry.filename)
    if evidence is None:
        problems.append(Problem(where, "document_path", "証憑のファイルが読み込まれていない"))
        return None
    before = len(problems)
    meta = _meta(entry.meta, DOCUMENT_KEYS, where, problems)
    tx_ref = meta.pop("transaction_id", None)
    transaction_id = None
    if tx_ref is not None:
        if "string" not in tx_ref or not _ID_RE.fullmatch(tx_ref["string"]):
            problems.append(Problem(where, "meta_type", "document の transaction_id は取引 ID の文字列"))
        else:
            transaction_id = tx_ref["string"]
    if len(problems) != before:
        return None
    out: dict[str, Any] = {
        "date": entry.date.isoformat(),
        "account": entry.account,
        "path": evidence.path,
        "sha256": evidence.sha256,
        "bytes": evidence.size,
        "tags": sorted(entry.tags or ()),
        "links": sorted(entry.links or ()),
        "meta": meta,
        "source": source,
    }
    if transaction_id is not None:
        out["transaction_id"] = transaction_id
    return out


def _check_other(entry: Any, ledger: LoadedLedger, problems: list[Problem]) -> None:
    where, _ = _where(entry.meta, ledger)
    if isinstance(entry, bc_data.Open):
        others = [c for c in (entry.currencies or []) if c != CURRENCY]
        if others:
            problems.append(Problem(where, "currency_not_jpy", f"JPY 以外の通貨の勘定（{', '.join(others)}）"))
    elif isinstance(entry, bc_data.Commodity):
        if entry.currency != CURRENCY:
            problems.append(Problem(where, "currency_not_jpy", f"JPY 以外の通貨（{entry.currency}）"))
    elif isinstance(entry, bc_data.Balance):
        if entry.amount.currency != CURRENCY:
            problems.append(Problem(where, "currency_not_jpy", f"JPY 以外の残高の確認（{entry.amount.currency}）"))
        else:
            _, code = _jpy_int(entry.amount.number)
            if code is not None:
                problems.append(_amount_problem(code, where, "残高の確認の金額"))
    elif not isinstance(entry, _SKIPPED):
        problems.append(
            Problem(where, "directive_not_supported", f"{type(entry).__name__.lower()} ディレクティブは扱わない（pad・price・query・custom など）")
        )


def normalize(ledger: LoadedLedger) -> tuple[dict[str, Any] | None, list[Problem]]:
    """台帳を正規化した取引 JSON にする。(JSON, 問題の一覧)。問題があれば JSON は None。"""
    problems: list[Problem] = []
    transactions: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    for entry in ledger.entries:
        if isinstance(entry, bc_data.Transaction):
            tx = _transaction(entry, ledger, problems)
            if tx is not None:
                transactions.append(tx)
        elif isinstance(entry, bc_data.Document):
            doc = _document(entry, ledger, problems)
            if doc is not None:
                documents.append(doc)
        else:
            _check_other(entry, ledger, problems)

    seen: dict[str, str] = {}
    for tx in transactions:
        where = f"{tx['source']['file']}:{tx['source']['line']}"
        if tx["id"] in seen:
            problems.append(Problem(where, "transaction_id_duplicate", f"取引 ID {tx['id']!r} が重複（{seen[tx['id']]} と）"))
        else:
            seen[tx["id"]] = where
    for doc in documents:
        if "transaction_id" in doc and doc["transaction_id"] not in seen:
            where = f"{doc['source']['file']}:{doc['source']['line']}"
            problems.append(Problem(where, "document_transaction_unknown", f"document の transaction_id {doc['transaction_id']!r} の取引が無い"))
    if problems:
        return None, problems

    transactions.sort(key=lambda t: (t["date"], t["source"]["file"], t["source"]["line"]))
    documents.sort(key=lambda d: (d["date"], d["path"], d["source"]["file"], d["source"]["line"]))
    return (
        {
            "format": FORMAT,
            "currency": CURRENCY,
            "main": ledger.main,
            "source_files": [{"path": s.path, "sha256": s.sha256, "bytes": s.size} for s in ledger.source_files],
            "transactions": transactions,
            "documents": documents,
        },
        [],
    )

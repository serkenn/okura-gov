"""JSON Schema 2020-12 の部分集合を解釈する自作の検査器（標準ライブラリだけ）。

解釈するキーワード：
  type, required, properties, additionalProperties, enum, const, items, minItems,
  minimum, maximum, pattern, format（"date" だけ）, $defs, $ref（"#/$defs/<名前>" だけ）, oneOf
注釈として読み飛ばすキーワード：$schema, $id, $comment, title, description
スキーマとして真偽値 false（その場所に値を置けない）と、空のオブジェクト {}（何でもよい）を使える。

JSON Schema の仕様より厳しくしている点（README にも書いた）：
  - "integer" は Python の int だけ（bool と float を拒否する。1.0 も拒否）。
  - "number" は int（bool を除く）と有限の float。NaN・無限大を拒否する。
  - 文字列はサロゲートの符号位置を含まないこと（UTF-8 で書き出せること）。
  - format "date" は注釈ではなく検査として扱い、YYYY-MM-DD の形で実在する日付だけを通す。
  - pattern は ECMA-262 と Python の re の共通部分だけを使う前提で、re.ASCII で照合する。
    文字クラスの外の「$」は \\Z（文字列の終わり）に置き換える（Python の $ は末尾の改行の
    直前にも合うため）。
  - oneOf の枝がどれも直下の "kind" を const で決めているとき（判別つきの oneOf）は、
    kind の値が合う枝だけを評価する。合う枝がなければ code "unknown_kind" を返す。
    結果は全部の枝を評価したときと同じ（kind の const が合わない枝は必ず不合格になるため）。

評価の結果は Outcome（問題の一覧と注釈の一覧）。注釈は、$ref で "#/$defs/<名前>" を
通って合格した値の（名前, 場所, 値）で、意味の検査（validate.py）が参照の整合などに使う。
oneOf で選ばれなかった枝の注釈は捨てる。
"""

from __future__ import annotations

import datetime as _dt
import math
import re
from dataclasses import dataclass, field
from typing import Any

from .problem import ROOT, Problem, child_index, child_key

SUPPORTED_KEYWORDS: frozenset[str] = frozenset(
    {
        "type",
        "required",
        "properties",
        "additionalProperties",
        "enum",
        "const",
        "items",
        "minItems",
        "minimum",
        "maximum",
        "pattern",
        "format",
        "$defs",
        "$ref",
        "oneOf",
    }
)
ANNOTATION_KEYWORDS: frozenset[str] = frozenset({"$schema", "$id", "$comment", "title", "description"})
JSON_TYPES: frozenset[str] = frozenset({"object", "array", "string", "integer", "number", "boolean", "null"})
SUPPORTED_FORMATS: frozenset[str] = frozenset({"date"})

_DATE_SHAPE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", re.ASCII)
_REF_PREFIX = "#/$defs/"
_MAX_DEPTH = 64  # スキーマの入れ子の深さの上限（$ref の循環でも止まるように）


class SchemaError(Exception):
    """スキーマが部分集合の外にある・壊れている。検査器の使い方の誤り。"""

    def __init__(self, pointer: str, message: str) -> None:
        super().__init__(f"{pointer}: {message}")
        self.pointer = pointer
        self.message = message


@dataclass(frozen=True, slots=True)
class Annotation:
    """$ref で名前つきの定義を通って合格した値。"""

    name: str
    path: str
    value: Any


@dataclass(slots=True)
class Outcome:
    problems: list[Problem] = field(default_factory=list)
    annotations: list[Annotation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def extend(self, other: "Outcome") -> None:
        self.problems.extend(other.problems)
        self.annotations.extend(other.annotations)


# ---------------------------------------------------------------------------
# JSON の値としての比較・型
# ---------------------------------------------------------------------------


def json_type_of(value: Any) -> str:
    """Python の値の JSON での型の名前。JSON にない値は "unsupported"。"""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unsupported"


def json_equal(a: Any, b: Any) -> bool:
    """JSON の値として等しいか（True と 1 を区別し、1 と 1.0 は等しいとする）。"""
    ta, tb = json_type_of(a), json_type_of(b)
    numeric = {"integer", "number"}
    if ta in numeric and tb in numeric:
        return a == b
    if ta != tb:
        return False
    if ta == "array":
        return len(a) == len(b) and all(json_equal(x, y) for x, y in zip(a, b))
    if ta == "object":
        return a.keys() == b.keys() and all(json_equal(a[k], b[k]) for k in a)
    return a == b


def _matches_type(value: Any, type_name: str) -> bool:
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        if isinstance(value, bool):
            return False
        if isinstance(value, int):
            return True
        return isinstance(value, float) and math.isfinite(value)
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "null":
        return value is None
    if type_name == "array":
        return isinstance(value, list)
    if type_name == "object":
        return isinstance(value, dict)
    return False


def _has_surrogate(text: str) -> bool:
    return any(0xD800 <= ord(ch) <= 0xDFFF for ch in text)


_TYPE_LABELS = {
    "object": "オブジェクト",
    "array": "配列",
    "string": "文字列",
    "integer": "整数",
    "number": "数",
    "boolean": "真偽値",
    "null": "null",
    "unsupported": "JSON にない値",
}


def _describe(value: Any) -> str:
    kind = json_type_of(value)
    if kind == "number" and isinstance(value, float) and value.is_integer():
        return "小数（整数の値でも小数の形は使えない）"
    return _TYPE_LABELS.get(kind, kind)


def _short(value: Any, limit: int = 60) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ---------------------------------------------------------------------------
# pattern の変換（ECMA-262 の $ の意味に合わせる）
# ---------------------------------------------------------------------------


def translate_pattern(pattern: str) -> str:
    """文字クラスの外のエスケープされていない "$" を "\\Z" に置き換える。"""
    out: list[str] = []
    in_class = False
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\" and i + 1 < len(pattern):
            out.append(pattern[i : i + 2])
            i += 2
            continue
        if in_class:
            if ch == "]":
                in_class = False
            out.append(ch)
        elif ch == "[":
            in_class = True
            out.append(ch)
        elif ch == "$":
            out.append(r"\Z")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _compile_pattern(pattern: str, pointer: str) -> re.Pattern[str]:
    try:
        return re.compile(translate_pattern(pattern), re.ASCII)
    except re.error as exc:
        raise SchemaError(pointer, f"pattern を正規表現として読めない: {exc}") from None


# ---------------------------------------------------------------------------
# スキーマ自体の検査
# ---------------------------------------------------------------------------


def check_schema(root: Any) -> list[Problem]:
    """スキーマが部分集合の中にあるかを検査する。問題の path はスキーマの中の JSON Pointer。"""
    problems: list[Problem] = []
    if not isinstance(root, dict):
        return [Problem("#", "schema_error", "スキーマの根はオブジェクトでなければならない")]
    defs = root.get("$defs", {})
    if not isinstance(defs, dict):
        return [Problem("#/$defs", "schema_error", "$defs はオブジェクトでなければならない")]

    def walk(node: Any, pointer: str, depth: int) -> None:
        if depth > _MAX_DEPTH:
            problems.append(Problem(pointer, "schema_error", "スキーマの入れ子が深すぎる"))
            return
        if isinstance(node, bool):
            if node is True:
                problems.append(Problem(pointer, "schema_error", "true のスキーマは使わない（{} を使う）"))
            return
        if not isinstance(node, dict):
            problems.append(Problem(pointer, "schema_error", "スキーマはオブジェクトか false でなければならない"))
            return
        for key in node:
            if key not in SUPPORTED_KEYWORDS and key not in ANNOTATION_KEYWORDS:
                problems.append(Problem(f"{pointer}/{key}", "schema_error", f"解釈しないキーワード: {key}"))
        if "$defs" in node and pointer != "#":
            problems.append(Problem(f"{pointer}/$defs", "schema_error", "$defs は根にだけ置く"))
        if "type" in node:
            t = node["type"]
            names = t if isinstance(t, list) else [t]
            if not names or not all(isinstance(n, str) and n in JSON_TYPES for n in names):
                problems.append(Problem(f"{pointer}/type", "schema_error", f"type の値が正しくない: {_short(t)}"))
        if "required" in node:
            r = node["required"]
            if not isinstance(r, list) or not all(isinstance(x, str) for x in r) or len(set(r)) != len(r):
                problems.append(Problem(f"{pointer}/required", "schema_error", "required は重複のない文字列の配列"))
        if "properties" in node:
            props = node["properties"]
            if not isinstance(props, dict):
                problems.append(Problem(f"{pointer}/properties", "schema_error", "properties はオブジェクト"))
            else:
                for name, sub in props.items():
                    walk(sub, f"{pointer}/properties/{name}", depth + 1)
        if "additionalProperties" in node:
            ap = node["additionalProperties"]
            if ap is not False:
                walk(ap, f"{pointer}/additionalProperties", depth + 1)
        if "enum" in node and not isinstance(node["enum"], list):
            problems.append(Problem(f"{pointer}/enum", "schema_error", "enum は配列"))
        if "items" in node:
            walk(node["items"], f"{pointer}/items", depth + 1)
        if "minItems" in node:
            v = node["minItems"]
            if not (isinstance(v, int) and not isinstance(v, bool) and v >= 0):
                problems.append(Problem(f"{pointer}/minItems", "schema_error", "minItems は 0 以上の整数"))
        for key in ("minimum", "maximum"):
            if key in node and not _matches_type(node[key], "number"):
                problems.append(Problem(f"{pointer}/{key}", "schema_error", f"{key} は数"))
        if "pattern" in node:
            p = node["pattern"]
            if not isinstance(p, str):
                problems.append(Problem(f"{pointer}/pattern", "schema_error", "pattern は文字列"))
            else:
                try:
                    _compile_pattern(p, f"{pointer}/pattern")
                except SchemaError as exc:
                    problems.append(Problem(exc.pointer, "schema_error", exc.message))
        if "format" in node and node["format"] not in SUPPORTED_FORMATS:
            problems.append(Problem(f"{pointer}/format", "schema_error", f"解釈しない format: {_short(node['format'])}"))
        if "$ref" in node:
            ref = node["$ref"]
            if not isinstance(ref, str) or not ref.startswith(_REF_PREFIX):
                problems.append(Problem(f"{pointer}/$ref", "schema_error", "$ref は \"#/$defs/<名前>\" の形だけ"))
            elif ref[len(_REF_PREFIX) :] not in defs:
                problems.append(Problem(f"{pointer}/$ref", "schema_error", f"$defs にない定義: {ref}"))
        if "oneOf" in node:
            branches = node["oneOf"]
            if not isinstance(branches, list) or not branches:
                problems.append(Problem(f"{pointer}/oneOf", "schema_error", "oneOf は空でない配列"))
            else:
                for i, sub in enumerate(branches):
                    walk(sub, f"{pointer}/oneOf/{i}", depth + 1)

    walk(root, "#", 0)
    for name, sub in defs.items():
        walk(sub, f"#/$defs/{name}", 1)
    problems.extend(_check_ref_cycles(defs))
    return problems


def _check_ref_cycles(defs: dict[str, Any]) -> list[Problem]:
    """定義が自分自身へ（値を1段も降りずに）$ref でたどり着く循環を探す。"""
    problems: list[Problem] = []
    for name in defs:
        seen: set[str] = set()
        current: str | None = name
        while current is not None:
            if current in seen:
                problems.append(Problem(f"#/$defs/{name}", "schema_error", "$ref の循環"))
                break
            seen.add(current)
            node = defs.get(current)
            ref = node.get("$ref") if isinstance(node, dict) else None
            current = ref[len(_REF_PREFIX) :] if isinstance(ref, str) and ref.startswith(_REF_PREFIX) else None
    return problems


# ---------------------------------------------------------------------------
# 評価
# ---------------------------------------------------------------------------


def _discriminator(branch: Any) -> Any:
    """枝が直下の kind を const で決めていれば、その値を返す。そうでなければ _NO_KIND。"""
    if isinstance(branch, dict):
        props = branch.get("properties")
        if isinstance(props, dict):
            kind = props.get("kind")
            if isinstance(kind, dict) and "const" in kind:
                return kind["const"]
    return _NO_KIND


_NO_KIND = object()


class _Evaluator:
    """1回の評価に使う状態（根のスキーマとコンパイル済みの pattern）。外へ漏らさない。"""

    def __init__(self, root: dict[str, Any]) -> None:
        self._root = root
        self._defs = root.get("$defs", {})
        self._patterns: dict[str, re.Pattern[str]] = {}

    def evaluate(self, instance: Any, schema: Any, path: str, pointer: str, depth: int = 0) -> Outcome:
        if depth > _MAX_DEPTH:
            raise SchemaError(pointer, "スキーマの入れ子が深すぎる（$ref の循環の疑い）")
        out = Outcome()
        if schema is False:
            out.problems.append(Problem(path, "forbidden", "この場所には値を置けない"))
            return out
        if not isinstance(schema, dict):
            raise SchemaError(pointer, "スキーマはオブジェクトか false でなければならない")
        for key in schema:
            if key not in SUPPORTED_KEYWORDS and key not in ANNOTATION_KEYWORDS:
                raise SchemaError(f"{pointer}/{key}", f"解釈しないキーワード: {key}")

        # type が合わなければ、ほかのキーワードの問題は出さない（同じ原因の重複を避ける）
        if "type" in schema:
            t = schema["type"]
            names = t if isinstance(t, list) else [t]
            if not any(_matches_type(instance, n) for n in names):
                wanted = "・".join(_TYPE_LABELS.get(n, n) for n in names)
                out.problems.append(Problem(path, "type", f"{wanted}が必要（{_describe(instance)}が来た）"))
                return out

        if isinstance(instance, str) and _has_surrogate(instance):
            out.problems.append(Problem(path, "invalid_string", "文字列にサロゲートの符号位置がある"))
            return out

        if "$ref" in schema:
            ref = schema["$ref"]
            if not isinstance(ref, str) or not ref.startswith(_REF_PREFIX):
                raise SchemaError(f"{pointer}/$ref", "$ref は \"#/$defs/<名前>\" の形だけ")
            name = ref[len(_REF_PREFIX) :]
            if name not in self._defs:
                raise SchemaError(f"{pointer}/$ref", f"$defs にない定義: {ref}")
            sub = self.evaluate(instance, self._defs[name], path, f"#/$defs/{name}", depth + 1)
            out.extend(sub)
            if sub.ok:
                out.annotations.append(Annotation(name, path, instance))

        if "enum" in schema:
            allowed = schema["enum"]
            if not any(json_equal(instance, a) for a in allowed):
                if not allowed:
                    out.problems.append(Problem(path, "forbidden", "この場所には値を置けない"))
                else:
                    shown = "、".join(_short(a, 40) for a in allowed[:20])
                    more = f" ほか{len(allowed) - 20}個" if len(allowed) > 20 else ""
                    out.problems.append(Problem(path, "enum", f"次のどれか: {shown}{more}（{_short(instance)} が来た）"))

        if "const" in schema and not json_equal(instance, schema["const"]):
            out.problems.append(Problem(path, "const", f"{_short(schema['const'])} でなければならない（{_short(instance)} が来た）"))

        if isinstance(instance, dict):
            self._evaluate_object(instance, schema, path, pointer, depth, out)
        elif isinstance(instance, list):
            self._evaluate_array(instance, schema, path, pointer, depth, out)
        elif isinstance(instance, str):
            self._evaluate_string(instance, schema, path, pointer, out)
        elif _matches_type(instance, "number"):
            if "minimum" in schema and instance < schema["minimum"]:
                out.problems.append(Problem(path, "minimum", f"{schema['minimum']} 以上（{instance} が来た）"))
            if "maximum" in schema and instance > schema["maximum"]:
                out.problems.append(Problem(path, "maximum", f"{schema['maximum']} 以下（{instance} が来た）"))

        if "oneOf" in schema:
            self._evaluate_one_of(instance, schema, path, pointer, depth, out)
        return out

    def _evaluate_object(
        self, instance: dict[Any, Any], schema: dict[str, Any], path: str, pointer: str, depth: int, out: Outcome
    ) -> None:
        bad_keys = [k for k in instance if not isinstance(k, str)]
        for k in bad_keys:
            out.problems.append(Problem(path, "invalid_key", f"オブジェクトのキーは文字列だけ（{_short(k)} が来た）"))
        if bad_keys:
            return
        for name in schema.get("required", []):
            if name not in instance:
                out.problems.append(Problem(child_key(path, name), "required", f"{name} が必要"))
        props: dict[str, Any] = schema.get("properties", {})
        for name, value in instance.items():
            if name in props:
                out.extend(
                    self.evaluate(value, props[name], child_key(path, name), f"{pointer}/properties/{name}", depth + 1)
                )
            elif "additionalProperties" in schema:
                extra = schema["additionalProperties"]
                if extra is False:
                    out.problems.append(Problem(child_key(path, name), "additional_property", f"知らないキー: {name}"))
                else:
                    out.extend(
                        self.evaluate(value, extra, child_key(path, name), f"{pointer}/additionalProperties", depth + 1)
                    )

    def _evaluate_array(
        self, instance: list[Any], schema: dict[str, Any], path: str, pointer: str, depth: int, out: Outcome
    ) -> None:
        if "minItems" in schema and len(instance) < schema["minItems"]:
            out.problems.append(Problem(path, "min_items", f"{schema['minItems']} 個以上が必要（{len(instance)} 個）"))
        if "items" in schema:
            for i, item in enumerate(instance):
                out.extend(self.evaluate(item, schema["items"], child_index(path, i), f"{pointer}/items", depth + 1))

    def _evaluate_string(self, instance: str, schema: dict[str, Any], path: str, pointer: str, out: Outcome) -> None:
        if "pattern" in schema:
            pattern = schema["pattern"]
            compiled = self._patterns.get(pattern)
            if compiled is None:
                compiled = _compile_pattern(pattern, f"{pointer}/pattern")
                self._patterns[pattern] = compiled
            if compiled.search(instance) is None:
                out.problems.append(Problem(path, "pattern", f"形が合わない（{pattern}。{_short(instance)} が来た）"))
        if "format" in schema:
            fmt = schema["format"]
            if fmt != "date":
                raise SchemaError(f"{pointer}/format", f"解釈しない format: {_short(fmt)}")
            if not _is_date(instance):
                out.problems.append(Problem(path, "format", f"YYYY-MM-DD の形の実在する日付が必要（{_short(instance)} が来た）"))

    def _evaluate_one_of(
        self, instance: Any, schema: dict[str, Any], path: str, pointer: str, depth: int, out: Outcome
    ) -> None:
        branches: list[Any] = schema["oneOf"]
        kinds = [_discriminator(b) for b in branches]
        if branches and all(k is not _NO_KIND for k in kinds) and isinstance(instance, dict):
            kind = instance.get("kind")
            declared = "kind" in schema.get("required", []) and "kind" in schema.get("properties", {})
            if not isinstance(kind, str):
                if not declared:
                    out.problems.append(Problem(child_key(path, "kind"), "unknown_kind", "kind が必要"))
                return
            matching = [i for i, k in enumerate(kinds) if json_equal(k, kind)]
            if not matching:
                out.problems.append(Problem(child_key(path, "kind"), "unknown_kind", f"知らない kind: {_short(kind)}"))
                return
            candidates = matching
        else:
            candidates = list(range(len(branches)))

        results = [(i, self.evaluate(instance, branches[i], path, f"{pointer}/oneOf/{i}", depth + 1)) for i in candidates]
        passed = [(i, r) for i, r in results if r.ok]
        if len(passed) == 1:
            out.annotations.extend(passed[0][1].annotations)
            return
        if len(passed) > 1:
            which = "、".join(str(i) for i, _ in passed)
            out.problems.append(Problem(path, "one_of_multiple", f"oneOf の複数の枝（{which}）に合う"))
            return
        if len(results) == 1:
            out.problems.extend(results[0][1].problems)
            return
        details = "；".join(
            f"枝{i}: {r.problems[0].path} {r.problems[0].message}" for i, r in results if r.problems
        )
        out.problems.append(Problem(path, "one_of_none", f"oneOf のどの枝にも合わない（{details}）"))


def _is_date(text: str) -> bool:
    if not _DATE_SHAPE.fullmatch(text):
        return False
    try:
        _dt.date.fromisoformat(text)
    except ValueError:
        return False
    return True


def evaluate(instance: Any, schema: dict[str, Any], *, root: dict[str, Any] | None = None) -> Outcome:
    """instance を schema で評価する。schema の $ref は root（省略時は schema）の $defs で引く。

    スキーマが部分集合の外にあるときは SchemaError を送出する（検査器の使い方の誤り）。
    """
    evaluator = _Evaluator(root if root is not None else schema)
    return evaluator.evaluate(instance, schema, ROOT, "#")

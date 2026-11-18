"""判定コアのパラメータ（parameters/**.yaml）と概念辞書（concepts.yaml）の出典から、参照している法令を静的に集める。

- okura_core を import しない。YAML のライブラリも使わない（標準ライブラリだけ）。行をテキストとして読み、
  `law:`・`条文:`・`law_revision:` の値と、そのときのキーの道筋（パラメータ名）・概念の id を拾う。
- 法令名の表は targets.LAW_NAMES。表にない「…法第N条」などは unresolved に数えて返す（表に足す候補）。
- 「同施行令」「同施行規則」「同法」は、同じ出典の文の中で直前に出た法令から読む。
- 通知（「保発0704第1号」の形の番号、事務連絡）を引用する出典は notices に集める（厚労省の新着通知の issue の候補に使う）。
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .targets import EXTRA_LAWS, LAW_NAMES


@dataclass(frozen=True)
class Citation:
    file: str  # 判定コアの src からの相対パス（/ 区切り）
    module: str  # rules/<module> の名前。concepts/ は "concepts"
    kind: str  # "parameter" | "concept"
    name: str  # パラメータの道筋（例 所得税.基礎控除.第1号.額）か概念の id
    text: str  # 出典の文


@dataclass
class LawTarget:
    law_id: str
    title: str
    citations: list[Citation] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def modules(self) -> Counter:
        return Counter(c.module for c in self.citations)

    def names(self, kind: str) -> list[str]:
        seen: dict[str, None] = {}
        for c in self.citations:
            if c.kind == kind:
                seen.setdefault(c.name, None)
        return list(seen)


@dataclass
class CoreReferences:
    laws: dict[str, LawTarget] = field(default_factory=dict)
    unresolved: Counter = field(default_factory=Counter)
    notices: list[Citation] = field(default_factory=list)
    files_scanned: int = 0


_LAW_KEY = re.compile(r"(?:^|[\s{,])(law|条文)\s*:\s*(.*)$")
_REV_KEY = re.compile(r"law_revision\s*:\s*['\"]?(\d{3}[A-Z0-9]{12})_")
_END_OF_VALUE = re.compile(r",\s*(?:根拠の種類|出典|source_kind|reference|unit|比較|施行日|適用|law_revision)\s*:|\}\s*$")
_KEY_LINE = re.compile(r"^(\s*)(-\s+)?([^\s#:\-][^:]*?|-\S[^:]*?)\s*:(?:\s+(.*))?$")
_BLOCK_SCALAR = re.compile(r"^[>|][+-]?\s*$")
_SKIP_KEYS = {"metadata", "values", "description", "reference"}
_DATE_KEY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UNRESOLVED = re.compile(r"([一-龥ぁ-んァ-ヶー]{2,}?(?:法律|施行規則|施行令|省令|政令|規則|法|令))第[0-9０-９一二三四五六七八九十]+条")
_NOTICE_NO = re.compile(r"([一-龥]{0,4}発)[0-9０-９]{0,4}第[0-9０-９]+号")
_SAME = re.compile(r"同(施行令|施行規則|法)")


def _name_pattern() -> re.Pattern:
    names = sorted(LAW_NAMES, key=len, reverse=True)
    return re.compile("|".join(re.escape(n) for n in names) + "|" + _SAME.pattern)


_NAMES_RE = _name_pattern()


def _display_titles() -> dict[str, str]:
    titles: dict[str, str] = {}
    for name, law_id in LAW_NAMES.items():
        titles.setdefault(law_id, name)
    return titles


DISPLAY_TITLES = _display_titles()


def _base_name(name: str) -> str:
    for suffix in ("施行規則", "施行令"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def resolve_laws(text: str) -> tuple[list[str], list[str]]:
    """出典の文から、法令ID（出た順・重複なし）と、表にない法令名（unresolved）を返す。"""
    found: list[str] = []
    last_name: str | None = None
    spans = []
    for m in _NAMES_RE.finditer(text):
        token = m.group(0)
        spans.append(m.span())
        same = _SAME.fullmatch(token)
        if same:
            if last_name is None:
                continue
            base = _base_name(last_name)
            cand = base if same.group(1) == "法" else base + same.group(1)
            law_id = LAW_NAMES.get(cand)
        else:
            law_id = LAW_NAMES[token]
            last_name = token
        if law_id and law_id not in found:
            found.append(law_id)
    masked = list(text)
    for a, b in spans:
        for i in range(a, b):
            masked[i] = " "
    unresolved = [m.group(1) for m in _UNRESOLVED.finditer("".join(masked))]
    return found, unresolved


def _value_of(rest: str) -> str:
    rest = rest.strip()
    m = _END_OF_VALUE.search(rest)
    if m:
        rest = rest[: m.start()]
    return rest.strip().strip("'\"").strip()


def _scan_file(path: Path, rel: str, module: str, kind: str, param_prefix: str, refs: CoreReferences) -> None:
    stack: list[tuple[int, str]] = []
    block_indent: int | None = None
    concept_id: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if block_indent is not None:
            if indent > block_indent:
                continue
            block_indent = None
        km = _KEY_LINE.match(line)
        if km:
            key_indent = indent + (len(km.group(2)) if km.group(2) else 0)
            key = km.group(3).strip()
            value = (km.group(4) or "").strip()
            while stack and stack[-1][0] >= key_indent:
                stack.pop()
            if km.group(2):  # リストの項目の始まり（- id: …）
                while stack and stack[-1][0] >= indent:
                    stack.pop()
            stack.append((key_indent, key))
            if kind == "concept" and key == "id":
                concept_id = value.strip("'\"")
            if _BLOCK_SCALAR.match(value):
                block_indent = key_indent
        if kind == "parameter":
            path_keys = [k for _, k in stack if k not in _SKIP_KEYS and not _DATE_KEY.match(k)]
            # 末尾のキーが law・law_revision 自身なら除く
            while path_keys and path_keys[-1] in ("law", "law_revision", "条文"):
                path_keys.pop()
            name = ".".join([p for p in [param_prefix, *path_keys] if p])
        else:
            name = concept_id or "(概念の id なし)"
        lm = _LAW_KEY.search(line)
        if lm:
            text = _value_of(lm.group(2))
            if text and not _BLOCK_SCALAR.match(text):
                cit = Citation(rel, module, kind, name, text)
                ids, unresolved = resolve_laws(text)
                for law_id in ids:
                    refs.laws.setdefault(law_id, LawTarget(law_id, DISPLAY_TITLES.get(law_id, law_id))).citations.append(cit)
                refs.unresolved.update(unresolved)
                if _NOTICE_NO.search(text) or "事務連絡" in text or "通知" in text:
                    refs.notices.append(cit)
        for rm in _REV_KEY.finditer(line):
            law_id = rm.group(1)
            t = refs.laws.setdefault(law_id, LawTarget(law_id, DISPLAY_TITLES.get(law_id, law_id)))
            cit = Citation(rel, module, kind, name, f"law_revision {law_id}")
            if cit not in t.citations:
                t.citations.append(cit)


def collect(core_src: Path | str, *, include_extra: bool = True) -> CoreReferences:
    """判定コアの src（okura_core パッケージのディレクトリ、または packages/core/src）から法令の参照を集める。"""
    root = Path(core_src)
    if (root / "okura_core").is_dir():
        root = root / "okura_core"
    if not (root / "rules").is_dir():
        raise FileNotFoundError(f"判定コアの rules/ が見つからない: {root}")
    refs = CoreReferences()
    files = sorted(root.glob("rules/*/parameters/**/*.yaml")) + sorted(root.glob("rules/*/concepts.yaml")) \
        + sorted(root.glob("concepts/*.yaml"))
    for path in files:
        rel = path.relative_to(root).as_posix()
        parts = rel.split("/")
        if parts[0] == "rules":
            module = parts[1]
            if parts[2] == "parameters":
                kind = "parameter"
                sub = parts[3:]
                sub[-1] = sub[-1][: -len(".yaml")]
                if sub[-1] == "index":
                    sub = sub[:-1]
                prefix = ".".join(sub)
            else:
                kind, prefix = "concept", ""
        else:
            module, kind, prefix = "concepts", "concept", ""
        _scan_file(path, rel, module, kind, prefix, refs)
        refs.files_scanned += 1
    if include_extra:
        for law_id, reason in EXTRA_LAWS.items():
            refs.laws.setdefault(law_id, LawTarget(law_id, DISPLAY_TITLES.get(law_id, law_id))).reasons.append(reason)
    for t in refs.laws.values():
        if t.citations:
            t.reasons.insert(0, f"判定コアの出典が {len(t.citations)} か所で引用")
    return refs


def notice_prefixes(text: str) -> set[str]:
    """通知の番号の発翰の部分（保発・年管発など）の集合。"""
    # 「令和８年11月10日保保発…」のように日付に続けて書かれると「日」まで拾うので除く（発翰は「日」で始まらない）
    return {m.group(1).lstrip("日") for m in _NOTICE_NO.finditer(text)} - {"発"}


def default_core_src() -> Path | None:
    """このリポジトリの中で使うときの判定コアの場所（packages/core/src/okura_core）。見つからなければ None。"""
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "packages" / "core" / "src" / "okura_core"
        if (cand / "rules").is_dir():
            return cand
    return None

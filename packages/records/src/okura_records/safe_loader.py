"""beancount の台帳を安全に読む（記録層の入口。台帳はここ以外から読まない）。

beancount の `loader.load_file` は使わない。代わりに次の順で読む。

1. 走査（読む前の検査）：台帳のファイルを include をたどって1つずつ、
   - パスの検査：root の中だけ。include の文字列は glob を使う前に形を検査する（相対・ASCII・`..` なし・
     ワイルドカードなし・拡張子 `.beancount`・Windows の装置名なし・代替データストリームなし）。
     実体のパス（realpath）が見かけのパスと違う（シンボリックリンク・ジャンクション）・通常のファイルでない・
     ハードリンク（リンク数が 1 でない）を拒否する。
   - 大きさの上限（1ファイル・合計・ファイルの数）を読む前に stat で確かめる。
   - ファイルを1回だけバイト列で読み、その SHA-256 を取る。
   - 文字コードの細工を拒否する：BOM、NUL、タブ・改行以外の制御文字（C1 制御文字と U+2028・U+2029 を含む）、
     双方向の書式制御文字、LF の伴わない CR、UTF-8 として正しくないもの。
   - 1行の長さと、文字列の字句（`"…"`。改行を含みうる）の長さの上限を超えるものは parse しない
     （beancount の字句解析は長い字句に対して時間が長さの2乗で増える）。
   - 同じバイト列を `parser.parse_file` に渡し、`plugin` 行・`option "insert_pythonpath"`・
     `option "plugin_processing_mode"`・`option "documents"`・root の外を指す `document` を拒否する。
2. 読み込み：走査で読んだバイト列の parse の結果だけを使い、loader の `_load` と同じ順で
   並べ替え → booking → 既定の処理（ops.documents・ops.pad・ops.balance）→ 検査（ops.validation）を行う。
   - **台帳の `plugin` 行は（走査で拒否したうえで）どのみち実行しない**。読み込みキャッシュ（pickle）は読まない・書かない・消さない。
   - ファイルを読み直さないので、走査と読み込みの間にファイルが変わる隙が無い。
   - beancount のエラーは、1件でもあれば失敗として扱う（メタデータの1行の誤りで取引が黙って消えるため）。
3. 証憑：`document` ディレクティブのファイルを、同じパスの検査をしてから SHA-256 を取る。

根拠：`docs/measurements/20261109_R2-tools_beancount-runtime.md` §4〜§7、
`docs/measurements/20261109_impl-prep_tools-beancount-probe.md` A1〜A10、
`docs/hypotheses/20261109_impl-prep_tools-adoption-recheck.md` H2。
このモジュールを使うプロセスは `python -I` で起動すること（同じ文書 A9）。
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import stat
from collections import deque
from dataclasses import dataclass, field
from os import path
from typing import Any, Mapping

from beancount.core import data as bc_data
from beancount.ops import balance as bc_balance
from beancount.ops import documents as bc_documents
from beancount.ops import pad as bc_pad
from beancount.ops import validation as bc_validation
from beancount.parser import booking as bc_booking
from beancount.parser import parser as bc_parser

from .problem import Problem

__all__ = [
    "DEFAULT_LIMITS",
    "EvidenceFile",
    "LoadResult",
    "LoadedLedger",
    "Limits",
    "SourceFile",
    "check_text",
    "load_ledger",
    "longest_string_span",
]


@dataclass(frozen=True)
class Limits:
    """読み込みの上限。既定値は実測（beancount-probe A6）からの仮の値。"""

    max_file_bytes: int = 20 * 2**20
    max_total_bytes: int = 100 * 2**20
    max_files: int = 500
    max_line_bytes: int = 64 * 1024
    max_string_bytes: int = 64 * 1024
    max_evidence_bytes: int = 256 * 2**20
    max_evidence_total_bytes: int = 4 * 2**30
    max_evidence_files: int = 100_000


DEFAULT_LIMITS = Limits()


@dataclass(frozen=True)
class SourceFile:
    """読んだ台帳のファイル。path は root からの相対パス（/ 区切り）。"""

    path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class EvidenceFile:
    """document ディレクティブが指す証憑のファイル。path は root からの相対パス（/ 区切り）。"""

    path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class LoadedLedger:
    """安全に読み込んだ台帳。アダプタ（adapter.normalize）への入力。

    - root：root の実体の絶対パス（出力には出さない。相対パスを作るためだけに使う）。
    - entries：beancount のディレクティブ（booking・検査の後。日付順）。
    - account_roots：ルートの勘定の名前 → 種類（assets・liabilities・equity・income・expenses）。
    - evidence：証憑の実体の絶対パス（normcase したもの）→ EvidenceFile。
    """

    root: str
    main: str
    entries: tuple[Any, ...]
    source_files: tuple[SourceFile, ...]
    evidence: Mapping[str, EvidenceFile]
    account_roots: Mapping[str, str]

    def relpath(self, abs_path: str) -> str:
        return _rel_posix(abs_path, self.root)

    def evidence_for(self, abs_path: str) -> EvidenceFile | None:
        return self.evidence.get(path.normcase(path.normpath(abs_path)))


@dataclass(frozen=True)
class LoadResult:
    ledger: LoadedLedger | None
    problems: tuple[Problem, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.ledger is not None and not self.problems


# ---------------------------------------------------------------------------
# パスの形の検査
# ---------------------------------------------------------------------------

_DIR_COMPONENT = r"[A-Za-z0-9_\-]+"
_FILE_COMPONENT = r"[A-Za-z0-9_\-]+\.beancount"
INCLUDE_RE = re.compile(rf"(?:{_DIR_COMPONENT}/)*{_FILE_COMPONENT}", re.ASCII)
_DIR_RE = re.compile(_DIR_COMPONENT, re.ASCII)
_FILE_RE = re.compile(_FILE_COMPONENT, re.ASCII)
_RESERVED_STEMS = frozenset(
    ["CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"]
    + [f"COM{i}" for i in range(1, 10)]
    + [f"LPT{i}" for i in range(1, 10)]
    # 上付きの数字も装置名（証憑の名前は ASCII に限らないので要る）
    + [f"{name}{digit}" for name in ("COM", "LPT") for digit in ("\u00b9", "\u00b2", "\u00b3")]
)
_EVIDENCE_BAD_CHARS = re.compile(r'[\x00-\x1f\x7f:*?"<>|]')


def _reserved(component: str) -> bool:
    stem = component.split(".", 1)[0].rstrip(" ").upper()
    return stem in _RESERVED_STEMS


def _ledger_components_ok(parts: list[str]) -> bool:
    """台帳のファイルの相対パス（root から）の各成分が許された形か。"""
    if not parts:
        return False
    *dirs, last = parts
    if not all(_DIR_RE.fullmatch(d) for d in dirs) or not _FILE_RE.fullmatch(last):
        return False
    return not any(_reserved(p) for p in parts)


def _evidence_components_ok(parts: list[str]) -> bool:
    """証憑のファイルの相対パスの各成分が許された形か（日本語の名前は許す）。"""
    for p in parts:
        if p in ("", os.curdir, os.pardir) or _EVIDENCE_BAD_CHARS.search(p) or p != p.rstrip(". "):
            return False
        if _reserved(p):
            return False
    return bool(parts)


def _split(rel: str) -> list[str]:
    rel = rel.replace("\\", "/") if os.sep == "\\" else rel
    return rel.split("/")


def _norm(p: str) -> str:
    return path.normcase(path.normpath(p))


def _inside(p: str, root: str) -> bool:
    """p が root の中（root そのものは含まない）か。"""
    try:
        rel = path.relpath(p, root)
    except ValueError:  # 別のドライブ
        return False
    if path.isabs(rel) or rel == os.curdir:
        return False
    return _split(rel)[0] != os.pardir


def _rel_posix(p: str, root: str) -> str:
    return "/".join(_split(path.relpath(p, root)))


_EXTENDED_PREFIX = "\\\\?\\"


def _plain(p: str) -> str:
    """Windows の拡張パスの接頭辞（`\\\\?\\C:\\…`・`\\\\?\\UNC\\…`）を外す。

    main と root の片方だけに接頭辞があると、relpath が別のドライブとみなして root の外と判定するため、書き方を揃える。
    それ以外の `\\\\?\\` の形（ボリュームの GUID など）はそのまま（後の検査で開けないか root の外になる）。
    """
    if os.name != "nt" or not p.startswith(_EXTENDED_PREFIX):
        return p
    rest = p[len(_EXTENDED_PREFIX) :]
    if len(rest) >= 3 and rest[0].isascii() and rest[0].isalpha() and rest[1] == ":" and rest[2] == "\\":
        return rest
    if rest[:4].upper() == "UNC\\":
        return "\\\\" + rest[4:]
    return p


# ---------------------------------------------------------------------------
# バイト列の検査
# ---------------------------------------------------------------------------

_CONTROL = re.compile(rb"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]")  # NUL は別に数える
# UTF-8 として読んだ後の検査。C1 制御文字（U+0085 NEL など）と行・段落の区切り（U+2028・U+2029）は、
# beancount の字句解析では改行にならないが、エディタによっては改行に見える（コメントの中に取引を隠せる）。
_C1_OR_SEPARATOR = re.compile("[\u0080-\u009f\u2028\u2029]")
# 双方向の書式制御文字（表示の順が実際の並びと変わる。Trojan Source の手口）
_BIDI_CONTROL = re.compile("[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]")
_BARE_CR = re.compile(rb"\r(?!\n)")
_QUOTE_OR_BACKSLASH = re.compile(rb'[\\"]')


def longest_string_span(data: bytes) -> int:
    """文字列の字句（`"` から次の `"` まで）になりうる最も長いバイト数（控えめな上界）。

    beancount の字句解析（lexer.l）の文字列の規則は、`"` で始まり、バックスラッシュの次の1文字（改行を除く）を飛ばし、
    次の `"` で終わる。改行を含みうるので、1行の長さの上限では抑えられない。どの `"` も字句の始まりになりうるとみなし、
    バックスラッシュの次の1バイト（改行を除く）は飛ばし、その次が改行か終わりなら字句はそこで失敗する、として数える。
    コメントの中の `"` も始まりとみなすので、実際の字句より長く見積もることはあっても短くは見積もらない。
    """
    longest = 0
    start: int | None = None
    skip_until = -1
    n = len(data)
    for match in _QUOTE_OR_BACKSLASH.finditer(data):
        i = match.start()
        if i < skip_until:
            continue
        if data[i] == 0x5C:  # バックスラッシュ
            if i + 1 < n and data[i + 1] != 0x0A:
                skip_until = i + 2
                continue
            if start is not None:  # 字句はここで失敗する（失敗するまでに読む長さ）
                longest = max(longest, i - start + 1)
                start = None
            continue
        if start is not None:
            longest = max(longest, i - start + 1)
        start = i  # 閉じる `"` も次の字句の始まりになりうる（控えめに数える）
    if start is not None:
        longest = max(longest, n - start)
    return longest


def check_text(data: bytes, limits: Limits = DEFAULT_LIMITS) -> list[tuple[str, str]]:
    """台帳のバイト列を parse する前に検査する。(code, message) の一覧（空なら合格）。"""
    problems: list[tuple[str, str]] = []
    if data.startswith(b"\xef\xbb\xbf"):
        problems.append(("bom", "BOM がある（台帳は BOM なしの UTF-8 にする）"))
    nul_at = data.find(b"\x00")
    if nul_at >= 0:
        problems.append(("nul", f"NUL がある（{nul_at} バイト目）"))
    m = _CONTROL.search(data)
    if m:
        problems.append(("control_char", f"タブ・改行以外の制御文字がある（{m.start()} バイト目）"))
    m = _BARE_CR.search(data)
    if m:
        problems.append(("bare_cr", f"LF の伴わない CR がある（{m.start()} バイト目）"))
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        problems.append(("not_utf8", f"UTF-8 として正しくない（{exc.start} バイト目）"))
    else:
        m = _C1_OR_SEPARATOR.search(text)
        if m:
            at = len(text[: m.start()].encode("utf-8"))
            problems.append(("control_char", f"C1 制御文字・行の区切り文字 U+{ord(m.group()):04X} がある（{at} バイト目）"))
        m = _BIDI_CONTROL.search(text)
        if m:
            at = len(text[: m.start()].encode("utf-8"))
            problems.append(("bidi_control", f"双方向の書式制御文字 U+{ord(m.group()):04X} がある（{at} バイト目）"))
    longest_line = max((len(x) for x in data.split(b"\n")), default=0)
    if longest_line > limits.max_line_bytes:
        problems.append(("line_too_long", f"1行が長すぎる（{longest_line} バイト。上限 {limits.max_line_bytes}）"))
    span = longest_string_span(data)
    if span > limits.max_string_bytes:
        problems.append(
            ("string_too_long", f"文字列の字句になりうる範囲が長すぎる（{span} バイト。上限 {limits.max_string_bytes}）")
        )
    return problems


# ---------------------------------------------------------------------------
# ファイルを開く（リンク・root の外・通常でないファイル・ハードリンク・大きさ）
# ---------------------------------------------------------------------------


@dataclass
class _Budget:
    files: int = 0
    total: int = 0


def _stat_checked(
    apparent: str, root_real: str, where: str, max_bytes: int, too_large: str = "file_too_large"
) -> tuple[os.stat_result | None, str | None, list[Problem]]:
    """見かけのパス apparent を確かめる。(lstat, 実体のパス, 問題)。"""
    try:
        real = path.realpath(apparent, strict=True)
    except (OSError, ValueError) as exc:
        return None, None, [Problem(where, "not_found", f"開けない（{type(exc).__name__}）")]
    if _norm(real) != _norm(apparent):
        return None, None, [Problem(where, "link", "実体のパスが見かけと違う（シンボリックリンク・ジャンクションなど）")]
    if not _inside(real, root_real):
        return None, None, [Problem(where, "outside_root", "root の外のファイル")]
    try:
        st = os.lstat(apparent)
    except OSError as exc:
        return None, None, [Problem(where, "not_found", f"開けない（{type(exc).__name__}）")]
    if stat.S_ISLNK(st.st_mode):
        return None, None, [Problem(where, "link", "シンボリックリンク")]
    if not stat.S_ISREG(st.st_mode):
        return None, None, [Problem(where, "not_regular_file", "通常のファイルでない")]
    if st.st_nlink != 1:
        return None, None, [Problem(where, "hard_link", f"ハードリンクがある（リンク数 {st.st_nlink}）")]
    if st.st_size > max_bytes:
        return None, None, [Problem(where, too_large, f"大きすぎる（{st.st_size} バイト。上限 {max_bytes}）")]
    return st, real, []


def _same_file(st: os.stat_result, fh: Any) -> bool:
    fst = os.fstat(fh.fileno())
    return (fst.st_dev, fst.st_ino) == (st.st_dev, st.st_ino)


def _read_checked(apparent: str, root_real: str, where: str, max_bytes: int) -> tuple[bytes | None, str | None, list[Problem]]:
    st, real, problems = _stat_checked(apparent, root_real, where, max_bytes)
    if st is None or real is None:
        return None, None, problems
    try:
        with open(apparent, "rb") as fh:
            if not _same_file(st, fh):
                return None, None, [Problem(where, "changed_during_read", "確かめた後にファイルが差し替えられた")]
            data = fh.read(max_bytes + 1)
    except OSError as exc:
        return None, None, [Problem(where, "io_error", f"読めない（{type(exc).__name__}）")]
    if len(data) > max_bytes:
        return None, None, [Problem(where, "file_too_large", f"大きすぎる（上限 {max_bytes} バイト）")]
    return data, real, []


def _hash_checked(apparent: str, root_real: str, where: str, max_bytes: int) -> tuple[tuple[str, int] | None, str | None, list[Problem]]:
    st, real, problems = _stat_checked(apparent, root_real, where, max_bytes, "evidence_too_large")
    if st is None or real is None:
        return None, None, problems
    digest = hashlib.sha256()
    size = 0
    try:
        with open(apparent, "rb") as fh:
            if not _same_file(st, fh):
                return None, None, [Problem(where, "changed_during_read", "確かめた後にファイルが差し替えられた")]
            while True:
                chunk = fh.read(1 << 20)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    return None, None, [Problem(where, "evidence_too_large", f"証憑が大きすぎる（上限 {max_bytes} バイト）")]
                digest.update(chunk)
    except OSError as exc:
        return None, None, [Problem(where, "io_error", f"読めない（{type(exc).__name__}）")]
    return (digest.hexdigest(), size), real, []


# ---------------------------------------------------------------------------
# 走査
# ---------------------------------------------------------------------------


@dataclass
class _Parsed:
    real: str
    rel: str
    data_sha256: str
    size: int
    entries: list[Any]
    options: dict[str, Any]


def _error_where(err: Any, root_real: str, fallback: str) -> str:
    return _meta_where(getattr(err, "source", None), root_real, fallback)


def _meta_where(source: Any, root_real: str, fallback: str) -> str:
    """beancount のメタデータ（filename・lineno）から `相対パス:行` を作る。"""
    if isinstance(source, dict):
        filename = source.get("filename")
        lineno = source.get("lineno")
        if isinstance(filename, str) and path.isabs(filename) and _inside(filename, root_real):
            return f"{_rel_posix(filename, root_real)}:{lineno}"
        if isinstance(lineno, int) and lineno:
            return f"{fallback}:{lineno}"
    return fallback


def _first_line(message: Any, limit: int = 300) -> str:
    text = str(message).splitlines()[0] if str(message) else ""
    return text[:limit]


def _scan_options(parsed_entries: list[Any], opts: dict[str, Any], rel: str, root_real: str) -> list[Problem]:
    problems: list[Problem] = []
    for item in opts.get("plugin") or []:
        name = item[0] if isinstance(item, tuple) and item else item
        # 設定の文字列（コードになりうる）は出さない
        problems.append(Problem(rel, "plugin", f"plugin 行は使えない（{str(name)[:80]!r}）"))
    if opts.get("insert_pythonpath"):
        problems.append(Problem(rel, "insert_pythonpath", 'option "insert_pythonpath" は使えない'))
    if opts.get("plugin_processing_mode") != "default":
        problems.append(Problem(rel, "plugin_processing_mode", 'option "plugin_processing_mode" は変えられない'))
    if opts.get("documents"):
        problems.append(Problem(rel, "option_documents", 'option "documents"（証憑の自動の走査）は使えない'))
    for entry in parsed_entries:
        if isinstance(entry, bc_data.Document):
            where = f"{rel}:{entry.meta.get('lineno')}"
            problems.extend(_document_path_problems(entry.filename, root_real, where))
    return problems


def _document_path_problems(filename: Any, root_real: str, where: str) -> list[Problem]:
    if not isinstance(filename, str) or not path.isabs(filename):
        return [Problem(where, "document_path", "document のパスが絶対パスにならない")]
    if not _inside(filename, root_real):
        return [Problem(where, "document_outside_root", "document が root の外を指す")]
    if not _evidence_components_ok(_split(path.relpath(filename, root_real))):
        return [Problem(where, "document_path", "document のパスに使えない文字・名前がある（: 制御文字 装置名 末尾の . など）")]
    return []


def _scan(main_apparent: str, root_real: str, limits: Limits) -> tuple[list[_Parsed], list[Problem]]:
    problems: list[Problem] = []
    parsed: list[_Parsed] = []
    seen: set[str] = set()
    budget = _Budget()
    queue: deque[tuple[str, str]] = deque([(main_apparent, "(main)")])
    while queue:
        apparent, included_from = queue.popleft()  # loader と同じ幅優先
        apparent = path.normpath(apparent)
        where = _rel_posix(apparent, root_real) if _inside(apparent, root_real) else apparent
        key = _norm(apparent)
        if key in seen:
            problems.append(Problem(where, "include_duplicate", f"同じファイルを2回読む（include の循環・重複。{included_from} から）"))
            continue
        seen.add(key)
        budget.files += 1
        if budget.files > limits.max_files:
            problems.append(Problem(where, "too_many_files", f"台帳のファイルが多すぎる（上限 {limits.max_files}）"))
            break
        data, real, file_problems = _read_checked(apparent, root_real, where, limits.max_file_bytes)
        if data is None or real is None:
            problems.extend(file_problems)
            continue
        budget.total += len(data)
        if budget.total > limits.max_total_bytes:
            problems.append(Problem(where, "total_too_large", f"台帳の合計が大きすぎる（上限 {limits.max_total_bytes} バイト）"))
            break
        rel = _rel_posix(real, root_real)
        text_problems = check_text(data, limits)
        if text_problems:
            problems.extend(Problem(rel, code, message) for code, message in text_problems)
            continue  # 正しくないバイト列は parse に渡さない（include もたどらない）
        entries, errors, opts = bc_parser.parse_file(io.BytesIO(data), report_filename=real)
        for err in errors:
            problems.append(Problem(_error_where(err, root_real, rel), "beancount_error", _first_line(err.message)))
        problems.extend(_scan_options(entries, opts, rel, root_real))
        for inc in opts.get("include") or []:
            if not (isinstance(inc, str) and INCLUDE_RE.fullmatch(inc) and _ledger_components_ok(inc.split("/"))):
                problems.append(
                    Problem(rel, "include_form", f"include の形が許されない（{str(inc)[:120]!r}。相対・英数字・.beancount だけ）")
                )
                continue
            queue.append((path.join(path.dirname(real), *inc.split("/")), rel))
        parsed.append(_Parsed(real, rel, hashlib.sha256(data).hexdigest(), len(data), entries, opts))
    return parsed, problems


# ---------------------------------------------------------------------------
# 読み込み（loader._load と同じ順。plugin 行は実行しない）
# ---------------------------------------------------------------------------

_DEFAULT_TRANSFORMS = (
    # loader.PLUGINS_PRE（beancount.ops.documents の __plugins__）
    bc_documents.process_documents,
    bc_documents.verify_document_files_exist,
    # 台帳の plugin 行（走査で拒否した。ここでは実行しない）
    # loader.PLUGINS_POST
    bc_pad.pad,
    bc_balance.check,
)


def _unique(items: list[Any]) -> list[Any]:
    out: list[Any] = []
    for item in items:
        if item not in out:
            out.append(item)
    return out


def _build(parsed: list[_Parsed], root_real: str) -> tuple[list[Any], dict[str, Any], list[Problem]]:
    top = parsed[0]
    options_map = dict(top.options)
    options_map["include"] = sorted(p.real for p in parsed)
    # loader.aggregate_options_map と同じ（pythonpath は使わないので常に空）
    currencies = list(options_map.get("operating_currency") or [])
    for other in parsed[1:]:
        currencies.extend(other.options.get("operating_currency") or [])
        options_map["dcontext"].update_from(other.options["dcontext"])
    options_map["operating_currency"] = _unique(currencies)
    options_map["pythonpath"] = []
    options_map["plugin"] = []

    entries: list[Any] = []
    for p in parsed:
        entries.extend(p.entries)
    entries.sort(key=bc_data.entry_sortkey)
    errors: list[Any] = []
    entries, booking_errors = bc_booking.book(entries, options_map)
    errors.extend(booking_errors)
    for transform in _DEFAULT_TRANSFORMS:
        entries, new_errors = transform(entries, options_map)
        errors.extend(new_errors)
        entries.sort(key=bc_data.entry_sortkey)
    errors.extend(bc_validation.validate(entries, options_map, None, None))
    problems = [Problem(_error_where(e, root_real, top.rel), "beancount_error", _first_line(e.message)) for e in errors]
    return entries, options_map, problems


def _account_roots(options_map: Mapping[str, Any]) -> dict[str, str]:
    roots = {}
    for kind in ("assets", "liabilities", "equity", "income", "expenses"):
        name = options_map.get(f"name_{kind}")
        if isinstance(name, str):
            roots[name] = kind
    return roots


def _hash_evidence(entries: list[Any], root_real: str, limits: Limits) -> tuple[dict[str, EvidenceFile], list[Problem]]:
    evidence: dict[str, EvidenceFile] = {}
    problems: list[Problem] = []
    total = 0
    for entry in entries:
        if not isinstance(entry, bc_data.Document):
            continue
        key = _norm(entry.filename)
        if key in evidence:
            continue
        where = _meta_where(entry.meta, root_real, "(document)")
        path_problems = _document_path_problems(entry.filename, root_real, where)
        if path_problems:
            problems.extend(path_problems)
            continue
        if len(evidence) >= limits.max_evidence_files:
            problems.append(Problem(where, "too_many_files", f"証憑が多すぎる（上限 {limits.max_evidence_files}）"))
            break
        hashed, real, file_problems = _hash_checked(path.normpath(entry.filename), root_real, where, limits.max_evidence_bytes)
        if hashed is None or real is None:
            problems.extend(file_problems)
            continue
        total += hashed[1]
        if total > limits.max_evidence_total_bytes:
            problems.append(Problem(where, "total_too_large", f"証憑の合計が大きすぎる（上限 {limits.max_evidence_total_bytes} バイト）"))
            break
        evidence[key] = EvidenceFile(_rel_posix(real, root_real), hashed[0], hashed[1])
    return evidence, problems


def load_ledger(main: str | os.PathLike[str], *, root: str | os.PathLike[str] | None = None, limits: Limits = DEFAULT_LIMITS) -> LoadResult:
    """台帳を安全に読み込む。例外は送出しない（入力の誤りは problems に入る）。

    - main：最上位の台帳のファイル（拡張子 `.beancount`）。
    - root：読んでよいディレクトリ。既定は main のディレクトリ。include・document はこの中だけ。
    """
    try:
        return _load_ledger(os.fspath(main), None if root is None else os.fspath(root), limits)
    except Exception as exc:  # 最後の守り：beancount の内部の例外でも呼び出し側を落とさない
        return LoadResult(None, (Problem("(load)", "internal_error", f"読み込みの内部の誤り（{type(exc).__name__}）"),))


def _load_ledger(main: str, root: str | None, limits: Limits) -> LoadResult:
    main_abs = _plain(path.abspath(main))
    root_abs = _plain(path.abspath(root)) if root is not None else path.dirname(main_abs)
    try:
        root_real = path.realpath(root_abs, strict=True)
    except (OSError, ValueError) as exc:
        return LoadResult(None, (Problem("(root)", "root", f"root を開けない（{type(exc).__name__}）"),))
    if not path.isdir(root_real):
        return LoadResult(None, (Problem("(root)", "root", "root がディレクトリでない"),))
    if not _inside(main_abs, root_abs):
        return LoadResult(None, (Problem("(main)", "outside_root", "台帳のファイルが root の中にない"),))
    parts = _split(path.relpath(main_abs, root_abs))
    if not _ledger_components_ok(parts):
        return LoadResult(
            None, (Problem("(main)", "main_path", "台帳のファイル名は英数字・_・- と拡張子 .beancount だけ（root からの相対パスの各段）"),)
        )
    main_apparent = path.join(root_real, *parts)

    parsed, problems = _scan(main_apparent, root_real, limits)
    if problems or not parsed:
        return LoadResult(None, tuple(problems) or (Problem("(main)", "not_found", "台帳を読めなかった"),))

    entries, options_map, problems = _build(parsed, root_real)
    if problems:
        return LoadResult(None, tuple(problems))
    evidence, problems = _hash_evidence(entries, root_real, limits)
    if problems:
        return LoadResult(None, tuple(problems))
    ledger = LoadedLedger(
        root=root_real,
        main=parsed[0].rel,
        entries=tuple(entries),
        source_files=tuple(sorted((SourceFile(p.rel, p.data_sha256, p.size) for p in parsed), key=lambda s: s.path)),
        evidence=evidence,
        account_roots=_account_roots(options_map),
    )
    return LoadResult(ledger, ())

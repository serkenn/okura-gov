"""一覧ページ（国税庁・日本年金機構・厚労省）の条件付き取得（304）と、本文のテキストの比較。

根拠：docs/measurements/20261109_R3-tsutatsu_fetch-and-monitor-probe.md
- §1：国税庁の一覧は ETag・Last-Modified があり 304 を返す。日本年金機構の新着一覧は Last-Modified があり 304 を返す。
- §2-2：Last-Modified は本文の変化と一致しないことがある（TA の一斉更新）→ 変化の判定は抽出したテキストの比較で行う。
- §2-1：国税庁は存在しない URL に HTTP 200 で「指定されたページを表示できませんでした」を返す（ソフト404）。
- §2-3：Shift_JIS と UTF-8 が混在する。§2-4：「補塡」の「塡」が画像（alt）で表示される → alt を ⟨…⟩ で残す。
"""
from __future__ import annotations

import difflib
import hashlib
import html
import re
from dataclasses import dataclass, field

from .fetch import Fetcher, FetchError, Response

_SCRIPT = re.compile(r"(?is)<(script|style|noscript)\b.*?</\1\s*>")
_COMMENT = re.compile(r"(?s)<!--.*?-->")
_IMG_ALT = re.compile(r"(?is)<img\b[^>]*?\balt\s*=\s*[\"']([^\"']*)[\"'][^>]*>")
_BLOCK_END = re.compile(r"(?i)<br\s*/?>|</?(p|li|tr|h[1-6]|div|td|th|dt|dd|ul|ol|table|section|article|header|footer|nav|title|head|body)\b[^>]*>")
_TAG = re.compile(r"(?s)<[^>]+>")
_TITLE = re.compile(r"(?is)<title[^>]*>(.*?)</title>")
_IGNORED_ALTS = {"", "別ウィンドウが開きます", "別ウィンドウで開きます", "PDF", "pdf"}


def decode_html(body: bytes, content_type: str | None) -> str:
    m = re.search(r"charset=([\w\-]+)", content_type or "", re.I) or \
        re.search(r"charset=[\"']?([\w\-]+)", body[:4000].decode("ascii", "replace"), re.I)
    cands = ([m.group(1)] if m else []) + ["utf-8", "cp932", "euc-jp"]
    for c in cands:
        c = {"shift_jis": "cp932", "sjis": "cp932", "x-sjis": "cp932", "shift-jis": "cp932"}.get(c.lower(), c)
        try:
            return body.decode(c)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", "replace")


def page_title(text: str) -> str:
    m = _TITLE.search(text)
    return " ".join(html.unescape(m.group(1)).split()) if m else ""


def extract_lines(text: str) -> list[str]:
    """HTML から比較用のテキストの行を取り出す（script・style・コメントを除き、画像の alt は ⟨…⟩ で残す）。"""
    t = _COMMENT.sub(" ", _SCRIPT.sub(" ", text))

    def alt(m: re.Match) -> str:
        a = html.unescape(m.group(1)).strip()
        return "" if a in _IGNORED_ALTS else f"⟨{a}⟩"

    t = _IMG_ALT.sub(alt, t)
    t = _BLOCK_END.sub("\n", t)
    t = html.unescape(_TAG.sub(" ", t))
    lines = []
    for line in t.splitlines():
        s = re.sub(r"[ \t　\xa0]+", " ", line).strip()
        if s:
            lines.append(s)
    return lines


def text_sha(lines: list[str]) -> str:
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def diff_lines(old: list[str], new: list[str]) -> tuple[list[str], list[str]]:
    added, removed = [], []
    for op, a1, a2, b1, b2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if op in ("replace", "delete"):
            removed.extend(old[a1:a2])
        if op in ("replace", "insert"):
            added.extend(new[b1:b2])
    return added, removed


@dataclass
class PageCheck:
    target_id: str
    status: str  # "baseline" | "not_modified" | "unchanged" | "changed" | "missing" | "error"
    http_status: int | None = None
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    title: str = ""
    error: str | None = None
    note: str | None = None


def conditional_headers(state: dict | None) -> dict[str, str]:
    h: dict[str, str] = {}
    if state:
        if state.get("etag"):
            h["If-None-Match"] = state["etag"]
        if state.get("last_modified"):
            h["If-Modified-Since"] = state["last_modified"]
    return h


def check_page(fetcher: Fetcher, url: str, target_id: str, state: dict | None,
               soft404_titles: tuple[str, ...] = ()) -> tuple[PageCheck, dict | None]:
    """返り値の2つ目は保存する新しい状態（変えないなら None）。"""
    try:
        resp: Response = fetcher.get(url, conditional_headers(state))
    except FetchError as e:
        return PageCheck(target_id, "error", error=str(e)), None
    return evaluate_response(resp, target_id, state, soft404_titles)


def evaluate_response(resp: Response, target_id: str, state: dict | None,
                      soft404_titles: tuple[str, ...] = ()) -> tuple[PageCheck, dict | None]:
    if resp.status == 304:
        if state is None:
            return PageCheck(target_id, "error", http_status=304, error="状態がないのに 304 が返った"), None
        return PageCheck(target_id, "not_modified", http_status=304), None
    if resp.status != 200:
        if resp.status in (404, 410) and state is not None and not state.get("missing"):
            new_state = dict(state, missing=True)
            return PageCheck(target_id, "missing", http_status=resp.status, note=f"HTTP {resp.status}"), new_state
        return PageCheck(target_id, "error", http_status=resp.status, error=f"HTTP {resp.status}"), None
    text = decode_html(resp.body, resp.header("content-type"))
    title = page_title(text)
    if any(s in title for s in soft404_titles):
        if state is not None and not state.get("missing"):
            return PageCheck(target_id, "missing", 200, title=title, note="ソフト404（タイトル）"), dict(state, missing=True)
        return PageCheck(target_id, "error", 200, title=title, error="ソフト404（タイトル）"), None
    lines = extract_lines(text)
    new_state = {"etag": resp.header("etag"), "last_modified": resp.header("last-modified"),
                 "sha256": text_sha(lines), "title": title, "lines": lines, "missing": False}
    if state is None:
        return PageCheck(target_id, "baseline", 200, title=title), new_state
    if state.get("sha256") == new_state["sha256"]:
        return PageCheck(target_id, "unchanged", 200, title=title,
                         note="200 が返ったが本文のテキストは同じ（Last-Modified・ETag だけの変化）"), new_state
    added, removed = diff_lines(state.get("lines") or [], lines)
    return PageCheck(target_id, "changed", 200, added=added, removed=removed, title=title), new_state


def matching_lines(lines: list[str], keywords: tuple[str, ...]) -> list[str]:
    return [l for l in lines if any(k in l for k in keywords)]

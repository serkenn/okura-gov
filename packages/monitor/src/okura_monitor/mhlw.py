"""厚労省 法令等データベースの「登載準備中の新着通知」（newindex.html）の解析。

根拠：docs/public-sources/20261109_R3-tsutatsu_monitoring-sources.md §1.2（データベースは毎月更新。更新までの間に発出された
通知は「登載準備中のコーナー」に載り、登載後にコーナーから削除される）、docs/measurements/20261109_R3-tsutatsu_fetch-and-monitor-probe.md
§1（Last-Modified あり、ETag なし、304 を返す）・§2-5（登載後は PDF の URL が消える）。

ページの形（2026-11-12 に取得して確かめた）：
  <A name=tu_10> … <B>保険局 新着の通知</B> … <B>令和８年１１月２日掲載</b> …
  <LI style="list-style-type: circle"><A HREF="../../doc/tsuchi/T261102S0050.pdf">通知名（令和８年10月30日保医発1030第２号）(PDF,388KB)</A> …【保険局医療課　…関係】
  <LI style="list-style-type:disc;"><A HREF="…">新旧対照条文(PDF,55KB)</A>（添付。前の通知に属する）
"""
from __future__ import annotations

import html
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

from .targets import MhlwNoticeRule
from .wareki import parse_wareki

_TOKEN = re.compile(
    r"<B>\s*(?P<dept>[^<]+?)\s*新着の通知\s*</B>"
    r"|<B>\s*(?P<posted>[^<]*?掲載)\s*</b>"
    r"|<LI\s+style=\"list-style-type:\s*(?P<li>circle|disc);?\"\s*>\s*<A\s+HREF=\"(?P<href>[^\"]+)\"[^>]*>(?P<title>.*?)</A>(?P<after>.*?)(?=<LI\b|</UL>|<BR>|<br>|$)",
    re.I | re.S,
)
_SECTION = re.compile(r"【([^】]+)】")
_SIZE = re.compile(r"\s*\((?:PDF|Word|Excel|ZIP)[^)]*\)\s*$", re.I)
_ISSUED = re.compile(r"[（(]([^（）()]*?(?:明治|大正|昭和|平成|令和)[^（）()]*?日[^（）()]*?)[）)]\s*$")
_NUMBER = re.compile(r"日\s*([^（）]*?(?:第[0-9０-９]+号|事務連絡))")


def _clean(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


@dataclass
class Notice:
    key: str  # PDF の URL（絶対）
    department: str
    posted: str  # 「令和８年１１月６日掲載」の日付（ISO。読めなければ元の文字列）
    title: str
    url: str
    section: str = ""
    issued: str | None = None  # 発出日（ISO）
    number: str | None = None  # 番号（保発1030第２号、事務連絡 など）
    attachments: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def parse_new_notices(text: str, base_url: str) -> list[Notice]:
    items: list[Notice] = []
    dept, posted = "", ""
    for m in _TOKEN.finditer(text):
        if m.group("dept"):
            dept, posted = _clean(m.group("dept")), ""
        elif m.group("posted"):
            raw = _clean(m.group("posted"))
            wd = parse_wareki(raw)
            posted = wd.iso() if wd and wd.iso() else raw
        else:
            url = urllib.parse.urljoin(base_url, html.unescape(m.group("href")))
            title = _SIZE.sub("", _clean(m.group("title")))
            if m.group("li").lower() == "disc":
                if items:
                    items[-1].attachments.append({"title": title, "url": url})
                continue
            sec = _SECTION.search(_clean(m.group("after") or ""))
            issued = number = None
            im = _ISSUED.search(title)
            if im:
                inner = im.group(1)
                wd = parse_wareki(inner)
                issued = wd.iso() if wd else None
                nm = _NUMBER.search(inner)
                number = nm.group(1).strip() if nm else None
            items.append(Notice(url, dept, posted, title, url, sec.group(1) if sec else "", issued, number))
    return items


def is_relevant(n: Notice, rule: MhlwNoticeRule) -> bool:
    if any(k in n.title for k in rule.title_keywords):
        return True
    if n.department in rule.departments and not any(x in n.section for x in rule.excluded_sections):
        return True
    return False


def diff_notices(old_keys: set[str], items: list[Notice]) -> tuple[list[Notice], list[str]]:
    """新しく載った通知と、消えた通知の key（データベースへの登載で消えるのが普通）。"""
    new = [n for n in items if n.key not in old_keys]
    now = {n.key for n in items}
    removed = sorted(k for k in old_keys if k not in now)
    return new, removed

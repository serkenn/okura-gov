"""e-Gov 法令API v2 の改正履歴（/law_revisions/{law_id}）と、一括ダウンロードの日次 CSV（file_section=3）。

根拠：docs/measurements/20261109_R1-laws_egov-api-monitoring.md
- §3：`/law_revisions/{id}?updated_from=<日付>` で更新された版だけが返る。新しい版が加わると、隣の既存の版の `updated` も
  同時刻に変わることがある → `updated` だけの変化は issue にせず、報告に載せる。
- §2：未施行の版も入る。施行日未定の版には amendment_scheduled_enforcement_date と amendment_enforcement_comment が入る。
- §5：日次 CSV（UTF-8 BOM つき）の列。「令和九十九年…」の仮の施行日がある（wareki.py）。日曜などは HTTP 500 が返った。
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import urllib.parse
import zipfile
from dataclasses import dataclass, field
from typing import Any

from .fetch import Fetcher, FetchError
from .targets import BULK_RELATED_KEYWORDS, EGOV_API_BASE, EGOV_BULK_UPDATED
from .wareki import parse_wareki

# 版の項目のうち、変われば issue にするもの（current_revision_status は施行日が来れば変わるので含めない）
SIGNIFICANT_FIELDS = (
    "amendment_law_num", "amendment_law_title", "amendment_promulgate_date", "amendment_enforcement_date",
    "amendment_scheduled_enforcement_date", "amendment_enforcement_comment", "repeal_status", "mission", "amendment_type",
)
KEPT_FIELDS = SIGNIFICANT_FIELDS + ("law_title", "current_revision_status", "updated")
ORIGINAL_AMEND_ID = "000000000000000"


def revisions_url(law_id: str, updated_from: str | None = None) -> str:
    url = f"{EGOV_API_BASE}/law_revisions/{urllib.parse.quote(law_id)}"
    if updated_from:
        url += "?" + urllib.parse.urlencode({"updated_from": updated_from})
    return url


def law_page_url(revision_id: str) -> str:
    """e-Gov 法令検索の版のページ（一括ダウンロードの CSV の本文URLと同じ形：/law/<law_id>/<施行日>_<改正法令ID>）。"""
    law_id, _, rest = revision_id.partition("_")
    return f"https://laws.e-gov.go.jp/law/{law_id}/{rest}" if rest else f"https://laws.e-gov.go.jp/law/{law_id}"


def amend_law_id(revision_id: str) -> str:
    parts = revision_id.split("_")
    return parts[2] if len(parts) >= 3 else ORIGINAL_AMEND_ID


def parse_revisions(body: bytes) -> dict[str, dict[str, Any]]:
    data = json.loads(body.decode("utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for r in data.get("revisions") or []:
        rid = r.get("law_revision_id")
        if rid:
            out[rid] = {k: r.get(k) for k in KEPT_FIELDS}
    return out


@dataclass
class RevisionEvent:
    kind: str  # "new" | "changed" | "touched"（updated だけ変わった）
    law_id: str
    revision_id: str
    revision: dict[str, Any]
    changes: dict[str, tuple[Any, Any]] = field(default_factory=dict)


def diff_revisions(old: dict[str, dict[str, Any]], new: dict[str, dict[str, Any]], law_id: str) -> list[RevisionEvent]:
    """前回の版の一覧 old と、今回取得した版 new（updated_from で絞った一部でもよい）を比べる。"""
    events = []
    for rid, rev in new.items():
        if rid not in old:
            events.append(RevisionEvent("new", law_id, rid, rev))
            continue
        prev = old[rid]
        changes = {k: (prev.get(k), rev.get(k)) for k in SIGNIFICANT_FIELDS if prev.get(k) != rev.get(k)}
        if changes:
            events.append(RevisionEvent("changed", law_id, rid, rev, changes))
        elif prev.get("updated") != rev.get("updated"):
            events.append(RevisionEvent("touched", law_id, rid, rev, {"updated": (prev.get("updated"), rev.get("updated"))}))
    return events


@dataclass
class LawCheck:
    law_id: str
    status: str  # "baseline" | "checked" | "error"
    title: str | None = None
    events: list[RevisionEvent] = field(default_factory=list)
    error: str | None = None
    url: str | None = None


def check_law(fetcher: Fetcher, law_id: str, state: dict | None, today: dt.date) -> tuple[LawCheck, dict | None]:
    """1つの法令の改正履歴を確かめる。返り値の2つ目は保存する新しい状態（失敗なら None）。

    初回（状態なし）は全件を取って基準にする（issue は作らない）。2回目からは updated_from=前回の確認日の前日。
    """
    if state is None:
        url = revisions_url(law_id)
    else:
        since = dt.date.fromisoformat(state["checked_on"]) - dt.timedelta(days=1)
        url = revisions_url(law_id, since.isoformat())
    try:
        resp = fetcher.get(url, {"Accept": "application/json"})
    except FetchError as e:
        return LawCheck(law_id, "error", error=str(e), url=url), None
    if resp.status != 200:
        return LawCheck(law_id, "error", error=f"HTTP {resp.status}", url=url), None
    try:
        got = parse_revisions(resp.body)
    except (ValueError, UnicodeDecodeError) as e:
        return LawCheck(law_id, "error", error=f"JSON を読めない: {e}", url=url), None
    old = (state or {}).get("revisions", {})
    title = next((r.get("law_title") for r in got.values() if r.get("law_title")), None) or (state or {}).get("title")
    merged = dict(old)
    merged.update(got)
    new_state = {"law_id": law_id, "title": title, "checked_on": today.isoformat(), "revisions": merged}
    if state is None:
        return LawCheck(law_id, "baseline", title=title, url=url), new_state
    return LawCheck(law_id, "checked", title=title, events=diff_revisions(old, got, law_id), url=url), new_state


# ---------------------------------------------------------------------------------------------
# 一括ダウンロードの日次 CSV
# ---------------------------------------------------------------------------------------------

CSV_COLUMNS = ("法令種別", "法令番号", "法令名", "法令名読み", "旧法令名", "公布日", "改正法令名", "改正法令番号",
               "改正法令公布日", "施行日", "施行日備考", "法令ID", "本文URL", "未施行")


@dataclass
class BulkRow:
    law_type: str
    law_num: str
    law_title: str
    amendment_law_title: str
    amendment_law_num: str
    amendment_promulgate_raw: str
    enforcement_raw: str
    enforcement_date: str | None  # ISO。仮の日付なら None
    enforcement_provisional: bool
    enforcement_note: str
    law_id: str
    url: str
    unenforced: bool

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def parse_bulk_csv(data: bytes) -> list[BulkRow]:
    for enc in ("utf-8-sig", "cp932"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("CSV の文字コードを読めない")
    reader = csv.DictReader(io.StringIO(text))
    missing = [c for c in ("法令名", "施行日", "法令ID") if c not in (reader.fieldnames or [])]
    if missing:
        raise ValueError(f"CSV の列がない: {missing}（列：{reader.fieldnames}）")
    rows = []
    for r in reader:
        g = lambda k: (r.get(k) or "").strip()  # noqa: E731
        wd = parse_wareki(g("施行日"))
        rows.append(BulkRow(
            law_type=g("法令種別"), law_num=g("法令番号"), law_title=g("法令名"),
            amendment_law_title=g("改正法令名"), amendment_law_num=g("改正法令番号"),
            amendment_promulgate_raw=g("改正法令公布日"), enforcement_raw=g("施行日"),
            enforcement_date=wd.iso() if wd else None, enforcement_provisional=bool(wd and wd.provisional),
            enforcement_note=g("施行日備考"), law_id=g("法令ID"), url=g("本文URL"), unenforced=g("未施行") != "",
        ))
    return rows


def csv_from_zip(data: bytes, max_csv_bytes: int = 50_000_000) -> tuple[str, bytes]:
    """ZIP から CSV だけをデータとして読む（展開しない。XML は読まない）。"""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        csvs = [i for i in z.infolist() if i.filename.lower().endswith(".csv")]
        if not csvs:
            raise ValueError("ZIP に CSV がない")
        info = csvs[0]
        if info.file_size > max_csv_bytes:
            raise ValueError(f"CSV が大きすぎる: {info.file_size}")
        return info.filename, z.read(info)


def is_related(row: BulkRow, keywords: tuple[str, ...] = BULK_RELATED_KEYWORDS) -> bool:
    hay = row.law_title + " " + row.amendment_law_title
    return any(k in hay for k in keywords)


@dataclass
class BulkDay:
    date: str
    status: str  # "ok" | "no_data" | "error"
    http_status: int | None = None
    csv_name: str | None = None
    rows: list[BulkRow] = field(default_factory=list)
    error: str | None = None
    url: str | None = None


def fetch_bulk_day(fetcher: Fetcher, day: dt.date) -> BulkDay:
    url = EGOV_BULK_UPDATED.format(yyyymmdd=day.strftime("%Y%m%d"))
    try:
        resp = fetcher.get(url)
    except FetchError as e:
        return BulkDay(day.isoformat(), "error", error=str(e), url=url)
    if resp.status != 200:
        # 更新のない日（日曜など）は HTTP 500 の HTML が返った（実測 §5）。404 も「その日のデータなし」とする。
        if resp.status in (404, 500):
            return BulkDay(day.isoformat(), "no_data", http_status=resp.status, url=url)
        return BulkDay(day.isoformat(), "error", http_status=resp.status, error=f"HTTP {resp.status}", url=url)
    if not resp.body.startswith(b"PK"):
        return BulkDay(day.isoformat(), "no_data", http_status=resp.status, error="ZIP ではない応答", url=url)
    try:
        name, raw = csv_from_zip(resp.body)
        rows = parse_bulk_csv(raw)
    except (ValueError, zipfile.BadZipFile) as e:
        return BulkDay(day.isoformat(), "error", http_status=200, error=str(e), url=url)
    return BulkDay(day.isoformat(), "ok", http_status=200, csv_name=name, rows=rows, url=url)


def bulk_dates_to_check(state: dict | None, today: dt.date, max_days: int) -> list[dt.date]:
    """確かめる日付（前回の続きの日から昨日まで。最大 max_days 日。古い日から）。初回は空（基準の日を記録するだけ）。"""
    if state is None or not state.get("cursor"):
        return []
    cursor = dt.date.fromisoformat(state["cursor"])
    days = []
    d = cursor + dt.timedelta(days=1)
    last = today - dt.timedelta(days=1)
    while d <= last and len(days) < max_days:
        days.append(d)
        d += dt.timedelta(days=1)
    return days

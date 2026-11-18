"""1回の監視の実行：取得 → 前回の状態との比較 → issue の下書き → 状態の保存。

各情報源の初回は、状態を記録するだけで issue は作らない（基準の記録）。取得に失敗した対象は、状態を進めない（次回にやり直す）。
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from . import __version__
from .builders import draft_from_notice, draft_from_page, drafts_from_bulk_day, drafts_from_revision_events
from .core_refs import CoreReferences
from .egov import bulk_dates_to_check, check_law, fetch_bulk_day, is_related
from .fetch import Fetcher, FetchError
from .issues import IssueDraft
from .mhlw import diff_notices, is_relevant, parse_new_notices
from .pages import check_page, conditional_headers, decode_html, matching_lines
from .state import StateStore
from .targets import MHLW_NOTICES, PAGE_TARGETS, MhlwNoticeRule, PageTarget

JST = dt.timezone(dt.timedelta(hours=9))
SOURCES = ("egov", "bulk", "mhlw", "pages")
BULK_KEEP_DAYS = 120


@dataclass
class RunOptions:
    sources: tuple[str, ...] = SOURCES
    bulk_max_days: int = 7
    page_targets: tuple[PageTarget, ...] = PAGE_TARGETS
    mhlw_rule: MhlwNoticeRule = MHLW_NOTICES
    law_ids: tuple[str, ...] | None = None  # 指定すれば判定コアから集めた一覧の代わりに使う


@dataclass
class RunResult:
    report: dict[str, Any]
    drafts: list[IssueDraft] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return bool(self.report.get("errors"))


def law_ids_for(refs: CoreReferences | None, options: RunOptions) -> list[str]:
    if options.law_ids is not None:
        return list(options.law_ids)
    return sorted(refs.laws) if refs else []


def run(fetcher: Fetcher, store: StateStore, refs: CoreReferences | None, now: dt.datetime | None = None,
        options: RunOptions | None = None) -> RunResult:
    options = options or RunOptions()
    now = (now or dt.datetime.now(JST)).astimezone(JST)
    today = now.date()
    detected_on = today.isoformat()
    report: dict[str, Any] = {"run_at": now.isoformat(timespec="seconds"), "okura_monitor": __version__,
                              "sources": list(options.sources), "errors": []}
    if refs is not None:
        report["core_refs"] = {"files_scanned": refs.files_scanned, "laws": len(refs.laws),
                               "unresolved_law_names": dict(refs.unresolved)}
    drafts: list[IssueDraft] = []
    law_ids = law_ids_for(refs, options)

    if "egov" in options.sources:
        drafts += _run_egov(fetcher, store, refs, law_ids, today, detected_on, report)
    if "bulk" in options.sources:
        drafts += _run_bulk(fetcher, store, refs, set(law_ids), today, detected_on, options, report)
    if "mhlw" in options.sources:
        drafts += _run_mhlw(fetcher, store, refs, detected_on, options.mhlw_rule, report)
    if "pages" in options.sources:
        drafts += _run_pages(fetcher, store, options.page_targets, detected_on, report)
    report["targets"] = {"egov_laws": len(law_ids) if "egov" in options.sources else 0,
                         "bulk_csv": 1 if "bulk" in options.sources else 0,
                         "mhlw_new_notices": 1 if "mhlw" in options.sources else 0,
                         "pages": len(options.page_targets) if "pages" in options.sources else 0}
    report["issues"] = [{"key": d.key, "title": d.title} for d in drafts]
    return RunResult(report, drafts)


def _run_egov(fetcher, store, refs, law_ids, today, detected_on, report) -> list[IssueDraft]:
    rows, events, titles = [], [], {}
    for law_id in law_ids:
        name = f"egov_revisions/{law_id}"
        check, new_state = check_law(fetcher, law_id, store.load(name), today)
        if new_state is not None:
            store.save(name, new_state)
        titles[law_id] = check.title or (refs.laws[law_id].title if refs and law_id in refs.laws else law_id)
        counts = {k: sum(1 for e in check.events if e.kind == k) for k in ("new", "changed", "touched")}
        rows.append({"law_id": law_id, "title": titles[law_id], "status": check.status, "events": counts,
                     "touched": [e.revision_id for e in check.events if e.kind == "touched"], "error": check.error})
        if check.error:
            report["errors"].append({"source": "egov", "target": law_id, "url": check.url, "error": check.error})
        events += check.events
    report["egov"] = rows
    return drafts_from_revision_events(events, titles, refs, detected_on)


def _run_bulk(fetcher, store, refs, target_ids, today, detected_on, options, report) -> list[IssueDraft]:
    state = store.load("egov_bulk")
    out: dict[str, Any] = {"days": []}
    drafts: list[IssueDraft] = []
    if state is None:
        state = {"cursor": (today - dt.timedelta(days=1)).isoformat(), "days": {}}
        store.save("egov_bulk", state)
        out["status"] = "baseline"
        out["cursor"] = state["cursor"]
        report["bulk"] = out
        return drafts
    for day in bulk_dates_to_check(state, today, options.bulk_max_days):
        res = fetch_bulk_day(fetcher, day)
        target_rows = [r for r in res.rows if r.law_id in target_ids]
        rec = {"date": res.date, "status": res.status, "http_status": res.http_status, "csv": res.csv_name,
               "rows": len(res.rows), "provisional_dates": sum(1 for r in res.rows if r.enforcement_provisional),
               "related_rows": sum(1 for r in res.rows if r.law_id not in target_ids and is_related(r)),
               "target_rows": [_cross_check(store, r) for r in target_rows], "error": res.error}
        out["days"].append(rec)
        if res.status == "error":
            report["errors"].append({"source": "bulk", "target": res.date, "url": res.url, "error": res.error})
            break  # この日から次回にやり直す
        drafts += drafts_from_bulk_day(res, target_ids, refs, detected_on, is_related)
        state["cursor"] = res.date
        state.setdefault("days", {})[res.date] = {"status": res.status, "rows": len(res.rows), "http_status": res.http_status}
    keep = sorted(state.get("days", {}))[-BULK_KEEP_DAYS:]
    state["days"] = {k: state["days"][k] for k in keep}
    store.save("egov_bulk", state)
    out["status"] = "checked"
    out["cursor"] = state["cursor"]
    report["bulk"] = out
    return drafts


def _cross_check(store: StateStore, row) -> dict[str, Any]:
    """日次 CSV の監視対象の行が、e-Gov 法令API の状態（改正履歴）にも載っているか（報告用）。"""
    rest = row.url.rstrip("/").rsplit("/", 1)[-1] if row.url else ""
    rid = f"{row.law_id}_{rest}" if rest else None
    st = store.load(f"egov_revisions/{row.law_id}") or {}
    return {"law_id": row.law_id, "law_title": row.law_title, "revision_id": rid,
            "enforcement": row.enforcement_date or row.enforcement_raw, "provisional": row.enforcement_provisional,
            "in_api_state": bool(rid and rid in (st.get("revisions") or {}))}


def _run_mhlw(fetcher, store, refs, detected_on, rule: MhlwNoticeRule, report) -> list[IssueDraft]:
    state = store.load("mhlw_new_notices")
    out: dict[str, Any] = {"url": rule.url}
    report["mhlw"] = out
    try:
        resp = fetcher.get(rule.url, conditional_headers(state))
    except FetchError as e:
        out["status"] = "error"
        report["errors"].append({"source": "mhlw", "target": rule.url, "error": str(e)})
        return []
    if resp.status == 304 and state is not None:
        out["status"] = "not_modified"
        return []
    if resp.status != 200:
        out["status"] = "error"
        report["errors"].append({"source": "mhlw", "target": rule.url, "error": f"HTTP {resp.status}"})
        return []
    items = parse_new_notices(decode_html(resp.body, resp.header("content-type")), rule.url)
    if not items:
        out["status"] = "error"
        report["errors"].append({"source": "mhlw", "target": rule.url,
                                 "error": "通知を1件も読めなかった（ページの形が変わった可能性）。状態は進めない"})
        return []
    new_state = {"last_modified": resp.header("last-modified"), "etag": resp.header("etag"),
                 "keys": sorted(n.key for n in items), "items": len(items)}
    store.save("mhlw_new_notices", new_state)
    if state is None:
        out.update(status="baseline", items=len(items))
        return []
    new, removed = diff_notices(set(state.get("keys") or []), items)
    relevant = [n for n in new if is_relevant(n, rule)]
    out.update(status="checked", items=len(items), removed=len(removed),
               new=[{"title": n.title, "department": n.department, "section": n.section, "relevant": is_relevant(n, rule),
                     "url": n.url} for n in new])
    return [draft_from_notice(n, refs, detected_on) for n in relevant]


def _run_pages(fetcher, store, targets, detected_on, report) -> list[IssueDraft]:
    rows, drafts = [], []
    for t in targets:
        name = f"pages/{t.id}"
        check, new_state = check_page(fetcher, t.url, t.id, store.load(name), t.soft404_titles)
        if new_state is not None:
            store.save(name, new_state)
        matched: list[str] = []
        if check.status == "changed":
            matched = matching_lines(check.added, t.keywords) if t.keywords else check.added
            if matched or not t.keywords:
                drafts.append(draft_from_page(t, check, detected_on, matched))
        elif check.status == "missing":
            drafts.append(draft_from_page(t, check, detected_on, []))
        if check.error:
            report["errors"].append({"source": "pages", "target": t.id, "url": t.url, "error": check.error})
        rows.append({"id": t.id, "url": t.url, "status": check.status, "http_status": check.http_status,
                     "added": len(check.added), "removed": len(check.removed), "matched": len(matched),
                     "note": check.note, "error": check.error})
    report["pages"] = rows
    return drafts

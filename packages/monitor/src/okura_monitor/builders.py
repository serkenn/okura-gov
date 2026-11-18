"""検知した変化（e-Gov の版・日次 CSV の行・厚労省の新着通知・一覧ページの差分）から issue の下書きを作る。"""
from __future__ import annotations

import hashlib
from collections import defaultdict

from .core_refs import CoreReferences
from .egov import ORIGINAL_AMEND_ID, BulkDay, RevisionEvent, amend_law_id, law_page_url, revisions_url
from .issues import (EnforcementInfo, IssueDraft, applicable_years_hint, candidates_for_laws, candidates_for_notice,
                     candidates_from_citations, layers_for)
from .mhlw import Notice
from .pages import PageCheck
from .targets import MHLW_NOTICES, PageTarget

MAX_PAGE_LINES = 60


def _short_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:10]


def _enforcement_of(rev: dict, label: str) -> EnforcementInfo:
    date = rev.get("amendment_enforcement_date")
    notes = []
    if rev.get("current_revision_status"):
        notes.append(f"状態 {rev['current_revision_status']}")
    if rev.get("amendment_scheduled_enforcement_date") and rev.get("amendment_scheduled_enforcement_date") != date:
        notes.append(f"予定 {rev['amendment_scheduled_enforcement_date']}")
    if rev.get("amendment_enforcement_comment"):
        notes.append(f"施行期日の定め：{rev['amendment_enforcement_comment']}")
        if not date:
            notes.append("施行日は未定")
    return EnforcementInfo(label, date, "。".join(notes))


def drafts_from_revision_events(events: list[RevisionEvent], titles: dict[str, str], refs: CoreReferences | None,
                                detected_on: str) -> list[IssueDraft]:
    """新しい版・施行日などが変わった版を、改正法令ごと（と、新しい版か変化か）に1つの issue にまとめる。"""
    groups: dict[tuple[str, str], list[RevisionEvent]] = defaultdict(list)
    for e in events:
        if e.kind in ("new", "changed"):
            groups[(amend_law_id(e.revision_id), e.kind)].append(e)
    drafts = []
    for (amend, kind), evs in sorted(groups.items()):
        law_ids = list(dict.fromkeys(e.law_id for e in evs))
        law_titles = [titles.get(l) or evs[0].revision.get("law_title") or l for l in law_ids]
        first = evs[0].revision
        if amend == ORIGINAL_AMEND_ID:
            head = "制定時の版"
        else:
            head = f"{first.get('amendment_law_num') or amend}（{first.get('amendment_law_title') or '改正法令名なし'}）"
        names = "・".join(law_titles[:3]) + (f" ほか{len(law_titles) - 3}法令" if len(law_titles) > 3 else "")
        what = "に新しい版" if kind == "new" else "の版の施行日・改正法令の情報が変わった"
        summary = []
        for e in evs:
            t = titles.get(e.law_id) or e.revision.get("law_title") or e.law_id
            if kind == "new":
                summary.append(f"{t}：版 `{e.revision_id}` が載った（施行 {e.revision.get('amendment_enforcement_date') or '未定'}、"
                               f"{e.revision.get('current_revision_status') or '状態不明'}、更新 {e.revision.get('updated')}）")
            else:
                ch = "、".join(f"{k}：{a!r} → {b!r}" for k, (a, b) in e.changes.items())
                summary.append(f"{t}：版 `{e.revision_id}` の {ch}")
            if (e.revision.get("repeal_status") or "None") != "None":
                summary.append(f"{t}：廃止等の状態 {e.revision.get('repeal_status')}")
        urls = list(dict.fromkeys([law_page_url(e.revision_id) for e in evs] + [revisions_url(l) for l in law_ids]))
        enforcement = [_enforcement_of(e.revision, f"{titles.get(e.law_id) or e.law_id}（{e.revision_id}）") for e in evs]
        cand = candidates_for_laws(refs, law_ids)
        drafts.append(IssueDraft(
            key=(f"egov-{law_ids[0]}-original-{kind}-{detected_on}" if amend == ORIGINAL_AMEND_ID
                 else f"egov-{amend}-{kind}-{detected_on}"),
            title=f"[法令] {head}：{names}{what}",
            source="e-Gov 法令API v2（/law_revisions）",
            detected_on=detected_on,
            summary=summary,
            source_urls=urls,
            enforcement=enforcement,
            applicable_years=applicable_years_hint(law_titles, [x.date for x in enforcement]),
            layers=layers_for(cand),
            candidates=cand,
            details={"events": [{"kind": e.kind, "law_id": e.law_id, "revision_id": e.revision_id, "revision": e.revision,
                                 "changes": {k: list(v) for k, v in e.changes.items()}} for e in evs]},
            labels=["法令の変更", "e-Gov"],
        ))
    return drafts


def drafts_from_bulk_day(day: BulkDay, target_ids: set[str], refs: CoreReferences | None, detected_on: str,
                         related) -> list[IssueDraft]:
    """監視対象の外の法令のうち、関係しうるもの（related(row) が真）を、その日の1つの issue にまとめる（改正法令ごとに節を分ける）。
    監視対象の法令の行は e-Gov 法令API の側で issue にするので、ここでは作らない（報告で突き合わせる）。"""
    groups: dict[str, list] = defaultdict(list)
    for row in day.rows:
        if row.law_id in target_ids or not related(row):
            continue
        groups[row.amendment_law_num or row.law_num].append(row)
    if not groups:
        return []
    summary, enforcement, all_rows = [], [], []
    for amend, rows in sorted(groups.items()):
        first = rows[0]
        titles = list(dict.fromkeys(r.law_title for r in rows))
        summary.append(f"改正法令 {amend or '番号なし'}（{first.amendment_law_title or '改正法令名なし'}、公布 {first.amendment_promulgate_raw or '不明'}）："
                       + "・".join(titles))
        for r in rows:
            note = []
            if r.enforcement_provisional:
                note.append(f"仮の日付（CSV の値「{r.enforcement_raw}」。施行日未定の改正に入る値と推測：実在の日付として扱わない）")
            if r.enforcement_note:
                note.append(f"施行日備考：{r.enforcement_note}")
            if r.unenforced:
                note.append("未施行")
            enforcement.append(EnforcementInfo(f"{r.law_title}（{r.law_id}）／{amend}", r.enforcement_date, "。".join(note)))
            all_rows.append(r)
    summary.append("いずれも判定コアが引用していない法令。関係するかどうかを人が判断し、関係するなら targets.LAW_NAMES と判定コアの出典に足す。")
    first_titles = list(dict.fromkeys(r.law_title for r in all_rows))
    cand = candidates_from_citations([])
    return [IssueDraft(
        key=f"egov-bulk-{day.date}",
        title=f"[法令・監視対象外] {day.date} の更新法令データ：関係しうる改正 {len(groups)} 件（{'・'.join(first_titles[:2])}"
              + (" ほか" if len(first_titles) > 2 else "") + "）",
        source=f"e-Gov 法令データ一括ダウンロード（更新法令データ {day.date}、{day.csv_name}）",
        detected_on=detected_on,
        summary=summary,
        source_urls=list(dict.fromkeys([r.url for r in all_rows if r.url] + ([day.url] if day.url else []))),
        enforcement=enforcement,
        applicable_years=applicable_years_hint(first_titles, [e.date for e in enforcement]),
        layers=layers_for(cand),
        candidates=cand,
        details={"rows": [r.to_dict() for r in all_rows]},
        labels=["法令の変更", "e-Gov", "監視対象外"],
    )]


def draft_from_notice(n: Notice, refs: CoreReferences | None, detected_on: str) -> IssueDraft:
    cand = candidates_for_notice(refs, n.number, n.title)
    return IssueDraft(
        key=f"mhlw-{_short_hash(n.key)}",
        title=f"[通知] {n.title}",
        source="厚生労働省 法令等データベース「登載準備中の新着通知」",
        detected_on=detected_on,
        summary=[f"{n.department}（{n.section}）に {n.posted} 掲載。発出日 {n.issued or '不明'}、番号 {n.number or '不明'}",
                 "登載準備中のコーナーの PDF は、データベースへの登載後に URL が消える（R3 実測 §2-5）。"
                 "原文はデータベースの t_doc で引き直し、docs/public-sources に記録する。"],
        source_urls=[n.url] + [a["url"] for a in n.attachments] + [MHLW_NOTICES.page_url],
        enforcement=[EnforcementInfo("通知", None, "適用日は通知の本文で確かめる")],
        applicable_years=applicable_years_hint([n.title, n.section], [n.issued]),
        layers=layers_for(cand),
        candidates=cand,
        details={"notice": n.to_dict()},
        labels=["通知の変更", "厚労省"],
    )


def draft_from_page(target: PageTarget, check: PageCheck, detected_on: str, matched: list[str]) -> IssueDraft:
    if check.status == "missing":
        summary = [f"ページが見つからない（{check.note}）。削除・移動の可能性。監視の URL を直す（targets.PAGE_TARGETS）"]
        title = f"[{target.org}] {target.title}：ページが見つからない"
    else:
        summary = [f"本文のテキストが変わった（足された行 {len(check.added)}、消えた行 {len(check.removed)}）"]
        if matched:
            summary.append("監視の語を含む足された行：")
            summary += [f"  - {l}" for l in matched[:MAX_PAGE_LINES]]
        title = f"[{target.org}] {target.title}：更新"
    return IssueDraft(
        key=f"page-{target.id}-{detected_on}",
        title=title,
        source=f"{target.org}の一覧ページ（条件付き取得とテキストの比較）",
        detected_on=detected_on,
        summary=summary,
        source_urls=[target.url],
        enforcement=[],
        applicable_years="未確定（リンク先の資料で確かめる）",
        layers=layers_for({}),
        candidates=candidates_from_citations([]),
        details={"added": check.added[:MAX_PAGE_LINES * 2], "removed": check.removed[:MAX_PAGE_LINES * 2],
                 "keywords": list(target.keywords)},
        labels=["通達・案内の変更", target.org],
    )

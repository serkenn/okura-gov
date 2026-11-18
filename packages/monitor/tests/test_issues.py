import json
from pathlib import Path

from okura_monitor import core_refs
from okura_monitor.builders import draft_from_notice, drafts_from_bulk_day, drafts_from_revision_events
from okura_monitor.egov import BulkDay, BulkRow, RevisionEvent, is_related
from okura_monitor.github import post_issues
from okura_monitor.issues import render_markdown, write_drafts
from okura_monitor.mhlw import Notice
from okura_monitor.state import StateStore

PARAM_YAML = """\
description: 基礎控除（所得税法第86条第1項）
第1号:
  上限:
    description: >-
      第1号の区分の上限: 説明の続き
      law: これはキーではない
    metadata:
      law: 所得税法第86条第1項第1号
      reference:
        - docs/public-sources/x.md#2
    values:
      2025-01-01:
        value: 23500000
        metadata:
          law_revision: 340AC0000000033_20251218_507AC0000000013
  額:
    metadata: {law: 地方税法施行令第47条の3・同施行規則第9条の21, source_kind: 政令}
    values:
      2025-01-01: {value: 1, metadata: {比較: 以下}}
"""
CONCEPT_YAML = """\
制度: 健保
概念:
  - id: 健保.年間収入
    名称: 年間収入
    定義: {条文: 令和7年7月4日 保発0704第1号・年管発0704第1号 記1, 根拠の種類: 通知・事務連絡, 出典: [docs/x.md#1]}
  - id: 健保.被扶養者か
    定義:
      条文: 健康保険法第3条第7項、架空の特例法第2条
"""


def _core(tmp_path: Path) -> Path:
    root = tmp_path / "okura_core"
    p = root / "rules" / "personal_deductions" / "parameters" / "所得税"
    p.mkdir(parents=True)
    (p / "基礎控除.yaml").write_text(PARAM_YAML, encoding="utf-8")
    c = root / "rules" / "hifuyosha"
    (c / "parameters").mkdir(parents=True)
    (c / "concepts.yaml").write_text(CONCEPT_YAML, encoding="utf-8")
    return root


def test_collect_laws_parameters_concepts_and_unresolved(tmp_path):
    refs = core_refs.collect(_core(tmp_path), include_extra=False)
    assert set(refs.laws) == {"340AC0000000033", "325CO0000000245", "329M50000002023", "211AC0000000070"}
    it = refs.laws["340AC0000000033"]
    assert it.names("parameter") == ["所得税.基礎控除.第1号.上限"]  # law と law_revision が同じパラメータに付く
    # 「同施行規則」は直前の「地方税法施行令」から読む
    assert refs.laws["329M50000002023"].names("parameter") == ["所得税.基礎控除.第1号.額"]
    assert refs.laws["211AC0000000070"].names("concept") == ["健保.被扶養者か"]
    assert refs.unresolved == {"架空の特例法": 1}
    assert [c.name for c in refs.notices] == ["健保.年間収入"]


def _rev(rid, enforcement, **kw):
    r = {"law_title": "所得税法", "amendment_law_num": "令和八年法律第十二号", "amendment_law_title": "所得税法等の一部を改正する法律",
         "amendment_enforcement_date": enforcement, "amendment_scheduled_enforcement_date": None,
         "amendment_enforcement_comment": None, "current_revision_status": "UnEnforced", "repeal_status": "None",
         "updated": "2026-11-11T03:00:00+09:00"}
    r.update(kw)
    return r


def test_revision_events_grouped_by_amending_law_with_d9_fields(tmp_path):
    refs = core_refs.collect(_core(tmp_path), include_extra=False)
    events = [
        RevisionEvent("new", "340AC0000000033", "340AC0000000033_20261201_508AC0000000012", _rev("a", "2026-12-01")),
        RevisionEvent("new", "325AC0000000226", "325AC0000000226_20270101_508AC0000000012",
                      _rev("b", None, law_title="地方税法", amendment_scheduled_enforcement_date="2029-06-01",
                           amendment_enforcement_comment="公布の日から起算して三年を超えない範囲内において政令で定める日")),
        RevisionEvent("touched", "340AC0000000033", "340AC0000000033_20250401_x", _rev("c", "2025-04-01")),
    ]
    drafts = drafts_from_revision_events(events, {"340AC0000000033": "所得税法", "325AC0000000226": "地方税法"}, refs, "2026-11-12")
    assert len(drafts) == 1  # touched は issue にしない。同じ改正法令は1つにまとめる
    d = drafts[0]
    assert d.key == "egov-508AC0000000012-new-2026-11-12"
    assert "令和八年法律第十二号" in d.title and "所得税法・地方税法" in d.title
    assert "https://laws.e-gov.go.jp/law/340AC0000000033/20261201_508AC0000000012" in d.source_urls
    assert [e.date for e in d.enforcement] == ["2026-12-01", None]
    assert "施行日は未定" in d.enforcement[1].note
    assert d.applicable_years.startswith("未確定") and "年分以後" in d.applicable_years
    assert d.candidates["parameters"] == ["所得税.基礎控除.第1号.上限"]
    md = render_markdown(d)
    for heading in ("## 施行日", "## 適用年分", "## 影響する層（D9）", "## 関係する概念・パラメータ・モジュールの候補", "## 出典 URL"):
        assert heading in md
    assert "- [ ] 判定コア：パラメータ" in md and "候補：このパラメータ 1 件" in md
    paths = write_drafts(tmp_path / "out", drafts)
    data = json.loads(paths[0].with_suffix(".json").read_text(encoding="utf-8"))
    assert data["key"] == d.key and data["enforcement"][1]["date"] is None


def test_bulk_draft_skips_targets_and_marks_provisional_date():
    rows = [
        BulkRow("法律", "n", "租税特別措置法", "所得税法等の一部を改正する法律", "令和七年法律第十三号", "", "令和八年十一月一日",
                "2026-11-01", False, "", "332AC0000000026", "u1", False),
        BulkRow("法律", "n", "国民健康保険法施行規則の特例省令", "健康保険法等の一部を改正する法律", "令和七年法律第九十九号", "",
                "令和九十九年十二月三十一日", None, True, "…の施行の日", "999M00000000001", "u2", True),
        BulkRow("法律", "n", "道路交通法", "道路交通法の一部を改正する法律", "令和七年法律第一号", "", "令和八年一月一日",
                "2026-01-01", False, "", "335AC0000000105", "u3", False),
    ]
    day = BulkDay("2026-11-11", "ok", 200, "R081111.csv", rows, url="bulk")
    drafts = drafts_from_bulk_day(day, {"332AC0000000026"}, None, "2026-11-12", is_related)
    assert len(drafts) == 1  # 監視対象の行（API 側で扱う）と関係しない行は除く
    d = drafts[0]
    assert d.enforcement[0].date is None and "仮の日付" in d.enforcement[0].note and "施行日備考" in d.enforcement[0].note
    assert "監視対象外" in d.title


def test_notice_draft_candidates_by_notice_prefix(tmp_path):
    refs = core_refs.collect(_core(tmp_path), include_extra=False)
    n = Notice("k", "保険局", "2026-11-02", "被扶養者の認定について（令和８年10月30日保発1030第１号）", "https://x/T.pdf",
               "保険局保険課", "2026-10-30", "保発1030第１号")
    d = draft_from_notice(n, refs, "2026-11-12")
    assert d.candidates["concepts"] == ["健保.年間収入"] and "保発" in d.candidates["match"]
    assert core_refs.notice_prefixes("令和８年10月30日保保発1030第１号・年管管発1030第２号") == {"保保発", "年管管発"}
    assert d.source_urls[0] == "https://x/T.pdf"


class _Proc:
    def __init__(self, rc, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def test_post_issues_once_per_key(tmp_path):
    n = Notice("k", "保険局", "2026-11-02", "被扶養者について", "https://x/T.pdf")
    drafts = [draft_from_notice(n, None, "2026-11-12")]
    write_drafts(tmp_path, drafts)
    store, calls = StateStore(tmp_path / "state"), []

    def runner(args):
        calls.append(args)
        return _Proc(0, "https://github.com/o/r/issues/1\n")

    first = post_issues(drafts, tmp_path / "issues", store, repo="o/r", gh="gh", runner=runner)
    second = post_issues(drafts, tmp_path / "issues", store, repo="o/r", gh="gh", runner=runner)
    assert first[0]["status"] == "posted" and second[0]["status"] == "already_posted" and len(calls) == 1
    assert calls[0][:3] == ["gh", "issue", "create"] and "--repo" in calls[0]

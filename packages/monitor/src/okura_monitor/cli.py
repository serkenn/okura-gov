"""コマンド：python -I -X utf8 -m okura_monitor run --state-dir <DIR> --out <DIR>

終了コード：0 完了、2 使い方の誤り（-I なしの起動を含む）、3 一部の対象を取得できなかった（出力は書く。状態はその対象だけ進めない）。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from . import USER_AGENT, __version__
from .core_refs import collect, default_core_src
from .fetch import UrllibFetcher
from .github import post_issues
from .issues import write_drafts
from .runner import JST, SOURCES, RunOptions, run
from .state import StateStore
from .targets import MHLW_NOTICES, PAGE_TARGETS


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="okura_monitor", description="法令・通知・通達の変更を監視し、issue の下書きを作る")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="監視を1回実行する")
    r.add_argument("--state-dir", required=True, type=Path, help="前回の状態を置くディレクトリ（なければ作る）")
    r.add_argument("--out", required=True, type=Path, help="下書き・報告を書くディレクトリ（中に実行ごとのディレクトリを作る）")
    r.add_argument("--core-src", type=Path, default=None,
                   help="判定コアの src（packages/core/src）。既定はこのリポジトリの中を探す")
    r.add_argument("--sources", default=",".join(SOURCES), help=f"使う情報源（カンマ区切り。{','.join(SOURCES)}）")
    r.add_argument("--law-id", action="append", default=None,
                   help="e-Gov の改正履歴を確かめる法令IDをこれだけにする（複数可。既定は判定コアから集めた全部）")
    r.add_argument("--bulk-max-days", type=int, default=7, help="日次 CSV を1回で遡る日数の上限")
    r.add_argument("--min-interval", type=float, default=1.5, help="リクエストの間隔（秒。1 未満は 1 にする）")
    r.add_argument("--post-github", action="store_true", help="gh コマンドで issue を作る（既定は出力だけ）")
    r.add_argument("--repo", default=None, help="gh に渡す --repo（OWNER/NAME）")
    r.add_argument("--label", action="append", default=[], help="gh に渡す --label（複数可。ラベルはリポジトリに先に作っておく）")

    t = sub.add_parser("targets", help="監視対象の一覧を出す（ネットワークに出ない）")
    t.add_argument("--core-src", type=Path, default=None)
    t.add_argument("--json", action="store_true", help="JSON で出す")
    return p


def _refs(core_src: Path | None):
    src = core_src or default_core_src()
    if src is None:
        raise SystemExit("判定コアの src が見つからない。--core-src で指定する")
    return collect(src)


def cmd_targets(args) -> int:
    refs = _refs(args.core_src)
    data = {
        "egov_laws": [{"law_id": t.law_id, "title": t.title, "citations": len(t.citations),
                       "modules": dict(t.modules()), "reasons": t.reasons} for t in sorted(refs.laws.values(), key=lambda x: x.law_id)],
        "unresolved_law_names": dict(refs.unresolved),
        "bulk_csv": "e-Gov 一括ダウンロードの更新法令データ（file_section=3、日次）",
        "mhlw_new_notices": MHLW_NOTICES.url,
        "pages": [{"id": p.id, "org": p.org, "title": p.title, "url": p.url, "keywords": list(p.keywords)} for p in PAGE_TARGETS],
    }
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=1))
    else:
        print(f"e-Gov 法令API の改正履歴：{len(data['egov_laws'])} 法令")
        for l in data["egov_laws"]:
            print(f"  {l['law_id']}  {l['title']}  引用 {l['citations']}  {'; '.join(l['reasons'])}")
        if data["unresolved_law_names"]:
            print("表にない法令名（targets.LAW_NAMES に足す候補）：", data["unresolved_law_names"])
        print("一括ダウンロードの日次 CSV：1")
        print(f"厚労省の登載準備中の新着通知：1（{MHLW_NOTICES.url}）")
        print(f"一覧ページ：{len(PAGE_TARGETS)}")
        for p in PAGE_TARGETS:
            print(f"  {p.id}  {p.org} {p.title}  {p.url}")
    return 0


def _report_md(report: dict, run_dir: Path, posted: list[dict] | None) -> str:
    L = [f"# 監視の報告 {report['run_at']}", "", f"- 対象：{report.get('targets')}", f"- issue の下書き：{len(report['issues'])} 件"]
    for i in report["issues"]:
        L.append(f"  - {i['title']}（`{i['key']}`）")
    L.append(f"- 取得の誤り：{len(report['errors'])} 件")
    for e in report["errors"]:
        L.append(f"  - {e['source']} {e.get('target')}: {e['error']}")
    if report.get("core_refs", {}).get("unresolved_law_names"):
        L.append(f"- 表にない法令名：{report['core_refs']['unresolved_law_names']}")
    if posted is not None:
        L.append(f"- GitHub：{posted}")
    L.append(f"- 詳細：{(run_dir / 'report.json').name}")
    return "\n".join(L) + "\n"


def cmd_run(args) -> int:
    sources = tuple(s.strip() for s in args.sources.split(",") if s.strip())
    bad = [s for s in sources if s not in SOURCES]
    if bad:
        print(f"知らない情報源：{bad}", file=sys.stderr)
        return 2
    refs = _refs(args.core_src) if ("egov" in sources or "bulk" in sources or "mhlw" in sources) else None
    store = StateStore(args.state_dir)
    fetcher = UrllibFetcher(user_agent=USER_AGENT, min_interval=args.min_interval)
    now = dt.datetime.now(JST)
    result = run(fetcher, store, refs, now, RunOptions(sources=sources, bulk_max_days=args.bulk_max_days,
                                                        law_ids=tuple(args.law_id) if args.law_id else None))
    run_dir = args.out / now.strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=False)
    write_drafts(run_dir, result.drafts)
    result.report["requests"] = fetcher.requests
    posted = None
    if args.post_github and result.drafts:
        posted = post_issues(result.drafts, run_dir / "issues", store, repo=args.repo, labels=args.label)
        result.report["github"] = posted
    (run_dir / "report.json").write_text(json.dumps(result.report, ensure_ascii=False, indent=1), encoding="utf-8")
    (run_dir / "report.md").write_text(_report_md(result.report, run_dir, posted), encoding="utf-8")
    print(f"{run_dir}  issue の下書き {len(result.drafts)} 件、取得の誤り {len(result.report['errors'])} 件、リクエスト {fetcher.requests} 回")
    return 3 if result.has_errors else 0


def main(argv: list[str] | None = None) -> int:
    if not sys.flags.isolated:
        print("python -I -X utf8 -m okura_monitor … で起動する（-I：カレントディレクトリの .py を読まない）", file=sys.stderr)
        return 2
    args = _parser().parse_args(argv)
    if args.command == "targets":
        return cmd_targets(args)
    return cmd_run(args)

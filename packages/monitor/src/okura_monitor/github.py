"""任意の機能：gh コマンドがあれば、issue の下書きを GitHub の issue として作る。既定では使わない（出力だけ）。

- 同じ key の下書きは2回投稿しない（投稿した key と URL を状態のディレクトリの github_posted.json に記録する）。
- gh の認証・リポジトリの指定は gh に任せる（--repo を渡さなければ、gh が今のディレクトリのリポジトリを使う）。
- シェルを通さずに引数の配列で呼ぶ。
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable

from .issues import IssueDraft, safe_key
from .state import StateStore

Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


def _default_runner(args: list[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=120, check=False)


def post_issues(drafts: list[IssueDraft], issues_dir: Path, store: StateStore, *, repo: str | None = None,
                labels: list[str] | None = None, gh: str | None = None, runner: Runner = _default_runner) -> list[dict]:
    gh = gh or shutil.which("gh")
    if not gh:
        return [{"key": d.key, "status": "skipped", "error": "gh コマンドが見つからない"} for d in drafts]
    posted = store.load("github_posted") or {}
    results = []
    for d in drafts:
        if d.key in posted:
            results.append({"key": d.key, "status": "already_posted", "url": posted[d.key]})
            continue
        args = [gh, "issue", "create", "--title", d.title, "--body-file", str(issues_dir / f"{safe_key(d.key)}.md")]
        if repo:
            args += ["--repo", repo]
        for label in labels or []:
            args += ["--label", label]
        proc = runner(args)
        if proc.returncode == 0:
            url = (proc.stdout or "").strip().splitlines()[-1] if (proc.stdout or "").strip() else ""
            posted[d.key] = url
            store.save("github_posted", posted)
            results.append({"key": d.key, "status": "posted", "url": url})
        else:
            results.append({"key": d.key, "status": "error", "error": (proc.stderr or "").strip()[:500]})
    return results

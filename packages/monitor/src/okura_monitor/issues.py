"""issue の下書き（D9）：影響する層の欄、施行日、適用年分、出典 URL、関係する概念・パラメータ・モジュールの候補。

下書きは Markdown（本文）と JSON（機械で読む）の2つのファイルにする。値（基準額など）は書かない。
原文（e-Gov の版と改正法の附則、通知の本文）で確かめるまでは、候補と手がかりだけを書く（AGENTS.md：記憶で基準額を書かない）。
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .core_refs import Citation, CoreReferences, LawTarget, notice_prefixes
from .targets import LAYERS

MAX_LIST = 25
PROCEDURE = (
    "原文を確かめ、`docs/public-sources/` に出典URL・取得日・対象年分つきで記録する（AGENTS.md）",
    "施行日（適用開始日）つきのテストケースを先に書く（D9）",
    "パラメータ・計算式・概念辞書を直す（パラメータの日付のキーは適用開始日。施行日と出典はメタデータ：SCOPE §10 T2）",
    "上の「影響する層」を確かめ、中間表現・記録・出力の整形に及ぶかを決める",
)
#: 対応の始め方（2026-11-12 ユーザーの決定：issue のあとは人が Claude Code で対応する。packages/monitor/README.md §4.1）
HOW_TO_START = (
    "このリポジトリを手元に取り、Claude Code を開く（`git pull` で最新にする）",
    "Claude Code に「スキル law-change で、この issue に対応して」と頼み、この issue の URL か番号を渡す"
    "（エージェントは `gh issue view <番号>` で本文を読む）",
    "変化が法令の値に関係しないと分かったら、確かめた結果をこの issue に書いて閉じる",
)


@dataclass
class EnforcementInfo:
    label: str
    date: str | None  # ISO。未定・仮の日付なら None
    note: str = ""


@dataclass
class IssueDraft:
    key: str
    title: str
    source: str  # egov_api | egov_bulk | mhlw_notice | page
    detected_on: str
    summary: list[str]
    source_urls: list[str]
    enforcement: list[EnforcementInfo] = field(default_factory=list)
    applicable_years: str = ""
    layers: list[dict[str, Any]] = field(default_factory=list)
    candidates: dict[str, Any] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)
    labels: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------------------------
# 候補（関係する概念・パラメータ・モジュール）と影響する層
# ---------------------------------------------------------------------------------------------

def candidates_from_citations(citations: Iterable[Citation]) -> dict[str, Any]:
    cits = list(citations)
    modules = Counter(c.module for c in cits)
    params: dict[str, None] = {}
    concepts: dict[str, None] = {}
    files: dict[str, None] = {}
    for c in cits:
        (params if c.kind == "parameter" else concepts).setdefault(c.name, None)
        files.setdefault(c.file, None)
    return {
        "modules": [{"module": m, "citations": n} for m, n in modules.most_common()],
        "parameters": list(params),
        "concepts": list(concepts),
        "files": list(files),
    }


def candidates_for_laws(refs: CoreReferences | None, law_ids: Iterable[str]) -> dict[str, Any]:
    if refs is None:
        return candidates_from_citations([])
    cits: list[Citation] = []
    for law_id in law_ids:
        t: LawTarget | None = refs.laws.get(law_id)
        if t:
            cits.extend(t.citations)
    return candidates_from_citations(cits)


def candidates_for_notice(refs: CoreReferences | None, number: str | None, title: str) -> dict[str, Any]:
    if refs is None or not refs.notices:
        return candidates_from_citations([])
    prefixes = notice_prefixes(number or "") | notice_prefixes(title)
    hit = [c for c in refs.notices if prefixes and notice_prefixes(c.text) & prefixes]
    cand = candidates_from_citations(hit or refs.notices)
    cand["match"] = "通知の番号の発翰（" + "・".join(sorted(prefixes)) + "）が同じ出典" if hit else "通知を引用する出典の全部（番号で絞れなかった）"
    return cand


def layers_for(candidates: dict[str, Any]) -> list[dict[str, Any]]:
    """影響する層の欄。チェックは人が付ける。判定コアの出典から言えることだけを「候補」として書く。"""
    n_params = len(candidates.get("parameters") or [])
    n_concepts = len(candidates.get("concepts") or [])
    modules = [m["module"] for m in candidates.get("modules") or []]
    hint = {
        "parameters": f"候補：このパラメータ {n_params} 件が出典に引用" if n_params else "",
        "formulas": f"候補：モジュール {', '.join(modules[:8])}" if modules else "",
        "concepts": f"候補：概念 {n_concepts} 件が定義の条文に引用" if n_concepts else "",
    }
    return [{"layer": key, "name": name, "checked": False, "hint": hint.get(key, "")} for key, name in LAYERS]


# ---------------------------------------------------------------------------------------------
# 適用年分の手がかり（判定はしない）
# ---------------------------------------------------------------------------------------------

def applicable_years_hint(titles: Iterable[str], dates: Iterable[str | None]) -> str:
    ts = " ".join(titles)
    years = sorted({d[:4] for d in dates if d})
    lines = ["未確定（自動では決めない）。"]
    if re.search(r"所得税|租税特別措置|復興特別所得税|国税", ts):
        lines.append("所得税の基準額は施行日ではなく、改正法の附則の「令和X年分以後」で適用が決まる"
                     "（docs/hypotheses/20261109_R1-laws_hypotheses.md H2）。被改正法令の本文に収録された改正法の附則（SupplProvision の AmendLawNum）で確かめる。")
    if re.search(r"地方税|森林環境税", ts):
        lines.append("住民税は「令和X年度以後」の年度と前年の所得の軸で書かれる（同 H2）。附則で確かめる。")
    if re.search(r"健康保険|国民健康保険|国民年金|厚生年金|共済|介護保険", ts):
        lines.append("社会保険は、施行日・認定日・年度など規則ごとに軸が違う（docs/hypotheses/20261109_R3-tsutatsu_record-facts-and-monitoring.md H2）。附則・通知の本文で確かめる。")
    if years:
        lines.append("参考：施行日の年は " + "、".join(years) + "。")
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------
# Markdown・JSON の書き出し
# ---------------------------------------------------------------------------------------------

def _list(items: list[str], limit: int = MAX_LIST) -> list[str]:
    out = [f"- `{x}`" for x in items[:limit]]
    if len(items) > limit:
        out.append(f"- ほか {len(items) - limit} 件（JSON に全件）")
    return out or ["- （なし）"]


def render_markdown(d: IssueDraft) -> str:
    L = [f"# {d.title}", ""]
    L += [f"- 検知日：{d.detected_on}", f"- 情報源：{d.source}", f"- 下書きの key：`{d.key}`", ""]
    L += ["## 何が変わったか", ""] + [f"- {s}" for s in d.summary] + [""]
    L += ["## 出典 URL", ""] + [f"- {u}" for u in d.source_urls] + [""]
    L += ["## 施行日", ""]
    if d.enforcement:
        L += ["| 対象 | 施行日 | 備考 |", "|---|---|---|"]
        for e in d.enforcement:
            L.append(f"| {e.label} | {e.date or '未定・要確認'} | {e.note.replace('|', '／')} |")
    else:
        L.append("要確認（原文から読む）")
    L += ["", "## 適用年分", "", d.applicable_years or "未確定（原文で確かめる）", ""]
    L += ["## 影響する層（D9）", ""]
    for l in d.layers:
        L.append(f"- [{'x' if l['checked'] else ' '}] {l['name']}" + (f"（{l['hint']}）" if l.get("hint") else ""))
    L += ["", "## 関係する概念・パラメータ・モジュールの候補", ""]
    c = d.candidates
    if c.get("match"):
        L += [f"絞り方：{c['match']}", ""]
    L += ["モジュール：", ""]
    L += [f"- `{m['module']}`（出典 {m['citations']} か所）" for m in c.get("modules") or []] or ["- （なし）"]
    L += ["", "パラメータ：", ""] + _list(c.get("parameters") or [])
    L += ["", "概念：", ""] + _list(c.get("concepts") or [])
    L += ["", "## 対応の始め方", ""] + [f"{i}. {p}" for i, p in enumerate(HOW_TO_START, 1)]
    L += ["", "## 対応の手順", ""] + [f"{i}. {p}" for i, p in enumerate(PROCEDURE, 1)]
    if d.details:
        L += ["", "<details><summary>取得したデータ</summary>", "", "```json",
              json.dumps(d.details, ensure_ascii=False, indent=1)[:20000], "```", "", "</details>"]
    L += ["", "---", "この下書きは okura_monitor が自動で作った。候補は判定コアの出典の文字列から機械的に拾ったもので、"
          "値・施行日・適用年分は原文で確かめるまで使わない。"]
    return "\n".join(L) + "\n"


_SAFE_KEY = re.compile(r"[^A-Za-z0-9_.-]+")


def safe_key(key: str) -> str:
    return _SAFE_KEY.sub("_", key)[:150]


def write_drafts(out_dir: Path, drafts: list[IssueDraft]) -> list[Path]:
    d = out_dir / "issues"
    d.mkdir(parents=True, exist_ok=True)
    paths = []
    for draft in drafts:
        base = safe_key(draft.key)
        (d / f"{base}.md").write_text(render_markdown(draft), encoding="utf-8")
        (d / f"{base}.json").write_text(json.dumps(draft.to_json(), ensure_ascii=False, indent=1), encoding="utf-8")
        paths.append(d / f"{base}.md")
    return paths

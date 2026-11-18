"""IMPL7 tokubetsu laws: 個人の特別償却・割増償却（租税特別措置法 第2章 個人の所得税の特例）の条文を、取得済みの e-Gov 法令API v2 の JSON から取り出す。

調べること（docs/public-sources/20261112_impl-research7_tokubetsu-shokyaku.md）：
- 個人の特別償却・割増償却の条（措法第10条の2〜第19条の範囲で、見出しに「特別償却」「割増償却」「償却の特例」を含む本則の条）の見出しと、
  「青色申告書を提出する個人」を要件とするか。
- 特別償却不足額・割増償却不足額の繰越（「償却不足額」を含む項）。
- 特別償却等に関する複数の規定の不適用（第19条）。

実行（リポジトリのルートで。標準ライブラリのみ。ネットワークを使わない）:
  .work/venvs/core/Scripts/python.exe -I -X utf8 scripts/IMPL7_tokubetsu_laws.py <ダウンロード先>
    <ダウンロード先> は scripts/IMPL5_laws_egov.py fetch が作ったディレクトリ（sochi_2025-12-31.json・sochi_2026-12-31.json を読む。
    2026-11-12 の実行では .work/downloads/20261112-084817_IMPL5_laws_egov。取得の記録は scripts/results/IMPL5_laws_egov/fetch_log_20261112-084817.json）。

- ダウンロードしたものは信頼できないデータとして json.loads で読むだけ。中では何も実行しない。
- テキスト化は scripts/IMPL5_laws_egov.py（もとは scripts/IMPL4_laws_egov.py）を写した（import はしない）。
- 出力 scripts/results/IMPL7_tokubetsu_laws/
    articles_<asof>.txt   見出しで選んだ条の全文（「## Num=」）
    summary_<asof>.json   条ごとの見出し・青色申告書を提出する個人の要件の有無・償却不足額の語を含む項の番号・本文の SHA-256
    sames.json            条の本文の SHA-256 を版の間で比べた結果
"""
import hashlib
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
NAME = "IMPL7_tokubetsu_laws"
OUT = ROOT / "scripts" / "results" / NAME
ASOFS = ("2025-12-31", "2026-12-31")  # 令和7年分・令和8年分の年末の版
CAPTION_WORDS = ("特別償却", "割増償却", "償却の特例")
BLOCK_LIKE = {"Paragraph", "Item"} | {f"Subitem{i}" for i in range(1, 11)}


# ---- scripts/IMPL5_laws_egov.py から写した（テキスト化） ----
def inline(n):
    if isinstance(n, str):
        return n
    if n.get("tag") in ("Rt",):
        return ""
    parts = [inline(c) for c in n.get("children", [])]
    if n.get("tag", "").endswith("Sentence") and any(isinstance(c, dict) and c.get("tag") == "Column" for c in n.get("children", [])):
        return "　".join(p for p in parts if p)
    return "".join(parts)


def render(n, depth, lines):
    if isinstance(n, str):
        if n.strip():
            lines.append("  " * depth + n)
        return
    tag = n.get("tag", "")
    ch = n.get("children", [])
    if tag in BLOCK_LIKE:
        title = "".join(inline(c) for c in ch if isinstance(c, dict) and c.get("tag", "").endswith(("Num", "Title")) and c.get("tag") != "ParagraphCaption")
        sent = [c for c in ch if isinstance(c, dict) and c.get("tag", "").endswith("Sentence")]
        body = "　".join(inline(s) for s in sent)
        cap = [inline(c) for c in ch if isinstance(c, dict) and c.get("tag") == "ParagraphCaption"]
        if cap:
            lines.append("  " * depth + cap[0])
        num = n.get("attr", {}).get("Num", "")
        prefix = title if title else (f"（{tag}{num}）" if tag == "Paragraph" else "")
        lines.append("  " * depth + (prefix + "　" if prefix else "") + body)
        for c in ch:
            if isinstance(c, dict) and not (c.get("tag", "").endswith(("Num", "Title", "Sentence")) or c.get("tag") == "ParagraphCaption"):
                render(c, depth + 1, lines)
        return
    if tag == "TableRow":
        cells = [inline(c).replace("\n", " ") for c in ch if isinstance(c, dict)]
        lines.append("  " * depth + "| " + " | ".join(cells) + " |")
        return
    if tag in ("ArticleCaption", "ArticleTitle", "SupplProvisionLabel", "ChapterTitle", "SectionTitle", "AppdxTableTitle"):
        lines.append("  " * depth + inline(n))
        return
    for c in ch:
        render(c, depth, lines)


def walk(n, fn, path=()):
    if isinstance(n, dict):
        fn(n, path)
        for c in n.get("children", []):
            walk(c, fn, path + (n.get("tag"),))
# ---- 写しここまで ----


def text_of(n):
    lines = []
    render(n, 0, lines)
    return "\n".join(lines)


def num_key(num):
    """本則の条の Num（"10_2" など）を並べるための組。"""
    return tuple(int(x) for x in re.findall(r"\d+", num or "0"))


def in_range(num):
    k = num_key(num)
    return (10, 2) <= k + (0,) * (2 - len(k)) <= (19, 99)


def caption(a):
    for c in a.get("children", []):
        if isinstance(c, dict) and c.get("tag") == "ArticleCaption":
            return inline(c)
    return ""


def main(dl):
    dl = pathlib.Path(dl)
    OUT.mkdir(parents=True, exist_ok=True)
    sames = {}
    for asof in ASOFS:
        p = dl / f"sochi_{asof}.json"
        if not p.exists():
            print("missing", p)
            continue
        d = json.loads(p.read_bytes())
        ri = d.get("revision_info") or {}
        arts = []
        walk(d["law_full_text"], lambda n, path: arts.append(n) if n.get("tag") == "Article" and "SupplProvision" not in path else None)
        chosen = [a for a in arts if in_range(a["attr"].get("Num")) and (any(w in caption(a) for w in CAPTION_WORDS) or a["attr"].get("Num") == "19")]
        lines = [
            f"# 租税特別措置法 332AC0000000026 asof={asof}",
            f"# law_revision_id={ri.get('law_revision_id')} 改正法令={ri.get('amendment_law_num')} 施行日={ri.get('amendment_enforcement_date')}",
            f"# 元データ={p.relative_to(ROOT) if p.is_relative_to(ROOT) else p} sha256={hashlib.sha256(p.read_bytes()).hexdigest()}",
            "",
        ]
        summary = []
        sames[asof] = {}
        for a in chosen:
            num = a["attr"].get("Num")
            t = text_of(a)
            sames[asof][num] = hashlib.sha256(t.encode("utf-8")).hexdigest()
            lines += [f"## Num={num}", t, ""]
            paras = [c for c in a.get("children", []) if isinstance(c, dict) and c.get("tag") == "Paragraph"]
            summary.append({
                "num": num,
                "caption": caption(a),
                "blue_return_individual": "青色申告書を提出する個人" in t,
                "paragraphs_with_shortfall": [pp["attr"].get("Num") for pp in paras if "償却不足額" in text_of(pp)],
                "sha256": sames[asof][num],
            })
        (OUT / f"articles_{asof}.txt").write_text("\n".join(lines), encoding="utf-8")
        (OUT / f"summary_{asof}.json").write_text(json.dumps({"revision": ri, "articles": summary}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(asof, len(chosen))
    a, b = ASOFS
    if a in sames and b in sames:
        changed = sorted((set(sames[a]) | set(sames[b])) - {n for n in sames[a] if sames[a].get(n) == sames[b].get(n)}, key=num_key)
        (OUT / "sames.json").write_text(json.dumps({"changed": changed, "sha256": sames}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", OUT)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    main(sys.argv[1])

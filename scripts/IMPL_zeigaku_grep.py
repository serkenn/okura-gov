"""IMPL zeigaku: 取得済みの e-Gov 法令本文 JSON（.work/downloads/... の中）から、文字列を含む条（本則・附則）を探して表示する。

実行（リポジトリの直下から。ダウンロード先のディレクトリの中では実行しない）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_zeigaku_grep.py <JSONのパス> <出力名> <文字列> [<文字列> ...]
- JSON はデータとして読むだけ（json.loads）。標準ライブラリのみ。
- 結果は scripts/results/IMPL_zeigaku_grep/<出力名>.txt に書く（該当した条の全文と、所在＝本則/附則の改正法令番号）。
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def text_of(n):
    if isinstance(n, str):
        return n
    if not isinstance(n, dict) or n.get("tag") == "Rt":
        return ""
    return "".join(text_of(c) for c in n.get("children", []))


def lines_of(n, depth=0, out=None):
    """項・号ごとに改行したテキスト（簡易）。"""
    if out is None:
        out = []
    if isinstance(n, str):
        return out
    tag = n.get("tag", "")
    if tag in ("Paragraph", "Item") or tag.startswith("Subitem") and not tag.endswith(("Title", "Sentence")):
        head = []
        rest = []
        for c in n.get("children", []):
            if isinstance(c, dict) and c.get("tag", "").endswith(("Num", "Title", "Sentence", "Caption")):
                head.append(text_of(c))
            else:
                rest.append(c)
        out.append("  " * depth + "　".join(h for h in head if h))
        for c in rest:
            lines_of(c, depth + 1, out)
        return out
    if tag == "TableRow":
        out.append("  " * depth + "| " + " | ".join(text_of(c) for c in n.get("children", []) if isinstance(c, dict)) + " |")
        return out
    if tag in ("ArticleCaption", "ArticleTitle"):
        out.append("  " * depth + text_of(n))
        return out
    for c in n.get("children", []):
        lines_of(c, depth, out)
    return out


def main():
    src = pathlib.Path(sys.argv[1]).resolve()
    name = sys.argv[2]
    needles = sys.argv[3:]
    d = json.loads(src.read_bytes())
    ri = d.get("revision_info") or {}
    res = [f"# source={src.relative_to(ROOT) if src.is_relative_to(ROOT) else src}",
           f"# law_revision_id={ri.get('law_revision_id')} 施行日={ri.get('amendment_enforcement_date')} 状態={ri.get('current_revision_status')}",
           f"# needles={needles}", ""]
    hits = 0

    def visit(n, where):
        nonlocal hits
        if not isinstance(n, dict):
            return
        tag = n.get("tag")
        if tag == "SupplProvision":
            where = "附則 AmendLawNum=" + (n.get("attr", {}).get("AmendLawNum") or "(原始附則)")
        if tag == "Article":
            t = text_of(n)
            if any(s in t for s in needles):
                hits += 1
                res.append(f"## {where} Num={n.get('attr', {}).get('Num')}")
                res.extend(lines_of(n))
                res.append("")
            return
        for c in n.get("children", []):
            visit(c, where)
    visit(d["law_full_text"], "本則")
    res.append(f"# hits={hits}")
    out = ROOT / "scripts" / "results" / "IMPL_zeigaku_grep"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}.txt").write_text("\n".join(res) + "\n", encoding="utf-8")
    print(name, "hits", hits)


if __name__ == "__main__":
    main()

"""IMPL_iryohi: scripts/IMPL_iryohi_egov.py が保存した法令本文の JSON から、正規表現に一致する箇所を条ごとに書き出す。

目的：所得税法第73条第1項の「総所得金額、退職所得金額及び山林所得金額の合計額」を、
租税特別措置法・同施行令が分離課税の所得を含める形で読み替えている箇所を探す。

実行（ダウンロードしたディレクトリを引数で渡す。そのディレクトリの中ではインタプリタを実行しない）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_iryohi_egov_grep.py .work/downloads/<ts>_IMPL_iryohi_egov

- JSON は json.loads で読むだけ（コードとして評価しない）。
- 出力：scripts/results/IMPL_iryohi_egov/grep_<略称>_<asof>.txt と grep_summary.json
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "results" / "IMPL_iryohi_egov"

TARGETS = ["sochi_2025-12-31", "sochi_2026-12-31", "sochi-rei_2025-12-31", "sochi-rei_2026-12-31",
           "shotoku-rei_2025-12-31", "shotoku_2025-12-31"]
PATTERNS = [
    r"第七十三条第一項",
    r"第七十二条から第八十七条まで",
    r"第二章第四節（所得控除）",
    r"総所得金額、退職所得金額及び山林所得金額の合計額",
]


def text_of(n):
    if isinstance(n, str):
        return n
    if not isinstance(n, dict) or n.get("tag") == "Rt":
        return ""
    return "".join(text_of(c) for c in n.get("children", []))


def walk(n, fn, path=()):
    if isinstance(n, dict):
        fn(n, path)
        for c in n.get("children", []):
            walk(c, fn, path + (n.get("tag"),))


def caption(a):
    for c in a.get("children", []):
        if isinstance(c, dict) and c.get("tag") == "ArticleCaption":
            return text_of(c)
    return ""


def main():
    dl = pathlib.Path(sys.argv[1]).resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {"source_dir": dl.name, "patterns": PATTERNS, "files": {}}
    for t in TARGETS:
        p = dl / f"{t}.json"
        if not p.exists():
            summary["files"][t] = "missing"
            continue
        d = json.loads(p.read_bytes())
        ri = d.get("revision_info") or {}
        arts = []
        walk(d["law_full_text"], lambda n, path: arts.append(n) if n.get("tag") == "Article" and "SupplProvision" not in path else None)
        lines = [f"# {t} law_revision_id={ri.get('law_revision_id')} 状態={ri.get('current_revision_status')}", ""]
        counts = {}
        for pat in PATTERNS:
            lines.append(f"# パターン /{pat}/")
            n = 0
            for a in arts:
                # 項ごとに区切って、一致した項の全文を書く（読替え規定は項の単位で完結するため）
                paras = [c for c in a.get("children", []) if isinstance(c, dict) and c.get("tag") == "Paragraph"]
                for para in paras:
                    pt = text_of(para)
                    if re.search(pat, pt):
                        n += 1
                        lines.append(f"## Num={a.get('attr', {}).get('Num')} {caption(a)} 第{para.get('attr', {}).get('Num')}項")
                        for m in re.finditer(pat, pt):
                            s0 = max(0, m.start() - 300)
                            lines.append("…" + pt[s0:m.end() + 300] + "…")
                        lines.append("")
            counts[pat] = n
            lines.append("")
        (OUT / f"grep_{t}.txt").write_text("\n".join(lines), encoding="utf-8")
        summary["files"][t] = {"law_revision_id": ri.get("law_revision_id"), "counts": counts}
        print(t, counts)
    (OUT / "grep_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()

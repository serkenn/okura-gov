"""IMPL3 amend_suppl: scripts/IMPL3_egov_fetch.py が取得した法令の JSON から、改正法令の附則（SupplProvision の AmendLawNum があるもの）の
条・項のうち、語に当たるものを取り出す（令和9年度分に効く改正の施行日・適用関係を読むため）。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ。ネットワークは使わない）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL3_amend_suppl.py <ダウンロード先>

- 入力：<ダウンロード先>/<略称>_<asof>.json（信頼できないデータ。json.loads で読むだけ）。
- 出力：scripts/results/IMPL3_amend_suppl/<略称>_<asof>.md（改正法令ごとに、当たった項の本文）
- 描画は scripts/IMPL3_egov_fetch.py と同じ（R1_egov_articles.py を写したもの）。
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "results" / "IMPL3_amend_suppl"
JOBS = {
    "chiho_2027-04-01": (r"^令和(七|八)年", r"第三百十四条の七|第三十七条の二|第七百三条の五|寄附金税額控除|特例控除|附則第五条の五"),
    "kokuho_2027-04-01": (r"^令和(七|八)年", r"十八歳|第七十七条|第八十一条|保険料|令和九年"),
    "kokunen_2027-04-01": (r"^令和(七|八)年", r"第八十八条の三|第八十八条の二|第九十条|第八十七条の二"),
    "kokuhorei_2027-04-01": (r"^令和(七|八)年", r"第二十九条の七|限度|十八歳|出産"),
    "chihorei_2027-04-01": (r"^令和(七|八)年", r"第五十六条の八十八の二|第五十六条の八十九|限度|十八歳|出産|特例控除"),
}
BLOCK_LIKE = {"Paragraph", "Item"} | {f"Subitem{i}" for i in range(1, 11)}


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
    if tag in ("ArticleCaption", "ArticleTitle", "SupplProvisionLabel"):
        lines.append("  " * depth + inline(n))
        return
    for c in ch:
        render(c, depth, lines)


def walk(n, fn, path=()):
    if isinstance(n, dict):
        fn(n, path)
        for c in n.get("children", []):
            walk(c, fn, path + (n.get("tag"),))


def main(dl):
    OUT.mkdir(parents=True, exist_ok=True)
    for stem, (law_re, word_re) in JOBS.items():
        p = dl / f"{stem}.json"
        if not p.exists():
            print("missing", p)
            continue
        d = json.loads(p.read_bytes())
        ri = d.get("revision_info") or {}
        supp = []
        walk(d["law_full_text"], lambda n, q: supp.append(n) if n.get("tag") == "SupplProvision" and re.search(law_re, n.get("attr", {}).get("AmendLawNum") or "") else None)
        lines = [f"# 改正附則の抜き出し {stem}（law_revision_id={ri.get('law_revision_id')}）", f"# 改正法令 /{law_re}/、語 /{word_re}/", ""]
        for s in supp:
            an = s["attr"].get("AmendLawNum")
            hits = []
            # 条（Article）ごと、条がなければ項ごとに見る
            units = []
            walk(s, lambda n, q: units.append(n) if n.get("tag") == "Article" else None)
            if not units:
                walk(s, lambda n, q: units.append(n) if n.get("tag") == "Paragraph" and "Paragraph" not in q else None)
            for u in units:
                t = []
                render(u, 0, t)
                txt = "\n".join(t)
                if re.search(word_re, txt):
                    hits.append(txt)
            if hits:
                lines.append(f"## 改正法令 {an}（当たった条・項 {len(hits)}）")
                for h in hits:
                    lines += [h, ""]
        (OUT / f"{stem}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("done", OUT)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    main(pathlib.Path(sys.argv[1]))

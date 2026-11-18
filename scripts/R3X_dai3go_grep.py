"""R3X_dai3go: 取得したテキスト（scripts/R3X_dai3go_fetch.py の text/ と scripts/R3X_dai3go_pdftext.py の *_text.tsv）から、
第3号被保険者の収入基準の根拠に関する語を探し、前後の文字つきで書き出す。ネットワークは使わない。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_dai3go_grep.py

- 入力はすべて、取得したデータから作ったテキスト（信頼できないデータ）。読むだけで、解釈して実行することはない。
- PDF のテキスト（*_text.tsv）は、頁ごとに y の降順・x の昇順に並んだ断片を、同じ y の断片は x の間隔が 12pt を超えたら「｜」で区切ってつなぎ、
  y が変わったら改行して1頁の文字列にする（表の欄が同じ行に並ぶため、欄をまたいだ語の一致は起こりうる。一致した頁は Read ツールの頁指定で原本を確かめる）。
- 国会会議録の .txt は発言ごとに「=====」で区切られているので、一致した発言の日付・会議・発言者の行も書き出す。
- 出力：scripts/results/R3X_dai3go_grep/hits.json（語ごと・ファイルごとの一致、前後 80 字）
        scripts/results/R3X_dai3go_grep/hits.txt（同じ内容を読みやすくしたもの）
"""
import collections
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEXT = ROOT / "scripts" / "results" / "R3X_dai3go_fetch" / "text"
PDFT = ROOT / "scripts" / "results" / "R3X_dai3go_pdftext"
OUT = ROOT / "scripts" / "results" / "R3X_dai3go_grep"
CTX = 80

# 探す語（正規表現）。番号は漢数字・算用数字・全角数字の表記の揺れを許す。
PATTERNS = {
    "認定基準（被扶養配偶者）": r"被扶養配偶者の認定基準",
    "庁保発第13号": r"庁保発第\s*(?:13|１３|一三|十三)\s*号",
    "庁保険発第18号": r"庁保険発第\s*(?:18|１８|一八|十八)\s*号",
    "庁保発第15号": r"庁保発第\s*(?:15|１５|一五|十五)\s*号",
    "平成5年3月5日": r"平成\s*(?:5|５|五)\s*年\s*(?:3|３|三)\s*月\s*(?:5|５|五)\s*日",
    "最終改正": r"最終改正",
    "130万円（漢数字）": r"百三十万",
    "第3号と収入": r"第(?:三|3|３)号被保険者[^。]{0,60}(?:百三十万|130\s*万|一三〇万|一三○万)",
    "施行令第4条の3": r"施行令(?:\(昭和三四年政令第一八四号\))?第(?:四|4)条の(?:三|3)",
    "健康保険の被扶養者の認定の取扱いを勘案": r"被扶養者の認定の取扱いを勘案",
}


def pdf_pages(tsv):
    pages = collections.defaultdict(list)
    last = None
    for line in tsv.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or line.startswith("page\t"):
            continue
        parts = line.split("\t")
        try:
            row = (int(parts[0]), float(parts[2]), float(parts[1]), "\t".join(parts[4:]))
            if len(parts) < 5:
                raise ValueError
        except (ValueError, IndexError):
            # 断片の文字列に改行が含まれていた行（前の断片の続き）。前の断片につなぐ。
            if last is not None:
                y, x, t = pages[last[0]][-1]
                pages[last[0]][-1] = (y, x, t + " " + line)
            continue
        pages[row[0]].append((row[1], row[2], row[3]))
        last = row
    out = {}
    for p, rows in pages.items():
        rows.sort(key=lambda r: (-r[0], r[1]))
        buf, last_y, last_x_end = [], None, None
        for y, x, t in rows:
            if last_y is None or abs(y - last_y) > 1.0:
                buf.append("\n")
            elif last_x_end is not None and x - last_x_end > 12:
                buf.append("｜")
            buf.append(t)
            last_y, last_x_end = y, x + 9.0 * len(t)
        out[p] = "".join(buf)
    return out


def kokkai_header(text, pos):
    i = text.rfind("=" * 60, 0, pos)
    if i < 0:
        return None
    j = text.find("\n", i + 61)
    return text[i + 61:j].strip() if j > 0 else None


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    sources = []
    for f in sorted(TEXT.rglob("*.txt")):
        sources.append((str(f.relative_to(ROOT)).replace("\\", "/"), None, f.read_text(encoding="utf-8")))
    for f in sorted(PDFT.glob("*_text.tsv")):
        for p, t in sorted(pdf_pages(f).items()):
            sources.append((str(f.relative_to(ROOT)).replace("\\", "/"), p, t))
    hits = []
    for name, pat in PATTERNS.items():
        rx = re.compile(pat)
        for src, page, text in sources:
            flat = text
            for m in rx.finditer(flat):
                a, b = max(0, m.start() - CTX), min(len(flat), m.end() + CTX)
                h = {"pattern": name, "file": src, "page": page, "match": m.group(0),
                     "context": flat[a:b].replace("\n", "⏎")}
                if "_kokkai" in src:
                    h["speech"] = kokkai_header(flat, m.start())
                hits.append(h)
    (OUT / "hits.json").write_text(json.dumps({"patterns": PATTERNS, "n_sources": len(sources), "hits": hits},
                                              ensure_ascii=False, indent=1), encoding="utf-8")
    lines = []
    cnt = collections.Counter((h["pattern"], h["file"]) for h in hits)
    lines.append(f"# sources={len(sources)} hits={len(hits)}")
    for (pn, f), n in sorted(cnt.items()):
        lines.append(f"{pn}\t{f}\t{n}")
    lines.append("")
    for h in hits:
        lines.append(f"[{h['pattern']}] {h['file']}" + (f" p{h['page']}" if h["page"] else "") +
                     (f"  <{h['speech']}>" if h.get("speech") else ""))
        lines.append("    " + h["context"])
    (OUT / "hits.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[: 2 + len(cnt)]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

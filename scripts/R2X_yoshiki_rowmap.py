"""R2X_yoshiki_rowmap: R2X_yoshiki_pdftext.py が書き出した文字の位置（<名前>_text.tsv）から、
欄コード（G01・E01・M01 など）ごとに、同じ高さの行番号・左にある科目名・上にある列見出しの候補を並べる。

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_yoshiki_rowmap.py <名前> [<名前> ...]

- 入力：scripts/results/R2X_yoshiki_pdftext/<名前>_text.tsv（PDF は読まない）。
- 出力：scripts/results/R2X_yoshiki_rowmap/<名前>_rowmap.tsv
  列：page, code, x, y, row_no（同じ高さ（|dy|≦3）で欄コードのすぐ左（25pt 以内）にある 1〜2 桁の数字）,
      labels（|dy|≦12 で、欄コード（行番号があればその位置）より左 170pt 以内の文字列。上から順）,
      above（|dx|≦45 で上にある、欄コードでも数字だけでもない文字列のうち近い 2 つ）
- 対応づけは位置からの機械的な候補で、正しいかは目で確かめる（実測の文書に確かめた結果を書く）。
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "scripts" / "results" / "R2X_yoshiki_pdftext"
OUT = ROOT / "scripts" / "results" / "R2X_yoshiki_rowmap"
CODE = re.compile(r"[A-Z]\d{2,3}")
NUM = re.compile(r"\d{1,2}")
NOISE = re.compile(r"[（）()\s円\-－＋+×・]*|\(円\)|（円）")


def load(name):
    rows = []
    for line in (SRC / f"{name}_text.tsv").read_text(encoding="utf-8").splitlines()[2:]:
        p, x, y, font, text = line.split("\t", 4)
        rows.append((int(p), float(x), float(y), text.strip()))
    return rows


def rowmap(name):
    rows = load(name)
    out = ["page\tcode\tx\ty\trow_no\tlabels\tabove"]
    for p, x, y, t in rows:
        if not CODE.fullmatch(t):
            continue
        same = [r for r in rows if r[0] == p and r is not None]
        nums = sorted((r for r in same if NUM.fullmatch(r[3]) and abs(r[2] - y) <= 3 and x - 25 <= r[1] < x), key=lambda r: x - r[1])
        rn = nums[0] if nums else None
        right_edge = rn[1] if rn else x
        labs = sorted((r for r in same if abs(r[2] - y) <= 12 and right_edge - 170 <= r[1] < right_edge
                       and not CODE.fullmatch(r[3]) and not NUM.fullmatch(r[3]) and not NOISE.fullmatch(r[3])),
                      key=lambda r: (-round(r[2]), r[1]))
        above = sorted((r for r in same if abs(r[1] - x) <= 45 and r[2] > y + 3 and not CODE.fullmatch(r[3])
                        and not NUM.fullmatch(r[3]) and not NOISE.fullmatch(r[3])), key=lambda r: r[2] - y)[:2]
        out.append(f"{p}\t{t}\t{x:.1f}\t{y:.1f}\t{rn[3] if rn else ''}\t{' / '.join(r[3] for r in labs)}\t{' / '.join(r[3] for r in above)}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}_rowmap.tsv").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(name, len(out) - 1, "codes")


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not argv:
        print(__doc__)
        return 2
    for n in argv:
        rowmap(re.sub(r"[^A-Za-z0-9_-]", "_", n))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

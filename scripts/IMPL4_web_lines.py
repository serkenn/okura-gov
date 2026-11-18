"""IMPL4 lines: scripts/IMPL4_web_pdftext.py が書いた文字と位置（<名前>_text.tsv）を、読める行に並べ直す。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ。ネットワークは使わない）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL4_web_lines.py h <名前> [<名前> ...]   横書き
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL4_web_lines.py v <名前> [<名前> ...]   縦書き

- 横書き：頁ごとに y を 3pt 単位で丸めて行にし、行は y の降順、行の中は x の昇順。
- 縦書き：頁ごとに x を 4pt 単位で丸めて列にし、列は x の降順（右から）、列の中は y の降順（上から）。
- 出力 scripts/results/IMPL4_web_lines/<名前>.txt（先頭に元の tsv の1行目〔ファイル・SHA-256〕を写す）
"""
import collections
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "scripts" / "results" / "IMPL4_web_pdftext"
OUT = ROOT / "scripts" / "results" / "IMPL4_web_lines"


def lines_of(name, mode):
    raw = (SRC / f"{name}_text.tsv").read_text(encoding="utf-8").splitlines()
    head, rows = raw[0], []
    for r in raw[2:]:
        f = r.split("\t")
        if len(f) >= 5:
            rows.append(f[:4] + ["\t".join(f[4:])])
        elif rows:  # 文字列に改行が入っていた行は、前の行の文字列につなぐ
            rows[-1][4] += r
    groups = collections.defaultdict(list)
    for p, x, y, _f, t in rows:
        p, x, y = int(p), float(x), float(y)
        if mode == "h":
            groups[(p, -round(y / 3))].append((x, t))
        else:
            groups[(p, -round(x / 4))].append((-y, t))
    out = [head, ""]
    last_page = None
    for k in sorted(groups):
        if k[0] != last_page:
            out.append(f"--- page {k[0]}")
            last_page = k[0]
        out.append("".join(t for _, t in sorted(groups[k])))
    return out


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ("h", "v"):
        print(__doc__)
        sys.exit(2)
    OUT.mkdir(parents=True, exist_ok=True)
    for name in sys.argv[2:]:
        (OUT / f"{name}.txt").write_text("\n".join(lines_of(name, sys.argv[1])) + "\n", encoding="utf-8")
        print("ok", name)


if __name__ == "__main__":
    main()

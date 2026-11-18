"""IMPL3 pdf_lines: scripts/IMPL3_pdftext.py が書いた <名前>_text.tsv（頁, x, y, フォント, 文字列）を、頁ごと・行ごと（y が同じもの）の
テキストにして、語で検索できるようにする。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ。ネットワークは使わない）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL3_pdf_lines.py

- 入力：scripts/results/IMPL3_pdftext/*_text.tsv
- 出力：scripts/results/IMPL3_pdf_lines/<名前>.txt（「頁<TAB>行のテキスト」。y の降順、同じ行は x の昇順で連結）
        scripts/results/IMPL3_pdf_lines/hits.txt（GREP の語を含む行と前後3行）
- 行の組み立ては y を整数に丸めて同じ行とみなすだけ（段組・ルビの並びは崩れることがある。読みは原本の PDF で確かめる）。
"""
import csv
import pathlib
import re
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
IN = ROOT / "scripts" / "results" / "IMPL3_pdftext"
OUT = ROOT / "scripts" / "results" / "IMPL3_pdf_lines"
GREP = {
    "kokugai_qa_01": r"所得の見積|合計所得金額の見積|国内源泉|国外.*所得|日本の所得税法|所得要件|所得金額.*判定",
    "kokugai_qa": r"所得の見積|合計所得金額の見積|国内源泉|国外.*所得|日本の所得税法|所得要件|所得金額.*判定",
    "haito_keisansho_ki": r"負債の利子|配当所得の金額|按分|あん分|区分",
    "haito_keisansho": r"負債の利子|配当所得の金額",
    "code_spec": r"検査数字|11|１１|剰余|除し|乗じ|都道府県",
    "furusato_report2019": r"指定|告示|特例控除|第三十七条の二|第三百十四条の七",
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    hits = []
    for f in sorted(IN.glob("*_text.tsv")):
        name = f.name[: -len("_text.tsv")]
        pages = defaultdict(lambda: defaultdict(list))
        with f.open(encoding="utf-8") as fh:
            for r in csv.reader(fh, delimiter="\t"):
                if len(r) < 5:
                    continue
                try:
                    p, x, y = int(r[0]), float(r[1]), float(r[2])
                except ValueError:
                    continue
                pages[p][round(y)].append((x, r[4]))
        lines = []
        for p in sorted(pages):
            for y in sorted(pages[p], reverse=True):
                lines.append(f"{p}\t" + "".join(t for _, t in sorted(pages[p][y])))
        (OUT / f"{name}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        pat = GREP.get(name)
        if pat:
            for i, ln in enumerate(lines):
                if re.search(pat, ln):
                    hits.append(f"## {name} 行{i}")
                    hits += lines[max(0, i - 3): i + 4]
                    hits.append("")
    (OUT / "hits.txt").write_text("\n".join(hits) + "\n", encoding="utf-8")
    print("done", OUT)


if __name__ == "__main__":
    main()

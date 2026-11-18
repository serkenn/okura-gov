"""IMPL_output: 国税庁「様式変更された申告書等の公表時期・受付開始時期」（ai-ocr.xlsx）を IMPL_output_xlsx.py で
書き出したセルの一覧（01_cells.tsv）から、関係税目ごとの公開時期・受付開始時期の件数と、指定した語を含む様式名の行を数える。

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_output_schedule_summary.py

- 入力：scripts/results/IMPL_output_xlsx/ksk2_youshiki_schedule/01_cells.tsv（先に IMPL_output_xlsx.py を実行しておく）
- 出力：scripts/results/IMPL_output_schedule_summary/summary.md
標準ライブラリのみ。
"""
import collections
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "scripts" / "results" / "IMPL_output_xlsx" / "ksk2_youshiki_schedule" / "01_cells.tsv"
OUT = ROOT / "scripts" / "results" / "IMPL_output_schedule_summary"
WORDS = ["令和８年分", "令和8年分", "令和７年分", "医療費控除", "収支内訳書", "社会保険料控除"]


def main():
    rows = collections.defaultdict(dict)
    for line in SRC.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        ref, _t, val = line.split("\t", 2)
        m = re.match(r"([A-Z]+)(\d+)$", ref)
        rows[int(m.group(2))][m.group(1)] = val
    header = rows.get(1, {}).get("D", "")
    data = {n: d for n, d in rows.items() if n > 3}
    cnt = collections.Counter((d.get("A", "").replace("\\n", ""), d.get("C", ""), d.get("D", "")) for d in data.values())
    lines = [f"# 様式の公表時期・受付開始時期の一覧の集計", "", f"- 入力：`{SRC.relative_to(ROOT).as_posix()}`", f"- 一覧の時点（D1）：{header}",
             f"- データ行（4行目以降）：{len(data)}", "", "## 関係税目等 × 様式公開時期 × 受付開始時期", "",
             "| 関係税目等 | 様式公開時期 | 受付開始時期 | 行数 |", "|---|---|---|---|"]
    for (a, c, d), v in sorted(cnt.items()):
        lines.append(f"| {a} | {c} | {d} | {v} |")
    for w in WORDS:
        hits = [(n, d) for n, d in sorted(data.items()) if w in d.get("B", "")]
        lines += ["", f"## 様式名称に「{w}」を含む行：{len(hits)}", ""]
        for n, d in hits[:40]:
            lines.append(f"- {n}: {d.get('A', '')} | {d.get('B', '')} | {d.get('C', '')} | {d.get('D', '')} | {d.get('E', '')}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:60]))


if __name__ == "__main__":
    main()

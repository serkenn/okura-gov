"""SAKUSEI: scripts/results/SAKUSEI_fetch/fetch_*.json をまとめ、取得したファイルの一覧（Markdown の表）を作る。

実行: python -I scripts/SAKUSEI_inventory.py
- 出力: scripts/results/SAKUSEI_inventory/inventory.md（URL、HTTP状態、サイズ、SHA-256、保存先）。本文は含めない。
- URL のクエリが 64 桁の16進数のときは、ファイルの SHA-256 と一致するかを「query=sha256」欄に書く。
標準ライブラリのみ。
"""
import json
import pathlib
import re
import sys
import urllib.parse

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rows, n = [], 0
    for f in sorted((ROOT / "scripts" / "results" / "SAKUSEI_fetch").glob("fetch_*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        for r in d["results"]:
            n += 1
            q = urllib.parse.urlsplit(r["url"]).query
            qs = ""
            if re.fullmatch(r"[0-9a-f]{64}", q or ""):
                qs = "一致" if q == r.get("sha256") else "不一致"
            rows.append(f"| {n} | {d['run']} | {r['url']} | {r.get('status')} | {r.get('bytes')} | "
                        f"`{r.get('sha256')}` | {qs} | `{r.get('saved')}` |")
    head = ("| # | 実行 | URL | HTTP | バイト | SHA-256 | query=sha256 | 保存先（.work/downloads/ 配下） |\n"
            "|---|---|---|---|---|---|---|---|")
    out = ROOT / "scripts" / "results" / "SAKUSEI_inventory"
    out.mkdir(parents=True, exist_ok=True)
    text = f"取得件数：{n}\n\n" + head + "\n" + "\n".join(rows) + "\n"
    (out / "inventory.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    sys.exit(main())

"""R2: OSV querybatch の応答と freeze.txt を突き合わせ、パッケージごとの脆弱性 ID・要約・修正版を表にする。

使い方: python -I scripts/R2_osv_summarize.py <OSV結果のディレクトリ>
  （ディレクトリには freeze.txt, osv_response.json, vulns/<ID>.json が必要。R2_openfisca_deps_osv.sh が作る）
出力: <ディレクトリ>/summary.md
"""
import json
import pathlib
import sys

d = pathlib.Path(sys.argv[1])
pkgs = [l.strip() for l in (d / "freeze.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
res = json.loads((d / "osv_response.json").read_text(encoding="utf-8"))["results"]
rows = ["| パッケージ==版 | 脆弱性ID（別名） | 要約 | 修正版 |", "|---|---|---|---|"]
for pkg, r in zip(pkgs, res):
    ids = [v["id"] for v in r.get("vulns", [])]
    if not ids:
        rows.append(f"| {pkg} | なし | | |")
        continue
    seen = set()
    for i in ids:
        v = json.loads((d / "vulns" / f"{i}.json").read_text(encoding="utf-8"))
        key = tuple(sorted({i, *v.get("aliases", [])}))
        if key in seen or any(set(key) & set(s) for s in seen):
            continue
        seen.add(key)
        fixed = sorted({e["fixed"] for a in v.get("affected", []) for rg in a.get("ranges", []) for e in rg.get("events", []) if "fixed" in e})
        rows.append(f"| {pkg} | {i}（{', '.join(x for x in v.get('aliases', []) if x != i)}） | {v.get('summary', '').replace('|', '/')} | {', '.join(fixed)} |")
(d / "summary.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
print("\n".join(rows))

"""IMPL_iryohi: scripts/IMPL_iryohi_egov.py が書き出した条文テキストについて、条ごと・版（asof）ごとに本文が同じかを比べる。

実行:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_iryohi_compare.py

- 入力：scripts/results/IMPL_iryohi_egov/<略称>_<asof>.txt（自分で書き出したテキスト。ダウンロードしたファイルではない）
- 条の本文は「## Num=<条番号>」の行から、次の「## 」または「# 附則」の行の直前まで（附則は含めない）。
- 出力：scripts/results/IMPL_iryohi_egov/compare_versions.json（条ごとに asof → SHA-256 の先頭16桁と、2025-12-31 版と同じか）
- 項ごとの差分（2025-12-31 版との比較）も compare_versions_diff.txt に書く。
標準ライブラリのみ。
"""
import difflib
import hashlib
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
D = ROOT / "scripts" / "results" / "IMPL_iryohi_egov"
ASOFS = ["2025-12-31", "2026-11-09", "2026-12-31", "2027-01-01"]
TARGETS = [("shotoku", "22"), ("shotoku", "73"), ("shotoku", "87"), ("shotoku", "120"),
           ("shotoku-rei", "207"), ("shotoku-rei", "262"),
           ("shotoku-ki", "40_3"), ("shotoku-ki", "47_2"),
           ("sochi", "41_17"), ("sochi-rei", "26_27_3"), ("sochi-ki", "19_10_2_2")]


def body(path, num):
    out, on = [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            on = line == f"## Num={num}"
            continue
        if line.startswith("# 附則"):
            on = False
        if on:
            out.append(line)
    return out


def main():
    res, diffs = {}, []
    for short, num in TARGETS:
        base = body(D / f"{short}_{ASOFS[0]}.txt", num)
        row = {}
        for a in ASOFS:
            b = body(D / f"{short}_{a}.txt", num)
            row[a] = {"sha256_16": hashlib.sha256("\n".join(b).encode("utf-8")).hexdigest()[:16],
                      "lines": len(b), "same_as_2025-12-31": b == base}
            if b != base:
                diffs.append(f"===== {short} Num={num} {ASOFS[0]} -> {a}")
                diffs += list(difflib.unified_diff(base, b, lineterm="", n=0))
        res[f"{short}:{num}"] = row
        print(f"{short}:{num}", {a: ("same" if row[a]["same_as_2025-12-31"] else "DIFF") for a in ASOFS})
    (D / "compare_versions.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    (D / "compare_versions_diff.txt").write_text("\n".join(diffs), encoding="utf-8")


if __name__ == "__main__":
    main()

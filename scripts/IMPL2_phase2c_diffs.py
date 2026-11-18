"""IMPL2 phase2c: scripts/results/IMPL2_phase2c_egov/ の条文のうち、令和7年分の版（asof 2025-12-31）と令和8年分の版（asof 2026-12-31）で本文が変わった条の差分を書く。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ。ネットワークは使わない）:
  C:/Users/user/.pyenv/pyenv-win/versions/3.11.9/python.exe -I -X utf8 scripts/IMPL2_phase2c_diffs.py <ダウンロード先>

- <ダウンロード先> は scripts/IMPL2_phase2c_egov.py fetch が作ったディレクトリ（JSON を読むだけ）。
- 条文の取り出しは IMPL2_phase2c_egov.py と同じ（import はしない）。
- 出力：scripts/results/IMPL2_phase2c_diffs/<略称>_<条>.diff.txt（変わった語の前後を文字単位の差分で示す）と summary.json
"""
import difflib
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "results" / "IMPL2_phase2c_diffs"
R7, R8 = "2025-12-31", "2026-12-31"
TARGET = {
    "shoho": ["24", "87", "92", "120", "121", "190", "195", "201", "203_3", "204"],
    "shorei": ["59", "120_2", "132", "134", "139", "204", "262_2"],
    "sochi": ["8_4", "9_3", "37_10", "37_11", "37_12_2", "41_4", "41_18", "41_18_2", "41_18_3"],
    "sochirei": ["4_2", "25_8", "25_9", "25_11_2", "26_27_4", "26_28", "26_28_2", "26_6"],
}


def inline(n):
    if isinstance(n, str):
        return n
    if n.get("tag") == "Rt":
        return ""
    return "".join(inline(c) for c in n.get("children", []))


def articles(path):
    d = json.loads(path.read_bytes())
    out = {}

    def walk(n, in_suppl=False):
        if not isinstance(n, dict):
            return
        tag = n.get("tag")
        if tag == "SupplProvision":
            return
        if tag == "Article" and not in_suppl:
            out[n["attr"].get("Num")] = inline(n)
            return
        for c in n.get("children", []):
            walk(c, in_suppl)
    walk(d["law_full_text"])
    return out


def ops(a, b):
    res = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag != "equal":
            res.append({"op": tag, "ctx": a[max(0, i1 - 25):i1], "old": a[i1:i2], "new": b[j1:j2]})
    return res


def main():
    dl = pathlib.Path(sys.argv[1])
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {}
    for short, nums in TARGET.items():
        a = articles(dl / f"{short}_{R7}.json")
        b = articles(dl / f"{short}_{R8}.json")
        for n in nums:
            if a.get(n) == b.get(n):
                summary[f"{short}_{n}"] = "同文"
                continue
            if n not in a or n not in b:
                summary[f"{short}_{n}"] = f"一方にない（R7:{n in a} R8:{n in b}）"
                continue
            o = ops(a[n], b[n])
            summary[f"{short}_{n}"] = o
            (OUT / f"{short}_{n}.diff.txt").write_text("\n".join(
                f"[{x['op']}] …{x['ctx']}\n  旧: {x['old']}\n  新: {x['new']}" for x in o), encoding="utf-8")
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, v in summary.items():
        if isinstance(v, str):
            print(k, v)
        else:
            print(k, len(v), "箇所")
            for x in v[:4]:
                print("   ", x["op"], "…" + x["ctx"][-15:], "| 旧:", x["old"][:90], "| 新:", x["new"][:90])


if __name__ == "__main__":
    main()

"""IMPL2 fudosan: 不動産所得の損失のうち損益通算できない部分（措法41の4 ほか）が、既存の docs/*/20261109_round2b_fudosan-* に記録されているかを確かめる。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ。ネットワークは使わない）:
  C:/Users/user/.pyenv/pyenv-win/versions/3.11.9/python.exe -I -X utf8 scripts/IMPL2_fudosan_existing.py

- 既存の文書の文字列と、今回取得した条文（scripts/results/IMPL2_phase2c_egov/fudosan/*.txt）を照合する。
- 出力：scripts/results/IMPL2_fudosan_existing/check.json
"""
import glob
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "results" / "IMPL2_fudosan_existing"
ASOFS = ["2025-12-31", "2026-11-11", "2026-12-31", "2027-01-01"]
NEEDLES_DOCS = ["措法41の4", "措令26の6", "措法41の4の2", "措法41の4の3", "別荘", "所法69②", "所令178"]
STATUTE_NEEDLES = {
    "sochi": ["第四十一条の四", "を取得するために要した負債の利子の額があるときは",
              "所得税法第六十九条第一項の規定その他の所得税に関する法令の規定の適用については、生じなかつたものとみなす"],
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"docs": {}, "statutes": {}, "summary": {}}
    files = sorted(glob.glob(str(ROOT / "docs" / "*" / "20261109_round2b_fudosan-*")))
    union = {k: [] for k in NEEDLES_DOCS}
    for f in files:
        t = pathlib.Path(f).read_text(encoding="utf-8")
        rel = str(pathlib.Path(f).relative_to(ROOT)).replace("\\", "/")
        res["docs"][rel] = {k: t.count(k) for k in NEEDLES_DOCS}
        for k in NEEDLES_DOCS:
            if k in t:
                union[k].append(rel)
    res["summary"]["found_in_existing_docs"] = {k: bool(v) for k, v in union.items()}
    for asof in ASOFS:
        p = ROOT / "scripts" / "results" / "IMPL2_phase2c_egov" / "fudosan" / f"sochi_{asof}.txt"
        if not p.exists():
            res["statutes"][asof] = "ファイルなし"
            continue
        t = p.read_text(encoding="utf-8").replace("\u3000", "")
        res["statutes"][asof] = {k: (k.replace("\u3000", "") in t) for k in STATUTE_NEEDLES["sochi"]}
    (OUT / "check.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res["summary"], ensure_ascii=False, indent=1))
    print(json.dumps(res["statutes"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

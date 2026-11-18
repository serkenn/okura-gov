"""IMPL3 gensen: 所得税法 別表第二（月額表）・別表第三（日額表）・別表第四（賞与の算出率の表）を、scripts/IMPL3_egov_fetch.py が取り出した
格子（appdx_*.json）から数値の表にし、令和7年分（asof 2025-12-31）、令和8年中（2026-01-01・2026-11-30）、令和8年分の末（2026-12-31）を比べる。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ。ネットワークは使わない）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL3_gensen_tables.py

- 入力：scripts/results/IMPL3_egov_fetch/gensen/appdx_shoho_<asof>_別表第{二,三,四}.json
- 出力：scripts/results/IMPL3_gensen_tables/
    getsugaku_<asof>.csv   月額表の金額の行（以上, 未満, 甲0人〜甲7人, 乙）。「以上」「未満」が数字の行だけ（式で書かれた行は formula_rows に）
    nichigaku_<asof>.csv   日額表の金額の行（以上, 未満, 甲0人〜甲7人, 乙, 丙）
    shoyo_<asof>.csv       賞与の算出率の表（率％, 甲0人以上・未満, …, 甲7人以上・未満, 乙以上・未満。千円）
    summary.json           行数、帯が連続しているか（前の行の未満＝次の行の以上）、税額が帯の順に減らないか、式の行、備考の1人あたりの控除額
- 全角数字・全角カンマを算用数字にする。「―」や空欄は null。
"""
import csv
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
IN = ROOT / "scripts" / "results" / "IMPL3_egov_fetch" / "gensen"
OUT = ROOT / "scripts" / "results" / "IMPL3_gensen_tables"
ASOFS = ["2025-12-31", "2026-01-01", "2026-11-30", "2026-12-31"]  # 令和8年中の切替わりを見るため 2026-01-01・2026-11-30 も
Z2H = str.maketrans("０１２３４５６７８９，．", "0123456789,.")


def num(s):
    s = s.translate(Z2H).replace(",", "").replace("円", "").replace("千", "").strip()
    return int(s) if re.fullmatch(r"\d+", s) else None


def load(asof, name):
    return json.loads((IN / f"appdx_shoho_{asof}_{name}.json").read_text(encoding="utf-8"))


def band_rows(obj, ncols):
    rows, formulas = [], []
    for st in obj["structs"]:
        for r in st["rows"]:
            if len(r) < 2:
                continue
            lo, hi = num(r[0]), num(r[1])
            if lo is not None and hi is not None and lo == hi:
                formulas.append(f"{lo}円ちょうどの税額: " + " | ".join(r[2:]))
            elif lo is not None and hi is not None:
                vals = [num(x) for x in r[2:2 + ncols]]
                rows.append([lo, hi] + vals)
            elif any("加算した金額" in x or "相当する金額" in x or "控除した金額" in x for x in r):
                t = " | ".join(dict.fromkeys(x for x in r if x))
                if t not in formulas:
                    formulas.append(t)
            elif lo is not None and r[0] == r[1]:
                # 「740,000円」のように 以上・未満 の欄が結合された行（その金額ちょうどの税額）
                formulas.append(f"{r[0]} の税額: " + " | ".join(r[2:]))
    return rows, formulas


def check(rows, taxcols):
    contiguous = all(a[1] == b[0] for a, b in zip(rows, rows[1:]))
    gaps = [(a[1], b[0]) for a, b in zip(rows, rows[1:]) if a[1] != b[0]]
    monotone = {}
    for i in taxcols:
        seq = [r[i] for r in rows if r[i] is not None]
        monotone[i] = all(x <= y for x, y in zip(seq, seq[1:]))
    return contiguous, gaps[:10], monotone


def all_remarks(obj):
    return list(obj.get("remarks", [])) + [x for st in obj["structs"] for x in st.get("remarks", [])]


def per_person(remarks, label):
    m = [re.findall(r"１人ごとに([０-９，]+)円", x) for x in remarks]
    return sorted({num(v) for g in m for v in g})


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {}
    for asof in ASOFS:
        s = {}
        g = load(asof, "別表第二")
        rows, formulas = band_rows(g, 9)
        with (OUT / f"getsugaku_{asof}.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["以上", "未満"] + [f"甲{i}人" for i in range(8)] + ["乙"])
            w.writerows(rows)
        cont, gaps, mono = check(rows, range(2, 11))
        s["別表第二"] = {"title": g["title"], "law_revision_id": g["law_revision_id"], "rows": len(rows),
                       "first": rows[0], "last": rows[-1], "contiguous": cont, "gaps": gaps, "monotone_by_col": mono,
                       "formula_rows": formulas, "per_person_yen_in_remarks": per_person(all_remarks(g), "月額")}
        d = load(asof, "別表第三")
        rows3, formulas3 = band_rows(d, 10)
        with (OUT / f"nichigaku_{asof}.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["以上", "未満"] + [f"甲{i}人" for i in range(8)] + ["乙", "丙"])
            w.writerows(rows3)
        cont3, gaps3, mono3 = check(rows3, range(2, 12))
        s["別表第三"] = {"title": d["title"], "rows": len(rows3), "first": rows3[0], "last": rows3[-1], "contiguous": cont3,
                       "gaps": gaps3, "monotone_by_col": mono3, "formula_rows": formulas3,
                       "per_person_yen_in_remarks": per_person(all_remarks(d), "日額")}
        b = load(asof, "別表第四")
        rate_rows = []
        for st in b["structs"]:
            for r in st["rows"]:
                rate = num(r[0].replace("．", ".").split(".")[0]) if r and re.fullmatch(r"[０-９．.]+", r[0].strip()) else None
                if rate is None or len(r) < 19:
                    continue
                rate_txt = r[0].translate(Z2H)
                rate_rows.append([rate_txt] + [x.translate(Z2H).replace(",", "") for x in r[1:19]])
        with (OUT / f"shoyo_{asof}.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            hdr = ["率％"]
            for i in range(7):
                hdr += [f"甲{i}人以上", f"甲{i}人未満"]
            hdr += ["甲7人以上_以上", "甲7人以上_未満", "乙以上", "乙未満"]
            w.writerow(hdr)
            w.writerows(rate_rows)
        s["別表第四"] = {"title": b["title"], "rows": len(rate_rows), "rates": [r[0] for r in rate_rows]}
        summary[asof] = s
    same = {}
    for x, y in zip(ASOFS, ASOFS[1:]):
        for k, stem in (("別表第二", "getsugaku"), ("別表第三", "nichigaku"), ("別表第四", "shoyo")):
            same[f"{k} {x}=={y}"] = (OUT / f"{stem}_{x}.csv").read_text(encoding="utf-8") == (OUT / f"{stem}_{y}.csv").read_text(encoding="utf-8")
    summary["same_between_versions"] = same
    a, c = summary[ASOFS[0]]["別表第二"], summary[ASOFS[-1]]["別表第二"]
    summary["compare"] = {"月額表の最初の行": [a["first"], c["first"]], "月額表の行数": [a["rows"], c["rows"]],
                          "1人あたり（月額）": [a["per_person_yen_in_remarks"], c["per_person_yen_in_remarks"]],
                          "1人あたり（日額）": [summary[ASOFS[0]]["別表第三"]["per_person_yen_in_remarks"],
                                           summary[ASOFS[-1]]["別表第三"]["per_person_yen_in_remarks"]]}
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    for asof in ASOFS:
        for k, v in summary[asof].items():
            print(asof, k, {x: v[x] for x in v if x not in ("formula_rows", "monotone_by_col")}, "monotone:", all(v.get("monotone_by_col", {0: True}).values()))
    print(summary["compare"])
    print(summary["same_between_versions"])


if __name__ == "__main__":
    main()

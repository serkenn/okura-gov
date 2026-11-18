"""IMPL_kyuyo: 機械抽出した別表第五（e-Gov）を、国税庁が公表した表（PDF）から人が書き写した値と照合する。

実行（ネットワーク不要。先に IMPL_kyuyo_fetch.py → IMPL_kyuyo_beppyo5.py を実行しておく）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_kyuyo_spotcheck.py

書き写しの元（2026-11-09 取得。scripts/results/IMPL_kyuyo_fetch_docs/fetch_log_nencho_tables.json）
- R7: 国税庁「令和7年分の年末調整等のための給与所得控除後の給与等の金額の表」
      https://www.nta.go.jp/publication/pamph/gensen/nencho2025/pdf/114.pdf  SHA-256 cc316009c20bad7709444d8fc3328ce35abacf3803dc6ecaddc40a352398eb89
      印刷頁 47（PDF 1 頁）と 54（PDF 8 頁）
- R8: 国税庁「令和8年分の年末調整等のための給与所得控除後の給与等の金額の表」
      https://www.nta.go.jp/publication/pamph/gensen/nencho2026/pdf/114.pdf  SHA-256 3d06c41b675161d51cc59c89d6d129ce8ea204b5ccc986f5b30b1072a12a032c
      印刷頁 47（PDF 1 頁）と 48（PDF 2 頁）。この表は措置法第29条の4第2項を織り込んだもの（国税庁 Q&A Q3−1）。
照合の相手
- R7：e-Gov の別表第五（asof 2025-12-31）を機械抽出した scripts/results/IMPL_kyuyo_beppyo5/beppyo5_2025-12-31.json
- R8：IMPL_kyuyo_thresholds.kyuyo_shotoku(2026, x)（e-Gov の別表第五 asof 2026-12-01 ＋ 措置法第29条の4第2項）と、
      220万円以上は e-Gov の別表第五（asof 2026-12-01）そのもの
出力：scripts/results/IMPL_kyuyo_spotcheck/spotcheck.json / spotcheck.md
"""
import importlib.util
import json
import pathlib
import sys

sys.dont_write_bytecode = True  # 読み込む IMPL_kyuyo_thresholds.py の .pyc を scripts/__pycache__ に残さない
ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "results" / "IMPL_kyuyo_spotcheck"

# IMPL_kyuyo_thresholds.py の関数を使う（同じリポジトリの自分のスクリプト。sys.path を変えずにファイルから読み込む）
spec = importlib.util.spec_from_file_location("thr", ROOT / "scripts" / "IMPL_kyuyo_thresholds.py")
thr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(thr)

# (以上, 未満, 給与所得控除後の給与等の金額 または ("minus", c) / ("rate_minus", pct, c), 頁)
NTA_R7 = [
    (0, 651_000, 0, "p47"),
    (651_000, 1_900_000, ("minus", 650_000), "p47"),
    (1_900_000, 1_904_000, 1_250_000, "p47"),
    (1_936_000, 1_940_000, 1_275_200, "p47"),
    (2_000_000, 2_004_000, 1_320_000, "p47"),
    (2_056_000, 2_060_000, 1_359_200, "p47"),
    (2_060_000, 2_064_000, 1_362_000, "p47"),
    (2_296_000, 2_300_000, 1_527_200, "p47"),
    (2_456_000, 2_460_000, 1_639_200, "p47"),
    (6_060_000, 6_064_000, 4_408_000, "p54"),
    (6_256_000, 6_260_000, 4_564_800, "p54"),
    (6_456_000, 6_460_000, 4_724_800, "p54"),
    (6_596_000, 6_600_000, 4_836_800, "p54"),
    (6_600_000, 8_500_000, ("rate_minus", 90, 1_100_000), "p54"),
    (8_500_000, 20_000_000, ("minus", 1_950_000), "p54"),
]
NTA_R8 = [
    (0, 741_000, 0, "p47"),
    (741_000, 2_191_000, ("minus", 740_000), "p47"),
    (2_191_000, 2_193_000, 1_451_000, "p47"),
    (2_193_000, 2_196_000, 1_453_000, "p47"),
    (2_196_000, 2_200_000, 1_456_000, "p47"),
    (2_200_000, 2_204_000, 1_460_000, "p47"),
    (2_204_000, 2_208_000, 1_462_800, "p47"),
    (2_380_000, 2_384_000, 1_586_000, "p47"),
    (2_384_000, 2_388_000, 1_588_800, "p47"),
    (2_580_000, 2_584_000, 1_726_000, "p47"),
    (2_584_000, 2_588_000, 1_728_800, "p48"),
    (2_780_000, 2_784_000, 1_866_000, "p48"),
    (2_984_000, 2_988_000, 2_008_800, "p48"),
    (3_180_000, 3_184_000, 2_146_000, "p48"),
]


def expected(v, x):
    if isinstance(v, int):
        return v
    if v[0] == "minus":
        return x - v[1]
    return x * v[1] // 100 - v[2]


def run(rows, f_ours, label):
    out = []
    for lo, up, v, page in rows:
        xs = sorted({lo, lo + 1, (lo + up) // 2, up - 1})
        for x in xs:
            e, o = expected(v, x), f_ours(x)
            out.append({"set": label, "page": page, "band": [lo, up], "x": x, "nta": e, "ours": o, "match": e == o})
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    t7 = thr.table("2025-12-31")
    t8 = thr.table("2026-12-01")
    res = []
    res += run(NTA_R7, lambda x: thr.kyuyo_shotoku(2025, x), "R7: NTA表 vs e-Gov別表第五(2025-12-31)")
    res += run(NTA_R8, lambda x: thr.kyuyo_shotoku(2026, x), "R8: NTA表 vs e-Gov別表第五(2026-12-01)+措置法29の4②")
    res += run([r for r in NTA_R8 if r[0] >= 2_200_000], t8.value, "R8: NTA表 vs e-Gov別表第五(2026-12-01) 単独（220万円以上）")
    # e-Gov の R8 の別表第五そのもの（措置法を織り込まない）の 220万円未満の値も、参考として並べる
    ref = [{"x": x, "egov_beppyo5_r8_only": t8.value(x), "with_sochi": thr.kyuyo_shotoku(2026, x)} for x in
           [690_999, 691_000, 740_999, 741_000, 1_360_000, 2_025_999, 2_026_000, 2_190_999, 2_199_999]]
    # 措置法第29条の4第2項の範囲 [691,000, 2,200,000) を1円刻みで走査し、別表第五（asof 2026-12-01）のみの値との差を調べる
    sweep = {"range": [691_000, 2_200_000], "n": 0, "min_diff": None, "max_diff": None, "n_sochi_greater": 0, "n_equal": 0, "diff_hist": {}}
    for x in range(691_000, 2_200_000):
        d = t8.value(x) - thr.sochi_29_4_2(x)
        sweep["n"] += 1
        sweep["min_diff"] = d if sweep["min_diff"] is None else min(sweep["min_diff"], d)
        sweep["max_diff"] = d if sweep["max_diff"] is None else max(sweep["max_diff"], d)
        sweep["n_sochi_greater"] += d < 0
        sweep["n_equal"] += d == 0
        k = "50000" if d == 50_000 else ("<50000" if d < 50_000 else ">50000")
        sweep["diff_hist"][k] = sweep["diff_hist"].get(k, 0) + 1
    sweep["at_2200000"] = {"beppyo5": t8.value(2_200_000), "kyuyo_shotoku": thr.kyuyo_shotoku(2026, 2_200_000)}
    sweep["below_691000_both_zero"] = all(t8.value(x) == 0 and thr.kyuyo_shotoku(2026, x) == 0 for x in range(0, 691_000, 1))
    summary = {"n": len(res), "n_match": sum(r["match"] for r in res), "mismatches": [r for r in res if not r["match"]], "sochi_vs_beppyo5_sweep": sweep}
    (OUT / "spotcheck.json").write_text(json.dumps({"summary": summary, "rows": res, "r8_beppyo5_only_reference": ref}, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# 別表第五の抽出と国税庁の表の照合（IMPL_kyuyo_spotcheck.py）", "",
          f"照合した点：{summary['n']}、一致：{summary['n_match']}、不一致：{len(summary['mismatches'])}", "",
          f"措置法第29条の4第2項と別表第五（asof 2026-12-01）の差（別表第五 − 措置法、[691,000, 2,200,000) を1円刻み）：{sweep}", "",
          "| 照合 | 頁 | 区分 | x | 国税庁の表 | 本調査 | 一致 |", "|---|---|---|---|---|---|---|"]
    for r in res:
        md.append(f"| {r['set']} | {r['page']} | [{r['band'][0]:,}, {r['band'][1]:,}) | {r['x']:,} | {r['nta']:,} | {r['ours']:,} | {'一致' if r['match'] else '不一致'} |")
    md += ["", "## 参考：e-Gov の別表第五（asof 2026-12-01）だけで求めた値と、措置法第29条の4第2項を適用した値", "",
           "| x | 別表第五のみ | 措置法適用後 |", "|---|---|---|"] + [f"| {r['x']:,} | {r['egov_beppyo5_r8_only']:,} | {r['with_sochi']:,} |" for r in ref]
    (OUT / "spotcheck.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md[:3]))


if __name__ == "__main__":
    main()

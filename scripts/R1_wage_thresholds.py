"""R1: 条文から読み取った基準額で「収入が給与だけの場合の給与収入の境目」を計算し、国税庁資料の値と照合する。

実行:  python -I scripts/R1_wage_thresholds.py
ネットワークは使わない。標準ライブラリのみ。

パラメータの出典（すべて e-Gov 法令API v2 で取得した条文。scripts/results/R1_egov_articles/ を参照）
- 給与所得控除: 所得税法第28条第3項（令和6年分: asof=2024-12-31、令和7年分: asof=2025-12-31、令和8年分: asof=2026-12-01）
  令和8年分・令和9年分は租税特別措置法第29条の4第1項・第2項（asof=2026-12-01）が優先する。
- 所得要件: 所得税法第2条第1項第32号（勤労学生）・第34号（扶養親族）、第84条の2（特定親族）
- 基礎控除: 所得税法第86条第1項、租税特別措置法第41条の16の2第1項
注意: 給与収入660万円未満は所得税法第28条第4項により別表第五（1,000円〜4,000円刻みの表）で給与所得を求める。
      このスクリプトは別表第五を再現していない（第28条第3項の式で計算する）。境目が別表の刻みに当たる場合は数千円ずれうる。
      令和8年分・令和9年分の 69万1千円〜219万1千円未満は措置法第29条の4第2項が式（収入−74万円）を直接定めているので、ずれない。
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAN = 10_000


def kyuyo_shotoku(year, rev):
    """給与所得の金額（円）。year は西暦の年分。"""
    if year in (2026, 2027):  # 措置法29条の4（令和8年・令和9年）
        if rev < 741_000:
            # 69.1万未満は第1項（控除額74万円。収入が74万円未満なら収入金額）で0、69.1万〜74.1万未満は第2項第1号で「ない」
            return 0
        if rev < 2_191_000:
            return rev - 740_000
        if rev < 2_193_000:
            return 1_451_000
        if rev < 2_196_000:
            return 1_453_000
        if rev < 2_200_000:
            return 1_456_000
        # 220万円以上は所得税法28条3項（令和8年分以後の式）
    if year >= 2026:
        if rev <= 3_600_000:
            ded = max(80_000 + rev * 30 // 100, 690_000)
        elif rev <= 6_600_000:
            ded = 1_160_000 + (rev - 3_600_000) * 20 // 100
        elif rev <= 8_500_000:
            ded = 1_760_000 + (rev - 6_600_000) * 10 // 100
        else:
            ded = 1_950_000
    elif year == 2025:
        if rev <= 1_900_000:
            ded = 650_000
        elif rev <= 3_600_000:
            ded = 650_000 + (rev - 1_900_000) * 30 // 100
        elif rev <= 6_600_000:
            ded = 1_160_000 + (rev - 3_600_000) * 20 // 100
        elif rev <= 8_500_000:
            ded = 1_760_000 + (rev - 6_600_000) * 10 // 100
        else:
            ded = 1_950_000
    else:  # 2024（令和6年分）
        if rev <= 1_800_000:
            ded = max(rev * 40 // 100 - 100_000, 550_000)
        elif rev <= 3_600_000:
            ded = 620_000 + (rev - 1_800_000) * 30 // 100
        elif rev <= 6_600_000:
            ded = 1_160_000 + (rev - 3_600_000) * 20 // 100
        elif rev <= 8_500_000:
            ded = 1_760_000 + (rev - 6_600_000) * 10 // 100
        else:
            ded = 1_950_000
    return max(0, rev - ded)


def max_revenue(year, income_limit):
    """給与所得 <= income_limit となる最大の給与収入（1円単位、二分探索）。"""
    lo, hi = 0, 30_000_000
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if kyuyo_shotoku(year, mid) <= income_limit:
            lo = mid
        else:
            hi = mid - 1
    return lo


# 年分ごとの所得要件（合計所得金額、円）と基礎控除（合計所得132万円以下の人の額）
PARAMS = {
    2024: {"label": "令和6年分", "fuyo": 48 * MAN, "kinro": 75 * MAN, "tokutei_full": None, "tokutei_max": None, "kiso_low": 48 * MAN},
    2025: {"label": "令和7年分", "fuyo": 58 * MAN, "kinro": 85 * MAN, "tokutei_full": 85 * MAN, "tokutei_max": 123 * MAN, "kiso_low": (58 + 37) * MAN},
    2026: {"label": "令和8年分", "fuyo": 62 * MAN, "kinro": 89 * MAN, "tokutei_full": 85 * MAN, "tokutei_max": 123 * MAN, "kiso_low": (62 + 42) * MAN},
}
# 国税庁資料に書かれた「収入が給与だけの場合の収入金額」（照合用）
EXPECTED = {
    2025: {"src": "https://www.nta.go.jp/publication/pamph/gensen/2026kaisei.pdf p.2 改正前欄 / https://www.nta.go.jp/users/gensen/2025kiso/index.htm",
           "fuyo": 123 * MAN, "kinro": 150 * MAN, "tokutei_max": 188 * MAN},
    2026: {"src": "https://www.nta.go.jp/publication/pamph/gensen/2026kaisei.pdf p.1-2 改正後欄",
           "fuyo": 136 * MAN, "kinro": 163 * MAN, "tokutei_full": 159 * MAN, "tokutei_max": 197 * MAN, "kiso_low_note": "合計所得132万円以下の欄は給与収入206万円以下"},
}


def main():
    out = ROOT / "scripts" / "results" / "R1_wage_thresholds"
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for y, p in PARAMS.items():
        r = {"year": y, "label": p["label"]}
        for k in ("fuyo", "kinro", "tokutei_full", "tokutei_max"):
            r[k + "_income_limit"] = p[k]
            r[k + "_max_wage"] = max_revenue(y, p[k]) if p[k] is not None else None
        # 本人の所得税がかからない給与収入の上限（給与所得 <= 基礎控除。他の所得控除がない場合）
        r["self_no_tax_max_wage"] = max_revenue(y, p["kiso_low"])
        r["self_basic_deduction_low"] = p["kiso_low"]
        exp = EXPECTED.get(y)
        if exp:
            r["expected_src"] = exp["src"]
            r["check"] = {k: {"computed": r[k + "_max_wage"], "expected": exp[k], "match": r[k + "_max_wage"] == exp[k]}
                          for k in ("fuyo", "kinro", "tokutei_full", "tokutei_max") if k in exp}
        rows.append(r)
    (out / "thresholds.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["| 年分 | 扶養親族（所得→給与収入） | 勤労学生 | 特定親族の満額63万円の上限 | 特定親族の上限 | 本人の所得税0の上限（基礎控除のみ） | 国税庁資料との照合 |", "|---|---|---|---|---|---|---|"]
    f = lambda a, b: "—" if a is None else f"{a // MAN}万 → {b:,}円"
    for r in rows:
        chk = "; ".join(f"{k}:{'一致' if v['match'] else '不一致'}" for k, v in (r.get("check") or {}).items()) or "（照合対象なし）"
        md.append(f"| {r['label']} | {f(r['fuyo_income_limit'], r['fuyo_max_wage'])} | {f(r['kinro_income_limit'], r['kinro_max_wage'])} | "
                  f"{f(r['tokutei_full_income_limit'], r['tokutei_full_max_wage'])} | {f(r['tokutei_max_income_limit'], r['tokutei_max_max_wage'])} | "
                  f"{f(r['self_basic_deduction_low'], r['self_no_tax_max_wage'])} | {chk} |")
    (out / "thresholds.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()

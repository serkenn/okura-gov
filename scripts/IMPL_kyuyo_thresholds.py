"""IMPL_kyuyo: 別表第五（実際の表）と措置法第29条の4第2項で給与所得を求め、所得要件の境目を給与収入に換算して公開資料の値と照合する。

実行（ネットワーク不要。先に IMPL_kyuyo_fetch.py → IMPL_kyuyo_beppyo5.py を実行しておく）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_kyuyo_thresholds.py

出力：scripts/results/IMPL_kyuyo_thresholds/
  - thresholds.json / thresholds.md：境目の一覧（表による値、式だけで求めた値、公開資料の値、一致・不一致）
  - kyuyo_shotoku_samples.csv：境目の前後の給与収入に対する給与所得（テストケースの元）
  - nencho_vs_kakutei_r8.md：令和8年分で、年末調整に旧の別表第五が使われる場合と確定申告の値の違い（例）

給与所得の求め方（所得税。年分ごと）
- 収入 6,600,000 円以上：所得税法第28条第2項・第3項の式。1円未満は切り捨てる（別表第五の備考と同じ扱い。第28条自体に端数処理の定めはない）。
- 令和8年分・令和9年分で収入 691,000 円以上 2,200,000 円未満：租税特別措置法第29条の4第2項（asof 2026-12-01 の条文）。
- それ以外で 6,600,000 円未満：所得税法第28条第4項により別表第五（年分に対応する版の表）。
    令和6年分：asof 2024-12-31 の表／令和7年分：asof 2025-12-31 の表／令和8年分・令和9年分：asof 2026-12-01 の表
住民税（年度）：年度 N の所得割は前年（N−1 年）の所得で計算し（地方税法第292条第1項第7号）、給与所得は所得税の計算の例による
  （地方税法第313条第2項）とみなして、所得税の N−1 年分と同じ関数を使う（この扱いは仮説。docs/hypotheses の該当文書を参照）。
"""
import bisect
import csv
import json
import math
import pathlib
from fractions import Fraction

ROOT = pathlib.Path(__file__).resolve().parent.parent
TB = ROOT / "scripts" / "results" / "IMPL_kyuyo_beppyo5"
OUT = ROOT / "scripts" / "results" / "IMPL_kyuyo_thresholds"
MAN = 10_000

TABLE_ASOF = {2024: "2024-12-31", 2025: "2025-12-31", 2026: "2026-12-01", 2027: "2026-12-01",
              2028: "2026-12-01"}  # 2028 は仮定（令和10年分。2026-11-09 時点の条文のまま改正がない場合。措置法第29条の4は適用されない）
OLD_TABLE_FOR = {2025: "2024-12-31", 2026: "2025-12-31"}  # 年末調整で「なお従前の例による」場合の表


class Table:
    def __init__(self, asof):
        d = json.loads((TB / f"beppyo5_{asof}.json").read_text(encoding="utf-8"))
        self.asof = asof
        self.meta = d["meta"]
        self.recs = [r for r in d["records"] if r["kind"] != "point"]
        self.lowers = [r["lower"] for r in self.recs]

    def value(self, x):
        i = bisect.bisect_right(self.lowers, x) - 1
        r = self.recs[i]
        assert r["lower"] <= x < r["upper"], (x, r)
        if r["kind"] == "fixed":
            return r["value"]
        if r["kind"] == "minus":
            return x - r["c"]
        if r["kind"] == "rate_minus":
            return x * r["rate_pct"] // 100 - r["c"]
        raise ValueError(r)

    def boundaries(self):
        return [r["lower"] for r in self.recs] + [self.recs[-1]["upper"]]


def ded_exact(year, x):
    """所得税法第28条第3項の給与所得控除額（Fraction）。年分に適用される版の式。"""
    x = Fraction(x)
    if year <= 2024:
        if x <= 1_800_000:
            return max(x * Fraction(40, 100) - 100_000, Fraction(550_000))
        if x <= 3_600_000:
            return 620_000 + (x - 1_800_000) * Fraction(30, 100)
    elif year == 2025:
        if x <= 1_900_000:
            return Fraction(650_000)
        if x <= 3_600_000:
            return 650_000 + (x - 1_900_000) * Fraction(30, 100)
    else:
        if x <= 3_600_000:
            return max(80_000 + x * Fraction(30, 100), Fraction(690_000))
    if x <= 6_600_000:
        return 1_160_000 + (x - 3_600_000) * Fraction(20, 100)
    if x <= 8_500_000:
        return 1_760_000 + (x - 6_600_000) * Fraction(10, 100)
    return Fraction(1_950_000)


def formula_only(year, x):
    """別表第五を使わず第28条第2項・第3項の式だけで求めた値（R1_wage_thresholds.py と同じ考え方。1円未満切捨て）。
    令和8・9年分の措置法第29条の4第1項（74万円）は含めるが、第2項の表は使わない。"""
    if year in (2026, 2027) and x <= 2_200_000:
        d = Fraction(min(740_000, x))
    else:
        d = ded_exact(year, x)
    return max(0, math.floor(Fraction(x) - d))


def sochi_29_4_2(x):
    """租税特別措置法第29条の4第2項（令和8年・令和9年）。適用範囲外なら None。"""
    if 691_000 <= x < 741_000:
        return 0
    if 741_000 <= x < 2_191_000:
        return x - 740_000
    if 2_191_000 <= x < 2_193_000:
        return 1_451_000
    if 2_193_000 <= x < 2_196_000:
        return 1_453_000
    if 2_196_000 <= x < 2_200_000:
        return 1_456_000
    return None


TABLES = {}


def table(asof):
    if asof not in TABLES:
        TABLES[asof] = Table(asof)
    return TABLES[asof]


def kyuyo_shotoku(year, x, old_table=False):
    """給与所得の金額（所得税、確定申告の計算）。old_table=True は年末調整で旧表が使われる場合の参考計算。"""
    if x >= 6_600_000:
        return math.floor(Fraction(x) - ded_exact(year, x))
    if year in (2026, 2027) and not old_table:
        v = sochi_29_4_2(x)
        if v is not None:
            return v
    asof = OLD_TABLE_FOR[year] if old_table else TABLE_ASOF[year]
    return table(asof).value(x)


def check_monotone(year):
    """境目の前後で値が下がらないこと（区分内は定数か増加の一次式なので、区分の境目で調べれば足りる）。"""
    pts = set()
    for b in table(TABLE_ASOF[year]).boundaries():
        pts |= {b - 1, b}
    pts |= {690_999, 691_000, 740_999, 741_000, 2_190_999, 2_191_000, 2_192_999, 2_193_000, 2_195_999, 2_196_000, 2_199_999, 2_200_000,
            6_599_999, 6_600_000, 8_499_999, 8_500_000}
    pts = sorted(p for p in pts if 0 <= p <= 30_000_000)
    bad = []
    prev = None
    for p in pts:
        v = kyuyo_shotoku(year, p)
        if prev is not None and v < prev[1]:
            bad.append({"x_prev": prev[0], "v_prev": prev[1], "x": p, "v": v})
        prev = (p, v)
    return bad


def max_wage(fn, limit, hi=40_000_000):
    """fn(x) <= limit となる最大の x（fn は非減少）。"""
    lo = 0
    if fn(0) > limit:
        return None
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if fn(mid) <= limit:
            lo = mid
        else:
            hi = mid - 1
    return lo


# 所得要件など（合計所得金額、円）。出典は docs/public-sources/20261109_R1-laws_income-tax.md・_local-tax.md と本調査の public-sources。
TOKUTEI_EDGES_IT = [850_000, 900_000, 950_000, 1_000_000, 1_050_000, 1_100_000, 1_150_000, 1_200_000, 1_230_000]
TOKUTEI_EDGES_JUMIN = [950_000, 1_000_000, 1_050_000, 1_100_000, 1_150_000, 1_200_000, 1_230_000]
KISO_EDGES = [1_320_000, 3_360_000, 4_890_000, 6_550_000, 23_500_000]

ITEMS_IT = {  # 所得税（年分）
    2024: {"扶養親族": 480_000, "勤労学生": 750_000},
    2025: {"扶養親族": 580_000, "勤労学生": 850_000, "源泉控除対象親族(特定親族)": 1_000_000, "配偶者特別控除の上限": 1_330_000,
           **{f"特定親族 {e // MAN}万": e for e in TOKUTEI_EDGES_IT}, **{f"基礎控除 {e // MAN}万": e for e in KISO_EDGES}},
    2026: {"扶養親族": 620_000, "勤労学生": 890_000, "配偶者特別控除の上限": 1_330_000,
           **{f"特定親族 {e // MAN}万": e for e in TOKUTEI_EDGES_IT}, **{f"基礎控除 {e // MAN}万": e for e in KISO_EDGES}},
    2027: {"扶養親族": 620_000, "勤労学生": 890_000, **{f"特定親族 {e // MAN}万": e for e in TOKUTEI_EDGES_IT}},
    # 仮定のシナリオ：令和10年分で条文が変わらない場合（措置法第29条の4 は「令和八年又は令和九年」なので適用されない）
    2028: {"(仮定)扶養親族": 620_000, "(仮定)勤労学生": 890_000, **{f"(仮定)特定親族 {e // MAN}万": e for e in TOKUTEI_EDGES_IT}},
}
ITEMS_JUMIN = {  # 住民税（年度 → 前年の所得の年）
    "令和8年度": (2025, {"扶養親族": 580_000, "勤労学生": 850_000, "未成年者等の非課税": 1_350_000,
                       **{f"特定親族 {e // MAN}万": e for e in TOKUTEI_EDGES_JUMIN},
                       **{f"均等割等非課税(仙台市の表) {e // MAN}万": e for e in [450_000, 1_010_000, 1_360_000, 1_710_000, 2_060_000, 2_410_000]}}),
    "令和9年度": (2026, {"扶養親族": 620_000, "勤労学生": 890_000, "未成年者等の非課税": 1_350_000,
                       **{f"特定親族 {e // MAN}万": e for e in TOKUTEI_EDGES_JUMIN},
                       **{f"均等割等非課税(仙台市の表) {e // MAN}万": e for e in [450_000, 1_010_000, 1_360_000, 1_710_000, 2_060_000, 2_410_000]}}),
    "令和10年度": (2027, {"扶養親族": 620_000, "未成年者等の非課税": 1_350_000}),
}

# 公開資料に書かれた給与収入の値（「以下」の上端）。出典は docs/public-sources/20261109_impl-prep_kyuyo-sources.md。
NTA_2025QA = "国税庁 令和7年度税制改正（基礎控除の見直し等関係）Q&A（令和7年5月30日）0025005-051.pdf"
NTA_2026KAISEI = "国税庁 源泉所得税の改正のあらまし（令和8年4月）2026kaisei.pdf"
SENDAI = "仙台市 令和9年度（令和8年分）から適用される個人市県民税の税制改正等について（r8.html）"
SOUMU = "総務省 令和8年度地方税制改正(案)について（令和7年12月）001047636.pdf"
EXPECTED_IT = {
    2025: {"扶養親族": (1_230_000, NTA_2026KAISEI + " p.2 改正前"), "勤労学生": (1_500_000, NTA_2026KAISEI + " p.2 改正前"),
           "配偶者特別控除の上限": (2_015_999, NTA_2026KAISEI + " p.2 改正前"),
           "源泉控除対象親族(特定親族)": (1_650_000, NTA_2025QA + " p.7（印刷頁）"),
           **{f"特定親族 {e // MAN}万": (w, NTA_2025QA + " p.5（印刷頁）") for e, w in zip(TOKUTEI_EDGES_IT,
              [1_500_000, 1_550_000, 1_600_000, 1_650_000, 1_700_000, 1_750_000, 1_800_000, 1_850_000, 1_880_000])},
           **{f"基礎控除 {e // MAN}万": (w, NTA_2025QA + " p.3（印刷頁）") for e, w in zip(KISO_EDGES,
              [2_003_999, 4_751_999, 6_655_556, 8_500_000, 25_450_000])}},
    2026: {"扶養親族": (1_360_000, NTA_2026KAISEI + " p.2"), "勤労学生": (1_630_000, NTA_2026KAISEI + " p.2"),
           "配偶者特別控除の上限": (2_070_000, NTA_2026KAISEI + " p.2"),
           **{f"特定親族 {e // MAN}万": (w, NTA_2026KAISEI + " p.2（参考）の表") for e, w in zip(TOKUTEI_EDGES_IT,
              [1_590_000, 1_640_000, 1_690_000, 1_740_000, 1_790_000, 1_840_000, 1_890_000, 1_940_000, 1_970_000])},
           **{f"基礎控除 {e // MAN}万": (w, NTA_2026KAISEI + " p.1") for e, w in zip(KISO_EDGES,
              [2_060_000, 4_751_999, 6_655_556, 8_500_000, 25_450_000])}},
}
EXPECTED_JUMIN = {
    "令和8年度": {"扶養親族": (1_230_000, SENDAI), "勤労学生": (1_500_000, SENDAI),
                **{f"均等割等非課税(仙台市の表) {e // MAN}万": (w, SENDAI) for e, w in zip(
                    [450_000, 1_010_000, 1_360_000, 1_710_000, 2_060_000, 2_410_000],
                    [1_100_000, 1_660_000, 2_059_000, 2_559_999, 3_059_999, 3_559_999])}},
    "令和9年度": {"扶養親族": (1_360_000, SENDAI), "勤労学生": (1_630_000, SENDAI),
                **{f"均等割等非課税(仙台市の表) {e // MAN}万": (w, SENDAI if e != 450_000 else SENDAI + " / " + SOUMU) for e, w in zip(
                    [450_000, 1_010_000, 1_360_000, 1_710_000, 2_060_000, 2_410_000],
                    [1_190_000, 1_750_000, 2_059_000, 2_559_999, 3_059_999, 3_559_999])}},
}


def row(label, year, limit, expected):
    fn = lambda x: kyuyo_shotoku(year, x)
    w = max_wage(fn, limit)
    wf = max_wage(lambda x: formula_only(year, x), limit)
    r = {"label": label, "income_year": year, "income_limit": limit, "max_wage": w, "max_wage_formula_only": wf,
         "diff_table_vs_formula": None if (w is None or wf is None) else w - wf,
         "kyuyo_at_max": fn(w) if w is not None else None, "kyuyo_at_max_plus_1": fn(w + 1) if w is not None else None}
    if expected:
        r["expected"], r["expected_src"] = expected
        r["match"] = (w == expected[0])
    return r


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"tables": {y: {"asof": a, "law_revision_id": table(a).meta["law_revision_id"], "source_sha256": table(a).meta["source_sha256"]}
                      for y, a in TABLE_ASOF.items()},
           "monotone_violations": {y: check_monotone(y) for y in TABLE_ASOF}, "income_tax": [], "jumin": []}
    for y, items in ITEMS_IT.items():
        for label, lim in items.items():
            res["income_tax"].append(row(label, y, lim, EXPECTED_IT.get(y, {}).get(label)))
    for nendo, (y, items) in ITEMS_JUMIN.items():
        for label, lim in items.items():
            r = row(label, y, lim, EXPECTED_JUMIN.get(nendo, {}).get(label))
            r["nendo"] = nendo
            res["jumin"].append(r)
    (OUT / "thresholds.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")

    def fmt(v):
        return "—" if v is None else f"{v:,}"
    md = ["# 給与収入の境目（IMPL_kyuyo_thresholds.py の出力）", "",
          "max_wage＝「給与所得 ≤ 所得要件」となる最大の給与収入（別表第五と措置法第29条の4第2項による）。",
          "formula_only＝別表第五を使わず第28条第3項の式だけで求めた値（R1 の方法）。", "",
          f"表の単調性の検査（境目で値が下がる箇所）：{ {y: len(v) for y, v in res['monotone_violations'].items()} }", "",
          "## 所得税（年分）", "", "| 年分 | 項目 | 所得要件 | max_wage | formula_only | 差 | 公開資料 | 一致 | 出典 |", "|---|---|---|---|---|---|---|---|---|"]
    for r in res["income_tax"]:
        md.append(f"| {r['income_year']} | {r['label']} | {fmt(r['income_limit'])} | {fmt(r['max_wage'])} | {fmt(r['max_wage_formula_only'])} | "
                  f"{fmt(r['diff_table_vs_formula'])} | {fmt(r.get('expected'))} | {'' if 'match' not in r else ('一致' if r['match'] else '不一致')} | {r.get('expected_src', '')} |")
    md += ["", "## 住民税（年度。給与所得は前年の所得税の計算の例による、という仮説の下で計算）", "",
           "| 年度 | 所得の年 | 項目 | 前年の合計所得金額の要件 | max_wage | formula_only | 差 | 公開資料 | 一致 | 出典 |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in res["jumin"]:
        md.append(f"| {r['nendo']} | {r['income_year']} | {r['label']} | {fmt(r['income_limit'])} | {fmt(r['max_wage'])} | {fmt(r['max_wage_formula_only'])} | "
                  f"{fmt(r['diff_table_vs_formula'])} | {fmt(r.get('expected'))} | {'' if 'match' not in r else ('一致' if r['match'] else '不一致')} | {r.get('expected_src', '')} |")
    (OUT / "thresholds.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    # テストケースの元：境目の前後
    with open(OUT / "kyuyo_shotoku_samples.csv", "w", encoding="utf-8", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["income_year", "wage", "kyuyo_shotoku", "formula_only", "note"])
        pts = {2024: [550_999, 551_000, 1_618_999, 1_619_000, 1_623_999, 1_624_000, 1_627_999, 1_628_000],
               2025: [650_000, 650_999, 651_000, 1_899_999, 1_900_000, 1_903_999, 1_904_000, 2_003_999, 2_004_000, 2_015_999, 2_016_000],
               2026: [690_999, 691_000, 740_999, 741_000, 1_360_000, 1_360_001, 2_190_999, 2_191_000, 2_199_999, 2_200_000, 2_203_999, 2_204_000,
                      2_025_999, 2_026_000, 2_035_999, 2_036_000, 4_751_999, 4_752_000, 6_599_999, 6_600_000, 6_655_556, 6_655_557],
               2027: [690_999, 691_000, 1_360_000, 2_199_999, 2_200_000]}
        for r in res["income_tax"] + res["jumin"]:
            if r["max_wage"] is not None:
                pts.setdefault(r["income_year"], []).extend([r["max_wage"], r["max_wage"] + 1])
        for y in sorted(pts):
            for x in sorted(set(pts[y])):
                w.writerow([y, x, kyuyo_shotoku(y, x), formula_only(y, x), ""])

    # 令和8年分：年末調整で旧表（asof 2025-12-31）が使われる場合と、確定申告（新表＋措置法第29条の4第2項）の違いの例
    ex = ["# 令和8年分：最後の給与の支払が令和8年12月1日前の人の年末調整（旧の別表第五）と確定申告の給与所得の違い（例）", "",
          "前提（条文の読み）：令和8年法律第12号附則第13条第2項により、最後の支払が12月1日前の給与等には旧の別表第五（asof 2025-12-31）。",
          "同法附則第36条第1項により、措置法第29条の4第4項（年末調整での特例）はその人には適用されない。確定申告では新しい規定による（国税庁 Q&A Q1−3・Q7−1）。", "",
          "| 給与収入 | 年末調整（旧表） | 確定申告（新表＋措置法） | 差 |", "|---|---|---|---|"]
    for x in [650_000, 651_000, 680_000, 690_999, 700_000, 1_000_000, 1_230_000, 1_360_000, 1_500_000, 1_900_000, 2_000_000, 2_036_000, 2_200_000, 3_000_000]:
        a, b = kyuyo_shotoku(2026, x, old_table=True), kyuyo_shotoku(2026, x)
        ex.append(f"| {x:,} | {a:,} | {b:,} | {a - b:,} |")
    (OUT / "nencho_vs_kakutei_r8.md").write_text("\n".join(ex) + "\n", encoding="utf-8")
    print((OUT / "thresholds.md").read_text(encoding="utf-8"))
    print((OUT / "nencho_vs_kakutei_r8.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()

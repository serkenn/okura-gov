"""IMPL zeigaku: 推測の文書（docs/inferences/20261109_impl-prep_zeigaku-examples.md）の手計算を検算する。ネットワークは使わない。

実行（pyenv のシムは使わない）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_zeigaku_example_calc.py
- 結果は scripts/results/IMPL_zeigaku_example_calc/examples.json と examples.md に書く。
- 値はすべて docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md と docs/public-sources/20261109_R1-laws_income-tax.md に
  書いた条文の値を、ここに手で写したもの（テストの期待値の下書き。判定コアの実装ではない）。
- 金額は整数（円）で扱い、復興特別所得税の 2.1% だけは Fraction で端数を残してから切り捨てる。
"""
import datetime
import json
import pathlib
from fractions import Fraction

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "results" / "IMPL_zeigaku_example_calc"

# 所得税法第89条第1項の表（令和6・7・8年分で同じ文言。docs/public-sources §3）
BRACKETS = [(1_950_000, Fraction(5, 100)), (3_300_000, Fraction(10, 100)), (6_950_000, Fraction(20, 100)),
            (9_000_000, Fraction(23, 100)), (18_000_000, Fraction(33, 100)), (40_000_000, Fraction(40, 100)),
            (None, Fraction(45, 100))]


def kyuyo_shotoku(year, income):
    """給与所得。令和7年分は所得税法別表第五の最初の2行、令和8年分は措法第29条の4第2項。範囲外は扱わない。"""
    if year == 2025:
        if income < 651_000:
            return 0
        if income < 1_900_000:
            return income - 650_000
    if year == 2026:
        if 691_000 <= income < 741_000:
            return 0
        if 741_000 <= income < 2_191_000:
            return income - 740_000
    raise ValueError("この検算では扱わない範囲")


def kiso_kojo(year, gokei):
    """基礎控除（合計所得金額 489万円以下・132万円以下の範囲だけ）。"""
    if year == 2025 and gokei <= 1_320_000:
        return 580_000 + 370_000
    if year == 2026 and gokei <= 4_890_000:
        return 620_000 + 420_000
    raise ValueError("この検算では扱わない範囲")


def kinro_gakusei(year, gokei, non_labor, is_student):
    limit = {2025: 850_000, 2026: 890_000}[year]
    return 270_000 if (is_student and gokei <= limit and non_labor <= 100_000) else 0


def tax89(kazei):
    tax, lower = Fraction(0), 0
    for upper, rate in BRACKETS:
        top = kazei if upper is None else min(kazei, upper)
        if top > lower:
            tax += (top - lower) * rate
        if upper is None or kazei <= upper:
            break
        lower = upper
    return tax


def run(case):
    y = case["year"]
    k = kyuyo_shotoku(y, case["kyuyo_income"])
    zatsu = case.get("zatsu_income", 0) - case.get("zatsu_expense", 0)
    sotoku = k + zatsu                      # 総所得金額（所法22②一。損益通算・繰越控除なし）
    gokei = sotoku                          # 合計所得金額（所法2①三十イ(2)）
    non_labor = case.get("non_labor_income", 0)
    kojo = {"shakai_hoken": case.get("shakai_hoken_paid_by_self", 0),
            "kinro_gakusei": kinro_gakusei(y, gokei, non_labor, case["is_student_art1"]),
            "kiso": kiso_kojo(y, gokei)}
    kojo_total = sum(kojo.values())
    zan = max(0, sotoku - kojo_total)       # 所法87②・89②（赤字は0）
    kazei = zan // 1000 * 1000              # 通則法118①（千円未満切捨て）
    t = tax89(kazei)
    assert t.denominator == 1, "課税総所得金額が千円単位なので所得税額は整数になるはず"
    kijun = int(t)                          # 基準所得税額（税額控除なし。復興法10一）
    fukko_exact = Fraction(kijun) * Fraction(21, 1000)   # 復興法13（令和7・8年分は2.1%）
    fukko_tebiki = int(fukko_exact)          # 手引き p.27「1円未満の端数…切り捨て」
    gensen = case["gensen_total"]            # 源泉徴収税額（所得税及び復興特別所得税の合計。架空の入力）
    yono = case.get("yono", 0)
    res = {}
    for label, total in (("tebiki_1yen_floor_first", Fraction(kijun + fukko_tebiki)), ("strict_no_floor_first", kijun + fukko_exact)):
        diff = total - gensen - yono
        if diff >= 0:
            res[label] = {"kind": "納付", "amount": int(diff) // 100 * 100}   # 復興法24②・通則法119①（合計で百円未満切捨て）
        else:
            res[label] = {"kind": "還付", "amount": int(-diff)}              # 通則法120①（一円未満切捨て）
    # 確定申告の義務（所法120①）：税率を当てた税額 > 配当控除(0) で、控除しきれない源泉徴収税額・予納税額がないとき
    shotoku_part_of_gensen = case.get("gensen_shotoku_part", gensen)  # 所得税の部分（分からなければ合計で近似）
    duty_120 = kijun > 0 and not (shotoku_part_of_gensen > kijun) and not (yono > kijun - shotoku_part_of_gensen)
    other_income = sotoku - k               # 給与所得及び退職所得以外の所得金額（所法121①一。通達121-6 の特例は考えない）
    exempt_121_1 = (case["kyuyo_payers"] == 1 and case["kyuyo_all_withheld"] and case["kyuyo_income"] <= 20_000_000
                    and other_income <= 200_000)
    duty = duty_120 and not exempt_121_1
    refund_possible = res["tebiki_1yen_floor_first"]["kind"] == "還付" and res["tebiki_1yen_floor_first"]["amount"] > 0
    return {"case": case["id"], "year": y, "kyuyo_shotoku": k, "zatsu_shotoku": zatsu, "sotoku": sotoku, "gokei": gokei,
            "kojo": kojo, "kojo_total": kojo_total, "kazei_sotoku": kazei, "shotokuzei": kijun,
            "fukko_exact": str(fukko_exact), "fukko_tebiki": fukko_tebiki, "settlement": res,
            "duty_120": duty_120, "exempt_121_1": exempt_121_1, "duty": duty, "refund_possible": refund_possible}


CASES = [
    {"id": "Z1", "year": 2026, "kyuyo_income": 1_400_000, "kyuyo_payers": 1, "kyuyo_all_withheld": True,
     "is_student_art1": True, "gensen_total": 40_000},
    {"id": "Z1-R7", "year": 2025, "kyuyo_income": 1_400_000, "kyuyo_payers": 1, "kyuyo_all_withheld": True,
     "is_student_art1": True, "gensen_total": 40_000},
    {"id": "Z1-nokinro", "year": 2026, "kyuyo_income": 1_400_000, "kyuyo_payers": 1, "kyuyo_all_withheld": True,
     "is_student_art1": False, "gensen_total": 40_000},
    {"id": "Z2", "year": 2026, "kyuyo_income": 1_400_000, "zatsu_income": 600_000, "zatsu_expense": 100_000,
     "kyuyo_payers": 1, "kyuyo_all_withheld": True, "is_student_art1": True, "gensen_total": 40_000 + 61_260},
    {"id": "Z3", "year": 2026, "kyuyo_income": 1_400_000, "zatsu_income": 600_000, "zatsu_expense": 100_000,
     "kyuyo_payers": 1, "kyuyo_all_withheld": True, "is_student_art1": True, "gensen_total": 0},
    {"id": "Z3-small", "year": 2026, "kyuyo_income": 1_400_000, "zatsu_income": 300_000, "zatsu_expense": 100_000,
     "kyuyo_payers": 1, "kyuyo_all_withheld": True, "is_student_art1": True, "gensen_total": 0},
    {"id": "Z5-R7", "year": 2025, "kyuyo_income": 1_400_000, "zatsu_income": 421_000, "zatsu_expense": 100_000,
     "kyuyo_payers": 1, "kyuyo_all_withheld": True, "is_student_art1": True, "gensen_total": 40_000 + 61_260},
]


def property_kinro_no_effect():
    """性質：令和7・8年分で、給与だけ（1万円刻み）なら、勤労学生控除の有無で課税総所得金額が変わらない。"""
    out = []
    for year, (lo, hi) in ((2025, (651_000, 1_899_000)), (2026, (741_000, 2_190_000))):
        bad = []
        for inc in range(lo, hi + 1, 1000):
            k = kyuyo_shotoku(year, inc)
            gokei = k
            if gokei > 1_320_000:
                continue
            a = max(0, k - kiso_kojo(year, gokei) - kinro_gakusei(year, gokei, 0, True)) // 1000
            b = max(0, k - kiso_kojo(year, gokei)) // 1000
            if a != b:
                bad.append(inc)
        out.append({"year": year, "range": [lo, hi], "step": 1000, "counterexamples": bad[:5], "n_counterexamples": len(bad)})
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    results = [run(c) for c in CASES]
    dates = {d: datetime.date.fromisoformat(d).strftime("%A") for d in ("2026-03-15", "2026-03-16", "2027-03-15", "2027-02-16")}
    data = {"cases": CASES, "results": results, "property_kinro_no_effect": property_kinro_no_effect(), "weekdays": dates}
    (OUT / "examples.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["| case | 年 | 給与所得 | 雑所得 | 合計所得 | 控除計 | 課税総所得 | 所得税 | 復興(厳密) | 復興(手引き) | 精算(手引き) | 精算(厳密) | 120条 | 121①一 | 申告義務 |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        s1, s2 = r["settlement"]["tebiki_1yen_floor_first"], r["settlement"]["strict_no_floor_first"]
        lines.append(f"| {r['case']} | {r['year']} | {r['kyuyo_shotoku']} | {r['zatsu_shotoku']} | {r['gokei']} | {r['kojo_total']} | {r['kazei_sotoku']} | "
                     f"{r['shotokuzei']} | {r['fukko_exact']} | {r['fukko_tebiki']} | {s1['kind']} {s1['amount']} | {s2['kind']} {s2['amount']} | "
                     f"{r['duty_120']} | {r['exempt_121_1']} | {r['duty']} |")
    lines += ["", "性質（勤労学生控除の有無で課税総所得金額が変わらないか）：", json.dumps(data["property_kinro_no_effect"], ensure_ascii=False),
              "", "曜日：", json.dumps(dates, ensure_ascii=False)]
    (OUT / "examples.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

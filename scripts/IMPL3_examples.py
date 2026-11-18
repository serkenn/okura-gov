"""IMPL3 examples: impl-research3 の仮説（docs/hypotheses/20261111_impl-research3_all-model.md）から、推測の例（テストケースの期待値）を計算する。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ。ネットワークは使わない）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL3_examples.py

- 表の値は scripts/results/IMPL3_genka_tables/beppyo*_2026-12-31.csv と scripts/results/IMPL3_gensen_tables/getsugaku_*.csv から読む。
- 金額はすべて架空。1円未満は Fraction のまま出し、丸めない（端数の処理は既存の決定に従うので、ここでは決めない）。
- 出力：scripts/results/IMPL3_examples/examples.json
"""
import csv
import json
import pathlib
from fractions import Fraction as F

ROOT = pathlib.Path(__file__).resolve().parent.parent
GK = ROOT / "scripts" / "results" / "IMPL3_genka_tables"
GS = ROOT / "scripts" / "results" / "IMPL3_gensen_tables"
OUT = ROOT / "scripts" / "results" / "IMPL3_examples"


def table(name):
    with (GK / name).open(encoding="utf-8") as f:
        r = csv.reader(f)
        next(r)
        return {int(row[0]): [F(x) if x else None for x in row[1:]] for row in r}


def kyu_teigaku(cost, n, years, residual_ratio=F(1, 10)):
    """旧定額法：(取得価額−残存価額)×率。累積が95%に達したら止め、翌年から (取得価額×5%−1)/5 を5年（所令134①一イ・②）。"""
    rate = table("beppyo7_2026-12-31.csv")[n][0]
    cap95 = cost * F(95, 100)
    acc, out, after = F(0), [], None
    for y in range(1, years + 1):
        if after is not None:
            d = min(after, cost - 1 - acc)
        else:
            d = (cost - cost * residual_ratio) * rate
            if acc + d > cap95:
                d = cap95 - acc
        d = max(d, F(0))
        acc += d
        out.append({"年": y, "償却費": str(d), "累積": str(acc)})
        if after is None and acc >= cap95:
            after = (cost - cap95 - 1) / 5
    return {"率": str(rate), "schedule": out}


def kyu_teiritsu(cost, n, years):
    rate = table("beppyo7_2026-12-31.csv")[n][1]
    cap95 = cost * F(95, 100)
    acc, out = F(0), []
    for y in range(1, years + 1):
        d = (cost - acc) * rate
        if acc + d > cap95:
            d = cap95 - acc
        acc += d
        out.append({"年": y, "償却費": str(d), "累積": str(acc)})
    return {"率": str(rate), "schedule": out}


def teiritsu(cost, n, years, table_name="beppyo10_2026-12-31.csv"):
    rate, kaitei, hosho = table(table_name)[n]
    guarantee = cost * hosho
    acc, out, revised_base = F(0), [], None
    for y in range(1, years + 1):
        book = cost - acc
        if revised_base is None:
            d = book * rate
            if d < guarantee:
                revised_base = book
        if revised_base is not None:
            d = revised_base * kaitei
        d = min(d, cost - 1 - acc)
        acc += d
        out.append({"年": y, "償却費": str(d), "累積": str(acc), "改定": revised_base is not None})
    return {"率": str(rate), "改定償却率": str(kaitei), "保証率": str(hosho), "償却保証額": str(guarantee), "schedule": out}


def getsugaku(asof, amount, col):
    with (GS / f"getsugaku_{asof}.csv").open(encoding="utf-8") as f:
        r = csv.reader(f)
        hdr = next(r)
        i = hdr.index(col)
        for row in r:
            if int(row[0]) <= amount < int(row[1]):
                return int(row[i])
    return None


def furusato_special_5_5(donation, sep_kinds, designated_city=False, shotokuwari=None):
    """地法附則5の5②：割合の最も低いもの × (寄附−2,000) × 3/5（指定都市 4/5）、所得割の額の20%が上限。"""
    rates = {"土地等事業": F(50, 100), "短期譲渡": F(60, 100), "上場配当": F(75, 100), "長期譲渡": F(75, 100),
             "一般株式譲渡": F(75, 100), "上場株式譲渡": F(75, 100), "先物": F(75, 100)}
    r = min(rates[k] for k in sep_kinds)
    v = (donation - 2000) * r * (F(4, 5) if designated_city else F(3, 5))
    if shotokuwari is not None:
        v = min(v, shotokuwari * F(20, 100))
    return {"割合": str(r), "特例控除額": str(v)}


def tokutei_setai(byodo_total, households, tokutei, keizoku):
    """国保令29の7②八：按分の分母 = 世帯数 − 特定世帯×1/2 − 特定継続世帯×1/4。"""
    denom = households - F(tokutei, 2) - F(keizoku, 4)
    base = F(byodo_total) / denom
    return {"分母": str(denom), "一般の世帯": str(base), "特定世帯": str(base / 2), "特定継続世帯": str(base * F(3, 4))}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ex = {
        "G-1 旧定額法 取得価額1,000,000 耐用年数10 15年": kyu_teigaku(F(1_000_000), 10, 17),
        "G-2 旧定率法 取得価額1,000,000 耐用年数5 3年": kyu_teiritsu(F(1_000_000), 5, 3),
        "G-3 定率法(200%) 取得価額1,000,000 耐用年数5 5年": teiritsu(F(1_000_000), 5, 5),
        "G-4 定率法(250%) 取得価額1,000,000 耐用年数5 5年": teiritsu(F(1_000_000), 5, 5, "beppyo9_2026-12-31.csv"),
        "S-1 月額表 R8 106,000 甲0人": getsugaku("2026-12-31", 106_000, "甲0人"),
        "S-2 月額表 R7 88,500 甲0人": getsugaku("2025-12-31", 88_500, "甲0人"),
        "S-3 月額表 R8 300,000 甲2人": getsugaku("2026-12-31", 300_000, "甲2人"),
        "S-4 月額表 R7 300,000 甲2人": getsugaku("2025-12-31", 300_000, "甲2人"),
        "S-5 月額表 R8 300,000 乙": getsugaku("2026-12-31", 300_000, "乙"),
        "J-1 附則5の5② 寄附50,000 上場配当のみ 一般市 所得割100,000": furusato_special_5_5(F(50_000), ["上場配当"], False, F(100_000)),
        "J-2 附則5の5② 寄附50,000 短期譲渡と上場配当 指定都市 上限なし": furusato_special_5_5(F(50_000), ["短期譲渡", "上場配当"], True, None),
        "K-1 特定世帯 平等割総額10,000,000 世帯1,000 特定世帯20 特定継続世帯8": tokutei_setai(10_000_000, 1000, 20, 8),
    }
    (OUT / "examples.json").write_text(json.dumps(ex, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, v in ex.items():
        if isinstance(v, dict) and "schedule" in v:
            print(k, {x: v[x] for x in v if x != "schedule"}, [(s["年"], s["償却費"]) for s in v["schedule"]])
        else:
            print(k, v)


if __name__ == "__main__":
    main()

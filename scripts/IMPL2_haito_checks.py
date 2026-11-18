"""IMPL2 haito: 配当控除（所法92①）の条文どおりの式と、タックスアンサー No.1250 のパターン1〜4、手引き（3-4_28 の計算欄）の式が一致することを確かめる。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ。ネットワークは使わない）:
  C:/Users/user/.pyenv/pyenv-win/versions/3.11.9/python.exe -I -X utf8 scripts/IMPL2_haito_checks.py

- 値は架空の整数。出力：scripts/results/IMPL2_haito_checks/checks.json
- 課税総所得金額（措法8の4③四等の読替え後の「課税総所得金額及び…の合計額」）を T、
  剰余金の配当等の配当所得の金額を A、証券投資信託の収益の分配に係る配当所得の金額を B（特定外貨建等の率の読替えは対象外）とする。
"""
import itertools
import json
import pathlib
from fractions import Fraction as F

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "results" / "IMPL2_haito_checks"
M = 10_000_000


def statute(t, a, b):
    """所法92①一〜三（A,B,T は整数の円）"""
    a, b, t = F(a), F(b), F(t)
    if t <= M:
        return a * F(10, 100) + b * F(5, 100)
    if t - b <= M:
        over = t - M
        return a * F(10, 100) + min(over, b) * F(25, 1000) + (b - min(over, b)) * F(5, 100)
    x = t - (M + b)
    return min(x, a) * F(5, 100) + (a - min(x, a)) * F(10, 100) + b * F(25, 1000)


def ta1250(t, a, b):
    """タックスアンサー No.1250 のパターン1〜4"""
    a, b, t = F(a), F(b), F(t)
    if t <= M:
        return a * F(10, 100) + b * F(5, 100)
    if t - b <= M:
        over = t - M
        return a * F(10, 100) + min(over, b) * F(25, 1000) + (b - min(over, b)) * F(5, 100)
    if t - a - b > M:
        return a * F(5, 100) + b * F(25, 1000)
    x = t - M - b
    return x * F(5, 100) + (a - x) * F(10, 100) + b * F(25, 1000)


def tebiki_form(t, a):
    """手引き 3-4_28 の計算欄（証券投資信託の収益の分配がない場合の様式）：B=課税所得、C=B-1000万(赤字0)、D=A-C(赤字0)、E=D×0.1、F=(A-D)×0.05、G=E+F"""
    a, t = F(a), F(t)
    c = max(t - M, F(0))
    d = max(a - c, F(0))
    return d * F(1, 10) + (a - d) * F(5, 100)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ts = [0, 5_000_000, 10_000_000, 10_000_001, 10_500_000, 11_000_000, 15_000_000, 20_000_000, 50_000_000]
    As = [0, 1, 300_000, 1_000_000, 5_000_000, 20_000_000]
    Bs = [0, 1, 200_000, 600_000, 1_500_000]
    cases = list(itertools.product(ts, As, Bs))
    mm = [c for c in cases if statute(*c) != ta1250(*c)]
    cases2 = list(itertools.product(ts, As))
    mm2 = [c for c in cases2 if statute(c[0], c[1], 0) != tebiki_form(*c)]
    frac = [c for c in cases if statute(*c).denominator != 1]
    res = {"statute_vs_ta1250": {"cases": len(cases), "mismatch": len(mm), "mismatch_examples": mm[:5]},
           "statute_vs_tebiki_form_B0": {"cases": len(cases2), "mismatch": len(mm2), "mismatch_examples": mm2[:5]},
           "cases_with_fraction_of_yen": len(frac), "fraction_examples": [[*c, str(statute(*c))] for c in frac[:5]],
           "fraction_note": "配当控除の式は百分率を掛けるだけ。A・B に端数の出る値では円未満が残る。条文に配当控除額の端数の定めはない（docs/public-sources/20261111_impl-research_haito-laws-and-nta.md）。"}
    res["examples"] = {
        "T=800万 A=30万 B=0": str(statute(8_000_000, 300_000, 0)),
        "T=1050万 A=30万 B=0": str(statute(10_500_000, 300_000, 0)),
        "T=1050万 A=0 B=60万": str(statute(10_500_000, 0, 600_000)),
        "T=1500万 A=30万 B=20万": str(statute(15_000_000, 300_000, 200_000)),
    }
    (OUT / "checks.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

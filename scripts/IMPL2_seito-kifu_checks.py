"""IMPL2 seito-kifu: 政党等寄附金特別控除等（措法41の18②・41の18の2②・41の18の3①）の条文どおりの式と、国税庁の計算明細書の欄の式が一致することを確かめる。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:/Users/user/.pyenv/pyenv-win/versions/3.11.9/python.exe -I -X utf8 scripts/IMPL2_seito-kifu_checks.py

- 条文の式：措法41の18②（政党等）、41の18の2②（認定NPO法人等）、41の18の3①（公益社団法人等）。docs/public-sources/20261111_impl-research_seito-kifu-laws-and-nta.md
- 様式の式：国税庁「政党等寄附金特別控除額の計算明細書」(06.pdf)、「認定NPO法人等寄附金特別控除額の計算明細書」(09-1.pdf)、「公益社団法人等寄附金特別控除額の計算明細書」(09-4.pdf) の欄。
- 値はすべて架空の整数。出力：scripts/results/IMPL2_seito-kifu_checks/checks.json
- ネットワークは使わない。
"""
import itertools
import json
import pathlib
from fractions import Fraction as F

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "results" / "IMPL2_seito-kifu_checks"


def floor100(x):
    return int(F(x) // 100) * 100


def base_amount(donation, others, income):
    """条文の「当該合計額…を超える場合には、当該百分の四十に相当する金額から…控除した残額」（残額が負なら0として扱う）"""
    cap40 = F(income) * F(40, 100)
    base = F(donation) if donation + others <= cap40 else cap40 - others
    return max(F(0), base)


def statute_seito(p, s, income, tax):
    """措法41の18②。p=政党等寄附金、s=特定寄附金等の金額（政党等寄附金以外の寄附金の額）、income=総所得金額等の合計、tax=その年分の所得税の額"""
    base = base_amount(p, s, income)
    deductible = max(2000 - s, 0)
    if base <= deductible:
        return 0
    credit = floor100((base - deductible) * F(30, 100))
    limit = floor100(F(tax) * F(25, 100))
    return min(credit, limit)


def form_seito(p, s, income, tax):
    """政党等寄附金特別控除額の計算明細書 ①〜⑫"""
    c5 = F(income) * F(40, 100)
    c6 = max(c5 - s, F(0))
    c7 = min(F(p), c6)
    c8 = max(2000 - s, 0)
    c9 = 0 if c7 - c8 <= 0 else floor100((c7 - c8) * F(30, 100))
    c11 = floor100(F(tax) * F(25, 100))
    return min(c9, c11)


def statute_koeki(k, others, income, tax):
    """措法41の18の3①。k=税額控除対象寄附金の額、others=所得控除対象寄附金の額（特定寄附金等－k）"""
    base = base_amount(k, others, income)
    deductible = max(2000 - others, 0)
    if base <= deductible:
        return 0
    credit = floor100((base - deductible) * F(40, 100))
    limit = floor100(F(tax) * F(25, 100))
    return min(credit, limit)


def form_koeki(k, others, income, tax):
    c5 = F(income) * F(40, 100)
    c6 = max(c5 - others, F(0))
    c7 = min(F(k), c6)
    c8 = max(2000 - others, 0)
    c9 = 0 if c7 - c8 <= 0 else floor100((c7 - c8) * F(40, 100))
    c11 = floor100(F(tax) * F(25, 100))
    return min(c9, c11)


def statute_npo(n, s, income, tax, koeki_credit):
    """措法41の18の2②。s=特定寄附金等の金額、koeki_credit=41の18の3①の控除額（次条第一項の規定により控除する金額）"""
    base = base_amount(n, s, income)
    deductible = max(2000 - s, 0)
    if base <= deductible:
        return 0
    credit = floor100((base - deductible) * F(40, 100))
    limit = floor100(max(F(tax) * F(25, 100) - koeki_credit, F(0)))
    return min(credit, limit)


def form_npo(n, s, income, tax, koeki_credit):
    c5 = F(income) * F(40, 100)
    c6 = max(c5 - s, F(0))
    c7 = min(F(n), c6)
    c8 = max(2000 - s, 0)
    c9 = 0 if c7 - c8 <= 0 else floor100((c7 - c8) * F(40, 100))
    c11 = floor100(F(tax) * F(25, 100))
    c12 = max(c11 - koeki_credit, 0)
    return min(c9, c12)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ps = [0, 1500, 2000, 2001, 30000, 150000, 2000000]
    ss = [0, 500, 1999, 2000, 2500, 100000, 900000]
    incomes = [0, 1000, 500000, 3000000, 8000000]
    taxes = [0, 2400, 4000, 9999, 100000, 430000, 2000000]
    koekis = [0, 100, 500, 12300, 100000]
    n = 0
    mismatch = {"seito": 0, "koeki": 0, "npo": 0}
    for p, s, inc, t in itertools.product(ps, ss, incomes, taxes):
        n += 1
        if statute_seito(p, s, inc, t) != form_seito(p, s, inc, t):
            mismatch["seito"] += 1
        if statute_koeki(p, s, inc, t) != form_koeki(p, s, inc, t):
            mismatch["koeki"] += 1
    m = 0
    for x, s, inc, t, k in itertools.product(ps, ss, incomes, taxes, koekis):
        m += 1
        if statute_npo(x, s, inc, t, k) != form_npo(x, s, inc, t, k):
            mismatch["npo"] += 1
    examples = {
        "E1 政党等 3万円・他の寄附なし・所得300万・算出税額10万 → (30000-2000)*30%=8400": statute_seito(30000, 0, 3000000, 100000),
        "E2 政党等 3万円・他の寄附1000円（2千円の残りは1000円）→ (30000-1000)*30%=8700": statute_seito(30000, 1000, 3000000, 100000),
        "E3 25%の限度にかかる：政党等 200万・所得 1000万・算出税額 10万 → 限度 25000": statute_seito(2000000, 0, 10000000, 100000),
        "E4 40%の限度にかかる：政党等 200万・所得 100万・税額 100万 → (400000-2000)*30%=119400": statute_seito(2000000, 0, 1000000, 1000000),
        "E5 2千円以下：政党等 2000円 → 0": statute_seito(2000, 0, 3000000, 100000),
        "E6 NPO 10万・公益控除 12300・算出税額 10万 → min(39200, 25000-12300=12700)": statute_npo(100000, 0, 3000000, 100000, 12300),
    }
    result = {
        "cases_seito_koeki": n, "cases_npo": m, "mismatch": mismatch,
        "npo_25pct_rounding_note": "statute_npo は 25%相当額－公益控除 を百円未満切捨て、form_npo は 25%相当額を百円未満切捨て後に公益控除を引く。公益控除額は百円の倍数なので一致する。",
        "examples": examples,
    }
    (OUT / "checks.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

"""R2B invoice: 消費税等の経理方式（税込経理・税抜経理）と、納付税額・還付税額の計上時期が、所得税の事業所得等の金額に
どう効くかを、架空の数値で計算して確かめる。ネットワークには接続しない。

前提（出典は docs/public-sources/20261109_round2b_invoice-laws-and-nta.md）
- 税込経理：納付すべき消費税等は、納税申告書を提出した日の属する年の必要経費。ただし、申告期限が来ていない申告書に
  記載すべき額を未払金に計上したときは、その計上した年の必要経費にしてよい（直所3-8 の 7）。還付は同じ形で総収入金額（同 8）。
- 税抜経理：課税期間の終了の時の（仮受消費税等の合計 − 仮払消費税等の合計）と、納付すべき消費税等の額との差額を、
  その課税期間を含む年の総収入金額又は必要経費に算入する（同 6）。
- 免税事業者は税込経理（同 5）。
- 消費税等の額そのもの（納付すべき額）は、このスクリプトでは計算しない。外部で計算した値（架空の値）として与える（D20）。

検査すること
- C1：固定資産・棚卸資産のない取引だけなら、税抜経理の所得 ＝ 税込経理で未払金に計上した場合の所得（年ごと）。
      仮払消費税等として区分した額（例：経過措置の 80％・70％ か、全額か）を変えても、所得は変わらない。
- C2：税込経理で申告年に計上（原則）すると、納付額の分だけ所得が翌年にずれる。複数年の合計は未払金計上と一致する
      （最後の年の分の納付が期間内に入る場合）。
- C3：還付の場合も同じ形（符号が逆）。
- C4：減価償却資産を税抜経理で取得すると、取得価額が税抜になり、所得の年の配分が税込経理と変わる（合計は同じ）。

実行（リポジトリのルートで）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_invoice_examples.py
結果：scripts/results/R2B_invoice_examples/results.json と results.md
"""
import json
import pathlib
import random

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "results" / "R2B_invoice_examples"


def income_zeikomi(years, flows, payments, accrue):
    """税込経理。flows[y] = (税込の売上, 税込の経費)。payments = [(課税期間の年, 申告書を出した年, 納付(+)/還付(-)の額)]。
    accrue=True なら課税期間の年に未払金・未収入金として計上（直所3-8 の 7・8 のただし書）、False なら申告書を出した年（本文）。"""
    res = {}
    for y in years:
        sales, cost = flows.get(y, (0, 0))
        tax = 0
        for period_y, filed_y, amt in payments:
            if (period_y if accrue else filed_y) == y:
                tax += amt  # 納付は必要経費（+）、還付は総収入金額（負の納付として扱う）
        res[y] = sales - cost - tax
    return res


def income_zeinuki(years, flows_split, payments):
    """税抜経理。flows_split[y] = (税抜の売上, 仮受消費税等, 税抜の経費, 仮払消費税等)。
    清算差額 = (仮受 − 仮払) − 納付すべき額 を、課税期間を含む年に（正なら総収入金額、負なら必要経費）算入（直所3-8 の 6）。"""
    res = {}
    for y in years:
        s, kariuke, c, karibarai = flows_split.get(y, (0, 0, 0, 0))
        due = sum(amt for period_y, _filed, amt in payments if period_y == y)
        settle = (kariuke - karibarai) - due
        res[y] = s - c + settle
    return res


def example_basic():
    """架空の例：毎年、税込売上 1,100,000（税抜 1,000,000＋消費税等 100,000）、税込経費 330,000（税抜 300,000＋30,000）。
    令和7年分・令和8年分の納付すべき消費税等をそれぞれ 20,000 と置く（外部で計算した値の代わりの架空の値）。
    令和7年分は令和8年3月に、令和8年分は令和9年3月に申告書を提出したとする。"""
    years = [2025, 2026, 2027]
    flows = {2025: (1_100_000, 330_000), 2026: (1_100_000, 330_000), 2027: (0, 0)}
    split = {2025: (1_000_000, 100_000, 300_000, 30_000), 2026: (1_000_000, 100_000, 300_000, 30_000)}
    pay = [(2025, 2026, 20_000), (2026, 2027, 20_000)]
    a = income_zeikomi(years, flows, pay, accrue=False)
    b = income_zeikomi(years, flows, pay, accrue=True)
    c = income_zeinuki(years, split, pay)
    menzei = income_zeikomi(years, flows, [], accrue=False)  # 免税事業者（納付なし、税込）
    return {"years": years, "zeikomi_filed_year": a, "zeikomi_accrued": b, "zeinuki": c, "menzei_zeikomi": menzei,
            "C1_zeinuki_eq_accrued": all(b[y] == c[y] for y in years),
            "C2_shift_equals_payment": (a[2025] - b[2025] == 20_000) and (b[2026] - a[2026] == 0) and (a[2027] - b[2027] == -20_000),
            "C2_sum_equal": sum(a.values()) == sum(b.values()) == sum(c.values())}


def example_partial_karibarai():
    """経過措置（適格請求書発行事業者以外の者からの課税仕入れ）で、仮払消費税等として区分する額が変わっても、
    固定資産・棚卸資産がなければ所得は変わらないこと。税込 110,000 の経費について、仮払を 10,000（全額）・8,000（80％）・
    7,000（70％）・0 と変え、区分しなかった分は経費（取引の対価）に含める（直所3-8 の 3の2・11の2、令和3年改正の経過的取扱い(2)(3)）。"""
    out = []
    for karibarai in (10_000, 8_000, 7_000, 0):
        cost_ex = 110_000 - karibarai
        split = {2026: (1_000_000, 100_000, cost_ex, karibarai)}
        pay = [(2026, 2027, 18_000)]
        inc = income_zeinuki([2026], split, pay)[2026]
        out.append({"karibarai": karibarai, "cost_ex": cost_ex, "income_2026": inc})
    zk = income_zeikomi([2026], {2026: (1_100_000, 110_000)}, [(2026, 2027, 18_000)], accrue=True)[2026]
    return {"cases": out, "zeikomi_accrued_2026": zk, "C1_all_equal": len({c["income_2026"] for c in out} | {zk}) == 1}


def example_refund():
    """還付：令和8年に税込 2,200,000 の課税仕入れ（経費。資産でないものと仮定）、税込売上 550,000。還付額 −150,000（架空）。"""
    years = [2026, 2027]
    flows = {2026: (550_000, 2_200_000)}
    split = {2026: (500_000, 50_000, 2_000_000, 200_000)}
    pay = [(2026, 2027, -150_000)]
    a = income_zeikomi(years, flows, pay, accrue=False)
    b = income_zeikomi(years, flows, pay, accrue=True)
    c = income_zeinuki(years, split, pay)
    return {"zeikomi_filed_year": a, "zeikomi_accrued": b, "zeinuki": c,
            "C3_zeinuki_eq_accrued": all(b[y] == c[y] for y in years),
            "C3_shift": a[2026] - b[2026] == -150_000}


def example_depreciation():
    """減価償却資産：令和8年1月に税込 330,000（税抜 300,000）の器具を取得、耐用年数 3 年の定額法（償却率は架空に 1/3 とし、
    月数按分・残存簿価の扱いは無視する）。税込経理では取得価額 330,000、税抜経理では 300,000 で、差の 30,000 は仮払消費税等として
    令和8年の清算に入る。所得の年の配分が変わり、3年の合計は同じになることだけを見る（償却の計算そのものは検証しない）。"""
    years = [2026, 2027, 2028]
    dep_in = {y: 110_000 for y in years}   # 330,000 / 3
    dep_ex = {y: 100_000 for y in years}   # 300,000 / 3
    sales_in, sales_ex, kariuke = 1_100_000, 1_000_000, 100_000
    due = 20_000
    zk = {y: sales_in - dep_in[y] - due for y in years}  # 税込・未払金計上（各年の納付を同年に）
    zn = {}
    for y in years:
        karibarai = 30_000 if y == 2026 else 0
        zn[y] = sales_ex - dep_ex[y] + ((kariuke - karibarai) - due)
    return {"zeikomi_accrued": zk, "zeinuki": zn, "C4_differs_by_year": any(zk[y] != zn[y] for y in years),
            "C4_sum_equal": sum(zk.values()) == sum(zn.values())}


def example_threshold():
    """推測 I1 の数値：令和7年分、税込売上 660,000（税抜 600,000＋60,000）、税込経費 77,000（税抜 70,000＋7,000）、
    令和7年分の消費税等 12,000（2割特例を想定した外部の値の代わりの架空の値）を令和8年3月に申告。他の所得は無いとする。
    比べる値：令和7年分の扶養親族の合計所得金額の要件 580,000 以下（docs/public-sources/20261109_R1-laws_income-tax.md §2）。"""
    years = [2025, 2026]
    flows = {2025: (660_000, 77_000)}
    split = {2025: (600_000, 60_000, 70_000, 7_000)}
    pay = [(2025, 2026, 12_000)]
    a = income_zeikomi(years, flows, pay, accrue=False)
    b = income_zeikomi(years, flows, pay, accrue=True)
    c = income_zeinuki(years, split, pay)
    menzei = income_zeikomi(years, flows, [], accrue=False)
    lim = 580_000
    return {"zeikomi_filed_year": a, "zeikomi_accrued": b, "zeinuki": c, "menzei": menzei, "limit_r7": lim,
            "within_limit_2025": {"zeikomi_filed_year": a[2025] <= lim, "zeikomi_accrued": b[2025] <= lim,
                                  "zeinuki": c[2025] <= lim, "menzei": menzei[2025] <= lim}}


def example_shogaku():
    """推測 I3 の数値：税抜経理で、適格請求書発行事業者以外の者から器具を買った場合の税抜の取得価額と、
    少額の減価償却資産（取得価額 10万円未満、所令138）の判定。仮払消費税等＝税込の額×10/110×控除割合（端数は切捨てと
    四捨五入の両方を出す。端数の扱いは一次情報で確認していない）。1の2 を選んだ場合は控除割合を 1 とする。"""
    from fractions import Fraction as F
    out = []
    for price in (107_000, 108_900):
        for label, ratio in (("登録事業者から（又は1の2）", F(1)), ("登録なし・2026-09-30 まで 80%", F(8, 10)),
                             ("登録なし・2026-10-01 から 70%", F(7, 10)), ("税込経理", None)):
            if ratio is None:
                cost_floor = cost_round = price
            else:
                kb = F(price) * F(10, 110) * ratio
                kb_floor = kb.numerator // kb.denominator
                kb_round = int(kb + F(1, 2)) if kb >= 0 else -int(-kb + F(1, 2))
                cost_floor, cost_round = price - kb_floor, price - kb_round
            out.append({"price_incl": price, "case": label, "cost_if_floor": cost_floor, "cost_if_round": cost_round,
                        "shogaku_under_100000": [cost_floor < 100_000, cost_round < 100_000]})
    return out


def property_check(n=2000, seed=20261109):
    """C1 の性質テスト：資産のない取引だけなら、どんな値でも 税抜 ＝ 税込（未払金計上）。"""
    rnd = random.Random(seed)
    bad = 0
    for _ in range(n):
        s_ex = rnd.randrange(0, 20_000_000)
        kariuke = rnd.randrange(0, 2_000_000)
        c_ex = rnd.randrange(0, 20_000_000)
        karibarai = rnd.randrange(0, 2_000_000)
        due = rnd.randrange(-2_000_000, 2_000_000)
        zn = income_zeinuki([1], {1: (s_ex, kariuke, c_ex, karibarai)}, [(1, 2, due)])[1]
        zk = income_zeikomi([1], {1: (s_ex + kariuke, c_ex + karibarai)}, [(1, 2, due)], accrue=True)[1]
        bad += zn != zk
    return {"n": n, "seed": seed, "mismatches": bad}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"basic": example_basic(), "partial_karibarai": example_partial_karibarai(), "refund": example_refund(),
           "depreciation": example_depreciation(), "property_C1": property_check(),
           "threshold_I1": example_threshold(), "shogaku_I3": example_shogaku()}
    (OUT / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    b = res["basic"]
    md = ["# R2B invoice 例の計算（架空の数値）", "",
          "## 基本の例（税込売上 1,100,000、税込経費 330,000、納付 20,000 を翌年3月に申告）", "",
          "| 年 | 税込・申告年に計上 | 税込・未払金計上 | 税抜 | 免税（税込） |", "|---|---|---|---|---|"]
    for y in b["years"]:
        md.append(f"| {y} | {b['zeikomi_filed_year'][y]:,} | {b['zeikomi_accrued'][y]:,} | {b['zeinuki'][y]:,} | {b['menzei_zeikomi'][y]:,} |")
    md += ["", f"- C1 税抜＝税込（未払金計上）：{b['C1_zeinuki_eq_accrued']}",
           f"- C2 申告年計上は納付額だけ翌年にずれる：{b['C2_shift_equals_payment']}、合計一致：{b['C2_sum_equal']}", "",
           "## 仮払消費税等として区分する額を変えた例（令和8年、税込経費 110,000、納付 18,000）", "",
           "| 仮払 | 税抜の経費 | 所得 |", "|---|---|---|"]
    for c in res["partial_karibarai"]["cases"]:
        md.append(f"| {c['karibarai']:,} | {c['cost_ex']:,} | {c['income_2026']:,} |")
    md += [f"", f"- 税込（未払金計上）の所得：{res['partial_karibarai']['zeikomi_accrued_2026']:,}、すべて一致：{res['partial_karibarai']['C1_all_equal']}", "",
           "## 還付の例", "", f"- {json.dumps({k: v for k, v in res['refund'].items()}, ensure_ascii=False)}", "",
           "## 減価償却資産の例", "", f"- {json.dumps(res['depreciation'], ensure_ascii=False)}", "",
           "## 性質テスト（C1）", "", f"- {json.dumps(res['property_C1'], ensure_ascii=False)}", "",
           "## 推測 I1 の数値（令和7年分、扶養親族の要件 580,000 以下との比較）", "",
           f"- {json.dumps(res['threshold_I1'], ensure_ascii=False)}", "",
           "## 推測 I3 の数値（税抜の取得価額と 10万円未満の判定。[切捨て, 四捨五入]）", "",
           "| 税込 | 場合 | 取得価額（切捨て） | 取得価額（四捨五入） | 10万円未満 |", "|---|---|---|---|---|"]
    for r in res["shogaku_I3"]:
        md.append(f"| {r['price_incl']:,} | {r['case']} | {r['cost_if_floor']:,} | {r['cost_if_round']:,} | {r['shogaku_under_100000']} |")
    (OUT / "results.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()

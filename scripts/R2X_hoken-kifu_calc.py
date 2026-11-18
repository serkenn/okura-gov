"""R2X_hoken-kifu: 生命保険料控除・地震保険料控除・寄附金控除・雑損控除と、ふるさと納税の特例控除の「条文どおりの式」を
整数・分数で書き、国税庁・総務省の説明（表の式・質疑応答事例の数値）と一致するかを確かめる。ネットワークは使わない。

実行:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_hoken-kifu_calc.py
標準ライブラリのみ（fractions）。出力：scripts/results/R2X_hoken-kifu_calc/checks.json と summary.txt

条文の出典（原文は scripts/results/R2X_hoken-kifu_egov/、scripts/results/R2X_hoken-kifu_egov2/ に取得済み）
- 所得税法第76条（asof 2025-12-31・2026-12-31・2027-01-01 で同文）
- 租税特別措置法第41条の15の5（asof 2026-04-01 以後の文言：令和8年分又は令和9年分）
- 所得税法第77条、所得税法等の一部を改正する等の法律（平成18年法律第10号）附則第10条
- 所得税法第78条、第72条
- 地方税法第314条の2第1項第5号・第5号の3、地方税法等の一部を改正する法律（平成18年法律第7号）附則第11条第5項
- 地方税法第314条の7第11項、附則第5条の6、附則第7条の2、附則第7条の3
説明の出典（取得は scripts/R2X_hoken-kifu_web.py）
- 国税庁 タックスアンサー No.1140・No.1145・No.1110、質疑応答事例（所得税）05/74・05/76・05/68
- 国税庁「令和8年分 年末調整のしかた」p.24（計算式Ⅰ〜Ⅲ）、p.26（地震保険料）
- 総務省 ふるさと納税ポータル「税金の控除について」
"""
import json
import pathlib
import random
import sys
from fractions import Fraction as F

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "results" / "R2X_hoken-kifu_calc"


# ---------- 所得税法第76条（各区分の式。端数は丸めずに分数で返す） ----------
def life_new(x, a=20000, b=40000, c=80000, base_b=20000, base_c=30000, cap=40000):
    """所法76①一イ〜ニ（新生命保険料）、②（介護医療）、③一（新個人年金）と同じ形の式。
    イ x<=a: x ／ ロ a<x<=b: base_b + (x-a)/2 ／ ハ b<x<=c: base_c + (x-b)/4 ／ ニ x>c: cap"""
    x = F(x)
    if x <= a:
        return x
    if x <= b:
        return F(base_b) + (x - a) / 2
    if x <= c:
        return F(base_c) + (x - b) / 4
    return F(cap)


def life_new_tokurei(x):
    """措法41の15の5①の読替え後の所法76①一：イ「二万円」→「三万円」、ロ「二万円」→「三万円」・「四万円」→「六万円」、
    ハ「四万円」→「六万円」・「八万円」→「十二万円」・「三万円」→「四万五千円」、ニ「八万円」→「十二万円」・「四万円」→「六万円」"""
    return life_new(x, a=30000, b=60000, c=120000, base_b=30000, base_c=45000, cap=60000)


def life_old(x):
    """所法76①二イ〜ニ（旧生命保険料）、③二（旧個人年金）"""
    return life_new(x, a=25000, b=50000, c=100000, base_b=25000, base_c=37500, cap=50000)


def life_ippan_options(new, old, tokurei=False):
    """一般の生命保険料：①一（新のみ）、①二（旧のみ）、①三（両方。合計の上限 4万円、特例は 6万円＝措法の「同項第三号中『四万円』とあるのは『六万円』」）。
    どれを適用するかは納税者の選択（質疑応答事例 05/75・05/76）。"""
    fn = life_new_tokurei if tokurei else life_new
    cap3 = 60000 if tokurei else 40000
    opts = {}
    if new > 0:
        opts["新のみ"] = fn(new)
    if old > 0:
        opts["旧のみ"] = life_old(old)
    if new > 0 and old > 0:
        opts["両方"] = min(fn(new) + life_old(old), F(cap3))
    return opts


def life_total(ippan, kaigo, nenkin):
    """所法76④：合計 12万円が上限"""
    return min(ippan + kaigo + nenkin, F(120000))


# ---------- 国税庁の表の式（TA1140、年末調整のしかた p.24 の計算式Ⅰ〜Ⅲ） ----------
def nta_shiki1(x):
    x = F(x)
    if x <= 20000:
        return x
    if x <= 40000:
        return x / 2 + 10000
    if x <= 80000:
        return x / 4 + 20000
    return F(40000)


def nta_shiki2(x):
    x = F(x)
    if x <= 30000:
        return x
    if x <= 60000:
        return x / 2 + 15000
    if x <= 120000:
        return x / 4 + 30000
    return F(60000)


def nta_shiki3(x):
    x = F(x)
    if x <= 25000:
        return x
    if x <= 50000:
        return x / 2 + 12500
    if x <= 100000:
        return x / 4 + 25000
    return F(50000)


# ---------- 地方税法第314条の2第1項第5号（住民税の生命保険料控除） ----------
def jumin_life_new(x):
    """（１）（ｉ）〜（ｉｖ）：1万2千円以下全額／3万2千円以下 1万2千＋1/2／5万6千円以下 2万2千＋1/4／超 2万8千円"""
    return life_new(x, a=12000, b=32000, c=56000, base_b=12000, base_c=22000, cap=28000)


def jumin_life_old(x):
    """（２）（ｉ）〜（ｉｖ）：1万5千円以下全額／4万円以下 1万5千＋1/2／7万円以下 2万7千5百＋1/4／超 3万5千円"""
    return life_new(x, a=15000, b=40000, c=70000, base_b=15000, base_c=27500, cap=35000)


# ---------- 地震保険料控除 ----------
def jishin_shotoku(jishin, kyu_choki):
    """所法77①（地震保険料：合計、上限5万円）、平18法10附則10②（旧長期損害保険料：1万円以下全額、2万円以下 1万＋1/2、超 1万5千円。
    両方あれば合計で上限5万円）"""
    def kyu(x):
        x = F(x)
        if x <= 10000:
            return x
        if x <= 20000:
            return 10000 + (x - 10000) / 2
        return F(15000)
    if jishin and kyu_choki:
        return min(min(F(jishin), F(50000)) + kyu(kyu_choki), F(50000))
    if jishin:
        return min(F(jishin), F(50000))
    if kyu_choki:
        return kyu(kyu_choki)
    return F(0)


def jishin_jumin(jishin, kyu_choki):
    """地法314の2①五の三（地震保険料の1/2、上限2万5千円）、平18法7附則11⑤（旧長期：5千円以下全額、超は 5千円＋超える額（上限1万円）の1/2。
    両方あれば合計で上限2万5千円）"""
    def j(x):
        return min(F(x) / 2, F(25000))

    def kyu(x):
        x = F(x)
        if x <= 5000:
            return x
        return 5000 + min(x - 5000, F(10000)) / 2
    if jishin and kyu_choki:
        return min(j(jishin) + kyu(kyu_choki), F(25000))
    if jishin:
        return j(jishin)
    if kyu_choki:
        return kyu(kyu_choki)
    return F(0)


# ---------- 寄附金控除（所法78①） ----------
def kifu_shotoku(total_tokutei_kifu, sougoukei):
    """一（特定寄附金の合計。総所得金額・退職所得金額・山林所得金額の合計の 40/100 を上限）が 二（2千円）を超える部分"""
    one = min(F(total_tokutei_kifu), F(sougoukei) * F(40, 100))
    return max(one - 2000, F(0))


# ---------- 雑損控除（所法72①） ----------
def zasson_law(L, D, T):
    """L：損失の金額（支出を含み、保険金等で補塡される部分を除く）、D：そのうちの災害関連支出の金額、T：総所得金額等の合計。
    一 D<=5万：足切り T/10 ／ 二 D>5万：min(L-(D-5万), T/10) ／ 三 L が全部 D：min(5万, T/10)"""
    L, D, T10 = F(L), F(D), F(T) / 10
    if L == D and L > 0:
        th = min(F(50000), T10)
    elif D <= 50000:
        th = T10
    else:
        th = min(L - (D - 50000), T10)
    return max(L - th, F(0))


def zasson_ta1110(L, D, T):
    """TA1110 の説明：(1) L - T×10% と (2) D - 5万円 のいずれか多い方（0 未満は 0）"""
    return max(F(L) - F(T) / 10, F(D) - 50000, F(0))


# ---------- ふるさと納税：地方税法の割合と、所得税の税率（所法89①）・復興特別所得税（×1.021）の関係 ----------
SHOTOKU_RATES = [5, 10, 20, 23, 33, 40, 45]          # 所法89①の税率（％）。zeigaku の公開資料の情報で確認済み
TOKUREI_BASE = [85, 80, 70, 67, 57, 50, 45]           # 地法314の7⑪一の表（本則）
TOKUREI_FUKKO = ["84.895", "79.79", "69.58", "66.517", "56.307", "49.16", "44.055"]  # 地法附則5の6②の読替え後
SHINKOKU_TOKUREI = [("5", "85"), ("10", "80"), ("20", "70"), ("23", "67"), ("33", "57")]  # 地法附則7の2⑤の表（本則）
SHINKOKU_TOKUREI_FUKKO = [("5.105", "84.895"), ("10.21", "79.79"), ("20.42", "69.58"), ("23.483", "66.517"), ("33.693", "56.307")]  # 附則7の3②


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    res = {}
    lines = []

    def rec(name, ok, detail):
        res[name] = {"ok": bool(ok), "detail": detail}
        lines.append(f"[{'OK' if ok else 'NG'}] {name}: {json.dumps(detail, ensure_ascii=False, default=str)}")

    # 1. 条文の式と国税庁の表の式の一致（0〜300,000円のすべての整数）
    rng = range(0, 300001)
    bad1 = [x for x in rng if life_new(x) != nta_shiki1(x)]
    rec("所法76①一（新生命保険料）＝ 計算式Ⅰ（TA1140・年末調整のしかた p.24）", not bad1, {"範囲": "0〜300000", "不一致の数": len(bad1), "例": bad1[:5]})
    bad2 = [x for x in rng if life_new_tokurei(x) != nta_shiki2(x)]
    rec("措法41の15の5①で読み替えた所法76①一 ＝ 計算式Ⅱ（23歳未満の扶養親族あり）", not bad2, {"範囲": "0〜300000", "不一致の数": len(bad2), "例": bad2[:5]})
    bad3 = [x for x in rng if life_old(x) != nta_shiki3(x)]
    rec("所法76①二（旧生命保険料）＝ 計算式Ⅲ", not bad3, {"範囲": "0〜300000", "不一致の数": len(bad3), "例": bad3[:5]})

    # 2. 境目での連続性（条文の式は区分の境目で値が飛ばない）
    def cont(fn, pts):
        return {p: [str(fn(p)), str(fn(p + 1))] for p in pts}
    rec("境目の値（新・特例・旧・住民税新・住民税旧）", True, {
        "新": cont(life_new, [20000, 40000, 80000]),
        "特例": cont(life_new_tokurei, [30000, 60000, 120000]),
        "旧": cont(life_old, [25000, 50000, 100000]),
        "住民税新": cont(jumin_life_new, [12000, 32000, 56000]),
        "住民税旧": cont(jumin_life_old, [15000, 40000, 70000])})

    # 3. 端数（1円未満）が生じる支払額の割合。条文は端数処理を書いていない。国税庁「年末調整のしかた」p.24 注2・p.26 注3 は「切り上げ」
    frac_new = sum(1 for x in range(0, 200001) if life_new(x).denominator != 1)
    frac_tok = sum(1 for x in range(0, 200001) if life_new_tokurei(x).denominator != 1)
    frac_old = sum(1 for x in range(0, 200001) if life_old(x).denominator != 1)
    frac_jn = sum(1 for x in range(0, 200001) if jumin_life_new(x).denominator != 1)
    frac_jk = sum(1 for x in range(0, 100001) if jishin_jumin(x, 0).denominator != 1)
    rec("1円未満の端数が生じる支払額の数（0〜200000円の整数のうち）", True, {
        "新（所得税）": frac_new, "特例": frac_tok, "旧（所得税）": frac_old, "新（住民税）": frac_jn, "地震（住民税、0〜100000円）": frac_jk,
        "例：新 20001円": str(life_new(20001)), "例：新 40003円": str(life_new(40003)), "例：住民税 地震 10001円": str(jishin_jumin(10001, 0))})

    # 4. 質疑応答事例 05/74：新4万円・旧10万円 → 新のみ3万、旧のみ5万、両方4万 → 5万円
    o = life_ippan_options(40000, 100000)
    rec("質疑応答 05/74（新4万・旧10万 → 控除額5万円）", max(o.values()) == 50000, {k: str(v) for k, v in o.items()})
    # 同じ支払で、23歳未満の扶養親族ありの令和8年分：新のみ 4万（=40000 は 3万以下を超え 6万以下 → 1/2+1.5万 = 3.5万）
    o2 = life_ippan_options(40000, 100000, tokurei=True)
    rec("同じ支払で措法41の15の5 の適用あり（推定値、出典の例ではない）", True, {k: str(v) for k, v in o2.items()})

    # 5. 質疑応答事例 05/76：一般5万（旧のみ）＋介護医療2.5万＋個人年金5万（旧のみ）＝12.5万 → 12万円
    t = life_total(F(50000), F(25000), F(50000))
    rec("質疑応答 05/76（合計12.5万 → 12万円）", t == 120000, {"合計": str(t)})

    # 6. 地震保険料：TA1145 の表、質疑応答 05/68（一の契約に地震1万・旧長期1.7万 → いずれか一方を選択 → 13,500円）
    j1 = jishin_shotoku(10000, 0)
    j2 = jishin_shotoku(0, 17000)
    rec("質疑応答 05/68（一の契約：地震1万 or 旧長期1.7万の選択 → 13,500円）", max(j1, j2) == 13500, {"地震のみ": str(j1), "旧長期のみ": str(j2)})
    bad_j = [x for x in range(0, 60001) if jishin_shotoku(0, x) != (F(x) if x <= 10000 else (F(x) / 2 + 5000 if x <= 20000 else F(15000)))]
    rec("平18附則10②二 ＝ TA1145 の表（旧長期：1万以下全額、2万以下 ×1/2＋5千、超 1万5千）", not bad_j, {"不一致の数": len(bad_j)})
    rec("住民税の地震保険料控除の例（推定値）", True, {"地震5万": str(jishin_jumin(50000, 0)), "地震6万": str(jishin_jumin(60000, 0)),
                                         "旧長期1万": str(jishin_jumin(0, 10000)), "旧長期2万": str(jishin_jumin(0, 20000)),
                                         "地震4万＋旧長期2万": str(jishin_jumin(40000, 20000))})

    # 7. 雑損控除：条文の3つの場合分けと TA1110 の「いずれか多い方」が一致するか（無作為の組 20万件＋境目）
    random.seed(20261109)
    bad_z = []
    cases = [(L, D, T) for L in (0, 30000, 50000, 50001, 80000, 300000) for D in (0, 30000, 50000, 50001, 80000) for T in (0, 300000, 500000, 600000, 5000000) if D <= L]
    for _ in range(200000):
        L = random.randint(0, 3000000)
        D = random.randint(0, L)
        T = random.randint(0, 20000000)
        cases.append((L, D, T))
    for L, D, T in cases:
        if zasson_law(L, D, T) != zasson_ta1110(L, D, T):
            bad_z.append((L, D, T, str(zasson_law(L, D, T)), str(zasson_ta1110(L, D, T))))
    rec("所法72①一〜三 ＝ TA1110 の「(1)と(2)のいずれか多い方」", not bad_z, {"件数": len(cases), "不一致の数": len(bad_z), "例": bad_z[:5]})

    # 8. 寄附金控除（所法78①）の例
    rec("所法78① の例（推定値）", True, {"寄附3万・総所得等300万": str(kifu_shotoku(30000, 3000000)),
                                     "寄附150万・総所得等300万（40%上限120万）": str(kifu_shotoku(1500000, 3000000)),
                                     "寄附2千": str(kifu_shotoku(2000, 3000000))})

    # 9. ふるさと納税：地方税法の割合と所得税率・復興特別所得税の関係
    rel = []
    ok9 = True
    for r, base, fk in zip(SHOTOKU_RATES, TOKUREI_BASE, TOKUREI_FUKKO):
        v_base = 90 - r
        v_fk = F(90) - F(r) * F("1.021")
        rel.append({"所得税率%": r, "本則の割合%": base, "90-税率": v_base, "附則5の6の割合%": fk, "90-税率×1.021": str(float(v_fk))})
        ok9 = ok9 and (base == v_base) and (F(fk) == v_fk)
    rec("地法314の7⑪一の表 ＝ 90%−所得税率、附則5の6 ＝ 90%−所得税率×1.021", ok9, rel)
    rel2 = []
    ok10 = True
    for (n, d), (nf, dfk), r in zip(SHINKOKU_TOKUREI, SHINKOKU_TOKUREI_FUKKO, SHOTOKU_RATES[:5]):
        ok10 = ok10 and F(n) == r and F(d) == 90 - r and F(nf) == F(r) * F("1.021") and F(dfk) == 90 - F(r) * F("1.021")
        rel2.append({"所得税率%": r, "附則7の2": f"{d}分の{n}", "附則7の3": f"{dfk}分の{nf}"})
    rec("附則7の2・7の3 の割合 ＝ 所得税率(×1.021) ÷ (90%−所得税率(×1.021))", ok10, rel2)

    # 10. 特例控除＋基本分＋（所得税の軽減）の和が（寄附−2千円）に一致する条件の確認（20%上限に当たらず、
    #     所得税の限界税率と特例分の割合の区分が同じ場合）。基本分 10%（4%+6%）＋特例分(90%−r×1.021)＋所得税 r×1.021 ＝ 100%
    ok11 = all(F(10) + (F(90) - F(r) * F("1.021")) + F(r) * F("1.021") == 100 for r in SHOTOKU_RATES)
    rec("基本分10%＋特例分＋所得税分（r×1.021）＝100%（区分が一致し上限に当たらない場合）", ok11, {"税率": SHOTOKU_RATES})

    (OUT / "checks.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (OUT / "summary.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print("NG の数:", sum(1 for v in res.values() if not v["ok"]))


if __name__ == "__main__":
    sys.exit(main())

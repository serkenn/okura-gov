"""IMPL jigyo: 取得済みの条文テキストと国税庁ページのテキストから、基準額・期間を機械的に読み取り、
家内労働者等の特例の計算を2つの書き方（措置法施行令の文言／国税庁の計算書）で突き合わせる。

実行（Python 3.11、標準ライブラリのみ。ネットワークは使わない）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_jigyo_checks.py

入力（先に scripts/IMPL_jigyo_laws.py と scripts/IMPL_jigyo_nta.py を実行しておく）:
  scripts/results/IMPL_jigyo_laws/*.txt            e-Gov 法令API v2 から取り出した条文
  scripts/results/R1_egov_articles/shotoku_*.txt   R1 で取り出した所得税法第2条（扶養親族の所得要件）
  scripts/results/IMPL_jigyo_nta/ta_index/ta_1810.txt  タックスアンサー No.1810 の本文
出力:
  scripts/results/IMPL_jigyo_checks/checks.json, checks.md
"""
import itertools
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
LAWS = ROOT / "scripts" / "results" / "IMPL_jigyo_laws"
R1 = ROOT / "scripts" / "results" / "R1_egov_articles"
NTA = ROOT / "scripts" / "results" / "IMPL_jigyo_nta"
OUT = ROOT / "scripts" / "results" / "IMPL_jigyo_checks"

DIG = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
UNIT = {"十": 10, "百": 100, "千": 1000}


def kanji_int(s):
    """「六十五万」「三百万」「千万」「七」などの漢数字を整数にする（万の位まで）。"""
    total, man = 0, 0
    if "万" in s:
        hi, lo = s.split("万", 1)
        man = kanji_small(hi) if hi else 1
        total = man * 10000 + (kanji_small(lo) if lo else 0)
        return total
    return kanji_small(s)


def kanji_small(s):
    n, cur = 0, 0
    for ch in s:
        if ch in DIG:
            cur = DIG[ch]
        elif ch in UNIT:
            n += (cur if cur else 1) * UNIT[ch]
            cur = 0
        else:
            raise ValueError(s)
    return n + cur


def articles(path):
    """IMPL_jigyo_laws の出力を「## Num=..」ごとに分ける。"""
    t = path.read_text(encoding="utf-8")
    parts = re.split(r"^## (Num=[^\n]+|附則[^\n]*)$", t, flags=re.M)
    d = {}
    for i in range(1, len(parts), 2):
        d[parts[i].replace("Num=", "")] = parts[i + 1]
    return d


def amounts(text, pat=r"([〇一二三四五六七八九十百千万]+)円"):
    return [kanji_int(m) for m in re.findall(pat, text)]


def para(text, num_kanji):
    """条の本文から「２　…」のような項を取り出す（第1項は（Paragraph1））。"""
    if num_kanji == "1":
        m = re.search(r"（Paragraph1）[^\n]*(?:\n  [^\n]*)*", text)
    else:
        m = re.search(rf"^{num_kanji}　[^\n]*(?:\n  [^\n]*)*", text, flags=re.M)
    return m.group(0) if m else None


ZEN = "０１２３４５６７８９"


def zen(n):
    return "".join(ZEN[int(c)] for c in str(n))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"inputs": [], "checks": {}}

    def use(p):
        res["inputs"].append(str(p.relative_to(ROOT)).replace("\\", "/"))
        return p

    # C1/C2 家内労働者等の特例の額（措法27、措令18の2）
    c = {}
    for asof in ["2025-12-31", "2026-12-31", "2027-01-01", "2030-12-31"]:
        a = articles(use(LAWS / f"sochi_{asof}.txt"))
        c[f"sochi27@{asof}"] = sorted(set(amounts(a["27"])))
    for asof in ["2025-12-31", "2026-12-31", "2030-12-31"]:
        a = articles(use(LAWS / f"sochi-rei_{asof}.txt"))
        c[f"sochirei18_2@{asof}"] = sorted(set(amounts(a["18_2"])))
    res["checks"]["C1_kanai_amounts"] = c

    # C3 一時所得の特別控除・総所得金額の2分の1
    c = {}
    for asof in ["2025-12-31", "2026-12-31", "2027-01-01", "2030-12-31"]:
        a = articles(use(LAWS / f"shotoku_{asof}.txt"))
        c[f"shotoku34_3@{asof}"] = amounts(para(a["34"], "３"))
        c[f"shotoku22_2_ii_has_half@{asof}"] = "一時所得の金額" in a["22"] and "二分の一に相当する金額" in a["22"]
    res["checks"]["C3_ichiji"] = c

    # C4 300万円・1,000万円の基準（所令196の2、所法232②、所法45③、所法120 の内訳書添付の項）
    c = {}
    for asof in ["2025-12-31", "2026-12-31", "2027-01-01", "2030-12-31"]:
        a = articles(use(LAWS / f"shotoku_{asof}.txt"))
        c[f"shotoku232_2@{asof}"] = amounts(para(a["232"], "２"))
        c[f"shotoku45_3@{asof}"] = amounts(para(a["45"], "３"))[:1]
        hit = None
        for n in range(2, 12):
            p = para(a["120"], zen(n))
            if p and "総収入金額及び必要経費の内容を記載した書類" in p:
                hit = {"paragraph": n, "amounts": amounts(p)}
        c[f"shotoku120_shushi@{asof}"] = hit
    for asof in ["2025-12-31", "2026-12-31", "2030-12-31"]:
        a = articles(use(LAWS / f"shotoku-rei_{asof}.txt"))
        c[f"shotokurei196_2@{asof}"] = amounts(a["196_2"])
        c[f"shotokurei96_item1_has_zatsu@{asof}"] = bool(re.search(r"一　[^\n]*雑所得", a["96"]))
        c[f"shotokurei96_item2_has_zatsu@{asof}"] = bool(re.search(r"二　[^\n]*雑所得", a["96"]))
        c[f"shotokurei96_item2_requires_aoiro@{asof}"] = bool(re.search(r"二　[^\n]*青色申告書を提出することにつき税務署長の承認", a["96"]))
    res["checks"]["C4_thresholds"] = c

    # C5 白色の帳簿書類の保存期間（所規102④⑧）
    c = {}
    for asof in ["2025-12-31", "2026-12-31", "2030-12-31"]:
        a = articles(use(LAWS / f"shotoku-ki_{asof}.txt"))
        p4, p8 = para(a["102"], "４"), para(a["102"], "８")
        c[f"shotokuki102_4_years@{asof}"] = [kanji_int(x) for x in re.findall(r"([一二三四五六七八九十]+)年間", p4)]
        c[f"shotokuki102_8_years@{asof}"] = [kanji_int(x) for x in re.findall(r"([一二三四五六七八九十]+)年間", p8)]
    res["checks"]["C5_retention"] = c

    # C6 所法45① が雑所得を含むか、所法37① が雑所得を含むか、所法67② の有無
    c = {}
    for asof in ["2025-12-31", "2026-12-31", "2027-01-01", "2030-12-31"]:
        a = articles(use(LAWS / f"shotoku_{asof}.txt"))
        c[f"shotoku45_1_lists_zatsu@{asof}"] = "事業所得の金額、山林所得の金額又は雑所得の金額の計算上、必要経費に算入しない" in para(a["45"], "1")
        c[f"shotoku37_1_lists_zatsu@{asof}"] = "事業所得の金額又は雑所得の金額" in para(a["37"], "1")
        c[f"shotoku67_2_present@{asof}"] = bool(para(a["67"], "２")) and "雑所得を生ずべき業務" in para(a["67"], "２")
        c[f"shotoku67_1_requires_aoiro@{asof}"] = "青色申告書を提出することにつき税務署長の承認を受けている居住者" in para(a["67"], "1")
        c[f"shotoku35_5_present@{asof}"] = bool(para(a["35"], "５"))
    res["checks"]["C6_scope"] = c

    # C8 青色申告特別控除の額（措法25の2）
    c = {}
    for asof in ["2025-12-31", "2026-12-31", "2027-01-01", "2030-12-31"]:
        a = articles(use(LAWS / f"sochi_{asof}.txt"))
        c[f"sochi25_2@{asof}"] = sorted(set(amounts(a["25_2"])))
    res["checks"]["C8_aoiro_amounts"] = c

    # C9 タックスアンサー No.1810 の注記の金額と、条文の値からの計算の突合せ
    fuyo = {}
    for y, f in [("R7", "shotoku_2025-12-31.txt"), ("R8", "shotoku_2026-12-01.txt")]:
        t = use(R1 / f).read_text(encoding="utf-8")
        line = [ln for ln in t.splitlines() if ln.startswith("  三十四　扶養親族")][0]
        fuyo[y] = kanji_int(re.search(r"合計所得金額が([〇一二三四五六七八九十百千万]+)円以下", line).group(1))
    kanai = {"R7": res["checks"]["C1_kanai_amounts"]["sochi27@2025-12-31"][0],
             "R8": res["checks"]["C1_kanai_amounts"]["sochi27@2026-12-31"][0]}
    ta = use(NTA / "ta_index" / "ta_1810.txt").read_text(encoding="utf-8")
    ta_amounts = sorted(set(int(x.replace(",", "")) * 10000 for x in re.findall(r"([0-9,]+)万円", ta)))
    kiso_ta = {"R8": 1040000, "R7": 950000}  # TA No.1810 本文中の基礎控除額（「基礎控除額の104万円」「基礎控除額が95万円」）
    c = {"fuyo_limit_from_law": fuyo, "kanai_amount_from_law": kanai, "ta1810_amounts_found": ta_amounts}
    for y in ["R7", "R8"]:
        c[f"{y}_only_kanai_income_upper_for_fuyo(=kanai+fuyo)"] = kanai[y] + fuyo[y]
        c[f"{y}_only_kanai_income_upper_for_no_tax(=kanai+kiso_in_TA)"] = kanai[y] + kiso_ta[y]
    c["TA_states_R8_131man_for_fuyo"] = "131万円以下の場合は、扶養者の所得税額の計算上" in ta
    c["TA_states_R7_160man_for_both_no_tax_and_fuyo"] = bool(re.search(r"160万円以下の場合は、[^。]*95万円以下[^。]*扶養控除の対象となります。", ta))
    c["TA_states_R8_173man_for_no_tax"] = "173万円以下の場合は、総所得金額が基礎控除額の104万円以下" in ta
    res["checks"]["C9_ta1810_vs_law"] = c

    # C10 家内労働者等の特例の配分：措令18の2②の文言どおりの計算 と 国税庁の計算書（⑤〜⑨）の計算 を総当たりで比べる
    def by_seirei(base, sal_ded, R_biz, E_biz, R_misc, E_misc):
        F = max(0, base - sal_ded)
        if E_biz + E_misc >= F:
            return None  # 特例の要件（必要経費の合計額が F に満たない）を満たさない
        has_biz, has_misc = R_biz > 0, R_misc > 0
        if has_biz and not has_misc:
            return (min(F, R_biz), 0)
        if has_misc and not has_biz:
            return (0, min(F, R_misc))
        ro = max(0, F - E_biz)                        # ロ：F のうち事業所得の必要経費に達するまでの部分以外の部分
        short = max(0, ro - R_misc)                   # 雑所得の総収入金額がロに満たない部分
        i = min(F, E_biz + short)                     # イ
        return (min(i, R_biz), min(ro, R_misc))       # 措法27 後段：それぞれの総収入金額が限度

    def by_nta_sheet(base, sal_income, R_biz, E_biz, R_misc):
        v5 = max(0, base - E_biz - sal_income)
        v6 = max(0, base - R_misc - sal_income)
        if R_biz > 0:
            biz = min(R_biz, v6) if (R_misc == 0 or R_misc <= v5) else E_biz
        else:
            biz = 0
        misc = min(R_misc, v5) if R_misc > 0 else 0
        if R_biz > 0 and R_misc == 0 and sal_income == 0:
            biz = min(R_biz, base)
        return (biz, misc)

    grid = range(0, 1000001, 50000)
    stats = {"compared": 0, "equal": 0, "diff": 0, "diff_only_when_E_biz_gt_R_biz": True, "examples": []}
    base = 650000
    for R_biz, E_biz, R_misc, E_misc, sal in itertools.product(grid, range(0, 700001, 50000), grid, range(0, 300001, 100000), [0, 300000, 600000]):
        if R_biz == 0 and R_misc == 0:
            continue
        if R_biz == 0 and E_biz > 0:
            continue
        a = by_seirei(base, min(sal, base), R_biz, E_biz, R_misc, E_misc)  # 給与所得控除額は給与収入（計算書の読み方）
        if a is None:
            continue
        b = by_nta_sheet(base, sal, R_biz, E_biz, R_misc)
        stats["compared"] += 1
        if a == b:
            stats["equal"] += 1
        else:
            stats["diff"] += 1
            if not E_biz > R_biz:
                stats["diff_only_when_E_biz_gt_R_biz"] = False
            if len(stats["examples"]) < 5:
                stats["examples"].append({"R_biz": R_biz, "E_biz": E_biz, "R_misc": R_misc, "E_misc": E_misc, "salary": sal, "seirei": a, "nta_sheet": b})
    res["checks"]["C10_allocation_equivalence_R7base"] = stats

    # C11 給与がある場合の F（＝特例額−給与所得控除額）の、給与所得控除額の2通りの読み方による違い
    def kyuyo_koujo_r7_literal(x):   # 所法28③一（令和7年分）：収入190万円以下は65万円（収入を限度とする文言はない）
        return 650000 if 0 < x <= 1900000 else 0

    def kyuyo_koujo_r8(x):           # 措法29の4①（令和8・9年）：収入220万円以下は74万円（収入が74万円未満なら収入）
        return min(740000, x) if 0 < x <= 2200000 else None

    rows = []
    for sal in [0, 100000, 300000, 640000, 650000, 690000, 700000, 740000]:
        rows.append({"salary_income": sal,
                     "R7_F_literal(65万-所法28③一)": max(0, 650000 - kyuyo_koujo_r7_literal(sal)) if sal else 650000,
                     "R7_F_nta_sheet(65万-給与収入)": max(0, 650000 - sal),
                     "R8_F_with_sochi29_4(69万-min(74万,収入))": max(0, 690000 - (kyuyo_koujo_r8(sal) or 0)),
                     "R8_F_nta_style(69万-給与収入)": max(0, 690000 - sal)})
    res["checks"]["C11_salary_adjustment_readings"] = rows

    (OUT / "checks.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# IMPL_jigyo_checks の結果", "", "入力：", *[f"- `{p}`" for p in sorted(set(res["inputs"]))], ""]
    for k, v in res["checks"].items():
        md += [f"## {k}", "", "```json", json.dumps(v, ensure_ascii=False, indent=1), "```", ""]
    (OUT / "checks.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps(res["checks"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

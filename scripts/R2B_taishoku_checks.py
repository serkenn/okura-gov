"""R2B taishoku: 退職所得の計算の構造を、取得した条文（scripts/results/R2B_taishoku_egov/）から組み立て、
国税庁・総務省の設例（scripts/results/R2B_taishoku_web/ と PDF の目視転記）と照合する。

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_taishoku_checks.py
標準ライブラリのみ。ネットワークには接続しない。入力は scripts/results/ の下の、これまでの取得で作ったテキストだけ。
出力: scripts/results/R2B_taishoku_checks/checks.json（各検査の入力・期待値・計算値・一致）と summary.txt。

検査の一覧
  C1 所得税法 別表第六（源泉徴収のための退職所得控除額の表）の各行が、第30条第3項・第6項第2号・第3号の式と一致するか（全時点）
  C2 第89条の税率表を条文から読み取り、速算表（TA2732 別紙）の控除額と一致するか
  C3 勤続年数（所基通30-13 の期間の数え方＋所令69②の1年未満切上げ）を、国税庁の設例の期間で計算する
  C4 退職所得の金額（一般・短期・特定役員、所令71の2③の一般＋特定役員）を国税庁の設例と照合する
  C5 源泉徴収税額（所法201①③、復興特別所得税 2.1%、端数）を国税庁の設例と照合する
  C6 住民税の分離課税に係る所得割（地方税法328の2〜328の3・50の3〜50の4、20の4の2）を総務省の早見表（目視転記）と照合する
  C7 所令70①二（前の退職手当等の範囲）の改正前・改正後を、令和7年・令和8年・令和9年の支払の組合せで比べる
  C8 合計所得金額（所得税は退職所得を含む／住民税は源泉徴収された退職所得を除く）を国税庁の設例で確かめる
  C9 取得した条文から基準額と文言を抜き出す（所法2①三十二の勤労学生、地法292①七・九、地法附則3の3 の「分離課税に係る所得割を除く」）
"""
import datetime as dt
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
EG = ROOT / "scripts" / "results" / "R2B_taishoku_egov"
OUT = ROOT / "scripts" / "results" / "R2B_taishoku_checks"

ZEN = str.maketrans("０１２３４５６７８９，", "0123456789,")
KDIG = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def kanji_num(s):
    """「千八百」「六百九十五」「四千」などの漢数字（万未満の部分）を整数にする。"""
    total, cur = 0, 0
    for ch in s:
        if ch in KDIG:
            cur = KDIG[ch]
        elif ch in "十百千":
            unit = {"十": 10, "百": 100, "千": 1000}[ch]
            total += (cur or 1) * unit
            cur = 0
        else:
            raise ValueError(s)
    return total + cur


def kanji_yen(s):
    """「千八百万円」「百九十五万円」「四千万円」を円の整数にする。"""
    m = re.fullmatch(r"(.+)万円", s)
    if not m:
        raise ValueError(s)
    return kanji_num(m.group(1)) * 10000


def article_block(path, num):
    t = path.read_text(encoding="utf-8")
    m = re.search(rf"^## Num={re.escape(num)}\n(.*?)(?=^## )", t, re.S | re.M)
    return m.group(1) if m else None


def appdx_block(path, title):
    t = path.read_text(encoding="utf-8")
    m = re.search(rf"^## 別表「{re.escape(title)}」.*?\n(.*?)(?=^## )", t, re.S | re.M)
    return m.group(1) if m else None


# ---------------- 法令の構造（条文から） ----------------
def taishoku_kojo(years, disability=False, prior_overlap_years=0):
    """所法30③（40万円×年数 / 800万円＋70万円×(年数−20)）、⑥一（前の退職手当等の重複期間の控除額を引く）、
    ⑥二（80万円に満たないとき80万円。⑥三に当たる場合を除く）、⑥三（⑥一後の額（80万円未満なら80万円）に100万円を加算）。"""
    def base(n):
        return 400_000 * n if n <= 20 else 8_000_000 + 700_000 * (n - 20)
    amt = base(years)
    if prior_overlap_years:
        amt -= base(prior_overlap_years)
    if disability:
        return max(amt, 800_000) + 1_000_000
    return max(amt, 800_000)


def kinzoku_years(start, end):
    """所基通30-13：暦に従って計算し、1月に満たない期間は日で数え、日数は30日を1月、月数は12月を1年とする。
    所令69②：1年未満の端数は1年とする。期間は就職の日から退職の日まで（両端を含む）として、退職の日の翌日までの暦の差で数える。"""
    e = end + dt.timedelta(days=1)
    y, m = e.year - start.year, e.month - start.month
    d = e.day - start.day
    if d < 0:
        m -= 1
        prev_month_end = dt.date(e.year, e.month, 1) - dt.timedelta(days=1)
        d += prev_month_end.day
    if m < 0:
        y -= 1
        m += 12
    m += d // 30
    d = d % 30
    y += m // 12
    m = m % 12
    return y + (1 if (m or d) else 0), (y, m, d)


def taishoku_shotoku(income, kojo, kind):
    """所法30②：一般＝(収入−控除)×1/2、特定役員＝収入−控除、短期＝残額300万円以下なら1/2、超えるなら150万円＋(収入−(300万円＋控除))。
    残額が負なら 0（「残額」）。ここでは端数処理をしない（源泉の 1,000円未満切捨ては所法201①、確定申告は通則法118①で課税標準に）。"""
    r = max(income - kojo, 0)
    if kind == "ippan":
        return r / 2
    if kind == "tokutei_yakuin":
        return r
    if kind == "tanki":
        return r / 2 if r <= 3_000_000 else 1_500_000 + (income - (3_000_000 + kojo))
    raise ValueError(kind)


def ippan_plus_tokutei(ippan_income, tokutei_income, total_years, tokutei_years, overlap_years):
    """所令71の2③（一般＋特定役員）。特定役員退職所得控除額＝40万円×(特定役員等勤続年数−重複勤続年数)＋20万円×重複勤続年数。
    一般退職所得控除額＝退職所得控除額−特定役員退職所得控除額。収入が控除額に満たない場合の調整（③一・二のかっこ書）は、この設例では起きない。"""
    kojo = taishoku_kojo(total_years)
    tk = 400_000 * (tokutei_years - overlap_years) + 200_000 * overlap_years
    ik = kojo - tk
    return (tokutei_income - tk) + (ippan_income - ik) / 2, {"退職所得控除額": kojo, "特定役員退職所得控除額": tk, "一般退職所得控除額": ik}


def tanki_plus_tokutei(tanki_income, tokutei_income, total_years, tokutei_years, overlap_years):
    """所令71の2⑤（短期＋特定役員。一般なし）。特定役員退職所得控除額＝40万円×(特定役員等勤続年数−重複)＋20万円×重複、
    短期退職所得控除額＝退職所得控除額−特定役員退職所得控除額。短期の残額が300万円以下なら1/2、超えるなら150万円＋(収入−(300万円＋短期控除))。
    控除額に満たない場合の調整（⑤一・二のかっこ書）は、この設例では起きない。"""
    kojo = taishoku_kojo(total_years)
    tk = 400_000 * (tokutei_years - overlap_years) + 200_000 * overlap_years
    sk = kojo - tk
    r = tanki_income - sk
    tanki_part = r / 2 if r <= 3_000_000 else 1_500_000 + (tanki_income - (3_000_000 + sk))
    return (tokutei_income - tk) + tanki_part, {"退職所得控除額": kojo, "特定役員退職所得控除額": tk, "短期退職所得控除額": sk}


def rate_table_from_law():
    """所法89①の表を、取得した条文（asof 2026-11-09）から読む。返り値：[(上限 or None, 率の分子, 分母)]"""
    blk = article_block(EG / "shotoku_2026-11-09.txt", "89")
    rows = re.findall(r"^\s*\| (.+?) \| 百分の(.+?) \|$", blk, re.M)
    out = []
    for amount, rate in rows:
        m = re.search(r"(?:を超え)?(.+?万円)以下の金額$", amount)
        upper = kanji_yen(m.group(1).split("を超え")[-1]) if m else None
        out.append((upper, kanji_num(rate), 100))
    return out


def income_tax_89(taxable):
    tbl = rate_table_from_law()
    tax_num, lower = 0, 0  # 円×100 の整数で持つ（率が百分の n なので）
    for upper, num, den in tbl:
        top = taxable if upper is None else min(taxable, upper)
        if top > lower:
            tax_num += (top - lower) * num
        if upper is None or taxable <= upper:
            break
        lower = upper
    return tax_num  # 所得税額×100（端数処理の前）


def gensen_with_shinkokusho(kazei_taishoku_before_round):
    """所法201①一：課税退職所得金額とみなす金額は 1,000円未満切捨て。第89条①で税額。
    復興財確法28②：所得税額に 2.1%。国税庁の速算表は (A×B−C)×102.1% として 1円未満を切り捨てる（TA2732 別紙）。"""
    a = int(kazei_taishoku_before_round) // 1000 * 1000
    tax100 = income_tax_89(a)                  # 所得税×100
    total = tax100 * 1021 // 100000            # (所得税×102.1%) を 1円未満切捨て： tax100/100 × 1021/1000
    return a, total


def gensen_without_shinkokusho(payment):
    """所法201③：支払金額×20%。復興 2.1% を併せて 20.42%（TA2732）。1円未満切捨て。"""
    return payment * 2042 // 10000


def juminzei_bunri(before_half):
    """地方税法328の2②（所法30②の計算の例）・50の3②、20の4の2①（課税標準 1,000円未満切捨て）・③（確定金額 100円未満切捨て）、
    328の3（市町村 6%）・50の4（道府県 4%）。総務省の案内は「それぞれ百円未満の端数を切り捨てる」。"""
    base = (before_half // 2) // 1000 * 1000
    city = base * 6 // 100 // 100 * 100
    pref = base * 4 // 100 // 100 * 100
    return base, city, pref


# ---------------- 所令70①二（前の退職手当等の範囲） ----------------
IDECO_START = dt.date(2026, 1, 1)


def prior_in_scope_old(year, prior_date, prior_is_ideco, current_has_ideco):
    """改正前（asof 2025-12-31）：前年以前4年内（その年に iDeCo の一時金の支払を受ける場合には19年内）に支払を受けた退職手当等。"""
    span = 19 if current_has_ideco else 4
    return year - span <= prior_date.year <= year - 1


def prior_in_scope_new(year, prior_date, prior_is_ideco, current_has_ideco, priors):
    """改正後（asof 2026-11-09、所令70①二イロハ）。priors は前年以前に支払を受けた全部の (date, is_ideco)。
    ハ：前年以前19年内に退職手当等を受け、かつ、その年に iDeCo の一時金を受ける → 前年以前19年内のもの。
    ロ：前年以前9年内に iDeCo の一時金（令和8年1月1日以後に支払を受けたもの）を受け、かつ、その年に退職手当等を受ける（ハを除く）
        → (1) 令和8年1月1日以後に受けたもので前年以前9年内のもの、(2) 令和8年1月1日前に受けたもので前年以前4年内のもの。
    イ：前年以前4年内に退職手当等を受け、かつ、その年に退職手当等を受ける（ロ・ハを除く） → 前年以前4年内のもの。"""
    if current_has_ideco and any(year - 19 <= d.year <= year - 1 for d, _ in priors):
        return year - 19 <= prior_date.year <= year - 1
    if any(i and d >= IDECO_START and year - 9 <= d.year <= year - 1 for d, i in priors):
        if prior_date >= IDECO_START:
            return year - 9 <= prior_date.year <= year - 1
        return year - 4 <= prior_date.year <= year - 1
    return year - 4 <= prior_date.year <= year - 1


def c7_cases():
    out = []
    for year in range(2025, 2036):
        for prior_year in range(year - 20, year):
            for prior_is_ideco in (False, True):
                for current_has_ideco in (False, True):
                    pd = dt.date(prior_year, 6, 30)
                    priors = [(pd, prior_is_ideco)]
                    old = prior_in_scope_old(year, pd, prior_is_ideco, current_has_ideco)
                    new = prior_in_scope_new(year, pd, prior_is_ideco, current_has_ideco, priors)
                    out.append({"year": year, "prior_year": prior_year, "prior_is_ideco": prior_is_ideco,
                                "current_has_ideco": current_has_ideco, "old": old, "new": new, "same": old == new})
    # 前の退職手当等が2つある場合（ロ(1)：令和8年以後の一般の退職手当等が、令和8年以後の iDeCo の一時金があることで9年内の対象になる）
    for year, priors in [(2031, [(dt.date(2026, 3, 31), False), (dt.date(2027, 6, 30), True)]),
                         (2030, [(dt.date(2026, 3, 31), False), (dt.date(2027, 6, 30), True)]),
                         (2031, [(dt.date(2025, 12, 31), False), (dt.date(2027, 6, 30), True)])]:
        for pd, pi in priors:
            old = prior_in_scope_old(year, pd, pi, False)
            new = prior_in_scope_new(year, pd, pi, False, priors)
            out.append({"year": year, "prior_year": pd.isoformat(), "prior_is_ideco": pi, "current_has_ideco": False,
                        "other_priors": [(d.isoformat(), i) for d, i in priors], "old": old, "new": new, "same": old == new})
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"generated_by": "scripts/R2B_taishoku_checks.py", "inputs": [], "checks": {}}

    # C1 別表第六
    c1 = []
    for asof in ["2024-12-31", "2025-12-31", "2026-11-09", "2026-12-31", "2027-01-01"]:
        p = EG / f"shotoku_{asof}.txt"
        res["inputs"].append(str(p.relative_to(ROOT)))
        blk = appdx_block(p, "別表第六")
        rows = 0
        mism = []
        for line in blk.splitlines():
            cells = [c.strip().translate(ZEN) for c in line.strip().strip("|").split("|")]
            # 1行に (年数, 一般, 障害) が左右2組ある
            for j in range(0, len(cells) - 2, 3):
                ycell, g, h = cells[j], cells[j + 1], cells[j + 2]
                m = re.fullmatch(r"(\d+)年(以下)?", ycell)
                if not m or not g.replace(",", "").isdigit():
                    continue
                n = int(m.group(1))
                gen, dis = int(g.replace(",", "")) * 1000, int(h.replace(",", "")) * 1000
                ns = range(1, n + 1) if m.group(2) else [n]
                for k in ns:
                    rows += 1
                    eg, ed = taishoku_kojo(k), taishoku_kojo(k, disability=True)
                    if (gen, dis) != (eg, ed):
                        mism.append({"years": k, "table": [gen, dis], "formula": [eg, ed]})
        tail = "４１年以上" in blk and "２２，０００千円に、勤続年数が４０年を超える１年ごとに７００千円を加算" in blk
        f41 = [taishoku_kojo(k) == 22_000_000 + 700_000 * (k - 40) for k in range(41, 61)]
        c1.append({"asof": asof, "rows_checked": rows, "mismatches": mism, "row_41_plus_text_found": tail,
                   "formula_matches_41_plus_rule_41_to_60": all(f41)})
    res["checks"]["C1_beppyo6"] = c1

    # C2 税率表と速算表の控除額
    tbl = rate_table_from_law()
    quick = []
    lower, ded = 0, 0
    prev_rate = 0
    for upper, num, den in tbl:
        ded += lower * (num - prev_rate) // 100  # 控除額 = Σ 境目 × 率の差
        quick.append({"over": lower, "upper": upper, "rate_pct": num, "deduction": ded})
        prev_rate = num
        lower = upper or lower
    nta_quick = [0, 97_500, 427_500, 636_000, 1_536_000, 2_796_000, 4_796_000]  # TA2732 別紙の「控除額」欄
    res["checks"]["C2_rate_table"] = {"law_table": [{"upper": u, "rate": f"{n}/{d}"} for u, n, d in tbl], "quick": quick,
                                      "nta_deductions": nta_quick,
                                      "match_all": [q["deduction"] for q in quick] == nta_quick}

    # C3 勤続年数
    c3 = []
    for label, s, e, expect in [
        ("TA2735 A社 平29.4.1〜令8.3.31", dt.date(2017, 4, 1), dt.date(2026, 3, 31), 9),
        ("TA2735 B社の通算 平29.4.1〜令8.7.31（9年4か月）", dt.date(2017, 4, 1), dt.date(2026, 7, 31), 10),
        ("TA1420/TA2732 10年2か月（例：平28.4.1〜令8.5.31）", dt.date(2016, 4, 1), dt.date(2026, 5, 31), 11),
        ("TA2732 29年2か月（例：平9.4.1〜令8.5.31）", dt.date(1997, 4, 1), dt.date(2026, 5, 31), 30),
        ("TA2740 4年2か月（例：令4.4.1〜令8.5.31）", dt.date(2022, 4, 1), dt.date(2026, 5, 31), 5),
        ("TA2741 A社 役員 令4.5.1〜令8.5.31（4年1か月）", dt.date(2022, 5, 1), dt.date(2026, 5, 31), 5),
        ("TA2741 B社 使用人 令4.8.1〜令8.5.31（3年10か月）", dt.date(2022, 8, 1), dt.date(2026, 5, 31), 4),
        ("TA2741 A社 使用人 令3.2.1〜令8.1.31（5年）", dt.date(2021, 2, 1), dt.date(2026, 1, 31), 5),
        ("境目：ちょうど5年（令3.4.1〜令8.3.31）", dt.date(2021, 4, 1), dt.date(2026, 3, 31), 5),
        ("境目：5年と1日（令3.4.1〜令8.4.1）", dt.date(2021, 4, 1), dt.date(2026, 4, 1), 6),
    ]:
        got, parts = kinzoku_years(s, e)
        c3.append({"case": label, "start": s.isoformat(), "end": e.isoformat(), "y_m_d": parts, "expect": expect, "got": got, "ok": got == expect})
    res["checks"]["C3_kinzoku"] = c3

    # C4 退職所得の金額
    c4 = []
    def add4(label, got, expect):
        c4.append({"case": label, "expect": expect, "got": got, "ok": got == expect})
    add4("TA1420 例1 控除額 11年", taishoku_kojo(11), 4_400_000)
    add4("TA1420 例2 控除額 30年", taishoku_kojo(30), 15_000_000)
    add4("TA2732 例1 (800万−440万)×1/2", taishoku_shotoku(8_000_000, taishoku_kojo(11), "ippan"), 1_800_000)
    add4("TA2732 例2 (2,300万−1,500万)×1/2", taishoku_shotoku(23_000_000, taishoku_kojo(30), "ippan"), 4_000_000)
    add4("TA2740 短期 800万・5年", taishoku_shotoku(8_000_000, taishoku_kojo(5), "tanki"), 4_500_000)
    add4("TA2737 例1 特定役員 500万・5年", taishoku_shotoku(5_000_000, taishoku_kojo(5), "tokutei_yakuin"), 3_000_000)
    v, d = ippan_plus_tokutei(8_000_000, 5_000_000, 13, 3, 0)
    add4("TA2737 例2 使用人800万＋役員500万・13年（役員3年）", v, 5_800_000)
    v, d = ippan_plus_tokutei(8_000_000, 5_000_000, 15, 5, 3)
    add4("TA2737 例3 重複3年（兼務役員）・15年（役員等5年）", v, 5_300_000)
    v, d = tanki_plus_tokutei(5_000_000, 15_000_000, 5, 5, 4)
    add4("TA2741 短期500万（4年）＋特定役員1,500万（5年）・重複4年", v, 16_500_000)
    add4("TA2741 同 特定役員退職所得控除額", d["特定役員退職所得控除額"], 1_200_000)
    add4("TA2741 同 短期退職所得控除額", d["短期退職所得控除額"], 800_000)
    add4("80万円の最低保障（勤続1年）", taishoku_kojo(1), 800_000)
    add4("障害退職（勤続1年）＝80万円＋100万円", taishoku_kojo(1, disability=True), 1_800_000)
    res["checks"]["C4_shotoku"] = c4

    # C5 源泉徴収税額
    c5 = []
    def add5(label, got, expect):
        c5.append({"case": label, "expect": expect, "got": got, "ok": got == expect})
    add5("TA2732 例1 課税退職所得180万円", gensen_with_shinkokusho(1_800_000)[1], 91_890)
    add5("TA2732 例2 課税退職所得400万円", gensen_with_shinkokusho(4_000_000)[1], 380_322)
    add5("TA2732 別紙の注 課税退職所得700万円", gensen_with_shinkokusho(7_000_000)[1], 994_454)
    add5("TA2732 申告書なし 800万円×20.42%", gensen_without_shinkokusho(8_000_000), 1_633_600)
    a_tax = gensen_with_shinkokusho(taishoku_shotoku(4_000_000, taishoku_kojo(9), "ippan"))[1]
    add5("TA2735 A社 (400万−360万)×1/2＝20万", a_tax, 10_210)
    b_total = gensen_with_shinkokusho(taishoku_shotoku(4_000_000 + 1_800_000, taishoku_kojo(10), "ippan"))[1]
    add5("TA2735 B社 合計で90万円の税額", b_total, 45_945)
    add5("TA2735 B社 差引", b_total - a_tax, 35_735)
    res["checks"]["C5_gensen"] = c5

    # C6 住民税（総務省の早見表 p.1〜2 から目視で転記した行。(から, まで, 市町村民税, 道府県民税)）
    hayami = [
        (0, 3_999, 0, 0), (4_000, 5_999, 100, 0), (6_000, 7_999, 100, 100), (8_000, 9_999, 200, 100),
        (10_000, 13_999, 300, 200), (20_000, 23_999, 600, 400), (100_000, 103_999, 3_000, 2_000),
        (104_000, 105_999, 3_100, 2_000), (106_000, 107_999, 3_100, 2_100), (198_000, 199_999, 5_900, 3_900),
        (200_000, 203_999, 6_000, 4_000), (298_000, 299_999, 8_900, 5_900), (300_000, 303_999, 9_000, 6_000),
        (398_000, 399_999, 11_900, 7_900),
    ]
    c6 = []
    for lo, hi, ec, ep in hayami:
        for x in (lo, hi):
            base, city, pref = juminzei_bunri(x)
            c6.append({"before_half": x, "base": base, "expect": [ec, ep], "got": [city, pref], "ok": [city, pref] == [ec, ep]})
    ex = juminzei_bunri(8_000_000 - taishoku_kojo(11))
    res["checks"]["C6_juminzei"] = {"hayami_rows": c6,
                                    "example_TA2732_ex1_payment_8m_11y": {"base": ex[0], "city": ex[1], "pref": ex[2]}}

    # C7 所令70①二 改正前後
    cases = c7_cases()
    diff = [c for c in cases if not c["same"]]
    res["checks"]["C7_rei70"] = {"n_cases": len(cases), "n_diff": len(diff),
                                 "diff_years": sorted({c["year"] for c in diff}),
                                 "first_diff_year": min((c["year"] for c in diff), default=None),
                                 "diff_examples": diff[:20],
                                 "same_for_2025_2026": all(c["same"] for c in cases if c["year"] in (2025, 2026))}

    # C8 合計所得金額
    c8 = []
    # 作成コーナー FAQ（令和7年分 scid1322）：給与所得10万円・退職所得40万円・不動産所得30万円
    kyuyo, taishoku, fudosan = 100_000, 400_000, 300_000
    c8.append({"case": "作成コーナー scid1322 住民税（源泉徴収された退職所得を除く）", "expect": 400_000, "got": kyuyo + fudosan,
               "ok": kyuyo + fudosan == 400_000})
    c8.append({"case": "同じ人の所得税の合計所得金額（所法2①三十イ(2)：退職所得金額を含む）", "expect": None, "got": kyuyo + taishoku + fudosan})
    # 質疑応答事例 shotoku/05/85：給与所得105万円＋退職所得30万円＝135万円 > 133万円
    c8.append({"case": "質疑応答 05/85 配偶者特別控除の判定", "expect": 1_350_000, "got": 1_050_000 + 300_000,
               "over_1_33m": 1_050_000 + 300_000 > 1_330_000, "ok": 1_050_000 + 300_000 == 1_350_000})
    c8.append({"case": "同上の退職所得 30万円＝(300万円−控除)×1/2 から逆算した控除額", "kojo_implied": 3_000_000 - 2 * 300_000,
               "years_if_40man": (3_000_000 - 2 * 300_000) / 400_000})
    res["checks"]["C8_gokei"] = c8

    # C9 基準額・文言の抽出
    c9 = {"shotoku_2_32_kinro": {}, "chiho_292_7_9": {}, "chiho_fusoku_3_3_excl": {}}
    for asof in ["2024-12-31", "2025-12-31", "2026-11-09", "2026-12-31", "2027-01-01"]:
        t = (EG / f"shotoku_{asof}.txt").read_text(encoding="utf-8")
        m = re.search(r"三十二　勤労学生.*?退職所得又は雑所得（以下この号において「給与所得等」という。）.*?合計所得金額が(.{1,8}?)以下であり", t)
        c9["shotoku_2_32_kinro"][asof] = m.group(1) if m else None
    for asof in ["2026-01-01", "2026-11-09", "2027-01-01"]:
        t = (EG / f"chiho_{asof}.txt").read_text(encoding="utf-8")
        s292 = t[t.index("## Num=292"):]
        m7 = re.search(r"七　同一生計配偶者.*?合計所得金額が(.{1,8}?)以下", s292)
        m9 = re.search(r"九　扶養親族.*?合計所得金額が(.{1,8}?)以下", s292)
        c9["chiho_292_7_9"][asof] = [m7.group(1) if m7 else None, m9.group(1) if m9 else None]
        s33 = t[t.index("## 原始附則 Num=3_3"):]
        c9["chiho_fusoku_3_3_excl"][asof] = {
            "道府県民税の所得割（第五十条の二の規定により課する所得割を除く。": "道府県民税の所得割（第五十条の二の規定により課する所得割を除く。" in s33,
            "市町村民税の所得割（分離課税に係る所得割を除く。": "市町村民税の所得割（分離課税に係る所得割を除く。" in s33}
    res["checks"]["C9_text"] = c9

    # 集計
    summ = []
    def ok_all(lst):
        return all(x.get("ok", True) for x in lst)
    summ.append(f"C1 別表第六: " + "; ".join(f"{c['asof']} 行{c['rows_checked']} 不一致{len(c['mismatches'])} 41年以上の文{c['row_41_plus_text_found']}" for c in c1))
    summ.append(f"C2 税率表→速算表の控除額（7区分）一致: {res['checks']['C2_rate_table']['match_all']}  計算値={[q['deduction'] for q in quick]}")
    summ.append(f"C3 勤続年数 全一致: {ok_all(c3)}")
    summ.append(f"C4 退職所得の金額 全一致: {ok_all(c4)}")
    summ.append(f"C5 源泉徴収税額 全一致: {ok_all(c5)}")
    summ.append(f"C6 住民税 早見表の行 全一致: {ok_all(c6)}  TA2732例1の支払の住民税={res['checks']['C6_juminzei']['example_TA2732_ex1_payment_8m_11y']}")
    summ.append(f"C7 所令70①二 改正前後: 組合せ{len(cases)} 違い{len(diff)} 違いが出る年={res['checks']['C7_rei70']['diff_years']} 最初={res['checks']['C7_rei70']['first_diff_year']} 2025・2026年は同じ={res['checks']['C7_rei70']['same_for_2025_2026']}")
    summ.append(f"C8 合計所得金額の設例 全一致: {ok_all(c8)}")
    summ.append(f"C9 所法2①三十二（勤労学生）: {c9['shotoku_2_32_kinro']}")
    summ.append(f"C9 地法292①七・九: {c9['chiho_292_7_9']}")
    summ.append(f"C9 地法附則3の3 分離課税を除く: {c9['chiho_fusoku_3_3_excl']}")
    (OUT / "checks.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (OUT / "summary.txt").write_text("\n".join(summ) + "\n", encoding="utf-8")
    print("\n".join(summ))


if __name__ == "__main__":
    sys.exit(main())

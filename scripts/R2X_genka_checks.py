"""R2X genka: 取得した条文・別表（scripts/results/R2X_genka_laws/）から、減価償却と損益通算の基準額・期限・文言を
機械的に読み取り、償却率表の性質と、仮説・推測の文書で使う計算例を出す。ネットワークは使わない。

実行（Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_genka_checks.py

入力：scripts/results/R2X_genka_laws/*.txt, taiyo_tables_*.json（scripts/R2X_genka_laws.py の出力）
出力：scripts/results/R2X_genka_checks/checks.json, checks.md

- 計算例の端数処理は、一次情報で決まっていないものがある（償却費の1円未満、事業専用割合を掛けた後、一括償却資産の1/3）。
  ここでは「切り捨て」「切り上げ」「端数のまま（分数）」を並べて出し、どれが正しいかは判断しない。
- 金額は整数（円）、率は整数の分数（fractions.Fraction）で扱う。
"""
import datetime as dt
import json
import pathlib
import re
from fractions import Fraction as F

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "scripts" / "results" / "R2X_genka_laws"
OUT = ROOT / "scripts" / "results" / "R2X_genka_checks"

KANSUJI = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def kan2int(s):
    """「一〇」「九五」のような位取りの漢数字、「十万」「三百万」「四十」のような単位つきの漢数字を整数にする。"""
    s = s.strip()
    if s and all(c in KANSUJI for c in s):
        n = 0
        for c in s:
            n = n * 10 + KANSUJI[c]
        return n
    total, sect, num = 0, 0, 0
    for c in s:
        if c in KANSUJI:
            num = KANSUJI[c]
        elif c == "十":
            sect += (num or 1) * 10
            num = 0
        elif c == "百":
            sect += (num or 1) * 100
            num = 0
        elif c == "千":
            sect += (num or 1) * 1000
            num = 0
        elif c == "万":
            total += (sect + num) * 10000
            sect, num = 0, 0
        else:
            raise ValueError(s)
    return total + sect + num


def kan_rate(s):
    """「〇・二五〇」→ Fraction(250, 1000)"""
    a, b = s.split("・")
    return F(kan2int(a) * 10 ** len(b) + kan2int(b), 10 ** len(b))


def read(name):
    return (SRC / name).read_text(encoding="utf-8")


def header(text):
    return text.splitlines()[1].lstrip("# ").strip()


def article(text, num):
    m = re.search(r"^## Num=%s\n(.*?)(?=^## )" % re.escape(num), text, re.S | re.M)
    return m.group(1) if m else ""


def found(pattern, text):
    m = re.search(pattern, text)
    return m.group(0) if m else None


# ---------------------------------------------------------------- 1. 文言と基準額
def check_values():
    res = {}
    # 所令138・139（令和7年分・令和8年分の版、2030-12-31 版）
    for asof in ("2025-12-31", "2026-12-31", "2030-12-31"):
        t = read(f"shotoku-rei_{asof}.txt")
        a138, a139, a132, a134 = article(t, "138"), article(t, "139"), article(t, "132"), article(t, "134")
        a85, a198, a125 = article(t, "85"), article(t, "198"), article(t, "125")
        a81 = article(t, "81")
        res[f"shotoku-rei@{asof}"] = {
            "version": header(t),
            "138_threshold": found(r"が[一二三四五六七八九十百千万]+円未満であるもの（貸付け", a138),
            "138_useful_life_lt_1y": "使用可能期間が一年未満" in a138,
            "138_excludes_lending": "貸付け（主要な業務として行われるものを除く。）の用に供したものを除く" in a138,
            "138_includes_zatsu": "雑所得" in a138,
            "139_threshold": found(r"取得価額が([一二三四五六七八九十百千万]+円)未満", a139),
            "139_three_years": "三年間" in a139 and "三で除して" in a139,
            "139_includes_zatsu": "雑所得" in a139,
            "132_month_rule": found(r"一月に満たない端数を生じたときは、これを一月とする", a132),
            "134_2_i_one_yen": found(r"その取得価額から一円を控除した金額", a134),
            "85_x1_5": found(r"耐用年数に一・五を乗じて", a85),
            "85_rounding": [found(r"一年未満の端数は、切り捨てる", a85), found(r"六月以上の端数は一年とし、六月に満たない端数は切り捨てる", a85)],
            "125_default_teigaku": found(r"第百二十条の二第一項第一号イ及び第二号（減価償却資産の償却の方法）に掲げる減価償却資産　定額法", a125),
            "81_lists": [found(r"第百三十八条第一項（少額の減価償却資産の取得価額の必要経費算入）", a81),
                         found(r"第百三十九条第一項（一括償却資産の必要経費算入）", a81),
                         "租税特別措置法" in a81 or "第二十八条の二" in a81],
            "198_item3_conj": found(r"譲渡所得の金額(及び|又は)一時所得の金額（前号", a198),
            "198_items": [ln.strip()[:2] for ln in a198.splitlines() if re.match(r"\s+[一二三四五六]　", ln)],
        }
    # 措法28の2（期限・限度額）
    for asof in ("2025-12-31", "2026-03-31", "2026-04-01", "2026-12-31", "2027-01-01", "2030-12-31"):
        t = read(f"sochi_{asof}.txt")
        a = article(t, "28_2")
        res[f"sochi@{asof}"] = {
            "version": header(t),
            "28_2_period": found(r"平成十八年四月一日から[^ま]+までの間", a),
            "28_2_upper": found(r"その取得価額が[一二三四五六七八九十百千万]+円未満", a),
            "28_2_annual_cap": found(r"合計額が三百万円", a),
            "28_2_blue_only": "青色申告書を提出するもの" in a,
            "28_2_income_types": found(r"不動産所得、事業所得又は山林所得を生ずべき業務の用に供した", a),
            "28_2_attach": found(r"確定申告書に少額減価償却資産の取得価額に関する明細書の添付がある場合に限り", a),
        }
    for asof in ("2025-12-31", "2026-03-31", "2026-04-01", "2026-12-31", "2030-12-31"):
        t = read(f"sochi-rei_{asof}.txt")
        a = article(t, "18_5")
        a53 = article(t, "5_3")
        res[f"sochi-rei@{asof}"] = {
            "version": header(t),
            "18_5_employees": found(r"常時使用する従業員の数が[一二三四五六七八九十百千]+人以下の個人", a),
            "5_3_chusho": found(r"常時使用する従業員の数が[一二三四五六七八九十百千]+人以下の個人", a53),
        }
    # 所法69・70・2①二十五・51
    for asof in ("2025-12-31", "2026-12-31", "2027-01-01", "2030-12-31"):
        t = read(f"shotoku_{asof}.txt")
        a2, a69, a70, a51 = article(t, "2"), article(t, "69"), article(t, "70"), article(t, "51")
        res[f"shotoku@{asof}"] = {
            "version": header(t),
            "2_19": found(r"十九　減価償却資産　[^\n]+", a2),
            "2_25": found(r"二十五　純損失の金額　[^\n]+", a2),
            "69_1_targets": found(r"不動産所得の金額、事業所得の金額、山林所得の金額又は譲渡所得の金額の計算上生じた損失の金額", a69),
            "70_1_blue_3y": bool(re.search(r"前年以前三年内の各年（その年分の所得税につき青色申告書を提出している年に限る。）", a70)),
            "70_2_kinds": [found(r"変動所得の金額の計算上生じた損失の金額", a70), found(r"被災事業用資産の損失の金額", a70)],
            "70_4_continuous": found(r"その後において連続して確定申告書を提出している場合に限り", a70),
            "51_1_jigyo": found(r"不動産所得、事業所得又は山林所得を生ずべき事業の用に供される固定資産", a51),
            "51_4_limit": found(r"不動産所得の金額又は雑所得の金額（この項の規定を適用しないで計算したこれらの所得の金額とする。）を限度として", a51),
        }
    return res


# ---------------------------------------------------------------- 2. 別表（耐用年数・償却率）
def load_tables(asof):
    return json.loads((SRC / f"taiyo_tables_{asof}.json").read_text(encoding="utf-8"))


def teigaku_rates(tables):
    t8 = next(t for t in tables["tables"] if "別表第八" in t["title"])
    rates = {}
    for row in t8["structs"][0]["rows"]:
        if len(row) >= 2 and row[0] and all(c in KANSUJI for c in row[0]) and "・" in row[1]:
            rates[kan2int(row[0])] = kan_rate(row[1])
    return rates


def check_rates(rates):
    """別表第八の値が「1/耐用年数 を小数第3位に切り上げた値」と一致するかを確かめる（表が正。式は検査用の性質）。"""
    mism = []
    for n, r in sorted(rates.items()):
        ceil3 = F(-(-1000 // n), 1000)
        if r != ceil3:
            mism.append({"years": n, "table": str(r), "ceil(1000/n)/1000": str(ceil3)})
    return {"count": len(rates), "min_years": min(rates), "max_years": max(rates), "mismatch_vs_ceil": mism,
            "sample": {n: f"{float(rates[n]):.3f}" for n in (2, 3, 4, 5, 6, 8, 10, 15, 20) if n in rates}}


def appendix_rows(tables, title_kw, keywords):
    """別表の行のうち、細目にキーワードを含む行と、その直前の「年数の空いた見出し行」を返す。
    e-Gov の表では種類・構造又は用途の列が空のことがあるので、直前の空でない値を引き継いで表示する。"""
    t = next(x for x in tables["tables"] if title_kw in x["title"])
    out = []
    cur = ["", ""]
    heads = []
    for row in t["structs"][0]["rows"]:
        if len(row) < 3:
            continue
        if row[0]:
            cur[0], heads = row[0], []
        if len(row) >= 4 and row[1]:
            cur[1], heads = row[1], []
        detail, years = (row[2], row[3]) if len(row) >= 4 else (row[1], row[2])
        if not years:
            heads = [detail]  # 年数の空いた行は、次の行群の見出し
            continue
        if any(k in detail for k in keywords) or any(k in "".join(heads) for k in keywords):
            out.append({"種類": cur[0], "構造又は用途": cur[1] if len(row) >= 4 else "", "直前の年数の空いた行（階層は推定しない）": heads[0] if heads else "",
                        "細目": detail, "耐用年数": kan2int(years) if all(c in KANSUJI for c in years) else years})
    return out


# ---------------------------------------------------------------- 3. 計算例
def months_in_service(start: dt.date, year: int):
    """所令132①一・②：業務の用に供した日からその年12月31日までの月数（1月未満の端数は1月）。暦に従う。"""
    if start.year < year:
        return 12
    if start.year > year:
        return 0
    return 12 - start.month + 1  # 供用した月を1月として数える（1日でも月の途中でも1月）


def months_by_calendar(start: dt.date, end: dt.date):
    """暦に従って start から end（両端を含む）までの月数を数え、1月に満たない端数を1月とする（所令132②）。
    k か月の期間の末日は、起算日に応当する日の前日（応当する日がない月は、その月の末日。民法143②の考え方）。
    end を末日が初めて越える k を返す。months_in_service の検査用（独立に数える）。"""
    import calendar
    k = 0
    while True:
        k += 1
        y, m = start.year + (start.month - 1 + k) // 12, (start.month - 1 + k) % 12 + 1
        last = calendar.monthrange(y, m)[1]
        if start.day <= last:
            period_end = dt.date(y, m, start.day) - dt.timedelta(days=1)
        else:
            period_end = dt.date(y, m, last)
        if period_end >= end:
            return k


def check_months(year=2026):
    mism = []
    d = dt.date(year, 1, 1)
    while d.year == year:
        a, b = months_in_service(d, year), months_by_calendar(d, dt.date(year, 12, 31))
        if a != b:
            mism.append({"start": d.isoformat(), "months_in_service": a, "by_calendar": b})
        d += dt.timedelta(days=1)
    return {"year": year, "days_checked": (dt.date(year, 12, 31) - dt.date(year, 1, 1)).days + 1, "mismatch": mism}


def old_teigaku_rates(tables):
    """別表第七（平成十九年三月三十一日以前に取得をされた減価償却資産の償却率表）の旧定額法の償却率。
    所令85（非業務用期間の減価の額）は、取得時期にかかわらず旧定額法に準じて計算するので、この表を使う。"""
    t7 = next(t for t in tables["tables"] if "別表第七" in t["title"])
    rates = {}
    for row in t7["structs"][0]["rows"]:
        if len(row) >= 2 and row[0] and all(c in KANSUJI for c in row[0]) and "・" in row[1]:
            rates[kan2int(row[0])] = kan_rate(row[1])
    return rates


def years_elapsed_6m(start: dt.date, end: dt.date):
    """所令85②二：期間に係る年数は、六月以上の端数は一年とし、六月に満たない端数は切り捨てる。
    start から end の前日までを暦で数えた満月数から年数を出す（日の端数は切り捨てて月数を数える単純化）。"""
    months = (end.year - start.year) * 12 + (end.month - start.month) - (1 if end.day < start.day else 0)
    y, m = divmod(months, 12)
    return y + (1 if m >= 6 else 0), months


def conversion_example(cost, legal_years, acquired, converted, old_rates, new_rates, until_year):
    """非業務用資産を業務の用に供した場合（所令135・所令85）：
    非業務用期間の減価の額 = 取得価額 × 0.9（旧定額法の償却の基礎。残存価額10%） × 旧定額法償却率(floor(耐用年数×1.5)) × 年数。
    ※「取得価額×0.9」は質疑応答事例 04/17 の算式（旧定額法に準じる）。所令85 の文言は「旧定額法に準じて計算」。
    業務の用に供した後は、取得価額×定額法償却率×月数/12 を、未償却残額が1円になるまで（仮説 H5 の読み方）。"""
    y15 = (legal_years * 3) // 2  # 一・五を乗じた年数の1年未満の端数は切り捨て（所令85②一）
    yrs, months = years_elapsed_6m(acquired, converted)
    genka = F(cost) * F(9, 10) * old_rates[y15] * yrs
    rows = []
    remaining = F(cost) - genka
    for y in range(converted.year, until_year + 1):
        m = months_in_service(converted, y)
        raw = F(cost) * new_rates[legal_years] * F(m, 12)
        v = min(raw, remaining - 1)
        v = max(v, F(0))
        remaining -= v
        rows.append({"year": y, "months": m, "償却費": str(v), "期末未償却残高": str(remaining)})
    return {"cost": cost, "法定耐用年数": legal_years, "1.5倍の年数": y15, "旧定額法償却率": str(old_rates[y15]),
            "取得日": acquired.isoformat(), "業務供用日": converted.isoformat(), "経過の満月数": months, "所令85の年数": yrs,
            "減価の額": str(genka), "業務供用時の未償却残額": str(F(cost) - genka), "rows": rows}


def disposal_option_equivalence():
    """業務に係る雑所得で、年の中途で除却した資産について、
    (a) その年の償却費（dep）を計算してから、残り（loss）を所法51④の上限つきで必要経費にする場合と、
    (b) 償却費の計算を省略して、dep+loss の全額を所法51④の上限つきで必要経費にする場合（手引き 30(4)）とで、
    雑所得の金額が変わるかを総当たりで比べる。A はこの資産の項目を入れる前の雑所得の金額（負もありうる）。
    所法51④の上限は「この項の規定を適用しないで計算した雑所得の金額」で、負なら上限 0 とした。"""
    mism, n = [], 0
    for A in range(-100_000, 300_001, 10_000):
        for dep in range(0, 100_001, 10_000):
            for loss in range(0, 150_001, 10_000):
                n += 1
                a_before = A - dep
                a = a_before - min(loss, max(a_before, 0))
                b = A - min(dep + loss, max(A, 0))
                if max(a, 0) != max(b, 0):
                    mism.append({"A": A, "dep": dep, "loss": loss, "a": a, "b": b})
    return {"cases": n, "mismatch_after_floor_0": mism[:20], "mismatch_count": len(mism)}


def round_variants(x: F):
    import math
    return {"切り捨て": math.floor(x), "切り上げ": math.ceil(x), "分数": str(x)}


def straight_line_schedule(cost, years, rates, start, until_year, business_ratio=F(1), intangible=False):
    """定額法（所令120の2①一イ(1)）＋月割（所令132）＋有形は1円まで（所令134①二イ）、無形は0円まで（同ロ）。端数は3通りで並べる。
    家事按分は「償却費全額を計算し、事業専用割合を掛けた額を必要経費」とする（仮説。収支内訳書の欄の構成）。"""
    rate = rates[years]
    rows = []
    acc = {"切り捨て": 0, "切り上げ": 0}
    for y in range(start.year, until_year + 1):
        m = months_in_service(start, y)
        raw = F(cost) * rate * F(m, 12)
        row = {"year": y, "months": m, "raw": str(raw)}
        for mode in ("切り捨て", "切り上げ"):
            v = round_variants(raw)[mode]
            v = min(v, cost - (0 if intangible else 1) - acc[mode])  # 有形は未償却残高が1円になるまで、無形は0円まで
            v = max(v, 0)
            acc[mode] += v
            biz = F(v) * business_ratio
            row[mode] = {"償却費": v, "必要経費（事業専用割合を掛けた額）": round_variants(biz) if biz.denominator != 1 else int(biz),
                         "期末未償却残高": cost - acc[mode]}
        rows.append(row)
    return {"cost": cost, "years": years, "rate": str(rate), "start": start.isoformat(), "business_ratio": str(business_ratio), "intangible": intangible, "rows": rows}


def ikkatsu(total):
    """所令139①：一括償却対象額 ÷ 3（各年）。端数の扱いは条文にない。"""
    raw = F(total, 3)
    return {"一括償却対象額": total, "各年": round_variants(raw),
            "切り捨てで3年の合計": (total // 3) * 3, "切り捨てで3年目に残りを寄せた場合の3年目": total - 2 * (total // 3)}


def sochi28_2_cap(months):
    """措法28の2①：300万円（業務の開始・廃止の年は 300万円÷12×月数。月数は暦に従い1月未満は1月＝同②）。"""
    return F(3_000_000, 12) * months


def sontsu(keijo_pos: dict, loss_jigyo: int, joto_short: int, joto_long: int, ichiji: int, sanrin=0, taishoku=0):
    """所令198 第1号・第3号・第5号の順（事業所得・不動産所得の損失だけがある場合）で損益通算し、総所得金額を出す。
    ichiji は特別控除（所法34③）後の一時所得の金額、joto_* は特別控除後の譲渡所得の金額（短期＝所法33③一、長期＝同二）。
    返り値の総所得金額は、所法22②一（経常＋短期譲渡）＋二（（長期譲渡＋一時）×1/2）。1/2 の端数は分数のまま返す。"""
    loss = -loss_jigyo
    steps = []
    keijo = sum(keijo_pos.values())
    d = min(loss, keijo); keijo -= d; loss -= d; steps.append(("経常所得", d))
    for name in ("短期譲渡", "長期譲渡", "一時"):
        v = {"短期譲渡": joto_short, "長期譲渡": joto_long, "一時": ichiji}[name]
        d = min(loss, v)
        v -= d; loss -= d; steps.append((name, d))
        if name == "短期譲渡": joto_short = v
        elif name == "長期譲渡": joto_long = v
        else: ichiji = v
    d = min(loss, sanrin); sanrin -= d; loss -= d; steps.append(("山林", d))
    d = min(loss, taishoku); taishoku -= d; loss -= d; steps.append(("退職", d))
    soshotoku = F(keijo + joto_short) + F(joto_long + ichiji, 2)
    return {"控除の順": steps, "経常所得（通算後）": keijo, "短期譲渡（通算後）": joto_short, "長期譲渡（通算後）": joto_long,
            "一時（通算後）": ichiji, "純損失（控除しきれない額）": loss, "総所得金額": str(soshotoku)}


def naive_sum(keijo_pos, loss_jigyo, joto_short, joto_long, ichiji):
    """順序を無視して、損失をそのまま合計に入れた場合（誤りの例。比較のため）。"""
    return str(F(sum(keijo_pos.values()) + loss_jigyo + joto_short) + F(joto_long + ichiji, 2))


def pdf_hashes():
    """Read ツールで読んだ PDF（信頼できないデータ）が、取得の記録の SHA-256 と同じものかを確かめる（読むだけ。実行しない）。"""
    import hashlib
    logs = [ROOT / "scripts/results/R2X_genka_nta/forms/fetch_log.json", ROOT / "scripts/results/R2X_genka_nta/ta2/fetch_log.json",
            ROOT / "scripts/results/IMPL_jigyo_nta/forms/fetch_log.json"]
    want = {"aoiro_kessan_kakikata_r07", "sonshitsu_tebiki_r07", "ta_2100_01", "ta_2100_02", "shushi_ippan_kakikata_r07", "kessan_tebiki_shiro_r07"}
    out = {}
    for lg in logs:
        for it in json.loads(lg.read_text(encoding="utf-8"))["items"]:
            if it["id"] in want:
                p = ROOT / it["saved"]
                got = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
                out[it["id"]] = {"saved": it["saved"], "url": it["url"], "last_modified": it.get("last_modified"),
                                 "recorded_sha256": it["sha256"], "local_sha256_matches": got == it["sha256"]}
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"generated_from": str(SRC.relative_to(ROOT)).replace("\\", "/")}
    res["pdf_hashes"] = pdf_hashes()
    res["months_rule_check"] = [check_months(2025), check_months(2026)]
    res["disposal_option_equivalence"] = disposal_option_equivalence()
    res["values"] = check_values()
    tabs = {asof: load_tables(asof) for asof in ("2025-12-31", "2026-12-31")}
    res["taiyo_versions"] = {a: t["law_revision_id"] for a, t in tabs.items()}
    rates = {a: teigaku_rates(t) for a, t in tabs.items()}
    res["teigaku_rates_same_r7_r8"] = rates["2025-12-31"] == rates["2026-12-31"]
    res["teigaku_rates_check"] = check_rates(rates["2026-12-31"])
    kw1 = ["パーソナルコンピュータ", "電子計算機", "カメラ", "複写機", "その他の事務機器", "ファクシミリ", "電話設備",
           "事務机", "音響機器", "冷房用", "二輪", "自転車", "小型車（総排気量が〇・六六", "報道通信用"]
    res["beppyo1_rows"] = appendix_rows(tabs["2026-12-31"], "別表第一", kw1)
    res["beppyo3_rows"] = appendix_rows(tabs["2026-12-31"], "別表第三", ["ソフトウエア", "複写して販売", "その他のもの"])
    r = rates["2026-12-31"]
    ex = {}
    # 例1：パソコン 240,000円、2026-07-15 に業務の用に供した、耐用年数4年、事業専用割合 6/10
    ex["E1_pc_240000_2026-07-15_4y_ratio_6_10"] = straight_line_schedule(240_000, 4, r, dt.date(2026, 7, 15), 2031, F(6, 10))
    # 例2：端数が出る取得価額（123,457円、2026-08-01、4年、事業専用割合 1/3）
    ex["E2_pc_123457_2026-08-01_4y_ratio_1_3"] = straight_line_schedule(123_457, 4, r, dt.date(2026, 8, 1), 2031, F(1, 3))
    # 例3：ソフトウエア（その他のもの）300,000円、2025-12-01、5年、専用
    ex["E3_soft_300000_2025-12-01_5y"] = straight_line_schedule(300_000, 5, r, dt.date(2025, 12, 1), 2031, intangible=True)
    # 例4：一括償却資産
    ex["E4_ikkatsu"] = [ikkatsu(150_000), ikkatsu(100_001), ikkatsu(199_999 + 150_000)]
    # 例5：措法28の2 の年300万円の上限（開業・廃業の年の月割）
    ex["E5_sochi28_2_cap"] = {m: str(sochi28_2_cap(m)) for m in (1, 5, 7, 12)}
    # 例6：損益通算（所令198）。事業所得の損失 −500,000、給与所得 300,000、雑所得 100,000、一時所得（特別控除後）200,000
    ex["E6_sontsu"] = {"correct": sontsu({"給与": 300_000, "雑": 100_000}, -500_000, 0, 0, 200_000),
                       "naive": naive_sum({"給与": 300_000, "雑": 100_000}, -500_000, 0, 0, 200_000)}
    # 例7：同じ数字で、損失が業務に係る雑所得の損失だった場合（所法69①の対象外 → 雑所得の中だけで通算、他の所得とは通算しない）
    ex["E7_zatsu_loss"] = {"雑所得（業務 −500,000 と その他 +100,000 の内部通算）": -400_000,
                           "総所得金額に入る雑所得": 0, "総所得金額": str(F(300_000) + F(200_000, 2))}
    # 例8：扶養の境目（令和7年分、合計所得金額 58万円以下）。給与所得 700,000 と 事業所得 −200,000 → 500,000、業務雑 −200,000 → 700,000
    ex["E8_fuyo_r7"] = {"事業所得の損失の場合の合計所得金額": 700_000 - 200_000, "業務に係る雑所得の損失の場合の合計所得金額": 700_000,
                        "要件（所法2①三十四、令和7年分）": 580_000}
    old = old_teigaku_rates(tabs["2026-12-31"])
    res["old_teigaku_rates_sample"] = {n: f"{float(old[n]):.3f}" for n in (2, 3, 4, 5, 6, 7, 8, 9, 10, 33) if n in old}
    # 例9：私用で買ったパソコン（200,000円、2024-05-10 取得）を 2026-07-01 から業務の用に供した（所令135・85）
    ex["E9_conversion_pc_200000"] = conversion_example(200_000, 4, dt.date(2024, 5, 10), dt.date(2026, 7, 1), old, r, 2030)
    # 例9の検算：質疑応答事例 04/17 の数字（30,000,000円、22年 → 33年、旧定額法 0.031、18年）
    ex["E9_check_shitsugi_04_17"] = {"33年の旧定額法償却率": str(old[33]), "減価の額（18年）": str(F(30_000_000) * F(9, 10) * old[33] * 18)}
    res["examples"] = ex
    (OUT / "checks.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    # 人が読む要約
    L = ["# R2X genka checks（自動生成。scripts/R2X_genka_checks.py）", ""]
    L.append("## 1. 文言と基準額（版ごと）")
    for k, v in res["values"].items():
        L.append(f"### {k}")
        for kk, vv in v.items():
            L.append(f"- {kk}: {vv}")
    L.append("")
    L.append("## 2. 別表第八（定額法の償却率）")
    L.append(f"- 耐用年数省令の版：{res['taiyo_versions']}")
    L.append(f"- 令和7年分と令和8年分の版で同じ：{res['teigaku_rates_same_r7_r8']}")
    L.append(f"- 性質の検査：{json.dumps(res['teigaku_rates_check'], ensure_ascii=False)}")
    L.append("")
    L.append("## 3. 別表第一・第三の行（抜粋）")
    for row in res["beppyo1_rows"] + res["beppyo3_rows"]:
        L.append(f"- {json.dumps(row, ensure_ascii=False)}")
    L.append("")
    L.append("## 4. 計算例")
    L.append("```json")
    L.append(json.dumps(ex, ensure_ascii=False, indent=1, default=str))
    L.append("```")
    (OUT / "checks.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("done", OUT)


if __name__ == "__main__":
    main()

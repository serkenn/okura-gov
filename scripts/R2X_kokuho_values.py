r"""R2X_kokuho: 取得した条文のテキスト（scripts/results/R2X_kokuho_egov/）から、国民健康保険料（税）と国民年金保険料の
年度ごとの値を機械的に取り出し、版ごとの表にする。あわせて、条文の式で値を計算し、公開資料（日本年金機構のページ）の値と照合する。

実行:
  C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe -I -X utf8 scripts/R2X_kokuho_values.py
標準ライブラリのみ。ネットワークには接続しない（入力は scripts/results/ の下のテキストと JSON だけ）。

入力
- scripts/results/R2X_kokuho_egov/articles_<略称>_<asof>.txt（scripts/R2X_kokuho_egov.py の出力）
- scripts/results/R2X_kokuho_web/nenkin_*.json、round2_*.json（scripts/R2X_kokuho_web.py の出力。抜き書きだけを使う）
- .work/text/<ts>_R2X_kokuho_web_nenkin/nk_menjo.txt（同じく scripts/R2X_kokuho_web.py が書く、ページのテキスト。C4 で使う。
  .work は git 管理外なので、検証し直すときは先に scripts/R2X_kokuho_web.py nenkin round2 を実行する）
出力
- scripts/results/R2X_kokuho_values/values.json：版ごとに取り出した値、計算結果、照合の結果
- scripts/results/R2X_kokuho_values/values.md：同じ内容の表
検査（失敗したら check に false を記録する。止めない）
- C1 国保令（料）と地方税法施行令（税）で、同じ版の賦課限度額・軽減の額が一致するか
- C2 国保令の軽減判定の基準額（地方税法第314条の2第2項第1号の額）が 43万円か（地方税法本文から取り出した値と照合）
- C3 国民年金保険料の月額＝17,000円×保険料改定率（第87条第3項の端数処理）が日本年金機構のページの額と一致するか
- C4 一部免除の納付額（第90条の2第6項の端数処理）が日本年金機構のページの額と一致するか
"""
import json
import pathlib
import re
from fractions import Fraction

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "scripts" / "results" / "R2X_kokuho_egov"
WEB = ROOT / "scripts" / "results" / "R2X_kokuho_web"
OUT = ROOT / "scripts" / "results" / "R2X_kokuho_values"
ASOFS = ["2025-04-01", "2026-04-01", "2026-11-09", "2027-04-01"]

DIG = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
UNIT_SMALL = {"十": 10, "百": 100, "千": 1000}
UNIT_BIG = {"万": 10_000, "億": 100_000_000}


def kanji_int(s):
    """漢数字（位取りの単位つき。例：三十万五千、二千四百五十万）を整数にする。"""
    total, section, num = 0, 0, 0
    for ch in s:
        if ch in DIG:
            num = DIG[ch]
        elif ch in UNIT_SMALL:
            section += (num or 1) * UNIT_SMALL[ch]
            num = 0
        elif ch in UNIT_BIG:
            section += num
            total += section * UNIT_BIG[ch]
            section, num = 0, 0
        else:
            raise ValueError(f"漢数字でない文字: {ch!r} in {s!r}")
    return total + section + num


def kanji_decimal(s):
    """「一・〇五四」のような小数（中点区切り、各桁は漢数字1文字）を Fraction にする。"""
    ip, fp = s.split("・")
    return Fraction(kanji_int(ip)) + Fraction(int("".join(str(DIG[c]) for c in fp)), 10 ** len(fp))


KNUM = "[〇一二三四五六七八九十百千万]+"


def section(text, start_pat, end_pat):
    m = re.search(start_pat, text, re.M)
    if not m:
        return ""
    rest = text[m.start():]
    e = re.search(end_pat, rest[1:], re.M)
    return rest[: e.start() + 1] if e else rest


def read(short, asof):
    p = SRC / f"articles_{short}_{asof}.txt"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def header(text):
    m = re.search(r"^# law_revision_id=(\S+) 改正法令=(\S+) 施行日=(\S+) 状態=(\S+)", text, re.M)
    return dict(zip(["law_revision_id", "amendment_law_num", "enforcement_date", "status"], m.groups())) if m else {}


def paragraph(sec, num_kanji_fullwidth):
    """条のテキストから、全角数字で始まる項（例 "２"）の範囲を返す。第1項は "（Paragraph1）"。"""
    if num_kanji_fullwidth == "1":
        start = r"^（Paragraph1）"
    else:
        start = r"^" + num_kanji_fullwidth + "　"
    return section(sec, start, r"^[２-９]　|^１[０-９]　|^## ")


def kokuho_rei_values(asof):
    t = read("kokuho-rei", asof)
    sec = section(t, r"^## Num=29_7$", r"^## Num=29_7_2$")
    out = {"source": header(t)}
    # 賦課限度額：「第三号の…賦課額は、X万円を超えることができない」
    lim = re.findall(r"第三号の(基礎賦課額|後期高齢者支援金等賦課額|介護納付金賦課額|子ども・子育て支援納付金賦課額)は、(" + KNUM + ")円を超えることができない", sec)
    out["limits"] = {k: kanji_int(v) for k, v in lim}
    # 減額賦課の項（第5項または第6項。版により項番号が違う）
    red = ""
    for p in ["５", "６"]:
        cand = paragraph(sec, p)
        if "減額賦課" in cand[:80]:
            red = cand
    out["reduction_paragraph"] = "第6項" if paragraph(sec, "６")[:80].find("減額賦課") >= 0 else ("第5項" if red else None)
    per_person = re.findall(r"合計数に(" + KNUM + ")円を乗じて得た金額を加算", red)
    out["reduction_per_person_amounts"] = sorted({kanji_int(x) for x in per_person})
    out["reduction_per_earner_add"] = sorted({kanji_int(x) for x in re.findall(r"一を減じた数に(" + KNUM + ")円を乗じて得た金額を加えた", red)})
    out["earner_salary_threshold"] = sorted({kanji_int(x) for x in re.findall(r"給与等の収入金額が(" + KNUM + ")円を超える者", red)})
    out["earner_pension_thresholds"] = sorted({kanji_int(x) for x in re.findall(r"公的年金等の収入金額が(" + KNUM + ")円を超える者", red)})
    out["reduction_ratios"] = re.findall(r"　(十分の[一二三四五六七八九])$", red, re.M)
    out["base_amount_ref"] = "地方税法第三百十四条の二第二項第一号に定める金額" if "地方税法第三百十四条の二第二項第一号に定める金額" in red else None
    out["preschool_reduction"] = bool(re.search(r"六歳に達する日以後の最初の三月三十一日以前である被保険者", red))
    # 未就学児の減額は、第6号（対象）の次の第7号（割合）。第7号の文で割合を取る
    m = re.search(r"七　前号の規定に基づき減額する額は、当該市町村の当該年度分の保険料に係る当該被保険者均等割額に(十分の[一二三四五六七八九])を乗じて得た額", red)
    out["preschool_ratio"] = m.group(1) if (m and out["preschool_reduction"]) else None
    out["childbirth_reduction"] = bool(re.search(r"出産する予定の被保険者又は出産した被保険者", red))
    m = re.search(r"出産予定月」という。）の前月（多胎妊娠の場合には、三月前）から出産予定月の翌々月までの期間", red)
    out["childbirth_period_text"] = m.group(0) if m else None
    out["under18_full_reduction"] = bool(re.search(r"十八歳未満被保険者", red))
    out["kodomo_component"] = "子ども・子育て支援納付金賦課額" in sec
    # 附則第5条（65歳以上の公的年金の15万円）
    m = re.search(r"から(" + KNUM + ")円を控除した金額）及び」と[^。]*「百十万円」とあるのは「(" + KNUM + ")円」", t)
    out["suppl5_pension_deduction"] = kanji_int(m.group(1)) if m else None
    out["suppl5_pension_threshold"] = kanji_int(m.group(2)) if m else None
    return out


def chiho_rei_values(asof):
    t = read("chiho-rei", asof)
    out = {"source": header(t)}
    s1 = section(t, r"^## Num=56_88_2$", r"^## Num=56_89$")
    out["limits_by_paragraph"] = [kanji_int(x) for x in re.findall(r"政令で定める金額は、(" + KNUM + ")円とする", s1)]
    s2 = section(t, r"^## Num=56_89$", r"^# ----|^## ")
    p1 = paragraph(s2, "1")
    out["base_amount"] = sorted({kanji_int(x) for x in re.findall(r"金額は、(" + KNUM + ")円（", p1)})
    out["reduction_per_person_amounts"] = sorted({kanji_int(x) for x in re.findall(r"合計数に(" + KNUM + ")円を乗じて得た金額を加算", s2)})
    out["reduction_per_earner_add"] = sorted({kanji_int(x) for x in re.findall(r"一を減じた数に(" + KNUM + ")円を乗じて得た金額を加算", s2)})
    out["earner_salary_threshold"] = sorted({kanji_int(x) for x in re.findall(r"給与等の収入金額が(" + KNUM + ")円を超える者", s2)})
    out["earner_pension_thresholds"] = sorted({kanji_int(x) for x in re.findall(r"公的年金等の収入金額が(" + KNUM + ")円を超える者", s2)})
    out["reduction_ratios"] = re.findall(r"　(十分の[一二三四五六七八九])$", s2, re.M)
    # 第3項（未就学児。法第703条の5第2項の基準）の第2号の割合
    p3 = paragraph(s2, "３")
    m = re.search(r"被保険者均等割額に(十分の[一二三四五六七八九])を乗じて得た額を基準として定めた額とすること", p3)
    out["preschool_ratio"] = m.group(1) if (m and "六歳に達する日" in p3) else None
    m = re.search(r"同条第一項中「百十万円」とあるのは「(" + KNUM + ")円」", t)
    out["suppl18_8_pension_threshold"] = kanji_int(m.group(1)) if m else None
    s3 = section(t, r"^## Num=6_17$", r"^## Num=56_88_2$")
    out["rounding_exceptions_mention_kokuho"] = "国民健康保険税" in s3
    return out


def chiho_values(asof):
    t = read("chiho", asof)
    out = {"source": header(t)}
    s = section(t, r"^## Num=314_2$", r"^# ----|^## 附則")
    p2 = paragraph(s, "２")
    out["juminzei_basic_deduction"] = [(kanji_int(a), kanji_int(b)) for a, b in
                                       re.findall(r"合計所得金額が(?:" + KNUM + "円を超え)?(" + KNUM + ")円以下である場合　(" + KNUM + ")円", p2)]
    s703 = section(t, r"^## Num=703_4$", r"^## Num=703_5$")
    out["deemed_householder_paragraph"] = bool(re.search(r"被保険者である資格がない世帯主の属する世帯内に被保険者がある場合には、当該世帯主を第一項の被保険者である世帯主とみなして", s703))
    out["kodomo_component"] = "子ども・子育て支援納付金課税額" in s703
    s705 = section(t, r"^## Num=705$", r"^## Num=706$")
    m = re.search(r"国民健康保険税の賦課期日は、(.+?)とする", s705)
    out["assessment_date"] = m.group(1) if m else None
    s20 = section(t, r"^## Num=20_4_2$", r"^## Num=703_4$")
    out["rounding_final_amount_100yen"] = bool(re.search(r"地方税の確定金額に百円未満の端数があるとき", s20))
    # 第703条の5第2項（子の被保険者均等割額の減額）の対象年齢
    s7035 = section(t, r"^## Num=703_5$", r"^## Num=703_5_2$")
    m = re.search(r"^２　市町村は、国民健康保険税の納税義務者の属する世帯内に(六|十八)歳に達する日以後の最初の三月三十一日以前である被保険者", s7035, re.M)
    out["child_equal_reduction_age_703_5_2"] = (m.group(1) + "歳") if m else None
    return out


def kokuho_values(asof):
    t = read("kokuho", asof)
    out = {"source": header(t)}
    s = section(t, r"^## Num=72_3_2$", r"^## Num=76$")
    m = re.search(r"一般会計から、(六|十八)歳に達する日以後の最初の三月三十一日以前である被保険者について", s)
    out["child_equal_reduction_age_72_3_2"] = (m.group(1) + "歳") if m else None
    s76 = section(t, r"^## Num=76$", r"^## Num=76_2$")
    out["kodomo_in_76"] = "子ども・子育て支援納付金" in s76
    return out


def kokunen_values(asof):
    t = read("kokunen", asof)
    out = {"source": header(t)}
    s87 = section(t, r"^## Num=87$", r"^## Num=87_2$")
    m = re.search(r"令和元年度以後の年度に属する月の月分 \| (" + KNUM + ")円", s87)
    out["base_monthly_from_R1"] = kanji_int(m.group(1)) if m else None
    out["rounding_rule_87_3"] = bool(re.search(r"五円未満の端数が生じたときは、これを切り捨て、五円以上十円未満の端数が生じたときは、これを十円に切り上げる", s87))
    s872 = section(t, r"^## Num=87_2$", r"^## Num=88$")
    m = re.search(r"ほか、(" + KNUM + ")円の保険料", s872)
    out["fuka_monthly"] = kanji_int(m.group(1)) if m else None
    out["has_88_3_childcare"] = "## Num=88_3: 見つからない" not in t
    out["deferral_periods"] = re.findall(r"(平成[^　（]{1,8}年[^　（]{1,3}月)から((?:令和|平成)[^　（]{1,8}年[^　（]{1,3}月)までの期間において、(五十|三十)歳に達する日", t)
    s902 = section(t, r"^## Num=90_2$", r"^## Num=90_3$")
    out["rounding_rule_90_2_6"] = bool(re.search(r"残余の額に五円未満の端数が生じたときは、これを切り捨て、五円以上十円未満の端数が生じたときは、これを十円に切り上げる", s902))
    return out


def kokunen_rei_values(asof):
    t = read("kokunen-rei", asof)
    out = {"source": header(t)}
    s67 = section(t, r"^## Num=6_7$", r"^## Num=6_7_2$")
    m = re.search(r"数に一を加えた数を(" + KNUM + ")円に乗じて得た額に(" + KNUM + ")円を加算", s67)
    out["full_exemption"] = {"per_head": kanji_int(m.group(1)), "add": kanji_int(m.group(2))} if m else None
    for key, num, nxt in [("three_quarter", "6_8_2", "6_9"), ("half_and_student", "6_9", "6_9_2"), ("quarter", "6_9_2", "6_10")]:
        s = section(t, r"^## Num=" + num + "$", r"^## Num=" + nxt + "$")
        m = re.search(r"扶養親族等がないときは(" + KNUM + ")円", s)
        adds = re.findall(r"一人につき(" + KNUM + ")円", s)
        out[key] = {"base": kanji_int(m.group(1)) if m else None, "per_dependent": [kanji_int(x) for x in adds]}
    s68 = section(t, r"^## Num=6_8$", r"^## Num=6_8_2$")
    m = re.search(r"政令で定める額は、(" + KNUM + ")円とする", s68)
    out["disabled_widow_single_parent_limit"] = kanji_int(m.group(1)) if m else None
    s612 = section(t, r"^## Num=6_12$", r"^# ----|^## 附則")
    out["6_12_includes_tokutei_shinzoku"] = "特定親族特別控除額" in s612
    return out


def kaiteiritsu_values(asof):
    t = read("kaiteiritsu", asof)
    out = {"source": header(t)}
    rates = re.findall(r"(令和" + KNUM + "年度)における国民年金法第八十七条第三項の保険料改定率は、([〇一二三四五六七八九]・[〇一二三四五六七八九]+)とする", t)
    out["premium_rates"] = {y: str(kanji_decimal(r)) for y, r in rates}
    return out


def round_87(x: Fraction) -> int:
    """国民年金法第87条第3項：5円未満切捨て、5円以上10円未満は10円に切上げ（＝10円単位の四捨五入。負の値は扱わない）。"""
    yen = int(x)  # 1円未満は、条文の「端数」の定義上どう扱うか書かれていないので、ここでは整数部で判定する（下の注を参照）
    r = yen % 10
    return yen - r + (10 if r >= 5 else 0)


def web_snippets():
    res = {}
    for p in sorted(WEB.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        for it in d.get("items", []):
            res[it["id"]] = {"file": str(p.relative_to(ROOT)), "url": it.get("url"), "status": it.get("status"),
                             "fetched_at": it.get("fetched_at"), "snippets": it.get("snippets", {})}
    return res


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"inputs": str(SRC.relative_to(ROOT)), "versions": {}, "checks": [], "computed": {}}
    for a in ASOFS:
        res["versions"][a] = {
            "kokuho-rei": kokuho_rei_values(a),
            "chiho-rei": chiho_rei_values(a),
            "chiho": chiho_values(a),
            "kokuho": kokuho_values(a),
            "kokunen": kokunen_values(a),
            "kokunen-rei": kokunen_rei_values(a),
            "kaiteiritsu": kaiteiritsu_values(a),
        }
    # C1：料と税の一致
    for a in ASOFS:
        k = res["versions"][a]["kokuho-rei"]
        c = res["versions"][a]["chiho-rei"]
        lim_k = [k["limits"].get(x) for x in ["基礎賦課額", "後期高齢者支援金等賦課額", "介護納付金賦課額", "子ども・子育て支援納付金賦課額"]]
        lim_c = c["limits_by_paragraph"] + [None] * (4 - len(c["limits_by_paragraph"]))
        ok = (lim_k == lim_c and k["reduction_per_person_amounts"] == c["reduction_per_person_amounts"]
              and k["reduction_per_earner_add"] == c["reduction_per_earner_add"]
              and k["earner_salary_threshold"] == c["earner_salary_threshold"]
              and k["earner_pension_thresholds"] == c["earner_pension_thresholds"]
              and k["preschool_ratio"] == c["preschool_ratio"]
              and k["suppl5_pension_threshold"] == c["suppl18_8_pension_threshold"])
        res["checks"].append({"id": "C1", "asof": a, "ok": ok, "kokuho_limits": lim_k, "chiho_limits": lim_c,
                              "kokuho_per_person": k["reduction_per_person_amounts"], "chiho_per_person": c["reduction_per_person_amounts"]})
    # C2：314条の2第2項第1号の額
    for a in ASOFS:
        bd = res["versions"][a]["chiho"]["juminzei_basic_deduction"]
        first = bd[0][1] if bd else None
        tax_base = res["versions"][a]["chiho-rei"]["base_amount"]
        res["checks"].append({"id": "C2", "asof": a, "ok": first == 430_000 and tax_base == [430_000],
                              "chiho_314_2_2_1": first, "chiho_rei_56_89_1_base": tax_base})
    # C3：国民年金保険料の月額
    base = res["versions"]["2026-11-09"]["kokunen"]["base_monthly_from_R1"]
    rates = {}
    for a in ASOFS:
        rates.update(res["versions"][a]["kaiteiritsu"]["premium_rates"])
    monthly = {}
    for y, r in sorted(rates.items(), key=lambda kv: kanji_int(kv[0][2:-2])):
        exact = Fraction(base) * Fraction(r)
        monthly[y] = {"rate": r, "exact": str(exact), "exact_float": float(exact), "monthly": round_87(exact)}
    res["computed"]["kokunen_monthly"] = monthly
    web = web_snippets()
    res["computed"]["web_snippets_used"] = {k: web[k] for k in ["nk_hokenryo", "nk_menjo", "nk_zenno"] if k in web}
    hk = " ".join(sum(web.get("nk_hokenryo", {}).get("snippets", {}).values(), []))
    zn = " ".join(sum(web.get("nk_zenno", {}).get("snippets", {}).values(), []))
    for y, expect_text, src in [("令和八年度", "17,920円（令和8年度）", hk), ("令和九年度", "令和9年度保険料18,290円", zn)]:
        if y in monthly:
            ok = expect_text in src and f"{monthly[y]['monthly']:,}" in expect_text
            res["checks"].append({"id": "C3", "year": y, "computed": monthly[y]["monthly"], "web_text": expect_text, "found_in_web": expect_text in src, "ok": ok})
    # C4：一部免除の納付額（令和8年度）
    mn = " ".join(sum(web.get("nk_menjo", {}).get("snippets", {}).values(), []))
    full = Fraction(monthly.get("令和八年度", {}).get("monthly", 0))
    partial = {}
    for name, exempt in [("4分の3免除", Fraction(3, 4)), ("半額免除", Fraction(1, 2)), ("4分の1免除", Fraction(1, 4))]:
        remain = full - full * exempt
        partial[name] = round_87(remain)
    res["computed"]["kokunen_partial_R8"] = partial
    # 参考：各年度の一部免除の残りの額（残りの額そのものと、第90条の2第6項の端数処理の後）。照合はしていない
    partial_all = {}
    for y, m in monthly.items():
        f = Fraction(m["monthly"])
        partial_all[y] = {name: {"remain_exact": str(f - f * ex), "remain_float": float(f - f * ex), "rounded": round_87(f - f * ex)}
                          for name, ex in [("4分の3免除", Fraction(3, 4)), ("半額免除", Fraction(1, 2)), ("4分の1免除", Fraction(1, 4))]}
    res["computed"]["kokunen_partial_all_years"] = partial_all
    for name, v in partial.items():
        txt = f"{name}（納めた保険料額　{v:,}円：令和8年度）"
        # 抜き書きは語の前後120字なので、ページのテキストそのものを探す
        res["checks"].append({"id": "C4", "case": name, "computed": v, "expected_text": txt})
    tx = sorted((ROOT / ".work" / "text").glob("*_R2X_kokuho_web_nenkin"))
    if tx:
        page = (tx[-1] / "nk_menjo.txt").read_text(encoding="utf-8")
        for c in res["checks"]:
            if c["id"] == "C4":
                c["ok"] = c["expected_text"] in page
                c["page_text_file"] = str((tx[-1] / "nk_menjo.txt").relative_to(ROOT))
    # 計算例：軽減判定の基準額（令和7年度・令和8年度。被保険者等の数 n、給与所得者等の数 k）
    examples = {}
    for a, label in [("2025-04-01", "令和7年度"), ("2026-04-01", "令和8年度")]:
        k = res["versions"][a]["kokuho-rei"]
        basic = 430_000
        add_k = k["reduction_per_earner_add"][0]
        p5, p2 = sorted(k["reduction_per_person_amounts"])
        rows = []
        for n in range(1, 6):
            for e in range(0, 3):
                b7 = basic + max(e - 1, 0) * add_k
                rows.append({"n": n, "earners": e, "7割": b7, "5割": b7 + n * p5, "2割": b7 + n * p2})
        examples[label] = {"basic": basic, "per_earner_add": add_k, "per_person_5wari": p5, "per_person_2wari": p2, "rows": rows}
    res["computed"]["reduction_thresholds"] = examples
    # 計算例：国民年金の全額免除・納付猶予（扶養親族等の数 d）と、一部免除・学生の基準（扶養親族等が一般の控除対象扶養親族だけの場合）
    kr = res["versions"]["2026-11-09"]["kokunen-rei"]
    ex2 = []
    for d in range(0, 4):
        ex2.append({"dependents": d,
                    "全額免除・納付猶予": (d + 1) * kr["full_exemption"]["per_head"] + kr["full_exemption"]["add"],
                    "4分の3免除": kr["three_quarter"]["base"] + d * kr["three_quarter"]["per_dependent"][0],
                    "半額免除・学生納付特例": kr["half_and_student"]["base"] + d * kr["half_and_student"]["per_dependent"][0],
                    "4分の1免除": kr["quarter"]["base"] + d * kr["quarter"]["per_dependent"][0]})
    res["computed"]["kokunen_exemption_thresholds_general_dependents"] = ex2
    (OUT / "values.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")

    # 表
    L = ["# R2X_kokuho_values（scripts/R2X_kokuho_values.py の出力）", ""]
    L.append("## 版")
    L.append("| asof | 国保令 | 地方税法施行令 | 地方税法 | 国民年金法 | 国年令 | 改定率政令 |")
    L.append("|---|---|---|---|---|---|---|")
    for a in ASOFS:
        v = res["versions"][a]
        L.append(f"| {a} | " + " | ".join(f"{v[s]['source'].get('law_revision_id')}（{v[s]['source'].get('status')}）"
                                            for s in ["kokuho-rei", "chiho-rei", "chiho", "kokunen", "kokunen-rei", "kaiteiritsu"]) + " |")
    L += ["", "## 国保料（国保令第29条の7）と国保税（地方税法施行令第56条の88の2・第56条の89）"]
    L.append("| asof | 限度額（料：基礎/後期/介護/子ども） | 限度額（税：第1〜4項） | 5割・2割の1人あたり（料） | 同（税） | 給与者等の加算 | 給与の収入要件 | 年金の収入要件 | 年金の収入要件（65歳以上、附則） | 未就学 | 出産 | 18歳未満全額 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for a in ASOFS:
        k = res["versions"][a]["kokuho-rei"]
        c = res["versions"][a]["chiho-rei"]
        L.append(f"| {a} | {k['limits']} | {c['limits_by_paragraph']} | {k['reduction_per_person_amounts']} | {c['reduction_per_person_amounts']} | "
                 f"{k['reduction_per_earner_add']} | {k['earner_salary_threshold']} | {k['earner_pension_thresholds']} | "
                 f"料 {k['suppl5_pension_threshold']}／税 {c['suppl18_8_pension_threshold']} | {k['preschool_ratio']}／{c['preschool_ratio']} | {k['childbirth_reduction']} | {k['under18_full_reduction']} |")
    L += ["", "## 地方税法"]
    for a in ASOFS:
        c = res["versions"][a]["chiho"]
        L.append(f"- {a}：国保法第72条の3の2の対象年齢 {res['versions'][a]['kokuho']['child_equal_reduction_age_72_3_2']}、地法第703条の5第2項の対象年齢 {c['child_equal_reduction_age_703_5_2']}、国保法第76条に子ども・子育て支援納付金 {res['versions'][a]['kokuho']['kodomo_in_76']}")
        L.append(f"- {a}：第314条の2第2項 {c['juminzei_basic_deduction']}、第703条の4第38項（擬制）{c['deemed_householder_paragraph']}、子ども・子育て支援納付金課税額 {c['kodomo_component']}、賦課期日 {c['assessment_date']}、第20条の4の2第3項（100円未満切捨て）{c['rounding_final_amount_100yen']}")
    L += ["", "## 国民年金"]
    for a in ASOFS:
        n = res["versions"][a]["kokunen"]
        r = res["versions"][a]["kokunen-rei"]
        L.append(f"- {a}：第87条第3項の額 {n['base_monthly_from_R1']}、端数処理 {n['rounding_rule_87_3']}、付加 {n['fuka_monthly']}、第88条の3 {n['has_88_3_childcare']}、納付猶予の期間 {n['deferral_periods']}、"
                 f"全額免除 {r['full_exemption']}、3/4 {r['three_quarter']}、半額・学生 {r['half_and_student']}、1/4 {r['quarter']}、障害者等 {r['disabled_widow_single_parent_limit']}、6条の12に特定親族特別控除 {r['6_12_includes_tokutei_shinzoku']}")
    L += ["", "## 保険料の月額（計算）"]
    for y, m in monthly.items():
        L.append(f"- {y}：17,000 × {m['rate']} = {m['exact_float']} → {m['monthly']:,}円")
    L.append(f"- 令和8年度の一部免除の納付額（計算）：{partial}")
    for y, d in partial_all.items():
        L.append(f"- 参考 {y} の一部免除の残りの額（端数処理前 → 後）：" + "、".join(f"{n} {v['remain_float']} → {v['rounded']:,}円" for n, v in d.items()))
    L.append("  注：残りの額に0.5円の端数が出る場合、10円未満の端数は r＋0.5（r は整数部の1の位）で、これが5円以上になるのは r≥5 のときだけなので、round_87（整数部で判定）と、0.5円を含めて判定した結果は同じになる。0.5円以外の1円未満の端数はこの3つの割合では出ない。")
    L += ["", "## 検査"]
    for c in res["checks"]:
        L.append(f"- {c['id']} {c.get('asof') or c.get('year') or c.get('case')}: ok={c.get('ok')}  " + json.dumps({k: v for k, v in c.items() if k not in ('id', 'ok')}, ensure_ascii=False))
    L += ["", "## 計算例：軽減判定の基準額（円。総所得金額等の合算額がこの額以下なら該当）"]
    for label, ex in examples.items():
        L.append(f"### {label}（基礎 {ex['basic']}、給与所得者等2人目以降 +{ex['per_earner_add']}、5割 +{ex['per_person_5wari']}×n、2割 +{ex['per_person_2wari']}×n）")
        L.append("| n（被保険者＋特定同一世帯所属者） | 給与所得者等の数 | 7割 | 5割 | 2割 |")
        L.append("|---|---|---|---|---|")
        for row in ex["rows"]:
            L.append(f"| {row['n']} | {row['earners']} | {row['7割']:,} | {row['5割']:,} | {row['2割']:,} |")
    L += ["", "## 計算例：国民年金の免除・納付猶予の所得基準（扶養親族等がすべて一般の控除対象扶養親族の場合。円）",
          "| 扶養親族等の数 | 全額免除・納付猶予 | 4分の3免除 | 半額免除・学生納付特例 | 4分の1免除 |", "|---|---|---|---|---|"]
    for row in ex2:
        L.append(f"| {row['dependents']} | {row['全額免除・納付猶予']:,} | {row['4分の3免除']:,} | {row['半額免除・学生納付特例']:,} | {row['4分の1免除']:,} |")
    L.append("")
    L.append("注：4分の3・半額・4分の1免除と学生納付特例の基準には、このほか社会保険料控除額等（国年令第6条の12第2項）を所得から差し引く（基準額に足すのと同じ）。")
    (OUT / "values.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L[:80]))


if __name__ == "__main__":
    main()

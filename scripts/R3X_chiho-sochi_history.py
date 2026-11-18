"""R3X chiho-sochi（補足）: 取得済みの条文 JSON と PDF のテキストから、次を機械的に確かめる（ネットワークは使わない）。

1. 地方税法施行令の「総所得金額の算定の特例」（第7条の10の5・第48条の5の2）を入れた改正政令と、その適用年度
   （令和4年政令第133号 附則第1条・第2条・第7条）、措置法の条の引用を替えた改正政令（令和6年政令第136号 附則第1条第1号）。
2. 地方税法が措置法の規定を個別に扱う例：附則第6条（肉用牛。措法第25条）、附則第4条の5（特定一般用医薬品等購入費。措法第41条の17）、
   第314条の2第1項（所得控除は地方税法自身が「前年の所得について算定した総所得金額…から控除」と定める）。
3. 地方税法施行令の原始附則第18条第1項（「所得税法その他の所得税に関する法令の規定（租税特別措置法施行令第…の規定を除く。…）の例」）。
4. 総務省の取扱通知（市町村税関係）第2章第2節 12(3) ア〜キ（措置法の規定で総所得金額から除かれる利子等）と、
   令和8年4月1日 総税企第44号（施行通知）の (9)・(11)（措法第41条の17・第25条の特例を地方税法の附則で手当てしたこと）。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_chiho-sochi_history.py

入力（読むだけ。ダウンロード先の中では何も実行しない）:
- scripts/results/R3X_chiho-sochi_egov/fetch_log.json の download_dir にある e-Gov 法令API v2 の JSON（scripts/R3X_chiho-sochi_egov.py が取得）
- scripts/results/R3X_chiho-sochi_pdftext/<名前>.txt（scripts/R3X_chiho-sochi_pdftext.py の出力）
出力（scripts/results/R3X_chiho-sochi_history/）:
- history.md：抜き出した条文（改正政令の附則、地方税法の附則など）と検査の結果
- checks.json：検査ごとの OK/NG
条文の木の扱い（inline・walk）は scripts/R3X_chiho-sochi_checks.py を写した（import はしない）。
"""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
EG = ROOT / "scripts" / "results" / "R3X_chiho-sochi_egov"
PT = ROOT / "scripts" / "results" / "R3X_chiho-sochi_pdftext"
OUT = ROOT / "scripts" / "results" / "R3X_chiho-sochi_history"

CHIHO, CHIHO_REI = "325AC0000000226", "325CO0000000245"


def inline(n):
    if isinstance(n, str):
        return n
    if n.get("tag") == "Rt":
        return ""
    return "".join(inline(c) for c in n.get("children", []))


def walk(n, fn, path=()):
    if isinstance(n, dict):
        fn(n, path)
        for c in n.get("children", []):
            walk(c, fn, path + (n,))


_cache = {}


def law(law_id, asof):
    key = (law_id, asof)
    if key not in _cache:
        log = json.loads((EG / "fetch_log.json").read_text(encoding="utf-8"))
        dl = ROOT / log["download_dir"]
        d = json.loads((dl / f"{law_id}_{asof}.json").read_text(encoding="utf-8"))
        ri = d.get("revision_info") or {}
        _cache[key] = (d["law_full_text"], ri.get("law_revision_id"))
    return _cache[key]


def amend_articles(law_id, asof, amend_law_num):
    """改正附則（AmendLawNum が一致する SupplProvision）の条を {Num: テキスト} で返す"""
    root, rid = law(law_id, asof)
    out = {}

    def fn(n, path):
        if n.get("tag") == "SupplProvision" and (n.get("attr", {}).get("AmendLawNum") or "") == amend_law_num:
            for c in n.get("children", []):
                if isinstance(c, dict) and c.get("tag") == "Article":
                    out[c["attr"].get("Num")] = inline(c)
    walk(root, fn)
    return out, rid


def original_suppl_article(law_id, asof, num):
    """原始附則（AmendLawNum のない SupplProvision）の条：(見出し, [項のテキスト])"""
    root, rid = law(law_id, asof)
    found = []

    def fn(n, path):
        if n.get("tag") == "Article" and n.get("attr", {}).get("Num") == num:
            sp = [p for p in path if p.get("tag") == "SupplProvision"]
            if sp and not sp[-1].get("attr", {}).get("AmendLawNum"):
                cap = "".join(inline(c) for c in n["children"] if isinstance(c, dict) and c.get("tag") == "ArticleCaption")
                paras = [inline(c) for c in n["children"] if isinstance(c, dict) and c.get("tag") == "Paragraph"]
                found.append((cap, paras))
    walk(root, fn)
    return (found[0] if found else (None, [])), rid


def main_paragraph(law_id, asof, num, para):
    root, rid = law(law_id, asof)
    found = []

    def fn(n, path):
        if n.get("tag") == "Article" and n.get("attr", {}).get("Num") == num and not any(p.get("tag") == "SupplProvision" for p in path):
            for c in n.get("children", []):
                if isinstance(c, dict) and c.get("tag") == "Paragraph" and c.get("attr", {}).get("Num") == para:
                    found.append(inline(c))
    walk(root, fn)
    return (found[0] if found else ""), rid


def pdf_flat(name):
    t = (PT / f"{name}.txt").read_text(encoding="utf-8")
    lines = [ln for ln in t.splitlines()[1:] if not ln.startswith("=== p.") and not re.fullmatch(r"\s*[-－–]\s*[0-9０-９]+\s*[-－–]?\s*|\s*[0-9０-９]+\s*", ln)]
    return re.sub(r"[\s\u3000]+", "", "".join(lines))


def norm(s):
    return re.sub(r"[\s\u3000]+", "", s)


RESULTS = []


def check(cid, target, expect, ok):
    RESULTS.append({"id": cid, "target": target, "expect": expect, "ok": bool(ok)})


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    md = ["# R3X chiho-sochi（補足）：改正政令の附則・地方税法の附則・通知の文字列", "",
          "生成：scripts/R3X_chiho-sochi_history.py。入力は scripts/results/R3X_chiho-sochi_egov/fetch_log.json の download_dir の JSON と、"
          "scripts/results/R3X_chiho-sochi_pdftext/*.txt。", ""]

    # ---- 1. 改正政令の附則（施行令 asof 2024-12-31 と 2026-11-09 の版に収録されている改正附則）
    R4 = "令和四年三月三一日政令第一三三号"
    R6 = "令和六年三月三〇日政令第一三六号"
    md += ["## 1. 地方税法施行令の改正附則", ""]
    for asof in ["2024-12-31", "2026-11-09"]:
        a4, rid = amend_articles(CHIHO_REI, asof, R4)
        md += [f"### {R4}（地方税法施行令 asof={asof}、{rid} に収録）", ""]
        for num in ["2", "7"]:
            md += [f"- 附則第{num}条：{a4.get(num, '（見つからない）')}"]
        md += [f"- 附則第1条（冒頭 60 字）：{a4.get('1', '（見つからない）')[:60]}", ""]
        check(f"A4-1-{asof}", f"施行令 asof={asof} {R4} 附則第1条", "この政令は、令和四年四月一日から施行する。", "この政令は、令和四年四月一日から施行する。" in a4.get("1", ""))
        check(f"A4-2-{asof}", f"施行令 asof={asof} {R4} 附則第2条（道府県民税）",
              "新令第七条の十の五及び第七条の十一第二項の規定は、令和四年度以後の年度分の個人の道府県民税について適用し、令和三年度分までの個人の道府県民税については、なお従前の例による。",
              "新令」という。）第七条の十の五及び第七条の十一第二項の規定は、令和四年度以後の年度分の個人の道府県民税について適用し、令和三年度分までの個人の道府県民税については、なお従前の例による。" in a4.get("2", ""))
        check(f"A4-7-{asof}", f"施行令 asof={asof} {R4} 附則第7条（市町村民税）",
              "新令第四十八条の五の二及び第四十八条の五の三第二項の規定は、令和四年度以後の年度分の個人の市町村民税について適用し、令和三年度分までの個人の市町村民税については、なお従前の例による。",
              "新令第四十八条の五の二及び第四十八条の五の三第二項の規定は、令和四年度以後の年度分の個人の市町村民税について適用し、令和三年度分までの個人の市町村民税については、なお従前の例による。" in a4.get("7", ""))
        a6, _ = amend_articles(CHIHO_REI, asof, R6)
        t6 = a6.get("1", "")
        frag = "第七条の十の五、第七条の十一第二項、第四十八条の五の二及び第四十八条の五の三第二項の改正規定並びに附則第十八条第一項、第十八条の六並びに第二十七条の三第二項及び第五項の改正規定令和七年一月一日"
        check(f"A6-1-{asof}", f"施行令 asof={asof} {R6} 附則第1条第1号", frag + "（号の文と施行日が続けて取り出される）", frag in t6)
        md += [f"### {R6}（同 asof={asof}）附則第1条第1号の該当部分", "", f"- {frag if frag in t6 else '（見つからない）'}", ""]

    # ---- 2. 地方税法が措置法の規定を個別に扱う例（asof 2026-11-09）
    md += ["## 2. 地方税法が措置法の規定を個別に扱う例（地方税法 asof=2026-11-09）", ""]
    (cap6, p6), rid = original_suppl_article(CHIHO, "2026-11-09", "6")
    md += [f"### 附則第6条 {cap6}（{rid}）", ""]
    for i in (3, 4):
        if i < len(p6):
            md += [f"- 第{i + 1}項：{p6[i]}"]
    md += [""]
    check("B6-cap", "地方税法 原始附則第6条の見出し", "（肉用牛の売却による事業所得に係る道府県民税及び市町村民税の課税の特例）",
          cap6 == "（肉用牛の売却による事業所得に係る道府県民税及び市町村民税の課税の特例）")
    check("B6-4a", "地方税法 原始附則第6条第4項", "市町村は、昭和五十七年度から令和十二年度までの各年度分の個人の市町村民税に限り、所得割の納税義務者が前年中に租税特別措置法第二十五条第一項各号に掲げる売却の方法により",
          len(p6) > 3 and "市町村は、昭和五十七年度から令和十二年度までの各年度分の個人の市町村民税に限り、所得割の納税義務者が前年中に租税特別措置法第二十五条第一項各号に掲げる売却の方法により" in p6[3])
    check("B6-4b", "地方税法 原始附則第6条第4項（末尾）", "当該事業所得に係る市町村民税の所得割の額として政令で定める額を免除するものとする。",
          len(p6) > 3 and p6[3].endswith("当該事業所得に係る市町村民税の所得割の額として政令で定める額を免除するものとする。"))
    (cap45, p45), _ = original_suppl_article(CHIHO, "2026-11-09", "4_5")
    md += [f"### 附則第4条の5 {cap45}", "", f"- 第3項（冒頭 200 字）：{p45[2][:200] if len(p45) > 2 else '（見つからない）'}", ""]
    check("B45-cap", "地方税法 原始附則第4条の5の見出し", "（特定一般用医薬品等購入費を支払つた場合の医療費控除の特例）", cap45 == "（特定一般用医薬品等購入費を支払つた場合の医療費控除の特例）")
    check("B45-3", "地方税法 原始附則第4条の5第3項", "市町村は、平成三十年度から令和九年度までの各年度分の個人の市町村民税に限り",
          len(p45) > 2 and "市町村は、平成三十年度から令和九年度までの各年度分の個人の市町村民税に限り" in p45[2][:40])  # 先頭に項番号「３」が付く
    check("B45-3b", "地方税法 原始附則第4条の5第3項", "第三百十四条の二第一項（第二号に係る部分に限る。）の規定による控除については、その者の選択により",
          len(p45) > 2 and "第三百十四条の二第一項（第二号に係る部分に限る。）の規定による控除については、その者の選択により" in p45[2])
    t3142, rid = main_paragraph(CHIHO, "2026-11-09", "314_2", "1")
    s = "市町村は、所得割の納税義務者が次の各号に掲げる者のいずれかに該当する場合には、それぞれ当該各号に定める金額をその者の前年の所得について算定した総所得金額、退職所得金額又は山林所得金額から控除するものとする。"
    check("B3142", f"地方税法 asof=2026-11-09（{rid}）第314条の2第1項 柱書", s, t3142.startswith(s))
    md += ["### 第314条の2第1項 柱書", "", f"- {s if t3142.startswith(s) else '（一致しない）'}", ""]

    # ---- 3. 施行令 原始附則第18条第1項
    (cap18, p18), rid = original_suppl_article(CHIHO_REI, "2026-11-09", "18")
    md += [f"## 3. 地方税法施行令 原始附則第18条 {cap18}（asof=2026-11-09、{rid}）第1項の前半", "", f"- {p18[0][:420] if p18 else '（見つからない）'}…", ""]
    s18 = "所得税法その他の所得税に関する法令の規定（租税特別措置法施行令第二十五条の十二第十項から第十二項まで、第二十五条の十二の二第八項及び第九項並びに第二十六条の二十八の三第六項の規定を除く。以下この条から附則第十八条の六までにおいて同じ。）の例により計算した"
    check("C18", "地方税法施行令 原始附則第18条第1項", s18, bool(p18) and s18 in p18[0])

    # ---- 4. 通知（PDF）
    P = {n: pdf_flat(n) for n in ["toriatsukai_shichoson_zenbun", "r8_kaisei_tsuchi"]}
    md += ["## 4. 総務省の通知（PDF から取り出した文字。空白・改行を除いて比べた）", ""]
    pdfc = [
        ("D12-3-a", "toriatsukai_shichoson_zenbun", "取扱通知（市町村税）第2章第2節 12(3)ア", "ア租税特別措置法（昭和３２年法律第２６号）第３条第１項に規定する一般利子等"),
        ("D12-3-i", "toriatsukai_shichoson_zenbun", "同 イ", "イ租税特別措置法第３条の３第１項に規定する国外一般公社債等の利子等"),
        ("D12-3-u", "toriatsukai_shichoson_zenbun", "同 ウ", "ウ租税特別措置法第４条の４第１項に規定する勤労者財産形成貯蓄保険契約等に基づき支払いを受ける差益"),
        ("D12-3-e", "toriatsukai_shichoson_zenbun", "同 エ", "エ租税特別措置法第８条の２第１項に規定する私募公社債等運用投資信託等の収益の分配に係る配当等"),
        ("D12-3-o", "toriatsukai_shichoson_zenbun", "同 オ", "オ租税特別措置法第８条の３第１項に規定する国外私募公社債等運用投資信託等の配当等"),
        ("D12-3-ka", "toriatsukai_shichoson_zenbun", "同 カ", "カ租税特別措置法第４１条の９第１項に規定する懸賞金付預貯金等の懸賞金等"),
        ("D12-3-ki", "toriatsukai_shichoson_zenbun", "同 キ", "キ租税特別措置法第４１条の１０第１項に規定する給付補填金等"),
        ("D12-3-head", "toriatsukai_shichoson_zenbun", "同 12(3) 柱書",
         "次に掲げるものは、それぞれの規定により所得税法第２２条第２項の総所得金額から除かれているので、所得割の課税標準となる総所得金額には含まれないものであること。"),
        ("D12-6", "toriatsukai_shichoson_zenbun", "同 12(6)（非居住者期間）",
         "法又は法に基づく政令で特別の定めをする場合を除くほか所得税法その他の所得税に関する法令の規定による同法第１６５条及び同法施行令第２５８条の所得税の課税標準の計算の例によって算定するものであること。"),
        ("D-r8-9a", "r8_kaisei_tsuchi", "令和8年 総税企第44号 第二 市町村税 (7)（第一 道府県税 (9) と同文）",
         "特定一般用医薬品等購入費を支払った場合の医療費控除の特例について、租税特別措置法第四十一条の十七第一項各号に掲げる期間内に特定一般用医薬"),
        ("D-r8-9b", "r8_kaisei_tsuchi", "同（関係条）", "（法附則第四条の五関係）"),
        ("D-r8-11", "r8_kaisei_tsuchi", "同 第二 (9)", "肉用牛の売却による事業所得に係る課税の特例について、適用期限を令和十二年度分の個人の市町村民税まで延長する。（法附則第六条関係）"),
    ]
    md += ["| ID | 対象 | 結果 | 文字列 |", "|---|---|---|---|"]
    for cid, name, label, text in pdfc:
        ok = norm(text) in P[name]
        check(cid, f"{name}：{label}", text, ok)
        md += [f"| {cid} | {name}：{label} | {'OK' if ok else 'NG'} | {text} |"]
    md += [""]

    # ---- 5. 語の出現回数（措置法第29条の4 の条番号、給与所得控除）
    md += ["## 5. 語の出現回数（PDF の全頁。空白・改行を除いてつないだ文字列で数えた）", "",
           "| PDF | 二十九条の四 | ２９条の４ | 29条の4 | 給与所得控除 | 租税特別措置法 |", "|---|---|---|---|---|---|"]
    counts = {}
    for name in ["r8_ryuiten", "r8_gaiyo", "r8_kaisei_tsuchi", "toriatsukai_shichoson_zenbun", "toriatsukai_dofuken_zenbun"]:
        t = norm((PT / f"{name}.txt").read_text(encoding="utf-8"))
        c = [t.count(k) for k in ["二十九条の四", "２９条の４", "29条の4", "給与所得控除", "租税特別措置法"]]
        counts[name] = c
        md.append(f"| {name} | " + " | ".join(str(x) for x in c) + " |")
    md += ["", "（この表は数えただけで、OK/NG の判定はしない。頁の区切りの行も含めて数えた）", ""]

    ok = sum(1 for r in RESULTS if r["ok"])
    ng = [r for r in RESULTS if not r["ok"]]
    md += ["## 検査の結果（全体）", "", f"- {ok + len(ng)} 件（OK {ok}、NG {len(ng)}）", "", "| ID | 結果 | 対象 | 期待 |", "|---|---|---|---|"]
    for r in RESULTS:
        md.append(f"| {r['id']} | {'OK' if r['ok'] else 'NG'} | {r['target']} | {r['expect']} |")
    (OUT / "history.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (OUT / "checks.json").write_text(json.dumps({"checks": RESULTS, "word_counts": counts}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("OK", ok, "NG", len(ng))
    for r in ng:
        print("NG", r["id"], r["target"])


if __name__ == "__main__":
    main()

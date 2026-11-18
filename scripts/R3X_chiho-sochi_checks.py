"""R3X chiho-sochi: 文書に書く文字列（法令の原文・総務省の通知の文）を、取得したデータで機械的に確かめる。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ。ネットワークは使わない）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_chiho-sochi_checks.py

入力（読むだけ。ダウンロード先の中では何も実行しない）:
- scripts/results/R3X_chiho-sochi_egov/fetch_log.json の download_dir にある e-Gov 法令API v2 の JSON（scripts/R3X_chiho-sochi_egov.py が取得）
- scripts/results/R3X_chiho-sochi_pdftext/<名前>.txt（scripts/R3X_chiho-sochi_pdftext.py が PDF から取り出した行のテキスト）
出力:
- scripts/results/R3X_chiho-sochi_checks/evidence.md：検査ごとの OK/NG、対象（法令・asof・条・項、または PDF・頁）、確かめた文字列
- scripts/results/R3X_chiho-sochi_checks/checks.json：同じ内容の JSON
- scripts/results/R3X_chiho-sochi_checks/structure.md：地方税法の第32条・第313条が属する章・節・款の題名、第23条第5項・第292条第5項の除外の一覧

PDF のテキストは、頁の区切り（=== p.N ===）と頁番号の行（-N- など）を除き、空白と改行を取り除いてつないだ文字列で探す。
レイアウトの都合で文が入れ替わって取り出された箇所（平成30年の留意事項 p.6 など）は、文の断片ごとに確かめる（全文は PDF を画像で読んで確かめた）。
"""
import glob
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
EG = ROOT / "scripts" / "results" / "R3X_chiho-sochi_egov"
PT = ROOT / "scripts" / "results" / "R3X_chiho-sochi_pdftext"
OUT = ROOT / "scripts" / "results" / "R3X_chiho-sochi_checks"

CHIHO, CHIHO_REI, CHIHO_KI, SOCHI = "325AC0000000226", "325CO0000000245", "329M50000002023", "332AC0000000026"


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


def main_article(law_id, asof, num):
    root, rid = law(law_id, asof)
    found = []

    def fn(n, path):
        if n.get("tag") == "Article" and n.get("attr", {}).get("Num") == num and not any(p.get("tag") == "SupplProvision" for p in path):
            found.append(n)
    walk(root, fn)
    return (found[0] if found else None), rid


def paragraph(law_id, asof, num, para):
    a, rid = main_article(law_id, asof, num)
    if a is None:
        return "", rid
    for c in a.get("children", []):
        if isinstance(c, dict) and c.get("tag") == "Paragraph" and c.get("attr", {}).get("Num") == para:
            return inline(c), rid
    return "", rid


def caption(law_id, asof, num):
    a, _ = main_article(law_id, asof, num)
    if a is None:
        return None
    for c in a.get("children", []):
        if isinstance(c, dict) and c.get("tag") == "ArticleCaption":
            return inline(c)
    return ""


def suppl_original_article(law_id, asof, num, para):
    """原始附則（AmendLawNum のない SupplProvision）の条・項"""
    root, rid = law(law_id, asof)
    out = []

    def fn(n, path):
        if n.get("tag") == "Paragraph" and n.get("attr", {}).get("Num") == para:
            sp = [p for p in path if p.get("tag") == "SupplProvision"]
            arts = [p for p in path if p.get("tag") == "Article"]
            if sp and not sp[-1].get("attr", {}).get("AmendLawNum") and arts and arts[-1].get("attr", {}).get("Num") == num:
                out.append(inline(n))
    walk(root, fn)
    return (out[0] if out else ""), rid


def main_sentences(law_id, asof):
    root, rid = law(law_id, asof)
    out = []

    def fn(n, path):
        if n.get("tag") == "Sentence" and not any(p.get("tag") == "SupplProvision" for p in path):
            out.append(inline(n))
    walk(root, fn)
    return out, rid


def pdf_flat(name):
    t = (PT / f"{name}.txt").read_text(encoding="utf-8")
    lines = [ln for ln in t.splitlines()[1:] if not ln.startswith("=== p.") and not re.fullmatch(r"\s*[-－–]\s*[0-9０-９]+\s*[-－–]?\s*|\s*[0-9０-９]+\s*", ln)]
    return re.sub(r"[\s\u3000]+", "", "".join(lines))


def norm(s):
    return re.sub(r"[\s\u3000]+", "", s)


RESULTS = []


def check(cid, target, expect, ok, note=""):
    RESULTS.append({"id": cid, "target": target, "expect": expect, "ok": bool(ok), "note": note})


def law_contains(cid, law_id, asof, num, para, text, label):
    body, rid = paragraph(law_id, asof, num, para)
    check(cid, f"{label} asof={asof}（{rid}）第{num}条第{para}項", text, text in body)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    # ---------------- 法令（e-Gov） ----------------
    s313 = "所得税法その他の所得税に関する法令の規定による所得税法第二十二条第二項又は第三項の総所得金額、退職所得金額又は山林所得金額の計算の例により算定するものとする"
    tad = "ただし、同法第六十条の二から第六十条の四までの規定の例によらないものとする。"
    for asof in ["2026-11-09", "2026-12-01", "2027-01-01"]:
        law_contains(f"L1-313-{asof}", CHIHO, asof, "313", "2", "この法律又はこれに基づく政令で特別の定めをする場合を除くほか、それぞれ" + s313, "地方税法")
        law_contains(f"L1-313t-{asof}", CHIHO, asof, "313", "2", tad, "地方税法")
        law_contains(f"L2-32-{asof}", CHIHO, asof, "32", "2", "この法律又はこれに基づく政令で特別の定めをする場合を除くほか、それぞれ" + s313, "地方税法")
        law_contains(f"L2-32t-{asof}", CHIHO, asof, "32", "2", tad, "地方税法")
        law_contains(f"L3-292-{asof}", CHIHO, asof, "292", "5",
                     "市町村民税について所得税法その他の所得税に関する法令を引用する場合（第一項第六号、第三百十七条の六、第三百二十一条の四及び第五款において引用する場合を除く。）には、これらの法令は、前年の所得について適用されたものをいうものとする。", "地方税法")
        law_contains(f"L3-23-{asof}", CHIHO, asof, "23", "5",
                     "道府県民税について所得税法その他の所得税に関する法令を引用する場合（第一項第六号及び第十四号から第十七号まで、第二十五条の二、次款第三目及び第四款から第六款まで並びに附則第三十五条の二の五第二項から第四項までにおいて引用する場合を除く。）には、これらの法令は、前年の所得について適用されたものをいうものとする。", "地方税法")
        law_contains(f"L8-72_49_12-{asof}", CHIHO, asof, "72_49_12", "1",
                     "所得税法第二十六条及び第二十七条（同法第百六十五条第一項の規定によりこれらの規定に準ずる場合を含む。）に規定する不動産所得及び事業所得の計算の例により算定する。ただし、租税特別措置法第二十八条の四の規定の例によらないものとし", "地方税法")
    # 第292条第1項第6号の措法の引用（2026-11-09・2026-12-01 は第二十九条の四、2027-01-01 は第二十九条の五）
    for asof, art in [("2026-11-09", "第二十九条の四"), ("2026-12-01", "第二十九条の四"), ("2027-01-01", "第二十九条の五")]:
        law_contains(f"L15-292-1-6-{asof}", CHIHO, asof, "292", "1", f"租税特別措置法{art}において退職手当等とみなされる金額を含む。", "地方税法")
    # 施行令 第48条の5の2・第7条の10の5
    r48 = ["法第三百十三条第二項の規定により同条第一項の総所得金額を算定する場合には",
           "租税特別措置法第四十一条の三の十一第四項第三号中「所得税法第二条第一項第三十四号に規定する扶養親族」とあるのは「地方税法（昭和二十五年法律第二百二十六号）第二百九十二条第一項第九号に規定する扶養親族」と",
           "同項第四号中「所得税法第二条第一項第三十三号に規定する同一生計配偶者」とあるのは「地方税法第二百九十二条第一項第七号に規定する同一生計配偶者」と",
           "同法第四十一条の十五の三第一項中「同条第四項（同法第百六十五条第一項において適用する場合を含む。）」とあるのは「地方税法第三百十三条第二項の規定によりその例によることとされる所得税法第三十五条第四項」と",
           "所得税法第三十五条第四項第一号中「第二条第一項第三十号（定義）に規定する合計所得金額」とあるのは「地方税法（昭和二十五年法律第二百二十六号）第二百九十二条第一項第十三号に規定する合計所得金額」と",
           "として、これらの規定の例によるものとする。"]
    r7 = ["法第三十二条第二項の規定により同条第一項の総所得金額を算定する場合には",
          "租税特別措置法第四十一条の三の十一第四項第三号中「所得税法第二条第一項第三十四号に規定する扶養親族」とあるのは「地方税法（昭和二十五年法律第二百二十六号）第二十三条第一項第九号に規定する扶養親族」と",
          "同法第四十一条の十五の三第一項中「同条第四項（同法第百六十五条第一項において適用する場合を含む。）」とあるのは「地方税法第三十二条第二項の規定によりその例によることとされる所得税法第三十五条第四項」と",
          "として、これらの規定の例によるものとする。"]
    for asof in ["2025-01-01", "2026-01-01", "2026-11-09", "2027-01-01"]:
        for i, t in enumerate(r48):
            law_contains(f"L4-48_5_2-{asof}-{i}", CHIHO_REI, asof, "48_5_2", "1", t, "地方税法施行令")
        for i, t in enumerate(r7):
            law_contains(f"L5-7_10_5-{asof}-{i}", CHIHO_REI, asof, "7_10_5", "1", t, "地方税法施行令")
        check(f"L4c-{asof}", f"地方税法施行令 asof={asof} 第48条の5の2 の見出し", "（総所得金額の算定の特例）", caption(CHIHO_REI, asof, "48_5_2") == "（総所得金額の算定の特例）")
    # 令和6年政令第136号の前（2024-12-31）は措法第41条の3の3 を引いていた。2021-01-01 には第7条の10の5 がなく、第48条の5の2 は別の条
    law_contains("L17-2024-12-31-48", CHIHO_REI, "2024-12-31", "48_5_2", "1", "租税特別措置法第四十一条の三の三第四項第三号中", "地方税法施行令")
    law_contains("L17-2024-12-31-7", CHIHO_REI, "2024-12-31", "7_10_5", "1", "租税特別措置法第四十一条の三の三第四項第三号中", "地方税法施行令")
    check("L17-2021-7_10_5", "地方税法施行令 asof=2021-01-01 第7条の10の5", "本則にない", main_article(CHIHO_REI, "2021-01-01", "7_10_5")[0] is None)
    check("L17-2021-48_5_2", "地方税法施行令 asof=2021-01-01 第48条の5の2 の見出し", "（非居住者期間を有する所得割の納税義務者の課税標準の算定）",
          caption(CHIHO_REI, "2021-01-01", "48_5_2") == "（非居住者期間を有する所得割の納税義務者の課税標準の算定）")
    # 施行令 附則第18条第1項（原始附則）
    for asof in ["2026-11-09", "2027-01-01"]:
        body, rid = suppl_original_article(CHIHO_REI, asof, "18", "1")
        t = "所得税法その他の所得税に関する法令の規定（租税特別措置法施行令第二十五条の十二第十項から第十二項まで、第二十五条の十二の二第八項及び第九項並びに第二十六条の二十八の三第六項の規定を除く。"
        check(f"L6-附則18-{asof}", f"地方税法施行令 asof={asof}（{rid}）原始附則第18条第1項", t, t in body)
    # 施行規則 第6条の8
    for i, t in enumerate(["法第七十二条の五十五の二第三項の規定により申告書に付記しなければならない事項は",
                           "租税特別措置法第二十六条第一項の規定又は法第三十二条第二項の規定においてその例によるものとされる租税特別措置法第二十六条第一項の規定により算定した事業所得等の金額",
                           "租税特別措置法第二十五条の二に規定する青色申告特別控除の適用を受けた者にあつては、その旨",
                           "租税特別措置法第四十一条の四第一項及び第四十一条の四の二第一項の規定の適用を受けた者にあつては、所得税法第二十六条第二項の規定又は法第三十二条第二項の規定においてその例によるものとされる所得税法第二十六条第二項の規定により算定した不動産所得の金額"]):
        a, rid = main_article(CHIHO_KI, "2026-11-09", "6_8")
        check(f"L7-規則6_8-{i}", f"地方税法施行規則 asof=2026-11-09（{rid}）第6条の8", t, a is not None and t in inline(a))
    # 措置法
    for asof in ["2026-11-09", "2026-12-01", "2027-01-01"]:
        law_contains(f"L9-措1-{asof}", SOCHI, asof, "1", "1",
                     "又はこれらの税に係る納税義務、課税標準若しくは税額の計算、申告書の提出期限若しくは徴収につき、所得税法（昭和四十年法律第三十三号）", "租税特別措置法")
        law_contains(f"L9-措1b-{asof}", SOCHI, asof, "1", "1", "の特例を設けることについて規定するものとする。", "租税特別措置法")
        law_contains(f"L11-措41_4-{asof}", SOCHI, asof, "41_4", "1", "所得税法第六十九条第一項の規定その他の所得税に関する法令の規定の適用については、生じなかつたものとみなす。", "租税特別措置法")
        law_contains(f"L13-措41_15_3-{asof}", SOCHI, asof, "41_15_3", "4", "第一項の個人の年齢が六十五歳以上であるかどうかの判定はその年十二月三十一日", "租税特別措置法")
        law_contains(f"L13b-措41_15_3-{asof}", SOCHI, asof, "41_15_3", "1", "同法第三十五条第四項第一号中「六十万円に」とあるのは「百十万円に」と", "租税特別措置法")
        law_contains(f"L19-措25_2-{asof}", SOCHI, asof, "25_2", "1",
                     "所得税法第二十六条第二項、第二十七条第二項又は第三十二条第三項の規定により計算した不動産所得の金額、事業所得の金額又は山林所得の金額から次に掲げる金額のうちいずれか低い金額を控除した金額とする。", "租税特別措置法")
        law_contains(f"L20-措41_3_11-{asof}", SOCHI, asof, "41_3_11", "2", "その年分の給与所得の金額（前項の規定の適用がある場合には、同項の規定による控除をした残額）から控除する。", "租税特別措置法")
        # 第二章の題名と、6つの条が第二章（第三章の前）にあること
        root, rid = law(SOCHI, asof)
        order = []

        def fn(n, path):
            if any(p.get("tag") == "SupplProvision" for p in path):
                return
            if n.get("tag") == "ChapterTitle":
                order.append(("章", inline(n)))
            if n.get("tag") == "Article":
                order.append(("条", n["attr"].get("Num")))
        walk(root, fn)
        ch = None
        where = {}
        for k, v in order:
            if k == "章":
                ch = v
            else:
                where[v] = ch
        for num in ["25_2", "27", "29_4", "41_3_11", "41_4", "41_15_3"]:
            check(f"L10-{num}-{asof}", f"租税特別措置法 asof={asof}（{rid}）第{num}条の属する章", "第二章　所得税法の特例", where.get(num) == "第二章　所得税法の特例",
                  f"見出し={caption(SOCHI, asof, num)}")
    check("L16-29_4-2026-11-09", "租税特別措置法 asof=2026-11-09 第29条の4 の見出し", "（退職勤労者が弁済を受ける未払賃金に係る課税の特例）",
          caption(SOCHI, "2026-11-09", "29_4") == "（退職勤労者が弁済を受ける未払賃金に係る課税の特例）")
    for asof in ["2026-12-01", "2027-01-01"]:
        check(f"L16-29_4-{asof}", f"租税特別措置法 asof={asof} 第29条の4 の見出し", "（給与所得控除の最低控除額等の特例）", caption(SOCHI, asof, "29_4") == "（給与所得控除の最低控除額等の特例）")
        check(f"L16-29_5-{asof}", f"租税特別措置法 asof={asof} 第29条の5 の見出し", "（退職勤労者が弁済を受ける未払賃金に係る課税の特例）",
              caption(SOCHI, asof, "29_5") == "（退職勤労者が弁済を受ける未払賃金に係る課税の特例）")
        law_contains(f"L12-措29_4-{asof}", SOCHI, asof, "29_4", "1", "令和八年又は令和九年において、その年中の所得税法第二十八条第一項に規定する給与等", "租税特別措置法")
        law_contains(f"L12b-措29_4-{asof}", SOCHI, asof, "29_4", "1", "同項第一号の規定にかかわらず、七十四万円（当該収入金額が七十四万円に満たない場合には、当該収入金額に相当する金額）とする。", "租税特別措置法")
    check("L18-2021", "租税特別措置法 asof=2021-01-01 第41条の3の3 の見出し", "（所得金額調整控除）", caption(SOCHI, "2021-01-01", "41_3_3") == "（所得金額調整控除）")
    # 地方税法・施行令の本則に、6つの条を「租税特別措置法第…条」の形で引く文があるか（数）
    tgt = {"第二十五条の二": "25の2", "第二十七条": "27", "第二十九条の四": "29の4", "第四十一条の三の十一": "41の3の11", "第四十一条の四": "41の4", "第四十一条の十五の三": "41の15の3"}
    for lid, lname in [(CHIHO, "地方税法"), (CHIHO_REI, "地方税法施行令")]:
        for asof in ["2026-11-09", "2027-01-01"]:
            ss, rid = main_sentences(lid, asof)
            for art, lab in tgt.items():
                n = sum(len(re.findall("租税特別措置法" + re.escape(art) + "(?!の)", s)) for s in ss)
                n2 = sum(len(re.findall("同法" + re.escape(art) + "(?!の)", s)) for s in ss if "租税特別措置法" in s)
                RESULTS.append({"id": f"C-{lname}-{asof}-{lab}", "target": f"{lname} asof={asof}（{rid}）本則の文",
                                "expect": f"「租税特別措置法{art}」の数（参考：「租税特別措置法」を含む文の中の「同法{art}」の数）",
                                "ok": None, "note": f"{n}（{n2}）"})
    # 地方税法の構造：第32条・第313条の属する節・款
    root, rid = law(CHIHO, "2026-11-09")
    stack, loc = {}, {}

    def sfn(n, path):
        if any(p.get("tag") == "SupplProvision" for p in path):
            return
        if n.get("tag") == "Article" and n["attr"].get("Num") in ("23", "32", "292", "313", "328"):
            titles = []
            for p in path:
                for c in p.get("children", []):
                    if isinstance(c, dict) and c.get("tag") in ("ChapterTitle", "SectionTitle", "SubsectionTitle", "DivisionTitle") and p.get("tag") in ("Chapter", "Section", "Subsection", "Division"):
                        titles.append(inline(c))
            loc[n["attr"]["Num"]] = titles
    walk(root, sfn)
    st = [f"# 地方税法 asof=2026-11-09（{rid}）の構造（本則）", ""]
    for k in ("23", "32", "292", "313", "328"):
        st.append(f"- 第{k}条：" + " ＞ ".join(loc.get(k, ["(見つからない)"])))
    (OUT / "structure.md").write_text("\n".join(st) + "\n", encoding="utf-8")
    check("S-313", "地方税法 asof=2026-11-09 第313条の属する款", "第二款　課税標準及び税率（第五款ではない）",
          any(t.startswith("第二款") for t in loc.get("313", [])) and not any(t.startswith("第五款") for t in loc.get("313", [])), " ＞ ".join(loc.get("313", [])))
    check("S-32", "地方税法 asof=2026-11-09 第32条の属する款", "第四款〜第六款・次款第三目ではない（第23条第5項の除外に当たらない）",
          not any(re.match("第[四五六]款", t) for t in loc.get("32", [])), " ＞ ".join(loc.get("32", [])))

    # ---------------- PDF（総務省） ----------------
    P = {n: pdf_flat(n) for n in ["toriatsukai_shichoson_zenbun", "toriatsukai_dofuken_zenbun", "h30_ryuiten", "h30_kaisei_tsuchi",
                                  "r8_ryuiten", "r8_kaisei_tsuchi", "r8_gaiyo", "toriatsukai_shichoson_r8_honbun"]}
    pdfc = [
        ("P1", "toriatsukai_shichoson_zenbun", "取扱通知（市町村税）第2章第2節第3 の12（p.36-37）",
         "総所得金額、退職所得金額又は山林所得金額の算定については、法又はこれに基づく政令で特別の定めをする場合を除くほか、それぞれ所得税法その他の所得税に関する法令の規定による所得税法第２２条第２項又は第３項の総所得金額、退職所得金額又は山林所得金額の計算の例によるものとされているものであること。したがって、収入金額の計算、必要経費の計算、損益の通算等については、原則として所得税の例によるものであること。"),
        ("P2", "toriatsukai_shichoson_zenbun", "同 12(3)（p.37）",
         "次に掲げるものは、それぞれの規定により所得税法第２２条第２項の総所得金額から除かれているので、所得割の課税標準となる総所得金額には含まれないものであること。"),
        ("P2a", "toriatsukai_shichoson_zenbun", "同 12(3)ア（p.37）", "ア租税特別措置法（昭和３２年法律第２６号）第３条第１項に規定する一般利子等"),
        ("P2b", "toriatsukai_shichoson_zenbun", "同 12(3)キ（p.37）", "キ租税特別措置法第４１条の１０第１項に規定する給付補填金等"),
        ("P3", "toriatsukai_shichoson_zenbun", "同 12(4)（p.38）", "課税の特例の対象となる肉用牛の売却による事業所得は、総所得金額に算入されるものであること。（法附則６④・⑤）"),
        ("P3b", "toriatsukai_shichoson_zenbun", "同 12(5)（p.38）",
         "所得税法第３５条第４項に規定する公的年金等控除額の算定の基礎となる同項第１号の公的年金等に係る雑所得以外の所得に係る合計所得金額については、個人の市町村民税における他の所得控除等と同様に、退職手当等（法第３２８条に規定する退職手当等に限る。）を含まない合計所得金額を用いること。（法３１３②、令４８の５の２、令４８の５の３②）"),
        ("P5", "toriatsukai_shichoson_zenbun", "同 一般株式等に係る譲渡所得等（p.92-93）",
         "所得税法その他の所得税に関する法令の規定（租税特別措置法施行令第２５条の１２第７項及び第８項、第２５条の１２の２第７項並びに第２６条の２８の３第６項の規定を除く。"),
        ("P4", "toriatsukai_dofuken_zenbun", "取扱通知（道府県税）第2章第2節第4 の8（p.30）",
         "所得割の課税標準の基礎となる総所得金額、退職所得金額又は山林所得金額の計算及び所得控除の計算は、市町村民税の場合と全く同様であり、これと異なる計算を行うことはできないものであること。"),
        ("P6a", "h30_ryuiten", "平成30年度 留意事項（平成30年1月23日 事務連絡）p.6 (4)①オ(オ) の断片1", "「特定支出控除」、「青色申告特別控除」、「家内労働者等の事業所得等の"),
        ("P6b", "h30_ryuiten", "同 断片2", "所得計算の特例」及び「勤労学生（合計所得金額要件）"),
        ("P6c", "h30_ryuiten", "同 断片3", "税における見直しが、個人住民税にも適用となること。"),
        ("P6d", "h30_ryuiten", "同 (4)①カ の断片", "得金額調整控除に係る部分は、所得税に係る法令の規定が個人住民税にも適用となること。"),
        ("P6e", "h30_ryuiten", "同 (4)①ア(イ) の断片", "の合計額から１０万円を控除した残額を、給与所得の金額から控除すること（所得金額調整控除）"),
        ("P6f", "h30_ryuiten", "同 p.1", "平成３０年度地方税制改正・地方税務行政の運営に当たっての留意事項等について"),
        ("P10", "h30_kaisei_tsuchi", "平成30年4月1日 総税企第50号 十三 特記事項1", "本年度改正における個人所得課税の見直しが平成３３年度"),
        ("P7a", "r8_ryuiten", "令和8年度 留意事項（令和8年1月21日 事務連絡）p.2 (1)①ア(ア)", "６５万円の最低保障額を６９万円に引き上げ"),
        ("P7b", "r8_ryuiten", "同 (1)①ア(イ)", "令和９年度分及び令和１０年度分の個人住民税に係る給与所得控除の"),
        ("P7c", "r8_ryuiten", "同 (1)①イ", "所得税における見直しに伴う所要の措置"),
        ("P7d", "r8_ryuiten", "同 (注)", "上記ア及びイの改正は、令和９年度分以後の個人住民税について適用す"),
        ("P8", "r8_kaisei_tsuchi", "令和8年4月1日 総税企第44号 一 総括的事項（１）", "（１）個人住民税のひとり親控除の額の引上げ等を行うこととした。"),
        ("P9a", "r8_gaiyo", "令和8年度税制改正の概要（地方税）", "給与所得控除の最低保障額を74万円（現行:65万円）に引き上げる"),
        ("P9b", "r8_gaiyo", "同", "※令和９年度分の個人住民税から適用（引上げ額９万円のうち、５万円は２年間の時限措置）"),
        ("P11", "toriatsukai_shichoson_r8_honbun", "総税市第25号 本文", "第２４５条の４（技術的な"),
    ]
    for cid, name, label, text in pdfc:
        check(cid, f"{name}：{label}", text, norm(text) in P[name])
    for name, kw in [("r8_kaisei_tsuchi", "給与所得控除"), ("r8_kaisei_tsuchi", "二十九条の四"), ("toriatsukai_shichoson_zenbun", "給与所得控除"),
                     ("toriatsukai_shichoson_zenbun", "所得金額調整控除"), ("toriatsukai_shichoson_zenbun", "青色申告特別控除"),
                     ("toriatsukai_shichoson_zenbun", "家内労働"), ("toriatsukai_dofuken_zenbun", "給与所得控除")]:
        RESULTS.append({"id": f"N-{name}-{kw}", "target": f"{name}（全頁）", "expect": f"「{kw}」の出現数", "ok": None, "note": str(P[name].count(kw))})

    ok = sum(1 for r in RESULTS if r["ok"] is True)
    ng = [r for r in RESULTS if r["ok"] is False]
    md = ["# R3X chiho-sochi 検査の結果", "", f"- 検査：{ok + len(ng)} 件（OK {ok}、NG {len(ng)}）。ほかに数を数えただけの行（ok=—）がある。",
          "- 法令は scripts/results/R3X_chiho-sochi_egov/fetch_log.json の download_dir の JSON、PDF は scripts/results/R3X_chiho-sochi_pdftext/*.txt を読んだ。", "",
          "| ID | 結果 | 対象 | 確かめた文字列・数えたもの | 備考 |", "|---|---|---|---|---|"]
    for r in RESULTS:
        res = "—" if r["ok"] is None else ("OK" if r["ok"] else "NG")
        md.append(f"| {r['id']} | {res} | {r['target']} | {r['expect']} | {r['note']} |")
    (OUT / "evidence.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (OUT / "checks.json").write_text(json.dumps(RESULTS, ensure_ascii=False, indent=1), encoding="utf-8")
    print("OK", ok, "NG", len(ng))
    for r in ng:
        print("NG", r["id"], r["target"])


if __name__ == "__main__":
    main()

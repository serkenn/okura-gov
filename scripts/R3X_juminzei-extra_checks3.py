"""R3X juminzei-extra（補足3）: 前の2本（R3X_juminzei-extra_checks.py・_checks2.py）で確かめていない文字列を、取得済みのテキストで機械的に確かめ、
仮説の境目を示す計算例を出す（ネットワークは使わない）。

確かめること
A. 改正附則（e-Gov の地方税法 asof 2030-01-01 に収録された改正法の附則）：
   令和4年法律第1号 附則第10条第3項・第3条第3項（令和4年1月1日前の居住は「なお従前の例による」）、
   令和8年法律第2号 附則第1条第2号（令和9年1月1日施行の部分）・附則第11条第10項、同法の附則で「特定配当等」「住宅借入金」を含む項の一覧。
B. 地方税法・施行令（e-Gov）：旧附則第5条の4（2026-01-01 の版）の中身、附則第5条の4の2 がなくなったこと、附則第5条の4 の第4項・第8項、
   「平成十九年又は平成二十年」の括弧書きの有無、附則第45条第4項・第6項、施行令第7条の3 の見出し、施行令の見出しに「住宅借入金」がないこと、
   第300条（納税管理人）に「家屋敷」がないこと、第71条の27・第71条の31（配当割の課税標準・特別徴収）。
C. 総務省の通知（PDF から取り出した文字）：取扱通知（市町村税）33の2・26(2) の見出し、取扱通知（道府県税）の「独立性」の文脈、
   令和8年 総税企第44号の「令和四年法律」「居住年が平成二十八年から令和七年まで」の出現数。
D. 地方税法等の一部を改正する法律（令和8年法律第2号）の本文 PDF（総務省）：他の法律の一部改正の見出しと、「令和四年法律第一」の出現数。
E. 自治体・総務省の案内（HTML のテキスト）：家屋敷課税の対象の書き方、均等割の額、更新日、住宅ローン控除の申告。
F. 計算例：(1) 居住年 平成28年〜令和3年の住宅借入金等特別税額控除で、基礎控除の差の加算の有無の2つの読みが結論を分けるか、
   (2) 住宅借入金等特別税額控除の後に配当割額等の控除をすること（第314条の9第1項と附則第5条の4第6項）で控除不足額（還付）が生じる例と、
       順序を逆にした場合との違い、(3) 特定配当等の種類と支払日による配当割の有無（令和8年法律第2号附則第3条第3項）、
   (4) 家屋敷課税の判定を、入力のない事実・注入のないデータについて取りうる値の全部で評価した結果。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_juminzei-extra_checks3.py

入力（読むだけ。.work/downloads の中のものは読まない）:
- scripts/results/R3X_juminzei-extra_laws/（scripts/R3X_juminzei-extra_laws.py の出力）
- scripts/results/R3X_juminzei-extra_pdftext/{shichoson,dofuken,r8_houritsu}_lines.txt（scripts/R3X_juminzei-extra_pdftext.py の出力）
- scripts/results/R3X_chiho-sochi_pdftext/r8_kaisei_tsuchi.txt（scripts/R3X_chiho-sochi_pdftext.py の出力）
- scripts/results/R3X_juminzei-extra_web/<名前>.txt（scripts/R3X_juminzei-extra_web.py の出力）
出力：scripts/results/R3X_juminzei-extra_checks3/evidence.md・checks.json・cases.md
文字列の比べ方（空白を除く）と PDF の行のつなぎ方は scripts/R3X_juminzei-extra_checks.py・_checks2.py を写した（import はしない）。
住宅借入金等特別税額控除の計算は scripts/R3X_juminzei-extra_checks.py の housing_credit を写し、加算の読みを引数にした。
"""
import itertools
import json
import pathlib
import re
import sys
from fractions import Fraction as F

ROOT = pathlib.Path(__file__).resolve().parent.parent
RES = ROOT / "scripts" / "results"
LAWS = RES / "R3X_juminzei-extra_laws"
PDFT = RES / "R3X_juminzei-extra_pdftext"
WEB = RES / "R3X_juminzei-extra_web"
SOCHI_PDFT = RES / "R3X_chiho-sochi_pdftext"
OUT = RES / "R3X_juminzei-extra_checks3"


def norm(s):
    return re.sub(r"[\s\u3000]+", "", s)


def arts(short, asof):
    return json.loads((LAWS / f"{short}_{asof}.articles.json").read_text(encoding="utf-8"))


def notice_text(path):
    """=== page N === 区切りの行テキストをつなぐ（頁番号の行を除く）。頁ごとの開始位置も返す"""
    buf, starts, page = [], [], 0
    for ln in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"=== page (\d+) ===", ln)
        if m:
            page = int(m.group(1))
            starts.append((len("".join(buf)), page))
            continue
        if ln.startswith("# file=") or re.fullmatch(r"\s*-\s*\d+\s*-\s*", ln):
            continue
        buf.append(norm(ln))
    return "".join(buf), starts


def page_at(starts, pos):
    p = None
    for off, pg in starts:
        if off <= pos:
            p = pg
    return p


def pdf_flat(path):
    """R3X_chiho-sochi_pdftext の出力（=== p.N === 区切り）をつなぐ"""
    t = path.read_text(encoding="utf-8")
    lines = [ln for ln in t.splitlines()[1:] if not ln.startswith("=== p.")]
    return norm("".join(lines))


def amend_sections():
    """amend_chiho-far_2030-01-01.md を「## 」の見出しごとに分ける"""
    secs, cur, buf = [], None, []
    for ln in (LAWS / "amend_chiho-far_2030-01-01.md").read_text(encoding="utf-8").splitlines():
        if ln.startswith("## "):
            if cur is not None:
                secs.append((cur, "\n".join(buf)))
            cur, buf = ln[3:].strip(), []
        elif cur is not None:
            buf.append(ln)
    if cur is not None:
        secs.append((cur, "\n".join(buf)))
    return secs


RESULTS = []


def rec(cid, target, expect, ok, note=""):
    RESULTS.append({"id": cid, "target": target, "expect": expect, "ok": ok, "note": note})


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ A. 改正附則
    secs = amend_sections()

    def sec(law, art, para):
        for h, body in secs:
            if h.startswith(law) and f"附則 第{art}条" in h and h.endswith(f"第{para}項"):
                return body
        return None

    R4 = "令和四年三月三一日法律第一号"
    R8 = "令和八年三月三一日法律第二号"
    for cid, law, art, para, needle, desc in [
        ("A11", R4, 10, 3, "市町村民税の所得割の納税義務者が同日前に旧租税特別措置法第四十一条第一項に規定する居住用家屋若しくは既存住宅又は増改築等をした家屋（当該増改築等に係る部分に限る。第六項及び第七項において同じ。）を同条第一項の定めるところによりその者の居住の用に供した場合については、なお従前の例による。",
         "令和4年法律第1号 附則第10条第3項：令和4年1月1日前の居住は従前の例（市町村民税）"),
        ("A11b", R4, 10, 3, "新法附則第五条の四の二第五項から第八項までの規定は、市町村民税の所得割の納税義務者が令和四年一月一日以後に",
         "同 前段：令和4年1月1日以後の居住に新法を適用"),
        ("A12", R4, 3, 3, "新法附則第五条の四の二第一項から第四項までの規定は、道府県民税の所得割の納税義務者が令和四年一月一日以後に",
         "令和4年法律第1号 附則第3条第3項（道府県民税）"),
        ("A12b", R4, 3, 3, "なお従前の例による。", "同 後段：従前の例"),
        ("A13", R8, 11, 10, "九年一月新法附則第五条の四第五項から第八項までの規定は、市町村民税の所得割の納税義務者が令和八年一月一日以後に",
         "令和8年法律第2号 附則第11条第10項 前段"),
        ("A13b", R8, 11, 10, "を同条第一項の定めるところによりその者の居住の用に供した場合については、なお従前の例による。",
         "同 後段：令和8年1月1日前の居住は従前の例"),
        ("A14", R8, 1, 1, "同法附則第五条の四の二第一項の改正規定（「令和二十年度」を「令和二十五年度」に改める部分、「令和七年」を「令和十二年」に改める部分",
         "令和8年法律第2号 附則第1条第2号：令和9年1月1日施行の部分（延長）"),
        ("A14b", R8, 1, 1, "附則第三条第二項、第九項、第十項及び第十二項並びに第十一条第二項及び第八項から第十項までの規定　令和九年一月一日",
         "同 第2号の施行日"),
    ]:
        body = sec(law, art, para)
        ok = body is not None and norm(needle) in norm(body)
        rec(cid, desc, needle, ok)

    r8secs = [(h, b) for h, b in secs if h.startswith(R8)]
    tok = sorted(re.sub(r"^.*?附則 ", "附則 ", h) for h, b in r8secs if "特定配当等" in b)
    rec("A15", "令和8年法律第2号の附則の項のうち「特定配当等」を含むもの", "['附則 第3条 （道府県民税に関する経過措置） 第3項'] だけ",
        tok == ["附則 第3条 （道府県民税に関する経過措置） 第3項"], json.dumps(tok, ensure_ascii=False))
    th = sorted(re.sub(r"^.*?附則 ", "附則 ", h) for h, b in r8secs if ("住宅借入金" in b or "附則第五条の四" in b))
    rec("A16", "令和8年法律第2号の附則の項のうち「住宅借入金」「附則第五条の四」を含むもの（一覧）", "—", None, json.dumps(th, ensure_ascii=False))
    t48 = sorted(h for h, b in secs if "四十八万円" in b)
    rec("A17", "改正附則（令和の改正法）の項のうち「四十八万円」を含むもの", "0 件", len(t48) == 0, json.dumps(t48, ensure_ascii=False))

    # ------------------------------------------------------------ B. 法令（e-Gov）
    c26 = arts("chiho", "2026-01-01")["articles"]
    rec("B01", "地方税法 2026-01-01 の版の附則第5条の4（旧）", "平成二十年度から平成二十八年度まで／居住年 平成11年〜18年",
        norm("平成二十年度から平成二十八年度までの各年度分の個人の道府県民税に限り") in norm(c26["附則:5_4"])
        and norm("が平成十一年から平成十八年までの各年である場合に限る。") in norm(c26["附則:5_4"]))
    for asof in ["2026-04-01", "2026-11-09", "2027-01-01", "2028-01-01"]:
        d = arts("chiho", asof)
        rec(f"B02-{asof}", f"地方税法 {asof} の版に附則第5条の4の2 がない", "missing に 附則:5_4_2", "附則:5_4_2" in d["missing"])
    a1109 = arts("chiho", "2026-11-09")["articles"]
    a2701 = arts("chiho", "2027-01-01")["articles"]
    for cid, needle, desc in [
        ("B03", "所得割の納税義務者が前年分の所得税につき租税特別措置法第四十一条又は第四十一条の二の二の規定の適用を受けた場合", "附則第5条の4 第1項・第5項の要件（前年分の所得税で措法第41条等の適用を受けた場合）"),
        ("B03b", "４　前二項に定めるもののほか、第一項の規定の適用に関し必要な事項は、政令で定める。", "附則第5条の4第4項"),
        ("B03c", "８　前二項に定めるもののほか、第五項の規定の適用に関し必要な事項は、政令で定める。", "附則第5条の4第8項"),
    ]:
        rec(cid, desc + "（2026-11-09）", needle, norm(needle) in norm(a1109["附則:5_4"]))
    h1920 = "（平成十九年又は平成二十年の居住年に係る同項に規定する住宅借入金等の金額を有する場合には"
    rec("B04", "附則第5条の4 第1項第1号・第5項第1号の平成19年・20年の括弧書き：2026-11-09 にあり、2027-01-01 にない", h1920,
        norm(h1920) in norm(a1109["附則:5_4"]) and norm(h1920) not in norm(a2701["附則:5_4"]))
    for cid, needle, desc in [
        ("B05", "市町村民税の所得割の納税義務者が前年分の所得税につき震災特例法第十三条第一項の規定の適用を受けた場合における附則第五条の四の規定の適用については", "附則第45条第4項"),
        ("B05b", "前項の規定により読み替えて適用される附則第五条の四第五項中「百分の三」とあるのは「百分の四・二」と", "附則第45条第6項"),
    ]:
        rec(cid, desc + "（2026-11-09）", needle, norm(needle) in norm(a1109["附則:45"]))
    idx = {a: (LAWS / f"index_chiho-rei_{a}.txt").read_text(encoding="utf-8").splitlines() for a in ["2026-01-01", "2026-11-09", "2027-01-01"]}
    rec("B06", "施行令第7条の3 の見出し：2026-01-01 は空（削除）、2026-11-09 は「法第二十三条第一項第十五号ロの政令で定めるもの」", "7_3\\t / 7_3\\t（法第二十三条…）",
        "7_3\t" in idx["2026-01-01"] and "7_3\t（法第二十三条第一項第十五号ロの政令で定めるもの）" in idx["2026-11-09"])
    for a in ["2026-11-09", "2027-01-01"]:
        n_j = sum(1 for ln in idx[a] if "住宅借入金" in ln)
        n_h = sum(1 for ln in idx[a] if "配当割額又は株式等譲渡所得割額" in ln)
        rec(f"B07-{a}", f"施行令（{a}）の条の見出しで「住宅借入金」を含む行の数／「配当割額又は株式等譲渡所得割額」を含む行の数", "0 / 3", n_j == 0 and n_h == 3, f"{n_j} / {n_h}")
    rec("B08", "第300条（納税管理人）の第1項の場所の列挙に「家屋敷」がない（2026-11-09）", "「家屋敷」を含まない", "家屋敷" not in a1109["本則:300"])
    for cid, key, needle, desc in [
        ("B09", "本則:71_27", "配当割の課税標準は、支払を受けるべき特定配当等の額とする。", "第71条の27第1項"),
        ("B09b", "本則:71_31", "特定配当等の支払を受けるべき日現在において道府県内に住所を有する個人に対して特定配当等の支払をする者", "第71条の31第1項"),
        ("B10", "本則:24", "第二号及び第四号に掲げる者に対しては均等割額により、", "第24条第1項柱書（第2号の者は均等割額）"),
    ]:
        rec(cid, desc + "（2026-11-09）", needle, norm(needle) in norm(a1109[key]))

    # ------------------------------------------------------------ C. 通知
    st, sst = notice_text(PDFT / "shichoson_lines.txt")
    dt, dst = notice_text(PDFT / "dofuken_lines.txt")
    for cid, t, starts, needle, desc in [
        ("C01", st, sst, "個人の市町村民税（法第２９４条第１項第２号に掲げる者に対して課する均等割及び法第３２８条の規定により課する所得割に限る。以下この項、３５及び３９において同じ。）",
         "取扱通知（市町村税）第2章第4節 33の2"),
        ("C02", st, sst, "２６調整控除の適用に当たっては、次の諸点に留意すること。（法３１４の６）(１)合計課税所得金額は、課税総所得金額、課税退職所得金額及び課税山林所得金額の合計額であり、上場株式等に係る配当所得等の金額、土地等に係る課税事業所得等の金額、課税長期譲渡所得金額、課税短期譲渡所得金額、一般株式等に係る課税譲渡所得等の金額、上場株式等に係る課税譲渡所得等の金額、特定暗号資産に係る課税譲渡所得等の金額又は先物取引に係る課税雑所得等の金額を含まないものであること。(２)この控除の額は、他の税額控除に先立ち",
         "同 26(2)「他の税額控除に先立ち」は 26（調整控除）の中の文"),
        ("C03", st, sst, "２８法附則第５条の４の規定に基づく住宅借入金等特別税額控除の適用に当たっては、次の諸点に留意すること。（法附則５の４⑤～⑧）",
         "同 28 の柱書"),
        ("C04", st, sst, "６事務所又は事業所(１)事務所又は事業所（以下６において「事務所等」という。）とは、", "第1章第1節 6（事務所等の定義。家屋敷の定義はこの項にない）"),
    ]:
        pos = t.find(norm(needle))
        rec(cid, desc, needle, pos >= 0, f"p.{page_at(starts, pos)}" if pos >= 0 else "")
    ctx = [dt[max(0, m.start() - 300):m.end() + 300] for m in re.finditer("独立性", dt)]
    rec("C05", "取扱通知（道府県税）の「独立性」の出現（すべて不動産取得税の文脈か）", "出現 1・文脈に「不動産取得税」",
        len(ctx) == 1 and all("不動産取得税" in c for c in ctx), f"出現 {len(ctx)}；p.{[page_at(dst, m.start()) for m in re.finditer('独立性', dt)]}")
    rec("C06", "取扱通知（市町村税・道府県税）の「家屋敷」の出現数", "1 / 1", st.count("家屋敷") == 1 and dt.count("家屋敷") == 1,
        f"{st.count('家屋敷')} / {dt.count('家屋敷')}")
    i28, i283 = st.find(norm("２８法附則第５条の４の規定に基づく")), st.find(norm("２８の３所得税については"))
    sec28 = st[i28:i283] if 0 <= i28 < i283 else ""
    rec("C09", "取扱通知（市町村税）28（柱書〜(4)。28の3 の前まで）に「基礎控除」「４８万円」「四十八万円」がない", "0 / 0 / 0",
        bool(sec28) and all(sec28.count(w) == 0 for w in ("基礎控除", "４８万円", "四十八万円")),
        f"28 の文字数 {len(sec28)}；" + " / ".join(str(sec28.count(w)) for w in ("基礎控除", "４８万円", "四十八万円")))
    kt = pdf_flat(SOCHI_PDFT / "r8_kaisei_tsuchi.txt")
    rec("C07", "令和8年 総税企第44号の「令和四年法律」の出現数", "0", kt.count("令和四年法律") == 0, str(kt.count("令和四年法律")))
    n28 = kt.count(norm("居住年が平成二十八年から令和七年までの各年である場合に係る控除限"))
    rec("C08", "令和8年 総税企第44号の「居住年が平成二十八年から令和七年までの各年である場合に係る控除限」の出現数（道府県税・市町村税）", "2", n28 == 2, str(n28))

    # ------------------------------------------------------------ D. 令和8年法律第2号の本文 PDF
    ht, hst = notice_text(PDFT / "r8_houritsu_lines.txt")
    caps = {}
    for m in re.finditer(r"（[^（）]{2,50}?の一部改正）", ht):
        caps[m.group(0)] = caps.get(m.group(0), 0) + 1
    n_cap = caps.get("（地方税法等の一部を改正する法律の一部改正）", 0)
    rec("D01", "令和8年法律第2号の本文 PDF：見出し「（地方税法等の一部を改正する法律の一部改正）」の数", "2", n_cap == 2,
        "見出しの一覧：" + json.dumps(caps, ensure_ascii=False))
    amended = sorted({m.group(1) for m in re.finditer(r"地方税法等の一部を改正する(?:等の)?法律（((?:平成|令和)[^）]{1,20}号)）の一部を次のように改正する", ht)})
    rec("D02", "同：「地方税法等の一部を改正する（等の）法律（…号）の一部を次のように改正する」の法律番号", "平成二十六年法律第四号・平成三十一年法律第二号を含み、令和四年法律第一号を含まない",
        "平成二十六年法律第四号" in amended and "平成三十一年法律第二号" in amended and "令和四年法律第一号" not in amended, json.dumps(amended, ensure_ascii=False))
    rec("D03", "同：「令和四年法律第一」の出現数", "0", ht.count("令和四年法律第一") == 0, str(ht.count("令和四年法律第一")))
    p48 = sorted({page_at(hst, m.start()) for m in re.finditer("四十八万円", ht)})
    rec("D04", "同：「四十八万円」が出る頁（PDF の頁）", "—", None, str(p48))
    rec("D05", "同：附則第5条の4の2 の改正規定の「（居住年が平成二十八年から令和七年までの」", "含む", norm("（居住年が平成二十八年から令和七年までの") in ht)

    # ------------------------------------------------------------ E. 案内
    def web(nm):
        return norm((WEB / f"{nm}.txt").read_text(encoding="utf-8"))
    for cid, nm, needle, desc in [
        ("E01", "kumamoto_ieyashiki", "(1)熊本市内に本人または家族が住むことを目的とした住宅を持っている方(※借家・持家は関係ありません)", "熊本市：単身赴任の条件(1)"),
        ("E02", "kumamoto_ieyashiki", "※家屋敷課税対象者の配偶者の方は、市県民税申告が必要です", "熊本市：配偶者の申告"),
        ("E03", "kumamoto_ieyashiki", "最終更新日：2022年8月19日", "熊本市：更新日"),
        ("E03b", "kumamoto_ieyashiki", "※家屋敷とは、自己または家族居住の目的で、住所地以外の場所に設けられた住宅で、「いつでも自由に居住できる状態である」建物のことをいいます。", "熊本市：家屋敷とは"),
        ("E03c", "kumamoto_ieyashiki", "(※住民登録は関係ありません）", "熊本市：住民登録は関係ない"),
        ("E04", "kagoshima_ieyashiki", "鹿児島市に自己または家族が住むことを目的とした自由に居住することができる独立性のある住宅、事務所・事業所を持っている", "鹿児島市：対象1・2の3つ目"),
        ("E05", "kagoshima_ieyashiki", "均等割：4,500円（市民税：3,000円＋県民税：1,500円）", "鹿児島市：均等割の額"),
        ("E06", "kagoshima_ieyashiki", "更新日：2025年10月1日", "鹿児島市：更新日"),
        ("E07", "funabashi_ieyashiki", "均等割 4,000円（市民税3,000円＋県民税1,000円）", "船橋市：均等割の額"),
        ("E08", "funabashi_ieyashiki", "※均等割については月割課税は行っていません。一括納付となります。", "船橋市：月割なし・一括"),
        ("E09", "funabashi_ieyashiki", "更新日：令和6(2024)年5月2日", "船橋市：更新日"),
        ("E10", "soumu_juutaku_loan", "源泉徴収税額の項目が0円のときのみ、住宅ローン控除が適用になる場合があります。", "総務省：算出例の注"),
        ("E11", "soumu_juutaku_loan", "※確定申告や年末調整で、住宅ローン控除を受ける方の手続きは、今までと変わりません。", "総務省：手続"),
        ("E12", "soumu_juutaku_loan", "※ 期限までに申告されなかった場合は、自動的に、申告を不要とする新たな住宅ローン控除の適用を受けることになります。", "総務省：旧制度（平成11年〜18年入居）の申告"),
        ("E13", "suginami_juutaku", "年末調整を行う勤務先から提出される給与支払報告書や所得税の確定申告書等から内容を確認します。", "杉並区：情報の出所"),
        ("E14", "suginami_juutaku", "更新日:2026年6月13日", "杉並区：更新日"),
        ("E15", "meguro_kabu", "更新日：2025年1月27日", "目黒区：更新日"),
    ]:
        rec(cid, desc, needle, norm(needle) in web(nm))

    # ------------------------------------------------------------ 出力（evidence）
    ev = ["# R3X juminzei-extra（補足3）：検査の結果", "", "生成：scripts/R3X_juminzei-extra_checks3.py。文字列は空白を除いて比べた。結果 — は数えただけ（判定なし）。", "",
          "| ID | 対象 | 期待 | 結果 | 備考 |", "|---|---|---|---|---|"]
    for r in RESULTS:
        res = "—" if r["ok"] is None else ("OK" if r["ok"] else "NG")
        exp = r["expect"] if len(r["expect"]) <= 60 else r["expect"][:60] + "…"
        ev.append(f"| {r['id']} | {r['target']} | {exp} | {res} | {r['note']} |")
    n_ok = sum(1 for r in RESULTS if r["ok"] is True)
    n_ng = sum(1 for r in RESULTS if r["ok"] is False)
    ev += ["", f"検査 {n_ok + n_ng} 件（OK {n_ok}、NG {n_ng}）。ほかに数えただけの行 {sum(1 for r in RESULTS if r['ok'] is None)} 件。"]
    (OUT / "evidence.md").write_text("\n".join(ev) + "\n", encoding="utf-8")
    (OUT / "checks.json").write_text(json.dumps(RESULTS, ensure_ascii=False, indent=1), encoding="utf-8")

    # ------------------------------------------------------------ F. 計算例
    cs = ["# R3X juminzei-extra（補足3）：計算例", "", "生成：scripts/R3X_juminzei-extra_checks3.py。金額は Fraction（1円未満を丸めない）。入力の値は架空。",
          "所得税の基礎控除の額などは入力として与えた値で、ある年分の実際の額を示すものではない。", ""]

    # F1 加算の2つの読み
    cs += ["## F1 住宅借入金等特別税額控除：居住年 平成28年〜令和3年で、基礎控除の差の加算の2つの読み", "",
           "- 読み A：現行の附則第5条の4 第5項の文言どおり（居住年 平成28年〜令和7年は加算あり）。",
           "- 読み B：令和4年法律第1号附則第10条第3項の「なお従前の例による」で、令和4年1月1日前の居住には令和4年改正前の文言（加算の文言がない）が使われる、と読む（居住年 令和3年以前は加算なし）。",
           "- 2つの読みで控除額が同じなら断定、違えば未確定（D21 R6 と同じ扱いを法令の読みに当てはめた場合）。一般の市・一般の取得・市町村民税と道府県民税の合計。", "",
           "| ID | 居住年 | ①−② | 課税総所得金額等 | 基礎控除の額 | 読み A | 読み B | 結論 |", "|---|---|---|---|---|---|---|---|"]

    def credit(kyojyunen, diff, taxable, basic, add_rule, shitei=False):
        add = 0
        if 2016 <= kyojyunen <= 2025 and not (add_rule == "B" and kyojyunen <= 2021):
            add = max(0, basic - 480000)
        base = taxable + add
        tot = F(0)
        for share, rate, cap in ((F(3, 5), F(3, 100), 58500), (F(2, 5), F(2, 100), 39000)) if not shitei else ((F(4, 5), F(4, 100), 78000), (F(1, 5), F(1, 100), 19500)):
            tot += min(diff * share, min(base * rate, F(cap)))
        return tot

    for cid, ky, diff, tx, bd in [("HX1", 2018, 240000, 1000000, 880000), ("HX2", 2018, 240000, 3000000, 880000),
                                  ("HX3", 2018, 30000, 1000000, 880000), ("HX4", 2021, 240000, 1000000, 580000),
                                  ("HX5", 2023, 240000, 1000000, 880000)]:
        a, b = credit(ky, diff, tx, bd, "A"), credit(ky, diff, tx, bd, "B")
        cs.append(f"| {cid} | {ky} | {diff} | {tx} | {bd} | {a} | {b} | {'断定' if a == b else '未確定'} |")
    cs += ["", "HX5（居住年 2023）は令和4年1月1日以後の居住なので読み B でも加算あり（令和4年法律第1号附則第10条第3項前段）。", ""]

    # F2 住宅→配当割の順序
    cs += ["## F2 住宅借入金等特別税額控除の後に配当割額等の控除をする（第314条の9第1項・附則第5条の4第6項）", "",
           "市町村民税だけで示す。所得割（調整控除の後）＝ S、住宅借入金等特別税額控除額（限度後）＝ H、配当割額等 × 3/5 ＝ D。", "",
           "| ID | S | H | D | 法令の順（H→D）：所得割 | 控除不足額（還付・充当） | 差引 | 逆の順（D→H）：所得割 | 逆の順の控除不足額 | 逆の順の差引 |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for cid, S, H, D in [("HD1", 10000, 10000, 3000), ("HD2", 20000, 10000, 3000), ("HD3", 10000, 8000, 3000), ("HD4", 0, 5000, 3000)]:
        s1 = max(0, S - H)
        used = min(s1, D)
        short = D - used
        net = s1 - used - short
        r1 = max(0, S - D)
        short_r = D - min(S, D)
        r2 = max(0, r1 - H)
        net_r = r2 - short_r
        cs.append(f"| {cid} | {S} | {H} | {D} | {s1 - used} | {short} | {net} | {r2} | {short_r} | {net_r} |")
    cs += ["", "差引 ＝ 所得割（控除後）− 控除不足額。法令の順では、住宅借入金等特別税額控除で所得割が 0 になると、配当割額等は控除不足額として還付・充当に回る。", ""]

    # F3 配当割の有無
    cs += ["## F3 特定配当等の種類と支払日による配当割の有無（第23条第1項第15号、令和8年法律第2号附則第3条第3項）", "",
           "種類：イ＝措法第8条の4第1項の上場株式等の配当等、ロ＝措法第9条の3第1号の配当等（イと政令で定めるものを除く）。", "",
           "| ID | 種類 | 支払を受けるべき日 | 住民税の年度 | 特定配当等か | 配当割 | 第313条第12項で総所得金額から除くか（確定申告書に記載がないとき） |",
           "|---|---|---|---|---|---|---|"]

    def tokutei(kind, paid):
        if kind == "イ":
            return True
        if kind == "ロ":
            return paid >= "2026-04-01"
        return False

    for cid, kind, paid in [("DX1", "イ", "2025-06-30"), ("DX2", "ロ", "2025-06-30"), ("DX3", "ロ", "2026-03-31"), ("DX4", "ロ", "2026-04-01"),
                            ("DX5", "ロ", "2026-12-10"), ("DX6", "イ", "2026-12-10")]:
        nendo = "令和" + str(int(paid[:4]) - 2018 + 1) + "年度"
        tk = tokutei(kind, paid)
        excl = "除く（申告不要）" if (tk and kind == "イ") else "除かない（総所得金額に入る）"
        cs.append(f"| {cid} | {kind} | {paid} | {nendo} | {'はい' if tk else 'いいえ'} | {'課される（5%）' if tk else '課されない'} | {excl} |")
    cs += ["", "ロ に当たるのは、令和8年 総税企第44号の言い方で「自己の同族会社である法人との合計で株式等の保有割合が百分の三以上となる内国法人から支払を受ける上場株式等の配当等」。",
           "ロ は施行日（令和8年4月1日）前の支払では旧法の特定配当等に当たらない（旧第23条第1項第15号はイとハに当たるものだけ）ので、配当割の対象外。", ""]

    # F4 家屋敷課税の判定（取りうる値の全部で評価）
    cs += ["## F4 家屋敷課税（第294条第1項第2号・第24条第1項第2号）の判定を、入力のない値について取りうる値の全部で評価", "",
           "判定の手順（仮説 H1 の写し）：",
           "1. 賦課期日（1月1日）にその市町村（指定都市は区）に住所がある → 家屋敷課税ではない（住所地として課税）。",
           "2. その市町村に家屋敷がない → 課税しない。",
           "3. 法の施行地に住所がない → 均等割を課す（第295条第1項ただし書・取扱通知 4の3。第295条第3項は「施行地に住所を有する者」に限る）。",
           "4. 第295条第1項（生活扶助、障害者等で前年の合計所得金額 135万円以下）に当たる → 課さない。",
           "5. 前年の合計所得金額がその市町村の条例の額以下（第295条第3項）→ 課さない。",
           "6. 市町村の運用の型 B（熊本市の案内：同じ市内に住む配偶者が市民税・県民税を課されていない場合に限る）で配偶者が課されている → 課さない（法令ではなく運用。注入するデータ）。",
           "7. それ以外 → 均等割（市町村民税・道府県民税）を課す。森林環境税は課さない（森林環境税法第3条：住所を有する個人）。", "",
           "None は「入力なし／注入なし」。取りうる値の全部で結論が同じなら断定、違えば未確定と、結論を分けた項目を出す。", "",
           "| ID | 住所あり | 家屋敷あり | 施行地に住所 | 295①該当 | 条例の額以下 | 運用の型 | 配偶者が課税 | 結論 | 結論を分けた項目 |",
           "|---|---|---|---|---|---|---|---|---|---|"]

    def decide(jusho_here, house, kokunai, hikazei1, le_jorei, rule, spouse_taxed):
        if jusho_here:
            return "対象外（住所地）"
        if not house:
            return "課さない"
        if not kokunai:
            return "課す"
        if hikazei1:
            return "課さない"
        if le_jorei:
            return "課さない"
        if rule == "B" and spouse_taxed:
            return "課さない"
        return "課す"

    domains = {"jusho_here": [True, False], "house": [True, False], "kokunai": [True, False], "hikazei1": [True, False],
               "le_jorei": [True, False], "rule": ["A", "B"], "spouse_taxed": [True, False]}
    names = ["jusho_here", "house", "kokunai", "hikazei1", "le_jorei", "rule", "spouse_taxed"]
    for cid, vals in [
        ("IY1", dict(jusho_here=False, house=True, kokunai=True, hikazei1=False, le_jorei=False, rule="A", spouse_taxed=True)),
        ("IY2", dict(jusho_here=False, house=True, kokunai=True, hikazei1=False, le_jorei=False, rule=None, spouse_taxed=True)),
        ("IY3", dict(jusho_here=False, house=True, kokunai=True, hikazei1=False, le_jorei=False, rule=None, spouse_taxed=False)),
        ("IY4", dict(jusho_here=False, house=True, kokunai=True, hikazei1=False, le_jorei=None, rule="A", spouse_taxed=False)),
        ("IY5", dict(jusho_here=False, house=True, kokunai=False, hikazei1=None, le_jorei=None, rule=None, spouse_taxed=None)),
        ("IY6", dict(jusho_here=False, house=None, kokunai=True, hikazei1=False, le_jorei=False, rule="A", spouse_taxed=False)),
        ("IY7", dict(jusho_here=False, house=True, kokunai=True, hikazei1=True, le_jorei=None, rule=None, spouse_taxed=None)),
    ]:
        free = [n for n in names if vals[n] is None]
        outs = {}
        for combo in itertools.product(*[domains[n] for n in free]):
            v = dict(vals)
            v.update(dict(zip(free, combo)))
            outs.setdefault(decide(**v), []).append(dict(zip(free, combo)))
        if len(outs) == 1:
            concl, why = next(iter(outs)), "—"
        else:
            concl = "未確定（" + "／".join(sorted(outs)) + "）"
            why = []
            for n in free:
                # 結論を分けた項目：その項目だけを動かして結論が変わる組があるか
                changed = False
                for o, lst in outs.items():
                    for c in lst:
                        for val in domains[n]:
                            c2 = dict(c)
                            c2[n] = val
                            v = dict(vals)
                            v.update(c2)
                            if decide(**v) != o:
                                changed = True
                if changed:
                    why.append(n)
            why = ", ".join(why)
        cell = lambda x: "—" if x is None else ("はい" if x is True else ("いいえ" if x is False else x))
        cs.append(f"| {cid} | {cell(vals['jusho_here'])} | {cell(vals['house'])} | {cell(vals['kokunai'])} | {cell(vals['hikazei1'])} | "
                  f"{cell(vals['le_jorei'])} | {cell(vals['rule'])} | {cell(vals['spouse_taxed'])} | {concl} | {why} |")
    cs += ["", "項目名：jusho_here＝その市町村（区）に住所、house＝家屋敷、kokunai＝施行地に住所、hikazei1＝第295条第1項、le_jorei＝第295条第3項の条例の額以下、"
           "rule＝運用の型、spouse_taxed＝その市町村に住む配偶者が課税されているか。", ""]
    (OUT / "cases.md").write_text("\n".join(cs) + "\n", encoding="utf-8")

    print(f"OK {n_ok} NG {n_ng}")
    return 0 if n_ng == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

"""R2X_gaps: 取得済みの条文・公表資料のテキストから、残っていた個別の未解決（6項目）を機械的に確かめる。ネットワークは使わない。

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_gaps_check.py

入力（すべて先に実行したスクリプトの出力。読むだけ）
- scripts/results/R2X_gaps_egov/        （scripts/R2X_gaps_egov.py の出力）
- scripts/results/R2X_gaps_web/         （scripts/R2X_gaps_web.py の出力）
- scripts/results/R1_egov_articles/     （scripts/R1_egov_articles.py の出力。扶養親族の要件、措法41の16の2、所法83の2・84の2）
- scripts/results/IMPL_kyuyo_fetch/     （scripts/IMPL_kyuyo_fetch.py の出力。措法27 の版ごとの額）
- .work/downloads/<R2X_gaps_egov の取得ディレクトリ>/*.json（所得税法・同施行規則・地方税法の生データ。データとして読むだけ。
   改正法令の附則と地方税法の全文の語句を探すのに使う）

出力: scripts/results/R2X_gaps_check/checks.json と checks.md
"""
import hashlib
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
RES = ROOT / "scripts" / "results"
EG = RES / "R2X_gaps_egov"
WEB = RES / "R2X_gaps_web"
OUT = RES / "R2X_gaps_check"

KD = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
SMALL = {"十": 10, "百": 100, "千": 1000}
BIG = {"万": 10_000, "億": 100_000_000}


def kanji_int(s):
    """漢数字（例：二千三百五十万、六十九万千、千万）を整数にする。"""
    total, sect, num = 0, 0, 0
    for ch in s:
        if ch in KD:
            num = KD[ch]
        elif ch in SMALL:
            sect += (num or 1) * SMALL[ch]
            num = 0
        elif ch in BIG:
            sect += num
            total += (sect or 1) * BIG[ch]
            sect, num = 0, 0
        else:
            raise ValueError(f"漢数字でない文字: {ch!r} in {s!r}")
    return total + sect + num


YEN = re.compile(r"([〇一二三四五六七八九十百千万億]+)円")


def read(p):
    return pathlib.Path(p).read_text(encoding="utf-8")


def section(text, start_pat, end_pat=r"^## "):
    """text の中で start_pat に一致する行から、次の end_pat の行の前まで。"""
    lines = text.splitlines()
    out, on = [], False
    for ln in lines:
        if on and re.match(end_pat, ln):
            break
        if not on and re.search(start_pat, ln):
            on = True
        if on:
            out.append(ln)
    return "\n".join(out)


def header_rev(text):
    m = re.search(r"law_revision_id=(\S+)", text)
    return m.group(1) if m else None


# ---------------------------------------------------------------- (1) 勤労学生
def check_kinro():
    res = {}
    for asof in ["2025-12-31", "2026-12-31", "2027-01-01"]:
        t = read(EG / f"shotoku_asof{asof}.txt")
        item = section(t, r"^## 本則 Num=2 第1項 第32号")
        m = re.search(r"合計所得金額が([〇一二三四五六七八九十百千万]+)円以下であり", item)
        res[asof] = {"law_revision_id": header_rev(t),
                     "has_phrase_jiko_no_kinro": "自己の勤労に基づいて得た事業所得、給与所得、退職所得又は雑所得" in item,
                     "goukei_limit": kanji_int(m.group(1)) if m else None,
                     "kyuyo_igai_limit": kanji_int(re.search(r"給与所得等以外の所得に係る部分の金額が([〇一二三四五六七八九十百千万]+)円以下", item).group(1))}
    # 国税庁の資料で「勤労」「アフィリエイト」が出る行
    files = {
        "ta_1175": WEB / "nta" / "ta_1175.txt", "kihon_01_07": WEB / "nta" / "kihon_01_07.txt",
        "tebiki_r07_3_3_15": WEB / "nta" / "tebiki_r07_3_3_15.txt", "nencho2025_qa": WEB / "nta" / "nencho2025_qa.txt",
        "nencho2026_qa": WEB / "nta" / "nencho2026_qa.txt", "keisan_r7_kinro_cid472": WEB / "keisan" / "keisan_r7_kinro_cid472.txt",
        "tokushu_chui": WEB / "nta" / "tokushu_chui.txt", "ta_1500": WEB / "nta" / "ta_1500.txt", "kihon_04_09": WEB / "nta" / "kihon_04_09.txt",
    }
    kw_kinro = re.compile(r"勤労")
    kw_net = re.compile(r"アフィリエイト|広告収入|広告料|ドロップシッピング|ネット通販|転売|動画配信")
    hits = {}
    for k, p in files.items():
        lines = read(p).splitlines()
        body = [ln for ln in lines if not ln.startswith("#")]
        kin = [ln for ln in body if kw_kinro.search(ln) and "勤労学生控除｜" not in ln]
        net = [ln for ln in body if kw_net.search(ln)]
        both = [ln for ln in body if kw_kinro.search(ln) and kw_net.search(ln)]
        hits[k] = {"lines_with_kinro": len(kin), "lines_with_net_income_words": len(net), "lines_with_both": len(both),
                   "sample_kinro": [ln[:200] for ln in kin[:8]], "sample_net": [ln[:240] for ln in net[:3]]}
    # 所得税基本通達 2-43〜2-45の2 の見出しと、「自己の勤労」の語の有無
    k = read(WEB / "nta" / "kihon_01_07.txt")
    kinro_part = section(k, r"〔勤労学生（第32号関係）〕", r"^〔")
    items = re.findall(r"^(2－4[3-5](?:の２)?)", kinro_part, re.M)
    res["kihon_tsutatsu"] = {"items_in_kinro_section": items, "has_jiko_no_kinro": "自己の勤労" in kinro_part,
                             "has_kinro_ni_motozuku": "勤労に基づ" in kinro_part}
    res["nta_hits"] = hits
    # 所得税法の全文（生データ）で「勤労に基づ」「勤労による」を含む条を探す（定義の規定があるかの確認）
    log = json.loads(read(EG / "fetch_log.json"))
    dl = ROOT / log["download_dir"]
    def inline(n):
        if isinstance(n, str):
            return n
        if n.get("tag") == "Rt":
            return ""
        return "".join(inline(c) for c in n.get("children", []))
    locs = {}
    for f in log["fetches"]:
        if f["short"] != "shotoku":
            continue
        d = json.loads((dl / f"{f['law_id']}_{f['asof']}.json").read_text(encoding="utf-8"))
        found = []
        def walk(n, path):
            if isinstance(n, dict):
                if n.get("tag") == "Article":
                    t = inline(n)
                    for kw in ["勤労に基づ", "勤労による", "勤労により"]:
                        if kw in t:
                            part = "附則" if any(p == "SupplProvision" for p in path) else "本則"
                            found.append({"part": part, "article": n["attr"].get("Num"), "keyword": kw, "count": t.count(kw)})
                for c in n.get("children", []):
                    walk(c, path + (n.get("tag"),))
        walk(d["law_full_text"], ())
        locs[f["asof"]] = found
    res["shotoku_fulltext_kinro"] = locs
    return res


# ---------------------------------------------------------------- (2) TA No.1810
def ta1810_notes(path):
    t = read(path)
    m = re.search(r"\[(令和\d+年4月1日現在法令等)\]", t)
    lines = t.splitlines()
    i = next(j for j, ln in enumerate(lines) if ln.startswith("注意事項"))
    note2 = [ln for ln in lines[i:i + 8] if ln.startswith("（2）") or ln.startswith("（注）") or ln.startswith("また、令和2年分")]
    return {"as_of_label": m.group(1) if m else None, "sha256_file_text": hashlib.sha256(t.encode("utf-8")).hexdigest(), "note2": note2}


def check_1810():
    # 条文の値
    s7 = read(RES / "R1_egov_articles" / "shotoku_2025-12-31.txt")
    s8 = read(RES / "R1_egov_articles" / "shotoku_2026-12-01.txt")
    def fuyo_limit(t, head="三十四　扶養親族"):
        line = next(ln for ln in t.splitlines() if ln.strip().startswith(head))
        return kanji_int(re.search(r"合計所得金額が([〇一二三四五六七八九十百千万]+)円以下である者をいう", line).group(1))
    def art(t, num):
        return section(t, rf"^## Num={num}$")
    def tokutei_upper(t):
        a = art(t, "84_2")
        return kanji_int(re.search(r"合計所得金額が([〇一二三四五六七八九十百千万]+)円以下", a).group(1)) if a else None
    def haigu_toku_upper(t):
        a = art(t, "83_2")
        vals = [kanji_int(x) for x in re.findall(r"合計所得金額が([〇一二三四五六七八九十百千万]+)円以下", a)]
        return vals
    k7 = read(EG / "shotoku_asof2025-12-31.txt")
    k8 = read(EG / "shotoku_asof2026-12-31.txt")
    def kiso_honsoku(t):
        a = section(t, r"^## 本則 Num=86")
        return kanji_int(re.search(r"二千三百五十万円以下である場合　([〇一二三四五六七八九十百千万]+)円", a).group(1))
    so7 = read(RES / "R1_egov_articles" / "sochi_2025-12-31.txt")
    so8 = read(RES / "R1_egov_articles" / "sochi_2026-12-01.txt")
    kasan7 = kanji_int(re.search(r"合計所得金額が百三十二万円以下である場合　([〇一二三四五六七八九十百千万]+)円", section(so7, r"^## Num=41_16_2$")).group(1))
    kasan8 = kanji_int(re.search(r"合計所得金額が四百八十九万円以下である場合　([〇一二三四五六七八九十百千万]+)円", section(so8, r"^## Num=41_16_2$")).group(1))
    q7 = read(RES / "IMPL_kyuyo_fetch" / "articles_sochi_2026-11-09.txt")
    q8 = read(RES / "IMPL_kyuyo_fetch" / "articles_sochi_2026-12-01.txt")
    def tokurei(t):
        a = section(t, r"^## Num=27$")
        # 措法27① 「…必要経費に算入すべき金額の合計額が六十五万円（当該個人が給与所得を有する…」
        return kanji_int(re.search(r"必要経費に算入すべき金額の合計額が([〇一二三四五六七八九十百千万]+)円", a).group(1))
    years = {}
    for y, st, kt, kasan, qt in [("令和7年分", s7, k7, kasan7, q7), ("令和8年分", s8, k8, kasan8, q8)]:
        tk = tokurei(qt)
        fy = fuyo_limit(st)
        fy_spouse = fuyo_limit(st, "三十三　同一生計配偶者")
        kiso = kiso_honsoku(kt) + kasan
        tt = tokutei_upper(st)
        hs = haigu_toku_upper(st)
        years[y] = {
            "特例額（措法27①）": tk, "扶養親族・同一生計配偶者の合計所得金額の要件（所法2①三十四・三十三）": fy,
            "同一生計配偶者の合計所得金額の要件（所法2①三十三。上と同じかの確認）": fy_spouse,
            "基礎控除（低い所得の段階。所法86①一＋措法41の16の2①）": kiso, "特定親族特別控除の対象の上限（所法84の2）": tt,
            "所法83の2 に出る合計所得金額の上限（配偶者特別控除。本人と配偶者）": hs,
            "総収入の上限：扶養親族・配偶者控除の対象（特例額＋扶養の要件）": tk + fy,
            "総収入の上限：本人に所得税がかからない（特例額＋基礎控除）": tk + kiso,
            "総収入の上限：特定親族特別控除の対象（特例額＋123万）": tk + tt if tt else None,
        }
    # 総収入 1,600,000（令和7年分）の人の合計所得金額と、該当する控除の種類
    y7 = years["令和7年分"]
    g = 1_600_000 - y7["特例額（措法27①）"]
    classify_160 = {"総収入": 1_600_000, "合計所得金額": g,
                    "扶養親族（扶養控除・配偶者控除の対象）に当たるか": g <= y7["扶養親族・同一生計配偶者の合計所得金額の要件（所法2①三十四・三十三）"],
                    "特定親族（19歳以上23歳未満）に当たるか": y7["扶養親族・同一生計配偶者の合計所得金額の要件（所法2①三十四・三十三）"] < g <= y7["特定親族特別控除の対象の上限（所法84の2）"],
                    "本人の所得税がかからないか（基礎控除以下）": g <= y7["基礎控除（低い所得の段階。所法86①一＋措法41の16の2①）"]}
    ta = {"current": ta1810_notes(WEB / "nta" / "ta_1810.txt")}
    for f in sorted((WEB / "archive2").glob("wa_ta_1810_*.txt")):
        ta[f.stem] = ta1810_notes(f)
    # TA の文に出る金額（万円）を拾う
    for v in ta.values():
        v["amounts_man"] = sorted({int(x) for ln in v["note2"] for x in re.findall(r"(\d+)万円", ln)})
    return {"statute": years, "classify_R7_1600000": classify_160, "ta_1810": ta}


# ---------------------------------------------------------------- (3) 所得金額調整控除
def check_chosei():
    res = {}
    for asof in ["2024-12-31", "2025-12-31", "2026-12-31", "2027-01-01"]:
        t = read(EG / f"sochi_asof{asof}.txt")
        a = section(t, r"^## 本則 Num=41_3_11 ")
        nums = [kanji_int(x) for x in YEN.findall(a)]
        res[asof] = {"law_revision_id": header_rev(t), "found": bool(a), "yen_amounts_in_order": nums,
                     "has_hyakubun_no_ju": "百分の十" in a, "has_hasu": "端数" in a,
                     "sha256_article_text": hashlib.sha256(a.encode("utf-8")).hexdigest()}
    for short, asofs in [("sochi-rei", ["2025-12-31", "2026-12-31"]), ("sochi-ki", ["2025-12-31", "2026-12-31"])]:
        for asof in asofs:
            t = read(EG / f"{short}_asof{asof}.txt")
            arts = re.split(r"(?m)^## ", t)[1:]
            res[f"{short}_{asof}"] = {"law_revision_id": header_rev(t),
                                      "articles": [{"head": x.splitlines()[0], "has_hasu": "端数" in x,
                                                    "mentions_chosei": "所得金額調整控除" in x} for x in arts]}
    # 計算例（第1項：TA No.1411 の「1円未満の端数があるときは切り上げ」と、端数を扱わない計算の両方）
    def k1(salary, up=True):
        if salary <= 8_500_000:
            return 0
        base = min(salary, 10_000_000) - 8_500_000
        q, r = divmod(base * 10, 100)
        return q + (1 if (up and r) else 0)
    def k2(kyuyo_after, nenkin):
        if kyuyo_after <= 0 or nenkin <= 0 or kyuyo_after + nenkin <= 100_000:
            return 0
        return min(kyuyo_after, 100_000) + min(nenkin, 100_000) - 100_000
    ex1 = [{"給与等の収入金額": s, "控除額（切上げ）": k1(s, True), "控除額（端数を切捨て）": k1(s, False)}
           for s in [8_500_000, 8_500_001, 8_500_005, 8_500_010, 9_000_000, 9_999_999, 10_000_000, 12_000_000]]
    ex2 = [{"給与所得控除後の給与等の金額": a, "公的年金等に係る雑所得の金額": b, "控除額": k2(a, b)}
           for a, b in [(50_000, 40_000), (50_000, 80_000), (200_000, 300_000), (100_000, 1), (0, 500_000)]]
    res["examples_item1"] = ex1
    res["examples_item2"] = ex2
    # 地方税法の全文（生データ）に措法41の3の11 を引く箇所があるか
    log = json.loads(read(EG / "fetch_log.json"))
    dl = ROOT / log["download_dir"]
    chiho = {}
    for f in log["fetches"]:
        if f["short"] == "chiho":
            raw = (dl / f"{f['law_id']}_{f['asof']}.json").read_text(encoding="utf-8")
            chiho[f["asof"]] = {k: raw.count(k) for k in ["所得金額調整控除", "四十一条の三の十一", "第四十一条の三の三"]}
    res["chiho_raw_counts"] = chiho
    return res


# ---------------------------------------------------------------- (4) 基礎控除
def check_kiso():
    res = {}
    for asof in ["2025-12-31", "2026-12-31", "2027-01-01"]:
        t = read(EG / f"shotoku_asof{asof}.txt")
        a = section(t, r"^## 本則 Num=86")
        rows = []
        for ln in a.splitlines():
            m = re.match(r"\s*([一二三四])　その居住者の合計所得金額が(.+?)である場合　([〇一二三四五六七八九十百千万]+)円", ln)
            if m:
                cond = m.group(2)
                lo = re.search(r"([〇一二三四五六七八九十百千万]+)円を超え", cond)
                hi = re.search(r"([〇一二三四五六七八九十百千万]+)円以下", cond)
                rows.append({"号": m.group(1), "超": kanji_int(lo.group(1)) if lo else None,
                             "以下": kanji_int(hi.group(1)) if hi else None, "控除額": kanji_int(m.group(3))})
        top = re.search(r"合計所得金額が([〇一二三四五六七八九十百千万]+)円以下である居住者については", a)
        res[asof] = {"law_revision_id": header_rev(t), "対象の上限": kanji_int(top.group(1)) if top else None, "rows": rows}
    return res


# ---------------------------------------------------------------- (5) 所規47の3 の引用
def check_47_3():
    res = {"shotoku_120": {}, "shotoku_ki_47_3": {}}
    for asof in ["2025-12-31", "2026-12-31", "2027-01-01"]:
        t = read(EG / f"shotoku_asof{asof}.txt")
        a = section(t, r"^## 本則 Num=120")
        para = None
        for ln in a.splitlines():
            if "総収入金額及び必要経費の内容を記載した書類" in ln:
                m = re.match(r"\s*（Paragraph(\d+)）|\s*([２-９])　", ln)
                para = ln.strip()[0]
        res["shotoku_120"][asof] = {"law_revision_id": header_rev(t), "paragraph_with_shushi_naiyaku": para}
    zen = str.maketrans("０１２３４５６７８９", "0123456789")
    for k, v in res["shotoku_120"].items():
        v["paragraph_number"] = int(v["paragraph_with_shushi_naiyaku"].translate(zen)) if v["paragraph_with_shushi_naiyaku"] else None
    for asof in ["2026-11-09", "2026-12-31", "2027-01-01"]:
        t = read(EG / f"shotoku-ki_asof{asof}.txt")
        a = section(t, r"^## 本則 Num=47_3")
        cites = re.findall(r"法第百二十条第([一二三四五六七八九十]+)項", a)
        res["shotoku_ki_47_3"][asof] = {"law_revision_id": header_rev(t), "cited_paragraphs": [kanji_int(c) for c in cites]}
    # 生データの附則から、2027-01-01（令和九年一月一日）に施行する規定を探す
    log = json.loads(read(EG / "fetch_log.json"))
    dl = ROOT / log["download_dir"]

    def inline(n):
        if isinstance(n, str):
            return n
        if n.get("tag") == "Rt":
            return ""
        return "".join(inline(c) for c in n.get("children", []))

    def suppls(path):
        d = json.loads(path.read_text(encoding="utf-8"))
        out = []
        def walk(n):
            if isinstance(n, dict):
                if n.get("tag") == "SupplProvision":
                    out.append(n)
                for c in n.get("children", []):
                    walk(c)
        walk(d["law_full_text"])
        return out
    found = {}
    for short, law_id, asof, nums in [
        ("shotoku-ki", "340M50000040011", "2027-01-01", ["令和八年三月三一日財務省令第一七号", "令和七年三月三一日財務省令第一八号", "令和五年三月三一日財務省令第一二号"]),
        ("shotoku", "340AC0000000033", "2027-01-01", ["令和八年三月三一日法律第一二号", "令和七年三月三一日法律第一三号", "令和六年三月三〇日法律第八号", "令和五年三月三一日法律第三号"]),
    ]:
        sps = suppls(dl / f"{law_id}_{asof}.json")
        for num in nums:
            hit = [s for s in sps if (s.get("attr") or {}).get("AmendLawNum") == num]
            sents = []
            for s in hit:
                # 附則の条ごと・項ごとに、「令和九年一月一日」を含み、かつ第120条・第47条の3 に触れる文を拾う
                arts = []
                def walk(n, cur=None):
                    if isinstance(n, dict):
                        if n.get("tag") == "Article":
                            cur = n
                            arts.append(n)
                        for c in n.get("children", []):
                            walk(c, cur)
                walk(s)
                for a in arts:
                    cap = next((inline(c) for c in a.get("children", []) if isinstance(c, dict) and c.get("tag") == "ArticleCaption"), "")
                    for p in a.get("children", []):
                        if not (isinstance(p, dict) and p.get("tag") == "Paragraph"):
                            continue
                        pt = inline(p)
                        if "令和九年一月一日" in pt and ("第百二十条" in pt or "第四十七条の三" in pt):
                            sents.append({"article": a["attr"].get("Num"), "caption": cap, "paragraph": p["attr"].get("Num"),
                                          "text": pt[:1500]})
            found[f"{short}:{num}"] = {"suppl_found": len(hit), "paragraphs_R9_0101_and_120_or_47_3": sents}
    res["suppl_2027_01_01"] = found
    return res


# ---------------------------------------------------------------- (6) 健保の見込み
def check_kenpo():
    t = read(WEB / "mhlw2" / "mhlw_00tc5007_p1.txt")
    heads = re.findall(r"\((\S+あて)厚生労働省保険局保険課通知\)", t)
    items = sorted(set(re.findall(r"^([1-4])　(.+)$", t, re.M)))
    q = read(WEB / "mhlw2" / "mhlw_00tc5958_p1.txt")
    return {"00tc5007": {"addressees": heads, "items": [{"no": n, "text": s} for n, s in items],
                         "has_chokkin_3kagetsu": "直近3ヶ月の収入を年収に換算すると130万円以上" in t},
            "00tc5958_mentions_R2_0410": q.count("令和2年4月10日付け厚生労働省保険局保険課事務連絡"),
            "00tc5958_kyoukai_via_nenkin": "被扶養者異動届は日本年金機構に提出し、被扶養者の年間収入見込みを確認する" in q}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"kinro": check_kinro(), "ta1810": check_1810(), "chosei": check_chosei(), "kiso": check_kiso(),
           "shoki_47_3": check_47_3(), "kenpo": check_kenpo()}
    (OUT / "checks.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# R2X_gaps_check の結果", "", "（scripts/R2X_gaps_check.py の出力。checks.json の要約）", ""]
    md.append("## (1) 勤労学生")
    for k in ["2025-12-31", "2026-12-31", "2027-01-01"]:
        md.append(f"- 所法2①三十二 asof {k}: {res['kinro'][k]}")
    md.append(f"- 所得税基本通達（勤労学生）: {res['kinro']['kihon_tsutatsu']}")
    for k, v in res["kinro"]["nta_hits"].items():
        md.append(f"- {k}: 勤労の行 {v['lines_with_kinro']}、アフィリエイト等の行 {v['lines_with_net_income_words']}、両方を含む行 {v['lines_with_both']}")
    md.append("")
    md.append("## (2) TA No.1810")
    for y, v in res["ta1810"]["statute"].items():
        md.append(f"- {y}: " + "、".join(f"{a}={b}" for a, b in v.items()))
    md.append(f"- 令和7年分・総収入 1,600,000: {res['ta1810']['classify_R7_1600000']}")
    for k, v in res["ta1810"]["ta_1810"].items():
        md.append(f"- {k} [{v['as_of_label']}] 金額（万円）{v['amounts_man']}")
        for ln in v["note2"]:
            md.append(f"  - {ln}")
    md.append("")
    md.append("## (3) 所得金額調整控除")
    for k, v in res["chosei"].items():
        md.append(f"- {k}: {v}")
    md.append("")
    md.append("## (4) 基礎控除")
    for k, v in res["kiso"].items():
        md.append(f"- {k}: {v}")
    md.append("")
    md.append("## (5) 所規47の3")
    md.append(f"- {json.dumps(res['shoki_47_3'], ensure_ascii=False)}")
    md.append("")
    md.append("## (6) 健保の見込み")
    md.append(f"- {json.dumps(res['kenpo'], ensure_ascii=False)}")
    (OUT / "checks.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("done", OUT)


if __name__ == "__main__":
    sys.exit(main())

"""R3X_dai3go: 取得済みのテキストから、国民年金の被扶養配偶者の認定基準（昭和61年3月31日 庁保発第13号）を
130万円に改正した通知の番号・日付の手がかりを機械的に取り出して突き合わせる。ネットワークは使わない。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_dai3go_checks.py

入力（すべて取得済みのデータから作ったテキスト。読むだけで、解釈して実行することはない）:
  D1 scripts/results/R3X_dai3go_pdftext/shinsa_r02_03_15_01_text.tsv（社会保険審査会 裁決 令和元年（国）第263号）
  D2 scripts/results/R2X_spouse_fetch/text/20261109-173657_mhlw/srch_H050301_0331.txt と
     scripts/results/R2X_spouse_fetch/text/20261109-180456_mhlw_pages/srch_H050301_0331_p{1,2}.txt
     （厚労省 法令等データベースの日付検索 平成5年3月1日〜31日の結果一覧 48件。第2ラウンドの取得）
  D3 scripts/results/R2X_spouse_fetch/text/20261109-173657_mhlw/S61_hifuyo_haigusha_nintei.txt（同 データベースの 00tb1690 の本文）
  D4 scripts/results/R3X_dai3go_fetch/text/20261109-201133_mhlw_docs/S610401_chohokenhatsu18_unyo.txt（00tb1695 運用の通知）
  D5 scripts/results/R3X_dai3go_fetch/text/20261109-201133_mhlw_docs/H220101_nenhatsu101002_kizon.txt（00tb5871 別添2）
  D6 scripts/results/R3X_dai3go_pdftext/c_0000086586_text.tsv（厚労省 年金局「紙上Live講義」基礎編2 の5頁）
  D7 scripts/results/R3X_dai3go_fetch/text/*_kokkai*/*.txt（国会会議録検索システム API の発言）
  D8 scripts/results/R3X_dai3go_egov/kokunen-rei_*.txt（国民年金法施行令 第4条。e-Gov 法令API v2）
  D9 scripts/results/R3X_dai3go_fetch/text/*_mhlw_h05_no5/srch_*.txt（同 データベースの種別・番号の検索。平成5年 庁保発 第5号・第6号）
出力: scripts/results/R3X_dai3go_checks/checks.json
"""
import collections
import glob
import json
import pathlib
import re
import sys
import unicodedata

ROOT = pathlib.Path(__file__).resolve().parent.parent
R3 = ROOT / "scripts" / "results"
OUT = R3 / "R3X_dai3go_checks"


def norm(s):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s))


def tsv_rows(path):
    """scripts/R3X_dai3go_pdftext.py の *_text.tsv を (page, x, y, text) にする。断片の中の改行で欄が足りない行は前の断片につなぐ。"""
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or line.startswith("page\t"):
            continue
        parts = line.split("\t")
        if len(parts) < 5:
            if rows:
                p, x, y, t = rows[-1]
                rows[-1] = (p, x, y, t + line)
            continue
        try:
            rows.append((int(parts[0]), float(parts[1]), float(parts[2]), "\t".join(parts[4:])))
        except ValueError:
            continue
    return rows


def d1_shinsakai():
    rows = tsv_rows(R3 / "R3X_dai3go_pdftext" / "shinsa_r02_03_15_01_text.tsv")
    p1 = [r for r in rows if r[0] == 1 and r[2] > 540]
    head = [r[3] for r in sorted(p1, key=lambda r: (-r[2], r[1])) if r[1] < 230]
    # 2頁の左の段（x 211〜214）を上から順につなぐ
    col = [r for r in rows if r[0] == 2 and 211.0 <= r[1] <= 214.0]
    text = "".join(r[3] for r in sorted(col, key=lambda r: -r[2]))
    m = re.search(r"「国民年金法における被扶養配偶者の認定基準について」（.*?））", text)
    nt = norm(m.group(0)) if m else None
    return {
        "page1_head": head,
        "citation": m.group(0) if m else None,
        "citation_has_saishu_kaisei_H5_3_15_chohohatsu5": bool(nt and "最終改正平成5年3月15日庁保発第5号" in nt),
    }


def d2_mhlw_h5_march():
    base = R3 / "R2X_spouse_fetch" / "text"
    files = [base / "20261109-173657_mhlw" / "srch_H050301_0331.txt",
             base / "20261109-180456_mhlw_pages" / "srch_H050301_0331_p1.txt",
             base / "20261109-180456_mhlw_pages" / "srch_H050301_0331_p2.txt"]
    items, totals = [], []
    for f in files:
        t = f.read_text(encoding="utf-8")
        m = re.search(r"該当件数:\s*(\d+)件中\s*(\d+)件~\s*(\d+)件", t)
        totals.append(m.groups() if m else None)
        for title, date, num in re.findall(r"・([^\n]+)\n(?:[^\n]*\n){0,3}?\s*\|\s*◆(平成05年03月\d\d日)\n\s*\|\s*([^\n]*)", t):
            items.append({"date": date, "number": num.strip(), "title": title.strip(), "file": str(f.relative_to(ROOT)).replace("\\", "/")})
    chohohatsu = [i for i in items if i["number"].startswith("庁保発")]
    return {
        "pages": totals,
        "n_items": len(items),
        "chohohatsu_items": chohohatsu,
        "items_on_0315": [i for i in items if i["date"] == "平成05年03月15日"],
        "any_title_with_hifuyo": [i for i in items if "被扶養" in i["title"]],
        "has_chohohatsu5": any(re.fullmatch(r"庁保発第5号", i["number"]) for i in items),
    }


def d3_s61():
    t = (R3 / "R2X_spouse_fetch" / "text" / "20261109-173657_mhlw" / "S61_hifuyo_haigusha_nintei.txt").read_text(encoding="utf-8")
    return {
        "title_line": next((x for x in t.splitlines() if x.startswith("・")), None),
        "count_90man": len(re.findall(r"九[○〇]万円", t)),
        "count_150man": len(re.findall(r"一五[○〇]万円", t)),
        "count_130man": len(re.findall(r"(?:一三[○〇]|百三十|130)万円", t)),
        "has_kaisei_rireki_word": bool(re.search(r"改正", t)),
    }


def d4_unyo18():
    t = (R3 / "R3X_dai3go_fetch" / "text" / "20261109-201133_mhlw_docs" / "S610401_chohokenhatsu18_unyo.txt").read_text(encoding="utf-8")
    m = re.search(r"１　第三号被保険者としての届出に係る者.*?こと。", t, re.S)
    return {
        "title_line": next((x for x in t.splitlines() if x.startswith("・")), None),
        "item1": m.group(0) if m else None,
        "amounts_in_item1": re.findall(r"[一二三四五六七八九○〇]+万円", m.group(0)) if m else [],
        "has_130": bool(re.search(r"一三[○〇]万円|百三十万円", t)),
    }


def d5_h22():
    t = (R3 / "R3X_dai3go_fetch" / "text" / "20261109-201133_mhlw_docs" / "H220101_nenhatsu101002_kizon.txt").read_text(encoding="utf-8")
    cells = [c.strip() for c in re.split(r"\n\s*\|?\s*\n", t) if c.strip() and c.strip() != "|"]
    out = []
    for i, c in enumerate(cells):
        if c in ("国民年金法における被扶養配偶者の認定基準について", "国民年金法における被扶養配偶者の認定基準の運用について"):
            out.append({"no": re.sub(r"\D", "", cells[i - 1]) if i else None, "name": c, "date": cells[i + 1], "number": cells[i + 2], "bunrui": cells[i + 3]})
    bettenn2 = t.find("\n別添2\n")
    return {"rows": out, "in_bettenn2": all(t.find(r["name"]) > bettenn2 for r in out) if bettenn2 > 0 else None,
            "bettenn2_header": [c for c in cells if c in ("通知等の名称", "発出日", "発出番号", "分類")][:4]}


def d6_kamijo():
    rows = tsv_rows(R3 / "R3X_dai3go_pdftext" / "c_0000086586_text.tsv")
    p5 = sorted([r for r in rows if r[0] == 5], key=lambda r: (-r[2], r[1]))
    # 右の段（x が 300 より大きい）を上から順につなぐ
    right = "".join(r[3] for r in p5 if r[1] > 300)
    m = re.search(r"なお、被扶養配偶者の認定基準に関しては.*?ください。", norm(right))
    return {"citation": m.group(0) if m else None,
            "numbers": re.findall(r"『([^』]+)』", m.group(0)) if m else []}


def d7_kokkai():
    want = [("1993-03-05", "69"), ("1993-03-05", "70"), ("1993-03-09", "70"), ("2002-03-28", "57"), ("2002-04-16", "139"),
            ("2023-02-20", "294")]
    found = {}
    for f in sorted(glob.glob(str(R3 / "R3X_dai3go_fetch" / "text" / "*_kokkai*" / "*.txt"))):
        t = pathlib.Path(f).read_text(encoding="utf-8")
        for block in t.split("=" * 60):
            m = re.search(r"date=(\S+) house=(\S+) meeting=(\S+) issue=(\S+) speechOrder=(\d+) speaker=(\S+) position=(\S+)", block)
            if not m:
                continue
            key = (m.group(1), m.group(5))
            if key in want and f"{key[0]}#{key[1]}" not in found:
                body = block[block.find("○"):] if "○" in block else block
                sents = [s + "。" for s in re.split(r"。", body) if re.search(r"百三十万|百二十万|被扶養配偶者|通知|第三号", s)]
                url = re.search(r"speechURL=(\S+)", block)
                found[f"{key[0]}#{key[1]}"] = {"house": m.group(2), "meeting": m.group(3), "issue": m.group(4), "speaker": m.group(6),
                                              "position": m.group(7), "speechURL": url.group(1) if url else None,
                                              "file": str(pathlib.Path(f).relative_to(ROOT)).replace("\\", "/"),
                                              "sentences": [s.strip() for s in sents][:6]}
    return {"want": [f"{a}#{b}" for a, b in want], "found": found}


def d8_egov():
    out = {}
    for f in sorted((R3 / "R3X_dai3go_egov").glob("kokunen-rei_*.txt")):
        t = f.read_text(encoding="utf-8")
        m = re.search(r"## Num=4\n（[^）]+）\n第四条\n（Paragraph1）　(.+)", t)
        st = re.search(r"# HTTP (\d+)", t)
        rev = re.search(r"law_revision_id=(\S+)", t)
        out[f.stem] = {"http": st.group(1) if st else None, "law_revision_id": rev.group(1) if rev else None,
                       "art4": m.group(1) if m else None,
                       "message": t.strip().splitlines()[-1] if st and st.group(1) != "200" else None}
    texts = {v["art4"] for v in out.values() if v["art4"]}
    return {"versions": out, "art4_same_in_all_200": len(texts) == 1}


def d9_number_search():
    """D9 厚労省 法令等データベースの種別・番号の検索（平成5年、庁保発 第5号・第6号）。scripts/R3X_dai3go_fetch.py の mhlw_h05_no5。"""
    out = {}
    for f in sorted(glob.glob(str(R3 / "R3X_dai3go_fetch" / "text" / "*_mhlw_h05_no5" / "srch_*.txt"))):
        t = pathlib.Path(f).read_text(encoding="utf-8")
        m = re.search(r"該当件数:\s*(\d+)件", t)
        items = re.findall(r"・([^\n]+)\n(?:[^\n]*\n){0,3}?\s*\|\s*◆(\S+)\n(?:[^\n]*\n){0,2}?\s*(庁保発第\d+号)", t)
        out[pathlib.Path(f).stem] = {"hits": int(m.group(1)) if m else None,
                                     "items": [{"title": a.strip(), "date": b, "number": c} for a, b, c in items],
                                     "file": str(pathlib.Path(f).relative_to(ROOT)).replace("\\", "/")}
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"D1_shinsakai": d1_shinsakai(), "D2_mhlw_h5_march": d2_mhlw_h5_march(), "D3_s61_text": d3_s61(),
           "D4_unyo18": d4_unyo18(), "D5_h22_bettenn2": d5_h22(), "D6_kamijo_live": d6_kamijo(), "D7_kokkai": d7_kokkai(),
           "D8_egov_kokunen_rei_art4": d8_egov(), "D9_mhlw_number_search_H5": d9_number_search()}
    print("D9", res["D9_mhlw_number_search_H5"])
    (OUT / "checks.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("D1", res["D1_shinsakai"]["page1_head"], res["D1_shinsakai"]["citation"], res["D1_shinsakai"]["citation_has_saishu_kaisei_H5_3_15_chohohatsu5"])
    d2 = res["D2_mhlw_h5_march"]
    print("D2", d2["pages"], d2["n_items"], [(i["date"], i["number"]) for i in d2["chohohatsu_items"]],
          "0315:", [(i["number"], i["title"][:20]) for i in d2["items_on_0315"]], "被扶養:", d2["any_title_with_hifuyo"], "第5号:", d2["has_chohohatsu5"])
    print("D3", res["D3_s61_text"])
    print("D4", res["D4_unyo18"]["title_line"], res["D4_unyo18"]["amounts_in_item1"], res["D4_unyo18"]["has_130"])
    print("D5", res["D5_h22_bettenn2"])
    print("D6", res["D6_kamijo_live"])
    for k, v in res["D7_kokkai"]["found"].items():
        print("D7", k, v["meeting"], v["speaker"], v["position"], v["sentences"][:2])
    print("D7 missing", [w for w in res["D7_kokkai"]["want"] if w not in res["D7_kokkai"]["found"]])
    print("D8", {k: (v["http"], v["law_revision_id"]) for k, v in res["D8_egov_kokunen_rei_art4"]["versions"].items()},
          res["D8_egov_kokunen_rei_art4"]["art4_same_in_all_200"])


if __name__ == "__main__":
    main()

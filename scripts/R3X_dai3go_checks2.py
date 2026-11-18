"""R3X_dai3go（続き）：2026-11-11 に追加で取得したもの（厚労省 法令等データベースの検索、社会保険審査会の裁決など）と、
取得済みのテキストから、昭和61年3月31日 庁保発第13号（国民年金法における被扶養配偶者の認定基準）を改正した通知の
番号・日付の手がかりを機械的に取り出して突き合わせる。ネットワークは使わない。
scripts/R3X_dai3go_checks.py（D1〜D9）の続き（N1〜N7）。D1〜D9 の結果は scripts/results/R3X_dai3go_checks/checks.json。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_dai3go_checks2.py

入力（すべて取得済みのデータから作ったテキスト。読むだけで、解釈して実行することはない）:
  N1 scripts/results/R3X_dai3go_fetch/text/*_mhlw_h05_no5/srch_*.txt と *_mhlw_h05_neighbors/srch_*.txt
     （厚労省 法令等データベースの情報詳細検索。平成5年1月1日〜12月31日、種別「庁保発」、番号 1〜6）と、
     scripts/results/R2X_spouse_fetch/text/20261109-173657_mhlw/srch_H050301_0331.txt・
     20261109-180456_mhlw_pages/srch_H050301_0331_p{1,2}.txt（日付検索 平成5年3月1日〜31日。第2ラウンドの取得）
  N2 scripts/results/R3X_dai3go_fetch/text/*_mhlw_h05_neighbors/kw_H050315.txt（本文検索「平成五年三月一五日」）
  N3 scripts/results/R3X_dai3go_fetch/text/*_mhlw_h05_neighbors/kw_chohohatsu5.txt と *_mhlw_h05_neighbors2/kw_chohohatsu5_p1.txt
     （本文検索「庁保発第五号」の1〜2頁）
  N4 scripts/results/R3X_dai3go_pdftext/shinsa_*_text.tsv（社会保険審査会の裁決 6件）
  N5 scripts/results/R3X_dai3go_pdftext/summary.json（c_001746546 と kentokai1_shiryo2 の SHA-256）
  N6 scripts/results/R3X_dai3go_pdftext/c_0000086586_text.tsv（厚労省 年金局「紙上Live講義」基礎編 5頁の130万円の文）
  N7 scripts/results/R3X_dai3go_pdftext/kounen_tekiyou_text.tsv（日本年金機構「疑義照会回答（厚生年金保険 適用）」の
     「庁保険発第18号」「庁保発第13号」の頁ごとの出現数）
  N8 scripts/results/R3X_dai3go_fetch/text/*_kokkai*/*.txt（国会会議録検索システム API の発言。「百三十万」と
     「第三号」「被扶養配偶者」「被扶養者」を同じ文に含む文）
出力: scripts/results/R3X_dai3go_checks2/checks2.json
"""
import glob
import json
import pathlib
import re
import sys
import unicodedata

ROOT = pathlib.Path(__file__).resolve().parent.parent
R = ROOT / "scripts" / "results"
FT = R / "R3X_dai3go_fetch" / "text"
PT = R / "R3X_dai3go_pdftext"
OUT = R / "R3X_dai3go_checks2"

# 結果一覧の1件：行頭（空白と「|」のあと）の「・件名」、3行以内の「◆制定年月日」、次の行（情報詳細検索では「|」だけの行を
# 1つはさむ）の「種別・番号」
ITEM = re.compile(r"(?m)^[\t |]*・([^\n]+)\n(?:[^\n]*\n){0,3}?[\t |]*◆(\S+)\n(?:[\t |]*\n)?[\t |]*([^\n]+)")
COUNT = re.compile(r"該当件数:\s*(\d+)件中\s*(\d+)件~\s*(\d+)件")


def rel(p):
    return str(pathlib.Path(p).resolve().relative_to(ROOT)).replace("\\", "/")


def norm(s):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s))


def result_list(path):
    t = pathlib.Path(path).read_text(encoding="utf-8")
    m = COUNT.search(t)
    kw = re.search(r"name='keyword' type='hidden' value='([^']*)'", t)
    bango = re.search(r"name='bango' type='hidden' value='([^']*)'", t)
    err = re.search(r"\[ERR-[^\]]+\][^\n]*", t)
    items = [{"title": a.strip(), "date": b, "number": c.strip()} for a, b, c in ITEM.findall(t)]
    return {"file": rel(path), "keyword": kw.group(1) if kw else None, "bango": bango.group(1) if bango else None,
            "count": [int(x) for x in m.groups()] if m else None, "error": err.group(0) if err else None, "items": items}


def wareki_h(date):
    """「平成05年03月17日」→ (5, 3, 17)。平成以外は None。"""
    m = re.fullmatch(r"平成(\d\d)年(\d\d)月(\d\d)日", date)
    return tuple(int(x) for x in m.groups()) if m else None


def n1_h5_chohohatsu_numbers():
    files = sorted(glob.glob(str(FT / "*_mhlw_h05_no5" / "srch_*.txt")) + glob.glob(str(FT / "*_mhlw_h05_neighbors" / "srch_*.txt")))
    by_number = {}
    for f in files:
        r = result_list(f)
        by_number[r["bango"]] = {"count": r["count"], "items": r["items"], "file": r["file"]}
    # 第2ラウンドの日付検索（平成5年3月の全件）から、庁保発の番号と日付
    base = R / "R2X_spouse_fetch" / "text"
    march = []
    for f in [base / "20261109-173657_mhlw" / "srch_H050301_0331.txt",
              base / "20261109-180456_mhlw_pages" / "srch_H050301_0331_p1.txt",
              base / "20261109-180456_mhlw_pages" / "srch_H050301_0331_p2.txt"]:
        r = result_list(f)
        march.append({"file": r["file"], "count": r["count"], "n_items_parsed": len(r["items"])})
        for it in r["items"]:
            if re.fullmatch(r"庁保発第\d+号", it["number"]):
                by_number.setdefault(re.search(r"\d+", it["number"]).group(0) + "(3月の日付検索)", {"items": [it], "file": r["file"]})
    pairs = {}
    for k, v in by_number.items():
        for it in v["items"]:
            m = re.fullmatch(r"庁保発第(\d+)号", it["number"])
            if m and wareki_h(it["date"]):
                pairs[int(m.group(1))] = it["date"]
    seq = sorted(pairs.items())
    monotonic = all(wareki_h(a[1]) <= wareki_h(b[1]) for a, b in zip(seq, seq[1:]))
    lo = max((n for n in pairs if n < 5), default=None)
    hi = min((n for n in pairs if n > 5), default=None)
    fits = None
    if lo is not None and hi is not None:
        fits = wareki_h(pairs[lo]) <= (5, 3, 15) <= wareki_h(pairs[hi])
    return {"number_search": {k: v for k, v in sorted(by_number.items()) if "3月" not in k},
            "march_date_search": march,
            "known_H5_chohohatsu_number_date": [{"number": n, "date": d} for n, d in seq],
            "dates_nondecreasing_with_number": monotonic,
            "no5_found": 5 in pairs,
            "neighbors_of_no5": {"below": [lo, pairs.get(lo)], "above": [hi, pairs.get(hi)]},
            "H050315_between_neighbors": fits}


def n2_kw_h050315():
    f = glob.glob(str(FT / "*_mhlw_h05_neighbors" / "kw_H050315.txt"))[0]
    r = result_list(f)
    r["chohohatsu_items"] = [i for i in r["items"] if "庁保発" in i["number"]]
    r["titles_with_hifuyo_or_kokunen"] = [i for i in r["items"] if re.search(r"被扶養|国民年金", i["title"])]
    return r


def n3_kw_chohohatsu5():
    out = []
    for f in sorted(glob.glob(str(FT / "*_mhlw_h05_neighbors" / "kw_chohohatsu5.txt")) + glob.glob(str(FT / "*_mhlw_h05_neighbors2" / "kw_chohohatsu5_p1.txt"))):
        out.append(result_list(f))
    items = [i for r in out for i in r["items"]]
    return {"pages": [{"file": r["file"], "count": r["count"], "n_items": len(r["items"])} for r in out],
            "n_items_total": len(items),
            "items": items,
            "heisei5_items": [i for i in items if i["date"].startswith("平成05年")],
            "titles_with_hifuyo": [i for i in items if "被扶養" in i["title"]]}


def tsv_rows(path):
    rows = []
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
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


def n4_shinsakai():
    out = {}
    for f in sorted(PT.glob("shinsa_*_text.tsv")):
        rows = tsv_rows(f)
        # 2段組み：頁ごとに x を 20pt 幅で束ね（左の段→右の段）、段の中は y の降順につなぐ
        text = ""
        for pg in sorted({r[0] for r in rows}):
            P = [r for r in rows if r[0] == pg]
            text += "".join(r[3] for r in sorted(P, key=lambda r: (round(r[1] / 20), -r[2])))
        t = norm(text)
        cjk = len(re.findall(r"[\u3040-\u30ff\u4e00-\u9fff]", t))
        # NFKC で全角の括弧・数字は半角になる
        head = re.search(r"(?:平成|令和)(?:元|\d+)年\((国|厚|健|船)\)第\d+号", t)
        date = re.search(r"(?:平成|令和)\d+年\d+月\d+日", t)
        cite = re.search(r"「国民年金法における被扶養配偶者の認定基準について」\([^「」]*?\)\)", t)
        out[f.name.replace("_text.tsv", "")] = {
            "rows": len(rows), "chars": len(t), "cjk_ratio": round(cjk / len(t), 3) if t else None,
            "case_number": head.group(0) if head else None, "first_date": date.group(0) if date else None,
            "kind": head.group(1) if head else None,
            "has_dai3go": "第3号被保険者" in t, "has_chohohatsu13_S61": "昭和61年3月31日庁保発第13号" in t,
            "citation_S61": cite.group(0) if cite else None,
            "has_saishu_kaisei": "最終改正" in t,
            "has_130man": bool(re.search(r"130万", t)),
        }
    return out


def n5_same_file():
    s = json.loads((PT / "summary.json").read_text(encoding="utf-8"))["files"]
    a, b = s.get("c_001746546", {}), s.get("kentokai1_shiryo2", {})
    return {"c_001746546": {"path": a.get("path"), "sha256": a.get("sha256"), "pages": a.get("pages")},
            "kentokai1_shiryo2": {"path": b.get("path"), "sha256": b.get("sha256"), "pages": b.get("pages")},
            "same_sha256": bool(a.get("sha256")) and a.get("sha256") == b.get("sha256")}


def n6_kamijo_130():
    rows = tsv_rows(PT / "c_0000086586_text.tsv")
    p5 = sorted([r for r in rows if r[0] == 5], key=lambda r: (-r[2], r[1]))
    left = norm("".join(r[3] for r in p5 if r[1] <= 300))
    right = norm("".join(r[3] for r in p5 if r[1] > 300))
    sents = []
    for side, t in (("left", left), ("right", right)):
        for s in re.split(r"(?<=。)", t):
            if re.search(r"130万円|108,333円|3,611円|庁保発|庁保険発|庁文発|健康保険法などの被扶養者の認定", s):
                sents.append({"column": side, "sentence": s})
    return {"page": 5, "sentences": sents}


def n7_kikou_gigi():
    rows = tsv_rows(PT / "kounen_tekiyou_text.tsv")
    out = {}
    for pg in sorted({r[0] for r in rows}):
        t = norm("".join(r[3] for r in rows if r[0] == pg))
        a = len(re.findall(r"庁保険発第18号", t))
        b = len(re.findall(r"庁保発第13号", t))
        c = len(re.findall(r"被扶養配偶者の認定基準の運用", t))
        if a or b or c:
            out[pg] = {"庁保険発第18号": a, "庁保発第13号": b, "被扶養配偶者の認定基準の運用": c}
    return {"pdf_pages_with_hits": out}


def n8_kokkai_130():
    """国会会議録（scripts/R3X_dai3go_fetch.py の kokkai・kokkai2・kokkai3 の .txt）の発言のうち、「百三十万」を含み、
    「第三号」「被扶養配偶者」「被扶養者」のどれかを同じ文に含む文。発言の URL で重複を除き、日付の順に並べる。"""
    found = {}
    for f in sorted(glob.glob(str(FT / "*_kokkai*" / "*.txt"))):
        t = pathlib.Path(f).read_text(encoding="utf-8")
        for block in t.split("=" * 60):
            m = re.search(r"date=(\S+) house=(\S+) meeting=(\S+) issue=(\S+) speechOrder=(\d+) speaker=(\S+) position=(\S+)", block)
            u = re.search(r"speechURL=(\S+)", block)
            if not m or not u or u.group(1) in found:
                continue
            body = re.sub(r"\s+", "", block[block.find("○"):]) if "○" in block else ""
            sents = [s for s in re.split(r"(?<=。)", body) if "百三十万" in s and re.search(r"第三号|被扶養配偶者|被扶養者", s)]
            if sents:
                found[u.group(1)] = {"date": m.group(1), "house": m.group(2), "meeting": m.group(3), "issue": m.group(4),
                                     "speechOrder": int(m.group(5)), "speaker": m.group(6), "position": m.group(7),
                                     "file": rel(f), "sentences": sents}
    return sorted(found.values(), key=lambda r: (r["date"], r["speechOrder"]))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"N1_H5_chohohatsu_numbers": n1_h5_chohohatsu_numbers(), "N2_kw_H050315": n2_kw_h050315(),
           "N3_kw_chohohatsu5": n3_kw_chohohatsu5(), "N4_shinsakai": n4_shinsakai(), "N5_same_file": n5_same_file(),
           "N6_kamijo_130": n6_kamijo_130(), "N7_kikou_gigi": n7_kikou_gigi(), "N8_kokkai_130": n8_kokkai_130()}
    (OUT / "checks2.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    n1 = res["N1_H5_chohohatsu_numbers"]
    print("N1", {k: v["count"] for k, v in n1["number_search"].items()}, n1["known_H5_chohohatsu_number_date"],
          "nondecreasing:", n1["dates_nondecreasing_with_number"], "no5:", n1["no5_found"], "neighbors:", n1["neighbors_of_no5"],
          "fits:", n1["H050315_between_neighbors"])
    n2 = res["N2_kw_H050315"]
    print("N2", n2["count"], [(i["date"], i["number"]) for i in n2["items"]], n2["chohohatsu_items"], n2["titles_with_hifuyo_or_kokunen"])
    n3 = res["N3_kw_chohohatsu5"]
    print("N3", n3["pages"], n3["n_items_total"], "H5:", n3["heisei5_items"], "被扶養:", n3["titles_with_hifuyo"])
    for k, v in res["N4_shinsakai"].items():
        print("N4", k, {x: v[x] for x in ("case_number", "first_date", "kind", "cjk_ratio", "has_dai3go", "has_chohohatsu13_S61", "has_saishu_kaisei")})
    print("N5", res["N5_same_file"]["same_sha256"], res["N5_same_file"]["c_001746546"]["sha256"])
    for s in res["N6_kamijo_130"]["sentences"]:
        print("N6", s["column"], s["sentence"])
    print("N7", res["N7_kikou_gigi"])
    for r in res["N8_kokkai_130"]:
        print("N8", r["date"], r["meeting"], r["speechOrder"], r["speaker"], r["position"], [s[:90] for s in r["sentences"]])


if __name__ == "__main__":
    main()

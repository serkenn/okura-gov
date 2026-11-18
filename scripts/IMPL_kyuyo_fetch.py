"""IMPL_kyuyo: e-Gov 法令API v2 で、給与所得の計算に関係する条文・別表を時点（asof）ごとに取得する。

実行:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_kyuyo_fetch.py
標準ライブラリのみ。リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。

取得するもの
- 所得税法（340AC0000000033）：第28条、第190条、別表第五（全体の表の格子）、令和7年法律第13号・令和8年法律第12号の附則
- 租税特別措置法（332AC0000000026）：第27条、第29条の4、第29条の5、令和8年法律第12号の附則
- 租税特別措置法施行令（332CO0000000043）：「第二十九条の四」を含む条
- 地方税法（325AC0000000226）：第292条、第295条、第313条、第314条の2、令和7年法律第7号・令和8年法律第2号の附則
- 地方税法施行令（325CO0000000245）：キーワードの全文検索のみ
- すべての法令について、本則と附則（原始附則・改正附則）の全文からキーワードを検索し、場所（本則/附則、条、項）と前後の文を記録する
- 地方税法・租税特別措置法の改正履歴（/law_revisions、2025-01-01 以後）

ダウンロードした JSON は .work/downloads/<ts>_kyuyo_laws/ に置く（信頼できないデータ。中でコードを実行しない）。
抜き出した結果は scripts/results/IMPL_kyuyo_fetch/ に書く。
- fetch_log.json：取得URL、asof、law_revision_id、施行日、状態、生データの SHA-256 とバイト数
- articles_<略称>_<asof>.txt：抜き出した条と附則のテキスト
- beppyo5_grid_<asof>.json：所得税法 別表第五 の表の格子（行ごとのセル。rowspan/colspan を保持）と備考
- keyword_hits_<略称>_<asof>.json：キーワードの出現箇所
- revisions_<略称>.json：改正履歴
"""
import hashlib
import json
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
SLEEP = 1.5

R7_SHOTOKU = "令和七年三月三一日法律第一三号"
R8_SHOTOKU = "令和八年三月三一日法律第一二号"
R7_CHIHO = "令和七年三月三一日法律第七号"
R8_CHIHO = "令和八年三月三一日法律第二号"

KW_COMMON = ["別表第五", "二十九条の四", "給与所得控除", "七十四万円", "六十九万", "六十五万円", "六十九万千円", "第二十八条第"]
KW_CHIHO = KW_COMMON + ["所得税法第二十八条", "租税特別措置法第二十九条", "所得税に関する法令", "計算の例によつて", "計算の例によって"]

# (略称, law_id, [asof...], [本則の条番号 Num], [別表の題名], [附則を取り出す改正法令番号], [キーワード], 「第二十九条の四」を含む条を全部出すか)
JOBS = [
    ("shotoku", "340AC0000000033", ["2024-12-31", "2025-11-30", "2025-12-31", "2026-11-09", "2026-11-30", "2026-12-01", "2027-01-01"],
     ["28", "190"], ["別表第五"], [R7_SHOTOKU, R8_SHOTOKU], KW_COMMON, False),
    ("sochi", "332AC0000000026", ["2026-11-09", "2026-12-01", "2027-01-01", "2028-01-01"],
     ["27", "29_4", "29_5"], [], [R8_SHOTOKU], KW_COMMON, False),
    ("sochi-rei", "332CO0000000043", ["2026-12-01"], [], [], [], KW_COMMON, True),
    ("chiho", "325AC0000000226", ["2025-12-31", "2026-11-09", "2027-01-01", "2028-01-01"],
     ["292", "295", "313", "314_2"], [], [R7_CHIHO, R8_CHIHO], KW_CHIHO, False),
    ("chiho-rei", "325CO0000000245", ["2027-01-01"], [], [], [], KW_CHIHO, True),
]
REVISIONS = [("chiho", "325AC0000000226"), ("sochi", "332AC0000000026"), ("shotoku", "340AC0000000033")]

BLOCK_LIKE = {"Paragraph", "Item"} | {f"Subitem{i}" for i in range(1, 11)}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            body, st = r.read(), r.status
    except urllib.error.HTTPError as e:
        body, st = e.read(), e.code
    time.sleep(SLEEP)
    return st, body


# ---- テキスト化（scripts/R1_egov_articles.py の inline / render を写したもの） ----
def inline(n):
    if isinstance(n, str):
        return n
    if n.get("tag") in ("Rt",):
        return ""
    parts = [inline(c) for c in n.get("children", [])]
    if n.get("tag", "").endswith("Sentence") and any(isinstance(c, dict) and c.get("tag") == "Column" for c in n.get("children", [])):
        return "　".join(p for p in parts if p)
    return "".join(parts)


def render(n, depth, lines):
    if isinstance(n, str):
        if n.strip():
            lines.append("  " * depth + n)
        return
    tag = n.get("tag", "")
    ch = n.get("children", [])
    if tag in BLOCK_LIKE:
        title = "".join(inline(c) for c in ch if isinstance(c, dict) and c.get("tag", "").endswith(("Num", "Title")) and c.get("tag") != "ParagraphCaption")
        sent = [c for c in ch if isinstance(c, dict) and c.get("tag", "").endswith("Sentence")]
        body = "　".join(inline(s) for s in sent)
        cap = [inline(c) for c in ch if isinstance(c, dict) and c.get("tag") == "ParagraphCaption"]
        if cap:
            lines.append("  " * depth + cap[0])
        num = n.get("attr", {}).get("Num", "")
        prefix = title if title else (f"（{tag}{num}）" if tag == "Paragraph" else "")
        lines.append("  " * depth + (prefix + "　" if prefix else "") + body)
        for c in ch:
            if isinstance(c, dict) and not (c.get("tag", "").endswith(("Num", "Title", "Sentence")) or c.get("tag") == "ParagraphCaption"):
                render(c, depth + 1, lines)
        return
    if tag == "TableRow":
        cells = [inline(c).replace("\n", " ") for c in ch if isinstance(c, dict)]
        lines.append("  " * depth + "| " + " | ".join(cells) + " |")
        return
    if tag in ("ArticleCaption", "ArticleTitle", "SupplProvisionLabel", "ChapterTitle", "SectionTitle"):
        lines.append("  " * depth + inline(n))
        return
    for c in ch:
        render(c, depth, lines)


def walk(n, fn, path=()):
    if isinstance(n, dict):
        fn(n, path)
        for c in n.get("children", []):
            walk(c, fn, path + (n,))


def caption_of(a):
    for c in a.get("children", []):
        if isinstance(c, dict) and c.get("tag") == "ArticleCaption":
            return inline(c)
    return ""


# ---- 別表の格子 ----
def appdx_grid(appdx):
    """AppdxTable を、TableStruct ごとに「行 → セル（text, rowspan, colspan）」の list にする。備考も返す。"""
    out = {"title": "", "related_article_num": "", "structs": [], "remarks": []}
    for c in appdx.get("children", []):
        if not isinstance(c, dict):
            continue
        t = c.get("tag")
        if t == "AppdxTableTitle":
            out["title"] = inline(c)
        elif t == "RelatedArticleNum":
            out["related_article_num"] = inline(c)
        elif t == "TableStruct":
            st = {"title": "", "rows": [], "remarks": []}
            for x in c.get("children", []):
                if not isinstance(x, dict):
                    continue
                if x.get("tag") == "TableStructTitle":
                    st["title"] = inline(x)
                elif x.get("tag") == "Table":
                    for row in x.get("children", []):
                        if isinstance(row, dict) and row.get("tag") in ("TableRow", "TableHeaderRow"):
                            cells = []
                            for col in row.get("children", []):
                                if isinstance(col, dict):
                                    a = col.get("attr") or {}
                                    cells.append({"text": inline(col), "rowspan": int(a.get("rowspan", 1)), "colspan": int(a.get("colspan", 1))})
                            st["rows"].append(cells)
                elif x.get("tag") == "Remarks":
                    st["remarks"].append(inline(x))
            out["structs"].append(st)
        elif t == "Remarks":
            out["remarks"].append(inline(c))
    return out


def locate(path, node):
    """キーワードの出現箇所：本則/附則（AmendLawNum）、条番号、見出し、項番号。"""
    loc = {"part": "MainProvision", "amend_law_num": None, "article": None, "caption": None, "paragraph": None, "appdx": None}
    for p in list(path) + [node]:
        t = p.get("tag")
        a = p.get("attr") or {}
        if t == "SupplProvision":
            loc["part"] = "SupplProvision"
            loc["amend_law_num"] = a.get("AmendLawNum", "(原始附則)")
        elif t in ("AppdxTable", "AppdxNote", "Appdx", "AppdxStyle", "AppdxFormat", "AppdxFig"):
            loc["part"] = t
        elif t == "Article":
            loc["article"] = a.get("Num")
            loc["caption"] = caption_of(p)
        elif t == "Paragraph":
            loc["paragraph"] = a.get("Num")
        elif t == "AppdxTableTitle":
            loc["appdx"] = inline(p)
    return loc


def keyword_hits(root, keywords):
    """Sentence 単位でキーワードを探す（同じ文に複数あれば1回だけ数える）。"""
    hits = []

    def fn(n, path):
        t = n.get("tag", "")
        if t == "Sentence":
            txt = inline(n)
            for kw in keywords:
                i = txt.find(kw)
                if i >= 0:
                    loc = locate(path, n)
                    # 別表の中では、題名を探す
                    for p in path:
                        if p.get("tag") == "AppdxTable":
                            for c in p.get("children", []):
                                if isinstance(c, dict) and c.get("tag") == "AppdxTableTitle":
                                    loc["appdx"] = inline(c)
                    hits.append({"keyword": kw, **loc, "snippet": txt[max(0, i - 120): i + 160]})
    walk(root, fn)
    return hits


def fetch_full(law_id, asof, dl):
    q = {"response_format": "json", "asof": asof}
    url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode(q)
    st, body = get(url)
    fn = dl / f"{law_id}_{asof}.json"
    fn.write_bytes(body)
    if st != 200:
        raise RuntimeError(f"{url} -> {st} {body[:200]!r}")
    return url, body, json.loads(body)


def main():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_kyuyo_laws"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "IMPL_kyuyo_fetch"
    out.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "fetches": [], "revisions": []}
    for short, law_id, asofs, arts, appdx_titles, amend_nums, kws, all_29_4 in JOBS:
        for asof in asofs:
            url, body, d = fetch_full(law_id, asof, dl)
            ri = d.get("revision_info") or {}
            entry = {"short": short, "law_id": law_id, "asof": asof, "url": url,
                     "law_title": ri.get("law_title"),
                     "law_revision_id": ri.get("law_revision_id"),
                     "amendment_law_num": ri.get("amendment_law_num"),
                     "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                     "current_revision_status": ri.get("current_revision_status"),
                     "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
            log["fetches"].append(entry)
            print("ok", short, asof, ri.get("law_revision_id"), flush=True)
            root = d["law_full_text"]
            main_arts, suppl, appdx = [], [], []

            def collect(n, path):
                tags = [p.get("tag") for p in path]
                if n.get("tag") == "Article" and "SupplProvision" not in tags:
                    main_arts.append(n)
                if n.get("tag") == "SupplProvision":
                    suppl.append(n)
                if n.get("tag") == "AppdxTable":
                    appdx.append(n)
            walk(root, collect)
            header = [f"# {short} {law_id} asof={asof}",
                      f"# 法令名={ri.get('law_title')} law_revision_id={ri.get('law_revision_id')} 改正法令={ri.get('amendment_law_num')} "
                      f"施行日={ri.get('amendment_enforcement_date')} 状態={ri.get('current_revision_status')}",
                      f"# 取得URL={url}", f"# 取得日時={ts}", f"# 生データ SHA-256={entry['sha256']}", ""]
            lines = list(header)
            by_num = {a["attr"].get("Num"): a for a in main_arts}
            sel = list(arts)
            if all_29_4:
                for a in main_arts:
                    tl = []
                    render(a, 0, tl)
                    if any("二十九条の四" in x for x in tl) and a["attr"].get("Num") not in sel:
                        sel.append(a["attr"].get("Num"))
            for num in sel:
                a = by_num.get(num)
                if a is None:
                    lines += [f"## Num={num}: 見つからない（この時点の本則にない）", ""]
                    continue
                lines.append(f"## Num={num}")
                render(a, 0, lines)
                lines.append("")
            for an in amend_nums:
                hits = [s for s in suppl if (s.get("attr") or {}).get("AmendLawNum") == an]
                lines.append(f"## 附則 AmendLawNum={an}: {len(hits)} 件")
                for s in hits:
                    render(s, 0, lines)
                lines.append("")
            (out / f"articles_{short}_{asof}.txt").write_text("\n".join(lines), encoding="utf-8")
            for ap in appdx:
                g = appdx_grid(ap)
                if g["title"].strip() in appdx_titles:
                    g.update({"law_id": law_id, "asof": asof, "law_revision_id": ri.get("law_revision_id"),
                              "current_revision_status": ri.get("current_revision_status"), "source_url": url,
                              "source_sha256": entry["sha256"], "fetched_at": ts})
                    (out / f"beppyo5_grid_{asof}.json").write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding="utf-8")
            kh = keyword_hits(root, kws)
            (out / f"keyword_hits_{short}_{asof}.json").write_text(
                json.dumps({"law_id": law_id, "asof": asof, "law_revision_id": ri.get("law_revision_id"), "keywords": kws,
                            "hits": kh}, ensure_ascii=False, indent=1), encoding="utf-8")
    for short, law_id in REVISIONS:
        q = urllib.parse.urlencode({"response_format": "json", "amendment_date_from": "2025-01-01"})
        url = f"{API}/law_revisions/{law_id}?{q}"
        st, body = get(url)
        (dl / f"revisions_{law_id}.json").write_bytes(body)
        revs = []
        if st == 200:
            for rv in json.loads(body).get("revisions", []):
                revs.append({k: rv.get(k) for k in ("law_revision_id", "amendment_promulgate_date", "amendment_enforcement_date",
                                                   "amendment_scheduled_enforcement_date", "amendment_law_title", "amendment_law_num",
                                                   "current_revision_status")})
        (out / f"revisions_{short}.json").write_text(json.dumps({"url": url, "status": st, "revisions": revs}, ensure_ascii=False, indent=1), encoding="utf-8")
        log["revisions"].append({"short": short, "url": url, "status": st, "n": len(revs), "sha256": hashlib.sha256(body).hexdigest()})
    (out / "fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", out)


if __name__ == "__main__":
    sys.exit(main())

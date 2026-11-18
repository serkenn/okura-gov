"""IMPL juminzei: 住民税の扶養・非課税の判定と申告の要否に関係する条文を、e-Gov 法令API v2 で時点（asof）ごとに取得する。

実行:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_juminzei_laws.py            # 全部
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_juminzei_laws.py chiho-ki   # 指定した略称だけ

標準ライブラリのみ。リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。
e-Gov の使い方は scripts/R1_egov_articles.py と scripts/R4_fetch_laws.py を写した（import はしない）。

- ダウンロードした JSON は .work/downloads/<ts>_IMPL_juminzei_laws/ に置く（信頼できないデータ。中でコードを実行しない）。
- 出力は scripts/results/IMPL_juminzei_laws/:
  - <略称>_<asof>.txt     指定した本則の条・原始附則の条・改正附則の本文（版の情報つき）
  - index_<略称>_<asof>.txt 本則と原始附則の条番号と見出しの一覧
  - hits_<略称>_<asof>.json キーワードが出てくる条（本則・附則の別、前後の文字列）
  - diff_<略称>_<asofA>_vs_<asofB>.diff 抜き出した本文の版の間の差分
  - revisions_<略称>.json  2025-01-01 以降の改正履歴
  - keyword_<n>.json       /keyword API の結果（法令をまたいだ全文検索）
  - fetch_log.json         取得した URL・版・状態
"""
import difflib
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
SLEEP = 1.5

# 令和7年度分の賦課期日の前日（＝令和7年度分に適用された版の確認用）, 令和8年度分の賦課期日, 今日, 令和9年度分の賦課期日, 令和10年度分の賦課期日
ASOFS = ["2025-12-31", "2026-01-01", "2026-11-09", "2027-01-01", "2028-01-01"]

# キーワード（全文のどの条に出てくるかを数える）
KEYWORDS = [
    "二以上の納税義務者", "二以上の者", "所属", "未成年者", "十八歳", "二十歳",
    "第二百九十五条第三項", "第二百九十五条第一項", "附則第三条の三", "第二十四条の五第三項",
    "第二十九条の四", "給与所得控除", "所得税法第二十八条", "三十五万円", "三十二万円", "二十一万円", "十万円を加算",
    "第三百十七条の二", "確定申告書", "生活保護法",
]

# (略称, 法令名（/laws の law_title 完全一致）, 既知の law_id（None なら検索）, asofs, 本則の条番号, 本則で本文に含まれていたら抜き出す正規表現,
#  原始附則で見出し・本文に当たったら抜き出す正規表現, 抜き出す改正附則の AmendLawNum の正規表現)
JOBS = [
    ("chiho", "地方税法", "325AC0000000226", ASOFS,
     ["23", "24_5", "45_2", "45_3", "292", "294", "295", "310", "313", "314_2", "317_2", "317_3", "317_3_2", "317_3_3", "317_6", "318", "323"],
     None,
     r"非課税|附則第三条の三|個人の(?:道府県民税|市町村民税)の所得割の課税",
     [r"^令和七年三月三一日法律第七号$", r"^令和八年三月三一日法律第二号$"]),
    ("chiho-rei", "地方税法施行令", None, ASOFS,
     [],
     r"第二百九十五条|第二十四条の五|二以上の納税義務者|附則第三条の三|第三百十七条の二|第三百十四条の二第一項第十一号|扶養親族の所属|控除対象配偶者の所属",
     r"附則第三条の三|非課税|第二百九十五条",
     [r"^令和[七八]年"]),
    ("chiho-ki", "地方税法施行規則", None, ["2026-01-01", "2026-11-09", "2027-01-01"],
     [],
     r"二以上の納税義務者|扶養親族の所属|令第四十七条の三|令第四十六条の[三四五]|令第七条の三の[三四五]|施行令第四十七条の三",
     None,
     []),
    ("minpo", "民法", "129AC0000000089", ["2026-11-09"],
     ["4", "143"],
     None,
     None,
     [r"^平成三〇年六月二〇日法律第五九号$"]),
    # 給与収入から住民税の非課税の境目を求めるとき（IMPL_juminzei_thresholds.py）に使う所得税法の別表第五（第28条第4項）。
    # 令和7年分（令和8年度分の住民税）＝2025-12-31 の版、令和8年分（令和9年度分）＝2026-12-01 の版。
    ("shotoku", "所得税法", "340AC0000000033", ["2025-12-31", "2026-12-01"],
     ["28"],
     None,
     None,
     []),
    # 令和8年分・令和9年分の給与所得控除の特例（措法第29条の4。2026-12-01 施行）。住民税にも及ぶかの確認と、境目の計算に使う。
    ("sochi", "租税特別措置法", "332AC0000000026", ["2026-12-01"],
     ["29_4"],
     None,
     None,
     []),
]

# 本文の別表（AppdxTable）を取り出す法令と、別表の題名の正規表現
APPDX = {"shotoku": r"別表第五"}

# 法令をまたいだ全文検索（/keyword）
SEARCH = ["二以上の納税義務者の扶養親族", "二以上の納税義務者の控除対象配偶者", "均等割を課することができない"]

BLOCK_LIKE = {"Paragraph", "Item"} | {f"Subitem{i}" for i in range(1, 11)}


def get(url, dest=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            body, st = r.read(), r.status
    except urllib.error.HTTPError as e:
        body, st = e.read(), e.code
    if dest is not None:
        dest.write_bytes(body)
    time.sleep(SLEEP)
    return st, body


# ---- R1_egov_articles.py から写した描画 ----
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
            walk(c, fn, path + (n.get("tag"),))


def caption(a):
    for c in a.get("children", []):
        if isinstance(c, dict) and c.get("tag") == "ArticleCaption":
            return inline(c)
    return ""


def find_law_id(title, dl, tag):
    q = urllib.parse.urlencode({"law_title": title, "response_format": "json", "asof": "2026-11-09"})
    st, body = get(f"{API}/laws?{q}", dl / f"laws_{tag}.json")
    data = json.loads(body)
    for law in data.get("laws", []):
        rv = law.get("current_revision_info") or law.get("revision_info") or {}
        if rv.get("law_title") == title:
            return law["law_info"]["law_id"]
    return None


def split(root):
    """本則の条、原始附則（AmendLawNum なし）の条、改正附則（AmendLawNum ごと）に分ける。"""
    main_arts, orig_suppl_arts, amend_suppl = [], [], []

    def fn(n, path):
        if n.get("tag") == "Article":
            if "SupplProvision" not in path:
                main_arts.append(n)
        if n.get("tag") == "SupplProvision":
            if not n.get("attr", {}).get("AmendLawNum"):
                walk(n, lambda m, p: orig_suppl_arts.append(m) if m.get("tag") == "Article" else None)
            else:
                amend_suppl.append(n)
    walk(root, fn)
    return main_arts, orig_suppl_arts, amend_suppl


def text_of(n):
    lines = []
    render(n, 0, lines)
    return "\n".join(l.strip() for l in lines)


def main():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL_juminzei_laws"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "IMPL_juminzei_laws"
    out.mkdir(parents=True, exist_ok=True)
    # 引数で略称を指定すると、その法令だけを取得する（例: chiho-ki）。引数なしなら全部と /keyword 検索。
    only = set(sys.argv[1:])
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "only": sorted(only), "fetches": [], "errors": []}

    for short, title, law_id, asofs, arts, main_re, suppl_re, amend_nums in JOBS:
        if only and short not in only:
            continue
        try:
            if law_id is None:
                law_id = find_law_id(title, dl, short)
                if law_id is None:
                    log["errors"].append({"law": title, "error": "law_id not found"})
                    continue
            bodies = {}
            for asof in asofs:
                q = {"response_format": "json", "asof": asof}
                url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode(q)
                st, raw = get(url, dl / f"{short}_{asof}.json")
                if st != 200:
                    log["errors"].append({"law": title, "asof": asof, "status": st, "body": raw[:300].decode("utf-8", "replace")})
                    continue
                d = json.loads(raw)
                ri = d.get("revision_info") or {}
                li = d.get("law_info") or {}
                log["fetches"].append({"short": short, "law": title, "law_id": law_id, "law_num": li.get("law_num"), "asof": asof, "url": url,
                                       "law_revision_id": ri.get("law_revision_id"), "amendment_law_num": ri.get("amendment_law_num"),
                                       "amendment_law_title": ri.get("amendment_law_title"),
                                       "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                                       "updated": ri.get("updated"),
                                       "current_revision_status": ri.get("current_revision_status")})
                root = d["law_full_text"]
                main_arts, orig_arts, amend_suppl = split(root)
                header = [f"# {title}（{li.get('law_num')}） law_id={law_id} asof={asof}",
                          f"# law_revision_id={ri.get('law_revision_id')} 改正法令={ri.get('amendment_law_num')} 施行日={ri.get('amendment_enforcement_date')} 状態={ri.get('current_revision_status')} updated={ri.get('updated')}",
                          f"# 取得URL={url}", f"# 取得日時={ts}", ""]
                # 索引
                idx = header + ["## 本則"] + [f"{a['attr'].get('Num')}\t{caption(a)}" for a in main_arts]
                idx += ["", "## 原始附則"] + [f"附則{a['attr'].get('Num')}\t{caption(a)}" for a in orig_arts]
                idx += ["", "## 改正附則（AmendLawNum）"] + sorted({s.get('attr', {}).get('AmendLawNum') for s in amend_suppl})
                (out / f"index_{short}_{asof}.txt").write_text("\n".join(idx) + "\n", encoding="utf-8")
                # 抜き出し
                lines = list(header)
                by_num = {a["attr"].get("Num"): a for a in main_arts}
                chosen = []
                for num in arts:
                    if num in by_num:
                        chosen.append(num)
                    else:
                        lines += [f"## 本則 第{num}条: 見つからない（この時点の本則にない）", ""]
                if main_re:
                    for a in main_arts:
                        n = a["attr"].get("Num")
                        if n not in chosen and (re.search(main_re, text_of(a)) or re.search(main_re, caption(a))):
                            chosen.append(n)
                for num in chosen:
                    lines.append(f"## 本則 Num={num}")
                    render(by_num[num], 0, lines)
                    lines.append("")
                if suppl_re:
                    for a in orig_arts:
                        t = text_of(a)
                        if re.search(suppl_re, caption(a)) or re.search(suppl_re, t):
                            lines.append(f"## 原始附則 Num={a['attr'].get('Num')}")
                            render(a, 0, lines)
                            lines.append("")
                for an in amend_nums:
                    hits = [s for s in amend_suppl if re.search(an, s.get("attr", {}).get("AmendLawNum") or "")]
                    lines.append(f"## 改正附則 AmendLawNum~/{an}/: {len(hits)} 件")
                    for s in hits:
                        lines.append(f"### 改正附則 {s.get('attr', {}).get('AmendLawNum')}")
                        render(s, 0, lines)
                    lines.append("")
                if short in APPDX:
                    tabs = []
                    walk(root, lambda m, p: tabs.append(m) if m.get("tag") == "AppdxTable" else None)
                    for tnode in tabs:
                        ttl = "".join(inline(c) for c in tnode.get("children", []) if isinstance(c, dict) and c.get("tag") == "AppdxTableTitle")
                        if not re.search(APPDX[short], ttl):
                            continue
                        alines = list(header) + [f"## 別表 {ttl}"]
                        render(tnode, 0, alines)
                        (out / f"{short}_appdx_{asof}.txt").write_text("\n".join(alines) + "\n", encoding="utf-8")
                        log.setdefault("appdx", []).append({"short": short, "asof": asof, "title": ttl, "rows": sum(1 for l in alines if l.lstrip().startswith("|"))})
                body = "\n".join(lines[len(header):])
                bodies[asof] = body
                (out / f"{short}_{asof}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
                # キーワードの出現箇所
                hits = {}
                for kind, arts_ in (("本則", main_arts), ("原始附則", orig_arts)):
                    for a in arts_:
                        t = text_of(a).replace("\n", "")
                        for k in KEYWORDS:
                            for m in re.finditer(re.escape(k), t):
                                s = max(0, m.start() - 60)
                                hits.setdefault(k, []).append({"where": kind, "article": a["attr"].get("Num"), "caption": caption(a),
                                                               "snippet": t[s:m.end() + 80]})
                for s_ in amend_suppl:
                    t = text_of(s_).replace("\n", "")
                    for k in KEYWORDS:
                        for m in re.finditer(re.escape(k), t):
                            s = max(0, m.start() - 60)
                            hits.setdefault(k, []).append({"where": "改正附則", "article": s_.get("attr", {}).get("AmendLawNum"),
                                                           "snippet": t[s:m.end() + 80]})
                (out / f"hits_{short}_{asof}.json").write_text(json.dumps(hits, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"ok {short} {asof} {ri.get('law_revision_id')} {ri.get('current_revision_status')} chosen={len(chosen)}", flush=True)
            got = [a for a in asofs if a in bodies]
            for x, y in zip(got, got[1:]):
                diff = "\n".join(difflib.unified_diff(bodies[x].splitlines(), bodies[y].splitlines(), f"{short}@{x}", f"{short}@{y}", lineterm=""))
                (out / f"diff_{short}_{x}_vs_{y}.diff").write_text(diff + "\n", encoding="utf-8")
            if short in ("chiho", "chiho-rei"):
                q = urllib.parse.urlencode({"response_format": "json", "amendment_date_from": "2025-01-01"})
                st, raw = get(f"{API}/law_revisions/{law_id}?{q}", dl / f"revisions_{short}.json")
                if st == 200:
                    data = json.loads(raw)
                    revs = [{k: rv.get(k) for k in ("law_revision_id", "amendment_promulgate_date", "amendment_enforcement_date",
                                                     "amendment_scheduled_enforcement_date", "amendment_law_title", "amendment_law_num",
                                                     "current_revision_status", "updated")} for rv in data.get("revisions", [])]
                    (out / f"revisions_{short}.json").write_text(json.dumps(revs, ensure_ascii=False, indent=1), encoding="utf-8")
                else:
                    log["errors"].append({"law": title, "revisions_status": st})
        except Exception as e:  # noqa
            log["errors"].append({"law": title, "error": repr(e)})
            print(f"ERR {short} {e!r}", flush=True)

    for n, kw in enumerate(SEARCH if not only else []):
        q = urllib.parse.urlencode({"keyword": kw, "response_format": "json", "asof": "2026-11-09", "limit": 100, "sentences_limit": 5})
        st, raw = get(f"{API}/keyword?{q}", dl / f"keyword_{n}.json")
        if st != 200:
            res = {"keyword": kw, "status": st, "body": raw[:300].decode("utf-8", "replace")}
        else:
            data = json.loads(raw)
            items = []
            for it in data.get("items", []):
                li, rv = it.get("law_info", {}), it.get("revision_info", {})
                items.append({"law_id": li.get("law_id"), "law_num": li.get("law_num"), "law_title": rv.get("law_title"),
                              "law_revision_id": rv.get("law_revision_id"),
                              "sentences": [{"position": s.get("position"), "text": re.sub(r"<[^>]+>", "", s.get("text") or "")}
                                            for s in it.get("sentences", [])]})
            res = {"keyword": kw, "asof": "2026-11-09", "total_count": data.get("total_count"), "items": items}
        (out / f"keyword_{n}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"ok keyword {kw} {res.get('total_count', res.get('status'))}", flush=True)

    (out / ("fetch_log.json" if not only else f"fetch_log_{'_'.join(sorted(only))}.json")).write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", out)


if __name__ == "__main__":
    sys.exit(main())

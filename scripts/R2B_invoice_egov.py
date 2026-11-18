"""R2B invoice: e-Gov 法令API v2 で、消費税の納税義務・適格請求書発行事業者の登録・インボイスの経過措置と、
所得税の計算で消費税等の経理処理に関係する条文を、時点（asof）ごとに取得する。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_invoice_egov.py probe
      法令の検索（/laws）で、消費税法・平成28年法律第15号（所得税法等の一部を改正する法律）などが e-Gov にあるかを調べ、
      消費税法・所得税法施行令の改正履歴（/law_revisions、2023-01-01 以後）を取る。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_invoice_egov.py fetch
      JOBS の法令・時点の本文（/law_data）を取得し、条・附則を抜き出し、キーワードを検索する。

- e-Gov の使い方は scripts/R1_egov_articles.py と scripts/IMPL_kyuyo_fetch.py を写した（import はしない）。
- 取得した JSON は信頼できないデータとして、取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_R2B_invoice_egov_<mode>/ に置く。その中で何も実行しない。
- 結果は scripts/results/R2B_invoice_egov/ に書く。
  - probe_log.json：検索・改正履歴の結果（URL、ステータス、件数、主な項目、SHA-256）
  - revisions_<略称>.json：改正履歴
  - fetch_log.json：取得URL、asof、law_revision_id、改正法令、施行日、状態、生データの SHA-256 とバイト数
  - articles_<略称>_<asof>.txt：抜き出した条と附則のテキスト
  - suppl_index_<略称>_<asof>.txt：附則（SupplProvision）の AmendLawNum と、その中の条番号・見出しの一覧
  - keyword_hits_<略称>_<asof>.json：キーワードの出現箇所
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。
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
OUT = ROOT / "scripts" / "results" / "R2B_invoice_egov"

H28 = "平成二八年三月三一日法律第一五号"
R5 = "令和五年三月三一日法律第三号"
R6 = "令和六年三月三〇日法律第八号"
R7 = "令和七年三月三一日法律第一三号"
R8 = "令和八年三月三一日法律第一二号"
H30REI = "平成三〇年三月三一日政令第一三一号"  # 所得税法施行令等の一部を改正する政令
R8REI = "令和八年三月三一日政令第九三号"

KW_SHOHI = ["千万円", "第五十七条の二", "適格請求書発行事業者", "百分の八十", "百分の七十", "百分の五十", "百分の三十",
            "百分の二十", "十分の二", "十分の三", "令和八年九月三十日", "令和十年", "令和十一年", "令和十二年", "令和十三年",
            "特定期間", "基準期間"]
KW_SHOTOKU = ["消費税", "控除対象外消費税額等", "地方消費税"]

# (略称, law_id, [asof...], [本則の条番号 Num], [附則を全文で取り出す改正法令番号（AmendLawNum）], [キーワード])
JOBS = [
    ("shohi", "363AC0000000108", ["2025-12-31", "2026-09-30", "2026-11-09", "2027-10-01", "2028-04-01"],
     ["2", "9", "9_2", "19", "30", "42", "44", "45", "57_2", "57_3", "57_4"], [H28, R5, R6, R7, R8], KW_SHOHI),
    ("shotoku-rei", "340CO0000000096", ["2026-09-30", "2026-11-09"], ["182_2"], [H30REI, R8REI], KW_SHOTOKU),
    ("shotoku", "340AC0000000033", ["2026-11-09"], ["36", "37"], [], KW_SHOTOKU),
    ("sochi", "332AC0000000026", ["2026-11-09"], ["86_4"], [], KW_SHOTOKU),
]
SEARCHES = [
    ("laws_shohi", {"law_title": "消費税法"}),
    ("laws_h28_15", {"law_num": "平成二十八年法律第十五号"}),
    ("laws_r8_12", {"law_num": "令和八年法律第十二号"}),
    ("laws_r5_3", {"law_num": "令和五年法律第三号"}),
    ("laws_title_kaisei", {"law_title": "所得税法等の一部を改正する法律"}),
]
REVISIONS = [("shohi", "363AC0000000108"), ("shotoku-rei", "340CO0000000096")]
DIRECT = [("law_data_428AC0000000015", "428AC0000000015")]

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


# ---- テキスト化（scripts/IMPL_kyuyo_fetch.py の inline / render を写したもの） ----
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


def title_of(a):
    for c in a.get("children", []):
        if isinstance(c, dict) and c.get("tag") == "ArticleTitle":
            return inline(c)
    return ""


def locate(path, node):
    loc = {"part": "MainProvision", "amend_law_num": None, "article": None, "article_title": None, "caption": None, "paragraph": None}
    for p in list(path) + [node]:
        t = p.get("tag")
        a = p.get("attr") or {}
        if t == "SupplProvision":
            loc["part"] = "SupplProvision"
            loc["amend_law_num"] = a.get("AmendLawNum", "(原始附則)")
        elif t == "Article":
            loc["article"] = a.get("Num")
            loc["article_title"] = title_of(p)
            loc["caption"] = caption_of(p)
        elif t == "Paragraph":
            loc["paragraph"] = a.get("Num")
    return loc


def keyword_hits(root, keywords):
    hits = []

    def fn(n, path):
        if n.get("tag", "") == "Sentence":
            txt = inline(n)
            for kw in keywords:
                i = txt.find(kw)
                if i >= 0:
                    hits.append({"keyword": kw, **locate(path, n), "snippet": txt[max(0, i - 120): i + 160]})
    walk(root, fn)
    return hits


def fetch_full(law_id, asof, dl):
    q = {"response_format": "json", "asof": asof}
    url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode(q)
    # 2026-11-09 の最初の実行で、ステータス 200 のまま JSON でない応答（HTML のページ）が返ったことがあったので、
    # JSON として読めない応答は 5 秒あけて 3 回まで取り直す。
    for attempt in range(3):
        st, body = get(url)
        (dl / f"{law_id}_{asof}_try{attempt}.json").write_bytes(body)
        if st == 200 and body.lstrip()[:1] == b"{":
            try:
                return url, body, json.loads(body)
            except json.JSONDecodeError:
                pass
        time.sleep(5)
    raise RuntimeError(f"{url} -> {st} {body[:200]!r}")


def new_dl(mode):
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2B_invoice_egov_{mode}"
    dl.mkdir(parents=True, exist_ok=False)
    return ts, dl


def probe():
    ts, dl = new_dl("probe")
    OUT.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "searches": [], "direct": [], "revisions": []}
    for key, params in SEARCHES:
        q = urllib.parse.urlencode({"response_format": "json", **params})
        url = f"{API}/laws?{q}"
        st, body = get(url)
        (dl / f"{key}.json").write_bytes(body)
        ent = {"key": key, "url": url, "status": st, "sha256": hashlib.sha256(body).hexdigest(), "laws": []}
        if st == 200:
            d = json.loads(body)
            ent["total_count"] = d.get("total_count")
            for lw in d.get("laws", []):
                li = lw.get("law_info") or {}
                ri = lw.get("revision_info") or lw.get("current_revision_info") or {}
                ent["laws"].append({"law_id": li.get("law_id"), "law_num": li.get("law_num"), "law_type": li.get("law_type"),
                                    "promulgation_date": li.get("promulgation_date"), "law_title": ri.get("law_title"),
                                    "law_revision_id": ri.get("law_revision_id"), "current_revision_status": ri.get("current_revision_status")})
        else:
            ent["body_head"] = body[:300].decode("utf-8", "replace")
        log["searches"].append(ent)
        print("search", key, st, ent.get("total_count"), flush=True)
    for key, law_id in DIRECT:
        url = f"{API}/law_data/{law_id}?response_format=json"
        st, body = get(url)
        (dl / f"{key}.json").write_bytes(body)
        ent = {"key": key, "url": url, "status": st, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
               "body_head": body[:300].decode("utf-8", "replace") if st != 200 else None}
        if st == 200:
            ri = json.loads(body).get("revision_info") or {}
            ent["law_title"] = ri.get("law_title")
            ent["law_revision_id"] = ri.get("law_revision_id")
        log["direct"].append(ent)
        print("direct", key, st, flush=True)
    for short, law_id in REVISIONS:
        q = urllib.parse.urlencode({"response_format": "json", "amendment_date_from": "2023-01-01"})
        url = f"{API}/law_revisions/{law_id}?{q}"
        st, body = get(url)
        (dl / f"revisions_{law_id}.json").write_bytes(body)
        revs = []
        if st == 200:
            for rv in json.loads(body).get("revisions", []):
                revs.append({k: rv.get(k) for k in ("law_revision_id", "amendment_promulgate_date", "amendment_enforcement_date",
                                                   "amendment_scheduled_enforcement_date", "amendment_law_title", "amendment_law_num",
                                                   "current_revision_status")})
        (OUT / f"revisions_{short}.json").write_text(json.dumps({"url": url, "status": st, "revisions": revs}, ensure_ascii=False, indent=1), encoding="utf-8")
        log["revisions"].append({"short": short, "url": url, "status": st, "n": len(revs), "sha256": hashlib.sha256(body).hexdigest()})
        print("revisions", short, st, len(revs), flush=True)
    (OUT / "probe_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


def fetch():
    ts, dl = new_dl("fetch")
    OUT.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "fetches": []}
    for short, law_id, asofs, arts, amend_nums, kws in JOBS:
        for asof in asofs:
            url, body, d = fetch_full(law_id, asof, dl)
            ri = d.get("revision_info") or {}
            entry = {"short": short, "law_id": law_id, "asof": asof, "url": url, "law_title": ri.get("law_title"),
                     "law_revision_id": ri.get("law_revision_id"), "amendment_law_num": ri.get("amendment_law_num"),
                     "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                     "current_revision_status": ri.get("current_revision_status"),
                     "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
            log["fetches"].append(entry)
            print("ok", short, asof, ri.get("law_revision_id"), flush=True)
            root = d["law_full_text"]
            main_arts, suppl = [], []

            def collect(n, path):
                tags = [p.get("tag") for p in path]
                if n.get("tag") == "Article" and "SupplProvision" not in tags:
                    main_arts.append(n)
                if n.get("tag") == "SupplProvision":
                    suppl.append(n)
            walk(root, collect)
            header = [f"# {short} {law_id} asof={asof}",
                      f"# 法令名={ri.get('law_title')} law_revision_id={ri.get('law_revision_id')} 改正法令={ri.get('amendment_law_num')} "
                      f"施行日={ri.get('amendment_enforcement_date')} 状態={ri.get('current_revision_status')}",
                      f"# 取得URL={url}", f"# 取得日時={ts}", f"# 生データ SHA-256={entry['sha256']}", ""]
            lines = list(header)
            by_num = {a["attr"].get("Num"): a for a in main_arts}
            for num in arts:
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
            (OUT / f"articles_{short}_{asof}.txt").write_text("\n".join(lines), encoding="utf-8")
            idx = list(header)
            for s in suppl:
                an = (s.get("attr") or {}).get("AmendLawNum", "(原始附則)")
                arts_in = []
                walk(s, lambda n, p: arts_in.append(n) if n.get("tag") == "Article" else None)
                idx.append(f"{an}\t条の数={len(arts_in)}")
                if an in amend_nums:
                    for a in arts_in:
                        idx.append(f"\t{a['attr'].get('Num')}\t{title_of(a)}\t{caption_of(a)}")
            (OUT / f"suppl_index_{short}_{asof}.txt").write_text("\n".join(idx), encoding="utf-8")
            kh = keyword_hits(root, kws)
            (OUT / f"keyword_hits_{short}_{asof}.json").write_text(
                json.dumps({"law_id": law_id, "asof": asof, "law_revision_id": ri.get("law_revision_id"), "keywords": kws, "hits": kh},
                           ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", OUT)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "probe":
        probe()
    elif mode == "fetch":
        fetch()
    else:
        print(__doc__)

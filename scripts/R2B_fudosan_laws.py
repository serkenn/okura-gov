"""R2B_fudosan_laws: 不動産所得（第2ラウンド追加分、トピック fudosan）のため、e-Gov 法令API v2 で
条文を時点（asof）ごとに取得し、テキスト・条の索引・キーワードの出現箇所・時点間の差分を書き出す。

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_fudosan_laws.py

- e-Gov の取得とテキスト化は scripts/R1_egov_articles.py・scripts/IMPL_kyuyo_fetch.py の get / inline / render / walk を
  写したもの（import はしない）。標準ライブラリのみ。
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。個人の情報は送らない。
- 取得した JSON は信頼できないデータとして .work/downloads/<YYYYMMDD-HHMMSS>_R2B_fudosan_laws/ に置く（中で何も実行しない）。
- 出力：scripts/results/R2B_fudosan_laws/
  - fetch_log.json：取得URL、asof、law_revision_id、改正法令、施行日、状態、生データの SHA-256 とバイト数
  - <略称>_<asof>.txt：抜き出した条（本則の指定した条、キーワードを含む条、原始附則のうちキーワードを含む条）
  - index_<略称>_<asof>.txt：本則の条番号と見出しの一覧
  - keyword_hits_<略称>_<asof>.json：キーワードの出現箇所（本則/附則、条、項）
  - diff_<略称>_<asof1>_vs_<asof2>.diff：抜き出したテキストの時点間の差分（ヘッダ行を除く）
  - revisions_<略称>.json：改正履歴（2025-01-01 以後）
"""
import difflib
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

ASOFS = ["2025-12-31", "2026-11-09", "2026-12-31", "2027-01-01"]

# (略称, law_id, [asof...], [本則の条番号 Num], [本則でこの語を含む条を全部抜き出す], [原始附則でこの語を含む条を抜き出す], [キーワード])
JOBS = [
    ("shotoku", "340AC0000000033", ASOFS,
     ["2", "26", "33", "36", "37", "51", "56", "57", "63", "64", "69", "70", "143", "152"],
     [], [],
     ["不動産所得", "不動産等", "事業的規模", "生計を一にする", "貸倒れ", "生活に通常必要でない資産"]),
    ("shotoku-rei", "340CO0000000096", ASOFS,
     ["79", "80", "178", "180", "198", "200"],
     ["不動産所得"], [],
     ["不動産所得", "生計を一にする", "借地権"]),
    ("sochi", "332AC0000000026", ASOFS,
     ["25_2", "41_4", "41_4_2", "41_4_3"],
     ["第四十一条の四"], [],
     ["第四十一条の四", "不動産所得の金額の計算上生じた損失", "土地等を取得するために要した負債の利子"]),
    ("sochi-rei", "332CO0000000043", ["2025-12-31", "2026-12-31"],
     [],
     ["第四十一条の四"], [],
     ["第四十一条の四", "負債の利子"]),
    ("chiho", "325AC0000000226", ["2025-12-31", "2026-12-31", "2027-01-01"],
     ["32", "313"],
     [], ["第四十一条の四", "不動産所得"],
     ["第四十一条の四", "不動産所得の金額の計算上生じた損失", "土地等を取得するために要した負債の利子"]),
]
REVISIONS = [("shotoku", "340AC0000000033"), ("shotoku-rei", "340CO0000000096"), ("sochi", "332AC0000000026"),
             ("sochi-rei", "332CO0000000043")]

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


def locate(path, node):
    loc = {"part": "MainProvision", "amend_law_num": None, "article": None, "caption": None, "paragraph": None, "item": None}
    for p in list(path) + [node]:
        t = p.get("tag")
        a = p.get("attr") or {}
        if t == "SupplProvision":
            loc["part"] = "SupplProvision"
            loc["amend_law_num"] = a.get("AmendLawNum", "(原始附則)")
        elif t == "Article":
            loc["article"] = a.get("Num")
            loc["caption"] = caption_of(p)
        elif t == "Paragraph":
            loc["paragraph"] = a.get("Num")
        elif t == "Item":
            loc["item"] = a.get("Num")
    return loc


def keyword_hits(root, keywords):
    hits = []

    def fn(n, path):
        if n.get("tag", "") == "Sentence":
            txt = inline(n)
            for kw in keywords:
                i = txt.find(kw)
                if i >= 0:
                    hits.append({"keyword": kw, **locate(path, n), "snippet": txt[max(0, i - 120): i + 200]})
    walk(root, fn)
    return hits


def article_text(a):
    tl = []
    render(a, 0, tl)
    return tl


PIN_ASOFS = ["2025-12-31", "2026-01-01", "2026-03-31", "2026-04-01", "2026-05-21", "2028-01-01", "2026-05-22"]


def pin198():
    """所令198（損益通算の順序）の文言「及び」→「又は」が、どの版で変わったかを確かめる（引数 pin198 で実行）。
    出力：scripts/results/R2B_fudosan_laws/pin198.json（asof ごとの law_revision_id・改正法令・第198条第3号の文言）と、
    改正政令の附則のうち「第百九十八条」を含む文。"""
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2B_fudosan_laws_pin198"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "R2B_fudosan_laws"
    res = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "rows": []}
    for asof in PIN_ASOFS:
        url = f"{API}/law_data/340CO0000000096?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
        st, body = get(url)
        (dl / f"340CO0000000096_{asof}.json").write_bytes(body)
        d = json.loads(body)
        ri = d.get("revision_info") or {}
        root = d["law_full_text"]
        item3, suppl_hits, art198, art178 = None, [], [], []

        def fn(n, path):
            nonlocal item3
            if n.get("tag") == "Article" and (n.get("attr") or {}).get("Num") == "198" and not any(p.get("tag") == "SupplProvision" for p in path):
                for line in article_text(n):
                    if line.strip().startswith("三　"):
                        item3 = line.strip()
                art198.extend(article_text(n))
            if n.get("tag") == "Article" and (n.get("attr") or {}).get("Num") == "178" and not any(p.get("tag") == "SupplProvision" for p in path):
                art178.extend(article_text(n))
            if n.get("tag") == "Sentence":
                sp = [p for p in path if p.get("tag") == "SupplProvision"]
                t = inline(n)
                if sp and "第百九十八条" in t:
                    suppl_hits.append({"amend_law_num": (sp[0].get("attr") or {}).get("AmendLawNum"), "text": t[:400]})
        walk(root, fn)
        if asof == PIN_ASOFS[-1]:
            # 令和8年政令第93号の附則（施行期日）を全文で書き出す
            sl = []

            def fs(n, path):
                if n.get("tag") == "SupplProvision" and (n.get("attr") or {}).get("AmendLawNum") == "令和八年三月三一日政令第九三号":
                    render(n, 0, sl)
            walk(root, fs)
            (out / "pin198_suppl_R8seirei93.txt").write_text(
                f"# 所得税法施行令 asof={asof} law_revision_id={ri.get('law_revision_id')} 附則 AmendLawNum=令和八年三月三一日政令第九三号\n"
                f"# 取得URL={url}\n\n" + "\n".join(sl), encoding="utf-8")
        res["rows"].append({"asof": asof, "status": st, "law_revision_id": ri.get("law_revision_id"),
                            "amendment_law_num": ri.get("amendment_law_num"), "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                            "sha256": hashlib.sha256(body).hexdigest(),
                            "uses_oyobi": bool(item3 and "譲渡所得の金額及び一時所得の金額" in item3),
                            "uses_matawa": bool(item3 and "譲渡所得の金額又は一時所得の金額" in item3),
                            "item3": item3, "suppl_hits_198": suppl_hits, "art198": art198, "art178": art178})
        print("ok", asof, ri.get("law_revision_id"), flush=True)
    (out / "pin198.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    if sys.argv[1:] == ["pin198"]:
        return pin198()
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2B_fudosan_laws"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "R2B_fudosan_laws"
    out.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "fetches": [], "revisions": []}
    texts = {}
    for short, law_id, asofs, arts, grep_main, grep_suppl, kws in JOBS:
        for asof in asofs:
            url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
            st, body = get(url)
            (dl / f"{law_id}_{asof}.json").write_bytes(body)
            if st != 200:
                log["fetches"].append({"short": short, "law_id": law_id, "asof": asof, "url": url, "status": st})
                print("ERR", short, asof, st, flush=True)
                continue
            d = json.loads(body)
            ri = d.get("revision_info") or {}
            entry = {"short": short, "law_id": law_id, "asof": asof, "url": url, "status": st,
                     "law_title": ri.get("law_title"), "law_revision_id": ri.get("law_revision_id"),
                     "amendment_law_num": ri.get("amendment_law_num"),
                     "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                     "current_revision_status": ri.get("current_revision_status"),
                     "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
            log["fetches"].append(entry)
            print("ok", short, asof, ri.get("law_revision_id"), flush=True)
            root = d["law_full_text"]
            main_arts, orig_suppl_arts = [], []

            def collect(n, path):
                if n.get("tag") != "Article":
                    return
                supp = [p for p in path if p.get("tag") == "SupplProvision"]
                if not supp:
                    main_arts.append(n)
                elif not (supp[0].get("attr") or {}).get("AmendLawNum"):
                    orig_suppl_arts.append(n)
            walk(root, collect)
            header = [f"# {short} {law_id} asof={asof}",
                      f"# 法令名={ri.get('law_title')} law_revision_id={ri.get('law_revision_id')} 改正法令={ri.get('amendment_law_num')} "
                      f"施行日={ri.get('amendment_enforcement_date')} 状態={ri.get('current_revision_status')}",
                      f"# 取得URL={url}", f"# 取得日時={ts}", f"# 生データ SHA-256={entry['sha256']}", ""]
            body_lines = []
            by_num = {a["attr"].get("Num"): a for a in main_arts}
            sel = list(arts)
            for a in main_arts:
                num = a["attr"].get("Num")
                if num in sel:
                    continue
                tl = article_text(a)
                if any(any(g in x for x in tl) for g in grep_main):
                    sel.append(num)
            for num in sel:
                a = by_num.get(num)
                if a is None:
                    body_lines += [f"## 本則 Num={num}: 見つからない（この時点の本則にない）", ""]
                    continue
                body_lines.append(f"## 本則 Num={num}")
                body_lines += article_text(a)
                body_lines.append("")
            for a in orig_suppl_arts:
                tl = article_text(a)
                if any(any(g in x for x in tl) for g in grep_suppl):
                    body_lines.append(f"## 原始附則 Num={a['attr'].get('Num')}")
                    body_lines += tl
                    body_lines.append("")
            texts[(short, asof)] = body_lines
            (out / f"{short}_{asof}.txt").write_text("\n".join(header + body_lines), encoding="utf-8")
            idx = header + [f"{a['attr'].get('Num')}\t{caption_of(a)}" for a in main_arts]
            (out / f"index_{short}_{asof}.txt").write_text("\n".join(idx), encoding="utf-8")
            kh = keyword_hits(root, kws)
            (out / f"keyword_hits_{short}_{asof}.json").write_text(
                json.dumps({"law_id": law_id, "asof": asof, "law_revision_id": ri.get("law_revision_id"), "keywords": kws,
                            "hits": kh}, ensure_ascii=False, indent=1), encoding="utf-8")
        for a1, a2 in zip(asofs, asofs[1:]):
            if (short, a1) in texts and (short, a2) in texts:
                diff = list(difflib.unified_diff(texts[(short, a1)], texts[(short, a2)], f"{short}_{a1}", f"{short}_{a2}", lineterm=""))
                (out / f"diff_{short}_{a1}_vs_{a2}.diff").write_text("\n".join(diff) + ("\n" if diff else "(差分なし)\n"), encoding="utf-8")
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

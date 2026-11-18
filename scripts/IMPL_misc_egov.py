"""IMPL_misc: e-Gov 法令API v2 で、扶養の所属・死亡後の再婚の特例・源泉徴収の区分などの条文を版ごとに取り出し、
「扶養親族とされた人が別の人を扶養する申告者になれるか」に関わる書き方を本則の全文から機械的に拾う。

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_misc_egov.py

- R1_egov_articles.py・R4_fetch_laws.py のコードを写して作った（import はしない）。標準ライブラリのみ。
- 本文（JSON）は .work/downloads/<YYYYMMDD-HHMMSS>_IMPL_misc_egov/ に置く（信頼できないデータ。中で何も実行しない）。
- 出力は scripts/results/IMPL_misc_egov/：
  - <略称>_asof<日付>.txt   指定した条（項・号の構造つき）。先頭に law_revision_id・施行日・取得URL
  - <略称>_diff_<日付1>_vs_<日付2>.diff  版の間の差分
  - scan.json / scan.md   本則の全文から拾った行（「民法」「年少扶養親族」「適用を受けている場合」など）
  - keyword_*.json        キーワード検索API の結果
  - fetch_log.json        取得の記録（URL・版・状態）
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。
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
TODAY = "2026-11-09"

# 版：令和7年分の年末（2025-12-31）、取得日（2026-11-09）、令和8年分の年末（2026-12-31。未施行の改正の施行予定分を含む版）
ASOFS_SHOTOKU = ["2025-12-31", "2026-11-09", "2026-12-31"]

# (略称, 法令名, law_id（None なら /laws で引く）, [asof...], [条番号], 見出しの正規表現)
JOBS = [
    ("shotoku", "所得税法", "340AC0000000033", ASOFS_SHOTOKU,
     ["83_2", "84", "84_2", "85", "121", "185", "190", "194", "195", "195_3"], None),
    ("shotoku-rei", "所得税法施行令", "340CO0000000096", ASOFS_SHOTOKU,
     ["217_2", "217_3", "218", "218_2", "219", "220"], r"源泉控除対象親族"),
    ("shotoku-ki", "所得税法施行規則", "340M50000040011", [TODAY], [], None),
    ("chiho", "地方税法", "325AC0000000226", [TODAY], [], None),
    ("chiho-rei", "地方税法施行令", None, [TODAY], [], None),
]
# 所得税法第2条第1項のうち取り出す号（Item の Num 属性）
SHOTOKU_ART2_ITEMS = ["30", "31", "32", "33", "33_2", "33_3", "33_4", "34", "34_2", "34_3", "34_4", "34_5"]

# 本則の全文から拾う行の正規表現（行＝項・号・イロハの1単位）
SCAN = {
    "minpo": r"民法",
    "nensho": r"年少扶養親族",
    "applied_as_resident": r"居住者として[^。]*適用を受けている場合",
    "applied_case": r"適用を受けている場合",
    "fuyo_status": r"扶養親族(?:とされ|に該当する者|に該当するもの)|特定親族とされ|同一生計配偶者又は扶養親族",
    "age_rule": r"十二月三十一日の現況|年齢[^。]{0,20}(?:以上|未満)",
}
SCAN_TARGETS = {"shotoku", "shotoku-rei", "shotoku-ki", "chiho", "chiho-rei"}
KEYWORDS = ["年少扶養親族"]

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
    if n.get("tag") in ("Rt",):  # ルビの読みは落とす
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


def article_caption(a):
    for c in a.get("children", []):
        if isinstance(c, dict) and c.get("tag") == "ArticleCaption":
            return inline(c)
    return ""


def find_law_id(title, dl):
    q = urllib.parse.urlencode({"law_title": title, "response_format": "json", "asof": TODAY})
    st, body = get(f"{API}/laws?{q}")
    (dl / f"laws_{title}.json").write_bytes(body)
    data = json.loads(body)
    for law in data.get("laws", []):
        rv = law.get("current_revision_info") or law.get("revision_info") or {}
        if rv.get("law_title") == title:
            return law["law_info"]["law_id"]
    return None


def fetch_full(law_id, asof, dl):
    q = {"response_format": "json", "asof": asof, "omit_amendment_suppl_provision": "true"}
    url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode(q)
    st, body = get(url)
    (dl / f"{law_id}_{asof}.json").write_bytes(body)
    if st != 200:
        raise RuntimeError(f"{url} -> {st} {body[:200]!r}")
    return url, json.loads(body)


def main_articles(root):
    arts = []

    def collect(n, path):
        if n.get("tag") == "Article" and "SupplProvision" not in path:
            arts.append(n)
    walk(root, collect)
    return arts


def art2_items(a, wanted):
    """第2条第1項の号のうち wanted のものを出す。"""
    lines = []
    for p in a.get("children", []):
        if not (isinstance(p, dict) and p.get("tag") == "Paragraph" and p.get("attr", {}).get("Num") == "1"):
            continue
        for it in p.get("children", []):
            if isinstance(it, dict) and it.get("tag") == "Item" and it.get("attr", {}).get("Num") in wanted:
                lines.append(f"### 第2条第1項 Item Num={it['attr']['Num']}")
                render(it, 0, lines)
                lines.append("")
    return lines


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL_misc_egov"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "IMPL_misc_egov"
    out.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "fetches": [], "errors": []}
    scan = {}
    texts = {}
    for short, title, law_id, asofs, arts, cap_re in JOBS:
        try:
            if law_id is None:
                law_id = find_law_id(title, dl)
                if not law_id:
                    log["errors"].append({"law": title, "error": "law_id not found"})
                    continue
            for asof in asofs:
                url, d = fetch_full(law_id, asof, dl)
                ri = d.get("revision_info") or {}
                log["fetches"].append({"short": short, "law": title, "law_id": law_id, "asof": asof, "url": url,
                                       "law_revision_id": ri.get("law_revision_id"),
                                       "amendment_law_title": ri.get("amendment_law_title"),
                                       "amendment_law_num": ri.get("amendment_law_num"),
                                       "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                                       "current_revision_status": ri.get("current_revision_status"),
                                       "updated": ri.get("updated")})
                root = d["law_full_text"]
                marts = main_articles(root)
                by_num = {a["attr"].get("Num"): a for a in marts}
                header = [f"# {short} {title} {law_id} asof={asof}",
                          f"# law_revision_id={ri.get('law_revision_id')} 改正法令={ri.get('amendment_law_num')} "
                          f"施行日={ri.get('amendment_enforcement_date')} 状態={ri.get('current_revision_status')}",
                          f"# 取得URL={url}", f"# 取得日時={ts}", ""]
                if arts or cap_re or short == "shotoku":
                    lines = list(header)
                    if short == "shotoku" and "2" in by_num:
                        lines.append("## Num=2（第1項の指定した号だけ）")
                        lines += art2_items(by_num["2"], SHOTOKU_ART2_ITEMS)
                    picked = list(arts)
                    if cap_re:
                        for a in marts:
                            n = a["attr"].get("Num")
                            if re.search(cap_re, article_caption(a)) and n not in picked:
                                picked.append(n)
                    for num in picked:
                        a = by_num.get(num)
                        if a is None:
                            lines += [f"## Num={num}: 見つからない（この版の本則にない）", ""]
                            continue
                        lines.append(f"## Num={num}")
                        render(a, 0, lines)
                        lines.append("")
                    body = "\n".join(lines[len(header):])
                    texts[(short, asof)] = body
                    (out / f"{short}_asof{asof}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
                if short in SCAN_TARGETS:
                    res = {}
                    for a in marts:
                        alines = []
                        render(a, 0, alines)
                        num = a["attr"].get("Num")
                        cap = article_caption(a)
                        for ln in alines:
                            for key, pat in SCAN.items():
                                if re.search(pat, ln):
                                    res.setdefault(key, []).append({"article": num, "caption": cap, "line": ln.strip()[:600]})
                    scan[f"{short}@{asof}"] = {"law_revision_id": ri.get("law_revision_id"),
                                               "counts": {k: len(v) for k, v in res.items()}, "hits": res}
                print(f"ok {short} {asof} {ri.get('law_revision_id')}", flush=True)
            # 版の間の差分
            for i in range(len(asofs) - 1):
                x, y = asofs[i], asofs[i + 1]
                if (short, x) in texts and (short, y) in texts:
                    diff = "\n".join(difflib.unified_diff(texts[(short, x)].splitlines(), texts[(short, y)].splitlines(),
                                                          f"{short}@{x}", f"{short}@{y}", lineterm=""))
                    (out / f"{short}_diff_{x}_vs_{y}.diff").write_text(diff + "\n", encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            log["errors"].append({"law": title, "error": repr(e)})
            print(f"ERR {title} {e!r}", flush=True)

    # キーワード検索API（「年少扶養親族」がどの法令に出てくるか）
    for n, kw in enumerate(KEYWORDS):
        q = urllib.parse.urlencode({"keyword": kw, "response_format": "json", "asof": TODAY, "limit": 1000, "sentences_limit": 5})
        st, body = get(f"{API}/keyword?{q}")
        (dl / f"keyword_{n}.json").write_bytes(body)
        rec = {"keyword": kw, "asof": TODAY, "status": st}
        try:
            data = json.loads(body)
            items = []
            for it in data.get("items", []):
                li, rv = it.get("law_info", {}), it.get("revision_info", {})
                items.append({"law_id": li.get("law_id"), "law_num": li.get("law_num"), "law_title": rv.get("law_title"),
                              "law_type": li.get("law_type"),
                              "sentences": [{"position": s.get("position"), "text": re.sub(r"<[^>]+>", "", s.get("text") or "")}
                                            for s in it.get("sentences", [])]})
            rec.update({"total_count": data.get("total_count"), "sentence_count": data.get("sentence_count"), "items": items,
                        "raw_message": data.get("message")})
        except Exception as e:  # noqa: BLE001
            rec["error"] = repr(e)
            rec["body_head"] = body[:300].decode("utf-8", "replace")
        (out / f"keyword_{n}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"keyword {kw} status={st} total={rec.get('total_count')}", flush=True)

    (out / "scan.json").write_text(json.dumps(scan, ensure_ascii=False, indent=1), encoding="utf-8")
    md = [f"# 本則の全文から拾った行（取得 {ts}）", ""]
    for k, v in scan.items():
        md += [f"## {k}（{v['law_revision_id']}）", "", "| 種類 | 件数 |", "|---|---|"]
        md += [f"| {kk} | {vv} |" for kk, vv in v["counts"].items()]
        md.append("")
        for key in ("minpo", "nensho", "applied_as_resident", "fuyo_status"):
            for h in v["hits"].get(key, []):
                md.append(f"- [{key}] 第{h['article']}条{h['caption']}：{h['line'][:300]}")
        md.append("")
    (out / "scan.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (out / "fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", out)


if __name__ == "__main__":
    main()

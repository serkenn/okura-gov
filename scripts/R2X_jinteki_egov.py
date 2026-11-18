"""R2X_jinteki: 障害者控除・寡婦控除・ひとり親控除と、住民税の非課税（障害者・寡婦・ひとり親）の定義を、
e-Gov 法令API v2 で版ごとに取り出す。健保の被扶養者の 180万円の「障害厚生年金の受給要件に該当する程度」の
障害等級の条文と、障害者控除の範囲（所令10）が引用する手帳・認定の根拠条文も取り出す。

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_jinteki_egov.py

- scripts/R1_egov_articles.py・scripts/IMPL_misc_egov.py のコードを写して作った（import はしない）。標準ライブラリのみ。
- 本文（JSON）は .work/downloads/<YYYYMMDD-HHMMSS>_R2X_jinteki_egov/ に置く（信頼できないデータ。中で何も実行しない）。
- 出力は scripts/results/R2X_jinteki_egov/：
  - <略称>_asof<日付>.txt    指定した条・号・別表（項・号の構造つき）と改正附則。先頭に law_revision_id・施行日・取得URL
  - <略称>_diff_<日付1>_vs_<日付2>.diff  版の間の差分（指定した条・号・別表の部分だけ）
  - scan.md / scan.json      本則の全文から「障害者」「特別障害者」「寡婦」「ひとり親」を含む行を拾ったもの
  - amend_nums.json          各版に収録された改正附則の AmendLawNum の一覧（令和7年・令和8年のもの）
  - fetch_log.json           取得の記録（URL・版・状態）
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。個人の情報は送らない。
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

# 版の選び方
# - 所得税：令和7年分＝2025-12-31、令和8年分＝2026-12-31（2026-12-01 施行の改正を含む）、令和9年分の参考＝2027-01-01
# - 住民税：令和8年度分＝2026-01-01、令和9年度分＝2027-01-01、令和10年度分の参考＝2028-01-01
#   （どの年度分に効くかは改正法の附則で決まる。既存 docs/public-sources/20261109_impl-prep_juminzei-hikazei-fuyo-shinkoku.md §0）
ASOF_SHOTOKU = ["2025-12-31", "2026-12-31", "2027-01-01"]
ASOF_CHIHO = ["2026-01-01", "2027-01-01", "2028-01-01"]

# (略称, 法令名, law_id（None なら /laws で引く）, [asof...], [条番号], 第2条第1項の号, 見出しの正規表現, 別表の題名の正規表現,
#  改正附則（AmendLawNum の正規表現。None なら改正附則を省いて取得）)
JOBS = [
    ("shotoku", "所得税法", "340AC0000000033", ASOF_SHOTOKU, ["79", "80", "81", "85"],
     ["28", "29", "30", "31", "33", "34"], None, None, r"^令和(七|八)年.*法律第(一三|十三|一二|十二)号$"),
    ("shotoku-rei", "所得税法施行令", "340CO0000000096", ASOF_SHOTOKU, ["10", "11", "11_2"], None,
     r"障害者|寡婦|ひとり親", None, r"^令和(七|八)年.*政令第(一二〇|九三)号$"),
    # 第1条の4 は第1条の3 と見出しを共有する（見出しの省略）ので条番号で指定する
    ("shotoku-ki", "所得税法施行規則", "340M50000040011", ASOF_SHOTOKU[:2], ["1_3", "1_4"], None,
     r"寡婦|ひとり親|事実上婚姻|障害者", None, None),
    ("chiho", "地方税法", "325AC0000000226", ASOF_CHIHO, ["292", "295", "314_2", "34"], None, None, None,
     r"^令和(七|八)年.*法律第(七|二)号$"),
    # 第48条の7 は市町村民税の特別障害者の範囲などを定める（見出しに「障害者」がない）
    ("chiho-rei", "地方税法施行令", "325CO0000000245", ASOF_CHIHO, ["46", "46_2", "46_2_2", "48_7"], None,
     r"障害者|寡婦|ひとり親", None, r"^令和(七|八)年.*政令第(一一九|八三)号$"),
    ("chiho-ki", "地方税法施行規則", "329M50000002023", ASOF_CHIHO[:2], ["1_9_7", "1_9_8"], None,
     r"寡婦|ひとり親|事実上婚姻|障害者", None, None),
    # 健保の被扶養者 180万円の「障害厚生年金の受給要件に該当する程度」
    # 第41条第2項・国民年金法第25条：障害を支給事由とする給付への公課の禁止（障害年金が合計所得金額に入るかの確認）
    ("kounen", "厚生年金保険法", None, [TODAY], ["41", "47"], None, None, None, None),
    ("kokunen", "国民年金法", "334AC0000000141", [TODAY], ["25", "30"], None, None, None, None),
    ("kounen-rei", "厚生年金保険法施行令", None, [TODAY], ["3_8"], None, None, r"^別表第一", None),
    ("kokunen-rei", "国民年金法施行令", "334CO0000000184", [TODAY], ["4_6"], None, None, r"^別表", None),
    # 所令10 が引用する手帳・認定の根拠
    ("seishin", "精神保健及び精神障害者福祉に関する法律", None, [TODAY], ["45"], None, None, None, None),
    ("seishin-rei", "精神保健及び精神障害者福祉に関する法律施行令", None, [TODAY], ["6"], None, None, None, None),
    ("shintai", "身体障害者福祉法", None, [TODAY], ["4", "15"], None, None, None, None),
    ("shintai-ki", "身体障害者福祉法施行規則", None, [TODAY], ["5"], None, None, r"^別表第五", None),
    ("senshobyo", "戦傷病者特別援護法", None, [TODAY], ["4"], None, None, None, None),
    ("genbaku", "原子爆弾被爆者に対する援護に関する法律", None, [TODAY], ["11"], None, None, None, None),
]

SCAN = {
    "shogaisha": r"障害者",
    "kafu": r"寡婦",
    "hitorioya": r"ひとり親",
}
SCAN_TARGETS = {"shotoku", "shotoku-rei", "shotoku-ki", "chiho", "chiho-rei", "chiho-ki"}

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
        cells = [" ".join(inline(c).split()) for c in ch if isinstance(c, dict)]
        lines.append("  " * depth + "| " + " | ".join(cells) + " |")
        return
    if tag in ("ArticleCaption", "ArticleTitle", "SupplProvisionLabel", "ChapterTitle", "SectionTitle",
               "AppdxTableTitle", "RelatedArticleNum"):
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


def fetch_full(law_id, asof, dl, omit_amend):
    q = {"response_format": "json", "asof": asof}
    if omit_amend:
        q["omit_amendment_suppl_provision"] = "true"
    url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode(q)
    st, body = get(url)
    (dl / f"{law_id}_{asof}.json").write_bytes(body)
    if st != 200:
        raise RuntimeError(f"{url} -> {st} {body[:200]!r}")
    return url, json.loads(body)


def collect_parts(root):
    arts, suppl, appdx = [], [], []

    def fn(n, path):
        t = n.get("tag")
        if t == "Article" and "SupplProvision" not in path:
            arts.append(n)
        elif t == "SupplProvision":
            suppl.append(n)
        elif t == "AppdxTable":
            appdx.append(n)
    walk(root, fn)
    return arts, suppl, appdx


def appdx_title(n):
    for c in n.get("children", []):
        if isinstance(c, dict) and c.get("tag") == "AppdxTableTitle":
            return inline(c)
    return ""


def art2_items(a, wanted):
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
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_jinteki_egov"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "R2X_jinteki_egov"
    out.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "fetches": [], "errors": []}
    scan, amend_list, texts = {}, {}, {}
    for short, title, law_id, asofs, arts, items2, cap_re, appdx_re, amend_re in JOBS:
        try:
            if law_id is None:
                law_id = find_law_id(title, dl)
                if not law_id:
                    log["errors"].append({"law": title, "error": "law_id not found"})
                    print(f"ERR {title} law_id not found", flush=True)
                    continue
            for asof in asofs:
                url, d = fetch_full(law_id, asof, dl, omit_amend=(amend_re is None))
                ri = d.get("revision_info") or {}
                log["fetches"].append({"short": short, "law": title, "law_id": law_id, "asof": asof, "url": url,
                                       "law_revision_id": ri.get("law_revision_id"),
                                       "amendment_law_title": ri.get("amendment_law_title"),
                                       "amendment_law_num": ri.get("amendment_law_num"),
                                       "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                                       "current_revision_status": ri.get("current_revision_status"),
                                       "updated": ri.get("updated")})
                root = d["law_full_text"]
                marts, suppl, appdx = collect_parts(root)
                by_num = {a["attr"].get("Num"): a for a in marts}
                header = [f"# {short} {title} {law_id} asof={asof}",
                          f"# law_revision_id={ri.get('law_revision_id')} 改正法令={ri.get('amendment_law_num')} "
                          f"施行日={ri.get('amendment_enforcement_date')} 状態={ri.get('current_revision_status')}",
                          f"# 取得URL={url}", f"# 取得日時={ts}", ""]
                lines = list(header)
                if items2 and "2" in by_num:
                    lines.append("## Num=2（第1項の指定した号だけ）")
                    lines += art2_items(by_num["2"], items2)
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
                    lines.append(f"## Num={num} {article_caption(a)}")
                    render(a, 0, lines)
                    lines.append("")
                if appdx_re:
                    for t in appdx:
                        tt = appdx_title(t)
                        if re.search(appdx_re, tt):
                            lines.append(f"## 別表 {tt}")
                            render(t, 0, lines)
                            lines.append("")
                body = "\n".join(lines[len(header):])
                texts[(short, asof)] = body
                if amend_re:
                    nums = sorted({s.get("attr", {}).get("AmendLawNum", "") for s in suppl})
                    amend_list[f"{short}@{asof}"] = [x for x in nums if x.startswith("令和七年") or x.startswith("令和八年")]
                    for an in nums:
                        if an and re.search(amend_re, an):
                            hits = [s for s in suppl if s.get("attr", {}).get("AmendLawNum") == an]
                            lines.append(f"## 改正附則 AmendLawNum={an}: {len(hits)} 件")
                            for s in hits:
                                render(s, 0, lines)
                            lines.append("")
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
                                    res.setdefault(key, []).append({"article": num, "caption": cap, "line": ln.strip()[:400]})
                    scan[f"{short}@{asof}"] = {"law_revision_id": ri.get("law_revision_id"),
                                               "counts": {k: len(v) for k, v in res.items()}, "hits": res}
                print(f"ok {short} {asof} {ri.get('law_revision_id')} {ri.get('current_revision_status')}", flush=True)
            for i in range(len(asofs) - 1):
                x, y = asofs[i], asofs[i + 1]
                if (short, x) in texts and (short, y) in texts:
                    diff = "\n".join(difflib.unified_diff(texts[(short, x)].splitlines(), texts[(short, y)].splitlines(),
                                                          f"{short}@{x}", f"{short}@{y}", lineterm=""))
                    (out / f"{short}_diff_{x}_vs_{y}.diff").write_text(diff + "\n", encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            log["errors"].append({"law": title, "error": repr(e)})
            print(f"ERR {title} {e!r}", flush=True)

    (out / "scan.json").write_text(json.dumps(scan, ensure_ascii=False, indent=1), encoding="utf-8")
    md = [f"# 本則の全文から「障害者」「寡婦」「ひとり親」を含む行（取得 {ts}）", ""]
    for k, v in scan.items():
        md += [f"## {k}（{v['law_revision_id']}）", "", "| 種類 | 件数 |", "|---|---|"]
        md += [f"| {kk} | {vv} |" for kk, vv in v["counts"].items()]
        md.append("")
        seen = set()
        for key in SCAN:
            for h in v["hits"].get(key, []):
                sig = (h["article"], h["line"])
                if sig in seen:
                    continue
                seen.add(sig)
                md.append(f"- 第{h['article']}条{h['caption']}：{h['line'][:200]}")
        md.append("")
    (out / "scan.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (out / "amend_nums.json").write_text(json.dumps(amend_list, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", out)


if __name__ == "__main__":
    main()

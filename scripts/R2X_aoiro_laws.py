"""R2X aoiro: 青色申告（承認・帳簿・特別控除・専従者給与・純損失・現金主義）に関係する条文を e-Gov 法令API v2 で取得する。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_aoiro_laws.py articles
      JOBS の条（本則）と別表、令和7年・令和8年の改正法令の附則のうちキーワードに当たる条を、各時点（asof）の版で取り出す。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_aoiro_laws.py revisions
      租税特別措置法の /law_revisions を取り、2027-01-01 施行の版（改正法令ごと）を law_revision_id で取得して第25条の2 を取り出す。
      （既存の調査 docs/public-sources/20261109_impl-prep_jigyo-laws-and-nta.md §10 の未確認点：令和7年法律第13号附則第31条と
       令和8年法律第12号による組替えの関係を確かめるため）

- API の使い方とテキスト化は scripts/IMPL_jigyo_laws.py（R1_egov_articles.py から写したもの）を写した。import はしない。
- ダウンロードした JSON は .work/downloads/<YYYYMMDD-HHMMSS>_R2X_aoiro_laws_<mode>/ に置く（信頼できないデータ。中でコードを実行しない）。
- 出力は scripts/results/R2X_aoiro_laws/。
  - <略称>_<asof>.txt  … 取り出した条（本則・別表・附則）。先頭に law_revision_id・改正法令・施行日・取得URL
  - diff_<略称>_<asof1>_vs_<asof2>.diff … 時点の間の差分
  - appdx_index_<略称>_<asof>.txt … 別表の題名と関係条（所得税法施行規則のみ）
  - fetch_log_<mode>.json … 取得した URL、版、SHA-256
  - sochi_25_2_by_revision.txt / revisions_sochi.json … revisions モードの出力
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。個人の情報は送らない。
"""
import difflib
import hashlib
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
OUT = ROOT / "scripts" / "results" / "R2X_aoiro_laws"

# 時点：令和7年分の年末（2025-12-31）、令和8年分の年末（2026-12-31。2026-11-09 時点では未施行の改正を含む）、
#       令和9年分の初日（2027-01-01）
ASOFS = ["2025-12-31", "2026-12-31", "2027-01-01"]

# 附則を拾う改正法令（AmendLawNum の先頭が次のどれかに当たるもの）とキーワード
SUPPL_PREFIX = ("令和七年", "令和八年")
SUPPL_KW = (r"青色|第五十七条|第六十七条|第七十条|第百四十条|第百四十一条|第百四十二条|第百四十三条|第百四十四条|第百四十五条|"
            r"第百四十七条|第百四十八条|第百四十九条|第百五十条|第百五十一条|第二十五条の二|第九条の六|純損失|専従者|"
            r"第五十六条|第五十七条|第五十八条|第六十一条|第六十三条|第六十四条|第六十五条")

# (略称, 法令名, law_id, [本則の条番号（Num 属性。枝番は "70_2"）], 別表を拾うか)
JOBS = [
    ("shotoku", "所得税法", "340AC0000000033",
     ["2", "57", "67", "69", "70", "70_2", "123", "140", "141", "142", "143", "144", "145", "146", "147", "148", "149", "150",
      "151", "155", "232"], False),
    ("shotoku-rei", "所得税法施行令", "340CO0000000096",
     ["164", "165", "166", "167", "195", "196", "197", "198", "201", "271", "272"], False),
    ("shotoku-ki", "所得税法施行規則", "340M50000040011",
     ["36_4", "39_2", "40", "40_2", "48", "54", "55", "56", "57", "58", "59", "60", "61", "62", "63", "64", "65", "66"], True),
    ("sochi", "租税特別措置法", "332AC0000000026", ["25_2"], False),
    ("sochi-ki", "租税特別措置法施行規則", "332M50000040015", ["9_6"], False),
    ("denchou", "電子計算機を使用して作成する国税関係帳簿書類の保存方法等の特例に関する法律", "410AC0000000025", ["2", "4", "8"], False),
    ("denchou-ki", "電子計算機を使用して作成する国税関係帳簿書類の保存方法等の特例に関する法律施行規則", "410M50000040043",
     ["2", "5"], False),
]

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


# ---- 本文のテキスト化（scripts/IMPL_jigyo_laws.py の render を写したもの） ----
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
    if tag in ("ArticleCaption", "ArticleTitle", "SupplProvisionLabel", "ChapterTitle", "SectionTitle", "AppdxTableTitle",
               "RelatedArticleNum"):
        lines.append("  " * depth + inline(n))
        return
    for c in ch:
        render(c, depth, lines)


def walk(n, fn, path=()):
    if isinstance(n, dict):
        fn(n, path)
        for c in n.get("children", []):
            walk(c, fn, path + (n.get("tag"),))


def split(root):
    main_arts, suppl, appdx = [], [], []

    def collect(n, path):
        if n.get("tag") == "Article" and "SupplProvision" not in path:
            main_arts.append(n)
        if n.get("tag") == "SupplProvision":
            suppl.append(n)
        if n.get("tag") == "AppdxTable":
            appdx.append(n)
    walk(root, collect)
    return main_arts, suppl, appdx


def child_text(n, tag):
    for c in n.get("children", []):
        if isinstance(c, dict) and c.get("tag") == tag:
            return inline(c)
    return ""


def fetch_json(url, dl, fname):
    st, body = get(url)
    (dl / fname).write_bytes(body)
    if st != 200:
        raise RuntimeError(f"{url} -> {st} {body[:200]!r}")
    return json.loads(body), hashlib.sha256(body).hexdigest()


def rev_info(d):
    ri = d.get("revision_info") or {}
    return {k: ri.get(k) for k in ("law_revision_id", "law_title", "amendment_law_num", "amendment_law_title",
                                   "amendment_enforcement_date", "amendment_promulgate_date", "current_revision_status", "updated")}


def extract(d, nums, with_appdx):
    main_arts, suppl, appdx = split(d["law_full_text"])
    by_num = {a["attr"].get("Num"): a for a in main_arts}
    body = []
    for num in nums:
        a = by_num.get(num)
        body.append(f"## Num={num}")
        if a is None:
            body += ["（この時点の本則にない）", ""]
            continue
        render(a, 0, body)
        body.append("")
    appdx_index = []
    if with_appdx:
        for t in appdx:
            title = child_text(t, "AppdxTableTitle")
            rel = child_text(t, "RelatedArticleNum")
            appdx_index.append(f"{t.get('attr', {}).get('Num', '')}\t{title}\t{rel}")
            if re.search(r"第(五十[六七八九]|六十[一二三四五六]?)条", rel):
                body.append(f"## 別表 {title} {rel}")
                render(t, 0, body)
                body.append("")
    for s in suppl:
        an = s.get("attr", {}).get("AmendLawNum", "") or ""
        if not an.startswith(SUPPL_PREFIX):
            continue
        sa = []
        walk(s, lambda n, p: sa.append(n) if n.get("tag") == "Article" else None)
        hits = []
        for a in sa:
            t = []
            render(a, 0, t)
            if re.search(SUPPL_KW, "\n".join(t)):
                hits.append((a["attr"].get("Num"), t))
        if hits:
            body.append(f"## 附則 AmendLawNum={an}（条の本文が附則のキーワードに当たる条だけ）")
            for num, t in hits:
                body.append(f"### 附則 Num={num}")
                body.extend(t)
                body.append("")
    return body, appdx_index


def mode_articles(dl, log):
    for short, title, law_id, nums, with_appdx in JOBS:
        texts = {}
        for asof in ASOFS:
            url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
            try:
                d, sha = fetch_json(url, dl, f"{short}_{asof}.json")
            except Exception as e:  # noqa
                log["errors"].append({"short": short, "asof": asof, "error": repr(e)})
                print("ERR", short, asof, repr(e), flush=True)
                continue
            ri = rev_info(d)
            li = d.get("law_info") or {}
            body, appdx_index = extract(d, nums, with_appdx)
            header = [f"# {short} {title} law_id={law_id} 法令番号={li.get('law_num')} asof={asof}",
                      f"# law_revision_id={ri['law_revision_id']} 改正法令={ri['amendment_law_num']}（{ri['amendment_law_title']}） "
                      f"施行日={ri['amendment_enforcement_date']} 状態={ri['current_revision_status']} updated={ri['updated']}",
                      f"# 取得URL={url}", f"# 取得日時={log['run_at']} sha256={sha}", ""]
            texts[asof] = body
            (OUT / f"{short}_{asof}.txt").write_text("\n".join(header + body) + "\n", encoding="utf-8")
            if with_appdx:
                (OUT / f"appdx_index_{short}_{asof}.txt").write_text("\n".join(appdx_index) + "\n", encoding="utf-8")
            log["fetches"].append({"short": short, "law_id": law_id, "law_num": li.get("law_num"), "asof": asof, "url": url,
                                   "sha256": sha, **ri})
            print("ok", short, asof, ri["law_revision_id"], flush=True)
        keys = [a for a in ASOFS if a in texts]
        for x, y in zip(keys, keys[1:]):
            diff = "\n".join(difflib.unified_diff(texts[x], texts[y], f"{short}@{x}", f"{short}@{y}", lineterm=""))
            (OUT / f"diff_{short}_{x}_vs_{y}.diff").write_text(diff + "\n", encoding="utf-8")
            log.setdefault("diff_line_counts", {})[f"{short}_{x}_vs_{y}"] = len(diff.splitlines())


def mode_revisions(dl, log):
    law_id = "332AC0000000026"
    url = f"{API}/law_revisions/{law_id}?" + urllib.parse.urlencode({"response_format": "json"})
    d, sha = fetch_json(url, dl, "revisions_sochi.json")
    revs = [{k: r.get(k) for k in ("law_revision_id", "amendment_promulgate_date", "amendment_enforcement_date",
                                   "amendment_scheduled_enforcement_date", "amendment_law_title", "amendment_law_num",
                                   "current_revision_status", "updated")} for r in d.get("revisions", [])]
    (OUT / "revisions_sochi.json").write_text(json.dumps({"url": url, "sha256": sha, "revisions": revs}, ensure_ascii=False, indent=1),
                                              encoding="utf-8")
    log["fetches"].append({"url": url, "sha256": sha, "count": len(revs)})
    pick = [r for r in revs if (r.get("amendment_enforcement_date") or "") >= "2025-12-31"
            and (r.get("amendment_enforcement_date") or "") <= "2027-01-01"]
    out = []
    for r in pick:
        rid = r["law_revision_id"]
        u = f"{API}/law_data/{rid}?" + urllib.parse.urlencode({"response_format": "json"})
        try:
            dd, sh = fetch_json(u, dl, f"sochi_{rid}.json")
        except Exception as e:  # noqa
            log["errors"].append({"rev": rid, "error": repr(e)})
            print("ERR", rid, repr(e), flush=True)
            continue
        ri = rev_info(dd)
        body, _ = extract(dd, ["25_2"], False)
        out.append(f"# law_revision_id={rid} 改正法令={r.get('amendment_law_num')}（{r.get('amendment_law_title')}） "
                   f"施行日={r.get('amendment_enforcement_date')} 状態={r.get('current_revision_status')}")
        out.append(f"# 取得URL={u} sha256={sh} 応答の law_revision_id={ri['law_revision_id']}")
        out.extend(body)
        out.append("")
        log["fetches"].append({"url": u, "sha256": sh, **ri})
        print("ok rev", rid, flush=True)
    (OUT / "sochi_25_2_by_revision.txt").write_text("\n".join(out) + "\n", encoding="utf-8")


def mode_suppl(dl, log):
    """所得税法施行規則の第36条の4（青色専従者給与の届出書の記載事項）・第55条（青色申告承認申請書の記載事項）・
    第66条（取りやめの届出書の記載事項）の文言が 2025-12-31 → 2026-12-31 → 2027-01-01 で変わる（articles モードの diff）。
    どの改正省令で、いつから適用されるかを確かめるため、/law_revisions の版の一覧と、今日（2026-11-09）・2027-01-01 の版の
    本則の3条と、令和5年〜令和8年の改正省令の附則のうち第三十六条の四・第五十五条・第六十六条に触れる条の全文を書き出す。"""
    law_id = "340M50000040011"
    url = f"{API}/law_revisions/{law_id}?" + urllib.parse.urlencode({"response_format": "json"})
    d, sha = fetch_json(url, dl, "revisions_shotoku-ki.json")
    revs = [{k: r.get(k) for k in ("law_revision_id", "amendment_promulgate_date", "amendment_enforcement_date",
                                   "amendment_law_title", "amendment_law_num", "current_revision_status")}
            for r in d.get("revisions", []) if "2025-06-01" <= (r.get("amendment_enforcement_date") or "") <= "2027-12-31"]
    log["fetches"].append({"url": url, "sha256": sha, "picked": len(revs)})
    out = [f"# /law_revisions {url} sha256={sha}（施行日 2025-06-01〜2027-12-31 の版）"]
    out += [f"#   {r['law_revision_id']} 施行={r['amendment_enforcement_date']} 公布={r['amendment_promulgate_date']} "
            f"{r['amendment_law_num']}（{r['amendment_law_title']}） {r['current_revision_status']}" for r in revs]
    out.append("")
    kw = r"第三十六条の四|第五十五条|第六十六条"
    for asof in ("2026-11-09", "2027-01-01"):
        u = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
        dd, sh = fetch_json(u, dl, f"shotoku-ki_{asof}.json")
        ri = rev_info(dd)
        log["fetches"].append({"url": u, "sha256": sh, **ri})
        out.append(f"## asof={asof} law_revision_id={ri['law_revision_id']} 改正法令={ri['amendment_law_num']} 施行日={ri['amendment_enforcement_date']} "
                   f"状態={ri['current_revision_status']} 取得URL={u} sha256={sh}")
        main_arts, suppl, _ = split(dd["law_full_text"])
        by_num = {a["attr"].get("Num"): a for a in main_arts}
        for num in ("36_4", "55", "66"):
            out.append(f"### 本則 Num={num}")
            if num in by_num:
                render(by_num[num], 0, out)
            out.append("")
        for s in suppl:
            an = s.get("attr", {}).get("AmendLawNum", "") or ""
            if not an.startswith(("令和五年", "令和六年", "令和七年", "令和八年")):
                continue
            sa = []
            walk(s, lambda n, p: sa.append(n) if n.get("tag") == "Article" else None)
            for a in sa:
                t = []
                render(a, 0, t)
                if re.search(kw, "\n".join(t)):
                    out.append(f"### 附則 AmendLawNum={an} Num={a['attr'].get('Num')}")
                    out.extend(t)
                    out.append("")
        print("ok suppl", asof, ri["law_revision_id"], flush=True)
    (OUT / "shotoku-ki_suppl_36_4_55_66.txt").write_text("\n".join(out) + "\n", encoding="utf-8")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "articles"
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_aoiro_laws_{mode}"
    dl.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "mode": mode, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "fetches": [], "errors": []}
    if mode == "articles":
        mode_articles(dl, log)
    elif mode == "revisions":
        mode_revisions(dl, log)
    elif mode == "suppl":
        mode_suppl(dl, log)
    else:
        raise SystemExit("mode は articles・revisions・suppl のどれか")
    (OUT / f"fetch_log_{mode}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", OUT)


if __name__ == "__main__":
    main()

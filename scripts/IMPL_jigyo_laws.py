"""IMPL jigyo: 事業所得・業務に係る雑所得の計算（家事関連費・特例・帳簿）に関係する条文を e-Gov 法令API v2 で取得する。

実行（Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_jigyo_laws.py index
      対象法令の law_id を /laws で引き、本則の「条番号と見出し」の索引を作る（asof=TODAY）。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_jigyo_laws.py articles
      JOBS の条を、指定した各時点（asof）の版で取り出してテキストにし、時点の間の差分をとる。

- API の使い方は scripts/R1_egov_articles.py と scripts/R4_fetch_laws.py を写した（import はしない）。
- ダウンロードした JSON は .work/downloads/<ts>_IMPL_jigyo_laws_<mode>/ に置く（信頼できないデータ。中でコードを実行しない）。
- 結果は scripts/results/IMPL_jigyo_laws/ に書く。
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
TODAY = "2026-11-09"
SLEEP = 1.5
OUT = ROOT / "scripts" / "results" / "IMPL_jigyo_laws"

# 略称 -> 法令名（/laws の law_title で完全一致を探す）
TITLES = {
    "shotoku": "所得税法",
    "shotoku-rei": "所得税法施行令",
    "shotoku-ki": "所得税法施行規則",
    "sochi": "租税特別措置法",
    "sochi-rei": "租税特別措置法施行令",
    "sochi-ki": "租税特別措置法施行規則",
}

# 版：令和7年分の年末（2025-12-31）、令和8年分の年末（2026-12-31）、令和9年分の初日（2027-01-01）、
# e-Gov に登録されている未施行の改正の最後の施行日より後（2030-12-31。この時点で登録済みの改正をすべて反映した版）
ASOF_MAIN = ["2025-12-31", "2026-12-31", "2027-01-01", "2030-12-31"]

# (略称, [asof...], [本則の条番号（Num 属性）], 見出しで追加で拾う正規表現, [(附則の AmendLawNum, 附則の条を拾うキーワードの正規表現)])
AMEND_R7 = "令和七年三月三一日法律第一三号"
AMEND_R8 = "令和八年三月三一日法律第一二号"
JOBS = [
    ("shotoku", ASOF_MAIN,
     ["22", "26", "27", "34", "35", "36", "37", "45", "56", "57", "63", "65", "66", "67", "69", "120", "143", "144", "145", "146",
      "147", "148", "149", "150", "151", "232", "233"],
     None,
     [(AMEND_R7, r"第三十五条|第六十七条|第百二十条|第二百三十二条|第四十五条"),
      (AMEND_R8, r"第三十五条|第六十七条|第百二十条|第二百三十二条|第四十五条|第三十七条")]),
    ("shotoku-rei", ["2025-12-31", "2026-12-31", "2030-12-31"],
     ["96", "195", "196", "196_2", "196_3", "197"],
     None,
     []),
    ("shotoku-ki", ["2025-12-31", "2026-12-31", "2030-12-31"],
     ["39_2", "40", "40_2", "47", "47_2", "47_3", "55", "56", "57", "58", "63", "64", "65", "102", "103"],
     None,
     []),
    ("sochi", ASOF_MAIN,
     ["25_2", "27"],
     None,
     [(AMEND_R7, r"第二十五条の二|第二十七条|家内労働者|青色申告特別控除"),
      (AMEND_R8, r"第二十五条の二|第二十七条|家内労働者|青色申告特別控除")]),
    ("sochi-rei", ["2025-12-31", "2026-12-31", "2030-12-31"],
     [],
     r"家内労働者|青色申告特別控除",
     []),
    ("sochi-ki", ["2025-12-31", "2026-12-31", "2030-12-31"],
     [],
     r"家内労働者|青色申告特別控除",
     []),
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


# ---- 本文のテキスト化（R1_egov_articles.py の render を写したもの） ----
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


def split_articles(root):
    main_arts, suppl = [], []

    def collect(n, path):
        if n.get("tag") == "Article" and "SupplProvision" not in path:
            main_arts.append(n)
        if n.get("tag") == "SupplProvision":
            suppl.append(n)
    walk(root, collect)
    return main_arts, suppl


def find_law_id(title, dl, idx):
    q = urllib.parse.urlencode({"law_title": title, "response_format": "json", "asof": TODAY})
    url = f"{API}/laws?{q}"
    st, body = get(url)
    (dl / f"{idx:02d}_laws_{title}.json").write_bytes(body)
    data = json.loads(body)
    for law in data.get("laws", []):
        rv = law.get("current_revision_info") or law.get("revision_info") or {}
        if rv.get("law_title") == title:
            return law["law_info"]["law_id"], law["law_info"].get("law_num"), url
    return None, None, url


def fetch_full(law_id, asof, dl):
    q = {"response_format": "json", "asof": asof}
    url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode(q)
    st, body = get(url)
    (dl / f"{law_id}_{asof}.json").write_bytes(body)
    if st != 200:
        raise RuntimeError(f"{url} -> {st} {body[:200]!r}")
    return url, json.loads(body)


def rev_info(d):
    ri = d.get("revision_info") or {}
    return {k: ri.get(k) for k in ("law_revision_id", "amendment_law_num", "amendment_law_title", "amendment_enforcement_date",
                                   "amendment_promulgate_date", "current_revision_status", "updated")}


def mode_index(dl, log):
    ids = {}
    for i, (short, title) in enumerate(TITLES.items(), 1):
        law_id, law_num, url = find_law_id(title, dl, i)
        ids[short] = {"title": title, "law_id": law_id, "law_num": law_num, "lookup_url": url}
        if not law_id:
            log["errors"].append({"short": short, "error": "law_id not found"})
            continue
        furl, d = fetch_full(law_id, TODAY, dl)
        ri = rev_info(d)
        main_arts, suppl = split_articles(d["law_full_text"])
        lines = [f"# {short} {title} {law_id} asof={TODAY}", f"# {json.dumps(ri, ensure_ascii=False)}", f"# 取得URL={furl}", ""]
        lines += [f"{a['attr'].get('Num')}\t{article_caption(a)}" for a in main_arts]
        (OUT / f"index_{short}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        log["fetches"].append({"short": short, "law_id": law_id, "asof": TODAY, "url": furl, **ri, "articles": len(main_arts)})
        print("ok index", short, law_id, len(main_arts), flush=True)
    (OUT / "law_ids.json").write_text(json.dumps(ids, ensure_ascii=False, indent=1), encoding="utf-8")


def mode_articles(dl, log):
    ids = json.loads((OUT / "law_ids.json").read_text(encoding="utf-8"))
    for short, asofs, nums, cap_re, amends in JOBS:
        law_id = ids[short]["law_id"]
        texts = {}
        for asof in asofs:
            url, d = fetch_full(law_id, asof, dl)
            ri = rev_info(d)
            main_arts, suppl = split_articles(d["law_full_text"])
            by_num = {a["attr"].get("Num"): a for a in main_arts}
            sel = list(nums)
            if cap_re:
                for a in main_arts:
                    n = a["attr"].get("Num")
                    if n not in sel and re.search(cap_re, article_caption(a)):
                        sel.append(n)
            header = [f"# {short} {ids[short]['title']} {law_id} asof={asof}",
                      f"# law_revision_id={ri['law_revision_id']} 改正法令={ri['amendment_law_num']} 施行日={ri['amendment_enforcement_date']} 状態={ri['current_revision_status']} updated={ri['updated']}",
                      f"# 取得URL={url}", f"# 取得日時={log['run_at']}", ""]
            body = []
            for num in sel:
                a = by_num.get(num)
                body.append(f"## Num={num}")
                if a is None:
                    body += ["（この時点の本則にない）", ""]
                    continue
                render(a, 0, body)
                body.append("")
            for an, kw in amends:
                hits = [s for s in suppl if s.get("attr", {}).get("AmendLawNum") == an]
                body.append(f"## 附則 AmendLawNum={an}（{len(hits)} 件の附則のうち、条の本文が /{kw}/ に当たる条だけ）")
                for s in hits:
                    sa = []
                    walk(s, lambda n, p: sa.append(n) if n.get("tag") == "Article" else None)
                    for a in sa:
                        t = []
                        render(a, 0, t)
                        txt = "\n".join(t)
                        if re.search(kw, txt):
                            body.append(f"### 附則 Num={a['attr'].get('Num')}")
                            body.extend(t)
                            body.append("")
                body.append("")
            texts[asof] = body
            (OUT / f"{short}_{asof}.txt").write_text("\n".join(header + body) + "\n", encoding="utf-8")
            log["fetches"].append({"short": short, "law_id": law_id, "asof": asof, "url": url, **ri, "selected": sel})
            print("ok", short, asof, ri["law_revision_id"], len(sel), flush=True)
        for x, y in zip(asofs, asofs[1:]):
            diff = "\n".join(difflib.unified_diff(texts[x], texts[y], f"{short}@{x}", f"{short}@{y}", lineterm=""))
            (OUT / f"diff_{short}_{x}_vs_{y}.diff").write_text(diff + "\n", encoding="utf-8")
            log.setdefault("diff_line_counts", {})[f"{short}_{x}_vs_{y}"] = len(diff.splitlines())


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "articles"
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL_jigyo_laws_{mode}"
    dl.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "mode": mode, "download_dir": str(dl.relative_to(ROOT)), "fetches": [], "errors": []}
    if mode == "index":
        mode_index(dl, log)
    elif mode == "articles":
        mode_articles(dl, log)
    else:
        raise SystemExit("mode は index か articles")
    (OUT / f"fetch_log_{mode}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", OUT)


if __name__ == "__main__":
    main()

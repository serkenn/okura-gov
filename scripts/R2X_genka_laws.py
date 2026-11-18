"""R2X genka: 減価償却と損益通算に関係する条文・別表を e-Gov 法令API v2 で取得する。

実行（Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_genka_laws.py index
      対象法令の law_id を /laws で引き（law_ids.json）、本則の「条番号と見出し」の索引を作る（asof=TODAY）。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_genka_laws.py revisions
      /law_revisions/<law_id> で改正履歴を取り、2025-01-01〜2028-12-31 に施行日があるものを表にする。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_genka_laws.py articles
      JOBS の条（と附則）を、各時点（asof）の版で取り出してテキストにし、時点の間の差分をとる。
      `articles shotoku-rei` のように略称を続けると、その法令だけを取り直す。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_genka_laws.py taiyo
      減価償却資産の耐用年数等に関する省令の本則と別表を、各時点の版で取り出す。別表は rowspan を下へ埋めた
      「行ごとの全セル」の形（JSON とテキスト）にする。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_genka_laws.py probe
      版の間で変わった箇所（所令198）がどの改正で入ったかを改正ごとの版（law_revision_id）で調べ、
      関係する改正の附則（施行期日・経過措置）を取り出す（probe.txt）。

- API の使い方は scripts/IMPL_jigyo_laws.py（本文のテキスト化）と scripts/IMPL_kyuyo_fetch.py（別表の格子）を写した（import はしない）。
- ダウンロードした JSON は .work/downloads/<ts>_R2X_genka_laws_<mode>/ に置く（信頼できないデータ。中でコードを実行しない）。
- 結果は scripts/results/R2X_genka_laws/ に書く。
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
TODAY = "2026-11-09"
SLEEP = 1.5
OUT = ROOT / "scripts" / "results" / "R2X_genka_laws"

TITLES = {
    "shotoku": "所得税法",
    "shotoku-rei": "所得税法施行令",
    "shotoku-ki": "所得税法施行規則",
    "sochi": "租税特別措置法",
    "sochi-rei": "租税特別措置法施行令",
    "sochi-ki": "租税特別措置法施行規則",
    "taiyo": "減価償却資産の耐用年数等に関する省令",
    "chiho": "地方税法",
}

# 令和7年分の年末、令和8年分の年末、令和9年分の初日、登録済みの未施行の改正をすべて反映した版
ASOF_MAIN = ["2025-12-31", "2026-12-31", "2027-01-01", "2030-12-31"]
# 措法28の2 は適用期限（令和8年3月31日）の前後で版を見る
ASOF_SOCHI = ["2025-12-31", "2026-03-31", "2026-04-01", "2026-12-31", "2027-01-01", "2030-12-31"]

AMEND_R7 = "令和七年三月三一日法律第一三号"
AMEND_R8 = "令和八年三月三一日法律第一二号"


def rng(lo, hi):
    """所令などの条番号（Num 属性 '120', '120_2' など）で、整数部が lo 以上 hi 以下のものを選ぶための述語。"""
    def f(num):
        m = re.match(r"(\d+)", num or "")
        return bool(m) and lo <= int(m.group(1)) <= hi
    return f


# (略称, [asof...], [本則の条番号], 本則の条番号の述語 or None, 見出しで追加で拾う正規表現 or None,
#  [(附則の AmendLawNum or None(全附則), 附則の条を拾うキーワードの正規表現)])
JOBS = [
    ("shotoku", ASOF_MAIN,
     ["2", "22", "26", "27", "33", "35", "37", "38", "45", "49", "50", "51", "62", "63", "69", "70", "70_2", "71", "123", "140", "141", "142"],
     None, None,
     [(AMEND_R7, r"第四十九条|第五十一条|第六十九条|第七十条|減価償却|純損失"),
      (AMEND_R8, r"第四十九条|第五十一条|第六十九条|第七十条|減価償却|純損失")]),
    ("shotoku-rei", ["2025-12-31", "2026-12-31", "2030-12-31"],
     ["6", "7_2", "81", "85", "96", "140", "141", "142", "143", "198", "199", "200", "201", "202", "203", "204"],
     rng(120, 139), None,
     []),
    ("shotoku-ki", ["2025-12-31", "2026-12-31", "2030-12-31"],
     [],
     None, r"減価償却|償却|耐用年数|損益通算|純損失|一括償却|少額|資産損失",
     []),
    ("sochi", ASOF_SOCHI,
     ["10", "28_2"],
     None, r"少額減価償却資産",
     [(None, r"第二十八条の二|少額減価償却資産")]),
    ("sochi-rei", ["2025-12-31", "2026-03-31", "2026-04-01", "2026-12-31", "2030-12-31"],
     ["5_3", "18_5"],
     None, r"少額減価償却資産",
     [(None, r"第十八条の五|少額減価償却資産")]),
    ("sochi-ki", ["2025-12-31", "2026-04-01", "2026-12-31", "2030-12-31"],
     [],
     None, r"少額減価償却資産",
     []),
    ("chiho", ["2025-12-31", "2026-12-31"],
     ["313"],
     None, None,
     []),
]

ASOF_TAIYO = ["2025-12-31", "2026-12-31", "2030-12-31"]

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


# ---- 本文のテキスト化（IMPL_jigyo_laws.py の render を写したもの） ----
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
    if tag in ("TableRow", "TableHeaderRow"):
        cells = [inline(c).replace("\n", " ") for c in ch if isinstance(c, dict)]
        lines.append("  " * depth + "| " + " | ".join(cells) + " |")
        return
    if tag in ("ArticleCaption", "ArticleTitle", "SupplProvisionLabel", "ChapterTitle", "SectionTitle", "AppdxTableTitle"):
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
    main_arts, suppl, appdx = [], [], []

    def collect(n, path):
        if n.get("tag") == "Article" and "SupplProvision" not in path:
            main_arts.append(n)
        if n.get("tag") == "SupplProvision":
            suppl.append(n)
        if n.get("tag") == "AppdxTable" and "SupplProvision" not in path:
            appdx.append(n)
    walk(root, collect)
    return main_arts, suppl, appdx


def find_law_id(title, dl, idx):
    q = urllib.parse.urlencode({"law_title": title, "response_format": "json", "asof": TODAY})
    url = f"{API}/laws?{q}"
    st, body = get(url)
    (dl / f"{idx:02d}_laws.json").write_bytes(body)
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


# ---- 別表の格子（IMPL_kyuyo_fetch.py の appdx_grid を写し、rowspan を下へ埋める処理を足した） ----
def appdx_grid(appdx):
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
                                    cells.append({"text": inline(col).replace("\n", " ").strip(),
                                                  "rowspan": int(a.get("rowspan", 1)), "colspan": int(a.get("colspan", 1))})
                            st["rows"].append(cells)
                elif x.get("tag") == "Remarks":
                    st["remarks"].append(inline(x))
            out["structs"].append(st)
        elif t == "Remarks":
            out["remarks"].append(inline(c))
    return out


def fill_grid(rows):
    """rowspan / colspan を展開して、各行を同じ列数のテキストの list にする（HTML の表の配置規則と同じ）。"""
    occupied = {}  # (r, c) -> text
    out = []
    for r, cells in enumerate(rows):
        c = 0
        for cell in cells:
            while (r, c) in occupied:
                c += 1
            for dr in range(cell["rowspan"]):
                for dc in range(cell["colspan"]):
                    occupied[(r + dr, c + dc)] = cell["text"]
            c += cell["colspan"]
    nrows = len(rows)
    ncols = max((c for (_, c) in occupied), default=-1) + 1
    for r in range(nrows):
        out.append([occupied.get((r, c), "") for c in range(ncols)])
    return out


def mode_index(dl, log):
    ids = {}
    for i, (short, title) in enumerate(TITLES.items(), 1):
        law_id, law_num, url = find_law_id(title, dl, i)
        ids[short] = {"title": title, "law_id": law_id, "law_num": law_num, "lookup_url": url}
        if not law_id:
            log["errors"].append({"short": short, "error": "law_id not found"})
            print("NG index", short, flush=True)
            continue
        if short in ("chiho",):  # 地方税法は大きいので索引を作らない
            print("ok id", short, law_id, flush=True)
            continue
        furl, d = fetch_full(law_id, TODAY, dl)
        ri = rev_info(d)
        main_arts, suppl, appdx = split_articles(d["law_full_text"])
        lines = [f"# {short} {title} {law_id} asof={TODAY}", f"# {json.dumps(ri, ensure_ascii=False)}", f"# 取得URL={furl}", ""]
        lines += [f"{a['attr'].get('Num')}\t{article_caption(a)}" for a in main_arts]
        lines += [f"別表\t{inline(next((c for c in t.get('children', []) if isinstance(c, dict) and c.get('tag') == 'AppdxTableTitle'), ''))}" for t in appdx]
        (OUT / f"index_{short}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        log["fetches"].append({"short": short, "law_id": law_id, "asof": TODAY, "url": furl, **ri, "articles": len(main_arts), "appdx_tables": len(appdx)})
        print("ok index", short, law_id, len(main_arts), len(appdx), flush=True)
    (OUT / "law_ids.json").write_text(json.dumps(ids, ensure_ascii=False, indent=1), encoding="utf-8")


def mode_revisions(dl, log):
    ids = json.loads((OUT / "law_ids.json").read_text(encoding="utf-8"))
    rows = ["| 略称 | law_revision_id | 施行日 | 改正法令 | 改正法令名 | 状態 | updated |", "|---|---|---|---|---|---|---|"]
    for short in ("shotoku", "shotoku-rei", "shotoku-ki", "sochi", "sochi-rei", "sochi-ki", "taiyo"):
        law_id = ids[short]["law_id"]
        url = f"{API}/law_revisions/{law_id}?response_format=json"
        st, body = get(url)
        (dl / f"revisions_{law_id}.json").write_bytes(body)
        if st != 200:
            log["errors"].append({"short": short, "url": url, "status": st})
            continue
        data = json.loads(body)
        revs = data.get("revisions", [])
        n = 0
        for rv in revs:
            ed = rv.get("amendment_enforcement_date") or ""
            if "2025-01-01" <= ed <= "2028-12-31":
                rows.append(f"| {short} | {rv.get('law_revision_id')} | {ed} | {rv.get('amendment_law_num')} | {rv.get('amendment_law_title')} | {rv.get('current_revision_status')} | {rv.get('updated')} |")
                n += 1
        log["fetches"].append({"short": short, "url": url, "status": st, "revisions_total": len(revs), "revisions_2025_2028": n})
        print("ok revisions", short, len(revs), n, flush=True)
    (OUT / "revisions_2025_2028.md").write_text("\n".join(rows) + "\n", encoding="utf-8")


def mode_articles(dl, log, only=None):
    ids = json.loads((OUT / "law_ids.json").read_text(encoding="utf-8"))
    for short, asofs, nums, pred, cap_re, amends in JOBS:
        if only and short not in only:
            continue
        law_id = ids[short]["law_id"]
        texts = {}
        for asof in asofs:
            url, d = fetch_full(law_id, asof, dl)
            ri = rev_info(d)
            main_arts, suppl, _ = split_articles(d["law_full_text"])
            sel = []
            for a in main_arts:
                n = a["attr"].get("Num")
                if n in nums or (pred and pred(n)) or (cap_re and re.search(cap_re, article_caption(a))):
                    if n not in sel:
                        sel.append(n)
            for n in nums:
                if n not in sel:
                    sel.append(n)
            by_num = {a["attr"].get("Num"): a for a in main_arts}
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
                hits = [s for s in suppl if an is None or s.get("attr", {}).get("AmendLawNum") == an]
                body.append(f"## 附則 AmendLawNum={an or '(すべて)'}（{len(hits)} 件の附則のうち、条の本文が /{kw}/ に当たる条だけ）")
                for s in hits:
                    sa = []
                    walk(s, lambda n, p: sa.append(n) if n.get("tag") == "Article" else None)
                    for a in sa:
                        t = []
                        render(a, 0, t)
                        txt = "\n".join(t)
                        if re.search(kw, txt):
                            body.append(f"### 附則 AmendLawNum={s.get('attr', {}).get('AmendLawNum', '(原始附則)')} Num={a['attr'].get('Num')}")
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


def mode_taiyo(dl, log):
    ids = json.loads((OUT / "law_ids.json").read_text(encoding="utf-8"))
    law_id = ids["taiyo"]["law_id"]
    texts = {}
    for asof in ASOF_TAIYO:
        url, d = fetch_full(law_id, asof, dl)
        ri = rev_info(d)
        main_arts, suppl, appdx = split_articles(d["law_full_text"])
        header = [f"# taiyo {ids['taiyo']['title']} {law_id} asof={asof}",
                  f"# law_revision_id={ri['law_revision_id']} 改正法令={ri['amendment_law_num']} 施行日={ri['amendment_enforcement_date']} 状態={ri['current_revision_status']} updated={ri['updated']}",
                  f"# 取得URL={url}", f"# 取得日時={log['run_at']}", ""]
        body = []
        for a in main_arts:
            body.append(f"## Num={a['attr'].get('Num')}")
            render(a, 0, body)
            body.append("")
        tables = []
        for t in appdx:
            g = appdx_grid(t)
            filled = []
            for st in g["structs"]:
                filled.append({"title": st["title"], "rows": fill_grid(st["rows"]), "remarks": st["remarks"]})
            tables.append({"title": g["title"], "related_article_num": g["related_article_num"], "structs": filled, "remarks": g["remarks"]})
            body.append(f"## 別表 {g['title']} {g['related_article_num']}")
            for st in filled:
                for row in st["rows"]:
                    body.append("| " + " | ".join(row) + " |")
                for rm in st["remarks"]:
                    body.append("備考：" + rm)
            for rm in g["remarks"]:
                body.append("備考：" + rm)
            body.append("")
        texts[asof] = body
        (OUT / f"taiyo_{asof}.txt").write_text("\n".join(header + body) + "\n", encoding="utf-8")
        (OUT / f"taiyo_tables_{asof}.json").write_text(json.dumps({"asof": asof, **ri, "url": url, "tables": tables}, ensure_ascii=False, indent=1), encoding="utf-8")
        log["fetches"].append({"short": "taiyo", "law_id": law_id, "asof": asof, "url": url, **ri, "articles": len(main_arts), "appdx_tables": len(appdx)})
        print("ok taiyo", asof, ri["law_revision_id"], len(main_arts), len(appdx), flush=True)
    for x, y in zip(ASOF_TAIYO, ASOF_TAIYO[1:]):
        diff = "\n".join(difflib.unified_diff(texts[x], texts[y], f"taiyo@{x}", f"taiyo@{y}", lineterm=""))
        (OUT / f"diff_taiyo_{x}_vs_{y}.diff").write_text(diff + "\n", encoding="utf-8")
        log.setdefault("diff_line_counts", {})[f"taiyo_{x}_vs_{y}"] = len(diff.splitlines())


# probe：版の間で変わった箇所が、どの改正（law_revision_id）で入ったか、その改正の附則（施行期日・経過措置）を見る
# (略称, 改正履歴から選ぶ施行日の範囲 [from, to], 本則の条番号, 見る語の正規表現)
PROBE_REV = [
    ("shotoku-rei", ("2025-12-01", "2026-12-01"), "198", r"譲渡所得の金額(及び|又は)一時所得の金額"),
]
# (略称, asof, 附則の AmendLawNum を探す正規表現, 附則の条を拾う正規表現)
PROBE_SUPPL = [
    ("sochi", "2026-04-01", r"令和八年三月三一日法律第一二号", r"施行期日|第二十八条の二"),
    ("sochi-rei", "2026-04-01", r"令和八年.*政令第九八号", r"施行期日|第十八条の五"),
    ("shotoku-rei", "2026-12-31", r"令和八年.*政令第九三号", r"施行期日|第百九十八条|損益通算"),
]


def mode_probe(dl, log):
    ids = json.loads((OUT / "law_ids.json").read_text(encoding="utf-8"))
    out = []
    for short, (lo, hi), num, pat in PROBE_REV:
        law_id = ids[short]["law_id"]
        st, body = get(f"{API}/law_revisions/{law_id}?response_format=json")
        (dl / f"revisions_{law_id}.json").write_bytes(body)
        revs = [r for r in json.loads(body).get("revisions", []) if lo <= (r.get("amendment_enforcement_date") or "") <= hi]
        revs.sort(key=lambda r: (r.get("amendment_enforcement_date"), r.get("law_revision_id")))
        out.append(f"## {short} 第{num}条（Num）の /{pat}/ の出現を、改正ごとの版で見る（施行日 {lo}〜{hi}）")
        for r in revs:
            rid = r["law_revision_id"]
            url = f"{API}/law_data/{rid}?response_format=json"
            st, b = get(url)
            (dl / f"{rid}.json").write_bytes(b)
            if st != 200:
                out.append(f"- {rid}: HTTP {st}")
                continue
            d = json.loads(b)
            main_arts, _, _ = split_articles(d["law_full_text"])
            a = next((x for x in main_arts if x["attr"].get("Num") == num), None)
            t = []
            if a is not None:
                render(a, 0, t)
            hits = sorted(set(m.group(0) for m in re.finditer(pat, "\n".join(t))))
            out.append(f"- {rid}（施行日 {r.get('amendment_enforcement_date')}、{r.get('amendment_law_num')}、状態 {r.get('current_revision_status')}）：{hits}")
            log["fetches"].append({"short": short, "url": url, "status": st, "law_revision_id": rid, "hits": hits})
            print("ok probe-rev", rid, hits, flush=True)
        out.append("")
    for short, asof, an_re, kw in PROBE_SUPPL:
        law_id = ids[short]["law_id"]
        url, d = fetch_full(law_id, asof, dl)
        ri = rev_info(d)
        _, suppl, _ = split_articles(d["law_full_text"])
        hits = [s for s in suppl if re.search(an_re, s.get("attr", {}).get("AmendLawNum", ""))]
        out.append(f"## {short} asof={asof}（{ri['law_revision_id']}）の附則のうち AmendLawNum が /{an_re}/ のもの（{len(hits)} 件）で、条の本文が /{kw}/ に当たる条")
        out.append(f"取得URL={url}")
        for s in hits:
            sa = []
            walk(s, lambda n, p: sa.append(n) if n.get("tag") == "Article" else None)
            for a in sa:
                t = []
                render(a, 0, t)
                if re.search(kw, "\n".join(t)):
                    out.append(f"### 附則 AmendLawNum={s.get('attr', {}).get('AmendLawNum')} Num={a['attr'].get('Num')}")
                    out.extend(t)
                    out.append("")
        log["fetches"].append({"short": short, "asof": asof, "url": url, **ri, "suppl_hits": len(hits)})
        print("ok probe-suppl", short, asof, len(hits), flush=True)
    (OUT / "probe.txt").write_text("\n".join(out) + "\n", encoding="utf-8")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "articles"
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_genka_laws_{mode}"
    dl.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "mode": mode, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "fetches": [], "errors": []}
    if mode == "index":
        mode_index(dl, log)
    elif mode == "revisions":
        mode_revisions(dl, log)
    elif mode == "articles":
        mode_articles(dl, log, only=sys.argv[2:] or None)
    elif mode == "taiyo":
        mode_taiyo(dl, log)
    elif mode == "probe":
        mode_probe(dl, log)
    else:
        raise SystemExit("mode は index / revisions / articles / taiyo / probe")
    (OUT / f"fetch_log_{mode}{('_' + '_'.join(sys.argv[2:])) if sys.argv[2:] else ''}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", OUT)


if __name__ == "__main__":
    main()

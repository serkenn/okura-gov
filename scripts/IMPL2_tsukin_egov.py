"""IMPL2 tsukin: e-Gov 法令API v2 で、通勤手当の非課税（所得税法第9条第1項第5号、所得税法施行令第20条の2、
所得税法施行規則の駐車場等の規定）の条文を、改正の版ごとに取り出す。あわせて給与所得の定義（所法28）と収入金額（所法36）を取り出す。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL2_tsukin_egov.py

- e-Gov の呼び方と条文のテキスト化は scripts/R1_egov_articles.py を写した（import はしない）。
- 手順
  1. /law_revisions/<law_id> で所得税法施行令・所得税法の改正履歴を取り、施行日が 2024-01-01〜2028-12-31 のものを残す。
  2. 所得税法施行令：その範囲の改正の施行日（の前日と当日）と固定の時点（FIXED_ASOF_REI）で /law_data を取り、第20条の2 を取り出す。
     版（law_revision_id）ごとの本文の SHA-256 と、本文が変わった版どうしの差分（difflib）を書く。
     版の並びは、取った asof の最も早い日の順（UnEnforced の版は revision_info の施行日が null のことがあるため）。
  3. 最後に取った版の本文から、令和6年〜令和10年の改正法令の附則（SupplProvision の AmendLawNum が「令和六年」〜「令和十年」で
     始まるもの。AmendLawNum は「令和七年一一月一九日政令第三八〇号」の形で、改正履歴の amendment_law_num
     「令和七年政令第三百八十号」とは書き方が違う）を全部取り出し、キーワードを含む附則を記録する。
  4. 所得税法：施行令と同じ手順で第9条を版ごとに取り（第1項第5号の改正の施行日を知るため）、附則を「第九条第一項第五号」「通勤」で
     走査する。FIXED_ASOF_HO の時点では第9条・第28条・第36条も書く。
  5. 所得税法施行規則（施行令第20条の2 が「財務省令で定める」とした駐車場等の要件・金額）：FIXED_ASOF_KI で本則の全条を走査し、
     「駐車場等」「第二十条の二」を含む条を取り出す。附則も同じ語で走査する。
- ダウンロードしたもの（信頼できないデータ）は .work/downloads/<YYYYMMDD-HHMMSS>_IMPL2_tsukin_egov/ に置く（新しい空のディレクトリ。
  中では何も実行しない）。
- 出力は scripts/results/IMPL2_tsukin_egov/。リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。
"""
import datetime as dt
import difflib
import hashlib
import json
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
SLEEP = 1.5
OUT = ROOT / "scripts" / "results" / "IMPL2_tsukin_egov"

REI = "340CO0000000096"  # 所得税法施行令
HO = "340AC0000000033"  # 所得税法
KI = "340M50000040011"  # 所得税法施行規則
RANGE = ("2024-01-01", "2028-12-31")
FIXED_ASOF_REI = ["2024-12-31", "2025-03-31", "2025-04-01", "2025-12-31", "2026-03-31", "2026-04-01", "2026-11-11",
                  "2026-12-31", "2027-12-31"]
FIXED_ASOF_HO = ["2024-12-31", "2025-12-31", "2026-03-31", "2026-04-01", "2026-11-11", "2026-12-31", "2027-01-01"]
FIXED_ASOF_KI = ["2026-03-31", "2026-04-01", "2026-11-11"]
SUPPL_PREFIXES = ("令和六年", "令和七年", "令和八年", "令和九年", "令和十年")
REI_ARTS = ["20_2"]
HO_ARTS = ["9", "28", "36"]
REI_KEYWORDS = ["第二十条の二", "通勤"]
HO_KEYWORDS = ["第九条第一項第五号", "通勤"]
KI_KEYWORDS = ["駐車場等", "第二十条の二"]

BLOCK_LIKE = {"Paragraph", "Item"} | {f"Subitem{i}" for i in range(1, 11)}
NL = "\n"


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
        cells = [inline(c).replace(NL, " ") for c in ch if isinstance(c, dict)]
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


def api(path, **q):
    q.setdefault("response_format", "json")
    url = API + path + "?" + urllib.parse.urlencode(q)
    st, body = get(url)
    return url, st, body


def revisions(law_id, dl):
    url, st, body = api(f"/law_revisions/{law_id}")
    (dl / f"revisions_{law_id}.json").write_bytes(body)
    if st != 200:
        raise RuntimeError(f"{url} -> {st}")
    keys = ["law_revision_id", "amendment_law_num", "amendment_law_title", "amendment_promulgate_date",
            "amendment_enforcement_date", "amendment_enforcement_comment", "current_revision_status", "updated"]
    rows = [{k: r.get(k) for k in keys} for r in json.loads(body).get("revisions", [])]
    return url, [r for r in rows if r["amendment_enforcement_date"] and RANGE[0] <= r["amendment_enforcement_date"] <= RANGE[1]]


def fetch_law(law_id, asof, dl):
    url, st, body = api(f"/law_data/{law_id}", asof=asof)
    (dl / f"{law_id}_{asof}.json").write_bytes(body)
    if st != 200:
        raise RuntimeError(f"{url} -> {st} {body[:200]!r}")
    d = json.loads(body)
    ri = d.get("revision_info") or {}
    meta = {"law_id": law_id, "asof": asof, "url": url, "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body),
            "law_revision_id": ri.get("law_revision_id"), "amendment_law_num": ri.get("amendment_law_num"),
            "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
            "current_revision_status": ri.get("current_revision_status")}
    return meta, d["law_full_text"]


def split(root):
    main_arts, suppl = [], []

    def collect(n, path):
        if n.get("tag") == "Article" and "SupplProvision" not in path:
            main_arts.append(n)
        if n.get("tag") == "SupplProvision":
            suppl.append(n)
    walk(root, collect)
    return {a["attr"].get("Num"): a for a in main_arts}, suppl


def article_text(by_num, num):
    a = by_num.get(num)
    if a is None:
        return f"## Num={num}: 見つからない（この時点の本則にない）" + NL
    lines = [f"## Num={num}"]
    render(a, 0, lines)
    return NL.join(lines) + NL


def prev_day(d):
    return (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()


def header(name, law_id, asof, meta, ts):
    return NL.join([f"# {name} {law_id} asof={asof}",
                    f"# law_revision_id={meta['law_revision_id']} 改正法令={meta['amendment_law_num']} "
                    f"施行日={meta['amendment_enforcement_date']} 状態={meta['current_revision_status']}",
                    f"# 取得URL={meta['url']}", f"# 取得日時={ts}", "", ""])


def track(law_id, short, name, arts, fixed, revs, keywords, dl, log, ts, extra_arts=None):
    """改正の施行日（の前日と当日）と固定の時点で本文を取り、arts の本文の版ごとの差分と、附則のキーワードの一致を書く。"""
    dates = set(fixed)
    for r in revs:
        d = r["amendment_enforcement_date"]
        dates.add(d)
        dates.add(prev_day(d))
    tag = "_".join(arts)
    versions = {}
    last_root = None
    for asof in sorted(dates):
        meta, root = fetch_law(law_id, asof, dl)
        by_num, _ = split(root)
        text = "".join(article_text(by_num, n) for n in arts)
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        meta["article_text_sha256"] = sha
        log["fetches"].append(meta)
        v = versions.setdefault(meta["law_revision_id"], {"asofs": [], "article_text_sha256": sha, "meta": meta})
        v["asofs"].append(asof)
        h = header(name, law_id, asof, meta, ts)
        (OUT / f"{short}_{tag}_{asof}.txt").write_text(h + text, encoding="utf-8")
        if extra_arts and asof in fixed:
            et = "".join(article_text(by_num, n) for n in extra_arts)
            (OUT / f"{short}_{'_'.join(extra_arts)}_{asof}.txt").write_text(h + et, encoding="utf-8")
        last_root = root
        print(short, asof, meta["law_revision_id"], sha[:16], flush=True)

    order = sorted(versions.items(), key=lambda kv: min(kv[1]["asofs"]))
    summary = []
    prev = None
    for rid, v in order:
        cur = (OUT / f"{short}_{tag}_{v['asofs'][0]}.txt").read_text(encoding="utf-8").split(NL + NL, 1)[1]
        changed = prev is not None and prev[1] != v["article_text_sha256"]
        summary.append({"law_revision_id": rid, "enforcement": v["meta"]["amendment_enforcement_date"],
                        "amendment_law_num": v["meta"]["amendment_law_num"], "status": v["meta"]["current_revision_status"],
                        "asofs": v["asofs"], "article_text_sha256": v["article_text_sha256"], "changed_from_previous": changed})
        if changed:
            diff = difflib.unified_diff(prev[2].splitlines(), cur.splitlines(), fromfile=prev[0], tofile=rid, lineterm="")
            (OUT / f"diff_{short}_{tag}_{prev[0]}__{rid}.txt").write_text(NL.join(diff), encoding="utf-8")
        prev = (rid, v["article_text_sha256"], cur)
    (OUT / f"{short}_{tag}_versions.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")

    _, suppl = split(last_root)
    amend_nums = sorted({sp.get("attr", {}).get("AmendLawNum") or "" for sp in suppl} - {""})
    amend_nums = [a for a in amend_nums if a.startswith(SUPPL_PREFIXES)]
    hits = []
    lines = [f"# {name}の附則（AmendLawNum が {SUPPL_PREFIXES} で始まるもの）。本文は asof={sorted(dates)[-1]} の版から", ""]
    for an in amend_nums:
        ss = [sp for sp in suppl if sp.get("attr", {}).get("AmendLawNum") == an]
        lines.append(f"## 附則 AmendLawNum={an}: {len(ss)} 件")
        for sp in ss:
            sl = []
            render(sp, 0, sl)
            txt = NL.join(sl)
            lines.append(txt)
            if any(k in txt for k in keywords):
                hits.append({"amendment_law_num": an, "keywords": [k for k in keywords if k in txt]})
        lines.append("")
    (OUT / f"{short}_suppl_in_range.txt").write_text(NL.join(lines), encoding="utf-8")
    (OUT / f"{short}_suppl_keyword_hits.json").write_text(json.dumps(hits, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL2_tsukin_egov"
    dl.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "fetches": [], "revisions": {}}

    # 1. 改正履歴
    rev = {}
    for law_id in (REI, HO):
        url, rows = revisions(law_id, dl)
        rev[law_id] = rows
        log["revisions"][law_id] = {"url": url, "rows_in_range": rows}
    (OUT / "revisions_in_range.json").write_text(json.dumps(rev, ensure_ascii=False, indent=1), encoding="utf-8")

    # 2・3. 施行令 第20条の2（版ごと）と附則
    track(REI, "rei", "所得税法施行令", REI_ARTS, FIXED_ASOF_REI, rev[REI], REI_KEYWORDS, dl, log, ts)
    # 4. 所得税法 第9条（版ごと）と附則、固定の時点で第9条・第28条・第36条
    track(HO, "ho", "所得税法", ["9"], FIXED_ASOF_HO, rev[HO], HO_KEYWORDS, dl, log, ts, extra_arts=HO_ARTS)

    # 5. 所得税法施行規則：駐車場等
    ki_hits = []
    for asof in FIXED_ASOF_KI:
        meta, root = fetch_law(KI, asof, dl)
        by_num, suppl_ki = split(root)
        lines = [header("所得税法施行規則", KI, asof, meta, ts) + "# 本則で KI_KEYWORDS を含む条", ""]
        found = []
        for num, a in by_num.items():
            al = []
            render(a, 0, al)
            t = NL.join(al)
            if any(k in t for k in KI_KEYWORDS):
                found.append(num)
                lines += [f"## Num={num}", t, ""]
        lines += ["# 附則（AmendLawNum が SUPPL_PREFIXES で始まり、KI_KEYWORDS を含むもの）", ""]
        sfound = []
        for sp in suppl_ki:
            an = sp.get("attr", {}).get("AmendLawNum") or ""
            if not an.startswith(SUPPL_PREFIXES):
                continue
            sl = []
            render(sp, 0, sl)
            t = NL.join(sl)
            if any(k in t for k in KI_KEYWORDS):
                sfound.append(an)
                lines += [f"## 附則 AmendLawNum={an}", t, ""]
        meta["articles_with_keywords"] = found
        meta["suppl_with_keywords"] = sfound
        log["fetches"].append(meta)
        ki_hits.append({"asof": asof, "law_revision_id": meta["law_revision_id"], "articles": found, "suppl": sfound})
        (OUT / f"ki_chushajo_{asof}.txt").write_text(NL.join(lines), encoding="utf-8")
        print("ki", asof, meta["law_revision_id"], found, sfound, flush=True)
    (OUT / "ki_keyword_hits.json").write_text(json.dumps(ki_hits, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", OUT)


if __name__ == "__main__":
    main()

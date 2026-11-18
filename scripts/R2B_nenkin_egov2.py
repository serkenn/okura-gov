r"""R2B_nenkin（2回目）：源泉徴収を要しない公的年金等の額（所令319の12、措令26の27）の版ごとの値と、改正政令の施行期日・適用関係、
年金生活者支援給付金の非課税の定めを e-Gov 法令API v2 で取得する。

実行:
  C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe -I -X utf8 scripts/R2B_nenkin_egov2.py
標準ライブラリのみ。リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。個人の情報は送らない。

- 措令26の27の2（所令319の12 を読み替えるもう一つの条）と、措法41の16の2（基礎控除等の特例。公的年金等の源泉徴収の読替えを含む）も取得する。
- 1回目（scripts/R2B_nenkin_egov.py）で、所令319の12 が 2025-12-31 版で 108万円、2026-12-31 版で 118万円だったため、
  いつの改正か（改正政令の附則）を確かめる。
- ダウンロードした JSON は .work/downloads/<ts>_R2B_nenkin_egov2/ に置く（信頼できないデータ。中でコードを実行しない）。
- 結果は scripts/results/R2B_nenkin_egov2/ に書く：
    revisions_<略称>.json      改正履歴（2025-01-01 以後）
    articles_<略称>_<asof>.txt  指定の条と、本文に指定の語を含む改正附則の条
    lawsearch.json             法令名から引いた law_id
    fetch_log.json             取得記録（URL、law_revision_id、SHA-256）
scripts/R2B_nenkin_egov.py のコードを写して作った（import はしていない）。
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
OUT = ROOT / "scripts" / "results" / "R2B_nenkin_egov2"

# (略称, law_id, [asof...], [本則の条 Num], [改正附則の本文で探す語])
JOBS = [
    ("shotoku-rei", "340CO0000000096", ["2025-12-31", "2026-01-01", "2027-01-01"], ["319_12"], ["第三百十九条の十二", "公的年金"]),
    ("sochi-rei", "332CO0000000043", ["2025-12-31", "2026-01-01", "2027-01-01"], ["26_27", "26_27_2"], ["第二十六条の二十七", "公的年金"]),
    ("sochi", "332AC0000000026", ["2026-12-31"], ["41_16_2"], ["第四十一条の十六の二"]),
]
REVISIONS = [("shotoku-rei", "340CO0000000096"), ("sochi-rei", "332CO0000000043")]
LAWSEARCH = ["年金生活者支援給付金の支給に関する法律"]

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


def text_of(a):
    tl = []
    render(a, 0, tl)
    return "\n".join(tl)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2B_nenkin_egov2"
    dl.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "user_agent": UA, "fetches": []}

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
        (OUT / f"revisions_{short}.json").write_text(json.dumps({"url": url, "status": st, "revisions": revs}, ensure_ascii=False, indent=1), encoding="utf-8")
        log["fetches"].append({"kind": "revisions", "short": short, "url": url, "status": st, "n": len(revs), "sha256": hashlib.sha256(body).hexdigest()})
        print("revisions", short, st, len(revs), flush=True)

    for short, law_id, asofs, arts, kws in JOBS:
        for asof in asofs:
            q = {"response_format": "json", "asof": asof}
            url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode(q)
            st, body = get(url)
            (dl / f"{law_id}_{asof}.json").write_bytes(body)
            if st != 200:
                raise RuntimeError(f"{url} -> {st}")
            d = json.loads(body)
            ri = d.get("revision_info") or {}
            log["fetches"].append({"kind": "law_data", "short": short, "law_id": law_id, "asof": asof, "url": url,
                                   "law_revision_id": ri.get("law_revision_id"), "amendment_law_num": ri.get("amendment_law_num"),
                                   "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                                   "current_revision_status": ri.get("current_revision_status"),
                                   "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)})
            print("ok", short, asof, ri.get("law_revision_id"), flush=True)
            root = d["law_full_text"]
            main_arts, suppl = {}, []

            def collect(n, path):
                tags = [p.get("tag") for p in path]
                if n.get("tag") == "Article" and "SupplProvision" not in tags:
                    main_arts[n["attr"].get("Num")] = n
                if n.get("tag") == "SupplProvision":
                    suppl.append(n)
            walk(root, collect)
            lines = [f"# {short} {law_id} asof={asof}",
                     f"# law_revision_id={ri.get('law_revision_id')} 改正法令={ri.get('amendment_law_num')} 施行日={ri.get('amendment_enforcement_date')} 状態={ri.get('current_revision_status')}",
                     f"# 取得URL={url}", f"# 取得日時={ts}", f"# 生データ SHA-256={hashlib.sha256(body).hexdigest()}", ""]
            for num in arts:
                a = main_arts.get(num)
                lines.append(f"## 本則 Num={num}" + ("" if a else ": 見つからない"))
                if a:
                    render(a, 0, lines)
                lines.append("")
            for s in suppl:
                an = (s.get("attr") or {}).get("AmendLawNum")
                if not an:
                    continue
                hit_arts = []
                for c in s.get("children", []):
                    if isinstance(c, dict) and c.get("tag") == "Article":
                        t = text_of(c)
                        if any(k in t for k in kws):
                            hit_arts.append(t)
                if hit_arts:
                    lines.append(f"## 改正附則 AmendLawNum={an}（本文に {kws} のどれかを含む条）")
                    lines += hit_arts
                    lines.append("")
            (OUT / f"articles_{short}_{asof}.txt").write_text("\n".join(lines), encoding="utf-8")

    found = {}
    for title in LAWSEARCH:
        q = urllib.parse.urlencode({"law_title": title, "response_format": "json"})
        url = f"{API}/laws?{q}"
        st, body = get(url)
        (dl / "lawsearch.json").write_bytes(body)
        laws = []
        if st == 200:
            for x in json.loads(body).get("laws", []):
                li = x.get("law_info") or {}
                ri = x.get("revision_info") or {}
                laws.append({"law_id": li.get("law_id"), "law_num": li.get("law_num"), "law_title": ri.get("law_title")})
        found[title] = {"url": url, "status": st, "laws": laws}
        log["fetches"].append({"kind": "laws", "title": title, "url": url, "status": st, "sha256": hashlib.sha256(body).hexdigest()})
    (OUT / "lawsearch.json").write_text(json.dumps(found, ensure_ascii=False, indent=1), encoding="utf-8")

    for title, ent in found.items():
        exact = [x for x in ent["laws"] if x["law_title"] == title]
        if not exact:
            continue
        law_id = exact[0]["law_id"]
        q = {"response_format": "json", "asof": "2026-11-09", "omit_amendment_suppl_provision": "true"}
        url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode(q)
        st, body = get(url)
        (dl / f"{law_id}_2026-11-09.json").write_bytes(body)
        d = json.loads(body)
        ri = d.get("revision_info") or {}
        log["fetches"].append({"kind": "law_data", "short": "shienkyufu", "law_id": law_id, "asof": "2026-11-09", "url": url,
                               "law_revision_id": ri.get("law_revision_id"), "sha256": hashlib.sha256(body).hexdigest()})
        arts = []

        def collect2(n, path):
            tags = [p.get("tag") for p in path]
            if n.get("tag") == "Article" and "SupplProvision" not in tags:
                t = text_of(n)
                if "公課" in t:
                    arts.append(t)
        walk(d["law_full_text"], collect2)
        lines = [f"# shienkyufu {title} {law_id} asof=2026-11-09", f"# law_revision_id={ri.get('law_revision_id')}",
                 f"# 取得URL={url}", f"# 取得日時={ts}", f"# 生データ SHA-256={hashlib.sha256(body).hexdigest()}", "",
                 "## 本則のうち「公課」を含む条"] + arts
        (OUT / "articles_shienkyufu_2026-11-09.txt").write_text("\n".join(lines), encoding="utf-8")
        print("ok shienkyufu", law_id, ri.get("law_revision_id"), flush=True)

    (OUT / "fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", OUT)


if __name__ == "__main__":
    sys.exit(main())

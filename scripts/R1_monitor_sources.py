"""R1: 監視（D9）に使えそうな情報源と、税制改正の一次資料のページを実際に取得して確かめる。

実行:  python -I scripts/R1_monitor_sources.py
標準ライブラリのみ。リクエストの間は 1.5 秒あける。robots.txt も取得して記録する（中身の判断は人が行う）。

やること
 1. 各サイトのトップページ等を取得し、<link rel="alternate" type="application/rss+xml|atom+xml"> と、
    href に rss / rdf / atom / feed を含むリンクを列挙する。
 2. 見つかったフィード（同じホストのもの、各サイト最大6件）を取得し、形式・件数・先頭の項目を記録する。
 3. 税制改正の一次資料のページ（国税庁・財務省）を取得し、タイトルと「万円」を含む行を抜き出す。

HTML・XML は .work/downloads/<ts>_monitor_sources/ に置く（信頼できないデータ）。
要約は scripts/results/R1_monitor_sources/summary.json に書く。
XML は xml.etree で読むが、DTD・外部実体を含むものは読まずに記録だけする。
"""
import html
import json
import pathlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
SLEEP = 1.5
MAX_BYTES = 8_000_000

SITES = {
    "nta": ["https://www.nta.go.jp/", "https://www.nta.go.jp/information/news/news.htm", "https://www.nta.go.jp/information/rss.htm", "https://www.nta.go.jp/about/rss/index.htm"],
    "egov_laws": ["https://laws.e-gov.go.jp/"],
    "kanpo": ["https://www.kanpo.go.jp/"],
    "mof": ["https://www.mof.go.jp/", "https://www.mof.go.jp/tax_policy/tax_reform/index.html"],
    "mhlw": ["https://www.mhlw.go.jp/"],
    "nenkin": ["https://www.nenkin.go.jp/"],
}
PRIMARY_PAGES = {
    "nta_2025kiso": "https://www.nta.go.jp/users/gensen/2025kiso/index.htm",
    "nta_2026kiso_guess": "https://www.nta.go.jp/users/gensen/2026kiso/index.htm",
    "mof_fy2025": "https://www.mof.go.jp/tax_policy/tax_reform/outline/fy2025/index.html",
    "mof_fy2025_explanation_guess": "https://www.mof.go.jp/tax_policy/tax_reform/outline/fy2025/explanation/index.html",
    "mof_fy2026": "https://www.mof.go.jp/tax_policy/tax_reform/outline/fy2026/index.html",
    "mof_fy2026_explanation_guess": "https://www.mof.go.jp/tax_policy/tax_reform/outline/fy2026/explanation/index.html",
}
FEED_HINT = re.compile(r"(rss|\.rdf|atom|feed)", re.I)


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read(MAX_BYTES)
            res = (r.status, r.headers.get("Content-Type"), r.geturl(), body)
    except urllib.error.HTTPError as e:
        res = (e.code, e.headers.get("Content-Type"), url, e.read(20000))
    except Exception as e:  # noqa
        res = (None, None, url, repr(e).encode())
    time.sleep(SLEEP)
    return res


def decode(body, ctype):
    m = re.search(r"charset=([\w-]+)", ctype or "", re.I) or re.search(rb'charset=["\']?([\w-]+)', body[:3000], re.I)
    enc = m.group(1) if m else "utf-8"
    if isinstance(enc, bytes):
        enc = enc.decode("ascii", "replace")
    try:
        return body.decode(enc, "replace")
    except LookupError:
        return body.decode("utf-8", "replace")


def text_of(h):
    h = re.sub(r"(?is)<(script|style).*?</\1>", " ", h)
    h = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</tr>|</h\d>|</div>|</td>", "\n", h)
    t = html.unescape(re.sub(r"<[^>]+>", " ", h))
    return [re.sub(r"[ \t　]+", " ", l).strip() for l in t.splitlines() if l.strip()]


def safe_name(url):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", url)[:150]


def parse_feed(body):
    head = body[:4000]
    if b"<!DOCTYPE" in head or b"<!ENTITY" in head:
        return {"skipped": "DTD/ENTITY を含むので解析しない"}
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        return {"parse_error": str(e)}
    tag = root.tag.split("}")[-1]
    items = [e for e in root.iter() if e.tag.split("}")[-1] in ("item", "entry")]

    def child(e, name):
        for c in e:
            if c.tag.split("}")[-1] == name:
                return (c.text or c.get("href") or "").strip()
        return None
    return {"root": tag, "items": len(items),
            "head": [{"title": child(i, "title"), "link": child(i, "link"),
                      "date": child(i, "pubDate") or child(i, "date") or child(i, "updated")} for i in items[:5]]}


def main():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_monitor_sources"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "R1_monitor_sources"
    out.mkdir(parents=True, exist_ok=True)
    summary = {"run_at": ts, "user_agent": UA, "sites": {}, "primary_pages": {}}

    for site, urls in SITES.items():
        rec = {"pages": [], "feeds": []}
        host = urllib.parse.urlparse(urls[0]).netloc
        st, ct, final, body = get(f"https://{host}/robots.txt")
        (dl / f"{site}_robots.txt").write_bytes(body)
        rec["robots_txt"] = {"status": st, "text_head": decode(body, ct)[:1500] if st == 200 else None}
        cands = []
        for u in urls:
            st, ct, final, body = get(u)
            (dl / f"{site}_{safe_name(u)}.html").write_bytes(body)
            h = decode(body, ct) if st == 200 else ""
            alt = re.findall(r'(?is)<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]*>', h)
            alt_href = [re.search(r'href=["\']([^"\']+)', a).group(1) for a in alt if re.search(r'href=["\']([^"\']+)', a)]
            hrefs = re.findall(r'(?i)href=["\']([^"\']+)["\']', h)
            hinted = sorted({x for x in hrefs if FEED_HINT.search(x)})
            title = re.search(r"(?is)<title>(.*?)</title>", h)
            rec["pages"].append({"url": u, "status": st, "final_url": final, "content_type": ct,
                                 "title": html.unescape(title.group(1)).strip() if title else None,
                                 "link_rel_alternate_feeds": alt_href, "hrefs_with_feed_hint": hinted[:40]})
            for x in alt_href + hinted:
                full = urllib.parse.urljoin(final, x)
                if urllib.parse.urlparse(full).netloc.endswith(host.split(".", 1)[-1]) and full not in cands:
                    cands.append(full)
        for fu in cands[:6]:
            st, ct, final, body = get(fu)
            (dl / f"{site}_feed_{safe_name(fu)}").write_bytes(body)
            f = {"url": fu, "status": st, "content_type": ct, "final_url": final}
            if st == 200 and (b"<rss" in body[:3000] or b"<feed" in body[:3000] or b"<rdf:RDF" in body[:3000]):
                f.update(parse_feed(body))
            else:
                f["note"] = "フィードではない（HTML 等）"
                t = re.search(rb"(?is)<title>(.*?)</title>", body)
                f["title"] = decode(t.group(1), ct).strip() if t else None
            rec["feeds"].append(f)
        summary["sites"][site] = rec

    for key, u in PRIMARY_PAGES.items():
        st, ct, final, body = get(u)
        (dl / f"primary_{key}.html").write_bytes(body)
        rec = {"url": u, "status": st, "final_url": final, "content_type": ct}
        if st == 200:
            h = decode(body, ct)
            title = re.search(r"(?is)<title>(.*?)</title>", h)
            rec["title"] = html.unescape(title.group(1)).strip() if title else None
            lines = text_of(h)
            rec["lines_with_manen"] = [l[:300] for l in lines if "万円" in l][:60]
            rec["pdf_links"] = sorted({urllib.parse.urljoin(final, x) for x in re.findall(r'(?i)href=["\']([^"\']+\.pdf)["\']', h)})[:60]
        summary["primary_pages"][key] = rec

    # 4. sitemap.xml に lastmod（更新日）があるか（RSS の代わりに使えるか）
    summary["sitemaps"] = {}
    for key, u in {"nta": "https://www.nta.go.jp/sitemap.xml"}.items():
        st, ct, final, body = get(u)
        (dl / f"sitemap_{key}.xml").write_bytes(body)
        rec = {"url": u, "status": st, "content_type": ct, "bytes": len(body)}
        if st == 200 and b"<!DOCTYPE" not in body[:4000] and b"<!ENTITY" not in body[:4000]:
            try:
                root = ET.fromstring(body)
                locs = [e for e in root.iter() if e.tag.split("}")[-1] in ("url", "sitemap")]
                lm = [c.text for e in locs for c in e if c.tag.split("}")[-1] == "lastmod"]
                rec.update({"root": root.tag.split("}")[-1], "entries": len(locs), "entries_with_lastmod": len(lm),
                            "lastmod_max": max(lm) if lm else None,
                            "head": [[(c.tag.split("}")[-1], (c.text or "").strip()) for c in e] for e in locs[:3]]})
            except ET.ParseError as e:
                rec["parse_error"] = str(e)
        summary["sitemaps"][key] = rec

    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", out)


if __name__ == "__main__":
    main()

"""R3: 法令変更の監視（D9）に使えそうな情報源を実際に取得し、機械で読めるかを確かめる。

実行: python -I scripts/R3_monitor_probe.py

各候補 URL について次を記録する。
1. 通常の GET：HTTP ステータス、Content-Type、サイズ、SHA-256、Last-Modified、ETag、Cache-Control
2. 「ソフト404」（200 を返すが中身は『ページが見つかりません』）かどうか（タイトルで判定）
3. RSS/RDF/Atom なら、項目数、最新の日付、先頭3件のタイトル
   HTML なら、本文中の日付表記（令和X年X月X日／YYYY年M月D日）の数と最新日付、リンク数
4. 条件付き GET（If-None-Match / If-Modified-Since）で 304 を返すか
5. 2回目の通常 GET で本文のハッシュが変わるか（毎回変わるならハッシュ比較の差分監視に向かない）

- 取得したものは信頼できないデータとして、新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_R3_monitor_probe/ に置く。
- 結果は scripts/results/R3_monitor_probe/probe_<ts>.json と summary_<ts>.md に書く。
- XML は DOCTYPE / ENTITY を含む場合はパースしない（外部実体・展開攻撃の予防）。
- リクエストの間は 1.5 秒あける。User-Agent は汎用名。
標準ライブラリのみ（Python 3.11）。
"""
import datetime as dt
import email.utils
import hashlib
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
WAIT = 1.5
TIMEOUT = 30

# (id, 機関, 種類の想定, URL)
CANDIDATES = [
    # 国税庁
    ("nta_news", "国税庁", "html", "https://www.nta.go.jp/information/news/index.htm"),
    ("nta_shotoku_kaisei", "国税庁", "html", "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/kaisei/kaisei_a.htm"),
    ("nta_gensen_index", "国税庁", "html", "https://www.nta.go.jp/users/gensen/index.htm"),
    ("nta_ta_1180", "国税庁", "html", "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1180.htm"),
    ("nta_rss_guess1", "国税庁", "feed?", "https://www.nta.go.jp/rss/index.htm"),
    ("nta_rss_guess2", "国税庁", "feed?", "https://www.nta.go.jp/rss.xml"),
    # 厚生労働省
    ("mhlw_news_rdf", "厚労省", "feed", "https://www.mhlw.go.jp/stf/news.rdf"),
    ("mhlw_rss_index", "厚労省", "html", "https://www.mhlw.go.jp/rss/index.html"),
    ("mhlw_hourei_new_tsuchi", "厚労省", "html", "https://www.mhlw.go.jp/hourei/new/tsuchi/newindex.html"),
    ("mhlw_hourei_update", "厚労省", "html", "https://www.mhlw.go.jp/hourei/new/update/data.html"),
    ("mhlw_hourei_search_R071001", "厚労省", "html",
     "https://www.mhlw.go.jp/web/t_itemsrch_result?type=1&startGengo=5&yearFrom=7&monthFrom=10&dayFrom=1"
     "&endGengo=5&yearTo=7&monthTo=10&dayTo=1&shubetsu=&bango="),
    # 日本年金機構
    ("nenkin_allnews", "日本年金機構", "html", "https://www.nenkin.go.jp/allNewsList.html"),
    ("nenkin_rss_guess", "日本年金機構", "feed?", "https://www.nenkin.go.jp/rss/news.xml"),
    # 協会けんぽ
    ("kyokai_top", "協会けんぽ", "html", "https://www.kyoukaikenpo.or.jp/"),
    # 総務省
    ("soumu_rss_info", "総務省", "html", "https://www.soumu.go.jp/menu_kyotsuu/rss_information.html"),
    ("soumu_news_rdf", "総務省", "feed", "https://www.soumu.go.jp/news.rdf"),
    # e-Gov パブリックコメント（改正の予告を拾う候補）
    ("egov_pubcom_rss", "e-Gov", "feed", "https://public-comment.e-gov.go.jp/rss/pcm_list.xml"),
]

SOFT404 = re.compile(r"(見つかりません|表示できませんでした|Not Found|ページが存在しません)", re.I)
DATE_WAREKI = re.compile(r"令和\s*([0-9０-９元]+)\s*年\s*([0-9０-９]+)\s*月\s*([0-9０-９]+)\s*日")
DATE_SEIREKI = re.compile(r"(20[0-9]{2})\s*年\s*([0-9]{1,2})\s*月\s*([0-9]{1,2})\s*日")
DATE_ISO = re.compile(r"(20[0-9]{2})[-/.]([0-9]{1,2})[-/.]([0-9]{1,2})")


def z2h(s):
    return s.translate(str.maketrans("０１２３４５６７８９", "0123456789")).replace("元", "1")


def req(url, extra=None):
    h = {"User-Agent": UA, "Accept-Language": "ja"}
    if extra:
        h.update(extra)
    r = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=TIMEOUT) as resp:
            return resp.status, resp.geturl(), dict(resp.headers), read_with_deadline(resp)
    except urllib.error.HTTPError as e:
        body = b""
        try:
            body = e.read()
        except Exception:  # noqa: BLE001
            pass
        return e.code, url, dict(e.headers or {}), body


def read_with_deadline(resp, seconds=90):
    """本文を少しずつ読み、全体の制限時間を超えたら打ち切る（ソケットの timeout は1回の読み取りごとにしか効かないため）。"""
    deadline = time.monotonic() + seconds
    chunks = []
    while True:
        b = resp.read(65536)
        if not b:
            break
        chunks.append(b)
        if time.monotonic() > deadline:
            raise TimeoutError(f"body read exceeded {seconds}s")
    return b"".join(chunks)


def decode(body, ctype):
    m = re.search(r"charset=([\w\-]+)", ctype or "", re.I) or re.search(
        r"charset=[\"']?([\w\-]+)", body[:4000].decode("ascii", "replace"), re.I)
    for c in ([m.group(1)] if m else []) + ["utf-8", "cp932", "euc-jp"]:
        try:
            return body.decode(c)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", "replace")


def dates_in(text):
    found = []
    for y, m, d in DATE_WAREKI.findall(text):
        try:
            found.append(dt.date(2018 + int(z2h(y)), int(z2h(m)), int(z2h(d))))
        except ValueError:
            pass
    for pat in (DATE_SEIREKI, DATE_ISO):
        for y, m, d in pat.findall(text):
            try:
                found.append(dt.date(int(y), int(m), int(d)))
            except ValueError:
                pass
    return found


def parse_feed(body):
    head = body[:2000].decode("utf-8", "replace")
    if "<!DOCTYPE" in head.upper() or "<!ENTITY" in body.decode("utf-8", "replace").upper():
        return {"feed_parse": "skipped (DOCTYPE/ENTITY present)"}
    # expat は Shift_JIS などのマルチバイト符号化を扱えないため、宣言された符号化で文字列にしてから UTF-8 で渡す
    m = re.match(rb"<\?xml[^>]*encoding=[\"']([\w\-]+)[\"']", body.lstrip())
    if m and m.group(1).lower() not in (b"utf-8", b"utf8", b"us-ascii"):
        enc = m.group(1).decode("ascii")
        try:
            txt = body.decode({"shift_jis": "cp932", "sjis": "cp932", "x-sjis": "cp932"}.get(enc.lower(), enc))
            body = re.sub(r"encoding=[\"'][\w\-]+[\"']", 'encoding="utf-8"', txt, count=1).encode("utf-8")
        except (LookupError, UnicodeDecodeError) as e:
            return {"feed_parse": f"decode failed ({enc}): {e}"}
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        return {"feed_parse": f"not XML: {e}"}
    items = [el for el in root.iter() if el.tag.split("}")[-1] in ("item", "entry")]
    out = {"feed_root": root.tag.split("}")[-1], "feed_items": len(items), "feed_samples": []}
    dates = []
    for it in items:
        title, date = None, None
        for ch in it:
            t = ch.tag.split("}")[-1]
            if t == "title":
                title = (ch.text or "").strip()
            if t in ("date", "pubDate", "updated", "published"):
                date = (ch.text or "").strip()
        if date:
            try:
                dates.append(dt.datetime.fromisoformat(date.replace("Z", "+00:00")).date())
            except ValueError:
                try:
                    dates.append(email.utils.parsedate_to_datetime(date).date())
                except Exception:  # noqa: BLE001
                    pass
        if len(out["feed_samples"]) < 3:
            out["feed_samples"].append({"title": title, "date": date})
    out["feed_newest_date"] = max(dates).isoformat() if dates else None
    out["feed_items_with_date"] = len(dates)
    return out


def probe(cid, org, kind, url, dl):
    rec = {"id": cid, "org": org, "expected": kind, "url": url}
    st, final, hdr, body = req(url)
    ctype = hdr.get("Content-Type", "")
    sha = hashlib.sha256(body).hexdigest()
    (dl / f"{cid}.bin").write_bytes(body)
    rec.update({
        "status": st, "final_url": final, "content_type": ctype, "bytes": len(body), "sha256": sha,
        "last_modified": hdr.get("Last-Modified"), "etag": hdr.get("ETag"),
        "cache_control": hdr.get("Cache-Control"), "saved": str((dl / f"{cid}.bin").relative_to(ROOT)),
    })
    text = decode(body, ctype) if body else ""
    m = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    title = " ".join(m.group(1).split()) if m else None
    rec["title"] = title
    rec["soft_404"] = bool(st == 200 and title and SOFT404.search(title))
    is_xml = ("xml" in ctype.lower() or "rdf" in ctype.lower() or text.lstrip().startswith("<?xml")) and "<html" not in text[:500].lower()
    rec["is_feed_like"] = is_xml
    if st == 200 and is_xml:
        rec.update(parse_feed(body))
    elif st == 200:
        ds = dates_in(text)
        rec["html_dates_found"] = len(ds)
        rec["html_newest_date"] = max(ds).isoformat() if ds else None  # 本文中の最大の日付（施行日など未来の日付を含む）
        past = [d for d in ds if d <= dt.date.today()]
        rec["html_newest_past_date"] = max(past).isoformat() if past else None  # 今日以前で最大の日付
        rec["html_links"] = len(re.findall(r"<a\s[^>]*href=", text, re.I))
    # 条件付き GET
    cond = {}
    if hdr.get("ETag"):
        cond["If-None-Match"] = hdr["ETag"]
    if hdr.get("Last-Modified"):
        cond["If-Modified-Since"] = hdr["Last-Modified"]
    if cond and st == 200:
        time.sleep(WAIT)
        st2, _, _, b2 = req(url, cond)
        rec["conditional_get_status"] = st2
        rec["conditional_get_bytes"] = len(b2)
    else:
        rec["conditional_get_status"] = None
    # 2回目の通常 GET（本文が毎回変わるか）
    if st == 200:
        time.sleep(WAIT)
        st3, _, _, b3 = req(url)
        rec["second_get_status"] = st3
        rec["second_get_same_sha256"] = hashlib.sha256(b3).hexdigest() == sha
    return rec


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R3_monitor_probe"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "R3_monitor_probe"
    out.mkdir(parents=True, exist_ok=True)
    results = []
    for i, (cid, org, kind, url) in enumerate(CANDIDATES):
        if i:
            time.sleep(WAIT)
        try:
            rec = probe(cid, org, kind, url, dl)
        except Exception as e:  # noqa: BLE001
            rec = {"id": cid, "org": org, "expected": kind, "url": url, "error": repr(e)}
        results.append(rec)
        print(json.dumps({k: rec.get(k) for k in ("id", "status", "soft_404", "is_feed_like", "feed_items",
                                                    "conditional_get_status", "second_get_same_sha256", "error")},
                         ensure_ascii=False), flush=True)
    meta = {"run_at_local": ts, "user_agent": UA, "python": sys.version, "results": results}
    (out / f"probe_{ts}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [f"# R3_monitor_probe {ts}", "",
             "| id | 機関 | status | soft404 | feed | items | 最新日付(今日以前) | Last-Modified | ETag | 304 | 2回目同一 |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        lines.append("| {id} | {org} | {st} | {s4} | {fd} | {it} | {nw} | {lm} | {et} | {c} | {same} |".format(
            id=r["id"], org=r["org"], st=r.get("status", r.get("error", "")), s4=r.get("soft_404"),
            fd=r.get("is_feed_like"), it=r.get("feed_items", ""),
            nw=r.get("feed_newest_date") or r.get("html_newest_past_date") or "",
            lm="有" if r.get("last_modified") else "無", et="有" if r.get("etag") else "無",
            c=r.get("conditional_get_status"), same=r.get("second_get_same_sha256")))
    (out / f"summary_{ts}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

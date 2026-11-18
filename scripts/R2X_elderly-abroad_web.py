"""R2X elderly-abroad: 老人扶養・同居老親等、国外居住親族、健保の被扶養者（60歳以上・国内居住要件）について、
国税庁・厚生労働省・日本年金機構・協会けんぽの公開資料（HTML・PDF）を取得し、取得記録と HTML のテキストを残す。

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_elderly-abroad_web.py <set> [<set> ...]
  ... scripts/R2X_elderly-abroad_web.py --list

- 取得したファイルは信頼できないデータ。セットごと・実行ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_R2X_elderly-abroad_<set>/ に置く（その中では何も実行しない）。
- 取得記録（ステータス、Content-Type、Last-Modified、SHA-256、バイト数、タイトル、キーワードを含む行）は
  scripts/results/R2X_elderly-abroad_web/<set>_<ts>.json に書く。
- HTML から抜き出したテキストとリンクは scripts/results/R2X_elderly-abroad_web/text/<set>_<ts>/<id>.txt・<id>.links.json に書く
  （docs の引用を後で照合できるように）。
- PDF は中身を解析しない（標準ライブラリで日本語の本文を確実に取り出せないため）。PDF は人が読んで docs に書き、
  ここではファイルの同一性（SHA-256・サイズ・Last-Modified）だけを記録する。
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。個人の情報は送らない。官報は取得しない。
- 標準ライブラリのみ（Python 3.11）。scripts/IMPL_misc_fetch.py のコードを写して作った（import はしない）。
"""
import hashlib
import html.parser
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
WAIT = 1.5
NTA = "https://www.nta.go.jp"
NAME = "R2X_elderly-abroad"


def tdoc(data_id):
    return f"https://www.mhlw.go.jp/web/t_doc?dataId={data_id}&dataType=1&pageNo=1"


SETS = {
    "robots": {
        "nta_robots": f"{NTA}/robots.txt",
        "mhlw_robots": "https://www.mhlw.go.jp/robots.txt",
        "nenkin_robots": "https://www.nenkin.go.jp/robots.txt",
        "kyoukai_robots": "https://www.kyoukaikenpo.or.jp/robots.txt",
    },
    # 老人扶養親族・同居老親等（国税庁）
    "elderly": {
        "ta_1180": f"{NTA}/taxes/shiraberu/taxanswer/shotoku/1180.htm",
        "ta_1180_qa": f"{NTA}/taxes/shiraberu/taxanswer/shotoku/1180_qa.htm",
        "ta_1182": f"{NTA}/taxes/shiraberu/taxanswer/shotoku/1182.htm",
        "shitsugi_shotoku_05_32": f"{NTA}/law/shitsugi/shotoku/05/32.htm",
        "tebiki2025_yogo_y11": f"{NTA}/taxes/shiraberu/shinkoku/tebiki/2025/03/order3/yogo/3-3_y11.htm",
        "tebiki2025_yogo_y12": f"{NTA}/taxes/shiraberu/shinkoku/tebiki/2025/03/order3/yogo/3-3_y12.htm",
        "tebiki2025_3_3_27": f"{NTA}/taxes/shiraberu/shinkoku/tebiki/2025/03/order3/3-3_27.htm",
        "sochiho_tsutatsu_toc": f"{NTA}/law/tsutatsu/kobetsu/shotoku/sochiho/801226/sinkoku/01.htm",
        "kihon_tsutatsu_2_1": f"{NTA}/law/tsutatsu/kihon/shotoku/01/01.htm",
        "kihon_tsutatsu_2_47": f"{NTA}/law/tsutatsu/kihon/shotoku/01/07.htm",
        "nencho2026_105": f"{NTA}/publication/pamph/gensen/nencho2026/pdf/105.pdf",
        "nencho2025_105": f"{NTA}/publication/pamph/gensen/nencho2025/pdf/105.pdf",
    },
    # 国外居住親族（国税庁）
    "abroad": {
        "kokugai_index": f"{NTA}/taxes/tetsuzuki/shinsei/annai/gensen/kokugai/index.htm",
        "kokugai_sokin": f"{NTA}/taxes/tetsuzuki/shinsei/annai/gensen/kokugai/sokin/index.htm",
        "kokugai_qa_pdf": f"{NTA}/publication/pamph/pdf/0022009-107_02.pdf",
        "kokugai_leaf_pdf": f"{NTA}/publication/pamph/pdf/0022009-107_01.pdf",
        "r2kaisei_pdf": f"{NTA}/publication/pamph/shotoku/r2kaisei.pdf",
    },
    # 健康保険の被扶養者：60歳以上の基準、国内居住要件
    "kenpo": {
        "S52_tsuchi": tdoc("00tb0189"),
        "R01_kokunai": tdoc("00tc4995"),
        "R05_kokunai_kaisei": tdoc("00tc7769"),
        "nenkin_kyojuyoken": "https://www.nenkin.go.jp/service/kounen/tekiyo/hihokensha1/kyojuyoken.html",
        "nenkin_20200324": "https://www.nenkin.go.jp/oshirase/taisetu/2020/202003/20200324.html",
        "nenkin_20141202": "https://www.nenkin.go.jp/service/kounen/tekiyo/hihokensha1/20141202.html",
        "kyoukai_guide2607": "https://www.kyoukaikenpo.or.jp/assets/n_fuyouidou_guide2607.pdf",
        "kyoukai_faq_dependent": "https://www.kyoukaikenpo.or.jp/faq/dependent_status/",
    },
}

PATTERNS = {
    "dokyo": r"同居|入院|老人ホーム|起居|居所",
    "abroad": r"国外居住|非居住|親族関係書類|送金関係書類|留学ビザ|38万円送金|３８万円送金|送金",
    "age": r"70歳|７０歳|60歳|６０歳|30歳|３０歳|180万|１８０万|百八十万",
    "kokunai": r"国内居住|国内に住所|住民票|住民登録|生活の基礎|留学|同行|特定活動",
    "sochi": r"41の16|４１の16|41条の16|第四十一条の十六|同居老親",
}


class Extract(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.links, self.title = [], [], ""
        self._skip = 0
        self._in_title = False
        self._href = None
        self._atext = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "img" and a.get("alt") and not self._skip:
            # 国税庁のページでは一部の字が画像（alt 付き）で表示される。alt を ⟨⟩ で囲んで残す。
            self.parts.append("⟨" + a["alt"] + "⟩")
            if self._href is not None:
                self._atext.append("⟨" + a["alt"] + "⟩")
        if tag == "a" and a.get("href"):
            self._href = a["href"]
            self._atext = []
        if tag in ("br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "dt", "dd", "table"):
            self.parts.append("\n")
        if tag in ("td", "th"):
            self.parts.append(" | ")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False
        if tag == "a" and self._href is not None:
            self.links.append({"href": self._href, "text": " ".join("".join(self._atext).split())})
            self._href = None
        if tag in ("p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "dd"):
            self.parts.append("\n")

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.title += data
        if self._href is not None:
            self._atext.append(data)
        self.parts.append(data)

    def text(self):
        t = "".join(self.parts)
        t = re.sub(r"[ \t　]+\n", "\n", t)
        t = re.sub(r"\n{3,}", "\n\n", t)
        return t.strip()


def read_with_deadline(resp, seconds=120):
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
    cs = None
    m = re.search(r"charset=([\w\-]+)", ctype or "", re.I)
    if m:
        cs = m.group(1)
    if not cs:
        m = re.search(rb"<meta[^>]+charset=[\"']?([\w\-]+)", body[:4000], re.I)
        if m:
            cs = m.group(1).decode("ascii", "replace")
    for c in [cs, "utf-8", "cp932", "euc-jp"]:
        if not c:
            continue
        if c.lower() in ("shift_jis", "shift-jis", "sjis", "x-sjis"):
            c = "cp932"
        try:
            return body.decode(c), c
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", "replace"), "utf-8(replace)"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.geturl(), dict(r.headers), read_with_deadline(r)
    except urllib.error.HTTPError as e:
        return e.code, url, dict(e.headers or {}), e.read() if hasattr(e, "read") else b""


def ext_for(ctype, url):
    c = (ctype or "").lower()
    if "pdf" in c or url.lower().endswith(".pdf"):
        return ".pdf"
    if "html" in c:
        return ".html"
    if url.lower().endswith(".txt") or "text/plain" in c:
        return ".txt"
    return ".bin"


def matched_lines(text):
    res = {}
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for name, pat in PATTERNS.items():
        hits = []
        for i, ln in enumerate(lines):
            if re.search(pat, ln):
                hits.append({"line_no": i + 1, "text": ln[:400]})
        res[name] = hits[:200]
    return res


def run_set(name, urls, ts):
    dl = ROOT / ".work" / "downloads" / f"{ts}_{NAME}_{name}"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / f"{NAME}_web"
    out.mkdir(parents=True, exist_ok=True)
    tx = out / "text" / f"{name}_{ts}"
    tx.mkdir(parents=True, exist_ok=False)
    log = []

    def dump():
        (out / f"{name}_{ts}.json").write_text(
            json.dumps({"set": name, "fetched_at_local": ts, "user_agent": UA, "download_dir": str(dl.relative_to(ROOT)),
                        "text_dir": str(tx.relative_to(ROOT)), "results": log}, ensure_ascii=False, indent=2),
            encoding="utf-8")

    for i, (sid, url) in enumerate(urls.items()):
        if i:
            time.sleep(WAIT)
        rec = {"id": sid, "url": url}
        try:
            st, final, hdr, body = get(url)
            ctype = hdr.get("Content-Type", "")
            ext = ext_for(ctype, final)
            (dl / f"{sid}{ext}").write_bytes(body)
            rec.update({
                "status": st, "final_url": final, "content_type": ctype, "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "last_modified": hdr.get("Last-Modified"), "etag": hdr.get("ETag"),
                "saved": str((dl / f"{sid}{ext}").relative_to(ROOT)),
            })
            if ext == ".txt" and body:
                s, cs = decode(body, ctype)
                rec["text_body"] = s[:4000]
            if ext == ".html" and body:
                s, cs = decode(body, ctype)
                p = Extract()
                p.feed(s)
                links = []
                for lk in p.links:
                    h = lk["href"]
                    if h and not h.startswith(("javascript:", "mailto:", "#")):
                        links.append({"href": urllib.parse.urljoin(final, h), "text": lk["text"]})
                text = p.text()
                (tx / f"{sid}.txt").write_text(text, encoding="utf-8")
                (tx / f"{sid}.links.json").write_text(json.dumps(links, ensure_ascii=False, indent=1), encoding="utf-8")
                rec.update({"charset": cs, "title": " ".join(p.title.split()), "text_chars": len(text),
                            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                            "text": str((tx / f"{sid}.txt").relative_to(ROOT)), "n_links": len(links),
                            "matches": matched_lines(text),
                            "pdf_links": [lk for lk in links if lk["href"].lower().endswith(".pdf")][:80]})
        except Exception as e:  # noqa: BLE001
            rec["error"] = repr(e)
        log.append(rec)
        dump()
        print(json.dumps({k: rec.get(k) for k in ("id", "status", "bytes", "title", "last_modified", "error")}, ensure_ascii=False), flush=True)
    dump()


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")
    if not argv or argv[0] == "--list":
        for k, v in SETS.items():
            print(k, len(v))
        return 0
    ts = time.strftime("%Y%m%d-%H%M%S")
    for i, name in enumerate(argv):
        if i:
            time.sleep(WAIT)
        run_set(name, SETS[name], ts)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

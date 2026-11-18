"""IMPL_misc: 実装前の追加調査（年齢の判定・親族の範囲・扶養の所属・源泉徴収の区分）のために、
国税庁などの公開資料（HTML・PDF）を取得し、取得記録（ステータス、ヘッダ、SHA-256、タイトル）と、
HTML から抜き出した「生年月日の範囲」「親族の範囲」などの該当行を残す。

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_misc_fetch.py <set> [<set> ...]
  ... scripts/IMPL_misc_fetch.py --list

- 取得したファイルは信頼できないデータ。セットごと・実行ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_IMPL_misc_<set>/ に置く（その中では何も実行しない）。
- HTML から抜き出したテキストとリンクは、別の新しいディレクトリ .work/text/<ts>_IMPL_misc_<set>/ に置く。
- 取得記録と該当行は scripts/results/IMPL_misc_fetch/<set>_<ts>.json に書く。
- PDF は中身を解析しない（標準ライブラリで日本語の本文を確実に取り出せないため）。PDF の内容は人が読んで
  docs に書き、ここではファイルの同一性（SHA-256・サイズ・Last-Modified）だけを記録する。
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。個人の情報は送らない。
- 標準ライブラリのみ（Python 3.11）。R3_fetch.py のコードを写して作った（import はしない）。
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

SETS = {
    # 取得先のサイトの robots.txt（巡回の可否の確認）
    "robots": {
        "nta_robots": f"{NTA}/robots.txt",
        "courts_robots": "https://www.courts.go.jp/robots.txt",
        "egov_robots": "https://laws.e-gov.go.jp/robots.txt",
    },
    # 1. 生年月日の範囲：扶養控除等申告書（令和7年分・令和8年分）、確定申告の手引きの用語、年末調整のしかた
    "birth": {
        "form_r07_fuyo": f"{NTA}/taxes/tetsuzuki/shinsei/annai/gensen/pdf/2025bun_01.pdf",
        "form_r07_fuyo_1": f"{NTA}/taxes/tetsuzuki/shinsei/annai/gensen/pdf/2025bun_01-1.pdf",
        "form_r07_fuyo_kisai": f"{NTA}/taxes/tetsuzuki/shinsei/annai/gensen/pdf/2025bun_02.pdf",
        "form_r08_fuyo": f"{NTA}/taxes/tetsuzuki/shinsei/annai/gensen/pdf/2026bun_01.pdf",
        "form_r08_fuyo_kisai": f"{NTA}/taxes/tetsuzuki/shinsei/annai/gensen/pdf/2026bun_02.pdf",
        "form_page_1648_01": f"{NTA}/taxes/tetsuzuki/shinsei/annai/gensen/annai/1648_01.htm",
        "form_page_1648_73": f"{NTA}/taxes/tetsuzuki/shinsei/annai/gensen/annai/1648_73.htm",
        "shinkokusyo_index": f"{NTA}/users/gensen/nencho/shinkokusyo/index.htm",
        "tebiki2025_yogo_y13": f"{NTA}/taxes/shiraberu/shinkoku/tebiki/2025/03/order3/yogo/3-3_y13.htm",
        "nencho2026_105": f"{NTA}/publication/pamph/gensen/nencho2026/pdf/105.pdf",
        "nencho2025_105": f"{NTA}/publication/pamph/gensen/nencho2025/pdf/105.pdf",
        "nencho2026_304": f"{NTA}/publication/pamph/gensen/nencho2026/pdf/304.pdf",
    },
    # 2. 「親族」の範囲：タックスアンサー、用語集、国外居住親族の Q&A
    "kinship": {
        "ta_1180": f"{NTA}/taxes/shiraberu/taxanswer/shotoku/1180.htm",
        "ta_1180_qa": f"{NTA}/taxes/shiraberu/taxanswer/shotoku/1180_qa.htm",
        "ta_yogo_senmon": f"{NTA}/taxes/shiraberu/taxanswer/yogo/senmon.htm",
        "kokugai_index": f"{NTA}/taxes/tetsuzuki/shinsei/annai/gensen/kokugai/index.htm",
        "kokugai_qa_pdf": f"{NTA}/publication/pamph/pdf/0022009-107_02.pdf",
        "kokugai_leaf_pdf": f"{NTA}/publication/pamph/pdf/0022009-107_01.pdf",
    },
    # 2. 裁判例（裁判所の裁判例検索の詳細ページ。robots.txt を確認してから取得する）
    "courts": {
        "hanrei_62674": "https://www.courts.go.jp/hanrei/62674/detail2/index.html",
    },
    # 5. 源泉徴収の区分（甲欄・乙欄・丙欄）と扶養控除等申告書
    "gensen": {
        "ta_2511": f"{NTA}/taxes/shiraberu/taxanswer/gensen/2511.htm",
        "ta_2514": f"{NTA}/taxes/shiraberu/taxanswer/gensen/2514.htm",
        "ta_2520": f"{NTA}/taxes/shiraberu/taxanswer/gensen/2520.htm",
        "ta_1900": f"{NTA}/taxes/shiraberu/taxanswer/shotoku/1900.htm",
        "ta_1177": f"{NTA}/taxes/shiraberu/taxanswer/shotoku/1177.htm",
        "zeigakuhyo2026_all": f"{NTA}/publication/pamph/gensen/zeigakuhyo2026/data/all.pdf",
        "nencho2026_103": f"{NTA}/publication/pamph/gensen/nencho2026/pdf/103.pdf",
    },
    # 1回目の取得で見つけたリンクの追跡：特定親族の説明（年末調整のしかた 106）、特定親族特別控除申告書、
    # 判決の全文、質疑応答事例（親族の範囲・扶養親族等の所属）
    "followup": {
        "nencho2026_106": f"{NTA}/publication/pamph/gensen/nencho2026/pdf/106.pdf",
        "nencho2025_106": f"{NTA}/publication/pamph/gensen/nencho2025/pdf/106.pdf",
        "form_r08_kiso_tokutei": f"{NTA}/taxes/tetsuzuki/shinsei/annai/gensen/pdf/2026bun_06.pdf",
        "form_r07_kiso_tokutei": f"{NTA}/taxes/tetsuzuki/shinsei/annai/gensen/pdf/2025bun_06.pdf",
        "hanrei_62674_pdf": "https://www.courts.go.jp/assets/hanrei/hanrei-pdf-62674.pdf",
        "shitsugi_shotoku_05_64": f"{NTA}/law/shitsugi/shotoku/05/64.htm",
        "shitsugi_shotoku_05_67": f"{NTA}/law/shitsugi/shotoku/05/67.htm",
        "shitsugi_gensen_03_09": f"{NTA}/law/shitsugi/gensen/03/09.htm",
        "tebiki2026_yogo_y13": f"{NTA}/taxes/shiraberu/shinkoku/tebiki/2026/03/order3/yogo/3-3_y13.htm",
    },
    # 5. 源泉徴収票に「乙欄」「年末調整の有無」がどう書かれるか（法定調書の作成と提出の手引 第2章 給与所得の源泉徴収票）
    "hotei": {
        "hotei_tebiki2026_02": f"{NTA}/publication/pamph/hotei/tebiki2026/PDF/02.pdf",
        "hotei_tebiki2025_02": f"{NTA}/publication/pamph/hotei/tebiki2025/PDF/02.pdf",
        "hotei_page_23100051": f"{NTA}/taxes/tetsuzuki/shinsei/annai/hotei/23100051.htm",
    },
    # 源泉徴収票の様式そのもの（受給者交付用）と記載要領（令和8年分）。「乙欄」の欄の有無を見る
    "hotei_form": {
        "chousho_r08_jukyusha": f"{NTA}/taxes/tetsuzuki/shinsei/annai/hotei/pdf/r08/0026009-129.pdf",
        "chousho_r08_kisai": f"{NTA}/taxes/tetsuzuki/shinsei/annai/hotei/pdf/r08/kisai_chousho01.pdf",
    },
    # 確定申告の手引き（令和7年分）の用語のページ（3-3_y01〜y20）。生年月日の範囲の記載を拾う
    "tebiki_yogo": {f"tebiki2025_yogo_y{n:02d}": f"{NTA}/taxes/shiraberu/shinkoku/tebiki/2025/03/order3/yogo/3-3_y{n:02d}.htm"
                    for n in range(1, 21) if n != 13},
}

# HTML のテキストから拾う行（生年月日の範囲、親族の範囲、源泉徴収の区分）
PATTERNS = {
    "birth_range": r"(?:明治|大正|昭和|平成|令和|[昭平令])\s*[\d０-９元]+\s*[年\.．]\s*[\d０-９]+\s*[月\.．]\s*[\d０-９]+\s*日?\s*(?:以前|以後|生|から|～|〜|まで)",
    "kinship": r"親等|血族|姻族|民法",
    "kou_otsu": r"甲欄|乙欄|丙欄|扶養控除等(?:（異動）)?申告書を提出",
    "age_rule": r"12月31日|十二月三十一日|１月１日生|1月1日生|誕生日の前日",
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
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL_misc_{name}"
    dl.mkdir(parents=True, exist_ok=False)
    tx = ROOT / ".work" / "text" / f"{ts}_IMPL_misc_{name}"
    tx.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "IMPL_misc_fetch"
    out.mkdir(parents=True, exist_ok=True)
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
                            "text": str((tx / f"{sid}.txt").relative_to(ROOT)), "n_links": len(links),
                            "matches": matched_lines(text),
                            "pdf_links": [lk for lk in links if lk["href"].lower().endswith(".pdf")][:80]})
        except Exception as e:  # noqa: BLE001
            rec["error"] = repr(e)
        log.append(rec)
        dump()
        print(json.dumps({k: rec.get(k) for k in ("id", "status", "bytes", "title", "error")}, ensure_ascii=False), flush=True)
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

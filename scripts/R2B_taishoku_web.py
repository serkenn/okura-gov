"""R2B taishoku: 退職所得（所得税・住民税・扶養の判定・健保の被扶養者）の行政の案内（国税庁のタックスアンサー・質疑応答事例・
様式、確定申告書等作成コーナーのよくある質問、総務省の案内、保険者の資料）を取得し、取得記録とテキストを残す。

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_taishoku_web.py <set名> [<set名> ...]
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_taishoku_web.py --list
- 取得したファイルは信頼できないデータとして、取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_R2B_taishoku_<set>/ に置く（その中でインタプリタやツールを実行しない）。
- HTML から抽出したテキストとリンクは scripts/results/R2B_taishoku_web/text/<set>_<ts>/ に置く（PDF は抽出しない。Read ツールで読む）。
- 取得記録（ステータス、最終URL、Content-Type、Last-Modified、ETag、SHA-256、タイトル）は scripts/results/R2B_taishoku_web/<set>_<ts>.json に書く。
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。個人の情報は送らない。官報は取得しない。
標準ライブラリのみ（Python 3.11）。scripts/R2X_jinteki_web.py のコードを写して作った（import はしていない）。
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
OUT = ROOT / "scripts" / "results" / "R2B_taishoku_web"

TA = "https://www.nta.go.jp/taxes/shiraberu/taxanswer/"
KEISAN = "https://www.keisan.nta.go.jp/"
SETS = {
    # 国税庁 タックスアンサー（退職所得・退職手当等の源泉徴収、扶養の判定、用語集）
    "nta_ta": {
        "ta_1420": TA + "shotoku/1420.htm",        # 退職金を受け取ったとき（退職所得）
        "ta_2725": TA + "gensen/2725.htm",         # 退職所得となるもの
        "ta_2732": TA + "gensen/2732.htm",         # 退職手当等に対する源泉徴収
        "ta_2732_besshi": TA + "gensen/2732_besshi.htm",  # 退職所得の源泉徴収税額の速算表
        "ta_2735": TA + "gensen/2735.htm",         # 同じ年に2か所以上から退職手当等が支払われるとき
        "ta_2736": TA + "gensen/2736.htm",         # 解雇予告手当や未払賃金立替払
        "ta_2741": TA + "gensen/2741.htm",         # 一般・短期・特定役員退職手当等がある場合
        "ta_1180": TA + "shotoku/1180.htm",        # 扶養控除
        "ta_1191": TA + "shotoku/1191.htm",        # 配偶者控除
        "ta_1195": TA + "shotoku/1195.htm",        # 配偶者特別控除
        "ta_yogo_senmon": TA + "yogo/senmon.htm",  # 専門用語集（合計所得金額・総所得金額等）
    },
    # 国税庁 手続の案内・質疑応答事例・通達の目次・申告書の一覧
    "nta_misc": {
        "tetsuzuki_1648_37": "https://www.nta.go.jp/taxes/tetsuzuki/shinsei/annai/gensen/annai/1648_37.htm",  # 退職所得の受給に関する申告
        "shitsugi_shotoku_05_85": "https://www.nta.go.jp/law/shitsugi/shotoku/05/85.htm",  # 退職所得がある場合の配偶者特別控除
        "shitsugi_gensen_04_06": "https://www.nta.go.jp/law/shitsugi/gensen/04/06.htm",    # 申告書に支払済の退職手当を記載しないで提出
        "kihon_shotoku_toc": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/01.htm",     # 所得税基本通達の目次
        "nencho_shinkokusyo": "https://www.nta.go.jp/users/gensen/nencho/shinkokusyo/index.htm",  # 各種申告書・記載例
    },
    # 国税庁 PDF（扶養控除等申告書の令和7年分・令和8年分、その記載のしかた、源泉所得税の改正のあらまし）
    "nta_pdf": {
        "fuyo_2025bun_01": "https://www.nta.go.jp/taxes/tetsuzuki/shinsei/annai/gensen/pdf/2025bun_01.pdf",
        "fuyo_2026bun_01": "https://www.nta.go.jp/taxes/tetsuzuki/shinsei/annai/gensen/pdf/2026bun_01.pdf",
        "fuyo_2025bun_02": "https://www.nta.go.jp/taxes/tetsuzuki/shinsei/annai/gensen/pdf/2025bun_02.pdf",
        "fuyo_2026bun_02": "https://www.nta.go.jp/taxes/tetsuzuki/shinsei/annai/gensen/pdf/2026bun_02.pdf",
        "aramashi2026_01": "https://www.nta.go.jp/publication/pamph/gensen/aramashi2026/pdf/01.pdf",
    },
    # 確定申告書等作成コーナー よくある質問（令和7年分・令和5年分）。計算のコードは取得しない（D16）
    "keisan": {
        "keisan_robots": KEISAN + "robots.txt",
        "r7_cat21c_index": KEISAN + "r7yokuaru/cat2/cat21/cat21c/index.html",          # 退職所得等
        "r7sp_scid1559": KEISAN + "r7yokuaru_sp/cat2/cat21/cat21c/scid1559.html",       # 退職所得に係る所得税
        "r7_cid458": KEISAN + "r7yokuaru/cat2/cat21/cat21e/cid458.html",                # 退職金の収入がある場合
        "r7sp_scid1322": KEISAN + "r7yokuaru_sp/socat2/socat23/scid1322.html",          # 退職所得（源泉徴収されたもの）を除く所得金額
        "r7_ocat241_index": KEISAN + "r7yokuaru/ocat2/ocat24/ocat241/index.html",       # 住民税に関する事項（一覧）
        "r5_cid647": KEISAN + "r5yokuaru/ocat2/ocat24/ocat241/cid647.html",             # 退職所得のある配偶者・親族がいる方の入力項目
    },
    # 1回目の取得のリンクから辿ったもの（作成コーナー令和7年分の cid647、所得税基本通達 法第30条関係・法第203条関係、
    # 令和8年分扶養控除等申告書の記載例、タックスアンサー 2728・2737・2740）
    "followup": {
        "r7_cid647": KEISAN + "r7yokuaru/ocat2/ocat24/ocat241/cid647.html",
        "kihon_04_04": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/04/04.htm",
        "kihon_34_01": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/34/01.htm",
        "nencho2026_305": "https://www.nta.go.jp/publication/pamph/gensen/nencho2026/pdf/305.pdf",
        "ta_2728": TA + "gensen/2728.htm",
        "ta_2737": TA + "gensen/2737.htm",
        "ta_2740": TA + "gensen/2740.htm",
    },
    # 総務省の案内
    "soumu": {
        "soumu_65871": "https://www.soumu.go.jp/main_sosiki/jichi_zeisei/czaisei/65871.html",  # 平成25年1月1日以降の退職所得に対する住民税の特別徴収
    },
    # 総務省の特別徴収税額早見表（平成25年1月1日以降の分。soumu_65871 のリンクから）
    "soumu_pdf": {
        "soumu_hayami_h25": "https://www.soumu.go.jp/main_content/000189437.pdf",
    },
    # 保険者の資料（被扶養者の年間収入に退職金を含めるか）
    "hokensha": {
        "chikyosai_osaka_2023": "https://osaka.chikyosai.or.jp/files/kaiin/hifuyousya_gendogaku_2023.pdf?230331",
    },
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


def read_with_deadline(resp, seconds=90):
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
    path = urllib.parse.urlparse(url).path.lower()
    if "pdf" in c or path.endswith(".pdf"):
        return ".pdf"
    if "html" in c:
        return ".html"
    if "text/plain" in c:
        return ".txt"
    return ".bin"


def run_set(name, urls, ts):
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2B_taishoku_{name}"
    dl.mkdir(parents=True, exist_ok=False)
    tx = OUT / "text" / f"{name}_{ts}"
    tx.mkdir(parents=True, exist_ok=False)
    log = []
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
            if ext in (".html", ".txt") and body:
                s, cs = decode(body, ctype)
                if ext == ".html":
                    p = Extract()
                    p.feed(s)
                    links = []
                    for lk in p.links:
                        h = lk["href"]
                        if h and not h.startswith(("javascript:", "mailto:", "#")):
                            links.append({"href": urllib.parse.urljoin(final, h), "text": lk["text"]})
                    text, title = p.text(), " ".join(p.title.split())
                    (tx / f"{sid}.links.json").write_text(json.dumps(links, ensure_ascii=False, indent=1), encoding="utf-8")
                    rec["n_links"] = len(links)
                else:
                    text, title = s, ""
                (tx / f"{sid}.txt").write_text(text, encoding="utf-8")
                rec.update({"charset": cs, "title": title, "text_chars": len(text),
                            "text": str((tx / f"{sid}.txt").relative_to(ROOT))})
        except Exception as e:  # noqa: BLE001
            rec["error"] = repr(e)
        log.append(rec)
        (OUT / f"{name}_{ts}.json").write_text(
            json.dumps({"set": name, "fetched_at_local": ts, "user_agent": UA, "download_dir": str(dl.relative_to(ROOT)),
                        "results": log}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        print(json.dumps({k: rec.get(k) for k in ("id", "status", "bytes", "title", "last_modified", "error")}, ensure_ascii=False))


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")
    if not argv or argv[0] == "--list":
        for k, v in SETS.items():
            print(k, len(v))
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    for i, name in enumerate(argv):
        if i:
            time.sleep(WAIT)
        ts = time.strftime("%Y%m%d-%H%M%S")
        run_set(name, SETS[name], ts)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

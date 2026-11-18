r"""R2B_nenkin: 公的年金等の雑所得（老齢・障害・遺族年金）について、国税庁（タックスアンサー・所得税基本通達・パンフレット）、
日本年金機構、地方公共団体の案内を取得し、取得記録を残す。

実行（Windows）:
  C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe -I -X utf8 scripts/R2B_nenkin_web.py <set名> [<set名> ...]
  C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe -I -X utf8 scripts/R2B_nenkin_web.py --list
- 取得したファイルは信頼できないデータとして、取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_R2B_nenkin_<set>/ に置く（その中でインタプリタやツールを実行しない）。
- HTML から抽出したテキストとリンクは、別の新しいディレクトリ .work/text/<ts>_R2B_nenkin_<set>/ に置く。
- 取得記録（ステータス、Last-Modified、ETag、SHA-256、タイトル）は scripts/results/R2B_nenkin_web/<set>_<ts>.json に書く。
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
OUT = ROOT / "scripts" / "results" / "R2B_nenkin_web"

TA = "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/"
KIHON = "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/"
SETS = {
    # 国税庁 タックスアンサー（公的年金等の課税関係、遺族年金、雑所得、非課税所得、扶養控除の Q&A）と分野別の索引
    "nta_ta": {
        "ta_1600": TA + "1600.htm",   # 公的年金等の課税関係
        "ta_1605": TA + "1605.htm",   # 遺族の方に支給される公的年金等
        "ta_1500": TA + "1500.htm",   # 雑所得
        "ta_2011": TA + "2011.htm",   # 課税される所得と非課税所得
        "ta_1180_qa": TA + "1180_qa.htm",  # 扶養控除の Q&A
        "ta_bunya_nenkin": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/code/bunya-taisyoku-nenkin.htm",
    },
    # 所得税基本通達（法9条1項3号関係、法35条関係、法36条関係）、国税庁「暮らしの税情報」の年金と税
    "nta_kihon": {
        "kihon_02_02": KIHON + "02/02.htm",   # 法9条 第3号関係（9-2 遺族の受ける年金の範囲 など）
        "kihon_04_09": KIHON + "04/09.htm",   # 法35条 雑所得関係
        "kihon_05_01": KIHON + "05/01.htm",   # 法36条 収入すべき時期（36-14 公的年金等）
        "kurashi_03_1": "https://www.nta.go.jp/publication/pamph/koho/kurashi/html/03_1.htm",  # 高齢者と税（年金と税）
    },
    # 日本年金機構：非課税の年金と源泉徴収票、扶養親族等申告書の所得計算での非課税所得、源泉徴収の案内
    "nenkin": {
        "nenkin_faq_gensen_05": "https://www.nenkin.go.jp/faq/jukyu/uketori/tsuchisho/gensen/20140421-05.html",
        "nenkin_faq_fuyou_hikazei": "https://www.nenkin.go.jp/section/faq/jukyu/jukyushatodoke/rourei/fuyoushinkoku/shotoku/20140421-14.html",
        "nenkin_shotokuzeikojo": "https://www.nenkin.go.jp/service/jukyu/tetsuduki/rourei/jukyu/shotokuzeikojo.html",
    },
    # TA No.1600 の「公的年金等に係る雑所得の速算表（令和2年分以後）」は画像（図1〜図3）なので、画像を取得して目で読む
    "nta_img": {
        "ta_1600_img01": TA + "img/1600_01.png",
        "ta_1600_img02": TA + "img/1600_02.png",
        "ta_1600_img03": TA + "img/1600_03.png",
    },
    # 地方公共団体：個人住民税での公的年金等控除の年齢の判定時点（二次情報 E）
    "local": {
        "tokyo_kojin_ju": "https://www.tax.metro.tokyo.lg.jp/kazei/life/kojin_ju",
        "higashiosaka_0000001683": "https://www.city.higashiosaka.lg.jp/0000001683.html",
        "yokohama_faq_answer6": "https://www.city.yokohama.lg.jp/kurashi/koseki-zei-hoken/zeikin/faq/answer6.html",
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
    """本文を少しずつ読み、全体の制限時間を超えたら打ち切る。"""
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
    if "png" in c or url.lower().endswith(".png"):
        return ".png"
    return ".bin"


def run_set(name, urls, ts):
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2B_nenkin_{name}"
    dl.mkdir(parents=True, exist_ok=False)
    tx = ROOT / ".work" / "text" / f"{ts}_R2B_nenkin_{name}"
    tx.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
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
            if ext == ".html" and body:
                s, cs = decode(body, ctype)
                p = Extract()
                p.feed(s)
                links = []
                for lk in p.links:
                    h = lk["href"]
                    if h and not h.startswith(("javascript:", "mailto:", "#")):
                        links.append({"href": urllib.parse.urljoin(final, h), "text": lk["text"]})
                (tx / f"{sid}.txt").write_text(p.text(), encoding="utf-8")
                (tx / f"{sid}.links.json").write_text(json.dumps(links, ensure_ascii=False, indent=1), encoding="utf-8")
                rec.update({"charset": cs, "title": " ".join(p.title.split()), "text_chars": len(p.text()),
                            "text": str((tx / f"{sid}.txt").relative_to(ROOT)), "n_links": len(links)})
        except Exception as e:  # noqa: BLE001
            rec["error"] = repr(e)
        log.append(rec)
        (OUT / f"{name}_{ts}.json").write_text(
            json.dumps({"set": name, "fetched_at_local": ts, "user_agent": UA, "results": log}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        print(json.dumps({k: rec.get(k) for k in ("id", "status", "bytes", "title", "error")}, ensure_ascii=False))


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

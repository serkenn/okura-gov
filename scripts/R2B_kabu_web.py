"""R2B_kabu: 株式等の譲渡所得・配当所得（申告の選択を含む）について、国税庁（タックスアンサー・通達・手引き・様式）、
総務省、健康保険の保険者の公表資料を取得し、取得記録を残す。

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_kabu_web.py <set名> [<set名> ...]
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_kabu_web.py --list
- 取得したファイルは信頼できないデータとして、取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_R2B_kabu_<set>/ に置く（その中でインタプリタやツールを実行しない）。
- HTML から抽出したテキストとリンクは scripts/results/R2B_kabu_web/text/<ts>_<set>/ に置く（後で検証に使うため）。
- 取得記録（ステータス、Last-Modified、ETag、SHA-256、タイトル）は scripts/results/R2B_kabu_web/<set>_<ts>.json に書く。
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
OUT = ROOT / "scripts" / "results" / "R2B_kabu_web"

TA = "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/"
SOCHI_SINKOKU = "https://www.nta.go.jp/law/tsutatsu/kobetsu/shotoku/sochiho/801226/sinkoku/57/"
KABUTSU = "https://www.nta.go.jp/law/tsutatsu/kobetsu/shotoku/sochiho/020624/sanrin/"
TEBIKI = "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/2025/"
SETS = {
    # 国税庁 タックスアンサー
    "nta_ta": {
        "ta_1330": TA + "1330.htm",   # 配当金を受け取ったとき（配当所得）
        "ta_1331": TA + "1331.htm",   # 上場株式等の配当等に係る申告分離課税制度
        "ta_1250": TA + "1250.htm",   # 配当控除
        "ta_1463": TA + "1463.htm",   # 株式等を譲渡したときの課税（申告分離課税）
        "ta_1474": TA + "1474.htm",   # 上場株式等に係る譲渡損失の損益通算及び繰越控除
        "ta_1476": TA + "1476.htm",   # 特定口座制度
        "yogo_senmon": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/yogo/senmon.htm",  # 専門用語集（合計所得金額・総所得金額等）
    },
    # 国税庁 租税特別措置法関係通達（申告所得税関係／株式等に係る譲渡所得等関係）
    "nta_tsutatsu": {
        "sochitsu_8_4": SOCHI_SINKOKU + "08/04.htm",
        "sochitsu_8_5": SOCHI_SINKOKU + "08/06.htm",
        "kabutsu_toc": KABUTSU + "01.htm",
        "kabutsu_37_10_11": KABUTSU + "1273/37_10-11/01.htm",
        "kabutsu_37_11": KABUTSU + "1273/37_11/01.htm",
        "kabutsu_37_11_5": KABUTSU + "1273/37_11_5/01.htm",
    },
    # 国税庁 令和7年分の確定申告の手引き・特集・記載例
    "nta_tebiki": {
        "tebiki_1_03": TEBIKI + "01/1_03.htm",   # 所得の種類と課税方法
        "tebiki_1_12": TEBIKI + "01/1_12.htm",   # 市区町村からのお知らせ
        "tebiki_y01": TEBIKI + "03/order2/yogo/3-2_y01.htm",   # 利子所得と配当所得の課税方法
        "tokushu_kabu": "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tokushu/keisubetsu/kabu-haitou-shinkoku.htm",
        "kisairei_kabu": TEBIKI + "kisairei/kabushiki/index.htm",
    },
    # 国税庁 様式（PDF）
    "nta_pdf": {
        "yoshiki_r07_02": "https://www.nta.go.jp/taxes/shiraberu/shinkoku/yoshiki/01/shinkokusho/pdf/r07/02.pdf",  # 第三表
        "joto_r07_18_2": "https://www.nta.go.jp/taxes/shiraberu/shinkoku/syotoku/pdf/r07_joto_18-2.pdf",  # 付表（損益通算・繰越控除）
    },
    # 総務省（個人住民税の金融所得課税、令和4年度改正の検討資料）
    "soumu": {
        "soumu_kinyu_r040715": "https://www.soumu.go.jp/main_content/000833994.pdf",
    },
    # 健康保険の保険者（健保組合）の公表：被扶養者の年間収入に株式の配当・譲渡を含めるか（保険者ごとの例）
    "kenpo": {
        "ntt_member_1": "https://www.nttkenpo.jp/member/outline/files/member_1.pdf",
        "topre_fuyou_jouken": "https://toprekenpo.or.jp/fuyou_jouken/",
        "ngk_family_a": "https://ngkntk-kenpo.or.jp/outline_index/family_a",
        "otsuka_qa01": "https://www.kenpo.gr.jp/opckenpo/contents/qa/qa01.html",
        "nec_fuyousha_shunyu": "https://neckenpo.or.jp/fuyousha_shunyu/",
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
    if "pdf" in c or url.lower().endswith(".pdf"):
        return ".pdf"
    if "html" in c:
        return ".html"
    return ".bin"


def run_set(name, urls, ts):
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2B_kabu_{name}"
    dl.mkdir(parents=True, exist_ok=False)
    tx = OUT / "text" / f"{ts}_{name}"
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
    OUT.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    for i, name in enumerate(argv):
        if i:
            time.sleep(WAIT)
        run_set(name, SETS[name], ts)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

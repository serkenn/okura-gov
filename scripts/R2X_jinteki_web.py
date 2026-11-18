"""R2X_jinteki: 障害者控除・寡婦控除・ひとり親控除と、健保の被扶養者（障害者 180万円）の行政の案内・通達・事務連絡を取得し、
取得記録を残す。

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_jinteki_web.py <set名> [<set名> ...]
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_jinteki_web.py --list
- 取得したファイルは信頼できないデータとして、取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_R2X_jinteki_<set>/ に置く（その中でインタプリタやツールを実行しない）。
- HTML から抽出したテキストとリンクは、別の新しいディレクトリ .work/text/<ts>_R2X_jinteki_<set>/ に置く。
- 取得記録（ステータス、Last-Modified、ETag、SHA-256、タイトル）は scripts/results/R2X_jinteki_web/<set>_<ts>.json に書く。
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。個人の情報は送らない。官報は取得しない。
標準ライブラリのみ（Python 3.11）。scripts/IMPL_kenpo_fetch.py のコードを写して作った（import はしていない）。
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
OUT = ROOT / "scripts" / "results" / "R2X_jinteki_web"

TA = "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/"
SETS = {
    # 国税庁 タックスアンサー（障害者控除・寡婦控除・ひとり親控除と、その周辺）
    "nta_ta": {
        "ta_1160": TA + "1160.htm",   # 障害者控除
        "ta_1170": TA + "1170.htm",   # 寡婦控除
        "ta_1171": TA + "1171.htm",   # ひとり親控除
        "ta_1184": TA + "1184.htm",   # 扶養家族に寝たきりの人がいるときの控除額
        "ta_1185": TA + "1185.htm",   # 市町村長等の障害者認定と介護保険法の要介護認定
        "ta_1186": TA + "1186.htm",   # 身体障害者手帳等の交付を申請中である場合
    },
    # 国税庁 タックスアンサーの Q&A と、No.1160・No.1171 から張られた質疑応答事例（nta_ta の取得後に links から追加）
    "nta_ta_qa": {
        "ta_1160_qa": TA + "1160_qa.htm",   # Q1 7級相当、Q2 療育手帳、Q3 国外の親族
        "ta_1170_qa": TA + "1170_qa.htm",   # 事業専従者である妹がいる場合の寡婦
        "ta_1171_qa": TA + "1171_qa.htm",   # 事業専従者である子、年少扶養親族とひとり親控除
        "shitsugi_05_32": "https://www.nta.go.jp/law/shitsugi/shotoku/05/32.htm",  # 「同居」の範囲（長期間入院）
        "shitsugi_gensen_03_10": "https://www.nta.go.jp/law/shitsugi/gensen/03/10.htm",  # 配偶者控除とひとり親控除の双方適用
    },
    # 国税庁 質疑応答事例と所得税基本通達
    "nta_shitsugi_kihon": {
        "shitsugi_05_31": "https://www.nta.go.jp/law/shitsugi/shotoku/05/31.htm",  # 障害者控除の適用を受けることのできる年分
        "shitsugi_05_63": "https://www.nta.go.jp/law/shitsugi/shotoku/05/63.htm",  # 福祉事務所長の認定を受けていない認知症の高齢者
        "kihon_01_07": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/01/07.htm",  # 所基通 2-38〜（障害者、寡婦・ひとり親ほか）
        "kihon_16_06": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/16/06.htm",  # 所基通 79-1〜85-2
    },
    # 国税庁 年末調整のしかた（令和7年分・令和8年分）の扶養控除等申告書の確認の章、源泉所得税の改正のあらまし
    "nta_pdf": {
        "nencho2025_105": "https://www.nta.go.jp/publication/pamph/gensen/nencho2025/pdf/105.pdf",
        "nencho2026_105": "https://www.nta.go.jp/publication/pamph/gensen/nencho2026/pdf/105.pdf",
        "gensen_2026kaisei": "https://www.nta.go.jp/publication/pamph/gensen/2026kaisei.pdf",
    },
    # 厚労省：要介護認定と障害者控除の認定（平成14年の事務連絡を掲載した会議資料）、内閣府の提案募集への厚労省の回答
    "mhlw_cao": {
        "mhlw_kaigo_020904_2_3": "https://www.mhlw.go.jp/topics/kaigo/kaigi/020904/2-3.html",
        "cao_r07_12mhlw_140": "https://www.cao.go.jp/bunken-suishin/teianbosyu/doc/r07/tb_r7fu_12mhlw_140.pdf",
    },
    # 協会けんぽ：被扶養者（異動）届の手引き（障害者 180万円の確認書類の記載があるか）
    "kyokai": {
        "kyokai_fuyouidou_guide2607": "https://www.kyoukaikenpo.or.jp/assets/n_fuyouidou_guide2607.pdf",
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
    return ".bin"


def run_set(name, urls, ts):
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_jinteki_{name}"
    dl.mkdir(parents=True, exist_ok=False)
    tx = ROOT / ".work" / "text" / f"{ts}_R2X_jinteki_{name}"
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

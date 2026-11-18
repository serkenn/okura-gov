"""R2X_spouse: 配偶者控除・配偶者特別控除、年の途中の結婚、配偶者の被扶養者・第3号被保険者の一次情報（国税庁・厚労省・日本年金機構）を取得し、取得記録を残す。

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_spouse_fetch.py <set名> [<set名> ...]
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_spouse_fetch.py --list

- scripts/IMPL_kenpo_fetch.py のコードを写して作った（import はしていない）。標準ライブラリのみ（Python 3.11）。
- 取得したファイルは信頼できないデータとして、取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_R2X_spouse_<set>/ に置く（その中でインタプリタやツールを実行しない）。
- HTML から抽出したテキストとリンクは scripts/results/R2X_spouse_fetch/text/<ts>_<set>/ に置く（後で原文の引用を照合するため）。
  PDF はテキスト化しない（Read ツールのページ指定で読む）。
- 取得記録（ステータス、最終URL、Content-Type、Last-Modified、ETag、SHA-256、タイトル）は
  scripts/results/R2X_spouse_fetch/<set>_<ts>.json に書く。
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。個人の情報は送らない。官報は取得しない。
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
OUT = ROOT / "scripts" / "results" / "R2X_spouse_fetch"


def mhlw_date_search(gengo, y, m, d, y2=None, m2=None, d2=None):
    """厚労省 法令等データベース 通知の情報詳細検索（日付指定、GET）。gengo: 3=昭和 4=平成 5=令和（R3_fetch.py の実測による）。"""
    y2, m2, d2 = y2 or y, m2 or m, d2 or d
    return ("https://www.mhlw.go.jp/web/t_itemsrch_result?type=1"
            f"&startGengo={gengo}&yearFrom={y}&monthFrom={m}&dayFrom={d}"
            f"&endGengo={gengo}&yearTo={y2}&monthTo={m2}&dayTo={d2}&shubetsu=&bango=")


def tdoc(data_id, page=1):
    return f"https://www.mhlw.go.jp/web/t_doc?dataId={data_id}&dataType=1&pageNo={page}"


NTA_TA = "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/"

SETS = {
    # 国税庁 タックスアンサー（配偶者控除・配偶者特別控除）と手続の案内
    "nta_ta": {
        "ta1191": NTA_TA + "1191.htm",
        "ta1195": NTA_TA + "1195.htm",
        "ta1180_qa": NTA_TA + "1180_qa.htm",
        "p1648_73": "https://www.nta.go.jp/taxes/tetsuzuki/shinsei/annai/gensen/annai/1648_73.htm",
        "shinkokusyo_index": "https://www.nta.go.jp/users/gensen/nencho/shinkokusyo/index.htm",
    },
    # 国税庁 タックスアンサー No.1191 の Q&A、関連する質疑応答事例（源泉所得税）、No.1190・No.2672（1回目の取得のリンクから）
    "nta_ta2": {
        "ta1191_qa": NTA_TA + "1191_qa.htm",
        "ta1190": NTA_TA + "1190.htm",
        "ta2672": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/gensen/2672.htm",
        "shitsugi_gensen_03_10": "https://www.nta.go.jp/law/shitsugi/gensen/03/10.htm",
        "shitsugi_gensen_03_11": "https://www.nta.go.jp/law/shitsugi/gensen/03/11.htm",
    },
    # 国税庁 年末調整のしかた（配偶者控除等申告書の章）・改正の Q&A・申告書の様式
    "nta_pdf": {
        "nencho2025_106": "https://www.nta.go.jp/publication/pamph/gensen/nencho2025/pdf/106.pdf",
        "nencho2026_106": "https://www.nta.go.jp/publication/pamph/gensen/nencho2026/pdf/106.pdf",
        "kiso2026_qa": "https://www.nta.go.jp/users/gensen/2026kiso/pdf/0026005-024.pdf",
        "form2026bun_06": "https://www.nta.go.jp/taxes/tetsuzuki/shinsei/annai/gensen/pdf/2026bun_06.pdf",
        "form2025bun_06": "https://www.nta.go.jp/taxes/tetsuzuki/shinsei/annai/gensen/pdf/2025bun_06.pdf",
    },
    # 厚労省 法令等データベース：国民年金の被扶養配偶者の認定基準（昭和61年3月31日 庁保発第13号）と同日・関連日の検索
    "mhlw": {
        "S61_hifuyo_haigusha_nintei": tdoc("00tb1690"),
        "srch_S610331": mhlw_date_search(3, 61, 3, 31),
        "srch_H050305": mhlw_date_search(4, 5, 3, 5),
        "srch_H050301_0331": mhlw_date_search(4, 5, 3, 1, 5, 3, 31),
        "S52_hifuyosha_nintei": tdoc("00tb0189"),
    },
    # 平成5年3月の検索結果（48件）の2・3ページ目（検索フォームの hidden の page を指定。1回目の取得の HTML で確認）
    "mhlw_pages": {
        "srch_H050301_0331_p1": mhlw_date_search(4, 5, 3, 1, 5, 3, 31) + "&page=1",
        "srch_H050301_0331_p2": mhlw_date_search(4, 5, 3, 1, 5, 3, 31) + "&page=2",
    },
    # 厚労省 国民年金第３号被保険者制度等に関する検討会（2026年9月〜）の資料一覧
    "mhlw_kentokai": {
        "kentokai1_page": "https://www.mhlw.go.jp/stf/newpage_75888.html",
        "kentokai_gijiroku": "https://www.mhlw.go.jp/stf/newpage_76904.html",
    },
    # 同 第1回（令和8年9月4日）資料2「第３号被保険者制度を巡る現状について」（議事録で「次ページに具体的な通知を添付」と説明された資料）
    "mhlw_kentokai_pdf": {
        "kentokai1_shiryo2": "https://www.mhlw.go.jp/content/12500000/001746546.pdf",
    },
    # 市区町村の住民税の配偶者（特別）控除の表（地方税法第314条の2の計算結果の照合用。二次的な確認。特定の市町村を選ぶ意味はない）
    "municipal": {
        "utsunomiya_haigusha": "https://www.city.utsunomiya.lg.jp/kurashi/zeikin/shinzei/1003621.html",
        "chuo_haigusha": "https://www.city.chuo.lg.jp/a0009/kurashi/zeikin/juuminzei/shotokukoujo/haigusya.html",
    },
    # 日本年金機構：第3号被保険者の説明・手続、被扶養者の手続（内縁の確認書類）、国内居住要件
    "nenkin": {
        "yougo_dai3": "https://www.nenkin.go.jp/service/yougo/tagyo/dai3hihokensha.html",
        "faq_dai1_dai3": "https://www.nenkin.go.jp/section/faq/kokunen/seido/kanyu/seidosetsumei/20140602-01.html",
        "kokunen_kanyu_tetsuzuki": "https://www.nenkin.go.jp/service/kokunen/kanyu/20140710-04.html",
        "hifuyo_tetsuzuki": "https://www.nenkin.go.jp/service/kounen/tekiyo/hihokensha1/20141202.html",
        "kyojuyoken": "https://www.nenkin.go.jp/service/kounen/tekiyo/hihokensha1/kyojuyoken.html",
        "kyojuyoken_20200324": "https://www.nenkin.go.jp/oshirase/taisetu/2020/202003/20200324.html",
        "kenshu_01_pdf": "https://www.nenkin.go.jp/service/riyoushabetsu/cooperator/kenshu.files/01.pdf",
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
    if "json" in c:
        return ".json"
    return ".bin"


def run_set(name, urls, ts):
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_spouse_{name}"
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
                "saved": str((dl / f"{sid}{ext}").relative_to(ROOT)).replace("\\", "/"),
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
                text = p.text()
                (tx / f"{sid}.txt").write_text(f"# source={final}\n# fetched_at={ts}\n# charset={cs}\n\n" + text, encoding="utf-8")
                (tx / f"{sid}.links.json").write_text(json.dumps(links, ensure_ascii=False, indent=1), encoding="utf-8")
                rec.update({"charset": cs, "title": " ".join(p.title.split()), "text_chars": len(text),
                            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                            "text": str((tx / f"{sid}.txt").relative_to(ROOT)).replace("\\", "/"), "n_links": len(links)})
        except Exception as e:  # noqa: BLE001
            rec["error"] = repr(e)
        log.append(rec)
        (OUT / f"{name}_{ts}.json").write_text(
            json.dumps({"set": name, "fetched_at_local": ts, "user_agent": UA, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"),
                        "results": log}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        print(json.dumps({k: rec.get(k) for k in ("id", "status", "bytes", "last_modified", "title", "error")}, ensure_ascii=False), flush=True)


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

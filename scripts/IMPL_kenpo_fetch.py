"""IMPL_kenpo: 健康保険の被扶養者認定の実務（年収の定義・同一世帯・共働き・重複）の一次情報を取得し、取得記録を残す。

実行: python -I -X utf8 scripts/IMPL_kenpo_fetch.py <set名> [<set名> ...]
      python -I -X utf8 scripts/IMPL_kenpo_fetch.py --list
- 取得したファイルは信頼できないデータとして、取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_IMPL_kenpo_<set>/ に置く（その中でインタプリタやツールを実行しない）。
- HTML から抽出したテキストとリンクは、別の新しいディレクトリ .work/text/<ts>_IMPL_kenpo_<set>/ に置く。
- 取得記録（ステータス、Last-Modified、ETag、SHA-256、タイトル）は scripts/results/IMPL_kenpo_fetch/<set>_<ts>.json に書く。
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。個人の情報は送らない。
- 官報は取得しない（robots.txt で号ごとのページの巡回が禁止されているため）。
標準ライブラリのみ（Python 3.11）。scripts/R3_fetch.py のコードを写して作った（import はしていない）。
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
OUT = ROOT / "scripts" / "results" / "IMPL_kenpo_fetch"


def mhlw_date_search(gengo, y, m, d, y2=None, m2=None, d2=None):
    """厚労省 法令等データベース 通知の情報詳細検索（日付指定、GET）。gengo: 3=昭和 4=平成 5=令和（R3_fetch.py の実測による）。"""
    y2, m2, d2 = y2 or y, m2 or m, d2 or d
    return ("https://www.mhlw.go.jp/web/t_itemsrch_result?type=1"
            f"&startGengo={gengo}&yearFrom={y}&monthFrom={m}&dayFrom={d}"
            f"&endGengo={gengo}&yearTo={y2}&monthTo={m2}&dayTo={d2}&shubetsu=&bango=")


def tdoc(data_id):
    return f"https://www.mhlw.go.jp/web/t_doc?dataId={data_id}&dataType=1&pageNo=1"


# id -> url。id はファイル名に使う。
SETS = {
    # 厚労省 法令等データベース：日付検索（夫婦共同扶養、国内居住要件、同一世帯の確認、Q&A 第2版の候補日）
    "mhlw_search": {
        "srch_R030430": mhlw_date_search(5, 3, 4, 30),
        "srch_S600613": mhlw_date_search(3, 60, 6, 13),
        "srch_H300829": mhlw_date_search(4, 30, 8, 29),
        "srch_R011113": mhlw_date_search(5, 1, 11, 13),
        "srch_R050619": mhlw_date_search(5, 5, 6, 19),
        "srch_R080301_0331": mhlw_date_search(5, 8, 3, 1, 8, 3, 31),
    },
    # 厚労省 法令等データベース：通知本文（R3 で取得済みのものの再取得を含む。年齢の判定時点 Q4 の再確認など）
    "mhlw_tdoc_known": {
        "S52_hifuyosha_nintei": tdoc("00tb0189"),
        "R7_19_23_qa": tdoc("00tc9628"),
        "R7_19_23_a": tdoc("00tc9249"),
        "R7_rodokeiyaku": tdoc("00tc9348"),
        "R7_rodokeiyaku_qa": tdoc("00tc9349"),
    },
    # 厚労省 法令等データベース：日付検索で見つけた通知本文（夫婦共同扶養、国内居住要件と同一世帯の確認、その Q&A）
    "mhlw_tdoc_new": {
        "R3_fufu_kyodo_fuyo": tdoc("00tc5892"),
        "H30_kokunai_jusho_hohohatsu": tdoc("00tc3621"),
        "H30_kokunai_jusho_kenpo": tdoc("00tc3625"),
        "H30_kokunai_jusho_ryuiten": tdoc("00tc3622"),
        "H30_kokunai_jusho_ryuiten_kenpo": tdoc("00tc3627"),
        "R01_kokunai_kyoju_kenpo_a": tdoc("00tc4995"),
        "R01_kokunai_kyoju_kenpo_b": tdoc("00tc4997"),
        "R05_kokunai_kyoju_kaisei_a": tdoc("00tc7769"),
        "R05_kokunai_kyoju_kaisei_b": tdoc("00tc7767"),
        "srch_R080309_0310": mhlw_date_search(5, 8, 3, 9, 8, 3, 10),
    },
    # 労働契約による判定の Q&A 第2版（令和8年3月9日 事務連絡。R3 では未取得）
    "mhlw_tdoc_qa2": {
        "R8_rodokeiyaku_qa2": tdoc("00tc9817"),
    },
    # Q&A 第2版の本文（画像として登載されている）
    "mhlw_qa2_images": {f"R8_qa2_img{i}": f"https://www.mhlw.go.jp/web/t_img?img={8023729 + i}" for i in range(1, 10)},
    # 上の t_img は画像を包む HTML（<IMG src="./t_img_res?img=...">）なので、画像そのものを取得する
    "mhlw_qa2_images_res": {f"R8_qa2_res{i}": f"https://www.mhlw.go.jp/web/t_img_res?img={8023729 + i}" for i in range(1, 10)},
    # 日本年金機構 年金Q&A（家族を扶養に入れるとき）
    "nenkin_faq_add": {
        "nenkin_faq_add_index": "https://www.nenkin.go.jp/section/faq/kounen/dependents/add/index.html",
        "nenkin_faq_19to22_timing": "https://www.nenkin.go.jp/section/faq/kounen/dependents/aged19to22/timing.html",
    },
    # 日本年金機構
    "nenkin": {
        "nenkin_hifuyo_tetsuzuki": "https://www.nenkin.go.jp/service/kounen/tekiyo/hihokensha1/20141202.html",
        "nenkin_henreifuyou": "https://www.nenkin.go.jp/service/kounen/info/jireishokai/henreifuyou.html",
        "nenkin_shinsei_20141224": "https://www.nenkin.go.jp/shinsei/kounen/tekiyo/hihokensha/20141224.html",
        "nenkin_faq_dependents": "https://www.nenkin.go.jp/section/faq/kounen/dependents/index.html",
        "nenkin_faq_19to22": "https://www.nenkin.go.jp/section/faq/kounen/dependents/aged19to22/index.html",
        "nenkin_0819": "https://www.nenkin.go.jp/oshirase/taisetu/2025/202508/0819.html",
        "nenkin_jigyosho_0501": "https://www.nenkin.go.jp/oshirase/taisetu/jigyosho/2026/202605/0501.html",
    },
    # 協会けんぽ（2026-03-18 にサイトを刷新。旧 URL は 404）
    "kyokai": {
        "kyokai_faq_dependent_status": "https://www.kyoukaikenpo.or.jp/faq/dependent_status/",
        "kyokai_pr_004_tokurei": "https://www.kyoukaikenpo.or.jp/about/business/public_relations/004/index.html",
        "kyokai_senpo_glossary_004": "https://www.kyoukaikenpo.or.jp/senpo/about/outline/glossary/004/index.html",
        "kyokai_glossary_top": "https://www.kyoukaikenpo.or.jp/glossary/",
        "kyokai_faq_top": "https://www.kyoukaikenpo.or.jp/faq/",
        "kyokai_jigyosho_qa_001159347": "https://www.kyoukaikenpo.or.jp/assets/001159347.pdf",
        "kyokai_dependent_r8leaf": "https://www.kyoukaikenpo.or.jp/assets/dependent_status_r8leaf.pdf",
    },
    # 協会けんぽ 被扶養者資格の再確認の様式（裏面の注記に「年収」の範囲が書かれている可能性がある）
    "kyokai_forms": {
        "kyokai_dependent_r8form": "https://www.kyoukaikenpo.or.jp/assets/dependent_status_r8form.pdf",
        "kyokai_dependent_r8list": "https://www.kyoukaikenpo.or.jp/assets/dependent_status_r8list.pdf",
        "kyokai_hihuchousaura2310": "https://www.kyoukaikenpo.or.jp/~/media/Files/honbu/cat590/hihuchousaura2310.pdf",
    },
    # 健康保険組合の公表例（保険者ごとの書き方の違いを示す例として1件だけ。一般化しない）
    "kenpo_kumiai_example": {
        "its_kenpo_20260327_2": "https://www.its-kenpo.or.jp/NEWS/hoken/20260327_2.html",
    },
    # 総務省 住民基本台帳
    "soumu": {
        "soumu_daityo_gaiyou": "https://www.soumu.go.jp/main_sosiki/jichi_gyousei/daityo/gaiyou.html",
        "soumu_001094645": "https://www.soumu.go.jp/main_content/001094645.pdf",
    },
    # 厚労省 content（検索で見つけた PDF。中身は取得後に確認する）
    "mhlw_content": {
        "content_000863814": "https://www.mhlw.go.jp/content/12400000/000863814.pdf",
        "content_001093084": "https://www.mhlw.go.jp/content/12400000/001093084.pdf",
        "content_001093085": "https://www.mhlw.go.jp/content/12400000/001093085.pdf",
        "content_000991672": "https://www.mhlw.go.jp/content/12400000/000991672.pdf",
        "content_001678029": "https://www.mhlw.go.jp/content/001678029.pdf",
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
    for img in ("png", "gif", "jpeg", "jpg"):
        if f"image/{img}" in c:
            return "." + ("jpg" if img == "jpeg" else img)
    if "spreadsheetml" in c or url.lower().endswith(".xlsx"):
        return ".xlsx"
    if "xml" in c or url.lower().endswith((".rdf", ".xml", ".rss")):
        return ".xml"
    if "json" in c:
        return ".json"
    if "html" in c:
        return ".html"
    return ".bin"


def run_set(name, urls, ts):
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL_kenpo_{name}"
    dl.mkdir(parents=True, exist_ok=False)
    tx = ROOT / ".work" / "text" / f"{ts}_IMPL_kenpo_{name}"
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

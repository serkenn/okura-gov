"""R3: 通達・通知・Q&A の一次情報ページを取得し、取得記録（ステータス、ヘッダ、SHA-256、タイトル）を残す。

実行: python -I scripts/R3_fetch.py <set名> [<set名> ...]
      python -I scripts/R3_fetch.py --list        # セットの一覧
- 取得したファイルは信頼できないデータとして、取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_R3_<set>/ に置く。
- HTML から抽出したテキストとリンクは、別の新しいディレクトリ .work/text/<ts>_R3_<set>/ に置く
  （ダウンロード用ディレクトリには取得したものだけを置く）。
- 取得記録は scripts/results/R3_fetch/<set>_<ts>.json に書く。
- リクエストの間は 1.5 秒あける。User-Agent は汎用名。
標準ライブラリのみ（Python 3.11）。
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

# id -> url。id はファイル名に使う。
SETS = {
    # 国税庁 所得税基本通達の目次など（リンクの発見用）
    "nta_index": {
        "shotoku_kihon_index": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/01.htm",
        "kobetsu_shotoku_index": "https://www.nta.go.jp/law/tsutatsu/kobetsu/shotoku/shinkoku/menu.htm",
        "nta_law_kaisei": "https://www.nta.go.jp/law/tsutatsu/kaisei/kaisei_a.htm",
        "nta_new": "https://www.nta.go.jp/information/news/index.htm",
        "nta_rss_page": "https://www.nta.go.jp/rss/index.htm",
    },
    # 国税庁 所得税基本通達の本文ページと、改正の一覧
    "nta_kihon": {
        "kihon_00_01_maebun": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/00/01.htm",
        "kihon_01_07_teigi": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/01/07.htm",
        "kihon_04_02_jigyo": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/04/02.htm",
        "kihon_04_03_kyuyo": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/04/03.htm",
        "kihon_04_09_zatsu": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/04/09.htm",
        "kihon_07_01_kaji": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/07/01.htm",
        "kihon_16_01_iryo": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/16/01.htm",
        "kihon_16_06_fuyo": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/16/06.htm",
        "kihon_33_01_shinkokusho": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/33/01.htm",
        "kihon_kaisei_a": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/kaisei/kaisei_a.htm",
        "law_tsutatsu_menu": "https://www.nta.go.jp/law/tsutatsu/menu.htm",
        "nta_information_index": "https://www.nta.go.jp/information/index.htm",
    },
    # 国税庁 改正のFAQ・年末調整
    "nta_kaisei_faq": {
        "gensen_2025kiso": "https://www.nta.go.jp/users/gensen/2025kiso/index.htm",
        "gensen_2026kiso": "https://www.nta.go.jp/users/gensen/2026kiso/index.htm",
        "gensen_nencho": "https://www.nta.go.jp/users/gensen/nencho/index.htm",
        "gensen_nenmatsu_nencho": "https://www.nta.go.jp/users/gensen/nenmatsu/nencho.htm",
        "gensen_2026tsukin": "https://www.nta.go.jp/users/gensen/2026tsukin/index.htm",
        "nenchou_yoshiki": "https://www.nta.go.jp/taxes/tetsuzuki/shinsei/annai/gensen/mokuji.htm",
        "mynapo_renkeiyotei": "https://www.nta.go.jp/taxes/tetsuzuki/mynumberinfo/mynapo_renkeiyotei.htm",
    },
    # 国税庁 改正のQ&A・パンフレット（PDF）
    "nta_pdf": {
        "r8_kaisei_aramashi": "https://www.nta.go.jp/publication/pamph/gensen/2026kaisei.pdf",
        "r8_kiso_qa": "https://www.nta.go.jp/users/gensen/2026kiso/pdf/0026005-024.pdf",
        "r7_kiso_pamph": "https://www.nta.go.jp/publication/pamph/gensen/0025004-025.pdf",
        "r7_kiso_qa": "https://www.nta.go.jp/publication/pamph/gensen/0025005-051.pdf",
        "nencho2026_kawatta": "https://www.nta.go.jp/publication/pamph/gensen/nencho2026/pdf/102.pdf",
    },
    # 国税庁 タックスアンサー・通達改正ページ・年末調整のしかた
    "nta_ta": {
        "ta_1180": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1180.htm",
        "ta_1177": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1177.htm",
        "ta_1120": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1120.htm",
        "ta_1122": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1122.htm",
        "ta_1350": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1350.htm",
        "ta_1500": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1500.htm",
        "ta_2210": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/2210.htm",
        "ta_1400": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1400.htm",
        "kaisei_221007": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/kaisei/221007/index.htm",
        "kaisei_2606": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/kaisei/2606/index.htm",
        "kaisei_260331": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/kaisei/260331/index.htm",
        "kaisei_251128": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/kaisei/251128/index.htm",
        "kaisei_250619": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/kaisei/250619/index.htm",
        "nencho2026_01": "https://www.nta.go.jp/publication/pamph/gensen/nencho2026/01.htm",
        "nencho2025_01": "https://www.nta.go.jp/publication/pamph/gensen/nencho2025/01.htm",
        "taxanswer_index": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/index2.htm",
    },
    # 厚労省 法令等データベースの通知（PDF）と関連資料
    "mhlw_tsuchi": {
        "T250724S0010": "https://www.mhlw.go.jp/hourei/doc/tsuchi/T250724S0010.pdf",
        "T260310S0010": "https://www.mhlw.go.jp/hourei/doc/tsuchi/T260310S0010.pdf",
        "T251006S0050": "https://www.mhlw.go.jp/hourei/doc/tsuchi/T251006S0050.pdf",
        "T240112T0010": "https://www.mhlw.go.jp/hourei/doc/tsuchi/T240112T0010.pdf",
        "content_001678030": "https://www.mhlw.go.jp/content/001678030.pdf",
        "content_001678015": "https://www.mhlw.go.jp/content/001678015.pdf",
        "content_001678016": "https://www.mhlw.go.jp/content/001678016.pdf",
        "hourei_top": "https://www.mhlw.go.jp/hourei/",
    },
    # 日本年金機構・協会けんぽ
    "nenkin_kyokai": {
        "nenkin_0819": "https://www.nenkin.go.jp/oshirase/taisetu/2025/202508/0819.html",
        "nenkin_jigyosho_0501": "https://www.nenkin.go.jp/oshirase/taisetu/jigyosho/2026/202605/0501.html",
        "nenkin_hihokensha_fuyo": "https://www.nenkin.go.jp/service/kounen/jigyosho-hiho/hihokensha1/20141204.html",
        "kyokai_fuyo": "https://www.kyoukaikenpo.or.jp/g3/cat320/sb3160/sbb3163/1959-230/",
        "kyokai_nenshuunokabe": "https://www.kyoukaikenpo.or.jp/event/cat550/nenshuunokabe/",
    },
    # 厚労省 法令等データベースの新着・更新一覧（監視の候補）
    "mhlw_hourei_lists": {
        "hourei_new_tsuchi": "https://www.mhlw.go.jp/hourei/new/tsuchi/new.html",
        "hourei_new_hourei": "https://www.mhlw.go.jp/hourei/new/hourei/new.html",
        "hourei_update_data": "https://www.mhlw.go.jp/hourei/new/update/data.html",
        "hourei_tsuchi_item_search": "https://www.mhlw.go.jp/hourei/html/tsuchi/item_search.html",
        "hourei_tsuchi_contents": "https://www.mhlw.go.jp/hourei/html/tsuchi/contents.html",
        "hourei_readme": "https://www.mhlw.go.jp/hourei/readme.html",
    },
    # 厚労省 法令等データベースの iframe の中身
    "mhlw_hourei_frames": {
        "hourei_new_tsuchi_index": "https://www.mhlw.go.jp/hourei/new/tsuchi/newindex.html",
        "hourei_new_hourei_index": "https://www.mhlw.go.jp/hourei/new/hourei/newindex.html",
        "web_t_itemsrch": "https://www.mhlw.go.jp/web/t_itemsrch?type=1",
    },
    # 厚労省 法令等データベース 通知の情報詳細検索（日付指定、GET）
    "mhlw_search": {
        "srch_S520406": "https://www.mhlw.go.jp/web/t_itemsrch_result?type=1&startGengo=3&yearFrom=52&monthFrom=4&dayFrom=6&endGengo=3&yearTo=52&monthTo=4&dayTo=6&shubetsu=&bango=",
        "srch_R070704": "https://www.mhlw.go.jp/web/t_itemsrch_result?type=1&startGengo=5&yearFrom=7&monthFrom=7&dayFrom=4&endGengo=5&yearTo=7&monthTo=7&dayTo=4&shubetsu=&bango=",
        "srch_R071001": "https://www.mhlw.go.jp/web/t_itemsrch_result?type=1&startGengo=5&yearFrom=7&monthFrom=10&dayFrom=1&endGengo=5&yearTo=7&monthTo=10&dayTo=1&shubetsu=&bango=",
        "srch_R050929": "https://www.mhlw.go.jp/web/t_itemsrch_result?type=1&startGengo=5&yearFrom=5&monthFrom=9&dayFrom=29&endGengo=5&yearTo=5&monthTo=9&dayTo=29&shubetsu=&bango=",
        "srch_R051020": "https://www.mhlw.go.jp/web/t_itemsrch_result?type=1&startGengo=5&yearFrom=5&monthFrom=10&dayFrom=20&endGengo=5&yearTo=5&monthTo=10&dayTo=20&shubetsu=&bango=",
    },
    # 厚労省 法令等データベース 通知本文（t_doc）
    "mhlw_tdoc": {
        "S52_hifuyosha_nintei": "https://www.mhlw.go.jp/web/t_doc?dataId=00tb0189&dataType=1&pageNo=1",
        "R7_19_23_a": "https://www.mhlw.go.jp/web/t_doc?dataId=00tc9249&dataType=1&pageNo=1",
        "R7_19_23_b": "https://www.mhlw.go.jp/web/t_doc?dataId=00tc9250&dataType=1&pageNo=1",
        "R7_19_23_qa": "https://www.mhlw.go.jp/web/t_doc?dataId=00tc9628&dataType=1&pageNo=1",
        "R7_kabe_kokyuka": "https://www.mhlw.go.jp/web/t_doc?dataId=00tc9347&dataType=1&pageNo=1",
        "R7_rodokeiyaku": "https://www.mhlw.go.jp/web/t_doc?dataId=00tc9348&dataType=1&pageNo=1",
        "R7_rodokeiyaku_qa": "https://www.mhlw.go.jp/web/t_doc?dataId=00tc9349&dataType=1&pageNo=1",
        "R5_kabe_kenpo": "https://www.mhlw.go.jp/web/t_doc?dataId=00tc8005&dataType=1&pageNo=1",
        "R5_kabe_honbun": "https://www.mhlw.go.jp/web/t_doc?dataId=00tc8012&dataType=1&pageNo=1",
    },
    # 監視用の情報源の発見（トップページ等から RSS のリンクを探す）
    "feeds_discovery": {
        "nta_top": "https://www.nta.go.jp/index.htm",
        "mhlw_rss_page": "https://www.mhlw.go.jp/rss",
        "nenkin_allnews": "https://www.nenkin.go.jp/allNewsList.html",
        "nenkin_top": "https://www.nenkin.go.jp/",
        "kyokai_top": "https://www.kyoukaikenpo.or.jp/",
        "soumu_top": "https://www.soumu.go.jp/",
        "nta_gensen_index": "https://www.nta.go.jp/users/gensen/index.htm",
    },
    # 追加の一次情報（第3号の認定基準、通達の解説、年末調整のしかた、住民税の自治体資料）
    "extra": {
        "srch_H050305": "https://www.mhlw.go.jp/web/t_itemsrch_result?type=1&startGengo=4&yearFrom=5&monthFrom=3&dayFrom=5&endGengo=4&yearTo=5&monthTo=3&dayTo=5&shubetsu=&bango=",
        "nenkin_hifuyo_tetsuzuki": "https://www.nenkin.go.jp/service/kounen/tekiyo/hihokensha1/20141202.html",
        "nenkin_faq_19to22": "https://www.nenkin.go.jp/section/faq/kounen/dependents/aged19to22/index.html",
        "nenkin_0617": "https://www.nenkin.go.jp/oshirase/taisetu/kojin/2026/202606/0617.html",
        "nta_221007_kaisetsu": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/kaisei/221007/pdf/02.pdf",
        "nta_shohi_kihon_01_01": "https://www.nta.go.jp/law/tsutatsu/kihon/shohi/01/01.htm",
        "nta_kobetsu_shinkoku": "https://www.nta.go.jp/law/tsutatsu/kobetsu/shotoku/shinkoku/sinkoku.htm",
        "nencho2026_103": "https://www.nta.go.jp/publication/pamph/gensen/nencho2026/pdf/103.pdf",
        "nencho2026_105": "https://www.nta.go.jp/publication/pamph/gensen/nencho2026/pdf/105.pdf",
        "yokohama_r8": "https://www.city.yokohama.lg.jp/kurashi/koseki-zei-hoken/zeikin/y-shizei/kojin-shiminzei-kenminzei/kaisei/zeiseikaiseiR8.html",
        "chiba_r8": "https://www.city.chiba.jp/zaiseikyoku/zeimu/kazeikanri/zeiseikaiseijuminzei2026.html",
    },
    # 追加2（協会けんぽの案内、給与と事業の区分の個別通達、令和9年度住民税の自治体資料、第3号の認定基準の検索）
    "extra2": {
        "kyokai_dependent_r8leaf": "https://www.kyoukaikenpo.or.jp/assets/dependent_status_r8leaf.pdf",
        "kyokai_fuyouidou_guide2607": "https://www.kyoukaikenpo.or.jp/assets/n_fuyouidou_guide2607.pdf",
        "kyokai_dependent_status_001": "https://www.kyoukaikenpo.or.jp/about/business/dependent_status/001/index.html",
        "nta_daiku_091217": "https://www.nta.go.jp/law/tsutatsu/kobetsu/shotoku/shinkoku/091217/01.htm",
        "chiba_r9": "https://www.city.chiba.jp/zaiseikyoku/zeimu/kazeikanri/zeiseikaiseijuminzei2027.html",
        "kobe_r9": "https://www.city.kobe.lg.jp/a83576/kurashi/tax/shikenminze/r9kaisei.html",
        "srch_H0503": "https://www.mhlw.go.jp/web/t_itemsrch_result?type=1&startGengo=4&yearFrom=5&monthFrom=3&dayFrom=1&endGengo=4&yearTo=5&monthTo=3&dayTo=31&shubetsu=&bango=",
    },
    # 国民健康保険（自治体の案内）
    "kokuho": {
        "yokohama_kokuho_hihokensha": "https://www.city.yokohama.lg.jp/kurashi/koseki-zei-hoken/kokuho/hokensho/hihokensha.html",
    },
    # 医療費通知のマイナポータル連携
    "mynapo": {
        "mynapo_list": "https://www.nta.go.jp/taxes/tetsuzuki/mynumberinfo/list.htm",
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
            # 国税庁の通達では「補塡」などの字が画像（alt 付き）で表示される。alt を ⟨⟩ で囲んで残す。
            self.parts.append("⟨" + a["alt"] + "⟩")
            if self._href is not None:
                self._atext.append("⟨" + a["alt"] + "⟩")
        if tag == "a" and a.get("href"):
            self._href = a["href"]
            self._atext = []
        if tag == "link" and a.get("type", "").endswith(("rss+xml", "atom+xml")):
            self.links.append({"href": a.get("href"), "text": "[feed] " + (a.get("title") or "")})
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
    if "xml" in c or "rss" in c or url.lower().endswith((".rdf", ".xml", ".rss")):
        return ".xml"
    if "json" in c:
        return ".json"
    if "html" in c:
        return ".html"
    return ".bin"


def run_set(name, urls, ts):
    dl = ROOT / ".work" / "downloads" / f"{ts}_R3_{name}"
    dl.mkdir(parents=True, exist_ok=False)
    tx = ROOT / ".work" / "text" / f"{ts}_R3_{name}"
    tx.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "R3_fetch"
    out.mkdir(parents=True, exist_ok=True)
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
            if ext in (".html",) and body:
                s, cs = decode(body, ctype)
                p = Extract()
                p.feed(s)
                links = []
                for l in p.links:
                    h = l["href"]
                    if h and not h.startswith(("javascript:", "mailto:", "#")):
                        links.append({"href": urllib.parse.urljoin(final, h), "text": l["text"]})
                (tx / f"{sid}.txt").write_text(p.text(), encoding="utf-8")
                (tx / f"{sid}.links.json").write_text(json.dumps(links, ensure_ascii=False, indent=1), encoding="utf-8")
                rec.update({"charset": cs, "title": " ".join(p.title.split()), "text_chars": len(p.text()),
                            "text": str((tx / f"{sid}.txt").relative_to(ROOT)), "n_links": len(links)})
        except Exception as e:  # noqa: BLE001
            rec["error"] = repr(e)
        log.append(rec)
        (out / f"{name}_{ts}.json").write_text(
            json.dumps({"set": name, "fetched_at_local": ts, "user_agent": UA, "results": log}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        print(json.dumps({k: rec.get(k) for k in ("id", "status", "bytes", "title", "error")}, ensure_ascii=False))
    (out / f"{name}_{ts}.json").write_text(
        json.dumps({"set": name, "fetched_at_local": ts, "user_agent": UA, "results": log}, ensure_ascii=False, indent=2),
        encoding="utf-8")


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

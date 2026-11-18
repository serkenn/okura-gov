"""IMPL_iryohi: 医療費控除・セルフメディケーション税制に関する国税庁・厚生労働省のページを GET で取得し、取得記録を残す。

実行（Windows では pyenv のシムを通さずに実体の python.exe を使う）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_iryohi_web.py <set名> [<set名> ...]
  ... scripts/IMPL_iryohi_web.py --list

- 書き方は scripts/R3_fetch.py を写したもの（import はしない）。
- 取得したファイルは信頼できないデータとして、取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_IMPL_iryohi_<set>/ に置く。その中でインタプリタやツールを実行しない。
- HTML から抜き出したテキストとリンクは、別の新しいディレクトリ .work/text/<ts>_IMPL_iryohi_<set>/ に置く。
  国税庁の通達では「補塡」の「塡」などが画像（alt 付き）で表示されるので、alt を ⟨⟩ で囲んで残す。
- 取得記録（URL、HTTP 状態、Content-Type、Last-Modified、サイズ、SHA-256、タイトル）は
  scripts/results/IMPL_iryohi_web/<set>_<ts>.json に書く。
- キーワードに一致したリンク（URL と表示文字列だけ）は scripts/results/IMPL_iryohi_web/<set>_<ts>_links.json に書く。
- GET だけ。Cookie を保存・送信しない。リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。
- 官報（kanpou.npb.go.jp）は robots.txt で号ごとのページの巡回が禁止されているので、ここには入れない。
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
ALLOWED_HOSTS = {"www.nta.go.jp", "www.mhlw.go.jp", "www.keisan.nta.go.jp", "www.e-tax.nta.go.jp"}
LINK_KW = re.compile(r"医療費|セルフメディケーション|一般用医薬品|明細書|1120|1122|1124|1126|1127|1128|1129|1130|1131|1132|1133|補(?:塡|てん|填)|医薬品")

SETS = {
    # 目次・索引（リンクの発見用）
    "discover": {
        "ta_shoto320": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/shoto320.htm",
        "shitsugi_shotoku_01": "https://www.nta.go.jp/law/shitsugi/shotoku/01.htm",
        "shitsugi_index": "https://www.nta.go.jp/law/shitsugi/01.htm",
        "yoshiki_01_index": "https://www.nta.go.jp/taxes/shiraberu/shinkoku/yoshiki/01/index.htm",
        "yoshiki_shinkokusho_01": "https://www.nta.go.jp/taxes/shiraberu/shinkoku/yoshiki/01/shinkokusho/01.htm",
        "tsutatsu_menu": "https://www.nta.go.jp/law/tsutatsu/menu.htm",
        "tokushu_iryou": "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tokushu/keisubetsu/iryou-koujo.htm",
        "tokushu_self": "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tokushu/keisubetsu/self-medication.htm",
        "mhlw_selfmed": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000124853.html",
    },
    # 通達とタックスアンサーの本文
    "core": {
        "kihon_16_01_iryo": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/16/01.htm",
        "ta_1120": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1120.htm",
        "ta_1122": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1122.htm",
    },
    # 質疑応答事例（所得税・医療費控除。TA1120 からリンクされているもの）
    "shitsugi": {f"shitsugi_05_{n}": f"https://www.nta.go.jp/law/shitsugi/shotoku/05/{n}.htm"
                 for n in ["24", "25", "26", "27", "28", "57", "58", "59", "60", "61", "81", "82", "83"]},
    # 質疑応答事例（所得税・医療費控除。記録の種類の境目に関係するもの。shitsugi_shotoku_01 の目次から選んだ）
    "shitsugi2": {f"shitsugi_05_{n}": f"https://www.nta.go.jp/law/shitsugi/shotoku/05/{n}.htm"
                  for n in ["86", "72", "12", "39", "21", "50", "20", "09", "16", "18", "53", "54", "42"]},
    # タックスアンサー（医療費控除・セルフメディケーション税制の関連。TA1120 からリンクされているもの）
    "ta2": {f"ta_{n}": f"https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/{n}.htm"
            for n in ["1124", "1126", "1128", "1129", "1131", "1132", "1133", "1134"]},
    # 明細書の様式・医療費集計フォームの案内
    "forms": {
        "annai_1557_2": "https://www.nta.go.jp/taxes/tetsuzuki/shinsei/annai/shinkoku/annai/1557_2.htm",
        "kakutei_koujyo": "https://www.nta.go.jp/taxes/shiraberu/shinkoku/kakutei/koujyo.htm",
        "iryou_shuukei": "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tokushu/keisubetsu/iryou-shuukei.htm",
        "kakushin_yoshiki": "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tokushu/kakushin-sakusei/yoshiki.htm",
    },
    # 明細書の様式（PDF）と医療費集計フォーム（xlsx）。リンクは annai_1557_2・iryou_shuukei から
    "forms2": {
        "meisai_iryohi_ref1": "https://www.nta.go.jp/taxes/shiraberu/shinkoku/yoshiki/04/pdf/ref1.pdf",
        "meisai_iryohi_jiyo_ref3": "https://www.nta.go.jp/taxes/shiraberu/shinkoku/yoshiki/03/pdf/ref3.pdf",
        "meisai_selfmed_017": "https://www.nta.go.jp/taxes/shiraberu/shinkoku/yoshiki/017.pdf",
        "meisai_selfmed_jiyo_ref4": "https://www.nta.go.jp/taxes/shiraberu/shinkoku/yoshiki/03/pdf/ref4.pdf",
        "iryouhi_form_v31": "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tokushu/keisubetsu/iryouhi_form_v3.1.xlsx",
    },
    # 明細書の記載要領（annai_1557_2 の「記載要領」リンク）
    "forms3": {
        "meisai_iryohi_ref1_ki": "https://www.nta.go.jp/taxes/shiraberu/shinkoku/yoshiki/04/pdf/ref1-ki.pdf",
        "meisai_selfmed_017_ki": "https://www.nta.go.jp/taxes/shiraberu/shinkoku/yoshiki/017-ki.pdf",
    },
    # 令和7年分の確定申告の手引き（医療費控除の書き方・端数の扱いを探すため）
    "tebiki": {
        "tebiki_2025_index": "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/2025/index.htm",
        "tebiki_2025_01": "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/2025/01.htm",
        "tebiki_index": "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/index.htm",
    },
    # 令和7年分の手引きの医療費控除の欄・明細書のページ、所得金額の合計の欄（tebiki_2025_index からリンク）
    "tebiki2": {
        "tebiki_2025_3-3_24_iryohi": "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/2025/03/order3/3-3_24.htm",
        "tebiki_2025_6_01_meisai": "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/2025/06/6_01.htm",
        "tebiki_2025_3-2_09_goukei": "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/2025/03/order2/3-2_09.htm",
    },
    # タックスアンサーの用語集（TA1120・TA1131 の「総所得金額等」のリンク先）
    "yogo": {
        "ta_yogo_senmon": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/yogo/senmon.htm",
    },
    # 令和7年分『医療費控除を受けられる方へ』（tebiki_2025_3-3_24_iryohi からリンク）
    "tebiki3": {
        "tebiki_2025_pdf_008_iryohi": "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/2025/pdf/008.pdf",
    },
    # 厚生労働省のセルフメディケーション税制の資料（0000124853.html からリンクされているもの）
    "mhlw": {
        "mhlw_qa_r080807": "https://www.mhlw.go.jp/content/10800000/001461529.pdf",
        "mhlw_receipt_jimurenraku": "https://www.mhlw.go.jp/file/06-Seisakujouhou-10800000-Iseikyoku/0000138818.pdf",
        "mhlw_exclude_r071231": "https://www.mhlw.go.jp/content/10800000/001596290.pdf",
        "mhlw_kokuji178_switch": "https://www.mhlw.go.jp/content/10800000/001750283.pdf",
        "mhlw_kokuji251_nonswitch": "https://www.mhlw.go.jp/content/10800000/001750284.pdf",
        "mhlw_kokuji251_nonswitch_r9": "https://www.mhlw.go.jp/content/10800000/001750285.pdf",
        "mhlw_kokuji307_kensa_r9": "https://www.mhlw.go.jp/content/10800000/001750286.pdf",
        "mhlw_r8kaisei_todokede": "https://www.mhlw.go.jp/content/10800000/001741727.pdf",
    },
    # 厚生労働省：取組の告示、令和8年分以後の証明の発行、取組の説明（0000124853.html からリンク）
    "mhlw2": {
        "mhlw_kokuji181_torikumi": "https://www.mhlw.go.jp/content/10800000/000619222.pdf",
        "mhlw_shomei_r8_hokensha": "https://www.mhlw.go.jp/content/10800000/001755789.pdf",
        "mhlw_torikumi_setsumei": "https://www.mhlw.go.jp/content/10800000/000837214.pdf",
        "mhlw_receipt_error_page": "https://www.mhlw.go.jp/stf/newpage_08184.html",
    },
}


class Extract(html.parser.HTMLParser):
    """scripts/R3_fetch.py の Extract の写し。"""
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


class NoOffsiteRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).hostname not in ALLOWED_HOSTS:
            raise urllib.error.HTTPError(newurl, code, f"offsite redirect blocked: {newurl}", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(NoOffsiteRedirect)


def get(url):
    if urllib.parse.urlsplit(url).hostname not in ALLOWED_HOSTS:
        raise ValueError(f"host not allowed: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja"}, method="GET")
    try:
        with OPENER.open(req, timeout=30) as r:
            return r.status, r.geturl(), dict(r.headers), read_with_deadline(r)
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
        except Exception:  # noqa: BLE001
            body = b""
        return e.code, url, dict(e.headers or {}), body


def ext_for(ctype, url):
    c = (ctype or "").lower()
    u = url.lower().split("?")[0]
    if "pdf" in c or u.endswith(".pdf"):
        return ".pdf"
    if "spreadsheetml" in c or u.endswith(".xlsx"):
        return ".xlsx"
    if "xml" in c or u.endswith((".rdf", ".xml", ".rss")):
        return ".xml"
    if "json" in c:
        return ".json"
    if "html" in c:
        return ".html"
    return ".bin"


def run_set(name, urls, ts):
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL_iryohi_{name}"
    dl.mkdir(parents=True, exist_ok=False)
    tx = ROOT / ".work" / "text" / f"{ts}_IMPL_iryohi_{name}"
    tx.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "IMPL_iryohi_web"
    out.mkdir(parents=True, exist_ok=True)
    log, kw_links = [], {}
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
                "last_modified": hdr.get("Last-Modified"),
                "saved": str((dl / f"{sid}{ext}").relative_to(ROOT)).replace("\\", "/"),
            })
            if ext == ".html" and body and st == 200:
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
                kw_links[sid] = [l for l in links if LINK_KW.search(l["text"]) or LINK_KW.search(l["href"])]
                rec.update({"charset": cs, "title": " ".join(p.title.split()), "text_chars": len(p.text()),
                            "text": str((tx / f"{sid}.txt").relative_to(ROOT)).replace("\\", "/"), "n_links": len(links)})
        except Exception as e:  # noqa: BLE001
            rec["error"] = repr(e)
        log.append(rec)
        print(json.dumps({k: rec.get(k) for k in ("id", "status", "bytes", "last_modified", "title", "error")}, ensure_ascii=False))
    meta = {"set": name, "fetched_at_local": ts, "user_agent": UA, "results": log}
    (out / f"{name}_{ts}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / f"{name}_{ts}_links.json").write_text(json.dumps(kw_links, ensure_ascii=False, indent=1), encoding="utf-8")


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

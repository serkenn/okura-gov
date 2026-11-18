"""R3X kyosai-b: 共済組合の被扶養者の認定基準（大臣の定め）の原文を探すため、財務省・総務省・文部科学省・e-Gov パブリック・コメント・
各共済組合・日本私立学校振興・共済事業団の公表資料を取得し、取得記録を残す。

実行（リポジトリのルートで）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_kyosai-b_fetch.py <set名> [<set名> ...]
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_kyosai-b_fetch.py --list

- 取得したファイルは信頼できないデータとして、取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_R3X_kyosai-b_<set>/ に置く（その中でインタプリタやツールを実行しない）。
- HTML から抽出したテキストとリンクは、別の新しいディレクトリ .work/text/<ts>_R3X_kyosai-b_<set>/ に置く。
- 取得記録（ステータス、最終 URL、Last-Modified、ETag、SHA-256、バイト数、タイトル）は
  scripts/results/R3X_kyosai-b_fetch/<set>_<ts>.json に書く。
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。個人の情報は送らない。官報は取得しない。
- 本文の読み出しは 1 件 90 秒・64 MiB で打ち切る。
標準ライブラリのみ（Python 3.11）。scripts/R2X_kyosai_fetch.py のコードを写して作った（import はしていない）。
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
MAXBYTES = 64 * 1024 * 1024
OUT = ROOT / "scripts" / "results" / "R3X_kyosai-b_fetch"

PCM = "https://public-comment.e-gov.go.jp/servlet/Public?CLASSNAME=PCM1040&Mode=1&id="
PCMD = "https://public-comment.e-gov.go.jp/servlet/Public?CLASSNAME=PCMMSTDETAIL&Mode=0&id="

# id -> url。id はファイル名に使う。
SETS = {
    # 国家公務員：財務省の運用方針（現行の全文）と通達の一覧、e-Gov パブリック・コメントの結果の公示・意見募集
    "kokka_pcm": {
        "pcm_395081949": PCM + "395081949",
        "pcm_395081944": PCM + "395081944",
        "pcmd_395081959": PCMD + "395081959",
        "pcm_395081959": PCM + "395081959",
    },
    "mof": {
        "mof_unyo_hoshin_current": "https://www.mof.go.jp/about_mof/act/kokuji_tsuutatsu/tsuutatsu/TU-19591001-2927-11.pdf",
        "mof_tsuutatsu_r": "https://www.mof.go.jp/about_mof/act/kokuji_tsuutatsu/tsuutatsu/tsuutatsu_r.htm",
        "mof_tsuutatsu_s": "https://www.mof.go.jp/about_mof/act/kokuji_tsuutatsu/tsuutatsu/tsuutatsu_s.htm",
    },
    # 地方公務員：組合の案内（総務省の改正通知を添付・引用しているもの）と、運用方針（抄）を載せた資料
    "chiho_a": {
        "kouritu_tokyo_19_23": "https://www.kouritu.or.jp/tokyo/topics/19-23kizyungaku/index.html",
        "sendai_kyosai_detail78": "https://sendai-kyosai.or.jp/pop/detail78",
        "miyagi_fget96": "https://www.kyosai-miyagi.or.jp/osirase/fget96",
        "sigichokai_hoshin_kyosai": "https://www.si-gichokai.jp/kyousai/nenkin_gaiyo/pdf/hoshin_kyosai.pdf",
        "kouritu_kagoshima_19_23": "https://www.kouritu.or.jp/kagoshima/19%E6%AD%B3%E4%BB%A5%E4%B8%8A23%E6%AD%B3%E6%9C%AA%E6%BA%80%E3%81%AE%E8%A2%AB%E6%89%B6%E9%A4%8A%E8%80%85%E3%81%AE%E8%AA%8D%E5%AE%9A%E5%9F%BA%E6%BA%96%E9%A1%8D%E3%81%8C%E5%A4%89%E6%9B%B4%E3%81%95%E3%82%8C%E3%81%BE%E3%81%99/index.html",
    },
    # 地方公務員（続き）：公立学校共済組合東京支部のページに添付された PDF（「03_総務省運用方針改正通知.pdf」ほか）、
    # 地方職員共済組合本部のお知らせ、e-Gov パブリック・コメントの公募時の画面・結果概要（国家公務員）
    "chiho_b": {
        "kouritu_tokyo_00_tsuchi": "https://www.kouritu.or.jp/tokyo/content/files/0f79f0f5da86d0d0a0fef9885fb76e23.pdf",
        "kouritu_tokyo_01_qa": "https://www.kouritu.or.jp/tokyo/content/files/28a6386c07a64e8326868d75bc01aa8d.pdf",
        "kouritu_tokyo_03_soumu": "https://www.kouritu.or.jp/tokyo/content/files/3ba94cb45594628e0778652af5dc4b35.pdf",
        "kouritu_tokyo_04_mhlw": "https://www.kouritu.or.jp/tokyo/content/files/df544b2f3530eb3bcb33c968da6f091a.pdf",
        "chikyosai_info_250924": "https://www.chikyosai.or.jp/info/short/pdf/info_250924.pdf",
    },
    "kokka_b": {
        "pcm_dl_0000289948": "https://public-comment.e-gov.go.jp/pcm/download?seqNo=0000289948",
        "pcm_dl_0000318809": "https://public-comment.e-gov.go.jp/pcm/download?seqNo=0000318809",
        "boueikyosai_164": "https://www.boueikyosai.or.jp/site/folder1/164.html",
        "mhlw_pcm_495250041": PCM + "495250041",
        "pcm_detail_395081959": "https://public-comment.e-gov.go.jp/pcm/detail?CLASSNAME=PCMMSTDETAIL&id=395081959&Mode=0",
    },
    # 私学：日本私立学校振興・共済事業団の案内（19〜23歳の改正のお知らせ、Q&A、取消）
    "pmac_a": {
        "pmac_news_250910_00": "https://www.pmac.shigaku.go.jp/annai/news/topics/250910_00.html",
        "pmac_qa_48": "https://www.pmac.shigaku.go.jp/qa/detail/qa_48.html",
        "pmac_hifuyosya_09": "https://www.pmac.shigaku.go.jp/annai/shikaku/hifuyosya/hifuyosya_09/index.html",
    },
    # 私学（続き）：事業団の規程の一覧（事業団本体・私学共済事業）、共済運営規則、私学共済事業のお知らせの一覧
    "pmac_b": {
        "shigaku_g_kiteitou": "https://www.shigaku.go.jp/g_kiteitou.htm",
        "pmac_joho_kitei": "https://www.pmac.shigaku.go.jp/annai/joho/kitei/index.html",
        "shigaku_kyousai_uneikisoku": "https://www.shigaku.go.jp/files/kyousai_uneikisoku_250627%20.pdf",
        "pmac_news_index": "https://www.pmac.shigaku.go.jp/annai/news/index.html",
        "pmac_top": "https://www.pmac.shigaku.go.jp/",
    },
    # 国家公務員（続き）：Internet Archive（Wayback Machine）の CDX API で、財務省の運用方針の PDF の保存の一覧を取る
    # （第三者の保存。改正の前後の版を比べるためだけに使う）
    "wayback_cdx": {
        "cdx_mof_unyo": "https://web.archive.org/cdx/search/cdx?url=www.mof.go.jp/about_mof/act/kokuji_tsuutatsu/tsuutatsu/TU-19591001-2927-11.pdf&output=json&fl=timestamp,original,statuscode,mimetype,digest,length&from=2023",
    },
    # 上の一覧にあった保存（2025-07-21・2026-09-26）の本体（"id_" をつけると保存した元のバイト列を返す）
    "wayback_pdf": {
        "wb_20250721_mof_unyo": "https://web.archive.org/web/20250721103617id_/https://www.mof.go.jp/about_mof/act/kokuji_tsuutatsu/tsuutatsu/TU-19591001-2927-11.pdf",
        "wb_20260926_mof_unyo": "https://web.archive.org/web/20260926161059id_/https://www.mof.go.jp/about_mof/act/kokuji_tsuutatsu/tsuutatsu/TU-19591001-2927-11.pdf",
    },
    # 国家公務員（続き）：裁判所共済組合が掲載する運用方針の写し（前回の取得は令和5年3月28日現在の版）。改正前後の比較のため取り直す
    "unyo_old": {
        "courts_unyo_hoshin": "https://www.kyousai.courts.or.jp/files/user/img/houki/1-01.pdf",
    },
    # 私学（続き）：私学共済事業の規程（共済規程・共済運営規則の現行の PDF）、被扶養者の認定に関するお知らせ
    "pmac_c": {
        "pmac_kyosai_kitei_2026_03": "https://www.pmac.shigaku.go.jp/annai/joho/kitei/i1o6910000008vka-att/k_kyosai_kitei_2026_03.pdf",
        "pmac_kyosai_uneikisoku_2026_02": "https://www.pmac.shigaku.go.jp/annai/joho/kitei/i1o6910000008vld-att/k_kyosai_uneikisoku_2026_02.pdf",
        "pmac_topics_260302_01": "https://www.pmac.shigaku.go.jp/annai/news/topics/topics_260302_01_.html",
        "pmac_topics_251201_00": "https://www.pmac.shigaku.go.jp/annai/news/topics/topics_251201_00.html",
        "pmac_topics_231106_00": "https://www.pmac.shigaku.go.jp/annai/news/topics/topics_231106_00.html",
        "pmac_hifuyosya_index": "https://www.pmac.shigaku.go.jp/annai/shikaku/hifuyosya/index.html",
    },
    # 私学（続き）：令和8年3月2日の通知文（労働契約による年間収入）と、令和7年9月のお知らせ（19〜23歳）の保存の一覧（Wayback CDX）
    "pmac_d": {
        "pmac_oshirase_20260302_339": "https://www.pmac.shigaku.go.jp/annai/news/topics/sdajio0000000a0o-att/k_oshirase_20260302_339.pdf",
        "cdx_pmac_topics_2025": "https://web.archive.org/cdx/search/cdx?url=pmac.shigaku.go.jp/annai/news/topics/&matchType=prefix&output=json&fl=timestamp,original,statuscode,mimetype,digest,length&from=20250801&to=20251231&collapse=urlkey",
    },
    # 私学（続き）：私学共済事業の「私立学校教職員共済制度関係法令集」のページ
    "pmac_e": {
        "pmac_kanko_hourei": "https://www.pmac.shigaku.go.jp/annai/kanko/jimu/hourei/index.html",
        "pmac_kanko_jimu": "https://www.pmac.shigaku.go.jp/annai/kanko/jimu/index.html",
    },
    # 私学（続き）：法令集 令和8年版（令和8年4月1日現在）の「凡例・総目次」と「その他」
    "pmac_f": {
        "pmac_hourei_mokuji_2026": "https://www.pmac.shigaku.go.jp/annai/kanko/jimu/hourei/ndc94q0000002jy6-att/hourei_hanrei_mokuji_2026.pdf",
        "pmac_hourei_sonota_2026": "https://www.pmac.shigaku.go.jp/annai/kanko/jimu/hourei/ndc94q0000002jy6-att/hourei_sonota_2026.pdf",
    },
    # 私学（続き）：法令集の過去の版（改正前の文部大臣裁定の文言を見るため）の保存の一覧（Wayback CDX）
    "cdx_pmac_hourei": {
        "cdx_pmac_hourei": "https://web.archive.org/cdx/search/cdx?url=pmac.shigaku.go.jp/annai/kanko/jimu/hourei/&matchType=prefix&output=json&fl=timestamp,original,statuscode,mimetype,digest,length&collapse=urlkey&limit=200",
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
    """本文を少しずつ読み、制限時間か上限のバイト数を超えたら打ち切る。"""
    deadline = time.monotonic() + seconds
    chunks, n = [], 0
    while True:
        b = resp.read(65536)
        if not b:
            break
        chunks.append(b)
        n += len(b)
        if n > MAXBYTES:
            raise ValueError(f"body exceeded {MAXBYTES} bytes")
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
        try:
            body = e.read()
        except Exception:  # noqa: BLE001
            body = b""
        return e.code, url, dict(e.headers or {}), body


def ext_for(ctype, url, body):
    c = (ctype or "").lower()
    if "pdf" in c or url.lower().endswith(".pdf") or body[:5] == b"%PDF-":
        return ".pdf"
    for img in ("png", "gif", "jpeg", "jpg"):
        if f"image/{img}" in c:
            return "." + ("jpg" if img == "jpeg" else img)
    if "spreadsheetml" in c or url.lower().endswith(".xlsx"):
        return ".xlsx"
    if "wordprocessingml" in c or url.lower().endswith(".docx"):
        return ".docx"
    if "msword" in c or url.lower().endswith(".doc"):
        return ".doc"
    if "html" in c:
        return ".html"
    if "xml" in c or url.lower().endswith((".rdf", ".xml", ".rss")):
        return ".xml"
    if "json" in c:
        return ".json"
    return ".bin"


def run_set(name, urls, ts):
    dl = ROOT / ".work" / "downloads" / f"{ts}_R3X_kyosai-b_{name}"
    dl.mkdir(parents=True, exist_ok=False)
    tx = ROOT / ".work" / "text" / f"{ts}_R3X_kyosai-b_{name}"
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
            ext = ext_for(ctype, final, body)
            (dl / f"{sid}{ext}").write_bytes(body)
            rec.update({
                "status": st, "final_url": final, "content_type": ctype, "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "last_modified": hdr.get("Last-Modified"), "etag": hdr.get("ETag"),
                "content_disposition": hdr.get("Content-Disposition"),
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
                (tx / f"{sid}.txt").write_text(p.text(), encoding="utf-8")
                (tx / f"{sid}.links.json").write_text(json.dumps(links, ensure_ascii=False, indent=1), encoding="utf-8")
                rec.update({"charset": cs, "title": " ".join(p.title.split()), "text_chars": len(p.text()),
                            "text": str((tx / f"{sid}.txt").relative_to(ROOT)).replace("\\", "/"), "n_links": len(links)})
        except Exception as e:  # noqa: BLE001
            rec["error"] = repr(e)
        log.append(rec)
        (OUT / f"{name}_{ts}.json").write_text(
            json.dumps({"set": name, "fetched_at_local": ts, "user_agent": UA, "results": log}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        print(json.dumps({k: rec.get(k) for k in ("id", "status", "bytes", "last_modified", "title", "error")}, ensure_ascii=False))


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")
    if not argv or argv[0] == "--list":
        for k, v in SETS.items():
            print(k, len(v))
        return 0
    for name in argv:
        if name not in SETS:
            print("unknown set:", name)
            return 2
    for i, name in enumerate(argv):
        if i:
            time.sleep(WAIT)
        ts = time.strftime("%Y%m%d-%H%M%S")
        run_set(name, SETS[name], ts)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

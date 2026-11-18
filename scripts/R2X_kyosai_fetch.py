"""R2X_kyosai: 共済組合（国家公務員・地方公務員・私学）の被扶養者の認定基準と、住所が別の家族（単身赴任・別居の学生）・
住民税の課税市町村に関する一次情報（財務省の運用方針、各共済の公表資料、総務省の要領・取扱通知）を取得し、取得記録を残す。

実行: python -I -X utf8 scripts/R2X_kyosai_fetch.py <set名> [<set名> ...]
      python -I -X utf8 scripts/R2X_kyosai_fetch.py --list
- 取得したファイルは信頼できないデータとして、取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_R2X_kyosai_<set>/ に置く（その中でインタプリタやツールを実行しない）。
- HTML から抽出したテキストとリンクは、別の新しいディレクトリ .work/text/<ts>_R2X_kyosai_<set>/ に置く。
- 取得記録（ステータス、Last-Modified、ETag、SHA-256、タイトル）は scripts/results/R2X_kyosai_fetch/<set>_<ts>.json に書く。
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
OUT = ROOT / "scripts" / "results" / "R2X_kyosai_fetch"

# id -> url。id はファイル名に使う。
SETS = {
    # 財務省：国家公務員共済組合法等の運用方針（昭和34年10月1日蔵計第2927号）の現行版と、通達の一覧
    "mof": {
        "mof_unyo_hoshin_R080801": "https://www.mof.go.jp/about_mof/act/kokuji_tsuutatsu/tsuutatsu/TU-19591001-2927-11.pdf",
        "mof_tsuutatsu_index": "https://www.mof.go.jp/about_mof/act/kokuji_tsuutatsu/tsuutatsu/index.html",
        "mof_kokuji_tsuutatsu_index": "https://www.mof.go.jp/about_mof/act/kokuji_tsuutatsu/index.html",
    },
    # 財務省 通達の年代別一覧（運用方針の改正の履歴を探すため）
    "mof_lists": {
        "mof_tsuutatsu_r": "https://www.mof.go.jp/about_mof/act/kokuji_tsuutatsu/tsuutatsu/tsuutatsu_r.htm",
        "mof_tsuutatsu_s": "https://www.mof.go.jp/about_mof/act/kokuji_tsuutatsu/tsuutatsu/tsuutatsu_s.htm",
    },
    # 運用方針の旧版（裁判所共済組合の掲載。令和5年3月28日現在）：改正の前後の比較のため
    "unyo_old": {
        "courts_unyo_hoshin_R050328": "https://www.kyousai.courts.or.jp/files/user/img/houki/1-01.pdf",
    },
    # 私学共済（日本私立学校振興・共済事業団）
    "pmac": {
        "pmac_hifuyosya_01": "https://www.pmac.shigaku.go.jp/annai/shikaku/hifuyosya/hifuyosya_01/index.html",
        "pmac_hifuyosya_02": "https://www.pmac.shigaku.go.jp/annai/shikaku/hifuyosya/hifuyosya_02/index.html",
        "pmac_hifuyosya_03": "https://www.pmac.shigaku.go.jp/annai/shikaku/hifuyosya/hifuyosya_03/index.html",
        "pmac_hifuyosya_04": "https://www.pmac.shigaku.go.jp/annai/shikaku/hifuyosya/hifuyosya_04/index.html",
        "pmac_hifuyosya_05": "https://www.pmac.shigaku.go.jp/annai/shikaku/hifuyosya/hifuyosya_05/index.html",
        "pmac_qa_29": "https://www.pmac.shigaku.go.jp/qa/detail/qa_29.html",
        "pmac_qa_37": "https://www.pmac.shigaku.go.jp/qa/detail/qa_37.html",
        "pmac_dl_shikaku_06": "https://www.pmac.shigaku.go.jp/dl/category/shikaku/shikaku_06.html",
    },
    # 地方公務員の共済組合（地方職員共済組合の支部、公立学校共済組合の支部、市町村職員共済組合）の公表資料
    "chiho": {
        "osaka_chikyosai_19_23": "https://osaka.chikyosai.or.jp/upload/files/%E3%80%90%E7%B5%84%E5%90%88%E5%93%A1%E3%80%9119%E6%AD%B3%E4%BB%A5%E4%B8%8A23%E6%AD%B3%E6%9C%AA%E6%BA%80%E3%81%AE%E8%A2%AB%E6%89%B6%E9%A4%8A%E8%80%85%E3%81%AE%E5%8F%8E%E5%85%A5%E9%99%90%E5%BA%A6%E9%A1%8D%E5%A4%89%E6%9B%B4%E3%81%AB%E3%81%A4%E3%81%84%E3%81%A6%EF%BC%88%E9%80%9A%E7%9F%A5%EF%BC%89%284%29.pdf",
        "osaka_chikyosai_unyo_kaisei_gaiyo": "https://osaka.chikyosai.or.jp/upload/files/%E5%9C%B0%E6%96%B9%E5%85%AC%E5%8B%99%E5%93%A1%E7%AD%89%E5%85%B1%E6%B8%88%E7%B5%84%E5%90%88%E6%B3%95%E9%81%8B%E7%94%A8%E6%96%B9%E9%87%9D%E3%81%AE%E4%B8%80%E9%83%A8%E6%94%B9%E6%AD%A3%E6%A1%88%E3%81%AE%E6%A6%82%E8%A6%81%E3%81%AB%E3%81%A4%E3%81%84%E3%81%A6.pdf",
        "kouritu_oita_tebiki": "https://www.kouritu.or.jp/oita/content/files/181cab2cc9686290fc920ece58333d94.pdf",
        "kouritu_shizuoka_480": "https://www.kouritu.or.jp/shizuoka/content/files/tetsuduki/kyosai/hifuyo/hihuyousya_480%20nenkashunyu.pdf",
        "kouritu_hiroshima_syunyu": "https://www.kouritu.or.jp/hiroshima/tetsuduki/kyosai/fuyosha/syunyuhanteisheet/index.html",
        "miyagi_shichoson_hihuyousha": "https://www.kyosai-miyagi.or.jp/pdf/hihuyousha.pdf",
        "fukuoka_shichoson_toriatsukai": "https://fukuoka-kyosai.jp/reiki_int/reiki_honbun/x650RG00000067.html",
        "nagasaki_chikyosai_law": "https://nagasaki.chikyosai.or.jp/about/law/",
    },
    # 国家公務員の共済組合の公表資料（連合会・各省の組合）
    "kokka": {
        "kkr_top": "https://www.kkr.or.jp/",
        "monkakyosai_shikumi_04": "https://www.monkakyosai.or.jp/shikumi/04.html",
        "yuseikyosai_nintei_shunyu_kijun": "https://www.yuseikyosai.or.jp/shikumi/docs/nintei_shunyu_kijun.pdf",
    },
    # 追加：公立学校共済組合静岡支部の事例ページ（同一世帯・別居の父母）、地方職員共済組合本部、公立学校共済組合本部の 19〜23歳の案内
    "chiho2": {
        "kouritu_shizuoka_rei_shinzoku": "https://www.kouritu.or.jp/shizuoka/tetsuduki/kyosai/hifuyo/rei/shinzoku/index.html",
        "kouritu_shizuoka_rei_fubo": "https://www.kouritu.or.jp/shizuoka/tetsuduki/kyosai/hifuyo/rei/fubo/index.html",
        "chikyosai_short_02": "https://www.chikyosai.or.jp/division/short/02.html",
        "kouritu_topics_fuyou_20250812": "https://www.kouritu.or.jp/topics/kumiai/fuyou_20250812/index.html",
    },
    # 追加：警察共済組合（地方公務員等共済組合法第3条第1項第3号の組合。2026-11-09 検証で注記を訂正：もとは「経済産業省共済組合」）と、財務省共済組合の規則集（国家公務員）
    "kokka2": {
        "keikyo_kenpo_621": "https://www.keikyo.jp/kenpo/621.html",
        "mofkyosai_reg_155": "http://mofkyosai.gijiroku.com/mofqa/reg_view_honbun.asp?RMODE=1&ISrchID=155",
    },
    # 対照：協会けんぽの被扶養者資格の再確認 FAQ（単身赴任・海外赴任の扱い）。既存の成果で取得済みのものを、この調査の記録として再取得する
    "kyokai_contrast": {
        "kyokai_faq_dependent_status": "https://www.kyoukaikenpo.or.jp/faq/dependent_status/",
    },
    # 総務省：住民基本台帳事務処理要領（住所の認定）と、地方税法の取扱通知（市町村税関係）の改正後全文
    "soumu": {
        "soumu_yoryo_001094645": "https://www.soumu.go.jp/main_content/001094645.pdf",
        "soumu_toriatsukai_shichoson_001071661": "https://www.soumu.go.jp/main_content/001071661.pdf",
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
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_kyosai_{name}"
    dl.mkdir(parents=True, exist_ok=False)
    tx = ROOT / ".work" / "text" / f"{ts}_R2X_kyosai_{name}"
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

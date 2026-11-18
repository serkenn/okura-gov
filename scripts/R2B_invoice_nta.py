"""R2B invoice: 国税庁の通達・タックスアンサー・Q&A・パンフレットのうち、消費税の納税義務・インボイス（適格請求書発行事業者の登録）
と、所得税の計算での消費税等の経理処理（税込経理・税抜経理、納付税額・還付税額の計上時期）に関係するページを取得し、
本文のテキストとリンクを取り出す。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_invoice_nta.py --robots
      robots.txt を取得し、SETS のすべての URL が User-Agent okura-gov-research/0.1 で許されるかを判定（robots_check.json）
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_invoice_nta.py <set> [<set> ...]
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_invoice_nta.py --list

- HTML の取得とテキスト化は scripts/R2X_aoiro_nta.py を写した（import はしない）。
- 取得したもの（HTML・PDF）は信頼できないデータとして、取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_R2B_invoice_nta_<set>/ に置く。その中でインタプリタやツールは実行しない。
- HTML から取り出したテキストとリンクは scripts/results/R2B_invoice_nta/<set>/<id>.txt / <id>.links.json に書く。
  画像で表示される文字は img の alt を〔alt:...〕の形で残す。
- PDF はテキスト化しない（ダウンロード先のパスと SHA-256 だけを記録し、人が Read ツールの pages 指定で読む）。
- 取得記録（ステータス、Content-Type、Last-Modified、SHA-256、バイト数）は scripts/results/R2B_invoice_nta/<set>/fetch_log.json。
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。官報は取得しない。
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
OUT = ROOT / "scripts" / "results" / "R2B_invoice_nta"

NTA = "https://www.nta.go.jp"
TA_SHOHI = NTA + "/taxes/shiraberu/taxanswer/shohi/"
TA_SHOTOKU = NTA + "/taxes/shiraberu/taxanswer/shotoku/"
INV = NTA + "/taxes/shiraberu/zeimokubetsu/shohi/keigenzeiritsu/"
SETS = {
    # 1回目：所得税の経理通達（直所3-8）とその改正、タックスアンサー、インボイスの特集・令和8年度改正の資料
    "pages": {
        "tsutatsu_890329": NTA + "/law/tsutatsu/kobetsu/shotoku/shinkoku/890329/01.htm",  # 消費税法等の施行に伴う所得税の取扱いについて
        "tsutatsu_890329_kaisei_r03": NTA + "/law/tsutatsu/kobetsu/shotoku/shinkoku/kaisei/2102xx/pdf/01.pdf",  # 令和3年の改正
        "ta_6909": TA_SHOHI + "6909.htm",  # 消費税等の経理処理（タックスアンサー）
        "ta_6501": TA_SHOHI + "6501.htm",  # 納税義務の免除
        "ta_shohi_index": NTA + "/taxes/shiraberu/taxanswer/code/bunya-shohizei.htm",  # タックスアンサー 分野別（消費税）
        "faq_keiri": NTA + "/law/joho-zeikaishaku/hojin/shouhizei_faq/01.htm",  # 令和3年改正消費税経理通達関係Q&A（目次）
        "invoice_review": INV + "invoice-review/index.htm",  # インボイス経過措置の見直し等（令和8年度税制改正）
        "invoice_top": INV + "invoice.htm",  # インボイス制度 特設サイト
        "pamph_r08kaisei": NTA + "/publication/pamph/shohi/kaisei/pdf/r08kaisei.pdf",  # 令和8年度 消費税の改正のあらまし（PDF）
        "pamph_0026004_066": INV + "pdf/0026004-066_01.pdf",  # 検索で見つかったインボイスの資料（PDF）
    },
    # 2回目：1回目のリンクから見つけたページと、所得税の手引き（令和7年分）
    "pages2": {
        "tsutatsu_menu": NTA + "/law/tsutatsu/menu.htm",  # 法令解釈通達の目次
        "ta_6913": TA_SHOHI + "6913.htm",  # 税抜経理と税込経理の併用と経理処理
        "ta_index2": NTA + "/taxes/shiraberu/taxanswer/index2.htm",  # タックスアンサー目次
        "invoice_faq": INV + "invoice_faq.htm",  # 通達Q&A等
        "invoice_2tokurei": INV + "invoice_2tokurei.htm",  # 2割特例特設ページ
        "leaflet_r08": INV + "invoice-review/pdf/0026004-099-01-1.pdf",  # R8改正リーフレット
        "invoice_review_print": INV + "invoice-review/pdf/0026004-099-01-2.pdf",  # 特集ページ印刷用
        "shushi_kakikata_r07": NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/pdf/034.pdf",  # 令和7年分収支内訳書（一般用）の書き方
        "aoiro_tebiki_r07": NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/pdf/025.pdf",  # 令和7年分青色申告の決算の手引き（一般用）
        "shiro_tebiki_r07": NTA + "/taxes/shiraberu/shinkoku/kojin_jigyo/kichou09.pdf",  # 令和7年分白色申告者の決算の手引き（一般用）
    },
}


class Page(html.parser.HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "dt", "dd", "table", "th", "td"}

    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base, self.parts, self.skip, self.links, self._a = base, [], 0, [], None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self.skip += 1
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag in ("td", "th"):
            self.parts.append(" | ")
        if tag == "img" and a.get("alt") and not self.skip:
            self.parts.append(f"〔alt:{a['alt']}〕")
            if self._a is not None:
                self._a["text"] += f"〔alt:{a['alt']}〕"
        if tag == "a" and a.get("href"):
            self._a = {"href": urllib.parse.urljoin(self.base, a["href"]), "text": ""}

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "a" and self._a is not None:
            self._a["text"] = re.sub(r"\s+", " ", self._a["text"]).strip()
            self.links.append(self._a)
            self._a = None

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)
            if self._a is not None:
                self._a["text"] += data

    def text(self):
        t = "".join(self.parts).replace("\r", "")
        t = re.sub(r"[ \t\u3000]*\n[ \t\u3000]*", "\n", t)
        return re.sub(r"\n{2,}", "\n", t).strip()


def decode(body, ctype):
    m = re.search(rb'charset=["\']?([A-Za-z0-9_\-]+)', body[:2048])
    enc = m.group(1).decode() if m else None
    if not enc and ctype and "charset=" in ctype:
        enc = ctype.split("charset=")[-1]
    for e in [enc, "utf-8", "cp932"]:
        if not e:
            continue
        try:
            return body.decode("cp932" if e.lower() in ("shift_jis", "sjis", "x-sjis") else e), e
        except (UnicodeDecodeError, LookupError):
            continue
    return body.decode("utf-8", "replace"), "utf-8(replace)"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, r.read(), dict(r.headers), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers or {}), url


def run_set(name):
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2B_invoice_nta_{name}"
    dl.mkdir(parents=True, exist_ok=False)
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    log = {"set": name, "fetched_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "items": []}
    for key, url in SETS[name].items():
        try:
            st, body, hd, final = fetch(url)
        except Exception as e:  # noqa
            log["items"].append({"id": key, "url": url, "error": repr(e)})
            print("ERR", key, repr(e), flush=True)
            time.sleep(WAIT)
            continue
        ctype = hd.get("Content-Type", "")
        is_pdf = "pdf" in ctype.lower() or url.lower().endswith(".pdf")
        fn = dl / (key + (".pdf" if is_pdf else ".htm"))
        fn.write_bytes(body)
        item = {"id": key, "url": url, "final_url": final, "status": st, "content_type": ctype, "last_modified": hd.get("Last-Modified"),
                "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(), "saved": str(fn.relative_to(ROOT)).replace("\\", "/")}
        if is_pdf:
            item["pdf_header_ok"] = body[:5] == b"%PDF-"
        if not is_pdf and st == 200:
            text, enc = decode(body, ctype)
            p = Page(final)
            p.feed(text)
            title = re.search(r"<title>(.*?)</title>", text, re.S)
            item["title"] = re.sub(r"\s+", " ", title.group(1)).strip() if title else None
            item["encoding"] = enc
            (out / f"{key}.txt").write_text(f"# source={url}\n# final_url={final}\n# fetched_at={ts}\n# last_modified={hd.get('Last-Modified')}\n# sha256={item['sha256']}\n\n{p.text()}\n", encoding="utf-8")
            (out / f"{key}.links.json").write_text(json.dumps(p.links, ensure_ascii=False, indent=1), encoding="utf-8")
        log["items"].append(item)
        print("ok", key, st, len(body), item.get("title"), flush=True)
        time.sleep(WAIT)
    (out / "fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


def check_robots():
    import urllib.robotparser
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2B_invoice_nta_robots"
    dl.mkdir(parents=True, exist_ok=False)
    st, body, hd, _ = fetch(NTA + "/robots.txt")
    (dl / "robots.txt").write_bytes(body)
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(body.decode("utf-8", "replace").splitlines())
    res = {"fetched_at": ts, "url": NTA + "/robots.txt", "status": st, "sha256": hashlib.sha256(body).hexdigest(),
           "saved": str((dl / "robots.txt").relative_to(ROOT)).replace("\\", "/"),
           "disallow_lines": [ln.strip() for ln in body.decode("utf-8", "replace").splitlines() if ln.strip().lower().startswith("disallow")],
           "urls": {}}
    for name, items in SETS.items():
        for key, url in items.items():
            res["urls"][f"{name}/{key}"] = {"url": url, "allowed": rp.can_fetch(UA, url)}
    res["all_allowed"] = all(v["allowed"] for v in res["urls"].values())
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "robots_check.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("robots", st, "all_allowed", res["all_allowed"], res["disallow_lines"])


def main():
    args = sys.argv[1:]
    if args == ["--robots"]:
        check_robots()
        return
    if not args or args == ["--list"]:
        for k, v in SETS.items():
            print(k, len(v))
        return
    for a in args:
        run_set(a)


if __name__ == "__main__":
    main()

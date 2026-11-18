"""IMPL2 kyuyo-jiki: 国税庁の通達・質疑応答事例・手引・年末調整のしかたのうち、給与所得の収入すべき時期（所基通36−9 ほか）、
未払の給与・年をまたぐ給与、死亡後に支給期の到来する給与（所基通9−17、相基通3−33）に関するページを取得し、本文のテキストとリンクを取り出す。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL2_kyuyo-jiki_nta.py --robots
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL2_kyuyo-jiki_nta.py <set> [<set> ...]
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL2_kyuyo-jiki_nta.py --list

- HTML の取得とテキスト化は scripts/IMPL2_tsukin_nta.py（その元は scripts/R3X_shibo-shukkoku_nta.py）を写した（import はしない）。
- 取得したもの（HTML・PDF）は信頼できないデータとして、取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_IMPL2_kyuyo-jiki_nta_<set>/ に置く。その中でインタプリタやツールは実行しない。
- HTML から取り出したテキストとリンクは scripts/results/IMPL2_kyuyo-jiki_nta/<set>/<id>.txt / <id>.links.json に書く。
- PDF はテキスト化しない（ダウンロード先のパスと SHA-256 だけを記録し、人が Read ツールの pages 指定で読む）。
- 取得記録は scripts/results/IMPL2_kyuyo-jiki_nta/<set>/fetch_log.json。
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。
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
OUT = ROOT / "scripts" / "results" / "IMPL2_kyuyo-jiki_nta"

NTA = "https://www.nta.go.jp"
KIHON = NTA + "/law/tsutatsu/kihon/shotoku/"
SETS = {
    # 1回目：所得税基本通達（URL は scripts/results/IMPL_jigyo_nta/ta_index/kihon_shotoku_index.links.json の目次から）、
    # 相続税法基本通達・質疑応答事例（URL は WebSearch の結果から）
    "pages": {
        "kihon_05_01": KIHON + "05/01.htm",    # 法第36条関係〔収入金額〕〔収入金額の収入すべき時期〕
        "kihon_02_04": KIHON + "02/04.htm",    # 法第9条関係（第17号：相続等により取得するもの。9−17）
        "kihon_04_03": KIHON + "04/03.htm",    # 法第28条《給与所得》関係
        "kihon_28_01": KIHON + "28/01.htm",    # 法第181条から第223条まで（源泉徴収）共通関係
        "kihon_31_01": KIHON + "31/01.htm",    # 法第183条《源泉徴収義務》関係
        "kihon_32_01": KIHON + "32/01.htm",    # 法第190条《年末調整》関係
        "sokihon_01_03": NTA + "/law/tsutatsu/kihon/sisan/sozoku2/01/03.htm",  # 相続税法基本通達〔退職手当金関係〕（3−33）
        "shitsugi_hotei_7_05": NTA + "/law/shitsugi/hotei/7/05.htm",  # 死亡後に支給期が到来する給与（法定調書）
        "shitsugi_hotei_7_16": NTA + "/law/shitsugi/hotei/7/16.htm",  # 死亡により退職した者の給与に係る源泉徴収票の交付
        "nencho2025_01": NTA + "/publication/pamph/gensen/nencho2025/01.htm",  # 令和7年分 年末調整のしかた（目次）
        "nencho2026_01": NTA + "/publication/pamph/gensen/nencho2026/01.htm",  # 令和8年分 年末調整のしかた（目次）
    },
    # 2回目：年末調整のしかたの「Ⅱ 年末調整とは」（年末調整の対象となる給与の説明を探す。URL は pages の
    # nencho2025_01.links.json・nencho2026_01.links.json の並び〔101＝表紙・目次、102＝Ⅰ、103＝Ⅱ〕から）
    "pdfs": {
        "nencho2025_103": NTA + "/publication/pamph/gensen/nencho2025/pdf/103.pdf",
        "nencho2026_103": NTA + "/publication/pamph/gensen/nencho2026/pdf/103.pdf",
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
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers or {})


def run_set(name):
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL2_kyuyo-jiki_nta_{name}"
    dl.mkdir(parents=True, exist_ok=False)
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    log = {"set": name, "fetched_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "items": []}
    for key, url in SETS[name].items():
        try:
            st, body, hd = fetch(url)
        except Exception as e:  # noqa
            log["items"].append({"id": key, "url": url, "error": repr(e)})
            print("ERR", key, repr(e), flush=True)
            time.sleep(WAIT)
            continue
        ctype = hd.get("Content-Type", "")
        is_pdf = "pdf" in ctype.lower() or url.lower().endswith(".pdf")
        fn = dl / (key + (".pdf" if is_pdf else ".htm"))
        fn.write_bytes(body)
        item = {"id": key, "url": url, "status": st, "content_type": ctype, "last_modified": hd.get("Last-Modified"),
                "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(), "saved": str(fn.relative_to(ROOT)).replace("\\", "/")}
        if is_pdf:
            item["pdf_header_ok"] = body[:5] == b"%PDF-"
        if not is_pdf and st == 200:
            text, enc = decode(body, ctype)
            p = Page(url)
            p.feed(text)
            title = re.search(r"<title>(.*?)</title>", text, re.S)
            item["title"] = re.sub(r"\s+", " ", title.group(1)).strip() if title else None
            item["encoding"] = enc
            (out / f"{key}.txt").write_text(f"# source={url}\n# fetched_at={ts}\n# last_modified={hd.get('Last-Modified')}\n# sha256={item['sha256']}\n\n{p.text()}\n", encoding="utf-8")
            (out / f"{key}.links.json").write_text(json.dumps(p.links, ensure_ascii=False, indent=1), encoding="utf-8")
        log["items"].append(item)
        print("ok", key, st, len(body), item.get("title"), flush=True)
        time.sleep(WAIT)
    (out / "fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


def check_robots():
    import urllib.robotparser
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL2_kyuyo-jiki_nta_robots"
    dl.mkdir(parents=True, exist_ok=False)
    st, body, hd = fetch(NTA + "/robots.txt")
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

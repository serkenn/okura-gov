"""IMPL6 web: impl-research6 の項目に関係する国税庁のページを取得する。
  - 棚卸資産・家事消費等・貸倒れ：所得税基本通達 39・47・51 の節、タックスアンサー、決算の手引き・収支内訳書の書き方。
  - 様式の欄：令和7年分 確定申告の手引き（特例適用条文・地震保険料控除の計算欄・住民税に関する事項・税額控除の欄・60 の欄）、
    分離課税用・損失申告用の手引き、医療費控除の明細書の医療費通知の欄。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL6_tanaoroshi_web_fetch.py <set> [<set> ...]
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL6_tanaoroshi_web_fetch.py --list

- scripts/IMPL5_web_fetch.py を写し、SETS・NAME・説明だけを変えた（import はしない）。robots.txt はホストごとに確かめ、
  許されていない URL は取得しない（記録だけする）。
- 取得したもの（HTML・PDF）は信頼できないデータとして、取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_IMPL6_tanaoroshi_web_fetch_<set>/ に置く。その中でインタプリタやツールは実行しない。
- HTML から取り出したテキストとリンクは scripts/results/IMPL6_tanaoroshi_web_fetch/<set>/<id>.txt / <id>.links.json に書く。
- 国税庁のサイトは無いページにも HTTP 200 とエラーページを返す（docs/measurements/20261109_impl-prep_iryohi-fetch-and-forms.md）。
  タイトルが「指定されたページを表示できませんでした」なら item に not_found: true を付ける。
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
import urllib.robotparser

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
WAIT = 1.5
NAME = "IMPL6_tanaoroshi_web_fetch"
OUT = ROOT / "scripts" / "results" / NAME

NTA = "https://www.nta.go.jp"
KIHON = NTA + "/law/tsutatsu/kihon/shotoku"
TEBIKI = NTA + "/taxes/shiraberu/shinkoku/tebiki/2025"
TA = NTA + "/taxes/shiraberu/taxanswer/shotoku"
SETS = {
    "index": {
        "kihon_index": KIHON + "/01.htm",
        "tebiki_index": TEBIKI + "/index.htm",
    },
}
# 2回目以後のセット（index の結果のリンクから決めた URL。docs/measurements/20261112_impl-research6_tanaoroshi-fetch-and-checks.md §1）
SETS_FILE = OUT / "sets.json"


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


_ROBOTS = {}


def robots_allowed(url, dl, log):
    host = urllib.parse.urlsplit(url)
    base = f"{host.scheme}://{host.netloc}"
    if base not in _ROBOTS:
        st, body, hd, _ = fetch(base + "/robots.txt")
        (dl / f"robots_{host.netloc}.txt").write_bytes(body)
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(body.decode("utf-8", "replace").splitlines() if st == 200 else [])
        _ROBOTS[base] = rp
        log["robots"].append({"host": base, "status": st, "sha256": hashlib.sha256(body).hexdigest()})
        time.sleep(WAIT)
    return _ROBOTS[base].can_fetch(UA, url)


def all_sets():
    sets = dict(SETS)
    if SETS_FILE.exists():
        sets.update(json.loads(SETS_FILE.read_text(encoding="utf-8")))
    return sets


def run_set(name):
    urls = all_sets()[name]
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_{NAME}_{name}"
    dl.mkdir(parents=True, exist_ok=False)
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    log = {"set": name, "fetched_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "robots": [], "items": []}
    for key, url in urls.items():
        if not robots_allowed(url, dl, log):
            log["items"].append({"id": key, "url": url, "skipped": "robots.txt で許されていない"})
            print("skip(robots)", key, flush=True)
            continue
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
            item["not_found"] = bool(item["title"] and "指定されたページを表示できませんでした" in item["title"])
            item["encoding"] = enc
            (out / f"{key}.txt").write_text(f"# source={url}\n# final_url={final}\n# fetched_at={ts}\n# last_modified={hd.get('Last-Modified')}\n"
                                            f"# sha256={item['sha256']}\n\n{p.text()}\n", encoding="utf-8")
            (out / f"{key}.links.json").write_text(json.dumps(p.links, ensure_ascii=False, indent=1), encoding="utf-8")
        log["items"].append(item)
        print("ok", key, st, len(body), item.get("title"), flush=True)
        time.sleep(WAIT)
    (out / f"fetch_log_{ts}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    args = sys.argv[1:]
    if not args or args == ["--list"]:
        for k, v in all_sets().items():
            print(k, len(v))
        return
    for a in args:
        run_set(a)


if __name__ == "__main__":
    main()

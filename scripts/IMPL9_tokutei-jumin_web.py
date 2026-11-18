"""IMPL9 tokutei-jumin web: 第一表の給与の「区分」・第二表の「特例適用条文等」に書くもの（手引き・記入要領・明細書）と、
給与所得者の特定支出に関する明細書の e-Tax の様式ID・欄（e-Tax の仕様書の一覧）、総務省の取扱通知を取得する。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL9_tokutei-jumin_web.py <set> [<set> ...]
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL9_tokutei-jumin_web.py --list

- scripts/IMPL8_tokutei-shishutsu_web.py を写し、SETS・NAME・説明を変え、zip・xlsx・xls も保存するようにした（import はしない）。
  robots.txt はホストごとに確かめ、許されていない URL は取得しない（記録だけする）。
- 取得したもの（HTML・PDF・zip）は信頼できないデータとして、取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_IMPL9_tokutei-jumin_web_<set>/ に置く。その中でインタプリタやツールは実行しない。
- HTML から取り出したテキストとリンクは scripts/results/IMPL9_tokutei-jumin_web/<set>/<id>.txt / <id>.links.json に書く。
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
NAME = "IMPL9_tokutei-jumin_web"
OUT = ROOT / "scripts" / "results" / NAME

NTA = "https://www.nta.go.jp"
ETAX = "https://www.e-tax.nta.go.jp"
SETS = {
    # 手引き（令和7年分）3-2_06 給与所得、様式変更に伴う記入要領、記入要領の変更点、記載例（給与所得者）、明細書の様式
    "nta": {
        "tebiki_2025_3_2_06": NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/03/order2/3-2_06.htm",
        "tebiki_2025_001_1": NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/pdf/001-1.pdf",
        "tebiki_2025_O1_1": NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/pdf/O/O1-1.pdf",
        "kisairei_kyuyo": NTA + "/taxes/shiraberu/shinkoku/kisairei/pdf/kyuyo.pdf",
        "yoshiki_039": NTA + "/taxes/shiraberu/shinkoku/yoshiki/02/pdf/039.pdf",
    },
    # e-Tax の仕様書の一覧（帳票フィールド仕様書・XML 構造設計書の置き場所を探す）
    "etax": {
        "shiyo_index": ETAX + "/shiyo/index.htm",
        "shiyo3": ETAX + "/shiyo/shiyo3.htm",  # 2026-11-12 は 404（一覧は ksk2_shiyo3.htm）
    },
    # e-Tax 仕様書一覧（shiyo_index のリンク）
    "etax2": {
        "ksk2_shiyo3": ETAX + "/shiyo/ksk2/ksk2_shiyo3.htm",
    },
    # ksk2_shiyo3 の 7「手続一覧・手続内帳票対応表・対象帳票一覧」と 9「XML構造設計書及び帳票フィールド仕様書【所得税関係】」（CAB）
    "etax3": {
        "e-tax07": ETAX + "/shiyo/ksk2/download/e-tax07.CAB",
        "e-tax09": ETAX + "/shiyo/ksk2/download/e-tax09.CAB",
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
        with urllib.request.urlopen(req, timeout=600) as r:
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


BINARY = (".pdf", ".zip", ".xlsx", ".xls", ".cab")


def run_set(name, items=None):
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_{NAME}_{name}"
    dl.mkdir(parents=True, exist_ok=False)
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    log = {"set": name, "fetched_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "robots": [], "items": []}
    for key, url in (items or SETS[name]).items():
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
        ext = next((x for x in BINARY if url.lower().endswith(x)), None)
        if ext is None and "pdf" in ctype.lower():
            ext = ".pdf"
        fn = dl / (key + (ext or ".htm"))
        fn.write_bytes(body)
        item = {"id": key, "url": url, "final_url": final, "status": st, "content_type": ctype, "last_modified": hd.get("Last-Modified"),
                "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(), "saved": str(fn.relative_to(ROOT)).replace("\\", "/")}
        if ext == ".pdf":
            item["pdf_header_ok"] = body[:5] == b"%PDF-"
        if ext in (".zip", ".xlsx"):
            item["zip_header_ok"] = body[:2] == b"PK"
        if ext is None and st == 200:
            text, enc = decode(body, ctype)
            p = Page(final)
            p.feed(text)
            title = re.search(r"<title>(.*?)</title>", text, re.S)
            item["title"] = re.sub(r"\s+", " ", title.group(1)).strip() if title else None
            item["encoding"] = enc
            (out / f"{key}.txt").write_text(f"# source={url}\n# final_url={final}\n# fetched_at={ts}\n# last_modified={hd.get('Last-Modified')}\n"
                                            f"# sha256={item['sha256']}\n\n{p.text()}\n", encoding="utf-8")
            (out / f"{key}.links.json").write_text(json.dumps(p.links, ensure_ascii=False, indent=1), encoding="utf-8")
        log["items"].append(item)
        print("ok", key, st, len(body), item.get("title"), flush=True)
        time.sleep(WAIT)
    (out / f"fetch_log_{ts}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", dl)


def main():
    args = sys.argv[1:]
    if not args or args == ["--list"]:
        for k, v in SETS.items():
            print(k, len(v))
        return
    for a in args:
        run_set(a)


if __name__ == "__main__":
    main()

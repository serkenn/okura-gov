"""R2X juminzei-tax: 個人住民税の税額の計算に関する行政の公開資料（総務省・自治体の案内）を取得し、本文をテキストにする。

実行:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_juminzei-tax_web.py            # 全部
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_juminzei-tax_web.py <名前>...   # 指定したものだけ

標準ライブラリのみ。リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。取得の前にホストごとに robots.txt を読み、禁止なら取得しない。
- ダウンロードしたもの（信頼できないデータ）は .work/downloads/<ts>_R2X_juminzei-tax_web/ に置く。中でコードを実行しない。
- HTML は html.parser でテキストにして scripts/results/R2X_juminzei-tax_web/<名前>.txt に書く（script・style は除く）。PDF は保存だけ（Read ツールで人が読む）。
- fetch_log*.json に URL、HTTP 状態、バイト数、SHA-256、robots.txt の可否を書く。
"""
import hashlib
import html.parser
import json
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
SLEEP = 1.5
NAME = "R2X_juminzei-tax_web"

TARGETS = [
    # 総務省「超過課税の状況」（標準税率と異なる税率の実例）
    ("soumu_choka", "https://www.soumu.go.jp/main_sosiki/jichi_zeisei/czaisei/czaisei_seido/149767_25.html"),
    # 自治体の計算例（端から端までの読みの照合に使う。E）
    ("nagoya_keisanrei", "https://www.city.nagoya.jp/kurashi/zeikin/1037356/1011880/1011883/1011891.html"),
    ("yokohama_keisan", "https://www.city.yokohama.lg.jp/kurashi/koseki-zei-hoken/zeikin/y-shizei/kojin-shiminzei-kenminzei/kojin-shiminzei-shosai/kojinkeisan.html"),
    ("yokohama_zeigakukoujo", "https://www.city.yokohama.lg.jp/kurashi/koseki-zei-hoken/zeikin/y-shizei/kojin-shiminzei-kenminzei/kojin-shiminzei-shosai/zeigakukoujoR2.html"),
    ("chuo_zeigakukoujo", "https://www.city.chuo.lg.jp/a0009/kurashi/zeikin/juuminzei/zeigakukoujo.html"),
    ("wakayama_zeigakukoujo", "https://www.pref.wakayama.lg.jp/prefg/010500/kenzei/kojinkenmin/kojinkenmin_zeigakukojo.html"),
]


class Text(html.parser.HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section", "article", "dt", "dd"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        if tag in self.BLOCK:
            self.out.append("\n")
        if tag in ("td", "th"):
            self.out.append(" | ")
        if tag == "img":
            alt = dict(attrs).get("alt") or ""
            if len(alt) > 20:  # 画像の代替テキストに本文が入っているページ（総務省の超過課税の状況）がある
                self.out.append("\n[画像の代替テキスト] " + alt + "\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.skip:
            self.skip -= 1
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)

    def text(self):
        lines = [" ".join(l.split()) for l in "".join(self.out).splitlines()]
        res, blank = [], 0
        for l in lines:
            if l:
                res.append(l)
                blank = 0
            elif not blank:
                res.append("")
                blank = 1
        return "\n".join(res)


def decode(body, ctype):
    cs = None
    if "charset=" in (ctype or "").lower():
        cs = ctype.lower().split("charset=")[1].split(";")[0].strip()
    head = body[:4000].decode("ascii", "replace").lower()
    if not cs and "charset=" in head:
        cs = head.split("charset=")[1].split('"')[0].split("'")[0].split(";")[0].strip().strip("/").strip(">")
    for c in [cs, "utf-8", "cp932", "euc-jp"]:
        if not c:
            continue
        try:
            return body.decode(c), c
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", "replace"), "utf-8(replace)"


def main():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_{NAME}"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / NAME
    out.mkdir(parents=True, exist_ok=True)
    only = set(sys.argv[1:])
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "fetches": []}
    robots = {}
    for name, url in TARGETS:
        if only and name not in only:
            continue
        host = urllib.parse.urlsplit(url)
        base = f"{host.scheme}://{host.netloc}"
        if base not in robots:
            rp = urllib.robotparser.RobotFileParser()
            rurl = base + "/robots.txt"
            try:
                req = urllib.request.Request(rurl, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=60) as r:
                    rp.parse(r.read().decode("utf-8", "replace").splitlines())
                    robots[base] = (rp, r.status)
            except urllib.error.HTTPError as e:
                rp.parse([])
                robots[base] = (rp, e.code)
            except Exception as e:  # noqa
                rp.parse([])
                robots[base] = (rp, repr(e))
            time.sleep(SLEEP)
        rp, rst = robots[base]
        allowed = rp.can_fetch(UA, url)
        entry = {"name": name, "url": url, "robots_status": rst, "robots_allowed": allowed}
        if not allowed:
            entry["skipped"] = "robots.txt disallow"
            log["fetches"].append(entry)
            print("skip", name, flush=True)
            continue
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                body, st, ctype, final = r.read(), r.status, r.headers.get("Content-Type"), r.geturl()
        except urllib.error.HTTPError as e:
            body, st, ctype, final = e.read(), e.code, e.headers.get("Content-Type"), url
        time.sleep(SLEEP)
        ext = ".pdf" if (ctype or "").startswith("application/pdf") or url.lower().endswith(".pdf") else ".html"
        (dl / f"{name}{ext}").write_bytes(body)
        entry.update({"status": st, "final_url": final, "content_type": ctype, "bytes": len(body),
                      "sha256": hashlib.sha256(body).hexdigest(), "saved": f"{name}{ext}"})
        if ext == ".html":
            s, cs = decode(body, ctype)
            p = Text()
            p.feed(s)
            (out / f"{name}.txt").write_text(f"# {url}\n# 取得 {ts} 状態 {st} 文字コード {cs}\n\n" + p.text() + "\n", encoding="utf-8")
            entry["charset"] = cs
        log["fetches"].append(entry)
        print("ok", name, st, len(body), flush=True)
    (out / ("fetch_log.json" if not only else f"fetch_log_{'_'.join(sorted(only))}.json")).write_text(
        json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", out)


if __name__ == "__main__":
    sys.exit(main())

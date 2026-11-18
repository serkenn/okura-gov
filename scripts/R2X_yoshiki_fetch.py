"""R2X_yoshiki_fetch: 申告書の様式の欄の対応（第2ラウンド、トピック yoshiki）のため、
国税庁・e-Tax の公開ページ・様式 PDF を GET で取得し、取得の記録を残す。HTML は本文テキストとリンクの一覧にする。

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_yoshiki_fetch.py <name> <URL> [<URL> ...]
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_yoshiki_fetch.py <name> --list <URLの一覧ファイル>
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_yoshiki_fetch.py --render <.work/downloads/のディレクトリ> <出力名>
    （取得済みの HTML を取り直さずに本文テキストへ書き直す。手引きの欄番号の画像の alt を〔〕で本文に入れる）

- scripts/IMPL_output_fetch.py の形（robots.txt の確認、他ホストへのリダイレクトの禁止、HTML の本文とリンクの書き出し）を写して作った
  （import はしない）。標準ライブラリのみ。
- GET だけを行う。フォームの送信・POST・ログインはしない。Cookie は保存・送信しない。
- 対象のホストは ALLOWED_HOSTS だけ。他のホストへのリダイレクトは止める。
- 各ホストの robots.txt を実行ごとに1回取得し、urllib.robotparser で許可されない URL は取得しない
  （robots.txt が 404 のホストは「制限なし」として扱い、その旨をログに残す）。
- 取得したファイルは信頼できないデータとして、実行ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_R2X_yoshiki_<name>/ に置く。中身は実行しない。
- 1ファイル MAX_BYTES を超える応答は途中で読むのをやめ、保存しない（記録だけ残す）。
- リクエストの間は DELAY 秒あける。User-Agent は okura-gov-research/0.1。
- 出力：scripts/results/R2X_yoshiki_fetch/fetch_<ts>_<name>.json（URL、最終URL、HTTP 状態、Content-Type、
  Last-Modified、サイズ、SHA-256、保存名）と、HTML の本文 scripts/results/R2X_yoshiki_fetch/<ts>_<name>/*.txt・*.links.tsv。
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
DELAY = 1.5
MAX_PER_RUN = 40
MAX_BYTES = 40 * 1024 * 1024
ALLOWED_HOSTS = {"www.nta.go.jp", "www.e-tax.nta.go.jp", "www.keisan.nta.go.jp"}
OUT = ROOT / "scripts" / "results" / "R2X_yoshiki_fetch"


class NoOtherHostRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = urllib.parse.urlsplit(newurl).hostname
        if host not in ALLOWED_HOSTS:
            raise urllib.error.HTTPError(newurl, code, f"redirect to other host blocked: {newurl}", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(NoOtherHostRedirect())


class Text(html.parser.HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "dt", "dd", "table", "th", "td",
             "caption", "section", "article", "ul", "ol", "dl"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip, self.links, self._a = [], 0, [], None

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag in ("th", "td"):
            self.parts.append("| ")
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self._a = [re.sub(r";jsessionid=[^?#]*", "", href), []]
        if tag == "img" and not self.skip:
            # 手引き（HTML 版）は欄番号（丸数字・丸カナ）を画像で出し、alt に番号を入れている（class="izon"）。
            # 本文から欄番号が落ちないよう、alt を〔〕で囲んで本文に入れる。
            # alt と画像のファイル名の番号が食い違うページがある（例：alt="10" で src=.../izon/13.gif）。
            # 画像に描かれているのはファイル名の番号と考え、数字のファイル名ならそれを使い、alt が違えば併記する。
            a = dict(attrs)
            if "izon" in (a.get("class") or "") or re.search(r"/izon/", a.get("src") or ""):
                alt = a.get("alt") or ""
                m = re.search(r"/izon/(\d+)[^/]*$", a.get("src") or "")
                if m:
                    num = str(int(m.group(1)))
                    self.parts.append(f"〔{num}〕" if alt in ("", num) else f"〔{num}|alt={alt}〕")
                else:
                    self.parts.append(f"〔{alt}〕")
            elif a.get("alt") in ("第一表", "第二表", "第三表", "第四表"):
                self.parts.append(f"［{a.get('alt')}］")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.skip:
            self.skip -= 1
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "a" and self._a:
            self.links.append((self._a[0], re.sub(r"\s+", " ", "".join(self._a[1])).strip()))
            self._a = None

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)
            if self._a:
                self._a[1].append(data)

    def text(self):
        t = "".join(self.parts).replace("\r", "")
        t = re.sub(r"[ \t　]*\n[ \t　]*", "\n", t)
        return re.sub(r"\n{2,}", "\n", t).strip()


def decode(body, ctype):
    m = re.search(rb'charset=["\']?([A-Za-z0-9_\-]+)', body[:4096])
    enc = m.group(1).decode() if m else None
    if not enc and ctype and "charset=" in ctype:
        enc = ctype.split("charset=")[-1].strip()
    for e in [enc, "utf-8", "cp932"]:
        if not e:
            continue
        try:
            return body.decode("cp932" if e.lower() in ("shift_jis", "sjis", "x-sjis", "shift-jis") else e), e
        except (UnicodeDecodeError, LookupError):
            continue
    return body.decode("utf-8", "replace"), "utf-8(replace)"


def safe_name(idx, url):
    p = urllib.parse.urlsplit(url)
    path = (p.netloc + "/" + p.path.strip("/")) if p.path.strip("/") else p.netloc + "_index"
    if p.query:
        path += "_q_" + p.query
    name = re.sub(r"[^A-Za-z0-9._-]", "_", path)
    return f"{idx:03d}_{name[-140:]}"  # 拡張子を残すため末尾を残す


def robots_for(host, cache, log):
    if host in cache:
        return cache[host]
    url = f"https://{host}/robots.txt"
    rp = urllib.robotparser.RobotFileParser()
    rec = {"robots_url": url}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA}, method="GET")
        with OPENER.open(req, timeout=30) as r:
            body = r.read(1024 * 1024)
            rec.update(status=r.status, bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
            txt, _ = decode(body, r.headers.get("Content-Type"))
            rp.parse(txt.splitlines())
    except urllib.error.HTTPError as e:
        rec.update(status=e.code)
        if e.code in (401, 403):
            rp.disallow_all = True
        else:
            rp.allow_all = True
    except Exception as e:  # noqa
        rec.update(error=repr(e))
        rp.disallow_all = True
    log.append(rec)
    cache[host] = rp
    time.sleep(DELAY)
    return rp


def read_limited(r):
    buf = bytearray()
    while True:
        chunk = r.read(1024 * 1024)
        if not chunk:
            return bytes(buf), False
        buf += chunk
        if len(buf) > MAX_BYTES:
            return bytes(buf[:0]), True


def render_saved(dl_dir, name):
    """取得済みの HTML（.work/downloads/<dir>/ の *.htm）を取り直さずに本文テキストへ書き直す（欄番号の画像の alt を含める）。"""
    src = pathlib.Path(dl_dir)
    tdir = OUT / f"render_{src.name}_{name}"
    tdir.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in sorted(src.iterdir()):
        if not f.name.endswith((".htm", ".html")):
            continue
        body = f.read_bytes()
        txt, enc = decode(body, None)
        p = Text()
        p.feed(txt)
        (tdir / f"{f.name}.txt").write_text(f"# saved={src.name}/{f.name}\n# sha256={hashlib.sha256(body).hexdigest()}\n"
                                            f"# encoding={enc}\n\n{p.text()}\n", encoding="utf-8")
        n += 1
    print(f"rendered {n} files to {tdir}")
    return 0


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(argv) < 2:
        print(__doc__)
        return 2
    if argv[0] == "--render":
        # 使い方: --render <.work/downloads/<dir>> <出力名>
        return render_saved(argv[1], re.sub(r"[^A-Za-z0-9_-]", "_", argv[2] if len(argv) > 2 else "alt"))
    name = re.sub(r"[^A-Za-z0-9_-]", "_", argv[0])
    if argv[1] == "--list":
        urls = [l.strip() for l in pathlib.Path(argv[2]).read_text(encoding="utf-8").splitlines()
                if l.strip() and not l.startswith("#")]
    else:
        urls = argv[1:]
    if len(urls) > MAX_PER_RUN:
        print(f"too many urls in one run: {len(urls)} > {MAX_PER_RUN}")
        return 2
    for u in urls:
        if urllib.parse.urlsplit(u).hostname not in ALLOWED_HOSTS or not u.startswith("https://"):
            print(f"not allowed: {u}")
            return 2
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_yoshiki_{name}"
    dl.mkdir(parents=True, exist_ok=False)
    tdir = OUT / f"{ts}_{name}"
    tdir.mkdir(parents=True, exist_ok=False)
    log, robots_log, cache = [], [], {}
    for i, url in enumerate(urls):
        host = urllib.parse.urlsplit(url).hostname
        rp = robots_for(host, cache, robots_log)
        rec = {"url": url, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        if not rp.can_fetch(UA, url):
            rec["skipped"] = "disallowed by robots.txt"
            log.append(rec)
            print(f"SKIP robots {url}")
            continue
        if i:
            time.sleep(DELAY)
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"}, method="GET")
        try:
            with OPENER.open(req, timeout=120) as r:
                body, too_big = read_limited(r)
                rec.update(status=r.status, final_url=re.sub(r";jsessionid=[^?#]*", "", r.geturl()),
                           content_type=r.headers.get("Content-Type"), last_modified=r.headers.get("Last-Modified"))
        except urllib.error.HTTPError as e:
            body, too_big = (e.read(1024 * 1024) if e.fp else b""), False
            rec.update(status=e.code, error=str(e.reason),
                       content_type=e.headers.get("Content-Type") if e.headers else None)
        except Exception as e:  # noqa
            rec.update(error=repr(e))
            log.append(rec)
            print(f"ERR {url} {e!r}")
            continue
        if too_big:
            rec["skipped"] = f"larger than {MAX_BYTES} bytes; not saved"
            log.append(rec)
            print(f"TOO BIG {url}")
            continue
        fname = safe_name(i, url)
        (dl / fname).write_bytes(body)
        rec.update(bytes=len(body), sha256=hashlib.sha256(body).hexdigest(), saved=f".work/downloads/{dl.name}/{fname}")
        ct = (rec.get("content_type") or "").lower()
        if "html" in ct or body[:200].lstrip().lower().startswith((b"<!doctype html", b"<html")):
            txt, enc = decode(body, rec.get("content_type"))
            p = Text()
            p.feed(txt)
            base = rec.get("final_url") or url
            links = [(urllib.parse.urljoin(base, h), t) for h, t in p.links]
            (tdir / f"{fname}.txt").write_text(
                f"# source={url}\n# final_url={rec.get('final_url')}\n# fetched_at={rec['fetched_at']}\n"
                f"# sha256={rec['sha256']}\n# encoding={enc}\n\n{p.text()}\n", encoding="utf-8")
            (tdir / f"{fname}.links.tsv").write_text("\n".join(f"{h}\t{t}" for h, t in links), encoding="utf-8")
            rec.update(encoding=enc, text=f"scripts/results/R2X_yoshiki_fetch/{tdir.name}/{fname}.txt",
                       links=f"scripts/results/R2X_yoshiki_fetch/{tdir.name}/{fname}.links.tsv", n_links=len(links))
        log.append(rec)
        print(f"{rec.get('status')} {len(body):>9} {rec.get('last_modified')} {fname}")
    (OUT / f"fetch_{ts}_{name}.json").write_text(
        json.dumps({"run": ts, "name": name, "download_dir": f".work/downloads/{dl.name}", "user_agent": UA,
                    "delay_sec": DELAY, "robots": robots_log, "results": log}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"saved to .work/downloads/{dl.name} ; log fetch_{ts}_{name}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""SAKUSEI: 確定申告書等作成コーナーの静的ファイル（HTML・JS・JSON など）を GET で取得する。

実行: python -I scripts/SAKUSEI_fetch.py <URL> [<URL> ...]
      python -I scripts/SAKUSEI_fetch.py --list <URLの一覧ファイル>

- GET だけを行う。フォームの送信・POST・ログインはしない。Cookie は保存・送信しない。
- 取得したファイルは信頼できないデータとして、実行ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_sakusei-assets/ に置く。中身は実行しない。
- リクエストの間は 2.5 秒あける。User-Agent は okura-gov-research/0.1。
- 1回の実行で取得する件数の上限は MAX_PER_RUN。全体の累計は scripts/results/SAKUSEI_fetch/ のログで数える。
- 取得の一覧（URL、最終URL、HTTP状態、Content-Type、サイズ、SHA-256、保存名）を
  scripts/results/SAKUSEI_fetch/fetch_<ts>.json に書く。本文はリポジトリに書かない。
標準ライブラリのみ。
"""
import hashlib
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
DELAY = 2.5
MAX_PER_RUN = 40
TOTAL_LIMIT = 100
ALLOWED_HOSTS = {"www.keisan.nta.go.jp", "keisan.nta.go.jp"}
OUT = ROOT / "scripts" / "results" / "SAKUSEI_fetch"


class NoCookieRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = urllib.parse.urlsplit(newurl).hostname
        if host not in ALLOWED_HOSTS:
            raise urllib.error.HTTPError(newurl, code, f"redirect to other host blocked: {newurl}", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(NoCookieRedirect())


def safe_name(idx, url):
    p = urllib.parse.urlsplit(url)
    path = p.path.strip("/") or "index"
    if p.query:
        path += "_q_" + p.query
    name = re.sub(r"[^A-Za-z0-9._-]", "_", path)
    return f"{idx:03d}_{name}"[:180]


def total_so_far():
    n = 0
    for f in OUT.glob("fetch_*.json"):
        try:
            n += len(json.loads(f.read_text(encoding="utf-8"))["results"])
        except Exception:  # noqa
            pass
    return n


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not argv:
        print(__doc__)
        return 2
    if argv[0] == "--list":
        urls = [l.strip() for l in pathlib.Path(argv[1]).read_text(encoding="utf-8").splitlines()
                if l.strip() and not l.startswith("#")]
    else:
        urls = argv
    OUT.mkdir(parents=True, exist_ok=True)
    done = total_so_far()
    if len(urls) > MAX_PER_RUN:
        print(f"too many urls in one run: {len(urls)} > {MAX_PER_RUN}")
        return 2
    if done + len(urls) > TOTAL_LIMIT:
        print(f"total limit exceeded: {done} + {len(urls)} > {TOTAL_LIMIT}")
        return 2
    for u in urls:
        if urllib.parse.urlsplit(u).hostname not in ALLOWED_HOSTS or not u.startswith("https://"):
            print(f"not allowed: {u}")
            return 2
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_sakusei-assets"
    dl.mkdir(parents=True, exist_ok=False)
    log = []
    for i, url in enumerate(urls):
        if i:
            time.sleep(DELAY)
        rec = {"url": url, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"}, method="GET")
        try:
            with OPENER.open(req, timeout=60) as r:
                body = r.read()
                rec.update(status=r.status, final_url=r.geturl(), content_type=r.headers.get("Content-Type"),
                           last_modified=r.headers.get("Last-Modified"))
        except urllib.error.HTTPError as e:
            body = e.read() if hasattr(e, "read") else b""
            rec.update(status=e.code, error=str(e.reason), content_type=e.headers.get("Content-Type") if e.headers else None)
        except Exception as e:  # noqa
            rec.update(error=repr(e))
            log.append(rec)
            continue
        name = safe_name(i, url)
        (dl / name).write_bytes(body)
        rec.update(bytes=len(body), sha256=hashlib.sha256(body).hexdigest(), saved=f"{dl.name}/{name}")
        log.append(rec)
        print(f"{rec.get('status')} {len(body):>9} {name}")
    (OUT / f"fetch_{ts}.json").write_text(
        json.dumps({"run": ts, "download_dir": f".work/downloads/{dl.name}", "user_agent": UA,
                    "delay_sec": DELAY, "results": log}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved to .work/downloads/{dl.name} ; log fetch_{ts}.json ; total={done + len(urls)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

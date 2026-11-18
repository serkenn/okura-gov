r"""R2X_kokuho: 国民年金保険料・免除・納付猶予（日本年金機構）と、国民健康保険料（税）の賦課限度額・軽減・子ども・子育て支援金
（厚生労働省・こども家庭庁）の公開ページを取得し、取得記録と要所の抜き書きを残す。
法令の原文は scripts/R2X_kokuho_egov.py で取得する。ここで取るのは照合用の公開資料。

実行（pyenv のシムは使わない）:
  C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe -I -X utf8 scripts/R2X_kokuho_web.py <set名> [<set名> ...]
  ... --list でセットの一覧
- 取得したファイルは信頼できないデータとして、取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_R2X_kokuho_web_<set>/ に置く（中でコードを実行しない）。
- HTML から取り出したテキストとリンクは .work/text/<ts>_R2X_kokuho_web_<set>/ に置く（ダウンロード用のディレクトリとは分ける）。
- 取得記録（ステータス、Last-Modified、SHA-256、タイトル、指定した語の前後の抜き書き）は
  scripts/results/R2X_kokuho_web/<set>_<ts>.json に書く。
- 取得の前に各ホストの robots.txt を読み、User-Agent okura-gov-research/0.1 で禁止されている URL は取得しない。
- リクエストの間は 1.5 秒あける。標準ライブラリのみ。取得と HTML の読み取りは scripts/IMPL_zeigaku_fetch_web.py を写した（import はしない）。
- 個人の情報は送らない（GET のみ。クエリ文字列なし）。
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
NK = "https://www.nenkin.go.jp/service/kokunen/"

# id -> (url, [抜き書きする語])
SETS = {
    "nenkin": {
        "nk_hokenryo": (NK + "hokenryo/hokenryo.html", ["17,510", "17,920", "18,290", "令和7年度", "令和8年度", "令和9年度", "付加保険料", "400円", "保険料改定率"]),
        "nk_menjo": (NK + "menjo/20150428.html", ["35万円", "32万円", "88万円", "128万円", "168万円", "納付猶予", "50歳未満", "世帯主", "配偶者", "前年所得", "7月", "6月"]),
        "nk_sanzen": (NK + "menjo/20180810.html", ["出産予定日", "前月", "翌々月", "3か月前", "多胎", "4か月"]),
    },
    # 2回目：1回目のリンクから見つけたページと、子ども・子育て支援金・国保の所管のページの候補
    "round2": {
        "nk_ikuji": (NK + "menjo/ikujimenjo.html", ["令和8年10月", "1歳", "養育", "免除", "所得", "父", "母"]),
        "nk_zenno": (NK + "hokenryo/zenno.html", ["令和8年度", "令和7年度", "17,920", "17,510", "前納"]),
        "cfa_shienkin": ("https://www.cfa.go.jp/policies/kodomokosodateshienkin", ["国民健康保険", "18歳", "均等割", "軽減", "令和8年度", "上限"]),
        "mhlw_kokuho_top": ("https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/iryouhoken/kokumin/index.html",
                            ["賦課限度額", "軽減", "未就学", "産前産後", "子ども・子育て支援", "保険料"]),
    },
}

# ---- 以下は scripts/IMPL_zeigaku_fetch_web.py の Extract 以降を写したもの（出力先の名前だけ変えた） ----


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


_robots = {}


def robots_ok(url, dl, log):
    host = urllib.parse.urlsplit(url)
    base = f"{host.scheme}://{host.netloc}"
    if base not in _robots:
        st, final, hdr, body = get(base + "/robots.txt")
        time.sleep(WAIT)
        name = "robots_" + host.netloc.replace(".", "_") + ".txt"
        (dl / name).write_bytes(body)
        rp = urllib.robotparser.RobotFileParser()
        if st == 200:
            rp.parse(decode(body, hdr.get("Content-Type", ""))[0].splitlines())
        else:
            rp.parse([])  # robots.txt がない → 制限なし
        _robots[base] = rp
        log.append({"robots": base + "/robots.txt", "status": st, "sha256": hashlib.sha256(body).hexdigest(), "saved": name})
    return _robots[base].can_fetch(UA, url)


def snippets(text, words, width=120, limit=6):
    out = {}
    for w in words:
        hits = []
        for m in re.finditer(re.escape(w), text):
            s, e = max(0, m.start() - width), min(len(text), m.end() + width)
            hits.append(" ".join(text[s:e].split()))
            if len(hits) >= limit:
                break
        out[w] = hits
    return out


def run_set(name, items, ts):
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_kokuho_web_{name}"
    dl.mkdir(parents=True, exist_ok=False)
    tx = ROOT / ".work" / "text" / f"{ts}_R2X_kokuho_web_{name}"
    tx.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "R2X_kokuho_web"
    out.mkdir(parents=True, exist_ok=True)
    log, robots_log = [], []
    for i, (sid, (url, words)) in enumerate(items.items()):
        rec = {"id": sid, "url": url, "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        try:
            if not robots_ok(url, dl, robots_log):
                rec["skipped"] = "robots.txt で禁止"
                log.append(rec)
                continue
            if i:
                time.sleep(WAIT)
            st, final, hdr, body = get(url)
            ctype = hdr.get("Content-Type", "")
            ext = ".pdf" if ("pdf" in ctype.lower() or final.lower().endswith(".pdf")) else (".html" if "html" in ctype.lower() else ".bin")
            (dl / f"{sid}{ext}").write_bytes(body)
            rec.update({"status": st, "final_url": final, "content_type": ctype, "bytes": len(body),
                        "sha256": hashlib.sha256(body).hexdigest(), "last_modified": hdr.get("Last-Modified"),
                        "saved": str((dl / f"{sid}{ext}").relative_to(ROOT))})
            if ext == ".html" and body:
                s, cs = decode(body, ctype)
                p = Extract()
                p.feed(s)
                t = p.text()
                rec["title"] = " ".join(p.title.split())
                rec["charset"] = cs
                m = re.search(r"[［\[]\s*(令和|平成)\s*[0-9０-９元]+年[0-9０-９]+月[0-9０-９]+日現在法令等\s*[］\]]", t)
                rec["as_of_label"] = m.group(0) if m else None
                rec["snippets"] = snippets(t, words)
                (tx / f"{sid}.txt").write_text(t, encoding="utf-8")
                links = []
                for ln in p.links:
                    href = urllib.parse.urljoin(final, ln["href"])
                    links.append({"href": href, "text": ln["text"]})
                (tx / f"{sid}.links.json").write_text(json.dumps(links, ensure_ascii=False, indent=1), encoding="utf-8")
                rec["text_saved"] = str((tx / f"{sid}.txt").relative_to(ROOT))
                rec["links_count"] = len(links)
        except Exception as e:  # noqa
            rec["error"] = repr(e)
        log.append(rec)
        print(sid, rec.get("status"), rec.get("as_of_label"), rec.get("error", ""), flush=True)
    res = {"set": name, "run_at": ts, "user_agent": UA, "robots": robots_log, "items": log}
    (out / f"{name}_{ts}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", out / f"{name}_{ts}.json")


def main():
    args = sys.argv[1:]
    if not args or args == ["--list"]:
        for k, v in SETS.items():
            print(k, len(v))
        return
    for name in args:
        ts = time.strftime("%Y%m%d-%H%M%S")
        run_set(name, SETS[name], ts)
        time.sleep(WAIT)


if __name__ == "__main__":
    main()

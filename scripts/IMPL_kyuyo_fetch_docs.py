"""IMPL_kyuyo: 給与所得・住民税の照合に使う公開資料（国税庁・総務省・地方公共団体）を取得する。

実行:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_kyuyo_fetch_docs.py [main|nencho_tables]
  引数なしは main。nencho_tables は国税庁「年末調整のしかた」の給与所得控除後の給与等の金額の表（PDF）だけを取る。
標準ライブラリのみ。リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。

- ダウンロードしたものは .work/downloads/<ts>_kyuyo_docs_<group>/ に置く（信頼できないデータ。中でコードを実行しない）。
- HTML は html.parser で本文のテキストとリンクを取り出し、scripts/results/IMPL_kyuyo_fetch_docs/<名前>.txt に書く。
- PDF はテキスト化しない（標準ライブラリでは読めない）。取得の記録（SHA-256、バイト数、Last-Modified）だけを残し、
  中身は人が Read ツールのページ指定で読む。
- 取得の記録は scripts/results/IMPL_kyuyo_fetch_docs/fetch_log.json。
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

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
SLEEP = 1.5

DOCS = [
    ("nta_ta1410", "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1410.htm"),
    ("nta_ta1177", "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1177.htm"),
    ("nta_2026kiso_index", "https://www.nta.go.jp/users/gensen/2026kiso/index.htm"),
    ("nta_2025kiso_index", "https://www.nta.go.jp/users/gensen/2025kiso/index.htm"),
    ("nta_2026kaisei_pdf", "https://www.nta.go.jp/publication/pamph/gensen/2026kaisei.pdf"),
    ("nta_2026kiso_qa_pdf", "https://www.nta.go.jp/users/gensen/2026kiso/pdf/0026005-024.pdf"),
    ("nta_2025kiso_qa_pdf", "https://www.nta.go.jp/publication/pamph/gensen/0025005-051.pdf"),
    ("nta_nencho2026_index", "https://www.nta.go.jp/publication/pamph/gensen/nencho2026/01.htm"),
    ("nta_nencho2025_index", "https://www.nta.go.jp/publication/pamph/gensen/nencho2025/01.htm"),
    ("soumu_r8_chihozei_an_pdf", "https://www.soumu.go.jp/main_content/001047636.pdf"),
    ("osaka_pref_r8_zeikai", "https://www.pref.osaka.lg.jp/o050030/zei/alacarte/reiwa8_zeikai.html"),
    ("sendai_r8", "https://www.city.sendai.jp/shiminze-kikaku/kurashi/tetsuzuki/zekin/kojin/kaisei/r8.html"),
    ("kumamoto_r9", "https://www.city.kumamoto.jp/kiji00373630/index.html"),
]

GROUPS = {
    "main": DOCS,
    "nencho_tables": [
        ("nta_nencho2025_114_pdf", "https://www.nta.go.jp/publication/pamph/gensen/nencho2025/pdf/114.pdf"),
        ("nta_nencho2026_114_pdf", "https://www.nta.go.jp/publication/pamph/gensen/nencho2026/pdf/114.pdf"),
    ],
}


class TextAndLinks(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section", "dt", "dd", "caption"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.links, self._skip, self._href = [], [], 0, None
        self._atext = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag in ("td", "th"):
            self.parts.append(" | ")
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._atext = []

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "a" and self._href:
            self.links.append({"href": self._href, "text": "".join(self._atext).strip()})
            self._href = None

    def handle_data(self, data):
        if self._skip:
            return
        self.parts.append(data)
        if self._href is not None:
            self._atext.append(data)


def decode(body, ctype):
    cs = None
    if ctype and "charset=" in ctype.lower():
        cs = ctype.lower().split("charset=")[-1].split(";")[0].strip()
    for enc in [cs, "utf-8", "shift_jis", "cp932", "euc_jp"]:
        if not enc:
            continue
        try:
            return body.decode(enc), enc
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", "replace"), "utf-8(replace)"


def main():
    group = sys.argv[1] if len(sys.argv) > 1 else "main"
    docs = GROUPS[group]
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_kyuyo_docs_{group}"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "IMPL_kyuyo_fetch_docs"
    out.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "group": group, "download_dir": str(dl.relative_to(ROOT)), "docs": []}
    for name, url in docs:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        rec = {"name": name, "url": url}
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                body, st = r.read(), r.status
                hdr = {k: r.headers.get(k) for k in ("Content-Type", "Last-Modified", "Content-Length")}
                final = r.geturl()
        except urllib.error.HTTPError as e:
            body, st, hdr, final = e.read(), e.code, {}, url
        except Exception as e:  # noqa
            rec["error"] = repr(e)
            log["docs"].append(rec)
            time.sleep(SLEEP)
            continue
        time.sleep(SLEEP)
        ext = ".pdf" if (hdr.get("Content-Type") or "").startswith("application/pdf") or url.endswith(".pdf") else ".html"
        fn = dl / f"{name}{ext}"
        fn.write_bytes(body)
        rec.update({"status": st, "final_url": final, "headers": hdr, "sha256": hashlib.sha256(body).hexdigest(),
                    "bytes": len(body), "saved_as": str(fn.relative_to(ROOT))})
        if ext == ".html" and st == 200:
            txt, enc = decode(body, hdr.get("Content-Type"))
            p = TextAndLinks()
            p.feed(txt)
            text = "".join(p.parts)
            lines = [ln.strip() for ln in text.splitlines()]
            lines = [ln for ln in lines if ln and ln != "|"]
            head = [f"# {name}", f"# URL={url}", f"# final_url={final}", f"# 取得日時={ts}", f"# status={st} encoding={enc}",
                    f"# Last-Modified={hdr.get('Last-Modified')}", f"# SHA-256={rec['sha256']}", ""]
            links = ["", "## links"] + [f"- {l['text']} -> {urllib.parse.urljoin(final, l['href'])}" for l in p.links if l["href"]]
            (out / f"{name}.txt").write_text("\n".join(head + lines + links), encoding="utf-8")
            rec["text_out"] = f"scripts/results/IMPL_kyuyo_fetch_docs/{name}.txt"
        log["docs"].append(rec)
        print(name, st, rec.get("bytes"), flush=True)
    (out / ("fetch_log.json" if group == "main" else f"fetch_log_{group}.json")).write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", out)


if __name__ == "__main__":
    sys.exit(main())

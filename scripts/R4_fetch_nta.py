"""R4: 国税庁「所得税基本通達」のうち、人・親族・生計・判定時期に関係するページを取得し、本文をテキストにする。

実行: python -I scripts/R4_fetch_nta.py
- ダウンロードした HTML は .work/downloads/<ts>_R4_nta/ に置く（信頼できないデータ。実行はしない）。
- テキスト化した本文と取得記録は scripts/results/R4_fetch_nta/ に書く。
- 標準ライブラリのみ。リクエストの間は 1.5 秒あける。
"""
import hashlib
import html.parser
import json
import pathlib
import re
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
BASE = "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/"
WAIT = 1.5
PAGES = {
    "01-01": "01/01.htm",  # 法第2条 居住者、非永住者及び非居住者
    "01-07": "01/07.htm",  # 法第2条 障害者・寡婦・ひとり親・同一生計配偶者等・扶養親族
    "11-01": "11/01.htm",  # 法第56条・第57条
    "16-01": "16/01.htm",  # 法第72条・第73条（医療費控除）
    "16-06": "16/06.htm",  # 法第79条〜第85条
}


class Text(html.parser.HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "dt", "dd", "table"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)

    def text(self):
        t = "".join(self.parts).replace("\r", "")
        t = re.sub(r"[ \t\u3000]*\n[ \t\u3000]*", "\n", t)
        return re.sub(r"\n{2,}", "\n", t).strip()


def decode(body, ctype):
    """HTML の meta charset、次に Content-Type の charset、最後に utf-8 / cp932 の順で試す。"""
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


def main():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R4_nta"
    dl.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "R4_fetch_nta"
    out.mkdir(parents=True, exist_ok=True)
    log = {"fetched_at": ts, "download_dir": str(dl.relative_to(ROOT)), "pages": []}
    for key, rel in PAGES.items():
        url = BASE + rel
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                body, status, ctype = r.read(), r.status, r.headers.get("Content-Type")
            (dl / f"{key}.htm").write_bytes(body)
            text, enc = decode(body, ctype)
            p = Text()
            p.feed(text)
            t = p.text()
            (out / f"{key}.txt").write_text(f"# source={url}\n# fetched_at={ts}\n# encoding={enc}\n\n{t}\n", encoding="utf-8")
            log["pages"].append({"key": key, "url": url, "status": status, "content_type": ctype, "bytes": len(body),
                                 "sha256": hashlib.sha256(body).hexdigest(), "encoding": enc, "output": f"scripts/results/R4_fetch_nta/{key}.txt"})
            print(f"ok {key} {status} {len(body)}", flush=True)
        except Exception as e:  # noqa
            log["pages"].append({"key": key, "url": url, "error": repr(e)})
            print(f"ERR {key} {e!r}", flush=True)
        time.sleep(WAIT)
    (out / "fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())

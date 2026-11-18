"""IMPL zeigaku: 国税庁のタックスアンサー・通達・手引き、日本年金機構の案内を取得し、取得記録と要所の抜き書きを残す。

実行（pyenv のシムは使わない）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_zeigaku_fetch_web.py <set名> [<set名> ...]
  ... --list でセットの一覧
- 取得したファイルは信頼できないデータとして、取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_IMPL_zeigaku_<set>/ に置く（中でコードを実行しない）。
- HTML から取り出したテキストとリンクは .work/text/<ts>_IMPL_zeigaku_<set>/ に置く（ダウンロード用のディレクトリとは分ける）。
- 取得記録（ステータス、Last-Modified、SHA-256、タイトル、ページ内の「令和X年X月X日現在法令等」の表示、指定した語の前後の抜き書き）は
  scripts/results/IMPL_zeigaku_fetch_web/<set>_<ts>.json に書く。
- 取得の前に各ホストの robots.txt を読み、User-Agent okura-gov-research/0.1 で禁止されている URL は取得しない。
- リクエストの間は 1.5 秒あける。標準ライブラリのみ。HTML の読み取りは scripts/R3_fetch.py の Extract を写した（import はしない）。
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
TA = "https://www.nta.go.jp/taxes/shiraberu/taxanswer/"

# id -> (url, [抜き書きする語])
SETS = {
    "ta": {
        "ta_1130": (TA + "shotoku/1130.htm", ["生計を一に", "国民年金", "支払った", "負担すべき", "前納", "年末調整"]),
        "ta_1175": (TA + "shotoku/1175.htm", ["勤労学生", "専修学校", "各種学校", "証明書", "89万", "85万", "10万円以下", "学校教育法"]),
        "ta_1900": (TA + "shotoku/1900.htm", ["20万円", "2,000万円", "確定申告が必要", "2か所以上", "年末調整"]),
        "ta_2020": (TA + "shotoku/2020.htm", ["確定申告が必要", "源泉徴収", "還付", "超える"]),
        "ta_2030": (TA + "shotoku/2030.htm", ["還付申告", "5年", "源泉徴収税額", "確定申告をする必要のない"]),
        "ta_2040": (TA + "shotoku/2040.htm", ["予定納税基準額", "15万円", "7月", "11月"]),
        "ta_2260": (TA + "shotoku/2260.htm", ["195万円", "5%", "2.1", "復興特別所得税", "1,000円未満", "速算表", "令和19年", "令和8年分", "令和9年"]),
        "ta_1199": (TA + "shotoku/1199.htm", ["104万円", "95万円", "62万円", "58万円", "令和8年分"]),
        "ta_1410": (TA + "shotoku/1410.htm", ["74万円", "65万円", "令和8年分", "190万円", "220万円"]),
    },
    "index": {
        "shitsugi_shotoku_index": ("https://www.nta.go.jp/law/shitsugi/shotoku/01.htm", ["社会保険料", "国民年金", "勤労学生"]),
        "kihon_shotoku_index": ("https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/01.htm", ["社会保険料控除", "第74条", "第82条", "勤労学生"]),
        "tebiki_index": ("https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/index.htm", ["手引き", "令和7年分", "令和８年分", "令和7年"]),
    },
    "nenkin": {
        # 注：20150331.html は「追納制度」のページだった（初回の取得で判明）。学生納付特例は下の round2 の 20150514.html
        "nenkin_gakusei": ("https://www.nenkin.go.jp/service/kokunen/menjo/20150331.html", ["128万", "所得の目安", "扶養親族等の数", "前年所得", "社会保険料控除", "学生納付特例", "4月", "3月"]),
    },
    # 2回目：1回目のリンクから見つけたページ
    "round2": {
        "nenkin_gakutoku": ("https://www.nenkin.go.jp/service/kokunen/menjo/20150514.html",
                            ["128万", "扶養親族等の数", "前年所得", "社会保険料控除", "所得基準", "4月", "3月", "学生"]),
        "nenkin_koujo": ("https://www.nenkin.go.jp/service/kokunen/hokenryo/koujo/index.html",
                         ["ご家族", "家族", "生計を一に", "社会保険料控除", "控除証明書"]),
        "kihon_16_02": ("https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/16/02.htm",
                        ["74・75－1", "74・75-1", "74・75－2", "74・75-2", "支払った", "生計を一に", "負担すべき", "前納"]),
        "kihon_01_07": ("https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/01/07.htm",
                        ["勤労学生", "2－43", "2-43", "2－44", "2-44", "自己の勤労", "給与所得等以外"]),
        "kihon_19_01": ("https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/19/01.htm",
                        ["121－1", "121-1", "120－1", "120-1", "20万円", "申告を要しない", "源泉徴収"]),
        "kihon_19_02": ("https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/19/02.htm",
                        ["122－1", "122-1", "還付", "5年"]),
        "tebiki_r07": ("https://www.nta.go.jp/taxes/shiraberu/shinkoku/syotoku/r07.htm",
                       ["手引き", "復興特別所得税", "確定申告書"]),
    },
    # 3回目：2回目のリンクから見つけたページ・PDF（PDF は Read ツールの pages 指定で読む）
    "round3": {
        "nenkin_r8koujo": ("https://www.nenkin.go.jp/service/kokunen/hokenryo/koujo/R8koujo/index.html",
                           ["ご家族", "家族", "生計を一に", "社会保険料控除", "控除証明書", "送付"]),
        "nencho2026_index": ("https://www.nta.go.jp/publication/pamph/gensen/nencho2026/01.htm", ["保険料控除", "社会保険料"]),
        "tebiki_r07_001pdf": ("https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/2025/pdf/001.pdf", []),
        "shinkokusho_r07_01pdf": ("https://www.nta.go.jp/taxes/shiraberu/shinkoku/yoshiki/01/shinkokusho/pdf/r07/01.pdf", []),
    },
}


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
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL_zeigaku_{name}"
    dl.mkdir(parents=True, exist_ok=False)
    tx = ROOT / ".work" / "text" / f"{ts}_IMPL_zeigaku_{name}"
    tx.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "IMPL_zeigaku_fetch_web"
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

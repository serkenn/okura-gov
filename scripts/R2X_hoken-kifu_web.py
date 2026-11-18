"""R2X_hoken-kifu: 国税庁のタックスアンサー・ふるさと納税の案内・年末調整の資料、総務省のふるさと納税の案内を取得し、
取得記録と要所の抜き書きを残す（生命保険料控除・地震保険料控除・寄附金控除・小規模企業共済等掛金控除・雑損控除）。

実行（pyenv のシムは使わない）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_hoken-kifu_web.py <set名> [<set名> ...]
  ... --list でセットの一覧
scripts/IMPL_zeigaku_fetch_web.py の取得・HTML 読み取りの関数を写したもの（import しない）。
- 取得したファイルは信頼できないデータとして、取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_R2X_hoken-kifu_<set>/ に置く（中でコードを実行しない）。
- HTML から取り出したテキストとリンクは .work/text/<ts>_R2X_hoken-kifu_<set>/ に置く。
- 取得記録（ステータス、Last-Modified、SHA-256、タイトル、「令和X年X月X日現在法令等」の表示、指定した語の前後の抜き書き）は
  scripts/results/R2X_hoken-kifu_web/<set>_<ts>.json に書く。
- 取得の前に各ホストの robots.txt を読み、User-Agent okura-gov-research/0.1 で禁止されている URL は取得しない。
- リクエストの間は 1.5 秒あける。標準ライブラリのみ。
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
SOUMU_F = "https://www.soumu.go.jp/main_sosiki/jichi_zeisei/czaisei/czaisei_seido/furusato/"

SETS = {
    "ta": {
        "ta_1110": (TA + "shotoku/1110.htm", ["5万円", "10分の1", "災害関連支出", "生計を一に", "48万円", "58万円", "62万円", "詐欺", "生活に通常必要", "雑損失の繰越", "災害減免法"]),
        "ta_1135": (TA + "shotoku/1135.htm", ["小規模企業共済", "個人型", "iDeCo", "確定拠出", "心身障害者扶養共済", "全額", "企業型"]),
        "ta_1140": (TA + "shotoku/1140.htm", ["平成24年1月1日", "新契約", "旧契約", "20,000円", "40,000円", "120,000円", "介護医療", "個人年金", "23歳未満", "令和8年分", "剰余金", "受取人"]),
        "ta_1145": (TA + "shotoku/1145.htm", ["50,000円", "長期損害保険", "平成18年12月31日", "10,000円", "15,000円", "生計を一に", "居住"]),
        "ta_1150": (TA + "shotoku/1150.htm", ["2,000円", "40%", "特定寄附金", "受領書", "ふるさと納税", "政党", "認定NPO", "税額控除"]),
        "ta_1155": (TA + "shotoku/1155.htm", ["2,000円", "ワンストップ", "5団体", "確定申告", "住民税", "特例分", "返礼品", "一時所得"]),
    },
    "furusato": {
        "nta_furusato": ("https://www.nta.go.jp/taxes/shiraberu/shinkoku/tokushu/keisubetsu/furusato.htm",
                         ["ワンストップ", "5団体", "確定申告", "無効", "寄附金受領証明書", "特定事業者", "年間寄附額"]),
        "nta_tokyo_onestop": ("https://www.nta.go.jp/about/organization/tokyo/topics/furusato_nozei_onestop/index.htm",
                              ["ワンストップ", "5団体", "確定申告", "無効", "住民税"]),
        "soumu_furusato_index": (SOUMU_F + "policy/", ["控除", "ワンストップ", "仕組み"]),
        "soumu_mechanism": (SOUMU_F + "mechanism/deduction.html", ["2,000円", "所得税", "住民税", "特例分", "20%", "ワンストップ", "5団体", "確定申告", "90%"]),
    },
    "nencho": {
        "nencho2026_index": ("https://www.nta.go.jp/publication/pamph/gensen/nencho2026/01.htm", ["保険料控除", "生命保険料", "23歳未満"]),
        "nencho2026_105pdf": ("https://www.nta.go.jp/publication/pamph/gensen/nencho2026/pdf/105.pdf", []),
    },
    # 2回目：1回目の TA のリンクから見つけた質疑応答事例・関連コード
    "round2": {
        "ta_1141": (TA + "shotoku/1141.htm", ["個人年金", "10年以上", "60歳", "受取人", "税制適格", "5年未満", "財形"]),
        "ta_1146": (TA + "shotoku/1146.htm", ["地震保険", "家屋", "生活用動産", "生計を一に", "常時", "店舗併用", "割合"]),
        "ta_1140_qa": (TA + "shotoku/1140_qa.htm", ["契約者", "支払った", "負担", "受取人", "解約"]),
        "shitsugi_05_74": ("https://www.nta.go.jp/law/shitsugi/shotoku/05/74.htm", ["旧生命保険料", "新生命保険料", "有利", "選択", "4万円", "5万円"]),
        "shitsugi_05_75": ("https://www.nta.go.jp/law/shitsugi/shotoku/05/75.htm", ["旧生命保険料", "新生命保険料", "証明書", "選択"]),
        "shitsugi_05_76": ("https://www.nta.go.jp/law/shitsugi/shotoku/05/76.htm", ["12万円", "限度", "介護医療"]),
        "shitsugi_05_68": ("https://www.nta.go.jp/law/shitsugi/shotoku/05/68.htm", ["長期損害保険", "変更", "選択"]),
        "shitsugi_02_37": ("https://www.nta.go.jp/law/shitsugi/shotoku/02/37.htm", ["一時所得", "謝礼", "ふるさと納税", "経済的利益"]),
        "shitsugi_05_05": ("https://www.nta.go.jp/law/shitsugi/shotoku/05/05.htm", ["詐欺", "雑損控除", "横領"]),
        "shitsugi_gensen_03_35": ("https://www.nta.go.jp/law/shitsugi/gensen/03/35.htm", ["妻名義", "支払った", "負担", "生命保険料控除"]),
        "ta_1902": (TA + "shotoku/1902.htm", ["1,000万円", "2分の1", "選択", "雑損控除"]),
    },
    # 3回目：年末調整のしかた（令和8年分）の「保険料控除申告書の受理と内容の確認」（PDF は Read ツールの pages 指定で読む）
    "round3": {
        "nencho2026_107pdf": ("https://www.nta.go.jp/publication/pamph/gensen/nencho2026/pdf/107.pdf", []),
    },
    # 4回目：所得税基本通達（第72条〜第78条関係）。題名で条を確かめる。端数（1円未満の切上げ）の根拠を探す
    "round4": {
        "kihon_16_01": ("https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/16/01.htm", ["72－", "72-", "生計を一に", "盗難", "横領", "詐欺", "1円未満", "切り上げ"]),
        "kihon_16_03": ("https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/16/03.htm", ["76－", "76-", "支払った", "1円未満", "切り上げ", "前納", "振替貸付", "受取人"]),
        "kihon_16_04": ("https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/16/04.htm", ["77－", "77-", "家屋", "生活に通常必要", "1円未満", "切り上げ", "店舗"]),
        "kihon_16_05": ("https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/16/05.htm", ["78－", "78-", "支出した", "特別の利益", "入学", "1円未満"]),
        "kihon_16_06": ("https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/16/06.htm", ["79－", "79-", "78－", "78-"]),
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
            rp.parse([])
        _robots[base] = rp
        log.append({"robots": base + "/robots.txt", "status": st, "sha256": hashlib.sha256(body).hexdigest(), "saved": name})
    return _robots[base].can_fetch(UA, url)


def snippets(text, words, width=140, limit=6):
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
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_hoken-kifu_{name}"
    dl.mkdir(parents=True, exist_ok=False)
    tx = ROOT / ".work" / "text" / f"{ts}_R2X_hoken-kifu_{name}"
    tx.mkdir(parents=True, exist_ok=False)
    out = ROOT / "scripts" / "results" / "R2X_hoken-kifu_web"
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
                        "saved": str((dl / f"{sid}{ext}").relative_to(ROOT)).replace("\\", "/")})
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
                links = [{"href": urllib.parse.urljoin(final, ln["href"]), "text": ln["text"]} for ln in p.links]
                (tx / f"{sid}.links.json").write_text(json.dumps(links, ensure_ascii=False, indent=1), encoding="utf-8")
                rec["text_saved"] = str((tx / f"{sid}.txt").relative_to(ROOT)).replace("\\", "/")
                rec["links_count"] = len(links)
        except Exception as e:  # noqa
            rec["error"] = repr(e)
        log.append(rec)
        print(sid, rec.get("status"), rec.get("as_of_label"), rec.get("title", ""), rec.get("error", ""), flush=True)
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

"""R2X genka: 国税庁の通達・タックスアンサー・質疑応答事例・手引きのうち、減価償却と損益通算に関係するページを取得し、
本文のテキストとリンクを取り出す。

実行（Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_genka_nta.py <set> [<set> ...]
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_genka_nta.py --list
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_genka_nta.py --robots
      （robots.txt を取得し、SETS のすべての URL が許されるかを urllib.robotparser で判定。結果は robots_check.json）

- scripts/IMPL_jigyo_nta.py を写した（import はしない）。
- 取得したもの（HTML・PDF）は信頼できないデータとして、取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_R2X_genka_nta_<set>/ に置く。その中でインタプリタやツールは実行しない。
- HTML から取り出したテキストとリンクは scripts/results/R2X_genka_nta/<set>/<id>.txt / <id>.links.json に書く。
  画像で表示される文字は img の alt を〔alt:...〕の形で残す。
- PDF はテキスト化しない（ダウンロード先のパスと SHA-256 だけを記録し、人が Read ツールで読む）。
- 取得記録（ステータス、Content-Type、Last-Modified、SHA-256、バイト数）は scripts/results/R2X_genka_nta/<set>/fetch_log.json。
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

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
WAIT = 1.5
OUT = ROOT / "scripts" / "results" / "R2X_genka_nta"

NTA = "https://www.nta.go.jp"
TA = NTA + "/taxes/shiraberu/taxanswer/shotoku/"
KIHON = NTA + "/law/tsutatsu/kihon/shotoku/"
SOCHI = NTA + "/law/tsutatsu/kobetsu/shotoku/sochiho/801226/sinkoku/57/"
SHITSUGI = NTA + "/law/shitsugi/shotoku/"
TEBIKI = NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/pdf/"
SETS = {
    # 1回目：タックスアンサー（リンクから関連の番号を探す）
    "ta": {
        "ta_2100": TA + "2100.htm",   # 減価償却のあらまし
        "ta_2250": TA + "2250.htm",   # 損益通算
    },
    # 2回目：所得税基本通達（法第2条第1項第19号・法第49条・法第51条・法第70条関係）と措置法通達（第28条の2 関係）
    "tsutatsu": {
        "kihon_01_04": KIHON + "01/04.htm",   # 〔減価償却資産（第19号関係）〕
        "kihon_08_05": KIHON + "08/05.htm",   # 〔減価償却資産の償却の方法（令120・120の2）〕〔減価償却資産の範囲〕ほか
        "kihon_08_06": KIHON + "08/06.htm",   # 〔減価償却資産の取得価額（令126）〕
        "kihon_08_08": KIHON + "08/08.htm",   # 〔償却費の計算（令131）〕
        "kihon_08_10": KIHON + "08/10.htm",   # 〔年の中途で業務の用に供した減価償却資産等の償却費の特例（令132）〕
        "kihon_08_12": KIHON + "08/12.htm",   # 〔少額の減価償却資産及び一括償却資産（令138・139）〕〔減価償却資産の除却等〕
        "kihon_08_13": KIHON + "08/13.htm",   # 〔償却累積額による償却費の特例…（令134・134の2）〕
        "kihon_09_01": KIHON + "09/01.htm",   # 法第51条〔固定資産等の損失〕
        "kihon_15_01": KIHON + "15/01.htm",   # 法第70条《純損失の繰越控除》関係ほか
        "kihon_04_07": KIHON + "04/07.htm",   # 法第33条《譲渡所得》関係
        "sochitsu_28_02": SOCHI + "28/02.htm",  # 措置法通達 第28条の2 関係
    },
    # 3回目：質疑応答事例（非業務用資産を業務の用に供した場合、生計を一にする親族の資産）
    "shitsugi": {
        "shitsugi_04_17": SHITSUGI + "04/17.htm",  # 非業務用資産を業務の用に供した場合
        "shitsugi_04_14": SHITSUGI + "04/14.htm",  # 生計を一にする親族の有する資産に係る特別償却
    },
    # 4回目：令和7年分の手引き（PDF）
    "forms": {
        "aoiro_kessan_kakikata_r07": TEBIKI + "037.pdf",   # 令和７年分青色申告決算書（一般用）の書き方
        "sonshitsu_tebiki_r07": TEBIKI + "003.pdf",        # 令和７年分 確定申告の手引き（損失申告用）
    },
    # 5回目：タックスアンサーの関連（定額法）、耐用年数表・償却率等表（PDF）、届出の手続
    "ta2": {
        "ta_2106": TA + "2106.htm",   # 定額法と定率法による減価償却（平成19年4月1日以後に取得する場合）
        "ta_2100_01": TA + "pdf/2100_01.pdf",   # 主な減価償却資産の耐用年数表
        "ta_2100_02": TA + "pdf/2100_02.pdf",   # 減価償却資産の償却率等表
        "tetsuzuki_18": NTA + "/taxes/tetsuzuki/shinsei/annai/shinkoku/annai/18.htm",   # 所得税の減価償却資産の償却方法の届出手続
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
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers or {})


def run_set(name):
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_genka_nta_{name}"
    dl.mkdir(parents=True, exist_ok=False)
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    log = {"set": name, "fetched_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "items": []}
    for key, url in SETS[name].items():
        try:
            st, body, hd = fetch(url)
        except Exception as e:  # noqa
            log["items"].append({"id": key, "url": url, "error": repr(e)})
            print("ERR", key, repr(e), flush=True)
            time.sleep(WAIT)
            continue
        ctype = hd.get("Content-Type", "")
        is_pdf = "pdf" in ctype.lower() or url.lower().endswith(".pdf")
        fn = dl / (key + (".pdf" if is_pdf else ".htm"))
        fn.write_bytes(body)
        item = {"id": key, "url": url, "status": st, "content_type": ctype, "last_modified": hd.get("Last-Modified"),
                "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(), "saved": str(fn.relative_to(ROOT)).replace("\\", "/")}
        if not is_pdf and st == 200:
            text, enc = decode(body, ctype)
            p = Page(url)
            p.feed(text)
            title = re.search(r"<title>(.*?)</title>", text, re.S)
            item["title"] = re.sub(r"\s+", " ", title.group(1)).strip() if title else None
            item["encoding"] = enc
            (out / f"{key}.txt").write_text(f"# source={url}\n# fetched_at={ts}\n# last_modified={hd.get('Last-Modified')}\n# sha256={item['sha256']}\n\n{p.text()}\n", encoding="utf-8")
            (out / f"{key}.links.json").write_text(json.dumps(p.links, ensure_ascii=False, indent=1), encoding="utf-8")
        log["items"].append(item)
        print("ok", key, st, len(body), item.get("title"), flush=True)
        time.sleep(WAIT)
    (out / "fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


def check_robots():
    import urllib.robotparser
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_genka_nta_robots"
    dl.mkdir(parents=True, exist_ok=False)
    st, body, hd = fetch(NTA + "/robots.txt")
    (dl / "robots.txt").write_bytes(body)
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(body.decode("utf-8", "replace").splitlines())
    res = {"fetched_at": ts, "url": NTA + "/robots.txt", "status": st, "sha256": hashlib.sha256(body).hexdigest(),
           "saved": str((dl / "robots.txt").relative_to(ROOT)).replace("\\", "/"),
           "disallow_lines": [ln.strip() for ln in body.decode("utf-8", "replace").splitlines() if ln.strip().lower().startswith("disallow")],
           "urls": {}}
    for name, items in SETS.items():
        for key, url in items.items():
            res["urls"][f"{name}/{key}"] = {"url": url, "allowed": rp.can_fetch(UA, url)}
    res["all_allowed"] = all(v["allowed"] for v in res["urls"].values())
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "robots_check.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("robots", st, "all_allowed", res["all_allowed"], res["disallow_lines"])


def main():
    args = sys.argv[1:]
    if args == ["--robots"]:
        check_robots()
        return
    if not args or args == ["--list"]:
        for k, v in SETS.items():
            print(k, len(v))
        return
    for a in args:
        run_set(a)


if __name__ == "__main__":
    main()

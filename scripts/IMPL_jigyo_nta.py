"""IMPL jigyo: 国税庁の通達・タックスアンサー・様式のうち、事業所得・業務に係る雑所得の計算（家事関連費・特例・帳簿）に
関係するページを取得し、本文のテキストとリンクを取り出す。

実行（Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_jigyo_nta.py <set> [<set> ...]
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_jigyo_nta.py --list
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_jigyo_nta.py --robots
      （robots.txt を取得し、SETS のすべての URL が許されるかを urllib.robotparser で判定。結果は robots_check.json）

- 取得したもの（HTML・PDF）は信頼できないデータとして、取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_IMPL_jigyo_nta_<set>/ に置く。その中でインタプリタやツールは実行しない。
- HTML から取り出したテキストとリンクは scripts/results/IMPL_jigyo_nta/<set>/<id>.txt / <id>.links.json に書く。
  画像で表示される文字（通達の「塡」など）は img の alt を〔alt:...〕の形で残す。
- PDF はテキスト化しない（ダウンロード先のパスと SHA-256 だけを記録し、人が Read ツールで読む）。
- 取得記録（ステータス、Content-Type、Last-Modified、SHA-256、バイト数）は scripts/results/IMPL_jigyo_nta/<set>/fetch_log.json。
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
OUT = ROOT / "scripts" / "results" / "IMPL_jigyo_nta"

NTA = "https://www.nta.go.jp"
TA = NTA + "/taxes/shiraberu/taxanswer/shotoku/"
KIHON = NTA + "/law/tsutatsu/kihon/shotoku/"
SETS = {
    # 1回目：タックスアンサーと、リンクを見つけるための目次ページ
    "ta_index": {
        "ta_1810": TA + "1810.htm",   # 家内労働者等の必要経費の特例
        "ta_1490": TA + "1490.htm",   # 一時所得
        "ta_1500": TA + "1500.htm",   # 雑所得
        "ta_1350": TA + "1350.htm",   # 事業所得の課税のしくみ
        "ta_2070": TA + "2070.htm",   # 青色申告制度
        "ta_2072": TA + "2072.htm",   # 青色申告特別控除
        "ta_2080": TA + "2080.htm",   # 白色申告者の記帳・帳簿等保存制度
        "ta_2210": TA + "2210.htm",   # 必要経費の知識
        "kicho_index": NTA + "/taxes/shiraberu/shinkoku/syotoku/index.htm",   # 記帳・帳簿等保存、青色申告
        "sochiho_shotoku_index": NTA + "/law/tsutatsu/kobetsu/shotoku/sochiho/sotihou.htm",  # 措置法通達（所得税編）目次
        "kihon_shotoku_index": NTA + "/law/tsutatsu/kihon/shotoku/01.htm",  # 所得税基本通達 目次
    },
    # 2回目：所得税基本通達の該当ページ、措置法通達の目次、様式・手引きの一覧
    "tsutatsu": {
        "kihon_04_02": KIHON + "04/02.htm",   # 法第27条（事業所得）関係
        "kihon_04_08": KIHON + "04/08.htm",   # 法第34条（一時所得）関係
        "kihon_04_09": KIHON + "04/09.htm",   # 法第35条（雑所得）関係
        "kihon_04_10": KIHON + "04/10.htm",   # 法第23条から第35条まで共通関係
        "kihon_07_01": KIHON + "07/01.htm",   # 法第45条（家事関連費等）関係
        "kihon_14_02": KIHON + "14/02.htm",   # 法第67条（小規模事業者等の収入及び費用の帰属時期）関係
        "kihon_19_01": KIHON + "19/01.htm",   # 法第120条（確定所得申告）関係
        "kihon_20_01": KIHON + "20/01.htm",   # 法第148条（青色申告者の帳簿書類）関係
        "kihon_40_02": KIHON + "40/02.htm",   # 法第232条（事業所得等を有する者の帳簿書類の備付け等）関係
        "sochiho_shotoku_toc": NTA + "/law/tsutatsu/kobetsu/shotoku/sochiho/801226/sinkoku/01.htm",  # 租税特別措置法に係る所得税の取扱いについて（目次）
        "yoshiki_r07": NTA + "/taxes/shiraberu/shinkoku/syotoku/r07.htm",   # 令和7年分の確定申告書等の様式・手引き等
        "fuhyo_1557_2": NTA + "/taxes/tetsuzuki/shinsei/annai/shinkoku/annai/1557_2.htm",  # 申告書・申告書付表と税額計算書等 一覧
        "pamph_01": NTA + "/publication/pamph/01.htm",   # パンフレット・手引（記帳・帳簿等保存、青色申告）
        "aoiro_shinsei_09": NTA + "/taxes/tetsuzuki/shinsei/annai/shinkoku/annai/09.htm",  # 所得税の青色申告承認申請手続
    },
    # 3回目：様式（PDF）と書き方、措置法通達 25の2 関係
    "forms": {
        "shushi_ippan_r07": NTA + "/taxes/shiraberu/shinkoku/yoshiki/01/shinkokusho/pdf/r07/05.pdf",  # 収支内訳書（一般用）【令和５年分以降用】（令和7年分の様式一覧から）
        "shushi_ippan_kakikata_r07": NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/pdf/034.pdf",      # 令和７年分収支内訳書（一般用）の書き方
        "kanai_keisansho_r07": NTA + "/taxes/shiraberu/shinkoku/yoshiki/03/09.pdf",                  # 家内労働者等…必要経費の額の計算書【令和７年分以降用】
        "kanai_kakikata_r07": NTA + "/taxes/shiraberu/shinkoku/yoshiki/03/09-ki.pdf",                # 家内労働者等の…特例の適用を受けられる方へ
        "kessan_tebiki_shiro_r07": NTA + "/taxes/shiraberu/shinkoku/kojin_jigyo/kichou09.pdf",       # 令和７年分白色申告者の決算の手引き（一般用）
        "kicho_shikata_jigyo": NTA + "/taxes/shiraberu/shinkoku/kojin_jigyo/kichou03.pdf",           # 帳簿の記帳のしかた（事業所得者用）
        "sochitsu_25_2": NTA + "/law/tsutatsu/kobetsu/shotoku/sochiho/801226/sinkoku/57/25/01.htm",  # 措置法通達 第25条の2 関係
    },
    # 4回目：質疑応答事例（所得税）の目次と、一時所得の内部通算の事例
    "shitsugi": {
        "shitsugi_shotoku_index": NTA + "/law/shitsugi/shotoku/01.htm",       # 質疑応答事例 所得税 目次
        "shitsugi_02_04": NTA + "/law/shitsugi/shotoku/02/04.htm",            # 一時所得の金額の計算（一時所得内の内部通算の可否）
        "shitsugi_02_09": NTA + "/law/shitsugi/shotoku/02/09.htm",            # 生命保険金の受取人が2人いる場合の一時所得の金額の計算
    },
    # 5回目：家内労働者等の特例の質疑応答事例
    "shitsugi2": {
        "shitsugi_04_34": NTA + "/law/shitsugi/shotoku/04/34.htm",            # ピアノ教室を営む場合の家内労働者等の事業所得等の所得計算の特例
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
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL_jigyo_nta_{name}"
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
    """https://www.nta.go.jp/robots.txt を取得し、SETS のすべての URL が User-agent okura-gov-research/0.1 で許されるかを判定する。"""
    import urllib.robotparser
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL_jigyo_nta_robots"
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

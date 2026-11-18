"""R2B_fudosan_nta: 不動産所得（第2ラウンド追加分、トピック fudosan）のため、国税庁の通達・タックスアンサー・様式（PDF）を
GET で取得し、HTML は本文テキストとリンクの一覧にする。

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_fudosan_nta.py <set> [<set> ...]
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_fudosan_nta.py --list

- scripts/IMPL_jigyo_nta.py の形（Page パーサ、decode、fetch）を写したもの（import はしない）。標準ライブラリのみ。
- GET だけを行う。フォームの送信・POST・ログインはしない。Cookie は保存・送信しない。個人の情報は送らない。
- 実行ごとに https://www.nta.go.jp/robots.txt を取得し、urllib.robotparser で許されない URL は取得しない。
- 対象のホストは www.nta.go.jp だけ。他ホストへのリダイレクトは止める。
- 取得したもの（HTML・PDF）は信頼できないデータとして、取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_R2B_fudosan_nta_<set>/ に置く。その中でインタプリタやツールは実行しない。
  PDF はテキスト化しない（パスと SHA-256 を記録し、人が Read ツールで読む）。
- HTML から取り出したテキストとリンクは scripts/results/R2B_fudosan_nta/<set>/<id>.txt / <id>.links.json に書く。
  画像で表示される文字は img の alt を〔alt:...〕の形で残す。
- 取得記録（ステータス、Content-Type、Last-Modified、SHA-256、バイト数、robots の判定）は
  scripts/results/R2B_fudosan_nta/<set>/fetch_log.json。
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
import urllib.robotparser

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
WAIT = 1.5
OUT = ROOT / "scripts" / "results" / "R2B_fudosan_nta"
ALLOWED_HOSTS = {"www.nta.go.jp"}

NTA = "https://www.nta.go.jp"
TA = NTA + "/taxes/shiraberu/taxanswer/shotoku/"
KIHON = NTA + "/law/tsutatsu/kihon/shotoku/"
SOCHI = NTA + "/law/tsutatsu/kobetsu/shotoku/sochiho/801226/sinkoku/"
SETS = {
    # タックスアンサー（「個人事業」分野の一覧 code/bunya-kojinjigyo.htm に載っている不動産所得の項目と、損益通算・青色）
    "ta": {
        "ta_1370": TA + "1370.htm",   # 不動産収入を受け取ったとき(不動産所得)
        "ta_1373": TA + "1373.htm",   # 事業としての不動産貸付けとそれ以外の不動産貸付けとの区分
        "ta_1376": TA + "1376.htm",   # 不動産所得の収入計上時期
        "ta_1391": TA + "1391.htm",   # 不動産所得が赤字のときの他の所得との通算
        "ta_1399": TA + "1399.htm",   # 新たに不動産の貸付けを始めたときの届出など
        "ta_2250": TA + "2250.htm",   # 損益通算
        "ta_2072": TA + "2072.htm",   # 青色申告特別控除
        "ta_2075": TA + "2075.htm",   # 青色事業専従者給与と事業専従者控除
        "ta_2210": TA + "2210.htm",   # やさしい必要経費の知識
    },
    # 所得税基本通達・措置法通達
    "tsutatsu": {
        "kihon_04_02": KIHON + "04/02.htm",   # 法第26条（不動産所得）関係
        "kihon_05_01": KIHON + "05/01.htm",   # 収入金額・収入すべき時期（法36関係）
        "kihon_09_01": KIHON + "09/01.htm",   # 固定資産等の損失（法51関係）
        "kihon_09_02": KIHON + "09/02.htm",   # 貸倒損失（法51関係）
        "kihon_11_01": KIHON + "11/01.htm",   # 法第56条・第57条関係
        "kihon_13_01": KIHON + "13/01.htm",   # 法第63条・第64条関係
        "kihon_15_01": KIHON + "15/01.htm",   # 損益通算・損失の繰越控除（法69〜71関係）
        "sochitsu_41_4": SOCHI + "57/41/04.htm",     # 措置法通達 第41条の4 関係
        "sochitsu_41_4_2": SOCHI + "57/41/04_2.htm", # 措置法通達 第41条の4の2 関係
        "sochitsu_41_4_3": SOCHI + "57/41/04_3.htm", # 措置法通達 第41条の4の3 関係（存在の確認）
    },
    # 様式（令和7年分の様式一覧 syotoku/r07.htm から）と、令和8年分の一覧ページの有無
    "forms": {
        "shushi_fudosan_r07": NTA + "/taxes/shiraberu/shinkoku/yoshiki/01/shinkokusho/pdf/r07/09.pdf",  # 収支内訳書（不動産所得用）【令和２年分以降用】
        "shushi_fudosan_kakikata_r07": NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/pdf/019.pdf",      # 令和７年分収支内訳書（不動産所得用）の書き方
        "kessan_fudosan_r07": NTA + "/taxes/shiraberu/shinkoku/yoshiki/01/shinkokusho/pdf/r07/12.pdf",  # 所得税青色申告決算書（不動産所得用）【令和２年分以降用】
        "kessan_fudosan_kakikata_r07": NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/pdf/039.pdf",      # 令和７年分青色申告決算書（不動産所得用）の書き方
        "yoshiki_r07": NTA + "/taxes/shiraberu/shinkoku/syotoku/r07.htm",   # 令和7年分の確定申告書等の様式・手引き等
        "yoshiki_r08": NTA + "/taxes/shiraberu/shinkoku/syotoku/r08.htm",   # 令和8年分（公開の有無の確認）
    },
    # 質疑応答事例・個別通達（TA 1373 のリンク、検索で見つけたもの）
    "more": {
        "shitsugi_02_27": NTA + "/law/shitsugi/shotoku/02/27.htm",   # 事業に至らない規模の不動産貸付において未収家賃が回収不能となった場合
        "shitsugi_04_14": NTA + "/law/shitsugi/shotoku/04/14.htm",   # 生計を一にする親族の有する資産に係る特別償却
        "kobetsu_731106": NTA + "/law/tsutatsu/kobetsu/shotoku/shinkoku/731106/01.htm",  # 不動産等の賃貸料にかかる不動産所得の収入金額の計上時期について
    },
}


class NoForeignRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).hostname not in ALLOWED_HOSTS:
            raise urllib.error.HTTPError(newurl, code, f"redirect to foreign host blocked: {newurl}", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(NoForeignRedirect())


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
        with OPENER.open(req, timeout=120) as r:
            return r.status, r.read(), dict(r.headers), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, (e.read() if e.fp else b""), dict(e.headers or {}), url


def robots(dl):
    st, body, hd, _ = fetch(NTA + "/robots.txt")
    (dl / "robots.txt").write_bytes(body)
    rp = urllib.robotparser.RobotFileParser()
    if st == 200:
        rp.parse(body.decode("utf-8", "replace").splitlines())
    else:
        rp.parse([])
    time.sleep(WAIT)
    return rp, {"url": NTA + "/robots.txt", "status": st, "sha256": hashlib.sha256(body).hexdigest()}


def run_set(name):
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2B_fudosan_nta_{name}"
    dl.mkdir(parents=True, exist_ok=False)
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    rp, rinfo = robots(dl)
    log = {"set": name, "fetched_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "robots": rinfo, "items": []}
    for key, url in SETS[name].items():
        if not rp.can_fetch(UA, url):
            log["items"].append({"id": key, "url": url, "robots_allowed": False})
            print("SKIP(robots)", key, flush=True)
            continue
        try:
            st, body, hd, final = fetch(url)
        except Exception as e:  # noqa
            log["items"].append({"id": key, "url": url, "robots_allowed": True, "error": repr(e)})
            print("ERR", key, repr(e), flush=True)
            time.sleep(WAIT)
            continue
        ctype = hd.get("Content-Type", "")
        is_pdf = "pdf" in ctype.lower() or url.lower().endswith(".pdf")
        fn = dl / (key + (".pdf" if is_pdf else ".htm"))
        fn.write_bytes(body)
        item = {"id": key, "url": url, "final_url": final, "robots_allowed": True, "status": st, "content_type": ctype,
                "last_modified": hd.get("Last-Modified"), "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
                "saved": str(fn.relative_to(ROOT)).replace("\\", "/")}
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


def main():
    args = sys.argv[1:]
    if not args or args == ["--list"]:
        for k, v in SETS.items():
            print(k, len(v))
        return
    for a in args:
        if a not in SETS:
            print("unknown set", a)
            continue
        run_set(a)


if __name__ == "__main__":
    main()

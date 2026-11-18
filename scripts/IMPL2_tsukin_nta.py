"""IMPL2 tsukin: 国税庁の通達・タックスアンサー・Q&A・手引のうち、通勤手当の非課税（所法9①五、所令20の2、所規2の2）と、
源泉徴収票の「支払金額」との関係に関するページを取得し、本文のテキストとリンクを取り出す。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL2_tsukin_nta.py --robots
      robots.txt を取得し、SETS のすべての URL が User-Agent okura-gov-research/0.1 で許されるかを判定（robots_check.json）
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL2_tsukin_nta.py <set> [<set> ...]
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL2_tsukin_nta.py --list

- HTML の取得とテキスト化は scripts/R3X_shibo-shukkoku_nta.py（その元は scripts/R2X_aoiro_nta.py）を写した（import はしない）。
- 取得したもの（HTML・PDF）は信頼できないデータとして、取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_IMPL2_tsukin_nta_<set>/ に置く。その中でインタプリタやツールは実行しない。
- HTML から取り出したテキストとリンクは scripts/results/IMPL2_tsukin_nta/<set>/<id>.txt / <id>.links.json に書く。
  画像で表示される文字は img の alt を〔alt:...〕の形で残す。
- PDF はテキスト化しない（ダウンロード先のパスと SHA-256 だけを記録し、人が Read ツールの pages 指定で読む）。
- 取得記録（ステータス、Content-Type、Last-Modified、SHA-256、バイト数）は scripts/results/IMPL2_tsukin_nta/<set>/fetch_log.json。
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
OUT = ROOT / "scripts" / "results" / "IMPL2_tsukin_nta"
PREFIX = "IMPL2_tsukin_nta"

NTA = "https://www.nta.go.jp"
TA_GENSEN = NTA + "/taxes/shiraberu/taxanswer/gensen/"
TACODE = NTA + "/taxes/shiraberu/taxanswer/code/"
KIHON = NTA + "/law/tsutatsu/kihon/shotoku/"
SETS = {
    # 1回目：通達（法第9条関係のうち通勤手当）・タックスアンサー（既知の番号）・索引
    "pages": {
        "kihon_02_02": KIHON + "02/02.htm",            # 法第9条関係（旅費・通勤手当・現物給与など）
        "kihon_index": KIHON + "01.htm",               # 所得税基本通達の目次
        "ta_2582": TA_GENSEN + "2582.htm",             # 電車・バス通勤者の通勤手当（番号は以前の知識。404 ならそのまま記録する）
        "ta_2585": TA_GENSEN + "2585.htm",             # マイカー・自転車通勤者の通勤手当（同上）
        "tacode_index": TACODE + "index.htm",          # タックスアンサーの分野の一覧
    },
    # 2回目：pages のリンク（質疑応答事例）と、国税庁の改正の案内（URL は WebSearch の結果と、
    # scripts/results/IMPL_kyuyo_fetch_docs/nta_nencho2025_index.txt のリンク「通勤手当の非課税限度額の改正について」から）
    "pages2": {
        "shitsugi_g_03_01": NTA + "/law/shitsugi/gensen/03/01.htm",   # 2以上の使用者から支払を受ける役員の出勤費用
        "shitsugi_g_03_18": NTA + "/law/shitsugi/gensen/03/18.htm",   # 障害者が2km未満を交通用具で通勤する場合
        "shitsugi_g_03_19": NTA + "/law/shitsugi/gensen/03/19.htm",   # 数か所に勤務する者に支給する通勤費
        "shitsugi_g_03_20": NTA + "/law/shitsugi/gensen/03/20.htm",   # 交通用具を使用している者の通勤距離が変更となった場合
        "shitsugi_g_03_21": NTA + "/law/shitsugi/gensen/03/21.htm",   # アルバイトに支給する通勤手当の非課税限度額
        "shitsugi_g_03_22": NTA + "/law/shitsugi/gensen/03/22.htm",   # 通勤手当と住宅手当を合算して支給する場合
        "shitsugi_g_03_23": NTA + "/law/shitsugi/gensen/03/23.htm",   # 緊急業務のために出社する従業員に支給するタクシー代等
        "ta_2508": TA_GENSEN + "2508.htm",                            # 給与所得となるもの
        "users_2025tsukin": NTA + "/users/gensen/2025tsukin/index.htm",  # 通勤手当の非課税限度額の改正について（令和7年）
        "users_2026tsukin": NTA + "/users/gensen/2026tsukin/index.htm",  # 通勤手当の非課税限度額の改正について（令和8年）
        "hotei_tebikihtml": NTA + "/publication/pamph/hotei/tebikihtml/index.htm",  # 令和7年分 法定調書の手引（HTML 版の目次）
    },
    # 3回目：PDF（国税庁の改正の Q&A・お知らせ・手引）
    "pdfs": {
        "tsukin2025_01": NTA + "/users/gensen/2025tsukin/pdf/01.pdf",   # 令和7年11月 通勤手当の非課税限度額の改正（お知らせ）
        "tsukin2025_02": NTA + "/users/gensen/2025tsukin/pdf/02.pdf",   # 年末調整で精算する際の源泉徴収簿の記載例
        "tsukin2026_01": NTA + "/users/gensen/2026tsukin/pdf/01.pdf",   # 令和8年4月 通勤手当の非課税限度額の改正に関する Q&A
        "tebiki2025_all": NTA + "/publication/pamph/hotei/tebiki2025/PDF/all.pdf",  # 令和7年分 法定調書の作成と提出の手引
        "tebiki2026_all": NTA + "/publication/pamph/hotei/tebiki2026/PDF/all.pdf",  # 令和8年分 同（令和8年8月1日現在の法令）
    },
    # 4回目：pages2 のリンクから（令和7年の Q&A、手引の HTML 版「④ 支払金額」。HTML 版は取得の時点で令和8年分に替わっていた）
    "pages3": {
        "tebikihtml_2_3_4": NTA + "/publication/pamph/hotei/tebikihtml/2-3-4.htm",  # 給与所得の源泉徴収票 ④ 支払金額
        "tsukin2025_03": NTA + "/users/gensen/2025tsukin/pdf/03.pdf",               # 通勤手当の非課税限度額の引上げに関する Q&A（令和7年）
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
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers or {})


def run_set(name):
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL2_tsukin_nta_{name}"
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
        if is_pdf:
            item["pdf_header_ok"] = body[:5] == b"%PDF-"
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
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL2_tsukin_nta_robots"
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

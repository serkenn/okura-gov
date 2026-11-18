"""IMPL4 web: impl-research4 の項目（所法64①の国税庁の説明、寄附金の告示、被扶養者の「今後1年間の収入」の保険者の基準、
国年則第77条の6第34号の指定、国保の特例）に関係するページ・PDF を取得する。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL4_web_fetch.py <set> [<set> ...]
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL4_web_fetch.py --list

- scripts/IMPL3_web_fetch.py を写し、SETS・NAME・説明だけを変えた（import はしない）。robots.txt はホストごとに確かめ、
  許されていない URL は取得しない（記録だけする）。
- 取得したもの（HTML・PDF）は信頼できないデータとして、取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_IMPL4_web_fetch_<set>/ に置く。その中でインタプリタやツールは実行しない。
- HTML から取り出したテキストとリンクは scripts/results/IMPL4_web_fetch/<set>/<id>.txt / <id>.links.json に書く。
- PDF はここではテキスト化しない（保存先と SHA-256 を記録する。文字の取り出しは scripts/IMPL4_web_pdftext.py）。
- 官報は取得しない。リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。
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
NAME = "IMPL4_web_fetch"
OUT = ROOT / "scripts" / "results" / NAME

NTA = "https://www.nta.go.jp"
SETS = {
    "nta": {
        "kihon_13_01": NTA + "/law/tsutatsu/kihon/shotoku/13/01.htm",          # 所基通 第6款（法63・64 関係）
        "kihon_13_index": NTA + "/law/tsutatsu/kihon/shotoku/13/",
        "shitsugi_02_27": NTA + "/law/shitsugi/shotoku/02/27.htm",             # 質疑応答：未収家賃の回収不能（法64①・令180②）
        "kobetsu_770822_01": NTA + "/law/tsutatsu/kobetsu/shotoku/shinkoku/770822/01.htm",  # 配当の受領の辞退と法64①
        "ta_1400": NTA + "/taxes/shiraberu/taxanswer/shotoku/1400.htm",        # 給与所得
        "kihon_06_index": NTA + "/law/tsutatsu/kihon/shotoku/06/",
    },
    "nta2": {
        "kihon_09_02": NTA + "/law/tsutatsu/kihon/shotoku/09/02.htm",          # 所基通 法51関係（51-11〜51-16 を探す）
        "kihon_09_03": NTA + "/law/tsutatsu/kihon/shotoku/09/03.htm",
    },
    "verify": {  # 反証の確認（docs/measurements/20261112_impl-research4_verification.md）
        "kashiwa_zyutoku": "https://www.city.kashiwa.lg.jp/hokennenkin/hokennenkin/kokuho/todokede/zyutoku.html",
        "mhlw_T251107S0010": "https://www.mhlw.go.jp/hourei/doc/tsuchi/T251107S0010.pdf",
    },
    "kifu": {
        "mof_ko_19650430_0154": "https://www.mof.go.jp/about_mof/act/kokuji_tsuutatsu/kokuji/KO-19650430-0154.pdf",
        "mof_ko_20261013_277": "https://www.mof.go.jp/tax_policy/reference/KO-20261013-277.pdf",
        "mof_ko_20240930_242": "https://www.mof.go.jp/about_mof/act/kokuji_tsuutatsu/kokuji/KO-20240930-242.pdf",
        "soumu_001096071": "https://www.soumu.go.jp/main_content/001096071.pdf",
        "soumu_000698503": "https://www.soumu.go.jp/main_content/000698503.pdf",
        "soumu_000948010": "https://www.soumu.go.jp/main_content/000948010.pdf",
        "soumu_000614893": "https://www.soumu.go.jp/main_content/000614893.pdf",
        "soumu_se_080331_08152_a": "https://www.soumu.go.jp/menu_hourei/s_hourei/pdf/se_080331_08152_a.pdf",
    },
    "hifuyosha": {
        "fukuoka_kijun": "https://fukuoka-kyosai.jp/reiki_int/reiki_honbun/x650RG00000067.html",
        "hiroshima_130moushitate": "https://jinji.hiroshima-u.ac.jp/kyosai/news/kennin/130moushitate.pdf",
        "hiroshima_130moushitate_rei": "https://jinji.hiroshima-u.ac.jp/kyosai/news/kennin/130moushitate(rei).pdf",
        "nara_2018_01_18": "https://kyosai-nara.jp/pdf/sukoyaka/252/pdf/2018_01_18.pdf",
        "ehime_20250701": "https://kyosai-ehime.or.jp/upfile/filebank/topic/20250701ninteiyouken.pdf",
        "tokyo_fuyou": "https://www.kyosai.metro.tokyo.jp/prv/qualification/fuyou/data/55a3bd4406bd54df88e6c763846cb6f9.pdf",
        "okayama_fuyo": "https://www.okayama-u.ac.jp/user/jinji/syotetuduki/hi/fuyo.pdf",
        "mhlw_001678029": "https://www.mhlw.go.jp/content/001678029.pdf",
    },
    "kokunen": {
        "nenkin_gakusei_pdf": "https://www.nenkin.go.jp/service/kokunen/menjo/gakutokutaisyouko.files/gakusei.pdf",
        "nenkin_gakutokutaisyouko": "https://www.nenkin.go.jp/service/kokunen/menjo/gakutokutaisyouko.html",
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
            return r.status, r.read(), dict(r.headers), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers or {}), url


_ROBOTS = {}


def robots_allowed(url, dl, log):
    host = urllib.parse.urlsplit(url)
    base = f"{host.scheme}://{host.netloc}"
    if base not in _ROBOTS:
        st, body, hd, _ = fetch(base + "/robots.txt")
        (dl / f"robots_{host.netloc}.txt").write_bytes(body)
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(body.decode("utf-8", "replace").splitlines() if st == 200 else [])
        _ROBOTS[base] = rp
        log["robots"].append({"host": base, "status": st, "sha256": hashlib.sha256(body).hexdigest()})
        time.sleep(WAIT)
    return _ROBOTS[base].can_fetch(UA, url)


def run_set(name):
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_{NAME}_{name}"
    dl.mkdir(parents=True, exist_ok=False)
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    log = {"set": name, "fetched_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "robots": [], "items": []}
    for key, url in SETS[name].items():
        if not robots_allowed(url, dl, log):
            log["items"].append({"id": key, "url": url, "skipped": "robots.txt で許されていない"})
            print("skip(robots)", key, flush=True)
            continue
        try:
            st, body, hd, final = fetch(url)
        except Exception as e:  # noqa
            log["items"].append({"id": key, "url": url, "error": repr(e)})
            print("ERR", key, repr(e), flush=True)
            time.sleep(WAIT)
            continue
        ctype = hd.get("Content-Type", "")
        is_pdf = "pdf" in ctype.lower() or url.lower().endswith(".pdf")
        is_xlsx = url.lower().endswith(".xlsx")
        fn = dl / (key + (".pdf" if is_pdf else ".xlsx" if is_xlsx else ".htm"))
        fn.write_bytes(body)
        item = {"id": key, "url": url, "final_url": final, "status": st, "content_type": ctype, "last_modified": hd.get("Last-Modified"),
                "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(), "saved": str(fn.relative_to(ROOT)).replace("\\", "/")}
        if is_pdf:
            item["pdf_header_ok"] = body[:5] == b"%PDF-"
        if is_xlsx:
            item["zip_header_ok"] = body[:2] == b"PK"
        if not is_pdf and not is_xlsx and st == 200:
            text, enc = decode(body, ctype)
            p = Page(final)
            p.feed(text)
            title = re.search(r"<title>(.*?)</title>", text, re.S)
            item["title"] = re.sub(r"\s+", " ", title.group(1)).strip() if title else None
            item["encoding"] = enc
            (out / f"{key}.txt").write_text(f"# source={url}\n# final_url={final}\n# fetched_at={ts}\n# last_modified={hd.get('Last-Modified')}\n"
                                            f"# sha256={item['sha256']}\n\n{p.text()}\n", encoding="utf-8")
            (out / f"{key}.links.json").write_text(json.dumps(p.links, ensure_ascii=False, indent=1), encoding="utf-8")
        log["items"].append(item)
        print("ok", key, st, len(body), item.get("title"), flush=True)
        time.sleep(WAIT)
    (out / f"fetch_log_{ts}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    args = sys.argv[1:]
    if not args or args == ["--list"]:
        for k, v in SETS.items():
            print(k, len(v))
        return
    for a in args:
        run_set(a)


if __name__ == "__main__":
    main()

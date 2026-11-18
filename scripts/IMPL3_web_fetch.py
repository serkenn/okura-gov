"""IMPL3 web: 国税庁・総務省・厚生労働省・日本年金機構のページのうち、impl-research3 の項目（非居住者の親族の所得、配当控除と負債の利子、
所得控除の順序、住宅借入金等特別控除と年末調整、生命保険料の剰余金、資産損失、年齢、ふるさと納税の指定、団体コード、国保・国年）に関係するものを取得する。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL3_web_fetch.py --robots
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL3_web_fetch.py <set> [<set> ...]
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL3_web_fetch.py --list

- HTML の取得とテキスト化は scripts/IMPL2_phase2c_nta.py を写した（import はしない）。robots.txt はホストごとに確かめ、
  許されていない URL は取得しない（記録だけする）。
- 取得したもの（HTML・PDF）は信頼できないデータとして、取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_IMPL3_web_fetch_<set>/ に置く。その中でインタプリタやツールは実行しない。
- HTML から取り出したテキストとリンクは scripts/results/IMPL3_web_fetch/<set>/<id>.txt / <id>.links.json に書く。
- PDF はここではテキスト化しない（保存先と SHA-256 を記録する。文字の取り出しは scripts/IMPL3_pdftext.py）。
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
NAME = "IMPL3_web_fetch"
OUT = ROOT / "scripts" / "results" / NAME

NTA = "https://www.nta.go.jp"
KIHON = NTA + "/law/tsutatsu/kihon/shotoku/"
TA = NTA + "/taxes/shiraberu/taxanswer/shotoku/"
SOCHI = NTA + "/law/tsutatsu/kobetsu/shotoku/sochiho/801226/sinkoku/57/"
SANRIN = NTA + "/law/tsutatsu/kobetsu/shotoku/sochiho/710826/sanrin/sanjyou/"
SOUMU = "https://www.soumu.go.jp"
NENKIN = "https://www.nenkin.go.jp"
SETS = {
    "nta_tsutatsu": {
        "kihon_01_07": KIHON + "01/07.htm",      # 法2 扶養親族など（2-47 など）
        "kihon_01_08": KIHON + "01/08.htm",      # 法3 居住者・非居住者
        "kihon_09_01": KIHON + "09/01.htm",      # 法51 固定資産等の損失（51-1〜）
        "kihon_16_01": KIHON + "16/01.htm",      # 法72 雑損控除
        "kihon_16_03": KIHON + "16/03.htm",      # 法76 生命保険料控除（76-5〜76-8）
        "kihon_16_06": KIHON + "16/06.htm",      # 法79〜85
        "kihon_24_01": KIHON + "24/01.htm",      # 法165
        "kihon_31_01": KIHON + "31/01.htm",      # 法185
        "sanrin_soti31_02": SANRIN + "soti31/02.htm",  # 措通31・32共-6（雑損失の繰越控除及び所得控除の順序）
        "sochi_41_02": SOCHI + "41/02.htm",      # 措通41の2の2 関係
    },
    "nta_ta": {
        "ta_1180": TA + "1180.htm", "ta_1250": TA + "1250.htm", "ta_1330": TA + "1330.htm", "ta_1140": TA + "1140.htm",
        "ta_1110": TA + "1110.htm", "ta_1900": TA + "1900.htm", "ta_1910": TA + "1910.htm",
        "annai_1557_2": NTA + "/taxes/tetsuzuki/shinsei/annai/shinkoku/annai/1557_2.htm",
    },
    "nta_more": {
        "ta_1180_qa": TA + "1180_qa.htm",          # Q4 日本国外に住む親族、Q7 年の中途で死亡
        "ta_1191": TA + "1191.htm",                # 配偶者控除（年齢・死亡の判定時期の記載を見る）
    },
    "nta_more2": {
        "kihon_15_01": KIHON + "15/01.htm",       # 法69〜71（70−6〜70−12：所基通72−7 が令206①各号の支出の範囲で準ずる先）
    },
    "nta_pdf": {
        "kokugai_qa_gensen": NTA + "/publication/pamph/pdf/0022009-107_02.pdf",
        "haito_keisansho": NTA + "/taxes/tetsuzuki/shinsei/annai/shinkoku/annai/pdf/10-03.pdf",
        "haito_keisansho_ki": NTA + "/taxes/tetsuzuki/shinsei/annai/shinkoku/annai/pdf/10-03-ki.pdf",
    },
    "soumu": {
        "code_page": SOUMU + "/denshijiti/code.html",
        "furusato_kojin": SOUMU + "/main_sosiki/jichi_zeisei/czaisei/czaisei_seido/080430_2_kojin.html",
        "furusato_top": SOUMU + "/main_sosiki/jichi_zeisei/czaisei/czaisei_seido/furusato/",
        "furusato_about": SOUMU + "/main_sosiki/jichi_zeisei/czaisei/czaisei_seido/furusato/about/",
    },
    "soumu_pdf": {
        "code_spec": SOUMU + "/main_content/000137948.pdf",
        "furusato_report2019": SOUMU + "/main_sosiki/jichi_zeisei/czaisei/czaisei_seido/furusato/file/report20190401_04.pdf",
    },
    "soumu_xlsx": {
        "code_list_xlsx": SOUMU + "/main_content/000925835.xlsx",   # 都道府県コード及び市区町村コード（令和6年1月1日更新）
    },
    "mhlw_nenkin": {
        "mhlw_iryohoken_bukai": "https://www.mhlw.go.jp/stf/shingi/shingi-hosho_126706.html",
        "nenkin_menjo": NENKIN + "/service/kokunen/menjo/20150428.html",
        "nenkin_sanzen": NENKIN + "/service/kokunen/menjo/20180810.html",
        "nenkin_fuka": NENKIN + "/service/kokunen/hokenryo/20150331-02.html",
        "nenkin_gakusei": NENKIN + "/service/kokunen/menjo/20150514.html",
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

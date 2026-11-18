"""IMPL2 phase2c: 国税庁のタックスアンサー・通達・手引き・様式の書き方のうち、実装で「一次情報が docs にない」と報告された項目
（政党等寄附金特別控除、配当、分離課税の順序、所法121、源泉徴収税額、端数、減価償却費の端数）に関係するページを取得する。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:/Users/user/.pyenv/pyenv-win/versions/3.11.9/python.exe -I -X utf8 scripts/IMPL2_phase2c_nta.py --robots
  C:/Users/user/.pyenv/pyenv-win/versions/3.11.9/python.exe -I -X utf8 scripts/IMPL2_phase2c_nta.py <set> [<set> ...]
  C:/Users/user/.pyenv/pyenv-win/versions/3.11.9/python.exe -I -X utf8 scripts/IMPL2_phase2c_nta.py --list
  C:/Users/user/.pyenv/pyenv-win/versions/3.11.9/python.exe -I -X utf8 scripts/IMPL2_phase2c_nta.py --robots-keisan

- HTML の取得とテキスト化は scripts/IMPL2_tsukin_nta.py を写した（import はしない）。
- 取得したもの（HTML・PDF）は信頼できないデータとして、取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_IMPL2_phase2c_nta_<set>/ に置く。その中でインタプリタやツールは実行しない。
- HTML から取り出したテキストとリンクは scripts/results/IMPL2_phase2c_nta/<set>/<id>.txt / <id>.links.json に書く。
- PDF はテキスト化しない（ダウンロード先のパスと SHA-256 だけを記録する。文字の取り出しは scripts/IMPL2_genka_pdftext.py）。
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
OUT = ROOT / "scripts" / "results" / "IMPL2_phase2c_nta"
PREFIX = "IMPL2_phase2c_nta"

NTA = "https://www.nta.go.jp"
TA = NTA + "/taxes/shiraberu/taxanswer/shotoku/"
TAG = NTA + "/taxes/shiraberu/taxanswer/gensen/"
KIHON = NTA + "/law/tsutatsu/kihon/shotoku/"
SOCHI = NTA + "/law/tsutatsu/kobetsu/shotoku/sochiho/801226/sinkoku/"
TEBIKI = NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/"
SETS = {
    "index": {
        "kihon_index": KIHON + "01.htm",
        "sochi_index": SOCHI + "01.htm",
        "tebiki_3_01": TEBIKI + "03/3_01.htm",
        "tebiki_order2_3_2_01": TEBIKI + "03/order2/3-2_01.htm",
        "tebiki_order5_3_5_01": TEBIKI + "03/order5/3-5_01.htm",
        "r07": NTA + "/taxes/shiraberu/shinkoku/syotoku/r07.htm",
        "r08": NTA + "/taxes/shiraberu/shinkoku/syotoku/r08.htm",
    },
    "ta": {
        "ta_1150": TA + "1150.htm", "ta_1250": TA + "1250.htm", "ta_1260": TA + "1260.htm", "ta_1263": TA + "1263.htm",
        "ta_1266": TA + "1266.htm", "ta_1330": TA + "1330.htm", "ta_1331": TA + "1331.htm", "ta_1420": TA + "1420.htm",
        "ta_1474": TA + "1474.htm", "ta_1600": TA + "1600.htm", "ta_1900": TA + "1900.htm", "ta_2020": TA + "2020.htm",
        "ta_2030": TA + "2030.htm", "ta_2100": TA + "2100.htm", "ta_2105": TA + "2105.htm", "ta_2106": TA + "2106.htm",
        "tag_2732": TAG + "2732.htm", "tag_2792": TAG + "2792.htm", "tag_2503": TAG + "2503.htm",
    },
    "tsutatsu": {
        "kihon_19_01": KIHON + "19/01.htm", "kihon_19_02": KIHON + "19/02.htm",
    },
    "tsutatsu2": {
        "kihon_04_01": KIHON + "04/01.htm", "kihon_08_05": KIHON + "08/05.htm", "kihon_08_04": KIHON + "08/04.htm",
        "kihon_31_01": KIHON + "31/01.htm", "kihon_34_01": KIHON + "34/01.htm", "kihon_35_01": KIHON + "35/01.htm",
        "kihon_30_01": KIHON + "30/01.htm", "sochi_41_17": SOCHI + "57/41/17.htm", "sochi_41_17_2": SOCHI + "57/41/17_2.htm",
        "sochi_41_17_3": SOCHI + "57/41/17_3.htm", "sochi_08_04": SOCHI + "57/08/04.htm",
    },
    "tebiki_html": {
        **{f"t3_2_{i:02d}": TEBIKI + f"03/order2/3-2_{i:02d}.htm" for i in range(1, 14)},
        "t3_2_08_1": TEBIKI + "03/order2/3-2_08_1.htm", "t3_2_08_2": TEBIKI + "03/order2/3-2_08_2.htm",
        **{f"t3_4_{i:02d}": TEBIKI + f"03/order4/3-4_{i:02d}.htm" for i in range(27, 44)},
        **{f"t3_5_{i:02d}": TEBIKI + f"03/order5/3-5_{i:02d}.htm" for i in range(1, 8)},
    },
    "forms": {
        "form_seito": NTA + "/taxes/shiraberu/shinkoku/yoshiki/04/pdf/06.pdf",
        "form_seito_ki": NTA + "/taxes/shiraberu/shinkoku/yoshiki/04/pdf/06-ki.pdf",
        "form_npo": NTA + "/taxes/shiraberu/shinkoku/yoshiki/04/pdf/09-1.pdf",
        "form_npo_ki": NTA + "/taxes/shiraberu/shinkoku/yoshiki/04/pdf/09-1-ki.pdf",
        "form_koeki": NTA + "/taxes/shiraberu/shinkoku/yoshiki/04/pdf/09-4.pdf",
        "form_koeki_ki": NTA + "/taxes/shiraberu/shinkoku/yoshiki/04/pdf/09-4-ki.pdf",
        "form_daisan": NTA + "/taxes/shiraberu/shinkoku/yoshiki/01/shinkokusho/pdf/r07/02.pdf",
        "form_daiichi": NTA + "/taxes/shiraberu/shinkoku/yoshiki/01/shinkokusho/pdf/r07/01.pdf",
    },
    "genka_keisan": {
        "keisan_r5_hasu": "https://www.keisan.nta.go.jp/r5yokuaru/aoiroshinkoku/hitsuyokeihi/genkashokyakuhi/hasushori.html",
        "keisan_r6_hasu": "https://www.keisan.nta.go.jp/r6yokuaru/aoiroshinkoku/hitsuyokeihi/genkashokyakuhi/hasushori.html",
        "keisan_r7_hasu": "https://www.keisan.nta.go.jp/r7yokuaru/aoiroshinkoku/hitsuyokeihi/genkashokyakuhi/hasushori.html",
        "saigai_genka": NTA + "/taxes/shiraberu/saigai/h30/0018008-045/05.htm",
        "hojin_bappyo16_1": NTA + "/publication/pamph/hojin/aramashi2025/pdf/02-17.pdf",
        "shitsugi_04_17": NTA + "/law/shitsugi/shotoku/04/17.htm",
        "kobetsu_hasu_tsusoku_119": NTA + "/law/tsutatsu/kihon/tsusoku/09/01/119.htm",
    },
    "genka_keisan2": {
        "keisan_r7_teigakuho": "https://www.keisan.nta.go.jp/r7yokuaru/aoiroshinkoku/hitsuyokeihi/genkashokyakuhi/teigakuho.html",
        "keisan_r7_ikkatsu": "https://www.keisan.nta.go.jp/r7yokuaru/aoiroshinkoku/hitsuyokeihi/genkashokyakuhi/ikkatsushokyaku.html",
        "keisan_r7_shogaku": "https://www.keisan.nta.go.jp/r7yokuaru/aoiroshinkoku/hitsuyokeihi/genkashokyakuhi/shogakugenkashokyaku.html",
        "keisan_r7_kikan": "https://www.keisan.nta.go.jp/r7yokuaru/aoiroshinkoku/hitsuyokeihi/genkashokyakuhi/shokyakukikan.html",
        "keisan_r7_zumi": "https://www.keisan.nta.go.jp/r7yokuaru/aoiroshinkoku/hitsuyokeihi/genkashokyakuhi/shokyakuzuminyuryoku.html",
        "keisan_r7_kyuteigaku": "https://www.keisan.nta.go.jp/r7yokuaru/aoiroshinkoku/hitsuyokeihi/genkashokyakuhi/kyuteigakuho.html",
        "keisan_r7_index": "https://www.keisan.nta.go.jp/r7yokuaru/aoiroshinkoku/hitsuyokeihi/genkashokyakuhi/index.html",
    },
    "hotei": {
        "hotei_index": NTA + "/publication/pamph/hotei/tebikihtml/index.htm",
    },
    "hotei2": {
        "hotei_3_2_0": NTA + "/publication/pamph/hotei/tebikihtml/3-2-0.htm",
        "hotei_3_2_5": NTA + "/publication/pamph/hotei/tebikihtml/3-2-5.htm",
        "hotei_3_2_6": NTA + "/publication/pamph/hotei/tebikihtml/3-2-6.htm",
        "hotei_4_2_0": NTA + "/publication/pamph/hotei/tebikihtml/4-2-0.htm",
        "hotei_4_2_5": NTA + "/publication/pamph/hotei/tebikihtml/4-2-5.htm",
        "hotei_4_2_6": NTA + "/publication/pamph/hotei/tebikihtml/4-2-6.htm",
    },
    "nencho": {
        "nencho2026_107": NTA + "/publication/pamph/gensen/nencho2026/pdf/107.pdf",
        "ta_1140": TA + "1140.htm",
    },
    "pdfs": {
        "tebiki_001": TEBIKI + "pdf/001.pdf",
        "tebiki_037": TEBIKI + "pdf/037.pdf",
        "tebiki_025": TEBIKI + "pdf/025.pdf",
        "tebiki_034": TEBIKI + "pdf/034.pdf",
        "tebiki_039": TEBIKI + "pdf/039.pdf",
        "tebiki_019": TEBIKI + "pdf/019.pdf",
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
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL2_phase2c_nta_{name}"
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
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL2_phase2c_nta_robots"
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


def check_robots_keisan():
    """keisan.nta.go.jp の robots.txt（確定申告書等作成コーナーのよくある質問）を確かめる。"""
    import urllib.robotparser
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL2_phase2c_keisan_robots"
    dl.mkdir(parents=True, exist_ok=False)
    st, body, hd = fetch("https://www.keisan.nta.go.jp/robots.txt")
    (dl / "robots.txt").write_bytes(body)
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(body.decode("utf-8", "replace").splitlines() if st == 200 else [])
    urls = [v for s_ in ("genka_keisan", "genka_keisan2") for v in SETS[s_].values() if "keisan.nta.go.jp" in v]
    res = {"fetched_at": ts, "status": st, "allowed": {u: rp.can_fetch(UA, u) for u in urls}, "body_head": body[:600].decode("utf-8", "replace")}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "keisan_robots.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("keisan robots", st, res["allowed"])


def main():
    args = sys.argv[1:]
    if args == ["--robots"]:
        check_robots()
        return
    if args == ["--robots-keisan"]:
        check_robots_keisan()
        return
    if not args or args == ["--list"]:
        for k, v in SETS.items():
            print(k, len(v))
        return
    for a in args:
        run_set(a)


if __name__ == "__main__":
    main()

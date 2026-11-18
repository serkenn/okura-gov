"""R2X_gaps: 残っていた個別の未解決のうち、国税庁・日本年金機構・厚労省・協会けんぽ・総務省の公表資料で確かめるものを取得し、
HTML は本文のテキストとリンクを取り出す（PDF はテキスト化せず、保存先と SHA-256 を記録して Read ツールで読む）。

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_gaps_web.py --list
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_gaps_web.py <set> [<set> ...]

- scripts/IMPL_jigyo_nta.py のコード（Page、decode、fetch）を写して作った（import はしない）。標準ライブラリのみ。
- 取得の前に、そのホストの robots.txt を取得し、urllib.robotparser で User-agent okura-gov-research/0.1 に許されるかを判定する。
  許されない URL は取得しない（記録だけ残す）。
- 取得したもの（HTML・PDF・robots.txt）は信頼できないデータとして、セットごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_R2X_gaps_web_<set>/ に置く。その中でインタプリタやツールは実行しない。
- HTML から取り出したテキストとリンクは scripts/results/R2X_gaps_web/<set>/<id>.txt / <id>.links.json に書く。
  画像で表示される文字は img の alt を〔alt:...〕の形で残す。
- 取得記録（robots の判定、ステータス、Content-Type、Last-Modified、SHA-256、バイト数）は scripts/results/R2X_gaps_web/<set>/fetch_log.json。
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。個人の情報は送らない。官報は取得しない。
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
OUT = ROOT / "scripts" / "results" / "R2X_gaps_web"

NTA = "https://www.nta.go.jp"
TA = NTA + "/taxes/shiraberu/taxanswer/shotoku/"
KIHON = NTA + "/law/tsutatsu/kihon/shotoku/"
NENKIN = "https://www.nenkin.go.jp"
SETS = {
    # (1)(2)(3)(4)：国税庁のタックスアンサー・通達・手引き・年末調整 Q&A
    "nta": {
        "ta_1175": TA + "1175.htm",      # 勤労学生控除
        "ta_1810": TA + "1810.htm",      # 家内労働者等の必要経費の特例
        "ta_1810_qa": TA + "1810_qa.htm",
        "ta_1411": TA + "1411.htm",      # 所得金額調整控除
        "ta_1199": TA + "1199.htm",      # 基礎控除
        "ta_1500": TA + "1500.htm",      # 雑所得
        "kihon_01_07": KIHON + "01/07.htm",   # 所得税基本通達 法第2条（勤労学生）関係
        "kihon_04_09": KIHON + "04/09.htm",   # 所得税基本通達 法第35条（雑所得）関係
        "tokushu_chui": NTA + "/taxes/shiraberu/shinkoku/tokushu/shinkoku-tyuui/",   # こんな収入の申告漏れにご注意
        "tebiki_r07_3_3_15": NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/03/order3/3-3_15.htm",  # 手順3 所得控除（勤労学生控除を含む）
        "nencho2025_qa": NTA + "/publication/pamph/gensen/nencho2025/qa.htm",
        "nencho2026_qa": NTA + "/publication/pamph/gensen/nencho2026/qa.htm",
    },
    # (3)：措置法通達（所得税）第41条の3の11・第41条の3の12 関係（TA No.1411 の根拠に挙がる 措通41の3の11-1 を含む）
    "sochitsu": {
        "sochitsu_41_3_11": NTA + "/law/tsutatsu/kobetsu/shotoku/sochiho/801226/sinkoku/57/41/03_2.htm",
        "sochitsu_41_3_12": NTA + "/law/tsutatsu/kobetsu/shotoku/sochiho/801226/sinkoku/57/41/03_4.htm",
    },
    # (1)：確定申告書等作成コーナーの「よくある質問」（別ホスト）
    "keisan": {
        "keisan_r7_kinro_cid472": "https://www.keisan.nta.go.jp/r7yokuaru/cat2/cat22/cat228/cid472.html",   # 勤労学生控除とは
        "keisan_r7_kinro_index": "https://www.keisan.nta.go.jp/r7yokuaru/cat2/cat22/cat228/index.html",
    },
    # (6)：日本年金機構
    "nenkin": {
        "gigishokai_index": NENKIN + "/service/seidozenpan/gigishokai.html",
        "gigishokai_kounen_tekiyou": NENKIN + "/service/seidozenpan/gigishokai.files/kounen_tekiyou.pdf",
        "gigishokai_kokunen_tekiyou": NENKIN + "/service/seidozenpan/gigishokai.files/kokunen_tekiyou.pdf",
        "faq_19to22_income": NENKIN + "/section/faq/kounen/dependents/aged19to22/income.html",
        "vaccine_20220225": NENKIN + "/oshirase/taisetu/2022/202202/20220225.html",
        "jimupoint_vol3": NENKIN + "/service/kounen/info/jimupoint.files/Vol.3.pdf",
        "setsumei_fuyou": NENKIN + "/shinsei/kounen/tekiyo/hihokensha/20141224.files/setumei.pdf",
    },
    # (6)：厚生労働省
    "mhlw": {
        "mhlw_000991674": "https://www.mhlw.go.jp/content/12400000/000991674.pdf",
        "mhlw_T251006S0060": "https://www.mhlw.go.jp/hourei/doc/tsuchi/T251006S0060.pdf",
    },
    # (6)：厚生労働省 法令等データベースの事務連絡（000991674.pdf の Q&A が引く「被扶養者の収入の確認における留意点について」）
    "mhlw2": {
        "mhlw_00tc5007_p1": "https://www.mhlw.go.jp/web/t_doc?dataId=00tc5007&dataType=1&pageNo=1",
        "mhlw_00tc5007_p2": "https://www.mhlw.go.jp/web/t_doc?dataId=00tc5007&dataType=1&pageNo=2",
        "mhlw_000744680_saishuchi": "https://www.mhlw.go.jp/content/000744680.pdf",
        "mhlw_00tc5958_p1": "https://www.mhlw.go.jp/web/t_doc?dataId=00tc5958&dataType=1&pageNo=1",
        "mhlw_newpage_19044": "https://www.mhlw.go.jp/stf/newpage_19044.html",
    },
    # (6)：日本年金機構の疑義照会回答（厚生年金保険 適用）が引く「昭和61年4月1日 庁保発第18号」の本文を探すための資料
    "mhlw3": {
        "mhlw_nenkin_0000086587": "https://www.mhlw.go.jp/file/06-Seisakujouhou-12500000-Nenkinkyoku/0000086587.pdf",
        "mhlw_shinsa_r02_03_15_01": "https://www.mhlw.go.jp/topics/bukyoku/shinsa/syakai/dl/05-r02_03/15_01.pdf",
    },
    # (6)：総務省（行政評価局の資料）
    "soumu": {
        "soumu_kanto_110113_1": "https://www.soumu.go.jp/kanku/kanto/pdf/110113_1.pdf",
        "soumu_kanto_120607_5": "https://www.soumu.go.jp/kanku/kanto/pdf/120607_5.pdf",
    },
    # (6)：協会けんぽ
    "kyoukai": {
        "kyoukai_covid19tokurei_nsyutoku": "https://www.kyoukaikenpo.or.jp/~/media/Files/honbu/g2/cat230/covid19tokurei_nsyutoku.pdf",
        "kyoukai_covid19i_fuyousaikakunin": "https://www.kyoukaikenpo.or.jp/~/media/Files/honbu/event/covid19/covid19i_fuyousaikakunin.pdf",
        "kyoukai_faq_dependent_status": "https://www.kyoukaikenpo.or.jp/faq/dependent_status/",
    },
    # (2)：TA No.1810 の過去の版（Internet Archive の CDX で、保存された版の一覧だけを取る）
    "archive": {
        "cdx_ta_1810": "https://web.archive.org/cdx/search/cdx?url=www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1810.htm&output=json&fl=timestamp,statuscode,digest,length&collapse=digest",
    },
    # (2)：CDX の一覧（archive の結果）から選んだ版の、保存時の元の HTML（URL の「id_」は Internet Archive の書き換えなしの原本）。
    #      令和6年分の版（2024-11）、改正後の最初の版（2025-11）、現在に近い版（2026-09）
    "archive2": {
        "wa_ta_1810_20241105": "https://web.archive.org/web/20241105195653id_/https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1810.htm",
        "wa_ta_1810_20250317": "https://web.archive.org/web/20250317120454id_/https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1810.htm",
        "wa_ta_1810_20251105": "https://web.archive.org/web/20251105081756id_/https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1810.htm",
        "wa_ta_1810_20260915": "https://web.archive.org/web/20260915033802id_/https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1810.htm",
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
            return r.status, r.read(), dict(r.headers), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers or {}), url


def robots_for(host, dl, cache, log):
    if host in cache:
        return cache[host]
    url = f"https://{host}/robots.txt"
    try:
        st, body, hd, _ = fetch(url)
    except Exception as e:  # noqa
        log.append({"host": host, "url": url, "error": repr(e)})
        cache[host] = None
        time.sleep(WAIT)
        return None
    fn = dl / f"robots_{host}.txt"
    fn.write_bytes(body)
    rp = urllib.robotparser.RobotFileParser()
    if st == 200:
        rp.parse(body.decode("utf-8", "replace").splitlines())
    elif st in (401, 403):
        rp.disallow_all = True
    else:
        rp.allow_all = True
    log.append({"host": host, "url": url, "status": st, "sha256": hashlib.sha256(body).hexdigest(),
                "saved": str(fn.relative_to(ROOT)).replace("\\", "/")})
    cache[host] = rp
    time.sleep(WAIT)
    return rp


def run_set(name):
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_gaps_web_{name}"
    dl.mkdir(parents=True, exist_ok=False)
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    log = {"set": name, "fetched_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "robots": [], "items": []}
    cache = {}
    for key, url in SETS[name].items():
        host = urllib.parse.urlsplit(url).hostname
        rp = robots_for(host, dl, cache, log["robots"])
        allowed = True if rp is None else rp.can_fetch(UA, url)
        if not allowed:
            log["items"].append({"id": key, "url": url, "robots_allowed": False, "skipped": True})
            print("SKIP(robots)", key, flush=True)
            continue
        try:
            st, body, hd, final = fetch(url)
        except Exception as e:  # noqa
            log["items"].append({"id": key, "url": url, "robots_allowed": allowed, "error": repr(e)})
            print("ERR", key, repr(e), flush=True)
            time.sleep(WAIT)
            continue
        ctype = hd.get("Content-Type", "")
        is_pdf = "pdf" in ctype.lower() or url.lower().endswith(".pdf")
        is_json = "json" in ctype.lower() or "output=json" in url
        ext = ".pdf" if is_pdf else (".json" if is_json else ".htm")
        fn = dl / (key + ext)
        fn.write_bytes(body)
        item = {"id": key, "url": url, "final_url": final, "robots_allowed": allowed, "status": st, "content_type": ctype,
                "last_modified": hd.get("Last-Modified"), "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
                "saved": str(fn.relative_to(ROOT)).replace("\\", "/")}
        if not is_pdf and st == 200:
            text, enc = decode(body, ctype)
            if is_json:
                (out / f"{key}.txt").write_text(f"# source={url}\n# fetched_at={ts}\n# sha256={item['sha256']}\n\n{text}\n", encoding="utf-8")
            else:
                p = Page(final)
                p.feed(text)
                title = re.search(r"<title>(.*?)</title>", text, re.S)
                item["title"] = re.sub(r"\s+", " ", title.group(1)).strip() if title else None
                item["encoding"] = enc
                body_text = p.text()
                item["text_sha256"] = hashlib.sha256(body_text.encode("utf-8")).hexdigest()
                (out / f"{key}.txt").write_text(f"# source={url}\n# final_url={final}\n# fetched_at={ts}\n# last_modified={hd.get('Last-Modified')}\n# sha256={item['sha256']}\n# text_sha256={item['text_sha256']}\n\n{body_text}\n", encoding="utf-8")
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
        run_set(a)


if __name__ == "__main__":
    main()

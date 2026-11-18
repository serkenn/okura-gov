"""R2X aoiro: 国税庁の通達・タックスアンサー・手続の案内・様式のうち、青色申告（承認・帳簿・特別控除・専従者給与・
純損失・現金主義）に関係するページを取得し、本文のテキストとリンクを取り出す。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_aoiro_nta.py --robots
      robots.txt を取得し、SETS のすべての URL が User-Agent okura-gov-research/0.1 で許されるかを判定（robots_check.json）
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_aoiro_nta.py <set> [<set> ...]
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_aoiro_nta.py --list

- HTML 取得とテキスト化は scripts/IMPL_jigyo_nta.py を写した（import はしない）。
- 取得したもの（HTML・PDF）は信頼できないデータとして、取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_R2X_aoiro_nta_<set>/ に置く。その中でインタプリタやツールは実行しない。
- HTML から取り出したテキストとリンクは scripts/results/R2X_aoiro_nta/<set>/<id>.txt / <id>.links.json に書く。
  画像で表示される文字は img の alt を〔alt:...〕の形で残す。
- PDF はテキスト化しない（ダウンロード先のパスと SHA-256 だけを記録し、人が Read ツールの pages 指定で読む）。
- 取得記録（ステータス、Content-Type、Last-Modified、SHA-256、バイト数）は scripts/results/R2X_aoiro_nta/<set>/fetch_log.json。
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。官報は取得しない。
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
OUT = ROOT / "scripts" / "results" / "R2X_aoiro_nta"

NTA = "https://www.nta.go.jp"
TA = NTA + "/taxes/shiraberu/taxanswer/shotoku/"
KIHON = NTA + "/law/tsutatsu/kihon/shotoku/"
ANNAI = NTA + "/taxes/tetsuzuki/shinsei/annai/shinkoku/annai/"
SETS = {
    # 1回目：タックスアンサー、所得税基本通達・措置法通達の該当ページ、手続の案内（目次と青色申告の手続）
    "pages": {
        "ta_2070": TA + "2070.htm",   # 青色申告制度
        "ta_2072": TA + "2072.htm",   # 青色申告特別控除
        "ta_2075": TA + "2075.htm",   # 青色事業専従者給与と事業専従者控除
        "ta_index2": NTA + "/taxes/shiraberu/taxanswer/index2.htm",  # タックスアンサー目次（純損失のコードを探す）
        "kihon_11_01": KIHON + "11/01.htm",   # 法第56条・第57条関係
        "kihon_14_02": KIHON + "14/02.htm",   # 法第66条〜第67条の3関係（現金主義）
        "kihon_15_01": KIHON + "15/01.htm",   # 法第70条〜第71条関係（純損失の繰越控除）
        "kihon_19_02": KIHON + "19/02.htm",   # 法第122条〜第142条関係（純損失の繰戻し）
        "kihon_20_01": KIHON + "20/01.htm",   # 法第143条〜第150条関係（青色申告）
        "sochitsu_25_2": NTA + "/law/tsutatsu/kobetsu/shotoku/sochiho/801226/sinkoku/57/25/01.htm",  # 措置法通達 25の2 関係
        "tetsuzuki_mokuji": NTA + "/taxes/tetsuzuki/shinsei/annai/shinkoku/mokuji.htm",  # 申告所得税関係の手続の目次
        "annai_09": ANNAI + "09.htm",          # 所得税の青色申告承認申請手続
        "annai_09_2": ANNAI + "09_2.htm",      # 65万円の青色申告特別控除・過少申告加算税の特例の適用を受ける旨の届出
        "annai_10": ANNAI + "10.htm",          # 青色申告承認申請書、現金主義の所得計算による旨の届出書
        "annai_12": ANNAI + "12.htm",          # 青色事業専従者給与に関する届出手続
        "annai_23200008": ANNAI + "23200008.htm",  # 所得税の青色申告の取りやめ手続
    },
    # 2回目：1回目のリンクから見つけたページ（純損失の繰戻し還付の手続、タックスアンサー）
    "pages2": {
        "ta_bunya_kojinjigyo": NTA + "/taxes/shiraberu/taxanswer/code/bunya-kojinjigyo.htm",  # タックスアンサー 分野別（個人事業）
        "annai_13": ANNAI + "13.htm",                # 青色事業専従者給与に関する変更届出手続
        "annai_17_0": ANNAI + "17_0.htm",            # 65万円の青色申告特別控除・過少申告加算税の特例の適用の取りやめの届出手続
        "annai_23200002": ANNAI + "23200002.htm",    # 純損失の金額の繰戻しによる所得税の還付請求手続
        "annai_23200010": ANNAI + "23200010.htm",    # 現金主義による所得計算の特例を受けるための手続
        "annai_23200011": ANNAI + "23200011.htm",    # 現金主義による所得計算の特例を受けることの取りやめ手続
        "annai_23200016": ANNAI + "23200016.htm",    # 再び現金主義による所得計算の特例の適用を受けることの承認申請手続
    },
    # 3回目：様式（PDF）と書き方・手引き（令和7年分の一覧 r07.htm と手続の案内のリンクから）
    "forms": {
        "kessan_ippan_r07": NTA + "/taxes/shiraberu/shinkoku/yoshiki/01/shinkokusho/pdf/r07/10.pdf",  # 所得税青色申告決算書（一般用）【令和５年分以降用】
        "kessan_ippan_kakikata_r07": NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/pdf/037.pdf",      # 令和７年分青色申告決算書（一般用）の書き方
        "kessan_tebiki_ippan_r07": NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/pdf/025.pdf",        # 令和７年分青色申告の決算の手引き（一般用）
        "kessan_genkin_r07": NTA + "/taxes/shiraberu/shinkoku/yoshiki/01/shinkokusho/pdf/r07/13.pdf",  # 所得税青色申告決算書（現金主義用）【令和２年分以降用】
        "shinkoku_dai4_r07": NTA + "/taxes/shiraberu/shinkoku/yoshiki/01/shinkokusho/pdf/r07/03.pdf",  # 申告書第四表【令和７年分以降用】
        "sonshitsu_tebiki_r07": NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/pdf/003.pdf",          # 令和７年分 確定申告の手引き（損失申告用）
        "shinsei_aoiro": NTA + "/taxes/tetsuzuki/shinsei/annai/shinkoku/pdf/h28/10.pdf",              # 所得税の青色申告承認申請書
        "shinsei_aoiro_ki": NTA + "/taxes/tetsuzuki/shinsei/annai/shinkoku/pdf/h28/10-ki.pdf",        # 同 記載要領
    },
    # 4回目：手続の案内から見つけた様式（PDF）
    "forms2": {
        "ta_2250": TA + "2250.htm",                                 # 損益通算（タックスアンサー）
        "todoke_65man": NTA + "/taxes/tetsuzuki/shinsei/annai/shinkoku/pdf/r03/01.pdf",                  # 65万円の青色申告特別控除・過少申告加算税の特例の適用を受ける旨の届出書
        "todoke_65man_ki": NTA + "/taxes/tetsuzuki/shinsei/annai/shinkoku/pdf/r03/01-ki.pdf",            # 同 記載要領
        "shinsei_aoiro_genkin": NTA + "/taxes/tetsuzuki/shinsei/annai/shinkoku/pdf/h28/11.pdf",          # 青色申告承認申請書（兼）現金主義の所得計算による旨の届出書
        "todoke_senju": NTA + "/taxes/tetsuzuki/shinsei/annai/shinkoku/pdf/h28/13_14.pdf",               # 青色事業専従者給与に関する届出・変更届出書
        "todoke_senju_ki": NTA + "/taxes/tetsuzuki/shinsei/annai/shinkoku/pdf/h28/13_14-ki.pdf",         # 同 記載要領
        "todoke_yame": NTA + "/taxes/tetsuzuki/shinsei/annai/shinkoku/pdf/h28/12.pdf",                   # 所得税の青色申告の取りやめ届出書
        "todoke_yame_ki": NTA + "/taxes/tetsuzuki/shinsei/annai/shinkoku/pdf/h28/12-ki.pdf",             # 同 記載要領
        "kanpu_kurimodoshi": NTA + "/taxes/tetsuzuki/shinsei/annai/shinkoku/pdf/03_r05.pdf",             # 純損失の金額の繰戻しによる所得税の還付請求書【令和５年分以降用】
        "kanpu_kurimodoshi_ki": NTA + "/taxes/tetsuzuki/shinsei/annai/shinkoku/pdf/03_r05-ki.pdf",       # 同 記載要領
        "todoke_genkin": NTA + "/taxes/tetsuzuki/shinsei/annai/shinkoku/pdf/h28/15.pdf",                 # 現金主義による所得計算の特例を受けることの届出書
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
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_aoiro_nta_{name}"
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
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_aoiro_nta_robots"
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

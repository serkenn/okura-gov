"""R3X shibo-shukkoku: 国税庁の通達・タックスアンサー・手続の案内・様式のうち、年の中途の死亡・出国の申告（準確定申告）と
損失の繰越・繰戻しに関係するページを取得し、本文のテキストとリンクを取り出す。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_shibo-shukkoku_nta.py --robots
      robots.txt を取得し、SETS のすべての URL が User-Agent okura-gov-research/0.1 で許されるかを判定（robots_check.json）
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_shibo-shukkoku_nta.py <set> [<set> ...]
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_shibo-shukkoku_nta.py --list

- HTML 取得とテキスト化は scripts/R2X_aoiro_nta.py を写した（import はしない）。
- 取得したもの（HTML・PDF）は信頼できないデータとして、取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_R3X_shibo-shukkoku_nta_<set>/ に置く。その中でインタプリタやツールは実行しない。
- HTML から取り出したテキストとリンクは scripts/results/R3X_shibo-shukkoku_nta/<set>/<id>.txt / <id>.links.json に書く。
  画像で表示される文字は img の alt を〔alt:...〕の形で残す。
- PDF はテキスト化しない（ダウンロード先のパスと SHA-256 だけを記録し、人が Read ツールの pages 指定で読む）。
- 取得記録（ステータス、Content-Type、Last-Modified、SHA-256、バイト数）は scripts/results/R3X_shibo-shukkoku_nta/<set>/fetch_log.json。
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
OUT = ROOT / "scripts" / "results" / "R3X_shibo-shukkoku_nta"

NTA = "https://www.nta.go.jp"
TA = NTA + "/taxes/shiraberu/taxanswer/shotoku/"
TACODE = NTA + "/taxes/shiraberu/taxanswer/code/"
KIHON = NTA + "/law/tsutatsu/kihon/shotoku/"
ANNAI = NTA + "/taxes/tetsuzuki/shinsei/annai/shinkoku/annai/"
SETS = {
    # 1回目：索引（タックスアンサーの分野別、手続の目次、令和7年分の様式の一覧）
    "index": {
        "ta_bunya_kakuteishinkoku": TACODE + "bunya-kakuteishinkoku.htm",
        "ta_bunya_souzoku_zoyo": TACODE + "bunya-souzoku-zoyo.htm",
        "ta_bunya_saigai": TACODE + "bunya-saigai.htm",
        "tetsuzuki_mokuji": NTA + "/taxes/tetsuzuki/shinsei/annai/shinkoku/mokuji.htm",
        "yoshiki_r07": NTA + "/taxes/shiraberu/shinkoku/syotoku/r07.htm",
    },
    # 2回目：通達とタックスアンサー（既知の URL）
    "pages": {
        "ta_2022": TA + "2022.htm",          # 納税者が死亡したときの確定申告（準確定申告）
        "ta_1110": TA + "1110.htm",          # 災害や盗難などで資産に損害を受けたとき（雑損控除）
        "kihon_19_01": KIHON + "19/01.htm",  # 法第120条・第121条関係
        "kihon_19_02": KIHON + "19/02.htm",  # 法第122条〜第142条関係（124・125、127、140・141、142）
        "kihon_16_06": KIHON + "16/06.htm",  # 法第79条〜第85条関係（85−1、83から84の2−1）
        "kihon_15_01": KIHON + "15/01.htm",  # 法第70条〜第71条の2関係（雑損失の繰越控除）
        "kihon_16_01": KIHON + "16/01.htm",  # 法第72条・第73条関係（雑損控除・医療費控除）
        "kihon_16_02": KIHON + "16/02.htm",  # 法第74条・第75条関係（社会保険料控除）
        "kihon_01_01": KIHON + "01/01.htm",  # 居住者、非永住者及び非居住者（法第2条第3〜5号関係）
        "kihon_01_08": KIHON + "01/08.htm",  # 法第3条関係
        "annai_07": ANNAI + "07.htm",        # 所得税・消費税の納税管理人の選任届出又は解任届出手続
    },
    # 3回目：index・pages のリンクから選んだページ
    "pages2": {
        "ta_1923": TA + "1923.htm",                                   # 海外勤務と納税管理人の選任又は解任
        "shitsugi_07_15": NTA + "/law/shitsugi/shotoku/07/15.htm",    # 民法上の相続人が不存在の場合の準確定申告の手続
        "annai_1557_2": ANNAI + "1557_2.htm",                         # 申告書・申告書付表と税額計算書等 一覧（準確定申告書の付表）
        "jyunkaku_index": NTA + "/taxes/shiraberu/shinkoku/jyunkaku/index.htm",  # 準確定申告の e-Tax 対応（TA2022 の「こちら」）
        "annai_23200032": ANNAI + "23200032.htm",                     # 繰越雑損失がある場合の源泉所得税の徴収猶予承認申請手続
        "ta_bunya_nemmatsuchosei": TACODE + "bunya-nemmatsuchosei.htm",  # 年末調整（出国の年末調整のタックスアンサーを探す）
    },
    # 5回目（4回目の後に足した）：出国の年の精算、基礎控除の引上げの特設ページ（令和8年・令和7年。令和7年の URL は
    # 令和8年の URL の形から推測したもの。404 ならそのまま記録する）
    "pages3": {
        "ta_1920": TA + "1920.htm",                                    # 海外勤務と所得税額の精算
        "gensen_2026kiso": NTA + "/users/gensen/2026kiso/index.htm",   # 令和8年度税制改正（基礎控除の引上げ等）の特設ページ
        "gensen_2025kiso": NTA + "/users/gensen/2025kiso/index.htm",   # 令和7年度税制改正（基礎控除の見直し等）の特設ページ（URL は推測）
    },
    # 4回目：様式・Q&A（PDF）
    "forms": {
        "fuhyo_shibou": NTA + "/taxes/shiraberu/shinkoku/yoshiki/01/fuhyo/f01-yoshiki.pdf",  # 死亡した者の…確定申告書付表（兼相続人の代表者指定届出書）
        "ininjo_junkaku": NTA + "/taxes/shiraberu/shinkoku/yoshiki/01/fuhyo/f01-3.pdf",     # 委任状（準確定申告書用）
        "r8_kiso_qa": NTA + "/users/gensen/2026kiso/pdf/0026005-024.pdf",                    # 令和8年度税制改正（所得税の基礎控除の引上げ等関係）Q&A（令和8年5月）
    },
    # 6回目：pages3 のリンクから（令和7年分の準確定申告の扱いを確かめるため）
    "forms2": {
        "r7_kiso_qa": NTA + "/publication/pamph/gensen/0025005-051.pdf",  # 令和７年度税制改正（基礎控除の見直し等関係）Q&A（令和７年５月）
    },
    # 7回目（中断の後に再開して足した）：付表の記載要領（期限の数え方・按分の端数の記載を探すため。
    # URL は pages2/annai_1557_2.links.json の「記載要領（PDF/2,366KB）」から）
    "forms3": {
        "fuhyo_kisaiyoryo": NTA + "/taxes/shiraberu/shinkoku/yoshiki/01/fuhyo/f01.pdf",
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
    dl = ROOT / ".work" / "downloads" / f"{ts}_R3X_shibo-shukkoku_nta_{name}"
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
    dl = ROOT / ".work" / "downloads" / f"{ts}_R3X_shibo-shukkoku_nta_robots"
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

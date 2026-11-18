"""R2X genka 独立検証（反証役）: 減価償却と損益通算（genka）の4つの文書に書かれた条番号・文言・数値・版・URL を、
担当のスクリプト（R2X_genka_laws.py / R2X_genka_nta.py / R2X_genka_checks.py）とは別に書いた取得・解析・計算で確かめる。

実行（Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_genka_verify.py egov
      e-Gov 法令API v2 で law_id を引き直し（/laws?law_title=）、各時点（asof）の本文（/law_data）を取得して、
      対象の条を条→項→号→イロハ の構造のまま JSON に取り出す。改正法令の附則（AmendLawNum で選ぶ）と、
      耐用年数省令の別表（セルの rowspan/colspan つき）も取り出す。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_genka_verify.py egov2
      所得税法 第28条・第33条・別表第五（asof 2025-12-31・2026-12-31）と、所得税法施行令 asof 2026-12-31 の
      全附則のうち「第百九十八条」「損益通算」を含む条を取り出す。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_genka_verify.py revs
      /law_revisions で所得税法施行令・耐用年数省令・措置法・措置法施行令の改正履歴を取り、
      所得税法施行令の 2025-12-01〜2026-12-01 施行の改正ごとの版（/law_data/<law_revision_id>）の第198条を取り出す。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_genka_verify.py nta
      先に https://www.nta.go.jp/robots.txt を取得して全 URL が許されるかを判定し（許されないものがあれば中止）、
      国税庁のページ（HTML はテキスト化、PDF は保存とハッシュだけ）を取得する。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_genka_verify.py nta2
      robots.txt の判定のあとで、決算の手引き（kichou09.pdf）を案内するページ2件を取得する（リンクの文字を見るため）。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_genka_verify.py check
      ネットワークを使わず、上の出力だけから、文書の主張（LAW・SAME・REVS・NQ・NTA_META・BEPPYO）を突き合わせ、
      計算例を担当の関数を使わずに書き直した実装で再計算する。PDF の中身は Read ツールで目視した（このスクリプトでは読まない）。

- API の使い方は scripts/R1_egov_articles.py・scripts/IMPL_jigyo_verify.py を読んで写した（import はしない）。
  本文のテキスト化・別表の解析・計算は、担当のスクリプトを使わずに書き直した。
- ダウンロードしたものは信頼できないデータ。取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_R2X_genka_verify_<mode>/ に置き、その中でインタプリタやツールは実行しない。
- 結果は scripts/results/R2X_genka_verify/ に書く。
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。送るのは法令ID・日付・公開ページの URL だけ。
"""
import calendar
import datetime as dt
import hashlib
import html.parser
import json
import math
import pathlib
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from fractions import Fraction as F

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "results" / "R2X_genka_verify"
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
TODAY = "2026-11-09"
WAIT = 1.5

# 略称: (法令名, 文書が書いた law_id, [asof...], [取り出す本則の条（Num 属性）], [附則を取り出す AmendLawNum の正規表現], 別表を取るか)
R8_LAW12 = r"令和八年三月三一日法律第一二号"
R8_SEIREI93 = r"令和八年.*政令第九三号"
R8_SEIREI98 = r"令和八年.*政令第九八号"
LAWS = {
    "shotoku": ("所得税法", "340AC0000000033", ["2025-12-31", "2026-12-31", "2027-01-01", "2030-12-31"],
                ["2", "22", "33", "35", "37", "38", "45", "49", "51", "69", "70", "70_2", "123", "140"], [R8_LAW12], False),
    "shotoku-rei": ("所得税法施行令", "340CO0000000096", ["2025-12-31", "2026-12-31", "2030-12-31"],
                    ["6", "7_2", "81", "85", "96", "120", "120_2", "123", "124", "125", "126", "129", "131", "132", "134",
                     "135", "138", "139", "142", "198", "199", "200", "201", "202"], [R8_SEIREI93], False),
    "shotoku-ki": ("所得税法施行規則", "340M50000040011", ["2025-12-31", "2026-12-31", "2030-12-31"], ["34_2", "34_3"], [], False),
    "sochi": ("租税特別措置法", "332AC0000000026", ["2025-12-31", "2026-03-31", "2026-04-01", "2026-12-31", "2027-01-01", "2030-12-31"],
              ["10", "28_2", "29_4"], [R8_LAW12], False),
    "sochi-rei": ("租税特別措置法施行令", "332CO0000000043", ["2025-12-31", "2026-03-31", "2026-04-01", "2026-12-31", "2030-12-31"],
                  ["5_3", "18_5"], [R8_SEIREI98], False),
    "sochi-ki": ("租税特別措置法施行規則", "332M50000040015", ["2025-12-31", "2026-04-01", "2026-12-31", "2030-12-31"], [], [], False),
    "taiyo": ("減価償却資産の耐用年数等に関する省令", "340M50000040015", ["2025-12-31", "2026-12-31", "2030-12-31"],
              ["1", "2", "3", "4", "5", "6"], [], True),
    "chiho": ("地方税法", "325AC0000000226", ["2025-12-31", "2026-12-31"], ["313"], [], False),
}


# ---------------------------------------------------------------- 共通
def http_get(url, accept=None):
    h = {"User-Agent": UA}
    if accept:
        h["Accept"] = accept
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            st, body, hd = r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        st, body, hd = e.code, e.read(), dict(e.headers or {})
    time.sleep(WAIT)
    return st, body, hd


def new_dl(mode):
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_genka_verify_{mode}"
    dl.mkdir(parents=True, exist_ok=False)
    return ts, dl


def rel(p):
    return str(pathlib.Path(p).relative_to(ROOT)).replace("\\", "/")


def norm(s):
    """突合せ用の正規化：NFKC（全角数字・括弧を半角に）にして、空白（全角空白を含む）と改行をすべて除く。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or ""))


# ---------------------------------------------------------------- e-Gov の構造
def flat(n):
    """ノード以下の文字列をつなぐ。ルビの読み（Rt）は落とし、Column どうしの間には全角空白を入れる。"""
    if isinstance(n, str):
        return n
    if n.get("tag") == "Rt":
        return ""
    ch = n.get("children", [])
    if any(isinstance(c, dict) and c.get("tag") == "Column" for c in ch):
        return "　".join(flat(c) for c in ch if not (isinstance(c, str) and not c.strip()))
    return "".join(flat(c) for c in ch)


def kids(n, tag=None):
    return [c for c in n.get("children", []) if isinstance(c, dict) and (tag is None or c.get("tag") == tag)]


SUBTAGS = ("Item",) + tuple(f"Subitem{i}" for i in range(1, 11))


def node(n):
    """Paragraph / Item / SubitemN を {tag, num, head, text(自分の文), full(配下すべて), ch:{Num: ...}} にする。"""
    head = "".join(flat(c) for c in kids(n) if c.get("tag", "").endswith(("Num", "Title")) and c.get("tag") != "ParagraphCaption")
    own = "　".join(flat(c) for c in kids(n) if c.get("tag", "").endswith("Sentence"))
    cap = "".join(flat(c) for c in kids(n, "ParagraphCaption"))
    ch = {}
    for c in kids(n):
        if c.get("tag") in SUBTAGS:
            ch[c.get("attr", {}).get("Num", str(len(ch) + 1))] = node(c)
    return {"tag": n.get("tag"), "num": n.get("attr", {}).get("Num"), "head": head, "caption": cap, "text": own,
            "full": flat(n), "ch": ch}


def article(a):
    return {"num": a.get("attr", {}).get("Num"), "caption": "".join(flat(c) for c in kids(a, "ArticleCaption")),
            "title": "".join(flat(c) for c in kids(a, "ArticleTitle")), "full": flat(a),
            "paras": {p.get("attr", {}).get("Num"): node(p) for p in kids(a, "Paragraph")}}


def walk(n, fn, path=()):
    if isinstance(n, dict):
        fn(n, path)
        for c in n.get("children", []):
            walk(c, fn, path + (n.get("tag"),))


def appdx_tables(root):
    """本則の別表（AppdxTable）を {title, rows:[[{text,rowspan,colspan}...]...]} にする。"""
    out = []

    def f(n, path):
        if n.get("tag") == "AppdxTable" and "SupplProvision" not in path:
            title = "".join(flat(c) for c in kids(n, "AppdxTableTitle"))
            rows = []

            def g(x, p):
                if x.get("tag") in ("TableRow", "TableHeaderRow"):
                    cells = []
                    for col in kids(x):
                        a = col.get("attr") or {}
                        cells.append({"text": re.sub(r"\s+", " ", flat(col)).strip(),
                                      "rowspan": int(a.get("rowspan", 1)), "colspan": int(a.get("colspan", 1))})
                    rows.append(cells)
            walk(n, g)
            out.append({"title": title, "rows": rows})
    walk(root, f)
    return out


def parse_law(d, nums, amend_res):
    root = d["law_full_text"]
    main, captions, suppl = {}, [], {}

    def coll(n, path):
        if n.get("tag") == "Article" and "SupplProvision" not in path:
            num = n.get("attr", {}).get("Num")
            captions.append([num, "".join(flat(c) for c in kids(n, "ArticleCaption"))])
            if num in nums:
                main[num] = article(n)
        if n.get("tag") == "SupplProvision":
            an = n.get("attr", {}).get("AmendLawNum") or ""
            if any(re.search(r, an) for r in amend_res):
                arts = {}
                walk(n, lambda x, p: arts.__setitem__(x["attr"].get("Num"), article(x)) if x.get("tag") == "Article" else None)
                suppl.setdefault(an, []).append(arts)
    walk(root, coll)
    return main, captions, suppl


def rev_info(d):
    ri = d.get("revision_info") or {}
    return {k: ri.get(k) for k in ("law_revision_id", "amendment_law_num", "amendment_law_title",
                                   "amendment_enforcement_date", "current_revision_status", "updated")}


def mode_egov():
    ts, dl = new_dl("egov")
    (OUT / "egov").mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": rel(dl), "lookups": {}, "fetches": []}
    for i, (short, (title, law_id, asofs, nums, amend_res, want_appdx)) in enumerate(LAWS.items(), 1):
        q = urllib.parse.urlencode({"law_title": title, "response_format": "json", "asof": TODAY})
        url = f"{API}/laws?{q}"
        st, body, _ = http_get(url, "application/json")
        (dl / f"{i:02d}_laws_{short}.json").write_bytes(body)
        found = []
        for law in json.loads(body).get("laws", []):
            rv = law.get("current_revision_info") or law.get("revision_info") or {}
            if rv.get("law_title") == title:
                found.append({"law_id": law["law_info"]["law_id"], "law_num": law["law_info"].get("law_num")})
        log["lookups"][short] = {"title": title, "url": url, "status": st, "exact_title_matches": found, "claimed_law_id": law_id,
                                 "claimed_matches": any(x["law_id"] == law_id for x in found)}
        print("lookup", short, found, flush=True)
        for asof in asofs:
            furl = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
            st, body, _ = http_get(furl, "application/json")
            raw = dl / f"{short}_{asof}.json"
            raw.write_bytes(body)
            if st != 200:
                log["fetches"].append({"short": short, "asof": asof, "url": furl, "status": st})
                print("ERR", short, asof, st, flush=True)
                continue
            d = json.loads(body)
            main, captions, suppl = parse_law(d, nums, amend_res)
            rec = {"short": short, "title": title, "law_id": law_id, "asof": asof, "url": furl, "fetched_at": ts, "raw": rel(raw),
                   "sha256": hashlib.sha256(body).hexdigest(), "revision_info": rev_info(d),
                   "missing": [x for x in nums if x not in main], "suppl_amend_nums": sorted(suppl)}
            data = {**rec, "captions": captions, "main": main, "suppl": suppl}
            if want_appdx:
                data["appdx"] = appdx_tables(d["law_full_text"])
            (OUT / "egov" / f"{short}_{asof}.json").write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
            log["fetches"].append(rec)
            print("ok", short, asof, rec["revision_info"]["law_revision_id"], rec["revision_info"]["current_revision_status"],
                  rec["missing"], rec["suppl_amend_nums"], flush=True)
    (OUT / "egov_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


def mode_revs():
    ts, dl = new_dl("revs")
    out = {"run_at": ts, "download_dir": rel(dl), "revisions": {}, "rei198_by_revision": []}
    for short in ("shotoku-rei", "taiyo", "sochi", "sochi-rei", "shotoku"):
        law_id = LAWS[short][1]
        url = f"{API}/law_revisions/{law_id}?response_format=json"
        st, body, _ = http_get(url, "application/json")
        (dl / f"revisions_{short}.json").write_bytes(body)
        revs = json.loads(body).get("revisions", []) if st == 200 else []
        out["revisions"][short] = {"url": url, "status": st, "count": len(revs),
                                   "in_2025_2030": [{k: r.get(k) for k in ("law_revision_id", "amendment_enforcement_date", "amendment_law_num",
                                                                          "amendment_law_title", "current_revision_status", "updated")}
                                                    for r in revs if "2025-01-01" <= (r.get("amendment_enforcement_date") or "") <= "2030-12-31"]}
        print("revs", short, st, len(revs), flush=True)
    # 所令198：2025-12-01〜2026-12-01 施行の改正ごとの版
    for r in sorted(out["revisions"]["shotoku-rei"]["in_2025_2030"], key=lambda r: (r["amendment_enforcement_date"], r["law_revision_id"])):
        if not ("2025-12-01" <= r["amendment_enforcement_date"] <= "2026-12-01"):
            continue
        rid = r["law_revision_id"]
        url = f"{API}/law_data/{rid}?response_format=json"
        st, body, _ = http_get(url, "application/json")
        (dl / f"{rid}.json").write_bytes(body)
        rec = {"law_revision_id": rid, "url": url, "status": st, "enforcement": r["amendment_enforcement_date"],
               "amend": r["amendment_law_num"], "rev_status": r["current_revision_status"]}
        if st == 200:
            d = json.loads(body)
            main, _, suppl = parse_law(d, ["198"], [R8_SEIREI93])
            a = main.get("198")
            rec["198_full"] = a["full"] if a else None
            rec["198_conj_item3"] = re.findall(r"譲渡所得の金額(及び|又は)一時所得の金額（前号", a["full"]) if a else None
            rec["198_conj_all"] = re.findall(r"譲渡所得の金額(及び|又は)一時所得の金額", a["full"]) if a else None
            rec["suppl_93"] = {an: [{k: v["full"] for k, v in arts.items()} for arts in lst] for an, lst in suppl.items()}
        out["rei198_by_revision"].append(rec)
        print("rev198", rid, st, rec.get("198_conj_all"), flush=True)
    (OUT / "revs.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


def mode_egov2():
    """追加の取得：所得税法 第28条・第33条・別表第五（推測 I7 の給与所得の前提、公開資料 §5.2 の所法33）と、
    所得税法施行令 asof 2026-12-31 の全附則のうち「第百九十八条」を含む条（実測 §6 の未確認点）。"""
    ts, dl = new_dl("egov2")
    (OUT / "egov2").mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": rel(dl), "fetches": []}
    for short, asof in (("shotoku", "2025-12-31"), ("shotoku", "2026-12-31")):
        law_id = LAWS[short][1]
        furl = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
        st, body, _ = http_get(furl, "application/json")
        raw = dl / f"{short}_{asof}.json"
        raw.write_bytes(body)
        d = json.loads(body)
        main, _, _ = parse_law(d, ["28", "33"], [])
        tabs = [t for t in appdx_tables(d["law_full_text"]) if t["title"].startswith("別表第五")]
        rec = {"short": short, "asof": asof, "url": furl, "status": st, "raw": rel(raw), "sha256": hashlib.sha256(body).hexdigest(),
               "revision_info": rev_info(d)}
        (OUT / "egov2" / f"{short}_{asof}.json").write_text(json.dumps({**rec, "main": main, "appdx": tabs}, ensure_ascii=False, indent=0),
                                                         encoding="utf-8")
        log["fetches"].append(rec)
        print("ok", short, asof, rec["revision_info"]["law_revision_id"], flush=True)
    short, asof = "shotoku-rei", "2026-12-31"
    law_id = LAWS[short][1]
    furl = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
    st, body, _ = http_get(furl, "application/json")
    raw = dl / f"{short}_{asof}.json"
    raw.write_bytes(body)
    d = json.loads(body)
    hits = []

    def f(n, path):
        if n.get("tag") == "SupplProvision":
            an = n.get("attr", {}).get("AmendLawNum") or "(原始附則)"
            walk(n, lambda x, p: hits.append({"amend": an, "num": x["attr"].get("Num"), "full": flat(x)})
                 if x.get("tag") == "Article" and ("第百九十八条" in flat(x) or "損益通算" in flat(x)) else None)
    walk(d["law_full_text"], f)
    rec = {"short": short, "asof": asof, "url": furl, "status": st, "raw": rel(raw), "sha256": hashlib.sha256(body).hexdigest(),
           "revision_info": rev_info(d), "suppl_articles_with_198_or_sontsu": hits}
    (OUT / "egov2" / f"{short}_{asof}_suppl198.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    log["fetches"].append({k: v for k, v in rec.items() if k != "suppl_articles_with_198_or_sontsu"})
    print("ok suppl198", [(h["amend"], h["num"]) for h in hits], flush=True)
    (OUT / "egov2_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- 国税庁
NTA = "https://www.nta.go.jp"
TA = NTA + "/taxes/shiraberu/taxanswer/shotoku/"
KIHON = NTA + "/law/tsutatsu/kihon/shotoku/"
PAGES = {
    "ta_2100": TA + "2100.htm", "ta_2106": TA + "2106.htm", "ta_2250": TA + "2250.htm", "ta_2109": TA + "2109.htm",
    "kihon_zenbun": KIHON + "00/01.htm",
    "kihon_01_04": KIHON + "01/04.htm", "kihon_08_05": KIHON + "08/05.htm", "kihon_08_06": KIHON + "08/06.htm",
    "kihon_08_08": KIHON + "08/08.htm", "kihon_08_10": KIHON + "08/10.htm", "kihon_08_12": KIHON + "08/12.htm",
    "kihon_08_13": KIHON + "08/13.htm", "kihon_09_01": KIHON + "09/01.htm", "kihon_15_01": KIHON + "15/01.htm",
    "kihon_04_07": KIHON + "04/07.htm",
    "sochitsu_28_02": NTA + "/law/tsutatsu/kobetsu/shotoku/sochiho/801226/sinkoku/57/28/02.htm",
    "shitsugi_04_17": NTA + "/law/shitsugi/shotoku/04/17.htm", "shitsugi_04_14": NTA + "/law/shitsugi/shotoku/04/14.htm",
    "tetsuzuki_18": NTA + "/taxes/tetsuzuki/shinsei/annai/shinkoku/annai/18.htm",
    "pdf_037": NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/pdf/037.pdf",
    "pdf_003": NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/pdf/003.pdf",
    "pdf_034": NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/pdf/034.pdf",
    "pdf_kichou09": NTA + "/taxes/shiraberu/shinkoku/kojin_jigyo/kichou09.pdf",
    "pdf_2100_01": TA + "pdf/2100_01.pdf", "pdf_2100_02": TA + "pdf/2100_02.pdf",
}


# 追加の取得：決算の手引き（kichou09.pdf）が何年分のものとして案内されているかを、案内のページのリンクの文字で見る
PAGES2 = {
    "kojin_jigyo_index": NTA + "/taxes/shiraberu/shinkoku/kojin_jigyo/index.htm",
    "yoshiki_r07": NTA + "/taxes/shiraberu/shinkoku/syotoku/r07.htm",
}


class TextOf(html.parser.HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "dt", "dd", "table", "td", "th", "caption"}

    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base, self.out, self.skip, self.links, self.cur = base, [], 0, [], None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        if tag in self.BLOCK:
            self.out.append("\n")
        if tag == "img" and a.get("alt") and not self.skip:
            self.out.append(f"〔alt:{a['alt']}〕")
        if tag == "a" and a.get("href"):
            self.cur = {"href": urllib.parse.urljoin(self.base, a["href"]), "text": ""}

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.skip:
            self.skip -= 1
        if tag in self.BLOCK:
            self.out.append("\n")
        if tag == "a" and self.cur is not None:
            self.cur["text"] = re.sub(r"\s+", " ", self.cur["text"]).strip()
            self.links.append(self.cur)
            self.cur = None

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)
            if self.cur is not None:
                self.cur["text"] += data

    def text(self):
        t = "".join(self.out).replace("\r", "")
        t = re.sub(r"[ \t\u3000]*\n[ \t\u3000]*", "\n", t)
        return re.sub(r"\n{2,}", "\n", t).strip()


def decode_html(body, ctype):
    m = re.search(rb'charset=["\']?([A-Za-z0-9_\-]+)', body[:4096])
    enc = m.group(1).decode().lower() if m else None
    if not enc and ctype and "charset=" in ctype:
        enc = ctype.split("charset=")[-1].strip().lower()
    for e in [enc, "utf-8", "cp932"]:
        if not e:
            continue
        e = "cp932" if e in ("shift_jis", "sjis", "x-sjis", "shift-jis") else e
        try:
            return body.decode(e), e
        except (UnicodeDecodeError, LookupError):
            continue
    return body.decode("utf-8", "replace"), "utf-8(replace)"


def mode_nta(pages=None, name="nta"):
    PAGES_ = pages or PAGES
    ts, dl = new_dl(name)
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    st, body, _ = http_get(NTA + "/robots.txt")
    (dl / "robots.txt").write_bytes(body)
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(body.decode("utf-8", "replace").splitlines())
    robots = {"fetched_at": ts, "status": st, "sha256": hashlib.sha256(body).hexdigest(), "saved": rel(dl / "robots.txt"),
              "disallow": [x.strip() for x in body.decode("utf-8", "replace").splitlines() if x.strip().lower().startswith("disallow")],
              "allowed": {k: rp.can_fetch(UA, u) for k, u in PAGES_.items()}}
    (OUT / f"{name}_robots.json").write_text(json.dumps(robots, ensure_ascii=False, indent=1), encoding="utf-8")
    if not all(robots["allowed"].values()):
        print("robots.txt で許されない URL がある。中止", [k for k, v in robots["allowed"].items() if not v])
        return
    log = {"run_at": ts, "download_dir": rel(dl), "items": []}
    for key, url in PAGES_.items():
        try:
            st, body, hd = http_get(url)
        except Exception as e:  # noqa: BLE001
            log["items"].append({"id": key, "url": url, "error": repr(e)})
            print("ERR", key, repr(e), flush=True)
            continue
        ctype = hd.get("Content-Type", "")
        is_pdf = url.lower().endswith(".pdf") or "pdf" in ctype.lower()
        fn = dl / (key + (".pdf" if is_pdf else ".htm"))
        fn.write_bytes(body)
        it = {"id": key, "url": url, "status": st, "content_type": ctype, "last_modified": hd.get("Last-Modified"),
              "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(), "saved": rel(fn)}
        if not is_pdf and st == 200:
            txt, enc = decode_html(body, ctype)
            p = TextOf(url)
            p.feed(txt)
            it["encoding"] = enc
            tm = re.search(r"<title>(.*?)</title>", txt, re.S)
            it["title"] = re.sub(r"\s+", " ", tm.group(1)).strip() if tm else None
            (out / f"{key}.txt").write_text(p.text() + "\n", encoding="utf-8")
            (out / f"{key}.links.json").write_text(json.dumps(p.links, ensure_ascii=False, indent=0), encoding="utf-8")
        if is_pdf and st == 200:
            # バイト列を読むだけ（PDF を解釈・実行しない）。暗号化の辞書と ToUnicode の有無を数える。
            it["pdf_has_Encrypt"] = b"/Encrypt" in body
            it["pdf_ToUnicode_count"] = body.count(b"/ToUnicode")
            it["pdf_head"] = body[:8].decode("latin-1")
        log["items"].append(it)
        print("ok", key, st, len(body), hd.get("Last-Modified"), flush=True)
    (OUT / f"{name}_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- check：文書の主張の突合せ（ネットワークなし）
R7, R8, R26A, R26B, R27, R30 = "2025-12-31", "2026-12-31", "2026-03-31", "2026-04-01", "2027-01-01", "2030-12-31"
_cache = {}


def eg(short, asof, sub="egov"):
    k = (short, asof, sub)
    if k not in _cache:
        _cache[k] = json.loads((OUT / sub / f"{short}_{asof}.json").read_text(encoding="utf-8"))
    return _cache[k]


def node_at(short, asof, path, sub="egov"):
    """path: '条/項/号/イ/(1)'。'条/cap' は見出し。'S:<AmendLawNum の正規表現>:条/項/…' は改正法令の附則。"""
    d = eg(short, asof, sub)
    if path.startswith("S:"):
        _, an_re, rest = path.split(":", 2)
        parts = rest.split("/")
        a = None
        for an, lst in d["suppl"].items():
            if re.search(an_re, an):
                for arts in lst:
                    if parts[0] in arts:
                        a = arts[parts[0]]
        if a is None:
            return None
    else:
        parts = path.split("/")
        a = d["main"].get(parts[0])
        if a is None:
            return None
    if len(parts) == 1:
        return a["full"]
    if parts[1] == "cap":
        return a["caption"]
    n = a["paras"].get(parts[1])
    for p in parts[2:]:
        if n is None:
            return None
        n = n["ch"].get(p)
    return None if n is None else n["full"]


def in_order(text, frags):
    """断片が text の中に順に現れるか（正規化して比べる）。現れなかった断片の list を返す。"""
    t, pos, miss = norm(text), 0, []
    for f in frags:
        i = t.find(norm(f), pos)
        if i < 0:
            miss.append(f)
        else:
            pos = i + len(norm(f))
    return miss


# (ID, 文書と節, 略称, [asof], path, [順に現れるべき断片], [否定なら True])
LAW = [
    # 公開資料 §1
    ("L01", "PS§1/H1 所法2①十九", "shotoku", [R7, R8], "2/1/19", ["減価償却資産　不動産所得若しくは雑所得の基因となり、又は不動産所得、事業所得、山林所得若しくは雑所得を生ずべき業務の用に供される建物、構築物、機械及び装置、船舶、車両及び運搬具、工具、器具及び備品、鉱業権その他の資産で償却をすべきものとして政令で定めるものをいう。"]),
    ("L02", "PS§1 所令6 見出し", "shotoku-rei", [R7, R8], "6/cap", ["減価償却資産の範囲"]),
    ("L03", "PS§1 所令6①柱書", "shotoku-rei", [R7, R8], "6/1", ["棚卸資産、有価証券及び繰延資産以外の資産のうち次に掲げるもの（時の経過によりその価値の減少しないものを除く。）"]),
    ("L04", "PS§1 所令6①一〜九", "shotoku-rei", [R7, R8], "6/1", ["一建物及びその附属設備", "二構築物", "三機械及び装置", "四船舶", "五航空機", "六車両及び運搬具", "七工具、器具及び備品", "八次に掲げる無形固定資産", "九次に掲げる生物"]),
    ("L05", "PS§1 所令6①八ヘ・リ・ヌ・カ", "shotoku-rei", [R7, R8], "6/1/8", ["ヘ特許権", "リ商標権", "ヌソフトウエア", "カ営業権"]),
    # §2.1
    ("L06", "PS§2.1 所法49①", "shotoku", [R7, R8], "49/1", ["居住者のその年十二月三十一日において有する減価償却資産につきその償却費として第三十七条（必要経費）の規定によりその者の不動産所得の金額、事業所得の金額、山林所得の金額又は雑所得の金額の計算上必要経費に算入する金額は、その取得をした日及びその種類の区分に応じ、償却費が毎年同一となる償却の方法、償却費が毎年一定の割合で逓減する償却の方法その他の政令で定める償却の方法の中からその者が当該資産について選定した償却の方法（償却の方法を選定しなかつた場合には、償却の方法のうち政令で定める方法）に基づき政令で定めるところにより計算した金額とする。"]),
    ("L07", "PS§2.1 所令120の2①柱書", "shotoku-rei", [R7, R8], "120_2/1", ["平成十九年四月一日以後に取得された減価償却資産"]),
    ("L08", "PS§2.1 所令120の2①一イ", "shotoku-rei", [R7, R8], "120_2/1/1/1", ["平成二十八年三月三十一日以前に取得された減価償却資産（建物を除く。）", "定額法", "定率法"]),
    ("L09", "PS§2.1 所令120の2①一ロ", "shotoku-rei", [R7, R8], "120_2/1/1/2", ["イに掲げる減価償却資産以外の減価償却資産　定額法"]),
    ("L10", "PS§2.1 定額法の定義", "shotoku-rei", [R7, R8], "120_2/1/1/1/1", ["当該減価償却資産の取得価額にその償却費が毎年同一となるように当該資産の耐用年数に応じた償却率（", "「定額法償却率」という。）を乗じて計算した金額を各年分の償却費として償却する方法"]),
    ("L11", "PS§2.1 所令120の2①二", "shotoku-rei", [R7, R8], "120_2/1/2", ["第六条第三号から第七号までに掲げる減価償却資産（次号及び第六号に掲げるものを除く。）", "イ定額法", "ロ定率法"]),
    ("L12", "PS§2.1 所令120の2①四", "shotoku-rei", [R7, R8], "120_2/1/4", ["第六条第八号に掲げる無形固定資産（次号及び第六号に掲げるものを除く。）及び同条第九号に掲げる生物　定額法"]),
    ("L13", "PS§2.1 所令125 見出し", "shotoku-rei", [R7, R8, R30], "125/cap", ["減価償却資産の法定償却方法"]),
    ("L14", "PS§2.1/§9 所令125二イ", "shotoku-rei", [R7, R8, R30], "125/1/2/1", ["第百二十条の二第一項第一号イ及び第二号（減価償却資産の償却の方法）に掲げる減価償却資産　定額法"]),
    ("L15", "PS§2.1 所令123②", "shotoku-rei", [R7, R8], "123/2", ["当該各号に定める日の属する年分の所得税に係る確定申告期限まで"]),
    ("L16", "PS§2.1 所令123②一", "shotoku-rei", [R7, R8], "123/2/1", ["新たに不動産所得、事業所得、山林所得又は雑所得を生ずべき業務を開始した居住者　当該業務を開始した日"]),
    ("L17", "PS§2.1 所令123②二", "shotoku-rei", [R7, R8], "123/2/2", ["当該資産を取得した日"]),
    ("L18", "PS§2.1 所令123⑤", "shotoku-rei", [R7, R8], "123/5", ["第二項ただし書に規定する減価償却資産", "当該資産を取得した日において", "第百二十条の二第一項第一号ロ、第四号若しくは第六号に定める償却の方法を選定したものとみなす"]),
    ("L19", "PS§2.1 所令124②", "shotoku-rei", [R7, R8], "124/2", ["その新たな償却の方法を採用しようとする年の三月十五日までに"]),
    ("L20", "PS§2.1 所令124⑤", "shotoku-rei", [R7, R8], "124/5", ["同項に規定する年の十二月三十一日", "その承認があつたものとみなす"]),
    ("L21", "PS§2.1 所令126①一イ", "shotoku-rei", [R7, R8], "126/1/1/1", ["当該資産の購入の代価（引取運賃、荷役費、運送保険料、購入手数料、関税", "その他当該資産の購入のために要した費用がある場合には、その費用の額を加算した金額）"]),
    ("L22", "PS§2.1 所令126①一ロ", "shotoku-rei", [R7, R8], "126/1/1/2", ["当該資産を業務の用に供するために直接要した費用の額"]),
    ("L23", "PS§2.1 所令126①五", "shotoku-rei", [R7, R8], "126/1/5", ["前各号に規定する方法以外の方法により取得した減価償却資産", "その取得の時における当該資産の取得のために通常要する価額", "当該資産を業務の用に供するために直接要した費用の額"]),
    ("L24", "PS§2.1 所令126②", "shotoku-rei", [R7, R8], "126/2", ["法第六十条第一項各号", "引き続き所有していたものとみなした場合"]),
    ("L25", "PS§2.1 所令129", "shotoku-rei", [R7, R8], "129/1", ["耐用年数", "償却率", "改定償却率", "保証率", "残存価額", "財務省令で定めるところによる"]),
    ("L26", "PS§2.1 所令131", "shotoku-rei", [R7, R8], "131/1", ["当該資産につきその者が採用している償却の方法に基づいて計算した金額"]),
    ("L27", "PS§2.1 所令132 見出し", "shotoku-rei", [R7, R8], "132/cap", ["年の中途で業務の用に供した減価償却資産等の償却費の特例"]),
    ("L28", "PS§2.1 所令132①一イ", "shotoku-rei", [R7, R8, R30], "132/1/1/1", ["当該資産につきこれらの方法により計算した前条の規定によるその年分の償却費の額に相当する金額を十二で除し、これに当該業務の用に供された日からその年十二月三十一日（", "死亡又は出国の日", "までの期間の月数を乗じて計算した金額"]),
    ("L29", "PS§2.1/H6 所令132①二イ", "shotoku-rei", [R7, R8], "132/1/2/1", ["その年一月一日（年の中途において当該資産が当該業務の用に供された場合には、当該業務の用に供された日", "から当該業務の用以外の用に供された日までの期間の月数"]),
    ("L30", "PS§2.1 所令132②", "shotoku-rei", [R7, R8, R30], "132/2", ["前項各号の月数は、暦に従つて計算し、一月に満たない端数を生じたときは、これを一月とする。"]),
    ("L31", "PS§2.1 所令134①（超える部分の控除）", "shotoku-rei", [R7, R8], "134/1", ["累積額", "合計額が", "を超える場合には", "その超える部分の金額を控除した金額をもつてその年分の償却費の額とする"]),
    ("L32", "PS§2.1/§9 所令134①二イ", "shotoku-rei", [R7, R8, R30], "134/1/2/1", ["その取得価額から一円を控除した金額に相当する金額"]),
    ("L33", "PS§2.1/§9 所令134①二ロ", "shotoku-rei", [R7, R8, R30], "134/1/2/2", ["坑道及び第六条第八号に掲げる無形固定資産　その取得価額に相当する金額"]),
    ("L34", "PS§2.1 所令135 前段", "shotoku-rei", [R7, R8], "135/1", ["業務の用に供していないもの", "当該業務の用に供した日に当該資産の譲渡があつたものとみなして法第三十八条第二項", "の規定を適用した場合に当該資産の取得費とされる金額に相当する金額を同日における当該資産の償却後の価額として計算する"]),
    ("L35", "（検証側の追加）所令135 後段", "shotoku-rei", [R7, R8], "135/1", ["取得価額と当該償却後の価額との差額に相当する金額は、第百三十四条", "当該資産の償却費として", "必要経費に算入された金額とみなす"]),
    ("L36", "PS§2.1 所法38②一", "shotoku", [R7, R8], "38/2/1", ["その資産が不動産所得、事業所得、山林所得又は雑所得を生ずべき業務の用に供されていた期間", "第四十九条第一項", "必要経費に算入されるその資産の償却費の額の累積額"]),
    ("L37", "PS§2.1 所法38②二", "shotoku", [R7, R8], "38/2/2", ["前号に掲げる期間以外の期間", "第四十九条第一項の規定に準じて政令で定めるところにより計算したその資産の当該期間に係る減価の額"]),
    ("L38", "PS§2.1 所令85 見出し", "shotoku-rei", [R7, R8, R30], "85/cap", ["非事業用資産の減価の額の計算"]),
    ("L39", "PS§2.1 所令85①", "shotoku-rei", [R7, R8, R30], "85/1", ["当該資産の取得に要した金額並びに設備費及び改良費の額の合計額につき、当該資産と同種の減価償却資産に係る第百二十九条", "に規定する耐用年数に一・五を乗じて計算した年数により第百二十条第一項第一号イ（１）", "に規定する旧定額法に準じて計算した金額に、当該資産の当該期間に係る年数を乗じて計算した金額"]),
    ("L40", "（検証側の追加）所令85①後段（限度）", "shotoku-rei", [R7, R8], "85/1", ["当該資産と同種の減価償却資産が第百三十四条第一項第一号イ又はハ", "に掲げる減価償却資産に該当する場合には、当該計算した金額は", "定める金額を限度とする"]),
    ("L41", "PS§2.1 所令85②一", "shotoku-rei", [R7, R8, R30], "85/2/1", ["前項に規定する一・五を乗じて計算した年数　一年未満の端数は、切り捨てる。"]),
    ("L42", "PS§2.1 所令85②二", "shotoku-rei", [R7, R8, R30], "85/2/2", ["前項に規定する期間に係る年数　六月以上の端数は一年とし、六月に満たない端数は切り捨てる。"]),
    ("L43", "（検証側の追加）所令134①一イ 95%", "shotoku-rei", [R7, R8], "134/1/1/1", ["百分の九十五に相当する金額"]),
    ("L44", "（検証側の追加）所令120①一イ(1) 旧定額法（残存価額）", "shotoku-rei", [R7, R8], "120/1/1/1/1", ["旧定額法", "残存価額"]),
    # §2.2 耐用年数省令
    ("L45", "PS§2.2 耐令1①一", "taiyo", [R7, R8], "1/1/1", ["第六条第一号、第二号及び第四号から第七号まで", "別表第一"]),
    ("L46", "PS§2.2 耐令1①二", "taiyo", [R7, R8], "1/1/2", ["第六条第三号", "別表第二"]),
    ("L47", "PS§2.2 耐令1①三", "taiyo", [R7, R8], "1/1/3", ["第六条第八号", "別表第三"]),
    ("L48", "PS§2.2 耐令1①四", "taiyo", [R7, R8], "1/1/4", ["第六条第九号", "別表第四"]),
    ("L49", "PS§2.2 耐令3①柱書・ただし書", "taiyo", [R7, R8], "3/1", ["個人において使用され", "業務", "次に掲げる年数によることができる", "ただし", "百分の五十に相当する金額を超える場合には、第二号に掲げる年数についてはこの限りでない"]),
    ("L50", "PS§2.2 耐令3①一", "taiyo", [R7, R8], "3/1/1", ["使用可能期間", "取得した後直ちにこれをその業務の用に供しなかつた場合には、当該資産を取得した時から引き続き業務の用に供したものとして見込まれる当該取得の時以後の使用可能期間"]),
    ("L51", "PS§2.2 耐令3①二", "taiyo", [R7, R8], "3/1/2", ["別表第一、別表第二、別表第五又は別表第六", "前号の年数を見積もることが困難なもの", "その年数が二年に満たないときは、これを二年とする", "の全部を経過した資産　当該資産の法定耐用年数の百分の二十に相当する年数", "法定耐用年数の一部を経過した資産　当該資産の法定耐用年数から経過年数を控除した年数に、経過年数の百分の二十に相当する年数を加算した年数"]),
    ("L52", "PS§2.2 耐令3⑤", "taiyo", [R7, R8], "3/5", ["第一項各号に掲げる年数", "暦に従つて計算し、一年に満たない端数を生じたときは、これを切り捨てる"]),
    ("L53", "PS§2.2 耐令5①一", "taiyo", [R7, R8], "5/1", ["平成十九年四月一日以後に取得をされた減価償却資産", "定額法", "別表第八"]),
]
LAW += [
    # §3.1
    ("L54", "PS§3.1 所令138 見出し", "shotoku-rei", [R7, R8, R30], "138/cap", ["少額の減価償却資産の取得価額の必要経費算入"]),
    ("L55", "PS§3.1/§9 所令138①", "shotoku-rei", [R7, R8, R30], "138/1", ["居住者が不動産所得、事業所得、山林所得又は雑所得を生ずべき業務の用に供した減価償却資産（", "で、取得価額（第百二十六条第一項各号又は第二項", "の規定により計算した価額をいう。", "が十万円未満であるもの（貸付け（主要な業務として行われるものを除く。）の用に供したものを除く。）又は第百八十一条第一号（資本的支出）に規定する使用可能期間が一年未満であるものについては、第四款（減価償却資産の償却）の規定にかかわらず、その取得価額に相当する金額を、その者のその業務の用に供した年分の", "必要経費に算入する。"]),
    ("L56", "PS§3.1 所令139 見出し", "shotoku-rei", [R7, R8, R30], "139/cap", ["一括償却資産の必要経費算入"]),
    ("L57", "PS§3.1/§9 所令139①", "shotoku-rei", [R7, R8, R30], "139/1", ["雑所得を生ずべき業務の用に供した減価償却資産で取得価額が二十万円未満であるもの", "前条第一項の規定の適用があるもの", "貸付け（主要な業務として行われるものを除く。）の用に供したものを除く。）の全部又は特定の一部を一括したもの", "その業務の用に供した年以後三年間の各年の費用の額とする方法を選択したときは", "一括償却対象額", "を三で除して計算した金額とする"]),
    ("L58", "PS§3.1 所令139②", "shotoku-rei", [R7, R8], "139/2", ["確定申告書に一括償却対象額を記載した書類を添付し、かつ、その計算に関する書類を保存している場合に限り"]),
    ("L59", "PS§3.1 所令139③", "shotoku-rei", [R7, R8], "139/3", ["その年分の確定申告書に", "明細書を添付しなければならない"]),
    # §3.2
    ("L60", "PS§3.2 措法28の2①（全版で共通の部分）", "sochi", [R7, R26A, R26B, R8, R27, R30], "28_2/1", ["中小事業者（第十条第八項第六号に規定する中小事業者で青色申告書を提出するもののうち、事務負担に配慮する必要があるものとして政令で定めるものをいう。", "が、平成十八年四月一日から", "までの間に取得し、又は製作し、若しくは建設し、かつ、当該中小事業者の不動産所得、事業所得又は山林所得を生ずべき業務の用に供した減価償却資産で、その取得価額が", "未満であるもの（その取得価額が十万円未満であるもの及び第十九条第一項各号に掲げる規定の適用を受けるものその他政令で定めるものを除く。", "「少額減価償却資産」", "取得価額に相当する金額を", "その業務の用に供した年分の", "必要経費に算入する。この場合において", "その業務の用に供した年分における少額減価償却資産の取得価額の合計額が三百万円（当該業務の用に供した年がその業務を開始した日の属する年又はその業務を廃止した日の属する年である場合には", "三百万円を十二で除し、これにこれらの年において業務を営んでいた期間の月数を乗じて計算した金額", "を超えるときは、その取得価額の合計額のうち三百万円に達するまでの少額減価償却資産の取得価額の合計額を限度とする。"]),
    ("L61", "PS§3.2 措法28の2 旧（期限・上限）", "sochi", [R7, R26A], "28_2/1", ["令和八年三月三十一日までの間", "三十万円未満"]),
    ("L62", "PS§3.2 措法28の2 新（期限・上限）", "sochi", [R26B, R8, R27, R30], "28_2/1", ["令和十一年三月三十一日までの間", "四十万円未満"]),
    ("L63", "PS§3.2 措法28の2②", "sochi", [R7, R26B, R8], "28_2/2", ["前項の月数は、暦に従つて計算し、一月に満たない端数を生じたときは、これを一月とする。"]),
    ("L64", "PS§3.2 措法28の2③", "sochi", [R7, R26B, R8], "28_2/3", ["確定申告書に少額減価償却資産の取得価額に関する明細書の添付がある場合に限り、適用する。"]),
    ("L65", "PS§3.2 措法28の2④", "sochi", [R7, R26B, R8], "28_2/4", ["所得税に関する法令の規定を適用する場合には", "必要経費に算入された金額は、当該少額減価償却資産の取得価額に算入しない"]),
    ("L66", "PS§3.2 措令18の5① 旧", "sochi-rei", [R7, R26A], "18_5/1", ["常時使用する従業員の数が五百人以下の個人"]),
    ("L67", "PS§3.2 措令18の5① 新", "sochi-rei", [R26B, R8, R30], "18_5/1", ["常時使用する従業員の数が四百人以下の個人"]),
    ("L68", "PS§3.2 措令18の5②", "sochi-rei", [R7, R26B, R8], "18_5/2", ["次に掲げる規定の適用を受ける減価償却資産及び貸付け（主要な業務として行われるものを除く。）の用に供した減価償却資産とする", "所得税法施行令第百三十八条又は第百三十九条の規定"]),
    ("L69", "PS§3.2 措法10⑧六", "sochi", [R7, R26B], "10/8/6", ["中小事業者　中小事業者に該当する個人として政令で定めるものをいう。"]),
    ("L70", "PS§3.2 措令5の3⑧", "sochi-rei", [R7, R26B], "5_3/8", ["法第十条第八項第六号に規定する政令で定めるものは、常時使用する従業員の数が千人以下の個人とする。"]),
    ("L70b", "（検証側の確認）措令5の3 の項番号：2026-03-31 以前の版は第9項", "sochi-rei", [R7, R26A], "5_3/9", ["法第十条第八項第六号に規定する政令で定めるものは、常時使用する従業員の数が千人以下の個人とする。"]),
    ("L70c", "（検証側の確認）措令5の3 の項番号：2026-04-01 以後の版は第8項", "sochi-rei", [R26B, R8], "5_3/8", ["法第十条第八項第六号に規定する政令で定めるものは、常時使用する従業員の数が千人以下の個人とする。"]),
    ("L71", "PS§3.2 令和8年法律第12号附則1条", "sochi", [R26B], "S:" + R8_LAW12 + ":1/1", ["この法律は、令和八年四月一日から施行する。"]),
    ("L72", "PS§3.2 同附則1条の各号（措法の写しで見える号）に28条の2なし", "sochi", [R26B], "S:" + R8_LAW12 + ":1/1", ["第二十八条の二"], True),
    ("L73", "PS§3.2 令和8年法律第12号附則35条", "sochi", [R26B, R8], "S:" + R8_LAW12 + ":35/1", ["新租税特別措置法第二十八条の二第一項の規定は、同項に規定する中小事業者が施行日以後に取得又は製作若しくは建設をする同項に規定する少額減価償却資産について適用し、旧租税特別措置法第二十八条の二第一項に規定する中小事業者が施行日前に取得又は製作若しくは建設をした同項に規定する少額減価償却資産については、なお従前の例による。"]),
    ("L74", "PS§3.2 令和8年政令第98号附則1条", "sochi-rei", [R26B], "S:" + R8_SEIREI98 + ":1/1", ["この政令は、令和八年四月一日から施行する。"]),
    ("L75", "PS§3.2 同附則1条の各号に18条の5なし", "sochi-rei", [R26B], "S:" + R8_SEIREI98 + ":1/1", ["第十八条の五"], True),
    ("L76", "PS§3.2 令和8年政令第98号附則9条", "sochi-rei", [R26B, R8], "S:" + R8_SEIREI98 + ":9/1", ["新令第十八条の五第一項の規定は、新法第二十八条の二第一項に規定する中小事業者が施行日以後に取得又は製作若しくは建設をする同項に規定する少額減価償却資産について適用し", "施行日前に取得又は製作若しくは建設をした同項に規定する少額減価償却資産については、なお従前の例による。"]),
    # §4・§5
    ("L77", "PS§4 所令96一（雑所得を含む）", "shotoku-rei", [R7, R8], "96/1/1", ["不動産所得、事業所得、山林所得又は雑所得を生ずべき業務の遂行上必要であり、かつ、その必要である部分を明らかに区分することができる場合"]),
    ("L78", "PS§4 所令96二（青色・不動産/事業/山林）", "shotoku-rei", [R7, R8], "96/1/2", ["青色申告書を提出することにつき税務署長の承認を受けている居住者", "取引の記録等に基づいて、不動産所得、事業所得又は山林所得を生ずべき業務の遂行上直接必要であつたことが明らかにされる部分"]),
    ("L79", "PS§5.1 所法51①", "shotoku", [R7, R8], "51/1", ["居住者の営む不動産所得、事業所得又は山林所得を生ずべき事業の用に供される固定資産その他これに準ずる資産で政令で定めるものについて、取りこわし、除却、滅失（当該資産の損壊による価値の減少を含む。）その他の事由により生じた損失の金額（保険金、損害賠償金その他これらに類するものにより補てんされる部分の金額及び資産の譲渡により又はこれに関連して生じたものを除く。）は", "その損失の生じた日の属する年分の", "必要経費に算入する。"]),
    ("L80", "PS§5.1 所法51④", "shotoku", [R7, R8], "51/4", ["居住者の不動産所得若しくは雑所得を生ずべき業務の用に供され又はこれらの所得の基因となる資産（山林及び第六十二条第一項", "に規定する資産を除く。）の損失の金額（保険金、損害賠償金その他これらに類するものにより補てんされる部分の金額、資産の譲渡により又はこれに関連して生じたもの及び第一項若しくは第二項又は第七十二条第一項（雑損控除）に規定するものを除く。）は、それぞれ、その者のその損失の生じた日の属する年分の不動産所得の金額又は雑所得の金額（この項の規定を適用しないで計算したこれらの所得の金額とする。）を限度として", "必要経費に算入する。"]),
    ("L81", "PS§5.1 所令142一", "shotoku-rei", [R7, R8], "142/1/1", ["当該損失の生じた日にその資産の譲渡があつたものとみなして法第三十八条第一項又は第二項", "の規定を適用した場合にその資産の取得費とされる金額に相当する金額"]),
    ("L82", "PS§5.2 所令81 見出し", "shotoku-rei", [R7, R8, R30], "81/cap", ["譲渡所得の基因とされない棚卸資産に準ずる資産"]),
    ("L83", "PS§5.2 所令81", "shotoku-rei", [R7, R8, R30], "81/1", ["法第三十三条第二項第一号", "一不動産所得、山林所得又は雑所得を生ずべき業務に係る第三条各号（棚卸資産の範囲）に掲げる資産に準ずる資産", "二減価償却資産で第百三十八条第一項", "の規定に該当するもの（同項に規定する取得価額が十万円未満であるもののうち、その者の業務の性質上基本的に重要なものを除く。）", "三減価償却資産で第百三十九条第一項", "の規定の適用を受けたもの（その者の業務の性質上基本的に重要なものを除く。）"]),
    ("L84", "PS§5.2 所令81 に措法28の2 なし", "shotoku-rei", [R7, R8, R30], "81", ["租税特別措置法"], True),
    ("L85", "PS§5.2 所法33③一（5年以内）", "shotoku", [R7, R8], "33/3/1", ["五年以内"]),
]
LAW += [
    # §6
    ("L86", "PS§6.1 所法69①", "shotoku", [R7, R8], "69/1", ["総所得金額、退職所得金額又は山林所得金額を計算する場合において、不動産所得の金額、事業所得の金額、山林所得の金額又は譲渡所得の金額の計算上生じた損失の金額があるときは、政令で定める順序により、これを他の各種所得の金額から控除する。"]),
    ("L87", "PS§6.1 所法69②", "shotoku", [R7, R8], "69/2", ["第六十二条第一項", "生じなかつたものとみなす"]),
    ("L88", "PS§6.1 所法2①二十五", "shotoku", [R7, R8], "2/1/25", ["純損失の金額　第六十九条第一項（損益通算）に規定する損失の金額のうち同条の規定を適用してもなお控除しきれない部分の金額をいう。"]),
    ("L89", "PS§6.1 所法22②一", "shotoku", [R7, R8], "22/2/1", ["利子所得の金額、配当所得の金額、不動産所得の金額、事業所得の金額、給与所得の金額、譲渡所得の金額（第三十三条第三項第一号", "に掲げる所得に係る部分の金額に限る。）及び雑所得の金額（これらの金額につき第六十九条（損益通算）の規定の適用がある場合には、その適用後の金額）の合計額"]),
    ("L90", "PS§6.1 所法22②二", "shotoku", [R7, R8], "22/2/2", ["譲渡所得の金額（第三十三条第三項第二号に掲げる所得に係る部分の金額に限る。）及び一時所得の金額（これらの金額につき第六十九条の規定の適用がある場合には、その適用後の金額）の合計額の二分の一に相当する金額"]),
    ("L91", "PS§6.1 所法22②柱書（70・71の適用後）", "shotoku", [R7, R8], "22/2", ["第七十条第一項若しくは第二項", "第七十一条第一項", "その適用後の金額"]),
    ("L92", "PS§6.1 所令198一", "shotoku-rei", [R7, R8], "198/1/1", ["不動産所得の金額又は事業所得の金額の計算上生じた損失の金額があるときは、これをまず他の利子所得の金額、配当所得の金額、不動産所得の金額、事業所得の金額、給与所得の金額及び雑所得の金額（以下この条において「経常所得の金額」という。）から控除する。"]),
    ("L93", "PS§6.1 所令198二", "shotoku-rei", [R7, R8], "198/1/2", ["譲渡所得の金額の計算上生じた損失の金額があるときは、これをまず一時所得の金額から控除する。"]),
    ("L94", "PS§6.1 所令198三（令和8年分の版）", "shotoku-rei", [R8], "198/1/3", ["第一号の場合において、同号の規定による控除をしてもなお控除しきれない損失の金額があるときは、これを譲渡所得の金額又は一時所得の金額（前号の規定による控除が行なわれる場合には、同号の規定による控除後の金額）から順次控除する。この場合において、当該譲渡所得の金額のうちに、法第三十三条第三項第一号（譲渡所得の金額）に掲げる所得に係る部分と同項第二号に掲げる所得に係る部分とがあるときは、同項第一号に掲げる所得に係る部分の譲渡所得の金額からまず控除する。"]),
    ("L95", "PS§6.2 所令198三（令和7年分の版は「及び」）", "shotoku-rei", [R7], "198/1/3", ["譲渡所得の金額及び一時所得の金額（前号"]),
    ("L96", "PS§6.2 所令198六（令和7年分の版は「及び」）", "shotoku-rei", [R7], "198/1/6", ["譲渡所得の金額及び一時所得の金額"]),
    ("L97", "PS§6.2 所令198六（令和8年分の版は「又は」）", "shotoku-rei", [R8], "198/1/6", ["譲渡所得の金額又は一時所得の金額"]),
    ("L98", "PS§6.1 所令198四", "shotoku-rei", [R7, R8], "198/1/4", ["第二号の場合において、同号の規定による控除をしてもなお控除しきれない損失の金額があるときは、これを経常所得の金額（第一号の規定による控除が行なわれる場合には、同号の規定による控除後の金額）から控除する。"]),
    ("L99", "PS§6.1 所令198五", "shotoku-rei", [R7, R8], "198/1/5", ["第一号又は第二号の場合において、前各号の規定による控除をしてもなお控除しきれない損失の金額があるときは、これをまず山林所得の金額から控除し、なお控除しきれない損失の金額があるときは、退職所得の金額から控除する。"]),
    ("L100", "PS§6.1 所令198六（順序）", "shotoku-rei", [R8], "198/1/6", ["山林所得の金額の計算上生じた損失の金額があるときは、これをまず経常所得の金額", "譲渡所得の金額又は一時所得の金額", "から順次控除し", "退職所得の金額", "第三号後段の規定を準用する"]),
    ("L101", "PS§6.2 所令198三（2030-12-31 版は第三号を含む）", "shotoku-rei", [R30], "198/1/3", ["法第三十三条第三項第一号又は第三号"]),
    ("L102", "PS§6.1 所令199一", "shotoku-rei", [R7, R8], "199/1/1", ["まずその他の損失の金額を控除し、次に被災事業用資産の損失の金額及び変動所得の損失の金額を順次控除する。"]),
    ("L103", "PS§6.1 所令200", "shotoku-rei", [R7, R8], "200", ["競走馬の譲渡に係る譲渡所得の金額の計算上生じた損失の金額", "当該競走馬の保有に係る雑所得の金額から控除する"]),
    ("L104", "PS§6.2 令和8年政令第93号附則1条柱書", "shotoku-rei", [R8], "S:" + R8_SEIREI93 + ":1/1", ["この政令は、令和八年四月一日から施行する。"]),
    ("L105", "PS§6.2 令和8年政令第93号附則1条五", "shotoku-rei", [R8], "S:" + R8_SEIREI93 + ":1/1/5", ["第百九十八条第三号の改正規定（「及び」を「又は」に改める部分を除く。）", "第三号に掲げる規定の施行の日の属する年の翌年の一月一日"]),
    ("L106", "PS§6.2 令和8年政令第93号附則1条三", "shotoku-rei", [R8], "S:" + R8_SEIREI93 + ":1/1/3", ["金融商品取引法及び資金決済に関する法律の一部を改正する法律（令和八年法律第六十四号）の施行の日"]),
    ("L107", "PS§6.2 令和8年法律第12号附則7条（所法69②）", "shotoku", [R30], "S:" + R8_LAW12 + ":7/1", ["新所得税法第六十九条第二項の規定は、附則第一条第十号に定める日の属する年分以後の所得税について適用"]),
    # §7
    ("L108", "PS§7 所法70①", "shotoku", [R7, R8], "70/1", ["確定申告書を提出する居住者のその年の前年以前三年内の各年（その年分の所得税につき青色申告書を提出している年に限る。）において生じた純損失の金額"]),
    ("L109", "PS§7 所法70②", "shotoku", [R7, R8], "70/2", ["一変動所得の金額の計算上生じた損失の金額", "二被災事業用資産の損失の金額"]),
    ("L110", "PS§7 所法70③", "shotoku", [R7, R8], "70/3", ["被災事業用資産の損失の金額とは、棚卸資産又は第五十一条第一項若しくは第三項", "災害による損失の金額"]),
    ("L111", "PS§7 所法70④", "shotoku", [R7, R8], "70/4", ["純損失の金額が生じた年分の所得税につき確定申告書を提出し、かつ、それぞれその後において連続して確定申告書を提出している場合に限り、適用する。"]),
    ("L112", "PS§7 所法70の2 見出し", "shotoku", [R7, R8], "70_2/cap", ["特定非常災害に係る純損失の繰越控除の特例"]),
    ("L113", "PS§7 所法70の2（5年）", "shotoku", [R7, R8], "70_2/3", ["五年内"]),
    ("L114", "PS§7 所令201一", "shotoku-rei", [R7, R8], "201/1/1", ["最も古い年に生じた純損失の金額から順次控除する"]),
    ("L115", "PS§7 所令201二イ", "shotoku-rei", [R7, R8], "201/1/2/1", ["総所得金額の計算上生じた損失の部分の金額", "まずその年分の総所得金額から控除する"]),
    ("L116", "PS§7 所令201三", "shotoku-rei", [R7, R8], "201/1/3", ["その年分の各種所得の金額の計算上生じた損失の金額があるときは、まず法第六十九条（損益通算）の規定による控除を行つた後に法第七十条第一項又は第二項の規定による控除を行う。"]),
    ("L117", "PS§7 所令202", "shotoku-rei", [R7, R8], "202/1", ["同項各号に掲げる損失の金額に達するまでの金額"]),
    ("L118", "PS§7 所法2①二十三", "shotoku", [R7, R8], "2/1/23", ["変動所得　漁獲から生ずる所得、著作権の使用料に係る所得その他の所得で年々の変動の著しいもののうち政令で定めるものをいう。"]),
    ("L119", "PS§7 所令7の2 見出し", "shotoku-rei", [R7, R8], "7_2/cap", ["変動所得の範囲"]),
    ("L120", "PS§7 所令7の2", "shotoku-rei", [R7, R8], "7_2/1", ["漁獲若しくはのりの採取から生ずる所得、はまち、まだい、ひらめ、かき、うなぎ、ほたて貝若しくは真珠（真珠貝を含む。）の養殖から生ずる所得、原稿若しくは作曲の報酬に係る所得又は著作権の使用料に係る所得とする。"]),
    ("L121", "PS§7 所法123 見出し", "shotoku", [R7, R8], "123/cap", ["確定損失申告"]),
    ("L122", "PS§7 所法123①", "shotoku", [R7, R8], "123/1", ["第七十条第一項若しくは第二項", "申告書を提出することができる", "一その年において生じた純損失の金額がある場合"]),
    ("L123", "PS§7 所法140 見出し", "shotoku", [R7, R8], "140/cap", ["純損失の繰戻しによる還付の請求"]),
    ("L124", "PS§7 所法140①", "shotoku", [R7, R8], "140/1", ["青色申告書を提出する居住者は、その年において生じた純損失の金額がある場合には", "還付を請求することができる"]),
    ("L125", "PS§7 所法140④", "shotoku", [R7, R8], "140/4", ["その年の前年分の所得税につき青色申告書を提出している場合であつて、その年分の青色申告書をその提出期限までに提出した場合"]),
    ("L126", "PS§7 所法2①三十イ(2)（合計所得金額）", "shotoku", [R7, R8], "2/1/30/1/2", ["第七十条（純損失の繰越控除）及び第七十一条（雑損失の繰越控除）の規定を適用しないで計算した場合における第二十二条", "合計所得金額"]),
    # §8
    ("L127", "PS§8/H9 地方税法313②", "chiho", [R7, R8], "313/2", ["所得税法第二十二条第二項又は第三項の総所得金額、退職所得金額又は山林所得金額の計算の例により算定する"]),
    ("L128", "PS§8 地方税法313⑧", "chiho", [R7, R8], "313/8", ["前年前三年間", "所得税法第二条第一項第二十五号の純損失の金額", "当該純損失の金額が生じた年分の所得税につき青色申告書を提出し、かつ、当該純損失の金額の生じた年の末日の属する年度の翌々年度以後の年度分の市町村民税について連続して第三百十七条の二第一項又は第三項の規定による申告書を提出しているときに限り"]),
    ("L129", "PS§8 地方税法313⑨", "chiho", [R7, R8], "313/9", ["前項の規定の適用がない場合においても", "変動所得", "被災事業用資産の損失の金額", "当該純損失又は雑損失の金額の生じた年の末日の属する年度の翌年度の市町村民税について", "その後の年度分の市町村民税について連続してこれらの申告書を提出しているときに限り"]),
    ("L130", "PS§8 地方税法313⑩", "chiho", [R7, R8], "313/10", ["「被災事業用資産の損失の金額」とは"]),
    # 推測 I7 の前提
    ("L131", "I7/E8 所法2①三十四 令和7年分 58万円", "shotoku", [R7], "2/1/34", ["合計所得金額が五十八万円以下"]),
    ("L132", "I7 所法2①三十四 令和8年分 62万円", "shotoku", [R8], "2/1/34", ["合計所得金額が六十二万円以下"]),
    ("L133", "M§4 所法2①三十二 勤労学生 85万円", "shotoku", [R7], "2/1/32", ["合計所得金額が八十五万円以下"]),
    ("L134", "M§4 所法2①三十二 勤労学生 89万円", "shotoku", [R8], "2/1/32", ["合計所得金額が八十九万円以下"]),
    ("L135", "I7 措法29の4②二（令和8年分の版）", "sochi", [R8], "29_4/2/2", ["七十四万千円以上二百十九万千円未満", "当該収入金額から七十四万円を控除した残額"]),
    ("L136", "I7 措法29の4 は 2026-04-01 の版では別の条（未払賃金）", "sochi", [R26B], "29_4/cap", ["退職勤労者が弁済を受ける未払賃金に係る課税の特例"]),
]
LAW2 = [  # egov2 の出力
    ("L137", "PS§5.2 所法33④（特別控除50万円）", "shotoku", [R7, R8], "33/4", ["五十万円"]),
    ("L138", "I7 所法28③一 令和7年分 65万円", "shotoku", [R7], "28/3/1", ["百九十万円以下である場合　六十五万円"]),
]

# 版の間で同文か（True）・変わるか（False）：担当の実測 §4 の差分の表と、公開資料の「同文」の主張
SAME = [
    ("D01", "PS§1 所法2①十九 同文", "shotoku", R7, R8, "2/1/19", True),
    ("D02", "M§4 所法2 は変わる", "shotoku", R7, R8, "2", False),
    ("D03", "M§4 所法22 変化なし", "shotoku", R7, R8, "22", True),
    ("D04", "M§4 所法38 変化なし", "shotoku", R7, R8, "38", True),
    ("D05", "M§4/PS§2.1 所法49 変化なし", "shotoku", R7, R8, "49", True),
    ("D06", "M§4 所法51 変化なし", "shotoku", R7, R8, "51", True),
    ("D07", "M§4/PS§6.1 所法69 変化なし", "shotoku", R7, R8, "69", True),
    ("D08", "M§4 所法70 変化なし", "shotoku", R7, R8, "70", True),
    ("D09", "M§4 所法35 2026-12-31→2027-01-01 で変わる", "shotoku", R8, R27, "35", False),
    ("D10", "M§4 所法123 2026-12-31→2027-01-01 で変わる", "shotoku", R8, R27, "123", False),
    ("D11", "M§4 所法22 2027→2030 で変わる", "shotoku", R27, R30, "22", False),
    ("D12", "M§4 所法33 2027→2030 で変わる", "shotoku", R27, R30, "33", False),
    ("D13", "M§4 所法69② 2027→2030 で変わる", "shotoku", R27, R30, "69/2", False),
    ("D14", "M§4 所法2 2027→2030 で変わる", "shotoku", R27, R30, "2", False),
]
SAME += [(f"D{15 + i}", f"M§4 所令{a} 2025→2026 で変わる", "shotoku-rei", R7, R8, a, False)
         for i, a in enumerate(["6", "120_2", "123", "125", "132", "134", "198"])]
SAME += [(f"D{22 + i}", f"M§4/§5.1 所令{a} {x}→{y} 変化なし", "shotoku-rei", x, y, a, True)
         for i, (a, x, y) in enumerate([(a, x, y) for a in ["138", "139", "85", "81", "142", "199", "200", "201", "202"]
                                        for (x, y) in ((R7, R8), (R8, R30))])]
SAME += [
    ("D40", "M§4 所令198 2026→2030 で変わる", "shotoku-rei", R8, R30, "198", False),
    ("D41", "M§4 措法28の2 2025-12-31=2026-03-31", "sochi", R7, R26A, "28_2", True),
    ("D42", "M§4 措法28の2 2026-03-31→04-01 で変わる", "sochi", R26A, R26B, "28_2", False),
    ("D43", "M§4 措法28の2 2026-04-01=2026-12-31", "sochi", R26B, R8, "28_2", True),
    ("D44", "M§4 措法28の2 2026-12-31=2030-12-31", "sochi", R8, R30, "28_2", True),
    ("D45", "M§4 措令18の5 2026-03-31→04-01 で変わる", "sochi-rei", R26A, R26B, "18_5", False),
    ("D46", "M§4 措令18の5 2025-12-31=2026-03-31", "sochi-rei", R7, R26A, "18_5", True),
    ("D47", "M§4 措令18の5 2026-04-01=2030-12-31", "sochi-rei", R26B, R30, "18_5", True),
    ("D48", "M§4 耐令1 は変わる", "taiyo", R7, R8, "1", False),
    ("D49", "M§4 耐令2 は変わる", "taiyo", R7, R8, "2", False),
    ("D50", "M§4 耐令3 は変わる", "taiyo", R7, R8, "3", False),
    ("D51", "M§4 耐令4 変化なし", "taiyo", R7, R8, "4", True),
    ("D52", "M§4 耐令5 変化なし", "taiyo", R7, R8, "5", True),
    ("D53", "M§4 耐令6 変化なし", "taiyo", R7, R8, "6", True),
    ("D54", "PS§7 所令7の2 同文", "shotoku-rei", R7, R8, "7_2", True),
    ("D55", "PS§6.1 所法69① 同文", "shotoku", R7, R8, "69/1", True),
]

# 版（law_revision_id と状態）：公開資料 §0 の表、実測 §2 の表（状態を書いていないものは None）
REVS = [
    ("shotoku", R7, "340AC0000000033_20251218_507AC0000000013", "PreviousEnforced"),
    ("shotoku", R8, "340AC0000000033_20261201_508AC0000000012", "UnEnforced"),
    ("shotoku", R27, "340AC0000000033_20270101_508AC0000000012", "UnEnforced"),
    ("shotoku", R30, "340AC0000000033_20300619_507AC0000000074", None),
    ("shotoku-rei", R7, "340CO0000000096_20251201_507CO0000000120", "PreviousEnforced"),
    ("shotoku-rei", R8, "340CO0000000096_20261201_508CO0000000093", "UnEnforced"),
    ("shotoku-rei", R30, "340CO0000000096_20280101_508CO0000000093", "UnEnforced"),
    ("shotoku-ki", R7, "340M50000040011_20251201_507M60000040018", None),
    ("shotoku-ki", R8, "340M50000040011_20261211_508M60000040017", None),
    ("sochi", R7, "332AC0000000026_20251231_507AC1000000081", "PreviousEnforced"),
    ("sochi", R26A, "332AC0000000026_20260101_507AC0000000041", "PreviousEnforced"),
    ("sochi", R26B, "332AC0000000026_20260401_508AC0000000012", "PreviousEnforced"),
    ("sochi", R8, "332AC0000000026_20261204_508AC0000000012", "UnEnforced"),
    ("sochi-rei", R7, "332CO0000000043_20251231_507CO0000000401", "PreviousEnforced"),
    ("sochi-rei", R26A, "332CO0000000043_20260101_507CO0000000277", "PreviousEnforced"),
    ("sochi-rei", R26B, "332CO0000000043_20260401_508CO0000000098", "PreviousEnforced"),
    ("sochi-rei", R8, "332CO0000000043_20261201_508CO0000000098", "UnEnforced"),
    ("sochi-ki", R7, "332M50000040015_20251231_507M60000040068", None),
    ("sochi-ki", R8, "332M50000040015_20261204_508M60000040021", None),
    ("taiyo", R7, "340M50000040015_20250401_507M60000040034", "PreviousEnforced"),
    ("taiyo", R8, "340M50000040015_20260522_508M60000040029", "CurrentEnforced"),
    ("taiyo", R30, "340M50000040015_20260522_508M60000040029", "CurrentEnforced"),
    ("chiho", R7, "325AC0000000226_20251212_507AC0000000087", "PreviousEnforced"),
    ("chiho", R8, "325AC0000000226_20261126_508AC0000000002", "UnEnforced"),
]
LAW_IDS = {"shotoku": ("340AC0000000033", None), "shotoku-rei": ("340CO0000000096", None), "shotoku-ki": ("340M50000040011", None),
           "sochi": ("332AC0000000026", None), "sochi-rei": ("332CO0000000043", None), "sochi-ki": ("332M50000040015", None),
           "taiyo": ("340M50000040015", "昭和四十年大蔵省令第十五号"), "chiho": ("325AC0000000226", None)}
# 実測 §4.1 の表（所令198 の改正ごとの版）
REV198 = [("340CO0000000096_20251201_507CO0000000120", "2025-12-01", "令和七年政令第百二十号", "及び"),
          ("340CO0000000096_20260101_507CO0000000120", "2026-01-01", "令和七年政令第百二十号", "及び"),
          ("340CO0000000096_20260401_506CO0000000141", "2026-04-01", "令和六年政令第百四十一号", "及び"),
          ("340CO0000000096_20260401_507CO0000000120", "2026-04-01", "令和七年政令第百二十号", "及び"),
          ("340CO0000000096_20260401_508CO0000000093", "2026-04-01", "令和八年政令第九十三号", "又は"),
          ("340CO0000000096_20260522_508CO0000000093", "2026-05-22", "令和八年政令第九十三号", "又は"),
          ("340CO0000000096_20261201_508CO0000000093", "2026-12-01", "令和八年政令第九十三号", "又は")]
TAIYO_REVS = [("2025-04-01", "令和七年財務省令第三十四号"), ("2026-04-01", "令和八年財務省令第二十九号"), ("2026-05-22", "令和八年財務省令第二十九号")]

# 国税庁のページ（HTML のテキスト）の引用：(ID, 文書, ページ, [順に現れるべき断片], [否定なら True])
NQ = [
    ("N01", "PS§0 TA 2100 の版", "ta_2100", ["[令和8年4月1日現在法令等]"]),
    ("N02", "PS§0 TA 2106 の版", "ta_2106", ["[令和8年4月1日現在法令等]"]),
    ("N03", "PS§0 TA 2250 の版", "ta_2250", ["[令和8年4月1日現在法令等]"]),
    ("N04", "PS§0 所基通の前文", "kihon_zenbun", ["直審（所）30", "昭和45年7月1日"]),
    ("N05", "PS§0 質疑 04/17 の作成時点", "shitsugi_04_17", ["令和7年8月1日現在の法令・通達等に基づいて作成しています。"]),
    ("N06", "PS§0 質疑 04/14 の作成時点", "shitsugi_04_14", ["令和7年8月1日現在の法令・通達等に基づいて作成しています。"]),
    ("N07", "PS§1 所基通2-14", "kihon_01_04", ["2－14", "時の経過によりその価値の減少しない資産", "古美術品", "歴史的価値又は希少価値を有し、代替性のないもの", "取得価額が1点100万円以上であるもの（時の経過によりその価値が減少することが明らかなものを除く。）", "取得価額が1点100万円未満であるもの（時の経過によりその価値が減少しないことが明らかなものを除く。）は減価償却資産と取り扱う。"]),
    ("N08", "PS§1 所基通2-16", "kihon_01_04", ["2－16", "現にか動していない場合であっても、これらの業務の用に供するために維持補修が行われており、いつでもか動し得る状態にあるときは、減価償却資産に該当する。"]),
    ("N09", "PS§1 所基通2-17", "kihon_01_04", ["2－17", "建設又は製作中の建物、機械及び装置等の資産は、減価償却資産に該当しない", "その完成した部分が", "業務の用に供されている場合には、その部分は減価償却資産に該当する"]),
    ("N10", "PS§2.3 TA 2100 償却方法の選定", "ta_2100", ["新たに業務を始めた場合には、減価償却の方法を選定してその翌年の3月15日までに所轄の税務署長に届け出なければなりません。この届出がない場合には、法定の償却方法で計算することになります。", "法定の償却方法は一般的には旧定額法または定額法です。", "減価償却の方法を変更しようとするときは、その変更しようとする年の3月15日までに所轄の税務署長に申請書を提出してその承認を受ける必要があります。"]),
    ("N11", "PS§2.3 手続 A1-18 の提出時期", "tetsuzuki_18", ["上記［手続対象者］となった日の属する年分の確定申告期限までに提出してください。"]),
    ("N12", "PS§2.3 TA 2106 注1・限度額", "ta_2106", ["（注1）資産を年の中途で取得または取壊しをした場合には、上記の金額を12で除しその年分において業務に使用していた月数を乗じて計算した金額になります。", "（1） 有形減価償却資産（坑道を除く。）または生物の取得価額から1円を控除した金額", "（2） 坑道および無形固定資産の取得価額"]),
    ("N13", "PS§2.3 質疑 04/17 の数字", "shitsugi_04_17", ["平成18年10月20日に新築した自宅", "令和7年2月1日から貸付けの用に供して", "22年×1.5＝33年（1年未満の端数切捨て）", "（30,000,000円-(30,000,000円×10％））×0.031×13年＝10,881,000円", "非業務用期間は18年3か月と12日となりますが、6か月未満の端数は切り捨てますので、18年となります。", "非業務用資産の減価の額の計算は、旧定額法によることに留意してください（所得税法施行令第85条、第120条の2）。", "30,000,000円－15,066,000円＝14,934,000円"]),
    ("N14", "（検証側の追加）質疑 04/17 の末尾の注", "shitsugi_04_17", ["なお、平成19年4月1日以後に取得した建物については定額法によることになります。"]),
    ("N15", "PS§2.3 所基通49-18", "kihon_08_08", ["49－18", "年の中途において従来使用されていた用途から他の用途に転用した場合には、その年において転用した減価償却資産の全部についてその転用した日の属する年の1月1日から転用後の耐用年数により償却費を計算することができる", "その年において転用した減価償却資産の一部についてのみこの方法により償却費を計算することはできない。"]),
    ("N16", "PS§3.1 所基通49-39", "kihon_08_12", ["49－39", "通常1単位として取引されるその単位、例えば、機械及び装置については1台又は1基ごとに、工具、器具及び備品については1個、1組又は1そろいごとに判定"]),
    ("N17", "PS§3.1 所基通49-39の2", "kihon_08_12", ["49－39の２", "一時的に貸付けの用に供したような場合において、その貸付けの用に供した事実のみをもって", "貸付けの用に供したものに該当するとはいえない"]),
    ("N18", "PS§3.1 所基通49-40", "kihon_08_12", ["49－40", "一般的に消耗性のものとして認識されている", "その使用可能期間が1年未満", "おおむね過去3年間の平均値を基準として判定する。"]),
    ("N19", "PS§3.1 所基通49-40の2", "kihon_08_12", ["49－40の2", "その全部又は一部につき滅失、除却等の事実が生じたときであっても、当該各年においてその一括償却資産につき必要経費に算入する金額は、同項の規定に従い計算される金額となる", "一括償却資産の全部又は一部を譲渡した場合についても、同様とする。"]),
    ("N20", "PS§3.1 所基通49-40の3", "kihon_08_12", ["49－40の3", "死亡した日の属する年分の必要経費に算入する", "業務を承継した者"]),
    ("N21", "PS§3.1 所基通49-41", "kihon_08_12", ["49－41", "法第67条", "当該減価償却資産の取得価額に相当する金額のうちその支出した金額を当該支出をした日の属する年分の", "必要経費に算入する。"]),
    ("N22", "PS§3.1 TA 2100 注5", "ta_2100", ["（注5） 取得価額の判定に際し、消費税の額を含めるかどうかは納税者の経理方式によります。すなわち、税込経理であれば消費税を含んだ金額で、税抜経理であれば消費税を含まない金額で判定します。なお、免税事業者の経理方式は税込経理になります。"]),
    ("N23", "PS§3.1 TA 2100 根拠法令等に平元直所3-8", "ta_2100", ["平元直所3-8"]),
    ("N24", "PS§3.2 措通28の2-1", "sochitsu_28_02", ["28の2-1", "中小事業者に該当するかどうかは、原則として", "取得等", "をした日及び当該少額減価償却資産を業務の用に供した日の現況により判定する"]),
    ("N25", "PS§3.2 措通28の2-1の2", "sochitsu_28_02", ["28の2-1の2", "常時使用する従業員の数"]),
    ("N26", "PS§3.2 措通28の2-2（40万円・令８課個2-10）", "sochitsu_28_02", ["28の2-2", "少額減価償却資産の取得価額が40万円未満であるかどうかについては、通常1単位として取引されるその単位", "令８課個2-10"]),
    ("N27", "PS§3.2 措通28の2-3（30万円のまま）", "sochitsu_28_02", ["28の2-3", "「減価償却費の計算」欄に次に掲げる事項を記載して提出し", "取得価額30万円未満の減価償却資産について、措置法第28条の2第1項の規定を適用していること", "適用した減価償却資産の取得価額の合計額", "適用した減価償却資産の明細は、別途保管していること"]),
    ("N28", "PS§3.2 TA 2100 注3", "ta_2100", ["（注3）一定の要件を満たす青色申告者が、平成18年4月1日から令和11年3月31日までに取得した取得価額10万円以上40万円未満（令和8年3月31日までに取得した場合の取得価額は10万円以上30万円未満）の減価償却資産（上記（注2）の適用を受けるものを除きます。）については、一定の要件の下でその取得価額の合計額のうち300万円に達するまでの取得価額の合計額をその業務の用に供した年分の必要経費に算入できるという特例があります。"]),
    ("N29", "PS§3.2 TA 2100 注4", "ta_2100", ["（注4）令和4年4月1日以降に取得した減価償却資産で貸付けの用に供したもの（主要な業務として行う貸付けに供するものを除きます。）については、上記（注1）ないし（注3）の適用はありません。"]),
    ("N30", "PS§4 質疑 04/14", "shitsugi_04_14", ["減価償却資産の普通償却費は、所得税法上強制償却となることから（所得税法第37条、第49条）、その親族のその対価に係る各種所得の金額の計算上必要経費に算入されるべき金額に該当し、事業主の事業所得等の金額の計算上必要経費に算入することになります。", "普通償却費については、Bの持分を含む旅館業用建物等の全部について、Aの事業所得の金額の計算上必要経費に算入することになりますが、特別償却については、Aの持分についてのみ必要経費に算入することができます。", "所得税法第37条、第49条、第56条、租税特別措置法第12条"]),
    ("N31", "PS§6.3 TA 2250", "ta_2250", ["損益通算の対象となる所得は次の所得です。", "（1） 不動産所得", "（2） 事業所得", "（3） 譲渡所得", "（4） 山林所得", "（注2） 配当所得、給与所得、一時所得および雑所得の金額の計算上損失が生じることはありますが、その損失の金額は他の各種所得の金額から控除することはできません。", "（注3） 生活に通常必要でない資産に係る所得の金額の計算上生じた損失は、競走馬の譲渡に係るもので一定の場合を除き、他の各種所得の金額と損益通算できません。", "（4） 生活の用に供する動産で、1個または1組の価額が30万円を超える貴金属、書画、骨とう等"]),
    ("N32", "PS§6.3 TA 2250 は順序の説明を持たない（「経常所得」の語がない）", "ta_2250", ["経常所得"], True),
    ("N33", "（検証側の追加）TA 2250 注4（不動産所得の損失のうち通算できないもの）", "ta_2250", ["（注4） 不動産所得の金額の計算上生じた損失の金額のうち、次に掲げるような損失の金額は、その損失が生じなかったものとみなされ、他の各種所得の金額から控除することはできません。", "土地（土地の上に存する権利を含みます。）を取得するために要した負債の利子に相当する部分の金額", "国外中古建物"]),
    ("N34", "PS§0 TA 2100 から 2100_01.pdf・2100_02.pdf へのリンク", "ta_2100.links", ["pdf/2100_01.pdf", "pdf/2100_02.pdf"]),
    ("N35", "（検証側の追加）TA 2109 の版と、業務供用後の償却方法は取得年月日による", "ta_2109", ["[令和8年4月1日現在法令等]", "その資産の取得年月日（非業務用から業務用に転用した日ではありません。）により", "未償却残高または取得価額を基に"]),
    ("N36", "（検証側の追加）TA 2109 注1（95%・所令134②）", "ta_2109", ["非業務用資産の減価の額の計算は、旧定額法によることに留意してください。", "取得価額の95パーセントに相当する金額"]),
]
# 実測 §3 の表（Last-Modified の日付と SHA-256 の先頭16桁）：(担当の id, 検証側の id, 日付, 先頭16桁)
NTA_META = [("ta_2100", "ta_2100", "2026-09-09", "969d085668660242"), ("ta_2250", "ta_2250", "2026-09-09", "81cabb299948105a"),
            ("kihon_01_04", "kihon_01_04", "2026-10-02", "cf6880a3a19b14f1"), ("kihon_08_05", "kihon_08_05", "2025-11-25", "30106b4f247464cd"),
            ("kihon_08_06", "kihon_08_06", "2025-12-25", "bf74fc838520f328"), ("kihon_08_08", "kihon_08_08", "2026-10-02", "c851fcef5d2218fb"),
            ("kihon_08_10", "kihon_08_10", "2025-12-25", "e19ac138ce44d6e9"), ("kihon_08_12", "kihon_08_12", "2026-10-02", "7eb3a7fd17cf0b84"),
            ("kihon_08_13", "kihon_08_13", "2024-01-18", "15c644e0a812bf8b"), ("kihon_09_01", "kihon_09_01", "2025-11-25", "8f4e8849c99b2757"),
            ("kihon_15_01", "kihon_15_01", "2025-11-25", "ead14cdf750a9590"), ("kihon_04_07", "kihon_04_07", "2025-12-25", "4923238537f5b3b8"),
            ("sochitsu_28_02", "sochitsu_28_02", "2026-10-02", "4e268639627124d3"), ("shitsugi_04_17", "shitsugi_04_17", "2025-12-03", "2b9756ae2bae08ef"),
            ("shitsugi_04_14", "shitsugi_04_14", "2025-12-03", "3b0c023583ce48b4"), ("aoiro_kessan_kakikata_r07", "pdf_037", "2025-12-12", "77c8ad203bbd04ef"),
            ("sonshitsu_tebiki_r07", "pdf_003", "2025-12-12", "e3a89abd687f659d"), ("ta_2106", "ta_2106", "2026-09-09", "6486a19d37297e29"),
            ("ta_2100_01", "pdf_2100_01", "2024-01-18", "4cdc99af5e423953"), ("ta_2100_02", "pdf_2100_02", "2024-01-18", "c02362285fec7aba"),
            ("tetsuzuki_18", "tetsuzuki_18", "2026-10-28", "0da6f068cb29717a"),
            ("(IMPL jigyo) 034.pdf", "pdf_034", None, "5ac5dabb0eff0947"), ("(IMPL jigyo) kichou09.pdf", "pdf_kichou09", None, "7e64dc7b9a14da6e")]

# 別表：(ID, 文書, 別表, 起点の細目, [(起点からの行のずれ, 細目に含む語, 年数)])
BEPPYO = [
    ("B01", "PS§2.2 パソコン4・その他の電子計算機5", "別表第一", "電子計算機", [(1, "パーソナルコンピュータ（サーバー用のものを除く。）", 4), (2, "その他のもの", 5)]),
    ("B02", "PS§2.2 複写機等5・その他の事務機器5", "別表第一", "複写機、計算機（電子計算機を除く。）、金銭登録機、タイムレコーダーその他これらに類するもの", [(0, "複写機", 5), (1, "その他の事務機器", 5)]),
    ("B03", "PS§2.2 電話設備 デジタル6・その他10", "別表第一", "電話設備その他の通信機器", [(1, "デジタル構内交換設備及びデジタルボタン電話設備", 6), (2, "その他のもの", 10)]),
    ("B04", "PS§2.2 カメラ等5", "別表第一", "カメラ、映画撮影機、映写機及び望遠鏡", [(0, "カメラ", 5)]),
    ("B05", "PS§2.2 事務机等 金属15・その他8", "別表第一", "事務机、事務いす及びキャビネット", [(1, "主として金属製のもの", 15), (2, "その他のもの", 8)]),
    ("B06", "PS§2.2 音響機器5", "別表第一", "ラジオ、テレビジョン、テープレコーダーその他の音響機器", [(0, "音響機器", 5)]),
    ("B07", "PS§2.2 冷房用又は暖房用機器6", "別表第一", "冷房用又は暖房用機器", [(0, "冷房用又は暖房用機器", 6)]),
    ("B08", "PS§2.2 小型車4・ダンプ4・貨物その他5・報道通信用5・その他6・二輪3・自転車2", "別表第一", "小型車（総排気量が〇・六六リットル以下のものをいう。）",
     [(0, "小型車", 4), (2, "貨物自動車", None), (3, "ダンプ式のもの", 4), (4, "その他のもの", 5), (5, "報道通信用のもの", 5), (6, "その他のもの", 6),
      (7, "二輪又は三輪自動車", 3), (8, "自転車", 2)]),
    ("B09", "PS§2.2 ソフトウエア 複写販売用原本3・その他5", "別表第三", "複写して販売するための原本", [(0, "複写して販売するための原本", 3), (1, "その他のもの", 5)]),
]


# ---------------------------------------------------------------- 別表の読み取り（検証側で書き直したもの）
KD = dict(zip("〇一二三四五六七八九", range(10)))


def kan(s):
    """漢数字（位取り「一〇」、単位つき「十五」）を整数にする。"""
    s = s.strip()
    if s and all(c in KD for c in s):
        return int("".join(str(KD[c]) for c in s))
    n, cur = 0, 0
    for c in s:
        if c in KD:
            cur = KD[c]
        elif c == "十":
            n, cur = n + (cur or 1) * 10, 0
        elif c == "百":
            n, cur = n + (cur or 1) * 100, 0
        else:
            raise ValueError(s)
    return n + cur


def rate_of(s):
    a, b = s.split("・")
    return F(kan(a) * 10 ** len(b) + int("".join(str(KD[c]) for c in b)), 10 ** len(b))


def table(short, asof, prefix):
    return next(t for t in eg(short, asof)["appdx"] if t["title"].startswith(prefix))


def year_rate_pairs(t):
    out = {}
    for r in t["rows"]:
        cells = [c["text"] for c in r]
        if len(cells) >= 2 and re.fullmatch(r"[〇一二三四五六七八九十百]+", cells[0] or "-") and "・" in cells[1]:
            out[kan(cells[0])] = rate_of(cells[1])
    return out


def find_rows(t, detail_kw):
    return [i for i, r in enumerate(t["rows"]) if len(r) >= 2 and detail_kw in r[-2]["text"]]


def row_detail_years(t, i):
    cells = [c["text"] for c in t["rows"][i]]
    y = cells[-1]
    return cells[-2], (kan(y) if y and re.fullmatch(r"[〇一二三四五六七八九十百]+", y) else None)


# ---------------------------------------------------------------- 計算の再現（担当の関数を使わずに書き直した）
def add_months(d, k):
    y, m = divmod(d.month - 1 + k, 12)
    y, m = d.year + y, m + 1
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def months_by_full(start, end):
    """暦に従う月数（1月未満の端数は1月）。k か月の満了日は「k か月後の応当日の前日」（応当日がなければその月の末日）。"""
    k = 0
    while True:
        k += 1
        y, m = divmod(start.month - 1 + k, 12)
        y, m = start.year + y, m + 1
        last = calendar.monthrange(y, m)[1]
        end_k = dt.date(y, m, start.day) - dt.timedelta(days=1) if start.day <= last else dt.date(y, m, last)
        if end_k >= end:
            return k


def months_full_only(start, end):
    """start から end の前日までの満月数（日の端数は切り捨て）。所令85②二の年数の材料。"""
    k = 0
    while add_months(start, k + 1) <= end:
        k += 1
    return k


def months_simple(start, year):
    return 0 if start.year > year else (12 if start.year < year else 13 - start.month)


def sl_schedule(cost, rate, start, years_to, ratio=F(1), intangible=False, rnd=math.floor, base_remaining=None):
    """定額法：年額 = 取得価額 × 率 × 月数/12（端数は rnd）。有形は1円、無形は0円まで（所令134①二イ・ロ）。"""
    keep = 0 if intangible else 1
    remaining = cost if base_remaining is None else base_remaining
    rows = []
    for y in range(start.year, years_to + 1):
        m = months_simple(start, y)
        raw = F(cost) * rate * F(m, 12)
        v = max(0, min(rnd(raw), remaining - keep))
        remaining -= v
        rows.append({"year": y, "months": m, "raw": raw, "dep": v, "biz": F(v) * ratio, "end": remaining})
        if remaining == keep:
            break
    return rows


def sontsu198(keijo, loss, tanki=0, choki=0, ichiji=0, sanrin=0, taishoku=0):
    """所令198一・三・五（不動産・事業の損失だけがある場合）。"""
    vals = {"keijo": keijo, "tanki": tanki, "choki": choki, "ichiji": ichiji, "sanrin": sanrin, "taishoku": taishoku}
    for k in ("keijo", "tanki", "choki", "ichiji", "sanrin", "taishoku"):
        d = min(vals[k], loss)
        vals[k] -= d
        loss -= d
    vals["junsonshitsu"] = loss
    vals["soshotoku"] = F(vals["keijo"] + vals["tanki"]) + F(vals["choki"] + vals["ichiji"], 2)
    return vals


def calc():
    r8 = year_rate_pairs(table("taiyo", R8, "別表第八"))
    r7 = year_rate_pairs(table("taiyo", R7, "別表第八"))
    old = year_rate_pairs(table("taiyo", R8, "別表第七"))
    out = {}
    exp = {2: "0.500", 3: "0.334", 4: "0.250", 5: "0.200", 6: "0.167", 7: "0.143", 8: "0.125", 9: "0.112", 10: "0.100", 15: "0.067", 20: "0.050"}
    out["beppyo8"] = {"title": table("taiyo", R8, "別表第八")["title"], "count": len(r8), "years": [min(r8), max(r8)], "same_r7_r8": r7 == r8,
                      "doc_values_match": all(f"{float(r8[n]):.3f}" == v for n, v in exp.items()),
                      "ceil_property_mismatch": [n for n, r in r8.items() if r != F(math.ceil(F(1000, n)), 1000)]}
    out["beppyo7"] = {"title": table("taiyo", R8, "別表第七")["title"], "6": str(old[6]), "22": str(old[22]), "33": str(old[33])}
    mism = []
    for y in (2025, 2026):
        d = dt.date(y, 1, 1)
        while d.year == y:
            if months_simple(d, y) != months_by_full(d, dt.date(y, 12, 31)):
                mism.append(d.isoformat())
            d += dt.timedelta(days=1)
    out["months_check"] = {"days": 730, "mismatch": mism}
    for tag, st in (("E1_2026", dt.date(2026, 7, 15)), ("I4A_2025", dt.date(2025, 7, 15))):
        rows = sl_schedule(240_000, r8[4], st, st.year + 6, F(6, 10))
        b = F(240_000)
        out[tag] = []
        for r in rows:
            b -= r["biz"]
            out[tag].append({"year": r["year"], "m": r["months"], "dep": r["dep"], "biz": str(r["biz"]), "end_A": r["end"], "end_B": str(b)})
    for tag, st in (("E2_2026", dt.date(2026, 8, 1)), ("I2_2025", dt.date(2025, 8, 1))):
        out[tag] = {mode: [(r["year"], r["months"], str(r["raw"]), r["dep"]) for r in sl_schedule(123_457, r8[4], st, st.year + 6, rnd=fn)]
                    for mode, fn in (("floor", math.floor), ("ceil", math.ceil))}
    out["E3"] = [(r["year"], r["months"], r["dep"], r["end"]) for r in sl_schedule(300_000, r8[5], dt.date(2025, 12, 1), 2031, intangible=True)]
    out["E4_I3"] = {"150000/3": str(F(150_000, 3)), "100001/3": str(F(100_001, 3)), "floor_x3": 3 * (100_001 // 3),
                    "residual_in_3rd": 100_001 - 2 * (100_001 // 3), "ceil_ceil_rest": [math.ceil(F(100_001, 3))] * 2 + [100_001 - 2 * math.ceil(F(100_001, 3))]}
    out["E5"] = {m: str(F(3_000_000, 12) * m) for m in (1, 5, 7, 12)}
    out["I1_9_months_2026-06-10"] = months_by_full(dt.date(2026, 6, 10), dt.date(2026, 12, 31))
    out["I1"] = {"#2": str(F(100_000, 3)), "#3": str(F(100_000) * r8[4] * F(months_simple(dt.date(2025, 9, 10), 2025), 12)),
                 "#4": str(F(350_000) * r8[4] * F(months_simple(dt.date(2026, 4, 5), 2026), 12)),
                 "#6": str(F(400_000) * r8[4] * F(months_simple(dt.date(2026, 4, 5), 2026), 12)), "#8": str(F(150_000, 3))}
    c = sontsu198(300_000 + 100_000, 500_000, ichiji=200_000)
    out["E6"] = {"correct": {k: str(v) for k, v in c.items()}, "naive": str(F(300_000 + 100_000 - 500_000) + F(200_000, 2))}
    out["E7"] = str(F(300_000) + F(200_000, 2))
    out["E8_I7"] = {"r7_salary_income(1,350,000-650,000)": 1_350_000 - 650_000, "r8_salary_income(1,440,000-740,000)": 1_440_000 - 740_000,
                    "jigyo": 700_000 - 200_000, "zatsu": 700_000}
    for tag, acq, conv in (("E9_2026", dt.date(2024, 5, 10), dt.date(2026, 7, 1)), ("I5_2025", dt.date(2023, 5, 10), dt.date(2025, 7, 1))):
        y15 = (4 * 15) // 10
        fm = months_full_only(acq, conv)
        yrs = fm // 12 + (1 if fm % 12 >= 6 else 0)
        genka = F(200_000) * F(9, 10) * old[y15] * yrs
        rem = F(200_000) - min(genka, F(200_000) * F(95, 100))
        rows = sl_schedule(200_000, r8[4], conv, conv.year + 5, base_remaining=int(rem))
        out[tag] = {"y15": y15, "full_months": fm, "years": yrs, "genka": str(genka), "rem": str(rem),
                    "rows": [(r["year"], r["months"], r["dep"], r["end"]) for r in rows]}
    out["04_17"] = {"18y": str(F(30_000_000) * F(9, 10) * old[33] * 18), "13y_alt": str(F(30_000_000) * F(9, 10) * old[33] * 13),
                    "r7_dep_11m": str(F(30_000_000) * F(9, 10) * old[22] * F(11, 12))}
    dep26 = F(200_000) * r8[4] * F(6, 12)
    rem26 = 200_000 - 50_000 - 50_000
    loss = rem26 - dep26
    before = 300_000 - 290_000 - dep26
    allowed = min(loss, max(before, 0))
    out["I6"] = {"dep_2026": str(dep26), "rem_2026_01_01": rem26, "loss": str(loss), "jigyo": str(300_000 - 290_000 - dep26 - loss),
                 "zatsu_limit": str(before), "zatsu_loss_allowed": str(allowed), "zatsu": str(before - allowed)}
    other, hendo, salary = 200_000, 100_000, 150_000
    rest_other = other - min(other, salary)
    rest_hendo = hendo - max(0, salary - other)
    out["I8"] = {"junsonshitsu": rest_other + rest_hendo, "carry_white": min(rest_other + rest_hendo, rest_hendo)}
    out["I9"] = {"no_dep_deduct": 1_650_000 - 200_000, "dep_deduct": 1_650_000 - 200_000 - 200_000}
    bad, n = 0, 0
    for A in range(-200_000, 400_001, 5_000):
        for dep in range(0, 150_001, 5_000):
            for ls in range(0, 200_001, 5_000):
                n += 1
                a = (A - dep) - min(ls, max(A - dep, 0))
                b = A - min(dep + ls, max(A, 0))
                bad += max(a, 0) != max(b, 0)
    out["disposal_equiv"] = {"cases": n, "mismatch": bad, "doc_cases_41x11x16": 41 * 11 * 16}
    return out


# ---------------------------------------------------------------- 文書の構造の検査
DOCS = {"PS": "docs/public-sources/20261109_round2_genka-laws-and-nta.md", "M": "docs/measurements/20261109_round2_genka-fetch-and-checks.md",
        "H": "docs/hypotheses/20261109_round2_genka-model.md", "I": "docs/inferences/20261109_round2_genka-examples.md"}
REFS = [
    ("docs/public-sources/20261109_impl-prep_jigyo-laws-and-nta.md", ["## 1.", "### 1.3", "## 6.", "## 7.", "### 7.4", "## 11."]),
    ("docs/public-sources/20261109_R1-laws_income-tax.md", ["## 4."]),
    ("docs/public-sources/20261109_impl-prep_kenpo-dependent-practice.md", ["### 1.2"]),
    ("docs/hypotheses/20261109_impl-prep_jigyo-calculation-model.md", ["## H3", "## H6", "## H10"]),
    ("docs/hypotheses/20261109_impl-prep_kenpo-input-facts.md", ["## HK0", "## HK1", "## HK2"]),
    ("docs/hypotheses/20261109_impl-prep_kyuyo-hypotheses.md", ["## H1"]),
]


def doc_checks():
    res = {}
    for k, p in DOCS.items():
        t = (ROOT / p).read_text(encoding="utf-8")
        res[k] = {"urls": len(re.findall(r"https?://", t)), "scope_refs": sorted(set(re.findall(r"SCOPE §[0-9][0-9.\-]*", t))),
                  "personal_terms": [w for w in ("国家公務員", "単身赴任", "共済組合", "長男", "長女", "次男", "息子", "娘") if w in t]}
    res["SCOPE_headings"] = re.findall(r"^#{2,3} [0-9.]+", (ROOT / "SCOPE.md").read_text(encoding="utf-8"), re.M)
    res["refs"] = {p: {h: bool(re.search("^" + re.escape(h), (ROOT / p).read_text(encoding="utf-8"), re.M)) for h in hs} for p, hs in REFS}
    return res


def author_pdf_hashes():
    """担当が Read で読んだ PDF のローカルの写し（信頼できないデータ。バイト列を読むだけ）が、取得記録の SHA-256 と同じか。"""
    out = {}
    for lg in ("scripts/results/R2X_genka_nta/forms/fetch_log.json", "scripts/results/R2X_genka_nta/ta2/fetch_log.json",
               "scripts/results/IMPL_jigyo_nta/forms/fetch_log.json"):
        for it in json.loads((ROOT / lg).read_text(encoding="utf-8"))["items"]:
            if it.get("saved", "").endswith(".pdf"):
                p = ROOT / it["saved"]
                out[it["id"]] = {"exists": p.exists(), "matches_record": p.exists() and hashlib.sha256(p.read_bytes()).hexdigest() == it["sha256"]}
    return out


def mode_check():
    res = {"law": [], "same": [], "revs": [], "lookups": [], "rev198": [], "taiyo_revs": [], "nta": [], "nta_meta": [], "beppyo": []}
    for group, sub in ((LAW, "egov"), (LAW2, "egov2")):
        for cid, src, short, asofs, path, frags, *neg in group:
            for a in asofs:
                t = node_at(short, a, path, sub)
                if t is None:
                    res["law"].append({"id": cid, "src": src, "law": short, "asof": a, "path": path, "ok": False, "why": "node not found"})
                    continue
                miss = in_order(t, frags)
                ok = (len(miss) == len(frags)) if neg else not miss
                res["law"].append({"id": cid, "src": src, "law": short, "asof": a, "path": path, "ok": ok, "missing": None if neg else miss, "negated": bool(neg)})
    for cid, src, short, a, b, path, expect_same in SAME:
        ta, tb = node_at(short, a, path), node_at(short, b, path)
        same = ta is not None and ta == tb
        res["same"].append({"id": cid, "src": src, "a": a, "b": b, "path": path, "expect_same": expect_same, "same": same, "ok": ta is not None and same == expect_same})
    for short, a, rid, status in REVS:
        ri = eg(short, a)["revision_info"]
        res["revs"].append({"law": short, "asof": a, "claimed": rid, "got": ri["law_revision_id"], "claimed_status": status, "got_status": ri["current_revision_status"],
                            "ok": ri["law_revision_id"] == rid and (status is None or status == ri["current_revision_status"])})
    lk = json.loads((OUT / "egov_log.json").read_text(encoding="utf-8"))["lookups"]
    for short, (lid, num) in LAW_IDS.items():
        m = lk[short]["exact_title_matches"]
        res["lookups"].append({"law": short, "claimed": lid, "got": m, "ok": any(x["law_id"] == lid and (num is None or x["law_num"] == num) for x in m)})
    rv = json.loads((OUT / "revs.json").read_text(encoding="utf-8"))
    got = {r["law_revision_id"]: r for r in rv["rei198_by_revision"]}
    for rid, ed, amend, conj in REV198:
        g = got.get(rid)
        res["rev198"].append({"id": rid, "ok": bool(g) and g["enforcement"] == ed and g["amend"] == amend and set(g["198_conj_all"]) == {conj},
                              "got": None if not g else [g["enforcement"], g["amend"], g["198_conj_all"]]})
    res["rev198_extra_in_range"] = sorted(set(got) - {x[0] for x in REV198})
    tr = rv["revisions"]["taiyo"]["in_2025_2030"]
    for ed, amend in TAIYO_REVS:
        res["taiyo_revs"].append({"enforcement": ed, "amend": amend, "ok": any(r["amendment_enforcement_date"] == ed and r["amendment_law_num"] == amend for r in tr)})
    res["taiyo_revs_count_2025_2030"] = len(tr)
    for cid, src, page, frags, *neg in NQ:
        name = f"{page[:-6]}.links.json" if page.endswith(".links") else f"{page}.txt"
        miss = in_order((OUT / "nta" / name).read_text(encoding="utf-8"), frags)
        ok = (len(miss) == len(frags)) if neg else not miss
        res["nta"].append({"id": cid, "src": src, "page": page, "ok": ok, "missing": None if neg else miss, "negated": bool(neg)})
    log = {it["id"]: it for it in json.loads((OUT / "nta_log.json").read_text(encoding="utf-8"))["items"]}
    for aid, vid, lm, sha16 in NTA_META:
        it = log[vid]
        lmd = dt.datetime.strptime(it["last_modified"], "%a, %d %b %Y %H:%M:%S GMT").date().isoformat() if it.get("last_modified") else None
        res["nta_meta"].append({"id": aid, "url": it["url"], "claimed_lm": lm, "got_lm": lmd, "claimed_sha16": sha16, "got_sha16": it["sha256"][:16],
                                "ok": it["status"] == 200 and it["sha256"].startswith(sha16) and (lm is None or lm == lmd)})
    res["pdf_flags"] = {k: {"Encrypt": log[k].get("pdf_has_Encrypt"), "ToUnicode": log[k].get("pdf_ToUnicode_count")} for k in ("pdf_037", "pdf_003", "pdf_034", "pdf_kichou09")}
    rb = json.loads((OUT / "nta_robots.json").read_text(encoding="utf-8"))
    res["robots"] = {"sha256": rb["sha256"], "all_allowed": all(rb["allowed"].values()),
                     "same_as_author": rb["sha256"] == "a5f4e421e5bb2b20563fa568d7ee4d7c6a41afa72ef8bb96cd35510ebe6d8528"}
    res["kichou09_link_texts"] = [x["text"] for p in sorted((OUT / "nta2").glob("*.links.json"))
                                  for x in json.loads(p.read_text(encoding="utf-8")) if x["href"].endswith("kichou09.pdf")]
    res["kichou09_meta"] = {"last_modified": log["pdf_kichou09"]["last_modified"], "bytes": log["pdf_kichou09"]["bytes"], "KiB": round(log["pdf_kichou09"]["bytes"] / 1024)}
    for bid, src, prefix, anchor, exp in BEPPYO:
        for a in (R7, R8):
            t = table("taiyo", a, prefix)
            pos = find_rows(t, anchor)
            ok, gotr = bool(pos), []
            if pos:
                for off, kw, yrs in exp:
                    det, y = row_detail_years(t, pos[0] + off)
                    gotr.append([off, det, y])
                    ok = ok and kw in det and y == yrs
            res["beppyo"].append({"id": bid, "src": src, "asof": a, "ok": ok, "anchor_rows": pos, "got": gotr})
    res["suppl198"] = [(h["amend"], h["num"]) for h in json.loads((OUT / "egov2" / "shotoku-rei_2026-12-31_suppl198.json").read_text(encoding="utf-8"))["suppl_articles_with_198_or_sontsu"]]
    res["beppyo5"] = {a: [[unicodedata.normalize("NFKC", c["text"]) for c in r][:3] for r in eg("shotoku", a, "egov2")["appdx"][0]["rows"]
                          if any("控除した金額" in c["text"] for c in r[:3])][:1] for a in (R7, R8)}
    res["calc"] = calc()
    res["docs"] = doc_checks()
    res["author_pdf_hashes"] = author_pdf_hashes()
    summ = {k: {"n": len(v), "ng": sum(1 for x in v if not x["ok"])} for k, v in res.items()
            if isinstance(v, list) and v and isinstance(v[0], dict) and "ok" in v[0]}
    res["summary"] = summ
    (OUT / "check.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    L = ["# R2X genka verify check（自動生成。scripts/R2X_genka_verify.py check）", "", "## 件数", ""]
    L += [f"- {k}: {v['n']} 件、うち不一致 {v['ng']} 件" for k, v in summ.items()]
    L += ["", "## 不一致（ok=false）", ""]
    for k in summ:
        L += [f"- {k}: {json.dumps(x, ensure_ascii=False, default=str)}" for x in res[k] if not x["ok"]]
    L += ["", "## 計算の再現", "", "```json", json.dumps(res["calc"], ensure_ascii=False, indent=1, default=str), "```", "",
          "## 文書の検査", "", "```json", json.dumps(res["docs"], ensure_ascii=False, indent=1), "```", "", "## その他", "", "```json",
          json.dumps({k: res[k] for k in ("robots", "pdf_flags", "kichou09_link_texts", "kichou09_meta", "suppl198", "beppyo5",
                                          "rev198_extra_in_range", "taiyo_revs_count_2025_2030", "author_pdf_hashes")}, ensure_ascii=False, indent=1), "```"]
    (OUT / "check.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("done", json.dumps(summ, ensure_ascii=False))


def main():
    m = sys.argv[1] if len(sys.argv) > 1 else "check"
    OUT.mkdir(parents=True, exist_ok=True)
    if m == "egov":
        mode_egov()
    elif m == "egov2":
        mode_egov2()
    elif m == "revs":
        mode_revs()
    elif m == "nta":
        mode_nta()
    elif m == "nta2":
        mode_nta(PAGES2, "nta2")
    elif m == "check":
        mode_check()
    else:
        raise SystemExit("mode は egov / egov2 / revs / nta / nta2 / check")


if __name__ == "__main__":
    main()

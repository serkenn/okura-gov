"""R2X aoiro 独立検証（反証役）: 青色申告のトピックの文書に書かれた条番号・項号・数値・施行日・適用年分・URL・版を、
一次情報に自分で当たり直して確かめる。担当のスクリプト（R2X_aoiro_laws/nta/pdftext/checks.py）と出力は使わない
（比較のために担当の出力のハッシュ・値を読むのは check モードだけ）。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_aoiro_verify.py egov
      e-Gov 法令API v2：/laws?law_title= で law_id を引き直し、/law_data/<law_id>?asof= で各時点の本文を取り、
      対象の条を「条→項→号→細目」の構造のまま JSON にする。対象の改正法令の附則（AmendLawNum で選ぶ）も構造で取り出す。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_aoiro_verify.py rev
      /law_revisions：措法（2027-01-01 施行の改正法令ごとの版の第25条の2）、所令（2026-01-01〜2027-01-01 施行の版の
      第165条・第198条。どの改正政令で文言が変わったかを特定する）、所規（第36条の4・55・66 を改めた版）。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_aoiro_verify.py nta
      先に https://www.nta.go.jp/robots.txt を取得・判定し（許されない URL があれば中止）、国税庁の HTML（テキスト化）と
      PDF（保存とハッシュだけ）を取得する。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_aoiro_verify.py pdf <名前>=<PDFのパス> ...
      青色申告決算書（一般用・現金主義用）の PDF（AESV2、空のユーザーパスワード）を自前の実装で復号し、ページごとの
      文字列と位置（Tm/Td の平行移動だけを追う近似）を取り出す。担当の R2X_aoiro_pdftext.py は使わない。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_aoiro_verify.py egov2
      法人税法施行規則 第53条（電帳規2① の括弧書きの「同法」が受ける法律の帳簿の原則を読む）。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_aoiro_verify.py nta2
      robots.txt を判定してから、質疑応答事例2件（TA No.2075 のリンク先）と TA の分野別一覧（個人事業）を取得する。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_aoiro_verify.py check
      ネットワークを使わず、上の出力だけから、文書の主張（引用・項号・金額・版・施行日・Last-Modified・SHA-256）を突き合わせ、
      推測の文書の計算例を担当とは別に書いた式で計算し直す。

- ダウンロードしたものは信頼できないデータ。取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_R2X_aoiro_verify_<mode>/ に置き、その中でインタプリタやツールは実行しない。
- 出力は scripts/results/R2X_aoiro_verify/。
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。個人の情報は送らない。官報は取得しない。
"""
import datetime as dt
import hashlib
import html.parser
import json
import pathlib
import re
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import zlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "results" / "R2X_aoiro_verify"
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
WAIT = 1.5
TODAY = "2026-11-09"
R7, R8, R9 = "2025-12-31", "2026-12-31", "2027-01-01"

# 略称: (法令名, 担当が書いた law_id, [asof], [本則の条 Num], [附則を取り出す改正法令（AmendLawNum の正規表現）])
LAWS = {
    "shotoku": ("所得税法", "340AC0000000033", [R7, R8, R9],
                ["2", "56", "57", "67", "69", "70", "70_2", "84_2", "120", "123", "140", "141", "142", "143", "144", "145", "146",
                 "147", "148", "149", "150", "151", "155", "166", "232"],
                [r"令和五年.*法律第三号", r"令和七年.*法律第一三号", r"令和八年.*法律第一二号"]),
    "shotoku-rei": ("所得税法施行令", "340CO0000000096", [R7, R8, R9],
                    ["164", "165", "166", "167", "195", "196", "197", "198", "201", "271", "272"], [r"令和八年.*政令"]),
    "shotoku-ki": ("所得税法施行規則", "340M50000040011", [R7, R8, R9, TODAY],
                   ["36_4", "39_2", "40", "40_2", "48", "54", "55", "56", "57", "58", "59", "60", "61", "62", "63", "64",
                    "65", "66", "67"],
                   [r"令和五年.*財務省令第一二号"]),
    "sochi": ("租税特別措置法", "332AC0000000026", [R7, R8, R9], ["25_2", "26"],
              [r"令和七年.*法律第一三号", r"令和八年.*法律第一二号"]),
    "sochi-ki": ("租税特別措置法施行規則", "332M50000040015", [R7, R8, R9], ["9_6"],
                 [r"令和七年.*財務省令第二六号", r"令和八年.*財務省令第二一号"]),
    "denchou": ("電子計算機を使用して作成する国税関係帳簿書類の保存方法等の特例に関する法律", "410AC0000000025",
                [R7, R8, R9], ["2", "4", "5", "8"], []),
    "denchou-ki": ("電子計算機を使用して作成する国税関係帳簿書類の保存方法等の特例に関する法律施行規則", "410M50000040043",
                   [R7, R8, R9], ["2", "3", "5"], []),
    "tsusoku": ("国税通則法", "337AC0000000066", [R7], ["10"], []),
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
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_aoiro_verify_{mode}"
    dl.mkdir(parents=True, exist_ok=False)
    return ts, dl


def rel(p):
    return str(pathlib.Path(p).relative_to(ROOT)).replace("\\", "/")


def wjson(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- e-Gov（構造のまま取り出す。担当の render は使わない）
def flat(n):
    if isinstance(n, str):
        return n
    if n.get("tag") == "Rt":
        return ""
    return "".join(flat(c) for c in n.get("children", []))


def kids(n, tag=None):
    return [c for c in n.get("children", []) if isinstance(c, dict) and (tag is None or c.get("tag") == tag)]


SUBTAGS = ("Item",) + tuple(f"Subitem{i}" for i in range(1, 11))


def node(n):
    """Paragraph / Item / SubitemN → {num, head, own, full, ch:{num: node}}。Num 属性で子を引く。"""
    head = "".join(flat(c) for c in kids(n) if c.get("tag", "").endswith(("Num", "Title")) and c.get("tag") != "ParagraphCaption")
    own = "".join(flat(c) for c in kids(n) if c.get("tag", "").endswith("Sentence"))
    ch = {}
    for c in kids(n):
        if c.get("tag") in SUBTAGS:
            ch[c.get("attr", {}).get("Num", str(len(ch) + 1))] = node(c)
    return {"num": n.get("attr", {}).get("Num"), "head": head, "own": own, "full": flat(n), "ch": ch}


def article(a):
    return {"num": a.get("attr", {}).get("Num"), "caption": "".join(flat(c) for c in kids(a, "ArticleCaption")),
            "title": "".join(flat(c) for c in kids(a, "ArticleTitle")), "full": flat(a),
            "ch": {p.get("attr", {}).get("Num"): node(p) for p in kids(a, "Paragraph")}}


def walk(n, fn, path=()):
    if isinstance(n, dict):
        fn(n, path)
        for c in n.get("children", []):
            walk(c, fn, path + (n.get("tag"),))


def rev_info(d):
    ri = d.get("revision_info") or {}
    return {k: ri.get(k) for k in ("law_revision_id", "amendment_law_num", "amendment_law_title", "amendment_enforcement_date",
                                   "amendment_promulgate_date", "current_revision_status", "updated")}


def extract(d, nums, suppl_res):
    main, suppl = {}, {}

    def f(n, path):
        if n.get("tag") == "Article" and "SupplProvision" not in path and n.get("attr", {}).get("Num") in nums:
            main[n["attr"]["Num"]] = article(n)
        if n.get("tag") == "SupplProvision":
            an = n.get("attr", {}).get("AmendLawNum") or ""
            if any(re.search(r, an) for r in suppl_res):
                arts = {}
                walk(n, lambda x, p: arts.__setitem__(x["attr"].get("Num"), article(x)) if x.get("tag") == "Article" else None)
                if not arts:  # 条のない附則（項だけ）
                    arts["_paras"] = {"full": flat(n)}
                suppl.setdefault(an, []).append(arts)
    walk(d["law_full_text"], f)
    return main, suppl


def mode_egov():
    ts, dl = new_dl("egov")
    log = {"run_at": ts, "download_dir": rel(dl), "lookups": {}, "fetches": []}
    for i, (short, (title, claimed, asofs, nums, sre)) in enumerate(LAWS.items(), 1):
        url = f"{API}/laws?" + urllib.parse.urlencode({"law_title": title, "response_format": "json", "asof": TODAY})
        st, body, _ = http_get(url, "application/json")
        (dl / f"{i:02d}_laws_{short}.json").write_bytes(body)
        found = []
        try:
            for law in json.loads(body).get("laws", []):
                rv = law.get("current_revision_info") or law.get("revision_info") or {}
                if rv.get("law_title") == title:
                    found.append({"law_id": law["law_info"]["law_id"], "law_num": law["law_info"].get("law_num")})
        except Exception as e:  # noqa: BLE001
            found.append({"error": repr(e)})
        log["lookups"][short] = {"title": title, "url": url, "status": st, "matches": found, "claimed": claimed,
                                 "claimed_ok": any(x.get("law_id") == claimed for x in found)}
        print("lookup", short, found, flush=True)
        for asof in asofs:
            furl = f"{API}/law_data/{claimed}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
            st, body, _ = http_get(furl, "application/json")
            raw = dl / f"{short}_{asof}.json"
            raw.write_bytes(body)
            if st != 200:
                log["fetches"].append({"short": short, "asof": asof, "url": furl, "status": st})
                print("ERR", short, asof, st, flush=True)
                continue
            d = json.loads(body)
            main, suppl = extract(d, nums, sre)
            rec = {"short": short, "asof": asof, "url": furl, "status": st, "raw": rel(raw),
                   "sha256": hashlib.sha256(body).hexdigest(), "law_num": (d.get("law_info") or {}).get("law_num"),
                   "revision_info": rev_info(d), "missing": [x for x in nums if x not in main],
                   "suppl_keys": sorted(suppl)}
            wjson(OUT / "egov" / f"{short}_{asof}.json", {**rec, "main": main, "suppl": suppl})
            log["fetches"].append(rec)
            print("ok", short, asof, rec["revision_info"]["law_revision_id"], rec["missing"], rec["suppl_keys"], flush=True)
    wjson(OUT / "egov_log.json", log)


def fetch_revisions(dl, law_id, tag):
    url = f"{API}/law_revisions/{law_id}?" + urllib.parse.urlencode({"response_format": "json"})
    st, body, _ = http_get(url, "application/json")
    (dl / f"revisions_{tag}.json").write_bytes(body)
    revs = [{k: r.get(k) for k in ("law_revision_id", "amendment_promulgate_date", "amendment_enforcement_date",
                                   "amendment_scheduled_enforcement_date", "amendment_law_num", "amendment_law_title",
                                   "current_revision_status", "updated")} for r in json.loads(body).get("revisions", [])]
    return url, hashlib.sha256(body).hexdigest(), revs


def fetch_rev_articles(dl, rid, nums, sre=()):
    u = f"{API}/law_data/{rid}?" + urllib.parse.urlencode({"response_format": "json"})
    st, body, _ = http_get(u, "application/json")
    (dl / f"{rid}.json").write_bytes(body)
    if st != 200:
        return {"law_revision_id": rid, "status": st}
    d = json.loads(body)
    main, suppl = extract(d, nums, sre)
    return {"law_revision_id": rid, "url": u, "status": st, "sha256": hashlib.sha256(body).hexdigest(),
            "revision_info": rev_info(d), "main": main, "suppl": suppl}


def mode_rev():
    ts, dl = new_dl("rev")
    res = {"run_at": ts, "download_dir": rel(dl)}
    # 措法：施行日 2026-12-04〜2027-01-01 の版の第25条の2
    url, sha, revs = fetch_revisions(dl, "332AC0000000026", "sochi")
    res["sochi"] = {"url": url, "sha256": sha, "revisions": [r for r in revs if "2025-12-31" <= (r["amendment_enforcement_date"] or "9999") <= "2027-01-01"
                                                             or r["amendment_enforcement_date"] is None]}
    picks = [r["law_revision_id"] for r in revs if (r["amendment_enforcement_date"] or "") == "2027-01-01"]
    picks += [r["law_revision_id"] for r in revs if r["law_revision_id"].startswith("332AC0000000026_20261204")]
    res["sochi"]["versions"] = []
    for rid in picks:
        v = fetch_rev_articles(dl, rid, ["25_2"], [r"令和八年.*法律第一二号", r"令和七年.*法律第一三号"])
        res["sochi"]["versions"].append(v)
        print("ok sochi", rid, flush=True)
    # 所令：施行日 2025-12-01〜2027-01-01 の版の第165条・第198条
    url, sha, revs = fetch_revisions(dl, "340CO0000000096", "shotoku-rei")
    sel = [r for r in revs if "2025-12-01" <= (r["amendment_enforcement_date"] or "") <= "2027-01-01"]
    res["shotoku-rei"] = {"url": url, "sha256": sha, "revisions": sel, "versions": []}
    for r in sel:
        v = fetch_rev_articles(dl, r["law_revision_id"], ["165", "198"], [r"令和八年.*政令", r"令和七年.*政令"])
        res["shotoku-rei"]["versions"].append(v)
        print("ok rei", r["law_revision_id"], flush=True)
    # 所規：/law_revisions の一覧だけ（版の施行日と改正省令）
    url, sha, revs = fetch_revisions(dl, "340M50000040011", "shotoku-ki")
    res["shotoku-ki"] = {"url": url, "sha256": sha,
                         "revisions": [r for r in revs if "2025-06-01" <= (r["amendment_enforcement_date"] or "") <= "2027-12-31"]}
    # 所法：/law_revisions の一覧だけ
    url, sha, revs = fetch_revisions(dl, "340AC0000000033", "shotoku")
    res["shotoku"] = {"url": url, "sha256": sha,
                      "revisions": [r for r in revs if "2025-06-01" <= (r["amendment_enforcement_date"] or "") <= "2027-12-31"]}
    # 措規：/law_revisions の一覧だけ
    url, sha, revs = fetch_revisions(dl, "332M50000040015", "sochi-ki")
    res["sochi-ki"] = {"url": url, "sha256": sha,
                       "revisions": [r for r in revs if "2025-06-01" <= (r["amendment_enforcement_date"] or "9999") <= "2027-12-31"
                                     or r["amendment_enforcement_date"] is None]}
    wjson(OUT / "rev.json", res)


# ---------------------------------------------------------------- 国税庁
NTA = "https://www.nta.go.jp"
TA = NTA + "/taxes/shiraberu/taxanswer/shotoku/"
KIHON = NTA + "/law/tsutatsu/kihon/shotoku/"
ANNAI = NTA + "/taxes/tetsuzuki/shinsei/annai/shinkoku/annai/"
SPDF = NTA + "/taxes/tetsuzuki/shinsei/annai/shinkoku/pdf/"
YPDF = NTA + "/taxes/shiraberu/shinkoku/yoshiki/01/shinkokusho/pdf/r07/"
TPDF = NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/pdf/"
PAGES = {
    "ta_2070": TA + "2070.htm", "ta_2072": TA + "2072.htm", "ta_2075": TA + "2075.htm", "ta_2250": TA + "2250.htm",
    "kihon_11_01": KIHON + "11/01.htm", "kihon_14_02": KIHON + "14/02.htm", "kihon_15_01": KIHON + "15/01.htm",
    "kihon_19_02": KIHON + "19/02.htm", "kihon_20_01": KIHON + "20/01.htm",
    "sochitsu_25_2": NTA + "/law/tsutatsu/kobetsu/shotoku/sochiho/801226/sinkoku/57/25/01.htm",
    "mokuji": NTA + "/taxes/tetsuzuki/shinsei/annai/shinkoku/mokuji.htm",
    "annai_09": ANNAI + "09.htm", "annai_09_2": ANNAI + "09_2.htm", "annai_10": ANNAI + "10.htm", "annai_12": ANNAI + "12.htm",
    "annai_13": ANNAI + "13.htm", "annai_17_0": ANNAI + "17_0.htm", "annai_23200002": ANNAI + "23200002.htm",
    "annai_23200008": ANNAI + "23200008.htm", "annai_23200010": ANNAI + "23200010.htm",
    "annai_23200011": ANNAI + "23200011.htm", "annai_23200016": ANNAI + "23200016.htm",
    "yoshiki_r07": NTA + "/taxes/shiraberu/shinkoku/syotoku/r07.htm",
    "pdf_kessan_ippan": YPDF + "10.pdf", "pdf_kessan_genkin": YPDF + "13.pdf", "pdf_dai4": YPDF + "03.pdf",
    "pdf_kakikata_037": TPDF + "037.pdf", "pdf_tebiki_025": TPDF + "025.pdf", "pdf_sonshitsu_003": TPDF + "003.pdf",
    "pdf_shinsei": SPDF + "h28/10.pdf", "pdf_shinsei_ki": SPDF + "h28/10-ki.pdf", "pdf_shinsei_genkin": SPDF + "h28/11.pdf",
    "pdf_yame": SPDF + "h28/12.pdf", "pdf_yame_ki": SPDF + "h28/12-ki.pdf", "pdf_senju": SPDF + "h28/13_14.pdf",
    "pdf_senju_ki": SPDF + "h28/13_14-ki.pdf", "pdf_genkin": SPDF + "h28/15.pdf", "pdf_65man": SPDF + "r03/01.pdf",
    "pdf_65man_ki": SPDF + "r03/01-ki.pdf", "pdf_kurimodoshi": SPDF + "03_r05.pdf", "pdf_kurimodoshi_ki": SPDF + "03_r05-ki.pdf",
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


def mode_nta():
    ts, dl = new_dl("nta")
    out = OUT / "nta"
    out.mkdir(parents=True, exist_ok=True)
    st, body, _ = http_get(NTA + "/robots.txt")
    (dl / "robots.txt").write_bytes(body)
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(body.decode("utf-8", "replace").splitlines())
    robots = {"fetched_at": ts, "status": st, "sha256": hashlib.sha256(body).hexdigest(), "saved": rel(dl / "robots.txt"),
              "disallow": [x.strip() for x in body.decode("utf-8", "replace").splitlines() if x.strip().lower().startswith("disallow")],
              "allowed": {k: rp.can_fetch(UA, u) for k, u in PAGES.items()}}
    wjson(OUT / "nta_robots.json", robots)
    if not all(robots["allowed"].values()):
        print("robots.txt で許されない URL がある。中止", [k for k, v in robots["allowed"].items() if not v])
        return
    log = {"run_at": ts, "download_dir": rel(dl), "items": []}
    for key, url in PAGES.items():
        try:
            st, body, hd = http_get(url)
        except Exception as e:  # noqa: BLE001
            log["items"].append({"id": key, "url": url, "error": repr(e)})
            print("ERR", key, repr(e), flush=True)
            continue
        ctype = hd.get("Content-Type", "")
        is_pdf = url.lower().endswith(".pdf")
        fn = dl / (key + (".pdf" if is_pdf else ".htm"))
        fn.write_bytes(body)
        it = {"id": key, "url": url, "status": st, "content_type": ctype, "last_modified": hd.get("Last-Modified"),
              "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(), "saved": rel(fn)}
        if is_pdf:
            it["pdf_header"] = body[:8].decode("latin-1")
            m = re.search(rb"/Filter\s*/Standard.{0,400}", body, re.S)
            it["encrypt_dict_head"] = m.group(0)[:200].decode("latin-1", "replace") if m else None
        elif st == 200:
            txt, enc = decode_html(body, ctype)
            p = TextOf(url)
            p.feed(txt)
            it["encoding"] = enc
            tm = re.search(r"<title>(.*?)</title>", txt, re.S)
            it["title"] = re.sub(r"\s+", " ", tm.group(1)).strip() if tm else None
            (out / f"{key}.txt").write_text(p.text() + "\n", encoding="utf-8")
            wjson(out / f"{key}.links.json", p.links)
        log["items"].append(it)
        print("ok", key, st, len(body), hd.get("Last-Modified"), flush=True)
    wjson(OUT / "nta_log.json", log)


# ---------------------------------------------------------------- PDF（自前の実装。AESV2・空のユーザーパスワードだけを扱う）
def _mul2(x):
    x <<= 1
    return (x ^ 0x11B) if x & 0x100 else x


def _gf(a, b):
    p = 0
    for _ in range(8):
        if b & 1:
            p ^= a
        a = _mul2(a)
        b >>= 1
    return p


def _make_sbox():
    # 乗法逆元は a^254（GF(2^8)）で求める
    def inv(a):
        if a == 0:
            return 0
        r, e, base = 1, 254, a
        while e:
            if e & 1:
                r = _gf(r, base)
            base = _gf(base, base)
            e >>= 1
        return r
    sb = []
    for a in range(256):
        b = inv(a)
        s = b
        for k in range(1, 5):
            s ^= ((b << k) | (b >> (8 - k))) & 0xFF
        sb.append(s ^ 0x63)
    isb = [0] * 256
    for i, v in enumerate(sb):
        isb[v] = i
    return sb, isb


SB, ISB = _make_sbox()


def _key_schedule(key):
    rc = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36]
    w = [list(key[4 * i:4 * i + 4]) for i in range(4)]
    for i in range(4, 44):
        t = w[i - 1][:]
        if i % 4 == 0:
            t = [SB[t[1]] ^ rc[i // 4 - 1], SB[t[2]], SB[t[3]], SB[t[0]]]
        w.append([a ^ b for a, b in zip(w[i - 4], t)])
    return [[w[4 * r + c][j] for c in range(4) for j in range(4)] for r in range(11)]  # 列優先の16バイト


def _inv_block(rk, blk):
    st = [b ^ k for b, k in zip(blk, rk[10])]
    for r in range(9, -1, -1):
        # InvShiftRows（状態は列優先：st[4*c + row]）
        st = [st[4 * ((c - row) % 4) + row] for c in range(4) for row in range(4)]
        st = [ISB[x] for x in st]
        st = [x ^ k for x, k in zip(st, rk[r])]
        if r:
            n = []
            for c in range(4):
                a0, a1, a2, a3 = st[4 * c:4 * c + 4]
                n += [_gf(a0, 14) ^ _gf(a1, 11) ^ _gf(a2, 13) ^ _gf(a3, 9),
                      _gf(a0, 9) ^ _gf(a1, 14) ^ _gf(a2, 11) ^ _gf(a3, 13),
                      _gf(a0, 13) ^ _gf(a1, 9) ^ _gf(a2, 14) ^ _gf(a3, 11),
                      _gf(a0, 11) ^ _gf(a1, 13) ^ _gf(a2, 9) ^ _gf(a3, 14)]
            st = n
    return bytes(st)


def aes_selftest():
    # FIPS-197 Appendix C.1（AES-128）
    k = bytes(range(16))
    ct = bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")
    return _inv_block(_key_schedule(k), ct) == bytes.fromhex("00112233445566778899aabbccddeeff")


def aes_cbc(key, data):
    rk = _key_schedule(key)
    iv, out = data[:16], bytearray()
    for i in range(16, len(data) - (len(data) - 16) % 16, 16):
        b = data[i:i + 16]
        out += bytes(x ^ y for x, y in zip(_inv_block(rk, b), iv))
        iv = b
    if out and 1 <= out[-1] <= 16 and out.endswith(bytes([out[-1]]) * out[-1]):
        out = out[:-out[-1]]
    return bytes(out)


PADPW = bytes.fromhex("28BF4E5E4E758A4164004E56FFFA01082E2E00B6D0683E802F0CA9FE6453697A")


def pdf_string(tok):
    """PDF のリテラル文字列 (...) か 16進 <...> をバイト列に。"""
    if tok.startswith(b"<"):
        h = re.sub(rb"\s", b"", tok[1:-1])
        if len(h) % 2:
            h += b"0"
        return bytes.fromhex(h.decode())
    s, out, i = tok[1:-1], bytearray(), 0
    esc = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12, ord("("): 40, ord(")"): 41, ord("\\"): 92}
    while i < len(s):
        c = s[i]
        if c == 92 and i + 1 < len(s):
            d = s[i + 1]
            if d in esc:
                out.append(esc[d])
                i += 2
            elif 48 <= d <= 55:
                m = re.match(rb"[0-7]{1,3}", s[i + 1:i + 4])
                out.append(int(m.group(0), 8) & 0xFF)
                i += 1 + len(m.group(0))
            elif d in (10, 13):
                i += 2 + (1 if d == 13 and i + 2 < len(s) and s[i + 2] == 10 else 0)
            else:
                out.append(d)
                i += 2
        else:
            out.append(c)
            i += 1
    return bytes(out)


STR_RE = rb"\((?:\\.|[^\\)])*\)|<[0-9A-Fa-f\s]*>"


def pdf_objects(pdf):
    """ファイルを先頭から順に読み、`n g obj … endobj` を取り出す（ストリームの中は /Length の分だけ飛ばす）。"""
    objs, pos = {}, 0
    pat = re.compile(rb"(?<![0-9])(\d+)\s+(\d+)\s+obj\b")
    while True:
        m = pat.search(pdf, pos)
        if not m:
            break
        num, gen = int(m.group(1)), int(m.group(2))
        sm = re.compile(rb"stream\r?\n").search(pdf, m.end())
        em = pdf.find(b"endobj", m.end())
        if sm and (em < 0 or sm.start() < em) and pdf[m.end():sm.start()].rstrip().endswith(b">>"):
            dic = pdf[m.end():sm.start()]
            lm = re.search(rb"/Length\s+(\d+)(\s+\d+\s+R)?", dic)
            if lm and not lm.group(2):
                data = pdf[sm.end():sm.end() + int(lm.group(1))]
                pos = pdf.find(b"endobj", sm.end() + int(lm.group(1)))
            else:
                es = pdf.find(b"endstream", sm.end())
                data = re.sub(rb"\r?\n$", b"", pdf[sm.end():es])
                pos = pdf.find(b"endobj", es)
            objs[num] = (gen, dic, data)
        else:
            objs[num] = (gen, pdf[m.end():em], None)
            pos = em
        if pos < 0:
            break
        pos += 6
    return objs


def expand_objstm(objs, key):
    """/Type /ObjStm の中のオブジェクトを objs に足す（辞書だけ。中のオブジェクトは個別には暗号化されない）。"""
    added = 0
    for num, (gen, dic, data) in list(objs.items()):
        if data is None or not re.search(rb"/Type\s*/ObjStm", dic):
            continue
        raw = obj_decrypt(key, num, gen, data)
        body = inflate(raw) if b"FlateDecode" in dic else raw
        n = int(re.search(rb"/N\s+(\d+)", dic).group(1))
        first = int(re.search(rb"/First\s+(\d+)", dic).group(1))
        hdr = [int(x) for x in body[:first].split()]
        pairs = [(hdr[2 * i], hdr[2 * i + 1]) for i in range(n)]
        for i, (onum, off) in enumerate(pairs):
            end = first + pairs[i + 1][1] if i + 1 < n else len(body)
            if onum not in objs:
                objs[onum] = (0, body[first + off:end], None)
                added += 1
    return added


def pdf_key(pdf, objs):
    tr = re.search(rb"/Encrypt\s+(\d+)\s+0\s+R", pdf)
    if not tr:
        return None, {"encrypted": False}
    _, ed, _ = objs[int(tr.group(1))]
    info = {"encrypted": True, "V": None, "R": None}
    for k in (b"V", b"R", b"P", b"Length"):
        m = re.search(rb"/" + k + rb"\s+(-?\d+)", ed)
        info[k.decode()] = int(m.group(1)) if m else None
    cfm = re.search(rb"/CFM\s*/(\w+)", ed)
    info["CFM"] = cfm.group(1).decode() if cfm else None
    if info["V"] != 4 or info["CFM"] != "AESV2":
        info["unsupported"] = True
        return None, info

    def get_str(name):
        m = re.search(rb"/" + name + rb"\s*(" + STR_RE + rb")", ed, re.S)
        return pdf_string(m.group(1))
    O, U = get_str(b"O")[:32], get_str(b"U")[:32]
    idm = re.search(rb"/ID\s*\[\s*(" + STR_RE + rb")", pdf, re.S)
    ID0 = pdf_string(idm.group(1))
    P = struct.pack("<i", info["P"])
    h = hashlib.md5(PADPW + O + P + ID0)
    if re.search(rb"/EncryptMetadata\s+false", ed):
        h.update(b"\xff\xff\xff\xff")
    key = h.digest()
    n = 16  # V4・AESV2 の鍵は128ビット（/CF の /Length はバイト数、最上位の /Length はビット数で、どちらが先に現れるかに依存しない）
    for _ in range(50):
        key = hashlib.md5(key[:n]).digest()
    key = key[:n]
    # 鍵の検査（R3 以上：U の先頭16バイト = RC4^20(MD5(PAD+ID0))）
    x = hashlib.md5(PADPW + ID0).digest()
    for i in range(20):
        x = rc4(bytes(b ^ i for b in key), x)
    info["key_ok"] = (x == U[:16])
    return key, info


def rc4(key, data):
    S = list(range(256))
    j = 0
    for i in range(256):
        j = (j + S[i] + key[i % len(key)]) & 255
        S[i], S[j] = S[j], S[i]
    i = j = 0
    out = bytearray()
    for b in data:
        i = (i + 1) & 255
        j = (j + S[i]) & 255
        S[i], S[j] = S[j], S[i]
        out.append(b ^ S[(S[i] + S[j]) & 255])
    return bytes(out)


def obj_decrypt(key, num, gen, data):
    if key is None:
        return data
    k = hashlib.md5(key + struct.pack("<i", num)[:3] + struct.pack("<i", gen)[:2] + b"sAlT").digest()[:min(len(key) + 5, 16)]
    return aes_cbc(k, data)


def inflate(b):
    d = zlib.decompressobj()
    out = d.decompress(b, 64 * 1024 * 1024)
    if d.unconsumed_tail:
        raise ValueError("展開の上限を超えた")
    return out


def page_streams(pdf, objs, key):
    """ページ（/Type /Page）ごとの内容ストリーム（展開済み）と、フォント名 → エンコーディング。オブジェクトストリームは扱わない。"""
    pages = []

    def order():
        # ページツリー（/Type /Pages の /Kids）を根からたどって、表示の順にページのオブジェクト番号を並べる
        roots = [n for n, (g, d, s) in objs.items() if re.search(rb"/Type\s*/Pages\b", d) and not re.search(rb"/Parent\s", d)]
        seq = []

        def visit(n):
            d = objs[n][1]
            if re.search(rb"/Type\s*/Pages\b", d):
                km = re.search(rb"/Kids\s*\[([^\]]*)\]", d)
                for k in re.findall(rb"(\d+)\s+\d+\s+R", km.group(1)):
                    visit(int(k))
            else:
                seq.append(n)
        for r in roots:
            visit(r)
        return seq
    for num in order():
        gen, dic, data = objs[num]
        if re.search(rb"/Type\s*/Page\b", dic):
            cm = re.search(rb"/Contents\s*(\[[^\]]*\]|\d+\s+\d+\s+R)", dic)
            refs = [int(x) for x in re.findall(rb"(\d+)\s+\d+\s+R", cm.group(1))] if cm else []
            content = b""
            for r in refs:
                g, d2, s2 = objs[r]
                raw = obj_decrypt(key, r, g, s2)
                content += (inflate(raw) if b"FlateDecode" in d2 else raw) + b"\n"
            # フォント
            fonts = {}
            rm = re.search(rb"/Resources\s*(\d+)\s+\d+\s+R", dic)
            res = objs[int(rm.group(1))][1] if rm else dic
            fm = re.search(rb"/Font\s*(<<.*?>>|\d+\s+\d+\s+R)", res, re.S)
            if fm:
                fd = fm.group(1)
                if fd.endswith(b"R"):
                    fd = objs[int(fd.split()[0])][1]
                for name, fr in re.findall(rb"/(\w+)\s+(\d+)\s+\d+\s+R", fd):
                    em = re.search(rb"/Encoding\s*/([\w\-]+)", objs[int(fr)][1])
                    fonts[name.decode()] = em.group(1).decode() if em else "?"
            pages.append({"obj": num, "content": content, "fonts": fonts})
    return pages


TOK = re.compile(rb"\((?:\\.|[^\\)])*\)|<[0-9A-Fa-f\s]*>|\[|\]|/[^\s/\[\]()<>]+|-?\d*\.?\d+|[A-Za-z'\"*]+")


def page_text(content, fonts):
    rows, stack, font, x, y, lx, ly = [], [], None, 0.0, 0.0, 0.0, 0.0
    arr = None
    for m in TOK.finditer(content):
        t = m.group(0)
        if t == b"[":
            arr = []
            continue
        if t == b"]":
            stack.append(arr)
            arr = None
            continue
        if arr is not None:
            arr.append(t)
            continue
        if re.fullmatch(rb"-?\d*\.?\d+", t) or t.startswith((b"(", b"<", b"/")):
            stack.append(t)
            continue
        op = t
        try:
            if op == b"BT":
                x = y = lx = ly = 0.0
            elif op == b"Tf":
                font = stack[-2].decode()[1:]
            elif op == b"Tm":
                x, y = float(stack[-2]), float(stack[-1])
                lx, ly = x, y
            elif op in (b"Td", b"TD"):
                lx, ly = lx + float(stack[-2]), ly + float(stack[-1])
                x, y = lx, ly
            elif op in (b"Tj", b"'", b'"'):
                rows.append((round(x, 1), round(y, 1), font, decode_str(pdf_string(stack[-1]), fonts.get(font))))
            elif op == b"TJ":
                parts = [decode_str(pdf_string(s), fonts.get(font)) for s in stack[-1] if s.startswith((b"(", b"<"))]
                rows.append((round(x, 1), round(y, 1), font, "".join(parts)))
        except (IndexError, ValueError, AttributeError):
            pass
        stack = []
    return rows


def decode_str(b, enc):
    if enc and "RKSJ" in enc:
        return b.decode("cp932", "replace")
    if enc and "UCS2" in enc:
        return b.decode("utf-16-be", "replace")
    return b.decode("latin-1")


def mode_pdf(args):
    res = {"aes_selftest": aes_selftest(), "files": {}}
    for a in args:
        name, path = a.split("=", 1)
        pdf = pathlib.Path(path).read_bytes()
        objs = pdf_objects(pdf)
        key, info = pdf_key(pdf, objs)
        rec = {"path": path.replace("\\", "/"), "sha256": hashlib.sha256(pdf).hexdigest(), "encrypt": info}
        if info.get("unsupported"):
            res["files"][name] = rec
            continue
        rec["objstm_added"] = expand_objstm(objs, key)
        pages = page_streams(pdf, objs, key)
        rec["pages"] = len(pages)
        rec["fonts"] = sorted({f"{k}:{v}" for p in pages for k, v in p["fonts"].items()})
        lines = []
        for i, p in enumerate(pages, 1):
            for x, y, f, s in page_text(p["content"], p["fonts"]):
                lines.append([i, x, y, f, s])
        rec["rows"] = len(lines)
        (OUT / "pdf").mkdir(parents=True, exist_ok=True)
        (OUT / "pdf" / f"{name}.tsv").write_text("\n".join("\t".join(map(str, r)) for r in lines) + "\n", encoding="utf-8")
        res["files"][name] = rec
        print("pdf", name, info, rec.get("pages"), rec.get("rows"), flush=True)
    wjson(OUT / "pdf_summary.json", res)


# ---------------------------------------------------------------- 追加の取得（検証の途中で要った一次情報）
def mode_egov2():
    """法人税法施行規則 第53条（電帳規2①の括弧書きの「同法」がどの法律の帳簿を指すかの確認のため、法人税法側の帳簿の原則を読む）。"""
    ts, dl = new_dl("egov2")
    title, law_id = "法人税法施行規則", "340M50000040012"
    url = f"{API}/laws?" + urllib.parse.urlencode({"law_title": title, "response_format": "json", "asof": TODAY})
    st, body, _ = http_get(url, "application/json")
    (dl / "laws_hojin-ki.json").write_bytes(body)
    found = [{"law_id": x["law_info"]["law_id"], "law_num": x["law_info"].get("law_num")} for x in json.loads(body).get("laws", [])
             if (x.get("current_revision_info") or x.get("revision_info") or {}).get("law_title") == title]
    furl = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": R7})
    st, body, _ = http_get(furl, "application/json")
    (dl / f"hojin-ki_{R7}.json").write_bytes(body)
    d = json.loads(body)
    main, _ = extract(d, ["53"], [])
    wjson(OUT / "egov" / f"hojin-ki_{R7}.json", {"short": "hojin-ki", "asof": R7, "url": furl, "lookup": found, "claimed": law_id,
                                                "sha256": hashlib.sha256(body).hexdigest(), "revision_info": rev_info(d),
                                                "main": main, "suppl": {}, "download_dir": rel(dl)})
    print("ok hojin-ki", found, rev_info(d)["law_revision_id"], list(main))


PAGES2 = {
    "shitsugi_04_10": NTA + "/law/shitsugi/shotoku/04/10.htm",   # 年の中途で事業に従事した親族に係る青色事業専従者給与（TA No.2075 のリンク）
    "shitsugi_04_09": NTA + "/law/shitsugi/shotoku/04/09.htm",   # 区画整理事業により休業する期間の青色事業専従者給与（同）
    "ta_bunya_kojinjigyo": NTA + "/taxes/shiraberu/taxanswer/code/bunya-kojinjigyo.htm",  # TA 分野別一覧（個人事業）。[M]§3.2 の主張の確認
}


def mode_nta2():
    global PAGES
    PAGES, saved = PAGES2, PAGES
    try:
        ts, dl = new_dl("nta2")
        st, body, _ = http_get(NTA + "/robots.txt")
        (dl / "robots.txt").write_bytes(body)
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(body.decode("utf-8", "replace").splitlines())
        allowed = {k: rp.can_fetch(UA, u) for k, u in PAGES2.items()}
        wjson(OUT / "nta2_robots.json", {"fetched_at": ts, "sha256": hashlib.sha256(body).hexdigest(), "allowed": allowed})
        if not all(allowed.values()):
            print("robots.txt で許されない URL がある。中止")
            return
        log = {"run_at": ts, "download_dir": rel(dl), "items": []}
        for key, url in PAGES2.items():
            st, body, hd = http_get(url)
            fn = dl / f"{key}.htm"
            fn.write_bytes(body)
            it = {"id": key, "url": url, "status": st, "last_modified": hd.get("Last-Modified"), "bytes": len(body),
                  "sha256": hashlib.sha256(body).hexdigest(), "saved": rel(fn)}
            if st == 200:
                txt, enc = decode_html(body, hd.get("Content-Type", ""))
                p = TextOf(url)
                p.feed(txt)
                (OUT / "nta" / f"{key}.txt").write_text(p.text() + "\n", encoding="utf-8")
                wjson(OUT / "nta" / f"{key}.links.json", p.links)
            log["items"].append(it)
            print("ok", key, st, hd.get("Last-Modified"), flush=True)
        wjson(OUT / "nta2_log.json", log)
    finally:
        PAGES = saved


# ---------------------------------------------------------------- 照合（check）
_TR = str.maketrans("０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ"
                    "（）－−―‐％，．［］・",
                    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz()----%,.[]･")


def nz(s):
    return re.sub(r"[\s　]", "", s or "").translate(_TR)


def seq_in(text, quote):
    """quote を「…」で断片に分け、text の中に順に現れるか（空白・全角半角を正規化）。"""
    t, pos = nz(text), 0
    for frag in re.split(r"…+|・・・", quote):
        f = nz(frag)
        if not f:
            continue
        i = t.find(f, pos)
        if i < 0:
            return False, frag
        pos = i + len(f)
    return True, None


_EG = {}


def eg(short, asof):
    k = (short, asof)
    if k not in _EG:
        p = OUT / "egov" / f"{short}_{asof}.json"
        _EG[k] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    return _EG[k]


def loc_text(short, asof, path):
    d = eg(short, asof)
    if d is None:
        return None
    n = d["main"].get(path[0])
    for k in path[1:]:
        if n is None:
            return None
        n = n["ch"].get(k)
    return None if n is None else n["full"]


def suppl_text(short, asof, amend, art, path=()):
    d = eg(short, asof)
    for an, lst in (d or {}).get("suppl", {}).items():
        if amend not in an:
            continue
        for arts in lst:
            n = arts.get(art)
            if n is None:
                continue
            for k in path:
                n = n["ch"].get(k) if n else None
            if n is not None:
                return n["full"]
    return None


def nta_txt(page):
    p = OUT / "nta" / f"{page}.txt"
    return p.read_text(encoding="utf-8") if p.exists() else None


def pdf_rows(name):
    p = OUT / "pdf" / f"{name}.tsv"
    rows = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        r = ln.split("\t")
        if len(r) >= 5:
            rows.append((int(r[0]), float(r[1]), float(r[2]), r[3], r[4]))
    return rows


B2 = (R7, R8)
B3 = (R7, R8, R9)

# ("L", id, 文書と節, 略称, 時点の組, (条, 項, 号, 細目...), 引用)   … 構造の位置で照合する（項・号の番号も確かめる）
# ("X", id, 文書と節, 略称, 時点の組, (条, 項, 号...), 含まれないはずの文言)
# ("S", id, 文書と節, 略称, 時点, 改正法令番号の一部, 附則の条, (項, 号, 細目...), 引用)
# ("N", id, 文書と節, ページ, 引用)
CLAIMS = [
    # ---------- §1 承認
    ("L", "所法143", "PS§1.1", "shotoku", B2, ("143", "1"), "不動産所得、事業所得又は山林所得を生ずべき業務を行なう居住者は、納税地の所轄税務署長の承認を受けた場合には、確定申告書及び当該申告書に係る修正申告書を青色の申告書により提出することができる。"),
    ("L", "所法2①四十", "PS§1.1", "shotoku", B2, ("2", "1", "40"), "青色申告書　第百四十三条（青色申告）（第百六十六条において準用する場合を含む。）の規定により青色の申告書によつて提出する確定申告書及び確定申告書に係る修正申告書をいう。"),
    ("N", "所基通143−1", "PS§1.1", "kihon_20_01", "143－1…不動産所得の基因となる資産を貸付け…事業所得を生ずべき事業を経営し、又は山林を保有している居住者をいう"),
    ("L", "所法144", "PS§1.2", "shotoku", B2, ("144", "1"), "その年分以後の各年分の所得税につき前条の承認を受けようとする居住者は、その年三月十五日まで（その年一月十六日以後新たに同条に規定する業務を開始した場合には、その業務を開始した日から二月以内）に、当該業務に係る所得の種類その他財務省令で定める事項を記載した申請書を納税地の所轄税務署長に提出しなければならない。"),
    ("N", "所基通144−1", "PS§1.2", "kihon_20_01", "144－1…相続したことにより…当該被相続人についての所得税の準確定申告書の提出期限（当該期限が法第147条《青色申告書の承認があったものとみなす場合》の規定により青色申告の承認があったとみなされる日後に到来するときは、その日）までに提出して差し支えない"),
    ("N", "A1-8 相続1", "PS§1.2", "annai_09", "その死亡の日がその年の1月1日から8月31日までの場合・・・死亡の日から4か月以内"),
    ("N", "A1-8 相続2", "PS§1.2", "annai_09", "9月1日から10月31日まで…その年の12月31日まで"),
    ("N", "A1-8 相続3", "PS§1.2", "annai_09", "11月1日から12月31日まで…その年の翌年の2月15日まで"),
    ("N", "A1-8 休日", "PS§1.2", "annai_09", "提出期限が土・日曜日・祝日等に当たる場合は、これらの日の翌日が期限となります。"),
    ("N", "A1-8 根拠", "PS§1.2", "annai_09", "所得税法第144条、所得税法第166条"),
    ("N", "A1-8 題", "PS§0.2", "annai_09", "A1-8…所得税の青色申告承認申請手続"),
    ("N", "TA2070 白色の承継", "PS§1.2", "ta_2070", "被相続人が白色申告者の場合(その年の1月16日以後に業務を承継した場合)…業務を承継した日から2か月以内"),
    ("L", "所規55①二", "PS§1.3", "shotoku-ki", B2, ("55", "1", "2"), "前号の申請書を提出した後最初に青色申告書を提出しようとする年"),
    ("L", "所規55①三", "PS§1.3", "shotoku-ki", B2, ("55", "1", "3"), "その取消しに係る同条第二項の規定による通知を受けた日又は取りやめの届出書の提出をした日"),
    ("L", "所規55①四", "PS§1.3", "shotoku-ki", B2, ("55", "1", "4"), "その年一月十六日以後新たに法第百四十三条（青色申告）に規定する業務を開始した場合には、その開始した年月日"),
    ("L", "所規55①五", "PS§1.3", "shotoku-ki", B2, ("55", "1", "5"), "その他参考となるべき事項"),
    ("L", "所規55①三(R9)", "PS§1.3", "shotoku-ki", (R9,), ("55", "1", "3"), "その他参考となるべき事項"),
    ("X", "所規55①四(R9なし)", "PS§1.3", "shotoku-ki", (R9,), ("55", "1", "4"), "＊"),
    ("S", "令5財12附則1⑤", "PS§1.3", "shotoku-ki", R9, "令和五年三月三一日財務省令第一二号", "1", ("1", "5"), "第五十五条の改正規定…令和九年一月一日"),
    ("S", "令5財12附則5", "PS§1.3", "shotoku-ki", R9, "令和五年三月三一日財務省令第一二号", "5", (), "新規則第五十五条…の規定は、令和九年分以後の所得税につき所得税法第百四十三条…の承認を受けようとする場合について適用し、令和八年分以前の所得税につき同法第百四十三条の承認を受けようとする場合については、なお従前の例による。"),
    ("L", "所法145一", "PS§1.4", "shotoku", B2, ("145", "1", "1"), "第百四十八条第一項"),
    ("L", "所法145二", "PS§1.4", "shotoku", B2, ("145", "1", "2"), "隠ぺいし又は仮装して…不実の記載又は記録があると認められる相当の理由"),
    ("L", "所法145三", "PS§1.4", "shotoku", B2, ("145", "1", "3"), "第百五十条第二項（青色申告の承認の取消し）の規定による通知を受け、又は第百五十一条第一項（青色申告の取りやめ）に規定する届出書の提出をした日以後一年以内にその申請書を提出したこと"),
    ("L", "所法146", "PS§1.4", "shotoku", B2, ("146", "1"), "書面により…通知する"),
    ("L", "所法147", "PS§1.4", "shotoku", B2, ("147", "1"), "承認を受けようとする年の十二月三十一日（その年十一月一日以後新たに同条に規定する業務を開始した場合には、その年の翌年二月十五日）までにその申請につき承認又は却下の処分がなかつたときは、その日においてその承認があつたものとみなす。"),
    ("L", "電帳法8③一", "PS§1.4", "denchou", (R7,), ("8", "3", "1"), "所得税法第百四十五条第一号（青色申告の承認申請の却下）"),
    ("L", "所法150①", "PS§1.5", "shotoku", B2, ("150", "1"), "当該各号に掲げる年までさかのぼつて、その承認を取り消すことができる。この場合において、その取消しがあつたときは、その居住者の当該年分以後の各年分の所得税につき提出したその承認に係る青色申告書は、青色申告書以外の申告書とみなす。"),
    ("L", "所法150①二", "PS§1.5", "shotoku", B2, ("150", "1", "2"), "第百四十八条第二項"),
    ("L", "所法150①三", "PS§1.5", "shotoku", B2, ("150", "1", "3"), "隠ぺい…仮装…真実性を疑うに足りる相当の理由"),
    ("L", "所法150②", "PS§1.5", "shotoku", B2, ("150", "2"), "書面により…通知する…同項各号のいずれに該当するかを附記しなければならない"),
    ("N", "所基通150−1", "PS§1.5", "kihon_20_01", "150－1…同条第6項に規定する「やむを得ない事情がある」ものとして同条第3項に規定する事業専従者控除を認めるものとする"),
    ("L", "所法151①R7", "PS§1.6", "shotoku", (R7,), ("151", "1"), "その年の翌年三月十五日までに、その申告をやめようとする年その他財務省令で定める事項を記載した届出書"),
    ("L", "所法151①R8", "PS§1.6", "shotoku", (R8,), ("151", "1"), "その年分の所得税に係る確定申告期限までに、その申告をやめようとする年その他財務省令で定める事項を記載した届出書"),
    ("L", "所法151①後段", "PS§1.6", "shotoku", B2, ("151", "1"), "当該年分以後の各年分の所得税については、その承認は、その効力を失うものとする。"),
    ("L", "所法151②R7", "PS§1.6", "shotoku", (R7,), ("151", "2"), "業務の全部を譲渡し又は廃止した場合には、その譲渡し又は廃止した日の属する年の翌年分以後の各年分の所得税については、その承認は、その効力を失うものとする。"),
    ("L", "所法151②R8", "PS§1.6", "shotoku", (R8,), ("151", "2"), "業務の全部を譲渡し、又は廃止した場合には、その譲渡し、又は廃止した日の属する年の翌年分以後の各年分の所得税については、その承認は、その効力を失うものとする。"),
    ("S", "令5法3附則1⑥イ", "PS§1.6", "shotoku", R8, "令和五年三月三一日法律第三号", "1", ("1", "6", "1"), "所得税法第百五十一条の改正規定"),
    ("S", "令5法3附則1⑥", "PS§1.6", "shotoku", R8, "令和五年三月三一日法律第三号", "1", ("1", "6"), "令和八年一月一日"),
    ("S", "令5法3附則5", "PS§1.6", "shotoku", R8, "令和五年三月三一日法律第三号", "5", (), "新所得税法第百五十一条…の規定は、令和八年分以後の所得税につき青色申告書の提出をやめようとする場合について適用し、令和七年分以前の所得税につき青色申告書の提出をやめようとする場合については、なお従前の例による。"),
    ("L", "所規66①R7二", "PS§1.6", "shotoku-ki", (R7,), ("66", "1", "2"), "青色申告書の提出の承認を受けた日又はその承認があつたものとみなされた日"),
    ("L", "所規66①R7三", "PS§1.6", "shotoku-ki", (R7,), ("66", "1", "3"), "青色申告書の提出をやめようとする理由"),
    ("L", "所規66①R7四", "PS§1.6", "shotoku-ki", (R7,), ("66", "1", "4"), "その他参考となるべき事項"),
    ("L", "所規66①R8二", "PS§1.6", "shotoku-ki", (R8, TODAY), ("66", "1", "2"), "その他参考となるべき事項"),
    ("X", "所規66①R8三なし", "PS§1.6", "shotoku-ki", (R8,), ("66", "1", "3"), "＊"),
    ("S", "令5財12附則1④", "PS§1.6", "shotoku-ki", R8, "令和五年三月三一日財務省令第一二号", "1", ("1", "4"), "第六十六条の改正規定…令和八年一月一日"),
    ("S", "令5財12附則6", "PS§1.6", "shotoku-ki", R8, "令和五年三月三一日財務省令第一二号", "6", (), "新規則第六十六条…の規定は、令和八年分以後の所得税につき青色申告書の提出をやめようとする場合について適用し、令和七年分以前の所得税につき青色申告書の提出をやめようとする場合については、なお従前の例による。"),
    ("N", "A1-9 取りやめ", "PS§1.6", "annai_23200008", "青色申告を取りやめようとする年分の所得税の確定申告期限までに提出してください"),
    ("N", "A1-9 取りやめ 題", "PS§0.2", "annai_23200008", "A1-9…所得税の青色申告の取りやめ手続"),
    ("N", "A1-9 兼現金主義 題", "PS§0.2", "annai_10", "A1-9…所得税の青色申告承認申請（兼）現金主義の所得計算による旨の届出手続"),
    ("L", "所法155①", "PS§1.7", "shotoku", B2, ("155", "1"), "その居住者の帳簿書類を調査し、その調査によりこれらの金額の計算に誤りがあると認められる場合に限り、これをすることができる。"),
    ("L", "所法155②", "PS§1.7", "shotoku", B2, ("155", "2"), "更正通知書にその更正の理由を付記しなければならない"),
    # ---------- §2 帳簿
    ("L", "所法148①", "PS§2.1", "shotoku", B2, ("148", "1"), "第百四十三条（青色申告）の承認を受けている居住者は、財務省令で定めるところにより、同条に規定する業務につき帳簿書類を備え付けてこれに不動産所得の金額、事業所得の金額及び山林所得の金額に係る取引を記録し、かつ、当該帳簿書類を保存しなければならない。"),
    ("L", "所法148②", "PS§2.1", "shotoku", B2, ("148", "2"), "必要な指示をすることができる"),
    ("L", "所法149", "PS§2.1", "shotoku", B2, ("149", "1"), "青色申告書には、財務省令で定めるところにより、貸借対照表、損益計算書その他不動産所得の金額、事業所得の金額若しくは山林所得の金額又は純損失の金額の計算に関する明細書を添附しなければならない。"),
    ("L", "所法232①", "PS§2.1", "shotoku", B2, ("232", "1"), "青色申告書を提出することにつき税務署長の承認を受けている者を除く"),
    ("L", "所規56①", "PS§2.2", "shotoku-ki", B3, ("56", "1"), "次条から第六十四条まで（青色申告者の帳簿書類の備付け等）に定めるところによらなければならない。ただし、当該帳簿書類については、次条から第五十九条まで（青色申告者の帳簿書類）、第六十一条（貸借対照表及び損益計算書）及び第六十四条（帳簿書類の記載事項等の省略又は変更）の規定に定めるところに代えて、財務大臣の定める簡易な記録の方法及び記載事項によることができる。"),
    ("L", "所規56③", "PS§2.2", "shotoku-ki", B3, ("56", "3"), "財務大臣は…告示する"),
    ("L", "所規57①", "PS§2.2", "shotoku-ki", B3, ("57", "1"), "資産、負債及び資本に影響を及ぼす一切の取引（以下この節において「取引」という。）を正規の簿記の原則に従い、整然と、かつ、明りように記録し、その記録に基づき、貸借対照表及び損益計算書を作成しなければならない。"),
    ("L", "所規57①一", "PS§2.2", "shotoku-ki", B3, ("57", "1", "1"), "不動産所得"),
    ("L", "所規57①三", "PS§2.2", "shotoku-ki", B3, ("57", "1", "3"), "山林所得"),
    ("L", "所規57②", "PS§2.2", "shotoku-ki", B3, ("57", "2"), "ただし、そのつど区分整理し難いものは年末において、一括して区分整理することができる。"),
    ("L", "所規58①", "PS§2.2", "shotoku-ki", B3, ("58", "1"), "すべての取引を借方及び貸方に仕訳する帳簿（次条において「仕訳帳」という。）、すべての取引を勘定科目の種類別に分類して整理計算する帳簿（次条において「総勘定元帳」という。）その他必要な帳簿を備え、財務大臣の定める取引に関する事項を記載しなければならない。"),
    ("L", "所規58②", "PS§2.2", "shotoku-ki", B3, ("58", "2"), "告示する"),
    ("L", "所規59", "PS§2.2", "shotoku-ki", B3, ("59",), "取引の発生順に、取引の年月日、内容、勘定科目及び金額を記載しなければならない。…その勘定ごとに、記載の年月日、相手方の勘定科目及び金額を記載しなければならない。"),
    ("L", "所規60①", "PS§2.2", "shotoku-ki", B3, ("60", "1"), "毎年十二月三十一日…棚卸資産の棚卸しその他決算のために必要な事項の整理を行い"),
    ("L", "所規60②", "PS§2.2", "shotoku-ki", B3, ("60", "2"), "一月一日"),
    ("L", "所規60③", "PS§2.2", "shotoku-ki", B3, ("60", "3"), "棚卸表"),
    ("L", "所規61①", "PS§2.2", "shotoku-ki", B3, ("61", "1"), "毎年十二月三十一日…財務大臣の定める科目に従い、貸借対照表及び損益計算書を作成しなければならない。"),
    ("L", "所規61②", "PS§2.2", "shotoku-ki", B3, ("61", "2"), "告示する"),
    ("L", "所規62", "PS§2.2", "shotoku-ki", B3, ("62",), "生計を一にする…親族…その親族の労務に従事した期間、労務の性質その他その労務の事績を明らかにする事項の記載を命ずることができる。"),
    ("L", "所規64", "PS§2.2", "shotoku-ki", B3, ("64",), "第五十八条から第六十二条まで…納税地の所轄税務署長の承認を受け、これらの規定に規定する記載事項の一部を省略し又は変更することができる。"),
    ("N", "所基通148−1", "PS§2.2", "kihon_20_01", "148－1…損益計算書はそれぞれの業務に係るものの区分ごとに各別に作成し、貸借対照表は全ての業務に係るものを合併して作成するものとする"),
    ("L", "所規65①一", "PS§2.3", "shotoku-ki", B3, ("65", "1", "1"), "貸借対照表及び損益計算書"),
    ("L", "所規65①二", "PS§2.3", "shotoku-ki", B3, ("65", "1", "2"), "変動所得…臨時所得"),
    ("L", "所規65①三", "PS§2.3", "shotoku-ki", B3, ("65", "1", "3"), "純損失の金額の計算に関する明細書"),
    ("L", "所規65②", "PS§2.3", "shotoku-ki", B3, ("65", "2"), "第五十六条第一項ただし書（青色申告者の備え付けるべき帳簿書類）の規定の適用を受ける青色申告者は、前項の規定にかかわらず、貸借対照表を青色申告書に添付することを要しない。"),
    ("L", "所規56②", "PS§2.3", "shotoku-ki", B3, ("56", "2"), "法第六十七条第一項…第六十条（決算）の規定による棚卸資産の棚卸を行うことを要しない"),
    ("N", "TA2070 簡易帳簿", "PS§2.3", "ta_2070", "年末に貸借対照表と損益計算書を作成することができるような正規の簿記によることが原則ですが、現金出納帳、売掛帳、買掛帳、経費帳、固定資産台帳のような帳簿を備え付けて簡易な記帳をするだけでもよいことになっています。"),
    ("L", "所規63①", "PS§2.4", "shotoku-ki", B3, ("63", "1"), "起算日から七年間（第三号に掲げる書類のうち、現金預金取引等関係書類に該当する書類以外のものにあつては、五年間）"),
    ("L", "所規63②", "PS§2.4", "shotoku-ki", B3, ("63", "2"), "前々年分の不動産所得の金額及び事業所得の金額の合計額（令第百九十五条第一号…）が同号に規定する金額以下であるもの…同項第三号に掲げる書類については、起算日から五年間を超えて保存することを要しない"),
    ("L", "所令195一 300万", "PS§2.4", "shotoku-rei", B3, ("195", "1", "1"), "三百万円以下"),
    ("L", "所規63④", "PS§2.4", "shotoku-ki", B3, ("63", "4"), "翌年三月十五日の翌日"),
    ("N", "TA2070 保存", "PS§2.4", "ta_2070", "原則として7年間保存することとされていますが、書類によっては5年間でよいものもあります"),
    ("L", "電帳規2①", "PS§2.5", "denchou-ki", B2, ("2", "1"), "所得税法（昭和四十年法律第三十三号）又は法人税法（昭和四十年法律第三十四号）の規定により…正規の簿記の原則（同法の規定により備付け及び保存をしなければならないこととされている帳簿にあっては、複式簿記の原則）に従い、整然と、かつ、明瞭に記録されているもの以外のものとする"),
    ("L", "法規53（複式簿記）", "検証で追加", "hojin-ki", (R7,), ("53", "1"), "青色申告法人…複式簿記の原則に従い"),
    ("L", "所規57①（正規の簿記）", "検証で追加", "shotoku-ki", (R7,), ("57", "1"), "正規の簿記の原則に従い"),
    ("L", "電帳規5⑤一イ(1)", "PS§2.5", "denchou-ki", B2, ("5", "5", "1", "1", "1"), "訂正又は削除を行った場合には、これらの事実及び内容を確認することができること"),
    ("L", "電帳規5⑤一イ(2)", "PS§2.5", "denchou-ki", B2, ("5", "5", "1", "1", "2"), "通常の期間を経過した後に行った場合には、その事実を確認することができること"),
    ("L", "電帳規5⑤一ロ", "PS§2.5", "denchou-ki", B2, ("5", "5", "1", "2"), "相互にその関連性を確認することができるようにしておくこと"),
    ("L", "電帳規5⑤一ハ(1)", "PS§2.5", "denchou-ki", B2, ("5", "5", "1", "3", "1"), "取引年月日、取引金額及び取引先"),
    ("L", "電帳規5⑤一ハ(2)", "PS§2.5", "denchou-ki", B2, ("5", "5", "1", "3", "2"), "範囲を指定して条件を設定することができること"),
    ("L", "電帳規5⑤一ハ(3)", "PS§2.5", "denchou-ki", B2, ("5", "5", "1", "3", "3"), "二以上の任意の記録項目を組み合わせて条件を設定することができること"),
    ("L", "電帳規5⑤一 括弧", "PS§2.5", "denchou-ki", B2, ("5", "5", "1"), "提示又は提出の要求に応じることができるようにしている場合には、ハ（（２）及び（３）に係る部分に限る。）に掲げる要件を除く"),
    ("L", "電帳規5⑤ 柱書", "PS§2.5", "denchou-ki", B2, ("5", "5"), "法第八条第四項に規定する財務省令で定める要件は"),
    ("L", "電帳規5①", "PS§2.5", "denchou-ki", B2, ("5", "1"), "あらかじめ…届出書"),
    ("L", "電帳規5②", "PS§2.5", "denchou-ki", B2, ("5", "2"), "あらかじめ…届出書"),
    ("L", "電帳規5④(R9)", "PS§2.5", "denchou-ki", (R9,), ("5", "4"), "法第八条第四項に規定する財務省令で定める要件は"),
    ("L", "電帳規5⑤(R9)", "PS§2.5", "denchou-ki", (R9,), ("5", "5"), "法第八条第五項に規定する財務省令で定める要件は、次に掲げる要件に従って特定電"),
    ("L", "電帳規5⑧(R9)", "PS§2.5", "denchou-ki", (R9,), ("5", "8"), "第六項の保存義務者は、同項の届出書に記載した事項の変更をしようとする場合には"),
    # ---------- §3 青色申告特別控除（R7・R8）
    ("L", "措法25の2①", "PS§3.1", "sochi", B2, ("25_2", "1"), "その承認を受けている年分（第三項の規定の適用を受ける年分を除く。）"),
    ("L", "措法25の2①一", "PS§3.1", "sochi", B2, ("25_2", "1", "1"), "十万円"),
    ("L", "措法25の2①二", "PS§3.1", "sochi", B2, ("25_2", "1", "2"), "次条第一項の規定の適用がある場合には、同項に規定する社会保険診療につき支払を受けるべき金額に対応する部分の金額を除く…合計額"),
    ("L", "措法26①（社会保険診療）", "PS§3.1", "sochi", B2, ("26", "1"), "社会保険診療"),
    ("L", "措法25の2②", "PS§3.1", "sochi", B2, ("25_2", "2"), "前項の規定により控除すべき金額は、不動産所得の金額、事業所得の金額又は山林所得の金額から順次控除する。"),
    ("L", "措法25の2③", "PS§3.1", "sochi", B2, ("25_2", "3"), "不動産所得又は事業所得を生ずべき事業を営むもの（所得税法第六十七条第一項の規定の適用を受ける者を除く。）…同法第百四十八条第一項の規定により…これらの所得の金額に係る一切の取引の内容を詳細に記録している場合として財務省令で定める場合に限る"),
    ("L", "措法25の2③一", "PS§3.1", "sochi", B2, ("25_2", "3", "1"), "五十五万円"),
    ("L", "措法25の2③二", "PS§3.1", "sochi", B2, ("25_2", "3", "2"), "不動産所得の金額又は事業所得の金額の合計額"),
    ("L", "措法25の2④", "PS§3.1", "sochi", B2, ("25_2", "4"), "同項第一号中「五十五万円」とあるのは、「六十五万円」として、同項の規定を適用することができる"),
    ("L", "措法25の2④一", "PS§3.1", "sochi", B2, ("25_2", "4", "1"), "その年における前項に規定する帳簿書類のうち財務省令で定めるもの…第四条第一項又は第五条第一項若しくは第三項…同法第八条第四項に規定する財務省令で定める要件を満たしている場合に限る。"),
    ("L", "措法25の2④二", "PS§3.1", "sochi", B2, ("25_2", "4", "2"), "その年分の所得税の確定申告書の提出期限までに…電子情報処理組織を使用して…前項の規定の適用を受けようとする旨及び同項の規定による控除を受ける金額の計算に関する事項を含む…貸借対照表、損益計算書"),
    ("L", "措法25の2⑤", "PS§3.1", "sochi", B2, ("25_2", "5"), "第三項の規定により控除すべき金額は、不動産所得の金額又は事業所得の金額から順次控除する。"),
    ("L", "措法25の2⑥", "PS§3.1", "sochi", B2, ("25_2", "6"), "第三項（第四項の規定により、同項第二号に掲げる要件を満たしている者について適用する場合を除く。）の規定は、確定申告書に第三項の規定の適用を受けようとする旨及び同項の規定による控除を受ける金額の計算に関する事項の記載並びに…貸借対照表、損益計算書…の添付があり、かつ、当該確定申告書をその提出期限までに提出した場合に限り、適用する。"),
    ("L", "措規9の6①", "PS§3.1", "sochi-ki", B2, ("9_6", "1"), "所得税法施行規則第五十七条から第六十二条まで及び第六十四条の規定に定めるところにより記録し、かつ、作成している場合とする。"),
    ("L", "措規9の6②", "PS§3.1", "sochi-ki", B2, ("9_6", "2"), "法第二十五条の二第四項第一号に規定する財務省令で定める帳簿書類は、所得税法施行規則第五十八条第一項に規定する仕訳帳及び総勘定元帳とする。"),
    ("L", "措規9の6③", "PS§3.1", "sochi-ki", B2, ("9_6", "3"), "電子帳簿保存適用個人…最初の記録段階から一貫して…第二条第二項又は第三条第一項の定めるところに従つて…電子帳簿保存法施行規則第五条第五項に規定する要件を満たすものに限る"),
    ("L", "措規9の6④", "PS§3.1", "sochi-ki", B2, ("9_6", "4"), "電子計算機出力マイクロフィルムによる保存"),
    ("L", "措規9の6⑤", "PS§3.1", "sochi-ki", B2, ("9_6", "5"), "電子帳簿保存法施行規則第五条第一項に規定する届出書（以下この項において「適用届出書」という。）の提出をしなければならない。…同条第二項に規定する届出書…の提出があつた日の属する年以後の各年分については、当該適用届出書の提出は、なかつたものとする。"),
    ("L", "措規9の6⑥", "PS§3.1", "sochi-ki", B2, ("9_6", "6"), "その年分の所得税の確定申告書の提出期限までに…第一項の帳簿書類に基づき作成された所得税法施行規則第六十五条第一項各号に掲げる書類に記載すべき事項に係る情報を国税関係法令に係る情報通信技術を活用した行政の推進等に関する省令第五条第一項の定めるところに従つて送信しなければならない。"),
    ("L", "措規9の6⑦", "PS§3.1", "sochi-ki", B2, ("9_6", "7"), "法第二十五条の二第六項…第一項の帳簿書類に基づき作成された所得税法施行規則第六十五条第一項各号に掲げる書類とする。"),
    # TA・手引き・措通
    ("N", "TA2072 日付", "PS§0.2", "ta_2072", "令和8年4月1日現在法令等"),
    ("N", "TA2070 日付", "PS§0.2", "ta_2070", "令和8年4月1日現在法令等"),
    ("N", "TA2075 日付", "PS§0.2", "ta_2075", "令和8年4月1日現在法令等"),
    ("N", "TA2250 日付", "PS§0.2", "ta_2250", "令和8年4月1日現在法令等"),
    ("N", "TA2072 注1", "PS§3.2", "ta_2072", "現金主義による所得計算の特例を選択している方は、55万円の青色申告特別控除を受けることはできません。"),
    ("N", "TA2072 注2", "PS§3.2", "ta_2072", "この合計額とは損益通算前の黒字の所得金額の合計額をいいますので、いずれかの所得に損失が生じている場合には、その損失をないものとして合計額を計算します。"),
    ("N", "TA2072 注3", "PS§3.2", "ta_2072", "不動産所得の金額、事業所得の金額から順次控除します。"),
    ("N", "TA2072 注4", "PS§3.2", "ta_2072", "還付申告書等を提出する方であっても、55万円または65万円の青色申告特別控除の適用を受けるためには、その年分の確定申告期限（翌年3月15日）までに当該申告書を提出する必要があります。"),
    ("N", "TA2072 イ", "PS§3.2", "ta_2072", "優良な電子帳簿の要件を満たして電子データによる備付けおよび保存を行い、一定の事項を記載した届出書をその年分の確定申告期限（翌年3月15日）までに提出する必要があります"),
    ("N", "TA2072 ロ", "PS§3.2", "ta_2072", "確定申告書、貸借対照表、損益計算書等をイメージデータで送信することはできません"),
    ("N", "TA2072 10万", "PS§3.2", "ta_2072", "上記「55万円の青色申告特別控除」および「65万円の青色申告特別控除」の要件に該当しない青色申告者が受けられます"),
    ("N", "措通25の2−1(1)", "PS§3.2", "sochitsu_25_2", "損益通算をする前のいわゆる黒字の所得金額をいうのであるから、これらの所得の金額の計算上生じた損失の金額がある場合には、その損失の金額を除外したところにより"),
    ("N", "措通25の2−1(2)", "PS§3.2", "sochitsu_25_2", "黒字の金額を限度として順次控除すること"),
    ("N", "措通25の2−1(3)", "PS§3.2", "sochitsu_25_2", "措置法第26条第1項…合計額を計算するときはこれを除外したところによるのであるが…当該所得を含めた事業所得の金額から控除すること"),
    ("N", "措通25の2−2", "PS§3.2", "sochitsu_25_2", "25の2－2…変動所得の金額又は臨時所得の金額の割合を乗じて計算した金額"),
    ("N", "措通25の2−3", "PS§3.2", "sochitsu_25_2", "25の2－3…確定申告書への記載を要件とするものではないから"),
    ("N", "措通25の2−5", "PS§3.2", "sochitsu_25_2", "措置法規則第９条の６第５項に規定する適用届出書又は同条第８項に規定する適用届出書を措置法第25条の２第７項に規定する提出期限までに提出しなければならない"),
    ("N", "措通 令8課個2-10", "PS§3.2", "sochitsu_25_2", "25の2－1…令８課個2-10、課審5-4改正"),
    ("N", "A1-15 対象者", "PS§3.2", "annai_09_2", "仕訳帳及び総勘定元帳について、規則第５条第５項の要件に従って保存等を行い、65万円の青色申告特別控除の適用を受けようとする方"),
    ("N", "A1-15 時期", "PS§3.2", "annai_09_2", "適用を受けようとする年の翌年3月15日（適用を受けようとする年分に係る法定申告期限）までに提出してください。"),
    ("N", "A1-15 根拠", "PS§3.2", "annai_09_2", "租税特別措置法第25条の２第４項…第８条第４項…施行規則第５条第１項"),
    ("N", "A1-15 題", "PS§0.2", "annai_09_2", "A1-15、H4-9"),
    ("N", "A1-16 根拠", "PS§3.2", "annai_17_0", "施行規則第５条第２項"),
    ("N", "A1-16 時期", "PS§3.2", "annai_17_0", "適用を受けようとする年の翌年3月15日"),
    ("N", "A1-16 題", "PS§0.2", "annai_17_0", "A1-16、H4-10"),
    # ---------- §3.3 令和9年分以後
    ("L", "措法25の2①(R9)", "PS§3.3", "sochi", (R9,), ("25_2", "1"), "（第四項の規定の適用を受ける年分を除く。）"),
    ("L", "措法25の2①一(R9)", "PS§3.3", "sochi", (R9,), ("25_2", "1", "1"), "十万円"),
    ("L", "措法25の2②(R9)", "PS§3.3", "sochi", (R9,), ("25_2", "2"), "前項の規定は、同項に規定する個人でその年において不動産所得又は事業所得を生ずべき事業を営むもの（所得税法第六十七条第一項の規定の適用を受ける者を除くものとし、次の各号に掲げる者の区分に応じ当該各号に定める要件を満たすものに限る。）が、第四項に規定する場合に該当しない場合には、適用しない。"),
    ("L", "措法25の2②一(R9)", "PS§3.3", "sochi", (R9,), ("25_2", "2", "1"), "不動産所得を生ずべき事業を営む者…その年の前々年分の不動産所得に係る総収入金額が千万円を超えること"),
    ("L", "措法25の2②二(R9)", "PS§3.3", "sochi", (R9,), ("25_2", "2", "2"), "事業所得を生ずべき事業を営む者…その年の前々年分の事業所得に係る総収入金額が千万円を超えること"),
    ("L", "措法25の2④一(R9)", "PS§3.3", "sochi", (R9,), ("25_2", "4", "1"), "六十五万円"),
    ("L", "措法25の2⑤(R9)", "PS§3.3", "sochi", (R9,), ("25_2", "5"), "前項第一号中「六十五万円」とあるのは、「七十五万円」として"),
    ("L", "措法25の2⑤一(R9)", "PS§3.3", "sochi", (R9,), ("25_2", "5", "1"), "第八条第四項に規定する財務省令で定める要件を満たしている場合"),
    ("L", "措法25の2⑤二イ(R9)", "PS§3.3", "sochi", (R9,), ("25_2", "5", "2", "1"), "特定電磁的記録…の保存が同項に規定する財務省令で定める要件を満たすために必要な措置として財務省令で定めるものを講じていること"),
    ("L", "措法25の2⑤二ロ(R9)", "PS§3.3", "sochi", (R9,), ("25_2", "5", "2", "2"), "当該電子取引の取引情報に係る特定電磁的記録を保存していること"),
    ("L", "措法25の2⑦(R9)", "PS§3.3", "sochi", (R9,), ("25_2", "7"), "第四項の規定は、その年分の所得税の確定申告書の提出期限までに…電子情報処理組織を使用して…送信した場合に限り、適用する。"),
    ("L", "措規9の6③(R9) 定義", "PS§3.3", "sochi-ki", (R9,), ("9_6", "3"), "「電子帳簿保存適用個人」"),
    ("L", "措規9の6⑥(R9) 定義", "PS§3.3", "sochi-ki", (R9,), ("9_6", "6"), "（以下この条において「電子帳簿保存適用個人」という。）"),
    ("L", "措規9の6⑤(R9)", "PS§3.3", "sochi-ki", (R9,), ("9_6", "5"), "電子帳簿保存法施行規則第五条第一項に規定する届出書"),
    ("L", "措規9の6⑧(R9)", "PS§3.3", "sochi-ki", (R9,), ("9_6", "8"), "特定電磁的記録につき電子帳簿保存法施行規則第五条第六項に規定する届出書"),
    ("L", "措規9の6⑨(R9)", "PS§3.3", "sochi-ki", (R9,), ("9_6", "9"), "特定電子計算機処理システム…事業の用に供していることとする"),
    ("L", "措規9の6⑩(R9)", "PS§3.3", "sochi-ki", (R9,), ("9_6", "10"), "電子取引を行つた場合には…特定電磁的記録"),
    ("L", "措規9の6⑪(R9)", "PS§3.3", "sochi-ki", (R9,), ("9_6", "11"), "確定申告書の提出期限までに…送信"),
    ("S", "令7財26附則1⑥", "PS§3.3", "sochi-ki", R9, "令和七年三月三一日財務省令第二六号", "1", ("1", "6"), "租税特別措置法施行規則第九条の六の改正規定…令和九年一月一日"),
    ("S", "令8財21附則1④イ", "PS§3.3", "sochi-ki", R9, "令和八年三月三一日財務省令第二一号", "1", ("1", "4", "1"), "同令第九条の六の改正規定"),
    ("S", "令8財21附則1④", "PS§3.3", "sochi-ki", R9, "令和八年三月三一日財務省令第二一号", "1", ("1", "4"), "令和九年一月一日"),
    ("S", "令8法12附則1⑤ロ", "PS§3.3", "sochi", R9, "令和八年三月三一日法律第一二号", "1", ("1", "5", "2"), "同法第二十五条の二の改正規定"),
    ("S", "令8法12附則1⑤", "PS§3.3", "sochi", R9, "令和八年三月三一日法律第一二号", "1", ("1", "5"), "令和九年一月一日"),
    ("S", "令8法12附則33", "PS§3.3", "sochi", R9, "令和八年三月三一日法律第一二号", "33", (), "新租税特別措置法第二十五条の二の規定は、令和九年分以後の所得税について適用し、令和八年分以前の所得税については、なお従前の例による。"),
    ("S", "令7法13附則31（第四項第一号ロ）", "PS§3.4", "sochi", R9, "令和七年三月三一日法律第一三号", "31", (), "新租税特別措置法第二十五条の二（第四項第一号ロに係る部分に限る。）の規定は、令和九年分以後の所得税について適用する。"),
    # ---------- §4 青色事業専従者
    ("L", "所法57①", "PS§4.1", "shotoku", B2, ("57", "1"), "青色申告書を提出することにつき税務署長の承認を受けている居住者と生計を一にする配偶者その他の親族（年齢十五歳未満である者を除く。）で専らその居住者の営む前条に規定する事業に従事するもの…次項の書類に記載されている方法に従いその記載されている金額の範囲内において給与の支払を受けた場合には…労務の対価として相当であると認められるものは…必要経費に算入し、かつ、当該青色事業専従者の当該年分の給与所得に係る収入金額とする。"),
    ("L", "所法56（前条の事業）", "PS§4.1", "shotoku", B2, ("56", "1"), "不動産所得、事業所得又は山林所得を生ずべき事業"),
    ("L", "所法57②", "PS§4.1", "shotoku", B2, ("57", "2"), "その年三月十五日まで（その年一月十六日以後新たに同項の事業を開始した場合には、その事業を開始した日から二月以内）に、青色事業専従者の氏名、その職務の内容及び給与の金額並びにその給与の支給期その他財務省令で定める事項を記載した書類"),
    ("L", "所法57⑦", "PS§4.1", "shotoku", B2, ("57", "7"), "その年十二月三十一日（これらの規定に規定する居住者がその年の中途において死亡し又は出国をした場合には、その死亡又は出国の時）の現況による。ただし、当該親族がその当時既に死亡している場合は、当該死亡の時の現況による。"),
    ("L", "所法57⑧", "PS§4", "shotoku", B2, ("57", "8"), "政令で定める"),
    ("L", "所法57③イ 86万", "H§H6", "shotoku", B2, ("57", "3", "1", "1"), "八十六万円"),
    ("L", "所法57③ロ 50万", "H§H6", "shotoku", B2, ("57", "3", "1", "2"), "五十万円"),
    ("L", "所法57③二", "H§H6", "shotoku", B2, ("57", "3", "2"), "事業専従者の数に一を加えた数で除して計算した金額"),
    ("L", "所令164①一", "PS§4.1", "shotoku-rei", B2, ("164", "1", "1"), "労務に従事した期間、労務の性質及びその提供の程度"),
    ("L", "所令164①二", "PS§4.1", "shotoku-rei", B2, ("164", "1", "2"), "その事業に従事する他の使用人が支払を受ける給与の状況及びその事業と同種の事業でその規模が類似するものに従事する者が支払を受ける給与の状況"),
    ("L", "所令164①三", "PS§4.1", "shotoku-rei", B2, ("164", "1", "3"), "その事業の種類及び規模並びにその収益の状況"),
    ("L", "所令164②", "PS§4.2", "shotoku-rei", B2, ("164", "2"), "当該書類に記載した事項を変更する場合には、財務省令で定めるところにより、その旨その他必要な事項を記載した書類を納税地の所轄税務署長に提出しなければならない。"),
    ("L", "所令165①", "PS§4.1", "shotoku-rei", B2, ("165", "1"), "当該事業に専ら従事する期間がその年を通じて六月をこえるかどうかによる。ただし、同条第一項の場合にあつては、次の各号のいずれかに該当するときは、当該事業に従事することができると認められる期間を通じてその二分の一に相当する期間をこえる期間当該事業に専ら従事すれば足りるものとする。"),
    ("L", "所令165①一", "PS§4.1", "shotoku-rei", B2, ("165", "1", "1"), "年の中途における開業、廃業、休業…死亡…季節営業"),
    ("L", "所令165①二", "PS§4.1", "shotoku-rei", B2, ("165", "1", "2"), "死亡、長期にわたる病気、婚姻その他相当の理由"),
    ("L", "所令165②一", "PS§4.1", "shotoku-rei", B2, ("165", "2", "1"), "学校教育法第一条（学校の範囲）、第百二十四条（専修学校）又は第百三十四条第一項（各種学校）の学校の学生又は生徒である者（夜間において授業を受ける者で昼間を主とする当該事業に従事するもの、昼間において授業を受ける者で夜間を主とする当該事業に従事するもの"),
    ("L", "所令165②一(R7) 生徒", "PS§4.1", "shotoku-rei", (R7,), ("165", "2", "1"), "同法第百二十四条又は同項の学校の生徒で常時修学しないもの"),
    ("L", "所令165②一(R8) 学生又は生徒", "PS§4.1", "shotoku-rei", (R8,), ("165", "2", "1"), "同法第百二十四条又は同項の学校の学生又は生徒で常時修学しないもの"),
    ("L", "所令165②二", "PS§4.1", "shotoku-rei", B2, ("165", "2", "2"), "他に職業を有する者（その職業に従事する時間が短い者その他当該事業に専ら従事することが妨げられないと認められる者を除く。）"),
    ("L", "所令165②三", "PS§4.1", "shotoku-rei", B2, ("165", "2", "3"), "老衰その他心身の障害により事業に従事する能力が著しく阻害されている者"),
    ("L", "所令167", "PS§4.1", "shotoku-rei", B2, ("167",), "従事した分量に応じて配分…明らかでない場合…均等に従事したものとみなして"),
    ("N", "TA2075 要件", "PS§4.1", "ta_2075", "青色申告者と生計を一にする配偶者その他の親族であること…その年の12月31日現在で年齢が15歳以上であること…その年を通じて6か月を超える期間（一定の場合には事業に従事することができる期間の2分の1を超える期間）、その青色申告者の営む事業に専ら従事していること"),
    ("N", "TA2075 注2", "PS§4.1", "ta_2075", "不動産貸付けが事業として行われている場合は適用がありますが、それ以外の場合には適用がありません"),
    ("N", "TA2075 過大", "PS§4.1", "ta_2075", "過大とされる部分は必要経費とはなりません"),
    ("N", "所基通57−2", "PS§4.1", "kihon_11_01", "57－2…赤字"),
    ("N", "所基通57−3", "PS§4.1", "kihon_11_01", "57－3…変動所得…臨時所得"),
    ("L", "所規36の4①二", "PS§4.2", "shotoku-ki", B2, ("36_4", "1", "2"), "続柄及び年齢"),
    ("L", "所規36の4①三", "PS§4.2", "shotoku-ki", B2, ("36_4", "1", "3"), "青色事業専従者が他の業務に従事し又は就学している場合には、その事実"),
    ("L", "所規36の4①四", "PS§4.2", "shotoku-ki", B2, ("36_4", "1", "4"), "その事業に従事する他の使用人に対して支払う給与の金額並びにその支給の方法及び形態"),
    ("L", "所規36の4①五", "PS§4.2", "shotoku-ki", B2, ("36_4", "1", "5"), "昇給の基準その他参考となるべき事項"),
    ("L", "所規36の4①四(R9)", "PS§4.2", "shotoku-ki", (R9,), ("36_4", "1", "4"), "その事業に従事する他の使用人に対して支払う給与の金額"),
    ("X", "所規36の4①四(R9) 支給の方法なし", "PS§4.2", "shotoku-ki", (R9,), ("36_4", "1", "4"), "支給の方法"),
    ("L", "所規36の4①五(R9)", "PS§4.2", "shotoku-ki", (R9,), ("36_4", "1", "5"), "その他参考となるべき事項"),
    ("X", "所規36の4①五(R9) 昇給なし", "PS§4.2", "shotoku-ki", (R9,), ("36_4", "1", "5"), "昇給"),
    ("S", "令5財12附則1⑤（36の4）", "PS§4.2", "shotoku-ki", R9, "令和五年三月三一日財務省令第一二号", "1", ("1", "5"), "第三十六条の四第一項の改正規定…令和九年一月一日"),
    ("S", "令5財12附則2", "PS§4.2", "shotoku-ki", R9, "令和五年三月三一日財務省令第一二号", "2", (), "第三十六条の四第一項の規定は、令和九年分以後の所得税について適用し、令和八年分以前の所得税については、なお従前の例による。"),
    ("L", "所規36の4②", "PS§4.2", "shotoku-ki", B2, ("36_4", "2"), "給与の金額の基準を変更する場合には、遅滞なく"),
    ("L", "所規36の4③", "PS§4.2", "shotoku-ki", B2, ("36_4", "3"), "その年一月十六日以後新たに青色事業専従者を有することとなつた場合には、その者は、その有することとなつた日から二月以内に"),
    ("N", "A1-10 時期", "PS§4.2", "annai_12", "青色事業専従者給与額を必要経費に算入しようとする年の3月15日まで（その年の1月16日以後に開業した人や新たに専従者がいることとなった人は、その開業の日や専従者がいることとなった日から2月以内）"),
    ("N", "A1-10 給与規程", "PS§4.2", "annai_12", "届出書に記載した内容とは別に給与規程を定めているときは、その写しを提出してください"),
    ("N", "A1-11 遅滞なく", "PS§4.2", "annai_13", "遅滞なく提出してください"),
    ("L", "所法2①三十三 除外", "PS§4.3", "shotoku", B2, ("2", "1", "33"), "第五十七条第一項（事業に専従する親族がある場合の必要経費の特例等）に規定する青色事業専従者に該当するもので同項に規定する給与の支払を受けるもの及び同条第三項に規定する事業専従者に該当するもの"),
    ("L", "所法2①三十四 除外", "PS§4.3", "shotoku", B2, ("2", "1", "34"), "第五十七条第一項に規定する青色事業専従者に該当するもので同項に規定する給与の支払を受けるもの及び同条第三項に規定する事業専従者に該当するもの"),
    ("L", "所法2①三十三の四", "PS§4.3", "shotoku", B2, ("2", "1", "33_4"), "源泉控除対象配偶者…青色事業専従者等を除く"),
    ("L", "所法2①三十四の五(R8)", "PS§4.3", "shotoku", (R8,), ("2", "1", "34_5"), "源泉控除対象親族…青色事業専従者等を除く"),
    ("L", "所法84の2 特定親族の除外", "PS§4.3", "shotoku", B2, ("84_2", "1"), "第五十七条第一項（事業に専従する親族がある場合の必要経費の特例等）に規定する青色事業専従者に該当するもので同項に規定する給与の支払を受けるもの及び同条第三項に規定する事業専従者に該当するものを除く"),
    ("L", "所令272②（前前年分）", "PS§5.3", "shotoku-rei", B2, ("272", "2"), "前前年分の課税総所得金額"),
    ("L", "所令271①五（その他の損失から）", "PS§5.3", "shotoku-rei", B2, ("271", "1", "5"), "まずその他の損失の金額を控除し、次に変動所得の損失の金額を控除する"),
    ("L", "通則法10①一（初日不算入）", "H§H1", "tsusoku", (R7,), ("10", "1", "1"), "期間の初日は、算入しない。ただし、その期間が午前零時から始まるとき…この限りでない"),
    ("L", "通則法10①二（月は暦）", "H§H10", "tsusoku", (R7,), ("10", "1", "2"), "暦に従う"),
    ("L", "通則法10②（休日）", "H§H10", "tsusoku", (R7,), ("10", "2"), "日曜日、国民の祝日に関する法律…に規定する休日その他一般の休日又は政令で定める日に当たるときは、これらの日の翌日をもつてその期限とみなす"),
    ("N", "質疑応答 年の中途で従事（相当の理由に就職・退職）", "検証で追加", "shitsugi_04_10", "この「相当の理由」には就職や退職も含むと解されます"),
    ("N", "質疑応答 年の中途で従事（従事可能期間）", "検証で追加", "shitsugi_04_10", "退職したときから年末までを「従事可能期間」とし、その2分の1を超える期間専ら事業に従事している場合"),
    ("N", "TA2070 扶養", "PS§4.3", "ta_2070", "青色事業専従者として給与の支払を受ける方は、同一生計配偶者や扶養親族にはなれません。"),
    # ---------- §5 純損失
    ("L", "所法2①二十五", "PS§5.1", "shotoku", B2, ("2", "1", "25"), "純損失の金額　第六十九条第一項（損益通算）に規定する損失の金額のうち同条の規定を適用してもなお控除しきれない部分の金額をいう。"),
    ("L", "所法69①", "PS§5.1", "shotoku", B2, ("69", "1"), "不動産所得の金額、事業所得の金額、山林所得の金額又は譲渡所得の金額の計算上生じた損失の金額…政令で定める順序により"),
    ("L", "所令198三(R7) 及び", "PS§5.1", "shotoku-rei", (R7,), ("198", "1", "3"), "譲渡所得の金額及び一時所得の金額"),
    ("L", "所令198三(R8) 又は", "PS§5.1", "shotoku-rei", (R8,), ("198", "1", "3"), "譲渡所得の金額又は一時所得の金額"),
    ("L", "所令198六(R7) 及び", "PS§5.1", "shotoku-rei", (R7,), ("198", "1", "6"), "譲渡所得の金額及び一時所得の金額"),
    ("L", "所令198六(R8) 又は", "PS§5.1", "shotoku-rei", (R8,), ("198", "1", "6"), "譲渡所得の金額又は一時所得の金額"),
    ("L", "所法70①", "PS§5.2", "shotoku", B2, ("70", "1"), "確定申告書を提出する居住者のその年の前年以前三年内の各年（その年分の所得税につき青色申告書を提出している年に限る。）において生じた純損失の金額（この項の規定により前年以前において控除されたもの及び第百四十二条第二項（純損失の繰戻しによる還付）の規定により還付を受けるべき金額の計算の基礎となつたものを除く。）"),
    ("L", "所法70②一", "PS§5.2", "shotoku", B2, ("70", "2", "1"), "変動所得の金額の計算上生じた損失の金額"),
    ("L", "所法70②二", "PS§5.2", "shotoku", B2, ("70", "2", "2"), "被災事業用資産の損失の金額"),
    ("L", "所法70③", "PS§5.2", "shotoku", B2, ("70", "3"), "被災事業用資産の損失の金額"),
    ("L", "所法70④", "PS§5.2", "shotoku", B2, ("70", "4"), "純損失の金額が生じた年分の所得税につき確定申告書を提出し、かつ、それぞれその後において連続して確定申告書を提出している場合に限り、適用する。"),
    ("L", "所法70の2 五年", "PS§5.2", "shotoku", B2, ("70_2", "1"), "前年以前五年内"),
    ("L", "所令201①一", "PS§5.2", "shotoku-rei", B2, ("201", "1", "1"), "これらの年のうち最も古い年に生じた純損失の金額から順次控除する"),
    ("L", "所令201①二", "PS§5.2", "shotoku-rei", B2, ("201", "1", "2"), "総所得金額の計算上生じた損失の部分の金額…これをまずその年分の総所得金額から控除する…山林所得金額の計算上生じた損失の部分の金額…これをまずその年分の山林所得金額から控除する…次に退職所得金額から控除する"),
    ("L", "所令201①三", "PS§5.2", "shotoku-rei", B2, ("201", "1", "3"), "その年分の各種所得の金額の計算上生じた損失の金額があるときは、まず法第六十九条（損益通算）の規定による控除を行つた後に法第七十条第一項又は第二項の規定による控除を行う。"),
    ("L", "所令201②", "PS§5.2", "shotoku-rei", B2, ("201", "2"), "特例対象純損失金額"),
    ("N", "所基通70−13", "PS§5.2", "kihon_15_01", "70－13…更正の請求に基づく更正により新たに純損失の金額があることとなった場合も含まれる"),
    ("N", "所基通70−14", "PS§5.2", "kihon_15_01", "70－14…更正"),
    ("N", "所基通70−15", "PS§5.2", "kihon_15_01", "70－15…当該相続人の総所得金額、退職所得金額又は山林所得金額の計算上控除することができないことに留意する"),
    ("L", "所法123①", "PS§5.2", "shotoku", B2, ("123", "1"), "純損失の金額"),
    ("L", "所法123③(R7)", "PS§5.2", "shotoku", B2, ("123", "3"), "第百二十条第三項から第七項までの規定は"),
    ("L", "所法123③(R9)", "PS§5.2", "shotoku", (R9,), ("123", "3"), "第百二十条第三項から第九項までの規定は"),
    ("L", "所法140①", "PS§5.3", "shotoku", B2, ("140", "1"), "青色申告書を提出する居住者は、その年において生じた純損失の金額がある場合には、当該申告書の提出と同時に、納税地の所轄税務署長に対し、第一号に掲げる金額から第二号に掲げる金額を控除した金額に相当する所得税の還付を請求することができる。"),
    ("L", "所法140①一", "PS§5.3", "shotoku", B2, ("140", "1", "1"), "前年分の課税総所得金額、課税退職所得金額及び課税山林所得金額"),
    ("L", "所法140②", "PS§5.3", "shotoku", B2, ("140", "2"), "当該所得税の額に相当する金額を限度とする"),
    ("L", "所法140③", "PS§5.3", "shotoku", B2, ("140", "3"), "政令で定める"),
    ("L", "所法140④", "PS§5.3", "shotoku", B2, ("140", "4"), "その年の前年分の所得税につき青色申告書を提出している場合であつて、その年分の青色申告書をその提出期限までに提出した場合（税務署長においてやむを得ない事情があると認める場合には、当該申告書をその提出期限後に提出した場合を含む。）に限り、適用する。"),
    ("L", "所法140⑤", "PS§5.3", "shotoku", B2, ("140", "5"), "同日の属する年の前年分及び前前年分の所得税につき青色申告書を提出している場合に限り、同日の属する年分の所得税に係る確定申告期限までに"),
    ("L", "所令272①", "PS§5.3", "shotoku-rei", B2, ("272", "1"), "事業の全部の相当期間の休止又は重要部分の譲渡"),
    ("L", "所法141", "PS§5.3", "shotoku", B2, ("141", "1"), "死亡"),
    ("L", "所法142①", "PS§5.3", "shotoku", B2, ("142", "1"), "その還付を受けようとする所得税の額、その計算の基礎その他財務省令で定める事項を記載した還付請求書"),
    ("L", "所法142③", "PS§5.3", "shotoku", B2, ("142", "3"), "還付加算金"),
    ("L", "所令271①一", "PS§5.3", "shotoku-rei", B2, ("271", "1", "1"), "これをまず前年分の課税総所得金額から控除する"),
    ("L", "所令271①二", "PS§5.3", "shotoku-rei", B2, ("271", "1", "2"), "課税山林所得金額"),
    ("L", "所令271①五", "PS§5.3", "shotoku-rei", B2, ("271", "1", "5"), "変動所得"),
    ("X", "所令271⑤なし（H9 の「同⑤」）", "H§H9", "shotoku-rei", B2, ("271", "5"), "＊"),
    ("L", "所令271①六", "PS§5.3", "shotoku-rei", B2, ("271", "1", "6"), "第九十条"),
    ("L", "所規54①", "PS§5.3", "shotoku-ki", B2, ("54", "1"), "当該青色申告書がその提出期限までに提出されなかつた事情の詳細"),
    ("N", "所基通140・141−2", "PS§5.3", "kihon_19_02", "法第120条第1項第3号《確定所得申告》に掲げる各種の税額控除後の所得税の額をいうことに留意する"),
    ("N", "所基通140・141−3", "PS§5.3", "kihon_19_02", "同時に提出されたかったことについて税務署長においてやむを得ない事情があると認めるときは、これを同時に提出されたものとして"),
    ("N", "所基通140・141−4", "PS§5.3", "kihon_19_02", "通則法第118条第1項《国税の課税標準の端数計算等》及び第119条第1項《国税の確定金額の端数計算等》の規定を準用する"),
    ("N", "所基通142−1", "PS§5.3", "kihon_19_02", "当該増加した部分の純損失の金額は繰戻しをすることができないものとし、当該金額については、法第70条第1項《純損失の繰越控除》の規定を適用する"),
    ("N", "A1-4 時期", "PS§5.3", "annai_23200002", "確定申告期限内に提出してください"),
    ("N", "TA2070 繰戻し", "PS§5.3", "ta_2070", "前年も青色申告をしている場合は、純損失の繰越しに代えて、その損失額を生じた年の前年分の所得金額に繰り戻して控除し、前年分の所得税額の還付を受けることもできます。"),
    # ---------- §6 現金主義
    ("L", "所法67①", "PS§6", "shotoku", B2, ("67", "1"), "青色申告書を提出することにつき税務署長の承認を受けている居住者で不動産所得又は事業所得を生ずべき業務を行うもののうち小規模事業者として政令で定める要件に該当するもの…その年において収入した金額及び支出した費用の額とすることができる"),
    ("L", "所令195一", "PS§6", "shotoku-rei", B2, ("195", "1", "1"), "その年の前々年分の不動産所得の金額及び事業所得の金額（法第五十七条（事業に専従する親族がある場合の必要経費の特例等）の規定を適用しないで計算した場合の金額とする。）の合計額が三百万円以下であること"),
    ("L", "所令195二", "PS§6", "shotoku-rei", B2, ("195", "1", "2"), "承認を受けた者"),
    ("L", "所令196②", "PS§6", "shotoku-rei", B2, ("196", "2"), "償却費並びに法第五十一条第一項及び第四項（資産損失の必要経費算入）の規定の適用を受けるものを除き"),
    ("L", "所令197①", "PS§6", "shotoku-rei", B2, ("197", "1"), "その年三月十五日まで（その年一月十六日以後新たに同項に規定する業務を開始した場合には、その業務を開始した日から二月以内）に、同項の規定の適用を受けようとする旨その他財務省令で定める事項を記載した届出書"),
    ("L", "所令197②", "PS§6", "shotoku-rei", B2, ("197", "2"), "その年三月十五日までに、その適用を受けることをやめる旨"),
    ("L", "所規39の2①", "PS§6", "shotoku-ki", B2, ("39_2", "1"), "一月三十一日までに"),
    ("L", "所規39の2 みなし", "PS§6", "shotoku-ki", B2, ("39_2",), "三月十五日…承認があつたものとみなす"),
    ("L", "所規40①", "PS§6", "shotoku-ki", B2, ("40", "1"), "売掛金、買掛金、未収収益、前受収益、前払費用、未払費用その他これらに類する資産及び負債並びに棚卸資産"),
    ("L", "所規40の2①", "PS§6", "shotoku-ki", B2, ("40_2", "1"), "十二月三十一日"),
    ("N", "所基通67−1", "PS§6", "kihon_14_02", "法第67条第１項の規定の適用を受けようとする年の前年末現在において確定しているところにより、また、当該前々年分の不動産所得又は事業所得のいずれかに赤字が生じている場合には、当該赤字の金額は他の黒字の金額と相殺したところにより判定するものとする"),
    ("N", "所基通67−5", "PS§6", "kihon_14_02", "67－5…当該被相続人についての所得税の準確定申告書の提出期限"),
    ("N", "A1-12 小規模", "PS§6", "annai_23200010", "小規模事業者とは、その年の前々年分の不動産所得の金額及び事業所得の金額（事業専従者給与（控除）の額を必要経費に算入しないで計算した金額）の合計額が300万円以下である方のことです。"),
]


def run_claims():
    out = []
    for c in CLAIMS:
        kind = c[0]
        if kind in ("L", "X"):
            _, cid, ref, short, asofs, path, quote = c
            for a in asofs:
                t = loc_text(short, a, path)
                if kind == "X":
                    ok = (t is None) if quote == "＊" else (t is not None and nz(quote) not in nz(t))
                    out.append({"id": cid, "ref": ref, "target": f"{short}@{a} {'/'.join(path)}", "kind": "absent", "ok": ok})
                    continue
                ok, miss = (False, "（位置が見つからない）") if t is None else seq_in(t, quote)
                out.append({"id": cid, "ref": ref, "target": f"{short}@{a} {'/'.join(path)}", "kind": "law", "ok": ok, "missing": miss})
        elif kind == "S":
            _, cid, ref, short, a, amend, art, path, quote = c
            t = suppl_text(short, a, amend, art, path)
            ok, miss = (False, "（附則の位置が見つからない）") if t is None else seq_in(t, quote)
            out.append({"id": cid, "ref": ref, "target": f"{short}@{a} 附則({amend}) 第{art}条 {'/'.join(path)}", "kind": "suppl",
                        "ok": ok, "missing": miss})
        elif kind == "N":
            _, cid, ref, page, quote = c
            t = nta_txt(page)
            ok, miss = (False, "（ページなし）") if t is None else seq_in(t, quote)
            out.append({"id": cid, "ref": ref, "target": f"nta/{page}", "kind": "nta", "ok": ok, "missing": miss})
    return out


# [PS]§0.1・[M]§2.1 の版（略称, asof, law_revision_id, 改正法令, 施行日, 状態, SHA-256 先頭16桁）
REVS = [
    ("shotoku", R7, "340AC0000000033_20251218_507AC0000000013", "令和七年法律第十三号", "2025-12-18", "PreviousEnforced", "84a2235cb4437184"),
    ("shotoku", R8, "340AC0000000033_20261201_508AC0000000012", "令和八年法律第十二号", "2026-12-01", "UnEnforced", "47792299f0fb5a74"),
    ("shotoku", R9, "340AC0000000033_20270101_508AC0000000012", "令和八年法律第十二号", "2027-01-01", "UnEnforced", "d4bf435220bc0b0c"),
    ("shotoku-rei", R7, "340CO0000000096_20251201_507CO0000000120", "令和七年政令第百二十号", "2025-12-01", "PreviousEnforced", "e972344f436ecd9b"),
    ("shotoku-rei", R8, "340CO0000000096_20261201_508CO0000000093", "令和八年政令第九十三号", "2026-12-01", "UnEnforced", "cd63914bb5962edf"),
    ("shotoku-rei", R9, "340CO0000000096_20270101_508CO0000000093", "令和八年政令第九十三号", "2027-01-01", "UnEnforced", "f4965711894ea1c7"),
    ("shotoku-ki", R7, "340M50000040011_20251201_507M60000040018", "令和七年財務省令第十八号", "2025-12-01", "PreviousEnforced", "16358c775e2d1dcc"),
    ("shotoku-ki", R8, "340M50000040011_20261211_508M60000040017", "令和八年財務省令第十七号", "2026-12-11", "UnEnforced", "9ba37bf34afed1f9"),
    ("shotoku-ki", R9, "340M50000040011_20270101_508M60000040017", "令和八年財務省令第十七号", "2027-01-01", "UnEnforced", "1600117df38c4463"),
    ("shotoku-ki", TODAY, "340M50000040011_20261001_507M60000040018", "令和七年財務省令第十八号", "2026-10-01", "CurrentEnforced", None),
    ("sochi", R7, "332AC0000000026_20251231_507AC1000000081", "令和七年法律第八十一号", "2025-12-31", "PreviousEnforced", "ef95d90f7bf57e18"),
    ("sochi", R8, "332AC0000000026_20261204_508AC0000000012", "令和八年法律第十二号", None, "UnEnforced", "763fce2df2b1e709"),
    ("sochi", R9, "332AC0000000026_20270101_508AC0000000012", "令和八年法律第十二号", "2027-01-01", "UnEnforced", "8c6ee577201c3be0"),
    ("sochi-ki", R7, "332M50000040015_20251231_507M60000040068", "令和七年財務省令第六十八号", "2025-12-31", "PreviousEnforced", "e61bd52d88b1484a"),
    ("sochi-ki", R8, "332M50000040015_20261204_508M60000040021", "令和八年財務省令第二十一号", None, "UnEnforced", "03b356f8297e93b7"),
    ("sochi-ki", R9, "332M50000040015_20270101_508M60000040021", "令和八年財務省令第二十一号", "2027-01-01", "UnEnforced", "106cc5bcfb7fb9be"),
    ("denchou", R7, "410AC0000000025_20250401_507AC0000000013", "令和七年法律第十三号", "2025-04-01", "CurrentEnforced", "81885682cdf2beae"),
    ("denchou", R8, "410AC0000000025_20250401_507AC0000000013", "令和七年法律第十三号", "2025-04-01", "CurrentEnforced", "81885682cdf2beae"),
    ("denchou", R9, "410AC0000000025_20270101_507AC0000000013", "令和七年法律第十三号", "2027-01-01", "UnEnforced", "e3da96443d6cd7d8"),
    ("denchou-ki", R7, "410M50000040043_20250401_507M60000040028", "令和七年財務省令第二十八号", "2025-04-01", "CurrentEnforced", "15786f1ae7140c2a"),
    ("denchou-ki", R8, "410M50000040043_20250401_507M60000040028", "令和七年財務省令第二十八号", "2025-04-01", "CurrentEnforced", "15786f1ae7140c2a"),
    ("denchou-ki", R9, "410M50000040043_20270101_507M60000040028", "令和七年財務省令第二十八号", "2027-01-01", "UnEnforced", "5138459ca02073b7"),
]


def run_revs():
    out = []
    for short, a, rid, law, ed, st, sha in REVS:
        d = eg(short, a)
        ri = d["revision_info"] if d else {}
        r = {"target": f"{short}@{a}", "claimed": [rid, law, ed, st, sha],
             "got": [ri.get("law_revision_id"), ri.get("amendment_law_num"), ri.get("amendment_enforcement_date"),
                     ri.get("current_revision_status"), (d or {}).get("sha256", "")[:16]]}
        r["ok_revision"] = r["claimed"][:4] == r["got"][:4]
        r["sha_same"] = None if sha is None else (sha == r["got"][4])
        out.append(r)
    return out


# [M]§4.2：時点の間で本文が違う条の一覧（担当の主張）
DIFF_R7_R8 = {"shotoku": {"2", "151"}, "shotoku-rei": {"165", "198"}, "shotoku-ki": {"48", "66"}}
DIFF_R8_R9 = {"shotoku": {"123"}, "shotoku-ki": {"36_4", "55"}, "sochi": {"25_2"}, "sochi-ki": {"9_6"},
              "denchou": {"8"}, "denchou-ki": {"2", "5"}}
SCOPE_ARTS = {  # 担当が取り出した条（[PS]§0.1）。この範囲で比べる
    "shotoku": ["2", "57", "67", "69", "70", "70_2", "123", "140", "141", "142", "143", "144", "145", "146", "147", "148", "149", "150", "151", "155", "232"],
    "shotoku-rei": ["164", "165", "166", "167", "195", "196", "197", "198", "201", "271", "272"],
    "shotoku-ki": ["36_4", "39_2", "40", "40_2", "48", "54", "55", "56", "57", "58", "59", "60", "61", "62", "63", "64", "65", "66"],
    "sochi": ["25_2"], "sochi-ki": ["9_6"], "denchou": ["2", "4", "8"], "denchou-ki": ["2", "5"],
}


def run_article_diffs():
    res = {"R7_vs_R8": {}, "R8_vs_R9": {}, "mismatch_with_claim": []}
    for short, arts in SCOPE_ARTS.items():
        for x, y, key, claim in ((R7, R8, "R7_vs_R8", DIFF_R7_R8), (R8, R9, "R8_vs_R9", DIFF_R8_R9)):
            diff = set()
            for art in arts:
                a, b = loc_text(short, x, (art,)), loc_text(short, y, (art,))
                if nz(a) != nz(b):
                    diff.add(art)
            res[key][short] = sorted(diff)
            if diff != claim.get(short, set()):
                res["mismatch_with_claim"].append({"pair": key, "short": short, "got": sorted(diff), "claimed": sorted(claim.get(short, set()))})
    return res


# [M]§3.2・§3.3 の Last-Modified と SHA-256（先頭16桁）
NTA_META = {
    "ta_2070": ("2026-09-09", "2f280b15db8d1691"), "ta_2072": ("2026-09-09", "de4d48788c2cdaf2"),
    "ta_2075": ("2026-09-09", "e8f8fde1bfd353d8"), "ta_2250": ("2026-09-09", "81cabb299948105a"),
    "kihon_11_01": ("2024-01-18", "357de2fabe640a6a"), "kihon_14_02": ("2025-12-25", "4852d0a64b63aaf6"),
    "kihon_15_01": ("2025-11-25", "ead14cdf750a9590"), "kihon_19_02": ("2025-11-25", "a9a3b2a8f9de88eb"),
    "kihon_20_01": ("2024-01-18", "096ae07ac0983fe3"), "sochitsu_25_2": ("2026-10-02", "fab8f8e21c5edece"),
    "mokuji": ("2026-10-07", "94182e6dd8881c21"),
    "annai_09": ("2026-10-28", "c9133cca3a85ca4a"), "annai_09_2": ("2026-10-28", "e2fed007d5fbb06f"),
    "annai_10": ("2026-10-28", "a9de82dfd1b81aa1"), "annai_12": ("2026-10-28", "c21c732bb154f8c9"),
    "annai_23200008": ("2026-10-28", "c31d320b3a756747"), "annai_13": ("2026-10-28", "05d56742a9bd12eb"),
    "annai_17_0": ("2026-10-28", "3bf159272f0bf645"), "annai_23200002": ("2026-10-28", "4d49bf49d81d59b8"),
    "annai_23200010": ("2026-10-28", "67e3638f2ec510fd"), "annai_23200011": ("2026-10-28", "35d064453b7c993d"),
    "annai_23200016": ("2026-10-28", "1707f2fece682758"),
    "pdf_kessan_ippan": ("2026-08-31", "c3cd9d17c0174972"), "pdf_kessan_genkin": ("2026-08-31", "184a71c5efda112d"),
    "pdf_dai4": ("2026-08-31", "10dfa7825ae19b64"), "pdf_shinsei": ("2026-06-30", "a4e3fc8b15abe41e"),
    "pdf_shinsei_ki": ("2026-06-30", "77baaa0debf60e28"), "pdf_shinsei_genkin": ("2024-01-18", "87a8138c4e6a5629"),
    "pdf_senju": ("2026-06-30", "5684a36c2b96b0df"), "pdf_senju_ki": ("2026-06-30", "c8689907257f5eb7"),
    "pdf_yame": ("2026-06-30", "b36c35c0329719cf"), "pdf_yame_ki": ("2026-06-30", "ce784ca32f5e24d5"),
    "pdf_genkin": ("2026-06-30", "72118e58a7f3bdb1"), "pdf_65man": ("2026-06-30", "b507448e6a1ab684"),
    "pdf_65man_ki": ("2026-06-30", "1dde8a4fd0d2e94d"), "pdf_kurimodoshi": ("2026-06-30", "9b7c9881634f8fea"),
    "pdf_kurimodoshi_ki": ("2026-06-30", "83b51e9daf2e2ad9"), "pdf_kakikata_037": ("2025-12-12", "77c8ad203bbd04ef"),
    "pdf_tebiki_025": ("2025-12-12", "d688dd73e82a13b5"), "pdf_sonshitsu_003": ("2025-12-12", "e3a89abd687f659d"),
}
# [M]§3.3 の頁数（AES-256 の3つは [M] に頁数の記載がないので、[PS]§3.2・§5.2 が読んだ頁が存在するかだけを見る＝None）
PDF_PAGES = {"pdf_kessan_ippan": 4, "pdf_kessan_genkin": 2, "pdf_dai4": 2, "pdf_shinsei": 1, "pdf_shinsei_ki": 1, "pdf_shinsei_genkin": 2,
             "pdf_senju": 1, "pdf_senju_ki": 1, "pdf_yame": 1, "pdf_yame_ki": 1, "pdf_genkin": 2, "pdf_65man": 1, "pdf_65man_ki": 2,
             "pdf_kurimodoshi": 1, "pdf_kurimodoshi_ki": 1, "pdf_kakikata_037": 8, "pdf_tebiki_025": 8, "pdf_sonshitsu_003": 16}
# [M]§3.3 の暗号の種類（V, R）
PDF_ENC = {"pdf_kakikata_037": (5, 6), "pdf_tebiki_025": (5, 6), "pdf_sonshitsu_003": (5, 6)}


def run_nta_meta():
    log = json.loads((OUT / "nta_log.json").read_text(encoding="utf-8"))
    items = {i["id"]: i for i in log["items"]}
    out = []
    for k, (lm, sha) in NTA_META.items():
        it = items.get(k, {})
        got_lm = None
        if it.get("last_modified"):
            got_lm = dt.datetime.strptime(it["last_modified"], "%a, %d %b %Y %H:%M:%S GMT").strftime("%Y-%m-%d")
        r = {"id": k, "url": it.get("url"), "status": it.get("status"), "lm_claimed": lm, "lm_got": got_lm, "lm_ok": lm == got_lm,
             "sha_claimed": sha, "sha_got": (it.get("sha256") or "")[:16], "sha_same": sha == (it.get("sha256") or "")[:16]}
        if k.startswith("pdf_"):
            # 保存した PDF をバイト列として読み、/Encrypt の辞書の /V・/R・/CFM を取り出す（中身は実行しない）
            pdf = (ROOT / it["saved"]).read_bytes()
            tr = re.search(rb"/Encrypt\s+(\d+)\s+0\s+R", pdf)
            ed = pdf_objects(pdf).get(int(tr.group(1)), (0, b"", None))[1] if tr else b""
            v = re.search(rb"/V\s+(\d+)", ed)
            rr = re.search(rb"/R\s+(\d+)", ed)
            cfm = re.search(rb"/CFM\s*/(\w+)", ed)
            r["enc_VR_got"] = (int(v.group(1)) if v else None, int(rr.group(1)) if rr else None)
            r["enc_CFM"] = cfm.group(1).decode() if cfm else None
            objs = pdf_objects(pdf)
            key, info = pdf_key(pdf, objs)
            if info.get("unsupported"):
                # AES-256 は復号しない。ページツリーの根の辞書（暗号化されない）の /Count を読む（/Type と /Count の順序はどちらもありうる）
                cm = re.findall(rb"/Type\s*/Pages\b[^>]*?/Count\s+(\d+)|/Count\s+(\d+)[^>]*?/Type\s*/Pages\b", pdf)
                r["pages_got"] = max(int(a or b) for a, b in cm) if cm else None
            else:
                r["key_ok"] = info.get("key_ok")
                expand_objstm(objs, key)
                r["pages_got"] = len(page_streams(pdf, objs, key))
            r["pages_claimed"] = PDF_PAGES.get(k)
            r["pages_ok"] = r["pages_got"] == r["pages_claimed"]
            r["enc_VR_claimed"] = PDF_ENC.get(k, (4, 4))
            r["enc_ok"] = r["enc_VR_got"] == r["enc_VR_claimed"]
        out.append(r)
    return out


# [PS]§0.2 の様式・手引きの URL が、国税庁の一覧・手続の案内のリンクにあるか（リンク先, 題の一部）
LINKS = [
    ("yoshiki_r07", "shinkokusho/pdf/r07/10.pdf", "所得税青色申告決算書（一般用）【令和５年分以降用】"),
    ("yoshiki_r07", "tebiki/2025/pdf/037.pdf", "青色申告決算書（一般用）の書き方"),
    ("yoshiki_r07", "tebiki/2025/pdf/025.pdf", "青色申告の決算の手引き（一般用）"),
    ("yoshiki_r07", "shinkokusho/pdf/r07/13.pdf", "所得税青色申告決算書（現金主義用）【令和２年分以降用】"),
    ("yoshiki_r07", "shinkokusho/pdf/r07/03.pdf", "第四表"),
    ("yoshiki_r07", "tebiki/2025/pdf/003.pdf", "損失申告用"),
    ("annai_09", "pdf/h28/10.pdf", ""), ("annai_09", "pdf/h28/10-ki.pdf", ""), ("annai_10", "pdf/h28/11.pdf", ""),
    ("annai_12", "pdf/h28/13_14.pdf", ""), ("annai_12", "pdf/h28/13_14-ki.pdf", ""), ("annai_23200008", "pdf/h28/12.pdf", ""),
    ("annai_23200008", "pdf/h28/12-ki.pdf", ""), ("annai_23200010", "pdf/h28/15.pdf", ""), ("annai_09_2", "pdf/r03/01.pdf", ""),
    ("annai_09_2", "pdf/r03/01-ki.pdf", ""), ("annai_23200002", "pdf/03_r05.pdf", ""), ("annai_23200002", "pdf/03_r05-ki.pdf", ""),
]


def run_links():
    out = []
    for page, href, text in LINKS:
        p = OUT / "nta" / f"{page}.links.json"
        links = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
        hit = [x for x in links if x["href"].endswith(href) and nz(text) in nz(x["text"])]
        out.append({"page": page, "href": href, "text": text, "ok": bool(hit), "texts": [x["text"] for x in hit][:2]})
    return out


# [PS]§7.1：1ページの欄の番号・科目・欄コード
P1_TABLE = {
    "G01": "売上（収入）金額", "G02": "期首商品（製品）棚卸高", "G03": "仕入金額", "G04": "小計", "G05": "期末商品（製品）棚卸高",
    "G06": "差引原価", "G07": "差引金額", "G08": "租税公課", "G09": "荷造運賃", "G10": "水道光熱費", "G11": "旅費交通費",
    "G12": "通信費", "G13": "広告宣伝費", "G14": "接待交際費", "G15": "損害保険料", "G16": "修繕費", "G17": "消耗品費",
    "G18": "減価償却費", "G19": "福利厚生費", "G20": "給料賃金", "G21": "外注工賃", "G22": "利子割引料", "G23": "地代家賃",
    "G24": "貸倒金", "G31": "雑費", "G32": "計", "G33": "差引金額", "G34": "貸倒引当金", "G37": "計", "G38": "専従者給与",
    "G39": "貸倒引当金", "G42": "計", "G43": "青色申告特別控除前の所得金額", "G44": "青色申告特別控除額", "G45": "所得金額",
}
P1_NUM = {f"G{n:02d}": str(n) for n in range(1, 46)}


def run_pdf_checks():
    res = {}
    rows = pdf_rows("kessan_ippan")
    # 様式ID
    res["formid"] = {p: [s for (pg, x, y, f, s) in rows if pg == p and s.startswith("NTA0")] for p in (1, 2, 3, 4)}
    res["formid_ok"] = res["formid"] == {1: ["NTA0KOA210010110"], 2: ["NTA0KOA210020110"], 3: ["NTA0KOA210030110"], 4: ["NTA0KOA210040110"]}
    # 1ページの欄コードと科目（コードの左 150pt・上下 −12〜+8pt の文字列）
    p1 = [(x, y, s) for (pg, x, y, f, s) in rows if pg == 1]
    m = {}
    for cx, cy, c in [(x, y, s) for x, y, s in p1 if re.fullmatch(r"G\d\d", s)]:
        near = sorted([(x, y, s) for x, y, s in p1 if cx - 150 <= x < cx and cy - 12 <= y <= cy + 8 and not re.fullmatch(r"G\d\d", s)],
                      key=lambda t: (-t[1], t[0]))
        m[c] = [s for _, _, s in near]
    chk = {}
    for code in sorted(m):
        joined = nz("".join(m[code]))
        want = P1_TABLE.get(code)
        chk[code] = {"near": m[code], "num_ok": P1_NUM[code] in [nz(s) for s in m[code]],
                     "label_ok": None if want is None else re.sub(r"[()0-9]", "", nz(want)) in re.sub(r"[()0-9+\-]", "", joined)}
    res["p1"] = chk
    res["p1_codes"] = sorted(m)
    res["p1_all_ok"] = sorted(m) == [f"G{n:02d}" for n in range(1, 46)] and all(v["num_ok"] and v["label_ok"] in (True, None) for v in chk.values())
    # 各ページの「（令和五年分以降用）」
    res["r5_label_pages"] = sorted({pg for (pg, x, y, f, s) in rows if "令和五年分以降用" in nz(s)})
    # 2ページの青色申告特別控除額の計算（ページの文字列を出現順につないで照合）
    pages = {}
    for (pg, x, y, f, s) in rows:
        pages.setdefault(pg, []).append(s)
    p2 = "".join(pages.get(2, []))
    res["p2_quotes"] = {q: seq_in(p2, q)[0] for q in (
        "青色申告特別控除額の計算", "本年分の不動産所得の金額", "青色申告特別控除前の所得金額", "65万円又は55", "万円の青色申", "告特別控除", "を受ける場合",
        "65万円又は55万円と…のいずれか少ない方の金額", "「65万円又は55万円－…」と", "上…記…以…外", "10万円と…のいずれか少ない方の金額", "「10万円―…」と",
        "不動産所得から差し引かれる…青色申告特別控除額です。", "１ページの「損益計算書」の…欄の金額を書いてください。",
        "×5.5％", "3.3％", "専従者給与の内訳", "給料賃金の内訳", "地代家賃の内訳", "貸倒引当金繰入額の計算")}
    p4 = "".join(pages.get(4, []))
    res["p4_quotes"] = {q: seq_in(p4, q)[0] for q in ("貸借対照表", "資産負債調", "元入金", "事業主貸", "事業主借", "製造原価の計算",
                                                      "欄の金額は、1ページの「損益計算書」の…欄に移記してください。",
                                                      "原価計算を行っていない人は、記入する必要はありません。")}
    # 4ページの欄コードの列
    p4codes = [(x, s) for (pg, x, y, f, s) in rows if pg == 4 and re.fullmatch(r"G\d\d", s)]
    cols = {}
    for x, s in p4codes:
        cols.setdefault(round(x), []).append(int(s[1:]))
    res["p4_columns"] = {str(k): [min(v), max(v), len(v)] for k, v in sorted(cols.items())}
    # 現金主義用
    g = pdf_rows("kessan_genkin")
    gp = {}
    for (pg, x, y, f, s) in g:
        gp.setdefault(pg, []).append(s)
    gall = "".join(s for pg in sorted(gp) for s in gp[pg])
    res["genkin"] = {"formid": sorted({s for (pg, x, y, f, s) in g if s.startswith("NTA0")}),
                     "has_10man": seq_in(gall, "10万円と")[0], "has_65man": "65万円" in nz(gall), "has_bs": "貸借対照表" in nz(gall),
                     "has_label17": seq_in(gall, "青色申告特別控除前の所得金額")[0]}
    return res


# ---------------------------------------------------------------- 推測の計算例を別の式で計算し直す
def bracket_tax(taxable):
    """所法89①（課税総所得金額。千円未満切捨て済み）。区分ごとの速算表ではなく、各段の幅×率の和で計算する。"""
    edges = [0, 1_950_000, 3_300_000, 6_950_000, 9_000_000, 18_000_000, 40_000_000, 10**15]
    rates = [5, 10, 20, 23, 33, 40, 45]
    t = 0
    for lo, hi, r in zip(edges, edges[1:], rates):
        if taxable > lo:
            t += (min(taxable, hi) - lo) * r
    return t // 100


def v_tokubetsu_r7r8(inc, jigyo_teki_fudosan, seiki, genkin, filing, denshi_yuryo_todoke):
    """filing: 'etax_ontime' | 'paper_ontime' | 'late'。inc: {'fudosan','jigyo','sanrin'}（無ければ None）。"""
    eigyo = inc.get("jigyo") is not None or jigyo_teki_fudosan
    pos = {k: max(inc.get(k) or 0, 0) for k in ("fudosan", "jigyo", "sanrin")}
    base3 = eigyo and seiki and not genkin                                 # ③の「場合」
    if base3 and filing == "etax_ontime":
        cap, keys = 650_000, ("fudosan", "jigyo")                          # ④二（⑥の括弧で⑥は不要）
    elif base3 and filing == "paper_ontime" and denshi_yuryo_todoke:
        cap, keys = 650_000, ("fudosan", "jigyo")                          # ④一＋⑥
    elif base3 and filing == "paper_ontime":
        cap, keys = 550_000, ("fudosan", "jigyo")                          # ③＋⑥
    else:
        cap, keys = 100_000, ("fudosan", "jigyo", "sanrin")                # ①
    total = min(cap, sum(pos[k] for k in keys))
    left, parts = total, {}
    for k in keys:
        parts[k] = min(left, pos[k])
        left -= parts[k]
    return total, parts


def v_tokubetsu_r9(inc, seiki, genkin, etax_ontime, extra, zenzen_jigyo, reading):
    """reading: 'A'＝②の「第四項に規定する場合」を正規の簿記の記録の場合と読む／'B'＝④の控除を受ける場合と読む。"""
    pos = {k: max(inc.get(k) or 0, 0) for k in ("fudosan", "jigyo", "sanrin")}
    case4 = inc.get("jigyo") is not None and seiki and not genkin
    if case4 and etax_ontime:
        return min(750_000 if extra else 650_000, pos["fudosan"] + pos["jigyo"])
    over = inc.get("jigyo") is not None and zenzen_jigyo > 10_000_000 and not genkin
    in_case4 = case4 if reading == "A" else False
    if over and not in_case4:
        return 0
    return min(100_000, sum(pos.values()))


def v_kurikoshi(losses, incomes):
    remain = dict(losses)
    used = {}
    for y in sorted(incomes):
        avail = incomes[y]
        for ly in sorted(remain):
            if y - 3 <= ly < y and avail > 0 and remain[ly] > 0:
                d = min(avail, remain[ly])
                remain[ly] -= d
                avail -= d
                used.setdefault(y, []).append((ly, d))
        used.setdefault(y, [])
    expired = {ly: v for ly, v in remain.items() if max(incomes) >= ly + 3}
    return used, remain, expired


def v_age_at(birth, ref):
    """年齢計算ニ関スル法律・民法143：出生の日から起算し、応当日の前日の終了で年齢が加わる。ref の日の終わりの年齢。"""
    def anniv(n):
        try:
            return birth.replace(year=birth.year + n)
        except ValueError:  # 2月29日生まれ
            return dt.date(birth.year + n, 3, 1)
    n = 0
    while anniv(n + 1) - dt.timedelta(days=1) <= ref:
        n += 1
    return n


def add_months_deadline(start, months, first_day_counts=False):
    """通則法10①：初日不算入（算入する読みも計算できる）、月は暦に従い、起算日の応当日の前日に満了。"""
    s = start if first_day_counts else start + dt.timedelta(days=1)
    y, m = s.year, s.month + months
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    import calendar
    last = calendar.monthrange(y, m)[1]
    if s.day > last:
        return dt.date(y, m, last)
    return dt.date(y, m, s.day) - dt.timedelta(days=1)


def run_examples():
    ex = {}
    T = lambda **k: v_tokubetsu_r7r8(**k)[0]  # noqa: E731
    d = dict(jigyo_teki_fudosan=False, seiki=True, genkin=False, filing="etax_ontime", denshi_yuryo_todoke=False)
    ex["T1"] = (T(inc={"jigyo": 3_000_000}, **d), 650_000)
    ex["T2"] = (T(inc={"jigyo": 400_000}, **d), 400_000)
    ex["T3"] = (v_tokubetsu_r7r8({"jigyo": 2_000_000, "fudosan": -500_000}, **{**d, "jigyo_teki_fudosan": True}), (650_000, {"fudosan": 0, "jigyo": 650_000}))
    ex["T4"] = (T(inc={"jigyo": 3_000_000}, **{**d, "filing": "paper_ontime"}), 550_000)
    ex["T5"] = (T(inc={"jigyo": 3_000_000}, **{**d, "filing": "late"}), 100_000)
    ex["T6"] = (T(inc={"jigyo": 3_000_000}, **{**d, "seiki": False}), 100_000)
    ex["T7"] = (T(inc={"jigyo": 3_000_000}, **{**d, "genkin": True}), 100_000)
    ex["T8"] = (T(inc={"fudosan": 800_000}, **d), 100_000)
    ex["T9"] = (v_tokubetsu_r7r8({"fudosan": 300_000, "jigyo": 200_000}, **d), (500_000, {"fudosan": 300_000, "jigyo": 200_000}))
    ex["T10"] = (T(inc={"jigyo": -1_000_000}, **d), 0)
    ex["T11"] = (T(inc={"jigyo": 3_000_000}, **{**d, "filing": "paper_ontime", "denshi_yuryo_todoke": False}), 550_000)
    ex["T12"] = (T(inc={"jigyo": 3_000_000}, **{**d, "filing": "paper_ontime", "denshi_yuryo_todoke": True}), 650_000)
    for name, kw, want in (
        ("R9_1", dict(seiki=False, etax_ontime=True, extra=False, zenzen_jigyo=12_000_000), {"A": 0, "B": 0}),
        ("R9_2", dict(seiki=True, etax_ontime=False, extra=False, zenzen_jigyo=12_000_000), {"A": 100_000, "B": 0}),
        ("R9_3", dict(seiki=False, etax_ontime=True, extra=False, zenzen_jigyo=9_000_000), {"A": 100_000, "B": 100_000}),
        ("R9_4", dict(seiki=True, etax_ontime=True, extra=False, zenzen_jigyo=0), {"A": 650_000, "B": 650_000}),
        ("R9_5", dict(seiki=True, etax_ontime=True, extra=True, zenzen_jigyo=0), {"A": 750_000, "B": 750_000}),
        ("R9_6", dict(seiki=True, etax_ontime=False, extra=False, zenzen_jigyo=0), {"A": 100_000, "B": 100_000}),
    ):
        ex[name] = ({r: v_tokubetsu_r9({"jigyo": 3_000_000}, genkin=False, reading=r, **kw) for r in ("A", "B")}, want)
    # 繰戻し
    def kuri(prev, loss, cap):
        a = bracket_tax(prev // 1000 * 1000) // 100 * 100
        b = bracket_tax(max(prev - loss, 0) // 1000 * 1000) // 100 * 100
        return min(a - b, cap), a, b
    ex["K1"] = (kuri(3_000_000, 1_000_000, 10**12), (100_000, 202_500, 102_500))
    ex["K2"] = (kuri(1_500_000, 3_000_000, 10**12), (75_000, 75_000, 0))
    ex["K3"] = (kuri(3_000_000, 1_000_000, 50_000), (50_000, 202_500, 102_500))
    ex["K2_一部(150万)"] = (kuri(1_500_000, 1_500_000, 10**12), (75_000, 75_000, 0))
    ex["C1"] = (v_kurikoshi({2025: 1_000_000}, {2026: 600_000, 2027: 600_000})[0], {2026: [(2025, 600_000)], 2027: [(2025, 400_000)]})
    u, rem, exp = v_kurikoshi({2025: 1_000_000}, {2026: 0, 2027: 0, 2028: 200_000, 2029: 2_000_000})
    ex["C2"] = ((u, exp), ({2026: [], 2027: [], 2028: [(2025, 200_000)], 2029: []}, {2025: 800_000}))
    ex["C3"] = (v_kurikoshi({2025: 500_000, 2026: 500_000}, {2027: 700_000})[:2], ({2027: [(2025, 500_000), (2026, 200_000)]}, {2025: 0, 2026: 300_000}))
    ex["S1"] = (v_age_at(dt.date(2010, 12, 31), dt.date(2025, 12, 31)) >= 15, True)
    ex["S2"] = (v_age_at(dt.date(2011, 1, 1), dt.date(2025, 12, 31)) >= 15, True)
    ex["S3"] = (v_age_at(dt.date(2011, 1, 2), dt.date(2025, 12, 31)) >= 15, False)
    # I6 の期限と曜日
    ex["I6_2026-03-01開業_初日不算入"] = (str(add_months_deadline(dt.date(2026, 3, 1), 2)), "2026-05-01")
    ex["I6_2026-03-01開業_初日算入"] = (str(add_months_deadline(dt.date(2026, 3, 1), 2, True)), "2026-04-30")
    ex["I6_2026-11-15開業"] = (str(add_months_deadline(dt.date(2026, 11, 15), 2)), "2027-01-15")
    ex["I6_2026-03-15の曜日"] = (dt.date(2026, 3, 15).strftime("%A"), "Sunday")
    ex["I6_2027-03-15の曜日"] = (dt.date(2027, 3, 15).strftime("%A"), "Monday")
    ex["I6_2026-05-01の曜日"] = (dt.date(2026, 5, 1).strftime("%A"), "Friday")
    ex["I6_2027-01-15の曜日"] = (dt.date(2027, 1, 15).strftime("%A"), "Friday")
    # I5 の期間（日数と月）
    ex["I5_1/1〜7/10"] = ((dt.date(2025, 7, 10) - dt.date(2025, 1, 1)).days + 1, 191)
    # I9：決算書の写し（売上1,000万・仕入600万・経費100万）
    s, cogs, exp_ = 10_000_000, 6_000_000, 1_000_000
    l7 = s - cogs
    l33 = l7 - exp_
    l44 = T(inc={"jigyo": l33}, **d)
    ex["I9"] = ((l7, l33, l33, l44, l33 - l44), (4_000_000, 3_000_000, 3_000_000, 650_000, 2_350_000))
    return {k: {"got": v[0], "want": v[1], "ok": v[0] == v[1]} for k, v in ex.items()}


def run_appdx():
    """[M]§2.1：所規の別表は「別表第一　削除」の1件だけか（保存した e-Gov の JSON を読む）。"""
    out = {}
    for a in (R7, R8, R9):
        d = eg("shotoku-ki", a)
        raw = json.loads((ROOT / d["raw"]).read_text(encoding="utf-8"))
        titles = []
        walk(raw["law_full_text"], lambda n, pth: titles.append(
            "".join(flat(c) for c in kids(n, "AppdxTableTitle")) + "|" + flat(n)[:40]) if n.get("tag") == "AppdxTable" else None)
        out[a] = titles
    return out


def mode_check():
    claims = run_claims()
    revs = run_revs()
    diffs = run_article_diffs()
    meta = run_nta_meta()
    links = run_links()
    pdfc = run_pdf_checks()
    exs = run_examples()
    egl = json.loads((OUT / "egov_log.json").read_text(encoding="utf-8"))
    lookups = {k: {"matches": v["matches"], "claimed_ok": v["claimed_ok"]} for k, v in egl["lookups"].items()}
    rev = json.loads((OUT / "rev.json").read_text(encoding="utf-8"))
    sv = {v["law_revision_id"]: v for v in rev["sochi"]["versions"]}
    t25 = {k: (nz(v["main"]["25_2"]["full"]) if "25_2" in v.get("main", {}) else None) for k, v in sv.items()}
    sochi_rev = {
        "versions_2027_01_01": sorted(k for k in sv if "_20270101_" in k),
        "updated": {k: v["revision_info"]["updated"] for k, v in sv.items()},
        "R6_8_eq_20261204": t25.get("332AC0000000026_20270101_506AC0000000008") == t25.get("332AC0000000026_20261204_508AC0000000012"),
        "R7_13_has_4_1_ro": "次に掲げる場合のいずれかに該当する場合に限る" in (t25.get("332AC0000000026_20270101_507AC0000000013") or "")
                            and "ロ次に掲げる要件の全てを満たす場合" in (t25.get("332AC0000000026_20270101_507AC0000000013") or ""),
        "R8_12_eq_asof_2027": t25.get("332AC0000000026_20270101_508AC0000000012") == nz(loc_text("sochi", R9, ("25_2",))),
        "R8_12_has_senman": "千万円を超えること" in (t25.get("332AC0000000026_20270101_508AC0000000012") or ""),
    }
    rei = {v["revision_info"]["law_revision_id"]: {
        "施行日": v["revision_info"]["amendment_enforcement_date"], "改正": v["revision_info"]["amendment_law_num"],
        "165②一_学生又は生徒で常時修学しない": "学校の学生又は生徒で常時修学しないもの" in nz(v["main"]["165"]["full"]),
        "198_又は": "譲渡所得の金額又は一時所得の金額" in nz(v["main"]["198"]["full"])} for v in rev["shotoku-rei"]["versions"]}
    summary = {
        "claims_total": len(claims), "claims_ok": sum(c["ok"] for c in claims),
        "revs_total": len(revs), "revs_ok": sum(r["ok_revision"] for r in revs),
        "revs_sha_same": sum(1 for r in revs if r["sha_same"]), "revs_sha_compared": sum(1 for r in revs if r["sha_same"] is not None),
        "article_diff_mismatch": len(diffs["mismatch_with_claim"]),
        "nta_meta_total": len(meta), "nta_lm_ok": sum(m["lm_ok"] for m in meta), "nta_sha_same": sum(m["sha_same"] for m in meta),
        "pdf_enc_ok": sum(1 for m in meta if m.get("enc_ok")), "pdf_enc_total": sum(1 for m in meta if "enc_ok" in m),
        "pdf_pages_ok": sum(1 for m in meta if m.get("pages_ok")), "pdf_key_ok": sum(1 for m in meta if m.get("key_ok")),
        "links_total": len(links), "links_ok": sum(l["ok"] for l in links),
        "pdf_formid_ok": pdfc["formid_ok"], "pdf_p1_all_ok": pdfc["p1_all_ok"],
        "examples_total": len(exs), "examples_ok": sum(v["ok"] for v in exs.values()),
        "lookups_ok": sum(v["claimed_ok"] for v in lookups.values()), "lookups_total": len(lookups),
    }
    res = {"summary": summary, "ng_claims": [c for c in claims if not c["ok"]], "claims": claims, "revs": revs,
           "article_diffs": diffs, "nta_meta": meta, "links": links, "pdf": pdfc, "examples": exs, "lookups": lookups,
           "sochi_25_2_by_revision": sochi_rev, "shotoku_rei_165_198_by_revision": rei, "shotoku_ki_appdx": run_appdx(),
           "ta_bunya_kojinjigyo_links_loss": [x for x in json.loads((OUT / "nta" / "ta_bunya_kojinjigyo.links.json").read_text(encoding="utf-8"))
                                              if re.search(r"純損失|繰戻|繰越|損失", x["text"])]
           if (OUT / "nta" / "ta_bunya_kojinjigyo.links.json").exists() else None}
    wjson(OUT / "check.json", res)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    for c in res["ng_claims"]:
        print("NG", c["id"], c["ref"], c["target"], c.get("missing"))
    for r in revs:
        if not r["ok_revision"] or r["sha_same"] is False:
            print("REV", r["target"], r["claimed"], r["got"])
    print("diff mismatch", diffs["mismatch_with_claim"])
    for m_ in meta:
        if not (m_["lm_ok"] and m_["sha_same"] and m_.get("enc_ok", True) and m_.get("pages_ok", True)):
            print("META", m_)
    for l_ in links:
        if not l_["ok"]:
            print("LINK", l_)
    for k, v in exs.items():
        if not v["ok"]:
            print("EX", k, v)
    print("sochi_rev", sochi_rev)
    print("pdf p2", pdfc["p2_quotes"], "p4", pdfc["p4_quotes"], pdfc["p4_columns"], pdfc["genkin"], pdfc["r5_label_pages"])
    print("p1 bad", {k: v for k, v in pdfc["p1"].items() if not (v["num_ok"] and v["label_ok"] in (True, None))})


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    OUT.mkdir(parents=True, exist_ok=True)
    if mode == "egov":
        mode_egov()
    elif mode == "rev":
        mode_rev()
    elif mode == "nta":
        mode_nta()
    elif mode == "pdf":
        mode_pdf(sys.argv[2:])
    elif mode == "egov2":
        mode_egov2()
    elif mode == "nta2":
        mode_nta2()
    elif mode == "check":
        mode_check()
    else:
        raise SystemExit("mode は egov・rev・nta・pdf・egov2・nta2・check のどれか")


if __name__ == "__main__":
    main()

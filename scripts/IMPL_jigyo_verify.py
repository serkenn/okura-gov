"""IMPL jigyo 独立検証（反証役）: 事業所得・業務に係る雑所得の文書に書かれた条文・数値・URL を、一次情報に自分で当たり直して確かめる。

実行（Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_jigyo_verify.py egov
      e-Gov 法令API v2 で law_id を引き直し（/laws?law_title=）、各時点（asof）の本文（/law_data）を取得して、
      対象の条・別表・改正法令の附則を構造（条→項→号）のまま JSON に取り出す。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_jigyo_verify.py nta
      先に https://www.nta.go.jp/robots.txt を取得して全 URL が許されるかを判定し（許されないものがあれば中止）、
      国税庁のページ（HTML はテキスト化、PDF は保存とハッシュだけ）を取得する。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_jigyo_verify.py nta2
      追加の国税庁ページ（通達の前文2件、申告書付表等の一覧 1557_2.htm、TA No.1810 の Q&A）を、robots.txt の判定のあとで取得する。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_jigyo_verify.py egov2
      国税通則法 第118条・第119条（asof 2025-12-31）。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_jigyo_verify.py egov3
      措法27 の asof 2020-12-31・2024-12-31 版、所得税法の /law_revisions と各版の第151条・令和5年法律第3号附則（担当の未確認点）。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_jigyo_verify.py check
      ネットワークを使わず、上の出力だけから、文書の主張（引用文・金額・項番号・施行日・適用年分）を突き合わせ、
      境目の計算・家内労働者等の特例の配分の総当たりを、担当のスクリプト（IMPL_jigyo_checks.py）とは別に書き直して再計算する。

- API の使い方は scripts/R1_egov_articles.py・scripts/R4_fetch_laws.py を読んで真似た（import はしない）。
  本文のテキスト化は自分で書き直した（担当の render は使わない）。
- ダウンロードしたものは信頼できないデータ。取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_IMPL_jigyo_verify_<mode>/ に置き、その中でインタプリタやツールは実行しない。
- 結果は scripts/results/IMPL_jigyo_verify/ に書く。
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。
"""
import hashlib
import html.parser
import itertools
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
OUT = ROOT / "scripts" / "results" / "IMPL_jigyo_verify"
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
TODAY = "2026-11-09"
WAIT = 1.5

AMEND_R7 = "令和七年三月三一日法律第一三号"
AMEND_R8 = "令和八年三月三一日法律第一二号"

# 略称: (法令名, 担当が書いた law_id, [asof...], [取り出す本則の条（Num 属性）], 別表を取り出すか)
LAWS = {
    "shotoku": ("所得税法", "340AC0000000033", ["2025-12-31", "2026-12-31", "2027-01-01", "2030-12-31"],
                ["2", "22", "27", "28", "34", "35", "36", "37", "45", "56", "57", "67", "69", "86", "120",
                 "143", "144", "145", "147", "148", "149", "150", "151", "232"], True),
    "shotoku-rei": ("所得税法施行令", "340CO0000000096", ["2025-12-31", "2026-12-31", "2030-12-31"],
                    ["96", "195", "196", "196_2", "196_3", "197"], False),
    "shotoku-ki": ("所得税法施行規則", "340M50000040011", ["2025-12-31", "2026-12-31", "2027-01-01", "2030-12-31"],
                   ["40", "47", "47_3", "63", "102"], False),
    "sochi": ("租税特別措置法", "332AC0000000026", ["2025-12-31", "2026-12-31", "2027-01-01", "2030-12-31"],
              ["25_2", "27", "29_4", "41_16_2"], False),
    "sochi-rei": ("租税特別措置法施行令", "332CO0000000043", ["2025-12-31", "2026-12-31", "2030-12-31"],
                  ["18_2"], False),
    "sochi-ki": ("租税特別措置法施行規則", "332M50000040015", ["2025-12-31", "2026-12-31", "2030-12-31"],
                 ["9_6"], False),
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
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL_jigyo_verify_{mode}"
    dl.mkdir(parents=True, exist_ok=False)
    return ts, dl


def rel(p):
    return str(pathlib.Path(p).relative_to(ROOT)).replace("\\", "/")


# ---------------------------------------------------------------- e-Gov
def flat(n):
    """ノード以下の文字列をつなぐ（ルビの読み Rt は落とす）。"""
    if isinstance(n, str):
        return n
    if n.get("tag") == "Rt":
        return ""
    return "".join(flat(c) for c in n.get("children", []))


def kids(n, tag=None):
    return [c for c in n.get("children", []) if isinstance(c, dict) and (tag is None or c.get("tag") == tag)]


def node_struct(n):
    """Paragraph / Item / SubitemN を {num, head, text(自分の文だけ), full(配下すべて), children:{num: ...}} に。"""
    tag = n.get("tag")
    head = "".join(flat(c) for c in kids(n) if c.get("tag", "").endswith(("Num", "Title")) and c.get("tag") != "ParagraphCaption")
    own = "".join(flat(c) for c in kids(n) if c.get("tag", "").endswith("Sentence"))
    ch = {}
    for c in kids(n):
        t = c.get("tag", "")
        if t == "Item" or t.startswith("Subitem"):
            if not t.endswith(("Title", "Sentence")):
                ch[c.get("attr", {}).get("Num", str(len(ch) + 1))] = node_struct(c)
    return {"tag": tag, "num": n.get("attr", {}).get("Num"), "head": head, "text": own, "full": flat(n), "children": ch}


def article_struct(a):
    cap = "".join(flat(c) for c in kids(a, "ArticleCaption"))
    title = "".join(flat(c) for c in kids(a, "ArticleTitle"))
    paras = {}
    for p in kids(a, "Paragraph"):
        paras[p.get("attr", {}).get("Num")] = node_struct(p)
    return {"num": a.get("attr", {}).get("Num"), "caption": cap, "title": title, "full": flat(a), "paras": paras}


def walk(n, fn, path=()):
    if isinstance(n, dict):
        fn(n, path)
        for c in n.get("children", []):
            walk(c, fn, path + (n.get("tag"),))


def table_rows(n):
    rows = []

    def f(x, p):
        if x.get("tag") == "TableRow":
            rows.append([flat(c).strip() for c in kids(x)])
    walk(n, f)
    return rows


def mode_egov():
    ts, dl = new_dl("egov")
    OUT.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": rel(dl), "lookups": {}, "fetches": []}
    for i, (short, (title, law_id_claimed, asofs, nums, appdx)) in enumerate(LAWS.items(), 1):
        q = urllib.parse.urlencode({"law_title": title, "response_format": "json", "asof": TODAY})
        url = f"{API}/laws?{q}"
        st, body, _ = http_get(url, "application/json")
        (dl / f"{i:02d}_laws_{short}.json").write_bytes(body)
        found = []
        for law in json.loads(body).get("laws", []):
            rv = law.get("current_revision_info") or law.get("revision_info") or {}
            if rv.get("law_title") == title:
                found.append({"law_id": law["law_info"]["law_id"], "law_num": law["law_info"].get("law_num")})
        log["lookups"][short] = {"title": title, "url": url, "status": st, "exact_title_matches": found,
                                 "claimed_law_id": law_id_claimed,
                                 "claimed_matches": any(x["law_id"] == law_id_claimed for x in found)}
        print("lookup", short, found, flush=True)
        law_id = law_id_claimed
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
            ri = d.get("revision_info") or {}
            root = d["law_full_text"]
            main, suppl, appdx_tables, captions = {}, {}, [], []

            def coll(n, path):
                if n.get("tag") == "Article" and "SupplProvision" not in path:
                    captions.append([n.get("attr", {}).get("Num"), "".join(flat(c) for c in kids(n, "ArticleCaption"))])
                    if n.get("attr", {}).get("Num") in nums:
                        main[n["attr"]["Num"]] = article_struct(n)
                if n.get("tag") == "SupplProvision":
                    an = n.get("attr", {}).get("AmendLawNum")
                    if an in (AMEND_R7, AMEND_R8):
                        arts = {}
                        walk(n, lambda x, p: arts.__setitem__(x["attr"].get("Num"), article_struct(x)) if x.get("tag") == "Article" else None)
                        suppl.setdefault(an, []).append(arts)
                if n.get("tag") == "AppdxTable" and appdx:
                    t = "".join(flat(c) for c in kids(n, "AppdxTableTitle"))
                    appdx_tables.append({"title": t, "rows": table_rows(n)})
            walk(root, coll)
            rec = {"short": short, "title": title, "law_id": law_id, "asof": asof, "url": furl, "fetched_at": ts,
                   "raw": rel(raw), "sha256": hashlib.sha256(body).hexdigest(),
                   "revision_info": {k: ri.get(k) for k in ("law_revision_id", "amendment_law_num", "amendment_law_title",
                                                            "amendment_enforcement_date", "current_revision_status", "updated")},
                   "missing": [x for x in nums if x not in main]}
            (OUT / f"egov_{short}_{asof}.json").write_text(json.dumps(
                {**rec, "captions": captions, "main": main, "suppl": suppl, "appdx": appdx_tables}, ensure_ascii=False, indent=0),
                encoding="utf-8")
            log["fetches"].append(rec)
            print("ok", short, asof, ri.get("law_revision_id"), ri.get("current_revision_status"), rec["missing"], flush=True)
    (OUT / "egov_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- 国税庁
NTA = "https://www.nta.go.jp"
TA = NTA + "/taxes/shiraberu/taxanswer/shotoku/"
KIHON = NTA + "/law/tsutatsu/kihon/shotoku/"
PAGES = {
    "ta_1810": TA + "1810.htm", "ta_1490": TA + "1490.htm", "ta_1500": TA + "1500.htm", "ta_2070": TA + "2070.htm",
    "ta_2072": TA + "2072.htm", "ta_2080": TA + "2080.htm", "ta_2210": TA + "2210.htm",
    "kihon_toc": KIHON + "01.htm",
    "kihon_04_08": KIHON + "04/08.htm", "kihon_04_09": KIHON + "04/09.htm", "kihon_07_01": KIHON + "07/01.htm",
    "kihon_14_02": KIHON + "14/02.htm", "kihon_19_01": KIHON + "19/01.htm", "kihon_40_02": KIHON + "40/02.htm",
    "sochitsu_toc": NTA + "/law/tsutatsu/kobetsu/shotoku/sochiho/801226/sinkoku/01.htm",
    "sochitsu_25_2": NTA + "/law/tsutatsu/kobetsu/shotoku/sochiho/801226/sinkoku/57/25/01.htm",
    "shitsugi_02_04": NTA + "/law/shitsugi/shotoku/02/04.htm",
    "shitsugi_04_34": NTA + "/law/shitsugi/shotoku/04/34.htm",
    "yoshiki_index": NTA + "/taxes/shiraberu/shinkoku/syotoku/index.htm",
    "yoshiki_r07": NTA + "/taxes/shiraberu/shinkoku/syotoku/r07.htm",
    "pdf_shushi_ippan_r07": NTA + "/taxes/shiraberu/shinkoku/yoshiki/01/shinkokusho/pdf/r07/05.pdf",
    "pdf_shushi_kakikata_r07": NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/pdf/034.pdf",
    "pdf_kanai_keisansho": NTA + "/taxes/shiraberu/shinkoku/yoshiki/03/09.pdf",
    "pdf_kanai_kakikata": NTA + "/taxes/shiraberu/shinkoku/yoshiki/03/09-ki.pdf",
    "pdf_kessan_tebiki_shiro": NTA + "/taxes/shiraberu/shinkoku/kojin_jigyo/kichou09.pdf",
    "pdf_kicho_shikata": NTA + "/taxes/shiraberu/shinkoku/kojin_jigyo/kichou03.pdf",
    "pdf_ta1810_input": TA + "pdf/1810.pdf",
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
    out = OUT / "nta"
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
            (out / f"{key}.txt").write_text(p.text() + "\n", encoding="utf-8")
            (out / f"{key}.links.json").write_text(json.dumps(p.links, ensure_ascii=False, indent=0), encoding="utf-8")
        log["items"].append(it)
        print("ok", key, st, len(body), hd.get("Last-Modified"), flush=True)
    (OUT / f"{name}_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- 追加の取得（前文・国税通則法）
PAGES2 = {
    "kihon_zenbun": KIHON + "00/01.htm",
    "sochitsu_zenbun": NTA + "/law/tsutatsu/kobetsu/shotoku/sochiho/801226/sinkoku/57/zenbun/01.htm",
    "fuhyo_1557_2": NTA + "/taxes/tetsuzuki/shinsei/annai/shinkoku/annai/1557_2.htm",  # 計算書の【令和７年分以降用】の表示
    "ta_1810_qa": TA + "1810_qa.htm",  # TA1810 の QA（家内労働者等の所得とそれ以外の所得がある場合）
}


def mode_egov2():
    """国税通則法（推測 I8 が触れる第118条）を law_title で引き、asof=2025-12-31 の第118条・第119条を取り出す。"""
    ts, dl = new_dl("egov2")
    title = "国税通則法"
    q = urllib.parse.urlencode({"law_title": title, "response_format": "json", "asof": TODAY})
    st, body, _ = http_get(f"{API}/laws?{q}", "application/json")
    (dl / "01_laws_tsusoku.json").write_bytes(body)
    found = []
    for lw in json.loads(body).get("laws", []):
        rv = lw.get("current_revision_info") or lw.get("revision_info") or {}
        if rv.get("law_title") == title:
            found.append({"law_id": lw["law_info"]["law_id"], "law_num": lw["law_info"].get("law_num")})
    law_id = found[0]["law_id"]
    asof = "2025-12-31"
    furl = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
    st, body, _ = http_get(furl, "application/json")
    raw = dl / f"tsusoku_{asof}.json"
    raw.write_bytes(body)
    d = json.loads(body)
    ri = d.get("revision_info") or {}
    main = {}

    def coll(n, path):
        if n.get("tag") == "Article" and "SupplProvision" not in path and n.get("attr", {}).get("Num") in ("118", "119"):
            main[n["attr"]["Num"]] = article_struct(n)
    walk(d["law_full_text"], coll)
    rec = {"short": "tsusoku", "title": title, "lookup": found, "law_id": law_id, "asof": asof, "url": furl, "fetched_at": ts,
           "raw": rel(raw), "sha256": hashlib.sha256(body).hexdigest(),
           "revision_info": {k: ri.get(k) for k in ("law_revision_id", "amendment_law_num", "amendment_enforcement_date",
                                                    "current_revision_status")}}
    (OUT / f"egov_tsusoku_{asof}.json").write_text(json.dumps({**rec, "main": main, "suppl": {}, "appdx": [], "captions": [],
                                                               "missing": []}, ensure_ascii=False, indent=0), encoding="utf-8")
    print("ok tsusoku", law_id, ri.get("law_revision_id"), list(main))


def mode_egov3():
    """担当が「分からなかった」とした2点を一次情報で確かめる。
    (a) 措法27 の令和2年分〜令和6年分の額：asof=2020-12-31・2024-12-31 の版の第27条。
    (b) 所法151 の文言（取りやめ届出の期限）がどの改正で変わったか：/law_revisions で 2026-01-01〜2026-11-09 に施行の版を列挙し、
        各版（/law_data/<law_revision_id>）の第151条を取り出す。"""
    ts, dl = new_dl("egov3")
    out = {"fetched_at": ts, "download_dir": rel(dl), "sochi27_past": {}, "shotoku_revisions": [], "shotoku151_by_revision": {}}
    for asof in ("2020-12-31", "2024-12-31"):
        furl = f"{API}/law_data/332AC0000000026?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
        st, body, _ = http_get(furl, "application/json")
        (dl / f"sochi_{asof}.json").write_bytes(body)
        d = json.loads(body)
        ri = d.get("revision_info") or {}
        found = {}
        walk(d["law_full_text"], lambda n, p: found.__setitem__("27", article_struct(n))
             if n.get("tag") == "Article" and "SupplProvision" not in p and n.get("attr", {}).get("Num") == "27" else None)
        out["sochi27_past"][asof] = {"url": furl, "law_revision_id": ri.get("law_revision_id"),
                                     "status": ri.get("current_revision_status"), "text": found.get("27", {}).get("full")}
        print("ok sochi", asof, ri.get("law_revision_id"), flush=True)
    st, body, _ = http_get(f"{API}/law_revisions/340AC0000000033?response_format=json", "application/json")
    (dl / "shotoku_revisions.json").write_bytes(body)
    revs = json.loads(body).get("revisions", [])
    for r in revs:
        out["shotoku_revisions"].append({k: r.get(k) for k in ("law_revision_id", "amendment_enforcement_date", "amendment_law_num",
                                                               "amendment_law_title", "current_revision_status")})
    pick = [r for r in out["shotoku_revisions"] if r["amendment_enforcement_date"] and "2025-12-18" <= r["amendment_enforcement_date"] <= TODAY]
    for r in pick:
        rid = r["law_revision_id"]
        st, body, _ = http_get(f"{API}/law_data/{rid}?response_format=json", "application/json")
        (dl / f"shotoku_{rid}.json").write_bytes(body)
        if st != 200:
            out["shotoku151_by_revision"][rid] = {"status": st}
            continue
        d = json.loads(body)
        found = {}
        walk(d["law_full_text"], lambda n, p: found.__setitem__("151", article_struct(n))
             if n.get("tag") == "Article" and "SupplProvision" not in p and n.get("attr", {}).get("Num") == "151" else None)
        t = found.get("151", {}).get("full", "")
        r5 = {}

        def coll_r5(n, p):
            if n.get("tag") == "SupplProvision" and n.get("attr", {}).get("AmendLawNum") == "令和五年三月三一日法律第三号":
                walk(n, lambda x, q: r5.__setitem__(x["attr"].get("Num"), article_struct(x))
                     if x.get("tag") == "Article" and x.get("attr", {}).get("Num") in ("1", "5") else None)
        walk(d["law_full_text"], coll_r5)
        r5_1_6 = r5.get("1", {}).get("paras", {}).get("1", {}).get("children", {}).get("6", {}).get("full")
        out["shotoku151_by_revision"][rid] = {**r, "old_text": "その年の翌年三月十五日までに" in t,
                                              "new_text": "その年分の所得税に係る確定申告期限までに" in t,
                                              "R5law3_suppl_1_1_6": r5_1_6, "R5law3_suppl_5": r5.get("5", {}).get("full")}
        print("ok shotoku rev", rid, out["shotoku151_by_revision"][rid]["new_text"], flush=True)
    (OUT / "egov3.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- 突合せ（ネットワークなし）
_TR = str.maketrans("０１２３４５６７８９（）％－−―‐，『』［］", "0123456789()%----,「」[]")


def norm(s):
    return re.sub(r"[\s　]", "", s or "").translate(_TR)


def contains_seq(text, quote):
    """quote を「…」で分け、各断片が text に順に現れるか。"""
    t, pos = norm(text), 0
    for frag in re.split(r"…+", quote):
        f = norm(frag)
        if not f:
            continue
        i = t.find(f, pos)
        if i < 0:
            return False, frag
        pos = i + len(f)
    return True, None


_D = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def k2i(s):
    total = section = cur = 0
    for ch in s:
        if ch in _D:
            cur = _D[ch]
        elif ch in "十百千":
            section += (cur or 1) * {"十": 10, "百": 100, "千": 1000}[ch]
            cur = 0
        elif ch in "万億":
            total += (section + cur) * {"万": 10 ** 4, "億": 10 ** 8}[ch]
            section = cur = 0
    return total + section + cur


def yen(text):
    return [k2i(m) for m in re.findall(r"([〇一二三四五六七八九十百千万億]+)円", text or "")]


_LAWCACHE = {}


def law(short, asof):
    k = (short, asof)
    if k not in _LAWCACHE:
        _LAWCACHE[k] = json.loads((OUT / f"egov_{short}_{asof}.json").read_text(encoding="utf-8"))
    return _LAWCACHE[k]


def _sub(a, rest):
    if not rest:
        return a, a["full"]
    node = a["paras"].get(rest[0])
    for r in rest[1:]:
        if node is None:
            return None, None
        node = node["children"].get(r)
    return (node, node["full"]) if node else (None, None)


def loc(short, asof, where):
    """where: '45' / '45:1' / '18_2:2:2' / 'S:R7:32' / 'S:R8:1:1:4'（附則）。(node, text) を返す。"""
    d = law(short, asof)
    p = where.split(":")
    if p[0] == "S":
        an = {"R7": AMEND_R7, "R8": AMEND_R8}[p[1]]
        for arts in d["suppl"].get(an, []):
            if p[2] in arts:
                return _sub(arts[p[2]], p[3:])
        return None, None
    a = d["main"].get(p[0])
    return _sub(a, p[1:]) if a else (None, None)


Y7, Y8, Y9, Y30 = "2025-12-31", "2026-12-31", "2027-01-01", "2030-12-31"
SO4 = ["Y7", "Y8", "Y9", "Y30"]

# 担当の文書の主張（PS=公開資料の情報、M=実測、H=仮説、I=推測。§は各文書の節）。
# law の kind：Q=引用（「…」で分けた断片が順に現れる）、NQ=現れない、A=「…円」の金額の集合、A1=最初の金額、
#   CAP=条の見出し、ABS=その項がない、NOCHILD=号にイ・ロなどの細分がない
CLAIMS = {
    "law": [
        # ---- §1 家事関連費
        ["PS§1.1 所法35②二", "shotoku", ["Y7", "Y8"], "35:2:2", "Q", ["その年中の雑所得（公的年金等に係るものを除く。）に係る総収入金額から必要経費を控除した金額"]],
        ["PS§1.1 所法37①", "shotoku", ["Y7", "Y8"], "37:1", "Q", ["その年分の不動産所得の金額、事業所得の金額又は雑所得の金額（事業所得の金額及び雑所得の金額のうち山林の伐採又は譲渡に係るもの並びに雑所得の金額のうち第三十五条第三項（公的年金等の定義）に規定する公的年金等に係るものを除く。）の計算上必要経費に算入すべき金額は、別段の定めがあるものを除き、これらの所得の総収入金額に係る売上原価その他当該総収入金額を得るため直接に要した費用の額及びその年における販売費、一般管理費その他これらの所得を生ずべき業務について生じた費用（償却費以外の費用でその年において債務の確定しないものを除く。）の額とする。"]],
        ["PS§1.1 所法45 見出し", "shotoku", ["Y7", "Y8"], "45", "CAP", "家事関連費等の必要経費不算入等"],
        ["PS§1.1 所法45①", "shotoku", ["Y7", "Y8"], "45:1", "Q", ["居住者が支出し又は納付する次に掲げるものの額は、その者の不動産所得の金額、事業所得の金額、山林所得の金額又は雑所得の金額の計算上、必要経費に算入しない。", "一家事上の経費及びこれに関連する経費で政令で定めるもの"]],
        ["PS§1.1 所令96 見出し", "shotoku-rei", ["Y7", "Y8", "Y30"], "96", "CAP", "家事関連費"],
        ["PS§1.1 所令96", "shotoku-rei", ["Y7", "Y8", "Y30"], "96", "Q", ["法第四十五条第一項第一号（必要経費とされない家事関連費）に規定する政令で定める経費は、次に掲げる経費以外の経費とする。", "一家事上の経費に関連する経費の主たる部分が不動産所得、事業所得、山林所得又は雑所得を生ずべき業務の遂行上必要であり、かつ、その必要である部分を明らかに区分することができる場合における当該部分に相当する経費", "二前号に掲げるもののほか、青色申告書を提出することにつき税務署長の承認を受けている居住者に係る家事上の経費に関連する経費のうち、取引の記録等に基づいて、不動産所得、事業所得又は山林所得を生ずべき業務の遂行上直接必要であつたことが明らかにされる部分の金額に相当する経費"]],
        ["PS§1.2/M C4 所令96二に雑所得なし", "shotoku-rei", ["Y7", "Y8", "Y30"], "96:1:2", "NQ", ["雑所得"]],
        ["PS§1.3 所法56", "shotoku", ["Y7", "Y8"], "56", "Q", ["居住者と生計を一にする配偶者その他の親族がその居住者の営む不動産所得、事業所得又は山林所得を生ずべき事業に従事したことその他の事由により当該事業から対価の支払を受ける場合には、その対価に相当する金額は、その居住者の当該事業に係る不動産所得の金額、事業所得の金額又は山林所得の金額の計算上、必要経費に算入しない"]],
        # ---- §2 家内労働者等
        ["PS§2.1 措法27（令和7年分の版）", "sochi", ["Y7"], "27", "Q", ["家内労働法（昭和四十五年法律第六十号）第二条第二項に規定する家内労働者に該当する個人、外交員その他これらに類する者として政令で定める個人が事業所得又は雑所得を有する場合において、その年分の事業所得の金額の計算上必要経費に算入すべき金額及び雑所得の金額の計算上必要経費に算入すべき金額の合計額が六十五万円（当該個人が給与所得を有する場合にあつては、六十五万円から所得税法第二十八条第二項に規定する給与所得控除額を控除した残額。以下この条において同じ。）に満たないときは、その年分の事業所得の金額の計算上必要経費に算入する金額又は雑所得の金額の計算上必要経費に算入する金額は、所得税法第三十七条第一項及び第二編第二章第二節第四款第一目から第五目までの規定にかかわらず、六十五万円を政令で定めるところにより事業所得に係る金額と雑所得に係る金額とに区分をした場合の当該区分をしたそれぞれの金額とする。この場合において、当該それぞれの金額は、その年分の事業所得に係る総収入金額又は雑所得に係る総収入金額（同法第三十五条第三項に規定する公的年金等に係るものを除く。）を限度とする。"]],
        ["PS§2.1 措法27（令和8年分の版以後、金額だけ69万円）", "sochi", ["Y8", "Y9", "Y30"], "27", "Q", ["合計額が六十九万円（当該個人が給与所得を有する場合にあつては、六十九万円から所得税法第二十八条第二項に規定する給与所得控除額を控除した残額。以下この条において同じ。）に満たないときは", "六十九万円を政令で定めるところにより事業所得に係る金額と雑所得に係る金額とに区分をした場合の当該区分をしたそれぞれの金額とする。この場合において、当該それぞれの金額は、その年分の事業所得に係る総収入金額又は雑所得に係る総収入金額（同法第三十五条第三項に規定する公的年金等に係るものを除く。）を限度とする。"]],
        ["PS§2.1 措法27 見出し", "sochi", SO4, "27", "CAP", "家内労働者等の事業所得等の所得計算の特例"],
        ["PS§2.1/M C1 措法27 金額（令和7年分の版）", "sochi", ["Y7"], "27", "A", [650000]],
        ["PS§2.1/M C1 措法27 金額（令和8年分の版以後）", "sochi", ["Y8", "Y9", "Y30"], "27", "A", [690000]],
        ["PS§2.1 措令18の2①", "sochi-rei", ["Y7", "Y8", "Y30"], "18_2:1", "Q", ["法第二十七条に規定する政令で定める個人は、集金人、電力量計の検針人その他特定の者に対して継続的に人的役務の提供を行うことを業務とする者とする。"]],
        ["PS§2.1 措令18の2②一", "sochi-rei", ["Y7"], "18_2:2:1", "Q", ["事業所得又は雑所得のいずれかを有する家内労働者等", "六十五万円（当該家内労働者等が給与所得を有する場合にあつては、六十五万円から所得税法第二十八条第二項に規定する給与所得控除額を控除した残額。次号において同じ。）"]],
        ["PS§2.1 措令18の2②二", "sochi-rei", ["Y7"], "18_2:2:2", "Q", ["事業所得及び雑所得を有する家内労働者等", "イ六十五万円のうち、所得税法第三十七条第一項及び…の規定による事業所得の必要経費に相当する金額（雑所得に係る総収入金額（…公的年金等に係るものを除く。）がロに掲げる金額に満たない場合には、当該満たない部分に相当する金額を加算した金額）に達するまでの部分に相当する金額", "ロ六十五万円のうち、…事業所得の必要経費に相当する金額に達するまでの部分以外の部分に相当する金額"]],
        ["PS§2.1 措令18の2② イ=事業・ロ=雑", "sochi-rei", ["Y7", "Y8"], "18_2:2", "Q", ["同号イに掲げる金額を事業所得に係る必要経費に算入する金額とし、かつ、同号ロに掲げる金額を雑所得に係る必要経費に算入する金額とする"]],
        ["PS§2.1/M C1 措令18の2 金額（令和7年分の版）", "sochi-rei", ["Y7"], "18_2", "A", [650000]],
        ["PS§2.1/M C1 措令18の2 金額（令和8年分の版以後）", "sochi-rei", ["Y8", "Y30"], "18_2", "A", [690000]],
        ["PS§2.1 R7法13附則1①一ロ（施行日）", "sochi", ["Y9"], "S:R7:1:1:1", "Q", ["令和七年十二月一日", "ロ第八条中租税特別措置法第二十七条の改正規定"]],
        ["PS§2.1 R7法13附則32①（適用）", "sochi", ["Y7", "Y9"], "S:R7:32:1", "Q", ["新租税特別措置法第二十七条の規定は、令和七年分以後の所得税について適用し、令和六年分以前の所得税については、なお従前の例による。"]],
        ["PS§2.1 R7法13附則32②（更正の請求）", "sochi", ["Y9"], "S:R7:32:2", "Q", ["令和七年十二月一日前に", "同日から五年以内に", "更正の請求"]],
        ["PS§2.1 R8法12附則1①四ロ（施行日）", "sochi", ["Y9"], "S:R8:1:1:4", "Q", ["令和八年十二月一日", "ロ第七条中", "同法第二十七条の改正規定"]],
        ["PS§2.1 R8法12附則34①（適用）", "sochi", ["Y8", "Y9"], "S:R8:34:1", "Q", ["新租税特別措置法第二十七条の規定は、令和八年分以後の所得税について適用し、令和七年分以前の所得税については、なお従前の例による。"]],
        ["PS§2.1 R8法12附則34②（更正の請求）", "sochi", ["Y9"], "S:R8:34:2", "Q", ["令和八年十二月一日前に", "同日から五年以内に", "更正の請求"]],
        # ---- §3 青色
        ["PS§3.1 所法143", "shotoku", ["Y7", "Y8"], "143", "Q", ["不動産所得、事業所得又は山林所得を生ずべき業務を行なう居住者は、納税地の所轄税務署長の承認を受けた場合には、確定申告書及び当該申告書に係る修正申告書を青色の申告書により提出することができる。"]],
        ["PS§3.1 所法143に雑所得なし", "shotoku", ["Y7", "Y8"], "143", "NQ", ["雑所得"]],
        ["PS§3.1 所法144", "shotoku", ["Y7", "Y8"], "144", "Q", ["三月十五日まで（その年一月十六日以後新たに同条に規定する業務を開始した場合には、その業務を開始した日から二月以内）"]],
        ["PS§3.1 所法145", "shotoku", ["Y7", "Y8"], "145", "Q", ["第百四十八条第一項", "不実の記載又は記録", "一年以内"]],
        ["PS§3.1 所法147", "shotoku", ["Y7", "Y8"], "147", "Q", ["十二月三十一日（その年十一月一日以後新たに同条に規定する業務を開始した場合には、その年の翌年二月十五日）まで"]],
        ["PS§3.1 所法148", "shotoku", ["Y7", "Y8"], "148:1", "Q", ["財務省令で定めるところにより", "帳簿書類を備え付けて", "記録し、かつ、当該帳簿書類を保存しなければならない"]],
        ["PS§3.1 所法149", "shotoku", ["Y7", "Y8"], "149", "Q", ["貸借対照表、損益計算書その他"]],
        ["PS§3.1 所法150", "shotoku", ["Y7", "Y8"], "150", "Q", ["承認を取り消すことができる", "行なわれていないこと", "指示に従わなかつたこと", "隠ぺいし又は仮装"]],
        ["PS§3.1/M§3 所法151（令和7年分の版）", "shotoku", ["Y7"], "151:1", "Q", ["その年の翌年三月十五日までに"]],
        ["PS§3.1/M§3 所法151（令和8年分の版以後）", "shotoku", ["Y8", "Y9", "Y30"], "151:1", "Q", ["その年分の所得税に係る確定申告期限までに"]],
        ["PS§3.1 所法57①", "shotoku", ["Y7", "Y8"], "57:1", "Q", ["青色申告書を提出することにつき税務署長の承認を受けている居住者", "年齢十五歳未満である者を除く"]],
        ["PS§3.1 所法57③ 金額", "shotoku", ["Y7", "Y8"], "57:3", "A", [860000, 500000]],
        ["PS§3.1 所法57③ 式", "shotoku", ["Y7", "Y8"], "57:3", "Q", ["いずれか低い金額", "事業専従者の数に一を加えた数で除して計算した金額"]],
        ["PS§3.2 措法25の2①一（10万円）", "sochi", ["Y7", "Y8"], "25_2:1:1", "A", [100000]],
        ["PS§3.2 措法25の2③（55万円）", "sochi", ["Y7", "Y8"], "25_2:3", "Q", ["所得税法第六十七条第一項の規定の適用を受ける者を除く。", "同法第百四十八条第一項の規定により", "一切の取引の内容を詳細に記録している場合として財務省令で定める場合に限る", "五十五万円"]],
        ["PS§3.2 措法25の2④（65万円）", "sochi", ["Y7", "Y8"], "25_2:4", "Q", ["「六十五万円」", "同法第八条第四項に規定する財務省令で定める要件", "確定申告書の提出期限までに", "電子情報処理組織を使用して"]],
        ["PS§3.2 措法25の2⑥", "sochi", ["Y7", "Y8"], "25_2:6", "Q", ["第三項（第四項の規定により、同項第二号に掲げる要件を満たしている者について適用する場合を除く。）", "当該確定申告書をその提出期限までに提出した場合に限り、適用する"]],
        ["PS§3.2/M C8 措法25の2 金額（令和7・8年分の版）", "sochi", ["Y7", "Y8"], "25_2", "A", [100000, 550000, 650000]],
        ["PS§3.2 措法25の2②（千万円）", "sochi", ["Y9", "Y30"], "25_2:2", "Q", ["前々年分の不動産所得に係る総収入金額が千万円を超えること", "前々年分の事業所得に係る総収入金額が千万円を超えること"]],
        ["PS§3.2 措法25の2②柱書", "sochi", ["Y9", "Y30"], "25_2:2", "Q", ["第四項に規定する場合に該当しない場合には、適用しない"]],
        ["PS§3.2 措法25の2④一（65万円）", "sochi", ["Y9", "Y30"], "25_2:4:1", "A", [650000]],
        ["PS§3.2 措法25の2⑤（75万円）", "sochi", ["Y9", "Y30"], "25_2:5", "Q", ["電磁的記録", "の備付け及び保存", "「七十五万円」"]],
        ["PS§3.2 措法25の2⑤二イ・ロ（電子取引）", "sochi", ["Y9", "Y30"], "25_2:5:2", "Q", ["次に掲げる要件の全てを満たす場合", "電子取引", "特定電磁的記録"]],
        ["PS§3.2 措法25の2⑦（e-Tax）", "sochi", ["Y9", "Y30"], "25_2:7", "Q", ["電子情報処理組織を使用して", "送信した場合に限り、適用する"]],
        ["PS§3.2/M C8 措法25の2 金額（令和9年分以後）", "sochi", ["Y9", "Y30"], "25_2", "A", [100000, 650000, 750000, 10000000]],
        ["PS§3.2 措規9の6①", "sochi-ki", ["Y7", "Y8"], "9_6:1", "Q", ["所得税法施行規則第五十七条から第六十二条まで及び第六十四条の規定に定めるところにより記録し"]],
        ["PS§3.2 措規9の6②", "sochi-ki", ["Y7", "Y8"], "9_6:2", "Q", ["仕訳帳及び総勘定元帳"]],
        ["PS§3.2 R8法12附則1①五ロ", "sochi", ["Y9"], "S:R8:1:1:5", "Q", ["令和九年一月一日", "同法第二十五条の二の改正規定"]],
        ["PS§3.2 R8法12附則33", "sochi", ["Y9"], "S:R8:33", "Q", ["新租税特別措置法第二十五条の二の規定は、令和九年分以後の所得税について適用し、令和八年分以前の所得税については、なお従前の例による。"]],
        ["PS§3.2 R7法13附則1①五ハ", "sochi", ["Y9"], "S:R7:1:1:5", "Q", ["令和九年一月一日", "ハ第八条中租税特別措置法第二十五条の二第四項第一号の改正規定", "附則第三十一条"]],
        ["PS§3.2 R7法13附則31", "sochi", ["Y9"], "S:R7:31", "Q", ["新租税特別措置法第二十五条の二（第四項第一号ロに係る部分に限る。）の規定は、令和九年分以後の所得税について適用する。"]],
        ["PS§3.2 2027-01-01版の措法25の2④一にロがない", "sochi", ["Y9"], "25_2:4:1", "NOCHILD", None],
        # ---- §4 帰属時期
        ["PS§4.1 所法67②", "shotoku", SO4, "67:2", "Q", ["雑所得を生ずべき業務を行う居住者のうち小規模な業務を行う者として政令で定める要件に該当するもののその年分の当該雑所得を生ずべき業務に係る雑所得の金額（山林の伐採又は譲渡に係るものを除く。）の計算上総収入金額及び必要経費に算入すべき金額は、政令で定めるところにより、その業務につきその年において収入した金額及び支出した費用の額とすることができる。"]],
        ["PS§4.1/M C6 所法67②に青色の要件なし", "shotoku", SO4, "67:2", "NQ", ["青色"]],
        ["PS§4.1 所令196の2", "shotoku-rei", ["Y7", "Y8", "Y30"], "196_2", "Q", ["法第六十七条第二項", "に規定する政令で定める要件は、その年の前々年分の雑所得を生ずべき業務に係る収入金額が三百万円以下であることとする。"]],
        ["PS§4.1/M C4 所令196の2 金額", "shotoku-rei", ["Y7", "Y8", "Y30"], "196_2", "A", [3000000]],
        ["PS§4.1 所令196の3①", "shotoku-rei", ["Y7", "Y8"], "196_3:1", "Q", ["雑所得を生ずべき業務の全部を譲渡し、若しくは廃止し、又は死亡した日の属する年分を除く", "その者の選択により、その業務につきその年において収入した金額"]],
        ["PS§4.1 所令196の3②", "shotoku-rei", ["Y7", "Y8"], "196_3:2", "Q", ["償却費及び法第五十一条第四項", "その年において当該業務に係る雑所得の総収入金額を得るために直接支出した費用の額及びその年において当該業務について支出した費用の額"]],
        ["PS§4.1 所令197③", "shotoku-rei", ["Y7", "Y8"], "197:3", "Q", ["前条第一項の選択をする居住者は、同項の規定の適用を受けようとする年分の確定申告書を提出する場合には、当該申告書にその適用を受ける旨の記載をしなければならない。"]],
        ["PS§4.1・§4.2 所令197①（196条1項の手続・期限）", "shotoku-rei", ["Y7", "Y8"], "197:1", "Q", ["第百九十六条第一項", "その年三月十五日まで（その年一月十六日以後新たに同項に規定する業務を開始した場合には、その業務を開始した日から二月以内）"]],
        ["PS§4.1 所規40②", "shotoku-ki", ["Y7", "Y8"], "40:2", "Q", ["前年において法第六十七条第二項の規定の適用を受けていた", "その適用を受けることとなつた年の前年十二月三十一日（年の中途において新たに雑所得を生ずべき業務を開始した場合には、当該業務を開始した日）", "売掛金、買掛金、未収収益、前受収益、前払費用、未払費用その他これらに類する資産及び負債", "一月一日における売掛金等の額との差額"]],
        ["PS§4.1 所規40③", "shotoku-ki", ["Y7", "Y8"], "40:3", "Q", ["前年以前五年内の各年のいずれの年においても", "前項の規定を適用しないことができる"]],
        ["PS§4.1 所規40④", "shotoku-ki", ["Y7", "Y8"], "40:4", "Q", ["確定申告書", "記載をしなければならない"]],
        ["PS§4.2/M C6 所法67①", "shotoku", SO4, "67:1", "Q", ["青色申告書を提出することにつき税務署長の承認を受けている居住者で不動産所得又は事業所得を生ずべき業務を行うもののうち小規模事業者として政令で定める要件に該当するもの"]],
        ["PS§4.2 所令195一", "shotoku-rei", ["Y7", "Y8"], "195:1:1", "Q", ["その年の前々年分の不動産所得の金額及び事業所得の金額（法第五十七条", "の規定を適用しないで計算した場合の金額とする。）の合計額が三百万円以下であること"]],
        ["PS§4.2 所法36①", "shotoku", ["Y7", "Y8"], "36:1", "Q", ["その年において収入すべき金額"]],
        ["PS§4.3/M C4 所法232② 金額", "shotoku", SO4, "232:2", "A", [3000000]],
        ["PS§4.3/M C4 所法45③ 最初の金額", "shotoku", SO4, "45:3", "A1", 3000000],
        ["PS§4.3 所法45③ 対象", "shotoku", ["Y7", "Y8"], "45:3", "Q", ["その年において不動産所得、事業所得若しくは山林所得を生ずべき業務を行う居住者又はその年において雑所得を生ずべき業務を行う居住者でその年の前々年分の当該雑所得を生ずべき業務に係る収入金額が三百万円を超えるもの", "隠蔽仮装行為"]],
        ["PS§4.3/M C4 所法120⑥（令和7・8年分の版）", "shotoku", ["Y7", "Y8"], "120:6", "Q", ["当該申告書が青色申告書である場合を除く", "前々年分の当該業務に係る収入金額が千万円を超える", "総収入金額及び必要経費の内容を記載した書類"]],
        ["PS§4.3/M C4 所法120⑧（2027-01-01版以後）", "shotoku", ["Y9", "Y30"], "120:8", "Q", ["当該申告書が青色申告書である場合を除く", "前々年分の当該業務に係る収入金額が千万円を超える", "総収入金額及び必要経費の内容を記載した書類"]],
        ["M C4 所法120⑥は2027-01-01版では内訳書の項でない", "shotoku", ["Y9"], "120:6", "NQ", ["総収入金額及び必要経費の内容を記載した書類"]],
        ["PS§4.3 R7法13附則1①五イ（所法120）", "shotoku", ["Y9"], "S:R7:1:1:5", "Q", ["令和九年一月一日", "所得税法第百二十条の改正規定"]],
        ["PS§4.3・§5 R8法12附則1①五イ（所法35⑤・120）", "shotoku", ["Y9"], "S:R8:1:1:5", "Q", ["令和九年一月一日", "第一条中所得税法第三十五条に一項を加える改正規定", "同法第百二十条の改正規定"]],
        ["PS§4.3 R7法13附則8②", "shotoku", ["Y9"], "S:R7:8:2", "Q", ["新所得税法第百二十条第六項及び第七項", "令和九年一月一日以後に令和八年分以後の所得税に係る確定申告書を提出する場合について適用する"]],
        ["PS§4.3 R8法12附則10", "shotoku", ["Y9"], "S:R8:10", "Q", ["新所得税法第百二十条第六項及び第七項", "令和九年一月一日以後に令和八年分以後の所得税に係る確定申告書を提出する場合について適用する"]],
        # ---- §5 所法35⑤
        ["PS§5 所法35⑤（原文）", "shotoku", ["Y9", "Y30"], "35:5", "Q", ["その年中の第二十八条第一項（給与所得）に規定する給与等に係る同条第二項に規定する給与所得控除額とその年中の第三項に規定する公的年金等に係る前項に規定する公的年金等控除額との合計額が二百八十万円を超える場合には、第二項に規定する公的年金等控除額は、前項の規定にかかわらず、同項の規定により計算した金額に相当する金額から当該超える部分の金額を控除した金額とする。"]],
        ["PS§5/M C6 所法35⑤は令和7・8年分の版にない", "shotoku", ["Y7", "Y8"], "35:5", "ABS", None],
        ["PS§5 R8法12附則5", "shotoku", ["Y9"], "S:R8:5", "Q", ["新所得税法第三十五条第五項の規定は、令和九年分以後の所得税について適用する。"]],
        # ---- §6 一時所得
        ["PS§6 所法34①", "shotoku", SO4, "34:1", "Q", ["一時所得とは、利子所得、配当所得、不動産所得、事業所得、給与所得、退職所得、山林所得及び譲渡所得以外の所得のうち、営利を目的とする継続的行為から生じた所得以外の一時の所得で労務その他の役務又は資産の譲渡の対価としての性質を有しないものをいう。"]],
        ["PS§6 所法34②", "shotoku", SO4, "34:2", "Q", ["一時所得の金額は、その年中の一時所得に係る総収入金額からその収入を得るために支出した金額（その収入を生じた行為をするため、又はその収入を生じた原因の発生に伴い直接要した金額に限る。）の合計額を控除し、その残額から一時所得の特別控除額を控除した金額とする。"]],
        ["PS§6/M C3 所法34③", "shotoku", SO4, "34:3", "Q", ["前項に規定する一時所得の特別控除額は、五十万円（同項に規定する残額が五十万円に満たない場合には、当該残額）とする。"]],
        ["PS§6/M C3 所法22②二", "shotoku", SO4, "22:2:2", "Q", ["譲渡所得の金額（第三十三条第三項第二号に掲げる所得に係る部分の金額に限る。）及び一時所得の金額（これらの金額につき第六十九条の規定の適用がある場合には、その適用後の金額）の合計額の二分の一に相当する金額"]],
        ["H6 所法22に端数の規定なし", "shotoku", ["Y7", "Y8"], "22", "NQ", ["端数"]],
        ["PS§6 所法69①", "shotoku", ["Y7", "Y8"], "69:1", "Q", ["不動産所得の金額、事業所得の金額、山林所得の金額又は譲渡所得の金額の計算上生じた損失の金額があるときは", "これを他の各種所得の金額から控除する"]],
        # ---- §7 帳簿
        ["PS§7.1 所法232 見出し", "shotoku", SO4, "232", "CAP", "事業所得等を有する者の帳簿書類の備付け等"],
        ["PS§7.1 所法232①", "shotoku", SO4, "232:1", "Q", ["その年において不動産所得、事業所得若しくは山林所得を生ずべき業務を行う居住者", "（青色申告書を提出することにつき税務署長の承認を受けている者を除く。）は、財務省令で定めるところにより、帳簿を備え付けてこれにこれらの所得を生ずべき業務に係るその年の取引", "のうち総収入金額及び必要経費に関する事項を財務省令で定める簡易な方法により記録し、かつ、当該帳簿（その年においてこれらの業務に関して作成したその他の帳簿及びこれらの業務に関して作成し、又は受領した財務省令で定める書類を含む。", "を保存しなければならない。"]],
        ["PS§7.1 所法232②", "shotoku", SO4, "232:2", "Q", ["その年において雑所得を生ずべき業務を行う居住者", "で、その年の前々年分のこれらの雑所得を生ずべき業務に係る収入金額が三百万円を超えるものは、財務省令で定めるところにより、これらの雑所得を生ずべき業務に係るその年の取引のうち総収入金額及び必要経費に関する事項を記載した書類として財務省令で定める書類を保存しなければならない。"]],
        ["PS§7.1 所法232③", "shotoku", ["Y7", "Y8"], "232:3", "Q", ["第一項の帳簿又は前項の書類を検査する"]],
        ["PS§7.1 所規102 見出し", "shotoku-ki", ["Y7", "Y8"], "102", "CAP", "事業所得等に係る取引に関する帳簿の記録の方法及び帳簿書類の保存"],
        ["PS§7.1 所規102①", "shotoku-ki", ["Y7", "Y8", "Y30"], "102:1", "Q", ["正確に計算できるように", "整然と、かつ、明瞭に記録しなければならない。"]],
        ["PS§7.1 所規102②", "shotoku-ki", ["Y7", "Y8", "Y30"], "102:2", "Q", ["法第二百三十二条第一項に規定する財務省令で定める簡易な方法は、財務大臣の定める記録の方法とする。"]],
        ["PS§7.1 所規102③", "shotoku-ki", ["Y7", "Y8", "Y30"], "102:3", "Q", ["その年の決算に関して作成した棚卸表その他の書類", "請求書、納品書、送り状、領収書その他これらに類する書類（自己の作成したこれらの書類でその写しのあるものは、当該写しを含む。）"]],
        ["PS§7.1/M C5 所規102④", "shotoku-ki", ["Y7", "Y8", "Y30"], "102:4", "Q", ["第六十三条第四項", "に規定する起算日から七年間（その他の帳簿及び前項各号に掲げる書類にあつては、五年間）"]],
        ["PS§7.1 所規102⑥（告示）", "shotoku-ki", ["Y7", "Y8", "Y30"], "102:6", "Q", ["告示"]],
        ["PS§7.1 所規102⑦", "shotoku-ki", ["Y7", "Y8", "Y30"], "102:7", "Q", ["現金の収受若しくは払出し又は預貯金の預入若しくは引出しに際して作成されたもの"]],
        ["PS§7.1/M C5 所規102⑧", "shotoku-ki", ["Y7", "Y8", "Y30"], "102:8", "Q", ["その作成又は受領の日の属する年の翌年三月十五日の翌日から五年間"]],
        ["PS§7.1 所規63④", "shotoku-ki", ["Y7", "Y8"], "63:4", "Q", ["帳簿についてはその閉鎖の日の属する年の翌年三月十五日の翌日をいい、書類についてはその作成又は受領の日の属する年の翌年三月十五日の翌日をいう。"]],
        ["PS§7.1 所規47の3 見出し", "shotoku-ki", ["Y7", "Y8"], "47_3", "CAP", "事業所得等に係る総収入金額及び必要経費の内訳書"],
        ["PS§7.1 所規47の3①", "shotoku-ki", ["Y7", "Y8"], "47_3:1", "Q", ["不動産所得、事業所得若しくは山林所得又は雑所得を生ずべき業務に係る雑所得のそれぞれについて作成", "商品製品等の売上高（加工その他の役務の給付等売上と同様の性質を有する収入金額を含む。）", "賃貸料、山林の伐採又は譲渡による売上高、家事消費の高並びにその他の収入", "商品製品等の売上原価、年初において有する農産物の棚卸高、雇人費、小作料、外注工賃、減価償却費、貸倒金、地代家賃、利子割引料及びその他の経費", "当該項目に準ずる他の項目によることができる"]],
        ["M§3 所規47の3 が引く項（令和7・8年分の版）", "shotoku-ki", ["Y7", "Y8"], "47_3:1", "Q", ["法第百二十条第六項"]],
        ["M§6（未確認→本検証で確認）所規47の3 が引く項（2027-01-01版・2030-12-31版）", "shotoku-ki", ["Y9", "Y30"], "47_3:1", "Q", ["法第百二十条第八項"]],
        ["PS§8-7 所法120①六", "shotoku", ["Y7", "Y8"], "120:1:6", "Q", ["一時所得、雑所得又は雑所得に該当しない臨時所得について源泉徴収をされた又はされるべき所得税の額"]],
        # ---- 実測 §3・§4 の個別の値
        ["M§3 所法120④二の名称（令和7年分の版）", "shotoku", ["Y7"], "120:4:2", "Q", ["社会保険診療報酬支払基金"]],
        ["M§3 所法120④二の名称（令和8年分の版）", "shotoku", ["Y8"], "120:4:2", "Q", ["医療情報基盤・診療報酬審査支払機構"]],
        ["M§3 所法22②一に「第三号」（2030-12-31版）", "shotoku", ["Y30"], "22:2:1", "Q", ["第三号"]],
        ["M§3 所法69②（2030-12-31版）暗号資産", "shotoku", ["Y30"], "69:2", "Q", ["暗号資産"]],
        ["M§3 所規47 に措法41の15の5（令和8年分の版）", "shotoku-ki", ["Y8"], "47", "Q", ["第四十一条の十五の五"]],
        ["M§4.1/I1 所法2①三十四（令和7年分の版）", "shotoku", ["Y7"], "2:1:34", "A", [580000]],
        ["M§4.1/I1 所法2①三十四（令和8年分の版）", "shotoku", ["Y8"], "2:1:34", "A", [620000]],
        ["M§4.3/I2 所法28③一（令和7年分の版）", "shotoku", ["Y7"], "28:3:1", "Q", ["前項に規定する収入金額が百九十万円以下である場合", "六十五万円"]],
        ["M§4.3 所法28③一に収入を限度とする文言なし（令和7年分の版）", "shotoku", ["Y7"], "28:3:1", "NQ", ["満たない場合"]],
        ["M§4.3/H2/I3 措法29の4①（令和8年分の版）", "sochi", ["Y8", "Y9"], "29_4:1", "Q", ["令和八年又は令和九年において", "二百二十万円以下である場合には、当該給与等に係る同条第三項に規定する給与所得控除額は、同項第一号の規定にかかわらず、七十四万円（当該収入金額が七十四万円に満たない場合には、当該収入金額に相当する金額）とする。"]],
        ["I7 措法29の4②二（令和8年分の版）", "sochi", ["Y8"], "29_4:2:2", "Q", ["七十四万千円以上二百十九万千円未満である場合には、当該給与等に係る給与所得の金額は、当該収入金額から七十四万円を控除した残額とする。"]],
        ["I8 国税通則法118①（端数）", "tsusoku", ["Y7"], "118:1", "Q", ["千円未満の端数があるとき"]],
    ],
    "eq": [
        ["M§3 所法 令和7→8年分の版で同文", "shotoku", "Y7", "Y8", ["27", "34", "35", "37", "45", "67", "143", "144", "145", "147", "148", "149", "150", "232"], True],
        ["M§3 所法 令和7→8年分の版で変わる", "shotoku", "Y7", "Y8", ["120", "151"], False],
        ["M§3 所法 2026-12-31→2027-01-01 で変わる", "shotoku", "Y8", "Y9", ["35", "120"], False],
        ["M§3 所法 2027-01-01→2030-12-31 で変わる", "shotoku", "Y9", "Y30", ["22", "35", "69"], False],
        ["M§3 所法 2027-01-01→2030-12-31 で同文（事業・業務雑・一時の計算）", "shotoku", "Y9", "Y30", ["27", "34", "37", "45", "67", "232"], True],
        ["M§3 所令 令和7→8年分の版で同文", "shotoku-rei", "Y7", "Y8", ["96", "195", "196", "196_2", "196_3", "197"], True],
        ["M§3 所令 令和8年分の版→2030-12-31 で同文", "shotoku-rei", "Y8", "Y30", ["96", "195", "196", "196_2", "196_3", "197"], True],
        ["M§3 所規47 令和7→8年分の版で変わる", "shotoku-ki", "Y7", "Y8", ["47"], False],
        ["M§3 所規47の3・102 令和7→8年分の版で同文", "shotoku-ki", "Y7", "Y8", ["47_3", "102"], True],
        ["M§3 所規102 令和8年分の版→2030-12-31 で同文", "shotoku-ki", "Y8", "Y30", ["102"], True],
        ["M§6 所規47の3 令和8年分の版→2027-01-01 で変わる", "shotoku-ki", "Y8", "Y9", ["47_3"], False],
        ["M§3 措法25の2 令和7→8年分の版で同文", "sochi", "Y7", "Y8", ["25_2"], True],
        ["M§3 措法27 令和7→8年分の版で変わる", "sochi", "Y7", "Y8", ["27"], False],
        ["M§3 措法25の2 2026-12-31→2027-01-01 で変わる", "sochi", "Y8", "Y9", ["25_2"], False],
        ["M§3 措法25の2・27 2027-01-01→2030-12-31 で同文", "sochi", "Y9", "Y30", ["25_2", "27"], True],
        ["M§3 措令18の2 令和7→8年分の版で変わる", "sochi-rei", "Y7", "Y8", ["18_2"], False],
        ["M§3 措令18の2 令和8年分の版→2030-12-31 で同文", "sochi-rei", "Y8", "Y30", ["18_2"], True],
        ["M§3 措規9の6 令和7→8年分の版で同文", "sochi-ki", "Y7", "Y8", ["9_6"], True],
        ["M§3 措規9の6 令和8年分の版→2030-12-31 で変わる", "sochi-ki", "Y8", "Y30", ["9_6"], False],
    ],
    "rev": [  # 実測 §2・公開資料の情報 §0 の表
        ["shotoku", "Y7", "340AC0000000033_20251218_507AC0000000013", "PreviousEnforced"],
        ["shotoku", "Y8", "340AC0000000033_20261201_508AC0000000012", "UnEnforced"],
        ["shotoku", "Y9", "340AC0000000033_20270101_508AC0000000012", "UnEnforced"],
        ["shotoku", "Y30", "340AC0000000033_20300619_507AC0000000074", "UnEnforced"],
        ["shotoku-rei", "Y7", "340CO0000000096_20251201_507CO0000000120", "PreviousEnforced"],
        ["shotoku-rei", "Y8", "340CO0000000096_20261201_508CO0000000093", "UnEnforced"],
        ["shotoku-rei", "Y30", "340CO0000000096_20280101_508CO0000000093", "UnEnforced"],
        ["shotoku-ki", "Y7", "340M50000040011_20251201_507M60000040018", "PreviousEnforced"],
        ["shotoku-ki", "Y8", "340M50000040011_20261211_508M60000040017", "UnEnforced"],
        ["shotoku-ki", "Y30", "340M50000040011_20280101_508M60000040017", "UnEnforced"],
        ["sochi", "Y7", "332AC0000000026_20251231_507AC1000000081", "PreviousEnforced"],
        ["sochi", "Y8", "332AC0000000026_20261204_508AC0000000012", "UnEnforced"],
        ["sochi", "Y9", "332AC0000000026_20270101_508AC0000000012", "UnEnforced"],
        ["sochi", "Y30", "332AC0000000026_20300101_505AC0000000003", "UnEnforced"],
        ["sochi-rei", "Y7", "332CO0000000043_20251231_507CO0000000401", "PreviousEnforced"],
        ["sochi-rei", "Y8", "332CO0000000043_20261201_508CO0000000098", "UnEnforced"],
        ["sochi-rei", "Y30", "332CO0000000043_20280401_508CO0000000098", "UnEnforced"],
        ["sochi-ki", "Y7", "332M50000040015_20251231_507M60000040068", "PreviousEnforced"],
        ["sochi-ki", "Y8", "332M50000040015_20261204_508M60000040021", "UnEnforced"],
        ["sochi-ki", "Y30", "332M50000040015_20300101_505M60000040019", "UnEnforced"],
    ],
    "lawnum": {"shotoku": "昭和四十年法律第三十三号", "shotoku-ki": "昭和四十年大蔵省令第十一号",
               "sochi-rei": "昭和三十二年政令第四十三号", "sochi-ki": "昭和三十二年大蔵省令第十五号"},
    "nta": [
        ["PS§2.2 TA1810 版", "ta_1810", "Q", ["[令和8年4月1日現在法令等]"]],
        ["PS§2.2 TA1810 概要", "ta_1810", "Q", ["家内労働者等の場合には、必要経費として69万円まで（令和7年分は65万円、令和2年分から令和6年分までは55万円。以下同じです。）認められる特例があります。", "（注）家内労働者等とは、家内労働法に規定する家内労働者や、外交員、集金人、電力量計の検針人のほか、特定の者に対して継続的に人的役務の提供を行うことを業務とする人をいいます。"]],
        ["PS§2.2 TA1810 両方の所得", "ta_1810", "Q", ["69万円と実際にかかった経費の合計額との差額を、まず雑所得の実際にかかった経費に加えることになります。"]],
        ["PS§2.2 TA1810 給与", "ta_1810", "Q", ["（1）給与の収入金額が69万円以上あるときは、この特例は受けられません。", "（2）給与の収入金額が69万円未満のときは、69万円からその給与に係る給与所得控除額を差し引いた残額と、事業所得や雑所得の実際にかかった経費とを比べて高い方がその事業所得や雑所得の必要経費になります。"]],
        ["PS§2.2 TA1810 注意(1)", "ta_1810", "Q", ["特例の必要経費額は、事業所得や公的年金等以外の雑所得の収入金額が限度です。"]],
        ["PS§2.2/M§4.1 TA1810 注意(2) 令和8年分", "ta_1810", "Q", ["その年の総収入金額が173万円以下の場合は、総所得金額が基礎控除額の104万円以下となりますので、本人に所得税は課されません。また、その年の総収入金額が131万円以下の場合は、扶養者の所得税額の計算上、配偶者控除あるいは扶養控除の対象となります。"]],
        ["PS§2.2/M§4.1 TA1810 注意(2)(注) 令和7年分", "ta_1810", "Q", ["その年の総収入金額が160万円以下の場合は、合計所得金額が基礎控除額の95万円以下となりますので、本人に所得税は課されず、また、扶養者の所得税額の計算上、配偶者控除あるいは扶養控除の対象となります。"]],
        ["PS§2.2 TA1810 注意(4)", "ta_1810", "Q", ["令和8年分の場合は、令和8年12月1日に施行され、令和8年分から適用される金額です。"]],
        ["PS§2.2 TA1810 根拠法令等", "ta_1810", "Q", ["所法2、27、35、83、84、措法27、措法41の16の2、措令18の2"]],
        ["PS§6 TA1490 版・式・2分の1", "ta_1490", "Q", ["[令和8年4月1日現在法令等]", "総収入金額 - 収入を得るために支出した金額(注) - 特別控除額(最高50万円) ＝ 一時所得の金額", "一時所得は、その所得金額の2分の1に相当する金額を給与所得などの他の所得の金額と合計して総所得金額を求めた後、納める税額を計算します。", "懸賞金付預貯金等の懸賞金等"]],
        ["PS§4.1・§6 TA1500", "ta_1500", "Q", ["[令和8年4月1日現在法令等]", "その年の前々年分の収入金額が300万円以下である方は、業務に係る雑所得の金額の計算上総収入金額および必要経費に算入すべき金額は、その年において収入した金額および支出した費用の額とすることができます（いわゆる現金主義の特例）。ただし、この特例を受けるには、確定申告書にこの特例を受ける旨を記載しなければなりません。", "雑所得の金額の計算上生じた損失の金額は、他の所得の金額と損益通算はできません"]],
        ["PS§3.2 TA2072", "ta_2072", "Q", ["[令和8年4月1日現在法令等]", "現金主義による所得計算の特例を選択している方は、55万円の青色申告特別控除を受けることはできません"]],
        ["PS§0 TA2070 版", "ta_2070", "Q", ["[令和8年4月1日現在法令等]"]],
        ["PS§7.2 TA2080", "ta_2080", "Q", ["[令和8年4月1日現在法令等]", "不動産所得、事業所得または山林所得のある方", "売上げなどの収入金額、仕入れや経費に関する事項について、取引の年月日、売上先・仕入先その他の相手方の名称、金額、日々の売上げ・仕入れ・経費の金額等を帳簿に記載します。", "記帳に当たっては、一つ一つの取引ごとではなく、日々の合計金額のみをまとめて記載するなど、簡易な方法で記載してもよいことになっています。", "業務に係る雑所得のある方で、その年の前々年分の業務に係る雑所得の収入金額が300万円を超える方", "令和5年分の確定申告に対する修正申告等から、売上げに関する帳簿を保存していなかったことや帳簿の売上げについて記載が不十分であったことなどが税務調査において把握された場合には", "5パーセントまたは10パーセント"]],
        ["PS§7.2 TA2080 根拠法令等", "ta_2080", "Q", ["所法120、148、232", "所規47の3、102", "電子帳簿保存法2、4、5"]],
        ["PS§1.2・§1.3 TA2210", "ta_2210", "Q", ["[令和8年4月1日現在法令等]", "この家事関連費のうち必要経費になるのは、取引の記録などに基づいて、業務遂行上直接必要であったことが明らかに区分できる場合のその区分できる金額に限られます。", "生計を一にする配偶者その他の親族に支払う地代家賃などは必要経費になりません", "ただし、例えば子が生計を一にする父から業務のために借りた土地・建物に課される固定資産税等の費用は、子が営む業務の必要経費になります"]],
        ["PS§1.2 所基通45−1", "kihon_07_01", "Q", ["45－1", "業務の内容、経費の内容、家族及び使用人の構成、店舗併用の家屋その他の資産の利用状況等を総合勘案して判定する。"]],
        ["PS§1.2 所基通45−2", "kihon_07_01", "Q", ["令第96条第1号に規定する『主たる部分が不動産所得、事業所得、山林所得又は雑所得を生ずべき業務の遂行上必要』であるかどうかは、その支出する金額のうち当該業務の遂行上必要な部分が50％を超えるかどうかにより判定するものとする。ただし、当該必要な部分の金額が50%以下であっても、その必要である部分を明らかに区分することができる場合には、当該必要である部分に相当する金額を必要経費に算入して差し支えない。"]],
        ["PS§6 所基通34−1", "kihon_04_08", "Q", ["懸賞の賞金品、福引の当選金品等（業務に関して受けるものを除く。）", "競馬の馬券の払戻金", "（営利を目的とする継続的行為から生じたものを除く。）", "生命保険契約等に基づく一時金（業務に関して受けるものを除く。）", "法人からの贈与により取得する金品（業務に関して受けるもの及び継続的に受けるものを除く。）", "遺失物拾得者又は埋蔵物発見者が受ける報労金"]],
        ["PS§6 所基通34−3", "kihon_04_08", "Q", ["34－3", "懸賞クイズ等の当選金品の一部を公益施設等に寄附する定めがある場合に当該定めに基づき寄附した金品"]],
        ["PS§4.1 所基通67−6", "kihon_14_02", "Q", ["67－６", "法第67条第２項の規定の適用を受けようとする年の前年末現在において確定しているところにより判定するものとする", "不服申立てに対する決定等により、その年の３月15日までに300万円以下となった者", "令４課個2-13"]],
        ["PS§4.3 所基通120−4の2", "kihon_19_01", "Q", ["120－４の２", "法第120条第８項に規定する「その年の前々年分の当該業務に係る収入金額が1,000万円を超える」かどうかは、その年分の確定申告書を提出する時までに確定しているところにより判定するものとする", "令７課個2-10"]],
        ["PS§7.1 所基通120−5", "kihon_19_01", "Q", ["事業所得を生ずべき業務のうち農業と農業以外の業務を営む場合には、収支内訳書は各別に作成するものとする。"]],
        ["PS§4.3 所基通232−1", "kihon_40_02", "Q", ["232－１", "その年の前年末現在において確定しているところにより判定するものとする"]],
        ["PS§4.3 所基通35−2（注）", "kihon_04_09", "Q", ["その所得に係る取引を記録した帳簿書類の保存がない場合（その所得に係る収入金額が300万円を超え、かつ、事業所得と認められる事実がある場合を除く。）には、業務に係る雑所得"]],
        ["PS§3.2 措置法通達25の2 見出し（65万円又は75万円）", "sochitsu_25_2", "Q", ["（65万円又は75万円の青色申告特別控除）", "25の2－4"]],
        ["PS§3.2 措置法通達25の2 令8課個2-10", "sochitsu_25_2", "Q", ["令８課個2-10"]],
        ["PS§2.5/M§5 措置法通達目次に第27条（家内労働者等）関係なし", "sochitsu_toc", "NQ", ["家内労働者"]],
        ["PS§3.2/M§5 措置法通達目次に第25条の2関係あり", "sochitsu_toc", "Q", ["第25条の2（（青色申告特別控除））関係"]],
        ["PS§6 質疑応答 02/04", "shitsugi_02_04", "Q", ["(100万円+2,000万円)", "(200万円+1,200万円)", "50万円", "=650万円", "定期保険の保険期間が満了した場合のように収入金額（満期保険金等）のないものは内部通算できません。", "令和7年8月1日現在の法令・通達等に基づいて作成"]],
        ["PS§2.5/M§5 質疑応答 04/34", "shitsugi_04_34", "Q", ["本特例の適用を受けることはできません。", "必要経費として55万円まで", "人的役務の提供先を広く募るなど、その業務の性質上、不特定の者を対象として人的役務の提供をする場合における人的役務の提供先は、上記の「特定の者」に当たりませんので、本特例の適用を受けることはできません。", "令和７年８月１日現在施行の法令・通達等に基づいて作成"]],
        ["M§5/PS§7.4 様式一覧は令和7年分まで", "yoshiki_index", "Q", ["令和７年分の確定申告書等の様式・手引き等"]],
        ["M§5/PS§7.4 様式一覧に令和8年分なし", "yoshiki_index", "NQ", ["令和８年分の確定申告書等の様式"]],
        ["PS§0 所基通の番号（前文）", "kihon_zenbun", "Q", ["昭和45年7月1日", "直審（所）30"]],
    ],
    "links": [
        ["PS§7.4 r07 一覧から収支内訳書（一般用）05.pdf", "yoshiki_r07", "/yoshiki/01/shinkokusho/pdf/r07/05.pdf"],
        ["I2 TA1810 から入力方法の PDF", "ta_1810", "/taxanswer/shotoku/pdf/1810.pdf"],
        ["PS§2.3 TA1810 から計算書（様式一覧 1557_2.htm#a39 経由）", "ta_1810", "/annai/1557_2.htm#a39"],
    ],
}


def kyuyo_shotoku(year, x, tab_r7, tab_r8):
    """給与所得の金額（収入 x。この検証で使う範囲だけ）。令和7年分：所法28④・別表第五（e-Gov の表から読んだ境目）。
    令和8年分：措法29の4②（69.1万〜219.1万円）、69.1万円未満は別表第五。"""
    if year == 7:
        lo, hi, ded = tab_r7
        if x < lo:
            return 0
        if x < hi:
            return x - ded
        raise ValueError("範囲外")
    if 691000 <= x < 741000:
        return 0
    if 741000 <= x < 2191000:
        return x - 740000
    lo, hi, ded = tab_r8
    if x < lo:
        return 0
    raise ValueError("範囲外")


def beppyo5_rows(short, asof):
    """別表第五の最初の2つの区分（「X円未満 → 0」「X以上Y未満 → 給与等の金額からZ円を控除した金額」）を読む。"""
    d = law(short, asof)
    t = [x for x in d["appdx"] if x["title"].startswith("別表第五")][0]

    def z(s):
        return int(norm(s).replace(",", "").replace("円", "").replace("未満", ""))
    first = [r for r in t["rows"] if r and "未満" in r[0]][0]
    lo = z(first[0])
    assert norm(first[1]) == "0"
    second = [r for r in t["rows"] if r and norm(r[0]).replace(",", "") == str(lo)][0]
    hi = z(second[1])
    m = re.search(r"給与等の金額から([0-9,]+)円を控除した金額", norm(second[2]))
    return {"first_row": first[:2], "second_row": second[:3], "parsed": (lo, hi, int(m.group(1).replace(",", "")))}


def mode_check():
    claims = CLAIMS
    asof_alias = {"Y7": Y7, "Y8": Y8, "Y9": Y9, "Y30": Y30}
    res = {"law": [], "eq": [], "rev": [], "lawnum": [], "nta": [], "links": [], "calc": {}}
    for cid, short, asofs, where, kind, payload in claims["law"]:
        for asof in [asof_alias[a] for a in asofs]:
            try:
                node, text = loc(short, asof, where)
            except FileNotFoundError:
                res["law"].append({"id": cid, "asof": asof, "where": where, "ok": None, "note": "未取得"})
                continue
            r = {"id": cid, "short": short, "asof": asof, "where": where, "kind": kind}
            if kind == "ABS":
                r["ok"] = node is None
            elif node is None:
                r["ok"], r["note"] = False, "条・項・号が見つからない"
            elif kind == "Q":
                bad = [contains_seq(text, q)[1] for q in payload if not contains_seq(text, q)[0]]
                r["ok"], r["missing"] = not bad, bad
            elif kind == "NQ":
                r["ok"] = not any(norm(q) in norm(text) for q in payload)
            elif kind == "A":
                got = sorted(set(yen(text)))
                r["ok"], r["got"] = got == sorted(set(payload)), got
            elif kind == "A1":
                got = yen(text)[:1]
                r["ok"], r["got"] = got == [payload], got
            elif kind == "CAP":
                r["ok"], r["got"] = norm(node["caption"]) == norm(f"（{payload}）"), node["caption"]
            elif kind == "NOCHILD":
                r["ok"], r["got"] = not node["children"], list(node["children"])
            res["law"].append(r)
    for cid, short, a, b, nums, expect in claims["eq"]:
        a, b = asof_alias[a], asof_alias[b]
        for n in nums:
            ta, tb = loc(short, a, n)[1], loc(short, b, n)[1]
            same = norm(ta) == norm(tb)
            res["eq"].append({"id": cid, "short": short, "art": n, "a": a, "b": b, "same": same, "expected_same": expect, "ok": same == expect})
    for short, asof, rid, stt in claims["rev"]:
        ri = law(short, asof_alias[asof])["revision_info"]
        res["rev"].append({"short": short, "asof": asof_alias[asof], "claimed": [rid, stt], "got": [ri["law_revision_id"], ri["current_revision_status"]],
                           "ok": ri["law_revision_id"] == rid and ri["current_revision_status"] == stt})
    lk = json.loads((OUT / "egov_log.json").read_text(encoding="utf-8"))["lookups"]
    for short, v in lk.items():
        nums = [x["law_num"] for x in v["exact_title_matches"]]
        claimed = claims["lawnum"].get(short)
        res["lawnum"].append({"short": short, "claimed_law_id": v["claimed_law_id"], "claimed_law_id_found": v["claimed_matches"],
                              "law_nums": nums, "claimed_law_num": claimed,
                              "ok": v["claimed_matches"] and (claimed is None or claimed in nums)})
    nta = OUT / "nta"
    for cid, page, kind, quotes in claims["nta"]:
        p = nta / f"{page}.txt"
        if not p.exists():
            res["nta"].append({"id": cid, "page": page, "ok": None, "note": "未取得"})
            continue
        t = p.read_text(encoding="utf-8")
        if kind == "Q":
            bad = [q for q in quotes if not contains_seq(t, q)[0]]
            res["nta"].append({"id": cid, "page": page, "ok": not bad, "missing": bad})
        else:
            hit = [q for q in quotes if norm(q) in norm(t)]
            res["nta"].append({"id": cid, "page": page, "ok": not hit, "unexpected": hit})
    for cid, page, tail in claims["links"]:
        links = json.loads((nta / f"{page}.links.json").read_text(encoding="utf-8"))
        res["links"].append({"id": cid, "page": page, "ok": any(x["href"].endswith(tail) for x in links), "tail": tail})

    # ---- 再計算（担当の IMPL_jigyo_checks.py とは別に書いた）
    c = res["calc"]
    fuyo = {7: yen(loc("shotoku", Y7, "2:1:34")[1])[-1], 8: yen(loc("shotoku", Y8, "2:1:34")[1])[-1]}
    kanai = {7: yen(loc("sochi", Y7, "27")[1])[0], 8: yen(loc("sochi", Y8, "27")[1])[0]}
    kiso_ta = {7: 950000, 8: 1040000}  # TA No.1810 の本文の値（条文では確かめていない）
    c["C9"] = {"fuyo_from_law": fuyo, "kanai_from_law": kanai,
               "upper_for_fuyo": {y: kanai[y] + fuyo[y] for y in (7, 8)},
               "upper_for_no_tax_using_TA_kiso": {y: kanai[y] + kiso_ta[y] for y in (7, 8)},
               "doc_claims": {"upper_for_fuyo": {7: 1230000, 8: 1310000}, "upper_for_no_tax": {7: 1600000, 8: 1730000}}}
    c["C9"]["ok"] = c["C9"]["upper_for_fuyo"] == c["C9"]["doc_claims"]["upper_for_fuyo"] and \
        c["C9"]["upper_for_no_tax_using_TA_kiso"] == c["C9"]["doc_claims"]["upper_for_no_tax"]

    b7, b8 = beppyo5_rows("shotoku", Y7), beppyo5_rows("shotoku", Y8)
    c["beppyo5"] = {"R7": b7, "R8": b8}
    t7, t8 = b7["parsed"], b8["parsed"]

    def seirei(base, sal, Rb, Eb, Rm, Em):
        """措令18の2② の文言どおり（給与の調整は計算書と同じく給与の収入金額、特例額が上限）。"""
        F = base - min(sal, base)
        if not (Eb + Em < F):
            return None
        if Rb > 0 and Rm == 0:
            return (min(F, Rb), 0)
        if Rm > 0 and Rb == 0:
            return (0, min(F, Rm))
        ro = F - min(F, Eb)                     # ロ：F のうち事業の必要経費に達するまでの部分「以外」の部分
        i = min(F, Eb + max(0, ro - Rm))        # イ：F のうち（事業の必要経費＋雑収入がロに満たない部分）に達するまでの部分
        return (min(i, Rb), min(ro, Rm))        # 措法27 後段：総収入金額が限度

    def sheet(base, sal, Rb, Eb, Rm):
        """国税庁の計算書 ⑤〜⑨。"""
        v5 = max(0, base - Eb - sal)
        v6 = max(0, base - Rm - sal)
        if Rb > 0:
            v_biz = min(Rb, v6) if (Rm == 0 or Rm <= v5) else Eb   # ⑦ または ⑧
        else:
            v_biz = 0
        v_misc = min(Rm, v5) if Rm > 0 else 0                      # ⑨
        return (v_biz, v_misc)

    g = range(0, 1000001, 50000)
    st = {"grid": "事業収入0〜100万(5万)×事業経費0〜70万(5万)×雑収入0〜100万(5万)×雑経費0〜30万(10万)×給与0/30万/60万、特例額65万",
          "all_combos": 0, "skipped_no_income": 0, "not_eligible": 0, "skipped_Rb0_Eb_pos": 0,
          "compared": 0, "equal": 0, "diff": 0, "diff_with_Eb_le_Rb": 0, "diff_examples": [],
          "if_Rb0_Eb_pos_included": {"compared": 0, "diff": 0}}
    for Rb, Eb, Rm, Em, sal in itertools.product(g, range(0, 700001, 50000), g, range(0, 300001, 100000), (0, 300000, 600000)):
        st["all_combos"] += 1
        if Rb == 0 and Rm == 0:
            st["skipped_no_income"] += 1
            continue
        a = seirei(650000, sal, Rb, Eb, Rm, Em)
        if a is None:
            st["not_eligible"] += 1
            continue
        b = sheet(650000, sal, Rb, Eb, Rm)
        if Rb == 0 and Eb > 0:
            st["skipped_Rb0_Eb_pos"] += 1
            st["if_Rb0_Eb_pos_included"]["compared"] += 1
            st["if_Rb0_Eb_pos_included"]["diff"] += int(a != b)
            continue
        st["compared"] += 1
        if a == b:
            st["equal"] += 1
        else:
            st["diff"] += 1
            if Eb <= Rb:
                st["diff_with_Eb_le_Rb"] += 1
            if len(st["diff_examples"]) < 3:
                st["diff_examples"].append({"Rb": Rb, "Eb": Eb, "Rm": Rm, "Em": Em, "sal": sal, "seirei": a, "sheet": b})
    st["doc_claims"] = {"compared": 24120, "equal": 21524, "diff": 2596, "diff_only_when_Eb_gt_Rb": True}
    st["ok"] = (st["compared"], st["equal"], st["diff"], st["diff_with_Eb_le_Rb"]) == (24120, 21524, 2596, 0)
    ex = seirei(650000, 300000, 50000, 100000, 300000, 0), sheet(650000, 300000, 50000, 100000, 300000)
    st["doc_example_Rb5_Eb10_Rm30_sal30"] = {"seirei": ex[0], "sheet": ex[1], "ok": ex[0][0] == 50000 and ex[1][0] == 100000}
    c["C10"] = st

    rows = []
    doc = {0: (650000, 650000, 690000, 690000), 100000: (0, 550000, 590000, 590000), 300000: (0, 350000, 390000, 390000),
           640000: (0, 10000, 50000, 50000), 650000: (0, 0, 40000, 40000), 690000: (0, 0, 0, 0), 700000: (0, 0, 0, 0),
           740000: (0, 0, 0, 0)}
    for s in doc:
        r7_lit = 650000 - (650000 if 0 < s <= 1900000 else 0)
        r8_29 = 690000 - (min(740000, s) if 0 < s <= 2200000 else 0)
        r = {"salary": s, "R7_literal": max(0, r7_lit), "R7_sheet": max(0, 650000 - s),
             "R8_sochi29_4": max(0, r8_29), "R8_sheet": max(0, 690000 - s)}
        r["ok"] = (r["R7_literal"], r["R7_sheet"], r["R8_sochi29_4"], r["R8_sheet"]) == doc[s]
        rows.append(r)
    c["C11"] = rows

    def kanai_only(year, R, E, sal):
        base = kanai[year]
        F = base - min(sal, base)
        return min(F, R) if E < F else E

    inf = {"I1": []}
    for y, R, exp_inc, exp_fuyo in [(7, 1230000, 580000, True), (7, 1230001, 580001, False), (8, 1310000, 620000, True),
                                    (8, 1310001, 620001, False), (7, 1600000, 950000, False)]:
        inc = R - kanai_only(y, R, 100000, 0)
        inf["I1"].append({"year": y, "R": R, "income": inc, "fuyo": inc <= fuyo[y],
                          "ok": inc == exp_inc and (inc <= fuyo[y]) == exp_fuyo})
    sal, R, E = 300000, 800000, 50000
    ks = kyuyo_shotoku(7, sal, t7, t8)
    F_sheet, F_lit = 650000 - sal, 650000 - 650000
    z_sheet = R - (min(F_sheet, R) if E < F_sheet else E)
    z_lit = R - (min(F_lit, R) if E < F_lit else E)
    inf["I2"] = {"kyuyo_shotoku": ks, "sheet": {"F": F_sheet, "zatsu": z_sheet, "total": z_sheet + ks},
                 "literal": {"F": F_lit, "zatsu": z_lit, "total": z_lit + ks},
                 "ok": (ks, F_sheet, z_sheet, F_lit, z_lit) == (0, 350000, 450000, 0, 750000)
                 and z_sheet + ks <= fuyo[7] < z_lit + ks}
    ks8 = kyuyo_shotoku(8, sal, t7, t8)
    F8 = 690000 - min(740000, sal)
    z8 = R - (min(F8, R) if E < F8 else E)
    inf["I3"] = {"kyuyo_shotoku": ks8, "F": F8, "zatsu": z8, "total": z8 + ks8,
                 "ok": (ks8, F8, z8, z8 + ks8) == (0, 390000, 410000, 410000) and z8 + ks8 <= fuyo[8]}
    a, b = seirei(650000, 0, 300000, 50000, 200000, 0), sheet(650000, 0, 300000, 50000, 200000)
    inf["I4A"] = {"seirei": a, "sheet": b, "sheet_v5": 650000 - 50000, "sheet_v6": 650000 - 200000, "ok": a == b == (300000, 200000)}
    inf["I5"] = {"40%": 120000 * 40 // 100, "60%": 120000 * 60 // 100,
                 "ok": (120000 * 40 // 100, 120000 * 60 // 100) == (48000, 72000)}

    def ichiji(Rx, Ex=0):
        rest = Rx - Ex
        return max(0, rest - min(500000, rest))
    i7 = []
    for y, salx, prize, exp in [(7, 1000000, 700000, (350000, 200000, 100000, 450000, True)),
                                (8, 1000000, 700000, (260000, 200000, 100000, 360000, True)),
                                (7, 1000000, 400000, (350000, 0, 0, 350000, True)),
                                (7, 1000000, 1800000, (350000, 1300000, 650000, 1000000, False))]:
        k = kyuyo_shotoku(y, salx, t7, t8)
        ic = ichiji(prize)
        tot = k + ic // 2
        got = (k, ic, ic // 2, tot, tot <= fuyo[y])
        i7.append({"year": y, "salary": salx, "prize": prize, "got": got, "ok": got == exp})
    inf["I7"] = i7
    inf["I1_age_at_year_end(2008-05-01生)"] = {"2025-12-31": 2025 - 2008, "2026-12-31": 2026 - 2008}
    c["inferences"] = inf
    c["H3_aoiro_special_deduction"] = {
        "sochi25_2_amounts_R7": sorted(set(yen(loc("sochi", Y7, "25_2")[1]))),
        "max_R7_R8": max(yen(loc("sochi", Y7, "25_2:4")[1])),
        "doc_claim_max": 550000}
    c["H3_aoiro_special_deduction"]["ok"] = c["H3_aoiro_special_deduction"]["max_R7_R8"] == 550000

    # 担当が「分からなかった」とした点（egov3 の出力）
    e3p = OUT / "egov3.json"
    if e3p.exists():
        e3 = json.loads(e3p.read_text(encoding="utf-8"))
        gap = {"sochi27_amounts_past": {k: sorted(set(yen(v["text"]))) for k, v in e3["sochi27_past"].items()},
               "sochi27_revision_past": {k: v["law_revision_id"] for k, v in e3["sochi27_past"].items()}}
        revs = sorted(e3["shotoku151_by_revision"].values(), key=lambda r: (r["amendment_enforcement_date"], r["law_revision_id"]))
        gap["shotoku151_first_new_text"] = [r["law_revision_id"] for r in revs if r.get("new_text")][:2]
        gap["shotoku151_last_old_text"] = [r["law_revision_id"] for r in revs if r.get("old_text")][-1:]
        any_r = next((r for r in revs if r.get("R5law3_suppl_5")), {})
        gap["R5law3_suppl_1_1_6"] = any_r.get("R5law3_suppl_1_1_6")
        gap["R5law3_suppl_5"] = any_r.get("R5law3_suppl_5")
        gap["ok_sochi27_550000"] = all(v == [550000] for v in gap["sochi27_amounts_past"].values())
        gap["ok_151_by_R5law3"] = bool(gap["R5law3_suppl_1_1_6"]) and contains_seq(gap["R5law3_suppl_1_1_6"], "令和八年一月一日…第一条中所得税法第百五十一条の改正規定")[0] \
            and contains_seq(gap["R5law3_suppl_5"] or "", "新所得税法第百五十一条…令和八年分以後の所得税につき青色申告書の提出をやめようとする場合について適用し")[0]
        c["gap_fill"] = gap
    c["gap_fill_shotoku_ki_47_3_at_2027_01_01"] = "法第百二十条第八項" in norm(loc("shotoku-ki", Y9, "47_3:1")[1])
    c["tsusoku118"] = {"text": loc("tsusoku", Y7, "118:1")[1], "revision": law("tsusoku", Y7)["revision_info"]}

    def cnt(lst):
        return {"total": len(lst), "ok": sum(1 for x in lst if x.get("ok") is True),
                "ng": [x for x in lst if x.get("ok") is False], "unknown": [x for x in lst if x.get("ok") is None]}
    summary = {k: cnt(res[k]) for k in ("law", "eq", "rev", "lawnum", "nta", "links")}
    calc_ok = {"C9": c["C9"]["ok"], "C10": c["C10"]["ok"], "C10_example": c["C10"]["doc_example_Rb5_Eb10_Rm30_sal30"]["ok"],
               "C11": all(r["ok"] for r in c["C11"]), "I1": all(r["ok"] for r in inf["I1"]), "I2": inf["I2"]["ok"],
               "I3": inf["I3"]["ok"], "I4A": inf["I4A"]["ok"], "I5": inf["I5"]["ok"], "I7": all(r["ok"] for r in inf["I7"]),
               "H3_doc_claim_max_550000_holds(偽なら仮説H3の誤り)": c["H3_aoiro_special_deduction"]["ok"]}
    out = {"summary": {k: {"total": v["total"], "ok": v["ok"], "ng": len(v["ng"]), "unknown": len(v["unknown"])} for k, v in summary.items()},
           "calc_ok": calc_ok, "ng": {k: v["ng"] for k, v in summary.items()}, "unknown": {k: v["unknown"] for k, v in summary.items()},
           "detail": res}
    (OUT / "check.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# IMPL_jigyo_verify check の結果", "", f"主張の定義：scripts/IMPL_jigyo_verify.py の CLAIMS", "", "## 件数", ""]
    for k, v in out["summary"].items():
        md.append(f"- {k}: 全 {v['total']} 件、一致 {v['ok']}、不一致 {v['ng']}、未確認 {v['unknown']}")
    md += ["", "## 再計算の一致", "", "```json", json.dumps(calc_ok, ensure_ascii=False, indent=1), "```", "",
           "## 不一致", "", "```json", json.dumps(out["ng"], ensure_ascii=False, indent=1), "```", "",
           "## 再計算の詳細", "", "```json", json.dumps(c, ensure_ascii=False, indent=1), "```", ""]
    (OUT / "check.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps(out["summary"], ensure_ascii=False))
    print(json.dumps(calc_ok, ensure_ascii=False))
    print(json.dumps(out["ng"], ensure_ascii=False, indent=1)[:8000])


if __name__ == "__main__":
    m = sys.argv[1] if len(sys.argv) > 1 else ""
    if m == "egov":
        mode_egov()
    elif m == "nta":
        mode_nta()
    elif m == "nta2":
        mode_nta(PAGES2, "nta2")
    elif m == "egov2":
        mode_egov2()
    elif m == "egov3":
        mode_egov3()
    elif m == "check":
        mode_check()
    else:
        raise SystemExit("mode は egov / nta / nta2 / egov2 / egov3 / check")

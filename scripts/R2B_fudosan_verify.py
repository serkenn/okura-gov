"""R2B_fudosan_verify: 不動産所得（第2ラウンド追加分、トピック fudosan）の文書の独立検証（反証役）。

担当の文書（docs/*/20261109_round2b_fudosan-*.md）に書かれた条番号・項号・数値・施行日・適用年分・URL・版を、
一次情報に自分で当たり直して確かめる。担当のスクリプト（R2B_fudosan_laws/nta/pdftext/checks.py）とその出力は使わない
（check モードは、文書［PS］［M］に書かれた law_revision_id・Last-Modified・SHA-256 などの値を読んで、検証側の取得と比べる）。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_fudosan_verify.py egov
      e-Gov 法令API v2：/laws?law_title= で law_id を引き直し、/law_data/<law_id>?asof= で各時点の本文を取り、
      対象の条を「条→項→号」の構造のまま JSON にする。所令は 2026-03-31・2026-04-01・2028-01-01 も取り、
      令和8年政令第93号の附則を構造で取り出す。地方税法は全文から「第四十一条の四」を探す。
      /law_revisions（amendment_date_from=2025-01-01 と、指定なし）で改正履歴の件数を数える。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_fudosan_verify.py nta
      先に https://www.nta.go.jp/robots.txt を取得・判定し（許されない URL があれば中止）、国税庁の HTML（テキスト化）と
      PDF（保存とハッシュだけ）を取得する。書き方の PDF（AESV3）は Read ツールのページ指定で目視した。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_fudosan_verify.py pdf shushi_r07=<09.pdf のパス> kessan_r07=<12.pdf のパス>
      様式の PDF（AESV2、空のユーザーパスワード）を復号し、ページごとの文字列と位置を取り出す（下の PDF の節の注記のとおり、
      scripts/R2X_aoiro_verify.py の実装を写したもの。担当の R2B_fudosan_pdftext.py は使わない）。パスは nta モードの保存先。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_fudosan_verify.py check
      ネットワークを使わず、上の出力から文書の主張（引用・項号・金額・版・施行日・Last-Modified・SHA-256）を突き合わせ、
      推測の文書の計算例を担当とは別に書いた式で計算し直す。文書の参照のルール（仮説・推測に外部 URL がないか）も検査する。

- ダウンロードしたものは信頼できないデータ。取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_R2B_fudosan_verify_<mode>/ に置き、その中でインタプリタやツールは実行しない。
- 出力は scripts/results/R2B_fudosan_verify/。
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。GET だけで、個人の情報は送らない。官報は取得しない。
- e-Gov の取得（http_get・walk・flat の形）は scripts/R1_egov_articles.py・scripts/IMPL_kyuyo_fetch.py を写したもの（import しない）。
"""
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
OUT = ROOT / "scripts" / "results" / "R2B_fudosan_verify"
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
WAIT = 1.5
TODAY = "2026-11-09"
R7, NOW, R8, R9 = "2025-12-31", "2026-11-09", "2026-12-31", "2027-01-01"

# 略称: (法令名, 担当が書いた law_id, [asof], [本則の条 Num], [附則を取り出す改正法令（AmendLawNum の正規表現）])
LAWS = {
    "shotoku": ("所得税法", "340AC0000000033", [R7, NOW, R8, R9],
                ["2", "22", "26", "27", "33", "36", "37", "51", "56", "57", "63", "64", "67", "67_2", "69", "70", "143", "152"], []),
    "shotoku-rei": ("所得税法施行令", "340CO0000000096", [R7, "2026-03-31", "2026-04-01", NOW, R8, R9, "2028-01-01"],
                    ["79", "80", "178", "179", "180", "198", "200"], [r"令和八年.*政令第九三号"]),
    "sochi": ("租税特別措置法", "332AC0000000026", [R7, NOW, R8, R9], ["12", "25_2", "41_4", "41_4_2", "41_4_3"], []),
    "sochi-rei": ("租税特別措置法施行令", "332CO0000000043", [R7, NOW, R8], ["26_6", "26_6_2", "26_6_3"], []),
    "chiho": ("地方税法", "325AC0000000226", [R7, R8, R9], ["313"], []),
}
REV_LAWS = ["shotoku", "shotoku-rei", "sochi", "sochi-rei"]


# ---------------------------------------------------------------- 共通
def http_get(url, accept=None):
    h = {"User-Agent": UA}
    if accept:
        h["Accept"] = accept
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            st, body, hd, final = r.status, r.read(), dict(r.headers), r.geturl()
    except urllib.error.HTTPError as e:
        st, body, hd, final = e.code, e.read(), dict(e.headers or {}), url
    time.sleep(WAIT)
    return st, body, hd, final


def new_dl(mode):
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2B_fudosan_verify_{mode}"
    dl.mkdir(parents=True, exist_ok=False)
    return ts, dl


def rel(p):
    return str(pathlib.Path(p).relative_to(ROOT)).replace("\\", "/")


def wjson(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def rjson(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- e-Gov（構造のまま取り出す）
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
            walk(c, fn, path + (n,))


def rev_info(d):
    ri = d.get("revision_info") or {}
    return {k: ri.get(k) for k in ("law_revision_id", "amendment_law_num", "amendment_law_title", "amendment_enforcement_date",
                                   "amendment_promulgate_date", "current_revision_status", "updated")}


def extract(d, nums, suppl_res):
    main, suppl, index = {}, {}, []

    def f(n, path):
        tags = [p.get("tag") for p in path]
        if n.get("tag") == "Article" and "SupplProvision" not in tags:
            num = n.get("attr", {}).get("Num")
            index.append([num, "".join(flat(c) for c in kids(n, "ArticleCaption"))])
            if num in nums:
                main[num] = article(n)
        if n.get("tag") == "SupplProvision":
            an = n.get("attr", {}).get("AmendLawNum") or ""
            if an and any(re.search(r, an) for r in suppl_res):
                arts = {}
                walk(n, lambda x, p: arts.__setitem__(x["attr"].get("Num"), article(x)) if x.get("tag") == "Article" else None)
                suppl.setdefault(an, []).append({"full": flat(n), "arts": arts})
    walk(d["law_full_text"], f)
    return main, suppl, index


def grep_all(d, needle):
    hits = []

    def f(n, path):
        if n.get("tag") in ("Sentence",):
            t = flat(n)
            if needle in t:
                sp = [p for p in path if p.get("tag") == "SupplProvision"]
                art = [p for p in path if p.get("tag") == "Article"]
                hits.append({"suppl": (sp[0].get("attr", {}).get("AmendLawNum") or "(原始附則)") if sp else None,
                             "article": art[-1].get("attr", {}).get("Num") if art else None, "snippet": t[:200]})
    walk(d["law_full_text"], f)
    return hits


def mode_egov():
    ts, dl = new_dl("egov")
    log = {"run_at": ts, "download_dir": rel(dl), "lookups": {}, "fetches": [], "revisions": {}}
    for i, (short, (title, claimed, asofs, nums, sre)) in enumerate(LAWS.items(), 1):
        url = f"{API}/laws?" + urllib.parse.urlencode({"law_title": title, "response_format": "json", "asof": TODAY})
        st, body, _, _ = http_get(url, "application/json")
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
            st, body, _, _ = http_get(furl, "application/json")
            raw = dl / f"{short}_{asof}.json"
            raw.write_bytes(body)
            if st != 200:
                log["fetches"].append({"short": short, "asof": asof, "url": furl, "status": st})
                print("ERR", short, asof, st, flush=True)
                continue
            d = json.loads(body)
            main, suppl, index = extract(d, nums, sre)
            rec = {"short": short, "asof": asof, "url": furl, "status": st, "raw": rel(raw),
                   "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body),
                   "law_num": (d.get("law_info") or {}).get("law_num"),
                   "revision_info": rev_info(d), "missing": [x for x in nums if x not in main], "suppl_keys": sorted(suppl)}
            extra = {}
            if short == "chiho":
                extra["grep_41_4"] = grep_all(d, "第四十一条の四")
                extra["grep_sochi_41_4_kanji"] = grep_all(d, "租税特別措置法第四十一条の四")
            wjson(OUT / "egov" / f"{short}_{asof}.json", {**rec, "main": main, "suppl": suppl, "index": index, **extra})
            log["fetches"].append(rec)
            print("ok", short, asof, rec["revision_info"]["law_revision_id"], rec["revision_info"]["current_revision_status"],
                  rec["missing"], flush=True)
    for short in REV_LAWS:
        law_id = LAWS[short][1]
        for label, q in [("from_2025", {"response_format": "json", "amendment_date_from": "2025-01-01"}),
                         ("all", {"response_format": "json"})]:
            url = f"{API}/law_revisions/{law_id}?" + urllib.parse.urlencode(q)
            st, body, _, _ = http_get(url, "application/json")
            (dl / f"revisions_{short}_{label}.json").write_bytes(body)
            revs = []
            if st == 200:
                for r in json.loads(body).get("revisions", []):
                    revs.append({k: r.get(k) for k in ("law_revision_id", "amendment_promulgate_date", "amendment_enforcement_date",
                                                       "amendment_scheduled_enforcement_date", "amendment_law_num",
                                                       "amendment_law_title", "current_revision_status")})
            log["revisions"][f"{short}_{label}"] = {"url": url, "status": st, "n": len(revs), "sha256": hashlib.sha256(body).hexdigest(),
                                                     "revisions": revs}
            print("rev", short, label, st, len(revs), flush=True)
    wjson(OUT / "egov_log.json", log)


# ---------------------------------------------------------------- 国税庁
NTA = "https://www.nta.go.jp"
TA = NTA + "/taxes/shiraberu/taxanswer/shotoku/"
KIHON = NTA + "/law/tsutatsu/kihon/shotoku/"
SOCHI = NTA + "/law/tsutatsu/kobetsu/shotoku/sochiho/801226/sinkoku/"
PAGES = {
    "ta_1370": TA + "1370.htm", "ta_1373": TA + "1373.htm", "ta_1376": TA + "1376.htm", "ta_1391": TA + "1391.htm",
    "ta_1399": TA + "1399.htm", "ta_2072": TA + "2072.htm", "ta_2075": TA + "2075.htm", "ta_2210": TA + "2210.htm",
    "ta_2250": TA + "2250.htm",
    "kihon_04_02": KIHON + "04/02.htm", "kihon_05_01": KIHON + "05/01.htm", "kihon_09_01": KIHON + "09/01.htm",
    "kihon_09_02": KIHON + "09/02.htm", "kihon_11_01": KIHON + "11/01.htm", "kihon_13_01": KIHON + "13/01.htm",
    "kihon_15_01": KIHON + "15/01.htm",
    "sochitsu_41_4": SOCHI + "57/41/04.htm", "sochitsu_41_4_2": SOCHI + "57/41/04_2.htm", "sochitsu_41_4_3": SOCHI + "57/41/04_3.htm",
    "kobetsu_731106": NTA + "/law/tsutatsu/kobetsu/shotoku/shinkoku/731106/01.htm",
    "kobetsu_index": NTA + "/law/tsutatsu/kobetsu/shotoku/shinkoku/shinkoku.htm",
    "shitsugi_02_27": NTA + "/law/shitsugi/shotoku/02/27.htm", "shitsugi_04_14": NTA + "/law/shitsugi/shotoku/04/14.htm",
    "yoshiki_r07": NTA + "/taxes/shiraberu/shinkoku/syotoku/r07.htm", "yoshiki_r08": NTA + "/taxes/shiraberu/shinkoku/syotoku/r08.htm",
    "pdf_shushi_r07": NTA + "/taxes/shiraberu/shinkoku/yoshiki/01/shinkokusho/pdf/r07/09.pdf",
    "pdf_shushi_kakikata_r07": NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/pdf/019.pdf",
    "pdf_kessan_r07": NTA + "/taxes/shiraberu/shinkoku/yoshiki/01/shinkokusho/pdf/r07/12.pdf",
    "pdf_kessan_kakikata_r07": NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/pdf/039.pdf",
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
    st, body, _, _ = http_get(NTA + "/robots.txt")
    (dl / "robots.txt").write_bytes(body)
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(body.decode("utf-8", "replace").splitlines())
    robots = {"fetched_at": ts, "status": st, "sha256": hashlib.sha256(body).hexdigest(), "saved": rel(dl / "robots.txt"),
              "allowed": {k: rp.can_fetch(UA, u) for k, u in PAGES.items()}}
    wjson(OUT / "nta_robots.json", robots)
    if not all(robots["allowed"].values()):
        print("robots.txt で許されない URL がある。中止", [k for k, v in robots["allowed"].items() if not v])
        return
    log = {"run_at": ts, "download_dir": rel(dl), "items": []}
    for key, url in PAGES.items():
        try:
            st, body, hd, final = http_get(url)
        except Exception as e:  # noqa: BLE001
            log["items"].append({"id": key, "url": url, "error": repr(e)})
            print("ERR", key, repr(e), flush=True)
            continue
        if urllib.parse.urlsplit(final).hostname != "www.nta.go.jp":
            log["items"].append({"id": key, "url": url, "final_url": final, "error": "foreign host"})
            continue
        ctype = hd.get("Content-Type", "")
        is_pdf = url.lower().endswith(".pdf")
        fn = dl / (key + (".pdf" if is_pdf else ".htm"))
        fn.write_bytes(body)
        it = {"id": key, "url": url, "final_url": final, "status": st, "content_type": ctype, "last_modified": hd.get("Last-Modified"),
              "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(), "saved": rel(fn)}
        if is_pdf:
            it["pdf_header"] = body[:8].decode("latin-1")
        elif st == 200:
            txt, enc = decode_html(body, ctype)
            p = TextOf(final)
            p.feed(txt)
            it["encoding"] = enc
            tm = re.search(r"<title>(.*?)</title>", txt, re.S)
            it["title"] = re.sub(r"\s+", " ", tm.group(1)).strip() if tm else None
            (out / f"{key}.txt").write_text(p.text() + "\n", encoding="utf-8")
            wjson(out / f"{key}.links.json", p.links)
        log["items"].append(it)
        print("ok", key, st, len(body), hd.get("Last-Modified"), flush=True)
    wjson(OUT / "nta_log.json", log)


# ---------------------------------------------------------------- PDF（AESV2・空のユーザーパスワードだけを扱う）
# 以下の PDF の復号と文字の取り出しは scripts/R2X_aoiro_verify.py（青色申告のトピックの独立検証者が書いたもの）の pdf モードを写した
# （import しない）。担当の scripts/R2B_fudosan_pdftext.py（scripts/R2X_aoiro_pdftext.py の写し）とは別の実装。
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


# ---------------------------------------------------------------- check（ネットワークなし）
DOCS = {
    "PS": ROOT / "docs" / "public-sources" / "20261109_round2b_fudosan-laws-and-nta.md",
    "M": ROOT / "docs" / "measurements" / "20261109_round2b_fudosan-fetch-and-checks.md",
    "H": ROOT / "docs" / "hypotheses" / "20261109_round2b_fudosan-calculation-model.md",
    "I": ROOT / "docs" / "inferences" / "20261109_round2b_fudosan-inferences.md",
}
RESULTS = []


def C(cid, doc, desc, ok, ev=None):
    RESULTS.append({"id": cid, "doc": doc, "desc": desc, "ok": bool(ok), "evidence": ev})
    print(("OK  " if ok else "NG  ") + cid + "  " + desc, flush=True)


def norm(s):
    return re.sub(r"[\s　]", "", s or "")


_EG = {}


def eg(short, asof):
    k = (short, asof)
    if k not in _EG:
        _EG[k] = rjson(OUT / "egov" / f"{short}_{asof}.json")
    return _EG[k]


def art_node(short, asof, art, *path):
    """条（本則）→ 項 → 号 の node。path は ("1",) や ("1", "2")。"""
    n = eg(short, asof)["main"].get(art)
    if n is None:
        return None
    for i, p in enumerate(path):
        n = n["ch"].get(p)
        if n is None:
            return None
    return n


def has(short, asof, art, path, *frags):
    """node の全文に、断片が順に現れるか（空白は無視）。"""
    n = art_node(short, asof, art, *path)
    if n is None:
        return False
    t, pos = norm(n["full"]), 0
    for f in frags:
        i = t.find(norm(f), pos)
        if i < 0:
            return False
        pos = i + len(norm(f))
    return True


KNUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def kanji_int(s):
    """「八十五」「八十九」「十」「五十八」のような漢数字（百未満）を整数に。担当の kanji_man とは別に書いた。"""
    if "十" in s:
        a, b = s.split("十", 1)
        return (KNUM.get(a, 1) if a else 1) * 10 + (KNUM.get(b, 0) if b else 0)
    return KNUM[s]


def nta_txt(key):
    return (OUT / "nta" / f"{key}.txt").read_text(encoding="utf-8")


def nta_has(key, *frags):
    t, pos = norm(nta_txt(key)), 0
    for f in frags:
        i = t.find(norm(f), pos)
        if i < 0:
            return False
        pos = i + len(norm(f))
    return True


def pdf_rows(name):
    rows = []
    for ln in (OUT / "pdf" / f"{name}.tsv").read_text(encoding="utf-8").splitlines():
        c = ln.split("\t")
        if len(c) >= 5:
            rows.append((int(c[0]), float(c[1]), float(c[2]), c[4]))
    return rows


def code_label(rows, page, code, xmax):
    """欄コードと同じ高さ（±6pt）で、コードより左（x < xmax）にある日本語の文字列をつなげる。"""
    cs = [(x, y) for p, x, y, t in rows if p == page and t == code]
    if not cs:
        return None
    x0, y0 = cs[0]
    near = sorted([(x, t) for p, x, y, t in rows if p == page and abs(y - y0) <= 6 and x < x0 and x < xmax
                   and re.search(r"[ぁ-んァ-ン一-龥]", t)])
    return "".join(norm(t) for _, t in near)


# 推測の計算（担当の R2B_fudosan_checks.py とは別に、一次情報の文言から書き直した）
def disallowed_41_4(loss, interest):
    """措令26の6①：一 利子 > 損失 → 損失の金額、二 利子 ≦ 損失 → 利子の額。loss は正の数（赤字の大きさ）。"""
    if loss <= 0 or interest <= 0:
        return 0
    return loss if interest > loss else interest


def tsusan_order(loss, keijo, joto_ichiji, sanrin_taishoku):
    """所令198 一・三・五（不動産所得・事業所得の損失）。各リストは (名前, 金額) の正の黒字。残りの純損失と、控除後の各所得を返す。"""
    rest, after = loss, {}
    for group in (keijo, joto_ichiji, sanrin_taishoku):
        for name, amt in group:
            d = min(rest, max(amt, 0))
            after[name] = amt - d
            rest -= d
    return rest, after


def aoiro_kojo(cap, parts):
    """措法25の2①二・②（③二・⑤）と TA2072（注）：合計は黒字だけ、順に控除。"""
    pos = [max(p, 0) for p in parts]
    total = min(cap, sum(pos))
    out, r = [], total
    for p in pos:
        d = min(p, r)
        out.append(d)
        r -= d
    return total, out


def mode_check():
    # 「## 訂正の記録」の節（検証者が足した、検証の記録への参照）は、文書の主張・参照の検査から外す
    ps, mdoc, hdoc, idoc = (DOCS[k].read_text(encoding="utf-8").split("\n## 訂正の記録", 1)[0] for k in ("PS", "M", "H", "I"))
    elog = rjson(OUT / "egov_log.json")

    # ============ A. 版（［PS］§0、［M］§2.1・§5）
    for short, lk in elog["lookups"].items():
        C(f"A-lawid-{short}", "PS§0", f"{lk['title']} の law_id は {lk['claimed']}", lk["claimed_ok"], lk["matches"])
    got = {(f["short"], f["asof"]): f["revision_info"] for f in elog["fetches"] if f.get("status") == 200}
    # ［PS］§0 の表の law_revision_id（本文から読み取る）
    rid_re = re.compile(r"\b(\d{3}(?:AC|CO)\d{10}_\d{8}_\d{3}(?:AC|CO)\d{10})\b")
    ps0 = ps.split("## 0. 出典の版", 1)[1].split("条文の全文", 1)[0]
    table = {"所法": "shotoku", "所令": "shotoku-rei", "措法": "sochi", "措令": "sochi-rei", "地方税法": "chiho"}
    cols = [R7, NOW, R8, R9]
    for line in ps0.splitlines():
        m = re.match(r"\|\s*(所法|所令|措法|措令|地方税法)\s*\|", line)
        if not m:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")][2:]
        short = table[m.group(1)]
        for asof, cell in zip(cols, cells):
            if cell == "—":
                continue
            g = got.get((short, asof), {}).get("law_revision_id")
            C(f"A-rid-PS-{short}-{asof}", "PS§0", f"{short} asof {asof} の版は {cell}", g == cell, {"got": g})
    mtab = mdoc.split("### 2.1 e-Gov 法令API v2", 1)[1].split("### 2.2", 1)[0]
    for line in mtab.splitlines():
        m = re.match(r"\|\s*(shotoku|shotoku-rei|sochi|sochi-rei|chiho)（", line)
        if not m:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")][1:]
        for asof, cell in zip(cols, cells):
            mm = rid_re.search(cell)
            if not mm:
                continue
            g = got.get((m.group(1), asof), {})
            st = re.search(r"（(\w+)）", cell)
            ok = g.get("law_revision_id") == mm.group(1) and (st is None or st.group(1) == g.get("current_revision_status"))
            C(f"A-rid-M-{m.group(1)}-{asof}", "M§2.1", f"{m.group(1)} asof {asof}：{cell}", ok,
              {"got": g.get("law_revision_id"), "status": g.get("current_revision_status")})
    for short, n in [("shotoku", 29), ("shotoku-rei", 16), ("sochi", 44), ("sochi-rei", 35)]:
        r = elog["revisions"][f"{short}_from_2025"]
        C(f"A-revs-{short}", "M§2.1", f"/law_revisions（amendment_date_from=2025-01-01）の件数 {n}", r["n"] == n,
          {"n": r["n"], "n_all": elog["revisions"][f"{short}_all"]["n"]})
    C("A-R8-unenforced", "PS§6", "令和8年分の版（asof 2026-12-31）は 2026-11-09 時点で UnEnforced（所法）",
      got[("shotoku", R8)]["current_revision_status"] == "UnEnforced", got[("shotoku", R8)])
    # 所令198 の版の特定（［M］§5、［PS］§4.2）
    exp198 = {R7: ("340CO0000000096_20251201_507CO0000000120", "及び"), "2026-03-31": ("340CO0000000096_20260101_507CO0000000120", "及び"),
              "2026-04-01": ("340CO0000000096_20260401_508CO0000000093", "又は"), NOW: ("340CO0000000096_20260522_508CO0000000093", "又は"),
              R8: ("340CO0000000096_20261201_508CO0000000093", "又は"), R9: ("340CO0000000096_20270101_508CO0000000093", "又は"),
              "2028-01-01": ("340CO0000000096_20280101_508CO0000000093", "又は")}
    for asof, (rid, word) in exp198.items():
        i3 = norm(art_node("shotoku-rei", asof, "198", "1", "3")["full"])
        i6 = norm(art_node("shotoku-rei", asof, "198", "1", "6")["full"])
        ok = got[("shotoku-rei", asof)]["law_revision_id"] == rid and f"譲渡所得の金額{word}一時所得の金額" in i3 and f"譲渡所得の金額{word}一時所得の金額" in i6
        C(f"A-198-{asof}", "M§5/PS§4.2", f"所令198 三号・六号の文言 asof {asof}：「{word}」、版 {rid}", ok,
          {"got": got[("shotoku-rei", asof)]["law_revision_id"]})
    C("A-198-2028-item3", "M§5/PS§4.2", "2028-01-01 の版の所令198三号に「法第三十三条第三項第一号又は第三号」",
      has("shotoku-rei", "2028-01-01", "198", ("1", "3"), "法第三十三条第三項第一号又は第三号"), None)
    C("A-178-2028", "M§5", "2028-01-01 の版の所令178②に「法第三十三条第三項第三号」が入る（2026-11-09 の版にはない）",
      has("shotoku-rei", "2028-01-01", "178", ("2",), "法第三十三条第三項第三号") and not has("shotoku-rei", NOW, "178", ("2",), "法第三十三条第三項第三号"), None)
    sup = eg("shotoku-rei", NOW)["suppl"]
    k93 = [k for k in sup if "政令第九三号" in k]
    a1 = norm(sup[k93[0]][0]["arts"]["1"]["full"]) if k93 else ""
    C("A-R8-93-art1", "PS§4.2/M§5", "令和8年政令第93号 附則第1条本文「この政令は、令和八年四月一日から施行する。」", "この政令は、令和八年四月一日から施行する。" in a1, k93)
    C("A-R8-93-item5", "PS§4.2/M§5", "同条第5号：「第百九十八条第三号の改正規定（「及び」を「又は」に改める部分を除く。）」は第3号の施行日の属する年の翌年の1月1日",
      re.search(r"五.*第百九十八条第三号の改正規定（「及び」を「又は」に改める部分を除く。）.*第三号に掲げる規定の施行の日の属する年の翌年の一月一日", a1) is not None, None)

    # ============ B. 条文の引用（［PS］§1〜§6、［M］§3 C2）
    Q = [  # (id, 法令, [asof], 条, path, 断片...)
        ("26-1", "shotoku", [R7, R8, R9], "26", ("1",), "不動産所得とは、不動産、不動産の上に存する権利、船舶又は航空機（以下この項において「不動産等」という。）の貸付け（地上権又は永小作権の設定その他他人に不動産等を使用させることを含む。）による所得（事業所得又は譲渡所得に該当するものを除く。）をいう。"),
        ("26-2", "shotoku", [R7, R8], "26", ("2",), "不動産所得の金額は、その年中の不動産所得に係る総収入金額から必要経費を控除した金額とする。"),
        ("33-1", "shotoku", [R7, R8], "33", ("1",), "資産の譲渡（建物又は構築物の所有を目的とする地上権又は賃借権の設定その他契約により他人に土地を長期間使用させる行為で政令で定めるものを含む。", "による所得"),
        ("33-3-1", "shotoku", [R7, R8], "33", ("3", "1"), "その資産の取得の日以後五年以内にされたもの"),
        ("37-1", "shotoku", [R7, R8], "37", ("1",), "その年分の不動産所得の金額、事業所得の金額又は雑所得の金額"),
        ("rei79-1", "shotoku-rei", [R7, R8], "79", ("1",), "その対価として支払を受ける金額が次の各号に掲げる場合の区分に応じ当該各号に定める金額の十分の五に相当する金額を超えるもの"),
        ("rei79-1-1", "shotoku-rei", [R7, R8], "79", ("1", "1"), "全部の所有を目的とする", "地下若しくは空間について上下の範囲を定めた", "二分の一"),
        ("rei79-1-2", "shotoku-rei", [R7, R8], "79", ("1", "2"), "一部の所有を目的とする", "床面積"),
        ("rei79-1-3", "shotoku-rei", [R7, R8], "79", ("1", "3"), "大深度地下"),
        ("rei79-3", "shotoku-rei", [R7, R8], "79", ("3",), "借地権又は地役権の設定の対価として支払を受ける金額が当該設定により支払を受ける地代の年額の二十倍に相当する金額以下である場合には、当該設定は、同項の行為に該当しないものと推定する。"),
        ("rei80", "shotoku-rei", [R7, R8], "80", ("2",), "通常の利率", "の十分の五に相当する利率による複利の方法で計算した現在価値"),
        ("51-1", "shotoku", [R7, R8], "51", ("1",), "不動産所得、事業所得又は山林所得を生ずべき事業の用に供される固定資産"),
        ("51-2", "shotoku", [R7, R8], "51", ("2",), "不動産所得、事業所得又は山林所得を生ずべき事業について、その事業の遂行上生じた売掛金、貸付金、前渡金その他これらに準ずる債権の貸倒れ"),
        ("51-4", "shotoku", [R7, R8], "51", ("4",), "不動産所得若しくは雑所得を生ずべき業務の用に供され", "その者のその損失の生じた日の属する年分の不動産所得の金額又は雑所得の金額（この項の規定を適用しないで計算したこれらの所得の金額とする。）を限度として"),
        ("64-1", "shotoku", [R7, R8], "64", ("1",), "事業所得の金額を除く", "不動産所得又は山林所得を生ずべき事業から生じたものを除く", "なかつたものとみなす"),
        ("152", "shotoku", [R7, R8], "152", ("1",), "第六十四条", "当該事実が生じた日の翌日から二月以内に限り"),
        ("rei180-2-1", "shotoku-rei", [R7, R8], "180", ("2", "1"), "回収不能額等が生じた時の直前において確定している法第六十四条第一項に規定する年分の総所得金額、退職所得金額及び山林所得金額の合計額"),
        ("rei180-2-2", "shotoku-rei", [R7, R8], "180", ("2", "2"), "前号に掲げる金額の計算の基礎とされる各種所得の金額のうち当該回収不能額等に係るものから、当該回収不能額等に相当する収入金額又は総収入金額がなかつたものとした場合に計算される当該各種所得の金額を控除した残額"),
        ("57-1", "shotoku", [R7, R8], "57", ("1",), "年齢十五歳未満である者を除く", "前条に規定する事業に従事するもの", "前条の規定にかかわらず"),
        ("57-3-1", "shotoku", [R7, R8], "57", ("3", "1"), "配偶者である事業専従者", "八十六万円", "五十万円"),
        ("57-3-2", "shotoku", [R7, R8], "57", ("3", "2"), "その年分の当該事業に係る不動産所得の金額、事業所得の金額又は山林所得の金額（この項の規定を適用しないで計算した場合の金額とする。）を当該事業に係る事業専従者の数に一を加えた数で除して計算した金額"),
        ("57-4", "shotoku", [R7, R8], "57", ("4",), "給与所得に係る収入金額とみなす"),
        ("63", "shotoku", [R7, R8], "63", ("1",), "不動産所得、事業所得又は山林所得を生ずべき事業を廃止した後において", "その廃止した日の属する年分", "又はその前年分"),
        ("rei179", "shotoku-rei", [R7, R8], "179", ("1",), "法第六十三条"),
        ("69-1", "shotoku", [R7, R8], "69", ("1",), "総所得金額、退職所得金額又は山林所得金額を計算する場合において、不動産所得の金額、事業所得の金額、山林所得の金額又は譲渡所得の金額の計算上生じた損失の金額があるときは、政令で定める順序により、これを他の各種所得の金額から控除する。"),
        ("69-2", "shotoku", [R7, R8], "69", ("2",), "第六十二条第一項（生活に通常必要でない資産の災害による損失）に規定する資産に係る所得の金額", "当該損失の金額のうち政令で定めるものは", "他の生活に通常必要でない資産に係る所得の金額から控除するものとし、当該政令で定めるもの以外のもの及び当該控除をしてもなお控除しきれないものは生じなかつたものとみなす。"),
        ("rei178-1-2", "shotoku-rei", [R7, R8], "178", ("1", "2"), "通常自己及び自己と生計を一にする親族が居住の用に供しない家屋で主として趣味、娯楽又は保養の用に供する目的で所有するものその他主として趣味、娯楽、保養又は鑑賞の目的で所有する資産"),
        ("rei200", "shotoku-rei", [R7, R8], "200", ("1",), "競走馬の譲渡に係る譲渡所得の金額の計算上生じた損失の金額"),
        ("rei198-1", "shotoku-rei", [R7, R8], "198", ("1", "1"), "不動産所得の金額又は事業所得の金額の計算上生じた損失の金額があるときは、これをまず他の利子所得の金額、配当所得の金額、不動産所得の金額、事業所得の金額、給与所得の金額及び雑所得の金額（以下この条において「経常所得の金額」という。）から控除する。"),
        ("rei198-2", "shotoku-rei", [R7, R8], "198", ("1", "2"), "譲渡所得の金額の計算上生じた損失の金額があるときは、これをまず一時所得の金額から控除する。"),
        ("rei198-3", "shotoku-rei", [R7, R8], "198", ("1", "3"), "一時所得の金額", "順次控除する", "法第三十三条第三項第一号", "からまず控除する"),
        ("rei198-4", "shotoku-rei", [R7, R8], "198", ("1", "4"), "第二号の場合において", "経常所得の金額"),
        ("rei198-5", "shotoku-rei", [R7, R8], "198", ("1", "5"), "まず山林所得の金額から控除し", "退職所得の金額から控除する"),
        ("rei198-6", "shotoku-rei", [R7, R8], "198", ("1", "6"), "山林所得の金額の計算上生じた損失の金額があるときは"),
        ("41_4-1", "sochi", [R7, R8, R9], "41_4", ("1",), "個人の平成四年分以後の各年分の不動産所得の金額の計算上生じた損失の金額がある場合において、当該年分の不動産所得の金額の計算上必要経費に算入した金額のうちに不動産所得を生ずべき業務の用に供する土地又は土地の上に存する権利（次項において「土地等」という。）を取得するために要した負債の利子の額があるときは、当該損失の金額のうち当該負債の利子の額に相当する部分の金額として政令で定めるところにより計算した金額は、所得税法第六十九条第一項の規定その他の所得税に関する法令の規定の適用については、生じなかつたものとみなす。"),
        ("41_4-2", "sochi", [R7, R8], "41_4", ("2",), "建物とともにその敷地の用に供されている土地等を取得した場合における土地等を取得するために要した負債の額の計算", "政令で定める"),
        ("rei26_6-1-1", "sochi-rei", [R7, R8], "26_6", ("1", "1"), "負債の利子の額が当該不動産所得の金額の計算上生じた損失の金額を超える場合", "当該損失の金額"),
        ("rei26_6-1-2", "sochi-rei", [R7, R8], "26_6", ("1", "2"), "負債の利子の額が当該不動産所得の金額の計算上生じた損失の金額以下である場合", "当該損失の金額のうち当該負債の利子の額に相当する金額"),
        ("rei26_6-2", "sochi-rei", [R7, R8], "26_6", ("2",), "（これらの資産を一の契約により同一の者から譲り受けた場合に限る。）", "区分することが困難であるときは", "当該個人は、これらの資産を取得するために要した負債の額がまず当該建物の取得の対価の額に充てられ、次に当該土地等の取得の対価の額に充てられたものとして", "計算することができる。"),
        ("41_4_2-1", "sochi", [R7, R8], "41_4_2", ("1",), "平成十八年以後の各年において、組合事業又は信託から生ずる不動産所得を有する場合", "同法第二十六条第二項及び第六十九条第一項の規定その他の所得税に関する法令の規定の適用については、生じなかつたものとみなす。"),
        ("rei26_6_2-4", "sochi-rei", [R7, R8], "26_6_2", ("4",), "総収入金額に算入すべき金額の合計額が", "必要経費に算入すべき金額の合計額に満たない場合におけるその満たない部分の金額"),
        ("rei26_6_2-6", "sochi-rei", [R7, R8], "26_6_2", ("6",), "明細書を当該申告書に添付しなければならない"),
        ("41_4_3-1", "sochi", [R7, R8], "41_4_3", ("1",), "個人が、令和三年以後の各年において、国外中古建物から生ずる不動産所得を有する場合においてその年分の不動産所得の金額の計算上国外不動産所得の損失の金額があるときは、当該国外不動産所得の損失の金額に相当する金額は、所得税法第二十六条第二項及び第六十九条第一項の規定その他の所得税に関する法令の規定の適用については、生じなかつたものとみなす。"),
        ("41_4_3-2-1", "sochi", [R7, R8], "41_4_3", ("2", "1"), "国外にある建物", "耐用年数を財務省令で定めるところにより算定しているものに限る"),
        ("41_4_3-3", "sochi", [R7, R8], "41_4_3", ("3",), "取得費"),
        ("rei26_6_3-1", "sochi-rei", [R7, R8], "26_6_3", ("1",), "国外中古建物", "ごとの償却費の額のうち次の各号に掲げる場合の区分に応じ当該各号に定める金額の合計額"),
        ("25_2-1", "sochi", [R7, R8], "25_2", ("1",), "不動産所得の金額、事業所得の金額又は山林所得の金額は、所得税法第二十六条第二項、第二十七条第二項又は第三十二条第三項の規定により計算した不動産所得の金額、事業所得の金額又は山林所得の金額から次に掲げる金額のうちいずれか低い金額を控除した金額とする。", "十万円", "合計額"),
        ("25_2-2", "sochi", [R7, R8], "25_2", ("2",), "不動産所得の金額、事業所得の金額又は山林所得の金額から順次控除する"),
        ("25_2-3", "sochi", [R7, R8], "25_2", ("3",), "青色申告書を提出することにつき税務署長の承認を受けている個人で不動産所得又は事業所得を生ずべき事業を営むもの（所得税法第六十七条第一項の規定の適用を受ける者を除く。）", "五十五万円", "不動産所得の金額又は事業所得の金額の合計額"),
        ("25_2-4", "sochi", [R7, R8], "25_2", ("4",), "「五十五万円」とあるのは、「六十五万円」"),
        ("25_2-R9-2", "sochi", [R9], "25_2", ("2",), "前項の規定は", "不動産所得又は事業所得を生ずべき事業を営むもの", "第四項に規定する場合に該当しない場合には、適用しない。", "その年の前々年分の不動産所得に係る総収入金額が千万円を超えること", "その年の前々年分の事業所得に係る総収入金額が千万円を超えること"),
        ("25_2-R9-4", "sochi", [R9], "25_2", ("4",), "不動産所得又は事業所得を生ずべき事業を営むもの", "六十五万円"),
        ("25_2-R9-5", "sochi", [R9], "25_2", ("5",), "前項に規定する個人", "「六十五万円」とあるのは、「七十五万円」"),
        ("143", "shotoku", [R7, R8], "143", ("1",), "不動産所得、事業所得又は山林所得を生ずべき業務を行なう居住者"),
        ("70-1", "shotoku", [R7, R8], "70", ("1",), "前年以前三年内の各年（その年分の所得税につき青色申告書を提出している年に限る。）"),
        ("70-2", "shotoku", [R7, R8], "70", ("2",), "変動所得の金額の計算上生じた損失の金額", "被災事業用資産の損失の金額"),
        ("2-30-i2", "shotoku", [R7, NOW, R8, R9], "2", ("1", "30"), "第七十条（純損失の繰越控除）及び第七十一条（雑損失の繰越控除）の規定を適用しないで計算した場合における第二十二条（課税標準）に規定する総所得金額、退職所得金額及び山林所得金額の合計額（以下この条において「合計所得金額」という。）"),
        ("2-32-kyuyo", "shotoku", [R7, NOW, R8, R9], "2", ("1", "32"), "自己の勤労に基づいて得た事業所得、給与所得、退職所得又は雑所得（以下この号において「給与所得等」という。）"),
        ("2-33-senju", "shotoku", [R7, R8], "2", ("1", "33"), "第五十七条第一項", "青色事業専従者に該当するもので同項に規定する給与の支払を受けるもの及び同条第三項に規定する事業専従者に該当するもの"),
        ("2-34-senju", "shotoku", [R7, R8], "2", ("1", "34"), "青色事業専従者に該当するもので同項に規定する給与の支払を受けるもの及び同条第三項に規定する事業専従者に該当するもの", "を除く。）"),
        ("2-34-term-R8", "shotoku", [NOW, R8], "2", ("1", "34"), "「青色事業専従者等」という。）を除く。）"),
        ("56", "shotoku", [R7, NOW, R8, R9], "56", ("1",), "居住者と生計を一にする配偶者その他の親族がその居住者の営む不動産所得、事業所得又は山林所得を生ずべき事業に従事したことその他の事由により当該事業から対価の支払を受ける場合には、その対価に相当する金額は、その居住者の当該事業に係る不動産所得の金額、事業所得の金額又は山林所得の金額の計算上、必要経費に算入しないものとし、かつ、その親族のその対価に係る各種所得の金額の計算上必要経費に算入されるべき金額は、その居住者の当該事業に係る不動産所得の金額、事業所得の金額又は山林所得の金額の計算上、必要経費に算入する。この場合において、その親族が支払を受けた対価の額及びその親族のその対価に係る各種所得の金額の計算上必要経費に算入されるべき金額は、当該各種所得の金額の計算上ないものとみなす。"),
        ("chiho313-2", "chiho", [R7, R8, R9], "313", ("2",), "前項の総所得金額、退職所得金額又は山林所得金額は、この法律又はこれに基づく政令で特別の定めをする場合を除くほか、それぞれ所得税法その他の所得税に関する法令の規定による所得税法第二十二条第二項又は第三項の総所得金額、退職所得金額又は山林所得金額の計算の例により算定するものとする。ただし、同法第六十条の二から第六十条の四までの規定の例によらないものとする。"),
        ("chiho313-3", "chiho", [R7, R8], "313", ("3",), "生計を一にする配偶者その他の親族", "専ら当該納税義務者の営む同法第五十六条に規定する事業に従事するもの", "同条第一項の規定による計算の例により"),
        ("chiho313-4", "chiho", [R7, R8], "313", ("4",), "八十六万円", "五十万円", "事業専従者の数に一を加えた数で除して得た金額"),
        ("chiho313-5", "chiho", [R7, R8], "313", ("5",), "事業専従者の給与所得に係る収入金額とみなす"),
    ]
    for qid, short, asofs, art, path, *frags in Q:
        res = {a: has(short, a, art, path, *frags) for a in asofs}
        C(f"B-{qid}", "PS", f"{short} {art} {'-'.join(path)} の文言（{', '.join(asofs)}）", all(res.values()), res)
    C("B-25_2-R9-no55", "PS§3.4/H4", "措法25の2（2027-01-01）の本文に「五十五万円」がない（65万円・75万円はある）",
      "五十五万円" not in art_node("sochi", R9, "25_2")["full"] and "六十五万円" in art_node("sochi", R9, "25_2")["full"]
      and "七十五万円" in art_node("sochi", R9, "25_2")["full"], None)
    C("B-56-no-gyomu", "PS§5.1/M C2-56", "所法56 の本文に「業務」の語がない（4つの版）",
      all("業務" not in art_node("shotoku", a, "56")["full"] for a in [R7, NOW, R8, R9]), None)
    C("B-67-caption", "PS§9-7", "現行の所法67 の見出しは「小規模事業者等の収入及び費用の帰属時期」、67の2 は「リース取引に係る所得の金額の計算」（参考）",
      art_node("shotoku", NOW, "67")["caption"] == "（小規模事業者等の収入及び費用の帰属時期）"
      and art_node("shotoku", NOW, "67_2")["caption"] == "（リース取引に係る所得の金額の計算）",
      {"67": art_node("shotoku", NOW, "67")["caption"], "67_2": art_node("shotoku", NOW, "67_2")["caption"]})
    C("B-no-hasu", "PS§9-3", "所法57・措令26の6 の本文に「端数」の語がない（R7・R8）。措通41の4−3 の本文にも「端数」がない",
      all("端数" not in art_node(s, a, n)["full"] for s, n in (("shotoku", "57"), ("sochi-rei", "26_6")) for a in (R7, R8))
      and "端数" not in nta_txt("sochitsu_41_4").split("41の4－3", 1)[1].split("41の4－4", 1)[0], None)
    for asof in [R7, R8, R9]:
        d = eg("chiho", asof)
        C(f"B-chiho-no41_4-{asof}", "PS§4.5/M C2", f"地方税法（{asof}）の全文に「第四十一条の四」がない", len(d["grep_41_4"]) == 0, len(d["grep_41_4"]))

    # 基準額（［PS］§6、［M］C3）
    for asof, ek, ef, es in [(R7, 85, 58, 58), (NOW, 85, 58, 58), (R8, 89, 62, 62), (R9, 89, 62, 62)]:
        t32 = norm(art_node("shotoku", asof, "2", "1", "32")["full"])
        t34 = norm(art_node("shotoku", asof, "2", "1", "34")["full"])
        t33 = norm(art_node("shotoku", asof, "2", "1", "33")["full"])
        m32 = re.search(r"合計所得金額が(\S+?)万円以下であり、かつ、合計所得金額のうち給与所得等以外の所得に係る部分の金額が(\S+?)万円以下", t32)
        m34 = re.search(r"合計所得金額が(\S+?)万円以下である者", t34)
        m33 = re.search(r"合計所得金額が(\S+?)万円以下である者", t33)
        v = (kanji_int(m32.group(1)), kanji_int(m32.group(2)), kanji_int(m34.group(1)), kanji_int(m33.group(1)))
        C(f"C3-{asof}", "PS§6/M C3", f"所法2①三十二・三十四（{asof}）：勤労学生 {ek}万円・10万円、扶養親族 {ef}万円", v[:3] == (ek, 10, ef), {"got": v, "同一生計配偶者": v[3]})

    # 版の間で同じか（［PS］§0、［M］C1）
    same = {"shotoku": (["26", "33", "36", "37", "51", "56", "57", "63", "64", "69", "70", "143", "152"], [R7, NOW, R8, R9]),
            "shotoku-rei": (["79", "80", "178", "179", "180", "200"], [R7, NOW, R8, R9]),
            "sochi": (["41_4", "41_4_2", "41_4_3"], [R7, NOW, R8, R9]),
            "sochi-rei": (["26_6", "26_6_2", "26_6_3"], [R7, NOW, R8])}
    for short, (arts, asofs) in same.items():
        for a in arts:
            ts = {x: art_node(short, x, a)["full"] for x in asofs}
            C(f"C1-{short}-{a}", "PS§0/M C1", f"{short} {a} は {asofs[0]}〜{asofs[-1]} で同文", len(set(ts.values())) == 1, None)
    c313 = {x: [art_node("chiho", x, "313", str(i))["full"] for i in range(1, 12)] for x in [R7, R8, R9]}
    C("C1-chiho-313-1-11", "PS§0/M C1", "地方税法313 ①〜⑪ は 2025-12-31・2026-12-31・2027-01-01 で同文", c313[R7] == c313[R8] == c313[R9], None)
    c313_12 = {x: art_node("chiho", x, "313", "12")["full"] for x in [R7, R8, R9]}
    C("C1-chiho-313-12", "M C1", "地方税法313⑫ は版の間で変わる（担当の「第12項の特定配当等の文言だけが変わる」の前半）",
      len(set(c313_12.values())) > 1 and "特定配当等" in c313_12[R7], {"n_distinct": len(set(c313_12.values()))})
    c313_rest = {x: [art_node("chiho", x, "313", str(i))["full"] for i in range(13, 17) if art_node("chiho", x, "313", str(i))] for x in [R7, R8, R9]}
    C("C1-chiho-313-13-16", "M C1", "地方税法313 ⑬以降は版の間で同文（「第12項…だけが変わる」の後半）", c313_rest[R7] == c313_rest[R8] == c313_rest[R9], None)
    s25 = {x: art_node("sochi", x, "25_2")["full"] for x in [R7, NOW, R8, R9]}
    C("C1-25_2", "PS§3.4/M C1", "措法25の2 は 2025-12-31・2026-11-09・2026-12-31 で同文、2027-01-01 で変わる",
      s25[R7] == s25[NOW] == s25[R8] and s25[R8] != s25[R9], None)
    r198 = {x: art_node("shotoku-rei", x, "198")["full"] for x in [R7, NOW, R8, R9]}
    C("C1-198", "PS§4.2/M C1", "所令198：2025-12-31 と 2026-11-09 以後の差は「及び」→「又は」だけ（2026-11-09〜2027-01-01 は同文）",
      r198[R7].replace("譲渡所得の金額及び一時所得の金額", "譲渡所得の金額又は一時所得の金額") == r198[NOW] == r198[R8] == r198[R9] and r198[R7] != r198[NOW], None)
    s2 = {x: art_node("shotoku", x, "2")["full"] for x in [R7, R8]}
    C("C1-2", "PS§0", "所法2 は 2025-12-31 と 2026-12-31 で変わる", s2[R7] != s2[R8], None)

    # ============ D. 国税庁（［PS］§0〜§5、［M］§2.2・C6）
    nlog = rjson(OUT / "nta_log.json")
    mine = {i["id"]: i for i in nlog["items"]}
    rob = rjson(OUT / "nta_robots.json")
    C("D-robots", "M§2.2", "robots.txt の SHA-256 が a5f4e421…d8528 で、対象の URL はすべて許可",
      rob["sha256"] == "a5f4e421e5bb2b20563fa568d7ee4d7c6a41afa72ef8bb96cd35510ebe6d8528" and all(rob["allowed"].values()), rob["sha256"])
    idmap = {"shushi_fudosan_r07（PDF）": "pdf_shushi_r07", "shushi_fudosan_kakikata_r07（PDF）": "pdf_shushi_kakikata_r07",
             "kessan_fudosan_r07（PDF）": "pdf_kessan_r07", "kessan_fudosan_kakikata_r07（PDF）": "pdf_kessan_kakikata_r07"}
    m22 = mdoc.split("### 2.2 国税庁", 1)[1].split("## 3.", 1)[0]
    for line in m22.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 6 or not re.fullmatch(r"[0-9a-f]{64}", cells[-1]):
            continue
        rid = idmap.get(cells[1], cells[1])
        it = mine.get(rid)
        if it is None:
            C(f"D-hash-{rid}", "M§2.2", f"{rid}：検証側で取得していない", False, None)
            continue
        ok = it["sha256"] == cells[-1] and it.get("last_modified") == cells[3] and str(it["bytes"]) == cells[4]
        C(f"D-hash-{rid}", "M§2.2", f"{rid}：Last-Modified・バイト数・SHA-256 が［M］§2.2 と同じ", ok,
          {"lm": it.get("last_modified"), "bytes": it["bytes"], "sha256": it["sha256"][:16]})
    C("D-r08-404", "PS§8.3/M§2.2", "令和8年分の様式一覧（r08.htm）は /error/404.htm に転送され、題名「指定されたページを表示できませんでした」",
      mine["yoshiki_r08"]["final_url"].endswith("/error/404.htm") and mine["yoshiki_r08"].get("title") == "指定されたページを表示できませんでした", mine["yoshiki_r08"].get("final_url"))
    for k in ["ta_1370", "ta_1373", "ta_1376", "ta_1391", "ta_1399", "ta_2072", "ta_2075", "ta_2210", "ta_2250"]:
        C(f"D-asof-{k}", "PS§0", f"{k} は [令和8年4月1日現在法令等]", nta_has(k, "[令和8年4月1日現在法令等]"), None)
    for k in ["shitsugi_02_27", "shitsugi_04_14"]:
        C(f"D-asof-{k}", "PS§0", f"{k} は「令和7年8月1日現在の法令・通達等」", nta_has(k, "令和7年8月1日現在の法令・通達等に基づいて作成しています。"), None)
    links = json.loads((OUT / "nta" / "yoshiki_r07.links.json").read_text(encoding="utf-8"))
    for url, title in [("r07/09.pdf", "収支内訳書（不動産所得用）【令和２年分以降用】"), ("2025/pdf/019.pdf", "令和７年分収支内訳書（不動産所得用）の書き方"),
                       ("r07/12.pdf", "所得税青色申告決算書（不動産所得用）【令和２年分以降用】"), ("2025/pdf/039.pdf", "令和７年分青色申告決算書（不動産所得用）の書き方")]:
        C(f"D-link-{url}", "PS§0", f"令和7年分の様式一覧に「{title}」→ {url}", any(l["href"].endswith(url) and title in l["text"] for l in links), None)
    NQ = [
        ("26-1", "kihon_04_02", "26－1", "総トン数20トン未満の船舶及び端舟その他ろかいのみで運転し、又は主としてろかいで運転する舟の貸付けによる所得は、事業所得又は雑所得に該当する。"),
        ("26-2", "kihon_04_02", "26－2　いわゆるケース貸しは、不動産の貸付けに該当する。"),
        ("26-3", "kihon_04_02", "26－3", "裸用船契約に係る所得は、法第26条第1項に規定する船舶の貸付けによる所得に該当し", "定期用船契約又は航海用船契約に係る所得は、事業所得又は雑所得に該当する。", "航空機の貸付けに係る所得についても、これに準ずる。"),
        ("26-4", "kihon_04_02", "26－4", "アパート、貸間等のように食事を供さない場合の所得は、不動産所得とする。", "下宿等のように食事を供する場合の所得は、事業所得又は雑所得とする。"),
        ("26-5", "kihon_04_02", "26－5", "広告等のため、土地、家屋の屋上又は側面、塀等を使用させる場合の所得は、不動産所得に該当する。"),
        ("26-6", "kihon_04_02", "26－6", "その実質が契約の更改に係るものであり、かつ、令第79条《資産の譲渡とみなされる行為》の規定の適用があるものを除き、不動産所得に該当する。"),
        ("26-7", "kihon_04_02", "26－7", "不動産業者が販売の目的で取得した土地、建物等の不動産を一時的に貸し付けた場合における当該貸付けによる所得は、不動産業から生ずる事業所得に該当する。"),
        ("26-8", "kihon_04_02", "26－8", "使用人に寄宿舎等を利用させることにより受ける使用料に係る所得は、当該事業から生ずる所得に該当する。"),
        ("26-9", "kihon_04_02", "26－9　建物の貸付けが不動産所得を生ずべき事業として行われているかどうかは、社会通念上事業と称するに至る程度の規模で建物の貸付けを行っているかどうかにより判定すべきであるが、次に掲げる事実のいずれか一に該当する場合又は賃貸料の収入の状況、貸付資産の管理の状況等からみてこれらの場合に準ずる事情があると認められる場合には、特に反証がない限り、事業として行われているものとする。", "（1） 貸間、アパート等については、貸与することができる独立した室数がおおむね10以上であること。", "（2） 独立家屋の貸付けについては、おおむね5棟以上であること。"),
        ("27-2", "kihon_04_02", "27－2", "自己の責任において他人の物を保管する場合の所得は事業所得又は雑所得に該当し、そうでない場合の所得は不動産所得に該当する。"),
        ("27-3", "kihon_04_02", "27－3", "バンガロー等", "簡易な施設の貸付けによる所得は、事業所得又は雑所得に該当する。"),
        ("36-5", "kihon_05_01", "36－5", "契約又は慣習により支払日が定められているものについてはその支払日、支払日が定められていないものについてはその支払を受けた日（請求があったときに支払うべきものとされているものについては、その請求の日）", "判決、和解等のあった日", "計算の基礎とされた期間が3年以上である場合には、当該賃貸料相当額に係る所得は、臨時所得に該当する"),
        ("36-6", "kihon_05_01", "36－6", "資産の引渡しを要するものについては当該引渡しのあった日、引渡しを要しないものについては当該貸付けに係る契約の効力発生の日", "ただし、引渡しを要するものについて契約の効力発生の日により総収入金額に算入して申告があったときは、これを認める。"),
        ("36-7", "kihon_05_01", "36－7", "貸付期間の経過に関係なく返還を要しないこととなっている部分の金額", "36－6に定める日", "貸付期間の経過に応じて返還を要しないこととなる部分の金額", "契約に定められたところにより当該返還を要しないこととなった日", "貸付期間が終了しなければ返還を要しないことが確定しない部分の金額", "当該不動産等の貸付けが終了した日"),
        ("51-5", "kihon_09_01", "51－5", "当該事業を営む者が当該資産を所有しているものとみなして法第51条第1項の規定を適用することができるものとする。ただし、自己又は自己と生計を一にする配偶者その他の親族が法第72条第1項《雑損控除》の規定の適用を受ける場合は、この限りでない。"),
        ("51-1..9", "kihon_09_01", "51－1", "51－9"),
        ("51-10", "kihon_09_02", "51-10", "不動産貸付業者の未収賃貸料"),
        ("56-1", "kihon_11_01", "56－1　不動産所得、事業所得又は山林所得を生ずべき事業を営む居住者と生計を一にする配偶者その他の親族がその有する資産を無償で当該事業の用に供している場合には、その対価の授受があったものとしたならば法第56条の規定により当該居住者の営む当該事業に係る所得の金額の計算上必要経費に算入されることとなる金額を当該居住者の営む当該事業に係る所得の金額の計算上必要経費に算入するものとする。"),
        ("57-2,3", "kihon_11_01", "57－2", "57－3"),
        ("63/64", "kihon_13_01", "63-1", "64-1"),
        ("s41_4-1", "sochitsu_41_4", "41の4－1", "併用する建物", "業務の遂行のために必要な部分の額を基として同項の規定を適用する"),
        ("s41_4-2", "sochitsu_41_4", "41の4－2", "構築物の取得の対価の額を当該建物の取得の対価の額に含めて差し支えない"),
        ("s41_4-3", "sochitsu_41_4", "41の4－3", "建物及び土地等を取得するために要した負債の利子の額にこれらの資産を取得するために要した負債の額のうちに同項の規定により当該土地等の取得の対価の額に充てられたものとされる負債の額の割合を乗じて計算した額"),
        ("s41_4-4", "sochitsu_41_4", "41の4－4", "措置法第27条の2又は第41条の4の2の適用がある場合"),
        ("731106-head", "kobetsu_731106", "直所 2－78", "昭和48年11月6日", "不動産等の賃貸料にかかる不動産所得の収入金額 の計上時期について"),
        ("731106-1", "kobetsu_731106", "その者が不動産等の貸付けを事業的規模で行なっている場合で、次のいずれにも該当するときは、同法第67条の2《小規模事業者の収入及び費用の帰属時期》の規定の適用を受ける場合を除き",
         "帳簿書類を備えて継続的に記帳し", "前受収益および未収収益の経理", "1年をこえる期間にかかる賃貸料収入については、その前受収益または未収収益についての明細書を確定申告書に添付していること", "頭金、権利金、名義書替料、更新料、礼金等は含まれない"),
        ("731106-2", "kobetsu_731106", "事業的規模で行なっていない場合であつても", "1年以内の期間にかかる不動産等の賃貸料の収入金額の全部について上記1の(2)に該当するときは"),
        ("731106-3", "kobetsu_731106", "計上時期の変更のあつた年分の総収入金額の計算", "前月払の月額賃貸料の場合には、新たに上記1または2の取扱いによることとした年分は、11か月分の賃貸料を総収入金額に算入する"),
        ("TA1370", "ta_1370", "（1） 土地や建物などの不動産の貸付け", "（2） 借地権など不動産の上に存する権利の設定および貸付け", "（3） 船舶や航空機の貸付け",
         "イ 名義書換料、承諾料、更新料または頭金などの名目で受領するもの", "ロ 敷金や保証金などのうち、返還を要しないもの", "ハ 共益費などの名目で受け取る電気代、水道代や掃除代など",
         "不動産収入を得るために直接必要な費用のうち家事上の経費と明確に区分できるもの", "イ 固定資産税", "ロ 損害保険料", "ハ 減価償却費", "ニ 修繕費", "所法26、36、37、49"),
        ("TA1373", "ta_1373", "原則として社会通念上事業と称するに至る程度の規模で行われているかどうかによって、実質的に判断します。", "おおむね10室以上", "おおむね5棟以上",
         "その年分の資産損失を差し引く前の不動産所得の金額を限度として", "収入に計上した年分までさかのぼって", "それ以外の場合には適用がありません。", "（4） 令和8年分までの青色申告特別控除については", "最高55万円", "65万円", "最高10万円",
         "所法26、51、57、64、措法25の2、所基通26-9"),
        ("TA1376-qa", "ta_1376", "Q 未分割遺産から生じる不動産所得"),
        ("TA1391", "ta_1391", "1　別荘等のように主として趣味、娯楽、保養または鑑賞の目的で所有する不動産の貸付けに係るもの", "2 不動産所得の金額の計算上必要経費に算入した土地等を取得するために要した負債の利子に相当する部分の金額"),
        ("TA1399", "ta_1399", "事業的規模の不動産貸付けを開始したときは、開業の日の属する年分の確定申告期限までに「個人事業の開業・廃業等届出書」を提出することが必要です。",
         "開業の日から2か月以内（その年の1月15日以前に開業した場合は3月15日まで）", "必要経費に算入しようとする年の3月15日まで（その年の1月16日以後に開業した人や新たに専従者がいることとなった人は、その開業の日や専従者がいることとなった日から2か月以内）",
         "所法49、57、143、144、229、所令120、120の2、123、125、所規36の4、所基通49-1"),
        ("TA2072", "ta_2072", "（注2）不動産所得の金額または事業所得の金額の合計額が55万円より少ない場合には、その合計額が限度になります。ただし、この合計額とは損益通算前の黒字の所得金額の合計額をいいますので、いずれかの所得に損失が生じている場合には、その損失をないものとして合計額を計算します。",
         "（注3）不動産所得の金額、事業所得の金額から順次控除します。", "（注1）不動産所得の金額、事業所得の金額または山林所得の金額の合計額が10万円より少ない場合には、その金額が限度になります。", "（注2）不動産所得の金額、事業所得の金額、山林所得の金額から順次控除します。"),
        ("TA2075", "ta_2075", "（注1）青色申告者の事業専従者として給与の支払を受ける人または白色申告者の事業専従者である人は、同一生計配偶者や扶養親族にはなれません。",
         "（注2） 不動産所得の場合、青色申告者に係る青色事業専従者給与または白色申告者に係る事業専従者控除額については、不動産貸付けが事業として行われている場合は適用がありますが、それ以外の場合には適用がありません。"),
        ("TA2210", "ta_2210", "（2）必要経費になるものとならないものの例", "イ 生計を一にする配偶者その他の親族に支払う地代家賃などは必要経費になりません。逆に、受け取った人も所得としては考えません。", "これは、土地や家屋に限らずその他の資産を借りた場合も同様です。ただし、例えば子が生計を一にする父から業務のために借りた土地・建物に課される固定資産税等の費用は、子が営む業務の必要経費になります。",
         "ロ 生計を一にする配偶者その他の親族に支払う給与賃金（青色事業専従者給与は除きます。）は必要経費になりません。",
         "（注）不動産所得を生ずべき業務の用に供する土地等を取得するために要した負債の利子の額は、不動産所得の計算上必要経費になりますが、不動産所得の金額が損失（赤字）となった場合には、その負債の利子の額に相当する部分の損失の額は生じなかったものとみなされ、他の所得金額との損益通算はできません。"),
        ("TA2250-4", "ta_2250", "（注4）", "（1） 別荘等の生活に通常必要でない資産の貸付けに係るもの", "（2） 土地（土地の上に存する権利を含みます。）を取得するために要した負債の利子に相当する部分の金額",
         "（3） 一定の組合契約等に基づいて営まれる事業から生じたもので、その組合の特定組合員等に係るもの", "※（3）により生じた損失は、他の不動産から生ずる不動産所得との内部通算（いわゆる所得内通算）もできません。",
         "（4） 令和3年分以後の各年において、国外中古建物から生じた不動産所得の損失", "※（4）により生じた損失は、国内にある不動産から生ずる不動産所得との内部通算（いわゆる所得内通算）もできません。"),
        ("TA1391-extra", "ta_1391", "特定組合員等の不動産所得の損益通算", "他の不動産所得の黒字から差し引くことができませんし、損益通算の対象にもなりません。",
         "国外中古建物の不動産所得の損益通算等の特例", "国内にある不動産から生じる不動産所得との内部通算（いわゆる所得内通算）および不動産所得以外の所得との損益通算はできません。"),
        ("QA02-27", "shitsugi_02_27", "事業に至らない規模で不動産を貸し付けていましたが、総収入金額に計上していた未収家賃（50万円）が回収不能となりました。", "その回収不能となった未収家賃の申告年分の不動産所得の金額は赤字",
         "上記〔alt:2〕の金額は「控除した残額」と規定されていますので、「不動産所得の金額」及び「回収不能額に相当する総収入金額がなかったものとした場合に計算される不動産所得の金額」はそれぞれ黒字の場合を前提としており、これらの金額が赤字の場合にはそれぞれ0円として計算します。",
         "したがって、「不動産所得の金額」が赤字の場合には、なかったものとみなされる金額は生じないことから、照会の場合には更正の請求をすることはできません。"),
        ("QA04-14", "shitsugi_04_14", "生計を一にする親族Bとの共有（持分1/2ずつ）", "Aの持分についてのみ特別償却ができます。", "普通償却費については、Bの持分を含む旅館業用建物等の全部について、Aの事業所得の金額の計算上必要経費に算入することになります"),
    ]
    for qid, key, *frags in NQ:
        C(f"D-{qid}", "PS", f"{key} の文言", nta_has(key, *frags), None)
    C("D-51-10-only-ascii", "PS§0", "〔貸倒損失〕のページの最初は 51-10（PS§0 の「51−10〜」）", nta_has("kihon_09_02", "〔貸倒損失〕", "51-10"), None)

    # ============ E. 様式の PDF（検証側の復号。［PS］§8、［M］§3 C5・§4）
    sm = rjson(OUT / "pdf_summary.json")
    for name, (ver, pages) in {"shushi_r07": ("AESV2", 2), "kessan_r07": ("AESV2", 4)}.items():
        f = sm["files"][name]
        C(f"E-enc-{name}", "M§4.1", f"{name}：{ver}（V4・R4）、鍵の検査が通る、{pages}頁",
          f["encrypt"].get("CFM") == ver and f["encrypt"].get("V") == 4 and f["encrypt"].get("R") == 4 and f["encrypt"].get("key_ok") and f["pages"] == pages,
          {"encrypt": f["encrypt"], "pages": f["pages"], "rows": f["rows"]})
    C("E-aes-selftest", "—", "AES-128 復号の自己検査（FIPS-197 C.1）", sm["aes_selftest"], None)
    dl_pdf = pathlib.Path(rjson(OUT / "nta_log.json")["download_dir"])
    for key, n_type0, n_tou in [("pdf_shushi_kakikata_r07", 20, 8), ("pdf_kessan_kakikata_r07", 14, 0)]:
        b = (ROOT / dl_pdf / f"{key}.pdf").read_bytes()
        er = re.search(rb"/Encrypt\s+(\d+)\s+0\s+R", b)
        enc = re.search(rb"(?<![0-9])" + er.group(1) + rb"\s+0\s+obj(.{0,900}?)endobj", b, re.S) if er else None
        v5 = enc is not None and re.search(rb"/V\s+5\b", enc.group(1)) is not None and re.search(rb"/R\s+6\b", enc.group(1)) is not None
        cnt = re.search(rb"/Count\s+(\d+)", b)
        t0 = len(re.findall(rb"/Subtype\s*/Type0", b))
        tou = len(re.findall(rb"/ToUnicode", b))
        idh = len(re.findall(rb"/Encoding\s*/Identity-H", b))
        cid0 = len(re.findall(rb"/Subtype\s*/CIDFontType0\b", b))
        C(f"E-kakikata-{key}", "M§4.1/§4.2", f"{key}：AESV3（V5・R6）、8頁、Type0 フォント {n_type0}・/ToUnicode {n_tou}（暗号化されない辞書の文字列で数えた）",
          b.count(b"/AESV3") > 0 and v5 and cnt and int(cnt.group(1)) == 8 and t0 == n_type0 and tou == n_tou,
          {"V5R6": v5, "count": int(cnt.group(1)) if cnt else None, "type0": t0, "tounicode": tou, "identity_h": idh, "cidfonttype0": cid0})
    sr = pdf_rows("shushi_r07")
    exp_sh = {"G01": "賃貸料", "G02": "礼金・権利金更新料", "G03": "名義書換料その他", "G04": "小計", "G05": "計", "G06": "給料賃金", "G07": "減価償却費",
              "G08": "貸倒金", "G09": "地代家賃", "G10": "借入金利子", "G11": "租税公課", "G12": "損害保険料", "G13": "修繕費", "G14": "", "G15": "雑費",
              "G16": "小計", "G17": "経費計", "G18": "専従者控除前の所得金額", "G19": "専従者控除", "G20": "所得金額", "G21": "土地等を取得するために要した負債の利子の額"}
    got_sh = {}
    for code in exp_sh:
        cs = [(x, y) for p, x, y, t in sr if p == 1 and t == code and x < 200]
        if not cs:
            got_sh[code] = None
            continue
        x0, y0 = cs[0]
        lab = sorted([(-y, x, t) for p, x, y, t in sr if p == 1 and 35 < x < 135 and y0 - 10 <= y <= y0 + 10 and re.search(r"[ぁ-んァ-ン一-龥]", t)
                      and t not in ("そ", "の", "他", "経", "費", "収", "入", "金", "額")])
        got_sh[code] = "".join(norm(t) for _, _, t in lab)
    bad = {c: got_sh.get(c) for c, e in exp_sh.items() if (e and (got_sh.get(c) is None or e not in got_sh[c])) or (not e and got_sh.get(c))}
    C("E-shushi-codes", "PS§8.1/M C5", "収支内訳書（不動産所得用）1頁：G01〜G21 の科目名（G14 は科目名の印字なし）", not bad, {"mismatch": bad, "got": got_sh})
    C("E-shushi-formid", "PS§8.1", "収支内訳書の様式ID：1頁 NTA0KOA130010090、2頁 NTA0KOA130020090",
      any(p == 1 and t == "NTA0KOA130010090" for p, x, y, t in sr) and any(p == 2 and t == "NTA0KOA130020090" for p, x, y, t in sr), None)
    kr = pdf_rows("kessan_r07")
    exp_ks = {"G01": "賃貸料", "G02": "礼金・権利金更新料", "G03": "", "G04": "計", "G05": "租税公課", "G06": "損害保険料", "G07": "修繕費", "G08": "減価償却費",
              "G09": "借入金利子", "G10": "地代家賃", "G11": "給料賃金", "G12": "", "G13": "", "G14": "", "G15": "", "G16": "", "G17": "その他の経費", "G18": "計",
              "G19": "差引金額", "G20": "専従者給与", "G21": "青色申告特別控除前の所得金額", "G22": ("青色申告", "特別控除額"), "G23": "所得金額", "G24": "土地等を取得するために要した負債の利子の額"}
    got_ks = {}
    for code in exp_ks:
        cs = [(x, y) for p, x, y, t in kr if p == 1 and t == code]
        x0, y0 = cs[0]
        lo, hi = (40, 120) if x0 < 300 else (350, 430)
        lab = sorted([(-y, x, t) for p, x, y, t in kr if p == 1 and lo < x < hi and y0 - 12 <= y <= y0 + 12 and re.search(r"[ぁ-んァ-ン一-龥]", t)
                      and t not in ("収", "入", "金", "額", "必", "要", "経", "費")])
        got_ks[code] = "".join(norm(t) for _, _, t in lab)
    bad = {c: got_ks.get(c) for c, e in exp_ks.items() if (e and not all(f in (got_ks.get(c) or "") for f in ((e,) if isinstance(e, str) else e))) or (not e and got_ks.get(c))}
    C("E-kessan-codes", "PS§8.2/M C5", "青色申告決算書（不動産所得用）1頁：G01〜G24 の科目名（G03・G12〜G16 は科目名の印字なし）", not bad, {"mismatch": bad, "got": got_ks})
    k1 = {norm(t) for p, x, y, t in kr if p == 1}
    C("E-kessan-22", "PS§8.2", "決算書㉒：「65万円又は55万円又は10万円と㉑のいずれか少ない方の金額」（PDF の行ごとの文字列）",
      {"65万円又は55万円又", "は10万円とのいず", "れか少ない方の金額"} <= k1, None)
    C("E-kessan-24note", "PS§8.2", "決算書1頁の注記：「㉓欄が赤字の人で…その負債の利子の額を書いてください。」（PDF の行ごとの文字列）",
      {"欄が赤字の人で必要経費に算入した", "金額のうちに土地等を取得するために", "要した負債の利子の額がある人は、そ", "の負債の利子の額を書いてください。"} <= k1, None)
    # 4頁の貸借対照表：科目名と欄コード（期首・期末）
    p4 = [(x, y, t) for p, x, y, t in kr if p == 4]
    codes = {}
    for x, y, t in p4:
        if re.fullmatch(r"G\d\d", t):
            codes.setdefault(round(x), []).append((y, t))

    def at(col, y):
        c = [t for yy, t in codes.get(col, []) if abs(yy - y) < 6]
        return c[0] if c else None
    bs = {}
    for x, y, t in p4:
        if (40 < x < 120 or 300 < x < 380) and 45 < y < 460 and re.search(r"[ぁ-んァ-ン一-龥]", t):
            cols = (132, 218) if x < 200 else (394, 481)
            bs[norm(t)] = (at(cols[0], y), at(cols[1], y))
    C("E-kessan-p4-range", "PS§8.2", "決算書4頁：資産の部 G01〜G24（期首）・G25〜G49（期末）、負債・資本の部 G50〜G72（期首）・G73〜G97（期末）",
      sorted(int(t[1:]) for c in (132,) for _, t in codes.get(c, [])) == list(range(1, 25)) and sorted(int(t[1:]) for _, t in codes.get(218, [])) == list(range(25, 50))
      and sorted(int(t[1:]) for _, t in codes.get(394, [])) == list(range(50, 73)) and sorted(int(t[1:]) for _, t in codes.get(481, [])) == list(range(73, 98)), None)
    C("E-kessan-p4-jigyonushi", "PS§8.2（訂正）", "決算書4頁の PDF の文字に「事業主貸」（期末 G48）・「事業主借」（期末 G94）・「元入金」（G71・G95）・「青色申告特別控除前の所得金額」（期末 G96）がある",
      bs.get("事業主貸") == (None, "G48") and bs.get("事業主借") == (None, "G94") and bs.get("元入金") == ("G71", "G95")
      and bs.get("青色申告特別控除") == (None, "G96") and bs.get("前の所得金額") == (None, "G96"),
      {k: bs.get(k) for k in ("事業主貸", "事業主借", "元入金", "青色申告特別控除", "前の所得金額")})
    p2s = "".join(norm(t) for p, x, y, t in sr if p == 2)
    C("E-shushi-p2", "PS§8.1", "収支内訳書2頁：減価償却費の計算（貸付割合の列）・借入金利子・地代家賃・修繕費・税理士等の報酬の内訳・貸付不動産の保有状況（空家・空地、駐車場の屋根付・青空）・特殊事情",
      all(w in p2s for w in ["減価償却費の計算", "貸付割合", "借入金利子の内訳", "地代家賃の内訳", "修繕費の内訳", "税理士", "貸付不動産の保有状況", "空家", "空地", "屋根付", "青空", "特殊事情"]), None)

    # ============ F. 計算（［M］C4 と［I］I1〜I9 を別の実装で）
    p1s = "".join(norm(t) for p, x, y, t in sr if p == 1)
    C("E-shushi-p1-right", "PS§8.1", "収支内訳書1頁の右：不動産所得の収入の内訳（貸家・貸地等の別、用途、不動産の所在地、賃借人の住所・氏名、賃貸契約期間、貸付面積、賃貸料、保証金・敷金）、給料賃金の内訳、事業専従者の氏名等",
      all(w in p1s for w in ["不動産所得の収入の内訳", "貸家", "貸地", "用途", "不動産の所在地", "賃借人", "賃貸契約期間", "貸付面積", "保証金", "敷金", "給料賃金の内訳", "事業専従者の氏名等"]),
      [w for w in ["不動産所得の収入の内訳", "貸家", "貸地", "用途", "不動産の所在地", "賃借人", "賃貸契約期間", "貸付面積", "保証金", "敷金", "給料賃金の内訳", "事業専従者の氏名等"] if w not in p1s])
    k2 = "".join(norm(t) for p, x, y, t in kr if p == 2)
    k3 = "".join(norm(t) for p, x, y, t in kr if p == 3)
    C("E-kessan-p2-p3", "PS§8.2", "決算書2頁：不動産所得の収入の内訳・給料賃金の内訳・専従者給与の内訳。3頁：減価償却費の計算・地代家賃の内訳・借入金利子の内訳（金融機関を除く）・税理士・弁護士等の報酬・料金の内訳",
      all(w in k2 for w in ["不動産所得の収入の内訳", "給料賃金の内訳", "専従者給与の内訳"]) and all(w in k3 for w in ["減価償却費の計算", "地代家賃の内訳", "借入金利子の内訳", "金融機関を除く", "税理士・弁護士等の報酬・料金の内訳"]), None)
    tl = json.loads((OUT / "nta" / "ta_1373.links.json").read_text(encoding="utf-8"))
    C("D-1373-link-0227", "M§2.2", "TA1373 から質疑応答 02/27 へのリンクがある", any(l["href"].endswith("/law/shitsugi/shotoku/02/27.htm") for l in tl), None)
    tl6 = json.loads((OUT / "nta" / "ta_1376.links.json").read_text(encoding="utf-8"))
    C("D-1376-link-qa", "PS§9-8", "TA1376 から「未分割遺産から生じる不動産所得」の QA（1376_qa.htm）へのリンクがある",
      any("1376_qa.htm" in l["href"] and "未分割遺産" in l["text"] for l in tl6), None)

    F = []
    F.append(("C4-41_4-example", [(-100, 90, -10), (-100, 120, 0), (-100, 100, 0), (50, 90, 50)],
              lambda i, r: i if i >= 0 else i + disallowed_41_4(-i, r)))
    for cid, cases, fn in F:
        res = [(a, b, e, fn(a, b)) for a, b, e in cases]
        C(cid, "M C4", "措令26の6① と書き方 p.3 の例（△100・90 → △10 ほか）", all(g == e for *_, e, g in res), res)
    C("C4-25_2-limit", "M C4", "10万円・不動産 △30万円・事業 8万円 → 8万円（事業から）", aoiro_kojo(100_000, [-300_000, 80_000, 0]) == (80_000, [0, 80_000, 0]), aoiro_kojo(100_000, [-300_000, 80_000, 0]))
    C("C4-25_2-order", "M C4", "65万円・不動産 40万円・事業 50万円 → 40万円・25万円", aoiro_kojo(650_000, [400_000, 500_000, 0]) == (650_000, [400_000, 250_000, 0]), None)
    C("C4-57-3", "M C4", "所法57③：配偶者1人・150万円 → 75万円、配偶者以外1人・300万円 → 50万円",
      min(860_000, 1_500_000 // 2) == 750_000 and min(500_000, 3_000_000 // 2) == 500_000, None)
    # I1
    loss = 2_000_000 - 1_200_000
    d1 = disallowed_41_4(loss, 500_000)
    d2 = disallowed_41_4(loss, 900_000)
    C("I1", "I", "I1：⑮ △800,000、みなす額 500,000、③ △300,000、合計所得金額 2,700,000／利子 900,000 なら ③ 0・3,000,000",
      (-loss, d1, -loss + d1, 3_000_000 + (-loss + d1)) == (-800_000, 500_000, -300_000, 2_700_000) and (d2, -loss + d2, 3_000_000 + (-loss + d2)) == (800_000, 0, 3_000_000), None)
    # I2・I9
    c_ok = 1_500_000 - 400_000 - (50_000 + 80_000 + 10_000)
    c_ng = 1_500_000 - 400_000 - 600_000
    p_ng = 600_000 - 140_000
    C("I2", "I", "I2：所法56 適用で C の事業所得 960,000（扶養親族の上限 620,000 を超える）、不適用なら 500,000（上限以下）・P の不動産所得 460,000",
      c_ok == 960_000 and c_ng == 500_000 and p_ng == 460_000 and c_ok > 620_000 and c_ng <= 620_000 and c_ok <= 1_230_000, None)
    C("I9", "I", "I9：既定の解釈で C の雑所得 500,000、P の不動産所得 460,000", c_ng == 500_000 and p_ng == 460_000, None)
    # I3
    C("I3", "I", "I3：給与所得 400,000＋不動産所得 120,000 → 合計 520,000（≦850,000）だが給与所得等以外 120,000 > 100,000 → 勤労学生に当たらない。90,000 なら当たる",
      (400_000 + 120_000 <= 850_000) and not (120_000 <= 100_000) and (400_000 + 90_000 <= 850_000 and 90_000 <= 100_000), None)
    # I4
    r4 = [1_000_000 - aoiro_kojo(c, [1_000_000])[0] for c in (650_000, 550_000, 100_000)]
    C("I4", "I", "I4：控除前 1,000,000 → 65万円で 350,000・55万円で 450,000（≦580,000）、10万円で 900,000（>580,000）",
      r4 == [350_000, 450_000, 900_000] and r4[0] <= 580_000 and r4[1] <= 580_000 and r4[2] > 580_000, r4)
    # I5
    exp5 = {"sozei": 200_000, "hoken": 50_000, "genka": 400_000, "risoku": 300_000, "shuzen": 100_000}
    shotoku5 = 1_500_000 - sum(exp5.values())
    ng = exp5["sozei"] + exp5["hoken"] + exp5["genka"] + exp5["risoku"]
    lo, hi = 1_500_000 - exp5["shuzen"], 1_500_000
    C("I5", "I", "I5：不動産所得 450,000（≦580,000）。健保（協会けんぽの公表を注入）1,400,000〜1,500,000 → 130万円基準で当たらない・180万円基準で満たす。注入なし 450,000〜1,500,000 → 130万円で未確定",
      shotoku5 == 450_000 and ng == 950_000 and (lo, hi) == (1_400_000, 1_500_000) and lo >= 1_300_000 and hi < 1_800_000
      and (1_500_000 - sum(exp5.values()), 1_500_000) == (450_000, 1_500_000) and 450_000 < 1_300_000 <= 1_500_000, None)
    # I6
    C("I6", "I", "I6：X +200,000・Y △500,000 → 不動産所得 △300,000（Y の赤字の範囲内）→ 通算に回る損失 0、総所得金額 2,000,000",
      200_000 - 500_000 == -300_000 and 300_000 <= 500_000, None)
    # I7
    pays_2025 = [m for m in range(1, 13)]  # 2025-01-31〜2025-12-31 の各月末に翌月分を受け取る
    period_2025 = [m for m in range(2, 13)]
    C("I7", "I", "I7：支払日基準 12回 × 50,000 = 600,000、期間対応 2月〜12月 = 550,000", (len(pays_2025) * 50_000, len(period_2025) * 50_000) == (600_000, 550_000), None)
    # I8
    rest, after = tsusan_order(1_000_000, [("給与", 600_000)], [("一時", 300_000)], [])
    C("I8", "I", "I8：不動産 △1,000,000 → 給与 600,000 → 0、一時 300,000 → 0、純損失 100,000、総所得金額 0",
      rest == 100_000 and after == {"給与": 0, "一時": 0} and (after["給与"] + after["一時"] // 2) == 0, {"rest": rest, "after": after})

    # ============ G. 文書の規約（参照・URL・個人の情報）
    for k, t in (("H", hdoc), ("I", idoc)):
        C(f"G-nourl-{k}", k, f"［{k}］に外部の URL（http）がない", re.search(r"https?://", t) is None, re.findall(r"https?://\S+", t)[:5])
    hbasis = "\n".join(ln for ln in hdoc.splitlines() if not ln.startswith("- 推測（"))  # 推測の文書への案内の1行は根拠の参照ではない
    hrefs = set(re.findall(r"`(docs/[^`]+\.md)`", hbasis))
    C("G-H-refs", "H", "［H］が根拠として参照する文書は measurements・public-sources だけ（推測の文書への案内の1行を除く）",
      all(r.startswith(("docs/measurements/", "docs/public-sources/")) for r in hrefs), sorted(hrefs))
    irefs = set(re.findall(r"`(docs/[^`]+\.md)`", idoc))
    C("G-I-refs", "I", "［I］が参照する文書は hypotheses だけ", all(r.startswith("docs/hypotheses/") for r in irefs), sorted(irefs))
    allrefs = set(re.findall(r"`(docs/[^`]+\.md)`", ps + mdoc + hdoc + idoc))
    C("G-refs-exist", "all", "4つの文書が参照する docs/ の文書がすべて存在する", all((ROOT / r).exists() for r in allrefs), [r for r in allrefs if not (ROOT / r).exists()])
    srefs = set(re.findall(r"`(scripts/[^`<>]+?\.(?:py|json))`", ps + mdoc))
    C("G-scripts-exist", "M", "［M］［PS］が参照するスクリプト・出力のファイルが存在する", all((ROOT / r).exists() for r in srefs), [r for r in srefs if not (ROOT / r).exists()])
    pii = re.findall(r"(長男|長女|次男|次女|息子|娘さん|ユーザーの(?:家族|子|妻|夫|母|父)|実在の家族|本人の氏名)", ps + mdoc + hdoc + idoc)
    C("G-no-pii", "all", "個人・家族を特定する語（長男・長女・ユーザーの家族 など）がない", not pii, pii)
    # 参照先の節が存在するか（［PS］冒頭の既存の成果との関係）
    jigyo = (ROOT / "docs/public-sources/20261109_impl-prep_jigyo-laws-and-nta.md").read_text(encoding="utf-8")
    j5 = jigyo.split("## 5.", 1)[1].split("## 7.", 1)[0]
    C("G-PS-jigyo-sec", "PS冒頭", "（訂正前の主張）［PS］冒頭の「帳簿（所法148・232）、収支内訳書の添付（所法120）：jigyo §5〜§6」は jigyo の §5〜§6 にある。NG なら誤り",
      "第232条" in j5 or "所法232" in j5, {"jigyo§5〜§6 の見出し": re.findall(r"^## [56]\..*$", jigyo, re.M)})
    C("G-PS-jigyo-sec-actual", "PS冒頭", "所法148 は jigyo §3.1、所法232 は §4.3・§7.1、所法120 は §4.3・§7 にある（訂正後の参照先）",
      "第148条" in jigyo.split("### 3.1", 1)[1].split("### 3.2", 1)[0] and "第232条" in jigyo.split("## 7.", 1)[1].split("## 8.", 1)[0]
      and "所法120" in jigyo.split("### 4.3", 1)[1].split("## 5.", 1)[0], None)
    out_doc = (ROOT / "docs/public-sources/20261109_impl-prep_output-forms-and-specs.md").read_text(encoding="utf-8")
    C("G-OF-codes", "H8", "［OF］§2.2 に第一表の ㋒ 不動産 `G30`、③ 不動産 `G41`、区分 `G11`・`G12`",
      re.search(r"㋒ 不動産 \| `G11`・`G12` \| `G30`", out_doc) is not None and re.search(r"③ 不動産 .*`G41`", out_doc) is not None, None)
    C("G-OF-12", "PS§8.3", "［OF］§1.2 に「令和８年９月19日（土）から」と収支内訳書（農業所得用・不動産所得用）・青色申告決算書（…不動産所得用…）",
      "令和８年９月19日（土）から" in out_doc and "収支内訳書（農業所得用・不動産所得用）" in out_doc and "不動産所得用" in out_doc.split("### 1.2", 1)[1].split("### 1.3", 1)[0], None)
    kp = (ROOT / "docs/public-sources/20261109_impl-prep_kenpo-dependent-practice.md").read_text(encoding="utf-8")
    kp12 = kp.split("### 1.2", 1)[1].split("### 1.4", 1)[0]
    C("G-KP", "PS§7/H7", "［KP］§1.2：不動産収入は年間収入に含む、減価償却費（不動産所得）は控除できない、令和8年度リーフレットの認められない経費の例",
      "地代・家賃収入などの財産収入" in kp12 and "不動産所得" in kp12 and "租税公課、旅費交通費、広告宣伝費、接待交際費、損害保険料、減価償却費、福利厚生費、利子割引料、雑費、青色申告特別控除等" in kp12, None)

    ng = [r["id"] for r in RESULTS if not r["ok"]]
    wjson(OUT / "check.json", {"n": len(RESULTS), "ng": ng, "results": RESULTS})
    print("done", len(RESULTS), "NG:", ng)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "egov":
        return mode_egov()
    if mode == "nta":
        return mode_nta()
    if mode == "pdf":
        return mode_pdf(sys.argv[2:])
    if mode == "check":
        return mode_check()
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())

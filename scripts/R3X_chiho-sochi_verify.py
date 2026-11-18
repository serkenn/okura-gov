"""R3X chiho-sochi 検証（反証役）：トピック chiho-sochi の文書（docs/*/20261109_round3_chiho-sochi-*.md）に書かれた
条番号・条文の引用・通知の番号と日付・URL・取得の記録・数えた回数を、一次情報を取り直して確かめる。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_chiho-sochi_verify.py fetch-egov
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_chiho-sochi_verify.py fetch-web
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_chiho-sochi_verify.py check

- 担当の取得物（.work/downloads/*_R3X_chiho-sochi_*）や担当の出力（scripts/results/R3X_chiho-sochi_*）は使わない。すべて取り直す。
  ただし、担当の fetch_log の値（law_revision_id・SHA-256・Last-Modified）は「文書に書かれた値」と同じものとして、比べる相手に使う。
- e-Gov 法令API v2 の使い方は scripts/R1_egov_articles.py・scripts/IMPL_kyuyo_fetch.py を写した（import しない）。
- PDF の文字の取り出しは scripts/R3X_chiho-sochi_pdftext.py の暗号なしの経路（オブジェクトの読み出し・ToUnicode・BT〜ET）を写した（import しない）。
  暗号つきの PDF は扱わない（あれば記録して読まない）。
- ダウンロードしたもの（信頼できないデータ）は、取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_R3X_chiho-sochi_verify_<egov|web>/ に置く。その中では何も実行しない（このスクリプトはパスを読むだけ）。
- リクエストの間は 1.5 秒。User-Agent は okura-gov-research/0.1。robots.txt を読み、禁止された URL は取らない。官報は取らない。
- 出力：scripts/results/R3X_chiho-sochi_verify/
    fetch_egov.json・fetch_web.json（取得の記録）、revisions_<略称>.json（改正履歴）、
    checks.json・checks.md（検査ごとの OK / NG / INFO と、確かめた文字列・場所）、
    excerpts/（検査に使った条・PDF の頁のテキストの抜き出し）
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
import zlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "results" / "R3X_chiho-sochi_verify"
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
SLEEP = 1.5
MAXOUT = 64 * 1024 * 1024

CHIHO, CHIHO_REI, CHIHO_KI, SOCHI = "325AC0000000226", "325CO0000000245", "329M50000002023", "332AC0000000026"
EGOV_JOBS = [
    ("chiho", CHIHO, ["2026-11-09", "2026-12-01", "2027-01-01"]),
    # 2022-03-31・2022-04-01・2023-01-01 は担当が取っていない版（令和4年政令第133号の前後。第48条の5の2 の制定時の文を見るため）
    ("chiho-rei", CHIHO_REI, ["2021-01-01", "2022-03-31", "2022-04-01", "2023-01-01", "2024-12-31", "2025-01-01",
                              "2026-01-01", "2026-11-09", "2027-01-01"]),
    ("chiho-ki", CHIHO_KI, ["2026-11-09"]),
    # 2024-12-31 は担当が取っていない版（所得金額調整控除が第41条の3の3 だった時点の確認のため）
    ("sochi", SOCHI, ["2024-12-31", "2026-11-09", "2026-12-01", "2027-01-01"]),
]
REVISIONS = [("chiho-rei", CHIHO_REI, "2021-01-01"), ("chiho", CHIHO, "2025-01-01"), ("sochi", SOCHI, "2024-01-01")]
# 追加の取得（fetch-egov-extra）：所得税法（第60条の2〜第60条の4 の見出し。PS §1.1 の「国外転出時課税など」の確認）
SHOTOKU = "340AC0000000033"
EGOV_EXTRA = [("shotoku", SHOTOKU, ["2026-11-09"])]

SOUMU = "https://www.soumu.go.jp"
WEB_JOBS = [
    ("soumu_ichiran04", f"{SOUMU}/main_sosiki/jichi_zeisei/czaisei/czaisei_seido/ichiran04.html"),
    ("soumu_tsuchi_index", f"{SOUMU}/menu_hourei/s_tsuchi.html"),
    ("soumu_t_tsutatsu", f"{SOUMU}/menu_hourei/tsutatsu/t_tsutatsu.html"),
    ("r8_kaisei_tsuchi", f"{SOUMU}/main_content/001069033.pdf"),
    ("r8_ryuiten", f"{SOUMU}/main_content/001052119.pdf"),
    ("r8_gaiyo", f"{SOUMU}/main_content/001047636.pdf"),
    ("r8_houritsu_sansho", f"{SOUMU}/main_content/001060866.pdf"),
    ("toriatsukai_shichoson_zenbun", f"{SOUMU}/main_content/001071661.pdf"),
    ("toriatsukai_dofuken_zenbun", f"{SOUMU}/main_content/001087182.pdf"),
    ("toriatsukai_shichoson_r8_honbun", f"{SOUMU}/main_content/001067041.pdf"),
    ("toriatsukai_shichoson_r8_betten1", f"{SOUMU}/main_content/001067044.pdf"),
    ("r7_kaisei_tsuchi", f"{SOUMU}/main_content/001004707.pdf"),
    ("r7_ryuiten", f"{SOUMU}/main_content/000988698.pdf"),
    ("h30_kaisei_tsuchi", f"{SOUMU}/main_content/000543593.pdf"),
    ("h30_ryuiten", f"{SOUMU}/main_content/000530377.pdf"),
    ("h30_gaiyo", f"{SOUMU}/main_content/000522323.pdf"),
    # 文書の冒頭に書かれた法令の閲覧用 URL
    ("egov_view_chiho", "https://laws.e-gov.go.jp/law/325AC0000000226"),
    ("egov_view_chiho_rei", "https://laws.e-gov.go.jp/law/325CO0000000245"),
    ("egov_view_chiho_ki", "https://laws.e-gov.go.jp/law/329M50000002023"),
    ("egov_view_sochi", "https://laws.e-gov.go.jp/law/332AC0000000026"),
]


# ============================================================ 取得
def get(url, accept="*/*"):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    hdr = {}
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            body, st = r.read(), r.status
            hdr = {"content_type": r.headers.get("Content-Type", ""), "last_modified": r.headers.get("Last-Modified", ""),
                   "final_url": r.geturl()}
    except urllib.error.HTTPError as e:
        body, st = e.read(), e.code
        hdr = {"content_type": e.headers.get("Content-Type", "") if e.headers else "", "last_modified": "", "final_url": url}
    time.sleep(SLEEP)
    return st, body, hdr


def new_dl(kind):
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R3X_chiho-sochi_verify_{kind}"
    dl.mkdir(parents=True, exist_ok=False)
    return ts, dl


def fetch_egov_extra():
    OUT.mkdir(parents=True, exist_ok=True)
    ts, dl = new_dl("egov-extra")
    log = {"run_at": ts, "download_dir": dl.relative_to(ROOT).as_posix(), "fetches": []}
    for short, law_id, asofs in EGOV_EXTRA:
        for asof in asofs:
            url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
            st, body, _ = get(url, "application/json")
            fn = f"{law_id}_{asof}.json"
            (dl / fn).write_bytes(body)
            e = {"short": short, "law_id": law_id, "asof": asof, "url": url, "status": st, "file": fn,
                 "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
            if st == 200:
                ri = json.loads(body).get("revision_info") or {}
                e.update({k: ri.get(k) for k in ("law_title", "law_revision_id", "amendment_law_num", "current_revision_status")})
            log["fetches"].append(e)
            print(short, asof, st, e.get("law_revision_id"), flush=True)
    (OUT / "fetch_egov_extra.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


def fetch_egov():
    OUT.mkdir(parents=True, exist_ok=True)
    ts, dl = new_dl("egov")
    log = {"run_at": ts, "download_dir": dl.relative_to(ROOT).as_posix(), "search": None, "fetches": [], "revisions": []}
    # 施行規則の law_id を題名で確かめる
    q = urllib.parse.urlencode({"law_title": "地方税法施行規則", "response_format": "json"})
    st, body, _ = get(f"{API}/laws?{q}", "application/json")
    (dl / "search_chiho-ki.json").write_bytes(body)
    found = []
    if st == 200:
        for it in json.loads(body).get("laws", []):
            ri = it.get("revision_info") or it.get("current_revision_info") or {}
            found.append({"law_id": (it.get("law_info") or {}).get("law_id"), "law_title": ri.get("law_title"),
                          "law_num": (it.get("law_info") or {}).get("law_num")})
    log["search"] = {"url": f"{API}/laws?{q}", "status": st, "results": found}
    print("search", st, found, flush=True)
    for short, law_id, asofs in EGOV_JOBS:
        for asof in asofs:
            url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
            st, body, _ = get(url, "application/json")
            fn = f"{law_id}_{asof}.json"
            (dl / fn).write_bytes(body)
            e = {"short": short, "law_id": law_id, "asof": asof, "url": url, "status": st, "file": fn,
                 "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
            if st == 200:
                ri = json.loads(body).get("revision_info") or {}
                e.update({k: ri.get(k) for k in ("law_title", "law_revision_id", "amendment_law_num", "amendment_law_title",
                                                 "amendment_promulgate_date", "amendment_enforcement_date",
                                                 "current_revision_status")})
            log["fetches"].append(e)
            print(short, asof, st, e.get("law_revision_id"), flush=True)
    for short, law_id, frm in REVISIONS:
        q = urllib.parse.urlencode({"response_format": "json", "amendment_date_from": frm})
        url = f"{API}/law_revisions/{law_id}?{q}"
        st, body, _ = get(url, "application/json")
        (dl / f"revisions_{law_id}.json").write_bytes(body)
        revs = []
        if st == 200:
            for rv in json.loads(body).get("revisions", []):
                revs.append({k: rv.get(k) for k in ("law_revision_id", "amendment_promulgate_date", "amendment_enforcement_date",
                                                   "amendment_scheduled_enforcement_date", "amendment_law_title",
                                                   "amendment_law_num", "current_revision_status")})
        (OUT / f"revisions_{short}.json").write_text(json.dumps({"url": url, "status": st, "revisions": revs}, ensure_ascii=False,
                                                                indent=1), encoding="utf-8")
        log["revisions"].append({"short": short, "url": url, "status": st, "n": len(revs), "sha256": hashlib.sha256(body).hexdigest()})
        print("revisions", short, st, len(revs), flush=True)
    (OUT / "fetch_egov.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


def fetch_web():
    OUT.mkdir(parents=True, exist_ok=True)
    ts, dl = new_dl("web")
    log = {"run_at": ts, "download_dir": dl.relative_to(ROOT).as_posix(), "robots": {}, "fetches": []}
    rps = {}
    for name, url in WEB_JOBS:
        host = "{0.scheme}://{0.netloc}".format(urllib.parse.urlsplit(url))
        if host not in rps:
            st, body, _ = get(host + "/robots.txt")
            (dl / f"robots_{urllib.parse.urlsplit(url).netloc}.txt").write_bytes(body)
            rp = urllib.robotparser.RobotFileParser()
            rp.parse(body.decode("utf-8", "replace").splitlines() if st == 200 else [])
            rps[host] = rp
            log["robots"][host] = {"status": st, "sha256": hashlib.sha256(body).hexdigest()}
        allowed = rps[host].can_fetch(UA, url)
        e = {"name": name, "url": url, "robots_allowed": allowed}
        if not allowed:
            log["fetches"].append(e)
            continue
        st, body, hdr = get(url)
        ext = ".pdf" if url.endswith(".pdf") else ".html"
        (dl / f"{name}{ext}").write_bytes(body)
        e.update({"status": st, **hdr, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(), "file": f"{name}{ext}",
                  "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
        log["fetches"].append(e)
        print(name, st, hdr.get("last_modified"), len(body), flush=True)
    (OUT / "fetch_web.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


# ============================================================ e-Gov の JSON
def inline(n):
    if isinstance(n, str):
        return n
    if n.get("tag") == "Rt":
        return ""
    return "".join(inline(c) for c in n.get("children", []))


def walk(n, fn, path=()):
    if isinstance(n, dict):
        fn(n, path)
        for c in n.get("children", []):
            walk(c, fn, path + (n,))


def norm(s):
    return re.sub(r"[\s\u3000]+", "", s.replace("**", ""))


class Law:
    def __init__(self, path):
        d = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        self.ri = d.get("revision_info") or {}
        self.root = d["law_full_text"]
        self.arts = []   # (suppl: None=本則 / "原始" / AmendLawNum, article node, path)
        self.sents = []  # (where, text)

        def fn(n, path):
            if n.get("tag") == "Article":
                sp = [p for p in path if p.get("tag") == "SupplProvision"]
                sup = None if not sp else (sp[-1].get("attr", {}).get("AmendLawNum") or "原始")
                self.arts.append((sup, n, path))
            if n.get("tag") == "Sentence":
                self.sents.append((self.where(path), inline(n)))
        walk(self.root, fn)

    @staticmethod
    def where(path):
        part, art, para, item = "本則", None, None, None
        for p in path:
            t, a = p.get("tag"), p.get("attr") or {}
            if t == "SupplProvision":
                part = "附則(" + (a.get("AmendLawNum") or "原始") + ")"
            elif t == "Article":
                art = a.get("Num")
            elif t == "Paragraph":
                para = a.get("Num")
            elif t == "Item":
                item = a.get("Num")
            elif t.startswith("Appdx"):
                part = t
        return (part, art, para, item)

    def article(self, num, suppl=None):
        """suppl：None＝本則、"原始"＝原始附則、"re:<正規表現>"＝AmendLawNum が正規表現に合う改正附則（例 re:^令和四年.*政令第一三三号$）"""
        for sup, n, path in self.arts:
            if isinstance(suppl, str) and suppl.startswith("re:"):
                hit = sup not in (None, "原始") and re.search(suppl[3:], sup)
            else:
                hit = sup == suppl
            if hit and n.get("attr", {}).get("Num") == num:
                return n, path
        return None, None

    def caption(self, num, suppl=None):
        a, _ = self.article(num, suppl)
        if a is None:
            return None
        for c in a.get("children", []):
            if isinstance(c, dict) and c.get("tag") == "ArticleCaption":
                return inline(c)
        return ""

    def para(self, num, p, suppl=None):
        a, _ = self.article(num, suppl)
        if a is None:
            return None
        for c in a.get("children", []):
            if isinstance(c, dict) and c.get("tag") == "Paragraph" and c.get("attr", {}).get("Num") == str(p):
                return c
        return None

    def para_text(self, num, p, suppl=None):
        n = self.para(num, p, suppl)
        return None if n is None else inline(n)

    def para_head(self, num, p, suppl=None):
        """項の柱書（号を除いた部分）"""
        n = self.para(num, p, suppl)
        if n is None:
            return None
        return "".join(inline(c) for c in n.get("children", []) if isinstance(c, dict) and c.get("tag") in ("ParagraphNum", "ParagraphSentence"))

    def item_text(self, num, p, item, suppl=None, head_only=False):
        n = self.para(num, p, suppl)
        if n is None:
            return None
        for c in n.get("children", []):
            if isinstance(c, dict) and c.get("tag") == "Item" and c.get("attr", {}).get("Num") == str(item):
                if head_only:
                    return "".join(inline(x) for x in c.get("children", []) if isinstance(x, dict) and x.get("tag") in ("ItemTitle", "ItemSentence"))
                return inline(c)
        return None

    def subitem_text(self, num, p, item, sub, suppl=None):
        n = self.para(num, p, suppl)
        if n is None:
            return None, None
        for c in n.get("children", []):
            if isinstance(c, dict) and c.get("tag") == "Item" and c.get("attr", {}).get("Num") == str(item):
                for s in c.get("children", []):
                    if isinstance(s, dict) and s.get("tag") == "Subitem1" and s.get("attr", {}).get("Num") == str(sub):
                        title = "".join(inline(x) for x in s.get("children", []) if isinstance(x, dict) and x.get("tag") == "Subitem1Title")
                        return title, inline(s)
        return None, None

    def article_text(self, num, suppl=None):
        a, _ = self.article(num, suppl)
        return None if a is None else inline(a)

    def ancestors(self, num, suppl=None):
        a, path = self.article(num, suppl)
        if a is None:
            return None
        out = []
        for p in path:
            t = p.get("tag")
            if t in ("Part", "Chapter", "Section", "Subsection", "Division"):
                for c in p.get("children", []):
                    if isinstance(c, dict) and c.get("tag") == t + "Title":
                        out.append(inline(c))
        return out

    def structure_titles(self, tag):
        """指定したタグ（Chapter など）の題名と、その中の最初と最後の本則の条番号"""
        res = []

        def fn(n, path):
            if n.get("tag") == tag and not any(p.get("tag") == "SupplProvision" for p in path):
                title = "".join(inline(c) for c in n.get("children", []) if isinstance(c, dict) and c.get("tag") == tag + "Title")
                nums = []
                walk(n, lambda m, pp: nums.append(m["attr"].get("Num")) if m.get("tag") == "Article" else None)
                anc = [inline(c) for p in path for c in p.get("children", []) if isinstance(c, dict) and c.get("tag", "").endswith("Title")
                       and p.get("tag") in ("Chapter", "Section", "Subsection", "Division")]
                res.append({"title": title, "parents": anc, "first": nums[0] if nums else None, "last": nums[-1] if nums else None})
        walk(self.root, fn)
        return res


# ============================================================ PDF（scripts/R3X_chiho-sochi_pdftext.py の暗号なしの経路を写した）
def inflate(b):
    d = zlib.decompressobj()
    out = d.decompress(b, MAXOUT)
    if d.unconsumed_tail:
        raise ValueError("inflate: 上限を超えた")
    return out


def raw_objects(pdf):
    for m in re.finditer(rb"(\d+)\s+(\d+)\s+obj\b", pdf):
        end = pdf.find(b"endobj", m.end())
        body = pdf[m.end():end]
        sm = re.search(rb"stream\r?\n", body)
        if not sm:
            yield int(m.group(1)), int(m.group(2)), body, None
            continue
        dic = body[:sm.start()]
        lm = re.search(rb"/Length\s+(\d+)(?!\s+\d+\s+R)", dic)
        raw = body[sm.end():sm.end() + int(lm.group(1))] if lm else body[sm.end():body.rfind(b"endstream")].rstrip(b"\r\n")
        yield int(m.group(1)), int(m.group(2)), dic, raw


def load_pdf(pdf):
    if re.search(rb"/Encrypt\s", pdf):
        return None, True
    objs = {}
    for num, gen, dic, raw in raw_objects(pdf):
        if raw is None:
            objs[num] = (dic, None)
            continue
        dec = raw
        if b"FlateDecode" in dic:
            try:
                dec = inflate(dec)
            except Exception as e:  # noqa
                dec = b"<<inflate error " + repr(e).encode() + b">>"
        objs[num] = (dic, dec)
    for num, (dic, dec) in list(objs.items()):
        if dec is not None and b"/ObjStm" in dic:
            nn = int(re.search(rb"/N\s+(\d+)", dic).group(1))
            first = int(re.search(rb"/First\s+(\d+)", dic).group(1))
            hdr = [int(x) for x in dec[:first].split()]
            pairs = [(hdr[i], hdr[i + 1]) for i in range(0, min(len(hdr), 2 * nn), 2)]
            for i, (onum, off) in enumerate(pairs):
                end = pairs[i + 1][1] if i + 1 < len(pairs) else len(dec) - first
                objs.setdefault(onum, (dec[first + off:first + end], None))
    return objs, False


def ref(b, name):
    m = re.search(rb"/" + name + rb"\s*(\d+)\s+0\s+R", b)
    return int(m.group(1)) if m else None


def parse_cmap(b):
    m = {}
    for blk in re.findall(rb"beginbfchar(.*?)endbfchar", b, re.S):
        for a, c in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
            m[int(a, 16)] = bytes.fromhex(c.decode()).decode("utf-16-be", "replace")
    for blk in re.findall(rb"beginbfrange(.*?)endbfrange", b, re.S):
        for a, z, c in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
            base = int(c, 16)
            for k in range(int(a, 16), int(z, 16) + 1):
                m[k] = chr(base + k - int(a, 16))
    return m


def font_decoder(objs, fnum):
    dic = objs.get(fnum, (b"", None))[0]
    encm = re.search(rb"/Encoding\s*/([A-Za-z0-9\-]+)", dic)
    enc = encm.group(1).decode() if encm else ""
    tu = ref(dic, rb"ToUnicode")
    if "RKSJ" in enc:
        return lambda raw: raw.decode("cp932", "replace")
    if "UCS2" in enc or "UTF16" in enc:
        return lambda raw: raw.decode("utf-16-be", "replace")
    if tu is not None and objs.get(tu, (None, None))[1]:
        cm = parse_cmap(objs[tu][1])
        if enc.startswith("Identity") or b"/Type0" in dic:
            return lambda raw: "".join(cm.get(int.from_bytes(raw[i:i + 2], "big"), "\ufffd") for i in range(0, len(raw) - 1, 2))
        return lambda raw: "".join(cm.get(c, chr(c)) for c in raw)
    return lambda raw: raw.decode("latin-1")


def unescape_literal(s):
    out, i = bytearray(), 0
    while i < len(s):
        c = s[i]
        if c == 0x5C and i + 1 < len(s):
            n = s[i + 1]
            mp = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12, ord("("): 40, ord(")"): 41, ord("\\"): 92}
            if n in mp:
                out.append(mp[n])
                i += 2
                continue
            m = re.match(rb"[0-7]{1,3}", s[i + 1:i + 4])
            if m:
                out.append(int(m.group(0), 8) & 0xFF)
                i += 1 + len(m.group(0))
                continue
            i += 1
            continue
        out.append(c)
        i += 1
    return bytes(out)


TOK = re.compile(rb"<([0-9A-Fa-f\s]*)>|\(((?:[^()\\]|\\.)*)\)|\[|\]|/([^\s/\[\]<>()]+)|([-+]?\d*\.?\d+)|([A-Za-z'\"*]+)", re.S)


def page_rows(objs, pno, pdic):
    res = pdic
    rnum = ref(pdic, rb"Resources")
    if rnum is not None:
        res = objs.get(rnum, (b"", None))[0]
    fonts = {}
    fm = re.search(rb"/Font\s*(\d+)\s+0\s+R", res)
    fdict = objs.get(int(fm.group(1)), (b"", None))[0] if fm else (re.search(rb"/Font\s*<<(.*?)>>", res, re.S) or re.search(b"()", b"")).group(1)
    for name, num in re.findall(rb"/([^\s/<>]+)\s+(\d+)\s+0\s+R", fdict or b""):
        fonts[name.decode()] = font_decoder(objs, int(num))
    cont = re.search(rb"/Contents\s*(\[[^\]]*\]|\d+\s+0\s+R)", pdic)
    nums = [int(x) for x in re.findall(rb"(\d+)\s+0\s+R", cont.group(1))] if cont else []
    content = b"\n".join(objs.get(c, (b"", b""))[1] or b"" for c in nums)
    rows = []
    for bt in re.findall(rb"\bBT\b(.*?)\bET\b", content, re.S):
        stack, x, y, lx, ly, cur, lead = [], 0.0, 0.0, 0.0, 0.0, None, 0.0
        arr = None
        for m in TOK.finditer(bt):
            h, lit, nm, num, op = m.groups()
            tok = m.group(0)
            if tok == b"[":
                arr = []
                continue
            if tok == b"]":
                stack.append(("arr", arr))
                arr = None
                continue
            if h is not None:
                hx = re.sub(rb"\s", b"", h)
                v = ("str", bytes.fromhex(hx.decode() + ("0" if len(hx) % 2 else "")))
            elif lit is not None:
                v = ("str", unescape_literal(lit))
            elif nm is not None:
                v = ("name", nm.decode("latin-1"))
            elif num is not None:
                v = ("num", float(num))
            else:
                v = None
            if v is not None:
                if arr is not None:
                    arr.append(v)
                else:
                    stack.append(v)
                continue
            o = op.decode("latin-1")
            nums_ = [s[1] for s in stack if s[0] == "num"]
            if o == "Tf" and len(stack) >= 2 and stack[-2][0] == "name":
                cur = stack[-2][1]
            elif o == "Tm" and len(nums_) >= 6:
                x, y = nums_[-2], nums_[-1]
                lx, ly = x, y
            elif o in ("Td", "TD") and len(nums_) >= 2:
                lx, ly = lx + nums_[-2], ly + nums_[-1]
                x, y = lx, ly
                if o == "TD":
                    lead = -nums_[-1]
            elif o == "TL" and nums_:
                lead = nums_[-1]
            elif o == "T*":
                ly -= lead
                x, y = lx, ly
            elif o in ("Tj", "'", '"', "TJ"):
                dec = fonts.get(cur, lambda raw: raw.decode("latin-1"))
                if o == "TJ":
                    parts = [s for s in (stack[-1][1] if stack and stack[-1][0] == "arr" else []) if s[0] == "str"]
                    txt = "".join(dec(s[1]) for s in parts)
                else:
                    strs = [s for s in stack if s[0] == "str"]
                    txt = dec(strs[-1][1]) if strs else ""
                if txt.strip():
                    rows.append((pno, x, y, txt))
            stack = []
    return rows


def pages_of(objs):
    def kids(num):
        dic = objs.get(num, (b"", None))[0]
        if re.search(rb"/Type\s*/Page\b(?!s)", dic):
            return [num]
        km = re.search(rb"/Kids\s*\[([^\]]*)\]", dic)
        out = []
        for k in re.findall(rb"(\d+)\s+0\s+R", km.group(1) if km else b""):
            out += kids(int(k))
        return out
    roots = [n for n, (d, _) in objs.items() if re.search(rb"/Type\s*/Pages\b", d) and not re.search(rb"/Parent\s", d)]
    return kids(roots[0]) if roots else [n for n, (d, _) in sorted(objs.items()) if re.search(rb"/Type\s*/Page\b(?!s)", d)]


def pdf_pages(path):
    """頁ごとの行（y の近さ 2.5 以内を1行、x の昇順）。暗号つきなら None。"""
    pdf = pathlib.Path(path).read_bytes()
    objs, enc = load_pdf(pdf)
    if enc:
        return None, {"encrypted": True}
    pages = pages_of(objs)
    out = []
    for i, pnum in enumerate(pages, 1):
        rows = page_rows(objs, i, objs[pnum][0])
        pr = sorted(rows, key=lambda r: (-r[2], r[1]))
        lines, cur, cy = [], [], None
        for r in pr:
            if cy is None or abs(r[2] - cy) <= 2.5:
                cur.append(r)
                cy = r[2] if cy is None else cy
            else:
                lines.append(cur)
                cur, cy = [r], r[2]
        if cur:
            lines.append(cur)
        out.append(["".join(q[3] for q in sorted(ln, key=lambda q: q[1])) for ln in lines])
    t0 = [d for d, _ in objs.values() if re.search(rb"/Subtype\s*/Type0", d)]
    meta = {"encrypted": False, "pages": len(pages), "pages_without_text": [i + 1 for i, p in enumerate(out) if not p],
            "type0_fonts": len(t0), "type0_without_tounicode": sum(1 for d in t0 if b"/ToUnicode" not in d)}
    return out, meta


PAGENO = re.compile(r"\s*[-－–−‐]?\s*[0-9０-９]+\s*[-－–−‐]?\s*")


class Doc:
    """PDF の頁のテキスト。頁番号だけの行を除き、空白を取り除いて頁をつないだ文字列と、位置 → 頁の対応を持つ。"""

    def __init__(self, pages):
        self.pages = pages
        self.text, self.starts = "", []
        for p in pages:
            self.starts.append(len(self.text))
            self.text += norm("".join(ln for ln in p if not PAGENO.fullmatch(ln)))

    def page_at(self, pos):
        k = 0
        for i, s in enumerate(self.starts):
            if s <= pos:
                k = i
        return k + 1

    def find(self, s):
        s = norm(s)
        i = self.text.find(s)
        return None if i < 0 else (self.page_at(i), self.page_at(i + len(s) - 1))

    def count(self, s):
        return self.text.count(norm(s))


# ============================================================ 検査
RESULTS = []


LAYOUT = {"PS7.2-p6-0", "PS7.2-p6-1", "PS7.2-p6-2", "PS7.2-p6-3", "PS7.3-r-a", "PS7.3-r-i", "PS7.3-r-note", "PS7.3-k-no"}


def rec(cid, doc, sec, claim, ok, detail=""):
    r = "OK" if ok is True else ("NG" if ok is False else "INFO")
    if r == "NG" and cid in LAYOUT:
        r = "NG(取り出し順)"
        detail += "（取り出したテキストで文の順序が崩れる頁。頁の画像で確かめる。実測の文書を参照）"
    RESULTS.append({"id": cid, "doc": doc, "section": sec, "claim": claim, "result": r, "detail": detail})
    print(f"[{r}] {cid} {claim} {detail}"[:300], flush=True)


def frags_in_order(text, quote):
    """引用（「…」で省略）の断片が、空白を除いた text に順に含まれるか。含まれない最初の断片を返す。"""
    t = norm(text or "")
    pos = 0
    for f in [norm(x) for x in quote.split("…")]:
        if len(f) < 2:
            continue
        i = t.find(f, pos)
        if i < 0:
            return False, f
        pos = i + len(f)
    return True, ""


def check_quote(cid, doc, sec, claim, text, quote, exact=False):
    if text is None:
        rec(cid, doc, sec, claim, False, "対象の条・項が見つからない")
        return
    if exact:
        ok = norm(text) == norm(quote)
        rec(cid, doc, sec, claim, ok, "全文一致" if ok else f"不一致: 取得={norm(text)[:200]}")
        return
    ok, miss = frags_in_order(text, quote)
    rec(cid, doc, sec, claim, ok, "断片がすべて順に含まれる" if ok else f"含まれない断片: {miss[:120]}")


def check():
    eg = json.loads((OUT / "fetch_egov.json").read_text(encoding="utf-8"))
    wb = json.loads((OUT / "fetch_web.json").read_text(encoding="utf-8"))
    edl = ROOT / eg["download_dir"]
    wdl = ROOT / wb["download_dir"]
    ex = OUT / "excerpts"
    ex.mkdir(parents=True, exist_ok=True)
    laws = {}
    for f in eg["fetches"]:
        if f["status"] == 200:
            laws[(f["short"], f["asof"])] = Law(edl / f["file"])
    L = lambda s, a: laws[(s, a)]  # noqa

    PS, M, H = "PS", "M", "H"
    # ---------------------------------------------------------------- 取得の記録（M §2.1）
    prev = {  # 実測 §2.1 の表に書かれた値
        ("chiho", "2026-11-09"): ("325AC0000000226_20261101_508AC0000000002", "3dd29e0078bf24e0"),
        ("chiho", "2026-12-01"): ("325AC0000000226_20261126_508AC0000000002", "4bb0901ff8ddbf8e"),
        ("chiho", "2027-01-01"): ("325AC0000000226_20270101_508AC0000000002", "ee21722ce5fd1561"),
        ("chiho-rei", "2021-01-01"): ("325CO0000000245_20210101_502CO0000000264", "52159da22a292349"),
        ("chiho-rei", "2024-12-31"): ("325CO0000000245_20241001_506CO0000000300", "661ba6ae7ba4f8b7"),
        ("chiho-rei", "2025-01-01"): ("325CO0000000245_20250101_506CO0000000136", "1eea13376c9d16a4"),
        ("chiho-rei", "2026-01-01"): ("325CO0000000245_20260101_507CO0000000119", "e6224a70357bbc64"),
        ("chiho-rei", "2026-11-09"): ("325CO0000000245_20261101_508CO0000000083", "9bc03b230fb0ed10"),
        ("chiho-rei", "2027-01-01"): ("325CO0000000245_20270101_508CO0000000083", "962bfc48e43c49b4"),
        ("chiho-ki", "2026-11-09"): ("329M50000002023_20261101_508M60000008045", "5ffb833bd3a3d7c4"),
        ("sochi", "2026-11-09"): ("332AC0000000026_20261101_507AC0000000013", "e6e6013bbc0608c6"),
        ("sochi", "2026-12-01"): ("332AC0000000026_20261201_508AC0000000012", "1a11304351168b77"),
        ("sochi", "2027-01-01"): ("332AC0000000026_20270101_508AC0000000012", "8c6ee577201c3be0"),
    }
    byk = {(f["short"], f["asof"]): f for f in eg["fetches"]}
    for k, (rid, sha) in prev.items():
        f = byk.get(k, {})
        rec(f"M2.1-{k[0]}-{k[1]}", M, "§2.1", f"{k[0]} asof {k[1]} の law_revision_id = {rid}", f.get("law_revision_id") == rid,
            f"取得={f.get('law_revision_id')} 改正法令={f.get('amendment_law_num')} 題名={f.get('amendment_law_title')} 施行日={f.get('amendment_enforcement_date')} 状態={f.get('current_revision_status')}")
        rec(f"M2.1-sha-{k[0]}-{k[1]}", M, "§2.1", f"{k[0]} asof {k[1]} の SHA-256 先頭16桁 = {sha}（取り直して同じか。違っても誤りとは限らない）",
            None, f"取り直し={f.get('sha256', '')[:16]} {'同じ' if f.get('sha256', '').startswith(sha) else '違う'}")
    s = eg["search"]
    rec("M2.1-ki-id", M, "§2.1", "地方税法施行規則の law_id = 329M50000002023（題名で検索）",
        any(r["law_id"] == CHIHO_KI and r["law_title"] == "地方税法施行規則" for r in s["results"]), json.dumps(s["results"], ensure_ascii=False))
    rec("M-sochi-2021", M, "§2.1", "措置法 asof 2021-01-01 の law_revision_id = 332AC0000000026_20210101_502AC0000000008（今回は取っていない）", None,
        "今回は 2021-01-01 の措置法を取り直していない（文書の主張に使われていないため）")

    # ---------------------------------------------------------------- PS §1 地方税法の本則
    q313 = ("２　前項の総所得金額、退職所得金額又は山林所得金額は、この法律又はこれに基づく政令で特別の定めをする場合を除くほか、それぞれ所得税法その他の所得税に関する法令の規定による所得税法第二十二条第二項又は第三項の総所得金額、退職所得金額又は山林所得金額の計算の例により算定するものとする。ただし、同法第六十条の二から第六十条の四までの規定の例によらないものとする。")
    for a in ("2026-11-09", "2026-12-01", "2027-01-01"):
        c = L("chiho", a)
        check_quote(f"PS1.1-313-{a}", PS, "§1.1", f"地方税法第313条第2項の全文（asof {a}）", c.para_text("313", 2), q313, exact=True)
        check_quote(f"PS1.1-32-{a}", PS, "§1.1", f"第32条第2項は同じ文（asof {a}）", c.para_text("32", 2), q313, exact=True)
    c = L("chiho", "2026-11-09")
    (ex / "chiho_2026-11-09_313.txt").write_text(c.article_text("313"), encoding="utf-8")
    anc313, anc32 = c.ancestors("313"), c.ancestors("32")
    rec("PS1.1-313-anc", PS, "§1.1", "第313条は 第三章 市町村の普通税 ＞ 第一節 市町村民税 ＞ 第二款 課税標準及び税率",
        [norm(x) for x in anc313] == [norm(x) for x in ["第三章　市町村の普通税", "第一節　市町村民税", "第二款　課税標準及び税率"]], " / ".join(anc313))
    rec("PS1.1-32-anc", PS, "§1.1", "第32条は 第二章 道府県の普通税 ＞ 第一節 道府県民税 ＞ 第二款 個人の道府県民税 ＞ 第一目 課税標準及び税率",
        [norm(x) for x in anc32] == [norm(x) for x in ["第二章　道府県の普通税", "第一節　道府県民税", "第二款　個人の道府県民税", "第一目　課税標準及び税率"]],
        " / ".join(anc32))
    # 第292条第5項・第23条第5項
    for a in ("2026-11-09", "2027-01-01"):
        c = L("chiho", a)
        check_quote(f"PS1.2-292-5-{a}", PS, "§1.2", f"第292条第5項の全文（asof {a}）", c.para_text("292", 5),
                    "５　市町村民税について所得税法その他の所得税に関する法令を引用する場合（第一項第六号、第三百十七条の六、第三百二十一条の四及び第五款において引用する場合を除く。）には、これらの法令は、前年の所得について適用されたものをいうものとする。", exact=True)
        check_quote(f"PS1.2-23-5-{a}", PS, "§1.2", f"第23条第5項の全文（asof {a}）", c.para_text("23", 5),
                    "５　道府県民税について所得税法その他の所得税に関する法令を引用する場合（第一項第六号及び第十四号から第十七号まで、第二十五条の二、次款第三目及び第四款から第六款まで並びに附則第三十五条の二の五第二項から第四項までにおいて引用する場合を除く。）には、これらの法令は、前年の所得について適用されたものをいうものとする。", exact=True)
    c = L("chiho", "2026-11-09")
    # 款・目の題名（除外の当てはまり）
    divs = c.structure_titles("Subsection") + c.structure_titles("Division")
    (ex / "chiho_2026-11-09_subsections.json").write_text(json.dumps(divs, ensure_ascii=False, indent=1), encoding="utf-8")
    sub_ss = [d for d in c.structure_titles("Subsection") if d["parents"] and norm(d["parents"][-1]) == norm("第一節　市町村民税")]
    sub_dk = [d for d in c.structure_titles("Subsection") if d["parents"] and norm(d["parents"][-1]) == norm("第一節　道府県民税")]
    rec("PS1.2-ss-kan", PS, "§1.2", "市町村民税（第三章第一節）の款の一覧（第五款は何か。第313条は第二款）", None,
        "; ".join(f"{d['title']}（第{d['first']}条〜第{d['last']}条）" for d in sub_ss))
    rec("PS1.2-dk-kan", PS, "§1.2", "道府県民税（第二章第一節）の款の一覧（第23条の款、次款、第四款〜第六款）", None,
        "; ".join(f"{d['title']}（第{d['first']}条〜第{d['last']}条）" for d in sub_dk))
    dk2_div = [d for d in c.structure_titles("Division") if d["parents"] and norm(d["parents"][-1]) == norm("第二款　個人の道府県民税")]
    rec("PS1.2-dk2-moku", PS, "§1.2", "道府県民税 第二款（個人の道府県民税）の目の一覧（第三目は何か。第32条は第一目）", None,
        "; ".join(f"{d['title']}（第{d['first']}条〜第{d['last']}条）" for d in dk2_div))
    a23 = c.ancestors("23")
    rec("PS1.2-23-anc", PS, "§1.2", "第23条の属する款（「次款」の起点）", None, " / ".join(a23))
    # §1.3
    for num, p in (("71_5", 2), ("71_27", 2)):
        check_quote(f"PS1.3-{num}", PS, "§1.3", f"第{num.replace('_', '条の')}条第{p}項に「…所得税法その他の所得税に関する法令の規定の例によつて算定する。」",
                    c.para_text(num, p), "所得税法その他の所得税に関する法令の規定の例によつて算定する。")
        rec(f"PS1.3-{num}-cap", PS, "§1.3", f"第{num}条の見出し", None, str(c.caption(num)))
    check_quote("PS1.3-316", PS, "§1.3", "第316条第1項の文", c.para_text("316", 1),
                "この法律又はこれに基づく政令で特別の定めをする場合を除くほか、所得税法その他の所得税に関する法令に規定する所得の計算の方法に従い自らその所得を計算し")
    rec("PS1.3-316-cap", PS, "§1.3", "第316条の見出し（「所得の計算が著しく適正を欠く場合」と書かれている）", None, str(c.caption("316")))
    for num in ("34", "35"):
        check_quote(f"PS1.3-fusoku{num}", PS, "§1.3", f"原始附則第{num}条第2項の文", c.para_text(num, 2, "原始"),
                    "譲渡所得について所得税法その他の所得税に関する法令の規定の例により計算した同法第三十三条第三項の譲渡所得の金額")
        rec(f"PS1.3-fusoku{num}-cap", PS, "§1.3", f"原始附則第{num}条の見出し（長期・短期譲渡所得）", None, str(c.caption(num, "原始")))
    # §1.4
    check_quote("PS1.4-72_49_12", PS, "§1.4", "第72条の49の12第1項の文", c.para_text("72_49_12", 1),
                "…所得税の課税標準である所得につき適用される所得税法第二十六条及び第二十七条（同法第百六十五条第一項の規定によりこれらの規定に準ずる場合を含む。）に規定する不動産所得及び事業所得の計算の例により算定する。ただし、租税特別措置法第二十八条の四の規定の例によらないものとし、")
    hits = [(w, s) for w, s in c.sents if "の例によらない" in s]
    locs = sorted({f"{w[0]} 第{w[1]}条第{w[2]}項" for w, s in hits})
    want = {"本則 第32条第2項", "本則 第72条の18第2項", "本則 第72条の23第2項", "本則 第72条の49の12第1項", "本則 第313条第2項", "本則 第703条の5第1項"}
    got = {x.replace("条の", "条の").replace("_", "条の") for x in locs}
    got2 = set()
    for w, s in hits:
        got2.add(f"{w[0]} 第{w[1].replace('_', 'の')}条第{w[2]}項".replace("第72の18", "第72条の18"))
    rec("PS1.4-count", PS, "§1.4", "地方税法（asof 2026-11-09）の全文で「の例によらない」を含む文は 6（第32条②・第72条の18②・第72条の23②・第72条の49の12①・第313条②・第703条の5①）",
        len(hits) == 6, f"{len(hits)} 文: " + "; ".join(f"{w[0]} {w[1]}条 {w[2]}項 {w[3] or ''}号" for w, s in hits))
    for w, s in hits:
        if w[1] in ("72_18", "72_23"):
            rec(f"PS1.4-{w[1]}", PS, "§1.4", f"第{w[1]}条第{w[2]}項は租税特別措置法第55条などを名指しで「例によらない」", "租税特別措置法第五十五条" in s, s[:300])
    hits2 = [(w, s) for w, s in c.sents if "の例によらず" in s]
    rec("PS1.4-yorazu", PS, "§1.4", "（反証探し）地方税法の全文で「の例によらず」を含む文", None,
        f"{len(hits2)} 文: " + "; ".join(f"{w[0]} {w[1]}条 {w[2]}項 {w[3] or ''}号" for w, s in hits2))
    # §1.5
    for a, num in (("2026-11-09", "第二十九条の四"), ("2026-12-01", "第二十九条の四"), ("2027-01-01", "第二十九条の五")):
        t = L("chiho", a).item_text("292", 1, 6)
        check_quote(f"PS1.5-292-1-6-{a}", PS, "§1.5", f"第292条第1項第6号（asof {a}）が措法「{num}」を引く", t,
                    f"所得税法第三十条第一項に規定する退職手当等（同法第三十一条において退職手当等とみなされる一時金及び租税特別措置法{num}において退職手当等とみなされる金額を含む。）をいう。")
        t = L("chiho", a).item_text("23", 1, 6)
        rec(f"PS1.5-23-1-6-{a}", PS, "§1.5", f"第23条第1項第6号（asof {a}）も措法「{num}」を引く", f"租税特別措置法{num}" in (t or ""), (t or "")[:200])
    for a, cap in (("2026-11-09", "（退職勤労者が弁済を受ける未払賃金に係る課税の特例）"), ("2026-12-01", "（給与所得控除の最低控除額等の特例）"),
                   ("2027-01-01", "（給与所得控除の最低控除額等の特例）")):
        got = L("sochi", a).caption("29_4")
        rec(f"PS1.5-29_4cap-{a}", PS, "§1.5", f"措法第29条の4 の見出し（asof {a}）= {cap}", got == cap, str(got))
    for a in ("2026-12-01", "2027-01-01"):
        got = L("sochi", a).caption("29_5")
        rec(f"PS1.5-29_5cap-{a}", PS, "§1.5", f"措法第29条の5 の見出し（asof {a}）= 未払賃金の特例", got == "（退職勤労者が弁済を受ける未払賃金に係る課税の特例）", str(got))
    # 地方税法の 2026-12-01 版の第292条第1項第6号の「第二十九条の四」：改正の附則を探す（反証・未決 CS3）
    for a in ("2026-12-01", "2027-01-01"):
        cc = L("chiho", a)
        hs = [(w, s) for w, s in cc.sents if "第二十九条の五" in s and "租税特別措置法" in s]
        rec(f"CS3-29_5-{a}", H, "未決 CS3", f"（未決の確認）地方税法 asof {a} で「租税特別措置法…第二十九条の五」を含む文", None,
            f"{len(hs)} 文: " + "; ".join(f"{w[0]} {w[1]}条 {w[2]}項 {w[3] or ''}号" for w, s in hs))
    # §1.6
    check_quote("PS1.6-314_2", PS, "§1.6", "第314条の2第1項の柱書", c.para_head("314_2", 1),
                "市町村は、所得割の納税義務者が次の各号に掲げる者のいずれかに該当する場合には、それぞれ当該各号に定める金額をその者の前年の所得について算定した総所得金額、退職所得金額又は山林所得金額から控除するものとする。")

    # ---------------------------------------------------------------- PS §2 施行令
    q4852 = ("（総所得金額の算定の特例）第四十八条の五の二　法第三百十三条第二項の規定により同条第一項の総所得金額を算定する場合には、所得税法第三十五条第四項第一号中「第二条第一項第三十号（定義）に規定する合計所得金額」とあるのは「地方税法（昭和二十五年法律第二百二十六号）第二百九十二条第一項第十三号に規定する合計所得金額」と、租税特別措置法第四十一条の三の十一第四項第三号中「所得税法第二条第一項第三十四号に規定する扶養親族」とあるのは「地方税法（昭和二十五年法律第二百二十六号）第二百九十二条第一項第九号に規定する扶養親族」と、同項第四号中「所得税法第二条第一項第三十三号に規定する同一生計配偶者」とあるのは「地方税法第二百九十二条第一項第七号に規定する同一生計配偶者」と、同法第四十一条の十五の三第一項中「同条第四項（同法第百六十五条第一項において適用する場合を含む。）」とあるのは「地方税法第三百十三条第二項の規定によりその例によることとされる所得税法第三十五条第四項」と、「ついては、同法」とあるのは「ついては、地方税法施行令第四十八条の五の二の規定により読み替えられた同法」として、これらの規定の例によるものとする。")
    for a in ("2025-01-01", "2026-01-01", "2026-11-09", "2027-01-01"):
        r = L("chiho-rei", a)
        check_quote(f"PS2.1-48_5_2-{a}", PS, "§2.1", f"施行令第48条の5の2 の全文（見出しを含む。asof {a}）", r.article_text("48_5_2"), q4852, exact=True)
        t = r.article_text("7_10_5") or ""
        ok = all(x in t for x in ("法第三十二条第二項の規定により", "第二十三条第一項第十三号", "第二十三条第一項第九号", "第二十三条第一項第七号",
                                  "地方税法第三十二条第二項の規定によりその例によることとされる"))
        rec(f"PS2.1-7_10_5-{a}", PS, "§2.1", f"第7条の10の5 は第32条第2項・第23条第1項第13号・第9号・第7号を引く（asof {a}）", ok, t[:400])
    r = L("chiho-rei", "2026-11-09")
    (ex / "chiho-rei_2026-11-09_48_5_2-3_7_10_5_7_11.txt").write_text(
        "\n\n".join(f"## {n}\n{r.article_text(n)}" for n in ("48_5_2", "48_5_3", "7_10_5", "7_11")), encoding="utf-8")
    check_quote("PS2.1-48_5_3-1", PS, "§2.1", "第48条の5の3第1項（非居住者期間）の文", r.para_text("48_5_3", 1),
                "所得税法その他の所得税に関する法令の規定による同法第百六十五条及び所得税法施行令第二百五十八条の所得税の課税標準の計算の例")
    for n in ("48_5_3", "7_11"):
        t = r.para_text(n, 2) or ""
        rec(f"PS2.1-{n}-2", PS, "§2.1", f"第{n}条第2項が措法第41条の3の11・第41条の15の3 を読み替える", "第四十一条の三の十一" in t and "第四十一条の十五の三" in t, t[:300])
    # §2.2 版ごと
    r21 = L("chiho-rei", "2021-01-01")
    rec("PS2.2-2021-cap", PS, "§2.2", "asof 2021-01-01 の第48条の5の2 の見出しは「（非居住者期間を有する所得割の納税義務者の課税標準の算定）」",
        r21.caption("48_5_2") == "（非居住者期間を有する所得割の納税義務者の課税標準の算定）", str(r21.caption("48_5_2")))
    rec("PS2.2-2021-7_10_5", PS, "§2.2", "asof 2021-01-01 に第7条の10の5 はない", r21.article("7_10_5")[0] is None, str(r21.caption("7_10_5")))
    r24 = L("chiho-rei", "2024-12-31")
    t24 = r24.article_text("48_5_2") or ""
    rec("PS2.2-2024", PS, "§2.2", "asof 2024-12-31 の第48条の5の2 は「（総所得金額の算定の特例）」で措法「第四十一条の三の三」を引く",
        r24.caption("48_5_2") == "（総所得金額の算定の特例）" and "第四十一条の三の三" in t24 and "第四十一条の三の十一" not in t24, t24[:500])
    (ex / "chiho-rei_2024-12-31_48_5_2.txt").write_text(t24, encoding="utf-8")
    for a in ("2022-03-31", "2022-04-01", "2023-01-01"):
        rr = laws.get(("chiho-rei", a))
        if rr is None:
            rec(f"CS2-{a}", PS, "§2.2・未決 CS2", f"（担当が取っていない版）施行令 asof {a}", False, "取得できなかった")
            continue
        t = rr.article_text("48_5_2") or ""
        (ex / f"chiho-rei_{a}_48_5_2.txt").write_text(f"law_revision_id={rr.ri.get('law_revision_id')}\n{t}\n\n## 7_10_5\n{rr.article_text('7_10_5')}", encoding="utf-8")
        rec(f"CS2-{a}", PS, "§2.2・未決 CS2", f"（担当が取っていない版）施行令 asof {a} の第48条の5の2", None,
            f"law_revision_id={rr.ri.get('law_revision_id')} 見出し={rr.caption('48_5_2')} 第7条の10の5={'あり' if rr.article('7_10_5')[0] is not None else 'なし'} 本文={t[:700]}")
    # 改正附則（令和4年政令第133号・令和6年政令第136号）
    for a in ("2024-12-31", "2026-11-09"):
        rr = L("chiho-rei", a)
        sup = "re:^令和四年.*政令第一三三号$"
        t1 = rr.article_text("1", sup)
        check_quote(f"PS2.2-R4-133-1-{a}", PS, "§2.2", f"令和4年政令第133号 附則第1条「この政令は、令和四年四月一日から施行する。」（asof {a} の版に収録）",
                    t1, "この政令は、令和四年四月一日から施行する。")
        check_quote(f"PS2.2-R4-133-2-{a}", PS, "§2.2", f"同 附則第2条（asof {a}）", rr.article_text("2", sup),
                    "第一条の規定による改正後の地方税法施行令（以下「新令」という。）第七条の十の五及び第七条の十一第二項の規定は、令和四年度以後の年度分の個人の道府県民税について適用し、令和三年度分までの個人の道府県民税については、なお従前の例による。")
        check_quote(f"PS2.2-R4-133-7-{a}", PS, "§2.2", f"同 附則第7条（asof {a}）", rr.article_text("7", sup),
                    "新令第四十八条の五の二及び第四十八条の五の三第二項の規定は、令和四年度以後の年度分の個人の市町村民税について適用し、令和三年度分までの個人の市町村民税については、なお従前の例による。")
        sup6 = "re:^令和六年.*政令第一三六号$"
        t = rr.item_text("1", 1, 1, sup6) if rr.article("1", sup6)[0] is not None else None
        if t is None:
            t = rr.article_text("1", sup6)
        check_quote(f"PS2.2-R6-136-{a}", PS, "§2.2", f"令和6年政令第136号 附則第1条第1号（第7条の10の5 等の改正規定は令和7年1月1日施行。asof {a}）", t,
                    "第七条の十の五、第七条の十一第二項、第四十八条の五の二及び第四十八条の五の三第二項の改正規定…令和七年一月一日")
        if a == "2026-11-09":
            (ex / "chiho-rei_suppl_R4-133_R6-136.txt").write_text(
                f"## 令和4年政令第133号 附則\n" + "\n".join(f"第{n}条 {rr.article_text(n, sup)}" for n in ("1", "2", "7")) +
                f"\n\n## 令和6年政令第136号 附則第1条\n{rr.article_text('1', sup6)}", encoding="utf-8")
    # 令和4年政令第133号 の題名（改正履歴から）
    revs = json.loads((OUT / "revisions_chiho-rei.json").read_text(encoding="utf-8"))["revisions"]
    for num, label in ((r"令和四年.*政令第(百三十三|一三三)号", "令和4年政令第133号"), (r"令和六年.*政令第(百三十六|一三六)号", "令和6年政令第136号")):
        hit = [rv for rv in revs if re.search(num, rv.get("amendment_law_num") or "")]
        rec(f"PS2.2-rev-{label}", PS, "§2.2", f"{label} の題名・公布日・施行日（e-Gov の改正履歴）", None,
            json.dumps(hit[:4], ensure_ascii=False) if hit else "改正履歴に見つからない（番号の表記を確認）")

    # ---------------------------------------------------------------- PS §3 施行規則 第6条の8
    k = L("chiho-ki", "2026-11-09")
    rec("PS3-rid", PS, "§3", "施行規則の版 329M50000002023_20261101_508M60000008045", k.ri.get("law_revision_id") == "329M50000002023_20261101_508M60000008045", str(k.ri.get("law_revision_id")))
    (ex / "chiho-ki_2026-11-09_6_8.txt").write_text(str(k.article_text("6_8")), encoding="utf-8")
    rec("PS3-cap", PS, "§3", "施行規則第6条の8 の見出し（申告書の付記事項。事業税）", None, str(k.caption("6_8")))
    check_quote("PS3-head", PS, "§3", "第6条の8 の柱書", k.para_head("6_8", 1), "法第七十二条の五十五の二第三項の規定により申告書に付記しなければならない事項は、次に掲げる事項とする。")
    check_quote("PS3-1", PS, "§3", "第6条の8 第1号", k.item_text("6_8", 1, 1, head_only=True),
                "所得税法第二十六条第二項及び第二十七条第二項（…）の金額又は法第三十二条第二項の規定においてその例によるものとされる所得税法第二十六条第二項及び第二十七条第二項の規定により算定した金額（農業に係る金額を除くものとする。以下「事業所得等の金額」という。）のうちに次に掲げる金額を有する者にあつては、その金額")
    title, t = k.subitem_text("6_8", 1, 1, 4)
    rec("PS3-1-ni-title", PS, "§3", "第1号の4番目の細目の記号が「ニ」", title == "ニ", f"記号={title}")
    check_quote("PS3-1-ni", PS, "§3", "第1号ニ", t, "租税特別措置法第二十六条第一項の規定又は法第三十二条第二項の規定においてその例によるものとされる租税特別措置法第二十六条第一項の規定により算定した事業所得等の金額")
    check_quote("PS3-5", PS, "§3", "第5号", k.item_text("6_8", 1, 5), "租税特別措置法第二十五条の二に規定する青色申告特別控除の適用を受けた者にあつては、その旨")
    check_quote("PS3-6", PS, "§3", "第6号", k.item_text("6_8", 1, 6),
                "租税特別措置法第四十一条の四第一項及び第四十一条の四の二第一項の規定の適用を受けた者にあつては、所得税法第二十六条第二項の規定又は法第三十二条第二項の規定においてその例によるものとされる所得税法第二十六条第二項の規定により算定した不動産所得の金額")
    # 反証探し：施行規則の全文で「法第三十二条第二項」「法第三百十三条第二項」と措置法を一緒に書く文
    hs = [(w, s) for w, s in k.sents if ("法第三十二条第二項" in s or "法第三百十三条第二項" in s) and "租税特別措置法" in s]
    rec("PS3-scan", PS, "§3・M§5", "（担当が数えていない）施行規則の全文で「法第三十二条第二項」または「法第三百十三条第二項」と「租税特別措置法」を同じ文に含むもの", None,
        f"{len(hs)} 文: " + "; ".join(f"{w[0]} {w[1]}条 {w[2]}項 {w[3] or ''}号" for w, s in hs[:30]))

    # ---------------------------------------------------------------- PS §4 施行令 原始附則第18条第1項
    check_quote("PS4-fusoku18", PS, "§4", "施行令 原始附則第18条第1項", r.para_text("18", 1, "原始"),
                "法附則第三十五条の二第一項に規定する一般株式等に係る譲渡所得等の金額として政令で定めるところにより計算した金額は、…一般株式等の租税特別措置法第三十七条の十第一項に規定する譲渡…による事業所得、譲渡所得及び雑所得について所得税法その他の所得税に関する法令の規定（租税特別措置法施行令第二十五条の十二第十項から第十二項まで、第二十五条の十二の二第八項及び第九項並びに第二十六条の二十八の三第六項の規定を除く。以下この条から附則第十八条の六までにおいて同じ。）の例により計算した")

    # ---------------------------------------------------------------- PS §5 地方税法の附則
    c = L("chiho", "2026-11-09")
    rec("PS5-6-cap", PS, "§5", "原始附則第6条の見出し（肉用牛の売却による事業所得に係る道府県民税及び市町村民税の課税の特例）",
        c.caption("6", "原始") == "（肉用牛の売却による事業所得に係る道府県民税及び市町村民税の課税の特例）", str(c.caption("6", "原始")))
    check_quote("PS5-6-4", PS, "§5", "原始附則第6条第4項", c.para_text("6", 4, "原始"),
                "市町村は、昭和五十七年度から令和十二年度までの各年度分の個人の市町村民税に限り、所得割の納税義務者が前年中に租税特別措置法第二十五条第一項各号に掲げる売却の方法により…売却し、…当該事業所得に係る市町村民税の所得割の額として政令で定める額を免除するものとする。")
    rec("PS5-6-5", PS, "§5", "原始附則第6条第5項（免税対象飼育牛以外を含む場合の税額の特例）", None, (c.para_text("6", 5, "原始") or "なし")[:300])
    rec("PS5-4_5-cap", PS, "§5", "原始附則第4条の5 の見出し（特定一般用医薬品等購入費を支払つた場合の医療費控除の特例）",
        c.caption("4_5", "原始") == "（特定一般用医薬品等購入費を支払つた場合の医療費控除の特例）", str(c.caption("4_5", "原始")))
    check_quote("PS5-4_5-3", PS, "§5", "原始附則第4条の5第3項", c.para_text("4_5", 3, "原始"),
                "市町村は、平成三十年度から令和九年度までの各年度分の個人の市町村民税に限り、…第三百十四条の二第一項（第二号に係る部分に限る。）の規定による控除については、その者の選択により、")
    rec("PS5-4_5-41_17", PS, "§5", "原始附則第4条の5 が措法第41条の17 に対応する（条文の中に措法第41条の17 があるか）",
        "第四十一条の十七" in (c.article_text("4_5", "原始") or ""), "")

    # ---------------------------------------------------------------- PS §6 措置法
    for a in ("2026-11-09", "2026-12-01", "2027-01-01"):
        so = L("sochi", a)
        check_quote(f"PS6-1-{a}", PS, "§6", f"措法第1条（asof {a}）", so.article_text("1"),
                    "この法律は、当分の間、所得税、…その他の内国税を軽減し、若しくは免除し、若しくは還付し、又はこれらの税に係る納税義務、課税標準若しくは税額の計算、申告書の提出期限若しくは徴収につき、所得税法（昭和四十年法律第三十三号）、…の特例を設けることについて規定するものとする。")
        for n in ("25_2", "27", "29_4", "41_3_11", "41_4", "41_15_3", "26"):
            anc = so.ancestors(n) or []
            rec(f"PS6-chap-{n}-{a}", PS, "§6", f"措法第{n}条は本則「第二章　所得税法の特例」に属する（asof {a}）",
                bool(anc) and norm(anc[0]) == norm("第二章　所得税法の特例"), " / ".join(anc) + f" 見出し={so.caption(n)}")
    so = L("sochi", "2026-11-09")
    check_quote("PS6-25_2", PS, "§6", "措法第25条の2第1項", so.para_text("25_2", 1),
                "青色申告書を提出することにつき税務署長の承認を受けている個人のその承認を受けている年分（…）の不動産所得の金額、事業所得の金額又は山林所得の金額は、所得税法第二十六条第二項、第二十七条第二項又は第三十二条第三項の規定により計算した不動産所得の金額、事業所得の金額又は山林所得の金額から次に掲げる金額のうちいずれか低い金額を控除した金額とする。")
    check_quote("PS6-27-1109", PS, "§6", "措法第27条第1項（asof 2026-11-09）65万円", so.para_text("27", 1),
                "六十五万円（当該個人が給与所得を有する場合にあつては、六十五万円から所得税法第二十八条第二項に規定する給与所得控除額を控除した残額。")
    check_quote("PS6-27-1201", PS, "§6", "措法第27条第1項（asof 2026-12-01）69万円", L("sochi", "2026-12-01").para_text("27", 1),
                "六十九万円（当該個人が給与所得を有する場合にあつては、六十九万円から所得税法第二十八条第二項に規定する給与所得控除額を控除した残額")
    for a in ("2026-12-01", "2027-01-01"):
        check_quote(f"PS6-29_4-{a}", PS, "§6", f"措法第29条の4第1項（asof {a}）", L("sochi", a).para_text("29_4", 1),
                    "令和八年又は令和九年において、その年中の所得税法第二十八条第一項に規定する給与等…同項第一号の規定にかかわらず、七十四万円（当該収入金額が七十四万円に満たない場合には、当該収入金額に相当する金額）とする。")
    check_quote("PS6-41_3_11-2", PS, "§6", "措法第41条の3の11第2項", so.para_text("41_3_11", 2),
                "その年分の給与所得の金額（前項の規定の適用がある場合には、同項の規定による控除をした残額）から控除する。")
    t5 = so.para_text("41_3_11", 5) or ""
    rec("PS6-41_3_11-5", PS, "§6", "措法第41条の3の11第5項で所得税法第22条第2項第1号の「給与所得の金額」を読み替える",
        "所得税法第二十二条の規定の適用については、同条第二項第一号中「給与所得の金額」" in t5 and "給与所得の金額から租税特別措置法第四十一条の三の十一第一項又は第二項（所得金額調整控除）の規定による控除をした残額" in t5, t5[:400])
    t4 = so.para_text("41_3_11", 4) or ""
    rec("PS6-41_3_11-4", PS, "§6", "措法第41条の3の11第4項第3号・第4号に施行令が読み替える語（扶養親族・同一生計配偶者）がある",
        "所得税法第二条第一項第三十四号に規定する扶養親族" in t4 and "所得税法第二条第一項第三十三号に規定する同一生計配偶者" in t4, t4[:400])
    check_quote("PS6-41_4", PS, "§6", "措法第41条の4第1項", so.para_text("41_4", 1),
                "所得税法第六十九条第一項の規定その他の所得税に関する法令の規定の適用については、生じなかつたものとみなす。")
    t = so.para_text("41_15_3", 1) or ""
    rec("PS6-41_15_3-1", PS, "§6", "措法第41条の15の3第1項：65歳以上は所得税法第35条第4項第1号の「六十万円に」を「百十万円に」と読み替える",
        "「六十万円に」とあるのは「百十万円に」" in norm(t) and "六十五歳以上" in t, t[:400])
    t = so.para_text("41_15_3", 4) or ""
    rec("PS6-41_15_3-4", PS, "§6", "措法第41条の15の3第4項：65歳以上かの判定は「その年十二月三十一日」", "その年十二月三十一日" in t, t[:300])
    for n, cap in (("25_2", "（青色申告特別控除）"), ("27", "（家内労働者等の事業所得等の所得計算の特例）"), ("26", "（社会保険診療報酬の所得計算の特例）"),
                   ("41_3_11", "（所得金額調整控除）"), ("41_4", "（不動産所得に係る損益通算の特例）"), ("41_15_3", "（公的年金等控除の最低控除額等の特例）"),
                   ("41_17", None)):
        got = so.caption(n)
        rec(f"H2-cap-{n}", H, "H2・M§1", f"措法第{n}条の見出し = {cap}", (got == cap) if cap else None, str(got))
    s24 = laws.get(("sochi", "2024-12-31"))
    if s24:
        rec("H4-41_3_3-2024", H, "H4", "（反証探し）措法 asof 2024-12-31 で所得金額調整控除は第何条か（施行令は同じ日に第41条の3の3 を引く）", None,
            f"law_revision_id={s24.ri.get('law_revision_id')} 41の3の3={s24.caption('41_3_3')} 41の3の11={s24.caption('41_3_11')}")
    # 地方税法 第313条 第3項以下（H3 の5）
    t313 = {p: (c.para_text("313", p) or "") for p in range(3, 17)}
    found = {k2: [p for p, tx in t313.items() if k2 in tx] for k2 in ("青色事業専従者", "事業専従者", "純損失", "雑損失", "特定支出", "特定配当等", "特定株式等譲渡所得金額")}
    rec("H3-5", H, "H3 の5", "第313条第3項以下に青色事業専従者・事業専従者・純損失・雑損失の繰越・特定支出控除・特定配当等・特定株式等譲渡所得の除外がある",
        all(found.values()), json.dumps(found, ensure_ascii=False))

    # ---------------------------------------------------------------- M §3.2 数えたもの
    targets = {"第25条の2": "第二十五条の二", "第27条": "第二十七条", "第29条の4": "第二十九条の四", "第41条の3の11": "第四十一条の三の十一",
               "第41条の4": "第四十一条の四", "第41条の15の3": "第四十一条の十五の三"}
    expect = {  # 実測 §3.2 の表（形「租税特別措置法第…」の数, 「同法第…」の数）
        ("chiho", "2026-11-09"): {"第25条の2": (0, 0), "第27条": (0, 0), "第29条の4": (2, 0), "第41条の3の11": (0, 0), "第41条の4": (0, 0), "第41条の15の3": (0, 0)},
        ("chiho", "2027-01-01"): {"第25条の2": (0, 0), "第27条": (0, 0), "第29条の4": (0, 0), "第41条の3の11": (0, 0), "第41条の4": (0, 0), "第41条の15の3": (0, 0)},
        ("chiho-rei", "2026-11-09"): {"第25条の2": (0, 0), "第27条": (0, 0), "第29条の4": (0, 0), "第41条の3の11": (4, 0), "第41条の4": (0, 0), "第41条の15の3": (0, 4)},
        ("chiho-rei", "2027-01-01"): {"第25条の2": (0, 0), "第27条": (0, 0), "第29条の4": (0, 0), "第41条の3の11": (4, 0), "第41条の4": (0, 0), "第41条の15の3": (0, 4)},
    }
    for key, row in expect.items():
        lw = L(*key)
        main_s = [s for w, s in lw.sents if w[0] == "本則" and "租税特別措置法" in s]
        for lab, kan in targets.items():
            pat = re.compile(r"租税特別措置法(?:（[^）]*）)?" + re.escape(kan) + r"(?!の)")
            pat2 = re.compile(r"同法" + re.escape(kan) + r"(?!の)")
            n1 = sum(len(pat.findall(s)) for s in main_s)
            n2 = sum(len(pat2.findall(s)) for s in main_s)
            rec(f"M3.2-{key[0]}-{key[1]}-{lab}", M, "§3.2", f"{key[0]} {key[1]} 本則：措法{lab} を「租税特別措置法{kan}」の形で引く数={row[lab][0]}、「同法{kan}」の数={row[lab][1]}",
                (n1, n2) == row[lab], f"数え直し=({n1}, {n2})")
    c = L("chiho", "2026-11-09")
    so_s = [(w, s) for w, s in c.sents if "租税特別措置法" in s]
    nm = sum(1 for w, s in so_s if w[0] == "本則")
    na = sum(1 for w, s in so_s if w[0].startswith("附則"))
    rec("M3.2-477", M, "§3.2", "地方税法 2026-11-09 の全文で「租税特別措置法」を含む文は 477（本則 64、附則 413）", (len(so_s), nm, na) == (477, 64, 413),
        f"数え直し={len(so_s)}（本則 {nm}、附則 {na}、その他 {len(so_s) - nm - na}）")
    h25 = [(w, s) for w, s in so_s if re.search(r"第二十五条の二(?!の)", s) and re.search(r"租税特別措置法(?:（[^）]*）)?第二十五条の二(?!の)", s)]
    rec("M3.2-25_2", M, "§3.2", "地方税法で措法第25条の2 を引くのは平成4年の改正附則（みなし法人課税の経過措置）だけ",
        bool(h25) and all(re.fullmatch(r"附則\(平成四年.*法律第五号\)", w[0]) for w, s in h25), "; ".join(f"{w[0]} {w[1]}条 {w[2]}項" for w, s in h25))

    # ---------------------------------------------------------------- 反証探し：地方税法・施行令の全文で「七十四万円」「六十九万円」「給与所得控除」
    for key in (("chiho", "2026-11-09"), ("chiho", "2027-01-01"), ("chiho-rei", "2027-01-01")):
        lw = L(*key)
        for kw in ("七十四万円", "六十九万円", "給与所得控除", "六十五万円"):
            hs = [(w, s) for w, s in lw.sents if kw in s]
            rec(f"X-{key[0]}-{key[1]}-{kw}", H, "H1・H2（反証探し）", f"{key[0]} {key[1]} の全文で「{kw}」を含む文", None,
                f"{len(hs)} 文: " + "; ".join(f"{w[0]} {w[1]}条 {w[2]}項 {w[3] or ''}号" for w, s in hs[:20]))

    # ---------------------------------------------------------------- PDF
    wf = {f["name"]: f for f in wb["fetches"]}
    prevw = {  # 実測 §2.2 の表
        "soumu_ichiran04": (200, "2026-10-21", "ab72810a39d3c3a8"), "soumu_tsuchi_index": (404, None, None),
        "soumu_t_tsutatsu": (200, "2026-10-30", "5ce31c684eea6ba7"), "r8_kaisei_tsuchi": (200, "2026-04-16", "321af651108b58ab"),
        "r8_ryuiten": (200, "2026-01-23", "2a5b45ff6a6e221b"), "r8_gaiyo": (200, "2025-12-23", "0b2fa54af7eeb7aa"),
        "r8_houritsu_sansho": (200, "2026-03-31", "ce7390bbb7164cbd"), "toriatsukai_shichoson_zenbun": (200, "2026-05-07", "107ba94cd6bd4b5e"),
        "toriatsukai_dofuken_zenbun": (200, "2026-08-14", "b8c40110f3a48e8d"), "toriatsukai_shichoson_r8_honbun": (200, "2026-04-03", "357f9d5c385b928e"),
        "toriatsukai_shichoson_r8_betten1": (200, "2026-04-03", "d93f2fac00893cf6"), "r7_kaisei_tsuchi": (200, "2025-04-10", "b4bc06980e8831af"),
        "r7_ryuiten": (200, "2025-01-27", "b5607bdc39773d2f"), "h30_kaisei_tsuchi": (200, "2025-03-19", "665f7a97d51a42a6"),
        "h30_ryuiten": (200, "2025-01-27", "2dd91940bca42148"), "h30_gaiyo": (200, "2025-01-27", "659c3c07beedcd30"),
    }
    mon = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}

    def lmdate(s):
        m = re.search(r"(\d{1,2}) (\w{3}) (\d{4})", s or "")
        return f"{m.group(3)}-{mon[m.group(2)]:02d}-{int(m.group(1)):02d}" if m else None
    for name, (st, lm, sha) in prevw.items():
        f = wf.get(name, {})
        ok = f.get("status") == st and (lm is None or lmdate(f.get("last_modified")) == lm)
        if not ok and f.get("status") == st and (lmdate(f.get("last_modified")) or "") > "2026-11-09":
            ok = None  # 担当の取得（2026-11-09）の後で更新された。当時の Last-Modified は確かめられない
        rec(f"M2.2-{name}", M, "§2.2", f"{name} 状態={st} Last-Modified={lm}", ok,
            f"取り直し: 状態={f.get('status')} Last-Modified={f.get('last_modified')} SHA-256先頭={f.get('sha256', '')[:16]}"
            + ("" if sha is None else (" SHA 同じ" if f.get("sha256", "").startswith(sha) else " SHA 違う")))
    for name in ("egov_view_chiho", "egov_view_chiho_rei", "egov_view_chiho_ki", "egov_view_sochi"):
        f = wf.get(name, {})
        rec(f"PS-url-{name}", PS, "冒頭", f"法令の閲覧用 URL {f.get('url')} が開ける", f.get("status") == 200,
            f"状態={f.get('status')} robots={f.get('robots_allowed')} 最終URL={f.get('final_url')}")
    docs = {}
    for name, f in wf.items():
        if f.get("file", "").endswith(".pdf") and f.get("status") == 200:
            pages, meta = pdf_pages(wdl / f["file"])
            docs[name] = (Doc(pages) if pages else None, meta)
            if pages:
                (ex / f"pdf_{name}.txt").write_text("\n".join(f"=== p.{i} ===\n" + "\n".join(p) for i, p in enumerate(pages, 1)), encoding="utf-8")
    enc = {n: m.get("encrypted") for n, (d, m) in docs.items()}
    rec("M2.2-noenc", M, "§2.2", "PDF はすべて暗号なし", not any(enc.values()), json.dumps(enc, ensure_ascii=False))
    hs = docs.get("r8_houritsu_sansho", (None, {}))[1]
    rec("M2.2-sansho", M, "§2.2", "r8_houritsu_sansho は p.2・p.3 に文字がなく、/ToUnicode のない Type0 フォントが 17",
        hs.get("pages_without_text") == [2, 3] and hs.get("type0_without_tounicode") == 17, json.dumps(hs, ensure_ascii=False))
    others = {n: (m.get("pages_without_text"), m.get("type0_without_tounicode")) for n, (d, m) in docs.items() if n != "r8_houritsu_sansho"}
    rec("M2.2-others", M, "§2.2", "それ以外の12の PDF は全頁に文字があり、/ToUnicode のない Type0 フォントはない",
        all(not a and not b for a, b in others.values()) and len(others) == 12, json.dumps(others, ensure_ascii=False))

    def pq(cid, doc, sec, name, claim, quote, pages=None):
        d = docs.get(name, (None, None))[0]
        if d is None:
            rec(cid, doc, sec, claim, False, f"{name} を読めない")
            return
        fr = [norm(x) for x in quote.split("…") if len(norm(x)) >= 2]
        locs = [d.find(x) for x in fr]
        ok = all(locs)
        pg = sorted({p for l in locs if l for p in l})
        if ok and pages is not None:
            ok = set(pg) <= set(pages)
        miss = [x for x, l in zip(fr, locs) if not l]
        rec(cid, doc, sec, claim, ok, f"頁={pg}" + (f" 期待頁={pages}" if pages else "") + (f" 見つからない断片={miss[0][:80]}" if miss else ""))

    def pcount(cid, doc, sec, name, word, n):
        d = docs.get(name, (None, None))[0]
        got = d.count(word) if d else None
        rec(cid, doc, sec, f"{name} の全文で「{word}」は {n} 回", got == n if n is not None else None, f"数え直し={got}")

    S, D = "toriatsukai_shichoson_zenbun", "toriatsukai_dofuken_zenbun"
    rec("PS7.1-pages-s", PS, "§7.1", "取扱通知（市町村税）全文は 142頁", docs[S][1].get("pages") == 142, str(docs[S][1].get("pages")))
    rec("PS7.1-pages-d", PS, "§7.1", "取扱通知（道府県税）全文は 199頁", docs[D][1].get("pages") == 199, str(docs[D][1].get("pages")))
    pq("PS7.1-s-title", PS, "§7.1", S, "市町村税：平成22年4月1日 総税市第16号", "平成２２年４月１日…総税市第１６号")
    pq("PS7.1-s-last", PS, "§7.1", S, "市町村税：最終改正 令和8年4月1日 総税市第25号", "令和８年４月１日総税市第２５号")
    pq("PS7.1-d-title", PS, "§7.1", D, "道府県税：平成22年4月1日 総税都第16号", "平成２２年４月１日…総税都第１６号")
    pq("PS7.1-d-last", PS, "§7.1", D, "道府県税：最終改正 令和8年4月1日 総税都第15号", "令和８年４月１日総税都第１５号")
    pq("PS7.1-honbun-245_4", PS, "§7.1", "toriatsukai_shichoson_r8_honbun", "総税市第25号の本文に地方自治法第245条の4（技術的な助言）", "地方自治法…第２４５条の４")
    pq("PS7.1-honbun-25", PS, "§7.1", "toriatsukai_shichoson_r8_honbun", "総税市第25号の本文の番号", "総税市第２５号")
    pq("PS7.1-12", PS, "§7.1", S, "市町村税 第2章第2節 第3 の 12（p.36-37）",
       "１２　所得割の課税標準は、前年の所得について算定した総所得金額、退職所得金額及び山林所得金額とするものとされているが、総所得金額、退職所得金額又は山林所得金額の算定については、法又はこれに基づく政令で特別の定めをする場合を除くほか、それぞれ所得税法その他の所得税に関する法令の規定による所得税法第２２条第２項又は第３項の総所得金額、退職所得金額又は山林所得金額の計算の例によるものとされているものであること。したがって、収入金額の計算、必要経費の計算、損益の通算等については、原則として所得税の例によるものであること。ただし、同法第６０条の２から第６０条の４までの規定の例によらないものとする。",
       pages=[36, 37])
    pq("PS7.1-12-3", PS, "§7.1", S, "12(3) の柱書（p.37）", "次に掲げるものは、それぞれの規定により所得税法第２２条第２項の総所得金額から除かれているので、所得割の課税標準となる総所得金額には含まれないものであること。", pages=[37])
    for lab, q in (("ア", "ア租税特別措置法…第３条第１項に規定する一般利子等"), ("イ", "イ…第３条の３第１項に規定する国外一般公社債等の利子等"),
                   ("ウ", "ウ…第４条の４第１項に規定する勤労者財産形成貯蓄保険契約等の差益"),
                   ("ウ（訂正後）", "ウ租税特別措置法第４条の４第１項に規定する勤労者財産形成貯蓄保険契約等に基づき支払いを受ける差益"),
                   ("エ", "エ…第８条の２第１項に規定する私募公社債等運用投資信託等の収益の分配に係る配当等"),
                   ("オ", "オ…第８条の３第１項に規定する国外私募公社債等運用投資信託等の配当等"),
                   ("カ", "カ…第４１条の９第１項に規定する懸賞金付預貯金等の懸賞金等"), ("キ", "キ…第４１条の１０第１項に規定する給付補填金等"),
                   ("預金保険法", "預金保険法")):
        pq(f"PS7.1-12-3-{lab}", PS, "§7.1", S, f"12(3){lab}", q)
    pq("PS7.1-12-4", PS, "§7.1", S, "12(4)（p.38）肉用牛", "課税の特例の対象となる肉用牛の売却による事業所得は、総所得金額に算入されるものであること。（法附則６④・⑤）", pages=[38])
    pq("PS7.1-12-5", PS, "§7.1", S, "12(5)（p.38）",
       "所得税法第３５条第４項に規定する公的年金等控除額の算定の基礎となる同項第１号の公的年金等に係る雑所得以外の所得に係る合計所得金額については、個人の市町村民税における他の所得控除等と同様に、退職手当等（法第３２８条に規定する退職手当等に限る。）を含まない合計所得金額を用いること。（法３１３②、令４８の５の２、令４８の５の３②）", pages=[38])
    pq("PS7.1-12-6", PS, "§7.1", S, "12(6)（p.38）",
       "法又は法に基づく政令で特別の定めをする場合を除くほか所得税法その他の所得税に関する法令の規定による同法第１６５条及び同法施行令第２５８条の所得税の課税標準の計算の例によって算定するものであること。", pages=[38])
    d = docs[S][0]
    start12 = d.text.find(norm("１２所得割の課税標準は、前年の所得について算定した"))
    for lab, needle in (("(3)", "次に掲げるものは、それぞれの規定により所得税法第２２条第２項"), ("(4)", "課税の特例の対象となる肉用牛"),
                        ("(5)", "所得税の例により所得割の課税標準である総所得金額を算定する場合において、所得税法第３５条第４項"),
                        ("(6)", "前年中に所得税法第２条第１項第５号に規定する非居住者であった期間を有する者の所得割の課税標準")):
        i = d.text.find(norm(needle), max(start12, 0))
        want = "(" + "０１２３４５６７８９"[int(lab[1])] + ")"
        rec(f"PS7.1-num{lab}", PS, "§7.1", f"取扱通知（市町村税）12 の中で、該当の文の番号が {lab}", d.text[max(0, i - 3):i] == want if i >= 0 else False,
            f"頁={d.page_at(i) if i >= 0 else None} 直前={d.text[max(0, i - 12):i + 4] if i >= 0 else '見つからない'}")
    pq("PS7.1-ippan", PS, "§4・§7.1", S, "取扱通知（市町村税）一般株式等の項（p.92-93）の「所得税法その他の所得税に関する法令の規定（租税特別措置法施行令…を除く」",
       "所得税法その他の所得税に関する法令の規定（租税特別措置法施行令第２５条の１２", pages=[92, 93])
    pq("PS7.1-d8", PS, "§7.1", D, "道府県税 第2章第2節 第4 の 8（p.30）",
       "８　所得割の課税標準の基礎となる総所得金額、退職所得金額又は山林所得金額の計算及び所得控除の計算は、市町村民税の場合と全く同様であり、これと異なる計算を行うことはできないものであること。", pages=[30])
    for w in ("給与所得控除", "所得金額調整控除", "青色申告特別控除", "家内労働"):
        pcount(f"PS7.1-cnt-s-{w}", PS, "§7.1・M§3.2", S, w, 0)
    pcount("PS7.1-cnt-d-給与所得控除", PS, "§7.1", D, "給与所得控除", 0)
    # §7.2
    H30 = "h30_ryuiten"
    pq("PS7.2-date", PS, "§7.2", H30, "平成30年1月23日・事務連絡・4課", "平成３０年１月２３日")
    for kk in ("企画課", "都道府県税課", "市町村税課", "固定資産税課"):
        pq(f"PS7.2-ka-{kk}", PS, "§7.2", H30, f"発出者に {kk}", kk, pages=[1])
    for i, frag in enumerate(("「特定支出控除」、「青色申告特別控除」、「家内労働者等の事業所得等の所得計算の特例」及び「勤労学生（合計所得金額要件）」",
                              "所得税における見直しが、個人住民税にも適用となること",
                              "上記アからオまでの改正は、平成３３年度分以後の個人住民税から適用すること",
                              "給与所得控除、公的年金等控除及び所得金額調整控除に係る部分は、所得税に係る法令の規定が個人住民税にも適用となること")):
        pq(f"PS7.2-p6-{i}", PS, "§7.2", H30, f"p.6 の文の断片 {i + 1}", frag, pages=[6])
    pq("PS7.2-p1", PS, "§7.2", H30, "p.1「…地方税制に関する所要の法令案の作成を急いでいるところですが、さしあたり現段階における…留意事項等について、別紙のとおりお知らせする」",
       "法令案の作成を急いでいるところ…さしあたり現段階における…別紙のとおりお知らせ", pages=[1])
    pq("PS7.2-p5", PS, "§7.2", H30, "p.5 に給与所得控除・公的年金等控除の10万円引下げ、所得金額調整控除", "所得金額調整控除")
    d = docs[H30][0]
    for w in ("１０万円", "所得金額調整控除", "８５０万円"):
        rec(f"PS7.2-p5-{w}", PS, "§7.2", f"h30_ryuiten で「{w}」が出る頁", None, str(sorted({d.page_at(m.start()) for m in re.finditer(re.escape(norm(w)), d.text)})))
    K30 = "h30_kaisei_tsuchi"
    pq("PS7.2-k-date", PS, "§7.2", K30, "平成30年4月1日 総税企第50号", "総税企第５０号")
    pq("PS7.2-k-date2", PS, "§7.2", K30, "平成30年4月1日", "平成３０年４月１日")
    pq("PS7.2-k-daijin", PS, "§7.2", K30, "総務大臣", "総務大臣")
    pq("PS7.2-k-13", PS, "§7.2", K30, "十三 特記事項 1「…本年度改正における個人所得課税の見直しが平成３３年度分から、それぞれ適用される。」",
       "本年度改正における個人所得課税の見直しが平成３３年度分から、それぞれ適用される")
    pq("PS7.2-k-sanko", PS, "§7.2", K30, "参考の (2)（元の文書の引用「給与所得控除の上限額…を引き下げること。また、…」）",
       "給与所得控除の上限額…を引き下げること。また、年齢23歳未満の扶養親族や特別障害者である扶養親族等を有する者等には負担増が生じないよう措置すること。")
    pq("PS7.2-k-sanko-fix", PS, "§7.2", K30, "参考の (2)（訂正後の引用）",
       "(2)給与所得控除の上限額が適用される給与等の収入金額を８５０万円に、その上限額を１９５万円((1)による１０万円引下げを含む。)に引き下げること。また、年齢23歳未満の扶養親族や特別障害者である扶養親族等を有する者等には負担増が生じないよう措置すること。")
    # §7.3
    G8 = "r8_gaiyo"
    pq("PS7.3-g", PS, "§7.3", G8, "令和8年度地方税制改正(案)：給与所得控除の最低保障額を74万円（現行:65万円）に引き上げる",
       "給与所得控除の最低保障額を74万円（現行:65万円）に引き上げる")
    pq("PS7.3-g2", PS, "§7.3", G8, "※令和９年度分の個人住民税から適用（引上げ額９万円のうち、５万円は２年間の時限措置）",
       "令和９年度分の個人住民税から適用（引上げ額９万円のうち、５万円は２年間の時限措置）")
    pq("PS7.3-g-title", PS, "§7.3", G8, "題名「令和８年度地方税制改正(案)について」・令和7年12月", "令和８年度地方税制改正")
    pq("PS7.3-g-date", PS, "§7.3", G8, "令和7年12月（PDF の表記は「令和７年12月」）", "令和７年12月", pages=[1])
    R8 = "r8_ryuiten"
    pq("PS7.3-r-date", PS, "§7.3", R8, "令和8年1月21日", "令和８年１月２１日")
    pq("PS7.3-r-a", PS, "§7.3", R8, "p.2 ア(ア)「給与所得控除について、６５万円の最低保障額を６９万円に引き上げること。」", "給与所得控除について、６５万円の最低保障額を６９万円に引き上げること。", pages=[2])
    pq("PS7.3-r-i", PS, "§7.3", R8, "p.2 ア(イ)", "令和９年度分及び令和１０年度分の個人住民税に係る給与所得控除の最低保障額について、(ア)に加え、５万円引き上げること。", pages=[2])
    pq("PS7.3-r-i2", PS, "§7.3", R8, "イ「所得税における見直しに伴う所要の措置」", "所得税における見直しに伴う所要の措置")
    for w in ("６２万円", "８９万円"):
        pq(f"PS7.3-r-{w}", PS, "§7.3", R8, f"イに {w}", w)
    pq("PS7.3-r-note", PS, "§7.3", R8, "（注）「上記ア及びイの改正は、令和９年度分以後の個人住民税について適用することとしていること。」",
       "上記ア及びイの改正は、令和９年度分以後の個人住民税について適用することとしていること。")
    for w, n in (("二十九条の四", 0), ("２９条の４", 0), ("29条の4", 0), ("給与所得控除", 6), ("租税特別措置法", 1)):
        pcount(f"PS7.3-cnt-r-{w}", PS, "§7.3", R8, w, n)
    pcount("PS7.3-cnt-g-給与所得控除", M, "§3.4", G8, "給与所得控除", 2)
    for nm in (G8, "r8_kaisei_tsuchi", S, D):
        for w in ("二十九条の四", "２９条の４", "29条の4"):
            pcount(f"PS7.3-cnt-{nm}-{w}", PS, "§7.3", nm, w, 0)
    K8 = "r8_kaisei_tsuchi"
    pq("PS7.3-k-no", PS, "§7.3", K8, "令和8年4月1日 総税企第44号", "総税企第４４号")
    pq("PS7.3-k-date", PS, "§7.3", K8, "令和8年4月1日", "令和８年４月１日")
    pq("PS7.3-k-daijin", PS, "§7.3", K8, "総務大臣", "総務大臣")
    pq("PS7.3-k-1", PS, "§7.3", K8, "一 総括的事項（1）", "個人住民税のひとり親控除の額の引上げ等を行うこととした。")
    pcount("PS7.3-cnt-k-給与所得控除", PS, "§7.3", K8, "給与所得控除", 0)
    pq("PS7.3-k-iyaku", PS, "§7.3", K8, "特定一般用医薬品等購入費（法附則第四条の五関係）", "租税特別措置法第四十一条の十七第一項各号に掲げる期間内に…（法附則第四条の五関係）")
    d = docs[K8][0]
    rec("PS7.3-k-iyaku-n", PS, "§7.3", "総税企第44号で「法附則第四条の五関係」が出る回数（第一 道府県税・第二 市町村税の2回か）", None,
        str(d.count("法附則第四条の五関係")) + " 回、頁=" + str(sorted({d.page_at(m.start()) for m in re.finditer(norm("法附則第四条の五関係"), d.text)})))
    pq("PS7.3-k-gyu", PS, "§7.3", K8, "第二 1(9) 肉用牛",
       "肉用牛の売却による事業所得に係る課税の特例について、適用期限を令和十二年度分の個人の市町村民税まで延長する。（法附則第六条関係）")
    # 総税企第44号の第一・第二の項目番号を確かめるため、該当箇所の前の文字列を出す
    for needle in ("租税特別措置法第四十一条の十七第一項各号に掲げる期間内に", "肉用牛の売却による事業所得に係る課税の特例について、適用期限を令和十二年度分の個人の市町村民税"):
        for m in re.finditer(re.escape(norm(needle)), d.text):
            rec("PS7.3-k-ctx", PS, "§7.3", f"総税企第44号の「{needle[:20]}…」の前の文字列（項目番号の確認）", None,
                f"頁={d.page_at(m.start())} 前={d.text[max(0, m.start() - 160):m.start()]}")

    pq("H2-sochi-kouzuru", H, "H2", R8, "（H2 の「措置を講ずる」）留意事項の① 給与所得控除及びひとり親控除の見直し等について、次の措置を講ずることとしていること",
       "個人住民税における給与所得控除及びひとり親控除の見直し等について、次…の措置を講ずることとしていること")

    # ---------------------------------------------------------------- 追加：第72条の49の12 の見出し、所得税法第60条の2〜第60条の4 の見出し
    c = L("chiho", "2026-11-09")
    rec("PS1.4-cap", PS, "§1.4", "第72条の49の12 の見出し（個人の事業税の所得）", None, str(c.caption("72_49_12")))
    xp = OUT / "fetch_egov_extra.json"
    if xp.exists():
        xl = json.loads(xp.read_text(encoding="utf-8"))
        for f in xl["fetches"]:
            if f["short"] == "shotoku" and f["status"] == 200:
                sh = Law(ROOT / xl["download_dir"] / f["file"])
                caps = {n: sh.caption(n) for n in ("60_2", "60_3", "60_4")}
                rec("PS1.1-60", PS, "§1.1", "所得税法第60条の2〜第60条の4 は国外転出時課税など（見出し）", None,
                    f"law_revision_id={sh.ri.get('law_revision_id')} " + json.dumps(caps, ensure_ascii=False))
    # 未決 CS3：地方税法 2027-01-01 版の 令和8年法律第2号 の附則で、第292条（第23条）・措法第29条の4／第29条の5 を書く文
    c27 = L("chiho", "2027-01-01")
    hs = [(w, s) for w, s in c27.sents if w[0].startswith("附則(令和八年") and ("第二十九条の五" in s or "第二十九条の四" in s or "第二百九十二条第一項第六号" in s)]
    rec("CS3-suppl", H, "未決 CS3", "（未決の確認）地方税法 asof 2027-01-01 の令和8年の改正附則で、措法第29条の4・第29条の5 または第292条第1項第6号を書く文", None,
        f"{len(hs)} 文: " + " ／ ".join(f"{w[0]} {w[1]}条 {w[2]}項 {w[3] or ''}号：{s[:200]}" for w, s in hs[:8]))
    revc = json.loads((OUT / "revisions_chiho.json").read_text(encoding="utf-8"))["revisions"]
    rec("CS3-rev-chiho", H, "未決 CS3", "地方税法の改正履歴（2025-01-01 以後）のうち 2026-11-01〜2027-01-01 の版", None,
        json.dumps([rv for rv in revc if (rv.get("law_revision_id") or "")[16:24] >= "20261101" and (rv.get("law_revision_id") or "")[16:24] <= "20270101"],
                   ensure_ascii=False)[:1500])
    revs_s = json.loads((OUT / "revisions_sochi.json").read_text(encoding="utf-8"))["revisions"]
    rec("CS3-rev-sochi", H, "未決 CS3", "措置法の改正履歴のうち 2026-11-01〜2027-01-01 の版", None,
        json.dumps([rv for rv in revs_s if (rv.get("law_revision_id") or "")[16:24] >= "20261101" and (rv.get("law_revision_id") or "")[16:24] <= "20270101"],
                   ensure_ascii=False)[:1500])

    # CS2：令和4年政令第133号の制定時（asof 2022-04-01）の第48条の5の2・第7条の10の5 は asof 2024-12-31 の文と同じか
    r22, r24 = L("chiho-rei", "2022-04-01"), L("chiho-rei", "2024-12-31")
    for n in ("48_5_2", "7_10_5"):
        a22, a24 = r22.article_text(n), r24.article_text(n)
        rec(f"CS2-same-{n}", PS, "§2.2・未決 CS2", f"施行令第{n}条：asof 2022-04-01（令和4年政令第133号の制定時）と asof 2024-12-31 の文が同じ（措法第41条の3の3 を引く）",
            a22 is not None and norm(a22) == norm(a24 or "") and "租税特別措置法第四十一条の三の三第四項第三号" in a22, (a22 or "なし")[:200])
    r2203 = L("chiho-rei", "2022-03-31")
    hs = [(w, s2) for w, s2 in r2203.sents if w[0] == "本則" and "第四十一条の三の三" in s2]
    rec("CS2-2022-03-31-refs", PS, "未決 CS2", "施行令 asof 2022-03-31 の本則で措法「第四十一条の三の三」を含む文（読替えがあったか）", None,
        f"{len(hs)} 文: " + "; ".join(f"{w[1]}条 {w[2]}項" for w, s2 in hs))
    # H4：措法 asof 2024-12-31 の第41条の3の3〜第41条の3の11 の見出しと、令和6年法律第8号の附則で第41条の3の3 を書く文
    s24 = L("sochi", "2024-12-31")
    caps = {n: s24.caption(n) for n in ("41_3_3", "41_3_4", "41_3_10", "41_3_11")}
    rec("H4-sochi-2024-caps", H, "H4", "措法 asof 2024-12-31 の第41条の3の3・の4・の10・の11 の見出し", None, json.dumps(caps, ensure_ascii=False))
    sup6l = "re:^令和六年.*法律第八号$"
    for it in range(1, 12):
        tt = s24.item_text("1", 1, it, sup6l)
        if tt and "第四十一条の三の十一とする" in tt:
            rec(f"H4-sochi-2024-suppl1-{it}", H, "H4", f"令和6年法律第8号 附則第1条第{it}号（第41条の3の3 を第41条の3の11 とする改正規定を含む）の号の柱書（施行日）と末尾", None,
                f"柱書={s24.item_text('1', 1, it, sup6l, head_only=True)} ／ 末尾={tt[-120:]}")
    hs = [(w, s2) for w, s2 in s24.sents if re.match(r"附則\(令和六年.*法律第八号\)", w[0]) and "第四十一条の三の三" in s2]
    rec("H4-sochi-2024-suppl", H, "H4", "措法 asof 2024-12-31 の令和6年法律第8号の附則で「第四十一条の三の三」を書く文（繰下げの施行日）", None,
        f"{len(hs)} 文: " + " ／ ".join(f"{w[1]}条 {w[2]}項 {w[3] or ''}号：{s2[:260]}" for w, s2 in hs[:6]))
    # CS3：令和8年法律第2号の附則第1条（柱書・第2号）
    c27 = L("chiho", "2027-01-01")
    sup8 = "re:^令和八年.*法律第二号$"
    rec("CS3-suppl-1", H, "未決 CS3", "地方税法 asof 2027-01-01 の令和8年法律第2号 附則第1条の柱書と第2号（第292条第1項第6号の改正規定の施行日）", None,
        f"柱書={c27.para_head('1', 1, sup8)} ／ 第2号の末尾={(c27.item_text('1', 1, 2, sup8) or '')[-200:]}")
    hs = [(w, s2) for w, s2 in c27.sents if re.match(r"附則\(令和八年.*法律第二号\)", w[0]) and "退職手当等" in s2]
    rec("CS3-suppl-taishoku", H, "未決 CS3", "令和8年法律第2号の附則で「退職手当等」を書く文（経過措置があるか）", None,
        f"{len(hs)} 文: " + " ／ ".join(f"{w[1]}条 {w[2]}項 {w[3] or ''}号：{s2[:200]}" for w, s2 in hs[:6]))
    s1201 = L("sochi", "2026-12-01")
    hs = [(w, s2) for w, s2 in s1201.sents if re.match(r"附則\(令和八年.*法律第一二号\)", w[0]) and ("地方税法" in s2)]
    rec("CS3-sochi-suppl-chiho", H, "未決 CS3", "措法 asof 2026-12-01 の令和8年法律第12号の附則で「地方税法」を書く文", None,
        f"{len(hs)} 文: " + " ／ ".join(f"{w[1]}条 {w[2]}項 {w[3] or ''}号：{s2[:200]}" for w, s2 in hs[:6]))

    # ---------------------------------------------------------------- 出力
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "checks.json").write_text(json.dumps(RESULTS, ensure_ascii=False, indent=1), encoding="utf-8")
    n = {k3: sum(1 for r3 in RESULTS if r3["result"] == k3) for k3 in ("OK", "NG", "NG(取り出し順)", "INFO")}
    lines = ["# R3X chiho-sochi 検証の結果", "", f"- e-Gov の取得：{eg['download_dir']}（{eg['run_at']}）", f"- Web の取得：{wb['download_dir']}（{wb['run_at']}）",
             f"- OK {n['OK']}、NG {n['NG']}、NG(取り出し順) {n['NG(取り出し順)']}、INFO {n['INFO']}（INFO は判定しない記録）", "", "| ID | 文書 | 節 | 主張 | 結果 | 詳細 |", "|---|---|---|---|---|---|"]
    for r3 in RESULTS:
        lines.append("| " + " | ".join(str(r3[k3]).replace("|", "｜").replace("\n", " ")[:600] for k3 in ("id", "doc", "section", "claim", "result", "detail")) + " |")
    (OUT / "checks.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("OK", n, flush=True)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "fetch-egov":
        fetch_egov()
    elif mode == "fetch-egov-extra":
        fetch_egov_extra()
    elif mode == "fetch-web":
        fetch_web()
    elif mode == "check":
        check()
    else:
        print(__doc__)
        sys.exit(2)

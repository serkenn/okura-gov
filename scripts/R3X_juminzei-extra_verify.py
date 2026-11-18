"""R3X juminzei-extra 検証（反証役）：家屋敷課税・配当割額等の控除・住宅借入金等特別税額控除の文書に書かれた
条番号・項番号・号番号・数値・日付・URL を、一次情報を取り直して、担当のスクリプト・出力に頼らずに確かめる。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_juminzei-extra_verify.py
      取得（e-Gov 法令API v2・総務省・自治体）→ 検査。ダウンロード先は新しい空のディレクトリ
      .work/downloads/<ts>_R3X_juminzei-extra_verify_laws/ と .work/downloads/<ts>_R3X_juminzei-extra_verify_web/
  ...R3X_juminzei-extra_verify.py --use <laws のディレクトリ> <web のディレクトリ>
      取得をせず、前に取得したものを読んで検査だけをやり直す（ネットワーク不要）。

- 担当のスクリプト（R3X_juminzei-extra_*.py）は import も実行もしない。e-Gov の JSON の読み方は
  scripts/R1_egov_articles.py・scripts/IMPL_kyuyo_fetch.py を参考に書き直した。PDF の文字の取り出しは自前で書いた
  （担当の _pdftext.py とは別の実装。xref を使わず、ファイルの中の obj と ObjStm を全部読み、頁木をたどり、ToUnicode で文字にする）。
- 担当の検査は「条の全体に文字列が含まれるか」で、項・号の番号は機械的に確かめていない。この検査は **項・号の単位** で文字列を探す。
- ダウンロードしたものは信頼できないデータ。ダウンロード先の中では何も実行しない。このスクリプトはパスを受け取って読むだけ。
  zlib の展開には上限（64MiB）をつける。リクエストの間は 1.5 秒。User-Agent は okura-gov-research/0.1。Web はホストごとに robots.txt を読む。
- 出力：scripts/results/R3X_juminzei-extra_verify/
    fetch_log.json   取得の記録（URL、状態、Last-Modified、バイト数、SHA-256、e-Gov の revision_info）
    checks.json      検査ごとの結果（ID、文書の箇所、期待、結果、見つかった場所）
    evidence.md      検査の結果を人が読む形にしたもの（見つかった文の抜粋つき）
    cases.md         計算例の再計算（文書の数値と照合）
  PDF の全文は書き出さない（見つかった箇所の前後だけを evidence.md に残す）。
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
from fractions import Fraction as Fr

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "results" / "R3X_juminzei-extra_verify"
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
SLEEP = 1.5
MAXOUT = 64 * 1024 * 1024

# ---------------------------------------------------------------- 取得の対象
LAWS = [
    # (略称, law_id, [asof...])
    # 2021-12-31・2022-04-01・2023-01-01 は、令和4年法律第1号の前後で附則第5条の4の2 がどう変わったかを見るため（H3-2 の未決の材料）
    ("chiho", "325AC0000000226", ["2021-12-31", "2022-04-01", "2023-01-01", "2025-01-01", "2026-01-01", "2026-04-01", "2026-11-09",
                                  "2027-01-01", "2028-01-01", "2030-01-01"]),
    ("chiho-rei", "325CO0000000245", ["2026-01-01", "2026-11-09", "2027-01-01"]),
    ("chiho-kisoku", "329M50000002023", ["2026-01-01", "2026-11-09", "2027-01-01"]),
    # 2025 年の3版は、令和7年中の支払（令和8年度分）に効く措法第8条の4第1項第1号の文言を見るため（［法令］§4-6）
    ("sochi", "332AC0000000026", ["2025-01-01", "2025-06-30", "2025-12-31", "2026-11-09"]),
    ("shotoku", "340AC0000000033", ["2026-01-01"]),
    ("shinrin", "431AC0000000003", ["2026-11-09"]),
]
TITLE_SEARCH = ["地方税法施行規則", "森林環境税及び森林環境譲与税に関する法律"]
WEB = [
    ("shichoson", "https://www.soumu.go.jp/main_content/001071661.pdf"),
    ("dofuken", "https://www.soumu.go.jp/main_content/001087182.pdf"),
    ("kaisei_tsuchi", "https://www.soumu.go.jp/main_content/001069033.pdf"),
    ("r8_houritsu", "https://www.soumu.go.jp/main_content/001066281.pdf"),
    ("ichiran04", "https://www.soumu.go.jp/main_sosiki/jichi_zeisei/czaisei/czaisei_seido/ichiran04.html"),
    ("soumu_juutaku_loan", "https://www.soumu.go.jp/main_sosiki/jichi_zeisei/czaisei/czaisei_seido/090929.html"),
    ("suginami_juutaku", "https://www.city.suginami.tokyo.jp/s028/2058.html"),
    ("funabashi_ieyashiki", "https://www.city.funabashi.lg.jp/kurashi/zei/007/001/p108828.html"),
    ("kumamoto_ieyashiki", "https://www.city.kumamoto.jp/kiji003367/index.html"),
    ("kagoshima_ieyashiki", "https://www.city.kagoshima.lg.jp/soumu/zeimu/shiminzei/ieyasiki.html"),
    ("meguro_kabu", "https://www.city.meguro.tokyo.jp/zeimu/kurashi/juuminzei/jyoujyoukabusikitou.html"),
]


def http_get(url, accept="*/*"):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            body, st, hd, final = r.read(), r.status, dict(r.headers), r.geturl()
    except urllib.error.HTTPError as e:
        body, st, hd, final = e.read(), e.code, dict(e.headers or {}), url
    time.sleep(SLEEP)
    return st, body, hd, final


def sha(b):
    return hashlib.sha256(b).hexdigest()


def fetch_all():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl_laws = ROOT / ".work" / "downloads" / f"{ts}_R3X_juminzei-extra_verify_laws"
    dl_web = ROOT / ".work" / "downloads" / f"{ts}_R3X_juminzei-extra_verify_web"
    dl_laws.mkdir(parents=True, exist_ok=False)
    dl_web.mkdir(parents=True, exist_ok=False)
    log = {"run_at": ts, "dl_laws": str(dl_laws.relative_to(ROOT)), "dl_web": str(dl_web.relative_to(ROOT)), "laws": [], "titles": [], "web": [], "robots": {}}
    for title in TITLE_SEARCH:
        url = f"{API}/laws?" + urllib.parse.urlencode({"law_title": title, "response_format": "json"})
        st, body, hd, _ = http_get(url, "application/json")
        name = f"title_{hashlib.sha1(title.encode()).hexdigest()[:8]}.json"
        (dl_laws / name).write_bytes(body)
        log["titles"].append({"title": title, "url": url, "status": st, "saved": name, "sha256": sha(body)})
    for short, law_id, asofs in LAWS:
        for asof in asofs:
            url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
            st, body, hd, _ = http_get(url, "application/json")
            name = f"{short}_{asof}.json"
            (dl_laws / name).write_bytes(body)
            ent = {"short": short, "law_id": law_id, "asof": asof, "url": url, "status": st, "bytes": len(body), "sha256": sha(body), "saved": name}
            if st == 200:
                try:
                    ri = json.loads(body).get("revision_info") or {}
                    li = json.loads(body).get("law_info") or {}
                    ent.update({k: ri.get(k) for k in ("law_revision_id", "amendment_law_num", "amendment_enforcement_date", "current_revision_status", "law_title")})
                    ent["law_num"] = li.get("law_num")
                except Exception as e:  # noqa
                    ent["parse_error"] = repr(e)
            log["laws"].append(ent)
            print("law", short, asof, st, len(body), flush=True)
    robots = {}
    for name, url in WEB:
        host = urllib.parse.urlsplit(url).netloc
        if host not in robots:
            rurl = f"https://{host}/robots.txt"
            st, body, hd, _ = http_get(rurl, "text/plain")
            rp = urllib.robotparser.RobotFileParser()
            if st == 200:
                rp.parse(body.decode("utf-8", "replace").splitlines())
            else:
                rp.parse([])
            robots[host] = (st, rp)
            log["robots"][host] = st
        st_r, rp = robots[host]
        ok = rp.can_fetch(UA, url)
        ent = {"name": name, "url": url, "robots_status": st_r, "robots_allowed": ok}
        if ok:
            st, body, hd, final = http_get(url)
            ext = ".pdf" if body[:5] == b"%PDF-" else ".html"
            (dl_web / (name + ext)).write_bytes(body)
            ent.update({"status": st, "final_url": final, "content_type": hd.get("Content-Type"), "last_modified": hd.get("Last-Modified"),
                        "bytes": len(body), "sha256": sha(body), "saved": name + ext})
        log["web"].append(ent)
        print("web", name, ent.get("status"), ent.get("bytes"), flush=True)
    return dl_laws, dl_web, log


# ---------------------------------------------------------------- e-Gov の JSON
def txt(n):
    if isinstance(n, str):
        return n
    if n.get("tag") == "Rt":
        return ""
    return "".join(txt(c) for c in n.get("children", []))


def N(s):
    """比較用：空白（全角を含む）と改行を除く。"""
    return re.sub(r"[\s\u3000]+", "", s)


class Law:
    def __init__(self, path):
        d = json.loads(pathlib.Path(path).read_bytes())
        self.ri = d.get("revision_info") or {}
        self.root = d["law_full_text"]
        self.main = None
        self.suppl = []  # (AmendLawNum or None, node)
        self._index()

    def _index(self):
        def walk(n):
            if not isinstance(n, dict):
                return
            t = n.get("tag")
            if t == "MainProvision":
                self.main = n
                return
            if t == "SupplProvision":
                self.suppl.append(((n.get("attr") or {}).get("AmendLawNum"), n))
                return
            for c in n.get("children", []):
                walk(c)
        walk(self.root)

    @staticmethod
    def _articles(node):
        out = []

        def walk(n):
            if not isinstance(n, dict):
                return
            if n.get("tag") == "Article":
                out.append(n)
                return
            for c in n.get("children", []):
                walk(c)
        walk(node)
        return out

    def part(self, where):
        """where: 'main' / 'orig'（原始附則）/ 改正法令番号（AmendLawNum）。"""
        if where == "main":
            return [self.main]
        if where == "orig":
            return [n for a, n in self.suppl if a is None]
        return [n for a, n in self.suppl if a == where]

    def article(self, where, num):
        hits = []
        for p in self.part(where):
            for a in self._articles(p):
                if (a.get("attr") or {}).get("Num") == num:
                    hits.append(a)
        return hits

    def all_articles(self, where):
        out = []
        for p in self.part(where):
            out.extend(self._articles(p))
        return out


def child(n, tag, num):
    for c in n.get("children", []):
        if isinstance(c, dict) and c.get("tag") == tag and (c.get("attr") or {}).get("Num") == str(num):
            return c
    return None


def para_of(art, p):
    return child(art, "Paragraph", p)


def item_of(par, i):
    return child(par, "Item", i)


def caption(art):
    for c in art.get("children", []):
        if isinstance(c, dict) and c.get("tag") == "ArticleCaption":
            return txt(c)
    return ""


def para_main_sentence(par):
    """項の本文（号を除く）。"""
    return "".join(txt(c) for c in par.get("children", []) if isinstance(c, dict) and c.get("tag") == "ParagraphSentence")


def suppl_paragraphs(law, amend_num):
    """改正附則の項：[(条番号 or None, 項番号, テキスト)]"""
    out = []
    for p in law.part(amend_num):
        for c in p.get("children", []):
            if not isinstance(c, dict):
                continue
            if c.get("tag") == "Paragraph":
                out.append((None, (c.get("attr") or {}).get("Num"), txt(c)))
        for a in Law._articles(p):
            an = (a.get("attr") or {}).get("Num")
            for c in a.get("children", []):
                if isinstance(c, dict) and c.get("tag") == "Paragraph":
                    out.append((an, (c.get("attr") or {}).get("Num"), txt(c)))
    return out


# ---------------------------------------------------------------- PDF（自前の最小の実装）
WS = b" \t\r\n\x0c\x00"
DL = b"()<>[]{}/%"


class Name(str):
    pass


class Ref(tuple):
    pass


class Op(str):
    pass


def _skip(b, i):
    n = len(b)
    while i < n:
        c = b[i]
        if c in WS:
            i += 1
        elif c == 0x25:  # %
            while i < n and b[i] not in b"\r\n":
                i += 1
        else:
            break
    return i


def _lit(b, i):
    # b[i] == '('
    i += 1
    depth, out = 1, bytearray()
    esc = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12, ord("("): 40, ord(")"): 41, ord("\\"): 92}
    while i < len(b):
        c = b[i]
        if c == 0x5C:
            i += 1
            d = b[i]
            if d in esc:
                out.append(esc[d]); i += 1
            elif 0x30 <= d <= 0x37:
                j = i
                while j < len(b) and j < i + 3 and 0x30 <= b[j] <= 0x37:
                    j += 1
                out.append(int(b[i:j], 8) & 0xFF); i = j
            elif d in b"\r\n":
                i += 1
                if d == 13 and i < len(b) and b[i] == 10:
                    i += 1
            else:
                out.append(d); i += 1
            continue
        if c == 0x28:
            depth += 1
        elif c == 0x29:
            depth -= 1
            if depth == 0:
                return bytes(out), i + 1
        out.append(c); i += 1
    return bytes(out), i


def parse_obj(b, i):
    i = _skip(b, i)
    if i >= len(b):
        return None, i
    c = b[i]
    if b.startswith(b"<<", i):
        i += 2
        d = {}
        while True:
            i = _skip(b, i)
            if b.startswith(b">>", i):
                return d, i + 2
            if i >= len(b):
                return d, i
            k, i = parse_obj(b, i)
            v, i = parse_obj(b, i)
            d[str(k)] = v
    if c == 0x5B:  # [
        i += 1
        arr = []
        while True:
            i = _skip(b, i)
            if i >= len(b) or b[i] == 0x5D:
                return arr, i + 1
            v, i = parse_obj(b, i)
            arr.append(v)
    if c == 0x28:
        return _lit(b, i)
    if c == 0x3C:  # <hex>
        j = b.index(b">", i)
        h = re.sub(rb"\s", b"", b[i + 1:j])
        if len(h) % 2:
            h += b"0"
        return bytes.fromhex(h.decode()), j + 1
    if c == 0x2F:  # /name
        j = i + 1
        while j < len(b) and b[j] not in WS and b[j] not in DL:
            j += 1
        nm = re.sub(rb"#([0-9A-Fa-f]{2})", lambda m: bytes([int(m.group(1), 16)]), b[i + 1:j])
        return Name(nm.decode("latin-1")), j
    j = i
    while j < len(b) and b[j] not in WS and b[j] not in DL:
        j += 1
    if j == i:
        return Op(chr(b[i])), i + 1
    tok = b[i:j].decode("latin-1")
    if re.fullmatch(r"[+-]?\d+", tok):
        m = re.match(rb"\s+(\d+)\s+R(?![A-Za-z])", b[j:j + 24])
        if m:
            return Ref((int(tok), int(m.group(1)))), j + m.end()
        return int(tok), j
    if re.fullmatch(r"[+-]?(\d+\.?\d*|\.\d+)", tok):
        return float(tok), j
    if tok == "true":
        return True, j
    if tok == "false":
        return False, j
    if tok == "null":
        return None, j
    return Op(tok), j


def inflate(data):
    d = zlib.decompressobj()
    out = d.decompress(data, MAXOUT)
    if d.unconsumed_tail:
        raise ValueError("展開の上限を超えた")
    return out


class PDF:
    def __init__(self, data):
        self.data = data
        self.objs = {}
        for m in re.finditer(rb"(?<![0-9])(\d+)\s+(\d+)\s+obj\b", data):
            num = int(m.group(1))
            try:
                v, j = parse_obj(data, m.end())
            except Exception:
                continue
            k = _skip(data, j)
            stream = None
            if data.startswith(b"stream", k):
                s = k + 6
                if data[s:s + 2] == b"\r\n":
                    s += 2
                elif data[s:s + 1] in (b"\n", b"\r"):
                    s += 1
                ln = v.get("Length") if isinstance(v, dict) else None
                if isinstance(ln, int) and data[s + ln:s + ln + 12].lstrip().startswith(b"endstream"):
                    stream = data[s:s + ln]
                else:
                    e = data.find(b"endstream", s)
                    stream = data[s:e].rstrip(b"\r\n")
            self.objs[num] = (v, stream)
        for num, (v, st) in list(self.objs.items()):
            if isinstance(v, dict) and v.get("Type") == "ObjStm" and st is not None:
                raw = self.decode(v, st)
                n, first = v["N"], v["First"]
                hdr = raw[:first].split()
                for k in range(n):
                    on, off = int(hdr[2 * k]), int(hdr[2 * k + 1])
                    if on in self.objs:
                        continue
                    o, _ = parse_obj(raw, first + off)
                    self.objs[on] = (o, None)

    def r(self, v):
        while isinstance(v, Ref):
            v = self.objs.get(v[0], (None, None))[0]
        return v

    def decode(self, d, st):
        f = self.r(d.get("Filter"))
        fl = f if isinstance(f, list) else ([f] if f else [])
        for x in fl:
            if x == "FlateDecode":
                st = inflate(st)
            else:
                return None
        return st

    def stream_of(self, ref):
        v, st = self.objs.get(ref[0], (None, None))
        if st is None:
            return b""
        return self.decode(v, st) or b""

    def pages(self):
        cat = None
        for v, _ in self.objs.values():
            if isinstance(v, dict) and v.get("Type") == "Catalog":
                cat = v
        out = []

        def walk(node, inh):
            node = self.r(node)
            res = node.get("Resources", inh)
            if node.get("Type") == "Pages":
                for k in self.r(node.get("Kids")) or []:
                    walk(k, res)
            else:
                out.append((node, self.r(res) or {}))
        walk(cat["Pages"], None)
        return out

    def font_decoder(self, fref):
        f = self.r(fref)
        if not isinstance(f, dict):
            return (1, {}, "latin-1")
        two = f.get("Subtype") == "Type0"
        cmap = {}
        tu = f.get("ToUnicode")
        if isinstance(tu, Ref):
            cm = self.stream_of(tu)
            for blk in re.findall(rb"beginbfchar(.*?)endbfchar", cm, re.S):
                for a, b2 in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", blk):
                    cmap[int(a, 16)] = bytes.fromhex(b2.decode()).decode("utf-16-be", "replace")
            for blk in re.findall(rb"beginbfrange(.*?)endbfrange", cm, re.S):
                for a, z, rest in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<[0-9A-Fa-f]*>|\[[^\]]*\])", blk):
                    lo, hi = int(a, 16), int(z, 16)
                    if rest.startswith(b"["):
                        for k, h in enumerate(re.findall(rb"<([0-9A-Fa-f]*)>", rest)):
                            cmap[lo + k] = bytes.fromhex(h.decode()).decode("utf-16-be", "replace")
                    else:
                        base = bytes.fromhex(rest[1:-1].decode())
                        bi = int.from_bytes(base, "big")
                        for k in range(hi - lo + 1):
                            cmap[lo + k] = (bi + k).to_bytes(len(base), "big").decode("utf-16-be", "replace")
        return (2 if two else 1, cmap, "cp1252")

    def page_text(self, page, res, depth=0):
        content = self.r(page.get("Contents")) if depth == 0 else None
        if depth == 0:
            refs = page.get("Contents")
            refs = refs if isinstance(refs, list) else [refs]
            if isinstance(self.r(page.get("Contents")), list):
                refs = self.r(page.get("Contents"))
            data = b"\n".join(self.stream_of(x) for x in refs if isinstance(x, Ref))
        else:
            data = page  # Form XObject の展開済みのデータ
        fonts = self.r(res.get("Font")) or {}
        xobjs = self.r(res.get("XObject")) or {}
        dec = {}
        out = []
        cur = None
        i, ops = 0, []
        while True:
            i = _skip(data, i)
            if i >= len(data):
                break
            try:
                v, i = parse_obj(data, i)
            except Exception:
                i += 1
                continue
            if isinstance(v, Op):
                if v == "BI":
                    e = data.find(b"EI", i)
                    i = e + 2 if e >= 0 else len(data)
                    ops = []
                    continue
                if v == "Tf" and len(ops) >= 2:
                    fn = ops[-2]
                    if fn not in dec:
                        dec[fn] = self.font_decoder(fonts.get(fn))
                    cur = dec[fn]
                elif v in ("Tj", "'", '"') and ops and isinstance(ops[-1], bytes):
                    if v != "Tj":
                        out.append("\n")
                    out.append(self._dec(ops[-1], cur))
                elif v == "TJ" and ops and isinstance(ops[-1], list):
                    for x in ops[-1]:
                        if isinstance(x, bytes):
                            out.append(self._dec(x, cur))
                elif v in ("Td", "TD", "Tm", "T*", "BT", "ET"):
                    out.append("\n")
                elif v == "Do" and ops and depth < 3:
                    xo = self.r(xobjs.get(ops[-1]))
                    ref = xobjs.get(ops[-1])
                    if isinstance(xo, dict) and xo.get("Subtype") == "Form" and isinstance(ref, Ref):
                        sub = self.stream_of(ref)
                        out.append(self.page_text(sub, self.r(xo.get("Resources")) or res, depth + 1))
                ops = []
            else:
                ops.append(v)
        return "".join(out)

    @staticmethod
    def _dec(bs, cur):
        if cur is None:
            return bs.decode("latin-1")
        w, cmap, enc = cur
        if w == 2:
            return "".join(cmap.get(int.from_bytes(bs[k:k + 2], "big"), "\ufffd") for k in range(0, len(bs) - 1, 2))
        if cmap:
            return "".join(cmap.get(c, bytes([c]).decode(enc, "replace")) for c in bs)
        return bs.decode(enc, "replace")


def pdf_pages_text(path):
    p = PDF(pathlib.Path(path).read_bytes())
    return [p.page_text(pg, res) for pg, res in p.pages()]


# ---------------------------------------------------------------- HTML
class HText(html.parser.HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section", "article", "dt", "dd", "td", "th"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.links, self._a = [], 0, [], None

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        if tag in self.BLOCK:
            self.out.append("\n")
        if tag == "a":
            self._a = [dict(attrs).get("href"), ""]
        if tag == "img" and not self.skip:
            alt = dict(attrs).get("alt")
            if alt:
                self.out.append(f"[alt]{alt}[/alt]")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.skip:
            self.skip -= 1
        if tag in self.BLOCK:
            self.out.append("\n")
        if tag == "a" and self._a:
            self.links.append(tuple(self._a))
            self._a = None

    def handle_data(self, d):
        if not self.skip:
            self.out.append(d)
            if self._a is not None:
                self._a[1] += d


def html_text(path):
    raw = pathlib.Path(path).read_bytes()
    m = re.search(rb"charset=[\"']?([A-Za-z0-9_\-]+)", raw[:4000])
    enc = (m.group(1).decode().lower() if m else "utf-8")
    if enc in ("shift_jis", "sjis", "x-sjis"):
        enc = "cp932"
    h = HText()
    h.feed(raw.decode(enc, "replace"))
    return "".join(h.out), h.links, enc


# ---------------------------------------------------------------- 検査の道具
R8 = "令和八年三月三一日法律第二号"
R4 = "令和四年三月三一日法律第一号"
H31 = "平成三一年三月二九日法律第二号"
V6 = ["2025-01-01", "2026-01-01", "2026-04-01", "2026-11-09", "2027-01-01", "2028-01-01"]
LT = "docs/public-sources/20261109_round3_juminzei-extra-law-text.md"
AD = "docs/public-sources/20261109_round3_juminzei-extra-admin-and-municipal.md"
MS = "docs/measurements/20261109_round3_juminzei-extra-fetch-and-checks.md"
HY = "docs/hypotheses/20261109_round3_juminzei-extra-model.md"
IN = "docs/inferences/20261109_round3_juminzei-extra-implications.md"


class Ctx:
    """検査の結果を集め、法令・PDF・HTML を引く。"""

    def __init__(self, dl_laws, dl_web, log):
        self.dl_laws, self.dl_web, self.log = dl_laws, dl_web, log
        self.res, self.laws, self.pdfs, self.htm = [], {}, {}, {}

    def L(self, short, asof):
        k = (short, asof)
        if k not in self.laws:
            self.laws[k] = Law(self.dl_laws / f"{short}_{asof}.json")
        return self.laws[k]

    def rec(self, cid, doc, claim, ok, found="", kind="check"):
        self.res.append({"id": cid, "doc": doc, "claim": claim, "ok": ok, "found": found, "kind": kind})

    def node(self, short, asof, where, art, para=None, item=None, main_only=False):
        arts = self.L(short, asof).article(where, art)
        if not arts:
            return None
        n = arts[0]
        if para is not None:
            n = para_of(n, para)
            if n is None:
                return None
            if item is not None:
                n = item_of(n, item)
                if n is None:
                    return None
            elif main_only:
                return para_main_sentence(n)
        return txt(n)

    def law_has(self, cid, doc, claim, short, asofs, where, art, para, item, frags, absent=(), main_only=False):
        for asof in asofs:
            t = self.node(short, asof, where, art, para, item, main_only)
            loc = f"{short}@{asof} {where}:{art}" + (f" 第{para}項" if para else "") + (f" 第{item}号" if item else "")
            if t is None:
                self.rec(cid, doc, claim, False, f"{loc} が見つからない")
                continue
            nt = N(t)
            miss = [f for f in frags if N(f) not in nt]
            pres = [f for f in absent if N(f) in nt]
            ok = not miss and not pres
            self.rec(cid, doc, claim, ok, loc + (f" 欠け={miss}" if miss else "") + (f" 余計={pres}" if pres else "") + ("" if ok else f" 抜粋={nt[:160]}"))

    def suppl_map(self, asof, amend):
        return {(a, p): t for a, p, t in suppl_paragraphs(self.L("chiho", asof), amend)}

    def sp_has(self, cid, doc, claim, sp, a, p, frags):
        t = sp.get((a, p))
        self.rec(cid, doc, claim, t is not None and all(N(f) in N(t) for f in frags), (t or "（なし）")[:200])

    def load_pdf(self, name):
        p = PDF((self.dl_web / f"{name}.pdf").read_bytes())
        pages = [N(p.page_text(pg, res)) for pg, res in p.pages()]
        fonts = set()
        for pg, res in p.pages():
            for fn, fr in (p.r(res.get("Font")) or {}).items():
                f = p.r(fr) or {}
                enc = f.get("Encoding")
                fonts.add(f"{fn}:{enc if isinstance(enc, str) else type(enc).__name__}{'+ToUnicode' if f.get('ToUnicode') else ''}")
        self.pdfs[name] = pages
        return pages, sorted(fonts)

    def pdf_at(self, cid, doc, claim, name, frag, pages_exp):
        f = N(frag)
        got = [i + 1 for i, t in enumerate(self.pdfs[name]) if f in t]
        ok = (set(pages_exp) <= set(got)) if pages_exp else bool(got)
        ex = ""
        if got:
            t = self.pdfs[name][got[0] - 1]
            i = t.find(f)
            ex = t[max(0, i - 30): i + min(len(f), 60) + 30]
        self.rec(cid, doc, claim + f"（期待 p.{pages_exp}）", ok, f"見つかった頁={got} 抜粋={ex}")

    def h_has(self, cid, doc, claim, name, frags, absent=()):
        t = self.htm[name][0]
        miss = [f for f in frags if N(f) not in t]
        pres = [f for f in absent if N(f) in t]
        self.rec(cid, doc, claim, not miss and not pres, (f"欠け={miss} " if miss else "") + (f"余計={pres}" if pres else ""))


def checks_laws(c):
    L, rec, law_has, node = c.L, c.rec, c.law_has, c.node
    # ---------------- §0 取得した版（［法令］§0、［実測］§2.1）
    exp_rev = {
        ("chiho", "2025-01-01"): ("325AC0000000226_20250101_506AC0000000004", "PreviousEnforced", "228e182f179fb138"),
        ("chiho", "2026-01-01"): ("325AC0000000226_20260101_507AC0000000041", "PreviousEnforced", "ba0a40e550be7762"),
        ("chiho", "2026-04-01"): ("325AC0000000226_20260401_508AC0000000002", "PreviousEnforced", "06db2ba6ccfec62e"),
        ("chiho", "2026-11-09"): ("325AC0000000226_20261101_508AC0000000002", "CurrentEnforced", "3dd29e0078bf24e0"),
        ("chiho", "2027-01-01"): ("325AC0000000226_20270101_508AC0000000002", "UnEnforced", "ee21722ce5fd1561"),
        ("chiho", "2028-01-01"): ("325AC0000000226_20280101_508AC0000000002", "UnEnforced", "ba69aa86514c9750"),
        ("chiho", "2030-01-01"): ("325AC0000000226_20290624_508AC0000000051", "UnEnforced", "3257c8e4f4aa68e8"),
        ("chiho-rei", "2026-01-01"): ("325CO0000000245_20260101_507CO0000000119", "PreviousEnforced", "e6224a70357bbc64"),
        ("chiho-rei", "2026-11-09"): ("325CO0000000245_20261101_508CO0000000083", "CurrentEnforced", "9bc03b230fb0ed10"),
        ("chiho-rei", "2027-01-01"): ("325CO0000000245_20270101_508CO0000000083", "UnEnforced", "962bfc48e43c49b4"),
        ("chiho-kisoku", "2026-01-01"): ("329M50000002023_20260101_507M60000008116", "PreviousEnforced", "285e203a423a4fee"),
        ("chiho-kisoku", "2026-11-09"): ("329M50000002023_20261101_508M60000008045", "CurrentEnforced", "5ffb833bd3a3d7c4"),
        ("chiho-kisoku", "2027-01-01"): ("329M50000002023_20270101_508M60000008089", "UnEnforced", "e8d5c022315165a3"),
        ("sochi", "2026-11-09"): ("332AC0000000026_20261101_507AC0000000013", "CurrentEnforced", "e6e6013bbc0608c6"),
    }
    byk = {(e["short"], e["asof"]): e for e in c.log["laws"]}
    for k, (rid, st, h) in exp_rev.items():
        e = byk.get(k, {})
        rec("V0-rev", f"{LT} §0・{MS} §2.1", f"{k[0]} asof {k[1]}：law_revision_id={rid}・状態={st}・SHA-256 先頭={h}",
            e.get("law_revision_id") == rid and e.get("current_revision_status") == st and (e.get("sha256") or "").startswith(h),
            f"今回：{e.get('law_revision_id')} {e.get('current_revision_status')} {(e.get('sha256') or '')[:16]}")
    e = byk.get(("chiho-kisoku", "2026-11-09"), {})
    rec("V0-kisoku", f"{LT} §0", "地方税法施行規則＝昭和29年総理府令第23号（law_id 329M50000002023）", e.get("law_num") == "昭和二十九年総理府令第二十三号", str(e.get("law_num")))

    # ---------------- §1 家屋敷課税
    law_has("V1-01", f"{LT} §1.1", "第294条第1項柱書：第2号・第4号の者は均等割額", "chiho", V6, "main", "294", 1, None, ["第二号及び第四号の者に対しては均等割額により"], main_only=True)
    law_has("V1-02", f"{LT} §1.1", "第294条第1項第2号", "chiho", V6, "main", "294", 1, 2, ["市町村内に事務所、事業所又は家屋敷を有する個人で当該市町村内に住所を有しない者"])
    law_has("V1-03", f"{LT} §1.1", "第24条第1項柱書", "chiho", V6, "main", "24", 1, None, ["第二号及び第四号に掲げる者に対しては均等割額により"], main_only=True)
    law_has("V1-04", f"{LT} §1.1", "第24条第1項第2号", "chiho", V6, "main", "24", 1, 2, ["道府県内に事務所、事業所又は家屋敷を有する個人で当該事務所、事業所又は家屋敷を有する市町村内に住所を有しない者"])
    law_has("V1-05", f"{LT} §1.1", "第24条第7項", "chiho", V6, "main", "24", 7, None, ["第一項第二号に掲げる者については、市町村民税を均等割により課する市町村ごとに一の納税義務があるものとして道府県民税を課する"])
    law_has("V1-06", f"{LT} §1.2", "第318条（賦課期日 1月1日）", "chiho", V6, "main", "318", 1, None, ["個人の市町村民税の賦課期日は、当該年度の初日の属する年の一月一日とする"])
    law_has("V1-07", f"{LT} §1.2", "第39条（同）", "chiho", V6, "main", "39", 1, None, ["個人の道府県民税の賦課期日は、当該年度の初日の属する年の一月一日とする"])
    law_has("V1-08", f"{LT} §1.2", "第317条の2第8項（家屋敷等の申告）", "chiho", ["2026-01-01", "2026-11-09", "2027-01-01"], "main", "317_2", 8, None,
            ["当該市町村の条例で定めるところにより、第二百九十四条第一項第二号に掲げる者に、賦課期日現在において有する事務所、事業所又は家屋敷の所在その他必要な事項を申告させることができる"])
    law_has("V1-09", f"{LT} §1.3", "第294条第2項", "chiho", V6, "main", "294", 2, None, ["当該市町村の住民基本台帳に記録されている者をいう"])
    law_has("V1-10", f"{LT} §1.3", "第294条第3項", "chiho", V6, "main", "294", 3, None, ["その者を当該住民基本台帳に記録されている者とみなして、その者に市町村民税を課することができる"])
    law_has("V1-11", f"{LT} §1.3", "第294条第4項", "chiho", V6, "main", "294", 4, None, ["その者が記録されている住民基本台帳に係る市町村は、第二項の規定にかかわらず、市町村民税を課することができない"])
    law_has("V1-12", f"{LT} §1.4", "第737条第1項", "chiho", V6, "main", "737", 1, None, ["特別区並びに指定都市の区及び総合区の区域は、一の市の区域とみなし"])
    law_has("V1-13", f"{LT} §1.5", "第295条第1項ただし書", "chiho", V6, "main", "295", 1, None, ["ただし、この法律の施行地に住所を有しない者については、この限りでない"], main_only=True)
    law_has("V1-14", f"{LT} §1.5", "第295条第1項第1号", "chiho", V6, "main", "295", 1, 1, ["生活保護法の規定による生活扶助を受けている者"])
    law_has("V1-15", f"{LT} §1.5", "第295条第1項第2号（135万円）", "chiho", V6, "main", "295", 1, 2, ["障害者、未成年者、寡婦又はひとり親（これらの者の前年の合計所得金額が百三十五万円を超える場合を除く。）"])
    law_has("V1-16", f"{LT} §1.5", "第295条第3項", "chiho", V6, "main", "295", 3, None,
            ["この法律の施行地に住所を有する者で均等割のみを課すべきもののうち、前年の合計所得金額が政令で定める基準に従い当該市町村の条例で定める金額以下である者に対しては、均等割を課することができない"])
    law_has("V1-17", f"{LT} §1.5", "第295条に第294条第1項第2号を名指しして除く文言はない", "chiho", V6, "main", "295", None, None, [], absent=["第二百九十四条第一項第二号"])
    law_has("V1-18", f"{LT} §1.5", "第24条の5第1項ただし書", "chiho", V6, "main", "24_5", 1, None, ["ただし、この法律の施行地に住所を有しない者については、この限りでない"], main_only=True)
    law_has("V1-19", f"{LT} §1.5", "第24条の5第3項", "chiho", V6, "main", "24_5", 3, None,
            ["第二百九十五条第三項の規定により個人の市町村民税の均等割を課することができないこととされる者に対しては、当該均等割と併せて賦課徴収すべき個人の道府県民税の均等割を課することができない"])
    law_has("V1-20", f"{LT} §1.5", "施行令第47条の3 は第295条第3項の政令の基準", "chiho-rei", ["2026-11-09"], "main", "47_3", 1, None, ["法第二百九十五条第三項に規定する政令で定める基準は"], main_only=True)
    law_has("V1-21", f"{LT} §1.6", "第300条第1項（列挙に家屋敷なし）", "chiho", ["2026-11-09"], "main", "300", 1, None, ["納税義務を負う市町村内に住所、居所、事務所、事業所又は寮等を有しない場合"], absent=["家屋敷"])
    law_has("V1-22", f"{LT} §1.6", "第300条第2項", "chiho", ["2026-11-09"], "main", "300", 2, None, ["徴収の確保に支障がないことについて市町村長に申請してその認定を受けたときは、納税管理人を定めることを要しない"])
    law_has("V1-23", f"{LT} §1.6", "第320条", "chiho", V6, "main", "320", 1, None, ["六月、八月、十月及び一月中（当該個人の市町村民税額が均等割額に相当する金額以下である場合にあつては、六月中）"])
    law_has("V1-24", f"{LT} §1.6", "第41条第1項", "chiho", ["2026-11-09"], "main", "41", 1, None, ["当該市町村の個人の市町村民税の賦課徴収（均等割の税率の軽減を除く。）の例により"])
    for art, para in (("41", 3), ("17_2", 2), ("17_4", 6), ("739_2", 1), ("739_5", 1)):
        law_has(f"V1-25-{art}", f"{LT} §1.6", f"第{art.replace('_', '条の', 1).replace('_', 'の')}{'' if '_' in art else '条'}第{para}項が第294条第1項第2号の均等割を名指し", "chiho", ["2026-11-09"], "main", art, para, None,
                ["第二百九十四条第一項第二号に掲げる者に対して課する均等割"])
    law_has("V1-26", f"{LT} §1.6", "第319条第2項", "chiho", ["2026-11-09"], "main", "319", 2, None, ["当該個人の道府県民税及び森林環境税を併せて賦課し、及び徴収するものとする"])
    law_has("V1-27", f"{LT} §1.7", "第310条（3,000円）", "chiho", V6, "main", "310", 1, None, ["個人の均等割の標準税率は、三千円とする"])
    law_has("V1-28", f"{LT} §1.7", "第38条（1,000円）", "chiho", ["2026-01-01", "2026-11-09", "2027-01-01"], "main", "38", 1, None, ["個人の均等割の標準税率は、千円とする"])
    law_has("V1-29", f"{LT} §1.7", "森林環境税法第3条（施行地に住所を有する個人）", "shinrin", ["2026-11-09"], "main", "3", 1, None, ["この法律の施行地に住所を有する個人に対しては"])
    for asof in V6:
        law = L("chiho", asof)
        for kw, exp in (("家屋敷", ["main:20_3", "main:20_4", "main:24", "main:294", "main:317_2"]),
                        ("第二百九十四条第一項第二号", ["main:17_2", "main:17_2_2", "main:17_4", "main:41", "main:317_2", "main:739_2", "main:739_5"])):
            got = [f"{w}:{a['attr']['Num']}" for w in ("main", "orig") for a in law.all_articles(w) if kw in txt(a)]
            am = [an for an, n in law.suppl if an and kw in txt(n)]
            rec("V1-30", f"{LT} §1.8・§1.6・{MS} §4.1", f"asof {asof}：「{kw}」を含む条（本則・原始附則）は {exp}、改正附則に 0", got == exp and not am, f"{got} 改正附則={am}")
            if kw == "家屋敷":
                defs = [g for g in got if re.search("家屋敷とは|家屋敷をいう", txt(law.article(*g.split(":"))[0]))]
                rec("V1-31", f"{LT} §1.8", f"asof {asof}：「家屋敷とは」「家屋敷をいう」はない", not defs, str(defs))
    for short in ("chiho-rei", "chiho-kisoku"):
        for asof in ("2026-11-09", "2027-01-01"):
            law = L(short, asof)
            got = [a["attr"]["Num"] for w in ("main", "orig") for a in law.all_articles(w) if "家屋敷" in txt(a)]
            am = [an for an, n in law.suppl if an and "家屋敷" in txt(n)]
            rec("V1-32", f"{LT} §1.8", f"{short} asof {asof}：「家屋敷」は 0（本則・原始附則・改正附則）", not got and not am, f"{got} {am}")

    # ---------------- §2 配当割額等の控除
    law_has("V2-01", f"{LT} §2.1", "第314条の9第1項（確定申告書に記載・3/5・第314条の3及び前三条の後）", "chiho", V6, "main", "314_9", 1, None,
            ["第三百十三条第十三項に規定する確定申告書に記載した特定配当等", "同条第十五項に規定する確定申告書に記載した特定株式等譲渡所得金額",
             "五分の三を乗じて得た金額を、その者の第三百十四条の三及び前三条の規定を適用した場合の所得割の額から控除する"], absent=["指定都市"])
    law_has("V2-02", f"{LT} §2.1", "第314条の9第2項（還付・委託のみなし）", "chiho", V6, "main", "314_9", 2, None,
            ["その控除することができなかつた金額を還付しなければならない", "確定申告書に係る年の末日の属する年度の翌年度分の個人の道府県民税、個人の市町村民税若しくは森林環境税",
             "市町村徴収金を納付し、又は納入することを委託したものとみなす"])
    law_has("V2-03", f"{LT} §2.1", "第314条の9第3項（道府県民税分も市町村が扱う）", "chiho", V6, "main", "314_9", 3, None, ["第三十七条の四の規定により控除されるべき額で同条の所得割の額から控除することができなかつた金額があるときは"])
    law_has("V2-04", f"{LT} §2.1", "第37条の4（2/5・第35条及び前三条の後）", "chiho", V6, "main", "37_4", 1, None, ["五分の二を乗じて得た金額を、その者の第三十五条及び前三条の規定を適用した場合の所得割の額から控除する"], absent=["指定都市"])
    for asof in V6:
        rec("V2-05", f"{LT} §2.1", f"asof {asof}：第37条の4 に第2項はない", para_of(L("chiho", asof).article("main", "37_4")[0], 2) is None, "")
    law_has("V2-06", f"{LT} §2.2", "第71条の27第1項", "chiho", ["2026-11-09"], "main", "71_27", 1, None, ["配当割の課税標準は、支払を受けるべき特定配当等の額とする"])
    law_has("V2-07", f"{LT} §2.2", "第71条の28（百分の五）", "chiho", V6, "main", "71_28", 1, None, ["配当割の税率は、百分の五とする"])
    law_has("V2-08", f"{LT} §2.2", "第71条の49（百分の五）", "chiho", V6, "main", "71_49", 1, None, ["株式等譲渡所得割の税率は、百分の五とする"])
    law_has("V2-09", f"{LT} §2.2", "第71条の31第1項（特別徴収義務者）", "chiho", ["2026-11-09"], "main", "71_31", 1, None,
            ["特定配当等の支払を受けるべき日現在において道府県内に住所を有する個人に対して特定配当等の支払をする者", "その支払を取り扱う者があるときは、その者"])
    law_has("V2-10", f"{LT} §2.2", "第313条第12項（ロを除く）", "chiho", ["2026-04-01", "2026-11-09", "2027-01-01"], "main", "313", 12, None,
            ["特定配当等（第二十三条第一項第十五号ロに掲げるものを除く。以下この項において同じ。）に係る所得を有する者に係る総所得金額は"])
    law_has("V2-11", f"{LT} §2.2", "第313条第12項（2026-01-01 以前は括弧書きなし）", "chiho", ["2025-01-01", "2026-01-01"], "main", "313", 12, None, ["特定配当等に係る所得を有する者に係る総所得金額は"], absent=["第二十三条第一項第十五号ロ"])
    law_has("V2-12", f"{LT} §2.2", "第313条第13項", "chiho", ["2026-11-09"], "main", "313", 13, None,
            ["前年分の所得税に係る第三百十七条の三第一項に規定する確定申告書に特定配当等に係る所得の明細に関する事項その他総務省令で定める事項の記載があるとき"])
    law_has("V2-13", f"{LT} §2.2", "第313条第15項", "chiho", ["2026-11-09"], "main", "313", 15, None, ["特定株式等譲渡所得金額に係る所得の明細に関する事項その他総務省令で定める事項の記載があるとき"])
    law_has("V2-14", f"{LT} §2.2", "施行規則第1条の12の2第1項第1号", "chiho-kisoku", ["2026-01-01", "2026-11-09", "2027-01-01"], "main", "1_12_2", 1, 1, ["法第三十七条の四及び第三百十四条の九第一項の規定により所得割額から控除する配当割額"])
    law_has("V2-15", f"{LT} §2.2", "施行規則第1条の12の2第2項", "chiho-kisoku", ["2026-11-09"], "main", "1_12_2", 2, None, ["前項第一号に掲げる事項は、第二条の三第二項の確定申告書に付記しなければならない事項とする"])
    law_has("V2-16", f"{LT} §2.2", "施行規則第1条の12の3第1項第1号（株式等譲渡所得割額）", "chiho-kisoku", ["2026-11-09"], "main", "1_12_3", 1, 1, ["株式等譲渡所得割額"])
    law_has("V2-17", f"{LT} §2.2", "施行規則第2条の3第2項（付記事項）", "chiho-kisoku", ["2026-11-09"], "main", "2_3", 2, None, ["確定申告書に付記しなければならない事項は、次に掲げる事項とする"], main_only=True)
    law_has("V2-18", f"{LT} §2.3", "施行令第48条の9の3第1項", "chiho-rei", ["2026-01-01", "2026-11-09", "2027-01-01"], "main", "48_9_3", 1, None,
            ["確定申告書に係る年の末日の属する年度の翌年度分の個人の道府県民税、個人の市町村民税又は森林環境税の法第十七条の四に規定する賦課決定（法第三百二十一条の二第一項の規定による追徴に係るものを除く。）後、納税通知書を発する前に"])
    law_has("V2-19", f"{LT} §2.3", "施行令第48条の9の3第3項（追徴→その他の未納）", "chiho-rei", ["2026-11-09"], "main", "48_9_3", 3, None, ["次の各号の順序により", "追徴すべきもの", "その他の未納に係る地方団体の徴収金"])
    law_has("V2-20", f"{LT} §2.3", "施行令第48条の9の4第1項（還付）", "chiho-rei", ["2026-11-09"], "main", "48_9_4", 1, None, ["当該金額を還付するものとする"])
    law_has("V2-21", f"{LT} §2.3", "施行令第48条の9の5第1項（7.3%・同年度分への充当は加算なし）", "chiho-rei", ["2026-11-09"], "main", "48_9_5", 1, None,
            ["当該控除不足額が確定した日の翌日から", "年七・三パーセントの割合", "ただし、第四十八条の九の三第一項又は第三項第一号の規定による納付又は納入をする場合は、この限りでない"])
    law_has("V2-22", f"{LT} §2.3", "施行令第48条の9の5第2項（第20条の4の2第2項・第5項の準用）", "chiho-rei", ["2026-11-09"], "main", "48_9_5", 2, None,
            ["法第二十条の四の二第二項及び第五項の規定は前項の規定により還付金等の額に加算すべき金額について準用する"])
    law_has("V2-23", f"{LT} §2.3・§4-7（未確認だった点）", "施行令附則第3条の2第1項は第48条の9の5第1項の年7.3% を還付加算金特例基準割合に替える", "chiho-rei", ["2026-11-09", "2027-01-01"], "orig", "3_2", 1, None,
            ["第四十八条の九の五第一項", "還付加算金の年七・三パーセントの割合は、これらの規定にかかわらず、各年の還付加算金特例基準割合", "年七・三パーセントの割合に満たない場合には"])
    law_has("V2-24", f"{LT} §2.4", "附則第5条の4第6項（第314条の9 の前三条の読替え）", "chiho", ["2026-04-01", "2026-11-09", "2027-01-01"], "orig", "5_4", 6, None, ["同項中「前三条」とあるのは「前三条並びに附則第五条の四第五項」とする"])
    law_has("V2-25", f"{LT} §2.4", "附則第5条の4第2項（第37条の3・第37条の4 の読替え）", "chiho", ["2026-11-09"], "orig", "5_4", 2, None,
            ["第三十七条の三中「前二条」とあるのは「前二条並びに附則第五条の四第一項」と、第三十七条の四中「前三条」とあるのは「前三条並びに附則第五条の四第一項」とする"])
    for asof in ("2026-04-01", "2026-11-09", "2027-01-01"):
        law = L("chiho", asof)
        hits = []
        for a in law.all_articles("orig"):
            for p in a.get("children", []):
                if isinstance(p, dict) and p.get("tag") == "Paragraph":
                    t = txt(p)
                    if "第三百十四条の九第一項" in t and "「前三条」とあるのは" in t:
                        hits.append(f"{a['attr']['Num']}-{p['attr']['Num']}")
        t72 = txt(law.article("orig", "7_2")[0])
        rec("V2-26", f"{LT} §4-8（未確認だった点）・{HY} 未決4", f"asof {asof}：第314条の9第1項の「前三条」を読み替える原始附則は 3_3-6・5-4・5_4-6・6-6 だけで、附則第7条の2（申告特例控除）に第314条の9 の語はない",
            hits == ["3_3-6", "5-4", "5_4-6", "6-6"] and "第三百十四条の九" not in t72, f"{hits} 7_2に314条の9={'第三百十四条の九' in t72}")
    law_has("V2-27", f"{LT} §4-8（未確認だった点）", "附則第7条の2第4項：申告特例控除は第314条の7第1項・第11項の後の所得割から", "chiho", ["2026-11-09"], "orig", "7_2", 4, None,
            ["申告特例控除額を当該納税義務者の第三百十四条の七第一項及び第十一項の規定を適用した場合の所得割の額から控除するものとする"])
    law_has("V2-30", f"{LT} §2.5", "第23条第1項第15号（イ・ロ・ハ）", "chiho", ["2026-04-01", "2026-11-09", "2027-01-01", "2028-01-01"], "main", "23", 1, 15,
            ["イ租税特別措置法第八条の四第一項に規定する上場株式等の配当等", "ロ租税特別措置法第九条の三第一号に掲げる同条に規定する配当等（イに掲げるもの及び政令で定めるものを除く。）",
             "ハ租税特別措置法第四十一条の十二の二第一項各号に掲げる償還金に係る同条第六項第三号に規定する差益金額"])
    law_has("V2-31", f"{LT} §2.5", "第23条第1項第15号（2026-01-01 以前はロなし）", "chiho", ["2025-01-01", "2026-01-01"], "main", "23", 1, 15,
            ["租税特別措置法第八条の四第一項に規定する上場株式等の配当等及び同法第四十一条の十二の二第一項各号に掲げる償還金"], absent=["第九条の三第一号"])
    law_has("V2-32", f"{LT} §2.5", "施行令第7条の3", "chiho-rei", ["2026-11-09", "2027-01-01"], "main", "7_3", 1, None,
            ["所得税法（昭和四十年法律第三十三号）第百六十一条第一項第九号に掲げる配当等のうち同法第二百十二条第二項の規定の適用を受けるもの"])
    t73 = node("chiho-rei", "2026-01-01", "main", "7_3", 1)
    rec("V2-33", f"{LT} §2.5", "asof 2026-01-01 の施行令第7条の3 は「見出しのない空の条」", False,
        f"取得した本文={t73!r}：見出しはないが本文は「削除」（空ではない）→ 文言を訂正")
    law_has("V2-34", f"{LT} §2.5", "措法第9条の3第1号（大口株主等以外）", "sochi", ["2025-01-01", "2025-06-30", "2025-12-31", "2026-11-09"], "main", "9_3", 1, 1,
            ["百分の三以上に相当する数又は金額の株式又は出資を有する個人（次条第一項において「大口株主等」という。）以外の者が支払を受けるもの"])
    law_has("V2-35", f"{LT} §2.5・§4-6（未確認だった点）", "措法第8条の4第1項第1号の括弧書き（同族会社と合算して 3% 以上）", "sochi", ["2025-01-01", "2025-06-30", "2025-12-31", "2026-11-09"], "main", "8_4", 1, 1,
            ["法人税法第二条第十号に規定する同族会社に該当することとなる法人と合算して当該内国法人の発行済株式又は出資の総数又は総額の百分の三以上に相当する数又は金額の株式又は出資を有することとなるものを含む"])
    vals = {a: node("sochi", a, "main", "8_4", 1, 1) for a in ("2025-01-01", "2025-06-30", "2025-12-31", "2026-11-09")}
    rec("V2-36", f"{LT} §4-6（未確認だった点）", "措法第8条の4第1項第1号の文言は asof 2025-01-01・2025-06-30・2025-12-31・2026-11-09 で同じ",
        len(set(vals.values())) == 1, str({k: hashlib.sha256((v or "").encode()).hexdigest()[:12] for k, v in vals.items()}))
    law_has("V2-37", f"{LT} §2.5", "令和8年法律第2号 附則第1条本文（令和8年4月1日施行）", "chiho", ["2030-01-01"], R8, "1", 1, None, ["この法律は、令和八年四月一日から施行する"], main_only=True)
    sp8 = c.suppl_map("2030-01-01", R8)
    c.sp_has("V2-38", f"{LT} §2.5・§3.4", "令和8年法律第2号 附則第3条第1項（道府県民税：令和8年度以後）", sp8, "3", "1", ["令和八年度以後の年度分の個人の道府県民税について適用し"])
    c.sp_has("V2-39", f"{LT} §2.5・§3.4", "令和8年法律第2号 附則第11条第1項（市町村民税：令和8年度以後）", sp8, "11", "1", ["令和八年度以後の年度分の個人の市町村民税について適用し"])
    c.sp_has("V2-40", f"{LT} §2.5", "令和8年法律第2号 附則第3条第3項（施行日以後に支払を受けるべき特定配当等）", sp8, "3", "3",
             ["新法第二十三条第一項第十五号に規定する特定配当等に係る道府県民税に関する部分は、この法律の施行の日（以下「施行日」という。）以後に支払を受けるべき同号に規定する特定配当等について適用し", "なお従前の例による"])
    arts8 = sorted({a for a, p in sp8 if a}, key=lambda x: [int(y) for y in x.split("_")])
    hit8 = sorted(f"{a}-{p}" for (a, p), t in sp8.items() if "特定配当等" in t)
    rec("V2-41", f"{LT} §2.5", "令和8年法律第2号の附則で「特定配当等」を含む項は附則第3条第3項だけ", None,
        f"e-Gov に収録された附則は第{arts8[0]}条〜第{arts8[-1]}条（{len(arts8)} 条）で、その中では {hit8}。本文 PDF の附則第28条・第29条（他の法律の改正規定）にも「特定配当等」がある（V5-47）→ 「e-Gov 収録分（附則第1条〜第22条）では」と限定する")
    sp4 = c.suppl_map("2030-01-01", R4)
    c.sp_has("V2-42", f"{LT} §2.5", "令和4年法律第1号 附則第1条第5号（第313条第13項・第314条の9第1項・第317条の2第1項ただし書などは令和6年1月1日）", sp4, "1", "1",
             ["第三百十三条第十三項及び第十五項、第三百十四条の九第一項、第三百十七条の二第一項ただし書", "令和六年一月一日"])
    c.sp_has("V2-43", f"{LT} §2.5", "令和4年法律第1号 附則第11条第1項（六年新法は令和6年度以後）", sp4, "11", "1", ["六年新法の規定中個人の市町村民税に関する部分は、令和六年度以後の年度分の個人の市町村民税について適用し"])

    # ---------------- §3 住宅借入金等特別税額控除
    t = node("chiho", "2026-01-01", "orig", "5_4")
    t2 = node("chiho", "2026-01-01", "orig", "5_4_2")
    rec("V3-01", f"{LT} §3.1", "asof 2026-01-01：附則第5条の4 は旧制度（平成二十年度から平成二十八年度まで・居住年 平成十一年から平成十八年まで）",
        all(N(f) in N(t) for f in ("平成二十年度から平成二十八年度までの各年度分", "平成十一年から平成十八年までの各年")), "")
    rec("V3-02", f"{LT} §3.1", "asof 2026-01-01：附則第5条の4の2（平成十一年から平成十八年まで又は平成二十一年から令和七年まで）に基礎控除の差の加算・申告書の定めはない",
        N("平成十一年から平成十八年まで又は平成二十一年から令和七年まで") in N(t2) and "基礎控除" not in t2 and "申告書" not in t2 and "四十八万円" not in t2, "")
    for asof in ("2026-04-01", "2026-11-09", "2027-01-01"):
        rec("V3-03", f"{LT} §3.1", f"asof {asof}：附則第5条の4の2 はない", not L("chiho", asof).article("orig", "5_4_2"), "")
    P5 = ["平成二十二年度から令和二十年度までの各年度分の個人の市町村民税に限り",
          "前年分の所得税につき租税特別措置法第四十一条又は第四十一条の二の二の規定の適用を受けた場合（居住年が平成二十一年から令和七年までの各年である場合に限る。）",
          "の五分の三（当該納税義務者が指定都市の区域内に住所を有する場合には、五分の四）に相当する金額",
          "第三百十四条の三及び第三百十四条の六の規定を適用した場合の所得割の額から控除する",
          "所得税法第八十九条第二項に規定する課税総所得金額、課税退職所得金額及び課税山林所得金額の合計額（居住年が平成二十八年から令和七年までの各年である場合には、当該納税義務者の前年分の所得税に係る同法第八十六条第二項に規定する基礎控除の額（租税特別措置法第四十一条の十六の二第一項の規定の適用がある場合には、その適用後の額）から四十八万円を控除して得た額（当該控除して得た額が零を下回る場合には、零とする。）を加算した額）の百分の三（当該納税義務者が指定都市の区域内に住所を有する場合には、百分の四）",
          "五万八千五百円（当該納税義務者が指定都市の区域内に住所を有する場合には、七万八千円）"]
    law_has("V3-04", f"{LT} §3.2", "附則第5条の4第5項（年度・居住年・3/5（4/5）・基・加算・3%（4%）・58,500円（78,000円））", "chiho", ["2026-04-01", "2026-11-09"], "orig", "5_4", 5, None, P5, main_only=True)
    law_has("V3-05", f"{LT} §3.2", "附則第5条の4第5項第1号", "chiho", ["2026-11-09"], "orig", "5_4", 5, 1,
            ["租税特別措置法第四十一条第二項から第五項まで若しくは第十項から第二十一項まで若しくは第四十一条の二又は阪神・淡路大震災の被災者等に係る国税関係法律の臨時特例に関する法律第十六条第一項から第三項までの規定を適用して計算した",
             "平成十九年又は平成二十年の居住年に係る同項に規定する住宅借入金等の金額を有する場合には"])
    law_has("V3-06", f"{LT} §3.2", "附則第5条の4第5項第2号", "chiho", ["2026-11-09"], "orig", "5_4", 5, 2,
            ["租税特別措置法第四十一条、第四十一条の二の二、第四十一条の十八、第四十一条の十八の二第二項、第四十一条の十八の三若しくは第四十一条の十九の二から第四十一条の十九の四まで、災害被害者に対する租税の減免、徴収猶予等に関する法律第二条又は所得税法第九十五条若しくは第百六十五条の六"])
    law_has("V3-07", f"{LT} §3.2", "附則第5条の4第1項（2/5（1/5）・第35条及び第37条の後・2%（1%）・39,000円（19,500円））", "chiho", ["2026-11-09"], "orig", "5_4", 1, None,
            ["の五分の二（当該納税義務者が指定都市の区域内に住所を有する場合には、五分の一）", "第三十五条及び第三十七条の規定を適用した場合の所得割の額から控除する",
             "百分の二（当該納税義務者が指定都市の区域内に住所を有する場合には、百分の一）", "三万九千円（当該納税義務者が指定都市の区域内に住所を有する場合には、一万九千五百円）"], main_only=True)
    law_has("V3-08", f"{LT} §3.2", "附則第5条の4第7項（平成26年〜令和3年・特定取得（第5項）・特別特定取得（第16項）：4.2%・5.6%・81,900円・109,200円）", "chiho", ["2026-11-09"], "orig", "5_4", 7, None,
            ["居住年が平成二十六年から令和三年までであつて", "租税特別措置法第四十一条第五項に規定する特定取得又は同条第十六項に規定する特別特定取得",
             "「百分の三」とあるのは「百分の四・二」と、「百分の四」とあるのは「百分の五・六」と、「五万八千五百円」とあるのは「八万千九百円」と、「七万八千円」とあるのは「十万九千二百円」"])
    law_has("V3-09", f"{LT} §3.2", "附則第5条の4第3項（2.8%・1.4%・54,600円・27,300円）", "chiho", ["2026-11-09"], "orig", "5_4", 3, None,
            ["「百分の二」とあるのは「百分の二・八」と、「百分の一」とあるのは「百分の一・四」と、「三万九千円」とあるのは「五万四千六百円」と、「一万九千五百円」とあるのは「二万七千三百円」"])
    law_has("V3-10", f"{LT} §3.2", "附則第5条の4第4項", "chiho", ["2026-11-09"], "orig", "5_4", 4, None, ["前二項に定めるもののほか、第一項の規定の適用に関し必要な事項は、政令で定める"])
    law_has("V3-11", f"{LT} §3.2", "附則第5条の4第8項", "chiho", ["2026-11-09"], "orig", "5_4", 8, None, ["前二項に定めるもののほか、第五項の規定の適用に関し必要な事項は、政令で定める"])
    law_has("V3-12", f"{LT} §3.2", "附則第5条の4 に還付・申告書・「限度とする」の文言はない", "chiho", ["2026-04-01", "2026-11-09", "2027-01-01"], "orig", "5_4", None, None, [], absent=["還付", "申告書", "限度とする"])
    for short in ("chiho-rei", "chiho-kisoku"):
        for asof in ("2026-11-09", "2027-01-01"):
            law = L(short, asof)
            kw = "住宅借入金等特別税額控除" if short == "chiho-kisoku" else "住宅借入金"
            got = [a["attr"]["Num"] for w in ("main", "orig") for a in law.all_articles(w) if kw in txt(a)]
            am = [an for an, n in law.suppl if an and kw in txt(n)]
            rec("V3-13", f"{LT} §3.2・§4-10・{MS} §4.1", f"{short} asof {asof}：「{kw}」は本則・原始附則・改正附則に 0", not got and not am, f"本則・原始附則={got} 改正附則={am}")
    law_has("V3-14", f"{LT} §3.3", "asof 2027-01-01 の附則第5条の4第5項（令和二十五年度・令和十二年・第二項から第十八項まで・平成19/20年の括弧書きなし・加算は平成二十八年から令和七年まで）", "chiho", ["2027-01-01", "2028-01-01"], "orig", "5_4", 5, None,
            ["平成二十二年度から令和二十五年度までの各年度分", "居住年が平成二十一年から令和十二年までの各年である場合に限る", "第四十一条第二項から第十八項まで", "居住年が平成二十八年から令和七年までの各年である場合には"],
            absent=["平成十九年又は平成二十年の居住年"])
    law_has("V3-15", f"{LT} §3.3", "asof 2027-01-01 の附則第5条の4第7項（特別特定取得は同条第十二項）", "chiho", ["2027-01-01"], "orig", "5_4", 7, None, ["同条第十二項に規定する特別特定取得"])
    c.sp_has("V3-16", f"{LT} §3.3", "令和8年法律第2号 附則第1条第2号（附則第5条の4の2第1項・第5項の「令和二十年度」→「令和二十五年度」、「令和七年」→「令和十二年」などは令和9年1月1日）", sp8, "1", "1",
             ["同法附則第五条の四の二第一項の改正規定（「令和二十年度」を「令和二十五年度」に改める部分、「令和七年」を「令和十二年」に改める部分",
              "同条第五項の改正規定（「令和二十年度」を「令和二十五年度」に改める部分、「令和七年」を「令和十二年」に改める部分及び同項第一号に係る部分に限る。）", "令和九年一月一日"])
    c.sp_has("V3-17", f"{LT} §3.4", "令和8年法律第2号 附則第11条第10項（令和8年1月1日以後の居住に九年一月新法、前は従前の例）", sp8, "11", "10",
             ["九年一月新法附則第五条の四第五項から第八項までの規定は、市町村民税の所得割の納税義務者が令和八年一月一日以後に", "同日前に", "なお従前の例による"])
    c.sp_has("V3-18", f"{LT} §3.4", "令和8年法律第2号 附則第3条第12項（道府県民税）", sp8, "3", "12", ["九年一月新法附則第五条の四第一項から第四項までの規定は、道府県民税の所得割の納税義務者が令和八年一月一日以後に", "なお従前の例による"])
    c.sp_has("V3-19", f"{LT} §3.4", "令和4年法律第1号 附則第10条第3項（令和4年1月1日以後の居住に新法、前は従前の例）", sp4, "10", "3",
             ["新法附則第五条の四の二第五項から第八項までの規定は、市町村民税の所得割の納税義務者が令和四年一月一日以後に", "同日前に", "なお従前の例による"])
    c.sp_has("V3-20", f"{LT} §3.4", "令和4年法律第1号 附則第3条第3項（道府県民税）", sp4, "3", "3", ["新法附則第五条の四の二第一項から第四項までの規定は、道府県民税の所得割の納税義務者が令和四年一月一日以後に", "なお従前の例による"])
    c.sp_has("V3-21", f"{LT} §3.4", "令和4年法律第1号 附則第10条第6項（旧法附則第61条第3項による読替えの控除は従前の例）", sp4, "10", "6",
             ["旧法附則第六十一条第三項の規定により読み替えて適用される旧法附則第五条の四の二第五項の規定による控除については、なお従前の例による"])
    c.sp_has("V3-22", f"{LT} §3.4（追加）", "令和4年法律第1号 附則第1条第3号：附則第5条の4の2第1項・第5項の改正規定と附則第10条第1項〜第3項は令和5年1月1日施行", sp4, "1", "1",
             ["同法附則第五条の四の二第一項及び第五項", "第十条第一項から第三項まで及び第五項から第七項まで", "令和五年一月一日"])
    law4 = L("chiho", "2030-01-01")
    refs = [f"{an} {a}-{p}" for an, n in law4.suppl if an and an != R4 for a, p, t in suppl_paragraphs(law4, an) if re.search("令和四年法律第一号|令和四年改正法", t)]
    rec("V3-23", f"{LT} §3.4・§4-2", "e-Gov の地方税法（asof 2030-01-01）の改正附則で令和4年法律第1号を引く項は、同法自身の附則のほかにない", not refs, str(refs))
    pres = {asof: sorted(f"{a}-{p}" for a, p, t in suppl_paragraphs(L("chiho", asof), H31) if a in ("11", "18") and p in ("5", "6", "7"))
            for asof in ("2026-01-01", "2026-04-01", "2026-11-09", "2030-01-01")}
    rec("V3-24", f"{LT} §3.4（追加）", "e-Gov の版は改正附則が後の法律で改められたことを反映する：平成31年法律第2号 附則第11条・第18条の第5項〜第7項（令和8年法律第2号 第37条で削る）は 2026-01-01 にあり、2026-04-01 以後にない",
        len(pres["2026-01-01"]) == 6 and not pres["2026-04-01"] and not pres["2030-01-01"], str(pres))
    rec("V3-25", f"{LT} §3.4（追加）", "同じ e-Gov の asof 2030-01-01 で、令和4年法律第1号 附則第10条第3項は制定時の文言のまま（V3-19）", ("10", "3") in sp4 and "令和四年一月一日以後に" in sp4[("10", "3")], "")
    for asof, yrs, nendo in (("2021-12-31", "平成二十一年から令和三年まで", "令和十五年度"), ("2022-04-01", "平成二十一年から令和三年まで", "令和十五年度"),
                             ("2023-01-01", "平成二十一年から令和七年まで", "令和二十年度")):
        law_has("V3-26", f"{LT} §3.4（追加）・{HY} H3-2", f"asof {asof} の附則第5条の4の2第5項：居住年 {yrs}・{nendo}まで・3%・58,500円・基礎控除の加算なし", "chiho", [asof], "orig", "5_4_2", 5, None,
                [yrs, f"平成二十二年度から{nendo}までの各年度分", "百分の三", "五万八千五百円"], absent=["基礎控除", "四十八万円"], main_only=True)
        law_has("V3-27", f"{LT} §3.4（追加）", f"asof {asof} の附則第5条の4の2第7項：平成二十六年から令和三年まで・4.2%・81,900円", "chiho", [asof], "orig", "5_4_2", 7, None,
                ["居住年が平成二十六年から令和三年までであつて", "百分の四・二", "八万千九百円"])
    law_has("V3-30", f"{LT} §3.5", "附則第45条第4項（市町村民税・震災特例法第13条第1項）", "chiho", ["2026-11-09"], "orig", "45", 4, None,
            ["市町村民税の所得割の納税義務者が前年分の所得税につき震災特例法第十三条第一項の規定の適用を受けた場合における附則第五条の四の規定の適用"], main_only=True)
    law_has("V3-31", f"{LT} §3.5", "附則第45条第6項（平成26年〜令和3年、平成26年は4月1日以後、4.2%・81,900円）", "chiho", ["2026-11-09"], "orig", "45", 6, None,
            ["平成二十六年から令和三年までの居住年", "平成二十六年四月一日から同年十二月三十一日までの期間内の日であるものに限る", "「百分の三」とあるのは「百分の四・二」", "「五万八千五百円」とあるのは「八万千九百円」"])
    law_has("V3-32", f"{LT} §3.5", "附則第45条第3項（道府県民税）", "chiho", ["2026-11-09"], "orig", "45", 3, None, ["「百分の二」とあるのは「百分の二・八」"])
    law_has("V3-33", f"{LT} §3.5", "附則第61条第2項（「令和三年」→「令和四年」）", "chiho", ["2026-11-09"], "orig", "61", 2, None,
            ["附則第五条の四第七項及び第四十五条第六項の規定の適用については、これらの規定中「令和三年」とあるのは、「令和四年」とする"])
    law_has("V3-34", f"{LT} §3.5", "附則第61条第1項", "chiho", ["2026-11-09"], "orig", "61", 1, None, ["附則第五条の四第三項及び第四十五条第三項"])
    law_has("V3-35", f"{LT} §3.2", "所得税法第86条第2項（基礎控除の名）", "shotoku", ["2026-01-01"], "main", "86", 2, None, ["前項の規定による控除は、基礎控除という"])


def checks_versions(c):
    import difflib

    def lab(seq):
        m, out = {}, []
        for s in seq:
            if s is None:
                out.append("-")
                continue
            if s not in m:
                m[s] = chr(65 + len(m))
            out.append(m[s])
        return "".join(out)
    exp_tbl = {("main", "294"): "AABBBB", ("main", "24"): "AABBBB", ("main", "295"): "AAAAAA", ("main", "24_5"): "AAAAAA", ("main", "318"): "AAAAAA",
               ("main", "39"): "AAAAAA", ("main", "320"): "AAAAAA", ("main", "737"): "AAAAAA", ("main", "310"): "AAAAAA", ("main", "317_2"): "ABBBBB",
               ("main", "314_9"): "AAAAAA", ("main", "37_4"): "AAAAAA", ("main", "71_28"): "AAAAAA", ("main", "71_49"): "AAAAAA", ("main", "313"): "AABBBB",
               ("main", "23"): "ABCDEF", ("orig", "5_4"): "ABCCDD", ("orig", "45"): "AABBCC", ("orig", "61"): "AABBBB"}
    for (w, a), exp in exp_tbl.items():
        got = lab([c.node("chiho", v, w, a) for v in V6])
        c.rec("V4-tbl", f"{MS} §3.2", f"{w}:{a} の6版の並び {exp}", got == exp, got)
    for short, a in (("chiho-rei", "48_9_3"), ("chiho-rei", "48_9_4"), ("chiho-rei", "48_9_5"), ("chiho-kisoku", "1_12_2"), ("chiho-kisoku", "1_12_3")):
        got = lab([c.node(short, v, "main", a) for v in ("2026-01-01", "2026-11-09", "2027-01-01")])
        c.rec("V4-tbl2", f"{MS} §3.2・{LT} §2.3", f"{short}:{a} は 2026-01-01・2026-11-09・2027-01-01 で同じ", got == "AAA", got)
    for a in ("294", "24"):
        x, y = c.node("chiho", "2026-01-01", "main", a), c.node("chiho", "2026-04-01", "main", a)
        ops = [(x[i1:i2], y[j1:j2]) for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, x, y, autojunk=False).get_opcodes() if op != "equal"]
        ok = all(re.fullmatch(r"[マンション建替再生等敷地売却除却組合、及び]*", s1 + s2) for s1, s2 in ops)
        c.rec("V4-diff", f"{LT} §1.1・{MS} §3.2", f"第{a}条の 2026-01-01→2026-04-01 の違いはマンション関係の組合の名前だけ", ok, str(ops))
    AMEND_RE = (r"家屋敷|第二百九十四条|第二十四条第一項|第三百十四条の九|第三十七条の四|配当割額|株式等譲渡所得割額|附則第五条の四|住宅借入金"
                r"|特定配当等|第二十三条第一項第十五号|第三百十三条第十二項|第三十二条第十二項"
                r"|令和六年度以後の年度分|令和八年度以後の年度分|令和九年度以後の年度分|令和十年度以後の年度分")
    law = c.L("chiho", "2030-01-01")
    cnt = c48 = 0
    for an, n in law.suppl:
        if not an or not an.startswith("令和"):
            continue
        for a, p, t in suppl_paragraphs(law, an):
            if re.search(AMEND_RE, t):
                cnt += 1
                c48 += "四十八万円" in t
    all48 = [f"{an} {a}-{p}" for an, n in law.suppl if an for a, p, t in suppl_paragraphs(law, an) if "四十八万円" in t]
    c.rec("V4-amend", f"{MS} §4.2", "令和の改正附則で担当の正規表現（_laws.py の AMEND_RE）に当たる項は 47 件、そのうち「四十八万円」は 0", cnt == 47 and c48 == 0, f"件数={cnt}、四十八万円={c48}")
    c.rec("V4-amend48", f"{MS} §4.2（範囲を広げた）", "平成を含む全部の改正附則で「四十八万円」を含む項は 0", not all48, str(all48[:10]))


def checks_pdf(c):
    rec, pdf_at = c.rec, c.pdf_at
    meta = {e["name"]: e for e in c.log["web"]}
    for name in ("shichoson", "dofuken", "kaisei_tsuchi", "r8_houritsu"):
        pages, fonts = c.load_pdf(name)
        rec("V5-meta", f"{AD}・{MS} §2.3", f"{name}：頁数・フォント（情報）", None,
            f"頁={len(pages)} フォント={fonts} SHA-256={meta[name]['sha256'][:16]} Last-Modified={meta[name]['last_modified']}", kind="info")
    P = c.pdfs
    # 内容のストリームで実際に使われているフォント（Tf 演算子）と、そのエンコーディング
    exp_fonts = {"shichoson": {"F1": "WinAnsiEncoding", "F2": "Identity-H", "F3": "Identity-H"},
                 "dofuken": {"F1": "Identity-H", "F2": "Identity-H"},
                 "r8_houritsu": {"TT1": "Identity-H", "TT2": "Identity-V"}}
    for name, exp in exp_fonts.items():
        p = PDF((c.dl_web / f"{name}.pdf").read_bytes())
        used, npg = {}, {}
        for pg, res in p.pages():
            refs = pg.get("Contents")
            refs = refs if isinstance(refs, list) else (p.r(refs) if isinstance(p.r(refs), list) else [refs])
            data = b"\n".join(p.stream_of(x) for x in refs if isinstance(x, Ref))
            fonts = p.r(res.get("Font")) or {}
            for fn in set(re.findall(rb"/([A-Za-z0-9_]+)\s+[\d.]+\s+Tf", data)):
                fn = fn.decode()
                enc = (p.r(fonts.get(fn)) or {}).get("Encoding")
                used[fn] = enc if isinstance(enc, str) else type(enc).__name__
                npg[fn] = npg.get(fn, 0) + 1
        used, npg = dict(sorted(used.items())), dict(sorted(npg.items()))
        rec("V5-fonts", f"{MS} §2.3", f"{name}：使われているフォントは {exp}", used == exp, f"今回：{used}（使われた頁の数 {npg}）")
    rec("V5-pages", f"{AD} §1・§2.1・{MS} §2.3", "頁数：取扱通知（市町村税）142・（道府県税）199・総税企第44号 47・令和8年法律第2号 226",
        [len(P[n]) for n in ("shichoson", "dofuken", "kaisei_tsuchi", "r8_houritsu")] == [142, 199, 47, 226], str([len(P[n]) for n in ("shichoson", "dofuken", "kaisei_tsuchi", "r8_houritsu")]))
    S = "shichoson"
    pdf_at("V5-01", f"{AD} §1", "p.1 の改正の列の最後は令和8年4月1日総税市第25号", S, "令和８年４月１日総税市第２５号（目次）", [1])
    rec("V5-02", f"{AD} §1・{MS} §4.4", "取扱通知（市町村税）の「家屋敷」は p.31 の 1 回だけ", sum(t.count("家屋敷") for t in P[S]) == 1 and "家屋敷" in P[S][30], f"回数={sum(t.count('家屋敷') for t in P[S])}")
    pdf_at("V5-03", f"{AD} §1.1", "4の3（非課税の措置は適用されない）", S, "その所在する市町村において、均等割を課する。この場合においては、法第２９５条第１項の規定による非課税の措置は適用されないことに留意すること。（法２９４①Ⅱ）", [31])
    pdf_at("V5-04", f"{AD} §1.1", "5（法294③・④）", S, "（法２９４③・④）", [31])
    pdf_at("V5-05", f"{AD} §1.1", "6（１人１箇所）", S, "地方税法上その施行地を通じて１人１箇所に限られるものであること", [31])
    pdf_at("V5-06", f"{AD} §1.1", "6(1)（勤務日以外には家族のもと）", S, "勤務日以外には家族のもとにおいて生活をともにする者については、家族の居住地にあるものとする", [32])
    pdf_at("V5-07", f"{AD} §1.1", "6(2) ただし書（同一場所に1年以上）", S, "ただし、同一場所に１年以上居住している場合においては、本人の住所は、当該場所にあるものとして取り扱うこと", [32])
    pdf_at("V5-07b", f"{AD} §1.1", "6(3) 船員", S, "(３)船舶に乗り組んでいる船員の住所については", [32])
    pdf_at("V5-07c", f"{AD} §1.1", "6(4) たまたま出国した者", S, "(４)法施行地に住所を有するかどうかは、実質的に判断すべきであるから、たまたま出国した者であっても", [32])
    pdf_at("V5-07d", f"{AD} §1.1", "6(5) 公務員に所得税法第3条第1項は適用しない", S, "所得税法第３条第１項の規定は、個人住民税については、適用されないこと", [32])
    pdf_at("V5-07e", f"{AD} §1.1", "6(6) 自衛隊隊員", S, "(６)自衛隊隊員の住所については次の取扱いによるものであること", [32])
    pdf_at("V5-08", f"{AD} §1.1", "第1章第1節6（事務所又は事業所）", S, "事業の必要から設けられた人的及び物的設備であって、そこで継続して事業が行われる場所", [6])
    pdf_at("V5-09", f"{AD} §1.1", "第1章第1節6(2)（2、3か月程度の現場事務所）", S, "２、３か月程度の一時的な事業の用に供する目的で設けられる現場事務所、仮小屋等は事務所等の範囲に入らない", [6])
    pdf_at("V5-10", f"{AD} §1.1", "32（同日の現況）", S, "納税義務の有無に関する事実の認定は、同日の現況においてこれを行うものであること。（法３１８）", [57])
    pdf_at("V5-11", f"{AD} §1.1", "33の2（合算額で計算）", S, "個人の道府県民税及び個人の市町村民税の額の合算額によりこれらの規定を適用するものとする", [58])
    pdf_at("V5-12", f"{AD} §1.2", "25の2(1)（5分の3）", S, "当該配当割額又は当該株式等譲渡所得割額に５分の３を乗じて得た金額を、その者に係る所得割の額から控除するものであること", [50])
    pdf_at("V5-12b", f"{AD} §1.2", "25の2 の書き出し", S, "２５の２法第３１４条の９の規定の適用に当たっては", [49])
    pdf_at("V5-13", f"{AD} §1.2", "25の2(2)（賦課決定後・納税通知書の前）", S, "賦課決定後、納税通知書を発する前に、当該控除不足額のうち法第３１４条の９第２項後段に規定する還付をすべき金額", [50])
    pdf_at("V5-13b", f"{AD} §1.2", "25の2(2)（同一年度分）", S, "により同一年度分の個人の道府県民税、個人の市町村民税又は森林環境税を納付し", [50])
    pdf_at("V5-14", f"{AD} §1.2", "25の2(4)（未納に充て、残りを還付）", S, "それでもなお納付又は納入をすることができなかった部分の金額があるときは、当該金額を当該納税義務者に還付するものであること", [50])
    pdf_at("V5-15", f"{AD} §1.2", "25の2(6)（確定した日＝(2)の賦課決定の日）", S, "控除不足額が確定した日とは、(２)の賦課決定の日をいうものであること", [50])
    pdf_at("V5-16", f"{AD} §1.3", "28 柱書（法附則５の４⑤～⑧）", S, "２８法附則第５条の４の規定に基づく住宅借入金等特別税額控除の適用に当たっては、次の諸点に留意すること。（法附則５の４⑤～⑧）", [51])
    pdf_at("V5-17", f"{AD} §1.3", "28(1)（平成21年から令和12年まで）", S, "居住の用に供した年が平成２１年から令和１２年までの各年である所得割の納税義務者を対象とするものであること", [51])
    pdf_at("V5-18", f"{AD} §1.3", "28(2)（措法第41条の3の2 を適用しない）", S, "租税特別措置法第４１条の３の２の規定（特定の増改築等に係る住宅借入金等特別税額控除に係る控除額の特例の規定）については適用しないで計算する", [51])
    pdf_at("V5-19", f"{AD} §1.3", "28(3)（控除前の所得税額）", S, "住宅借入金等特別税額控除を行う前の段階の所得税額であること", [51])
    pdf_at("V5-20", f"{AD} §1.3", "28(4)（給与支払報告書等の記載）", S, "市町村は、給与支払報告書等の記載により、控除額を算出するために必要な情報を把握するものであること", [51])
    pdf_at("V5-21", f"{AD} §1.3", "28の3（税額控除の範囲は異ならない）", S, "前年中に非居住者であった期間を有する者についても税額控", [51])
    sec = P[S][50]
    i0, i1 = sec.find(N("２８法附則第５条の４")), sec.find(N("２８の３"))
    rec("V5-22", f"{AD} §1.3・{MS} §4.4", "28 の柱書〜(4) に「基礎控除」「４８万円」「四十八万円」は 0",
        i0 >= 0 and i1 > i0 and not any(k in sec[i0:i1] for k in ("基礎控除", "４８万円", "四十八万円", "48万円")), f"範囲の長さ={i1 - i0}")
    pdf_at("V5-23", f"{AD} §1.4", "26(2)（他の税額控除に先立ち）", S, "(２)この控除の額は、他の税額控除に先立ち、税率適用後の所得割の額から控除するものであること", [51])
    pdf_at("V5-23b", f"{AD} §1.4", "26 は調整控除の項", S, "２６調整控除の適用に当たっては", [50])
    pdf_at("V5-24", f"{AD} §1.4", "29（毎年3月15日まで）", S, "毎年３月１５日までに、法第３１７条の２第１項の申告書を提出しなければならないものであること", [51])
    pdf_at("V5-25", f"{AD} §1.4", "30（確定申告書の提出の日に申告書の提出があったものとみなす）", S, "当該確定申告書が提出された日に法第３１７条の２第１項から第４項までの規定による申告書が提出されたものとみなし", [52])
    pg_sp = [i + 1 for i, t in enumerate(P[S]) if "申告特例控除" in t]
    rec("V5-28", f"{LT} §4-8（未確認だった点）", "取扱通知（市町村税）で「申告特例控除」は p.48 の 1 回だけ（配当割額等の控除との順序の記述はない）（情報）", None,
        f"頁={pg_sp} 回数={sum(t.count('申告特例控除') for t in P[S])}", kind="info")
    D = "dofuken"
    pg_ie =[i + 1 for i, t in enumerate(P[D]) if "家屋敷" in t]
    pg_dk = [i + 1 for i, t in enumerate(P[D]) if "独立性" in t]
    rec("V5-26", f"{AD} §5-1・{MS} §4.4", "取扱通知（道府県税）の「家屋敷」は p.30 の 1 回、「独立性」は p.144 の 1 回（不動産取得税）",
        pg_ie == [30] and sum(t.count("家屋敷") for t in P[D]) == 1 and pg_dk == [144] and "不動産取得税" in P[D][143], f"家屋敷={pg_ie} 独立性={pg_dk}")
    pdf_at("V5-27", f"{AD} §1", "取扱通知（道府県税）の最後の改正は令和8年4月1日総税都第15号", D, "令和８年４月１日総税都第１５号（目次）", [1])
    K = "kaisei_tsuchi"
    pdf_at("V5-30", f"{AD} §2.1", "総税企第44号 第一 1(2)（同族会社との合計で 3% 以上 → 総合課税のまま配当割の対象）", K,
           "所得割の納税義務者が、自己の同族会社である法人との合計で株式等の保有割合が百分の三以上となる内国法人から支払を受ける上場株式等の配当等について、引き続き総合課税の対象とした上で、配当割の対象とする。（法第二十三条、第三十二条、令第七条の三関係）", [2])
    pdf_at("V5-31", f"{AD} §2.1", "総税企第44号 第一 1(10)（加算・令和二十五年度・令和十二年）", K,
           "（10）住宅借入金等特別税額控除について、以下の措置を講ずる。（法附則第五条の四関係）イ居住年が平成二十八年から令和七年までの各年である場合に係る控除限度額の計算上用いる所得税の課税総所得金額等について、前年分の所得税に係る基礎控除の額から四十八万円を控除して得た額を加算する。ロ適用期限を令和二十五年度分の個人の道府県民税及び居住年が令和十二年であるものまで延長する", [4])
    pdf_at("V5-32", f"{AD} §2.1", "総税企第44号 第二 1(8)（市町村民税）", K,
           "（８）住宅借入金等特別税額控除について、以下の措置を講ずる。（法附則第五条の四関係）イ居住年が平成二十八年から令和七年までの各年である場合に係る控除限度額の計算上用いる所得税の課税総所得金額等について、前年分の所得税に係る基礎控除の額から四十八万円を控除して得た額を加算する。ロ適用期限を令和二十五年度分の個人の市町村民税及び居住年が令和十二年であるものまで延長する", [14])
    rec("V5-33", f"{AD} §2.1・{MS} §4.4", "総税企第44号に「令和四年法律」は 0", not any("令和四年法律" in t for t in P[K]), "")
    R = "r8_houritsu"
    allr = "".join(f"<<p{i + 1}>>" + t for i, t in enumerate(P[R]))
    rec("V5-40", f"{LT} §3.4・{MS} §4.3", "令和8年法律第2号の本文 PDF に「令和四年法律第一」は 0", not any("令和四年法律第一" in t for t in P[R]),
        "「令和四年法律」は p." + str([i + 1 for i, t in enumerate(P[R]) if "令和四年法律" in t]) + "（いずれも令和四年法律第五十六号）")
    rec("V5-41", f"{MS} §4.3", "「四十八万円」は p.25・52・73・74・78", [i + 1 for i, t in enumerate(P[R]) if "四十八万円" in t] == [25, 52, 73, 74, 78], str([i + 1 for i, t in enumerate(P[R]) if "四十八万円" in t]))
    pdf_at("V5-42", f"{LT} §3.1", "本文 PDF に「（居住年が平成二十八年から令和七年までの」", R, "（居住年が平成二十八年から令和七年までの", [])
    heads = []
    for m in re.finditer(r"（([^（）]{2,200}?の一部改正)）(?=(?:<<p\d+>>-\d+-)?第[一二三四五六七八九十]+条)", allr):
        pg = re.findall(r"<<p(\d+)>>", allr[:m.start()])[-1]
        art = re.match(r"(?:<<p\d+>>-\d+-)?第([一二三四五六七八九十]+)条", allr[m.end():]).group(1)
        heads.append((int(pg), art, m.group(1)))
    kinds = sorted({h[2] for h in heads})
    rec("V5-43", f"{MS} §4.3", "「（…の一部改正）」の見出しは 15 種（「地方税法等の一部を改正する法律の一部改正」2 回・「地方税法等の一部を改正する等の法律の一部改正」1 回）",
        len(kinds) == 15 and sum(h[2] == "地方税法等の一部を改正する法律の一部改正" for h in heads) == 2,
        f"見出し {len(heads)} 個・{len(kinds)} 種：" + "; ".join(f"p.{p} 第{a}条 {k[:40]}" for p, a, k in heads))
    for kw, pg in (("第三十五条地方税法等の一部を改正する法律（平成二十六年法律第四号）の一部を次のように改正する", 222),
                   ("第三十六条地方税法等の一部を改正する等の法律の一部を次のように改正する。附則第四十条を次のように改める。第四十条削除附則第五十三条を次のように改める。第五十三条削除", 224),
                   ("第三十七条地方税法等の一部を改正する法律（平成三十一年法律第二号）の一部を次のように改正する。", 224),
                   ("附則第十一条第五項から第七項までを削る。附則第十八条第五項から第七項までを削る。", 225),
                   ("第三十四条総合特別区域法第二十二条の二第一項", 221),
                   ("第四条地方税法等の一部を改正する等の法律（平成二十八年法律第十三号）", 168)):
        pdf_at("V5-44", f"{MS} §4.3", f"p.{pg}：{kw[:34]}…", R, kw, [pg])
    rec("V5-45", f"{MS} §4.3", "第37条（平成31年法律第2号の一部改正）が附則第53条を「削除」とする", False,
        "附則第40条・第53条を「削除」とするのは第36条（平成28年法律第13号の一部改正）。第37条は平成31年法律第2号の附則第11条第5項〜第7項・第18条第5項〜第7項を削る（p.225）。p.224・225 は頁の画像でも確かめた → 訂正")
    p28 = [i + 1 for i, t in enumerate(P[R]) if "特定配当等" in t and i + 1 >= 212]
    rec("V5-47", f"{LT} §2.5", "本文 PDF の附則のうち他の法律の改正規定（第23条以後、p.212〜）にも「特定配当等」がある（情報）", None, f"p.{p28}", kind="info")


def checks_html(c):
    rec, h_has = c.rec, c.h_has
    for e in c.log["web"]:
        if e.get("saved", "").endswith(".html"):
            t, links, enc = html_text(c.dl_web / e["saved"])
            c.htm[e["name"]] = (N(t), links)
    h_has("V6-01", f"{AD} §2.2", "総務省の案内：平成21年から令和12年12月31日まで・翌年度の個人住民税", "soumu_juutaku_loan",
          ["平成21年から令和12年12月31日までの間に居住し", "翌年度の個人住民税において住宅ローン控除が適用されます"])
    h_has("V6-02", f"{AD} §2.2", "総務省の案内：5％(97,500円を限度)・7％(136,500円を限度)・平成26年から令和3年12月31日まで", "soumu_juutaku_loan",
          ["5％(97,500円を限度)", "7％(136,500円を限度)", "居住年が平成26年から令和3年12月31日までであって"])
    h_has("V6-03", f"{AD} §2.2", "総務省の案内：市区町村への申告は不要・手続は今までと変わらない", "soumu_juutaku_loan",
          ["個人住民税の住宅ローン控除の適用にあたって、市区町村への申告は不要です", "確定申告や年末調整で、住宅ローン控除を受ける方の手続きは、今までと変わりません"])
    h_has("V6-04", f"{AD} §2.2", "総務省の案内：算出例（225,000円・190,000円 → 35,000円）と注（源泉徴収税額が0円）。35,000円と注は画像の代替テキスト（alt）にある", "soumu_juutaku_loan",
          ["平成21年5月12日", "225,000円", "190,000円", "[alt]源泉徴収税額の項目が0円のときのみ、住宅ローン控除が適用になる場合があります。", "225,000-190,000＝35,000円"])
    h_has("V6-05", f"{AD} §2.2", "総務省の案内：旧制度は期限までに申告しなければ自動的に新制度", "soumu_juutaku_loan",
          ["期限までに申告されなかった場合は、自動的に、申告を不要とする新たな住宅ローン控除の適用を受けることになります"])
    h_has("V6-06", f"{AD} §2.2・§4.2", "総務省の案内に「基礎控除」「48万」はない", "soumu_juutaku_loan", [], absent=["基礎控除", "48万", "４８万"])
    h_has("V6-10", f"{AD} §4.1", "杉並区：平成21年から令和12年12月末・9万7,500円・13万6,500円・申告不要・更新日 2026年6月13日", "suginami_juutaku",
          ["平成21年から令和12年12月末までに入居", "9万7,500円", "13万6,500円", "区への申告（個人住民税の「住宅借入金等特別税額控除申告書」の提出）は不要です",
           "給与支払報告書や所得税の確定申告書等から内容を確認します", "2026年6月13日"], absent=["基礎控除"])
    h_has("V6-20", f"{AD} §3.1", "船橋市：対象・条例の額以下は課税されない・4,000円・月割なし・更新日 令和6(2024)年5月2日・根拠条文", "funabashi_ieyashiki",
          ["船橋市に住民登録をしていない人", "前年の合計所得金額が条例で定める金額以下の方は、課税されません", "均等割4,000円（市民税3,000円＋県民税1,000円）",
           "均等割については月割課税は行っていません", "更新日：令和6(2024)年5月2日", "地方税法第294条第1項第2号"])
    h_has("V6-21", f"{AD} §3.1", "船橋市：家屋敷とは（独立性・自己所有でなくても・現に居住していなくても・単身赴任者の妻子・貸付は除く・実質的な支配権）", "funabashi_ieyashiki",
          ["自己または家族の居住を目的に設けられた独立性のある住宅であり、自己所有でなくても、また現に居住していなくても、常に居住できる状態にあるもの",
           "生活の本拠地を別に設けている単身赴任者が妻子を常時住まわせている住宅（実家）等", "他人に貸し付ける目的で所有しているものや、現に他人に貸しているものには課税されません",
           "住居の実質的な支配権を持っている状態"])
    h_has("V6-30", f"{AD} §3.2", "熊本市：区以外の区・住民登録は関係ない・根拠条文・家屋敷の書き方・単身赴任の条件・配偶者の申告・最終更新日", "kumamoto_ieyashiki",
          ["熊本市内のお住まいの区以外の区に", "住民登録は関係ありません", "地方税法第24条第1項第2号、第294条第1項第2号、第737条", "いつでも自由に居住できる状態である",
           "熊本市内に居住する配偶者に市民税・県民税が課されていない方", "借家・持家は関係ありません", "家屋敷課税対象者の配偶者の方は、市県民税申告が必要です", "2022年8月19日"])
    h_has("V6-40", f"{AD} §3.3", "鹿児島市：条例第12条・独立性のある住宅・住民登録外居住者・4,500円（3,000円＋1,500円）・第24条第7項・更新日", "kagoshima_ieyashiki",
          ["鹿児島市税条例第12条", "自由に居住することができる独立性のある住宅", "住民登録外居住者として", "4,500円（市民税：3,000円＋県民税：1,500円）", "地方税法第24条第7項により", "2025年10月1日"])
    h_has("V6-50", f"{AD} §4.3", "目黒区：令和6年度分以降・大口株主等を除く・課税方式を一致・更新日", "meguro_kabu",
          ["令和6年度分以降の個人住民税より", "大口株主等が支払いを受けるものを除く", "課税方式を所得税と一致させることになりました", "2025年1月27日"])
    lk = [x for x in c.htm["ichiran04"][1] if x[0] and "001066281" in x[0]]
    rec("V6-60", f"{LT} §0・{MS} §2.2", "総務省の税制改正の一覧（ichiran04.html）に令和8年法律第2号の本文 PDF（001066281.pdf）へのリンクがある", bool(lk), str(lk))
    import email.utils
    meta = {e["name"]: e for e in c.log["web"]}
    exp_web = {"shichoson": ("2026-05-07", 792394, "107ba94cd6bd4b5e"), "dofuken": ("2026-08-14", 1001894, "b8c40110f3a48e8d"),
               "kaisei_tsuchi": ("2026-04-16", 531864, "321af651108b58ab"), "r8_houritsu": ("2026-03-31", 511245, "0282d962b36395be"),
               "soumu_juutaku_loan": ("2026-05-20", 45536, "43d772eb48c24aa0"), "suginami_juutaku": ("2026-08-04", 16203, "2c4fd2f6dc6568fd"),
               "funabashi_ieyashiki": ("2026-11-07", 27197, "550f8a5377cb5762"), "kumamoto_ieyashiki": ("2026-11-06", 72083, "8fcb806df6102fb5"),
               "kagoshima_ieyashiki": ("2026-03-16", 20309, "cdceb055e3354154"), "meguro_kabu": ("2026-10-29", 23214, "67ff67515578577a")}
    for n, (lm, b, h) in exp_web.items():
        e = meta[n]
        got_lm = email.utils.parsedate_to_datetime(e["last_modified"]).strftime("%Y-%m-%d") if e.get("last_modified") else None
        same = got_lm == lm and e.get("bytes") == b and e.get("sha256", "").startswith(h)
        rec("V6-web", f"{MS} §2.2・{AD}", f"{n}：Last-Modified {lm}・{b} バイト・SHA-256 先頭 {h}", True if same else None,
            f"今回：{got_lm} {e.get('bytes')} {e.get('sha256', '')[:16]}" + ("" if same else "（取得の時点で変わる動的なページ。引用した文は本文の検査で確かめた）"))
    rec("V6-robots", f"{MS} §2.2", "robots.txt：soumu.go.jp・city.kumamoto.jp・city.kagoshima.lg.jp は 200、ほかは 404",
        c.log["robots"] == {"www.soumu.go.jp": 200, "www.city.suginami.tokyo.jp": 404, "www.city.funabashi.lg.jp": 404, "www.city.kumamoto.jp": 200,
                            "www.city.kagoshima.lg.jp": 200, "www.city.meguro.tokyo.jp": 404}, str(c.log["robots"]))


def checks_cases(c):
    rec = c.rec
    lines = ["# 計算例の再計算（R3X juminzei-extra 検証）", "",
             "地方税法附則第5条の4（asof 2026-04-01 以後の版）と第314条の9・第37条の4 の式を条文から書き直して計算した（担当のコードは使っていない）。金額は Fraction。", ""]

    def jutaku(credit, tax, taxable, basic, kasan_on, shitei=False, tokutei=False):
        d = max(Fr(0), Fr(credit) - Fr(tax))
        base = Fr(taxable) + (max(Fr(0), Fr(basic) - 480000) if kasan_on else 0)
        if tokutei:
            sr, sc, kr, kc = (Fr(56, 1000), 109200, Fr(14, 1000), 27300) if shitei else (Fr(42, 1000), 81900, Fr(28, 1000), 54600)
        else:
            sr, sc, kr, kc = (Fr(4, 100), 78000, Fr(1, 100), 19500) if shitei else (Fr(3, 100), 58500, Fr(2, 100), 39000)
        sa, ka = (Fr(4, 5), Fr(1, 5)) if shitei else (Fr(3, 5), Fr(2, 5))
        return min(d * sa, min(base * sr, sc)), min(d * ka, min(base * kr, kc))
    exp_cases = [
        ("HC1", (200000, 75000, 1500000, 880000, True), {}, (57000, 38000)),
        ("HC1b", (200000, 75000, 1500000, 880000, False), {}, (45000, 30000)),
        ("HC2", (200000, 75000, 1500000, 880000, True), {"shitei": True}, (76000, 19000)),
        ("HC3", (200000, 75000, 1500000, 1040000, False), {}, (45000, 30000)),
        ("HC4", (400000, 100000, 3000000, 630000, True), {"tokutei": True}, (81900, 54600)),
        ("HC5", (150000, 180000, 2500000, 880000, True), {}, (0, 0)),
        ("HC6", (100001, 90000, 1500000, 880000, True), {}, (Fr(30003, 5), Fr(20002, 5))),
        ("HC8", (200000, 20000, 800000, 950000, True), {}, (38100, 25400)),
        ("HC9", (200000, 75000, 1500000, 1040000, True), {}, (58500, 39000)),
        ("F1-HX1-A", (240000, 0, 1000000, 880000, True), {}, (42000, 28000)),
        ("F1-HX1-B", (240000, 0, 1000000, 880000, False), {}, (30000, 20000)),
        ("F1-HX2-A", (240000, 0, 3000000, 880000, True), {}, (58500, 39000)),
        ("F1-HX2-B", (240000, 0, 3000000, 880000, False), {}, (58500, 39000)),
        ("F1-HX3-A", (30000, 0, 1000000, 880000, True), {}, (18000, 12000)),
        ("F1-HX4-A", (240000, 0, 1000000, 580000, True), {}, (33000, 22000)),
        ("F1-HX4-B", (240000, 0, 1000000, 580000, False), {}, (30000, 20000)),
    ]
    for cid, args, kw, exp in exp_cases:
        s, k = jutaku(*args, **kw)
        rec("V7-" + cid, f"{MS} §5", f"{cid}：市 {exp[0]}・県 {exp[1]}（合計 {exp[0] + exp[1]}）", (s, k) == tuple(Fr(x) for x in exp), f"再計算：市 {s}・県 {k}・合計 {s + k}")
        lines.append(f"- {cid}：(①, ②, 課税総所得金額等, 基礎控除, 加算) = {args} {kw} → 市 {s}（{float(s)}）・県 {k}（{float(k)}）・合計 {s + k}")
    pairs = ((Fr(3, 100), 58500), (Fr(2, 100), 39000), (Fr(4, 100), 78000), (Fr(1, 100), 19500), (Fr(42, 1000), 81900), (Fr(28, 1000), 54600), (Fr(56, 1000), 109200), (Fr(14, 1000), 27300))
    vals = sorted({cap / r for r, cap in pairs})
    rec("V7-195", f"{IN} I4-3", "上限に届く控除限度の基は 195万円（3%・58,500円、2%・39,000円。指定都市・特定取得の率と上限でも同じ）", vals == [1950000], str(vals))
    rec("V7-sum", f"{HY} H3-1", "市町村民税＋道府県民税＝5%・97,500円、7%・136,500円（一般の市・指定都市とも）",
        Fr(3, 100) + Fr(2, 100) == Fr(5, 100) == Fr(4, 100) + Fr(1, 100) and 58500 + 39000 == 78000 + 19500 == 97500
        and Fr(42, 1000) + Fr(28, 1000) == Fr(7, 100) == Fr(56, 1000) + Fr(14, 1000) and 81900 + 54600 == 109200 + 27300 == 136500, "")

    def haito(h, kb, s, k):
        ds, dk = Fr(h + kb) * Fr(3, 5), Fr(h + kb) * Fr(2, 5)
        return min(ds, s), min(dk, k), (ds - min(ds, s)) + (dk - min(dk, k))
    for cid, a, exp in (("DC1", (5000, 0, 10000, 6000), (3000, 2000, 0)), ("DC2", (5000, 0, 1000, 0), (1000, 0, 4000)), ("DC3", (1234, 2000, 50000, 30000), (Fr(9702, 5), Fr(6468, 5), 0))):
        got = haito(*a)
        rec("V7-" + cid, f"{MS} §5.1", f"{cid}：市で控除・県で控除・控除不足額 = {exp}", got == tuple(Fr(x) for x in exp), str(got))
        lines.append(f"- {cid}：(配当割額, 株式等譲渡所得割額, 市の所得割, 県の所得割) = {a} → 市で控除 {got[0]}・県で控除 {got[1]}・控除不足額 {got[2]}")

    def order(S, H, D, law_order=True):
        if law_order:
            s1 = max(0, S - H)
            return s1 - min(s1, D), D - min(s1, D)
        s1 = max(0, S - D)
        return max(0, s1 - H), max(0, D - S)
    for S, exp_law, exp_rev in ((10000, (0, 3000), (0, 0)), (20000, (7000, 0), (7000, 0)), (0, (0, 3000), (0, 3000))):
        g1, g2 = order(S, 10000, 3000, True), order(S, 10000, 3000, False)
        rec("V7-F2", f"{MS} §5.2・{HY} H4-3", f"F2 S={S}：法令の順（住宅→配当割）＝(所得割, 控除不足額) {exp_law}、逆の順＝{exp_rev}", g1 == exp_law and g2 == exp_rev, f"{g1} {g2}")
        lines.append(f"- F2 S={S}, H=10000, D=3000：法令の順 {g1}、逆の順 {g2}")
    (OUT / "cases.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def checks_author_outputs(c):
    rec = c.rec
    c2 = json.loads((ROOT / "scripts/results/R3X_juminzei-extra_checks2/checks.json").read_text(encoding="utf-8"))
    n_ok = sum(1 for x in c2 if x.get("ok") is True)
    n_cnt = sum(1 for x in c2 if x.get("ok") is None)
    rec("V8-c2", f"{MS} §3.1", "_checks2.py は OK 15 件（ほかに数えただけ 3 行）", n_ok == 15 and n_cnt == 3, f"OK={n_ok} 数えただけ={n_cnt}")
    c3 = json.loads((ROOT / "scripts/results/R3X_juminzei-extra_checks3/checks.json").read_text(encoding="utf-8"))
    rec("V8-c3", f"{MS} §3.1", "_checks3.py は OK 58 件（ほかに数えただけ 2 行）",
        sum(1 for x in c3 if x.get("ok") is True) == 58 and sum(1 for x in c3 if x.get("ok") is None) == 2, "")
    h3 = {f: hashlib.sha256((ROOT / "scripts/results/R3X_juminzei-extra_checks3" / f).read_bytes()).hexdigest()[:16] for f in ("evidence.md", "cases.md", "checks.json")}
    rec("V8-c3h", f"{MS} §3.1", "_checks3.py の出力の SHA-256 先頭（evidence.md 3290c49731afd81e、cases.md 68d9e672fe78b49a、checks.json a250b19ef5b77bbf）",
        h3 == {"evidence.md": "3290c49731afd81e", "cases.md": "68d9e672fe78b49a", "checks.json": "a250b19ef5b77bbf"}, str(h3))
    s1 = json.loads((ROOT / "scripts/results/R3X_juminzei-extra_checks/summary.json").read_text(encoding="utf-8"))
    rec("V8-c1", f"{MS} §3.1", "_checks.py は OK 394・NG 0", s1.get("ok") == 394 and s1.get("ng") == 0, f"{s1.get('ok')} {s1.get('ng')}")


def write_outputs(c):
    res = c.res
    (OUT / "checks.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    n_ok = sum(1 for r in res if r["ok"] is True)
    n_ng = sum(1 for r in res if r["ok"] is False)
    n_na = sum(1 for r in res if r["ok"] is None)
    md = ["# R3X juminzei-extra 検証：検査の結果", "",
          f"- 取得：{c.log['run_at']}（{c.log['dl_laws']}、{c.log['dl_web']}）。生成：scripts/R3X_juminzei-extra_verify.py",
          f"- 結果：OK {n_ok}・NG {n_ng}・判定なし {n_na}（情報、動的なページの差、文言の限定が要るもの）。NG は文書の記述と一次情報が合わないもの。", "",
          "| ID | 文書の箇所 | 文書の記述（期待） | 結果 | 見つかったもの |", "|---|---|---|---|---|"]
    for r in res:
        mark = {True: "OK", False: "**NG**", None: "—"}[r["ok"]]
        md.append(f"| {r['id']} | {r['doc']} | {r['claim'].replace('|', '｜')} | {mark} | {str(r['found']).replace('|', '｜').replace(chr(10), ' ')[:400]} |")
    (OUT / "evidence.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"OK {n_ok} NG {n_ng} NA {n_na}")
    for r in res:
        if r["ok"] is not True:
            print("NG" if r["ok"] is False else "--", r["id"], r["claim"][:70], "|", str(r["found"])[:260])


def run_checks(dl_laws, dl_web, log):
    c = Ctx(dl_laws, dl_web, log)
    checks_laws(c)
    checks_versions(c)
    checks_pdf(c)
    checks_html(c)
    checks_cases(c)
    checks_author_outputs(c)
    write_outputs(c)


# ---------------------------------------------------------------- 実行
def main():
    OUT.mkdir(parents=True, exist_ok=True)
    args = sys.argv[1:]
    if args and args[0] == "--use":
        dl_laws, dl_web = ROOT / args[1], ROOT / args[2]
        log = json.loads((OUT / "fetch_log.json").read_text(encoding="utf-8"))
    else:
        dl_laws, dl_web, log = fetch_all()
        (OUT / "fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    if "--fetch-only" in args:
        return
    run_checks(dl_laws, dl_web, log)


if __name__ == "__main__":
    main()

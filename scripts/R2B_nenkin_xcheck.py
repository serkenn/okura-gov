r"""R2B_nenkin（独立検証・反証役）：公的年金等の雑所得のトピックの文書（docs/*/20261109_round2b_nenkin-*）に書かれた
数値・条番号・通達番号・施行日・適用年分・URL を、一次情報を取り直して確かめる。

他の担当のスクリプト（scripts/R2B_nenkin_egov.py・R2B_nenkin_egov2.py・R2B_nenkin_web.py・R2B_nenkin_verify.py）は
import も再利用もしない。e-Gov 法令API v2 の使い方は scripts/R1_egov_articles.py を写した。

実行（Windows）:
  PY=C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe
  $PY -I -X utf8 scripts/R2B_nenkin_xcheck.py fetch_laws          # e-Gov 法令API v2（ネットワーク）
  $PY -I -X utf8 scripts/R2B_nenkin_xcheck.py fetch_web           # 国税庁・日本年金機構・地方公共団体（ネットワーク）
  $PY -I -X utf8 scripts/R2B_nenkin_xcheck.py dump <laws_dir>     # 条文を読むためのテキスト（ネットワーク不要）
  $PY -I -X utf8 scripts/R2B_nenkin_xcheck.py fetch_laws kokikourei  # 2回目：高齢者の医療の確保に関する法律だけ（推測 I1 の確認）
  $PY -I -X utf8 scripts/R2B_nenkin_xcheck.py webtext <web_dir>   # 読むための HTML のテキスト（.work/text/ に置く）
  $PY -I -X utf8 scripts/R2B_nenkin_xcheck.py compare_web         # 他の担当の取得記録と HTML・画像の SHA-256 を比べる（ネットワーク不要）
  $PY -I -X utf8 scripts/R2B_nenkin_xcheck.py show <json> main|orig|amend|list <Num...> [--amend <改正法令番号>]   # 条を表示
  $PY -I -X utf8 scripts/R2B_nenkin_xcheck.py analyze <laws_dir>[,<laws_dir2>] <web_dir> [<全整数の比較の上限>]   # 突き合わせ（ネットワーク不要）

- 標準ライブラリのみ。リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。個人の情報は送らない。官報は取得しない。
- ダウンロードしたものは信頼できないデータとして、取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_R2B_nenkin_xcheck_<laws|web>/ に置く（中で何も実行しない。読むだけ）。
- 結果は scripts/results/R2B_nenkin_xcheck/ に書く。
"""
import datetime
import hashlib
import html.parser
import json
import pathlib
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from fractions import Fraction as Fr

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
SLEEP = 1.5
OUT = ROOT / "scripts" / "results" / "R2B_nenkin_xcheck"

# (略称, law_id, [asof...], 改正附則を省くか)
LAWS = [
    ("shotoku", "340AC0000000033", ["2025-12-31", "2026-12-31", "2027-01-01"], False),
    ("shotoku-rei", "340CO0000000096", ["2025-12-31", "2026-01-01", "2026-12-31", "2027-01-01"], False),
    ("sochi", "332AC0000000026", ["2025-12-31", "2026-12-31", "2027-01-01"], True),
    ("sochi-rei", "332CO0000000043", ["2025-12-31", "2026-01-01", "2026-12-31", "2027-01-01"], False),
    ("chiho", "325AC0000000226", ["2026-01-01", "2027-01-01"], True),
    ("chiho-rei", "325CO0000000245", ["2026-01-01", "2027-01-01"], True),
    ("kokunen", "334AC0000000141", ["2026-11-09"], True),
    ("kounen", "329AC0000000115", ["2026-11-09"], True),
    ("kokkyo", "333AC0000000128", ["2026-11-09"], True),
    ("chikyo", "337AC0000000152", ["2026-11-09"], True),
    ("shigaku", "328AC0000000245", ["2026-11-09"], True),
    ("shienkyufu", "424AC0000000102", ["2026-11-09"], True),
    ("kenpo", "211AC0000000070", ["2026-11-09"], True),
    # 2回目（fetch_laws kokikourei）で足した：推測 I1 の「75歳以上は後期高齢者医療の被保険者」の確認用
    ("kokikourei", "357AC0000000080", ["2026-11-09"], True),
]
REVISIONS = [("shotoku-rei", "340CO0000000096"), ("sochi-rei", "332CO0000000043")]
LAWSEARCH = ["年金生活者支援給付金の支給に関する法律"]

TA = "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/"
KIHON = "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/"
WEB = {
    "robots_nta": "https://www.nta.go.jp/robots.txt",
    "robots_nenkin": "https://www.nenkin.go.jp/robots.txt",
    "robots_tokyo": "https://www.tax.metro.tokyo.lg.jp/robots.txt",
    "robots_higashiosaka": "https://www.city.higashiosaka.lg.jp/robots.txt",
    "robots_yokohama": "https://www.city.yokohama.lg.jp/robots.txt",
    "ta_1600": TA + "1600.htm",
    "ta_1605": TA + "1605.htm",
    "ta_1500": TA + "1500.htm",
    "ta_2011": TA + "2011.htm",
    "ta_1180_qa": TA + "1180_qa.htm",
    "kihon_02_02": KIHON + "02/02.htm",
    "kihon_04_09": KIHON + "04/09.htm",
    "kihon_05_01": KIHON + "05/01.htm",
    "kurashi_03_1": "https://www.nta.go.jp/publication/pamph/koho/kurashi/html/03_1.htm",
    "nenkin_faq_gensen_05": "https://www.nenkin.go.jp/faq/jukyu/uketori/tsuchisho/gensen/20140421-05.html",
    "nenkin_faq_fuyou_hikazei": "https://www.nenkin.go.jp/section/faq/jukyu/jukyushatodoke/rourei/fuyoushinkoku/shotoku/20140421-14.html",
    "nenkin_shotokuzeikojo": "https://www.nenkin.go.jp/service/jukyu/tetsuduki/rourei/jukyu/shotokuzeikojo.html",
    "tokyo_kojin_ju": "https://www.tax.metro.tokyo.lg.jp/kazei/life/kojin_ju",
    "higashiosaka_0000001683": "https://www.city.higashiosaka.lg.jp/0000001683.html",
    "yokohama_faq_answer6": "https://www.city.yokohama.lg.jp/kurashi/koseki-zei-hoken/zeikin/faq/answer6.html",
    "ta_1600_img01": TA + "img/1600_01.png",
    "ta_1600_img02": TA + "img/1600_02.png",
    "ta_1600_img03": TA + "img/1600_03.png",
}

BLOCK_LIKE = {"Paragraph", "Item"} | {f"Subitem{i}" for i in range(1, 11)}


# ---------------------------------------------------------------- ネットワーク
def get(url, accept="application/json", timeout=300):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept, "Accept-Language": "ja"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body, st, hdr, final = r.read(), r.status, dict(r.headers), r.geturl()
    except urllib.error.HTTPError as e:
        body, st, hdr, final = e.read(), e.code, dict(e.headers or {}), url
    time.sleep(SLEEP)
    return st, body, hdr, final


def new_dir(kind):
    ts = time.strftime("%Y%m%d-%H%M%S")
    d = ROOT / ".work" / "downloads" / f"{ts}_R2B_nenkin_xcheck_{kind}"
    d.mkdir(parents=True, exist_ok=False)
    return ts, d


def fetch_laws(only=None):
    """only：取得する略称のリスト（省略時はすべて＋改正履歴＋法令名検索）。"""
    ts, dl = new_dir("laws")
    OUT.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "user_agent": UA, "only": only, "fetches": []}
    for short, law_id, asofs, omit in LAWS:
        if only and short not in only:
            continue
        for asof in asofs:
            q = {"response_format": "json", "asof": asof}
            if omit:
                q["omit_amendment_suppl_provision"] = "true"
            url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode(q)
            st, body, _, _ = get(url)
            fn = f"{short}_{asof}.json"
            (dl / fn).write_bytes(body)
            ent = {"kind": "law_data", "short": short, "law_id": law_id, "asof": asof, "url": url, "status": st, "file": fn,
                   "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
            if st == 200:
                ri = (json.loads(body).get("revision_info") or {})
                for k in ("law_title", "law_revision_id", "amendment_law_title", "amendment_law_num", "amendment_promulgate_date",
                          "amendment_enforcement_date", "current_revision_status"):
                    ent[k] = ri.get(k)
            log["fetches"].append(ent)
            print("law", short, asof, st, ent.get("law_revision_id"), flush=True)
    for short, law_id in ([] if only else REVISIONS):
        q = urllib.parse.urlencode({"response_format": "json", "amendment_date_from": "2025-01-01"})
        url = f"{API}/law_revisions/{law_id}?{q}"
        st, body, _, _ = get(url)
        fn = f"revisions_{short}.json"
        (dl / fn).write_bytes(body)
        log["fetches"].append({"kind": "revisions", "short": short, "url": url, "status": st, "file": fn,
                               "sha256": hashlib.sha256(body).hexdigest()})
        print("rev", short, st, flush=True)
    for title in ([] if only else LAWSEARCH):
        q = urllib.parse.urlencode({"law_title": title, "response_format": "json"})
        url = f"{API}/laws?{q}"
        st, body, _, _ = get(url)
        fn = "lawsearch_shienkyufu.json"
        (dl / fn).write_bytes(body)
        log["fetches"].append({"kind": "laws", "title": title, "url": url, "status": st, "file": fn,
                               "sha256": hashlib.sha256(body).hexdigest()})
        print("search", title, st, flush=True)
    (OUT / ("fetch_laws_log.json" if not only else f"fetch_laws_log_{'_'.join(only)}.json")).write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", dl)


def fetch_web():
    ts, dl = new_dir("web")
    OUT.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "user_agent": UA, "fetches": []}
    for sid, url in WEB.items():
        rec = {"id": sid, "url": url}
        try:
            st, body, hdr, final = get(url, accept="*/*", timeout=60)
            ct = hdr.get("Content-Type", "")
            ext = ".png" if "png" in ct.lower() else (".txt" if sid.startswith("robots") else ".html")
            (dl / f"{sid}{ext}").write_bytes(body)
            rec.update({"status": st, "final_url": final, "content_type": ct, "bytes": len(body),
                        "sha256": hashlib.sha256(body).hexdigest(), "last_modified": hdr.get("Last-Modified"),
                        "etag": hdr.get("ETag"), "file": f"{sid}{ext}"})
        except Exception as e:  # noqa: BLE001
            rec["error"] = repr(e)
            time.sleep(SLEEP)
        log["fetches"].append(rec)
        print(json.dumps({k: rec.get(k) for k in ("id", "status", "bytes", "last_modified", "error")}, ensure_ascii=False), flush=True)
    (OUT / "fetch_web_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", dl)


# ---------------------------------------------------------------- 法令 JSON のテキスト化（R1_egov_articles.py を写した）
def inline(n):
    if isinstance(n, str):
        return n
    if n.get("tag") in ("Rt",):
        return ""
    parts = [inline(c) for c in n.get("children", [])]
    if n.get("tag", "").endswith("Sentence") and any(isinstance(c, dict) and c.get("tag") == "Column" for c in n.get("children", [])):
        return "　".join(p for p in parts if p)
    return "".join(parts)


def render(n, depth, lines):
    if isinstance(n, str):
        if n.strip():
            lines.append("  " * depth + n)
        return
    tag = n.get("tag", "")
    ch = n.get("children", [])
    if tag in BLOCK_LIKE:
        title = "".join(inline(c) for c in ch if isinstance(c, dict) and c.get("tag", "").endswith(("Num", "Title")) and c.get("tag") != "ParagraphCaption")
        sent = [c for c in ch if isinstance(c, dict) and c.get("tag", "").endswith("Sentence")]
        body = "　".join(inline(s) for s in sent)
        cap = [inline(c) for c in ch if isinstance(c, dict) and c.get("tag") == "ParagraphCaption"]
        if cap:
            lines.append("  " * depth + cap[0])
        num = n.get("attr", {}).get("Num", "")
        prefix = title if title else (f"（{tag}{num}）" if tag == "Paragraph" else "")
        lines.append("  " * depth + (prefix + "　" if prefix else "") + body)
        for c in ch:
            if isinstance(c, dict) and not (c.get("tag", "").endswith(("Num", "Title", "Sentence")) or c.get("tag") == "ParagraphCaption"):
                render(c, depth + 1, lines)
        return
    if tag == "TableRow":
        cells = [inline(c).replace("\n", " ") for c in ch if isinstance(c, dict)]
        lines.append("  " * depth + "| " + " | ".join(cells) + " |")
        return
    if tag in ("ArticleCaption", "ArticleTitle", "SupplProvisionLabel", "ChapterTitle", "SectionTitle"):
        lines.append("  " * depth + inline(n))
        return
    for c in ch:
        render(c, depth, lines)


def text_of(n):
    tl = []
    render(n, 0, tl)
    return "\n".join(tl)


def walk(n, fn, path=()):
    if isinstance(n, dict):
        fn(n, path)
        for c in n.get("children", []):
            walk(c, fn, path + (n,))


class Law:
    """取得した JSON 1つ。本則の条・原始附則の条・改正附則（AmendLawNum ごと）を引けるようにする。"""

    def __init__(self, path):
        d = json.loads(pathlib.Path(path).read_bytes())
        self.ri = d.get("revision_info") or {}
        self.root = d["law_full_text"]
        self.main, self.orig_suppl, self.amend = {}, {}, {}
        self.paragraph_nodes = {}

        def fn(n, path):
            if n.get("tag") != "Article":
                return
            sps = [p for p in path if p.get("tag") == "SupplProvision"]
            num = n["attr"].get("Num")
            if not sps:
                self.main[num] = n
            else:
                an = (sps[-1].get("attr") or {}).get("AmendLawNum")
                if not an:
                    self.orig_suppl[num] = n
                else:
                    self.amend.setdefault(an, {})[num] = n
        walk(self.root, fn)

    def art(self, num, where="main", amend=None):
        if where == "main":
            return self.main.get(num)
        if where == "orig":
            return self.orig_suppl.get(num)
        return self.amend.get(amend, {}).get(num)

    def text(self, num, where="main", amend=None):
        a = self.art(num, where, amend)
        return text_of(a) if a is not None else None

    def para(self, num, pnum, where="main", amend=None):
        a = self.art(num, where, amend)
        if a is None:
            return None
        for c in a.get("children", []):
            if isinstance(c, dict) and c.get("tag") == "Paragraph" and c["attr"].get("Num") == str(pnum):
                return text_of(c)
        return None

    def para_nums(self, num):
        a = self.art(num)
        if a is None:
            return []
        return [c["attr"].get("Num") for c in a.get("children", []) if isinstance(c, dict) and c.get("tag") == "Paragraph"]

    def sentences_with(self, word, include_caption=False):
        """語を含む Sentence の位置（本則／原始附則／改正附則、条）。"""
        hits = []

        def fn(n, path):
            if n.get("tag") == "Sentence" and word in inline(n):
                sps = [p for p in path if p.get("tag") == "SupplProvision"]
                arts = [p for p in path if p.get("tag") == "Article"]
                part = "main" if not sps else ("orig" if not (sps[-1].get("attr") or {}).get("AmendLawNum") else "amend:" + sps[-1]["attr"]["AmendLawNum"])
                hits.append((part, arts[-1]["attr"].get("Num") if arts else None))
        walk(self.root, fn)
        return hits


def load_laws(ddir):
    ddir = pathlib.Path(ddir)
    laws = {}
    for short, law_id, asofs, _ in LAWS:
        for asof in asofs:
            p = ddir / f"{short}_{asof}.json"
            if p.exists():
                laws[(short, asof)] = Law(p)
    return laws


DUMP = {
    "shotoku": (["2", "9", "22", "31", "34", "35", "36", "69", "120", "121", "203_2", "203_3", "203_5", "203_6", "203_7", "231"],
                ["令和七年三月三一日法律第一三号", "令和八年三月三一日法律第一二号"]),
    "shotoku-rei": (["20", "82_2", "258", "319_12"], None),
    "sochi": (["41_15_3", "41_15_4", "41_16_2"], []),
    "sochi-rei": (["26_27", "26_27_2"], None),
    "chiho": (["295", "313", "317_2", "317_3", "317_6", "321_3", "321_7_2"], []),
    "chiho-rei": (["56_89"], []),
    "kokunen": (["25"], []), "kounen": (["41"], []), "kokkyo": (["49"], []), "chikyo": (["52"], []),
    "shigaku": (["5"], []), "shienkyufu": (["33"], []), "kenpo": (["3"], []), "kokikourei": (["50", "51"], []),
}


def dump(ddir):
    laws = load_laws(ddir)
    OUT.mkdir(parents=True, exist_ok=True)
    for (short, asof), law in laws.items():
        arts, amends = DUMP[short]
        lines = [f"# {short} asof={asof} law_revision_id={law.ri.get('law_revision_id')} 改正法令={law.ri.get('amendment_law_num')} "
                 f"施行日={law.ri.get('amendment_enforcement_date')} 状態={law.ri.get('current_revision_status')}", ""]
        for num in arts:
            t = law.text(num)
            lines += [f"## 本則 Num={num}" + ("" if t else "：なし"), t or "", ""]
        for num in ("35_5",):
            if short == "chiho":
                lines += [f"## 原始附則 Num={num}", law.text(num, "orig") or "なし", ""]
        if amends is None:  # 政令：本文に 319の12・26の27 などを含む改正附則の条をすべて
            for an, arts2 in law.amend.items():
                for num, a in arts2.items():
                    t = text_of(a)
                    if any(k in t for k in ("第三百十九条の十二", "第二十六条の二十七", "第八十二条の二", "公的年金")) or (num == "1" and an.startswith(("令和七年", "令和八年"))):
                        lines += [f"## 改正附則 {an} Num={num}", t, ""]
        else:
            for an in amends:
                for num, a in law.amend.get(an, {}).items():
                    t = text_of(a)
                    if num == "1" or "公的年金" in t or "第二百三条の三" in t:
                        lines += [f"## 改正附則 {an} Num={num}", t, ""]
        (OUT / f"dump_{short}_{asof}.txt").write_text("\n".join(lines), encoding="utf-8")
    print("dumped", len(laws))


# ---------------------------------------------------------------- HTML のテキスト化（自作。他の担当のものは使わない）
class HtmlText(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript"}
    BREAK = {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "dt", "dd", "table", "section", "caption"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        if tag in self.BREAK:
            self.parts.append("\n")
        if tag in ("td", "th"):
            self.parts.append(" | ")
        if tag == "img":
            alt = dict(attrs).get("alt")
            if alt and not self.skip:
                self.parts.append(f"⟨{alt}⟩")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag in self.BREAK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def decode_html(body):
    m = re.search(rb"charset=[\"']?([\w\-]+)", body[:4000], re.I)
    cands = [m.group(1).decode("ascii", "replace")] if m else []
    for c in cands + ["utf-8", "cp932", "euc-jp"]:
        try:
            return body.decode(c)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", "replace")


def html_text(path):
    p = HtmlText()
    p.feed(decode_html(pathlib.Path(path).read_bytes()))
    t = "".join(p.parts)
    t = re.sub(r"[ \t　]+\n", "\n", t)
    return re.sub(r"\n{3,}", "\n\n", t)


def webtext(wdir):
    wdir = pathlib.Path(wdir)
    ts = time.strftime("%Y%m%d-%H%M%S")
    tdir = ROOT / ".work" / "text" / f"{ts}_R2B_nenkin_xcheck_web"
    tdir.mkdir(parents=True, exist_ok=False)
    for p in sorted(wdir.glob("*.html")):
        (tdir / (p.stem + ".txt")).write_text(html_text(p), encoding="utf-8")
    print("text", tdir)


# ---------------------------------------------------------------- 突き合わせ
KD = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def kan4(s):
    n, cur = 0, 0
    for ch in s:
        if ch in KD:
            cur = KD[ch]
        elif ch in "千百十":
            n += (cur or 1) * {"千": 1000, "百": 100, "十": 10}[ch]
            cur = 0
        else:
            raise ValueError(s)
    return n + cur


def kanyen(s):
    """「百五十五万五千円」→ 1555000。"""
    s = s.replace("円", "")
    total = 0
    if "万" in s:
        a, s = s.split("万", 1)
        total += kan4(a) * 10000
    return total + (kan4(s) if s else 0)


def norm(s):
    return re.sub(r"[\s　]", "", s or "")


def has(text, quote):
    """quote を「…」で区切った断片が、text の中にこの順で現れるか（空白は無視）。"""
    t = norm(text)
    pos = 0
    for frag in quote.split("…"):
        f = norm(frag)
        if not f:
            continue
        i = t.find(f, pos)
        if i < 0:
            return False
        pos = i + len(f)
    return True


# 公的年金等控除額・雑所得の金額（100倍の整数＝銭の単位で計算。条文から取り出した定数を使う）
def make_law_formula(K):
    """K：条文から取り出した定数の辞書。返り値 z100(A, O, age65) は公的年金等に係る雑所得の金額の100倍、k100 は控除額の100倍。"""
    def k100(A, O, age65):
        if O <= K["O1"]:
            base, mn = K["base1"], K["min1"]
        elif O <= K["O2"]:
            base, mn = K["base2"], K["min2"]
        else:
            base, mn = K["base3"], K["min3"]
        if age65:
            mn = K["min65"][mn]
        r = max(0, A - K["sub"])
        if r <= K["r1"]:
            b = r * K["p1"]
        elif r <= K["r2"]:
            b = K["c2"] * 100 + (r - K["r1"]) * K["p2"]
        elif r <= K["r3"]:
            b = K["c3"] * 100 + (r - K["r2"]) * K["p3"]
        else:
            b = K["c4"] * 100
        return max(mn * 100, base * 100 + b)

    def z100(A, O, age65):
        return max(0, A * 100 - k100(A, O, age65))
    return k100, z100


# TA No.1600 の速算表（図1〜図3）を、この検証者が画像を見て書き写したもの（他の担当の書き写しは使わない）。
# 区分ごとに (0円の上限［以下］, 「収入−x」の帯の上限［未満］, 差し引く額：x, ×0.75, ×0.85, ×0.95, 1,000万円以上)
NTA_IMG = {
    (1, False): (600_000, 1_300_000, 600_000, 275_000, 685_000, 1_455_000, 1_955_000),
    (1, True): (1_100_000, 3_300_000, 1_100_000, 275_000, 685_000, 1_455_000, 1_955_000),
    (2, False): (500_000, 1_300_000, 500_000, 175_000, 585_000, 1_355_000, 1_855_000),
    (2, True): (1_000_000, 3_300_000, 1_000_000, 175_000, 585_000, 1_355_000, 1_855_000),
    (3, False): (400_000, 1_300_000, 400_000, 75_000, 485_000, 1_255_000, 1_755_000),
    (3, True): (900_000, 3_300_000, 900_000, 75_000, 485_000, 1_255_000, 1_755_000),
}


def z100_nta(A, tier, age65):
    zero, lin_hi, x, m75, m85, m95, mtop = NTA_IMG[(tier, age65)]
    if A <= zero:
        return 0
    if A < lin_hi:
        return (A - x) * 100
    if A < 4_100_000:
        return A * 75 - m75 * 100
    if A < 7_700_000:
        return A * 85 - m85 * 100
    if A < 10_000_000:
        return A * 95 - m95 * 100
    return (A - mtop) * 100


def age_L(birth, day):
    """年齢計算ニ関スル法律・民法143条：n歳に達するのは n 年目の応当日の前日の終了時（応当日がなければ月末の終了時）。day の終了時の年齢。"""
    nxt = day + datetime.timedelta(days=1)
    return nxt.year - birth.year - (1 if (nxt.month, nxt.day) < (birth.month, birth.day) else 0)


def analyze(laws_dirs, web_dir, exhaustive_max=15_000_000):
    laws = {}
    for d in laws_dirs.split(","):
        laws.update(load_laws(d))
    wdir = pathlib.Path(web_dir)
    web = {p.stem: html_text(p) for p in wdir.glob("*.html")}
    wlog = {f["id"]: f for f in json.loads((OUT / "fetch_web_log.json").read_text(encoding="utf-8"))["fetches"]}
    CH = []

    def add(cid, doc, sec, claim, ok, detail=""):
        CH.append({"id": cid, "doc": doc, "section": sec, "claim": claim,
                   "result": ("OK" if ok is True else "NG" if ok is False else ok), "detail": detail})

    def L(short, asof):
        return laws[(short, asof)]

    def lq(cid, doc, sec, short, asof, num, quote, para=None, where="main", amend=None, claim=None):
        law = L(short, asof)
        t = law.para(num, para, where, amend) if para else law.text(num, where, amend)
        ok = t is not None and has(t, quote)
        add(cid, doc, sec, claim or f"{short} asof={asof} Num={num}{'' if not para else ' ¶' + str(para)}：「{quote[:60]}…」", ok,
            "" if ok else ("条が見つからない" if t is None else "引用の断片が原文に見つからない"))

    def wq(cid, doc, sec, page, quote, claim=None):
        ok = has(web.get(page, ""), quote)
        add(cid, doc, sec, claim or f"{page}：「{quote[:60]}」", ok, "" if ok else "本文に見つからない")

    # ===== 版（PS §0、M §1）
    flog = json.loads((OUT / "fetch_laws_log.json").read_text(encoding="utf-8"))["fetches"]
    got = {(f["short"], f["asof"]): f for f in flog if f.get("kind") == "law_data"}
    expect_rev = {
        ("shotoku", "2025-12-31"): ("340AC0000000033_20251218_507AC0000000013", "PreviousEnforced", "令和七年法律第十三号"),
        ("shotoku", "2026-12-31"): ("340AC0000000033_20261201_508AC0000000012", "UnEnforced", "令和八年法律第十二号"),
        ("shotoku", "2027-01-01"): ("340AC0000000033_20270101_508AC0000000012", "UnEnforced", "令和八年法律第十二号"),
        ("shotoku-rei", "2025-12-31"): ("340CO0000000096_20251201_507CO0000000120", "PreviousEnforced", "令和七年政令第百二十号"),
        ("shotoku-rei", "2026-01-01"): ("340CO0000000096_20260101_507CO0000000120", "PreviousEnforced", "令和七年政令第百二十号"),
        ("shotoku-rei", "2026-12-31"): ("340CO0000000096_20261201_508CO0000000093", "UnEnforced", "令和八年政令第九十三号"),
        ("shotoku-rei", "2027-01-01"): ("340CO0000000096_20270101_508CO0000000093", "UnEnforced", "令和八年政令第九十三号"),
        ("sochi", "2025-12-31"): ("332AC0000000026_20251231_507AC1000000081", "PreviousEnforced", "令和七年法律第八十一号"),
        ("sochi", "2026-12-31"): ("332AC0000000026_20261204_508AC0000000012", "UnEnforced", "令和八年法律第十二号"),
        ("sochi", "2027-01-01"): ("332AC0000000026_20270101_508AC0000000012", "UnEnforced", "令和八年法律第十二号"),
        ("sochi-rei", "2025-12-31"): ("332CO0000000043_20251231_507CO0000000401", "PreviousEnforced", "令和七年政令第四百一号"),
        ("sochi-rei", "2026-01-01"): ("332CO0000000043_20260101_507CO0000000277", "PreviousEnforced", "令和七年政令第二百七十七号"),
        ("sochi-rei", "2026-12-31"): ("332CO0000000043_20261201_508CO0000000098", "UnEnforced", "令和八年政令第九十八号"),
        ("sochi-rei", "2027-01-01"): ("332CO0000000043_20270101_508CO0000000098", "UnEnforced", "令和八年政令第九十八号"),
        ("chiho", "2026-01-01"): ("325AC0000000226_20260101_507AC0000000041", "PreviousEnforced", "令和七年法律第四十一号"),
        ("chiho", "2027-01-01"): ("325AC0000000226_20270101_508AC0000000002", "UnEnforced", "令和八年法律第二号"),
        ("chiho-rei", "2026-01-01"): ("325CO0000000245_20260101_507CO0000000119", "PreviousEnforced", "令和七年政令第百十九号"),
        ("chiho-rei", "2027-01-01"): ("325CO0000000245_20270101_508CO0000000083", "UnEnforced", "令和八年政令第八十三号"),
        ("kokunen", "2026-11-09"): ("334AC0000000141_20261001_507AC0000000074", "CurrentEnforced", "令和七年法律第七十四号"),
        ("kounen", "2026-11-09"): ("329AC0000000115_20261001_507AC0000000074", "CurrentEnforced", "令和七年法律第七十四号"),
        ("kokkyo", "2026-11-09"): ("333AC0000000128_20261001_507AC0000000087", "CurrentEnforced", "令和七年法律第八十七号"),
        ("chikyo", "2026-11-09"): ("337AC0000000152_20261001_507AC0000000087", "CurrentEnforced", "令和七年法律第八十七号"),
        ("shigaku", "2026-11-09"): ("328AC0000000245_20261001_507AC0000000087", "CurrentEnforced", "令和七年法律第八十七号"),
        ("shienkyufu", "2026-11-09"): ("424AC0000000102_20250601_504AC0000000068", None, None),
    }
    for k, (rid, st, an) in expect_rev.items():
        f = got.get(k, {})
        ok = f.get("law_revision_id") == rid and (st is None or f.get("current_revision_status") == st) and (an is None or f.get("amendment_law_num") == an)
        add(f"REV-{k[0]}-{k[1]}", "PS/M", "PS §0・M §1", f"{k[0]} asof={k[1]}：{rid}／{st}／{an}", ok,
            f"取得：{f.get('law_revision_id')}／{f.get('current_revision_status')}／{f.get('amendment_law_num')}")
    # 他の担当の生データの SHA-256（同じ問い合わせのものだけ比べる）
    author_sha = {}
    for lp in ("scripts/results/R2B_nenkin_egov/fetch_log.json", "scripts/results/R2B_nenkin_egov2/fetch_log.json"):
        for f in json.loads((ROOT / lp).read_text(encoding="utf-8"))["fetches"]:
            if f.get("asof") and f.get("url"):
                author_sha[(f["short"], f["asof"], "omit_amendment_suppl_provision=true" in f["url"])] = f["sha256"]
    same_q = 0
    for (short, asof), f in got.items():
        omit = "omit_amendment_suppl_provision=true" in f["url"]
        a = author_sha.get((short, asof, omit))
        if a:
            same_q += 1
            add(f"SHA-{short}-{asof}", "M", "M §1", f"{short} asof={asof} の生データ（同じ問い合わせ）の SHA-256 が他の担当の取得と同じ", a == f["sha256"],
                f"他の担当 {a[:16]}／検証 {f['sha256'][:16]}")
    revs = {}
    for f in flog:
        if f.get("kind") == "revisions":
            d = json.loads((pathlib.Path(laws_dirs.split(",")[0]) / f["file"]).read_bytes())
            revs[f["short"]] = len(d.get("revisions", []))
    add("REV-count", "M", "M §1", "改正履歴（2025-01-01 以後）：所令 16 版・措令 35 版", revs.get("shotoku-rei") == 16 and revs.get("sochi-rei") == 35, str(revs))

    # ===== PS §1.1 公的年金等の範囲
    S8, S7, S9 = "2026-12-31", "2025-12-31", "2027-01-01"
    lq("PS1.1-35-1", "PS", "§1.1", "shotoku", S8, "35", "雑所得とは、利子所得、配当所得、不動産所得、事業所得、給与所得、退職所得、山林所得、譲渡所得及び一時所得のいずれにも該当しない所得をいう。", 1)
    lq("PS1.1-35-2", "PS", "§1.1", "shotoku", S8, "35", "雑所得の金額は、次の各号に掲げる金額の合計額とする。…一　その年中の公的年金等の収入金額から公的年金等控除額を控除した残額…二　その年中の雑所得（公的年金等に係るものを除く。）に係る総収入金額から必要経費を控除した金額", 2)
    lq("PS1.1-35-3", "PS", "§1.1", "shotoku", S8, "35", "前項に規定する公的年金等とは、次に掲げる年金をいう。…第三十一条第一号及び第二号（退職手当等とみなす一時金）に規定する法律の規定に基づく年金その他同条第一号及び第二号に規定する制度に基づく年金（これに類する給付を含む。…）で政令で定めるもの…二　恩給（一時恩給を除く。）及び過去の勤務に基づき使用者であつた者から支給される年金…三　確定給付企業年金法の規定に基づいて支給を受ける年金…その他これに類する年金として政令で定めるもの", 3)
    lq("PS1.1-31-1-ell", "PS", "§1.1", "shotoku", S8, "31", "国民年金法、厚生年金保険法…、国家公務員共済組合法…、地方公務員等共済組合法…、私立学校教職員共済法…及び独立行政法人農業者年金基金法…の規定に基づく一時金その他これらの法律の規定による社会保険又は共済に関する制度に類する制度に基づく一時金…で政令で定めるもの", 1,
       claim="所法31①一（法律番号の括弧を「…」として読む）")
    t31 = L("shotoku", S8).para("31", 1)
    add("PS1.1-31-1-literal", "PS", "§1.1", "所法31①一の引用が、括弧（法律番号）を省いたことを示さずに連続した文として書かれている（「厚生年金保険法、国家公務員共済組合法、…」）",
        not has(t31, "国民年金法、厚生年金保険法、国家公務員共済組合法、地方公務員等共済組合法、私立学校教職員共済法及び独立行政法人農業者年金基金法の規定に基づく一時金"),
        "原文は各法律名の後に（昭和二十九年法律第百十五号）などの括弧がある。省略の表示がない（引用の形式の誤り。内容は同じ）")
    r82a, r82b = L("shotoku-rei", S7), L("shotoku-rei", S8)
    a82 = r82b.art("82_2")
    add("PS1.1-82_2-caption", "PS", "§1.1", "所令82の2の見出し「公的年金等とされる年金」", "公的年金等とされる年金" in (r82b.text("82_2") or ""), "")
    add("PS1.1-82_2-same", "PS", "§1.1", "所令82の2 は 2025-12-31 版と 2026-12-31 版で同文", r82a.text("82_2") == r82b.text("82_2"), "")
    p1 = [c for c in a82["children"] if isinstance(c, dict) and c.get("tag") == "Paragraph" and c["attr"].get("Num") == "1"][0]
    nitems = sum(1 for c in p1["children"] if isinstance(c, dict) and c.get("tag") == "Item")
    add("PS1.1-82_2-1-13", "PS", "§1.1", "所令82の2①は13号", nitems == 13, f"号の数 {nitems}")
    lq("PS1.1-82_2-2-1", "PS", "§1.1", "shotoku-rei", S8, "82_2", "第七十二条第三項第一号又は第九号（退職手当等とみなす一時金）に規定する制度に基づいて支給される年金", 2)
    lq("PS1.1-82_2-2-6", "PS", "§1.1", "shotoku-rei", S8, "82_2", "確定拠出年金法…老齢給付金として支給される年金", 2)
    lq("PS1.1-82_2-2-4", "PS", "§1.1", "shotoku-rei", S8, "82_2", "適格退職年金契約に基づいて支給を受ける退職年金", 2)
    lq("PS1.1-82_2-4", "PS", "§1.1", "shotoku-rei", S8, "82_2", "前項に規定する給付として支給される金額は、法第三十五条第三項に規定する公的年金等に係る雑所得以外の雑所得に係る収入金額とする。", 4)
    lq("PS1.1-82_2-3-76", "PS", "§1.1", "shotoku-rei", S8, "82_2", "第七十六条第一項各号…に掲げる給付（年金に該当するものに限る。）を含まないもの", 3,
       claim="所令82の2④の「前項に規定する給付」は③の所令76条①各号・②各号の給付（PS の「所令76条の給付」の要約の確認）")
    lq("NEW-72-3-9", "PS", "§1.2・§10-2", "shotoku-rei", S8, "72", "九　外国の法令に基づく保険又は共済に関する制度で法第三十一条第一号及び第二号に規定する法律の規定による社会保険又は共済に関する制度に類するものに基づいて支給される一時金", 3,
       claim="（追加）所令72③九＝外国の法令に基づく保険又は共済に関する制度。所令82の2②一がこれを引くので、外国の制度に基づく年金は所法35③三の公的年金等（PS §10-2 の経路）")
    lq("PS1.1-69", "PS", "§1.1", "shotoku", S8, "69", "不動産所得の金額、事業所得の金額、山林所得の金額又は譲渡所得の金額の計算上生じた損失の金額があるときは", 1,
       claim="（参考）所法69①が損益通算の対象を不動産・事業・山林・譲渡の損失に限ること（TA1500 の記述と整合）")
    wq("PS1.1-TA1500", "PS", "§1.1", "ta_1500", "雑所得の金額の計算上生じた損失の金額は、他の所得の金額と損益通算はできません")
    wq("PS1.1-TA1500-date", "PS", "§1.1", "ta_1500", "[令和8年4月1日現在法令等]")

    # ===== PS §1.2
    for q in ["[令和8年4月1日現在法令等]",
              "（1）国民年金法、厚生年金保険法、公務員等の共済組合法などの規定による年金（2）過去の勤務により会社などから支払われる年金（3）確定給付企業年金法の規定に基づいて支給を受ける年金（4）外国の法令に基づく保険または共済に関する制度で（1）に掲げる法律の規定による社会保険または共済制度に類するものに基づいて支給を受ける年金",
              "生命保険契約や生命共済契約に基づく年金、互助年金などは公的年金等には該当しません。",
              "所法35、121、203の2、203の3、所令82の2、措法41の15の3"]:
        wq("PS1.2-TA1600", "PS", "§1.2", "ta_1600", q)
    add("PS1.2-TA1600-LM", "PS", "§1.2", "TA1600 Last-Modified 2026-09-09", "09 Sep 2026" in (wlog["ta_1600"].get("last_modified") or ""), wlog["ta_1600"].get("last_modified"))
    wq("PS1.2-kihon35-5", "PS", "§1.2", "kihon_04_09", "在職中に使用者に対して所定の掛金を拠出することにより退職後当該使用者であった者から支給される年金は、法第35条第3項第2号に規定する公的年金等とする。この場合において、その公的年金等の収入金額は、その年中に支給される年金の額から受給者が拠出した掛金…の額を基として")
    wq("PS1.2-kihon35-8", "PS", "§1.2", "kihon_04_09", "法第35条第4項各号に規定する「公的年金等に係る雑所得以外の合計所得金額」は、その年中の公的年金等の収入金額がないものとして計算した場合における合計所得金額をいうのであるから、措置法第41条の3の11第2項((所得金額調整控除))の規定による所得金額調整控除の適用はないものとして計算することに留意する。")
    add("PS1.2-kihon04-LM", "PS", "§1.2", "所基通 04/09.htm Last-Modified 2024-11-25", "25 Nov 2024" in (wlog["kihon_04_09"].get("last_modified") or ""), wlog["kihon_04_09"].get("last_modified"))
    for q in ["国民年金、厚生年金、恩給、確定給付企業年金、確定拠出年金、一定の外国年金など", "生命保険契約や生命共済契約に基づく年金、互助年金など", "暮らしの税情報」（令和８年度版）"]:
        wq("PS1.2-kurashi", "PS", "§1.2", "kurashi_03_1", q)
    add("PS1.2-kurashi-LM", "PS", "§1.2", "暮らしの税情報 03_1.htm Last-Modified 2026-07-09", "09 Jul 2026" in (wlog["kurashi_03_1"].get("last_modified") or ""), wlog["kurashi_03_1"].get("last_modified"))

    # ===== PS §2.1 所法35④
    q354 = ("第二項に規定する公的年金等控除額は、次の各号に掲げる場合の区分に応じ当該各号に定める金額とする。…一　その年中の公的年金等の収入金額がないものとして計算した場合における第二条第一項第三十号（定義）に規定する合計所得金額（次号及び第三号において「公的年金等に係る雑所得以外の合計所得金額」という。）が千万円以下である場合　次に掲げる金額の合計額（当該合計額が六十万円に満たない場合には、六十万円）"
            "…イ　四十万円…ロ　その年中の公的年金等の収入金額から五十万円を控除した残額の次に掲げる場合の区分に応じそれぞれ次に定める金額"
            "…当該残額が三百六十万円以下である場合　当該残額の百分の二十五に相当する金額"
            "…当該残額が三百六十万円を超え七百二十万円以下である場合　九十万円と当該残額から三百六十万円を控除した金額の百分の十五に相当する金額との合計額"
            "…当該残額が七百二十万円を超え九百五十万円以下である場合　百四十四万円と当該残額から七百二十万円を控除した金額の百分の五に相当する金額との合計額"
            "…当該残額が九百五十万円を超える場合　百五十五万五千円"
            "…二　その年中の公的年金等に係る雑所得以外の合計所得金額が千万円を超え二千万円以下である場合　次に掲げる金額の合計額（当該合計額が五十万円に満たない場合には、五十万円）…イ　三十万円…ロ　前号ロに掲げる金額"
            "…三　その年中の公的年金等に係る雑所得以外の合計所得金額が二千万円を超える場合　次に掲げる金額の合計額（当該合計額が四十万円に満たない場合には、四十万円）…イ　二十万円…ロ　第一号ロに掲げる金額")
    for a in (S7, S8, S9):
        lq(f"PS2.1-35-4-{a}", "PS", "§2.1", "shotoku", a, "35", q354, 4)
    s35 = {a: [L("shotoku", a).para("35", i) for i in (1, 2, 3, 4)] for a in (S7, S8, S9)}
    add("PS2.1-35-same", "PS/M", "§2.1・M V1", "所法35①〜④は 2025-12-31・2026-12-31・2027-01-01 で同文", s35[S7] == s35[S8] == s35[S9], "")
    pn = {a: L("shotoku", a).para_nums("35") for a in (S7, S8, S9)}
    add("PS2.1-35-5", "PS/M", "§2.1・M V1", "所法35⑤は 2027-01-01 版にだけある", pn[S7] == pn[S8] == ["1", "2", "3", "4"] and pn[S9] == ["1", "2", "3", "4", "5"], str(pn))
    lq("PS2.1-35-5-280", "PS", "§2.1", "shotoku", S9, "35", "給与所得控除額とその年中の第三項に規定する公的年金等に係る前項に規定する公的年金等控除額との合計額が二百八十万円を超える場合", 5)
    lq("PS2.1-R8-5", "PS", "§2.1", "shotoku", S9, "5", "新所得税法第三十五条第五項の規定は、令和九年分以後の所得税について適用する。", 1, "amend", "令和八年三月三一日法律第一二号",
       claim="令和8年法律第12号附則第5条：新35⑤は令和9年分以後")
    no_frac = all(not re.search(r"端数|円未満", L("shotoku", a).text("35")) for a in (S7, S8)) and all(not re.search(r"端数|円未満", L("sochi", a).text("41_15_3")) for a in (S7, S8))
    add("PS2.1-nofrac", "PS", "§2.1・§10-1", "所法35・措法41の15の3 に端数（円未満）の処理の定めがない", no_frac, "「端数」「円未満」の語が0件")

    # ===== PS §2.2 措法41の15の3
    for a in (S7, S8, S9):
        lq(f"PS2.2-41153-1-{a}", "PS", "§2.2", "sochi", a, "41_15_3", "年齢が六十五歳以上である個人が、平成十七年以後の各年において、その年中の所得税法第三十五条第三項に規定する公的年金等…の収入金額がある場合における当該公的年金等に係る同条第四項…の規定の適用については、同法第三十五条第四項第一号中「六十万円に」とあるのは「百十万円に」と、「六十万円）」とあるのは「百十万円）」と、同項第二号中「五十万円」とあるのは「百万円」と、同項第三号中「四十万円」とあるのは「九十万円」とする。", 1)
        lq(f"PS2.2-41153-4-{a}", "PS", "§2.2", "sochi", a, "41_15_3", "第一項の個人の年齢が六十五歳以上であるかどうかの判定はその年十二月三十一日（その者が年の中途において死亡し、又は所得税法第二条第一項第四十二号に規定する出国をする場合には、その死亡又は出国の時）の年齢によるものとし、第二項の居住者又は前項の非居住者の年齢が六十五歳以上であるかどうかの判定はその年十二月三十一日の年齢によるものとする。", 4)
    add("PS2.2-caption", "PS", "§2.2", "措法41の15の3の見出し「公的年金等控除の最低控除額等の特例」", "（公的年金等控除の最低控除額等の特例）" in L("sochi", S8).text("41_15_3"), "")
    s4115 = {a: L("sochi", a) for a in (S7, S8, S9)}
    add("PS2.2-same-1-3-4", "PS/M", "§2.2・M V1", "措法41の15の3①③④は3つの版で同文", all(s4115[S7].para("41_15_3", i) == s4115[S8].para("41_15_3", i) == s4115[S9].para("41_15_3", i) for i in (1, 3, 4)), "")
    p2 = {a: s4115[a].para("41_15_3", 2) for a in (S7, S8, S9)}
    exp2 = {S7: ("九万円", "十三万五千円"), S8: ("十万円", "十四万円"), S9: ("十万五千円", "十四万五千円")}
    for a, (x, y) in exp2.items():
        add(f"PS2.2-41153-2-{a}", "PS", "§2.2・§5.1", f"措法41の15の3② asof={a}：所法203の3 第1号イ・第4号の「{x}」→「{y}」", has(p2[a], f"同条第一号イ及び第四号中「{x}」とあるのは、「{y}」とする。"), "")
    p2n = {a: re.sub(r"「[^「」]*万[^「」]*円」", "「X」", p2[a]) for a in p2}
    add("PS2.2-41153-2-onlyamt", "M", "M V1", "措法41の15の3②の版の違いは金額の読替えだけ", p2n[S7] == p2n[S8] == p2n[S9], "")

    # 式の定数を条文から取り出す
    t4 = L("shotoku", S8).para("35", 4)
    tS = L("sochi", S8).para("41_15_3", 1)
    K = {
        "base1": kanyen(re.search(r"一　その年中の公的年金等の収入金額がない.*?\n\s*イ　(.+?)\n", t4, re.S).group(1)),
        "min1": kanyen(re.search(r"千万円以下である場合.*?六十万円に満たない場合には、(.+?)）", t4, re.S).group(1)),
        "base2": kanyen(re.search(r"二千万円以下である場合.*?\n\s*イ　(.+?)\n", t4, re.S).group(1)),
        "min2": kanyen(re.search(r"二千万円以下である場合.*?満たない場合には、(.+?)）", t4, re.S).group(1)),
        "base3": kanyen(re.search(r"二千万円を超える場合.*?\n\s*イ　(.+?)\n", t4, re.S).group(1)),
        "min3": kanyen(re.search(r"二千万円を超える場合.*?満たない場合には、(.+?)）", t4, re.S).group(1)),
        "sub": kanyen(re.search(r"収入金額から(.+?)を控除した残額の次に", t4).group(1)),
        "r1": kanyen(re.search(r"当該残額が(.+?)以下である場合　当該残額の百分の", t4).group(1)),
        "p1": int(kan4(re.search(r"当該残額の百分の(.+?)に相当する金額", t4).group(1))),
        "r2": kanyen(re.search(r"を超え(.+?)以下である場合　九十万円と", t4).group(1)),
        "c2": kanyen(re.search(r"以下である場合　(.+?)と当該残額から三百六十万円", t4).group(1)),
        "p2": int(kan4(re.search(r"三百六十万円を控除した金額の百分の(.+?)に相当", t4).group(1))),
        "r3": kanyen(re.search(r"七百二十万円を超え(.+?)以下である場合", t4).group(1)),
        "c3": kanyen(re.search(r"以下である場合　(.+?)と当該残額から七百二十万円", t4).group(1)),
        "p3": int(kan4(re.search(r"七百二十万円を控除した金額の百分の(.+?)に相当", t4).group(1))),
        "c4": kanyen(re.search(r"九百五十万円を超える場合　(.+?)$", t4, re.M).group(1)),
        "O1": 10_000_000, "O2": 20_000_000,
    }
    rd2 = {kanyen(a): kanyen(b) for a, b in re.findall(r"「([一二三四五六七八九十百千]+万円)(?:に|）)?」とあるのは「([一二三四五六七八九十百千]+万円)(?:に|）)?」", tS)}
    K["min65"] = rd2
    add("V-consts", "M", "M V1・V2", "条文（2026-12-31 版）から取り出した式の定数", K["base1"] == 400_000 and K["min1"] == 600_000 and K["base2"] == 300_000 and K["min2"] == 500_000
        and K["base3"] == 200_000 and K["min3"] == 400_000 and K["sub"] == 500_000 and K["r1"] == 3_600_000 and K["p1"] == 25 and K["r2"] == 7_200_000 and K["c2"] == 900_000
        and K["p2"] == 15 and K["r3"] == 9_500_000 and K["c3"] == 1_440_000 and K["p3"] == 5 and K["c4"] == 1_555_000 and rd2 == {600_000: 1_100_000, 500_000: 1_000_000, 400_000: 900_000},
        json.dumps({k: v for k, v in K.items() if k != "min65"}, ensure_ascii=False) + f" 措法の読替え {rd2}")
    k100, z100 = make_law_formula(K)

    # ===== PS §2.3 速算表：PS の表（65歳未満・65歳以上、区分1）と区分2・3 の注記を、この検証者の書き写し（NTA_IMG）と比べる
    ps_tbl = {(1, False): (600_000, 1_300_000, 600_000, 275_000, 685_000, 1_455_000, 1_955_000),
              (1, True): (1_100_000, 3_300_000, 1_100_000, 275_000, 685_000, 1_455_000, 1_955_000),
              (2, False): (500_000, 1_300_000, 500_000, 175_000, 585_000, 1_355_000, 1_855_000),
              (2, True): (1_000_000, 3_300_000, 1_000_000, 175_000, 585_000, 1_355_000, 1_855_000),
              (3, False): (400_000, 1_300_000, 400_000, 75_000, 485_000, 1_255_000, 1_755_000),
              (3, True): (900_000, 3_300_000, 900_000, 75_000, 485_000, 1_255_000, 1_755_000)}
    add("PS2.3-table", "PS", "§2.3", "PS の速算表の値（区分1の表と区分2・3の注記）が画像（図1〜3）の書き写しと同じ", ps_tbl == NTA_IMG, "")
    for i in (1, 2, 3):
        lm = wlog[f"ta_1600_img0{i}"].get("last_modified") or ""
        add(f"PS2.3-img{i}-LM", "PS", "§2.3", f"1600_0{i}.png Last-Modified 2024-04-09", "09 Apr 2024" in lm, lm)
    wq("PS2.3-ex", "PS/M", "§2.3・M V4", "ta_1600", "3,500,000円×75％-275,000円＝2,350,000円")
    for q in ["注１:令和8年分の所得税については、65歳未満の方とは昭和37年1月2日以後に生まれた方、65歳以上の方とは昭和37年1月1日以前に生まれた方になります。",
              "注２:公的年金等に係る雑所得以外の所得金額が1,000万円以下である場合の表です。",
              "注：住民税を算出する際の年金等に係る雑所得の計算方法も同様になります。"]:
        wq("PS2.3-kurashi", "PS", "§2.3", "kurashi_03_1", q)

    # ===== M V2・V3：全整数での比較と、他の担当の点の集合の再現
    t0 = time.time()
    mism = {}
    frac = {}
    frac_range = {}
    tiers = {1: 5_000_000, 2: 15_000_000, 3: 25_000_000}
    for tier, O in tiers.items():
        for age65 in (False, True):
            m = 0
            fc = 0
            lo, hi = None, None
            first = None
            for A in range(0, exhaustive_max + 1):
                zl = z100(A, O, age65)
                if zl != z100_nta(A, tier, age65):
                    m += 1
                    if first is None:
                        first = A
                if zl % 100:
                    fc += 1
                    if lo is None:
                        lo = A
                    hi = A
            mism[(tier, age65)] = (m, first)
            frac[(tier, age65)] = fc
            frac_range[(tier, age65)] = (lo, hi)
    secs = time.time() - t0
    add("V2-exhaustive", "M", "M V2", f"条文の式と速算表（検証者の書き写し）が 0〜{exhaustive_max:,}円のすべての整数・6表で一致", all(v[0] == 0 for v in mism.values()),
        json.dumps({f"{k[0]}-{'65以上' if k[1] else '65未満'}": v for k, v in mism.items()}, ensure_ascii=False) + f"（{secs:.0f}秒）")
    add("V3-frac-range", "PS/H", "H8", "円未満の端数が出る収入の範囲：65歳未満 130万円超〜1,000万円未満、65歳以上 330万円超〜1,000万円未満（全区分）",
        all(frac_range[(t, False)] == (1_300_001, 9_999_999) and frac_range[(t, True)] == (3_300_001, 9_999_999) for t in (1, 2, 3)),
        json.dumps({f"{k[0]}-{'65以上' if k[1] else '65未満'}": v for k, v in frac_range.items()}, ensure_ascii=False) + "；全整数での端数の点の数 " + json.dumps({f"{k[0]}-{'65以上' if k[1] else '65未満'}": v for k, v in frac.items()}, ensure_ascii=False))
    # 他の担当の点の集合（scripts/R2B_nenkin_verify.py の作り方。M V2 の説明と比べる）
    def pointset(bnd):
        pts = set(range(0, 12_000_001, 1000))
        for b in bnd:
            for d in range(-5, 6):
                if b + d >= 0:
                    pts.add(b + d)
        rng = random.Random(20261109)
        for _ in range(200_000):
            pts.add(rng.randrange(0, 15_000_000))
        return sorted(pts)
    bnd_doc = [400_000, 500_000, 600_000, 900_000, 1_000_000, 1_100_000, 1_300_000, 3_300_000, 4_100_000, 7_700_000, 9_500_000, 10_000_000]
    pts_doc = pointset(bnd_doc)
    pts_scr = pointset(bnd_doc + [10_000_001])
    fc_scr = {}
    for tier, O in tiers.items():
        for age65 in (False, True):
            fc_scr[(tier, age65)] = sum(1 for A in pts_scr if z100(A, O, age65) % 100)
    add("V2-points", "M", "M V2", "比べた点は重複を除いて 210,677 点", len(pts_scr) == 210_677,
        f"スクリプトの作り方（境目に 10,000,001 を含む）{len(pts_scr):,} 点／M の文の列挙どおり（10,000,001 を含まない）{len(pts_doc):,} 点")
    add("V3-counts", "M", "M V3", "端数が出る点：65歳未満 102,280・65歳以上 82,388（各区分で同じ）",
        all(fc_scr[(t, False)] == 102_280 and fc_scr[(t, True)] == 82_388 for t in (1, 2, 3)), json.dumps({f"{k[0]}-{k[1]}": v for k, v in fc_scr.items()}))
    ex = {1_300_001: 70_000_075, 1_300_002: 70_000_150, 4_100_001: 280_000_085, 7_700_001: 586_000_095}
    add("V3-examples", "M", "M V3", "例：1,300,001→700,000.75、1,300,002→700,001.50、4,100,001→2,800,000.85、7,700,001→5,860,000.95",
        all(z100(a, 5_000_000, False) == v for a, v in ex.items()), str({a: z100(a, 5_000_000, False) / 100 for a in ex}))
    edges = {10_000_000: (775_000, 1_100_000), 10_000_001: (675_000, 1_000_000), 20_000_000: (675_000, 1_000_000), 20_000_001: (575_000, 900_000)}
    add("V2-edges", "M", "M V2", "収入 200万円での控除額：O=1,000万→77.5万/110万、1,000万1→67.5万/100万、2,000万→67.5万/100万、2,000万1→57.5万/90万",
        all((k100(2_000_000, o, False) // 100, k100(2_000_000, o, True) // 100) == v for o, v in edges.items()), "")
    add("V4", "PS/M", "§2.3・M V4", "65歳以上・O=500万・収入350万 → 2,350,000円", z100(3_500_000, 5_000_000, True) == 235_000_000, str(z100(3_500_000, 5_000_000, True) / 100))

    # ===== PS §3 収入すべき時期
    lq("PS3-36", "PS", "§3", "shotoku", S8, "36", "その年において収入すべき金額", 1)
    wq("PS3-36-14", "PS", "§3", "kihon_05_01", "36−14　雑所得の収入金額又は総収入金額の収入すべき時期は、次に掲げる区分に応じそれぞれ次に掲げる日によるものとする。")
    wq("PS3-36-14b", "PS", "§3", "kihon_05_01", "イ　公的年金等の支給の基礎となる法令、契約、規程又は規約（以下この(1)において「法令等」という。）により定められた支給日…ロ　法令等の改正、改訂が既往にさかのぼって実施されたため既往の期間に対応して支払われる新旧公的年金等の差額で、その支給日が定められているものについてはその支給日、その日が定められていないものについてはその改正、改訂の効力が生じた日…（注）　裁定、改定等の遅延、誤びゅう等により既往にさかのぼって支払われる公的年金等については、法令等により定められた当該公的年金等の計算の対象とされた期間に係る各々の支給日によることに留意する。")
    add("PS3-LM", "PS", "§3", "所基通 05/01.htm Last-Modified 2025-11-25", "25 Nov 2025" in (wlog["kihon_05_01"].get("last_modified") or ""), wlog["kihon_05_01"].get("last_modified"))

    # ===== PS §4.1 公課の禁止
    T = "2026-11-09"
    lq("PS4.1-kokunen", "PS", "§4.1", "kokunen", T, "25", "（公課の禁止）…租税その他の公課は、給付として支給を受けた金銭を標準として、課することができない。ただし、老齢基礎年金及び付加年金については、この限りでない。")
    lq("PS4.1-kounen", "PS", "§4.1", "kounen", T, "41", "租税その他の公課は、保険給付として支給を受けた金銭を標準として、課することができない。ただし、老齢厚生年金については、この限りでない。", 2)
    lq("PS4.1-kokkyo", "PS", "§4.1", "kokkyo", T, "49", "（公課の禁止）…租税その他の公課は、組合の給付として支給を受ける金品を標準として、課することができない。ただし、退職年金及び公務遺族年金並びに休業手当金については、この限りでない。")
    lq("PS4.1-chikyo", "PS", "§4.1", "chikyo", T, "52", "（公課の禁止）…租税その他の公課は、組合の給付として支給を受ける金品を標準として、課することができない。ただし、退職年金及び公務遺族年金並びに休業手当金については、この限りでない。")
    lq("PS4.1-shigaku", "PS", "§4.1", "shigaku", T, "5", "（非課税）…この法律に基づく給付として支給を受ける金品のうち、退職年金及び職務遺族年金並びに休業手当金以外の給付については、これを標準として、租税その他の公課を課さない。")
    lq("PS4.1-shien", "PS", "§4.1", "shienkyufu", T, "33", "（公課の禁止）…租税その他の公課は、年金生活者支援給付金として支給を受けた金銭を標準として、課することができない。")
    # ===== PS §4.2
    lq("PS4.2-9-1-3", "PS", "§4.2", "shotoku", S8, "9", "三　恩給、年金その他これらに準ずる給付で次に掲げるもの…イ　恩給法…に規定する増加恩給（これに併給される普通恩給を含む。）及び傷病賜金その他公務上又は業務上の事由による負傷又は疾病に基因して受けるこれらに準ずる給付で政令で定めるもの…ロ　遺族の受ける恩給及び年金（死亡した者の勤務に基づいて支給されるものに限る。）…ハ　条例の規定により地方公共団体が精神又は身体に障害のある者に関して実施する共済制度で政令で定めるものに基づいて受ける給付", 1)
    wq("PS4.2-kihon9-2", "PS", "§4.2", "kihon_02_02", "法第9条第1項第3号ロに掲げる年金には、次に掲げるものが含まれる。…（1）　死亡した者の勤務に基づき、使用者であった者から当該死亡した者の遺族に支給される年金…（2）　死亡した者がその勤務に直接関連して加入した社会保険又は共済に関する制度、退職年金制度等に基づき、当該死亡した者の遺族に支給される年金で、当該死亡した者が生存中に支給を受けたとすれば法第35条第3項《雑所得》の規定によりその者の公的年金等とされるもの")
    add("PS4.2-LM", "PS", "§4.2", "所基通 02/02.htm Last-Modified 2024-01-18", "18 Jan 2024" in (wlog["kihon_02_02"].get("last_modified") or ""), wlog["kihon_02_02"].get("last_modified"))
    # ===== PS §4.3
    for q in ["[令和8年4月1日現在法令等]", "国民年金法、厚生年金保険法、恩給法、旧船員保険法、国家公務員共済組合法、地方公務員等共済組合法、私立学校教職員共済法、旧農林漁業団体職員共済組合法",
              "原則として所得税も相続税も課税されません", "毎年受け取る年金には所得税が課税されません", "その遺族の一時所得の収入金額に該当します", "所法9、34、所令82の2、所基通9-2、34-2"]:
        wq("PS4.3-TA1605", "PS", "§4.3", "ta_1605", q)
    for q in ["扶養親族や同一生計配偶者に該当するか否かを判定する場合の合計所得金額には、所得税法やその他の法令の規定によって非課税とされる所得の金額は含まれないことになっています。",
              "厚生年金保険法に基づく遺族厚生年金や国民年金法に基づく遺族基礎年金などは非課税所得ですから、お母さんの合計所得金額は58万円以下", "令和8年分から適用される金額は「62万円以下」", "(所法2、9、所基通2-41、9-2)",
              "非課税所得や次の（1）から（5）のような所得は扶養控除が受けられるかどうかを判定する場合の合計所得金額から除かれます。"]:
        wq("PS4.3-TA1180", "PS", "§4.3", "ta_1180_qa", q)
    t1180 = web.get("ta_1180_qa", "")
    i = t1180.find("（1）から（5）のような所得")
    blk = t1180[i:i + 600]
    add("PS4.3-TA1180-nopension", "PS/H", "§4.3・H4", "TA1180 の除外の類型（1）〜（5）に公的年金等の雑所得が挙がっていない", "年金" not in blk and "（5）" in blk, "")
    for q in ["傷病者や遺族などの受け取る恩給、年金等(所法9①三、所令20)", "非課税所得は、所得金額の計算から除かれますから、非課税の適用を受けるための手続は原則として必要ありません。"]:
        wq("PS4.3-TA2011", "PS", "§4.3", "ta_2011", q)
    for q in ["更新日：2024年12月27日", "障害年金や遺族年金は、所得税および復興特別所得税の課税対象となっていないため（非課税）、", "公的年金等の源泉徴収票が送付されるのは、老齢または退職を支給事由とする年金を受けている方だけとなります（年金生活者支援給付金は含まれません）。"]:
        wq("PS4.3-nenkin-gensen", "PS", "§4.3", "nenkin_faq_gensen_05", q)
    for q in ["更新日：2026年9月3日", "死亡を支給事由とする年金（遺族が受ける恩給も含みます。）", "障害を支給事由とする年金（障害を負ったことにより受ける恩給も含みます。）", "雇用保険の失業給付", "労働者災害補償保険の給付"]:
        wq("PS4.3-nenkin-fuyou", "PS", "§4.3", "nenkin_faq_fuyou_hikazei", q)
    for q in ["更新日：2026年9月3日", "老齢年金（※）には、所得税法により、「雑所得」として所得税、防衛特別所得税および", "なお、障害年金、遺族年金には税金はかかりません。", "※老齢年金とは、老齢または退職を支給事由とする年金（老齢福祉年金を除く。）をいいます。"]:
        wq("PS4.3-nenkin-kojo", "PS", "§4.3", "nenkin_shotokuzeikojo", q)

    # ===== PS §5.1 源泉徴収
    lq("PS5.1-203_2", "PS", "§5.1", "shotoku", S8, "203_2", "居住者に対し国内において第三十五条第三項（公的年金等の定義）に規定する公的年金等…の支払をする者は、その支払の際、その公的年金等について所得税を徴収し、その徴収の日の属する月の翌月十日までに、これを国に納付しなければならない。", 1)
    exp203 = {S7: ("六万五千円", "九万円"), S8: ("七万五千円", "十万円"), S9: ("七万五千円", "十万五千円")}
    for a, (x, y) in exp203.items():
        lq(f"PS5.1-203_3-{a}", "PS", "§5.1", "shotoku", a, "203_3", f"イ　当該公的年金等の月割額として政令で定める金額の百分の二十五に相当する金額に{x}を加算した金額と{y}とのいずれか多い金額", 1)
    lq("PS5.1-203_3-rate", "PS", "§5.1", "shotoku", S8, "203_3", "控除した残額に百分の五（…百分の十）の税率を乗じて計算した金額とする", 1)
    lq("PS5.1-R7-10", "PS", "§5.1", "shotoku", S8, "10", "新所得税法第二百三条の三及び第二百三条の四の二の規定は、令和八年一月一日以後に支払うべき所得税法第二百三条の二に規定する公的年金等…について適用し", 1, "amend", "令和七年三月三一日法律第一三号",
       claim="令和7年法律第13号附則第10条第1項：新203の3 は令和8年1月1日以後に支払うべき公的年金等に適用")
    lq("PS5.1-R8-1-5", "PS", "§5.1", "shotoku", S9, "1", "五　次に掲げる規定　令和九年一月一日…第一条中所得税法第三十五条に一項を加える改正規定…同法第二百三条の三の改正規定", 1, "amend", "令和八年三月三一日法律第一二号",
       claim="（補足）令和8年法律第12号附則第1条第5号：35条に1項を加える改正・203の3の改正は令和9年1月1日施行（2027-01-01 版の 10万5千円）")
    lq("PS5.1-203_5", "PS", "§5.1", "shotoku", S8, "203_5", "公的年金等の支払の際控除される第七十四条第二項（社会保険料控除）に規定する社会保険料がある場合　その公的年金等の金額に相当する金額から当該社会保険料の金額を控除した残額に相当する金額の公的年金等の支払があつたものとみなし", 1)
    lq("PS5.1-203_6", "PS", "§5.1", "shotoku", S8, "203_6", "四　源泉控除対象親族（当該支払を受ける日の属する年の第二条第一項第三十号（定義）に規定する合計所得金額の見積額が八十五万円を超える者を除く。", 1)
    lq("PS5.1-203_7", "PS", "§5.1", "shotoku", S8, "203_7", "居住者が前条第一項に規定する公的年金等の支払を受ける場合において、その年中に支払を受けるべき当該公的年金等の額がその年最初に当該公的年金等の支払を受けるべき日の前日の現況において政令で定める金額に満たないときは、当該公的年金等については、第二百三条の二（源泉徴収義務）の規定による所得税の徴収及び納付は、要しないものとする。", 1)
    lq("PS5.1-203_6-def", "H", "H6", "shotoku", S8, "203_6", "国内において公的年金等（確定給付企業年金等を除く。）の支払を受ける居住者が", 1,
       claim="（H6 の読みの確認）203の7 の「前条第一項に規定する公的年金等」は 203の6①の「国内において…（確定給付企業年金等を除く。）」")
    lq("PS5.1-231", "PS", "§5.1", "shotoku", S8, "231", "居住者に対し国内において給与等、退職手当等又は公的年金等の支払をする者は、…支払明細書を、その支払を受ける者に交付しなければならない。", 1)
    lq("PS5.1-41154-1", "PS", "§5.1", "sochi", S8, "41_15_4", "国民年金法…又は厚生年金保険法…の消滅時効が完成した場合において、これらの権利の消滅時効を援用せずに居住者に支払うこととされた所得税法第三十五条第三項に規定する公的年金等については、同法第二百三条の二の規定は、適用しない。", 1)
    lq("PS5.1-41154-2", "PS", "§5.1", "sochi", S8, "41_15_4", "所得税法第百二十一条第三項の規定の適用については、同項中「の規定の」とあるのは、「又は租税特別措置法第四十一条の十五の四第一項（消滅時効を援用せずに支払うこととされた公的年金等に対する源泉徴収の不適用）の規定の」とする。", 2)

    # ===== PS §5.2 源泉徴収を要しない額
    reiwa = {"令和七年": 2025, "令和八年": 2026, "令和九年": 2027}

    def chain(year, asof):
        so = L("shotoku-rei", asof).text("319_12")
        base = kanyen(re.search(r"政令で定める金額は、(.+?)円とする", so).group(1) + "円")
        s27 = L("sochi-rei", asof).para("26_27", 1)
        m = re.search(r"同条中「(.+?)円」とあるのは、「(.+?)円（同条に規定する公的年金等が.+?である場合にあつては、(.+?)円）」", s27)
        ref, a65, ak = kanyen(m.group(1) + "円"), kanyen(m.group(2) + "円"), kanyen(m.group(3) + "円")
        p2_ = L("sochi-rei", asof).para("26_27_2", 2)
        m2 = re.search(r"２　(令和.+?年)(以後の各年)?において", p2_)
        cy = reiwa[m2.group(1)]
        applies = (year >= cy) if m2.group(2) else (year == cy)
        rep = {kanyen(a): kanyen(b) for a, b in re.findall(r"「([一二三四五六七八九十百千]+万円)」とあるのは「([一二三四五六七八九十百千]+万円)」", p2_)}
        u, o, k = base, a65, ak
        if applies:
            u, o, k = rep.get(base, base), rep.get(a65, a65), rep.get(ak, ak)
        return {"所令319の12": base, "措令26の27_引用": ref, "措令26の27_65": a65, "措令26の27_共済": ak, "26の27の2②": f"{m2.group(1)}{m2.group(2) or ''}",
                "適用": applies, "65未満": u, "65以上": o, "共済": k}
    exp52 = {(2025, S7): (1_080_000, 1_580_000, 800_000), (2026, "2026-01-01"): (1_550_000, 2_050_000, 1_270_000),
             (2026, S8): (1_550_000, 2_050_000, 1_270_000), (2027, S9): (1_640_000, 2_140_000, 1_370_000)}
    v5 = {}
    for (y, a), e in exp52.items():
        c = chain(y, a)
        v5[f"{y}@{a}"] = c
        add(f"PS5.2-chain-{y}-{a}", "PS/M", "§5.2・M V5", f"{y}年に支払うべき公的年金等（asof {a}）：65歳未満 {e[0]:,}／65歳以上 {e[1]:,}／一定の退職共済年金 {e[2]:,}",
            (c["65未満"], c["65以上"], c["共済"]) == e and c["措令26の27_引用"] == c["所令319の12"], json.dumps(c, ensure_ascii=False))
    base_exp = {S7: 1_080_000, "2026-01-01": 1_180_000, S8: 1_180_000, S9: 1_220_000}
    add("PS5.2-319_12", "PS", "§5.2", "所令319の12：108万（2025-12-31）・118万（2026-01-01）・122万（2027-01-01）",
        all(kanyen(re.search(r"政令で定める金額は、(.+?)円とする", L("shotoku-rei", a).text("319_12")).group(1) + "円") == v for a, v in base_exp.items()), "")
    nk = web.get("nenkin_shotokuzeikojo", "")
    rows = {}
    for lab, key in (("65歳未満の方", "u"), ("65歳以上の方", "o"), ("退職共済年金の受給者", "k")):
        line = [ln for ln in nk.splitlines() if lab in ln and "万円" in ln][0]
        rows[key] = [int(x) * 10_000 for x in re.findall(r"(\d+)万円", line)]
    add("PS5.2-nenkin-table", "PS/M", "§5.2・M V5", "機構の表：令和7年分まで 108/158/80万、令和8年分 155/205/127万、令和9年分以降 164/214/137万",
        rows == {"u": [1_080_000, 1_550_000, 1_640_000], "o": [1_580_000, 2_050_000, 2_140_000], "k": [800_000, 1_270_000, 1_370_000]}, json.dumps(rows))
    wq("PS5.2-nenkin-hdr", "PS", "§5.2", "nenkin_shotokuzeikojo", "令和7年分まで | 令和8年分 | 令和9年分以降")
    lq("PS5.2-R7-120-1-2", "PS", "§5.2", "shotoku-rei", S9, "1", "二　第一条中所得税法施行令…同令第三百十九条の十二の改正規定並びに附則第四条、第十一条及び第十二条第一項の規定　令和八年一月一日", 1, "amend", "令和七年三月三一日政令第一二〇号",
       claim="令和7年政令第120号附則第1条第2号：319の12 の改正は令和8年1月1日施行")
    lq("PS5.2-R7-120-12", "PS", "§5.2", "shotoku-rei", S9, "12", "新令第三百十九条の十二の規定は、令和八年一月一日以後に支払うべき所得税法第二百三条の七に規定する公的年金等について適用し、同日前に支払うべき同条に規定する公的年金等については、なお従前の例による。", 1, "amend", "令和七年三月三一日政令第一二〇号",
       claim="令和7年政令第120号附則第12条第1項（PS の引用）")
    lq("PS5.2-R8-93-1-2", "PS", "§5.2", "shotoku-rei", S9, "1", "二　第二百二十二条の二第三項第五号の改正規定及び第三百十九条の十二の改正規定並びに附則第九条第一項の規定　令和九年一月一日", 1, "amend", "令和八年三月三一日政令第九三号",
       claim="令和8年政令第93号附則第1条第2号：319の12 の改正は令和9年1月1日施行")
    lq("PS5.2-R8-93-9", "PS", "§5.2", "shotoku-rei", S9, "9", "新令第三百十九条の十二の規定は、令和九年一月一日以後に支払うべき所得税法第二百三条の七に規定する公的年金等について適用し", 1, "amend", "令和八年三月三一日政令第九三号",
       claim="令和8年政令第93号附則第9条第1項")
    lq("PS5.2-R7-127-1-2", "PS", "§5.2", "sochi-rei", S9, "1", "二　第二十五条の十の十二の改正規定及び第二十六条の二十七第一項の改正規定並びに附則第十条及び第十一条の規定　令和八年一月一日", 1, "amend", "令和七年三月三一日政令第一二七号",
       claim="令和7年政令第127号附則第1条第2号：26の27①の改正は令和8年1月1日施行")
    lq("PS5.2-R7-127-10", "PS", "§5.2", "sochi-rei", S9, "10", "新令第二十六条の二十七第一項の規定により読み替えられた所得税法施行令…第三百十九条の十二の規定は、令和八年一月一日以後に支払うべき", 1, "amend", "令和七年三月三一日政令第一二七号",
       claim="令和7年政令第127号附則第10条")
    lq("PS5.2-R7-127-11", "PS", "§5.2", "sochi-rei", S9, "11", "新令第二十六条の二十七の二第二項の規定により読み替えられた所得税法施行令第三百十九条の十二の規定及び新令第二十六条の二十七の規定は、令和八年一月一日以後に支払うべき公的年金等について適用し", 1, "amend", "令和七年三月三一日政令第一二七号",
       claim="令和7年政令第127号附則第11条")
    lq("NEW-R8-98-1-3", "PS", "§5.2", "sochi-rei", S9, "1", "三　…第二十六条の二十七第一項の改正規定、第二十六条の二十七の二第一項の改正規定、同条第二項の改正規定…並びに附則第十二条及び第十三条第一項の規定　令和九年一月一日", 1, "amend", "令和八年三月三一日政令第九八号",
       claim="（追加）令和8年政令第98号附則第1条第3号：26の27①・26の27の2②の改正は令和9年1月1日施行（PS が「附則は読んでいない」とした部分）")
    lq("NEW-R8-98-12", "PS", "§5.2", "sochi-rei", S9, "12", "新令第二十六条の二十七第一項の規定により読み替えられた…第三百十九条の十二の規定は、令和九年一月一日以後に支払うべき", 1, "amend", "令和八年三月三一日政令第九八号",
       claim="（追加）令和8年政令第98号附則第12条")
    lq("NEW-R8-98-13", "PS", "§5.2", "sochi-rei", S9, "13", "新令第二十六条の二十七の二第二項の規定により読み替えられた新所得税法施行令第三百十九条の十二の規定及び新令第二十六条の二十七の規定は、令和九年一月一日以後に支払うべき公的年金等について適用し", 1, "amend", "令和八年三月三一日政令第九八号",
       claim="（追加）令和8年政令第98号附則第13条第1項")
    lq("PS5.2-2627-2", "PS", "§5.2", "sochi-rei", S8, "26_27", "前項の居住者の年齢が六十五歳以上であるかどうかの判定は、その年十二月三十一日の年齢によるものとする。", 2)

    # ===== PS §6 申告不要
    q121 = ("その年において第三十五条第三項（雑所得）に規定する公的年金等（以下この条において「公的年金等」という。）に係る雑所得を有する居住者で、その年中の公的年金等の収入金額が四百万円以下であるものが、その公的年金等の全部（第二百三条の七（源泉徴収を要しない公的年金等）の規定の適用を受けるものを除く。）について第二百三条の二（公的年金等に係る源泉徴収義務）の規定による所得税の徴収をされた又はされるべき場合において、"
            "その年分の公的年金等に係る雑所得以外の所得金額（利子所得の金額、配当所得の金額、不動産所得の金額、事業所得の金額、給与所得の金額、山林所得の金額、譲渡所得の金額、一時所得の金額及び公的年金等に係る雑所得以外の雑所得の金額の合計額をいう。）が二十万円以下であるときは、前条第一項の規定にかかわらず、その年分の課税総所得金額又は課税山林所得金額に係る所得税については、同項の規定による申告書を提出することを要しない。")
    for a in (S7, S8, S9):
        lq(f"PS6-121-3-{a}", "PS", "§6", "shotoku", a, "121", q121, 3)
    add("PS6-121-same", "PS/M", "§6・M V1", "所法121 は3つの版で同文（第1〜3項）", L("shotoku", S7).text("121") == L("shotoku", S8).text("121") == L("shotoku", S9).text("121"), "")
    lq("PS6-121-1", "PS", "§6", "shotoku", S8, "121", "その年分の利子所得の金額、配当所得の金額、不動産所得の金額、事業所得の金額、山林所得の金額、譲渡所得の金額、一時所得の金額及び雑所得の金額の合計額（以下この項において「給与所得及び退職所得以外の所得金額」という。）が二十万円以下であるとき。", 1)
    lq("PS6-121-1-kanokawarazu", "H", "H6", "shotoku", S8, "121", "前条第一項の規定にかかわらず", 1, claim="所法121①にも「前条第一項の規定にかかわらず」がある（H6 の読みの前提）")
    for a in (S7, S8):
        lq(f"NEW-41_3_11-6-{a}", "H", "H6", "sochi", a, "41_3_11", "第二項の規定の適用がある場合における所得税法第百二十一条第三項の規定の適用については、同項中「給与所得の金額」とあるのは、「給与所得の金額から租税特別措置法第四十一条の三の十一第二項（所得金額調整控除）の規定による控除をした残額」とする。", 6,
           claim="（追加）措法41の3の11⑥：所法121③の 20万円の判定の「給与所得の金額」は所得金額調整控除（第2項）の後の額")
    for q in ["（1） 公的年金等に係る雑所得の金額から所得控除を差し引くと残額がある方は、確定申告で税額を精算することとなります。ただし、下記(2)の「公的年金等に係る確定申告不要制度」の適用を受ける方は、その限りではありません。",
              "平成23年分以後は、その年において公的年金等に係る雑所得を有する居住者で、その年中の公的年金等の収入金額が400万円以下であり、かつ、その年分の公的年金等に係る雑所得以外の所得金額が20万円以下である場合には確定申告の必要はありません。",
              "（注1） この場合であっても、例えば、医療費控除や社会保険料控除など各種の所得控除の適用による所得税の還付を受けるための確定申告をすることができます。",
              "（注2） 公的年金等以外の所得金額が20万円以下で確定申告の必要がない場合であっても、住民税の申告が必要な場合があります。",
              "（注3） 平成27年分以後は、源泉徴収の対象とされない「概要」の（4）に該当する公的年金等を受給している方は、公的年金等に係る確定申告不要制度の適用はできません。"]:
        wq("PS6-TA1600", "PS", "§6", "ta_1600", q)

    # ===== PS §7 住民税
    C6, C7 = "2026-01-01", "2027-01-01"
    for a in (C6, C7):
        lq(f"PS7-313-2-{a}", "PS", "§7.1", "chiho", a, "313", "前項の総所得金額、退職所得金額又は山林所得金額は、この法律又はこれに基づく政令で特別の定めをする場合を除くほか、それぞれ所得税法その他の所得税に関する法令の規定による所得税法第二十二条第二項又は第三項の総所得金額、退職所得金額又は山林所得金額の計算の例により算定するものとする。ただし、同法第六十条の二から第六十条の四までの規定の例によらないものとする。", 2)
        lq(f"PS7-317_2-{a}", "PS", "§7.1", "chiho", a, "317_2", "第三百十七条の六第一項又は第四項の規定により給与支払報告書又は公的年金等支払報告書を提出する義務がある者から一月一日現在において…公的年金等…の支払を受けている者で前年中において給与所得以外の所得又は公的年金等に係る所得以外の所得を有しなかつたもの（公的年金等に係る所得以外の所得を有しなかつた者で社会保険料控除額（政令で定めるものを除く。）、小規模企業共済等掛金控除額、生命保険料控除額、地震保険料控除額、勤労学生控除額、配偶者特別控除額（…）、第三百十四条の二第四項に規定する扶養控除額若しくは特定親族特別控除額（…）の控除又はこれらと併せて雑損控除額若しくは医療費控除額の控除、第三百十三条第八項に規定する純損失の金額の控除、同条第九項に規定する純損失若しくは雑損失の金額の控除若しくは…寄附金税額控除額…の控除を受けようとするものを除く。）", 1)
        lq(f"PS7-35_5-{a}", "PS", "§7.1", "chiho", a, "35_5", "当分の間、世帯主又はその世帯に属する国民健康保険の被保険者若しくは特定同一世帯所属者が、前年中に所得税法第三十五条第三項に規定する公的年金等に係る所得について同条第四項に規定する公的年金等控除額（年齢六十五歳以上である者に係るものに限る。）の控除を受けた場合における第七百三条の五の規定の適用については、同条第一項中「総所得金額（」とあるのは「総所得金額（所得税法第三十五条第三項に規定する公的年金等に係る所得については、同条第二項第一号の規定によつて計算した金額から十五万円を控除した金額によるものとし、」と", where="orig")
        lq(f"PS7-295-{a}", "I/H", "I6・H4", "chiho", a, "295", "二　障害者、未成年者、寡婦又はひとり親（これらの者の前年の合計所得金額が百三十五万円を超える場合を除く。）", 1)
    add("PS7-313-same", "PS", "§7.1", "地法313② は 2026-01-01 版と 2027-01-01 版で同文", L("chiho", C6).para("313", 2) == L("chiho", C7).para("313", 2), "")
    lq("PS7-314_2-4", "PS/H", "§7.1・H7", "chiho", C7, "314_2", "当該老人扶養親族に係る第一項第十一号の金額は、四十五万円とする。", 4,
       claim="地法314の2④の「扶養控除額」は同居老親等（同居直系尊属）の老人扶養親族に係る扶養控除額そのもの（45万円）。「割増分」ではない")
    lq("PS7-703_5", "PS", "§7.1", "chiho", C7, "703_5", "（国民健康保険税の減額）")
    lq("PS7-321_7_2", "PS", "§7.1", "chiho", C7, "321_7_2", "当該年度の初日において老齢等年金給付…の支払を受けている年齢六十五歳以上の者（特別徴収の方法によつて徴収することが著しく困難であると認めるものその他の政令で定めるものを除く。", 1)
    lq("NEW-317_6-4", "PS/H", "§10-10・H7", "chiho", C7, "317_6", "一月一日現在において公的年金等の支払をする者で、当該公的年金等の支払をする際所得税法第二百三条の二の規定により所得税を徴収する義務があるものは、同月三十一日までに、…当該公的年金等の支払を受けている者についてその者に係る前年中の公的年金等の支払額その他必要な事項を…公的年金等支払報告書に記載し、これを当該市町村の長に提出しなければならない。", 4,
       claim="（追加）地法317の6④：公的年金等支払報告書を出すのは、1月1日現在で公的年金等を支払う者のうち所法203の2 で徴収義務があるもの")
    add("PS7-317_6-same", "PS", "§10-10", "地法317の6④ は 2026-01-01 版と 2027-01-01 版で同文", L("chiho", C6).para("317_6", 4) == L("chiho", C7).para("317_6", 4), "")
    wq("PS7.2-tokyo", "PS", "§7.2", "tokyo_kojin_ju", "（注２）年齢は、前年の12月31日現在の年齢によります。")
    add("PS7.2-tokyo-LM", "PS", "§7.2", "東京都主税局 Last-Modified なし", not wlog["tokyo_kojin_ju"].get("last_modified"), str(wlog["tokyo_kojin_ju"].get("last_modified")))
    wq("PS7.2-higashiosaka", "PS", "§7.2", "higashiosaka_0000001683", "65歳であるかどうかの判定は、該当年度が発生する年の1月1日の現況で行います。")
    wq("PS7.2-higashiosaka-date", "PS", "§7.2", "higashiosaka_0000001683", "[更新日：2021年12月3日]")
    for q in ["お父さんの年金に対する税法上の取扱いはどうなっているのでしょうか？（令和７年度）", "私の父（68歳）", "220万円（年金収入）－110万円（公的年金等控除額）＝110万円（雑所得金額）"]:
        wq("PS7.2-yokohama", "PS", "§7.2", "yokohama_faq_answer6", q)

    # ===== PS §9 合計所得金額・勤労学生、扶養の基準額
    lq("PS9-2-30", "PS", "§9", "shotoku", S8, "2", "第七十条（純損失の繰越控除）及び第七十一条（雑損失の繰越控除）の規定を適用しないで計算した場合における第二十二条（課税標準）に規定する総所得金額、退職所得金額及び山林所得金額の合計額（以下この条において「合計所得金額」という。）", 1)
    t2 = L("shotoku", S8).text("2")
    i30 = t2.find("三十　寡婦")
    i31 = t2.find("三十一　ひとり親")
    add("PS9-2-30-loc", "PS", "§9", "合計所得金額の定義は所法2①三十（寡婦）のイ(2)にある", 0 <= i30 < t2.find("（以下この条において「合計所得金額」という。）") < i31 and "（２）" in t2[i30:i31], "")
    lq("PS9-22-2-1", "PS", "§9", "shotoku", S8, "22", "一　利子所得の金額、配当所得の金額、不動産所得の金額、事業所得の金額、給与所得の金額、譲渡所得の金額…及び雑所得の金額", 2)
    for a, amt in ((S7, "八十五万円"), (S8, "八十九万円"), (S9, "八十九万円")):
        lq(f"PS9-2-32-{a}", "PS", "§9", "shotoku", a, "2", f"三十二　勤労学生　次に掲げる者で、自己の勤労に基づいて得た事業所得、給与所得、退職所得又は雑所得（以下この号において「給与所得等」という。）を有するもののうち、合計所得金額が{amt}以下であり、かつ、合計所得金額のうち給与所得等以外の所得に係る部分の金額が十万円以下であるもの", 1)
    for a, amt in ((S7, "五十八万円"), (S8, "六十二万円")):
        lq(f"PS4.3-2-34-{a}", "PS/I", "§4.3注・I 冒頭", "shotoku", a, "2", f"三十四　扶養親族…のうち、合計所得金額が{amt}以下である者をいう。", 1)
    lq("PS4.3-R8-2", "PS/I", "§4.3注", "shotoku", S9, "2", "新所得税法…第二条第一項（第三十二号（ロに係る部分を除く。）、第三十三号及び第三十四号に係る部分に限る。）の規定は、令和八年分以後の所得税について適用し", 1, "amend", "令和八年三月三一日法律第一二号",
       claim="令和8年法律第12号附則第2条第1項：62万円・89万円は令和8年分以後")
    lq("I9-34-3", "I", "I9", "shotoku", S8, "34", "前項に規定する一時所得の特別控除額は、五十万円（同項に規定する残額が五十万円に満たない場合には、当該残額）とする。", 3)
    lq("I1-kenpo-3-7", "I", "I1", "kenpo", T, "3", "ただし、後期高齢者医療の被保険者等である者", 7)
    lq("I1-kokikourei-50", "I", "I1", "kokikourei", T, "50", "一　後期高齢者医療広域連合の区域内に住所を有する七十五歳以上の者", 1)

    # ===== M §2 走査
    def scan(short, asof, word, parts=("main", "orig")):
        hits = L(short, asof).sentences_with(word)
        return [h for h in hits if h[0] in parts or (h[0].startswith("amend:") and "amend" in parts)]
    h = scan("shotoku", S8, "公的年金等控除", ("main", "orig", "amend"))
    add("M2-shotoku", "M", "M §2", "所法 2026-12-31 版：「公的年金等控除」を含む Sentence は第35条の2か所だけ", h == [("main", "35"), ("main", "35")], str(h))
    h = scan("shotoku-rei", S8, "公的年金等控除", ("main", "orig"))
    add("M2-shotoku-rei", "M", "M §2", "所令 2026-12-31 版：本則・原始附則では第258条だけ", sorted(set(x[1] for x in h)) == ["258"], str(h))
    hs = [scan("sochi", a, "公的年金等控除", ("main", "orig")) for a in (S7, S8, S9)] + [scan("sochi-rei", S8, "公的年金等控除", ("main", "orig"))]
    add("M2-sochi", "M", "M §2", "措法（3版）・措令（2026-12-31）：本則・原始附則に「公的年金等控除」の Sentence は0件", all(not x for x in hs), str(hs))
    for a in (C6, C7):
        h = scan("chiho", a, "公的年金等控除", ("main", "orig"))
        add(f"M2-chiho-{a}", "M", "M §2", f"地法 {a}：「公的年金等控除」は原始附則第35条の5だけ", sorted(set(h)) == [("orig", "35_5")], str(h))
        h = scan("chiho-rei", a, "公的年金等控除", ("main", "orig"))
        add(f"M2-chiho-rei-{a}", "M", "M §2", f"地令 {a}：「公的年金等控除」は第56条の89だけ", sorted(set(x[1] for x in h)) == ["56_89"], str(h))
        h = scan("chiho", a, "六十五歳以上", ("main",))
        got65 = sorted(set(x[1] for x in h))
        add(f"M2-chiho-65-{a}", "M", "M §2", f"地法 {a}：本則で「六十五歳以上」を含む条は 321の3・321の7の2・321の7の3・701の31・706", got65 == sorted(["321_3", "321_7_2", "321_7_3", "701_31", "706"]), str(got65))

    # ===== V6・H2：65歳の判定
    for b, exp in ((datetime.date(1961, 12, 31), 65), (datetime.date(1962, 1, 1), 65), (datetime.date(1962, 1, 2), 64)):
        add(f"V6-{b}", "M/H", "M V6・H2", f"{b} 生まれは 2026-12-31 の終了時に {exp} 歳（式L）", age_L(b, datetime.date(2026, 12, 31)) == exp, str(age_L(b, datetime.date(2026, 12, 31))))
    diff = []
    d0 = datetime.date(1930, 1, 1)
    for n in range(0, 365 * 80):
        b = d0 + datetime.timedelta(days=n)
        a1 = age_L(b, datetime.date(2026, 12, 31))
        a2 = age_L(b, datetime.date(2027, 1, 1))
        if (a1 >= 65) != (a2 >= 65):
            diff.append(str(b))
    add("H2-dec31-vs-jan1", "H/PS", "H2・PS §10-6", "「前年12月31日現在」と「1月1日の現況」は年齢の数え方では同じ結果になる（H2 の主張）", not diff,
        f"式L で 2026-12-31 の終了時と 2027-01-01 の終了時の 65歳以上の判定が分かれる生年月日：{diff}（1月1日生まれではなく1月2日生まれ）")

    # ===== 推測・仮説の数値
    Z = lambda A, a65, O=0: z100(A, O, a65) / 100  # noqa: E731
    KJ = lambda A, a65, O=0: k100(A, O, a65) / 100  # noqa: E731
    add("I1", "I", "I1", "175万円・65歳以上 → 雑所得 65万円（>62万）。境目 172万円（62万）・172万1円、令和7年分 168万円（58万）・169万円（59万）",
        Z(1_750_000, True) == 650_000 and Z(1_720_000, True) == 620_000 and Z(1_720_001, True) == 620_001 and Z(1_680_000, True) == 580_000 and Z(1_690_000, True) == 590_000, "")
    add("I2", "I", "I2", "老齢基礎年金 60万円・65歳以上 → 雑所得 0。120万＋60万＝180万（「180万円未満」に当たらない）", Z(600_000, True) == 0 and 1_200_000 + 600_000 == 1_800_000, "")
    add("I3", "I", "I3", "300万円・68歳 → 190万円、＋15万円＝205万円", Z(3_000_000, True) == 1_900_000, "")
    add("I4", "I", "I4", "64歳・100万円 → 雑所得 40万円（>20万円）。100万円 < 155万円（令和8年の65歳未満の源泉徴収を要しない額）", Z(1_000_000, False) == 400_000 and v5[f"2026@{S8}"]["65未満"] == 1_550_000, "")
    add("I5", "I", "I5", "67歳・230万円 → 120万円", Z(2_300_000, True) == 1_200_000, "")
    add("I6", "I", "I6", "62歳・2,166,667円 → 1,350,000.25円。65歳以上なら 135万円の境目は 245万円（端数なし）", Z(2_166_667, False) == 1_350_000.25 and Z(2_450_000, True) == 1_350_000 and z100(2_450_000, 0, True) % 100 == 0, str(Z(2_166_667, False)))
    add("I7-65", "I", "I7", "150万円・65歳 → 控除 110万円・雑所得 40万円", KJ(1_500_000, True) == 1_100_000 and Z(1_500_000, True) == 400_000, "")
    add("I7-64", "I", "I7", "150万円・64歳 → 控除 60万円・雑所得 90万円（I7 の記載）", KJ(1_500_000, False) == 600_000 and Z(1_500_000, False) == 900_000,
        f"条文の式では控除 {KJ(1_500_000, False):,.0f}円・雑所得 {Z(1_500_000, False):,.0f}円（40万円＋(150万−50万)×25%＝65万円 ＞ 最低額 60万円）。速算表でも 150万×0.75−27.5万＝{z100_nta(1_500_000, 1, False) / 100:,.0f}円")
    add("I8", "I", "I8", "150万＋30万＝180万円・66歳 → 70万円（>62万）", Z(1_800_000, True) == 700_000, "")
    add("I9", "I", "I9", "一時所得 20万円 − 特別控除（50万円、残額が50万円未満なら残額）→ 0", max(0, 200_000 - min(500_000, 200_000)) == 0, "")
    add("H8-3", "H", "H8", "扶養の境目の収入：65歳未満 122万（R8 62万）／118万（R7 58万）、65歳以上 172万／168万。いずれも端数が出ない帯",
        Z(1_220_000, False) == 620_000 and Z(1_180_000, False) == 580_000 and Z(1_720_000, True) == 620_000 and Z(1_680_000, True) == 580_000
        and all(z100(a, 0, g) % 100 == 0 for a, g in ((1_220_000, False), (1_180_000, False), (1_720_000, True), (1_680_000, True))), "")

    # ===== robots.txt（M §0 の記述）
    rb = {k: (wlog[k].get("status"), (pathlib.Path(web_dir) / wlog[k]["file"]).read_text(encoding="utf-8", errors="replace") if wlog[k].get("status") == 200 else "") for k in wlog if k.startswith("robots_")}
    nta_dis = re.findall(r"Disallow:\s*(\S+)", rb["robots_nta"][1])
    nk_dis = re.findall(r"Disallow:\s*(\S+)", rb["robots_nenkin"][1])
    add("M0-robots-nta", "M", "M §0", "国税庁 robots.txt の Disallow は /service_publication/ 系だけで、今回の取得先は当たらない", all("service_publication" in x for x in nta_dis), str(nta_dis))
    add("M0-robots-nenkin", "M", "M §0", "日本年金機構 robots.txt の Disallow は PDF 1件だけ", len(nk_dis) == 1 and nk_dis[0].endswith(".pdf"), str(nk_dis))
    tk_dis = re.findall(r"Disallow:\s*(\S+)", rb["robots_tokyo"][1])
    add("M0-robots-local", "M", "M §0（M は未確認としていた）", "地方公共団体：東京都主税局の Disallow に /kazei/ は当たらない。東大阪市・横浜市は robots.txt が 404",
        not any(x.startswith("/kazei") for x in tk_dis) and rb["robots_higashiosaka"][0] == 404 and rb["robots_yokohama"][0] == 404, f"東京 {tk_dis}／東大阪 {rb['robots_higashiosaka'][0]}／横浜 {rb['robots_yokohama'][0]}")

    # ===== 出力
    n_ok = sum(1 for c in CH if c["result"] == "OK")
    n_ng = [c for c in CH if c["result"] == "NG"]
    rep = {"laws_dirs": laws_dirs, "web_dir": web_dir, "exhaustive_max": exhaustive_max, "n_checks": len(CH), "n_ok": n_ok, "n_ng": len(n_ng),
           "constants_from_law": {k: (v if k != "min65" else {str(a): b for a, b in v.items()}) for k, v in K.items()}, "V5_chain": v5, "checks": CH}
    (OUT / "checks.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    md = ["# R2B_nenkin_xcheck の突き合わせの結果", "", f"- 入力：{laws_dirs}、{web_dir}", f"- 検査 {len(CH)} 件：OK {n_ok}、NG {len(n_ng)}", "",
          "| # | id | 文書 | 節 | 主張 | 結果 | 詳細 |", "|---|---|---|---|---|---|---|"]
    for i, c in enumerate(CH, 1):
        md.append(f"| {i} | {c['id']} | {c['doc']} | {c['section']} | {c['claim'].replace('|', '｜')} | {c['result']} | {c['detail'].replace('|', '｜')[:400]} |")
    (OUT / "checks.md").write_text("\n".join(md), encoding="utf-8")
    print(f"checks {len(CH)} ok {n_ok} ng {len(n_ng)}")
    for c in n_ng:
        print("NG", c["id"], c["claim"][:80], "|", c["detail"][:300])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "webtext":
        webtext(sys.argv[2])
        sys.exit(0)
    if cmd == "compare_web":  # 他の担当の取得記録（scripts/results/R2B_nenkin_web/*.json）と、この検証の取得の SHA-256 を比べる
        mine = {f["id"]: f for f in json.loads((OUT / "fetch_web_log.json").read_text(encoding="utf-8"))["fetches"]}
        rows = []
        for lp in sorted((ROOT / "scripts" / "results" / "R2B_nenkin_web").glob("*.json")):
            for r in json.loads(lp.read_text(encoding="utf-8"))["results"]:
                m = mine.get(r["id"])
                if m:
                    rows.append({"id": r["id"], "author_log": lp.name, "same_sha256": m["sha256"] == r.get("sha256"),
                                 "author_last_modified": r.get("last_modified"), "xcheck_last_modified": m.get("last_modified")})
        (OUT / "compare_web.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"same {sum(r['same_sha256'] for r in rows)} / {len(rows)}；違う：{[r['id'] for r in rows if not r['same_sha256']]}")
        sys.exit(0)
    if cmd == "show":  # show <json> <main|orig|amend> <Num...> [--amend <AmendLawNum>]：条を読むための表示
        law = Law(sys.argv[2])
        where = sys.argv[3]
        rest = sys.argv[4:]
        an = None
        if "--amend" in rest:
            i = rest.index("--amend")
            an = rest[i + 1]
            rest = rest[:i]
        if where == "list":
            print(law.ri)
            for k, v in law.amend.items():
                print(k, list(v.keys())[:40])
            sys.exit(0)
        for num in rest:
            print(f"## {where} {an or ''} Num={num}")
            print(law.text(num, where, an))
        sys.exit(0)
    if cmd == "fetch_laws":
        fetch_laws(sys.argv[2:] or None)
    elif cmd == "fetch_web":
        fetch_web()
    elif cmd == "dump":
        dump(sys.argv[2])
    elif cmd == "analyze":
        analyze(sys.argv[2], sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 15_000_000)
    else:
        print(__doc__)

"""R2B_kabu_xcheck: トピック kabu（株式等の譲渡所得・配当所得）の文書を、独立の検証者（反証役）が一次情報に当たり直して確かめる。

担当の R2B_kabu_egov.py・R2B_kabu_web.py・R2B_kabu_verify.py の結果は使わない（すべて取り直す）。
担当のスクリプト名 R2B_kabu_verify.py は担当の照合に使われているので、上書きせず別の名前にした。

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_kabu_xcheck.py fetch
      → .work/downloads/<ts>_R2B_kabu_xcheck/ に取得（法令の JSON、改正履歴、Web）。取得記録は
        scripts/results/R2B_kabu_xcheck/fetch_<ts>.json
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_kabu_xcheck.py fetch chiho:2026-03-31 chiho:2026-04-01 chiho:2026-11-09
      → 指定した法令の版だけを .work/downloads/<ts>_R2B_kabu_xcheck_extra/ に取得（追加の確認用）
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_kabu_xcheck.py check .work/downloads/<ts>_R2B_kabu_xcheck [.work/downloads/<ts>_R2B_kabu_xcheck_extra]
      → 取得したデータを読むだけ（ネットワークに出ない）。照合の結果と、読んだ条・ページのテキストを
        scripts/results/R2B_kabu_xcheck/ に書く。Web の取得記録は最初のディレクトリのものを使う。

標準ライブラリのみ。リクエストの間は 1.5 秒。User-Agent は okura-gov-research/0.1。個人の情報は送らない。官報は取得しない。
e-Gov の使い方（/law_data の JSON、inline / render / walk）は scripts/R1_egov_articles.py と scripts/IMPL_kyuyo_fetch.py を
写した（import はしない）。ダウンロードしたものは信頼できないデータとして扱い、そのディレクトリの中では何も実行しない
（このスクリプトはリポジトリの scripts/ から起動し、ダウンロードしたファイルはデータとして読むだけ）。

照合の方法
- 条文：法令・時点・条（本則／原始附則）・項・号を構造（Num 属性）で指定し、その範囲のテキストに引用の文字列が
  含まれるかを見る。引用の「…」は省略の印として、前後の断片がこの順に現れるかを見る（空白は無視）。
  「含まれないこと」を確かめる検査もある（expect=False）。
- Web：HTML をテキストにし、引用の文字列が含まれるか。Last-Modified・SHA-256・バイト数を記録し、文書の値と比べる。
- 例の計算：仮説の算入規則とは別に、条文の構造から書き直した計算で、実測の文書 §6 の値を再計算する。
"""
import difflib
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
API = "https://laws.e-gov.go.jp/api/2"
SLEEP = 1.5
OUT = ROOT / "scripts" / "results" / "R2B_kabu_xcheck"

LAW = {"shotoku": "340AC0000000033", "shotoku-rei": "340CO0000000096", "sochi": "332AC0000000026",
       "sochi-rei": "332CO0000000043", "chiho": "325AC0000000226", "kokuho-rei": "333CO0000000362",
       "tsusoku": "337AC0000000066"}

FETCH_LAWS = [
    ("shotoku", "2025-12-31"), ("shotoku", "2026-12-31"),
    ("shotoku-rei", "2025-12-31"), ("shotoku-rei", "2026-12-31"),
    ("sochi", "2025-12-31"), ("sochi", "2026-01-01"), ("sochi", "2026-11-09"), ("sochi", "2026-12-31"), ("sochi", "2027-01-01"),
    ("sochi-rei", "2025-12-31"), ("sochi-rei", "2026-01-01"), ("sochi-rei", "2026-11-09"), ("sochi-rei", "2026-12-31"),
    ("chiho", "2023-12-31"), ("chiho", "2024-01-01"), ("chiho", "2026-01-01"), ("chiho", "2027-01-01"),
    ("kokuho-rei", "2026-04-01"), ("kokuho-rei", "2027-04-01"),
    ("tsusoku", "2025-12-31"),
]
FETCH_REVS = ["shotoku", "sochi", "sochi-rei", "chiho", "kokuho-rei"]

NTA = "https://www.nta.go.jp"
WEB = [
    ("ta_1330", NTA + "/taxes/shiraberu/taxanswer/shotoku/1330.htm"),
    ("ta_1331", NTA + "/taxes/shiraberu/taxanswer/shotoku/1331.htm"),
    ("ta_1250", NTA + "/taxes/shiraberu/taxanswer/shotoku/1250.htm"),
    ("ta_1463", NTA + "/taxes/shiraberu/taxanswer/shotoku/1463.htm"),
    ("ta_1474", NTA + "/taxes/shiraberu/taxanswer/shotoku/1474.htm"),
    ("ta_1476", NTA + "/taxes/shiraberu/taxanswer/shotoku/1476.htm"),
    ("yogo_senmon", NTA + "/taxes/shiraberu/taxanswer/yogo/senmon.htm"),
    ("sochitsu_8_4", NTA + "/law/tsutatsu/kobetsu/shotoku/sochiho/801226/sinkoku/57/08/04.htm"),
    ("sochitsu_8_5", NTA + "/law/tsutatsu/kobetsu/shotoku/sochiho/801226/sinkoku/57/08/06.htm"),
    ("kabutsu_toc", NTA + "/law/tsutatsu/kobetsu/shotoku/sochiho/020624/sanrin/01.htm"),
    ("kabutsu_37_10_11", NTA + "/law/tsutatsu/kobetsu/shotoku/sochiho/020624/sanrin/1273/37_10-11/01.htm"),
    ("kabutsu_37_11", NTA + "/law/tsutatsu/kobetsu/shotoku/sochiho/020624/sanrin/1273/37_11/01.htm"),
    ("kabutsu_37_11_5", NTA + "/law/tsutatsu/kobetsu/shotoku/sochiho/020624/sanrin/1273/37_11_5/01.htm"),
    ("tebiki_1_03", NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/01/1_03.htm"),
    ("tebiki_1_12", NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/01/1_12.htm"),
    ("tebiki_y01", NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/03/order2/yogo/3-2_y01.htm"),
    ("tokushu_kabu", NTA + "/taxes/shiraberu/shinkoku/tokushu/keisubetsu/kabu-haitou-shinkoku.htm"),
    ("kisairei_kabu", NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/kisairei/kabushiki/index.htm"),
    ("yoshiki_r07_02", NTA + "/taxes/shiraberu/shinkoku/yoshiki/01/shinkokusho/pdf/r07/02.pdf"),
    ("yoshiki_r07_01", NTA + "/taxes/shiraberu/shinkoku/yoshiki/01/shinkokusho/pdf/r07/01.pdf"),
    ("joto_r07_18_2", NTA + "/taxes/shiraberu/shinkoku/syotoku/pdf/r07_joto_18-2.pdf"),
    ("soumu_kinyu_r040715", "https://www.soumu.go.jp/main_content/000833994.pdf"),
    ("ntt_member_1", "https://www.nttkenpo.jp/member/outline/files/member_1.pdf"),
    ("topre_fuyou_jouken", "https://toprekenpo.or.jp/fuyou_jouken/"),
    ("ngk_family_a", "https://ngkntk-kenpo.or.jp/outline_index/family_a"),
    ("otsuka_qa01", "https://www.kenpo.gr.jp/opckenpo/contents/qa/qa01.html"),
    ("nec_fuyousha_shunyu", "https://neckenpo.or.jp/fuyousha_shunyu/"),
]

BLOCK_LIKE = {"Paragraph", "Item"} | {f"Subitem{i}" for i in range(1, 11)}


def http_get(url, accept="*/*", timeout=300):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept, "Accept-Language": "ja"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body, st, hdr, final = r.read(), r.status, dict(r.headers), r.geturl()
    except urllib.error.HTTPError as e:
        body, st, hdr, final = e.read(), e.code, dict(e.headers or {}), url
    time.sleep(SLEEP)
    return st, hdr, body, final


def fetch(only=None):
    """only：["chiho:2026-11-09", ...] を渡すと、その法令の版だけを取得する（改正履歴と Web は取得しない）。"""
    sys.stdout.reconfigure(encoding="utf-8")
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2B_kabu_xcheck{'_extra' if only else ''}"
    dl.mkdir(parents=True, exist_ok=False)
    (dl / "laws").mkdir()
    (dl / "revs").mkdir()
    (dl / "web").mkdir()
    OUT.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "user_agent": UA, "laws": [], "revs": [], "web": []}
    targets = [tuple(x.split(":", 1)) for x in only] if only else FETCH_LAWS
    for short, asof in targets:
        law_id = LAW[short]
        url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
        st, hdr, body, _ = http_get(url, accept="application/json")
        fn = dl / "laws" / f"{short}_{asof}.json"
        fn.write_bytes(body)
        rec = {"short": short, "law_id": law_id, "asof": asof, "url": url, "status": st, "bytes": len(body),
               "sha256": hashlib.sha256(body).hexdigest(), "file": fn.name}
        log["laws"].append(rec)
        print("law", short, asof, st, len(body), flush=True)
    if only:
        (OUT / f"fetch_{ts}_extra.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
        print("done", dl)
        return 0
    for short in FETCH_REVS:
        law_id = LAW[short]
        url = f"{API}/law_revisions/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "amendment_date_from": "2023-06-01"})
        st, hdr, body, _ = http_get(url, accept="application/json")
        fn = dl / "revs" / f"{short}.json"
        fn.write_bytes(body)
        log["revs"].append({"short": short, "url": url, "status": st, "bytes": len(body), "file": fn.name})
        print("rev", short, st, len(body), flush=True)
    for wid, url in WEB:
        try:
            st, hdr, body, final = http_get(url, timeout=120)
            ext = ".pdf" if (url.endswith(".pdf") or body[:5] == b"%PDF-") else ".html"
            fn = dl / "web" / f"{wid}{ext}"
            fn.write_bytes(body)
            log["web"].append({"id": wid, "url": url, "final_url": final, "status": st, "bytes": len(body),
                               "sha256": hashlib.sha256(body).hexdigest(), "last_modified": hdr.get("Last-Modified"),
                               "content_type": hdr.get("Content-Type"), "file": fn.name})
            print("web", wid, st, len(body), hdr.get("Last-Modified"), flush=True)
        except Exception as e:  # noqa: BLE001
            log["web"].append({"id": wid, "url": url, "error": repr(e)})
            print("web", wid, "ERROR", e, flush=True)
    (OUT / f"fetch_{ts}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", dl)
    return 0


# ---- e-Gov のテキスト化（R1_egov_articles.py / IMPL_kyuyo_fetch.py から写した） ----
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


def walk(n, fn, path=()):
    if isinstance(n, dict):
        fn(n, path)
        for c in n.get("children", []):
            walk(c, fn, path + (n,))


def caption(a):
    for c in a.get("children", []):
        if isinstance(c, dict) and c.get("tag") == "ArticleCaption":
            return inline(c)
    return ""


class Law:
    def __init__(self, dl, short, asof):
        p = dl / "laws" / f"{short}_{asof}.json"
        raw = p.read_bytes()
        d = json.loads(raw)
        ri = d.get("revision_info") or {}
        li = d.get("law_info") or {}
        self.short, self.asof = short, asof
        self.meta = {"short": short, "asof": asof, "law_id": LAW[short], "law_num": li.get("law_num"),
                     "law_title": ri.get("law_title"),
                     "law_revision_id": ri.get("law_revision_id"), "amendment_law_num": ri.get("amendment_law_num"),
                     "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                     "amendment_promulgate_date": ri.get("amendment_promulgate_date"),
                     "current_revision_status": ri.get("current_revision_status"),
                     "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        self.root = d["law_full_text"]
        self.arts = {}
        self.suppl = []

        def collect(n, path):
            if n.get("tag") == "SupplProvision":
                self.suppl.append(n)
            if n.get("tag") != "Article":
                return
            sp = [q for q in path if q.get("tag") == "SupplProvision"]
            if not sp:
                self.arts.setdefault("本則:" + n["attr"].get("Num"), n)
            elif "AmendLawNum" not in (sp[-1].get("attr") or {}):
                self.arts.setdefault("附則:" + n["attr"].get("Num"), n)
        walk(self.root, collect)

    def node(self, addr):
        """addr: '本則:8_4' / '本則:8_4#3' / '本則:8_4#3.1' / '本則:2#1.30.イ' (イ以下は Subitem1 の Num ではなく SubitemTitle)"""
        key, _, rest = addr.partition("#")
        n = self.arts.get(key)
        if n is None or not rest:
            return n
        parts = rest.split(".")
        # 項
        n = next((c for c in n.get("children", []) if isinstance(c, dict) and c.get("tag") == "Paragraph" and c["attr"].get("Num") == parts[0]), None)
        if n is None or len(parts) == 1:
            return n
        n = next((c for c in n.get("children", []) if isinstance(c, dict) and c.get("tag") == "Item" and c["attr"].get("Num") == parts[1]), None)
        level = 1
        for p in parts[2:]:
            if n is None:
                return None
            tag = f"Subitem{level}"
            n = next((c for c in n.get("children", []) if isinstance(c, dict) and c.get("tag") == tag and
                      (c["attr"].get("Num") == p or inline(next((x for x in c.get("children", []) if isinstance(x, dict) and x.get("tag") == tag + "Title"), {"children": []})) == p)), None)
            level += 1
        return n

    def text(self, addr):
        n = self.node(addr)
        if n is None:
            return None
        tl = []
        render(n, 0, tl)
        return "\n".join(tl)


class Extract(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        if tag in ("br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "dt", "dd", "table", "td", "th"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def norm(s):
    return re.sub(r"\s+", "", s or "")


def contains_seq(hay, needle):
    """「…」で区切った断片が、この順に hay に現れるか。"""
    h = norm(hay)
    pos = 0
    for seg in [norm(x) for x in re.split(r"…+", needle)]:
        if not seg:
            continue
        i = h.find(seg, pos)
        if i < 0:
            return False
        pos = i + len(seg)
    return True


# ---- 読むための条の抜き出し（検証者が本文を目で読むためのテキスト） ----
DUMP = {
    ("shotoku", "2025-12-31"): ["本則:2#1.30", "本則:2#1.32", "本則:2#1.34", "本則:2#1.34_4", "本則:2#1.34_5", "本則:28#3", "本則:73#1", "本則:83", "本則:84", "本則:84_2", "本則:86", "本則:92", "本則:123"],
    ("shotoku", "2026-12-31"): ["本則:2#1.30", "本則:2#1.32", "本則:2#1.34_4", "本則:2#1.34_5", "本則:83", "本則:84", "本則:84_2", "本則:86", "本則:92"],
    ("shotoku-rei", "2025-12-31"): ["本則:11_2"],
    ("sochi", "2025-12-31"): ["本則:8_4", "本則:8_5", "本則:9", "本則:9_8", "本則:37_10#6", "本則:37_11#1", "本則:37_11#2", "本則:37_11#6",
                               "本則:37_11_5", "本則:37_11_6#9", "本則:37_11_6#10", "本則:37_12_2", "本則:37_14#1", "本則:37_14#2", "本則:37_14#5", "本則:41_16_2"],
    ("sochi", "2026-12-31"): ["本則:8_4#3", "本則:37_10#6"],
    ("sochi-rei", "2025-12-31"): ["本則:4_2#9", "本則:4_3", "本則:25_10_12#1", "本則:25_11_2#8", "本則:25_11_2#15", "本則:25_11_2#16"],
    ("sochi-rei", "2026-12-31"): ["本則:25_10_12#1", "本則:25_11_2#15"],
    ("chiho", "2023-12-31"): ["本則:313#12", "本則:313#13", "本則:313#14", "本則:313#15"],
    ("chiho", "2026-01-01"): ["本則:23#1.3_3", "本則:23#1.3_4", "本則:23#1.15", "本則:23#1.17", "本則:32#12", "本則:32#13", "本則:32#14", "本則:32#15",
                               "本則:71_28", "本則:37_4#1", "本則:314_9#1", "本則:292#1.7", "本則:292#1.8", "本則:292#1.9", "本則:292#1.11", "本則:292#1.12", "本則:292#1.13",
                               "本則:295#1", "本則:295#3", "本則:313#12", "本則:313#13", "本則:313#14", "本則:313#15",
                               "本則:314_2#1.10_2", "本則:314_2#1.11", "本則:314_2#1.12", "本則:314_2#9", "本則:314_2#11",
                               "附則:33_2", "附則:35_2#8", "附則:35_2_2", "附則:35_2_6"],
    ("chiho", "2027-01-01"): ["本則:23#1.15", "本則:313#12", "本則:292#1.7", "本則:292#1.9"],
    ("chiho", "2026-03-31"): ["本則:23#1.15", "本則:313#12"],
    ("chiho", "2026-04-01"): ["本則:23#1.15", "本則:313#12"],
    ("chiho", "2026-11-09"): ["本則:23#1.15", "本則:313#12", "本則:292#1.9"],
    ("sochi", "2026-11-09"): ["本則:9_3#1.1"],
    ("kokuho-rei", "2026-04-01"): ["本則:29_7#2", "本則:29_7#6"],
    ("tsusoku", "2025-12-31"): ["本則:118"],
}


def load_laws(dls):
    """dls：取得ディレクトリの並び。laws/ にある版をすべて読む（同じ版が2つあれば先のものを使う）。"""
    laws = {}
    for dl in dls:
        for p in sorted((dl / "laws").glob("*.json")):
            short, asof = p.stem.rsplit("_", 1)
            if (short, asof) not in laws:
                laws[(short, asof)] = Law(dl, short, asof)
    return laws


def dump(laws):
    d = OUT / "articles"
    d.mkdir(parents=True, exist_ok=True)
    for (short, asof), addrs in DUMP.items():
        L = laws.get((short, asof))
        if L is None:
            continue
        lines = [f"# {short} asof={asof} {L.meta['law_revision_id']} {L.meta['current_revision_status']} 改正={L.meta['amendment_law_num']} 施行={L.meta['amendment_enforcement_date']}", ""]
        for a in addrs:
            key = a.split("#")[0]
            art = L.arts.get(key)
            lines.append(f"## {a}  見出し={caption(art) if art else '(条なし)'}")
            t = L.text(a)
            lines.append(t if t is not None else "(見つからない)")
            lines.append("")
        (d / f"{short}_{asof}.txt").write_text("\n".join(lines), encoding="utf-8")


def web_texts(dl):
    out = {}
    d = OUT / "web_text"
    d.mkdir(parents=True, exist_ok=True)
    for p in sorted((dl / "web").glob("*.html")):
        body = p.read_bytes()
        s = None
        m = re.search(rb'charset=["\']?([A-Za-z0-9_\-]+)', body[:3000])
        encs = [m.group(1).decode("ascii", "replace")] if m else []
        for cs in encs + ["utf-8", "cp932"]:
            try:
                s = body.decode(cs)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        ex = Extract()
        ex.feed(s or body.decode("utf-8", "replace"))
        t = re.sub(r"\n\s*\n+", "\n", "".join(ex.parts))
        out[p.stem] = t
        (d / f"{p.stem}.txt").write_text(t, encoding="utf-8")
    return out


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")
    if argv and argv[0] == "fetch":
        return fetch(argv[1:] or None)
    if len(argv) >= 2 and argv[0] in ("dump", "check"):
        dls = [(ROOT / a).resolve() for a in argv[1:]]
        dl = dls[0]
        OUT.mkdir(parents=True, exist_ok=True)
        laws = load_laws(dls)
        dump(laws)
        web = web_texts(dl)
        if argv[0] == "check":
            return check(dl, laws, web)
        return 0
    print(__doc__)
    return 2


def check(dl, laws, web):
    return run_checks(dl, laws, web)


# ==== 照合（CHECKS）====
PS = "docs/public-sources/20261109_round2b_kabu-law-and-nta.md"
MEAS = "docs/measurements/20261109_round2b_kabu-fetch-and-verify.md"
HYP = "docs/hypotheses/20261109_round2b_kabu-model.md"
INF = "docs/inferences/20261109_round2b_kabu-scenarios.md"
S25, S26 = "2025-12-31", "2026-12-31"

# (ID, 文書と節, 法令, asof, 番地, 含むべき文字列（「…」は省略）, 期待（True＝含む／False＝含まない）)
LAWCHK = [
    # PS §1.1 措法第8条の4第1項
    ("L1.1a", "PS §1.1", "sochi", S25, "本則:8_4#1", "平成二十八年一月一日以後に支払を受けるべき", True),
    ("L1.1b", "PS §1.1", "sochi", S25, "本則:8_4#1.1", "第三十七条の十一第二項第一号に掲げる株式等…百分の三以上…同族会社…と合算して…百分の三以上", True),
    ("L1.1c", "PS §1.1", "sochi", S25, "本則:8_4#1.2", "公募…（特定株式投資信託を除く。）の収益の分配", True),
    ("L1.1d", "PS §1.1", "sochi", S25, "本則:8_4#1.3", "特定投資法人…の投資口の配当等", True),
    ("L1.1e", "PS §1.1", "sochi", S25, "本則:8_4#1.4", "特定受益証券発行信託…公募…の収益の分配", True),
    ("L1.1f", "PS §1.1", "sochi", S25, "本則:8_4#1.5", "特定目的信託…公募…の社債的受益権の剰余金の配当", True),
    ("L1.1g", "PS §1.1", "sochi", S25, "本則:8_4#1.6", "特定公社債の利子", True),
    ("L1.1h", "PS §1.1", "sochi", S25, "本則:8_4#1", "他の所得と区分し、その年中の当該上場株式等の配当等に係る利子所得の金額及び配当所得の金額として政令で定めるところにより計算した金額（以下この項において「上場株式等に係る配当所得等の金額」という。）に対し、上場株式等に係る課税配当所得等の金額（…第三項第三号の規定により読み替えられた同法第七十二条から第八十七条までの規定の適用がある場合には、その適用後の金額）…の百分の十五に相当する金額に相当する所得税を課する。この場合において、当該上場株式等の配当等に係る配当所得については、同法第九十二条第一項の規定は、適用しない。", True),
    # PS §1.2
    ("L1.2a", "PS §1.2", "sochi", S25, "本則:8_4#2", "前項の規定のうち、上場株式等の配当等で同項第一号から第三号までに掲げるもの（同項第二号に掲げる収益の分配にあつては、公社債投資信託以外の証券投資信託に係るものに限る。以下この項において「特定上場株式等の配当等」という。）に係る配当所得に係る部分は、居住者…がその年中に支払を受けるべき特定上場株式等の配当等に係る配当所得につき前項の規定の適用を受けようとする旨の記載のある確定申告書を提出した場合に限り適用するものとし、居住者…がその年中に支払を受けるべき特定上場株式等の配当等に係る配当所得について所得税法第二十二条及び第八十九条又は第百六十五条の規定の適用を受けた場合には、その者がその同一の年中に支払を受けるべき他の特定上場株式等の配当等に係る配当所得については、同項の規定は、適用しない。", True),
    # PS §1.3
    ("L1.3a", "PS §1.3 第1号", "sochi", S25, "本則:8_4#3.1", "所得税法第二条第一項第三十号から第三十四号の四までの規定の適用については、同項第三十号中「山林所得金額」とあるのは、「山林所得金額並びに租税特別措置法第八条の四第一項（上場株式等に係る配当所得等の課税の特例）に規定する上場株式等に係る配当所得等の金額（以下「上場株式等に係る配当所得等の金額」という。）」とする。", True),
    ("L1.3a2", "PS §1.3 第1号（令和7年分は第三十四号の五ではない）", "sochi", S25, "本則:8_4#3.1", "第三十四号の五", False),
    ("L1.3b", "PS §1.3・MEAS §4.2（2026-01-01 版）", "sochi", "2026-01-01", "本則:8_4#3.1", "第三十号から第三十四号の五まで", True),
    ("L1.3b2", "MEAS §4.2（2026-11-09 版）", "sochi", "2026-11-09", "本則:8_4#3.1", "第三十号から第三十四号の五まで", True),
    ("L1.3c", "PS §1.3（令和8年分の版）", "sochi", S26, "本則:8_4#3.1", "第三十号から第三十四号の五まで", True),
    ("L1.3d", "PS §1.3 第2号", "sochi", S25, "本則:8_4#3.2", "所得税法第六十九条の規定の適用については、同条第一項中「各種所得の金額」とあるのは、「各種所得の金額（上場株式等に係る配当所得等の金額を除く。）」とする。", True),
    ("L1.3e", "PS §1.3 第3号", "sochi", S25, "本則:8_4#3.3", "所得税法第七十一条及び第七十二条から第八十七条までの規定の適用については、これらの規定中「総所得金額」とあるのは、「総所得金額、上場株式等に係る配当所得等の金額」とする。", True),
    ("L1.3f", "PS §1.3 第4号", "sochi", S25, "本則:8_4#3.4", "同法第九十二条第一項中「ものを除く。）」とあるのは「ものを除く。）及び…上場株式等の配当等に係る配当所得（同項の規定の適用を受けようとするものに限る。）」", True),
    ("L1.3g", "PS §1.3 所法第2条第1項第30号イ(2)（令和7年分）", "shotoku", S25, "本則:2#1.30.1.2", "第七十条（純損失の繰越控除）及び第七十一条（雑損失の繰越控除）の規定を適用しないで計算した場合における第二十二条（課税標準）に規定する総所得金額、退職所得金額及び山林所得金額の合計額（以下この条において「合計所得金額」という。）", True),
    ("L1.3g2", "PS §1.3 同（令和8年分）", "shotoku", S26, "本則:2#1.30.1.2", "第七十条（純損失の繰越控除）及び第七十一条（雑損失の繰越控除）の規定を適用しないで計算した場合における第二十二条（課税標準）に規定する総所得金額、退職所得金額及び山林所得金額の合計額（以下この条において「合計所得金額」という。）", True),
    ("L1.3h", "PS §1.3 第34号の5「源泉控除対象親族」（令和8年分の版）", "shotoku", S26, "本則:2#1.34_5", "源泉控除対象親族", True),
    ("L1.3h2", "PS §1.3 第34号の5 は令和7年分の版にない", "shotoku", S25, "本則:2#1.34_5", "源泉控除対象親族", False),
    ("L1.3i", "PS §1.3 所法第83条第1項第1号", "shotoku", S25, "本則:83#1.1", "その居住者の第二条第一項第三十号（定義）に規定する合計所得金額（以下この項、次条第一項、第八十四条の二第一項（特定親族特別控除）及び第八十六条第一項（基礎控除）において「合計所得金額」という。）", True),
    ("L1.3j", "PS §1.3 措令第4条の2第9項", "sochi-rei", S25, "本則:4_2#9", "第十一条の二第二項…総所得金額…総所得金額、租税特別措置法（昭和三十二年法律第二十六号）第八条の四第一項（上場株式等に係る配当所得等の課税の特例）に規定する上場株式等に係る配当所得等の金額", True),
    ("L1.3k", "PS §1.3 所令第11条の2（ひとり親の範囲）", "shotoku-rei", S25, "本則:11_2", "（ひとり親の範囲）", True),
    # PS §2.1 措法第8条の5
    ("L2.1a", "PS §2.1 第1項", "sochi", S25, "本則:8_5#1", "同法第百二十条、第百二十三条若しくは第百二十七条…に規定する総所得金額、配当控除の額若しくは純損失の金額若しくは同法第百二十一条第一項…に規定する給与所得及び退職所得以外の所得金額若しくは同法第百二十一条第三項…に規定する公的年金等に係る雑所得以外の所得金額又は前条第一項に規定する上場株式等に係る配当所得等の金額の計算上当該利子等に係る利子所得の金額又は配当等に係る配当所得の金額を除外し、…同法第九十三条第一項、第百二十条から第百二十七条まで…の規定…を適用することができる。", True),
    ("L2.1b", "PS §2.1 第1号", "sochi", S25, "本則:8_5#1.1", "内国法人から支払を受ける配当等（次号から第六号までに掲げるものを除く。）で、当該内国法人から一回に支払を受けるべき金額が、十万円に配当計算期間（…）の月数を乗じてこれを十二で除して計算した金額以下であるもの", True),
    ("L2.1c", "PS §2.1 第2号", "sochi", S25, "本則:8_5#1.2", "前条第一項第一号に掲げる利子等又は配当等", True),
    ("L2.1d", "PS §2.1 第3号", "sochi", S25, "本則:8_5#1.3", "公募…（特定株式投資信託を除く。）の収益の分配", True),
    ("L2.1e", "PS §2.1 第4号", "sochi", S25, "本則:8_5#1.4", "特定投資法人", True),
    ("L2.1f", "PS §2.1 第5号", "sochi", S25, "本則:8_5#1.5", "特定受益証券発行信託…公募", True),
    ("L2.1g", "PS §2.1 第6号", "sochi", S25, "本則:8_5#1.6", "特定目的信託…社債的受益権の剰余金の配当", True),
    ("L2.1h", "PS §2.1 第7号", "sochi", S25, "本則:8_5#1.7", "特定公社債の利子", True),
    ("L2.1i", "PS §2.1 第3項", "sochi", S25, "本則:8_5#3", "暦に従つて計算し、十二月を超えるときは十二月とし、一月に満たない端数を生じたときはこれを一月とする", True),
    ("L2.1j", "PS §2.1 第4項", "sochi", S25, "本則:8_5#4", "第一項の居住者…が有する同項各号に掲げる利子等又は配当等についての同項の規定の適用は、その一回に支払を受けるべき利子等の額又は配当等の額ごとに行うことができる。", True),
    ("L2.1k", "PS §2.1 措令第4条の3 第1項（政令で定める利子等）", "sochi-rei", S25, "本則:4_3#1", "法第八条の五第一項に規定する政令で定める利子等", True),
    ("L2.1k2", "PS §2.1 措令第4条の3 第2項（政令で定める配当等）", "sochi-rei", S25, "本則:4_3#2", "法第八条の五第一項に規定する政令で定める配当等", True),
    ("L2.1l", "PS §2.1 措令第4条の3 に合計所得金額の読替えはない", "sochi-rei", S25, "本則:4_3", "合計所得金額", False),
    ("L2.1l2", "PS §2.1 措令第4条の3 に第2条第1項第30号の読替えはない", "sochi-rei", S25, "本則:4_3", "第二条第一項第三十号", False),
    ("L2.1m", "PS §2.1 措法第37条の11の6第9項", "sochi", S25, "本則:37_11_6#9", "源泉徴収選択口座内配当等についての第八条の五第一項の規定の適用は、同条第四項の規定にかかわらず、…それぞれの源泉徴収選択口座において有する源泉徴収選択口座内配当等）に係る利子所得の金額及び配当所得の金額の合計額ごとに行うものとする。", True),
    ("L2.1n", "PS §2.1 同第10項", "sochi", S25, "本則:37_11_6#10", "につき前条第一項の規定の適用を受けない場合には、当該源泉徴収選択口座内配当等に係る利子所得の金額及び配当所得の金額の合計額については、第八条の五第一項及び第二項の規定は、適用しない。", True),
    # PS §3 配当控除
    ("L3a", "PS §3 所法第92条第1項", "shotoku", S25, "本則:92#1", "外国法人から受けるこれらの金額に係るもの（…）を除く", True),
    ("L3b", "PS §3 第1号（課税総所得金額が1,000万円以下）", "shotoku", S25, "本則:92#1.1", "その年分の課税総所得金額が千万円以下である場合", True),
    ("L3c", "PS §3 第1号イ 百分の十", "shotoku", S25, "本則:92#1.1.1", "剰余金の配当等…当該配当所得の金額に百分の十を乗じて計算した金額", True),
    ("L3d", "PS §3 第1号ロ 百分の五", "shotoku", S25, "本則:92#1.1.2", "証券投資信託の収益の分配に係る配当所得　当該配当所得の金額に百分の五を乗じて計算した金額", True),
    ("L3e", "PS §3 第2号 百分の二・五", "shotoku", S25, "本則:92#1.2", "百分の二・五", True),
    ("L3f", "PS §3 第3号 百分の五・百分の二・五", "shotoku", S25, "本則:92#1.3", "百分の五…百分の二・五", True),
    ("L3g", "PS §3 第2項", "shotoku", S25, "本則:92#2", "課税総所得金額に係る所得税額、課税山林所得金額に係る所得税額又は課税退職所得金額に係る所得税額から順次控除する。…当該所得税額に相当する金額とする。", True),
    ("L3h", "PS §3 措法第9条第1項第7号", "sochi", S25, "本則:9#1.7", "投資法人から支払を受けるべき配当等", True),
    ("L3i", "PS §3 措法第9条第1項第1号", "sochi", S25, "本則:9#1.1", "第八条の二第一項の規定の適用を受ける", True),
    ("L3j", "PS §3 措法第9条第1項第2号", "sochi", S25, "本則:9#1.2", "国外私募公社債等運用投資信託等", True),
    ("L3k", "PS §3 措法第9条第1項第3号", "sochi", S25, "本則:9#1.3", "外国株価指数連動型特定株式投資信託", True),
    ("L3l", "PS §3 措法第9条第1項第4号", "sochi", S25, "本則:9#1.4", "特定外貨建等証券投資信託", True),
    ("L3m", "PS §3 措法第9条第1項第5号", "sochi", S25, "本則:9#1.5", "機関投資家私募…特定目的信託", True),
    ("L3n", "PS §3 措法第9条第1項第6号", "sochi", S25, "本則:9#1.6", "特定目的会社", True),
    ("L3o", "PS §3 措法第9条第3項", "sochi", S25, "本則:9#3", "特定株式投資信託", True),
    ("L3p", "PS §3 措法第9条第4項", "sochi", S25, "本則:9#4", "一般外貨建等証券投資信託", True),
    # PS §4
    ("L4a", "PS §4 措法第37条の11第1項", "sochi", S25, "本則:37_11#1", "平成二十八年一月一日以後に上場株式等の譲渡をした場合…他の所得と区分し、…上場株式等に係る譲渡所得等の金額…に対し、上場株式等に係る課税譲渡所得等の金額…の百分の十五に相当する金額に相当する所得税を課する。この場合において、上場株式等に係る譲渡所得等の金額の計算上生じた損失の金額があるときは、同法その他所得税に関する法令の規定の適用については、当該損失の金額は生じなかつたものとみなす。", True),
    ("L4b", "PS §4 第2項 上場", "sochi", S25, "本則:37_11#2.1", "金融商品取引所に上場されているもの", True),
    ("L4c", "PS §4 第2項 公募投信", "sochi", S25, "本則:37_11#2.2", "公募により行われたもの（第三条の二に規定する特定株式投資信託を除く。）の受益権", True),
    ("L4d", "PS §4 第2項 特定投資法人", "sochi", S25, "本則:37_11#2.3", "特定投資法人", True),
    ("L4e", "PS §4 第2項 国債・地方債", "sochi", S25, "本則:37_11#2.5", "国債及び地方債", True),
    ("L4f", "PS §4 第6項", "sochi", S25, "本則:37_11#6", "前条第六項の規定は、第一項の規定の適用がある場合について準用する。", True),
    ("L4g", "PS §4 第37条の10第6項第1号（令和7年分）", "sochi", S25, "本則:37_10#6.1", "所得税法第二条第一項第三十号から第三十四号の四までの規定の適用については、同項第三十号中「山林所得金額」とあるのは、「山林所得金額並びに租税特別措置法第三十七条の十第一項", True),
    ("L4g2", "PS §4 同（令和8年分）", "sochi", S26, "本則:37_10#6.1", "所得税法第二条第一項第三十号から第三十四号の五までの規定の適用については", True),
    ("L4h", "PS §4 第37条の10第6項第4号", "sochi", S25, "本則:37_10#6.4", "「各種所得の金額」とあるのは「各種所得の金額（一般株式等に係る譲渡所得等の金額を除く。）」", True),
    ("L4i", "PS §4 第37条の10第6項第5号", "sochi", S25, "本則:37_10#6.5", "所得税法第七十一条及び第七十二条から第八十七条までの規定の適用については、これらの規定中「総所得金額」とあるのは、「総所得金額、一般株式等に係る譲渡所得等の金額」とする。", True),
    # PS §5.2
    ("L5a", "PS §5.2 措法第37条の11の5第1項", "sochi", S25, "本則:37_11_5#1", "除外したところにより", True),
    ("L5b", "PS §5.2 同（同じ口座の第1号・第2号）", "sochi", S25, "本則:37_11_5#1", "当該各号に掲げる金額が同一の源泉徴収選択口座に係るものである場合には、当該源泉徴収選択口座については、第一号に掲げる金額及び第二号に掲げる金額", True),
    ("L5c", "PS §5.2 第1号 特定口座内保管上場株式等", "sochi", S25, "本則:37_11_5#1.1", "特定口座内保管上場株式等の譲渡", True),
    ("L5d", "PS §5.2 第2号 信用取引等", "sochi", S25, "本則:37_11_5#1.2", "信用取引等", True),
    ("L5e", "PS §5.2 措令第25条の10の12第1項第1号（令和7年分）", "sochi-rei", S25, "本則:25_10_12#1.1", "所得税法第二条第一項第三十号から第三十四号の四までの規定の適用については、同項第三十号中「山林所得金額」とあるのは、「山林所得金額並びに租税特別措置法第三十七条の十一第一項…に規定する上場株式等に係る譲渡所得等の金額（同法第三十七条の十一の五第一項（確定申告を要しない上場株式等の譲渡による所得）の規定の適用を受ける場合には、同項各号に掲げる金額を除外した金額）」とする。", True),
    ("L5e2", "PS §5.2 同（令和8年分は第三十四号の五）", "sochi-rei", S26, "本則:25_10_12#1.1", "所得税法第二条第一項第三十号から第三十四号の五までの規定の適用については", True),
    ("L5e3", "MEAS §4.2（措令 2026-01-01 版）", "sochi-rei", "2026-01-01", "本則:25_10_12#1.1", "第三十号から第三十四号の五まで", True),
    ("L5e4", "MEAS §4.2（措令 2026-11-09 版）", "sochi-rei", "2026-11-09", "本則:25_10_12#1.1", "第三十号から第三十四号の五まで", True),
    # PS §6 措法第37条の12の2・措令第25条の11の2
    ("L6a", "PS §6 第1項", "sochi", S25, "本則:37_12_2#1", "当該確定申告書に係る年分の第八条の四第一項に規定する上場株式等に係る配当所得等の金額を限度として、当該年分の当該上場株式等に係る配当所得等の金額の計算上控除する。", True),
    ("L6b", "PS §6 第2項 第1号（売委託）", "sochi", S25, "本則:37_12_2#2.1", "への売委託により行う上場株式等の譲渡", True),
    ("L6c", "PS §6 第2項 第11号まで", "sochi", S25, "本則:37_12_2#2.11", "上場株式等の譲渡", True),
    ("L6c2", "PS §6 第2項 第12号はない", "sochi", S25, "本則:37_12_2#2.12", "上場株式等", False),
    ("L6d", "PS §6 第3項", "sochi", S25, "本則:37_12_2#3", "同項の規定の適用を受けようとする旨の記載があり、かつ、上場株式等に係る譲渡損失の金額の計算に関する明細書その他の財務省令で定める書類の添付がある場合に限り、適用する", True),
    ("L6e", "PS §6 第4項", "sochi", S25, "本則:37_12_2#4", "第一項の規定の適用がある場合における第八条の四の規定の適用については、同条第一項中「計算した金額（」とあるのは、「計算した金額（第三十七条の十二の二第一項の規定の適用がある場合には、その適用後の金額。」とする。", True),
    ("L6f", "PS §6 第5項", "sochi", S25, "本則:37_12_2#5", "その年の前年以前三年内の各年において生じた上場株式等に係る譲渡損失の金額…上場株式等に係る譲渡所得等の金額及び第八条の四第一項に規定する上場株式等に係る配当所得等の金額（第一項の規定の適用がある場合にはその適用後の金額。…）を限度として", True),
    ("L6g", "PS §6 第7項", "sochi", S25, "本則:37_12_2#7", "その後において連続して確定申告書を提出している場合", True),
    ("L6h", "PS §6 第8項", "sochi", S25, "本則:37_12_2#8", "第五項の規定の適用がある場合における第八条の四（第三項を除く。）及び第三十七条の十一（第六項を除く。）の規定の適用については、第八条の四第一項及び第三十七条の十一第一項中「計算した金額（」とあるのは、「計算した金額（第三十七条の十二の二第五項の規定の適用がある場合には、その適用後の金額。」とする。", True),
    ("L6i", "PS §6 第9項（所法第123条第1項の準用）", "sochi", S25, "本則:37_12_2#9", "所得税法第百二十三条第一項（第二号を除く。）…の規定は、…第五項の規定の適用を受けようとする場合…について準用する", True),
    ("L6j", "PS §6 措令第25条の11の2第8項第1号", "sochi-rei", S25, "本則:25_11_2#8.1", "最も古い年に生じた上場株式等に係る譲渡損失の金額から順次控除する", True),
    ("L6k", "PS §6 同第2号", "sochi-rei", S25, "本則:25_11_2#8.2", "まず当該上場株式等に係る譲渡所得等の金額から控除し、なお控除しきれない損失の金額があるときは、当該上場株式等に係る配当所得等の金額から控除する", True),
    ("L6l", "PS §6 同第3号（所法第71条より先）", "sochi-rei", S25, "本則:25_11_2#8.3", "所得税法第七十一条第一項の規定による控除が行われる場合には、まず法第三十七条の十二の二第五項の規定による控除を行つた後", True),
    ("L6m", "PS §6 措令第25条の11の2第15項", "sochi-rei", S25, "本則:25_11_2#15", "法第八条の四第三項の規定により読み替えられた所得税法の規定の適用については…同法第七十二条第一項各号列記以外の部分中「総所得金額」とあるのは「総所得金額、上場株式等に係る配当所得等の金額（租税特別措置法第三十七条の十二の二第一項又は第五項（上場株式等に係る譲渡損失の損益通算及び繰越控除）の規定の適用がある場合には、その適用後の金額。以下同じ。）」…同法第七十三条から第八十七条までの規定", True),
    ("L6n", "PS §6 措令第25条の11の2第16項", "sochi-rei", S25, "本則:25_11_2#16", "「総所得金額、上場株式等に係る譲渡所得等の金額（租税特別措置法第三十七条の十二の二第五項（上場株式等に係る譲渡損失の繰越控除）の規定の適用がある場合には、その適用後の金額。以下同じ。）」", True),
    # PS §7 NISA
    ("L7a", "PS §7 第9条の8", "sochi", S25, "本則:9_8#1", "所得税を課さない", True),
    ("L7a1", "PS §7 第9条の8第1号 非課税管理勘定", "sochi", S25, "本則:9_8#1.1", "非課税管理勘定", True),
    ("L7a2", "PS §7 第9条の8第2号 累積投資勘定", "sochi", S25, "本則:9_8#1.2", "累積投資勘定", True),
    ("L7a3", "PS §7 第9条の8第3号 特定累積投資勘定", "sochi", S25, "本則:9_8#1.3", "特定累積投資勘定", True),
    ("L7a4", "PS §7 第9条の8第4号 特定非課税管理勘定", "sochi", S25, "本則:9_8#1.4", "特定非課税管理勘定", True),
    ("L7b", "PS §7 第37条の14第1項", "sochi", S25, "本則:37_14#1", "所得税を課さない", True),
    ("L7c", "PS §7 第37条の14第2項", "sochi", S25, "本則:37_14#2", "その不足額は、所得税に関する法令の規定の適用については、ないものとみなす。", True),
    ("L7d", "PS §7 第5項第6号イ 120万円・1800万円", "sochi", S25, "本則:37_14#5.6.1", "合計額が百二十万円を超えないもの…千八百万円を超えることとなる", True),
    ("L7e", "PS §7 第5項第6号ハ 240万円", "sochi", S25, "本則:37_14#5.6.3", "合計額が二百四十万円を超えないもの", True),
    ("L7f", "PS §7 第5項第6号ハ(1) 1200万円", "sochi", S25, "本則:37_14#5.6.3.1", "千二百万円を超える場合", True),
    # PS §8.1 地方税法
    ("L8a", "PS §8.1 第313条第12項", "chiho", "2026-01-01", "本則:313#12", "特定配当等に係る所得を有する者に係る総所得金額は、当該特定配当等に係る所得の金額を除外して算定するものとする。", True),
    ("L8b", "PS §8.1 第313条第13項", "chiho", "2026-01-01", "本則:313#13", "前項の規定は、前年分の所得税に係る第三百十七条の三第一項に規定する確定申告書に特定配当等に係る所得の明細に関する事項その他総務省令で定める事項の記載があるときは、当該特定配当等に係る所得の金額については、適用しない。", True),
    ("L8c", "PS §8.1 第313条第14項", "chiho", "2026-01-01", "本則:313#14", "特定株式等譲渡所得金額に係る所得を有する者に係る総所得金額は、当該特定株式等譲渡所得金額に係る所得の金額を除外して算定するものとする。", True),
    ("L8d", "PS §8.1 第313条第15項", "chiho", "2026-01-01", "本則:313#15", "前項の規定は、前年分の所得税に係る第三百十七条の三第一項に規定する確定申告書に特定株式等譲渡所得金額に係る所得の明細に関する事項その他総務省令で定める事項の記載があるときは、当該特定株式等譲渡所得金額に係る所得の金額については、適用しない。", True),
    ("L8e", "PS §8.1 第32条第12項", "chiho", "2026-01-01", "本則:32#12", "特定配当等に係る所得を有する者に係る総所得金額は、当該特定配当等に係る所得の金額を除外して算定するものとする。", True),
    ("L8f", "PS §8.1 第32条第13項（第四十五条の三第一項）", "chiho", "2026-01-01", "本則:32#13", "前年分の所得税に係る第四十五条の三第一項に規定する確定申告書", True),
    ("L8g", "PS §8.1 第32条第14項", "chiho", "2026-01-01", "本則:32#14", "特定株式等譲渡所得金額に係る所得を有する者に係る総所得金額は", True),
    ("L8h", "PS §8.1 第32条第15項（第四十五条の三第一項）", "chiho", "2026-01-01", "本則:32#15", "前年分の所得税に係る第四十五条の三第一項に規定する確定申告書", True),
    ("L8i", "PS §8.1 第23条第1項第15号", "chiho", "2026-01-01", "本則:23#1.15", "十五　特定配当等　租税特別措置法第八条の四第一項に規定する上場株式等の配当等及び同法第四十一条の十二の二第一項各号に掲げる償還金に係る同条第六項第三号に規定する差益金額をいう。", True),
    ("L8j", "PS §8.1 第23条第1項第17号", "chiho", "2026-01-01", "本則:23#1.17", "十七　特定株式等譲渡所得金額　租税特別措置法第三十七条の十一の四第二項に規定する源泉徴収選択口座内調整所得金額をいう。", True),
    ("L8k", "PS §8.1 第23条第1項第3号の3 配当割", "chiho", "2026-01-01", "本則:23#1.3_3", "配当割　支払を受けるべき特定配当等の額により課する道府県民税", True),
    ("L8l", "PS §8.1 第23条第1項第3号の4 株式等譲渡所得割", "chiho", "2026-01-01", "本則:23#1.3_4", "株式等譲渡所得割　特定株式等譲渡所得金額により課する道府県民税", True),
    ("L8m", "PS §8.1・MEAS §4.1 2023-12-31 版の第313条第13項（特定配当等申告書）", "chiho", "2023-12-31", "本則:313#13", "特定配当等申告書…第三百十七条の二第一項の規定による申告書…第三百十七条の三第一項に規定する確定申告書", True),
    ("L8m2", "MEAS §4.1 2023-12-31 版には新しい文がない", "chiho", "2023-12-31", "本則:313#13", "前年分の所得税に係る第三百十七条の三第一項に規定する確定申告書", False),
    ("L8m3", "MEAS §4.1 2024-01-01 版に新しい文がある", "chiho", "2024-01-01", "本則:313#13", "前年分の所得税に係る第三百十七条の三第一項に規定する確定申告書に特定配当等に係る所得の明細に関する事項", True),
    ("L8m4", "MEAS §4.1 2024-01-01 版の第313条第15項", "chiho", "2024-01-01", "本則:313#15", "前年分の所得税に係る第三百十七条の三第一項に規定する確定申告書に特定株式等譲渡所得金額に係る所得の明細に関する事項", True),
    ("L8m5", "MEAS §4.1 附則第33条の2第6項（2024-01-01 版）", "chiho", "2024-01-01", "附則:33_2#6", "前年分の所得税について特定上場株式等の配当等に係る配当所得につき租税特別措置法第八条の四第一項の規定の適用を受けた場合に限り", True),
    ("L8m6", "MEAS §4.1 附則第33条の2第6項（2023-12-31 版は特定配当等申告書）", "chiho", "2023-12-31", "附則:33_2#6", "特定配当等申告書", True),
    ("L8m7", "MEAS §4.1 附則第33条の2第2項（2024-01-01 版）", "chiho", "2024-01-01", "附則:33_2#2", "前年分の所得税について当該特定上場株式等の配当等に係る配当所得につき同条第一項の規定の適用を受けた場合に限り", True),
    ("L8n", "PS §8.1 令和9年度分の第23条第1項第15号ロ", "chiho", "2027-01-01", "本則:23#1.15.2", "租税特別措置法第九条の三第一号に掲げる同条に規定する配当等（イに掲げるもの及び政令で定めるものを除く。）", True),
    ("L8n2", "PS §8.1 令和9年度分の第23条第1項第15号イ", "chiho", "2027-01-01", "本則:23#1.15.1", "租税特別措置法第八条の四第一項に規定する上場株式等の配当等", True),
    ("L8n3", "PS §8.1 令和9年度分の第23条第1項第15号ハ", "chiho", "2027-01-01", "本則:23#1.15.3", "償還金に係る同条第六項第三号に規定する差益金額", True),
    ("L8o", "PS §8.1 令和9年度分の第313条第12項", "chiho", "2027-01-01", "本則:313#12", "特定配当等（第二十三条第一項第十五号ロに掲げるものを除く。以下この項において同じ。）", True),
    # PS §8.2
    ("L8.2a", "PS §8.2 附則第33条の2第5項 3%/4%", "chiho", "2026-01-01", "附則:33_2#5", "の百分の三（当該納税義務者が指定都市の区域内に住所を有する場合には、百分の四）", True),
    ("L8.2a2", "PS §8.2 同 配当控除（附則第5条第3項）を適用しない", "chiho", "2026-01-01", "附則:33_2#5", "附則第五条第三項の規定は、適用しない", True),
    ("L8.2b", "PS §8.2 附則第33条の2第1項 2%/1%", "chiho", "2026-01-01", "附則:33_2#1", "の百分の二（当該納税義務者が指定都市の区域内に住所を有する場合には、百分の一）", True),
    ("L8.2b2", "PS §8.2 同 配当控除（附則第5条第1項）を適用しない", "chiho", "2026-01-01", "附則:33_2#1", "附則第五条第一項の規定は、適用しない", True),
    ("L8.2c", "PS §8.2 附則第33条の2第6項", "chiho", "2026-01-01", "附則:33_2#6", "前項の規定のうち、特定上場株式等の配当等に係る配当所得に係る部分は、市町村民税の所得割の納税義務者が前年分の所得税について特定上場株式等の配当等に係る配当所得につき租税特別措置法第八条の四第一項の規定の適用を受けた場合に限り適用する。", True),
    ("L8.2d", "PS §8.2 附則第33条の2第7項第1号", "chiho", "2026-01-01", "附則:33_2#7.1", "第二百九十二条第一項（第七号から第九号まで、第十一号イ（２）、第十二号ロ及び第十三号に係る部分に限る。）、第二百九十五条第一項（第二号に係る部分に限る。）及び第三項、第三百十四条の二第一項（第十号の二及び第十二号に係る部分に限る。）及び第九項、第三百十四条の六、附則第四条第十項並びに附則第四条の二第十項の規定の適用については、第二百九十二条第一項第十三号中「山林所得金額」とあるのは、「山林所得金額並びに附則第三十三条の二第五項に規定する上場株式等に係る配当所得等の金額」とする。", True),
    ("L8.2e", "PS §8.2 附則第33条の2第7項第3号", "chiho", "2026-01-01", "附則:33_2#7.3", "第三百十三条第九項（雑損失の金額に係る部分に限る。）及び第三百十四条の二の規定の適用については、これらの規定中「総所得金額」とあるのは、「総所得金額、附則第三十三条の二第五項に規定する上場株式等に係る配当所得等の金額」とする。", True),
    ("L8.2f7", "PS §8.2 第292条第1項第7号", "chiho", "2026-01-01", "本則:292#1.7", "同一生計配偶者", True),
    ("L8.2f8", "PS §8.2 第292条第1項第8号", "chiho", "2026-01-01", "本則:292#1.8", "控除対象配偶者", True),
    ("L8.2f9", "PS §8.2 第292条第1項第9号", "chiho", "2026-01-01", "本則:292#1.9", "扶養親族", True),
    ("L8.2f11", "PS §8.2 第292条第1項第11号", "chiho", "2026-01-01", "本則:292#1.11", "寡婦", True),
    ("L8.2f12", "PS §8.2 第292条第1項第12号", "chiho", "2026-01-01", "本則:292#1.12", "ひとり親", True),
    ("L8.2f13", "PS §8.2 第292条第1項第13号", "chiho", "2026-01-01", "本則:292#1.13", "十三　合計所得金額　第三百十三条第八項及び第九項の規定による控除前の同条第一項の総所得金額、退職所得金額及び山林所得金額の合計額をいう。", True),
    ("L8.2g", "PS §8.2 第295条第1項第2号（135万円）", "chiho", "2026-01-01", "本則:295#1.2", "障害者、未成年者、寡婦又はひとり親（これらの者の前年の合計所得金額が百三十五万円を超える場合を除く。）", True),
    ("L8.2h", "PS §8.2 第314条の2第1項第10号の2（配偶者特別控除）", "chiho", "2026-01-01", "本則:314_2#1.10_2", "控除対象配偶者に該当しないもの", True),
    ("L8.2i", "PS §8.2 第314条の2第1項第12号（特定親族特別控除）", "chiho", "2026-01-01", "本則:314_2#1.12", "「特定親族」という", True),
    ("L8.2j", "PS §8.2 第314条の2第9項（勤労学生）", "chiho", "2026-01-01", "本則:314_2#9", "所得税法第二条第一項第三十二号の規定は、第一項第九号及び第三百十四条の六の勤労学生の意義について準用する。この場合において、…「合計所得金額が」とあるのは「…前年の合計所得金額（地方税法第二百九十二条第一項第十三号に規定する合計所得金額をいう。…）が」", True),
    ("L8.2k", "PS §8.2 附則第35条の2の2第5項 3%/4%", "chiho", "2026-01-01", "附則:35_2_2#5", "の百分の三（当該納税義務者が指定都市の区域内に住所を有する場合には、百分の四）", True),
    ("L8.2k2", "PS §8.2 同 除外", "chiho", "2026-01-01", "附則:35_2_2#5", "当該特定株式等譲渡所得金額に係る所得の金額（第三百十三条第十五項の規定により同条第十四項の規定の適用を受けないものを除く。）を除外して算定する", True),
    ("L8.2k3", "PS §8.2 同 損失は生じなかつたものとみなす", "chiho", "2026-01-01", "附則:35_2_2#5", "当該損失の金額は生じなかつたものとみなす", True),
    ("L8.2k4", "PS §8.2 附則第35条の2の2第1項 2%/1%", "chiho", "2026-01-01", "附則:35_2_2#1", "の百分の二（当該納税義務者が指定都市の区域内に住所を有する場合には、百分の一）", True),
    ("L8.2k5", "PS §8.2 附則第35条の2の2第8項（附則第35条の2第8項の準用）", "chiho", "2026-01-01", "附則:35_2_2#8", "前条第八項の規定は、第五項の規定の適用がある場合について準用する", True),
    ("L8.2k6", "PS §8.2 附則第35条の2第8項第1号（合計所得金額の読替え）", "chiho", "2026-01-01", "附則:35_2#8.1", "第二百九十二条第一項第十三号中「山林所得金額」とあるのは、「山林所得金額並びに附則第三十五条の二第五項に規定する一般株式等に係る譲渡所得等の金額」とする", True),
    ("L8.2l", "PS §8.2 附則第35条の2の6第8項", "chiho", "2026-01-01", "附則:35_2_6#8", "上場株式等に係る譲渡損失の金額の控除に関する事項を記載した確定申告書を提出した場合（租税特別措置法第三十七条の十二の二第一項の規定の適用がある場合に限る。）に限り", True),
    ("L8.2m", "PS §8.2 同第10項", "chiho", "2026-01-01", "附則:35_2_6#10", "第八項の規定の適用がある場合における附則第三十三条の二第五項から第八項までの規定の適用については", True),
    ("L8.2n", "PS §8.2 同第11項", "chiho", "2026-01-01", "附則:35_2_6#11", "前年前三年内の各年に生じた上場株式等に係る譲渡損失の金額…その後の年分の所得税について連続して確定申告書を提出しているとき（租税特別措置法第三十七条の十二の二第五項の規定の適用があるときに限る。）", True),
    ("L8.2o", "PS §8.2 同第13項", "chiho", "2026-01-01", "附則:35_2_6#13", "第十一項の規定の適用がある場合における附則第三十三条の二第五項、第六項及び第八項並びに附則第三十五条の二の二第五項から第七項までの規定の適用については", True),
    # PS §9 国保令
    ("L9a", "PS §9 第29条の7第2項第4号", "kokuho-rei", "2026-04-01", "本則:29_7#2.4", "地方税法第三百十四条の二第一項に規定する総所得金額及び山林所得金額並びに他の所得と区分して計算される所得の金額の合計額から同条第二項の規定による控除をした後の総所得金額及び山林所得金額並びに他の所得と区分して計算される所得の金額の合計額（以下「基礎控除後の総所得金額等」という。）に按分して算定する", True),
    ("L9b", "PS §9 第29条の7第2項第5号", "kokuho-rei", "2026-04-01", "本則:29_7#2.5", "同法第三百十三条第九項中雑損失の金額に係る部分の規定を適用しないものとして算定する", True),
    ("L9c", "PS §9 第29条の7第6項第1号", "kokuho-rei", "2026-04-01", "本則:29_7#6.1", "地方税法第三百十四条の二第一項に規定する総所得金額及び山林所得金額並びに他の所得と区分して計算される所得の金額（同法附則第三十三条の二第五項に規定する上場株式等に係る配当所得等の金額（同法附則第三十五条の二の六第八項又は第十一項の規定の適用がある場合には、その適用後の金額）、…同法附則第三十五条の二の二第五項に規定する上場株式等に係る譲渡所得等の金額（同法附則第三十五条の二の六第十一項又は第三十五条の三第十三項若しくは第十五項の規定の適用がある場合には、その適用後の金額）、…をいう。…）の合算額", True),
    # 仮説・推測の基準額（H・I）
    ("LH1", "HYP H2・INF 前提 勤労学生 85万円・10万円（令和7年分）", "shotoku", S25, "本則:2#1.32", "合計所得金額が八十五万円以下であり、かつ、合計所得金額のうち給与所得等以外の所得に係る部分の金額が十万円以下", True),
    ("LH1b", "MEAS §3 勤労学生 89万円（令和8年分の版）", "shotoku", S26, "本則:2#1.32", "合計所得金額が八十九万円以下", True),
    ("LH2", "INF 前提 扶養親族 58万円以下（令和7年分）", "shotoku", S25, "本則:2#1.34", "合計所得金額が五十八万円以下", True),
    ("LH3", "INF 前提 特定扶養親族の控除 63万円", "shotoku", S25, "本則:84#1", "その者が特定扶養親族である場合には六十三万円", True),
    ("LH4", "INF 前提 特定親族 123万円以下", "shotoku", S25, "本則:84_2#1", "合計所得金額が百二十三万円以下であるものに限る", True),
    ("LH5", "INF 前提 特定親族特別控除 85万円以下 63万円", "shotoku", S25, "本則:84_2#1.1", "合計所得金額が八十五万円以下である特定親族　六十三万円", True),
    ("LH6", "INF 前提 住民税 扶養親族 58万円以下（令和8年度分）", "chiho", "2026-01-01", "本則:292#1.9", "前年の合計所得金額が五十八万円以下である者", True),
    ("LH7", "INF 前提 住民税 特定扶養 45万円", "chiho", "2026-01-01", "本則:314_2#1.11", "特定扶養親族…である場合には四十五万円", True),
    ("LH8", "INF 前提 住民税 特定親族 95万円以下 45万円", "chiho", "2026-01-01", "本則:314_2#1.12.1", "前年の合計所得金額が九十五万円以下である特定親族　四十五万円", True),
    ("LH9", "SCN 給与所得控除 190万円以下 65万円（令和7年分）", "shotoku", S25, "本則:28#3.1", "百九十万円以下…六十五万円", True),
    ("LH10", "INF I4 医療費控除の足切り（5%・10万円）", "shotoku", S25, "本則:73#1", "百分の五…十万円", True),
    ("LH11", "HYP H2-2 措法第41条の16の2（基礎控除の特例）", "sochi", S25, "本則:41_16_2", "（令和七年分以後の各年分の基礎控除等の特例）", True),
    ("LH12", "HYP H3 配当割 5%", "chiho", "2026-01-01", "本則:71_28#1", "配当割の税率は、百分の五とする", True),
    ("LH13", "HYP H6 国税通則法第118条第1項 千円未満切捨て", "tsusoku", S25, "本則:118#1", "千円未満の端数があるとき、又はその全額が千円未満であるときは、その端数金額又はその全額を切り捨てる", True),
    ("LH14", "HYP H8 地方税法第37条の4（配当割額の控除）", "chiho", "2026-01-01", "本則:37_4", "配当割額", True),
    ("LH15", "HYP H8 地方税法第314条の9（配当割額又は株式等譲渡所得割額の控除）", "chiho", "2026-01-01", "本則:314_9", "株式等譲渡所得割額", True),
    # ---- 検証者が足した検査（訂正後の記載・追加で分かったこと）----
    ("X1", "訂正後 PS §8.2 第314条の2第9項（省略の印を正した引用）", "chiho", "2026-01-01", "本則:314_2#9", "所得税法第二条第一項第三十二号の規定は、第一項第九号及び第三百十四条の六の勤労学生の意義について準用する。この場合において、…「合計所得金額が」とあるのは「…前年（…）の合計所得金額（地方税法第二百九十二条第一項第十三号に規定する合計所得金額をいう。…）が」", True),
    ("X2", "訂正後 MEAS §3 第292条第1項第9号 扶養親族 62万円（令和9年度分の版）", "chiho", "2027-01-01", "本則:292#1.9", "前年の合計所得金額が六十二万円以下である者", True),
    ("X3", "訂正後 MEAS §3 第292条第1項第7号 同一生計配偶者 62万円（令和9年度分の版）", "chiho", "2027-01-01", "本則:292#1.7", "の合計所得金額が六十二万円以下である者", True),
    ("X4", "追加 第292条第1項第9号は 2026-11-09 版ではまだ 58万円", "chiho", "2026-11-09", "本則:292#1.9", "前年の合計所得金額が五十八万円以下である者", True),
    ("X5", "追加 第23条第1項第15号は 2026-03-31 版では分かれていない", "chiho", "2026-03-31", "本則:23#1.15", "租税特別措置法第九条の三第一号", False),
    ("X6", "追加 第23条第1項第15号ロは 2026-04-01 版から", "chiho", "2026-04-01", "本則:23#1.15.2", "租税特別措置法第九条の三第一号に掲げる同条に規定する配当等（イに掲げるもの及び政令で定めるものを除く。）", True),
    ("X7", "追加 第313条第12項のロの除外は 2026-04-01 版から", "chiho", "2026-04-01", "本則:313#12", "特定配当等（第二十三条第一項第十五号ロに掲げるものを除く。以下この項において同じ。）", True),
    ("X8", "追加 第313条第12項は 2026-03-31 版ではロの除外がない", "chiho", "2026-03-31", "本則:313#12", "第二十三条第一項第十五号ロ", False),
]

# 令和4年法律第1号（地方税法等の一部を改正する法律）の附則（2024-01-01 版の本文に収録されたもの）
SUPPLCHK = [
    ("S1", "PS §8.1 附則第1条第5号の施行日", "chiho", "2024-01-01", "令和四年三月三一日法律第一号", "1", None, "5", "令和六年一月一日", True),
    ("S1b", "PS §8.1 附則第1条第5号の対象（第313条第13項）", "chiho", "2024-01-01", "令和四年三月三一日法律第一号", "1", None, "5", "第三百十三条第十三項", True),
    ("S1c", "PS §8.1 附則第1条第5号の対象（附則第33条の2第2項）", "chiho", "2024-01-01", "令和四年三月三一日法律第一号", "1", None, "5", "附則第三十三条の二第二項", True),
    ("S2", "PS §8.1 附則第11条第1項", "chiho", "2024-01-01", "令和四年三月三一日法律第一号", "11", "1", None, "六年新法の規定中個人の市町村民税に関する部分は、令和六年度以後の年度分の個人の市町村民税について適用し、令和五年度分までの個人の市町村民税については、なお従前の例による。", True),
    ("S3", "PS §8.1 附則第4条第1項（道府県民税）", "chiho", "2024-01-01", "令和四年三月三一日法律第一号", "4", "1", None, "令和六年度以後の年度分の個人の道府県民税について適用", True),
    ("S4", "PS §8.1 附則第11条第2項（令和6〜8年度・令和2〜4年の損失）", "chiho", "2024-01-01", "令和四年三月三一日法律第一号", "11", "2", None, "令和六年度から令和八年度までの各年度分", True),
    ("S4b", "PS §8.1 附則第11条第2項（令和2〜4年）", "chiho", "2024-01-01", "令和四年三月三一日法律第一号", "11", "2", None, "令和二年…令和四年", True),
    ("S4c", "PS §8.1 附則第11条第2項（附則第35条の2の6第11項）", "chiho", "2024-01-01", "令和四年三月三一日法律第一号", "11", "2", None, "附則第三十五条の二の六第十一項", True),
    ("S5", "PS §8.1 令和8年法律第2号 附則第3条第3項", "chiho", "2027-01-01", "令和八年三月三一日法律第二号", "3", "3", None, "施行日以後に支払を受けるべき同号に規定する特定配当等について適用", True),
    ("S5-fix", "訂正後 PS §8.1 同（原文）", "chiho", "2027-01-01", "令和八年三月三一日法律第二号", "3", "3", None, "新法の規定中新法第二十三条第一項第十五号に規定する特定配当等に係る道府県民税に関する部分は、この法律の施行の日（以下「施行日」という。）以後に支払を受けるべき同号に規定する特定配当等について適用し", True),
    ("S6", "追加 令和8年法律第2号 附則第1条（施行期日 令和八年四月一日）", "chiho", "2027-01-01", "令和八年三月三一日法律第二号", "1", "1", None, "この法律は、令和八年四月一日から施行する。", True),
    ("S6b", "追加 同第2号（第292条第1項第7号・第9号は令和九年一月一日）", "chiho", "2027-01-01", "令和八年三月三一日法律第二号", "1", "1", "2", "第二百九十二条第一項第六号、第七号及び第九号…令和九年一月一日", True),
]

# Web：(ID, 文書と節, ページID, 含むべき文字列)
WEBCHK = [
    ("W1.2", "PS §1.2", "tebiki_y01", "上場株式等の配当等に係る利子所得…申告する場合は、申告分離課税の対象となり、総合課税を選択することはできません。"),
    ("W1.4a", "PS §1.4 8の4-1", "sochitsu_8_4", "措置法第8条の4第1項の規定を適用したところにより確定申告書を提出した場合には、その後においてその者が更正の請求をし、又は修正申告書を提出するときにおいても、同項の規定を適用することに留意する"),
    ("W1.4b", "PS §1.4 8の4-1（注）", "sochitsu_8_4", "上場株式等に係る配当所得について申告不要制度若しくは総合課税の適用を受けた場合又は利子所得について申告不要制度の適用を受けた場合においても同様である。"),
    ("W2.2a", "PS §2.2 TA1331 令和8年4月1日現在", "ta_1331", "令和8年4月1日現在法令等"),
    ("W2.2b", "PS §2.2 TA1331 表", "ta_1331", "扶養控除等の判定…合計所得金額に含まれる…合計所得金額に含まれる…（※2）…合計所得金額に含まれない"),
    ("W2.2c", "PS §2.2 TA1331 ※2", "ta_1331", "上場株式等に係る譲渡損失と申告分離課税を選択した上場株式等に係る配当所得との損益通算の特例の適用を受けている場合にはその適用後の金額、上場株式等に係る譲渡損失の繰越控除の適用を受けている場合にはその適用前の金額になります。"),
    ("W2.2d", "HYP H1-1 TA1331 注1", "ta_1331", "（注1） 申告不要、申告分離課税、総合課税のいずれによるかは確定申告において選択し、確定申告において選択した、または、選択しなかった方法は、その後、修正申告や更正の請求において変更することはできません。"),
    ("W2.2e", "PS §2.2 手引き", "tebiki_y01", "この制度を選択した利子等・配当等の金額は、「合計所得金額」に含みません。"),
    ("W2.2f", "PS §2.2 8の5-1", "sochitsu_8_5", "総所得金額又は同法第8条の4第1項に規定する上場株式等に係る配当所得等の金額に算入したところにより確定申告書を提出した場合には、その後においてその者が更正の請求をし、又は修正申告書を提出する場合においても、当該利子所得の金額又は配当所得の金額を総所得金額等の計算上除外することはできないことに留意する。"),
    ("W2.2g", "PS §2.2 8の5-2", "sochitsu_8_5", "措置法第8条の5第1項の規定の適用を受けるときは、その年中に支払う当該負債の利子の額は、法第24条第2項に規定する「負債の利子の額」に含まれないことに留意する"),
    ("W3a", "PS §3 TA1250 令和8年4月1日現在", "ta_1250", "令和8年4月1日現在法令等"),
    ("W3b", "PS §3 TA1250 (10)", "ta_1250", "（10） 確定申告不要制度を選択したもの"),
    ("W3c", "PS §3 TA1250 (11)", "ta_1250", "（11） 申告分離課税制度を選択したもの"),
    ("W3d", "PS §3 TA1250 課税総所得金額等", "ta_1250", "「課税総所得金額等」とは、課税総所得金額、…上場株式等に係る課税配当所得等の金額、株式等に係る課税譲渡所得等の金額…の合計額"),
    ("W4a", "PS §4 TA1463", "ta_1463", "それぞれ別々の申告分離課税とされているため、上場株式等に係る譲渡損失の金額を一般株式等に係る譲渡所得等の金額から控除することはできません。"),
    ("W4b", "PS §4 TA1463（逆も原則できない）", "ta_1463", "一般株式等に係る譲渡損失の金額は、原則として上場株式等に係る譲渡所得等の金額から控除することはできません。"),
    ("W4c", "PS §4 共-24(1)", "kabutsu_37_10_11", "所得税法第2条第1項第30号イ(2)に規定する「合計所得金額」には、措置法第37条の10第6項第1号及び第37条の11第6項の規定により一般株式等に係る譲渡所得等の金額及び上場株式等に係る譲渡所得等の金額が含まれ、所得税法令第11条の2第2項《ひとり親の範囲》に規定する「総所得金額、退職所得金額及び山林所得金額の合計額」には"),
    ("W4d", "PS §4 共-24(2)", "kabutsu_37_10_11", "法令の規定により確定申告書の提出又は確定申告書への記載若しくは明細書等の添付を要件として適用される特例を適用しないで計算した金額による。"),
    ("W5.1a", "PS §5.1 TA1476 1口座", "ta_1476", "1金融商品取引業者等につき、1口座"),
    ("W5.1b", "PS §5.1 TA1476 源泉徴収の率", "ta_1476", "15.315パーセント（他に住民税5パーセント）"),
    ("W5.1c", "PS §5.1 TA1476 選択の時期", "ta_1476", "その年の最初の譲渡の時までに"),
    ("W5.1d", "PS §5.1 TA1476 年単位", "ta_1476", "年単位であることから、年の途中で源泉徴収を行わないように変更することはできません"),
    ("W5.1e", "PS §5.1 TA1476 口座ごと（譲渡）", "ta_1476", "源泉徴収口座内の上場株式等の譲渡による所得については、口座ごとに、申告するまたは申告不要とすることの選択をすることができます"),
    ("W5.1f", "PS §5.1 TA1476 口座ごと（配当）", "ta_1476", "口座ごとに、申告するまたは申告不要とすることの選択をすることができます（1回に支払を受ける利子等または配当等ごとの選択はできません。）。ただし、源泉徴収口座内で生じた上場株式等に係る譲渡損失の金額を申告する場合には、その源泉徴収口座に受け入れた上場株式等に係る利子等の金額および配当等の金額を申告不要とすることはできない"),
    ("W5.1g", "PS §5.1 TA1476 令和8年4月1日現在", "ta_1476", "令和8年4月1日現在法令等"),
    ("W5.2a", "PS §5.2 37の11の5-1", "kabutsu_37_11_5", "（1） 所得税法第2条第1項第30号イ(2)に規定する「合計所得金額」（2） 所得税法令第11条の2第2項に規定する「総所得金額、退職所得金額及び山林所得金額の合計額」（3） 所得税法第120条第1項に規定する「その年分の総所得金額、退職所得金額及び山林所得金額の合計額」（4） 所得税法第121条第1項第1号に規定する「給与所得及び退職所得以外の所得金額」（5） 所得税法第121条第3項に規定する「その年分の公的年金等に係る雑所得以外の所得金額」"),
    ("W5.2b", "PS §5.2 37の11の5-2", "kabutsu_37_11_5", "当該源泉徴収選択口座ごとに行うことができる"),
    ("W5.2c", "PS §5.2 37の11の5-2 ただし書", "kabutsu_37_11_5", "いずれかの勘定において生じた所得又は損失の金額のみについて同法第37条の11の5第1項の規定を適用することはできない"),
    ("W5.2d", "PS §5.2 37の11の5-3 順序", "kabutsu_37_11_5", "まず、申告しようとする源泉徴収選択口座が2以上ある場合には…次に、源泉徴収選択口座以外の特定口座との間で同様の合計計算を行う。…最後に、…特定口座以外の上場株式等に係る譲渡所得等の金額と合計する。"),
    ("W5.2e", "PS §5.2 37の11の5-4", "kabutsu_37_11_5", "更正の請求をし、又は修正申告書を提出する場合においても、当該所得又は損失の金額を当該上場株式等に係る譲渡所得等の金額の計算上除外することはできない"),
    ("W6a", "PS §6 TA1474 注2", "ta_1474", "上場株式等の譲渡であっても、いわゆる相対取引などにより生じた譲渡損失については、損益通算及び繰越控除はできません。"),
    ("W6b", "PS §6 TA1474 申告分離に限る", "ta_1474", "上場株式等に係る配当所得については、申告分離課税を選択したものに限ります"),
    ("W6c", "PS §6 TA1474 3年", "ta_1474", "翌年以後3年間"),
    ("W6d", "PS §6 TA1474 注（譲渡がなかった年も申告）", "ta_1474", "上場株式等の譲渡がなかった年も、譲渡損失を翌年へ繰り越すための申告が必要です。"),
    ("W6e", "PS §6 TA1474 NISA", "ta_1474", "非課税口座（NISA）及び未成年者口座（ジュニアNISA）内の上場株式等を譲渡したことにより生じた譲渡損失については、損益通算及び繰越控除はできません。"),
    ("W6f", "PS §6 TA1474 付表", "ta_1474", "所得税及び復興特別所得税の確定申告書付表（上場株式等に係る譲渡損失の損益通算及び繰越控除用）…株式等に係る譲渡所得等の金額の計算明細書"),
    ("W6g", "PS §6 TA1474 令和8年4月1日現在", "ta_1474", "令和8年4月1日現在法令等"),
    ("W6h", "PS §6 用語集 合計所得金額（繰越控除の適用前）", "yogo_senmon", "合計所得金額…ただし、次の繰越控除を受けている場合は、その適用前の金額をいいます。…上場株式等に係る譲渡損失の繰越控除"),
    ("W6i", "PS §6 用語集 総所得金額等（繰越控除の適用後）", "yogo_senmon", "総所得金額等…その適用後の金額をいいます。…上場株式等に係る譲渡損失の繰越控除"),
    ("W8a", "PS §8.1 手引き 市区町村からのお知らせ", "tebiki_1_12", "令和６年度の個人住民税から、上場株式等に係る配当所得等及び譲渡所得等の申告における課税方式を所得税等の…課税方式と一致させることとなりました。上場株式等に係る配当所得等について、所得税等の確定申告で選択した総合課税、申告分離課税又は確定申告不要制度の課税方式は、個人住民税においても同様の課税方式となります。上場株式等に係る譲渡所得等についても、所得税等の確定申告で選択した申告分離課税又は確定申告不要制度の課税方式は、個人住民税においても同様の課税方式となります。"),
    ("W10a", "PS §10 東プレ健保", "topre_fuyou_jouken", "配当収入…株式配当金・決算剰余配当金等"),
    ("W10a2", "PS §10 東プレ健保", "topre_fuyou_jouken", "その他継続性のある収入…名義貸料・譲渡収入等"),
    ("W10a3", "PS §10 東プレ健保", "topre_fuyou_jouken", "※収入とは、恒久的（現在から将来に続いて）であり、生活費に充当されるもので、所得税など他法の課税非課税を問いません。なお、一時的なものは収入とみなしません。"),
    ("W10b", "PS §10 日本特殊陶業健保", "ngk_family_a", "配当収入（株式配当金、決算剰余配当金等）"),
    ("W10b2", "PS §10 日本特殊陶業健保", "ngk_family_a", "利子収入（預貯金・有価証券利子等）"),
    ("W10c", "PS §10 大塚製薬健保", "otsuka_qa01", "※収入とは、継続的に生じる収入のすべてを含みます。"),
    ("W10c2", "PS §10 大塚製薬健保", "otsuka_qa01", "投資収入（株式配当金、決算剰余配当金 等）"),
    ("W10d", "PS §10 日本電気健保", "nec_fuyousha_shunyu", "配当金収入…株式の配当金"),
    ("W10d2", "PS §10 日本電気健保", "nec_fuyousha_shunyu", "一時金は継続性がないため収入としてはみませんが、銀行等に預金して定期的に利子収入を得た場合は継続性があり生活維持費として健康保険では収入として扱います。"),
    ("W11a", "PS §11.2 手引き 第二表", "tebiki_y01", "申告分離課税とする場合でも、申告書第ニ表「所得の内訳（所得税及び復興特別所得税の源泉徴収税額）」欄に該当事項を記入します。"),
    ("W11b", "PS §11.2 記載例の目次 事例3", "kisairei_kabu", "【事例3】特定口座の譲渡損失を配当所得等から控除し翌年以後に繰り越すケース"),
    ("W12a", "PS §12 TA1331 令和9年", "ta_1331", "令和9年1月1日以後に生ずる所得については、復興特別所得税の税率が1.1パーセントに引き下げられ、防衛特別所得税（源泉徴収すべき所得税の額の1％相当額）が併せて源泉徴収されます。なお、合計税率に変更はありませんので、源泉徴収税額の計算方法に変更は生じません。"),
    ("W12b", "PS §12 TA1331 令和9年分以後の申告", "ta_1331", "令和9年分以後は、復興特別所得税の税率が、基準所得税額の1.1パーセントとなり、防衛特別所得税を、基準所得税額の1パーセントの税率で、所得税および復興特別所得税と合わせて申告・納付"),
    ("W12c", "PS §12 TA1330 令和9年", "ta_1330", "令和9年1月1日以後に生ずる所得については、復興特別所得税の税率が1.1パーセントに引き下げられ、防衛特別所得税（源泉徴収すべき所得税の額の1％相当額）が併せて源泉徴収されます。"),
    ("WH1", "HYP H1 TA1330 1回ごと・口座ごと", "ta_1330", "1回に支払を受けるべき配当等の額ごと（特定口座制度における源泉徴収口座に受け入れた配当等については、口座ごと）に選択することができます"),
    ("WH2", "HYP H1 TA1330 大口株主等は総合のみ（少額配当を除く）", "ta_1330", "「大口株主等」（注）が支払いを受ける上場株式等の配当等および上場株式等以外の配当等については、総合課税の対象となりますので、申告分離課税や確定申告不要制度（下記（２）イの「少額配当」である場合を除きます。）を選択することはできません。"),
    ("WI1", "INF I1 源泉徴収 15.315%", "ta_1330", "15.315パーセント（他に地方税5パーセント）"),
]

# 文書に書かれた Web の取得記録（MEAS §5、PS の本文）：(ページID, Last-Modified の日付, SHA-256 先頭16桁, バイト数)
WEBMETA = [
    ("ta_1330", "2026-09-09", "e97f7323c284b0e2", 21400), ("ta_1331", "2026-09-09", "621495555b3d1fa3", 24458),
    ("ta_1250", "2026-09-09", "cb65c62ac8590834", 20736), ("ta_1463", "2026-09-07", "528a157f810c2333", 23704),
    ("ta_1474", "2026-09-07", "91111d470297e555", 18854), ("ta_1476", "2026-09-07", "1721ce41db4aafb0", 18748),
    ("yogo_senmon", "2026-09-16", "e0d5142e9eabe61f", 21839), ("sochitsu_8_4", "2025-12-25", "5a2aab0dae5f2fec", 4276),
    ("sochitsu_8_5", "2024-11-25", "26204373a4257088", 6931), ("kabutsu_toc", "2026-07-31", "7786d2bf5b349373", 38811),
    ("kabutsu_37_10_11", "2026-07-31", "1a5b4e441444e643", 47988), ("kabutsu_37_11", "2026-07-31", "6fe17ee21b06150e", 21248),
    ("kabutsu_37_11_5", "2024-01-18", "ae1a712d03c06fee", 6929), ("tebiki_1_03", "2025-12-24", "daccf149f371deac", 14498),
    ("tebiki_1_12", "2025-12-24", "c23a64c7061ffc26", 9615), ("tebiki_y01", "2025-12-24", "9b725077601c7541", 18108),
    ("tokushu_kabu", "2026-03-17", "97300df3a2bad4b4", 49357), ("kisairei_kabu", "2026-03-27", "d97d9288336ef595", 13974),
    ("yoshiki_r07_02", "2026-08-31", "1d30dbc3e8823a32", 913314), ("joto_r07_18_2", "2025-12-12", "ed4ae7ab6c4737cb", 356188),
    ("soumu_kinyu_r040715", "2025-03-03", "eaaa241eaee0a37e", 1456240), ("ntt_member_1", "2026-08-12", "43edf8e1590d9531", 159336),
    ("topre_fuyou_jouken", None, "84e4ee1c5cbf60ab", 45925), ("ngk_family_a", None, "eb87109049dd6cd3", 43072),
    ("otsuka_qa01", "2026-09-16", "3fc6921683624502", 30883), ("nec_fuyousha_shunyu", None, "53a88175be327f03", 54981),
]

# 文書に書かれた法令の版（PS §0、MEAS §2・§4.1・§4.2）：(法令, asof, law_revision_id, 改正法令, 施行日, 状態, SHA-256 先頭16桁)
LAWMETA = [
    ("shotoku", S25, "340AC0000000033_20251218_507AC0000000013", "令和七年法律第十三号", "2025-12-18", "PreviousEnforced", "84a2235cb4437184"),
    ("shotoku", S26, "340AC0000000033_20261201_508AC0000000012", "令和八年法律第十二号", "2026-12-01", "UnEnforced", "47792299f0fb5a74"),
    ("sochi", S25, "332AC0000000026_20251231_507AC1000000081", "令和七年法律第八十一号", "2025-12-31", "PreviousEnforced", "ef95d90f7bf57e18"),
    ("sochi", S26, "332AC0000000026_20261204_508AC0000000012", "令和八年法律第十二号", None, "UnEnforced", "763fce2df2b1e709"),
    ("sochi", "2027-01-01", "332AC0000000026_20270101_508AC0000000012", "令和八年法律第十二号", "2027-01-01", "UnEnforced", "8c6ee577201c3be0"),
    ("sochi-rei", S25, "332CO0000000043_20251231_507CO0000000401", "令和七年政令第四百一号", "2025-12-31", "PreviousEnforced", "a3f62b67c672c552"),
    ("sochi-rei", S26, "332CO0000000043_20261201_508CO0000000098", "令和八年政令第九十八号", "2026-12-01", "UnEnforced", "cc9aa8b1a0a429fb"),
    ("chiho", "2026-01-01", "325AC0000000226_20260101_507AC0000000041", "令和七年法律第四十一号", "2026-01-01", "PreviousEnforced", "ba0a40e550be7762"),
    ("chiho", "2027-01-01", "325AC0000000226_20270101_508AC0000000002", "令和八年法律第二号", "2027-01-01", "UnEnforced", "ee21722ce5fd1561"),
    ("kokuho-rei", "2026-04-01", "333CO0000000362_20260401_508CO0000000002", "令和八年政令第二号", "2026-04-01", "PreviousEnforced", "beb2bf7a59170169"),
    ("kokuho-rei", "2027-04-01", "333CO0000000362_20260801_508CO0000000240", "令和八年政令第二百四十号", "2026-08-01", "CurrentEnforced", "913bd2d8016edf64"),
    ("chiho", "2023-12-31", "325AC0000000226_20231213_505AC0000000050", None, None, None, None),
    ("chiho", "2024-01-01", "325AC0000000226_20240101_505AC0000000031", None, None, None, None),
    ("sochi", "2026-01-01", "332AC0000000026_20260101_507AC0000000041", None, None, None, None),
    ("sochi-rei", "2026-01-01", "332CO0000000043_20260101_507CO0000000277", None, None, None, None),
    ("sochi", "2026-11-09", "332AC0000000026_20261101_507AC0000000013", None, None, None, None),
    ("sochi-rei", "2026-11-09", "332CO0000000043_20261101_507CO0000000127", None, None, None, None),
    ("shotoku-rei", S25, "340CO0000000096_20251201_507CO0000000120", None, None, None, None),
]

# MEAS §3 の版の違い：(法令, asofA, asofB, 条, 違うはず(True)/同じはず(False), 追加行に含むはずの文字列, 削除行に含むはずの文字列)
DIFFCHK = [
    ("shotoku", S25, S26, "本則:2", True, ["八十九万円", "三十四の五"], ["八十五万円"]),
    ("shotoku", S25, S26, "本則:120", True, [], []),
    ("sochi", S25, S26, "本則:3", True, [], []),
    ("sochi", S25, S26, "本則:8_4", True, ["第三十四号の五"], ["第三十四号の四"]),
    ("sochi", S25, S26, "本則:8_5", False, [], []),
    ("sochi", S25, S26, "本則:9", False, [], []),
    ("sochi", S25, S26, "本則:29_2", True, [], []),
    ("sochi", S25, S26, "本則:37_10", True, ["第三十四号の五"], []),
    ("sochi", S25, S26, "本則:37_11", True, ["特定受益証券発行信託"], []),
    ("sochi", S25, S26, "本則:37_11_3", True, [], []),
    ("sochi", S25, S26, "本則:37_11_5", False, [], []),
    ("sochi", S25, S26, "本則:37_11_6", False, [], []),
    ("sochi", S25, S26, "本則:37_12_2", False, [], []),
    ("sochi", S25, S26, "本則:37_14", False, [], []),
    ("sochi", S25, S26, "本則:37_14_2", True, [], []),
    ("sochi", S25, S26, "本則:38", True, [], []),
    ("sochi", S26, "2027-01-01", "本則:9_8", True, [], []),
    ("sochi", S26, "2027-01-01", "本則:9_9", True, [], []),
    ("sochi", S26, "2027-01-01", "本則:37_14", True, [], []),
    ("sochi", S26, "2027-01-01", "本則:8_4", False, [], []),
    ("sochi", S26, "2027-01-01", "本則:37_11", False, [], []),
    ("sochi-rei", S25, S26, "本則:4_3", True, [], []),
    ("sochi-rei", S25, S26, "本則:25_8", True, [], []),
    ("sochi-rei", S25, S26, "本則:25_10_12", True, ["第三十四号の五"], ["第三十四号の四"]),
    ("sochi-rei", S25, S26, "本則:25_11_2", True, ["の総所得金額"], []),
    ("sochi-rei", S25, S26, "本則:4_2", False, [], []),
    ("chiho", "2026-01-01", "2027-01-01", "本則:23", True, ["租税特別措置法第九条の三第一号"], []),
    ("chiho", "2026-01-01", "2027-01-01", "本則:32", True, [], []),
    ("chiho", "2026-01-01", "2027-01-01", "本則:292", True, ["法人税割"], []),
    ("chiho", "2026-01-01", "2027-01-01", "本則:292", True, ["六十二万円", "第二十九条の五", "法人税額"], ["五十八万円", "第二十九条の四"]),
    ("chiho", "2026-01-01", "2027-01-01", "本則:313", True, ["第二十三条第一項第十五号ロ"], []),
    ("chiho", "2026-01-01", "2027-01-01", "附則:33_2", True, [], ["附則第五条の四の二"]),
    ("chiho", "2026-01-01", "2027-01-01", "附則:33_2_2", True, [], []),
    ("chiho", "2026-01-01", "2027-01-01", "附則:33_2_3", True, [], []),
    ("chiho", "2026-01-01", "2027-01-01", "附則:35_2", True, [], []),
    ("chiho", "2026-01-01", "2027-01-01", "附則:35_2_2", True, [], []),
    ("chiho", "2026-01-01", "2027-01-01", "附則:35_2_3", True, [], []),
    ("chiho", "2026-01-01", "2027-01-01", "附則:35_2_6", False, [], []),
    ("chiho", "2026-01-01", "2027-01-01", "附則:35_3_2", True, [], []),
    ("chiho", "2026-01-01", "2027-01-01", "附則:35_3_5", True, [], []),
    ("chiho", "2023-12-31", "2024-01-01", "本則:313", True, [], []),
    ("chiho", "2023-12-31", "2024-01-01", "附則:33_2", True, [], []),
    ("chiho", "2023-12-31", "2024-01-01", "附則:35_2_2", True, [], []),
    ("chiho", "2023-12-31", "2024-01-01", "附則:35_2_2", False, [], []),
    ("chiho", "2026-03-31", "2026-04-01", "本則:23", True, ["租税特別措置法第九条の三第一号"], []),
    ("kokuho-rei", "2026-04-01", "2027-04-01", "本則:29_7", False, [], []),
    ("kokuho-rei", "2026-04-01", "2027-04-01", "本則:29_3", True, [], []),
]


def nfkc(s):
    import unicodedata
    return unicodedata.normalize("NFKC", s or "")


def contains_seq_web(hay, needle):
    # NFKC は「…」を「...」に変えるので、先に「…」で分けてから断片ごとに正規化する
    h = norm(nfkc(hay))
    pos = 0
    for seg in [norm(nfkc(x)) for x in re.split(r"…+", needle)]:
        if not seg:
            continue
        i = h.find(seg, pos)
        if i < 0:
            return False
        pos = i + len(seg)
    return True


def suppl_node(L, amend_prefix, art, para, item):
    for s in L.suppl:
        an = (s.get("attr") or {}).get("AmendLawNum", "")
        if not an.startswith(amend_prefix):
            continue
        a = next((c for c in s.get("children", []) if isinstance(c, dict) and c.get("tag") == "Article" and c["attr"].get("Num") == art), None)
        if a is None:
            continue
        n = a
        if para:
            n = next((c for c in n.get("children", []) if isinstance(c, dict) and c.get("tag") == "Paragraph" and c["attr"].get("Num") == para), None)
        if n is not None and item:
            if para is None:
                n = next((c for c in n.get("children", []) if isinstance(c, dict) and c.get("tag") == "Paragraph"), None)
            n = next((c for c in (n or {}).get("children", []) if isinstance(c, dict) and c.get("tag") == "Item" and c["attr"].get("Num") == item), None)
        if n is not None:
            tl = []
            render(n, 0, tl)
            return an, "\n".join(tl)
    return None, None


def e4_broad(laws):
    """申告不要の配当（措法第8条の5）と合計所得金額を結ぶ規定を、項（Paragraph）単位で広く探す。"""
    hits = []
    for key in [("shotoku", S25), ("shotoku-rei", S25), ("sochi", S25), ("sochi-rei", S25)]:
        L = laws[key]

        def fn(n, path, key=key):
            if n.get("tag") != "Paragraph":
                return
            tl = []
            render(n, 0, tl)
            t = "".join(tl)
            ref85 = ("第八条の五" in t) if key[0] in ("sochi", "sochi-rei") else ("租税特別措置法第八条の五" in t)
            if not ref85:
                return
            if key[0] == "sochi-rei":
                ref85 = "法第八条の五" in t
            hit_gokei = ("合計所得金額" in t) or ("第二条第一項第三十号" in t)
            art = next((p for p in reversed(path) if p.get("tag") == "Article"), None)
            insup = any(p.get("tag") == "SupplProvision" for p in path)
            hits.append({"law": key[0], "asof": key[1], "article": art["attr"].get("Num") if art else None,
                         "paragraph": n["attr"].get("Num"), "in_suppl": insup, "mentions_gokei_or_2_1_30": hit_gokei,
                         "snippet": re.sub(r"\s+", "", t)[:300]})
        walk(L.root, fn)
    return hits


# ---- 例の計算（実測の文書 §6 の値を、条文の構造から書き直した計算で再計算する） ----
def recompute_scenarios():
    def kyuyo_r7(x):
        # 所法第28条第3項（令和7年分）：給与等の収入金額が190万円以下なら給与所得控除額は65万円（LH9 で条文を確認）
        assert x <= 1_900_000
        return max(0, x - 650_000)

    def run(kyuyo=0, div=0, mode="fuyo", acct_gain=0, acct_declared=False, other_gain=0, carry=0, nisa=0):
        sogo = kyuyo_r7(kyuyo) + (div if mode == "sogo" else 0)
        div_b = div if mode == "bunri" else 0
        jo = (acct_gain if acct_declared else 0) + other_gain          # 申告する上場株式等の譲渡の損益の合計
        jo_amt = max(0, jo)                                            # 措法37の11①後段：損失は生じなかつたもの
        loss = max(0, -jo)                                             # 措法37の12の2②：譲渡損失の金額（売委託などの譲渡と仮定）
        tsusan = min(loss, div_b)                                      # 同①：分離の配当所得等を限度
        div_after = div_b - tsusan                                     # 同④：第8条の4（第3項第1号を含む）は通算後
        c_jo = min(carry, jo_amt)                                      # 措令25の11の2⑧二：まず譲渡所得等から
        c_div = min(carry - c_jo, div_after)                           # 残りを配当所得等から
        gokei = sogo + div_after + jo_amt                              # 合計所得金額：通算後・繰越控除前（同⑧で第8条の4第3項・第37条の11第6項を除外）
        so_to = sogo + (div_after - c_div) + (jo_amt - c_jo)           # 総所得金額等：繰越控除後（措令25の11の2⑮⑯）
        hi_kyuyo = gokei - kyuyo_r7(kyuyo)                             # 給与所得等以外（この例では給与所得以外は株式等の所得だけ）
        return {"所得税.合計所得金額": gokei, "所得税.総所得金額等": so_to, "住民税.合計所得金額": gokei,
                "国保.所得の合算額(繰越控除後)": so_to, "所得税.勤労学生_給与所得等以外": hi_kyuyo}

    sc = {
        "S1-不要": run(kyuyo=1_100_000, div=200_000, mode="fuyo"),
        "S1-総合": run(kyuyo=1_100_000, div=200_000, mode="sogo"),
        "S1-分離": run(kyuyo=1_100_000, div=200_000, mode="bunri"),
        "S2-不要": run(kyuyo=1_000_000, acct_gain=80_000, acct_declared=False),
        "S2-申告": run(kyuyo=1_000_000, acct_gain=80_000, acct_declared=True),
        "S3-分離で通算": run(div=100_000, mode="bunri", other_gain=-300_000),
        "S3-総合(通算不可)": run(div=100_000, mode="sogo", other_gain=-300_000),
        "S4-繰越": run(div=200_000, mode="bunri", acct_gain=300_000, acct_declared=True, carry=400_000),
        "S5-NISA": run(nisa=1_000_000),
    }
    # 実測の文書 §6 の表の値（合計所得金額, 総所得金額等, 住民税.合計所得金額, 国保, 勤労学生の給与所得等以外）
    claimed = {
        "S1-不要": (450_000, 450_000, 450_000, 450_000, 0), "S1-総合": (650_000, 650_000, 650_000, 650_000, 200_000),
        "S1-分離": (650_000, 650_000, 650_000, 650_000, 200_000), "S2-不要": (350_000, 350_000, 350_000, 350_000, 0),
        "S2-申告": (430_000, 430_000, 430_000, 430_000, 80_000), "S3-分離で通算": (0, 0, 0, 0, 0),
        "S3-総合(通算不可)": (100_000, 100_000, 100_000, 100_000, 100_000), "S4-繰越": (500_000, 100_000, 500_000, 100_000, 500_000),
        "S5-NISA": (0, 0, 0, 0, 0),
    }
    keys = ["所得税.合計所得金額", "所得税.総所得金額等", "住民税.合計所得金額", "国保.所得の合算額(繰越控除後)", "所得税.勤労学生_給与所得等以外"]
    out = []
    for k, v in sc.items():
        got = tuple(v[x] for x in keys)
        out.append({"scenario": k, "recomputed": got, "claimed": claimed[k], "ok": got == claimed[k]})
    # 判定（令和7年分の境目。条文で確認した値：扶養親族 58万以下、特定親族 58万超123万以下、勤労学生 85万以下かつ10万以下）
    jd = {}
    for k, v in sc.items():
        g, h = v["所得税.合計所得金額"], v["所得税.勤労学生_給与所得等以外"]
        jd[k] = {"扶養親族": g <= 580_000, "特定親族": 580_000 < g <= 1_230_000, "勤労学生": g <= 850_000 and h <= 100_000}
    # 推測 I1 の親の控除額（令和7年分の所得税・令和8年度分の住民税）
    def tokutei_shinzoku_it(g):  # 所法第84条の2第1項第1号のみ（85万円以下 63万円）
        return 630_000 if 580_000 < g <= 850_000 else None

    def tokutei_shinzoku_lt(g):  # 地方税法第314条の2第1項第12号イ（95万円以下 45万円）
        return 450_000 if 580_000 < g <= 950_000 else None
    i1 = {"S1-総合.親の所得税の特定親族特別控除": tokutei_shinzoku_it(650_000), "S1-総合.親の住民税の特定親族特別控除": tokutei_shinzoku_lt(650_000),
          "S1-不要.親の所得税の特定扶養控除": 630_000, "S1-不要.親の住民税の特定扶養控除": 450_000,
          "I4.医療費控除の足切り(総所得金額等10万円)": min(100_000 * 5 // 100, 100_000), "I4.医療費控除額(医療費3万円)": 30_000 - min(100_000 * 5 // 100, 100_000)}
    return out, jd, i1


def run_checks(dl, laws, web):
    results = []
    ts = dl.name.split("_")[0]
    # 版
    for short, asof, rid, aln, aed, st, sha in LAWMETA:
        L = laws.get((short, asof))
        m = L.meta if L else {}
        got = (m.get("law_revision_id"), m.get("amendment_law_num"), m.get("amendment_enforcement_date"), m.get("current_revision_status"), (m.get("sha256") or "")[:16])
        exp = (rid, aln, aed, st, sha)
        ok = all(e is None or g == e for g, e in zip(got, exp)) if not (aed is None and aln) else (got[0] == rid and got[1] == aln and got[3] == st and got[2] in (None, "") and (sha is None or got[4] == sha))
        results.append({"id": f"V-{short}-{asof}", "kind": "版", "doc": "PS §0・MEAS §2", "expected": exp, "got": got, "ok": ok})
    # 条文
    for cid, doc, short, asof, addr, needle, expect in LAWCHK:
        L = laws.get((short, asof))
        t = L.text(addr) if L else None
        found = t is not None and contains_seq(t, needle)
        results.append({"id": cid, "kind": "条文", "doc": doc, "law": short, "asof": asof, "addr": addr,
                        "law_revision_id": L.meta["law_revision_id"] if L else None, "needle": needle, "expect": expect,
                        "node_found": t is not None, "found": found, "ok": found == expect})
    # 改正法の附則
    sup_dump = []
    for cid, doc, short, asof, amend, art, para, item, needle, expect in SUPPLCHK:
        L = laws.get((short, asof))
        an, t = suppl_node(L, amend, art, para, item) if L else (None, None)
        found = t is not None and contains_seq(t, needle)
        sup_dump.append(f"## {cid} {short} {asof} 附則（{an}） 第{art}条 第{para}項 第{item}号\n{t}\n")
        results.append({"id": cid, "kind": "附則", "doc": doc, "law": short, "asof": asof, "amend": an, "where": f"第{art}条第{para}項第{item}号",
                        "needle": needle, "expect": expect, "found": found, "ok": found == expect})
    # 令和8年法律第2号の附則第1条（施行期日）も読むために書き出す
    for amend, art in (("令和八年三月三一日法律第二号", "1"), ("令和八年三月三一日法律第二号", "3"), ("令和八年三月三一日法律第二号", "11")):
        an, t = suppl_node(laws[("chiho", "2027-01-01")], amend, art, None, None)
        sup_dump.append(f"## 参考 chiho 2027-01-01 附則（{an}） 第{art}条（全文）\n{t}\n")
    (OUT / "suppl_extracts.md").write_text("\n".join(sup_dump), encoding="utf-8")
    # 版の違い
    dmd = ["# 版の違い（MEAS §3 の照合用）", ""]
    for di, (short, a, b, key, should_differ, add_needles, del_needles) in enumerate(DIFFCHK):
        ta, tb = laws[(short, a)].text(key) or "", laws[(short, b)].text(key) or ""
        differ = ta != tb
        ud = list(difflib.unified_diff(ta.splitlines(), tb.splitlines(), a, b, lineterm="", n=0))
        added = "\n".join(x[1:] for x in ud if x.startswith("+") and not x.startswith("+++"))
        removed = "\n".join(x[1:] for x in ud if x.startswith("-") and not x.startswith("---"))
        ok = (differ == should_differ) and all(n in added for n in add_needles) and all(n in removed for n in del_needles)
        results.append({"id": f"D{di:02d}-{short}-{key}-{a}-{b}", "kind": "版の違い", "doc": "MEAS §3・§4.1・PS §9", "expect_differ": should_differ,
                        "differ": differ, "add_needles": add_needles, "del_needles": del_needles, "ok": ok})
        dmd.append(f"## {short} {key} {a} → {b}: {'違う' if differ else '同じ'}")
        if differ:
            dmd += ["```diff"] + [x[:1200] for x in ud] + ["```"]
        dmd.append("")
    (OUT / "diffs.md").write_text("\n".join(dmd), encoding="utf-8")
    # E4 を広げた探索
    e4 = e4_broad(laws)
    (OUT / "e4_broad.json").write_text(json.dumps(e4, ensure_ascii=False, indent=1), encoding="utf-8")
    n_g = sum(1 for h in e4 if h["mentions_gokei_or_2_1_30"])
    results.append({"id": "E4-broad", "kind": "探索", "doc": "PS §2.2・MEAS §4.3",
                    "claim": "所法・所令・措法・措令（2025-12-31）の項のうち、措法第8条の5 を引用し、かつ合計所得金額または所法第2条第1項第30号に触れるもの",
                    "paragraphs_citing_8_5": len(e4), "with_gokei": n_g, "ok": n_g == 0})
    # Web
    for wid, doc, page, needle in WEBCHK:
        t = web.get(page)
        found = t is not None and contains_seq_web(t, needle)
        results.append({"id": wid, "kind": "Web", "doc": doc, "page": page, "needle": needle, "found": found, "ok": found})
    flog = sorted(OUT.glob(f"fetch_{ts}.json"))
    wl = {}
    if flog:
        for w in json.loads(flog[-1].read_text(encoding="utf-8"))["web"]:
            wl[w["id"]] = w
    import email.utils
    for page, lm, sha, size in WEBMETA:
        w = wl.get(page, {})
        lmd = None
        if w.get("last_modified"):
            lmd = email.utils.parsedate_to_datetime(w["last_modified"]).strftime("%Y-%m-%d")
        got = (lmd, (w.get("sha256") or "")[:16], w.get("bytes"))
        results.append({"id": f"WM-{page}", "kind": "Web の版", "doc": "MEAS §5・PS 本文", "expected": (lm, sha, size), "got": got,
                        "ok": got == (lm, sha, size)})
    # 例の計算
    sc, jd, i1 = recompute_scenarios()
    for r in sc:
        results.append({"id": f"SC-{r['scenario']}", "kind": "例の計算", "doc": "MEAS §6", "expected": r["claimed"], "got": r["recomputed"], "ok": r["ok"]})
    exp_j = {"S1-不要": (True, False, True), "S1-総合": (False, True, False), "S1-分離": (False, True, False),
             "S2-不要": (True, False, True), "S2-申告": (True, False, True)}
    for k, e in exp_j.items():
        g = (jd[k]["扶養親族"], jd[k]["特定親族"], jd[k]["勤労学生"])
        results.append({"id": f"SJ-{k}", "kind": "判定", "doc": "MEAS §6・INF I1・I2", "expected": e, "got": g, "ok": g == e})
    exp_i1 = {"S1-総合.親の所得税の特定親族特別控除": 630_000, "S1-総合.親の住民税の特定親族特別控除": 450_000,
              "S1-不要.親の所得税の特定扶養控除": 630_000, "S1-不要.親の住民税の特定扶養控除": 450_000,
              "I4.医療費控除の足切り(総所得金額等10万円)": 5_000, "I4.医療費控除額(医療費3万円)": 25_000}
    for k, e in exp_i1.items():
        results.append({"id": f"SI-{k}", "kind": "推測の数値", "doc": "INF I1・I4", "expected": e, "got": i1[k], "ok": i1[k] == e})
    # 出力
    out = {"run_at": time.strftime("%Y%m%d-%H%M%S"), "download_dir": str(dl.relative_to(ROOT)),
           "laws": [L.meta for L in laws.values()], "results": results}
    (OUT / "xcheck.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    md = [f"# R2B_kabu_xcheck 結果（データ：{dl.relative_to(ROOT)}）", "",
          f"- 合格 {sum(1 for r in results if r['ok'])} / {len(results)}", "",
          "| ID | 種類 | 文書と節 | 結果 | 補足 |", "|---|---|---|---|---|"]
    for r in results:
        extra = ""
        if r["kind"] in ("版", "Web の版", "例の計算", "判定", "推測の数値") and not r["ok"]:
            extra = f"期待 {r['expected']} / 実際 {r['got']}"
        elif r["kind"] == "条文":
            extra = f"{r['law']} {r['asof']} {r['addr']}" + ("" if r["node_found"] else "（番地なし）")
        elif r["kind"] == "版の違い":
            extra = f"違う={r['differ']}（期待 {r['expect_differ']}）"
        elif r["kind"] == "探索":
            extra = f"第8条の5 を引用する項 {r['paragraphs_citing_8_5']} 件、うち合計所得金額等に触れるもの {r['with_gokei']} 件"
        md.append(f"| {r['id']} | {r['kind']} | {r['doc']} | {'OK' if r['ok'] else '**NG**'} | {extra} |")
    md += ["", "## 取得した法令の版", ""] + [f"- {m['short']} asof={m['asof']} {m['law_revision_id']} {m['amendment_law_num']} 施行={m['amendment_enforcement_date']} {m['current_revision_status']} sha256={m['sha256'][:16]} {m['bytes']}B" for m in (L.meta for L in laws.values())]
    md += ["", "## Web の取得", ""] + [f"- {k} {w.get('status')} {w.get('bytes')}B LM={w.get('last_modified')} sha256={(w.get('sha256') or '')[:16]}" for k, w in wl.items()]
    (OUT / "xcheck.md").write_text("\n".join(md), encoding="utf-8")
    bad = [r["id"] for r in results if not r["ok"]]
    print(f"合格 {len(results) - len(bad)} / {len(results)}")
    print("NG:", bad)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

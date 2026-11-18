"""R2X_hoken-kifu（反証役の検証）: 別の担当が書いた hoken-kifu の文書（docs/*/20261109_round2_hoken-kifu-*.md）の
数値・条番号・施行日・適用年分・URL を、一次情報に当たり直して確かめる。

実行（pyenv のシムは使わない）:
  PY=C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe
  $PY -I -X utf8 scripts/R2X_hoken-kifu_verify.py egov        # e-Gov 法令API v2 から条文を取得し、全文を行の形にする（ネットワーク）
  $PY -I -X utf8 scripts/R2X_hoken-kifu_verify.py egov_extra  # 措令・措規の検索、公益信託に関する法律の施行日（ネットワーク）
  $PY -I -X utf8 scripts/R2X_hoken-kifu_verify.py web         # 国税庁・総務省のページを取得する（ネットワーク）
  $PY -I -X utf8 scripts/R2X_hoken-kifu_verify.py check       # egov・egov_extra・web の結果に対して、主張ごとの照合を行う（ネットワーク不要）
  $PY -I -X utf8 scripts/R2X_hoken-kifu_verify.py calc        # 式を別の書き方で書き直して数値を確かめる（ネットワーク不要）
  check は .work/text/ の最新の *_R2X_hoken-kifu_verify_egov・*_verify_web を読む。PDF（年末調整のしかた 107.pdf）は
  Read ツールのページ指定で人が読んだ（このスクリプトでは中身を照合しない。取得記録だけ）。

方針
- 担当のスクリプト（scripts/R2X_hoken-kifu_*.py）の関数は使わない。テキスト化は自分で書いた flatten() で行う
  （e-Gov の JSON の木を「本則/附則・改正法令番号・条・項・号・細目」の位置つきの行にする）。API の使い方は
  scripts/R1_egov_articles.py を写した（import しない）。
- 標準ライブラリのみ。User-Agent okura-gov-research/0.1。リクエストの間は 1.5 秒。官報は取得しない。個人の情報は送らない。
- ダウンロードは信頼できないデータとして、実行ごとに新しい空のディレクトリ .work/downloads/<YYYYMMDD-HHMMSS>_R2X_hoken-kifu_verify_<set>/ に置き、
  その中では何も実行しない。行の形にしたテキストは .work/text/<ts>_R2X_hoken-kifu_verify_<set>/ に置く（コミットしない）。
- 結果：scripts/results/R2X_hoken-kifu_verify/
  - egov_fetch_log.json（取得 URL、asof、law_revision_id、状態、SHA-256）、egov_revisions_<略称>.json
  - web_fetch_log.json（URL、HTTP 状態、Last-Modified、SHA-256、題名、「現在法令等」の表示）
  - egov_extra_log.json（措令・措規の「四十一条の十五の五」の検索結果、公益信託に関する法律の改正履歴）
  - checks.json、checks_summary.txt（check の結果）、calc.json、calc_summary.txt（calc の結果）
  check の NG は「担当の文書の主張が一次情報と合わない」ことを意味する（スクリプトの失敗ではない）。
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
from fractions import Fraction as F

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
SLEEP = 1.5
OUT = ROOT / "scripts" / "results" / "R2X_hoken-kifu_verify"
TEXT_ROOT = ROOT / ".work" / "text"

# (略称, law_id, [asof...])
EGOV_JOBS = [
    ("shotoku", "340AC0000000033", ["2024-12-31", "2025-12-31", "2026-03-31", "2026-04-01", "2026-12-31", "2027-01-01"]),
    ("shotoku-rei", "340CO0000000096", ["2025-12-31", "2026-12-31", "2027-01-01"]),
    ("shotoku-ki", "340M50000040011", ["2025-12-31", "2026-01-01", "2026-12-31", "2027-01-01"]),
    ("sochi", "332AC0000000026", ["2025-12-31", "2026-01-01", "2026-03-31", "2026-04-01", "2026-11-09", "2026-12-31", "2027-01-01"]),
    ("chiho", "325AC0000000226", ["2025-12-31", "2026-01-01", "2026-03-31", "2026-04-01", "2026-11-09", "2027-01-01"]),
    ("chiho-rei", "325CO0000000245", ["2025-12-31", "2026-01-01", "2026-11-09", "2027-01-01"]),
]
REVISIONS = [("shotoku", "340AC0000000033"), ("shotoku-rei", "340CO0000000096"), ("sochi", "332AC0000000026"),
             ("chiho", "325AC0000000226"), ("chiho-rei", "325CO0000000245")]


def get(url, accept="application/json"):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            body, st, hdr = r.read(), r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        body, st, hdr = e.read(), e.code, dict(e.headers or {})
    time.sleep(SLEEP)
    return st, body, hdr


# ---------------- e-Gov の JSON の木を、位置つきの行にする（自作） ----------------
def text_all(n):
    """節の下のすべての文字列をつなぐ（ルビ Rt は除く）。"""
    if isinstance(n, str):
        return n
    if n.get("tag") == "Rt":
        return ""
    return "".join(text_all(c) for c in n.get("children", []))


def kids(n, tag=None):
    return [c for c in n.get("children", []) if isinstance(c, dict) and (tag is None or c.get("tag") == tag)]


STRUCT_TITLES = {"Part": "PartTitle", "Chapter": "ChapterTitle", "Section": "SectionTitle",
                 "Subsection": "SubsectionTitle", "Division": "DivisionTitle"}


def flatten(root):
    """戻り値：行のリスト。各行は dict(part, amend, struct, art, cap, para, item, text)。
    part = "M"（本則）/"S"（附則）。amend = 改正法令番号（原始附則は "orig"）。
    struct = 編・章・節・款・目の題名を " / " でつないだもの（本則のみ）。
    art = 条の Num 属性。cap = 条の見出し。para = 項の Num。item = 号・細目の Num を "-" でつないだもの。
    text = その項・号の文（下位の号を含まない）。表の行は item に "表" を付けて1行ずつ。"""
    rows = []

    def sentence_text(node):
        out = []
        for c in kids(node):
            t = c.get("tag", "")
            if t.endswith("Sentence"):
                cols = kids(c, "Column")
                if cols:
                    out.append("　".join(text_all(x) for x in cols))
                else:
                    out.append(text_all(c))
        return "".join(out)

    def walk(n, ctx):
        if not isinstance(n, dict):
            return
        tag = n.get("tag", "")
        attr = n.get("attr") or {}
        if tag == "SupplProvision":
            ctx = dict(ctx, part="S", amend=attr.get("AmendLawNum", "orig"), struct="")
        elif tag in STRUCT_TITLES and ctx["part"] == "M":
            title = "".join(text_all(c) for c in kids(n, STRUCT_TITLES[tag]))
            ctx = dict(ctx, struct=(ctx["struct"] + " / " + title) if ctx["struct"] else title)
        elif tag == "Article":
            cap = "".join(text_all(c) for c in kids(n, "ArticleCaption"))
            ctx = dict(ctx, art=attr.get("Num"), cap=cap, para=None, item="")
            for c in kids(n):
                walk(c, ctx)
            return
        elif tag == "Paragraph":
            ctx = dict(ctx, para=attr.get("Num"), item="")
            rows.append(dict(ctx, text=sentence_text(n)))
        elif tag == "Item" or re.fullmatch(r"Subitem\d+", tag):
            ctx = dict(ctx, item=(ctx["item"] + "-" if ctx["item"] else "") + (attr.get("Num") or "?"))
            rows.append(dict(ctx, text=sentence_text(n)))
        elif tag == "TableRow":
            cells = [text_all(c).replace("\n", " ") for c in kids(n)]
            rows.append(dict(ctx, item=(ctx["item"] + "-表" if ctx["item"] else "表"), text=" | ".join(cells)))
            return
        for c in kids(n):
            walk(c, ctx)

    walk(root, {"part": "M", "amend": "", "struct": "", "art": None, "cap": "", "para": None, "item": ""})
    return rows


def row_line(r):
    return "\t".join([r["part"], r["amend"] or "", r["art"] or "", r["para"] or "", r["item"] or "", r["cap"] or "",
                      r["struct"] or "", r["text"].replace("\t", " ").replace("\n", " ")])


def cmd_egov():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_hoken-kifu_verify_egov"
    dl.mkdir(parents=True, exist_ok=False)
    tx = TEXT_ROOT / f"{ts}_R2X_hoken-kifu_verify_egov"
    tx.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"),
           "text_dir": str(tx.relative_to(ROOT)).replace("\\", "/"), "fetches": [], "revisions": []}
    for short, law_id, asofs in EGOV_JOBS:
        for asof in asofs:
            url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
            st, body, _ = get(url)
            raw = dl / f"{short}_{asof}.json"
            raw.write_bytes(body)
            ent = {"short": short, "law_id": law_id, "asof": asof, "url": url, "status": st,
                   "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
            if st == 200:
                d = json.loads(body)
                ri = d.get("revision_info") or {}
                for k in ("law_title", "law_revision_id", "amendment_law_num", "amendment_law_title", "amendment_enforcement_date",
                          "current_revision_status", "updated"):
                    ent[k] = ri.get(k)
                rows = flatten(d["law_full_text"])
                (tx / f"{short}_{asof}.tsv").write_text("\n".join(row_line(r) for r in rows), encoding="utf-8")
                ent["rows"] = len(rows)
            log["fetches"].append(ent)
            print("egov", short, asof, st, ent.get("law_revision_id"), ent.get("current_revision_status"), flush=True)
    for short, law_id in REVISIONS:
        url = f"{API}/law_revisions/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "amendment_date_from": "2025-01-01"})
        st, body, _ = get(url)
        (dl / f"revisions_{short}.json").write_bytes(body)
        revs = []
        if st == 200:
            for rv in json.loads(body).get("revisions", []):
                revs.append({k: rv.get(k) for k in ("law_revision_id", "amendment_promulgate_date", "amendment_enforcement_date",
                                                   "amendment_law_title", "amendment_law_num", "current_revision_status")})
        (OUT / f"egov_revisions_{short}.json").write_text(json.dumps({"url": url, "status": st, "n": len(revs), "revisions": revs},
                                                                     ensure_ascii=False, indent=1), encoding="utf-8")
        log["revisions"].append({"short": short, "url": url, "status": st, "n": len(revs), "sha256": hashlib.sha256(body).hexdigest()})
        print("revisions", short, st, len(revs), flush=True)
    (OUT / "egov_fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


def cmd_egov_extra():
    """公益信託に関する法律（令和6年法律第30号）の施行日を、e-Gov の改正履歴（制定時の施行日）と施行期日政令の検索で確かめる。"""
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_hoken-kifu_verify_egov_extra"
    dl.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    reqs = [
        ("koeki_revisions", f"{API}/law_revisions/506AC0000000030?" + urllib.parse.urlencode({"response_format": "json"})),
        ("koeki_shikoki_search", f"{API}/laws?" + urllib.parse.urlencode({"response_format": "json", "law_title": "公益信託に関する法律の施行期日"})),
    ]
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "requests": []}
    # 租税特別措置法施行令・同施行規則に、措法第41条の15の5 の扶養親族の所属（所法85⑥との関係）を定める規定があるか
    for name, lid in (("sochirei", "332CO0000000043"), ("sochiki", "332M50000040015")):
        url = f"{API}/law_data/{lid}?" + urllib.parse.urlencode({"response_format": "json", "asof": "2026-11-09"})
        st, body, _ = get(url)
        (dl / f"{name}_2026-11-09.json").write_bytes(body)
        ent = {"name": name, "url": url, "status": st, "sha256": hashlib.sha256(body).hexdigest()}
        if st == 200:
            d = json.loads(body)
            ri = d.get("revision_info") or {}
            ent.update({k: ri.get(k) for k in ("law_title", "law_revision_id", "current_revision_status")})
            rows = flatten(d["law_full_text"])
            ent["hits_41_15_5"] = [{k: r[k] for k in ("part", "amend", "art", "para", "item", "cap")} | {"text": r["text"][:400]}
                                   for r in rows if "四十一条の十五の五" in r["text"]]
        log["requests"].append(ent)
        print("extra", name, st, len(ent.get("hits_41_15_5", [])), flush=True)
    for name, url in reqs:
        st, body, _ = get(url)
        (dl / f"{name}.json").write_bytes(body)
        ent = {"name": name, "url": url, "status": st, "sha256": hashlib.sha256(body).hexdigest()}
        if st == 200:
            d = json.loads(body)
            if "revisions" in d:
                ent["law_info"] = d.get("law_info")
                ent["revisions"] = [{k: rv.get(k) for k in ("law_revision_id", "law_title", "amendment_law_num", "amendment_law_title",
                                                         "amendment_promulgate_date", "amendment_enforcement_date",
                                                         "current_revision_status")} for rv in d["revisions"]]
            if "laws" in d:
                ent["laws"] = [{"law_info": l.get("law_info"),
                                "revision_info": {k: (l.get("revision_info") or {}).get(k) for k in
                                                  ("law_revision_id", "law_title", "amendment_enforcement_date", "current_revision_status")}}
                               for l in d["laws"]]
        log["requests"].append(ent)
        print("extra", name, st, flush=True)
    # 見つかった施行期日政令の本文（あれば）
    for ent in list(log["requests"]):
        for l in ent.get("laws", []):
            lid = (l.get("law_info") or {}).get("law_id")
            if lid:
                url = f"{API}/law_data/{lid}?" + urllib.parse.urlencode({"response_format": "json"})
                st, body, _ = get(url)
                (dl / f"law_{lid}.json").write_bytes(body)
                rec = {"name": f"law_data_{lid}", "url": url, "status": st, "sha256": hashlib.sha256(body).hexdigest()}
                if st == 200:
                    d = json.loads(body)
                    rec["text"] = [r["text"] for r in flatten(d["law_full_text"])][:20]
                    rec["revision_info"] = d.get("revision_info")
                log["requests"].append(rec)
                print("extra", rec["name"], st, flush=True)
    (OUT / "egov_extra_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------- 国税庁・総務省のページ ----------------
TA = "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/"
WEB = {
    "ta_1110": TA + "1110.htm", "ta_1135": TA + "1135.htm", "ta_1140": TA + "1140.htm", "ta_1140_qa": TA + "1140_qa.htm",
    "ta_1141": TA + "1141.htm", "ta_1145": TA + "1145.htm", "ta_1146": TA + "1146.htm", "ta_1150": TA + "1150.htm",
    "ta_1155": TA + "1155.htm", "ta_1902": TA + "1902.htm",
    "shitsugi_05_74": "https://www.nta.go.jp/law/shitsugi/shotoku/05/74.htm",
    "shitsugi_05_75": "https://www.nta.go.jp/law/shitsugi/shotoku/05/75.htm",
    "shitsugi_05_76": "https://www.nta.go.jp/law/shitsugi/shotoku/05/76.htm",
    "shitsugi_05_68": "https://www.nta.go.jp/law/shitsugi/shotoku/05/68.htm",
    "shitsugi_05_05": "https://www.nta.go.jp/law/shitsugi/shotoku/05/05.htm",
    "shitsugi_02_37": "https://www.nta.go.jp/law/shitsugi/shotoku/02/37.htm",
    "shitsugi_gensen_03_35": "https://www.nta.go.jp/law/shitsugi/gensen/03/35.htm",
    "kihon_16_01": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/16/01.htm",
    "kihon_16_03": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/16/03.htm",
    "kihon_16_04": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/16/04.htm",
    "kihon_16_05": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/16/05.htm",
    "kihon_16_06": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/16/06.htm",
    "nta_furusato": "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tokushu/keisubetsu/furusato.htm",
    "nta_tokyo_onestop": "https://www.nta.go.jp/about/organization/tokyo/topics/furusato_nozei_onestop/index.htm",
    "soumu_furusato_index": "https://www.soumu.go.jp/main_sosiki/jichi_zeisei/czaisei/czaisei_seido/furusato/policy/",
    "soumu_mechanism": "https://www.soumu.go.jp/main_sosiki/jichi_zeisei/czaisei/czaisei_seido/furusato/mechanism/deduction.html",
    "nencho2026_index": "https://www.nta.go.jp/publication/pamph/gensen/nencho2026/01.htm",
    "nencho2026_107pdf": "https://www.nta.go.jp/publication/pamph/gensen/nencho2026/pdf/107.pdf",
    "nencho2026_105pdf": "https://www.nta.go.jp/publication/pamph/gensen/nencho2026/pdf/105.pdf",
}


class TextHTML(html.parser.HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "dt", "dd", "section", "article"}
    SKIP = {"script", "style", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip, self.title, self.in_title = [], 0, "", False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        if tag == "title":
            self.in_title = True
        if tag in self.BLOCK or tag in ("td", "th"):
            self.parts.append("\n" if tag not in ("td", "th") else " | ")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag == "title":
            self.in_title = False
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if not self.skip:
            self.parts.append(data)

    def text(self):
        t = "".join(self.parts)
        t = re.sub(r"[ \t\r\f\v\u3000]+", " ", t)
        return re.sub(r"\n\s*\n+", "\n", t)


def decode(body, hdr):
    ct = (hdr.get("Content-Type") or hdr.get("content-type") or "").lower()
    m = re.search(r"charset=([\w-]+)", ct) or re.search(rb'charset=["\']?([\w-]+)', body[:2000])
    enc = (m.group(1).decode() if isinstance(m.group(1), bytes) else m.group(1)) if m else "utf-8"
    try:
        return body.decode(enc, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def cmd_web():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_hoken-kifu_verify_web"
    dl.mkdir(parents=True, exist_ok=False)
    tx = TEXT_ROOT / f"{ts}_R2X_hoken-kifu_verify_web"
    tx.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    robots = {}
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"),
           "text_dir": str(tx.relative_to(ROOT)).replace("\\", "/"), "robots": {}, "pages": []}
    for host in sorted({urllib.parse.urlsplit(u).netloc for u in WEB.values()}):
        rurl = f"https://{host}/robots.txt"
        st, body, _ = get(rurl, accept="text/plain")
        (dl / f"robots_{host}.txt").write_bytes(body)
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(body.decode("utf-8", errors="replace").splitlines() if st == 200 else [])
        robots[host] = rp
        log["robots"][host] = {"status": st, "sha256": hashlib.sha256(body).hexdigest()}
    for pid, url in WEB.items():
        host = urllib.parse.urlsplit(url).netloc
        if not robots[host].can_fetch(UA, url):
            log["pages"].append({"id": pid, "url": url, "skipped": "robots.txt"})
            continue
        st, body, hdr = get(url, accept="*/*")
        ext = ".pdf" if url.endswith(".pdf") else ".html"
        (dl / f"{pid}{ext}").write_bytes(body)
        ent = {"id": pid, "url": url, "status": st, "last_modified": hdr.get("Last-Modified") or hdr.get("last-modified"),
               "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
        if ext == ".html" and st == 200:
            p = TextHTML()
            p.feed(decode(body, hdr))
            t = p.text()
            (tx / f"{pid}.txt").write_text(t, encoding="utf-8")
            ent["title"] = p.title.strip()
            m = re.search(r"\[?［?令和\s*\d+\s*年\s*\d+\s*月\s*\d+\s*日現在法令等\]?］?", t)
            ent["genzai_horei"] = m.group(0) if m else None
        log["pages"].append(ent)
        print("web", pid, st, ent.get("last_modified"), flush=True)
    (OUT / "web_fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------- 照合（ネットワーク不要） ----------------
def latest_dir(suffix):
    ds = sorted(p for p in TEXT_ROOT.glob(f"*_R2X_hoken-kifu_verify_{suffix}") if p.is_dir())
    if not ds:
        raise SystemExit(f"先に {suffix} を実行する")
    return ds[-1]


class Law:
    def __init__(self, path):
        self.rows = []
        for ln in path.read_text(encoding="utf-8").split("\n"):
            c = ln.split("\t")
            if len(c) == 8:
                self.rows.append(dict(part=c[0], amend=c[1], art=c[2], para=c[3], item=c[4], cap=c[5], struct=c[6], text=c[7]))

    def sel(self, part="M", amend=None, art=None, para=None, item=None, item_prefix=None):
        out = []
        for r in self.rows:
            if r["part"] != part:
                continue
            if amend is not None and r["amend"] != amend:
                continue
            if art is not None and r["art"] != art:
                continue
            if para is not None and r["para"] != para:
                continue
            if item is not None and r["item"] != item:
                continue
            if item_prefix is not None and not (r["item"] == item_prefix or r["item"].startswith(item_prefix + "-")):
                continue
            out.append(r)
        return out

    def text(self, **kw):
        return "\n".join(r["text"] for r in self.sel(**kw))

    def article_sig(self, part="M", amend=None, art=None):
        rows = self.sel(part=part, amend=amend, art=art)
        return hashlib.sha256("\n".join(f"{r['para']}|{r['item']}|{r['text']}" for r in rows).encode("utf-8")).hexdigest()[:12] if rows else None

    def search(self, s, part=None):
        return [r for r in self.rows if s in r["text"] and (part is None or r["part"] == part)]


def latest_dir(suffix):
    ds = sorted(p for p in TEXT_ROOT.glob(f"*_R2X_hoken-kifu_verify_{suffix}") if p.is_dir())
    if not ds:
        raise SystemExit(f"先に {suffix} を実行する")
    return ds[-1]


class Law:
    def __init__(self, path):
        self.rows = []
        for ln in path.read_text(encoding="utf-8").split("\n"):
            c = ln.split("\t")
            if len(c) == 8:
                self.rows.append(dict(part=c[0], amend=c[1], art=c[2], para=c[3], item=c[4], cap=c[5], struct=c[6], text=c[7]))

    def sel(self, part="M", amend="", art=None, para=None, item=None):
        out = []
        for r in self.rows:
            if r["part"] != part or (amend is not None and r["amend"] != amend) or (art is not None and r["art"] != art):
                continue
            if para is not None and r["para"] != para:
                continue
            if item is not None and not (r["item"] == item or r["item"].startswith(item + "-")):
                continue
            out.append(r)
        return out

    def text(self, **kw):
        return "\n".join(r["text"] for r in self.sel(**kw))

    def sig(self, **kw):
        rows = self.sel(**kw)
        if not rows:
            return None
        return hashlib.sha256("\n".join(f"{r['para']}|{r['item']}|{r['text']}" for r in rows).encode("utf-8")).hexdigest()[:12]

    def changed_paras(self, other, **kw):
        a = {(r["para"], r["item"]): r["text"] for r in self.sel(**kw)}
        b = {(r["para"], r["item"]): r["text"] for r in other.sel(**kw)}
        keys = set(a) | set(b)
        return sorted({k[0] for k in keys if a.get(k) != b.get(k)}, key=lambda x: (len(x), x))

    def search(self, s):
        return [r for r in self.rows if s in r["text"]]


def cmd_check():
    tdir = latest_dir("egov")
    wdir = latest_dir("web")
    L = {}
    for p in tdir.glob("*.tsv"):
        short, asof = p.stem.rsplit("_", 1)
        L[(short, asof)] = Law(p)
    flog = json.loads((OUT / "egov_fetch_log.json").read_text(encoding="utf-8"))
    FE = {(f["short"], f["asof"]): f for f in flog["fetches"]}
    wlog = json.loads((OUT / "web_fetch_log.json").read_text(encoding="utf-8"))
    WP = {p["id"]: p for p in wlog["pages"]}
    W = {p.stem: p.read_text(encoding="utf-8") for p in wdir.glob("*.txt")}
    xlog = json.loads((OUT / "egov_extra_log.json").read_text(encoding="utf-8"))
    checks = []

    def ck(cid, doc, claim, ok, detail=None):
        checks.append({"id": cid, "doc": doc, "claim": claim, "ok": bool(ok), "detail": detail})

    def has(key, needles, **kw):
        t = L[key].text(**kw)
        miss = [n for n in needles if n not in t]
        return not miss, ({"missing": miss} if miss else None)

    def wnorm(t):
        return re.sub(r"\s+", "", t)

    def whas(pid, needles):
        t = wnorm(W.get(pid, ""))
        miss = [n for n in needles if wnorm(n) not in t]
        return not miss, ({"missing": miss} if miss else None)

    MF, PL, PN, HY, IN, MC = ("M-HKF", "PS-HKL", "PS-HKN", "H", "C", "M-HKC")

    # ---- 1. 版（law_revision_id・状態・生データの SHA-256 先頭16桁）：M-HKF §1、PS-HKL §0 ----
    EXP = [
        ("shotoku", "2024-12-31", "340AC0000000033_20240612_506AC0000000047", "PreviousEnforced", "9af089a685c8f0ca"),
        ("shotoku", "2025-12-31", "340AC0000000033_20251218_507AC0000000013", "PreviousEnforced", "84a2235cb4437184"),
        ("shotoku", "2026-03-31", "340AC0000000033_20260101_507AC0000000013", "PreviousEnforced", "82aa4ab37e1bfd1e"),
        ("shotoku", "2026-04-01", "340AC0000000033_20260401_508AC0000000012", "PreviousEnforced", "71d18be7c42df610"),
        ("shotoku", "2026-12-31", "340AC0000000033_20261201_508AC0000000012", "UnEnforced", "47792299f0fb5a74"),
        ("shotoku", "2027-01-01", "340AC0000000033_20270101_508AC0000000012", "UnEnforced", "d4bf435220bc0b0c"),
        ("shotoku-rei", "2025-12-31", "340CO0000000096_20251201_507CO0000000120", "PreviousEnforced", "e972344f436ecd9b"),
        ("shotoku-rei", "2026-12-31", "340CO0000000096_20261201_508CO0000000093", "UnEnforced", "cd63914bb5962edf"),
        ("shotoku-rei", "2027-01-01", "340CO0000000096_20270101_508CO0000000093", "UnEnforced", "f4965711894ea1c7"),
        ("shotoku-ki", "2025-12-31", "340M50000040011_20251201_507M60000040018", "PreviousEnforced", "16358c775e2d1dcc"),
        ("shotoku-ki", "2026-12-31", "340M50000040011_20261211_508M60000040017", "UnEnforced", "9ba37bf34afed1f9"),
        ("shotoku-ki", "2027-01-01", "340M50000040011_20270101_508M60000040017", "UnEnforced", "1600117df38c4463"),
        ("sochi", "2025-12-31", "332AC0000000026_20251231_507AC1000000081", "PreviousEnforced", "ef95d90f7bf57e18"),
        ("sochi", "2026-01-01", "332AC0000000026_20260101_507AC0000000041", "PreviousEnforced", "fc120ad551878b61"),
        ("sochi", "2026-03-31", "332AC0000000026_20260101_507AC0000000041", "PreviousEnforced", "fc120ad551878b61"),
        ("sochi", "2026-04-01", "332AC0000000026_20260401_508AC0000000012", "PreviousEnforced", "d7499813f8851511"),
        ("sochi", "2026-11-09", "332AC0000000026_20261101_507AC0000000013", "CurrentEnforced", "e6e6013bbc0608c6"),
        ("sochi", "2026-12-31", "332AC0000000026_20261204_508AC0000000012", "UnEnforced", "763fce2df2b1e709"),
        ("sochi", "2027-01-01", "332AC0000000026_20270101_508AC0000000012", "UnEnforced", "8c6ee577201c3be0"),
        ("chiho", "2025-12-31", "325AC0000000226_20251212_507AC0000000087", "PreviousEnforced", "0deae64106b42fdb"),
        ("chiho", "2026-01-01", "325AC0000000226_20260101_507AC0000000041", "PreviousEnforced", "ba0a40e550be7762"),
        ("chiho", "2026-03-31", "325AC0000000226_20260101_507AC0000000041", "PreviousEnforced", "ba0a40e550be7762"),
        ("chiho", "2026-04-01", "325AC0000000226_20260401_508AC0000000002", "PreviousEnforced", "06db2ba6ccfec62e"),
        ("chiho", "2026-11-09", "325AC0000000226_20261101_508AC0000000002", "CurrentEnforced", "3dd29e0078bf24e0"),
        ("chiho", "2027-01-01", "325AC0000000226_20270101_508AC0000000002", "UnEnforced", "ee21722ce5fd1561"),
        ("chiho-rei", "2026-11-09", "325CO0000000245_20261101_508CO0000000083", "CurrentEnforced", "9bc03b230fb0ed10"),
        ("chiho-rei", "2027-01-01", "325CO0000000245_20270101_508CO0000000083", "UnEnforced", "962bfc48e43c49b4"),
    ]
    for short, asof, rid, st, sha in EXP:
        f = FE[(short, asof)]
        ok = f.get("law_revision_id") == rid and f.get("current_revision_status") == st and f["sha256"][:16] == sha
        ck(f"ver_{short}_{asof}", MF + " §1", f"{short} asof={asof}: {rid} {st} sha={sha}", ok,
           None if ok else {"got": [f.get("law_revision_id"), f.get("current_revision_status"), f["sha256"][:16]]})
    REVN = {"shotoku": 29, "shotoku-rei": 16, "sochi": 44, "chiho": 67}
    for short, n in REVN.items():
        d = json.loads((OUT / f"egov_revisions_{short}.json").read_text(encoding="utf-8"))
        ck(f"revcount_{short}", MF + " §1", f"改正履歴（2025-01-01 以後）{short} {n}件", d["n"] == n, {"got": d["n"]})
    d = json.loads((OUT / "egov_revisions_shotoku.json").read_text(encoding="utf-8"))
    r = [x for x in d["revisions"] if x["law_revision_id"] == "340AC0000000033_20260401_506AC0000000008"]
    ck("rev_r6_8", MF + " §1・" + PL + " §9", "所法の改正 340AC0000000033_20260401_506AC0000000008（令和六年法律第八号、施行 2026-04-01）",
       bool(r) and r[0]["amendment_law_num"] == "令和六年法律第八号" and r[0]["amendment_enforcement_date"] == "2026-04-01", r)
    kr = [q for q in xlog["requests"] if q["name"] == "koeki_revisions"][0]
    ok = any(x["law_revision_id"].startswith("506AC0000000030_20260401") and x["amendment_enforcement_date"] == "2026-04-01" for x in kr.get("revisions", []))
    ck("koeki_shiko", PL + " §1・§9", "公益信託に関する法律（令和6年法律第30号）の施行日 2026-04-01（e-Gov の同法の改正履歴に、施行 2026-04-01 の版がある）", ok)

    # ---- 2. 条の本文が版の間で同じか・違うか：M-HKF §2 ----
    def same_all(short, asofs, **kw):
        sigs = [L[(short, a)].sig(**kw) for a in asofs]
        return all(s is not None for s in sigs) and len(set(sigs)) == 1, sigs

    SH = ["2024-12-31", "2025-12-31", "2026-03-31", "2026-04-01", "2026-12-31", "2027-01-01"]
    for art in ("72", "75", "76", "77"):
        ok, sg = same_all("shotoku", SH, art=art)
        ck(f"same_shotoku_{art}", MF + " §2・" + PL + " §1", f"所法第{art}条は 2024-12-31〜2027-01-01 の版で同文", ok, sg)
    ok, sg = same_all("shotoku", SH, part="S", amend="平成一八年三月三一日法律第一〇号", art="10")
    ck("same_h18_10_10", MF + " §2", "平成18年法律第10号附則第10条は同文", ok, sg)
    ch = L[("shotoku", "2026-03-31")].sig(art="78") != L[("shotoku", "2026-04-01")].sig(art="78") and \
        L[("shotoku", "2025-12-31")].sig(art="78") == L[("shotoku", "2026-03-31")].sig(art="78")
    ck("chg_shotoku_78", MF + " §2・§3.2", "所法第78条は 2026-03-31 と 2026-04-01 の間で変わる", ch)
    a87 = L[("shotoku", "2024-12-31")].text(art="87", para="1"); b87 = L[("shotoku", "2025-12-31")].text(art="87", para="1")
    ck("chg_shotoku_87", MF + " §2", "所法第87条は 2024-12-31→2025-12-31 で「特定親族特別控除」が加わる", "特定親族特別控除" not in a87 and "特定親族特別控除" in b87)
    for art in ["206", "208_2", "208_3", "208_4", "208_5", "208_6", "208_7", "208_8", "209", "210", "210_2", "211", "212", "213",
                "214", "215", "216", "217", "262"]:
        ok, sg = same_all("shotoku-rei", ["2025-12-31", "2026-12-31", "2027-01-01"], art=art)
        ck(f"same_rei_{art}", MF + " §2・" + PL + " §2.2", f"所令第{art}条は3つの版で同文", ok, sg)
    ok = "五十八万円以下" in L[("shotoku-rei", "2025-12-31")].text(art="205", para="1") and \
        "六十二万円以下" in L[("shotoku-rei", "2026-12-31")].text(art="205", para="1")
    ck("rei205_amount", MF + " §2・§3.4・" + PL + " §1・§6", "所令第205条第1項：58万円以下（2025-12-31）→62万円以下（2026-12-31）", ok)
    k25, k26, k27 = L[("shotoku-ki", "2025-12-31")], L[("shotoku-ki", "2026-12-31")], L[("shotoku-ki", "2027-01-01")]
    cp1 = k25.changed_paras(k26, art="47_2"); cp2 = k26.changed_paras(k27, art="47_2")
    ck("ki47_2_paras_r8", MF + " §2", "所規第47条の2：2025-12-31→2026-12-31 で変わるのは第3項（公益信託）だけ", cp1 == ["3"], {"changed_paras": cp1})
    ck("ki47_2_paras_r9", MF + " §2", "所規第47条の2：2026-12-31→2027-01-01 で第14項が加わる", "14" in cp2 and "法第百二十条第六項" in k27.text(art="47_2", para="14"), {"changed_paras": cp2})
    ck("sochi_41_15_5_absent", MF + " §2・" + PL + " §1", "措法第41条の15の5 は 2025-12-31 の版にない", L[("sochi", "2025-12-31")].sig(art="41_15_5") is None)
    ok, sg = same_all("sochi", ["2026-04-01", "2026-11-09", "2026-12-31", "2027-01-01"], art="41_15_5")
    ck("sochi_41_15_5_same", MF + " §2・§3.1", "措法第41条の15の5 は 2026-04-01 以後の版で同文", ok, sg)
    ok, sg = same_all("sochi", ["2026-01-01", "2026-03-31"], art="41_15_5")
    ck("sochi_41_15_5_same0", MF + " §3.1", "措法第41条の15の5 は 2026-01-01・2026-03-31 で同文（当初の文言）", ok, sg)
    for art in ("41_18", "41_18_2", "41_18_3"):
        ck(f"chg_sochi_{art}", MF + " §2", f"措法第{art} は 2025-12-31→2026-11-09 で変わる",
           L[("sochi", "2025-12-31")].sig(art=art) != L[("sochi", "2026-11-09")].sig(art=art))
    s25, s0101, s0401 = L[("sochi", "2025-12-31")], L[("sochi", "2026-01-01")], L[("sochi", "2026-04-01")]
    only_koeki = ("特定政党支部" not in s0101.text(art="41_18", para="1")) and ("学生に対する修学" not in s0401.text(art="41_18_3"))
    ck("sochi_41_18_nature", MF + " §2", "措法第41条の18〜第41条の18の3 の変更は「公益信託関係の文言」だけ", only_koeki,
       {"41_18①（2026-01-01 から）": "公職の候補者が自らが代表者の特定政党支部にする寄附を除く文言が加わる" if "特定政党支部" in s0101.text(art="41_18", para="1") and "特定政党支部" not in s25.text(art="41_18", para="1") else None,
        "41_18②・41_18_2②・41_18_3①（2026-04-01 から）": "所法78③（特定公益信託）の引用の削除" if "同条第三項の規定又は" in s25.text(art="41_18", para="2") and "同条第三項の規定又は" not in s0401.text(art="41_18", para="2") else None,
        "41_18_3①二（2026-04-01 から）": "「学生等に対する修学の支援」→「学生に対する修学の支援」" if "学生等に対する修学" in s25.text(art="41_18_3") and "学生に対する修学" in s0401.text(art="41_18_3") else None})
    caps = {a: s0401.sel(art=a)[0]["cap"] for a in ("41_18", "41_18_2", "41_18_3")}
    ck("sochi_41_18_caps", PL + " §4", "措法41の18・41の18の2・41の18の3 はいずれも「寄附金控除の特例又は所得税額の特別控除」を定める",
       all("寄附金控除の特例又は所得税額の特別控除" in c for c in caps.values()), caps)
    sr = [q for q in xlog["requests"] if q["name"] == "sochirei"][0]
    sk = [q for q in xlog["requests"] if q["name"] == "sochiki"][0]
    ck("sochirei_41_15_5", PL + " §9・" + HY + " H3", "措令（asof 2026-11-09）に措法41の15の5 を引く規定はなく、措規は第19条の10（保険料控除申告書の記載事項）だけ（扶養親族の所属を定める規定は見つからない）",
       sr["status"] == 200 and not sr["hits_41_15_5"] and sk["status"] == 200 and {h["art"] for h in sk["hits_41_15_5"]} == {"19_10"},
       {"措令": sr.get("law_revision_id"), "措規": sk.get("law_revision_id"), "措規の該当": sorted({h["art"] for h in sk["hits_41_15_5"]})})
    # M-HKF §2 の表の SHA-256（先頭8桁）が、担当自身の記録（scripts/results/R2X_hoken-kifu_egov/article_hashes.json）と一致するか（記録の転記の確認）
    ah = json.loads((ROOT / "scripts" / "results" / "R2X_hoken-kifu_egov" / "article_hashes.json").read_text(encoding="utf-8"))["hashes"]
    CLAIMED = [("shotoku", "本則:72", "2024-12-31", "28757bf4"), ("shotoku", "本則:75", "2027-01-01", "fb4173da"), ("shotoku", "本則:76", "2025-12-31", "523e7659"),
               ("shotoku", "本則:77", "2026-12-31", "72189ef8"), ("shotoku", "本則:78", "2025-12-31", "2ed763fa"), ("shotoku", "本則:78", "2026-12-31", "7c05f83d"),
               ("shotoku", "本則:87", "2024-12-31", "295c550b"), ("shotoku", "本則:87", "2025-12-31", "c6974d98"),
               ("shotoku", "附則[平成一八年三月三一日法律第一〇号]:10", "2027-01-01", "31098fef"), ("shotoku-rei", "本則:205", "2025-12-31", "d9ab6e76"),
               ("shotoku-rei", "本則:205", "2026-12-31", "868f5d09"), ("shotoku-ki", "本則:47_2", "2025-12-31", "c42de55b"), ("shotoku-ki", "本則:47_2", "2026-12-31", "8e4fa13c"),
               ("shotoku-ki", "本則:47_2", "2027-01-01", "b2160a50"), ("sochi", "本則:41_15_5", "2026-11-09", "fcb10043"), ("chiho", "本則:314_2", "2025-12-31", "127a1d6c"),
               ("chiho", "本則:314_2", "2026-11-09", "9b9b6398"), ("chiho", "本則:314_2", "2027-01-01", "4ea7f2b3"), ("chiho", "本則:314_7", "2025-12-31", "c9159b48"),
               ("chiho", "本則:314_7", "2026-11-09", "df6419da"), ("chiho", "本則:314_7", "2027-01-01", "98e6b4f6"), ("chiho", "本則:37_2", "2025-12-31", "7ed74e50"),
               ("chiho", "本則:37_2", "2026-11-09", "ff655fe2"), ("chiho", "本則:37_2", "2027-01-01", "9f3ac92b"), ("chiho", "附則[(原始附則)]:5_5", "2026-11-09", "fddd44ef"),
               ("chiho", "附則[(原始附則)]:5_5", "2027-01-01", "9cfc7080")]
    bad = [c for c in CLAIMED if (ah.get(c[0], {}).get(c[1], {}).get(c[2]) or "")[:8] != c[3]]
    ck("mhkf_hash_transcription", MF + " §2", f"§2 の表の SHA-256（先頭8桁、{len(CLAIMED)}件）は担当の article_hashes.json と一致（転記の確認。値そのものは担当のテキスト化に依存）", not bad, bad)
    c25, c26a, c26b, c27 = L[("chiho", "2025-12-31")], L[("chiho", "2026-04-01")], L[("chiho", "2026-11-09")], L[("chiho", "2027-01-01")]
    c0101, c0331 = L[("chiho", "2026-01-01")], L[("chiho", "2026-03-31")]
    ok = all(c25.text(art="314_2", para="1", item=i) == c26b.text(art="314_2", para="1", item=i) == c27.text(art="314_2", para="1", item=i)
             for i in ("1", "2", "3", "4", "5", "5_2", "5_3"))
    ck("chiho314_2_items_same", MF + " §2・" + PL + " §1・§7", "地法第314条の2第1項第1号〜第5号の3 は 3つの版で同文", ok)
    a = {(r["para"], r["item"]): r["text"] for r in c25.sel(art="314_2")}
    b = {(r["para"], r["item"]): r["text"] for r in c26b.sel(art="314_2")}
    diffkeys = sorted({(k[0], k[1].split("-")[0]) for k in set(a) | set(b) if a.get(k) != b.get(k)})
    exp = {("1", "10_2"), ("1", "11"), ("1", "12"), ("6", ""), ("8", ""), ("10", ""), ("11", "")}
    ck("chiho314_2_diff_r8", MF + " §2", "地法第314条の2 の 2025-12-31→2026-11-09 の差分は第1項第10号の2・第11号・第12号・第6項・第8項・第10項・第11項だけ",
       set(diffkeys) == exp, {"diff": diffkeys})
    a = {(r["para"], r["item"]): r["text"] for r in c26b.sel(art="314_2")}
    b = {(r["para"], r["item"]): r["text"] for r in c27.sel(art="314_2")}
    diffkeys = sorted({(k[0], k[1].split("-")[0]) for k in set(a) | set(b) if a.get(k) != b.get(k)})
    ck("chiho314_2_diff_r9", MF + " §2", "地法第314条の2 の 2026-11-09→2027-01-01 の差分は第1項第6号だけ", diffkeys == [("1", "6")], {"diff": diffkeys})
    for art in ("314_7", "37_2"):
        ck(f"chg_chiho_{art}", MF + " §2", f"地法第{art} は 2025-12-31・2026-11-09・2027-01-01 で互いに違う",
           len({c25.sig(art=art), c26b.sig(art=art), c27.sig(art=art)}) == 3)
    ck("chiho_suppl_5_5", MF + " §2", "地法原始附則第5条の5 は 2025-12-31=2026-11-09、2027-01-01 で変わる",
       c25.sig(part="S", amend="orig", art="5_5") == c26b.sig(part="S", amend="orig", art="5_5") != c27.sig(part="S", amend="orig", art="5_5"))
    for art in ("5_7", "7", "5_6", "7_3"):
        ok, sg = same_all("chiho", ["2025-12-31", "2026-04-01", "2026-11-09", "2027-01-01"], part="S", amend="orig", art=art)
        ck(f"chiho_suppl_same_{art}", MF + " §2・" + PL + " §8.3", f"地法原始附則第{art} は 2025-12-31〜2027-01-01 で同文", ok, sg)
    for art in ("5", "11"):
        ok, sg = same_all("chiho", ["2025-12-31", "2026-11-09", "2027-01-01"], part="S", amend="平成一八年三月三一日法律第七号", art=art)
        ck(f"chiho_h18_7_{art}", MF + " §2", f"平成18年法律第7号附則第{art}条は3つの版で同文", ok, sg)
    hits = {}
    for asof in ("2025-12-31", "2026-11-09", "2027-01-01"):
        hits[asof] = (sorted({(r["part"], r["art"]) for r in L[("chiho", asof)].search("二十三歳未満")}), len(L[("chiho", asof)].search("四十一条の十五の五")))
    ok = all(v[0] == [("M", "314_2"), ("M", "34")] and v[1] == 0 for v in hits.values())
    ck("chiho_kw_23", MF + " §2・" + PL + " §1", "地法で「二十三歳未満」を含むのは第34条と第314条の2 だけ、「四十一条の十五の五」は0件", ok, hits)

    # ---- 3. 措法第41条の15の5 の文言と施行：M-HKF §3.1、PS-HKL §1・§2.3、H3・H12 ----
    ok, det = has(("sochi", "2026-01-01"), ["令和八年分の同法第七十六条第十一項", "「各年」とあるのは「令和八年」", "令和八年十二月三十一日"], art="41_15_5")
    ck("s41155_orig", MF + " §3.1・" + PL + " §2.3", "当初の文言は「令和八年分」、判定日「令和八年十二月三十一日」", ok, det)
    ok, det = has(("sochi", "2026-04-01"), ["令和八年分又は令和九年分", "「令和八年又は令和九年」", "その年十二月三十一日",
                                            "所得税法第二条第一項第三十四号に規定する扶養親族",
                                            "同項第一号イ中「二万円」とあるのは「三万円」", "同号ロ中「二万円」とあるのは「三万円」と、「四万円」とあるのは「六万円」",
                                            "同号ハ中「四万円」とあるのは「六万円」と、「八万円」とあるのは「十二万円」と、「三万円」とあるのは「四万五千円」",
                                            "同号ニ中「八万円」とあるのは「十二万円」と、「四万円」とあるのは「六万円」",
                                            "同項第三号中「四万円」とあるのは「六万円」", "その死亡の時の現況による"], art="41_15_5")
    ck("s41155_r8", MF + " §3.1・" + PL + " §2.3・" + HY + " H3", "2026-04-01 以後の文言（令和8年分又は令和9年分、読替え、12月31日判定）", ok, det)
    t3 = L[("sochi", "2026-04-01")].text(art="41_15_5", para="3")
    ck("s41155_p3", PL + " §2.3", "第3項は所法190二ロ・196①・196①三・198④ を読み替える",
       all(x in t3 for x in ("第百九十条第二号ロ", "第百九十六条第一項", "第百九十六条第一項第三号", "第百九十八条第四項")))
    t = L[("sochi", "2026-11-09")].text(part="S", amend="令和七年三月三一日法律第一三号", art="1", para="1", item="2")
    ck("r7_13_s1_2", MF + " §3.1・" + PL + " §1", "令和7年法律第13号附則第1条第2号（令和八年一月一日）ロに「同法第四十一条の十五の四の次に一条を加える改正規定」",
       "令和八年一月一日" in t and "同法第四十一条の十五の四の次に一条を加える改正規定" in L[("sochi", "2026-11-09")].text(part="S", amend="令和七年三月三一日法律第一三号", art="1", para="1", item="2-2"))
    n = len([r for r in L[("sochi", "2026-11-09")].rows if r["part"] == "S" and "四十一条の十五の五" in r["text"]])
    ck("s41155_suppl_none", MF + " §3.1", "措法の附則（改正附則を含む）に「四十一条の十五の五」を含む規定はない（asof 2026-11-09）", n == 0, {"hits": n})
    t = L[("shotoku-ki", "2026-01-01")].text(art="47", para="3", item="24")
    ck("ki47_3_24", PL + " §2.3", "所規第47条第3項第24号（扶養親族の氏名・生年月日・続柄・個人番号）は 2026-01-01 の版から",
       "四十一条の十五の五" in t and all(x in t for x in ("氏名", "生年月日", "続柄", "個人番号")) and
       "四十一条の十五の五" not in L[("shotoku-ki", "2025-12-31")].text(art="47", para="3", item="24"))

    # ---- 4. 所法第76条・第75条・第77条・第72条・第78条の文言：PS-HKL §2〜§6 ----
    s = ("shotoku", "2025-12-31")
    for cid, kw, needles in [
        ("76_1_1", dict(art="76", para="1", item="1"), ["二万円以下である場合　当該合計額", "二万円を超え四万円以下である場合　二万円と当該合計額から二万円を控除した金額の二分の一",
                                                        "四万円を超え八万円以下である場合　三万円と当該合計額から四万円を控除した金額の四分の一", "八万円を超える場合　四万円"]),
        ("76_1_2", dict(art="76", para="1", item="2"), ["二万五千円以下である場合　当該合計額", "二万五千円を超え五万円以下である場合　二万五千円と当該合計額から二万五千円を控除した金額の二分の一",
                                                        "五万円を超え十万円以下である場合　三万七千五百円と当該合計額から五万円を控除した金額の四分の一", "十万円を超える場合　五万円"]),
        ("76_1_3", dict(art="76", para="1", item="3"), ["当該合計額が四万円を超える場合には、四万円"]),
        ("76_2", dict(art="76", para="2"), ["二万円以下である場合　当該合計額", "八万円を超える場合　四万円"]),
        ("76_3", dict(art="76", para="3"), ["八万円を超える場合　四万円", "十万円を超える場合　五万円", "当該合計額が四万円を超える場合には、四万円"]),
        ("76_4", dict(art="76", para="4"), ["十二万円を超える場合", "十二万円とする"]),
        ("76_5", dict(art="76", para="5"), ["平成二十四年一月一日以後に締結", "保険金等の受取人のすべてをその保険料若しくは掛金の払込みをする者又はその配偶者その他の親族とするもの", "保険期間が五年に満たない保険契約で政令で定めるもの"]),
        ("76_6", dict(art="76", para="6"), ["平成二十三年十二月三十一日以前に締結", "医療費等支払事由に基因して保険金等が支払われるもの"]),
        ("76_8", dict(art="76", para="8"), ["年金支払開始日前十年以上の期間にわたつて定期に行う", "年齢が六十歳に達した日以後", "十年以上の期間又は当該受取人が生存している期間"]),
        ("76_10", dict(art="76", para="10"), ["平成二十四年一月一日以後に", "附帯して", "同日以後に締結した契約とみなして"]),
        ("76_11", dict(art="76", para="11"), ["生命保険料控除という"]),
        ("75_1", dict(art="75", para="1"), ["その支払つた金額を"]),
        ("75_2", dict(art="75", para="2"), ["小規模企業共済法", "企業型年金加入者掛金", "個人型年金加入者掛金", "第九条第一項第三号ハ"]),
        ("77_1", dict(art="77", para="1"), ["自己若しくは自己と生計を一にする配偶者その他の親族の有する家屋で常時その居住の用に供するもの", "第九条第一項第九号", "五万円を超える場合には五万円"]),
        ("77_2", dict(art="77", para="2"), ["附帯して締結されるもの又は当該契約と一体となつて効力を有する", "建物更生共済又は火災共済"]),
        ("72_1", dict(art="72", para="1"), ["生計を一にする配偶者その他の親族で政令で定めるもの", "第六十二条第一項", "第七十条第三項", "災害又は盗難若しくは横領",
                                            "五万円以下である場合", "十分の一に相当する金額", "五万円を超える部分の金額を控除した金額と前号に掲げる金額とのいずれか低い金額",
                                            "すべて災害関連支出の金額である場合　五万円と第一号に掲げる金額とのいずれか低い金額"]),
    ]:
        ok, det = has(s, needles, **kw)
        ck("text_" + cid, PL + " §2〜§6", f"所法の文言 {cid}", ok, det)
    ok, det = has(("shotoku", "2026-03-31"), ["百分の四十", "二千円", "学校の入学に関してするもの", "特別の利益", "特定公益信託"], art="78")
    ck("text_78_old", PL + " §4", "所法78（2026-03-31）：40/100・2千円・入学・特別の利益・旧第3項の特定公益信託", ok, det)
    ok, det = has(("shotoku", "2026-04-01"), ["公益信託の信託財産とするために支出した当該公益信託に係る信託事務に関連する寄附金（出資に関する信託事務に充てられることが明らかなもの及び前三号に規定する寄附金に該当するものを除く。）"], art="78", para="2", item="4")
    ck("text_78_new", PL + " §4・" + MF + " §3.2", "所法78②四（2026-04-01）", ok and "特定公益信託" not in L[("shotoku", "2026-04-01")].text(art="78"), det)
    t1 = L[("shotoku", "2026-04-01")].text(part="S", amend="令和六年三月三〇日法律第八号", art="1", para="1", item="9")
    t3 = L[("shotoku", "2026-04-01")].text(part="S", amend="令和六年三月三〇日法律第八号", art="3", para="1")
    ck("r6_8_suppl", MF + " §3.2・" + PL + " §1", "令和6年法律第8号附則第1条第9号（公益信託に関する法律の施行の日）イに所法78の改正規定、第3条第1項の経過措置",
       "公益信託に関する法律（令和六年法律第三十号）の施行の日" in t1 and "同法第七十八条の改正規定" in t1 and "移行認可を受けたものを除く" in t3 and "なおその効力を有する" in t3)
    r = L[("shotoku-rei", "2026-12-31")]
    ck("rei205_2", PL + " §6・" + HY + " H10", "所令205②：扶養等の居住者、配偶者は夫又は妻、その他は総所得金額等が最も大きい居住者",
       all(x in r.text(art="205", para="2") for x in ("自己の同一生計配偶者又は扶養親族としている居住者の親族", "その夫又は妻である居住者の親族", "最も大きい居住者の親族")))
    t = r.text(art="206")
    ck("rei206", PL + " §6", "所令206：①一〜四、②は第1号〜第3号、③直前の価額、1年（3年）",
       all(x in t for x in ("一年を経過した日", "三年を経過した日", "盗難又は横領による損失が生じた住宅家財等の原状回復", "前項第一号から第三号までに掲げる支出の金額", "直前におけるその資産の価額")))
    ck("rei208_2", PL + " §5", "所令208の2：旧第二種共済契約", "旧第二種共済契約" in r.text(art="208_2"))
    ck("rei209", PL + " §2.2", "所令209：保険期間5年未満の保険契約（見出し「生命保険料控除の対象とならない保険契約等」）",
       "保険期間が五年に満たない" in r.text(art="209") and r.sel(art="209")[0]["cap"] == "（生命保険料控除の対象とならない保険契約等）")
    ck("rei217_koeki", PL + " §4（訂正後の文言）", "所令217第3号：公益社団法人及び公益財団法人（所法78②三の特定公益増進法人）", "公益社団法人及び公益財団法人" in r.text(art="217", para="1", item="3"))
    ck("rei212", PL + " §2.2", "所令212：法76⑧三の政令で定める要件", "法第七十六条第八項第三号" in r.text(art="212"))
    ck("rei219", HY + " H3", "所令219：二以上の居住者がある場合の扶養親族及び特定親族の所属（法85⑥）",
       "法第八十五条第六項" in r.text(art="219") and "所属" in r.sel(art="219")[0]["cap"])
    t = r.text(art="262", para="1", item="4")
    ck("rei262_1_4", PL + " §2.4", "所令262①四：旧生命保険料は9千円を超える旧生命保険契約等に係るものに限る", "九千円を超える法第七十六条第六項に規定する旧生命保険契約等" in t)
    ck("rei262_1_5", PL + " §3", "所令262①五：地震保険料（金額の例外なし）", "地震保険料の金額" in r.text(art="262", para="1", item="5") and "九千円" not in r.text(art="262", para="1", item="5"))
    ck("rei262_1_1", PL + " §6", "所令262①一：やむを得ない支出の領収を証する書類", "やむを得ない支出をした金額につきこれを領収した者のその領収を証する書類" in r.text(art="262", para="1", item="1"))
    ck("rei262_1_3_6", PL + " §4・§5", "所令262①三（小規模企業共済等掛金の額）・六（特定寄附金の明細書その他）",
       "小規模企業共済等掛金の額を証する書類" in r.text(art="262", para="1", item="3") and "特定寄附金の明細書その他財務省令で定める書類" in r.text(art="262", para="1", item="6"))
    t = k26.text(art="47_2", para="1")
    ck("ki47_2_1", PL + " §2.4", "所規47の2①：保険契約者の氏名・該当する旨、個人年金は年金受取人の氏名・生年月日・支払開始日・支払期間・払込期間",
       all(x in t for x in ("保険契約者若しくは共済契約者の氏名", "年金受取人の氏名及び生年月日", "支払開始日及び支払期間")))
    ck("ki47_2_2", PL + " §3", "所規47の2②：保険契約者の氏名、保険又は共済の種類及びその目的", "保険又は共済の種類及びその目的" in k26.text(art="47_2", para="2"))
    t = k26.text(art="47_2", para="3")
    ck("ki47_2_3", PL + " §4", "所規47の2③：受領した旨・額・年月日、公益信託の受託者、特定事業者（国税庁長官が指定）",
       all(x in t for x in ("受領した旨", "受領した年月日", "公益信託の受託者", "特定事業者（地方公共団体と特定寄附金の仲介に関する契約を締結している者", "国税庁長官が指定したもの")))
    t = L[("shotoku", "2027-01-01")].text(art="120", para="6")
    ck("shotoku120_6", PL + " §2.4", "所法120⑥（2027-01-01 の版）：明細書の添付で証明書類に代えられる", "明細書を当該申告書に添付することができる" in t and "生命保険料控除" in t)
    t = L[("shotoku", "2027-01-01")].text(part="S", amend="令和八年三月三一日法律第一二号", art="10", para="1")
    ck("shotoku120_6_app", PL + " §2.4", "令和8年法律第12号附則第10条第1項：令和9年1月1日以後に令和8年分以後の確定申告書を提出する場合に適用", "令和九年一月一日以後に令和八年分以後" in t)
    t = L[("shotoku", "2026-04-01")].text(art="2", para="1", item="37")
    ck("shotoku2_1_37", PL + " §8.3", "所法2①三十七：第二編第五章第二節第一款及び第二款の申告書（期限後申告書を含む）", "第二編第五章第二節第一款及び第二款" in t and "期限後申告書" in t)
    st = {a: L[("shotoku", "2026-04-01")].sel(art=a)[0]["struct"] for a in ("120", "121", "122", "123", "124", "125", "126", "127")}
    ok = all(st[a].endswith("第一款　確定申告") for a in ("120", "121", "122", "123")) and all(st[a].endswith("第二款　死亡又は出国の場合の確定申告") for a in ("124", "125", "126", "127"))
    ck("shotoku_120_127", MF + " §3.5・" + PL + " §8.3", "所法120〜123 は第一款、124〜127 は第二款", ok, st)
    n1 = len(L[("shotoku", "2026-04-01")].search("一円未満")); n2 = [(x["art"], x["para"]) for x in L[("shotoku-rei", "2026-12-31")].search("一円未満")]
    ck("ichienmiman", MF + " §3.5", "「一円未満」：所法（2026-04-01）0件、所令（2026-12-31）は第319条の7第2項の1件だけ", n1 == 0 and n2 == [("319_7", "2")], {"shotoku": n1, "rei": n2})
    t = L[("shotoku", "2026-12-31")].text(art="85", para="6")
    ck("shotoku85_6", PL + " §9", "所法85⑥の文言", "いずれか一の居住者の扶養親族又は特定親族にのみ該当するものとみなす" in t)
    ck("shotoku2_34", HY + " H3", "所法2①三十四：扶養親族の合計所得金額 58万円以下（2025-12-31）／62万円以下（2026-12-31）",
       "五十八万円以下" in L[("shotoku", "2025-12-31")].text(art="2", para="1", item="34") and "六十二万円以下" in L[("shotoku", "2026-12-31")].text(art="2", para="1", item="34"))
    ck("shotoku84_2", HY + " H3", "特定親族：合計所得金額 123万円以下で控除対象扶養親族に該当しない19歳以上23歳未満の親族（令和8年分の版も同じ）",
       all("百二十三万円以下" in L[("shotoku", a)].text(art="84_2", para="1") and "十九歳以上二十三歳未満" in L[("shotoku", a)].text(art="84_2", para="1") for a in ("2025-12-31", "2026-12-31")))
    ok = "百三十二万円以下である場合　三十七万円" in L[("sochi", "2025-12-31")].text(art="41_16_2", para="1") and \
        "五十八万円" in L[("shotoku", "2025-12-31")].text(art="86", para="1", item="1") and \
        "四百八十九万円以下である場合　四十二万円" in L[("sochi", "2026-12-31")].text(art="41_16_2", para="1") and \
        "六十二万円" in L[("shotoku", "2026-12-31")].text(art="86", para="1", item="1")
    ck("kiso_kojo", HY + " H7・" + IN + " C6", "基礎控除：令和7年分 58万＋37万＝95万（合計所得132万円以下）、令和8年分 62万＋42万＝104万（489万円以下）", ok)
    t = L[("shotoku", "2025-12-31")].text(part="S", amend="平成一八年三月三一日法律第一〇号", art="10")
    ck("h18_10_10_text", PL + " §3", "平18法10附則10②：10年以上・平成19年1月1日以後に変更していない・1万円以下／1万5千円／5万円、③一の契約は一方",
       all(x in t for x in ("平成十八年十二月三十一日までに締結", "十年以上", "平成十九年一月一日以後に当該損害保険契約等の変更をしていない", "一万円以下である場合　当該合計額",
                            "一万円と当該合計額から一万円を控除した金額の二分の一", "二万円を超える場合　一万五千円", "いずれか一の契約のみに該当するものとして")))

    # ---- 5. 所令・地令の改正附則：M-HKF §3.4、PS-HKL §1 ----
    r = L[("shotoku-rei", "2026-12-31")]
    A120 = "令和七年三月三一日政令第一二〇号"; A93 = "令和八年三月三一日政令第九三号"
    ck("r7_120_s1", MF + " §3.4", "令和7年政令第120号附則第1条第1号（令和七年十二月一日）イに第205条第1項の改正規定",
       "令和七年十二月一日" in r.text(part="S", amend=A120, art="1", para="1", item="1").split("\n")[0] and
       "同令第二百五条第一項の改正規定" in r.text(part="S", amend=A120, art="1", para="1", item="1-1"))
    ck("r7_120_s10_1", MF + " §3.4・" + PL + " §1", "同附則第10条第1項：令和7年分以後", "令和七年分以後の所得税" in r.text(part="S", amend=A120, art="10", para="1"))
    t = r.text(part="S", amend=A120, art="10", para="2")
    ck("r7_120_s10_2_scope", MF + " §3.4・" + PL + " §1", "同附則第10条第2項：施行日前に同年分の確定申告書を出した者（一般）は5年以内に更正の請求ができる",
       "所得税法第百二十五条又は第百二十七条" not in t,
       {"原文の対象": "所得税法第百二十五条又は第百二十七条の規定による確定申告書を提出した者及び同日前に決定を受けた者" if "所得税法第百二十五条又は第百二十七条" in t else t[:200]})
    ck("r8_93_s1", MF + " §3.4", "令和8年政令第93号附則第1条第1号：第205条第1項の改正規定は令和八年十二月一日",
       "第二百五条第一項の改正規定" in r.text(part="S", amend=A93, art="1", para="1", item="1") and "令和八年十二月一日" in r.text(part="S", amend=A93, art="1", para="1", item="1"))
    ck("r8_93_s8_1", MF + " §3.4・" + PL + " §1", "同附則第8条第1項：令和8年分以後", "令和八年分以後の所得税" in r.text(part="S", amend=A93, art="8", para="1"))
    t = r.text(part="S", amend=A93, art="8", para="2")
    ck("r8_93_s8_2_scope", MF + " §3.4・" + PL + " §1", "同附則第8条第2項：施行日前に同年分の確定申告書を出した者（一般）は5年以内に更正の請求ができる",
       ("所得税法第百二十五条又は第百二十七条" not in t), {"原文の対象": "所得税法第百二十五条又は第百二十七条の規定による確定申告書を提出した者及び同日前に決定を受けた者"})
    for asof, amt in (("2025-12-31", "四十八万円以下"), ("2026-01-01", "五十八万円以下"), ("2026-11-09", "五十八万円以下"), ("2027-01-01", "六十二万円以下")):
        lr = L[("chiho-rei", asof)]
        ck(f"chirei48_6_{asof}", MF + " §3.4・" + PL + " §1・§7", f"地令48の6①（asof {asof}）：{amt}", amt in lr.text(art="48_6", para="1"))
        ck(f"chirei7_13_{asof}", PL + " §9（未読とされていた点）", f"地令7の13①（道府県民税、asof {asof}）：{amt}", amt in lr.text(art="7_13", para="1"))
    lr = L[("chiho-rei", "2027-01-01")]
    A119 = "令和七年三月三一日政令第一一九号"; A83 = "令和八年三月三一日政令第八三号"
    ck("r7_119", MF + " §3.4", "令和7年政令第119号附則第1条第1号（令和八年一月一日）に第48条の6第1項の改正規定、附則第6条第2項：令和8年度以後",
       "同令第四十八条の六第一項の改正規定" in lr.text(part="S", amend=A119, art="1", para="1", item="1") and "令和八年一月一日" in lr.text(part="S", amend=A119, art="1", para="1", item="1")
       and "令和八年度以後" in lr.text(part="S", amend=A119, art="6", para="2"))
    ck("r8_83", MF + " §3.4", "令和8年政令第83号附則第1条第1号（令和九年一月一日）に第48条の6第1項の改正規定、附則第5条第2項：令和9年度以後",
       "第四十八条の六第一項の改正規定" in lr.text(part="S", amend=A83, art="1", para="1", item="1") and "令和九年一月一日" in lr.text(part="S", amend=A83, art="1", para="1", item="1")
       and "令和九年度以後" in lr.text(part="S", amend=A83, art="5", para="2"))

    # ---- 6. 地方税法：PS-HKL §7・§8、M-HKF §3.3 ----
    t = c26b.text(art="314_2", para="1", item="5")
    ck("chiho314_2_5", PL + " §7", "地法314の2①五：1万2千/3万2千/5万6千/2万8千、1万5千/4万/7万/3万5千、両方2万8千、合計7万",
       all(x in t for x in ("一万二千円以下", "一万二千円と当該合計額から一万二千円を控除した金額の二分の一", "二万二千円と当該合計額から三万二千円を控除した金額の四分の一",
                            "五万六千円を超える場合　二万八千円", "一万五千円以下", "二万七千五百円と当該合計額から四万円を控除した金額の四分の一", "七万円を超える場合　三万五千円",
                            "当該合計額が二万八千円を超える場合には、二万八千円")) and "当該合計額が七万円を超える場合には、七万円" in c26b.text(art="314_2", para="1", item="5").split("\n")[0])
    ck("chiho314_2_5_3", PL + " §7", "地法314の2①五の三：2分の1、2万5千円", "二分の一に相当する金額（その金額が二万五千円を超える場合には、二万五千円）" in c26b.text(art="314_2", para="1", item="5_3"))
    ck("chiho314_2_1", PL + " §7", "地法314の2①一：第313条第10項の資産と政令で定める生活に通常必要でない資産を除く、10分の1・5万円",
       all(x in c26b.text(art="314_2", para="1", item="1") for x in ("第三百十三条第十項に規定する資産及び生活に通常必要でない資産として政令で定める資産を除く", "十分の一", "五万円")))
    ck("chiho314_2_4", PL + " §7", "地法314の2①四：支払った金額の合計額（小規模企業共済・企業型/個人型・条例の共済）",
       all(x in c26b.text(art="314_2", para="1", item="4") for x in ("その支払つた金額の合計額", "小規模企業共済法", "個人型年金加入者掛金", "条例の規定により地方公共団体")))
    ck("chiho314_2_p5_7_11", PL + " §7", "地法314の2⑤（財形は適用しない）・⑦（附帯の新契約のみなし）・⑪（まず雑損控除額）",
       "勤労者財産形成貯蓄保険契約等" in c26b.text(art="314_2", para="5") and "同日以後に締結した契約とみなす" in c26b.text(art="314_2", para="7") and
       "まず雑損控除額を控除し" in c26b.text(art="314_2", para="11"))
    t = c26b.text(part="S", amend="平成一八年三月三一日法律第七号", art="11", para="5")
    ck("h18_7_11_5", PL + " §7", "平18法7附則11⑤：1/2・2万5千、5千円＋（超える額〔上限1万円〕の1/2）、両方2万5千",
       all(x in t for x in ("二分の一に相当する金額（その金額が二万五千円を超える場合には、二万五千円）", "五千円以下である場合", "五千円にその超える金額（その金額が一万円を超えるときは、一万円）の二分の一",
                            "当該合計額が二万五千円を超える場合には、二万五千円")))
    t = c26b.text(art="314_7", para="1")
    ck("chiho314_7_1", PL + " §8.1", "地法314の7①：100分の30・2千円・100分の6（指定都市100分の8）・特例控除額を加算・所得割の額が上限",
       all(x in t for x in ("百分の三十", "二千円", "百分の六", "百分の八", "特例控除額を加算", "当該所得割の額に相当する金額")))
    t = c26b.text(art="314_7", para="1", item="3"); t27 = c27.text(art="314_7", para="1", item="3")
    ck("chiho314_7_1_3", PL + " §8.1・" + MF + " §3.3", "地法314の7①三：所法78②二・三（2026-11-09）→二から四まで（2027-01-01）、市町村の条例で定めるもの",
       "第七十八条第二項第二号及び第三号" in t and "第七十八条第二項第二号から第四号まで" in t27 and "市町村の条例で定めるもの" in t27)
    ck("chiho314_7_9", PL + " §8.1", "地法314の7⑨：寄附金を支出した時に指定されているか", "支出した時に当該第一号寄附金を受領した都道府県等が指定をされているか" in c26b.text(art="314_7", para="9"))
    t = c26b.text(art="314_7", para="11")
    ck("chiho314_7_11", PL + " §8.2", "地法314の7⑪（2026-11-09）：2千円超・5分の3（指定都市5分の4）・所得割の100分の20、表の割合85〜45、差引き負は100分の90",
       all(x in t for x in ("二千円を超える金額", "五分の三", "五分の四", "百分の二十", "百九十五万円以下の金額 | 百分の八十五", "千八百万円を超え四千万円以下の金額 | 百分の五十",
                            "四千万円を超える金額 | 百分の四十五", "百分の九十", "四十八万円を控除して得た額")))
    ck("chiho314_7_11_old", PL + " §1・§8.2・" + MF + " §3.3", "地法314の7⑪一の人的控除差調整額は 2026-03-31 まで「前条第一号イに掲げる金額」だけ、2026-04-01 から基礎控除−48万円を加える",
       "四十八万円" not in c0331.text(art="314_7", para="11", item="1") and "四十八万円を控除して得た額" in c26a.text(art="314_7", para="11", item="1"))
    cp = c0331.changed_paras(c26a, art="314_7")
    ck("chiho314_7_0401_paras", MF + " §3.3", "地法314の7 の 2026-03-31→2026-04-01 の変更：第11項第1号のほか第4項〜第8項（指定の取消し）の整理（第2項第5号の項番号の引用も変わる）", cp == ["2", "4", "5", "6", "7", "8", "11"], {"changed_paras": cp})
    cp = c26a.changed_paras(c26b, art="314_7")
    ck("chiho314_7_1101_paras", MF + " §3.3", "地法314の7 の 2026-04-01→2026-11-09 の差分は「第2項と第3項〜第8項」", cp == ["2", "3", "4", "5", "6", "7", "8"], {"changed_paras": cp})
    t = c27.text(art="314_7", para="11")
    ck("chiho314_7_11_r9", MF + " §3.3・" + PL + " §1", "地法314の7⑪（2027-01-01）：百十五万八千円（指定都市百五十四万四千円）", "百十五万八千円" in t and "百五十四万四千円" in t)
    t = c27.text(art="37_2", para="11")
    ck("chiho37_2_11_r9", MF + " §3.3・" + PL + " §1", "地法37の2⑪（2027-01-01）：七十七万二千円（指定都市三十八万六千円）、5分の2（5分の1）", all(x in t for x in ("七十七万二千円", "三十八万六千円", "五分の二", "五分の一")))
    ck("chiho37_2_1", PL + " §8.1", "地法37の2①：100分の4（指定都市100分の2）", "百分の四" in c26b.text(art="37_2", para="1") and "百分の二" in c26b.text(art="37_2", para="1"))
    t1 = c27.text(part="S", amend="orig", art="5_5", para="1"); t2 = c27.text(part="S", amend="orig", art="5_5", para="2")
    ck("chiho_s5_5_r9", MF + " §3.3", "地法附則5の5①②（2027-01-01）も同じ額の上限", "七十七万二千円" in t1 and "百十五万八千円" in t2)
    t = c26b.text(part="S", amend="orig", art="5_6", para="2")
    ck("chiho_s5_6_2", PL + " §8.2・" + MC + " §6", "地法附則5の6②：平成26年度から令和20年度、84.895〜44.055、49.16・59.37・74.685",
       all(x in t for x in ("平成二十六年度から令和二十年度まで", "百分の八十四・八九五", "百分の七十九・七九", "百分の六十九・五八", "百分の六十六・五一七", "百分の五十六・三〇七",
                            "百分の四十九・一六", "百分の四十四・〇五五", "百分の五十九・三七", "百分の七十四・六八五")))
    t = c26b.text(part="S", amend="orig", art="7_3", para="2")
    ck("chiho_s7_3_2", PL + " §8.4・" + MC + " §6", "地法附則7の3②：平成28年度から令和20年度、84.895分の5.105 など",
       all(x in t for x in ("平成二十八年度から令和二十年度まで", "八十四・八九五分の五・一〇五", "七十九・七九分の十・二一", "六十九・五八分の二十・四二", "六十六・五一七分の二十三・四八三", "五十六・三〇七分の三十三・六九三")))
    t = c26b.text(part="S", amend="orig", art="7_2", para="5")
    ck("chiho_s7_2_5", PL + " §8.4", "地法附則7の2⑤（2026-04-01 以後）：区分と 85分の5〜57分の33（900万円超は1区分）",
       all(x in t for x in ("四十八万円を控除して得た額", "八十五分の五", "八十分の十", "七十分の二十", "六十七分の二十三", "九百万円を超える金額 | 五十七分の三十三")) and "四十八万円" not in c0331.text(part="S", amend="orig", art="7_2", para="5"))
    t = c26b.text(part="S", amend="orig", art="7")
    ok = all(x in c26b.text(part="S", amend="orig", art="7", para="8") for x in ("所得税法第百二十条第一項の規定による申告書を提出する義務がないと見込まれる者", "同法第百二十一条（第一項ただし書を除く。）",
                                                                                 "第三百十七条の三第一項の規定により", "確定申告書の提出を含む", "当分の間"))
    ok = ok and "五以下" in c26b.text(part="S", amend="orig", art="7", para="9") and "一月十日" in c26b.text(part="S", amend="orig", art="7", para="11") and \
        "一月三十一日" in c26b.text(part="S", amend="orig", art="7", para="12") and "氏名、住所及び生年月日" in c26b.text(part="S", amend="orig", art="7", para="10", item="1")
    t13 = c26b.text(part="S", amend="orig", art="7", para="13")
    ok = ok and all(x in t13 for x in ("第百二十一条の規定の適用を受けないこととなつた", "第三百十七条の二第一項から第五項までの規定による申告書の提出をした", "五を超えた", "異なつた", "なかつたものとみなす"))
    t6 = c26b.text(part="S", amend="orig", art="7", para="6")
    ok = ok and "なかつたものとみなす" in t6 and "第四十五条の二の規定による申告書の提出をした" in t6
    ck("chiho_s7", PL + " §8.3・" + HY + " H8", "地法附則7⑧〜⑬（5以下・1月10日・1月31日・4つの無効事由）、道府県は⑥", ok)
    ok = all(x in c27.text(art="317_3", para="1") for x in ("所得税法第二条第一項第三十七号の確定申告書", "政令で定める場合を除く", "提出されたものとみなす"))
    ck("chiho317_3", PL + " §8.3", "地法317の3①（2027-01-01）", ok)
    A2 = "令和八年三月三一日法律第二号"
    ok = "令和八年四月一日から施行" in c27.text(part="S", amend=A2, art="1", para="1").split("\n")[0]
    t1 = c27.text(part="S", amend=A2, art="1", para="1", item="1"); t2 = c27.text(part="S", amend=A2, art="1", para="1", item="2")
    ok = ok and "令和八年十月一日" in t1 and "同法第三百十四条の七第二項の改正規定" in t1 and "令和九年一月一日" in t2 and \
        "同法第三百十四条の七第十一項の改正規定（同項第一号に係る部分を除く。）" in t2 and "同法第三十七条の二第十一項の改正規定（同項第一号に係る部分を除く。）" in t2 and "同法附則第五条の五の改正規定" in t2
    ck("r8_2_s1", MF + " §3.3・" + PL + " §1", "令和8年法律第2号附則第1条：原則 令和8年4月1日、第1号 令和8年10月1日、第2号 令和9年1月1日（314の7⑪の改正は第1号に係る部分を除く）", ok)
    ok = "令和八年度以後" in c27.text(part="S", amend=A2, art="3", para="1") and "令和八年度以後" in c27.text(part="S", amend=A2, art="11", para="1") and \
        "令和十年度以後" in c27.text(part="S", amend=A2, art="3", para="9") and "令和十年度以後" in c27.text(part="S", amend=A2, art="11", para="8") and \
        "百分の五十二・五" in c27.text(part="S", amend=A2, art="3", para="5") and "令和九年九月三十日" in c27.text(part="S", amend=A2, art="11", para="4")
    ck("r8_2_s3_11", MF + " §3.3・" + PL + " §1", "同附則第3条①⑤⑨・第11条①④⑧（令和8年度以後、令和10年度以後、百分の五十二・五）", ok)

    # ---- 7. 国税庁・総務省のページ：M-HKF §4、PS-HKN ----
    EXPW = {"ta_1110": ("Wed, 09 Sep 2026 01:00:17 GMT", "377fee05900a97e3"), "ta_1135": ("Wed, 09 Sep 2026 01:00:16 GMT", "7feba875b3b0ce80"),
            "ta_1140": ("Wed, 09 Sep 2026 01:00:16 GMT", "20cf3d89f75dc48a"), "ta_1140_qa": ("Wed, 09 Sep 2026 01:00:16 GMT", "a97fab46521400ee"),
            "ta_1141": ("Wed, 09 Sep 2026 01:00:16 GMT", "d413caed251207e9"), "ta_1145": ("Wed, 09 Sep 2026 01:00:16 GMT", "13e2dd00c0165c02"),
            "ta_1146": ("Wed, 09 Sep 2026 01:00:16 GMT", "6b6331a281b23362"), "ta_1150": ("Wed, 09 Sep 2026 01:00:16 GMT", "850e2be9456fb284"),
            "ta_1155": ("Wed, 09 Sep 2026 01:00:15 GMT", "6f2ea6b344610274"), "ta_1902": ("Tue, 25 Aug 2026 05:00:01 GMT", "27810fec98a6178b"),
            "shitsugi_05_74": ("Wed, 03 Dec 2025 08:31:00 GMT", "207e9fd72fffcb53"), "shitsugi_05_75": ("Wed, 03 Dec 2025 08:31:00 GMT", "c5be17f927c8aac7"),
            "shitsugi_05_76": ("Wed, 03 Dec 2025 08:31:00 GMT", "f78dbf2ed3d95c36"), "shitsugi_05_68": ("Wed, 03 Dec 2025 08:31:01 GMT", "4526423ea6edd742"),
            "shitsugi_05_05": ("Wed, 03 Dec 2025 08:31:03 GMT", "4cc1f311ae396d01"), "shitsugi_02_37": ("Wed, 03 Dec 2025 08:31:06 GMT", "f513bd5fb1d72336"),
            "shitsugi_gensen_03_35": ("Wed, 03 Dec 2025 08:31:15 GMT", "ca8f5848862b9fd1"), "kihon_16_01": ("Thu, 18 Jan 2024 09:30:20 GMT", "c00969ebe1eb83e0"),
            "kihon_16_03": ("Thu, 18 Jan 2024 09:30:20 GMT", "c26562a874bbead4"), "kihon_16_04": ("Thu, 25 Dec 2025 01:00:05 GMT", "771948518a019004"),
            "kihon_16_05": ("Fri, 02 Oct 2026 08:30:04 GMT", "50f0070469597674"), "kihon_16_06": ("Tue, 25 Nov 2025 08:30:05 GMT", "73c6009edd9c2ed3"),
            "nta_furusato": ("Tue, 17 Mar 2026 01:00:12 GMT", "c5cafeaa8e304f71"), "nta_tokyo_onestop": ("Tue, 17 Mar 2026 08:30:01 GMT", "766cc4348aab3594"),
            "soumu_furusato_index": ("Wed, 01 Oct 2025 00:14:28 GMT", "1ac955a0b8c79972"), "soumu_mechanism": ("Sun, 08 Feb 2026 23:57:31 GMT", "732a9085ddf7ecfb"),
            "nencho2026_index": ("Fri, 16 Oct 2026 08:30:09 GMT", "3e47f99112faf3ff"), "nencho2026_107pdf": ("Mon, 31 Aug 2026 08:30:11 GMT", "38907ac31a3a50e0"),
            "nencho2026_105pdf": ("Thu, 24 Sep 2026 08:30:11 GMT", "9460af44b13c8651")}
    for pid, (lm, sha) in EXPW.items():
        p = WP[pid]
        ck(f"web_{pid}", MF + " §4", f"{pid}: HTTP 200, Last-Modified {lm}, SHA-256 {sha}", p["status"] == 200 and p["last_modified"] == lm and p["sha256"][:16] == sha,
           None if p["last_modified"] == lm and p["sha256"][:16] == sha else {"got": [p["last_modified"], p["sha256"][:16]]})
    ck("web_ta_genzai", MF + " §4・" + PN + " 冒頭", "TA 10ページとも「[令和8年4月1日現在法令等]」",
       all(WP[k].get("genzai_horei") == "[令和8年4月1日現在法令等]" for k in EXPW if k.startswith("ta_")))
    TITLES = {"kihon_16_01": "法第72条《雑損控除》関係", "kihon_16_03": "法第76条《生命保険料控除》関係", "kihon_16_04": "法第77条《地震保険料控除》関係",
              "kihon_16_05": "法第78条《寄附金控除》関係", "kihon_16_06": "法第79条《障害者控除》関係", "nta_furusato": "ふるさと納税をされた方へ｜令和7年分 確定申告特集",
              "soumu_mechanism": "税金の控除について", "nencho2026_index": "令和8年分　年末調整のしかた"}
    for pid, tt in TITLES.items():
        ck(f"title_{pid}", MF + " §4", f"{pid} の題名に「{tt}」", tt in (WP[pid].get("title") or ""), WP[pid].get("title"))
    ok, det = whas("nencho2026_index", ["2-3 保険料控除申告書の受理と内容の確認", "21から28", "2 各種控除額の確認", "8から15"])
    ck("nencho_toc", MF + " §4", "年末調整のしかた目次：2-3 は 21から28、2 は 8から15", ok, det)
    WEBQ = [
        ("ta_1140", PN + " §1.1", ["平成24年1月1日以後に締結した保険契約等に係る保険料と平成23年12月31日以前に締結した保険契約等に係る保険料では、生命保険料控除の取扱いが異なります。",
                                   "保険期間が5年未満の生命保険などの中には、控除の対象とならないものもあります", "120,000円を超える場合", "令和8年分以降の申告の場合",
                                   "30,000円超 60,000円以下", "新生命保険料×1/2+15,000円", "新生命保険料×1/4+30,000円", "一律60,000円", "主たる保障内容",
                                   "支払保険料等×1/2+12,500円", "支払保険料等×1/4+25,000円", "令和8年以降、23歳未満の扶養親族を有する新生命保険料を支払った場合は最高60,000円",
                                   "年間保険料が9,000円以下のものと年末調整の際に控除を受けたもの", "所法76、120、所令209、262、平成29年国税庁告示10号"]),
        ("ta_1140_qa", PN + " §1.2", ["契約者が誰であるかは要件とされていません", "保険料を支った夫の生命保険料控除の対象".replace("支った", "支払った"), "解約一時金は原則として一時所得",
                                      "保険料等を支払った時の現況により判定", "(所法76、所基通76-1)"]),
        ("ta_1141", PN + " §1.3", ["10年以上の期間にわたって、定期に支払う", "満60歳", "重度の障害を原因として", "財形年金貯蓄契約", "所法76、120、所令208の3～212、262、所規40の6、40の7、47の2"]),
        ("shitsugi_05_74", PN + " §1.4", ["新生命保険料だけの場合：3万円", "旧生命保険料だけの場合：5万円", "4万円が限度額"]),
        ("shitsugi_05_75", PN + " §1.4", ["新生命保険料と旧生命保険料に係る控除のいずれを適用するか又はその両方の支払について適用するか、納税者はいずれか有利な方を選択することができます。"]),
        ("shitsugi_05_76", PN + " §1.4", ["それぞれの生命保険料控除の区分ごとに、どちらの控除額を適用するか（又は併用するか）は任意に選択できます", "120,000円（限度額）"]),
        ("shitsugi_gensen_03_35", PN + " §1.4", ["Aがその保険料を支払ったことを明らかにした場合は、生命保険料控除の対象として差し支えありません。", "必ずしも払込みをする者が保険契約者である必要はありません（所得税法第76条第5項、第6項）",
                                                 "贈与税又は一時所得として課税が生じる"]),
        ("kihon_16_03", PN + " §1.5", ["保険料又は掛金を支払った時の現況により判定する", "現実に支払っていないものは含まれない", "振替貸付けにより生命保険料等の払込みに充当した金額は、その年において支払った金額とする",
                                       "その返済した金額は支払った生命保険料等には該当しない", "その減額後の額を支払った金額とする", "その負担した金額は役員又は使用人が支払った生命保険料等の金額には含まれない",
                                       "旧生命保険契約等、介護医療保険契約等、新個人年金保険契約等又は旧個人年金保険契約等に係る保険料又は掛金からは控除しない"]),
        ("ta_1145", PN + " §2.1", ["平成18年12月31日までに締結した契約", "10年以上の契約", "平成19年1月1日以後にその損害保険契約等の変更をしていないもの", "支払金額×1/2＋5,000円",
                                   "（最高50,000円）", "納税者の選択により地震保険料または旧長期損害保険料のいずれか一方の控除を受けることとなります", "平18改正法附則10"]),
        ("ta_1146", PN + " §2.2", ["自己や自己と生計を一にする配偶者その他の親族の所有する家屋で常時その居住の用に供するものまたは生活に通常必要な家具、じゅう器、衣服などの生活用動産",
                                   "所法77、120、所令213、214、262、所規40の8、47の2、平18財務省告示第139号"]),
        ("shitsugi_05_68", PN + " §2.3", ["地震保険料控除の額は13,500円とすることができます。", "建物又は動産の共済期間中の耐存を共済事故とする共済に係る契約"]),
        ("kihon_16_04", PN + " §2.4", ["代金完済後に所有権を移転する旨の特約", "居住の用に供している部分だけが居住の用に供する家屋に該当する", "おおむね90%以上を居住の用に供しているとき",
                                       "76−3から76−7までの取扱いに準ずる"]),
        ("ta_1150", PN + " §3.1", ["所得控除に代えて、税額控除を選択することができます", "（4）一定の公益信託の信託財産とするために支出したその公益信託に係る信託事務に関連する寄附金",
                                   "学校の入学に関してするもの、寄附をした人に特別の利益がおよぶと認められるものおよび政治資金規正法に違反するもの", "次の（1）または（2）のいずれか低い金額 - 2000円 ＝ 寄附金控除額",
                                   "令和3年分の確定申告から、ふるさと納税の場合は", "特定事業者", "所法78、120、所令217、217の2、262、所規47の2、措法41の18、41の18の2、41の18の3、41の18の4"]),
        ("ta_1155", PN + " §3.2", ["確定申告を行う方は、ふるさと納税ワンストップ特例の申請が無効となるため、ワンストップ特例の申請をした分も含めて寄附金控除額を計算する必要があります。",
                                   "所得割額の20％を限度", "平成25年分から令和29年分については、所得税率が0％である場合を除き、復興特別所得税を加算した率", "ふるさと納税先が5団体以内の場合に限り",
                                   "医療費控除や雑損控除を受けるなどのために確定申告や個人住民税の申告をする方などを含みます", "更正の請求により寄附金控除の適用を受けることができます",
                                   "最終的な所得税等の額に異動がない場合は、更正の請求をすることができません", "都道府県、市区町村への寄附（特例控除対象）", "地方税法45の3、317の3、地方税法施行規則2の3",
                                   "所法78、所法165、通法23、地法37の2、314の7、地法附則7、7の2、7の3"]),
        ("nta_furusato", PN + " §3.3", ["５団体以内で、各ふるさと納税先の自治体にふるさと納税ワンストップ特例の申請を行われた方は、原則として確定申告は不要です（所得税の控除額も個人住民税から控除されます。）。",
                                        "寄附金受領証明書等のデータをマイナポータル経由で取得"]),
        ("nta_tokyo_onestop", PN + " §3.3", ["確定申告を行う場合は、ふるさと納税ワンストップ特例の適用に関する申請が無効となるため", "更正の請求書の提出が必要です",
                                             "寄附金控除を追加しても最終的な所得税等の額に異動がない場合は、更正の請求をすることができませんので、この場合は、お住まいの市区町村にご相談ください。"]),
        ("soumu_mechanism", PN + " §3.4", ["(1)所得税からの控除 = （ふるさと納税額−2,000円）×「所得税の税率」", "総所得金額等の40％が上限", "令和19年中の寄附までは、所得税の税率は復興特別所得税の税率を加えた率",
                                           "総所得金額等の30％が上限", "個人住民税の課税総所得金額から人的控除差調整額を差し引いた金額により求めた所得税の税率", "(3)'住民税からの控除（特例分） = （住民税所得割額）×20％",
                                           "平成27年4月1日以後に行われるふるさと納税に適用", "所得税からの控除は行われず、その分も含めた控除額の全額が、翌年度の住民税から控除されます。"]),
        ("shitsugi_02_37", PN + " §3.5", ["寄附者が特産品を受けた場合の経済的利益は、一時所得に該当します。", "所得税基本通達34-1(5)"]),
        ("kihon_16_05", PN + " §3.6", ["現実に支払ったことをいう", "手形の振出し", "入学辞退等により結果的に入学しないこととなった場合においても、これに該当する", "義援金配分委員会",
                                       "最終的に国等に帰属しないと認められるものは、国等に対する寄附金には該当しない", "全額政府出資", "当該個人が支出した寄附金として同条の規定を適用する",
                                       "78−10 法第78条第２項第４号に規定する「出資に関する信託事務に充てられることが明らかなもの」", "令８課個2-8"]),
        ("ta_1135", PN + " §4", ["旧第二種共済契約の掛金はこの控除ではなく生命保険料控除の対象", "個人型年金加入者掛金", "心身障害者扶養共済制度", "その年に支払った掛金の全額です。",
                                 "令和8年分以後の所得税に係る確定申告書を令和9年1月1日以後に提出するときは"]),
        ("ta_1110", PN + " §5.1", ["災害減免法による所得税の軽減免除があり、納税者の選択によりどちらか有利な方法を選べます", "（損害金額+災害等関連支出の金額-保険金等の額）-（総所得金額等）×10％",
                                   "（災害関連支出の金額-保険金等の額）-5万円", "保険金等の額は、まず、損害金額から差し引き、保険金等の額が損害金額を超える場合には、災害（等）関連支出の金額から差し引きます。",
                                   "58万円以下（注）（令和2年分から令和6年分までは48万円以下）", "令和8年12月1日に施行され、令和8年分から適用される金額は「62万円以下」です。",
                                   "1個または1組の価額が30万円超", "詐欺や恐喝の場合には、雑損控除は受けられません。", "翌年以後3年間", "5年間", "所法2、62、71、71の2、72、87、120、所令9、178、203、204、204の2、205、206、262、災免法2"]),
        ("shitsugi_05_05", PN + " §5.2", ["「詐欺」による損失は対象となりません。"]),
        ("kihon_16_01", PN + " §5.3", ["当該損失が生じた日又は現実に当該支出をした日", "基礎控除の額に相当する金額以下であるかどうか", "12月31日の現況により判定する", "その死亡又は出国の日において見積もった",
                                       "その年1月1日から3月15日までの間に支出をした金額", "その金額の30%に相当する額を原状回復のための支出の部分の額とし", "37−15の3、51−6から51−8まで及び70−6から70−12までの取扱いに準ずる"]),
        ("ta_1902", PN + " §5.4", ["No.1902 災害減免法による所得税の軽減免除"]),
    ]
    for pid, doc, needles in WEBQ:
        ok, det = whas(pid, needles)
        ck(f"quote_{pid}", doc, f"{pid} の引用・要約（{len(needles)}か所）", ok, det)

    (OUT / "checks.json").write_text(json.dumps({"egov_text_dir": str(tdir.relative_to(ROOT)).replace("\\", "/"),
                                                  "web_text_dir": str(wdir.relative_to(ROOT)).replace("\\", "/"),
                                                  "n": len(checks), "ng": sum(1 for c in checks if not c["ok"]), "checks": checks},
                                                 ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"[{'OK' if c['ok'] else 'NG'}] {c['id']} ({c['doc']}): {c['claim']}" + ("" if c["ok"] or not c["detail"] else "  -> " + json.dumps(c["detail"], ensure_ascii=False)[:600])
             for c in checks]
    (OUT / "checks_summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"checks: {len(checks)}  NG: {sum(1 for c in checks if not c['ok'])}")
    for ln in lines:
        if ln.startswith("[NG]"):
            print(ln)


# ---------------- 式の検算（自分で書き直したもの。ネットワーク不要） ----------------
def piece(x, steps, cap):
    """条文の書き方そのまま：steps = [(上限, 基礎額, 控除する額, 割合)]。x が上限以下の最初の段で 基礎額 + (x - 控除する額)×割合。超えれば cap。"""
    x = F(x)
    for upper, base, minus, rate in steps:
        if x <= upper:
            return F(base) + (x - minus) * rate
    return F(cap)


# 所法76①一（新）、①二（旧）、措法41の15の5 の読替え後の①一、地法314の2①五イ（１）（２）
SH_NEW = ([(20000, 0, 0, 1), (40000, 20000, 20000, F(1, 2)), (80000, 30000, 40000, F(1, 4))], 40000)
SH_OLD = ([(25000, 0, 0, 1), (50000, 25000, 25000, F(1, 2)), (100000, 37500, 50000, F(1, 4))], 50000)
SH_TOK = ([(30000, 0, 0, 1), (60000, 30000, 30000, F(1, 2)), (120000, 45000, 60000, F(1, 4))], 60000)
JU_NEW = ([(12000, 0, 0, 1), (32000, 12000, 12000, F(1, 2)), (56000, 22000, 32000, F(1, 4))], 28000)
JU_OLD = ([(15000, 0, 0, 1), (40000, 15000, 15000, F(1, 2)), (70000, 27500, 40000, F(1, 4))], 35000)


def f(table, x):
    return piece(x, *table)


def nta_table(x, rows, cap):
    """国税庁の表の書き方：rows = [(上限, 割合, 加算額)]。支払額×割合＋加算額。"""
    x = F(x)
    for upper, rate, add in rows:
        if x <= upper:
            return x * rate + add
    return F(cap)


def ippan(new, old, tok=False):
    fn = SH_TOK if tok else SH_NEW
    cap3 = 60000 if tok else 40000
    return {"新のみ": f(fn, new), "旧のみ": f(SH_OLD, old), "両方": min(f(fn, new) + f(SH_OLD, old), F(cap3))}


def zasson_law(Lx, Dx, T):
    """所法72①：損失の金額 Lx（保険金等控除後、支出を含む）、災害関連支出 Dx、総所得金額等 T"""
    tenth = F(T, 10)
    if Lx == Dx and Lx > 0:
        th = min(F(50000), tenth)
    elif Dx <= 50000:
        th = tenth
    else:
        th = min(F(Lx) - (Dx - 50000), tenth)
    return max(F(0), F(Lx) - th)


def zasson_ta(Lx, Dx, T):
    return max(F(0), max(F(Lx) - F(T, 10), F(Dx) - 50000))


def cmd_calc():
    import random
    res = []

    def rc(cid, doc, claim, ok, detail=None):
        res.append({"id": cid, "doc": doc, "claim": claim, "ok": bool(ok), "detail": detail})

    # 1. 条文の式 ＝ 国税庁の表（0〜300,000 円の整数）
    T1 = ([(20000, 1, 0), (40000, F(1, 2), 10000), (80000, F(1, 4), 20000)], 40000)
    T2 = ([(30000, 1, 0), (60000, F(1, 2), 15000), (120000, F(1, 4), 30000)], 60000)
    T3 = ([(25000, 1, 0), (50000, F(1, 2), 12500), (100000, F(1, 4), 25000)], 50000)
    for cid, law, ta in (("shiki1", SH_NEW, T1), ("shiki2", SH_TOK, T2), ("shiki3", SH_OLD, T3)):
        mism = [x for x in range(0, 300001) if f(law, x) != nta_table(x, *ta)]
        rc(cid, "M-HKC §1", f"条文の式 ＝ 国税庁の計算式（{cid}）0〜300,000 円", not mism, {"不一致": len(mism)})
    # 境目で値が飛ばない
    jumps = []
    for tbl, bs in ((SH_NEW, (20000, 40000, 80000)), (SH_TOK, (30000, 60000, 120000)), (SH_OLD, (25000, 50000, 100000))):
        for b in bs:
            if f(tbl, b + 1) - f(tbl, b) > 1:
                jumps.append(b)
    rc("boundary", "M-HKC §1", "境目の次の1円で値が飛ばない", not jumps, {"jumps": jumps})
    vals = {k: [str(f(t, b)) for b in bs] for k, t, bs in (("新", SH_NEW, (20000, 40000, 80000)), ("特例", SH_TOK, (30000, 60000, 120000)), ("旧", SH_OLD, (25000, 50000, 100000)))}
    rc("boundary_vals", "M-HKC §1", "境目の値 20,000/30,000/40,000、30,000/45,000/60,000、25,000/37,500/50,000",
       vals == {"新": ["20000", "30000", "40000"], "特例": ["30000", "45000", "60000"], "旧": ["25000", "37500", "50000"]}, vals)
    # 2. 質疑応答事例
    o = ippan(40000, 100000)
    rc("q0574", "M-HKC §1・PS-HKN §1.4", "05/74：新のみ30,000・旧のみ50,000・両方40,000 → 50,000", (o["新のみ"], o["旧のみ"], o["両方"]) == (30000, 50000, 40000) and max(o.values()) == 50000, {k: str(v) for k, v in o.items()})
    rc("q0576", "M-HKC §1", "05/76：50,000＋25,000＋50,000＝125,000 → 120,000", min(F(50000 + 25000 + 50000), F(120000)) == 120000)
    o = ippan(40000, 100000, tok=True)
    rc("tok_example", "M-HKC §1", "特例あり（新4万・旧10万）：新のみ35,000・旧のみ50,000・両方60,000", (o["新のみ"], o["旧のみ"], o["両方"]) == (35000, 50000, 60000), {k: str(v) for k, v in o.items()})
    # 3. 端数の数
    def nfrac(tbl, hi):
        return sum(1 for x in range(0, hi + 1) if f(tbl, x).denominator != 1)
    cnt = {"新": nfrac(SH_NEW, 200000), "特例": nfrac(SH_TOK, 200000), "旧": nfrac(SH_OLD, 200000), "住民税新": nfrac(JU_NEW, 200000),
           "住民税地震": sum(1 for x in range(0, 100001) if min(F(x, 2), F(25000)).denominator != 1)}
    rc("frac_counts", "M-HKC §2・H H4", "端数が出る支払額の数：40,000／60,000／50,000／28,000／25,000",
       cnt == {"新": 40000, "特例": 60000, "旧": 50000, "住民税新": 28000, "住民税地震": 25000}, cnt)
    rc("frac_examples", "M-HKC §2", "20,001→40001/2、40,003→120003/4、地震（住民税）10,001→10001/2",
       f(SH_NEW, 20001) == F(40001, 2) and f(SH_NEW, 40003) == F(120003, 4) and F(10001, 2) == F(10001, 2))
    # 4. 地震保険料
    def kyucho(x):
        return piece(x, [(10000, 0, 0, 1), (20000, 10000, 10000, F(1, 2))], 15000)
    mism = [x for x in range(0, 60001) if kyucho(x) != nta_table(x, [(10000, 1, 0), (20000, F(1, 2), 5000)], 15000)]
    rc("kyucho_ta1145", "M-HKC §3", "平18法10附則10②二 ＝ TA1145 の表（0〜60,000 円）", not mism, {"不一致": len(mism)})
    rc("q0568", "M-HKC §3・PS-HKN §2.3", "05/68：地震10,000 と 旧長期17,000→13,500 の大きい方 13,500", max(min(F(10000), F(50000)), kyucho(17000)) == 13500)
    def ju_jishin(x):
        return min(F(x, 2), F(25000))
    def ju_kyucho(x):
        x = F(x)
        return x if x <= 5000 else 5000 + min(x - 5000, F(10000)) / 2
    vals = [ju_jishin(50000), ju_jishin(60000), ju_kyucho(10000), ju_kyucho(20000), min(ju_jishin(40000) + ju_kyucho(20000), F(25000))]
    rc("ju_jishin", "M-HKC §3", "住民税：地震5万→25,000、6万→25,000、旧長期1万→7,500、2万→10,000、地震4万＋旧長期2万→25,000", vals == [25000, 25000, 7500, 10000, 25000], [str(v) for v in vals])
    # 5. 雑損控除
    LS = [0, 30000, 50000, 50001, 80000, 300000]; DS = [0, 30000, 50000, 50001, 80000]; TS = [0, 300000, 500000, 600000, 5000000]
    combos = [(l, d, t) for l in LS for d in DS for t in TS if d <= l]
    rnd = random.Random(20261109)
    for _ in range(200000):
        l = rnd.randint(0, 3000000); d = rnd.randint(0, l); t = rnd.randint(0, 20000000)
        combos.append((l, d, t))
    mism = [c for c in combos if zasson_law(*c) != zasson_ta(*c)]
    rc("zasson", "M-HKC §4", f"所法72①一〜三 ＝ TA1110 の「いずれか多い方」（{len(combos)} 組）", not mism and len(combos) == 200100, {"件数": len(combos), "不一致": len(mism), "例": mism[:3]})
    # 6. 寄附金控除
    def kifu(g, T):
        return max(F(0), min(F(g), F(T) * F(40, 100)) - 2000)
    vals = [kifu(30000, 3000000), kifu(1500000, 3000000), kifu(2000, 3000000)]
    rc("kifu", "M-HKC §5", "寄附3万→28,000、150万→1,198,000、2千→0", vals == [28000, 1198000, 0], [str(v) for v in vals])
    # 7. ふるさと納税の割合
    rates = [5, 10, 20, 23, 33, 40, 45]
    honsoku = [85, 80, 70, 67, 57, 50, 45]
    fusoku = [F("84.895"), F("79.79"), F("69.58"), F("66.517"), F("56.307"), F("49.16"), F("44.055")]
    ok = all(90 - r == h for r, h in zip(rates, honsoku)) and all(90 - F(r) * F("1.021") == x for r, x in zip(rates, fusoku))
    rc("furusato_rates", "M-HKC §6", "314の7⑪の表＝90−税率、附則5の6②＝90−税率×1.021", ok)
    sp = [(5, 85), (10, 80), (20, 70), (23, 67), (33, 57)]
    sp2 = [(F("5.105"), F("84.895")), (F("10.21"), F("79.79")), (F("20.42"), F("69.58")), (F("23.483"), F("66.517")), (F("33.693"), F("56.307"))]
    ok = all(F(a, b) == F(r, 90 - r) for (r, _), (a, b) in zip(sp, sp)) and all(a == F(r) * F("1.021") and b == 90 - F(r) * F("1.021") for (r, _), (a, b) in zip(sp, sp2))
    rc("shinkoku_tokurei_rates", "M-HKC §6", "附則7の2⑤・7の3②の割合 ＝ r/(90−r)、r×1.021/(90−r×1.021)", ok)
    ok = all(10 + (90 - F(r) * F("1.021")) + F(r) * F("1.021") == 100 for r in rates)
    rc("sum100", "M-HKC §6", "基本分10＋特例分＋所得税分＝100", ok)
    s5_5 = [(F(50), F("49.16")), (F(60), F("59.37")), (F(75), F("74.685"))]
    rc("s5_5_rates", "PS-HKL §8.2", "附則5の5 の 50・60・75 → 49.16・59.37・74.685（＝90 − (90 − x)×1.021）",
       all(b == 90 - (90 - a) * F("1.021") for a, b in s5_5), [str(90 - (90 - a) * F("1.021")) for a, _ in s5_5])
    # 8. 推測（C）の数値
    a_n = f(SH_NEW, 100000); a_t = f(SH_TOK, 100000)
    b = ippan(50000, 70000); bt = ippan(50000, 70000, tok=True)
    rc("C1", "C C1", "親A：40,000→55,000、親B：特例なし 42,500（新のみ32,500・旧のみ42,500・両方40,000）、特例あり 60,000（新のみ40,000・両方60,000）",
       a_n == 40000 and a_t == 55000 and (b["新のみ"], b["旧のみ"], b["両方"]) == (32500, 42500, 40000) and max(b.values()) == 42500 and
       (bt["新のみ"], bt["旧のみ"], bt["両方"]) == (40000, 42500, 60000) and max(bt.values()) == 60000)
    rc("C6", "C C6", "210万−X−47万 ≦ 195万（X≧0）→84.895%、210万−X ＞ 195万 ⇔ X＜15万→79.79%", 2100000 - 470000 <= 1950000 and 2100000 - 150000 == 1950000)
    v40 = 10 + 50 * (1 + F(33, 57)); v45 = 10 + 45 * (1 + F(33, 57))
    rc("C7", "C C7", "40%区分 ≒88.9%、45%区分 ≒81.1%", round(float(v40), 1) == 88.9 and round(float(v45), 1) == 81.1, [float(v40), float(v45)])
    rc("C8", "C C8", "足切り 500万×1/10＝50万 → 5万の損失は 0", zasson_law(50000, 0, 5000000) == 0)
    rc("C9", "C C9", "地震保険料 1万2千円 → 所得税 12,000、住民税 6,000", min(F(12000), F(50000)) == 12000 and ju_jishin(12000) == 6000)
    rc("C11", "C C11", "新 40,003 円 → 30,000.75 円", f(SH_NEW, 40003) == F(3000075, 100))
    rc("C12", "C C12", "住民税 新10万 → 28,000", f(JU_NEW, 100000) == 28000)
    (OUT / "calc.json").write_text(json.dumps({"n": len(res), "ng": sum(1 for r in res if not r["ok"]), "checks": res}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    lines = [f"[{'OK' if r['ok'] else 'NG'}] {r['id']} ({r['doc']}): {r['claim']}" + ("" if r["ok"] else "  -> " + json.dumps(r["detail"], ensure_ascii=False, default=str)[:400]) for r in res]
    (OUT / "calc_summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"calc: {len(res)}  NG: {sum(1 for r in res if not r['ok'])}")
    for ln in lines:
        if ln.startswith("[NG]"):
            print(ln)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"egov": cmd_egov, "egov_extra": cmd_egov_extra, "web": cmd_web, "check": cmd_check, "calc": cmd_calc}[cmd]()

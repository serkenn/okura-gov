"""R3X shibo-shukkoku の独立した検証（反証役）。

トピック「年の中途の死亡・出国の申告（準確定申告）と、損失の繰越・繰戻し」の文書
（docs/*/20261109_round3_shibo-shukkoku-*.md）に書かれた条文の引用・条番号・項号・版・施行日・数値・期限・URL を、
担当の取得物（.work/downloads/*_R3X_shibo-shukkoku_*、scripts/results/R3X_shibo-shukkoku_*）を使わずに一次情報を取り直して確かめる。

実行（リポジトリのルートで。Python 3.11、標準ライブラリだけ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_shibo-shukkoku_verify.py fetch-egov
      e-Gov 法令API v2：/laws（law_id と asof で版の ID だけを引く）、/law_revisions、/law_data（本文）。
      本文から検査に使う条（本則と令和7年・令和8年の改正附則）を構造つきで excerpts/ に書き出す。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_shibo-shukkoku_verify.py fetch-web [<組> ...]
      国税庁の HTML・PDF（robots.txt を先に読む）。組：main（担当が使ったページ）、extra（担当が使っていないページ。
      引数で URL を足す：extra id=URL ...）。HTML はテキストとリンクを excerpts/web/ に書く。PDF は保存して SHA-256 だけを記録する
      （中身は人が Read ツールで見る。検証の文書に「目視」と書く）。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_shibo-shukkoku_verify.py prior-hashes
      担当の取得物の SHA-256 を計算し直し、担当の実測の文書に書かれた SHA-256 と照らす（中身は読まない。ハッシュだけ）。
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_shibo-shukkoku_verify.py check
      excerpts/ だけを使って検査する（ネットワークに出ない）。結果は checks.json・checks.md。

- API の使い方とテキスト化は scripts/R1_egov_articles.py・scripts/IMPL_kyuyo_fetch.py を読んで写した（import しない）。
- ダウンロードしたもの（信頼できないデータ）は、取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_R3X_shibo-shukkoku_verify_<組>/ に置き、その中では何も実行しない。
- リクエストの間は 1.5 秒。User-Agent は okura-gov-research/0.1。官報は取得しない。個人の情報は送らない・書かない。
- 出力：scripts/results/R3X_shibo-shukkoku_verify/
"""
import datetime as dt
import hashlib
import html.parser
import json
import pathlib
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from fractions import Fraction

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
SLEEP = 1.5
OUT = ROOT / "scripts" / "results" / "R3X_shibo-shukkoku_verify"
EXC = OUT / "excerpts"

DOCS = {
    "PS": ROOT / "docs/public-sources/20261109_round3_shibo-shukkoku-laws-and-nta.md",
    "M": ROOT / "docs/measurements/20261109_round3_shibo-shukkoku-fetch-and-calc.md",
    "H": ROOT / "docs/hypotheses/20261109_round3_shibo-shukkoku-model.md",
    "I": ROOT / "docs/inferences/20261109_round3_shibo-shukkoku-cases.md",
}

# ---------------------------------------------------------------- e-Gov
# (略称, law_id, 本文を取る asof, 版の ID だけを引く asof, 取り出す本則の条 Num, 附則を取り出す改正法令（AmendLawNum の正規表現）)
R7_LAW13 = r"^令和七年.*法律第一三号$"
R8_LAW12 = r"^令和八年.*法律第一二号$"
R7_REI120 = r"^令和七年.*政令第一二〇号$"
R8_REI93 = r"^令和八年.*政令第九三号$"
R7_KI18 = r"^令和七年.*財務省令第一八号$"
R8_KI17 = r"^令和八年.*財務省令第一七号$"
ASOF_ALL = ["2025-12-31", "2026-11-09", "2026-11-30", "2026-12-01", "2026-12-31", "2027-01-01"]
EGOV = [
    ("shotoku", "340AC0000000033", ["2025-12-31", "2026-11-11", "2026-12-01", "2027-01-01"], ASOF_ALL,
     ["2", "3", "16", "60_2", "69", "70", "70_2", "71", "71_2", "72", "85", "86", "87", "89", "102", "115"]
     + [str(n) for n in range(120, 132)] + ["138", "139", "140", "141", "142", "165", "166", "172"],
     [R7_LAW13, R8_LAW12]),
    ("shotoku-rei", "340CO0000000096", ["2025-12-31", "2026-11-11", "2026-12-01", "2027-01-01"], ASOF_ALL,
     ["11_2", "14", "15", "201", "204", "204_2", "205", "206", "218", "218_2", "219", "220", "258", "263", "267", "271", "272", "273"], [R7_REI120, R8_REI93]),
    ("shotoku-ki", "340M50000040011", ["2025-12-31", "2026-11-11", "2026-12-31", "2027-01-01"], ASOF_ALL,
     ["47", "48", "49", "54"], [R7_KI18, R8_KI17]),
    ("sochi", "332AC0000000026", ["2025-12-31", "2026-11-11", "2026-11-30", "2026-12-01", "2026-12-31", "2027-01-01"], ASOF_ALL,
     ["27", "29_4", "41_16_2"], [R7_LAW13, R8_LAW12]),
    ("tsusoku", "337AC0000000066", ["2026-11-11"], ["2026-11-09", "2027-01-01"], ["2", "5", "10", "11", "23", "74", "117", "118", "119"], []),
    ("tsusoku-rei", "337CO0000000135", ["2026-11-11"], ["2026-11-09", "2027-01-01"], ["2"], []),
    ("chiho", "325AC0000000226", ["2026-11-11"], ["2026-11-09", "2027-01-01"], ["9", "294", "318"], []),
    ("shukujitsu", "323AC1000000178", ["2026-11-11"], ["2026-11-09", "2027-01-01"], ["1", "2", "3"], []),
]
# 題名で law_id を引くもの（担当が取っていない。休日の決まらない点の手がかり）
EXTRA_TITLES = [("kenkoku-rei", "建国記念の日となる日を定める政令"), ("nenrei", "年齢計算ニ関スル法律")]

BLOCK_LIKE = {"Paragraph", "Item"} | {f"Subitem{i}" for i in range(1, 11)}


def get(url, accept="application/json"):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            body, st, hd = r.read(), r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        body, st, hd = e.read(), e.code, dict(e.headers or {})
    time.sleep(SLEEP)
    return st, body, hd


def new_dl(name):
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R3X_shibo-shukkoku_verify_{name}"
    dl.mkdir(parents=True, exist_ok=False)
    return ts, dl


def rel(p):
    return str(pathlib.Path(p).relative_to(ROOT)).replace("\\", "/")


# ---- テキスト化（scripts/IMPL_kyuyo_fetch.py の inline を写したもの） ----
def inline(n):
    if isinstance(n, str):
        return n
    if n.get("tag") in ("Rt",):
        return ""
    parts = [inline(c) for c in n.get("children", [])]
    if n.get("tag", "").endswith("Sentence") and any(isinstance(c, dict) and c.get("tag") == "Column" for c in n.get("children", [])):
        return "　".join(p for p in parts if p)
    return "".join(parts)


def walk(n, fn, path=()):
    if isinstance(n, dict):
        fn(n, path)
        for c in n.get("children", []):
            walk(c, fn, path + (n,))


def sentences_text(n):
    """節点の中の Sentence を文書の順に連結（表の行は「｜」で区切る）。"""
    out = []

    def rec(x):
        if isinstance(x, str):
            return
        t = x.get("tag", "")
        if t.endswith("Sentence"):
            out.append(inline(x))
            return
        if t == "TableRow":
            out.append("｜".join(inline(c) for c in x.get("children", []) if isinstance(c, dict)) + "｜／")
            return
        if t in ("ArticleCaption", "ParagraphCaption", "ArticleTitle", "ParagraphNum") or t.endswith(("Title",)):
            return
        for c in x.get("children", []):
            rec(c)
    rec(n)
    return "".join(out)


def struct_article(a, prefix):
    """条を「場所 → テキスト」の平らな辞書にする。場所は Art<Num>/P<Num>/I<Num>/S1_<Num>/S2_<Num>。"""
    flat = {}

    def rec(n, loc):
        flat[loc] = {"full": sentences_text(n),
                     "title": "".join(inline(c) for c in n.get("children", []) if isinstance(c, dict)
                                      and c.get("tag", "").endswith("Title") and c.get("tag") != "ParagraphCaption")}
        for c in n.get("children", []):
            if not isinstance(c, dict):
                continue
            t = c.get("tag", "")
            num = (c.get("attr") or {}).get("Num", "")
            if t == "Paragraph":
                rec(c, f"{loc}/P{num}")
            elif t == "Item":
                rec(c, f"{loc}/I{num}")
            elif re.fullmatch(r"Subitem\d+", t):
                rec(c, f"{loc}/S{t[7:]}_{num}")
            elif t in ("TableStruct", "Table", "List", "Sublist1", "Sublist2", "AmendProvision", "Class"):
                # 表・リストの中の節点はさらに潜る（Paragraph などがあれば拾う）
                rec_inside(c, loc)

    def rec_inside(c, loc):
        for x in c.get("children", []):
            if isinstance(x, dict):
                t = x.get("tag", "")
                num = (x.get("attr") or {}).get("Num", "")
                if t == "Item":
                    rec(x, f"{loc}/I{num}")
                elif re.fullmatch(r"Subitem\d+", t):
                    rec(x, f"{loc}/S{t[7:]}_{num}")
                else:
                    rec_inside(x, loc)
    num = (a.get("attr") or {}).get("Num")
    loc = f"{prefix}Art{num}"
    rec(a, loc)
    cap = ""
    for c in a.get("children", []):
        if isinstance(c, dict) and c.get("tag") == "ArticleCaption":
            cap = inline(c)
    flat[loc]["caption"] = cap
    return flat


def extract_law(d, nums, suppl_pats):
    root = d["law_full_text"]
    main_arts, suppls, hier = [], [], {}

    def collect(n, path):
        tags = [p.get("tag") for p in path]
        if n.get("tag") == "Article" and "SupplProvision" not in tags:
            main_arts.append(n)
            titles = []
            for p in path:
                for c in p.get("children", []):
                    if isinstance(c, dict) and c.get("tag") in ("PartTitle", "ChapterTitle", "SectionTitle", "SubsectionTitle", "DivisionTitle"):
                        titles.append(inline(c))
            hier[(n.get("attr") or {}).get("Num")] = titles
        if n.get("tag") == "SupplProvision":
            suppls.append(n)
    walk(root, collect)
    by_num = {(a.get("attr") or {}).get("Num"): a for a in main_arts}
    flat, missing = {}, []
    for num in nums:
        a = by_num.get(num)
        if a is None:
            missing.append(num)
            continue
        flat.update(struct_article(a, ""))
    suppl_found = {}
    for s in suppls:
        an = (s.get("attr") or {}).get("AmendLawNum") or ""
        for pat in suppl_pats:
            if re.match(pat, an):
                key = "Suppl[" + an + "]/"
                arts = []
                walk(s, lambda n, p: arts.append(n) if n.get("tag") == "Article" else None)
                for a in arts:
                    flat.update(struct_article(a, key))
                # 条のない附則（項だけ）
                if not arts:
                    flat[key + "Body"] = {"full": sentences_text(s), "title": ""}
                suppl_found[an] = len(arts)
    return flat, missing, suppl_found, {k: hier.get(k) for k in nums}, len(main_arts)


def mode_fetch_egov():
    ts, dl = new_dl("egov")
    EXC.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": rel(dl), "versions": [], "fetches": [], "revisions": [], "titles": [], "errors": []}
    # 1. 版の ID（/laws?law_id&asof）
    for short, law_id, _, asofs_meta, _, _ in EGOV:
        for asof in asofs_meta:
            q = urllib.parse.urlencode({"law_id": law_id, "asof": asof, "response_format": "json"})
            url = f"{API}/laws?{q}"
            st, body, _ = get(url)
            fn = dl / f"laws_{short}_{asof}.json"
            fn.write_bytes(body)
            rec = {"short": short, "law_id": law_id, "asof": asof, "url": url, "status": st, "sha256": hashlib.sha256(body).hexdigest()}
            if st == 200:
                laws = json.loads(body).get("laws", [])
                rec["n"] = len(laws)
                if laws:
                    ri = laws[0].get("revision_info") or {}
                    for k in ("law_revision_id", "amendment_law_num", "amendment_enforcement_date", "current_revision_status", "law_title"):
                        rec[k] = ri.get(k)
            log["versions"].append(rec)
            print("ver", short, asof, st, rec.get("law_revision_id"), rec.get("current_revision_status"), flush=True)
    # 2. 改正履歴
    for short, law_id, *_ in EGOV:
        url = f"{API}/law_revisions/{law_id}?" + urllib.parse.urlencode({"response_format": "json"})
        st, body, _ = get(url)
        (dl / f"revisions_{short}.json").write_bytes(body)
        revs = []
        if st == 200:
            for rv in json.loads(body).get("revisions", []):
                d0 = rv.get("amendment_enforcement_date") or rv.get("amendment_scheduled_enforcement_date") or ""
                if d0 >= "2025-01-01" or not d0:
                    revs.append({k: rv.get(k) for k in ("law_revision_id", "amendment_law_num", "amendment_law_title", "amendment_promulgate_date",
                                                       "amendment_enforcement_date", "amendment_scheduled_enforcement_date", "current_revision_status")})
        (EXC / f"revisions_{short}.json").write_text(json.dumps({"url": url, "status": st, "revisions_since_2025": revs}, ensure_ascii=False, indent=1), encoding="utf-8")
        log["revisions"].append({"short": short, "url": url, "status": st, "n_since_2025": len(revs), "sha256": hashlib.sha256(body).hexdigest()})
        print("rev", short, st, len(revs), flush=True)
    # 3. 題名で引く法令
    for short, title in EXTRA_TITLES:
        q = urllib.parse.urlencode({"law_title": title, "response_format": "json", "asof": "2026-11-11"})
        st, body, _ = get(f"{API}/laws?{q}")
        (dl / f"title_{short}.json").write_bytes(body)
        hits = []
        if st == 200:
            for law in json.loads(body).get("laws", []):
                ri = law.get("revision_info") or law.get("current_revision_info") or {}
                hits.append({"law_id": law["law_info"]["law_id"], "law_num": law["law_info"].get("law_num"), "title": ri.get("law_title")})
        log["titles"].append({"short": short, "title": title, "status": st, "hits": hits})
        print("title", short, hits, flush=True)
        exact = [h for h in hits if h["title"] == title]
        if exact:
            law_id = exact[0]["law_id"]
            url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": "2026-11-11"})
            st, body, _ = get(url)
            (dl / f"{short}_2026-11-11.json").write_bytes(body)
            if st == 200:
                d = json.loads(body)
                ri = d.get("revision_info") or {}
                txt = sentences_text(d["law_full_text"])
                (EXC / f"{short}_2026-11-11.json").write_text(json.dumps({"law_id": law_id, "law_revision_id": ri.get("law_revision_id"),
                                                                          "url": url, "sha256": hashlib.sha256(body).hexdigest(),
                                                                          "full_text": txt}, ensure_ascii=False, indent=1), encoding="utf-8")
                log["fetches"].append({"short": short, "law_id": law_id, "asof": "2026-11-11", "url": url, "status": st,
                                       "law_revision_id": ri.get("law_revision_id"), "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)})
    # 4. 本文
    for short, law_id, asofs, _, nums, pats in EGOV:
        for asof in asofs:
            url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
            try:
                st, body, _ = get(url)
            except Exception as e:  # noqa
                log["errors"].append({"short": short, "asof": asof, "error": repr(e)})
                print("ERR", short, asof, repr(e), flush=True)
                continue
            fn = dl / f"{short}_{asof}.json"
            fn.write_bytes(body)
            rec = {"short": short, "law_id": law_id, "asof": asof, "url": url, "status": st, "bytes": len(body),
                   "sha256": hashlib.sha256(body).hexdigest(), "saved": rel(fn)}
            if st != 200:
                log["errors"].append(rec)
                continue
            d = json.loads(body)
            ri = d.get("revision_info") or {}
            for k in ("law_revision_id", "amendment_law_num", "amendment_law_title", "amendment_enforcement_date", "current_revision_status", "updated"):
                rec[k] = ri.get(k)
            flat, missing, suppl_found, hier, n_main = extract_law(d, nums, pats)
            rec.update({"missing": missing, "suppl_found": suppl_found, "n_main_articles": n_main})
            (EXC / f"{short}_{asof}.json").write_text(json.dumps({"meta": rec, "hier": hier, "flat": flat}, ensure_ascii=False, indent=1), encoding="utf-8")
            log["fetches"].append(rec)
            print("ok", short, asof, ri.get("law_revision_id"), "missing", missing, "suppl", suppl_found, flush=True)
    (OUT / "fetch_egov.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done errors", len(log["errors"]))


def mode_extract(dl_arg):
    """fetch-egov で保存した生の JSON（信頼できないデータ）をパスで受け取り、excerpts/ を作り直す（ネットワークに出ない）。
    取り出しの手順を直したときに、取り直さずに同じ生データから作り直すため。"""
    dl = (ROOT / dl_arg).resolve()
    fe = json.loads((OUT / "fetch_egov.json").read_text(encoding="utf-8"))
    by = {(f["short"], f["asof"]): f for f in fe["fetches"]}
    for short, law_id, asofs, _, nums, pats in EGOV:
        for asof in asofs:
            fn = dl / f"{short}_{asof}.json"
            body = fn.read_bytes()
            sha = hashlib.sha256(body).hexdigest()
            rec = dict(by[(short, asof)])
            if sha != rec["sha256"]:
                raise SystemExit(f"SHA-256 が取得の記録と違う：{fn}")
            d = json.loads(body)
            flat, missing, suppl_found, hier, n_main = extract_law(d, nums, pats)
            (EXC / f"{short}_{asof}.json").write_text(json.dumps({"meta": rec, "hier": hier, "flat": flat}, ensure_ascii=False, indent=1), encoding="utf-8")
            print("re-extract", short, asof, len(flat), flush=True)


# ---------------------------------------------------------------- 国税庁
NTA = "https://www.nta.go.jp"
TA = NTA + "/taxes/shiraberu/taxanswer/shotoku/"
KIHON = NTA + "/law/tsutatsu/kihon/shotoku/"
ANNAI = NTA + "/taxes/tetsuzuki/shinsei/annai/shinkoku/annai/"
WEB_MAIN = {
    "ta_2022": TA + "2022.htm", "ta_1920": TA + "1920.htm", "ta_1923": TA + "1923.htm", "ta_1110": TA + "1110.htm",
    "kihon_19_02": KIHON + "19/02.htm", "kihon_16_06": KIHON + "16/06.htm", "kihon_15_01": KIHON + "15/01.htm",
    "kihon_16_01": KIHON + "16/01.htm", "kihon_01_01": KIHON + "01/01.htm", "kihon_19_01": KIHON + "19/01.htm",
    "shitsugi_07_15": NTA + "/law/shitsugi/shotoku/07/15.htm",
    "jyunkaku_index": NTA + "/taxes/shiraberu/shinkoku/jyunkaku/index.htm",
    "annai_07": ANNAI + "07.htm", "annai_23200032": ANNAI + "23200032.htm", "annai_1557_2": ANNAI + "1557_2.htm",
    "tsutatsu_menu": NTA + "/law/tsutatsu/menu.htm",
    "pdf_fuhyo": NTA + "/taxes/shiraberu/shinkoku/yoshiki/01/fuhyo/f01-yoshiki.pdf",
    "pdf_fuhyo_kakikata": NTA + "/taxes/shiraberu/shinkoku/yoshiki/01/fuhyo/f01.pdf",
    "pdf_ininjo": NTA + "/taxes/shiraberu/shinkoku/yoshiki/01/fuhyo/f01-3.pdf",
    "pdf_r8qa": NTA + "/users/gensen/2026kiso/pdf/0026005-024.pdf",
    "pdf_r7qa": NTA + "/publication/pamph/gensen/0025005-051.pdf",
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
        if tag == "img" and a.get("alt") and not self.skip:
            self.parts.append(f"〔alt:{a['alt']}〕")
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
            return body.decode("cp932" if e.lower() in ("shift_jis", "sjis", "x-sjis") else e)
        except (UnicodeDecodeError, LookupError):
            continue
    return body.decode("utf-8", "replace")


def robots_for(host, urls, dl):
    st, body, _ = get(f"https://{host}/robots.txt", accept="text/plain")
    (dl / f"robots_{host}.txt").write_bytes(body)
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(body.decode("utf-8", "replace").splitlines() if st == 200 else [])
    return {"status": st, "sha256": hashlib.sha256(body).hexdigest(),
            "allowed": {u: rp.can_fetch(UA, u) for u in urls}}


def mode_fetch_web(args):
    group = args[0] if args else "main"
    if group == "main":
        items = dict(WEB_MAIN)
    else:
        items = dict(a.split("=", 1) for a in args[1:])
    ts, dl = new_dl("web-" + group)
    (EXC / "web").mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "group": group, "download_dir": rel(dl), "robots": {}, "items": []}
    hosts = sorted({urllib.parse.urlparse(u).netloc for u in items.values()})
    for h in hosts:
        log["robots"][h] = robots_for(h, [u for u in items.values() if urllib.parse.urlparse(u).netloc == h], dl)
    for key, url in items.items():
        host = urllib.parse.urlparse(url).netloc
        if not log["robots"][host]["allowed"].get(url, False):
            log["items"].append({"id": key, "url": url, "skipped": "robots"})
            print("skip robots", key, flush=True)
            continue
        st, body, hd = get(url, accept="*/*")
        ctype = hd.get("Content-Type", "")
        is_pdf = body[:5] == b"%PDF-"
        fn = dl / (key + (".pdf" if is_pdf else ".htm"))
        fn.write_bytes(body)
        item = {"id": key, "url": url, "status": st, "content_type": ctype, "last_modified": hd.get("Last-Modified"),
                "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(), "saved": rel(fn), "is_pdf": is_pdf}
        if not is_pdf and st == 200:
            text = decode(body, ctype)
            p = Page(url)
            p.feed(text)
            m = re.search(r"<title>(.*?)</title>", text, re.S)
            item["title"] = re.sub(r"\s+", " ", m.group(1)).strip() if m else None
            (EXC / "web" / f"{key}.txt").write_text(f"# source={url}\n# fetched_at={ts}\n# last_modified={hd.get('Last-Modified')}\n"
                                                     f"# sha256={item['sha256']}\n\n{p.text()}\n", encoding="utf-8")
            (EXC / "web" / f"{key}.links.json").write_text(json.dumps(p.links, ensure_ascii=False, indent=1), encoding="utf-8")
        log["items"].append(item)
        print("ok", key, st, len(body), item.get("last_modified"), item.get("title"), flush=True)
    prev = OUT / "fetch_web.json"
    allv = json.loads(prev.read_text(encoding="utf-8")) if prev.exists() else []
    allv.append(log)
    prev.write_text(json.dumps(allv, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- 担当の取得物のハッシュ
def mode_prior_hashes():
    res = {"files": {}, "doc_hashes": []}
    for d in sorted((ROOT / ".work" / "downloads").glob("*_R3X_shibo-shukkoku_*")):
        if "_verify_" in d.name:
            continue
        for f in sorted(d.iterdir()):
            if f.is_file():
                res["files"][rel(f)] = hashlib.sha256(f.read_bytes()).hexdigest()
    allh = set(res["files"].values())
    mtxt = DOCS["M"].read_text(encoding="utf-8")
    for m in re.finditer(r"`([0-9a-f]{8})…([0-9a-f]{5,6})`|`([0-9a-f]{64})`", mtxt):
        if m.group(3):
            h = m.group(3)
            hit = [k for k, v in res["files"].items() if v == h]
        else:
            hit = [k for k, v in res["files"].items() if v.startswith(m.group(1)) and v.endswith(m.group(2))]
        line = mtxt[:m.start()].count("\n") + 1
        res["doc_hashes"].append({"line": line, "hash": m.group(0), "files": hit})
    res["summary"] = {"n_files": len(res["files"]), "n_doc_hashes": len(res["doc_hashes"]),
                      "n_doc_hashes_matched": sum(1 for x in res["doc_hashes"] if x["files"])}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "prior_hashes.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(res["summary"])
    for x in res["doc_hashes"]:
        if not x["files"]:
            print("unmatched", x)


# ---------------------------------------------------------------- 検査の道具
def norm(s):
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s+", "", s)
    for a in "‐-−–—―ー－":
        pass
    s = re.sub(r"[‐\-−–—―－]", "-", s)
    return s


def frags_in_order(text, quote):
    """引用を「…」で区切った断片が、順に text に含まれるか。"""
    t = norm(text)
    parts = [norm(p) for p in re.split(r"…+|・・・", quote)]
    parts = [p.strip("「」") for p in parts if p.strip("「」")]
    pos = 0
    for p in parts:
        i = t.find(p, pos)
        if i < 0:
            return False, p
        pos = i + len(p)
    return True, None


class Laws:
    def __init__(self):
        self.d = {}
        for f in EXC.glob("*.json"):
            if f.name.startswith(("revisions_", "kenkoku", "nenrei")):
                continue
            j = json.loads(f.read_text(encoding="utf-8"))
            if "flat" in j:
                self.d[f.stem] = j

    def versions(self, short):
        return sorted(k.split("_", 1)[1] for k in self.d if k.split("_", 1)[0] == short)

    def node(self, short, asof, loc):
        j = self.d.get(f"{short}_{asof}")
        if not j:
            return None
        n = j["flat"].get(loc)
        return n["full"] if n else None

    def meta(self, short, asof):
        return self.d[f"{short}_{asof}"]["meta"]


def web_text(pid):
    f = EXC / "web" / f"{pid}.txt"
    return f.read_text(encoding="utf-8") if f.exists() else None


def web_section(pid, start_pat, end_pat=None):
    t = web_text(pid)
    if t is None:
        return None
    nt = norm(t)
    m = re.search(norm(start_pat) if not start_pat.startswith("re:") else start_pat[3:], nt)
    if not m:
        return None
    rest = nt[m.start():]
    if end_pat:
        m2 = re.search(end_pat, rest[len(m.group(0)):])
        if m2:
            rest = rest[: len(m.group(0)) + m2.start()]
    return rest


# ---------------------------------------------------------------- 休日・期限・年齢（独自の実装）
def nth_monday(y, m, n):
    d = dt.date(y, m, 1)
    off = (0 - d.weekday()) % 7
    return d + dt.timedelta(days=off + 7 * (n - 1))


def national_holidays(y, equinox):
    """祝日法2 の表（2020-01-01 の版）から作る。春分日・秋分日は equinox[(y,'spring'|'autumn')]、無ければ None（決まらない）。
    建国記念の日は政令の値（2月11日）を引数で渡す前提（kenkoku_day）。"""
    h = {dt.date(y, 1, 1): "元日", nth_monday(y, 1, 2): "成人の日", dt.date(y, 2, 23): "天皇誕生日",
         dt.date(y, 4, 29): "昭和の日", dt.date(y, 5, 3): "憲法記念日", dt.date(y, 5, 4): "みどりの日", dt.date(y, 5, 5): "こどもの日",
         nth_monday(y, 7, 3): "海の日", dt.date(y, 8, 11): "山の日", nth_monday(y, 9, 3): "敬老の日",
         nth_monday(y, 10, 2): "スポーツの日", dt.date(y, 11, 3): "文化の日", dt.date(y, 11, 23): "勤労感謝の日"}
    unknown = []
    for key, name in (("kenkoku", "建国記念の日"), ("spring", "春分の日"), ("autumn", "秋分の日")):
        v = equinox.get((y, key))
        if v is None:
            unknown.append(name)
        else:
            h[v] = name
    return h, unknown


def holiday_info(d, equinox, ippan):
    """d が通則法10②の休日等か。戻り値 True/False/None（決まらない）と理由。
    ippan：「その他一般の休日」に当たる日の集合を返す関数か None（決まらない）。"""
    if d.weekday() == 6:
        return True, "日曜日"
    if d.weekday() == 5:
        return True, "土曜日（通則令2②）"
    if d.month == 12 and d.day in (29, 30, 31):
        return True, "12月29〜31日（通則令2②）"
    y = d.year
    hol, unknown = national_holidays(y, equinox)
    # 振替休日（祝日法3②）と国民の休日（3③）
    alls = dict(hol)
    for x, nm in sorted(hol.items()):
        if x.weekday() == 6:
            z = x + dt.timedelta(days=1)
            while z in hol:
                z += dt.timedelta(days=1)
            alls.setdefault(z, "振替休日")
    for x in list(hol):
        z = x + dt.timedelta(days=2)
        mid = x + dt.timedelta(days=1)
        if z in hol and mid not in hol:
            alls.setdefault(mid, "国民の休日")
    if d in alls:
        return True, alls[d]
    if unknown:
        # 決まらない祝日がある月（建国記念の日＝2月、春分＝3月、秋分＝9月）にかかるときは決まらない
        months = {"建国記念の日": 2, "春分の日": 3, "秋分の日": 9}
        if any(months[u] == d.month for u in unknown):
            return None, "決まらない（" + "・".join(u for u in unknown if months[u] == d.month) + "の日付が未取得）"
    if ippan is None:
        if d.month == 1 and d.day in (2, 3):
            return None, "決まらない（1月2日・3日が「その他一般の休日」か未確認）"
        return False, "平日"
    if d in ippan(y):
        return True, "その他一般の休日"
    return False, "平日"


def add_months_end(start, months):
    """通則法10①二・三：start を起算日とする months 月の期間の満了日（最後の月の起算日に応当する日の前日。応当日が無ければ月末）。"""
    y, m = start.year, start.month + months
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    import calendar
    last = calendar.monthrange(y, m)[1]
    if start.day > last:
        return dt.date(y, m, last)
    return dt.date(y, m, start.day) - dt.timedelta(days=1)


def roll_forward(d, equinox, ippan):
    cur = d
    for _ in range(20):
        h, why = holiday_info(cur, equinox, ippan)
        if h is None:
            return None, f"{cur} {why}"
        if not h:
            return cur, None
        cur += dt.timedelta(days=1)
    return None, "too many"


def deadline_shibo(knew, equinox, ippan, reading="A"):
    """所法125①：知った日の翌日から四月を経過した日の前日。読みA＝翌日を起算日とする4月の期間の満了日、読みB＝その前日。"""
    end = add_months_end(knew + dt.timedelta(days=1), 4)
    if reading == "B":
        end -= dt.timedelta(days=1)
    return end


def age_on(birth, on):
    """年齢計算ニ関スル法律・民法143：誕生日の前日の終了で1歳加わる（＝on が誕生日の前日以後なら加算）。"""
    a = on.year - birth.year
    try:
        bday_this = dt.date(on.year, birth.month, birth.day)
    except ValueError:
        bday_this = dt.date(on.year, 3, 1)
    if on < bday_this - dt.timedelta(days=1):
        a -= 1
    return a


def tax89(taxable):
    """所法89① の速算（課税総所得金額は1,000円未満切捨て後）。表の値は検査で条文と照らす。"""
    brackets = [(1950000, Fraction(5, 100), 0), (3300000, Fraction(10, 100), 97500), (6950000, Fraction(20, 100), 427500),
                (9000000, Fraction(23, 100), 636000), (18000000, Fraction(33, 100), 1536000), (40000000, Fraction(40, 100), 2796000),
                (None, Fraction(45, 100), 4796000)]
    for lim, r, sub in brackets:
        if lim is None or taxable <= lim:
            return taxable * r - sub


def tax_by_bracket(taxable):
    """速算表を使わない計算（段ごとに税率を掛けて足す）。tax89 の検算用。"""
    edges = [(1950000, Fraction(5, 100)), (3300000, Fraction(10, 100)), (6950000, Fraction(20, 100)), (9000000, Fraction(23, 100)),
             (18000000, Fraction(33, 100)), (40000000, Fraction(40, 100)), (10 ** 15, Fraction(45, 100))]
    t, lo = Fraction(0), 0
    for hi, r in edges:
        if taxable > lo:
            t += (min(taxable, hi) - lo) * r
        lo = hi
    return t


def kurimodoshi(prev_taxable, loss):
    a = prev_taxable // 1000 * 1000
    t1 = int(tax_by_bracket(a)) // 100 * 100
    b = max(0, a - loss) // 1000 * 1000
    t2 = int(tax_by_bracket(b)) // 100 * 100
    return t1, t2, t1 - t2


# ---------------------------------------------------------------- 検査の本体
RESULTS = []


def rec(cid, doc, claim, ok, detail="", kind="check"):
    RESULTS.append({"id": cid, "doc": doc, "claim": claim, "result": ok, "detail": detail, "kind": kind})


KANJI = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def kanji_num(s):
    total, cur = 0, 0
    for ch in s:
        if ch == "十":
            total += (cur or 1) * 10
            cur = 0
        elif ch == "百":
            total += (cur or 1) * 100
            cur = 0
        else:
            cur = KANJI[ch]
    return total + cur


CIRC = {c: i + 1 for i, c in enumerate("①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳")}
IROHA = "イロハニホヘトチリヌルヲワカヨタレソツネナラムウヰノオクヤマケフコエテアサキユメミシヱヒモセス"
LAWABBR = {"所法": "shotoku", "所令": "shotoku-rei", "所規": "shotoku-ki", "措法": "sochi", "通則法": "tsusoku", "通則令": "tsusoku-rei",
           "地法": "chiho", "祝日法": "shukujitsu"}
CIT_RE = re.compile(r"(所法|所令|所規|措法|通則法|通則令|地法|祝日法)(\d+(?:の\d+)*)((?:[①-⑳](?:[一二三四五六七八九十百]+(?:の[一二三四五六七八九十]+)?)?)*)")


def parse_cit(m):
    law = LAWABBR[m.group(1)]
    art = m.group(2).replace("の", "_")
    rest = m.group(3)
    paras = re.findall(r"([①-⑳])([一二三四五六七八九十百]+(?:の[一二三四五六七八九十]+)?)?", rest)
    if not paras:
        return law, f"Art{art}", None
    p, it = paras[0]
    loc = f"Art{art}/P{CIRC[p]}"
    if it:
        parts = it.split("の")
        loc += "/I" + "_".join(str(kanji_num(x)) for x in parts)
    return law, loc, None


def quotes_in(line):
    """行の中の「」（入れ子を考える）を (開始位置, 中身) で返す。"""
    out, depth, start = [], 0, None
    for i, ch in enumerate(line):
        if ch == "「":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "」" and depth:
            depth -= 1
            if depth == 0:
                out.append((start, line[start + 1:i]))
    return out


def auto_quotes(L, docname):
    """文書の各行の引用について、直前の条の引用（所法125① など）から場所を推定し、その場所（項・号）の中に断片が順に含まれるかを見る。
    場所が推定できない・場所に無い引用は、その法令の取り出した全部の条で探す。どの版にあったかも記録する。"""
    text = DOCS[docname].read_text(encoding="utf-8")
    res = []
    for ln, line in enumerate(text.splitlines(), 1):
        qs = quotes_in(line)
        if not qs:
            continue
        cits = [(m.start(), m) for m in CIT_RE.finditer(line)]
        for pos, q in qs:
            if len(norm(q)) < 6:
                continue
            prev = [m for s, m in cits if s < pos]
            entry = {"line": ln, "quote": q[:80] + ("…" if len(q) > 80 else ""), "cit": None, "at_loc": None, "anywhere": None}
            if prev:
                m = prev[-1]
                law, loc, _ = parse_cit(m)
                entry["cit"] = m.group(0)
                # 引用の直前に「②」「一」だけが書かれていれば、その項・号に読み替える
                between = line[m.end():pos]
                m2 = re.search(r"([①-⑳])\s*(?:[（(][^）)]*[）)])?\s*[：:]?\s*$", between)
                m3 = re.search(r"(?:^|[、。）\s])([一二三四五六七八九十]+(?:の[一二三四五六七八九十]+)?)\s*$", between)
                if m2 and "/P" in loc:
                    loc = loc.split("/P")[0] + f"/P{CIRC[m2.group(1)]}"
                elif m2:
                    loc = loc + f"/P{CIRC[m2.group(1)]}"
                if m3 and "/P" in loc:
                    loc = re.sub(r"/I[\d_]+$", "", loc) + "/I" + "_".join(str(kanji_num(x)) for x in m3.group(1).split("の"))
                found = []
                for asof in L.versions(law):
                    t = L.node(law, asof, loc)
                    if t is not None and frags_in_order(t, q)[0]:
                        found.append(asof)
                entry["loc"] = f"{law}:{loc}"
                entry["at_loc"] = found
                if not found:
                    any_found = []
                    for asof in L.versions(law):
                        j = L.d[f"{law}_{asof}"]["flat"]
                        for k, v in j.items():
                            if "/" in k.split("Art", 1)[-1]:
                                continue  # 条の全体だけで探す
                            if frags_in_order(v["full"], q)[0]:
                                any_found.append(f"{asof}:{k}")
                    entry["anywhere"] = any_found[:6]
            if not entry["at_loc"]:
                # 法令のすべての取り出し（条・附則の条）と、国税庁などの HTML のテキストで探す
                hits = []
                for key, j in L.d.items():
                    for k, v in j["flat"].items():
                        if "/" in k.split("Art", 1)[-1]:
                            continue
                        if frags_in_order(v["full"], q)[0]:
                            hits.append(f"{key}:{k}")
                webhits = [f.stem for f in sorted((EXC / "web").glob("*.txt")) if frags_in_order(f.read_text(encoding="utf-8"), q)[0]]
                entry["all_laws"] = hits[:8]
                entry["web"] = webhits
            res.append(entry)
    return res


def run_checks():
    L = Laws()
    out = {}

    # ---- 1. 版の ID（［PS］§0.1・［M］§2.1）
    fe = json.loads((OUT / "fetch_egov.json").read_text(encoding="utf-8"))
    claimed = {
        ("shotoku", "2025-12-31"): "340AC0000000033_20251218_507AC0000000013", ("shotoku", "2026-11-09"): "340AC0000000033_20261001_507AC0000000070",
        ("shotoku", "2026-11-30"): "340AC0000000033_20261001_507AC0000000070", ("shotoku", "2026-12-01"): "340AC0000000033_20261201_508AC0000000012",
        ("shotoku", "2026-12-31"): "340AC0000000033_20261201_508AC0000000012", ("shotoku", "2027-01-01"): "340AC0000000033_20270101_508AC0000000012",
        ("shotoku-rei", "2025-12-31"): "340CO0000000096_20251201_507CO0000000120", ("shotoku-rei", "2026-11-09"): "340CO0000000096_20260522_508CO0000000093",
        ("shotoku-rei", "2026-12-31"): "340CO0000000096_20261201_508CO0000000093", ("shotoku-rei", "2027-01-01"): "340CO0000000096_20270101_508CO0000000093",
        ("shotoku-ki", "2025-12-31"): "340M50000040011_20251201_507M60000040018", ("shotoku-ki", "2026-11-09"): "340M50000040011_20261001_507M60000040018",
        ("shotoku-ki", "2026-12-31"): "340M50000040011_20261211_508M60000040017", ("shotoku-ki", "2027-01-01"): "340M50000040011_20270101_508M60000040017",
        ("sochi", "2025-12-31"): "332AC0000000026_20251231_507AC1000000081", ("sochi", "2026-11-09"): "332AC0000000026_20261101_507AC0000000013",
        ("sochi", "2026-11-30"): "332AC0000000026_20261126_508AC0000000012", ("sochi", "2026-12-01"): "332AC0000000026_20261201_508AC0000000012",
        ("sochi", "2026-12-31"): "332AC0000000026_20261204_508AC0000000012", ("sochi", "2027-01-01"): "332AC0000000026_20270101_508AC0000000012",
        ("tsusoku", "2026-11-09"): "337AC0000000066_20261101_507AC0000000013", ("tsusoku", "2027-01-01"): "337AC0000000066_20261101_507AC0000000013",
        ("tsusoku-rei", "2026-11-09"): "337CO0000000135_20260401_507CO0000000126", ("tsusoku-rei", "2027-01-01"): "337CO0000000135_20260401_507CO0000000126",
        ("chiho", "2026-11-09"): "325AC0000000226_20261101_508AC0000000002", ("chiho", "2027-01-01"): "325AC0000000226_20270101_508AC0000000002",
        ("shukujitsu", "2026-11-09"): "323AC1000000178_20200101_430AC1000000057", ("shukujitsu", "2027-01-01"): "323AC1000000178_20200101_430AC1000000057",
    }
    got = {(v["short"], v["asof"]): v for v in fe["versions"]}
    full = {(f["short"], f["asof"]): f for f in fe["fetches"]}
    for k, want in claimed.items():
        # 本文（/law_data）を同じ asof で取ったときはその版 ID を正とする。/laws の revision_info は同じ施行日に複数の版があると別の版を返すことがある
        g = full.get(k) or got.get(k, {})
        src = "/law_data" if k in full else "/laws"
        gl = got.get(k, {})
        extra = "" if gl.get("law_revision_id") in (None, g.get("law_revision_id")) else f"（/laws の revision_info は {gl.get('law_revision_id')}）"
        rec(f"V-{k[0]}-{k[1]}", "PS§0.1/M§2.1", f"{k[0]} asof {k[1]} の版 = {want}", g.get("law_revision_id") == want,
            f"取得（{src}）：{g.get('law_revision_id')}（{g.get('current_revision_status')}、施行日 {g.get('amendment_enforcement_date')}、改正法令 {g.get('amendment_law_num')}）{extra}")
    # 本文を取った版の ID
    for f in fe["fetches"]:
        rec(f"VF-{f['short']}-{f['asof']}", "M§2.1", f"本文 {f['short']} asof {f['asof']}", True,
            f"{f.get('law_revision_id')} {f.get('current_revision_status')} 施行日 {f.get('amendment_enforcement_date')} 改正法令 {f.get('amendment_law_num')} "
            f"SHA-256 {f.get('sha256', '')[:16]}… bytes {f.get('bytes')} missing {f.get('missing')} 附則 {f.get('suppl_found')}", kind="info")

    # ---- 2. 時点の間で本文が違う条（［PS］§0.1・［M］§3.1）
    def art_text(short, asof, num):
        j = L.d.get(f"{short}_{asof}")
        if not j:
            return None
        parts = [v["full"] for k, v in j["flat"].items() if k == f"Art{num}"]
        return parts[0] if parts else None
    diff_claim = {"shotoku": {"2", "120", "122", "123", "125", "127", "166"}, "shotoku-ki": {"47", "48"}, "sochi": {"41_16_2"}, "shotoku-rei": set()}
    same_claim = {
        "shotoku": ["3", "69", "70", "70_2", "71", "71_2", "72", "85", "87", "89", "102", "115", "121", "124", "126", "128", "129", "130", "131",
                    "138", "139", "140", "141", "142", "165"],
        "shotoku-rei": ["14", "15", "201", "204", "204_2", "206", "258", "263", "267", "271", "272", "273"],
        "shotoku-ki": ["49", "54"],
    }
    vers = {"shotoku": ["2025-12-31", "2026-11-11", "2026-12-01", "2027-01-01"], "shotoku-rei": ["2025-12-31", "2026-11-11", "2026-12-01", "2027-01-01"],
            "shotoku-ki": ["2025-12-31", "2026-11-11", "2026-12-31", "2027-01-01"],
            "sochi": ["2025-12-31", "2026-11-11", "2026-11-30", "2026-12-01", "2026-12-31", "2027-01-01"]}
    for short, nums in same_claim.items():
        for num in nums:
            ts = [art_text(short, a, num) for a in vers[short]]
            groups = []
            for a, t in zip(vers[short], ts):
                for g in groups:
                    if g[1] == t:
                        g[0].append(a)
                        break
                else:
                    groups.append(([a], t))
            rec(f"SAME-{short}-{num}", "PS§0.1/M§3.1", f"{short} 第{num}条は取得したすべての時点で同文", len(groups) == 1 and ts[0] is not None,
                " ｜ ".join("=".join(g[0]) for g in groups))
    for short, nums in diff_claim.items():
        for num in sorted(nums, key=lambda x: [int(y) for y in x.split("_")]):
            ts = [art_text(short, a, num) for a in vers[short]]
            groups = []
            for a, t in zip(vers[short], ts):
                for g in groups:
                    if g[1] == t:
                        g[0].append(a)
                        break
                else:
                    groups.append(([a], t))
            rec(f"DIFF-{short}-{num}", "PS§0.1/M§3.1", f"{short} 第{num}条は時点で本文が違う", len(groups) > 1, " ｜ ".join("=".join(g[0]) for g in groups))

    # ---- 3. 編・章・節・款（［M］§3.3）
    j = L.d["shotoku_2026-11-11"]
    for num in ["120", "123", "124", "127", "128", "130", "131", "138", "142"]:
        rec(f"HIER-{num}", "M§3.3", f"所法{num} の所属", True, " / ".join(j["hier"].get(num) or []), kind="info")
    h124 = j["hier"].get("124") or []
    rec("HIER-124-127", "M§3.3", "第124条〜第127条は第二款「死亡又は出国の場合の確定申告」",
        all(any("第二款" in x and "死亡又は出国の場合の確定申告" in x for x in (j["hier"].get(n) or [])) for n in ["124", "125", "126", "127"]),
        " / ".join(h124))

    # ---- 4. 引用の自動照合（［PS］［H］）
    for dn in ("PS", "H", "M"):
        aq = auto_quotes(L, dn)
        out[f"auto_quotes_{dn}"] = aq
    return L, out


def main_check():
    L, out = run_checks()
    import importlib  # noqa
    # 個別の検査は check_specific（下）で足す
    check_specific(L)
    res = {"results": RESULTS, **out}
    (OUT / "checks.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["# R3X_shibo-shukkoku_verify checks", "", "| ID | 文書 | 主張 | 結果 | 詳細 |", "|---|---|---|---|---|"]
    for r in RESULTS:
        st = "INFO" if r["kind"] == "info" else ("OK" if r["result"] is True else ("NG" if r["result"] is False else str(r["result"])))
        lines.append(f"| {r['id']} | {r['doc']} | {r['claim']} | {st} | {r['detail']} |")
    for dn in ("PS", "H", "M"):
        aq = out[f"auto_quotes_{dn}"]
        lines += ["", f"## 引用の自動照合（{dn}）", "", "| 行 | 直前の条 | 推定した場所 | その場所で見つかった版 | 場所に無いとき条の全体で見つかった所 | 引用（先頭80字） |", "|---|---|---|---|---|---|"]
        for e in aq:
            lines.append(f"| {e['line']} | {e['cit']} | {e.get('loc')} | {','.join(e['at_loc']) if e['at_loc'] else ('—' if e['at_loc'] is None else 'なし')} | "
                         f"{'; '.join(e['anywhere']) if e['anywhere'] else ('' if e['anywhere'] is None else 'なし')} | {e['quote']} |")
    (OUT / "checks.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    n_ng = sum(1 for r in RESULTS if r["kind"] != "info" and r["result"] is False)
    print("checks", len(RESULTS), "NG", n_ng)


R7L = "Suppl[令和七年三月三一日法律第一三号]/"
R8L = "Suppl[令和八年三月三一日法律第一二号]/"
R7R = "Suppl[令和七年三月三一日政令第一二〇号]/"
R8R = "Suppl[令和八年三月三一日政令第九三号]/"


def check_specific(L):
    def lawq(cid, doc, claim, short, loc, quote, versions=None, expect=True):
        """場所 loc（Art.../P.../I...）のテキストに quote（…で区切った断片）が順に含まれるかを、指定した版（既定は全部）で見る。
        expect=False のときは「含まれない」ことを見る。"""
        vs = versions or L.versions(short)
        got = {}
        for v in vs:
            t = L.node(short, v, loc)
            got[v] = None if t is None else frags_in_order(t, quote)[0]
        if expect:
            ok = all(got[v] is True for v in vs)
        else:
            ok = all(got[v] is False for v in vs)
        rec(cid, doc, claim, ok, f"{short}:{loc} " + " ".join(f"{v}={'有' if g else ('無' if g is False else '場所なし')}" for v, g in got.items()))

    def webq(cid, doc, claim, page, quote, start=None, expect=True):
        t = web_text(page)
        if t is None:
            rec(cid, doc, claim, None, f"{page} 未取得")
            return
        if start:
            # 行頭が start（通達番号）の行から、次に行頭が通達番号（「数字－数字」の形）の行の前までを節とする
            lines = t.splitlines()
            head = re.compile(r"^\d+(?:の\d+)?(?:・\d+)?(?:から\d+の\d+)?[－-]\d+(?:の\d+)?[\s　]")
            idx = [k for k, ln in enumerate(lines) if ln.startswith(start)]
            if not idx:
                rec(cid, doc, claim, False, f"{page}：見出し {start} が見つからない")
                return
            k0 = idx[0]
            k1 = next((k for k in range(k0 + 1, len(lines)) if head.match(lines[k])), len(lines))
            sect = "\n".join(lines[k0:k1])
            ok = frags_in_order(sect, quote)[0]
            rec(cid, doc, claim, ok if expect else not ok, f"{page}：{start} の節の中")
        else:
            ok = frags_in_order(t, quote)[0]
            rec(cid, doc, claim, ok if expect else not ok, f"{page}")

    AS = L.versions("shotoku")
    # ---------------- ［PS］§2.1
    lawq("PS2.1-125-1", "PS§2.1", "所法125① の全文の引用", "shotoku", "Art125/P1",
         "居住者が年の中途において死亡した場合において、その者のその年分の所得税について第百二十条第一項（確定所得申告）の規定による申告書を提出しなければならない場合に該当するときは、その相続人は、第三項の規定による申告書を提出する場合を除き、政令で定めるところにより、その相続の開始があつたことを知つた日の翌日から四月を経過した日の前日（同日前に当該相続人が出国をする場合には、その出国の時。以下この条において同じ。）までに、税務署長に対し、当該所得税について第百二十条第一項各号に掲げる事項その他の事項を記載した申告書を提出しなければならない。")
    lawq("PS2.1-125-2", "PS§2.1", "所法125② の引用", "shotoku", "Art125/P2", "税務署長に対し、当該所得税について第百二十条第一項各号及び第百二十二条第一項各号に掲げる事項その他の事項を記載した申告書を提出することができる。")
    lawq("PS2.1-125-2n", "PS§2.1/M T04", "所法125② に「までに」が無い", "shotoku", "Art125/P2", "までに", expect=False)
    lawq("PS2.1-125-3", "PS§2.1", "所法125③ の期限", "shotoku", "Art125/P3", "その相続の開始があつたことを知つた日の翌日から四月を経過した日の前日までに")
    lawq("PS2.1-125-4a", "PS§2.1/§7.3", "所法125④（2026-12-01 までの版）「同条第三項から第七項までの規定は前三項の規定による申告書の提出について」", "shotoku", "Art125/P4",
         "同条第三項から第七項までの規定は前三項の規定による申告書の提出について", ["2025-12-31", "2026-11-11", "2026-12-01"])
    lawq("PS7.3-125-4b", "PS§7.3", "所法125④（2027-01-01 の版）「同条第三項から第九項まで」「同条第五項及び第七項中「確定申告期限」」", "shotoku", "Art125/P4",
         "同条第三項から第九項までの規定は前三項の規定による申告書の提出について…同条第五項及び第七項中「確定申告期限」", ["2027-01-01"])
    for n, para in (("127", "P4"), ("122", "P3"), ("123", "P3")):
        lawq(f"PS7.3-{n}a", "PS§7.3", f"所法{n}{para}（2026-12-01 までの版）は「第三項から第七項まで」", "shotoku", f"Art{n}/{para}", "第三項から第七項までの規定", ["2025-12-31", "2026-11-11", "2026-12-01"])
        lawq(f"PS7.3-{n}b", "PS§7.3", f"所法{n}{para}（2027-01-01 の版）は「第三項から第九項まで」", "shotoku", f"Art{n}/{para}", "第三項から第九項までの規定…同条第五項及び第七項中「確定申告期限」", ["2027-01-01"])
    lawq("PS7.3-120-6", "PS§7.3", "新所法120⑥（明細書の添付で代える）", "shotoku", "Art120/P6", "社会保険料控除、小規模企業共済等掛金控除、生命保険料控除又は地震保険料控除に関する事項の記載をする居住者…明細書を当該申告書に添付することができる", ["2027-01-01"])
    lawq("PS7.3-120-7", "PS§7.3", "新所法120⑦（書類の提示・提出の求め）", "shotoku", "Art120/P7", "前項に規定する書類の提示又は提出を求めることができる", ["2027-01-01"])
    lawq("PS2.1-125-5", "PS§2.1", "所法125⑤ の引用", "shotoku", "Art125/P5", "前条第一項又は第二項の規定は、第一項の規定による申告書を提出すべき者又は第三項の規定による申告書を提出することができる者がこれらの申告書の提出期限前にこれらの申告書を提出しないで死亡した場合についてそれぞれ準用する。")
    lawq("PS2.1-124-2", "PS§2.1", "所法124② は確定損失申告書について同じ期限で「提出することができる」", "shotoku", "Art124/P2", "前条第一項の規定による申告書を提出することができる居住者…その相続の開始があつたことを知つた日の翌日から四月を経過した日の前日までに、税務署長に対し、当該申告書を提出することができる。")
    lawq("PS2.1-129", "PS§2.1", "所法129（124①（125⑤ で準用を含む）・125① の申告書、通則法5 による納付）", "shotoku", "Art129",
         "第百二十四条第一項（確定申告書を提出すべき者が死亡した場合の確定申告）（第百二十五条第五項（年の中途で死亡した場合の確定申告）において準用する場合を含む。）又は第百二十五条第一項…これらの申告書の提出期限までに、当該金額に相当する所得税を国税通則法第五条（相続による国税の納付義務の承継）に定めるところにより国に納付しなければならない。")
    lawq("PS2.1-128", "PS§2.1", "所法128 の括弧が 124①・126① の申告書を除く", "shotoku", "Art128", "（第百二十四条第一項（確定申告書を提出すべき者が死亡した場合の確定申告）又は第百二十六条第一項（確定申告書を提出すべき者が出国をする場合の確定申告）の規定に該当して提出すべきものを除く。）…第三期において")
    lawq("PS2.1-rei263-1", "PS§2.1", "所令263①（124①②・125①〜③ の申告書、120①各号・122①各号＋財務省令の事項）", "shotoku-rei", "Art263/P1", "法第百二十四条第一項若しくは第二項…又は第百二十五条第一項から第三項まで…法第百二十条第一項各号（確定所得申告）又は第百二十二条第一項各号（還付等を受けるための申告）に掲げる事項のほか、財務省令で定める事項を併せて記載しなければならない")
    lawq("PS2.1-rei263-2", "PS§2.1", "所令263② の引用", "shotoku-rei", "Art263/P2", "前項の申告書を提出する場合において、相続人が二人以上あるときは、当該申告書は、各相続人が連署による一の書面で提出しなければならない。ただし、他の相続人の氏名を付記して各別に提出することを妨げない。")
    lawq("PS2.1-rei263-3", "PS§2.1", "所令263③（各別に提出した相続人は要領を通知）", "shotoku-rei", "Art263/P3", "遅滞なく、他の相続人に対し、当該申告書に記載した事項の要領を通知しなければならない")
    lawq("PS2.1-rei267-5", "PS§2.1", "所令267⑤ の引用", "shotoku-rei", "Art267/P5", "当該申告書には、当該還付金の額を各人別に記載しなければならない。")
    for i, q in ((1, "各相続人の氏名、住所…及び個人番号…、被相続人との続柄、民法（明治二十九年法律第八十九号）第九百条から第九百二条まで（法定相続分・代襲相続人の相続分・遺言による相続分の指定）の規定によるその相続分並びに相続又は遺贈によつて得た財産の価額"),
                 (2, "相続人が限定承認をした場合には、その旨"),
                 (3, "相続人が二人以上ある場合には、法第百二十条第一項第三号（確定所得申告）に掲げる所得税の額（…）を第一号の各相続人の相続分により按分して計算した額に相当する所得税の額")):
        lawq(f"PS2.1-ki49-{i}", "PS§2.1", f"所規49①{i} の引用", "shotoku-ki", f"Art49/P1/I{i}", q)
    lawq("PS2.1-ki48-1-2", "PS§2.1", "所規48①二（124②・125③ の確定損失申告書：死亡をした者の氏名と死亡の時の住所）", "shotoku-ki", "Art48/P1/I2", "法第百二十四条第二項…又は第百二十五条第三項…死亡をした者の氏名及びその死亡の時における住所")
    lawq("PS2.1-ts5-1", "PS§2.1", "通則法5①（相続人又は民法951条の法人が承継）", "tsusoku", "Art5/P1", "相続人（包括受遺者を含む。以下同じ。）又は民法（明治二十九年法律第八十九号）第九百五十一条（相続財産法人の成立）の法人は…国税…を納める義務を承継する")
    lawq("PS2.1-ts5-2", "PS§2.1", "通則法5② の引用", "tsusoku", "Art5/P2", "前項前段の場合において、相続人が二人以上あるときは、各相続人が同項前段の規定により承継する国税の額は、同項の国税の額を民法第九百条から第九百二条まで（法定相続分・代襲相続人の相続分・遺言による相続分の指定）の規定によるその相続分により按分して計算した額とする。")
    lawq("PS2.1-ts5-3", "PS§2.1", "通則法5③（財産の価額が承継額を超える相続人の責め）", "tsusoku", "Art5/P3", "相続によつて得た財産の価額が同項の規定により計算した国税の額を超える者があるときは、その相続人は、その超える価額を限度として、他の相続人が前二項の規定により承継する国税を納付する責めに任ずる")
    # ---------------- ［PS］§2.2・§3.2・§4.2・§8・§9 の通達（節の中にあるか）
    K = "kihon_19_02"
    webq("PS2.2-124125-1", "PS§2.2", "所基通124・125−1（122① の申告書を出せる者が翌年1月1日以後に死亡、所令263①〜③）", K, "令第263条第1項《死亡の場合の確定申告の特例》に規定する事項を記載し、同条第2項及び第3項に規定するところにより提出する", "124・125－1")
    webq("PS2.2-124125-2", "PS§2.2", "所基通124・125−2 の引用と（注）", K, "法第120条第1項《確定所得申告》に規定する申告書を提出すべき者又は第123条第1項《確定損失申告》に規定する申告書を提出することができる者がこれらの申告書を提出しないでこれらの申告書の提出期限後に死亡した場合には、法第124条の規定の適用はなく、相続人が提出するこれらの申告書は、期限後申告書となることに留意する。…通則法第11条", "124・125－2")
    webq("PS2.2-124125-3", "PS§2.2", "所基通124・125−3 の引用（あん分と100円未満切捨て）", K, "所得税の確定金額及び復興特別所得税の確定金額の合計額に復興財確法第24条第2項の規定を適用した後の金額を規則第49条第1号の各相続人の相続分によりあん分して計算した額に相当する額とする。…この場合において、当該相当する額に100円未満の端数がある場合又はその全額が100円未満である場合は、その端数金額又はその全額を切り捨てる。", "124・125－3")
    webq("PS2.2-124125-4", "PS§2.2", "所基通124・125−4 (1)〜(4)", K, "死亡の日までに生じた損失の金額及び同日までに支出した令第206条第1項各号…死亡の日までに支払った医療費の合計額…死亡の日までに支払ったこれらの保険料又は掛金のそれぞれの合計額…死亡の日までに支出した特定寄附金の額の合計額…85－1参照", "124・125－4")
    webq("PS3.2-127-1", "PS§3.2", "所基通127−1 の引用", K, "法第127条の規定により確定申告書を提出する場合における所得控除額の計算については、124・125－4の取扱いに準ずる。", "127－1")
    webq("PS9-140141-1", "PS§9", "所基通140・141−1 の引用", K, "法第140条第1項に規定する「青色申告書を提出する居住者」には、法第124条第1項又は第2項《確定申告書を提出すべき者等が死亡した場合の確定申告》の規定に該当して青色申告書を提出する相続人も含まれることに留意する。…令第273条…規則第54条第2項", "140・141－1")
    webq("PS9-140141-2", "PS§9", "所基通140・141−2（各号は税額控除前、限度は120①三の税額控除後）", K, "各種の税額控除前の所得税の額をいうのであるが、同条第2項に規定する還付金の限度額となる前年分の所得税の額（附帯税を除く。）は、法第120条第1項第3号《確定所得申告》に掲げる各種の税額控除後の所得税の額", "140・141－2")
    webq("PS9-140141-4", "PS§9", "所基通140・141−4（通則法118①・119① の準用）", K, "通則法第118条第1項《国税の課税標準の端数計算等》及び第119条第1項《国税の確定金額の端数計算等》の規定を準用する", "140・141－4")
    K = "kihon_16_06"
    webq("PS4.2-85-1", "PS§4.2", "所基通85−1 の柱書と (1)(2)", K, "年の中途において死亡し又は出国をした居住者の配偶者その他の親族…その死亡又は出国の時（その年1月1日から当該時までに死亡した親族等については、当該親族等の死亡の時）の現況により判定する。…その死亡又は出国の時の現況により見積もったその年1月1日から12月31日までの当該親族等の合計所得金額により判定する。", "85－1")
    webq("PS4.2-83-84-2-1", "PS§4.2", "所基通83から84の2−1 の引用", K, "その後その年中において相続人等他の居住者の控除対象配偶者若しくは配偶者又は控除対象扶養親族若しくは特定親族にも該当する者については、当該他の居住者が自己の控除対象配偶者若しくは配偶者又は控除対象扶養親族若しくは特定親族として控除することができることに留意する。", "83から84の2－1")
    webq("PS4.2-79-2", "PS§4.2", "所基通79−2 の引用", K, "その後その年中において相続人等他の居住者の同一生計配偶者又は扶養親族にも該当するときは、当該他の居住者が自己の障害者である同一生計配偶者又は扶養親族として障害者控除の適用を受けることができることに留意する。", "79－2")
    webq("PS4.2-72-4", "PS§4.2", "所基通72−4(2) の引用（死亡・出国の日において見積もった合計額）", "kihon_16_01", "この場合において、当該居住者が年の中途において死亡し又は出国をしたときは、その死亡又は出国の日において見積もった当該日の属する年分の当該合計額を基礎として法第72条第1項の規定を適用する。", "72－4")
    webq("PS4.2-72-4b", "PS§12", "所基通72−4(2) の基準は「基礎控除の額に相当する金額以下」", "kihon_16_01", "合計額が基礎控除の額に相当する金額以下であるかどうか", "72－4")
    webq("PS9-70-15", "PS§9", "所基通70−15 と（注）", "kihon_15_01", "当該相続人の総所得金額、退職所得金額又は山林所得金額の計算上控除することができないことに留意する。…法第141条第1項又は第4項《相続人等の純損失の繰戻しによる還付の請求》の規定により当該被相続人の死亡した日の属する年の前年分又は前前年分に繰り戻して還付の請求ができることに留意する。", "70－15")
    webq("PS8-71-1", "PS§8", "所基通71−1（更正の請求に基づく更正で雑損失が生じた場合も含む）", "kihon_15_01", "通則法第23条", "71－1")
    webq("PS8-71-2", "PS§8", "所基通71−2（過少の雑損失の更正後の金額）", "kihon_15_01", "過少である", "71－2")
    webq("PS8-noinherit", "PS§8/§12", "取得した 法第70条〜第71条関係のページに「雑損失」と「相続人」が同じ通達にある箇所は無い（所基通70−15 は純損失だけ）", "kihon_15_01", "雑損失…相続人", "71－1", expect=False)
    # ---------------- ［PS］§3.1
    lawq("PS3.1-127-1", "PS§3.1", "所法127① の引用", "shotoku", "Art127/P1", "居住者は、年の中途において出国をする場合において、その年一月一日からその出国の時までの間における総所得金額、退職所得金額及び山林所得金額について、第百二十条第一項（確定所得申告）の規定による申告書を提出しなければならない場合に該当するときは、第三項の規定による申告書を提出する場合を除き、その出国の時までに、税務署長に対し、その時の現況により同条第一項各号に掲げる事項を記載した申告書を提出しなければならない。")
    lawq("PS3.1-127-2", "PS§3.1", "所法127② の引用", "shotoku", "Art127/P2", "その時の現況により第百二十条第一項各号及び第百二十二条第一項各号に掲げる事項を記載した申告書を提出することができる。")
    lawq("PS3.1-127-2n", "PS§3.1/M T05", "所法127② に「までに」が無い", "shotoku", "Art127/P2", "までに", expect=False)
    lawq("PS3.1-127-3", "PS§3.1", "所法127③「その出国の時までに」", "shotoku", "Art127/P3", "その出国の時までに")
    lawq("PS3.1-126-1", "PS§3.1", "所法126① の引用", "shotoku", "Art126/P1", "第百二十条第一項（確定所得申告）の規定による申告書を提出すべき居住者は、その年の翌年一月一日から当該申告書の提出期限までの間に出国をする場合には、第百二十三条第一項（確定損失申告）の規定による申告書を提出する場合を除き、その出国の時までに、税務署長に対し、当該申告書を提出しなければならない。")
    lawq("PS3.1-126-2", "PS§3.1", "所法126② の引用", "shotoku", "Art126/P2", "第百二十三条第一項の規定による申告書を提出することができる居住者は、その年の翌年一月一日から二月十五日までの間に出国をする場合には、当該期間内においても、税務署長に対し、当該申告書を提出することができる。")
    lawq("PS3.1-130", "PS§3.1", "所法130 の引用", "shotoku", "Art130", "これらの申告書の提出期限までに、当該金額に相当する所得税を国に納付しなければならない。")
    lawq("PS3.1-115", "PS§3.1", "所法115 の引用", "shotoku", "Art115", "その出国後に当該納期限の到来する予定納税額に相当する所得税を、その出国の時までに国に納付しなければならない。")
    lawq("PS3.1-120-1-4", "PS§3.1", "所法120①四（127①〜③ の申告書で還付される金額を源泉徴収税額から控除）", "shotoku", "Art120/P1/I4", "第百二十七条第一項から第三項まで（年の中途で出国をする場合の確定申告）の規定による申告書を提出したことにより…還付される金額")
    lawq("PS3.1-120-2-2", "PS§3.1", "所法120②二（127① に該当して130 等により納付した所得税の額を予納税額に含める）", "shotoku", "Art120/P2/I2", "その年において第百二十七条第一項の規定に該当して、第百三十条（出国の場合の確定申告による納付）又は国税通則法第三十五条第二項（期限後申告等による納付）の規定により納付した又は納付すべき所得税の額")
    lawq("PS3.1-102", "PS§3.1", "所法102 の引用", "shotoku", "Art102", "その年十二月三十一日（その年の中途において死亡した場合には、その死亡の日）において居住者である者でその年において非居住者であつた期間を有するもの又はその年の中途において出国をする居住者でその年一月一日からその出国の日までの間に非居住者であつた期間を有するもの")
    for i, w in ((1, "雑損控除"), (2, "医療費控除"), (3, "社会保険料控除及び小規模企業共済等掛金控除"), (4, "生命保険料控除及び地震保険料控除")):
        lawq(f"PS3.1-rei258-3-{i}", "PS§3.1", f"所令258③{i}（{w}：居住者期間内）", "shotoku-rei", f"Art258/P3/I{i}", "居住者期間内")
    lawq("PS3.1-165-1", "PS§3.1", "所法165① が 60の4・95の2 を除く", "shotoku", "Art165/P1", "第六十条の四（外国転出時課税の規定の適用を受けた場合の譲渡所得等の特例）…第九十五条の二（国外転出をする場合の譲渡所得等の特例に係る外国税額控除の特例）")
    lawq("PS3.1-ts117-1", "PS§3.1", "通則法117①（納税管理人を定めなければならない）", "tsusoku", "Art117/P1", "個人である納税者がこの法律の施行地に住所及び居所（事務所及び事業所を除く。）を有せず、若しくは有しないこととなる場合…納税申告書の提出その他国税に関する事項を処理する必要があるときは…納税管理人を定めなければならない")
    lawq("PS3.1-ts117-2", "PS§3.1", "通則法117② の引用", "tsusoku", "Art117/P2", "納税者は、前項の規定により納税管理人を定めたときは、当該納税管理人に係る国税の納税地を所轄する税務署長…にその旨を届け出なければならない。その納税管理人を解任したときも、同様とする。")
    lawq("PS3.1-ts117-5-1-i", "PS§3.1", "通則法117⑤一イ の引用", "tsusoku", "Art117/P5/I1/S1_1", "当該特定納税者と生計を一にする配偶者その他の親族で成年に達した者")
    lawq("PS3.1-rei15-1-1", "PS§3.1", "所令15①一 の引用（号名を除く）", "shotoku-rei", "Art15/P1/I1", "その者が国外において、継続して一年以上居住することを通常必要とする職業を有すること。")
    lawq("PS3.1-rei15-2", "PS§3.1", "所令15②（生計を一にする配偶者等も国内に住所を有しない者と推定）", "shotoku-rei", "Art15/P2", "生計を一にする配偶者その他その者の扶養する親族が国外に居住する場合には、これらの者も国内に住所を有しない者と推定する")
    # ---------------- ［PS］§6
    lawq("PS6-ts10-1-1", "PS§6", "通則法10①一", "tsusoku", "Art10/P1/I1", "期間の初日は、算入しない。ただし、その期間が午前零時から始まるとき、又は国税に関する法律に別段の定めがあるときは、この限りでない。")
    lawq("PS6-ts10-1-2", "PS§6", "通則法10①二", "tsusoku", "Art10/P1/I2", "期間を定めるのに月又は年をもつてしたときは、暦に従う。")
    lawq("PS6-ts10-1-3", "PS§6", "通則法10①三", "tsusoku", "Art10/P1/I3", "前号の場合において、月又は年の始めから期間を起算しないときは、その期間は、最後の月又は年においてその起算日に応当する日の前日に満了する。ただし、最後の月にその応当する日がないときは、その月の末日に満了する。")
    lawq("PS6-ts10-2", "PS§6", "通則法10②", "tsusoku", "Art10/P2", "国税に関する法律に定める申告、申請、請求、届出その他書類の提出、通知、納付又は徴収に関する期限（時をもつて定める期限その他の政令で定める期限を除く。）が日曜日、国民の祝日に関する法律（昭和二十三年法律第百七十八号）に規定する休日その他一般の休日又は政令で定める日に当たるときは、これらの日の翌日をもつてその期限とみなす。")
    lawq("PS6-tr2-1-1", "PS§6", "通則令2①一", "tsusoku-rei", "Art2/P1/I1", "所得税法（昭和四十年法律第三十三号）第二条第一項第四十二号（定義）に規定する出国（以下「出国」という。）の時その他の時をもつて定めた期限")
    lawq("PS6-tr2-2", "PS§6", "通則令2②", "tsusoku-rei", "Art2/P2", "法第十条第二項に規定する政令で定める日は、土曜日又は十二月二十九日、同月三十日若しくは同月三十一日とする。")
    lawq("PS6-ts11", "PS§6", "通則法11（理由のやんだ日から二月以内）", "tsusoku", "Art11", "その理由のやんだ日から二月以内に限り、当該期限を延長することができる。")
    for nm, d in (("元日", "一月一日"), ("成人の日", "一月の第二月曜日"), ("建国記念の日", "政令で定める日"), ("天皇誕生日", "二月二十三日"), ("春分の日", "春分日"),
                  ("昭和の日", "四月二十九日"), ("憲法記念日", "五月三日"), ("みどりの日", "五月四日"), ("こどもの日", "五月五日"), ("海の日", "七月の第三月曜日"),
                  ("山の日", "八月十一日"), ("敬老の日", "九月の第三月曜日"), ("秋分の日", "秋分日"), ("スポーツの日", "十月の第二月曜日"), ("文化の日", "十一月三日"),
                  ("勤労感謝の日", "十一月二十三日")):
        lawq(f"PS6-sj2-{nm}", "PS§6", f"祝日法2 の表：{nm}＝{d}", "shukujitsu", "Art2", f"{nm}｜{d}｜")
    lawq("PS6-sj3-1", "PS§6", "祝日法3①", "shukujitsu", "Art3/P1", "「国民の祝日」は、休日とする。")
    lawq("PS6-sj3-2", "PS§6", "祝日法3②", "shukujitsu", "Art3/P2", "「国民の祝日」が日曜日に当たるときは、その日後においてその日に最も近い「国民の祝日」でない日を休日とする。")
    lawq("PS6-sj3-3", "PS§6", "祝日法3③", "shukujitsu", "Art3/P3", "その前日及び翌日が「国民の祝日」である日（「国民の祝日」でない日に限る。）は、休日とする。")
    # ---------------- ［PS］§7.1 附則
    lawq("PS7.1-R7-1-main", "PS§7.1", "令和7年法律第13号 附則1条本文「令和七年四月一日から施行する」", "shotoku", R7L + "Art1/P1", "この法律は、令和七年四月一日から施行する。")
    lawq("PS7.1-R7-1-1", "PS§7.1", "同 1号 令和7年12月1日：所法2①32・33・34（48万→58万の部分）、28③、83①一、84の2 の追加、85、86①、87①、120③三、121①二ロ、190", "shotoku", R7L + "Art1/P1/I1",
          "令和七年十二月一日…所得税法第二条第一項第三十二号の改正規定、同項第三十三号の改正規定、同項第三十四号の改正規定（「四十八万円」を「五十八万円」に改める部分に限る。）、同法第二十八条第三項の改正規定、同法第八十三条第一項第一号の改正規定、同法第八十四条の次に一条を加える改正規定、同法第八十五条の改正規定、同法第八十六条第一項の改正規定、同法第八十七条第一項の改正規定、同法第百二十条第三項第三号の改正規定、同法第百二十一条第一項第二号ロの改正規定、同法第百九十条")
    lawq("PS7.1-R7-1-2", "PS§7.1", "同 2号「令和八年一月一日」", "shotoku", R7L + "Art1/P1/I2", "令和八年一月一日")
    lawq("PS7.1-R7-1-5", "PS§7.1", "同 5号「令和九年一月一日」と所法120・122③・123③・125④・127④・166 の改正規定、附則8②", "shotoku", R7L + "Art1/P1/I5",
         "令和九年一月一日…所得税法第百二十条の改正規定（同条第三項第三号に係る部分及び同条第四項第二号に係る部分を除く。）、同法第百二十二条第三項、第百二十三条第三項、第百二十五条第四項及び第百二十七条第四項の改正規定並びに同法第百六十六条の改正規定並びに附則第八条第二項の規定")
    common = "令和七年十二月一日前に同年分の所得税につき所得税法第百二十五条又は第百二十七条…の規定による確定申告書を提出した者及び同日前に同年分の所得税につき決定を受けた者は、…異動を生ずることとなった事項について、同日から五年以内に、税務署長に対し、国税通則法第二十三条第一項の更正の請求をすることができる。"
    for a, w in (("Art2/P2", "所法2①三十二〜三十四"), ("Art3/P2", "所法28"), ("Art6/P4", "所法84の2"), ("Art7/P2", "所法86")):
        lawq(f"PS7.1-R7-{a}", "PS§7.1", f"令和7年法律第13号 附則{a}（{w}）の更正の請求の定め", "shotoku", R7L + a, common)
    lawq("PS7.1-R7-6-4w", "PS§7.1", "附則6④ の対象は新所法84の2", "shotoku", R7L + "Art6/P4", "新所得税法第八十四条の二の規定の適用により異動")
    lawq("PS7.1-R7-7-2w", "PS§7.1", "附則7② は「これらの規定を同法第百六十六条において準用する場合を含む。」を含む", "shotoku", R7L + "Art7/P2", "これらの規定を同法第百六十六条において準用する場合を含む。")
    lawq("PS7.1-R7-6-3", "PS§7.1", "附則6③ の引用", "shotoku", R7L + "Art6/P3", "新所得税法第八十五条の規定は、令和七年分以後の所得税について適用し、令和六年分以前の所得税については、なお従前の例による。")
    lawq("PS7.1-R8-2-1", "PS§7.1", "令和8年法律第12号 附則2① の引用", "shotoku", R8L + "Art2/P1", "第一条の規定による改正後の所得税法（以下「新所得税法」という。）第二条第一項（第三十二号（ロに係る部分を除く。）、第三十三号及び第三十四号に係る部分に限る。）の規定は、令和八年分以後の所得税について適用し、令和七年分以前の所得税については、なお従前の例による。", ["2026-12-01", "2027-01-01"])
    c8 = common.replace("令和七年", "令和八年")
    for a, w in (("Art2/P2", "所法2"), ("Art3/P2", "所法28"), ("Art9/P2", "所法86")):
        lawq(f"PS7.1-R8-{a}", "PS§7.1", f"令和8年法律第12号 附則{a}（{w}）の更正の請求の定め", "shotoku", R8L + a, c8, ["2026-12-01", "2027-01-01"])
    lawq("PS7.1-R8-1-4", "PS§7.1/PS§7.4", "令和8年法律第12号 附則1条4号「令和八年十二月一日」：所法2①32（ロを除く）・33・34、28③、86①一", "shotoku", R8L + "Art1/P1/I4",
         "令和八年十二月一日…所得税法第二条第一項第三十二号の改正規定（同号ロに係る部分を除く。）、同項第三十三号及び第三十四号の改正規定、同法第二十八条第三項の改正規定、同法第八十六条第一項第一号の改正規定", ["2026-11-11", "2026-12-01", "2027-01-01"])
    lawq("PS7.1-R8-1-5", "PS§7.3", "令和8年法律第12号 附則1条5号「令和九年一月一日」：所法120 の改正規定・附則10条", "shotoku", R8L + "Art1/P1/I5", "令和九年一月一日…同法第百二十条の改正規定…附則第五条、第八条、第十条", ["2026-11-11", "2026-12-01", "2027-01-01"])
    q10 = "新所得税法第百二十条第六項及び第七項（これらの規定を所得税法第百二十二条第三項、第百二十三条第三項、第百二十五条第四項及び第百二十七条第四項において準用する場合を含む。）の規定は、令和九年一月一日以後に令和八年分以後の所得税に係る確定申告書を提出する場合について適用する。"
    lawq("PS7.3-R8-10", "PS§7.3", "令和8年法律第12号 附則10 の引用（文字どおり）", "shotoku", R8L + "Art10", q10, ["2027-01-01"])
    lawq("PS7.3-R7-8-2", "PS§7.3", "令和7年法律第13号 附則8② は［PS］の引用と文字どおり同じか", "shotoku", R7L + "Art8/P2", q10, ["2027-01-01"])
    lawq("PS7.3-R7-8-2b", "PS§7.3", "令和7年法律第13号 附則8② の括弧は「新所得税法第百二十二条第三項…」", "shotoku", R7L + "Art8/P2", "（これらの規定を新所得税法第百二十二条第三項、第百二十三条第三項、第百二十五条第四項及び第百二十七条第四項において準用する場合を含む。）の規定は、令和九年一月一日以後に令和八年分以後の所得税に係る確定申告書を提出する場合について適用する。", ["2027-01-01"])
    lawq("PS7.3-R7-8-1", "検証で追加", "令和7年法律第13号 附則8①：新所法120③三 は令和7年12月1日以後に提出する確定申告書から（提出日で切り替わる）", "shotoku", R7L + "Art8/P1", "令和七年十二月一日以後に同年分以後の所得税に係る確定申告書を提出する場合について適用し、同日前に確定申告書を提出した場合…なお従前の例による")
    # 政令
    cr = "同日から五年以内に、税務署長に対し、国税通則法"
    lawq("PS7.1-R7R-2-2", "PS§7.1", "令和7年政令第120号 附則2②（所令11の2②）", "shotoku-rei", R7R + "Art2/P2", "令和七年十二月一日前に同年分の所得税につき所得税法第百二十五条又は第百二十七条の規定による確定申告書を提出した者…新令第十一条の二第二項の規定の適用により異動…" + cr)
    lawq("PS7.1-R7R-10-2", "PS§7.1", "令和7年政令第120号 附則10②（所令205①）", "shotoku-rei", R7R + "Art10/P2", "令和七年十二月一日前に…新令第二百五条第一項の規定の適用により異動…" + cr)
    lawq("PS7.1-R8R-2-2", "PS§7.1", "令和8年政令第93号 附則2②（所令11の2②）", "shotoku-rei", R8R + "Art2/P2", "令和八年十二月一日前に…新令第十一条の二第二項の規定の適用により異動…" + cr, ["2026-12-01", "2027-01-01"])
    lawq("PS7.1-R8R-8-2", "PS§7.1", "令和8年政令第93号 附則8②（所令205①）", "shotoku-rei", R8R + "Art8/P2", "令和八年十二月一日前に…新令第二百五条第一項の規定の適用により異動…" + cr, ["2026-12-01", "2027-01-01"])
    lawq("PS7.1-R8R-1-1", "PS§7.1", "令和8年政令第93号 附則1条1号：所令11の2② と205① の改正規定は「令和八年十二月一日」", "shotoku-rei", R8R + "Art1/P1/I1", "第十一条の二第二項の改正規定及び第二百五条第一項の改正規定…令和八年十二月一日", ["2026-11-11", "2026-12-01", "2027-01-01"])
    for a, txt in (("2025-12-31", "五十八万円"), ("2026-11-11", "五十八万円"), ("2026-12-01", "六十二万円"), ("2027-01-01", "六十二万円")):
        lawq(f"ADD-rei205-1-{a}", "検証で追加（PS§12・H SH4）", f"所令205①（雑損控除の親族）の額 asof {a} = {txt}", "shotoku-rei", "Art205/P1", f"合計額が{txt}以下であるもの", [a])
    # 措置法の附則
    S = "sochi"
    lawq("PS7.1-S-R7-32-2", "PS§7.1", "令和7年法律第13号 附則32②（措法27）", S, R7L + "Art32/P2", "令和七年十二月一日前に同年分の所得税につき所得税法第百二十五条又は第百二十七条…新租税特別措置法第二十七条の規定の適用により異動…同日から五年以内に")
    lawq("PS7.1-S-R7-37_2-3", "PS§7.1", "令和7年法律第13号 附則37の2③（措法41の16の2①）", S, R7L + "Art37_2/P3", "令和七年十二月一日前に同年分の所得税につき所得税法第百二十五条又は第百二十七条…新租税特別措置法第四十一条の十六の二第一項の規定の適用により異動…同日から五年以内に")
    lawq("PS7.1-S-R8-34-2", "PS§7.1", "令和8年法律第12号 附則34②（措法27）", S, R8L + "Art34/P2", "令和八年十二月一日前に…新租税特別措置法第二十七条の規定の適用により異動…同日から五年以内に", ["2026-12-01", "2026-12-31", "2027-01-01"])
    lawq("PS7.1-S-R8-36-2", "PS§7.1", "令和8年法律第12号 附則36②（措法29の4）", S, R8L + "Art36/P2", "令和八年十二月一日前に…新租税特別措置法第二十九条の四の規定の適用により異動…同日から五年以内に", ["2026-12-01", "2026-12-31", "2027-01-01"])
    lawq("PS7.1-S-R8-45-1", "PS§7.1", "令和8年法律第12号 附則45① の引用", S, R8L + "Art45/P1", "令和七年分の所得税に係る旧租税特別措置法第四十一条の十六の二第一項に規定する基礎控除の額については、なお従前の例による。", ["2026-12-01", "2026-12-31", "2027-01-01"])
    lawq("PS7.1-S-R8-45-4", "PS§7.1", "令和8年法律第12号 附則45④（措法41の16の2①）", S, R8L + "Art45/P4", "令和八年十二月一日前に…新租税特別措置法第四十一条の十六の二第一項の規定の適用により異動…同日から五年以内に", ["2026-12-01", "2026-12-31", "2027-01-01"])
    # ---------------- ［PS］§7.1・§7.4 措置法第41条の16の2 と所法86・2
    lawq("PS7.1-S41-main-1231", "PS§7.1", "措法41の16の2①（2026-12-31 の版）柱書の引用", S, "Art41_16_2/P1",
         "令和八年分以後の各年分において、居住者のその年分の所得税に係る合計所得金額…が六百五十五万円（令和十年分以後の各年分にあつては、百三十二万円）以下である場合における同法第八十六条第二項に規定する基礎控除の額は、…同項第一号に定める金額に次の各号に掲げる年分の区分に応じ当該各号に定める金額を加算した額とする。", ["2026-12-01", "2026-12-31", "2027-01-01"])
    for v, items in ((["2025-12-31", "2026-11-11", "2026-11-30"], [("I1", "令和七年分及び令和八年分"), ("I1/S1_1", "百三十二万円以下である場合　三十七万円"), ("I1/S1_2", "百三十二万円を超え三百三十六万円以下である場合　三十万円"),
                                                                ("I1/S1_3", "三百三十六万円を超え四百八十九万円以下である場合　十万円"), ("I1/S1_4", "四百八十九万円を超える場合　五万円"), ("I2", "令和九年分以後の各年分　三十七万円")]),
                     (["2026-12-01", "2026-12-31", "2027-01-01"], [("I1", "令和八年分及び令和九年分"), ("I1/S1_1", "その居住者のその年分の所得税に係る合計所得金額が四百八十九万円以下である場合　四十二万円"),
                                                                 ("I1/S1_2", "四百八十九万円を超える場合　五万円"), ("I2", "令和十年分以後の各年分　三十七万円")])):
        for loc, q in items:
            lawq(f"PS7.4-S41-{loc}-{v[0]}", "PS§7.1/§7.4/M§3.2", f"措法41の16の2①{loc}（{v[0]}〜{v[-1]}）「{q}」", S, "Art41_16_2/P1/" + loc, q, v)
    for a, cap in (("2026-11-30", "（令和七年分以後の各年分の基礎控除等の特例）"), ("2026-12-01", "（令和八年分以後の各年分の基礎控除等の特例）")):
        c = L.d[f"sochi_{a}"]["flat"]["Art41_16_2"].get("caption")
        rec(f"PS7.4-S41-cap-{a}", "PS§7.4", f"措法41の16の2 の見出し asof {a} = {cap}", c == cap, f"取得：{c}")
    for a, amt in (("2025-12-31", "五十八万円"), ("2026-11-11", "五十八万円"), ("2026-12-01", "六十二万円"), ("2027-01-01", "六十二万円")):
        lawq(f"PS7.4-86-1-1-{a}", "PS§7.4/M§5.7", f"所法86①一 asof {a}：2,350万円以下 {amt}", "shotoku", "Art86/P1/I1", f"その居住者の合計所得金額が二千三百五十万円以下である場合　{amt}", [a])
    for i, amt in ((2, "四十八万円"), (3, "三十二万円"), (4, "十六万円")):
        lawq(f"PS7.4-86-1-{i}", "PS§7.4", f"所法86①{i} は {amt}（全時点）", "shotoku", f"Art86/P1/I{i}", amt)
    for a, (k, d, f) in (("2026-11-11", ("八十五万円", "五十八万円", "五十八万円")), ("2026-12-01", ("八十九万円", "六十二万円", "六十二万円"))):
        lawq(f"PS7.4-2-32-{a}", "PS§7.4", f"所法2①三十二（勤労学生）asof {a} = {k}", "shotoku", "Art2/P1/I32", f"合計所得金額が{k}以下", [a])
        lawq(f"PS7.4-2-33-{a}", "PS§7.4", f"所法2①三十三（同一生計配偶者）asof {a} = {d}", "shotoku", "Art2/P1/I33", f"のうち、合計所得金額が{d}以下である者をいう。", [a])
        lawq(f"PS7.4-2-34-{a}", "PS§7.4", f"所法2①三十四（扶養親族）末尾 asof {a} = {f}", "shotoku", "Art2/P1/I34", f"のうち、合計所得金額が{f}以下である者をいう。", [a])
    # ---------------- ［PS］§8・§9・§10
    lawq("PS8-71_2-1", "PS§8", "所法71の2①「前年以前五年内」", "shotoku", "Art71_2/P1", "前年以前五年内において生じた特定雑損失金額")
    lawq("PS8-rei204_2", "PS§8", "所令204の2：特定非常災害が発生した日の現況", "shotoku-rei", "Art204_2", "特定非常災害が発生した日の現況による")
    lawq("PS8-rei206-4", "PS§8", "所令206④（特定非常災害による損失から順次成る）", "shotoku-rei", "Art206/P4", "当該特定非常災害により生じた損失の金額から順次成るものとする")
    lawq("PS8-rei206-5", "PS§8", "所令206⑤（雑損控除は他の雑損失金額から順次控除）", "shotoku-rei", "Art206/P5", "他の雑損失金額から順次控除する")
    lawq("PS8-123-1-2", "PS§8", "所法123①二", "shotoku", "Art123/P1/I2", "その年において生じた雑損失の金額がその年分の総所得金額、退職所得金額及び山林所得金額の合計額を超える場合")
    lawq("PS8-123-1-3", "PS§8", "所法123①三（前年以前3年内、特定非常災害で5年内）", "shotoku", "Art123/P1/I3", "その年の前年以前三年内（…前年以前五年内。…）の各年において生じた純損失の金額及び雑損失の金額")
    lawq("PS9-141-1-1", "PS§9", "所法141①一（死亡をした居住者の前年分の課税総所得金額等の税額）", "shotoku", "Art141/P1/I1", "死亡をした居住者のその年の前年分の課税総所得金額、課税退職所得金額及び課税山林所得金額につき第三章第一節（税率）の規定を適用して計算した所得税の額")
    lawq("PS9-141-1-2", "PS§9", "所法141①二（純損失の全部又は一部を控除した金額の税額）", "shotoku", "Art141/P1/I2", "当該純損失の金額の全部又は一部を控除した金額につき第三章第一節の規定に準じて計算した所得税の額")
    lawq("PS9-141-2", "PS§9", "所法141② の引用", "shotoku", "Art141/P2", "前条第二項及び第三項の規定は、前項の場合について準用する。")
    lawq("PS9-rei272-2b", "PS§9", "所令272② の後段（前前年分に140①・141① の適用があれば控除後の額）", "shotoku-rei", "Art272/P2", "既に当該前前年分の所得税につき法第百四十条第一項又は第百四十一条第一項の規定の適用があつたときは、当該前前年分の課税総所得金額、課税退職所得金額及び課税山林所得金額に相当する金額からその適用に係る純損失の金額を控除した金額をもつて")
    for i, q in ((1, "まず前年分の課税総所得金額から控除する"), (2, "まず前年分の課税山林所得金額から控除する"), (5, "まずその他の損失の金額を控除し、次に変動所得の損失の金額を控除する"), (6, "法第九十条第一項（変動所得及び臨時所得の平均課税）")):
        lawq(f"PS9-rei271-1-{i}", "PS§9", f"所令271①{i}", "shotoku-rei", f"Art271/P1/I{i}", q)
    lawq("PS9-rei273-1", "PS§9", "所令273① の引用", "shotoku-rei", "Art273/P1", "各相続人が連署による一の書面で提出しなければならない。ただし、他の相続人の氏名を附記して各別に提出することを妨げない。")
    for i, q in ((1, "各相続人の氏名、住所（国内に住所がない場合には、居所）及び個人番号並びに被相続人との続柄"), (2, "法第百四十一条第一項又は第四項の規定の適用を受けようとする純損失の金額"),
                 (3, "死亡をした者の氏名及びその死亡の時における住所"), (4, "相続人が二人以上ある場合には、各相続人別の還付を受けようとする所得税の額")):
        lawq(f"PS9-ki54-2-{i}", "PS§9", f"所規54②{i}", "shotoku-ki", f"Art54/P2/I{i}", q)
    lawq("PS9-142-3", "PS§9", "所法142③（還付加算金の期間：請求の日（140①・141① で提出期限前ならその提出期限）の翌日以後3月を経過した日から）", "shotoku", "Art142/P3",
         "前二条の規定による還付の請求がされた日（第百四十条第一項（純損失の繰戻しによる還付の請求）又は前条第一項の規定による還付の請求がされた日がこれらの規定に規定する申告書の提出期限前である場合には、その提出期限）の翌日以後三月を経過した日から")
    lawq("PS9-70-1", "PS§9/M T10", "所法70①「確定申告書を提出する居住者」「青色申告書を提出している年に限る」", "shotoku", "Art70/P1", "確定申告書を提出する居住者のその年の前年以前三年内の各年（その年分の所得税につき青色申告書を提出している年に限る。）")
    lawq("PS9-70-4", "PS§9/M T11", "所法70④「連続して確定申告書を提出している場合に限り」", "shotoku", "Art70/P4", "連続して確定申告書を提出している場合に限り")
    lawq("PS10-ch318", "PS§10", "地法318", "chiho", "Art318", "個人の市町村民税の賦課期日は、当該年度の初日の属する年の一月一日とする。")
    lawq("PS10-ch294-2", "PS§10", "地法294②", "chiho", "Art294/P2", "前項第一号の市町村内に住所を有する個人とは、住民基本台帳法の適用を受ける者については、当該市町村の住民基本台帳に記録されている者をいう。")
    lawq("PS10-ch9-1", "PS§10", "地法9①（相続人又は民法951条の法人が納付）", "chiho", "Art9/P1", "その相続人（包括受遺者を含む。以下本章において同じ。）又は民法（明治二十九年法律第八十九号）第九百五十一条の法人は")
    lawq("PS10-ch9-2", "PS§10", "地法9②（相続分によりあん分）", "chiho", "Art9/P2", "民法第九百条から第九百二条までの規定によるその相続分によりあん分して計算した額")
    lawq("PS10-ch9-4", "PS§10", "地法9④ の引用", "chiho", "Art9/P4", "前三項の規定によつて承継する義務は、当該義務に係る申告又は報告の義務を含むものとする。")
    # ---------------- 検証で追加（担当が取っていない一次情報）
    for a, cap in (("Art218", "（二以上の居住者がある場合の同一生計配偶者の所属）"), ("Art218_2", "（二以上の居住者がある場合の生計を一にする配偶者の所属）"),
                   ("Art219", "（二以上の居住者がある場合の扶養親族及び特定親族の所属）"), ("Art220", "（居住者が再婚した場合における同一生計配偶者等の特例）")):
        c = L.d["shotoku-rei_2026-11-11"]["flat"][a].get("caption")
        rec(f"H-SH11-rei{a}", "H SH11-4", f"所令{a[3:]} の見出し = {cap}", c == cap, f"取得：{c}")
    lawq("H-SH11-85-7", "H SH11-4", "所法85⑦ は再婚の特例（政令＝所令220）", "shotoku", "Art85/P7", "年の中途において居住者の配偶者が死亡し、その年中にその居住者が再婚した場合")
    for a, cap in (("Art27", None), ("Art29_4", None)):
        c = L.d["sochi_2026-12-01"]["flat"].get(a, {}).get("caption")
        rec(f"ADD-sochi-{a}", "検証で追加（H SH7）", f"措法{a[3:]} の見出し（2026-12-01 の版）", c is not None, f"取得：{c}", kind="info")
    lawq("ADD-ts74-1", "検証で追加（PS§12）", "通則法74①：還付金等の請求権は請求できる日から5年で時効により消滅", "tsusoku", "Art74/P1", "還付金等に係る国に対する請求権は、その請求をすることができる日から五年間行使しないことによつて、時効により消滅する。")
    kk = json.loads((EXC / "kenkoku-rei_2026-11-11.json").read_text(encoding="utf-8"))
    rec("ADD-kenkoku", "検証で追加（PS§6・§12）", "建国記念の日となる日を定める政令（昭和41年政令第376号）：二月十一日", "二月十一日とする" in kk["full_text"], f"{kk['law_id']} {kk['law_revision_id']}：{kk['full_text'][:60]}")
    webq("ADD-tsukihon10-4", "検証で追加（PS§6・§12）", "国税通則法基本通達（徴収部関係）第10条関係4：1月2日及び3日は「一般の休日」に該当", "tsusoku_10", "１月２日及び３日は、法第10条第２項の「一般の休日」に該当する")
    webq("ADD-tsukihon10-4a", "検証で追加", "同 4：「一般の休日」とは日曜日・祝日法の休日以外の全国的な休日", "tsusoku_10", "法第10条第2項の「一般の休日」とは、日曜日、国民の祝日に関する法律に規定する休日以外の全国的な休日をいうものとする。")
    for y, sp, au, pub in ((2025, "3月20日", "9月23日", "令和 6年 2月 1日"), (2026, "3月20日", "9月23日", "令和 7年 2月 3日"), (2027, "3月21日", "9月23日", "令和 8年 2月 2日")):
        webq(f"ADD-naoj-{y}-sp", "検証で追加", f"国立天文台 暦要項 {y}：春分の日 {sp}", f"naoj_{y}", f"春分の日 {sp}")
        webq(f"ADD-naoj-{y}-au", "検証で追加", f"国立天文台 暦要項 {y}：秋分の日 {au}", f"naoj_{y}", f"秋分の日 {au}")
        webq(f"ADD-naoj-{y}-pub", "検証で追加", f"国立天文台 暦要項 {y}：発表 {pub}", f"naoj_{y}", f"{pub}　　国立天文台発表")
    webq("ADD-kihon9-17", "検証で追加（H SH2-2）", "所基通9−17：死亡後に支給期の到来する給与等・公的年金等・退職手当等で相続税の課税価格に算入されるものは課税しない", "kihon_02_04",
         "死亡した者に係る給与等、公的年金等及び退職手当等（法第30条第1項《退職所得》に規定する退職手当等をいう。）で、その死亡後に支給期の到来するもののうち相続税法の規定により相続税の課税価格計算の基礎に算入されるものについては、課税しないものとする。", "9－17")
    # ---------------- ［PS］§0.2 の版の表示・§2.3 の HTML
    for p, lab in (("ta_2022", "[令和8年4月1日現在法令等]"), ("ta_1920", "[令和8年4月1日現在法令等]"), ("ta_1923", "[令和8年4月1日現在法令等]"), ("ta_1110", "[令和8年4月1日現在法令等]"),
                   ("shitsugi_07_15", "令和7年8月1日現在の法令・通達等")):
        webq(f"PS0.2-label-{p}", "PS§0.2", f"{p} の版の表示「{lab}」", p, lab)
    webq("PS2.3-TA2022-fuhyo", "PS§2.3", "TA2022：付表を添付し死亡当時の納税地の税務署長に提出", "ta_2022", "準確定申告書の付表を添付し、被相続人の死亡当時の納税地の税務署長に提出します。")
    webq("PS2.3-etax-1", "PS§2.3", "e-Tax準確定：相続人が1名でも付表を XML で提出", "jyunkaku_index", "相続人が１名の場合でも必ず②付表をe-Tax（XML形式）で提出する必要があります。")
    webq("PS2.3-etax-2", "PS§2.3", "e-Tax準確定：相続人2名以上なら確認書のイメージデータ", "jyunkaku_index", "相続人が２名以上いる場合は、各相続人が申告内容等を確認し署名した上で、③確認書のイメージデータ（PDF形式）を作成し、e-Taxで送信する必要があります。")
    webq("PS0.2-TA1923-117", "PS§3.2", "TA1923 の根拠法令等に通則法117", "ta_1923", "通法12、117")

    # ---------------- ［M］§5.1 の T01〜T16 を、項・号の単位で見直す
    lawq("M-T01", "M§5.1", "T01 所法2①三十七 が「第二編第五章第二節第一款及び第二款」を引く", "shotoku", "Art2/P1/I37", "第二編第五章第二節第一款及び第二款")
    lawq("M-T02", "M§5.1", "T02 所法2①四十一 に 125①・127①", "shotoku", "Art2/P1/I41", "第百二十五条第一項（年の中途で死亡した場合の確定申告）又は第百二十七条第一項")
    lawq("M-T03", "M§5.1", "T03 所法2①三十イ(2)", "shotoku", "Art2/P1/I30", "第七十条（純損失の繰越控除）及び第七十一条（雑損失の繰越控除）の規定を適用しないで計算した")
    lawq("M-T06a", "M§5.1", "T06 所法127①② に「その時の現況により」", "shotoku", "Art127/P1", "その時の現況により")
    lawq("M-T06b", "M§5.1", "T06 所法125 の全体に「現況」が無い", "shotoku", "Art125", "現況", expect=False)
    lawq("M-T07", "M§5.1", "T07 所法85①「以下この条において同じ」", "shotoku", "Art85/P1", "以下この条において同じ")
    lawq("M-T08a", "M§5.1", "T08 所法141 の全体に「第百二十七条」が無い", "shotoku", "Art141", "第百二十七条", expect=False)
    lawq("M-T08b", "M§5.1", "T08 所法140① に「青色申告書を提出する居住者」", "shotoku", "Art140/P1", "青色申告書を提出する居住者")
    lawq("M-T10b", "M§5.1", "T10 所法71 の全体に「青色」が無い", "shotoku", "Art71", "青色", expect=False)
    lawq("M-T11", "M§5.1", "T11 所法71②「連続して確定申告書を提出している場合に限り」", "shotoku", "Art71/P2", "連続して確定申告書を提出している場合に限り")
    lawq("M-T12", "M§5.1", "T12 所法124①「その年の翌年一月一日から当該申告書の提出期限までの間に当該申告書を提出しないで死亡した場合」", "shotoku", "Art124/P1", "その年の翌年一月一日から当該申告書の提出期限までの間に当該申告書を提出しないで死亡した場合")
    lawq("M-T13", "M§5.1", "T13 所法120① 第三期", "shotoku", "Art120/P1", "第三期（その年の翌年二月十六日から三月十五日までの期間をいう。")
    for nm, q in (("34_2", "居住者　年齢十六歳以上の者"), ("34_3", "年齢十九歳以上二十三歳未満"), ("34_4", "年齢七十歳以上")):
        lawq(f"M-T14-{nm}", "M§5.1", f"T14 所法2①{nm}", "shotoku", f"Art2/P1/I{nm}", q)

    # ---------------- 計算の再現（独自の実装）
    # 所法89① の表
    t89 = L.node("shotoku", "2026-11-11", "Art89/P1")
    pairs = re.findall(r"([一二三四五六七八九十百千万]+万円)(?:以下の金額|を超える金額)｜百分の([一二三四五六七八九十]+)｜／", t89)
    rec("M[1]-89", "M§4[1]", "所法89① の表（195万以下5%…4,000万超45%）", [p[1] for p in pairs] == ["五", "十", "二十", "二十三", "三十三", "四十", "四十五"], f"表から読んだ段：{pairs}")
    # 期限：担当の前提（春分・秋分・建国記念の日・1/2・1/3 が決まらない）と、検証で取得した一次情報を入れた前提
    eq_none = {}
    eq_full = {(2025, "spring"): dt.date(2025, 3, 20), (2025, "autumn"): dt.date(2025, 9, 23), (2026, "spring"): dt.date(2026, 3, 20), (2026, "autumn"): dt.date(2026, 9, 23),
               (2027, "spring"): dt.date(2027, 3, 21), (2027, "autumn"): dt.date(2027, 9, 23)}
    for y in range(2020, 2032):
        eq_full[(y, "kenkoku")] = dt.date(y, 2, 11)
    ippan_full = lambda y: {dt.date(y, 1, 2), dt.date(y, 1, 3)}  # noqa: E731

    def dl(knew, model):
        end = deadline_shibo(knew, None, None)
        if model == "tanto":
            r, why = roll_forward(end, eq_none, None)
        else:
            r, why = roll_forward(end, eq_full, ippan_full)
        return end, r, why

    # [2] 読みA・読みB と記載要領の例
    okA = all(deadline_shibo(dt.date(y, 6, 20), None, None, "A") == dt.date(y, 10, 20) for y in range(2020, 2031))
    okB = any(deadline_shibo(dt.date(y, 6, 20), None, None, "B") == dt.date(y, 10, 20) for y in range(2020, 2031))
    rec("M[2]", "M§4[2]", "読みA は記載要領の例（6/20→10/20）と 2020〜2030 年で一致、読みB は一致しない", okA and not okB, f"A={okA} B いずれかの年で一致={okB}")
    cases3 = [("2026-06-20", "2026-10-20"), ("2026-01-10", "2026-05-11"), ("2026-04-29", "2026-08-31"), ("2026-07-02", "2026-11-02"), ("2026-08-28", "2026-12-28"),
              ("2027-02-10", "2027-06-10"), ("2027-01-15", "2027-05-17"), ("2027-03-10", "2027-07-12"), ("2027-03-15", "2027-07-15"), ("2027-03-20", "2027-07-20"),
              ("2026-07-10", "2026-11-10"), ("2026-08-29", "2027-01-04"), ("2026-09-03", "2027-01-04"), ("2026-08-27", "2026-12-28")]
    for k, want in cases3:
        end, r, why = dl(dt.date.fromisoformat(k), "tanto")
        rec(f"M[3]-{k}", "M§4[3][9]/§5.4/I SI6", f"知った日 {k} → 期限 {want}（担当の前提で）", str(r) == want, f"満了 {end}（{end.strftime('%a')}）→ {r} {why or ''}")
    und = []
    for k in ["2026-10-27", "2026-10-28", "2026-10-31", "2026-11-01", "2026-11-02", "2026-11-26", "2026-11-27", "2027-10-31", "2025-08-27", "2025-09-02", "2025-09-03", "2027-08-29", "2027-09-03",
              "2026-04-20", "2026-05-20", "2026-09-20"]:
        e1, r1, w1 = dl(dt.date.fromisoformat(k), "tanto")
        e2, r2, w2 = dl(dt.date.fromisoformat(k), "full")
        und.append(f"{k}: 満了 {e1}（{e1.strftime('%a')}）担当の前提 {r1 or '決まらない'} ／ 一次情報を入れると {r2 or ('決まらない：' + str(w2))}")
    rec("M[3]-und", "M§4[3]/§5.4/I SI6", "担当の前提で「決まらない」期限と、検証で取得した一次情報（政令・暦要項・通則法基本通達）を入れたときの期限", True, " ／ ".join(und), kind="info")
    # SI6 の「10-28〜10-31、11-01」の範囲：担当の前提で決まらない知った日の範囲（2026-10-01〜2026-12-31）
    rng = []
    d0 = dt.date(2026, 10, 1)
    while d0 <= dt.date(2026, 12, 31):
        _, r, _ = dl(d0, "tanto")
        if r is None:
            rng.append(d0)
        d0 += dt.timedelta(days=1)
    spans = []
    for d in rng:
        if spans and (d - spans[-1][1]).days == 1:
            spans[-1][1] = d
        else:
            spans.append([d, d])
    rec("I-SI6-range", "I SI6", "担当の前提で期限が決まらない知った日（2026年10〜12月）の範囲（SI6 は 10-28〜10-31・11-01 を例に挙げる）", None,
        "決まらない範囲：" + "、".join(f"{a}〜{b}" for a, b in spans), kind="info")
    rng2 = []
    d0 = dt.date(2025, 1, 1)
    while d0 <= dt.date(2027, 8, 31):
        _, r, w = dl(d0, "full")
        if r is None:
            rng2.append(f"{d0}（{w}）")
        d0 += dt.timedelta(days=1)
    rec("ADD-deadline-full", "検証で追加", "一次情報を入れた前提で、知った日 2025-01-01〜2027-08-31 のうち期限が決まらない日", len(rng2) == 0, f"{len(rng2)} 日：" + "、".join(rng2[:10]))
    # 休日の関数の自己検査：祝日法3②③ から作った振替休日・国民の休日が、暦要項の「…は休日になる」と一致するか
    naoj_extra = {2025: ["2月24日", "5月6日", "11月24日"], 2026: ["5月6日", "9月22日"], 2027: ["3月22日"]}
    for y, lst in naoj_extra.items():
        hol, _ = national_holidays(y, eq_full)
        mine = []
        d0 = dt.date(y, 1, 1)
        while d0.year == y:
            h, why = holiday_info(d0, eq_full, ippan_full)
            if h and why in ("振替休日", "国民の休日"):
                mine.append(f"{d0.month}月{d0.day}日")
            d0 += dt.timedelta(days=1)
        t = web_text(f"naoj_{y}") or ""
        stated = "、".join(lst)
        rec(f"ADD-naoj-{y}-extra", "検証で追加", f"{y} 年の振替休日・国民の休日（祝日法3②③ から計算）＝暦要項の「{stated}は休日になる」", mine == lst and all(norm(x) in norm(t) for x in lst), f"計算：{mine}")
    # [5c] 2026年分の第三期の末日
    r, w = roll_forward(dt.date(2027, 3, 15), eq_full, ippan_full)
    rec("ADD-3rd-2027", "M§5.4[5c]/I SI6", "2026年分の第三期の末日（2027-03-15）は一次情報を入れると決まる", r == dt.date(2027, 3, 15), f"→ {r}（{dt.date(2027, 3, 15).strftime('%a')}）。担当の前提では {roll_forward(dt.date(2027, 3, 15), eq_none, None)}")
    # [4] 5年
    for start, want in ((dt.date(2025, 12, 1), "2030-12-02"), (dt.date(2026, 12, 1), "2031-12-01")):
        a = dt.date(start.year + 5, start.month, start.day) - dt.timedelta(days=1)  # 初日算入
        b = dt.date(start.year + 5, start.month, start.day)  # 初日不算入（翌日起算）
        ra, _ = roll_forward(a, eq_full, ippan_full)
        rb, _ = roll_forward(b, eq_full, ippan_full)
        rec(f"M[4]-{start}", "M§4[4]", f"起点 {start} の「五年以内」→ {want}（2つの読みとも）", str(ra) == want and str(rb) == want, f"初日算入 {a}（{a.strftime('%a')}）→{ra}、不算入 {b}（{b.strftime('%a')}）→{rb}")
    # [5] 按分
    def share(total, ratios, unit):
        return [int(Fraction(total) * r) // unit * unit for r in ratios]
    for total, ratios, unit, want in ((123400, [Fraction(1, 2), Fraction(1, 4), Fraction(1, 4)], 100, [61700, 30800, 30800]),
                                      (100000, [Fraction(1, 3)] * 3, 100, [33300] * 3), (250, [Fraction(1, 2), Fraction(1, 4), Fraction(1, 4)], 100, [100, 0, 0]),
                                      (12345, [Fraction(2, 3), Fraction(1, 3)], 1, [8230, 4115]), (10000, [Fraction(1, 3)] * 3, 1, [3333] * 3)):
        got = share(total, ratios, unit)
        rec(f"M[5]-{total}-{unit}", "M§4[5]/I SI7", f"{total} を {[str(r) for r in ratios]} で按分（{unit}円未満切捨て）→ {want}", got == want, f"{got} 差 {total - sum(got)}")
    # [6]・§5.6 繰戻し
    for prev, loss, want in ((4000000, 1500000, (372500, 152500, 220000)), (3000000, 500000, (202500, 152500, 50000)), (5000000, 600000, (572500, 452500, 120000))):
        got = kurimodoshi(prev, loss)
        rec(f"M[6]-{prev}-{loss}", "M§4[6]/§5.6/I SI5", f"課税総所得 {prev}・純損失 {loss} → {want}", got == want, f"{got}（速算 tax89 と段ごとの計算の一致：{tax89(prev) == tax_by_bracket(prev)}）")
    # [7] 雑損失の順序
    carry = [[2023, 500000], [2025, 300000]]
    incomes = [("総所得", 300000), ("山林", 0), ("退職", 100000)]
    used = []
    for i, (yr_amt) in enumerate(carry):
        for j, (nm, inc) in enumerate(incomes):
            take = min(yr_amt[1], inc)
            if take:
                used.append((yr_amt[0], nm, take))
                yr_amt[1] -= take
                incomes[j] = (nm, inc - take)
    rec("M[7]", "M§4[7]/I SI9", "雑損失 2023:500,000・2025:300,000、総所得 300,000・退職 100,000 → 2023 から 300,000・100,000、残り 2023:100,000・2025:300,000",
        used == [(2023, "総所得", 300000), (2023, "退職", 100000)] and carry == [[2023, 100000], [2025, 300000]], f"控除 {used} 残り {carry}")
    # [8]・§5.5 年齢
    for b, on, want in (("1956-10-01", "2026-06-30", 69), ("1956-10-01", "2026-12-31", 70), ("2010-09-01", "2026-06-30", 15), ("2010-09-01", "2026-12-31", 16),
                        ("2007-08-01", "2026-06-30", 18), ("2007-08-01", "2026-12-31", 19), ("2003-07-15", "2026-06-30", 22), ("2003-07-15", "2026-12-31", 23)):
        a = age_on(dt.date.fromisoformat(b), dt.date.fromisoformat(on))
        rec(f"M[8]-{b}-{on}", "M§4[8]/§5.5/I SI2", f"生年月日 {b}、{on} の年齢 {want}", a == want, f"{a}")
    # §5.7 基礎控除
    def kiso(total, ver):
        base = 580000 if ver == "1130" else 620000
        if ver == "1130":
            add = 370000 if total <= 1320000 else 300000 if total <= 3360000 else 100000 if total <= 4890000 else 50000 if total <= 6550000 else 0
        else:
            add = 420000 if total <= 4890000 else 50000 if total <= 6550000 else 0
        return base + add
    for tot, a, b in ((1000000, 950000, 1040000), (2000000, 880000, 1040000), (4000000, 680000, 1040000), (5000000, 630000, 670000)):
        rec(f"M§5.7-{tot}", "M§5.7/H SH7/I SI1", f"合計所得金額 {tot}：11-30 版 {a}、12-01 版 {b}", kiso(tot, "1130") == a and kiso(tot, "1201") == b, f"{kiso(tot, '1130')} / {kiso(tot, '1201')} 差 {kiso(tot, '1201') - kiso(tot, '1130')}")
    # 曜日
    for d, wd in (("2026-10-20", "Tue"), ("2027-02-28", "Sun"), ("2027-03-15", "Mon"), ("2030-12-02", "Mon"), ("2031-12-01", "Mon"), ("2027-05-15", "Sat"), ("2026-09-12", "Sat")):
        rec(f"WD-{d}", "M§4/§5.4", f"{d} は {wd}", dt.date.fromisoformat(d).strftime("%a") == wd, dt.date.fromisoformat(d).strftime("%a"))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    mode = sys.argv[1]
    OUT.mkdir(parents=True, exist_ok=True)
    if mode == "fetch-egov":
        mode_fetch_egov()
    elif mode == "fetch-web":
        mode_fetch_web(sys.argv[2:])
    elif mode == "prior-hashes":
        mode_prior_hashes()
    elif mode == "extract":
        mode_extract(sys.argv[2])
    elif mode == "check":
        main_check()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

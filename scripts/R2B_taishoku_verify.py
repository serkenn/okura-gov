"""R2B taishoku の独立した検証（反証役）。

別の担当が書いた次の文書の数値・条番号・通達の番号・施行日・適用年分・URL を、一次情報に当たり直して確かめる。
  docs/public-sources/20261109_round2b_taishoku-laws-and-guidance.md   [PS]
  docs/measurements/20261109_round2b_taishoku-fetch-and-checks.md      [M]
  docs/hypotheses/20261109_round2b_taishoku-model.md                   [H]
  docs/inferences/20261109_round2b_taishoku-inferences.md              [I]
担当のスクリプト（R2B_taishoku_egov.py・_web.py・_checks.py）とその出力は使わない。e-Gov 法令API v2 と行政のサイトから
取り直し、担当とは別に書いたテキスト化（JSON の木を項・号まで下りて文字列を連結する）と照合で確かめる。

実行（Windows。リポジトリの直下で）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_taishoku_verify.py egov    # 条文の取得
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_taishoku_verify.py web     # 行政の資料の取得
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_taishoku_verify.py check   # 照合（ネットワークなし）
  （2026-11-09 の実行では、egov のあとに `egov fukko-rei`・`egov chiho-x` で2つの版を追加で取得した。
    略称を付けた egov は、その略称の版だけを取り直して egov_manifest.json に追記する）
- ID が X- で始まる照合項目は「反証の確認」：文書の主張と反対の事実が一次情報にあるかを見る（一致＝文書の誤りを確認）。

- e-Gov 法令API v2 の使い方は scripts/R1_egov_articles.py・scripts/IMPL_kyuyo_fetch.py を読んで写した（import しない）。
  HTML のテキスト化は scripts/R2X_jinteki_verify.py を写した（import しない）。標準ライブラリのみ。
- ダウンロードは取得ごとに新しい空のディレクトリ .work/downloads/<YYYYMMDD-HHMMSS>_R2B_taishoku_verify_<egov|web>/ に置く
  （信頼できないデータ。その中で何も実行しない）。HTML から取り出したテキストは .work/text/<ts>_R2B_taishoku_verify_web/ に置く。
- 結果は scripts/results/R2B_taishoku_verify/ に書く：egov_manifest.json、web_manifest.json、checks.json、checks.md、diffs.md。
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。個人の情報は送らない。官報は取得しない。
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

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
SLEEP = 1.5
OUT = ROOT / "scripts" / "results" / "R2B_taishoku_verify"

S5 = ["2024-12-31", "2025-12-31", "2026-11-09", "2026-12-31", "2027-01-01"]
# (略称, law_id, 期待する法令名, [asof...])  改正附則も含めて取得する（施行・適用の附則を読むため）
LAWS = [
    ("shotoku", "340AC0000000033", "所得税法", S5),
    ("shotoku-rei", "340CO0000000096", "所得税法施行令", S5),
    ("shotoku-ki", "340M50000040011", "所得税法施行規則", ["2025-12-31", "2026-11-09", "2027-01-01"]),
    ("sochi", "332AC0000000026", "租税特別措置法", ["2025-12-31", "2026-11-09", "2026-12-31", "2027-01-01"]),
    ("fukko", "423AC0000000117", "東日本大震災からの復興のための施策を実施するために必要な財源の確保に関する特別措置法",
     ["2025-12-31", "2026-11-09", "2027-01-01"]),
    ("tsusoku", "337AC0000000066", "国税通則法", ["2026-11-09"]),
    ("tsusoku-rei", "337CO0000000135", "国税通則法施行令", ["2026-11-09"]),
    # 2回目の取得で追加（復興財確法28⑪の政令：徴収・納付があったものとされた額の1円未満の端数の処理）
    ("fukko-rei", "424CO0000000016", "復興特別所得税に関する政令", ["2026-11-09"]),
    ("chiho", "325AC0000000226", "地方税法", ["2026-01-01", "2026-11-09", "2027-01-01"]),
    ("chiho-rei", "325CO0000000245", "地方税法施行令", ["2026-11-09", "2027-01-01"]),
    # 3回目の取得で追加：令和8年12月1日（措法29の4→29の5）の後の地方税法の引用の確認
    ("chiho-x", "325AC0000000226", "地方税法", ["2026-12-31"]),
    ("kokuho-rei", "333CO0000000362", "国民健康保険法施行令", ["2026-11-09"]),
]

TA = "https://www.nta.go.jp/taxes/shiraberu/taxanswer/"
KEISAN = "https://www.keisan.nta.go.jp/"
WEB = {
    "ta_1420": TA + "shotoku/1420.htm",
    "ta_2725": TA + "gensen/2725.htm",
    "ta_2728": TA + "gensen/2728.htm",
    "ta_2732": TA + "gensen/2732.htm",
    "ta_2732_besshi": TA + "gensen/2732_besshi.htm",
    "ta_2735": TA + "gensen/2735.htm",
    "ta_2736": TA + "gensen/2736.htm",
    "ta_2737": TA + "gensen/2737.htm",
    "ta_2740": TA + "gensen/2740.htm",
    "ta_2741": TA + "gensen/2741.htm",
    "ta_1180": TA + "shotoku/1180.htm",
    "ta_1191": TA + "shotoku/1191.htm",
    "ta_1195": TA + "shotoku/1195.htm",
    "ta_1199": TA + "shotoku/1199.htm",
    "ta_yogo_senmon": TA + "yogo/senmon.htm",
    "tetsuzuki_1648_37": "https://www.nta.go.jp/taxes/tetsuzuki/shinsei/annai/gensen/annai/1648_37.htm",
    "shitsugi_shotoku_05_85": "https://www.nta.go.jp/law/shitsugi/shotoku/05/85.htm",
    "shitsugi_gensen_04_06": "https://www.nta.go.jp/law/shitsugi/gensen/04/06.htm",
    "kihon_shotoku_toc": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/01.htm",
    "kihon_04_04": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/04/04.htm",
    "kihon_34_01": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/34/01.htm",
    "nencho_shinkokusyo": "https://www.nta.go.jp/users/gensen/nencho/shinkokusyo/index.htm",
    "fuyo_2025bun_01": "https://www.nta.go.jp/taxes/tetsuzuki/shinsei/annai/gensen/pdf/2025bun_01.pdf",
    "fuyo_2026bun_01": "https://www.nta.go.jp/taxes/tetsuzuki/shinsei/annai/gensen/pdf/2026bun_01.pdf",
    "fuyo_2025bun_02": "https://www.nta.go.jp/taxes/tetsuzuki/shinsei/annai/gensen/pdf/2025bun_02.pdf",
    "fuyo_2026bun_02": "https://www.nta.go.jp/taxes/tetsuzuki/shinsei/annai/gensen/pdf/2026bun_02.pdf",
    "aramashi2026_01": "https://www.nta.go.jp/publication/pamph/gensen/aramashi2026/pdf/01.pdf",
    "nencho2026_305": "https://www.nta.go.jp/publication/pamph/gensen/nencho2026/pdf/305.pdf",
    "keisan_robots": KEISAN + "robots.txt",
    "r7_cat21c_index": KEISAN + "r7yokuaru/cat2/cat21/cat21c/index.html",
    "r7sp_scid1559": KEISAN + "r7yokuaru_sp/cat2/cat21/cat21c/scid1559.html",
    "r7_cid458": KEISAN + "r7yokuaru/cat2/cat21/cat21e/cid458.html",
    "r7sp_scid1322": KEISAN + "r7yokuaru_sp/socat2/socat23/scid1322.html",
    "r7_ocat241_index": KEISAN + "r7yokuaru/ocat2/ocat24/ocat241/index.html",
    "r5_cid647": KEISAN + "r5yokuaru/ocat2/ocat24/ocat241/cid647.html",
    "r7_cid647": KEISAN + "r7yokuaru/ocat2/ocat24/ocat241/cid647.html",
    "soumu_65871": "https://www.soumu.go.jp/main_sosiki/jichi_zeisei/czaisei/65871.html",
    "soumu_hayami_h25": "https://www.soumu.go.jp/main_content/000189437.pdf",
    "chikyosai_osaka_2023": "https://osaka.chikyosai.or.jp/files/kaiin/hifuyousya_gendogaku_2023.pdf?230331",
}


# ---------------------------------------------------------------- 取得
def http_get(url, accept="*/*", timeout=300):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept, "Accept-Language": "ja"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.geturl(), dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, url, dict(e.headers or {}), e.read()


def cmd_egov(only=None):
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2B_taishoku_verify_egov"
    dl.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    man_path = OUT / "egov_manifest.json"
    man = json.loads(man_path.read_text(encoding="utf-8")) if (only and man_path.exists()) else {"runs": [], "fetches": [], "errors": []}
    man["runs"].append({"run_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "only": only or []})
    for short, law_id, title, asofs in LAWS:
        if only and short not in only:
            continue
        for asof in asofs:
            q = {"response_format": "json", "asof": asof}
            url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode(q)
            rec = None
            for attempt in range(1, 5):
                try:
                    st, _, _, body = http_get(url, accept="application/json")
                except Exception as e:  # noqa: BLE001
                    st, body = None, repr(e).encode()
                fn = dl / f"{short}_{asof}_try{attempt}.json"
                fn.write_bytes(body)
                rec = {"short": short, "law_id": law_id, "asof": asof, "url": url, "status": st, "attempt": attempt,
                       "file": str(fn.relative_to(ROOT)).replace("\\", "/"), "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
                ok = False
                if st == 200:
                    try:
                        d = json.loads(body)
                        ok = True
                    except json.JSONDecodeError:
                        rec["not_json"] = True
                if ok:
                    ri = d.get("revision_info") or {}
                    li = d.get("law_info") or {}
                    rec.update({"law_title": ri.get("law_title"), "title_ok": ri.get("law_title") == title,
                                "law_num": li.get("law_num"), "law_revision_id": ri.get("law_revision_id"),
                                "amendment_law_num": ri.get("amendment_law_num"),
                                "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                                "current_revision_status": ri.get("current_revision_status"), "updated": ri.get("updated")})
                    break
                print("retry", short, asof, st, len(body), flush=True)
                time.sleep(15)
            man["fetches"] = [f for f in man["fetches"] if not (f["short"] == short and f["asof"] == asof)] + [rec]
            print("ok" if rec.get("law_revision_id") else "NG", short, asof, rec.get("law_revision_id"), rec.get("current_revision_status"), flush=True)
            time.sleep(SLEEP)
    man_path.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")


class Extract(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self._skip, self.title, self._in_title = [], 0, "", False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "img" and not self._skip:
            alt = dict(attrs).get("alt")
            if alt:
                self.parts.append("⟨" + alt + "⟩")
        if tag in ("br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "dt", "dd", "table"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.title += data
        self.parts.append(data)


def decode(body, ctype):
    cands = []
    m = re.search(r"charset=([\w\-]+)", ctype or "", re.I)
    if m:
        cands.append(m.group(1))
    m = re.search(rb"<meta[^>]+charset=[\"']?([\w\-]+)", body[:4000], re.I)
    if m:
        cands.append(m.group(1).decode("ascii", "replace"))
    for c in cands + ["utf-8", "cp932", "euc-jp"]:
        try:
            return body.decode(c)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", "replace")


def cmd_web(ids=None):
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2B_taishoku_verify_web"
    dl.mkdir(parents=True, exist_ok=False)
    tx = ROOT / ".work" / "text" / f"{ts}_R2B_taishoku_verify_web"
    tx.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    man = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"),
           "text_dir": str(tx.relative_to(ROOT)).replace("\\", "/"), "results": []}
    items = [(k, v) for k, v in WEB.items() if not ids or k in ids]
    for i, (sid, url) in enumerate(items):
        if i:
            time.sleep(SLEEP)
        rec = {"id": sid, "url": url}
        try:
            st, final, hdr, body = http_get(url, timeout=90)
            ctype = hdr.get("Content-Type", "")
            ext = ".pdf" if ("pdf" in ctype.lower() or final.lower().split("?")[0].endswith(".pdf")) else (
                ".txt" if "text/plain" in ctype.lower() else ".html")
            (dl / f"{sid}{ext}").write_bytes(body)
            rec.update({"status": st, "final_url": final, "content_type": ctype, "bytes": len(body),
                        "sha256": hashlib.sha256(body).hexdigest(), "last_modified": hdr.get("Last-Modified"),
                        "saved": f"{sid}{ext}"})
            if ext == ".html":
                p = Extract()
                p.feed(decode(body, ctype))
                t = re.sub(r"\n{3,}", "\n\n", "".join(p.parts))
                (tx / f"{sid}.txt").write_text(t, encoding="utf-8")
                rec.update({"title": " ".join(p.title.split()), "text": f"{sid}.txt"})
        except Exception as e:  # noqa: BLE001
            rec["error"] = repr(e)
        man["results"].append(rec)
        print(rec["id"], rec.get("status"), rec.get("last_modified"), (rec.get("sha256") or "")[:16], rec.get("final_url") if rec.get("final_url") != url else "", rec.get("error", ""), flush=True)
    name = "web_manifest.json" if not ids else f"web_manifest_extra_{ts}.json"
    (OUT / name).write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- 条文のテキスト化（担当の render とは別に書いた）
def text_of(n):
    if isinstance(n, str):
        return n
    if n.get("tag") == "Rt":
        return ""
    return "".join(text_of(c) for c in n.get("children", []))


def kids(n, tag=None):
    return [c for c in n.get("children", []) if isinstance(c, dict) and (tag is None or c.get("tag") == tag)]


def walk(n, fn, anc=()):
    if isinstance(n, dict):
        fn(n, anc)
        for c in n.get("children", []):
            walk(c, fn, anc + (n,))


class Law:
    def __init__(self, path):
        d = json.loads(pathlib.Path(path).read_bytes())
        self.rev = d.get("revision_info") or {}
        self.root = d["law_full_text"]
        self.main, self.suppl, self.appdx = {}, [], []

        def fn(n, anc):
            t = n.get("tag")
            in_suppl = any(a.get("tag") == "SupplProvision" for a in anc)
            if t == "Article" and not in_suppl:
                self.main.setdefault(n["attr"].get("Num"), n)
            elif t == "SupplProvision":
                self.suppl.append(n)
            elif t == "AppdxTable":
                self.appdx.append(n)
        walk(self.root, fn)

    def suppl_of(self, amend):
        """amend が None なら原始附則、そうでなければ AmendLawNum が正規表現 amend に当たる改正附則。"""
        out = []
        for s in self.suppl:
            an = s.get("attr", {}).get("AmendLawNum") or ""
            if amend is None and not an:
                out.append(s)
            elif amend is not None and an and re.search(amend, an):
                out.append(s)
        return out

    def caption(self, num):
        a = self.main.get(num)
        if a is None:
            return None
        return "".join(text_of(c) for c in kids(a, "ArticleCaption"))


def locate(node, path):
    """path の例：'1/31'（第1項第31号）、'1/30/イ'、'2'。段は Paragraph(Num) → Item(Num) → Subitem1..3（Num か見出し）。"""
    cur = node
    if not path:
        return cur
    levels = ["Paragraph", "Item", "Subitem1", "Subitem2", "Subitem3"]
    for lvl, st in zip(levels, path.split("/")):
        found = None
        for c in kids(cur, lvl):
            num = c.get("attr", {}).get("Num")
            title = "".join(text_of(t) for t in kids(c) if t.get("tag", "").endswith("Title"))
            if num == st or title == st:
                found = c
                break
        if found is None:
            return None
        cur = found
    return cur


def norm(s):
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub("[−－‐‑]", "-", s)
    return re.sub(r"\s", "", s)


def has_all(text, frags):
    t = norm(text)
    pos = 0
    for f in frags:
        f = norm(f)
        i = t.find(f, pos)
        if i < 0:
            return False, f
        pos = i + len(f)
    return True, None


# ---------------------------------------------------------------- 照合する項目
S_ALL = S5
S_R78 = ["2025-12-31", "2026-11-09", "2026-12-31"]
C_ALL = ["2026-01-01", "2026-11-09", "2027-01-01"]
R3_11 = r"令和三年.*法律第(十一|一一)号"
R7_120 = r"令和七年.*政令第(百二十|一二〇)号"
R7_MOF18 = r"令和七年.*財務省令第(十八|一八)号"
R8_12 = r"令和八年.*法律第(十二|一二)号"


def claims():
    C = []

    def law(cid, where, what, short, asofs, part, art, path, frags):
        lst = asofs if isinstance(asofs, list) else [asofs]
        for a in lst:
            C.append((f"{cid}@{a}" if len(lst) > 1 else cid, where, what, "law", (short, a, part, art, path, frags)))

    def nolaw(cid, where, what, short, asofs, part, art, path, frag):
        lst = asofs if isinstance(asofs, list) else [asofs]
        for a in lst:
            C.append((f"{cid}@{a}" if len(lst) > 1 else cid, where, what, "nolaw", (short, a, part, art, path, frag)))

    def cap(cid, where, what, short, asof, art, frag):
        C.append((cid, where, what, "caption", (short, asof, art, frag)))

    def web(cid, where, what, sid, frags):
        C.append((cid, where, what, "web", (sid, frags)))

    def meta(cid, where, what, sid, lm, sha):
        C.append((cid, where, what, "webmeta", (sid, lm, sha)))

    def calc(cid, where, what, got, expect):
        C.append((cid, where, what, "calc", (got, expect)))

    # ---- 版（[M] §2） ----
    revs = [
        ("shotoku", "2024-12-31", "340AC0000000033_20240612_506AC0000000047", "PreviousEnforced"),
        ("shotoku", "2025-12-31", "340AC0000000033_20251218_507AC0000000013", "PreviousEnforced"),
        ("shotoku", "2026-11-09", "340AC0000000033_20261001_507AC0000000070", "CurrentEnforced"),
        ("shotoku", "2026-12-31", "340AC0000000033_20261201_508AC0000000012", "UnEnforced"),
        ("shotoku", "2027-01-01", "340AC0000000033_20270101_508AC0000000012", "UnEnforced"),
        ("shotoku-rei", "2024-12-31", "340CO0000000096_20241202_506CO0000000141", "PreviousEnforced"),
        ("shotoku-rei", "2025-12-31", "340CO0000000096_20251201_507CO0000000120", "PreviousEnforced"),
        ("shotoku-rei", "2026-11-09", "340CO0000000096_20260522_508CO0000000093", "CurrentEnforced"),
        ("shotoku-rei", "2026-12-31", "340CO0000000096_20261201_508CO0000000093", "UnEnforced"),
        ("shotoku-rei", "2027-01-01", "340CO0000000096_20270101_508CO0000000093", "UnEnforced"),
        ("shotoku-ki", "2025-12-31", "340M50000040011_20251201_507M60000040018", "PreviousEnforced"),
        ("shotoku-ki", "2026-11-09", "340M50000040011_20261001_507M60000040018", "CurrentEnforced"),
        ("shotoku-ki", "2027-01-01", "340M50000040011_20270101_508M60000040017", "UnEnforced"),
        ("sochi", "2025-12-31", "332AC0000000026_20251231_507AC1000000081", "PreviousEnforced"),
        ("sochi", "2026-11-09", "332AC0000000026_20261101_507AC0000000013", "CurrentEnforced"),
        ("sochi", "2027-01-01", "332AC0000000026_20270101_508AC0000000012", "UnEnforced"),
        ("fukko", "2025-12-31", "423AC0000000117_20250601_504AC0000000068", "PreviousEnforced"),
        ("fukko", "2026-11-09", "423AC0000000117_20260401_508AC0000000012", "CurrentEnforced"),
        ("fukko", "2027-01-01", "423AC0000000117_20270101_508AC0000000012", "UnEnforced"),
        ("tsusoku", "2026-11-09", "337AC0000000066_20261101_507AC0000000013", "CurrentEnforced"),
        ("chiho", "2026-01-01", "325AC0000000226_20260101_507AC0000000041", "PreviousEnforced"),
        ("chiho", "2026-11-09", "325AC0000000226_20261101_508AC0000000002", "CurrentEnforced"),
        ("chiho", "2027-01-01", "325AC0000000226_20270101_508AC0000000002", "UnEnforced"),
        ("chiho-rei", "2026-11-09", "325CO0000000245_20261101_508CO0000000083", "CurrentEnforced"),
        ("chiho-rei", "2027-01-01", "325CO0000000245_20270101_508CO0000000083", "UnEnforced"),
        ("kokuho-rei", "2026-11-09", "333CO0000000362_20260801_508CO0000000240", "CurrentEnforced"),
    ]
    for s, a, rid, st in revs:
        C.append((f"rev:{s}@{a}", "M §2・PS §0.1", f"{s} asof {a} の版 {rid}（{st}）", "rev", (s, a, rid, st)))

    # ---- [PS] §1.1 範囲 ----
    law("PS1.1-30-1", "PS §1.1", "所法30①の定義", "shotoku", S_ALL, "main", "30", "1",
        ["退職所得とは、退職手当、一時恩給その他の退職により一時に受ける給与及びこれらの性質を有する給与（以下この条において「退職手当等」という。）に係る所得をいう。"])
    law("PS1.1-31", "PS §1.1", "所法31 柱書と第1〜3号", "shotoku", S_ALL, "main", "31", "1",
        ["次に掲げる一時金は、この法律の規定の適用については、前条第一項に規定する退職手当等とみなす。",
         "国民年金法", "厚生年金保険法", "政令で定めるもの", "石炭鉱業年金基金法", "確定給付企業年金法", "の規定に基づいて支給を受ける一時金で", "加入者の退職により支払われるもの",
         "加入者の負担した金額", "控除した金額に相当する部分に限る", "その他これに類する一時金として政令で定めるもの"])
    nolaw("X-31-no-para3", "PS §1.1・§4.2・H4", "反証：所法31 は1項だけ（第3項は無い）。「所法31③」は「所法31三」の誤り", "shotoku", "2026-11-09", "main", "31", "3", None)
    law("PS1.1-31-item3", "PS §1.1・§4.2・H4", "所法31 第3号（確定給付企業年金法の一時金、加入者の負担した金額）", "shotoku", "2026-11-09", "main", "31", "1/3",
        ["確定給付企業年金法", "加入者の負担した金額", "その他これに類する一時金として政令で定めるもの"])
    law("X-rei72-3", "PS §1.1", "反証：所令72③ の柱書は「法第三十一条第三号」（所法31③ ではない）", "shotoku-rei", S_ALL, "main", "72", "3",
        ["法第三十一条第三号"])
    law("PS1.1-rei72-3-1", "PS §1.1", "所令72③一 特定退職金共済団体", "shotoku-rei", "2026-11-09", "main", "72", "3/1", ["特定退職金共済団体"])
    law("PS1.1-rei72-3-2", "PS §1.1", "所令72③二 中小企業退職金共済法", "shotoku-rei", "2026-11-09", "main", "72", "3/2", ["中小企業退職金共済法"])
    law("PS1.1-rei72-3-3", "PS §1.1", "所令72③三 小規模企業共済", "shotoku-rei", "2026-11-09", "main", "72", "3/3", ["小規模企業共済"])
    law("PS1.1-rei72-3-7", "PS §1.1", "所令72③七 確定拠出年金法 老齢給付金 一時金", "shotoku-rei", S_ALL, "main", "72", "3/7",
        ["確定拠出年金法", "企業型年金規約又は", "個人型年金規約に基づいて", "第二十八条第一号", "老齢給付金として支給される一時金"])
    law("PS1.1-sochi29_4", "PS §1.1", "措法29の4 未払賃金を退職手当等とみなす", "sochi", ["2025-12-31", "2026-11-09"], "main", "29_4", "",
        ["賃金の支払の確保等に関する法律", "第七条", "退職した労働者が", "弁済を受けた金額は", "退職手当等の金額とみなして"])
    law("X-sochi29_5", "PS §1.1・M §3・H2・H11", "反証：措法29の5 は asof 2026-12-31 で既に未払賃金の規定（2027年からではない）", "sochi", ["2026-12-31", "2027-01-01"], "main", "29_5", "",
        ["賃金の支払の確保等に関する法律", "第七条", "退職した労働者が", "弁済を受けた金額は", "退職手当等の金額とみなして"])
    cap("X-sochi29_4cap-1231", "M §3・H2・H11", "措法29の4 の見出し（asof 2026-12-31）＝給与所得控除の最低控除額等の特例（移動は令和8年12月1日）", "sochi", "2026-12-31", "29_4", "給与所得控除の最低控除額等の特例")
    law("X-r8-12-1-4-ro-29_5", "M §3・H2・H11", "令和8年法律第12号附則第1条第4号（令和八年十二月一日）に措法第二十九条の四を第二十九条の五とする改正規定", "sochi", "2026-12-31", "suppl:" + R8_12, "1", "1/4",
        ["令和八年十二月一日", "第二十九条の四を第二十九条の五とし"])
    cap("PS1.1-sochi29_4cap", "PS §1.1・M §3", "措法29の4 の見出し（asof 2027-01-01）", "sochi", "2027-01-01", "29_4", "給与所得控除の最低控除額等の特例")
    law("PS1.1-chiho23-6", "PS §1.1", "地法23①六（措法第二十九条の四）", "chiho", ["2026-01-01", "2026-11-09"], "main", "23", "1/6",
        ["所得税法第三十条第一項に規定する退職手当等（同法第三十一条において退職手当等とみなされる一時金及び租税特別措置法第二十九条の四において退職手当等とみなされる金額を含む。）"])
    law("PS1.1-chiho23-6b", "PS §1.1", "地法23①六（asof 2027-01-01 で第二十九条の五）", "chiho", "2027-01-01", "main", "23", "1/6", ["租税特別措置法第二十九条の五"])
    law("PS1.1-chiho292-6", "PS §1.1", "地法292①六（措法第二十九条の四）", "chiho", ["2026-01-01", "2026-11-09"], "main", "292", "1/6",
        ["所得税法第三十条第一項に規定する退職手当等", "租税特別措置法第二十九条の四"])
    law("PS1.1-chiho292-6b", "PS §1.1", "地法292①六（asof 2027-01-01 で第二十九条の五）", "chiho", "2027-01-01", "main", "292", "1/6", ["租税特別措置法第二十九条の五"])
    law("PS1.2-rei77", "PS §1.2", "所令77 一の勤務先の退職で二以上の退職手当等→最初に支払を受けるべき日の年", "shotoku-rei", S_ALL, "main", "77", "",
        ["一の勤務先を退職することにより二以上の", "退職手当等の支払を受ける権利を有することとなる場合には", "これらのうち最初に支払を受けるべきものの支払を受けるべき日の属する年"])

    # ---- [PS] §2.1 所法30②〜⑦ ----
    law("PS2.1-30-2", "PS §2.1", "所法30② 本則の式（1/2、短期、特定役員）", "shotoku", S_ALL, "main", "30", "2",
        ["退職所得の金額は、その年中の退職手当等の収入金額から退職所得控除額を控除した残額の二分の一に相当する金額", "短期退職手当等である場合には", "特定役員退職手当等である場合には当該退職手当等の収入金額から退職所得控除額を控除した残額に相当する金額"])
    law("PS2.1-30-2-1", "PS §2.1", "所法30②一 三百万円以下→二分の一", "shotoku", S_ALL, "main", "30", "2/1", ["三百万円以下である場合", "当該残額の二分の一に相当する金額"])
    law("PS2.1-30-2-2", "PS §2.1", "所法30②二 百五十万円＋(収入−(三百万円＋控除))", "shotoku", S_ALL, "main", "30", "2/2",
        ["百五十万円と当該退職手当等の収入金額から三百万円に退職所得控除額を加算した金額を控除した残額との合計額"])
    law("PS2.1-30-3-1", "PS §2.1", "所法30③一 四十万円×勤続年数（二十年以下）", "shotoku", S_ALL, "main", "30", "3/1", ["二十年以下", "四十万円に当該勤続年数を乗じて計算した金額"])
    law("PS2.1-30-3-2", "PS §2.1", "所法30③二 八百万円＋七十万円×(勤続年数−二十年)", "shotoku", S_ALL, "main", "30", "3/2", ["二十年を超える", "八百万円と七十万円に当該勤続年数から二十年を控除した年数を乗じて計算した金額との合計額"])
    law("PS2.1-30-4", "PS §2.1", "所法30④ 短期退職手当等（五年以下）", "shotoku", S_ALL, "main", "30", "4",
        ["短期退職手当等", "短期勤続年数", "役員等以外の者として", "五年以下", "特定役員退職手当等に該当しないもの"])
    law("PS2.1-30-5", "PS §2.1", "所法30⑤ 特定役員退職手当等（役員等勤続年数 五年以下）", "shotoku", S_ALL, "main", "30", "5",
        ["特定役員退職手当等", "役員等勤続年数", "五年以下"])
    law("PS2.1-30-5-1", "PS §2.1", "所法30⑤一 法人税法第二条第十五号の役員", "shotoku", S_ALL, "main", "30", "5/1", ["法人税法第二条第十五号"])
    law("PS2.1-30-5-2", "PS §2.1", "所法30⑤二 国会議員・地方議会の議員", "shotoku", S_ALL, "main", "30", "5/2", ["国会議員", "地方公共団体の議会の議員"])
    law("PS2.1-30-5-3", "PS §2.1", "所法30⑤三 国家公務員・地方公務員", "shotoku", S_ALL, "main", "30", "5/3", ["国家公務員", "地方公務員"])
    law("PS2.1-30-6-1", "PS §2.1", "所法30⑥一 前年以前の他の退職手当等", "shotoku", S_ALL, "main", "30", "6/1",
        ["前年以前に他の退職手当等の支払を受けている場合で政令で定める場合", "当該他の退職手当等につき政令で定めるところにより同項の規定に準じて計算した金額を控除した金額"])
    law("PS2.1-30-6-2", "PS §2.1", "所法30⑥二 八十万円に満たない場合は八十万円", "shotoku", S_ALL, "main", "30", "6/2", ["八十万円に満たない場合", "八十万円"])
    law("PS2.1-30-6-3", "PS §2.1", "所法30⑥三 障害者になつたことに直接基因して退職、百万円を加算", "shotoku", S_ALL, "main", "30", "6/3",
        ["障害者になつたことに直接基因して退職したと認められる場合で政令で定める場合", "百万円を加算した金額"])
    law("PS2.1-30-7", "PS §2.1", "所法30⑦ 二以上ある場合の重複期間は政令", "shotoku", S_ALL, "main", "30", "7",
        ["一般退職手当等", "短期退職手当等", "特定役員退職手当等", "二以上", "重複している期間", "政令で定める"])

    # ---- [PS] §2.2 勤続年数 ----
    law("PS2.2-rei69-1-1", "PS §2.2", "所令69①一 退職の日まで引き続き勤務した期間", "shotoku-rei", S_ALL, "main", "69", "1/1", ["引き続き勤務した期間"])
    law("PS2.2-rei69-1-2", "PS §2.2", "所令69①二 退職一時金等は組合員等であった期間", "shotoku-rei", S_ALL, "main", "69", "1/2", ["組合員等であつた期間"])
    law("PS2.2-rei69-1-2b", "PS §2.2", "所令69①二 第七十二条第三項第七号の一時金は企業型年金加入者期間等と重複しない個人型年金加入者期間を合算", "shotoku-rei", "2026-11-09", "main", "69", "1/2",
        ["第七十二条第三項第七号", "企業型年金加入者期間", "個人型年金加入者期間"])
    law("PS2.2-rei69-1-3", "PS §2.2", "所令69①三 二以上の退職手当等→最も長い期間＋重複していない期間", "shotoku-rei", S_ALL, "main", "69", "1/3", ["最も長い期間により勤続年数を計算する", "重複していない勤続期間等について", "その最も長い期間に加算"])
    law("PS2.2-rei69-2", "PS §2.2", "所令69② 一年未満の端数は一年", "shotoku-rei", S_ALL, "main", "69", "2",
        ["前項各号の規定により計算した期間に一年未満の端数を生じたときは、これを一年として同項の勤続年数を計算する。"])
    law("PS2.2-rei69_2", "PS §2.2", "所令69の2 短期・特定役員の勤続年数", "shotoku-rei", S_ALL, "main", "69_2", "", ["役員等以外の者として勤務した期間", "役員等として勤務した期間"])

    # ---- [PS] §2.3 所令70 ----
    law("PS2.3-rei70-1-1", "PS §2.3", "所令70①一", "shotoku-rei", S_ALL, "main", "70", "1/1", ["第六十九条第一項第一号ロ", "前に退職手当等", "の支払を受けている場合"])
    law("PS2.3-rei70-1-2-old", "PS §2.3", "所令70①二 改正前（四年内、十九年内）", "shotoku-rei", ["2024-12-31", "2025-12-31"], "main", "70", "1/2",
        ["その年の前年以前四年内", "十九年内"])
    law("PS2.3-rei70-1-2-i", "PS §2.3", "所令70①二イ（四年内）", "shotoku-rei", ["2026-11-09", "2026-12-31", "2027-01-01"], "main", "70", "1/2/イ",
        ["その年の前年以前四年内に退職手当等", "の支払を受け、かつ、その年に退職手当等の支払を受けた場合（ロ及びハに掲げる場合に該当する場合を除く。）", "その年の前年以前四年内に支払を受けた退職手当等"])
    law("PS2.3-rei70-1-2-ro", "PS §2.3", "所令70①二ロ（九年内、令和八年一月一日以後）", "shotoku-rei", ["2026-11-09", "2026-12-31", "2027-01-01"], "main", "70", "1/2/ロ",
        ["その年の前年以前九年内に第七十二条第三項第七号", "に掲げる一時金（令和八年一月一日以後に支払を受けたものに限り", "の支払を受け、かつ、その年に退職手当等の支払を受けた場合（ハに掲げる場合に該当する場合を除く。）",
         "令和八年一月一日以後に支払を受けた退職手当等であつてその年の前年以前九年内に支払を受けたもの", "令和八年一月一日前に支払を受けた退職手当等であつてその年の前年以前四年内に支払を受けたもの"])
    law("PS2.3-rei70-1-2-ha", "PS §2.3", "所令70①二ハ（十九年内）", "shotoku-rei", ["2026-11-09", "2026-12-31", "2027-01-01"], "main", "70", "1/2/ハ",
        ["その年の前年以前十九年内に退職手当等", "の支払を受け、かつ、その年に第七十二条第三項第七号", "に掲げる一時金の支払を受けた場合", "その年の前年以前十九年内に支払を受けた退職手当等"])
    law("PS2.3-rei70-2", "PS §2.3", "所令70② 収入金額が控除額に満たない場合のみなし期間", "shotoku-rei", S_ALL, "main", "70", "2",
        ["一に満たない端数を生じたときは、これを切り捨てた数"])
    law("PS2.3-rei70-2-1", "PS §2.3", "所令70②一 八百万円以下→四十万円で除した数", "shotoku-rei", S_ALL, "main", "70", "2/1", ["八百万円以下", "四十万円で除して計算した数"])
    law("PS2.3-rei70-2-2", "PS §2.3", "所令70②二 八百万円超→(収入−八百万円)/七十万円＋二十", "shotoku-rei", S_ALL, "main", "70", "2/2",
        ["八百万円を控除した金額を七十万円で除して計算した数に二十を加算した数"])
    law("PS2.3-rei70-3", "PS §2.3", "所令70③ 一年未満の端数は切り捨て", "shotoku-rei", S_ALL, "main", "70", "3", ["第一項第一号の期間及び同項第二号の重複している部分の期間に一年未満の端数があるときは、その端数を切り捨てる"])
    law("PS2.3-r7-120-4", "PS §2.3・H3", "令和7年政令第120号附則第4条（新令第七十条第一項第二号は令和八年分以後）", "shotoku-rei", "2026-11-09", "suppl:" + R7_120, "4", "",
        ["新令第七十条第一項（第二号に係る部分に限る。）の規定は、令和八年分以後の所得税について適用し、令和七年分以前の所得税については、なお従前の例による。"])
    law("PS2.3-ki77-6", "PS §2.3", "所規77⑥ただし書（七年、令第七十二条第三項第七号の一時金は十年）", "shotoku-ki", ["2026-11-09", "2027-01-01"], "main", "77", "6",
        ["七年", "令第七十二条第三項第七号", "十年"])
    nolaw("PS2.3-ki77-6-old", "PS §2.3", "所規77⑥（asof 2025-12-31）に「十年」は無い", "shotoku-ki", "2025-12-31", "main", "77", "6", "十年")
    law("PS2.3-mof18-5", "PS §2.3", "令和7年財務省令第18号附則第5条（令和八年一月一日以後に支払を受けるべき退職手当等）", "shotoku-ki", "2026-11-09", "suppl:" + R7_MOF18, "5", "",
        ["第七十七条第六項", "令和八年一月一日以後に支払を受けるべき", "退職手当等"])
    law("PS2.3-mof18-8", "PS §2.3", "令和7年財務省令第18号附則第8条（新規則第九十四条は令和八年一月一日以後に支払うべき退職手当等）", "shotoku-ki", "2026-11-09", "suppl:" + R7_MOF18, "8", "",
        ["新規則第九十四条", "令和八年一月一日以後に支払うべき", "退職手当等について適用"])

    # ---- [PS] §2.4 ----
    law("PS2.4-rei71", "PS §2.4", "所令71 障害退職の要件", "shotoku-rei", S_ALL, "main", "71", "",
        ["在職中に障害者に該当することとなつたことにより、その該当することとなつた日以後全く又はほとんど勤務に服さないで退職した場合"])
    law("PS2.4-rei71_2-13", "PS §2.4", "所令71の2⑬ 他の使用人に対する退職給与の支給の水準等を勘案して相当と認められる金額", "shotoku-rei", S_ALL, "main", "71_2", "13",
        ["他の使用人に対する退職給与の支給の水準等を勘案して相当と認められる金額"])
    law("PS2.4-r3-11-5", "PS §2.4", "令和3年法律第11号附則第5条（新所得税法第三十条は令和四年分以後）", "shotoku", "2026-11-09", "suppl:" + R3_11, "5", "",
        ["新所得税法第三十条の規定は、令和四年分以後の所得税について適用し、令和三年分以前の所得税については、なお従前の例による。"])
    law("PS2.4-r3-11-9", "PS §2.4", "令和3年法律第11号附則第9条（第201条は令和4年1月1日以後に支払うべき退職手当等、第203条第1項は以後に支払を受けるべき退職手当等の申告書）", "shotoku", "2026-11-09", "suppl:" + R3_11, "9", "",
        ["新所得税法第二百一条", "令和四年一月一日以後に支払うべき退職手当等", "第二百三条第一項", "令和四年一月一日以後に支払を受けるべき退職手当等"])

    # ---- [PS] §3 復興 ----
    law("PS3-fukko13", "PS §3", "復興法13 百分の二・一", "fukko", ["2025-12-31", "2026-11-09"], "main", "13", "", ["百分の二・一"])
    law("PS3-fukko13b", "PS §3", "復興法13 asof 2027-01-01 百分の一・一", "fukko", "2027-01-01", "main", "13", "", ["百分の一・一"])
    law("PS4.2-fukko28-1", "PS §4.2", "復興法28① 第四編第一章から第六章、平成二十五年一月一日から令和十九年十二月三十一日", "fukko", ["2025-12-31", "2026-11-09"], "main", "28", "1",
        ["所得税法第四編第一章から第六章まで", "平成二十五年一月一日から令和十九年十二月三十一日までの間に行うべきもの", "復興特別所得税を併せて徴収"])
    law("PS4.2-fukko28-2", "PS §4.2", "復興法28② 百分の二・一", "fukko", ["2025-12-31", "2026-11-09"], "main", "28", "2", ["百分の二・一"])
    law("PS4.2-fukko28-9", "PS §4.2", "復興法28⑨ 百二・一分の二・一／百二・一分の百", "fukko", ["2025-12-31", "2026-11-09"], "main", "28", "9", ["百二・一分の二・一", "百二・一分の百"])
    law("PS3-fukko28-2b", "PS §3", "復興法28② asof 2027-01-01 百分の一・一", "fukko", "2027-01-01", "main", "28", "2", ["百分の一・一"])

    # ---- [PS] §4.1 ----
    law("PS4.1-22-1", "PS §4.1", "所法22① 総所得金額、退職所得金額及び山林所得金額", "shotoku", S_ALL, "main", "22", "1", ["総所得金額、退職所得金額及び山林所得金額"])
    law("PS4.1-22-3", "PS §4.1", "所法22③ 退職所得金額は第69条・第70条・第71条の適用後", "shotoku", S_ALL, "main", "22", "3",
        ["退職所得金額又は山林所得金額は", "退職所得の金額", "第六十九条、第七十条又は第七十一条", "適用後の金額"])
    law("PS4.1-69-1", "PS §4.1", "所法69①", "shotoku", S_ALL, "main", "69", "1",
        ["総所得金額、退職所得金額又は山林所得金額を計算する場合において、不動産所得の金額、事業所得の金額、山林所得の金額又は譲渡所得の金額の計算上生じた損失の金額があるときは、政令で定める順序により、これを他の各種所得の金額から控除する。"])
    law("PS4.1-87-2", "PS §4.1", "所法87② 総所得金額、山林所得金額又は退職所得金額から順次控除", "shotoku", S_ALL, "main", "87", "2", ["総所得金額、山林所得金額又は退職所得金額から順次控除する"])
    law("PS4.1-89-1", "PS §4.1", "所法89① 課税総所得金額又は課税退職所得金額をそれぞれ", "shotoku", S_ALL, "main", "89", "1",
        ["課税総所得金額又は課税退職所得金額をそれぞれ", "百九十五万円以下の金額", "百分の五", "三百三十万円以下の金額", "百分の十", "六百九十五万円以下の金額", "百分の二十",
         "九百万円以下の金額", "百分の二十三", "千八百万円以下の金額", "百分の三十三", "四千万円以下の金額", "百分の四十", "四千万円を超える金額", "百分の四十五"])
    law("PS4.1-89-2", "PS §4.1", "所法89② 課税退職所得金額の定義", "shotoku", S_ALL, "main", "89", "2", ["課税退職所得金額", "退職所得金額"])
    law("PS4.1-tsu118-1", "PS §4.1", "通則法118① 千円未満の端数を切り捨て", "tsusoku", "2026-11-09", "main", "118", "1", ["千円未満の端数があるとき", "切り捨てる"])
    law("PS4.1-tsu119-1", "PS §4.1", "通則法119① 百円未満の端数を切り捨て", "tsusoku", "2026-11-09", "main", "119", "1", ["百円未満の端数があるとき", "切り捨てる"])
    law("PS4.1-tsu119-2", "PS §4.1", "通則法119② 政令で定める国税の確定金額は一円未満を切り捨て", "tsusoku", "2026-11-09", "main", "119", "2", ["政令で定める国税", "一円未満の端数"])
    law("V-tsurei40-1", "PS §9-4・M §7・H9", "通令40① 通則法118②の国税＝源泉徴収の所得税（第190条と、第201条第1項の適用を受ける第199条を除く）", "tsusoku-rei", "2026-11-09", "main", "40", "1",
        ["法第百十八条第二項", "所得税法第四編第一章から第五章まで", "第百九十条", "第百九十九条", "第二百一条第一項", "の規定の適用を受ける場合に限る。）を除く。）の規定により徴収する所得税とする。"])
    law("V-tsurei40-2", "PS §9-4・M §7・H9", "通令40② 通則法119②の国税＝一 前項の国税、二 第190条・第192条", "tsusoku-rei", "2026-11-09", "main", "40", "2",
        ["法第百十九条第二項", "前項に規定する国税", "所得税法第百九十条又は第百九十二条"])
    law("PS4.1-120-1", "PS §4.1", "所法120① 柱書", "shotoku", S_ALL, "main", "120", "1",
        ["総所得金額、退職所得金額及び山林所得金額の合計額", "第八十七条第二項", "準じて控除した後の金額", "配当控除の額を超えるとき"])
    law("PS4.1-120-1-4", "PS §4.1・H6・I6", "所法120①四 源泉徴収をされた又はされるべき所得税の額", "shotoku", S_ALL, "main", "120", "1/4",
        ["総所得金額若しくは退職所得金額", "源泉徴収をされた又はされるべき所得税の額"])
    law("PS4.1-121-2", "PS §4.1", "所法121② 退職所得の申告不要（一・二号）", "shotoku", S_ALL, "main", "121", "2",
        ["その年において退職所得を有する居住者は、次の各号のいずれかに該当する場合には、前条第一項の規定にかかわらず、その年分の課税退職所得金額に係る所得税については、同項の規定による申告書を提出することを要しない。"])
    law("PS4.1-121-2-1", "PS §4.1", "所法121②一", "shotoku", S_ALL, "main", "121", "2/1",
        ["退職手当等", "の全部について第百九十九条", "及び第二百一条第一項", "の規定による所得税の徴収をされた又はされるべき場合"])
    law("PS4.1-121-2-2", "PS §4.1", "所法121②二", "shotoku", S_ALL, "main", "121", "2/2",
        ["前号に該当する場合を除き", "第八十九条", "の規定を適用して計算した所得税の額がその年分の退職所得に係る退職手当等につき源泉徴収をされた又はされるべき所得税の額以下である場合"])
    law("PS4.1-121-1-1", "PS §4.1・H5", "所法121①一 給与所得及び退職所得以外の所得金額 二十万円以下", "shotoku", S_ALL, "main", "121", "1/1",
        ["給与所得及び退職所得以外の所得金額", "二十万円以下"])
    law("PS4.1-122-1", "PS §4.1", "所法122① 還付を受けるための申告書", "shotoku", S_ALL, "main", "122", "1", ["還付を受けるため"])

    # ---- [PS] §4.2 源泉徴収 ----
    law("PS4.2-199", "PS §4.2", "所法199 退職手当等の支払の際に徴収、翌月十日", "shotoku", S_ALL, "main", "199", "",
        ["居住者に対し国内において第三十条第一項", "に規定する退職手当等", "の支払をする者は、その支払の際", "翌月十日までに"])
    law("PS4.2-200", "PS §4.2", "所法200 常時二人以下の家事使用人のみ", "shotoku", S_ALL, "main", "200", "", ["常時二人以下の家事使用人のみ", "退職手当等"])
    law("PS4.2-201-1-1", "PS §4.2", "所法201①一イ・ロ・ハ（千円未満切捨て）", "shotoku", S_ALL, "main", "201", "1/1",
        ["がない旨の記載がある場合", "第八十九条第一項", "一般退職手当等", "千円未満の端数", "短期退職手当等", "三百万円以下", "百五十万円", "特定役員退職手当等", "千円未満の端数"])
    law("PS4.2-201-1-2", "PS §4.2", "所法201①二 支払済みの他の退職手当等がある旨の記載、ニ 政令で定めるところにより計算した金額", "shotoku", S_ALL, "main", "201", "1/2",
        ["支払済みの他の退職手当等がある旨の記載がある場合", "徴収された又は徴収されるべき所得税の額を控除した残額", "政令で定めるところにより計算した金額"])
    law("PS4.2-201-2", "PS §4.2", "所法201② 支払うべきことが確定した時の状況、別表第六", "shotoku", S_ALL, "main", "201", "2",
        ["支払うべきことが確定した時の状況", "別表第六"])
    law("PS4.2-201-3", "PS §4.2", "所法201③ 申告書なし→百分の二十", "shotoku", S_ALL, "main", "201", "3",
        ["退職所得の受給に関する申告書を提出していないとき", "百分の二十の税率を乗じて計算した金額に相当する税額"])
    law("PS4.2-202", "PS §4.2", "所法202（第三十一条第三号の一時金、加入者の負担した金額）", "shotoku", S_ALL, "main", "202", "",
        ["第三十一条", "加入者の負担した金額"])
    law("PS4.2-203-1", "PS §4.2", "所法203① 申告書の記載事項（一〜五）", "shotoku", S_ALL, "main", "203", "1",
        ["支払を受ける時までに", "退職手当等の支払者の氏名又は名称", "支払済みの他の退職手当等", "勤続年数", "財務省令で定める事項"])
    law("PS4.2-203-6", "PS §4.2", "所法203⑥ 退職所得の受給に関する申告書という", "shotoku", S_ALL, "main", "203", "6", ["第一項の規定による申告書は、退職所得の受給に関する申告書という。"])
    law("PS4.2-203-2", "PS §4.2", "所法203② 第200条の支払者の退職手当等は含まない", "shotoku", S_ALL, "main", "203", "2", ["第二百条", "含まれないものとする"])
    law("PS4.2-203-4", "PS §4.2", "所法203④ 電磁的方法による提供", "shotoku", S_ALL, "main", "203", "4", ["電磁的方法により提供することができる"])
    law("X-202-31-3", "PS §1.1・§4.2・H4", "反証：所法202 の冒頭は「第三十一条第三号」", "shotoku", S_ALL, "main", "202", "", ["第三十一条第三号"])
    law("PS4.2-ki77-1", "PS §4.2", "所規77① 申告書の記載事項", "shotoku-ki", ["2025-12-31", "2026-11-09"], "main", "77", "1", ["個人番号", "勤続年数"])
    law("PS4.2-rei319_3", "PS §4.2", "所令319の3① 法第二百一条第一項第二号ニ", "shotoku-rei", S_ALL, "main", "319_3", "1", ["法第二百一条第一項第二号ニ"])

    # ---- [PS] §5.1 合計所得金額・勤労学生 ----
    law("PS5.1-2-30i2", "PS §5.1", "所法2①三十イ(2) 合計所得金額の定義", "shotoku", S_ALL, "main", "2", "1/30/イ/（２）",
        ["第七十条", "及び第七十一条", "の規定を適用しないで計算した場合における第二十二条", "に規定する総所得金額、退職所得金額及び山林所得金額の合計額（以下この条において「合計所得金額」という。）"])
    law("PS5.1-2-32a", "PS §5.1", "所法2①三十二 勤労学生 八十五万円（令和7年分の版）", "shotoku", ["2025-12-31", "2026-11-09"], "main", "2", "1/32",
        ["自己の勤労に基づいて得た事業所得、給与所得、退職所得又は雑所得（以下この号において「給与所得等」という。）を有するもののうち、合計所得金額が八十五万円以下であり、かつ、合計所得金額のうち給与所得等以外の所得に係る部分の金額が十万円以下であるもの"])
    law("PS5.1-2-32b", "PS §5.1", "所法2①三十二 勤労学生 八十九万円（asof 2026-12-31・2027-01-01）", "shotoku", ["2026-12-31", "2027-01-01"], "main", "2", "1/32",
        ["退職所得又は雑所得（以下この号において「給与所得等」という。）", "合計所得金額が八十九万円以下"])
    law("PS5.1-2-32c", "M §3", "所法2①三十二 勤労学生 七十五万円（asof 2024-12-31）", "shotoku", "2024-12-31", "main", "2", "1/32", ["合計所得金額が七十五万円以下"])
    law("PS5.1-2-33a", "PS §5.1", "所法2①三十三 同一生計配偶者 五十八万円以下", "shotoku", ["2025-12-31", "2026-11-09"], "main", "2", "1/33", ["五十八万円以下"])
    law("PS5.1-2-33b", "PS §5.1", "所法2①三十三 六十二万円以下（asof 2026-12-31 以後）", "shotoku", ["2026-12-31", "2027-01-01"], "main", "2", "1/33", ["六十二万円以下"])
    law("PS5.1-2-34a", "PS §5.1", "所法2①三十四 扶養親族 五十八万円以下", "shotoku", ["2025-12-31", "2026-11-09"], "main", "2", "1/34", ["五十八万円以下"])
    law("PS5.1-2-34b", "PS §5.1", "所法2①三十四 六十二万円以下（asof 2026-12-31 以後）", "shotoku", ["2026-12-31", "2027-01-01"], "main", "2", "1/34", ["六十二万円以下"])
    law("PS5.1-rei11_2-2", "PS §5.1", "所令11の2② 総所得金額、退職所得金額及び山林所得金額の合計額", "shotoku-rei", S_ALL, "main", "11_2", "2", ["総所得金額、退職所得金額及び山林所得金額の合計額"])
    law("PS5.1-rei219-2-2", "PS §5.1", "所令219②二 同じ合計額の比較", "shotoku-rei", S_ALL, "main", "219", "2/2", ["総所得金額、退職所得金額及び山林所得金額の合計額"])
    # 令和8年分の基準額の適用（[H] H5・[I] I3 の「令和8年分62万円」）
    law("H5-r8-12-2", "H5・I3", "令和8年法律第12号附則第2条第1項（新所得税法第2条第1項（第32号（ロ除く）・第33号・第34号）は令和八年分以後）", "shotoku", "2026-12-31", "suppl:" + R8_12, "2", "1",
        ["新所得税法", "第二条第一項（第三十二号（ロに係る部分を除く。）、第三十三号及び第三十四号に係る部分に限る。）の規定は、令和八年分以後の所得税について適用"])
    law("X-r8-12-9", "H5・I4", "令和8年法律第12号附則第9条（新所得税法第86条は令和八年分以後）", "shotoku", "2026-12-31", "suppl:" + R8_12, "9", "1",
        ["新所得税法第八十六条の規定は、令和八年分以後の所得税について適用し、令和七年分以前の所得税については、なお従前の例による。"])
    law("X-r8-12-1-4", "H5・I4", "令和8年法律第12号附則第1条第4号（令和八年十二月一日施行：措法41の16の2①の改正）", "sochi", "2026-12-31", "suppl:" + R8_12, "1", "1/4",
        ["令和八年十二月一日", "第四十一条の十六の二の見出しの改正規定、同条第一項の改正規定"])
    # 配偶者特別控除・配偶者控除・寡婦・ひとり親・特定親族（[H] H5・[I] I4）
    law("H5-83_2-133", "H5", "所法83の2① 配偶者特別控除 合計所得金額 百三十三万円以下", "shotoku", ["2025-12-31", "2026-12-31"], "main", "83_2", "1", ["百三十三万円以下"])
    law("H5-2-33_2", "H5", "所法2①三十三の二 控除対象配偶者 合計所得金額 千万円以下", "shotoku", ["2025-12-31", "2026-12-31"], "main", "2", "1/33_2", ["千万円以下"])
    law("I4-83-900-950", "I4", "所法83① 本人の合計所得金額 九百万円・九百五十万円・千万円の段階", "shotoku", ["2025-12-31", "2026-12-31"], "main", "83", "1",
        ["九百万円以下", "九百万円を超え九百五十万円以下", "九百五十万円を超え千万円以下"])
    law("H5-2-30-500", "H5・I4", "所法2①三十・三十一 合計所得金額 五百万円以下", "shotoku", ["2025-12-31", "2026-12-31"], "main", "2", "1/31", ["合計所得金額が五百万円以下"])
    # 基礎控除の段階（[PS] §5.2 あらまし p.1、[H] H5、[I] I4）
    law("H5-86-1", "H5・I4", "所法86① 基礎控除（本則）の段階 二千三百五十万円以下", "shotoku", ["2025-12-31", "2026-12-31"], "main", "86", "1", ["二千三百五十万円以下"])
    law("H5-86-1-58", "H5・I4", "所法86①一 令和7年分の版 五十八万円", "shotoku", "2025-12-31", "main", "86", "1/1", ["五十八万円"])
    law("H5-86-1-62", "H5・I4", "所法86①一 asof 2026-12-31 六十二万円", "shotoku", "2026-12-31", "main", "86", "1/1", ["六十二万円"])
    law("H5-sochi41_16_2-r7", "H5・I4", "措法41の16の2①（asof 2025-12-31）百三十二万円・三百三十六万円・四百八十九万円・六百五十五万円", "sochi", "2025-12-31", "main", "41_16_2", "1",
        ["六百五十五万円", "百三十二万円以下", "三十七万円", "三百三十六万円以下", "三十万円", "四百八十九万円以下", "十万円", "五万円"])
    law("H5-sochi41_16_2-r8", "H5・I4", "措法41の16の2①（asof 2026-12-31）四百八十九万円以下 四十二万円", "sochi", "2026-12-31", "main", "41_16_2", "1",
        ["六百五十五万円", "四百八十九万円以下", "四十二万円"])
    nolaw("X-sochi41_16_2-r8-no336", "H5・I4",  "措法41の16の2①一（asof 2026-12-31。令和8年分・令和9年分）に「三百三十六万円」の段階は無い", "sochi", "2026-12-31", "main", "41_16_2", "1/1", "三百三十六万円")
    nolaw("X-sochi41_16_2-r8-no132i", "H5・I4",  "措法41の16の2①一（asof 2026-12-31）に「百三十二万円」の段階は無い", "sochi", "2026-12-31", "main", "41_16_2", "1/1", "百三十二万円")
    law("X-sochi41_16_2-r8-item1", "H5・I4", "措法41の16の2①一（asof 2026-12-31）令和八年分及び令和九年分 四百八十九万円以下 四十二万円、超える 五万円", "sochi", "2026-12-31", "main", "41_16_2", "1/1",
        ["令和八年分及び令和九年分", "四百八十九万円以下", "四十二万円", "四百八十九万円を超える", "五万円"])
    law("X-r8-12-45", "H5・I4", "令和8年法律第12号附則第45条第1項（令和7年分の措法41の16の2①の基礎控除の額は従前の例）", "sochi", "2026-12-31", "suppl:" + R8_12, "45", "1",
        ["令和七年分の所得税に係る旧租税特別措置法第四十一条の十六の二第一項に規定する基礎控除の額については、なお従前の例による。"])

    # ---- [PS] §6.1 住民税の分離課税 ----
    law("PS6.1-328", "PS §6.1", "地法328", "chiho", C_ALL, "main", "328", "",
        ["第二百九十四条第一項第一号の者が退職手当等（所得税法第百九十九条の規定によりその所得税を徴収して納付すべきものに限る。以下本款において同じ。）の支払を受ける場合には、当該退職手当等に係る所得割は、第三百十三条、第三百十四条の三及び第三百十八条の規定にかかわらず、当該退職手当等に係る所得を他の所得と区分し",
         "当該退職手当等の支払を受けるべき日の属する年の一月一日現在におけるその者の住所所在の市町村において課する。"])
    law("PS6.1-50_2", "PS §6.1", "地法50の2（第三十二条、第三十五条及び第三十九条の規定にかかわらず）", "chiho", C_ALL, "main", "50_2", "",
        ["第三十二条", "第三十五条", "第三十九条", "の規定にかかわらず", "他の所得と区分し"])
    law("PS6.1-328_2-1", "PS §6.1", "地法328の2①", "chiho", C_ALL, "main", "328_2", "1", ["分離課税に係る所得割の課税標準は、その年中の退職所得の金額とする。"])
    law("PS6.1-328_2-2", "PS §6.1", "地法328の2②", "chiho", C_ALL, "main", "328_2", "2", ["前項の退職所得の金額は、所得税法第三十条第二項に規定する退職所得の金額の計算の例によつて算定する。"])
    law("PS6.1-50_3", "PS §6.1", "地法50の3②（所得税法第三十条第二項の計算の例）", "chiho", C_ALL, "main", "50_3", "2", ["所得税法第三十条第二項に規定する退職所得の金額の計算の例"])
    law("PS6.1-328_3", "PS §6.1", "地法328の3 百分の六", "chiho", C_ALL, "main", "328_3", "", ["百分の六とする"])
    law("PS6.1-50_4", "PS §6.1", "地法50の4 百分の四", "chiho", C_ALL, "main", "50_4", "", ["百分の四とする"])
    nolaw("I11-328_3-nostd", "H7・I11", "地法328の3 に「標準税率」の語は無い", "chiho", C_ALL, "main", "328_3", "", "標準税率")
    nolaw("I11-50_4-nostd", "H7・I11", "地法50の4 に「標準税率」の語は無い", "chiho", C_ALL, "main", "50_4", "", "標準税率")
    law("PS6.1-328_4", "PS §6.1", "地法328の4 特別徴収の方法によらなければならない", "chiho", C_ALL, "main", "328_4", "", ["特別徴収の方法によらなければならない"])
    law("PS6.1-328_5", "PS §6.1", "地法328の5② 支払の際に徴収、翌月の十日まで、納入申告書", "chiho", C_ALL, "main", "328_5", "2", ["退職手当等の支払をする際", "翌月の十日までに", "納入申告書"])
    law("PS6.1-328_5-1", "PS §6.1", "地法328の5① 特別徴収義務者として指定", "chiho", C_ALL, "main", "328_5", "1", ["特別徴収義務者として指定"])
    law("PS6.1-328_6-1", "PS §6.1", "地法328の6①一・二", "chiho", C_ALL, "main", "328_6", "1", ["退職所得申告書", "がない旨の記載がある場合", "がある旨の記載がある場合"])
    law("PS6.1-328_6-2", "PS §6.1", "地法328の6② 申告書の提出がないとき", "chiho", C_ALL, "main", "328_6", "2",
        ["退職手当等の支払を受ける者がその支払を受ける時までに退職所得申告書を提出していないときは", "その支払う退職手当等の金額について第三百二十八条の二及び第三百二十八条の三の規定を適用して計算した税額とする。"])
    law("PS6.1-328_6-3", "PS §6.1", "地法328の6③ 支払うべきことが確定した時の状況", "chiho", C_ALL, "main", "328_6", "3", ["支払うべきことが確定した時の状況"])
    law("PS6.1-328_6-4", "PS §6.1", "地法328の6④ 所得税法第二百二条を準用", "chiho", C_ALL, "main", "328_6", "4", ["所得税法第二百二条"])
    law("PS6.1-328_7", "PS §6.1", "地法328の7 退職所得申告書（支払者を経由、一月一日現在の住所地の市町村長）", "chiho", C_ALL, "main", "328_7", "1", ["その退職手当等の支払者を経由して", "支払を受けるべき日の属する年の一月一日現在における住所所在地の市町村長に提出"])
    law("PS6.1-328_8", "PS §6.1", "地法328の8 十万円以下の過料", "chiho", C_ALL, "main", "328_8", "", ["十万円以下の過料"])
    law("PS6.1-328_13", "PS §6.1", "地法328の13 普通徴収", "chiho", C_ALL, "main", "328_13", "1", ["第三百二十八条の六第二項", "普通徴収の方法によつて徴収しなければならない"])
    law("PS6.1-328_14", "PS §6.1", "地法328の14 特別徴収票（退職の日以後一月以内）", "chiho", C_ALL, "main", "328_14", "", ["特別徴収票", "退職の日以後一月以内"])
    law("PS6.1-20_4_2-1", "PS §6.1", "地法20の4の2①", "chiho", C_ALL, "main", "20_4_2", "1",
        ["地方税の課税標準額を計算する場合において、その額に千円未満の端数があるとき、又はその全額が千円未満であるときは、その端数金額又はその全額を切り捨てる。ただし、政令で定める地方税については、この限りでない。"])
    law("PS6.1-20_4_2-3", "PS §6.1", "地法20の4の2③", "chiho", C_ALL, "main", "20_4_2", "3",
        ["地方税の確定金額に百円未満の端数があるとき、又はその全額が百円未満であるときは、その端数金額又はその全額を切り捨てる。"])
    law("PS6.1-20_4_2-8", "PS §6.1", "地法20の4の2⑧", "chiho", C_ALL, "main", "20_4_2", "8",
        ["第二項、第三項（地方税の確定金額の全額が百円未満であるときにおいて、その全額を切り捨てる部分に限る。）及び前三項の規定の適用については、個人の市町村民税", "それぞれ一の地方税とみなす"])

    # ---- [PS] §6.2 非課税 ----
    law("PS6.2-295-1", "PS §6.2", "地法295① 第二号に該当する者は分離課税に係る所得割を除く、百三十五万円", "chiho", C_ALL, "main", "295", "1",
        ["第二号に該当する者にあつては、第三百二十八条の規定により課する所得割（以下「分離課税に係る所得割」という。）を除く。", "百三十五万円"])
    law("PS6.2-295-1-1", "PS §6.2", "地法295①一 生活扶助", "chiho", C_ALL, "main", "295", "1/1", ["生活扶助"])
    law("PS6.2-295-2", "PS §6.2", "地法295② 退職手当等の支払を受けるべき日の属する年の一月一日の現況", "chiho", C_ALL, "main", "295", "2",
        ["分離課税に係る所得割につき前項第一号の規定を適用する場合における同号に掲げる者であるかどうかの判定は、退職手当等の支払を受けるべき日の属する年の一月一日の現況による"])
    law("PS6.2-24_5-1", "PS §6.2", "地法24の5① 道府県民税（第五十条の二の規定により課する所得割を除く）", "chiho", C_ALL, "main", "24_5", "1", ["第五十条の二の規定により課する所得割", "を除く"])
    law("PS6.2-fusoku3_3-1", "PS §6.2", "地法附則3の3① 道府県民税の所得割（第五十条の二の規定により課する所得割を除く。）", "chiho", C_ALL, "suppl:ORIG", "3_3", "1",
        ["総所得金額、退職所得金額及び山林所得金額の合計額", "道府県民税の所得割（第五十条の二の規定により課する所得割を除く。）を課することができない"])
    law("PS6.2-fusoku3_3-4", "PS §6.2", "地法附則3の3④ 市町村民税の所得割（分離課税に係る所得割を除く。）", "chiho", C_ALL, "suppl:ORIG", "3_3", "4",
        ["総所得金額、退職所得金額及び山林所得金額の合計額", "市町村民税の所得割（分離課税に係る所得割を除く。）を課することができない"])

    # ---- [PS] §6.3 ----
    law("PS6.3-292-13", "PS §6.3", "地法292①十三 合計所得金額の定義", "chiho", C_ALL, "main", "292", "1/13",
        ["第三百十三条第八項及び第九項の規定による控除前の同条第一項の総所得金額、退職所得金額及び山林所得金額の合計額をいう。"])
    law("PS6.3-23-13", "PS §6.3", "地法23①十三（道府県民税）", "chiho", C_ALL, "main", "23", "1/13", ["総所得金額、退職所得金額及び山林所得金額の合計額"])
    law("PS6.3-313-1", "PS §6.3", "地法313①", "chiho", C_ALL, "main", "313", "1", ["所得割の課税標準は、前年の所得について算定した総所得金額、退職所得金額及び山林所得金額とする。"])
    law("PS6.3-292-7a", "PS §6.3", "地法292①七 五十八万円以下", "chiho", ["2026-01-01", "2026-11-09"], "main", "292", "1/7", ["五十八万円以下"])
    law("PS6.3-292-7b", "PS §6.3", "地法292①七 六十二万円以下（asof 2027-01-01）", "chiho", "2027-01-01", "main", "292", "1/7", ["六十二万円以下"])
    law("PS6.3-292-9a", "PS §6.3", "地法292①九 五十八万円以下", "chiho", ["2026-01-01", "2026-11-09"], "main", "292", "1/9", ["五十八万円以下"])
    law("PS6.3-292-9b", "PS §6.3", "地法292①九 六十二万円以下（asof 2027-01-01）", "chiho", "2027-01-01", "main", "292", "1/9", ["六十二万円以下"])
    law("PS6.3-314_2-9", "PS §6.3", "地法314の2⑨ 勤労学生の読替え（前年の合計所得金額、第二百九十二条第一項第十三号）", "chiho", C_ALL, "main", "314_2", "9",
        ["所得税法第二条第一項第三十二号", "前年", "の合計所得金額（地方税法第二百九十二条第一項第十三号に規定する合計所得金額"])
    law("PS6.3-317_3_2-1-2", "PS §6.3", "地法317の3の2①二 百三十三万円以下", "chiho", C_ALL, "main", "317_3_2", "1/2", ["百三十三万円以下"])

    # ---- [PS] §8 国保 ----
    law("PS8-kokurei29_7-2-4", "PS §8", "国保令29の7②四 基礎控除後の総所得金額等", "kokuho-rei", "2026-11-09", "main", "29_7", "2/4",
        ["地方税法第三百十四条の二第一項に規定する総所得金額及び山林所得金額並びに他の所得と区分して計算される所得の金額", "同条第二項の規定による控除をした後の", "基礎控除後の総所得金額等"])
    nolaw("PS8-kokurei29_7-2-4-no", "PS §8", "国保令29の7②四 に「退職所得」の語は無い", "kokuho-rei", "2026-11-09", "main", "29_7", "2/4", "退職所得")
    law("PS8-kokurei29_7-6-1", "PS §8", "国保令29の7⑥一 他の所得と区分して計算される所得の金額の列挙", "kokuho-rei", "2026-11-09", "main", "29_7", "6/1",
        ["上場株式等に係る配当所得等の金額", "土地等に係る事業所得等の金額", "長期譲渡所得の金額", "短期譲渡所得の金額", "一般株式等に係る譲渡所得等の金額", "上場株式等に係る譲渡所得等の金額", "先物取引に係る雑所得等の金額", "特例適用利子等の額", "特例適用配当等の額", "条約適用利子等の額", "条約適用配当等の額"])
    nolaw("PS8-kokurei29_7-6-1-no", "PS §8", "国保令29の7⑥一 に「退職所得」の語は無い", "kokuho-rei", "2026-11-09", "main", "29_7", "6/1", "退職所得")

    # ---- [H] H10 ----
    for n in ("171", "172", "173"):
        cap(f"H10-cap{n}", "H10", f"所法{n} の見出し", "shotoku", "2026-11-09", n, {"171": "退職所得についての選択課税", "172": "給与等につき源泉徴収を受けない場合の申告納税等", "173": "退職所得の選択課税による還付"}[n])
    law("H10-171", "H10・I12", "所法171 第百六十九条に規定する非居住者の退職手当等の選択", "shotoku", "2026-11-09", "main", "171", "1",
        ["第百六十九条", "に規定する非居住者が", "退職手当等"])
    law("H10-172-2", "H10", "所法172② 前条（171）の退職手当等について同条の選択をする場合の申告書の記載", "shotoku", "2026-11-09", "main", "172", "2",
        ["前条に規定する退職手当等", "同条の選択をする場合"])

    # ---- [PS] §2.4 所令71の2 の構造（項・号と金額） ----
    law("PS2.4-71_2-1", "PS §2.4", "所令71の2① 一般＋短期", "shotoku-rei", S_ALL, "main", "71_2", "1", ["一般退職手当等", "短期退職手当等"])
    law("PS2.4-71_2-1-1-i-2", "PS §2.4", "所令71の2①一イ(2) 二十万円×重複勤続年数", "shotoku-rei", S_ALL, "main", "71_2", "1/1/イ/（２）", ["二十万円に重複勤続年数を乗じて計算した金額"])
    law("PS2.4-71_2-3", "PS §2.4", "所令71の2③ 一般＋特定役員（短期を除く）", "shotoku-rei", S_ALL, "main", "71_2", "3", ["一般退職手当等及び特定役員退職手当等がある場合", "短期退職手当等がある場合を除く"])
    law("PS2.4-71_2-3-1-ro", "PS §2.4", "所令71の2③一ロ 二十万円×重複勤続年数", "shotoku-rei", S_ALL, "main", "71_2", "3/1/ロ", ["二十万円に重複勤続年数を乗じて計算した金額"])
    law("PS2.4-71_2-5", "PS §2.4", "所令71の2⑤ 短期＋特定役員（一般を除く）", "shotoku-rei", S_ALL, "main", "71_2", "5", ["短期退職手当等及び特定役員退職手当等がある場合", "一般退職手当等がある場合を除く"])
    law("PS2.4-71_2-5-1-ro", "PS §2.4", "所令71の2⑤一ロ 二十万円×重複勤続年数", "shotoku-rei", S_ALL, "main", "71_2", "5/1/ロ", ["二十万円に重複勤続年数を乗じて計算した金額"])
    law("PS2.4-71_2-7", "PS §2.4", "所令71の2⑦ 3つともある場合", "shotoku-rei", S_ALL, "main", "71_2", "7", ["一般退職手当等、短期退職手当等及び特定役員退職手当等がある場合"])
    law("PS2.4-71_2-7-1-ha", "PS §2.4", "所令71の2⑦一ハ 十四万円（全重複期間）", "shotoku-rei", S_ALL, "main", "71_2", "7/1/ハ", ["十四万円に重複勤続年数（全重複期間により計算した年数に限る。）"])
    law("PS2.4-71_2-7-2-i-3", "PS §2.4", "所令71の2⑦二イ(3) 十三万円（全重複期間）", "shotoku-rei", S_ALL, "main", "71_2", "7/2/イ/（３）", ["十三万円に重複勤続年数（全重複期間により計算した年数に限る。）"])
    law("V-71_2-10", "H9（補足）", "所令71の2⑩ 重複勤続年数などの計算に所令69②（一年未満は一年）を準用", "shotoku-rei", S_ALL, "main", "71_2", "10",
        ["第六十九条第二項及び第三項の規定は", "重複勤続年数", "準用する"])
    nolaw("X-84_2-no-honnin", "I4", "反証：所法84の2①（特定親族特別控除）に居住者本人の合計所得金額の要件は無い", "shotoku", ["2025-12-31", "2026-12-31"], "main", "84_2", "1", "その居住者の合計所得金額")
    law("V-84_2-123", "I4", "所法84の2① 特定親族の合計所得金額 百二十三万円以下（特定親族の側の要件）", "shotoku", ["2025-12-31", "2026-12-31"], "main", "84_2", "1", ["合計所得金額が百二十三万円以下であるものに限る"])
    # ---- [M] §3 地方税法施行令（ひとり親の子の要件） ----
    law("M3-chirei7_2_2-a", "M §3", "地令7の2の2② 五十八万円以下（asof 2026-11-09）", "chiho-rei", "2026-11-09", "main", "7_2_2", "2", ["総所得金額、退職所得金額及び山林所得金額の合計額", "五十八万円以下"])
    law("M3-chirei7_2_2-b", "M §3", "地令7の2の2② 六十二万円以下（asof 2027-01-01）", "chiho-rei", "2027-01-01", "main", "7_2_2", "2", ["総所得金額、退職所得金額及び山林所得金額の合計額", "六十二万円以下"])
    law("M3-chirei46_2_2-a", "M §3", "地令46の2の2② 五十八万円以下（asof 2026-11-09）", "chiho-rei", "2026-11-09", "main", "46_2_2", "2", ["総所得金額、退職所得金額及び山林所得金額の合計額", "五十八万円以下"])
    law("M3-chirei46_2_2-b", "M §3", "地令46の2の2② 六十二万円以下（asof 2027-01-01）", "chiho-rei", "2027-01-01", "main", "46_2_2", "2", ["総所得金額、退職所得金額及び山林所得金額の合計額", "六十二万円以下"])
    # ---- 令和8年分の基礎控除（国税庁 TA1199） ----
    web("X-ta1199", "H5・I4", "TA1199 令和8年分・令和9年分の基礎控除（104万円・67万円・62万円）", "ta_1199",
        ["令和8年4月1日現在法令等", "令和8年分", "132万円以下", "104万円", "489万円超", "655万円以下", "67万円", "655万円超2,350万円以下", "62万円"])

    # ---- 行政の案内（HTML） ----
    web("W-1420-a", "PS §1.2", "TA1420 iDeCo 一時金も退職所得とみなす", "ta_1420",
        ["確定拠出年金法に規定する企業型年金規約または個人型年金規約に基づいて老齢給付金として支給される一時金"])
    web("W-1420-b", "PS §1.2", "TA1420 解雇予告手当・未払賃金", "ta_1420",
        ["労働基準法第20条の規定により支払われる解雇予告手当", "賃金の支払の確保等に関する法律第7条の規定により退職した労働者が弁済を受ける未払賃金も退職所得に該当します"])
    web("W-1420-c", "PS §4.1", "TA1420 申告書を提出している人は原則として確定申告不要、医療費控除等の場合は記載", "ta_1420",
        ["原則として確定申告は必要ありません", "医療費控除", "退職所得の金額を記載する必要があります"])
    web("W-1420-d", "PS §4.1", "TA1420 申告書を提出していない人は20.42パーセント", "ta_1420", ["20.42パーセント"])
    web("W-1420-e", "PS §3", "TA1420 令和8年度税制改正、防衛特別所得税、令和9年以後", "ta_1420",
        ["令和8年度税制改正により、防衛特別所得税の創設並びに復興特別所得税の税率の引下げおよび課税期間の延長が行われ、令和9年以後に適用されます"])
    for sid in ("ta_1420",):
        web(f"W-{sid}-asof", "PS §0.2", f"{sid} 版の表示 [令和8年4月1日現在法令等]", sid, ["令和8年4月1日現在法令等"])
    for sid in ("ta_2725", "ta_2728", "ta_2732", "ta_2732_besshi", "ta_2735", "ta_2737", "ta_2740", "ta_2741"):
        web(f"W-{sid}-asof", "PS §0.2", f"{sid} 版の表示 [令和8年4月1日現在法令等]", sid, ["令和8年4月1日現在法令等"])
    web("W-2725-title", "PS §0.2", "TA2725 題名", "ta_2725", ["退職所得となるもの"])
    web("W-2728-title", "PS §0.2", "TA2728 題名", "ta_2728", ["退職所得の収入金額の収入すべき時期"])
    web("W-2732-title", "PS §0.2", "TA2732 題名", "ta_2732", ["退職手当等に対する源泉徴収"])
    web("W-2735-title", "PS §0.2", "TA2735 題名", "ta_2735", ["同じ年に2か所以上から退職手当等が支払われるとき"])
    web("W-2737-title", "PS §0.2", "TA2737 題名", "ta_2737", ["役員等の勤続年数が5年以下の者に対する退職手当等", "特定役員退職手当等"])
    web("W-2740-title", "PS §0.2", "TA2740 題名", "ta_2740", ["勤続年数が5年以下の者に対する退職手当等", "短期退職手当等", "令和4年1月1日以後"])
    web("W-2741-title", "PS §0.2", "TA2741 題名", "ta_2741", ["同じ年に一般退職手当等のほか、短期退職手当等や特定役員退職手当等がある場合"])
    web("W-2732-death", "PS §1.2", "TA2732 死亡退職で相続税の対象", "ta_2732",
        ["死亡退職により支払う退職手当等で相続税の課税の対象となるものは、所得税の課税の対象とならないため、所得税および復興特別所得税の源泉徴収は必要ありません"])
    web("W-2732-basis", "PS §1.2・M §7", "TA2732 根拠法令等（通令40、所法9）", "ta_2732", ["根拠法令等", "通令40", "所法9"])
    web("W-2728-a", "PS §1.2", "TA2728 一般的には退職の日", "ta_2728", ["退職の日"])
    web("W-2728-b", "PS §1.2", "TA2728 役員の決議の日", "ta_2728", ["株主総会", "決議"])
    web("W-2728-c", "PS §1.2", "TA2728 年を異にする場合の最初に支払を受けるべき日", "ta_2728", ["最初に支払を受けるべき"])
    web("W-2728-d", "PS §1.2", "TA2728 確定拠出年金の老齢給付金の一時金の例外", "ta_2728",
        ["確定拠出年金法の規定に基づき老齢給付金として支給される一時金の場合は", "給付事由が生じた日が収入すべき日となり、最初に支払われたものの支給期の属する年分にはなりません"])
    web("W-2732-ex1", "PS §4.2", "TA2732 例1（10年2か月→11年、440万円、180万円、91,890円）", "ta_2732",
        ["10年2か月", "11年", "440万円", "180万円", "91,890円"])
    web("W-2732-ex2", "PS §4.2", "TA2732 例2（29年2か月→30年、1,500万円、400万円、380,322円）", "ta_2732",
        ["29年2か月", "30年", "1,500万円", "400万円", "427,500円", "380,322"])
    web("W-2732-nodecl", "PS §4.2", "TA2732 申告書なし 1,633,600円", "ta_2732", ["1,633,600円"])
    web("W-2732-1yen", "PS §4.2", "TA2732 20.42パーセント（1円未満の端数は切り捨て）", "ta_2732", ["20.42パーセント", "1円未満の端数は切り捨てます"])
    web("W-2732-1000", "PS §4.2", "TA2732 （注1）課税退職所得金額の1,000円未満の端数切捨て", "ta_2732", ["課税退職所得金額に1,000円未満の端数があるときは、これを切り捨てます"])
    web("W-2732-overlap", "PS §2.3", "TA2732 重複期間の1年未満の端数は切り捨て", "ta_2732", ["重複期間に1年未満の端数がある場合には切り捨てます"])
    web("W-2732-tanki", "PS §2.4", "TA2732 短期退職手当等は令和4年1月1日以後", "ta_2732", ["短期退職手当等については、令和4年1月1日以後に支払うべき退職手当等について適用されます"])
    web("W-2740-tanki", "PS §2.4", "TA2740 短期退職手当等は令和4年1月1日以後", "ta_2740", ["令和4年1月1日以後に支払うべき退職手当等について適用されます"])
    web("W-2740-ex", "PS §2.4・M §5 C4", "TA2740 短期の設例（800万円・450万円）", "ta_2740", ["800万円", "450万円"])
    web("W-besshi", "PS §4.2", "TA2732別紙 速算表の控除額と102.1%", "ta_2732_besshi",
        ["102.1", "97,500円", "427,500円", "636,000円", "1,536,000円", "2,796,000円", "4,796,000円"])
    web("W-besshi-note", "PS §4.2", "TA2732別紙 注 700万円→994,454円", "ta_2732_besshi", ["994,454"])
    web("W-2735-ex", "PS §4.2", "TA2735 令和8年の設例", "ta_2735",
        ["平成29年4月1日", "令和8年3月31日", "400万円", "平成31年4月1日", "令和8年7月31日", "180万円", "9年", "360万円", "20万円", "10,210円",
         "9年4か月", "10年", "400万円", "90万円", "45,945円", "35,735円"])
    web("W-2735-minus", "PS §4.2", "TA2735 マイナスの金額の還付は確定申告", "ta_2735",
        ["控除後の額がマイナスとなる場合には源泉徴収税額はないことになります", "確定申告をする必要があります"])
    web("W-2735-overlap", "PS §2.3", "TA2735 重複期間の1年未満の端数は切り捨て", "ta_2735", ["1年未満の端数がある場合には切り捨てます"])
    web("W-2737-ex2", "PS §2.4", "TA2737 例2（520万円、120万円、580万円）", "ta_2737", ["520万円", "120万円", "580万円"])
    web("W-2737-ex3", "PS §2.4", "TA2737 例3（140万円、530万円）", "ta_2737", ["140万円", "530万円"])
    web("W-2741-ex", "PS §2.4", "TA2741（120万円、80万円、1,650万円）", "ta_2741", ["120万円", "80万円", "1,650万円"])
    web("W-yogo", "PS §5.2", "用語集 合計所得金額の注（退職所得金額は確定申告が不要な場合でも加算）", "ta_yogo_senmon",
        ["合計所得金額", "退職所得金額は、確定申告が不要な場合でも計算に当たって加算する必要があります"])
    web("W-qa0585-a", "PS §5.2", "QA0585 配偶者特別控除の適用を受けることはできません", "shitsugi_shotoku_05_85", ["配偶者特別控除の適用を受けることはできません"])
    web("W-qa0585-b", "PS §5.2", "QA0585 121②で申告不要でも合計所得金額に退職所得金額が含まれる", "shitsugi_shotoku_05_85",
        ["所得税法第121条第２項の規定により確定申告書の提出が不要となる場合であっても、合計所得金額に退職所得金額が含まれることに変わりはありません"])
    web("W-qa0585-c", "PS §5.2", "QA0585 105万円・30万円・135万円・133万円", "shitsugi_shotoku_05_85", ["105万円", "135万円", "133万円"])
    web("W-qa0585-d", "PS §5.2", "QA0585 令和7年8月1日現在の法令・通達等", "shitsugi_shotoku_05_85", ["令和7年8月1日現在の法令・通達等に基づいて作成"])
    web("W-qa0585-e", "PS §5.2", "QA0585 関係法令通達（所法2①30、22②、83の2①、121②）", "shitsugi_shotoku_05_85", ["関係法令通達", "所得税法第２条第１項第30号", "第22条第２項", "第83の２条第１項", "第121条第２項"])
    web("W-qag0406-a", "PS §4.2", "QAG0406 確定申告で精算することはできません", "shitsugi_gensen_04_06", ["確定申告で精算することはできません"])
    web("W-qag0406-b", "PS §4.2", "QAG0406 関係法令通達 203-3、194〜198共-1", "shitsugi_gensen_04_06", ["203-3", "194", "198共-1"])
    web("W-kihon30-1", "PS §1.2", "通達30-1（本来退職しなかったとしたならば支払われなかったもので…）", "kihon_04_04",
        ["30-1", "本来退職しなかったとしたならば支払われなかったもので、退職したことに基因して一時に支払われることとなった給与"])
    web("W-kihon30-2", "PS §1.2", "通達30-2", "kihon_04_04", ["引き続き勤務する者に支払われる給与で退職手当等とするもの", "30-2"])
    web("W-kihon30-2_2", "PS §1.2", "通達30-2の2 執行役員", "kihon_04_04", ["30-2の2", "執行役員"])
    web("W-kihon30-3", "PS §1.2", "通達30-3 掛金を拠出して使用者から支払われる一時金", "kihon_04_04", ["30-3"])
    web("W-kihon30-4", "PS §1.2", "通達30-4 年金に代えて支払われる一時金", "kihon_04_04", ["30-4", "年金に代えて支払われる一時金"])
    web("W-kihon30-5", "PS §1.2", "通達30-5 解雇予告手当", "kihon_04_04", ["30-5", "労働基準法第20条", "予告手当"])
    web("W-kihon30-6", "PS §2.2", "通達30-6 勤続年数", "kihon_04_04", ["30-6"])
    web("W-kihon30-7", "PS §2.2", "通達30-7 長期欠勤・休職", "kihon_04_04", ["30-7", "休職"])
    web("W-kihon30-9", "PS §2.2", "通達30-9 日額表の丙欄", "kihon_04_04", ["30-9", "丙欄"])
    web("W-kihon30-10", "PS §2.2", "通達30-10 明らかに定められている場合に限り", "kihon_04_04", ["30-10", "明らかに定められている"])
    web("W-kihon30-11", "PS §2.2", "通達30-11", "kihon_04_04", ["30-11"])
    web("W-kihon30-12", "PS §2.2", "通達30-12 復職の条件として退職手当等を返還", "kihon_04_04", ["30-12", "返還"])
    web("W-kihon30-13", "PS §2.2", "通達30-13 暦に従って計算、30日を1月、12月を1年", "kihon_04_04",
        ["30-13", "暦に従って計算し、1月に満たない期間は日をもって数え", "日数は30日をもって1月とし、月数は12月をもって1年とする"])
    web("W-kihon201-2", "PS §4.1", "通達201-2 赤字の金額は還付しない", "kihon_34_01",
        ["201-2", "当該退職手当等から徴収する税額がないにとどまり、その赤字の金額は当該退職手当等の支払者からは還付しない"])
    web("W-kihon203-1", "PS §4.2", "通達203-1 提出の順序", "kihon_34_01", ["203-1", "順序"])
    web("W-kihon203-2", "PS §4.2", "通達203-2 連記式その他の簡易な方法", "kihon_34_01", ["203-2", "連記式"])
    web("W-keisan-1559", "PS §4.1", "作成R7-1559 退職所得に係る所得税", "r7sp_scid1559", ["退職所得の受給に関する申告書", "確定申告"])
    web("W-keisan-458", "PS §4.1", "作成R7-458 退職金の収入がある場合", "r7_cid458", ["退職所得の受給に関する申告書", "原則として確定申告は必要ありません"])
    web("W-keisan-1322", "PS §6.3", "作成R7-1322 住民税では退職所得（源泉徴収されたものに限る）の金額は含めない", "r7sp_scid1322",
        ["住民税では、扶養控除等の要件とされる合計所得金額等には、退職所得（源泉徴収されたものに限ります。以下同じです。）の金額は含めないこととされています"])
    web("W-keisan-1322-ex", "PS §6.3・M §5 C8", "作成R7-1322 設例 10万円＋30万円＝40万円", "r7sp_scid1322", ["10万円", "40万円", "30万円"])
    web("W-keisan-647-r7", "PS §6.3", "作成R7-647 令和7年中の退職所得を除いた合計所得金額", "r7_cid647",
        ["令和7年中に退職所得のある配偶者又は親族等の合計所得金額を退職所得の金額を除いた上で計算した結果", "令和7年中の退職所得を除いた合計所得金額"])
    web("W-keisan-647-r5", "PS §6.3", "作成R5-647 同じ文（令和5年）", "r5_cid647", ["令和5年中に退職所得のある配偶者又は親族等の合計所得金額を退職所得の金額を除いた上で計算した結果"])
    web("W-soumu-a", "PS §6.1", "総務省 退職所得の金額×税率（6%・4%）＝特別徴収すべき税額（画像の alt）", "soumu_65871", ["退職所得の金額×税率", "6%", "市町村民税", "4%", "道府県民税", "特別徴収すべき税額"])
    web("W-soumu-b", "PS §6.1", "総務省 千円未満の金額を切り捨て", "soumu_65871", ["千円未満の端数がある場合は、千円未満の金額を切り捨てる"])
    web("W-soumu-c", "PS §6.1", "総務省 それぞれ百円単位未満の端数を切り捨て", "soumu_65871", ["それぞれ百円単位未満の端数を切り捨てる"])
    web("W-soumu-d", "PS §6.1", "総務省 勤続年数が5年以内の法人役員等", "soumu_65871", ["勤続年数が5年以内の法人役員等"])
    web("W-soumu-e", "PS §6.1", "総務省 1月1日現在における住所の所在する市町村", "soumu_65871", ["1月1日現在における住所の所在する市町村"])
    web("W-tetsuzuki", "PS §0.2", "手続A2-29 退職所得の受給に関する申告", "tetsuzuki_1648_37", ["退職所得の受給に関する申告"])

    # Last-Modified と SHA-256（[M] §4。SHA-256 は先頭16桁）
    metas = [
        ("ta_1420", "2026-09-09", "daef0c400c24bbe4"), ("ta_2725", "2026-09-10", "8e862d250d54419d"),
        ("ta_2732", "2026-09-10", "7102f34ed11c7441"), ("ta_2732_besshi", "2026-09-10", "a6c9a2138e735452"),
        ("ta_2735", "2026-09-10", "590a51d205d8c1be"), ("ta_2736", "2026-09-10", "788275e79aea3b7f"),
        ("ta_2741", "2026-09-10", "460a2d07be6bd9ba"), ("ta_1180", "2026-09-09", "c92803d8c75aa5c7"),
        ("ta_1191", "2026-09-09", "0725ae1600feec40"), ("ta_1195", "2026-09-09", "ee1364c58db7f9e4"),
        ("ta_yogo_senmon", "2026-09-16", "e0d5142e9eabe61f"), ("tetsuzuki_1648_37", "2026-03-27", "6c6d833425c419a7"),
        ("shitsugi_shotoku_05_85", "2025-12-03", "8c9be1ab0230bfb4"), ("shitsugi_gensen_04_06", "2025-12-03", "9f377183be267651"),
        ("kihon_shotoku_toc", "2025-12-25", "74710f9540adcb9b"), ("nencho_shinkokusyo", "2026-10-16", "3fdfcbe7248226f0"),
        ("fuyo_2025bun_01", "2024-09-24", "1d3e1ebea76a108b"), ("fuyo_2026bun_01", "2025-09-03", "15bae0d3fbca3dde"),
        ("fuyo_2025bun_02", "2024-09-24", "b88eae10c7796236"), ("fuyo_2026bun_02", None, "700138cae1f347c2"),
        ("aramashi2026_01", "2025-12-12", "3e09c81c06d547d0"), ("keisan_robots", None, "e2bd8f0bfa6b6105"),
        ("r7_cat21c_index", "2026-11-08", "c4afc4514028700f"), ("r7sp_scid1559", "2026-11-08", "d86e1434725e260c"),
        ("r7_cid458", "2026-11-08", "a1205ddcc8b123e1"), ("r7sp_scid1322", "2025-12-25", "8519920f35b039c5"),
        ("r7_ocat241_index", "2026-11-08", "fa8310c0bd017c62"), ("r5_cid647", "2023-11-01", "fa9ae2e6472bf218"),
        ("r7_cid647", "2025-12-25", "bdaa488dec854b3e"), ("kihon_04_04", "2024-01-18", "e39928235cd98d3e"),
        ("kihon_34_01", "2024-01-18", "59429391d1e420eb"), ("nencho2026_305", "2026-08-31", "f49605a28ed82223"),
        ("ta_2728", "2026-09-10", "e2131e79d799d815"), ("ta_2737", "2026-09-10", "d5232335377e44c9"),
        ("ta_2740", "2026-09-10", "0fb5230e08821cef"), ("soumu_65871", "2026-05-12", "ddaa098456bd018a"),
        ("soumu_hayami_h25", "2025-01-22", "8df7239d26023872"), ("chikyosai_osaka_2023", "2023-03-31", "03798e7d2b423b68"),
    ]
    for sid, lm, sha in metas:
        meta(f"META-{sid}", "M §4・PS §0.2", f"{sid} の Last-Modified {lm}・SHA-256 {sha}", sid, lm, sha)

    # ---- 計算（[PS]・[M]・[H]・[I] の数値。独立に書いた式） ----
    def kojo(n, dis=False):
        a = 400_000 * n if n <= 20 else 8_000_000 + 700_000 * (n - 20)
        a = max(a, 800_000)
        return a + (1_000_000 if dis else 0)

    def tax89(x):  # 所法89①（円。端数処理前の整数×100）
        br = [(1_950_000, 5), (3_300_000, 10), (6_950_000, 20), (9_000_000, 23), (18_000_000, 33), (40_000_000, 40), (None, 45)]
        lo, t = 0, 0
        for up, r in br:
            hi = x if up is None else min(x, up)
            if hi > lo:
                t += (hi - lo) * r
            if up is None or x <= up:
                break
            lo = up
        return t

    def gensen(base):
        a = base // 1000 * 1000
        return tax89(a) * 1021 // 100_000

    calc("C-kojo-11", "PS §4.2・I1", "勤続11年の退職所得控除額 440万円", kojo(11), 4_400_000)
    calc("C-kojo-30", "PS §4.2", "勤続30年の退職所得控除額 1,500万円", kojo(30), 15_000_000)
    calc("C-ex1-shotoku", "PS §4.2・I1", "(800万−440万)/2＝180万円", (8_000_000 - kojo(11)) // 2, 1_800_000)
    calc("C-ex1-gensen", "PS §4.2", "180万円→91,890円", gensen(1_800_000), 91_890)
    calc("C-ex2-gensen", "PS §4.2", "400万円→380,322円", gensen(4_000_000), 380_322)
    calc("C-besshi-700", "PS §4.2", "700万円→994,454円", gensen(7_000_000), 994_454)
    calc("C-nodecl", "PS §4.2", "800万円×20.42%＝1,633,600円", 8_000_000 * 2042 // 10_000, 1_633_600)
    calc("C-2735-A", "PS §4.2", "A社 (400万−360万)/2＝20万円→10,210円", gensen((4_000_000 - kojo(9)) // 2), 10_210)
    calc("C-2735-B", "PS §4.2", "B社 合計 (580万−400万)/2＝90万円→45,945円", gensen((5_800_000 - kojo(10)) // 2), 45_945)
    calc("C-2735-diff", "PS §4.2", "45,945−10,210＝35,735円", 45_945 - 10_210, 35_735)
    # 速算表の控除額 = Σ 境目×率の差
    ded, prev, lo, deds = 0, 0, 0, []
    for up, r in [(1_950_000, 5), (3_300_000, 10), (6_950_000, 20), (9_000_000, 23), (18_000_000, 33), (40_000_000, 40), (None, 45)]:
        ded += lo * (r - prev) // 100
        deds.append(ded)
        prev, lo = r, (up or lo)
    calc("C-quick", "PS §4.2", "速算表の控除額", deds, [0, 97_500, 427_500, 636_000, 1_536_000, 2_796_000, 4_796_000])
    calc("C-2740", "PS §2.4", "短期 800万・5年→450万円", 1_500_000 + (8_000_000 - (3_000_000 + kojo(5))), 4_500_000)
    calc("C-2737-1", "PS §2.4", "特定役員 500万・5年→300万円", 5_000_000 - kojo(5), 3_000_000)
    calc("C-2737-2", "PS §2.4", "使用人10年→役員3年：(500万−120万)＋{800万−(520万−120万)}/2＝580万円",
         (5_000_000 - 1_200_000) + (8_000_000 - (kojo(13) - 1_200_000)) // 2, 5_800_000)
    calc("C-2737-3tk", "PS §2.4", "40万×(5−3)＋20万×3＝140万円", 400_000 * 2 + 200_000 * 3, 1_400_000)
    calc("C-2741", "PS §2.4", "(1,500万−120万)＋150万＋{500万−(300万＋80万)}＝1,650万円",
         (15_000_000 - 1_200_000) + 1_500_000 + (5_000_000 - (3_000_000 + 800_000)), 16_500_000)
    calc("C-2741-sk", "PS §2.4", "40万×5−120万＝80万円", 400_000 * 5 - 1_200_000, 800_000)
    calc("C-min80", "M §5 C4", "勤続1年 80万円・障害 180万円", [kojo(1), kojo(1, True)], [800_000, 1_800_000])
    # 別表第六の 41年以上の文と式
    calc("C-beppyo-41", "PS §2.5", "41〜60年：22,000千円＋700千円×(年数−40)＝式", all(kojo(k) == 22_000_000 + 700_000 * (k - 40) for k in range(41, 61)), True)
    # 住民税（[M] §5 C6 の例）
    base = ((8_000_000 - kojo(11)) // 2) // 1000 * 1000
    calc("C-jumin-ex1", "M §5 C6", "TA2732 例1 の支払の住民税 180万円→市町村 108,000・道府県 72,000", [base, base * 6 // 100 // 100 * 100, base * 4 // 100 // 100 * 100], [1_800_000, 108_000, 72_000])
    # 総務省の早見表（平成25年1月1日以降適用）p.1〜2 から本検証が別に目視で転記した行（担当の転記とは別の行）
    # (2分の1前 から, まで, 市町村民税, 道府県民税)
    hayami_v = [(14_000, 15_999, 400, 200), (50_000, 53_999, 1_500, 1_000), (150_000, 153_999, 4_500, 3_000),
                (250_000, 253_999, 7_500, 5_000), (334_000, 335_999, 10_000, 6_600), (336_000, 337_999, 10_000, 6_700),
                (350_000, 353_999, 10_500, 7_000), (88_000, 89_999, 2_600, 1_700)]
    got_h, exp_h = [], []
    for lo, hi, ec, ep in hayami_v:
        for x in (lo, hi):
            b = (x // 2) // 1000 * 1000
            got_h.append((x, b * 6 // 100 // 100 * 100, b * 4 // 100 // 100 * 100))
            exp_h.append((x, ec, ep))
    calc("V-hayami", "PS §6.1・M §5 C6", "早見表の別の8行（16点）が地法328の2・328の3・50の4・20の4の2の順の計算と一致", got_h, exp_h)
    def add_months(d, m):
        y, mo = divmod(d.month - 1 + m, 12)
        y += d.year
        mo += 1
        last = (dt.date(y + (mo // 12), mo % 12 + 1, 1) - dt.timedelta(days=1)).day
        return dt.date(y, mo, min(d.day, last))

    def kinzoku(s, e):
        end_x = e + dt.timedelta(days=1)  # 退職の日を含める
        m = 0
        while add_months(s, m + 1) <= end_x:
            m += 1
        days = (end_x - add_months(s, m)).days
        m += days // 30
        days %= 30
        y, mo = divmod(m, 12)
        return y + (1 if (mo or days) else 0), (y, mo, days)
    kz = [("TA2735 A社 平29.4.1〜令8.3.31", dt.date(2017, 4, 1), dt.date(2026, 3, 31), 9),
          ("TA2735 B社の通算 平29.4.1〜令8.7.31（9年4か月）", dt.date(2017, 4, 1), dt.date(2026, 7, 31), 10),
          ("TA2741 A社 役員 令4.5.1〜令8.5.31（4年1か月）", dt.date(2022, 5, 1), dt.date(2026, 5, 31), 5),
          ("TA2741 B社 使用人 令4.8.1〜令8.5.31（3年10か月）", dt.date(2022, 8, 1), dt.date(2026, 5, 31), 4),
          ("TA2741 C社 令3.2.1〜令8.1.31（5年）", dt.date(2021, 2, 1), dt.date(2026, 1, 31), 5),
          ("境目 令3.4.1〜令8.4.1（5年と1日）", dt.date(2021, 4, 1), dt.date(2026, 4, 1), 6)]
    calc("V-kinzoku", "M §5 C3", "勤続年数（通達30-13 の数え方＋所令69② の切上げ）を国税庁の設例の期間で数える",
         [(lbl, kinzoku(a, b)) for lbl, a, b, _ in kz], [(lbl, (x, kinzoku(a, b)[1])) for lbl, a, b, x in kz])
    # [I] I3・I5・I7
    calc("I3-shotoku", "I3", "退職金400万・勤続9年→控除360万・退職所得20万", [kojo(9), (4_000_000 - kojo(9)) // 2], [3_600_000, 200_000])
    calc("I5-gensen", "I5", "課税退職所得200万円の源泉 104,652円（200万×10%−97,500＝102,500 の102.1%）",
         [2_000_000 * 10 // 100 - 97_500, gensen(2_000_000)], [102_500, 104_652])
    calc("I5-shinkoku", "I5", "課税退職所得110万円→110万×5%×102.1%＝56,155円", 1_100_000 * 5 * 1021 // 100_000, 56_155)
    calc("I7-half", "I7", "(4,000,001−3,600,000)/2＝200,000.5", (4_000_001 - 3_600_000) / 2, 200_000.5)
    calc("C8-qa0585", "M §5 C8", "QA0585 の控除額の逆算（300万−2×30万＝240万＝40万×6年）", [3_000_000 - 2 * 300_000, (3_000_000 - 2 * 300_000) // 400_000], [2_400_000, 6])
    return C


# ---------------------------------------------------------------- 照合
def load_laws():
    man = json.loads((OUT / "egov_manifest.json").read_text(encoding="utf-8"))
    laws = {}
    for f in man["fetches"]:
        if f.get("law_revision_id"):
            laws[(f["short"], f["asof"])] = (ROOT / f["file"], f)
    return man, laws


def node_for(law, part, art):
    if part == "main":
        return law.main.get(art)
    if part.startswith("suppl:"):
        key = part[len("suppl:"):]
        sps = law.suppl_of(None if key == "ORIG" else key)
        if not art:
            return {"tag": "X", "children": sps}
        for s in sps:
            for c in kids(s):
                if c.get("tag") == "Article" and c.get("attr", {}).get("Num") == art:
                    return c
            for c in kids(s, "Paragraph"):
                if c.get("attr", {}).get("Num") == art:
                    return c
    return None


def cmd_check():
    man, laws = load_laws()
    wm = json.loads((OUT / "web_manifest.json").read_text(encoding="utf-8"))
    ddir = ROOT / wm["download_dir"]
    wrec = {r["id"]: r for r in wm["results"]}
    # HTML のテキストは、保存した HTML から照合のたびに取り出し直す（画像の alt も含める）
    wtext = {}
    for sid, rec in wrec.items():
        if (rec.get("saved") or "").endswith(".html"):
            ep = Extract()
            ep.feed(decode((ddir / rec["saved"]).read_bytes(), rec.get("content_type")))
            wtext[sid] = "".join(ep.parts)
    cache = {}

    def get_law(short, asof):
        k = (short, asof)
        if k not in cache:
            p, _ = laws[k]
            cache[k] = Law(p)
        return cache[k]

    results = []
    for cid, where, what, kind, args in claims():
        r = {"id": cid, "where": where, "what": what, "kind": kind}
        try:
            if kind == "rev":
                s, a, rid, st = args
                _, f = laws[(s, a)]
                r["got"] = [f.get("law_revision_id"), f.get("current_revision_status")]
                r["ok"] = r["got"] == [rid, st]
            elif kind in ("law", "nolaw"):
                short, a, part, art, path, frags = args
                lw = get_law(short, a)
                n = node_for(lw, part, art)
                n2 = locate(n, path) if n is not None else None
                if kind == "law":
                    if n2 is None:
                        r["ok"], r["note"] = False, f"条・項・号が見つからない（{art} {path}）"
                    else:
                        ok, miss = has_all(text_of(n2), frags)
                        r["ok"] = ok
                        if not ok:
                            r["note"] = f"見つからない断片：{miss}"
                else:
                    if frags is None:
                        r["ok"] = n2 is None
                        r["note"] = "存在しない" if n2 is None else "存在する"
                    else:
                        r["ok"] = n2 is not None and norm(frags) not in norm(text_of(n2))
                        r["note"] = "語は無い" if r["ok"] else "語がある（または条が無い）"
            elif kind == "caption":
                short, a, art, frag = args
                c = get_law(short, a).caption(art)
                r["got"] = c
                r["ok"] = c is not None and frag in c
            elif kind == "web":
                sid, frags = args
                if sid not in wtext:
                    r["ok"], r["note"] = False, "テキストが無い"
                else:
                    ok, miss = has_all(wtext[sid], frags)
                    r["ok"] = ok
                    if not ok:
                        r["note"] = f"見つからない断片：{miss}"
            elif kind == "webmeta":
                sid, lm, sha = args
                rec = wrec.get(sid, {})
                got_lm = None
                if rec.get("last_modified"):
                    try:
                        got_lm = dt.datetime.strptime(rec["last_modified"], "%a, %d %b %Y %H:%M:%S %Z").date().isoformat()
                    except ValueError:
                        got_lm = rec["last_modified"]
                r["got"] = {"status": rec.get("status"), "last_modified": got_lm, "sha256_16": (rec.get("sha256") or "")[:16], "final_url": rec.get("final_url")}
                # lm が None：文書が Last-Modified を書いていない（「—」）。比べずに実際の値を記録する
                r["ok_lm"] = True if lm is None else (got_lm == lm)
                r["ok_sha"] = (r["got"]["sha256_16"] == sha)
                r["ok"] = r["ok_lm"] and r["ok_sha"]
            elif kind == "calc":
                got, exp = args
                r["got"], r["expect"] = got, exp
                r["ok"] = got == exp
        except Exception as e:  # noqa: BLE001
            r["ok"], r["note"] = False, f"例外：{e!r}"
        results.append(r)

    # 版の間の差分（担当の [M] §3 の主張の確認：退職所得に関係する条が同文か）
    diffs = ["# 版の間の差分（本検証のテキスト化。条ごとに同文かどうか）", ""]
    def art_text(short, asof, num):
        lw = get_law(short, asof)
        a = lw.main.get(num)
        return None if a is None else text_of(a)
    groups = [
        ("shotoku", S5, ["2", "22", "30", "31", "69", "87", "89", "120", "121", "122", "199", "200", "201", "202", "203", "226"]),
        ("shotoku-rei", S5, ["11_2", "69", "69_2", "70", "71", "71_2", "72", "76", "77", "319_3", "319_3_2"]),
        ("shotoku-ki", ["2025-12-31", "2026-11-09", "2027-01-01"], ["77", "77_2", "77_3", "77_4"]),
        ("sochi", ["2025-12-31", "2026-11-09", "2027-01-01"], ["29_4", "29_5"]),
        ("fukko", ["2025-12-31", "2026-11-09", "2027-01-01"], ["8", "9", "10", "12", "13", "17", "18", "28", "31"]),
        ("chiho", C_ALL, ["20_4_2", "23", "24", "24_5", "32", "50_2", "50_3", "50_4", "50_5", "50_6", "50_7", "50_8", "50_9", "50_10",
                          "292", "294", "295", "313", "314_2", "317_2", "317_3_2", "45_3_2", "328", "328_2", "328_3", "328_4", "328_5",
                          "328_6", "328_7", "328_8", "328_9", "328_10", "328_11", "328_12", "328_13", "328_14", "328_15", "328_16"]),
        ("chiho-rei", ["2026-11-09", "2027-01-01"], ["7_2_2", "46_2_2", "48_17"]),
    ]
    diff_summary = {}
    for short, asofs, nums in groups:
        for a, b in zip(asofs, asofs[1:]):
            changed = [n for n in nums if art_text(short, a, n) != art_text(short, b, n)]
            diff_summary[f"{short} {a}→{b}"] = changed
            diffs.append(f"- {short} {a} → {b}：変化した条 = {changed or 'なし'}")
    # 別表第六の同文の確認
    def appdx6(short, asof):
        lw = get_law(short, asof)
        for t in lw.appdx:
            title = "".join(text_of(c) for c in kids(t, "AppdxTableTitle"))
            if title.startswith("別表第六"):
                return text_of(t)
        return None
    b6 = {a: appdx6("shotoku", a) for a in S5}
    diffs.append(f"- 所得税法 別表第六：5時点で同文 = {len(set(b6.values())) == 1 and None not in b6.values()}")
    # 別表第六の各セルを式と照合（本検証の独自の読み取り：TableColumn のテキストを行ごとに並べる）
    b6rows = []
    for t in get_law("shotoku", "2026-11-09").appdx:
        title = "".join(text_of(c) for c in kids(t, "AppdxTableTitle"))
        if not title.startswith("別表第六"):
            continue
        def rows_of(n):
            if isinstance(n, dict):
                if n.get("tag") == "TableRow":
                    b6rows.append([norm(text_of(c)) for c in kids(n)])
                for c in n.get("children", []):
                    rows_of(c)
        rows_of(t)
    mism, nrow = [], 0
    for cells in b6rows:
        for j in range(0, len(cells) - 2, 3):
            m = re.fullmatch(r"(\d+)年(以下)?", cells[j])
            if not m or not cells[j + 1].replace(",", "").isdigit():
                continue
            n = int(m.group(1))
            for k in (range(1, n + 1) if m.group(2) else [n]):
                nrow += 1
                base_k = 400_000 * k if k <= 20 else 8_000_000 + 700_000 * (k - 20)
                exp = (max(base_k, 800_000), max(base_k, 800_000) + 1_000_000)
                got = (int(cells[j + 1].replace(",", "")) * 1000, int(cells[j + 2].replace(",", "")) * 1000)
                if got != exp:
                    mism.append((k, got, exp))
    results.append({"id": "C-beppyo6-rows", "where": "PS §2.5・M §5 C1", "what": "別表第六（asof 2026-11-09）の1〜40年の一般・障害の欄が所法30③⑥の式と一致",
                    "kind": "calc", "got": {"rows": nrow, "mismatch": mism[:5]}, "ok": nrow == 40 and not mism})
    diffs.append(f"- 別表第六（asof 2026-11-09）：読み取った年数 {nrow}、式との不一致 {len(mism)}")
    # 地方税法 附則3の3
    for a in C_ALL:
        lw = get_law("chiho", a)
        n = node_for(lw, "suppl:ORIG", "3_3")
        diff_summary[f"chiho 原始附則3の3 @{a}"] = hashlib.sha256((text_of(n) if n else "").encode()).hexdigest()[:16]
    diffs.append(f"- 地方税法 原始附則第3条の3 の本文の SHA-256（先頭16桁）：{ {k: v for k, v in diff_summary.items() if '3の3' in k} }")

    # 所令70①二の旧・新の比較（担当の C7 とは別の書き方：年の差で直接書く）
    c7 = []
    for Y in range(2025, 2041):
        for py in range(Y - 20, Y):
            for p_ideco in (False, True):
                for cur_ideco in (False, True):
                    old = (Y - py <= (19 if cur_ideco else 4))
                    # 新：ハ → ロ → イ
                    if cur_ideco and (Y - py <= 19):
                        new = Y - py <= 19
                    elif p_ideco and py >= 2026 and Y - py <= 9:
                        new = (Y - py <= 9) if py >= 2026 else (Y - py <= 4)
                    else:
                        new = Y - py <= 4
                    c7.append((Y, py, p_ideco, cur_ideco, old, new))
    diff7 = [x for x in c7 if x[4] != x[5]]
    c7_sum = {"n": len(c7), "n_diff": len(diff7), "first_year": min((x[0] for x in diff7), default=None),
              "same_2025_2030": all(x[4] == x[5] for x in c7 if x[0] <= 2030)}
    results.append({"id": "C7-indep", "where": "M §5 C7・H3・I2", "what": "所令70①二 改正前後で違いが出る最初の年は2031年、2025〜2030年は同じ",
                    "kind": "calc", "got": c7_sum, "ok": c7_sum["first_year"] == 2031 and c7_sum["same_2025_2030"]})

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "checks.json").write_text(json.dumps({"results": results, "diff_summary": diff_summary}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (OUT / "diffs.md").write_text("\n".join(diffs) + "\n", encoding="utf-8")
    n_ok = sum(1 for r in results if r.get("ok"))
    n_x = sum(1 for r in results if r["id"].startswith("X-"))
    n_x_ok = sum(1 for r in results if r["id"].startswith("X-") and r.get("ok"))
    lines = [f"# R2B taishoku 検証の照合結果", "",
             f"- 項目 {len(results)}、一次情報と一致 {n_ok}、不一致 {len(results) - n_ok}",
             f"- うち ID が X- の {n_x} 項目は「反証の確認」（文書の主張と反対の事実が一次情報にあるかを見る項目）。一致 {n_x_ok} は、その数だけ文書の誤りを一次情報で確かめたことを表す",
             "- 不一致の項目は、文書か照合の断片のどちらかの誤り。最終の実行で不一致が0件になるまで、断片の書き方（条文の語順・かっこ書）を原文に合わせた",
             "", "| ID | 文書・節 | 主張 | 結果 | 備考 |", "|---|---|---|---|---|"]
    for r in results:
        note = r.get("note") or ""
        if r["kind"] in ("rev", "caption", "webmeta", "calc") and "got" in r:
            note = (note + " " + json.dumps(r["got"], ensure_ascii=False, default=str))[:300]
        verdict = ("反証を確認（文書の誤り）" if r["id"].startswith("X-") else "一致") if r.get("ok") else "**不一致**"
        lines.append(f"| {r['id']} | {r['where']} | {r['what']} | {verdict} | {note.replace('|', '／')} |")
    (OUT / "checks.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"items={len(results)} ok={n_ok} ng={len(results) - n_ok}")
    for r in results:
        if not r.get("ok"):
            print("NG", r["id"], r["what"], r.get("note", ""), json.dumps(r.get("got"), ensure_ascii=False, default=str)[:200])


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")
    mode = argv[0] if argv else "check"
    if mode == "egov":
        cmd_egov(argv[1:] or None)
    elif mode == "web":
        cmd_web(argv[1:] or None)
    elif mode == "check":
        cmd_check()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

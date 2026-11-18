"""R2X_jinteki の独立した検証（反証役）。

別の担当が書いた次の文書の数値・条番号・通達/通知の番号と日付・施行日・適用年分・URL を、一次情報に当たり直して確かめる。
  docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md
  docs/measurements/20261109_round2_jinteki-fetch-and-checks.md
  docs/hypotheses/20261109_round2_jinteki-model.md
  docs/inferences/20261109_round2_jinteki-cases.md
担当のスクリプト（R2X_jinteki_egov.py など）とその出力は使わない。e-Gov 法令API v2 と行政のサイトから取り直し、
自分で書いた（担当とは別の）テキスト化と照合で確かめる。

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_jinteki_verify.py egov    # 条文の取得
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_jinteki_verify.py web     # 行政の資料の取得
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_jinteki_verify.py check   # 照合（ネットワークなし）
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_jinteki_verify.py web nenkin_hifuyo   # 1件だけ追加で取得（2回目の取得）
  （条文の一部を表示するだけの便利ツールは .work/tools/R2X_jinteki_show.py に分けた）

- e-Gov 法令API v2 の使い方は scripts/R1_egov_articles.py を読んで写した（import しない）。標準ライブラリのみ。
- ダウンロードは取得ごとに新しい空のディレクトリ .work/downloads/<YYYYMMDD-HHMMSS>_R2X_jinteki_verify_<egov|web>/ に置く
  （信頼できないデータ。その中で何も実行しない）。HTML から取り出したテキストは .work/text/<ts>_R2X_jinteki_verify_web/ に置く。
- 取得の記録と照合の結果は scripts/results/R2X_jinteki_verify/ に書く：
  egov_manifest.json（取得した版の記録）、web_manifest.json・web_manifest_extra_<ts>.json（URL・HTTP・Last-Modified・SHA-256）、
  checks.json・checks.md（項目ごとの照合の結果）、
  diffs.md（版の間で変わった項・号の一覧と、所得税・住民税の政令・省令の号ごとの文字列の違い）
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。個人の情報は送らない。官報は取得しない。
"""
import difflib
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
OUT = ROOT / "scripts" / "results" / "R2X_jinteki_verify"

# (略称, law_id, 期待する法令名, [asof...], 改正附則を含めるか)
LAWS = [
    ("shotoku", "340AC0000000033", "所得税法", ["2025-12-31", "2026-12-31", "2027-01-01"], True),
    ("shotoku-rei", "340CO0000000096", "所得税法施行令", ["2025-12-31", "2026-12-31", "2027-01-01"], True),
    ("shotoku-ki", "340M50000040011", "所得税法施行規則", ["2025-12-31", "2026-12-31"], False),
    ("chiho", "325AC0000000226", "地方税法", ["2026-01-01", "2027-01-01", "2028-01-01"], True),
    ("chiho-rei", "325CO0000000245", "地方税法施行令", ["2026-01-01", "2027-01-01", "2028-01-01"], True),
    ("chiho-ki", "329M50000002023", "地方税法施行規則", ["2026-01-01", "2027-01-01"], False),
    ("kounen", "329AC0000000115", "厚生年金保険法", ["2026-11-09"], False),
    ("kounen-rei", "329CO0000000110", "厚生年金保険法施行令", ["2026-11-09"], False),
    ("kokunen", "334AC0000000141", "国民年金法", ["2026-11-09"], False),
    ("kokunen-rei", "334CO0000000184", "国民年金法施行令", ["2026-11-09"], False),
    ("seishin", "325AC0100000123", "精神保健及び精神障害者福祉に関する法律", ["2026-11-09"], False),
    ("seishin-rei", "325CO0000000155", "精神保健及び精神障害者福祉に関する法律施行令", ["2026-11-09"], False),
    ("shintai", "324AC1000000283", "身体障害者福祉法", ["2026-11-09"], False),
    ("shintai-ki", "325M50000100015", "身体障害者福祉法施行規則", ["2026-11-09"], False),
    ("senshobyo", "338AC1000000168", "戦傷病者特別援護法", ["2026-11-09"], False),
    ("genbaku", "406AC0000000117", "原子爆弾被爆者に対する援護に関する法律", ["2026-11-09"], False),
    # 推測の文書が引く租税特別措置法（第29条の4・第41条の16）
    ("sochi", "332AC0000000026", "租税特別措置法", ["2026-12-31"], False),
]

WEB = {
    # 国税庁 タックスアンサー・Q&A
    "ta_1160": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1160.htm",
    "ta_1160_qa": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1160_qa.htm",
    "ta_1170": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1170.htm",
    "ta_1170_qa": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1170_qa.htm",
    "ta_1171": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1171.htm",
    "ta_1171_qa": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1171_qa.htm",
    "ta_1184": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1184.htm",
    "ta_1185": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1185.htm",
    "ta_1186": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1186.htm",
    # 国税庁 質疑応答事例・基本通達
    "shitsugi_05_31": "https://www.nta.go.jp/law/shitsugi/shotoku/05/31.htm",
    "shitsugi_05_32": "https://www.nta.go.jp/law/shitsugi/shotoku/05/32.htm",
    "shitsugi_05_63": "https://www.nta.go.jp/law/shitsugi/shotoku/05/63.htm",
    "shitsugi_gensen_03_10": "https://www.nta.go.jp/law/shitsugi/gensen/03/10.htm",
    "kihon_01_07": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/01/07.htm",
    "kihon_16_06": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/16/06.htm",
    # 国税庁 PDF
    "nencho2025_105": "https://www.nta.go.jp/publication/pamph/gensen/nencho2025/pdf/105.pdf",
    "nencho2026_105": "https://www.nta.go.jp/publication/pamph/gensen/nencho2026/pdf/105.pdf",
    "gensen_2026kaisei": "https://www.nta.go.jp/publication/pamph/gensen/2026kaisei.pdf",
    # 厚生労働省・内閣府
    "mhlw_kaigo_020904_2_3": "https://www.mhlw.go.jp/topics/kaigo/kaigi/020904/2-3.html",
    "cao_r07_12mhlw_140": "https://www.cao.go.jp/bunken-suishin/teianbosyu/doc/r07/tb_r7fu_12mhlw_140.pdf",
    "mhlw_tdoc_S52": "https://www.mhlw.go.jp/web/t_doc?dataId=00tb0189&dataType=1&pageNo=1",
    "mhlw_tdoc_R7_0704": "https://www.mhlw.go.jp/web/t_doc?dataId=00tc9249&dataType=1&pageNo=1",
    "mhlw_tdoc_R7_1001": "https://www.mhlw.go.jp/web/t_doc?dataId=00tc9348&dataType=1&pageNo=1",
    # 総務省 取扱通知（市町村税関係）
    "soumu_tsuchi": "https://www.soumu.go.jp/main_content/001071661.pdf",
    # 協会けんぽ
    "kyokai_faq": "https://www.kyoukaikenpo.or.jp/faq/dependent_status/",
    "kyokai_fuyouidou_guide2607": "https://www.kyoukaikenpo.or.jp/assets/n_fuyouidou_guide2607.pdf",
    # 日本年金機構（2回目の取得で追加：`web nenkin_hifuyo`）
    "nenkin_hifuyo": "https://www.nenkin.go.jp/service/kounen/tekiyo/hihokensha1/20141202.html",
}


# ---------------------------------------------------------------- 取得
def http_get(url, accept="*/*", timeout=300):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept, "Accept-Language": "ja"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.geturl(), dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, url, dict(e.headers or {}), e.read()


def cmd_egov():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_jinteki_verify_egov"
    dl.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    man = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "fetches": [], "errors": []}
    for short, law_id, title, asofs, with_amend in LAWS:
        for asof in asofs:
            q = {"response_format": "json", "asof": asof}
            if not with_amend:
                q["omit_amendment_suppl_provision"] = "true"
            url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode(q)
            try:
                st, _, _, body = http_get(url, accept="application/json")
                fn = dl / f"{short}_{asof}.json"
                fn.write_bytes(body)
                rec = {"short": short, "law_id": law_id, "asof": asof, "url": url, "status": st,
                       "file": fn.name, "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
                if st == 200:
                    d = json.loads(body)
                    ri = d.get("revision_info") or {}
                    li = d.get("law_info") or {}
                    rec.update({"law_title": ri.get("law_title"), "title_ok": ri.get("law_title") == title,
                                "law_num": li.get("law_num"),
                                "law_revision_id": ri.get("law_revision_id"),
                                "amendment_law_num": ri.get("amendment_law_num"),
                                "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                                "current_revision_status": ri.get("current_revision_status"),
                                "updated": ri.get("updated")})
                man["fetches"].append(rec)
                print("ok" if st == 200 else "NG", short, asof, rec.get("law_revision_id"), rec.get("current_revision_status"), flush=True)
            except Exception as e:  # noqa: BLE001
                man["errors"].append({"short": short, "asof": asof, "error": repr(e)})
                print("ERR", short, asof, repr(e), flush=True)
            time.sleep(SLEEP)
    (OUT / "egov_manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")


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
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_jinteki_verify_web"
    dl.mkdir(parents=True, exist_ok=False)
    tx = ROOT / ".work" / "text" / f"{ts}_R2X_jinteki_verify_web"
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
            st, final, hdr, body = http_get(url, timeout=60)
            ctype = hdr.get("Content-Type", "")
            ext = ".pdf" if ("pdf" in ctype.lower() or final.lower().endswith(".pdf")) else ".html"
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
        print(rec["id"], rec.get("status"), rec.get("last_modified"), (rec.get("sha256") or "")[:16], rec.get("error", ""), flush=True)
    name = "web_manifest.json" if not ids else f"web_manifest_extra_{ts}.json"
    (OUT / name).write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- 条文のテキスト化（担当の render とは別に書いた）
def text_of(n):
    """ノードの文字列を連結する（ルビの読み Rt は落とす。空白は入れない）。"""
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
            elif t in ("AppdxTable", "AppdxNote", "Appdx", "AppdxStyle"):
                self.appdx.append(n)
        walk(self.root, fn)

    def suppl_of(self, amend):
        """AmendLawNum が amend（漢数字の表記の揺れ「一三」「十三」を両方試す）に一致する改正附則。"""
        out = []
        for s in self.suppl:
            an = s.get("attr", {}).get("AmendLawNum", "") or ""
            if re.sub(r"\s", "", an) and re.search(amend, an):
                out.append(s)
        return out


def locate(node, path):
    """path の例：'1/31'（第1項第31号）、'1/30/イ'（第1項第30号イ）、'2'（第2項）、'2/三'（号の見出しで指定）。
    段は Paragraph(Num) → Item(Num) → Subitem1(見出し) → Subitem2(見出し)。"""
    cur = node
    if not path:
        return cur
    steps = path.split("/")
    levels = ["Paragraph", "Item", "Subitem1", "Subitem2", "Subitem3"]
    for lvl, st in zip(levels, steps):
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
    """空白を除き、全角英数字を半角にし（NFKC）、ダッシュ類（−－‐‑）を「-」にそろえる。"""
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub("[−－‐‑]", "-", s)
    return re.sub(r"\s", "", s)


def has_all(text, frags):
    """frags（「…」で区切った断片）がこの順に text に現れるか。"""
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
# 各項目：(ID, 対象の文書と節, 主張の要約, 種類, 引数)
#   種類 "law"：(略称, asof, 'main'|'suppl:<AmendLawNum の正規表現>', 条番号, 項/号の path, [断片...])
#   種類 "rev"：(略称, asof, 期待する law_revision_id, 期待する状態)
#   種類 "web"：(資料ID, [断片...])  HTML のテキストに断片が順に現れるか
#   種類 "webmeta"：(資料ID, Last-Modified の日付(YYYY-MM-DD) か None, SHA-256 の先頭 か None)
PS = "PS"   # docs/public-sources/20261109_round2_jinteki-laws-and-guidance.md
MS = "M"    # docs/measurements/20261109_round2_jinteki-fetch-and-checks.md
HY = "H"    # docs/hypotheses/20261109_round2_jinteki-model.md
IN = "I"    # docs/inferences/20261109_round2_jinteki-cases.md

S_ALL = ["2025-12-31", "2026-12-31", "2027-01-01"]
C_ALL = ["2026-01-01", "2027-01-01", "2028-01-01"]
R8_12 = r"令和八年.*法律第(十二|一二)号"
R7_120 = r"令和七年.*政令第(百二十|一二〇)号"
R8_93 = r"令和八年.*政令第(九十三|九三)号"
R7_119 = r"令和七年.*政令第(百十九|一一九)号"
R8_83 = r"令和八年.*政令第(八十三|八三)号"
R8_2 = r"令和八年.*法律第(二)号"


def claims():
    C = []

    def law(cid, where, what, short, asofs, part, art, path, frags):
        for a in (asofs if isinstance(asofs, list) else [asofs]):
            C.append((f"{cid}@{a}" if isinstance(asofs, list) and len(asofs) > 1 else cid, where, what, "law",
                      (short, a, part, art, path, frags)))

    # §0 版
    revs = [
        ("shotoku", "2025-12-31", "340AC0000000033_20251218_507AC0000000013", "PreviousEnforced"),
        ("shotoku", "2026-12-31", "340AC0000000033_20261201_508AC0000000012", "UnEnforced"),
        ("shotoku", "2027-01-01", "340AC0000000033_20270101_508AC0000000012", "UnEnforced"),
        ("shotoku-rei", "2025-12-31", "340CO0000000096_20251201_507CO0000000120", "PreviousEnforced"),
        ("shotoku-rei", "2026-12-31", "340CO0000000096_20261201_508CO0000000093", "UnEnforced"),
        ("shotoku-rei", "2027-01-01", "340CO0000000096_20270101_508CO0000000093", "UnEnforced"),
        ("shotoku-ki", "2025-12-31", "340M50000040011_20251201_507M60000040018", "PreviousEnforced"),
        ("shotoku-ki", "2026-12-31", "340M50000040011_20261211_508M60000040017", "UnEnforced"),
        ("chiho", "2026-01-01", "325AC0000000226_20260101_507AC0000000041", "PreviousEnforced"),
        ("chiho", "2027-01-01", "325AC0000000226_20270101_508AC0000000002", "UnEnforced"),
        ("chiho", "2028-01-01", "325AC0000000226_20280101_508AC0000000002", "UnEnforced"),
        ("chiho-rei", "2026-01-01", "325CO0000000245_20260101_507CO0000000119", "PreviousEnforced"),
        ("chiho-rei", "2027-01-01", "325CO0000000245_20270101_508CO0000000083", "UnEnforced"),
        ("chiho-rei", "2028-01-01", "325CO0000000245_20280101_508CO0000000083", "UnEnforced"),
        ("chiho-ki", "2026-01-01", "329M50000002023_20260101_507M60000008116", "PreviousEnforced"),
        ("chiho-ki", "2027-01-01", "329M50000002023_20270101_508M60000008089", "UnEnforced"),
        ("kounen", "2026-11-09", "329AC0000000115_20261001_507AC0000000074", "CurrentEnforced"),
        ("kounen-rei", "2026-11-09", "329CO0000000110_20261001_508CO0000000276", "CurrentEnforced"),
        ("kokunen", "2026-11-09", "334AC0000000141_20261001_507AC0000000074", "CurrentEnforced"),
        ("kokunen-rei", "2026-11-09", "334CO0000000184_20261001_508CO0000000226", "CurrentEnforced"),
        ("seishin", "2026-11-09", "325AC0100000123_20261001_507AC0000000087", "CurrentEnforced"),
        ("seishin-rei", "2026-11-09", "325CO0000000155_20260301_507CO0000000368", "CurrentEnforced"),
        ("shintai", "2026-11-09", "324AC1000000283_20260624_508AC0000000046", "CurrentEnforced"),
        ("shintai-ki", "2026-11-09", "325M50000100015_20260331_508M60000100067", "CurrentEnforced"),
        ("senshobyo", "2026-11-09", "338AC1000000168_20261001_507AC0000000087", "CurrentEnforced"),
        ("genbaku", "2026-11-09", "406AC0000000117_20261001_507AC0000000087", "CurrentEnforced"),
    ]
    for s, a, rid, st in revs:
        C.append((f"rev:{s}@{a}", f"{PS} §0", f"{s} asof {a} の版 {rid}（{st}）", "rev", (s, a, rid, st)))

    # §1.1 所法2①
    law("PS1.1-28", f"{PS} §1.1", "所法2①二十八 障害者の定義", "shotoku", S_ALL, "main", "2", "1/28",
        ["障害者", "精神上の障害により事理を弁識する能力を欠く常況にある者、失明者その他の精神又は身体に障害がある者で政令で定めるものをいう。"])
    law("PS1.1-29", f"{PS} §1.1", "所法2①二十九 特別障害者の定義", "shotoku", S_ALL, "main", "2", "1/29",
        ["特別障害者", "障害者のうち、精神又は身体に重度の障害がある者で政令で定めるものをいう。"])
    law("PS1.1-30", f"{PS} §1.1", "所法2①三十 寡婦（イ(1)扶養親族 (2)合計所得金額 500万円以下 (3)財務省令、ロ）", "shotoku", S_ALL, "main", "2", "1/30",
        ["寡婦", "次に掲げる者でひとり親に該当しないものをいう。", "夫と離婚した後婚姻をしていない者のうち、次に掲げる要件を満たすもの",
         "扶養親族を有すること。", "総所得金額、退職所得金額及び山林所得金額の合計額（以下この条において「合計所得金額」という。）が五百万円以下であること。",
         "その者と事実上婚姻関係と同様の事情にあると認められる者として財務省令で定めるものがいないこと。",
         "夫と死別した後婚姻をしていない者又は夫の生死の明らかでない者で政令で定めるもののうち、イ（２）及び（３）に掲げる要件を満たすもの"])
    law("PS1.1-31", f"{PS} §1.1", "所法2①三十一 ひとり親（イ 子、ロ 500万円以下、ハ 財務省令）", "shotoku", S_ALL, "main", "2", "1/31",
        ["ひとり親", "現に婚姻をしていない者又は配偶者の生死の明らかでない者で政令で定めるもののうち、次に掲げる要件を満たすものをいう。",
         "その者と生計を一にする子で政令で定めるものを有すること。", "合計所得金額が五百万円以下であること。",
         "その者と事実上婚姻関係と同様の事情にあると認められる者として財務省令で定めるものがいないこと。"])
    law("PS1.1-33a", f"{PS} §1.1", "所法2①三十三 同一生計配偶者 令和7年分 58万円以下", "shotoku", "2025-12-31", "main", "2", "1/33", ["五十八万円以下"])
    law("PS1.1-33b", f"{PS} §1.1", "所法2①三十三 同一生計配偶者 令和8年分 62万円以下", "shotoku", "2026-12-31", "main", "2", "1/33", ["六十二万円以下"])
    law("PS1.1-34a", f"{PS} §1.1", "所法2①三十四 扶養親族 令和7年分 58万円以下", "shotoku", "2025-12-31", "main", "2", "1/34", ["五十八万円以下"])
    law("PS1.1-34b", f"{PS} §1.1", "所法2①三十四 扶養親族 令和8年分 62万円以下", "shotoku", "2026-12-31", "main", "2", "1/34", ["六十二万円以下"])

    # §1.2 所法79〜81
    law("PS1.2-79-1", f"{PS} §1.2", "所法79① 27万円（特別障害者 40万円）", "shotoku", S_ALL, "main", "79", "1",
        ["居住者が障害者である場合には", "二十七万円（その者が特別障害者である場合には、四十万円）を控除する。"])
    law("PS1.2-79-2", f"{PS} §1.2", "所法79② 同一生計配偶者又は扶養親族 一人につき27万円（40万円）", "shotoku", S_ALL, "main", "79", "2",
        ["居住者の同一生計配偶者又は扶養親族が障害者である場合には", "その障害者一人につき二十七万円", "特別障害者である場合には、四十万円"])
    law("PS1.2-79-3", f"{PS} §1.2", "所法79③ 同居を常況、75万円", "shotoku", S_ALL, "main", "79", "3",
        ["居住者の同一生計配偶者又は扶養親族が特別障害者で、かつ、その居住者又はその居住者の配偶者若しくはその居住者と生計を一にするその他の親族のいずれかとの同居を常況としている者である場合には、前項の規定にかかわらず",
         "その特別障害者一人につき七十五万円を控除する。"])
    law("PS1.2-80", f"{PS} §1.2", "所法80① 寡婦 27万円", "shotoku", S_ALL, "main", "80", "1", ["居住者が寡婦である場合には", "二十七万円を控除する。"])
    law("PS1.2-81a", f"{PS} §1.2", "所法81① ひとり親 35万円（令和7年分・令和8年分の版）", "shotoku", ["2025-12-31", "2026-12-31"], "main", "81", "1",
        ["居住者がひとり親である場合には", "三十五万円を控除する。"])
    law("PS1.2-81b", f"{PS} §1.2", "所法81① ひとり親 38万円（asof 2027-01-01）", "shotoku", "2027-01-01", "main", "81", "1",
        ["居住者がひとり親である場合には", "三十八万円を控除する。"])

    # §1.3 所法85
    law("PS1.3-85-1", f"{PS} §1.3", "所法85① 12月31日の現況、子の死亡時のただし書", "shotoku", S_ALL, "main", "85", "1",
        ["特別障害者若しくはその他の障害者、寡婦、ひとり親又は勤労学生に該当するかどうかの判定は、その年十二月三十一日（その者がその年の中途において死亡し、又は出国をする場合には、その死亡又は出国の時。",
         "の現況による。ただし、その居住者の子がその当時既に死亡している場合におけるその子がその居住者の第二条第一項第三十一号イ（定義）に規定する政令で定める子に該当するかどうかの判定は、当該死亡の時の現況による。"])
    law("PS1.3-85-2", f"{PS} §1.3", "所法85② 同一生計配偶者・扶養親族の障害者の判定は12月31日（死亡時）", "shotoku", S_ALL, "main", "85", "2",
        ["同居特別障害者", "その年十二月三十一日の現況による。ただし、その同一生計配偶者又は扶養親族がその当時既に死亡している場合は、当該死亡の時の現況による。"])
    law("PS1.3-85-2ref", f"{PS} §1.3", "所法85② 同居特別障害者の語を第187条・第190条第2号ハ・第194条第1項第3号・第203条の3第1号ト・第203条の6第1項第5号で使う",
        "shotoku", "2026-12-31", "main", "85", "2",
        ["第百八十七条", "第百九十条第二号ハ", "第百九十四条第一項第三号", "第二百三条の三第一号ト", "第二百三条の六第一項第五号"])
    law("PS1.3-85-4", f"{PS} §1.3", "所法85④ 配偶者が同一生計配偶者と他の居住者の扶養親族の両方に当たるとき、いずれか一にのみ該当とみなす", "shotoku", "2026-12-31", "main", "85", "4",
        ["同一生計配偶者に該当し、かつ、他の居住者の扶養親族にも該当する場合には", "政令で定めるところにより、これらのうちいずれか一にのみ該当するものとみなす。"])
    law("PS1.3-85-6", f"{PS} §1.3", "所法85⑥ 二以上の居住者の扶養親族（又は特定親族）はいずれか一の居住者の扶養親族とみなす", "shotoku", "2026-12-31", "main", "85", "6",
        ["二以上の居住者の扶養親族又は特定親族に該当する者がある場合には", "いずれか一の居住者の扶養親族又は特定親族にのみ該当するものとみなす。"])
    law("PS1.3-rei218", f"{PS} §1.3・{HY} H4", "所令218 の見出し（同一生計配偶者の所属、法85④）", "shotoku-rei", "2026-12-31", "main", "218", "", ["二以上の居住者がある場合の同一生計配偶者の所属", "法第八十五条第四項"])
    law("PS1.3-rei219", f"{PS} §1.3・{HY} H4", "所令219 の見出し（扶養親族及び特定親族の所属、法85⑥）", "shotoku-rei", "2026-12-31", "main", "219", "", ["二以上の居住者がある場合の扶養親族及び特定親族の所属", "法第八十五条第六項"])

    # §1.4 附則
    law("PS1.4-R8L12-1-5", f"{PS} §1.4", "令和8年法律第12号 附則第1条第5号（令和九年一月一日）イ：第81条第1項の改正規定・附則第8条", "shotoku", "2027-01-01", "suppl:" + R8_12, "1", "1/5",
        ["令和九年一月一日", "第一条中所得税法", "同法第八十一条第一項の改正規定", "附則第五条、第八条"])
    law("PS1.4-R8L12-8", f"{PS} §1.4", "令和8年法律第12号 附則第8条：新所得税法第81条は令和9年分以後", "shotoku", "2027-01-01", "suppl:" + R8_12, "8", "",
        ["ひとり親控除に関する経過措置", "新所得税法第八十一条の規定は、令和九年分以後の所得税について適用し、令和八年分以前の所得税については、なお従前の例による。"])
    law("PS1.4-R7S120-1-1i", f"{PS} §1.4", "令和7年政令第120号 附則第1条第1号イ：第11条の2第2項の改正規定 令和7年12月1日", "shotoku-rei", "2025-12-31", "suppl:" + R7_120, "1", "1/1/イ",
        ["第十一条の二第二項"])
    law("PS1.4-R7S120-1-1", f"{PS} §1.4", "令和7年政令第120号 附則第1条第1号：令和七年十二月一日", "shotoku-rei", "2025-12-31", "suppl:" + R7_120, "1", "1/1",
        ["令和七年十二月一日"])
    law("PS1.4-R7S120-2sub", f"{PS} §1.4", "令和7年政令第120号 附則第2条第1項（内容）：改正後の所得税法施行令第11条の2第2項は令和7年分以後", "shotoku-rei", "2025-12-31", "suppl:" + R7_120, "2", "1",
        ["第一条の規定による改正後の所得税法施行令（以下「新令」という。）第十一条の二第二項の規定は、令和七年分以後の所得税について適用し、令和六年分以前の所得税については、なお従前の例による。"])
    law("PS1.4-R7S120-2", f"{PS} §1.4", "令和7年政令第120号 附則第2条第1項（文書の引用のとおりの文字列）", "shotoku-rei", "2025-12-31", "suppl:" + R7_120, "2", "1",
        ["新令第十一条の二第二項の規定は、令和七年分以後の所得税について適用し、令和六年分以前の所得税については、なお従前の例による。"])
    law("PS1.4-R7S120-2cap", f"{PS} §1.4", "令和7年政令第120号 附則第2条の見出し「ひとり親の範囲に関する経過措置」", "shotoku-rei", "2025-12-31", "suppl:" + R7_120, "2", "",
        ["ひとり親の範囲に関する経過措置"])
    law("PS1.4-R8S93-1-1", f"{PS} §1.4", "令和8年政令第93号 附則第1条第1号：第11条の2第2項の改正規定 令和8年12月1日", "shotoku-rei", "2026-12-31", "suppl:" + R8_93, "1", "1/1",
        ["第十一条の二第二項", "令和八年十二月一日"])
    law("PS1.4-R8S93-2-1sub", f"{PS} §1.4", "令和8年政令第93号 附則第2条第1項（内容）：令和8年分以後", "shotoku-rei", "2026-12-31", "suppl:" + R8_93, "2", "1",
        ["改正後の所得税法施行令（以下「新令」という。）第十一条の二第二項の規定は、令和八年分以後の所得税について適用し、令和七年分以前の所得税については、なお従前の例による。"])
    law("PS1.4-R8S93-2-1", f"{PS} §1.4", "令和8年政令第93号 附則第2条第1項（文書の引用のとおりの文字列）", "shotoku-rei", "2026-12-31", "suppl:" + R8_93, "2", "1",
        ["新令第十一条の二第二項の規定は、令和八年分以後の所得税について適用し、令和七年分以前の所得税については、なお従前の例による。"])
    law("PS1.4-R8S93-2-2", f"{PS} §1.4", "令和8年政令第93号 附則第2条第2項：施行日前に確定申告書を提出した者等の更正の請求", "shotoku-rei", "2026-12-31", "suppl:" + R8_93, "2", "2",
        ["更正の請求"])
    law("PS1.4-500", f"{PS} §1.4", "所法2①三十一ロ 500万円以下（asof 2027-01-01 も）", "shotoku", "2027-01-01", "main", "2", "1/31/ロ", ["合計所得金額が五百万円以下であること。"])
    law("PS1.4-11-2-58", f"{PS} §1.4", "所令11の2② 58万円以下（令和7年分の版）", "shotoku-rei", "2025-12-31", "main", "11_2", "2",
        ["総所得金額、退職所得金額及び山林所得金額の合計額が五十八万円以下の子（他の者の同一生計配偶者又は扶養親族とされている者を除く。）"])
    law("PS1.4-11-2-62", f"{PS} §1.4", "所令11の2② 62万円以下（令和8年分・令和9年分の版）", "shotoku-rei", ["2026-12-31", "2027-01-01"], "main", "11_2", "2",
        ["総所得金額、退職所得金額及び山林所得金額の合計額が六十二万円以下の子（他の者の同一生計配偶者又は扶養親族とされている者を除く。）"])

    # §1.5 所令10
    law("PS1.5-10-1-1", f"{PS} §1.5", "所令10①一 事理弁識・知的障害の判定（児相・更生相談所・精神保健福祉センター・精神保健指定医）", "shotoku-rei", S_ALL, "main", "10", "1/1",
        ["精神上の障害により事理を弁識する能力を欠く常況にある者又は児童相談所、知的障害者更生相談所", "精神保健福祉センター", "精神保健指定医の判定により知的障害者とされた者"])
    law("PS1.5-10-1-2", f"{PS} §1.5", "所令10①二 精神法45② 精神障害者保健福祉手帳の交付を受けている者", "shotoku-rei", S_ALL, "main", "10", "1/2",
        ["精神保健及び精神障害者福祉に関する法律", "第四十五条第二項", "精神障害者保健福祉手帳の交付を受けている者"])
    law("PS1.5-10-1-3", f"{PS} §1.5", "所令10①三 身障法15④ 手帳に身体上の障害がある者として記載", "shotoku-rei", S_ALL, "main", "10", "1/3",
        ["身体障害者福祉法", "第十五条第四項", "身体障害者手帳に身体上の障害がある者として記載されている者"])
    law("PS1.5-10-1-4", f"{PS} §1.5", "所令10①四 戦傷法4 戦傷病者手帳", "shotoku-rei", S_ALL, "main", "10", "1/4",
        ["戦傷病者特別援護法", "第四条", "戦傷病者手帳の交付を受けている者"])
    law("PS1.5-10-1-5", f"{PS} §1.5", "所令10①五 被爆法11① 厚生労働大臣の認定", "shotoku-rei", S_ALL, "main", "10", "1/5",
        ["原子爆弾被爆者に対する援護に関する法律", "第十一条第一項", "厚生労働大臣の認定を受けている者"])
    law("PS1.5-10-1-6", f"{PS} §1.5", "所令10①六 常に就床を要し、複雑な介護を要する者", "shotoku-rei", S_ALL, "main", "10", "1/6", ["常に就床を要し、複雑な介護を要する者"])
    law("PS1.5-10-1-7", f"{PS} §1.5", "所令10①七 年齢65歳以上、市町村長又は特別区の区長、老人福祉法5の4②各号、市町村長等の認定", "shotoku-rei", S_ALL, "main", "10", "1/7",
        ["精神又は身体に障害のある年齢六十五歳以上の者で、その障害の程度が第一号又は第三号に掲げる者に準ずるものとして市町村長又は特別区の区長",
         "老人福祉法", "第五条の四第二項各号", "市町村長等", "の認定を受けている者"])
    law("PS1.5-10-2-1", f"{PS} §1.5", "所令10②一 重度の知的障害者", "shotoku-rei", S_ALL, "main", "10", "2/1", ["前項第一号", "重度の知的障害者とされた者"])
    law("PS1.5-10-2-2", f"{PS} §1.5", "所令10②二 精神令6③ 障害等級 一級", "shotoku-rei", S_ALL, "main", "10", "2/2",
        ["前項第二号", "精神保健及び精神障害者福祉に関する法律施行令", "第六条第三項", "障害等級が一級である者として記載されている者"])
    law("PS1.5-10-2-3", f"{PS} §1.5", "所令10②三 一級又は二級", "shotoku-rei", S_ALL, "main", "10", "2/3", ["前項第三号", "身体上の障害の程度が一級又は二級である者として記載されている者"])
    law("PS1.5-10-2-4", f"{PS} §1.5", "所令10②四 恩給法別表第一号表ノ二 特別項症から第三項症まで", "shotoku-rei", S_ALL, "main", "10", "2/4",
        ["前項第四号", "恩給法", "別表第一号表ノ二の特別項症から第三項症までである者として記載されている者"])
    law("PS1.5-10-2-5", f"{PS} §1.5", "所令10②五 前項第五号又は第六号", "shotoku-rei", S_ALL, "main", "10", "2/5", ["前項第五号又は第六号に掲げる者"])
    law("PS1.5-10-2-6", f"{PS} §1.5", "所令10②六 前項第七号 特別障害者に準ずる認定", "shotoku-rei", S_ALL, "main", "10", "2/6", ["前項第七号", "第一号又は第三号に掲げる者に準ずるものとして市町村長等の認定を受けている者"])
    law("PS1.5-31-2-14", f"{PS} §1.5", "所令31の2第14号 療育手帳の定義", "shotoku-rei", "2026-12-31", "main", "31_2", "1/14",
        ["療育手帳", "児童相談所又は知的障害者更生相談所において知的障害と判定された者に対して支給される手帳で、その者の障害の程度その他の事項の記載があるもの"])

    # §1.6 所令11・11の2①、所規1の3・1の4
    law("PS1.6-11", f"{PS} §1.6", "所令11 寡婦の範囲：五号（太平洋戦争、国外、船舶航空機3月、危難1年、3年）", "shotoku-rei", S_ALL, "main", "11", "1",
        ["太平洋戦争の終結の当時もとの陸海軍に属していた者で、まだ国内に帰らないもの", "国外", "船舶", "航空機", "三月以上", "危難", "一年以上", "三年以上"])
    law("PS1.6-11-2-1", f"{PS} §1.6", "所令11の2① 前条各号の者の配偶者", "shotoku-rei", S_ALL, "main", "11_2", "1", ["前条各号に掲げる者の配偶者"])
    law("PS1.6-ki-1-3-1", f"{PS} §1.6", "所規1の3一 世帯主：未届の夫", "shotoku-ki", ["2025-12-31", "2026-12-31"], "main", "1_3", "1/1", ["世帯主の未届の夫である旨"])
    law("PS1.6-ki-1-3-2", f"{PS} §1.6", "所規1の3二 世帯主でない：未届の妻", "shotoku-ki", ["2025-12-31", "2026-12-31"], "main", "1_3", "1/2", ["世帯主の未届の妻である旨"])
    law("PS1.6-ki-1-4", f"{PS} §1.6", "所規1の4 未届の夫又は未届の妻", "shotoku-ki", ["2025-12-31", "2026-12-31"], "main", "1_4", "", ["未届の夫又は未届の妻"])

    # §2.1 地法292①
    law("PS2.1-292-10", f"{PS} §2.1", "地法292①十 障害者（所法と同文）", "chiho", C_ALL, "main", "292", "1/10",
        ["障害者", "精神上の障害により事理を弁識する能力を欠く常況にある者、失明者その他の精神又は身体に障害がある者で政令で定めるものをいう。"])
    law("PS2.1-292-11", f"{PS} §2.1", "地法292①十一 寡婦（前年の合計所得金額 500万円以下、総務省令）", "chiho", C_ALL, "main", "292", "1/11",
        ["寡婦", "次に掲げる者でひとり親に該当しないものをいう。", "夫と離婚した後婚姻をしていない者のうち", "扶養親族を有すること。",
         "前年の合計所得金額が五百万円以下であること。", "総務省令で定めるものがいないこと。", "夫と死別した後婚姻をしていない者又は夫の生死の明らかでない者で政令で定めるもの"])
    law("PS2.1-292-12", f"{PS} §2.1", "地法292①十二 ひとり親（前年の合計所得金額 500万円以下、総務省令）", "chiho", C_ALL, "main", "292", "1/12",
        ["ひとり親", "その者と生計を一にする子で政令で定めるものを有すること。", "前年の合計所得金額が五百万円以下であること。", "総務省令で定めるものがいないこと。"])
    law("PS2.1-292-13", f"{PS} §2.1", "地法292①十三 合計所得金額：第313条第8項・第9項の控除前", "chiho", C_ALL, "main", "292", "1/13",
        ["合計所得金額", "第三百十三条第八項及び第九項", "総所得金額、退職所得金額及び山林所得金額の合計額"])
    law("PS2.1-314-2-6sp", f"{PS} §2.1", "地法314の2①六の括弧書きで特別障害者を定義", "chiho", C_ALL, "main", "314_2", "1/6",
        ["特別障害者（障害者のうち、精神又は身体に重度の障害がある者で政令で定めるものをいう。"])
    law("PS2.1-23-10", f"{PS} §2.1", "地法23①十 障害者（道府県民税）", "chiho", "2027-01-01", "main", "23", "1/10", ["障害者"])
    law("PS2.1-23-11", f"{PS} §2.1", "地法23①十一 寡婦（道府県民税）", "chiho", "2027-01-01", "main", "23", "1/11", ["寡婦", "前年の合計所得金額が五百万円以下"])
    law("PS2.1-23-12", f"{PS} §2.1", "地法23①十二 ひとり親（道府県民税）", "chiho", "2027-01-01", "main", "23", "1/12", ["ひとり親", "前年の合計所得金額が五百万円以下"])
    law("PS2.1-34-6sp", f"{PS} §2.1", "地法34①六 特別障害者の括弧書き（道府県民税）", "chiho", "2027-01-01", "main", "34", "1/6", ["特別障害者（障害者のうち、精神又は身体に重度の障害がある者で政令で定めるものをいう。"])
    law("PS2.1-rei7", f"{PS} §2.1", "地令7 が「法第二十三条第一項第十号」を引く", "chiho-rei", "2027-01-01", "main", "7", "", ["法第二十三条第一項第十号"])

    # §2.2 地令・地規
    law("PS2.2-rei46", f"{PS} §2.2", "地令46：法292①十の政令で定める者は第七条に規定する者", "chiho-rei", C_ALL, "main", "46", "",
        ["法第二百九十二条第一項第十号に規定する政令で定める者は、第七条に規定する者とする。"])
    law("PS2.2-rei7-7", f"{PS} §2.2", "地令7七 市町村長（特別区の区長なし）・市町村長等", "chiho-rei", C_ALL, "main", "7", "1/7",
        ["年齢六十五歳以上の者", "第一号又は第三号に掲げる者に準ずるものとして市町村長", "市町村長等", "の認定を受けている者"])
    law("PS2.2-rei48-7-2", f"{PS} §2.2", "地令48の7②：同項第六号の政令で定める障害者は第七条の十五の七", "chiho-rei", C_ALL, "main", "48_7", "2",
        ["同項第六号に規定する政令で定める障害者は第七条の十五の七に規定する者とする"])
    law("PS2.2-rei46-2", f"{PS} §2.2", "地令46の2 寡婦の範囲（法の施行地内）", "chiho-rei", C_ALL, "main", "46_2", "", ["法の施行地内", "三月以上", "一年以上", "三年以上"])
    law("PS2.2-rei46-2-2-58", f"{PS} §2.2", "地令46の2の2② 前年の…58万円以下の子（令和8年度分の版）", "chiho-rei", "2026-01-01", "main", "46_2_2", "2",
        ["当該年度の初日の属する年の前年", "第三百十三条第一項の総所得金額、退職所得金額及び山林所得金額の合計額が五十八万円以下の子（他の者の同一生計配偶者又は扶養親族とされている者を除く。）"])
    law("PS2.2-rei46-2-2-62", f"{PS} §2.2", "地令46の2の2② 62万円以下（令和9年度分・令和10年度分の版）", "chiho-rei", ["2027-01-01", "2028-01-01"], "main", "46_2_2", "2",
        ["合計額が六十二万円以下の子（他の者の同一生計配偶者又は扶養親族とされている者を除く。）"])
    law("PS2.2-rei7-2-2-58", f"{PS} §2.2", "地令7の2の2② 58万円以下（道府県民税、令和8年度分の版）", "chiho-rei", "2026-01-01", "main", "7_2_2", "2", ["五十八万円以下の子"])
    law("PS2.2-rei7-2-2-62", f"{PS} §2.2", "地令7の2の2② 62万円以下（道府県民税、令和9年度分の版）", "chiho-rei", "2027-01-01", "main", "7_2_2", "2", ["六十二万円以下の子"])
    law("PS2.2-R7S119-1-1", f"{PS} §2.2", "令和7年政令第119号 附則第1条第1号：令和八年一月一日", "chiho-rei", "2026-01-01", "suppl:" + R7_119, "1", "1/1", ["令和八年一月一日"])
    law("PS2.2-R7S119-6-1", f"{PS} §2.2", "令和7年政令第119号 附則第6条第1項：新令46の2の2② は令和8年度以後", "chiho-rei", "2026-01-01", "suppl:" + R7_119, "6", "1",
        ["新令第四十六条の二の二第二項の規定は、令和八年度以後の年度分の個人の市町村民税について適用"])
    law("PS2.2-R7S119-6cap", f"{PS} §2.2", "令和7年政令第119号 附則第6条の見出し「市町村民税に関する経過措置」", "chiho-rei", "2026-01-01", "suppl:" + R7_119, "6", "", ["市町村民税に関する経過措置"])
    law("PS2.2-R7S119-2-1", f"{PS} §2.2", "令和7年政令第119号 附則第2条第1項：新令7の2の2②（道府県民税）", "chiho-rei", "2026-01-01", "suppl:" + R7_119, "2", "1",
        ["第七条の二の二第二項の規定は、令和八年度以後の年度分の個人の道府県民税について適用"])
    law("PS2.2-R8S83-1-1", f"{PS} §2.2", "令和8年政令第83号 附則第1条第1号：令和九年一月一日", "chiho-rei", "2027-01-01", "suppl:" + R8_83, "1", "1/1", ["令和九年一月一日"])
    law("PS2.2-R8S83-5-1", f"{PS} §2.2", "令和8年政令第83号 附則第5条第1項：令和9年度以後", "chiho-rei", "2027-01-01", "suppl:" + R8_83, "5", "1",
        ["新令第四十六条の二の二第二項の規定は、令和九年度以後の年度分の個人の市町村民税について適用し、令和八年度分までの個人の市町村民税については、なお従前の例による。"])
    law("PS2.2-R8S83-5cap", f"{PS} §2.2", "令和8年政令第83号 附則第5条の見出し「市町村民税に関する経過措置」", "chiho-rei", "2027-01-01", "suppl:" + R8_83, "5", "", ["市町村民税に関する経過措置"])
    law("PS2.2-R8S83-2-1", f"{PS} §2.2", "令和8年政令第83号 附則第2条第1項：新令7の2の2② 令和9年度以後（道府県民税）", "chiho-rei", "2027-01-01", "suppl:" + R8_83, "2", "1",
        ["第七条の二の二第二項の規定は、令和九年度以後の年度分の個人の道府県民税について適用"])
    law("PS2.2-ki-1-9-7", f"{PS} §2.2", "地規1の9の7 法23①・292①、未届の夫", "chiho-ki", ["2026-01-01", "2027-01-01"], "main", "1_9_7", "",
        ["法第二十三条第一項第十一号イ", "第二百九十二条第一項第十一号イ", "未届の夫"])
    law("PS2.2-ki-1-9-8", f"{PS} §2.2", "地規1の9の8 法23①・292①、未届の夫又は未届の妻", "chiho-ki", ["2026-01-01", "2027-01-01"], "main", "1_9_8", "",
        ["法第二十三条第一項第十二号ハ", "第二百九十二条第一項第十二号ハ", "未届の夫又は未届の妻"])

    # §2.3 地法314の2・34
    for art, tax in (("314_2", "市町村民税"), ("34", "道府県民税")):
        law(f"PS2.3-{art}-1-6", f"{PS} §2.3", f"地法{art}①六 26万円（特別障害者 30万円）［{tax}］", "chiho", C_ALL, "main", art, "1/6",
            ["障害者である所得割の納税義務者又は障害者である同一生計配偶者若しくは扶養親族を有する所得割の納税義務者", "各障害者につき二十六万円（その者が特別障害者", "である場合には、三十万円）"])
        law(f"PS2.3-{art}-3", f"{PS} §2.3", f"地法{art}③ 同居特別障害者 53万円［{tax}］", "chiho", C_ALL, "main", art, "3",
            ["同居を常況としている者", "第一項第六号の金額は、", "五十三万円とする"])
        law(f"PS2.3-{art}-1-8", f"{PS} §2.3", f"地法{art}①八 寡婦 26万円［{tax}］", "chiho", C_ALL, "main", art, "1/8", ["寡婦である所得割の納税義務者", "二十六万円"])
        law(f"PS2.3-{art}-1-8-2a", f"{PS} §2.3", f"地法{art}①八の二 ひとり親 30万円（令和8年度分・令和9年度分の版）［{tax}］", "chiho", ["2026-01-01", "2027-01-01"], "main", art, "1/8_2",
            ["ひとり親である所得割の納税義務者", "三十万円"])
        law(f"PS2.3-{art}-1-8-2b", f"{PS} §2.3", f"地法{art}①八の二 ひとり親 33万円（asof 2028-01-01）［{tax}］", "chiho", "2028-01-01", "main", art, "1/8_2",
            ["ひとり親である所得割の納税義務者", "三十三万円"])
    law("PS2.3-314-2-8", f"{PS} §2.3", "地法314の2⑧ 前年の十二月三十一日の現況、子の死亡時", "chiho", C_ALL, "main", "314_2", "8",
        ["第一項、第三項又は第四項の場合において", "特別障害者若しくはその他の障害者、寡婦、ひとり親若しくは勤労学生であるかどうか", "の判定は、前年の十二月三十一日（前年の中途においてその者が死亡した場合には、その死亡の時）の現況によるものとする。",
         "ただし", "既に死亡している場合", "その死亡の時の現況による"])
    law("PS2.3-R8L2-1-6", f"{PS} §2.3", "令和8年法律第2号 附則第1条第6号：第314条の2第1項第8号の2・第34条第1項第8号の2 令和十年一月一日", "chiho", "2028-01-01", "suppl:" + R8_2, "1", "1/6",
        ["令和十年一月一日"])
    law("PS2.3-R8L2-1-6b", f"{PS} §2.3", "令和8年法律第2号 附則第1条第6号に第三百十四条の二第一項第八号の二の改正規定が入っている", "chiho", "2028-01-01", "suppl:" + R8_2, "1", "1/6",
        ["第三百十四条の二第一項第八号の二"])
    law("PS2.3-R8L2-11-3", f"{PS} §2.3", "令和8年法律第2号 附則第11条第3項：令和10年度以後", "chiho", "2028-01-01", "suppl:" + R8_2, "11", "3",
        ["新法第三百十四条の二第一項（第八号の二に係る部分に限る。）の規定は、令和十年度以後の年度分の個人の市町村民税について適用し、令和九年度分までの個人の市町村民税については、なお従前の例による。"])
    law("PS2.3-R8L2-11cap", f"{PS} §2.3", "令和8年法律第2号 附則第11条の見出し「市町村民税に関する経過措置」", "chiho", "2028-01-01", "suppl:" + R8_2, "11", "", ["市町村民税に関する経過措置"])
    law("PS2.3-R8L2-3-4", f"{PS} §2.3", "令和8年法律第2号 附則第3条第4項：新法34①（八の二）令和10年度以後（道府県民税）", "chiho", "2028-01-01", "suppl:" + R8_2, "3", "4",
        ["新法第三十四条第一項（第八号の二に係る部分に限る。）の規定は、令和十年度以後の年度分の個人の道府県民税について適用"])

    # §2.4 地法295
    law("PS2.4-295-1", f"{PS} §2.4", "地法295① 本文", "chiho", C_ALL, "main", "295", "1",
        ["市町村は、次の各号のいずれかに該当する者に対しては市町村民税（第二号に該当する者にあつては、第三百二十八条の規定により課する所得割（以下「分離課税に係る所得割」という。）を除く。）を課することができない。ただし、この法律の施行地に住所を有しない者については、この限りでない。"])
    law("PS2.4-295-1-2", f"{PS} §2.4", "地法295①二 135万円", "chiho", C_ALL, "main", "295", "1/2",
        ["障害者、未成年者、寡婦又はひとり親（これらの者の前年の合計所得金額が百三十五万円を超える場合を除く。）"])

    # §3 手帳・認定
    law("PS3-shintai-15-1", f"{PS} §3", "身障法15① 都道府県知事に申請、15歳未満は保護者", "shintai", "2026-11-09", "main", "15", "1", ["都道府県知事", "十五歳に満たないとき", "保護者"])
    law("PS3-shintai-15-4", f"{PS} §3", "身障法15④ 身体障害者手帳を交付", "shintai", "2026-11-09", "main", "15", "4", ["身体障害者手帳を交付しなければならない"])
    law("PS3-shintai-4", f"{PS} §3", "身障法4 十八歳以上・手帳の交付を受けた者", "shintai", "2026-11-09", "main", "4", "", ["別表に掲げる身体上の障害がある十八歳以上の者であつて、都道府県知事から身体障害者手帳の交付を受けたもの"])
    law("PS3-shintaiki-5-1-2", f"{PS} §3", "身障則5①二 障害名及び障害の級別", "shintai-ki", "2026-11-09", "main", "5", "1/2", ["障害名及び障害の級別"])
    law("PS3-seishin-45-2", f"{PS} §3", "精神法45② 都道府県知事が手帳を交付", "seishin", "2026-11-09", "main", "45", "2", ["都道府県知事", "精神障害者保健福祉手帳を交付しなければならない"])
    law("PS3-seishin-45-4", f"{PS} §3", "精神法45④ 二年ごとに認定", "seishin", "2026-11-09", "main", "45", "4", ["二年ごとに", "都道府県知事の認定を受けなければならない"])
    law("PS3-seishinrei-6-2", f"{PS} §3", "精神令6② 手帳に障害等級を記載", "seishin-rei", "2026-11-09", "main", "6", "2", ["障害等級"])
    law("PS3-seishinrei-6-3", f"{PS} §3", "精神令6③ 1級〜3級の状態", "seishin-rei", "2026-11-09", "main", "6", "3",
        ["一級", "日常生活の用を弁ずることを不能ならしめる程度のもの", "二級", "日常生活が著しい制限を受けるか", "三級", "日常生活若しくは社会生活が制限を受けるか"])
    law("PS3-sensho-4-4", f"{PS} §3", "戦傷法4④ 手帳に障害の程度（恩給法別表第一号表ノ二・ノ三）を記載（第4項の文言に恩給法別表があるか）", "senshobyo", "2026-11-09", "main", "4", "4", ["別表第一号表ノ二", "別表第一号表ノ三"])
    law("PS3-sensho-4-4b", f"{PS} §3", "戦傷法4④ 第一項第一号又は第二項に規定する程度の障害の有無、その障害の程度を記載", "senshobyo", "2026-11-09", "main", "4", "4", ["第一項第一号又は第二項に規定する程度の障害の有無、その障害の程度"])
    law("PS3-sensho-4-1-1", f"{PS} §3", "戦傷法4①一 恩給法別表第一号表ノ二又は別表第一号表ノ三に定める程度の障害", "senshobyo", "2026-11-09", "main", "4", "1/1", ["恩給法別表第一号表ノ二又は別表第一号表ノ三に定める程度の障害"])
    law("PS3-sensho-4-1", f"{PS} §3", "戦傷法4① 厚生労働大臣が交付", "senshobyo", "2026-11-09", "main", "4", "", ["厚生労働大臣", "戦傷病者手帳"])
    law("PS3-genbaku-11-1", f"{PS} §3", "被爆法11① 原子爆弾の傷害作用に起因する旨の厚生労働大臣の認定", "genbaku", "2026-11-09", "main", "11", "1", ["原子爆弾の傷害作用に起因する旨の厚生労働大臣の認定"])

    # §4.2 障害等級、§5 公課の禁止
    law("PS4.2-kounen-47-2", f"{PS} §4.2", "厚年法47② 障害等級 一級・二級・三級、政令で定める", "kounen", "2026-11-09", "main", "47", "2",
        ["障害等級は、障害の程度に応じて重度のものから一級、二級及び三級とし、各級の障害の状態は、政令で定める。"])
    law("PS4.2-kounenrei-3-8", f"{PS} §4.2", "厚年令3の8 1・2級は国年令別表、3級は別表第一", "kounen-rei", "2026-11-09", "main", "3_8", "",
        ["法第四十七条第二項に規定する障害等級の各級の障害の状態は、一級及び二級についてはそれぞれ国民年金法施行令別表に定める一級及び二級の障害の状態とし、三級については別表第一に定めるとおりとする。"])
    law("PS4.2-kokunen-30-2", f"{PS} §4.2", "国年法30② 障害等級 一級・二級", "kokunen", "2026-11-09", "main", "30", "2", ["一級及び二級"])
    law("PS4.2-kokunenrei-4-6", f"{PS} §4.2", "国年令4の6 障害等級の各級の障害の状態は別表", "kokunen-rei", "2026-11-09", "main", "4_6", "", ["別表"])
    law("PS5-kokunen-25", f"{PS} §5", "国年法25 公課の禁止（老齢基礎年金・付加年金を除く）", "kokunen", "2026-11-09", "main", "25", "",
        ["租税その他の公課は、給付として支給を受けた金銭を標準として、課することができない。ただし、老齢基礎年金及び付加年金については、この限りでない。"])
    law("PS5-kounen-41-2", f"{PS} §5", "厚年法41② 公課の禁止（老齢厚生年金を除く）", "kounen", "2026-11-09", "main", "41", "2",
        ["租税その他の公課は、保険給付として支給を受けた金銭を標準として、課することができない。ただし、老齢厚生年金については、この限りでない。"])

    # 仮説・推測が引く条（所属・同居老親等）
    law("H4-chiho-292-4", f"{HY} H4・{IN} I2", "地法292④ 扶養親族の所属（二以上の納税義務者）", "chiho", "2027-01-01", "main", "292", "4", ["二以上の市町村民税の納税義務者の扶養親族又は特定親族に該当する者がある場合には", "いずれか一の納税義務者の扶養親族又は特定親族にのみ該当するものとみなす"])
    law("H4-chiho-292-2", f"{HY} H4", "地法292② 同一生計配偶者等の所属", "chiho", "2027-01-01", "main", "292", "2", ["同一生計配偶者に該当し、かつ、他の市町村民税の納税義務者の扶養親族にも該当する場合には", "いずれか一にのみ該当するものとみなす"])
    law("H4-chiho-292-3", f"{HY} H4", "地法292③ 生計を一にする配偶者と他の納税義務者の特定親族", "chiho", "2027-01-01", "main", "292", "3", ["特定親族", "いずれか一にのみ該当するものとみなす"])
    law("H6-chiho-295-3", f"{HY} H6", "地法295③ 均等割の非課税は政令で定める基準に従い条例で定める", "chiho", "2027-01-01", "main", "295", "3", ["均等割", "政令で定める基準に従い", "条例で定める"])
    law("H4-chirei-46-3", f"{HY} H4", "地令46の3 見出し（所属）", "chiho-rei", "2027-01-01", "main", "46_3", "", ["所属"])
    law("H4-chirei-46-4", f"{HY} H4", "地令46の4 見出し（所属）", "chiho-rei", "2027-01-01", "main", "46_4", "", ["所属"])
    law("H4-chirei-46-5", f"{HY} H4・{IN} I2", "地令46の5 見出し（扶養親族及び特定親族の所属）", "chiho-rei", "2027-01-01", "main", "46_5", "", ["扶養親族及び特定親族の所属"])
    law("I3-sochi-41-16", f"{IN} I3", "措法41の16 同居老親等", "sochi", "2026-12-31", "main", "41_16", "", ["同居の老親等に係る扶養控除の特例", "同居を常況としている者"])
    law("I7-sochi-29-4-2", f"{IN} I7", "措法29の4② 令和八年又は令和九年、七十四万円", "sochi", "2026-12-31", "main", "29_4", "2", ["令和八年又は令和九年", "七十四万円"])

    # 給与収入 6,777,778円（［M］§5）：所法28③ の 660万円超850万円以下の区分の号番号（版で違う）
    law("M5-28-3-4@R7", f"{MS} §5", "所法28③ 660万円超850万円以下の式は令和7年分の版では第4号", "shotoku", "2025-12-31", "main", "28", "3/4",
        ["六百六十万円を超え八百五十万円以下である場合", "百七十六万円と当該収入金額から六百六十万円を控除した金額の百分の十に相当する金額との合計額"])
    law("M5-28-3-3@R7", f"{MS} §5", "（文書の記載）所法28③三 が 660万円超850万円以下の式（令和7年分の版）", "shotoku", "2025-12-31", "main", "28", "3/3",
        ["六百六十万円を超え八百五十万円以下である場合"])
    law("M5-28-3-3@R8", f"{MS} §5", "所法28③三 が 660万円超850万円以下の式（令和8年分の版）", "shotoku", "2026-12-31", "main", "28", "3/3",
        ["六百六十万円を超え八百五十万円以下である場合", "百七十六万円と当該収入金額から六百六十万円を控除した金額の百分の十に相当する金額との合計額"])

    law("M5-R8L12-1-4", f"{MS} §5（本検証の C1 の説明）", "令和8年法律第12号 附則第1条第4号（令和八年十二月一日）イに所得税法第28条第3項の改正規定", "shotoku", "2027-01-01", "suppl:" + R8_12, "1", "1/4",
        ["令和八年十二月一日", "同法第二十八条第三項の改正規定"])

    def kyuyo():
        from fractions import Fraction
        out = []
        for inc in (6_777_777, 6_777_778, 6_777_779):
            g = Fraction(inc) - (Fraction(1_760_000) + Fraction(inc - 6_600_000, 10))
            out.append((inc, str(g), g <= 5_000_000, (g.numerator // g.denominator) <= 5_000_000))
        return out
    C.append(("M5-calc", f"{MS} §5・{IN} I11", "給与所得（端数そのまま／1円未満切捨て）と 500万円以下の判定", "calc",
              (kyuyo, [(6777777, "49999993/10", True, True), (6777778, "25000001/5", False, True), (6777779, "50000011/10", False, False)])))

    def age65():
        import datetime
        # 年齢計算ニ関スル法律・民法第143条：誕生日の前日の終わりに1歳加わる → 65歳に達する日は65回目の誕生日の前日
        out = []
        for y in (2025, 2026):
            d = datetime.date(y - 65 + 1, 1, 1)   # この日以前に生まれた人は y年12月31日に65歳以上
            reached = datetime.date(d.year + 65, d.month, d.day) - datetime.timedelta(days=1)
            out.append((y, f"昭和{d.year - 1925}年{d.month}月{d.day}日", reached <= datetime.date(y, 12, 31)))
        return out
    C.append(("H10-age65", f"{HY} H10・{PS} §1.8", "65歳以上の生年月日の目安：令和7年分 昭和36年1月1日以前、令和8年分 昭和37年1月1日以前", "calc",
              (age65, [(2025, "昭和36年1月1日", True), (2026, "昭和37年1月1日", True)])))

    # 別表（§3・§4.2）
    def appdx(cid, where, what, short, asof, title_re, frags):
        C.append((cid, where, what, "appdx", (short, asof, title_re, frags)))
    appdx("PS3-shintaiki-b5", f"{PS} §3", "身障則 別表第五号：一級〜七級、備考2「肢体不自由においては、七級に該当する障害が二以上重複する場合は、六級とする。」",
          "shintai-ki", "2026-11-09", r"別表第五", ["一級", "二級", "三級", "四級", "五級", "六級", "七級", "肢体不自由においては、七級に該当する障害が二以上重複する場合は、六級とする。"])
    appdx("PS4.2-kounenrei-b1", f"{PS} §4.2", "厚年令 別表第一（第三条の八関係）は十四号（十三 精神又は神経系統…、十四 傷病が治らないで…厚生労働大臣が定めるもの）",
          "kounen-rei", "2026-11-09", r"別表第一", ["第三条の八関係", "十三", "精神又は神経系統に、労働が著しい制限を受けるか", "十四", "傷病が治らないで", "厚生労働大臣が定めるもの"])
    appdx("PS4.2-kokunenrei-b", f"{PS} §4.2", "国年令 別表：一級は一〜一一号、二級は一〜一七号", "kokunen-rei", "2026-11-09", r"別表",
          ["一級", "一〇", "一一", "二級", "一五", "一六", "一七"])
    law("PS4.2-kounen-47-1", f"{PS} §4.2", "厚年法47① 受給の要件に初診日に被保険者であったこと（障害の程度以外の要件）", "kounen", "2026-11-09", "main", "47", "1",
        ["初診日", "において被保険者であつた者が", "障害認定日", "障害等級に該当する程度の障害の状態にある場合"])

    # 特別区（［PS］§6 の6、［M］§4）：地方税法・同施行令は市町村の規定を特別区に準用し「市町村長」を「特別区長」と読み替える
    law("PS6-6-chiho-1-2", f"{PS} §6・{MS} §4", "地法1② 市町村に関する規定は特別区に準用、「市町村長」→「特別区長」", "chiho", "2027-01-01", "main", "1", "2",
        ["市町村に関する規定は特別区に準用する", "「市町村長」", "「特別区長」", "と読み替えるものとする"])
    law("PS6-6-chirei-1", f"{PS} §6・{MS} §4", "地令1 市町村に関する規定（法人の市町村民税・固定資産税等を除く）は特別区に準用、「市町村長」→「特別区長」", "chiho-rei", "2027-01-01", "main", "1", "",
        ["道府県及び市町村に関する規定の都及び特別区への準用", "市町村に関する規定（法人の市町村民税並びに固定資産税、特別土地保有税、事業所税及び都市計画税に関する規定を除く。）は特別区に準用する", "「市町村長」", "「特別区長」と読み替える"])

    # 行政の資料（HTML の本文に断片が順に現れるか）
    W = []

    def web(cid, where, what, sid, frags):
        W.append((cid, where, what, "web", (sid, frags)))

    def meta(cid, where, sid, lm, sha):
        W.append((cid, where, f"{sid} の Last-Modified {lm} / SHA-256 {sha}", "webmeta", (sid, lm, sha)))

    web("TA1160-base", f"{PS} §1.8", "No.1160 ［令和8年4月1日現在法令等］", "ta_1160", ["令和8年4月1日現在法令等"])
    web("TA1160-amt", f"{PS} §1.8", "No.1160 27万・40万・75万", "ta_1160", ["27万円", "40万円", "75万円"])
    web("TA1160-16", f"{PS} §1.2・§1.8", "No.1160 16歳未満の扶養親族も対象（原文の文）", "ta_1160", ["障害者控除は、扶養控除の適用がない16歳未満の扶養親族を有する場合においても適用されます。"])
    web("TA1160-6m", f"{PS} §1.8", "No.1160 (8) 6か月以上（引き続き6か月以上）", "ta_1160", ["6か月以上"])
    web("TA1160-fukushi", f"{PS} §1.8", "No.1160 市町村長等や福祉事務所長の認定", "ta_1160", ["市町村長等や福祉事務所長の認定"])
    web("TA1160QA-Q1", f"{PS} §1.8", "No.1160 Q&A：7級、65歳以上で市町村長等の認定", "ta_1160_qa", ["7級", "65歳以上", "認定"])
    web("TA1160QA-Q2", f"{PS} §1.8", "No.1160 Q&A：療育手帳、A（マルA、A2）、愛護手帳・愛の手帳・みどりの手帳", "ta_1160_qa",
        ["療育手帳", "児童相談所または知的障害者更生相談所", "都道府県知事", "重度", "A", "B", "特別障害者", "マルA", "A2", "愛護手帳", "愛の手帳", "みどりの手帳"])
    web("TA1160QA-Q3", f"{PS} §1.8", "No.1160 Q&A：国外に住む16歳未満、医師の診断書", "ta_1160_qa", ["国外", "16歳未満", "診断書"])
    web("TA1185", f"{PS} §1.8", "No.1185 要介護認定を受けられただけでは障害者控除の対象とはなりません", "ta_1185", ["介護保険法の要介護認定を受けられただけでは障害者控除の対象とはなりません"])
    web("TA1186", f"{PS} §1.8", "No.1186 申請中・診断書・明らかに", "ta_1186", ["申請中", "診断書", "明らかに"])
    web("TA1184", f"{PS} §1.8", "No.1184 寝たきり・特別障害者・扶養控除も", "ta_1184", ["特別障害者", "扶養控除"])
    web("TA1170-r2", f"{PS} §1.8", "No.1170 令和2年分以後 27万円、民法上の婚姻", "ta_1170", ["27万円", "民法"])
    web("TA1170QA", f"{PS} §1.8", "No.1170 Q&A：妹・青色事業専従者・寡婦に当たらない", "ta_1170_qa", ["妹", "事業専従者"])
    web("TA1171-35", f"{PS} §1.8", "No.1171 35万円、58万円、令和8年12月1日施行・62万円", "ta_1171", ["35万円", "58万円", "62万円"])
    web("TA1171-r8", f"{PS} §1.8", "No.1171 注に令和8年12月1日（施行）", "ta_1171", ["令和8年12月1日"])
    web("TA1171QA-Q1", f"{PS} §1.8", "No.1171 Q&A：事業専従者である子", "ta_1171_qa", ["事業専従者"])
    web("TA1171QA-Q2", f"{PS} §1.8", "No.1171 Q&A：年齢の制限はない／16歳未満", "ta_1171_qa", ["16歳未満"])
    web("SG05-31", f"{PS} §1.8", "質疑応答 05/31：2-38 は遡及を認める趣旨ではない、令和7年8月1日現在", "shitsugi_05_31", ["2-38", "過去に遡及して適用を認める趣旨ではない", "令和7年8月1日現在"])
    web("SG05-63", f"{PS} §1.8", "質疑応答 05/63：申請中なら適用して差し支えない、所令10①七・所基通2-38", "shitsugi_05_63", ["申請", "差し支えありません"])
    web("SG05-32", f"{PS} §1.8・{HY} H4", "質疑応答 05/32：入院は同居、老人ホーム等への入所は同居に当たらない、措法41の16", "shitsugi_05_32", ["入院", "老人ホーム"])
    web("SG05-32-law", f"{PS} §1.8", "質疑応答 05/32 の関係法令に措法41の16", "shitsugi_05_32", ["41条の16"])
    web("SGgensen03-10", f"{PS} §1.8", "質疑応答（源泉）03/10：死亡時と12月31日で判定、双方適用", "shitsugi_gensen_03_10", ["ひとり親控除", "配偶者控除", "12月31日"])
    web("KIHON-2-38", f"{PS} §1.7", "所基通2-38：申請中・診断書・明らかに・令第10条第1項第3号又は第4号", "kihon_01_07",
        ["2-38", "身体障害者手帳の交付を受けていない者又は戦傷病者手帳の交付を受けていない者", "令第10条第1項第3号又は第4号", "申告書", "提出する時において", "申請中", "診断書", "その年12月31日", "明らかに"])
    web("KIHON-2-39", f"{PS} §1.7", "所基通2-39：引き続き6月以上", "kihon_01_07", ["2-39", "引き続き6月以上"])
    web("KIHON-2-40", f"{PS} §1.7", "所基通2-40：法第85条第6項…に限る", "kihon_01_07", ["2-40", "法第85条第6項", "に限る"])
    web("KIHON-2-41", f"{PS} §1.7", "所基通2-41：非課税所得", "kihon_01_07", ["2-41", "非課税所得"])
    web("KIHON-2-42", f"{PS} §1.7", "所基通2-42：危難、令第11条第3号又は第4号", "kihon_01_07", ["2-42", "令第11条第3号又は第4号", "危難"])
    web("KIHON-79-1", f"{PS} §1.7", "所基通79-1：他の居住者が障害者控除を受けるようなことはできない", "kihon_16_06", ["79-1", "控除対象配偶者", "控除対象扶養親族", "一の居住者が配偶者控除又は扶養控除の規定の適用を受け、他の居住者が障害者控除の規定の適用を受けるようなことはできない"])
    web("KIHON-79-2", f"{PS} §1.7", "所基通79-2：相続人等", "kihon_16_06", ["79-2", "相続人"])
    web("KIHON-80-1", f"{PS} §1.7", "所基通80-1：死別・配偶者控除・寡婦控除", "kihon_16_06", ["80-1", "寡婦控除"])
    web("KIHON-81-1", f"{PS} §1.7", "所基通81-1：ひとり親控除", "kihon_16_06", ["81-1", "ひとり親控除"])
    web("KIHON-85-2", f"{IN} I2", "所基通85-2：所属を変更しようとする場合は全員が申告書等を提出", "kihon_16_06", ["85-2", "所属を変更しようとする場合", "全員"])
    web("MHLW-H14", f"{PS} §1.9", "平成14年8月1日 事務連絡「老齢者の所得税、地方税上の障害者控除の取扱いについて」", "mhlw_kaigo_020904_2_3",
        ["平成14年8月1日", "老齢者の所得税、地方税上の障害者控除の取扱いについて"])
    web("MHLW-H14-ryokai", f"{PS} §1.9", "国税庁、総務省当局の了解済み", "mhlw_kaigo_020904_2_3", ["国税庁", "総務省", "了解済み"])
    web("MHLW-H14-fukusu", f"{PS} §1.9", "認定書は複数年使用される", "mhlw_kaigo_020904_2_3", ["複数年使用"])
    web("MHLW-H14-hantei", f"{PS} §1.9", "要介護認定と障害認定は判断基準が異なる", "mhlw_kaigo_020904_2_3", ["判断基準が異なる"])
    web("MHLW-H14-amt", f"{PS} §1.9", "所得税27万円、住民税26万円／所得税40万円、住民税30万円", "mhlw_kaigo_020904_2_3", ["27万円", "26万円", "40万円", "30万円"])
    web("MHLW-S52", f"{PS} §4.1", "昭和52年通知：保発第9号・庁保発第9号、130万円未満、概ね障害厚生年金…180万円未満", "mhlw_tdoc_S52",
        ["保発第九号", "庁保発第九号", "一三〇万円未満", "概ね厚生年金保険法による障害厚生年金の受給要件に該当する程度の障害者", "一八〇万円未満"])
    web("MHLW-S52-date", f"{PS} §4.1", "昭和52年4月6日", "mhlw_tdoc_S52", ["昭和五二年四月六日"])
    web("MHLW-R7-0704", f"{PS} §4.1", "19歳以上23歳未満の被扶養者に係る認定：年管発0704第1号・保発0704第1号、障害者の括弧書き（180万円未満）", "mhlw_tdoc_R7_0704",
        ["19歳以上23歳未満の被扶養者に係る認定について", "180万円未満"])
    web("MHLW-R7-1001", f"{PS} §4.1", "労働契約内容による年間収入…（注2）180万円", "mhlw_tdoc_R7_1001",
        ["労働契約内容による年間収入が基準額未満である場合の被扶養者の認定における年間収入の取扱いについて", "60歳以上", "概ね厚生年金保険法による障害厚生年金の受給要件に該当する程度の障害者", "180万円"])
    web("KYOKAI-FAQ", f"{PS} §4.3", "協会けんぽ FAQ：おおむね…障害厚生年金の受給要件に該当する程度の障害者…180万円未満", "kyokai_faq",
        ["おおむね厚生年金保険法による障害厚生年金の受給要件に該当する程度の障害者", "180万円未満"])

    web("NENKIN-180", f"{PS} §4.3", "日本年金機構：年間収入130万円未満（60歳以上または障害者の場合は180万円未満）、障害年金等は受取金額のわかる通知書等のコピー", "nenkin_hifuyo",
        ["130万円未満", "60歳以上または障害者の場合は、年間収入180万円未満", "障害年金", "受取金額のわかる通知書等のコピー"])
    # Last-Modified と SHA-256（文書が書いた値）
    for sid, lm, sha in [
        ("ta_1160", "2026-09-09", "b921678a"), ("ta_1160_qa", "2026-09-09", "acdf4f8d"), ("ta_1170", "2026-09-09", "d3791953"),
        ("ta_1170_qa", "2026-09-09", "5f8032e2"), ("ta_1171", "2026-09-09", "e1391148"), ("ta_1171_qa", "2026-09-09", "b1ddfc32"),
        ("ta_1184", "2026-09-09", "201e3a99"), ("ta_1185", "2026-09-09", "1f89395a"), ("ta_1186", "2026-09-09", "a3f916bc"),
        ("shitsugi_05_31", "2025-12-03", "36071298"), ("shitsugi_05_32", "2025-12-03", "2965b255"), ("shitsugi_05_63", "2025-12-03", "bfb70916"),
        ("shitsugi_gensen_03_10", "2025-12-03", "1b9e9f68"), ("kihon_01_07", "2026-10-02", "52d60882"), ("kihon_16_06", "2025-11-25", "73c6009e"),
        ("nencho2025_105", "2025-09-03", "f69eda75"), ("nencho2026_105", "2026-09-24", "9460af44"), ("gensen_2026kaisei", "2026-04-20", "8db585cd"),
        ("mhlw_kaigo_020904_2_3", "2018-06-02", "4908b9f7"), ("cao_r07_12mhlw_140", "2026-05-27", "adda2dc2"),
        ("kyokai_fuyouidou_guide2607", "2026-06-23", "c655715c"), ("soumu_tsuchi", None, "107ba94c"),
        ("mhlw_tdoc_S52", None, "3a0aec4d"), ("mhlw_tdoc_R7_0704", None, "49a921c3"), ("mhlw_tdoc_R7_1001", None, "8cf28bc4"),
        ("kyokai_faq", None, "87da9750"),
    ]:
        meta(f"META-{sid}", f"{PS} §1.7〜§4.3・{MS} §6", sid, lm, sha)
    return C + W


# ---------------------------------------------------------------- 照合
def load_manifest(name):
    p = OUT / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


class Store:
    def __init__(self):
        self.em = load_manifest("egov_manifest.json")
        self.wm = load_manifest("web_manifest.json")
        self.wms = [self.wm] + [json.loads(x.read_text(encoding="utf-8")) for x in sorted(OUT.glob("web_manifest_extra_*.json"))]
        self.cache = {}

    def law(self, short, asof):
        k = (short, asof)
        if k not in self.cache:
            p = ROOT / self.em["download_dir"] / f"{short}_{asof}.json"
            self.cache[k] = Law(p) if p.exists() else None
        return self.cache[k]

    def rev(self, short, asof):
        for f in self.em["fetches"]:
            if f["short"] == short and f["asof"] == asof:
                return f
        return None

    def _web(self, sid):
        for m in self.wms:
            for r in (m or {}).get("results", []):
                if r["id"] == sid:
                    return m, r
        return None, None

    def web(self, sid):
        return self._web(sid)[1]

    def webtext(self, sid):
        m, r = self._web(sid)
        if not r or not r.get("text"):
            return None
        return (ROOT / m["text_dir"] / r["text"]).read_text(encoding="utf-8")


def run_one(st, c):
    cid, where, what, kind, args = c
    res = {"id": cid, "where": where, "what": what, "kind": kind}
    if kind == "rev":
        short, asof, rid, status = args
        f = st.rev(short, asof)
        if not f:
            res.update(result="確認できない", detail="取得なし")
        else:
            ok = f.get("law_revision_id") == rid and f.get("current_revision_status") == status and f.get("title_ok")
            res.update(result="一致" if ok else "不一致",
                       detail=f"取得：{f.get('law_revision_id')} {f.get('current_revision_status')} 施行日 {f.get('amendment_enforcement_date')} 改正 {f.get('amendment_law_num')} 題名一致 {f.get('title_ok')}")
    elif kind == "law":
        short, asof, part, art, path, frags = args
        lw = st.law(short, asof)
        if lw is None:
            res.update(result="確認できない", detail="取得なし")
            return res
        if part == "main":
            node = lw.main.get(art)
            src = f"本則 第{art}条"
        else:
            sups = lw.suppl_of(part.split(":", 1)[1])
            node = None
            for s in sups:
                for a in kids(s, "Article"):
                    if a["attr"].get("Num") == art:
                        node = a
                        break
                if node:
                    break
            src = f"改正附則 {[s['attr'].get('AmendLawNum') for s in sups]} 第{art}条"
        if node is None:
            res.update(result="不一致", detail=f"{src} が見つからない")
            return res
        sub = locate(node, path)
        if sub is None:
            res.update(result="不一致", detail=f"{src} の {path} が見つからない")
            return res
        txt = text_of(sub)
        ok, miss = has_all(txt, frags)
        res.update(result="一致" if ok else "不一致", detail=f"{src} {path}" + ("" if ok else f"：『{miss}』がない"),
                   excerpt=norm(txt)[:300])
    elif kind == "appdx":
        short, asof, title_re, frags = args
        lw = st.law(short, asof)
        hit = [t for t in (lw.appdx if lw else []) if t.get("tag") == "AppdxTable" and re.match(title_re, norm(text_of(t))[:40])]
        if not hit:
            res.update(result="不一致" if lw else "確認できない", detail=f"別表 {title_re} が見つからない")
            return res
        txt = text_of(hit[0])
        ok, miss = has_all(txt, frags)
        res.update(result="一致" if ok else "不一致", detail=f"別表 {title_re}" + ("" if ok else f"：『{miss}』がない"))
    elif kind == "calc":
        fn, expect = args
        got = fn()
        res.update(result="一致" if got == expect else "不一致", detail=f"計算 {got}／文書 {expect}")
    elif kind == "web":
        sid, frags = args
        t = st.webtext(sid)
        if t is None:
            res.update(result="確認できない", detail="取得なし／HTML でない")
            return res
        ok, miss = has_all(t, frags)
        res.update(result="一致" if ok else "不一致", detail="" if ok else f"『{miss}』がない（順序を含む）")
    elif kind == "webmeta":
        sid, lm, sha = args
        r = st.web(sid)
        if not r or r.get("status") != 200:
            res.update(result="確認できない", detail=f"取得 {r and r.get('status')}")
            return res
        got_lm = r.get("last_modified")
        got_sha = r.get("sha256", "")
        lm_ok = True
        if lm:
            try:
                tt = time.strptime(got_lm, "%a, %d %b %Y %H:%M:%S GMT")
                lm_ok = time.strftime("%Y-%m-%d", tt) == lm
            except Exception:  # noqa: BLE001
                lm_ok = False
        sha_ok = got_sha.startswith(sha) if sha else True
        res.update(result="一致" if (lm_ok and sha_ok) else ("一致（Last-Modified のみ）" if lm_ok and lm else "不一致"),
                   detail=f"取得：Last-Modified {got_lm}、SHA-256 {got_sha[:16]}")
    return res


# 版の間の差分（担当の diff とは別に、条・項・号の単位で比べる）
DIFF_TARGETS = {
    "shotoku": (S_ALL, ["2", "79", "80", "81", "85"], {"2": ["28", "29", "30", "31", "33", "34"]}),
    "shotoku-rei": (S_ALL, ["10", "11", "11_2"], {}),
    "shotoku-ki": (["2025-12-31", "2026-12-31"], ["1_3", "1_4"], {}),
    "chiho": (C_ALL, ["292", "295", "314_2", "34"], {}),
    "chiho-rei": (C_ALL, ["7", "7_15_7", "7_2_2", "46", "46_2", "46_2_2", "48_7"], {}),
    "chiho-ki": (["2026-01-01", "2027-01-01"], ["1_9_7", "1_9_8"], {}),
}


def units(art, only_items=None):
    """条を項・号の単位に分けて、(場所, 本文) の一覧にする。"""
    out = []
    for p in kids(art, "Paragraph"):
        pn = p["attr"].get("Num")
        items = kids(p, "Item")
        head = "".join(text_of(c) for c in kids(p) if c.get("tag") != "Item")
        out.append((f"{pn}項（柱書）", norm(head)))
        for it in items:
            inum = it["attr"].get("Num")
            if only_items and pn == "1" and inum not in only_items:
                continue
            out.append((f"{pn}項{inum}号", norm(text_of(it))))
    return out


def diffs(st):
    md = ["# 版の間で変わった項・号（R2X_jinteki_verify の独立したテキスト化）", ""]
    js = {}
    for short, (asofs, arts, only) in DIFF_TARGETS.items():
        for a, b in zip(asofs, asofs[1:]):
            la, lb = st.law(short, a), st.law(short, b)
            if not la or not lb:
                continue
            changed = []
            for art in arts:
                na, nb = la.main.get(art), lb.main.get(art)
                if na is None or nb is None:
                    changed.append({"where": f"第{art}条", "a": None if na is None else "あり", "b": None if nb is None else "あり"})
                    continue
                ua, ub = dict(units(na, only.get(art))), dict(units(nb, only.get(art)))
                for k in sorted(set(ua) | set(ub), key=lambda x: (len(x), x)):
                    if ua.get(k) != ub.get(k):
                        x, y = ua.get(k) or "", ub.get(k) or ""
                        sm = difflib.SequenceMatcher(None, x, y)
                        ops = [(x[i1:i2], y[j1:j2]) for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal"]
                        changed.append({"where": f"第{art}条{k}", "changes": ops[:8]})
            js[f"{short} {a}→{b}"] = changed
            md += [f"## {short} {a} → {b}", ""]
            if not changed:
                md.append("- 変更なし（対象の条）")
            for c in changed:
                if "changes" in c:
                    md.append(f"- {c['where']}：" + "；".join(f"「{x}」→「{y}」" for x, y in c["changes"]))
                else:
                    md.append(f"- {c['where']}：版による有無 {c['a']} / {c['b']}")
            md.append("")
    return md, js



# 所得税と住民税の政令・省令の文言の違い（担当の正規化とは別に、正規化をせずに号ごとの違いをすべて出す）
WORDING = [
    ("障害者の範囲 所令10① vs 地令7", ("shotoku-rei", "2026-12-31", "10", "1"), ("chiho-rei", "2027-01-01", "7", "1")),
    ("特別障害者の範囲 所令10② vs 地令7の15の7", ("shotoku-rei", "2026-12-31", "10", "2"), ("chiho-rei", "2027-01-01", "7_15_7", "1")),
    ("寡婦の範囲 所令11 vs 地令46の2", ("shotoku-rei", "2026-12-31", "11", "1"), ("chiho-rei", "2027-01-01", "46_2", "1")),
    ("寡婦の事実婚 所規1の3 vs 地規1の9の7", ("shotoku-ki", "2026-12-31", "1_3", "1"), ("chiho-ki", "2027-01-01", "1_9_7", "1")),
    ("ひとり親の事実婚 所規1の4 vs 地規1の9の8", ("shotoku-ki", "2026-12-31", "1_4", "1"), ("chiho-ki", "2027-01-01", "1_9_8", "1")),
]


def wording(st):
    md = ["", "# 所得税と住民税の政令・省令の文言の違い（正規化なし。号ごとの文字列の違いをすべて出す）", ""]
    js = {}
    for name, a, b in WORDING:
        pa = locate(st.law(*a[:2]).main.get(a[2]), a[3])
        pb = locate(st.law(*b[:2]).main.get(b[2]), b[3])
        ia, ib = kids(pa, "Item"), kids(pb, "Item")
        md += [f"## {name}（号の数 {len(ia)} / {len(ib)}）", ""]
        rows = []
        for k in range(max(len(ia), len(ib))):
            x = norm(text_of(ia[k])) if k < len(ia) else ""
            y = norm(text_of(ib[k])) if k < len(ib) else ""
            sm = difflib.SequenceMatcher(None, x, y, autojunk=False)
            ops = [(x[i1:i2], y[j1:j2]) for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal"]
            rows.append({"item": k + 1, "ops": ops})
            md.append(f"- 第{k + 1}号：" + ("同じ" if not ops else "；".join(f"「{u}」→「{v}」" for u, v in ops)))
        js[name] = rows
        md.append("")
    return md, js

def cmd_check():
    st = Store()
    rows = [run_one(st, c) for c in claims()]
    md_d, js_d = diffs(st)
    md_w, js_w = wording(st)
    (OUT / "diffs.md").write_text("\n".join(md_d + md_w) + "\n", encoding="utf-8")
    cnt = {}
    for r in rows:
        cnt[r["result"]] = cnt.get(r["result"], 0) + 1
    (OUT / "checks.json").write_text(json.dumps({"counts": cnt, "rows": rows, "diffs": js_d, "wording": js_w}, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# R2X_jinteki_verify の照合の結果", "",
          f"- 条文：`{st.em['download_dir']}`（取得 {st.em['run_at']}）", f"- 行政の資料：`{(st.wm or {}).get('download_dir')}`（取得 {(st.wm or {}).get('run_at')}）",
          f"- 件数：{cnt}", "", "| ID | 文書・節 | 主張 | 結果 | 詳細 |", "|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['id']} | {r['where']} | {r['what']} | {r['result']} | {r.get('detail', '').replace('|', '/')} |")
    (OUT / "checks.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(cnt)
    for r in rows:
        if r["result"] not in ("一致",):
            print(r["id"], r["result"], r.get("detail"), "\n   ", r.get("excerpt", "")[:200])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    a = sys.argv[1:]
    if not a:
        print(__doc__)
    elif a[0] == "egov":
        cmd_egov()
    elif a[0] == "web":
        cmd_web(a[1:])
    elif a[0] == "check":
        cmd_check()

"""R2X_spouse の独立した検証（反証役）。

別の担当が書いた次の文書の数値・条番号・通達/通知の番号と日付・施行日・適用年分・URL を、一次情報に当たり直して確かめる。
  docs/public-sources/20261109_round2_spouse-laws-and-sources.md     （以下 PS）
  docs/measurements/20261109_round2_spouse-fetch-and-tables.md       （以下 M）
  docs/hypotheses/20261109_round2_spouse-model.md                    （以下 H）
  docs/inferences/20261109_round2_spouse-implications.md             （以下 I）
担当のスクリプト（R2X_spouse_egov.py・R2X_spouse_fetch.py・R2X_spouse_tables.py）は import も実行もしない。
e-Gov 法令API v2 と行政のサイトから取り直し、自分で書いたテキスト化・照合・計算で確かめる。
担当の出力は「担当の記録と取り直した結果が同じか」を比べる用途（cmp_author）にだけ読む。

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_spouse_verify.py egov    # 条文の取得（ネットワーク）
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_spouse_verify.py web     # 行政の資料の取得（ネットワーク）
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_spouse_verify.py check   # 照合と再計算（ネットワークなし）

- e-Gov 法令API v2 の使い方は scripts/R1_egov_articles.py・scripts/IMPL_kyuyo_fetch.py を読んで写した（import しない）。標準ライブラリのみ。
- ダウンロードは取得ごとに新しい空のディレクトリ .work/downloads/<YYYYMMDD-HHMMSS>_R2X_spouse_verify_<egov|web>/ に置く
  （信頼できないデータ。その中で何も実行しない）。HTML から取り出したテキストは .work/text/<ts>_R2X_spouse_verify_web/ に置く。
  PDF はテキスト化しない（Read ツールのページ指定で読み、結果は文書に書く）。
- 出力は scripts/results/R2X_spouse_verify/：
  egov_manifest.json（取得した版）、web_manifest.json（URL・HTTP・Last-Modified・SHA-256）、
  checks.json・checks.md（項目ごとの照合の結果）、calc.json・calc.md（控除額の再計算と国税庁・市の表との照合）、
  author_cmp.json・author_cmp.md（担当の取得記録の SHA-256・版と、取り直した結果の比較）
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。個人の情報は送らない。官報は取得しない。
"""
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
OUT = ROOT / "scripts" / "results" / "R2X_spouse_verify"

# (略称, law_id, 期待する法令名, [(asof, 改正附則を含めるか)...])
LAWS = [
    ("shotoku", "340AC0000000033", "所得税法", [("2024-12-31", False), ("2025-12-31", False), ("2026-12-31", True)]),
    ("shotoku-rei", "340CO0000000096", "所得税法施行令", [("2024-12-31", False), ("2025-12-31", False), ("2026-12-31", False)]),
    # 2025-01-01 は令和7年度分の賦課期日の版（PS が「令和7年度分（比較用）」とした 2025-12-31 の版と比べるため）
    ("chiho", "325AC0000000226", "地方税法", [("2025-01-01", False), ("2025-12-31", False), ("2026-01-01", False), ("2027-01-01", True)]),
    ("chiho-rei", "325CO0000000245", "地方税法施行令", [("2025-12-31", False), ("2026-01-01", False), ("2027-01-01", False)]),
    ("kokunen", "334AC0000000141", "国民年金法", [("2026-11-09", False)]),
    ("kokunen-rei", "334CO0000000184", "国民年金法施行令", [("2026-11-09", False)]),
    ("kokunen-ki", "335M50000100012", "国民年金法施行規則", [("2026-11-09", False)]),
    ("kenpo", "211AC0000000070", "健康保険法", [("2026-11-09", False)]),
    # 検証で足した法令：国民年金法附則第3条が引く厚生年金保険法附則第4条の3、推測の文書の例が使う措置法（給与所得控除 74万円・基礎控除の加算）
    ("kounen", "329AC0000000115", "厚生年金保険法", [("2026-11-09", False)]),
    ("sochi", "332AC0000000026", "租税特別措置法", [("2026-12-31", False)]),
]

WEB = {
    # 国税庁
    "ta1191": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1191.htm",
    "ta1191_qa": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1191_qa.htm",
    "ta1195": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1195.htm",
    "ta1190": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1190.htm",
    "ta2672": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/gensen/2672.htm",
    "sg_0310": "https://www.nta.go.jp/law/shitsugi/gensen/03/10.htm",
    "sg_0311": "https://www.nta.go.jp/law/shitsugi/gensen/03/11.htm",
    "kihon_01_07": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/01/07.htm",
    "kihon_16_06": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/16/06.htm",
    "nencho2026_106": "https://www.nta.go.jp/publication/pamph/gensen/nencho2026/pdf/106.pdf",
    "nencho2025_106": "https://www.nta.go.jp/publication/pamph/gensen/nencho2025/pdf/106.pdf",
    "form2026bun_06": "https://www.nta.go.jp/taxes/tetsuzuki/shinsei/annai/gensen/pdf/2026bun_06.pdf",
    "form2025bun_06": "https://www.nta.go.jp/taxes/tetsuzuki/shinsei/annai/gensen/pdf/2025bun_06.pdf",
    "kiso2026_qa": "https://www.nta.go.jp/users/gensen/2026kiso/pdf/0026005-024.pdf",
    # 厚生労働省（法令等データベース・検討会）
    "mhlw_S61": "https://www.mhlw.go.jp/web/t_doc?dataId=00tb1690&dataType=1&pageNo=1",
    "mhlw_S52": "https://www.mhlw.go.jp/web/t_doc?dataId=00tb0189&dataType=1&pageNo=1",
    "mhlw_srch_S610331": "https://www.mhlw.go.jp/web/t_itemsrch_result?type=1&startGengo=3&yearFrom=61&monthFrom=3&dayFrom=31"
                         "&endGengo=3&yearTo=61&monthTo=3&dayTo=31&shubetsu=&bango=",
    "mhlw_srch_H050305": "https://www.mhlw.go.jp/web/t_itemsrch_result?type=1&startGengo=4&yearFrom=5&monthFrom=3&dayFrom=5"
                         "&endGengo=4&yearTo=5&monthTo=3&dayTo=5&shubetsu=&bango=",
    "mhlw_srch_H0503_p0": "https://www.mhlw.go.jp/web/t_itemsrch_result?type=1&startGengo=4&yearFrom=5&monthFrom=3&dayFrom=1"
                          "&endGengo=4&yearTo=5&monthTo=3&dayTo=31&shubetsu=&bango=",
    "mhlw_srch_H0503_p1": "https://www.mhlw.go.jp/web/t_itemsrch_result?type=1&startGengo=4&yearFrom=5&monthFrom=3&dayFrom=1"
                          "&endGengo=4&yearTo=5&monthTo=3&dayTo=31&shubetsu=&bango=&page=1",
    "mhlw_srch_H0503_p2": "https://www.mhlw.go.jp/web/t_itemsrch_result?type=1&startGengo=4&yearFrom=5&monthFrom=3&dayFrom=1"
                          "&endGengo=4&yearTo=5&monthTo=3&dayTo=31&shubetsu=&bango=&page=2",
    "mhlw_kentokai": "https://www.mhlw.go.jp/stf/newpage_75888.html",
    "mhlw_gijiroku": "https://www.mhlw.go.jp/stf/newpage_76904.html",
    "mhlw_kt2_pdf": "https://www.mhlw.go.jp/content/12500000/001746546.pdf",
    # 日本年金機構
    "nenkin_yougo": "https://www.nenkin.go.jp/service/yougo/tagyo/dai3hihokensha.html",
    "nenkin_faq": "https://www.nenkin.go.jp/section/faq/kokunen/seido/kanyu/seidosetsumei/20140602-01.html",
    "nenkin_kanyu": "https://www.nenkin.go.jp/service/kokunen/kanyu/20140710-04.html",
    "nenkin_tet": "https://www.nenkin.go.jp/service/kounen/tekiyo/hihokensha1/20141202.html",
    "nenkin_kyoju": "https://www.nenkin.go.jp/service/kounen/tekiyo/hihokensha1/kyojuyoken.html",
    "nenkin_kenshu_pdf": "https://www.nenkin.go.jp/service/riyoushabetsu/cooperator/kenshu.files/01.pdf",
    # 市の案内（照合用の二次的な資料）
    "utsunomiya": "https://www.city.utsunomiya.lg.jp/kurashi/zeikin/shinzei/1003621.html",
    # M §4 の表にあるが PS で引用していない資料（取得記録の再現だけを確かめる）
    "ta1180_qa": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1180_qa.htm",
    "p1648_73": "https://www.nta.go.jp/taxes/tetsuzuki/shinsei/annai/gensen/annai/1648_73.htm",
    "shinkokusyo_index": "https://www.nta.go.jp/users/gensen/nencho/shinkokusyo/index.htm",
    "nenkin_kyoju_20200324": "https://www.nenkin.go.jp/oshirase/taisetu/2020/202003/20200324.html",
    "chuo": "https://www.city.chuo.lg.jp/a0009/kurashi/zeikin/juuminzei/shotokukoujo/haigusya.html",
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
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_spouse_verify_egov"
    dl.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    man = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "fetches": [], "errors": []}
    for short, law_id, title, asofs in LAWS:
        for asof, with_amend in asofs:
            q = {"response_format": "json", "asof": asof}
            if not with_amend:
                q["omit_amendment_suppl_provision"] = "true"
            url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode(q)
            try:
                st, _, _, body = http_get(url, accept="application/json")
                fn = dl / f"{short}_{asof}.json"
                fn.write_bytes(body)
                rec = {"short": short, "law_id": law_id, "asof": asof, "with_amendment_suppl": with_amend, "url": url,
                       "status": st, "file": fn.name, "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
                if st == 200:
                    d = json.loads(body)
                    ri = d.get("revision_info") or {}
                    li = d.get("law_info") or {}
                    rec.update({"law_title": ri.get("law_title"), "title_ok": ri.get("law_title") == title,
                                "law_num": li.get("law_num"), "law_revision_id": ri.get("law_revision_id"),
                                "amendment_law_title": ri.get("amendment_law_title"),
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
    BREAK = {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "dt", "dd", "table", "caption"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self._skip, self.title, self._in_title = [], 0, "", False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag in self.BREAK:
            self.parts.append("\n")
        if tag in ("td", "th"):
            self.parts.append(" ¦ ")

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


def cmd_web():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_spouse_verify_web"
    dl.mkdir(parents=True, exist_ok=False)
    tx = ROOT / ".work" / "text" / f"{ts}_R2X_spouse_verify_web"
    tx.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    man = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"),
           "text_dir": str(tx.relative_to(ROOT)).replace("\\", "/"), "results": []}
    for i, (sid, url) in enumerate(WEB.items()):
        if i:
            time.sleep(SLEEP)
        rec = {"id": sid, "url": url}
        try:
            st, final, hdr, body = http_get(url, timeout=90)
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
                rec.update({"title": " ".join(p.title.split()), "text": f"{sid}.txt",
                            "text_sha256": hashlib.sha256(t.encode("utf-8")).hexdigest()})
        except Exception as e:  # noqa: BLE001
            rec["error"] = repr(e)
        man["results"].append(rec)
        print(rec["id"], rec.get("status"), rec.get("last_modified"), (rec.get("sha256") or "")[:16], rec.get("error", ""), flush=True)
    (OUT / "web_manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")


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
        self.main, self.suppl = {}, []

        def fn(n, anc):
            t = n.get("tag")
            in_suppl = any(a.get("tag") == "SupplProvision" for a in anc)
            if t == "Article" and not in_suppl:
                self.main.setdefault(n["attr"].get("Num"), n)
            elif t == "SupplProvision":
                self.suppl.append(n)
        walk(self.root, fn)

    def suppl_article(self, amend_re, num):
        """AmendLawNum が amend_re に合う改正附則の中の第 num 条。"""
        for s in self.suppl:
            an = s.get("attr", {}).get("AmendLawNum", "") or ""
            if re.search(amend_re, an):
                for a in [x for x in self._articles(s)]:
                    if a["attr"].get("Num") == num:
                        return a
        return None

    def suppl_has(self, amend_re):
        return [s.get("attr", {}).get("AmendLawNum") for s in self.suppl if re.search(amend_re, s.get("attr", {}).get("AmendLawNum", "") or "")]

    @staticmethod
    def _articles(s):
        out = []
        walk(s, lambda n, anc: out.append(n) if n.get("tag") == "Article" else None)
        return out


def units_of(article):
    """条の見出しと、項・号・細分ごとの本文（子の項・号を含めない）を1単位ずつ返す（行の数え方を担当の走査に合わせるため）。"""
    out = ["".join(text_of(c) for c in kids(article, "ArticleCaption"))]

    def rec(n):
        for c in kids(n):
            t = c.get("tag", "")
            if t in ("Paragraph", "Item") or t.startswith("Subitem"):
                out.append("".join(text_of(x) for x in kids(c) if x.get("tag", "").endswith("Sentence")))
                rec(c)
            elif t == "TableRow":
                out.append(text_of(c))
            else:
                rec(c)
    rec(article)
    return out


def locate(node, path):
    """path：'1/33_2'（第1項第33号の2）、'1/10_2/1/1'（第1項第10号の2 イ（１））、'8'（第8項）。
    段は Paragraph(Num) → Item(Num) → Subitem1(Num) → Subitem2(Num)。"""
    cur = node
    if not path:
        return cur
    levels = ["Paragraph", "Item", "Subitem1", "Subitem2", "Subitem3"]
    for lvl, st in zip(levels, path.split("/")):
        found = None
        for c in kids(cur, lvl):
            if c.get("attr", {}).get("Num") == st:
                found = c
                break
        if found is None:
            return None
        cur = found
    return cur


def norm(s):
    """空白を除き、全角英数字を半角にし（NFKC）、ダッシュ類をそろえる。"""
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub("[−－‐‑―ー](?=\\d)", "-", s)
    return re.sub(r"[\s¦|]", "", s)


def has_all(text, frags):
    """frags がこの順に text に現れるか。現れなかった最初の断片を返す。"""
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
# 種類：
#   "rev"  (略称, asof, 期待する law_revision_id, 期待する状態, 期待する改正法令番号(漢数字) or None, 期待する施行日 or None)
#   "law"  (略称, asof, 'main' | 'suppl:<AmendLawNum の正規表現>', 条番号, 項/号の path, [断片...])
#   "lawnot" 同上。断片が「現れない」ことを確かめる
#   "same" (略称, [asof...], 条番号, path)  … 版の間で文字列が同じ
#   "differ" (略称, asof1, asof2, 条番号, path) … 版の間で文字列が違う
#   "web"  (資料ID, [断片...])
#   "webnot" (資料ID, [断片...]) … 断片が現れない
#   "lm"   (資料ID, 'YYYY-MM-DD') … HTTP の Last-Modified の日付（GMT を JST に直さず、ヘッダの日付そのもの）
PS, MS, HY, IN = "PS", "M", "H", "I"
R6, R7, R8 = "2024-12-31", "2025-12-31", "2026-12-31"
C7, C8, C9 = "2025-12-31", "2026-01-01", "2027-01-01"
NOW = "2026-11-09"
A13 = "suppl:令和七年.*法律第一三号|suppl:令和七年.*法律第十三号"
A12 = "suppl:令和八年.*法律第一二号|suppl:令和八年.*法律第十二号"
L7 = "suppl:令和七年.*法律第七号"
L2 = "suppl:令和八年.*法律第二号"

CHECKS = [
    # ---------------- 版（PS §0.1、M §1）
    ("V01", PS + " §0.1 / " + MS + " §1", "所法@R6 の版", "rev", ("shotoku", R6, "340AC0000000033_20240612_506AC0000000047", "PreviousEnforced", "令和六年法律第四十七号", "2024-06-12")),
    ("V02", PS + " §0.1 / " + MS + " §1", "所法@R7 の版（最後の改正：令和7年法律第13号、2025-12-18）", "rev", ("shotoku", R7, "340AC0000000033_20251218_507AC0000000013", "PreviousEnforced", "令和七年法律第十三号", "2025-12-18")),
    ("V03", PS + " §0.1 / " + MS + " §1", "所法@R8 の版（令和8年法律第12号、2026-12-01、未施行）", "rev", ("shotoku", R8, "340AC0000000033_20261201_508AC0000000012", "UnEnforced", "令和八年法律第十二号", "2026-12-01")),
    ("V04", PS + " §0.1 / " + MS + " §1", "所令@R7 の版", "rev", ("shotoku-rei", R7, "340CO0000000096_20251201_507CO0000000120", "PreviousEnforced", "令和七年政令第百二十号", "2025-12-01")),
    ("V05", PS + " §0.1 / " + MS + " §1", "所令@R8 の版", "rev", ("shotoku-rei", R8, "340CO0000000096_20261201_508CO0000000093", "UnEnforced", "令和八年政令第九十三号", "2026-12-01")),
    ("V06", PS + " §0.1 / " + MS + " §1", "地法@R7度（比較用 2025-12-31）の版", "rev", ("chiho", C7, "325AC0000000226_20251212_507AC0000000087", "PreviousEnforced", "令和七年法律第八十七号", "2025-12-12")),
    ("V07", PS + " §0.1 / " + MS + " §1", "地法@R8度 の版", "rev", ("chiho", C8, "325AC0000000226_20260101_507AC0000000041", "PreviousEnforced", "令和七年法律第四十一号", "2026-01-01")),
    ("V08", PS + " §0.1 / " + MS + " §1", "地法@R9度 の版（未施行）", "rev", ("chiho", C9, "325AC0000000226_20270101_508AC0000000002", "UnEnforced", "令和八年法律第二号", "2027-01-01")),
    ("V09", PS + " §0.1 / " + MS + " §1", "地令@R8度 の版", "rev", ("chiho-rei", C8, "325CO0000000245_20260101_507CO0000000119", "PreviousEnforced", "令和七年政令第百十九号", "2026-01-01")),
    ("V10", PS + " §0.1 / " + MS + " §1", "地令@R9度 の版", "rev", ("chiho-rei", C9, "325CO0000000245_20270101_508CO0000000083", "UnEnforced", "令和八年政令第八十三号", "2027-01-01")),
    ("V11", PS + " §0.1 / " + MS + " §1", "国年法 の版", "rev", ("kokunen", NOW, "334AC0000000141_20261001_507AC0000000074", "CurrentEnforced", "令和七年法律第七十四号", "2026-10-01")),
    ("V12", PS + " §0.1 / " + MS + " §1", "国年令 の版", "rev", ("kokunen-rei", NOW, "334CO0000000184_20261001_508CO0000000226", "CurrentEnforced", "令和八年政令第二百二十六号", "2026-10-01")),
    ("V13", PS + " §0.1 / " + MS + " §1", "国年則 の版", "rev", ("kokunen-ki", NOW, "335M50000100012_20261001_508M60000100121", "CurrentEnforced", "令和八年厚生労働省令第百二十一号", "2026-10-01")),
    ("V14", PS + " §0.1 / " + MS + " §1", "健保法 の版", "rev", ("kenpo", NOW, "211AC0000000070_20261001_507AC0000000087", "CurrentEnforced", "令和七年法律第八十七号", "2026-10-01")),

    # ---------------- 所得税法の定義（PS §1.1、M §2.1）
    ("L01", PS + " §1.1", "第2条第1項第33号（令和8年分）62万円以下・青色事業専従者等", "law", ("shotoku", R8, "main", "2", "1/33", ["三十三", "同一生計配偶者", "居住者の配偶者でその居住者と生計を一にするもの（第五十七条第一項（事業に専従する親族がある場合の必要経費の特例等）に規定する青色事業専従者に該当するもので同項に規定する給与の支払を受けるもの及び同条第三項に規定する事業専従者に該当するもの（第三十三号の四において「青色事業専従者等」という。）を除く。）のうち、合計所得金額が六十二万円以下である者をいう。"])),
    ("L02", PS + " §1.1 表", "第33号 令和7年分 58万円以下", "law", ("shotoku", R7, "main", "2", "1/33", ["合計所得金額が五十八万円以下である者をいう"])),
    ("L03", PS + " §1.1 表", "第33号 令和6年分 48万円以下", "law", ("shotoku", R6, "main", "2", "1/33", ["合計所得金額が四十八万円以下である者をいう"])),
    ("L04", PS + " §1.1", "第33号の2 控除対象配偶者（本人1,000万円以下）", "law", ("shotoku", R8, "main", "2", "1/33_2", ["控除対象配偶者", "同一生計配偶者のうち、合計所得金額が千万円以下である居住者の配偶者をいう。"])),
    ("L05", PS + " §1.1", "第33号の3 老人控除対象配偶者（70歳以上）", "law", ("shotoku", R8, "main", "2", "1/33_3", ["老人控除対象配偶者", "控除対象配偶者のうち、年齢七十歳以上の者をいう。"])),
    ("L06", PS + " §1.1", "第33号の4 源泉控除対象配偶者（本人900万円以下・配偶者95万円以下）", "law", ("shotoku", R8, "main", "2", "1/33_4", ["源泉控除対象配偶者", "居住者（合計所得金額が九百万円以下であるものに限る。）の配偶者でその居住者と生計を一にするもの（青色事業専従者等を除く。）のうち、合計所得金額が九十五万円以下である者をいう。"])),
    ("L07", PS + " §1.1 / " + MS + " §2.1", "第33号の2〜第33号の4 は3つの版で同文", "same", ("shotoku", [R6, R7, R8], "2", "1/33_2")),
    ("L08", PS + " §1.1 / " + MS + " §2.1", "第33号の3 は3つの版で同文", "same", ("shotoku", [R6, R7, R8], "2", "1/33_3")),
    ("L09", PS + " §1.1 / " + MS + " §2.1", "第33号の4 は3つの版で同文", "same", ("shotoku", [R6, R7, R8], "2", "1/33_4")),
    # 第83条（PS §1.2）
    ("L10", PS + " §1.2", "第83条第1項 柱書と第1号〜第3号の額", "law", ("shotoku", R8, "main", "83", "1", ["居住者が控除対象配偶者を有する場合には、その居住者のその年分の総所得金額、退職所得金額又は山林所得金額から次の各号に掲げる場合の区分に応じ当該各号に定める金額を控除する。",
        "その居住者の第二条第一項第三十号（定義）に規定する合計所得金額（以下この項、次条第一項、第八十四条の二第一項（特定親族特別控除）及び第八十六条第一項（基礎控除）において「合計所得金額」という。）が九百万円以下である場合", "三十八万円（その控除対象配偶者が老人控除対象配偶者である場合には、四十八万円）",
        "その居住者の合計所得金額が九百万円を超え九百五十万円以下である場合", "二十六万円（その控除対象配偶者が老人控除対象配偶者である場合には、三十二万円）",
        "その居住者の合計所得金額が九百五十万円を超え千万円以下である場合", "十三万円（その控除対象配偶者が老人控除対象配偶者である場合には、十六万円）"])),
    ("L11", PS + " §1.2 / " + MS + " §2.1", "第83条 は R7 と R8 で同文", "same", ("shotoku", [R7, R8], "83", "")),
    ("L12", PS + " §1.2 / " + MS + " §2.1", "第83条第1項第1号は R6 と R7 で違う（列挙に第84条の2 が加わった）", "differ", ("shotoku", R6, R7, "83", "1/1")),
    ("L13", PS + " §1.2", "所法@R6 の第83条第1項第1号には第84条の2 の列挙がない・金額は同じ", "law", ("shotoku", R6, "main", "83", "1/1", ["九百万円以下である場合", "三十八万円（その控除対象配偶者が老人控除対象配偶者である場合には、四十八万円）"])),
    ("L13b", PS + " §1.2", "所法@R6 の第83条第1項第1号に「第八十四条の二」が無い", "lawnot", ("shotoku", R6, "main", "83", "1/1", ["第八十四条の二"])),
    # 第83条の2（PS §1.3）
    ("L14", PS + " §1.3", "第83条の2第1項 柱書（133万円以下・控除対象配偶者に該当しない・本人1,000万円以下）", "law", ("shotoku", R8, "main", "83_2", "1", ["居住者が生計を一にする配偶者（第二条第一項第三十三号（定義）に規定する青色事業専従者等を除くものとし、合計所得金額が百三十三万円以下であるものに限る。）で控除対象配偶者に該当しないもの（合計所得金額が千万円以下である当該居住者の配偶者に限る。）を有する場合には、その居住者のその年分の総所得金額、退職所得金額又は山林所得金額から次の各号に掲げる場合の区分に応じ当該各号に定める金額を控除する。"])),
    ("L15", PS + " §1.3", "第83条の2第1項第1号 イ〜ハ", "law", ("shotoku", R8, "main", "83_2", "1/1", ["その居住者の合計所得金額が九百万円以下である場合", "合計所得金額が九十五万円以下である配偶者", "三十八万円",
        "合計所得金額が九十五万円を超え百三十万円以下である配偶者", "三十八万円からその配偶者の合計所得金額のうち九十三万一円を超える部分の金額（当該超える部分の金額が五万円の整数倍の金額から三万円を控除した金額でないときは、五万円の整数倍の金額から三万円を控除した金額で当該超える部分の金額に満たないもののうち最も多い金額とする。）を控除した金額",
        "合計所得金額が百三十万円を超える配偶者", "三万円"])),
    ("L16", PS + " §1.3", "第83条の2第1項第2号 3分の2・1万円未満切上げ", "law", ("shotoku", R8, "main", "83_2", "1/2", ["その居住者の合計所得金額が九百万円を超え九百五十万円以下である場合", "三分の二に相当する金額（当該金額に一万円未満の端数がある場合には、これを切り上げた金額）"])),
    ("L17", PS + " §1.3", "第83条の2第1項第3号 3分の1・1万円未満切上げ", "law", ("shotoku", R8, "main", "83_2", "1/3", ["その居住者の合計所得金額が九百五十万円を超え千万円以下である場合", "三分の一に相当する金額（当該金額に一万円未満の端数がある場合には、これを切り上げた金額）"])),
    ("L18", PS + " §1.3 / " + MS + " §2.1", "第83条の2 は3つの版で同文", "same", ("shotoku", [R6, R7, R8], "83_2", "")),
    # 第83条の2第2項（PS §1.4）
    ("L19", PS + " §1.4", "第83条の2第2項第1号・第2号（185①一・二、186①一・②一、年末調整・確定申告・決定の除外）", "law", ("shotoku", R8, "main", "83_2", "2", ["前項の規定は、同項に規定する生計を一にする配偶者が、次に掲げる場合に該当するときは、適用しない。",
        "当該配偶者が前項に規定する居住者として同項の規定の適用を受けている場合",
        "給与所得者の扶養控除等申告書又は従たる給与についての扶養控除等申告書に記載された源泉控除対象配偶者がある居住者として第百八十五条第一項第一号若しくは第二号", "又は第百八十六条第一項第一号若しくは第二項第一号",
        "第百九十条（年末調整）の規定の適用を受けた者である場合又は確定申告書の提出をし、若しくは決定を受けた者である場合を除く。",
        "公的年金等の受給者の扶養親族等申告書"])),
    ("L20", PS + " §1.4 / §6-3", "第83条（配偶者控除）に相手方の適用による除外の文言がない（「適用を受けている」が第83条に現れない）", "lawnot", ("shotoku", R8, "main", "83", "", ["適用を受けている"])),
    # 第85条（PS §2.1）
    ("L21", PS + " §2.1", "第85条第3項 12月31日の現況・死亡の時", "law", ("shotoku", R8, "main", "85", "3", ["第七十九条から前条までの場合において、その者が居住者の老人控除対象配偶者若しくはその他の控除対象配偶者若しくはその他の同一生計配偶者若しくは第八十三条の二第一項（配偶者特別控除）に規定する生計を一にする配偶者又は", "特定親族", "に該当するかどうかの判定は、その年十二月三十一日の現況による。ただし、その判定に係る者がその当時既に死亡している場合は、当該死亡の時の現況による。"])),
    ("L22", PS + " §2.1", "第85条第7項 死亡と再婚の特例は政令", "law", ("shotoku", R8, "main", "85", "7", ["年の中途において居住者の配偶者が死亡し、その年中にその居住者が再婚した場合におけるその死亡し、又は再婚した配偶者に係る同一生計配偶者及び第八十三条の二第一項に規定する生計を一にする配偶者並びに扶養親族及び特定親族の範囲の特例については、政令で定める。"])),
    ("L23", PS + " §2.1", "所法@R6 では第6項で、特定親族の文言がない", "law", ("shotoku", R6, "main", "85", "6", ["年の中途において居住者の配偶者が死亡し、その年中にその居住者が再婚した場合", "生計を一にする配偶者並びに扶養親族の範囲の特例については、政令で定める。"])),
    ("L23b", PS + " §2.1", "所法@R6 第85条に「特定親族」がない", "lawnot", ("shotoku", R6, "main", "85", "", ["特定親族"])),
    ("L24", PS + " §2.1 / " + MS + " §2.1", "第85条 は R7 と R8 で同文", "same", ("shotoku", [R7, R8], "85", "")),
    ("L25", MS + " §2.1", "第85条は R6 と R7 で違う（第5項の新設など）", "differ", ("shotoku", R6, R7, "85", "")),
    ("L25b", MS + " §2.1", "R7 の第85条第5項は「生計を一にする配偶者」と「特定親族」", "law", ("shotoku", R7, "main", "85", "5", ["生計を一にする配偶者", "特定親族"])),
    # 第195条の2（PS §1.7、M §2.1）
    ("L26", PS + " §1.7", "第195条の2第1項（第190条の年末調整、最後に給与等の支払を受ける日の前日まで、支払者経由、本人の合計所得金額の見積額、配偶者の氏名・個人番号（有しない者は氏名）・合計所得金額又は見積額・老人／非居住者の旨）", "law", ("shotoku", R8, "main", "195_2", "1", ["第百九十条（年末調整）", "その年最後に給与等の支払を受ける日の前日までに", "当該給与等の支払者を経由して", "合計所得金額", "の見積額", "控除対象配偶者又は第八十三条の二第一項（配偶者特別控除）に規定する生計を一にする配偶者の氏名及び個人番号（個人番号を有しない者にあつては、氏名）並びにその者のその年の合計所得金額又はその見積額並びにその者が老人控除対象配偶者又は非居住者である場合にはその旨"])),
    ("L26c", PS + " §1.7", "第195条の2第3項（名称「給与所得者の配偶者控除等申告書」）", "law", ("shotoku", R8, "main", "195_2", "3", ["給与所得者の配偶者控除等申告書という"])),
    ("L27", PS + " §1.7", "第195条の2第2項 非居住者である配偶者：配偶者であること・生計を一にすることの書類の提出又は提示", "law", ("shotoku", R8, "main", "195_2", "2", ["非居住者である旨の記載をした居住者", "配偶者に該当する旨を証する書類", "生計を一にすることを明らかにする書類を提出し、又は提示しなければならない"])),
    ("L28", MS + " §2.1", "第195条の2 は R6 と R7 で違い、R7 と R8 で同じ", "differ", ("shotoku", R6, R7, "195_2", "")),
    ("L29", MS + " §2.1", "第195条の2 は R7 と R8 で同文", "same", ("shotoku", [R7, R8], "195_2", "")),
    # 附則（PS §1.5、M §2.3）
    ("L30", PS + " §1.5 / " + MS + " §2.3", "令和7年法律第13号 附則第1条第1号（イ）：第2条第1項第33号・第83条第1項第1号・第85条の改正規定は令和7年12月1日", "law", ("shotoku", R8, A13, "1", "1/1", ["令和七年十二月一日", "第二条第一項第三十二号の改正規定、同項第三十三号の改正規定", "第八十三条第一項第一号の改正規定", "第八十五条の改正規定"])),
    ("L31", PS + " §1.5", "同 附則第2条第1項（第32号・第33号・第34号は令和7年分以後）の原文", "law", ("shotoku", R8, A13, "2", "1", ["第一条の規定による改正後の所得税法（以下「新所得税法」という。）第二条第一項（第三十二号、第三十三号及び第三十四号に係る部分に限る。）の規定は、令和七年分以後の所得税について適用し、令和六年分以前の所得税については、なお従前の例による。"])),
    ("L31n", PS + " §1.5", "PS の引用「新所得税法第二条第一項（…」は原文の連続した文字列ではない（原文は「第一条の規定による改正後の所得税法（以下「新所得税法」という。）第二条第一項」）", "lawnot", ("shotoku", R8, A13, "2", "1", ["新所得税法第二条第一項（第三十二号"])),
    ("L32", PS + " §1.5", "同 附則第2条第2項（5年以内の更正の請求）", "law", ("shotoku", R8, A13, "2", "2", ["五年以内"])),
    ("L33", PS + " §1.5", "同 附則第6条第3項（第85条は令和7年分以後）", "law", ("shotoku", R8, A13, "6", "3", ["新所得税法第八十五条の規定は、令和七年分以後の所得税について適用し、令和六年分以前の所得税については、なお従前の例による。"])),
    ("L34", PS + " §1.5 / " + MS + " §2.3", "令和8年法律第12号 附則第1条第4号（イ）：第2条第1項第33号の改正規定は令和8年12月1日", "law", ("shotoku", R8, A12, "1", "1/4", ["令和八年十二月一日", "第二条第一項第三十二号の改正規定（同号ロに係る部分を除く。）、同項第三十三号及び第三十四号の改正規定"])),
    ("L35", PS + " §1.5", "同 附則第2条第1項の原文（「第三十二号（ロに係る部分を除く。）」）", "law", ("shotoku", R8, A12, "2", "1", ["第一条の規定による改正後の所得税法（以下「新所得税法」という。）第二条第一項（第三十二号（ロに係る部分を除く。）、第三十三号及び第三十四号に係る部分に限る。）の規定は、令和八年分以後の所得税について適用し、令和七年分以前の所得税については、なお従前の例による。"])),
    ("L35n", PS + " §1.5", "PS の引用「第三十二号（ロを除く。）」は原文にない", "lawnot", ("shotoku", R8, A12, "2", "1", ["第三十二号（ロを除く。）"])),
    # 所令（PS §2.1）
    ("L36", PS + " §2.1", "所令第220条第1項 死亡又は再婚した配偶者のうち一人", "law", ("shotoku-rei", R8, "main", "220", "1", ["死亡した配偶者又は再婚した配偶者のうち一人に限る"])),
    ("L37", PS + " §2.1", "所令第218条・第218条の2・第220条は R7 と R8 で同文", "same", ("shotoku-rei", [R7, R8], "220", "")),
    ("L38", PS + " §2.1", "所令第218条 R7・R8 同文", "same", ("shotoku-rei", [R7, R8], "218", "")),
    ("L39", PS + " §2.1", "所令第218条の2 R7・R8 同文", "same", ("shotoku-rei", [R7, R8], "218_2", "")),

    # ---------------- 地方税法（PS §2.2・§3、M §2.2）
    ("C01", PS + " §3.1", "第292条第1項第7号（令和9年度分）62万円以下・前年", "law", ("chiho", C9, "main", "292", "1/7", ["同一生計配偶者", "市町村民税の納税義務者の配偶者でその納税義務者と生計を一にするもの（第三百十三条第三項に規定する青色事業専従者に該当するもので同項に規定する給与の支払を受けるもの及び同条第四項に規定する事業専従者に該当するものを除く。）のうち、当該年度の初日の属する年の前年", "の合計所得金額が六十二万円以下である者をいう。"])),
    ("C02", PS + " §3.1", "第292条第1項第7号（令和8年度分）58万円以下", "law", ("chiho", C8, "main", "292", "1/7", ["合計所得金額が五十八万円以下である者をいう"])),
    ("C03", PS + " §3.1", "第292条第1項第7号（2025-12-31 の版）48万円以下", "law", ("chiho", C7, "main", "292", "1/7", ["合計所得金額が四十八万円以下である者をいう"])),
    ("C04", PS + " §3.1", "第292条第1項第8号 控除対象配偶者（本人の前年の合計所得金額1,000万円以下）", "law", ("chiho", C9, "main", "292", "1/8", ["控除対象配偶者", "同一生計配偶者のうち、前年の合計所得金額が千万円以下である市町村民税の納税義務者の配偶者をいう。"])),
    ("C05", PS + " §3.2", "第314条の2第1項第10号（33万・22万・11万、老人38万・26万・13万）", "law", ("chiho", C9, "main", "314_2", "1/10", ["控除対象配偶者を有する所得割の納税義務者", "当該納税義務者の前年の合計所得金額が九百万円以下である場合", "三十三万円（その控除対象配偶者が老人控除対象配偶者（控除対象配偶者のうち、年齢七十歳以上の者をいう。以下この条及び第三百十四条の六第一号イにおいて同じ。）である場合には、三十八万円）",
        "九百万円を超え九百五十万円以下である場合", "二十二万円", "二十六万円", "九百五十万円を超え千万円以下である場合", "十一万円", "十三万円"])),
    ("C06", PS + " §3.2", "第314条の2第1項第10号の2 柱書（R9度：前号又はこの号）", "law", ("chiho", C9, "main", "314_2", "1/10_2", ["自己と生計を一にする配偶者（第三百十三条第三項に規定する青色事業専従者に該当するもので同項に規定する給与の支払を受けるもの及び同条第四項に規定する事業専従者に該当するものを除き、前年の合計所得金額が百三十三万円以下であるものに限る。）で控除対象配偶者に該当しないものを有する所得割の納税義務者（その配偶者が前号又はこの号に規定する所得割の納税義務者としてこれらの規定の適用を受けているものを除き、前年の合計所得金額が千万円以下であるものに限る。）"])),
    ("C07", PS + " §3.2", "第10号の2 イ（１）100万円以下 33万円、（２）93万1円・5万円・3万円、（３）130万円超 3万円", "law", ("chiho", C9, "main", "314_2", "1/10_2/1", ["当該納税義務者の前年の合計所得金額が九百万円以下である場合", "前年の合計所得金額が百万円以下である配偶者", "三十三万円",
        "前年の合計所得金額が百万円を超え百三十万円以下である配偶者", "三十八万円から当該配偶者の前年の合計所得金額のうち九十三万一円を超える部分の金額（当該超える部分の金額が五万円の整数倍の金額から三万円を控除した金額でないときは、五万円の整数倍の金額から三万円を控除した金額で当該超える部分の金額に満たないもののうち最も多い金額とする。）を控除した金額",
        "前年の合計所得金額が百三十万円を超える配偶者", "三万円"])),
    ("C08", PS + " §3.2", "第10号の2 ロ 3分の2・ハ 3分の1、1万円未満切上げ", "law", ("chiho", C9, "main", "314_2", "1/10_2", ["九百万円を超え九百五十万円以下である場合", "三分の二に相当する金額（当該金額に一万円未満の端数がある場合には、これを切り上げた金額）", "九百五十万円を超え千万円以下である場合", "三分の一に相当する金額（当該金額に一万円未満の端数がある場合には、これを切り上げた金額）"])),
    ("C09", PS + " §3.2 / " + MS + " §2.2", "R7度（2025-12-31）の第10号の2 括弧書き「この号に…この号の規定」", "law", ("chiho", C7, "main", "314_2", "1/10_2", ["その配偶者がこの号に規定する所得割の納税義務者としてこの号の規定の適用を受けているものを除き"])),
    ("C10", PS + " §3.2 / " + MS + " §2.2", "R8度（2026-01-01）の第10号の2 括弧書き「前号又はこの号…これらの規定」", "law", ("chiho", C8, "main", "314_2", "1/10_2", ["その配偶者が前号又はこの号に規定する所得割の納税義務者としてこれらの規定の適用を受けているものを除き"])),
    ("C11", PS + " §3.2 / " + MS + " §2.2", "第34条第1項第10号の2（道府県民税）R7度は「この号」", "law", ("chiho", C7, "main", "34", "1/10_2", ["その配偶者がこの号に規定する所得割の納税義務者としてこの号の規定の適用を受けているものを除き"])),
    ("C12", PS + " §3.2 / " + MS + " §2.2", "第34条第1項第10号の2（道府県民税）R8度は「前号又はこの号」", "law", ("chiho", C8, "main", "34", "1/10_2", ["その配偶者が前号又はこの号に規定する所得割の納税義務者としてこれらの規定の適用を受けているものを除き"])),
    ("C13", PS + " §3.2 / " + MS + " §2.2", "第314条の2第1項第10号 の文言は3つの版で同じ", "same", ("chiho", [C7, C8, C9], "314_2", "1/10")),
    ("C14", MS + " §2.2", "第10号の2 は R8度と R9度で同じ", "same", ("chiho", [C8, C9], "314_2", "1/10_2")),
    ("C15", PS + " §3.3 / " + MS + " §2.2", "第314条の6 は3つの版で差分なし", "same", ("chiho", [C7, C8, C9], "314_6", "")),
    ("C16", PS + " §3.3", "第314条の6 調整控除（2,500万円以下、3/100・指定都市4/100、200万円、5万円）", "law", ("chiho", C9, "main", "314_6", "", ["前年の合計所得金額が二千五百万円以下である", "二百万円以下である", "いずれか少ない金額の百分の三（当該納税義務者が指定都市の区域内に住所を有する場合には、百分の四）", "二百万円を超える", "五万円"])),
    ("C17", PS + " §3.3", "第314条の6 表（６）控除対象配偶者 5万円（4万円・2万円）、老人 10万円（6万円・3万円）", "law", ("chiho", C9, "main", "314_6", "", ["控除対象配偶者を有する所得割の納税義務者", "五万円", "四万円", "二万円", "老人控除対象配偶者", "十万円", "六万円", "三万円"])),
    ("C18", PS + " §3.3", "第314条の6 表（７）55万円未満の配偶者、5万円、50万円以上55万円未満 3万円", "law", ("chiho", C9, "main", "314_6", "", ["第三百十四条の二第一項第十号の二に規定する配偶者（前年の合計所得金額が五十五万円未満である者に限る。）で控除対象配偶者に該当しないものを有する所得割の納税義務者（当該配偶者が同号に規定する所得割の納税義務者として同号の規定の適用を受けているものを除き、前年の合計所得金額が千万円以下であるものに限る。）",
        "五万円", "五十万円以上五十五万円未満", "三万円"])),
    ("C19", PS + " §3.3", "第37条（道府県民税の調整控除）率 2/100（指定都市 1/100）", "law", ("chiho", C9, "main", "37", "", ["百分の二（当該納税義務者が指定都市の区域内に住所を有する場合には、百分の一）"])),
    ("C20", PS + " §2.2", "第314条の2第8項：前年の12月31日（前年の中途で死亡はその時）の現況", "law", ("chiho", C9, "main", "314_2", "8", ["同一生計配偶者", "老人控除対象配偶者", "第一項第十号の二に規定する生計を一にする配偶者", "特定扶養親族", "前年の十二月三十一日（前年の中途においてその者が死亡した場合には、その死亡の時）の現況によるものとする。"])),
    ("C21", PS + " §2.2 / " + MS + " §2.2", "第8項：2025-12-31 の版には「若しくは特定親族」がなく、2026-01-01 の版にある", "law", ("chiho", C8, "main", "314_2", "8", ["若しくは特定親族"])),
    ("C21b", PS + " §2.2", "2025-12-31 の版の第8項に「特定親族」がない", "lawnot", ("chiho", C7, "main", "314_2", "8", ["特定親族"])),
    ("C22", PS + " §2.2", "第8項は R8度と R9度で同文", "same", ("chiho", [C8, C9], "314_2", "8")),
    ("C23", PS + " §2.2", "第314条の2第10項 死亡・再婚の特例は政令", "law", ("chiho", C9, "main", "314_2", "10", ["前年の中途において所得割の納税義務者の配偶者が死亡し、前年中にその納税義務者が再婚した場合におけるその死亡し、又は再婚した配偶者に係る同一生計配偶者及び第一項第十号の二に規定する生計を一にする配偶者並びに扶養親族及び特定親族の範囲の特例については、政令で定める。"])),
    ("C24", PS + " §3.4 / " + MS + " §2.3", "令和7年法律第7号 附則第1条第1号：第292条第1項第7号・第9号、第34条、第314条の2 などは令和8年1月1日", "law", ("chiho", C9, L7, "1", "1/1", ["同法第三十四条", "第二百九十二条第一項第七号及び第九号の改正規定", "同法第三百十四条の二", "令和八年一月一日"])),
    ("C25", PS + " §3.4", "同 附則第8条第1項：令和8年度以後", "law", ("chiho", C9, L7, "8", "1", ["新法第二百九十二条第一項（第七号及び第九号に係る部分に限る。）、第三項及び第四項、第三百十四条の二並びに第三百十七条の二第一項", "の規定は、令和八年度以後の年度分の個人の市町村民税について適用し、令和七年度分までの個人の市町村民税については、なお従前の例による。"])),
    ("C26", PS + " §3.4 / " + MS + " §2.3", "令和8年法律第2号 附則第1条第2号：第292条第1項第6号・第7号・第9号は令和9年1月1日", "law", ("chiho", C9, L2, "1", "1/2", ["第二百九十二条第一項第六号、第七号及び第九号", "令和九年一月一日"])),
    ("C27", PS + " §3.4", "同 附則第11条第2項：第292条第1項（第7号・第9号）は令和9年度以後", "law", ("chiho", C9, L2, "11", "2", ["新法第二百九十二条第一項（第七号及び第九号に係る部分に限る。）の規定は、令和九年度以後の年度分の個人の市町村民税について適用し、令和八年度分までの個人の市町村民税については、なお従前の例による。"])),
    # 地方税法施行令（PS §2.2）
    ("C28", PS + " §2.2", "地令第7条の16（見出しと本文）", "law", ("chiho-rei", C9, "main", "7_16", "", ["所得割の納税義務者が再婚した場合における同一生計配偶者等の特例", "法第三十四条第十項の場合において、同項の納税義務者の同一生計配偶者又は同条第一項第十号の二に規定する生計を一にする配偶者に該当する者は、その死亡した配偶者又は再婚した配偶者のうち一人に限るものとする。"])),
    ("C29", PS + " §2.2", "地令第48条の7第5項（第7条の16 の準用）", "law", ("chiho-rei", C9, "main", "48_7", "5", ["第七条の十六の規定は、法第三百十四条の二第十項の場合における同項の死亡し、又は再婚した配偶者に係る同一生計配偶者又は同条第一項第十号の二に規定する生計を一にする配偶者の範囲について準用する。"])),
    ("C30", PS + " §2.2", "地令第46条の3 は R8度・R9度で同文", "same", ("chiho-rei", [C8, C9], "46_3", "")),
    ("C31", PS + " §2.2", "地令第46条の4 は R8度・R9度で同文", "same", ("chiho-rei", [C8, C9], "46_4", "")),
    ("C32", MS + " §2.2", "地令第7条の16 は R8度・R9度で同文", "same", ("chiho-rei", [C8, C9], "7_16", "")),

    # ---------------- 国民年金法・健康保険法（PS §2.3・§4・§5.1）
    ("K01", PS + " §5.1", "国年法第5条第7項（配偶者に事実婚を含む）", "law", ("kokunen", NOW, "main", "5", "7", ["この法律において、「配偶者」、「夫」及び「妻」には、婚姻の届出をしていないが、事実上婚姻関係と同様の事情にある者を含むものとする。"])),
    ("K02", PS + " §5.1", "国年法第7条第1項第3号（被扶養配偶者、20歳以上60歳未満、国内居住）", "law", ("kokunen", NOW, "main", "7", "1/3", ["第二号被保険者の配偶者", "日本国内に住所を有する者又は", "厚生労働省令で定める者に限る", "主として第二号被保険者の収入により生計を維持するもの", "被扶養配偶者", "二十歳以上六十歳未満"])),
    ("K03", PS + " §5.1", "国年法第7条第1項第2号は厚生年金保険の被保険者", "law", ("kokunen", NOW, "main", "7", "1/2", ["厚生年金保険の被保険者"])),
    ("K04", PS + " §5.1", "国年法第7条第2項（認定は政令）・第3項（行政手続法第3章（第12条・第14条を除く）不適用）", "law", ("kokunen", NOW, "main", "7", "3", ["前項の認定については、行政手続法（平成五年法律第八十八号）第三章（第十二条及び第十四条を除く。）の規定は、適用しない。"])),
    ("K04b", PS + " §5.1", "国年法第7条第2項（生計維持の認定は政令）", "law", ("kokunen", NOW, "main", "7", "2", ["政令で定める"])),
    ("K05", PS + " §2.3", "国年法第8条第5号「被扶養配偶者となつたとき」", "law", ("kokunen", NOW, "main", "8", "", ["被扶養配偶者となつたとき"])),
    ("K05b", IN + " IS9", "国年法第8条第1号「二十歳に達したとき」", "law", ("kokunen", NOW, "main", "8", "1/1", ["二十歳に達したとき"])),
    ("K05c", PS + " §2.3", "国年法第8条第5号の位置", "law", ("kokunen", NOW, "main", "8", "1/5", ["被扶養配偶者となつたとき"])),
    ("K06", PS + " §2.3", "国年法第9条 柱書（翌日、括弧書きでその日）", "law", ("kokunen", NOW, "main", "9", "", ["次の各号のいずれかに該当するに至つた日の翌日（第二号に該当するに至つた日に更に第七条第一項第二号若しくは第三号に該当するに至つたとき又は第三号から第五号までのいずれかに該当するに至つたとき（第四号については、厚生年金保険法に基づく老齢給付等を受けることができる者となつたときに限る。）は、その日）に、被保険者の資格を喪失する"])),
    ("K07", PS + " §2.3", "国年法第9条第3号「六十歳に達したとき（第七条第一項第二号に該当するときを除く。）」", "law", ("kokunen", NOW, "main", "9", "1/3", ["六十歳に達したとき（第七条第一項第二号に該当するときを除く。）"])),
    ("K08", PS + " §2.3", "国年法第9条第6号「被扶養配偶者でなくなつたとき（第七条第一項第一号又は第二号に該当するときを除く。）」", "law", ("kokunen", NOW, "main", "9", "1/6", ["被扶養配偶者でなくなつたとき（第七条第一項第一号又は第二号に該当するときを除く。）"])),
    ("K09", PS + " §2.3", "国年法第12条第5項（第3号被保険者の届出、種別の変更）", "law", ("kokunen", NOW, "main", "12", "5", ["第三号被保険者", "種別の変更", "厚生労働大臣に届け出なければならない"])),
    ("K10", PS + " §2.3", "国年法第12条第6項（第1号厚生年金被保険者の被扶養配偶者は事業主経由、共済組合員等の被扶養配偶者は共済組合等経由）", "law", ("kokunen", NOW, "main", "12", "6", ["第一号厚生年金被保険者", "である第二号被保険者の被扶養配偶者である第三号被保険者にあつては、その配偶者である第二号被保険者を使用する事業主を経由", "国家公務員共済組合、地方公務員共済組合又は日本私立学校振興・共済事業団を経由"])),
    ("K11", PS + " §2.3", "国年法第12条第9項（受理されたときに届出があつたものとみなす）", "law", ("kokunen", NOW, "main", "12", "9", ["受理されたときは", "届出があつたものとみなす"])),
    ("K12", PS + " §5.1", "国年令第4条（見出し・本文）", "law", ("kokunen-rei", NOW, "main", "4", "", ["被扶養配偶者の認定", "法第七条第二項に規定する主として第二号被保険者の収入により生計を維持することの認定は、健康保険法", "国家公務員共済組合法", "地方公務員等共済組合法及び私立学校教職員共済法における被扶養者の認定の取扱いを勘案して日本年金機構（以下「機構」という。）が行う。"])),
    ("K13", PS + " §5.1", "国年則第1条の2（法第7条第1項第1号・第3号の厚生労働省令で定める者：外国籍の特定活動等）", "law", ("kokunen-ki", NOW, "main", "1_2", "", ["第七条第一項第一号及び第三号", "日本の国籍を有しない者", "医療", "観光"])),
    ("K14", PS + " §5.1", "国年則第1条の3（国内居住要件の例外 5類型）", "law", ("kokunen-ki", NOW, "main", "1_3", "", ["外国において留学をする学生", "外国に赴任する第二号被保険者", "に同行する者", "観光、保養又はボランティア活動その他就労以外の目的で一時的に海外に渡航する者", "第二号被保険者が外国に赴任している間に当該第二号被保険者との身分関係が生じた者", "日本国内に生活の基礎があると認められる者"])),
    ("K15", PS + " §2.3", "国年則第1条の4第2項 14日以内", "law", ("kokunen-ki", NOW, "main", "1_4", "2", ["当該事実があつた日から十四日以内"])),
    ("K16", PS + " §2.3", "国年則第6条の2の2（見出し・14日以内・被扶養配偶者でなくなつた年月日及びその理由）", "law", ("kokunen-ki", NOW, "main", "6_2_2", "", ["被扶養配偶者でなくなつたことの届出", "十四日以内", "被扶養配偶者でなくなつた年月日及びその理由"])),
    ("K17", PS + " §2.3", "国年則第14条の2（認定を行つたときは文書で通知）", "law", ("kokunen-ki", NOW, "main", "14_2", "", ["主として配偶者の収入により生計を維持していることの認定を行つたときは、文書で、その旨を届出者に通知しなければならない。"])),
    ("K18", PS + " §4", "健保法第3条第7項第1号（配偶者に事実婚を含む・生計維持）", "law", ("kenpo", NOW, "main", "3", "7/1", ["被保険者", "の直系尊属、配偶者（届出をしていないが、事実上婚姻関係と同様の事情にある者を含む。以下この項において同じ。）、子、孫及び兄弟姉妹であって、主としてその被保険者により生計を維持するもの"])),
    ("K19", PS + " §4", "健保法第3条第7項第3号・第4号（事実婚の配偶者の父母・子）", "law", ("kenpo", NOW, "main", "3", "7/3", ["事実上婚姻関係と同様の事情にあるものの父母及び子", "同一の世帯に属し"])),
    # ---------------- 検証で足した項目（文書の「分からなかったこと」の確かめ、推測の文書の前提の数値）
    ("K20", PS + " §5.2・§6-7 / " + HY + " HS7・HS9 / " + IN + " IS9", "国民年金法 原始附則第3条（被保険者の資格の特例）：65歳以上の第2号は老齢・退職の給付の受給権を有しない者に限る", "law", ("kokunen", NOW, "orig", "3", "", ["被保険者の資格の特例", "第七条第一項第二号の規定の適用については、当分の間、同号中「の被保険者」とあるのは、「の被保険者（六十五歳以上の者にあつては、厚生年金保険法附則第四条の三第一項に規定する政令で定める給付の受給権を有しない被保険者に限る。）」とする。"])),
    ("K21", PS + " §2.3・§6-12 / " + HY + " HS7・HS9", "国民年金法第11条の2：種別に変更があつた月は変更後の種別の月とみなす", "law", ("kokunen", NOW, "main", "11_2", "1", ["被保険者の種別（第一号被保険者、第二号被保険者又は第三号被保険者のいずれであるかの区別をいう。以下同じ。）に変更があつた月は、変更後の種別の被保険者であつた月とみなす。", "同一の月において、二回以上にわたり被保険者の種別に変更があつたときは、その月は最後の種別の被保険者であつた月とみなす。"])),
    ("K21b", PS + " §2.3", "国民年金法第11条第1項：被保険者期間は月により、取得した日の属する月から喪失した日の属する月の前月まで", "law", ("kokunen", NOW, "main", "11", "1", ["被保険者期間を計算する場合には、月によるものとし、被保険者の資格を取得した日の属する月からその資格を喪失した日の属する月の前月までをこれに算入する。"])),
    ("K22", PS + " §6-7", "厚生年金保険法 原始附則第4条の3第1項（国年法附則第3条が引く「政令で定める給付」の規定）", "law", ("kounen", NOW, "orig", "4_3", "1", ["老齢又は退職を支給事由とする", "政令で定める"])),
    ("S01", IN + " IS2・IS3", "措置法第29条の4（令和8年・令和9年の給与所得控除 74万円）", "law", ("sochi", R8, "main", "29_4", "", ["令和八年又は令和九年", "七十四万円"])),
    ("S02", IN + " IS4", "措置法第41条の16の2（令和8年分・令和9年分の基礎控除の加算 42万円）", "law", ("sochi", R8, "main", "41_16_2", "1", ["令和八年分及び令和九年分", "四十二万円"])),
    ("S03", IN + " IS4", "所得税法第86条第1項第1号（令和8年分 62万円）", "law", ("shotoku", R8, "main", "86", "1/1", ["六十二万円"])),
    ("C33", IN + " IS4", "地方税法第314条の2第2項（基礎控除 43万円、令和9年度分）", "law", ("chiho", C9, "main", "314_2", "2", ["四十三万円"])),
    # 走査の再現（M §2.4、PS §2.2）
    ("Z01", MS + " §2.4", "国年則：「第七条第一項第三号」を含む条は第1条の3・第1条の4", "scan", ("kokunen-ki", NOW, "第七条第一項第三号", ["1_3", "1_4"], "text")),
    ("Z02", MS + " §2.4", "国年則：「第七条第一項第一号及び第三号」を含む条は第1条の2", "scan", ("kokunen-ki", NOW, "第七条第一項第一号及び第三号", ["1_2"], "text")),
    ("Z03", MS + " §2.4", "国年則：「被扶養配偶者」を含む条は第6条の2の2", "scan", ("kokunen-ki", NOW, "被扶養配偶者", ["6_2_2"], "text")),
    ("Z04", MS + " §2.4", "国年則：「第三号被保険者」を含む単位（見出し・項・号の文）が 36", "scan", ("kokunen-ki", NOW, "第三号被保険者", 36, "units")),
    ("Z05", MS + " §2.4", "国年則：見出しで拾った条 第1条の3・第6条の2の2・第6条の3・第9条の3・第9条の4・第14条の2", "scan", ("kokunen-ki", NOW, "第三号被保険者|被扶養配偶者|国内居住|日本国内に住所", ["1_3", "6_2_2", "6_3", "9_3", "9_4", "14_2"], "caption")),
    ("Z06", PS + " §2.2 / " + MS + " §2.4", "地令@R8度：「再婚」「第三百十四条の二第十項」を含む条は第7条の16・第48条の7だけ", "scan", ("chiho-rei", C8, "再婚|第三百十四条の二第十項", ["7_16", "48_7"], "text")),
    ("Z07", PS + " §2.2 / " + MS + " §2.4", "地令@R9度：同上", "scan", ("chiho-rei", C9, "再婚|第三百十四条の二第十項", ["7_16", "48_7"], "text")),
    # 「令和7年度分（比較用）」に 2025-12-31 の版を使ったことの確かめ（賦課期日 2025-01-01 の版と同じか）
    ("Y01", PS + " §0.1・§3.1・§3.2", "第292条第1項第7号：2025-01-01 と 2025-12-31 で同文", "same", ("chiho", ["2025-01-01", C7], "292", "1/7")),
    ("Y02", PS + " §3.2", "第314条の2第1項第10号：2025-01-01 と 2025-12-31 で同文", "same", ("chiho", ["2025-01-01", C7], "314_2", "1/10")),
    ("Y03", PS + " §3.2", "第314条の2第1項第10号の2：2025-01-01 と 2025-12-31 で同文", "same", ("chiho", ["2025-01-01", C7], "314_2", "1/10_2")),
    ("Y04", PS + " §3.3", "第314条の6：2025-01-01 と 2025-12-31 で同文", "same", ("chiho", ["2025-01-01", C7], "314_6", "")),
    ("Y05", PS + " §3.2", "第34条第1項第10号の2：2025-01-01 と 2025-12-31 で同文", "same", ("chiho", ["2025-01-01", C7], "34", "1/10_2")),
    ("Y06", PS + " §2.2", "第314条の2第8項：2025-01-01 と 2025-12-31 で同文", "same", ("chiho", ["2025-01-01", C7], "314_2", "8")),
]

WEBCHECKS = [
    # ---------------- 国税庁（PS §0.2・§1.3・§1.4・§1.6・§1.8）
    ("W01", PS + " §0.2", "TA1191 の版表示「令和8年4月1日現在法令等」", "web", ("ta1191", ["令和8年4月1日現在法令等"])),
    ("W02", PS + " §1.6", "TA1191 の要件（12月31日の現況、4つの要件、62万円以下（令和7年分は58万円以下）、給与収入136万円以下（令和7年分は123万円以下、令和6年分以前は103万円以下））", "web", ("ta1191", ["控除対象配偶者とは、その年の12月31日の現況で、次の4つの要件のすべてに当てはまる人です。", "民法の規定による配偶者であること", "生計を一にしていること", "62万円以下", "令和7年分は58万円以下", "給与のみの場合は給与収入が136万円以下", "令和7年分は123万円以下、令和6年分以前は103万円以下"])),
    ("W03", PS + " §1.6", "TA1191 の要件（4）青色申告者の事業専従者…一度も給与の支払を受けていない／白色申告者の事業専従者でない", "web", ("ta1191", ["青色申告者の事業専従者としてその年を通じて一度も給与の支払を受けていないこと", "白色申告者の事業専従者でないこと"])),
    ("W04", PS + " §1.6", "TA1191 の根拠法令等「所法2、79、83、83の2、85、所基通2-46、2-47、措法41の16」", "web", ("ta1191", ["所法2、79、83、83の2、85", "所基通2-46、2-47", "措法41の16"])),
    ("W05", PS + " §1.2 / " + MS + " §3.2", "TA1191 の配偶者控除の表（38/48、26/32、13/16）", "web", ("ta1191", ["900万円以下", "38万円", "48万円", "900万円超950万円以下", "26万円", "32万円", "950万円超1,000万円以下", "13万円", "16万円"])),
    ("W06", PS + " §1.3", "TA1195 の要件ニの原文「62万円超（注）133万円以下（令和7年分は58万円を超え133万円以下、…）」", "web", ("ta1195", ["年間の合計所得金額が62万円超（注）133万円以下（令和7年分は58万円を超え133万円以下、令和2年分から令和6年分までは48万円を超え133万円以下"])),
    ("W06n", PS + " §1.3", "PS の引用「62万円超（令和7年分は58万円を超え）133万円以下」は原文にない", "webnot", ("ta1195", ["62万円超（令和7年分は58万円を超え）133万円以下"])),
    ("W07", PS + " §1.4", "TA1195「夫婦の間で互いに受けることはできません」と要件（3）（4）（5）", "web", ("ta1195", ["配偶者特別控除は夫婦の間で互いに受けることはできません", "配偶者が、配偶者特別控除を適用していないこと", "配偶者が、給与所得者の扶養控除等申告書または従たる給与についての扶養控除等申告書に記載された源泉控除対象配偶者がある居住者として、源泉徴収されていないこと（配偶者が年末調整や確定申告で配偶者特別控除の適用を受けなかった場合等を除きます。）", "公的年金"])),
    ("W08", PS + " §1.6", "TA1190 令和8年分の例（給与収入136万円以下、給与所得控除額74万円）", "web", ("ta1190", ["給与収入が136万円以下であれば、給与所得控除額が74万円ですので、これを差し引くと、合計所得金額が62万円以下となり、配偶者控除が受けられます"])),
    ("W09", PS + " §1.6", "TA1190 令和7年分（最低65万円・123万円）", "web", ("ta1190", ["65万円", "123万円"])),
    ("W10", PS + " §1.6", "TA1190 の除かれる所得（非課税所得、確定申告をしないことを選択した利子・配当等）", "web", ("ta1190", ["非課税", "確定申告をしないことを選択"])),
    ("W11", PS + " §1.8", "TA1191 Q&A Q1（事実婚の相手方は対象外。通則法）", "web", ("ta1191_qa", ["事実婚の相手方は、このような民法の規定による配偶者ではありませんから、配偶者控除の対象とはなりません", "法の適用に関する通則法"])),
    ("W12", PS + " §1.8", "TA1191 Q&A Q2（死亡時の現況、1月1日から死亡日まで、月割計算等は行いません、再婚の注）", "web", ("ta1191_qa", ["配偶者が死亡した時の現況において、控除対象配偶者の該当要件を満たしているか否かを判定し", "配偶者のその年の1月1日から死亡日までの間の合計所得金額で判定します", "配偶者控除額の月割計算等は行いません", "再婚", "所令220"])),
    ("W13", PS + " §1.8", "TA1191 Q&A Q3（本人死亡：1月1日から12月31日までの見積り、偶発的な事由、所基通85-1）", "web", ("ta1191_qa", ["配偶者のその年の1月1日から12月31日までの間の合計所得金額を見積もって判定", "偶発的", "所基通85-1"])),
    ("W14", PS + " §1.8", "TA1191 Q&A Q4〜Q6（求職者給付・出産育児一時金・出産手当金・育児休業給付金、所基通2-41）", "web", ("ta1191_qa", ["求職者給付", "出産育児一時金", "出産手当金", "育児休業給付金", "国家公務員共済組合法", "地方公務員等共済組合法", "所基通2-41"])),
    ("W15", PS + " §1.8", "TA1191 Q&A Q7（国外居住：所法120③、所令262③、所規47の2）", "web", ("ta1191_qa", ["親族関係書類", "送金関係書類", "所法120", "所令262", "所規47の2"])),
    ("W16", PS + " §1.8", "TA1191 Q&A Q3-2（所基通83〜84-1）", "web", ("ta1191_qa", ["所基通83〜84-1"])),
    ("W17", PS + " §1.8", "質疑応答 源泉 03/10（9月に死亡、両方適用できます、死亡時の現況、所法85①③、所基通81-1）", "web", ("sg_0310", ["9月", "配偶者控除とひとり親控除の両方について適用できます", "控除対象配偶者が年の中途で死亡した場合には、その死亡時の現況により判定することとされています", "所得税法第85条第1項、第3項", "所得税基本通達81-1"])),
    ("W18", PS + " §1.8", "質疑応答 源泉 03/11（父Cの青色事業専従者、84万円、控除対象配偶者とすることができません、規定ぶり、所法2①三十三・57①）", "web", ("sg_0311", ["84万円", "AはBを控除対象配偶者とすることができません", "その居住者の専従者であるとする規定ぶりではないことから、いったん生計を一にする他の者の事業専従者となった者については、その年において控除対象配偶者とすることはできません", "所得税法第2条第1項第33号", "第57条第1項"])),
    ("W19", PS + " §1.1 / §1.8", "所基通2-46（民法の規定による配偶者、内縁関係は該当しない）", "web", ("kihon_01_07", ["2－46", "民法の規定による配偶者をいうのであるから、いわゆる内縁関係にある者は"])),
    ("W20", PS + " §1.8", "所基通2-48（当該居住者又は当該居住者と生計を一にする居住者の青色事業専従者等）", "web", ("kihon_01_07", ["2－48", "当該居住者又は当該居住者と生計を一にする居住者の青色事業専従者等"])),
    ("W21", PS + " §1.8", "所基通80-1・81-1（年の中途で死別、配偶者控除と寡婦・ひとり親控除）", "web", ("kihon_16_06", ["80－1", "配偶者控除", "81－1", "配偶者控除"])),
    ("W22", PS + " §1.8", "所基通83から84の2－1（他の居住者が控除できる）", "web", ("kihon_16_06", ["83から84の2－1"])),
    ("W23", PS + " §1.8", "所基通85-1（死亡・出国の時の現況、見積もったその年1月1日から12月31日までの合計所得金額）", "web", ("kihon_16_06", ["85－1", "その死亡又は出国の時の現況により見積もったその年1月1日から12月31日までの当該親族等の合計所得金額"])),
    # ---------------- 厚労省（PS §0.3・§5.2・§5.3、M §4.1）
    ("W30", PS + " §5.2", "S61 本文（法第7条第2項・施行令第4条の三、別添、厚生大臣）", "web", ("mhlw_S61", ["国民年金法における被扶養配偶者の認定基準について", "国民年金法施行令", "第四条の三の規定に基づき", "別添", "厚生大臣"])),
    ("W31", PS + " §0.3 / §5.2", "S61 の日付・番号・宛先（昭和61年3月31日 庁保発第13号、各都道府県知事あて社会保険庁年金保険部長通知）", "web", ("mhlw_S61", ["庁保発第一三号", "各都道府県知事", "社会保険庁年金保険部長"])),
    ("W32", PS + " §5.2", "S61 別添 一 イ（九○万円未満、一五○万円未満、二分の一未満）", "web", ("mhlw_S61", ["認定対象者の年間収入が九○万円未満", "一五○万円未満", "第二号被保険者の年間収入の二分の一未満である場合は、原則として被扶養配偶者に該当するものとすること"])),
    ("W33", PS + " §5.2", "S61 別添 一 ロ・二・三", "web", ("mhlw_S61", ["第二号被保険者の年間収入を上回らない場合には", "生計維持の中心的役割を果たしていると認められるときは", "第二号被保険者からの援助による収入額より少ない場合には", "農業者"])),
    ("W34", PS + " §0.3 / §4", "S52 の日付・番号（昭和52年4月6日 保発第9号・庁保発第9号）と改正後の金額（一三〇万円・一八〇万円）", "web", ("mhlw_S52", ["保発第九号", "庁保発第九号", "一三〇万円未満", "一八〇万円未満"])),
    ("W35", PS + " §5.3 / " + MS + " §4.1", "日付検索 昭和61年3月31日：庁保発第13号の認定基準、庁保発第15号は障害認定基準", "web", ("mhlw_srch_S610331", ["国民年金法における被扶養配偶者の認定基準について", "庁保発第13号"])),
    ("W36", PS + " §5.3 / " + MS + " §4.1", "日付検索 昭和61年3月31日：庁保発第15号＝国民年金・厚生年金保険障害認定基準について", "web", ("mhlw_srch_S610331", ["国民年金・厚生年金保険障害認定基準について"])),
    ("W38", PS + " §0.3", "検討会の資料一覧に資料2（001746546.pdf）", "web", ("mhlw_kentokai", ["第３号被保険者制度"])),
    ("W39", PS + " §5.2", "議事録（130万未満、次ページに具体的な通知、平成５年４月以降130万円）", "web", ("mhlw_gijiroku", ["年間収入が130万未満であること等となってございます", "次ページに具体的な通知を添付してございます", "平成５年４月以降130万円となった後に、それ以降、変更はございません"])),
    ("W39b", PS + " §0.3", "議事録が第1回（2026年9月4日）のもの", "web", ("mhlw_gijiroku", ["第１回国民年金第３号被保険者制度等に関する検討会（議事録）", "2026年9月4日"])),
    # ---------------- 日本年金機構（PS §0.3・§2.3・§4・§5.2）
    ("W40", PS + " §0.3", "N-TET 更新日 2026年9月30日", "web", ("nenkin_tet", ["2026年9月30日"])),
    ("W41", PS + " §2.3", "N-TET 削除の事由と第1号の手続", "web", ("nenkin_tet", ["配偶者の扶養を外れた方で、厚生年金保険等に加入しない場合は、国民年金第1号被保険者の加入手続きもお願いします", "被扶養者の年間収入が130万円以上", "同居の場合、被扶養者の収入が被保険者の収入の半分以上になったとき、または別居の場合、被扶養者の収入が被保険者の仕送り額を超えたとき", "健康保険、船員保険の被保険者または共済組合、国保組合等の組合員になったとき", "婚姻等により他の被保険者に扶養されるようになったとき、または離婚したとき", "離縁、死亡または同居が要件の者が別居したとき"])),
    ("W42", PS + " §2.3", "N-TET 60日以上さかのぼる場合と、出生・婚姻・養子縁組（子が20歳以下）の例外", "web", ("nenkin_tet", ["60日以上さかのぼる場合は、扶養の事実を確認出来る書類の添付が必要", "出生、婚姻または養子縁組（子が20歳以下の場合のみ）を契機とする届出"])),
    ("W43", PS + " §4", "N-TET 配偶者（未届の事実婚関係を含む）は同居要件なし、内縁の確認書類、90日以内", "web", ("nenkin_tet", ["被保険者と同居している必要がない者", "配偶者（未届の事実婚関係を含む）", "（4）内縁関係を確認するための書類", "90日以内", "内縁関係にある両人の戸籍謄（抄）本", "被保険者の世帯全員の住民票（コピー不可・個人番号の記載がないもの）"])),
    ("W44", PS + " §4", "N-TET 控除対象配偶者・扶養親族は書類省略、1,000万円超は収入確認が必要", "web", ("nenkin_tet", ["所得税法の規定による控除対象配偶者または扶養親族となっている者", "被保険者の税法上の合計所得金額が1,000万円を超える場合は、所得税法上の控除対象配偶者の適用は受けられないため、収入確認の証明書類が必要"])),
    ("W45", PS + " §4 / " + IN + " IS7", "N-TET 一体化した様式・健保組合の場合は「国民年金第3号関係者届」のみ", "web", ("nenkin_tet", ["協会けんぽ以外の健康保険（健康保険組合など）の被保険者の配偶者が被扶養者の場合は、「国民年金第3号関係者届」のみを日本年金機構に提出してください", "健康保険被扶養者（異動）届と被扶養配偶者の国民年金第3号被保険者関係届が一体化した様式"])),
    ("W46", PS + " §0.3", "N-YOGO 更新日 2023年11月22日", "web", ("nenkin_yougo", ["2023年11月22日"])),
    ("W47", PS + " §5.2", "N-YOGO 本文（130万円未満、配偶者の年収の2分の1未満）", "web", ("nenkin_yougo", ["厚生年金に加入している第2号被保険者に扶養されている20歳以上60歳未満の配偶者（年収が130万円未満であり、かつ配偶者の年収の2分の1未満の方）を第3号被保険者といいます"])),
    ("W48", PS + " §0.3", "N-FAQ 更新日 2024年8月19日", "web", ("nenkin_faq", ["2024年8月19日"])),
    ("W49", PS + " §5.2", "N-FAQ 本文", "web", ("nenkin_faq", ["原則として年収が130万円未満の20歳以上60歳未満の方", "厚生年金保険の加入要件にあてはまる方は、厚生年金保険および健康保険に加入することになるため、第3号被保険者には該当しません"])),
    ("W50", PS + " §0.3", "N-KANYU 更新日 2025年9月11日", "web", ("nenkin_kanyu", ["2025年9月11日"])),
    ("W51", PS + " §5.2", "N-KANYU 本文（65歳到達で第1号へ、65歳以上70歳未満の除外、事業所を通じて）", "web", ("nenkin_kanyu", ["第3号被保険者の配偶者（厚生年金等の加入者）が、65歳に到達（誕生日の前日）した場合、第3号被保険者は、第1号被保険者へ切り替える必要があります", "65歳以上70歳未満で老齢または退職を理由とする年金の受給権を有する人は除く", "原則として年収が130万円未満であること", "配偶者の勤務している事業所を通じて手続きしてください"])),
    ("W52", PS + " §0.3", "N-KYOJU 更新日 2026年10月6日", "web", ("nenkin_kyoju", ["2026年10月6日"])),
    ("W53", PS + " §5.2", "N-KYOJU 本文（令和2年4月1日以降、国内居住、海外特例要件）", "web", ("nenkin_kyoju", ["令和2年4月1日", "日本国内に住所を有する", "海外特例要件"])),
    # ---------------- 市の案内（PS §0.4・§3.5）
    ("W60", PS + " §0.4", "宇都宮市 更新日 令和8年8月17日", "web", ("utsunomiya", ["更新日", "令和8年8月17日"])),
    ("W61", PS + " §3.5", "宇都宮市 配偶者控除（令和8年度以降）58万円以下・123万円以下、33/22/11万円、38/26/13万円", "web", ("utsunomiya", ["58万円以下", "123万円以下", "33万円", "22万円", "11万円", "38万円", "26万円", "13万円"])),
    ("W62", PS + " §3.5", "宇都宮市 配偶者特別控除（令和8年度以降）58万円超133万円以下、201万6,000円未満、事業専従者・他の納税義務者の扶養親族でないこと", "web", ("utsunomiya", ["配偶者が、事業専従者および他の納税義務者の扶養親族でないこと", "58万円を超え、133万円以下（給与収入のみの場合、201万6,000円未満）"])),
    # ---------------- 検証で足した項目
    ("W01b", PS + " §0.2", "TA1195・TA1190 も「令和8年4月1日現在法令等」", "web", ("ta1195", ["令和8年4月1日現在法令等"])),
    ("W01c", PS + " §0.2", "TA1190 の版表示", "web", ("ta1190", ["令和8年4月1日現在法令等"])),
    ("W01d", PS + " §0.2", "TA1191 Q&A の版表示", "web", ("ta1191_qa", ["令和8年4月1日現在法令等"])),
    ("W12b", PS + " §1.8", "TA1191 Q&A Q2 の（注）の根拠「所法2、83、85、所令220」", "web", ("ta1191_qa", ["所法2、83、85、所令220"])),
    ("W35c", PS + " §5.3 / " + MS + " §4.1", "日付検索 昭和61年3月31日 15件", "web", ("mhlw_srch_S610331", ["該当件数: 15件"])),
    ("W37", PS + " §5.3 / " + MS + " §4.1", "日付検索 平成5年3月5日 0件", "web", ("mhlw_srch_H050305", ["該当件数: 0件"])),
    ("W37b", PS + " §5.3 / " + MS + " §4.1", "日付検索 平成5年3月1日〜31日 48件", "web", ("mhlw_srch_H0503_p0", ["該当件数: 48件"])),
    ("W37c", PS + " §5.3 / " + MS + " §4.1", "平成5年3月の1〜20件目に「被扶養」を含む件名がない", "webnot", ("mhlw_srch_H0503_p0", ["被扶養"])),
    ("W37d", PS + " §5.3 / " + MS + " §4.1", "平成5年3月の21〜40件目に「被扶養」を含む件名がない", "webnot", ("mhlw_srch_H0503_p1", ["被扶養"])),
    ("W37e", PS + " §5.3 / " + MS + " §4.1", "平成5年3月の41〜48件目に「被扶養」を含む件名がない", "webnot", ("mhlw_srch_H0503_p2", ["被扶養"])),
    ("W37f", MS + " §4.1", "平成5年3月の2・3ページ目がそれぞれ 21件〜・41件〜", "web", ("mhlw_srch_H0503_p2", ["48件中 41件"])),
    ("W38b", PS + " §0.3", "資料一覧：第1回 令和８年９月４日、資料２「第３号被保険者制度を巡る現状について」、P9・P43 を令和８年９月７日に修正", "web", ("mhlw_kentokai", ["令和８年９月４日", "資料２　第３号被保険者制度を巡る現状について", "令和８年９月７日"])),
]

# HTTP の Last-Modified（PS §0.2・§0.3、M §4）。M の表の値と、ヘッダの日付（GMT）をそのまま比べる
LMCHECKS = [
    ("T01",MS + " §4 / " + PS + " §0.2", "ta1191 Last-Modified", "lm", ("ta1191", "2026-09-09")),
    ("T02", MS + " §4 / " + PS + " §0.2", "ta1195 Last-Modified", "lm", ("ta1195", "2026-09-09")),
    ("T03", MS + " §4 / " + PS + " §0.2", "ta1191_qa Last-Modified", "lm", ("ta1191_qa", "2026-09-09")),
    ("T04", MS + " §4 / " + PS + " §0.2", "ta1190 Last-Modified", "lm", ("ta1190", "2026-09-09")),
    ("T05", MS + " §4 / " + PS + " §0.2", "ta2672 Last-Modified", "lm", ("ta2672", "2026-09-10")),
    ("T06", MS + " §4 / " + PS + " §0.2", "質疑応答 03/10 Last-Modified", "lm", ("sg_0310", "2025-12-03")),
    ("T07", MS + " §4 / " + PS + " §0.2", "質疑応答 03/11 Last-Modified", "lm", ("sg_0311", "2025-12-03")),
    ("T08", MS + " §4 / " + PS + " §0.2", "年末調整のしかた 令和8年分 106.pdf Last-Modified", "lm", ("nencho2026_106", "2026-08-31")),
    ("T09", MS + " §4 / " + PS + " §0.2", "年末調整のしかた 令和7年分 106.pdf Last-Modified", "lm", ("nencho2025_106", "2025-08-29")),
    ("T10", MS + " §4", "2026bun_06.pdf Last-Modified", "lm", ("form2026bun_06", "2026-08-31")),
    ("T11", MS + " §4", "2025bun_06.pdf Last-Modified", "lm", ("form2025bun_06", "2025-08-29")),
    ("T12", MS + " §4", "令和8年度改正 Q&A Last-Modified", "lm", ("kiso2026_qa", "2026-05-29")),
    ("T13", MS + " §4 / " + PS + " §0.3", "検討会 資料2 Last-Modified", "lm", ("mhlw_kt2_pdf", "2026-09-07")),
    ("T14", MS + " §4 / " + PS + " §0.3", "機構 研修資料 01.pdf Last-Modified", "lm", ("nenkin_kenshu_pdf", "2026-09-29")),
]


# ---------------------------------------------------------------- 照合
def load_laws():
    man = json.loads((OUT / "egov_manifest.json").read_text(encoding="utf-8"))
    dl = ROOT / man["download_dir"]
    laws = {}
    for f in man["fetches"]:
        if f.get("status") == 200:
            laws[(f["short"], f["asof"])] = (Law(dl / f["file"]), f)
    return laws, man


def law_node(laws, short, asof, scope, art, path):
    lw, _ = laws[(short, asof)]
    if scope == "main":
        a = lw.main.get(art)
    elif scope == "orig":  # 原始附則（AmendLawNum の無い附則）
        a = None
        for sp in lw.suppl:
            if not (sp.get("attr", {}).get("AmendLawNum") or ""):
                for x in Law._articles(sp):
                    if x["attr"].get("Num") == art:
                        a = x
                        break
            if a is not None:
                break
    else:
        a = None
        for alt in scope[len("suppl:"):].split("|suppl:"):
            a = lw.suppl_article(alt, art)
            if a is not None:
                break
    if a is None:
        return None
    return locate(a, path)


def run_law_checks(laws):
    res = []
    for cid, doc, what, kind, args in CHECKS:
        r = {"id": cid, "doc": doc, "claim": what, "kind": kind}
        try:
            if kind == "rev":
                short, asof, rid, stt, anum, aeff = args
                _, f = laws[(short, asof)]
                got = {"law_revision_id": f.get("law_revision_id"), "status": f.get("current_revision_status"),
                       "amendment_law_num": f.get("amendment_law_num"), "amendment_enforcement_date": f.get("amendment_enforcement_date"),
                       "amendment_law_title": f.get("amendment_law_title")}
                ok = got["law_revision_id"] == rid and got["status"] == stt and (anum is None or got["amendment_law_num"] == anum) \
                    and (aeff is None or got["amendment_enforcement_date"] == aeff)
                r.update({"ok": ok, "got": got})
            elif kind in ("law", "lawnot"):
                short, asof, scope, art, path, frags = args
                n = law_node(laws, short, asof, scope, art, path)
                if n is None:
                    r.update({"ok": False, "why": f"{short}@{asof} {scope} 第{art}条 {path} が見つからない"})
                else:
                    t = text_of(n)
                    if kind == "law":
                        ok, miss = has_all(t, frags)
                        r.update({"ok": ok, "missing": miss, "where": f"{short}@{asof} {scope} 第{art}条 {path}"})
                    else:
                        found = [f for f in frags if norm(f) in norm(t)]
                        r.update({"ok": not found, "found": found, "where": f"{short}@{asof} {scope} 第{art}条 {path}"})
                    r["excerpt"] = norm(t)[:300]
            elif kind == "same":
                short, asofs, art, path = args
                ts = []
                for a in asofs:
                    n = law_node(laws, short, a, "main", art, path)
                    ts.append(None if n is None else norm(text_of(n)))
                r.update({"ok": all(t is not None for t in ts) and len(set(ts)) == 1, "asofs": asofs,
                          "lengths": [None if t is None else len(t) for t in ts]})
            elif kind == "scan":
                # (略称, asof, 正規表現, 期待する条番号の並び, 対象) 対象：text＝条の全文、caption＝見出し、units＝見出しと項・号の文の単位の数
                short, asof, pat, expected, mode = args
                lw, _ = laws[(short, asof)]
                if mode == "units":
                    n = 0
                    for a in lw.main.values():
                        n += sum(1 for u in units_of(a) if re.search(pat, u))
                    r.update({"ok": n == expected, "got": n})
                else:
                    got = []
                    for num, a in lw.main.items():
                        t = text_of(a) if mode == "text" else "".join(text_of(c) for c in kids(a, "ArticleCaption"))
                        if re.search(pat, t):
                            got.append(num)
                    r.update({"ok": sorted(got) == sorted(expected), "got": got})
            elif kind == "differ":
                short, a1, a2, art, path = args
                n1, n2 = law_node(laws, short, a1, "main", art, path), law_node(laws, short, a2, "main", art, path)
                t1, t2 = (None if n1 is None else norm(text_of(n1))), (None if n2 is None else norm(text_of(n2)))
                r.update({"ok": t1 is not None and t2 is not None and t1 != t2, "asofs": [a1, a2]})
        except Exception as e:  # noqa: BLE001
            r.update({"ok": False, "error": repr(e)})
        res.append(r)
    return res


def run_author_cmp(meta, laws_man):
    """担当の取得記録（scripts/results/R2X_spouse_fetch/*.json、R2X_spouse_egov/fetch_log*.json）と、取り直した結果が同じか。
    担当の記録は比べる用途にだけ読む（担当のコードは実行しない）。"""
    res = []
    mine_by_url = {r["url"]: r for r in meta.values()}
    for f in sorted(pathlib.Path(ROOT / "scripts" / "results" / "R2X_spouse_fetch").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        for r in d.get("results", []):
            m = mine_by_url.get(r.get("url"))
            row = {"id": "A-" + r["id"], "doc": MS + " §4", "claim": f"担当の取得記録 {f.name} の {r['id']}（SHA-256・Last-Modified）が取り直しと同じ", "kind": "auth",
                   "author_sha256": (r.get("sha256") or "")[:16], "author_lm": r.get("last_modified")}
            if m is None:
                row.update({"ok": None, "why": "取り直していない"})
            else:
                row.update({"mine_sha256": (m.get("sha256") or "")[:16], "mine_lm": m.get("last_modified"),
                            "ok": r.get("sha256") == m.get("sha256"), "lm_same": r.get("last_modified") == m.get("last_modified")})
            res.append(row)
    mine_rev = {(x["law_id"], x["asof"]): x for x in laws_man["fetches"]}
    for f in sorted(pathlib.Path(ROOT / "scripts" / "results" / "R2X_spouse_egov").glob("fetch_log*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        for r in d.get("fetches", []):
            m = mine_rev.get((r["law_id"], r["asof"]))
            row = {"id": f"A-{r['short']}@{r['asof']}", "doc": MS + " §1", "claim": f"担当の取得記録 {f.name} の版", "kind": "auth",
                   "author": r.get("law_revision_id")}
            if m is None:
                row.update({"ok": None, "why": "取り直していない"})
            else:
                row.update({"mine": m.get("law_revision_id"), "ok": r.get("law_revision_id") == m.get("law_revision_id")})
            res.append(row)
    return res


def write_author_md(auth):
    am = ["# 担当の取得記録と取り直した結果の比較", "", "| ID | 担当 | 取り直し | 同じ | 補足 |", "|---|---|---|---|---|"]
    for r in auth:
        note = r.get("why", "") + ("" if r.get("lm_same", True) else " Last-Modified が違う")
        am.append(f"| {r['id']} | {r.get('author_sha256') or r.get('author')} | {r.get('mine_sha256') or r.get('mine')} | {r.get('ok')} | {note} |")
    (OUT / "author_cmp.md").write_text(chr(10).join(am) + chr(10), encoding="utf-8")
    (OUT / "author_cmp.json").write_text(json.dumps(auth, ensure_ascii=False, indent=1), encoding="utf-8")


def load_web():
    man = json.loads((OUT / "web_manifest.json").read_text(encoding="utf-8"))
    tx = ROOT / man["text_dir"]
    texts, meta = {}, {}
    for r in man["results"]:
        meta[r["id"]] = r
        if r.get("text"):
            texts[r["id"]] = (tx / r["text"]).read_text(encoding="utf-8")
    return texts, meta, man


def lm_date(s):
    if not s:
        return None
    m = re.search(r"(\d{1,2}) (\w{3}) (\d{4})", s)
    if not m:
        return None
    mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"].index(m.group(2)) + 1
    return f"{m.group(3)}-{mon:02d}-{int(m.group(1)):02d}"


def run_web_checks(texts, meta):
    res = []
    for cid, doc, what, kind, args in WEBCHECKS + LMCHECKS:
        r = {"id": cid, "doc": doc, "claim": what, "kind": kind}
        sid = args[0]
        if kind == "lm":
            got = lm_date(meta.get(sid, {}).get("last_modified"))
            r.update({"ok": got == args[1], "got": meta.get(sid, {}).get("last_modified"), "expected_date": args[1]})
        else:
            t = texts.get(sid)
            if t is None:
                r.update({"ok": False, "why": f"{sid} のテキストがない（status={meta.get(sid, {}).get('status')}）"})
            elif kind == "webnot":
                found = [f for f in args[1] if norm(f) in norm(t)]
                r.update({"ok": not found, "found": found})
            else:
                ok, miss = has_all(t, args[1])
                r.update({"ok": ok, "missing": miss})
        res.append(r)
    return res


# ---------------------------------------------------------------- 控除額の再計算（担当の bands とは別の書き方）
def kan(s):
    """漢数字の金額（「九十三万一」「百三十三万」「千」）を整数にする。「万」の前後で分けて計算する。"""
    digits = dict(zip("〇一二三四五六七八九", range(10)))
    def small(x):
        v, cur = 0, 0
        for ch in x:
            if ch in digits:
                cur = digits[ch]
            else:
                v += (cur or 1) * {"十": 10, "百": 100, "千": 1000}[ch]
                cur = 0
        return v + cur
    if "万" in s:
        hi, lo = s.split("万", 1)
        return small(hi) * 10000 + (small(lo) if lo else 0)
    return small(s)


def calc_amount(s, honnin_band, flat_le, flat_amt, offset):
    """配偶者特別控除の額（第83条の2第1項・第314条の2第1項第10号の2）。flat_le 以下は flat_amt、130万円以下は
    38万円から「九十三万一円を超える部分の金額」（s − offset）を「5万円の整数倍−3万円」以下の最大値に切り下げた額を引く、
    130万円超は3万円。本人の区分 1・2 は 3分の2・3分の1 にして 1万円未満を切り上げる。
    offset=930001 が字義どおりの読み。930000 は比較用（どちらが公表の表に合うかを記録する）。"""
    if s <= flat_le:
        x = flat_amt
    elif s <= 1_300_000:
        over = s - offset
        # 5万円の整数倍から3万円を控除した金額のうち、over 以下で最大のもの（over がそれに等しければ over）
        k = 1
        best = None
        while 50_000 * k - 30_000 <= over:
            best = 50_000 * k - 30_000
            k += 1
        if best is None:
            best = 0  # over が 20,000 未満（5万円の整数倍−3万円の最小値 20,000 に満たない）
        x = 380_000 - best
    else:
        x = 30_000
    if honnin_band == 0:
        return x
    num, den = (2, 3) if honnin_band == 1 else (1, 3)
    # 1万円未満の端数を切り上げ（x*num/den を有理数のまま扱う）
    q, r = divmod(x * num, den * 10_000)
    return (q + (1 if r else 0)) * 10_000


def table_rows(lower, flat_le, flat_amt, offset):
    rows, cur = [], None
    for s in range(lower + 1, 1_330_001):
        v = tuple(calc_amount(s, hb, flat_le, flat_amt, offset) for hb in range(3))
        if cur and cur[2] == v:
            cur[1] = s
        else:
            if cur:
                rows.append(cur)
            cur = [s, s, v]
    rows.append(cur)
    return rows


def parse_nta_1195(text):
    """国税庁 No.1195 のテキストから「令和8年分以降」「令和7年分」の表の行を読む（自分の Extract の出力。セルの区切りは ¦）。"""
    t = re.sub(r"[ \t\u3000]+", " ", text)
    t = t.replace("\n", " ")
    out = {}
    for label in ("令和8年分以降", "令和7年分"):
        # 見出しの直後から次の見出し（「令和」）まで
        idx = [m.start() for m in re.finditer(re.escape(label) + r"\s*¦", t)]
        if not idx:
            out[label] = None
            continue
        i = idx[0]
        j = t.find("令和", i + len(label))
        seg = t[i: j if j > 0 else None]
        rows = []
        for m in re.finditer(r"(\d+)万円超\s*(\d+)万円以下\s*¦\s*(\d+)万円\s*¦\s*(\d+)万円\s*¦\s*(\d+)万円", seg):
            rows.append([int(m.group(1)) * 10000, int(m.group(2)) * 10000, [int(m.group(k)) * 10000 for k in (3, 4, 5)]])
        out[label] = rows
    return out


def cmp_rows(computed, published):
    """published の行（gt 超 le 以下）ごとに、computed の区間の額が3区分とも1つの値で一致するか。"""
    res = []
    for gt, le, amts in published:
        vals = [set(), set(), set()]
        for f, t, v in computed:
            if t <= gt or f > le:
                continue
            for k in range(3):
                vals[k].add(v[k])
        ok = all(vals[k] == {amts[k]} for k in range(3))
        res.append({"gt": gt, "le": le, "published": amts, "computed": [sorted(v) for v in vals], "match": ok})
    return res


UTSU_R8 = [  # 宇都宮市「令和8年度から」の表（取り直したテキストから書き写し。下の webcheck で文字列も確かめる）
    (580000, 1000000, [330000, 220000, 110000]), (1000000, 1050000, [310000, 210000, 110000]),
    (1050000, 1100000, [260000, 180000, 90000]), (1100000, 1150000, [210000, 140000, 70000]),
    (1150000, 1200000, [160000, 110000, 60000]), (1200000, 1250000, [110000, 80000, 40000]),
    (1250000, 1300000, [60000, 40000, 20000]), (1300000, 1330000, [30000, 20000, 10000]),
]


def kyuyo_shotoku_min(revenue, minimum):
    """給与収入が少ない範囲（最低保障額が効く範囲）の給与所得＝収入−最低保障額（0 未満は 0）。推測の文書の例の検算用。"""
    return max(0, revenue - minimum)


def run_calc(laws, texts):
    out = {}
    # 条文から定数を読む（所得税 R7・R8、住民税 R8度・R9度）
    consts = {}
    for key, short, asof in [("shotoku_R7", "shotoku", R7), ("shotoku_R8", "shotoku", R8)]:
        t33 = norm(text_of(law_node(laws, short, asof, "main", "2", "1/33")))
        m = re.search(r"合計所得金額が([〇一二三四五六七八九十百千万]+)円以下である者をいう", t33)
        consts[key] = {"douitsu_max": kan(m.group(1)), "flat_le": 950_000, "flat_amt": 380_000}
    for key, asof in [("jumin_R8nendo", C8), ("jumin_R9nendo", C9)]:
        t7 = norm(text_of(law_node(laws, "chiho", asof, "main", "292", "1/7")))
        m = re.search(r"合計所得金額が([〇一二三四五六七八九十百千万]+)円以下である者をいう", t7)
        consts[key] = {"douitsu_max": kan(m.group(1)), "flat_le": 1_000_000, "flat_amt": 330_000}
    # 条文の定数（95万円・100万円・38万円・33万円）が条文にあることは CHECKS の L15・C07 で確かめている
    tables = {}
    for key, c in consts.items():
        tables[key] = {}
        for offset_name, offset in [("literal_930001", 930_001), ("minus1_930000", 930_000)]:
            tables[key][offset_name] = table_rows(c["douitsu_max"], c["flat_le"], c["flat_amt"], offset)
    out["consts"] = consts
    # 国税庁 No.1195 との照合
    nta = parse_nta_1195(texts.get("ta1195", ""))
    out["nta_1195_rows"] = nta
    cmpres = {}
    for key, label in [("shotoku_R8", "令和8年分以降"), ("shotoku_R7", "令和7年分")]:
        for on in ("literal_930001", "minus1_930000"):
            if nta.get(label):
                cr = cmp_rows(tables[key][on], nta[label])
                cmpres[f"{key}_{on}_vs_TA1195"] = {"n": len(cr), "n_match": sum(x["match"] for x in cr), "rows": cr}
    # 宇都宮市（令和8年度）との照合
    for on in ("literal_930001", "minus1_930000"):
        cr = cmp_rows(tables["jumin_R8nendo"][on], UTSU_R8)
        cmpres[f"jumin_R8nendo_{on}_vs_utsunomiya"] = {"n": len(cr), "n_match": sum(x["match"] for x in cr), "rows": cr}
    out["compare"] = cmpres
    out["tables"] = {k: {on: [[f, t, list(v)] for f, t, v in rows] for on, rows in d.items()} for k, d in tables.items()}
    # 担当の bands.json と同じか（担当の出力は比べる用途にだけ読む）
    try:
        b = json.loads((ROOT / "scripts" / "results" / "R2X_spouse_tables" / "bands.json").read_text(encoding="utf-8"))
        same = {}
        for mine, theirs in [("shotoku_R7", "shotoku_R7"), ("shotoku_R8", "shotoku_R8"), ("jumin_R8nendo", "shichoson_R8nendo"), ("jumin_R9nendo", "shichoson_R9nendo")]:
            th = [[[r["spouse_from"], r["spouse_to"], r["amount"]] for r in band] for band in b[theirs]]
            my = tables[mine]["literal_930001"]
            # 3区分を別々の区間列にして比べる
            mine_by = []
            for hb in range(3):
                rows, cur = [], None
                for f, t, v in my:
                    if cur and cur[2] == v[hb] and cur[1] + 1 == f:
                        cur[1] = t
                    else:
                        if cur:
                            rows.append(cur)
                        cur = [f, t, v[hb]]
                rows.append(cur)
                mine_by.append(rows)
            same[mine] = mine_by == th
        out["same_as_author_bands"] = same
    except Exception as e:  # noqa: BLE001
        out["same_as_author_bands"] = {"error": repr(e)}
    # 推測の文書（IS1〜IS4）の数値の検算
    def amt(key, s, hb):
        c = consts[key]
        if s <= c["douitsu_max"]:
            return ("配偶者控除", [380_000, 260_000, 130_000][hb] if key.startswith("shotoku") else [330_000, 220_000, 110_000][hb])
        if s > 1_330_000:
            return ("対象外", 0)
        return ("配偶者特別控除", calc_amount(s, hb, c["flat_le"], c["flat_amt"], 930_001))
    is1 = []
    for key, s in [("shotoku_R7", 580_000), ("shotoku_R7", 580_001), ("shotoku_R8", 620_000), ("shotoku_R8", 620_001),
                   ("shotoku_R8", 950_000), ("shotoku_R8", 950_001), ("shotoku_R8", 1_000_000), ("shotoku_R8", 1_000_001),
                   ("shotoku_R8", 1_330_000), ("shotoku_R8", 1_330_001), ("jumin_R8nendo", 580_000), ("jumin_R8nendo", 580_001),
                   ("jumin_R9nendo", 620_000), ("jumin_R9nendo", 620_001), ("jumin_R9nendo", 1_000_000), ("jumin_R9nendo", 1_000_001)]:
        is1.append([key, s] + list(amt(key, s, 0)))
    for hb in range(3):
        is1.append(["shotoku_R8 本人区分", hb, 1_000_000] + list(amt("shotoku_R8", 1_000_000, hb)))
        is1.append(["jumin_R9nendo 本人区分", hb, 1_000_000] + list(amt("jumin_R9nendo", 1_000_000, hb)))
    out["IS1"] = is1
    # IS2・IS3：給与収入から給与所得（最低保障額 65万円・74万円が効く範囲として。最低保障額そのものは TA1190 の W08・W09 と年末調整のしかたで確認）
    is23 = {}
    for rev, mn, key in [(1_300_000, 650_000, "shotoku_R7"), (1_300_000, 740_000, "shotoku_R8"),
                         (2_000_000, 740_000, "shotoku_R8"), (2_100_000, 740_000, "shotoku_R8")]:
        g = kyuyo_shotoku_min(rev, mn)
        is23[f"{key}_{rev}"] = [g] + list(amt(key, g, 0))
    # IS3 の 2,000,000 円は、通常の給与所得控除（別表第五の基になる 収入×30%＋8万円 = 68万円）より 74万円が大きいことの確認
    is23["note_2000000_formula"] = 2_000_000 * 30 // 100 + 80_000
    is23["note_2100000_formula"] = 2_100_000 * 30 // 100 + 80_000
    out["IS2_IS3"] = is23
    # IS4：B 1,200,000 円の配偶者特別控除（所得税・本人 900万円以下）
    out["IS4"] = {"B_1200000_shotoku_R8": amt("shotoku_R8", 1_200_000, 0), "A_500000_shotoku_R8": amt("shotoku_R8", 500_000, 0),
                  "A_500000_jumin_R9": amt("jumin_R9nendo", 500_000, 0)}
    # IS5：表（７）の条件（10号の2 の配偶者で 55万円未満、控除対象配偶者でない、本人 1,000万円以下）が真になる範囲
    is5 = {}
    for key, dmax in [("R7nendo", 480_000), ("R8nendo", consts["jumin_R8nendo"]["douitsu_max"]), ("R9nendo", consts["jumin_R9nendo"]["douitsu_max"])]:
        hits = [s for s in range(0, 1_330_001) if s < 550_000 and s > dmax]  # 本人 1,000万円以下なら 控除対象配偶者でない ⇔ s > 同一生計配偶者の上限
        is5[key] = [min(hits), max(hits)] if hits else None
    out["IS5"] = is5
    return out


def write_md(law_res, web_res, calc, laws_man, web_man):
    md = ["# R2X_spouse_verify の照合結果", "",
          f"- e-Gov の取得：{laws_man['run_at']}（{laws_man['download_dir']}）",
          f"- 行政の資料の取得：{web_man['run_at']}（{web_man['download_dir']}）", ""]
    allr = law_res + web_res
    md.append(f"項目 {len(allr)} 件、一致 {sum(1 for r in allr if r.get('ok'))} 件、不一致 {sum(1 for r in allr if not r.get('ok'))} 件。")
    md.append("")
    md.append("| ID | 文書 | 主張 | 結果 | 補足 |")
    md.append("|---|---|---|---|---|")
    for r in allr:
        extra = ""
        if not r.get("ok"):
            extra = json.dumps({k: r[k] for k in ("missing", "found", "why", "got", "error", "lengths") if k in r}, ensure_ascii=False)[:400]
        elif r["kind"] == "rev":
            extra = r["got"]["law_revision_id"]
        md.append(f"| {r['id']} | {r['doc']} | {r['claim']} | {'一致' if r.get('ok') else '**不一致**'} | {extra} |")
    (OUT / "checks.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (OUT / "checks.json").write_text(json.dumps(allr, ensure_ascii=False, indent=1), encoding="utf-8")
    # calc
    cm = ["# R2X_spouse_verify の再計算", "", "## 条文から読んだ同一生計配偶者の上限", ""]
    for k, c in calc["consts"].items():
        cm.append(f"- {k}: {c['douitsu_max']:,} 円")
    cm += ["", "## 公表の表との照合（「九十三万一円を超える部分の金額」の読み方 2 通り）", ""]
    for k, c in calc["compare"].items():
        cm.append(f"- {k}: {c['n_match']}/{c['n']} 行一致")
    cm += ["", f"- 担当の bands.json と同じ区間・額か（字義どおりの読み）：{calc['same_as_author_bands']}", "", "## 区間（字義どおりの読み）", ""]
    for k, d in calc["tables"].items():
        cm.append(f"### {k}")
        cm.append("| 配偶者の合計所得金額 | 本人 900万円以下 | 900万円超950万円以下 | 950万円超1,000万円以下 |")
        cm.append("|---|---|---|---|")
        for f, t, v in d["literal_930001"]:
            cm.append(f"| {f:,}〜{t:,} | " + " | ".join(f"{x:,}" for x in v) + " |")
        cm.append("")
    cm += ["## 推測の文書の数値の検算", "", "IS1（本人区分 0=900万円以下）:", ""]
    for row in calc["IS1"]:
        cm.append(f"- {row}")
    cm += ["", f"IS2・IS3：{json.dumps(calc['IS2_IS3'], ensure_ascii=False)}", "", f"IS4：{json.dumps(calc['IS4'], ensure_ascii=False)}", "",
           f"IS5（表（７）が真になる配偶者の前年の合計所得金額の範囲）：{json.dumps(calc['IS5'], ensure_ascii=False)}", ""]
    (OUT / "calc.md").write_text("\n".join(cm) + "\n", encoding="utf-8")
    calc_small = {k: v for k, v in calc.items() if k != "tables"}
    (OUT / "calc.json").write_text(json.dumps(calc_small, ensure_ascii=False, indent=1), encoding="utf-8")


def cmd_check():
    laws, lman = load_laws()
    texts, meta, wman = load_web()
    law_res = run_law_checks(laws)
    web_res = run_web_checks(texts, meta)
    calc = run_calc(laws, texts)
    auth = run_author_cmp(meta, lman)
    write_md(law_res, web_res, calc, lman, wman)
    write_author_md(auth)
    print("author_cmp:", sum(1 for r in auth if r.get("ok")), "/", len(auth), "same; differ:", [r["id"] for r in auth if r.get("ok") is False],
          "not refetched:", [r["id"] for r in auth if r.get("ok") is None])
    for r in law_res + web_res:
        if not r.get("ok"):
            print("NG", r["id"], r["claim"], {k: r[k] for k in ("missing", "found", "why", "got", "error") if k in r})
    print("calc compare:", {k: f"{c['n_match']}/{c['n']}" for k, c in calc["compare"].items()})
    print("same_as_author_bands:", calc["same_as_author_bands"])
    print("checks:", len(law_res) + len(web_res), "ok:", sum(1 for r in law_res + web_res if r.get("ok")))


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")
    cmd = argv[0] if argv else ""
    if cmd == "egov":
        cmd_egov()
    elif cmd == "web":
        cmd_web()
    elif cmd == "check":
        cmd_check()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

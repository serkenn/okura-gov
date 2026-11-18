"""R2X juminzei-tax の独立した検証（反証役）。

別の担当が書いた次の文書の数値・条番号・通知の番号と日付・施行日・適用年度・URL を、一次情報に当たり直して確かめる。
  docs/public-sources/20261109_round2_juminzei-tax-law-text.md          （以下 PS-L）
  docs/public-sources/20261109_round2_juminzei-tax-admin-and-municipal.md （以下 PS-A）
  docs/measurements/20261109_round2_juminzei-tax-fetch-and-checks.md     （以下 M）
  docs/hypotheses/20261109_round2_juminzei-tax-calc-model.md             （以下 H）
  docs/inferences/20261109_round2_juminzei-tax-implications.md           （以下 I）
担当のスクリプト（R2X_juminzei-tax_laws.py・_web.py・_calc.py）は import も実行もしない。
e-Gov 法令API v2 と行政のサイトから取り直し、自分で書いたテキスト化（条・項・号の Num 属性で位置を特定する）・照合・計算で確かめる。
担当の出力は「担当の記録と取り直した結果が同じか」を比べる用途（author）にだけ読む。

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_juminzei-tax_verify.py egov    # 条文の取得（ネットワーク）
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_juminzei-tax_verify.py web     # 行政の資料の取得（ネットワーク）
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_juminzei-tax_verify.py check   # 照合と再計算（ネットワークなし）

- e-Gov 法令API v2 の使い方は scripts/R1_egov_articles.py・scripts/IMPL_kyuyo_fetch.py を読んで写した（import しない）。標準ライブラリのみ。
- ダウンロードは取得ごとに新しい空のディレクトリ .work/downloads/<YYYYMMDD-HHMMSS>_R2X_juminzei-tax_verify_<egov|web>/ に置く
  （信頼できないデータ。その中で何も実行しない）。HTML から取り出したテキストは .work/text/<ts>_R2X_juminzei-tax_verify_web/ に置く。
  PDF はテキスト化しない（Read ツールのページ指定で人が読み、結果は文書に書く）。
- 出力は scripts/results/R2X_juminzei-tax_verify/：
  egov_manifest.json（取得した版）、web_manifest.json（URL・HTTP・SHA-256・robots.txt）、
  checks.json・checks.md（項目ごとの照合の結果）、calc.json・calc.md（計算例・仮の例・恒等式・到達可能性・端数の感度の再計算）、
  amend_paras.md（改正附則の項が版ごとにどう見えるか）
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。個人の情報は送らない。官報は取得しない。
"""
import hashlib
import html.parser
import itertools
import json
import pathlib
import random
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from fractions import Fraction as Fr

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
SLEEP = 1.5
OUT = ROOT / "scripts" / "results" / "R2X_juminzei-tax_verify"
AUTHOR = ROOT / "scripts" / "results"

# (略称, law_id, 期待する法令名, [(asof, 改正附則を含めるか)...])
LAWS = [
    ("chiho", "325AC0000000226", "地方税法", [("2026-01-01", False), ("2026-03-31", False), ("2026-04-01", False),
                                              ("2026-11-09", True), ("2027-01-01", True), ("2028-01-01", True), ("2030-01-01", True)]),
    ("chiho-rei", "325CO0000000245", "地方税法施行令", [("2026-11-09", False), ("2027-01-01", False)]),
    ("shinrin", "431AC0000000003", "森林環境税及び森林環境譲与税に関する法律", [("2026-11-09", False), ("2027-01-01", False)]),
    ("shinrin-rei", "504CO0000000300", "森林環境税及び森林環境譲与税に関する法律施行令", [("2026-11-09", False), ("2027-01-01", False)]),
    ("shitei", "331CO0000000254", "地方自治法第二百五十二条の十九第一項の指定都市の指定に関する政令", [("2026-11-09", False), ("2027-01-01", False)]),
    ("shinsai", "423AC0000000118",
     "東日本大震災からの復興に関し地方公共団体が実施する防災のための施策に必要な財源の確保に係る地方税の臨時特例に関する法律", [("2026-11-09", False)]),
    # 推測 I5 が引く所得税の基礎控除の段階（所得税法第86条、租税特別措置法第41条の16の2）
    ("shotoku", "340AC0000000033", "所得税法", [("2025-12-31", False), ("2026-12-31", False)]),
    ("sochi", "332AC0000000026", "租税特別措置法", [("2025-12-31", False), ("2026-12-31", False)]),
]

WEB = {
    "soumu_choka": "https://www.soumu.go.jp/main_sosiki/jichi_zeisei/czaisei/czaisei_seido/149767_25.html",
    "soumu_choka_pdf": "https://www.soumu.go.jp/main_content/001073098.pdf",
    "soumu_tsuchi_pdf": "https://www.soumu.go.jp/main_content/001071661.pdf",
    "nagoya_keisanrei": "https://www.city.nagoya.jp/kurashi/zeikin/1037356/1011880/1011883/1011891.html",
    "yokohama_keisan": "https://www.city.yokohama.lg.jp/kurashi/koseki-zei-hoken/zeikin/y-shizei/kojin-shiminzei-kenminzei/kojin-shiminzei-shosai/kojinkeisan.html",
    "yokohama_zeigakukoujo": "https://www.city.yokohama.lg.jp/kurashi/koseki-zei-hoken/zeikin/y-shizei/kojin-shiminzei-kenminzei/kojin-shiminzei-shosai/zeigakukoujoR2.html",
    "chuo_zeigakukoujo": "https://www.city.chuo.lg.jp/a0009/kurashi/zeikin/juuminzei/zeigakukoujo.html",
    "wakayama_zeigakukoujo": "https://www.pref.wakayama.lg.jp/prefg/010500/kenzei/kojinkenmin/kojinkenmin_zeigakukojo.html",
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
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_juminzei-tax_verify_egov"
    dl.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    man_path = OUT / "egov_manifest.json"
    man = {"runs": []}
    if man_path.exists():
        man = json.loads(man_path.read_text(encoding="utf-8"))
    run = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "fetches": [], "errors": []}
    for short, law_id, title, asofs in LAWS:
        if only and short not in only:
            continue
        for asof, with_amend in asofs:
            q = {"response_format": "json", "asof": asof}
            if not with_amend:
                q["omit_amendment_suppl_provision"] = "true"
            url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode(q)
            rec = {"short": short, "law_id": law_id, "asof": asof, "with_amendment_suppl": with_amend, "url": url}
            for attempt in range(3):
                try:
                    st, _, hdr, body = http_get(url, accept="application/json")
                    fn = dl / f"{short}_{asof}_try{attempt}.json"
                    fn.write_bytes(body)
                    rec.update({"status": st, "file": fn.name, "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body),
                                "content_type": hdr.get("Content-Type"), "attempt": attempt})
                    d = json.loads(body)  # HTTP 200 で HTML が返ることがある（担当の M §2.2）。JSON として読めるかで判定する
                    ri = d.get("revision_info") or {}
                    li = d.get("law_info") or {}
                    rec.update({"json_ok": True, "law_title": ri.get("law_title"), "title_ok": ri.get("law_title") == title,
                                "law_num": li.get("law_num"), "law_revision_id": ri.get("law_revision_id"),
                                "amendment_law_title": ri.get("amendment_law_title"), "amendment_law_num": ri.get("amendment_law_num"),
                                "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                                "current_revision_status": ri.get("current_revision_status"), "updated": ri.get("updated")})
                    break
                except Exception as e:  # noqa: BLE001
                    rec.setdefault("failed_attempts", []).append({"attempt": attempt, "status": rec.get("status"), "bytes": rec.get("bytes"),
                                                                  "content_type": rec.get("content_type"), "error": repr(e)[:200]})
                    rec["json_ok"] = False
                    time.sleep(30)
            run["fetches"].append(rec)
            print("ok" if rec.get("json_ok") else "NG", short, asof, rec.get("law_revision_id"), rec.get("current_revision_status"),
                  rec.get("bytes"), flush=True)
            time.sleep(SLEEP)
    man["runs"].append(run)
    man_path.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")


class Extract(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript"}
    BREAK = {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "dt", "dd", "table", "caption"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self._skip, self.title, self._in_title, self.alts, self.links = [], 0, "", False, [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag in self.BREAK:
            self.parts.append("\n")
        if tag in ("td", "th"):
            self.parts.append(" ¦ ")
        if tag == "img" and a.get("alt"):
            self.alts.append(a["alt"])
            self.parts.append(f"[img alt={a['alt']}]")
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])

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
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_juminzei-tax_verify_web"
    dl.mkdir(parents=True, exist_ok=False)
    tx = ROOT / ".work" / "text" / f"{ts}_R2X_juminzei-tax_verify_web"
    tx.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    man = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"),
           "text_dir": str(tx.relative_to(ROOT)).replace("\\", "/"), "robots": {}, "results": []}
    rps = {}
    for sid, url in WEB.items():
        host = urllib.parse.urlsplit(url).netloc
        if host not in rps:
            rurl = f"https://{host}/robots.txt"
            st, _, _, body = http_get(rurl, timeout=60)
            (dl / f"robots_{host}.txt").write_bytes(body)
            rp = urllib.robotparser.RobotFileParser()
            if st == 200:
                rp.parse(decode(body, "").splitlines())
            else:
                rp.parse([])
            rps[host] = rp
            man["robots"][host] = {"url": rurl, "status": st, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
            time.sleep(SLEEP)
        rec = {"id": sid, "url": url, "robots_allowed": rps[host].can_fetch(UA, url)}
        if not rec["robots_allowed"]:
            rec["skipped"] = "robots.txt"
            man["results"].append(rec)
            continue
        try:
            st, final, hdr, body = http_get(url, timeout=120)
            ctype = hdr.get("Content-Type", "")
            ext = ".pdf" if ("pdf" in ctype.lower() or final.lower().endswith(".pdf")) else ".html"
            (dl / f"{sid}{ext}").write_bytes(body)
            rec.update({"status": st, "final_url": final, "content_type": ctype, "bytes": len(body),
                        "sha256": hashlib.sha256(body).hexdigest(), "last_modified": hdr.get("Last-Modified"), "saved": f"{sid}{ext}"})
            if ext == ".html":
                p = Extract()
                p.feed(decode(body, ctype))
                t = re.sub(r"\n{3,}", "\n\n", "".join(p.parts))
                (tx / f"{sid}.txt").write_text(t, encoding="utf-8")
                rec.update({"title": " ".join(p.title.split()), "text": f"{sid}.txt", "img_alts": len(p.alts),
                            "pdf_links": [h for h in p.links if h.lower().endswith(".pdf")][:20]})
        except Exception as e:  # noqa: BLE001
            rec["error"] = repr(e)
        man["results"].append(rec)
        print(rec["id"], rec.get("status"), rec.get("bytes"), (rec.get("sha256") or "")[:16], rec.get("error", ""), flush=True)
        time.sleep(SLEEP)
    (OUT / "web_manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- 条文のテキスト化（担当の render とは別に書いた）
def text_of(n):
    """ノードの文字列を連結する（ルビの読み Rt は落とす。表のセルの間に ¦ を入れる）。"""
    if isinstance(n, str):
        return n
    if n.get("tag") == "Rt":
        return ""
    if n.get("tag") in ("TableColumn",):
        return "¦" + "".join(text_of(c) for c in n.get("children", []))
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
        self.main, self.orig_suppl, self.amend = {}, {}, []
        self.main_provision = None

        def fn(n, anc):
            t = n.get("tag")
            sup = [a for a in anc if a.get("tag") == "SupplProvision"]
            if t == "MainProvision" and self.main_provision is None:
                self.main_provision = n
            if t == "Article" and not sup:
                self.main.setdefault(n["attr"].get("Num"), n)
            elif t == "Article" and sup and not sup[0].get("attr", {}).get("AmendLawNum"):
                self.orig_suppl.setdefault(n["attr"].get("Num"), n)
            elif t == "SupplProvision" and n.get("attr", {}).get("AmendLawNum"):
                self.amend.append(n)
        walk(self.root, fn)

    def amend_article(self, amend_re, num):
        for s in self.amend:
            if re.search(amend_re, s["attr"].get("AmendLawNum", "")):
                for a in self._articles(s):
                    if a["attr"].get("Num") == num:
                        return a
        return None

    @staticmethod
    def _articles(s):
        out = []
        walk(s, lambda n, anc: out.append(n) if n.get("tag") == "Article" else None)
        return out


def locate(node, path):
    """path：'1/10_2'（第1項第10号の2）、'1/1/1'（第1項第1号イ）、'8'（第8項）。段は Paragraph → Item → Subitem1 → Subitem2。"""
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
    """空白を除き、全角英数字を半角にする（NFKC）。"""
    s = unicodedata.normalize("NFKC", s or "")
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
#   rev      (略称, asof, 期待する law_revision_id, 期待する状態)
#   lawnum   (略称, asof, 期待する法令番号)
#   law      (略称, asof, scope, 条Num, 項/号の path, [断片...])  scope: main | orig | amend:<AmendLawNum の正規表現>
#   lawnot   同上。断片が「現れない」こと
#   same     (略称, [asof...], scope, 条Num, path)      … 版の間で文字列が同じ
#   differ   (略称, asof1, asof2, scope, 条Num, path)    … 版の間で文字列が違う
#   diffunits (略称, asof1, asof2, scope, 条Num, [違う単位の期待集合])  … 項・号の単位で違う所がちょうどその集合か
#   absent / present (略称, asof, scope, 条Num)          … 条がない／ある
#   amendparas (略称, asof, scope, 条Num, [見える項の Num...])
#   grepcount (略称, asof, 正規表現, 期待件数)            … 本則・原始附則の全文での出現数
#   shitei   (略称, asof, [市の名前...])
#   nocaption (略称, asof, 正規表現)                      … 本則の条の見出しに正規表現が現れない
NOW, C0101, C0331, C0401, C27, C28, C30 = "2026-11-09", "2026-01-01", "2026-03-31", "2026-04-01", "2027-01-01", "2028-01-01", "2030-01-01"
A2 = "amend:令和八年三月三一日法律第二号"
L, A, M = "PS-L", "PS-A", "M"
SHITEI20 = ["大阪市", "名古屋市", "京都市", "横浜市", "神戸市", "北九州市", "札幌市", "川崎市", "福岡市", "広島市", "仙台市", "千葉市", "さいたま市", "静岡市", "堺市",
            "新潟市", "浜松市", "岡山市", "相模原市", "熊本市"]
TOKUREI_TABLE = ["百九十五万円以下の金額", "百分の八十五", "百九十五万円を超え三百三十万円以下の金額", "百分の八十", "三百三十万円を超え六百九十五万円以下の金額", "百分の七十",
                 "六百九十五万円を超え九百万円以下の金額", "百分の六十七", "九百万円を超え千八百万円以下の金額", "百分の五十七", "千八百万円を超え四千万円以下の金額", "百分の五十",
                 "四千万円を超える金額", "百分の四十五"]


def c(cid, doc, claim, kind, *args):
    return (cid, doc, claim, kind, args)


CHECKS = [
    # ---- 版（PS-L §0、M §2.1）
    c("V01", L + " §0", "地方税法 asof 2026-01-01", "rev", "chiho", C0101, "325AC0000000226_20260101_507AC0000000041", "PreviousEnforced"),
    c("V02", L + " §0", "地方税法 asof 2026-03-31", "rev", "chiho", C0331, "325AC0000000226_20260101_507AC0000000041", "PreviousEnforced"),
    c("V03", L + " §0", "地方税法 asof 2026-04-01", "rev", "chiho", C0401, "325AC0000000226_20260401_508AC0000000002", "PreviousEnforced"),
    c("V04", L + " §0", "地方税法 asof 2026-11-09", "rev", "chiho", NOW, "325AC0000000226_20261101_508AC0000000002", "CurrentEnforced"),
    c("V05", L + " §0", "地方税法 asof 2027-01-01", "rev", "chiho", C27, "325AC0000000226_20270101_508AC0000000002", "UnEnforced"),
    c("V06", L + " §0", "地方税法 asof 2028-01-01", "rev", "chiho", C28, "325AC0000000226_20280101_508AC0000000002", "UnEnforced"),
    c("V07", L + " §0", "地方税法 asof 2030-01-01", "rev", "chiho", C30, "325AC0000000226_20290624_508AC0000000051", "UnEnforced"),
    c("V08", L + " §0", "地方税法施行令 asof 2026-11-09", "rev", "chiho-rei", NOW, "325CO0000000245_20261101_508CO0000000083", "CurrentEnforced"),
    c("V09", L + " §0", "地方税法施行令 asof 2027-01-01", "rev", "chiho-rei", C27, "325CO0000000245_20270101_508CO0000000083", "UnEnforced"),
    c("V10", L + " §0", "森林環境税法 asof 2026-11-09", "rev", "shinrin", NOW, "431AC0000000003_20260401_508AC0000000002", "CurrentEnforced"),
    c("V11", L + " §0", "森林環境税法 asof 2027-01-01（同じ版）", "rev", "shinrin", C27, "431AC0000000003_20260401_508AC0000000002", "CurrentEnforced"),
    c("V12", L + " §0", "森林環境税法施行令 asof 2026-11-09", "rev", "shinrin-rei", NOW, "504CO0000000300_20260401_508CO0000000083", "CurrentEnforced"),
    c("V13", L + " §0", "森林環境税法施行令 asof 2027-01-01（同じ版）", "rev", "shinrin-rei", C27, "504CO0000000300_20260401_508CO0000000083", "CurrentEnforced"),
    c("V14", L + " §0", "指定都市の政令 asof 2026-11-09", "rev", "shitei", NOW, "331CO0000000254_20120401_423CO0000000323", "CurrentEnforced"),
    c("V15", L + " §0", "指定都市の政令 asof 2027-01-01（同じ版）", "rev", "shitei", C27, "331CO0000000254_20120401_423CO0000000323", "CurrentEnforced"),
    c("V16", L + " §0", "震災臨時特例法 asof 2026-11-09", "rev", "shinsai", NOW, "423AC0000000118_20111202_000000000000000", "CurrentEnforced"),
    c("V17", L + " §0", "森林環境税法の法令番号（平成31年法律第3号）", "lawnum", "shinrin", NOW, "平成三十一年法律第三号"),
    c("V18", L + " §0", "同施行令の法令番号（令和4年政令第300号）", "lawnum", "shinrin-rei", NOW, "令和四年政令第三百号"),
    c("V19", L + " §0", "指定都市の政令の法令番号（昭和31年政令第254号）", "lawnum", "shitei", NOW, "昭和三十一年政令第二百五十四号"),
    c("V20", L + " §0", "震災臨時特例法の法令番号（平成23年法律第118号）", "lawnum", "shinsai", NOW, "平成二十三年法律第百十八号"),
    c("V21", "I5", "所得税法第86条①一（asof 2025-12-31、令和7年分）：58万円", "law", "shotoku", "2025-12-31", "main", "86", "1/1", ["二千三百五十万円以下である場合五十八万円"]),
    c("V22", "I5", "所得税法第86条①一（asof 2026-12-31、令和8年分）：62万円", "law", "shotoku", "2026-12-31", "main", "86", "1/1", ["二千三百五十万円以下である場合六十二万円"]),
    c("V23", "I5", "措法第41条の16の2①一イ（asof 2025-12-31、令和7年分）：132万円以下 37万円加算（計95万円）", "law", "sochi", "2025-12-31", "main", "41_16_2", "1/1/1",
      ["百三十二万円以下である場合三十七万円"]),
    c("V24", "I5", "措法第41条の16の2①一イ（asof 2026-12-31、令和8年分）：489万円以下 42万円加算（計104万円）", "law", "sochi", "2026-12-31", "main", "41_16_2", "1/1/1",
      ["四百八十九万円以下である場合四十二万円"]),
    c("V25", "I5", "措法第41条の16の2①一ロ（asof 2026-12-31）：489万円超 5万円", "law", "sochi", "2026-12-31", "main", "41_16_2", "1/1/2", ["四百八十九万円を超える場合五万円"]),
    c("V26", "I5", "措法第41条の16の2①（asof 2026-12-31）：655万円以下が対象", "law", "sochi", "2026-12-31", "main", "41_16_2", "1", ["六百五十五万円"]),

    # ---- 改正附則（PS-L §1、H4）
    c("A01", L + " §1", "令8法2 附則第1条：本体は令和8年4月1日施行", "law", "chiho", C30, A2, "1", "1", ["この法律は、令和八年四月一日から施行する。"]),
    c("A02", L + " §1", "同 第1条第2号：第292条①6・7・9号、第314条の7⑪（第1号に係る部分を除く）の改正などは令和9年1月1日", "law", "chiho", C30, A2, "1", "1/2",
      ["第二百九十二条第一項第六号、第七号及び第九号", "同法第三百十四条の七第十一項の改正規定（同項第一号に係る部分を除く。）", "第十一条第二項及び第八項から第十項までの規定", "令和九年一月一日"]),
    c("A03", L + " §1・§8.2", "同 第1条第1号（第314条の7②③の改正）は令和8年10月1日", "law", "chiho", C30, A2, "1", "1/1", ["同法第三百十四条の七第二項の改正規定", "同条第三項の改正規定", "令和八年十月一日"]),
    c("A04", L + " §1", "同 第1条第6号（第314条の2①8の2 の改正、附則第11条第3項）は令和10年1月1日", "law", "chiho", C30, A2, "1", "1/6", ["第三百十四条の二第一項第八号の二", "第十一条第三項", "令和十年一月一日"]),
    c("A05", L + " §1", "同 第1条第17号：令和8年法律第64号の施行の日の属する年の翌々年の1月1日（附則第11条第11項・第13項）", "law", "chiho", C30, A2, "1", "1/17",
      ["第十一条第十一項及び第十三項", "令和八年法律第六十四号）の施行の日の属する年の翌々年の一月一日"]),
    c("A06", L + " §1", "同 第11条第1項：令和8年度以後の個人の市町村民税に適用", "law", "chiho", C30, A2, "11", "1", ["新法の規定中個人の市町村民税に関する部分", "令和八年度以後の年度分の個人の市町村民税について適用"]),
    c("A07", L + " §1", "同 第3条第1項：令和8年度以後の個人の道府県民税に適用", "law", "chiho", C30, A2, "3", "1", ["個人の道府県民税に関する部分", "令和八年度以後の年度分"]),
    c("A08", L + " §1", "同 第11条第2項：第292条①7号・9号は令和9年度以後", "law", "chiho", C30, A2, "11", "2",
      ["新法第二百九十二条第一項（第七号及び第九号に係る部分に限る。）の規定は、令和九年度以後の年度分の個人の市町村民税について適用"]),
    c("A09", L + " §1", "同 第3条第2項：第23条①7号・9号は令和9年度以後", "law", "chiho", C30, A2, "3", "2", ["新法第二十三条第一項（第七号及び第九号に係る部分に限る。）の規定は、令和九年度以後"]),
    c("A10", L + " §1", "同 第11条第3項：第314条の2①8号の2 は令和10年度以後", "law", "chiho", C30, A2, "11", "3",
      ["新法第三百十四条の二第一項（第八号の二に係る部分に限る。）の規定は、令和十年度以後の年度分の個人の市町村民税について適用"]),
    c("A11", L + " §1", "同 第11条第8項：九年一月新法第314条の7⑪・附則第5条の5② は令和10年度以後（令和9年度分までは従前の例）", "law", "chiho", C30, A2, "11", "8",
      ["九年一月新法第三百十四条の七第十一項及び附則第五条の五第二項の規定は、令和十年度以後の年度分の個人の市町村民税について適用し、令和九年度分までの個人の市町村民税については、なお従前の例による。"]),
    c("A12", L + " §1", "同 第3条第9項：第37条の2⑪・附則第5条の5① は令和10年度以後", "law", "chiho", C30, A2, "3", "9",
      ["第三十七条の二第十一項及び附則第五条の五第一項の規定は、令和十年度以後", "令和九年度分までの個人の道府県民税については、なお従前の例による"]),
    c("A13", L + " §1 / I6", "同 第11条第10項：九年一月新法附則第5条の4⑤〜⑧ は令和8年1月1日以後に居住の用に供する場合に適用", "law", "chiho", C30, A2, "11", "10",
      ["九年一月新法附則第五条の四第五項から第八項までの規定は", "令和八年一月一日以後に", "居住の用に供する場合について適用し", "同日前に"]),
    c("A14", L + " §1", "同 第3条第12項：九年一月新法附則第5条の4①〜④（道府県）", "law", "chiho", C30, A2, "3", "12", ["九年一月新法附則第五条の四第一項から第四項までの規定は", "令和八年一月一日以後に"]),
    c("A15", L + " §1", "同 第11条第11項：十七号施行日の属する年度の翌年度以後", "law", "chiho", C30, A2, "11", "11", ["十七号施行日の属する年度の翌年度以後"]),
    c("A16", L + " §1", "同 第11条第13項：附則第35条の3の6 ほか", "law", "chiho", C30, A2, "11", "13", ["新法附則第三十五条の三の六第四項から第六項まで", "十七号施行日の属する年度の翌年度以後"]),
    c("A17", L + " §1", "附則第35条の3の6（asof 2030-01-01）は「特定暗号資産に係る譲渡所得等」（暗号資産関係の読み）", "law", "chiho", C30, "orig", "35_3_6", "", ["特定暗号資産に係る譲渡所得等"]),
    c("A18", L + " §1", "e-Gov の改正附則第11条の見える項（asof 2026-11-09）", "amendparas", "chiho", NOW, A2, "11", ["1", "4", "5", "6", "7", "14", "15"]),
    c("A19", L + " §1", "同（asof 2027-01-01）", "amendparas", "chiho", C27, A2, "11", ["1", "2", "4", "5", "6", "7", "8", "9", "10", "14", "15"]),
    c("A20", L + " §1", "同（asof 2028-01-01）", "amendparas", "chiho", C28, A2, "11", ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "12", "14", "15"]),
    c("A21", L + " §1", "同（asof 2030-01-01）", "amendparas", "chiho", C30, A2, "11", [str(i) for i in range(1, 16)]),
    # 施行日の特定（PS-L §1・§7・§8、M §3.3）
    c("S01", L + " §1 / " + M + " §3.3", "asof 2026-03-31 の第314条の7 に「四十八万円」がない", "lawnot", "chiho", C0331, "main", "314_7", "", ["四十八万円"]),
    c("S02", L + " §1 / " + M + " §3.3", "asof 2026-03-31 の第37条の2 に「四十八万円」がない", "lawnot", "chiho", C0331, "main", "37_2", "", ["四十八万円"]),
    c("S03", L + " §1 / " + M + " §3.3", "asof 2026-03-31 の附則第5条の4の2 に「四十八万円」がない", "lawnot", "chiho", C0331, "orig", "5_4_2", "", ["四十八万円"]),
    c("S04", L + " §1 / " + M + " §3.3", "asof 2026-03-31 の附則第7条の2 に「四十八万円」がない", "lawnot", "chiho", C0331, "orig", "7_2", "", ["四十八万円"]),
    c("S05", L + " §1 / " + M + " §3.3", "asof 2026-04-01 の第314条の7⑪一 に基礎控除の差", "law", "chiho", C0401, "main", "314_7", "11/1", ["から四十八万円を控除して得た額"]),
    c("S06", L + " §1 / " + M + " §3.3", "asof 2026-04-01 の第37条の2⑪一 に基礎控除の差", "law", "chiho", C0401, "main", "37_2", "11/1", ["から四十八万円を控除して得た額"]),
    c("S07", L + " §7 / " + M + " §3.3", "asof 2026-04-01 の附則第5条の4⑤ に基礎控除の差（居住年 平成28年〜令和7年）", "law", "chiho", C0401, "orig", "5_4", "5",
      ["居住年が平成二十八年から令和七年までの各年である場合には", "から四十八万円を控除して得た額"]),
    c("S08", L + " §8.3 / " + M + " §3.3", "asof 2026-04-01 の附則第7条の2⑤ に基礎控除の差", "law", "chiho", C0401, "orig", "7_2", "5", ["から四十八万円を控除して得た額"]),
    c("S09", L + " §7 / " + M + " §3.3", "asof 2026-04-01 には附則第5条の4の2 がない", "absent", "chiho", C0401, "orig", "5_4_2"),
    c("S10", L + " §8 / " + M + " §3.1", "asof 2026-01-01 の第314条の7 に「四十八万円」がない", "lawnot", "chiho", C0101, "main", "314_7", "", ["四十八万円"]),
    c("S11", L + " §8.3", "asof 2026-01-01 の附則第7条の2 に「四十八万円」がない", "lawnot", "chiho", C0101, "orig", "7_2", "", ["四十八万円"]),
    c("S12", L + " §7", "asof 2026-01-01 の附則第5条の4の2 に「四十八万円」がない", "lawnot", "chiho", C0101, "orig", "5_4_2", "", ["四十八万円"]),
    c("S13", L + " §7", "asof 2026-01-01 の附則第5条の4 は平成20年度〜平成28年度分の旧制度", "law", "chiho", C0101, "orig", "5_4", "1", ["平成二十年度から平成二十八年度まで"]),
    c("S14", L + " §7", "asof 2026-01-01 の附則第5条の4の2⑤：平成22年度〜令和20年度、3/5", "law", "chiho", C0101, "orig", "5_4_2", "5", ["平成二十二年度から令和二十年度まで", "五分の三"]),

    # ---- 所得割の課税標準（PS-L §2）
    c("T01", L + " §2", "第313条①：前年の所得について算定した総所得金額、退職所得金額及び山林所得金額", "law", "chiho", NOW, "main", "313", "1",
      ["所得割の課税標準は、前年の所得について算定した総所得金額、退職所得金額及び山林所得金額とする。"]),
    c("T02", L + " §2", "第313条②：所得税法等の計算の例、第60条の2〜第60条の4 の例によらない", "law", "chiho", NOW, "main", "313", "2",
      ["計算の例により算定する", "同法第六十条の二から第六十条の四までの規定の例によらない"]),
    c("T03", L + " §2", "第313条④：事業専従者控除 86万円・50万円・所得÷(専従者数+1) の低い方", "law", "chiho", NOW, "main", "313", "4",
      ["いずれか低い金額", "八十六万円", "五十万円", "事業専従者の数に一を加えた数で除して得た金額"]),
    c("T04", L + " §2", "第313条⑥：住民税の申告書に記載がないと適用しない（申告義務がない場合を除く）", "law", "chiho", NOW, "main", "313", "6",
      ["第三百十七条の二第一項の規定による申告書", "記載がない場合には、適用しない", "申告書を提出する義務がない場合"]),
    c("T05", L + " §2", "第313条⑦：15歳未満かは前年12月31日の現況", "law", "chiho", NOW, "main", "313", "7", ["十五歳未満", "前年の十二月三十一日"]),
    c("T06", L + " §2", "第313条⑧：青色の純損失は「生じた年の末日の属する年度の翌々年度以後」の申告書の連続提出が要件", "law", "chiho", NOW, "main", "313", "8",
      ["青色申告書を提出し", "当該純損失の金額の生じた年の末日の属する年度の翌々年度以後の年度分の市町村民税について連続して第三百十七条の二第一項又は第三項の規定による申告書を提出しているときに限り"]),
    c("T07", L + " §2", "第313条⑨：変動所得等の純損失・雑損失は「翌年度」の申告書の提出とその後の連続提出が要件", "law", "chiho", NOW, "main", "313", "9",
      ["雑損失の金額", "翌年度の市町村民税について第三百十七条の二第一項又は第三項の規定による申告書を提出し、かつ、その後の年度分の市町村民税について連続して"]),
    c("T08", L + " §2", "第313条⑪：所得税の納税義務がない者の特定支出控除は住民税の申告書で", "law", "chiho", NOW, "main", "313", "11",
      ["前年分の所得税につき納税義務を負わない", "特定支出", "第三百十七条の二第一項の規定による申告書"]),
    c("T09", L + " §2", "第313条⑫：特定配当等は除外", "law", "chiho", NOW, "main", "313", "12", ["特定配当等", "除外して算定する"]),
    c("T10", L + " §2", "第313条⑬：確定申告書に記載があれば⑫を適用しない", "law", "chiho", NOW, "main", "313", "13", ["確定申告書に特定配当等に係る所得の明細に関する事項", "適用しない"]),
    c("T11", L + " §2", "第313条⑮：特定株式等譲渡所得金額も同じ", "law", "chiho", NOW, "main", "313", "15", ["確定申告書に特定株式等譲渡所得金額に係る所得の明細に関する事項", "適用しない"]),
    c("T12", L + " §2", "第292条①13号：合計所得金額は第313条⑧⑨の控除前", "law", "chiho", NOW, "main", "292", "1/13", ["第三百十三条第八項及び第九項の規定による控除前"]),
    c("T13", L + " §2", "附則第33条の2⑦一：扶養・非課税・調整控除などの合計所得金額に上場株式等の配当所得等を含める読替え", "law", "chiho", NOW, "orig", "33_2", "7/1",
      ["第二百九十二条第一項（第七号から第九号まで、第十一号イ（２）、第十二号ロ及び第十三号に係る部分に限る。）", "第二百九十五条第一項（第二号に係る部分に限る。）及び第三項",
       "第三百十四条の六", "上場株式等に係る配当所得等の金額"]),
    c("T14", L + " §2", "第317条の3①：確定申告書の提出で住民税の申告書の提出とみなす", "law", "chiho", NOW, "main", "317_3", "1", ["確定申告書", "申告書が提出されたものとみなす"]),

    # ---- 所得控除（PS-L §3）
    c("K01", L + " §3", "第314条の2①一 雑損控除：総所得金額等の1/10 など", "law", "chiho", NOW, "main", "314_2", "1/1/1", ["十分の一"]),
    c("K02", L + " §3", "同①二 医療費控除：5%（上限10万円）、最高200万円", "law", "chiho", NOW, "main", "314_2", "1/2", ["百分の五", "十万円を超える場合には、十万円", "二百万円を超える場合には、二百万円"]),
    c("K03", L + " §3", "同①三 社会保険料控除：全額", "law", "chiho", NOW, "main", "314_2", "1/3", ["社会保険料", "その支払つた、又は給与から控除される金額"]),
    c("K04", L + " §3", "同①四 小規模企業共済等掛金控除：全額", "law", "chiho", NOW, "main", "314_2", "1/4", ["その支払つた金額の合計額"]),
    c("K05", L + " §3", "同①五 生命保険料控除：全体の上限7万円", "law", "chiho", NOW, "main", "314_2", "1/5", ["七万円を超える場合には、七万円"]),
    c("K06", L + " §3", "同①五イ(1) 新生命保険料：12,000/32,000/56,000円の区分、上限28,000円", "law", "chiho", NOW, "main", "314_2", "1/5/1/1",
      ["一万二千円以下", "一万二千円と当該合計額から一万二千円を控除した金額の二分の一", "二万二千円と当該合計額から三万二千円を控除した金額の四分の一", "五万六千円を超える場合二万八千円"]),
    c("K07", L + " §3", "同①五イ(2) 旧生命保険料：15,000/40,000/70,000円の区分、上限35,000円", "law", "chiho", NOW, "main", "314_2", "1/5/1/2",
      ["一万五千円以下", "一万五千円と当該合計額から一万五千円を控除した金額の二分の一", "二万七千五百円と当該合計額から四万円を控除した金額の四分の一", "七万円を超える場合三万五千円"]),
    c("K08", L + " §3", "同①五イ(3) 新旧両方：合計28,000円が上限", "law", "chiho", NOW, "main", "314_2", "1/5/1/3", ["二万八千円を超える場合には、二万八千円"]),
    c("K09", L + " §3", "同①五の三 地震保険料控除：1/2、上限25,000円", "law", "chiho", NOW, "main", "314_2", "1/5_3", ["二分の一に相当する金額", "二万五千円を超える場合には、二万五千円"]),
    c("K10", L + " §3", "同①六 障害者控除 26万円、特別障害者 30万円", "law", "chiho", NOW, "main", "314_2", "1/6", ["二十六万円", "三十万円"]),
    c("K11", L + " §3", "同③ 同居特別障害者 53万円", "law", "chiho", NOW, "main", "314_2", "3", ["五十三万円"]),
    c("K12", L + " §3", "同①八 寡婦控除 26万円", "law", "chiho", NOW, "main", "314_2", "1/8", ["寡婦である所得割の納税義務者二十六万円"]),
    c("K13", L + " §3", "同①八の二 ひとり親控除 30万円（asof 2026-11-09）", "law", "chiho", NOW, "main", "314_2", "1/8_2", ["ひとり親である所得割の納税義務者三十万円"]),
    c("K14", L + " §3", "同（asof 2027-01-01）も30万円", "law", "chiho", C27, "main", "314_2", "1/8_2", ["ひとり親である所得割の納税義務者三十万円"]),
    c("K15", L + " §3", "同（asof 2028-01-01）は33万円", "law", "chiho", C28, "main", "314_2", "1/8_2", ["ひとり親である所得割の納税義務者三十三万円"]),
    c("K16", L + " §3", "同①九 勤労学生控除 26万円", "law", "chiho", NOW, "main", "314_2", "1/9", ["勤労学生である所得割の納税義務者二十六万円"]),
    c("K17", L + " §3", "同①十 配偶者控除 33万（38万）・22万（26万）・11万（13万）", "law", "chiho", NOW, "main", "314_2", "1/10",
      ["九百万円以下である場合三十三万円", "三十八万円", "九百五十万円以下である場合二十二万円", "二十六万円", "千万円以下である場合十一万円", "十三万円"]),
    c("K18", L + " §3", "同①十の二 配偶者特別控除（133万円以下、本人1,000万円以下、100万円以下33万円、93万1円、5万円の整数倍−3万円、130万円超3万円、2/3・1/3 の1万円未満切上げ）", "law",
      "chiho", NOW, "main", "314_2", "1/10_2",
      ["百三十三万円以下", "千万円以下", "百万円以下である配偶者三十三万円", "九十三万一円を超える部分の金額", "五万円の整数倍の金額から三万円を控除した金額",
       "百三十万円を超える配偶者三万円", "三分の二", "一万円未満の端数がある場合には、これを切り上げた金額", "三分の一"]),
    c("K19", L + " §3", "同①十一 扶養控除 33万円・特定扶養（19歳以上23歳未満）45万円・老人扶養（70歳以上）38万円", "law", "chiho", NOW, "main", "314_2", "1/11",
      ["三十三万円", "年齢十九歳以上二十三歳未満", "四十五万円", "年齢七十歳以上", "三十八万円"]),
    c("K20", L + " §3", "同④ 同居老親等 45万円", "law", "chiho", NOW, "main", "314_2", "4", ["四十五万円"]),
    c("K21", L + " §3", "同①十二 特定親族特別控除（123万円以下、95万円以下45万円 … 120万円超3万円）", "law", "chiho", NOW, "main", "314_2", "1/12",
      ["百二十三万円以下", "九十五万円以下である特定親族四十五万円", "百二十万円を超える特定親族三万円"]),
    c("K22", L + " §3", "同② 基礎控除 43万・29万・15万", "law", "chiho", NOW, "main", "314_2", "2",
      ["二千五百万円以下", "二千四百万円以下である場合四十三万円", "二千四百五十万円以下である場合二十九万円", "二千五百万円以下である場合十五万円"]),
    c("K23", L + " §3", "同⑧ 前年12月31日の現況", "law", "chiho", NOW, "main", "314_2", "8", ["前年の十二月三十一日"]),
    c("K24", L + " §3", "同⑪ 控除の順序（雑損→医療費→…→基礎、総所得・山林・退職の順）", "law", "chiho", NOW, "main", "314_2", "11",
      ["まず雑損控除額を控除し、次に医療費控除額", "基礎控除額を控除する", "総所得金額、山林所得金額又は退職所得金額から順次控除する"]),
    c("K25", L + " §3 / " + M + " §3.2", "第314条の2：asof 2026-11-09→2027-01-01 で違うのは第1項第6号だけ（第1項本文ではない）", "diffunits", "chiho", NOW, C27, "main", "314_2", ["1/6"]),
    c("K26", L + " §3", "第314条の2：asof 2027-01-01→2028-01-01 で違うのは第1項第8号の2 だけ", "diffunits", "chiho", C27, C28, "main", "314_2", ["1/8_2"]),
    c("K27", L + " §3", "附則第4条の5（asof 2026-11-09）：平成30年度から令和9年度まで", "law", "chiho", NOW, "orig", "4_5", "1", ["平成三十年度から令和九年度まで"]),
    c("K28", L + " §3", "附則第4条の5（asof 2027-01-01）：平成30年度以後", "law", "chiho", C27, "orig", "4_5", "1", ["平成三十年度以後"]),
    c("K29", L + " §1・§5", "第292条①七（asof 2026-01-01）：58万円以下", "law", "chiho", C0101, "main", "292", "1/7", ["合計所得金額が五十八万円以下である者をいう"]),
    c("K30", L + " §1・§5", "第292条①七（asof 2026-11-09）：58万円以下", "law", "chiho", NOW, "main", "292", "1/7", ["合計所得金額が五十八万円以下である者をいう"]),
    c("K31", L + " §1・§5", "第292条①七（asof 2027-01-01）：62万円以下", "law", "chiho", C27, "main", "292", "1/7", ["合計所得金額が六十二万円以下である者をいう"]),
    c("K32", L + " §1", "第292条①九（asof 2027-01-01）：62万円以下", "law", "chiho", C27, "main", "292", "1/9", ["六十二万円以下"]),

    # ---- 税率（PS-L §4）
    c("R01", L + " §4", "第314条の3①：6%（指定都市8%）の標準税率、一の率", "law", "chiho", NOW, "main", "314_3", "1", ["百分の六", "百分の八）の標準税率", "当該定める率は、一の率でなければならない"]),
    c("R02", L + " §4", "第35条①：4%（指定都市2%）、同一の標準税率ごとに一の率", "law", "chiho", NOW, "main", "35", "1", ["百分の四", "百分の二）の標準税率", "同一の標準税率ごとに一の率でなければならない"]),
    c("R03", L + " §4", "第314条の3②：課税総所得金額等＝第314条の2 の控除後", "law", "chiho", NOW, "main", "314_3", "2", ["前条の規定による控除後の前年の総所得金額、退職所得金額又は山林所得金額"]),
    c("R04", L + " §4", "第1条①五：標準税率の定義", "law", "chiho", NOW, "main", "1", "1/5", ["これによることを要しない税率", "基準財政収入額の算定の基礎として用いる税率"]),
    c("R05", L + " §4", "第314条の3 に「超えることができない」「制限税率」がない", "lawnot", "chiho", NOW, "main", "314_3", "", ["超えることができない", "制限税率"]),
    c("R06", L + " §4", "第35条 に同", "lawnot", "chiho", NOW, "main", "35", "", ["超えることができない", "制限税率"]),
    c("R07", L + " §4", "第310条 に同", "lawnot", "chiho", NOW, "main", "310", "", ["超えることができない", "制限税率"]),
    c("R08", L + " §4", "第38条 に同", "lawnot", "chiho", NOW, "main", "38", "", ["超えることができない", "制限税率"]),
    c("R09", L + " §4 / " + M + " §3.4", "本則・原始附則の全文に「制限税率」が0件（asof 2026-11-09）", "grepcount", "chiho", NOW, "制限税率", 0),
    c("R10", L + " §4 / " + M + " §3.4", "同（asof 2026-01-01）", "grepcount", "chiho", C0101, "制限税率", 0),
    c("R11", L + " §4 / " + M + " §3.4", "同（asof 2027-01-01）", "grepcount", "chiho", C27, "制限税率", 0),
    c("R12", L + " §4", "指定都市は20市", "shitei", "shitei", NOW, SHITEI20),
    c("R13", L + " §4", "指定都市は20市（asof 2027-01-01）", "shitei", "shitei", C27, SHITEI20),
    c("R14", M + " §3.2", "第314条の3 は asof 2026-01-01〜2028-01-01 で同じ", "same", "chiho", [C0101, NOW, C27, C28], "main", "314_3", ""),
    c("R15", L + " §4", "第35条 は 4版で同じ", "same", "chiho", [C0101, NOW, C27, C28], "main", "35", ""),

    # ---- 調整控除（PS-L §5）
    c("J01", L + " §5・§11", "第314条の6①：前年の合計所得金額2,500万円以下、第314条の3 の所得割の額から", "law", "chiho", NOW, "main", "314_6", "1",
      ["前年の合計所得金額が二千五百万円以下", "第三百十四条の三の規定による所得割の額から"]),
    c("J02", L + " §5", "同①一：200万円以下はいずれか少ない金額の3%（4%）", "law", "chiho", NOW, "main", "314_6", "1/1", ["二百万円以下", "いずれか少ない金額の百分の三", "百分の四"]),
    c("J03", L + " §5", "同①一イの表（人的控除差）", "law", "chiho", NOW, "main", "314_6", "1/1/1",
      ["五万円に", "障害者", "当該障害者一人につき一万円", "当該特別障害者一人につき十万円", "当該同居特別障害者一人につき二十二万円",
       "寡婦又はひとり親で政令で定めるもの", "一万円", "ひとり親で政令で定めるもの", "五万円", "勤労学生", "一万円",
       "控除対象配偶者", "五万円", "四万円", "二万円", "老人控除対象配偶者", "十万円", "六万円", "三万円",
       "前年の合計所得金額が五十五万円未満である者に限る", "五万円", "四万円", "二万円", "五十万円以上五十五万円未満", "三万円", "二万円", "一万円",
       "同居直系尊属である老人扶養親族を除く", "五万円", "特定扶養親族一人につき十八万円", "老人扶養親族一人につき十万円", "同居直系尊属である老人扶養親族", "十三万円"]),
    c("J04", L + " §5", "同①二：200万円超は（イ−ロ、5万円を下回るときは5万円）の3%（4%）", "law", "chiho", NOW, "main", "314_6", "1/2",
      ["二百万円を超える場合", "五万円を下回る場合には、五万円とする", "百分の三", "百分の四"]),
    c("J05", L + " §5", "同①二ロ：合計課税所得金額−200万円", "law", "chiho", NOW, "main", "314_6", "1/2/2", ["合計課税所得金額から二百万円を控除した金額"]),
    c("J06", L + " §5", "第314条の6 に「特定親族」がない", "lawnot", "chiho", NOW, "main", "314_6", "", ["特定親族"]),
    c("J07", L + " §5", "第37条 に「特定親族」がない", "lawnot", "chiho", NOW, "main", "37", "", ["特定親族"]),
    c("J08", L + " §5", "第37条①一：2%（指定都市1%）", "law", "chiho", NOW, "main", "37", "1/1", ["百分の二", "百分の一"]),
    c("J09", L + " §5 / " + M + " §3.2", "第314条の6 は asof 2026-01-01〜2028-01-01 で同じ", "same", "chiho", [C0101, NOW, C27, C28], "main", "314_6", ""),
    c("J10", L + " §5", "第37条 は 4版で同じ", "same", "chiho", [C0101, NOW, C27, C28], "main", "37", ""),
    c("J11", L + " §5", "施行令第48条の7の2①：表の（３）＝ひとり親のうち父", "law", "chiho-rei", NOW, "main", "48_7_2", "1", ["ひとり親のうち父である者"]),
    c("J12", L + " §5", "同②：表の（４）＝ひとり親のうち母", "law", "chiho-rei", NOW, "main", "48_7_2", "2", ["ひとり親のうち母である者"]),
]

CHECKS += [
    # ---- 配当控除（PS-L §6）
    c("D01", L + " §6", "附則第5条③一：1.6%（2.24%）、1,000万円超の部分 0.8%（1.12%）", "law", "chiho", NOW, "orig", "5", "3/1", ["百分の一・六", "百分の二・二四", "千万円を超える", "百分の〇・八", "百分の一・一二"]),
    c("D02", L + " §6", "同③二：証券投資信託 0.8%（1.12%）／0.4%（0.56%）", "law", "chiho", NOW, "orig", "5", "3/2", ["百分の〇・八", "百分の一・一二", "百分の〇・四", "百分の〇・五六"]),
    c("D03", L + " §6", "同③三：一般外貨建等 0.4%（0.56%）／0.2%（0.28%）", "law", "chiho", NOW, "orig", "5", "3/3", ["百分の〇・四", "百分の〇・五六", "百分の〇・二", "百分の〇・二八"]),
    c("D04", L + " §6", "同①一（道府県）：1.2%（0.56%）／0.6%（0.28%）", "law", "chiho", NOW, "orig", "5", "1/1", ["百分の一・二", "百分の〇・五六", "百分の〇・六", "百分の〇・二八"]),
    c("D05", L + " §6", "同①二（道府県）：0.6%（0.28%）／0.3%（0.14%）", "law", "chiho", NOW, "orig", "5", "1/2", ["百分の〇・六", "百分の〇・二八", "百分の〇・三", "百分の〇・一四"]),
    c("D06", L + " §6", "同①三（道府県）：0.3%（0.14%）／0.15%（0.07%）", "law", "chiho", NOW, "orig", "5", "1/3", ["百分の〇・三", "百分の〇・一四", "百分の〇・一五", "百分の〇・〇七"]),
    c("D07", L + " §6・§11", "同③：措法第9条①の配当等を除く。第314条の3・第314条の6 の後の所得割の額から控除", "law", "chiho", NOW, "orig", "5", "3",
      ["租税特別措置法第九条第一項各号に掲げる配当等に係るものを除く", "第三百十四条の三及び第三百十四条の六の規定を適用した場合の所得割の額から控除"]),
    c("D08", L + " §6", "附則第33条の2⑤後段：上場株式等の配当所得等（分離課税）には附則第5条③を適用しない", "law", "chiho", NOW, "orig", "33_2", "5", ["附則第五条第三項の規定は、適用しない"]),
    c("D09", L + " §9", "附則第5条④：第314条の8・第314条の9 の読替え", "law", "chiho", NOW, "orig", "5", "4", ["前二条並びに附則第五条第三項", "前三条並びに附則第五条第三項"]),

    # ---- 住宅借入金等特別税額控除（PS-L §7）
    c("Y01", L + " §7・§11", "附則第5条の4⑤（asof 2026-11-09）", "law", "chiho", NOW, "orig", "5_4", "5",
      ["平成二十二年度から令和二十年度まで", "租税特別措置法第四十一条又は第四十一条の二の二の規定の適用を受けた場合", "居住年が平成二十一年から令和七年までの各年である場合に限る",
       "五分の三", "五分の四", "第三百十四条の三及び第三百十四条の六の規定を適用した場合の所得割の額から控除",
       "所得税法第八十九条第二項に規定する課税総所得金額、課税退職所得金額及び課税山林所得金額の合計額", "居住年が平成二十八年から令和七年までの各年である場合には",
       "租税特別措置法第四十一条の十六の二第一項", "四十八万円", "百分の三", "百分の四", "五万八千五百円", "七万八千円"]),
    c("Y02", L + " §7", "同⑤一：措法第41条の住宅借入金等特別税額控除額", "law", "chiho", NOW, "orig", "5_4", "5/1", ["住宅借入金等特別税額控除額"]),
    c("Y03", L + " §7", "同⑤二：前年分の所得税の額（住宅借入金等特別控除などを適用しないで計算）", "law", "chiho", NOW, "orig", "5_4", "5/2",
      ["前年分の所得税の額", "これらの規定の適用がなかつたものとして計算した金額"]),
    c("Y04", L + " §7", "同⑦：居住年 平成26年〜令和3年・特定取得／特別特定取得 → 4.2%（5.6%）・81,900円（109,200円）", "law", "chiho", NOW, "orig", "5_4", "7",
      ["居住年が平成二十六年から令和三年まで", "特定取得", "特別特定取得", "百分の四・二", "百分の五・六", "八万千九百円", "十万九千二百円"]),
    c("Y05", L + " §7", "同①（道府県）：2/5（1/5）、2%（1%）、39,000円（19,500円）", "law", "chiho", NOW, "orig", "5_4", "1", ["五分の二", "五分の一", "百分の二", "百分の一", "三万九千円", "一万九千五百円"]),
    c("Y06", L + " §7", "同③（道府県）：2.8%（1.4%）、54,600円（27,300円）", "law", "chiho", NOW, "orig", "5_4", "3", ["百分の二・八", "百分の一・四", "五万四千六百円", "二万七千三百円"]),
    c("Y07", L + " §7", "附則第5条の4⑤（asof 2027-01-01）：令和25年度まで、居住年 令和12年まで、加算は平成28年〜令和7年のまま", "law", "chiho", C27, "orig", "5_4", "5",
      ["平成二十二年度から令和二十五年度まで", "居住年が平成二十一年から令和十二年まで", "居住年が平成二十八年から令和七年までの各年である場合には"]),
    c("Y08", L + " §9", "附則第5条の4⑥：第314条の8・第314条の9 の読替え", "law", "chiho", NOW, "orig", "5_4", "6", ["前二条並びに附則第五条の四第五項"]),

    # ---- 寄附金税額控除（PS-L §8）
    c("F01", L + " §8.1・§11", "第314条の7①：30%・2,000円・6%（8%）・特例控除額の加算・第314条の3と前条の後の所得割・所得割の額が上限", "law", "chiho", NOW, "main", "314_7", "1",
      ["百分の三十に相当する金額を超える場合には、当該百分の三十に相当する金額", "二千円を超える場合には、その超える金額の百分の六", "百分の八", "特例控除額を加算した金額",
       "第三百十四条の三及び前条の規定を適用した場合の所得割の額から控除", "当該控除額が当該所得割の額を超えるときは、当該控除額は、当該所得割の額に相当する金額とする"]),
    c("F02", L + " §8.1", "同①一：都道府県等（特別の利益を除く）", "law", "chiho", NOW, "main", "314_7", "1/1", ["都道府県、市町村又は特別区", "特別の利益が当該納税義務者に及ぶと認められるものを除く"]),
    c("F03", L + " §8.1", "同①二：共同募金会・日赤（賦課期日現在の住所所在の道府県内）、政令で定めるもの", "law", "chiho", NOW, "main", "314_7", "1/2",
      ["共同募金会", "賦課期日現在における住所所在の道府県内", "日本赤十字社", "政令で定めるもの"]),
    c("F04", L + " §8.1", "同①三：所得税法第78条②二・三、措法第41条の18の2②、市町村の条例", "law", "chiho", NOW, "main", "314_7", "1/3",
      ["所得税法第七十八条第二項第二号及び第三号に掲げる寄附金", "租税特別措置法第四十一条の十八の二第二項に規定する特定非営利活動に関する寄附金", "当該市町村の条例で定めるもの"]),
    c("F05", L + " §8.1", "同①四：特定非営利活動法人・市町村の条例", "law", "chiho", NOW, "main", "314_7", "1/4", ["特定非営利活動法人", "当該市町村の条例で定めるもの"]),
    c("F06", L + " §8.1", "同⑫：条例で法人の名称・主たる事務所の所在地を明らかに", "law", "chiho", NOW, "main", "314_7", "12", ["名称及び主たる事務所の所在地を明らかにしなければならない"]),
    c("F07", L + " §8.2", "同⑪：特例控除額＝(特例控除対象寄附金−2,000円)×割合×3/5（4/5）、上限は第314条の3・前条の後の所得割の20%", "law", "chiho", NOW, "main", "314_7", "11",
      ["二千円を超える金額", "五分の三", "五分の四", "第三百十四条の三及び前条の規定を適用した場合の所得割の額の百分の二十に相当する金額を超えるときは、当該百分の二十に相当する金額"]),
    c("F08", L + " §8.2", "同⑪一：人的控除差調整額（前条①一イ＋基礎控除の額−48万円）と割合の表", "law", "chiho", NOW, "main", "314_7", "11/1",
      ["前条第一号イに掲げる金額", "所得税法第八十六条第二項に規定する基礎控除の額", "租税特別措置法第四十一条の十六の二第一項", "四十八万円", "人的控除差調整額", "零以上"] + TOKUREI_TABLE),
    c("F09", L + " §8.2", "同⑪二：零を下回り山林・退職がないとき 90%", "law", "chiho", NOW, "main", "314_7", "11/2", ["零を下回るとき", "課税山林所得金額", "課税退職所得金額", "有しないとき百分の九十"]),
    c("F10", L + " §8.2", "同⑪三：山林（1/5）・退職で表を引く、両方なら低い方", "law", "chiho", NOW, "main", "314_7", "11/3", ["いずれか低い割合", "課税山林所得金額の五分の一", "課税退職所得金額について"]),
    c("F11", L + " §8.1", "第37条の2①：4%（指定都市2%）", "law", "chiho", NOW, "main", "37_2", "1", ["その超える金額の百分の四", "百分の二"]),
    c("F12", L + " §8.2", "第37条の2⑪：2/5（1/5）", "law", "chiho", NOW, "main", "37_2", "11", ["五分の二", "五分の一"]),
    c("F13", L + " §8.1", "第37条の2①三：当該道府県の条例", "law", "chiho", NOW, "main", "37_2", "1/3", ["当該道府県の条例で定めるもの"]),
    c("F14", L + " §8.2", "附則第5条の6②（市町村民税、平成26年度〜令和20年度）の読替え", "law", "chiho", NOW, "orig", "5_6", "2",
      ["平成二十六年度から令和二十年度までの各年度分の個人の市町村民税", "「百分の八十五」とあるのは「百分の八十四・八九五」", "「百分の八十」とあるのは「百分の七十九・七九」",
       "「百分の七十」とあるのは「百分の六十九・五八」", "「百分の六十七」とあるのは「百分の六十六・五一七」", "「百分の五十七」とあるのは「百分の五十六・三〇七」",
       "「百分の五十」とあるのは「百分の四十九・一六」", "「百分の四十五」とあるのは「百分の四十四・〇五五」", "「百分の五十」とあるのは「百分の四十九・一六」",
       "「百分の六十」とあるのは「百分の五十九・三七」", "「百分の七十五」とあるのは「百分の七十四・六八五」"]),
    c("F15", L + " §8.2", "附則第5条の5②：分離課税の所得があるとき（附則第33条の2⑤〜第35条の4④）、3/5（4/5）、20%", "law", "chiho", NOW, "orig", "5_5", "2",
      ["附則第三十三条の二第五項", "附則第三十五条の四第四項", "五分の三", "五分の四", "百分の二十"]),
    c("F16", L + " §8.2", "附則第5条の5②三〜五：50%・60%・75%", "law", "chiho", NOW, "orig", "5_5", "2", ["百分の五十", "百分の六十", "百分の七十五"]),
    c("F17", L + " §8.2", "第314条の7⑪（asof 2027-01-01）：20% と 115万8千円（154万4千円）の低い方", "law", "chiho", C27, "main", "314_7", "11",
      ["百分の二十に相当する金額と百十五万八千円（当該納税義務者が指定都市の区域内に住所を有する場合には、百五十四万四千円）とのいずれか低い金額"]),
    c("F18", L + " §8.2", "第37条の2⑪（asof 2027-01-01）：77万2千円（38万6千円）", "law", "chiho", C27, "main", "37_2", "11", ["七十七万二千円", "三十八万六千円"]),
    c("F19", L + " §8.2", "第314条の7⑪（asof 2026-11-09）に定額の上限はない", "lawnot", "chiho", NOW, "main", "314_7", "11", ["百十五万八千円"]),
    c("F20", L + " §8.2 / " + A + " §1", "附則第5条の6③（asof 2028-01-01）：平成26年度〜令和30年度（市町村民税）", "law", "chiho", C28, "orig", "5_6", "3", ["平成二十六年度から令和三十年度まで", "個人の市町村民税"]),
    c("F21", L + " §8.2 / " + A + " §1", "附則第5条の6④（asof 2028-01-01）：令和31年度以後 84.95% など", "law", "chiho", C28, "orig", "5_6", "4",
      ["令和三十一年度以後", "「百分の八十五」とあるのは「百分の八十四・九五」"]),
    c("F22", L + " §8.3・§11", "附則第7条の2④：当分の間、申告特例通知書の送付、第314条の7①⑪ の後の所得割の額から控除", "law", "chiho", NOW, "orig", "7_2", "4",
      ["当分の間", "特例控除対象寄附金を支出し", "申告特例通知書の送付があつた場合", "第三百十四条の七第一項及び第十一項の規定を適用した場合の所得割の額から控除"]),
    c("F23", L + " §8.3", "附則第7条の2⑤：特例控除額×割合（5区分の表）", "law", "chiho", NOW, "orig", "7_2", "5",
      ["第三百十四条の七第十一項に規定する特例控除額に", "第三百十四条の六第一号イに掲げる金額", "四十八万円", "百九十五万円以下の金額", "八十五分の五", "八十分の十", "七十分の二十",
       "六十七分の二十三", "九百万円を超える金額", "五十七分の三十三"]),
    c("F24", L + " §8.3", "附則第7条の2⑤ の表に 1,800万円・4,000万円の区分がない", "lawnot", "chiho", NOW, "orig", "7_2", "5", ["千八百万円", "四千万円"]),
    c("F25", L + " §8.3", "附則第7条の3②（市町村民税、平成28年度〜令和20年度）の読替え", "law", "chiho", NOW, "orig", "7_3", "2",
      ["平成二十八年度から令和二十年度まで", "「八十五分の五」とあるのは「八十四・八九五分の五・一〇五」", "「八十分の十」とあるのは「七十九・七九分の十・二一」",
       "「七十分の二十」とあるのは「六十九・五八分の二十・四二」", "「六十七分の二十三」とあるのは「六十六・五一七分の二十三・四八三」",
       "「五十七分の三十三」とあるのは「五十六・三〇七分の三十三・六九三」"]),
    c("F26", L + " §8.3", "附則第7条⑬一：所得税法第121条の適用を受けないこととなったとき", "law", "chiho", NOW, "orig", "7", "13/1", ["所得税法第百二十一条の規定の適用を受けないこととなつたとき"]),
    c("F27", L + " §8.3", "附則第7条⑬二：住民税の申告書の提出", "law", "chiho", NOW, "orig", "7", "13/2", ["第三百十七条の二第一項から第五項までの規定による申告書の提出をしたとき"]),
    c("F28", L + " §8.3 / H3", "附則第7条⑬三：申告特例通知書を送付した都道府県知事等の数が5を超えたとき", "law", "chiho", NOW, "orig", "7", "13/3",
      ["申告特例通知書を送付した都道府県知事等の数が五を超えたとき"]),
    c("F35", L + " §8.3", "附則第7条⑬四：送付を受けた市町村長が賦課期日現在の住所所在地の市町村長と異なったとき", "law", "chiho", NOW, "orig", "7", "13/4",
      ["申告特例通知書の送付を受けた市町村長が賦課期日現在における住所所在地の市町村長と異なつたとき"]),
    c("F29", M + " §3.2", "第314条の7：asof 2026-01-01→2026-11-09 で第1項は同じ", "same", "chiho", [C0101, NOW], "main", "314_7", "1"),
    c("F30", M + " §3.2", "第314条の7：asof 2026-01-01→2026-11-09 で第11項は違う", "differ", "chiho", C0101, NOW, "main", "314_7", "11"),
    c("F31", M + " §3.2", "第314条の7：asof 2026-11-09→2027-01-01 で違うのは第1項第3号と第11項だけ", "diffunits", "chiho", NOW, C27, "main", "314_7", ["1/3", "11"]),
    c("F32", M + " §3.2", "附則第7条の2：asof 2026-01-01→2026-11-09 で違うのは第2項・第5項だけ", "diffunits", "chiho", C0101, NOW, "orig", "7_2", ["2", "5"]),
    c("F33", M + " §3.2", "附則第7条の2：asof 2026-11-09→2027-01-01 で全項同じ", "same", "chiho", [NOW, C27], "orig", "7_2", ""),
    c("F34", M + " §3.2", "附則第3条の3：asof 2026-11-09→2027-01-01 で違うのは第1項だけ", "diffunits", "chiho", NOW, C27, "orig", "3_3", ["1"]),

    # ---- 外国税額控除・配当割額等の控除（PS-L §9、PS-A §1 25）
    c("G01", L + " §9・§11", "第314条の8：第314条の3 及び前二条の後の所得割の額から", "law", "chiho", NOW, "main", "314_8", "1", ["第三百十四条の三及び前二条の規定を適用した場合の所得割の額から控除"]),
    c("G02", L + " §9 / " + A + " §1", "施行令第48条の9の2④：国税の控除限度額の18%（指定都市24%）", "law", "chiho-rei", NOW, "main", "48_9_2", "4", ["国税の控除限度額に百分の十八", "百分の二十四"]),
    c("G03", A + " §2.3", "施行令第7条の19③：道府県民税は国税の控除限度額の12%", "law", "chiho-rei", NOW, "main", "7_19", "3", ["国税の控除限度額に百分の十二"]),
    c("G04", L + " §9・§11", "第314条の9①：配当割額・株式等譲渡所得割額×3/5、第314条の3 及び前三条の後", "law", "chiho", NOW, "main", "314_9", "1",
      ["五分の三を乗じて得た金額", "第三百十四条の三及び前三条の規定を適用した場合の所得割の額から控除"]),
    c("G05", L + " §9", "第37条の4：2/5", "law", "chiho", NOW, "main", "37_4", "1", ["五分の二を乗じて得た金額"]),
    c("G06", L + " §9", "第314条の9②：還付、翌年度分の個人住民税・森林環境税への充当", "law", "chiho", NOW, "main", "314_9", "2",
      ["還付しなければならない", "翌年度分の個人の道府県民税、個人の市町村民税若しくは森林環境税"]),

    # ---- 所得割の非課税と調整（PS-L §10）
    c("N01", L + " §10", "附則第3条の3④：35万円×(人数+1)+10万円（+32万円）以下は所得割を課さない（分離課税を除く）", "law", "chiho", NOW, "orig", "3_3", "4",
      ["三十五万円", "同一生計配偶者及び扶養親族", "年齢十六歳未満の者及び第三百十四条の二第一項第十一号に規定する控除対象扶養親族に限る",
       "一を加えた数を乗じて得た金額に十万円を加算した金額", "三十二万円を加算した金額", "以下である者", "市町村民税の所得割（分離課税に係る所得割を除く。）を課することができない"]),
    c("N02", L + " §10・§11", "附則第3条の3⑤：超える金額×B/(B+C) を第314条の3・第314条の6 の後の所得割から控除", "law", "chiho", NOW, "orig", "3_3", "5",
      ["第一号に掲げる額から第二号に掲げる額と第三号に掲げる額との合計額を控除した金額を超える", "第二号に掲げる額を同号に掲げる額と第三号に掲げる額との合計額で除して得た数値を乗じて得た金額",
       "第三百十四条の三及び第三百十四条の六の規定を適用した場合の所得割の額から控除"]),
    c("N03", L + " §10", "同⑤二（B）：第314条の3、第314条の6〜第314条の8、附則第5条③、第5条の4⑤、第5条の5②", "law", "chiho", NOW, "orig", "3_3", "5/2",
      ["第三百十四条の三、第三百十四条の六から第三百十四条の八まで、附則第五条第三項、附則第五条の四第五項及び附則第五条の五第二項"]),
    c("N04", L + " §10", "同⑤三（C）：第35条、第37条〜第37条の3、附則第5条①、第5条の4①、第5条の5①", "law", "chiho", NOW, "orig", "3_3", "5/3",
      ["第三十五条、第三十七条から第三十七条の三まで、附則第五条第一項、附則第五条の四第一項及び附則第五条の五第一項"]),
    c("N05", M + " §3.7・§5（compute）", "同⑤二（B）に附則第7条の2（申告特例控除）は入っていない", "lawnot", "chiho", NOW, "orig", "3_3", "5/2", ["附則第七条の二"]),

    # ---- 分離課税（PS-L §12）
    c("B01", L + " §12", "第328条：支払を受けるべき日の属する年の1月1日現在の住所所在の市町村が課する", "law", "chiho", NOW, "main", "328", "1",
      ["当該退職手当等の支払を受けるべき日の属する年の一月一日現在におけるその者の住所所在の市町村において課する"]),
    c("B02", L + " §12", "第328条の2①②：その年中の退職所得の金額、所得税法第30条②の計算の例", "law", "chiho", NOW, "main", "328_2", "",
      ["その年中の退職所得の金額", "所得税法第三十条第二項に規定する退職所得の金額の計算の例"]),
    c("B03", L + " §12", "第328条の3：6%", "law", "chiho", NOW, "main", "328_3", "1", ["分離課税に係る所得割の税率は、百分の六とする。"]),
    c("B04", L + " §12", "第50条の4：4%", "law", "chiho", NOW, "main", "50_4", "1", ["分離課税に係る所得割の税率は、百分の四とする。"]),
    c("B05", L + " §12", "第328条の3 に「標準税率」「指定都市」の語がない", "lawnot", "chiho", NOW, "main", "328_3", "", ["標準税率", "指定都市"]),
    c("B06", L + " §12", "第50条の4 に同", "lawnot", "chiho", NOW, "main", "50_4", "", ["標準税率", "指定都市"]),
    c("B07", L + " §12", "第328条の6①一：支払済みの他の退職手当等がない旨の記載 → その支払額で計算", "law", "chiho", NOW, "main", "328_6", "1/1",
      ["支払済みの他の退職手当等", "がない旨の記載がある場合", "その支払う退職手当等の金額について第三百二十八条の二及び第三百二十八条の三の規定を適用して計算した税額"]),
    c("B08", L + " §12", "同①二：ある旨の記載 → 合計額で計算して徴収済みの額を引く", "law", "chiho", NOW, "main", "328_6", "1/2", ["がある旨の記載がある場合", "合計額について", "控除した残額"]),
    c("B09", L + " §12 / H10", "同②：退職所得申告書を出していないとき → その支払額で計算", "law", "chiho", NOW, "main", "328_6", "2",
      ["退職所得申告書を提出していないとき", "その支払う退職手当等の金額について第三百二十八条の二及び第三百二十八条の三の規定を適用して計算した税額"]),
    c("B10", L + " §12", "退職所得の特例の条は第328条〜第328条の16（第328条の16 がある）", "present", "chiho", NOW, "main", "328_16"),
    c("B11", L + " §12", "同（第328条の17 はない）", "absent", "chiho", NOW, "main", "328_17"),
    c("B12", L + " §12", "道府県民税は第50条の2〜第50条の10（第50条の10 がある）", "present", "chiho", NOW, "main", "50_10"),
    c("B13", L + " §12", "同（第50条の11 はない）", "absent", "chiho", NOW, "main", "50_11"),
    c("B14", L + " §12", "附則第33条の2⑤（上場株式等の配当所得等・市町村民税）：3%（指定都市4%）", "law", "chiho", NOW, "orig", "33_2", "5",
      ["百分の三（当該納税義務者が指定都市の区域内に住所を有する場合には、百分の四）"]),
    c("B15", L + " §12", "附則第33条の2①（道府県民税）：2%（指定都市1%）", "law", "chiho", NOW, "orig", "33_2", "1", ["百分の二（当該納税義務者が指定都市の区域内に住所を有する場合には、百分の一）"]),
    c("B16", L + " §12", "附則第35条の2の2（上場株式等の譲渡所得等）：2%（1%）・3%（4%）", "law", "chiho", NOW, "orig", "35_2_2", "",
      ["百分の二（当該納税義務者が指定都市の区域内に住所を有する場合には、百分の一）", "百分の三（当該納税義務者が指定都市の区域内に住所を有する場合には、百分の四）"]),
    c("B17", L + " §12", "附則第33条の2 に「標準税率」の語がない", "lawnot", "chiho", NOW, "orig", "33_2", "", ["標準税率"]),

    # ---- 均等割（PS-L §13）
    c("E01", L + " §13", "第294条①：一号（住所）は均等割＋所得割、二号（事務所等のみ）は均等割", "law", "chiho", NOW, "main", "294", "1",
      ["第一号の者に対しては均等割額及び所得割額の合算額により", "第二号及び第四号の者に対しては均等割額により"]),
    c("E02", L + " §13", "第294条①二", "law", "chiho", NOW, "main", "294", "1/2", ["市町村内に事務所、事業所又は家屋敷を有する個人で当該市町村内に住所を有しない者"]),
    c("E03", L + " §13", "第24条①（道府県民税）：同じ形", "law", "chiho", NOW, "main", "24", "1", ["第一号に掲げる者に対しては均等割額及び所得割額の合算額により"]),
    c("E04", L + " §13", "第310条：3,000円", "law", "chiho", NOW, "main", "310", "1", ["個人の均等割の標準税率は、三千円とする。"]),
    c("E05", L + " §13", "第38条：1,000円", "law", "chiho", NOW, "main", "38", "1", ["個人の均等割の標準税率は、千円とする。"]),
    c("E06", L + " §13", "第310条 は 4版で同じ", "same", "chiho", [C0101, NOW, C27, C28], "main", "310", ""),
    c("E07", L + " §13", "第38条 は 4版で同じ", "same", "chiho", [C0101, NOW, C27, C28], "main", "38", ""),
    c("E08", L + " §13", "第311条①：その者に対して課する均等割の額を条例で軽減できる", "law", "chiho", NOW, "main", "311", "1",
      ["その者に対して課する均等割の額を、当該市町村の条例で定めるところにより、軽減することができる"]),
    c("E09", L + " §13", "第311条①一：納税義務者自身が「均等割を納付する義務がある同一生計配偶者又は扶養親族」である場合", "law", "chiho", NOW, "main", "311", "1/1",
      ["均等割を納付する義務がある同一生計配偶者又は扶養親族", "年齢十六歳未満の者及び第三百十四条の二第一項第十一号に規定する控除対象扶養親族に限る"]),
    c("E10", L + " §13", "第311条①二：前号の者を二人以上有する者", "law", "chiho", NOW, "main", "311", "1/2", ["前号に掲げる者を二人以上有する者"]),
    c("E11", L + " §13", "震災臨時特例法第2条①：道府県民税に500円加算は平成26年度〜平成35年度", "law", "shinsai", NOW, "main", "2", "1", ["平成二十六年度から平成三十五年度まで", "五百円を加算した額"]),
    c("E12", L + " §13", "同②：市町村民税", "law", "shinsai", NOW, "main", "2", "2", ["平成二十六年度から平成三十五年度まで", "五百円を加算した額"]),

    # ---- 森林環境税（PS-L §14）
    c("M01", L + " §14", "森林環境税法第3条", "law", "shinrin", NOW, "main", "3", "1", ["この法律の施行地に住所を有する個人に対しては、この法律により、国が均等の額により森林環境税を課する。"]),
    c("M02", L + " §14", "第4条①一：生活扶助その他これに準ずるものとして政令で定める扶助", "law", "shinrin", NOW, "main", "4", "1/1", ["生活保護法", "生活扶助その他これに準ずるものとして政令で定める扶助を受けている者"]),
    c("M03", L + " §14", "第4条①二：障害者・未成年者・寡婦・ひとり親（合計所得135万円超を除く）", "law", "shinrin", NOW, "main", "4", "1/2", ["障害者、未成年者、寡婦又はひとり親", "百三十五万円を超える場合を除く"]),
    c("M04", L + " §14", "第4条①三：政令で定める金額以下", "law", "shinrin", NOW, "main", "4", "1/3", ["前年の合計所得金額が政令で定める金額以下である者"]),
    c("M05", L + " §14", "第5条：1,000円", "law", "shinrin", NOW, "main", "5", "1", ["森林環境税の税率は、千円とする。"]),
    c("M06", L + " §14", "第6条：賦課期日は1月1日", "law", "shinrin", NOW, "main", "6", "1", ["当該年度の初日の属する年の一月一日"]),
    c("M07", L + " §14", "第7条：均等割の賦課徴収の例（第6条・第7条・第311条・第321条②・第323条によるものを除く）", "law", "shinrin", NOW, "main", "7", "1",
      ["個人の市町村民税の均等割の賦課徴収（地方税法第六条、第七条、第三百十一条、第三百二十一条第二項又は第三百二十三条の規定によるものを除く。）の例により"]),
    c("M08", L + " §14", "第11条：災害・扶助・失業等による免除（政令）", "law", "shinrin", NOW, "main", "11", "1", ["森林環境税を免除する"]),
    c("M09", L + " §14", "附則第2条①：第2章は令和6年度以後", "law", "shinrin", NOW, "orig", "2", "1", ["第二章の規定は、令和六年度以後の年度分の森林環境税について適用する。"]),
    c("M10", L + " §14", "施行令第1条：第1号×(人数+1)+10万円（+第2号）", "law", "shinrin-rei", NOW, "main", "1", "1",
      ["第一号に掲げる金額に", "同一生計配偶者", "扶養親族", "年齢十六歳未満の者及び同法第三百十四条の二第一項第十一号に規定する控除対象扶養親族に限る",
       "一を加えた数を乗じて得た金額に、十万円を加算した金額", "第二号に掲げる金額を加算した金額"]),
    c("M11", L + " §14", "施行令第1条一：35万円×（前年12月31日の級地の）総務省令で定める率", "law", "shinrin-rei", NOW, "main", "1", "1/1",
      ["三十五万円に", "十二月三十一日における地域の級地区分", "総務省令で定める率"]),
    c("M12", L + " §14", "施行令第1条二：21万円×率", "law", "shinrin-rei", NOW, "main", "1", "1/2", ["二十一万円に"]),
    c("M13", L + " §14", "施行令第1条に「条例」の語がない", "lawnot", "shinrin-rei", NOW, "main", "1", "", ["条例"]),
    c("M14", L + " §14", "施行令の見出しに第4条第1項第1号（扶助）に当たる条がない", "nocaption", "shinrin-rei", NOW, "第四条第一項第一号"),
    c("M15", L + " §14", "施行令第6条（法第11条第2号の扶助）＝生活保護法の扶助のうち生活扶助などを除いたもの", "law", "shinrin-rei", NOW, "main", "6", "1",
      ["法第十一条第二号に規定する政令で定める扶助", "生活扶助", "を除く"]),

    # ---- 端数処理（PS-L §15）
    c("Z01", L + " §15", "第20条の4の2①：課税標準額の千円未満切捨て（政令で定める地方税を除く）", "law", "chiho", NOW, "main", "20_4_2", "1",
      ["地方税の課税標準額を計算する場合において、その額に千円未満の端数があるとき", "切り捨てる", "政令で定める地方税については、この限りでない"]),
    c("Z02", L + " §15", "同③：確定金額の百円未満切捨て（政令で定める地方税は1円未満）", "law", "chiho", NOW, "main", "20_4_2", "3", ["地方税の確定金額に百円未満の端数があるとき", "一円未満の端数"]),
    c("Z03", L + " §15", "同⑥：分割納付の千円未満の端数は最初の納期限に合算（条例で別の定め）", "law", "chiho", NOW, "main", "20_4_2", "6",
      ["千円未満の端数", "最初の納期限に係る分割金額に合算", "条例でこれと異なる定め"]),
    c("Z04", L + " §15", "同⑧：第2項、第3項（全額が100円未満の部分）及び前三項（第5項〜第7項）で一の地方税とみなす。特別徴収は百円", "law", "chiho", NOW, "main", "20_4_2", "8",
      ["第二項、第三項（地方税の確定金額の全額が百円未満であるときにおいて、その全額を切り捨てる部分に限る。）及び前三項の規定の適用については",
       "個人の市町村民税", "個人の道府県民税", "森林環境税", "それぞれ一の地方税とみなす", "「千円」とあるのは、「百円」とする"]),
    c("Z05", L + " §15", "同⑧ は「第四項」を挙げていない（前三項＝第5項〜第7項）", "lawnot", "chiho", NOW, "main", "20_4_2", "8", ["第四項"]),
    c("Z06", L + " §15", "施行令第6条の17①：個人の市町村民税を含まない", "lawnot", "chiho-rei", NOW, "main", "6_17", "1", ["市町村民税"]),
    c("Z07", L + " §15", "施行令第6条の17②：同", "lawnot", "chiho-rei", NOW, "main", "6_17", "2", ["市町村民税"]),
    c("Z08", L + " §15 / " + M + " §3.4", "施行令附則第4条の8：特定寄附信託の1円未満切捨て", "law", "chiho-rei", NOW, "orig", "4_8", "", ["一円未満の端数"]),
    c("Z09", L + " §15", "附則第5条の8（令和6年度分の特別税額控除）に1円未満切上げ", "law", "chiho", NOW, "orig", "5_8", "", ["一円未満の端数", "切り上げ"]),
    c("Z10", L + " §15", "附則第5条の12（令和7年度分の特別税額控除）に1円未満切上げ", "law", "chiho", NOW, "orig", "5_12", "", ["一円未満の端数", "切り上げ"]),
]

# ---- 検証の中で見つけた事実（検証の記録の §6・§7 の根拠）
CHECKS += [
    c("Q01", "検証 §7-1", "地方税法（asof 2026-11-09）の本則・原始附則に「特別特例取得」の語がない", "grepcount", "chiho", NOW, "特別特例取得", 0),
    c("Q02", "検証 §7-1", "租税特別措置法（asof 2025-12-31）の本則・原始附則に「特別特例取得」の語がない", "grepcount", "sochi", "2025-12-31", "特別特例取得", 0),
    c("Q03", "検証 §7-2", "地方税法施行令 附則第4条の6 は法附則第4条の4 に関する条", "law", "chiho-rei", NOW, "orig", "4_6", "1", ["法附則第四条の四第一項"]),
    c("Q04", "検証 §7-2", "地方税法施行令 附則第4条の8 は法附則第5条の7（特定寄附信託）の条", "law", "chiho-rei", NOW, "orig", "4_8", "2", ["法附則第五条の七第二項", "一円未満の端数"]),
    c("Q05", "検証 §7-3", "所得税法第78条③（asof 2025-12-31）は特定公益信託", "law", "shotoku", "2025-12-31", "main", "78", "3", ["特定公益信託"]),
    c("Q06", "検証 §7-3", "所得税法第78条②四（asof 2026-12-31）は公益信託", "law", "shotoku", "2026-12-31", "main", "78", "2/4", ["公益信託の信託財産とするために支出した"]),
    c("Q07", "検証 §7-3", "第314条の7①三（asof 2027-01-01）：所得税法第78条②二から四まで", "law", "chiho", C27, "main", "314_7", "1/3", ["所得税法第七十八条第二項第二号から第四号までに掲げる寄附金"]),
    c("Q08", "検証 §7-4", "附則第5条の4⑦（asof 2027-01-01）：平成26年〜令和3年、措法第41条第12項の特別特定取得", "law", "chiho", C27, "orig", "5_4", "7",
      ["居住年が平成二十六年から令和三年まで", "同条第十二項に規定する特別特定取得"]),
    c("Q09", "検証 §6", "附則第5条の4の2①（asof 2026-01-01）：居住年 平成11年〜18年又は平成21年〜令和7年、前条①の適用を受けないとき", "law", "chiho", C0101, "orig", "5_4_2", "1",
      ["居住年が平成十一年から平成十八年まで又は平成二十一年から令和七年まで", "前条第一項の規定の適用を受けないとき"]),
    c("Q10", "検証 §7-1", "附則第45条⑥（asof 2026-11-09）：震災特例法の場合も居住年 平成26年〜令和3年", "law", "chiho", NOW, "orig", "45", "6", ["平成二十六年から令和三年までの居住年"]),
]

# ---- 行政の資料（PS-A §1〜§3）・計算例（PS-A §2）の文字列
WEBCHECKS = [
    c("W01", A + " §2.1", "名古屋市：更新日 2026年4月1日、令和8年度の計算例", "web", "nagoya_keisanrei", ["更新日", "2026年4月1日", "市民税・県民税の計算例（令和8年度）"]),
    c("W02", A + " §2.1", "名古屋市：家族構成・給与収入・社会保険料・旧契約の一般生命保険料", "web", "nagoya_keisanrei",
      ["夫婦子ども3人（妻、子（19歳と16歳と12歳）は所得なし）", "給与収入:5,505,000円", "社会保険料支払額:825,600円", "旧契約の一般生命保険料支払額:80,000円"]),
    c("W03", A + " §2.1", "名古屋市：給与所得・所得控除の内訳と合計", "web", "nagoya_keisanrei",
      ["5,504,000円×80%－440,000円＝3,963,200円", "825,600円（全額）", "35,000円", "330,000円", "780,000円（19歳の子…45万円、16歳の子…33万円、12歳の子…0円）", "430,000円",
       "所得控除の合計額＝2,400,600円"]),
    c("W04", A + " §2.1", "名古屋市：課税総所得金額・税率・調整控除・税額", "web", "nagoya_keisanrei",
      ["3,963,200円－2,400,600円＝1,562,600円→1,562,000円(1,000円未満切捨)", "1,562,000円×7.7%＝120,274円", "1,562,000円×2%＝31,240円",
       "人的控除ごとに定められた金額の合計額＝330,000円", "市民税調整控除額　330,000円×4%＝13,200円", "県民税調整控除額　330,000円×1%＝3,300円",
       "均等割額(2,800円)", "120,274円－13,200円+2,800円＝109,874円→109,800円(100円未満切捨)", "均等割額(1,500円)",
       "31,240円－3,300円＋1,500円＝29,440円→29,400円(100円未満切捨)", "109,800円＋29,400円＝139,200円", "森林環境税額（1,000円）",
       "139,200円＋1,000円＝140,200円", "名古屋市市民税減税を適用した税率"]),
    c("W05", A + " §2.2", "横浜市：最終更新日 2026年4月1日、家族構成", "web", "yokohama_keisan",
      ["令和８年度市民税・県民税・森林環境税の計算（例）", "最終更新日 2026年4月1日", "夫婦（夫又は妻のどちらか一方が無収入の場合）、子供２人（17歳、13歳）"]),
    c("W06", A + " §2.2", "横浜市：収入・所得控除", "web", "yokohama_keisan",
      ["給与　5,500,000円", "3,960,000円", "394,800円", "一般生命保険料(新契約)：　90,000円", "地震保険料：　20,000円", "生命保険料控除額：　28,000円（限度額）",
       "地震保険料控除額：　10,000円", "配偶者控除額：　330,000円", "扶養控除額：　330,000円", "基礎控除額：　430,000円", "1,522,800円"]),
    c("W07", A + " §2.2", "横浜市：課税標準・税率・1円未満切捨て・調整控除・百円未満切捨て・均等割・森林環境税・合計", "web", "yokohama_keisan",
      ["3,960,000円－1,522,800円＝2,437,200円→2,437,000円（千円未満切捨）", "2,437,000円×8％（市民税の税率）＝194,960円",
       "2,437,000円×2.025％（県民税の税率）＝49,349.25円→49,349円（1円未満切捨）", "50,000円＋50,000円＋50,000円＝150,000円", "2,437,000円－2,000,000円＝437,000円",
       "50,000円×4％＝2,000円", "50,000円×1％＝500円", "194,960円－2,000円＝192,960円→192,900円（百円未満切捨）", "49,349円－500円＝48,849円→48,800円（百円未満切捨）",
       "3,900円（市民税）＋1,300円（県民税）＝5,200円", "森林環境税：1,000円", "241,700円＋5,200円＋1,000円＝247,900円"]),
    c("W08", A + " §2.3", "中央区：税額控除の順序", "web", "chuo_zeigakukoujo",
      ["税額控除は次の順序で控除します。", "調整控除", "配当控除", "住宅借入金等特別税額控除", "寄附金税額控除", "外国税額控除", "配当割額・株式等譲渡所得割額の控除"]),
    c("W09", A + " §2.3", "中央区：配当控除は1円未満を1円に切り上げ", "web", "chuo_zeigakukoujo", ["1円未満の端数がある場合は、1円に切り上げ"]),
    c("W10", A + " §2.3", "中央区：外国税額控除の都民税12%・特別区民税18%", "web", "chuo_zeigakukoujo", ["都民税の控除限度額：所得税の控除限度額×12％", "特別区民税の控除限度額：所得税の控除限度額×18％"]),
    c("W11", A + " §2.3", "中央区：48万円超50万円未満の行", "web", "chuo_zeigakukoujo", ["配偶者特別控除（配偶者の合計所得金額が48万円超50万円未満）"]),
    c("W12", A + " §2.4", "横浜市「税額控除」（zeigakukoujoR2.html）は令和2年度課税のページ", "web", "yokohama_zeigakukoujo", ["税額控除(令和２年度課税）", "このページでは令和２年度の課税内容を記載しています"]),
    c("W13", A + " §2.4", "横浜市（令和2年度課税）のページに1円未満・順序の記載がない", "webnot", "yokohama_zeigakukoujo", ["1円未満", "１円未満", "切り上げ", "順序"]),
    c("W14", A + " §2.4", "和歌山県のページに1円未満・順序の記載がない", "webnot", "wakayama_zeigakukoujo", ["1円未満", "１円未満", "切り上げ", "順序"]),
    c("W15", A + " §3", "総務省 超過課税の状況（画像の代替テキスト）：令和7年4月1日現在の団体", "web", "soumu_choka",
      ["超過課税実施団体数（令和7年4月1日現在）", "個人均等割 37団体",
       "岩手県、宮城県、秋田県、山形県、福島県、茨城県、栃木県、群馬県、神奈川県、富山県、石川県、山梨県、長野県、岐阜県、静岡県、愛知県、三重県、滋賀県、京都府、大阪府、兵庫県、奈良県、和歌山県、鳥取県、島根県、岡山県、広島県、山口県、愛媛県、高知県、福岡県、佐賀県、長崎県、熊本県、大分県、宮崎県、鹿児島県",
       "所得割 1団体 神奈川県", "個人均等割 2団体 神奈川県横浜市、兵庫県神戸市", "所得割 1団体 兵庫県豊岡市"]),
    c("W16", A + " §3", "同：超過課税の規模（令和6年度決算）255.1億・27.8億・21.3億・0.5億", "web", "soumu_choka",
      ["超過課税の規模（令和6年度決算）", "個人均等割 （37団体）255.1億円", "所得割 （1団体）27.8億円", "個人均等割 （2団体）21.3億円", "所得割 （1団体）0.5億円"]),
    c("W17", A + " §3", "同：本文の画像は /main_content/001073098.pdf へのリンク", "link", "soumu_choka", "/main_content/001073098.pdf"),
    c("W18", A + " 冒頭", "取扱通知 PDF の SHA-256 が担当の記録と同じ", "sha", "soumu_tsuchi_pdf", "107ba94cd6bd4b5e8db4ce3ce6e6e5e475fea94523d52f565daf396011746a02"),
    c("W19", A + " §2.1", "名古屋市のページの SHA-256 が担当の記録と同じ", "sha", "nagoya_keisanrei", "e31ea03689c320af2f9e829cffa1f474d6c7fe091481184adf3a7ebf4e9027a5"),
    c("W20", A + " §2.2", "横浜市（計算例）のページの SHA-256 が担当の記録と同じ", "sha", "yokohama_keisan", "4333d084b74e43c55a6e984cce8a287ba33249fea6291a1e0b81db3056ab66c9"),
    c("W21", A + " §2.3", "中央区のページの SHA-256 が担当の記録と同じ", "sha", "chuo_zeigakukoujo", "439d113607a5ecdf7d3e9b73cbc1d31b8165dc9908cc37271654b48f944a3d84"),
    c("W22", A + " §3", "総務省 超過課税の状況のページの SHA-256 が担当の記録と同じ", "sha", "soumu_choka", "1198f4c64e18700b71309478ba08522c5809f5f0ee02f8f9b26bc0c595ee7bd7"),
    c("W23", A + " §2.4", "横浜市（税額控除）の SHA-256 の先頭が担当の記録と同じ", "shaprefix", "yokohama_zeigakukoujo", "a6c0088c"),
    c("W24", A + " §2.4", "和歌山県の SHA-256 の先頭が担当の記録と同じ", "shaprefix", "wakayama_zeigakukoujo", "3142b6a4"),
    c("W25", M + " §2.2", "robots.txt：www.soumu.go.jp は 200", "robots", "www.soumu.go.jp", 200),
    c("W26", M + " §2.2", "robots.txt：www.city.nagoya.jp は 200", "robots", "www.city.nagoya.jp", 200),
    c("W27", M + " §2.2", "robots.txt：www.city.yokohama.lg.jp は 404", "robots", "www.city.yokohama.lg.jp", 404),
    c("W28", M + " §2.2", "robots.txt：www.city.chuo.lg.jp は 404", "robots", "www.city.chuo.lg.jp", 404),
    c("W29", M + " §2.2", "robots.txt：www.pref.wakayama.lg.jp は 404", "robots", "www.pref.wakayama.lg.jp", 404),
    c("W30", A + " §2.2", "横浜市の計算例のページの題名は「令和８年度市民税・県民税・森林環境税の計算（例）」", "title", "yokohama_keisan", "令和８年度市民税・県民税・森林環境税の計算（例）"),
    c("W31", A + " §2.2", "横浜市の計算例のページに「計算方法」の語がない（担当の見出し「個人の市民税・県民税の計算方法」はページの題名ではない）", "webnot", "yokohama_keisan", ["計算方法"]),
    c("W32", A + " §2.1", "名古屋市のページの題名は「市民税・県民税の計算例」", "title", "nagoya_keisanrei", "市民税・県民税の計算例"),
    c("W33", A + " §2.3", "中央区のページの題名は「税額控除」", "title", "chuo_zeigakukoujo", "税額控除"),
    c("W34", A + " §2.4", "和歌山県のページの題名は「個人県民税 税額控除」", "title", "wakayama_zeigakukoujo", "個人県民税 税額控除"),
    c("W35", A + " §3", "総務省のページの題名は「超過課税の状況」", "title", "soumu_choka", "超過課税の状況"),
]

# ---- 担当の記録（M）のうち、ファイルで確かめられるもの
FILECHECKS = [
    c("X01", M + " §2.2", "1回目の取得で地方税法 asof 2030-01-01 が 34,170 バイトの HTML（「ご利用のページが見つかりません」）", "errpage",
      ".work/downloads/20261109-180147_R2X_juminzei-tax_laws/chiho-far_2030-01-01.json", 34170, "ご利用のページが見つかりません"),
    c("X02", M + " §2.2", "同 施行令 asof 2026-11-09 も同じ", "errpage",
      ".work/downloads/20261109-180147_R2X_juminzei-tax_laws/chiho-rei_2026-11-09.json", 34170, "ご利用のページが見つかりません"),
    c("X03", A + " 冒頭 / " + M + " §2.2", "行政・自治体のページの2回の取得（17:47・18:18）で6件とも SHA-256 が一致", "samedirs",
      ".work/downloads/20261109-174755_R2X_juminzei-tax_web", ".work/downloads/20261109-181845_R2X_juminzei-tax_web"),
    c("X04", L + " 冒頭 / " + M + " §3.1", "担当の evidence.json は 181 件ですべて OK", "evidence", "scripts/results/R2X_juminzei-tax_calc/evidence.json", 181),
    c("X05", A + " 冒頭", "担当の municipal_checks.md は 25 件ですべて OK", "mdrows", "scripts/results/R2X_juminzei-tax_calc/municipal_checks.md", 25),
]

# M §3.4 が挙げた、地方税法（asof 2026-11-09）の本則・原始附則で端数・切上げの語が現れる条
HIT_PATTERNS = [r"一円未満の端数", r"百円未満の端数", r"千円未満の端数", r"一円に切り上げ|これを切り上げ|切り上げた金額", r"制限税率"]
M34_EXPECTED = {("本則", "20_4_2"), ("本則", "34"), ("本則", "314_2"), ("本則", "321_7_2"), ("本則", "321_7_8"), ("本則", "718_8"),
                ("原始附則", "3_2"), ("原始附則", "5_8"), ("原始附則", "5_12"), ("原始附則", "5_9"), ("原始附則", "5_11")}


# ---------------------------------------------------------------- 照合の実行
def latest_fetches():
    man = json.loads((OUT / "egov_manifest.json").read_text(encoding="utf-8"))
    recs = {}
    for run in man["runs"]:
        for f in run["fetches"]:
            if f.get("json_ok"):
                recs[(f["short"], f["asof"])] = (ROOT / run["download_dir"] / f["file"], f)
    return recs, man


class LawCache:
    def __init__(self, recs):
        self.recs, self.cache = recs, {}

    def get(self, short, asof):
        k = (short, asof)
        if k not in self.cache:
            self.cache[k] = Law(self.recs[k][0])
        return self.cache[k]

    def rec(self, short, asof):
        return self.recs[(short, asof)][1]


def article(lw, scope, art):
    if scope == "main":
        return lw.main.get(art)
    if scope == "orig":
        return lw.orig_suppl.get(art)
    return lw.amend_article(scope[len("amend:"):], art)


def units(a):
    """条を「項の本文」と「項/号」の単位に分ける（号の中の細目は号に含める）。"""
    res = {}
    for p in kids(a, "Paragraph"):
        pn = p["attr"].get("Num")
        res[pn] = "".join(text_of(x) for x in p.get("children", []) if not (isinstance(x, dict) and x.get("tag") == "Item"))
        for it in kids(p, "Item"):
            res[f"{pn}/{it['attr'].get('Num')}"] = text_of(it)
    return res


def caption(a):
    return "".join(text_of(x) for x in kids(a, "ArticleCaption"))


def all_articles(lw):
    for k, a in lw.main.items():
        yield "本則", k, a
    for k, a in lw.orig_suppl.items():
        yield "原始附則", k, a


def run_checks(lc):
    res = []
    for cid, doc, claim, kind, args in CHECKS:
        r = {"id": cid, "doc": doc, "claim": claim, "kind": kind}
        try:
            if kind == "rev":
                short, asof, rid, st = args
                f = lc.rec(short, asof)
                r.update({"ok": f.get("law_revision_id") == rid and f.get("current_revision_status") == st,
                          "got": [f.get("law_revision_id"), f.get("current_revision_status"), f.get("amendment_law_num"), f.get("amendment_enforcement_date")]})
            elif kind == "lawnum":
                short, asof, num = args
                f = lc.rec(short, asof)
                r.update({"ok": f.get("law_num") == num, "got": f.get("law_num")})
            elif kind in ("law", "lawnot"):
                short, asof, scope, art, path, frags = args
                a = article(lc.get(short, asof), scope, art)
                n = locate(a, path) if a is not None else None
                if n is None:
                    r.update({"ok": False, "why": f"{short}@{asof} {scope} {art} {path} が見つからない"})
                else:
                    t = text_of(n)
                    if kind == "law":
                        ok, miss = has_all(t, frags)
                        r.update({"ok": ok, "missing": miss})
                    else:
                        found = [f for f in frags if norm(f) in norm(t)]
                        r.update({"ok": not found, "found": found})
                    r["where"] = f"{short}@{asof} {scope} {art} {path}"
            elif kind == "same":
                short, asofs, scope, art, path = args
                ts = []
                for a_ in asofs:
                    a = article(lc.get(short, a_), scope, art)
                    n = locate(a, path) if a is not None else None
                    ts.append(None if n is None else norm(text_of(n)))
                r.update({"ok": all(t is not None for t in ts) and len(set(ts)) == 1, "lengths": [None if t is None else len(t) for t in ts]})
            elif kind == "differ":
                short, a1, a2, scope, art, path = args
                ns = [locate(article(lc.get(short, x), scope, art), path) for x in (a1, a2)]
                ts = [None if n is None else norm(text_of(n)) for n in ns]
                r.update({"ok": None not in ts and ts[0] != ts[1]})
            elif kind == "diffunits":
                short, a1, a2, scope, art, expected = args
                u1, u2 = units(article(lc.get(short, a1), scope, art)), units(article(lc.get(short, a2), scope, art))
                got = sorted(k for k in set(u1) | set(u2) if norm(u1.get(k, "")) != norm(u2.get(k, "")) or (k in u1) != (k in u2))
                r.update({"ok": got == sorted(expected), "got": got})
            elif kind in ("absent", "present"):
                short, asof, scope, art = args
                a = article(lc.get(short, asof), scope, art)
                r.update({"ok": (a is None) == (kind == "absent")})
            elif kind == "amendparas":
                short, asof, scope, art, expected = args
                a = article(lc.get(short, asof), scope, art)
                got = [p["attr"].get("Num") for p in kids(a, "Paragraph")] if a is not None else None
                r.update({"ok": got == expected, "got": got})
            elif kind == "grepcount":
                short, asof, rx, n = args
                cnt = sum(len(re.findall(rx, text_of(a))) for _, _, a in all_articles(lc.get(short, asof)))
                r.update({"ok": cnt == n, "got": cnt})
            elif kind == "shitei":
                short, asof, names = args
                t = text_of(lc.get(short, asof).main_provision)
                got = re.findall(r"[^\s　。]+?市", t.split("指定する。")[-1])
                r.update({"ok": sorted(got) == sorted(names) and len(got) == 20, "got": got})
            elif kind == "nocaption":
                short, asof, rx = args
                hits = [k for k, a in lc.get(short, asof).main.items() if re.search(rx, caption(a))]
                r.update({"ok": not hits, "got": hits, "captions": {k: caption(a) for k, a in lc.get(short, asof).main.items()}})
        except Exception as e:  # noqa: BLE001
            r.update({"ok": False, "error": repr(e)})
        res.append(r)
    return res


def run_hits(lc):
    out = {}
    for asof in (C0101, NOW, C27):
        lw = lc.get("chiho", asof)
        per = {p: [] for p in HIT_PATTERNS}
        for kind, k, a in all_articles(lw):
            t = text_of(a)
            for p in HIT_PATTERNS:
                for _ in re.finditer(p, t):
                    per[p].append((kind, k))
        out[asof] = per
    arts_now = {x for p in HIT_PATTERNS for x in out[NOW][p]}
    counts = {a: {p: len(v) for p, v in out[a].items()} for a in out}
    author = json.loads((AUTHOR / "R2X_juminzei-tax_laws" / "hits_chiho_2026-11-09.json").read_text(encoding="utf-8"))
    author_set = {(h["where"], h["article"]) for h in author}
    rei = lc.get("chiho-rei", NOW)
    rei_arts = sorted({(kind, k) for kind, k, a in all_articles(rei) for p in HIT_PATTERNS[:4] if re.search(p, text_of(a))})
    return {"articles_now": sorted(arts_now), "m34_expected": sorted(M34_EXPECTED), "same_as_m34": arts_now == M34_EXPECTED,
            "only_found": sorted(arts_now - M34_EXPECTED), "only_m34": sorted(M34_EXPECTED - arts_now),
            "counts_by_asof": counts, "counts_same_across_asof": len({json.dumps(v, sort_keys=True) for v in counts.values()}) == 1,
            "author_hits_set": sorted(author_set), "same_as_author_file": author_set == arts_now, "chiho_rei_articles_now": rei_arts}


def amend_paras_table(lc):
    rows = []
    for asof in (NOW, C27, C28, C30):
        lw = lc.get("chiho", asof)
        for art in ("3", "11"):
            a = article(lw, A2, art)
            rows.append((asof, art, [p["attr"].get("Num") for p in kids(a, "Paragraph")] if a is not None else None))
    return rows


def load_web():
    man = json.loads((OUT / "web_manifest.json").read_text(encoding="utf-8"))
    tx = ROOT / man["text_dir"]
    texts, meta = {}, {}
    for r in man["results"]:
        meta[r["id"]] = r
        if r.get("text"):
            texts[r["id"]] = (tx / r["text"]).read_text(encoding="utf-8")
    return texts, meta, man


def run_web(texts, meta, man):
    res = []
    for cid, doc, claim, kind, args in WEBCHECKS:
        r = {"id": cid, "doc": doc, "claim": claim, "kind": kind}
        sid = args[0]
        if kind == "web":
            ok, miss = has_all(texts.get(sid, ""), args[1])
            r.update({"ok": ok and sid in texts, "missing": miss})
        elif kind == "webnot":
            found = [f for f in args[1] if norm(f) in norm(texts.get(sid, ""))]
            r.update({"ok": sid in texts and not found, "found": found})
        elif kind == "link":
            r.update({"ok": args[1] in (meta.get(sid, {}).get("pdf_links") or []), "got": meta.get(sid, {}).get("pdf_links")})
        elif kind == "sha":
            r.update({"ok": meta.get(sid, {}).get("sha256") == args[1], "got": meta.get(sid, {}).get("sha256")})
        elif kind == "shaprefix":
            r.update({"ok": (meta.get(sid, {}).get("sha256") or "").startswith(args[1]), "got": meta.get(sid, {}).get("sha256")})
        elif kind == "title":
            r.update({"ok": args[1] in (meta.get(sid, {}).get("title") or ""), "got": meta.get(sid, {}).get("title")})
        elif kind == "robots":
            st = (man["robots"].get(sid) or {}).get("status")
            r.update({"ok": st == args[1], "got": st})
        res.append(r)
    return res


def run_files():
    res = []
    for cid, doc, claim, kind, args in FILECHECKS:
        r = {"id": cid, "doc": doc, "claim": claim, "kind": kind}
        try:
            if kind == "errpage":
                p = ROOT / args[0]
                b = p.read_bytes()
                r.update({"ok": len(b) == args[1] and args[2] in b.decode("utf-8", "replace"), "got": len(b)})
            elif kind == "samedirs":
                d1, d2 = ROOT / args[0], ROOT / args[1]
                h1 = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in d1.iterdir() if p.is_file()}
                h2 = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in d2.iterdir() if p.is_file()}
                r.update({"ok": h1 == h2 and len(h1) == 6, "got": {"n1": len(h1), "n2": len(h2), "diff": sorted(k for k in set(h1) | set(h2) if h1.get(k) != h2.get(k))}})
            elif kind == "evidence":
                ev = json.loads((ROOT / args[0]).read_text(encoding="utf-8"))
                r.update({"ok": len(ev) == args[1] and all(e.get("ok") for e in ev), "got": [len(ev), sum(1 for e in ev if e.get("ok"))]})
            elif kind == "mdrows":
                t = (ROOT / args[0]).read_text(encoding="utf-8").splitlines()
                rows = [x for x in t if x.startswith("| ") and x.rstrip().endswith(("| OK |", "| NG |"))]
                r.update({"ok": len(rows) == args[1] and all(x.rstrip().endswith("| OK |") for x in rows), "got": len(rows)})
        except Exception as e:  # noqa: BLE001
            r.update({"ok": False, "error": repr(e)})
        res.append(r)
    return res


# ---------------------------------------------------------------- 再計算（担当の compute とは別に、条文から書いた）
def floor_to(x, unit):
    return (Fr(x) // unit) * unit


def life_new(p):
    """第314条の2①五イ(1)（新契約。介護医療・新個人年金も同じ区分）。"""
    p = Fr(p)
    if p <= 12000:
        return p
    if p <= 32000:
        return 12000 + (p - 12000) / 2
    if p <= 56000:
        return 22000 + (p - 32000) / 4
    return Fr(28000)


def life_old(p):
    """第314条の2①五イ(2)（旧契約）。"""
    p = Fr(p)
    if p <= 15000:
        return p
    if p <= 40000:
        return 15000 + (p - 15000) / 2
    if p <= 70000:
        return 27500 + (p - 40000) / 4
    return Fr(35000)


def jishin(p):
    return min(Fr(p) / 2, Fr(25000))


def kiso_jumin(gokei):
    """第314条の2②。"""
    return 430000 if gokei <= 24000000 else 290000 if gokei <= 24500000 else 150000 if gokei <= 25000000 else 0


def jinteki(f):
    """第314条の6①一イ：5万円＋表の金額。f は該当の数（（７）は令和8・9年度分では当たらないので扱わない）。"""
    T = f["gokei"]
    t = 50000 + 10000 * f.get("shogai", 0) + 100000 * f.get("tokubetsu_shogai", 0) + 220000 * f.get("doukyo_tokubetsu", 0)
    t += 10000 * bool(f.get("kafu_or_father")) + 50000 * bool(f.get("mother")) + 10000 * bool(f.get("kinro"))
    if f.get("spouse") in ("general", "elderly"):
        hi = f["spouse"] == "elderly"
        t += (100000 if hi else 50000) if T <= 9000000 else (60000 if hi else 40000) if T <= 9500000 else (30000 if hi else 20000) if T <= 10000000 else 0
    t += 50000 * f.get("fuyo", 0) + 180000 * f.get("tokutei", 0) + 100000 * f.get("rojin", 0) + 130000 * f.get("doukyo_rojin", 0)
    return t


# 第314条の7⑪一の表を附則第5条の6②で読み替えた割合（令和8・9年度分）と、附則第7条の2⑤の表を附則第7条の3②で読み替えた割合
TOKUREI = [(1950000, Fr(84895, 100000)), (3300000, Fr(7979, 10000)), (6950000, Fr(6958, 10000)), (9000000, Fr(66517, 100000)),
           (18000000, Fr(56307, 100000)), (40000000, Fr(4916, 10000)), (None, Fr(44055, 100000))]
SHINKOKU = [(1950000, Fr(5105, 84895)), (3300000, Fr(1021, 7979)), (6950000, Fr(2042, 6958)), (9000000, Fr(23483, 66517)), (None, Fr(33693, 56307))]


def bracket(table, x):
    for lim, v in table:
        if lim is None or x <= lim:
            return v


def juminzei(p, inj, policy="P0", b_after_onestop=False):
    """一人の令和8・9年度分の個人住民税（所得割・均等割）＋森林環境税。条文の順：314の3 → 314の6 → 税額控除（住宅・寄附金）→ 申告特例 → 附則3の3 → 確定金額の100円未満切捨て。
    policy は担当の P0〜P3 と同じ意味（1円未満の扱いの仮定）。b_after_onestop=True で、附則第3条の3⑤の B・C に申告特例控除の後の額を使う（担当の compute と同じ扱い）。"""
    sh = inj["shitei"]
    taxable = floor_to(max(p["soshotoku"] - p["kojo"], 0), 1000)
    ci, pi = taxable * inj["city_rate"], taxable * inj["pref_rate"]
    if policy != "P0":
        ci, pi = floor_to(ci, 1), floor_to(pi, 1)
    js = jinteki(p)
    if p["gokei"] <= 25000000:
        base = min(js, taxable) if taxable <= 2000000 else max(js - (taxable - 2000000), 50000)
        cc, cp = (base * Fr(4, 100), base * Fr(1, 100)) if sh else (base * Fr(3, 100), base * Fr(2, 100))
    else:
        cc = cp = Fr(0)
    c1, p1 = max(ci - cc, 0), max(pi - cp, 0)

    def rnd(x):
        return floor_to(x, 1) if policy == "P2" else -floor_to(-x, 1) if policy == "P3" else x
    hc = hp = kc = kp = oc = op = Fr(0)
    j = p.get("jutaku")
    if j:
        diff = max(j["shotokuzei_kojo_kano"] - j["shotokuzei_mae"], 0)
        lim_base = j["shotokuzei_kazei"] + (max(p["shotokuzei_kiso"] - 480000, 0) if 2016 <= j["kyojunen"] <= 2025 else 0)
        if j.get("tokubetsu"):
            rc, rp, mc, mp = (Fr(56, 1000), Fr(14, 1000), 109200, 27300) if sh else (Fr(42, 1000), Fr(28, 1000), 81900, 54600)
        else:
            rc, rp, mc, mp = (Fr(4, 100), Fr(1, 100), 78000, 19500) if sh else (Fr(3, 100), Fr(2, 100), 58500, 39000)
        scc, scp = (Fr(4, 5), Fr(1, 5)) if sh else (Fr(3, 5), Fr(2, 5))
        hc, hp = rnd(min(diff * scc, lim_base * rc, mc)), rnd(min(diff * scp, lim_base * rp, mp))
    k = p.get("kifu")
    tc = tp = Fr(0)
    x = None
    if k:
        tot = min(Fr(k["total"]), Fr(p["soshotoku_tou"]) * Fr(30, 100))
        if tot > 2000:
            bc, bp = ((tot - 2000) * Fr(8, 100), (tot - 2000) * Fr(2, 100)) if sh else ((tot - 2000) * Fr(6, 100), (tot - 2000) * Fr(4, 100))
            if k.get("tokurei", 0) > 2000:
                x = taxable - (js + max(p["shotokuzei_kiso"] - 480000, 0))
                r = Fr(90, 100) if x < 0 else bracket(TOKUREI, x)
                scc, scp = (Fr(4, 5), Fr(1, 5)) if sh else (Fr(3, 5), Fr(2, 5))
                tc, tp = min((k["tokurei"] - 2000) * r * scc, c1 * Fr(20, 100)), min((k["tokurei"] - 2000) * r * scp, p1 * Fr(20, 100))
            kc, kp = rnd(min(bc + tc, c1)), rnd(min(bp + tp, p1))
            if k.get("onestop") and tc:
                ratio = bracket(SHINKOKU, max(x, 0))  # 区分の基準が負のときの扱いは一次情報で決まらない（担当と同じく最初の行）
                oc, op = rnd(tc * ratio), rnd(tp * ratio)
    B, C = max(c1 - hc - kc, 0), max(p1 - hp - kp, 0)          # 附則第3条の3⑤二・三（申告特例控除を含まない）
    fc, fp = max(c1 - hc - kc - oc, 0), max(p1 - hp - kp - op, 0)
    if b_after_onestop:
        B, C = fc, fp
    n = p.get("n_fuyo", 0)
    Lm = 350000 * (n + 1) + 100000 + (320000 if n else 0)
    A_ = p["soshotoku_tou"]
    adj = (Fr(0), Fr(0))
    if A_ <= Lm:
        fc = fp = Fr(0)
    elif B + C > 0 and Lm > A_ - (B + C):
        ex = Lm - (A_ - (B + C))
        adj = (ex * B / (B + C), ex * C / (B + C))
        fc, fp = max(fc - adj[0], 0), max(fp - adj[1], 0)
    tcity, tpref = floor_to(fc + inj["city_kinto"], 100), floor_to(fp + inj["pref_kinto"], 100)
    return {"taxable": taxable, "city_sanshutsu": ci, "pref_sanshutsu": pi, "jinteki": js, "chosei": (cc, cp), "jutaku": (hc, hp), "kifu": (kc, kp),
            "onestop": (oc, op), "x": x, "nonkazei_adj": adj, "city_shotokuwari": fc, "pref_shotokuwari": fp,
            "city": int(tcity), "pref": int(tpref), "total": int(tcity + tpref + inj["shinrin"])}


def fr(v):
    if isinstance(v, tuple):
        return [fr(x) for x in v]
    if isinstance(v, Fr):
        return str(v.numerator) if v.denominator == 1 else f"{v.numerator}/{v.denominator}≈{float(v):.4f}"
    return v


def kan_dec(s):
    """「八十四・八九五」「五十九・三七」「九十」などの漢数字（小数点つき）を Fraction にする。"""
    d = dict(zip("〇一二三四五六七八九", range(10)))
    ip, _, fp = s.partition("・")
    v, cur = 0, 0
    for ch in ip:
        if ch in d:
            cur = d[ch]
        elif ch == "十":
            v, cur = v + (cur or 1) * 10, 0
        elif ch == "百":
            v, cur = v + (cur or 1) * 100, 0
    v += cur
    return Fr(v) + sum((Fr(d[ch], 10 ** (i + 1)) for i, ch in enumerate(fp)), Fr(0))


def run_calc(lc):
    out = {}
    author = json.loads((AUTHOR / "R2X_juminzei-tax_calc" / "summary.json").read_text(encoding="utf-8"))
    aex = {e["name"]: e["result"] for e in author["examples"]}
    # ---- 名古屋市（令和8年度）
    kojo = Fr(825600) + life_old(80000) + 330000 + 450000 + 330000 + kiso_jumin(3963200)
    p = {"gokei": 3963200, "soshotoku": 3963200, "soshotoku_tou": 3963200, "kojo": kojo, "spouse": "general", "tokutei": 1, "fuyo": 1, "n_fuyo": 4}
    inj = {"shitei": True, "city_rate": Fr(77, 1000), "pref_rate": Fr(2, 100), "city_kinto": 2800, "pref_kinto": 1500, "shinrin": 1000}
    r = juminzei(p, inj)
    out["nagoya"] = {"kojo": fr(kojo), "life_old_80000": fr(life_old(80000)), "result": {k: fr(v) for k, v in r.items()},
                     "page": {"kojo": 2400600, "taxable": 1562000, "city": 109800, "pref": 29400, "total": 140200, "jinteki": 330000, "chosei": [13200, 3300]},
                     "ok": kojo == 2400600 and r["taxable"] == 1562000 and r["city"] == 109800 and r["pref"] == 29400 and r["total"] == 140200 and r["jinteki"] == 330000
                     and r["chosei"] == (13200, 3300) and r["city_sanshutsu"] == 120274 and r["pref_sanshutsu"] == 31240,
                     "same_as_author": aex.get("名古屋市 令和8年度") == {"city": r["city"], "pref": r["pref"], "total": r["total"]}}
    # ---- 横浜市（令和8年度）
    kojo = Fr(394800) + life_new(90000) + jishin(20000) + 330000 + 330000 + kiso_jumin(3960000)
    p = {"gokei": 3960000, "soshotoku": 3960000, "soshotoku_tou": 3960000, "kojo": kojo, "spouse": "general", "fuyo": 1, "n_fuyo": 3}
    inj = {"shitei": True, "city_rate": Fr(8, 100), "pref_rate": Fr(2025, 100000), "city_kinto": 3900, "pref_kinto": 1300, "shinrin": 1000}
    r0, r1 = juminzei(p, inj, "P0"), juminzei(p, inj, "P1")
    out["yokohama"] = {"kojo": fr(kojo), "P0": {k: fr(v) for k, v in r0.items()}, "P1": {k: fr(v) for k, v in r1.items()},
                       "ok": kojo == 1522800 and r1["taxable"] == 2437000 and r1["city_sanshutsu"] == 194960 and r1["pref_sanshutsu"] == 49349 and r0["pref_sanshutsu"] == Fr(4934925, 100)
                       and r1["chosei"] == (2000, 500) and floor_to(r1["city_shotokuwari"], 100) == 192900 and floor_to(r1["pref_shotokuwari"], 100) == 48800
                       and r0["total"] == 247900 and r1["total"] == 247900,
                       "same_as_author": aex.get("横浜市 令和8年度") == {"city": r1["city"], "pref": r1["pref"], "total": r1["total"]}}
    # ---- 仮の例 A・B・C（担当の M §3.7。標準税率・標準の均等割を注入した仮の入力）
    std = {"shitei": False, "city_rate": Fr(6, 100), "pref_rate": Fr(4, 100), "city_kinto": 3000, "pref_kinto": 1000, "shinrin": 1000}
    pa = {"gokei": 4000000, "soshotoku": 4000000, "soshotoku_tou": 4000000, "kojo": 1030000, "n_fuyo": 0, "shotokuzei_kiso": 1040000,
          "kifu": {"total": 50000, "tokurei": 50000, "onestop": True}}
    ra = juminzei(pa, std)
    kifu_sum = ra["kifu"][0] + ra["kifu"][1] + ra["onestop"][0] + ra["onestop"][1]
    out["exampleA"] = {"result": {k: fr(v) for k, v in ra.items()}, "kifu_total": fr(kifu_sum), "ok": kifu_sum == 48000 and ra["taxable"] == 2970000 and ra["x"] == 2360000,
                       "jinteki_chosei_gaku": 50000 + (1040000 - 480000), "same_as_author": aex.get("仮の例A") == {"city": ra["city"], "pref": ra["pref"], "total": ra["total"]}}
    pb = {"gokei": 3000000, "soshotoku": 3000000, "soshotoku_tou": 3000000, "kojo": 1210000, "spouse": "general", "n_fuyo": 1, "shotokuzei_kiso": 1040000,
          "jutaku": {"shotokuzei_kojo_kano": 140000, "shotokuzei_mae": 30000, "shotokuzei_kazei": 690000, "kyojunen": 2023}}
    rb = juminzei(pb, std)
    out["exampleB"] = {"result": {k: fr(v) for k, v in rb.items()}, "ok": rb["jutaku"] == (37500, 25000),
                       "same_as_author": aex.get("仮の例B") == {"city": rb["city"], "pref": rb["pref"], "total": rb["total"]}}
    pc = {"gokei": 451000, "soshotoku": 451000, "soshotoku_tou": 451000, "kojo": 430000, "n_fuyo": 0}
    rc = juminzei(pc, std)
    out["exampleC"] = {"result": {k: fr(v) for k, v in rc.items()}, "ok": rc["nonkazei_adj"] == (30, 20) and rc["city_shotokuwari"] == 600 and rc["pref_shotokuwari"] == 400,
                       "same_as_author": aex.get("仮の例C") == {"city": rc["city"], "pref": rc["pref"], "total": rc["total"]}}
    # ---- 率の恒等式（条文から読替えを取り出して確かめる）
    t56 = text_of(locate(article(lc.get("chiho", NOW), "orig", "5_6"), "2"))
    pairs = re.findall(r"「百分の([〇一二三四五六七八九十百・]+)」とあるのは「百分の([〇一二三四五六七八九十百・]+)」", t56)
    id56 = [(fr(kan_dec(a)), fr(kan_dec(b)), 90 - (90 - kan_dec(a)) * Fr(1021, 1000) == kan_dec(b)) for a, b in pairs]
    t56_28 = text_of(locate(article(lc.get("chiho", C28), "orig", "5_6"), "4"))
    pairs28 = re.findall(r"「百分の([〇一二三四五六七八九十百・]+)」とあるのは「百分の([〇一二三四五六七八九十百・]+)」", t56_28)
    id56_28 = [(fr(kan_dec(a)), fr(kan_dec(b)), 90 - (90 - kan_dec(a)) * Fr(101, 100) == kan_dec(b)) for a, b in pairs28]
    t73 = text_of(locate(article(lc.get("chiho", NOW), "orig", "7_3"), "2"))
    p73 = re.findall(r"「([〇一二三四五六七八九十・]+)分の([〇一二三四五六七八九十・]+)」とあるのは「([〇一二三四五六七八九十・]+)分の([〇一二三四五六七八九十・]+)」", t73)
    rates56 = {kan_dec(b) for _, b in pairs}
    id73 = [(f"{fr(kan_dec(n0))}/{fr(kan_dec(d0))}", f"{fr(kan_dec(n1))}/{fr(kan_dec(d1))}", kan_dec(n1) + kan_dec(d1) == 90, kan_dec(d1) in rates56) for d0, n0, d1, n1 in p73]
    # ワンストップ：314の7 の 7 区分それぞれで（基本10%＋特例 r'＋申告特例 r'×a/b）。申告特例の表は 900万円超を一つの区分にしている
    onestop = []
    for lim, r_ in TOKUREI:
        xx = (lim or 50000000)
        ab = bracket(SHINKOKU, xx)
        onestop.append({"区分の上限": lim, "r2": fr(r_), "a/b": fr(ab), "合計": fr(Fr(10, 100) + r_ * (1 + ab))})
    kakutei = [{"t": t_, "r2": fr(r_), "合計": fr(Fr(t_, 100) * Fr(1021, 1000) + Fr(10, 100) + r_)} for t_, (_, r_) in zip([5, 10, 20, 23, 33, 40, 45], TOKUREI)]
    out["identities"] = {"5_6_now": id56, "5_6_now_all_ok": all(x[2] for x in id56) and len(id56) == 10, "5_6_2028_r31": id56_28,
                         "5_6_2028_all_ok": all(x[2] for x in id56_28) and len(id56_28) == 10, "7_3": id73, "7_3_all_ok": all(x[2] and x[3] for x in id73) and len(id73) == 5,
                         "onestop_by_7_brackets": onestop, "kakutei": kakutei}
    # ---- 調整控除の表の（７）が当たる配偶者の合計所得金額（1円刻み）
    reach = {}
    for label, X in (("令和7年度分", 480000), ("令和8年度分", 580000), ("令和9年度分", 620000)):
        hits = []
        for s in range(0, 1340001):
            for T in (0, 9000000, 9500000, 10000000, 10000001):
                douitsu = s <= X                                   # 青色事業専従者等ではない配偶者
                kojo_taisho = douitsu and T <= 10000000
                tokubetsu = s <= 1330000 and not kojo_taisho and T <= 10000000
                if tokubetsu and s < 550000:
                    hits.append(s)
                    break
        reach[label] = {"X": X, "n_s": len(hits), "min": min(hits) if hits else None, "max": max(hits) if hits else None}
    out["reachability"] = reach
    # ---- 配偶者特別控除（住民税）の区間を1円刻みで（担当の表と比べる）
    def base(s):
        if s <= 1000000:
            return 330000
        if s <= 1300000:
            ex = s - 930001
            v = 50000 * ((ex + 30000) // 50000) - 30000
            return 380000 - v
        if s <= 1330000:
            return 30000
        return 0

    def ceil10k(x):
        return int(-((-x) // 10000) * 10000)
    tables = {}
    for label, lo in (("令和8年度分", 580001), ("令和9年度分", 620001)):
        rows, prev, start = [], None, lo
        for s in range(lo, 1330002):
            b = base(s)
            cur = (b, ceil10k(Fr(b * 2, 3)), ceil10k(Fr(b, 3)))
            if prev is not None and cur != prev:
                rows.append((start, s - 1) + prev)
                start = s
            prev = cur
        rows.append((start, None) + prev)
        tables[label] = rows
    at = (AUTHOR / "R2X_juminzei-tax_calc" / "haigusha_tokubetsu.md").read_text(encoding="utf-8")
    arows = []
    for line in at.splitlines():
        m = re.match(r"\| ([\d,]+)〜([\d,]*) \| ([\d,]+) \| ([\d,]+) \| ([\d,]+) \|", line)
        if m:
            g = [int(x.replace(",", "")) if x else None for x in m.groups()]
            arows.append(tuple(g))
    mine = tables["令和8年度分"] + tables["令和9年度分"]
    out["haigusha"] = {"tables": tables, "same_as_author": [tuple(x) for x in mine] == arows, "n_rows": len(mine), "n_author_rows": len(arows)}
    # ---- 1円未満の扱いの感度（担当の入力の作り方を写し、計算は上の juminzei で行う）
    rng = random.Random(20261109)
    rates = [(Fr(6, 100), Fr(4, 100), False), (Fr(8, 100), Fr(2, 100), True), (Fr(61, 1000), Fr(4, 100), False), (Fr(77, 1000), Fr(2, 100), True),
             (Fr(8, 100), Fr(2025, 100000), True), (Fr(6, 100), Fr(4025, 100000), False)]
    N = 20000
    res = {False: {"P1": [0, 0], "P2": [0, 0], "P3": [0, 0]}, True: {"P1": [0, 0], "P2": [0, 0], "P3": [0, 0]}}
    b_diff = 0
    for _ in range(N):
        cr, pr, sh = rng.choice(rates)
        so = rng.randrange(500000, 20000000)
        kojo = rng.randrange(430000, min(so, 3000000) + 430001)
        p = {"gokei": so, "soshotoku": so, "soshotoku_tou": so, "kojo": kojo}
        p["n_fuyo"] = rng.choice([0, 0, 1, 2])
        p["spouse"] = rng.choice([None, "general"])
        p["fuyo"] = rng.choice([0, 1])
        p["shotokuzei_kiso"] = rng.choice([580000, 630000, 680000, 880000, 950000, 1040000])
        if rng.random() < 0.6:
            t = rng.randrange(3000, 400000)
            tok = t if rng.random() < 0.8 else 0
            p["kifu"] = {"total": t, "tokurei": tok, "onestop": rng.random() < 0.5}
        if rng.random() < 0.3:
            kk = rng.randrange(10000, 350000)
            mm = rng.randrange(0, 300000)
            p["jutaku"] = {"shotokuzei_kojo_kano": kk, "shotokuzei_mae": mm, "shotokuzei_kazei": max(so - kojo - 300000, 0), "kyojunen": rng.choice([2019, 2022, 2024, 2025])}
        inj = {"shitei": sh, "city_rate": cr, "pref_rate": pr, "city_kinto": 3000, "pref_kinto": 1000, "shinrin": 1000}
        for flag in (False, True):
            b0 = juminzei(p, inj, "P0", flag)["total"]
            for pol in ("P1", "P2", "P3"):
                d = abs(juminzei(p, inj, pol, flag)["total"] - b0)
                if d:
                    res[flag][pol][0] += 1
                    res[flag][pol][1] = max(res[flag][pol][1], d)
        if juminzei(p, inj, "P0", False)["total"] != juminzei(p, inj, "P0", True)["total"]:
            b_diff += 1
    out["rounding"] = {"law_B_C_without_onestop": res[False], "author_like_B_C_after_onestop": res[True],
                       "author": {"diff": author["rounding_diff"], "max": author["rounding_maxdiff"]},
                       "author_reproduced": all(res[True][k] == [author["rounding_diff"][k], author["rounding_maxdiff"][k]] for k in ("P1", "P2", "P3")),
                       "P0_total_differs_by_B_definition": b_diff, "N": N}
    return out


# ---------------------------------------------------------------- 出力
def write_outputs(chk, web, files, hits, amend, calc, recs_man, web_man):
    allr = chk + web + files
    md = ["# R2X_juminzei-tax_verify の照合結果", "",
          f"- e-Gov の取得：{', '.join(r['run_at'] + '（' + r['download_dir'] + '）' for r in recs_man['runs'])}",
          f"- 行政の資料の取得：{web_man['run_at']}（{web_man['download_dir']}）", "",
          f"項目 {len(allr)} 件、一致 {sum(1 for r in allr if r.get('ok'))} 件、不一致 {sum(1 for r in allr if not r.get('ok'))} 件。", "",
          "| ID | 文書 | 主張 | 結果 | 補足 |", "|---|---|---|---|---|"]
    for r in allr:
        extra = ""
        if not r.get("ok"):
            extra = json.dumps({k: r[k] for k in ("missing", "found", "why", "got", "error", "lengths", "where") if k in r}, ensure_ascii=False)[:500]
        elif r["kind"] in ("rev", "amendparas", "diffunits", "grepcount", "robots"):
            extra = json.dumps(r.get("got"), ensure_ascii=False)[:200]
        md.append(f"| {r['id']} | {r['doc']} | {r['claim']} | {'一致' if r.get('ok') else '**不一致**'} | {extra.replace('|', '¦')} |")
    md += ["", "## 全文の語の出現（M §3.4 の照合）", "",
           f"- 地方税法 asof 2026-11-09 の本則・原始附則で、端数・切上げ・制限税率の語が現れる条：{hits['articles_now']}",
           f"- M §3.4 の列挙と同じか：{hits['same_as_m34']}（M にだけあるもの {hits['only_m34']}、ここでだけ見つかったもの {hits['only_found']}）",
           f"- 担当の hits_chiho_2026-11-09.json の条の集合と同じか：{hits['same_as_author_file']}",
           f"- パターンごとの件数（版ごと）：{json.dumps(hits['counts_by_asof'], ensure_ascii=False)}、版の間で同じか：{hits['counts_same_across_asof']}",
           f"- 地方税法施行令 asof 2026-11-09 で同じ語（制限税率を除く）が現れる条：{hits['chiho_rei_articles_now']}", ""]
    (OUT / "checks.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (OUT / "checks.json").write_text(json.dumps({"checks": allr, "hits": hits}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    am = ["# 令和8年法律第2号の改正附則（第3条・第11条）が e-Gov の版ごとにどの項まで見えるか", "", "| asof | 条 | 見える項 |", "|---|---|---|"]
    am += [f"| {a} | 第{art}条 | {', '.join(ps) if ps else '（なし）'} |" for a, art, ps in amend]
    (OUT / "amend_paras.md").write_text("\n".join(am) + "\n", encoding="utf-8")
    cm = ["# R2X_juminzei-tax_verify の再計算", "", "計算は fractions.Fraction で行った（担当の compute() は import していない）。", ""]
    for k in ("nagoya", "yokohama", "exampleA", "exampleB", "exampleC"):
        cm.append(f"## {k}：条文・ページとの一致 {calc[k]['ok']}、担当の summary.json と同じ {calc[k]['same_as_author']}")
        cm.append("")
        cm.append("```")
        cm.append(json.dumps({kk: vv for kk, vv in calc[k].items() if kk not in ("ok", "same_as_author")}, ensure_ascii=False, indent=1))
        cm.append("```")
        cm.append("")
    idn = calc["identities"]
    cm += ["## 率の恒等式", "", f"- 附則第5条の6②（asof 2026-11-09）：r' = 90 − (90 − r)×1.021 が10組すべて成り立つ：{idn['5_6_now_all_ok']}",
           f"- 附則第5条の6④（asof 2028-01-01、令和31年度以後）：r' = 90 − (90 − r)×1.01 が10組すべて成り立つ：{idn['5_6_2028_all_ok']}",
           f"- 附則第7条の3②：a + b = 90 かつ b が附則第5条の6の読替え後の割合、5組すべて：{idn['7_3_all_ok']}", "",
           "### ワンストップ（申告特例）のときの住民税の寄附金関係の控除の合計（(寄附金−2,000円) に対する割合。第314条の7⑪の7区分ごと）", "",
           "| 区分の上限（課税総所得金額−人的控除差調整額） | r' | 申告特例の割合 a/b | 合計 |", "|---|---|---|---|"]
    cm += [f"| {o['区分の上限']} | {o['r2']} | {o['a/b']} | {o['合計']} |" for o in idn["onestop_by_7_brackets"]]
    cm += ["", "### 確定申告のとき（所得税の (寄附金−2,000)×t×1.021 ＋ 住民税 10%＋r'）", "", "| t | r' | 合計 |", "|---|---|---|"]
    cm += [f"| {o['t']}% | {o['r2']} | {o['合計']} |" for o in idn["kakutei"]]
    cm += ["", "## 調整控除の表の（７）が当たる配偶者の合計所得金額（1円刻み、納税義務者 0・900万・950万・1,000万・1,000万1円）", ""]
    cm += [f"- {k}（同一生計配偶者の上限 {v['X']:,}円）：当たる s の数 {v['n_s']}、範囲 {v['min']}〜{v['max']}" for k, v in calc["reachability"].items()]
    cm += ["", f"## 配偶者特別控除（住民税）の区間：担当の haigusha_tokubetsu.md と同じ {calc['haigusha']['same_as_author']}（{calc['haigusha']['n_rows']} 行／担当 {calc['haigusha']['n_author_rows']} 行）", ""]
    for label, rows in calc["haigusha"]["tables"].items():
        cm += [f"### {label}", "", "| 配偶者の合計所得金額 | 900万円以下 | 900万超950万以下 | 950万超1,000万以下 |", "|---|---|---|---|"]
        cm += [f"| {a:,}〜{'' if b is None else format(b, ',')} | {x:,} | {y:,} | {z:,} |" for a, b, x, y, z in rows]
        cm.append("")
    ro = calc["rounding"]
    cm += ["## 1円未満の扱いの感度（担当と同じ入力の作り方、乱数の種 20261109、20,000件）", "",
           "| 方式 | 附則3の3⑤の B・C を条文どおり（申告特例の前） 件数・最大差 | 担当と同じ（申告特例の後） 件数・最大差 | 担当の記録 |", "|---|---|---|---|"]
    for k in ("P1", "P2", "P3"):
        cm.append(f"| {k} | {ro['law_B_C_without_onestop'][k]} | {ro['author_like_B_C_after_onestop'][k]} | {[ro['author']['diff'][k], ro['author']['max'][k]]} |")
    cm += ["", f"- 担当の数字を再現できたか（担当と同じ扱い）：{ro['author_reproduced']}",
           f"- B・C の定義の違いで P0 の年税額が変わった件数：{ro['P0_total_differs_by_B_definition']} / {ro['N']}", ""]
    (OUT / "calc.md").write_text("\n".join(cm) + "\n", encoding="utf-8")
    (OUT / "calc.json").write_text(json.dumps(calc, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def cmd_check():
    recs, man = latest_fetches()
    lc = LawCache(recs)
    chk = run_checks(lc)
    hits = run_hits(lc)
    amend = amend_paras_table(lc)
    texts, meta, wman = load_web()
    web = run_web(texts, meta, wman)
    files = run_files()
    calc = run_calc(lc)
    write_outputs(chk, web, files, hits, amend, calc, man, wman)
    allr = chk + web + files
    for r in allr:
        if not r.get("ok"):
            print("NG", r["id"], r["claim"], {k: r[k] for k in ("missing", "found", "why", "got", "error", "where") if k in r})
    print("checks:", len(allr), "ok:", sum(1 for r in allr if r.get("ok")))
    print("hits same_as_m34:", hits["same_as_m34"], "only_found:", hits["only_found"], "only_m34:", hits["only_m34"], "same_as_author_file:", hits["same_as_author_file"])
    print("calc:", {k: (calc[k]["ok"], calc[k]["same_as_author"]) for k in ("nagoya", "yokohama", "exampleA", "exampleB", "exampleC")})
    print("reach:", calc["reachability"])
    print("haigusha same:", calc["haigusha"]["same_as_author"], "identities:", {k: v for k, v in calc["identities"].items() if k.endswith("ok")})
    print("rounding:", json.dumps(calc["rounding"], ensure_ascii=False))


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")
    cmd = argv[0] if argv else ""
    if cmd == "egov":
        cmd_egov(set(argv[1:]) or None)
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


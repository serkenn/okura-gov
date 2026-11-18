"""IMPL_iryohi_verify: 医療費控除・セルフメディケーション税制のトピック（iryohi）の文書を、独立に一次情報へ当たり直して検証する。

実行（Windows では pyenv のシムを通さずに実体の python.exe を使う。カレントディレクトリはリポジトリの根）:
  PY=C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe
  $PY -I -X utf8 scripts/IMPL_iryohi_verify.py egov-fetch                # e-Gov 法令API v2 から本文を取得（新しい空のディレクトリへ）
  $PY -I -X utf8 scripts/IMPL_iryohi_verify.py egov-check <dlディレクトリ> # 取得した本文で条文の主張を検査
  $PY -I -X utf8 scripts/IMPL_iryohi_verify.py web-fetch                 # 国税庁・厚生労働省のページを取得（新しい空のディレクトリへ）
  $PY -I -X utf8 scripts/IMPL_iryohi_verify.py web-check <dlディレクトリ>  # 取得したページで文言の主張を検査
  $PY -I -X utf8 scripts/IMPL_iryohi_verify.py xlsx <xlsxのパス>...      # 医療費集計フォームを展開せずに読む
  $PY -I -X utf8 scripts/IMPL_iryohi_verify.py calc                      # 推測・仮説の計算を再計算

- 担当の書いたスクリプト（scripts/IMPL_iryohi_*.py）は import も実行もしない。e-Gov の使い方は
  scripts/R1_egov_articles.py と scripts/R4_fetch_laws.py を読んで、必要な部分だけを書き直した。
- ダウンロードしたもの（JSON・HTML・PDF・xlsx）は信頼できないデータ。取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_IMPL_iryohi_verify_<set>/ に置き、その中でインタプリタやツールを実行しない。
  読むときはパスを引数で渡し、json.loads / html.parser / zipfile（メモリ上）で読むだけ。
- 取得は GET だけ。リクエストの間は 1.5 秒。User-Agent は okura-gov-research/0.1。Cookie は送らない。
  許可したホスト（laws.e-gov.go.jp、www.nta.go.jp、www.mhlw.go.jp）以外へのリダイレクトは止める。官報は取得しない。
- 出力は scripts/results/IMPL_iryohi_verify/ に書く。HTML から抜き出したテキスト（ページの写し）はリポジトリの外の
  .work/text/<ダウンロードのディレクトリ名>/ に置く。
- PDF（様式・記載要領・手引き・厚生労働省の資料）の中身はこのスクリプトでは読まない。取得した同じファイル（SHA-256 は
  web_fetch_log_*.json）を Claude Code の Read ツールで読み、読んだ内容は実測の文書 docs/measurements/20261109_impl-prep_iryohi-verification.md §1.4 に書いた。
標準ライブラリのみ（Python 3.11）。
"""
import hashlib
import html.parser
import io
import json
import pathlib
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from fractions import Fraction
from xml.etree import ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "results" / "IMPL_iryohi_verify"
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
WAIT = 1.5
TODAY = "2026-11-09"
ALLOWED_HOSTS = {"laws.e-gov.go.jp", "www.nta.go.jp", "www.mhlw.go.jp"}


# ---------------------------------------------------------------- 取得（共通）
class NoForeignRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = urllib.parse.urlsplit(newurl).hostname
        if host not in ALLOWED_HOSTS:
            raise urllib.error.HTTPError(newurl, code, f"redirect to non-allowed host {host}", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(NoForeignRedirect)


def get(url, accept="*/*"):
    host = urllib.parse.urlsplit(url).hostname
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"host not allowed: {host}")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    meta = {"url": url}
    try:
        with OPENER.open(req, timeout=300) as r:
            body = r.read()
            meta.update(status=r.status, final_url=r.geturl(), content_type=r.headers.get("Content-Type"),
                        last_modified=r.headers.get("Last-Modified"))
    except urllib.error.HTTPError as e:
        body = e.read() if e.fp else b""
        meta.update(status=e.code, final_url=url, content_type=e.headers.get("Content-Type") if e.headers else None,
                    last_modified=None)
    time.sleep(WAIT)
    meta["bytes"] = len(body)
    meta["sha256"] = hashlib.sha256(body).hexdigest()
    return meta, body


def new_dl_dir(name):
    ts = time.strftime("%Y%m%d-%H%M%S")
    d = ROOT / ".work" / "downloads" / f"{ts}_IMPL_iryohi_verify_{name}"
    d.mkdir(parents=True, exist_ok=False)
    return ts, d


# ---------------------------------------------------------------- e-Gov
# (略称, law_id, asof のリスト)
LAWS = [
    ("shotoku", "340AC0000000033", ["2025-12-31", "2026-11-09", "2026-12-31", "2027-01-01"]),
    ("shotoku-rei", "340CO0000000096", ["2025-12-31", "2026-11-09", "2026-12-31", "2027-01-01"]),
    ("shotoku-ki", "340M50000040011", ["2025-12-31", "2026-11-09", "2026-12-31", "2027-01-01"]),
    ("sochi", "332AC0000000026", ["2025-12-31", "2026-11-09", "2026-12-31", "2027-01-01"]),
    ("sochi-rei", "332CO0000000043", ["2025-12-31", "2026-11-09", "2026-12-31", "2027-01-01"]),
    ("sochi-ki", "332M50000040015", ["2025-12-31", "2026-11-09", "2026-12-31", "2027-01-01"]),
    ("kenpo", "211AC0000000070", ["2026-11-09"]),
    ("minpo", "129AC0000000089", ["2026-11-09"]),
]
LAW_TITLES = ["所得税法", "所得税法施行令", "所得税法施行規則", "租税特別措置法", "租税特別措置法施行令", "租税特別措置法施行規則"]


def egov_fetch():
    ts, dl = new_dl_dir("egov")
    OUT.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "searches": [], "fetches": []}
    for i, title in enumerate(LAW_TITLES):
        q = urllib.parse.urlencode({"law_title": title, "response_format": "json", "asof": TODAY})
        meta, body = get(f"{API}/laws?{q}", "application/json")
        (dl / f"search_{i:02d}.json").write_bytes(body)
        hits = []
        if meta["status"] == 200:
            for law in json.loads(body).get("laws", []):
                rv = law.get("current_revision_info") or law.get("revision_info") or {}
                if rv.get("law_title") == title:
                    hits.append({"law_id": law["law_info"]["law_id"], "law_num": law["law_info"].get("law_num")})
        log["searches"].append({"title": title, "status": meta["status"], "exact_title_hits": hits})
        print("search", title, hits, flush=True)
    for short, law_id, asofs in LAWS:
        for asof in asofs:
            url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
            meta, body = get(url, "application/json")
            fn = f"{short}_{asof}.json"
            (dl / fn).write_bytes(body)
            rec = dict(meta, short=short, law_id=law_id, asof=asof, file=fn)
            if meta["status"] == 200:
                ri = json.loads(body).get("revision_info") or {}
                for k in ("law_title", "law_revision_id", "amendment_law_num", "amendment_law_title",
                          "amendment_enforcement_date", "amendment_promulgate_date", "current_revision_status", "updated"):
                    rec[k] = ri.get(k)
            log["fetches"].append(rec)
            print(short, asof, meta["status"], rec.get("law_revision_id"), rec.get("current_revision_status"), flush=True)
    (OUT / f"egov_fetch_log_{ts}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("download_dir", dl)


def text_of(n):
    if isinstance(n, str):
        return n
    if not isinstance(n, dict) or n.get("tag") == "Rt":
        return ""
    return "".join(text_of(c) for c in n.get("children", []))


def kids(n, tag=None):
    return [c for c in n.get("children", []) if isinstance(c, dict) and (tag is None or c.get("tag") == tag)]


def walk(n, fn, path=()):
    if isinstance(n, dict):
        fn(n, path)
        for c in n.get("children", []):
            walk(c, fn, path + (n.get("tag"),))


class Law:
    def __init__(self, path):
        d = json.loads(pathlib.Path(path).read_bytes())
        self.ri = d.get("revision_info") or {}
        self.root = d["law_full_text"]
        self.main = {}
        self.suppl = []
        mains, suppl = [], []

        def collect(n, p):
            if n.get("tag") == "Article" and "SupplProvision" not in p:
                mains.append(n)
            if n.get("tag") == "SupplProvision":
                suppl.append(n)
        walk(self.root, collect)
        for a in mains:
            self.main.setdefault(a.get("attr", {}).get("Num"), a)
        self.suppl = suppl

    def article(self, num):
        return self.main.get(num)

    def suppl_article(self, amend_re, num):
        out = []
        for s in self.suppl:
            an = s.get("attr", {}).get("AmendLawNum", "(原始附則)")
            if re.search(amend_re, an):
                arts = []
                walk(s, lambda n, p: arts.append(n) if n.get("tag") == "Article" else None)
                for a in arts:
                    if a.get("attr", {}).get("Num") == num:
                        out.append((an, a))
        return out


def para(art, pnum):
    for p in kids(art, "Paragraph"):
        if p.get("attr", {}).get("Num") == str(pnum):
            return p
    return None


def item(node, inum, tag="Item"):
    for c in kids(node, tag):
        if c.get("attr", {}).get("Num") == str(inum):
            return c
    return None


def caption(art):
    c = kids(art, "ArticleCaption")
    return text_of(c[0]) if c else ""


def struct_lines(n, prefix, out):
    """項・号・イロハの番号（Num 属性）をはっきり書いたテキストにする。"""
    tag = n.get("tag", "")
    if tag == "Article":
        out.append(f"{prefix} {caption(n)}")
        for p in kids(n, "Paragraph"):
            struct_lines(p, f"{prefix}-{p.get('attr', {}).get('Num')}", out)
        return
    if tag == "Paragraph" or re.fullmatch(r"Item|Subitem\d+", tag):
        sent = [c for c in kids(n) if c.get("tag", "").endswith("Sentence")]
        out.append(f"{prefix}\t" + "　".join(text_of(s) for s in sent))
        for c in kids(n):
            t = c.get("tag", "")
            if re.fullmatch(r"Item|Subitem\d+", t):
                struct_lines(c, f"{prefix}-{c.get('attr', {}).get('Num')}", out)
            elif t in ("TableStruct", "List"):
                out.append(f"{prefix}\t[表/List]{text_of(c)}")
        return


def norm(s):
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s+", "", s)
    return s


def egov_check(dl):
    dl = pathlib.Path(dl)
    OUT.mkdir(parents=True, exist_ok=True)
    laws = {}
    for short, law_id, asofs in LAWS:
        for asof in asofs:
            p = dl / f"{short}_{asof}.json"
            if p.exists():
                laws[(short, asof)] = Law(p)
    res = {"download_dir": str(dl), "versions": {}, "checks": [], "article_hash": {}, "dumps": []}
    for (short, asof), L in laws.items():
        res["versions"][f"{short}@{asof}"] = {k: L.ri.get(k) for k in (
            "law_revision_id", "current_revision_status", "amendment_law_num", "amendment_enforcement_date")}

    def chk(cid, short, asof, getter, needles, absent=()):
        L = laws.get((short, asof))
        node = getter(L) if L else None
        t = norm(text_of(node)) if node is not None else None
        if not needles and not absent:
            # 期待：その項・号が存在しない（「第N号はない」の確認）
            res["checks"].append({"id": cid, "law": short, "asof": asof, "ok": node is None, "expect": "absent", "node_found": node is not None})
            return
        ok = t is not None and all(norm(x) in t for x in needles) and not any(norm(x) in t for x in absent)
        miss = [x for x in needles if t is None or norm(x) not in t]
        bad = [x for x in absent if t is not None and norm(x) in t]
        res["checks"].append({"id": cid, "law": short, "asof": asof, "ok": ok, "node_found": node is not None,
                              "missing": miss, "unexpected": bad})

    A = lambda num: (lambda L: L.article(num))
    P = lambda num, p: (lambda L: para(L.article(num), p) if L.article(num) else None)
    I = lambda num, p, i: (lambda L: item(para(L.article(num), p), i) if L.article(num) and para(L.article(num), p) else None)

    # ---- 構造つきのダンプ（人が読んで照合する用）
    dump_targets = {
        "shotoku": ["2", "22", "73", "87", "102", "120"], "shotoku-rei": ["207", "258", "262"],
        "shotoku-ki": ["40_3", "47_2"],
        "sochi": ["8_4", "28_4", "31", "32", "37_10", "37_11", "41_14", "41_17"],
        "sochi-rei": ["26_27_3", "26_27_2"], "sochi-ki": ["19_10_2_2", "19_10_2"],
        "kenpo": ["87", "97", "99", "101", "102", "110", "112", "114", "115", "115_2"], "minpo": ["725"],
    }
    for (short, asof), L in laws.items():
        lines = [f"# {short} asof={asof} law_revision_id={L.ri.get('law_revision_id')} status={L.ri.get('current_revision_status')}", ""]
        for num in dump_targets.get(short, []):
            a = L.article(num)
            if a is None:
                lines.append(f"## {num}: 本則にない")
                continue
            lines.append(f"## {num} {caption(a)}")
            if short in ("kenpo", "minpo") or (short == "shotoku" and num == "2") or (short == "sochi" and num not in ("41_17",)):
                # 長い条は見出しと必要な項だけ
                if short == "shotoku" and num == "2":
                    i30 = item(para(a, 1), 30)
                    struct_lines(i30, "2-1-30", lines) if i30 is not None else lines.append("2-1-30 なし")
                    continue
                if short in ("kenpo", "minpo"):
                    continue
                if short == "sochi":
                    for p in kids(a, "Paragraph"):
                        if "第七十二条から第八十七条まで" in text_of(p) or "第七十三条" in text_of(p):
                            struct_lines(p, f"{num}-{p.get('attr', {}).get('Num')}", lines)
                    continue
            struct_lines(a, num, lines)
            lines.append("")
        fn = f"dump_{short}_{asof}.txt"
        (OUT / fn).write_text("\n".join(lines), encoding="utf-8")
        res["dumps"].append(fn)

    # ---- 条文の主張の検査（ID は文書の節に対応）
    for asof in ["2025-12-31", "2026-11-09", "2026-12-31", "2027-01-01"]:
        # [LAW] §1 所法73
        chk("LAW1-73-1", "shotoku", asof, P("73", 1), [
            "居住者が、各年において、自己又は自己と生計を一にする配偶者その他の親族に係る医療費を支払つた場合において、その年中に支払つた当該医療費の金額（保険金、損害賠償金その他これらに類するものにより補てんされる部分の金額を除く。）の合計額がその居住者のその年分の総所得金額、退職所得金額及び山林所得金額の合計額の百分の五に相当する金額（当該金額が十万円を超える場合には、十万円）を超えるときは、その超える部分の金額（当該金額が二百万円を超える場合には、二百万円）を、その居住者のその年分の総所得金額、退職所得金額又は山林所得金額から控除する。"])
        chk("LAW1-73-2", "shotoku", asof, P("73", 2), ["前項に規定する医療費とは、医師又は歯科医師による診療又は治療、治療又は療養に必要な医薬品の購入その他医療又はこれに関連する人的役務の提供の対価のうち通常必要であると認められるものとして政令で定めるものをいう。"])
        chk("LAW1-73-3", "shotoku", asof, P("73", 3), ["第一項の規定による控除は、医療費控除という。"])
        # [LAW] §2.1 所令207
        chk("LAW2.1-207", "shotoku-rei", asof, A("207"), [
            "法第七十三条第二項（医療費控除）に規定する政令で定める対価は、次に掲げるものの対価のうち、その病状その他財務省令で定める状況に応じて一般的に支出される水準を著しく超えない部分の金額とする。",
            "医師又は歯科医師による診療又は治療", "治療又は療養に必要な医薬品の購入",
            "病院、診療所（これに準ずるものとして財務省令で定めるものを含む。）又は助産所へ収容されるための人的役務の提供",
            "第三条の二（名簿）に規定する施術者（同法第十二条の二第一項（医業類似行為を業とすることができる者）の規定に該当する者を含む。）又は柔道整復師法（昭和四十五年法律第十九号）第二条第一項（定義）に規定する柔道整復師による施術",
            "保健師、看護師又は准看護師による療養上の世話", "助産師による分べんの介助",
            "介護福祉士による社会福祉士及び介護福祉士法（昭和六十二年法律第三十号）第二条第二項（定義）に規定する喀痰吸引等又は同法附則第十条第一項（認定特定行為業務従事者に係る特例）に規定する認定特定行為業務従事者による同項に規定する特定行為"])
        chk("LAW2.1-207-items", "shotoku-rei", asof, I("207", 1, 7), ["介護福祉士"])
        chk("LAW2.1-207-no8", "shotoku-rei", asof, I("207", 1, 8), [])  # 第8号はない（見つからないことを期待）
        # [LAW] §2.2 所規40の3
        chk("LAW2.2-40_3-1-1", "shotoku-ki", asof, I("40_3", 1, 1), ["介護保険法", "第四十八条第一項第一号", "指定地域密着型介護老人福祉施設"])
        chk("LAW2.2-40_3-1-2", "shotoku-ki", asof, I("40_3", 1, 2), ["高齢者の医療の確保に関する法律", "第十八条第一項", "特定健康診査", "特定保健指導", "積極的支援", "高血圧症", "脂質異常症", "糖尿病"])
        chk("LAW2.2-40_3-2", "shotoku-ki", asof, P("40_3", 2), ["指定介護老人福祉施設", "指定地域密着型介護老人福祉施設"])
        # [LAW] §3.1 所法22
        chk("LAW3.1-22-2", "shotoku", asof, P("22", 2), ["総所得金額は、次節（各種所得の金額の計算）の規定により計算した次に掲げる金額の合計額（第七十条第一項若しくは第二項（純損失の繰越控除）又は第七十一条第一項（雑損失の繰越控除）の規定の適用がある場合には、その適用後の金額）とする。",
                                                           "利子所得の金額、配当所得の金額、不動産所得の金額、事業所得の金額、給与所得の金額、譲渡所得の金額（第三十三条第三項第一号（譲渡所得）に掲げる所得に係る部分の金額に限る。）及び雑所得の金額（これらの金額につき第六十九条（損益通算）の規定の適用がある場合には、その適用後の金額）の合計額",
                                                           "譲渡所得の金額（第三十三条第三項第二号に掲げる所得に係る部分の金額に限る。）及び一時所得の金額（これらの金額につき第六十九条の規定の適用がある場合には、その適用後の金額）の合計額の二分の一に相当する金額"])
        chk("LAW3.1-22-3", "shotoku", asof, P("22", 3), ["退職所得金額又は山林所得金額は、それぞれ次節の規定により計算した退職所得の金額又は山林所得の金額（これらの金額につき第六十九条、第七十条又は第七十一条の規定の適用がある場合には、その適用後の金額）とする。"])
        # [LAW] §3.1 所法2①30イ(2)（合計所得金額の定義）
        chk("LAW3.1-2-1-30", "shotoku", asof, I("2", 1, 30), ["第七十条（純損失の繰越控除）及び第七十一条（雑損失の繰越控除）の規定を適用しないで計算した場合における", "合計所得金額"])
        # [LAW] §3.3 所法87
        chk("LAW3.3-87-1", "shotoku", asof, P("87", 1), ["雑損控除", "医療費控除", "まず雑損控除を行う"])
        chk("LAW3.3-87-2", "shotoku", asof, P("87", 2), ["総所得金額、山林所得金額又は退職所得金額から順次控除する"])
        # [LAW] §5.1 所法120④⑤
        chk("LAW5.1-120-4", "shotoku", asof, P("120", 4), ["医療費控除", "財務省令で定める事項", "控除適用医療費の額等", "明細書", "国民健康保険団体連合会"])
        chk("LAW5.1-120-5", "shotoku", asof, P("120", 5), ["税務署長は", "五年を経過する日", "六月以内", "六月を経過する日", "提示又は提出"])
        # [LAW] §5.2 所規47の2⑫⑬
        chk("LAW5.2-47_2-12", "shotoku-ki", asof, P("47_2", 12), ["その年中において支払つた法第七十三条第二項（医療費控除）に規定する医療費", "診療等", "を受けた者の氏名", "病院、診療所その他の者の名称又は氏名", "その他参考となるべき事項"])
        chk("LAW5.2-47_2-12-items", "shotoku-ki", asof, I("47_2", 12, 4), ["その他参考となるべき事項"])
        chk("LAW5.2-47_2-12-no5", "shotoku-ki", asof, I("47_2", 12, 5), [])
        chk("LAW5.2-47_2-13", "shotoku-ki", asof, P("47_2", 13), [
            "健康保険法施行規則", "第百十二条の二", "国民健康保険法施行規則", "第三十二条の七の二", "高齢者の医療の確保に関する法律施行規則", "第八十二条の二",
            "船員保険法施行規則", "第百五十五条の二", "国家公務員共済組合法施行規則", "第百十三条の三の二", "地方公務員等共済組合法施行規程", "第百十九条の五",
            "私立学校教職員共済法施行規則", "第十六条の四", "国民健康保険団体連合会", "電磁的記録印刷書面"])
        # [LAW] §5.3 所令262 に医療費控除の号がない
        chk("LAW5.3-262-no-iryohi", "shotoku-rei", asof, A("262"), ["雑損控除", "社会保険料控除", "生命保険料控除"], absent=["医療費控除"])
        # [LAW] §4.1 措法41の17（令和7年分・令和8年分の版）
        if asof != "2027-01-01":
            chk("LAW4.1-41_17-1", "sochi", asof, P("41_17", 1), [
                "平成二十九年一月一日から令和八年十二月三十一日までの間に自己又は自己と生計を一にする配偶者その他の親族に係る特定一般用医薬品等購入費を支払つた場合において当該居住者がその年中に健康の保持増進及び疾病の予防への取組として政令で定める取組を行つているとき",
                "その者の選択により", "平成二十九年から令和八年までの各年", "一万二千円", "八万八千円",
                "第四条第五項第三号", "要指導医薬品", "第四号", "一般用医薬品"])
            chk("LAW4.1-41_17-2-1", "sochi", asof, I("41_17", 2, 1), ["医療用薬剤との代替性が特に高いもの（その使用による医療保険療養給付費の適正化の効果が低いと認められる医薬品を除く。）"])
            chk("LAW4.1-41_17-2-2", "sochi", asof, I("41_17", 2, 2), ["前号に掲げる医薬品と同種の効能又は効果を有すると認められる医薬品（同号に掲げる医薬品を除く。）のうち", "適正化の効果が著しく高いと認められるもの"])
            chk("LAW4.1-41_17-3", "sochi", asof, P("41_17", 3), ["令和四年一月一日から、同日から令和八年十二月三十日までの間において政令で定める日までの期間内に行つた第一項の居住者の一般用医薬品等の購入の対価の支払"])
            chk("LAW4.1-41_17-4", "sochi", asof, P("41_17", 4), ["第百二十二条第三項、第百二十三条第三項、第百二十五条第四項及び第百二十七条第四項において準用する場合を含む", "財務省令で定める事項の記載がある明細書", "その領収をした金額のうち、特定一般用医薬品等購入費に該当するものの金額が明らかにされているものに限る"])
            chk("LAW4.1-41_17-5", "sochi", asof, P("41_17", 5), ["政令で定める"])
            chk("LAW4.1-41_17-no6", "sochi", asof, P("41_17", 6), [])
            # [LAW] §4.2 措令26の27の3
            chk("LAW4.2-26_27_3-1", "sochi-rei", asof, P("26_27_3", 1), ["法律又は法律に基づく命令（告示を含む。）に基づき行われる健康の保持増進及び疾病の予防への取組として厚生労働大臣が財務大臣と協議して定めるもの"])
            chk("LAW4.2-26_27_3-2", "sochi-rei", asof, P("26_27_3", 2), ["新医薬品", "第十四条の四第一項第一号", "人の身体に直接使用されることのないもの", "厚生労働大臣が財務大臣と協議して定めるもの"])
            chk("LAW4.2-26_27_3-3", "sochi-rei", asof, P("26_27_3", 3), ["人の身体に直接使用されることのないもの", "著しく高い"])
            chk("LAW4.2-26_27_3-4", "sochi-rei", asof, P("26_27_3", 4), ["厚生労働大臣が財務大臣と協議して定める日"])
            chk("LAW4.2-26_27_3-6", "sochi-rei", asof, P("26_27_3", 6), ["第百二条", "第二百五十八条第三項", "一万二千円", "八万八千円"])
            chk("LAW4.2-26_27_3-7", "sochi-rei", asof, P("26_27_3", 7), ["厚生労働大臣", "告示"])
            chk("LAW4.2-26_27_3-no8", "sochi-rei", asof, P("26_27_3", 8), [])
            # [LAW] §4.5 措規19の10の2の2
            for n, kw in [(1, "に規定する取組（次号及び次項において「取組」という。）の名称"), (2, "保険者、事業者若しくは市町村（特別区を含む。）の名称又は当該取組に係る診察を行つた医療機関の名称若しくは医師の氏名"),
                          (3, "その年中において支払つた法第四十一条の十七第一項に規定する特定一般用医薬品等購入費"), (4, "販売を行つた者の氏名又は名称"), (5, "特定一般用医薬品等の名称"), (6, "その他参考となるべき事項")]:
                chk(f"LAW4.5-19_10_2_2-1-{n}", "sochi-ki", asof, I("19_10_2_2", 1, n), [kw])
            chk("LAW4.5-19_10_2_2-1-no7", "sochi-ki", asof, I("19_10_2_2", 1, 7), [])
            chk("LAW4.5-19_10_2_2-2", "sochi-ki", asof, P("19_10_2_2", 2), ["氏名", "取組を行つた年", "前項第二号"])
        # [LAW] §3.2 措法の読替え（項・号を構造で確かめる）
        if asof in ("2025-12-31", "2026-12-31"):
            for cid, num, p, i, kw in [("LAW3.2-8_4-3-3", "8_4", 3, 3, "上場株式等に係る配当所得等の金額"),
                                       ("LAW3.2-28_4-5-2", "28_4", 5, 2, "土地等に係る事業所得等の金額"),
                                       ("LAW3.2-31-3-3", "31", 3, 3, "長期譲渡所得の金額"),
                                       ("LAW3.2-37_10-6-5", "37_10", 6, 5, "一般株式等に係る譲渡所得等の金額"),
                                       ("LAW3.2-41_14-2-4", "41_14", 2, 4, "先物取引に係る雑所得等の金額")]:
                chk(cid, "sochi", asof, I(num, p, i), ["第七十二条から第八十七条まで", "「総所得金額」とあるのは", kw])
            chk("LAW3.2-31-1-def", "sochi", asof, P("31", 1), ["同法第三十三条第三項に規定する譲渡所得の特別控除額の控除をしないで計算した金額"])
    # [LAW] §4.4 令和9年分以後（2027-01-01 版）
    chk("LAW4.4-41_17-1-r9", "sochi", "2027-01-01", P("41_17", 1), ["薬局製造販売医薬品", "平成二十九年一月一日以後の期間", "令和十三年十二月三十一日", "一万二千円", "八万八千円"])
    chk("LAW4.4-41_17-2-3-r9", "sochi", "2027-01-01", I("41_17", 2, 3), ["体外診断用医薬品"])
    for asof in ["2027-01-01"]:
        L = laws.get(("sochi", asof))
        if L:
            for an, a in L.suppl_article("令和八年.*法律第一二号", "46"):
                res["checks"].append({"id": "LAW4.4-R8-12-suppl46", "law": "sochi", "asof": asof, "amend": an,
                                      "ok": norm("新租税特別措置法第四十一条の十七の規定は、令和九年分以後の所得税について適用し、令和八年分以前の所得税については、なお従前の例による。") in norm(text_of(a)),
                                      "text": text_of(a)[:400]})
            for an, a in L.suppl_article("令和八年.*法律第一二号", "1"):
                i5 = item(para(a, 1) or a, 5)
                t5 = text_of(i5) if i5 is not None else ""
                i18 = item(para(a, 1) or a, 18)
                t18 = text_of(i18) if i18 is not None else ""
                res["checks"].append({"id": "LAW4.4-R8-12-suppl1-5", "law": "sochi", "asof": asof, "amend": an,
                                      "ok": ("令和九年一月一日" in t5) and ("第四十一条の十七の改正規定（同条第一項中「第四条第五項第三号」を「第四条第九項第三号」に改める部分を除く。）" in t5),
                                      "item5_head": t5[:200], "item5_len": len(t5)})
                res["checks"].append({"id": "LAW4.4-R8-12-suppl1-18", "law": "sochi", "asof": asof, "amend": an,
                                      "ok": ("令和七年法律第三十七号" in t18) and ("附則第一条第三号" in t18),
                                      "item18": t18[:600]})
                # 第5号のロの位置の確認（Subitem1）
                if i5 is not None:
                    subs = {s.get("attr", {}).get("Num"): text_of(s)[:300] for s in kids(i5, "Subitem1")}
                    res["checks"].append({"id": "LAW4.4-R8-12-suppl1-5-subitems", "law": "sochi", "asof": asof, "subitems": subs,
                                          "ok": any("第四十一条の十七の改正規定" in v for v in subs.values())})
    # [LAW] §4.6 令和3年法律第11号附則第38条
    for asof in ["2025-12-31", "2026-12-31"]:
        L = laws.get(("sochi", asof))
        if L:
            hits = L.suppl_article("令和三年.*法律第一一号", "38")
            for an, a in hits:
                p1, p2 = para(a, 1), para(a, 2)
                res["checks"].append({"id": "LAW4.6-R3-11-suppl38", "law": "sochi", "asof": asof, "amend": an,
                                      "p1": text_of(p1)[:300] if p1 else None, "p2": text_of(p2)[:300] if p2 else None,
                                      "ok": bool(p1 and p2 and "令和四年分以後" in text_of(p1) and "令和四年一月一日以後" in text_of(p2) and "令和三年分以後" in text_of(p2))})
            if not hits:
                res["checks"].append({"id": "LAW4.6-R3-11-suppl38", "law": "sochi", "asof": asof, "ok": False, "note": "附則が見つからない"})
    # [LAW] §4.2 措令の条番号の繰下げ（令和7年政令第127号附則第1条第1号）
    for asof in ["2025-12-31", "2026-11-09"]:
        L = laws.get(("sochi-rei", asof))
        if L:
            ans = sorted({s.get("attr", {}).get("AmendLawNum", "") for s in L.suppl if "一二七号" in s.get("attr", {}).get("AmendLawNum", "")})
            for an, a in L.suppl_article("令和七年.*政令第一二七号", "1"):
                t = text_of(a)
                k = t.find("第二十六条の二十七の二第六項の改正規定")
                i1 = item(para(a, 1) or a, 1)
                res["checks"].append({"id": "LAW4.2-R7-127-suppl1-1", "law": "sochi-rei", "asof": asof, "amend": an,
                                      "found_at": k, "context": t[max(0, k - 120):k + 200] if k >= 0 else None,
                                      "item1": text_of(i1)[:500] if i1 is not None else None,
                                      "ok": k >= 0 and i1 is not None and "第二十六条の二十七の二第六項の改正規定" in text_of(i1) and "令和七年十二月一日" in text_of(i1)})
            res.setdefault("notes", {})[f"sochi-rei@{asof} AmendLawNum(一二七号)"] = ans
            res.setdefault("notes", {})[f"sochi-rei@{asof} has 26_27_2 / 26_27_3"] = [L.article("26_27_2") is not None and caption(L.article("26_27_2")),
                                                                                     L.article("26_27_3") is not None and caption(L.article("26_27_3"))]
    # 所令258 の見出し
    for asof in ["2025-12-31", "2026-11-09"]:
        L = laws.get(("shotoku-rei", asof))
        if L and L.article("258"):
            res.setdefault("notes", {})[f"shotoku-rei@{asof} 258 caption"] = caption(L.article("258"))
    # 健康保険法の条の見出し（通達73−8・73−9 の引用の確認）
    L = laws.get(("kenpo", "2026-11-09"))
    if L:
        res.setdefault("notes", {})["kenpo captions"] = {n: (caption(L.article(n)) if L.article(n) else None)
                                                         for n in ["87", "97", "99", "101", "102", "110", "112", "114", "115", "115_2"]}
    L = laws.get(("minpo", "2026-11-09"))
    if L and L.article("725"):
        res.setdefault("notes", {})["minpo 725"] = text_of(L.article("725"))
    # 所法120・所規47の2 の項の数（版ごと）
    for short, num in [("shotoku", "120"), ("shotoku-ki", "47_2"), ("sochi", "41_17"), ("sochi-rei", "26_27_3"), ("sochi-ki", "19_10_2_2")]:
        for asof in ["2025-12-31", "2026-11-09", "2026-12-31", "2027-01-01"]:
            L = laws.get((short, asof))
            a = L.article(num) if L else None
            res.setdefault("paragraph_counts", {})[f"{short}:{num}@{asof}"] = len(kids(a, "Paragraph")) if a else None
    # 条ごとの本文の SHA-256（版の比較）。本則の条の本文全体。
    for short, nums in [("shotoku", ["22", "73", "87", "120"]), ("shotoku-rei", ["207", "262"]), ("shotoku-ki", ["40_3", "47_2"]),
                        ("sochi", ["41_17"]), ("sochi-rei", ["26_27_3"]), ("sochi-ki", ["19_10_2_2"])]:
        for num in nums:
            row = {}
            for asof in ["2025-12-31", "2026-11-09", "2026-12-31", "2027-01-01"]:
                L = laws.get((short, asof))
                a = L.article(num) if L else None
                row[asof] = hashlib.sha256(text_of(a).encode()).hexdigest()[:16] if a else None
            res["article_hash"][f"{short}:{num}"] = row
    # 所法120④⑤・所規47の2⑫ だけの比較（機関名の改称のほかに違いがないか）
    for short, num, ps in [("shotoku", "120", [4, 5]), ("shotoku-ki", "47_2", [12])]:
        for p in ps:
            row = {}
            for asof in ["2025-12-31", "2026-11-09", "2026-12-31", "2027-01-01"]:
                L = laws.get((short, asof))
                node = para(L.article(num), p) if L and L.article(num) else None
                t = text_of(node) if node is not None else ""
                t2 = t.replace("社会保険診療報酬支払基金", "＜機関＞").replace("医療情報基盤・診療報酬審査支払機構", "＜機関＞")
                row[asof] = {"raw": hashlib.sha256(t.encode()).hexdigest()[:16], "masked": hashlib.sha256(t2.encode()).hexdigest()[:16]}
            res["article_hash"][f"{short}:{num}-{p}"] = row
    # 隣り合う版で、どの項が違うか（所法120・所規47の2）。2027-01-01 版は項の番号がずれるので本文の一致で対応を見る
    for short, num in [("shotoku", "120"), ("shotoku-ki", "47_2")]:
        seq = ["2025-12-31", "2026-11-09", "2026-12-31", "2027-01-01"]
        for x, y in zip(seq, seq[1:]):
            Lx, Ly = laws.get((short, x)), laws.get((short, y))
            if not (Lx and Ly and Lx.article(num) and Ly.article(num)):
                continue
            px = {p.get("attr", {}).get("Num"): text_of(p)[1:] for p in kids(Lx.article(num), "Paragraph")}
            py = {p.get("attr", {}).get("Num"): text_of(p)[1:] for p in kids(Ly.article(num), "Paragraph")}
            same_num_diff = [k for k in sorted(set(px) | set(py), key=int) if px.get(k) != py.get(k)]
            new_to_old = {k: [j for j, v in px.items() if v == t] for k, t in py.items()}
            res.setdefault("paragraph_diff", {})[f"{short}:{num} {x}->{y}"] = {"differ_by_number": same_num_diff,
                                                                               "new_paragraph_matches_old": new_to_old}
    # 端数の定め：所法・所令・所規の本則で「円未満」「端数」を含む条（2025-12-31 版）。第73条の5%の端数の定めがあるかの部分的な確認
    for short in ["shotoku", "shotoku-rei", "shotoku-ki"]:
        L = laws.get((short, "2025-12-31"))
        if not L:
            continue
        arts = sorted({num for num, a in L.main.items() if re.search(r"円未満|端数", text_of(a))}, key=lambda s: [int(x) for x in s.split("_")])
        res.setdefault("rounding_search", {})[short] = {"articles_with_円未満_or_端数": arts,
                                                        "includes_73": "73" in arts}
    # 措法の本則で「第七十二条から第八十七条まで」を含む項（数と位置）、措令・所令で「第七十三条第一項」を含む項
    for short, asof, kw in [("sochi", "2025-12-31", "第七十二条から第八十七条まで"), ("sochi", "2026-12-31", "第七十二条から第八十七条まで"),
                            ("sochi-rei", "2025-12-31", "第七十三条第一項"), ("shotoku-rei", "2025-12-31", "第七十三条第一項")]:
        L = laws.get((short, asof))
        if not L:
            continue
        hits = []
        for num, a in L.main.items():
            for p in kids(a, "Paragraph"):
                if kw in text_of(p):
                    sub = [f"{num}-{p.get('attr', {}).get('Num')}-{i.get('attr', {}).get('Num')}" for i in kids(p, "Item") if kw in text_of(i)]
                    hits.append({"para": f"{num}-{p.get('attr', {}).get('Num')}", "items": sub,
                                 "yomikae": "「総所得金額」とあるのは" in text_of(p)})
        res.setdefault("grep", {})[f"{short}@{asof} {kw}"] = {"paragraphs": len(hits), "hits": hits}
    out = OUT / "egov_check.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    ng = [c for c in res["checks"] if not c.get("ok")]
    print("checks", len(res["checks"]), "ng", len(ng))
    for c in ng:
        print(" NG", c["id"], c.get("asof"), c.get("missing"), c.get("unexpected"), c.get("node_found"))
    print("written", out)


# ---------------------------------------------------------------- 国税庁・厚生労働省
NTA = "https://www.nta.go.jp"
MHLW = "https://www.mhlw.go.jp"
QA_NUMS = ["24", "25", "26", "27", "28", "57", "58", "59", "60", "61", "81", "82", "83",
           "86", "72", "12", "39", "21", "50", "20", "09", "16", "18", "53", "54", "42"]
WEB = {
    "tsutatsu73": NTA + "/law/tsutatsu/kihon/shotoku/16/01.htm",
    "ta1120": NTA + "/taxes/shiraberu/taxanswer/shotoku/1120.htm",
    "ta1122": NTA + "/taxes/shiraberu/taxanswer/shotoku/1122.htm",
    "ta1129": NTA + "/taxes/shiraberu/taxanswer/shotoku/1129.htm",
    "ta1131": NTA + "/taxes/shiraberu/taxanswer/shotoku/1131.htm",
    "ta1132": NTA + "/taxes/shiraberu/taxanswer/shotoku/1132.htm",
    "ta1133": NTA + "/taxes/shiraberu/taxanswer/shotoku/1133.htm",
    "ta1134": NTA + "/taxes/shiraberu/taxanswer/shotoku/1134.htm",
    "yogo": NTA + "/taxes/shiraberu/taxanswer/yogo/senmon.htm",
    "qa_index": NTA + "/law/shitsugi/shotoku/01.htm",
    **{f"qa05_{n}": NTA + f"/law/shitsugi/shotoku/05/{n}.htm" for n in QA_NUMS},
    "tebiki_3-3_24": NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/03/order3/3-3_24.htm",
    "tebiki_6_01": NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/06/6_01.htm",
    "tebiki_3-2_09": NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/03/order2/3-2_09.htm",
    "tebiki_008_pdf": NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/pdf/008.pdf",
    "yoshiki_ref1_pdf": NTA + "/taxes/shiraberu/shinkoku/yoshiki/04/pdf/ref1.pdf",
    "yoshiki_ref3_pdf": NTA + "/taxes/shiraberu/shinkoku/yoshiki/03/pdf/ref3.pdf",
    "yoshiki_ref1ki_pdf": NTA + "/taxes/shiraberu/shinkoku/yoshiki/04/pdf/ref1-ki.pdf",
    "yoshiki_017_pdf": NTA + "/taxes/shiraberu/shinkoku/yoshiki/017.pdf",
    "yoshiki_017ki_pdf": NTA + "/taxes/shiraberu/shinkoku/yoshiki/017-ki.pdf",
    "yoshiki_ref4_pdf": NTA + "/taxes/shiraberu/shinkoku/yoshiki/03/pdf/ref4.pdf",
    "yoshiki_list": NTA + "/taxes/tetsuzuki/shinsei/annai/shinkoku/annai/1557_2.htm",
    "tokushu_iryou": NTA + "/taxes/shiraberu/shinkoku/tokushu/keisubetsu/iryou-koujo.htm",
    "tokushu_self": NTA + "/taxes/shiraberu/shinkoku/tokushu/keisubetsu/self-medication.htm",
    "tokushu_shuukei": NTA + "/taxes/shiraberu/shinkoku/tokushu/keisubetsu/iryou-shuukei.htm",
    "form_xlsx": NTA + "/taxes/shiraberu/shinkoku/tokushu/keisubetsu/iryouhi_form_v3.1.xlsx",
    "soft404_shoto320": NTA + "/taxes/shiraberu/taxanswer/shotoku/shoto320.htm",
    "soft404_yoshiki01": NTA + "/taxes/shiraberu/shinkoku/yoshiki/01/index.htm",
    "soft404_shinkokusho01": NTA + "/taxes/shiraberu/shinkoku/yoshiki/01/shinkokusho/01.htm",
    "soft404_tebiki2025_01": NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/01.htm",
    "mhlw_page": MHLW + "/stf/seisakunitsuite/bunya/0000124853.html",
    "mhlw_qa_pdf": MHLW + "/content/10800000/001461529.pdf",
    "mhlw_receipt_pdf": MHLW + "/file/06-Seisakujouhou-10800000-Iseikyoku/0000138818.pdf",
    "mhlw_exclude_pdf": MHLW + "/content/10800000/001596290.pdf",
    "mhlw_kokuji181_pdf": MHLW + "/content/10800000/000619222.pdf",
    "mhlw_shomei_r8_pdf": MHLW + "/content/10800000/001755789.pdf",
    "mhlw_misprint": MHLW + "/stf/newpage_08184.html",
}
QA_DATE = "令和7年8月1日現在の法令・通達等に基づいて作成"
# 各ページで原文にあるはずの文言（[NM] の主張から）。比べる前に NFKC・空白の除去・「補てん/補填/補塡」の統一をする。
PHRASES = {
    "tsutatsu73": ["医療費を支出すべき事由が生じた時又は現実に医療費を支払った時の現況", "未払となっている医療費は現実に支払われるまでは",
                   "通院費", "送迎費", "部屋代、食事代", "義手、義足、松葉づえ、補聴器、義歯等", "身体障害者福祉法第38条", "知的障害者福祉法第27条", "児童福祉法第56条",
                   "健康診断により重大な疾病が発見され、かつ、当該診断に引き続きその疾病の治療をした場合",
                   "疾病の予防又は健康増進のために供されるもの", "療養上の世話を受けるために特に依頼したもの", "保健師助産師看護師法第3条",
                   "健康保険法第87条第2項", "第97条第1項", "第101条", "第110条", "第112条第1項", "第114条", "第115条第1項", "第115条の2第1項",
                   "第99条第1項", "第102条", "傷害費用保険金、医療保険金又は入院費給付金等", "任意の互助組織",
                   "確定申告書を提出する時までに確定していない場合", "見込額", "遡及してその医療費控除額を訂正"],
    "ta1120": ["令和8年4月1日現在法令等", "その給付の目的となった医療費の金額を限度として差し引きますので、引ききれない金額が生じた場合であっても他の医療費からは差し引きません",
               "10万円", "200万円", "高額療養費", "家族療養費", "出産育児一時金", "被保険者等の氏名", "療養を受けた年月",
               "療養を受けた者", "療養を受けた病院、診療所、薬局等の名称", "被保険者等が支払った医療費の額", "保険者等の名称"],
    "ta1122": ["令和8年4月1日現在法令等", "介護老人保健施設", "介護医療院", "指定介護療養型医療施設", "指定介護老人福祉施設", "指定地域密着型介護老人福祉施設",
               "日本骨髄バンク", "日本臓器移植ネットワーク", "おむつ使用証明書", "6か月以上", "タクシー代", "ガソリン代", "特定保健指導", "喀痰吸引", "経管栄養"],
    "ta1129": ["令和8年4月1日現在法令等", "更正の請求や修正申告によりこの選択を変更することはできません", "12,000円", "88,000円",
               "申告される方と生計を一にする配偶者その他の親族の方が「一定の取組」を行っている必要はありません",
               "所法73、120、所令262、措法41の17、措令26の27の3、措規19の10の2の2", "平28厚生労働省告示第178号", "第181号",
               "平成29年改正法附則58", "令和3年改正措法附則38", "令和4年1月1日以後"],
    "ta1131": ["令和8年4月1日現在法令等", "通常の医療費控除を併せて受けることはできません", "10万円と総所得金額等の5パーセント相当額のいずれか低い方の金額"],
    "ta1132": ["令和8年4月1日現在法令等", "平成29年1月1日から令和3年12月31日まで", "令和4年1月1日から令和8年12月31日まで",
               "令和8年1月1日以降に購入したものについては", "令和8年4月1日現在100成分", "令和8年4月1日現在42成分",
               "令3厚生労働省告示第251号", "第253号", "措令26の27の3"],
    "ta1133": ["令和8年4月1日現在法令等", "インフルエンザに関する特定感染症予防指針", "予防接種法第5条第1項", "労働安全衛生法第66条第1項",
               "高齢者の医療の確保に関する法律第20条", "第24条", "健康増進法第19条の2", "平28厚生労働省告示第181号"],
    "ta1134": ["令和8年4月1日現在法令等", "予防接種済証", "結果通知表", "勤務先名称", "保険者名"],
    "yogo": ["退職所得金額は、確定申告が不要な場合でも計算に当たって加算する必要があります", "長(短)期譲渡所得については特別控除前の金額",
             "純損失や雑損失の繰越控除", "先物取引の差金等決済に係る損失の繰越控除"],
    "qa05_24": [QA_DATE, "30万円", "20万円"],
    "qa05_25": [QA_DATE, "医療費を実際に支払った夫の医療費控除の対象となります", "所得金額の要件は付されていません"],
    "qa05_26": [QA_DATE, "夫の支払った医療費から妻が支払を受ける給付金を差し引く必要があります", "その保険金等の支払を受ける者が医療費を支払った者でない場合であっても"],
    "qa05_27": [QA_DATE, "出産手当金"],
    "qa05_28": [QA_DATE, "その補塡の対象とされる医療費ごとに行い", "他の医療費の金額からは差し引きません"],
    "qa05_57": [QA_DATE, "すなわち、その医療費の請求の基となった治療等を被相続人である父親が受けた時"],
    "qa05_58": [QA_DATE, "2-47"],
    "qa05_59": [QA_DATE, "遡ってその年分の医療費控除額を訂正します"],
    "qa05_60": [QA_DATE, "医療費控除の適用を受けた年分の控除額を是正することとなります"],
    "qa05_61": [QA_DATE, "支払った入院費用の額に応じて、各年分にあん分します"],
    "qa05_81": [QA_DATE, "借入金"],
    "qa05_82": [QA_DATE, "3親等", "725"],
    "qa05_83": [QA_DATE, "医療費を実際に支払った子供の医療費控除の対象となります", "控除対象配偶者や控除対象扶養親族であるかどうかは問わない"],
    "qa05_86": [QA_DATE, "入院費用に充当された年分の医療費控除の対象"],
    "qa05_72": [QA_DATE, "特定保健指導", "積極的支援"],
    "qa05_09": [QA_DATE, "人間ドック"], "qa05_12": [QA_DATE, "かぜ"], "qa05_39": [QA_DATE, "ビタミン剤"],
    "qa05_21": [QA_DATE, "タクシー"], "qa05_50": [QA_DATE, "電車賃やバス賃などのように人的役務の提供の対価として支出されるもの"],
    "qa05_20": [QA_DATE, "付添人の交通費"], "qa05_16": [QA_DATE, "差額ベッド料"], "qa05_18": [QA_DATE, "出前"],
    "qa05_53": [QA_DATE, "白内障"], "qa05_54": [QA_DATE, "おむつ使用証明書"], "qa05_42": [QA_DATE, "家政婦"],
    "tebiki_3-3_24": ["確定申告書を提出する時までに確定していない場合には、その保険金などの見込額を記載します",
                      "ほかに申告分離課税の所得がある場合には、それらの所得金額(特別控除前の金額)の合計額を加算します",
                      "マイナスのときは0円", "赤字のときは0円", "最高200万円",
                      "医療費控除を選択する場合は、「区分」の□は記入しません", "「区分」の□に「1」を記入します"],
    "tebiki_6_01": ["医療費の領収書の添付又は提示は必要ありません", "復元できない程度に塗り潰してください",
                    "通院費の支払先が乗り継ぎ等により複数ある場合には", "医療費の内容として該当するものを全てチェックします"],
    "tebiki_3-2_09": ["本年分で差し引く繰越損失額"],
    "tokushu_iryou": ["代理人の設定"],
    "tokushu_self": ["通常の医療費控除を受けることを選択した場合の控除の対象となる医療費にも該当します"],
    "tokushu_shuukei": ["ver3.1", "セルフメディケーション税制の適用を受ける方は"],
    "yoshiki_list": ["017-ki.pdf", "ref1.pdf"],
    "mhlw_page": ["令和8年11月1日時点"],
    "mhlw_misprint": ["2024年3月2日～9月25日", "2024年7月1日～9月29日", "2022年2月1日～2月9日", "(55品)"],
}


class Extract(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.links, self.title = [], [], ""
        self._skip = 0
        self._in_title = False
        self._href = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "img" and a.get("alt") and not self._skip:
            self.parts.append("⟨" + a["alt"] + "⟩")
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
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
    m = re.search(r"charset=([\w\-]+)", ctype or "", re.I) or re.search(rb"charset=[\"']?([\w\-]+)", body[:2000], re.I)
    cs = (m.group(1).decode() if isinstance(m.group(1), bytes) else m.group(1)) if m else "utf-8"
    if cs.lower().replace("-", "_") in ("shift_jis", "sjis", "x_sjis"):
        cs = "cp932"  # 丸数字などを含むため Windows の拡張（cp932）で読む
    try:
        return body.decode(cs)
    except (LookupError, UnicodeDecodeError):
        return body.decode("utf-8", "replace")


def wnorm(s):
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"⟨(ほてん|てん|塡)⟩", "塡", s)
    s = re.sub(r"\s+", "", s)
    s = s.replace("補てん", "補塡").replace("補填", "補塡")
    s = re.sub(r"[‐‑‒–—―−－]", "-", s)
    return s


def web_fetch():
    ts, dl = new_dl_dir("web")
    OUT.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "fetches": []}
    for i, (key, url) in enumerate(WEB.items()):
        try:
            meta, body = get(url)
        except Exception as e:  # noqa
            log["fetches"].append({"key": key, "url": url, "error": repr(e)})
            print("ERR", key, e, flush=True)
            continue
        ext = pathlib.PurePosixPath(urllib.parse.urlsplit(url).path).suffix or ".bin"
        fn = f"{i:02d}_{key}{ext}"
        (dl / fn).write_bytes(body)
        log["fetches"].append(dict(meta, key=key, file=fn))
        print(key, meta["status"], meta["bytes"], meta.get("last_modified"), meta["sha256"][:16], flush=True)
    (OUT / f"web_fetch_log_{ts}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("download_dir", dl)


def web_check(dl):
    dl = pathlib.Path(dl)
    logs = sorted(OUT.glob("web_fetch_log_*.json"))
    log = None
    for lp in logs:
        d = json.loads(lp.read_text(encoding="utf-8"))
        if pathlib.Path(d["download_dir"]).name == dl.name:
            log = d
    if log is None:
        raise SystemExit("fetch log for this download dir not found")
    res = {"download_dir": str(dl), "pages": {}, "checks": []}
    texts = {}
    for f in log["fetches"]:
        key = f["key"]
        info = {k: f.get(k) for k in ("url", "status", "bytes", "last_modified", "content_type")}
        info["sha256_16"] = (f.get("sha256") or "")[:16]
        p = dl / f.get("file", "")
        if p.suffix in (".htm", ".html") and p.exists():
            body = p.read_bytes()
            ex = Extract()
            ex.feed(decode(body, f.get("content_type")))
            text = "".join(ex.parts)
            texts[key] = text + "\n" + "\n".join(ex.links)  # リンク先（href）も検査の対象に含める
            info["title"] = ex.title.strip()
            m = re.search(r"\[?(令和\s*\d+\s*年\s*\d+\s*月\s*\d+\s*日現在法令等)\]?", unicodedata.normalize("NFKC", text))
            info["as_of_label"] = m.group(1) if m else None
            info["alt_texts"] = sorted(set(re.findall(r"⟨([^⟩]{1,10})⟩", text)))[:30]
            # 抜き出したテキストは国税庁・厚労省のページの写しなので、リポジトリの外（.work/text/）に置く
            tdir = ROOT / ".work" / "text" / dl.name
            tdir.mkdir(parents=True, exist_ok=True)
            (tdir / f"{key}.txt").write_text(re.sub(r"\n{3,}", "\n\n", text), encoding="utf-8")
        res["pages"][key] = info
    for key, needles in PHRASES.items():
        t = wnorm(texts.get(key, ""))
        miss = [n for n in needles if wnorm(n) not in t]
        res["checks"].append({"id": f"WEB-{key}", "ok": bool(t) and not miss, "n": len(needles), "missing": miss})
    # 質疑応答事例の目次：「●医療費控除」の節にある項目の数（目次の通し番号）
    if "qa_index" in texts:
        t = texts["qa_index"]
        s = t.find("●\xa0\xa0医療費控除")
        e = t.find("●", s + 5)
        seg = t[s:e] if s >= 0 else ""
        nums = [int(m.group(1)) for m in re.finditer(r"(?m)^\s*(\d+) ", seg)]
        res["qa_index_iryohi_section"] = {"found": s >= 0, "items": len(nums), "first_no": min(nums) if nums else None,
                                          "last_no": max(nums) if nums else None,
                                          "next_section": t[e:e + 30].strip() if e >= 0 else None,
                                          "missing_numbers": sorted(set(range(min(nums), max(nums) + 1)) - set(nums)) if nums else None}
        p = dl / next(f["file"] for f in log["fetches"] if f["key"] == "qa_index")
        links = re.findall(r'href="([^"]*shotoku/05/\d+\.htm)"', decode(p.read_bytes(), None))
        res["qa_index_05_links"] = {"count_unique": len(set(links)), "nums": sorted({re.search(r'/05/(\d+)\.htm', x).group(1) for x in links}, key=int)}
    # 厚生労働省「レシートの表示の誤り」：スギ薬局の段落（対象期間を原文から抜く）
    if "mhlw_misprint" in texts:
        t = texts["mhlw_misprint"]
        s = t.find("株式会社スギ薬局が発行するレシートの表示の誤り")
        e = t.find("この誤りの詳細は", s)
        seg = t[s:e] if s >= 0 else ""
        res["mhlw_misprint_sugi"] = {"found": s >= 0, "periods": re.findall(r"対象期間\s*(\S+)", seg),
                                     "count_marks": re.findall(r"（(\d+|[０-９]+)品）", seg)}
    # 国税庁のソフト404
    s4 = {k: (v["status"], v["bytes"], v["sha256_16"], v.get("last_modified"), v.get("title")) for k, v in res["pages"].items() if k.startswith("soft404")}
    res["soft404"] = s4
    out = OUT / "web_check.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    ng = [c for c in res["checks"] if not c["ok"]]
    print("checks", len(res["checks"]), "phrases", sum(c["n"] for c in res["checks"]), "ng", len(ng))
    for c in ng:
        print(" NG", c["id"], c["missing"])
    print("written", out)


# ---------------------------------------------------------------- xlsx
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def safe_xml(b):
    if b"<!DOCTYPE" in b[:4096] or b"<!ENTITY" in b[:4096]:
        raise ValueError("DTD/ENTITY を含む XML は読まない")
    return ET.fromstring(b)


def xlsx(paths):
    OUT.mkdir(parents=True, exist_ok=True)
    allres = {}
    for path in paths:
        raw = pathlib.Path(path).read_bytes()
        z = zipfile.ZipFile(io.BytesIO(raw))
        for zi in z.infolist():
            if zi.file_size > 50 * 1024 * 1024:
                raise ValueError(f"too large entry {zi.filename}")
        names = z.namelist()
        ss = []
        if "xl/sharedStrings.xml" in names:
            root = safe_xml(z.read("xl/sharedStrings.xml"))
            # ふりがな（rPh）の t を除く
            for si in root.findall("m:si", NS):
                parts = []
                for ch in si:
                    tag = ch.tag.split("}")[1]
                    if tag == "t":
                        parts.append(ch.text or "")
                    elif tag == "r":
                        for t in ch.findall("m:t", NS):
                            parts.append(t.text or "")
                ss.append("".join(parts))
        wb = safe_xml(z.read("xl/workbook.xml"))
        sheets = [s.get("name") for s in wb.find("m:sheets", NS)]
        rels = safe_xml(z.read("xl/_rels/workbook.xml.rels"))
        rel = {r.get("Id"): r.get("Target") for r in rels}
        sheet_files = []
        for s in wb.find("m:sheets", NS):
            rid = s.get(f"{{{NS['r']}}}id")
            tgt = rel[rid]
            sheet_files.append((s.get("name"), "xl/" + tgt.lstrip("/").replace("xl/", "") if not tgt.startswith("xl/") else tgt))
        res = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "sheets": sheets,
               "has_vba": any("vbaProject" in n for n in names), "sheet_data": {}}
        for name, f in sheet_files:
            root = safe_xml(z.read(f))
            cells = {}
            for c in root.iter(f"{{{NS['m']}}}c"):
                r = c.get("r")
                m = re.fullmatch(r"([A-Z]+)(\d+)", r)
                if not m or int(m.group(2)) > 9:
                    continue
                v = c.find("m:v", NS)
                fml = c.find("m:f", NS)
                isv = c.find("m:is", NS)
                val = None
                if c.get("t") == "s" and v is not None:
                    val = ss[int(v.text)]
                elif isv is not None:
                    val = "".join(t.text or "" for t in isv.iter(f"{{{NS['m']}}}t"))
                elif v is not None:
                    val = v.text
                cells[r] = {"v": val, "f": fml.text if fml is not None else None}
            dvs = []
            dvn = root.find("m:dataValidations", NS)
            if dvn is not None:
                for dv in dvn:
                    f1 = dv.find("m:formula1", NS)
                    f2 = dv.find("m:formula2", NS)
                    dvs.append({"sqref": dv.get("sqref"), "type": dv.get("type"), "operator": dv.get("operator"),
                                "f1": f1.text if f1 is not None else None, "f2": f2.text if f2 is not None else None})
            # 14 名前空間の入力規則（x14:dataValidations）
            for dv in root.iter("{http://schemas.microsoft.com/office/spreadsheetml/2009/9/main}dataValidation"):
                f1 = dv.find("{http://schemas.microsoft.com/office/spreadsheetml/2009/9/main}formula1")
                sq = dv.find("{http://schemas.microsoft.com/office/excel/2006/main}sqref")
                dvs.append({"x14": True, "type": dv.get("type"), "sqref": sq.text if sq is not None else None,
                            "f1": "".join(f1.itertext()) if f1 is not None else None})
            strings = []
            if name != sheets[0]:
                for c in root.iter(f"{{{NS['m']}}}c"):
                    v = c.find("m:v", NS)
                    if c.get("t") == "s" and v is not None:
                        strings.append(ss[int(v.text)])
            # 9 行目以降の数式（A 列など）
            fml9 = {}
            for c in root.iter(f"{{{NS['m']}}}c"):
                m = re.fullmatch(r"([A-Z]+)(\d+)", c.get("r") or "")
                if m and int(m.group(2)) in (9, 10, 1003, 1004):
                    fml = c.find("m:f", NS)
                    fml9[c.get("r")] = {"f": fml.text if fml is not None else None, "t": fml.get("t") if fml is not None else None,
                                        "ref": fml.get("ref") if fml is not None else None}
            res["sheet_data"][name] = {"cells_1_9": cells, "validations": dvs, "strings": strings[:400], "formula_rows": fml9}
        allres[pathlib.Path(path).name] = res
    out = OUT / "xlsx_check.json"
    out.write_text(json.dumps(allres, ensure_ascii=False, indent=1), encoding="utf-8")
    print("written", out)


# ---------------------------------------------------------------- 計算
def calc():
    OUT.mkdir(parents=True, exist_ok=True)
    R = {}

    def thr(base, mode):
        x = Fraction(base) * Fraction(5, 100)
        if mode == "floor":
            e = x.numerator // x.denominator
        elif mode == "ceil":
            e = -((-x.numerator) // x.denominator)
        elif mode == "round_half_up":
            e = int((x + Fraction(1, 2)).numerator // (x + Fraction(1, 2)).denominator)
        else:
            raise ValueError(mode)
        return min(max(e, 0), 100_000)

    def normal(C, base, mode="floor"):
        return min(max(C - thr(base, mode), 0), 2_000_000)

    def selfmed(C):
        return min(max(C - 12_000, 0), 88_000)

    # H6：D×0.05 が整数になるのは D が20の倍数のときだけ。端数は0.05の倍数
    bad = [d for d in range(0, 200_001) if ((d * 5) % 100 == 0) != (d % 20 == 0)]
    fr = sorted({Fraction(d * 5, 100) - (d * 5) // 100 for d in range(0, 2001)})
    R["H6_multiple_of_20"] = {"counterexamples_0_200000": len(bad), "distinct_fractions": [str(f) for f in fr],
                              "fractions_are_multiples_of_0.05": all((f / Fraction(1, 20)).denominator == 1 for f in fr)}
    # 10万円になる境目：5%が10万円に達する D
    R["threshold_cap_at_D"] = {"D_for_100000": 2_000_000, "thr(1_999_999)": thr(1_999_999, "floor"), "thr(2_000_000)": thr(2_000_000, "floor"),
                               "thr(2_000_019)": thr(2_000_019, "floor")}
    # S3（基礎）と S3-1
    P1, U1, P2, P3, P4, P5 = 120_000, 150_000, 180_000, 60_000, 50_000, 40_000
    p1_after = P1 - min(U1, P1)
    father_C = p1_after + P2 + P3
    father = normal(father_C, 5_000_000)
    mother = normal(P4 + P5, 1_150_000)
    R["S3"] = {"P1_after": p1_after, "father_C": father_C, "father": father, "mother": mother,
               "father_if_hoten_pooled": normal(P1 + P2 + P3 - U1, 5_000_000),
               "father_variant_P3_excluded": normal(p1_after + P2, 5_000_000)}
    A, B = P1 + P2 + P3, min(U1, P1)
    R["S3-1"] = {"father": {"A": A, "B": B, "C": max(A - B, 0), "D": 5_000_000, "E": 5_000_000 * 5 // 100, "F": thr(5_000_000, "floor"),
                            "G": normal(max(A - B, 0), 5_000_000)},
                 "father_if_B_150000": normal(max(A - U1, 0), 5_000_000),
                 "mother": {"A": P4 + P5, "B": 0, "C": P4 + P5, "D": 1_150_000, "E": str(Fraction(1_150_000 * 5, 100)), "F": thr(1_150_000, "floor"),
                            "G": normal(P4 + P5, 1_150_000)}}
    # S3-2：端数
    rows = []
    for D in (1_150_000, 1_150_001, 1_150_019):
        rows.append({"D": D, "Dx0.05": str(Fraction(D * 5, 100)), "E_floor": thr(D, "floor"),
                     "G_floor": normal(90_000, D, "floor"), "G_round": normal(90_000, D, "round_half_up"), "G_ceil": normal(90_000, D, "ceil")})
    R["S3-2"] = rows
    # S3-3：補塡の確定額
    R["S3-3"] = {}
    for name, fixed in (("a", 150_000), ("b", 100_000), ("c", 180_000)):
        p1a = P1 - min(fixed, P1)
        R["S3-3"][name] = {"after_P1": p1a, "C": p1a + P2 + P3, "G": normal(p1a + P2 + P3, 5_000_000)}
    # S3-4：年またぎのあん分
    P1a, P1b, U = 60_000, 60_000, 90_000
    u_a = Fraction(U * P1a, P1a + P1b)
    u_b = U - u_a
    R["S3-4"] = {"U_R7": str(u_a), "U_R8": str(u_b), "C_R7": int(P1a - u_a) + P2 + P3, "G_R7": normal(int(P1a - u_a) + P2 + P3, 5_000_000),
                 "C_R8": int(P1b - u_b), "G_R8": normal(int(P1b - u_b), 5_000_000),
                 "falsifier_G_R7_if_all_to_P1a": normal(P1a - min(U, P1a) + P2 + P3, 5_000_000)}
    # S3-5：セルフとの選択（母、D=1,150,000）
    OTC = 30_000
    R["S3-5"] = {"a": {"normal": normal(P4 + P5 + OTC, 1_150_000), "self": selfmed(OTC), "normal_if_otc_excluded": normal(P4 + P5, 1_150_000)},
                 "b": {"normal": normal(P5 + OTC, 1_150_000), "self": selfmed(OTC), "normal_if_otc_excluded": normal(P5, 1_150_000)},
                 "c": {"normal": normal(P5 + OTC, 1_150_000), "self": None}}
    # S3-6：分けて支払った場合
    R["S3-6"] = {"b_father": normal(father_C + 20_000, 5_000_000), "b_mother": normal(30_000 + P5, 1_150_000)}
    # セルフの上限に達する購入額
    R["selfmed_cap"] = {"C_for_88000": 100_000, "selfmed(100000)": selfmed(100_000), "selfmed(99999)": selfmed(99_999), "selfmed(12000)": selfmed(12_000)}
    # 通常の上限200万円に達する C（D が200万円以上のとき）
    R["normal_cap"] = {"C_for_2000000_when_D>=2000000": 2_100_000, "normal(2_100_000, 3_000_000)": normal(2_100_000, 3_000_000)}
    # 医療費集計フォームの入力例の支払年月日（Excel の1900年日付系のシリアル値。1900-03-01 以後は 1899-12-30 起点で計算できる）
    import datetime
    R["excel_serial"] = {str(n): (datetime.date(1899, 12, 30) + datetime.timedelta(days=n)).isoformat() for n in (43467, 43527)}
    out = OUT / "calc.json"
    out.write_text(json.dumps(R, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(R, ensure_ascii=False, indent=1))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "egov-fetch":
        egov_fetch()
    elif cmd == "egov-check":
        egov_check(sys.argv[2])
    elif cmd == "web-fetch":
        web_fetch()
    elif cmd == "web-check":
        web_check(sys.argv[2])
    elif cmd == "xlsx":
        xlsx(sys.argv[2:])
    elif cmd == "calc":
        calc()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()

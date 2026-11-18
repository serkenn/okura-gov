"""R2X_gaps の独立した検証（反証役）。

別の担当が書いた次の文書の数値・条番号・通達/通知の番号と日付・施行日・適用年分・URL を、一次情報に当たり直して確かめる。
  docs/measurements/20261109_round2_gaps-fetch-and-checks.md   （以下［M］）
  docs/public-sources/20261109_round2_gaps-sources.md          （以下［PS］）
  docs/hypotheses/20261109_round2_gaps-hypotheses.md           （以下［H］）
  docs/inferences/20261109_round2_gaps-inferences.md           （以下［I］）
担当のスクリプト（R2X_gaps_egov.py・R2X_gaps_web.py・R2X_gaps_check.py）とその出力は使わない（比較のために SHA-256 などを読むだけ）。
e-Gov 法令API v2 と行政のサイトから取り直し、自分で書いた（担当とは別の）テキスト化・照合・計算で確かめる。

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_gaps_verify.py egov    # 条文の取得
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_gaps_verify.py web     # 行政の資料の取得
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_gaps_verify.py web2    # 反証を探す追加の取得（税制改正 Q&A の PDF）
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_gaps_verify.py web3    # 反証を探す追加の取得（質疑応答事例（所得税）の目次）
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_gaps_verify.py check   # 照合（ネットワークなし）

- e-Gov 法令API v2 の使い方は scripts/R1_egov_articles.py・scripts/IMPL_kyuyo_fetch.py を読んで写した（import しない）。標準ライブラリのみ。
- ダウンロードは取得ごとに新しい空のディレクトリ .work/downloads/<YYYYMMDD-HHMMSS>_R2X_gaps_verify_<egov|web>/ に置く
  （信頼できないデータ。その中で何も実行しない）。HTML から取り出したテキストは scripts/results/R2X_gaps_verify/web/<id>.txt に書く。
- 取得の前にホストごとの robots.txt を取得して urllib.robotparser で判定し、許されない URL は取得しない。
- 出力（scripts/results/R2X_gaps_verify/）：egov_manifest.json、web_manifest.json・web2_manifest.json・web3_manifest.json、web/<id>.txt、checks.json、checks.md
- PDF はテキスト化しない（Read ツールのページ指定で読み、読んだページと結果は実測の文書に書く）。
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
import urllib.robotparser

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
SLEEP = 1.5
OUT = ROOT / "scripts" / "results" / "R2X_gaps_verify"

# (略称, law_id（None なら法令名で検索）, 法令名, [asof...], 改正附則を含めるか)
LAWS = [
    ("shotoku", "340AC0000000033", "所得税法", ["2025-12-31", "2026-12-31", "2027-01-01"], True),
    ("shotoku-rei", "340CO0000000096", "所得税法施行令", ["2025-12-31"], False),
    ("shotoku-ki", "340M50000040011", "所得税法施行規則", ["2026-11-09", "2026-12-31", "2027-01-01"], True),
    ("sochi", "332AC0000000026", "租税特別措置法", ["2024-12-31", "2025-12-31", "2026-12-31", "2027-01-01"], False),
    ("sochi-rei", "332CO0000000043", "租税特別措置法施行令", ["2025-12-31", "2026-12-31"], False),
    ("sochi-ki", None, "租税特別措置法施行規則", ["2025-12-31", "2026-12-31"], False),
    ("chiho", "325AC0000000226", "地方税法", ["2026-01-01", "2027-01-01"], True),
]
REVISIONS = [("shotoku", "340AC0000000033"), ("shotoku-ki", "340M50000040011")]

TA = "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/"
WA = "https://web.archive.org/web/"
WEB = {
    # 国税庁
    "ta_1175": TA + "1175.htm",
    "ta_1810": TA + "1810.htm",
    "ta_1810_qa": TA + "1810_qa.htm",
    "ta_1411": TA + "1411.htm",
    "ta_1199": TA + "1199.htm",
    "ta_1500": TA + "1500.htm",
    "kihon_01_07": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/01/07.htm",
    "kihon_04_09": "https://www.nta.go.jp/law/tsutatsu/kihon/shotoku/04/09.htm",
    "tokushu_chui": "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tokushu/shinkoku-tyuui/",
    "tebiki_r07_3_3_15": "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/2025/03/order3/3-3_15.htm",
    "nencho2025_qa": "https://www.nta.go.jp/publication/pamph/gensen/nencho2025/qa.htm",
    "nencho2026_qa": "https://www.nta.go.jp/publication/pamph/gensen/nencho2026/qa.htm",
    "sochitsu_41_3_11": "https://www.nta.go.jp/law/tsutatsu/kobetsu/shotoku/sochiho/801226/sinkoku/57/41/03_2.htm",
    "sochitsu_41_3_12": "https://www.nta.go.jp/law/tsutatsu/kobetsu/shotoku/sochiho/801226/sinkoku/57/41/03_4.htm",
    "keisan_r7_kinro_cid472": "https://www.keisan.nta.go.jp/r7yokuaru/cat2/cat22/cat228/cid472.html",
    "keisan_r7_kinro_index": "https://www.keisan.nta.go.jp/r7yokuaru/cat2/cat22/cat228/index.html",
    # 日本年金機構
    "gigishokai_index": "https://www.nenkin.go.jp/service/seidozenpan/gigishokai.html",
    "gigishokai_kounen_tekiyou": "https://www.nenkin.go.jp/service/seidozenpan/gigishokai.files/kounen_tekiyou.pdf",
    "gigishokai_kokunen_tekiyou": "https://www.nenkin.go.jp/service/seidozenpan/gigishokai.files/kokunen_tekiyou.pdf",
    "faq_19to22_income": "https://www.nenkin.go.jp/section/faq/kounen/dependents/aged19to22/income.html",
    "vaccine_20220225": "https://www.nenkin.go.jp/oshirase/taisetu/2022/202202/20220225.html",
    "jimupoint_vol3": "https://www.nenkin.go.jp/service/kounen/info/jimupoint.files/Vol.3.pdf",
    "setsumei_fuyou": "https://www.nenkin.go.jp/shinsei/kounen/tekiyo/hihokensha/20141224.files/setumei.pdf",
    # 厚生労働省
    "mhlw_000991674": "https://www.mhlw.go.jp/content/12400000/000991674.pdf",
    "mhlw_T251006S0060": "https://www.mhlw.go.jp/hourei/doc/tsuchi/T251006S0060.pdf",
    "mhlw_00tc5007_p1": "https://www.mhlw.go.jp/web/t_doc?dataId=00tc5007&dataType=1&pageNo=1",
    "mhlw_00tc5007_p2": "https://www.mhlw.go.jp/web/t_doc?dataId=00tc5007&dataType=1&pageNo=2",
    "mhlw_000744680_saishuchi": "https://www.mhlw.go.jp/content/000744680.pdf",
    "mhlw_00tc5958_p1": "https://www.mhlw.go.jp/web/t_doc?dataId=00tc5958&dataType=1&pageNo=1",
    "mhlw_newpage_19044": "https://www.mhlw.go.jp/stf/newpage_19044.html",
    "mhlw_nenkin_0000086587": "https://www.mhlw.go.jp/file/06-Seisakujouhou-12500000-Nenkinkyoku/0000086587.pdf",
    "mhlw_shinsa_r02_03_15_01": "https://www.mhlw.go.jp/topics/bukyoku/shinsa/syakai/dl/05-r02_03/15_01.pdf",
    # 総務省
    "soumu_kanto_110113_1": "https://www.soumu.go.jp/kanku/kanto/pdf/110113_1.pdf",
    "soumu_kanto_120607_5": "https://www.soumu.go.jp/kanku/kanto/pdf/120607_5.pdf",
    # 協会けんぽ
    "kyoukai_covid19tokurei_nsyutoku": "https://www.kyoukaikenpo.or.jp/~/media/Files/honbu/g2/cat230/covid19tokurei_nsyutoku.pdf",
    "kyoukai_covid19i_fuyousaikakunin": "https://www.kyoukaikenpo.or.jp/~/media/Files/honbu/event/covid19/covid19i_fuyousaikakunin.pdf",
    "kyoukai_faq_dependent_status": "https://www.kyoukaikenpo.or.jp/faq/dependent_status/",
    # Internet Archive（TA No.1810 の過去の版）。CDX は collapse なし（すべての保存）と collapse=digest（内容の違う保存）の両方を取る
    "cdx_ta_1810_digest": "https://web.archive.org/cdx/search/cdx?url=www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1810.htm&output=json&fl=timestamp,statuscode,digest,length&collapse=digest",
    "wa_ta_1810_20241105": WA + "20241105195653id_/https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1810.htm",
    "wa_ta_1810_20250317": WA + "20250317120454id_/https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1810.htm",
    "wa_ta_1810_20251105": WA + "20251105081756id_/https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1810.htm",
    "wa_ta_1810_20260915": WA + "20260915033802id_/https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1810.htm",
    # ［PS］§7 の e-Gov 法令検索のページ（URL が生きているかだけを見る）
    "egov_page_shotoku": "https://laws.e-gov.go.jp/law/340AC0000000033",
    "egov_page_shotoku_ki": "https://laws.e-gov.go.jp/law/340M50000040011",
    "egov_page_sochi": "https://laws.e-gov.go.jp/law/332AC0000000026",
    "egov_page_sochi_rei": "https://laws.e-gov.go.jp/law/332CO0000000043",
    "egov_page_sochi_ki": "https://laws.e-gov.go.jp/law/332M50000040015",
    "egov_page_chiho": "https://laws.e-gov.go.jp/law/325AC0000000226",
}


# 反証を探すための追加の取得（web2）：TA No.1810 の（注意事項）（4）が案内する税制改正の Q&A（令和7年5月・令和8年5月）。
# 家内労働者等の特例の所得だけの人が扶養親族に当たる上限を、国税庁が別の資料でどう書いているかを見る。
WEB2 = {
    "nta_qa_r7_kiso_0025005_051": "https://www.nta.go.jp/publication/pamph/gensen/0025005-051.pdf",
    "nta_qa_r8_kiso_0026005_024": "https://www.nta.go.jp/users/gensen/2026kiso/pdf/0026005-024.pdf",
    "ta_1810_pdf": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/pdf/1810.pdf",
}

# 反証を探すための追加の取得（web3）：［PS］§1.5 の「質疑応答事例（所得税）に勤労学生の範囲の事例は見当たらない」を目次で確かめる。
WEB3 = {
    "shitsugi_shotoku_index": "https://www.nta.go.jp/law/shitsugi/shotoku/01.htm",
}


# ---------------------------------------------------------------- 取得
def http_get(url, accept="*/*", timeout=300, tries=3):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept, "Accept-Language": "ja"})
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.geturl(), dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, url, dict(e.headers or {}), e.read()
        except (TimeoutError, urllib.error.URLError, ConnectionError) as e:
            print("retry", i + 1, url, repr(e), flush=True)
            if i == tries - 1:
                raise
            time.sleep(SLEEP * 10)


def cmd_egov():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_gaps_verify_egov"
    dl.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    man = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "lookups": [], "fetches": [],
           "revisions": [], "errors": []}
    # 法令名から law_id を引き直す（担当の law_id を信じない）
    ids = {}
    for short, law_id, title, _, _ in LAWS:
        url = f"{API}/laws?" + urllib.parse.urlencode({"law_title": title, "response_format": "json"})
        st, _, _, body = http_get(url, accept="application/json")
        (dl / f"lookup_{short}.json").write_bytes(body)
        cands = []
        if st == 200:
            for law in json.loads(body).get("laws", []):
                li = law.get("law_info") or {}
                ri = law.get("revision_info") or law.get("current_revision_info") or {}
                cands.append({"law_id": li.get("law_id"), "law_num": li.get("law_num"), "law_title": ri.get("law_title")})
        exact = [c for c in cands if c["law_title"] == title]
        ids[short] = exact[0]["law_id"] if exact else None
        man["lookups"].append({"short": short, "title": title, "url": url, "status": st, "exact": exact,
                               "expected_law_id": law_id, "match": (law_id is None) or (ids[short] == law_id)})
        print("lookup", short, ids[short], law_id, flush=True)
        time.sleep(SLEEP)
    for short, law_id, title, asofs, with_amend in LAWS:
        law_id = law_id or ids[short]
        for asof in asofs:
            q = {"response_format": "json", "asof": asof}
            if not with_amend:
                q["omit_amendment_suppl_provision"] = "true"
            url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode(q)
            try:
                st, _, _, body = http_get(url, accept="application/json", timeout=600)
                fn = dl / f"{short}_{asof}.json"
                fn.write_bytes(body)
                rec = {"short": short, "law_id": law_id, "asof": asof, "url": url, "status": st, "file": fn.name,
                       "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body), "with_amend_suppl": with_amend}
                if st == 200:
                    d = json.loads(body)
                    ri = d.get("revision_info") or {}
                    li = d.get("law_info") or {}
                    rec.update({"law_title": ri.get("law_title"), "title_ok": ri.get("law_title") == title,
                                "law_num": li.get("law_num"), "law_revision_id": ri.get("law_revision_id"),
                                "amendment_law_num": ri.get("amendment_law_num"),
                                "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                                "amendment_scheduled_enforcement_date": ri.get("amendment_scheduled_enforcement_date"),
                                "current_revision_status": ri.get("current_revision_status")})
                man["fetches"].append(rec)
                print("ok" if st == 200 else "NG", short, asof, rec.get("law_revision_id"), rec.get("current_revision_status"), flush=True)
            except Exception as e:  # noqa: BLE001
                man["errors"].append({"short": short, "asof": asof, "error": repr(e)})
                print("ERR", short, asof, repr(e), flush=True)
            time.sleep(SLEEP)
    for short, law_id in REVISIONS:
        url = f"{API}/law_revisions/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "amendment_date_from": "2025-01-01"})
        st, _, _, body = http_get(url, accept="application/json")
        (dl / f"revisions_{short}.json").write_bytes(body)
        revs = []
        if st == 200:
            for rv in json.loads(body).get("revisions", []):
                revs.append({k: rv.get(k) for k in ("law_revision_id", "amendment_enforcement_date", "amendment_law_num",
                                                   "current_revision_status")})
        man["revisions"].append({"short": short, "url": url, "status": st, "revisions": revs})
        time.sleep(SLEEP)
    (OUT / "egov_manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")


class Extract(html.parser.HTMLParser):
    """HTML の本文テキスト（担当の Page クラスとは別に書いた）。ブロック要素の境で改行し、img の alt は［画像:...］で残す。"""
    SKIP = {"script", "style", "noscript"}
    BLOCKS = {"br", "p", "div", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "dt", "dd", "table", "section", "article"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self._skip, self.title, self._in_title = [], 0, "", False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag in self.BLOCKS:
            self.parts.append("\n")
        if tag == "img" and not self._skip:
            alt = dict(attrs).get("alt")
            if alt:
                self.parts.append(f"［画像:{alt}］")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in self.BLOCKS:
            self.parts.append("\n")

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
        c = "cp932" if c.lower() in ("shift_jis", "sjis", "x-sjis", "shift-jis") else c
        try:
            return body.decode(c)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", "replace")


def cmd_web(name="web", urls=None):
    urls = WEB if urls is None else urls
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_gaps_verify_{name}"
    dl.mkdir(parents=True, exist_ok=False)
    tx = OUT / "web"
    tx.mkdir(parents=True, exist_ok=True)
    man = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "robots": {}, "results": []}
    robots = {}
    for sid, url in urls.items():
        host = urllib.parse.urlsplit(url).hostname
        if host not in robots:
            st, _, _, body = http_get(f"https://{host}/robots.txt", timeout=60)
            (dl / f"robots_{host}.txt").write_bytes(body)
            rp = urllib.robotparser.RobotFileParser()
            if st == 200:
                rp.parse(body.decode("utf-8", "replace").splitlines())
            elif st in (401, 403):
                rp.disallow_all = True
            else:
                rp.allow_all = True
            robots[host] = rp
            man["robots"][host] = {"status": st, "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
            time.sleep(SLEEP)
        rec = {"id": sid, "url": url, "robots_allowed": robots[host].can_fetch(UA, url)}
        if not rec["robots_allowed"]:
            rec["skipped"] = True
            man["results"].append(rec)
            print("SKIP(robots)", sid, flush=True)
            continue
        try:
            st, final, hdr, body = http_get(url, timeout=120)
            ctype = hdr.get("Content-Type", "")
            is_pdf = "pdf" in ctype.lower() or url.lower().endswith(".pdf")
            is_json = "json" in ctype.lower() or "output=json" in url
            ext = ".pdf" if is_pdf else (".json" if is_json else ".html")
            (dl / f"{sid}{ext}").write_bytes(body)
            rec.update({"status": st, "final_url": final, "content_type": ctype, "bytes": len(body),
                        "sha256": hashlib.sha256(body).hexdigest(), "last_modified": hdr.get("Last-Modified"),
                        "saved": f"{sid}{ext}"})
            if st == 200 and not is_pdf:
                t = decode(body, ctype)
                if not is_json:
                    p = Extract()
                    p.feed(t)
                    t = re.sub(r"[ \t\r\u3000]*\n[ \t\r\u3000]*", "\n", "".join(p.parts))
                    t = re.sub(r"\n{2,}", "\n", t).strip()
                    rec["title"] = " ".join(p.title.split())
                (tx / f"{sid}.txt").write_text(f"# source={url}\n# fetched_at={ts}\n# sha256={rec['sha256']}\n\n{t}\n", encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            rec["error"] = repr(e)
        man["results"].append(rec)
        print(sid, rec.get("status"), rec.get("last_modified"), (rec.get("sha256") or "")[:16], rec.get("error", ""), flush=True)
        time.sleep(SLEEP)
    (OUT / f"{name}_manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- 照合（check）：ネットワークなし
# 条文のテキスト化・照合は担当の render（R2X_gaps_egov.py）とは別に書いた。
def text_of(n):
    """ノードの文字列を連結する（ルビの読み Rt は落とす。空白は入れない）。"""
    if isinstance(n, str):
        return n
    if n.get("tag") == "Rt":
        return ""
    return "".join(text_of(c) for c in n.get("children", []))


def kids(n, tag=None):
    return [c for c in n.get("children", []) if isinstance(c, dict) and (tag is None or c.get("tag") == tag)]


def walk_tree(n, fn, anc=()):
    if isinstance(n, dict):
        fn(n, anc)
        for c in n.get("children", []):
            walk_tree(c, fn, anc + (n,))


class Law:
    def __init__(self, path):
        d = json.loads(pathlib.Path(path).read_bytes())
        self.rev = d.get("revision_info") or {}
        self.root = d["law_full_text"]
        self.main, self.orig_suppl, self.amend_suppl = {}, [], []

        def fn(n, anc):
            t = n.get("tag")
            sp = [a for a in anc if a.get("tag") == "SupplProvision"]
            if t == "Article":
                if not sp:
                    self.main.setdefault(n["attr"].get("Num"), n)
                elif "AmendLawNum" not in (sp[-1].get("attr") or {}):
                    self.orig_suppl.append(n)
            if t == "SupplProvision" and (n.get("attr") or {}).get("AmendLawNum"):
                self.amend_suppl.append(n)
        walk_tree(self.root, fn)

    def suppl_article(self, amend_re, num):
        for s in self.amend_suppl:
            if re.search(amend_re, s["attr"]["AmendLawNum"]):
                found = []
                walk_tree(s, lambda n, a: found.append(n) if n.get("tag") == "Article" and n["attr"].get("Num") == num else None)
                if found:
                    return found[0]
        return None

    def articles_with(self, *kws):
        """本則（と原始附則）の条のうち、kws をすべて含む条の番号。"""
        out = [("本則", k) for k, a in self.main.items() if all(w in text_of(a) for w in kws)]
        out += [("原始附則", a["attr"].get("Num")) for a in self.orig_suppl if all(w in text_of(a) for w in kws)]
        return out


def locate(node, path):
    """path の例：'1'（第1項）、'1/32'（第1項第32号）、'4/6'（第4項第6号）、'1/1/4'（第1項第1号の4つ目の細分）。"""
    cur = node
    if node is None:
        return None
    if not path:
        return cur
    for lvl, st in zip(["Paragraph", "Item", "Subitem1", "Subitem2"], path.split("/")):
        nxt = None
        for c in kids(cur, lvl):
            if c.get("attr", {}).get("Num") == st:
                nxt = c
                break
        if nxt is None:
            return None
        cur = nxt
    return cur


def norm(s):
    s = unicodedata.normalize("NFKC", s or "")
    return re.sub(r"\s", "", s)


def in_order(text, frags):
    """frags が text の中にこの順に現れるか（NFKC 正規化・空白除去のうえで）。見つからなかった断片を返す。"""
    t, pos = norm(text), 0
    for f in frags:
        f2 = norm(f)
        i = t.find(f2, pos)
        if i < 0:
            return False, f
        pos = i + len(f2)
    return True, None


def egov_dir():
    m = json.loads((OUT / "egov_manifest.json").read_text(encoding="utf-8"))
    return ROOT / m["download_dir"], m


_LAWS = {}


def L(short, asof):
    key = (short, asof)
    if key not in _LAWS:
        d, _ = egov_dir()
        _LAWS[key] = Law(d / f"{short}_{asof}.json")
    return _LAWS[key]


def node_of(short, asof, where, art, path):
    law = L(short, asof)
    a = law.main.get(art) if where == "main" else law.suppl_article(where, art)
    return locate(a, path)


R7_13 = r"令和七年.*法律第(十三|一三)号"
R8_12 = r"令和八年.*法律第(十二|一二)号"
R7K_18 = r"令和七年.*財務省令第(十八|一八)号"
R8K_17 = r"令和八年.*財務省令第(十七|一七)号"
S3 = ["2025-12-31", "2026-12-31", "2027-01-01"]

# (ID, 主張している文書と節, 主張の要約, 略称, [asof...], 'main' か改正附則の正規表現, 条, path, [断片...])
LAWCLAIMS = [
    ("L01", "M C1・PS 1.1", "所法2①三十二 の「自己の勤労に基づいて得た…」と10万円の要件（3版）", "shotoku", S3, "main", "2", "1/32",
     ["自己の勤労に基づいて得た事業所得、給与所得、退職所得又は雑所得（以下この号において「給与所得等」という。）を有するもののうち、合計所得金額が",
      "であり、かつ、合計所得金額のうち給与所得等以外の所得に係る部分の金額が十万円以下であるものをいう。"]),
    ("L02a", "M C1・PS 1.1", "勤労学生の合計所得金額 85万円（令和7年分の版）", "shotoku", ["2025-12-31"], "main", "2", "1/32", ["合計所得金額が八十五万円以下であり"]),
    ("L02b", "M C1・PS 1.1", "勤労学生の合計所得金額 89万円（令和8年分の版・2027-01-01版）", "shotoku", ["2026-12-31", "2027-01-01"], "main", "2", "1/32", ["合計所得金額が八十九万円以下であり"]),
    ("L03a", "M C4", "2①三十二ロ「各種学校の生徒」（2025-12-31版）", "shotoku", ["2025-12-31"], "main", "2", "1/32", ["各種学校の生徒で政令で定める課程"]),
    ("L03b", "M C4", "2①三十二ロ「各種学校の学生又は生徒」（2026-12-31版）", "shotoku", ["2026-12-31"], "main", "2", "1/32", ["各種学校の学生又は生徒で政令で定める課程"]),
    ("L04", "PS 1.1", "令和8年法律第12号 附則第1条第4号イ（2026-12-01 施行。2①三十二（ロを除く）・86①一）", "shotoku", ["2027-01-01"], R8_12, "1", "1/4",
     ["令和八年十二月一日", "第一条中所得税法第二条第一項第三十二号の改正規定（同号ロに係る部分を除く。）、同項第三十三号及び第三十四号の改正規定", "同法第八十六条第一項第一号の改正規定"]),
    ("L05", "PS 1.1", "令和8年法律第12号 附則第2条第1項（令和8年分以後）", "shotoku", ["2027-01-01"], R8_12, "2", "1",
     ["第二条第一項（第三十二号（ロに係る部分を除く。）、第三十三号及び第三十四号に係る部分に限る。）の規定は、令和八年分以後の所得税について適用"]),
    ("L06", "PS 1.1", "令和7年法律第13号 附則第2条第1項（85万円などは令和7年分以後）", "shotoku", ["2027-01-01"], R7_13, "2", "1",
     ["第二条第一項（第三十二号、第三十三号及び第三十四号に係る部分に限る。）の規定は、令和七年分以後の所得税について適用"]),
    ("L07", "PS 4.1", "令和7年法律第13号 附則第1条第1号（2025-12-01 施行。86①を含む）", "shotoku", ["2027-01-01"], R7_13, "1", "1/1",
     ["令和七年十二月一日", "第一条中所得税法第二条第一項第三十二号の改正規定", "同法第八十六条第一項の改正規定"]),
    ("L08", "PS 4.1", "令和7年法律第13号 附則第7条（86 は令和7年分以後）", "shotoku", ["2027-01-01"], R7_13, "7", "1",
     ["新所得税法第八十六条の規定は、令和七年分以後の所得税について適用"]),
    ("L09", "PS 4.1", "令和8年法律第12号 附則第9条（86 は令和8年分以後）", "shotoku", ["2027-01-01"], R8_12, "9", "1",
     ["新所得税法第八十六条の規定は、令和八年分以後の所得税について適用"]),
    ("L10", "PS 1.1", "所得税法施行令第11条の3 は勤労学生の範囲（学校・課程）", "shotoku-rei", ["2025-12-31"], "main", "11_3", "",
     ["（勤労学生の範囲）", "法第二条第一項第三十二号ロ（定義）に規定する政令で定める者は", "課程"]),
    ("L11", "H HG3（PS-CON）", "合計所得金額は所法2①三十イ(2) で定義（第22条の総所得金額等の合計）", "shotoku", ["2025-12-31", "2026-12-31"], "main", "2", "1/30",
     ["第七十条（純損失の繰越控除）及び第七十一条（雑損失の繰越控除）の規定を適用しないで計算した場合における第二十二条（課税標準）に規定する総所得金額、退職所得金額及び山林所得金額の合計額（以下この条において「合計所得金額」という。）"]),
    ("L12a", "M C2・PS 2.3", "扶養親族 58万円・同一生計配偶者 58万円（令和7年分の版）", "shotoku", ["2025-12-31"], "main", "2", "1/34", ["合計所得金額が五十八万円以下である者をいう"]),
    ("L12b", "M C2・PS 2.3", "同一生計配偶者 58万円（令和7年分の版）", "shotoku", ["2025-12-31"], "main", "2", "1/33", ["合計所得金額が五十八万円以下である者をいう"]),
    ("L12c", "M C2・PS 2.3", "扶養親族 62万円（令和8年分の版）", "shotoku", ["2026-12-31"], "main", "2", "1/34", ["合計所得金額が六十二万円以下である者をいう"]),
    ("L12d", "M C2・PS 2.3", "同一生計配偶者 62万円（令和8年分の版）", "shotoku", ["2026-12-31"], "main", "2", "1/33", ["合計所得金額が六十二万円以下である者をいう"]),
    ("L13", "H HG3（PS-IT）", "控除対象扶養親族（2①三十四の二）は居住者について年齢16歳以上", "shotoku", ["2025-12-31", "2026-12-31"], "main", "2", "1/34_2", ["控除対象扶養親族", "居住者年齢十六歳以上の者"]),
    ("L14", "PS 3.1", "特別障害者は所法2①二十九", "shotoku", ["2025-12-31"], "main", "2", "1/29", ["特別障害者", "重度の障害がある者"]),
    ("L15", "H HG3", "所法85⑥（二以上の居住者の扶養親族に当たる者は、いずれか一の居住者の扶養親族にのみ該当するとみなす）", "shotoku", ["2025-12-31", "2026-12-31"], "main", "85", "6",
     ["二以上の居住者の扶養親族又は特定親族に該当する者がある場合には", "いずれか一の居住者の扶養親族又は特定親族にのみ該当するものとみなす"]),
    ("L16", "M C2・PS 2.3・I IG2", "特定親族（所法84の2①）：合計所得金額123万円以下・控除対象扶養親族を除く／85万円以下は63万円", "shotoku", ["2025-12-31", "2026-12-31"], "main", "84_2", "1",
     ["年齢十九歳以上二十三歳未満の親族", "合計所得金額が百二十三万円以下", "控除対象扶養親族に該当しないもの（以下この項及び次項において「特定親族」という。）", "合計所得金額が八十五万円以下である特定親族六十三万円"]),
    ("L17", "I IG2・IG3", "特定扶養親族の扶養控除は63万円、一般は38万円（所法84①）", "shotoku", ["2025-12-31", "2026-12-31"], "main", "84", "1",
     ["その控除対象扶養親族一人につき三十八万円（その者が特定扶養親族である場合には六十三万円"]),
    ("L18a", "M C2・PS 2.3", "家内労働者等の特例額 65万円（措法27①、令和7年分の版）", "sochi", ["2025-12-31"], "main", "27", "1", ["必要経費に算入すべき金額の合計額が六十五万円"]),
    ("L18b", "M C2・PS 2.3", "家内労働者等の特例額 69万円（措法27①、令和8年分の版）", "sochi", ["2026-12-31"], "main", "27", "1", ["必要経費に算入すべき金額の合計額が六十九万円"]),
    ("L19", "PS 3.3・I IG1・IG3", "措法29の4②：令和8年又は令和9年、69万1千円以上220万円未満。第2号は74万1千円以上219万1千円未満で収入−74万円", "sochi", ["2026-12-31"], "main", "29_4", "2",
     ["令和八年又は令和九年において、その年中の給与等の収入金額が六十九万千円以上二百二十万円未満である場合", "七十四万千円以上二百十九万千円未満である場合には、当該給与等に係る給与所得の金額は、当該収入金額から七十四万円を控除した残額"]),
    ("L20a", "M C2・PS 4.1・H HG4", "措法41の16の2（令和7年分の版）：655万円以下、86①一の金額に加算、132万円以下37万円…489万円超5万円", "sochi", ["2025-12-31"], "main", "41_16_2", "1",
     ["六百五十五万円", "以下である場合における同法第八十六条第二項に規定する基礎控除の額は、同条第一項の規定にかかわらず、同項第一号に定める金額に", "百三十二万円以下である場合三十七万円",
      "百三十二万円を超え三百三十六万円以下である場合三十万円", "三百三十六万円を超え四百八十九万円以下である場合十万円", "四百八十九万円を超える場合五万円"]),
    ("L20b", "M C2・H HG4", "措法41の16の2（令和8年分の版）：489万円以下42万円・489万円超（655万円以下）5万円", "sochi", ["2026-12-31"], "main", "41_16_2", "1",
     ["六百五十五万円", "四百八十九万円以下である場合四十二万円", "四百八十九万円を超える場合五万円"]),
    ("L21-1", "PS 3.1・H HG3", "措法41の3の11①", "sochi", ["2024-12-31", "2025-12-31", "2026-12-31", "2027-01-01"], "main", "41_3_11", "1",
     ["その年中の給与等の収入金額が八百五十万円を超える居住者で、特別障害者に該当するもの又は年齢二十三歳未満の扶養親族を有するもの若しくは特別障害者である同一生計配偶者若しくは扶養親族を有するもの",
      "当該給与等の収入金額が千万円を超える場合には、千万円）から八百五十万円を控除した金額の百分の十に相当する金額を、その年分の給与所得の金額から控除する。"]),
    ("L21-2", "PS 3.1・H HG3", "措法41の3の11②", "sochi", ["2024-12-31", "2025-12-31", "2026-12-31", "2027-01-01"], "main", "41_3_11", "2",
     ["その年分の給与所得控除後の給与等の金額及び公的年金等に係る雑所得の金額がある居住者で、当該給与所得控除後の給与等の金額及び当該公的年金等に係る雑所得の金額の合計額が十万円を超えるもの",
      "合計額から十万円を控除した残額を、その年分の給与所得の金額（前項の規定の適用がある場合には、同項の規定による控除をした残額）から控除する。"]),
    ("L21-3", "PS 3.1・H HG3", "措法41の3の11③（12月31日の現況、死亡・出国）", "sochi", ["2025-12-31", "2026-12-31"], "main", "41_3_11", "3",
     ["その年十二月三十一日（その居住者がその年の中途において死亡し、又は出国をする場合には、その死亡又は出国の時）の現況による。ただし、その判定に係る者がその当時既に死亡している場合は、その死亡の時の現況による。"]),
    ("L21-4", "PS 3.1・H HG3", "措法41の3の11④一〜七の参照先", "sochi", ["2025-12-31", "2026-12-31"], "main", "41_3_11", "4",
     ["所得税法第二十八条第一項に規定する給与等", "所得税法第二条第一項第二十九号に規定する特別障害者", "所得税法第二条第一項第三十四号に規定する扶養親族",
      "所得税法第二条第一項第三十三号に規定する同一生計配偶者", "所得税法第二十八条第三項に規定する給与所得控除額を控除した残額（同条第四項の規定の適用がある場合には、同項に規定する給与所得控除後の給与等の金額に相当する金額）",
      "所得税法第三十五条第二項第一号に掲げる金額", "所得税法第二条第一項第四十二号に規定する出国"]),
    ("L21-4-6", "PS 3.1・M C3", "措法41の3の11④六 の 2027-01-01 版の追加文言", "sochi", ["2027-01-01"], "main", "41_3_11", "4/6",
     ["所得税法第三十五条第二項第一号に掲げる金額（同条第五項の規定の適用がある場合には、その適用がないものとして計算した金額）"]),
    ("L21-5", "PS 3.1", "措法41の3の11⑤（所法22②一の読替え）", "sochi", ["2025-12-31", "2026-12-31"], "main", "41_3_11", "5",
     ["第一項又は第二項の規定の適用がある場合における所得税法第二十二条の規定の適用については、同条第二項第一号中「給与所得の金額」とあるのは、「給与所得の金額から租税特別措置法第四十一条の三の十一第一項又は第二項（所得金額調整控除）の規定による控除をした残額」とする。"]),
    ("L21-6", "PS 3.1・H HG3", "措法41の3の11⑥（第2項だけ、所法121③の読替え）", "sochi", ["2025-12-31", "2026-12-31"], "main", "41_3_11", "6",
     ["第二項の規定の適用がある場合における所得税法第百二十一条第三項の規定の適用については", "第四十一条の三の十一第二項（所得金額調整控除）の規定による控除をした残額"]),
    ("L21-7", "PS 3.1", "措法41の3の11⑦（政令委任）", "sochi", ["2025-12-31", "2026-12-31"], "main", "41_3_11", "7", ["政令で定める"]),
    ("L22-1", "PS 3.2・H HG3", "措法41の3の12①（年末調整は前条第1項だけ）", "sochi", ["2025-12-31", "2026-12-31"], "main", "41_3_12", "1",
     ["所得税法第百九十条", "申告書をその給与等の支払者を経由して", "同条第二号に規定する給与所得控除後の給与等の金額は、当該金額に相当する金額から前条第一項の規定による控除をされる金額に相当する金額を控除した金額"]),
    ("L22-2", "PS 3.2", "措法41の3の12②（最後に給与等の支払を受ける日の前日まで）", "sochi", ["2025-12-31", "2026-12-31"], "main", "41_3_12", "2",
     ["その年最後に給与等の支払を受ける日の前日までに、提出しなければならない"]),
    ("L23-1", "PS 3.3", "措令26の5①（所法69・154・155 の読替え）", "sochi-rei", ["2025-12-31", "2026-12-31"], "main", "26_5", "1",
     ["所得税法第六十九条、第百五十四条及び第百五十五条の規定の適用については", "給与所得の金額から租税特別措置法第四十一条の三の十一第一項又は第二項（所得金額調整控除）の規定による控除をした残額"]),
    ("L23-2", "PS 3.3", "措令26の5②（所令198①一）", "sochi-rei", ["2025-12-31", "2026-12-31"], "main", "26_5", "2", ["所得税法施行令第百九十八条の規定の適用については、同条第一号中「給与所得の金額」"]),
    ("L23-3", "PS 3.3", "措令26の5③（災害減免法の徴収猶予の見積額）", "sochi-rei", ["2025-12-31", "2026-12-31"], "main", "26_5", "3", ["災害被害者に対する租税の減免、徴収猶予等に関する法律第三条第五項の規定による徴収の猶予", "見積額"]),
    ("L23-4", "PS 3.3・H HG3", "措令19の4の2①（2026-12-31 版）", "sochi-rei", ["2026-12-31"], "main", "19_4_2", "1",
     ["法第二十九条の四第二項の規定の適用がある場合における法第四十一条の三の十一第二項の規定の適用については、同条第四項第五号中「同条第四項の規定の適用がある場合には、同項に規定する給与所得控除後の給与等の金額に相当する金額」とあるのは、「第二十九条の四第二項の規定の適用がある場合には、同項の規定を適用した場合の同項に規定する給与所得の金額に相当する金額」とする。"]),
    ("L24a", "PS 3.2", "措規18の23の8（年末調整に係る所得金額調整控除の申告書の記載事項）", "sochi-ki", ["2025-12-31", "2026-12-31"], "main", "18_23_8", "",
     ["（年末調整に係る所得金額調整控除）", "法第四十一条の三の十二第一項に規定する財務省令で定める事項は"]),
    ("L24b", "PS 3.3", "措規18の23の5・18の23の6 は令和6年の特別控除（定額減税）の規定", "sochi-ki", ["2025-12-31", "2026-12-31"], "main", "18_23_5", "", ["（令和六年六月以後に支払われる給与等に係る特別控除の額の控除等）"]),
    ("L24c", "PS 3.3", "同上（18の23の6）", "sochi-ki", ["2025-12-31", "2026-12-31"], "main", "18_23_6", "", ["（令和六年における年末調整に係る特別控除の額の控除等）"]),
    ("L25a", "I IG1", "地方税法314の2①九 勤労学生控除 26万円", "chiho", ["2026-01-01", "2027-01-01"], "main", "314_2", "1/9", ["勤労学生である所得割の納税義務者二十六万円"]),
    ("L25b", "H HG4", "地方税法314の2②（2,400万円以下 43万円ほか）", "chiho", ["2026-01-01", "2027-01-01"], "main", "314_2", "2",
     ["前年の合計所得金額が二千四百万円以下である場合四十三万円", "二千四百万円を超え二千四百五十万円以下である場合二十九万円", "二千四百五十万円を超え二千五百万円以下である場合十五万円"]),
    ("L25c", "H HG1・I IG1", "地方税法314の2⑨（所法2①三十二 を準用）", "chiho", ["2026-01-01", "2027-01-01"], "main", "314_2", "9", ["所得税法第二条第一項第三十二号の規定は、第一項第九号及び第三百十四条の六の勤労学生の意義について準用する"]),
    ("L26a", "M C4・PS 4.1", "所法86①（令和7年分の版）", "shotoku", ["2025-12-31"], "main", "86", "1",
     ["合計所得金額が二千五百万円以下である居住者については", "二千三百五十万円以下である場合五十八万円", "二千三百五十万円を超え二千四百万円以下である場合四十八万円",
      "二千四百万円を超え二千四百五十万円以下である場合三十二万円", "二千四百五十万円を超え二千五百万円以下である場合十六万円"]),
    ("L26b", "M C4・PS 4.1", "所法86①（令和8年分の版・2027-01-01版）", "shotoku", ["2026-12-31", "2027-01-01"], "main", "86", "1",
     ["合計所得金額が二千五百万円以下である居住者については", "二千三百五十万円以下である場合六十二万円", "二千三百五十万円を超え二千四百万円以下である場合四十八万円",
      "二千四百万円を超え二千四百五十万円以下である場合三十二万円", "二千四百五十万円を超え二千五百万円以下である場合十六万円"]),
    ("L26c", "PS 4.1", "所法86②（基礎控除という）", "shotoku", S3, "main", "86", "2", ["前項の規定による控除は、基礎控除という。"]),
    ("L27a", "M C5・PS 5.1", "所法120⑥ が内訳書（2025-12-31・2026-12-31版）", "shotoku", ["2025-12-31", "2026-12-31"], "main", "120", "6", ["その年中の総収入金額及び必要経費の内容を記載した書類を当該申告書に添付しなければならない"]),
    ("L27b", "PS 5.1・H HG5", "所法120⑥（2027-01-01版）：社会保険料控除等の証明書類に代えて明細書", "shotoku", ["2027-01-01"], "main", "120", "6",
     ["社会保険料控除、小規模企業共済等掛金控除、生命保険料控除又は地震保険料控除に関する事項の記載をする居住者", "添付又は提示に代えて", "明細書を当該申告書に添付することができる"]),
    ("L27c", "PS 5.1", "所法120⑦（2027-01-01版）：5年を経過する日までの間、書類の提示・提出", "shotoku", ["2027-01-01"], "main", "120", "7", ["五年を経過する日", "前項に規定する書類の提示又は提出を求めることができる"]),
    ("L27d", "M C5・PS 5.1", "所法120⑧ が内訳書（2027-01-01版）", "shotoku", ["2027-01-01"], "main", "120", "8", ["その年中の総収入金額及び必要経費の内容を記載した書類を当該申告書に添付しなければならない"]),
    ("L27e", "PS 5.1", "所法120⑨ が非永住者の書類（2027-01-01版）", "shotoku", ["2027-01-01"], "main", "120", "9", ["非永住者であつた期間を有する居住者"]),
    ("L27f", "I IG5", "所法120（内訳書の項）：不動産・事業・山林は白色なら常に、業務に係る雑所得は前々年分の収入金額1,000万円超", "shotoku", ["2026-12-31"], "main", "120", "6",
     ["不動産所得、事業所得若しくは山林所得を生ずべき業務を行う居住者が第一項の規定による申告書を提出する場合（当該申告書が青色申告書である場合を除く。）又はその年において雑所得を生ずべき業務を行う居住者でその年の前々年分の当該業務に係る収入金額が千万円を超えるもの"]),
    ("L28a", "M C5・PS 5.1", "所規47の3①② が法120⑥ を引く（2026-11-09・2026-12-31版）", "shotoku-ki", ["2026-11-09", "2026-12-31"], "main", "47_3", "",
     ["法第百二十条第六項（確定所得申告）の規定により確定申告書に添付すべき同項の書類は", "において準用する法第百二十条第六項の規定により"]),
    ("L28b", "M C5・PS 5.1", "所規47の3①② が法120⑧ を引く（2027-01-01版）", "shotoku-ki", ["2027-01-01"], "main", "47_3", "",
     ["法第百二十条第八項（確定所得申告）の規定により確定申告書に添付すべき同項の書類は", "において準用する法第百二十条第八項の規定により"]),
    ("L29", "M C5・PS 5.1", "令和7年財務省令第18号 附則第1条第4号（第47条の3 の改正規定ほか 令和九年一月一日）", "shotoku-ki", ["2027-01-01"], R7K_18, "1", "1/4",
     ["第四十七条の二第十四項の改正規定、同項を同条第十五項とし、同条第十三項の次に一項を加える改正規定、第四十七条の三の改正規定、第四十七条の四の改正規定及び第六十八条の改正規定", "令和九年一月一日"]),
    ("L30", "M C5", "令和8年財務省令第17号 附則第1条第2号（令和九年一月一日：47の2⑭一・53条・別表第五（二十八））", "shotoku-ki", ["2027-01-01"], R8K_17, "1", "1/2",
     ["第四十七条の二第十四項第一号の改正規定、第五十三条の改正規定及び別表第五（二十八）の表の備考２（１２）の改正規定", "令和九年一月一日"]),
    ("L31a", "M C5・PS 5.1", "令和7年法律第13号 附則第1条第5号イ", "shotoku", ["2027-01-01"], R7_13, "1", "1/5",
     ["令和九年一月一日", "第一条中所得税法第百二十条の改正規定（同条第三項第三号に係る部分及び同条第四項第二号に係る部分を除く。）"]),
    ("L31b", "M C5・PS 5.1・H HG5", "令和7年法律第13号 附則第8条第2項", "shotoku", ["2027-01-01"], R7_13, "8", "2",
     ["新所得税法第百二十条第六項及び第七項（これらの規定を新所得税法第百二十二条第三項、第百二十三条第三項、第百二十五条第四項及び第百二十七条第四項において準用する場合を含む。）の規定は、令和九年一月一日以後に令和八年分以後の所得税に係る確定申告書を提出する場合について適用する。"]),
    ("L32a", "M C5・PS 5.1", "令和8年法律第12号 附則第1条第5号イ（所法120 の改正規定、令和九年一月一日）", "shotoku", ["2027-01-01"], R8_12, "1", "1/5",
     ["令和九年一月一日", "同法第百二十条の改正規定"]),
    ("L32b", "M C5・PS 5.1・H HG5", "令和8年法律第12号 附則第10条第1項", "shotoku", ["2027-01-01"], R8_12, "10", "1",
     ["新所得税法第百二十条第六項及び第七項", "令和九年一月一日以後に令和八年分以後の所得税に係る確定申告書を提出する場合について適用する"]),
    ("L33", "PS 3.1・H HG3", "所法22②一 に「給与所得の金額」（措法41の3の11⑤ の読替えの対象）", "shotoku", ["2025-12-31", "2026-12-31"], "main", "22", "2", ["事業所得の金額、給与所得の金額"]),
    ("L34", "PS 3.1", "所法121③（確定申告を要しない場合。公的年金等）", "shotoku", ["2025-12-31", "2026-12-31"], "main", "121", "3", ["公的年金等の収入金額が四百万円以下"]),
    # 検証側で足したもの（［M］§6・［H］HG5 の「分からなかった」の確認）
    ("X01", "M §6・H HG5（未取得の補足）", "所法122③（2027-01-01版）は第120条第3項から第9項までを準用", "shotoku", ["2027-01-01"], "main", "122", "3", ["同条第三項から第九項までの規定は前二項の規定による申告書の提出について"]),
    ("X02", "M §6（未取得の補足）", "所法122③（2026-12-31版）は第120条第3項から第7項までを準用", "shotoku", ["2026-12-31"], "main", "122", "3", ["同条第三項から第七項までの規定は前二項の規定による申告書の提出について"]),
    ("X03", "M §6（未取得の補足）", "所法123③・125④・127④（2027-01-01版）も第120条第3項から第9項まで", "shotoku", ["2027-01-01"], "main", "125", "4", ["同条第三項から第九項までの規定は"]),
    ("X04", "H HG5（未読の補足）", "所規47の2⑭（2027-01-01版）は法120⑥ の明細書の記載事項", "shotoku-ki", ["2027-01-01"], "main", "47_2", "14", ["法第百二十条第六項に規定する財務省令で定める事項は、次に掲げる事項とする"]),
    ("X05", "PS 3.6・H HG3（未確認の補足）", "地方税法313②：総所得金額等は所得税法その他の所得税に関する法令の規定による所法22②の総所得金額等の計算の例により算定", "chiho", ["2026-01-01", "2027-01-01"], "main", "313", "2",
     ["所得税法その他の所得税に関する法令の規定による所得税法第二十二条第二項又は第三項の総所得金額、退職所得金額又は山林所得金額の計算の例により算定するものとする"]),
]
LAWCLAIMS.append(("X03-123", "M §6（未取得の補足）", "所法123③（2027-01-01版）の準用の範囲", "shotoku", ["2027-01-01"], "main", "123", "3", ["第百二十条第三項から第九項までの規定は"]))
LAWCLAIMS.append(("X03-127", "M §6（未取得の補足）", "所法127④（2027-01-01版）の準用の範囲", "shotoku", ["2027-01-01"], "main", "127", "4", ["同条第三項から第九項までの規定は"]))
LAWCLAIMS.append(("L35a", "I IG4", "所法28③五（令和7年分の版）：850万円超は給与所得控除額195万円", "shotoku", ["2025-12-31"], "main", "28", "3/5", ["八百五十万円を超える場合百九十五万円"]))
LAWCLAIMS.append(("L35b", "I IG1", "所法28③一（令和7年分の版）：190万円以下は65万円", "shotoku", ["2025-12-31"], "main", "28", "3/1", ["百九十万円以下である場合六十五万円"]))

# ［M］§2 の表（担当が記録した版）
M_EGOV = [
    ("shotoku", "2025-12-31", "340AC0000000033_20251218_507AC0000000013", "2025-12-18", "PreviousEnforced", "84a2235cb4437184"),
    ("shotoku", "2026-12-31", "340AC0000000033_20261201_508AC0000000012", "2026-12-01", "UnEnforced", "47792299f0fb5a74"),
    ("shotoku", "2027-01-01", "340AC0000000033_20270101_508AC0000000012", "2027-01-01", "UnEnforced", "d4bf435220bc0b0c"),
    ("shotoku-ki", "2026-11-09", "340M50000040011_20261001_507M60000040018", "2026-10-01", "CurrentEnforced", "8721699516ac8202"),
    ("shotoku-ki", "2026-12-31", "340M50000040011_20261211_508M60000040017", "2026-12-11", "UnEnforced", "9ba37bf34afed1f9"),
    ("shotoku-ki", "2027-01-01", "340M50000040011_20270101_508M60000040017", "2027-01-01", "UnEnforced", "1600117df38c4463"),
    ("sochi", "2024-12-31", "332AC0000000026_20241108_506AC0000000008", "2024-11-08", "PreviousEnforced", "696d301305f4cf8c"),
    ("sochi", "2025-12-31", "332AC0000000026_20251231_507AC1000000081", "2025-12-31", "PreviousEnforced", "ef95d90f7bf57e18"),
    ("sochi", "2026-12-31", "332AC0000000026_20261204_508AC0000000012", None, "UnEnforced", "763fce2df2b1e709"),
    ("sochi", "2027-01-01", "332AC0000000026_20270101_508AC0000000012", "2027-01-01", "UnEnforced", "8c6ee577201c3be0"),
    ("sochi-rei", "2025-12-31", "332CO0000000043_20251231_507CO0000000401", "2025-12-31", "PreviousEnforced", "a3f62b67c672c552"),
    ("sochi-rei", "2026-12-31", "332CO0000000043_20261201_508CO0000000098", "2026-12-01", "UnEnforced", "cc9aa8b1a0a429fb"),
    ("sochi-ki", "2025-12-31", "332M50000040015_20251231_507M60000040068", "2025-12-31", "PreviousEnforced", "e61bd52d88b1484a"),
    ("sochi-ki", "2026-12-31", "332M50000040015_20261204_508M60000040021", None, "UnEnforced", "03b356f8297e93b7"),
    ("chiho", "2026-01-01", "325AC0000000226_20260101_507AC0000000041", "2026-01-01", "PreviousEnforced", "ba0a40e550be7762"),
    ("chiho", "2027-01-01", "325AC0000000226_20270101_508AC0000000002", "2027-01-01", "UnEnforced", "ee21722ce5fd1561"),
]

# ［M］§3 の表（id: (status, Last-Modified の日付時刻 or None, SHA-256 先頭16桁 or None)）
M_WEB = {
    "ta_1175": (200, "2026-09-09 01:00:15", "fbf07a1c42e16c68"), "ta_1810": (200, "2026-09-09 01:00:07", "66d23053e2d026aa"),
    "ta_1810_qa": (200, "2026-09-09 01:00:07", "235fea36dfd79690"), "ta_1411": (200, "2026-09-09 01:00:10", "67ede54d9ec7de57"),
    "ta_1199": (200, "2026-09-09 01:00:14", "21507083e62c8014"), "ta_1500": (200, "2026-09-09 01:00:09", "c3be3c0c45cdea73"),
    "kihon_01_07": (200, "2026-10-02 08:30:05", "52d60882df0b13f9"), "kihon_04_09": (200, "2024-11-25 05:00:03", "56b1ea747294e180"),
    "tokushu_chui": (200, "2026-03-17 01:00:11", "8ddc372077153494"), "tebiki_r07_3_3_15": (200, "2025-12-24 08:30:10", "e1ff17e6f41c54fd"),
    "nencho2025_qa": (200, "2025-08-29 08:30:11", "b2444e3094d01017"), "nencho2026_qa": (200, "2026-08-31 08:30:08", "eef620927e52589c"),
    "sochitsu_41_3_11": (200, "2024-11-25 05:00:02", "80a95a91d225b309"), "sochitsu_41_3_12": (200, "2024-11-25 05:00:02", "7fb364b783bfba79"),
    "keisan_r7_kinro_cid472": (200, "2026-11-08 22:01:46", "354599d1789671e3"), "keisan_r7_kinro_index": (200, "2026-11-08 22:01:46", "c938400774962ed6"),
    "gigishokai_index": (200, "2026-10-14 00:26:17", "6a15671a48a12a6d"), "gigishokai_kounen_tekiyou": (200, "2026-02-04 02:07:23", "09ea323c76fc1427"),
    "gigishokai_kokunen_tekiyou": (200, "2023-06-01 02:37:28", "de53c9918f912a20"), "faq_19to22_income": (200, "2026-10-14 00:25:50", "11b58cd4911a88a4"),
    "vaccine_20220225": (200, "2026-10-14 00:25:35", "220ea6471cb59b9e"), "jimupoint_vol3": (200, "2025-08-05 01:40:56", "4fe03d20353a0f57"),
    "setsumei_fuyou": (200, "2026-04-24 05:25:32", "8a3736da2f1fb13c"), "mhlw_000991674": (200, "2022-09-20 09:12:21", "921d44454041f247"),
    "mhlw_T251006S0060": (404, None, "bf7c76fbeda12ebf"), "mhlw_00tc5007_p1": (200, None, "a081730f8443bee3"),
    "mhlw_00tc5007_p2": (200, None, "c35afce1f9b8bbf1"), "mhlw_000744680_saishuchi": (200, "2023-02-09 00:31:26", "09be84652815620b"),
    "mhlw_00tc5958_p1": (200, None, "dfa91134ed04ed3e"), "mhlw_newpage_19044": (200, None, "b81d35b5bbbc9a76"),
    "mhlw_nenkin_0000086587": (200, "2018-06-12 20:19:23", "f2a8b6049f0fe241"), "mhlw_shinsa_r02_03_15_01": (200, "2026-07-10 01:41:16", "f5245cb5c81d5075"),
    "soumu_kanto_110113_1": (200, "2011-01-20 17:16:16", "6b230b6005ec9fc1"), "soumu_kanto_120607_5": (200, "2012-06-12 08:52:33", "f10c78e9304f4491"),
    "kyoukai_covid19tokurei_nsyutoku": (404, None, None), "kyoukai_covid19i_fuyousaikakunin": (404, None, None),
    "kyoukai_faq_dependent_status": (200, None, "e1a2aea39c610220"), "cdx_ta_1810_digest": (200, None, "b1e2256803d77646"),
    "wa_ta_1810_20241105": (200, None, "81c259160e9446ae"), "wa_ta_1810_20250317": (200, None, "20aceecf7eeb5372"),
    "wa_ta_1810_20251105": (200, None, "f8e87aee21d75a4a"), "wa_ta_1810_20260915": (200, None, "66d23053e2d026aa"),
}
M_ROBOTS = {"www.nta.go.jp": 200, "www.nenkin.go.jp": 200, "www.mhlw.go.jp": 200, "www.soumu.go.jp": 200,
            "www.keisan.nta.go.jp": 404, "www.kyoukaikenpo.or.jp": 404, "web.archive.org": 404}

# 公表資料（HTML）の引用。(ID, 文書と節, 資料ID, [断片...])
WEBCLAIMS = [
    ("W01", "PS 1.3", "ta_1175", ["[令和8年4月1日現在法令等]", "勤労学生とは、その年の12月31日の現況で、次の3つの要件のすべてに当てはまる人です。", "（1）給与所得などの勤労による所得があること",
                                  "（2）合計所得金額が85万円以下（注）（令和2年分から令和6年分までは、75万円以下）で、かつ、（1）の勤労に基づく所得以外の所得が10万円以下であること",
                                  "（注）令和8年12月１日に施行され、令和8年分から適用される金額は「89万円以下」です。", "（3）特定の学校の学生、生徒であること"]),
    ("W02", "PS 1.3", "keisan_r7_kinro_cid472", ["(1) 給与所得などの勤労による所得があること", "(2) 合計所得金額が85万円以下（令和６年分以前は75万円以下）で、かつ、(1)の勤労に基づく所得以外の所得が10万円以下であること"]),
    ("W03", "PS 1.3", "tebiki_r07_3_3_15", ["※ 合計所得金額が85万円を超える方や勤労によらない所得が10万円を超える方は、この控除を受けることはできません。"]),
    ("W04", "PS 1.3", "nencho2026_qa", ["〔問５〕", "勤労による所得を有する一定の学生又は生徒等のうち、合計所得金額が89万円以下（給与所得だけの場合は、給与の収入金額が163万円以下）で、かつ、合計所得金額のうち給与所得等以外の所得金額が10万円以下の人（以下「勤労学生」といいます。）は、「勤労学生控除」（控除額27万円）を受けることができます。", "アルバイト収入しかなく"]),
    ("W05", "PS 1.3", "nencho2025_qa", ["〔問５〕", "合計所得金額が85万円以下（給与所得だけの場合は、給与の収入金額が150万円以下）"]),
    ("W06", "PS 1.4", "tokushu_chui", ["原稿料、講演料、印税、放送出演料などの収入がある方", "事業所得に該当する場合を除き、雑所得（業務）として確定申告が必要です。",
                                       "フリマアプリ、ネットオークション、ネット通販、転売、ドロップシッピング、配達代行業、動画配信、アプリ作成・配信、有料メルマガ、アフィリエイト、ギャラ飲み、民泊、カーシェアリング、自宅等の時間貸し等の収入がある方",
                                       "原則、事業所得又は雑所得（業務）として確定申告が必要です。", "生活に通常必要な動産の譲渡による所得は非課税のため、確定申告に含める必要はありません。"]),
    ("W07", "PS 1.4", "ta_1500", ["[令和8年4月1日現在法令等]", "（注）業務に係るものとは、副業に係る収入のうち営利を目的とした継続的なものをいいます。"]),
    ("W08", "PS 1.4", "kihon_04_09", ["（12） 譲渡所得の基因とならない資産の譲渡から生ずる所得（営利を目的として継続的に行う当該資産の譲渡から生ずる所得及び山林の譲渡による所得を除く。）",
                                      "35-2 次に掲げるような所得は、事業所得又は山林所得と認められるものを除き、業務に係る雑所得に該当する。",
                                      "（4）　原稿、さし絵、作曲、レコードの吹き込み若しくはデザインの報酬、放送謝金、著作権の使用料又は講演料等に係る所得", "（7）　営利を目的として継続的に行う資産の譲渡から生ずる所得",
                                      "（注）　事業所得と認められるかどうかは、その所得を得るための活動が、社会通念上事業と称するに至る程度で行っているかどうかで判定する。",
                                      "その所得に係る取引を記録した帳簿書類の保存がない場合（その所得に係る収入金額が300万円を超え、かつ、事業所得と認められる事実がある場合を除く。）には、業務に係る雑所得（資産（山林を除く。）の譲渡から生ずる所得については、譲渡所得又はその他雑所得）に該当する"]),
    ("W09", "PS 1.2", "kihon_01_07", ["〔勤労学生（第32号関係）〕", "2－43", "通信教育生", "2－44", "2－45", "2－45の２", "〔同一生計配偶者等"]),
    ("W10", "PS 2.1", "ta_1810", ["[令和8年4月1日現在法令等]",
                                  "（2）この特例に該当する所得しかない人で、その年の総収入金額が173万円以下の場合は、総所得金額が基礎控除額の104万円以下となりますので、本人に所得税は課されません。また、その年の総収入金額が131万円以下の場合は、扶養者の所得税額の計算上、配偶者控除あるいは扶養控除の対象となります。",
                                  "（注）令和7年分は、基礎控除額が95万円となり、家内労働者等の必要経費の特例における必要経費に算入する金額の最低保障額が65万円であることから、その年の総収入金額が160万円以下の場合は、合計所得金額が基礎控除額の95万円以下となりますので、本人に所得税は課されず、また、扶養者の所得税額の計算上、配偶者控除あるいは扶養控除の対象となります。",
                                  "また、令和2年分から令和6年分までは基礎控除額が48万円（令和元年分以前は、基礎控除額が38万円）となり、", "最低保障額が55万円（令和元年分以前は65万円）であることから、その年の総収入金額が103万円以下の場合は、合計所得金額が基礎控除額の48万円（令和元年分以前は38万円）以下となりますので、本人に所得税は課されず、また、扶養者の所得税額の計算上、配偶者控除あるいは扶養控除の対象となります。"]),
    ("W11", "PS 2.4", "ta_1810", ["（1）給与の収入金額が69万円以上あるときは、この特例は受けられません。", "（2）給与の収入金額が69万円未満のときは、69万円からその給与に係る給与所得控除額を差し引いた残額と、事業所得や雑所得の実際にかかった経費とを比べて高い方が",
                                  "このため、給与の収入金額から控除する給与所得控除額が69万円以上ある場合（つまり、給与の収入金額が69万円以上ある場合）には、この特例の適用はありません。"]),
    ("W12", "PS 2.2", "wa_ta_1810_20251105", ["[令和7年4月1日現在法令等]",
                                              "（2）この特例に該当する所得しかない人で、その年の総収入金額が160万円以下の場合は、総所得金額が基礎控除額の95万円以下となりますので、本人に所得税は課されません。また、その年の総収入金額が123万円以下の場合は、扶養者の所得税額の計算上、配偶者控除あるいは扶養控除の対象となります。",
                                              "（4）令和７年分の場合は、令和７年12月１日に施行され、令和７年分から適用される金額です。"]),
    ("W13", "PS 2.4", "wa_ta_1810_20251105", ["（1）給与の収入金額が65万円以上あるときは、この特例は受けられません。", "このため、給与の収入金額から控除する給与所得控除額が65万円以上ある場合（つまり、給与の収入金額が65万円以上ある場合）には、この特例の適用はありません。"]),
    ("W14", "PS 2.2", "wa_ta_1810_20241105", ["[令和6年4月1日現在法令等]", "（2）この特例に該当する所得しかない人で、その年の総収入金額が103万円以下の場合は、総所得金額が基礎控除額の48万円以下となりますので、本人に所得税は課されず、また、扶養者の所得税額の計算上、配偶者控除あるいは扶養控除の対象となります。"]),
    ("W15", "PS 2.2", "wa_ta_1810_20250317", ["[令和6年4月1日現在法令等]", "総収入金額が103万円以下の場合は、総所得金額が基礎控除額の48万円以下となりますので、本人に所得税は課されず、また、"]),
    ("W16", "PS 3.4", "sochitsu_41_3_11", ["41の3の11-1", "２以上の居住者の年齢23歳未満若しくは特別障害者である扶養親族に該当する場合", "これらの居住者はいずれも年齢23歳未満の扶養親族又は特別障害者である同一生計配偶者若しくは扶養親族を有することとなることに留意する。",
                                           "41の3の11-2", "その死亡又は出国の時の現況により見積もったその年１月１日から12月31日までの当該親族等の合計所得金額により判定する。",
                                           "41の3の11-3", "特定支出の控除を受けた者であっても、措置法第41条の３の11第２項の規定による所得金額調整控除の適用があることに留意する。"]),
    ("W17", "PS 3.5", "ta_1411", ["[令和8年4月1日現在法令等]", "{給与等の収入金額（1,000万円超の場合は1,000万円） － 850万円}×10％＝控除額※", "※1円未満の端数があるときは、その端数を切り上げます。",
                                  "その年最後に給与等の支払を受ける日の前日までに、給与の支払者に所得金額調整控除申告書を提出する必要があります。",
                                  "（注）この控除は、扶養控除と異なり、同一生計内のいずれか一方のみの所得者に適用するという制限がありません。したがって、例えば、夫婦ともに給与等の収入金額が850万円を超えており、夫婦の間に1人の年齢23歳未満の扶養親族である子がいるような場合には、その夫婦双方が、この控除の適用を受けることができます。",
                                  "{給与所得控除後の給与等の金額（10万円超の場合は10万円） ＋ 公的年金等に係る雑所得の金額（10万円超の場合は10万円）}－10万円＝控除額（注）",
                                  "（注）上記の「子ども・特別障害者等を有する者等の所得金額調整控除」の適用がある場合はその適用後の給与所得の金額から控除します。",
                                  "根拠法令等", "措法41の3の11、41の3の12、措令26の5、措通41の3の11-1"]),
    ("W18", "PS 4.2", "ta_1199", ["[令和8年4月1日現在法令等]", "2,350万円超2,400万円以下", "48万円", "48万円", "48万円", "2,400万円超2,450万円以下", "32万円", "32万円", "32万円", "32万円",
                                  "2,450万円超2,500万円以下", "16万円", "16万円", "16万円", "16万円", "2,500万円超", "０円", "０円", "０円", "０円"]),
    ("W19", "PS 6.1", "mhlw_00tc5007_p1", ["(令和2年4月10日)", "(事務連絡)", "(全国健康保険協会あて厚生労働省保険局保険課通知)",
                                           "今般の新型コロナウイルス感染症への対応として、一時的に収入が増加する被扶養者の方が発生しうるとの指摘があることを踏まえ、被扶養者の収入の確認における留意点について、下記のとおり、改めて周知します",
                                           "1　被扶養者として認定した者については、認定後、少なくとも年1回は保険者において被扶養者に係る確認を行い、被扶養者の要件を引き続き満たしていることを確認することが望ましいこと。",
                                           "2　確認に当たり、被扶養者の収入については、被扶養者の過去の収入、現時点の収入又は将来の収入の見込みなどから、今後1年間の収入を見込むものとすること。この際には、勤務先から発行された給与明細書、市区町村から発行された課税証明書等の公的証明書等を用いること。",
                                           "3　今後1年間の収入を見込む際には、例えば、認定時(前回の確認時)には想定していなかった事情により、一時的に収入が増加し、直近3ヶ月の収入を年収に換算すると130万円以上となる場合であっても、直ちに被扶養者認定を取消すのではなく、過去の課税証明書、給与明細書、雇用契約書等と照らして、総合的に将来収入の見込みを判断すること。",
                                           "4　確認に当たり、被扶養者認定を受けている方の過去1年間の収入が、昇給又は恒久的な勤務時間の増加を伴わない一時的な事情等により、その1年間のみ上昇し、結果的に130万円以上となった場合においても、原則として、被扶養者認定を遡って取り消さないこと。",
                                           "(健康保険組合あて厚生労働省保険局保険課通知)", "(地方厚生(支)局あて厚生労働省保険局保険課通知)", "(健康保険組合連合会あて厚生労働省保険局保険課通知)"]),
    ("W20", "PS 6.2・M C6", "mhlw_00tc5958_p1", ["(令和3年6月4日)", "(事務連絡)", "協会けんぽ加入の場合、被扶養者認定の際の被扶養者異動届は日本年金機構に提出し、被扶養者の年間収入見込みを確認することになります"]),
    ("W21", "PS 6.2", "mhlw_newpage_19044", ["令和３年４月から令和６年３月末までのワクチン接種業務に対する給与収入"]),
    ("W22", "PS 6.5", "faq_19to22_income", ["年間収入が150万円未満かどうかの判定は、所得税法上の取り扱いと同様に、過去1年間の収入で判定するのですか。", "更新日：2025年8月19日",
                                            "年間収入が150万円未満かどうかの判定は、従来と同様の年間収入の考え方により判定します。具体的には、認定対象者の過去の収入、現時点の収入または将来の収入の見込みなどから、今後1年間の収入を見込むこととなります。"]),
    ("W23", "PS 6.3", "gigishokai_index", ["主な疑義照会と回答について", "更新日：2026年9月10日"]),
]

# 推測（［I］）と実測（［M］C2・C3）の数値の再計算（担当の R2X_gaps_check.py とは別に書いた）
def kyuyo_shotoku_r8(x):
    """令和8年分の給与所得の金額（措法29の4②。69万1千円以上220万円未満の範囲だけ）。"""
    assert 691_000 <= x < 2_200_000
    if x < 741_000:
        return 0
    if x < 2_191_000:
        return x - 740_000
    if x < 2_193_000:
        return 1_451_000
    if x < 2_196_000:
        return 1_453_000
    return 1_456_000


def chosei1(salary, mode):
    """措法41の3の11①。mode='up'：TA No.1411 の 1円未満切上げ、'down'：切捨て。"""
    if salary <= 8_500_000:
        return 0
    num = (min(salary, 10_000_000) - 8_500_000) * 10
    q, r = divmod(num, 100)
    return q + (1 if (mode == "up" and r) else 0)


def chosei2(kyuyo_after, nenkin):
    if kyuyo_after <= 0 or nenkin <= 0 or kyuyo_after + nenkin <= 100_000:
        return 0
    return min(kyuyo_after, 100_000) + min(nenkin, 100_000) - 100_000


def kiso(year, g):
    """所法86① と措法41の16の2①（令和7年分・令和8年分）。"""
    if g > 25_000_000:
        return 0
    if g > 24_500_000:
        base = 160_000
    elif g > 24_000_000:
        base = 320_000
    elif g > 23_500_000:
        base = 480_000
    else:
        base = 580_000 if year == 7 else 620_000
        if g <= 6_550_000:
            if year == 7:
                base += 370_000 if g <= 1_320_000 else 300_000 if g <= 3_360_000 else 100_000 if g <= 4_890_000 else 50_000
            else:
                base += 420_000 if g <= 4_890_000 else 50_000
    return base


def calc_checks():
    res = {}
    # ［M］C2 の表
    for y, tokurei, fuyo, kiso_low, tokutei in [(7, 650_000, 580_000, kiso(7, 1_000_000), 1_230_000), (8, 690_000, 620_000, kiso(8, 1_000_000), 1_230_000)]:
        res[f"C2_R{y}"] = {"特例額": tokurei, "扶養の要件": fuyo, "低い段階の基礎控除": kiso_low, "扶養の上限（総収入）": tokurei + fuyo,
                            "本人非課税の上限（総収入）": tokurei + kiso_low, "特定親族の上限（総収入）": tokurei + tokutei}
    g = 1_600_000 - 650_000
    res["C2_R7_1600000"] = {"合計所得金額": g, "扶養親族": g <= 580_000, "特定親族（19〜22歳）": 580_000 < g <= 1_230_000, "本人非課税": g <= kiso(7, g)}
    # ［M］C3 の計算例
    res["C3_item1"] = {s: (chosei1(s, "up"), chosei1(s, "down")) for s in [8_500_000, 8_500_001, 8_500_005, 8_500_010, 9_000_000, 9_999_999, 10_000_000, 12_000_000]}
    res["C3_item2"] = {f"{a},{b}": chosei2(a, b) for a, b in [(50_000, 40_000), (50_000, 80_000), (200_000, 300_000), (100_000, 1), (0, 500_000)]}
    # ［M］C4 の表（境目）
    res["IG4"] = {f"R{y}:{g}": kiso(y, g) for y in (7, 8) for g in [23_500_000, 23_500_001, 24_000_000, 24_000_001, 24_500_000, 24_500_001, 25_000_000, 25_000_001]}
    res["IG4_drop"] = {"R7": kiso(7, 23_500_000) - kiso(7, 23_500_001), "R8": kiso(8, 23_500_000) - kiso(8, 23_500_001)}
    res["IG4_salary"] = {"25,450,000": 25_450_000 - 1_950_000, "25,450,001": 25_450_001 - 1_950_000}
    # IG1
    k = kyuyo_shotoku_r8(1_300_000)
    res["IG1"] = {"給与所得（令和8年分）": k, "合計所得金額": k + 150_000, "89万円以下": k + 150_000 <= 890_000, "基礎控除": kiso(8, k + 150_000),
                  "課税総所得（基礎控除だけ）": max(0, k + 150_000 - kiso(8, k + 150_000)), "令和7年分の給与所得（参考：別表第五 1,900,000円未満は収入−650,000）": 1_300_000 - 650_000}
    # IG2
    res["IG2"] = {"合計所得金額": 1_500_000 - 650_000, "扶養親族": 1_500_000 - 650_000 <= 580_000, "特定親族特別控除（85万円以下）": 630_000 if 1_500_000 - 650_000 <= 850_000 else None,
                  "境目R7": [(x, x - 650_000 <= 580_000) for x in (1_230_000, 1_230_001)], "境目R8": [(x, x - 690_000 <= 620_000) for x in (1_310_000, 1_310_001)]}
    # IG3
    kc = kyuyo_shotoku_r8(800_000)
    adj = chosei2(kc, 200_000)
    res["IG3"] = {"A": chosei1(9_000_000, "up"), "B": chosei1(9_500_000, "up"), "C_給与所得": kc, "C_調整控除": adj, "C_給与所得（控除後）": kc - adj, "C_総所得金額": kc - adj + 200_000}
    # IG6
    months = [50_000] * 9 + [300_000] * 3
    res["IG6"] = {"直近12か月": sum(months), "直近3か月×4": sum(months[-3:]) * 4, "150万÷12": 1_500_000 / 12}
    return res


def cmd_check():
    out = {"egov_meta": [], "revisions": {}, "law": [], "law_extra": {}, "web_meta": [], "web": [], "cdx": {}, "calc": {}, "refs": [], "rules": {}}
    d, man = egov_dir()
    fetched = {(f["short"], f["asof"]): f for f in man["fetches"]}
    # 1. ［M］§2 の版
    for short, asof, rev, enf, st, sha16 in M_EGOV:
        f = fetched.get((short, asof), {})
        enf_mine = f.get("amendment_enforcement_date")
        out["egov_meta"].append({"short": short, "asof": asof, "rev_ok": f.get("law_revision_id") == rev, "status_ok": f.get("current_revision_status") == st,
                                 "enf_claim": enf, "enf_mine": enf_mine, "enf_ok": enf_mine == enf,
                                 "sha_claim": sha16, "sha_mine": (f.get("sha256") or "")[:16], "with_amend_suppl": f.get("with_amend_suppl")})
    out["lookups"] = man["lookups"]
    # 2. 改正履歴：施行日 2027-01-01 の版
    for r in man["revisions"]:
        out["revisions"][r["short"]] = sorted(x["amendment_law_num"] for x in r["revisions"] if x["amendment_enforcement_date"] == "2027-01-01")
    # 3. 条文の引用
    for cid, doc, desc, short, asofs, where, art, path, frags in LAWCLAIMS:
        for asof in asofs:
            n = node_of(short, asof, where, art, path)
            ok, miss = in_order(text_of(n), frags) if n is not None else (False, "（条・項・号が見つからない）")
            out["law"].append({"id": cid, "doc": doc, "desc": desc, "short": short, "asof": asof, "ok": ok, "missing": miss})
    # 4. 条文の機械的な確認
    ex = out["law_extra"]
    a = {asof: text_of(L("sochi", asof).main["41_3_11"]) for asof in ["2024-12-31", "2025-12-31", "2026-12-31", "2027-01-01"]}
    ex["41_3_11_sha"] = {k: hashlib.sha256(v.encode("utf-8")).hexdigest()[:16] for k, v in a.items()}
    ex["41_3_11_same_2024_2026"] = a["2024-12-31"] == a["2025-12-31"] == a["2026-12-31"]
    ex["41_3_11_has_hasu"] = {k: "端数" in v for k, v in a.items()}
    yen = re.compile(r"([〇一二三四五六七八九十百千万]+)円")
    ex["41_3_11_yen_in_order"] = yen.findall(a["2025-12-31"])
    ex["41_3_11_hyakubun_no_ju"] = "百分の十" in a["2025-12-31"]
    # 2027-01-01 版との差：項・号ごとに比べる
    diffs = []
    for p in range(1, 8):
        for asof_pair in [("2026-12-31", "2027-01-01")]:
            t1 = text_of(locate(L("sochi", asof_pair[0]).main["41_3_11"], str(p)))
            t2 = text_of(locate(L("sochi", asof_pair[1]).main["41_3_11"], str(p)))
            if t1 != t2:
                diffs.append(p)
    ex["41_3_11_paragraphs_changed_2026_vs_2027"] = diffs
    ex["41_3_11_items_changed_p4"] = [i for i in range(1, 8) if text_of(locate(L("sochi", "2026-12-31").main["41_3_11"], f"4/{i}")) != text_of(locate(L("sochi", "2027-01-01").main["41_3_11"], f"4/{i}"))]
    for asof in ["2025-12-31", "2026-12-31"]:
        rei = L("sochi-rei", asof)
        ex[f"sochi-rei_{asof}"] = {"端数を含む条の数（本則・原始附則）": len(rei.articles_with("端数")),
                                   "所得金額調整控除": rei.articles_with("所得金額調整控除"), "第四十一条の三の十一": rei.articles_with("第四十一条の三の十一"),
                                   "第四十一条の三の三": rei.articles_with("第四十一条の三の三"),
                                   "上の3語のいずれかを含む条のうち端数を含む条": sorted({x for k in ("所得金額調整控除", "第四十一条の三の十一", "第四十一条の三の三") for x in rei.articles_with(k, "端数")}),
                                   "19_4_2 があるか": "19_4_2" in rei.main}
        ki = L("sochi-ki", asof)
        ex[f"sochi-ki_{asof}"] = {"所得金額調整控除": ki.articles_with("所得金額調整控除"), "所得金額調整控除＋端数": ki.articles_with("所得金額調整控除", "端数"),
                                  "texts_sha": {n: hashlib.sha256(text_of(ki.main[n]).encode("utf-8")).hexdigest()[:16] for n in ["18_23_3", "18_23_5", "18_23_6", "18_23_8"]}}
    for asof in ["2026-01-01", "2027-01-01"]:
        raw = (d / f"chiho_{asof}.json").read_text(encoding="utf-8")
        ex[f"chiho_{asof}_raw_counts"] = {k: raw.count(k) for k in ["所得金額調整控除", "四十一条の三の十一"]}
    # 所得税法の全文で「勤労に基づ」「勤労による」「勤労により」を含む条
    for asof in S3:
        law = L("shotoku", asof)
        hits = []
        arts = []
        walk_tree(law.root, lambda n, anc: arts.append(("附則" if any(x.get("tag") == "SupplProvision" for x in anc) else "本則", n)) if n.get("tag") == "Article" else None)
        for part, n in arts:
            t = text_of(n)
            for kw in ["勤労に基づ", "勤労による", "勤労により"]:
                if kw in t:
                    hits.append((part, n["attr"].get("Num"), kw))
        ex[f"shotoku_{asof}_kinro_hits"] = hits
    # 版の差：2025-12-31 と 2026-12-31 で、所法86・120・2①三十二 の項・号ごとの差
    ch = []
    for art in ["86", "120"]:
        n1, n2 = L("shotoku", "2025-12-31").main[art], L("shotoku", "2026-12-31").main[art]
        for p in kids(n1, "Paragraph"):
            pn = p["attr"]["Num"]
            items1 = kids(p, "Item") or [None]
            for it in items1:
                path = pn if it is None else f"{pn}/{it['attr']['Num']}"
                if text_of(locate(n1, path)) != text_of(locate(n2, path)):
                    ch.append(f"{art} {path}")
    if text_of(locate(L("shotoku", "2025-12-31").main["2"], "1/32")) != text_of(locate(L("shotoku", "2026-12-31").main["2"], "1/32")):
        ch.append("2 1/32")
    ex["shotoku_changed_2025_vs_2026_selected"] = ch
    ex["shotoku_120_4_2_texts"] = [text_of(locate(L("shotoku", v).main["120"], "4/2"))[60:140] for v in ["2025-12-31", "2026-12-31"]]
    # 所規47の3 の 2026-12-31 と 2027-01-01 の差（各号は同じか）
    k1, k2 = L("shotoku-ki", "2026-12-31").main["47_3"], L("shotoku-ki", "2027-01-01").main["47_3"]
    ex["47_3_items_same"] = all(text_of(locate(k1, f"1/{i}")) == text_of(locate(k2, f"1/{i}")) for i in ("1", "2"))
    ex["47_3_R8K17_1_2_mentions_47_3"] = "第四十七条の三" in text_of(locate(L("shotoku-ki", "2027-01-01").suppl_article(R8K_17, "1"), "1/2"))
    # 5. 公表資料
    wm = json.loads((OUT / "web_manifest.json").read_text(encoding="utf-8"))
    mine = {r["id"]: r for r in wm["results"]}
    for sid, (st, lm, sha16) in M_WEB.items():
        r = mine.get(sid, {})
        lm_mine = None
        if r.get("last_modified"):
            lm_mine = time.strftime("%Y-%m-%d %H:%M:%S", time.strptime(r["last_modified"], "%a, %d %b %Y %H:%M:%S GMT"))
        out["web_meta"].append({"id": sid, "status_ok": r.get("status") == st, "lm_claim": lm, "lm_mine": lm_mine, "lm_ok": lm == lm_mine,
                                "sha_claim": sha16, "sha_mine": (r.get("sha256") or "")[:16], "sha_ok": (sha16 is None) or (sha16 == (r.get("sha256") or "")[:16]),
                                "robots_allowed": r.get("robots_allowed")})
    out["robots"] = {h: {"claim": M_ROBOTS.get(h), "mine": v["status"]} for h, v in wm["robots"].items()}
    tx = OUT / "web"
    for wid, doc, sid, frags in WEBCLAIMS:
        t = (tx / f"{sid}.txt").read_text(encoding="utf-8")
        ok, miss = in_order(t, frags)
        out["web"].append({"id": wid, "doc": doc, "source": sid, "ok": ok, "missing": miss})
    # 00tc5007：記の1〜4 の文が4つの宛先で同じか
    t = (tx / "mhlw_00tc5007_p1.txt").read_text(encoding="utf-8")
    blocks = re.split(r"\(令和2年4月10日\)", t)[1:]
    kis = []
    for b in blocks:
        items = re.findall(r"^([1-4])　(.+)$", b, re.M)
        kis.append(tuple(items))
    out["web_extra"] = {"00tc5007_blocks": len(blocks), "00tc5007_items_per_block": [len(k) for k in kis],
                        "00tc5007_items_same_in_blocks_with_items": len({k for k in kis if k}) == 1,
                        "00tc5007_has_haishi_shikko": [w for w in ("廃止", "失効") if w in t],
                        "00tc5958_mentions_R2_0410": (tx / "mhlw_00tc5958_p1.txt").read_text(encoding="utf-8").count("令和2年4月10日付け厚生労働省保険局保険課事務連絡")}
    # ［M］C1 の表（「勤労」の行とアフィリエイト等の行）を検証側のテキストで数え直す
    kw_net = re.compile(r"アフィリエイト|広告収入|広告料|ドロップシッピング|ネット通販|転売|動画配信")
    cnt = {}
    for sid in ["ta_1175", "kihon_01_07", "tebiki_r07_3_3_15", "nencho2025_qa", "nencho2026_qa", "keisan_r7_kinro_cid472", "tokushu_chui", "ta_1500", "kihon_04_09"]:
        lines = [ln for ln in (tx / f"{sid}.txt").read_text(encoding="utf-8").splitlines() if not ln.startswith("#")]
        cnt[sid] = {"勤労": sum("勤労" in ln for ln in lines), "net": sum(bool(kw_net.search(ln)) for ln in lines),
                    "both": sum(("勤労" in ln) and bool(kw_net.search(ln)) for ln in lines)}
    out["web_extra"]["C1_counts_mine"] = cnt
    # TA No.1810：版ごとの［…現在法令等］と、2026-09-15 の保存と現在の配信の SHA-256
    out["web_extra"]["ta1810_labels"] = {sid: re.search(r"\[(令和\d+年4月1日現在法令等)\]", (tx / f"{sid}.txt").read_text(encoding="utf-8")).group(1)
                                         for sid in ["ta_1810", "wa_ta_1810_20241105", "wa_ta_1810_20250317", "wa_ta_1810_20251105", "wa_ta_1810_20260915"]}
    out["web_extra"]["wa_20260915_eq_current"] = mine["wa_ta_1810_20260915"]["sha256"] == mine["ta_1810"]["sha256"]
    # 質疑応答事例（所得税）の目次（web3）に「勤労」「学生」の語があるか
    idx = tx / "shitsugi_shotoku_index.txt"
    if idx.exists():
        it = idx.read_text(encoding="utf-8")
        out["web_extra"]["shitsugi_shotoku_index"] = {"勤労": it.count("勤労"), "学生": it.count("学生"), "所得控除の節がある": "所得控除" in it}
    for nm in ("web2", "web3"):
        mp = OUT / f"{nm}_manifest.json"
        if mp.exists():
            out["web_extra"][nm] = [{k: r.get(k) for k in ("id", "status", "last_modified")} | {"sha16": (r.get("sha256") or "")[:16]}
                                    for r in json.loads(mp.read_text(encoding="utf-8"))["results"]]
    # 6. CDX
    rows = json.loads((tx / "cdx_ta_1810_digest.txt").read_text(encoding="utf-8").split("\n\n", 1)[1])[1:]
    out["cdx"] = {"rows": len(rows), "first": rows[0][0], "last": rows[-1][0], "n301": sum(r[1] == "301" for r in rows),
                  "distinct_digests": len({r[2] for r in rows}), "distinct_digests_200": len({r[2] for r in rows if r[1] == "200"}),
                  "repeated_digests": sorted({r[2] for r in rows if sum(x[2] == r[2] for x in rows) > 1})}
    # 7. 計算
    out["calc"] = calc_checks()
    # 8. 文書が参照する既存の文書と、その中の文言
    refs = [
        ("docs/measurements/20261109_impl-prep_jigyo-fetch-and-checks.md", "66d23053e2d026aa"),
        ("docs/measurements/20261109_impl-prep_jigyo-verification.md", "法第百二十条第八項"),
        ("docs/measurements/20261109_R3-tsutatsu_fetch-and-monitor-probe.md", "登載後に URL が消える"),
        ("docs/measurements/20261109_R1-laws_article-extraction.md", "二千四百万円以下：四十八万円"),
        ("docs/measurements/20261109_impl-prep_kyuyo-thresholds.md", "25,450,000"),
        ("docs/public-sources/20261109_impl-prep_kyuyo-sources.md", "特定支出控除や所得金額調整控除の適用がある場合には、表の金額とは異なります"),
        ("docs/public-sources/20261109_impl-prep_juminzei-hikazei-fuyo-shinkoku.md", "第9項（所得税法第2条第1項第32号を準用"),
        ("docs/public-sources/20261109_R4-modeling_concepts.md", "所法2①三十イ（２）"),
        ("docs/public-sources/20261109_R1-laws_income-tax.md", "第85条第6項"),
        ("docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md", "2−45の２"),
        ("docs/public-sources/20261109_impl-prep_kenpo-dependent-practice.md", "JQA-M A2-3"),
        ("docs/hypotheses/20261109_impl-prep_kenpo-input-facts.md", "## HK2"),
        ("docs/inferences/20261109_impl-prep_kenpo-test-cases.md", "候補日"),
        ("docs/hypotheses/20261109_impl-prep_jigyo-calculation-model.md", "## H2"),
        ("docs/inferences/20261109_impl-prep_jigyo-inferences.md", "1,230,001"),
        ("docs/hypotheses/20261109_impl-prep_juminzei-judgment-model.md", "#"),
    ]
    for p, s in refs:
        fp = ROOT / p
        out["refs"].append({"path": p, "exists": fp.exists(), "contains": s, "ok": fp.exists() and s in fp.read_text(encoding="utf-8")})
    # 9. 文書の規約：仮説・推測に外部 URL を書いていないか
    for p in ["docs/hypotheses/20261109_round2_gaps-hypotheses.md", "docs/inferences/20261109_round2_gaps-inferences.md"]:
        out["rules"][p] = {"http_urls": re.findall(r"https?://\S+", (ROOT / p).read_text(encoding="utf-8"))}
    (OUT / "checks.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    # 要約
    md = ["# R2X_gaps_verify の照合結果（scripts/R2X_gaps_verify.py check の出力）", ""]
    bad_meta = [m for m in out["egov_meta"] if not (m["rev_ok"] and m["status_ok"] and m["enf_ok"])]
    md.append(f"- e-Gov の版（［M］§2、{len(out['egov_meta'])} 件）：law_revision_id・状態・施行日が一致しないもの {len(bad_meta)} 件。"
              f"生データの SHA-256（先頭16桁）が一致したもの {sum(m['sha_claim'] == m['sha_mine'] for m in out['egov_meta'])} 件")
    for m in out["egov_meta"]:
        md.append(f"  - {m['short']} {m['asof']}: rev={m['rev_ok']} status={m['status_ok']} 施行日 claim={m['enf_claim']} mine={m['enf_mine']} sha claim={m['sha_claim']} mine={m['sha_mine']}")
    md.append(f"- law_id の引き直し：{[(x['short'], x['exact'][0]['law_id'] if x['exact'] else None, x['exact'][0]['law_num'] if x['exact'] else None, x['match']) for x in out['lookups']]}")
    md.append(f"- 施行日 2027-01-01 の版の改正法令：{out['revisions']}")
    nl = len(out["law"])
    md.append(f"- 条文の引用（主張×版）：{nl} 件中 一致 {sum(x['ok'] for x in out['law'])} 件")
    for x in out["law"]:
        if not x["ok"]:
            md.append(f"  - 不一致 {x['id']} {x['short']} {x['asof']} {x['desc']}：見つからない断片「{x['missing']}」")
    md.append("- 条文の機械的な確認：")
    for k, v in ex.items():
        md.append(f"  - {k}: {json.dumps(v, ensure_ascii=False)}")
    bw = [w for w in out["web_meta"] if not (w["status_ok"] and w["lm_ok"] and w["sha_ok"])]
    md.append(f"- 公表資料の取得（［M］§3、{len(out['web_meta'])} 件）：ステータス・Last-Modified・SHA-256 のどれかが一致しないもの {len(bw)} 件")
    for w in bw:
        md.append(f"  - {w}")
    md.append(f"- robots.txt：{out['robots']}")
    md.append(f"- 公表資料の引用：{len(out['web'])} 件中 一致 {sum(x['ok'] for x in out['web'])} 件")
    for x in out["web"]:
        if not x["ok"]:
            md.append(f"  - 不一致 {x['id']} {x['source']}：見つからない断片「{x['missing']}」")
    md.append(f"- 公表資料の機械的な確認：{json.dumps(out['web_extra'], ensure_ascii=False)}")
    md.append(f"- CDX：{json.dumps(out['cdx'], ensure_ascii=False)}")
    md.append(f"- 計算：{json.dumps(out['calc'], ensure_ascii=False)}")
    md.append(f"- 参照先の文書：{sum(r['ok'] for r in out['refs'])}/{len(out['refs'])} 件で文言を確認")
    for r in out["refs"]:
        if not r["ok"]:
            md.append(f"  - 不一致 {r}")
    md.append(f"- 規約：{json.dumps(out['rules'], ensure_ascii=False)}")
    (OUT / "checks.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "egov":
        cmd_egov()
    elif mode == "web":
        cmd_web()
    elif mode == "web2":
        cmd_web("web2", WEB2)
    elif mode == "web3":
        cmd_web("web3", WEB3)
    elif mode == "check":
        cmd_check()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()

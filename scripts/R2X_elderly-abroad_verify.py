"""R2X_elderly-abroad_verify: トピック elderly-abroad（老人扶養・同居老親等、国外居住親族、居住者の判定、健保の60歳以上・国内居住要件）
の文書を、担当の結論を信じない前提で、一次情報に当たり直して検証する（反証役）。

実行（Windows。pyenv の .bat シムは使わない）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_elderly-abroad_verify.py fetch-egov
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_elderly-abroad_verify.py fetch-egov2
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_elderly-abroad_verify.py fetch-web
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_elderly-abroad_verify.py check-egov
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_elderly-abroad_verify.py check-web
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_elderly-abroad_verify.py check-docs
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_elderly-abroad_verify.py calc

- fetch-egov: e-Gov 法令API v2 の /law_data（担当と同じ URL の形：response_format=json&asof=<日付>）で、担当が使った法令と版を取り直し、
  revision_info と生データの SHA-256 を記録する。あわせて /law_revisions で措法の版の一覧（施行日）を取る。
  ダウンロードは .work/downloads/<YYYYMMDD-HHMMSS>_R2X_elderly-abroad_verify_egov/（実行ごとに新しい空のディレクトリ。中では何も実行しない）。
- fetch-egov2: 令和8年分の確定申告書を出す時期の版（所法 asof 2027-01-01・2027-03-15、所令・所規 asof 2027-03-15）を取る
  （.work/downloads/<ts>_R2X_elderly-abroad_verify_egov2/）。
- fetch-web: 国税庁・厚労省・日本年金機構・協会けんぽの HTML と PDF を取り直す。HTML は .work/downloads/<ts>_R2X_elderly-abroad_verify_html/、
  PDF は .work/downloads/<ts>_R2X_elderly-abroad_verify_pdf/ に置く。PDF の中身は Read ツールで人が読む（ここでは同一性だけ）。
- check-egov / check-web: 最新の取得記録（scripts/results/R2X_elderly-abroad_verify/*_fetch.json）が指すダウンロードをデータとして読み、文書の主張を検査する
  （ネットワークに接続しない）。条文のテキスト化は担当のスクリプトを使わず、ここで別に書いた（ルビ Rt を落とし、番号・見出しを落として平文にする）。
- check-docs: 文書の表（［MS］§2.1・§2.2、［LW］§0、［GD］§0）を取得記録と照合し、仮説・推測の文書の参照（外部 URL の有無）を検査する。
- calc: 推測・仮説に書かれた算術（年齢、合計、境目）を、担当とは別の書き方で計算し直す（ネットワークに接続しない）。

e-Gov の使い方は scripts/R1_egov_articles.py・scripts/IMPL_kyuyo_fetch.py・scripts/IMPL_misc_verify.py のコードを写した（import しない）。
標準ライブラリのみ。リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。個人の情報は送らない。官報は取得しない。
出力は scripts/results/R2X_elderly-abroad_verify/。
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
OUT = ROOT / "scripts" / "results" / "R2X_elderly-abroad_verify"
DLROOT = ROOT / ".work" / "downloads"
NAME = "R2X_elderly-abroad_verify"
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
SLEEP = 1.5
THEIR_LAWS = ROOT / "scripts" / "results" / "R2X_elderly-abroad_laws"
THEIR_WEB = ROOT / "scripts" / "results" / "R2X_elderly-abroad_web"


# ---------------------------------------------------------------- 共通

def get(url, accept="application/json", timeout=300):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept, "Accept-Language": "ja"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body, st, hdr, final = r.read(), r.status, dict(r.headers.items()), r.geturl()
    except urllib.error.HTTPError as e:
        body, st, hdr, final = e.read(), e.code, dict((e.headers or {}).items()), url
    time.sleep(SLEEP)
    return st, body, hdr, final


def norm(s):
    """比較用の正規化：NFKC、空白の除去、波ダッシュの統一。"""
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s+", "", s)
    return s.replace("〜", "~").replace("～", "~")


def frags_in_order(quote, text):
    """quote を「…」で区切った断片が text の中に順に現れるか。現れない最初の断片を返す（全部あれば None）。"""
    t = norm(text)
    pos = 0
    for f in [x for x in re.split(r"…+", quote) if norm(x)]:
        nf = norm(f)
        i = t.find(nf, pos)
        if i < 0:
            return f
        pos = i + len(nf)
    return None


def latest_dir(suffix):
    ds = sorted(p for p in DLROOT.glob(f"*_{NAME}_{suffix}") if p.is_dir())
    if not ds:
        raise SystemExit(f"no download dir for {suffix}; run fetch first")
    return ds[-1]


# ---------------------------------------------------------------- e-Gov の取得

LAWS = {
    # 略称: (law_id, [asof...])  担当（scripts/R2X_elderly-abroad_laws.py）と同じ法令・同じ時点
    "shotoku": ("340AC0000000033", ["2025-12-31", "2026-11-09", "2026-12-31"]),
    "shotoku-rei": ("340CO0000000096", ["2025-12-31", "2026-11-09", "2026-12-31"]),
    "shotoku-ki": ("340M50000040011", ["2025-12-31", "2026-11-09", "2026-12-31"]),
    "sochi": ("332AC0000000026", ["2025-12-31", "2026-11-09", "2026-12-31"]),
    "sochi-rei": ("332CO0000000043", ["2026-11-09"]),
    "chiho": ("325AC0000000226", ["2026-01-01", "2026-11-09", "2027-01-01"]),
    "chiho-ki": ("329M50000002023", ["2026-01-01", "2026-11-09", "2027-01-01"]),
    "kenpo": ("211AC0000000070", ["2025-12-31", "2026-11-09"]),
    "kenpo-ki": ("215M10000008036", ["2025-12-31", "2026-11-09"]),
    "koukirei": ("357AC0000000080", ["2026-11-09"]),
}
REVISION_LISTS = {"sochi": "332AC0000000026", "shotoku": "340AC0000000033"}
# 追加の時点（fetch-egov2）：令和8年分の確定申告書を出す時期（2027年）の版。所法120条は 2027-01-01 施行の改正がある
# （令和7年法律第13号附則第1条第5号イ、令和8年法律第12号附則第1条第5号イ）ので、確定申告の書類の規定をこの版でも確かめる。
LAWS2 = {
    "shotoku": ("340AC0000000033", ["2027-01-01", "2027-03-15"]),
    "shotoku-rei": ("340CO0000000096", ["2027-03-15"]),
    "shotoku-ki": ("340M50000040011", ["2027-03-15"]),
}


def run_fetch_egov2():
    run_fetch_egov(LAWS2, "egov2", with_revisions=False)


def run_fetch_egov(laws=None, kind="egov", with_revisions=True):
    laws = laws or LAWS
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = DLROOT / f"{ts}_{NAME}_{kind}"
    dl.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "user_agent": UA, "fetches": [], "revision_lists": {}}
    for short, (law_id, asofs) in laws.items():
        for asof in asofs:
            url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
            st, body, _, _ = get(url)
            (dl / f"{short}_{asof}.json").write_bytes(body)
            ent = {"short": short, "law_id": law_id, "asof": asof, "url": url, "status": st,
                   "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
            if st == 200:
                ri = (json.loads(body).get("revision_info") or {})
                for k in ("law_title", "law_revision_id", "amendment_law_num", "amendment_law_title",
                          "amendment_enforcement_date", "current_revision_status", "updated"):
                    ent[k] = ri.get(k)
            log["fetches"].append(ent)
            print("egov", short, asof, st, ent.get("law_revision_id"), ent.get("current_revision_status"), flush=True)
    for short, law_id in (REVISION_LISTS.items() if with_revisions else []):
        url = f"{API}/law_revisions/{law_id}?response_format=json"
        st, body, _, _ = get(url)
        (dl / f"revisions_{short}.json").write_bytes(body)
        recs = []
        if st == 200:
            d = json.loads(body)
            for r in d.get("revisions", []):
                if (r.get("amendment_enforcement_date") or "9999") >= "2025-01-01" or r.get("amendment_enforcement_date") is None:
                    recs.append({k: r.get(k) for k in ("law_revision_id", "amendment_law_num", "amendment_law_title",
                                                       "amendment_promulgate_date", "amendment_enforcement_date",
                                                       "amendment_enforcement_comment", "current_revision_status")})
        log["revision_lists"][short] = {"url": url, "status": st, "sha256": hashlib.sha256(body).hexdigest(), "recent": recs}
        print("revisions", short, st, len(recs), flush=True)
    (OUT / f"{kind}_fetch.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", dl)


# ---------------------------------------------------------------- 行政資料の取得

NTA = "https://www.nta.go.jp"


def tdoc(data_id):
    return f"https://www.mhlw.go.jp/web/t_doc?dataId={data_id}&dataType=1&pageNo=1"


PAGES = {
    "ta_1180": f"{NTA}/taxes/shiraberu/taxanswer/shotoku/1180.htm",
    "ta_1180_qa": f"{NTA}/taxes/shiraberu/taxanswer/shotoku/1180_qa.htm",
    "ta_1182": f"{NTA}/taxes/shiraberu/taxanswer/shotoku/1182.htm",
    "shitsugi_shotoku_05_32": f"{NTA}/law/shitsugi/shotoku/05/32.htm",
    "tebiki2025_yogo_y11": f"{NTA}/taxes/shiraberu/shinkoku/tebiki/2025/03/order3/yogo/3-3_y11.htm",
    "tebiki2025_yogo_y12": f"{NTA}/taxes/shiraberu/shinkoku/tebiki/2025/03/order3/yogo/3-3_y12.htm",
    "tebiki2025_3_3_27": f"{NTA}/taxes/shiraberu/shinkoku/tebiki/2025/03/order3/3-3_27.htm",
    "sochiho_tsutatsu_toc": f"{NTA}/law/tsutatsu/kobetsu/shotoku/sochiho/801226/sinkoku/01.htm",
    "kihon_tsutatsu_2_1": f"{NTA}/law/tsutatsu/kihon/shotoku/01/01.htm",
    "kihon_tsutatsu_2_47": f"{NTA}/law/tsutatsu/kihon/shotoku/01/07.htm",
    "kokugai_index": f"{NTA}/taxes/tetsuzuki/shinsei/annai/gensen/kokugai/index.htm",
    "kokugai_sokin": f"{NTA}/taxes/tetsuzuki/shinsei/annai/gensen/kokugai/sokin/index.htm",
    "S52_tsuchi": tdoc("00tb0189"),
    "R01_kokunai": tdoc("00tc4995"),
    "R05_kokunai_kaisei": tdoc("00tc7769"),
    "nenkin_kyojuyoken": "https://www.nenkin.go.jp/service/kounen/tekiyo/hihokensha1/kyojuyoken.html",
    "nenkin_20141202": "https://www.nenkin.go.jp/service/kounen/tekiyo/hihokensha1/20141202.html",
    "kyoukai_faq_dependent": "https://www.kyoukaikenpo.or.jp/faq/dependent_status/",
    "nta_robots": f"{NTA}/robots.txt",
    "mhlw_robots": "https://www.mhlw.go.jp/robots.txt",
    "nenkin_robots": "https://www.nenkin.go.jp/robots.txt",
}
PDFS = {
    "nencho2026_105": f"{NTA}/publication/pamph/gensen/nencho2026/pdf/105.pdf",
    "nencho2025_105": f"{NTA}/publication/pamph/gensen/nencho2025/pdf/105.pdf",
    "kokugai_qa_pdf": f"{NTA}/publication/pamph/pdf/0022009-107_02.pdf",
    "kokugai_leaf_pdf": f"{NTA}/publication/pamph/pdf/0022009-107_01.pdf",
    "r2kaisei_pdf": f"{NTA}/publication/pamph/shotoku/r2kaisei.pdf",
    "kyoukai_guide2607": "https://www.kyoukaikenpo.or.jp/assets/n_fuyouidou_guide2607.pdf",
}


class Extract(html.parser.HTMLParser):
    """HTML の平文化（担当のスクリプトとは別に書いた。img の alt は残す）。"""
    SKIP = {"script", "style", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.title, self.links = [], "", []
        self._skip = 0
        self._in_title = False
        self._a = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "img" and a.get("alt") and not self._skip:
            self.parts.append(a["alt"])
            if self._a is not None:
                self._a[1].append(a["alt"])
        if tag == "a" and a.get("href"):
            self._a = (a["href"], [])
        if tag in ("br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "dt", "dd", "table", "td", "th"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False
        if tag == "a" and self._a is not None:
            self.links.append({"href": self._a[0], "text": "".join(self._a[1]).strip()})
            self._a = None

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if not self._skip:
            self.parts.append(data)
            if self._a is not None:
                self._a[1].append(data)


def decode_html(body, hdr):
    enc = None
    m = re.search(r"charset=([\w\-]+)", hdr.get("Content-Type", "") or "", re.I)
    if m:
        enc = m.group(1)
    if not enc:
        m = re.search(rb"charset=[\"']?([A-Za-z0-9_\-]+)", body[:4000])
        if m:
            enc = m.group(1).decode()
    for c in [enc, "utf-8", "cp932"]:
        if not c:
            continue
        if c.lower() in ("shift_jis", "shift-jis", "sjis"):
            c = "cp932"
        try:
            return body.decode(c)
        except (LookupError, UnicodeDecodeError):
            pass
    return body.decode("utf-8", "replace")


def run_fetch_web():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl_html = DLROOT / f"{ts}_{NAME}_html"
    dl_pdf = DLROOT / f"{ts}_{NAME}_pdf"
    dl_html.mkdir(parents=True, exist_ok=False)
    dl_pdf.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "html_dir": str(dl_html.relative_to(ROOT)), "pdf_dir": str(dl_pdf.relative_to(ROOT)), "user_agent": UA,
           "pages": {}, "pdfs": {}}
    for pid, url in PAGES.items():
        st, body, hdr, final = get(url, accept="text/html", timeout=60)
        (dl_html / f"{pid}.bin").write_bytes(body)
        log["pages"][pid] = {"url": url, "final_url": final, "status": st, "bytes": len(body),
                             "sha256": hashlib.sha256(body).hexdigest(), "last_modified": hdr.get("Last-Modified"),
                             "content_type": hdr.get("Content-Type")}
        print("html", pid, st, len(body), hdr.get("Last-Modified"), flush=True)
    for pid, url in PDFS.items():
        st, body, hdr, final = get(url, accept="application/pdf", timeout=120)
        (dl_pdf / f"{pid}.pdf").write_bytes(body)
        log["pdfs"][pid] = {"url": url, "final_url": final, "status": st, "bytes": len(body),
                            "sha256": hashlib.sha256(body).hexdigest(), "last_modified": hdr.get("Last-Modified"),
                            "content_type": hdr.get("Content-Type"), "is_pdf": body[:5] == b"%PDF-"}
        print("pdf", pid, st, len(body), hdr.get("Last-Modified"), flush=True)
    (OUT / "web_fetch.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", dl_html, dl_pdf)


# ---------------------------------------------------------------- 行政資料の検査

def html_texts():
    """最新の fetch-web の HTML をテキストにする（データとして読むだけ）。テキストは出力にも残す（照合できるように）。"""
    log = json.loads((OUT / "web_fetch.json").read_text(encoding="utf-8"))
    d = ROOT / log["html_dir"]
    tx = OUT / "text"
    tx.mkdir(parents=True, exist_ok=True)
    texts, links, titles = {}, {}, {}
    for pid, rec in log["pages"].items():
        body = (d / f"{pid}.bin").read_bytes()
        hdr = {"Content-Type": rec.get("content_type") or ""}
        s = decode_html(body, hdr)
        if pid.endswith("_robots"):
            texts[pid] = s
            continue
        ex = Extract()
        ex.feed(s)
        t = "".join(ex.parts)
        t = re.sub(r"[ \t　]+\n", "\n", t)
        t = re.sub(r"\n{3,}", "\n\n", t)
        texts[pid] = t
        links[pid] = ex.links
        titles[pid] = " ".join(ex.title.split())
        (tx / f"{pid}.txt").write_text(t, encoding="utf-8")
    return log, texts, links, titles


# (ID, 文書の箇所, ページID, 文言（「…」で区切る）)
WEB_QUOTES = [
    # ---- ［GD］§0 の版・基準日
    ("GD0-TA1180-date", "GD§0", "ta_1180", "令和8年4月1日現在法令等"),
    ("GD0-TA1180QA-date", "GD§0", "ta_1180_qa", "令和8年4月1日現在法令等"),
    ("GD0-TA1182-date", "GD§0", "ta_1182", "令和8年4月1日現在法令等"),
    ("GD0-SG0532-date", "GD§0", "shitsugi_shotoku_05_32", "令和7年8月1日現在の法令・通達等"),
    ("GD0-SG0532-title", "GD§0", "shitsugi_shotoku_05_32", "「同居」の範囲(長期間入院している場合)"),
    ("GD0-Y11", "GD§0", "tebiki2025_yogo_y11", "老人扶養親族"),
    ("GD0-Y12", "GD§0", "tebiki2025_yogo_y12", "同居老親等"),
    ("GD0-S52-title", "GD§0", "S52_tsuchi", "収入がある者についての被扶養者の認定について"),
    ("GD0-S52-num", "GD§0", "S52_tsuchi", "保発第九号"),
    ("GD0-S52-num2", "GD§0", "S52_tsuchi", "庁保発第九号"),
    ("GD0-R01-title", "GD§0", "R01_kokunai", "被扶養者の国内居住要件等について"),
    ("GD0-R01-num", "GD§0", "R01_kokunai", "保保発1113第1号"),
    ("GD0-R05-num", "GD§0", "R05_kokunai_kaisei", "保保発0619第1号"),
    ("GD0-R05-title", "GD§0", "R05_kokunai_kaisei", "「被扶養者の国内居住要件等について」の一部改正について"),
    ("GD0-R05-underline", "GD§5.3", "R05_kokunai_kaisei", "下線部が改正箇所"),
    ("GD0-NKYOJU-title", "GD§0", "nenkin_kyojuyoken", "従業員の家族が海外居住の場合の手続き"),
    ("GD0-NKYOJU-date", "GD§0", "nenkin_kyojuyoken", "2026年10月6日"),
    ("GD0-NTET-date", "GD§0", "nenkin_20141202", "2026年9月30日"),
    ("GD0-KFAQ-title", "GD§0", "kyoukai_faq_dependent", "被扶養者資格の再確認"),
    ("GD0-KGSOKIN-name", "GD§0", "kokugai_sokin", "国外居住親族に対する送金関係書類の明細書"),
    ("GD0-KGSOKIN-r4", "GD§0", "kokugai_sokin", "上記は、令和4年12月までの…説明となります"),
    ("GD0-KGSOKIN-120-9", "GD§3.4", "kokugai_sokin", "所得税基本通達120-9"),
    ("GD0-KGIDX-title", "GD§0", "kokugai_index", "国外居住親族に係る扶養控除等の適用について"),
    # ---- ［GD］§1 同居
    ("GD1.1-SG-q", "GD§1.1", "shitsugi_shotoku_05_32",
     "同居老親等の「同居」については、病気の治療のため入院していることにより所得者等と別居している場合であっても、同居に該当すると聞きましたが、1年以上といった長期入院の場合にも同居に該当しますか。"),
    ("GD1.1-SG-a", "GD§1.1", "shitsugi_shotoku_05_32",
     "病気の治療のための入院である限り、その期間が結果として1年以上といった長期にわたるような場合であっても、同居に該当するものとして取り扱って差し支えありません。ただし、老人ホームなどへ入所している場合には、その老人ホームが居所となり、同居しているとはいえません。"),
    ("GD1.1-SG-law", "GD§1.1", "shitsugi_shotoku_05_32", "租税特別措置法第41条の16"),
    ("GD-SG-note", "GD冒頭", "shitsugi_shotoku_05_32", "この質疑事例は、照会に係る事実関係を前提とした一般的な回答であり、…この回答内容と異なる課税関係が生ずることがあることにご注意ください。"),
    ("GD1.1-TA1180-note", "GD§1.1", "ta_1180",
     "同居老親等の「同居」については、病気の治療のため入院していることにより納税者等と別居している場合は、その期間が結果として1年以上といった長期にわたるような場合であっても、同居に該当するものとして取り扱って差し支えありません。ただし、老人ホーム等へ入所している場合には、その老人ホームが居所となり、同居しているとはいえません。"),
    ("GD1.1-Y12", "GD§1.1", "tebiki2025_yogo_y12",
     "老人扶養親族のうち、あなたや配偶者の直系尊属（父母、祖父母など）で、あなたや配偶者との同居を常としている方…老人ホームなどへ入所している場合は、同居を常にしているとはいえません。"),
    # ---- ［GD］§1.2 控除額
    ("GD1.2-TA1180-intro", "GD§1.2", "ta_1180", "控除額は、扶養親族の年齢、同居の有無等により次の表のとおりです。"),
    ("GD1.2-TA1180-tbl", "GD§1.2", "ta_1180", "一般の控除対象扶養親族…38万円…特定扶養親族…63万円…老人扶養親族…同居老親等以外の者…48万円…同居老親等…58万円"),
    ("GD1.2-TA1180-law", "GD§1.2", "ta_1180", "所法2、79、84、85、措法41の16"),
    ("GD1.2-TA1182-age", "GD§1.2", "ta_1182", "年齢70歳（その年12月31日現在の年齢）以上である人"),
    ("GD1.2-TA1182-tbl", "GD§1.2", "ta_1182", "同居老親等以外の者…48万円…同居老親等…58万円"),
    ("GD1.2-TA1182-law", "GD§1.2", "ta_1182", "所法2、83、84、85、措法41の16、平29改正法附則6"),
    # ---- ［GD］§1.3 措置法通達の目次
    ("GD1.3-SOTOC-a", "GD§1.3", "sochiho_tsutatsu_toc", "第41条の15の５…年齢23歳未満の扶養親族を有する場合の生命保険料控除の特例…第41条の17…特定一般用医薬品等購入費を支払った場合の医療費控除の特例"),
    # ---- ［GD］§2.1
    ("GD2.1-Y11", "GD§2.1", "tebiki2025_yogo_y11", "控除対象扶養親族のうち、昭和31年1月1日以前に生まれた方（年齢が70歳以上の方）"),
    # ---- ［GD］§3.1・§3.2
    ("GD3.1-TA1180-abroad", "GD§3.1", "ta_1180", "令和5年分以後の所得税においては、非居住者である扶養親族については、次に掲げるいずれかに該当する人に限り、控除対象扶養親族に該当します。"),
    ("GD3.2-TA1180QA-Q4a", "GD§3.2", "ta_1180_qa", "令和5年分以後の確定申告"),
    ("GD3.2-TA1180QA-Q4b", "GD§3.2", "ta_1180_qa", "上記(イ)から(ハ)のいずれにも該当しない30歳以上70歳未満の国外居住親族については、扶養控除の適用はありません。"),
    ("GD3.2-TA1180QA-Q4c", "GD§3.2", "ta_1180_qa", "令和6年分以後の所得税の確定申告書を提出する場合に「送金関係書類」となるもの"),
    ("GD3.2-TA1180QA-Q4d", "GD§3.2", "ta_1180_qa", "生活費または教育費に充てるための支払いを、必要の都度、各人に行ったことを明らかにするもの"),
    ("GD3.2-TB27-note1", "GD§3.2", "tebiki2025_3_3_27", "国外居住親族の区分が「５」になる場合、扶養控除の適用はありません"),
    ("GD3.2-TB27-note2", "GD§3.2", "tebiki2025_3_3_27", "1及び2の両方、2及び3の両方又は1～3の全てに該当する場合は「３」を記入します。2に該当せず、1及び3の両方に該当する場合は、添付又は提示する書類に応じて、『留学ビザ等書類』を使用する場合には、「２」を、『38万円送金関係書類』を使用する場合には「４」を記入します。"),
    ("GD3.2-TB27-tbl", "GD§3.2", "tebiki2025_3_3_27", "16歳未満…５…16歳以上30歳未満又は70歳以上…１…留学により国内に住所及び居所を有しなくなった方…２…障害者…３…38万円以上受けている方…４…上記1～3以外の方…５"),
    ("GD3.2-TB27-r8", "GD§3.2", "tebiki2025_3_3_27", "令和8年３月16日（月）までに住所所在地の市区町村へ提出しなければなりません"),
    ("GD3.2-TB27-hikazei", "GD§3.2", "tebiki2025_3_3_27", "非課税限度額制度適用者"),
    # ---- ［GD］§3.4 所基通2-50
    ("GD3.4-KT07-hist", "GD§3.4", "kihon_tsutatsu_2_47", "令4課個2-13…令5課個2-25"),
    ("GD3.4-KT07-a", "GD§3.4", "kihon_tsutatsu_2_47", "送金した日"),
    ("GD3.4-KT07-b", "GD§3.4", "kihon_tsutatsu_2_47", "電信売買相場の仲値"),
    ("GD3.4-KT07-c", "GD§3.4", "kihon_tsutatsu_2_47", "現に支出した本邦通貨の額"),
    ("GD3.4-KT07-d", "GD§3.4", "kihon_tsutatsu_2_47", "利用をした日"),
    ("GD3.4-KT07-e", "GD§3.4", "kihon_tsutatsu_2_47", "移転"),
    ("GD3.4-KT07-f", "GD§3.4", "kihon_tsutatsu_2_47", "その年最後の"),
    # ---- ［GD］§4 所基通2-1〜2-4の3
    ("GD4-KT01-2-1", "GD§4", "kihon_tsutatsu_2_1",
     "法に規定する住所とは各人の生活の本拠をいい、生活の本拠であるかどうかは客観的事実によって判定する。"),
    ("GD4-KT01-2-1n", "GD§4", "kihon_tsutatsu_2_1",
     "国の内外にわたって居住地が異動する者の住所が国内にあるかどうかの判定に当たっては、令第14条《国内に住所を有する者と推定する場合》及び第15条《国内に住所を有しない者と推定する場合》の規定があることに留意する。"),
    ("GD4-KT01-2-2", "GD§4", "kihon_tsutatsu_2_1", "明らかにその国外に赴いた目的が一時的なものであると認められるときは、当該在外期間中も引き続き国内に居所を有するもの"),
    ("GD4-KT01-2-4", "GD§4", "kihon_tsutatsu_2_1", "入国の日の翌日"),
    ("GD4-KT01-2-4_3", "GD§4", "kihon_tsutatsu_2_1", "2－4の3"),
    # ---- ［GD］§5 健保
    ("GD5.1-S52-1", "GD§5.1", "S52_tsuchi",
     "認定対象者の年間収入が一三〇万円未満(認定対象者が六〇歳以上の者である場合又は概ね厚生年金保険法による障害厚生年金の受給要件に該当する程度の障害者である場合にあっては一八〇万円未満)であって、かつ、被保険者の年間収入の二分の一未満である場合は、原則として被扶養者に該当するものとすること。"),
    ("GD5.1-S52-2", "GD§5.1", "S52_tsuchi", "被保険者からの援助に依る収入額より少ない場合には、原則として被扶養者に該当するものとすること。"),
    ("GD5.1-S52-date", "GD§0", "S52_tsuchi", "昭和五二年四月六日"),
    ("GD5.1-KFAQ", "GD§5.1", "kyoukai_faq_dependent", "令和7年中の課税収入額が130万円（60歳以上は180万円、19歳以上23歳未満かつ配偶者でない場合は150万円）以上の方"),
    ("GD5.2-NKYOJU", "GD§5.2", "nenkin_kyojuyoken", "被保険者と同居していることが確認できる公的証明書またはそれに準ずる書類"),
    ("GD5.3-R01-1a", "GD§5.3", "R01_kokunai", "住民基本台帳に住民登録されているかどうか(住民票があるかどうか)で判断し、住民票が日本国内にある者は原則、国内居住要件を満たす"),
    ("GD5.3-R01-1b", "GD§5.3", "R01_kokunai", "住民票が日本国内にあっても、海外で就労しており、日本で全く生活していないなど、明らかに日本での居住実態がないことが判明した場合は、保険者において、例外的に国内居住要件を満たさないものと判断して差し支えない"),
    ("GD5.3-R01-2", "GD§5.3", "R01_kokunai", "これまで日本で生活しており、渡航目的に照らし、今後日本で生活する蓋然性が高いと認められる者(一時的な海外渡航である者)で、かつ渡航目的が就労ではない者を基本に類型化"),
    ("GD5.3-R01-date", "GD§0", "R01_kokunai", "令和元年11月13日"),
    ("GD5.3-R01-start", "GD§5.3", "R01_kokunai", "令和2年4月1日"),
    ("GD5.3-NKYOJU-a", "GD§5.3", "nenkin_kyojuyoken", "扶養される方の年間収入が被保険者からの年間の仕送り額未満であることが必要"),
    ("GD5.3-NKYOJU-b", "GD§5.3", "nenkin_kyojuyoken", "扶養される方の年間収入が被保険者の年間収入の2分の1未満であることが必要"),
    ("GD5.3-NKYOJU-c", "GD§5.3", "nenkin_kyojuyoken", "海外特例要件"),
    ("GD5.3-NKYOJU-d", "GD§5.3", "nenkin_kyojuyoken", "130万円未満（扶養される方が60歳以上または障害厚生年金の受給要件に該当する程度の障害者である場合は180万円未満）"),
    ("GD5.3-NKYOJU-e", "GD§5.3", "nenkin_kyojuyoken", "被扶養者現況申立書"),
]

# 文言の照合とは別に、ページの構造を確かめるもの
def web_structure_checks(texts, links):
    res = []
    toc = texts.get("sochiho_tsutatsu_toc", "")
    heads = [ln.strip() for ln in toc.splitlines() if re.match(r"\s*第41条の1[5-7]", ln.strip())]
    has_4116 = [ln for ln in toc.splitlines() if re.search(r"第41条の16(?![の0-9０-９])", ln)]
    res.append({"id": "GD1.3-SOTOC-no4116", "where": "LW§2.3・GD§1.3", "ok": not has_4116,
                "evidence": {"heads_41_15_to_17": heads, "lines_with_41_16": has_4116}})
    kg_links = [lk for lk in links.get("kokugai_index", []) if "0022009-107_02" in lk["href"]]
    res.append({"id": "GD0-KGIDX-linktext", "where": "GD§0・MS§4-3", "ok": any("令和７年６月更新" in lk["text"] for lk in kg_links),
                "evidence": kg_links})
    s52 = texts.get("S52_tsuchi", "")
    res.append({"id": "GD5.1-S52-60count", "where": "GD§5.1・MS§3", "ok": s52.count("六〇歳以上の者である場合") == 3 and s52.count("一八〇万円未満") == 3,
                "evidence": {"六〇歳以上の者である場合": s52.count("六〇歳以上の者である場合"), "一八〇万円未満": s52.count("一八〇万円未満")}})
    res.append({"id": "GD5.1-S52-notime", "where": "GD§5.1・GD§6-4", "ok": all(w not in s52 for w in ("十二月三十一日", "時点", "12月31日")),
                "evidence": {w: (w in s52) for w in ("十二月三十一日", "時点", "12月31日", "認定日")}})
    # R01 と R05（改正後の全文）が「第1」以降で同じか（担当とは別の正規化：NFKC・空白除去・表の区切りを除いて行ごと）
    def body_from(t, head):
        lines = [norm(x) for x in t.splitlines()]
        lines = [x for x in lines if x and x != "|"]
        i = next((k for k, x in enumerate(lines) if x.startswith(norm(head))), None)
        return lines[i:] if i is not None else None
    r1 = body_from(texts.get("R01_kokunai", ""), "第1　国内居住要件の考え方について")
    r5 = body_from(texts.get("R05_kokunai_kaisei", ""), "第1　国内居住要件の考え方について")
    same = r1 is not None and r5 is not None and r1 == r5
    first_diff = None
    if r1 is not None and r5 is not None and not same:
        for k, (a, b) in enumerate(zip(r1, r5)):
            if a != b:
                first_diff = {"line": k, "R01": a[:120], "R05": b[:120]}
                break
        if first_diff is None:
            first_diff = {"len_R01": len(r1), "len_R05": len(r5), "tail_R01": r1[len(r5):][:3], "tail_R05": r5[len(r1):][:3]}
    res.append({"id": "GD5.3-R01eqR05", "where": "GD§5.3・MS§3", "ok": same, "evidence": first_diff or {"lines": len(r1 or [])}})
    # robots.txt（User-agent: * の Disallow）
    for rid in ("nta_robots", "mhlw_robots", "nenkin_robots"):
        cur, dis = [], []
        for ln in texts.get(rid, "").splitlines():
            ln = ln.strip()
            if ln.lower().startswith("user-agent:"):
                cur = [ln.split(":", 1)[1].strip()]
            elif ln.lower().startswith("disallow:") and "*" in cur:
                dis.append(ln.split(":", 1)[1].strip())
        res.append({"id": f"MS2.2-{rid}", "where": "MS§2.2", "ok": True, "evidence": dis})
    return res


def run_check_web():
    log, texts, links, titles = html_texts()
    theirs = {}
    for f in THEIR_WEB.glob("*_20261109-173918.json"):
        for r in json.loads(f.read_text(encoding="utf-8"))["results"]:
            theirs[r["id"]] = r
    res = {"fetch_run": log["run_at"], "identity": [], "quotes": [], "structure": []}
    for kind in ("pages", "pdfs"):
        for pid, rec in log[kind].items():
            t = theirs.get(pid, {})
            res["identity"].append({"id": pid, "kind": kind, "status": rec["status"], "bytes": rec["bytes"],
                                    "sha256_16": rec["sha256"][:16], "last_modified": rec["last_modified"],
                                    "title": titles.get(pid),
                                    "their_sha256_16": (t.get("sha256") or "")[:16], "same_sha256": rec["sha256"] == t.get("sha256"),
                                    "same_last_modified": rec["last_modified"] == t.get("last_modified")})
    for qid, where, pid, quote in WEB_QUOTES:
        miss = frags_in_order(quote, texts.get(pid, ""))
        res["quotes"].append({"id": qid, "where": where, "page": pid, "quote": quote, "ok": miss is None, "missing": miss})
    res["structure"] = web_structure_checks(texts, links)
    (OUT / "web_check.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    md = [f"# 行政資料の検証（取得 {log['run_at']}）", "", "## 同一性（担当の取得 20261109-173918 との比較）", "",
          "| ID | 種類 | HTTP | バイト | SHA-256（先頭16） | 担当と同じ | Last-Modified | 担当と同じ |", "|---|---|---|---|---|---|---|---|"]
    for r in res["identity"]:
        md.append(f"| {r['id']} | {r['kind']} | {r['status']} | {r['bytes']} | {r['sha256_16']} | {r['same_sha256']} | {r['last_modified']} | {r['same_last_modified']} |")
    md += ["", "## 文言の照合", "", "| ID | 文書の箇所 | ページ | 結果 | 欠けた断片 |", "|---|---|---|---|---|"]
    for q in res["quotes"]:
        md.append(f"| {q['id']} | {q['where']} | {q['page']} | {'OK' if q['ok'] else '**MISSING**'} | {(q['missing'] or '')[:60]} |")
    md += ["", "## 構造の検査", "", "| ID | 文書の箇所 | 結果 | 根拠 |", "|---|---|---|---|"]
    for s in res["structure"]:
        md.append(f"| {s['id']} | {s['where']} | {'OK' if s['ok'] else '**NG**'} | {json.dumps(s['evidence'], ensure_ascii=False)[:300]} |")
    (OUT / "web_check.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    n_ok = sum(q["ok"] for q in res["quotes"]) + sum(s["ok"] for s in res["structure"])
    print(f"web: {n_ok}/{len(res['quotes']) + len(res['structure'])} OK")
    for q in res["quotes"]:
        if not q["ok"]:
            print("MISSING", q["id"], q["missing"][:80])
    for s in res["structure"]:
        if not s["ok"]:
            print("NG", s["id"], json.dumps(s["evidence"], ensure_ascii=False)[:300])


# ---------------------------------------------------------------- e-Gov の検査

def flat(n, skip_num=True):
    """ノードを平文にする。ルビの読み（Rt）と、skip_num のときは番号・見出し（*Num・*Title・*Caption）を落とす。"""
    if isinstance(n, str):
        return n
    tag = n.get("tag", "")
    if tag == "Rt":
        return ""
    if skip_num and (tag.endswith("Num") or tag.endswith("Title") or tag.endswith("Caption")):
        return ""
    return "".join(flat(c, skip_num) for c in n.get("children", []))


def kids(n, tag):
    return [c for c in n.get("children", []) if isinstance(c, dict) and c.get("tag") == tag]


def walk(n, fn, path=()):
    if isinstance(n, dict):
        fn(n, path)
        for c in n.get("children", []):
            walk(c, fn, path + (n,))


def main_articles(root):
    arts = {}

    def collect(n, path):
        if n.get("tag") == "Article" and not any(p.get("tag") == "SupplProvision" for p in path):
            arts.setdefault(n["attr"].get("Num"), n)
    walk(root, collect)
    return arts


def suppl_articles(root, amend_key):
    out = {}
    sps = []
    walk(root, lambda n, p: sps.append(n) if n.get("tag") == "SupplProvision" and amend_key in n.get("attr", {}).get("AmendLawNum", "") else None)
    for sp in sps:
        for a in kids(sp, "Article"):
            out.setdefault(a["attr"].get("Num"), a)
    return out


def caption(a):
    for c in a.get("children", []):
        if isinstance(c, dict) and c.get("tag") == "ArticleCaption":
            return flat(c, skip_num=False)
    return ""


SUBTAGS = ["Paragraph", "Item", "Subitem1", "Subitem2", "Subitem3"]


def locate(arts, path):
    """path = [条, 項, 号, イロハ, (1)(2)...]。項以下は省略可。"""
    node = arts.get(path[0])
    for depth, num in enumerate(path[1:]):
        if node is None:
            return None
        ch = [c for c in kids(node, SUBTAGS[depth]) if c.get("attr", {}).get("Num") == str(num)]
        node = ch[0] if ch else None
    return node


S3 = ["2025-12-31", "2026-11-09", "2026-12-31"]
S5 = S3 + ["2027-01-01", "2027-03-15"]       # 所法（2027 の版は fetch-egov2）
R4 = S3 + ["2027-03-15"]                      # 所令・所規
C3 = ["2026-01-01", "2026-11-09", "2027-01-01"]
K2 = ["2025-12-31", "2026-11-09"]

# (ID, 文書の箇所, 法令, [asof...], 場所（条・項・号・イロハ…。"S:<改正法令番号>" で始まれば改正附則）, 文言（「…」で区切る）)
LAW_QUOTES = [
    ("LW1.1-2-34_4", "LW§1.1", "shotoku", S5, ["2", 1, "34_4"], "控除対象扶養親族のうち、年齢七十歳以上の者をいう。"),
    ("LW1.1-84-1", "LW§1.1", "shotoku", S5, ["84", 1],
     "居住者が控除対象扶養親族を有する場合には、その居住者のその年分の総所得金額、退職所得金額又は山林所得金額から、その控除対象扶養親族一人につき三十八万円（その者が特定扶養親族である場合には六十三万円とし、その者が老人扶養親族である場合には四十八万円とする。）を控除する。"),
    ("LW1.1-85-3", "LW§1.1", "shotoku", S5, ["85", 3], "その年十二月三十一日の現況による。ただし、その判定に係る者がその当時既に死亡している場合は、当該死亡の時の現況による。"),
    ("LW1.2-2-34-58", "LW§1.2", "shotoku", ["2025-12-31", "2026-11-09"], ["2", 1, "34"], "合計所得金額が五十八万円以下である者"),
    ("LW1.2-2-34-62", "LW§1.2", "shotoku", ["2026-12-31", "2027-03-15"], ["2", 1, "34"], "合計所得金額が六十二万円以下である者"),
    ("LW1.2-2-34_3", "IE11", "shotoku", S5, ["2", 1, "34_3"], "控除対象扶養親族のうち、年齢十九歳以上二十三歳未満の者をいう。"),
    ("LW0-R8-12-s1-4", "LW§0", "shotoku", ["2026-12-31"], ["S:令和八年三月三一日法律第一二号", "1", 1, "4"], "令和八年十二月一日"),
    ("LW0-R8-12-s1-4i", "LW§0", "shotoku", ["2026-12-31"], ["S:令和八年三月三一日法律第一二号", "1", 1, "4", "1"], "同項第三十三号及び第三十四号の改正規定"),
    ("LW0-R8-12-s2", "LW§0", "shotoku", ["2026-12-31"], ["S:令和八年三月三一日法律第一二号", "2", 1],
     "新所得税法…第二条第一項（第三十二号（ロに係る部分を除く。）、第三十三号及び第三十四号に係る部分に限る。）の規定は、令和八年分以後の所得税について適用し、令和七年分以前の所得税については、なお従前の例による。"),
    # §2 措法41の16
    ("LW2.1-41_16-1", "LW§2.1", "sochi", S3, ["41_16", 1],
     "居住者の有する所得税法第二条第一項第三十四号の四に規定する老人扶養親族が当該居住者又は当該居住者の配偶者の直系尊属で、かつ、当該居住者又は当該配偶者のいずれかとの同居を常況としている者である場合には、当該老人扶養親族に係る同法第八十四条第二項に規定する扶養控除の額は、同条第一項の規定にかかわらず、同項の金額に十万円を加算した額とする。"),
    ("LW2.1-41_16-2", "LW§2.1", "sochi", S3, ["41_16", 2],
     "前項の規定の適用がある場合における所得税法の規定の適用については、次の表の上欄に掲げる同法の規定中同表の中欄に掲げる字句は、同表の下欄に掲げる字句にそれぞれ読み替えるものとする。"
     "…第八十五条第三項…老人扶養親族…租税特別措置法第四十一条の十六第一項（同居の老親等に係る扶養控除の特例）の規定に該当する老人扶養親族若しくはその他の老人扶養親族"
     "…第百九十条第二号ハ…の規定…並びに租税特別措置法第四十一条の十六第一項（同居の老親等に係る扶養控除の特例）の規定"
     "…第百九十四条第一項第五号…老人扶養親族…租税特別措置法第四十一条の十六第一項（同居の老親等に係る扶養控除の特例）の規定に該当する老人扶養親族若しくはその他の老人扶養親族"),
    # §3.1 所法2①三十四の二
    ("LW3.1-2-34_2", "LW§3.1", "shotoku", S5, ["2", 1, "34_2"],
     "扶養親族のうち、次に掲げる者の区分に応じそれぞれ次に定める者をいう。…居住者…年齢十六歳以上の者…非居住者…年齢十六歳以上三十歳未満の者及び年齢七十歳以上の者並びに年齢三十歳以上七十歳未満の者であつて次に掲げる者のいずれかに該当するもの"
     "…留学により国内に住所及び居所を有しなくなつた者…障害者…その居住者からその年において生活費又は教育費に充てるための支払を三十八万円以上受けている者"),
    ("LW3.1-R2-8-s1-6", "LW§3.1", "shotoku", ["2026-12-31"], ["S:令和二年三月三一日法律第八号", "1", 1, "6"],
     "第一条中所得税法第二条第一項第三十四号の二の改正規定、同法第百二十条第三項の改正規定、同法第百九十四条の改正規定（同条第一項第二号に係る部分を除く。）…並びに附則第三条…の規定…令和五年一月一日"),
    ("LW3.1-R2-8-s3", "LW§3.1", "shotoku", ["2026-12-31"], ["S:令和二年三月三一日法律第八号", "3", 1],
     "新所得税法第二条第一項（第三十四号の二に係る部分に限る。）…並びに所得税法第八十四条の規定は、令和五年分以後の所得税…について適用し、令和四年分以前の所得税…については、なお従前の例による。"),
    # §3.2 確定申告の書類
    ("LW3.2-120-3", "LW§3.2", "shotoku", S5, ["120", 3], "当該申告書に添付し、又は当該申告書の提出の際提示しなければならない"),
    ("LW3.2-120-3-2", "LW§3.2・§3.4", "shotoku", S5, ["120", 3, "2"],
     "第八十五条第二項又は第三項…の規定による判定をする時の現況において非居住者である親族に係る障害者控除、配偶者控除又は配偶者特別控除…これらの控除に係る非居住者である親族が当該居住者の親族に該当する旨を証する書類及び当該非居住者である親族が当該居住者と生計を一にすることを明らかにする書類"),
    ("LW3.2-120-3-3", "LW§3.2・§3.4", "shotoku", S5, ["120", 3, "3"],
     "第八十五条第三項の規定による判定をする時の現況において非居住者である親族に係る扶養控除又は特定親族特別控除…並びに当該非居住者である親族が年齢三十歳以上七十歳未満の者である場合（当該非居住者である親族が障害者である場合を除く。）には第二条第一項第三十四号の二ロ（１）…に掲げる者に該当する旨を証する書類又は同号ロ（３）に掲げる者に該当することを明らかにする書類"),
    ("LW3.2-rei262-3", "LW§3.2", "shotoku-rei", R4, ["262", 3], "国外居住障害者…国外居住配偶者…各人別に確定申告書に添付し、又は当該申告書の提出の際提示しなければならない"),
    ("LW3.2-rei262-4", "LW§3.2", "shotoku-rei", R4, ["262", 4],
     "控除対象扶養親族又は法第八十四条の二第一項（特定親族特別控除）に規定する特定親族（以下この項において「国外居住扶養親族等」という。）の各人別に"
     "…ただし、法第百九十条第二号の規定により…控除された扶養控除若しくは特定親族特別控除の額に相当する金額…法第百九十四条第五項、第百九十五条第五項若しくは第二百三条の六第三項の規定により提出し、若しくは提示した…については、この限りでない。"),
    ("LW3.2-rei262-4-1", "LW§3.2", "shotoku-rei", R4, ["262", 4, "1"], "配偶者以外の親族に該当する旨を証する書類…生計を一にすることを明らかにする書類"),
    ("LW3.2-rei262-4-2", "LW§3.2", "shotoku-rei", R4, ["262", 4, "2"], "法第二条第一項第三十四号の二ロ（１）（定義）に掲げる者に該当するものとして扶養控除に関する事項を記載する場合…前号イに掲げる書類…前号ロに掲げる書類…法第二条第一項第三十四号の二ロ（１）に掲げる者に該当する旨を証する書類"),
    ("LW3.2-rei262-4-3", "LW§3.2", "shotoku-rei", R4, ["262", 4, "3"], "法第二条第一項第三十四号の二ロ（３）に掲げる者に該当するものとして扶養控除に関する事項を記載する場合…第一号イに掲げる書類…法第二条第一項第三十四号の二ロ（３）に掲げる者に該当することを明らかにする書類"),
    ("LW3.2-ki47_2-5", "LW§3.2", "shotoku-ki", R4, ["47_2", 5],
     "当該書類が外国語で作成されている場合には、その翻訳文を含む。…戸籍の附票の写しその他の国又は地方公共団体が発行した書類及び旅券…の写し…外国政府又は外国の地方公共団体が発行した書類（…氏名、生年月日及び住所又は居所の記載があるものに限る。）"),
    ("LW3.2-ki47_2-6", "LW§3.2", "shotoku-ki", R4, ["47_2", 6], "その年において…生活費又は教育費に充てるための支払を必要の都度、各人に行つたことを明らかにするもの"),
    ("LW3.2-ki47_2-7", "LW§3.2", "shotoku-ki", R4, ["47_2", 7],
     "戸籍の附票の写しその他の国又は地方公共団体が発行した書類及び旅券の写し…外国政府又は外国の地方公共団体が発行した書類（当該国外居住扶養親族等の氏名、生年月日及び住所又は居所の記載があるものに限る。）"),
    ("LW3.2-ki47_2-8", "LW§3.2", "shotoku-ki", R4, ["47_2", 8],
     "その年において国外居住扶養親族等の生活費又は教育費に充てるための支払を必要の都度、各人に行つたことを明らかにするもの…金融機関の書類又はその写しで、当該金融機関が行う為替取引によつて"
     "…クレジットカード等購入あつせん業者の書類又はその写しで、クレジットカード等を当該国外居住扶養親族等が提示し又は通知して…当該居住者から受領し、又は受領することとなることを明らかにするもの"
     "…電子決済手段等取引業者の書類又はその写しで…電子決済手段の移転によつて当該居住者から当該国外居住扶養親族等に支払をしたことを明らかにするもの"),
    ("LW3.2-ki47_2-9", "LW§3.2", "shotoku-ki", R4, ["47_2", 9],
     "外国政府又は外国の地方公共団体が発行した…外国における出入国管理及び難民認定法別表第一の四の表（在留資格）の留学の在留資格に相当する資格をもつて当該外国に在留することにより国内に住所及び居所を有しなくなつた旨を証するもの"
     "…外国における査証に類する書類の写し…在留カードに相当する書類の写し"),
    ("LW3.2-ki47_2-10", "LW§3.2", "shotoku-ki", R4, ["47_2", 10],
     "居住者から国外居住扶養親族等である各人へのその年における…支払の金額の合計額が三十八万円以上であることを明らかにするもの"),
    # §3.3 源泉徴収・年末調整
    ("LW3.3-194-1-7", "LW§3.3", "shotoku", ["2026-11-09", "2026-12-31"], ["194", 1, "7"], "非居住者である親族である場合にはその旨"),
    ("LW3.3-194-5", "LW§3.3", "shotoku", S3, ["194", 5], "「国外居住親族」という。）が当該居住者の親族に該当する旨を証する書類…提出し、又は提示しなければならない。"),
    ("LW3.3-194-6", "LW§3.3", "shotoku", S3, ["194", 6], "その年最後に給与等の支払を受ける日の前日までに、当該国外居住親族が当該居住者と生計を一にする事実"),
    ("LW3.3-194-7", "LW§3.3", "shotoku", S3, ["194", 7], "生計を一にすることを明らかにする書類…第二条第一項第三十四号の二ロ（３）に掲げる者に該当するものとして…同号ロ（３）に掲げる者に該当することを明らかにする書類"),
    ("LW3.3-190-2-ha", "LW§3.3", "shotoku", S3, ["190", 1, "2", "3"], "国外居住親族である場合には、第百九十四条第五項及び第七項…に規定する書類の提出又は提示がされた"),
    ("LW3.3-190-2-ni", "LW§3.3", "shotoku", S3, ["190", 1, "2", "4"], "給与所得者の配偶者控除等申告書"),
    ("LW3.3-190-2-ho", "LW§3.3", "shotoku", S3, ["190", 1, "2", "5"], "給与所得者の特定親族特別控除申告書…書類の提出又は提示がされた特定親族に限る。"),
    ("LW3.3-R7-13-s1-2", "LW§3.3（補足）", "shotoku", ["2026-12-31"], ["S:令和七年三月三一日法律第一三号", "1", 1, "2", "1"],
     "同項第三十四号の四の次に一号を加える改正規定…同法第百九十四条の改正規定"),
    ("LW3.3-R7-13-s1-2d", "LW§3.3（補足）", "shotoku", ["2026-12-31"], ["S:令和七年三月三一日法律第一三号", "1", 1, "2"], "令和八年一月一日"),
    ("LW3.3-R7-13-s9-4", "LW§3.3（補足）", "shotoku", ["2026-12-31"], ["S:令和七年三月三一日法律第一三号", "9", 4],
     "新所得税法第百九十四条第一項及び第五項…の規定は、令和八年一月一日以後に支払を受けるべき給与等について提出する…給与所得者の扶養控除等申告書…について適用し"),
    # §4 居住者
    ("LW4-2-3", "LW§4", "shotoku", S5, ["2", 1, "3"], "国内に住所を有し、又は現在まで引き続いて一年以上居所を有する個人をいう。"),
    ("LW4-2-4", "LW§4", "shotoku", S5, ["2", 1, "4"], "居住者のうち、日本の国籍を有しておらず、かつ、過去十年以内において国内に住所又は居所を有していた期間の合計が五年以下である個人をいう。"),
    ("LW4-2-5", "LW§4", "shotoku", S5, ["2", 1, "5"], "居住者以外の個人をいう。"),
    ("LW4-3-1", "LW§4", "shotoku", S5, ["3", 1],
     "国家公務員又は地方公務員（これらのうち日本の国籍を有しない者その他政令で定める者を除く。）は、国内に住所を有しない期間についても国内に住所を有するものとみなして、この法律（第十条…、第十五条…及び第十六条…を除く。）の規定を適用する。"),
    ("LW4-3-2", "LW§4", "shotoku", S5, ["3", 2], "前項に定めるもののほか、居住者及び非居住者の区分に関し、個人が国内に住所を有するかどうかの判定について必要な事項は、政令で定める。"),
    ("LW4-rei13", "LW§4", "shotoku-rei", R4, ["13", 1], "日本の国籍を有する者で、現に国外に居住し、かつ、その地に永住すると認められるもの"),
    ("LW4-rei14-1", "LW§4", "shotoku-rei", R4, ["14", 1],
     "国内に居住することとなつた個人が…その者が国内において、継続して一年以上居住することを通常必要とする職業を有すること。…その者が日本の国籍を有し、かつ、その者が国内において生計を一にする配偶者その他の親族を有することその他国内におけるその者の職業及び資産の有無等の状況に照らし、その者が国内において継続して一年以上居住するものと推測するに足りる事実があること。"),
    ("LW4-rei14-2", "LW§4", "shotoku-rei", R4, ["14", 2], "生計を一にする配偶者その他その者の扶養する親族が国内に居住する場合には、これらの者も国内に住所を有する者と推定する。"),
    ("LW4-rei15-1", "LW§4", "shotoku-rei", R4, ["15", 1],
     "国外に居住することとなつた個人が…その者が国外において、継続して一年以上居住することを通常必要とする職業を有すること。…その者が外国の国籍を有し又は外国の法令によりその外国に永住する許可を受けており、かつ、その者が国内において生計を一にする配偶者その他の親族を有しないことその他国内におけるその者の職業及び資産の有無等の状況に照らし、その者が再び国内に帰り、主として国内に居住するものと推測するに足りる事実がないこと。"),
    ("LW4-rei15-2", "LW§4", "shotoku-rei", R4, ["15", 2], "生計を一にする配偶者その他その者の扶養する親族が国外に居住する場合には、これらの者も国内に住所を有しない者と推定する。"),
    # §5 地方税法
    ("LW5.1-314_2-1-11", "LW§5.1", "chiho", C3, ["314_2", 1, "11"],
     "三十三万円（その者が特定扶養親族…である場合には四十五万円、その者が老人扶養親族（控除対象扶養親族のうち、年齢七十歳以上の者をいう。…）である場合には三十八万円）"
     "…所得税法第二条第一項第三号に規定する居住者…年齢十六歳以上の者…所得税法第二条第一項第五号に規定する非居住者…年齢十六歳以上三十歳未満の者及び年齢七十歳以上の者並びに年齢三十歳以上七十歳未満の者であつて次に掲げる者のいずれかに該当するもの"
     "…留学によりこの法律の施行地に住所及び居所を有しなくなつた者…障害者…その市町村民税の納税義務者から前年において生活費又は教育費に充てるための支払を三十八万円以上受けている者"),
    ("LW5.1-314_2-4", "LW§5.1", "chiho", C3, ["314_2", 4],
     "所得割の納税義務者の有する老人扶養親族が当該納税義務者又は当該納税義務者の配偶者の直系尊属で、かつ、当該納税義務者又は当該配偶者のいずれかとの同居を常況としている者（第三百十四条の六において「同居直系尊属」という。）である場合には、当該老人扶養親族に係る第一項第十一号の金額は、四十五万円とする。"),
    ("LW5.1-314_2-8", "LW§5.1", "chiho", C3, ["314_2", 8], "第四項の規定に該当する老人扶養親族…前年の十二月三十一日（前年の中途においてその者が死亡した場合には、その死亡の時）の現況による"),
    ("LW5.1-34-4", "LW§5.1", "chiho", C3, ["34", 4], "（第三十七条において「同居直系尊属」という。）…四十五万円とする。"),
    ("LW5.1-diff-new", "LW§5.1", "chiho", ["2026-11-09", "2027-01-01"], ["314_2", 1, "11"], "以下この款及び第三百十七条の三の三第一項において同じ。"),
    ("LW5.1-diff-old", "LW§5.1", "chiho", ["2026-01-01"], ["314_2", 1, "11"], "以下この款において同じ。"),
    ("LW5.2-314_6-tbl", "LW§5.2", "chiho", C3, ["314_6", 1, "1", "1"],
     "控除対象扶養親族（同居直系尊属である老人扶養親族を除く。）を有する所得割の納税義務者…当該控除対象扶養親族一人につき五万円…当該特定扶養親族一人につき十八万円…当該控除対象扶養親族が老人扶養親族である場合…当該老人扶養親族一人につき十万円"
     "…同居直系尊属である老人扶養親族を有する所得割の納税義務者…当該老人扶養親族一人につき十三万円"),
    ("LW5.2-314_6-1", "LW§5.2", "chiho", C3, ["314_6", 1, "1"], "二百万円以下である場合…いずれか少ない金額の百分の三（当該納税義務者が指定都市の区域内に住所を有する場合には、百分の四）"),
    ("LW5.2-314_6-1i", "LW§5.2", "chiho", C3, ["314_6", 1, "1", "1"], "五万円に、"),
    ("LW5.2-314_6-1ro", "LW§5.2", "chiho", C3, ["314_6", 1, "1", "2"], "当該納税義務者の合計課税所得金額"),
    ("LW5.2-314_6-2", "LW§5.2", "chiho", C3, ["314_6", 1, "2"], "二百万円を超える場合…（当該金額が五万円を下回る場合には、五万円とする。）の百分の三（当該納税義務者が指定都市の区域内に住所を有する場合には、百分の四）"),
    ("LW5.2-314_6-2ro", "LW§5.2", "chiho", C3, ["314_6", 1, "2", "2"], "合計課税所得金額から二百万円を控除した金額"),
    ("LW5.2-314_6-cap", "LW§5.2（補足）", "chiho", C3, ["314_6", 1], "前年の合計所得金額が二千五百万円以下である所得割の納税義務者"),
    ("LW5.2-37-cap", "LW§5.2（補足）", "chiho", C3, ["37", 1], "前年の合計所得金額が二千五百万円以下である所得割の納税義務者"),
    ("LW5.2-37-1-1", "LW§5.2・§7（補足）", "chiho", C3, ["37", 1, "1"], "二百万円以下である場合…いずれか少ない金額の百分の二（当該納税義務者が指定都市の区域内に住所を有する場合には、百分の一）"),
    ("LW5.2-37-1-2", "LW§5.2・§7（補足）", "chiho", C3, ["37", 1, "2"], "（当該金額が五万円を下回る場合には、五万円とする。）の百分の二（当該納税義務者が指定都市の区域内に住所を有する場合には、百分の一）"),
    ("LW5.2-37-tbl", "LW§5.1・§5.2", "chiho", C3, ["37", 1, "1", "1"], "同居直系尊属である老人扶養親族を除く。…当該老人扶養親族一人につき十万円…同居直系尊属である老人扶養親族を有する所得割の納税義務者…当該老人扶養親族一人につき十三万円"),
    ("IE2e-292-1-9-58", "IE2", "chiho", ["2026-01-01", "2026-11-09"], ["292", 1, "9"], "前年の合計所得金額が五十八万円以下"),
    ("IE2e-292-1-9-62", "IE2", "chiho", ["2027-01-01"], ["292", 1, "9"], "前年の合計所得金額が六十二万円以下"),
    # §5.3 地規2の2
    ("LW5.3-ki2_2-4", "LW§5.3", "chiho-ki", ["2026-01-01", "2026-11-09"], ["2_2", 4],
     "法第三十四条第八項及び第三百十四条の二第八項の規定による判定をするときの現況において所得税法第二条第一項第五号に規定する非居住者である者…「国外居住者」という。）に係る障害者控除額、配偶者控除額又は配偶者特別控除額…所得税法施行規則第四十七条の二第五項及び第六項に規定する書類"),
    ("LW5.3-ki2_2-5", "LW§5.3", "chiho-ki", ["2027-01-01"], ["2_2", 5],
     "法第三十四条第八項及び第三百十四条の二第八項の規定による判定をするときの現況において所得税法第二条第一項第五号に規定する非居住者である者…「国外居住者」という。）に係る障害者控除額、配偶者控除額又は配偶者特別控除額…所得税法施行規則第四十七条の二第五項及び第六項に規定する書類"),
    ("LW5.3-ki2_2-5b", "LW§5.3", "chiho-ki", ["2026-01-01", "2026-11-09"], ["2_2", 5],
     "国外居住者に係る扶養控除額又は特定親族特別控除額…ただし、所得税法の規定に基づいて所得税の確定申告書に添付し…所得税法施行規則第四十七条の二第七項…第八項…第九項…第十項"),
    ("LW5.3-ki2_2-6b", "LW§5.3", "chiho-ki", ["2027-01-01"], ["2_2", 6],
     "国外居住者に係る扶養控除額又は特定親族特別控除額…ただし、所得税法の規定に基づいて所得税の確定申告書に添付し…所得税法施行規則第四十七条の二第七項…第八項…第九項…第十項"),
    ("LW5.3-ki2_2-6c", "LW§5.3", "chiho-ki", ["2026-01-01", "2026-11-09"], ["2_2", 6],
     "年齢十六歳未満である者（以下「控除対象外国外扶養親族」という。）…「控除対象外国外同一生計配偶者」という。…「非課税限度額制度適用者」という。…国外扶養親族証明書類…国外配偶者証明書類"),
    ("LW5.3-ki2_2-7c", "LW§5.3", "chiho-ki", ["2027-01-01"], ["2_2", 7],
     "年齢十六歳未満である者（以下「控除対象外国外扶養親族」という。）…「控除対象外国外同一生計配偶者」という。…「非課税限度額制度適用者」という。…国外扶養親族証明書類…国外配偶者証明書類"),
    ("LW5.3-ki2_2-7d", "LW§5.3", "chiho-ki", ["2026-01-01", "2026-11-09"], ["2_2", 7], "前項の国外扶養親族証明書類とは"),
    ("LW5.3-ki2_2-8d", "LW§5.3", "chiho-ki", ["2026-01-01", "2026-11-09"], ["2_2", 8], "第六項の国外配偶者証明書類とは"),
    ("LW5.3-ki2_2-8d27", "LW§5.3", "chiho-ki", ["2027-01-01"], ["2_2", 8], "前項の国外扶養親族証明書類とは"),
    ("LW5.3-ki2_2-9d27", "LW§5.3", "chiho-ki", ["2027-01-01"], ["2_2", 9], "第七項の国外配偶者証明書類とは"),
    ("LW5.3-ki2_3-5", "LW§5.3（訂正）", "chiho-ki", C3, ["2_3", 5],
     "控除対象外国外扶養親族に係る…確定申告書を提出する者が非課税限度額制度適用者である場合には…国外扶養親族証明書類…を三月十五日までに市町村長に提出しなければならない。"),
    ("LW5.3-ki2_3-6", "LW§5.3（訂正）", "chiho-ki", C3, ["2_3", 6],
     "控除対象外国外同一生計配偶者に係る…確定申告書を提出する者が非課税限度額制度適用者である場合には…国外配偶者証明書類…を三月十五日までに市町村長に提出しなければならない。"),
    # §6 健保
    ("LW6.1-k3-7", "LW§6.1", "kenpo", K2, ["3", 7],
     "この法律において「被扶養者」とは、次に掲げる者で、日本国内に住所を有するもの又は外国において留学をする学生その他の日本国内に住所を有しないが渡航目的その他の事情を考慮して日本国内に生活の基礎があると認められるものとして厚生労働省令で定めるものをいう。ただし、後期高齢者医療の被保険者等である者その他この法律の適用を除外すべき特別の理由がある者として厚生労働省令で定める者は、この限りでない。"),
    ("LW6.1-k3-7-1", "LW§6.1", "kenpo", K2, ["3", 7, "1"],
     "被保険者（日雇特例被保険者であった者を含む。以下この項において同じ。）の直系尊属、配偶者（届出をしていないが、事実上婚姻関係と同様の事情にある者を含む。以下この項において同じ。）、子、孫及び兄弟姉妹であって、主としてその被保険者により生計を維持するもの"),
    ("LW6.1-k3-7-2", "LW§6.1", "kenpo", K2, ["3", 7, "2"], "被保険者の三親等内の親族で前号に掲げる者以外のものであって、その被保険者と同一の世帯に属し、主としてその被保険者により生計を維持するもの"),
    ("LW6.1-k3-7-3", "LW§6.1", "kenpo", K2, ["3", 7, "3"], "被保険者の配偶者で届出をしていないが事実上婚姻関係と同様の事情にあるものの父母及び子"),
    ("LW6.1-k3-7-4", "LW§6.1", "kenpo", K2, ["3", 7, "4"], "前号の配偶者の死亡後におけるその父母及び子"),
    ("LW6.1-k3-1-7", "LW§6.1", "kenpo", K2, ["3", 1, "7"],
     "後期高齢者医療の被保険者（高齢者の医療の確保に関する法律…第五十条の規定による被保険者をいう。）及び同条各号のいずれかに該当する者で同法第五十一条の規定により後期高齢者医療の被保険者とならないもの（以下「後期高齢者医療の被保険者等」という。）"),
    ("LW6.1-kk50-1", "LW§6.1", "koukirei", ["2026-11-09"], ["50", 1, "1"], "後期高齢者医療広域連合の区域内に住所を有する七十五歳以上の者"),
    ("LW6.1-kk50-2", "LW§6.1", "koukirei", ["2026-11-09"], ["50", 1, "2"], "六十五歳以上七十五歳未満の者であつて…政令で定める程度の障害の状態にある旨の当該後期高齢者医療広域連合の認定を受けたもの"),
    ("LW6.1-kk51-1", "LW§6.1", "koukirei", ["2026-11-09"], ["51", 1, "1"], "生活保護法…による保護を受けている世帯…に属する者"),
    ("LW6.2-kk37_2", "LW§6.2", "kenpo-ki", K2, ["37_2", 1],
     "外国において留学をする学生…外国に赴任する被保険者に同行する者…観光、保養又はボランティア活動その他就労以外の目的で一時的に海外に渡航する者"
     "…被保険者が外国に赴任している間に当該被保険者との身分関係が生じた者であって、第二号に掲げる者と同等と認められるもの…前各号に掲げる者のほか、渡航目的その他の事情を考慮して日本国内に生活の基礎があると認められる者"),
    ("LW6.2-kk37_3", "LW§6.2", "kenpo-ki", K2, ["37_3", 1],
     "日本の国籍を有しない者であって…医療を受ける活動…日常生活上の世話をする活動を行うもの…日本の国籍を有しない者であって…本邦において一年を超えない期間滞在し、観光、保養その他これらに類似する活動を行うもの"),
    ("LW6.2-kk38-1-3", "LW§6.2", "kenpo-ki", K2, ["38", 1, "3"], "第三十七条の二各号のいずれかに該当する者にあっては、その旨"),
    ("LW6.2-kk38-1-2", "LW§6.2", "kenpo-ki", K2, ["38", 1, "2"], "被扶養者が被保険者の直系尊属、配偶者、子、孫及び兄弟姉妹以外の者であるときは、同一の世帯に属した年月日及び扶養するに至った理由"),
]

CAPTIONS = [
    ("LW2.1-cap", "LW§2.1", "sochi", S3, "41_16", "同居の老親等に係る扶養控除の特例"),
    ("LW3.1-cap-R2s3", "LW§3.1", "shotoku", ["2026-12-31"], "S:令和二年三月三一日法律第八号:3", "控除対象扶養親族の定義及び扶養控除に関する経過措置"),
    ("LW4-cap3", "LW§4", "shotoku", S5, "3", "居住者及び非居住者の区分"),
    ("LW4-cap13", "LW§4", "shotoku-rei", R4, "13", "国内に住所を有するものとみなされる公務員から除かれる者"),
    ("LW4-cap14", "LW§4", "shotoku-rei", R4, "14", "国内に住所を有する者と推定する場合"),
    ("LW4-cap15", "LW§4", "shotoku-rei", R4, "15", "国内に住所を有しない者と推定する場合"),
    ("LW6.2-cap37_2", "LW§6.2", "kenpo-ki", K2, "37_2", "法第三条第七項本文の厚生労働省令で定めるもの"),
]

# 版の間で同文か（正規化した平文の比較）。(ID, 文書の箇所, 法令, [asof...], [場所...])
SAME_TEXT = [
    ("SAME-shotoku-2-34_2", "LW§3.1", "shotoku", S5, [["2", 1, "34_2"]]),
    ("SAME-shotoku-2-34_4", "LW§1.1", "shotoku", S5, [["2", 1, "34_4"]]),
    ("SAME-shotoku-84", "LW§1.1・§1.2", "shotoku", S5, [["84"]]),
    ("SAME-shotoku-85-3", "LW§1.1", "shotoku", S5, [["85", 3]]),
    ("SAME-shotoku-120-3-2_3", "LW§3.2", "shotoku", S5, [["120", 3, "2"], ["120", 3, "3"]]),
    ("SAME-shotoku-120-3-all", "LW§3.2", "shotoku", S3, [["120", 3]]),
    ("SAME-shotoku-3", "LW§4", "shotoku", S5, [["3"]]),
    ("SAME-shotoku-2-3_4_5", "LW§4", "shotoku", S5, [["2", 1, "3"], ["2", 1, "4"], ["2", 1, "5"]]),
    ("SAME-rei-13_14_15", "LW§4", "shotoku-rei", R4, [["13"], ["14"], ["15"]]),
    ("SAME-rei-262", "LW§3.2", "shotoku-rei", R4, [["262"]]),
    ("SAME-ki-47_2-5_10", "LW§3.2", "shotoku-ki", R4, [["47_2", k] for k in range(5, 11)]),
    ("SAME-sochi-41_16", "LW§2.1", "sochi", S3, [["41_16"]]),
    ("SAME-chiho-314_2-4_8", "LW§5.1", "chiho", C3, [["314_2", 4], ["314_2", 8]]),
    ("SAME-chiho-34-4", "LW§5.1", "chiho", C3, [["34", 4]]),
    ("SAME-chiho-314_6", "LW§5.2", "chiho", C3, [["314_6"]]),
    ("SAME-kenpo-3-7", "LW§6.1", "kenpo", K2, [["3", 7]]),
    ("SAME-kenpoki-37_2_37_3_38", "LW§6.2", "kenpo-ki", K2, [["37_2"], ["37_3"], ["38"]]),
]


def load_laws():
    data, revs = {}, {}
    for kind in ("egov", "egov2"):
        log = json.loads((OUT / f"{kind}_fetch.json").read_text(encoding="utf-8"))
        d = ROOT / log["download_dir"]
        for e in log["fetches"]:
            if e["status"] != 200:
                continue
            j = json.loads((d / f"{e['short']}_{e['asof']}.json").read_text(encoding="utf-8"))
            data[(e["short"], e["asof"])] = j["law_full_text"]
            revs[(e["short"], e["asof"])] = e
    return data, revs


# 文書（［LW］§0、［MS］§2.1）に書かれた版
REV_CLAIMS = [
    ("shotoku", "2025-12-31", "340AC0000000033_20251218_507AC0000000013", "PreviousEnforced"),
    ("shotoku", "2026-11-09", "340AC0000000033_20261001_507AC0000000070", "CurrentEnforced"),
    ("shotoku", "2026-12-31", "340AC0000000033_20261201_508AC0000000012", "UnEnforced"),
    ("shotoku-rei", "2025-12-31", "340CO0000000096_20251201_507CO0000000120", "PreviousEnforced"),
    ("shotoku-rei", "2026-11-09", "340CO0000000096_20260522_508CO0000000093", "CurrentEnforced"),
    ("shotoku-rei", "2026-12-31", "340CO0000000096_20261201_508CO0000000093", "UnEnforced"),
    ("shotoku-ki", "2025-12-31", "340M50000040011_20251201_507M60000040018", "PreviousEnforced"),
    ("shotoku-ki", "2026-11-09", "340M50000040011_20261001_507M60000040018", "CurrentEnforced"),
    ("shotoku-ki", "2026-12-31", "340M50000040011_20261211_508M60000040017", "UnEnforced"),
    ("sochi", "2025-12-31", "332AC0000000026_20251231_507AC1000000081", "PreviousEnforced"),
    ("sochi", "2026-11-09", "332AC0000000026_20261101_507AC0000000013", "CurrentEnforced"),
    ("sochi", "2026-12-31", "332AC0000000026_20261204_508AC0000000012", "UnEnforced"),
    ("sochi-rei", "2026-11-09", "332CO0000000043_20261101_507CO0000000127", "CurrentEnforced"),
    ("chiho", "2026-01-01", "325AC0000000226_20260101_507AC0000000041", "PreviousEnforced"),
    ("chiho", "2026-11-09", "325AC0000000226_20261101_508AC0000000002", "CurrentEnforced"),
    ("chiho", "2027-01-01", "325AC0000000226_20270101_508AC0000000002", "UnEnforced"),
    ("chiho-ki", "2026-01-01", "329M50000002023_20260101_507M60000008116", "PreviousEnforced"),
    ("chiho-ki", "2026-11-09", "329M50000002023_20261101_508M60000008045", "CurrentEnforced"),
    ("chiho-ki", "2027-01-01", "329M50000002023_20270101_508M60000008089", "UnEnforced"),
    ("kenpo", "2025-12-31", "211AC0000000070_20251212_507AC0000000087", "PreviousEnforced"),
    ("kenpo", "2026-11-09", "211AC0000000070_20261001_507AC0000000087", "CurrentEnforced"),
    ("kenpo-ki", "2025-12-31", "215M10000008036_20251201_507M60000100118", "PreviousEnforced"),
    ("kenpo-ki", "2026-11-09", "215M10000008036_20261001_508M60000100144", "CurrentEnforced"),
    ("koukirei", "2026-11-09", "357AC0000000080_20261001_507AC0000000087", "CurrentEnforced"),
]


def resolve(data, short, asof, path):
    root = data.get((short, asof))
    if root is None:
        return None
    if isinstance(path[0], str) and path[0].startswith("S:"):
        arts = suppl_articles(root, path[0][2:])
        return locate(arts, path[1:])
    return locate(main_articles(root), path)


def run_check_egov():
    data, revs = load_laws()
    their = {}
    for f in ("fetch_log.json", "fetch_log_koukirei.json", "fetch_log_chiho-ki.json"):
        for e in json.loads((THEIR_LAWS / f).read_text(encoding="utf-8"))["fetches"]:
            their[(e["short"], e["asof"])] = e     # 後のログ（chiho-ki）が前のログの値を上書きする
    res = {"revisions": [], "rev_claims": [], "quotes": [], "captions": [], "same": [], "scans": [], "misc": {}}
    for (short, asof), e in sorted(revs.items()):
        t = their.get((short, asof), {})
        res["revisions"].append({"short": short, "asof": asof, "law_revision_id": e.get("law_revision_id"),
                                 "status": e.get("current_revision_status"), "amendment_law_num": e.get("amendment_law_num"),
                                 "amendment_enforcement_date": e.get("amendment_enforcement_date"), "sha256_16": e["sha256"][:16],
                                 "bytes": e["bytes"], "their_sha256_same": (e["sha256"] == t.get("sha256")) if t else None,
                                 "their_bytes": t.get("bytes")})
    for short, asof, rid, st in REV_CLAIMS:
        e = revs.get((short, asof), {})
        res["rev_claims"].append({"short": short, "asof": asof, "claimed": rid, "claimed_status": st,
                                  "actual": e.get("law_revision_id"), "actual_status": e.get("current_revision_status"),
                                  "ok": e.get("law_revision_id") == rid and e.get("current_revision_status") == st})
    for qid, where, short, asofs, path, quote in LAW_QUOTES:
        for asof in asofs:
            node = resolve(data, short, asof, path)
            rec = {"id": qid, "where": where, "law": short, "asof": asof, "path": path}
            if node is None:
                rec.update(ok=False, result="location not found")
            else:
                miss = frags_in_order(quote, flat(node))
                rec.update(ok=miss is None, result="ok" if miss is None else "MISSING", missing=miss)
            res["quotes"].append(rec)
    for cid, where, short, asofs, art, want in CAPTIONS:
        for asof in asofs:
            root = data.get((short, asof))
            if art.startswith("S:"):
                _, key, num = art.split(":")
                a = suppl_articles(root, key).get(num)
            else:
                a = main_articles(root).get(art)
            cap = caption(a) if a else None
            res["captions"].append({"id": cid, "where": where, "law": short, "asof": asof, "caption": cap,
                                    "ok": cap is not None and want in cap})
    for sid, where, short, asofs, paths in SAME_TEXT:
        hashes = {}
        for asof in asofs:
            parts = []
            for p in paths:
                n = resolve(data, short, asof, p)
                parts.append(norm(flat(n)) if n is not None else "<none>")
            hashes[asof] = hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]
        res["same"].append({"id": sid, "where": where, "law": short, "hashes": hashes, "ok": len(set(hashes.values())) == 1})

    # 「同居老親等」の語：本則・附則だけでなく、law_full_text 全体（別表・様式の文字を含む）で数える
    for (short, asof), root in sorted(data.items()):
        whole = flat(root, skip_num=False)
        rec = {"law": short, "asof": asof}
        for w in ("同居老親等", "同居の老親等", "同居直系尊属", "国外居住親族", "国外居住者", "百三十万円", "百八十万円"):
            rec[w] = whole.count(w)
        res["scans"].append(rec)

    # 版の差分（文書の主張）
    def ftext(short, asof, path):
        n = resolve(data, short, asof, path)
        return norm(flat(n)) if n is not None else None
    m = res["misc"]
    # 所法194①五〜七・⑤、所令316の2②三、所規73の2②二：2025-12-31 → 2026-11-09 の違いは語の置換だけか
    for short, paths in (("shotoku", [["194", 1, "5"], ["194", 1, "6"], ["194", 1, "7"], ["194", 5]]),
                         ("shotoku-rei", [["316_2", 2, "3"]]), ("shotoku-ki", [["73_2", 2, "2"]])):
        for p in paths:
            a, b = ftext(short, "2025-12-31", p), ftext(short, "2026-11-09", p)
            m[f"replace_only:{short}:{'-'.join(map(str, p))}"] = {
                "changed": a != b, "old_has_控除対象扶養親族": a is not None and "控除対象扶養親族" in a,
                "new_has_源泉控除対象親族": b is not None and "源泉控除対象親族" in b,
                "equal_after_replace": a is not None and b is not None and a.replace("控除対象扶養親族", "源泉控除対象親族") == b}
    a, b = ftext("shotoku", "2025-12-31", ["194"]), ftext("shotoku", "2026-11-09", ["194"])
    m["replace_only:shotoku:194-whole"] = {"equal_after_replace": a.replace("控除対象扶養親族", "源泉控除対象親族") == b}
    # 地法314の2①十一：2026-01-01 → 2026-11-09 の違いは「以下この款において同じ」の句だけか
    a, b = ftext("chiho", "2026-01-01", ["314_2", 1, "11"]), ftext("chiho", "2026-11-09", ["314_2", 1, "11"])
    m["chiho-314_2-1-11:only_phrase"] = a.replace(norm("以下この款において同じ。"), norm("以下この款及び第三百十七条の三の三第一項において同じ。")) == b
    c = ftext("chiho", "2027-01-01", ["314_2", 1, "11"])
    m["chiho-314_2-1-11:2026-11-09==2027-01-01"] = b == c
    # 所法120条：2026-12-31 → 2027-01-01（令和8年分の確定申告書を出す時期の版）で、どの項・号が変わるか
    def units(short, asof, art):
        a = main_articles(data[(short, asof)]).get(art)
        out = {}
        for p in kids(a, "Paragraph"):
            pn = p["attr"]["Num"]
            out[pn] = norm("".join(flat(c) for c in p.get("children", []) if isinstance(c, dict) and c.get("tag") == "ParagraphSentence"))
            for it in kids(p, "Item"):
                out[f"{pn}-{it['attr']['Num']}"] = norm(flat(it))
        return out
    u1, u2 = units("shotoku", "2026-12-31", "120"), units("shotoku", "2027-01-01", "120")
    m["shotoku-120:2026-12-31→2027-01-01"] = {
        "changed_or_new": sorted(k for k in set(u1) | set(u2) if u1.get(k) != u2.get(k)),
        "unchanged_3-2_3-3": u1.get("3-2") == u2.get("3-2") and u1.get("3-3") == u2.get("3-3") and u1.get("3") == u2.get("3"),
        "paragraphs_2026-12-31": sorted(k for k in u1 if "-" not in k), "paragraphs_2027-01-01": sorted(k for k in u2 if "-" not in k)}
    # 措法41の16 の表の行数と、期限の文言
    for asof in S3:
        n = resolve(data, "sochi", asof, ["41_16", 2])
        rows = []
        walk(n, lambda x, p: rows.append(x) if x.get("tag") == "TableRow" else None)
        txt = flat(resolve(data, "sochi", asof, ["41_16"]))
        m[f"sochi-41_16@{asof}"] = {"table_rows": len(rows),
                                    "time_words": [w for w in ("令和", "平成", "昭和", "までの間", "年分", "まで") if w in txt]}
    # 地規2の2：「国外居住者」等の定義の項の番号（版ごと）
    for asof in C3:
        a = main_articles(data[("chiho-ki", asof)]).get("2_2")
        found = {}
        for p in kids(a, "Paragraph"):
            t = flat(p)
            for w in ("「国外居住者」という", "「控除対象外国外扶養親族」という", "「控除対象外国外同一生計配偶者」という",
                      "「非課税限度額制度適用者」という", "国外扶養親族証明書類とは", "国外配偶者証明書類とは", "扶養控除額又は特定親族特別控除額"):
                if w in t:
                    found.setdefault(w, []).append(p["attr"]["Num"])
        m[f"chiho-ki-2_2@{asof}"] = found
        # 非課税限度額の項（⑥ / ⑦）のただし書に「確定申告書」が含まれるか
        pnum = (found.get("「非課税限度額制度適用者」という") or [None])[0]
        pt = flat(locate(main_articles(data[("chiho-ki", asof)]), ["2_2", pnum])) if pnum else ""
        tail = pt[pt.find("ただし"):] if "ただし" in pt else ""
        m[f"chiho-ki-2_2-hikazei-proviso@{asof}"] = {"paragraph": pnum, "proviso_mentions_確定申告書": "確定申告書" in tail, "proviso": tail[:400]}
    # 道府県民税の調整控除（地法37）の率（担当が読んでいないもの。確認用）
    for asof in C3:
        t = ftext("chiho", asof, ["37", 1, "1"])
        m[f"chiho-37-1-1-rate@{asof}"] = re.findall(r"百分の[一二三四五六七八九十]+", t or "")
    # 地法292①九（住民税の扶養親族の所得要件）
    for asof in C3:
        t = ftext("chiho", asof, ["292", 1, "9"])
        mm = re.search(r"合計所得金額が(.+?)以下", t or "")
        m[f"chiho-292-1-9@{asof}"] = mm.group(1) if mm else None

    (OUT / "egov_check.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# e-Gov による検証", "", "## 取得した版（担当の取得と比較）", "",
          "| 略称 | asof | law_revision_id | 状態 | 改正法令 | 施行日（revision_info） | SHA-256（先頭16） | バイト | 担当と同じ生データ |", "|---|---|---|---|---|---|---|---|---|"]
    for r in res["revisions"]:
        md.append(f"| {r['short']} | {r['asof']} | {r['law_revision_id']} | {r['status']} | {r['amendment_law_num']} | {r['amendment_enforcement_date']} | {r['sha256_16']} | {r['bytes']} | {r['their_sha256_same']} |")
    md += ["", "## 文書（［LW］§0・［MS］§2.1）に書かれた版", "", "| 略称 | asof | 主張 | 実際 | 一致 |", "|---|---|---|---|---|"]
    md += [f"| {c['short']} | {c['asof']} | {c['claimed']} {c['claimed_status']} | {c['actual']} {c['actual_status']} | {c['ok']} |" for c in res["rev_claims"]]
    md += ["", "## 引用・文言の照合", "", "| ID | 文書の箇所 | 法令@版 | 場所 | 結果 | 欠けた断片 |", "|---|---|---|---|---|---|"]
    for q in res["quotes"]:
        md.append(f"| {q['id']} | {q['where']} | {q['law']}@{q['asof']} | {'-'.join(map(str, q['path']))} | {q['result']} | {(q.get('missing') or '')[:50]} |")
    md += ["", "## 見出し", "", "| ID | 法令@版 | 見出し | 一致 |", "|---|---|---|---|"]
    md += [f"| {c['id']} | {c['law']}@{c['asof']} | {c['caption']} | {c['ok']} |" for c in res["captions"]]
    md += ["", "## 版の間で同文か（正規化した平文の SHA-256 先頭16）", "", "| ID | 文書の箇所 | 法令 | 各版 | 同文 |", "|---|---|---|---|---|"]
    md += [f"| {s['id']} | {s['where']} | {s['law']} | {json.dumps(s['hashes'])} | {s['ok']} |" for s in res["same"]]
    md += ["", "## 語の出現回数（law_full_text 全体。別表・様式の文字を含む）", "", "| 法令@版 | 同居老親等 | 同居の老親等 | 同居直系尊属 | 国外居住親族 | 国外居住者 | 百三十万円 | 百八十万円 |", "|---|---|---|---|---|---|---|---|"]
    md += [f"| {s['law']}@{s['asof']} | {s['同居老親等']} | {s['同居の老親等']} | {s['同居直系尊属']} | {s['国外居住親族']} | {s['国外居住者']} | {s['百三十万円']} | {s['百八十万円']} |" for s in res["scans"]]
    md += ["", "## その他", "", "```", json.dumps(res["misc"], ensure_ascii=False, indent=1), "```"]
    (OUT / "egov_check.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    nq = sum(q["ok"] for q in res["quotes"])
    print(f"rev_claims {sum(c['ok'] for c in res['rev_claims'])}/{len(res['rev_claims'])}, quotes {nq}/{len(res['quotes'])}, "
          f"captions {sum(c['ok'] for c in res['captions'])}/{len(res['captions'])}, same {sum(s['ok'] for s in res['same'])}/{len(res['same'])}")
    for q in res["quotes"]:
        if not q["ok"]:
            print("MISSING", q["id"], q["law"], q["asof"], q["result"], (q.get("missing") or "")[:80])
    for c in res["captions"]:
        if not c["ok"]:
            print("CAPTION NG", c)
    for s in res["same"]:
        if not s["ok"]:
            print("NOT SAME", s)


# ---------------------------------------------------------------- 文書の表と取得記録の照合

DOCS = {
    "LW": ROOT / "docs" / "public-sources" / "20261109_round2_elderly-abroad-laws.md",
    "GD": ROOT / "docs" / "public-sources" / "20261109_round2_elderly-abroad-guidance.md",
    "MS": ROOT / "docs" / "measurements" / "20261109_round2_elderly-abroad-fetch-and-checks.md",
    "HY": ROOT / "docs" / "hypotheses" / "20261109_round2_elderly-abroad-model.md",
    "IN": ROOT / "docs" / "inferences" / "20261109_round2_elderly-abroad-cases.md",
}
THEIR_WEB_RAW = {  # 担当の生データ（.work/downloads。データとして読むだけ）
    "kyoukai_faq_dependent": ROOT / ".work" / "downloads" / "20261109-173918_R2X_elderly-abroad_kenpo" / "kyoukai_faq_dependent.html",
}


def html_to_text(body):
    ex = Extract()
    ex.feed(decode_html(body, {}))
    t = "".join(ex.parts)
    t = re.sub(r"[ \t　]+\n", "\n", t)
    return re.sub(r"\n{3,}", "\n\n", t)


def run_check_docs():
    egov = json.loads((OUT / "egov_fetch.json").read_text(encoding="utf-8"))
    web = json.loads((OUT / "web_fetch.json").read_text(encoding="utf-8"))
    mine_law = {(e["short"], e["asof"]): e for e in egov["fetches"]}
    mine_web = {**web["pages"], **web["pdfs"]}
    res = {"MS2.1": [], "MS2.2": [], "LW0": [], "GD0": [], "refs": {}, "kyoukai_text_same": None}
    ms = DOCS["MS"].read_text(encoding="utf-8")
    # ［MS］§2.1：| 略称 | asof | law_revision_id | 状態 | SHA-256（先頭16桁） | バイト |
    for m in re.finditer(r"^\| ([a-z\-]+) \| (\d{4}-\d{2}-\d{2}) \| (\d{3}[A-Z0-9]+_\d{8}_[0-9A-Z]+) \| (\w+)[^|]* \| ([0-9a-f]{16}) \| ([\d,]+) \|$", ms, re.M):
        short, asof, rid, st, sha, by = m.groups()
        e = mine_law.get((short, asof), {})
        res["MS2.1"].append({"row": m.group(0)[:80], "ok": e.get("law_revision_id") == rid and e.get("current_revision_status") == st
                             and e.get("sha256", "")[:16] == sha and e.get("bytes") == int(by.replace(",", ""))})
    # ［MS］§2.2：| セット | ID | Last-Modified | 生データ SHA-256 | バイト | テキスト SHA-256 |
    for m in re.finditer(r"^\| (elderly|abroad|kenpo) \| ([\w]+)(?:（[^）]*）)? \| ([^|]+) \| ([0-9a-f]{16}) \| ([\d,]+) \| ([0-9a-f]{16}|—) \|$", ms, re.M):
        st, pid, lm, sha, by, tsha = m.groups()
        w = mine_web.get(pid, {})
        lm_mine = w.get("last_modified")
        lm_ok = (lm.strip() == "なし" and lm_mine is None) or (lm_mine is not None and dt.datetime.strptime(lm_mine, "%a, %d %b %Y %H:%M:%S GMT").strftime("%Y-%m-%d") == lm.strip())
        their_txt = THEIR_WEB / "text" / f"{st}_20261109-173918" / f"{pid}.txt"
        # 担当のテキストは pathlib.write_text（Windows では LF を CRLF に変換）で保存されている。記録された値はメモリ上のテキストの値なので、
        # (a) universal newline で読んだ値（そのまま再計算した場合）と、(b) バイト列の CRLF を LF に1回だけ戻した値の両方を出す。
        if their_txt.exists():
            raw = their_txt.read_bytes()
            tsha_naive = hashlib.sha256(their_txt.read_text(encoding="utf-8").encode("utf-8")).hexdigest()[:16]
            tsha_lf = hashlib.sha256(raw.decode("utf-8").replace("\r\n", "\n").encode("utf-8")).hexdigest()[:16]
            n_cr = raw.count(b"\r\r\n")
        else:
            tsha_naive = tsha_lf = "—"
            n_cr = None
        refetched = pid in mine_web
        res["MS2.2"].append({"set": st, "id": pid, "refetched": refetched, "last_modified_ok": lm_ok if refetched else None,
                             "sha_same_as_my_fetch": (w.get("sha256", "")[:16] == sha) if refetched else None,
                             "bytes_ok": (w.get("bytes") == int(by.replace(",", ""))) if refetched else None,
                             "text_sha_in_doc": tsha, "their_text_sha_naive": tsha_naive, "their_text_sha_crlf_to_lf": tsha_lf,
                             "crcrlf_in_file": n_cr, "text_sha_ok": tsha == tsha_lf})
    # ［LW］§0 の表の law_revision_id（`_YYYYMMDD_...` の形で書かれたもの）
    lw = DOCS["LW"].read_text(encoding="utf-8")
    law_ids = {"所法": "340AC0000000033", "所令": "340CO0000000096", "所規": "340M50000040011", "措法": "332AC0000000026", "措令": "332CO0000000043",
               "地法": "325AC0000000226", "地規": "329M50000002023", "健保法": "211AC0000000070", "健保則": "215M10000008036", "高確法": "357AC0000000080"}
    shorts = {"所法": "shotoku", "所令": "shotoku-rei", "所規": "shotoku-ki", "措法": "sochi", "措令": "sochi-rei", "地法": "chiho", "地規": "chiho-ki",
              "健保法": "kenpo", "健保則": "kenpo-ki", "高確法": "koukirei"}
    for m in re.finditer(r"^\| (所法|所令|所規|措法|措令|地法|地規|健保法|健保則|高確法) \| [^|]+ \| ([^|]+) \| ([^|]+) \|", lw, re.M):
        name, asofs_s, rids_s = m.groups()
        asofs = [a.strip() for a in asofs_s.replace("同上", "").split("/") if a.strip()]
        rids = re.findall(r"`(_\d{8}_[0-9A-Z]+)`", rids_s)
        if not asofs:   # 「同上」
            asofs = {"所令": ["2025-12-31", "2026-11-09", "2026-12-31"], "所規": ["2025-12-31", "2026-11-09", "2026-12-31"],
                     "措法": ["2025-12-31", "2026-11-09", "2026-12-31"]}[name]
        for a, r in zip(asofs, rids):
            e = mine_law.get((shorts[name], a), {})
            res["LW0"].append({"law": name, "asof": a, "claimed": law_ids[name] + r, "actual": e.get("law_revision_id"),
                               "ok": e.get("law_revision_id") == law_ids[name] + r})
    # ［GD］§0 の出典一覧：URL と Last-Modified
    gd = DOCS["GD"].read_text(encoding="utf-8")
    url2id = {rec["url"]: pid for pid, rec in mine_web.items()}
    for m in re.finditer(r"^\| ［[^］]+］(?:［[^］]+］)? \| [^|]+ \| ([^|]+) \| [^|]* \| ([^|]+) \|$", gd, re.M):
        urls = re.findall(r"https?://\S+", m.group(1))
        lms = [x.strip() for x in m.group(2).split("・")]
        for i, u in enumerate(urls):
            pid = url2id.get(u)
            lm_claim = lms[i] if i < len(lms) else lms[-1]
            if pid is None:
                res["GD0"].append({"url": u, "ok": None, "note": "この検証では取得していない URL（…/ で省略した形を含む）"})
                continue
            lm_mine = mine_web[pid].get("last_modified")
            ok = (lm_claim == "なし" and lm_mine is None) or (lm_mine is not None and dt.datetime.strptime(lm_mine, "%a, %d %b %Y %H:%M:%S GMT").strftime("%Y-%m-%d") == lm_claim)
            res["GD0"].append({"url": u, "id": pid, "status": mine_web[pid]["status"], "last_modified_claim": lm_claim, "last_modified": lm_mine, "ok": ok and mine_web[pid]["status"] == 200})
    # 参照の規則：仮説・推測の文書に外部 URL がないか、仮説が参照する文書の種類
    for k in ("HY", "IN"):
        t = DOCS[k].read_text(encoding="utf-8")
        res["refs"][k] = {"urls": re.findall(r"https?://\S+", t),
                          "doc_refs": sorted(set(re.findall(r"docs/([a-z\-]+)/[\w\-]+\.md", t)))}
    # 協会けんぽ FAQ：担当の生データと今回の生データのテキストが同じか（生データの SHA-256 は Cloudflare のスクリプトで変わる）
    p = THEIR_WEB_RAW["kyoukai_faq_dependent"]
    if p.exists():
        mine = html_to_text((ROOT / web["html_dir"] / "kyoukai_faq_dependent.bin").read_bytes())
        theirs = html_to_text(p.read_bytes())
        res["kyoukai_text_same"] = norm(mine) == norm(theirs)
    (OUT / "docs_check.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for k in ("MS2.1", "LW0"):
        print(k, sum(1 for r in res[k] if r["ok"]), "/", len(res[k]))
    print("MS2.2", sum(1 for r in res["MS2.2"] if r["refetched"] and r["last_modified_ok"] and r["bytes_ok"] and r["text_sha_ok"]), "/",
          sum(1 for r in res["MS2.2"] if r["refetched"]), "(refetched)", "not refetched:", [r["id"] for r in res["MS2.2"] if not r["refetched"]],
          "raw sha differs:", [r["id"] for r in res["MS2.2"] if r["refetched"] and not r["sha_same_as_my_fetch"]],
          "naive text sha differs:", [r["id"] for r in res["MS2.2"] if r["text_sha_in_doc"] != r["their_text_sha_naive"]])
    print("GD0", [(r.get("id"), r["ok"]) for r in res["GD0"]])
    print("refs", res["refs"])
    print("kyoukai_text_same", res["kyoukai_text_same"])
    for k in ("MS2.1", "LW0"):
        for r in res[k]:
            if not r["ok"]:
                print("NG", k, r)
    for r in res["MS2.2"]:
        if r["refetched"] and not (r["last_modified_ok"] and r["bytes_ok"] and r["text_sha_ok"]):
            print("NG MS2.2", r)


# ---------------------------------------------------------------- 算術（推測・仮説の数値）

def add_years(b, n):
    """b の n 年後の応当日。応当日がない（2月29日）ときはその月の末日（民法143条の考え方）。"""
    try:
        return b.replace(year=b.year + n)
    except ValueError:
        return b.replace(year=b.year + n, day=28)


def age_end_of_day(b, d):
    """年齢計算ニ関スル法律・民法143条：満 n 歳になるのは、n 年後の応当日の前日が終わる時。d の日の終了時の年齢。"""
    n = 0
    while add_years(b, n + 1) - dt.timedelta(days=1) <= d:
        n += 1
    return n


def run_calc():
    D = dt.date
    res = []

    def chk(cid, where, got, want):
        res.append({"id": cid, "where": where, "got": got, "want": want, "ok": got == want})
    # 和暦の確認（昭和元年＝1926年）
    chk("wareki-S31", "LW§1.2・GD§2.1", 1925 + 31, 1956)
    chk("wareki-S32", "LW§1.2・GD§2.1", 1925 + 32, 1957)
    # IE1
    chk("IE1a", "IE1", age_end_of_day(D(1956, 1, 1), D(2025, 12, 31)), 70)
    chk("IE1b", "IE1", age_end_of_day(D(1956, 1, 2), D(2025, 12, 31)), 69)
    chk("IE1c", "IE1", age_end_of_day(D(1957, 1, 1), D(2026, 12, 31)), 70)
    chk("IE1d", "IE1", age_end_of_day(D(1957, 1, 2), D(2026, 12, 31)), 69)
    chk("IE1e", "IE1", age_end_of_day(D(1950, 5, 5), D(2026, 7, 1)), 76)
    # 70歳の境目を二分探索で求め、生年月日の範囲（昭和31年1月1日以前／昭和32年1月1日以前）を導く
    for year, want in ((2025, D(1956, 1, 1)), (2026, D(1957, 1, 1))):
        lo, hi = D(1900, 1, 1), D(year, 12, 31)
        while (hi - lo).days > 1:
            mid = lo + (hi - lo) / 2
            if age_end_of_day(mid, D(year, 12, 31)) >= 70:
                lo = mid
            else:
                hi = mid
        chk(f"range70-{year}", "LW§1.2・IE1", lo, want)
    # IE2
    chk("IE2a", "IE2", (480000, 380000, 480000 - 380000), (480000, 380000, 100000))
    chk("IE2b", "IE2", (480000 + 100000, 450000, 480000 + 100000 - 450000), (580000, 450000, 130000))
    chk("IE2d", "IE2", (380000, 330000, 380000 - 330000), (380000, 330000, 50000))
    chk("IE2e", "IE2", 620001 <= 620000, False)
    # IE5（令和8年分の目安：公的年金等の収入 172万円以下で合計所得 62万円以下）
    chk("IE5", "IE5", 1700000 <= 1720000, True)
    # IE6
    chk("IE6b", "IE6", (1700000 < 1800000, 1700000 < 1800000), (True, True))
    chk("IE6c", "IE6", 1700000 < 1600000, False)
    chk("IE6d", "IE6", (1700000 < 1800000, 1700000 < 3000000 / 2, 3000000 / 2), (True, False, 1500000.0))
    # IE8（38万円の判定）
    chk("IE8a", "IE8", 2520 * 15050 // 100, 379260)
    chk("IE8b", "IE8", 2520 * 151, 380520)
    chk("IE8c", "IE8", 375000 + 5000, 380000)
    chk("IE8f", "IE8", 50000 + 340000, 390000)
    # IE8 の端数の例：2,521.37 USD × 150.73（整数の演算で正確に）
    prod = 252137 * 15073   # 単位：1/10000 円
    floor_ = prod // 10000
    round_ = (prod + 5000) // 10000
    ceil_ = -(-prod // 10000)
    res.append({"id": "IE8-frac-example", "where": "IE8", "got": {"exact": f"{prod / 10000:.4f}", "floor": floor_, "round_half_up": round_, "ceil": ceil_},
                "want": "文書：切り捨て・四捨五入で 1円違う", "ok": floor_ != round_})
    # 38万円の境目をまたぐ例を探す（USD 2,5xx.xx × 仲値 150.00〜151.99：切り捨てなら 38万円未満、四捨五入なら 38万円以上）
    found = None
    for rate in range(15000, 15200):
        # prod/10000 が [379999.5, 380000) に入る金額（セント）
        lo_c = -(-3799995000 // rate)
        hi_c = (3800000000 - 1) // rate
        if lo_c <= hi_c:
            cents = lo_c
            p = cents * rate
            found = {"usd": f"{cents / 100:.2f}", "rate": f"{rate / 100:.2f}", "exact": f"{p / 10000:.4f}", "floor": p // 10000, "round_half_up": (p + 5000) // 10000}
            break
    res.append({"id": "IE8-boundary-example", "where": "IE8（訂正の材料）", "got": found, "want": "floor<380000<=round", "ok": found is not None})
    # IE12
    chk("IE12a-age-at-judge", "IE12", age_end_of_day(D(1966, 11, 20), D(2026, 6, 1)), 59)
    chk("IE12a-age-at-1231", "IE12", age_end_of_day(D(1966, 11, 20), D(2026, 12, 31)), 60)
    chk("IE12d-age-at-judge", "IE12", age_end_of_day(D(1966, 5, 1), D(2026, 6, 1)), 60)
    chk("IE12a", "IE12", (1500000 < 1300000, 1500000 < 1800000), (False, True))
    chk("IE12b", "IE12", (1200000 < 1300000, 1200000 < 1800000), (True, True))
    chk("IE12c", "IE12", (1900000 < 1300000, 1900000 < 1800000), (False, False))
    # IE7・IE9・IE11・IE15 の区分と額
    chk("IE7-age72-kubun1", "IE7", 72 >= 70, True)
    chk("IE9-age31-kubun2or4", "IE9", 30 <= 31 < 70, True)
    chk("IE11-age20-tokutei", "IE11", 19 <= 20 < 23, True)
    chk("IE15-age75-roujin", "IE15", 75 >= 70, True)
    (OUT / "calc.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    md = ["| ID | 文書の箇所 | 計算の結果 | 文書の値 | 一致 |", "|---|---|---|---|---|"]
    md += [f"| {r['id']} | {r['where']} | {json.dumps(r['got'], ensure_ascii=False, default=str)} | {json.dumps(r['want'], ensure_ascii=False, default=str)} | {r['ok']} |" for r in res]
    (OUT / "calc.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


EXTRA_COMMANDS = {"check-web": run_check_web, "check-egov": run_check_egov, "check-docs": run_check_docs, "calc": run_calc}


# ---------------------------------------------------------------- main

def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")
    cmds = {"fetch-egov": run_fetch_egov, "fetch-egov2": run_fetch_egov2, "fetch-web": run_fetch_web}
    extra = globals().get("EXTRA_COMMANDS", {})
    cmds.update(extra)
    if not argv or argv[0] not in cmds:
        print("usage:", " | ".join(cmds))
        return 2
    cmds[argv[0]]()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

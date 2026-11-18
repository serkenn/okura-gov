"""IMPL_kenpo_verify: 健康保険の被扶養者認定の実務（IMPL_kenpo）の文書に書かれた数値・番号・日付・URL・条番号を、
一次情報に当たり直して独立に検証する（反証役）。

実行（どれも python -I -X utf8 で）:
  scripts/IMPL_kenpo_verify.py fetch <set> [<set> ...]   一次情報（HTML/PDF/画像）を取得し、取得記録を残す
  scripts/IMPL_kenpo_verify.py fetch --list               セットの一覧
  scripts/IMPL_kenpo_verify.py egov [<略称> ...]          e-Gov 法令API v2 で条文を時点別に取得し、条を抜き出す（略称で絞れる）
  scripts/IMPL_kenpo_verify.py suppl <略称> <asof> <改正法令番号|原始附則> [<語句>]
                                                          取得済みの e-Gov JSON から附則を抜き出す（語句を含む条だけ）
  scripts/IMPL_kenpo_verify.py check                      取得した本文に、文書が引用した語句があるかを照合し、
                                                          版・SHA-256・走査の件数を比べ、境目の計算をやり直す

2026-11-09 に実行した順：fetch mhlw_tdoc mhlw_search mhlw_pdf → fetch nenkin kyokai other nta mhlw_img → egov
→ fetch extra → fetch extra2 → suppl kenpo 2026-11-09 令和七年六月二〇日法律第七四号 施行
→ suppl kenpo 2026-11-09 原始附則 八万八千円 → suppl kenpo 2026-04-01 原始附則 八万八千円 → egov kokuho rouki → check
（check は .work/text/20261109-133945_R3_extra/ と .work/text/20261109-145500_IMPL_kenpo_kyokai/ の既存の抽出テキストも読む）

- 取得したファイルは信頼できないデータとして、取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_kenpo_verify_<set>/ に置く（その中でインタプリタやツールを実行しない）。
  HTML から抽出したテキストは別の新しいディレクトリ .work/text/<ts>_kenpo_verify_<set>/ に置く。
- 出力は scripts/results/IMPL_kenpo_verify/ に書く。
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。個人の情報は送らない。官報は取得しない。
- 標準ライブラリのみ（Python 3.11）。scripts/R3_fetch.py・scripts/R1_egov_articles.py・scripts/R4_fetch_laws.py の
  コードを写して作った（import はしていない）。
"""
import datetime
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
WAIT = 1.5
API = "https://laws.e-gov.go.jp/api/2"
OUT = ROOT / "scripts" / "results" / "IMPL_kenpo_verify"


def mhlw_date_search(gengo, y, m, d, y2=None, m2=None, d2=None):
    """厚労省 法令等データベース 通知の情報詳細検索（日付指定、GET）。gengo: 3=昭和 4=平成 5=令和。"""
    y2, m2, d2 = y2 or y, m2 or m, d2 or d
    return ("https://www.mhlw.go.jp/web/t_itemsrch_result?type=1"
            f"&startGengo={gengo}&yearFrom={y}&monthFrom={m}&dayFrom={d}"
            f"&endGengo={gengo}&yearTo={y2}&monthTo={m2}&dayTo={d2}&shubetsu=&bango=")


def tdoc(data_id):
    return f"https://www.mhlw.go.jp/web/t_doc?dataId={data_id}&dataType=1&pageNo=1"


SETS = {
    "mhlw_tdoc": {
        "S52": tdoc("00tb0189"),
        "R7QA19": tdoc("00tc9628"),
        "R7_19_23_a": tdoc("00tc9249"),
        "R3FUFU": tdoc("00tc5892"),
        "H30A": tdoc("00tc3621"),
        "H30A_kikou": tdoc("00tc3625"),
        "H30QA_H": tdoc("00tc3622"),
        "H30QA_N": tdoc("00tc3627"),
        "R01": tdoc("00tc4995"),
        "R05": tdoc("00tc7769"),
        "R8QA2": tdoc("00tc9817"),
        "R7_rodo": tdoc("00tc9348"),
        "R7_rodo_qa": tdoc("00tc9349"),
    },
    "mhlw_search": {
        "srch_R030430": mhlw_date_search(5, 3, 4, 30),
        "srch_S600613": mhlw_date_search(3, 60, 6, 13),
        "srch_H300829": mhlw_date_search(4, 30, 8, 29),
        "srch_R011113": mhlw_date_search(5, 1, 11, 13),
        "srch_R050619": mhlw_date_search(5, 5, 6, 19),
        "srch_R080309_0310": mhlw_date_search(5, 8, 3, 9, 8, 3, 10),
        "srch_R080301_0331": mhlw_date_search(5, 8, 3, 1, 8, 3, 31),
    },
    "mhlw_img": {**{f"img{i}": f"https://www.mhlw.go.jp/web/t_img?img={8023729 + i}" for i in range(1, 10)},
                 **{f"res{i}": f"https://www.mhlw.go.jp/web/t_img_res?img={8023729 + i}" for i in range(1, 10)}},
    "mhlw_pdf": {
        "content_001678029": "https://www.mhlw.go.jp/content/001678029.pdf",
    },
    "nenkin": {
        "N_TET": "https://www.nenkin.go.jp/service/kounen/tekiyo/hihokensha1/20141202.html",
        "N_HEN": "https://www.nenkin.go.jp/service/kounen/info/jireishokai/henreifuyou.html",
        "N_0819": "https://www.nenkin.go.jp/oshirase/taisetu/2025/202508/0819.html",
        "N_FAQ": "https://www.nenkin.go.jp/section/faq/kounen/dependents/aged19to22/timing.html",
        "N_0501": "https://www.nenkin.go.jp/oshirase/taisetu/jigyosho/2026/202605/0501.html",
    },
    "kyokai": {
        "K_FAQ": "https://www.kyoukaikenpo.or.jp/faq/dependent_status/",
        "K_SEN": "https://www.kyoukaikenpo.or.jp/senpo/about/outline/glossary/004/index.html",
        "K_TOK": "https://www.kyoukaikenpo.or.jp/about/business/public_relations/004/index.html",
        "JQA": "https://www.kyoukaikenpo.or.jp/assets/001159347.pdf",
        "K_LEAF": "https://www.kyoukaikenpo.or.jp/assets/dependent_status_r8leaf.pdf",
    },
    "other": {
        "ITS": "https://www.its-kenpo.or.jp/NEWS/hoken/20260327_2.html",
        "soumu_gaiyou": "https://www.soumu.go.jp/main_sosiki/jichi_gyousei/daityo/gaiyou.html",
        "YORYO": "https://www.soumu.go.jp/main_content/001094645.pdf",
    },
    "nta": {
        "TA1180": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1180.htm",
        "TA1177": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1177.htm",
    },
    # 追加：JQA の発出元の確認（厚労省「年収の壁・支援強化パッケージ」ページ）、令和8年分の給与収入換算（年末調整のしかた）
    "extra": {
        "mhlw_taiou": "https://www.mhlw.go.jp/stf/taiou_001_00002.html",
        "nencho2026_102": "https://www.nta.go.jp/publication/pamph/gensen/nencho2026/pdf/102.pdf",
        "R5_1020_kenpo": tdoc("00tc8005"),
    },
    # 厚労省ページ（mhlw_taiou）からリンクされた「事業主の証明に依る被扶養者認定に関するQ&A」（JQA と同じものかを確かめる）
    "extra2": {
        "mhlw_jqa_001678016": "https://www.mhlw.go.jp/content/001678016.pdf",
    },
}


# ---------------------------------------------------------------- HTML のテキスト化（R3_fetch.py から写した）
class Extract(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.links, self.title = [], [], ""
        self._skip = 0
        self._in_title = False
        self._href = None
        self._atext = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "img" and a.get("alt") and not self._skip:
            self.parts.append("⟨" + a["alt"] + "⟩")
        if tag == "a" and a.get("href"):
            self._href = a["href"]
            self._atext = []
        if tag in ("br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "dt", "dd", "table"):
            self.parts.append("\n")
        if tag in ("td", "th"):
            self.parts.append(" | ")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False
        if tag == "a" and self._href is not None:
            self.links.append({"href": self._href, "text": " ".join("".join(self._atext).split())})
            self._href = None
        if tag in ("p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "dd"):
            self.parts.append("\n")

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.title += data
        if self._href is not None:
            self._atext.append(data)
        self.parts.append(data)

    def text(self):
        t = "".join(self.parts)
        t = re.sub(r"[ \t　]+\n", "\n", t)
        t = re.sub(r"\n{3,}", "\n\n", t)
        return t.strip()


def read_with_deadline(resp, seconds=90):
    deadline = time.monotonic() + seconds
    chunks = []
    while True:
        b = resp.read(65536)
        if not b:
            break
        chunks.append(b)
        if time.monotonic() > deadline:
            raise TimeoutError(f"body read exceeded {seconds}s")
    return b"".join(chunks)


def decode(body, ctype):
    cs = None
    m = re.search(r"charset=([\w\-]+)", ctype or "", re.I)
    if m:
        cs = m.group(1)
    if not cs:
        m = re.search(rb"<meta[^>]+charset=[\"']?([\w\-]+)", body[:4000], re.I)
        if m:
            cs = m.group(1).decode("ascii", "replace")
    for c in [cs, "utf-8", "cp932", "euc-jp"]:
        if not c:
            continue
        try:
            return body.decode(c), c
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", "replace"), "utf-8(replace)"


def http_get(url, accept=None, timeout=60):
    h = {"User-Agent": UA, "Accept-Language": "ja"}
    if accept:
        h["Accept"] = accept
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.geturl(), dict(r.headers), read_with_deadline(r)
    except urllib.error.HTTPError as e:
        return e.code, url, dict(e.headers or {}), e.read() if hasattr(e, "read") else b""


def ext_for(ctype, url):
    c = (ctype or "").lower()
    if "pdf" in c or url.lower().endswith(".pdf"):
        return ".pdf"
    for img in ("png", "gif", "jpeg", "jpg"):
        if f"image/{img}" in c:
            return "." + ("jpg" if img == "jpeg" else img)
    if "json" in c:
        return ".json"
    if "html" in c:
        return ".html"
    return ".bin"


def run_set(name, urls, ts):
    dl = ROOT / ".work" / "downloads" / f"{ts}_kenpo_verify_{name}"
    dl.mkdir(parents=True, exist_ok=False)
    tx = ROOT / ".work" / "text" / f"{ts}_kenpo_verify_{name}"
    tx.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    log = []
    for i, (sid, url) in enumerate(urls.items()):
        if i:
            time.sleep(WAIT)
        rec = {"id": sid, "url": url}
        try:
            st, final, hdr, body = http_get(url)
            ctype = hdr.get("Content-Type", "")
            ext = ext_for(ctype, final)
            (dl / f"{sid}{ext}").write_bytes(body)
            rec.update({"status": st, "final_url": final, "content_type": ctype, "bytes": len(body),
                        "sha256": hashlib.sha256(body).hexdigest(), "last_modified": hdr.get("Last-Modified"),
                        "saved": str((dl / f"{sid}{ext}").relative_to(ROOT))})
            if ext == ".html" and body:
                s, cs = decode(body, ctype)
                p = Extract()
                p.feed(s)
                (tx / f"{sid}.txt").write_text(p.text(), encoding="utf-8")
                links = [{"href": urllib.parse.urljoin(final, lk["href"]), "text": lk["text"]} for lk in p.links
                         if lk["href"] and not lk["href"].startswith(("javascript:", "mailto:", "#"))]
                (tx / f"{sid}.links.json").write_text(json.dumps(links, ensure_ascii=False, indent=1), encoding="utf-8")
                rec.update({"charset": cs, "title": " ".join(p.title.split()), "text_chars": len(p.text()),
                            "text": str((tx / f"{sid}.txt").relative_to(ROOT))})
        except Exception as e:  # noqa: BLE001
            rec["error"] = repr(e)
        log.append(rec)
        (OUT / f"fetch_{name}_{ts}.json").write_text(
            json.dumps({"set": name, "fetched_at_local": ts, "user_agent": UA, "results": log}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        print(json.dumps({k: rec.get(k) for k in ("id", "status", "bytes", "last_modified", "title", "error")}, ensure_ascii=False), flush=True)


# ---------------------------------------------------------------- e-Gov（R1_egov_articles.py・R4_fetch_laws.py から写した）
EGOV_JOBS = [
    # (略称, law_id, [asof...], [条（Num 属性）])
    ("kenpo", "211AC0000000070", ["2025-10-01", "2025-12-31", "2026-04-01", "2026-11-09"], ["3", "43_2"]),
    ("kenpo-rei", "215IO0000000243", ["2026-11-09"], []),
    ("kenpo-ki", "215M10000008036", ["2025-10-01", "2025-12-31", "2026-04-01", "2026-11-09"], ["37_3", "38", "50"]),
    ("jumin", "342AC0000000081", ["2026-11-09"], ["4", "6", "7", "25"]),
    ("kokuho", "333AC0000000192", ["2026-11-09"], ["6", "19"]),
    ("minpo", "129AC0000000089", ["2026-11-09"], ["143"]),
    ("nenrei", "135AC1000000050", ["2026-11-09"], ["__ALL__"]),
    ("shotoku", "340AC0000000033", ["2026-11-09", "2026-12-01"], ["84_2"]),
    ("rouki", "322AC0000000049", ["2026-11-09"], ["11", "15"]),
]


def text_of(node):
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ""
    if node.get("tag") == "Rt":
        return ""
    return "".join(text_of(c) for c in node.get("children", []))


def child(node, tag):
    for c in node.get("children", []):
        if isinstance(c, dict) and c.get("tag") == tag:
            return c
    return None


def iter_tag(node, tag):
    if isinstance(node, dict):
        if node.get("tag") == tag:
            yield node
        for c in node.get("children", []):
            yield from iter_tag(c, tag)


def render(node, depth=0, out=None):
    if out is None:
        out = []
    if not isinstance(node, dict):
        return out
    tag = node.get("tag", "")
    ind = "  " * depth
    if tag == "Article":
        cap = child(node, "ArticleCaption")
        tit = child(node, "ArticleTitle")
        out.append(f"{ind}{text_of(cap) if cap else ''}")
        out.append(f"{ind}{text_of(tit) if tit else ''}")
        for c in node.get("children", []):
            if isinstance(c, dict) and c.get("tag") == "Paragraph":
                render(c, depth, out)
        return out
    if tag == "Paragraph":
        num = child(node, "ParagraphNum")
        sen = child(node, "ParagraphSentence")
        out.append(f"{ind}[項{node.get('attr', {}).get('Num', '')}] {text_of(num) if num else ''} {text_of(sen) if sen else ''}".rstrip())
        for c in node.get("children", []):
            if isinstance(c, dict) and c.get("tag") not in ("ParagraphNum", "ParagraphSentence", "ParagraphCaption"):
                render(c, depth + 1, out)
        return out
    m = re.fullmatch(r"(Item|Subitem\d+)", tag)
    if m:
        t = child(node, f"{tag}Title")
        s = child(node, f"{tag}Sentence")
        sent = ""
        if s:
            parts = [text_of(c) for c in s.get("children", []) if isinstance(c, (dict, str))]
            sent = "　".join(p for p in parts if p)
        out.append(f"{ind}{text_of(t) if t else ''} {sent}".rstrip())
        for c in node.get("children", []):
            if isinstance(c, dict) and c.get("tag") not in (f"{tag}Title", f"{tag}Sentence"):
                render(c, depth + 1, out)
        return out
    for c in node.get("children", []):
        render(c, depth, out)
    return out


def egov(only=None):
    """only: 取得する略称の集合（None なら EGOV_JOBS のすべて）。"""
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_kenpo_verify_egov"
    dl.mkdir(parents=True, exist_ok=False)
    art_dir = OUT / "egov_articles"
    art_dir.mkdir(parents=True, exist_ok=True)
    log = {"fetched_at_local": ts, "download_dir": str(dl.relative_to(ROOT)), "fetches": []}
    first = True
    for short, law_id, asofs, arts in EGOV_JOBS:
        if only and short not in only:
            continue
        for asof in asofs:
            if not first:
                time.sleep(WAIT)
            first = False
            q = urllib.parse.urlencode({"response_format": "json", "asof": asof})
            url = f"{API}/law_data/{law_id}?{q}"
            st, final, hdr, body = http_get(url, accept="application/json", timeout=300)
            (dl / f"{short}_{asof}.json").write_bytes(body)
            rec = {"short": short, "law_id": law_id, "asof": asof, "url": url, "status": st, "bytes": len(body),
                   "sha256": hashlib.sha256(body).hexdigest()}
            if st != 200:
                rec["error"] = body[:300].decode("utf-8", "replace")
                log["fetches"].append(rec)
                print("ERR", short, asof, st, flush=True)
                continue
            d = json.loads(body)
            ri = d.get("revision_info") or {}
            li = d.get("law_info") or {}
            rec.update({k: ri.get(k) for k in ("law_revision_id", "law_title", "amendment_law_num", "amendment_law_title",
                                               "amendment_enforcement_date", "current_revision_status", "updated")})
            rec["law_num"] = li.get("law_num")
            log["fetches"].append(rec)
            full = d["law_full_text"]
            mp = next(iter_tag(full, "MainProvision"), None)
            lines = [f"# {ri.get('law_title')} {law_id} asof={asof}",
                     f"# law_revision_id={ri.get('law_revision_id')} 改正法令={ri.get('amendment_law_num')} "
                     f"施行日={ri.get('amendment_enforcement_date')} 状態={ri.get('current_revision_status')}",
                     f"# 取得URL={url}", f"# 取得日時={ts}", ""]
            if arts == ["__ALL__"]:
                lines += render(mp) if mp else []
            else:
                by_num = {a.get("attr", {}).get("Num"): a for a in (iter_tag(mp, "Article") if mp else [])}
                for num in arts:
                    a = by_num.get(num)
                    if a is None:
                        lines += [f"## Num={num}: 見つからない", ""]
                        continue
                    lines.append(f"## Num={num}")
                    lines += render(a)
                    lines.append("")
            (art_dir / f"{short}_{asof}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
            # 附則の改正法令の一覧（どの改正法令の附則が収録されているか）
            supl = [sp.get("attr", {}).get("AmendLawNum") or "原始附則" for sp in iter_tag(full, "SupplProvision")]
            (art_dir / f"{short}_{asof}_suppl_list.json").write_text(json.dumps(supl, ensure_ascii=False, indent=0), encoding="utf-8")
            print("ok", short, asof, ri.get("law_revision_id"), ri.get("amendment_enforcement_date"), flush=True)
    (OUT / f"egov_fetch_log_{ts}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


def egov_json_dir(short, asof):
    """<略称>_<asof>.json を含む最新の .work/downloads/*_kenpo_verify_egov/ を返す。"""
    for d in sorted((ROOT / ".work" / "downloads").glob("*_kenpo_verify_egov"), reverse=True):
        if (d / f"{short}_{asof}.json").exists():
            return d
    raise FileNotFoundError(f"{short}_{asof}.json")


# ---------------------------------------------------------------- 照合と再計算
def norm(s):
    s = unicodedata.normalize("NFKC", s)
    return re.sub(r"\s+", "", s)


def latest_text_dir(set_name):
    ds = sorted((ROOT / ".work" / "text").glob(f"*_kenpo_verify_{set_name}"))
    return ds[-1] if ds else None


def load_text(set_name, sid):
    d = latest_text_dir(set_name)
    if not d:
        return None
    p = d / f"{sid}.txt"
    return p.read_text(encoding="utf-8") if p.exists() else None


def load_egov(short, asof):
    p = OUT / "egov_articles" / f"{short}_{asof}.txt"
    return p.read_text(encoding="utf-8") if p.exists() else None


# 文書（IMPL_kenpo の4文書）が引用・依拠した語句が、再取得した一次情報の本文にあるか。
# (項目, 種類 web|egov, セット or 略称, id or asof, 語句)。照合は NFKC 正規化と空白除去のうえで部分一致。
W, E = "web", "egov"
PHRASES = [
    # S52（昭和52年通知）
    ("PS§0 S52 番号", W, "mhlw_tdoc", "S52", "(保発第九号・庁保発第九号)"),
    ("PS§0 S52 発出者・宛先", W, "mhlw_tdoc", "S52", "各道府県知事あて厚生省保険局長・社会保険庁医療保険部長通知"),
    ("PS§0 S52 記4", W, "mhlw_tdoc", "S52", "今後の被扶養者の認定について行うものとすること"),
    ("PS§1.3 S52 保険者の取扱い", W, "mhlw_tdoc", "S52", "保険者が行う取扱い"),
    ("PS§1.3 S52 参考として", W, "mhlw_tdoc", "S52", "左記要領を参考として"),
    ("PS§2.3 S52 同一世帯", W, "mhlw_tdoc", "S52", "被保険者と同一世帯に属している場合"),
    ("PS§2.3 S52 援助", W, "mhlw_tdoc", "S52", "被保険者からの援助に依る収入額より少ない場合"),
    ("PS§8 S52 記3", W, "mhlw_tdoc", "S52", "最も妥当と認められる認定を行うものとすること"),
    # R7QA19
    ("PS§0 R7QA19 宛先（機構）", W, "mhlw_tdoc", "R7QA19", "日本年金機構事業管理部門あて厚生労働省保険局保険課・厚生労働省年金局事業管理課通知"),
    ("PS§0 R7QA19 宛先（協会・組合）", W, "mhlw_tdoc", "R7QA19", "全国健康保険協会・健康保険組合あて厚生労働省保険局保険課通知"),
    ("PS§0 R7QA19 Q7 引用先 Q24", W, "mhlw_tdoc", "R7QA19", "の別紙Q24を参照のこと"),
    ("PS§0 R7QA19 Q7 引用先 Q19", W, "mhlw_tdoc", "R7QA19", "の別紙Q19を参照のこと"),
    ("PS§1.1 R7QA19 Q5", W, "mhlw_tdoc", "R7QA19", "今後1年間の収入を見込むこととなる"),
    ("PS§5.5 R7QA19 Q4 12月31日", W, "mhlw_tdoc", "R7QA19", "その年の12月31日現在の年齢で判定する"),
    ("PS§5.5 R7QA19 Q4 例", W, "mhlw_tdoc", "R7QA19", "N年10月に19歳の誕生日を迎える場合には、N年(暦年)における年間収入要件は150万円未満となる"),
    ("PS§5.5 R7QA19 Q4 1月1日", W, "mhlw_tdoc", "R7QA19", "誕生日が1月1日である者は12月31日において年齢が加算される"),
    ("PS§5.5 R7QA19 Q6", W, "mhlw_tdoc", "R7QA19", "12月31日現在の年齢が22歳である年(暦年)の翌年においては年間収入130万円未満"),
    ("PS§5.1 R7QA19 Q8", W, "mhlw_tdoc", "R7QA19", "令和7年10月1日より前に遡って認定する場合の19歳以上23歳未満の被扶養者の認定対象者の年間収入の要件は130万円未満"),
    ("PS§0 R7 局長通知 適用日", W, "mhlw_tdoc", "R7_19_23_a", "令和7年10月1日から適用"),
    # R3FUFU
    ("PS§0 R3FUFU 番号1", W, "mhlw_tdoc", "R3FUFU", "保保発0430第2号"),
    ("PS§0 R3FUFU 番号2", W, "mhlw_tdoc", "R3FUFU", "保国発0430第1号"),
    ("PS§0 R3FUFU 適用日", W, "mhlw_tdoc", "R3FUFU", "令和3年8月1日から適用する"),
    ("PS§0 R3FUFU 昭和60年通知", W, "mhlw_tdoc", "R3FUFU", "昭和60年6月13日付け保険発第66号・庁保険発第22号通知"),
    ("PS§0 R3FUFU 廃止", W, "mhlw_tdoc", "R3FUFU", "本通知をもって昭和60年通知は廃止する"),
    ("PS§3 附帯決議", W, "mhlw_tdoc", "R3FUFU", "令和元年法律第9号)に対する附帯決議"),
    ("PS§3 1(1) 員数", W, "mhlw_tdoc", "R3FUFU", "被扶養者とすべき者の員数にかかわらず"),
    ("PS§3 1(2) 1割", W, "mhlw_tdoc", "R3FUFU", "年間収入の差額が年間収入の多い方の1割以内である場合"),
    ("PS§3 1(5) 5日", W, "mhlw_tdoc", "R3FUFU", "届出を受理した日より5日以内(書類不備の是正を求める期間及び土日祝日を除く。)"),
    ("PS§3 1(5) 標準報酬", W, "mhlw_tdoc", "R3FUFU", "届出が提出された日の属する月の標準報酬月額が高い方の被扶養者とする"),
    ("PS§3 2(1) 国保", W, "mhlw_tdoc", "R3FUFU", "直近の年間所得で見込んだ年間収入"),
    ("PS§3 2(3) 課税証明", W, "mhlw_tdoc", "R3FUFU", "直近の課税(非課税)証明書の所得金額が多い方"),
    ("PS§3 3 育休", W, "mhlw_tdoc", "R3FUFU", "第43条の2に定める育児休業等を取得した場合"),
    ("PS§3 4 逆転", W, "mhlw_tdoc", "R3FUFU", "年間収入が多くなった被保険者の方の保険者等が認定することを確認してから削除"),
]
PHRASES += [
    # H30A / H30QA
    ("PS§0 H30A 第1号", W, "mhlw_tdoc", "H30A", "(保保発0829第1号)"),
    ("PS§0 H30A 第2号", W, "mhlw_tdoc", "H30A", "(保保発0829第2号)"),
    ("PS§0 H30A 適用日", W, "mhlw_tdoc", "H30A", "平成30年10月1日から適用"),
    ("PS§2.3 H30A 記2(2)", W, "mhlw_tdoc", "H30A", "同一世帯であることを確認できる公的証明書等の添付を求める"),
    ("PS§2.3 H30A 記2(3)", W, "mhlw_tdoc", "H30A", "仕送りが振込の場合は預金通帳等の写し"),
    ("PS§0 H30A 機構あて番号", W, "mhlw_tdoc", "H30A_kikou", "(年管管発0829第4号)"),
    ("PS§1.1 H30QA-H Q13", W, "mhlw_tdoc", "H30QA_H", "国内認定対象者の過去の収入、現時点の収入又は将来の収入の見込みなどから、今後1年間の収入を見込むものとする"),
    ("PS§6 H30QA-H Q12 給与", W, "mhlw_tdoc", "H30QA_H", "勤務先から発行された収入証明書"),
    ("PS§6 H30QA-H Q12 自営", W, "mhlw_tdoc", "H30QA_H", "自営業による収入、不動産収入等がある場合"),
    ("PS§2.3 H30QA-H Q15", W, "mhlw_tdoc", "H30QA_H", "民生委員による証明書の添付でも差し支えない"),
    ("PS§5.1 H30QA-H Q16 初回", W, "mhlw_tdoc", "H30QA_H", "初回の仕送りがなされた時点で"),
    ("PS§5.2 H30QA-H Q16 遡って削除", W, "mhlw_tdoc", "H30QA_H", "当該事実が確認できなくなった時点に遡って削除するものとする"),
    ("PS§6 H30QA-H Q17", W, "mhlw_tdoc", "H30QA_H", "16歳未満の子である場合は、収入を確認するための書類は要さない"),
    ("PS§6 H30QA-H Q18", W, "mhlw_tdoc", "H30QA_H", "国内認定対象者が学生の場合は、送金事実と仕送り額を確認するための書類を省略して差し支えない"),
    ("PS§5.3 H30QA-H Q19 年1回", W, "mhlw_tdoc", "H30QA_H", "認定後、少なくとも年1回は保険者において被扶養者に係る確認を行い"),
    ("PS§5.2 H30QA-H Q19 ①", W, "mhlw_tdoc", "H30QA_H", "保険者において事前に定めた日)以降で、被扶養者を削除する届出を提出させること"),
    ("PS§5.2 H30QA-H Q19 ②", W, "mhlw_tdoc", "H30QA_H", "認定時に遡って取り消すこととなる"),
    ("PS§1.3 H30QA-N Q3", W, "mhlw_tdoc", "H30QA_N", "保険者等の判断により、判断基準を追加や緩和することは認められない"),
    ("PS§1.3 H30QA-H に同旨なし", W, "mhlw_tdoc", "H30QA_H", "判断基準を追加や緩和することは認められない"),  # 期待：なし
    ("PS§1.3 H30QA-N Q5", W, "mhlw_tdoc", "H30QA_N", "厚生労働省から認定の見直し及び通知に基づく事務の徹底について指導を行う"),
    ("PS§1.4 H30QA-N Q13", W, "mhlw_tdoc", "H30QA_N", "「事業主確認欄」の「確認」部分を○で囲んで"),
    ("PS§1.1 H30QA-N Q14", W, "mhlw_tdoc", "H30QA_N", "認定対象者の過去の収入、現時点の収入又は将来の収入の見込みなどから、今後1年間の収入を見込むものとする"),
    ("PS§2.3 H30QA-N Q17", W, "mhlw_tdoc", "H30QA_N", "「国内認定対象者の年間収入が被保険者の年間収入の2分の1未満であること」を要件とする対象者であること等を確認するために求める"),
    ("PS§2.3 H30QA-N Q18", W, "mhlw_tdoc", "H30QA_N", "本人確認を行う際に同一世帯であることの確認も行うこととしている"),
    ("PS§2.3 H30QA-N Q19", W, "mhlw_tdoc", "H30QA_N", "民生委員等による同居の証明書の添付でも差し支えない"),
    ("PS§2.3 H30QA-N Q21", W, "mhlw_tdoc", "H30QA_N", "同居はしているものの、世帯を分離している、または、近所に住んでいる等の事情で現金の手渡しや現物(食料、衣料等)を渡すことにて生計維持をしている場合"),
    ("PS§5.1 H30QA-N Q22 遡って", W, "mhlw_tdoc", "H30QA_N", "遡って資格取得日で扶養認定して差し支えない"),
    ("PS§5.2 H30QA-N Q22 見直し", W, "mhlw_tdoc", "H30QA_N", "被扶養者の認定を見直すこととする"),
    ("PS§8 H30QA-N Q23", W, "mhlw_tdoc", "H30QA_N", "仕送りの対象者を複数名である場合は対象者を"),
    # R01 / R05
    ("PS§0 R01 番号", W, "mhlw_tdoc", "R01", "(保保発1113第1号)"),
    ("PS§0 R01 施行", W, "mhlw_tdoc", "R01", "いずれも令和2年4月1日から施行することとされた"),
    ("PS§2.3 R01 第1", W, "mhlw_tdoc", "R01", "住民基本台帳に住民登録されているかどうか(住民票があるかどうか)で判断"),
    ("PS§0 R01 最終改正", W, "mhlw_tdoc", "R05", "最終改正　令和5年6月19日保保発0619第1号"),
    # 労働契約（連名通知・Q&A 第2版の柱書き）
    ("PS§0 R8QA2 発出者・宛先", W, "mhlw_tdoc", "R8QA2", "全国健康保険協会・健康保険組合・日本年金機構あて厚生労働省保険局保険課・厚生労働省年金局事業管理課通知"),
    ("PS§0 R8QA2 第1版から追加・修正", W, "mhlw_tdoc", "R8QA2", "一部QAを追加・修正"),
    ("PS§1.2 連名通知 注1", W, "mhlw_tdoc", "R7_rodo", "(注1)労働基準法第11条に規定される賃金をいい、諸手当及び賞与も含まれる。"),
    ("PS§1.2 連名通知 適用日", W, "mhlw_tdoc", "R7_rodo", "令和8年4月1日から適用すること"),
    # 厚労省 日付検索の件数
    ("MS§1 R030430 7件", W, "mhlw_search", "srch_R030430", "該当件数: 7件"),
    ("MS§1 S600613 0件", W, "mhlw_search", "srch_S600613", "該当件数: 0件"),
    ("MS§1 H300829 8件", W, "mhlw_search", "srch_H300829", "該当件数: 8件"),
    ("MS§1 R011113 4件", W, "mhlw_search", "srch_R011113", "該当件数: 4件"),
    ("MS§1 R050619 3件", W, "mhlw_search", "srch_R050619", "該当件数: 3件"),
    ("MS§1 R080301-0331 176件", W, "mhlw_search", "srch_R080301_0331", "該当件数: 176件"),
    ("MS§1 R080309-0310 3件", W, "mhlw_search", "srch_R080309_0310", "該当件数: 3件"),
    ("MS§1 R080309-0310 Q&A第2版", W, "mhlw_search", "srch_R080309_0310", "Ｑ＆Ａ（第２版）について"),
]
PHRASES += [
    # 日本年金機構
    ("PS§0 N-TET 更新日", W, "nenkin", "N_TET", "更新日：2026年9月30日"),
    ("PS§1.1 N-TET 年間収入", W, "nenkin", "N_TET", "年間収入とは、過去の収入のことではなく、被扶養者に該当する時点および認定された日以降の年間の見込み収入額"),
    ("PS§1.2 N-TET 月額", W, "nenkin", "N_TET", "月額108,333円以下"),
    ("PS§1.2 N-TET 日額", W, "nenkin", "N_TET", "日額3,611円以下"),
    ("PS§1.2 N-TET 基本手当", W, "nenkin", "N_TET", "基本手当（3,612円以上）の支給が始まった場合は、扶養削除の届出が必要"),
    ("PS§1.2 N-TET 含む収入", W, "nenkin", "N_TET", "被扶養者の収入には、雇用保険の失業等給付、公的年金、健康保険の傷病手当金や出産手当金も含まれます"),
    ("PS§1.2 N-TET 非課税収入", W, "nenkin", "N_TET", "障害年金、遺族年金、傷病手当金、出産手当金、失業給付等の非課税対象となる収入がある場合は、別途「受取金額のわかる通知書等のコピー」が必要"),
    ("PS§1.2 N-TET 自営", W, "nenkin", "N_TET", "自営業者についての収入額は、当該事業遂行のための必要経費を控除した額"),
    ("PS§2.3 N-TET 同居不要", W, "nenkin", "N_TET", "被保険者と同居している必要がない者"),
    ("PS§2.3 N-TET 同居必要", W, "nenkin", "N_TET", "被保険者と同居していることが必要な者"),
    ("PS§2.3 N-TET 同居確認", W, "nenkin", "N_TET", "同居の確認は、日本年金機構で行うため、原則、書類の添付は不要ですが、確認できない場合には、住民票の提出を求めることがあります"),
    ("PS§2.3 N-TET 住民票", W, "nenkin", "N_TET", "被保険者が世帯主で、被扶養者と同一世帯である場合に限ります"),
    ("PS§3 N-TET 夫婦", W, "nenkin", "N_TET", "被扶養者の人数にかかわらず、年間収入の多い方の被扶養者として認定"),
    ("PS§3 N-TET 国保", W, "nenkin", "N_TET", "直近の年間所得で見込んだ額を年間収入として記載"),
    ("PS§3 N-TET 育休", W, "nenkin", "N_TET", "当該休業期間中の被扶養者の異動にかかる手続きは不要"),
    ("PS§4.2 N-TET 削除 被保険者", W, "nenkin", "N_TET", "健康保険、船員保険の被保険者または共済組合、国保組合等の組合員になったとき"),
    ("PS§4.2 N-TET 削除 他の被保険者", W, "nenkin", "N_TET", "婚姻等により他の被保険者に扶養されるようになったとき"),
    ("PS§4.2 N-TET 削除 後期", W, "nenkin", "N_TET", "後期高齢者医療制度の被保険者になったとき"),
    ("PS§5.4 N-TET 5日", W, "nenkin", "N_TET", "事実発生から5日以内"),
    ("PS§5.1 N-TET 60日", W, "nenkin", "N_TET", "受付日より60日以上さかのぼる場合"),
    ("PS§1.4 N-TET 所得税", W, "nenkin", "N_TET", "所得税法の規定による控除対象配偶者または扶養親族となっている者"),
    ("PS§1.4 N-TET 1,000万", W, "nenkin", "N_TET", "合計所得金額が1,000万円を超える場合"),
    ("PS§6 N-TET 学生", W, "nenkin", "N_TET", "16歳未満または16歳以上の学生の場合は不要"),
    ("PS§0 N-HEN 更新日", W, "nenkin", "N_HEN", "更新日：2026年10月22日"),
    ("PS§1.4 N-HEN 事業主確認", W, "nenkin", "N_HEN", "所得税法上の控除対象配偶者・扶養親族であることを事業主が確認し、事業主確認欄の「確認」を○（丸印）で囲んでいる場合"),
    ("PS§1.4 N-HEN 16歳未満", W, "nenkin", "N_HEN", "扶養認定を受ける方の年齢が16歳未満の場合"),
    ("検証で追加 N-HEN 源泉徴収票", W, "nenkin", "N_HEN", "よくある誤りとして「源泉徴収票」が添付され提出される場合があります"),
    ("PS§0 N-0819 更新日", W, "nenkin", "N_0819", "更新日：2025年8月19日"),
    ("PS§5.5 N-0819 判定時点", W, "nenkin", "N_0819", "扶養認定日が属する年の12月31日時点の年齢で判定"),
    ("IK1 N-0819 令和7年11月の例", W, "nenkin", "N_0819", "令和7年11月に19歳の誕生日を迎える場合には、令和7年（暦年）における年間収入要件は150万円未満"),
    ("検証で追加 N-0819 認定済みの者", W, "nenkin", "N_0819", "令和7年9月30日以前に扶養認定済みの19歳以上23歳未満の被扶養者については、令和7年10月1日以降は年間収入が150万円以上見込まれる場合に被扶養者の削除"),
    ("PS§0 N-FAQ 更新日", W, "nenkin", "N_FAQ", "更新日：2025年8月19日"),
    ("PS§5.5 N-FAQ 判定時点", W, "nenkin", "N_FAQ", "扶養認定日が属する年の12月31日時点の年齢で判定"),
    ("IK1 N-FAQ の例は N年10月", W, "nenkin", "N_FAQ", "Ｎ年10月に19歳の誕生日を迎える場合"),
    ("IK1 N-FAQ に令和7年11月の例なし", W, "nenkin", "N_FAQ", "令和7年11月"),  # 期待：なし
    ("PS§1.2 機構0501 通勤手当", W, "nenkin", "N_0501", "「通勤手当有」等となっており、手当の金額が不明確な場合"),
]
PHRASES += [
    # 協会けんぽ
    ("PS§5.3 K-FAQ 1 規則50条", W, "kyokai", "K_FAQ", "健康保険法施行規則第50条に基づき"),
    ("PS§0 K-FAQ 9月19日", W, "kyokai", "K_FAQ", "令和8年9月19日現在"),
    ("PS§0 K-FAQ 提出期限", W, "kyokai", "K_FAQ", "令和8年12月11日"),
    ("PS§4.2 K-FAQ 8 重複", W, "kyokai", "K_FAQ", "他の健康保険の資格と重複して加入していないか"),
    ("PS§2.3 K-FAQ 10", W, "kyokai", "K_FAQ", "実態として同居をしていれば同居の扱いとなります"),
    ("IK4 K-FAQ 11", W, "kyokai", "K_FAQ", "被扶養者本人の収入よりも仕送り額が少ないなどの場合は"),
    ("PS§1.2 K-FAQ 15 自営", W, "kyokai", "K_FAQ", "自営業の方の年収は、年間総収入から必要経費を差し引いた額"),
    ("PS§1.2 K-FAQ 15 必要経費", W, "kyokai", "K_FAQ", "社会通念上明らかに当該所得を得るために必要な経費であり、それ以外の費用は差し引くことはできません"),
    ("PS§5.2 K-FAQ 17 3年連続", W, "kyokai", "K_FAQ", "一時的に収入が増加している状態が３年連続している場合は扶養解除の手続きが必要"),
    ("PS§1.2 K-FAQ 17 基本給", W, "kyokai", "K_FAQ", "基本給が上がった場合や恒常的な手当が新設された場合など"),
    ("PS§2.3 K-FAQ 19 別居", W, "kyokai", "K_FAQ", "19：「別居」となります"),
    ("PS§1.2 K-FAQ 20 奨学金", W, "kyokai", "K_FAQ", "貸与型の奨学金は収入に含まれませんが、給付型の奨学金は収入に含まれる場合があります"),
    ("PS§1.2 K-FAQ 23", W, "kyokai", "K_FAQ", "今後１年間の収入を見込んだうえで年収要件に該当するのか確認"),
    ("PS§5.2 K-FAQ 26 資格重複", W, "kyokai", "K_FAQ", "健康保険組合等の資格取得年月日、後期高齢者医療制度の資格取得年月日"),
    ("PS§5.2 K-FAQ 26 別居", W, "kyokai", "K_FAQ", "被保険者と別居した日"),
    ("PS§5.2 K-FAQ 26 収入", W, "kyokai", "K_FAQ", "就職年月日、時給が上がった日、年金額改定年月日など収入が増加した日"),
    ("PS§5.2 K-FAQ 26 申出日", W, "kyokai", "K_FAQ", "日付が不明な場合は、申出日を記入してください"),
    ("PS§5.2 K-FAQ 32", W, "kyokai", "K_FAQ", "協会けんぽが被扶養者資格を総合的に判断"),
    ("PS§1.4 K-FAQ 54", W, "kyokai", "K_FAQ", "所得税法上の扶養要件と健康保険の扶養要件は異なる"),
    ("PS§8 K-FAQ 55", W, "kyokai", "K_FAQ", "18歳未満の被扶養者に関する収入要件の確認は不要"),
    ("PS§2.3 K-SEN 同一の世帯", W, "kyokai", "K_SEN", "「同一の世帯」とは、同居して家計を共にしている状態をいいます"),
    ("PS§2.3 K-SEN 生計維持", W, "kyokai", "K_SEN", "必ずしも被保険者と一緒に生活をしていなくてもかまいません"),
    ("PS§1.2 K-SEN 経費", W, "kyokai", "K_SEN", "収入から控除できる経費は事業所得の金額を計算する場合の必要経費とは異なります"),
    ("PS§1.2 K-SEN 減価償却", W, "kyokai", "K_SEN", "減価償却費（一般所得、農業所得、不動産所得）"),
    ("PS§5.5 K-SEN 12月31日", W, "kyokai", "K_SEN", "19歳以上23歳未満（その年の12月31日時点の年齢）"),
    ("PS§1.2 K-TOK 連続2回", W, "kyokai", "K_TOK", "原則、連続2回まで被扶養者の認定が可能"),
    # その他
    ("PS§1.2 ITS 通勤手当", W, "other", "ITS", "基本給、諸手当、通勤手当、賞与及び固定残業代は年間収入に算入します"),
    ("PS§0 ITS 適用", W, "other", "ITS", "令和8年4月1日からの被扶養者認定における年間収入の取扱い"),
    ("PS§0 YORYO リンク名", W, "other", "soumu_gaiyou", "住民基本台帳事務処理要領（令和8年6月14日施行）"),
    ("HK9 TA1180 58万", W, "nta", "TA1180", "年間の合計所得金額が58万円以下"),
    ("HK9 TA1180 62万", W, "nta", "TA1180", "令和8年12月1日に施行され、令和8年分から適用される金額は「62万円以下」です"),
    ("HK9 TA1177 197万・188万", W, "nta", "TA1177", "給与のみの場合は給与収入が197万円以下（令和7年分は188万円以下）"),
    ("HK9 TA1177 控除対象扶養親族でない", W, "nta", "TA1177", "控除対象扶養親族に該当しないこと"),
    ("PS§0 JQA 厚労省掲載版", W, "extra", "mhlw_taiou", "事業主の証明に依る被扶養者認定に関するQ&A［201KB］（令和５年12月25日更新）"),
]
PHRASES += [
    # e-Gov
    ("PS§2.1 健保法3⑦二", E, "kenpo", "2026-11-09", "被保険者の三親等内の親族で前号に掲げる者以外のものであって、その被保険者と同一の世帯に属し、主としてその被保険者により生計を維持するもの"),
    ("PS§4.1 健保法3⑦ただし書", E, "kenpo", "2026-11-09", "後期高齢者医療の被保険者等である者その他この法律の適用を除外すべき特別の理由がある者として厚生労働省令で定める者は、この限りでない"),
    ("PS§4.1 健保法3①九 イ又はロ", E, "kenpo", "2026-11-09", "かつ、イ又はロのいずれかの要件に該当するもの"),
    ("PS§4.1 健保法3①九 イ", E, "kenpo", "2026-11-09", "イ 一週間の所定労働時間が二十時間未満であること。"),
    ("PS§4.1 健保法3①九 ロ", E, "kenpo", "2026-11-09", "第五十条に規定する高等学校の生徒、同法第八十三条に規定する大学の学生その他の厚生労働省令で定める者であること。"),
    ("MS§5 健保法3①九 旧ロ 8.8万（2026-04-01）", E, "kenpo", "2026-04-01", "八万八千円未満であること"),
    ("MS§5 健保法3①九 イからハ（2026-04-01）", E, "kenpo", "2026-04-01", "イからハまでのいずれかの要件に該当するもの"),
    ("PS§3 健保法43の2 育児休業等", E, "kenpo", "2026-11-09", "（以下「育児休業等」という。）"),
    ("PS§5.4 健保則38① 5日", E, "kenpo-ki", "2026-11-09", "被扶養者を有するに至ったときは、五日以内に"),
    ("PS§2.1 健保則38①二", E, "kenpo-ki", "2026-11-09", "同一の世帯に属した年月日及び扶養するに至った理由"),
    ("PS§5.4 健保則38② その都度", E, "kenpo-ki", "2026-11-09", "前項に掲げる事項に変更があったときは、その都度"),
    ("PS§5.3 健保則50①", E, "kenpo-ki", "2026-11-09", "保険者は、毎年一定の期日を定め、資格確認書の検認若しくは更新又は被扶養者に係る確認をすることができる"),
    ("PS§4.1 健保則37の3 二", E, "kenpo-ki", "2026-11-09", "本邦において一年を超えない期間滞在し、観光、保養その他これらに類似する活動を行うもの"),
    ("PS§2.1 住基法6①", E, "jumin", "2026-11-09", "個人を単位とする住民票を世帯ごとに編成して、住民基本台帳を作成しなければならない"),
    ("PS§2.1 住基法7四", E, "jumin", "2026-11-09", "世帯主についてはその旨、世帯主でない者については世帯主の氏名及び世帯主との続柄"),
    ("PS§2.1 住基法25 14日", E, "jumin", "2026-11-09", "その変更があつた日から十四日以内に"),
    ("PS§4.1 国保法6一", E, "kokuho", "2026-11-09", "一 健康保険法（大正十一年法律第七十号）の規定による被保険者"),
    ("PS§4.1 国保法6五", E, "kokuho", "2026-11-09", "五 健康保険法の規定による被扶養者"),
    ("検証で追加 国保法19①ただし書", E, "kokuho", "2026-11-09", "第六条各号（第十号を除く。）のいずれかに該当する者及び他の組合が行う国民健康保険の被保険者は、この限りでない"),
    ("IK1 民法143②", E, "minpo", "2026-11-09", "その起算日に応当する日の前日に満了する"),
    ("IK1 年齢計算ニ関スル法律②", E, "nenrei", "2026-11-09", "民法第百四十三条ノ規定ハ年齢ノ計算ニ之ヲ準用ス"),
    ("HK9 所法84の2① 123万", E, "shotoku", "2026-12-01", "合計所得金額が百二十三万円以下であるものに限る。）で控除対象扶養親族に該当しないもの"),
    ("PS§1.2 労基法11", E, "rouki", "2026-11-09", "この法律で賃金とは、賃金、給料、手当、賞与その他名称の如何を問わず、労働の対償として使用者が労働者に支払うすべてのものをいう"),
    ("PS§6 労基法15", E, "rouki", "2026-11-09", "使用者は、労働契約の締結に際し、労働者に対して賃金、労働時間その他の労働条件を明示しなければならない"),
]
# 期待が「なし」の項目（文書の「見当たらない」という主張と、文書の誤りの反証）
EXPECT_ABSENT = {"PS§1.3 H30QA-H に同旨なし", "IK1 N-FAQ に令和7年11月の例なし"}

# 文書（MS §4）が記録した law_revision_id
EXPECTED_REV = {
    ("kenpo", "2025-10-01"): "211AC0000000070_20250620_507AC0000000074",
    ("kenpo", "2025-12-31"): "211AC0000000070_20251212_507AC0000000087",
    ("kenpo", "2026-04-01"): "211AC0000000070_20260401_507AC0000000087",
    ("kenpo", "2026-11-09"): "211AC0000000070_20261001_507AC0000000087",
    ("kenpo-rei", "2026-11-09"): "215IO0000000243_20261001_508CO0000000276",
    ("kenpo-ki", "2025-10-01"): "215M10000008036_20250601_507M60000100062",
    ("kenpo-ki", "2025-12-31"): "215M10000008036_20251201_507M60000100118",
    ("kenpo-ki", "2026-04-01"): "215M10000008036_20260401_508M60000100054",
    ("kenpo-ki", "2026-11-09"): "215M10000008036_20261001_508M60000100144",
    ("jumin", "2026-11-09"): "342AC0000000081_20261024_508AC0000000066",
    ("kokuho", "2026-11-09"): "333AC0000000192_20261001_507AC0000000087",
}

# 文書（MS §3）が記録した SHA-256 の先頭16桁と大きさ（キーは本スクリプトのセットと id）
EXPECTED_SHA = {
    ("mhlw_tdoc", "S52"): ("3a0aec4d588447f7", 7871),
    ("mhlw_tdoc", "R7QA19"): ("ab13f28cfdfee9aa", 36705),
    ("mhlw_tdoc", "R3FUFU"): ("877a6884fd3de8dd", 16027),
    ("mhlw_tdoc", "H30A"): ("74819dc27ce6ccf6", 15158),
    ("mhlw_tdoc", "H30QA_H"): ("0c43dac8f2fa0aba", 59894),
    ("mhlw_tdoc", "H30QA_N"): ("b2f78b198f7164c3", 39261),
    ("mhlw_tdoc", "R01"): ("8c7a41bd8eb8937a", 44339),
    ("mhlw_tdoc", "R05"): ("a333fbd3a7355dd4", 46263),
    ("mhlw_tdoc", "R8QA2"): ("5e59c9a4b7f675e3", 10956),
    ("mhlw_pdf", "content_001678029"): ("dc76229c5e2a60a8", 179658),
    ("nenkin", "N_TET"): ("e090abd4c5550dfc", 46959),
    ("nenkin", "N_HEN"): ("d8a686f9d22e1de7", 47439),
    ("nenkin", "N_FAQ"): ("2595c8961984db7f", 24655),
    ("kyokai", "K_FAQ"): ("87da9750c230082d", 71028),
    ("kyokai", "K_SEN"): ("85a8087e767cf166", 37945),
    ("kyokai", "JQA"): ("2a15f6217f652020", 198221),
    ("other", "YORYO"): ("aee75810dca37cd1", 751096),
    ("other", "ITS"): ("142549e4917e44c0", 14986),
}


def latest_fetch_log(set_name):
    fs = sorted(OUT.glob(f"fetch_{set_name}_*.json"))
    return json.loads(fs[-1].read_text(encoding="utf-8")) if fs else None


def walk_units(full):
    """本則の条と附則の条（条のない附則は附則全体）を (場所, ノード) で返す。IMPL_kenpo_egov.py から写した。"""
    units = []
    mp = next(iter_tag(full, "MainProvision"), None)
    if mp:
        arts = list(iter_tag(mp, "Article"))
        units += [(f"本則 第{a.get('attr', {}).get('Num')}条", a) for a in arts] or [("本則", mp)]
    for sp in iter_tag(full, "SupplProvision"):
        label = sp.get("attr", {}).get("AmendLawNum") or "原始附則"
        arts = list(iter_tag(sp, "Article"))
        if arts:
            units += [(f"附則({label}) 第{a.get('attr', {}).get('Num')}条", a) for a in arts]
        else:
            units.append((f"附則({label})", sp))
    return units


def scan_count(full, pat):
    n = 0
    for _, node in walk_units(full):
        for p in (list(iter_tag(node, "Paragraph")) or [node]):
            n += len(re.findall(pat, text_of(p)))
    return n


SCAN_DEP = [r"被扶養者[^。]{0,80}(被保険者である|被保険者となった|被保険者となる|二以上|同時に|重複|他の保険者)",
            r"(被保険者である|二以上の)[^。]{0,80}被扶養者", r"同一の世帯", r"世帯に属"]
# 文書（MS §6）が記録した件数
EXPECTED_SCAN = [
    ("kenpo", "2026-11-09", SCAN_DEP[0], 0), ("kenpo", "2026-11-09", SCAN_DEP[1], 2),
    ("kenpo", "2026-11-09", SCAN_DEP[2], 4), ("kenpo", "2026-11-09", SCAN_DEP[3], 4),
    ("kenpo-rei", "2026-11-09", SCAN_DEP[0], 2), ("kenpo-rei", "2026-11-09", SCAN_DEP[2], 3),
    ("kenpo-ki", "2026-11-09", SCAN_DEP[0], 0), ("kenpo-ki", "2026-11-09", SCAN_DEP[2], 4),
    ("jumin", "2026-11-09", r"「世帯」とは", 0),
    ("kokuho", "2026-11-09", r"被扶養者", 18),
    # 検証で追加：PS §2.1「健保法・令・則に『世帯』を定義する規定は見当たらない」の確認（期待 0）
    ("kenpo", "2026-11-09", r"「(同一の)?世帯」とは", 0),
    ("kenpo-rei", "2026-11-09", r"「(同一の)?世帯」とは", 0),
    ("kenpo-ki", "2026-11-09", r"「(同一の)?世帯」とは", 0),
]


def check():
    ts = time.strftime("%Y%m%d-%H%M%S")
    res = {"checked_at_local": ts, "phrases": [], "revisions": [], "sha": [], "images": None, "scan": [],
           "r3_same_text": None, "calc": []}
    for item, kind, st, sid, phrase in PHRASES:
        t = load_text(st, sid) if kind == W else load_egov(st, sid)
        found = None if t is None else (norm(phrase) in norm(t))
        expect = item not in EXPECT_ABSENT
        res["phrases"].append({"item": item, "kind": kind, "set": st, "id": sid, "phrase": phrase, "found": found,
                               "expected_found": expect, "ok": found is expect})
    got = {}
    for lp in sorted(OUT.glob("egov_fetch_log_*.json")):
        for f in json.loads(lp.read_text(encoding="utf-8"))["fetches"]:
            got[(f["short"], f["asof"])] = f.get("law_revision_id")
    for k, v in EXPECTED_REV.items():
        res["revisions"].append({"law": k[0], "asof": k[1], "expected": v, "got": got.get(k), "ok": got.get(k) == v})
    for (st, sid), (pref, size) in EXPECTED_SHA.items():
        lg = latest_fetch_log(st)
        r = next((x for x in (lg or {}).get("results", []) if x["id"] == sid), None)
        g_sha, g_size = (r or {}).get("sha256", ""), (r or {}).get("bytes")
        res["sha"].append({"set": st, "id": sid, "expected_prefix": pref, "got_prefix": g_sha[:16], "expected_bytes": size,
                           "got_bytes": g_size, "sha_ok": g_sha.startswith(pref), "bytes_ok": g_size == size})
    lg = latest_fetch_log("mhlw_img")
    if lg:
        imgs = {x["id"]: x for x in lg["results"]}
        sizes_html = sorted({imgs[f"img{i}"]["bytes"] for i in range(1, 10)})
        sizes_png = [imgs[f"res{i}"]["bytes"] for i in range(1, 10)]
        res["images"] = {"t_img_sizes": sizes_html, "t_img_ok": sizes_html == [808],
                         "t_img_res_min": min(sizes_png), "t_img_res_max": max(sizes_png),
                         "t_img_res_ok": (min(sizes_png), max(sizes_png)) == (33613, 65004),
                         "t_img_res_types": sorted({imgs[f"res{i}"]["content_type"] for i in range(1, 10)})}
    for short, asof, pat, exp in EXPECTED_SCAN:
        try:
            full = json.loads((egov_json_dir(short, asof) / f"{short}_{asof}.json").read_bytes())["law_full_text"]
            n = scan_count(full, pat)
        except FileNotFoundError:
            n = None
        res["scan"].append({"law": short, "asof": asof, "pattern": pat, "expected": exp, "got": n, "ok": n == exp})
    r3 = ROOT / ".work" / "text" / "20261109-133945_R3_extra" / "nenkin_hifuyo_tetsuzuki.txt"
    now = load_text("nenkin", "N_TET")
    if r3.exists() and now:
        a = [x for x in r3.read_text(encoding="utf-8").splitlines() if x.strip()]
        b = [x for x in now.splitlines() if x.strip()]
        res["r3_same_text"] = {"r3_lines": len(a), "now_lines": len(b), "same": a == b}
    # 協会けんぽの HTML は Cloudflare のスクリプトの値が取得ごとに変わる（SHA-256 が毎回変わる）。
    # 本文の抽出テキスト（script を除く）が IMPL_kenpo の取得時と同じかを比べる。
    res["kyokai_text_same"] = []
    old_dir = ROOT / ".work" / "text" / "20261109-145500_IMPL_kenpo_kyokai"
    for old_id, new_id in (("kyokai_faq_dependent_status", "K_FAQ"), ("kyokai_senpo_glossary_004", "K_SEN"),
                           ("kyokai_pr_004_tokurei", "K_TOK")):
        po, tn = old_dir / f"{old_id}.txt", load_text("kyokai", new_id)
        if po.exists() and tn:
            to = po.read_text(encoding="utf-8")
            res["kyokai_text_same"].append({"old": old_id, "new": new_id, "same": to == tn,
                                            "old_text_sha256": hashlib.sha256(to.encode()).hexdigest()[:16],
                                            "new_text_sha256": hashlib.sha256(tn.encode()).hexdigest()[:16]})
    res["calc"] = calc()
    (OUT / f"check_{ts}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    md = [f"# IMPL_kenpo_verify check {ts}", "",
          "照合は NFKC 正規化・空白除去のうえの部分一致。「期待」が なし の行は、文書の「見当たらない」という主張や誤りを、語句がないことで確かめる行。", "",
          "## 1. 語句の照合", "", "| 項目 | 出典 | 語句 | 結果 | 期待 | 判定 |", "|---|---|---|---|---|---|"]
    for r in res["phrases"]:
        mark = {True: "あり", False: "なし", None: "本文なし"}[r["found"]]
        md.append(f"| {r['item']} | {r['set']}/{r['id']} | {r['phrase'][:50].replace('|', '｜')} | {mark} | "
                  f"{'あり' if r['expected_found'] else 'なし'} | {'OK' if r['ok'] else '**NG**'} |")
    md += ["", "## 2. law_revision_id（MS §4 の値との比較）", "", "| 法令 | asof | 文書 | 今回 | 判定 |", "|---|---|---|---|---|"]
    md += [f"| {r['law']} | {r['asof']} | {r['expected']} | {r['got']} | {'OK' if r['ok'] else '**NG**'} |" for r in res["revisions"]]
    md += ["", "## 3. SHA-256・大きさ（MS §3 の値との比較）", "", "| 出典 | 文書 SHA 先頭 | 今回 | 文書 bytes | 今回 | 判定 |", "|---|---|---|---|---|---|"]
    md += [f"| {r['set']}/{r['id']} | {r['expected_prefix']} | {r['got_prefix']} | {r['expected_bytes']} | {r['got_bytes']} | "
           f"{'OK' if r['sha_ok'] and r['bytes_ok'] else ('大きさのみ一致' if r['bytes_ok'] else '**NG**')} |" for r in res["sha"]]
    md += ["", "## 4. Q&A 第2版の画像（MS §2）", "", f"`{json.dumps(res['images'], ensure_ascii=False)}`"]
    md += ["", "## 5. 語句の走査の件数（MS §6 の再現）", "", "| 法令 | asof | パターン | 文書 | 今回 | 判定 |", "|---|---|---|---|---|---|"]
    md += [f"| {r['law']} | {r['asof']} | `{r['pattern'].replace('|', '｜')}` | {r['expected']} | {r['got']} | {'OK' if r['ok'] else '**NG**'} |" for r in res["scan"]]
    md += ["", "## 6. R3 の 20141202.html の抽出テキストとの比較（MS §3-4）", "", f"`{json.dumps(res['r3_same_text'], ensure_ascii=False)}`"]
    md += ["", "## 6b. 協会けんぽの HTML：抽出テキストの比較（SHA-256 は取得ごとに変わるため）", "",
           f"`{json.dumps(res['kyokai_text_same'], ensure_ascii=False)}`"]
    md += ["", "## 7. 再計算", "", "| 項目 | 式 | 値 | 文書の値 | 一致 |", "|---|---|---|---|---|"]
    md += [f"| {c['item']} | {c['expr']} | {c['value']} | {c['doc']} | {'一致' if c['ok'] else '**不一致**'} |" for c in res["calc"]]
    (OUT / f"check_{ts}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    ng = ([r["item"] for r in res["phrases"] if not r["ok"]]
          + [f"rev {r['law']} {r['asof']}" for r in res["revisions"] if not r["ok"]]
          + [f"sha {r['set']}/{r['id']}" for r in res["sha"] if not (r["sha_ok"] and r["bytes_ok"])]
          + [f"scan {r['law']} {r['pattern']}" for r in res["scan"] if not r["ok"]]
          + [f"calc {c['item']}" for c in res["calc"] if not c["ok"]])
    print(f"phrases={len(res['phrases'])} revisions={len(res['revisions'])} sha={len(res['sha'])} scan={len(res['scan'])} calc={len(res['calc'])}")
    print("images:", json.dumps(res["images"], ensure_ascii=False))
    print("r3_same_text:", json.dumps(res["r3_same_text"], ensure_ascii=False))
    print("kyokai_text_same:", json.dumps(res["kyokai_text_same"], ensure_ascii=False))
    print("NG:", json.dumps(ng, ensure_ascii=False, indent=0))
    print(f"written {OUT / f'check_{ts}.md'}")


def age_on(birth, day):
    """年齢計算ニ関スル法律（民法第143条を準用。出生日から起算）による day 時点の満年齢。
    誕生日の前日の終了時に加算する扱い（R7QA19 Q4「誕生日の前日において加算」）なので、
    day が誕生日の前日以降なら加算済みとする。"""
    # 誕生日の前日に加算されるので、day の年齢 ＝ (day の翌日) における通常の満年齢（誕生日当日に加算）。
    # 1月1日生まれは前年の12月31日に加算される（R7QA19 Q4）ことも、これで扱える。
    d = day + datetime.timedelta(days=1)
    y = d.year - birth.year
    try:
        bd = birth.replace(year=d.year)
    except ValueError:  # 2月29日生まれ（平年は3月1日を誕生日とみなす。本検証のケースには出てこない）
        bd = datetime.date(d.year, 3, 1)
    if d < bd:
        y -= 1
    return y


def threshold_19_23(birth, d, spouse=False):
    """IK1 の期待値の再計算：判定日 d の属する年の12月31日の年齢が19〜22で、d が 2025-10-01 以降、配偶者でないなら150万円。"""
    a = age_on(birth, datetime.date(d.year, 12, 31))
    if (not spouse) and d >= datetime.date(2025, 10, 1) and 19 <= a <= 22:
        return a, 1_500_000
    return a, 1_300_000


def calc():
    out = []

    def add(item, expr, value, doc):
        out.append({"item": item, "expr": expr, "value": value, "doc": doc, "ok": value == doc})

    # IK3 / PS §1.2：月額・日額の目安
    add("PS§1.2 月額 130万", "floor(1300000/12)", 1_300_000 // 12, 108_333)
    add("IK3 108,333×12", "108333*12", 108_333 * 12, 1_299_996)
    add("PS§1.2 日額 130万", "floor(1300000/360)", 1_300_000 // 360, 3_611)
    add("IK3 3,611×360", "3611*360", 3_611 * 360, 1_299_960)
    add("IK3 3,612×360", "3612*360", 3_612 * 360, 1_300_320)
    add("IK3 3,612×360 >= 130万", "3612*360>=1300000", 3_612 * 360 >= 1_300_000, True)
    add("JQA 108,334 = 130万/12 の切り上げ", "ceil(1300000/12)", -(-1_300_000 // 12), 108_334)
    add("IK3 150万/12", "1500000/12", 1_500_000 / 12, 125_000)
    add("IK3 150万/360", "floor(1500000/360)", 1_500_000 // 360, 4_166)
    add("IK3 180万/12", "1800000/12", 1_800_000 / 12, 150_000)
    add("IK3 180万/360", "1800000/360", 1_800_000 / 360, 5_000)
    # 365日で割った場合（機構の日額が360日によるかの反証）
    add("IK3 反証：130万/365 の切り捨て", "floor(1300000/365)", 1_300_000 // 365, 3_561)
    # IK1：年齢と基準額
    cases = [
        ("a", "2006-11-20", "2025-09-30", False, 19, 1_300_000),
        ("b", "2006-11-20", "2025-10-01", False, 19, 1_500_000),
        ("c", "2007-01-01", "2025-11-01", False, 19, 1_500_000),
        ("d", "2007-01-02", "2025-11-01", False, 18, 1_300_000),
        ("e", "2007-01-02", "2026-01-05", False, 19, 1_500_000),
        ("f", "2003-01-02", "2025-11-01", False, 22, 1_500_000),
        ("g", "2003-01-01", "2025-11-01", False, 23, 1_300_000),
        ("h", "2003-01-02", "2026-02-01", False, 23, 1_300_000),
        ("i", "2005-05-05", "2026-02-01", True, 20, 1_300_000),  # 文書の値 20 をそのまま入れる（検証対象）
    ]
    for cid, b, d, sp, doc_age, doc_th in cases:
        bb, dd = datetime.date.fromisoformat(b), datetime.date.fromisoformat(d)
        a, th = threshold_19_23(bb, dd, sp)
        add(f"IK1 {cid} 年齢", f"age({b} → {dd.year}-12-31)", a, doc_age)
        add(f"IK1 {cid} 基準額", f"threshold({b},{d},spouse={sp})", th, doc_th)
    # IK1 i の文書の値（20）の検証用に、実際の値も記録
    # IK2
    add("IK2 基本（時給1,200×週15h×52週）", "1200*15*52", 1200 * 15 * 52, 936_000)
    add("IK2 通勤手当 月5,000×12", "5000*12", 5000 * 12, 60_000)
    add("IK2 従来（基本＋時間外60万）", "936000+600000", 936_000 + 600_000, 1_536_000)
    add("IK2 労働契約（基本＋通勤）", "936000+60000", 936_000 + 60_000, 996_000)
    add("IK2 従来 >= 150万", "1536000>=1500000", 1_536_000 >= 1_500_000, True)
    add("IK2 労働契約 < 150万", "996000<1500000", 996_000 < 1_500_000, True)
    # IK2 の年額への換算（×52週）は R8QA2 Q2 に定めがない（「時給・労働時間・日数等を用いて算出」）。換算の違いで結論が変わらないかの確認
    add("IK2 換算の別法 ×365/7週", "round(1200*15*365/7)", round(1200 * 15 * 365 / 7), 938_571)
    add("IK2 換算の別法 ×4.3週×12月", "1200*15*4.3*12", round(1200 * 15 * 4.3 * 12), 928_800)
    add("IK2 別法でも労働契約 < 150万", "max(938571,928800)+60000<1500000", max(938_571, 928_800) + 60_000 < 1_500_000, True)
    add("IK2 別法でも従来 >= 150万", "min(938571,928800)+600000>=1500000", min(938_571, 928_800) + 600_000 >= 1_500_000, True)
    # IK7：令和8・9年分の特例（収入 74万1,000円以上219万1,000円未満は 収入−74万円）での給与所得
    add("IK7 給与所得（令和8年分特例）", "1450000-740000", 1_450_000 - 740_000, 710_000)
    add("IK7 給与所得は 62万超123万以下", "620000<710000<=1230000", 620_000 < 710_000 <= 1_230_000, True)
    # IK2：通勤手当（年 60,000）を算入するかで結論が変わる「基本＋時間外」の範囲（150万円未満の基準）。
    # 文書は 1,450,000〜1,499,999 と書いている。下限を再計算する。
    lo = min(x for x in range(1_400_000, 1_500_000) if x < 1_500_000 <= x + 60_000)
    add("IK2 通勤手当で結論が変わる範囲の下限", "min{x: x<1500000<=x+60000}", lo, 1_450_000)
    add("IK2 通勤手当で結論が変わる範囲の上限", "max{x: x<1500000}", 1_499_999, 1_499_999)
    # IK5
    add("IK5 1割（600万の1割）", "6000000*0.1", 6_000_000 // 10, 600_000)
    add("IK5 a 差70万 > 60万", "700000>600000", 700_000 > 600_000, True)
    add("IK5 b 差50万 <= 60万", "500000<=600000", 500_000 <= 600_000, True)
    # IK7（令和8年分の給与収入の範囲：136万超197万以下は文書の値。ここでは 1,450,000 が範囲内かだけ）
    add("IK7 1,450,000 は 136万超197万以下", "1360000<1450000<=1970000", 1_360_000 < 1_450_000 <= 1_970_000, True)
    add("IK7 1,450,000 < 150万", "1450000<1500000", 1_450_000 < 1_500_000, True)
    add("IK7 親の2分の1（600万/2）", "6000000/2 > 1450000", 6_000_000 / 2 > 1_450_000, True)
    # HK9：令和8年分 62万＋最低保障74万＝136万、123万＋74万＝197万（給与所得控除の最低保障額が収入190万円以下で74万円の場合）
    add("HK9 62万+74万", "620000+740000", 620_000 + 740_000, 1_360_000)
    add("HK9 123万+74万", "1230000+740000", 1_230_000 + 740_000, 1_970_000)
    add("HK9 令和7年分 58万+65万", "580000+650000", 580_000 + 650_000, 1_230_000)
    add("HK9 令和7年分 123万+65万", "1230000+650000", 1_230_000 + 650_000, 1_880_000)
    # IK4
    add("IK4 100万 < 120万（援助）", "1000000<1200000", 1_000_000 < 1_200_000, True)
    add("IK4 100万 >= 80万", "1000000>=800000", 1_000_000 >= 800_000, True)
    return out


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")
    if not argv:
        print(__doc__)
        return 2
    cmd = argv[0]
    if cmd == "fetch":
        if len(argv) == 1 or argv[1] == "--list":
            for k, v in SETS.items():
                print(k, len(v))
            return 0
        ts = time.strftime("%Y%m%d-%H%M%S")
        for i, name in enumerate(argv[1:]):
            if i:
                time.sleep(WAIT)
            run_set(name, SETS[name], ts)
        return 0
    if cmd == "egov":
        egov(set(argv[1:]) or None)
        return 0
    if cmd == "check":
        check()
        return 0
    if cmd == "suppl":
        # 取得済みの e-Gov JSON（最新の .work/downloads/*_kenpo_verify_egov/）から、指定した改正法令の附則を抜き出す
        # 使い方: suppl <略称> <asof> <AmendLawNum> [<grep 語句>]
        short, asof, aln = argv[1], argv[2], argv[3]
        word = argv[4] if len(argv) > 4 else None
        d = egov_json_dir(short, asof)
        full = json.loads((d / f"{short}_{asof}.json").read_bytes())["law_full_text"]
        lines = [f"# {short} asof={asof} 附則 AmendLawNum={aln}（{d.name}/{short}_{asof}.json から）", ""]
        for sp in iter_tag(full, "SupplProvision"):
            if (sp.get("attr", {}).get("AmendLawNum") or "原始附則") != aln:
                continue
            arts = list(iter_tag(sp, "Article"))
            for a in arts or [sp]:
                txt = render(a) if arts else [text_of(p) for p in iter_tag(sp, "Paragraph")]
                if word and not any(word in t for t in txt):
                    continue
                lines += txt + [""]
        name = f"suppl_{short}_{asof}_{re.sub(r'[^0-9A-Za-z一-龥〇]', '', aln)}{'_' + word if word else ''}.txt"
        (OUT / "egov_articles" / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n".join(lines))
        return 0
    print("unknown command", cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

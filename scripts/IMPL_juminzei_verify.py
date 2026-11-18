"""IMPL juminzei verify: 住民税トピックの文書（public-sources / measurements / hypotheses / inferences）の主張を、
担当とは独立に一次情報へ当たり直して確かめる（反証役）。

実行（必ずこの python で。pyenv のシムは使わない）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_juminzei_verify.py laws   # e-Gov 法令API v2 から取得
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_juminzei_verify.py web    # 自治体・総務省・参議院の資料を取得
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_juminzei_verify.py check  # 条文の文字列の照合（ネットワーク不要）
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_juminzei_verify.py calc   # 境目の再計算（ネットワーク不要）
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_juminzei_verify.py webcheck  # 資料の文字列の照合（ネットワーク不要）

方針
- 担当のスクリプト（IMPL_juminzei_*.py）の出力は使わない。法令は自分で取り直し、自分の描画で文字列にする。
  e-Gov API の使い方は scripts/R1_egov_articles.py と scripts/R4_fetch_laws.py を参考にした（import していない）。
- 標準ライブラリのみ。リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。
- ダウンロードしたもの（JSON・HTML・PDF）は信頼できないデータ。取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_IMPL_juminzei_verify_<laws|web>/ に置き、その中でインタプリタやツールを実行しない。
  PDF はこのスクリプトでは解析しない（保存とハッシュのみ。中身は人が Read ツールの頁指定で読む）。
- 出力：scripts/results/IMPL_juminzei_verify/
"""
import datetime
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
import urllib.robotparser

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "results" / "IMPL_juminzei_verify"
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
SLEEP = 1.5

ASOF5 = ["2025-12-31", "2026-01-01", "2026-11-09", "2027-01-01", "2028-01-01"]
# (略称, law_id, asof の一覧, 本則の条（Num）, 原始附則の条（Num）, 改正附則の AmendLawNum（完全一致）, 別表の題名の正規表現)
LAWS = [
    ("chiho", "325AC0000000226", ASOF5,
     ["23", "24_5", "32", "34", "45_2", "292", "294", "295", "313", "314_2", "317_2", "317_3", "317_6", "318"],
     ["3_3"], ["令和七年三月三一日法律第七号", "令和八年三月三一日法律第二号"], None),
    ("chiho-rei", "325CO0000000245", ASOF5,
     ["7_3_3", "7_3_4", "7_3_5", "8_2", "46_3", "46_4", "46_5", "47_3", "48_9_7"], [], [], None),
    ("chiho-ki", "329M50000002023", ["2025-12-31", "2026-01-01", "2026-11-09", "2027-01-01", "2028-01-01"],
     ["9_21"], [], [], None),
    ("minpo", "129AC0000000089", ["2026-11-09"], ["4", "143"], [], ["平成三〇年六月二〇日法律第五九号"], None),
    ("shotoku", "340AC0000000033", ["2025-12-31", "2026-12-01"], ["2", "28"], [], [], r"別表第五"),
    ("shotoku-rei", "340CO0000000096", ["2026-11-09"], ["219"], [], [], None),
    ("sochi", "332AC0000000026", ["2026-11-09", "2026-12-01"], ["29_4", "29_5"], [], [], None),
]
KEYWORD_SEARCH = ["二以上の納税義務者の扶養親族", "二以上の納税義務者の控除対象配偶者", "均等割を課することができない"]

# 担当の文書が挙げた自治体・総務省・参議院の資料（docs/public-sources/20261109_impl-prep_juminzei-hikazei-fuyo-shinkoku.md §1.6・§3.2・§8）
WEB = [
    ("sapporo_jorei", "https://www.city.sapporo.jp/ncms/reiki/d1w_reiki_nonframe/H325901010044/H325901010044_j.html"),
    ("sapporo_jorei_misikou", "https://www.city.sapporo.jp/ncms/reiki/d1w_reiki_nonframe/H325901010044/H325901010044_misikou_j.html"),
    ("meguro", "https://www.city.meguro.tokyo.jp/zeimu/kurashi/juuminzei/zeiseikaisei5.html"),
    ("saitama", "https://www.city.saitama.lg.jp/001/153/004/002/001/003/p092338.html"),
    ("yokohama_konan", "https://www.city.yokohama.lg.jp/konan/kurashi/koseki_zei_hoken/zeikin/kojin/miseinensha.html"),
    ("setagaya", "https://www.city.setagaya.lg.jp/02051/220.html"),
    ("edogawa", "https://www.city.edogawa.tokyo.jp/e013/kurashi/zeikin/juminzei/zei_gaiyo/hikazei.html"),
    ("kashiwa", "https://www.city.kashiwa.lg.jp/shiminzei/kojinshiminzei/r8hikazei.html"),
    ("kobe", "https://www.city.kobe.lg.jp/a83576/kurashi/tax/shikenminze/r9kaisei.html"),
    ("sendai", "https://www.city.sendai.jp/shiminze-kikaku/kurashi/tetsuzuki/zekin/kojin/kaisei/r8.html"),
    ("chiba", "https://www.city.chiba.jp/zaiseikyoku/zeimu/kazeikanri/zeiseikaiseijuminzei2027.html"),
    ("osaka_pref", "https://www.pref.osaka.lg.jp/o050030/zei/alacarte/reiwa8_zeikai.html"),
    ("yokohama_r8", "https://www.city.yokohama.lg.jp/kurashi/koseki-zei-hoken/zeikin/y-shizei/kojin-shiminzei-kenminzei/R8kaisei.html"),
    ("soumu_kojin", "https://www.soumu.go.jp/main_sosiki/jichi_zeisei/czaisei/czaisei_seido/150790_06.html"),
    ("soumu_ichiran04", "https://www.soumu.go.jp/main_sosiki/jichi_zeisei/czaisei/czaisei_seido/ichiran04.html"),
    ("soumu_tsuchi_zenbun_r8", "https://www.soumu.go.jp/main_content/001071661.pdf"),
    ("sangiin_486", "https://www.sangiin.go.jp/japanese/annai/chousa/rippou_chousa/backnumber/2026pdf/20260806162.pdf"),
]


# ---------------------------------------------------------------- 取得
def get(url, accept="application/json", timeout=300):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body, st, hdr, final = r.read(), r.status, dict(r.headers), r.geturl()
    except urllib.error.HTTPError as e:
        body, st, hdr, final = e.read(), e.code, dict(e.headers or {}), url
    except Exception as e:  # noqa
        body, st, hdr, final = repr(e).encode(), None, {}, url
    time.sleep(SLEEP)
    return st, body, hdr, final


def new_dl(kind):
    ts = time.strftime("%Y%m%d-%H%M%S")
    d = ROOT / ".work" / "downloads" / f"{ts}_IMPL_juminzei_verify_{kind}"
    d.mkdir(parents=True, exist_ok=False)  # 必ず新しい空のディレクトリ
    return ts, d


# ---------------------------------------------------------------- 法令の描画（自分で書いたもの）
def flat(n):
    """節点の下の文字列を、ルビの読み（Rt）を除いてつなぐ。"""
    if isinstance(n, str):
        return n
    if n.get("tag") == "Rt":
        return ""
    return "".join(flat(c) for c in n.get("children", []))


def kids(n, tag=None):
    return [c for c in n.get("children", []) if isinstance(c, dict) and (tag is None or c.get("tag") == tag)]


def render_article(a):
    """条を、項・号・細目ごとに1行の文字列にする（項は「〔n〕」、号は「〈n〉」、細目は「《n》」の印をつける）。"""
    out = []

    def rec(n, depth):
        tag = n.get("tag", "")
        if tag in ("ArticleCaption", "ArticleTitle"):
            out.append(flat(n))
            return
        if tag == "Paragraph" or tag == "Item" or tag.startswith("Subitem") and not tag.endswith(("Sentence", "Title")):
            mark = {"Paragraph": "〔{}〕", "Item": "〈{}〉"}.get(tag, "《{}》").format(n.get("attr", {}).get("Num", "?"))
            head = "".join(flat(c) for c in kids(n) if c.get("tag", "").endswith(("Title", "Num")) or c.get("tag", "").endswith("Sentence"))
            cap = "".join(flat(c) for c in kids(n, "ParagraphCaption"))
            out.append("  " * depth + mark + (cap + " " if cap else "") + head)
            for c in kids(n):
                t = c.get("tag", "")
                if t.endswith(("Title", "Num", "Sentence")) or t == "ParagraphCaption":
                    continue
                rec(c, depth + 1)
            return
        if tag == "TableRow":
            out.append("  " * depth + "| " + " | ".join(flat(c).replace("\n", " ") for c in kids(n)) + " |")
            return
        if tag in ("TableStruct", "Table", "TableColumn", "TableHeaderRow", "TableHeaderColumn", "List", "ListSentence", "Sentence",
                   "Sublist1", "Sublist1Sentence", "Sublist2", "Sublist2Sentence", "Column", "Remarks", "RemarksLabel", "TableStructTitle"):
            if tag in ("TableHeaderRow",):
                out.append("  " * depth + "| " + " | ".join(flat(c) for c in kids(n)) + " |")
                return
            if tag in ("List", "Sublist1", "Sublist2", "Remarks"):
                out.append("  " * depth + flat(n))
                return
        for c in kids(n):
            rec(c, depth)

    rec(a, 0)
    return "\n".join(out)


def walk(n, fn, path=()):
    if isinstance(n, dict):
        fn(n, path)
        for c in n.get("children", []):
            walk(c, fn, path + (n.get("tag"),))


def split_law(root):
    main, orig, amend = [], [], []

    def fn(n, path):
        t = n.get("tag")
        if t == "Article" and "SupplProvision" not in path:
            main.append(n)
        if t == "SupplProvision":
            if n.get("attr", {}).get("AmendLawNum"):
                amend.append(n)
            else:
                walk(n, lambda m, p: orig.append(m) if m.get("tag") == "Article" else None)
    walk(root, fn)
    return main, orig, amend


def cmd_laws():
    ts, dl = new_dl("laws")
    od = OUT / "laws"
    od.mkdir(parents=True, exist_ok=True)
    meta = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "fetches": [], "keyword": [], "revisions": None}
    for short, law_id, asofs, arts, orig_arts, amend_nums, appdx in LAWS:
        for asof in asofs:
            url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
            st, raw, hdr, _ = get(url)
            (dl / f"{short}_{asof}.json").write_bytes(raw)
            rec = {"short": short, "law_id": law_id, "asof": asof, "url": url, "status": st, "bytes": len(raw),
                   "sha256": hashlib.sha256(raw).hexdigest()}
            if st != 200:
                meta["fetches"].append(rec)
                print("ERR", short, asof, st, flush=True)
                continue
            d = json.loads(raw)
            ri, li = d.get("revision_info") or {}, d.get("law_info") or {}
            rec.update({k: ri.get(k) for k in ("law_revision_id", "law_title", "amendment_law_num", "amendment_law_title",
                                                 "amendment_enforcement_date", "current_revision_status", "updated")})
            rec["law_num"] = li.get("law_num")
            meta["fetches"].append(rec)
            main, orig, amend = split_law(d["law_full_text"])
            by_main = {a["attr"].get("Num"): a for a in main}
            by_orig = {a["attr"].get("Num"): a for a in orig}
            lines = [f"# {rec.get('law_title')}（{rec['law_num']}） law_id={law_id} asof={asof}",
                     f"# law_revision_id={rec.get('law_revision_id')} status={rec.get('current_revision_status')} "
                     f"amendment={rec.get('amendment_law_num')} enforced={rec.get('amendment_enforcement_date')}",
                     f"# url={url}", ""]
            for num in arts:
                lines.append(f"=== 本則 {num}")
                lines.append(render_article(by_main[num]) if num in by_main else "（この版の本則にない）")
                lines.append("")
            for num in orig_arts:
                lines.append(f"=== 原始附則 {num}")
                lines.append(render_article(by_orig[num]) if num in by_orig else "（この版の原始附則にない）")
                lines.append("")
            for an in amend_nums:
                hits = [s for s in amend if s.get("attr", {}).get("AmendLawNum") == an]
                lines.append(f"=== 改正附則 {an}（{len(hits)} 件）")
                for s in hits:
                    for a in kids(s, "Article"):
                        lines.append(render_article(a))
                    for p in kids(s, "Paragraph"):
                        lines.append(render_article({"tag": "X", "children": [p]}))
                lines.append("")
            if appdx:
                tabs = []
                walk(d["law_full_text"], lambda m, p: tabs.append(m) if m.get("tag") == "AppdxTable" else None)
                for t in tabs:
                    ttl = "".join(flat(c) for c in kids(t, "AppdxTableTitle"))
                    if re.search(appdx, ttl):
                        rows = []
                        walk(t, lambda m, p: rows.append([flat(c).strip() for c in kids(m)]) if m.get("tag") == "TableRow" else None)
                        (od / f"{short}_appdx_{asof}.json").write_text(json.dumps({"title": ttl, "rows": rows}, ensure_ascii=False, indent=0),
                                                                       encoding="utf-8")
            # 語の出現数（本則・原始附則・改正附則の別）
            cnt = {}
            for word in ("未成年者", "第二十九条の四"):
                c = {"本則": [], "原始附則": [], "改正附則": 0}
                for a in main:
                    k = flat(a).count(word)
                    if k:
                        c["本則"].append([a["attr"].get("Num"), k])
                for a in orig:
                    k = flat(a).count(word)
                    if k:
                        c["原始附則"].append([a["attr"].get("Num"), k])
                for s in amend:
                    c["改正附則"] += flat(s).count(word)
                cnt[word] = c
            (od / f"{short}_{asof}_wordcount.json").write_text(json.dumps(cnt, ensure_ascii=False, indent=1), encoding="utf-8")
            (od / f"{short}_{asof}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
            print("ok", short, asof, rec.get("law_revision_id"), rec.get("current_revision_status"), flush=True)
    # 改正履歴（地方税法）
    q = urllib.parse.urlencode({"response_format": "json", "amendment_date_from": "2025-01-01"})
    st, raw, _, _ = get(f"{API}/law_revisions/325AC0000000226?{q}")
    (dl / "revisions_chiho.json").write_bytes(raw)
    if st == 200:
        revs = json.loads(raw).get("revisions", [])
        meta["revisions"] = [{k: r.get(k) for k in ("law_revision_id", "amendment_law_num", "amendment_law_title", "amendment_promulgate_date",
                                                  "amendment_enforcement_date", "current_revision_status")} for r in revs]
    # 全文検索
    for kw in KEYWORD_SEARCH:
        q = urllib.parse.urlencode({"keyword": kw, "response_format": "json", "asof": "2026-11-09", "limit": 100})
        st, raw, _, _ = get(f"{API}/keyword?{q}")
        r = {"keyword": kw, "status": st}
        if st == 200:
            dj = json.loads(raw)
            r["total_count"] = dj.get("total_count")
            r["laws"] = [(it.get("revision_info") or {}).get("law_title") for it in dj.get("items", [])]
        meta["keyword"].append(r)
    (OUT / "laws_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done laws")


# ---------------------------------------------------------------- Web 資料
class Text(html.parser.HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "dt", "dd", "section", "article", "caption"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        if tag in self.BLOCK:
            self.out.append("\n")
        if tag in ("td", "th"):
            self.out.append(" | ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.skip = max(0, self.skip - 1)
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def decode(body, ct):
    cands = []
    m = re.search(r"charset=([\w-]+)", ct or "", re.I)
    if m:
        cands.append(m.group(1))
    m2 = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", body[:4000], re.I)
    if m2:
        cands.append(m2.group(1).decode("ascii", "replace"))
    cands += ["utf-8", "cp932", "euc-jp"]
    for c in cands:
        try:
            return body.decode(c), c
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", "replace"), "utf-8(replace)"


def cmd_web(names):
    ts, dl = new_dl("web")
    od = OUT / "web"
    od.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "robots": {}, "fetches": []}
    robots = {}
    for name, url in WEB:
        if names and name not in names:
            continue
        sp = urllib.parse.urlsplit(url)
        base = f"{sp.scheme}://{sp.netloc}"
        if base not in robots:
            st, body, _, _ = get(base + "/robots.txt", accept="text/plain", timeout=60)
            (dl / f"robots_{sp.netloc}.txt").write_bytes(body)
            rp = urllib.robotparser.RobotFileParser()
            rp.parse(body.decode("utf-8", "replace").splitlines() if st == 200 else [])
            robots[base] = rp
            log["robots"][base] = st
        ok = robots[base].can_fetch(UA, url)
        e = {"name": name, "url": url, "robots_allowed": ok}
        if not ok:
            e["skipped"] = "robots.txt"
            log["fetches"].append(e)
            continue
        st, body, hdr, final = get(url, accept="*/*", timeout=180)
        ct = hdr.get("Content-Type", "")
        ext = ".pdf" if body[:5] == b"%PDF-" else ".html"
        (dl / f"{name}{ext}").write_bytes(body)
        e.update({"status": st, "final_url": final, "content_type": ct, "last_modified": hdr.get("Last-Modified"), "bytes": len(body),
                  "sha256": hashlib.sha256(body).hexdigest(), "saved": str((dl / f"{name}{ext}").relative_to(ROOT)),
                  "fetched_at": datetime.datetime.now().isoformat(timespec="seconds")})
        if ext == ".html" and st == 200:
            s, enc = decode(body, ct)
            p = Text()
            p.feed(s)
            t = "".join(p.out)
            t = re.sub(r"[ \t\u3000]+\n", "\n", t)
            t = re.sub(r"\n{3,}", "\n\n", t).strip()
            (od / f"{name}.txt").write_text(f"# {name}\n# url={url}\n# fetched={e['fetched_at']} sha256={e['sha256']}\n\n{t}\n", encoding="utf-8")
            e["encoding"] = enc
        log["fetches"].append(e)
        print("ok", name, st, ext, len(body), flush=True)
    suffix = "" if not names else "_partial_" + ts
    (OUT / f"web_log{suffix}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done web")


# ---------------------------------------------------------------- 文字列の照合
def nfkc(s):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s))


def law_sections(short, asof):
    p = OUT / "laws" / f"{short}_{asof}.txt"
    secs, cur, buf = {}, None, []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.startswith("=== "):
            if cur:
                secs[cur] = "\n".join(buf)
            cur, buf = line[4:].split("（")[0].strip(), []
        elif cur:
            buf.append(line)
    if cur:
        secs[cur] = "\n".join(buf)
    return secs


def para(text, pnum):
    """〔n〕 の印で始まる項の部分（次の項の印の前まで）を返す。"""
    m = re.search(r"^\s*〔" + re.escape(str(pnum)) + r"〕.*?(?=^\s*〔\d+(?:_\d+)?〕|\Z)", text, re.S | re.M)
    return m.group(0) if m else ""


def item(text, inum):
    """〈n〉 の印で始まる号（同じ深さの次の号・次の項の前まで）を返す。"""
    out, on, ind = [], False, None
    for ln in text.splitlines():
        m = re.match(r"^(\s*)〈([0-9_]+)〉", ln)
        if not on:
            if m and m.group(2) == str(inum):
                on, ind = True, len(m.group(1))
                out.append(ln)
            continue
        if re.match(r"^\s*〔", ln) or (m and len(m.group(1)) <= ind):
            break
        out.append(ln)
    return "\n".join(out)


def load_json_law(short, asof):
    """laws 段で保存した e-Gov の JSON を読む（ダウンロード先の外から、パスを渡して読むだけ）。"""
    meta = json.loads((OUT / "laws_meta.json").read_text(encoding="utf-8"))
    return json.loads((ROOT / meta["download_dir"] / f"{short}_{asof}.json").read_text(encoding="utf-8"))


def law_articles(short, asof):
    d = load_json_law(short, asof)
    main, orig, amend = split_law(d["law_full_text"])
    return d, main, orig, amend


# 主張の照合表：(ID, 文書と節, 略称, asof の一覧, 節（=== の見出し）, 項, 号, 含まれるべき文字列の一覧)
A5 = ASOF5
A3 = ["2026-01-01", "2026-11-09", "2027-01-01"]
R89 = ["2026-01-01", "2027-01-01"]
CLAIMS = [
    ("L01", "PS§1.1 法295③", "chiho", A5, "本則 295", 3, None,
     ["均等割のみを課すべきもののうち、前年の合計所得金額が政令で定める基準に従い当該市町村の条例で定める金額以下である者に対しては、均等割を課することができない"]),
    ("L02", "PS§1.1 法24の5③", "chiho", A5, "本則 24_5", 3, None,
     ["第二百九十五条第三項の規定により個人の市町村民税の均等割を課することができないこととされる者に対しては、当該均等割と併せて賦課徴収すべき個人の道府県民税の均等割を課することができない"]),
    ("L03", "PS§1.2 令47の3一", "chiho-rei", A5, "本則 47_3", 1, 1,
     ["当該条例で基本額として定める一定金額に", "年齢十六歳未満の者及び法第三百十四条の二第一項第十一号に規定する控除対象扶養親族に限る",
      "数に一を加えた数を乗じて得た金額に、十万円を加算した金額", "当該条例で加算額として定める一定金額を加算した金額"]),
    ("L04", "PS§1.2 令47の3二", "chiho-rei", A5, "本則 47_3", 1, 2,
     ["三十五万円を超えない範囲内", "前年の十二月三十一日における地域の級地区分とする", "参酌して定める"]),
    ("L05", "PS§1.2 令47の3三", "chiho-rei", A5, "本則 47_3", 1, 3, ["二十一万円を超えない範囲", "前年の十二月三十一日において該当した"]),
    ("L06", "PS§1.3 規則9の21①", "chiho-ki", A5, "本則 9_21", 1, None, ["夫、妻及び二人の子からなる世帯", "借家に居住する世帯", "収入のない世帯"]),
    ("L07", "PS§1.3 規則9の21②", "chiho-ki", A5, "本則 9_21", 2, None,
     ["前年の十二月三十一日における地域の級地区分とする", "一級地一・〇", "二級地〇・九", "三級地〇・八"]),
    ("L08", "PS§2.1 法附則3の3④", "chiho", A5, "原始附則 3_3", 4, None,
     ["当分の間", "第三百十三条の規定により算定した総所得金額、退職所得金額及び山林所得金額の合計額",
      "三十五万円にその者の同一生計配偶者及び扶養親族（年齢十六歳未満の者及び第三百十四条の二第一項第十一号に規定する控除対象扶養親族に限る。",
      "十万円を加算した金額", "三十二万円を加算した金額", "市町村民税の所得割（分離課税に係る所得割を除く。）を課することができない"]),
    ("L09", "PS§2.1 法附則3の3①", "chiho", A5, "原始附則 3_3", 1, None,
     ["第三十二条の規定により算定した総所得金額、退職所得金額及び山林所得金額の合計額", "第三十四条第一項第十一号に規定する控除対象扶養親族",
      "三十二万円を加算した金額"]),
    ("L10", "PS§2.1 法292①十三 合計所得金額", "chiho", A3, "本則 292", 1, 13,
     ["第三百十三条第八項及び第九項の規定による控除前の同条第一項の総所得金額、退職所得金額及び山林所得金額の合計額"]),
    ("L11", "PS§3.1 法295①", "chiho", A5, "本則 295", 1, None,
     ["第二号に該当する者にあつては、第三百二十八条の規定により課する所得割（以下「分離課税に係る所得割」という。）を除く",
      "生活保護法の規定による生活扶助を受けている者", "障害者、未成年者、寡婦又はひとり親（これらの者の前年の合計所得金額が百三十五万円を超える場合を除く。）"]),
    ("L12", "PS§3.1 法295②", "chiho", A5, "本則 295", 2, None,
     ["分離課税に係る所得割につき前項第一号の規定を適用する場合", "退職手当等の支払を受けるべき日の属する年の一月一日の現況"]),
    ("L13", "PS§3.1・§7 法318", "chiho", A5, "本則 318", 1, None, ["個人の市町村民税の賦課期日は、当該年度の初日の属する年の一月一日とする"]),
    ("L14", "PS§3.1 民法4", "minpo", ["2026-11-09"], "本則 4", 1, None, ["年齢十八歳をもって、成年とする"]),
    ("L15", "PS§3.1 平成30年法律第59号附則1・2②", "minpo", ["2026-11-09"], "改正附則 平成三〇年六月二〇日法律第五九号", None, None,
     ["この法律は、平成三十四年四月一日から施行する", "この法律の施行の際に十八歳以上二十歳未満の者（次項に規定する者を除く。）は、施行日において成年に達するものとする"]),
    ("L16", "PS§4.1 法292②", "chiho", A3, "本則 292", 2, None,
     ["同一生計配偶者に該当し、かつ、他の市町村民税の納税義務者の扶養親族にも該当する場合には、その配偶者は、政令で定めるところにより、これらのうちいずれか一にのみ該当するものとみなす"]),
    ("L17", "PS§4.1 法292③", "chiho", A3, "本則 292", 3, None,
     ["第三百十四条の二第一項第十号の二に規定する生計を一にする配偶者に該当し、かつ、他の市町村民税の納税義務者の特定親族"]),
    ("L18", "PS§4.1 法292④", "chiho", A3, "本則 292", 4, None,
     ["二以上の市町村民税の納税義務者の扶養親族又は特定親族に該当する者がある場合には、その者は、政令で定めるところにより、これらの納税義務者のうちいずれか一の納税義務者の扶養親族又は特定親族にのみ該当するものとみなす"]),
    ("L19", "PS§4.1 旧版（2025-12-31）法292③は扶養親族だけ", "chiho", ["2025-12-31"], "本則 292", 3, None,
     ["二以上の市町村民税の納税義務者の扶養親族に該当する者がある場合には"]),
    ("L20", "PS§4.1 法23②〜④（道府県民税）", "chiho", ["2026-11-09"], "本則 23", None, None,
     ["他の道府県民税の納税義務者の扶養親族にも該当する場合", "他の道府県民税の納税義務者の特定親族", "二以上の道府県民税の納税義務者の扶養親族又は特定親族に該当する者がある場合"]),
    ("L21", "PS§4.1 令7の3の5②", "chiho-rei", ["2026-11-09"], "本則 7_3_5", 2, None,
     ["前年の法第三十二条第一項の総所得金額、退職所得金額及び山林所得金額の合計額が最も大きいもの"]),
    ("L22", "PS§4.2 令46の5①", "chiho-rei", A3, "本則 46_5", 1, None,
     ["法第三百十七条の二第一項の申告書を提出する義務を有する者にあつては当該申告書",
      "給与所得等以外の所得を有しなかつた者にあつては法第三百十七条の六第一項の給与支払報告書又は同条第四項の公的年金等支払報告書に記載されたところによる",
      "申請書を賦課期日現在の住所所在地の市町村長に提出したときは、当該申請書に記載されたところによる"]),
    ("L23", "PS§4.2 令46の5②", "chiho-rei", A3, "本則 46_5", 2, None,
     ["当該二以上の納税義務者のうち前年の法第三百十三条第一項の総所得金額、退職所得金額及び山林所得金額の合計額が最も大きいものの扶養親族又は特定親族とする"]),
    ("L24", "PS§4.2 令46の3①（給与所得等以外の所得を有しなかつた者）", "chiho-rei", ["2026-11-09"], "本則 46_3", 1, None,
     ["一月一日現在において", "給与所得以外の所得又は公的年金等に係る所得以外の所得を有しなかつたもの", "給与所得等以外の所得を有しなかつた者"]),
    ("L25", "PS§4.2 令46の3②", "chiho-rei", ["2026-11-09"], "本則 46_3", 2, None, ["その夫又は妻である市町村民税の納税義務者の同一生計配偶者とする"]),
    ("L26", "PS§4.2 令46の4②", "chiho-rei", ["2026-11-09"], "本則 46_4", 2, None, ["その夫又は妻である市町村民税の納税義務者の特別控除対象配偶者とする"]),
    ("L27", "PS§4.2 旧版 令46の4＝扶養親族の所属", "chiho-rei", ["2025-12-31"], "本則 46_4", None, None, ["（二以上の納税義務者がある場合の扶養親族の所属）"]),
    ("L28", "PS§4.2 所令219②", "shotoku-rei", ["2026-11-09"], "本則 219", 2, None,
     ["その年において既に一の居住者が申告書等の記載によりその扶養親族又は特定親族としている場合には", "最も大きい居住者の扶養親族又は特定親族とする"]),
    ("L29", "PS§4.2・§6.1 法317の3", "chiho", ["2026-11-09"], "本則 317_3", None, None,
     ["前年分の所得税につき所得税法第二条第一項第三十七号の確定申告書", "（政令で定める場合を除く。）",
      "当該確定申告書が提出された日に前条第一項から第四項までの規定による申告書が提出されたものとみなす",
      "同条第一項から第四項までの規定による申告書に記載されたものとみなす", "市町村民税の賦課徴収につき必要な事項を付記しなければならない"]),
    ("L30", "PS§5 法292①九 58万（令和8年度）", "chiho", ["2026-01-01"], "本則 292", 1, 9, ["前年の合計所得金額が五十八万円以下である者"]),
    ("L31", "PS§5 法292①九 62万（令和9年度）", "chiho", ["2027-01-01", "2028-01-01"], "本則 292", 1, 9, ["前年の合計所得金額が六十二万円以下である者"]),
    ("L32", "PS§5 法292①七 58万", "chiho", ["2026-01-01"], "本則 292", 1, 7, ["の合計所得金額が五十八万円以下である者"]),
    ("L33", "PS§5 法292①七 62万", "chiho", ["2027-01-01"], "本則 292", 1, 7, ["の合計所得金額が六十二万円以下である者"]),
    ("L34", "PS§5 法314の2①十一", "chiho", R89, "本則 314_2", 1, 11,
     ["各控除対象扶養親族につき三十三万円", "年齢十九歳以上二十三歳未満の者をいう", "四十五万円", "年齢七十歳以上の者をいう", "三十八万円",
      "居住者年齢十六歳以上の者", "非居住者年齢十六歳以上三十歳未満の者及び年齢七十歳以上の者並びに年齢三十歳以上七十歳未満の者"]),
    ("L35", "PS§5 法314の2④ 同居老親等", "chiho", R89, "本則 314_2", 4, None, ["第一項第十一号の金額は、四十五万円とする"]),
    ("L36", "PS§5 法314の2①十二 特定親族", "chiho", R89, "本則 314_2", 1, 12,
     ["自己と生計を一にする年齢十九歳以上二十三歳未満の親族（自己の配偶者を除く。）", "前年の合計所得金額が百二十三万円以下であるものに限る。）で控除対象扶養親族に該当しないもの",
      "前年の合計所得金額が九十五万円以下である特定親族四十五万円",
      "六十三万円から当該特定親族の前年の合計所得金額のうち八十四万一円を超える部分の金額に二を乗じた金額",
      "十万円の整数倍の金額から八万円を控除した金額で当該乗じた金額に満たないもののうち最も多い金額",
      "百十五万円を超え百二十万円以下である特定親族六万円", "百二十万円を超える特定親族三万円"]),
    ("L37", "PS§5 法314の2①九 勤労学生 26万", "chiho", R89, "本則 314_2", 1, 9, ["勤労学生である所得割の納税義務者二十六万円"]),
    ("L38", "PS§5 法314の2⑨ 勤労学生の準用と読替え", "chiho", R89, "本則 314_2", 9, None,
     ["所得税法第二条第一項第三十二号の規定は、第一項第九号及び第三百十四条の六の勤労学生の意義について準用する", "「合計所得金額が」とあるのは「当該年度の初日の属する年の前年"]),
    ("L39", "PS§5 所得税法2①三十二 85万", "shotoku", ["2025-12-31"], "本則 2", 1, 32, ["合計所得金額が八十五万円以下であり", "給与所得等以外の所得に係る部分の金額が十万円以下"]),
    ("L40", "PS§5 所得税法2①三十二 89万", "shotoku", ["2026-12-01"], "本則 2", 1, 32, ["合計所得金額が八十九万円以下であり", "給与所得等以外の所得に係る部分の金額が十万円以下"]),
    ("L41", "PS§5 法314の2② 基礎控除", "chiho", R89, "本則 314_2", 2, None,
     ["二千四百万円以下である場合四十三万円", "二千四百五十万円以下である場合二十九万円", "二千五百万円以下である場合十五万円"]),
    ("L42", "PS§5 法314の2①八の二 ひとり親 30万", "chiho", R89, "本則 314_2", 1, "8_2", ["ひとり親である所得割の納税義務者三十万円"]),
    ("L43", "PS§5 法314の2①八の二 ひとり親 33万（2028-01-01）", "chiho", ["2028-01-01"], "本則 314_2", 1, "8_2", ["ひとり親である所得割の納税義務者三十三万円"]),
    ("L44", "PS§5 法314の2⑧ 判定の時点", "chiho", R89, "本則 314_2", 8, None,
     ["勤労学生であるかどうか", "特定親族であるかどうかの判定は、前年の十二月三十一日（前年の中途においてその者が死亡した場合には、その死亡の時）の現況による"]),
    ("L45", "PS§5 令和7年法律第7号附則1①一・8①②", "chiho", ["2026-11-09"], "改正附則 令和七年三月三一日法律第七号", None, None,
     ["令和八年度分の個人の市町村民税に係る申告書の提出に係る新法第三百十七条の二第一項の規定の適用については、同項ただし書中「特定親族特別控除額（特定親族（前年の合計所得金額が八十五万円以下であるものに限る。）に係るものを除く。）」とあるのは、「特定親族特別控除額」とする",
      "令和八年度以後の年度分の個人の市町村民税について適用し", "令和八年一月一日"]),
    ("L46", "PS§5・§7 法292⑤", "chiho", A3, "本則 292", 5, None,
     ["市町村民税について所得税法その他の所得税に関する法令を引用する場合", "前年の所得について適用されたものをいうものとする"]),
    ("L47", "PS§6.1 法317の2①", "chiho", ["2026-11-09"], "本則 317_2", 1, None,
     ["三月十五日までに", "賦課期日現在における住所所在地の市町村長に提出しなければならない",
      "給与支払報告書又は公的年金等支払報告書を提出する義務がある者から一月一日現在において",
      "前年中において給与所得以外の所得又は公的年金等に係る所得以外の所得を有しなかつたもの（公的年金等に係る所得以外の所得を有しなかつた者で",
      "特定親族特別控除額（特定親族（前年の合計所得金額が八十五万円以下であるものに限る。）に係るものを除く。）",
      "所得割の納税義務を負わないと認められる者のうち当該市町村の条例で定めるものについては、この限りでない"]),
    ("L48", "PS§6.1 法317の2②③④", "chiho", ["2026-11-09"], "本則 317_2", None, None,
     ["一月三十一日までに提出されなかつた場合",
      "雑損控除額若しくは医療費控除額の控除、第三百十三条第八項に規定する純損失の金額の控除、同条第九項に規定する純損失若しくは雑損失の金額の控除又は寄附金税額控除額の控除を受けようとする場合には、三月十五日までに",
      "前年中において純損失又は雑損失の金額がある場合には、三月十五日までに同項の申告書を提出することができる"]),
    ("L49", "PS§6.1 法317の6①③", "chiho", ["2026-11-09"], "本則 317_6", None, None,
     ["一月一日現在において給与の支払をする者", "所得税法第百八十三条の規定により所得税を徴収する義務があるものは、同月三十一日までに",
      "支払を受けた給与の金額の総額が三十万円以下である者については、この限りでない"]),
    ("L50", "PS§6.1 令48の9の7", "chiho-rei", A5, "本則 48_9_7", None, None, ["第八条の二に規定する社会保険料の金額とする"]),
    ("L51", "（PS§6.1・§9 で「分からない」とした）令8の2 の中身", "chiho-rei", ["2026-11-09"], "本則 8_2", None, None,
     ["所得税法第二百三条の五第一号の規定により公的年金等から控除される同号に規定する社会保険料の金額とする"]),
    ("L52", "PS§6.1 法45の2①", "chiho", ["2026-11-09"], "本則 45_2", 1, None, ["第三百十七条の二第一項の市町村民税に関する申告書と併せて、賦課期日現在における住所所在地の市町村長に提出しなければならない"]),
    ("L53", "PS§7 法292①七 前年の定義", "chiho", ["2026-11-09"], "本則 292", 1, 7, ["当該年度の初日の属する年の前年（以下この条、第二百九十五条、第三百十三条から第三百十七条の三まで"]),
    ("L54", "PS§7 法313②", "chiho", ["2026-11-09", "2027-01-01"], "本則 313", 2, None,
     ["所得税法その他の所得税に関する法令の規定による所得税法第二十二条第二項又は第三項の総所得金額、退職所得金額又は山林所得金額の計算の例により算定する"]),
    ("L55", "PS§7 措法29の4①②", "sochi", ["2026-12-01"], "本則 29_4", None, None,
     ["令和八年又は令和九年において", "収入金額が二百二十万円以下である場合", "七十四万円（当該収入金額が七十四万円に満たない場合には、当該収入金額に相当する金額）とする",
      "収入金額が六十九万千円以上二百二十万円未満である場合"]),
    ("L56", "PS§7 所得税法28④", "shotoku", ["2025-12-31", "2026-12-01"], "本則 28", 4, None, ["収入金額が六百六十万円未満である場合", "別表第五"]),
    ("L57", "M§3.2 法292①六（2026-11-09）は措法29の4＝退職手当等", "chiho", ["2026-11-09"], "本則 292", 1, 6, ["租税特別措置法第二十九条の四において退職手当等とみなされる金額"]),
    ("L58", "M§3.2 法292①六（2027-01-01）は措法29の5", "chiho", ["2027-01-01"], "本則 292", 1, 6, ["租税特別措置法第二十九条の五において退職手当等とみなされる金額"]),
    ("L59", "M§3.2 措法29の4（2026-11-09）＝退職勤労者の未払賃金", "sochi", ["2026-11-09"], "本則 29_4", None, None, ["（退職勤労者が弁済を受ける未払賃金に係る課税の特例）"]),
    ("L60", "H3 法294② 住所＝住民基本台帳", "chiho", ["2026-11-09"], "本則 294", 2, None, ["当該市町村の住民基本台帳に記録されている者をいう"]),
    ("L61", "I7 令和8年法律第2号附則1②⑥・11②", "chiho", ["2027-01-01"], "改正附則 令和八年三月三一日法律第二号", None, None,
     ["新法第二百九十二条第一項（第七号及び第九号に係る部分に限る。）の規定は、令和九年度以後の年度分の個人の市町村民税について適用し",
      "第二百九十二条第一項第六号、第七号及び第九号並びに第三百十四条の二第一項第六号の改正規定",
      "第三百十四条の二第一項第八号の二及び第三百二十一条の八の改正規定"]),
    ("L62", "I1 所得税法2①三十四 扶養親族 62万（2026-12-01 版）", "shotoku", ["2026-12-01"], "本則 2", 1, 34, ["合計所得金額が六十二万円以下である者"]),
    ("L63", "I2 法附則3の3⑤（境目をわずかに超える者の所得割の調整）", "chiho", ["2026-01-01", "2027-01-01"], "原始附則 3_3", 5, None,
     ["第一号に掲げる額から第二号に掲げる額と第三号に掲げる額との合計額を控除した金額を超えることとなるときは",
      "当該超える金額に第二号に掲げる額を同号に掲げる額と第三号に掲げる額との合計額で除して得た数値を乗じて得た金額を、当該納税義務者の第三百十四条の三及び第三百十四条の六の規定を適用した場合の所得割の額から控除する"]),
    ("L64", "H1・I7 令和8年法律第2号：本体は 2026-04-01 施行、個人の市町村民税は令和8年度分から適用（附則1・11①）", "chiho", ["2026-11-09"],
     "改正附則 令和八年三月三一日法律第二号", None, None,
     ["この法律は、令和八年四月一日から施行する",
      "別段の定めがあるものを除き、新法の規定中個人の市町村民税に関する部分（新法第三百三十二条の二の規定を除く。）は、令和八年度以後の年度分の個人の市町村民税について適用し"]),
]

# 改正附則（AmendLawNum）の本文を JSON から直接読んで照合するもの（LAWS で抜き出していない改正法）
AMEND_CLAIMS = [
    ("A01", "I1・H7 令和8年法律第12号附則2（所得税法2①三十二〜三十四は令和8年分から）・附則3（第28条は令和8年分から）", "shotoku", "2026-12-01",
     "令和八年三月三一日法律第一二号",
     ["第二条第一項（第三十二号（ロに係る部分を除く。）、第三十三号及び第三十四号に係る部分に限る。）の規定は、令和八年分以後の所得税について適用し",
      "新所得税法第二十八条の規定は、令和八年分以後の所得税について適用し", "令和八年十二月一日"]),
]

# 版の間で同じかどうか（M§3.1 の表）。担当の表の値を並べ、自分の抜き出しで再計算した値と比べる。
CHANGE_TABLE = {
    "chiho": (A5, {"24_5": "○○○○", "292": "××××", "295": "○○○○", "310": "○○○○", "313": "○×○○", "314_2": "××××", "317_2": "×○○○",
                   "317_3": "○○○○", "317_6": "○○○○", "318": "○○○○", "附則3_3": "○××○"}),
    "chiho-rei": (A5, {"46_3": "×○○○", "46_4": "×○○○", "46_5": "－○○○", "47_3": "○○○○", "48_9_7": "○○○○"}),
    "chiho-ki": (A3, {"9_21": "○○"}),
}


def cmd_check():
    rows, ok_all = [], True
    for cid, where, short, asofs, sec, pn, inum, needles in CLAIMS:
        for asof in asofs:
            t = law_sections(short, asof).get(sec, "")
            if pn is not None:
                t = para(t, pn)
            if inum is not None:
                t = item(t, inum)
            T = nfkc(t)
            miss = [n for n in needles if nfkc(n) not in T]
            ok = bool(T) and not miss
            ok_all &= ok
            rows.append({"id": cid, "where": where, "law": short, "asof": asof, "section": sec, "para": pn, "item": inum, "ok": ok, "missing": miss})
    for cid, where, short, asof, an, needles in AMEND_CLAIMS:
        _, _, _, amend = law_articles(short, asof)
        T = nfkc("".join(flat(s) for s in amend if s.get("attr", {}).get("AmendLawNum") == an))
        miss = [n for n in needles if nfkc(n) not in T]
        ok = bool(T) and not miss
        ok_all &= ok
        rows.append({"id": cid, "where": where, "law": short, "asof": asof, "section": f"改正附則 {an}", "para": None, "item": None, "ok": ok, "missing": miss})
    chg = []
    for short, (asofs, expect) in CHANGE_TABLE.items():
        texts = {}
        for asof in asofs:
            _, main, orig, _ = law_articles(short, asof)
            bm = {a["attr"].get("Num"): a for a in main}
            bo = {a["attr"].get("Num"): a for a in orig}
            texts[asof] = {}
            for k in expect:
                if k.startswith("附則"):
                    texts[asof][k] = render_article(bo[k[2:]]) if k[2:] in bo else None
                else:
                    texts[asof][k] = render_article(bm[k]) if k in bm else None
        for k, exp in expect.items():
            got, diffs = "", []
            for x, y in zip(asofs, asofs[1:]):
                a, b = texts[x][k], texts[y][k]
                got += "－" if a is None or b is None else ("○" if a == b else "×")
                if a and b and a != b:
                    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
                    for op, i1, i2, j1, j2 in sm.get_opcodes():
                        if op != "equal":
                            diffs.append(f"{x}→{y}: …{a[max(0, i1 - 25):i1]}【{a[i1:i2]} → {b[j1:j2]}】{a[i2:i2 + 15]}…".replace("\n", "⏎"))
            chg.append({"law": short, "article": k, "expected": exp, "got": got, "match": exp == got, "diffs": diffs})
    _, main, orig, amend = law_articles("chiho", "2026-11-09")
    words = {
        "未成年者_本則_2026-11-09": [(a["attr"].get("Num"), flat(a).count("未成年者")) for a in main if "未成年者" in flat(a)],
        "未成年者_原始附則": sum(flat(a).count("未成年者") for a in orig),
        "未成年者口座_原始附則": sum(flat(a).count("未成年者口座") for a in orig),
        "未成年者_改正附則": sum(flat(s).count("未成年者") for s in amend),
        "「未成年者」とは": sum(flat(a).count("「未成年者」とは") for a in main + orig),
    }
    _, main27, orig27, amend27 = law_articles("chiho", "2027-01-01")
    words["29の4_本則_2027-01-01"] = [a["attr"].get("Num") for a in main27 if "第二十九条の四" in flat(a)]
    words["29の4_原始附則_2027-01-01"] = [(a["attr"].get("Num"), "".join(flat(c) for c in kids(a, "ArticleCaption")))
                                       for a in orig27 if "第二十九条の四" in flat(a)]
    words["29の4_改正附則_2027-01-01"] = [(s["attr"].get("AmendLawNum"), [flat(s)[max(0, m.start() - 30):m.end() + 15] for m in re.finditer("第二十九条の四", flat(s))])
                                       for s in amend27 if "第二十九条の四" in flat(s)]
    # 法第317条の3第1項の「政令で定める場合」：施行令（asof 2026-11-09）の本則・原始附則で「三百十七条の三」を含む条（の二・の三 を除く）
    _, rmain, rorig, _ = law_articles("chiho-rei", "2026-11-09")
    words["施行令で法317の3（の二・の三を除く）を引く条"] = [a["attr"].get("Num") for a in rmain + rorig
                                                if re.search(r"三百十七条の三(?!の[二三])", flat(a))]
    # 法第292条第1項の号ごとの版の間の変化（M§3.2「第3号・第4号」の確認）
    items292 = {}
    for i in (3, 4, "4_2", 6, 7, 9, 13):
        vals = [item(para(law_sections("chiho", a)["本則 292"], 1), i) for a in A5]
        items292[str(i)] = "".join("○" if x == y else "×" for x, y in zip(vals, vals[1:]))
    words["法292①の号ごとの変化（2025-12-31→…→2028-01-01）"] = items292
    res = {"claims": rows, "all_ok": ok_all, "change_table": chg, "words": words}
    (OUT / "law_checks.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# 条文の照合（IMPL_juminzei_verify.py check）", "", f"- 照合 {len(rows)} 件（主張 {len(CLAIMS)} 個 × 版）、すべて一致: {ok_all}", "",
          "| ID | 主張 | 法令 | asof | 箇所 | 結果 | 見つからない文字列 |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        loc = r["section"] + (f" 第{r['para']}項" if r["para"] else "") + (f" 第{r['item']}号" if r["item"] else "")
        md.append(f"| {r['id']} | {r['where']} | {r['law']} | {r['asof']} | {loc} | {'○' if r['ok'] else '×'} | {' / '.join(r['missing'])} |")
    md += ["", "## 版の間の変化（M§3.1 の表との比較）", "", "| 法令 | 条 | 担当の表 | 再計算 | 一致 |", "|---|---|---|---|---|"]
    for c in chg:
        md.append(f"| {c['law']} | {c['article']} | {c['expected']} | {c['got']} | {'○' if c['match'] else '×'} |")
    md += ["", "### 変化の中身（文字単位の差分）", ""]
    for c in chg:
        for d in c["diffs"]:
            md.append(f"- {c['law']} {c['article']} {d[:400]}")
    md += ["", "## 語の出現", "", "```", json.dumps(words, ensure_ascii=False, indent=1), "```", ""]
    (OUT / "law_checks.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md[:4]))
    print("claims ng:", [(r["id"], r["asof"], r["missing"]) for r in rows if not r["ok"]])
    print("change ng:", [(c["law"], c["article"], c["expected"], c["got"]) for c in chg if not c["match"]])
    print(json.dumps(words, ensure_ascii=False)[:2000])


# ---------------------------------------------------------------- 境目の再計算（担当の計算とは別の書き方）
def z2i(s):
    s = unicodedata.normalize("NFKC", s).replace(",", "").strip()
    return int(s) if re.fullmatch(r"\d+", s) else None


def beppyo5_bins(asof):
    """別表第五の行を (下限, 上限, 種類, 値) の列にする。各行は「以上・未満・値」の3つ組が最大3つ並ぶ（先頭の行だけ「X円未満・値」の2つ）。"""
    d = json.loads((OUT / "laws" / f"shotoku_appdx_{asof}.json").read_text(encoding="utf-8"))
    bins = []
    for r in d["rows"]:
        c = [unicodedata.normalize("NFKC", x).replace(",", "").strip() for x in r]
        if len(c) == 6 or all(x in ("円", "") for x in c):
            continue  # 見出し行（給与等の金額…／以上・未満）と「円」の行、空行
        tk = [x for x in c if x]
        i = 0
        while i < len(tk):
            if m := re.fullmatch(r"(\d+)円未満", tk[i]):
                bins.append((0, int(m.group(1)), "fixed", z2i(tk[i + 1])))
                i += 2
                continue
            if re.fullmatch(r"\d+円", tk[i]):
                i += 1  # 2,000万円の行（年末調整用の欄。660万円未満の計算には使わない）
                continue
            lo, hi, v = z2i(tk[i]), z2i(tk[i + 1]), tk[i + 2]
            if lo is None or hi is None:
                raise SystemExit(f"読めない行: {r}")
            if z2i(v) is not None:
                bins.append((lo, hi, "fixed", z2i(v)))
            elif m := re.fullmatch(r"給与等の金額から(\d+)円を控除した金額", v):
                bins.append((lo, hi, "minus", int(m.group(1))))
            elif m := re.fullmatch(r"給与等の金額に(\d+)%を乗じて算出した金額から(\d+)円を控除した金額", v):
                bins.append((lo, hi, "pct", (int(m.group(1)), int(m.group(2)))))
            else:
                raise SystemExit(f"読めない値: {tk[i:i + 3]}")
            i += 3
    bins.sort()
    pos = 0
    for lo, hi, _, _ in bins:
        if lo >= 6_600_000:
            break
        assert lo == pos, (asof, pos, lo)
        pos = hi
    assert pos >= 6_600_000
    return bins


def table_value(kind, v, x):
    return v if kind == "fixed" else max(0, x - v) if kind == "minus" else x * v[0] // 100 - v[1]


def formula_kyuyo(nenbun, x):
    """所得税法第28条第3項（各版。cmd_calc の最初で文字列を確かめる）と、別表第五の作り方（4,000円刻みの下端で計算）から、
    表とは別に給与所得を計算する（照合用）。"""
    a = x // 4000 * 4000
    if nenbun == "令和7年分":  # 190万円以下 65万円、190万超360万以下 30%+8万、360万超660万以下 20%+44万
        if x < 651_000:
            return 0
        if x < 1_900_000:
            return x - 650_000
        if x < 3_600_000:
            return a * 7 // 10 - 80_000
        return a * 8 // 10 - 440_000
    if nenbun == "令和8年分":  # 360万以下 30%+8万（69万に満たないときは69万）、360万超660万以下 20%+44万
        if x < 691_000:
            return 0
        if x < 2_026_000:
            return x - 690_000
        if x < 2_028_000:  # 表では 2,026,000〜2,028,000 だけ 2,000 円幅の区間（下端 2,026,000 で計算した値）
            return 2_026_000 - 690_000
        if x < 3_600_000:
            return a - max(690_000, a * 3 // 10 + 80_000)
        return a * 8 // 10 - 440_000
    raise ValueError


def sochi_29_4(x):
    """措法第29条の4第2項（asof 2026-12-01。cmd_calc の最初で文字列を確かめる）。69万1千円以上220万円未満だけに使う。"""
    if x < 741_000:
        return 0
    if x < 2_191_000:
        return x - 740_000
    if x < 2_193_000:
        return 1_451_000
    if x < 2_196_000:
        return 1_453_000
    return 1_456_000


def cmd_calc():
    import array
    import bisect
    sochi = nfkc(law_sections("sochi", "2026-12-01")["本則 29_4"])
    for n in ["六十九万千円以上七十四万千円未満である場合には、当該給与等に係る給与所得の金額は、ないものとする",
              "七十四万千円以上二百十九万千円未満である場合には、当該給与等に係る給与所得の金額は、当該収入金額から七十四万円を控除した残額",
              "二百十九万千円以上二百十九万三千円未満である場合には、当該給与等に係る給与所得の金額は、百四十五万千円",
              "二百十九万三千円以上二百十九万六千円未満である場合には、当該給与等に係る給与所得の金額は、百四十五万三千円",
              "二百十九万六千円以上二百二十万円未満である場合には、当該給与等に係る給与所得の金額は、百四十五万六千円"]:
        assert nfkc(n) in sochi, n
    for asof, needles in (("2025-12-31", ["収入金額が百九十万円以下である場合六十五万円", "百九十万円を控除した金額の百分の三十",
                                          "百十六万円と当該収入金額から三百六十万円を控除した金額の百分の二十"]),
                          ("2026-12-01", ["八万円と当該収入金額の百分の三十に相当する金額との合計額（当該合計額が六十九万円に満たない場合には、六十九万円）",
                                          "百十六万円と当該収入金額から三百六十万円を控除した金額の百分の二十"])):
        t = nfkc(para(law_sections("shotoku", asof)["本則 28"], 3))
        for n in needles:
            assert nfkc(n) in t, (asof, n)
    out = {"beppyo5": {}, "formula_vs_table": {}, "nendo": {}, "published": [], "tokutei": [], "miseinen_dates": {}, "sendai": {}}
    tables = {"令和7年分": beppyo5_bins("2025-12-31"), "令和8年分": beppyo5_bins("2026-12-01")}
    G = {}
    for nenbun, bins in tables.items():
        out["beppyo5"][nenbun] = {"bins": len(bins), "first_two": bins[:2]}
        g = array.array("q", bytes(8 * 6_600_000))
        mism = []
        for lo, hi, kind, v in bins:
            if lo >= 6_600_000:
                break
            for x in range(lo, min(hi, 6_600_000)):
                tv = table_value(kind, v, x)
                if formula_kyuyo(nenbun, x) != tv and len(mism) < 20:
                    mism.append((x, tv, formula_kyuyo(nenbun, x)))
                g[x] = sochi_29_4(x) if (nenbun == "令和8年分" and 691_000 <= x < 2_200_000) else tv
        out["formula_vs_table"][nenbun] = mism
        assert all(g[i] <= g[i + 1] for i in range(len(g) - 1)), nenbun
        G[nenbun] = g
    for nenbun, lo in (("令和8年分", 2_200_000), ("令和7年分", 1_900_000)):
        bad = 0
        for x in range(lo, 6_600_000):
            A = (x // 4) // 1000 * 1000
            v = A * 28 // 10 - 80_000 if x < 3_600_000 else A * 32 // 10 - 440_000
            bad += v != G[nenbun][x]
        out["sendai"][nenbun] = {"from": lo, "to": 6_599_999, "mismatch": bad}

    def max_income(nenbun, limit):
        return bisect.bisect_right(G[nenbun], limit) - 1  # 給与所得 ≤ limit となる最大の収入（G は単調非減少）

    RATES = {1: (10, 10), 2: (9, 10), 3: (8, 10)}
    for nendo, nenbun in (("令和8年度", "令和7年分"), ("令和9年度", "令和8年分")):
        rows = []
        for n in range(5):
            r = {"n": n}
            for k, (a, b) in RATES.items():
                lim = 350_000 * a // b * (n + 1) + 100_000 + (210_000 * a // b if n else 0)
                r[f"均等割{k}級地"] = (lim, max_income(nenbun, lim))
            lim = 350_000 * (n + 1) + 100_000 + (320_000 if n else 0)
            r["所得割"] = (lim, max_income(nenbun, lim))
            rows.append(r)
        m135 = max_income(nenbun, 1_350_000)
        out["nendo"][nendo] = {"rows": rows, "135万": m135, "135万_次の1円の所得": G[nenbun][m135 + 1]}
    PUB = [("江戸川区", "令和8年度", "均等割1級地", [1_100_000, 1_660_000, 2_059_999, 2_559_999, 3_059_999]),
           ("江戸川区", "令和8年度", "所得割", [1_100_000, 1_770_000, 2_215_999, 2_715_999, 3_215_999]),
           ("柏市", "令和8年度", "均等割2級地", [1_065_000, 1_569_000, 1_884_000, 2_327_999, 2_779_999]),
           ("柏市", "令和8年度", "所得割", [1_100_000, 1_770_000, 2_215_999, 2_715_999, 3_215_999]),
           ("柏市", "令和9年度", "均等割2級地", [1_155_000, 1_659_000, 1_974_000, 2_210_000, 2_560_000]),
           ("柏市", "令和9年度", "所得割", [1_190_000, 1_860_000, 2_214_285, 2_714_285, 3_214_285]),
           ("神戸市（1級地として）", "令和9年度", "均等割1級地", [1_190_000, 1_750_000, None, None, None])]
    for who, nendo, kind, vals in PUB:
        for n, v in enumerate(vals):
            if v is not None:
                calc = out["nendo"][nendo]["rows"][n][kind][1]
                out["published"].append({"who": who, "nendo": nendo, "kind": kind, "n": n, "published": v, "calc": calc, "match": v == calc})
    for who, nendo, v in (("柏市", "令和8年度", 2_043_999), ("世田谷区（204万4千円未満）", "令和8年度", 2_043_999), ("柏市", "令和9年度", 2_090_000)):
        calc = out["nendo"][nendo]["135万"]
        out["published"].append({"who": who, "nendo": nendo, "kind": "135万", "n": "—", "published": v, "calc": calc, "match": v == calc})
    out["kashiwa_r9_kyuyo_shotoku"] = {str(x): G["令和8年分"][x] for x in (2_210_000, 2_327_999, 2_328_000, 2_560_000, 2_779_999, 2_780_000,
                                                                       2_214_285, 2_215_999, 2_216_000)}

    def tok(inc):  # 地方税法第314条の2第1項第12号（L36 で文字列を確認）。切り下げを算術で書く
        if inc <= 950_000:
            return 450_000
        if inc <= 1_150_000:
            v = 2 * (inc - 840_001)
            d = v if (v + 80_000) % 100_000 == 0 else ((v + 80_000) // 100_000) * 100_000 - 80_000
            return 630_000 - d
        if inc <= 1_200_000:
            return 60_000
        if inc <= 1_230_000:
            return 30_000
        return 0  # 123万円超は特定親族に当たらない
    cur, start = tok(580_001), 580_001
    for inc in range(580_002, 1_300_001):
        v = tok(inc)
        if v != cur:
            out["tokutei"].append((start, inc - 1, cur))
            start, cur = inc, v
    out["tokutei"].append((start, 1_300_000, cur))

    def age_end_of_day(birth, day):  # 年齢計算ニ関スル法律・民法143：誕生日の前日の終了で1歳加わる。day の終わりの時点の年齢
        try:
            ann = birth.replace(year=day.year)
        except ValueError:
            ann = datetime.date(day.year, 3, 1)
        y = day.year - birth.year
        return y if day >= ann - datetime.timedelta(days=1) else y - 1
    for y in (2023, 2026, 2027):
        day, b = datetime.date(y, 1, 1), datetime.date(y - 19, 1, 1)
        while age_end_of_day(b, day) >= 18:
            b += datetime.timedelta(days=1)
        out["miseinen_dates"][f"{y}-01-01 の終わりに18歳未満となる最初の生年月日"] = str(b)
    out["age_2008_01_02"] = {d: age_end_of_day(datetime.date(2008, 1, 2), datetime.date.fromisoformat(d)) for d in ("2025-12-31", "2026-01-01")}

    # 法附則第3条の3第5項（L63 で文字列を確認）を文言どおりに書き、境目 +1 円での調整後の市町村民税の所得割を見る（推測 I2 の訂正の確認）
    from fractions import Fraction

    def adjust_5(limit, S, Tm, Tp):
        """limit: 35万円×(n+1)+10万円(+32万円)、S: 総所得金額等（第1号）、Tm: 市町村民税の所得割（第2号）、Tp: 道府県民税の所得割（第3号）"""
        if limit > S - (Tm + Tp):
            return Tm - (limit - (S - (Tm + Tp))) * Fraction(Tm, Tm + Tp)
        return Fraction(Tm)
    ex = []
    for Tm, Tp in ((600, 400), (1_200, 800), (6, 4), (30_000, 20_000)):
        v = adjust_5(450_000, 450_001, Tm, Tp)
        ex.append({"S": 450_001, "limit": 450_000, "Tm": Tm, "Tp": Tp, "adjusted_Tm": str(v), "lt_1yen": v < 1})
    out["fusoku3_3_5_example"] = ex
    (OUT / "calc.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# 境目の再計算（IMPL_juminzei_verify.py calc）", "",
          f"- 別表第五の区間数: { {k: v['bins'] for k, v in out['beppyo5'].items()} }",
          f"- 所得税法第28条第3項の式（4,000円刻みの下端）と別表第五の不一致（先頭20件まで）: {out['formula_vs_table']}",
          f"- 仙台市の速算表の式と表の不一致の数: {out['sendai']}", ""]
    for nendo, y in out["nendo"].items():
        md += [f"## {nendo}", "", "| 人数 | 均等割1級地 | 給与収入 | 2級地 | 給与収入 | 3級地 | 給与収入 | 所得割 | 給与収入 |", "|---|---|---|---|---|---|---|---|---|"]
        for r in y["rows"]:
            md.append("| " + " | ".join([str(r["n"])] + [f"{r[k][0]:,} | {r[k][1]:,}" for k in ("均等割1級地", "均等割2級地", "均等割3級地", "所得割")]) + " |")
        md += ["", f"- 合計所得金額 135万円以下となる給与収入の上限: {y['135万']:,}（次の1円で給与所得 {y['135万_次の1円の所得']:,}）", ""]
    md += ["## 公表値との照合", "", "| 自治体 | 年度 | 区分 | 人数 | 公表 | 計算 | 一致 |", "|---|---|---|---|---|---|---|"]
    for p in out["published"]:
        md.append(f"| {p['who']} | {p['nendo']} | {p['kind']} | {p['n']} | {p['published']:,} | {p['calc']:,} | {'○' if p['match'] else '×'} |")
    md += ["", f"- 柏市 令和9年度の公表値などの給与所得（令和8年分）: {out['kashiwa_r9_kyuyo_shotoku']}", "", "## 特定親族特別控除の区間", "",
           "| 下限 | 上限 | 控除額 |", "|---|---|---|"] + [f"| {a:,} | {b:,} | {c:,} |" for a, b, c in out["tokutei"]]
    md += ["", f"- {out['miseinen_dates']}", f"- 2008-01-02 生まれの年齢（その日の終わり）: {out['age_2008_01_02']}",
           f"- 法附則第3条の3第5項：総所得金額等＝境目+1円のときの調整後の市町村民税の所得割: {out['fusoku3_3_5_example']}", ""]
    (OUT / "calc.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


# ---------------------------------------------------------------- 資料（自治体・総務省）の文字列の照合
WEBCLAIMS = [
    ("W01", "PS§1.6 札幌 第19条②", "sapporo_jorei", [
        "前年の合計所得金額が35万円にその者の同一生計配偶者及び扶養親族（年齢16歳未満の者及び第28条の３第14号に規定する控除対象扶養親族に限る。以下この項において同じ。）の数に１を加えた数を乗じて得た金額に10万円を加算して得た金額（その者が同一生計配偶者又は扶養親族を有する場合には、当該金額に21万円を加算した金額）以下である者に対しては、均等割を課さない"]),
    ("W02", "PS§1.6 札幌 第19条①", "sapporo_jorei", ["障害者、未成年者、寡婦又はひとり親（これらの者の前年の合計所得金額が135万円を超える場合を除く。）"]),
    ("W03", "PS§2.1 札幌 附則第3条の3", "sapporo_jorei", ["当分の間、市民税の所得割を課すべき者のうち", "32万円を加算した金額"]),
    ("W04", "PS§6.2 札幌 第30条①ただし書2〜4", "sapporo_jorei", [
        "前年の合計所得金額が第28条の３第15号アに定める基礎控除額以下である者",
        "青色事業専従者又は白色事業専従者で前年中において青色専従者給与額又は事業専従者控除額に係る給与所得以外の所得を有しなかつたもの",
        "賦課期日現在において生活保護法の規定による生活扶助を受けている者"]),
    ("W05", "（検証で発見）札幌 第28条の３第15号＝特定親族特別控除額、第16号＝基礎控除額", "sapporo_jorei", [
        "(15)　特定親族特別控除額", "ア　前年の合計所得金額が95万円以下である特定親族　45万円", "(16)　基礎控除額",
        "ア　納税義務者の前年の合計所得金額が2,400万円以下である場合　43万円"]),
    ("W06", "同上（未施行の改正を表示したページでも同じ）", "sapporo_jorei_misikou", [
        "前年の合計所得金額が第28条の３第15号アに定める基礎控除額以下である者", "(15)　特定親族特別控除額", "(16)　基礎控除額"]),
    ("W07", "PS§4.2 札幌 第30条⑦", "sapporo_jorei", [
        "第１項第１号に掲げる者は、その扶養親族について給与支払報告書又は公的年金等支払報告書に記載された扶養控除と異なる控除を受けようとする場合には、３月15日までに規則で定める様式による申請書を提出することができる"]),
    ("W08", "PS§6.2 札幌 第30条の2", "sapporo_jorei", ["当該確定申告書が提出された日に、前条第１項から第４項までの規定による申告書が提出されたものとみなす"]),
    ("W09", "PS§3.2 目黒区", "meguro", ["更新日：2022年12月28日", "賦課期日（その年の1月1日）時点で18歳未満（令和5年度の場合、平成17年1月3日以降に生まれたかた）"]),
    ("W10", "PS§3.2 さいたま市", "saitama", ["更新日付：2026年4月1日", "令和5年度の場合、平成17年1月3日以降に生まれた方が未成年（18歳未満）として扱われます"]),
    ("W11", "PS§3.2 横浜市港南区", "yokohama_konan", ["最終更新日 2024年9月18日", "平成14年１月３日以降に生まれた方", "平成17年１月３日以降に生まれた方"]),
    ("W12", "PS§3.2・§8.3 世田谷区", "setagaya", ["最終更新日 2026年6月18日", "給与収入になおすと、204万4千円未満",
                                             "35万円×(同一生計配偶者＋扶養親族数（年少扶養含む）＋1)＋31万円", "令和8年度以降", "35万円×（本人＋扶養親族等の数）＋42万円"]),
    ("W13", "PS§8.3・M§5.4 江戸川区", "edogawa", ["更新日：2026年2月4日", "（令和8年度賦課分～）", "1,660,000円以下", "2,059,999円以下", "1,770,000円以下",
                                                "2,215,999円以下", "3,215,999円以下"]),
    ("W14", "PS§3.2・§8.3・M§5.4 柏市", "kashiwa", ["更新日令和8(2026)年10月13日", "31万5千円×（本人と同一生計配偶者、扶養親族の合計人数）+10万円", "18万9千円",
                                                   "柏市は2級地に該当します", "給与の収入額では204万4千円未満", "給与の収入額では209万円未満", "2,043,999円", "2,090,000円",
                                                   "2,327,999円", "2,779,999円", "2,210,000円", "2,560,000円", "2,214,285円", "2,714,285円", "3,214,285円"]),
    ("W15", "PS§1.5・§7・§8.3 神戸市", "kobe", ["最終更新日：2026年10月23日", "119万円以下（改正前：110万円以下）", "前年中の合計所得金額が45万円以下",
                                               "給与収入が175万円以下の場合", "89万円以下", "85万円以下", "最低保証額が74万円"]),
    ("W16", "PS§7・§8.3・M§5.4 仙台市", "sendai", ["更新日：2026年10月29日", "給与所得の速算表（令和9年度及び令和10年度）",
                                                  "給与所得控除の最低控除額等の特例（租税特別措置法第29条の4）適用後", "2,200,000円から3,599,999円まで", "A×2.8-80,000円"]),
    ("W17", "PS§7・§8.3 千葉市", "chiba", ["更新日：2026年9月28日", "令和9年度分・10年度分の市民税・県民税に限り、さらに5万円引き上げる", "58万円から62万円（勤労学生控除を除く）"]),
    ("W18", "PS§7・§8.3 大阪府", "osaka_pref", ["更新日：2026年4月10日", "給与所得控除の最低保障額を74万円（現行:65万円）に引き上げます",
                                              "引上げ額9万円のうち、5万円は令和9年度分及び令和10年度分の2年",
                                              "ひとり親控除の控除額を33万円（現行:30万円）に引き上げます。（令和10年度分の個人住民税から適用します。）"]),
    ("W19", "PS§8.3 横浜市（令和8年度の改正）", "yokohama_r8", ["最終更新日 2026年4月27日"]),
]


def cmd_webcheck():
    rows = []
    for wid, where, name, needles in WEBCLAIMS:
        p = OUT / "web" / f"{name}.txt"
        t = nfkc(p.read_text(encoding="utf-8")) if p.exists() else ""
        miss = [n for n in needles if nfkc(n) not in t]
        rows.append({"id": wid, "where": where, "source": name, "ok": bool(t) and not miss, "missing": miss})
    # 総務省の一覧ページ：「（総税市第25号）」の通知の後に並ぶリンクの文字列と行き先（HTML を外から読むだけ）
    log = json.loads((OUT / "web_log.json").read_text(encoding="utf-8"))
    raw = (ROOT / log["download_dir"] / "soumu_ichiran04.html").read_bytes()
    s, _ = decode(raw, "")
    i = s.find("（総税市第25号）")
    links = re.findall(r'<a href="([^"]+)">\s*([^<]{1,40})', s[i:i + 1500])[:5]
    rows.append({"id": "W20", "where": "PS§8.2 令和8年の「改正後全文」＝001071661.pdf", "source": "soumu_ichiran04",
                 "ok": any(h.endswith("/001071661.pdf") and t.strip().startswith("改正後全文") for h, t in links), "missing": [], "links": links})
    (OUT / "web_checks.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# 資料の文字列の照合（IMPL_juminzei_verify.py webcheck）", "", "| ID | 主張 | 資料 | 結果 | 見つからない文字列・リンク |", "|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['id']} | {r['where']} | {r['source']} | {'○' if r['ok'] else '×'} | {' / '.join(r['missing']) or r.get('links', '')} |")
    (OUT / "web_checks.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "laws":
        cmd_laws()
    elif cmd == "web":
        cmd_web(set(sys.argv[2:]))
    elif cmd == "check":
        cmd_check()
    elif cmd == "calc":
        cmd_calc()
    elif cmd == "webcheck":
        cmd_webcheck()
    else:
        raise SystemExit(__doc__)



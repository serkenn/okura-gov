"""R3X_dai3go の独立した検証（反証役）：第3号被保険者の収入基準の根拠についての文書
docs/*/20261109_round3_dai3go-*.md に書かれた数値・番号・日付・URL を、一次情報を取得し直して機械的に確かめる。

実行（Windows、リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_dai3go_verify.py fetch <set名> [<set名> ...]
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_dai3go_verify.py fetch --list
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_dai3go_verify.py check

- 取得（fetch）：set ごとに新しい空のディレクトリ .work/downloads/<YYYYMMDD-HHMMSS>_R3X_dai3go_verify_<set>/ に置く（信頼できないデータ。
  その中でインタプリタやツールを実行しない）。リクエストの間は 1.5 秒。User-Agent は okura-gov-research/0.1。個人の情報は送らない。官報は取得しない。
  取得記録は scripts/results/R3X_dai3go_verify/fetch/<set>_<ts>.json、HTML・国会会議録 API の JSON から作ったテキストは
  scripts/results/R3X_dai3go_verify/text/<ts>_<set>/<id>.txt。
- HTML の抽出・取得の関数は scripts/R3X_dai3go_fetch.py から、e-Gov の条文の描画は scripts/R3X_dai3go_egov.py
  （元は scripts/R1_egov_articles.py）から、PDF の文字の取り出しは scripts/R3X_dai3go_pdftext.py から写した（import はしない。
  暗号化された PDF の復号は写していない。暗号化されていれば、そのことを記録して文字を取り出さない）。
- 検査（check）：ネットワークを使わない。各 set の最新の取得記録を読み、ダウンロードしたファイルを（リポジトリのルートから）パスで読む。
  出力 scripts/results/R3X_dai3go_verify/checks.json（項目ごとの結果）、checks.txt（読みやすい要約）、
  pdftext/<id>.tsv（PDF の頁ごとの文字）。
  検査の番号 V01〜 は docs/measurements/20261109_round3_dai3go-verification.md の番号。
"""
import glob
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
import zlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
WAIT = 1.5
OUT = ROOT / "scripts" / "results" / "R3X_dai3go_verify"
MAXOUT = 64 * 1024 * 1024


# ================================================================ URL の組み立て（R3X_dai3go_fetch.py の写し）
def mhlw_date_search(gengo, y, m, d, y2=None, m2=None, d2=None, shubetsu="", bango="", page=None):
    """厚労省 法令等データベース 通知の情報詳細検索（GET）。gengo: 3=昭和 4=平成 5=令和。"""
    y2, m2, d2 = y2 or y, m2 or m, d2 or d
    u = ("https://www.mhlw.go.jp/web/t_itemsrch_result?type=1"
         f"&startGengo={gengo}&yearFrom={y}&monthFrom={m}&dayFrom={d}"
         f"&endGengo={gengo}&yearTo={y2}&monthTo={m2}&dayTo={d2}"
         f"&shubetsu={urllib.parse.quote(shubetsu)}&bango={urllib.parse.quote(bango)}")
    if page is not None:
        u += f"&page={page}"
    return u


def mhlw_kw(keyword, page=None):
    u = "https://www.mhlw.go.jp/web/t_docsrch_keyword?" + urllib.parse.urlencode({"keyword": keyword, "type": "1", "mode": "0"})
    if page is not None:
        u += f"&page={page}"
    return u


def tdoc(data_id, page=1):
    return f"https://www.mhlw.go.jp/web/t_doc?dataId={data_id}&dataType=1&pageNo={page}"


def kokkai_speech(speech_id):
    """国会会議録検索システム 検索用API（発言単位）。発言ID（会議録ID_発言番号3桁）で1発言を引く。"""
    return "https://kokkai.ndl.go.jp/api/speech?" + urllib.parse.urlencode(
        {"speechID": speech_id, "maximumRecords": "1", "recordPacking": "json"})


def kokkai_search(any_words, frm, until, start=1, maxrec=100):
    """国会会議録検索システム 検索用API（発言単位出力）。R3X_dai3go_fetch.py の kokkai() の写し。"""
    q = {"any": any_words, "from": frm, "until": until, "startRecord": str(start),
         "maximumRecords": str(maxrec), "recordPacking": "json"}
    return "https://kokkai.ndl.go.jp/api/speech?" + urllib.parse.urlencode(q)


EGOV = "https://laws.e-gov.go.jp/api/2"
SHINSA = "https://www.mhlw.go.jp/topics/bukyoku/shinsa/syakai/"
TODAY = "2026-11-11"

SETS = {
    # 文書が引用した PDF（裁決、年金局の講義資料・検討会資料、機構の疑義照会回答）
    "v_pdf": {
        "shinsa_r02_03_15_01": SHINSA + "dl/05-r02_03/15_01.pdf",
        "shinsa_r02_03_06_04": SHINSA + "dl/05-r02_03/06_04.pdf",
        "shinsa_r02_03_06_05": SHINSA + "dl/05-r02_03/06_05.pdf",
        "shinsa_r02_03_06_10": SHINSA + "dl/05-r02_03/06_10.pdf",
        "shinsa_r02_03_06_11": SHINSA + "dl/05-r02_03/06_11.pdf",
        "shinsa_r04_05_07_02": SHINSA + "dl/05-r04_05/07_02.pdf",
        "live_0000086586": "https://www.mhlw.go.jp/file/06-Seisakujouhou-12500000-Nenkinkyoku/0000086586.pdf",
        "kt2_001746546": "https://www.mhlw.go.jp/content/12500000/001746546.pdf",
        "gigi_kounen_tekiyou": "https://www.nenkin.go.jp/service/seidozenpan/gigishokai.files/kounen_tekiyou.pdf",
    },
    # 厚労省 法令等データベースの通知の本文と、検討会の議事録・資料一覧
    "v_html": {
        "tdoc_00tb1690_S61": tdoc("00tb1690"),
        "tdoc_00tb1695_S61U": tdoc("00tb1695"),
        "tdoc_00tb1174_S61_12": tdoc("00tb1174"),
        "tdoc_00tb1694_S61_17": tdoc("00tb1694"),
        "tdoc_00tb5871_H22_p1": tdoc("00tb5871", 1),
        "tdoc_00tb5871_H22_p2": tdoc("00tb5871", 2),
        "tdoc_00tb5871_H22_p3": tdoc("00tb5871", 3),
        "tdoc_00tb0141_H050407": tdoc("00tb0141"),
        "tdoc_00ta3218_H050331": tdoc("00ta3218"),
        "tdoc_00tb0189_S52": tdoc("00tb0189"),
        "tdoc_00tc9348_R7_rodo": tdoc("00tc9348"),
        "tdoc_00tc9249_R7_1923": tdoc("00tc9249"),
        "kt_gijiroku": "https://www.mhlw.go.jp/stf/newpage_76904.html",
        "kt_page": "https://www.mhlw.go.jp/stf/newpage_75888.html",
    },
    # 同：本文検索「被扶養配偶者」「国民年金第三号被保険者 収入」に出た年金の事業運営・適用促進などの通知（第3号の収入の金額を書いているかを見る）
    "v_html2": {
        "tdoc_00tb1334_H03_chobun1099": tdoc("00tb1334"),
        "tdoc_00tb1742_H06_chobun1411": tdoc("00tb1742"),
        "tdoc_00tb1743_H06_chobun1412": tdoc("00tb1743"),
        "tdoc_00ta3625_H07_chobun1966": tdoc("00ta3625"),
        "tdoc_00ta3619_H07_chobun1935": tdoc("00ta3619"),
        "tdoc_00tb1770_H11_chobun894": tdoc("00tb1770"),
        "tdoc_00tb4433_H17_420001": tdoc("00tb4433"),
        "tdoc_00tb4191_H19_1026001": tdoc("00tb4191"),
        "tdoc_00tb4164_H20_306001": tdoc("00tb4164"),
    },
    # 同 情報詳細検索（日付・種別・番号）
    "v_search": dict(
        **{f"H05_chohohatsu_{n}": mhlw_date_search(4, 5, 1, 1, 5, 12, 31, shubetsu="庁保発", bango=str(n)) for n in range(1, 14)},
        **{
            # 検索の仕様の確かめ：連名の通知の2つ目の種別・番号でも引けるか（S52 は「保発第9号・庁保発第9号」の連名）
            "S52_chohohatsu_9": mhlw_date_search(3, 52, 1, 1, 52, 12, 31, shubetsu="庁保発", bango="9"),
            "S52_hohatsu_9": mhlw_date_search(3, 52, 1, 1, 52, 12, 31, shubetsu="保発", bango="9"),
            "S61_chohohatsu_13": mhlw_date_search(3, 61, 1, 1, 61, 12, 31, shubetsu="庁保発", bango="13"),
            "H050301_0331_p0": mhlw_date_search(4, 5, 3, 1, 5, 3, 31),
            "H050301_0331_p1": mhlw_date_search(4, 5, 3, 1, 5, 3, 31, page=1),
            "H050301_0331_p2": mhlw_date_search(4, 5, 3, 1, 5, 3, 31, page=2),
            "H050315": mhlw_date_search(4, 5, 3, 15),
            "H050305": mhlw_date_search(4, 5, 3, 5),
            "H150324": mhlw_date_search(4, 15, 3, 24),
            "H15_chobunhatsu_798": mhlw_date_search(4, 15, 1, 1, 15, 12, 31, shubetsu="庁文発", bango="798"),
            "H05_chohohatsu_only": mhlw_date_search(4, 5, 1, 1, 5, 12, 31, shubetsu="庁保発"),
        }),
    # 同 本文検索（件数は1頁目に出る）
    "v_kw": {
        "kw_nintei_kijun": mhlw_kw("被扶養配偶者の認定基準"),
        "kw_hifuyo_haigusha_p0": mhlw_kw("被扶養配偶者"),
        "kw_hifuyo_haigusha_p1": mhlw_kw("被扶養配偶者", page=1),
        "kw_hifuyo_haigusha_p2": mhlw_kw("被扶養配偶者", page=2),
        "kw_hifuyo_haigusha_p3": mhlw_kw("被扶養配偶者", page=3),
        "kw_hifuyo_haigusha_nintei": mhlw_kw("被扶養配偶者の認定"),
        "kw_chohohatsu13": mhlw_kw("庁保発第一三号"),
        "kw_dai3go_nintei": mhlw_kw("第三号被保険者の認定"),
        "kw_dai3go_nenkan_shunyu": mhlw_kw("第三号被保険者 年間収入"),
        "kw_kokunen_dai3go_shunyu": mhlw_kw("国民年金第三号被保険者 収入"),
        "kw_shunyu_nintei": mhlw_kw("収入がある者についての被扶養者の認定"),
        "kw_nintei_kijun_ichibu": mhlw_kw("被扶養配偶者の認定基準の一部"),
        "kw_nintei_kijun_kaisei": mhlw_kw("被扶養配偶者の認定基準の改正"),
        "kw_H050315": mhlw_kw("平成五年三月一五日"),
        "kw_chohohatsu5_p0": mhlw_kw("庁保発第五号"),
        "kw_chohohatsu5_p1": mhlw_kw("庁保発第五号", page=1),
        "kw_chobunhatsu798": mhlw_kw("庁文発第七九八号"),
    },
    # 国会会議録（文書 §4 の8発言と、質問の2発言、N8 の残りの発言）
    "v_kokkai": {f"kk_{sid}": kokkai_speech(sid) for sid in [
        "112605272X00219930305_069", "112605272X00219930305_070", "112605272X00219930305_071",
        "112604629X00619930309_070", "112605289X01519930604_089",
        "113104237X00719941026_037", "113114237X00519941031_050",
        "115414260X00520020328_057", "115414260X00620020416_139", "115414260X00620020416_140",
        "121105267X00120230220_294"]},
    # 同（追加）：担当の実測 §2.3 の検索12件の件数（numberOfRecords）を取り直す（URL の作り方は R3X_dai3go_fetch.py の写し）
    "v_kokkai_search": {
        "kk_hifuyo_nintei_S61_H06": kokkai_search("被扶養配偶者 認定基準", "1985-01-01", "1994-12-31"),
        "kk_dai3go_130_H04_H06": kokkai_search("第三号被保険者 百三十万円", "1992-01-01", "1994-12-31"),
        "kk_dai3go_kijun_all": kokkai_search("第三号被保険者 認定基準 通知", "1985-01-01", "2026-11-08"),
        "kk_hifuyo_haigusha_nintei_all": kokkai_search("被扶養配偶者の認定", "1985-01-01", "2026-11-08"),
        "kk_H140416_sangiin_kosei": "https://kokkai.ndl.go.jp/api/speech?" + urllib.parse.urlencode(
            {"issueID": "115414260X00620020416", "any": "被扶養配偶者", "maximumRecords": "100", "recordPacking": "json"}),
        "kk_hifuyo_130_H04_H06": kokkai_search("被扶養者 百三十万円", "1992-01-01", "1994-12-31"),
        "kk_hifuyo_kijun_hikiage_S62_H06": kokkai_search("被扶養者 認定基準 引き上げ", "1987-01-01", "1994-12-31"),
        "kk_dai3go_shunyu_kijun_all": kokkai_search("第三号被保険者 収入基準", "1985-01-01", "2026-11-08"),
        "kk_dai3go_hifuyo_nintei_kijun_all": kokkai_search("第三号被保険者 被扶養配偶者 認定", "1985-01-01", "2026-11-08"),
        "kk_H050305_yosan2": "https://kokkai.ndl.go.jp/api/speech?" + urllib.parse.urlencode(
            {"issueID": "112605272X00219930305", "any": "被扶養者", "maximumRecords": "100", "recordPacking": "json"}),
        "kk_hifuyo_haigusha_S62_H06": kokkai_search("被扶養配偶者", "1987-01-01", "1994-12-31"),
        "kk_dai3go_nintei_S62_H06": kokkai_search("第三号被保険者 認定", "1987-01-01", "1994-12-31"),
    },
    # 同（追加）：担当の N8 に出た発言のうち、§4 の表に無い2発言
    "v_kokkai2": {f"kk_{sid}": kokkai_speech(sid) for sid in ["113614237X01619960604_144", "118004401X01020120529_098"]},
    # e-Gov 法令API v2：国民年金法施行令の改正履歴・第4条、国民年金法 第7条・附則第7条の3
    "v_egov": {
        "kokunen_rei_revisions": f"{EGOV}/law_revisions/334CO0000000184",
        "kokunen_rei_2017-04-01": f"{EGOV}/law_data/334CO0000000184?response_format=json&asof=2017-04-01",
        "kokunen_rei_2017-03-31": f"{EGOV}/law_data/334CO0000000184?response_format=json&asof=2017-03-31",
        f"kokunen_rei_{TODAY}": f"{EGOV}/law_data/334CO0000000184?response_format=json&asof={TODAY}",
        f"kokunen_ho_{TODAY}": f"{EGOV}/law_data/334AC0000000141?response_format=json&asof={TODAY}",
    },
    # 社会保険審査会の裁決例の一覧（裁決年ごと）：第3号被保険者を扱う他の裁決を探す（推測 ID1 の検証方法3の一部）
    "v_shinsa_index": {
        "idx_h28_29": SHINSA + "h28_29.html",
        "idx_h30_31_r01": SHINSA + "h30_31_r01.html",
        "idx_r2_r3": SHINSA + "r2_r3.html",
        "idx_r04_r05": SHINSA + "r04_r05.html",
        "idx_r06": SHINSA + "r06.html",
        "idx_r07": SHINSA + "r07.html",
    },
    # 同（追加）：一覧の入口（05.html）と、入口から辿れない平成27年の一覧（検索エンジンで見つかった）
    "v_shinsa_index2": {
        "idx_root_05": SHINSA + "05.html",
        "idx_h27": SHINSA + "h27.html",
    },
}


# ================================================================ 取得（R3X_dai3go_fetch.py の写し）
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
            if self._href is not None:
                self._atext.append("⟨" + a["alt"] + "⟩")
        if tag == "a" and a.get("href"):
            self._href = a["href"]
            self._atext = []
        if tag == "form":
            self.parts.append(f"\n[form action={a.get('action')!r} method={a.get('method')!r}]\n")
        if tag in ("input", "select", "textarea") and a.get("name"):
            self.parts.append(f"[{tag} name={a.get('name')!r} type={a.get('type')!r} value={a.get('value')!r}]")
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


def read_with_deadline(resp, seconds=120):
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


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.geturl(), dict(r.headers), read_with_deadline(r)
    except urllib.error.HTTPError as e:
        return e.code, url, dict(e.headers or {}), e.read() if hasattr(e, "read") else b""


def ext_for(ctype, url):
    c = (ctype or "").lower()
    if "pdf" in c or url.lower().endswith(".pdf"):
        return ".pdf"
    if "json" in c or "/api/" in url:
        return ".json"
    if "html" in c:
        return ".html"
    return ".bin"


def kokkai_text(body):
    d = json.loads(body.decode("utf-8"))
    lines = [f"numberOfRecords={d.get('numberOfRecords')} numberOfReturn={d.get('numberOfReturn')}"]
    if "message" in d:
        lines.append("message=" + json.dumps(d.get("message"), ensure_ascii=False) + " details=" + json.dumps(d.get("details"), ensure_ascii=False))
    for r in d.get("speechRecord", []) or []:
        lines.append("=" * 60)
        lines.append(f"date={r.get('date')} house={r.get('nameOfHouse')} meeting={r.get('nameOfMeeting')} issue={r.get('issue')} "
                     f"speechOrder={r.get('speechOrder')} speaker={r.get('speaker')} position={r.get('speakerPosition')}")
        lines.append(f"speechID={r.get('speechID')}")
        lines.append(f"speechURL={r.get('speechURL')}")
        lines.append(str(r.get("speech") or ""))
    return "\n".join(lines)


def run_set(name, urls, ts):
    dl = ROOT / ".work" / "downloads" / f"{ts}_R3X_dai3go_verify_{name}"
    dl.mkdir(parents=True, exist_ok=False)
    tx = OUT / "text" / f"{ts}_{name}"
    tx.mkdir(parents=True, exist_ok=False)
    (OUT / "fetch").mkdir(parents=True, exist_ok=True)
    log = []
    for i, (sid, url) in enumerate(urls.items()):
        if i:
            time.sleep(WAIT)
        rec = {"id": sid, "url": url}
        try:
            st, final, hdr, body = get(url)
            ctype = hdr.get("Content-Type", "")
            ext = ext_for(ctype, final)
            (dl / f"{sid}{ext}").write_bytes(body)
            rec.update({"status": st, "final_url": final, "content_type": ctype, "bytes": len(body),
                        "sha256": hashlib.sha256(body).hexdigest(), "last_modified": hdr.get("Last-Modified"),
                        "saved": str((dl / f"{sid}{ext}").relative_to(ROOT)).replace("\\", "/")})
            text = None
            if ext == ".html" and body:
                s, cs = decode(body, ctype)
                p = Extract()
                p.feed(s)
                links = [{"href": urllib.parse.urljoin(final, lk["href"]), "text": lk["text"]} for lk in p.links
                         if lk["href"] and not lk["href"].startswith(("javascript:", "mailto:", "#"))]
                text = p.text()
                (tx / f"{sid}.links.json").write_text(json.dumps(links, ensure_ascii=False, indent=1), encoding="utf-8")
                rec.update({"charset": cs, "title": " ".join(p.title.split())})
                header = f"# source={final}\n# fetched_at={ts}\n# charset={cs}\n\n"
            elif ext == ".json" and body and "kokkai.ndl.go.jp" in final:
                text = kokkai_text(body)
                header = f"# source={final}\n# fetched_at={ts}\n\n"
            if text is not None:
                (tx / f"{sid}.txt").write_text(header + text, encoding="utf-8")
                rec["text"] = str((tx / f"{sid}.txt").relative_to(ROOT)).replace("\\", "/")
        except Exception as e:  # noqa: BLE001
            rec["error"] = repr(e)
        log.append(rec)
        (OUT / "fetch" / f"{name}_{ts}.json").write_text(
            json.dumps({"set": name, "fetched_at_local": ts, "user_agent": UA,
                        "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "results": log}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(json.dumps({k: rec.get(k) for k in ("id", "status", "bytes", "last_modified", "error")}, ensure_ascii=False), flush=True)


# ================================================================ PDF の文字（R3X_dai3go_pdftext.py の写し。暗号の復号は除いた）
def inflate(b):
    d = zlib.decompressobj()
    out = d.decompress(b, MAXOUT)
    if d.unconsumed_tail:
        raise ValueError("inflate: 上限を超えた")
    return out


def raw_objects(pdf):
    for m in re.finditer(rb"(\d+)\s+(\d+)\s+obj\b", pdf):
        end = pdf.find(b"endobj", m.end())
        body = pdf[m.end():end]
        sm = re.search(rb"stream\r?\n", body)
        if not sm:
            yield int(m.group(1)), int(m.group(2)), body, None
            continue
        dic = body[:sm.start()]
        lm = re.search(rb"/Length\s+(\d+)(?!\s+\d+\s+R)", dic)
        raw = body[sm.end():sm.end() + int(lm.group(1))] if lm else body[sm.end():body.rfind(b"endstream")].rstrip(b"\r\n")
        yield int(m.group(1)), int(m.group(2)), dic, raw


def load(pdf):
    if re.search(rb"/Filter\s*/Standard", pdf):
        return {}, "encrypted(未対応)"
    objs = {}
    for num, gen, dic, raw in raw_objects(pdf):
        if raw is None:
            objs[num] = (dic, None)
            continue
        dec = raw
        if b"FlateDecode" in dic:
            try:
                dec = inflate(dec)
            except Exception as e:  # noqa
                dec = b"<<inflate error " + repr(e).encode() + b">>"
        objs[num] = (dic, dec)
    for num, (dic, dec) in list(objs.items()):
        if dec is not None and b"/ObjStm" in dic:
            nn = int(re.search(rb"/N\s+(\d+)", dic).group(1))
            first = int(re.search(rb"/First\s+(\d+)", dic).group(1))
            hdr = [int(x) for x in dec[:first].split()]
            pairs = [(hdr[i], hdr[i + 1]) for i in range(0, min(len(hdr), 2 * nn), 2)]
            for i, (onum, off) in enumerate(pairs):
                end = pairs[i + 1][1] if i + 1 < len(pairs) else len(dec) - first
                objs.setdefault(onum, (dec[first + off:first + end], None))
    return objs, None


def ref(b, name):
    m = re.search(rb"/" + name + rb"\s*(\d+)\s+0\s+R", b)
    return int(m.group(1)) if m else None


def parse_cmap(b):
    m = {}
    for blk in re.findall(rb"beginbfchar(.*?)endbfchar", b, re.S):
        for a, c in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
            m[int(a, 16)] = bytes.fromhex(c.decode()).decode("utf-16-be", "replace")
    for blk in re.findall(rb"beginbfrange(.*?)endbfrange", b, re.S):
        for a, z, c in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
            base = int(c, 16)
            for k in range(int(a, 16), int(z, 16) + 1):
                m[k] = chr(base + k - int(a, 16))
    return m


def font_decoder(objs, fnum):
    dic = objs.get(fnum, (b"", None))[0]
    encm = re.search(rb"/Encoding\s*/([A-Za-z0-9\-]+)", dic)
    enc = encm.group(1).decode() if encm else ""
    tu = ref(dic, rb"ToUnicode")
    if "RKSJ" in enc:
        return lambda raw: raw.decode("cp932", "replace")
    if "UCS2" in enc or "UTF16" in enc:
        return lambda raw: raw.decode("utf-16-be", "replace")
    if tu is not None and objs.get(tu, (None, None))[1]:
        cm = parse_cmap(objs[tu][1])
        if enc.startswith("Identity") or b"/Type0" in dic:
            return lambda raw: "".join(cm.get(int.from_bytes(raw[i:i + 2], "big"), "�") for i in range(0, len(raw) - 1, 2))
        return lambda raw: "".join(cm.get(c, chr(c)) for c in raw)
    return lambda raw: raw.decode("latin-1")


def unescape_literal(s):
    out, i = bytearray(), 0
    while i < len(s):
        c = s[i]
        if c == 0x5C and i + 1 < len(s):
            n = s[i + 1]
            mp = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12, ord("("): 40, ord(")"): 41, ord("\\"): 92}
            if n in mp:
                out.append(mp[n])
                i += 2
                continue
            m = re.match(rb"[0-7]{1,3}", s[i + 1:i + 4])
            if m:
                out.append(int(m.group(0), 8) & 0xFF)
                i += 1 + len(m.group(0))
                continue
            i += 1
            continue
        out.append(c)
        i += 1
    return bytes(out)


TOK = re.compile(rb"<([0-9A-Fa-f\s]*)>|\(((?:[^()\\]|\\.)*)\)|\[|\]|/([^\s/\[\]<>()]+)|([-+]?\d*\.?\d+)|([A-Za-z'\"*]+)", re.S)


def page_rows(objs, pno, pdic):
    res = pdic
    rnum = ref(pdic, rb"Resources")
    if rnum is not None:
        res = objs.get(rnum, (b"", None))[0]
    fonts = {}
    fm = re.search(rb"/Font\s*(\d+)\s+0\s+R", res)
    fdict = objs.get(int(fm.group(1)), (b"", None))[0] if fm else (re.search(rb"/Font\s*<<(.*?)>>", res, re.S) or re.search(b"()", b"")).group(1)
    for name, num in re.findall(rb"/([^\s/<>]+)\s+(\d+)\s+0\s+R", fdict or b""):
        fonts[name.decode()] = font_decoder(objs, int(num))
    cont = re.search(rb"/Contents\s*(\[[^\]]*\]|\d+\s+0\s+R)", pdic)
    nums = [int(x) for x in re.findall(rb"(\d+)\s+0\s+R", cont.group(1))] if cont else []
    content = b"\n".join(objs.get(c, (b"", b""))[1] or b"" for c in nums)
    rows = []
    for bt in re.findall(rb"\bBT\b(.*?)\bET\b", content, re.S):
        stack, x, y, lx, ly, cur, lead = [], 0.0, 0.0, 0.0, 0.0, None, 0.0
        arr = None
        for m in TOK.finditer(bt):
            h, lit, nm, num, op = m.groups()
            tok = m.group(0)
            if tok == b"[":
                arr = []
                continue
            if tok == b"]":
                stack.append(("arr", arr))
                arr = None
                continue
            if h is not None:
                hh = re.sub(rb"\s", b"", h)
                v = ("str", bytes.fromhex(hh.decode() + ("0" if len(hh) % 2 else "")))
            elif lit is not None:
                v = ("str", unescape_literal(lit))
            elif nm is not None:
                v = ("name", nm.decode("latin-1"))
            elif num is not None:
                v = ("num", float(num))
            else:
                v = None
            if v is not None:
                if arr is not None:
                    arr.append(v)
                else:
                    stack.append(v)
                continue
            o = op.decode("latin-1")
            nums_ = [s[1] for s in stack if s[0] == "num"]
            if o == "Tf" and len(stack) >= 2 and stack[-2][0] == "name":
                cur = stack[-2][1]
            elif o == "Tm" and len(nums_) >= 6:
                x, y = nums_[-2], nums_[-1]
                lx, ly = x, y
            elif o in ("Td", "TD") and len(nums_) >= 2:
                lx, ly = lx + nums_[-2], ly + nums_[-1]
                x, y = lx, ly
                if o == "TD":
                    lead = -nums_[-1]
            elif o == "TL" and nums_:
                lead = nums_[-1]
            elif o == "T*":
                ly -= lead
                x, y = lx, ly
            elif o in ("Tj", "'", '"', "TJ"):
                dec = fonts.get(cur, lambda raw: raw.decode("latin-1"))
                if o == "TJ":
                    parts = [s for s in (stack[-1][1] if stack and stack[-1][0] == "arr" else []) if s[0] == "str"]
                    txt = "".join(dec(s[1]) for s in parts)
                else:
                    strs = [s for s in stack if s[0] == "str"]
                    txt = dec(strs[-1][1]) if strs else ""
                if txt.strip():
                    rows.append((pno, x, y, txt))
            stack = []
    return rows


def pages_of(objs):
    def kids(num):
        dic = objs.get(num, (b"", None))[0]
        if re.search(rb"/Type\s*/Page\b(?!s)", dic):
            return [num]
        km = re.search(rb"/Kids\s*\[([^\]]*)\]", dic)
        out = []
        for k in re.findall(rb"(\d+)\s+0\s+R", km.group(1) if km else b""):
            out += kids(int(k))
        return out
    roots = [n for n, (d, _) in objs.items() if re.search(rb"/Type\s*/Pages\b", d) and not re.search(rb"/Parent\s", d)]
    return kids(roots[0]) if roots else [n for n, (d, _) in sorted(objs.items()) if re.search(rb"/Type\s*/Page\b(?!s)", d)]


def pdf_pages_text(path, tsv_name):
    """頁ごとの文字列（y の降順・x の昇順で連結）を返し、頁・位置つきの TSV を書く。"""
    pdf = pathlib.Path(path).read_bytes()
    objs, enc = load(pdf)
    pages = pages_of(objs) if not enc else []
    rows = []
    for i, pnum in enumerate(pages, 1):
        rows += page_rows(objs, i, objs[pnum][0])
    rows.sort(key=lambda r: (r[0], -round(r[2], 1), r[1]))
    (OUT / "pdftext").mkdir(parents=True, exist_ok=True)
    with open(OUT / "pdftext" / f"{tsv_name}.tsv", "w", encoding="utf-8") as f:
        f.write(f"# file={pathlib.Path(path).as_posix()} sha256={hashlib.sha256(pdf).hexdigest()} encrypt={enc} pages={len(pages)}\n")
        for r in rows:
            f.write(f"{r[0]}\t{r[1]:.1f}\t{r[2]:.1f}\t{r[3]}\n")
    texts = {}
    for r in rows:
        texts.setdefault(r[0], []).append(r[3])
    # 2段組みの頁（裁決・講義資料）のため、x の最大の隙間で左右の段に分け、左の段→右の段の順に連結したものも作る
    cols = {}
    for p in texts:
        pr = [r for r in rows if r[0] == p]
        xs = sorted({round(r[1], 1) for r in pr})
        best = None
        for a, b in zip(xs, xs[1:]):
            left = sum(1 for r in pr if r[1] <= a)
            if left >= 0.2 * len(pr) and len(pr) - left >= 0.2 * len(pr) and (best is None or b - a > best[1] - best[0]):
                best = (a, b)
        if best is None:
            cols[p] = texts[p]
            continue
        lt = [r[3] for r in pr if r[1] <= best[0]]
        rt = [r[3] for r in pr if r[1] > best[0]]
        cols[p] = lt + rt
    return {"pages": len(pages), "encrypt": enc, "text": {p: "".join(v) for p, v in texts.items()},
            "text_cols": {p: "".join(v) for p, v in cols.items()}}


# ================================================================ 検査の道具
def norm(s):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or ""))


def latest_log(name):
    fs = sorted(f for f in glob.glob(str(OUT / "fetch" / f"{name}_*.json"))
                if re.fullmatch(re.escape(name) + r"_\d{8}-\d{6}\.json", pathlib.Path(f).name))
    return json.loads(pathlib.Path(fs[-1]).read_text(encoding="utf-8")) if fs else None


def recs(name):
    lg = latest_log(name)
    return {r["id"]: r for r in (lg or {}).get("results", [])}


def text_of(rec):
    return pathlib.Path(ROOT / rec["text"]).read_text(encoding="utf-8") if rec and rec.get("text") else ""


ITEM = re.compile(r"(?m)^[\t |]*・([^\n]+)\n(?:[^\n]*\n){0,3}?[\t |]*◆(\S+)\n(?:[\t |]*\n)?[\t |]*([^\n]+)")
COUNT = re.compile(r"該当件数:\s*(\d+)件中\s*(\d+)件~\s*(\d+)件")


def result_list(rec):
    t = text_of(rec)
    m = COUNT.search(t)
    err = re.search(r"\[ERR-[^\]]+\][^\n]*", t)
    items = [{"title": a.strip(), "date": b, "number": c.strip()} for a, b, c in ITEM.findall(t)]
    return {"total": int(m.group(1)) if m else (0 if "該当" in t and not items else None), "range": m.groups()[1:] if m else None,
            "error": err.group(0) if err else None, "items": items, "status": rec.get("status") if rec else None}


def has(text, s):
    return norm(s) in norm(text)


def egov_json(rec):
    return json.loads(pathlib.Path(ROOT / rec["saved"]).read_text(encoding="utf-8"))


def inline(n):
    if isinstance(n, str):
        return n
    if n.get("tag") in ("Rt",):
        return ""
    return "".join(inline(c) for c in n.get("children", []))


def find_articles(node, num, suppl):
    """本則（suppl=False）又は原始附則（suppl=True：AmendLawNum の無い SupplProvision）の Article Num=num を探す。"""
    out = []

    def walk(n, in_suppl, in_orig):
        if not isinstance(n, dict):
            return
        tag = n.get("tag")
        if tag == "SupplProvision":
            in_suppl, in_orig = True, not n.get("attr", {}).get("AmendLawNum")
        if tag == "Article" and n.get("attr", {}).get("Num") == num and ((suppl and in_suppl and in_orig) or (not suppl and not in_suppl)):
            out.append(n)
        for c in n.get("children", []):
            walk(c, in_suppl, in_orig)
    walk(node, False, False)
    return out


def paragraphs(art):
    res = []
    for p in art.get("children", []):
        if isinstance(p, dict) and p.get("tag") == "Paragraph":
            sent = "".join(inline(c) for c in p.get("children", []) if isinstance(c, dict) and c.get("tag") == "ParagraphSentence")
            items = []
            for it in p.get("children", []):
                if isinstance(it, dict) and it.get("tag") == "Item":
                    items.append((it.get("attr", {}).get("Num"), "".join(inline(c) for c in it.get("children", [])
                                                                          if isinstance(c, dict) and c.get("tag") == "ItemSentence")))
            res.append({"num": p.get("attr", {}).get("Num"), "sentence": sent, "items": items})
    return res


# ================================================================ 検査
def check():
    res = {}
    pdfr = recs("v_pdf")
    htr = recs("v_html")
    sr = recs("v_search")
    kwr = recs("v_kw")
    kkr = recs("v_kokkai")
    egr = recs("v_egov")
    idx = recs("v_shinsa_index")
    idx.update(recs("v_shinsa_index2"))
    h2r = recs("v_html2")
    kkr.update(recs("v_kokkai2"))
    pdfs = {}
    for k, r in pdfr.items():
        if r.get("status") == 200 and r.get("saved", "").endswith(".pdf"):
            pdfs[k] = pdf_pages_text(ROOT / r["saved"], k)

    # ---- V01 取得の状態（HTTP・Last-Modified・SHA-256・頁数）と、担当の取得（2026-11-09/11）との SHA-256 の一致
    old = {}
    for f in glob.glob(str(ROOT / "scripts" / "results" / "R3X_dai3go_fetch" / "*.json")):
        for r in json.loads(pathlib.Path(f).read_text(encoding="utf-8")).get("results", []):
            old.setdefault(r["url"], []).append({"sha256": r.get("sha256"), "bytes": r.get("bytes"), "last_modified": r.get("last_modified"), "log": pathlib.Path(f).name})
    v01 = {}
    for setname, rr in (("v_pdf", pdfr), ("v_html", htr)):
        for k, r in rr.items():
            v01[k] = {"status": r.get("status"), "last_modified": r.get("last_modified"), "sha256_16": (r.get("sha256") or "")[:16],
                      "pages": pdfs.get(k, {}).get("pages"), "encrypt": pdfs.get(k, {}).get("encrypt"),
                      "same_as_previous_fetch": [o["sha256"] == r.get("sha256") for o in old.get(r["url"], [])] or None}
    res["V01_fetch_status"] = v01

    # ---- V02 裁決 15_01（［SHS-263］）
    t = pdfs.get("shinsa_r02_03_15_01", {}).get("text_cols", {})
    full = "".join(t.values())
    res["V02_shs263"] = {
        "pages": pdfs.get("shinsa_r02_03_15_01", {}).get("pages"),
        "p1_case_no": has(t.get(1, ""), "令和元年（国）第２６３号"), "p1_date": has(t.get(1, ""), "令和２年４月３０日"),
        "p1_partial_cancel": [m for m in re.findall(r"[^。]{0,40}取り消す[^。]{0,10}", norm(t.get(1, "")))][:3],
        "fusoku_7_3_2": [m for m in re.findall(r"[^。]{0,40}附則第7条の3第2項[^。]{0,60}", norm(full))][:3],
        "hinintei_reason": has(full, "主として生計を維持していることが確認できないため。)」として、第3号被保険者に非該当である旨の通知"),
        "citation_s61_saishu": has(t.get(2, ""), "「国民年金法における被扶養配偶者の認定基準について」（昭和６１年３月３１日庁保発第１３号社会保険庁年金保険部長通知（最終改正平成５年３月１５日庁保発第５号））"),
        "quote1_head": has(t.get(2, ""), "被扶養配偶者の認定は、健康保険法、国家公務員共済組合法、地方公務員等共済組合法及び私立学校教職員共済組合法における被扶養者の認定の取扱いを勘案して、日本年金機構が行うとされ"),
        "quote2": has(full, "また、認定対象者が、健康保険、船員保険若しくは共済組合の被扶養者として認定されている場合又は所得税法第２条第１項第３３号に規定する控除対象配偶者として取り扱われている場合は、これを被扶養配偶者として取り扱うこととされ"),
        "quote2_tail": has(full, "（国民年金法施行令第４条及び「国民年金法における被扶養配偶者の認定基準の運用について」（昭和６１年４月１日庁保険発第１８号）"),
        "amount_130_in_text": [w for w in ("130万", "１３０万", "百三十万") if has(full, w)],
        "saishu_kaisei_all": re.findall(r"最終改正[^）]{0,30}", norm(full)),
    }

    # ---- V03 §1.2 の他の裁決の事件番号・日付・［S61］の引用の有無
    v03 = {}
    for k in ("shinsa_r02_03_06_04", "shinsa_r02_03_06_05", "shinsa_r02_03_06_10", "shinsa_r02_03_06_11", "shinsa_r04_05_07_02"):
        tt = pdfs.get(k, {}).get("text_cols", {})
        ft = norm("".join(tt.values()))
        p1 = norm(tt.get(1, ""))
        cjk = sum(1 for c in ft if "\u3040" <= c <= "\u9fff")
        v03[k] = {"pages": pdfs.get(k, {}).get("pages"),
                  "case_no": re.findall(r"(?:平成|令和)[元0-9０-９]+年\((?:厚|国|健)\)第[0-9０-９]+号", p1)[:2],
                  "date": re.findall(r"(?:平成|令和)[元0-9０-９]+年[0-9０-９]+月[0-9０-９]+日", p1)[:2],
                  "izoku": "遺族厚生年金" in ft, "cites_S61": "庁保発第13号" in ft or "被扶養配偶者の認定基準について" in ft,
                  "saishu": "最終改正" in ft, "H23_0323_1": "年発0323第1号" in ft, "850man": "850万円" in ft,
                  "cjk_ratio": round(cjk / len(ft), 3) if ft else None}
    res["V03_other_shinsa"] = v03

    # ---- V04 ［S61］00tb1690
    s61 = text_of(htr.get("tdoc_00tb1690_S61"))
    res["V04_S61"] = {
        "title_line": next((ln for ln in s61.splitlines() if ln.startswith("・")), None),
        "atesaki": re.findall(r"\(([^()]*あて[^()]*)\)", s61)[:2],
        "count_90": s61.count("九○万円") + s61.count("九〇万円"), "count_150": s61.count("一五○万円") + s61.count("一五〇万円"),
        "count_130": sum(s61.count(w) for w in ("一三○万円", "一三〇万円", "百三十万円", "130万円")),
        "kaisei_word": "改正" in s61,
        "zenbun": has(s61, "第七条第二項及び国民年金法施行令(昭和三四年政令第一八四号)第四条の三の規定に基づき"),
        "betten_daijin": has(s61, "(厚生大臣)"),
    }

    # ---- V05 ［S61-U］00tb1695
    su = text_of(htr.get("tdoc_00tb1695_S61U"))
    res["V05_S61U"] = {
        "title_line": next((ln for ln in su.splitlines() if ln.startswith("・")), None),
        "atesaki": re.findall(r"\(([^()]*あて[^()]*)\)", su)[:2],
        "item1_quote": has(su, "１　第三号被保険者としての届出に係る者(以下「認定対象者」という。)が、健康保険、船員保険若しくは共済組合の被扶養者として認定されている場合又は所得税法(昭和四○年法律第三三号)第二条第一項第三三号に規定する控除対象配偶者として取り扱われている場合(控除対象配偶者として取り扱われていない場合であつて、前年における年間収入が一一○万円未満(認定対象者が概ね厚生年金保険法による障害厚生年金の受給要件に該当する程度の障害者である場合にあつては一六○万円未満)である場合を含む。)は、これを第二号被保険者の配偶者であつて主として第二号被保険者の収入により生計を維持している者(以下「被扶養配偶者」という。)として取り扱うこと。ただし、認定対象者がこれらに該当する場合であつても、被扶養配偶者の認定基準に該当しないことが明らかであるとき又は農業者年金の被保険者であるときは、この限りでないこと。"),
        "item3_quote": has(su, "「年間収入」とは、認定対象者が被扶養配偶者に該当する時点での恒常的な収入の状況により算定すること。"),
        "amounts": sorted(set(re.findall(r"[一二三四五六七八九○〇]+万円", su))),
        "kaisei_word": "改正" in su,
    }

    # ---- V06 ［S61-12］・［S61-17］・［H22-KIZON］
    s12 = text_of(htr.get("tdoc_00tb1174_S61_12"))
    s17 = text_of(htr.get("tdoc_00tb1694_S61_17"))
    h22 = "\n".join(text_of(htr.get(f"tdoc_00tb5871_H22_p{i}")) for i in (1, 2, 3))
    h22p = {i: text_of(htr.get(f"tdoc_00tb5871_H22_p{i}")) for i in (1, 2, 3)}
    row85 = re.search(r"85[\s|]*国民年金法における被扶養配偶者の認定基準について[\s|]*([^\n|]+)[\s|]*([^\n|]+)[\s|]*([^\n|]+)", h22)
    row88 = re.search(r"88[\s|]*国民年金法における被扶養配偶者の認定基準の運用について[\s|]*([^\n|]+)[\s|]*([^\n|]+)[\s|]*([^\n|]+)", h22)
    res["V06_S61_12_17_H22"] = {
        "S61_12_title": next((ln for ln in s12.splitlines() if ln.startswith("・")), None),
        "S61_12_quote": has(s12, "(五)　被扶養配偶者の認定　国民年金の第三号被保険者の認定は、健康保険法(大正一一年法律第七○号)等の被扶養者の認定の取扱いを勘案して厚生大臣の定めるところにより都道府県知事が行うものとされたこと(国年施行令第四条の三)。"),
        "S61_17_title": next((ln for ln in s17.splitlines() if ln.startswith("・")), None),
        "S61_17_quote": has(s17, "第三号被保険者であることの認定は「国民年金法における被扶養配偶者の認定基準について」(昭和六一年三月三一日庁保発第一三号)及び「国民年金法における被扶養配偶者の認定基準の運用について」(昭和六一年四月一日庁保険発第一八号)に基づき都道府県知事が行うこと。"),
        "H22_title": next((ln for ln in h22p[1].splitlines() if ln.startswith("・")), None),
        "H22_atesaki": re.findall(r"\(([^()]*あて[^()]*)\)", h22p[1])[:2],
        "H22_pages_nonempty": {i: len(h22p[i]) for i in h22p},
        "H22_row85": [g.strip() for g in row85.groups()] if row85 else None,
        "H22_row85_page": [i for i in h22p if "被扶養配偶者の認定基準について" in h22p[i] and re.search(r"(?m)^[\s|]*85[\s|]*$", h22p[i])],
        "H22_row88": [g.strip() for g in row88.groups()] if row88 else None,
        "H22_bettenn2_word": [i for i in h22p if "別添2" in norm(h22p[i])],
        "H22_ki2_4": has(h22, "社会保険庁より発出された通知等について、上記(1)及び(2)により分類した主な例を別添2として添付する"),
        "H22_ki2_1": has(h22, "今後は、年金局より機構に対し、法令の施行通知、解釈通知、疑義照会への回答等の通知等を発出することとしている"),
        "H22_ki2_2": has(h22, "当該通知等に基づく事務に関し、機構においてその具体的方法(事務処理手順、事務処理上の添付書類等)や進捗管理手順(報告様式等)等を定める必要がある場合には、機構の業務処理マニュアル等によりその取扱いを定めることとする"),
        "H22_ki2_4b": has(h22, "機構は、通知等の取扱いを変更等する旨を年金局に報告しその了解を得ることとすること。"),
        "H22_header": has(h22, "発出番号(事務連絡にあっては「事務連絡」)"),
    }

    # ---- V07 平成5年の庁保発の番号検索、日付検索、検索の仕様の確かめ
    v07 = {f"H05_chohohatsu_{n}": result_list(sr.get(f"H05_chohohatsu_{n}")) for n in range(1, 14)}
    for k in ("S52_chohohatsu_9", "S52_hohatsu_9", "S61_chohohatsu_13", "H050315", "H050305", "H150324", "H15_chobunhatsu_798", "H05_chohohatsu_only"):
        v07[k] = result_list(sr.get(k))
    march = [result_list(sr.get(f"H050301_0331_p{i}")) for i in range(3)]
    items = [it for m in march for it in m["items"]]
    v07["H050301_0331"] = {"totals": [m["total"] for m in march], "n_items": len(items),
                           "chohohatsu": [it for it in items if it["number"].startswith("庁保発") or "庁保発" in it["number"]],
                           "on_0315": [it for it in items if it["date"].endswith("03月15日")],
                           "hifuyo_titles": [it for it in items if "被扶養" in it["title"]]}
    res["V07_db_search"] = v07

    # ---- V08 本文検索の件数
    v08 = {}
    for k, r in kwr.items():
        rl = result_list(r)
        v08[k] = {"total": rl["total"], "n_items": len(rl["items"]), "items": [f"{i['date']} {i['number']} {i['title'][:60]}" for i in rl["items"]]}
    hp = [it for k in ("kw_hifuyo_haigusha_p0", "kw_hifuyo_haigusha_p1", "kw_hifuyo_haigusha_p2", "kw_hifuyo_haigusha_p3")
          for it in result_list(kwr.get(k))["items"]]
    v08["hifuyo_haigusha_all_pages"] = {"n": len(hp), "titles_with_nintei_kijun": [f"{i['date']} {i['number']} {i['title']}" for i in hp if "認定基準" in i["title"]],
                                        "titles_with_kaisei_and_haigusha": [f"{i['date']} {i['number']} {i['title']}" for i in hp if "被扶養配偶者" in i["title"]]}
    c5 = [it for k in ("kw_chohohatsu5_p0", "kw_chohohatsu5_p1") for it in result_list(kwr.get(k))["items"]]
    v08["chohohatsu5_all_pages"] = {"n": len(c5), "heisei5": [i for i in c5 if i["date"].startswith("平成05年")], "hifuyo": [i for i in c5 if "被扶養" in i["title"]]}
    res["V08_db_keyword"] = v08

    # ---- V09 紙上Live講義（［LIVE］）5頁
    lt = pdfs.get("live_0000086586", {}).get("text_cols", {})
    p5 = lt.get(5, "")
    res["V09_live"] = {
        "pages": pdfs.get("live_0000086586", {}).get("pages"),
        "q_dousetai": has(p5, "最初に、認定対象者が第2号被保険者と同一世帯に属している場合です。第2号被保険者によって主として生計を維持されていて、認定対象者の年間収入が130万円未満であって、かつ、第2号被保険者の年間収入の2分の1未満である場合は、原則として被扶養配偶者に該当します。"),
        "q_tadashi": has(p5, "ただし、認定対象者の収入が第2号被保険者の2分の1以上の場合であっても、第2号被保険者の年間収入を上回らない場合には、日本年金機構がその世帯の生計の状況を総合的に勘案して、第2号被保険者がその世帯の生計維持の中心的役割を果たしていると認めるときは、被扶養配偶者に該当することがあります。"),
        "q_besetai": has(p5, "次は、認定対象者が第2号被保険者と同一世帯に属していない場合です。第2号被保険者によって主として生計を維持されていて、認定対象者の年間収入が130万円未満であって、かつ、第2号被保険者からの仕送りなどの援助による収入額より少ない場合には、原則として被扶養配偶者に該当します。"),
        "q_mikomi": has(p5, "また、ここでの年間収入とは、過去における収入のことではなく、被扶養配偶者に該当する時点、および認定された日以降の年間の見込み収入額のことをいいます。"),
        "q_108333": has(p5, "月額108,333円以下"), "q_3611": has(p5, "日額3,611円以下"),
        "q_tsuchi": has(p5, "なお、被扶養配偶者の認定基準に関しては、通知（『昭和61年3月31日庁保発第13号』、『昭和61年4月1日庁保険発第18号』、『平成15年3月24日庁文発第798号』）が発出されていますので、参照してください。"),
        "q_head": has(p5, "被扶養配偶者の認定は、健康保険法などの被扶養者の認定の取扱いを勘案して、日本年金機構が行っています。"),
        "q_shuunyu_fukumu": has(p5, "そして、被扶養配偶者の収入には、雇用保険の失業等給付、公的年金、健康保険の傷病手当金や出産手当金も含まれますので、注意してください。"),
        "has_180_or_shogai_on_p5": [w for w in ("180万", "障害") if w in norm(p5)],
        "saishu_kaisei_any_page": [p for p, s in lt.items() if "最終改正" in norm(s)],
        "date_like_any_page": sorted({m for s in lt.values() for m in re.findall(r"(?:平成|令和)[0-9元]+年[0-9]+月(?:[0-9]+日)?", norm(s))})[:20],
    }

    # ---- V10 機構「疑義照会回答（厚生年金保険 適用）」
    gt = pdfs.get("gigi_kounen_tekiyou", {}).get("text", {})
    gfull = {p: norm(s) for p, s in gt.items()}
    res["V10_gigi"] = {
        "pages": pdfs.get("gigi_kounen_tekiyou", {}).get("pages"),
        "q4_fragment": [p for p, s in gfull.items() if "被扶養配偶者の認定基準の運用について」(昭和61年4月1日庁" in s],
        "q6_q8_fragment": [p for p, s in gfull.items() if "庁保険発第18号と同様の扱い" in s],
        "q7_fragment": [p for p, s in gfull.items() if "日額3,611" in s and "130万円未満の基準" in s],
        "count_chohokenhatsu18_split_ok": {p: len(re.findall(r"庁保険発第18", gfull.get(p, ""))) for p in (24, 25, 26)},
        "chohohatsu13_pages": [p for p, s in gfull.items() if "庁保発第13号" in s],
        "chohokenhatsu18_pages": [p for p, s in gfull.items() if "庁保険発第18号" in s],
        "printed_page_numbers_24_26": {p: re.findall(r"(?:^|[^0-9])(2[0-9])$", gfull.get(p, ""))[:1] for p in (24, 25, 26)},
    }

    # ---- V11 国会会議録
    v11 = {}
    for k, r in kkr.items():
        tx = text_of(r)
        hd = re.search(r"date=(\S+) house=(\S+) meeting=(\S+) issue=(\S+) speechOrder=(\S+) speaker=(\S+) position=(\S+)", tx)
        url = re.search(r"speechURL=(\S+)", tx)
        v11[k] = {"head": hd.groups() if hd else None, "url": url.group(1) if url else None, "_text": norm(tx)}
    quotes = {
        "kk_112605272X00219930305_069": "健康保険において夫の被扶養者となれる妻の収入の限度額及び国民年金において夫の被扶養配偶者として扱われる限度額、平成元年に百万円から百十万円未満に、平成四年に百十万円から百二十万円未満に",
        "kk_112605272X00219930305_070": "改定の経緯につきましては、委員御指摘のとおり平成四年に百二十万円、そして平成五年度からは百三十万円に改定したい、このように考えているところでございます。",
        "kk_112604629X00619930309_070": "私ども、この四月から被扶養者認定基準百二十万円を百三十万に引き上げる、こういうふうにさせていただいたところでございます。",
        "kk_112605289X01519930604_089": "現在では、六十歳未満の場合百三十万円未満というものを目安として被扶養者と認定する、このような仕組みをとらせていただいているわけでございます。",
        "kk_113104237X00719941026_037": "配偶者の方は一般的に所得がないか百三十万以下の所得であるとかいうことで、保険料の負担能力というのは非常に乏しいわけでございまして",
        "kk_113114237X00519941031_050": "この対象外になった場合には、その収入に応じまして、百三十万円以上の方は国民年金の第一号被保険者、それから百三十万円未満の方は第三号被保険者ということで年金保障が行われることになっているわけでございます。",
        "kk_115414260X00520020328_057": "被扶養者の認定に当たりましては、被扶養配偶者に該当する時点での、その時点での収入の状況により認定することとなっております。具体的に申しますと、その時点での収入が年額ベースで百三十万円、これを日額ベースに直しますと、三千六百円を超えるかどうかにより認定するものとなっております。",
        "kk_115414260X00620020416_139": "昭和六十一年四月の国民年金課長通知",
        "kk_115414260X00620020416_140": "通知におきまして年間収入と記載しております趣旨は、認定時における収入状況を判断する指標として分かりやすいものとする観点から年間ベースに換算した額を示したものでありまして",
        "kk_121105267X00120230220_294": "数次にわたり見直しを行っておりまして、平成五年、現在の年収百三十万円としております。",
    }
    for k, q in quotes.items():
        if k in v11:
            v11[k]["quote_found"] = norm(q) in v11[k]["_text"]
    v11["kk_121105267X00120230220_294"]["quote2_found"] = norm("この一九九三年から、過去三十年間にわたりまして、") in v11.get("kk_121105267X00120230220_294", {}).get("_text", "") and norm("現在、百三十万円が維持されております。") in v11.get("kk_121105267X00120230220_294", {}).get("_text", "")
    v11["kk_112605289X01519930604_089"]["context_kenpo"] = [w for w in ("健康保険", "被扶養者", "第三号", "国民年金") if w in v11.get("kk_112605289X01519930604_089", {}).get("_text", "")]
    for v in v11.values():
        v.pop("_text", None)
    res["V11_kokkai"] = v11

    # ---- V12 e-Gov：国年令の改正履歴・第4条、国年法 第7条・原始附則第7条の3
    v12 = {}
    revs = egov_json(egr["kokunen_rei_revisions"]).get("revisions", []) if egr.get("kokunen_rei_revisions", {}).get("status") == 200 else []
    ds = sorted(r.get("amendment_enforcement_date") or "" for r in revs)
    v12["kokunen_rei_revisions"] = {"n": len(revs), "oldest": ds[:2], "newest": ds[-2:],
                                    "current": [{k: r.get(k) for k in ("law_revision_id", "amendment_law_num", "amendment_enforcement_date")} for r in revs if r.get("current_revision_status") == "CurrentEnforced"]}
    for k in ("kokunen_rei_2017-04-01", "kokunen_rei_2017-03-31", f"kokunen_rei_{TODAY}"):
        r = egr.get(k, {})
        if r.get("status") != 200:
            v12[k] = {"status": r.get("status"), "body": pathlib.Path(ROOT / r["saved"]).read_text(encoding="utf-8")[:300] if r.get("saved") else None}
            continue
        d = egov_json(r)
        a4 = find_articles(d["law_full_text"], "4", False)
        v12[k] = {"status": 200, "law_revision_id": (d.get("revision_info") or {}).get("law_revision_id"),
                  "enforcement": (d.get("revision_info") or {}).get("amendment_enforcement_date"),
                  "art4_caption": [inline(c) for c in a4[0]["children"] if isinstance(c, dict) and c.get("tag") == "ArticleCaption"] if a4 else None,
                  "art4": paragraphs(a4[0]) if a4 else None}
    a = v12.get("kokunen_rei_2017-04-01", {}).get("art4")
    b = v12.get(f"kokunen_rei_{TODAY}", {}).get("art4")
    v12["art4_same"] = (a == b) if a and b else None
    v12["art4_has_shiritsu_kyosai_ho"] = bool(b) and "私立学校教職員共済法" in b[0]["sentence"] and "私立学校教職員共済組合法" not in b[0]["sentence"]
    v12["art4_has_daijin_sadame"] = bool(b) and "大臣の定める" in b[0]["sentence"]
    r = egr.get(f"kokunen_ho_{TODAY}", {})
    if r.get("status") == 200:
        d = egov_json(r)
        a7 = find_articles(d["law_full_text"], "7", False)
        f73 = find_articles(d["law_full_text"], "7_3", True)
        v12["kokunen_ho"] = {"law_revision_id": (d.get("revision_info") or {}).get("law_revision_id"),
                             "art7": paragraphs(a7[0]) if a7 else None,
                             "suppl_7_3_caption": [inline(c) for c in f73[0]["children"] if isinstance(c, dict) and c.get("tag") == "ArticleCaption"] if f73 else None,
                             "suppl_7_3": paragraphs(f73[0]) if f73 else None}
    res["V12_egov"] = v12

    # ---- V13 検討会資料［KT2］と議事録［KT-GJ］：130万円の説明が第3号についてか、健保・厚年の被扶養者についてか
    gj = text_of(htr.get("kt_gijiroku"))
    i = gj.find("変更はございません")
    ctx = gj[max(0, i - 700): i + 40] if i >= 0 else ""
    kt = pdfs.get("kt2_001746546", {})
    res["V13_kentokai"] = {
        "gijiroku_sentence_found": i >= 0,
        "gijiroku_context_norm": norm(ctx)[-420:],
        "says_p5_is_kenpo_kounen": has(ctx, "５ページ目につきましては、厚生年金保険・健康保険の被扶養者の認定基準となってございます。"),
        "says_p4_is_tsuchi": has(gj, "詳細について、次ページに具体的な通知を添付してございます。"),
        "says_130_dai3go": has(gj, "生計維持関係の認定につきましては、年間収入が130万未満であること等となってございます。"),
        "kt2_pages": kt.get("pages"), "kt2_last_modified": pdfr.get("kt2_001746546", {}).get("last_modified"),
        "kt2_p4_S52_head": "被扶養者としての届出に係る者" in norm(kt.get("text", {}).get(4, "")),
        "kt2_p4_has_130_180": [w for w in ("130万円", "180万円") if w in norm(kt.get("text", {}).get(4, ""))],
        "kt2_p4_has_S61_number": "庁保発第13号" in norm(kt.get("text", {}).get(4, "")) or "庁保発第１３号" in kt.get("text", {}).get(4, ""),
        "kt_page_title": htr.get("kt_page", {}).get("title"),
    }

    # ---- V14 平成5年4月7日・平成5年3月31日の通知、S52 の最終改正、令和7年の通知（文書 §7.2・HD1・ID4 で使う日付）
    def head(k):
        tx = text_of(htr.get(k))
        return {"title_line": next((ln for ln in tx.splitlines() if ln.startswith("・")), None),
                "atesaki": re.findall(r"\(([^()]*あて[^()]*)\)", tx)[:1]}
    s52 = text_of(htr.get("tdoc_00tb0189_S52"))
    rodo = text_of(htr.get("tdoc_00tc9348_R7_rodo"))
    r1923 = text_of(htr.get("tdoc_00tc9249_R7_1923"))
    res["V14_other_notices"] = {
        "H050407": head("tdoc_00tb0141_H050407"), "H050331": head("tdoc_00ta3218_H050331"),
        "H050331_hifuyo_haigusha": [m for m in re.findall(r"[^。\n]{0,80}被扶養配偶者[^。\n]{0,80}", text_of(htr.get("tdoc_00ta3218_H050331")))][:3],
        "S52": head("tdoc_00tb0189_S52"), "S52_amounts": sorted(set(re.findall(r"[一二三四五六七八九○〇0-9]+万円", s52))),
        "S52_kaisei_notes": re.findall(r"[^\n]{0,30}改正[^\n]{0,40}", s52)[:6],
        "R7_rodo": head("tdoc_00tc9348_R7_rodo"), "R7_rodo_tekiyo": re.findall(r"[^\n]{0,20}から適用すること。", rodo),
        "R7_rodo_mentions_kokunen_dai3go": re.findall(r"国民年金|第3号被保険者|第三号被保険者|被扶養配偶者", rodo),
        "R7_1923": head("tdoc_00tc9249_R7_1923"), "R7_1923_tekiyo": re.findall(r"[^\n]{0,20}から適用すること。", r1923),
        "R7_1923_haigusha_jogai": has(r1923, "当該認定対象者(被保険者の配偶者を除く。)が19歳以上23歳未満である場合にあっては150万円未満として取り扱うこと。"),
        "R7_1923_mentions_kokunen_dai3go": re.findall(r"国民年金|第3号被保険者|第三号被保険者|被扶養配偶者", r1923),
    }

    # ---- V15 社会保険審査会の裁決例の一覧：第3号被保険者・被扶養配偶者を扱う裁決の候補
    v15 = {}
    for k, r in idx.items():
        tx = text_of(r)
        lk = json.loads(pathlib.Path(ROOT / r["text"].replace(".txt", ".links.json")).read_text(encoding="utf-8")) if r.get("text") else []
        v15[k] = {"status": r.get("status"), "title": r.get("title"),
                  "lines_dai3go": [ln.strip() for ln in tx.splitlines() if any(w in ln for w in ("第3号", "第３号", "第三号", "被扶養配偶者"))][:20],
                  "links_kokunen": [l for l in lk if any(w in l["text"] for w in ("国民年金",))][:30]}
    res["V15_shinsa_index"] = v15

    # ---- V17 年金の事業運営・適用促進などの通知に、第3号の収入の金額が書かれているか
    v17 = {}
    for k, r in h2r.items():
        tx = text_of(r)
        near = re.findall(r"[^。\n]{0,80}(?:第三号被保険者|第3号被保険者|被扶養配偶者)[^。\n]{0,80}", tx)
        v17[k] = {"title_line": next((ln for ln in tx.splitlines() if ln.startswith("・")), None),
                  "n_mentions": len(near),
                  "amount_near_dai3go": [m for m in near if re.search(r"[一二三四五六七八九○〇0-9０-９]+万円|万円未満", m)]}
    res["V17_other_nenkin_notices"] = v17

    # ---- V18 国会会議録（N8 の残り2発言）：発言者と「百三十万」の文
    v18 = {}
    for k in ("kk_113614237X01619960604_144", "kk_118004401X01020120529_098"):
        tx = text_of(kkr.get(k))
        hd = re.search(r"date=(\S+) house=(\S+) meeting=(\S+) issue=(\S+) speechOrder=(\S+) speaker=(\S+) position=(\S+)", tx)
        v18[k] = {"head": hd.groups() if hd else None,
                  "sentences_130": [x for x in re.split(r"(?<=。)", tx) if "百三十万" in x][:3]}
    res["V18_kokkai_n8_rest"] = v18

    # ---- V19 国会会議録の検索の件数（担当の実測 §2.3 の表と比べる）
    v19 = {}
    for k, r in recs("v_kokkai_search").items():
        m = re.search(r"numberOfRecords=(\S+)", text_of(r))
        v19[k] = m.group(1) if m else None
    res["V19_kokkai_search_counts"] = v19

    # 既存の担当の取得ファイルの SHA-256（文書の［M-D3］§2.1 の先頭16桁）を、ディスク上のファイルで計算し直す
    disk = {}
    for f in sorted(glob.glob(str(ROOT / "scripts" / "results" / "R3X_dai3go_fetch" / "*.json"))):
        lg = json.loads(pathlib.Path(f).read_text(encoding="utf-8"))
        for r in lg.get("results", []):
            p = ROOT / r.get("saved", "") if r.get("saved") else None
            ok = None
            if p and p.exists():
                ok = hashlib.sha256(p.read_bytes()).hexdigest() == r.get("sha256")
            disk[f"{lg['set']}/{r['id']}"] = {"sha256_16": (r.get("sha256") or "")[:16], "status": r.get("status"),
                                               "last_modified": r.get("last_modified"), "disk_matches_log": ok}
    res["V16_previous_logs"] = disk

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "checks.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = []
    for k, v in res.items():
        if k == "V16_previous_logs":
            continue
        lines.append(f"## {k}")
        lines.append(json.dumps(v, ensure_ascii=False, indent=1)[:6000])
        lines.append("")
    (OUT / "checks.txt").write_text("\n".join(lines), encoding="utf-8")
    print("wrote", (OUT / "checks.json").relative_to(ROOT))


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")
    if not argv:
        print(__doc__)
        return 1
    if argv[0] == "fetch":
        if len(argv) < 2 or argv[1] == "--list":
            for k, v in SETS.items():
                print(k, len(v))
            return 0
        ts = time.strftime("%Y%m%d-%H%M%S")
        for i, name in enumerate(argv[1:]):
            if i:
                time.sleep(WAIT)
            run_set(name, SETS[name], ts)
        return 0
    if argv[0] == "check":
        check()
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

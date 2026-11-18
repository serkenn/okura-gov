"""R3X_dai3go: 国民年金の第3号被保険者の収入基準（被扶養配偶者の認定基準）の現在の根拠を探すため、
厚労省 法令等データベース・日本年金機構の公開資料・国会会議録検索システムの API などを取得し、取得記録を残す。

実行（Windows、リポジトリのルートで）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_dai3go_fetch.py <set名> [<set名> ...]
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_dai3go_fetch.py --list

- scripts/R2X_spouse_fetch.py のコードを写して作った（import はしていない）。標準ライブラリのみ（Python 3.11）。
- 取得したファイルは信頼できないデータとして、取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_R3X_dai3go_<set>/ に置く（その中でインタプリタやツールを実行しない）。
- HTML から抽出したテキストとリンクは scripts/results/R3X_dai3go_fetch/text/<ts>_<set>/ に置く（後で原文の引用を照合するため）。
  国会会議録検索システムの JSON は、発言ごとの日付・会議名・発言者・URL と本文を同じ場所に .txt で書き出す。
  PDF はここではテキスト化しない（scripts/R3X_dai3go_pdftext.py か Read ツールのページ指定で読む）。
- 取得記録（ステータス、最終URL、Content-Type、Last-Modified、ETag、SHA-256、タイトル）は
  scripts/results/R3X_dai3go_fetch/<set>_<ts>.json に書く。
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。個人の情報は送らない。官報は取得しない。
"""
import hashlib
import html.parser
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
WAIT = 1.5
OUT = ROOT / "scripts" / "results" / "R3X_dai3go_fetch"


def mhlw_date_search(gengo, y, m, d, y2=None, m2=None, d2=None, shubetsu="", bango="", page=None):
    """厚労省 法令等データベース 通知の情報詳細検索（日付・種別・番号、GET）。gengo: 3=昭和 4=平成 5=令和。
    フォームの欄の名前は /web/t_itemsrch?type=1 の HTML（mhlw_forms の取得）で確認した。"""
    y2, m2, d2 = y2 or y, m2 or m, d2 or d
    u = ("https://www.mhlw.go.jp/web/t_itemsrch_result?type=1"
         f"&startGengo={gengo}&yearFrom={y}&monthFrom={m}&dayFrom={d}"
         f"&endGengo={gengo}&yearTo={y2}&monthTo={m2}&dayTo={d2}"
         f"&shubetsu={urllib.parse.quote(shubetsu)}&bango={urllib.parse.quote(bango)}")
    if page is not None:
        u += f"&page={page}"
    return u


def mhlw_kw(keyword, page=None):
    """厚労省 法令等データベース 通知の本文検索（GET）。フォームは /hourei/html/tsuchi/docsrch1.html（action=/web/t_docsrch_keyword、
    欄 keyword・type=1・mode=0）。"""
    u = "https://www.mhlw.go.jp/web/t_docsrch_keyword?" + urllib.parse.urlencode({"keyword": keyword, "type": "1", "mode": "0"})
    if page is not None:
        u += f"&page={page}"
    return u


def tdoc(data_id, page=1):
    return f"https://www.mhlw.go.jp/web/t_doc?dataId={data_id}&dataType=1&pageNo={page}"


def kokkai(any_words, frm, until, start=1, maxrec=100):
    """国会会議録検索システム 検索用API（発言単位出力）。https://kokkai.ndl.go.jp/api.html の仕様による。"""
    q = {"any": any_words, "from": frm, "until": until, "startRecord": str(start),
         "maximumRecords": str(maxrec), "recordPacking": "json"}
    return "https://kokkai.ndl.go.jp/api/speech?" + urllib.parse.urlencode(q)


NENKIN_GIGI = "https://www.nenkin.go.jp/service/seidozenpan/gigishokai.files/"

SETS = {
    # 厚労省 法令等データベース 通知検索のフォーム（欄の名前の確認用）
    "mhlw_forms": {
        "tsuchi_search1": "https://www.mhlw.go.jp/hourei/html/tsuchi/search1.html",
        "tsuchi_docsrch1": "https://www.mhlw.go.jp/hourei/html/tsuchi/docsrch1.html",
        "tsuchi_search2": "https://www.mhlw.go.jp/hourei/html/tsuchi/search2.html",
        "tsuchi_itemsrch": "https://www.mhlw.go.jp/web/t_itemsrch?type=1",
        "manual_hourei06": "https://www.mhlw.go.jp/hourei/html/manual/hourei-06.html",
        "bango_gd": "https://www.mhlw.go.jp/hourei/html/tsuchi/bango_gd.html",
    },
    # 同 本文検索（キーワード）。本文の数字は漢数字（「庁保発第一三号」など。00tb1690 の表示による）
    "mhlw_kw": {
        "kw_nintei_kijun": mhlw_kw("被扶養配偶者の認定基準"),
        "kw_hifuyo_haigusha": mhlw_kw("被扶養配偶者"),
        "kw_chohohatsu13": mhlw_kw("庁保発第一三号"),
        "kw_dai3go_nintei": mhlw_kw("第三号被保険者の認定"),
        "kw_shunyu_nintei": mhlw_kw("収入がある者についての被扶養者の認定"),
    },
    # 同 本文検索の続き：「被扶養配偶者」の2〜4ページ目（検索結果の hidden の page を指定）と追加の語
    "mhlw_kw2": {
        "kw_hifuyo_haigusha_p1": mhlw_kw("被扶養配偶者", page=1),
        "kw_hifuyo_haigusha_p2": mhlw_kw("被扶養配偶者", page=2),
        "kw_hifuyo_haigusha_p3": mhlw_kw("被扶養配偶者", page=3),
        "kw_hifuyo_haigusha_nintei": mhlw_kw("被扶養配偶者の認定"),
        "kw_dai3go_nenkan_shunyu": mhlw_kw("第三号被保険者 年間収入"),
        "kw_kokunen_dai3go_shunyu": mhlw_kw("国民年金第三号被保険者 収入"),
    },
    # 同 本文：本文検索で見つかった通知（第3号の認定基準の運用、機構の設立時の既存通知の扱い、平成5年4月の健保令の施行通知、
    # 被扶養者の認定に関する近年の通知）
    "mhlw_docs": {
        "S610401_chohokenhatsu17": tdoc("00tb1694"),
        "S610401_chohokenhatsu18_unyo": tdoc("00tb1695"),
        "S610331_chohohatsu12_shiko": tdoc("00tb1174"),
        "H220101_nenhatsu101002_kizon": tdoc("00tb5871"),
        "H050407_chohohatsu13_hohatsu36": tdoc("00tb0141"),
        "H05_kounen_jigyo_unei": tdoc("00ta3218"),
        "S601012_jizen_junbi": tdoc("00tb1449"),
        "H120228_bunken_iko": tdoc("00tb1777"),
        "R7_19_23_nintei_a": tdoc("00tc9249"),
        "R7_19_23_nintei_b": tdoc("00tc9250"),
        "R7_19_23_qa": tdoc("00tc9628"),
        "R7_rodo_keiyaku": tdoc("00tc9348"),
        "R7_jigyonushi_shomei_kokyuka": tdoc("00tc9347"),
        "R5_jigyonushi_shomei_a": tdoc("00tc8005"),
        "R5_jigyonushi_shomei_b": tdoc("00tc8012"),
        "shunyu_kakunin_ryuiten": tdoc("00tc5007"),
    },
    # 同：厚労省年金局「紙上Live講義」が被扶養配偶者の認定基準の通知として挙げた「平成15年3月24日 庁文発第798号」を探す
    #（種別だけの指定はエラー〔ERR-WEB-023〕になったので、日付だけ、又は種別と番号の両方を指定する）
    "mhlw_h150324": {
        "srch_H150324": mhlw_date_search(4, 15, 3, 24),
        "srch_H15_chobunhatsu798": mhlw_date_search(4, 15, 1, 1, 15, 12, 31, shubetsu="庁文発", bango="798"),
        "kw_nintei_kijun_ichibu_kaisei": mhlw_kw("被扶養配偶者の認定基準の一部"),
        "kw_nintei_kijun_kaisei": mhlw_kw("被扶養配偶者の認定基準の改正"),
        "kw_chobunhatsu798": mhlw_kw("庁文発第七九八号"),
    },
    # 同 情報詳細検索（日付と種別）。［KT2］p.5 の認定基準の経緯（62年5月・元年5月・4年1月・5年4月）の前後の「庁保発」の通知
    "mhlw_dates": {
        "S62_chohohatsu": mhlw_date_search(3, 62, 1, 1, 62, 12, 31, shubetsu="庁保発"),
        "H01_chohohatsu": mhlw_date_search(4, 1, 1, 8, 1, 12, 31, shubetsu="庁保発"),
        "H03_chohohatsu": mhlw_date_search(4, 3, 1, 1, 3, 12, 31, shubetsu="庁保発"),
        "H04_chohohatsu": mhlw_date_search(4, 4, 1, 1, 4, 12, 31, shubetsu="庁保発"),
        "H05_chohohatsu": mhlw_date_search(4, 5, 1, 1, 5, 12, 31, shubetsu="庁保発"),
        "H05_hohatsu": mhlw_date_search(4, 5, 1, 1, 5, 12, 31, shubetsu="保発"),
    },
    # 日本年金機構「主な疑義照会と回答について」（年金事務所等から本部への照会と回答）
    "nenkin_gigi": {
        "gigishokai_page": "https://www.nenkin.go.jp/service/seidozenpan/gigishokai.html",
        "kokunen_tekiyou": NENKIN_GIGI + "kokunen_tekiyou.pdf",
        "kokunen_hokenryo": NENKIN_GIGI + "kokunen_hokenryo.pdf",
        "kounen_tekiyou": NENKIN_GIGI + "kounen_tekiyou.pdf",
    },
    # 厚労省の審議会・検討会などの資料（検索エンジンで「第3号被保険者」「被扶養配偶者の認定基準」で見つかった PDF。中身は取得後に確かめる）
    "mhlw_shiryo": {
        "c_0000088039": "https://www.mhlw.go.jp/content/12500000/0000088039.pdf",
        "c_0000086586": "https://www.mhlw.go.jp/file/06-Seisakujouhou-12500000-Nenkinkyoku/0000086586.pdf",
        "c_0000086587": "https://www.mhlw.go.jp/file/06-Seisakujouhou-12500000-Nenkinkyoku/0000086587.pdf",
        "s_2r9852000001789o": "https://www.mhlw.go.jp/stf/shingi/2r9852000001784y-att/2r9852000001789o.pdf",
        "s_2r98520000017893": "https://www.mhlw.go.jp/stf/shingi/2r9852000001784y-att/2r98520000017893.pdf",
        "s_2r9852000001q11t": "https://www.mhlw.go.jp/stf/shingi/2r9852000001q0wz-att/2r9852000001q11t.pdf",
        "c_001745398": "https://www.mhlw.go.jp/content/12500000/001745398.pdf",
        "c_001763351": "https://www.mhlw.go.jp/content/12500000/001763351.pdf",
        "c_001743078": "https://www.mhlw.go.jp/content/12500000/001743078.pdf",
    },
    # 社会保険審査会の裁決例（厚労省のページに掲載された PDF。検索エンジンで「平成5年3月5日」「被扶養配偶者 認定基準 国民年金」で見つかったもの）
    "shinsakai": {
        "shinsa_r02_03_15_01": "https://www.mhlw.go.jp/topics/bukyoku/shinsa/syakai/dl/05-r02_03/15_01.pdf",
        "shinsa_r02_03_06_11": "https://www.mhlw.go.jp/topics/bukyoku/shinsa/syakai/dl/05-r02_03/06_11.pdf",
        "shinsa_r02_03_06_04": "https://www.mhlw.go.jp/topics/bukyoku/shinsa/syakai/dl/05-r02_03/06_04.pdf",
    },
    # 日本年金機構：第3号被保険者・被扶養者の認定の案内（労働契約による判定の案内を含む）
    "nenkin_pages": {
        "kokunen_kanyu_20140627": "https://www.nenkin.go.jp/service/kokunen/kanyu/20140627-01.html",
        "kokunen_kanyu_20150119": "https://www.nenkin.go.jp/service/kokunen/kanyu/20150119.html",
        "oshirase_20220225": "https://www.nenkin.go.jp/oshirase/taisetu/2022/202202/20220225.html",
        "oshirase_20250819": "https://www.nenkin.go.jp/oshirase/taisetu/2025/202508/0819.html",
    },
    # 国会会議録（追加）：平成14年4月16日 参議院厚生労働委員会で「御指摘の通知」と答えた発言の前後、平成5年前後の被扶養者の収入基準の説明
    "kokkai2": {
        "kk_H140416_sangiin_kosei": "https://kokkai.ndl.go.jp/api/speech?" + urllib.parse.urlencode(
            {"issueID": "115414260X00620020416", "any": "被扶養配偶者", "maximumRecords": "100", "recordPacking": "json"}),
        "kk_hifuyo_130_H04_H06": kokkai("被扶養者 百三十万円", "1992-01-01", "1994-12-31"),
        "kk_hifuyo_kijun_hikiage_S62_H06": kokkai("被扶養者 認定基準 引き上げ", "1987-01-01", "1994-12-31"),
        "kk_dai3go_shunyu_kijun_all": kokkai("第三号被保険者 収入基準", "1985-01-01", "2026-11-08"),
        "kk_dai3go_hifuyo_nintei_kijun_all": kokkai("第三号被保険者 被扶養配偶者 認定", "1985-01-01", "2026-11-08"),
    },
    # 国会会議録（追加2）：平成5年3月5日 衆議院予算委員会第二分科会の被扶養者の認定基準のやり取り全体、
    # 昭和62年〜平成6年の「被扶養配偶者」「第三号被保険者 認定」を含む発言
    "kokkai3": {
        "kk_H050305_yosan2": "https://kokkai.ndl.go.jp/api/speech?" + urllib.parse.urlencode(
            {"issueID": "112605272X00219930305", "any": "被扶養者", "maximumRecords": "100", "recordPacking": "json"}),
        "kk_hifuyo_haigusha_S62_H06": kokkai("被扶養配偶者", "1987-01-01", "1994-12-31"),
        "kk_dai3go_nintei_S62_H06": kokkai("第三号被保険者 認定", "1987-01-01", "1994-12-31"),
    },
    # 同 情報詳細検索（種別と番号）：社会保険審査会の裁決（令和元年（国）第263号）が［S61］の「最終改正」として書く
    # 「平成5年3月15日 庁保発第5号」が、データベースに載っているかを、平成5年の1年間で種別・番号を指定して確かめる
    #（第2ラウンドの日付検索 平成5年3月1日〜31日の48件には無かった）。比較のため同じ年の庁保発第6号も引く
    "mhlw_h05_no5": {
        "srch_H05_chohohatsu_5": mhlw_date_search(4, 5, 1, 1, 5, 12, 31, shubetsu="庁保発", bango="5"),
        "srch_H05_chohohatsu_6": mhlw_date_search(4, 5, 1, 1, 5, 12, 31, shubetsu="庁保発", bango="6"),
    },
    # 同（2026-11-11 追加）：平成5年の庁保発 第1号〜第4号（第5号の前の番号の日付を確かめる。第5号・第6号は mhlw_h05_no5 で取得済み）と、
    # 本文検索で「平成五年三月一五日」「庁保発第五号」を引く通知があるか（本文の数字は漢数字の一字ずつの表記。00tb1695 の「昭和五五年五月一六日」による）
    "mhlw_h05_neighbors": {
        "srch_H05_chohohatsu_1": mhlw_date_search(4, 5, 1, 1, 5, 12, 31, shubetsu="庁保発", bango="1"),
        "srch_H05_chohohatsu_2": mhlw_date_search(4, 5, 1, 1, 5, 12, 31, shubetsu="庁保発", bango="2"),
        "srch_H05_chohohatsu_3": mhlw_date_search(4, 5, 1, 1, 5, 12, 31, shubetsu="庁保発", bango="3"),
        "srch_H05_chohohatsu_4": mhlw_date_search(4, 5, 1, 1, 5, 12, 31, shubetsu="庁保発", bango="4"),
        "kw_H050315": mhlw_kw("平成五年三月一五日"),
        "kw_chohohatsu5": mhlw_kw("庁保発第五号"),
    },
    # 同（2026-11-11 追加）：「庁保発第五号」の本文検索は 23 件で、1頁目は 20 件だけだったので、2頁目（hidden の page=1）を引く
    "mhlw_h05_neighbors2": {
        "kw_chohohatsu5_p1": mhlw_kw("庁保発第五号", page=1),
    },
    # 社会保険審査会の裁決（2026-11-11 追加）：検索エンジンで「社会保険審査会 裁決 第３号被保険者 被扶養配偶者の認定基準について
    # 昭和６１年３月３１日庁保発第１３号」で 15_01.pdf と同じフォルダに出た 06_05.pdf。中身（国民年金の事案か、［S61］を引くか）は取得後に確かめる
    "shinsakai2": {
        "shinsa_r02_03_06_05": "https://www.mhlw.go.jp/topics/bukyoku/shinsa/syakai/dl/05-r02_03/06_05.pdf",
    },
    # 同（2026-11-11 追加）：検索エンジンで「"被扶養配偶者認定基準" 社会保険審査会 第３号被保険者 裁決 国民年金法施行令第４条」で出た
    # 裁決 2 件と年金局のフォルダの PDF 1 件（001745398.pdf は mhlw_shiryo で 404。中身は取得後に確かめる）
    "shinsakai3": {
        "shinsa_r04_05_07_02": "https://www.mhlw.go.jp/topics/bukyoku/shinsa/syakai/dl/05-r04_05/07_02.pdf",
        "shinsa_r02_03_06_10": "https://www.mhlw.go.jp/topics/bukyoku/shinsa/syakai/dl/05-r02_03/06_10.pdf",
        "c_001746546": "https://www.mhlw.go.jp/content/12500000/001746546.pdf",
    },
    # 国会会議録検索システム（発言単位）。昭和61年〜平成6年に「被扶養配偶者」「認定基準」を含む発言など
    "kokkai": {
        "kk_hifuyo_nintei_S61_H06": kokkai("被扶養配偶者 認定基準", "1985-01-01", "1994-12-31"),
        "kk_dai3go_130_H04_H06": kokkai("第三号被保険者 百三十万円", "1992-01-01", "1994-12-31"),
        "kk_dai3go_kijun_all": kokkai("第三号被保険者 認定基準 通知", "1985-01-01", "2026-11-08"),
        "kk_hifuyo_haigusha_nintei_all": kokkai("被扶養配偶者の認定", "1985-01-01", "2026-11-08"),
    },
}


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
        if tag == "iframe" and a.get("src"):
            self.links.append({"href": a["src"], "text": "[iframe] " + (a.get("title") or "")})
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


def read_with_deadline(resp, seconds=90):
    """本文を少しずつ読み、全体の制限時間を超えたら打ち切る。"""
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
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.geturl(), dict(r.headers), read_with_deadline(r)
    except urllib.error.HTTPError as e:
        return e.code, url, dict(e.headers or {}), e.read() if hasattr(e, "read") else b""


def ext_for(ctype, url, body):
    c = (ctype or "").lower()
    if "pdf" in c or url.lower().endswith(".pdf"):
        return ".pdf"
    if "json" in c or "/api/" in url:
        return ".json"
    if "html" in c:
        return ".html"
    return ".bin"


def kokkai_text(body):
    """国会会議録 API の JSON（信頼できないデータ）を json.loads で読み、発言ごとの記録をテキストにする。"""
    d = json.loads(body.decode("utf-8"))
    lines = [f"numberOfRecords={d.get('numberOfRecords')} numberOfReturn={d.get('numberOfReturn')} "
             f"startRecord={d.get('startRecord')} nextRecordPosition={d.get('nextRecordPosition')}"]
    if "message" in d:
        lines.append("message=" + json.dumps(d.get("message"), ensure_ascii=False) + " details=" + json.dumps(d.get("details"), ensure_ascii=False))
    for r in d.get("speechRecord", []) or []:
        lines.append("")
        lines.append("=" * 60)
        lines.append(f"date={r.get('date')} house={r.get('nameOfHouse')} meeting={r.get('nameOfMeeting')} issue={r.get('issue')} "
                     f"speechOrder={r.get('speechOrder')} speaker={r.get('speaker')} position={r.get('speakerPosition')} group={r.get('speakerGroup')}")
        lines.append(f"speechURL={r.get('speechURL')}")
        lines.append(f"meetingURL={r.get('meetingURL')}")
        lines.append(str(r.get("speech") or ""))
    return "\n".join(lines)


def run_set(name, urls, ts):
    dl = ROOT / ".work" / "downloads" / f"{ts}_R3X_dai3go_{name}"
    dl.mkdir(parents=True, exist_ok=False)
    tx = OUT / "text" / f"{ts}_{name}"
    tx.mkdir(parents=True, exist_ok=False)
    log = []
    for i, (sid, url) in enumerate(urls.items()):
        if i:
            time.sleep(WAIT)
        rec = {"id": sid, "url": url}
        try:
            st, final, hdr, body = get(url)
            ctype = hdr.get("Content-Type", "")
            ext = ext_for(ctype, final, body)
            (dl / f"{sid}{ext}").write_bytes(body)
            rec.update({
                "status": st, "final_url": final, "content_type": ctype, "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "last_modified": hdr.get("Last-Modified"), "etag": hdr.get("ETag"),
                "saved": str((dl / f"{sid}{ext}").relative_to(ROOT)).replace("\\", "/"),
            })
            text = None
            if ext == ".html" and body:
                s, cs = decode(body, ctype)
                p = Extract()
                p.feed(s)
                links = []
                for lk in p.links:
                    h = lk["href"]
                    if h and not h.startswith(("javascript:", "mailto:", "#")):
                        links.append({"href": urllib.parse.urljoin(final, h), "text": lk["text"]})
                text = p.text()
                (tx / f"{sid}.links.json").write_text(json.dumps(links, ensure_ascii=False, indent=1), encoding="utf-8")
                rec.update({"charset": cs, "title": " ".join(p.title.split()), "n_links": len(links)})
                header = f"# source={final}\n# fetched_at={ts}\n# charset={cs}\n\n"
            elif ext == ".json" and body:
                text = kokkai_text(body)
                header = f"# source={final}\n# fetched_at={ts}\n\n"
            if text is not None:
                (tx / f"{sid}.txt").write_text(header + text, encoding="utf-8")
                rec.update({"text_chars": len(text), "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                            "text": str((tx / f"{sid}.txt").relative_to(ROOT)).replace("\\", "/")})
        except Exception as e:  # noqa: BLE001
            rec["error"] = repr(e)
        log.append(rec)
        (OUT / f"{name}_{ts}.json").write_text(
            json.dumps({"set": name, "fetched_at_local": ts, "user_agent": UA, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"),
                        "results": log}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        print(json.dumps({k: rec.get(k) for k in ("id", "status", "bytes", "last_modified", "title", "error")}, ensure_ascii=False), flush=True)


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")
    if not argv or argv[0] == "--list":
        for k, v in SETS.items():
            print(k, len(v))
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    for i, name in enumerate(argv):
        if i:
            time.sleep(WAIT)
        run_set(name, SETS[name], ts)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

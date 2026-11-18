"""R2X_yoshiki_verify: トピック yoshiki（申告書の様式の欄の対応）の文書の主張を、一次情報に当たり直して独立に確かめる（反証役）。

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_yoshiki_verify.py web
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_yoshiki_verify.py egov
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_yoshiki_verify.py pdf <web で作ったダウンロードのディレクトリ>
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_yoshiki_verify.py docs

- web  ：国税庁・e-Tax の公開ページと様式 PDF を取り直し、前の担当の記録（scripts/results/R2X_yoshiki_fetch/fetch_*.json）の
         SHA-256・Last-Modified と比べ、文書が引用・要約した文言を照合する（`!` で始まる文字列は「無いこと」を確かめる）。
         手引き（HTML 版）の欄番号の画像（/izon/）は、ファイル名の番号を〔番号〕として本文に入れ、alt との食い違いも数える。
         通達の目次は表の行ごとに「様式番号・様式名・リンク先」を組にして確かめる。
- egov ：e-Gov 法令API v2 で所得税法・同法施行規則（3つの版）と租税特別措置法を取り、版の情報と条文の文言を照合する。
- pdf  ：web で取り直した様式 PDF（空のユーザーパスワードで AESV2 暗号化）を、このスクリプトの中の独自の読み取りで復号し、
         テキスト層の欄コードと行番号・科目名の対応、欄コードの数、様式ID、印字の文言を確かめる。
         様式ページの PDF と通達の別冊の PDF の、ページごとの画像（復号後）と内容ストリームの一致も確かめる。
- docs ：文書の種類分けと参照のルール（仮説に外部 URL がないか等）と、個人の情報に当たる語がないかを機械的に調べる。

- 標準ライブラリのみ。前の担当のスクリプト（R2X_yoshiki_*.py）は import も流用もしない。
  AES-128 の復号は scripts/IMPL_output_verify.py（別の検証者のスクリプト）の実装を写し（import しない）、FIPS-197 の試験ベクタで自己検査する。
  PDF の内容ストリームの読み取り（文字の位置）は、このスクリプトで新しく書いた。
- e-Gov 法令API v2 の叩き方は scripts/R1_egov_articles.py・scripts/IMPL_output_verify.py の形（GET、UA、間隔、/law_data/{law_id}?asof=）を写した。
- ダウンロードしたもの（信頼できないデータ）は実行ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_R2X_yoshiki_verify_<sub>/ に置く。その中では何も実行しない。
- 取得は GET だけ。リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。Cookie は使わない。
  対象ホストは laws.e-gov.go.jp・www.nta.go.jp・www.e-tax.nta.go.jp だけ（他ホストへのリダイレクトは止める）。
  e-Tax の CAB（「ダウンロードされた方は…同意したものとみなされます」）は取得しない。官報は取得しない。
- 出力は scripts/results/R2X_yoshiki_verify/<sub>/ 。照合は NFKC 正規化・空白除去・ダッシュ類の統一・『』→「」のうえで行う。
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
import zlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
SLEEP = 1.5
OUT = ROOT / "scripts" / "results" / "R2X_yoshiki_verify"
ALLOWED = {"laws.e-gov.go.jp", "www.nta.go.jp", "www.e-tax.nta.go.jp"}
API = "https://laws.e-gov.go.jp/api/2"
MAX_BYTES = 40 * 1024 * 1024


class _NoOffHost(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).hostname not in ALLOWED:
            raise urllib.error.HTTPError(newurl, code, "off-host redirect blocked", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(_NoOffHost())


def fetch(url, accept="*/*"):
    assert urllib.parse.urlsplit(url).hostname in ALLOWED, url
    assert not url.lower().endswith(".cab"), url
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept}, method="GET")
    try:
        with OPENER.open(req, timeout=300) as r:
            body = r.read(MAX_BYTES + 1)
            st, final, hdr = r.status, r.geturl(), dict(r.headers)
    except urllib.error.HTTPError as e:
        body, st, final, hdr = (e.read(1024 * 1024) if e.fp else b""), e.code, url, dict(e.headers or {})
    time.sleep(SLEEP)
    if len(body) > MAX_BYTES:
        return st, final, hdr, None
    return st, final, hdr, body


DASHES = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\uff0d"), "-")


def norm(s):
    s = unicodedata.normalize("NFKC", s).translate(DASHES)
    s = s.replace("『", "「").replace("』", "」")
    return re.sub(r"\s+", "", s)


def find(text, needle, width=50):
    t, n = norm(text), norm(needle)
    i = t.find(n)
    if i < 0:
        return False, ""
    return True, t[max(0, i - width): i + len(n) + width]


# ======================================================================== web
class Html(html.parser.HTMLParser):
    """本文テキスト、リンク、表の行（テキストとリンク）、/izon/ の画像（ファイル名の番号と alt）を集める。"""
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "dt", "dd", "table", "th", "td", "section", "ul", "ol", "dl"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.links, self.skip, self.rows, self.row, self.izon = [], [], 0, [], None, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        if tag in self.BLOCK:
            self.out.append("\n")
        if tag in ("tr", "li"):
            self.row = {"text": [], "links": []}
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
            if self.row is not None:
                self.row["links"].append(a["href"])
        if tag == "img" and not self.skip:
            src = a.get("src") or ""
            m = re.search(r"/izon/(\d+)[^/]*$", src)
            if m:
                num = str(int(m.group(1)))
                self.izon.append({"file_num": num, "alt": a.get("alt"), "src": src})
                self.out.append(f"〔{num}〕")
                if self.row is not None:
                    self.row["text"].append(f"〔{num}〕")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.skip:
            self.skip -= 1
        if tag in self.BLOCK:
            self.out.append("\n")
        if tag in ("tr", "li") and self.row is not None:
            self.rows.append({"text": "".join(self.row["text"]), "links": self.row["links"]})
            self.row = None

    def handle_data(self, d):
        if not self.skip:
            self.out.append(d)
            if self.row is not None:
                self.row["text"].append(d)


def decode_html(body):
    m = re.search(rb'charset=["\']?([A-Za-z0-9_\-]+)', body[:4096])
    enc = (m.group(1).decode().lower() if m else "utf-8")
    if enc in ("shift_jis", "sjis", "x-sjis", "shift-jis"):
        enc = "cp932"
    try:
        return body.decode(enc)
    except (UnicodeDecodeError, LookupError):
        return body.decode("utf-8", "replace")


NTA = "https://www.nta.go.jp"
TEBIKI = NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/03/"
TSU = NTA + "/law/tsutatsu/kobetsu/shotoku/shinkoku/"
YOS = NTA + "/taxes/shiraberu/shinkoku/yoshiki/"
# (鍵, URL, [照合する文字列...]。先頭が "!" は「無いこと」を確かめる)
WEB = [
    ("teiyo_01", TSU + "001115/01.htm", [
        "課所6-51", "課審3-30", "課資5-39", "官事6-218", "課法3-70", "徴管2-73", "課消3-72", "査調2-44", "課料1-44", "査察1-60",
        "平成12年11月15日", "国税局長殿", "国税庁長官", "「個人課税事務提要（様式編Ⅰ）」の制定について（法令解釈通達）",
        "標題のことについては、所得税法等の規定により、納税者から提出される書類及び納税者に通知する書類の様式を別冊のとおり制定したので、今後これにより適切に実施されたい。",
        "申告書等の処理事務", "第12章", "!社会保険料控除等の明細書"]),
    ("sinkoku", TSU + "sinkoku.htm", ["「個人課税事務提要（様式編Ⅰ）」の制定について", "（平成12年11月15日）（令和８年８月31日付改正分まで更新）"]),
    ("kaisei1", TSU + "kaisei/kaisei1.htm", ["令和8年8月31日", "令和8年6月30日", "令和8年3月27日", "令和7年12月22日", "260831/index.htm", "250630/index.htm"]),
    ("k260831", TSU + "kaisei/260831/index.htm", [
        "課個３―15", "課資６―101", "令和８年８月31日",
        "別冊について、別紙１のとおり目次を改正し、別紙２に掲げる帳票を別紙３のとおり改正したから、令和８年８月31日以後はこれによられたい。",
        "22,336KB", "改訂目次一覧", "改訂様式一覧"]),
    ("k250630", TSU + "kaisei/250630/index.htm", [
        "課個３－９", "課資６－67", "令和８年６月30日", "別紙１に掲げる帳票を別紙２のとおり改正したから、今後はこれによられたい。", "159,457KB"]),
    ("k260327", TSU + "kaisei/260327/index.htm", ["課個３―４", "課資６―16", "令和８年３月27日", "別紙１に掲げる帳票を別紙２のとおり改正"]),
    ("k251222", TSU + "kaisei/251222/index.htm", ["課個３―12", "課資６―73", "令和７年12月22日", "別紙１に掲げる帳票を別紙２のとおり改正",
                                                  "令和８年１月１以後はこれによられたい"]),
    ("ai_ocr", "https://www.e-tax.nta.go.jp/shiyo/ksk2/ksk2_ai-ocr.htm", [
        "AI-OCR開発は、上記の特性を踏まえ、様式の改定とあわせて行っています。", "AI-OCR様式のイメージ", "様式IDを追加",
        "様式ID等を識別する2次元コードを追加", "各項目に識別コードを追加（赤枠部分）"]),
    ("layout", "https://www.e-tax.nta.go.jp/shiyo/ksk2/ksk2_layout.htm", [
        "対象の帳票は「AI-OCR化対象帳票一覧」を、各帳票のレイアウトは「帳票レイアウト設計書」を、QRコードの仕様は「QRコード仕様書」を、それぞれリンクからダウンロードしてご確認ください。",
        "なお、ダウンロードされた方は、「e-Tax等仕様公開に当たっての注意事項」に同意したものとみなされますので、ご承知おきください。",
        "令和8年9月2日更新", "約228KB", "約783MB", "令和8年1月30日時点", "約33.2KB", "令和8年10月30日更新", "約170KB", "約865MB",
        "税制改正等により開発予定の帳票について", "ai-ocr_list.CAB", "ai-ocr_layout.CAB", "draft/ai-ocr_list.CAB", "draft/ai-ocr_layout.CAB", "ai-ocr_qr.CAB"]),
    ("r08", NTA + "/taxes/shiraberu/shinkoku/syotoku/r08.htm", []),
    ("r07", NTA + "/taxes/shiraberu/shinkoku/syotoku/r07.htm", ["令和７年分以降用", "r07/02.pdf", "r07/03.pdf", "r07/10.pdf", "017.pdf", "ref4.pdf"]),
    ("aiocr_xlsx", NTA + "/taxes/shiraberu/sodan/ai-ocr.xlsx", []),
    ("a1_1", NTA + "/taxes/tetsuzuki/shinsei/annai/shinkoku/annai/1557_2.htm", [
        "土地建物等の譲渡所得がある方", "申告分離課税の株式等の譲渡所得等がある方", "申告分離課税の上場株式等の配当所得等がある方",
        "申告分離課税の先物取引の雑所得等がある方", "山林所得や退職所得がある方", "その年分の所得金額が赤字の方",
        "その年分の所得金額から雑損控除額を控除すると赤字になる方", "その年分の所得金額から繰越損失額を控除すると赤字になる方",
        "翌年に繰り越す損失がある方は、この計算書を使用せず、申告書第四表（損失申告用）を使用します。"]),
    ("ta1130", NTA + "/taxes/shiraberu/taxanswer/shotoku/1130.htm", [
        "令和8年4月1日現在法令等",
        "なお、令和8年分以後の所得税に係る確定申告書を令和9年1月1日以後に提出するときは、国民年金の保険料または国民年金基金の掛金の金額を証する書類もしくは電磁的記録印刷書面の添付または提示に代えて、一定の事項の記載がある明細書を確定申告書に添付することができます。"]),
    ("ta1140", NTA + "/taxes/shiraberu/taxanswer/shotoku/1140.htm", ["令和8年4月1日現在法令等", "!一定の事項の記載がある明細書"]),
    ("ta1145", NTA + "/taxes/shiraberu/taxanswer/shotoku/1145.htm", ["令和8年4月1日現在法令等", "!一定の事項の記載がある明細書"]),
    # 推測の文書（I7）が確かめ方として挙げた URL が存在するか
    ("ref1_ki", YOS + "04/pdf/ref1-ki.pdf", []),
    ("tebiki_008", NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/pdf/008.pdf", []),
    # 手引き（HTML 版）
    ("t3-2_01", TEBIKI + "order2/3-2_01.htm", [
        "『青色申告決算書』又は『収支内訳書』", "優良な電子帳簿", "会計ソフト等", "正規の簿記の原則", "複式簿記以外の簡易な方法",
        "記帳の仕方が分からない", "４又は５に当てはまる場合、10万円を超える青色申告特別控除の適用は受けられません。",
        "程度・仕事の内容は、白色申告者のみ記入します。", "措法26", "措法27"]),
    ("t3-2_08_1", TEBIKI + "order2/3-2_08_1.htm", ["1円未満の端数があるときは、その端数を切り捨てます。", "損益の通算の計算書", "総合譲渡用"]),
    ("t3-2_09", TEBIKI + "order2/3-2_09.htm", ["〔1〕欄から〔6〕欄までの計＋〔10〕欄＋〔11〕欄の金額を記入",
                                             "第一表〔62〕欄「本年分で差し引く繰越損失額」に記載がある場合",
                                             "〔62〕欄の金額を差し引いた金額を〔12〕欄に記入します。"]),
    ("t3-3_10", TEBIKI + "order3/3-3_10.htm", ["社会保険料等の金額", "小規模企業共済等掛金", "源泉徴収分", "うち年末調整等以外"]),
    ("t3-3_11", TEBIKI + "order3/3-3_11.htm", ["源泉徴収分"]),
    ("t3-3_12", TEBIKI + "order3/3-3_12.htm", ["源泉徴収分"]),
    ("t3-3_13", TEBIKI + "order3/3-3_13.htm", ["地震保険料"]),
    ("t3-3_14", TEBIKI + "order3/3-3_14.htm", ["ひとり親控除"]),
    ("t3-3_15_2", TEBIKI + "order3/3-3_15_2.htm", ["勤労学生控除"]),
    ("t3-3_17", TEBIKI + "order3/3-3_17.htm", ["区分１", "国外居住親族"]),
    ("t3-3_21", TEBIKI + "order3/3-3_21.htm", ["基礎控除"]),
    ("t3-3_22", TEBIKI + "order3/3-3_22.htm", ["〔13〕欄から〔25〕欄までを合計"]),
    ("t3-3_23", TEBIKI + "order3/3-3_23.htm", ["雑損控除"]),
    ("t3-3_25", TEBIKI + "order3/3-3_25.htm", ["条例", "共同募金"]),
    ("t3-3_26", TEBIKI + "order3/3-3_26.htm", ["〔26〕欄から〔29〕欄までを合計"]),
    ("t3-3_y02", TEBIKI + "order3/yogo/3-3_y02.htm", []),
    ("t3-4_28", TEBIKI + "order4/3-4_28.htm", ["配当控除"]),
    ("t3-4_29", TEBIKI + "order4/3-4_29.htm", ["中小企業者が機械等を取得した場合"]),
    ("t3-4_30", TEBIKI + "order4/3-4_30.htm", ["住宅借入金等特別控除額の計算明細書", "居住開始年月日"]),
    ("t3-4_31", TEBIKI + "order4/3-4_31.htm", ["政党等寄附金"]),
    ("t3-4_32", TEBIKI + "order4/3-4_32.htm", ["住宅耐震改修", "住宅特定改修", "認定住宅等新築等"]),
    ("t3-4_36", TEBIKI + "order4/3-4_36.htm", ["「0」"]),
    ("t3-4_37", TEBIKI + "order4/3-4_37.htm", ["災害減免"]),
    ("t3-4_40", TEBIKI + "order4/3-4_40.htm", ["予定納税額"]),
    ("t3-4_40_1", TEBIKI + "order4/3-4_40_1.htm", []),
    ("t3-4_41_1", TEBIKI + "order4/3-4_41_1.htm", []),
    ("t3-4_42", TEBIKI + "order4/3-4_42.htm", ["修正申告"]),
    ("t3-4_42_1", TEBIKI + "order4/3-4_42_1.htm", ["外国税額控除"]),
    ("t3-5_01", TEBIKI + "order5/3-5_01.htm", [
        "前年分から繰り越された損失額を総所得金額等から差し引く場合で、翌年以後に繰り越す損失額がないときに、その差し引く繰越損失額を記入します。",
        "第四表（損失申告用）を使用する方は、この欄は記入しません。",
        "株式等の譲渡所得等、申告分離課税の上場株式等の配当所得等及び先物取引の雑所得等から差し引く繰越損失額は、この繰越損失額には含めません。",
        "公的年金等に係る雑所得以外の合計所得金額", "未納付の源泉徴収税額"]),
    ("t3-5_02", TEBIKI + "order5/3-5_02.htm", ["延納"]),
    ("t3-6_03", TEBIKI + "order6/3-6_03.htm", ["事業税"]),
]
# バイナリ（ハッシュと Last-Modified だけ。中身は pdf サブコマンドと Read ツールで読む）
PDFS = [
    ("r07_01", YOS + "01/shinkokusho/pdf/r07/01.pdf"), ("r07_02", YOS + "01/shinkokusho/pdf/r07/02.pdf"),
    ("r07_03", YOS + "01/shinkokusho/pdf/r07/03.pdf"), ("r07_05", YOS + "01/shinkokusho/pdf/r07/05.pdf"),
    ("r07_09", YOS + "01/shinkokusho/pdf/r07/09.pdf"), ("r07_10", YOS + "01/shinkokusho/pdf/r07/10.pdf"),
    ("r07_12", YOS + "01/shinkokusho/pdf/r07/12.pdf"), ("r07_13", YOS + "01/shinkokusho/pdf/r07/13.pdf"),
    ("ref1", YOS + "04/pdf/ref1.pdf"), ("ref3", YOS + "03/pdf/ref3.pdf"), ("s017", YOS + "017.pdf"), ("ref4", YOS + "03/pdf/ref4.pdf"),
    ("kinyu_001-1", NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/pdf/001-1.pdf"),
    ("kinyu_O1-1", NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/pdf/O/O1-1.pdf"),
    ("tebiki_003", NTA + "/taxes/shiraberu/shinkoku/tebiki/2025/pdf/003.pdf"),
    ("t06_081", TSU + "001115/pdf/06/06_081.pdf"), ("t06_082", TSU + "001115/pdf/06/06_082.pdf"),
    ("t06_083", TSU + "001115/pdf/06/06_083.pdf"), ("t06_085", TSU + "001115/pdf/06/06_085.pdf"),
    ("t06_086", TSU + "001115/pdf/06/06_086.pdf"), ("t06_093", TSU + "001115/pdf/06/06_093.pdf"),
    ("t06_096", TSU + "001115/pdf/06/06_096.pdf"), ("t06_010-1", TSU + "001115/pdf/06/06_010-1.pdf"),
    ("t06_010-3", TSU + "001115/pdf/06/06_010-3.pdf"),
    ("k260831_02", TSU + "kaisei/260831/pdf/02.pdf"), ("k250630_01", TSU + "kaisei/250630/pdf/01.pdf"),
]
# 通達の目次の行：(様式番号, 様式名の一部, リンク先のファイル名 or None)
TOC = [
    ("個12-1007", "医療費控除の明細書", "06_010-1.pdf"), ("個12-1008", "医療費控除の明細書（次葉）", "06_010-2.pdf"),
    ("個12-1009", "セルフメディケーション税制の明細書", "06_010-3.pdf"), ("個12-1010", "セルフメディケーション税制の明細書（次葉）", "06_010-4.pdf"),
    ("個12-1005", "損益の通算の計算書", None), ("個12-1072", "申告書第一表", "06_081.pdf"), ("個12-1073", "申告書第二表", "06_082.pdf"),
    ("個12-1074", "申告書第三表（分離課税用）", "06_083.pdf"), ("個12-1075", "申告書第四表（一）（損失申告用）", "06_085.pdf"),
    ("個12-1076", "申告書第四表（二）（損失申告用）", "06_086.pdf"), ("個12-1080", "収支内訳書（一般用）", "06_093.pdf"),
    ("個12-1082", "収支内訳書（不動産所得用）", "06_095.pdf"), ("個12-1083", "青色申告決算書（一般用）", "06_096.pdf"),
    ("個12-1084", "青色申告決算書（不動産所得用）", "06_097.pdf"), ("個12-1085", "青色申告決算書（現金主義用）", None),
    ("個12-1086", "青色申告決算書（農業所得用）", None), ("個12-1089", "付表", None),
    ("個12-1103", "公的年金等に係る雑所得以外の合計所得金額に関する計算書", "06_137.pdf"),
    ("個09-1001", "更正の請求書", None), ("個09-1003", "純損失の繰戻しによる所得税の還付請求書", None),
]


def prev_records():
    """前の担当の取得記録（URL → 記録）を読む（ローカルの結果ファイル。ネットワークには出ない）。"""
    recs = {}
    for f in sorted((ROOT / "scripts" / "results" / "R2X_yoshiki_fetch").glob("fetch_*.json")):
        for r in json.loads(f.read_text(encoding="utf-8"))["results"]:
            recs.setdefault(r["url"], r)
    return recs


def cmd_web():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_yoshiki_verify_web"
    dl.mkdir(parents=True, exist_ok=False)
    out = OUT / "web"
    (out / "text").mkdir(parents=True, exist_ok=True)
    prev = prev_records()
    rec = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "robots": [], "pages": []}
    for host in ("www.nta.go.jp", "www.e-tax.nta.go.jp"):
        st, final, hdr, body = fetch(f"https://{host}/robots.txt")
        rec["robots"].append({"host": host, "status": st, "sha256": hashlib.sha256(body).hexdigest() if (st == 200 and body) else None,
                              "text": body.decode("utf-8", "replace")[:1500] if (st == 200 and body) else None})
    items = [(k, u, n) for k, u, n in WEB] + [(k, u, None) for k, u in PDFS]
    for key, url, needles in items:
        st, final, hdr, body = fetch(url)
        page = {"key": key, "url": url, "final_url": final, "status": st, "last_modified": hdr.get("Last-Modified"),
                "content_type": hdr.get("Content-Type")}
        if body is None:
            page["skipped"] = "too big"
            rec["pages"].append(page)
            continue
        ext = pathlib.PurePosixPath(urllib.parse.urlsplit(final).path).suffix or ".bin"
        fname = f"{key}{ext}"
        (dl / fname).write_bytes(body)
        sha = hashlib.sha256(body).hexdigest()
        p0 = prev.get(url) or {}
        page.update(bytes=len(body), sha256=sha, saved=fname, prev_sha256=p0.get("sha256"), prev_last_modified=p0.get("last_modified"),
                    same_sha_as_prev=(sha == p0.get("sha256")) if p0.get("sha256") else None, checks=[])
        if needles is not None and st == 200 and "html" in (hdr.get("Content-Type") or "html"):
            h = Html()
            h.feed(decode_html(body))
            text = re.sub(r"\n\s*\n+", "\n", "".join(h.out))
            (out / "text" / f"{key}.txt").write_text(f"# url={url}\n# final={final}\n# sha256={sha}\n\n{text}", encoding="utf-8")
            hay = text + "\n" + "\n".join(h.links)
            for n in needles:
                neg = n.startswith("!")
                n2 = n[1:] if neg else n
                ok, ctx = find(hay, n2)
                page["checks"].append({"needle": n2, "expect_found": not neg, "found": ok, "pass": ok != neg, "context": ctx})
            if h.izon:
                mism = sorted({(i["file_num"], i["alt"]) for i in h.izon if (i["alt"] or "") != i["file_num"]})
                page["izon"] = {"n": len(h.izon), "dirs": sorted({re.sub(r"/[^/]*$", "/", i["src"]) for i in h.izon}),
                                "file_vs_alt_mismatch": [list(m) for m in mism]}
            if key == "teiyo_01":
                page["toc"] = []
                for num, name, pdf in TOC:
                    rows = [r for r in h.rows if norm(num) in norm(r["text"])]
                    hit = [r for r in rows if norm(name) in norm(r["text"])]
                    link_ok = None if pdf is None else any(any(l.endswith(pdf) for l in r["links"]) for r in hit)
                    page["toc"].append({"num": num, "name": name, "pdf": pdf, "rows_with_num": len(rows), "row_has_name": bool(hit),
                                        "link_ok": link_ok, "row_text": [norm(r["text"])[:120] for r in rows[:3]],
                                        "row_links": [r["links"] for r in rows[:3]]})
            if key == "kaisei1":
                page["first_rows"] = [norm(r["text"])[:150] for r in h.rows[:6]]
        rec["pages"].append(page)
        print(key, st, sha[:16], page.get("same_sha_as_prev"), [c["pass"] for c in page.get("checks", [])])
    (out / "web_checks.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    md = [f"# 公開資料の再取得と文言の照合（実行 {ts}）", "", f"- 保存先：`{rec['download_dir']}`（中では何も実行していない）", "",
          "## robots.txt", ""] + [f"- {r['host']}: HTTP {r['status']} `{(r['sha256'] or '')[:16]}`" for r in rec["robots"]]
    md += ["", "## ページ", "", "| 鍵 | HTTP | 最終URL（違えば） | Last-Modified（今回／前回） | SHA-256 先頭16（今回） | 前回と同じ | 照合 |", "|---|---|---|---|---|---|---|"]
    for p in rec["pages"]:
        bad = [("（無いはずが有る）" if not c["expect_found"] else "（無い）") + c["needle"][:40] for c in p.get("checks", []) if not c["pass"]]
        fin = p["final_url"] if p["final_url"] != p["url"] else ""
        md.append(f"| {p['key']} | {p['status']} | {fin} | {p.get('last_modified')}／{p.get('prev_last_modified')} | `{(p.get('sha256') or '')[:16]}` | "
                  f"{p.get('same_sha_as_prev')} | {len(p.get('checks', [])) - len(bad)}/{len(p.get('checks', []))}{'：' + '／'.join(bad) if bad else ''} |")
    izon = [p for p in rec["pages"] if p.get("izon")]
    md += ["", "## 手引きの欄番号の画像（ファイル名の番号 ≠ alt）", ""]
    for p in izon:
        md.append(f"- {p['key']}: 画像 {p['izon']['n']} 個、ディレクトリ {p['izon']['dirs']}、食い違い {p['izon']['file_vs_alt_mismatch']}")
    t = next((p for p in rec["pages"] if p["key"] == "teiyo_01"), None)
    if t and t.get("toc"):
        md += ["", "## 通達の目次の行", "", "| 様式番号 | 様式名 | 行あり | 名前あり | リンク一致 |", "|---|---|---|---|---|"]
        md += [f"| {x['num']} | {x['name']} | {x['rows_with_num']} | {x['row_has_name']} | {x['link_ok']} |" for x in t["toc"]]
    (out / "web_checks.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("saved", dl)


# ======================================================================== e-Gov
def law_text(node):
    if isinstance(node, str):
        return node
    if node.get("tag") == "Rt":
        return ""
    return "".join(law_text(c) for c in node.get("children", []))


def kids(node, tag):
    return [c for c in node.get("children", []) if isinstance(c, dict) and c.get("tag") == tag]


def iter_nodes(node, path=()):
    if isinstance(node, dict):
        yield node, path
        for c in node.get("children", []):
            yield from iter_nodes(c, path + (node.get("tag"),))


def article(root, num):
    for n, p in iter_nodes(root):
        if n.get("tag") == "Article" and n.get("attr", {}).get("Num") == num and "SupplProvision" not in p:
            return n
    return None


def para(art, num):
    return next((p for p in kids(art, "Paragraph") if p.get("attr", {}).get("Num") == str(num)), None)


def item(par, num):
    return next((i for i in kids(par, "Item") if i.get("attr", {}).get("Num") == str(num)), None)


def caption(art):
    c = kids(art, "ArticleCaption")
    return law_text(c[0]) if c else ""


LAWS = {
    "shotoku": ("340AC0000000033", ["2025-12-31", "2026-12-31", "2027-01-01"]),
    "shotoku-ki": ("340M50000040011", ["2025-12-31", "2026-01-01", "2026-11-09", "2026-12-31", "2027-01-01"]),
    "sochi": ("332AC0000000026", ["2025-12-31", "2026-11-09"]),
}
# 前の担当が記録した版
EXPECT_REV = {
    ("shotoku", "2025-12-31"): ("340AC0000000033_20251218_507AC0000000013", "2025-12-18", "PreviousEnforced"),
    ("shotoku", "2026-12-31"): ("340AC0000000033_20261201_508AC0000000012", "2026-12-01", "UnEnforced"),
    ("shotoku", "2027-01-01"): ("340AC0000000033_20270101_508AC0000000012", "2027-01-01", "UnEnforced"),
    ("shotoku-ki", "2025-12-31"): ("340M50000040011_20251201_507M60000040018", "2025-12-01", "PreviousEnforced"),
    ("shotoku-ki", "2026-12-31"): ("340M50000040011_20261211_508M60000040017", "2026-12-11", "UnEnforced"),
    ("shotoku-ki", "2027-01-01"): ("340M50000040011_20270101_508M60000040017", "2027-01-01", "UnEnforced"),
}


def cmd_egov():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2X_yoshiki_verify_egov"
    dl.mkdir(parents=True, exist_ok=False)
    out = OUT / "egov"
    out.mkdir(parents=True, exist_ok=True)
    roots, revs, checks = {}, [], []
    for short, (law_id, asofs) in LAWS.items():
        for asof in asofs:
            url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
            st, final, hdr, body = fetch(url, "application/json")
            (dl / f"{short}_{asof}.json").write_bytes(body or b"")
            d = json.loads(body)
            ri = d.get("revision_info") or {}
            roots[(short, asof)] = d["law_full_text"]
            r = {"short": short, "asof": asof, "status": st, "law_title": ri.get("law_title"), "law_revision_id": ri.get("law_revision_id"),
                 "amendment_law_num": ri.get("amendment_law_num"), "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                 "current_revision_status": ri.get("current_revision_status"), "sha256": hashlib.sha256(body).hexdigest()}
            exp = EXPECT_REV.get((short, asof))
            if exp:
                r["expect"] = exp
                r["pass"] = (r["law_revision_id"], r["amendment_enforcement_date"], r["current_revision_status"]) == exp
            revs.append(r)
            print(short, asof, r["law_revision_id"], r.get("pass"))

    def chk(label, short, asof, node_fn, needle, expect=True):
        root = roots[(short, asof)]
        try:
            node = node_fn(root)
            text = law_text(node) if node is not None else ""
        except Exception as e:  # noqa
            text = f"<error {e!r}>"
        ok, ctx = find(text, needle)
        checks.append({"label": label, "law": short, "asof": asof, "needle": needle, "expect_found": expect, "found": ok,
                       "pass": ok == expect, "context": ctx or norm(text)[:200]})

    A = lambda n: (lambda r: article(r, n))  # noqa
    P = lambda n, p: (lambda r: para(article(r, n), p))  # noqa
    I = lambda n, p, i: (lambda r: item(para(article(r, n), p), i))  # noqa
    S, K = "shotoku", "shotoku-ki"
    v25, v26, v27 = "2025-12-31", "2026-12-31", "2027-01-01"
    # 所得税法第120条（2025-12-31 版）第3項・第4項・第6項
    chk("所法120③ 証明書類", S, v25, P("120", 3), "書類を当該申告書に添付し、又は当該申告書の提出の際提示しなければならない")
    chk("所法120④ 医療費控除の明細書", S, v25, P("120", 4), "医療費控除")
    chk("所法120④ 明細書", S, v25, P("120", 4), "明細書")
    chk("所法120⑥ 不動産所得・事業所得・山林所得", S, v25, P("120", 6), "不動産所得、事業所得若しくは山林所得を生ずべき業務を行う居住者")
    chk("所法120⑥ 前々年分の業務雑収入 千万円超", S, v25, P("120", 6), "千万円を超えるもの")
    chk("所法120⑥ 総収入金額及び必要経費の内容", S, v25, P("120", 6), "総収入金額及び必要経費の内容を記載した書類")
    # 所得税法第123条
    for i, w in [(1, "純損失の金額"), (2, "前年以前三年内"), (3, "雑損失の金額がある場合"), (4, "控除しないで計算した"),
                 (5, "翌年以後"), (6, "外国税額控除"), (7, "源泉徴収"), (8, "予納税額"), (9, "財務省令で定める事項")]:
        chk(f"所法123②{i}", S, v25, I("123", 2, i), w)
    chk("所法123③（2025-12-31）", S, v25, P("123", 3), "第百二十条第三項から第七項までの規定は、第一項の規定による申告書の提出について準用する")
    chk("所法123③（2027-01-01）", S, v27, P("123", 3), "第百二十条第三項から第九項までの規定は、第一項の規定による申告書の提出について準用する")
    chk("所法123③（2026-12-31）", S, v26, P("123", 3), "第百二十条第三項から第七項までの規定は")
    # 所得税法第149条
    for v in (v25, v26, v27):
        chk(f"所法149（{v}）", S, v, A("149"),
            "青色申告書には、財務省令で定めるところにより、貸借対照表、損益計算書その他不動産所得の金額、事業所得の金額若しくは山林所得の金額又は純損失の金額の計算に関する明細書を添附しなければならない。")
    # 所得税法第120条第6項・第7項（2027-01-01 版）
    chk("所法120⑥（2027-01-01）", S, v27, P("120", 6),
        "第一項の規定による申告書に社会保険料控除、小規模企業共済等掛金控除、生命保険料控除又は地震保険料控除に関する事項の記載をする居住者が当該申告書を提出する場合には、第三項の規定による同項第一号に定める書類（これらの控除に係る部分に限る。）の添付又は提示に代えて、当該書類に記載されている事項として財務省令で定める事項の記載がある明細書を当該申告書に添付することができる。")
    chk("所法120⑦（2027-01-01）税務署長 5年", S, v27, P("120", 7), "五年")
    chk("所法120⑦（2027-01-01）提示又は提出", S, v27, P("120", 7), "提示又は提出")
    chk("所法120⑥（2025-12-31）は明細書の規定ではない", S, v25, P("120", 6), "社会保険料控除、小規模企業共済等掛金控除、生命保険料控除又は地震保険料控除に関する事項", False)
    # 附則（令和八年法律第十二号）第10条
    def suppl10(r):
        for n, p in iter_nodes(r):
            if n.get("tag") == "SupplProvision" and "一二号" in (n.get("attr", {}).get("AmendLawNum") or "") and "令和八年" in (n.get("attr", {}).get("AmendLawNum") or ""):
                return next((a for a in kids(n, "Article") if a.get("attr", {}).get("Num") == "10"), None)
        return None
    chk("令和八年法律第十二号附則10条", S, v27, suppl10,
        "新所得税法第百二十条第六項及び第七項（これらの規定を所得税法第百二十二条第三項、第百二十三条第三項、第百二十五条第四項及び第百二十七条第四項において準用する場合を含む。）の規定は、令和九年一月一日以後に令和八年分以後の所得税に係る確定申告書を提出する場合について適用する。")
    # 施行規則
    for v in (v25, v26, v27):
        chk(f"規則47③十八（{v}）", K, v, I("47", 3, 18), "法第百二十三条第二項第二号、第四号又は第五号（確定損失申告書の記載事項）に掲げる金額及びその計算の基礎")
        chk(f"規則48①四 第四号から第十六号まで（{v}）", K, v, I("48", 1, 4), "第四十七条第三項第四号から第十六号まで及び第十九号から")
        chk(f"規則48①四 第二十三号まで（{v}）", K, v, I("48", 1, 4), "第十九号から第二十三号まで", v == v25)
        chk(f"規則48①四 第二十四号まで（{v}）", K, v, I("48", 1, 4), "第十九号から第二十四号まで", v != v25)
        chk(f"規則48①一 氏名・住所・個人番号（{v}）", K, v, I("48", 1, 1), "個人番号")
        chk(f"規則48①二 死亡（{v}）", K, v, I("48", 1, 2), "死亡")
        chk(f"規則48①三 所在地（{v}）", K, v, I("48", 1, 3), "所在地")
        chk(f"規則48①五 その他参考（{v}）", K, v, I("48", 1, 5), "その他参考となるべき事項")
        chk(f"規則65①一（{v}）", K, v, I("65", 1, 1), "貸借対照表及び損益計算書")
        chk(f"規則65①二（{v}）", K, v, I("65", 1, 2), "変動所得")
        chk(f"規則65①三（{v}）", K, v, I("65", 1, 3), "純損失の金額の計算に関する明細書")
        chk(f"規則65②（{v}）", K, v, P("65", 2), "第五十六条第一項ただし書")
        chk(f"規則61（{v}）", K, v, A("61"), "財務大臣の定める科目に従い、貸借対照表及び損益計算書を作成しなければならない。")
        chk(f"規則47の2⑫ 医療費控除（{v}）", K, v, P("47_2", 12), "法第百二十条第四項第一号（確定所得申告）に規定する財務省令で定める事項は、確定申告書に記載した医療費控除を受ける金額の計算の基礎となる次に掲げる事項とする。")
        chk(f"規則47の3 内訳書（{v}）", K, v, A("47_3"), "総収入金額及び必要経費")
    for v in ("2026-01-01", "2026-11-09"):
        chk(f"規則48①四 第二十四号まで（{v}）", K, v, I("48", 1, 4), "第十九号から第二十四号まで")
        chk(f"規則47③二十四 措法41の15の5（{v}）", K, v, I("47", 3, 24), "租税特別措置法第四十一条の十五の五第一項")
    chk("規則47③二十四 は2025-12-31版にない", K, v25, I("47", 3, 24), "租税特別措置法第四十一条の十五の五第一項", False)
    chk("規則47の3 第120条第6項（2025-12-31）", K, v25, A("47_3"), "法第百二十条第六項")
    chk("規則47の3 第120条第8項（2027-01-01）", K, v27, A("47_3"), "法第百二十条第八項")
    chk("規則47の2⑭ 法120⑥の明細書（2027-01-01）", K, v27, P("47_2", 14), "法第百二十条第六項")
    for i, w in [(1, "社会保険料"), (1, "小規模企業共済等掛金"), (1, "生命保険料"), (1, "地震保険料"), (2, "その他参考となるべき事項")]:
        chk(f"規則47の2⑭{i}（2027-01-01）{w}", K, v27, I("47_2", 14, i), w)
    chk("規則47の2⑭イ 令262①二", K, v27, I("47_2", 14, 1), "令第二百六十二条第一項第二号")
    chk("規則47の2⑭ロ 令262①三", K, v27, I("47_2", 14, 1), "令第二百六十二条第一項第三号に規定する小規模企業共済等掛金の額")
    chk("規則47の2⑭ハ 令262①四イ〜ホ", K, v27, I("47_2", 14, 1), "令第二百六十二条第一項第四号イからホまでに掲げる保険料の金額及び第一項各号に掲げる保険料の区分に応じ同項各号に定める事項")
    chk("規則47の2⑭ニ 令262①五", K, v27, I("47_2", 14, 1), "令第二百六十二条第一項第五号に規定する地震保険料の金額及び第二項に規定する事項")
    chk("規則47の2⑮ 前三項（2027-01-01）", K, v27, P("47_2", 15), "前三項の規定は")
    chk("規則47の2⑮ 法123③準用（2027-01-01）", K, v27, P("47_2", 15), "第百二十三条第三項")
    chk("規則47の2⑭ は2025-12-31版では法120⑥の明細書ではない", K, v25, P("47_2", 14), "法第百二十条第六項", False)
    # 租税特別措置法（仮説の文書が挙げた条の見出し）
    for v in ("2025-12-31", "2026-11-09"):
        chk(f"措法26 見出し（{v}）", "sochi", v, lambda r: kids(article(r, "26"), "ArticleCaption")[0], "社会保険診療報酬")
        chk(f"措法27 見出し（{v}）", "sochi", v, lambda r: kids(article(r, "27"), "ArticleCaption")[0], "家内労働者")
    chk("措法41の15の5 見出し（2026-11-09）", "sochi", "2026-11-09", lambda r: kids(article(r, "41_15_5"), "ArticleCaption")[0],
        "年齢二十三歳未満の扶養親族を有する場合の生命保険料控除の特例")
    # 本則の全文の検索：書式・様式を定める条に確定申告書・確定損失申告書・青色申告決算書が出るか
    grep = {}
    for (short, asof), root in roots.items():
        if short not in (S, K) or asof != v25:
            continue
        hits = []
        for n, p in iter_nodes(root):
            if n.get("tag") == "Article" and "SupplProvision" not in p:
                t = law_text(n)
                if re.search(r"様式|書式|別表第", t):
                    hits.append({"num": n["attr"].get("Num"), "caption": caption(n),
                                 "mentions_kakutei": bool(re.search(r"確定申告書|確定所得申告書|確定損失申告書|青色申告決算書", t)),
                                 "snippets": [m.group(0) for m in re.finditer(r".{0,30}(様式|書式|別表第[一二三四五六七八九十]+).{0,30}", t)][:3]})
        grep[short] = hits
    res = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)).replace("\\", "/"), "revisions": revs, "checks": checks, "grep_format_articles": grep}
    (out / "egov_checks.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    md = [f"# e-Gov 法令API v2 の照合（実行 {ts}）", "", f"- 保存先：`{res['download_dir']}`", "", "## 版", "",
          "| 法令 | asof | law_revision_id | 改正法令 | 施行日 | 状態 | 前の担当の記録と一致 |", "|---|---|---|---|---|---|---|"]
    md += [f"| {r['short']} | {r['asof']} | `{r['law_revision_id']}` | {r['amendment_law_num']} | {r['amendment_enforcement_date']} | {r['current_revision_status']} | {r.get('pass')} |" for r in revs]
    md += ["", "## 文言", "", "| 項目 | 版 | 期待 | 結果 |", "|---|---|---|---|"]
    md += [f"| {c['label']} | {c['asof']} | {'有' if c['expect_found'] else '無'} | {'OK' if c['pass'] else 'NG：' + c['context'][:80]} |" for c in checks]
    for short, hits in grep.items():
        md += ["", f"## 本則で「様式・書式・別表第」を含む条（{short}、2025-12-31 版）", ""]
        md += [f"- 第{h['num']}条 {h['caption']}（確定申告書等の語：{h['mentions_kakutei']}）" for h in hits]
    (out / "egov_checks.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("checks", sum(c["pass"] for c in checks), "/", len(checks))


# ======================================================================== PDF（AES-128 は IMPL_output_verify.py から写した）
def _xt(a):
    return ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else a << 1


def _gmul(a, b):
    r = 0
    while b:
        if b & 1:
            r ^= a
        a = _xt(a)
        b >>= 1
    return r


def _sbox():
    inv = [0] * 256
    for a in range(1, 256):
        for b in range(1, 256):
            if _gmul(a, b) == 1:
                inv[a] = b
                break
    s = []
    for a in range(256):
        x = inv[a]
        y = x
        for i in range(1, 5):
            y ^= ((x << i) | (x >> (8 - i))) & 0xFF
        s.append(y ^ 0x63)
    si = [0] * 256
    for i, v in enumerate(s):
        si[v] = i
    return s, si


SBOX, INV_SBOX = _sbox()
M9, M11, M13, M14 = ([_gmul(x, k) for x in range(256)] for k in (9, 11, 13, 14))


def _expand(key):
    w = [list(key[i:i + 4]) for i in range(0, 16, 4)]
    rcon = 1
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = t[1:] + t[:1]
            t = [SBOX[x] for x in t]
            t[0] ^= rcon
            rcon = _xt(rcon)
        w.append([w[i - 4][j] ^ t[j] for j in range(4)])
    return [sum(w[r * 4:r * 4 + 4], []) for r in range(11)]


def aes128_decrypt_block(rk, block):
    s = [b ^ k for b, k in zip(block, rk[10])]
    for rnd in range(9, -1, -1):
        s = [s[((c - r) % 4) * 4 + r] for c in range(4) for r in range(4)]
        s = [INV_SBOX[x] for x in s]
        s = [x ^ k for x, k in zip(s, rk[rnd])]
        if rnd:
            ns = []
            for c in range(4):
                a = s[c * 4:c * 4 + 4]
                ns += [M14[a[0]] ^ M11[a[1]] ^ M13[a[2]] ^ M9[a[3]], M9[a[0]] ^ M14[a[1]] ^ M11[a[2]] ^ M13[a[3]],
                       M13[a[0]] ^ M9[a[1]] ^ M14[a[2]] ^ M11[a[3]], M11[a[0]] ^ M13[a[1]] ^ M9[a[2]] ^ M14[a[3]]]
            s = ns
    return bytes(s)


def aes128_cbc_decrypt(key, data):
    rk = _expand(key)
    iv, out = data[:16], bytearray()
    for i in range(16, len(data) - len(data) % 16, 16):
        blk = data[i:i + 16]
        out += bytes(x ^ y for x, y in zip(aes128_decrypt_block(rk, blk), iv))
        iv = blk
    if out and 1 <= out[-1] <= 16:
        out = out[:-out[-1]]
    return bytes(out)


def aes_selftest():
    return aes128_decrypt_block(_expand(bytes(range(16))), bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")).hex() == "00112233445566778899aabbccddeeff"


PAD = bytes.fromhex("28BF4E5E4E758A4164004E56FFFA01082E2E00B6D0683E802F0CA9FE6453697A")


def _rc4(key, data):
    S = list(range(256))
    j = 0
    for i in range(256):
        j = (j + S[i] + key[i % len(key)]) % 256
        S[i], S[j] = S[j], S[i]
    i = j = 0
    out = bytearray()
    for b in data:
        i = (i + 1) % 256
        j = (j + S[i]) % 256
        S[i], S[j] = S[j], S[i]
        out.append(b ^ S[(S[i] + S[j]) % 256])
    return bytes(out)


class Pdf:
    """ユーザーパスワード空の Standard セキュリティハンドラ（V4・R4・AESV2）だけを扱う、読み取り専用の簡易 PDF リーダ。"""

    def __init__(self, data):
        self.raw = data
        self.sha256 = hashlib.sha256(data).hexdigest()
        self.objs = {}  # num -> (dict bytes, stream bytes(decrypted, not inflated) or None)
        for m in re.finditer(rb"(?<![0-9])(\d+)\s+(\d+)\s+obj\b", data):
            end = data.find(b"endobj", m.end())
            body = data[m.end():end]
            sm = re.search(rb"stream\r?\n", body)
            if sm:
                dic = body[:sm.start()]
                ln = re.search(rb"/Length\s+(\d+)(?!\s+\d+\s+R)", dic)
                st = body[sm.end():sm.end() + int(ln.group(1))] if ln else re.sub(rb"\r?\n?endstream\s*$", b"", body[sm.end():].rstrip())
                self.objs[int(m.group(1))] = [dic, st, int(m.group(2))]
            else:
                self.objs[int(m.group(1))] = [body, None, int(m.group(2))]
        self.enc = None
        em = re.search(rb"/Encrypt\s+(\d+)\s+0\s+R", data)
        self.key_ok = None
        if em:
            ed = self.objs[int(em.group(1))][0]
            v = int(re.search(rb"/V\s+(\d+)", ed).group(1))
            r = int(re.search(rb"/R\s+(\d+)", ed).group(1))
            self.enc = {"obj": int(em.group(1)), "V": v, "R": r, "AESV2": b"AESV2" in ed}
            if v != 4 or r != 4 or b"AESV2" not in ed:
                self.enc["unsupported"] = True
                return
            o = bytes.fromhex(re.search(rb"/O\s*<([0-9a-fA-F]+)>", ed).group(1).decode())
            u = bytes.fromhex(re.search(rb"/U\s*<([0-9a-fA-F]+)>", ed).group(1).decode())
            p = int(re.search(rb"/P\s+(-?\d+)", ed).group(1))
            id0 = bytes.fromhex(re.search(rb"/ID\s*\[\s*<([0-9a-fA-F]+)>", data).group(1).decode())
            h = hashlib.md5(PAD + o + (p & 0xFFFFFFFF).to_bytes(4, "little") + id0).digest()
            for _ in range(50):
                h = hashlib.md5(h[:16]).digest()
            self.key = h[:16]
            x = _rc4(self.key, hashlib.md5(PAD + id0).digest())
            for i in range(1, 20):
                x = _rc4(bytes(k ^ i for k in self.key), x)
            self.key_ok = x == u[:16]
            self.enc["P"] = p
            for num, ob in self.objs.items():
                if ob[1] is not None and num != self.enc["obj"] and b"/XRef" not in ob[0]:
                    ob.append("encrypted")
        # オブジェクトストリームの中のオブジェクト
        for num, ob in list(self.objs.items()):
            if ob[1] is not None and b"/ObjStm" in ob[0] and not (self.enc or {}).get("unsupported"):
                d = self.data(num)
                n = int(re.search(rb"/N\s+(\d+)", ob[0]).group(1))
                first = int(re.search(rb"/First\s+(\d+)", ob[0]).group(1))
                hd = d[:first].split()
                pairs = [(int(hd[2 * k]), int(hd[2 * k + 1])) for k in range(n)]
                for k, (onum, off) in enumerate(pairs):
                    endo = pairs[k + 1][1] if k + 1 < n else len(d) - first
                    if onum not in self.objs:
                        self.objs[onum] = [d[first + off:first + endo], None, 0]

    def dic(self, num):
        return self.objs.get(num, [b"", None, 0])[0]

    def stream(self, num):
        """復号したストリーム（展開前）。暗号化されたものは初めて使うときに復号する。"""
        ob = self.objs.get(num)
        if not ob or ob[1] is None:
            return b""
        if len(ob) > 3 and ob[3] == "encrypted":
            okey = hashlib.md5(self.key + num.to_bytes(3, "little") + ob[2].to_bytes(2, "little") + b"sAlT").digest()[:16]
            ob[1] = aes128_cbc_decrypt(okey, ob[1])
            ob[3] = "decrypted"
        return ob[1]

    def data(self, num):
        ob = self.objs.get(num)
        if not ob or ob[1] is None:
            return b""
        self.stream(num)
        if b"FlateDecode" in ob[0]:
            try:
                return zlib.decompressobj().decompress(ob[1], 64 * 1024 * 1024)
            except zlib.error:
                return b""
        return ob[1]

    def ref(self, dic, key):
        m = re.search(rb"/" + key + rb"\s+(\d+)\s+0\s+R", dic)
        return int(m.group(1)) if m else None

    def pages(self):
        roots = re.findall(rb"/Root\s+(\d+)\s+0\s+R", self.raw)
        root = int(roots[-1]) if roots else None
        if root is None or not re.search(rb"/Type\s*/Catalog", self.dic(root)):
            root = next(n for n, o in self.objs.items() if re.search(rb"/Type\s*/Catalog", o[0]))
        out = []

        def walk(n, depth=0):
            d = self.dic(n)
            if re.search(rb"/Type\s*/Pages\b", d) and depth < 30:
                km = re.search(rb"/Kids\s*\[([^\]]*)\]", d)
                for k in re.findall(rb"(\d+)\s+0\s+R", km.group(1)):
                    walk(int(k), depth + 1)
            else:
                out.append(n)
        walk(self.ref(self.dic(root), b"Pages"))
        return out

    def inherited(self, pnum, key):
        n = pnum
        for _ in range(30):
            d = self.dic(n)
            m = re.search(rb"/" + key + rb"\s*(<<|\d+\s+0\s+R)", d)
            if m:
                if m.group(1) == b"<<":
                    return balanced(d, m.start(1))
                return self.dic(int(m.group(1).split()[0]))
            p = self.ref(d, b"Parent")
            if p is None:
                return b""
            n = p
        return b""

    def content(self, pnum):
        d = self.dic(pnum)
        m = re.search(rb"/Contents\s*(\[[^\]]*\]|\d+\s+0\s+R)", d)
        if not m:
            return b""
        nums = [int(x) for x in re.findall(rb"(\d+)\s+0\s+R", m.group(1))]
        if len(nums) == 1 and self.objs.get(nums[0], [b"", None])[1] is None:
            nums = [int(x) for x in re.findall(rb"(\d+)\s+0\s+R", self.dic(nums[0]))]
        return b"\n".join(self.data(c) for c in nums)

    def fonts(self, pnum):
        res = self.inherited(pnum, b"Resources")
        m = re.search(rb"/Font\s*(<<|\d+\s+0\s+R)", res)
        if not m:
            return {}
        fd = balanced(res, m.start(1)) if m.group(1) == b"<<" else self.dic(int(m.group(1).split()[0]))
        out = {}
        for name, n in re.findall(rb"/([^\s/<>\[\]()]+)\s+(\d+)\s+0\s+R", fd):
            f = self.dic(int(n))
            tu = self.ref(f, b"ToUnicode")
            two = b"/Type0" in f
            if tu and self.data(tu):
                out[name.decode()] = ("cmap", two, cmap(self.data(tu)))
            elif re.search(rb"/Encoding\s*/[\w-]*RKSJ", f):
                out[name.decode()] = ("cp932", True, None)
            else:
                out[name.decode()] = ("latin-1", False, None)
        return out

    def images(self, pnum):
        res = self.inherited(pnum, b"Resources")
        m = re.search(rb"/XObject\s*(<<|\d+\s+0\s+R)", res)
        if not m:
            return []
        xd = balanced(res, m.start(1)) if m.group(1) == b"<<" else self.dic(int(m.group(1).split()[0]))
        out = []
        for name, n in re.findall(rb"/([^\s/<>\[\]()]+)\s+(\d+)\s+0\s+R", xd):
            d = self.dic(int(n))
            if re.search(rb"/Subtype\s*/Image", d):
                w = re.search(rb"/Width\s+(\d+)", d)
                h = re.search(rb"/Height\s+(\d+)", d)
                out.append({"name": name.decode(), "w": int(w.group(1)) if w else 0, "h": int(h.group(1)) if h else 0,
                            "sha256_decrypted": hashlib.sha256(self.stream(int(n))).hexdigest() if (w and int(w.group(1)) > 1000) else None})
        return out


def balanced(b, i):
    """b[i] から始まる << ... >> を返す（入れ子を数える）。"""
    depth, j = 0, i
    while j < len(b) - 1:
        if b[j:j + 2] == b"<<":
            depth += 1
            j += 2
            continue
        if b[j:j + 2] == b">>":
            depth -= 1
            j += 2
            if depth == 0:
                return b[i:j]
            continue
        j += 1
    return b[i:]


def cmap(b):
    m = {}
    for blk in re.findall(rb"beginbfchar(.*?)endbfchar", b, re.S):
        for a, c in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
            m[int(a, 16)] = bytes.fromhex(c.decode()).decode("utf-16-be", "replace")
    for blk in re.findall(rb"beginbfrange(.*?)endbfrange", b, re.S):
        for a, z, c in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
            s, e, base = int(a, 16), int(z, 16), int(c, 16)
            for k in range(s, min(e, s + 70000) + 1):
                if base + k - s < 0x110000:
                    m[k] = chr(base + k - s)
    return m


def pdf_string(tok):
    if tok.startswith(b"<"):
        return bytes.fromhex(re.sub(rb"\s", b"", tok[1:-1]).decode() + ("0" if len(re.sub(rb"\s", b"", tok[1:-1])) % 2 else ""))
    s, out, i = tok[1:-1], bytearray(), 0
    while i < len(s):
        c = s[i]
        if c == 92 and i + 1 < len(s):
            n = s[i + 1]
            if 48 <= n <= 55:
                m = re.match(rb"[0-7]{1,3}", s[i + 1:i + 4])
                out.append(int(m.group(0), 8) & 255)
                i += 1 + len(m.group(0))
                continue
            out += {110: b"\n", 114: b"\r", 116: b"\t", 98: b"\b", 102: b"\f", 10: b"", 13: b""}.get(n, bytes([n]))
            i += 2
            continue
        out.append(c)
        i += 1
    return bytes(out)


TOK = re.compile(rb"\((?:\\.|[^\\()]|\((?:\\.|[^\\()])*\))*\)|<[0-9A-Fa-f\s]*>|\[|\]|/[^\s/\[\]()<>{}%]+|[-+]?(?:\d+\.?\d*|\.\d+)|[A-Za-z*'\"]+")


def runs(content, fonts):
    """内容ストリームを先頭から読み、テキスト行列（Tm）と行の開始位置（Td/TD/T*/'/"）を追って、文字列の開始位置を返す。
    変換行列（cm）は追わない（国税庁の様式は BT の中で Tm を使う）。"""
    out = []
    ops = []
    tlm = [0.0, 0.0]
    lead = 0.0
    font = None
    inbt = False
    for m in TOK.finditer(content):
        t = m.group(0)
        if t[:1] in (b"(", b"<") and t != b"<<":
            ops.append(("s", pdf_string(t)))
        elif t == b"[":
            ops.append(("[", None))
        elif t == b"]":
            arr = []
            while ops and ops[-1][0] != "[":
                arr.append(ops.pop())
            if ops:
                ops.pop()
            ops.append(("a", [v for k, v in reversed(arr) if k == "s"]))
        elif t[:1] == b"/":
            ops.append(("n", t[1:].decode("latin-1")))
        elif re.fullmatch(rb"[-+]?(?:\d+\.?\d*|\.\d+)", t):
            ops.append(("f", float(t)))
        else:
            nums = [v for k, v in ops if k == "f"]
            if t == b"BT":
                inbt, tlm = True, [0.0, 0.0]
            elif t == b"ET":
                inbt = False
            elif t == b"Tf":
                names = [v for k, v in ops if k == "n"]
                font = names[-1] if names else font
            elif t == b"Tm" and len(nums) >= 6:
                tlm = [nums[-2], nums[-1]]
            elif t in (b"Td", b"TD") and len(nums) >= 2:
                tlm = [tlm[0] + nums[-2], tlm[1] + nums[-1]]
                if t == b"TD":
                    lead = -nums[-1]
            elif t == b"TL" and nums:
                lead = nums[-1]
            elif t == b"T*":
                tlm = [tlm[0], tlm[1] - lead]
            elif t in (b"Tj", b"TJ", b"'", b'"') and inbt:
                if t in (b"'", b'"'):
                    tlm = [tlm[0], tlm[1] - lead]
                raw = b"".join(v if k == "s" else b"".join(v) for k, v in ops if k in ("s", "a"))
                f = fonts.get(font) or ("cp932", True, None)
                if f[0] == "cmap":
                    if f[1]:
                        s = "".join(f[2].get(int.from_bytes(raw[i:i + 2], "big"), "\ufffd") for i in range(0, len(raw) - 1, 2))
                    else:
                        s = "".join(f[2].get(b, chr(b)) for b in raw)
                else:
                    s = raw.decode(f[0], "replace")
                if s.strip():
                    out.append((round(tlm[0], 1), round(tlm[1], 1), s))
            ops = []
    return out


CODE = re.compile(r"[A-Z]\d{2,3}")


def page_rows(pdf):
    rows = []
    for pno, pn in enumerate(pdf.pages(), 1):
        for x, y, s in runs(pdf.content(pn), pdf.fonts(pn)):
            rows.append((pno, x, y, s.strip()))
    return rows


def codes_on(rows, page):
    return {r[3]: (r[1], r[2]) for r in rows if r[0] == page and CODE.fullmatch(r[3])}


def left_text(rows, page, x, y, dy=10, span=330):
    cand = sorted((r for r in rows if r[0] == page and abs(r[2] - y) <= dy and x - span <= r[1] < x and not CODE.fullmatch(r[3])),
                  key=lambda r: (-r[2], r[1]))
    return "".join(r[3] for r in cand)


def row_no(rows, page, x, y, dy=1.0, span=40):
    c = sorted((r for r in rows if r[0] == page and abs(r[2] - y) <= dy and x - span <= r[1] < x and re.fullmatch(r"\d{1,2}", r[3])),
               key=lambda r: x - r[1])
    return c[0][3] if c else None


# 青色申告決算書（一般用）1ページ：欄コード → 科目名（様式の印字。公開資料の文書 §6.1）
AOIRO_P1 = {1: "売上（収入）金額", 2: "期首商品", 3: "仕入金額", 4: "小計", 5: "期末商品", 6: "差引原価", 7: "差引金額", 8: "租税公課", 9: "荷造運賃",
            10: "水道光熱費", 11: "旅費交通費", 12: "通信費", 13: "広告宣伝費", 14: "接待交際費", 15: "損害保険料", 16: "修繕費", 17: "消耗品費",
            18: "減価償却費", 19: "福利厚生費", 20: "給料賃金", 21: "外注工賃", 22: "利子割引料", 23: "地代家賃", 24: "貸倒金", 31: "雑費", 32: "計",
            33: "差引金額", 34: "貸倒引当金", 37: "計", 38: "専従者給与", 39: "貸倒引当金", 42: "計", 43: "青色申告特別控除前の所得金額",
            44: "青色申告特別控除額", 45: "所得金額"}
AOIRO_P4_ASSET = ["現金", "当座預金", "定期預金", "その他の預金", "受取手形", "売掛金", "有価証券", "棚卸資産", "前払金", "貸付金", "建物",
                  "建物附属設備", "機械装置", "車両運搬具", "工具器具備品", "土地"]
AOIRO_P4_LIAB = {1: "支払手形", 2: "買掛金", 3: "借入金", 4: "未払金", 5: "前受金", 6: "預り金", 14: "貸倒引当金", 22: "事業主借", 23: "元入金",
                 24: "青色申告特別控除前の所得金額", 25: "合計"}
FUDOSAN_P1 = {1: "賃貸料", 2: "礼金", 3: "名義書換料", 4: "小計", 5: "計", 6: "給料賃金", 7: "減価償却費", 8: "貸倒金", 9: "地代家賃", 10: "借入金利子",
              11: "租税公課", 12: "損害保険料", 13: "修繕費", 15: "雑費", 16: "小計", 17: "経費計", 18: "専従者控除前の所得金額", 19: "専従者控除",
              20: "所得金額", 21: "土地等を取得するために要した負債の利子"}
QUOTES_10 = [
    # 行の折り返し・別の文字列に分かれた番号（43 など）・「イ」「T」の位置で文字列が切れるので、断片の並びで探す
    ["青色申告特別控除については、「決算の手引き」の「青色申告"],
    ["登録番号を記載する場合は上段に、法人番号を", "記載する場合は下段に記入してください。"],
    ["なお、登録番号を記載する場合には、先頭に", "「", "T", "」を付けてください"],
    ["平成19年４月１日以後に取得した減価償却資産について定率法を採用する場合にのみ", "イ", "欄のカッコ内に償却保証額を記入します。"],
    ["65万円又は55万円の青色申告特別控除を受ける人は必ず記入してください"],
    ["それ以外の人でも分かる箇所はできるだけ記入してください"],
    ["「元入金」は、「期首の資産の総額」から「期首の負債の総額」を差し引いて計算します。"],
    ["原価計算を行っていない人は、記入する必要はありません。"],
    ["欄の金額は、1ページの「損益計算書」の", "欄に移記してください。"],
    ["貸倒引当金、専従者給与や３ページの割増（特別）償却以外の特典を利用する人は、適宜の用紙にその明細を記載し、この決算書に添付してください。"],
    ["（１ページの「損益計算書」の", "欄の金額を書いてください。）"],
]


def page_hay(rows_in_order, page):
    """横書き：内容ストリームの順の連結。縦書き：同じ x（1pt 単位）の 1〜3 文字の文字列を上から連結したもの。"""
    rr = [r for r in rows_in_order if r[0] == page]
    horiz = norm("".join(r[3] for r in rr))
    cols = {}
    for r in rr:
        if len(r[3]) <= 3:
            cols.setdefault(round(r[1]), []).append(r)
    # 縦書きの句読点（。、）は x が少しずれて別の列になるので、縦書きの列では句読点を除いて比べる
    vert = [re.sub(r"[。、]", "", norm("".join(x[3] for x in sorted(v, key=lambda x: -x[2])))) for v in cols.values()]
    # 行ごと：同じ高さ（0.5pt に丸めた y）の文字列を x の順に並べ、上の行から連結したもの
    lines = {}
    for r in rr:
        lines.setdefault(round(r[2] * 2) / 2, []).append(r)
    by_line = norm("".join("".join(x[3] for x in sorted(v, key=lambda x: x[1])) for _, v in sorted(lines.items(), key=lambda kv: -kv[0])))
    return [horiz, by_line] + vert


def has_fragments(hays, frags):
    for h in hays:
        i, ok = 0, True
        for f in frags:
            nf = norm(f) if norm(f) in h else re.sub(r"[。、]", "", norm(f))
            j = h.find(nf, i)
            if j < 0:
                ok = False
                break
            i = j + len(nf)
        if ok:
            return True
    return False


def above_text(rows, page, x, y, dx=25, dy=130):
    c = sorted((r for r in rows if r[0] == page and abs(r[1] - x) <= dx and y < r[2] <= y + dy and not CODE.fullmatch(r[3])), key=lambda r: r[2] - y)
    return "".join(r[3] for r in c[:3])


def left_range(rows, page, x0, x1, y, dy=1.0):
    c = sorted((r for r in rows if r[0] == page and abs(r[2] - y) <= dy and x0 <= r[1] < x1 and not CODE.fullmatch(r[3])), key=lambda r: (-r[2], r[1]))
    return "".join(r[3] for r in c)


def row_group_ok(cc, g):
    """売上先・仕入先の明細の1行：名・所在地・金額は同じ高さ、登録番号（上段）と法人番号（下段）は同じ x で上下に分かれ、行の中心をはさむ。"""
    nm, ad, reg, corp, amt = (cc[k] for k in g)
    same = max(nm[1], ad[1], amt[1]) - min(nm[1], ad[1], amt[1]) <= 1.0
    updown = abs(reg[0] - corp[0]) <= 1.0 and 8 <= reg[1] - corp[1] <= 14 and corp[1] < nm[1] < reg[1]
    order = nm[0] < ad[0] < reg[0] < amt[0]
    return same and updown and order


def depr_ok(cc, n_rows, e_of, m_of, g_of):
    """減価償却の各行：取得年月（M）と取得価額（G）は同じ高さ、名称（E）はその行に最も近い。"""
    bad = []
    for n in range(1, n_rows + 1):
        e, m, g = cc.get(e_of(n)), cc.get(m_of(n)), cc.get(g_of(n))
        if not (e and m and g):
            bad.append((n, "missing"))
            continue
        nearest = min(range(1, n_rows + 1), key=lambda k: abs(cc[m_of(k)][1] - e[1]) if m_of(k) in cc else 1e9)
        if abs(m[1] - g[1]) > 1.0 or nearest != n or not (e[0] < m[0] < g[0]):
            bad.append((n, e, m, g))
    return bad


def cmd_pdf(dl_dir):
    src = pathlib.Path(dl_dir)
    out = OUT / "pdf"
    out.mkdir(parents=True, exist_ok=True)
    res = {"aes_selftest": aes_selftest(), "files": {}, "checks": []}

    def C(label, ok, detail=""):
        res["checks"].append({"label": label, "pass": bool(ok), "detail": detail})

    def load(key):
        f = src / f"{key}.pdf"
        p = Pdf(f.read_bytes())
        rows = page_rows(p) if not (p.enc or {}).get("unsupported") else []
        pages = p.pages() if not (p.enc or {}).get("unsupported") else []
        info = {"sha256": p.sha256, "enc": p.enc, "key_ok": p.key_ok, "n_pages": len(pages),
                "per_page": [{"page": i + 1, "n_runs": sum(1 for r in rows if r[0] == i + 1),
                              "n_codes": sum(1 for r in rows if r[0] == i + 1 and CODE.fullmatch(r[3])),
                              "images": p.images(pn)} for i, pn in enumerate(pages)],
                "n_codes": sum(1 for r in rows if CODE.fullmatch(r[3])),
                "form_ids": sorted(set(re.findall(r"NTA[0-9A-Z]{13}", "".join(r[3] for r in rows).replace(" ", ""))))}
        res["files"][key] = info
        with open(out / f"{key}_text.tsv", "w", encoding="utf-8") as fh:
            fh.write(f"# sha256={p.sha256}\npage\tx\ty\ttext\n")
            for r in sorted(rows, key=lambda r: (r[0], -r[2], r[1])):
                fh.write(f"{r[0]}\t{r[1]}\t{r[2]}\t{r[3]}\n")
        return p, rows, info

    # ---- 青色申告決算書（一般用）
    p10, rows, info = load("r07_10")
    C("10.pdf 暗号 AESV2・鍵 OK", info["enc"] and info["enc"]["AESV2"] and info["key_ok"], str(info["enc"]))
    C("10.pdf 欄コードの数 253", info["n_codes"] == 253, str(info["n_codes"]))
    C("10.pdf 様式ID NTA0KOA210010110〜040110", info["form_ids"] == [f"NTA0KOA2100{i}0110" for i in range(1, 5)], str(info["form_ids"]))
    hays = [h for pg in (1, 2, 3, 4) for h in page_hay(rows, pg)]
    for q in QUOTES_10:
        C("10.pdf 印字「" + "".join(q)[:34] + "…」", has_fragments(hays, q), "")
    C("10.pdf 版の表示「令和五年分以降用」（漢数字）がテキスト層にある", any(norm("令和五年分以降用") in h for h in hays), "")
    for pg in (1, 2, 3, 4):
        C(f"10.pdf {pg}ページに G01 がある（ページごとの振り直し）", "G01" in codes_on(rows, pg), "")
    c1 = codes_on(rows, 1)
    for n in range(1, 46):
        code = f"G{n:02d}"
        if code not in c1:
            C(f"10.pdf p1 {code}", False, "コードなし")
            continue
        x, y = c1[code]
        rn = row_no(rows, 1, x, y)
        lab = left_text(rows, 1, x, y)
        exp = AOIRO_P1.get(n)
        ok = rn == str(n) and (exp is None or norm(exp) in norm(lab))
        C(f"10.pdf p1 {code} 行番号{n}・{exp or '（空欄）'}", ok, f"row={rn} left={lab[:60]}")
    for code in ("L01", "U01", "U02"):
        C(f"10.pdf p1 {code} がある", code in c1, "")
    # 2ページ
    c2 = codes_on(rows, 2)
    for m in range(1, 13):
        a, b = f"G{m:02d}", f"G{m + 16:02d}"
        ok = a in c2 and b in c2 and row_no(rows, 2, *c2[a], span=60) == str(m) and abs(c2[a][1] - c2[b][1]) <= 1.0 and c2[b][0] > c2[a][0]
        C(f"10.pdf p2 月{m}：売上 {a}・仕入 {b} が同じ行", ok, f"{c2.get(a)} {c2.get(b)} row={row_no(rows, 2, *c2[a], span=60) if a in c2 else None}")
    for code, lab in [("G13", "家事消費等"), ("G14", "雑収入"), ("G15", "計"), ("G16", "うち軽減税率対象"), ("G29", "計"), ("G30", "うち軽減税率対象")]:
        lt = left_text(rows, 2, *c2[code], dy=6, span=200) if code in c2 else ""
        C(f"10.pdf p2 {code} {lab}", code in c2 and norm(lab) in norm(lt), lt[:60])
    C("10.pdf p2 E05 がない", "E05" not in c2, "")
    C("10.pdf p2 E01〜E04・E06〜E09 がある", all(f"E{i:02d}" in c2 for i in (1, 2, 3, 4, 6, 7, 8, 9)), "")
    C("10.pdf p2 G31〜G34 がある", all(f"G{i}" in c2 for i in (31, 32, 33, 34)), "")
    if all(k in c2 for k in ("G31", "G32", "E04")):
        C("10.pdf p2 G31・G32 は同じ行で E04 より下", abs(c2["G31"][1] - c2["G32"][1]) <= 1 and c2["G31"][1] < c2["E04"][1], f"{c2['G31']} {c2['G32']} E04={c2['E04']}")
    if all(k in c2 for k in ("G33", "G34", "E09")):
        C("10.pdf p2 G33・G34 は同じ行で E09 より下", abs(c2["G33"][1] - c2["G34"][1]) <= 1 and c2["G33"][1] < c2["E09"][1], f"{c2['G33']} {c2['G34']} E09={c2['E09']}")
    res["p2_E_rows"] = {k: [v, left_text(rows, 2, *v, dy=4, span=120)[:40]] for k, v in sorted(c2.items()) if k.startswith("E")}
    res["p2_sonota"] = [r for r in rows if r[0] == 2 and "その他" in r[3]]
    C("10.pdf p2 最大の欄コード番号", True, str(sorted(c2)[-5:]))
    # 3ページ
    c3 = codes_on(rows, 3)
    groups = [("E13", "E14", "E15", "G12", "G13"), ("E16", "E17", "E18", "G14", "G15"), ("E19", "E20", "E21", "G16", "G17"), ("E22", "E23", "E24", "G18", "G19"),
              ("E25", "E26", "E27", "G22", "G23"), ("E28", "E29", "E30", "G24", "G25"), ("E31", "E32", "E33", "G26", "G27"), ("E34", "E35", "E36", "G28", "G29")]
    for g in groups:
        if not all(k in c3 for k in g):
            C(f"10.pdf p3 行 {g}", False, "コードが欠ける")
            continue
        C(f"10.pdf p3 行 {g}：名・所在地・金額は同じ高さ、登録番号（上段）・法人番号（下段）は同じ x で上下", row_group_ok(c3, g),
          f"{[(k, c3[k]) for k in g]}")
    for code, lab in [("G20", "上記以外の売上先の計"), ("G30", "上記以外の仕入先の計")]:
        C(f"10.pdf p3 {code} {lab}", code in c3 and norm(lab) in norm(left_text(rows, 3, *c3[code], dy=8, span=420)),
          left_text(rows, 3, *c3[code], dy=8, span=420)[:80] if code in c3 else "なし")
    C("10.pdf p3 E12 本年中における特殊事情（見出しの下）", "E12" in c3 and "本年中における特殊事情" in norm(above_text(rows, 3, *c3["E12"])),
      above_text(rows, 3, *c3["E12"]) if "E12" in c3 else "なし")
    for code, n in (("G21", "1"), ("G31", "6")):
        lt = left_text(rows, 3, *c3[code], dy=4, span=200) if code in c3 else ""
        C(f"10.pdf p3 {code} 「計（{n}）」", code in c3 and norm(f"計({n})") in norm(lt), lt[:60])
    bad = depr_ok(c3, 7, lambda n: f"E{n:02d}", lambda n: f"M{n:02d}", lambda n: f"G{n:02d}")
    C("10.pdf p3 減価償却 7 行：(E0n 名称, M0n 取得年月, G0n 取得価額) n=1〜7", not bad, str(bad))
    C("10.pdf p3 E08〜E11・M08 がない", not any(x in c3 for x in ("E08", "E09", "E10", "E11", "M08")), str(sorted(x for x in c3 if x[0] in "EM")))
    # 4ページ（貸借対照表）
    c4 = codes_on(rows, 4)
    ys = sorted({round(v[1], 1) for k, v in c4.items() if k.startswith("G")}, reverse=True)
    C("10.pdf p4 行の数 25", len(ys) == 25, str(ys))
    rowy = {i + 1: y for i, y in enumerate(ys)}
    cols = {}
    for k, (x, y) in c4.items():
        if k.startswith("G"):
            col = min((136, 222, 398, 485), key=lambda c: abs(c - x))
            row = next(i for i, yy in rowy.items() if abs(yy - y) <= 0.6)
            cols[(col, row)] = k
    exp = {}
    for r in range(1, 24):
        exp[(136, r)] = f"G{r:02d}"
        exp[(222, r)] = f"G{r + 24:02d}"
    exp[(222, 24)], exp[(136, 25)], exp[(222, 25)] = "G48", "G24", "G49"
    for r in range(1, 22):
        exp[(398, r)] = f"G{r + 49:02d}"
        exp[(485, r)] = f"G{r + 72:02d}"
    exp.update({(485, 22): "G94", (398, 23): "G71", (485, 23): "G95", (485, 24): "G96", (398, 25): "G72", (485, 25): "G97"})
    diff = {f"{c}/{r}": (cols.get((c, r)), exp.get((c, r))) for c, r in set(cols) | set(exp) if cols.get((c, r)) != exp.get((c, r))}
    C("10.pdf p4 貸借対照表の欄コードの配置（公開資料 §6.4 の表）", not diff, json.dumps(diff, ensure_ascii=False))
    for i, name in enumerate(AOIRO_P4_ASSET, 1):
        lt = left_range(rows, 4, 50, 136, rowy[i], dy=1.0)
        C(f"10.pdf p4 資産 行{i} {name}", norm(name) in norm(lt), lt[:30])
    for r in range(17, 24):
        lt = left_range(rows, 4, 50, 136, rowy[r], dy=1.0)
        C(f"10.pdf p4 資産 行{r} 空欄", norm(lt) == "", lt[:30])
    for r, name in ((24, "事業主貸"), (25, "合計")):
        lt = left_range(rows, 4, 50, 136, rowy[r], dy=1.0)
        C(f"10.pdf p4 資産 行{r} {name}", norm(name) in norm(lt), lt[:30])
    for r in range(1, 26):
        lt = left_range(rows, 4, 300, 398, rowy[r], dy=6 if r == 24 else 1.6)
        name = AOIRO_P4_LIAB.get(r)
        C(f"10.pdf p4 負債・資本 行{r} {name or '空欄'}", (norm(name) in norm(lt)) if name else norm(lt) == "", lt[:30])
    # ---- 収支内訳書（一般用）
    p05, rows5, info5 = load("r07_05")
    C("05.pdf 欄コードの数 116", info5["n_codes"] == 116, str(info5["n_codes"]))
    C("05.pdf 様式ID", info5["form_ids"] == ["NTA0KOA110010120", "NTA0KOA110020120"], str(info5["form_ids"]))
    d2 = codes_on(rows5, 2)
    g5 = [("E01", "E02", "E24", "G21", "G01"), ("E03", "E04", "E25", "G22", "G02"), ("E05", "E06", "E26", "G23", "G03"), ("E07", "E08", "E27", "G24", "G04"),
          ("E09", "E10", "E28", "G25", "G08"), ("E11", "E12", "E29", "G26", "G09"), ("E13", "E14", "E30", "G27", "G10"), ("E15", "E16", "E31", "G28", "G11")]
    for g in g5:
        if not all(k in d2 for k in g):
            C(f"05.pdf p2 行 {g}", False, "コードが欠ける")
            continue
        C(f"05.pdf p2 行 {g}", row_group_ok(d2, g), str([(k, d2[k]) for k in g]))
    for code, lab in [("G05", "上記以外の売上先の計"), ("G06", "軽減税率対象"), ("G07", "計"), ("G12", "上記以外の仕入先の計"), ("G13", "軽減税率対象"),
                      ("G14", "計")]:
        lt = left_text(rows5, 2, *d2[code], dy=8, span=440) if code in d2 else ""
        C(f"05.pdf p2 {code} {lab}", code in d2 and norm(lab) in norm(lt), lt[:80])
    C("05.pdf p2 E23 本年中における特殊事情（見出しの下）", "E23" in d2 and "本年中における特殊事情" in norm(above_text(rows5, 2, *d2["E23"])),
      above_text(rows5, 2, *d2["E23"]) if "E23" in d2 else "なし")
    for code, n in (("G06", "1"), ("G13", "6")):
        lt = left_text(rows5, 2, *d2[code], dy=8, span=420) if code in d2 else ""
        C(f"05.pdf p2 {code} 「右記（{n}）のうち軽減税率対象」", norm(f"右記") in norm(lt), lt[:80])
    bad = depr_ok(d2, 6, lambda n: f"E{n + 16:02d}", lambda n: f"M{n:02d}", lambda n: f"G{n + 14:02d}")
    C("05.pdf p2 減価償却 6 行：(E17〜E22, M01〜M06, G15〜G20)", not bad, str(bad))
    # ---- 不動産所得用・現金主義用
    p09, rows9, info9 = load("r07_09")
    C("09.pdf 欄コードの数 52", info9["n_codes"] == 52, str(info9["n_codes"]))
    C("09.pdf 様式ID", info9["form_ids"] == ["NTA0KOA130010090", "NTA0KOA130020090"], str(info9["form_ids"]))
    e1 = codes_on(rows9, 1)
    for n, lab in FUDOSAN_P1.items():
        code = f"G{n:02d}"
        lt = left_text(rows9, 1, *e1[code], dy=8, span=330) if code in e1 else ""
        C(f"09.pdf p1 {code} {lab}", code in e1 and norm(lab) in norm(lt), lt[:70])
    p12, rows12, info12 = load("r07_12")
    C("12.pdf 欄コードの数 168", info12["n_codes"] == 168, str(info12["n_codes"]))
    C("12.pdf 様式ID", info12["form_ids"] == [f"NTA0KOA2200{i}0080" for i in range(1, 5)], str(info12["form_ids"]))
    p13, rows13, info13 = load("r07_13")
    C("13.pdf 欄コードの数 65", info13["n_codes"] == 65, str(info13["n_codes"]))
    C("13.pdf 様式ID", info13["form_ids"] == ["NTA0KOA230010090", "NTA0KOA230020090"], str(info13["form_ids"]))
    # ---- 画像だけの様式（テキスト層がないこと）
    for key, npg in [("r07_01", 2), ("r07_02", 1), ("r07_03", 2), ("ref1", 1), ("ref3", 1), ("s017", 1), ("ref4", 1), ("k260831_02", 10)]:
        _, rr, ii = load(key)
        big = [im for pp in ii["per_page"] for im in pp["images"] if im["w"] > 1000]
        C(f"{key} テキスト層なし・{npg} ページ", ii["n_pages"] == npg and not rr,
          f"pages={ii['n_pages']} runs={len(rr)} big_images={[(im['w'], im['h']) for im in big]}")
    # ---- 記入要領の変更点（001-1・O1-1）と改正通達の別紙（250630）
    for key, qs in [("kinyu_001-1", ["特親", "万円単位", "１", "準確定"]),
                    ("kinyu_O1-1", ["G01", "G07", "G13", "所法", "措法", "震法", "差引金額の合計額", "G65"]),
                    ("k250630_01", ["医療費控除の明細書【令和７年分以降用】", "医療費控除の明細書（次葉）【令和６年分以降用】",
                                    "セルフメディケーション税制の明細書【令和６年分以降用】", "AI-OCR読取対応のための帳票のレイアウト変更", "改訂様式一覧"])]:
        _, rr, ii = load(key)
        t = norm("".join(r[3] for r in sorted(rr, key=lambda r: (r[0], -r[2], r[1]))))
        for q in qs:
            C(f"{key} 文言「{q}」", norm(q) in t, "")
    _, rr, ii = load("kinyu_O1-1")
    res["O1-1_text_sample"] = [r[3] for r in sorted(rr, key=lambda r: (r[0], -r[2], r[1]))][:200]
    _, rr, ii = load("tebiki_003")
    C("003.pdf は AES-256（V5・R6）", (ii["enc"] or {}).get("V") == 5 and (ii["enc"] or {}).get("R") == 6, str(ii["enc"]))
    # ---- 様式ページの PDF と通達の別冊の PDF の一致
    pairs = [("r07_01", ["t06_081", "t06_082"]), ("r07_02", ["t06_083"]), ("r07_03", ["t06_085", "t06_086"]), ("r07_05", ["t06_093"]),
             ("r07_10", ["t06_096"]), ("ref1", ["t06_010-1"]), ("s017", ["t06_010-3"])]
    res["compare"] = []
    for a, bs in pairs:
        A = Pdf((src / f"{a}.pdf").read_bytes())
        apages = A.pages()
        bpages = []
        for b in bs:
            B = Pdf((src / f"{b}.pdf").read_bytes())
            bpages += [(B, pn) for pn in B.pages()]
        same_c = [hashlib.sha256(A.content(pa)).hexdigest() == hashlib.sha256(B.content(pb)).hexdigest() for pa, (B, pb) in zip(apages, bpages)]
        same_i = [[i["sha256_decrypted"] for i in A.images(pa) if i["w"] > 1000] == [i["sha256_decrypted"] for i in B.images(pb) if i["w"] > 1000]
                  for pa, (B, pb) in zip(apages, bpages)]
        big = [len([i for i in A.images(pa) if i["w"] > 1000]) for pa in apages]
        res["compare"].append({"a": a, "b": bs, "pages_a": len(apages), "pages_b": len(bpages), "contents_equal": same_c, "large_images_equal": same_i,
                               "large_images_per_page_a": big, "file_sha_equal": A.sha256 == hashlib.sha256((src / f"{bs[0]}.pdf").read_bytes()).hexdigest()})
        C(f"一致 {a} ↔ {bs}", len(apages) == len(bpages) and all(same_c) and all(same_i), f"contents={same_c} images={same_i} big={big}")
    (out / "pdf_checks.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    md = [f"# PDF の独立な読み取り（入力 `{str(src.relative_to(ROOT)).replace(chr(92), '/') if src.is_absolute() else src}`）", "",
          f"- AES の自己検査（FIPS-197 Appendix C.1）：{res['aes_selftest']}", "", "| 項目 | 結果 | 詳細 |", "|---|---|---|"]
    md += [f"| {c['label']} | {'OK' if c['pass'] else 'NG'} | {c['detail'][:160].replace('|', '／')} |" for c in res["checks"]]
    (out / "pdf_checks.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("checks", sum(c["pass"] for c in res["checks"]), "/", len(res["checks"]))
    for c in res["checks"]:
        if not c["pass"]:
            print("NG", c["label"], c["detail"][:200])


# ======================================================================== 文書のルール
DOCS = {
    "public-sources": "docs/public-sources/20261109_round2_yoshiki-forms-r07.md",
    "measurements": "docs/measurements/20261109_round2_yoshiki-fetch-and-extract.md",
    "hypotheses": "docs/hypotheses/20261109_round2_yoshiki-mapping-table.md",
    "inferences": "docs/inferences/20261109_round2_yoshiki-checks.md",
}
# 個人の情報に当たりうる語（家族の構成・職業・住所の手がかり）
PERSONAL = ["国家公務員", "地方公務員", "単身赴任", "私の", "うちの", "我が家", "長男", "長女", "次男", "次女", "父が", "母が", "妻が", "夫が",
            "市役所", "区役所", "町役場", "村役場", "@", "〒"]


def cmd_docs():
    out = OUT / "docs"
    out.mkdir(parents=True, exist_ok=True)
    res = {}
    for kind, path in DOCS.items():
        t = (ROOT / path).read_text(encoding="utf-8")
        urls = re.findall(r"https?://[^\s）)」`、]+", t)
        refs = sorted(set(re.findall(r"docs/[a-z-]+/[0-9A-Za-z_\-]+\.md", t)))
        ref_kinds = sorted({r.split("/")[1] for r in refs})
        missing = [r for r in refs if not (ROOT / r).exists()]
        scripts = sorted(set(re.findall(r"scripts/[A-Za-z0-9_\-/.]+", t)))
        missing_scripts = [s for s in scripts if not (ROOT / s.rstrip(".")).exists() and "<" not in s and "*" not in s]
        personal = [w for w in PERSONAL if w in t]
        city = sorted(set(re.findall(r"[一-龥]{1,4}(?:市|区|町|村)(?:役所|に住|在住)", t)))
        res[kind] = {"path": path, "n_urls": len(urls), "urls": urls[:50], "refs": refs, "ref_kinds": ref_kinds, "missing_refs": missing,
                     "scripts_referenced": scripts, "missing_scripts": missing_scripts, "personal_words": personal, "city_like": city}
    (out / "docs_checks.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# 文書の種類分け・参照・個人の情報の機械的な確認", ""]
    for kind, r in res.items():
        md += [f"## {kind}：`{r['path']}`", "", f"- 外部 URL の数：{r['n_urls']}", f"- 参照している docs の種類：{r['ref_kinds']}",
               f"- 存在しない docs への参照：{r['missing_refs']}", f"- 存在しない scripts への参照：{r['missing_scripts']}",
               f"- 個人の情報に当たりうる語：{r['personal_words']}　市町村の名前らしい語：{r['city_like']}", ""]
        if kind in ("hypotheses",) and r["urls"]:
            md += ["- 仮説の文書に外部 URL がある（ルール違反）："] + [f"  - {u}" for u in r["urls"]] + [""]
        if kind == "inferences" and r["urls"]:
            md += ["- 推測の文書の外部 URL（確かめ方の中）："] + [f"  - {u}" for u in r["urls"]] + [""]
    (out / "docs_checks.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps({k: {kk: v[kk] for kk in ("n_urls", "ref_kinds", "missing_refs", "missing_scripts", "personal_words", "city_like")} for k, v in res.items()},
                     ensure_ascii=False, indent=1))


def cmd_toc(dl_dir):
    """web で保存した通達の HTML（teiyo_01.htm）を取り直さずに読み、目次の行（<li>）ごとに様式番号・様式名・リンク先を確かめる。"""
    body = (pathlib.Path(dl_dir) / "teiyo_01.htm").read_bytes()
    h = Html()
    h.feed(decode_html(body))
    res = {"source": f"{pathlib.Path(dl_dir).name}/teiyo_01.htm", "sha256": hashlib.sha256(body).hexdigest(), "toc": []}
    for num, name, pdf in TOC:
        rows = [r for r in h.rows if norm(r["text"]).startswith(norm(num))]
        hit = [r for r in rows if norm(name) in norm(r["text"])]
        link_ok = None if pdf is None else any(any(l.endswith(pdf) for l in r["links"]) for r in hit)
        res["toc"].append({"num": num, "name": name, "pdf": pdf, "rows": len(rows), "name_ok": bool(hit), "link_ok": link_ok,
                           "row_text": [norm(r["text"])[:120] for r in rows[:2]], "links": [r["links"] for r in rows[:2]]})
    res["chapter12"] = [norm(r["text"])[:60] for r in h.rows if "申告書等の処理事務" in r["text"]][:3]
    res["has_shakai_meisai"] = "社会保険料控除等の明細書" in norm("".join(h.out))
    out = OUT / "web"
    (out / "toc_checks.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    md = [f"# 通達「個人課税事務提要（様式編Ⅰ）」の目次の行（`{res['source']}`、SHA-256 `{res['sha256'][:16]}`）", "",
          "| 様式番号 | 様式名（照合した部分） | 行の数 | 名前一致 | リンク一致 | 行の文字 | リンク |", "|---|---|---|---|---|---|---|"]
    md += [f"| {x['num']} | {x['name']} | {x['rows']} | {x['name_ok']} | {x['link_ok']} | {' / '.join(x['row_text'])[:90]} | {x['links']} |" for x in res["toc"]]
    md += ["", f"- 「社会保険料控除等の明細書」の語が本文にあるか：{res['has_shakai_meisai']}"]
    (out / "toc_checks.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


def cmd_enc(paths):
    """PDF の暗号化辞書（/Filter・/V・/R・/Length・暗号方式の名前）だけを読む（復号はしない）。前の担当が取得したファイルにも使う。"""
    out = []
    for p in paths:
        b = pathlib.Path(p).read_bytes()
        em = re.search(rb"/Encrypt\s+(\d+)\s+0\s+R", b)
        rec = {"file": pathlib.Path(p).name, "sha256": hashlib.sha256(b).hexdigest(), "encrypted": bool(em)}
        if em:
            m = re.search(rb"(?<![0-9])%d\s+0\s+obj(.*?)endobj" % int(em.group(1)), b, re.S)
            d = m.group(1) if m else b""
            for k in (b"Filter", b"V", b"R", b"Length", b"P"):
                mm = re.search(rb"/" + k + rb"\s*/?(-?\w+)", d)
                rec[k.decode()] = mm.group(1).decode() if mm else None
            rec["cfm"] = sorted({x.decode() for x in re.findall(rb"/CFM\s*/(\w+)", d)})
        out.append(rec)
    (OUT / "pdf").mkdir(parents=True, exist_ok=True)
    (OUT / "pdf" / "enc_checks.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not argv:
        print(__doc__)
        return 2
    if argv[0] == "web":
        cmd_web()
    elif argv[0] == "egov":
        cmd_egov()
    elif argv[0] == "pdf" and len(argv) == 2:
        cmd_pdf(argv[1])
    elif argv[0] == "enc" and len(argv) >= 2:
        cmd_enc(argv[1:])
    elif argv[0] == "toc" and len(argv) == 2:
        cmd_toc(argv[1])
    elif argv[0] == "docs":
        cmd_docs()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

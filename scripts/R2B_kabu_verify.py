"""R2B_kabu: 株式等の譲渡所得・配当所得の調査で書いた主張を、取り直したデータで機械的に確かめる。

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2B_kabu_verify.py

標準ライブラリのみ。リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。
e-Gov の使い方（/law_data の JSON、inline / render / walk）は scripts/R1_egov_articles.py と scripts/IMPL_kyuyo_fetch.py を、
HTML のテキスト化は scripts/R2X_jinteki_web.py を写した（import はしない）。scripts/R2B_kabu_egov.py・R2B_kabu_web.py の結果は使わず、
すべて取り直す（独立の確認）。

やること
 E1  条文の主張（法令・時点・条・含むべき文字列）を、取り直した本文で確かめる。
 E2  地方税法 第313条・附則第33条の2・附則第35条の2の2 を 2023-12-31 と 2024-01-01 で比べる（令和6年度分からの課税方式の一致）。
     令和4年の改正法（AmendLawNum が「令和四年」で始まるもの）の附則から、第313条・附則第33条の2 に触れる文を抜き出す。
 E3  措法 第8条の4第3項第1号・措令 第25条の10の12 の読替えの範囲（「第三十四号の四」か「第三十四号の五」か）を時点ごとに見る。
 E4  所得税法施行令・措法・措令の本文（本則＋附則）で、「第八条の五」と「第二条第一項第三十号」または「合計所得金額」を同じ文に含むものを探す
     （申告不要を選んだ配当が合計所得金額に入らないことを直接定める読替え規定があるかどうか）。
 W1  国税庁・総務省の公開資料を取り直し、引用した文字列が含まれるかを確かめる（PDF は SHA-256 と大きさだけ記録する）。

- ダウンロードは .work/downloads/<ts>_R2B_kabu_verify/ に置く（信頼できないデータ。中でコードを実行しない）。
- 結果は scripts/results/R2B_kabu_verify/：checks.json（すべての検査と結果）、checks.md（読みやすい形）、
  e2_*.txt（版の比較と改正附則の抜き出し）、e4_hits.json。
"""
import difflib
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
API = "https://laws.e-gov.go.jp/api/2"
SLEEP = 1.5
OUT = ROOT / "scripts" / "results" / "R2B_kabu_verify"

LAW = {"shotoku": "340AC0000000033", "shotoku-rei": "340CO0000000096", "sochi": "332AC0000000026",
       "sochi-rei": "332CO0000000043", "chiho": "325AC0000000226", "kokuho-rei": "333CO0000000362"}

# E1：(ID, 法令, asof, "本則:条" or "附則:条", 含むべき文字列)
E1 = [
    # 所得税（措法・措令）
    ("C01", "sochi", "2025-12-31", "本則:8_4", "同項第三十号中「山林所得金額」とあるのは、「山林所得金額並びに租税特別措置法第八条の四第一項（上場株式等に係る配当所得等の課税の特例）に規定する上場株式等に係る配当所得等の金額"),
    ("C01b", "sochi", "2026-12-31", "本則:8_4", "同項第三十号中「山林所得金額」とあるのは、「山林所得金額並びに租税特別措置法第八条の四第一項（上場株式等に係る配当所得等の課税の特例）に規定する上場株式等に係る配当所得等の金額"),
    ("C02", "sochi", "2025-12-31", "本則:8_4", "その年中に支払を受けるべき特定上場株式等の配当等に係る配当所得につき前項の規定の適用を受けようとする旨の記載のある確定申告書を提出した場合に限り適用する"),
    ("C03", "sochi", "2025-12-31", "本則:8_4", "その者がその同一の年中に支払を受けるべき他の特定上場株式等の配当等に係る配当所得については、同項の規定は、適用しない"),
    ("C04", "sochi", "2025-12-31", "本則:8_4", "の百分の十五に相当する金額に相当する所得税を課する。この場合において、当該上場株式等の配当等に係る配当所得については、同法第九十二条第一項の規定は、適用しない"),
    ("C05", "sochi", "2025-12-31", "本則:8_4", "同条第一項中「各種所得の金額」とあるのは、「各種所得の金額（上場株式等に係る配当所得等の金額を除く。）」とする"),
    ("C06", "sochi", "2025-12-31", "本則:8_4", "これらの規定中「総所得金額」とあるのは、「総所得金額、上場株式等に係る配当所得等の金額」とする"),
    ("C07", "sochi", "2025-12-31", "本則:8_5", "の計算上当該利子等に係る利子所得の金額又は配当等に係る配当所得の金額を除外し"),
    ("C08", "sochi", "2025-12-31", "本則:8_5", "その一回に支払を受けるべき利子等の額又は配当等の額ごとに行うことができる"),
    ("C09", "sochi", "2025-12-31", "本則:8_5", "十万円に配当計算期間"),
    ("C10", "sochi", "2025-12-31", "本則:37_11", "上場株式等に係る譲渡所得等の金額の計算上生じた損失の金額があるときは、同法その他所得税に関する法令の規定の適用については、当該損失の金額は生じなかつたものとみなす"),
    ("C11", "sochi", "2025-12-31", "本則:37_11", "前条第六項の規定は、第一項の規定の適用がある場合について準用する"),
    ("C12", "sochi", "2025-12-31", "本則:37_10", "同項第三十号中「山林所得金額」とあるのは、「山林所得金額並びに租税特別措置法第三十七条の十第一項"),
    ("C13", "sochi", "2025-12-31", "本則:37_11_5", "当該各号に掲げる金額（当該各号に掲げる金額が同一の源泉徴収選択口座に係るものである場合には、当該源泉徴収選択口座については、第一号に掲げる金額及び第二号に掲げる金額）を除外したところにより"),
    ("C14", "sochi-rei", "2025-12-31", "本則:25_10_12", "（同法第三十七条の十一の五第一項（確定申告を要しない上場株式等の譲渡による所得）の規定の適用を受ける場合には、同項各号に掲げる金額を除外した金額）"),
    ("C14b", "sochi-rei", "2026-12-31", "本則:25_10_12", "（同法第三十七条の十一の五第一項（確定申告を要しない上場株式等の譲渡による所得）の規定の適用を受ける場合には、同項各号に掲げる金額を除外した金額）"),
    ("C15", "sochi", "2025-12-31", "本則:37_12_2", "当該確定申告書に係る年分の第八条の四第一項に規定する上場株式等に係る配当所得等の金額を限度として、当該年分の当該上場株式等に係る配当所得等の金額の計算上控除する"),
    ("C16", "sochi", "2025-12-31", "本則:37_12_2", "その年の前年以前三年内の各年において生じた上場株式等に係る譲渡損失の金額"),
    ("C17", "sochi", "2025-12-31", "本則:37_12_2", "第一項の規定の適用がある場合における第八条の四の規定の適用については、同条第一項中「計算した金額（」とあるのは、「計算した金額（第三十七条の十二の二第一項の規定の適用がある場合には、その適用後の金額。」とする"),
    ("C18", "sochi", "2025-12-31", "本則:37_12_2", "第五項の規定の適用がある場合における第八条の四（第三項を除く。）及び第三十七条の十一（第六項を除く。）の規定の適用については"),
    ("C19", "sochi", "2025-12-31", "本則:37_12_2", "その後において連続して確定申告書を提出している場合"),
    ("C20", "sochi-rei", "2025-12-31", "本則:25_11_2", "同法第七十二条第一項各号列記以外の部分中「総所得金額」とあるのは「総所得金額、上場株式等に係る配当所得等の金額（租税特別措置法第三十七条の十二の二第一項又は第五項（上場株式等に係る譲渡損失の損益通算及び繰越控除）の規定の適用がある場合には、その適用後の金額。以下同じ。）」"),
    ("C21", "sochi-rei", "2025-12-31", "本則:25_11_2", "同法第七十二条第一項各号列記以外の部分中「総所得金額」とあるのは「総所得金額、上場株式等に係る譲渡所得等の金額（租税特別措置法第三十七条の十二の二第五項（上場株式等に係る譲渡損失の繰越控除）の規定の適用がある場合には、その適用後の金額。以下同じ。）」"),
    ("C31", "sochi-rei", "2025-12-31", "本則:25_11_2", "まず当該上場株式等に係る譲渡所得等の金額から控除し、なお控除しきれない損失の金額があるときは、当該上場株式等に係る配当所得等の金額から控除する"),
    ("C32", "sochi", "2025-12-31", "本則:37_11_6", "それぞれの源泉徴収選択口座において有する源泉徴収選択口座内配当等）に係る利子所得の金額及び配当所得の金額の合計額ごとに行うものとする"),
    ("C33", "sochi", "2025-12-31", "本則:37_11_6", "当該源泉徴収選択口座内配当等に係る利子所得の金額及び配当所得の金額の合計額については、第八条の五第一項及び第二項の規定は、適用しない"),
    ("C34", "chiho", "2026-01-01", "本則:314_2", "所得税法第二条第一項第三十二号の規定は、第一項第九号及び第三百十四条の六の勤労学生の意義について準用する"),
    ("C35", "chiho", "2026-01-01", "附則:33_2", "第三百十四条の二第一項（第十号の二及び第十二号に係る部分に限る。）及び第九項"),
    ("C22", "sochi", "2025-12-31", "本則:37_14", "その不足額は、所得税に関する法令の規定の適用については、ないものとみなす"),
    ("C23", "sochi", "2025-12-31", "本則:37_14", "合計額が百二十万円を超えないもの"),
    ("C24", "sochi", "2025-12-31", "本則:37_14", "合計額が二百四十万円を超えないもの"),
    ("C25", "sochi", "2025-12-31", "本則:37_14", "合計額が千八百万円を超えることとなる"),
    ("C26", "sochi", "2025-12-31", "本則:37_14", "合計額が千二百万円を超える場合"),
    ("C27", "sochi", "2025-12-31", "本則:9_8", "所得税を課さない"),
    ("C28", "shotoku", "2025-12-31", "本則:92", "当該配当所得の金額に百分の十を乗じて計算した金額"),
    ("C29", "shotoku", "2025-12-31", "本則:92", "外国法人から受けるこれらの金額に係るもの"),
    ("C30", "sochi", "2025-12-31", "本則:9", "投資法人から支払を受けるべき配当等"),
    # 住民税（地方税法）
    ("L01", "chiho", "2026-01-01", "本則:313", "特定配当等に係る所得を有する者に係る総所得金額は、当該特定配当等に係る所得の金額を除外して算定するものとする"),
    ("L02", "chiho", "2026-01-01", "本則:313", "前年分の所得税に係る第三百十七条の三第一項に規定する確定申告書に特定配当等に係る所得の明細に関する事項その他総務省令で定める事項の記載があるときは"),
    ("L03", "chiho", "2026-01-01", "本則:313", "特定株式等譲渡所得金額に係る所得を有する者に係る総所得金額は、当該特定株式等譲渡所得金額に係る所得の金額を除外して算定するものとする"),
    ("L04", "chiho", "2026-01-01", "本則:313", "前年分の所得税に係る第三百十七条の三第一項に規定する確定申告書に特定株式等譲渡所得金額に係る所得の明細に関する事項その他総務省令で定める事項の記載があるときは"),
    ("L05", "chiho", "2026-01-01", "本則:292", "十三　合計所得金額　第三百十三条第八項及び第九項の規定による控除前の同条第一項の総所得金額、退職所得金額及び山林所得金額の合計額をいう"),
    ("L06", "chiho", "2026-01-01", "附則:33_2", "市町村民税の所得割の納税義務者が前年分の所得税について特定上場株式等の配当等に係る配当所得につき租税特別措置法第八条の四第一項の規定の適用を受けた場合に限り適用する"),
    ("L07", "chiho", "2026-01-01", "附則:33_2", "第二百九十二条第一項第十三号中「山林所得金額」とあるのは、「山林所得金額並びに附則第三十三条の二第五項に規定する上場株式等に係る配当所得等の金額」とする"),
    ("L08", "chiho", "2026-01-01", "附則:33_2", "の百分の三（当該納税義務者が指定都市の区域内に住所を有する場合には、百分の四）"),
    ("L09", "chiho", "2026-01-01", "附則:33_2", "の百分の二（当該納税義務者が指定都市の区域内に住所を有する場合には、百分の一）"),
    ("L10", "chiho", "2026-01-01", "附則:35_2_2", "当該特定株式等譲渡所得金額に係る所得の金額（第三百十三条第十五項の規定により同条第十四項の規定の適用を受けないものを除く。）を除外して算定するものとする"),
    ("L11", "chiho", "2026-01-01", "附則:35_2_6", "第十一項の規定の適用がある場合における附則第三十三条の二第五項、第六項及び第八項並びに附則第三十五条の二の二第五項から第七項までの規定の適用については"),
    ("L12", "chiho", "2026-01-01", "附則:35_2_6", "第八項の規定の適用がある場合における附則第三十三条の二第五項から第八項までの規定の適用については"),
    ("L13", "chiho", "2027-01-01", "本則:313", "特定配当等（第二十三条第一項第十五号ロに掲げるものを除く。以下この項において同じ。）"),
    ("L14", "chiho", "2027-01-01", "本則:23", "ロ　租税特別措置法第九条の三第一号に掲げる同条に規定する配当等（イに掲げるもの及び政令で定めるものを除く。）"),
    ("L15", "chiho", "2026-01-01", "本則:23", "十五　特定配当等　租税特別措置法第八条の四第一項に規定する上場株式等の配当等及び同法第四十一条の十二の二第一項各号に掲げる償還金に係る同条第六項第三号に規定する差益金額をいう"),
    ("L16", "chiho", "2026-01-01", "本則:23", "十七　特定株式等譲渡所得金額　租税特別措置法第三十七条の十一の四第二項に規定する源泉徴収選択口座内調整所得金額をいう"),
    # 国民健康保険法施行令
    ("K01", "kokuho-rei", "2026-04-01", "本則:29_7", "地方税法第三百十四条の二第一項に規定する総所得金額及び山林所得金額並びに他の所得と区分して計算される所得の金額の合計額から同条第二項の規定による控除をした後の総所得金額及び山林所得金額並びに他の所得と区分して計算される所得の金額の合計額（以下「基礎控除後の総所得金額等」という。）"),
    ("K02", "kokuho-rei", "2026-04-01", "本則:29_7", "同法附則第三十三条の二第五項に規定する上場株式等に係る配当所得等の金額（同法附則第三十五条の二の六第八項又は第十一項の規定の適用がある場合には、その適用後の金額）"),
    ("K03", "kokuho-rei", "2026-04-01", "本則:29_7", "同法附則第三十五条の二の二第五項に規定する上場株式等に係る譲渡所得等の金額（同法附則第三十五条の二の六第十一項又は第三十五条の三第十三項若しくは第十五項の規定の適用がある場合には、その適用後の金額）"),
]

# E2：令和6年度分からの課税方式の一致（地方税法）
E2_ASOFS = ["2023-12-31", "2024-01-01"]
E2_KEYS = ["本則:313", "附則:33_2", "附則:35_2_2"]
# E3：読替えの範囲
E3 = [("sochi", ["2025-12-31", "2026-01-01", "2026-11-09", "2026-12-31"], "本則:8_4"),
      ("sochi-rei", ["2025-12-31", "2026-01-01", "2026-11-09", "2026-12-31"], "本則:25_10_12")]
# E4：申告不要の配当と合計所得金額の読替えを探す
E4 = [("shotoku-rei", "2025-12-31"), ("sochi", "2025-12-31"), ("sochi-rei", "2025-12-31")]

# W1：(ID, URL, 含むべき文字列のリスト)
W1 = [
    ("W_ta1331", "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1331.htm",
     ["その申告する上場株式等の配当等の全額について、総合課税と申告分離課税のいずれかを選択することになります",
      "合計所得金額に含まれない", "その適用前の金額になります",
      "確定申告において選択した、または、選択しなかった方法は、その後、修正申告や更正の請求において変更することはできません"]),
    ("W_ta1330", "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1330.htm",
     ["1回に支払を受けるべき配当等の額ごと（特定口座制度における源泉徴収口座に受け入れた配当等については、口座ごと）に選択することができます"]),
    ("W_ta1476", "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1476.htm",
     ["口座ごとに、申告するまたは申告不要とすることの選択をすることができます",
      "源泉徴収口座内で生じた上場株式等に係る譲渡損失の金額を申告する場合には、その源泉徴収口座に受け入れた上場株式等に係る利子等の金額および配当等の金額を申告不要とすることはできない"]),
    ("W_ta1474", "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1474.htm",
     ["上場株式等の譲渡がなかった年も、譲渡損失を翌年へ繰り越すための申告が必要です",
      "非課税口座（NISA）及び未成年者口座（ジュニアNISA）内の上場株式等を譲渡したことにより生じた譲渡損失については、損益通算及び繰越控除はできません"]),
    ("W_y01", "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/2025/03/order2/yogo/3-2_y01.htm",
     ["この制度を選択した利子等・配当等の金額は、「合計所得金額」に含みません",
      "源泉徴収口座内の譲渡損失を申告する場合には、同一口座内の利子所得・配当所得の金額を併せて申告する必要があります"]),
    ("W_1_12", "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/2025/01/1_12.htm",
     ["令和６年度の個人住民税から",
      "所得税等の確定申告で選択した総合課税、申告分離課税又は確定申告不要制度の課税方式は、個人住民税においても同様の課税方式となります"]),
    ("W_kabutsu_37_11_5", "https://www.nta.go.jp/law/tsutatsu/kobetsu/shotoku/sochiho/020624/sanrin/1273/37_11_5/01.htm",
     ["所得税法第2条第1項第30号イ(2)に規定する「合計所得金額」", "当該源泉徴収選択口座ごとに行うことができる"]),
    ("W_sochitsu_8_5", "https://www.nta.go.jp/law/tsutatsu/kobetsu/shotoku/sochiho/801226/sinkoku/57/08/06.htm",
     ["当該利子所得の金額又は配当所得の金額を総所得金額等の計算上除外することはできないことに留意する"]),
    ("W_yoshiki_r07_02", "https://www.nta.go.jp/taxes/shiraberu/shinkoku/yoshiki/01/shinkokusho/pdf/r07/02.pdf", []),
    ("W_soumu_r040715", "https://www.soumu.go.jp/main_content/000833994.pdf", []),
]

BLOCK_LIKE = {"Paragraph", "Item"} | {f"Subitem{i}" for i in range(1, 11)}


def http_get(url, accept="application/json", timeout=300):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept, "Accept-Language": "ja"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body, st, hdr = r.read(), r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        body, st, hdr = e.read(), e.code, dict(e.headers or {})
    time.sleep(SLEEP)
    return st, hdr, body


# ---- e-Gov のテキスト化（R1_egov_articles.py / IMPL_kyuyo_fetch.py から写した） ----
def inline(n):
    if isinstance(n, str):
        return n
    if n.get("tag") in ("Rt",):
        return ""
    parts = [inline(c) for c in n.get("children", [])]
    if n.get("tag", "").endswith("Sentence") and any(isinstance(c, dict) and c.get("tag") == "Column" for c in n.get("children", [])):
        return "　".join(p for p in parts if p)
    return "".join(parts)


def render(n, depth, lines):
    if isinstance(n, str):
        if n.strip():
            lines.append("  " * depth + n)
        return
    tag = n.get("tag", "")
    ch = n.get("children", [])
    if tag in BLOCK_LIKE:
        title = "".join(inline(c) for c in ch if isinstance(c, dict) and c.get("tag", "").endswith(("Num", "Title")) and c.get("tag") != "ParagraphCaption")
        sent = [c for c in ch if isinstance(c, dict) and c.get("tag", "").endswith("Sentence")]
        body = "　".join(inline(s) for s in sent)
        cap = [inline(c) for c in ch if isinstance(c, dict) and c.get("tag") == "ParagraphCaption"]
        if cap:
            lines.append("  " * depth + cap[0])
        num = n.get("attr", {}).get("Num", "")
        prefix = title if title else (f"（{tag}{num}）" if tag == "Paragraph" else "")
        lines.append("  " * depth + (prefix + "　" if prefix else "") + body)
        for c in ch:
            if isinstance(c, dict) and not (c.get("tag", "").endswith(("Num", "Title", "Sentence")) or c.get("tag") == "ParagraphCaption"):
                render(c, depth + 1, lines)
        return
    if tag == "TableRow":
        cells = [inline(c).replace("\n", " ") for c in ch if isinstance(c, dict)]
        lines.append("  " * depth + "| " + " | ".join(cells) + " |")
        return
    if tag in ("ArticleCaption", "ArticleTitle", "SupplProvisionLabel", "ChapterTitle", "SectionTitle"):
        lines.append("  " * depth + inline(n))
        return
    for c in ch:
        render(c, depth, lines)


def walk(n, fn, path=()):
    if isinstance(n, dict):
        fn(n, path)
        for c in n.get("children", []):
            walk(c, fn, path + (n,))


class Law:
    """取得した1つの版。本則・原始附則の条をテキストで引けるようにする。"""

    def __init__(self, short, asof, dl, log):
        law_id = LAW[short]
        url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
        st, _, body = http_get(url)
        (dl / f"{law_id}_{asof}.json").write_bytes(body)
        if st != 200:
            raise RuntimeError(f"{url} -> {st}")
        d = json.loads(body)
        ri = d.get("revision_info") or {}
        self.meta = {"short": short, "law_id": law_id, "asof": asof, "url": url,
                     "law_revision_id": ri.get("law_revision_id"), "amendment_law_num": ri.get("amendment_law_num"),
                     "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                     "current_revision_status": ri.get("current_revision_status"),
                     "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
        log.append(self.meta)
        print("ok", short, asof, ri.get("law_revision_id"), ri.get("current_revision_status"), flush=True)
        self.root = d["law_full_text"]
        self.arts = {}
        self.suppl = []

        def collect(n, path):
            if n.get("tag") == "SupplProvision":
                self.suppl.append(n)
            if n.get("tag") != "Article":
                return
            sp = [p for p in path if p.get("tag") == "SupplProvision"]
            if not sp:
                self.arts["本則:" + n["attr"].get("Num")] = n
            elif "AmendLawNum" not in (sp[-1].get("attr") or {}):
                self.arts["附則:" + n["attr"].get("Num")] = n
        walk(self.root, collect)

    def text(self, key):
        a = self.arts.get(key)
        if a is None:
            return None
        tl = []
        render(a, 0, tl)
        return "\n".join(tl)


class Extract(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        if tag in ("br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "dt", "dd", "table"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def norm(s):
    return re.sub(r"\s+", "", s or "")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_R2B_kabu_verify"
    dl.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    fetch_log, checks = [], []
    cache = {}

    def law(short, asof):
        k = (short, asof)
        if k not in cache:
            cache[k] = Law(short, asof, dl, fetch_log)
        return cache[k]

    # E1
    for cid, short, asof, key, needle in E1:
        t = law(short, asof).text(key)
        ok = t is not None and norm(needle) in norm(t)
        checks.append({"id": cid, "kind": "E1", "law": short, "asof": asof, "key": key,
                       "law_revision_id": law(short, asof).meta["law_revision_id"], "needle": needle, "ok": ok})
    # E2
    e2 = [f"# E2 地方税法の版の比較 {E2_ASOFS[0]} vs {E2_ASOFS[1]}", ""]
    la, lb = law("chiho", E2_ASOFS[0]), law("chiho", E2_ASOFS[1])
    e2 += [f"- {E2_ASOFS[0]}: {la.meta['law_revision_id']} {la.meta['current_revision_status']}",
           f"- {E2_ASOFS[1]}: {lb.meta['law_revision_id']} {lb.meta['current_revision_status']}", ""]
    for key in E2_KEYS:
        xa, xb = la.text(key) or "", lb.text(key) or ""
        e2.append(f"## {key}: {'同じ' if xa == xb else '違う'}")
        if xa != xb:
            e2 += ["```diff"] + list(difflib.unified_diff(xa.splitlines(), xb.splitlines(), E2_ASOFS[0], E2_ASOFS[1], lineterm="", n=0)) + ["```"]
        e2.append("")
    e2.append("## 令和4年の改正法の附則で、第三百十三条・附則第三十三条の二・附則第三十五条の二の二・「六年新法」に触れる文（2024-01-01 版の本文に収録されたもの）")
    e2_hits = []
    for s in lb.suppl:
        an = (s.get("attr") or {}).get("AmendLawNum", "")
        if not an.startswith("令和四年"):
            continue

        def fn2(n, path, an=an):
            if n.get("tag") != "Sentence":
                return
            t = inline(n)
            if re.search(r"第三百十三条|附則第三十三条の二|附則第三十五条の二の二|六年新法", t):
                num = {p.get("tag"): (p.get("attr") or {}).get("Num") for p in path if p.get("tag") in ("Article", "Paragraph", "Item")}
                e2_hits.append({"amend_law_num": an, "article": num.get("Article"), "paragraph": num.get("Paragraph"),
                                "item": num.get("Item"), "text": t})
        walk(s, fn2)
    for h in e2_hits:
        e2.append(f"- [{h['amend_law_num']}] 附則 第{h['article']}条 第{h['paragraph']}項 第{h['item']}号：{h['text'][:1500]}")
    checks.append({"id": "E2c", "kind": "E2", "claim": "令和4年法律第1号の附則に「令和六年度以後の年度分の個人の市町村民税について適用」がある",
                   "ok": any("令和六年度以後の年度分の個人の市町村民税について適用" in h["text"] for h in e2_hits)})
    (OUT / "e2_chiho_2023-12-31_vs_2024-01-01.md").write_text("\n".join(e2), encoding="utf-8")
    t313b = lb.text("本則:313") or ""
    t313a = la.text("本則:313") or ""
    needle_new = "前年分の所得税に係る第三百十七条の三第一項に規定する確定申告書に特定配当等に係る所得の明細に関する事項"
    checks.append({"id": "E2a", "kind": "E2", "claim": "2024-01-01 版の第313条に「前年分の所得税に係る…確定申告書に特定配当等…の記載があるとき」がある",
                   "ok": norm(needle_new) in norm(t313b)})
    checks.append({"id": "E2b", "kind": "E2", "claim": "2023-12-31 版の第313条にはその文がない（改正前）",
                   "ok": norm(needle_new) not in norm(t313a)})
    # E3
    e3 = []
    for short, asofs, key in E3:
        for asof in asofs:
            t = law(short, asof).text(key) or ""
            m = re.search(r"所得税法第二条第一項第三十号から(第三十四号の[四五])まで", t)
            e3.append({"law": short, "asof": asof, "key": key, "law_revision_id": law(short, asof).meta["law_revision_id"],
                       "range_end": m.group(1) if m else None})
    checks.append({"id": "E3", "kind": "E3", "claim": "読替えの範囲の終わり（第三十四号の四/五）を時点ごとに記録", "detail": e3, "ok": True})
    # E4
    e4 = []
    for short, asof in E4:
        L = law(short, asof)

        def fn(n, path):
            if n.get("tag") != "Sentence":
                return
            txt = inline(n)
            if "第八条の五" in txt and ("第二条第一項第三十号" in txt or "合計所得金額" in txt):
                art = next((p for p in reversed(path) if p.get("tag") == "Article"), None)
                e4.append({"law": short, "asof": asof, "article": art["attr"].get("Num") if art else None,
                           "in_suppl": any(p.get("tag") == "SupplProvision" for p in path), "snippet": txt[:600]})
        walk(L.root, fn)
    (OUT / "e4_hits.json").write_text(json.dumps(e4, ensure_ascii=False, indent=1), encoding="utf-8")
    checks.append({"id": "E4", "kind": "E4", "claim": "所令・措法・措令で「第八条の五」と「第二条第一項第三十号」または「合計所得金額」を同じ文に含むものの件数",
                   "count": len(e4), "ok": True})
    # W1
    wdl = dl / "web"
    wdl.mkdir()
    web_log = []
    for wid, url, needles in W1:
        st, hdr, body = http_get(url, accept="*/*", timeout=60)
        ext = ".pdf" if url.endswith(".pdf") else ".html"
        (wdl / f"{wid}{ext}").write_bytes(body)
        rec = {"id": wid, "url": url, "status": st, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
               "last_modified": hdr.get("Last-Modified")}
        web_log.append(rec)
        if ext == ".html":
            s = None
            for cs in ("utf-8", "cp932"):
                try:
                    s = body.decode(cs)
                    break
                except UnicodeDecodeError:
                    continue
            p = Extract()
            p.feed(s or body.decode("utf-8", "replace"))
            txt = norm("".join(p.parts))
            for i, nd in enumerate(needles):
                checks.append({"id": f"{wid}#{i + 1}", "kind": "W1", "url": url, "needle": nd, "ok": norm(nd) in txt})
    out = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "fetches": fetch_log, "web": web_log, "checks": checks}
    (OUT / "checks.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    md = [f"# R2B_kabu_verify 結果（{ts}）", "", f"- 合格 {sum(1 for c in checks if c['ok'])} / {len(checks)}", ""]
    md += ["| ID | 種類 | 対象 | 結果 |", "|---|---|---|---|"]
    for c in checks:
        tgt = c.get("key") and f"{c['law']} {c['asof']} {c['key']}" or c.get("url") or c.get("claim", "")
        md.append(f"| {c['id']} | {c['kind']} | {tgt} | {'OK' if c['ok'] else '**NG**'} |")
    md += ["", "## E3 読替えの範囲", ""] + [f"- {x['law']} {x['asof']} {x['key']} {x['law_revision_id']}: {x['range_end']}" for x in e3]
    md += ["", f"## E4 件数：{len(e4)}（詳細は e4_hits.json）"]
    md += ["", "## 取得した版", ""] + [f"- {m['short']} asof={m['asof']} {m['law_revision_id']} {m['current_revision_status']} sha256={m['sha256'][:16]}" for m in fetch_log]
    md += ["", "## Web", ""] + [f"- {w['id']} {w['status']} {w['bytes']}B LM={w['last_modified']} sha256={w['sha256'][:16]}" for w in web_log]
    (OUT / "checks.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md[:4]))
    bad = [c["id"] for c in checks if not c["ok"]]
    print("NG:", bad)
    return 0


if __name__ == "__main__":
    sys.exit(main())

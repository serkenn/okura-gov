r"""R2X_kokuho_verify：国民健康保険料（税）と国民年金保険料の構造（kokuho）の4つの文書に書かれた条番号・文言・数値・版・
公布日・施行日・URL を、担当のスクリプト（R2X_kokuho_lawsearch / egov / keyword / web / values）とは別に書いた取得・解析・計算で確かめる（反証役）。

実行（Python 3.11、標準ライブラリのみ。pyenv のシムは使わない）:
  C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe -I -X utf8 scripts/R2X_kokuho_verify.py egov
      e-Gov 法令API v2 /law_data で各法令を asof ごとに取得し、指定した本則の条と附則（AmendLawNum で選ぶ）を
      条→項→号→イロハ の構造のまま JSON に取り出す。本則の全条の本文のハッシュ（版の差の検査用）と、全文での語の出現回数も記録する。
  ... R2X_kokuho_verify.py revs      /law_revisions で改正履歴（公布日・施行日・状態）を取る
  ... R2X_kokuho_verify.py revdata   改正履歴で見つかった版（law_revision_id）を /law_data/<law_revision_id> で取得する
      （同じ施行日に複数の改正がある国保法・地法の 2027-04-01 の版の並びと、asof 2027-04-01 より後の国保令・地令の版）
  ... R2X_kokuho_verify.py search    /laws（法令名・法令番号）と /keyword（全文検索）を、文書に書かれた問い合わせで再実行する
  ... R2X_kokuho_verify.py web       各ホストの robots.txt を確かめてから、日本年金機構・こども家庭庁・厚労省のページを取得する
  ... R2X_kokuho_verify.py check     ネットワークを使わず、上の出力だけから文書の主張（CLAIMS）を突き合わせ、計算例を別の実装で再計算する
- API の使い方は scripts/R1_egov_articles.py・scripts/IMPL_kyuyo_fetch.py・scripts/R2X_genka_verify.py を読んで写した（import はしない）。
  本文の構造化・テキスト化・版の差・計算は、担当のスクリプトを使わずに書き直した。
- ダウンロードしたものは信頼できないデータ。取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_R2X_kokuho_verify_<mode>/ に置き、その中でインタプリタやツールは実行しない。
  HTML から取り出したテキストは .work/text/<ts>_R2X_kokuho_verify_web/ に置く。
- 結果は scripts/results/R2X_kokuho_verify/ に書く。
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。送るのは法令ID・日付・検索語・公開ページの URL だけ（個人の情報は送らない）。
"""
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
from fractions import Fraction as F

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "results" / "R2X_kokuho_verify"
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
WAIT = 1.5
A4 = ["2025-04-01", "2026-04-01", "2026-11-09", "2027-04-01"]
NOW = ["2026-11-09"]

# 略称: (law_id, 文書が書いた法令名, [asof], [本則の条 Num]（"__ALL__" は全条）, [(附則の AmendLawNum の正規表現 または "(原始附則)", [条 Num] または None=全体)], [全文で数える語])
LAWS = {
    "kokuho": ("333AC0000000192", "国民健康保険法", A4,
               ["4", "5", "6", "9", "72_3_2", "76", "76_2", "76_3", "77", "77_2", "78", "81", "82_3", "116", "116_2"],
               [(r"令和六年.*法律第四七号$", None), (r"令和八年.*法律第三一号$", None), (r"令和八年.*法律第五一号$", None)],
               ["擬制世帯主", "旧ただし書"]),
    "kokuho-rei": ("333CO0000000362", "国民健康保険法施行令", A4, ["27_2", "29_7", "29_7_2", "29_8"],
                   [("(原始附則)", ["5"]), (r"令和七年.*政令第三二号$", None), (r"令和八年.*政令第二号$", None),
                    (r"令和三年.*政令第二五三号$", None), (r"令和五年.*政令第二四三号$", None)],
                   ["擬制世帯主", "旧ただし書", "租税特別措置法第二十九条の四"]),
    "kokuho-ki": ("333M50000100053", "国民健康保険法施行規則", NOW, [], [], ["出産の日"]),
    "chiho": ("325AC0000000226", "地方税法", A4,
              ["20_4_2", "313", "314_2", "703_4", "703_5", "703_5_2", "705", "706", "706_2", "717"],
              [("(原始附則)", ["35_5", "35_6", "35_7", "36", "37", "37_2", "37_3"]), (r"令和六年.*法律第四七号$", None),
               (r"令和八年.*法律第三一号$", None), (r"令和八年.*法律第五一号$", None)],
              ["擬制世帯主", "旧ただし書", "租税特別措置法第二十九条の四"]),
    "chiho-rei": ("325CO0000000245", "地方税法施行令", A4, ["6_17", "56_88_2", "56_89"],
                  [("(原始附則)", ["18_8"]), (r"令和七年.*政令第一一九号$", None), (r"令和八年.*政令第八三号$", None)], ["租税特別措置法第二十九条の四"]),
    "kaigo": ("409AC0000000123", "介護保険法", NOW, ["9"], [], []),
    "kokunen": ("334AC0000000141", "国民年金法", A4,
                ["7", "36_3", "87", "87_2", "88", "88_2", "88_3", "89", "90", "90_2", "90_3"],
                [(r"平成一六年.*法律第一〇四号$", ["19"]), (r"平成二六年.*法律第六四号$", ["14"]),
                 (r"令和六年.*法律第四七号$", None), (r"令和七年.*法律第七四号$", None)], []),
    "kokunen-rei": ("334CO0000000184", "国民年金法施行令", A4,
                    ["5_4", "6_7", "6_7_2", "6_8", "6_8_2", "6_9", "6_9_2", "6_10", "6_11", "6_12"], [], []),
    "kokunen-ki": ("335M50000100012", "国民年金法施行規則", NOW, ["77_2"], [], []),
    "kaiteiritsu": ("417CO0000000092", "国民年金法による改定率の改定等に関する政令", A4, "__ALL__", [], []),
    "h26kei": ("426CO0000000353", "政府管掌年金事業等の運営の改善のための国民年金法等の一部を改正する法律の一部の施行に伴う経過措置に関する政令",
               NOW, ["11", "14", "15"], [], []),
    "h16kei": ("416CO0000000298", "平成十六年度、平成十七年度、平成十九年度及び平成二十年度の国民年金制度及び厚生年金保険制度並びに国家公務員共済組合制度の改正に伴う厚生労働省関係法令に関する経過措置に関する政令",
               NOW, ["22", "24", "25"], [], []),
    # 推測の文書（KI1・KI9）が使う給与所得控除の最低額（文書は出典を書いていないので、ここで原文に当たる）
    "shotoku": ("340AC0000000033", "所得税法", ["2025-12-31", "2026-12-31"], ["28"], [], []),
    "sochi": ("332AC0000000026", "租税特別措置法", ["2026-12-31"], ["29_4"], [], []),
}

# 文書（[PS-KH] §0、[M-KH] §2.1）が書いた版。(略称, asof) → (law_revision_id, 改正法令（数字）, 施行日, 状態, SHA-256 先頭16桁, バイト数)
DOC_REVS = {
    ("kokuho", "2025-04-01"): ("333AC0000000192_20250401_505AC0000000031", "令和5年法律第31号", "2025-04-01", "PreviousEnforced", "bd320e37a7ae9ddd", 943493),
    ("kokuho", "2026-04-01"): ("333AC0000000192_20260401_506AC0000000047", "令和6年法律第47号", "2026-04-01", "PreviousEnforced", "e063988040b3d28f", 974857),
    ("kokuho", "2026-11-09"): ("333AC0000000192_20261001_507AC0000000087", "令和7年法律第87号", "2026-10-01", "CurrentEnforced", "8842c78a13f64d73", 988946),
    ("kokuho", "2027-04-01"): ("333AC0000000192_20270401_508AC0000000051", "令和8年法律第51号", "2027-04-01", "UnEnforced", "27d2ae05502d7d8b", 1008307),
    ("kokuho-rei", "2025-04-01"): ("333CO0000000362_20250401_507CO0000000032", "令和7年政令第32号", "2025-04-01", "PreviousEnforced", "0eea1bb9fe1c85ba", 1368284),
    ("kokuho-rei", "2026-04-01"): ("333CO0000000362_20260401_508CO0000000002", "令和8年政令第2号", "2026-04-01", "PreviousEnforced", "beb2bf7a59170169", 1390901),
    ("kokuho-rei", "2026-11-09"): ("333CO0000000362_20260801_508CO0000000240", "令和8年政令第240号", "2026-08-01", "CurrentEnforced", "913bd2d8016edf64", 1436152),
    ("kokuho-rei", "2027-04-01"): ("333CO0000000362_20260801_508CO0000000240", "令和8年政令第240号", "2026-08-01", "CurrentEnforced", "913bd2d8016edf64", 1436152),
    ("kokuho-ki", "2026-11-09"): ("333M50000100053_20261001_508M60000100144", "令和8年厚生労働省令第144号", "2026-10-01", "CurrentEnforced", "38595e315f9f3350", 836133),
    ("chiho", "2025-04-01"): ("325AC0000000226_20250401_507AC0000000007", "令和7年法律第7号", "2025-04-01", "PreviousEnforced", "29fe4d615cd8ceef", 12367882),
    ("chiho", "2026-04-01"): ("325AC0000000226_20260401_508AC0000000002", "令和8年法律第2号", "2026-04-01", "PreviousEnforced", "06db2ba6ccfec62e", 12155003),
    ("chiho", "2026-11-09"): ("325AC0000000226_20261101_508AC0000000002", "令和8年法律第2号", "2026-11-01", "CurrentEnforced", "3dd29e0078bf24e0", 12181725),
    ("chiho", "2027-04-01"): ("325AC0000000226_20270401_508AC0000000051", "令和8年法律第51号", "2027-04-01", "UnEnforced", "ad65ea25cbad5bd4", 12272755),
    ("chiho-rei", "2025-04-01"): ("325CO0000000245_20250401_507CO0000000119", "令和7年政令第119号", "2025-04-01", "PreviousEnforced", "d926885b692c5174", 7448064),
    ("chiho-rei", "2026-04-01"): ("325CO0000000245_20260401_508CO0000000083", "令和8年政令第83号", "2026-04-01", "PreviousEnforced", "1098bebe8433c352", 7517128),
    ("chiho-rei", "2026-11-09"): ("325CO0000000245_20261101_508CO0000000083", "令和8年政令第83号", "2026-11-01", "CurrentEnforced", "9bc03b230fb0ed10", 7509563),
    ("chiho-rei", "2027-04-01"): ("325CO0000000245_20270101_508CO0000000083", "令和8年政令第83号", "2027-01-01", "UnEnforced", "962bfc48e43c49b4", 7524467),
    ("kokunen", "2025-04-01"): ("334AC0000000141_20241202_505AC0000000048", "令和5年法律第48号", "2024-12-02", "PreviousEnforced", "f52e4a98a4a2b220", 1788003),
    ("kokunen", "2026-04-01"): ("334AC0000000141_20260401_507AC0000000074", "令和7年法律第74号", "2026-04-01", "PreviousEnforced", "fc7c4b869c56fab9", 1826825),
    ("kokunen", "2026-11-09"): ("334AC0000000141_20261001_507AC0000000074", "令和7年法律第74号", "2026-10-01", "CurrentEnforced", "672850ba089660d8", 1832058),
    ("kokunen", "2027-04-01"): ("334AC0000000141_20261001_507AC0000000074", "令和7年法律第74号", "2026-10-01", "CurrentEnforced", "672850ba089660d8", 1832058),
    ("kokunen-rei", "2025-04-01"): ("334CO0000000184_20250401_507CO0000000106", "令和7年政令第106号", "2025-04-01", "PreviousEnforced", "67ff1d2e03d2ff52", 541868),
    ("kokunen-rei", "2026-04-01"): ("334CO0000000184_20260401_508CO0000000075", "令和8年政令第75号", "2026-04-01", "PreviousEnforced", "9dc65168139e3593", 548911),
    ("kokunen-rei", "2026-11-09"): ("334CO0000000184_20261001_508CO0000000226", "令和8年政令第226号", "2026-10-01", "CurrentEnforced", "73f5bbf61a9b8ab1", 551734),
    ("kokunen-rei", "2027-04-01"): ("334CO0000000184_20261001_508CO0000000226", "令和8年政令第226号", "2026-10-01", "CurrentEnforced", "73f5bbf61a9b8ab1", 551734),
    ("kokunen-ki", "2026-11-09"): ("335M50000100012_20261001_508M60000100121", "令和8年厚生労働省令第121号", "2026-10-01", "CurrentEnforced", "7b0086a03a573db7", 1603726),
    ("kaiteiritsu", "2025-04-01"): ("417CO0000000092_20250401_507CO0000000106", "令和7年政令第106号", "2025-04-01", "PreviousEnforced", "2a471159511c5d35", 569730),
    ("kaiteiritsu", "2026-04-01"): ("417CO0000000092_20260401_508CO0000000075", "令和8年政令第75号", "2026-04-01", "CurrentEnforced", "efc3a0f3e2fe8cb1", 579573),
    ("kaiteiritsu", "2026-11-09"): ("417CO0000000092_20260401_508CO0000000075", "令和8年政令第75号", "2026-04-01", "CurrentEnforced", "efc3a0f3e2fe8cb1", 579573),
    ("kaiteiritsu", "2027-04-01"): ("417CO0000000092_20260401_508CO0000000075", "令和8年政令第75号", "2026-04-01", "CurrentEnforced", "efc3a0f3e2fe8cb1", 579573),
    ("kaigo", "2026-11-09"): ("409AC0000000123_20261001_507AC0000000087", "令和7年法律第87号", "2026-10-01", "CurrentEnforced", "cebf49d04cbcd173", 1806374),
    ("h26kei", "2026-11-09"): ("426CO0000000353_20180401_430CO0000000115", None, None, None, None, None),
    ("h16kei", "2026-11-09"): ("416CO0000000298_20240101_505CO0000000144", None, None, None, None, None),
}
# 文書が書いた法令番号（law_id の確認用）
DOC_LAWNUM = {"kaiteiritsu": "平成17年政令第92号", "h26kei": "平成26年政令第353号", "h16kei": "平成16年政令第298号"}

# [M-KH] §1 の /laws の問い合わせと件数、[M-KH] §3 の /keyword の問い合わせと状態・件数
DOC_SEARCH = [
    ("law_title", "国民健康保険法", 9), ("law_title", "国民年金法", 46), ("law_title", "改定率の改定等に関する政令", 3),
    ("law_title", "政府管掌年金事業等の運営の改善のための国民年金法等の一部を改正する法律", None),
    ("law_num", "平成十六年法律第百四号", 0), ("law_num", "平成二十六年法律第六十四号", 0),
    ("law_title", "子ども・子育て支援法", 12), ("law_title", "地方税法施行令", 1), ("law_title", "地方税法施行規則", 1),
    # 反証用に足した問い合わせ：一部改正法そのものが法令として登録されているか
    ("law_num", "令和六年法律第四十七号", None), ("law_num", "令和八年法律第三十一号", None), ("law_num", "令和八年法律第五十一号", None),
]
# [M-KH] §1 が「使った law_id」として書いたもの（その問い合わせの結果に含まれるはず）
DOC_SEARCH_IDS = {"国民健康保険法": ["333AC0000000192", "333CO0000000362", "333M50000100053"],
                  "国民年金法": ["334AC0000000141", "334CO0000000184", "335M50000100012", "417CO0000000092", "426CO0000000353"],
                  "改定率の改定等に関する政令": ["417CO0000000092"], "地方税法施行令": ["325CO0000000245"]}
DOC_KEYWORD = [
    ("年金事業運営改善法附則第十四条第一項第一号", 200, 5), ("平成十六年改正法附則第十九条第二項第一号", 200, 2),
    ("附則第十四条第一項第一号に規定する政令で定める額", 200, 1), ("附則第十九条第二項第一号に規定する政令で定める額", 404, None),
    ("三十五万円に乗じて得た額に三十二万円を加算した額", 200, 1), ("改正法附則第十四条第一項第一号", 200, 44),
    ("改正法附則第十九条第二項第一号", 200, 2),
]

NK = "https://www.nenkin.go.jp/service/kokunen/"
WEB = {
    "nk_hokenryo": NK + "hokenryo/hokenryo.html",
    "nk_zenno": NK + "hokenryo/zenno.html",
    "nk_menjo": NK + "menjo/20150428.html",
    "nk_sanzen": NK + "menjo/20180810.html",
    "nk_ikuji": NK + "menjo/ikujimenjo.html",
    "cfa_shienkin": "https://www.cfa.go.jp/policies/kodomokosodateshienkin",
    "mhlw_kokuho_top": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/iryouhoken/kokumin/index.html",
}
# 文書（[PS-KH] §12.5・§12.6、[M-KH] §5）が書いたこと：id → (状態, 更新日（ページ内）, Last-Modified, タイトル, [本文に含まれるはずの文字列], [本文の語の出現回数の上限 (語, 上限)])
DOC_WEB = {
    "nk_hokenryo": (200, "2026年4月1日", "Wed, 14 Oct 2026 00:26:09 GMT", "国民年金保険料｜日本年金機構",
                    ["国民年金保険料の金額は、1カ月あたり17,920円です（令和8年度）。", "国民年金保険料17,920円（令和8年度）のほかに月額400円の付加保険料を納付することにより"], []),
    "nk_zenno": (200, "2026年9月4日", "Wed, 14 Oct 2026 00:26:09 GMT", "国民年金保険料の前納｜日本年金機構",
                 ["（令和8年度保険料17,920円×12カ月）＋（令和9年度保険料18,290円×12カ月）＝434,520円"], []),
    "nk_menjo": (200, "2026年11月5日", "Thu, 05 Nov 2026 00:00:31 GMT", "国民年金保険料の免除制度・納付猶予制度｜日本年金機構",
                 ["本人・配偶者・世帯主の前年所得", "20歳以上50歳未満の方で、本人・配偶者の前年所得", "（扶養親族等の数+1）×35万円+32万円",
                  "88万円+扶養親族等控除額+社会保険料控除額等", "128万円+", "168万円+", "地方税法に定める障害者、寡婦またはひとり親の場合、基準額が変わります",
                  "4分の3免除（納めた保険料額　4,480円：令和8年度）", "半額免除（納めた保険料額　8,960円：令和8年度）", "4分の1免除（納めた保険料額　13,440円：令和8年度）"], []),
    "nk_sanzen": (200, "2026年10月1日", "Wed, 14 Oct 2026 00:26:10 GMT", "国民年金保険料の産前産後期間の免除制度｜日本年金機構",
                  ["4カ月間", "3カ月前から6カ月間"], []),
    "nk_ikuji": (200, "2026年10月1日", "Wed, 14 Oct 2026 00:26:10 GMT", "国民年金保険料の育児免除制度｜日本年金機構",
                 ["令和8年10月1日以降、1歳になるまでの子", "9カ月間", "最大12カ月間", "令和8年10月1日以降の月分"], []),
    "cfa_shienkin": (200, None, "Mon, 14 Sep 2026 01:52:29 GMT", "加速化プランによる子育て支援の拡充と子ども・子育て支援金｜こども家庭庁", [], [("均等割", 0)]),
    "mhlw_kokuho_top": (404, None, None, None, [], []),
}
DOC_WEB_SHA = {"nk_hokenryo": "3dc7a93c7eca385d", "nk_menjo": "9460b2f46da7a2fc", "nk_sanzen": "4589f50a142d8315", "nk_ikuji": "c8bea077716407ee",
               "nk_zenno": "c7aac959ce33f973", "cfa_shienkin": "6b0a6e32b9ce16df", "mhlw_kokuho_top": "37e627f723d829e5"}


# /law_revisions で見つかった版のうち、文書の主張（令和9年度の改正の有無、18歳への拡大がどの改正によるか）に関わるもの
REVDATA = {
    "kokuho": ["333AC0000000192_20270301_508AC0000000031", "333AC0000000192_20270401_507AC0000000087",
               "333AC0000000192_20270401_508AC0000000031", "333AC0000000192_20270401_508AC0000000051"],
    "chiho": ["325AC0000000226_20270401_506AC0000000060", "325AC0000000226_20270401_507AC0000000007", "325AC0000000226_20270401_507AC0000000087",
              "325AC0000000226_20270401_508AC0000000002", "325AC0000000226_20270401_508AC0000000031", "325AC0000000226_20270401_508AC0000000051"],
    "kokuho-rei": ["333CO0000000362_20270801_508CO0000000240"],
    "chiho-rei": ["325CO0000000245_20290401_508CO0000000083", "325CO0000000245_21171231_508CO0000000251"],
    # 納付猶予の期間（令和12年6月→令和17年6月）がどの版で変わったか（2025-04-01 の版と 2026-04-01 の版の間の版）
    "kokunen": ["334AC0000000141_20250601_504AC0000000068", "334AC0000000141_20250606_507AC0000000057", "334AC0000000141_20250620_507AC0000000074",
                "334AC0000000141_20251201_507AC0000000074", "334AC0000000141_20260401_507AC0000000074"],
}


# ---------------------------------------------------------------- 取得
def http_get(url, accept="application/json", timeout=300):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept, "Accept-Language": "ja"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = (r.status, r.geturl(), dict(r.headers), r.read())
    except urllib.error.HTTPError as e:
        out = (e.code, url, dict(e.headers or {}), e.read())
    time.sleep(WAIT)
    return out


def new_dir(base, mode):
    ts = time.strftime("%Y%m%d-%H%M%S")
    d = ROOT / ".work" / base / f"{ts}_R2X_kokuho_verify_{mode}"
    d.mkdir(parents=True, exist_ok=False)
    return ts, d


def rel(p):
    return str(pathlib.Path(p).relative_to(ROOT)).replace("\\", "/")


# ---------------------------------------------------------------- 法令 JSON の構造化（担当のスクリプトとは別に書いた）
def kids(n):
    return [c for c in n.get("children", []) if isinstance(c, dict)]


def flat(n):
    """要素の中の文字列をすべてつなぐ。ルビ（Rt）は除く。Column を持つ Sentence は全角空白で区切る。"""
    if isinstance(n, str):
        return n
    if n.get("tag") == "Rt":
        return ""
    ch = n.get("children", [])
    sep = "　" if any(isinstance(c, dict) and c.get("tag") == "Column" for c in ch) else ""
    return sep.join(flat(c) for c in ch)


STRUCT_TAGS = {"Paragraph", "Item"} | {f"Subitem{i}" for i in range(1, 11)}


def struct(n):
    """Article / Paragraph / Item / SubitemN を {num, title, sent, full, ch:{num: ...}, rows} にする。"""
    tag = n.get("tag")
    title = ""
    sent = ""
    ch = {}
    for c in kids(n):
        t = c.get("tag", "")
        if t in ("ArticleTitle", "ParagraphNum", "ItemTitle") or re.fullmatch(r"Subitem\d+Title", t):
            title = flat(c)
        elif t in ("ParagraphSentence", "ItemSentence") or re.fullmatch(r"Subitem\d+Sentence", t):
            sent = flat(c)
        elif t in STRUCT_TAGS:
            s = struct(c)
            key = s["num"] if s["num"] not in ch else f"{s['num']}#{len(ch)}"
            ch[key] = s
    rows = []

    def tables(x):
        for c in kids(x):
            if c.get("tag") == "TableRow":
                rows.append([flat(cc) for cc in kids(c)])
            elif c.get("tag") not in STRUCT_TAGS:
                tables(c)
    tables(n)
    out = {"tag": tag, "num": (n.get("attr") or {}).get("Num"), "title": title, "sent": sent, "full": flat(n), "ch": ch}
    if rows:
        out["rows"] = rows
    if tag == "Article":
        out["caption"] = "".join(flat(c) for c in kids(n) if c.get("tag") == "ArticleCaption")
    return out


def parse_law(d, short):
    law_id, _, _, arts, suppl_specs, words = LAWS[short]
    root = d["law_full_text"]
    main_articles, suppls = [], []

    def walk(n, in_suppl):
        if not isinstance(n, dict):
            return
        t = n.get("tag")
        if t == "SupplProvision":
            suppls.append(n)
            return
        if t == "Article" and not in_suppl:
            main_articles.append(n)
            return
        for c in kids(n):
            walk(c, in_suppl)
    walk(root, False)
    hashes = {a["attr"]["Num"]: hashlib.sha256(flat(a).encode("utf-8")).hexdigest()[:16] for a in main_articles}
    by_num = {a["attr"]["Num"]: a for a in main_articles}
    main = {}
    for num in (list(by_num) if arts == "__ALL__" else arts):
        if num in by_num:
            main[num] = struct(by_num[num])
    sup = []
    for sp in suppls:
        an = (sp.get("attr") or {}).get("AmendLawNum") or "(原始附則)"
        for rx, nums in suppl_specs:
            hit = (an == "(原始附則)") if rx == "(原始附則)" else bool(re.search(rx, an))
            if not hit:
                continue
            ent = {"amend": an, "extract": (sp.get("attr") or {}).get("Extract"), "arts": {}, "paras": {}}
            for c in kids(sp):
                if c.get("tag") == "Article" and (nums is None or c["attr"].get("Num") in nums):
                    ent["arts"][c["attr"]["Num"]] = struct(c)
                elif c.get("tag") == "Paragraph" and nums is None:
                    ent["paras"][c["attr"].get("Num")] = struct(c)
            if nums is None:
                ent["full"] = flat(sp)
            sup.append(ent)
    whole = norm(flat(root))
    counts = {w: whole.count(norm(w)) for w in words}
    return {"main": main, "suppl": sup, "hashes": hashes, "counts": counts,
            "suppl_amend_nums": sorted({(s.get("attr") or {}).get("AmendLawNum") or "(原始附則)" for s in suppls})}


def norm(s):
    return re.sub(r"[\s\u3000]+", "", unicodedata.normalize("NFKC", s or ""))


def mode_egov(only=None):
    ts, dl = new_dir("downloads", "egov")
    OUT.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": rel(dl), "fetches": []}
    for short, (law_id, _, asofs, _, _, _) in LAWS.items():
        if only and short not in only:
            continue
        for asof in asofs:
            url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
            st, _, _, body = http_get(url)
            (dl / f"{short}_{asof}.json").write_bytes(body)
            rec = {"short": short, "asof": asof, "url": url, "status": st, "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
            if st == 200:
                d = json.loads(body)
                ri, li = d.get("revision_info") or {}, d.get("law_info") or {}
                rec.update({k: ri.get(k) for k in ("law_title", "law_revision_id", "amendment_law_num", "amendment_enforcement_date",
                                                   "current_revision_status", "amendment_promulgate_date")})
                rec.update({"law_num": li.get("law_num"), "law_id": li.get("law_id")})
                p = parse_law(d, short)
                p["rev"] = rec
                (OUT / f"egov_{short}_{asof}.json").write_text(json.dumps(p, ensure_ascii=False, indent=0), encoding="utf-8")
            log["fetches"].append(rec)
            print(short, asof, st, rec.get("law_revision_id"), flush=True)
    (OUT / "egov_fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


def mode_revdata():
    ts, dl = new_dir("downloads", "revdata")
    OUT.mkdir(parents=True, exist_ok=True)
    log = {"run_at": ts, "download_dir": rel(dl), "fetches": []}
    for short, ids in REVDATA.items():
        for rid in ids:
            url = f"{API}/law_data/{rid}?" + urllib.parse.urlencode({"response_format": "json"})
            st, _, _, body = http_get(url)
            (dl / f"{rid}.json").write_bytes(body)
            rec = {"short": short, "law_revision_id_requested": rid, "url": url, "status": st, "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
            if st == 200:
                d = json.loads(body)
                ri = d.get("revision_info") or {}
                rec.update({k: ri.get(k) for k in ("law_revision_id", "amendment_law_num", "amendment_enforcement_date", "current_revision_status")})
                p = parse_law(d, short)
                p["rev"] = rec
                (OUT / f"egovrev_{short}_{rid}.json").write_text(json.dumps(p, ensure_ascii=False, indent=0), encoding="utf-8")
            log["fetches"].append(rec)
            print(short, rid, st, rec.get("law_revision_id"), flush=True)
    (OUT / "egovrev_fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


def mode_revs():
    ts, dl = new_dir("downloads", "revs")
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"run_at": ts, "download_dir": rel(dl), "laws": {}}
    for short, (law_id, *_rest) in LAWS.items():
        url = f"{API}/law_revisions/{law_id}?" + urllib.parse.urlencode({"response_format": "json"})
        st, _, _, body = http_get(url)
        (dl / f"revisions_{short}.json").write_bytes(body)
        ent = {"url": url, "status": st, "sha256": hashlib.sha256(body).hexdigest()}
        if st == 200:
            d = json.loads(body)
            ent["law_info"] = d.get("law_info")
            ent["revisions"] = [{k: rv.get(k) for k in ("law_revision_id", "law_title", "amendment_law_num", "amendment_law_title",
                                                          "amendment_promulgate_date", "amendment_enforcement_date",
                                                          "amendment_scheduled_enforcement_date", "current_revision_status", "updated")}
                                for rv in d.get("revisions", [])]
        res["laws"][short] = ent
        print(short, st, len(ent.get("revisions", [])), flush=True)
    (OUT / "revisions.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


def mode_search():
    ts, dl = new_dir("downloads", "search")
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"run_at": ts, "download_dir": rel(dl), "laws": [], "keyword": []}
    for i, (k, v, _) in enumerate(DOC_SEARCH):
        url = f"{API}/laws?" + urllib.parse.urlencode({k: v, "limit": 100, "response_format": "json"})
        st, _, _, body = http_get(url)
        (dl / f"laws_{i:02d}.json").write_bytes(body)
        ent = {"param": k, "value": v, "url": url, "status": st}
        if st == 200:
            d = json.loads(body)
            ent["total_count"] = d.get("total_count")
            ent["laws"] = [{"law_id": (x.get("law_info") or {}).get("law_id"), "law_num": (x.get("law_info") or {}).get("law_num"),
                            "law_title": (x.get("revision_info") or {}).get("law_title")} for x in d.get("laws", [])]
        res["laws"].append(ent)
        print("laws", k, v, st, ent.get("total_count"), flush=True)
    for i, (kw, _, _) in enumerate(DOC_KEYWORD):
        url = f"{API}/keyword?" + urllib.parse.urlencode({"keyword": kw, "asof": "2026-11-09", "limit": 50, "response_format": "json"})
        st, _, _, body = http_get(url)
        (dl / f"keyword_{i:02d}.json").write_bytes(body)
        ent = {"keyword": kw, "url": url, "status": st}
        if st == 200:
            d = json.loads(body)
            ent["total_count"] = d.get("total_count")
            ent["laws"] = sorted({(x.get("law_info") or {}).get("law_id") for x in d.get("items", [])})
        else:
            ent["body_head"] = body[:300].decode("utf-8", "replace")
        res["keyword"].append(ent)
        print("keyword", kw, st, ent.get("total_count"), flush=True)
    (OUT / "search.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


class TextOf(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript"}
    BLOCK = {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "dt", "dd", "table", "section"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.title, self._skip, self._in_title = [], "", 0, False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.title += data
        self.parts.append(data)


def decode_html(body, ctype):
    m = re.search(r"charset=([\w\-]+)", ctype or "", re.I) or re.search(rb"charset=[\"']?([\w\-]+)", body[:4000], re.I)
    cs = (m.group(1).decode() if isinstance(m.group(1), bytes) else m.group(1)) if m else "utf-8"
    for c in (cs, "utf-8", "cp932"):
        try:
            return body.decode(c)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", "replace")


def mode_web():
    ts, dl = new_dir("downloads", "web")
    tx = ROOT / ".work" / "text" / f"{ts}_R2X_kokuho_verify_web"
    tx.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"run_at": ts, "download_dir": rel(dl), "text_dir": rel(tx), "robots": {}, "pages": {}}
    robots = {}
    for sid, url in WEB.items():
        u = urllib.parse.urlsplit(url)
        base = f"{u.scheme}://{u.netloc}"
        if base not in robots:
            st, _, hdr, body = http_get(base + "/robots.txt", accept="text/plain", timeout=60)
            (dl / ("robots_" + u.netloc.replace(".", "_") + ".txt")).write_bytes(body)
            rp = urllib.robotparser.RobotFileParser()
            rp.parse(decode_html(body, hdr.get("Content-Type", "")).splitlines() if st == 200 else [])
            robots[base] = rp
            res["robots"][base] = {"status": st, "sha256": hashlib.sha256(body).hexdigest()}
        ok = robots[base].can_fetch(UA, url)
        rec = {"url": url, "robots_allowed": ok}
        if ok:
            st, final, hdr, body = http_get(url, accept="text/html", timeout=60)
            (dl / f"{sid}.html").write_bytes(body)
            p = TextOf()
            p.feed(decode_html(body, hdr.get("Content-Type", "")))
            text = re.sub(r"\n\s*\n+", "\n", "".join(p.parts))
            (tx / f"{sid}.txt").write_text(text, encoding="utf-8")
            m = re.search(r"更新日[：:]?\s*(\d{4})年(\d{1,2})月(\d{1,2})日", text)
            rec.update({"status": st, "final_url": final, "last_modified": hdr.get("Last-Modified"), "sha256": hashlib.sha256(body).hexdigest(),
                        "bytes": len(body), "title": " ".join(p.title.split()), "page_updated": (f"{m.group(1)}年{int(m.group(2))}月{int(m.group(3))}日" if m else None),
                        "text_file": rel(tx / f"{sid}.txt"), "text_norm": norm(text)})
        res["pages"][sid] = rec
        print(sid, rec.get("status"), rec.get("page_updated"), flush=True)
    (OUT / "web.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- 主張（CLAIMS）
# path: ("A", 条, 項, 号, イロハ...)＝本則、("S", AmendLawNum の正規表現, "art"|"par", 条または項, ...)＝附則、("SF", 正規表現)＝その附則の全体。
# 要素が "t:イ" のときは号・イロハを見出し（Title）で探す。must はすべて含む、not_ はどれも含まない（空白を除き NFKC で比べる）。
# missing=True は「その版にその条・項・号がない」ことを確かめる主張。
CLAIMS = []


def c(cid, src, law, asofs, path, must=(), not_=(), missing=False, note=""):
    CLAIMS.append({"id": cid, "src": src, "law": law, "asofs": asofs, "path": path, "must": list(must), "not": list(not_), "missing": missing, "note": note})


R8ON = ["2026-04-01", "2026-11-09", "2027-04-01"]
R25 = ["2025-04-01"]
PS = "PS-KH"
# ---- 国保法
c("K01", PS + " §1.1", "kokuho", R8ON, ("A", "76", "1"), ["前期高齢者納付金等及び後期高齢者支援金等", "介護納付金", "流行初期医療確保拠出金等並びに子ども・子育て支援納付金", "財政安定化基金拠出金",
  "被保険者の属する世帯の世帯主（当該市町村の区域内に住所を有する世帯主に限る。）から保険料を徴収しなければならない。ただし、地方税法の規定により国民健康保険税を課するときは、この限りでない。"])
c("K02", PS + " §1.1・M-KH §2.3", "kokuho", R25, ("A", "76", "1"), ["介護納付金並びに流行初期医療確保拠出金等"], ["子ども・子育て支援納付金"])
c("K03", PS + " §1.1", "kokuho", A4, ("A", "76", "3"), ["介護保険法", "第九条第二号に規定する被保険者である被保険者について賦課する"])
c("K04", PS + " §1.1", "kaigo", NOW, ("A", "9", "1", "2"), ["市町村の区域内に住所を有する四十歳以上六十五歳未満の医療保険加入者（以下「第二号被保険者」という。）"])
c("K05", PS + " §1.1", "kokuho", A4, ("A", "76_2"), ["保険料の賦課期日は、当該年度の初日とする"])
c("K06", PS + " §1.1", "kokuho", NOW, ("A", "76_3"), ["特別徴収", "普通徴収"])
c("K07", PS + " §1.1", "kokuho", NOW, ("A", "77"), ["条例又は規約の定めるところにより、特別の理由がある者に対し、保険料を減免し、又はその徴収を猶予することができる"])
c("K08", PS + " §1.1", "kokuho", NOW, ("A", "78"), ["地方税法第九条、第十三条の二、第二十条、第二十条の二及び第二十条の四の規定を準用する"], ["第二十条の四の二"])
c("K09", PS + " §1.1", "kokuho", A4, ("A", "81"), ["第七十六条から前条までに規定するもののほか、賦課額、保険料率、納期、減額賦課その他保険料の賦課及び徴収等に関する事項は、政令で定める基準に従つて条例又は規約で定める。"])
c("K10", PS + " §1.1", "kokuho", NOW, ("A", "82_3"), ["市町村標準保険料率", "都道府県標準保険料率", "毎年度", "通知", "公表するよう努め"])
c("K11", PS + " §1.1", "kokuho", NOW, ("A", "5"), ["都道府県の区域内に住所を有する者は、当該都道府県が当該都道府県内の市町村とともに行う国民健康保険の被保険者とする"])
c("K12", PS + " §1.1", "kokuho", NOW, ("A", "6"), ["健康保険法", "被扶養者", "共済組合", "高齢者の医療の確保に関する法律", "生活保護法"])
c("K13", PS + " §3.1（特定同一世帯所属者＝後期高齢者医療へ移った者）", "kokuho", NOW, ("A", "6", "1", "8"), ["高齢者の医療の確保に関する法律", "被保険者"])
c("K14", PS + " §1.1", "kokuho", NOW, ("A", "9", "1"), ["世帯主は", "資格の取得及び喪失", "届け出なければならない"])
c("K15", PS + " §1.1", "kokuho", NOW, ("A", "116"), ["修学のため一の市町村の区域内に住所を有する被保険者であつて、修学していないとすれば他の市町村の区域内に住所を有する他人と同一の世帯に属するものと認められるものは、この法律の適用については、当該他の市町村の区域内に住所を有するものとみなし、かつ、当該世帯に属するものとみなす。"])
c("K16", PS + " §1.1", "kokuho", NOW, ("A", "116_2"), ["病院", "入院", "住所"])
c("K16b", "M-KH §2.2（国保法第77条の2 は存在しない）", "kokuho", A4, ("A", "77_2"), missing=True)
c("K17", PS + " §7・M-KH §2.3", "kokuho", ["2025-04-01", "2026-04-01", "2026-11-09"], ("A", "72_3_2", "1"), ["六歳に達する日以後の最初の三月三十一日以前である被保険者"], ["十八歳に達する日"])
c("K18", PS + " §7", "kokuho", ["2027-04-01"], ("A", "72_3_2", "1"), ["十八歳に達する日以後の最初の三月三十一日以前である被保険者について条例で定めるところにより行う保険料の減額賦課又は地方税法第七百三条の五第二項に規定する国民健康保険税の減額"])
c("K19", PS + " §7（国1/2・都道府県1/4）", "kokuho", ["2027-04-01"], ("A", "72_3_2"), ["二分の一", "四分の一"])
c("K20", PS + " §1.1（附則第1条第5号ロ）", "kokuho", ["2026-04-01"], ("S", r"令和六年.*法律第四七号$", "art", "1", "1", "5", "t:ロ"), ["第八条"])
c("K21", PS + " §1.1（附則第1条第5号）", "kokuho", ["2026-04-01"], ("S", r"令和六年.*法律第四七号$", "art", "1", "1", "5"), ["令和八年四月一日"])
c("K22", PS + " §1.1（第8条＝国保法の改正）", "kokuho", ["2026-04-01"], ("SF", r"令和六年.*法律第四七号$"), ["第八条の規定による改正後の国民健康保険法"])
# ---- 国保令
c("R01", PS + " §2.1", "kokuho-rei", R8ON, ("A", "29_7", "1", "4"), ["世帯主の世帯に属する被保険者につき算定した子ども・子育て支援納付金賦課額"])
c("R02", PS + " §2.1", "kokuho-rei", R25, ("A", "29_7", "1", "4"), missing=True)
c("R03", PS + " §2.1", "kokuho-rei", A4, ("A", "29_7", "1", "3"), ["世帯主の世帯に属する被保険者のうち介護保険法第九条第二号に規定する被保険者", "介護納付金賦課被保険者"])
c("R04", PS + " §3.1", "kokuho-rei", R8ON, ("A", "29_7", "2", "2"), ["所得割総額、資産割総額、被保険者均等割総額及び世帯別平等割総額の合計額", "所得割総額、被保険者均等割総額及び世帯別平等割総額の合計額", "所得割総額及び被保険者均等割総額の合計額"])
c("R05", PS + " §3.1", "kokuho-rei", R8ON, ("A", "29_7", "5", "2"), ["十八歳以上被保険者均等割総額"])
c("R06", PS + " §3.1", "kokuho-rei", R8ON, ("A", "29_7", "5", "3"), ["十八歳に達する日以後の最初の三月三十一日の翌日以後である被保険者", "十八歳以上被保険者"])
c("R07", PS + " §3.1・§4.1", "kokuho-rei", R8ON, ("A", "29_7", "2", "4"), ["基礎控除後の総所得金額等", "厚生労働省令で定めるところにより、基礎控除後の総所得金額等を補正するものとする"])
c("R08", PS + " §4.1", "kokuho-rei", R8ON, ("A", "29_7", "2", "5"), ["同法第三百十三条第九項中雑損失の金額に係る部分の規定を適用しないものとして算定"])
c("R09", PS + " §3.1", "kokuho-rei", R8ON, ("A", "29_7", "2", "6"), ["固定資産税の額又は当該額のうち土地及び家屋に係る部分の額"])
c("R10", PS + " §3.1", "kokuho-rei", R8ON, ("A", "29_7", "2", "7"), ["被保険者均等割総額を被保険者の数に按分"])
c("R11", PS + " §3.1", "kokuho-rei", R8ON, ("A", "29_7", "4", "6"), ["介護納付金賦課被保険者の数に按分"])
c("R12", PS + " §3.1", "kokuho-rei", R8ON, ("A", "29_7", "5", "7"), ["次項に規定する基準（同項第十号及び第十一号に係る部分に限る。）"])
c("R13", PS + " §3.1", "kokuho-rei", R8ON, ("A", "29_7", "5", "8"), ["十八歳以上被保険者均等割総額を十八歳以上被保険者の数に按分"])
c("R14", PS + " §3.1（特定世帯・特定継続世帯）", "kokuho-rei", R8ON, ("A", "29_7", "2", "8", "t:イ"),
  ["法第六条第八号に該当したことにより被保険者の資格を喪失した者", "以後五年を経過する月までの間にあるもの（当該世帯に他の被保険者がいない場合に限る。", "「特定世帯」", "二分の一", "八年を経過する月までの間", "「特定継続世帯」", "四分の一"])
c("R15", PS + " §3.1", "kokuho-rei", R8ON, ("A", "29_7", "2", "8", "t:ロ"), ["二分の一"])
c("R16", PS + " §3.1", "kokuho-rei", R8ON, ("A", "29_7", "2", "8", "t:ハ"), ["四分の三"])
c("R17", PS + " §3.1（介護の平等割に特定世帯の扱いなし）", "kokuho-rei", R8ON, ("A", "29_7", "4", "7"), ["介護納付金賦課被保険者が属する世帯の数に按分"], ["特定世帯"])
c("R18", PS + " §5（料・令和8年度以後）", "kokuho-rei", R8ON, ("A", "29_7", "2", "9"), ["基礎賦課額は、六十七万円を超えることができないものであること"])
c("R19", PS + " §5", "kokuho-rei", R8ON, ("A", "29_7", "3", "8"), ["二十六万円を超えることができないものであること"])
c("R20", PS + " §5", "kokuho-rei", R8ON, ("A", "29_7", "4", "8"), ["十七万円を超えることができないものであること"])
c("R21", PS + " §5", "kokuho-rei", R8ON, ("A", "29_7", "5", "10"), ["三万円を超えることができないものであること"])
c("R22", PS + " §5（令和7年度）", "kokuho-rei", R25, ("A", "29_7", "2", "9"), ["六十六万円"])
c("R23", PS + " §5（令和7年度）", "kokuho-rei", R25, ("A", "29_7", "3", "8"), ["二十六万円"])
c("R24", PS + " §5（令和7年度）", "kokuho-rei", R25, ("A", "29_7", "4", "8"), ["十七万円"])
c("R25", PS + " §6.1（令和8年度以後の第6項第1号）", "kokuho-rei", R8ON, ("A", "29_7", "6", "1"),
  ["世帯主並びに当該世帯主の世帯に属する被保険者及び特定同一世帯所属者につき算定した", "地方税法第三百十四条の二第二項第一号に定める金額", "給与等の収入金額が五十五万円を超える者に限る",
   "年齢六十五歳未満の者にあつては当該公的年金等の収入金額が六十万円を超える者に限り、年齢六十五歳以上の者にあつては当該公的年金等の収入金額が百十万円を超える者に限る", "給与所得を有する者を除く",
   "給与所得者等の数から一を減じた数に十万円を乗じて得た金額を加えた金額", "被保険者の数と特定同一世帯所属者の数の合計数に五十七万円を乗じて得た金額", "合計数に三十一万円を乗じて得た金額",
   "被保険者均等割額及び十八歳以上被保険者均等割額並びに世帯別平等割額（世帯別平等割額を賦課しない市町村においては、被保険者均等割額及び十八歳以上被保険者均等割額）",
   "附則第三十三条の二第五項に規定する上場株式等に係る配当所得等の金額", "附則第三十三条の三第五項に規定する土地等に係る事業所得等の金額", "附則第三十四条第四項に規定する長期譲渡所得の金額",
   "附則第三十五条第五項に規定する短期譲渡所得の金額", "附則第三十五条の二第五項に規定する一般株式等に係る譲渡所得等の金額", "附則第三十五条の二の二第五項に規定する上場株式等に係る譲渡所得等の金額",
   "附則第三十五条の四第四項に規定する先物取引に係る雑所得等の金額", "特例適用利子等の額", "特例適用配当等の額", "条約適用利子等の額", "条約適用配当等の額"])
c("R26", PS + " §6.1（令和7年度の版は第5項）", "kokuho-rei", R25, ("A", "29_7", "5", "1"),
  ["世帯主並びに当該世帯主の世帯に属する被保険者及び特定同一世帯所属者", "合計数に五十六万円を乗じて得た金額", "合計数に三十万五千円を乗じて得た金額", "給与等の収入金額が五十五万円を超える者に限る", "六十万円", "百十万円"],
  ["十八歳以上被保険者均等割額"])
c("R27", PS + " §6.1", "kokuho-rei", R8ON, ("A", "29_7", "6", "2"), ["同法第三百十三条第三項、第四項又は第五項の規定を適用せず、所得税法第五十七条第一項、第三項又は第四項の規定の例によらない"])
c("R28", PS + " §6.1", "kokuho-rei", R8ON, ("A", "29_7", "6", "3", "t:イ"), ["十分の七"])
c("R29", PS + " §6.1", "kokuho-rei", R8ON, ("A", "29_7", "6", "3", "t:ロ"), ["三十一万円", "十分の五"])
c("R30", PS + " §6.1", "kokuho-rei", R8ON, ("A", "29_7", "6", "3", "t:ハ"), ["五十七万円", "十分の二"])
c("R31", PS + " §6.1（令和7年度）", "kokuho-rei", R25, ("A", "29_7", "5", "3", "t:ロ"), ["三十万五千円", "十分の五"])
c("R32", PS + " §6.1（令和7年度）", "kokuho-rei", R25, ("A", "29_7", "5", "3", "t:ハ"), ["五十六万円", "十分の二"])
c("R33", PS + " §6.1（第4号）", "kokuho-rei", R8ON, ("A", "29_7", "6", "4"), ["前号の規定による減額を行うことが困難であると認める市町村", "十分の六", "十分の四"])
c("R34", PS + " §6.1（第5号）", "kokuho-rei", R8ON, ("A", "29_7", "6", "5"), ["前二号の規定による減額を行うことが困難であると認める市町村", "十分の五", "十分の三"])
c("R35", PS + " §7", "kokuho-rei", A4[1:], ("A", "29_7", "6", "6"), ["六歳に達する日以後の最初の三月三十一日以前である被保険者", "第二項、第三項及び前項の規定に基づき算定した被保険者均等割額"])
c("R36", PS + " §7", "kokuho-rei", A4[1:], ("A", "29_7", "6", "7"), ["被保険者均等割額に十分の五を乗じて得た額"])
c("R37", PS + " §7（令和7年度の版は第5項第6号・第7号）", "kokuho-rei", R25, ("A", "29_7", "5", "6"), ["六歳に達する日以後の最初の三月三十一日以前である被保険者"])
c("R38", PS + " §8", "kokuho-rei", R8ON, ("A", "29_7", "6", "8"), ["出産する予定の被保険者又は出産した被保険者", "所得割額（出産被保険者につき第二項から前項までの規定に基づき算定した所得割額に限る", "並びに被保険者均等割額及び十八歳以上被保険者均等割額"], ["世帯別平等割額"])
c("R39", PS + " §8", "kokuho-rei", R8ON, ("A", "29_7", "6", "9"), ["出産の予定日（厚生労働省令で定める場合には、出産の日）の属する月", "の前月（多胎妊娠の場合には、三月前）から出産予定月の翌々月までの期間に係る額を基準として算定した額"])
c("R40", PS + " §8（令和7年度の版は第5項第8号）", "kokuho-rei", R25, ("A", "29_7", "5", "8"), ["出産する予定の被保険者又は出産した被保険者"])
c("R41", PS + " §9", "kokuho-rei", R8ON, ("A", "29_7", "6", "10"), ["十八歳に達する日以後の最初の三月三十一日以前である被保険者（以下この号において「十八歳未満被保険者」という。）", "前項第六号の規定に基づき算定した被保険者均等割額"])
c("R42", PS + " §9", "kokuho-rei", R8ON, ("A", "29_7", "6", "11"), ["当該被保険者均等割額であること"])
c("R43", PS + " §9（第5項第1号イ(2)）", "kokuho-rei", R8ON, ("A", "29_7", "5", "1", "t:イ"), ["次項に規定する基準（同項第十号及び第十一号に係る部分に限る。）に従い第六号の規定に基づき算定される被保険者均等割額を減額するものとした場合に減額することとなる額の総額"])
c("R44", PS + " §4.1（第27条の2第1項第1号のかっこ書き）", "kokuho-rei", R8ON, ("A", "27_2", "1", "1"),
  ["附則第三十三条の二第五項", "附則第三十三条の三第五項", "附則第三十四条第四項", "附則第三十五条第五項", "附則第三十五条の二第五項", "附則第三十五条の二の二第五項", "附則第三十五条の四第四項",
   "特例適用利子等", "特例適用配当等", "条約適用利子等", "条約適用配当等", "第二十九条の七第二項第四号及び第五号において同じ"])
c("R45", PS + " §4.3", "kokuho-rei", R8ON, ("A", "29_7_2"), ["特定受給資格者", "特定理由離職者", "所得税法第二十八条第一項に規定する給与所得が含まれている場合においては、当該給与所得については、同条第二項の規定によつて計算した金額の百分の三十に相当する金額", "離職の日の翌日の属する年度の翌年度の末日", "同条第二項第四号中", "同条第六項第一号中"])
c("R46", PS + " §6.1（附則第5条。当分の間）", "kokuho-rei", R8ON, ("S", r"^\(原始附則\)$", "art", "5"),
  ["当分の間", "第二十九条の七第六項第一号", "の規定によつて計算した金額から十五万円を控除した金額", "「百十万円」とあるのは「百二十五万円」"])
c("R47", PS + " §6.1（附則第5条。令和7年度の版）", "kokuho-rei", R25, ("S", r"^\(原始附則\)$", "art", "5"), ["第二十九条の七第五項第一号", "十五万円", "百二十五万円"])
c("R48", PS + " §2.3（令和8年政令第2号附則第4項）", "kokuho-rei", R8ON, ("S", r"令和八年一月一五日政令第二号$", "par", "4"),
  ["第一条の規定による改正後の国民健康保険法施行令第二十九条の七の規定は、令和八年度以後の年度分の保険料について適用し、令和七年度以前の年度分の保険料については、なお従前の例による。"])
c("R49", PS + " §2.3（同附則第1項）", "kokuho-rei", R8ON, ("S", r"令和八年一月一五日政令第二号$", "par", "1"), ["令和八年四月一日から施行する"])
c("R50", PS + " §5（令和7年政令第32号附則第4項）", "kokuho-rei", A4, ("S", r"令和七年二月七日政令第三二号$", "par", "4"),
  ["この政令による改正後の第二十九条の七第二項、第三項及び第五項の規定は、令和七年度以後の年度分の保険料について適用し、令和六年度以前の年度分の保険料については、なお従前の例による。"])
c("R51", PS + " §5（同附則第1項）", "kokuho-rei", A4, ("S", r"令和七年二月七日政令第三二号$", "par", "1"), ["令和七年四月一日から施行する"])
c("R52", PS + " §7（令和3年政令第253号附則第2項）", "kokuho-rei", NOW, ("S", r"令和三年.*政令第二五三号$", "par", "2"),
  ["第一条の規定による改正後の国民健康保険法施行令第二十九条の七第五項（第六号及び第七号に係る部分に限る。）の規定は、令和四年度以後の年度分の国民健康保険の保険料について適用し"])
c("R53", PS + " §7（同附則第1項）", "kokuho-rei", NOW, ("S", r"令和三年.*政令第二五三号$", "par", "1"), ["令和四年四月一日から施行する"])
c("R54", PS + " §8（令和5年政令第243号附則第2項）", "kokuho-rei", NOW, ("S", r"令和五年.*政令第二四三号$", "par", "2"),
  ["第一条の規定による改正後の国民健康保険法施行令第二十九条の七第五項（第八号及び第九号に係る部分に限る。）の規定は、令和五年度分の国民健康保険の保険料のうち令和六年一月以後の期間に係るもの及び令和六年度以後の年度分の当該保険料について適用し"])
c("R55", PS + " §8（同附則第1項）", "kokuho-rei", NOW, ("S", r"令和五年.*政令第二四三号$", "par", "1"), ["令和六年一月一日から施行する"])
# ---- 地法
c("C01", PS + " §1.2", "chiho", R8ON, ("A", "703_4", "1"), ["国民健康保険の被保険者（以下この節において「被保険者」という。）である世帯主（当該市町村の区域内に住所を有する世帯主に限る。）に対し、国民健康保険税を課することができる", "子ども・子育て支援納付金"])
c("C02", PS + " §1.2（擬制。令和8年度以後の版は第38項）", "chiho", R8ON, ("A", "703_4", "38"),
  ["被保険者である資格がない世帯主の属する世帯内に被保険者がある場合には、当該世帯主を第一項の被保険者である世帯主とみなして国民健康保険税を課する。", "世帯に属する被保険者（世帯主を除く。）", "介護納付金課税被保険者（世帯主を除く。）"])
c("C03", PS + " §1.2（令和7年度の版は第28項）", "chiho", R25, ("A", "703_4", "28"), ["被保険者である資格がない世帯主の属する世帯内に被保険者がある場合には、当該世帯主を第一項の被保険者である世帯主とみなして国民健康保険税を課する。"])
c("C04", PS + " §2.2", "chiho", R8ON, ("A", "703_4", "2", "4"), ["子ども・子育て支援納付金課税額"])
c("C05", PS + " §2.2", "chiho", R25, ("A", "703_4", "2", "4"), missing=True)
c("C06", PS + " §2.2", "chiho", A4, ("A", "703_4", "2", "3"), ["介護保険法第九条第二号に規定する第二号被保険者"])
c("C07", PS + " §3.2", "chiho", R8ON, ("A", "703_4", "4"), ["所得割総額、資産割総額、被保険者均等割総額及び世帯別平等割総額の合計額", "所得割総額及び被保険者均等割総額の合計額"])
c("C08", PS + " §3.2", "chiho", R8ON, ("A", "703_4", "13"), ["標準後期高齢者支援金等課税総額は"])
c("C09", PS + " §3.2", "chiho", R8ON, ("A", "703_4", "21"), ["標準介護納付金課税総額は"])
c("C10", PS + " §3.2", "chiho", R8ON, ("A", "703_4", "29"), ["標準子ども・子育て支援納付金課税総額は", "十八歳以上被保険者均等割総額"])
c("C11", PS + " §3.2・§4.2", "chiho", R8ON, ("A", "703_4", "6"), ["第三百十四条の二第一項に規定する総所得金額及び山林所得金額の合計額から同条第二項の規定による控除をした後の総所得金額及び山林所得金額の合計額（以下この条において「基礎控除後の総所得金額等」という。）", "総務省令で定めるところにより"])
c("C12", PS + " §4.2", "chiho", R8ON, ("A", "703_4", "7"), ["第三百十三条第九項中雑損失の金額に係る部分の規定を適用しないものとする"])
c("C13", PS + " §3.2", "chiho", R8ON, ("A", "703_4", "8"), ["固定資産税額又は固定資産税額のうち土地及び家屋に係る部分の額"])
c("C14", PS + " §3.2", "chiho", R8ON, ("A", "703_4", "9"), ["被保険者均等割総額を被保険者の数に按分"])
c("C15", PS + " §3.2", "chiho", R8ON, ("A", "703_4", "10"), ["特定世帯", "特定継続世帯", "二分の一", "四分の三"])
c("C16", PS + " §5（税）", "chiho", R8ON, ("A", "703_4", "11"), ["基礎課税額は、納税義務者間の負担の衡平を考慮して政令で定める金額を超えることができない"])
c("C17", PS + " §3.2", "chiho", R8ON, ("A", "703_4", "15"), ["基礎控除後の総所得金額等に按分"])
c("C18", PS + " §5", "chiho", R8ON, ("A", "703_4", "19"), ["後期高齢者支援金等課税額は、納税義務者間の負担の衡平を考慮して政令で定める金額を超えることができない"])
c("C19", PS + " §3.2", "chiho", R8ON, ("A", "703_4", "23"), ["介護納付金課税被保険者に係る基礎控除後の総所得金額等に按分"])
c("C20", PS + " §5", "chiho", R8ON, ("A", "703_4", "27"), ["介護納付金課税額は、納税義務者間の負担の衡平を考慮して政令で定める金額を超えることができない"])
c("C21", PS + " §3.2", "chiho", R8ON, ("A", "703_4", "31"), ["基礎控除後の総所得金額等に按分"])
c("C22", PS + " §3.2", "chiho", R8ON, ("A", "703_4", "34"), ["十八歳以上被保険者均等割総額は"])
c("C23", PS + " §3.2", "chiho", R8ON, ("A", "703_4", "35"), ["十八歳以上被保険者均等割総額を十八歳以上被保険者の数に按分"])
c("C24", PS + " §5", "chiho", R8ON, ("A", "703_4", "37"), ["子ども・子育て支援納付金課税額は、納税義務者間の負担の衡平を考慮して政令で定める金額を超えることができない"])
c("C25", PS + " §9（第30項）", "chiho", R8ON, ("A", "703_4", "30"), ["子ども・子育て支援納付金課税額は", "十八歳以上被保険者均等割額"])
c("C26", PS + " §1.2（第717条の引用）", "chiho", R8ON, ("A", "703_4", "3"), ["第七百十七条の規定による基礎課税額の減免の額の総額"])
c("C27", PS + " §1.2", "chiho", A4, ("A", "705", "2"), ["国民健康保険税の賦課期日は、四月一日とする"])
c("C28", PS + " §1.2", "chiho", NOW, ("A", "705", "1"), ["条例で定め"])
c("C29", PS + " §1.2", "chiho", NOW, ("A", "706", "1"), ["普通徴収", "特別徴収"])
c("C30", PS + " §1.2", "chiho", NOW, ("A", "706", "2"), ["老齢等年金給付", "六十五歳以上", "特別徴収"])
c("C31", PS + " §1.2", "chiho", NOW, ("A", "706_2"), ["二分の一", "前年度"])
c("C32", PS + " §6.2", "chiho", R8ON, ("A", "703_5", "1"),
  ["納税義務者並びにその世帯に属する被保険者及び特定同一世帯所属者につき算定した", "第三百十三条第三項、第四項又は第五項", "所得税法第五十七条第一項、第三項又は第四項", "政令で定める金額を超えない場合には",
   "政令で定める基準に従い当該市町村の条例で定めるところにより", "被保険者均等割額及び十八歳以上被保険者均等割額又は世帯別平等割額を減額するものとする"])
c("C33", PS + " §7", "chiho", ["2025-04-01", "2026-04-01", "2026-11-09"], ("A", "703_5", "2"), ["六歳に達する日以後の最初の三月三十一日以前である被保険者"])
c("C34", PS + " §7（令和9年度の未施行の版）", "chiho", ["2027-04-01"], ("A", "703_5", "2"), ["十八歳に達する日以後の最初の三月三十一日以前である被保険者"], ["六歳に達する日"])
c("C35", PS + " §8", "chiho", A4, ("A", "703_5", "3"), ["出産"])
c("C36", PS + " §9", "chiho", R8ON, ("A", "703_5", "4"), ["十八歳に達する日以後の最初の三月三十一日以前"])
c("C37", PS + " §9・M-KH §2.3", "chiho", R25, ("A", "703_5", "4"), missing=True)
c("C38", PS + " §4.3", "chiho", R8ON, ("A", "703_5_2"), ["特定受給資格者", "特定理由離職者", "百分の三十", "所得税法第二十八条第二項"])
c("C39", PS + " §10", "chiho", A4, ("A", "20_4_2", "3"), ["地方税の確定金額に百円未満の端数があるとき、又はその全額が百円未満であるときは、その端数金額又はその全額を切り捨てる。ただし、政令で定める地方税の確定金額については", "一円未満"])
c("C40", PS + " §10（課税標準額の千円未満）", "chiho", NOW, ("A", "20_4_2", "1"), ["地方税の課税標準額を計算する場合において、その額に千円未満の端数があるとき"])
c("C41", PS + " §10・H-KH H4（第6項：最初の納期限に合算）", "chiho", NOW, ("A", "20_4_2", "6"), ["納期限ごとの分割金額に千円未満の端数があるとき", "最初の納期限に係る分割金額に合算"])
c("C42", PS + " §10（第9項：特別徴収の国保税は「千円」→「百円」）", "chiho", NOW, ("A", "20_4_2", "9"), ["特別徴収の方法によつて徴収する国民健康保険税については、第六項中「千円」とあるのは、「百円」とする。"])
c("C43", PS + " §4.1", "chiho", A4, ("A", "313", "1"), ["所得割の課税標準は、前年の所得について算定した総所得金額、退職所得金額及び山林所得金額とする"])
c("C44", PS + " §12.3（第313条第8項＝純損失の繰越控除）", "chiho", NOW, ("A", "313", "8"), ["純損失の金額"])
c("C45", PS + " §12.3（第313条第9項＝純損失・雑損失）", "chiho", NOW, ("A", "313", "9"), ["純損失", "雑損失の金額"])
for a in A4:
    c("C46-" + a, PS + " §4.1（住民税の基礎控除）", "chiho", [a], ("A", "314_2", "2"), ["二千四百万円以下", "四十三万円", "二千四百五十万円以下", "二十九万円", "二千五百万円以下", "十五万円"])
for n in ["35_6", "35_7", "36", "37", "37_2", "37_3"]:
    c("C47-" + n, PS + " §4.2（原始附則で第703条の4第6項・第703条の5第1項・第706条の2第1項を読み替え）", "chiho", ["2026-04-01"], ("S", r"^\(原始附則\)$", "art", n),
      ["第七百三条の四第六項", "第七百三条の五第一項", "第七百六条の二第一項"])
c("C47b", PS + " §4.2（附則第36条は長期・短期譲渡所得）", "chiho", ["2026-04-01"], ("S", r"^\(原始附則\)$", "art", "36"), ["附則第三十四条第四項", "附則第三十五条第五項"])
c("C48", PS + " §6.2（地法附則第35条の5：15万円）", "chiho", A4, ("S", r"^\(原始附則\)$", "art", "35_5"), ["十五万円", "第七百三条の五の規定の適用については、同条第一項中"])
c("C49", PS + " §2.3（令和6年法律第47号附則第1条第5号ニ）", "chiho", ["2026-04-01"], ("S", r"令和六年.*法律第四七号$", "art", "1", "1", "5", "t:ニ"), ["第五条"])
c("C50", PS + " §2.3（同附則第1条第5号）", "chiho", ["2026-04-01"], ("S", r"令和六年.*法律第四七号$", "art", "1", "1", "5"), ["令和八年四月一日"])
c("C51", PS + " §2.3（同附則第8条）", "chiho", ["2026-04-01"], ("S", r"令和六年.*法律第四七号$", "art", "8"),
  ["第五条の規定による改正後の地方税法第七百三条の四及び第七百三条の五の規定は、令和八年度以後の年度分の国民健康保険税について適用し、令和七年度分までの国民健康保険税については、なお従前の例による。"])
c("C52", PS + " §7（令和8年法律第31号、令和8年6月5日公布、附則第1条）", "chiho", ["2027-04-01"], ("S", r"令和八年六月五日法律第三一号$", "art", "1", "1"), ["この法律は、令和九年四月一日から施行する。"])
c("C53", PS + " §7（同附則第24条）", "chiho", ["2027-04-01"], ("S", r"令和八年六月五日法律第三一号$", "art", "24"),
  ["第七条の規定（附則第一条第六号に掲げる改正規定を除く。）による改正後の地方税法第七百三条の四及び第七百三条の五の規定は、令和九年度以後の年度分の国民健康保険税について適用し、令和八年度分までの国民健康保険税については、なお従前の例による。"])
# ---- 地令
for a, vals in [("2025-04-01", ["六十六万円", "二十六万円", "十七万円"]), ("2026-04-01", ["六十七万円", "二十六万円", "十七万円", "三万円"]),
                ("2026-11-09", ["六十七万円", "二十六万円", "十七万円", "三万円"]), ("2027-04-01", ["六十七万円", "二十六万円", "十七万円", "三万円"])]:
    for i, v in enumerate(vals, 1):
        c(f"D01-{a}-{i}", PS + " §5（地令第56条の88の2）", "chiho-rei", [a], ("A", "56_88_2", str(i)), [f"政令で定める金額は、{v}とする"])
c("D02", PS + " §5（令和7年度は第4項なし）", "chiho-rei", R25, ("A", "56_88_2", "4"), missing=True)
c("D03", PS + " §6.2", "chiho-rei", R8ON, ("A", "56_89", "1"),
  ["四十三万円（納税義務者並びにその世帯に属する国民健康保険の被保険者及び特定同一世帯所属者", "給与等の収入金額が五十五万円を超える者に限る", "六十万円を超える者に限り", "百十万円を超える者に限る",
   "四十三万円に当該給与所得者等の数から一を減じた数に十万円を乗じて得た金額を加算した金額", "合計数に五十七万円を乗じて得た金額を加算した金額（次項第三号又は第四号の規定による減額を行う場合には", "合計数に三十一万円を乗じて得た金額を加算した金額）とする"])
c("D04", PS + " §6.2（令和7年度）", "chiho-rei", R25, ("A", "56_89", "1"), ["五十六万円", "三十万五千円", "四十三万円"])
c("D05", PS + " §6.2", "chiho-rei", R8ON, ("A", "56_89", "2", "2"), ["割合を乗じて得た額を基準として定めた額とすること", "十分の七", "十分の五", "十分の二"])
c("D06", PS + " §6.2", "chiho-rei", R8ON, ("A", "56_89", "2", "3"), ["十分の六", "十分の四"])
c("D07", PS + " §6.2", "chiho-rei", R8ON, ("A", "56_89", "2", "4"), ["十分の五", "十分の三"])
c("D08", PS + " §7", "chiho-rei", A4, ("A", "56_89", "3"), ["六歳に達する日以後の最初の三月三十一日以前である国民健康保険の被保険者", "十分の五を乗じて得た額を基準として定めた額"])
c("D09", PS + " §8", "chiho-rei", A4, ("A", "56_89", "4"), ["総務省令で定める場合には、出産の日"])
c("D10", PS + " §9", "chiho-rei", R8ON, ("A", "56_89", "5"), ["十八歳に達する日以後の最初の三月三十一日以前である国民健康保険の被保険者", "当該被保険者均等割額を基準として定めた額"])
c("D11", PS + " §10（地令第6条の17第2項）", "chiho-rei", A4, ("A", "6_17", "2"), ["利子等に係る道府県民税", "特定配当等に係る道府県民税", "特定株式等譲渡所得金額に係る道府県民税", "道府県たばこ税", "ゴルフ場利用税", "軽油引取税", "市町村たばこ税", "入湯税", "条例で指定するもの"], ["国民健康保険税"])
c("D12", PS + " §10（地令第6条の17には第9項がない）", "chiho-rei", A4, ("A", "6_17", "9"), missing=True)
c("D13", PS + " §6.2（地令附則第18条の8）", "chiho-rei", A4, ("S", r"^\(原始附則\)$", "art", "18_8"), ["「百十万円」とあるのは「百二十五万円」"])
c("D14", PS + " §5（令和7年政令第119号附則第9条）", "chiho-rei", A4, ("S", r"令和七年.*政令第一一九号$", "art", "9"),
  ["新令第五十六条の八十八の二第一項及び第二項並びに第五十六条の八十九第一項及び第二項（第二号に係る部分に限る。）の規定は、令和七年度以後の年度分の国民健康保険税について適用し"])
c("D15", PS + " §5（令和8年政令第83号附則第8条）", "chiho-rei", R8ON, ("S", r"令和八年.*政令第八三号$", "art", "8"),
  ["新令第五十六条の八十八の二第一項並びに第五十六条の八十九第一項及び第二項の規定は、令和八年度以後の年度分の国民健康保険税について適用し、令和七年度分までの国民健康保険税については、なお従前の例による。"])
# ---- 国年法
c("N01", PS + " §10・§11.1", "kokunen", A4, ("A", "87", "3"), ["保険料改定率を乗じて得た額（その額に五円未満の端数が生じたときは、これを切り捨て、五円以上十円未満の端数が生じたときは、これを十円に切り上げるものとする。）"])
c("N02", PS + " §11.1（第4項）", "kokunen", A4, ("A", "87", "4"), ["平成十七年度における前項の保険料改定率は、一とする"])
c("N03", PS + " §11.1（第5項）", "kokunen", A4, ("A", "87", "5", "2"), ["三乗根"])
c("N04", PS + " §11.1（第5項第1号）", "kokunen", A4, ("A", "87", "5", "1"), ["物価指数"])
c("N05", PS + " §11.1（第6項）", "kokunen", A4, ("A", "87", "6"), ["保険料改定率の改定の措置は、政令で定める"])
c("N06", PS + " §11.1（付加保険料）", "kokunen", A4, ("A", "87_2", "1"), ["国民年金基金の加入員を除く", "四百円の保険料を納付する者となることができる"])
c("N07", PS + " §11.2", "kokunen", A4, ("A", "88"), ["被保険者は、保険料を納付しなければならない。", "世帯主は、その世帯に属する被保険者の保険料を連帯して納付する義務を負う。", "配偶者の一方は、被保険者たる他方の保険料を連帯して納付する義務を負う。"])
c("N08", PS + " §11.3（第88条の2。2025-04-01 の版からある）", "kokunen", A4, ("A", "88_2"), ["出産予定月", "の前月（多胎妊娠の場合においては、三月前）から出産予定月の翌々月までの期間に係る保険料は、納付することを要しない"])
c("N09", PS + " §11.3（第88条の3は 2026-04-01 の版にない）", "kokunen", ["2025-04-01", "2026-04-01"], ("A", "88_3"), missing=True)
c("N10", PS + " §11.3（第88条の3第1項）", "kokunen", ["2026-11-09", "2027-04-01"], ("A", "88_3", "1"), ["当該出産予定日から起算して三月を経過した日の属する月から当該出産予定日から起算して十二月を経過した日", "が属する月の前月までの期間"])
c("N11", PS + " §11.3（第88条の3第2項）", "kokunen", ["2026-11-09"], ("A", "88_3", "2"), ["特別養子縁組", "養子縁組里親", "養育することとなつた日の属する月から当該子が一歳に達する日", "の翌日が属する月の前月までの期間"])
c("N12", PS + " §11.3（第88条の3第3項）", "kokunen", ["2026-11-09"], ("A", "88_3", "3"), ["子ども・子育て支援納付金により補塡する"])
c("N13", PS + " §11.3（令和6年法律第47号附則第1条第6号ロ）", "kokunen", ["2026-11-09"], ("S", r"令和六年.*法律第四七号$", "art", "1", "1", "6", "t:ロ"), ["第九条"])
c("N14", PS + " §11.3（同第6号：令和8年10月1日）", "kokunen", ["2026-11-09"], ("S", r"令和六年.*法律第四七号$", "art", "1", "1", "6"), ["令和八年十月一日"])
c("N15", PS + " §11.3（同附則第10条）", "kokunen", ["2026-11-09"], ("S", r"令和六年.*法律第四七号$", "art", "10"), ["第九条の規定による改正後の国民年金法第八十八条の三の規定は、令和八年十月以後の各月の同法第八十七条第一項に規定する保険料について適用する。"])
c("N16", PS + " §12.1（法定免除）", "kokunen", NOW, ("A", "89", "1"), ["障害基礎年金", "生活扶助", "施設に入所"])
c("N17", PS + " §12.1（全額免除のただし書・学生等の除外）", "kokunen", A4, ("A", "90", "1"), ["（以下「学生等」という。）である期間若しくは学生等であつた期間を除く", "ただし、世帯主又は配偶者のいずれかが次の各号のいずれにも該当しないときは、この限りでない。"])
c("N18", PS + " §12.3（前々年）", "kokunen", A4, ("A", "90", "1", "1"), ["一月から厚生労働省令で定める月までの月分の保険料については、前々年の所得とする。以下この章において同じ。", "その者の扶養親族等の有無及び数に応じて、政令で定める額以下であるとき"])
c("N19", PS + " §12.1（第2号）", "kokunen", A4, ("A", "90", "1", "2"), ["生活扶助以外の扶助"])
c("N20", PS + " §12.1（第3号）", "kokunen", A4, ("A", "90", "1", "3"), ["障害者、寡婦その他", "前年の所得が政令で定める額以下であるとき"])
c("N21", PS + " §12.1（第4号）", "kokunen", A4, ("A", "90", "1", "4"), ["天災その他の厚生労働省令で定める事由"])
for p, frac in [("1", "四分の三"), ("2", "半額"), ("3", "四分の一")]:
    c(f"N22-{p}", PS + " §12.1（一部免除のただし書・学生等の除外）", "kokunen", A4, ("A", "90_2", p), [f"その{frac}を納付することを要しない", "学生等である期間若しくは学生等であつた期間を除く", "ただし、世帯主又は配偶者のいずれかが次の各号のいずれにも該当しないときは、この限りでない。"])
c("N23", PS + " §10（第90条の2第6項）", "kokunen", A4, ("A", "90_2", "6"), ["残余の額に五円未満の端数が生じたときは、これを切り捨て、五円以上十円未満の端数が生じたときは、これを十円に切り上げる"])
c("N24", PS + " §12.1（学生納付特例：ただし書なし）", "kokunen", A4, ("A", "90_3", "1"), ["学生等である期間又は学生等であつた期間に限る"], ["世帯主又は配偶者", "この限りでない"])
c("N25", PS + " §12.1（扶養親族等の定義）", "kokunen", A4, ("A", "36_3", "1"), ["所得税法（昭和四十年法律第三十三号）に規定する同一生計配偶者及び扶養親族（以下「扶養親族等」という。）"])
c("N26", PS + " §12.4（平成16年改正法附則第19条第2項。令和7年度の版）", "kokunen", R25, ("S", r"平成一六年.*法律第一〇四号$", "art", "19", "2"), ["平成十八年七月から令和十二年六月までの期間"])
c("N27", PS + " §12.4", "kokunen", R8ON, ("S", r"平成一六年.*法律第一〇四号$", "art", "19", "2"),
  ["平成十八年七月から令和十七年六月までの期間", "三十歳に達する日の属する月の前月までの被保険者期間", "学生等である期間若しくは学生等であった期間を除く", "ただし、配偶者（国民年金法第五条第七項に規定する配偶者をいう。）が次の各号のいずれにも該当しないときは、この限りでない。"], ["世帯主"])
c("N28", PS + " §12.1（同一生計配偶者及び扶養親族と直接書く）", "kokunen", R8ON, ("S", r"平成一六年.*法律第一〇四号$", "art", "19", "2", "1"), ["その者の所得税法に規定する同一生計配偶者及び扶養親族の有無及び数に応じて"])
c("N29", PS + " §12.4（平成26年改正法附則第14条第1項。令和7年度の版）", "kokunen", R25, ("S", r"平成二六年.*法律第六四号$", "art", "14", "1"), ["平成二十八年七月から令和十二年六月までの期間"])
c("N30", PS + " §12.4", "kokunen", R8ON, ("S", r"平成二六年.*法律第六四号$", "art", "14", "1"),
  ["平成二十八年七月から令和十七年六月までの期間", "五十歳に達する日の属する月の前月までの被保険者期間（三十歳に達した日の属する月以後の期間に限る。", "ただし、配偶者（同法第五条第七項に規定する配偶者をいう。）が次の各号のいずれにも該当しないときは、この限りでない。"], ["世帯主"])
c("N31", PS + " §12.1", "kokunen", R8ON, ("S", r"平成二六年.*法律第六四号$", "art", "14", "1", "1"), ["同一生計配偶者及び扶養親族の有無及び数に応じて"])
# ---- 国年令・国年規・改定率令・経過措置政令
c("P01", PS + " §12.1（国年令第5条の4第1項）", "kokunen-rei", A4, ("A", "5_4", "1"), ["扶養親族（三十歳以上七十歳未満の者に限る。以下「特定年齢扶養親族」という。）", "同一生計配偶者（七十歳以上の者に限る。以下同じ。）",
  "特定扶養親族等（同法に規定する特定扶養親族又は控除対象扶養親族（十九歳未満の者に限る。）をいう。以下同じ。）"])
c("P02", PS + " §12.2", "kokunen-rei", A4, ("A", "6_7"), ["扶養親族等（特定年齢扶養親族にあつては、控除対象扶養親族に限る。）の数に一を加えた数を三十五万円に乗じて得た額に三十二万円を加算した額"])
c("P03", PS + " §12.1", "kokunen-rei", A4, ("A", "6_7_2"), ["地方税法第二百九十二条第一項第十号に規定する障害者、同項第十一号に規定する寡婦及び同項第十二号に規定するひとり親"])
c("P04", PS + " §12.1", "kokunen-rei", A4, ("A", "6_8"), ["百三十五万円"])
c("P05", PS + " §12.2", "kokunen-rei", A4, ("A", "6_8_2"), ["扶養親族等がないときは八十八万円", "一人につき三十八万円", "一人につき四十八万円", "一人につき六十三万円"])
c("P06", PS + " §12.2", "kokunen-rei", A4, ("A", "6_9"), ["第九十条の三第一項第一号", "扶養親族等がないときは百二十八万円", "一人につき三十八万円", "一人につき四十八万円", "一人につき六十三万円"])
c("P07", PS + " §12.2", "kokunen-rei", A4, ("A", "6_9_2"), ["扶養親族等がないときは百六十八万円", "一人につき三十八万円", "一人につき四十八万円", "一人につき六十三万円"])
c("P08", PS + " §12.3", "kokunen-rei", A4, ("A", "6_10"), ["地方税法第五条第二項第一号に掲げる市町村民税", "非課税所得以外の所得"])
c("P09", PS + " §12.3（全額免除の所得＝繰越控除前）", "kokunen-rei", A4, ("A", "6_11"),
  ["法第九十条第一項第一号及び第三号に規定する所得の額は", "地方税法第三百十三条第八項及び第九項の規定による控除前の同条第一項に規定する総所得金額、退職所得金額及び山林所得金額", "附則第三十三条の三第五項に規定する土地等に係る事業所得等の金額",
   "附則第三十四条第四項に規定する長期譲渡所得の金額", "附則第三十五条第五項に規定する短期譲渡所得の金額", "附則第三十五条の四第四項に規定する先物取引に係る雑所得等の金額", "特例適用利子等の額", "特例適用配当等の額", "条約適用利子等の額", "条約適用配当等の額"],
  ["上場株式等に係る配当所得等", "株式等に係る譲渡所得等"])
c("P09b", PS + " §12.3（第6条の11に控除の規定がない＝第2項がない）", "kokunen-rei", A4, ("A", "6_11", "2"), missing=True)
c("P10", PS + " §12.3（一部免除・学生）", "kokunen-rei", A4, ("A", "6_12", "1"), ["法第九十条の二第一項第一号、第二項第一号及び第三項第一号並びに法第九十条の三第一項第一号", "地方税法第三百十三条第一項に規定する総所得金額、退職所得金額及び山林所得金額"], ["控除前"])
c("P11", PS + " §12.3", "kokunen-rei", R8ON, ("A", "6_12", "2", "1"), ["雑損控除額、医療費控除額、社会保険料控除額、小規模企業共済等掛金控除額、配偶者特別控除額又は特定親族特別控除額に相当する額"])
c("P12", PS + " §12.3（令和7年度の版には特定親族特別控除額なし）", "kokunen-rei", R25, ("A", "6_12", "2", "1"), ["社会保険料控除額"], ["特定親族特別控除額"])
c("P13", PS + " §12.3", "kokunen-rei", A4, ("A", "6_12", "2", "2"), ["障害者一人につき二十七万円", "特別障害者である場合には、四十万円", "同項第八号に規定する控除を受けた者については当該控除を受けた者につき二十七万円",
  "同項第八号の二に規定する控除を受けた者については当該控除を受けた者につき三十五万円", "同項第九号に規定する控除を受けた者については当該控除を受けた者につき二十七万円"])
c("P14", PS + " §12.3（国年規第77条の2）", "kokunen-ki", NOW, ("A", "77_2"),
  ["法第九十条第一項第一号、平成十六年改正法附則第十九条第一項第一号及び第二項第一号並びに平成二十六年年金事業運営改善法附則第十四条第一項第一号に規定する厚生労働省令で定める月は、六月（法第九十条の三第一項第一号に規定する前年の所得にあつては、三月）とする。"])
c("P15", PS + " §11.1（令和7年度 1.030）", "kaiteiritsu", R25, ("A", "2", "1"), ["令和七年度における国民年金法第八十七条第三項の保険料改定率は、一・〇三〇とする"])
c("P16", PS + " §11.1（令和8年度 1.054。令和7年政令第106号の版）", "kaiteiritsu", R25, ("A", "2", "2"), ["令和八年度における国民年金法第八十七条第三項の保険料改定率は、一・〇五四とする"])
c("P17", PS + " §11.1（令和8年度 1.054。令和8年政令第75号の版）", "kaiteiritsu", R8ON, ("A", "2", "1"), ["令和八年度における国民年金法第八十七条第三項の保険料改定率は、一・〇五四とする"])
c("P18", PS + " §11.1（令和9年度 1.076）", "kaiteiritsu", R8ON, ("A", "2", "2"), ["令和九年度における国民年金法第八十七条第三項の保険料改定率は、一・〇七六とする"])
c("P19", PS + " §12.2（H26経過令第11条）", "h26kei", NOW, ("A", "11"), ["国民年金法施行令", "第六条の七の規定は、平成二十六年改正法附則第十四条第一項第一号の政令で定める額について準用する"])
c("P20", PS + " §12.3（H26経過令第14条）", "h26kei", NOW, ("A", "14"), ["第六条の十の規定"])
c("P21", PS + " §12.3（H26経過令第15条）", "h26kei", NOW, ("A", "15"), ["第六条の十一の規定"])
c("P22", PS + " §12.2（H16経過令第22条）", "h16kei", NOW, ("A", "22"), ["国民年金法施行令", "第六条の七の規定は、平成十六年改正法附則第十九条第一項第一号及び第二項第一号の政令で定める額について準用する"])
c("P23", PS + " §12.3（H16経過令第24条）", "h16kei", NOW, ("A", "24"), ["第六条の十の規定"])
c("P24", PS + " §12.3（H16経過令第25条）", "h16kei", NOW, ("A", "25"), ["第六条の十一の規定"])

# ---- 推測（KI1・KI9・KI10）の前提を原文で確かめる（推測の検証方法として書かれたものの一部を実行）
c("T01", "I-KH KI1（令和7年分の給与所得控除の最低額 65万円）", "shotoku", ["2025-12-31"], ("A", "28", "3"), ["六十五万円"])
c("T02", "I-KH KI9（令和8年分の本則の最低額）", "shotoku", ["2026-12-31"], ("A", "28", "3"), ["六十九万円"])
c("T03", "I-KH KI9（措法第29条の4：令和8年・令和9年、220万円以下は74万円）", "sochi", ["2026-12-31"], ("A", "29_4"), ["令和八年又は令和九年", "二百二十万円", "七十四万円"])
c("X01", "H-KH H11・I-KH KI10（料の軽減の判定に繰越控除を除く規定がない）", "kokuho-rei", R8ON, ("A", "29_7", "6"), ["第三百十三条第三項、第四項又は第五項"], ["第三百十三条第八項", "第三百十三条第九項", "同条第八項", "同条第九項"])
c("X02", "H-KH H11・I-KH KI10（税の軽減の判定に繰越控除を除く規定がない）", "chiho", R8ON, ("A", "703_5", "1"), ["第三百十三条第三項、第四項又は第五項"], ["第三百十三条第八項", "第三百十三条第九項", "同条第八項", "同条第九項"])

# [M-KH] §2.1 の本則の条の差（文書が書いた条の一覧。"ほか" と書いたものは、書いた条が含まれることだけを確かめる）
DOC_DIFFS = [
    ("kokuho", "2026-11-09", "2027-04-01", ["4", "9", "36", "53", "54", "54_3", "55", "65", "66_2", "72_3_2", "73", "75_3", "81_2", "82", "85_3", "113_3", "116_2", "119", "119_2", "121"], "exact"),
    ("kokuho", "2025-04-01", "2026-04-01", ["69", "70", "73", "75", "75_7", "76", "81_2", "113_3", "120_2", "121", "121_2"], "exact"),
    ("kokuho-rei", "2025-04-01", "2026-04-01", ["29_7", "29_7_2"], ("count", 7)),
    ("kokuho-rei", "2026-11-09", "2027-04-01", [], "exact"),
    ("chiho", "2026-11-09", "2027-04-01", ["703_4", "703_5"], ("count", 51)),
    ("chiho-rei", "2025-04-01", "2026-04-01", ["56_88_2", "56_89"], ("count", 61)),
    ("kokunen", "2025-04-01", "2026-04-01", ["28", "37", "102", "111", "112", "138", "143"], "subset"),
    ("kokunen", "2026-04-01", "2026-11-09", ["5", "87_2", "88_2", "88_3", "89", "103", "106", "108"], "subset"),
    ("kokunen-rei", "2025-04-01", "2026-04-01", ["5_4", "6_6", "6_12"], "subset"),
    ("kokunen-rei", "2026-04-01", "2026-11-09", ["5_4", "6_4_3", "9", "11_2"], "exact"),
    ("kaiteiritsu", "2025-04-01", "2026-04-01", ["1", "2", "4", "5", "6"], "exact"),
]
# 文書が「変わっていない」と書いた条
DOC_UNCHANGED = [
    ("kokuho", "2026-11-09", "2027-04-01", ["76", "76_2", "76_3", "77", "78", "81"]),
    ("kokuho-rei", "2026-04-01", "2026-11-09", ["29_7"]),
    ("chiho-rei", "2026-04-01", "2026-11-09", ["56_88_2", "56_89"]),
    ("chiho-rei", "2026-11-09", "2027-04-01", ["56_88_2", "56_89"]),
    ("kokunen", "2025-04-01", "2026-04-01", ["87", "87_2", "88", "88_2", "89", "90", "90_2", "90_3"]),
    ("kokunen-rei", "2025-04-01", "2026-04-01", ["6_7", "6_7_2", "6_8", "6_8_2", "6_9", "6_9_2"]),
]


# ---------------------------------------------------------------- 照合
def load_egov():
    data = {}
    for p in OUT.glob("egov_*_*.json"):
        if p.name == "egov_fetch_log.json":
            continue
        m = re.fullmatch(r"egov_(.+)_(\d{4}-\d{2}-\d{2})\.json", p.name)
        data[(m.group(1), m.group(2))] = json.loads(p.read_text(encoding="utf-8"))
    return data


def child(node, key):
    if node is None:
        return None
    ch = node.get("ch", {})
    if key.startswith("t:"):
        for v in ch.values():
            if norm(v.get("title")) == norm(key[2:]):
                return v
        return None
    return ch.get(key)


def resolve(law, path):
    kind = path[0]
    if kind == "A":
        node = law["main"].get(path[1])
        for k in path[2:]:
            node = child(node, k)
        return node, (node or {}).get("full") if node else None
    if kind == "SF":
        for s in law["suppl"]:
            if re.search(path[1], s["amend"]) and "full" in s:
                return s, s["full"]
        return None, None
    if kind == "S":
        for s in law["suppl"]:
            if not re.search(path[1], s["amend"]):
                continue
            node = (s["arts"] if path[2] == "art" else s["paras"]).get(path[3])
            for k in path[4:]:
                node = child(node, k)
            if node is not None:
                return node, node["full"]
        return None, None
    raise ValueError(path)


def kanji_to_int(s):
    D = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if all(ch in D for ch in s):
        return int("".join(str(D[ch]) for ch in s))
    total, cur = 0, 0
    for ch in s:
        if ch in D:
            cur = D[ch]
        elif ch in "十百千":
            total += (cur or 1) * {"十": 10, "百": 100, "千": 1000}[ch]
            cur = 0
    return total + cur


def lawnum_key(s):
    """「令和六年法律第四十七号」「令和6年法律第47号」→ ('令和', 6, '法律', 47)。"""
    if not s:
        return None
    s = unicodedata.normalize("NFKC", s)
    m = re.match(r"(明治|大正|昭和|平成|令和)(.+?)年(.*?)第(.+?)号", s)
    if not m:
        return s
    y = int(m.group(2)) if m.group(2).isdigit() else (1 if m.group(2) == "元" else kanji_to_int(m.group(2)))
    n = int(m.group(4)) if m.group(4).isdigit() else kanji_to_int(m.group(4))
    return (m.group(1), y, m.group(3), n)


def round_kokunen(x: F) -> int:
    """国民年金法第87条第3項・第90条の2第6項：10円未満の端数が5円未満なら切捨て、5円以上なら10円に切上げ（1円未満を含めて判定）。"""
    q, r = divmod(x, 10)
    return int(q * 10 + (10 if r >= 5 else 0))


def mode_check():
    res = {"claims": [], "revisions_vs_doc": [], "diffs": [], "unchanged": [], "revisions_list": {}, "search": [], "keyword": [],
           "web": [], "computed": [], "docs": [], "summary": {}}
    eg = load_egov()
    # 1) 条文の主張
    for cl in CLAIMS:
        for asof in cl["asofs"]:
            law = eg.get((cl["law"], asof))
            ent = {"id": cl["id"], "src": cl["src"], "law": cl["law"], "asof": asof, "path": list(cl["path"])}
            if law is None:
                ent.update(ok=None, why="未取得")
            else:
                node, text = resolve(law, cl["path"])
                if cl["missing"]:
                    ent.update(ok=node is None, why=("その版にない（文書どおり）" if node is None else "その版にある（文書と違う）"))
                elif node is None:
                    ent.update(ok=False, why="条・項・号が見つからない")
                else:
                    t = norm(text)
                    miss = [m for m in cl["must"] if norm(m) not in t]
                    bad = [m for m in cl["not"] if norm(m) in t]
                    ent.update(ok=not miss and not bad, missing_strings=miss, forbidden_found=bad, excerpt=(text or "")[:200])
            res["claims"].append(ent)
    # 国年法第87条第3項の表（平成17年度 13,580円 … 令和元年度以後 17,000円）
    for asof in A4:
        law = eg.get(("kokunen", asof))
        if law:
            node, _ = resolve(law, ("A", "87", "3"))
            rows = [[norm(x) for x in r] for r in (node or {}).get("rows", [])]
            ok = bool(rows) and rows[-1] == [norm("令和元年度以後の年度に属する月の月分"), norm("一万七千円")] and any(r == [norm("平成十七年度に属する月の月分"), norm("一万三千五百八十円")] for r in rows)
            res["claims"].append({"id": "N00-table", "src": PS + " §11.1（第87条第3項の表）", "law": "kokunen", "asof": asof, "path": ["A", "87", "3", "表"], "ok": ok,
                                  "why": f"表の行数 {len(rows)}、先頭 {rows[:1]}、最後 {rows[-1:]}"})
    # 全文の語の出現回数（擬制世帯主・旧ただし書が本文にないこと）
    for (short, asof), law in sorted(eg.items()):
        for w, n in law.get("counts", {}).items():
            res["claims"].append({"id": f"W-{short}-{w}", "src": PS + " §1.1・§13-11", "law": short, "asof": asof, "path": ["全文"], "ok": (n == 0) if w in ("擬制世帯主", "旧ただし書") else None,
                                  "why": f"全文での出現回数 {n}"})
    # 2) 版（revision_info）と文書の表
    for (short, asof), (rid, lnum, edate, status, sha16, nbytes) in DOC_REVS.items():
        law = eg.get((short, asof))
        if law is None:
            res["revisions_vs_doc"].append({"short": short, "asof": asof, "ok": None, "why": "未取得"})
            continue
        r = law["rev"]
        chk = {"law_revision_id": r.get("law_revision_id") == rid}
        if lnum:
            chk["amendment_law_num"] = lawnum_key(r.get("amendment_law_num")) == lawnum_key(lnum)
        if edate:
            chk["enforcement_date"] = r.get("amendment_enforcement_date") == edate
        if status:
            chk["status"] = r.get("current_revision_status") == status
        same_bytes = {"sha256_16_same": (r.get("sha256") or "")[:16] == sha16, "bytes_same": r.get("bytes") == nbytes} if sha16 else {}
        res["revisions_vs_doc"].append({"short": short, "asof": asof, "ok": all(chk.values()), "checks": chk, "byte_identity": same_bytes,
                                        "got": {k: r.get(k) for k in ("law_revision_id", "amendment_law_num", "amendment_enforcement_date", "current_revision_status", "sha256", "bytes", "law_title", "law_num")}})
    for short, (law_id, title, asofs, *_r) in LAWS.items():
        law = eg.get((short, asofs[-1]))
        if law:
            got = law["rev"]
            ok = got.get("law_id") == law_id and norm(got.get("law_title")) == norm(title)
            if short in DOC_LAWNUM:
                ok = ok and lawnum_key(got.get("law_num")) == lawnum_key(DOC_LAWNUM[short])
            res["revisions_vs_doc"].append({"short": short, "asof": asofs[-1], "check": "law_id・法令名・法令番号", "ok": ok,
                                            "got": {"law_id": got.get("law_id"), "law_title": got.get("law_title"), "law_num": got.get("law_num")}})
    # 3) 本則の条の差
    for short, a, b, arts, mode in DOC_DIFFS:
        la, lb = eg.get((short, a)), eg.get((short, b))
        if not la or not lb:
            res["diffs"].append({"short": short, "from": a, "to": b, "ok": None})
            continue
        ha, hb = la["hashes"], lb["hashes"]
        changed = sorted(k for k in set(ha) | set(hb) if ha.get(k) != hb.get(k))
        if mode == "exact":
            ok = set(changed) == set(arts)
        elif mode == "subset":
            ok = set(arts) <= set(changed)
        else:
            ok = set(arts) <= set(changed) and len(changed) == mode[1]
        res["diffs"].append({"short": short, "from": a, "to": b, "mode": mode, "doc": arts, "got": changed, "count": len(changed), "ok": ok,
                             "not_in_doc": sorted(set(changed) - set(arts)), "doc_not_changed": sorted(set(arts) - set(changed))})
    for short, a, b, arts in DOC_UNCHANGED:
        la, lb = eg.get((short, a)), eg.get((short, b))
        if la and lb:
            res["unchanged"].append({"short": short, "from": a, "to": b, "arts": arts,
                                     "changed": [x for x in arts if la["hashes"].get(x) != lb["hashes"].get(x)], "ok": all(la["hashes"].get(x) == lb["hashes"].get(x) for x in arts)})
    # 地法第703条の4の 2026-11-09 → 2027-04-01 の文字の差
    la, lb = eg.get(("chiho", "2026-11-09")), eg.get(("chiho", "2027-04-01"))
    if la and lb:
        ta, tb = la["main"]["703_4"]["full"], lb["main"]["703_4"]["full"]
        sm = difflib.SequenceMatcher(a=ta, b=tb, autojunk=False)
        ops = [{"op": op, "from": ta[max(0, i1 - 30):i2 + 10], "to": tb[max(0, j1 - 30):j2 + 10]} for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal"]
        res["diffs"].append({"short": "chiho", "article": "703_4", "from": "2026-11-09", "to": "2027-04-01", "char_ops": ops,
                             "ok": len(ops) == 1 and "第八十一条の二第十項第二号" in ops[0]["from"] and "第十一項第二号" in ops[0]["to"]})
    # 4) 改正履歴（公布日・未登録の確認）
    rv = json.loads((OUT / "revisions.json").read_text(encoding="utf-8")) if (OUT / "revisions.json").exists() else {"laws": {}}
    for short, ent in rv["laws"].items():
        revs = ent.get("revisions", [])
        res["revisions_list"][short] = {"count": len(revs), "latest_enforcement": max((r.get("amendment_enforcement_date") or "") for r in revs) if revs else None,
                                        "after_2026_11_09": [{k: r.get(k) for k in ("law_revision_id", "amendment_law_num", "amendment_promulgate_date", "amendment_enforcement_date", "current_revision_status")}
                                                             for r in revs if (r.get("amendment_enforcement_date") or "") > "2026-11-09"]}

    def promulgate(short, lnum):
        for r in rv["laws"].get(short, {}).get("revisions", []):
            if lawnum_key(r.get("amendment_law_num")) == lawnum_key(lnum):
                return r.get("amendment_promulgate_date"), r.get("amendment_enforcement_date")
        return None, None
    for short, lnum, prom, src in [("kokuho-rei", "令和7年政令第32号", "2025-02-07", PS + " §13-1"), ("kokuho-rei", "令和8年政令第2号", "2026-01-15", PS + " §13-1"),
                                   ("chiho", "令和8年法律第31号", "2026-06-05", PS + " §7"), ("kokuho", "令和6年法律第47号", None, PS + " §1.1"),
                                   ("kokunen", "令和7年法律第74号", None, PS + " §12.4"), ("kokuho-rei", "令和8年政令第240号", None, PS + " §5")]:
        p, e = promulgate(short, lnum)
        res["revisions_list"].setdefault("promulgation_checks", []).append({"short": short, "law_num": lnum, "doc_promulgate": prom, "got_promulgate": p, "got_enforcement": e,
                                                                          "ok": (p == prom) if prom else (p is not None), "src": src})
    for short, cutoff, src in [("kokuho-rei", "2026-08-01", PS + " §0・§13-1（令和9年度の版は未登録）"), ("chiho-rei", "2027-01-01", PS + " §13-1"),
                               ("kaiteiritsu", "2026-04-01", PS + " §11.1"), ("kokunen-rei", "2026-10-01", "M-KH §2.1")]:
        revs = rv["laws"].get(short, {}).get("revisions", [])
        later = [r for r in revs if (r.get("amendment_enforcement_date") or "") > cutoff]
        res["revisions_list"].setdefault("not_registered_checks", []).append({"short": short, "cutoff": cutoff, "later_revisions": later, "ok": (not later) if revs else None, "src": src})
    # 4b) 版の並び（revdata）：18歳への拡大がどの改正の版で入ったか、asof 2027-04-01 より後の版で国保料（税）の基準が変わるか
    def lj(name):
        q = OUT / name
        return json.loads(q.read_text(encoding="utf-8")) if q.exists() else None

    def age_of(t):
        m = re.search(r"(六|十八)歳に達する日以後の最初の三月三十一日以前", t or "")
        return m.group(1) + "歳" if m else None
    res["revchain"] = []
    for short, art, para in [("kokuho", "72_3_2", "1"), ("chiho", "703_5", "2")]:
        chain = [("2026-11-09（asof）", eg.get((short, "2026-11-09")))] + [(rid, lj(f"egovrev_{short}_{rid}.json")) for rid in REVDATA[short]]
        rows = []
        for name, law in chain:
            if law:
                node = (law["main"].get(art) or {}).get("ch", {}).get(para)
                rows.append({"version": name, "amendment_law_num": law["rev"].get("amendment_law_num"), "age": age_of((node or {}).get("full")),
                             "hash_" + art: law["hashes"].get(art), "hash_703_4": law["hashes"].get("703_4")})
        first18 = next((r for r in rows if r["age"] == "十八歳"), None)
        res["revchain"].append({"what": f"{short} 第{art}条第{para}項の対象年齢が十八歳になる最初の版", "rows": rows,
                                "first_18": first18 and first18["version"], "ok": bool(first18) and "508AC0000000031" in first18["version"]})
    rows = []
    for name, law in [("2025-04-01（asof）", eg.get(("kokunen", "2025-04-01")))] + [(rid, lj(f"egovrev_kokunen_{rid}.json")) for rid in REVDATA["kokunen"]]:
        if law:
            n19, _ = resolve(law, ("S", r"平成一六年.*法律第一〇四号$", "art", "19", "2"))
            n14, _ = resolve(law, ("S", r"平成二六年.*法律第六四号$", "art", "14", "1"))
            per = lambda n: (re.search(r"から(令和[^ま]+?年[^ま]+?月)までの期間", norm((n or {}).get("full"))) or [None, None])[1]
            rows.append({"version": name, "amendment_law_num": law["rev"].get("amendment_law_num"), "H16_19_2": per(n19), "H26_14_1": per(n14)})
    first = next((r for r in rows if r["H16_19_2"] == "令和十七年六月"), None)
    res["revchain"].append({"what": "国年法に収録された平成16年改正法附則第19条第2項・平成26年改正法附則第14条第1項の期間の末日が令和十七年六月になる最初の版", "rows": rows,
                            "first": first and first["version"], "ok": bool(first)})
    for short, base_asof, arts in [("kokuho-rei", "2027-04-01", ["27_2", "29_7", "29_7_2", "29_8"]), ("chiho-rei", "2027-04-01", ["6_17", "56_88_2", "56_89"])]:
        base = eg.get((short, base_asof))
        for rid in REVDATA[short]:
            law = lj(f"egovrev_{short}_{rid}.json")
            if base and law:
                changed = [a for a in arts if base["hashes"].get(a) != law["hashes"].get(a)]
                ops = {}
                for a in changed:
                    ta, tb = base["main"][a]["full"], law["main"][a]["full"]
                    sm = difflib.SequenceMatcher(a=ta, b=tb, autojunk=False)
                    ops[a] = [(ta[max(0, i1 - 20):i2 + 5], tb[max(0, j1 - 20):j2 + 5]) for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal"]
                res["revchain"].append({"what": f"{short} {rid} と asof {base_asof} の版の比較（{arts}）", "changed": changed, "ops": ops,
                                        "all_changed_articles": sorted(k for k in set(base["hashes"]) | set(law["hashes"]) if base["hashes"].get(k) != law["hashes"].get(k)),
                                        "ok": not [a for a in changed if a != "27_2"] and all("第二十九条の三第四項" in x[0] for x in ops.get("27_2", [])) })
    # 5) 検索
    sr = json.loads((OUT / "search.json").read_text(encoding="utf-8")) if (OUT / "search.json").exists() else {"laws": [], "keyword": []}
    for (k, v, n), got in zip(DOC_SEARCH, sr["laws"]):
        ids = {x["law_id"] for x in got.get("laws", [])}
        need = DOC_SEARCH_IDS.get(v, [])
        res["search"].append({"param": k, "value": v, "doc_count": n, "got_status": got.get("status"), "got_count": got.get("total_count"),
                              "doc_ids_missing": [x for x in need if x not in ids],
                              "ok": ((got.get("total_count") == n) if n is not None else None) if not [x for x in need if x not in ids] else False, "laws": [(x["law_id"], x["law_title"]) for x in got.get("laws", [])][:60]})
    for (kw, st, n), got in zip(DOC_KEYWORD, sr["keyword"]):
        res["keyword"].append({"keyword": kw, "doc_status": st, "doc_count": n, "got_status": got.get("status"), "got_count": got.get("total_count"),
                               "laws": got.get("laws"), "ok": got.get("status") == st and (n is None or got.get("total_count") == n)})
    # 6) Web
    wb = json.loads((OUT / "web.json").read_text(encoding="utf-8")) if (OUT / "web.json").exists() else {"pages": {}}
    for sid, (st, upd, lm, title, strings, caps) in DOC_WEB.items():
        g = wb["pages"].get(sid, {})
        t = g.get("text_norm", "")
        miss = [s for s in strings if norm(s) not in t]
        capbad = [(w, t.count(norm(w))) for w, mx in caps if t.count(norm(w)) > mx]
        chk = {"status": g.get("status") == st, "strings": not miss, "caps": not capbad}
        if upd:
            chk["page_updated"] = g.get("page_updated") == upd
        if title:
            chk["title"] = g.get("title") == title
        res["web"].append({"id": sid, "url": WEB[sid], "robots_allowed": g.get("robots_allowed"), "ok": all(chk.values()), "checks": chk, "missing": miss, "cap_violations": capbad,
                           "got": {"status": g.get("status"), "page_updated": g.get("page_updated"), "last_modified": g.get("last_modified"), "title": g.get("title"),
                                   "sha256_16": (g.get("sha256") or "")[:16]},
                           "doc_last_modified": lm, "last_modified_same": g.get("last_modified") == lm if lm else None,
                           "sha256_16_same_as_doc": (g.get("sha256") or "")[:16] == DOC_WEB_SHA.get(sid)})
    # 7) 計算（担当の round_87 とは別に、1円未満を含めて判定する実装）
    base = 17000
    rates = {"令和7年度": F(1030, 1000), "令和8年度": F(1054, 1000), "令和9年度": F(1076, 1000)}
    doc_month = {"令和7年度": 17510, "令和8年度": 17920, "令和9年度": 18290}
    doc_part = {"令和7年度": (4380, 8760, 13130), "令和8年度": (4480, 8960, 13440), "令和9年度": (4570, 9150, 13720)}
    for y, r in rates.items():
        m = round_kokunen(F(base) * r)
        parts = tuple(round_kokunen(F(m) * k) for k in (F(1, 4), F(1, 2), F(3, 4)))
        res["computed"].append({"what": f"国民年金保険料の月額と一部免除の納付額（{y}）", "src": "PS-KH §11.1・M-KH §4.2・I-KH KI5", "exact": str(F(base) * r), "monthly": m,
                                "partial_3q_half_1q": parts, "ok": m == doc_month[y] and parts == doc_part[y]})
    res["computed"].append({"what": "2年前納の例（令和8・9年度）", "src": "PS-KH §12.5", "value": 17920 * 12 + 18290 * 12, "ok": 17920 * 12 + 18290 * 12 == 434520})

    def thresholds(k, n, p5, p2):
        b7 = 430000 + max(k - 1, 0) * 100000
        return b7, b7 + n * p5, b7 + n * p2
    for what, k, n, p5, p2, exp, src in [("令和8年度 n=3 k=2", 2, 3, 310000, 570000, (530000, 1460000, 2240000), "M-KH §4.4"),
                                         ("令和8年度 n=2 k=2（KI1 の変種）", 2, 2, 310000, 570000, (530000, 1150000, 1670000), "I-KH KI1"),
                                         ("令和8年度 n=2 k=1（KI7）", 1, 2, 310000, 570000, (430000, 1050000, 1570000), "I-KH KI7"),
                                         ("令和8年度 n=2 k=1（KI1：k=1 なら 7割は 43万円）", 1, 2, 310000, 570000, (430000, 1050000, 1570000), "I-KH KI1")]:
        got = thresholds(k, n, p5, p2)
        res["computed"].append({"what": "軽減判定の基準額 " + what, "src": src, "got": got, "doc": exp, "ok": got == exp})
    for d, exp in [(0, (670000, None, None, None)), (1, (1020000, 1260000, 1660000, 2060000))]:
        got = ((d + 1) * 350000 + 320000, 880000 + d * 380000, 1280000 + d * 380000, 1680000 + d * 380000)
        ok = got[0] == exp[0] and all(e is None or g == e for g, e in zip(got, exp))
        res["computed"].append({"what": f"国民年金の免除・猶予の所得基準（扶養親族等 {d} 人、一般の控除対象扶養親族）", "src": "M-KH §4.4・I-KH KI6", "got": got, "doc": exp, "ok": ok})
    res["computed"].append({"what": "賦課限度額の合計（令和7年度 66+26+17、令和8年度 67+26+17+3）", "src": "PS-KH §5・H-KH H9", "got": (660000 + 260000 + 170000, 670000 + 260000 + 170000 + 30000),
                            "ok": (660000 + 260000 + 170000, 670000 + 260000 + 170000 + 30000) == (1090000, 1130000)})
    # 年齢の区切り（KI4）：X歳に達する日（誕生日の前日）以後の最初の3月31日
    import datetime as dt

    def first_0331_after_reaching(birth, age):
        try:
            bd = birth.replace(year=birth.year + age)
        except ValueError:
            bd = dt.date(birth.year + age, 3, 1)
        reach = bd - dt.timedelta(days=1)
        y = reach.year if reach <= dt.date(reach.year, 3, 31) else reach.year + 1
        return dt.date(y, 3, 31)
    cases = []
    for b in [dt.date(2008, 4, 1), dt.date(2008, 4, 2), dt.date(2009, 4, 1), dt.date(2009, 4, 2)]:
        last = first_0331_after_reaching(b, 18)
        cases.append({"birth": str(b), "first_0331_after_18": str(last), "under18_whole_R8": last >= dt.date(2027, 3, 31)})
    ok = [x["under18_whole_R8"] for x in cases] == [False, True, True, True]
    res["computed"].append({"what": "KI4：令和8年度に18歳未満被保険者として扱われる生年月日（2008-04-02〜2009-04-01 生まれは年度を通じて対象、2008-04-01 生まれは対象外）",
                            "src": "I-KH KI4", "cases": cases, "ok": ok})
    # 8) 文書の参照と規約
    docs = {
        "PS": ROOT / "docs/public-sources/20261109_round2_kokuho-premium-structure.md",
        "M": ROOT / "docs/measurements/20261109_round2_kokuho-law-fetch.md",
        "H": ROOT / "docs/hypotheses/20261109_round2_kokuho-core-vs-injected.md",
        "I": ROOT / "docs/inferences/20261109_round2_kokuho-examples.md",
    }
    txt = {k: v.read_text(encoding="utf-8") for k, v in docs.items()}
    res["docs"].append({"what": "仮説の文書に外部 URL がない", "ok": not re.search(r"https?://", txt["H"]), "found": re.findall(r"https?://\S+", txt["H"])})
    res["docs"].append({"what": "推測の文書に外部 URL がない（参照は仮説経由）", "ok": not re.search(r"https?://", txt["I"]), "found": re.findall(r"https?://\S+", txt["I"])})
    res["docs"].append({"what": "推測の文書が仮説の文書を参照している", "ok": "docs/hypotheses/20261109_round2_kokuho-core-vs-injected.md" in txt["I"]})
    res["docs"].append({"what": "推測の各節に検証の方法がある", "ok": all("検証の方法" in sec for sec in re.split(r"\n## KI\d+", txt["I"])[1:]),
                        "n_sections": len(re.findall(r"\n## KI\d+", txt["I"]))})
    res["docs"].append({"what": "実測の文書がスクリプトと結果のパスを書いている", "ok": all(f"scripts/R2X_kokuho_{n}.py" in txt["M"] for n in ["lawsearch", "egov", "keyword", "web", "values"])})
    for k, p in docs.items():
        refs = sorted(set(re.findall(r"`(docs/[^`]+\.md)`", txt[k])))
        res["docs"].append({"what": f"{k} の参照先の文書が存在する", "ok": all((ROOT / r).exists() for r in refs), "refs": refs, "missing": [r for r in refs if not (ROOT / r).exists()]})
        refs2 = sorted(set(re.findall(r"`(scripts/[^`<>*]+)`", txt[k])))
        res["docs"].append({"what": f"{k} の参照先のスクリプト・結果が存在する", "ok": all((ROOT / r.rstrip('/')).exists() for r in refs2), "refs": refs2,
                            "missing": [r for r in refs2 if not (ROOT / r.rstrip('/')).exists()]})
    H_refs = re.findall(r"`(docs/(?:hypotheses|inferences)/[^`]+)`", txt["H"])
    res["docs"].append({"what": "仮説の文書が根拠として参照するのは実測・公開資料だけ（仮説・推測の文書への参照の一覧）", "ok": None, "refs_to_hypotheses_or_inferences": H_refs})
    # 個人の情報（家族の職業・住む市町村）の語
    pref = "北海道|青森|岩手|宮城|秋田|山形|福島|茨城|栃木|群馬|埼玉|千葉|東京|神奈川|新潟|富山|石川|福井|山梨|長野|岐阜|静岡|愛知|三重|滋賀|京都|大阪|兵庫|奈良|和歌山|鳥取|島根|岡山|広島|山口|徳島|香川|愛媛|高知|福岡|佐賀|長崎|熊本|大分|宮崎|鹿児島|沖縄"
    cities = "横浜|川崎|相模原|さいたま|名古屋|神戸|札幌|仙台|千葉市|新潟市|静岡市|浜松|堺|岡山市|広島市|北九州|福岡市|熊本市|世田谷|練馬|杉並"
    jobs = "国家公務員|地方公務員|自衛官|防衛省|単身赴任|教員|会社員"
    for k in docs:
        hits = [(m.group(0), txt[k][max(0, m.start() - 30):m.end() + 30].replace("\n", " ")) for m in re.finditer(f"{pref}|{cities}|{jobs}", txt[k])]
        res["docs"].append({"what": f"{k} の個人の情報になりうる語（都道府県・市の名前・職業）", "ok": None, "hits": hits})
    # 集計
    allc = [x for x in res["claims"] if x.get("ok") is not None]
    res["summary"] = {
        "claims_total": len(res["claims"]), "claims_ok": sum(1 for x in allc if x["ok"]), "claims_ng": [x["id"] + "@" + x["asof"] for x in allc if not x["ok"]],
        "revisions_ng": [f"{x['short']}@{x['asof']}" for x in res["revisions_vs_doc"] if x.get("ok") is False],
        "diffs_ng": [f"{x['short']} {x.get('from')}→{x.get('to')}" for x in res["diffs"] if x.get("ok") is False],
        "unchanged_ng": [f"{x['short']} {x['from']}→{x['to']} {x['changed']}" for x in res["unchanged"] if not x["ok"]],
        "search_ng": [f"{x['param']}={x['value']} doc={x['doc_count']} got={x['got_count']}" for x in res["search"] if x.get("ok") is False],
        "keyword_ng": [f"{x['keyword']} doc={x['doc_status']}/{x['doc_count']} got={x['got_status']}/{x['got_count']}" for x in res["keyword"] if not x["ok"]],
        "web_ng": [x["id"] for x in res["web"] if not x["ok"]],
        "computed_ng": [x["what"] for x in res["computed"] if not x["ok"]],
        "docs_ng": [x["what"] for x in res["docs"] if x.get("ok") is False],
        "promulgation_ng": [x for x in res["revisions_list"].get("promulgation_checks", []) if not x["ok"]],
        "not_registered_ng": [x["short"] + " " + str([r["law_revision_id"] for r in x["later_revisions"]]) for x in res["revisions_list"].get("not_registered_checks", []) if x["ok"] is False],
        "revchain_ng": [x["what"] for x in res["revchain"] if not x["ok"]],
    }
    res["summary"]["distinct_items"] = {
        "claim_ids": len({x["id"] for x in res["claims"]}), "revisions_vs_doc": len(res["revisions_vs_doc"]), "diffs": len(res["diffs"]), "unchanged": len(res["unchanged"]),
        "revchain": len(res["revchain"]), "search": len(res["search"]), "keyword": len(res["keyword"]), "web": len(res["web"]), "computed": len(res["computed"]),
        "docs": len(res["docs"]), "promulgation": len(res["revisions_list"].get("promulgation_checks", [])), "not_registered": len(res["revisions_list"].get("not_registered_checks", []))}
    res["summary"]["distinct_items"]["total"] = sum(res["summary"]["distinct_items"].values())
    (OUT / "check.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    L = ["# R2X_kokuho_verify check（scripts/R2X_kokuho_verify.py check の出力）", "", "## 集計", "```", json.dumps(res["summary"], ensure_ascii=False, indent=1), "```", "", "## 条文の主張"]
    for x in res["claims"]:
        L.append(f"- {x['id']} {x['law']}@{x['asof']} {x['path']} ok={x.get('ok')} {x.get('why', '')} {('不足:' + str(x['missing_strings'])) if x.get('missing_strings') else ''} {('禁止語あり:' + str(x['forbidden_found'])) if x.get('forbidden_found') else ''}  [{x['src']}]")
    for sec in ["revisions_vs_doc", "diffs", "unchanged", "revchain", "search", "keyword", "web", "computed", "docs"]:
        L += ["", f"## {sec}"]
        for x in res[sec]:
            L.append("- " + json.dumps(x, ensure_ascii=False)[:1500])
    L += ["", "## revisions_list", "```", json.dumps(res["revisions_list"], ensure_ascii=False, indent=1)[:20000], "```"]
    (OUT / "check.md").write_text("\n".join(L), encoding="utf-8")
    print(json.dumps(res["summary"], ensure_ascii=False, indent=1))


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    if mode == "egov":
        mode_egov(sys.argv[2:] or None)
        return
    {"revs": mode_revs, "revdata": mode_revdata, "search": mode_search, "web": mode_web, "check": mode_check}[mode]()


if __name__ == "__main__":
    main()

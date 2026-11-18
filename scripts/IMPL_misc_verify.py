"""IMPL_misc_verify: トピック misc（年齢の判定・親族の範囲・扶養の所属・源泉徴収の区分）の文書を、独立に一次情報へ当たり直して検証する。

実行（Windows。pyenv の python.bat シムは使わない）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_misc_verify.py egov
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_misc_verify.py egov2
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_misc_verify.py hash
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_misc_verify.py web
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_misc_verify.py age

- egov: e-Gov 法令API v2 で所得税法・同施行令（2025-12-31／2026-11-09／2026-12-31）、所得税法施行規則・地方税法・
  地方税法施行令・民法・年齢計算ニ関スル法律（2026-11-09）、租税特別措置法（2025-12-31／2026-12-31）を取得し、
  (1) 返った版（law_revision_id・改正法令・施行日・状態）、(2) 文書に引用された条文の断片が、指定した版の指定した条・項に
  そのまま現れるか、(3) 所令218〜220 の版の間の同一性、(4) 本則の全文の走査（「民法」「居住者として…適用を受けている場合」）、
  (5) 改正法の附則（施行期日・適用年分）を確かめる。
  e-Gov の使い方は scripts/R1_egov_articles.py・scripts/R4_fetch_laws.py のコードを写した（import しない）。
- egov2: 所得税法施行令の改正政令の附則（第217条の2・第217条の3 の適用年分）と、所得税法の条の版の間の同一性を確かめる。
- hash: 担当の実測 §3.2 の SHA-256（所令218〜220）を、担当の出力テキストから再現する（ネットワークに接続しない）。
- web: 国税庁・裁判所の HTML を取得し、文書に引用された文言と基準日の表示が本文に現れるかを確かめる。PDF は取得して
  SHA-256 を記録するだけ（中身は Read ツールで人が読む）。
- age: 年齢の判定を、担当のスクリプトとは別の書き方（誕生日の前日の終了時に加算＝「応当日の前日」の列挙）で実装し、
  国税庁の生年月日の範囲を年齢の境目から**導いて**、文書の表と突き合わせる。ネットワークに接続しない。

- ダウンロードしたもの（JSON・HTML・PDF）は信頼できないデータ。実行ごと・種類ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_IMPL_misc_verify_<kind>/ に置き、その中では何も実行しない。
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。個人の情報は送らない。官報は取得しない。
- 標準ライブラリのみ。出力は scripts/results/IMPL_misc_verify/。
"""
import calendar
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
OUT = ROOT / "scripts" / "results" / "IMPL_misc_verify"
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
SLEEP = 1.5
PS_DOC = ROOT / "docs" / "public-sources" / "20261109_impl-prep_misc-age-kinship-attribution.md"


# ---------------------------------------------------------------- 共通

def get(url, accept="application/json"):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            body, st, hdr = r.read(), r.status, dict(r.headers.items())
    except urllib.error.HTTPError as e:
        body, st, hdr = e.read(), e.code, dict(e.headers.items())
    time.sleep(SLEEP)
    return st, body, hdr


def norm(s):
    """比較用の正規化：NFKC、空白の除去、「〜～」の統一。"""
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s+", "", s)
    return s.replace("〜", "~").replace("～", "~")


def frags_in_order(quote, text):
    """quote を「…」で区切った断片が、text の中に順に現れるか。現れない最初の断片を返す（全部あれば None）。"""
    t = norm(text)
    pos = 0
    for f in [x for x in re.split(r"…+|\.\.\.", quote) if norm(x)]:
        nf = norm(f)
        i = t.find(nf, pos)
        if i < 0:
            return f
        pos = i + len(nf)
    return None


# ---------------------------------------------------------------- e-Gov

def flat(n, skip_num=True):
    """ノードを平文にする。ルビの読み（Rt）と、skip_num のときは番号・見出し（*Num, *Title, *Caption）を落とす。"""
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
            walk(c, fn, path + (n.get("tag"),))


def main_articles(root):
    arts = []

    def collect(n, path):
        if n.get("tag") == "Article" and "SupplProvision" not in path:
            arts.append(n)
    walk(root, collect)
    return {a["attr"].get("Num"): a for a in arts}


def caption(a):
    for c in a.get("children", []):
        if isinstance(c, dict) and c.get("tag") == "ArticleCaption":
            return flat(c, skip_num=False)
    return ""


def locate(arts, art, para=None, item=None, sub=None):
    a = arts.get(art)
    if a is None:
        return None
    if para is None:
        return a
    ps = [p for p in kids(a, "Paragraph") if p.get("attr", {}).get("Num") == str(para)]
    if not ps:
        return None
    node = ps[0]
    if item is None:
        return node
    its = [i for i in kids(node, "Item") if i.get("attr", {}).get("Num") == str(item)]
    if not its:
        return None
    node = its[0]
    if sub is None:
        return node
    ss = [s for s in kids(node, "Subitem1") if s.get("attr", {}).get("Num") == str(sub)]
    return ss[0] if ss else None


def lines_of(a):
    """条を「項・号・イロハ」の単位の行に分ける（走査用）。"""
    out = []
    block = {"Paragraph", "Item"} | {f"Subitem{i}" for i in range(1, 11)}

    def rec(n):
        if not isinstance(n, dict):
            return
        tag = n.get("tag", "")
        if tag in block:
            own = "".join(flat(c) for c in n.get("children", [])
                          if isinstance(c, dict) and c.get("tag", "").endswith("Sentence"))
            out.append(own)
            for c in n.get("children", []):
                if isinstance(c, dict) and not c.get("tag", "").endswith("Sentence"):
                    rec(c)
        else:
            for c in n.get("children", []):
                rec(c)
    rec(a)
    return out


LAWS = {
    # 略称: (law_id, [asof...], omit_amendment_suppl_provision)
    "shotoku": ("340AC0000000033", ["2025-12-31", "2026-11-09", "2026-12-31"], True),
    "shotoku_suppl": ("340AC0000000033", ["2026-12-31"], False),  # 改正法の附則を読むため
    "shotoku-rei": ("340CO0000000096", ["2025-12-31", "2026-11-09", "2026-12-31"], True),
    "shotoku-ki": ("340M50000040011", ["2026-11-09"], True),
    "chiho": ("325AC0000000226", ["2026-11-09"], True),
    "chiho-rei": ("325CO0000000245", ["2026-11-09"], True),
    "minpo": ("129AC0000000089", ["2026-11-09"], True),
    "nenrei": ("135AC1000000050", ["2026-11-09"], True),
    "sochi": ("332AC0000000026", ["2025-12-31", "2026-12-31"], True),
}

# 文書（public-sources・measurements・hypotheses・inferences）に引用・記載された条文の断片。
# (ID, 略称, [asof...], 条, 項, 号, イロハ, 断片（「…」で区切る）)
LAW_QUOTES = [
    ("PS1.1-85-3", "shotoku", ["2025-12-31", "2026-12-31"], "85", 3, None, None,
     "…特定扶養親族、老人扶養親族若しくはその他の控除対象扶養親族若しくはその他の扶養親族若しくは前条第一項に規定する特定親族…に該当するかどうかの判定は、その年十二月三十一日の現況による。ただし、その判定に係る者がその当時既に死亡している場合は、当該死亡の時の現況による。"),
    ("PS2.1-2-34", "shotoku", ["2025-12-31", "2026-12-31"], "2", 1, "34", None,
     "居住者の親族（その居住者の配偶者を除く。）並びに…里親に委託された児童及び…養護受託者に委託された老人でその居住者と生計を一にするもの…"),
    ("PS4.1-2-34-58", "shotoku", ["2025-12-31"], "2", 1, "34", None, "…のうち、合計所得金額が五十八万円以下である者"),
    ("PS4.1-2-34-62", "shotoku", ["2026-12-31"], "2", 1, "34", None, "…のうち、合計所得金額が六十二万円以下である者"),
    # 所令218〜220（3つの版で同文と書かれている）
    ("PS3.2-218-1", "shotoku-rei", ["2025-12-31", "2026-11-09", "2026-12-31"], "218", 1, None, None,
     "法第八十五条第四項（扶養親族等の判定の時期等）に規定する場合において、同項に規定する配偶者が同項に規定する同一生計配偶者又は扶養親族のいずれに該当するかは、同項に規定する居住者又は他の居住者の提出するその年分の法第百十二条第一項（予定納税額の減額の承認の申請手続）に規定する申請書、確定申告書又は法第百九十四条第一項若しくは第三項（給与所得者の扶養控除等申告書）、第百九十五条第一項若しくは第三項（従たる給与についての扶養控除等申告書）、第百九十五条の二第一項（給与所得者の配偶者控除等申告書）若しくは第二百三条の六第一項（公的年金等の受給者の扶養親族等申告書）の規定による申告書（法第百九十四条第二項、第百九十五条第二項又は第二百三条の六第二項の規定により提出した法第百九十四条第一項、第百九十五条第一項又は第二百三条の六第一項の申告書を含む。以下この条において「申告書等」という。）に記載されたところによる。ただし、本文又は次項の規定により、当該配偶者が当該同一生計配偶者又は扶養親族のいずれかとされた後において、当該居住者又は他の居住者が提出する申告書等にこれと異なる記載をすることにより、その区分を変更することを妨げない。"),
    ("PS3.2-218-2", "shotoku-rei", ["2025-12-31", "2026-11-09", "2026-12-31"], "218", 2, None, None,
     "前項の場合において、同項の居住者又は他の居住者が同一人をそれぞれ自己の同一生計配偶者又は扶養親族として申告書等に記載したとき、その他同項の規定により同一生計配偶者又は扶養親族のいずれに該当するかを定められないときは、その夫又は妻である居住者の同一生計配偶者とする。"),
    ("PS3.2-218_2-1", "shotoku-rei", ["2025-12-31", "2026-11-09", "2026-12-31"], "218_2", 1, None, None,
     "法第八十五条第五項…に規定する場合において、同項に規定する居住者の配偶者が同項に規定する生計を一にする配偶者（以下この条において「特別控除対象配偶者」という。）又は特定親族のいずれに該当するかは、同項に規定する居住者又は他の居住者の提出するその年分の前条第一項に規定する申告書等又は法第百九十五条の三第一項（給与所得者の特定親族特別控除申告書）の規定による申告書（以下この条において「申告書等」という。）に記載されたところによる。ただし、…異なる記載をすることにより、その区分を変更することを妨げない。"),
    ("PS3.2-218_2-2", "shotoku-rei", ["2025-12-31", "2026-11-09", "2026-12-31"], "218_2", 2, None, None,
     "前項の場合において、同項の居住者又は他の居住者が同一人をそれぞれ自己の特別控除対象配偶者又は特定親族として申告書等に記載したとき、その他同項の規定により特別控除対象配偶者又は特定親族のいずれに該当するかを定められないときは、その夫又は妻である居住者の特別控除対象配偶者とする。"),
    ("PS3.2-219-1", "shotoku-rei", ["2025-12-31", "2026-11-09", "2026-12-31"], "219", 1, None, None,
     "法第八十五条第六項（扶養親族等の判定の時期等）に規定する場合において、同項に規定する二以上の居住者の扶養親族又は特定親族に該当する者をいずれの居住者の扶養親族又は特定親族とするかは、これらの居住者の提出するその年分の第二百十八条第一項（二以上の居住者がある場合の同一生計配偶者の所属）に規定する申告書等（法第百九十五条の二第一項（給与所得者の配偶者控除等申告書）の規定による申告書を除く。）又は法第百九十五条の三第一項（給与所得者の特定親族特別控除申告書）の規定による申告書（以下この条において「申告書等」という。）に記載されたところによる。ただし、本文又は次項の規定により、その扶養親族又は特定親族がいずれか一の居住者の扶養親族又は特定親族に該当するものとされた後において、これらの居住者が提出する申告書等にこれと異なる記載をすることにより、他のいずれか一の居住者の扶養親族又は特定親族とすることを妨げない。"),
    ("PS3.2-219-2", "shotoku-rei", ["2025-12-31", "2026-11-09", "2026-12-31"], "219", 2, None, None,
     "前項の場合において、二以上の居住者が同一人をそれぞれ自己の扶養親族又は特定親族として申告書等に記載したとき、その他同項の規定によりいずれの居住者の扶養親族又は特定親族とするかを定められないときは、次に定めるところによる。"),
    ("PS3.2-219-2-1", "shotoku-rei", ["2025-12-31", "2026-11-09", "2026-12-31"], "219", 2, "1", None,
     "その年において既に一の居住者が申告書等の記載によりその扶養親族又は特定親族としている場合には、当該親族は、当該居住者の扶養親族又は特定親族とする。"),
    ("PS3.2-219-2-2", "shotoku-rei", ["2025-12-31", "2026-11-09", "2026-12-31"], "219", 2, "2", None,
     "前号の規定によつてもいずれの居住者の扶養親族又は特定親族とするかが定められない扶養親族又は特定親族は、居住者のうち総所得金額、退職所得金額及び山林所得金額の合計額又は当該親族がいずれの居住者の扶養親族若しくは特定親族とするかを判定すべき時における当該合計額の見積額が最も大きい居住者の扶養親族又は特定親族とする。"),
    ("PS3.2-220-1", "shotoku-rei", ["2025-12-31", "2026-11-09", "2026-12-31"], "220", 1, None, None,
     "法第八十五条第七項（扶養親族等の判定の時期等）に規定する場合において、同項の居住者の同一生計配偶者又は法第八十三条の二第一項（配偶者特別控除）に規定する生計を一にする配偶者に該当するものは、その死亡した配偶者又は再婚した配偶者のうち一人に限るものとする。"),
    ("PS3.2-220-2", "shotoku-rei", ["2025-12-31", "2026-11-09", "2026-12-31"], "220", 2, None, None,
     "前項の居住者の死亡した配偶者又は再婚した配偶者のうちこれらの配偶者と生計を一にする他の居住者の扶養親族にも該当するものは、同項の居住者がこれらの配偶者のうちの一人を同項の規定により同一生計配偶者としたときは、その同一生計配偶者とされた者以外の者は当該他の居住者の扶養親族には該当しないものとし、同項の居住者がこれらの配偶者のいずれをも同一生計配偶者としないときは、これらの配偶者のうちの一人に限り、当該他の居住者の扶養親族に該当するものとする。"),
    ("PS3.2-220-3", "shotoku-rei", ["2025-12-31", "2026-11-09", "2026-12-31"], "220", 3, None, None,
     "前項の場合において、第二百十八条第一項（二以上の居住者がある場合の同一生計配偶者の所属）の規定により、前項の配偶者の死亡の日までに提出された同条第一項に規定する申告書等（その年において当該申告書等を提出すべき期限が到来していないときは、その前年分の所得税につき最後に提出した当該申告書等）の記載に従つて当該死亡した配偶者が当該他の居住者の扶養親族とされていた場合には、当該死亡した配偶者は、当該他の居住者の扶養親族に該当するものとし、第一項の再婚した配偶者は、前項の規定にかかわらず、第一項の居住者の同一生計配偶者又はこれらの居住者以外の生計を一にする居住者の扶養親族に該当するものとする。"),
    ("PS3.2-85-7", "shotoku", ["2025-12-31", "2026-12-31"], "85", 7, None, None,
     "年の中途において居住者の配偶者が死亡し、その年中にその居住者が再婚した場合におけるその死亡し、又は再婚した配偶者に係る同一生計配偶者及び第八十三条の二第一項に規定する生計を一にする配偶者並びに扶養親族及び特定親族の範囲の特例については、政令で定める。"),
    ("PS4.1-84-1", "shotoku", ["2025-12-31", "2026-12-31"], "84", 1, None, None,
     "居住者が控除対象扶養親族を有する場合には、その居住者のその年分の総所得金額、退職所得金額又は山林所得金額から、その控除対象扶養親族一人につき三十八万円（その者が特定扶養親族である場合には六十三万円とし、その者が老人扶養親族である場合には四十八万円とする。）を控除する。"),
    ("PS4.1-84-2", "shotoku", ["2025-12-31", "2026-12-31"], "84", 2, None, None, "前項の規定による控除は、扶養控除という。"),
    ("PS4.2-83_2-2", "shotoku", ["2025-12-31", "2026-12-31"], "83_2", 2, None, None,
     "前項の規定は、同項に規定する生計を一にする配偶者が、次に掲げる場合に該当するときは、適用しない。"),
    ("PS4.2-83_2-2-1", "shotoku", ["2025-12-31", "2026-12-31"], "83_2", 2, "1", None, "当該配偶者が前項に規定する居住者として同項の規定の適用を受けている場合"),
    ("PS4.2-83_2-2-2", "shotoku", ["2025-12-31", "2026-12-31"], "83_2", 2, "2", None,
     "当該配偶者が、給与所得者の扶養控除等申告書又は従たる給与についての扶養控除等申告書に記載された源泉控除対象配偶者がある居住者として第百八十五条第一項第一号若しくは第二号（賞与以外の給与等に係る徴収税額）又は第百八十六条第一項第一号若しくは第二項第一号（賞与に係る徴収税額）の規定の適用を受けている場合（当該配偶者が、その年分の所得税につき、第百九十条（年末調整）の規定の適用を受けた者である場合又は確定申告書の提出をし、若しくは決定を受けた者である場合を除く。）"),
    ("PS4.2-84_2-2", "shotoku", ["2025-12-31", "2026-12-31"], "84_2", 2, None, None, "前項の規定は、次に掲げる場合に該当するときは、適用しない。"),
    ("PS4.2-84_2-2-1", "shotoku", ["2025-12-31", "2026-12-31"], "84_2", 2, "1", None, "特定親族が前項に規定する居住者として同項の規定の適用を受けている場合"),
    ("PS4.2-84_2-2-2", "shotoku", ["2025-12-31", "2026-12-31"], "84_2", 2, "2", None,
     "特定親族が、給与所得者の扶養控除等申告書又は従たる給与についての扶養控除等申告書に記載された源泉控除対象親族（特定親族に限る。）がある居住者として第百八十五条第一項第一号若しくは第二号（賞与以外の給与等に係る徴収税額）又は第百八十六条第一項第一号若しくは第二項第一号（賞与に係る徴収税額）の規定の適用を受けている場合（当該居住者としてこれらの規定の適用を受けている特定親族が、その年分の所得税につき、第百九十条（年末調整）の規定の適用を受けた者である場合又は確定申告書の提出をし、若しくは決定を受けた者である場合を除く。）"),
    ("PS4.2-84_2-2-3", "shotoku", ["2025-12-31", "2026-12-31"], "84_2", 2, "3", None, "前二号に掲げる場合のほか、政令で定める場合"),
    ("PS4.2-rei217_2", "shotoku-rei", ["2026-11-09", "2026-12-31"], "217_2", 1, None, None,
     "法第八十四条の二第二項第三号（特定親族特別控除）に規定する政令で定める場合は、次に掲げる場合とする。"),
    ("PS4.2-rei217_2-1", "shotoku-rei", ["2026-11-09", "2026-12-31"], "217_2", 1, "1", None,
     "他の者が、法第八十四条の二第一項に規定する居住者を、当該他の者の提出した法第百九十四条第八項（給与所得者の扶養控除等申告書）に規定する給与所得者の扶養控除等申告書又は法第百九十五条第六項（従たる給与についての扶養控除等申告書）に規定する従たる給与についての扶養控除等申告書に記載された源泉控除対象親族（法第八十四条の二第一項に規定する特定親族（…）に限る。次号において同じ。）として、法第百八十五条第一項第一号若しくは第二号（賞与以外の給与等に係る徴収税額）又は第百八十六条第一項第一号若しくは第二項第一号（賞与に係る徴収税額）の規定の適用を受けている場合（当該他の者が、その年分の所得税につき、法第百九十条（年末調整）の規定の適用を受けた者である場合又は確定申告書の提出をし、若しくは決定を受けた者である場合を除く。）"),
    ("PS4.2-rei217_2-2", "shotoku-rei", ["2026-11-09", "2026-12-31"], "217_2", 1, "2", None,
     "他の者が、法第八十四条の二第一項に規定する居住者を、当該他の者の提出した法第二百三条の六第八項（公的年金等の受給者の扶養親族等申告書）に規定する公的年金等の受給者の扶養親族等申告書に記載された源泉控除対象親族として、法第二百三条の三第一号から第三号まで（徴収税額）の規定の適用を受けている場合（当該他の者がその年分の所得税につき確定申告書の提出をし、又は決定を受けた者である場合を除く。）"),
    # 「所令@2025-12-31 では第217条の3 に同じ本文」の確認
    ("PS4.2-rei217_3-1@2025", "shotoku-rei", ["2025-12-31"], "217_3", 1, "1", None,
     "他の者が、法第八十四条の二第一項に規定する居住者を、当該他の者の提出した法第百九十四条第八項（給与所得者の扶養控除等申告書）に規定する給与所得者の扶養控除等申告書又は法第百九十五条第六項（従たる給与についての扶養控除等申告書）に規定する従たる給与についての扶養控除等申告書に記載された源泉控除対象親族（法第八十四条の二第一項に規定する特定親族（…）に限る。次号において同じ。）として、法第百八十五条第一項第一号若しくは第二号（賞与以外の給与等に係る徴収税額）又は第百八十六条第一項第一号若しくは第二項第一号（賞与に係る徴収税額）の規定の適用を受けている場合（当該他の者が、その年分の所得税につき、法第百九十条（年末調整）の規定の適用を受けた者である場合又は確定申告書の提出をし、若しくは決定を受けた者である場合を除く。）"),
    ("PS4.3-rei11_2-2@2025", "shotoku-rei", ["2025-12-31"], "11_2", 2, None, None,
     "法第二条第一項第三十一号イに規定する政令で定める子は、その年分の総所得金額、退職所得金額及び山林所得金額の合計額が五十八万円以下の子（他の者の同一生計配偶者又は扶養親族とされている者を除く。）とする。"),
    ("PS4.3-rei11_2-2@2026", "shotoku-rei", ["2026-12-31"], "11_2", 2, None, None, "…六十二万円以下の子（他の者の同一生計配偶者又は扶養親族とされている者を除く。）とする。"),
    ("PS4.3-chirei7_2_2-2", "chiho-rei", ["2026-11-09"], "7_2_2", 2, None, None,
     "…前年の…合計額が五十八万円以下の子（他の者の同一生計配偶者又は扶養親族とされている者を除く。）とする。"),
    ("PS4.3-chirei46_2_2-2", "chiho-rei", ["2026-11-09"], "46_2_2", 2, None, None,
     "…前年の…合計額が五十八万円以下の子（他の者の同一生計配偶者又は扶養親族とされている者を除く。）とする。"),
    ("PS4.3-rei205-1", "shotoku-rei", ["2026-12-31"], "205", None, None, None,
     "その親族が同一生計配偶者又は扶養親族に該当する場合には、その者を自己の同一生計配偶者又は扶養親族としている居住者の親族とする。"),
    ("PS4.3-2-30-i-1", "shotoku", ["2025-12-31", "2026-12-31"], "2", 1, "30", None, "扶養親族を有すること。"),
    ("PS3.4-chirei46_3-2", "chiho-rei", ["2026-11-09"], "46_3", 2, None, None,
     "…二以上の納税義務者につき同一人が同一生計配偶者又は扶養親族として同項の申告書、給与支払報告書若しくは公的年金等支払報告書又は申請書に記載されたとき、その他同項の規定により同一生計配偶者又は扶養親族のいずれに該当するかを定められないときは、その夫又は妻である市町村民税の納税義務者の同一生計配偶者とする。"),
    ("PS1.2-chirei47_3", "chiho-rei", ["2026-11-09"], "47_3", None, None, None,
     "同一生計配偶者及び扶養親族（年齢十六歳未満の者及び法第三百十四条の二第一項第十一号に規定する控除対象扶養親族に限る。…）"),
    # §5.1
    ("PS5.1-185-1-1", "shotoku", ["2026-12-31"], "185", 1, "1", None,
     "給与所得者の扶養控除等申告書を提出した居住者に対し、その提出の際に経由した給与等の支払者が支払う給与等"),
    ("PS5.1-185-1-1b", "shotoku", ["2026-12-31"], "185", 1, "1", None,
     "当該申告書に記載された源泉控除対象配偶者及び源泉控除対象親族（…）の有無及びその数に応ずる"),
    ("PS5.1-185-1-2", "shotoku", ["2026-12-31"], "185", 1, "2", None, "前号及び次号に掲げる給与等以外の給与等"),
    ("PS5.1-185-1-2b", "shotoku", ["2026-12-31"], "185", 1, "2", None,
     "従たる給与についての扶養控除等申告書の提出の有無並びに当該申告書に記載された…源泉控除対象配偶者及び源泉控除対象親族"),
    ("PS5.1-185-1-3", "shotoku", ["2026-12-31"], "185", 1, "3", None,
     "労働した日又は時間によつて算定され、かつ、労働した日ごとに支払を受ける給与等で政令で定めるもの"),
    ("PS5.1-194-1", "shotoku", ["2026-12-31"], "194", 1, None, None,
     "国内において給与等の支払を受ける居住者は、その給与等の支払者（その支払者が二以上ある場合には、主たる給与等の支払者）から毎年最初に給与等の支払を受ける日の前日までに、次に掲げる事項を記載した申告書を、当該給与等の支払者を経由して…提出しなければならない。"),
    ("PS5.1-194-1-5", "shotoku", ["2026-12-31"], "194", 1, "5", None,
     "源泉控除対象親族の氏名及び個人番号…並びに源泉控除対象親族のうちに特定扶養親族又は老人扶養親族がある場合には、その旨及びその該当する事実"),
    ("PS5.1-194-8", "shotoku", ["2026-12-31"], "194", 8, None, None, "給与所得者の扶養控除等申告書"),
    ("PS5.1-195_3-1", "shotoku", ["2026-12-31"], "195_3", 1, None, None,
     "国内において給与等の支払を受ける居住者は、第百九十条（年末調整）に規定する過不足の額の計算上、同条第二号ホに掲げる特定親族特別控除の額に相当する金額の控除を受けようとする場合には、その給与等の支払者（二以上の給与等の支払者から給与等の支払を受ける場合には、主たる給与等の支払者）からその年最後に給与等の支払を受ける日の前日までに、…申告書を…提出しなければならない。"),
    ("PS5.1-190", "shotoku", ["2026-12-31"], "190", None, None, None,
     "給与所得者の扶養控除等申告書を提出した居住者で、…その年中に支払うべきことが確定した給与等の金額が二千万円以下であるものに対し、その提出の際に経由した給与等の支払者がその年最後に給与等の支払をする場合…"),
    ("PS5.1-190-2-ho", "shotoku", ["2025-12-31", "2026-12-31"], "190", None, None, None,
     "有無、その特定親族がこの条に規定する居住者として当該申告書を提出しているかどうか、その特定親族の合計所得金額又はその見積額及びその特定親族の数に応じ、第八十四条の二の規定に準じて計算した特定親族特別控除の額に相当する金額"),
    ("PS5.1-121-1-1", "shotoku", ["2026-12-31"], "121", 1, "1", None,
     "一の給与等の支払者から給与等の支払を受け、かつ、当該給与等の全部について第百八十三条…又は第百九十条…の規定による所得税の徴収をされた又はされるべき場合において、…給与所得及び退職所得以外の所得金額…が二十万円以下であるとき"),
    ("PS5.3-2-34_5", "shotoku", ["2026-12-31"], "2", 1, "34_5", None,
     "控除対象扶養親族並びに居住者の親族（その居住者の配偶者を除く。）及び…里親に委託された児童でその居住者と生計を一にするもの（青色事業専従者等を除く。）のうち年齢十九歳以上二十三歳未満の者で合計所得金額が百万円以下であるもの（控除対象扶養親族に該当しないものに限る。）をいう。"),
    # 年齢の計算・民法
    ("PS1.3-nenrei-1", "nenrei", ["2026-11-09"], "_whole", None, None, None, "年齢ハ出生ノ日ヨリ之ヲ起算ス"),
    ("PS1.3-nenrei-2", "nenrei", ["2026-11-09"], "_whole", None, None, None, "民法第百四十三条ノ規定ハ年齢ノ計算ニ之ヲ準用ス"),
    ("PS1.3-minpo143-2", "minpo", ["2026-11-09"], "143", 2, None, None,
     "週、月又は年の初めから期間を起算しないときは、その期間は、最後の週、月又は年においてその起算日に応当する日の前日に満了する。ただし、月又は年によって期間を定めた場合において、最後の月に応当する日がないときは、その月の末日に満了する。"),
    ("PS2.3-minpo725", "minpo", ["2026-11-09"], "725", None, None, None, "六親等内の血族…配偶者…三親等内の姻族"),
    ("PS2.3-minpo727", "minpo", ["2026-11-09"], "727", None, None, None, "養子と養親及びその血族との間においては、養子縁組の日から、血族間におけるのと同一の親族関係を生ずる。"),
    ("PS2.3-minpo728-1", "minpo", ["2026-11-09"], "728", 1, None, None, "姻族関係は、離婚によって終了する。"),
    ("PS2.3-minpo728-2", "minpo", ["2026-11-09"], "728", 2, None, None, "夫婦の一方が死亡した場合において、生存配偶者が姻族関係を終了させる意思を表示したときも、前項と同様とする。"),
    # 推測 I2・I7 で使った数値・規定
    ("INF-I2-chiho295-1-2", "chiho", ["2026-11-09"], "295", 1, "2", None, "障害者、未成年者、寡婦又はひとり親（これらの者の前年の合計所得金額が百三十五万円を超える場合を除く。）"),
    # 訂正後の引用（検証で直した箇所）
    ("FIX-chirei7_2_2-2", "chiho-rei", ["2026-11-09"], "7_2_2", 2, None, None,
     "…当該年度の初日の属する年の前年（…）の…合計額が五十八万円以下の子（他の者の同一生計配偶者又は扶養親族とされている者を除く。）とする。"),
    ("FIX-chirei46_2_2-2", "chiho-rei", ["2026-11-09"], "46_2_2", 2, None, None,
     "…当該年度の初日の属する年の前年（…）の…合計額が五十八万円以下の子（他の者の同一生計配偶者又は扶養親族とされている者を除く。）とする。"),
    ("FIX-rei205-2-1", "shotoku-rei", ["2025-12-31", "2026-12-31"], "205", 2, "1", None,
     "その親族が同一生計配偶者又は扶養親族に該当する場合には、その者を自己の同一生計配偶者又は扶養親族としている居住者の親族とする。"),
    ("FIX-chiho311-1", "chiho", ["2026-11-09"], "311", 1, None, None,
     "同一生計配偶者又は扶養親族（年齢十六歳未満の者及び第三百十四条の二第一項第十一号に規定する控除対象扶養親族に限る。）"),
    ("INF-I7-sochi41_16_2@2025", "sochi", ["2025-12-31"], "41_16_2", 1, None, None,
     "令和七年分及び令和八年分…合計所得金額が百三十二万円以下である場合…三十七万円"),
    ("INF-I7-sochi41_16_2@2026", "sochi", ["2026-12-31"], "41_16_2", 1, None, None,
     "令和八年分及び令和九年分…合計所得金額が四百八十九万円以下である場合…四十二万円"),
    ("INF-I7-86@2025", "shotoku", ["2025-12-31"], "86", 1, "1", None, "その居住者の合計所得金額が二千三百五十万円以下である場合…五十八万円"),
    ("INF-I7-86@2026", "shotoku", ["2026-12-31"], "86", 1, "1", None, "その居住者の合計所得金額が二千三百五十万円以下である場合…六十二万円"),
    ("INF-I7-84_2-1", "shotoku", ["2025-12-31", "2026-12-31"], "84_2", 1, None, None, "合計所得金額が百二十三万円以下であるものに限る。）で控除対象扶養親族に該当しないもの"),
    ("M3.2-2-32@2026-11-09", "shotoku", ["2026-11-09"], "2", 1, "32", None, "合計所得金額が八十五万円以下であり"),
    ("M3.2-2-32@2026-12-31", "shotoku", ["2026-12-31"], "2", 1, "32", None, "合計所得金額が八十九万円以下であり"),
    ("CHK-minpo4", "minpo", ["2026-11-09"], "4", None, None, None, "年齢十八歳をもって、成年とする。"),
    ("INF-I2-chiho318", "chiho", ["2026-11-09"], "318", None, None, None, "個人の市町村民税の賦課期日は、当該年度の初日の属する年の一月一日とする。"),
]

# 文書に書かれた「版」の主張（PS §0.1・M §3.1）
REV_CLAIMS = [
    ("shotoku", "2025-12-31", "340AC0000000033_20251218_507AC0000000013", "PreviousEnforced"),
    ("shotoku", "2026-11-09", "340AC0000000033_20261001_507AC0000000070", "CurrentEnforced"),
    ("shotoku", "2026-12-31", "340AC0000000033_20261201_508AC0000000012", "UnEnforced"),
    ("shotoku-rei", "2025-12-31", "340CO0000000096_20251201_507CO0000000120", "PreviousEnforced"),
    ("shotoku-rei", "2026-11-09", "340CO0000000096_20260522_508CO0000000093", "CurrentEnforced"),
    ("shotoku-rei", "2026-12-31", "340CO0000000096_20261201_508CO0000000093", "UnEnforced"),
    ("shotoku-ki", "2026-11-09", "340M50000040011_20261001_507M60000040018", "CurrentEnforced"),
    ("chiho", "2026-11-09", "325AC0000000226_20261101_508AC0000000002", "CurrentEnforced"),
    ("chiho-rei", "2026-11-09", "325CO0000000245_20261101_508CO0000000083", "CurrentEnforced"),
]

SCAN = {
    "minpo": r"民法",
    "applied_as_resident": r"居住者として[^。]*適用を受けている場合",
    "nensho": r"年少扶養親族",
    # 担当の実測 §3.3 と同じ正規表現（件数の再現）
    "fuyo_status": r"扶養親族(?:とされ|に該当する者|に該当するもの)|特定親族とされ|同一生計配偶者又は扶養親族",
}


def misc_render_hash(arts_by_num, nums):
    """担当（IMPL_misc_egov.py）の render を写して、所令218〜220 の連結テキストの SHA-256 を再計算する。"""
    block = {"Paragraph", "Item"} | {f"Subitem{i}" for i in range(1, 11)}

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
        if tag in block:
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

    lines = []
    for num in nums:
        lines.append(f"## Num={num}")
        render(arts_by_num[num], 0, lines)
        lines.append("")
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def run_egov():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL_misc_verify_egov"
    dl.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    data = {}
    res = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "revisions": [], "rev_claims": [], "quotes": [],
           "identity_218_220": {}, "scan": {}, "suppl": {}, "articles": {}, "errors": []}
    for short, (law_id, asofs, omit) in LAWS.items():
        for asof in asofs:
            q = {"response_format": "json", "asof": asof}
            if omit:
                q["omit_amendment_suppl_provision"] = "true"
            url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode(q)
            st, body, _ = get(url)
            (dl / f"{short}_{asof}.json").write_bytes(body)
            if st != 200:
                res["errors"].append({"short": short, "asof": asof, "status": st, "head": body[:200].decode("utf-8", "replace")})
                print("ERR", short, asof, st, flush=True)
                continue
            d = json.loads(body)
            ri = d.get("revision_info") or {}
            res["revisions"].append({"short": short, "asof": asof, "url": url, "law_revision_id": ri.get("law_revision_id"),
                                     "amendment_law_num": ri.get("amendment_law_num"), "amendment_law_title": ri.get("amendment_law_title"),
                                     "amendment_enforcement_date": ri.get("amendment_enforcement_date"),
                                     "current_revision_status": ri.get("current_revision_status")})
            data[(short, asof)] = d["law_full_text"]
            print("ok", short, asof, ri.get("law_revision_id"), flush=True)

    # 版の主張
    revmap = {(r["short"], r["asof"]): r for r in res["revisions"]}
    for short, asof, rid, stt in REV_CLAIMS:
        r = revmap.get((short, asof), {})
        res["rev_claims"].append({"short": short, "asof": asof, "claimed": rid, "claimed_status": stt,
                                  "actual": r.get("law_revision_id"), "actual_status": r.get("current_revision_status"),
                                  "ok": r.get("law_revision_id") == rid and r.get("current_revision_status") == stt})

    # 引用の断片
    ps_text = PS_DOC.read_text(encoding="utf-8")
    for qid, short, asofs, art, para, item, sub, quote in LAW_QUOTES:
        for asof in asofs:
            root = data.get((short, asof))
            rec = {"id": qid, "law": short, "asof": asof, "article": art, "para": para, "item": item, "quote": quote}
            if root is None:
                rec["result"] = "law not fetched"
                res["quotes"].append(rec)
                continue
            if art == "_whole":
                node = root
            else:
                node = locate(main_articles(root), art, para, item, sub)
            if node is None:
                rec["result"] = "location not found"
            else:
                miss = frags_in_order(quote, flat(node))
                rec["result"] = "ok" if miss is None else "MISSING"
                if miss is not None:
                    rec["missing_fragment"] = miss
            # 文書（PS）に同じ文言があるか（PS の引用と照合しているかの確認。INF- は推測の文書の記載なので対象外）
            if qid.startswith("PS"):
                rec["in_ps_doc"] = all(norm(f) in norm(ps_text) for f in re.split(r"…+", quote) if norm(f))
            res["quotes"].append(rec)

    # 所令218〜220 の同一性（自分の平文化と、担当の render を写したものの両方）
    for asof in ["2025-12-31", "2026-11-09", "2026-12-31"]:
        arts = main_articles(data[("shotoku-rei", asof)])
        mine = hashlib.sha256("".join(norm(flat(arts[n])) for n in ["218", "218_2", "219", "220"]).encode()).hexdigest()
        theirs = misc_render_hash(arts, ["218", "218_2", "219", "220"])
        res["identity_218_220"][asof] = {"normalized_sha256": mine, "misc_render_sha256": theirs}

    # 条の見出し・本文（確認用）
    want = {
        "shotoku": ["83_2", "84", "84_2", "85", "86", "121", "185", "190", "194", "195", "195_3"],
        "shotoku-rei": ["11_2", "205", "217_2", "217_3", "218", "218_2", "219", "220", "318"],
        "chiho": ["295", "311", "314_2", "318"],
        "chiho-rei": ["7_2_2", "7_3_3", "46_2_2", "46_3", "47_3"],
        "sochi": ["41_16_2"],
        "minpo": ["4", "143", "725", "727", "728"],
    }
    for short, nums in want.items():
        for (s, asof), root in data.items():
            if s != short:
                continue
            arts = main_articles(root)
            for n in nums:
                a = arts.get(n)
                res["articles"][f"{short}@{asof}#{n}"] = {"caption": caption(a) if a else None,
                                                         "text": flat(a) if a else None}
        # 第2条第1項の号（所得税法）
    for asof in ["2025-12-31", "2026-11-09", "2026-12-31"]:
        arts = main_articles(data[("shotoku", asof)])
        p1 = locate(arts, "2", 1)
        for it in kids(p1, "Item"):
            num = it.get("attr", {}).get("Num")
            if num in ("30", "31", "32", "33", "33_2", "33_3", "33_4", "34", "34_2", "34_3", "34_4", "34_5", "34_6"):
                res["articles"][f"shotoku@{asof}#2-1-{num}"] = {"caption": None, "text": flat(it)}

    # 走査
    for (short, asof), root in data.items():
        if short not in ("shotoku", "shotoku-rei", "shotoku-ki", "chiho", "chiho-rei"):
            continue
        hits = {}
        for num, a in main_articles(root).items():
            for ln in lines_of(a):
                for key, pat in SCAN.items():
                    if re.search(pat, ln):
                        hits.setdefault(key, []).append({"article": num, "caption": caption(a), "line": ln[:400]})
        res["scan"][f"{short}@{asof}"] = {"counts": {k: len(v) for k, v in hits.items()},
                                         "articles": {k: sorted({h["article"] for h in v}, key=lambda x: [int(p) for p in x.split("_")]) for k, v in hits.items()},
                                         "hits": hits}

    # 改正法の附則（所得税法 2026-12-31 の版に収録されたもの）
    root = data.get(("shotoku_suppl", "2026-12-31"))
    if root is not None:
        sps = []
        walk(root, lambda n, p: sps.append(n) if n.get("tag") == "SupplProvision" else None)
        for sp in sps:
            aln = sp.get("attr", {}).get("AmendLawNum", "")
            if any(k in aln for k in ("令和七年三月三一日法律第一三号", "令和八年三月三一日法律第一二号")):
                arts = [c for c in sp.get("children", []) if isinstance(c, dict) and c.get("tag") == "Article"]
                key = aln
                res["suppl"][key] = {}
                for a in arts:
                    if a["attr"].get("Num") in ("1", "2", "3", "6", "7", "9"):
                        res["suppl"][key][a["attr"]["Num"]] = flat(a, skip_num=False)
                if not arts:  # 条の無い附則
                    res["suppl"][key]["_"] = flat(sp, skip_num=False)[:3000]

    (OUT / "egov.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    md = [f"# e-Gov による検証（取得 {ts}）", "", "## 版", "", "| 略称 | asof | law_revision_id | 改正法令 | 施行日 | 状態 |", "|---|---|---|---|---|---|"]
    md += [f"| {r['short']} | {r['asof']} | {r['law_revision_id']} | {r['amendment_law_num']} | {r['amendment_enforcement_date']} | {r['current_revision_status']} |" for r in res["revisions"]]
    md += ["", "## 文書に書かれた版の主張", "", "| 略称 | asof | 主張 | 実際 | 一致 |", "|---|---|---|---|---|"]
    md += [f"| {c['short']} | {c['asof']} | {c['claimed']} {c['claimed_status']} | {c['actual']} {c['actual_status']} | {c['ok']} |" for c in res["rev_claims"]]
    md += ["", "## 引用の断片", "", "| ID | 法令@版 | 条・項・号 | 結果 | PS 文書に同じ文言 | 欠けた断片 |", "|---|---|---|---|---|---|"]
    for q in res["quotes"]:
        md.append(f"| {q['id']} | {q['law']}@{q['asof']} | {q['article']}-{q['para']}-{q['item']} | {q['result']} | {q.get('in_ps_doc', '')} | {q.get('missing_fragment', '')[:60]} |")
    md += ["", "## 所令218〜220 の同一性", "", "| asof | 正規化した平文の SHA-256 | 担当の render を写した SHA-256 |", "|---|---|---|"]
    md += [f"| {k} | {v['normalized_sha256']} | {v['misc_render_sha256']} |" for k, v in res["identity_218_220"].items()]
    md += ["", "## 本則の走査", "", "| 法令@版 | キー | 行数 | 条 |", "|---|---|---|---|"]
    for k, v in res["scan"].items():
        for kk in SCAN:
            md.append(f"| {k} | {kk} | {v['counts'].get(kk, 0)} | {', '.join(v['articles'].get(kk, []))} |")
    (OUT / "egov.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


# ---------------------------------------------------------------- web

class Extract(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.title = [], ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "img" and a.get("alt") and not self._skip:
            self.parts.append(a["alt"])
        if tag in ("br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "dt", "dd", "table"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if not self._skip:
            self.parts.append(data)


NTA = "https://www.nta.go.jp"
PAGES = {
    "ta_1180": f"{NTA}/taxes/shiraberu/taxanswer/shotoku/1180.htm",
    "ta_1180_qa": f"{NTA}/taxes/shiraberu/taxanswer/shotoku/1180_qa.htm",
    "ta_1177": f"{NTA}/taxes/shiraberu/taxanswer/shotoku/1177.htm",
    "ta_1900": f"{NTA}/taxes/shiraberu/taxanswer/shotoku/1900.htm",
    "ta_2511": f"{NTA}/taxes/shiraberu/taxanswer/gensen/2511.htm",
    "ta_2514": f"{NTA}/taxes/shiraberu/taxanswer/gensen/2514.htm",
    "ta_2520": f"{NTA}/taxes/shiraberu/taxanswer/gensen/2520.htm",
    "yogo_senmon": f"{NTA}/taxes/shiraberu/taxanswer/yogo/senmon.htm",
    "sg_s0564": f"{NTA}/law/shitsugi/shotoku/05/64.htm",
    "sg_s0567": f"{NTA}/law/shitsugi/shotoku/05/67.htm",
    "sg_g0309": f"{NTA}/law/shitsugi/gensen/03/09.htm",
    "p1648": f"{NTA}/taxes/tetsuzuki/shinsei/annai/gensen/annai/1648_01.htm",
    "t25_y10": f"{NTA}/taxes/shiraberu/shinkoku/tebiki/2025/03/order3/yogo/3-3_y10.htm",
    "t25_y11": f"{NTA}/taxes/shiraberu/shinkoku/tebiki/2025/03/order3/yogo/3-3_y11.htm",
    "t25_y13": f"{NTA}/taxes/shiraberu/shinkoku/tebiki/2025/03/order3/yogo/3-3_y13.htm",
    "t26_y13": f"{NTA}/taxes/shiraberu/shinkoku/tebiki/2026/03/order3/yogo/3-3_y13.htm",
    "hanrei_62674": "https://www.courts.go.jp/hanrei/62674/detail2/index.html",
    "kihon_16_06": f"{NTA}/law/tsutatsu/kihon/shotoku/16/06.htm",
    "t25_y09": f"{NTA}/taxes/shiraberu/shinkoku/tebiki/2025/03/order3/yogo/3-3_y09.htm",
    "nta_robots": f"{NTA}/robots.txt",
    "courts_robots": "https://www.courts.go.jp/robots.txt",
}
PDFS = {
    "form_r07_fuyo": f"{NTA}/taxes/tetsuzuki/shinsei/annai/gensen/pdf/2025bun_01.pdf",
    "form_r08_fuyo": f"{NTA}/taxes/tetsuzuki/shinsei/annai/gensen/pdf/2026bun_01.pdf",
    "nencho2025_105": f"{NTA}/publication/pamph/gensen/nencho2025/pdf/105.pdf",
    "nencho2026_105": f"{NTA}/publication/pamph/gensen/nencho2026/pdf/105.pdf",
    "nencho2025_106": f"{NTA}/publication/pamph/gensen/nencho2025/pdf/106.pdf",
    "nencho2026_106": f"{NTA}/publication/pamph/gensen/nencho2026/pdf/106.pdf",
    "hotei2025_02": f"{NTA}/publication/pamph/hotei/tebiki2025/PDF/02.pdf",
    "hotei2026_02": f"{NTA}/publication/pamph/hotei/tebiki2026/PDF/02.pdf",
    "chousho_r08": f"{NTA}/taxes/tetsuzuki/shinsei/annai/hotei/pdf/r08/0026009-129.pdf",
    "chousho_r08_kisai": f"{NTA}/taxes/tetsuzuki/shinsei/annai/hotei/pdf/r08/kisai_chousho01.pdf",
    "kokugai_qa": f"{NTA}/publication/pamph/pdf/0022009-107_02.pdf",
    "hanrei_pdf": "https://www.courts.go.jp/assets/hanrei/hanrei-pdf-62674.pdf",
}
# (ページ, 文言（「…」で区切る）)
WEB_QUOTES = [
    ("ta_1180", "控除対象扶養親族とは、扶養親族のうち、その年12月31日現在の年齢が16歳以上の人をいいます。"),
    ("ta_1180", "配偶者以外の親族（6親等内の血族および3親等内の姻族をいいます。）または…里子…や…養護を委託された老人であること。"),
    ("ta_1180", "令和8年4月1日現在法令等"),
    ("ta_1180_qa", "親族とは、（1）六親等内の血族、（2）配偶者、（3）三親等内の姻族をいいますが、図表で示すと次のようになります。"),
    ("ta_1180_qa", "子のある者と再婚した場合のその子（所得なし）は、一親等の姻族に該当しますので、あなたと生計を一にしており、かつ、その子が16歳以上であれば扶養控除の対象となります。"),
    ("ta_1180_qa", "兄弟のうち、だれか1人だけが扶養控除の対象とすることができます。したがって、たとえ兄弟が均等に送金している場合であっても、兄弟がそれぞれ重複して控除の対象とすることはできません。"),
    ("ta_1180_qa", "12月31日の現況において、ある一人の者を対象として複数の納税者がそれぞれ重複して配偶者控除や扶養控除を受けることはできません。しかし、年の途中で死亡または出国した納税者の控除対象配偶者または控除対象扶養親族に該当した人であっても、その後、その年中において相続人等他の納税者の控除対象配偶者または控除対象扶養親族に該当する場合は、その納税者の控除対象配偶者または控除対象扶養親族として控除の対象となることができます。"),
    ("ta_1180_qa", "令和8年4月1日現在法令等"),
    ("ta_1177", "令和8年4月1日現在法令等"),
    ("ta_1900", "令和8年4月1日現在法令等"),
    ("ta_1900", "給与を1か所から受けていて、かつ、その給与の全部が源泉徴収の対象となる場合において、各種の所得金額（給与所得、退職所得を除く。）の合計額が20万円を超える人"),
    ("ta_2511", "令和8年4月1日現在法令等"),
    ("ta_2511", "「給与所得者の扶養控除等申告書」を提出している人に支払う給与については「甲欄」を、その他の人に支払う給与については「乙欄」を使って税額を求めます。"),
    ("ta_2511", "パートやアルバイトに対して日給や時間給で給与を支払う場合は、あらかじめ雇用契約の期間が2か月以内と決められていれば、「日額表」の「丙欄」を使って税額を求めます。"),
    ("ta_2511", "夫婦の双方がお互いに源泉控除対象配偶者に係る控除の適用を受けることはできません。また、親族の双方がお互いに特定親族に係る控除の適用を受けることや、特定親族に係る控除の適用を受けている親族を特定親族として控除の適用を受けることはできませんので、ご注意ください。"),
    ("ta_2514", "令和8年4月1日現在法令等"),
    ("ta_2514", "あらかじめ定められている雇用契約の期間が2か月以内であること。"),
    ("ta_2514", "日々雇い入れている場合には、継続して2か月を超えて支払をしないこと。"),
    ("ta_2514", "契約期間が2か月を超えた日から、「日額表」の「丙欄」を使うことができません。"),
    ("ta_2520", "令和8年4月1日現在法令等"),
    ("ta_2520", "主たる給与とは、「給与所得者の扶養控除等申告書」を提出している人に支払う給与をいい、…「甲欄」で求めます。"),
    ("ta_2520", "従たる給与とは、主たる給与の支払者以外の給与の支払者が支払う給与をいい、…「乙欄」で求めます。"),
    ("ta_2520", "原則として従たる給与については年末調整できませんので、所得者本人が確定申告することにより…精算を行う必要があります。"),
    ("yogo_senmon", "配偶者以外の親族（6親等内の血族および3親等内の姻族をいいます。）または…"),
    ("sg_s0567", "ここでいう「親族」とは、民法の規定に従い、6親等内の血族及び3親等内の姻族をいい（民法第725条）、「姻族」とは、配偶者の血族及び自己の血族の配偶者をいいますので、配偶者の子は、1親等の姻族に該当することとなります。"),
    ("sg_s0567", "なお、養子縁組をした場合には、血族間におけるのと同一の親族関係が生じますので（民法第727条）、1親等の血族に該当することとなります。"),
    ("sg_s0567", "令和7年8月1日現在の法令・通達等に基づく"),
    ("sg_s0567", "所得税法第2条第1項第34号、第34号の2、第84条"),
    ("sg_s0567", "民法第725条、第727条"),
    ("sg_s0564", "配偶者の死亡により婚姻関係は解消されますが、その配偶者の父母との姻族関係が直ちに否定されるわけではなく、生存している配偶者が婚姻関係を終了させる意思表示をしない限り死亡した配偶者の直系尊属も「配偶者の直系尊属」に含まれます。"),
    ("sg_s0564", "令和7年8月1日現在の法令・通達等に基づく"),
    ("sg_s0564", "租税特別措置法第41条の16第1項"),
    ("sg_s0564", "民法第728条第2項"),
    ("sg_g0309", "重複しない限り、いずれの者の扶養親族としても差し支えありません。"),
    ("sg_g0309", "同じ世帯に所得者が2人以上いる場合には、これらの者の扶養親族等を、その夫や妻若しくは同じ世帯の他の所得者のいずれの者の控除対象配偶者や扶養親族とするのかといった疑義が生じますが、このような場合には、「給与所得者の扶養控除等申告書」に記載されたところによることとされています。"),
    ("sg_g0309", "令和7年8月1日現在の法令・通達等に基づく"),
    ("sg_g0309", "所得税法施行令第218条、第219条"),
    ("sg_g0309", "この質疑事例は、照会に係る事実関係を前提とした一般的な回答であり、…この回答内容と異なる課税関係が生ずることがあることにご注意ください。"),
    ("p1648", "国内において給与の支給を受ける居住者は、源泉控除対象配偶者や扶養親族の有無にかかわらず原則としてこの申告を行わなければなりません。この申告を行わない場合は、月々（日々）の源泉徴収の際に受けることのできる諸控除が受けられず、また年末調整も行われないことになります。また、2以上の給与の支払者から給与の支払を受ける場合には、そのいずれか一の給与の支払者に対してのみ提出することができます。なお、適用される税額表が日額表の丙欄とされる人は、この申告書を提出する必要はありません。"),
    ("p1648", "「給与所得者の扶養控除等（異動）申告書」は、個人住民税の「給与所得者の扶養親族申告書」と統合した様式となっています。"),
    ("p1648", "所得税法第194条"),
    ("p1648", "所得税法施行令第316条の2"),
    ("p1648", "地方税法第45条の3の2"),
    ("p1648", "第317条の3の2"),
    ("t25_y13", "扶養親族のうち、平成22年1月1日以前に生まれた方（年齢が16歳以上の方）"),
    ("t25_y13", "平成8年1月2日から平成22年1月1日までの間"),
    ("t25_y13", "昭和31年1月2日から平成8年1月1日までの間"),
    ("t25_y10", "平成15年1月2日から平成19年1月1日までの間"),
    ("t25_y11", "昭和31年1月1日以前"),
    ("ta_2511", "この「扶養親族等の数」とは、源泉控除対象配偶者と源泉控除対象親族との合計数をいいます"),
    ("ta_2511", "（4）の日雇賃金については「丙欄」を使って税額を求めます。"),
    ("ta_1900", "給与を2か所以上から受けていて、…年末調整されなかった給与の収入金額と、各種の所得金額…との合計額が20万円を超える人"),
    ("t25_y09", "扶養親族"),
    ("t25_y13", "平成８年１月２日から平成22年１月１日の間に生まれた方（年齢が16歳以上30歳未満の方）"),
    ("t25_y13", "昭和31年１月２日から平成８年１月１日の間に生まれて（年齢が30歳以上70歳未満）"),
    ("hanrei_62674", "扶養控除の対象となる親族の範囲を定める所得税法（昭和六一年法律第一〇九号による改正前のもの）八四条、二条一項三四号の規定は、憲法一三条、一四条一項、二四条、二五条に違反しない。"),
    ("hanrei_62674", "昭和62(行コ)110"),
    ("sg_s0567", "令和7年8月1日現在の法令・通達等に基づいて作成しています。"),
    ("hanrei_62674", "平成3年10月17日"),
    ("hanrei_62674", "最高裁判所第一小法廷"),
    ("hanrei_62674", "平成2(行ツ)12"),
    ("hanrei_62674", "集民 第163号381頁"),
    ("hanrei_62674", "平成元年9月19日"),
    ("hanrei_62674", "婚姻の届出をしていないが事実上婚姻関係と同様の事情にある者との間の未認知の子又はその者の連れ子と所得税法（昭和六一年法律第一〇九号による改正前のもの）八四条、二条一項三四号に規定する扶養控除の対象となる親族"),
]


def run_web():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl_html = ROOT / ".work" / "downloads" / f"{ts}_IMPL_misc_verify_html"
    dl_pdf = ROOT / ".work" / "downloads" / f"{ts}_IMPL_misc_verify_pdf"
    dl_html.mkdir(parents=True, exist_ok=False)
    dl_pdf.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"run_at": ts, "html_dir": str(dl_html.relative_to(ROOT)), "pdf_dir": str(dl_pdf.relative_to(ROOT)),
           "pages": {}, "pdfs": {}, "quotes": []}
    texts = {}
    for pid, url in PAGES.items():
        st, body, hdr = get(url, accept="text/html")
        (dl_html / f"{pid}.html").write_bytes(body)
        enc = "utf-8"
        m = re.search(rb"charset=[\"']?([A-Za-z0-9_\-]+)", body[:3000])
        if m:
            enc = m.group(1).decode()
        txt = body.decode(enc, "replace")
        ex = Extract()
        ex.feed(txt)
        text = "".join(ex.parts)
        texts[pid] = text
        res["pages"][pid] = {"url": url, "status": st, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
                             "last_modified": hdr.get("Last-Modified"), "title": ex.title.strip(),
                             "is_error_page": "指定されたページを表示できませんでした" in text}
        print("html", pid, st, len(body), hdr.get("Last-Modified"), ex.title.strip()[:50], flush=True)
    for pid, quote in WEB_QUOTES:
        t = texts.get(pid, "")
        miss = frags_in_order(quote, t)
        res["quotes"].append({"page": pid, "quote": quote, "result": "ok" if miss is None else "MISSING", "missing_fragment": miss})
    # 基準日・日付の表示を拾う（確認用）
    for pid, t in texts.items():
        res["pages"][pid]["date_marks"] = sorted(set(re.findall(r"［[^］]{0,30}現在[^］]{0,10}］|\[[^\]]{0,30}現在[^\]]{0,10}\]|令和\d+年\d+月\d+日現在の法令・通達等", t)))
        res["pages"][pid]["text_head"] = re.sub(r"\s+", " ", t)[:200]
    for rid in ("nta_robots", "courts_robots"):
        res["pages"][rid]["disallow_for_star"] = []
        cur = []
        for ln in texts.get(rid, "").splitlines():
            ln = ln.strip()
            if ln.lower().startswith("user-agent:"):
                cur = [ln.split(":", 1)[1].strip()]
            elif ln.lower().startswith("disallow:") and "*" in cur:
                res["pages"][rid]["disallow_for_star"].append(ln.split(":", 1)[1].strip())
    # 所得税基本通達 85 関係の見出しと 85-1・85-2 の付近（確認用）
    t = texts.get("kihon_16_06", "")
    res["pages"]["kihon_16_06"]["mentions_219_2"] = [m.start() for m in re.finditer(r"令第219条第2項|令219②|第219条第２項", t)]
    res["pages"]["kihon_16_06"]["excerpt_85"] = [re.sub(r"\s+", " ", t[m.start(): m.start() + 600]) for m in re.finditer(r"85－[0-9０-９]+|85-[0-9]+", t)][:6]
    for pid, url in PDFS.items():
        st, body, hdr = get(url, accept="application/pdf")
        (dl_pdf / f"{pid}.pdf").write_bytes(body)
        res["pdfs"][pid] = {"url": url, "status": st, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
                            "last_modified": hdr.get("Last-Modified"), "content_type": hdr.get("Content-Type"),
                            "is_pdf": body[:5] == b"%PDF-"}
        print("pdf", pid, st, len(body), hdr.get("Last-Modified"), flush=True)
    (OUT / "web.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    md = [f"# 国税庁・裁判所の資料による検証（取得 {ts}）", "", "## HTML", "",
          "| ID | HTTP | バイト | SHA-256（先頭16） | Last-Modified | エラーページ | 基準日の表示 |", "|---|---|---|---|---|---|---|"]
    for pid, p in res["pages"].items():
        md.append(f"| {pid} | {p['status']} | {p['bytes']} | {p['sha256'][:16]} | {p['last_modified']} | {p['is_error_page']} | {'; '.join(p['date_marks'])} |")
    md += ["", "## PDF（中身は Read ツールで読む）", "", "| ID | HTTP | バイト | SHA-256（先頭16） | Last-Modified | PDF |", "|---|---|---|---|---|---|"]
    for pid, p in res["pdfs"].items():
        md.append(f"| {pid} | {p['status']} | {p['bytes']} | {p['sha256'][:16]} | {p['last_modified']} | {p['is_pdf']} |")
    md += ["", "## 文言の照合", "", "| ページ | 結果 | 文言（先頭） | 欠けた断片 |", "|---|---|---|---|"]
    for q in res["quotes"]:
        md.append(f"| {q['page']} | {q['result']} | {q['quote'][:50]} | {(q['missing_fragment'] or '')[:50]} |")
    (OUT / "web.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


# ---------------------------------------------------------------- age

def add_years(b, n):
    """b の n 年後の応当する日。無ければ None（2月29日生まれで平年）。"""
    try:
        return b.replace(year=b.year + n)
    except ValueError:
        return None


def age_at_end_of(b, d):
    """日 d の終了時の年齢。担当の式（期間の満了日を数える while ループ）とは別に、
    「n 歳に達する日（＝ n 年後の応当日の前日。応当日が無ければその月の末日）」を n について直接求め、二分探索する。"""
    def reach(n):
        a = add_years(b, n)
        if a is None:
            y = b.year + n
            return dt.date(y, b.month, calendar.monthrange(y, b.month)[1])
        return a - dt.timedelta(days=1)
    lo, hi = 0, 200
    while lo < hi:  # reach(n) <= d を満たす最大の n
        mid = (lo + hi + 1) // 2
        if reach(mid) <= d:
            lo = mid
        else:
            hi = mid - 1
    return lo


def wareki_str(d):
    if d >= dt.date(2019, 5, 1):
        return f"令和{d.year - 2018}年{d.month}月{d.day}日"
    if d >= dt.date(1989, 1, 8):
        return f"平成{d.year - 1988}年{d.month}月{d.day}日"
    return f"昭和{d.year - 1925}年{d.month}月{d.day}日"


def derive_range(y, lo, hi, judge):
    """年齢 lo 以上 hi 未満（hi=None は上限なし）の人の生年月日の範囲を、判定日 judge の終了時の年齢から導く。"""
    start, end = dt.date(1900, 1, 1), dt.date(2030, 12, 31)
    days = []
    d = start
    while d <= end:
        a = age_at_end_of(d, judge)
        if a >= lo and (hi is None or a < hi):
            days.append(d)
        d += dt.timedelta(days=1)
    first, last = days[0], days[-1]
    return (None if first == start else first), (None if last >= dt.date(y, 12, 31) else last)


# 文書（PS §1.2）の表の値（和暦の表記のまま）。(年分, 区分, 下限, 上限, 判定日の種類, 表の「から」, 表の「まで」)
DOC_RANGES = [
    (2025, "控除対象扶養親族 16歳以上", 16, None, "dec31", None, "平成22年1月1日"),
    (2026, "控除対象扶養親族 16歳以上", 16, None, "dec31", None, "平成23年1月1日"),
    (2025, "非居住者 16歳以上30歳未満", 16, 30, "dec31", "平成8年1月2日", "平成22年1月1日"),
    (2026, "非居住者 16歳以上30歳未満", 16, 30, "dec31", "平成9年1月2日", "平成23年1月1日"),
    (2025, "非居住者 30歳以上70歳未満", 30, 70, "dec31", "昭和31年1月2日", "平成8年1月1日"),
    (2026, "非居住者 30歳以上70歳未満", 30, 70, "dec31", "昭和32年1月2日", "平成9年1月1日"),
    (2025, "老人扶養親族 70歳以上", 70, None, "dec31", None, "昭和31年1月1日"),
    (2026, "老人扶養親族 70歳以上", 70, None, "dec31", None, "昭和32年1月1日"),
    (2025, "特定扶養親族・特定親族 19歳以上23歳未満", 19, 23, "dec31", "平成15年1月2日", "平成19年1月1日"),
    (2026, "特定扶養親族・特定親族 19歳以上23歳未満", 19, 23, "dec31", "平成16年1月2日", "平成20年1月1日"),
    (2025, "16歳未満", 0, 16, "dec31", "平成22年1月2日", None),
    (2026, "16歳未満", 0, 16, "dec31", "平成23年1月2日", None),
    (2026, "障害者（65歳以上）", 65, None, "dec31", None, "昭和37年1月1日"),
    (2025, "源泉徴収票の未成年者（18歳未満）", 0, 18, "dec31", "平成20年1月3日", None),
    (2025, "源泉徴収票の未成年者（18歳未満）", 0, 18, "jan1_next", "平成20年1月3日", None),
    (2026, "源泉徴収票の未成年者（18歳未満）", 0, 18, "dec31", "平成21年1月3日", None),
    (2026, "源泉徴収票の未成年者（18歳未満）", 0, 18, "jan1_next", "平成21年1月3日", None),
]

# 推測 I1 の表（生年月日, 令和7年分の年齢, 令和8年分の年齢）
I1 = [("2003-01-01", 23, 24), ("2003-01-02", 22, 23), ("2007-01-01", 19, 20), ("2007-01-02", 18, 19),
      ("2010-01-01", 16, 17), ("2010-01-02", 15, 16), ("2011-01-01", 15, 16), ("2004-02-29", 21, 22),
      ("1956-01-01", 70, 71), ("1957-01-01", 69, 70)]


def run_age():
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"ranges": [], "i1": [], "formula_A_check": None, "death_day_examples": []}
    for (y, name, lo, hi, jd, s, e) in DOC_RANGES:
        judge = dt.date(y, 12, 31) if jd == "dec31" else dt.date(y + 1, 1, 1)
        f, l = derive_range(y, lo, hi, judge)
        fs, ls = (wareki_str(f) if f else None), (wareki_str(l) if l else None)
        res["ranges"].append({"year": y, "category": name, "judge_end_of": judge.isoformat(), "derived_from": fs, "derived_to": ls,
                              "doc_from": s, "doc_to": e, "match": (fs == s and ls == e)})
    for b, a25, a26 in I1:
        bd = dt.date.fromisoformat(b)
        g25, g26 = age_at_end_of(bd, dt.date(2025, 12, 31)), age_at_end_of(bd, dt.date(2026, 12, 31))
        res["i1"].append({"birth": b, "doc_2025": a25, "calc_2025": g25, "doc_2026": a26, "calc_2026": g26,
                          "match": (a25, a26) == (g25, g26)})
    # 式A（Y − 生年 ＋ 1月1日生まれは1）との一致（1900〜2030 年生まれの全日付、2020〜2030 年分）
    mism = 0
    d = dt.date(1900, 1, 1)
    while d <= dt.date(2030, 12, 31):
        for y in range(max(2020, d.year), 2031):
            a = y - d.year + (1 if (d.month, d.day) == (1, 1) else 0)
            if a != age_at_end_of(d, dt.date(y, 12, 31)):
                mism += 1
        d += dt.timedelta(days=1)
    res["formula_A_check"] = {"birth_range": "1900-01-01..2030-12-31", "years": "2020..2030 (生年以後)", "mismatches": mism}
    # 推測 I3 の場面（誕生日の前日に死亡した人）：死亡日の終了時と前日の終了時で年齢が違う例
    for b, death in [("2007-03-15", "2026-03-14"), ("2007-03-15", "2026-03-13")]:
        bd, dd = dt.date.fromisoformat(b), dt.date.fromisoformat(death)
        res["death_day_examples"].append({"birth": b, "death": death, "age_end_of_death_day": age_at_end_of(bd, dd),
                                          "age_end_of_day_before": age_at_end_of(bd, dd - dt.timedelta(days=1))})
    (OUT / "age.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# 年齢の判定の独立した再計算", "",
          "- 年齢＝判定日の終了時までに達した年齢。n 歳に達する日＝出生日の n 年後の応当日の前日（応当日が無ければその月の末日）。",
          "- 生年月日の範囲は、1900-01-01〜2030-12-31 の各日の年齢から導いた（担当の表を入力にしない）。", "",
          "## 生年月日の範囲（導いた値と文書の表）", "",
          "| 年分 | 区分 | 判定日（の終了時） | 導いた範囲 | 文書の範囲 | 一致 |", "|---|---|---|---|---|---|"]
    for r in res["ranges"]:
        md.append(f"| {r['year']} | {r['category']} | {r['judge_end_of']} | {r['derived_from'] or ''}〜{r['derived_to'] or ''} | "
                  f"{r['doc_from'] or ''}〜{r['doc_to'] or ''} | {r['match']} |")
    md += ["", "## 推測 I1 の表", "", "| 生年月日 | 文書 2025 | 計算 2025 | 文書 2026 | 計算 2026 | 一致 |", "|---|---|---|---|---|---|"]
    md += [f"| {r['birth']} | {r['doc_2025']} | {r['calc_2025']} | {r['doc_2026']} | {r['calc_2026']} | {r['match']} |" for r in res["i1"]]
    md += ["", f"## 式A との一致：{res['formula_A_check']}", "", "## 推測 I3 の場面", ""]
    md += [f"- 生年月日 {r['birth']}、死亡日 {r['death']}：死亡日の終了時 {r['age_end_of_death_day']} 歳、前日の終了時 {r['age_end_of_day_before']} 歳" for r in res["death_day_examples"]]
    (OUT / "age.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))




# ---------------------------------------------------------------- egov2（追加の確認）

def run_egov2():
    """所令の改正政令の附則（第217条の2・第217条の3 の適用年分）と、版の間の同一性の主張を確かめる。"""
    ts = time.strftime("%Y%m%d-%H%M%S")
    dl = ROOT / ".work" / "downloads" / f"{ts}_IMPL_misc_verify_egov2"
    dl.mkdir(parents=True, exist_ok=False)
    res = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "rei_suppl": [], "identity": {}}
    roots = {}
    for short, law_id, asof, omit in [("shotoku-rei_suppl", "340CO0000000096", "2026-12-31", False),
                                      ("shotoku", "340AC0000000033", "2025-12-31", True),
                                      ("shotoku", "340AC0000000033", "2026-11-09", True),
                                      ("shotoku", "340AC0000000033", "2026-12-31", True),
                                      ("shotoku-rei", "340CO0000000096", "2025-12-31", True),
                                      ("shotoku-rei", "340CO0000000096", "2026-11-09", True)]:
        q = {"response_format": "json", "asof": asof}
        if omit:
            q["omit_amendment_suppl_provision"] = "true"
        url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode(q)
        st, body, _ = get(url)
        (dl / f"{short}_{asof}.json").write_bytes(body)
        d = json.loads(body)
        roots[(short, asof)] = d["law_full_text"]
        print("ok", short, asof, (d.get("revision_info") or {}).get("law_revision_id"), flush=True)
    # 改正政令の附則のうち「第二百十七条の二」「第二百十七条の三」「特定親族」に触れる条
    sps = []
    walk(roots[("shotoku-rei_suppl", "2026-12-31")], lambda n, p: sps.append(n) if n.get("tag") == "SupplProvision" else None)
    for sp in sps:
        aln = sp.get("attr", {}).get("AmendLawNum", "")
        if not aln.startswith(("令和七年", "令和八年")):
            continue
        for a in [c for c in sp.get("children", []) if isinstance(c, dict) and c.get("tag") == "Article"]:
            t = flat(a, skip_num=False)
            if re.search(r"第二百十七条の[二三]|特定親族", t):
                res["rei_suppl"].append({"amend_law_num": aln, "article": a["attr"].get("Num"), "text": t[:3000]})
    # 同一性
    def art_text(short, asof, num):
        a = main_articles(roots[(short, asof)]).get(num)
        return norm(flat(a)) if a else None
    res["identity"]["rei217_3@2025_vs_rei217_2@2026-11-09"] = art_text("shotoku-rei", "2025-12-31", "217_3") == art_text("shotoku-rei", "2026-11-09", "217_2")
    res["identity"]["rei217_2@2025_caption"] = caption(main_articles(roots[("shotoku-rei", "2025-12-31")])["217_2"])
    res["identity"]["rei217_3@2025_caption"] = caption(main_articles(roots[("shotoku-rei", "2025-12-31")])["217_3"])
    res["identity"]["rei217_2@2026-11-09_caption"] = caption(main_articles(roots[("shotoku-rei", "2026-11-09")])["217_2"])
    for num in ["84", "84_2", "85", "83_2", "185", "190", "194", "195", "195_3", "121"]:
        a, b, c = (art_text("shotoku", v, num) for v in ["2025-12-31", "2026-11-09", "2026-12-31"])
        res["identity"][f"shotoku#{num}"] = {"2025==2026-11-09": a == b, "2026-11-09==2026-12-31": b == c}
    # 第185条の「控除対象扶養親族」→「源泉控除対象親族」
    for v in ["2025-12-31", "2026-11-09"]:
        t = art_text("shotoku", v, "185")
        res["identity"][f"shotoku#185@{v}"] = {"源泉控除対象親族": t.count("源泉控除対象親族"), "控除対象扶養親族": t.count("控除対象扶養親族")}
    # キーワード検索API（「年少扶養親族」）
    q = urllib.parse.urlencode({"keyword": "年少扶養親族", "response_format": "json", "asof": "2026-11-09", "limit": 100})
    st, body, _ = get(f"{API}/keyword?{q}")
    (dl / "keyword_nensho.json").write_bytes(body)
    try:
        kd = json.loads(body)
        res["keyword_nensho"] = {"status": st, "total_count": kd.get("total_count"), "message": kd.get("message")}
    except Exception as e:  # noqa: BLE001
        res["keyword_nensho"] = {"status": st, "error": repr(e), "head": body[:200].decode("utf-8", "replace")}
    (OUT / "egov2.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("keyword", res["keyword_nensho"])
    print(json.dumps(res["identity"], ensure_ascii=False, indent=1))
    for r in res["rei_suppl"]:
        print("====", r["amend_law_num"], "附則第", r["article"], "条")
        print(r["text"][:1500])


# ---------------------------------------------------------------- hash（担当の実測 §3.2 の SHA-256 の再現）

def run_hash():
    """担当の出力 scripts/results/IMPL_misc_egov/shotoku-rei_asof<版>.txt から、「## Num=218」「## Num=218_2」
    「## Num=219」「## Num=220」の節（見出し行を含む）をこの順に連結した文字列の SHA-256 を求める。
    担当の実測 §3.2 の `337b49872ee286ec…` がどう計算されたかを再現するためのもの（担当のスクリプトにはこの計算が無い）。"""
    src = ROOT / "scripts" / "results" / "IMPL_misc_egov"
    res = {}
    for v in ["2025-12-31", "2026-11-09", "2026-12-31"]:
        t = (src / f"shotoku-rei_asof{v}.txt").read_text(encoding="utf-8")
        secs = {}
        for s in re.split(r"(?m)^## ", t):
            m = re.match(r"Num=(\S+)", s)
            if m:
                secs[m.group(1).rstrip(":")] = "## " + s
        joined = "".join(secs[k] for k in ["218", "218_2", "219", "220"])
        res[v] = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    (OUT / "hash_218_220.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"egov": run_egov, "egov2": run_egov2, "hash": run_hash, "web": run_web, "age": run_age}.get(cmd, lambda: print(__doc__))()

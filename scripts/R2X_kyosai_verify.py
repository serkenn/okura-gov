"""R2X_kyosai_verify: 共済組合の被扶養者・住所が別の家族（第2ラウンド）の文書に書かれた条文・公表値・計算を、
別の担当（反証役）が一次情報に当たり直して確かめる。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_kyosai_verify.py egov   # e-Gov 法令API v2 で条文を取り直して照合
  ... scripts/R2X_kyosai_verify.py web    # 公表資料（HTML）を取り直して引用を照合、PDF は取り直して版（ハッシュ・Last-Modified）を記録
  ... scripts/R2X_kyosai_verify.py calc   # 文書にある計算（月額・日額の端数、年齢の範囲、窓の規則、事業収入、仕送りの割合、30日の数え方）をやり直す
  ... scripts/R2X_kyosai_verify.py egovextra  # 租税特別措置法第41条の16（推測 IKY9 が挙げた条番号）を取得
  ... scripts/R2X_kyosai_verify.py webextra   # 総務省のページで YORYO・TORI-S の版の表示とリンク先を確かめる
  ... scripts/R2X_kyosai_verify.py all        # 上の取得と計算をすべて行う
  ネットワークに出ない再照合（取得済みのディレクトリの JSON・HTML で引用の照合だけをやり直す）:
  ... scripts/R2X_kyosai_verify.py egovcheck                 # egov.json の download_dir を読む
  ... scripts/R2X_kyosai_verify.py webcheck <download_dir>   # 例 .work/downloads/20261109-185318_R2X_kyosai_verify_web
  ... scripts/R2X_kyosai_verify.py comparechecks             # 元の担当の R2X_kyosai_checks.py を直して再実行した前後の checks.json を比べる

- 対象の文書：
    docs/public-sources/20261109_round2_kyosai-law-and-criteria.md（[KY]）
    docs/public-sources/20261109_round2_kyosai-separate-address.md（[SA2]）
    docs/measurements/20261109_round2_kyosai-fetch-and-checks.md（[MS-KY]）
    docs/hypotheses/20261109_round2_kyosai-model.md、docs/inferences/20261109_round2_kyosai-cases.md
- 元の担当のスクリプト（R2X_kyosai_egov.py / _fetch.py / _checks.py）も、その出力も使わない。law_id から引き直す。
  ただし、取り直した版が元の担当の版と同じかを確かめるため、元の担当の取得記録（SHA-256・law_revision_id）を読んで比べる。
- ダウンロードしたものは信頼できないデータとして、取得ごとに新しい空のディレクトリ
  .work/downloads/<YYYYMMDD-HHMMSS>_R2X_kyosai_verify_<set>/ に置く。その中で何も実行しない。
  PDF の本文は Read ツールで描画を読み、文書（docs/measurements/20261109_round2_kyosai-verification.md）に記録する。
- リクエストの間は 1.5 秒あける。User-Agent は okura-gov-research/0.1。個人の情報は送らない。官報は取得しない。
- 出力：scripts/results/R2X_kyosai_verify/{egov,egov_extra,web,web_extra,calc,checks_compare}.json、
  条文のテキスト articles/<略称>_<asof>.txt、標準出力 run_*_stdout.txt
- 引用の照合：空白（全角を含む）を除き、NFKC で正規化して比べる。文書の引用にある「…」は省略の印として扱い、
  「…」で区切った断片がこの順に現れるかを見る。
"""
import datetime as dt
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
from fractions import Fraction

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "okura-gov-research/0.1"
API = "https://laws.e-gov.go.jp/api/2"
WAIT = 1.5
OUT = ROOT / "scripts" / "results" / "R2X_kyosai_verify"
TODAY = "2026-11-09"


# ---------------------------------------------------------------- 共通
def norm(s):
    s = unicodedata.normalize("NFKC", s)
    s = s.replace(",", "、")  # 全角コンマ（，）と読点（、）の違いを無視する（数字の桁区切りも両側で同じに変わる）
    return re.sub(r"\s+", "", s)


def has_quote(text, quote):
    """「…」で区切った断片が、この順に text に現れるか。"""
    t = norm(text)
    pos = 0
    for frag in [f for f in re.split(r"…+|・・・", quote) if norm(f)]:
        i = t.find(norm(frag), pos)
        if i < 0:
            return False, frag
        pos = i + len(norm(frag))
    return True, None


def http_get(url, accept=None, timeout=120):
    h = {"User-Agent": UA}
    if accept:
        h["Accept"] = accept
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            deadline = time.monotonic() + 180
            chunks = []
            while True:
                b = r.read(65536)
                if not b:
                    break
                chunks.append(b)
                if time.monotonic() > deadline:
                    raise TimeoutError("body read exceeded 180s")
            return r.status, r.geturl(), dict(r.headers), b"".join(chunks)
    except urllib.error.HTTPError as e:
        return e.code, url, dict(e.headers or {}), e.read()
    finally:
        time.sleep(WAIT)


def new_dl(name):
    ts = time.strftime("%Y%m%d-%H%M%S")
    d = ROOT / ".work" / "downloads" / f"{ts}_R2X_kyosai_verify_{name}"
    d.mkdir(parents=True, exist_ok=False)
    return ts, d


# ---------------------------------------------------------------- e-Gov
def text_of(node):
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ""
    if node.get("tag") == "Rt":
        return ""
    return "".join(text_of(c) for c in node.get("children", []))


def kids(node, tag=None):
    return [c for c in (node or {}).get("children", []) if isinstance(c, dict) and (tag is None or c.get("tag") == tag)]


def iter_tag(node, tag):
    if isinstance(node, dict):
        if node.get("tag") == tag:
            yield node
        for c in node.get("children", []):
            yield from iter_tag(c, tag)


def main_articles(full):
    mp = next(iter_tag(full, "MainProvision"), None)
    return {a.get("attr", {}).get("Num"): a for a in iter_tag(mp, "Article")} if mp else {}


def node_at(full, art, para=None, item=None, sub=None):
    """条・項・号・イロハ のノードを返す。item は ItemTitle（例 "二"）、sub は Subitem1Title（例 "ロ"）。"""
    a = main_articles(full).get(art)
    if a is None or para is None:
        return a
    p = next((x for x in kids(a, "Paragraph") if x.get("attr", {}).get("Num") == str(para)), None)
    if p is None or item is None:
        return p
    it = next((x for x in kids(p, "Item") if text_of(next(iter(kids(x, "ItemTitle")), {})) == item), None)
    if it is None or sub is None:
        return it
    return next((x for x in kids(it, "Subitem1") if text_of(next(iter(kids(x, "Subitem1Title")), {})) == sub), None)


def render_article(a):
    out = []
    for c in kids(a):
        if c.get("tag") in ("ArticleCaption", "ArticleTitle"):
            out.append(text_of(c))
        elif c.get("tag") == "Paragraph":
            out.append(f"[項{c.get('attr', {}).get('Num')}] " + text_of(next(iter(kids(c, "ParagraphSentence")), {})))
            for it in kids(c, "Item"):
                out.append("  " + text_of(next(iter(kids(it, "ItemTitle")), {})) + " " + text_of(next(iter(kids(it, "ItemSentence")), {})))
                for s in kids(it, "Subitem1"):
                    out.append("    " + text_of(s))
    return "\n".join(out)


def toc_ranges(full):
    mp = next(iter_tag(full, "MainProvision"), None)
    rows = []

    def nums(n):
        return [a.get("attr", {}).get("Num") for a in iter_tag(n, "Article")]

    for ch in kids(mp, "Chapter"):
        n = nums(ch)
        rows.append([text_of(next(iter(kids(ch, "ChapterTitle")), {})), n[0] if n else None, n[-1] if n else None])
        for sec in kids(ch, "Section"):
            n = nums(sec)
            rows.append(["  " + text_of(next(iter(kids(sec, "SectionTitle")), {})), n[0] if n else None, n[-1] if n else None])
            for sub in kids(sec, "Subsection"):
                n = nums(sub)
                rows.append(["    " + text_of(next(iter(kids(sub, "SubsectionTitle")), {})), n[0] if n else None, n[-1] if n else None])
    return rows


# 法令（略称, 法令名, 文書が書いた law_id）
LAWS = {
    "kokkyo": ("国家公務員共済組合法", "333AC0000000128"),
    "kokkyo-rei": ("国家公務員共済組合法施行令", "333CO0000000207"),
    "kokkyo-ki": ("国家公務員共済組合法施行規則", "333M50000040054"),
    "chikyo": ("地方公務員等共済組合法", "337AC0000000152"),
    "chikyo-rei": ("地方公務員等共済組合法施行令", "337CO0000000352"),
    "chikyo-kitei": ("地方公務員等共済組合法施行規程", "337M5000008A001"),
    "shigaku": ("私立学校教職員共済法", "328AC0000000245"),
    "shigaku-rei": ("私立学校教職員共済法施行令", "328CO0000000425"),
    "shigaku-ki": ("私立学校教職員共済法施行規則", "328M50000080028"),
    "kyuyo": ("一般職の職員の給与に関する法律", "325AC1000000095"),
    "kenpo": ("健康保険法", "211AC0000000070"),
    "kenpo-ki": ("健康保険法施行規則", "215M10000008036"),
    "chizei": ("地方税法", "325AC0000000226"),
    "chijiho": ("地方自治法", "322AC0000000067"),
    "jumin": ("住民基本台帳法", "342AC0000000081"),
    "shotoku": ("所得税法", "340AC0000000033"),
    "kokunen-rei": ("国民年金法施行令", "334CO0000000184"),
}
K3 = ["2025-10-01", "2026-04-01", TODAY]
C3 = ["2026-01-01", TODAY, "2027-01-01"]
ASOFS = {k: K3 for k in ("kokkyo", "kokkyo-rei", "kokkyo-ki", "chikyo", "chikyo-rei", "chikyo-kitei", "shigaku", "shigaku-rei", "shigaku-ki", "kenpo")}
ASOFS.update({"chizei": C3})
# 文書（[KY] §0.1、[SA2] §0、[MS-KY] §1.2）が書いた law_revision_id
CLAIMED_REV = {
    ("kokkyo", "2025-10-01"): "333AC0000000128_20250627_507AC0000000080",
    ("kokkyo", "2026-04-01"): "333AC0000000128_20260401_507AC0000000080",
    ("kokkyo", TODAY): "333AC0000000128_20261001_507AC0000000087",
    ("kokkyo-rei", "2025-10-01"): "333CO0000000207_20250905_507CO0000000314",
    ("kokkyo-rei", "2026-04-01"): "333CO0000000207_20260401_508CO0000000011",
    ("kokkyo-rei", TODAY): "333CO0000000207_20261001_508CO0000000310",
    ("kokkyo-ki", "2025-10-01"): "333M50000040054_20251001_507M60000040063",
    ("kokkyo-ki", "2026-04-01"): "333M50000040054_20260401_508M60000040011",
    ("kokkyo-ki", TODAY): "333M50000040054_20261001_508M60000040062",
    ("chikyo", "2025-10-01"): "337AC0000000152_20250620_507AC0000000074",
    ("chikyo", "2026-04-01"): "337AC0000000152_20260401_507AC0000000074",
    ("chikyo", TODAY): "337AC0000000152_20261001_507AC0000000087",
    ("chikyo-rei", "2025-10-01"): "337CO0000000352_20250905_507CO0000000315",
    ("chikyo-rei", "2026-04-01"): "337CO0000000352_20260401_508CO0000000078",
    ("chikyo-rei", TODAY): "337CO0000000352_20261001_508CO0000000311",
    ("chikyo-kitei", "2025-10-01"): "337M5000008A001_20251001_507M6000008A004",
    ("chikyo-kitei", "2026-04-01"): "337M5000008A001_20260401_508M6000008A002",
    ("chikyo-kitei", TODAY): "337M5000008A001_20261001_508M6000008A005",
    ("shigaku", "2025-10-01"): "328AC0000000245_20250620_507AC0000000074",
    ("shigaku", "2026-04-01"): "328AC0000000245_20260401_507AC0000000074",
    ("shigaku", TODAY): "328AC0000000245_20261001_507AC0000000087",
    ("shigaku-rei", "2025-10-01"): "328CO0000000425_20250601_507CO0000000193",
    ("shigaku-rei", "2026-04-01"): "328CO0000000425_20260401_508CO0000000011",
    ("shigaku-rei", TODAY): "328CO0000000425_20261001_508CO0000000312",
    ("shigaku-ki", "2025-10-01"): "328M50000080028_20250728_507M60000080017",
    ("shigaku-ki", "2026-04-01"): "328M50000080028_20260401_508M60000080017",
    ("shigaku-ki", TODAY): "328M50000080028_20261001_508M60000080031",
    ("kyuyo", TODAY): "325AC1000000095_20260401_507AC0000000089",
    ("kenpo", "2025-10-01"): "211AC0000000070_20250620_507AC0000000074",
    ("kenpo", "2026-04-01"): "211AC0000000070_20260401_507AC0000000087",
    ("kenpo", TODAY): "211AC0000000070_20261001_507AC0000000087",
    ("kenpo-ki", TODAY): "215M10000008036_20261001_508M60000100144",
    ("chizei", "2026-01-01"): "325AC0000000226_20260101_507AC0000000041",
    ("chizei", TODAY): "325AC0000000226_20261101_508AC0000000002",
    ("chizei", "2027-01-01"): "325AC0000000226_20270101_508AC0000000002",
    ("chijiho", TODAY): "322AC0000000067_20261102_508AC0000000062",
    ("jumin", TODAY): "342AC0000000081_20261024_508AC0000000066",
    ("shotoku", TODAY): "340AC0000000033_20261001_507AC0000000070",
}
CLAIMED_STATUS = {("chizei", "2026-01-01"): "PreviousEnforced", ("chizei", TODAY): "CurrentEnforced", ("chizei", "2027-01-01"): "UnEnforced"}
CLAIMED_AMEND = {("kokkyo", TODAY): ("令和七年法律第八十七号", "2026-10-01"), ("chizei", "2026-01-01"): ("令和七年法律第四十一号", "2026-01-01"),
                 ("chizei", TODAY): ("令和八年法律第二号", "2026-11-01"), ("chizei", "2027-01-01"): ("令和八年法律第二号", "2027-01-01"),
                 ("kokkyo", "2025-10-01"): (None, "2025-06-27"), ("kokkyo", "2026-04-01"): (None, "2026-04-01"),
                 ("kenpo-ki", TODAY): (None, "2026-10-01"), ("kyuyo", TODAY): (None, "2026-04-01"),
                 ("chijiho", TODAY): (None, "2026-11-02"), ("jumin", TODAY): (None, "2026-10-24"), ("shotoku", TODAY): (None, "2026-10-01")}

# 引用の照合：(ID, 略称, asof, 条, 項, 号, イロハ, 引用（「…」は省略）, 期待（True＝現れる / False＝現れない）, 文書の箇所)
Q = [
    # [KY] §1.1 国共済法
    ("E01", "kokkyo", TODAY, "2", 1, "二", None, "被扶養者　次に掲げる者（後期高齢者医療の被保険者…（以下「後期高齢者医療の被保険者等」という。）その他健康保険法…第三条第七項ただし書に規定する特別の理由がある者に準じて財務省令で定める者を除く。）で主として組合員（短期給付に関する規定の適用を受けないものを除く。以下この号において同じ。）の収入により生計を維持するものであつて、日本国内に住所を有するもの又は外国において留学をする学生その他の日本国内に住所を有しないが渡航目的その他の事情を考慮して日本国内に生活の基礎があると認められるものとして財務省令で定めるものをいう。", True, "KY§1.1"),
    ("E02", "kokkyo", TODAY, "2", 1, "二", "イ", "組合員の配偶者、子、父母、孫、祖父母及び兄弟姉妹", True, "KY§1.1"),
    ("E03", "kokkyo", TODAY, "2", 1, "二", "ロ", "組合員と同一の世帯に属する三親等内の親族でイに掲げる者以外のもの", True, "KY§1.1"),
    ("E04", "kokkyo", TODAY, "2", 1, "二", "ハ", "組合員の配偶者で届出をしていないが事実上婚姻関係と同様の事情にあるものの父母及び子並びに当該配偶者の死亡後におけるその父母及び子で、組合員と同一の世帯に属するもの", True, "KY§1.1"),
    ("E05", "kokkyo", TODAY, "2", 1, "二", "ハ", "引き続き", False, "KY§1.2"),
    ("E06", "kokkyo", TODAY, "2", 2, None, None, "前項第二号の規定の適用上主として組合員の収入により生計を維持することの認定…に関し必要な事項は、政令で定める。", True, "KY§1.1"),
    ("E07", "kokkyo", TODAY, "2", 4, None, None, "この法律において、「配偶者」、「夫」及び「妻」には、婚姻の届出をしていないが、事実上婚姻関係と同様の事情にある者を含むものとする。", True, "KY§1.1"),
    ("E08", "kokkyo", TODAY, "53", 2, None, None, "被扶養者に係る短期給付は、新たに組合員となつた者に被扶養者となるべき者がある場合にはその者が組合員となつた日から、組合員に前項第一号に該当する事実が生じた場合にはその事実が生じた日から、それぞれ行うものとする。ただし、同項（第二号を除く。）の規定による届出がその組合員となつた日又はその事実の生じた日から三十日以内にされない場合には、その届出を受けた日から行うものとする。", True, "KY§7"),
    ("E09", "kokkyo", TODAY, None, None, None, None, "日本郵政共済組合", True, "（YUSEI が国共済法の組合か）"),
    # 地共済法
    ("E10", "chikyo", TODAY, "2", 1, "二", None, "主務省令で定める者を除く。）で主として組合員（短期給付に関する規定の適用を受けないものを除く。以下この号において同じ。）の収入により生計を維持するもの", True, "KY§1.1"),
    ("E11", "chikyo", TODAY, "2", 1, "二", None, "財務省令", False, "KY§1.1"),
    ("E12", "chikyo", TODAY, "2", 1, "二", "ロ", "組合員と同一世帯に属する三親等内の親族", True, "KY§1.1"),
    ("E13", "chikyo", TODAY, "2", 1, "二", "ロ", "同一の世帯", False, "KY§1.1"),
    ("E14", "chikyo", TODAY, "2", 1, "二", "ハ", "組合員と同一の世帯に属するもの", True, "KY§1.1"),
    ("E15", "chikyo", TODAY, "2", 2, None, None, "政令で定める", True, "KY§1.1"),
    ("E16", "chikyo", TODAY, "2", 4, None, None, "婚姻の届出をしていないが、事実上婚姻関係と同様の事情にある者を含む", True, "KY§1.1"),
    ("E17", "chikyo", TODAY, "55", 2, None, None, "三十日以内にされない場合には、その届出を受けた日から行うものとする。", True, "KY§7"),
    ("E18", "chikyo", TODAY, "3", None, None, None, "警察共済組合", True, "（KEISATSU が地共済法の組合か）"),
    # 私学法
    ("E19", "shigaku", TODAY, "25", 1, None, None, "この節に規定するもののほか、短期給付及び退職等年金給付については、国家公務員共済組合法第二条（第一項第一号及び第五号から第七号までを除く。）、第四章（…第四十九条から第五十一条まで…第三節第一款及び第二款…）…の規定を準用する。この場合において、これらの規定（…）中「組合員」とあるのは「加入者」と", True, "KY§1.1"),
    ("E20", "shigaku", TODAY, "25", 1, None, None, "（私立学校教職員共済法第十四条第一項に規定する加入者をいう。以下同じ。）（短期給付", True, "KY§1.1"),
    # 健保法
    ("E21", "kenpo", TODAY, "3", 7, None, None, "この法律において「被扶養者」とは、次に掲げる者で、日本国内に住所を有するもの又は…厚生労働省令で定めるものをいう。ただし、後期高齢者医療の被保険者等である者その他この法律の適用を除外すべき特別の理由がある者として厚生労働省令で定める者は、この限りでない。", True, "KY§1.1"),
    ("E22", "kenpo", TODAY, "3", 7, "一", None, "被保険者（日雇特例被保険者であった者を含む。…）の直系尊属、配偶者（届出をしていないが、事実上婚姻関係と同様の事情にある者を含む。…）、子、孫及び兄弟姉妹であって、主としてその被保険者により生計を維持するもの", True, "KY§1.1"),
    ("E23", "kenpo", TODAY, "3", 7, "二", None, "被保険者の三親等内の親族で前号に掲げる者以外のものであって、その被保険者と同一の世帯に属し、主としてその被保険者により生計を維持するもの", True, "KY§1.1"),
    ("E24", "kenpo", TODAY, "3", 7, "三", None, "被保険者の配偶者で届出をしていないが事実上婚姻関係と同様の事情にあるものの父母及び子であって、その被保険者と同一の世帯に属し、", True, "KY§1.1"),
    ("E25", "kenpo", TODAY, "3", 7, "四", None, "前号の配偶者の死亡後におけるその父母及び子であって、引き続きその被保険者と同一の世帯に属し、", True, "KY§1.1"),
    # 施行令第3条
    ("E26", "kokkyo-rei", TODAY, "3", 1, None, None, "法第二条第一項第二号に規定する主として組合員の収入により生計を維持することの認定に関しては、一般職の職員の給与に関する法律（昭和二十五年法律第九十五号）第十一条第二項に規定する扶養親族に係る扶養の事実の認定の例及び健康保険法（大正十一年法律第七十号）における被扶養者の認定の取扱いを参酌して、財務大臣の定めるところによる。", True, "KY§2"),
    ("E27", "chikyo-rei", TODAY, "3", 1, None, None, "第十一条第二項に規定する扶養親族に係る扶養の事実の認定の例及び健康保険法（大正十一年法律第七十号）における被扶養者の認定の取扱いを参酌して、総務大臣の定めるところによる。", True, "KY§2"),
    ("E28", "shigaku-rei", TODAY, "3", 1, None, None, "法第二十五条において準用する組合法第二条第一項第二号に規定する主として加入者の収入により生計を維持することの認定に関しては、…を参酌して、文部科学大臣が定めるところによる。", True, "KY§2"),
    ("E29", "shigaku-rei", TODAY, "3", 1, None, None, "第十一条第二項", True, "KY§2（給与法11②の参酌）"),
    # 一般職給与法第11条第2項
    ("E30", "kyuyo", TODAY, "11", 2, None, None, "扶養手当の支給については、次に掲げる者で他に生計の途がなく主としてその職員の扶養を受けているものを扶養親族とする。", True, "KY§2"),
    ("E31", "kyuyo", TODAY, "11", 2, "一", None, "満二十二歳に達する日以後の最初の三月三十一日までの間にある子", True, "KY§2"),
    ("E32", "kyuyo", TODAY, "11", 2, "二", None, "満二十二歳に達する日以後の最初の三月三十一日までの間にある孫", True, "KY§2"),
    ("E33", "kyuyo", TODAY, "11", 2, "三", None, "満六十歳以上の父母及び祖父母", True, "KY§2"),
    ("E34", "kyuyo", TODAY, "11", 2, "四", None, "満二十二歳に達する日以後の最初の三月三十一日までの間にある弟妹", True, "KY§2"),
    ("E35", "kyuyo", TODAY, "11", 2, "五", None, "重度心身障害者", True, "KY§2"),
    ("E36", "kyuyo", TODAY, "11", 2, None, None, "配偶者", False, "KY§2（この版では配偶者は列挙にない）"),
    # 除外・国内居住の例外
    ("E37", "kokkyo-ki", TODAY, "2_5", 1, "一", None, "日本の国籍を有しない者であつて", True, "KY§1.2"),
    ("E38", "kokkyo-ki", TODAY, "2_5", 1, "二", None, "日本の国籍を有しない者であつて…観光、保養その他これらに類似する活動を行うもの", True, "KY§1.2"),
    ("E39", "kokkyo-ki", TODAY, "2_5", 2, "一", None, "外国において留学をする学生", True, "KY§1.2"),
    ("E40", "kokkyo-ki", TODAY, "2_5", 2, "二", None, "外国に赴任する組合員に同行する者", True, "KY§1.2、IKY10"),
    ("E41", "kokkyo-ki", TODAY, "2_5", 2, "五", None, "前各号に掲げる者のほか、渡航目的その他の事情を考慮して日本国内に生活の基礎があると認められる者", True, "KY§1.2"),
    ("E42", "chikyo-kitei", TODAY, "2_3", 1, "二", None, "日本の国籍を有しない者であつて…観光、保養その他これらに類似する活動を行うもの", True, "KY§1.2"),
    ("E43", "chikyo-kitei", TODAY, "2_3", 2, "五", None, "日本国内に生活の基礎があると認められる者", True, "KY§1.2"),
    ("E44", "shigaku-ki", TODAY, "1_4_2", 1, "二", None, "日本の国籍を有しない者であつて…観光、保養その他これらに類似する活動を行うもの", True, "KY§1.2"),
    ("E45", "shigaku-ki", TODAY, "1_4_2", 2, "五", None, "日本国内に生活の基礎があると認められる者", True, "KY§1.2"),
    ("E46", "kenpo-ki", TODAY, "37_2", None, None, None, "外国において留学をする学生…外国に赴任する被保険者に同行する者…観光、保養又はボランティア活動その他就労以外の目的で一時的に海外に渡航する者…被保険者が外国に赴任している間に当該被保険者との身分関係が生じた者…渡航目的その他の事情を考慮して日本国内に生活の基礎があると認められる者", True, "KY§1.2"),
    ("E47", "kenpo-ki", TODAY, "37_3", None, None, None, "日本の国籍を有しない者であって", True, "KY§1.2（健保則は「って」の表記）"),
    # 届出の期限・記載事項
    ("E48", "kokkyo-ki", TODAY, "88", 1, None, None, "当該事実が生じた日から五日以内", True, "KY§7"),
    ("E49", "kokkyo-ki", TODAY, "88", 1, "二", None, "氏名…、性別、生年月日、職業、年間所得推計額、住所及び個人番号並びにその者と組合員との続柄", True, "KY§7"),
    ("E50", "kokkyo-ki", TODAY, "88", 1, "二", None, "身分関係", False, "KY§7（国共済則の第2号は「続柄」で「身分関係」の語はない）"),
    ("E51", "chikyo-kitei", TODAY, "94", 1, "二", None, "氏名…、性別、生年月日、職業、年間所得推計額、住所及び個人番号並びにその者と組合員との身分関係", True, "KY§7"),
    ("E52", "kokkyo-ki", TODAY, "88", 1, "三", None, "被扶養者の要件を備えるに至つた年月日又は被扶養者の要件を欠くに至つた年月日及びその理由", True, "KY§7"),
    ("E53", "chikyo-kitei", TODAY, "94", 1, None, None, "当該事実が生じた日から五日以内", True, "KY§7"),
    ("E54", "shigaku-ki", TODAY, "1_5", 1, None, None, "五日以内", True, "KY§7"),
    ("E55", "shigaku-ki", TODAY, "1_5", 2, None, None, "五日以内", True, "KY§7"),
    ("E56", "kenpo-ki", TODAY, "38", 1, None, None, "五日以内", True, "KY§7"),
    ("E57", "chikyo-kitei", TODAY, "97", 1, None, None, "組合は、組合の定めるところにより、資格確認書の検認若しくは更新又は被扶養者に係る確認をするものとする。", True, "KY§7"),
    ("E58", "chikyo-kitei", TODAY, "100", 1, None, None, "削除", True, "MS-KY§3"),
    ("E59", "kenpo-ki", TODAY, "50", 1, None, None, "できる", True, "KY§7（健保則50①は「できる」）"),
    # 国民年金法施行令第4条（[KY] 冒頭の [CON] の引用）
    ("E60", "kokunen-rei", TODAY, "4", None, None, None, "国家公務員共済組合法、地方公務員等共済組合法及び私立学校教職員共済法における被扶養者の認定の取扱いを勘案して", False, "KY 冒頭（[KY] の引用。原文は法律番号の括弧書きを挟むので、この形では現れない）"),
    ("E60b", "kokunen-rei", TODAY, "4", None, None, None, "健康保険法（大正十一年法律第七十号）、国家公務員共済組合法（昭和三十三年法律第百二十八号）、地方公務員等共済組合法及び私立学校教職員共済法における被扶養者の認定の取扱いを勘案して日本年金機構（以下「機構」という。）が行う。", True, "KY 冒頭（原文）"),
    # [SA2] §4 地方税法・地方自治法・住基法・所得税法
    ("E61", "chizei", TODAY, "294", 1, None, None, "市町村民税は、第一号の者に対しては均等割額及び所得割額の合算額により、…第二号及び第四号の者に対しては均等割額により…課する。", True, "SA2§4.1"),
    ("E62", "chizei", TODAY, "294", 1, "一", None, "市町村内に住所を有する個人", True, "SA2§4.1"),
    ("E63", "chizei", TODAY, "294", 1, "二", None, "市町村内に事務所、事業所又は家屋敷を有する個人で当該市町村内に住所を有しない者", True, "SA2§4.1"),
    ("E64", "chizei", TODAY, "294", 2, None, None, "前項第一号の市町村内に住所を有する個人とは、住民基本台帳法の適用を受ける者については、当該市町村の住民基本台帳に記録されている者をいう。", True, "SA2§4.1"),
    ("E65", "chizei", TODAY, "294", 3, None, None, "市町村は、当該市町村の住民基本台帳に記録されていない個人が当該市町村内に住所を有する者である場合には、その者を当該住民基本台帳に記録されている者とみなして、その者に市町村民税を課することができる。この場合において、市町村長は、その者が他の市町村の住民基本台帳に記録されていることを知つたときは、その旨を当該他の市町村の長に通知しなければならない。", True, "SA2§4.1"),
    ("E66", "chizei", TODAY, "294", 4, None, None, "前項の規定により市町村民税を課された者に対しては、その者が記録されている住民基本台帳に係る市町村は、第二項の規定にかかわらず、市町村民税を課することができない。", True, "SA2§4.1"),
    ("E67", "chizei", TODAY, "318", None, None, None, "個人の市町村民税の賦課期日は、当該年度の初日の属する年の一月一日とする。", True, "SA2§4.1"),
    ("E68", "chizei", TODAY, "24", 1, "一", None, "道府県内に住所を有する個人", True, "SA2§4.1"),
    ("E69", "chizei", TODAY, "24", 1, "二", None, "道府県内に事務所、事業所又は家屋敷を有する個人で当該事務所、事業所又は家屋敷を有する市町村内に住所を有しない者", True, "SA2§4.1"),
    ("E70", "chijiho", TODAY, "10", 1, None, None, "市町村の区域内に住所を有する者は、当該市町村及びこれを包括する都道府県の住民とする。", True, "SA2§4.1"),
    ("E71", "jumin", TODAY, "4", None, None, None, "住民の住所に関する法令の規定は、地方自治法…第十条第一項に規定する住民の住所と異なる意義の住所を定めるものと解釈してはならない。", True, "SA2§4.1"),
    ("E72", "shotoku", TODAY, "3", 1, None, None, "国家公務員又は地方公務員（これらのうち日本の国籍を有しない者その他政令で定める者を除く。）は、国内に住所を有しない期間についても国内に住所を有するものとみなして、この法律（第十条（障害者等の少額預金の利子所得等の非課税）、第十五条（納税地）及び第十六条（納税地の特例）を除く。）の規定を適用する。", True, "SA2§4.2"),
    ("E73", "chizei", "2026-01-01", "292", 1, "九", None, "市町村民税の納税義務者の親族（その納税義務者の配偶者を除く。）並びに…その納税義務者と生計を一にするもの（…）のうち、前年の合計所得金額が五十八万円以下である者をいう。", True, "SA2§4.3"),
    ("E74", "chizei", TODAY, "292", 1, "九", None, "前年の合計所得金額が五十八万円以下である者", True, "SA2§4.3"),
    ("E75", "chizei", "2027-01-01", "292", 1, "九", None, "前年の合計所得金額が六十二万円以下である者", True, "SA2§4.3"),
    ("E76", "chizei", TODAY, "292", 1, "九", None, "住所", False, "SA2§4.3"),
    ("E77", "chizei", TODAY, "292", 1, "九", None, "同居", False, "SA2§4.3"),
    ("E78", "chizei", TODAY, "314_2", 3, None, None, "所得割の納税義務者の有する同一生計配偶者又は扶養親族が特別障害者で、かつ、当該納税義務者又は当該納税義務者の配偶者若しくは当該納税義務者と生計を一にするその他の親族のいずれかとの同居を常況としている者…である場合には、当該特別障害者に係る第一項第六号の金額は、五十三万円とする。", True, "SA2§4.3"),
    ("E79", "chizei", TODAY, "314_2", 4, None, None, "所得割の納税義務者の有する老人扶養親族が当該納税義務者又は当該納税義務者の配偶者の直系尊属で、かつ、当該納税義務者又は当該配偶者のいずれかとの同居を常況としている者…である場合には、当該老人扶養親族に係る第一項第十一号の金額は、四十五万円とする。", True, "SA2§4.3、IKY9"),
    ("E80", "chizei", TODAY, "314_2", 1, "十一", None, "老人扶養親族", True, "IKY9（同居でなければの額）"),
    ("E81", "chizei", "2026-01-01", "317_2", 1, None, None, "賦課期日現在における住所所在地の市町村長に", True, "SA2§4.4"),
    ("E82", "chizei", "2026-01-01", "317_6", 1, None, None, "一月一日現在において給与の支払をする者…当該給与の支払を受けている者の同月一日現在における住所所在の市町村別に作成された給与支払報告書", True, "SA2§4.4"),
    ("E83", "chizei", "2026-11-09", "314_2", 1, "十一", None, "以下この款及び第三百十七条の三の三第一項において同じ。", True, "MS-KY§1.3（2026-11-09 版での追加）"),
    ("E84", "chizei", "2026-01-01", "314_2", 1, "十一", None, "以下この款及び第三百十七条の三の三第一項において同じ。", False, "MS-KY§1.3（2026-01-01 版にはない）"),
]

# 条文を抜き出して保存し、版の差分を数える条
SAVE_ARTS = {
    "kokkyo": ["2", "3", "53"], "kokkyo-rei": ["1", "3"], "kokkyo-ki": ["2", "2_5", "88"], "chikyo": ["2", "3", "55"],
    "chikyo-rei": ["3"], "chikyo-kitei": ["2", "2_3", "94", "97", "100"], "shigaku": ["14", "25"], "shigaku-rei": ["3"],
    "shigaku-ki": ["1_4_2", "1_5"], "kyuyo": ["11"], "kenpo": ["3"], "kenpo-ki": ["37_2", "37_3", "38", "50"],
    "chizei": ["23", "24", "39", "292", "294", "314_2", "317_2", "317_6", "318"], "chijiho": ["10"], "jumin": ["4", "6", "7"],
    "shotoku": ["3"], "kokunen-rei": ["4"],
}


def lookup_law_id(title, dl, i):
    q = urllib.parse.urlencode({"law_title": title, "response_format": "json", "asof": TODAY})
    st, _, _, body = http_get(f"{API}/laws?{q}", "application/json")
    (dl / f"lookup_{i:02d}.json").write_bytes(body)
    if st != 200:
        return None, st
    found = []
    for law in json.loads(body).get("laws", []):
        rv = law.get("current_revision_info") or law.get("revision_info") or {}
        if rv.get("law_title") == title:
            found.append(law["law_info"]["law_id"])
    return found, st


def check_quotes(fulls):
    out = []
    for qid, short, asof, art, para, item, sub, quote, expect, where in Q:
        full = fulls.get((short, asof))
        if full is None:
            out.append({"id": qid, "where": where, "error": "not fetched"})
            continue
        if art is None:
            node_text = text_of(full)
        else:
            nd = node_at(full, art, para, item, sub)
            node_text = text_of(nd) if nd is not None else ""
        found, missing = has_quote(node_text, quote)
        out.append({"id": qid, "law": short, "asof": asof, "at": [art, para, item, sub], "where": where,
                    "expect": expect, "found": found, "ok": found == expect, "first_missing_fragment": missing,
                    "node_found": bool(node_text)})
    return out


def recheck_egov():
    """ネットワークに出ず、egov.json に記録した取得ディレクトリの JSON で引用の照合だけをやり直す。"""
    res = json.loads((OUT / "egov.json").read_text(encoding="utf-8"))
    dl = ROOT / res["download_dir"]
    fulls = {}
    for f in res["fetches"]:
        if f.get("status") == 200:
            fulls[(f["short"], f["asof"])] = json.loads((dl / f"{f['short']}_{f['asof']}.json").read_bytes())["law_full_text"]
    res["quotes"] = check_quotes(fulls)
    res["rechecked_at"] = time.strftime("%Y%m%d-%H%M%S")
    (OUT / "egov.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    bad = [q for q in res["quotes"] if not q.get("ok")]
    print("quotes:", len(res["quotes"]), "not ok:", [(q["id"], q.get("first_missing_fragment")) for q in bad])


def run_egov():
    ts, dl = new_dl("egov")
    (OUT / "articles").mkdir(parents=True, exist_ok=True)
    res = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "laws": {}, "fetches": [], "quotes": [], "diffs": {}, "toc": {}}
    fulls = {}
    for i, (short, (title, claimed_id)) in enumerate(LAWS.items()):
        ids, st = lookup_law_id(title, dl, i)
        res["laws"][short] = {"title": title, "claimed_law_id": claimed_id, "lookup_status": st, "found_ids": ids,
                              "law_id_ok": bool(ids) and claimed_id in ids}
        for asof in ASOFS.get(short, [TODAY]):
            q = urllib.parse.urlencode({"response_format": "json", "asof": asof})
            url = f"{API}/law_data/{claimed_id}?{q}"
            st, _, _, body = http_get(url, "application/json")
            dest = dl / f"{short}_{asof}.json"
            dest.write_bytes(body)
            rec = {"short": short, "asof": asof, "url": url, "status": st, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
            if st == 200:
                d = json.loads(body)
                ri = d.get("revision_info") or {}
                rec.update({k: ri.get(k) for k in ("law_revision_id", "amendment_law_num", "amendment_enforcement_date", "current_revision_status")})
                c = CLAIMED_REV.get((short, asof))
                rec["claimed_rev"] = c
                rec["rev_ok"] = (c is None) or (c == ri.get("law_revision_id"))
                if (short, asof) in CLAIMED_STATUS:
                    rec["status_claimed"] = CLAIMED_STATUS[(short, asof)]
                    rec["status_ok"] = CLAIMED_STATUS[(short, asof)] == ri.get("current_revision_status")
                if (short, asof) in CLAIMED_AMEND:
                    num, date = CLAIMED_AMEND[(short, asof)]
                    rec["amend_claimed"] = [num, date]
                    rec["amend_ok"] = ((num is None or num == ri.get("amendment_law_num")) and date == ri.get("amendment_enforcement_date"))
                full = d["law_full_text"]
                fulls[(short, asof)] = full
                arts = main_articles(full)
                txt = [f"# {title} {claimed_id} asof={asof} law_revision_id={ri.get('law_revision_id')} 状態={ri.get('current_revision_status')}", f"# {url}", ""]
                for n in SAVE_ARTS.get(short, []):
                    a = arts.get(n)
                    txt += [f"## Num={n}", render_article(a) if a is not None else "(この時点の本則にない)", ""]
                (OUT / "articles" / f"{short}_{asof}.txt").write_text("\n".join(txt), encoding="utf-8")
            res["fetches"].append(rec)
            print("egov", short, asof, st, rec.get("law_revision_id"), "rev_ok" if rec.get("rev_ok") else "REV?", flush=True)
    res["quotes"] = check_quotes(fulls)
    # 版の差分（SAVE_ARTS の範囲の行の数）
    for short, asofs in ASOFS.items():
        for x, y in zip(asofs, asofs[1:]):
            if (short, x) not in fulls or (short, y) not in fulls:
                continue
            per_art = {}
            for n in SAVE_ARTS.get(short, []):
                ax, ay = main_articles(fulls[(short, x)]).get(n), main_articles(fulls[(short, y)]).get(n)
                tx = render_article(ax).splitlines() if ax is not None else []
                ty = render_article(ay).splitlines() if ay is not None else []
                dl_ = [ln for ln in difflib.unified_diff(tx, ty, lineterm="", n=0) if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]
                if dl_:
                    per_art[n] = dl_
            res["diffs"][f"{short} {x}->{y}"] = {"changed_articles": sorted(per_art), "n_lines": sum(len(v) for v in per_art.values()),
                                                 "lines": {k: [s[:400] for s in v] for k, v in per_art.items()}}
    # 国共済法の章・節・款の範囲
    if ("kokkyo", TODAY) in fulls:
        res["toc"]["kokkyo"] = toc_ranges(fulls[("kokkyo", TODAY)])
    # 元の担当の取得記録と SHA-256 を比べる
    prev = ROOT / "scripts" / "results" / "R2X_kyosai_egov" / "fetch_log_full.json"
    if prev.exists():
        pl = json.loads(prev.read_text(encoding="utf-8"))
        pm = {(f["short"], f["asof"]): f for f in pl.get("fetches", [])}
        res["compare_prev"] = []
        for f in res["fetches"]:
            p = pm.get((f["short"], f["asof"]))
            if p:
                res["compare_prev"].append({"short": f["short"], "asof": f["asof"], "same_sha256": p.get("sha256") == f.get("sha256"),
                                            "same_rev": p.get("law_revision_id") == f.get("law_revision_id"),
                                            "prev_sha12": (p.get("sha256") or "")[:12], "mine_sha12": (f.get("sha256") or "")[:12]})
    (OUT / "egov.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    bad = [q for q in res["quotes"] if not q.get("ok")]
    print("quotes:", len(res["quotes"]), "not ok:", [(q["id"], q.get("first_missing_fragment")) for q in bad])
    print("rev not ok:", [(f["short"], f["asof"], f.get("law_revision_id")) for f in res["fetches"] if f.get("rev_ok") is False])
    print("amend not ok:", [(f["short"], f["asof"], f.get("amendment_law_num"), f.get("amendment_enforcement_date")) for f in res["fetches"] if f.get("amend_ok") is False])
    print("status not ok:", [(f["short"], f["asof"], f.get("current_revision_status")) for f in res["fetches"] if f.get("status_ok") is False])
    print("law_id not ok:", [k for k, v in res["laws"].items() if not v["law_id_ok"]])


def run_egov_extra():
    """推測（IKY9）が検証先として挙げた条番号（租税特別措置法第41条の16：所得税の同居老親等）の見出しと文言を確かめる。"""
    ts, dl = new_dl("egovextra")
    law_id, asof = "332AC0000000026", TODAY
    url = f"{API}/law_data/{law_id}?" + urllib.parse.urlencode({"response_format": "json", "asof": asof})
    st, _, _, body = http_get(url, "application/json")
    (dl / f"sochi_{asof}.json").write_bytes(body)
    res = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "url": url, "status": st, "sha256": hashlib.sha256(body).hexdigest()}
    if st == 200:
        d = json.loads(body)
        ri = d.get("revision_info") or {}
        res["law_revision_id"] = ri.get("law_revision_id")
        a = main_articles(d["law_full_text"]).get("41_16")
        txt = render_article(a) if a is not None else ""
        (OUT / "articles").mkdir(parents=True, exist_ok=True)
        (OUT / "articles" / f"sochi_{asof}.txt").write_text(chr(10).join([f"# 租税特別措置法 {law_id} asof={asof} law_revision_id={ri.get('law_revision_id')}", "## Num=41_16", txt, ""]), encoding="utf-8")
        res["41_16_caption"] = txt.splitlines()[0] if txt else None
        for q in ("同居を常況としている者", "老人扶養親族", "直系尊属", "居住者又はその配偶者"):
            res[f"has:{q}"] = has_quote(text_of(a) if a is not None else "", q)[0]
    (OUT / "egov_extra.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- 公表資料（HTML の引用、PDF の版）
class Text(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self._skip, self.title, self._t = [], 0, "", False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        if tag == "title":
            self._t = True
        if tag in ("br", "p", "div", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "dt", "dd"):
            self.parts.append("\n")
        a = dict(attrs)
        if tag == "img" and a.get("alt") and not self._skip:
            self.parts.append(a["alt"])

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._t = False

    def handle_data(self, data):
        if self._t:
            self.title += data
        if not self._skip:
            self.parts.append(data)


def decode(body, ctype):
    m = re.search(r"charset=([\w\-]+)", ctype or "", re.I) or re.search(rb"<meta[^>]+charset=[\"']?([\w\-]+)", body[:4000], re.I)
    cs = None
    if m:
        cs = m.group(1) if isinstance(m.group(1), str) else m.group(1).decode("ascii", "replace")
    for c in [cs, "utf-8", "cp932", "euc-jp"]:
        if c:
            try:
                return body.decode(c)
            except (LookupError, UnicodeDecodeError):
                pass
    return body.decode("utf-8", "replace")


# (ID, URL, [ (引用, 期待, 文書の箇所) ... ])
WEB = [
    ("MOF-S", "https://www.mof.go.jp/about_mof/act/kokuji_tsuutatsu/tsuutatsu/tsuutatsu_s.htm", [
        ("蔵計第2927号", True, "KY§0.2・MS-KY§2.2"), ("国家公務員共済組合法等の運用方針", True, "KY§0.2"), ("主計局給与共済課共済係", True, "MS-KY§2.2"),
        ("TU-19591001-2927-11.pdf", True, "MS-KY§2.2（リンク先は HTML の属性。下の links で確かめる）")]),
    ("MOF-R", "https://www.mof.go.jp/about_mof/act/kokuji_tsuutatsu/tsuutatsu/tsuutatsu_r.htm", [
        ("財計第4707号", True, "MS-KY§2.2"), ("国家公務員等の旅費に関する法律等の運用方針について", True, "MS-KY§2.2"),
        ("財計第1487号", True, "MS-KY§2.2"), ("財計第1486号", True, "MS-KY§2.2"), ("財計第4140号", False, "KY§3.3（改正通達の行はない）"),
        ("財計第3570号", False, "KY§3.3"), ("蔵計第2927号", False, "KY§3.3")]),
    ("UNYO-K-H27", "http://mofkyosai.gijiroku.com/mofqa/reg_view_honbun.asp?RMODE=1&ISrchID=155", [
        ("平成27年4月1日財計第1382号", True, "KY§0.2"), ("国家公務員共済組合法等の運用方針", True, "KY§0.2")]),
    ("KKR", "https://www.kkr.or.jp/", []),
    ("CHIKYO-HQ", "https://www.chikyosai.or.jp/division/short/02.html", [
        ("令和7年10月1日", True, "KY§4"), ("150万円", True, "KY§4")]),
    ("NAGASAKI-LAW", "https://nagasaki.chikyosai.or.jp/about/law/", [
        ("地方公務員等共済組合法運用方針（昭和37年自治甲公第10号）", True, "KY§4")]),
    ("KOURITU-19-23", "https://www.kouritu.or.jp/topics/kumiai/fuyou_20250812/index.html", [
        ("令和7年中の基準額が150万円未満となるのは、誕生日が平成15年1月2日から平成19年1月1日までの方です", True, "KY§3.2"),
        ("令和7年10月1日", True, "KY§0.2"), ("12月31日", True, "KY§3.2")]),
    ("KOURITU-REI-S", "https://www.kouritu.or.jp/shizuoka/tetsuduki/kyosai/hifuyo/rei/shinzoku/index.html", [
        ("一時的な別居とは、2か月あるいは1年という具体的な期間を指すものではなく、今まで同居し扶養関係のあった者が、組合員の転勤等のため、同居をする意志がありながら勤務の都合上別居を余儀なくされるような場合で、実態についてみれば扶養関係が継続し、別居を余儀なくさせた原因が組合員の転勤等やむを得ない事由によるものである場合を指す。", True, "SA2§1.2"),
        ("組合員の転勤等のため同一世帯に属することを要件とされている被扶養者と別居することとなった者のうち、引き続き同居できない理由が、勤務先の住居の狭あい、被扶養者の療養上の問題、被扶養者の通学上の問題で真にやむを得ないと認められる場合は、生計維持関係を有している限り、継続して認定して差し支えない。", True, "SA2§1.2"),
        ("同居を要する親族が、大学等に在学するため組合員と別居を余儀なくされ、勉学に必要な生活費や教育費を組合員が負担し、主として組合員の収入によっている場合であっても、組合員の転勤等組合員自身の勤務の都合上別居を余儀なくされた場合を除き、被扶養者として認定することはできない。", True, "SA2§1.2"),
        ("勉学のため別居中の組合員の甥が、1年のうち夏休み、冬休み、試験休みと約4か月帰省し", True, "SA2§1.2"),
        ("この者の帰省中の期間だけを限って被扶養者として認定することはできない", True, "SA2§1.2"),
        ("更新日: 2021年04月01日", True, "KY§0.2（更新日）")]),
    ("KOURITU-REI-F", "https://www.kouritu.or.jp/shizuoka/tetsuduki/kyosai/hifuyo/rei/fubo/index.html", [
        ("官署を異にする異動等に伴い、組合員が同居していた被扶養者である父母等と一時的に別居することとなった場合の当該父母等（組合員の配偶者又は子と同居している父母等に限る。）に係る被扶養者の認定に当たっては、別居後も扶養の実態等に特段の変化がない限り、引き続き組合員と同居しているものとして取り扱うものとする。", True, "SA2§1.2"),
        ("3分の1以上", True, "SA2§2"), ("超える", True, "SA2§2（送金等の負担額が父母等の収入を超える）"), ("更新日: 2021年04月01日", True, "KY§0.2（更新日）")]),
    ("KOURITU-HIRO", "https://www.kouritu.or.jp/hiroshima/tetsuduki/kyosai/fuyosha/syunyuhanteisheet/index.html", [
        ("年額(12か月)の判定は、暦年ではありません。", True, "KY§6.4"),
        ("認定日以後、どの12か月の累計が130万円を超えても超えた月の初日で認定取消しとなります。", True, "KY§6.4"),
        ("月額108,334円以上が4か月連続すると、4か月目の初日で被扶養者認定を取り消し", True, "KY§6.4"),
        ("課税、非課税にかかわらず、通勤手当は全額を収入に含めて判定", True, "KY§6.2"),
        ("更新日: 2024年01月12日", True, "KY§0.2（更新日）"), ("150万", False, "KY§0.2（150万円の記載なし）")]),
    ("FUKUOKA-KIJUN", "https://fukuoka-kyosai.jp/reiki_int/reiki_honbun/x650RG00000067.html", [
        ("地方公務員等共済組合法運用方針(昭和37年10月3日自治甲公10)", True, "KY§4"),
        ("被扶養者の認定基準に関しては、各保険者の裁量に委ねられており、本基準は、その他の組合(地方職員、公立学校職員、警察職員、国家公務員、各指定都市職員、各都市職員又は各県市町村職員の共済組合)の取扱いとは異なる場合がある。", True, "KY§6"),
        ("諸手当(通勤手当等を含む。)", True, "KY§6.2"),
        ("「組合員と同一の世帯に属する」とは、組合員と生計を共にし、かつ、同居している場合をいう。この場合において、次に掲げる場合は、組合員と同一の世帯に属するものに準じて取り扱う。なお、二世帯住宅や同一敷地内に親世帯の家と子世帯の家がある場合等日常生活において自立した生活を営む居住形態は、同一世帯に属するものには該当しない。", True, "SA2§1.2"),
        ("病院勤務の看護師のように勤務上別居を要する場合若しくはこれに準ずる場合又は転勤等に際して自己の都合により一時的に別居を余儀なくされる場合", True, "SA2§1.2"),
        ("組合員と同居していた者が、医療機関への長期入院や出産のための帰省等生活の本拠は自宅であるが、やむを得ない事情により一時的に別居している場合", True, "SA2§1.2"),
        ("仕送り額は、別居の認定対象者の収入(組合員以外の者からの仕送り等を含む。)以上かつ年間合計65万円以上の金額であることを条件とする。", True, "SA2§2"),
        ("仕送り後の組合員世帯と認定対象者世帯の1人当たり平均生計費が逆転する場合は、原則として認定できない。", True, "SA2§2"),
        ("仕送り方法は、金融機関からの振込みとし、現金の手渡しや現物(食料、衣料等)を渡すことによる方法は、認められない。", True, "SA2§2"),
        ("毎月一定額を送金することを原則とする。", True, "SA2§2"),
        ("確定申告を行うことにより確定した事業の総収入から、その収入を得るために必要不可欠であると組合が認める経費(別表第3)を控除した額を、今後1年間に見込まれる事業収入とし、その額が収入基準額以上であり、今後も同程度の収入が見込まれる場合は、恒常的に基準額を超える収入があるものとみなす。この場合において、原則として、確定申告の受付締切日である3月15日をもって被扶養者の資格を取り消す。", True, "KY§6.3"),
        ("事業開始時点や事業の拡大、相続等、明らかに収入基準額以上となることが予測できた場合は、その時点をもって被扶養者の資格を取り消す。", True, "KY§6.3"),
        ("パート、アルバイト等月々の給与収入が変動する場合は、連続する3か月の平均給与月額が月額基準額以上となったときは、恒常的に基準額を超える収入があるものとみなす。", True, "KY§6.4"),
        ("当該3か月を含む今後1年間の収入が収入基準額以上とならないことが明らかである場合は、この限りでない。", True, "KY§6.4"),
        ("直近1年間の給与収入が収入基準額未満である月が3回連続した場合", True, "KY§6.4"),
        ("従業員を雇い、1人に対し年間130万円以上の給料賃金又は雇人費を経費として支出しているときは", True, "KY§6.3"),
        ("同居の親族に対する給料賃金は、原則必要経費とは認めない", True, "KY§6.3"),
        ("地代家賃、水道光熱費、通信費については事業分と家計消費分とが明確に区分されている場合のみ認める", True, "KY§6.3"),
        ("訪問販売における旅費交通費など職種によって認める場合もある", True, "KY§6.3"),
        ("被扶養者の要件を欠くに至った日を原則", True, "KY§7"),
        ("住民票記載の転出日", True, "SA2§1.2・KY§7"), ("住民票記載の転入日", True, "SA2§1.2"),
        ("月額基準額以上となった月の翌月初日", True, "KY§7・IKY3"),
        ("確定申告締切日(3月15日)", True, "KY§6.3"),
        ("施行規程第100条第2項の規定により準用する施行規程第97条第1項", True, "MS-KY§3"),
        ("学生である子は提出不要", True, "SA2§3"),
        ("令和3年2月18日", True, "KY§0.2"), ("令和5年1月19日", True, "KY§0.2"), ("令和3年7月1日", True, "KY§0.2"),
        ("150万", False, "KY§0.2（150万円の記載がない）"),
        ("2,600,000", None, "C5（夫婦合算の表。書き方を見る）"), ("260万", None, "C5"), ("310万", None, "C5"), ("360万", None, "C5")]),
    ("KEISATSU", "https://www.keikyo.jp/kenpo/621.html", [
        ("同居を必要としない親族では配偶者、子、父母、孫、祖父母、兄弟姉妹", True, "KY§1.2"),
        ("同居を必要とする親族では伯父伯母、甥姪、曾祖父母、曾孫、子の配偶者、配偶者の父母", True, "KY§1.2"),
        ("年額130万円未満", True, "KY§1.2"), ("を超えることが見込まれるとき", True, "KY§1.2"),
        ("年齢は民法の取扱いに準じて誕生日の前日に加齢されますので、誕生日が1月1日の場合、年齢は前年の12月31日に加齢されます", True, "KY§3.2"),
        ("12月31日現在", True, "KY§3.2"),
        ("労働基準法第11条に規定される賃金のことで、交通費等の諸手当や賞与を含みます", True, "KY§6.2"),
        ("被雇用者が対象であり、フリーランス・個人事業主等、特定の事業主と雇用関係にない場合は対象外", True, "KY§6.3"),
        ("連続2回", True, "KY§6.5"), ("警察共済組合", True, "（組合名）")]),
    ("MONKA", "https://www.monkakyosai.or.jp/shikumi/04.html", [
        ("収入とは所得税法上の所得(暦年でいう1月～12月までの所得額)をいうものではなく収入事由が発生した日から12ヶ月間における収入額となります", True, "KY§3.2"),
        ("どの月を基準にしても年額130万円未満でなければ被扶養者として認められません", True, "KY§6.4"),
        ("実績収入と見込収入額が異なる場合には遡って認定取消になる場合があります", True, "KY§6.4"),
        ("給与収入（交通費などの非課税収入及び賞与を含む）", True, "KY§6.2"), ("年金（個人年金含む）", True, "KY§6.2"),
        ("退職手当のような一時的な収入は含まれません", True, "KY§6.2"),
        ("組合員の送金額等が、当該認定する者の全収入（当該認定する者の収入及び組合員、その他の者の送金額等による収入の合計）の3分の1以上の額であることが必要", True, "SA2§2"),
        ("12月31日", True, "KY§3.2"), ("150万円", True, "KY§3.3")]),
    ("PMAC-01", "https://www.pmac.shigaku.go.jp/annai/shikaku/hifuyosya/hifuyosya_01/index.html", [
        ("3親等内の親族（内縁・養子縁組を含む）は、被扶養者となる要件を満たせば、被扶養者として認定できます。", True, "KY§5"),
        ("配偶者・子・父母・孫・祖父母・兄弟姉妹は、同居の要件はありません。", True, "KY§1.2・§5"),
        ("被扶養者となる要件は、学校法人等から支給される扶養手当の条件とは必ずしも一致するものではありません。", True, "KY§5"),
        ("被扶養者にしたい人からみて加入者より近い親族等がいる場合はその人の扶養義務が優先されますので、その親族等が健康保険や共済組合などの被用者保険に加入している場合（任意継続を含みます）は認定できません。", True, "KY§5"),
        ("配偶者はもっとも優先する扶養義務者になります（夫婦相互扶助義務）ので、子や兄弟姉妹を被扶養者に認定している場合で、その子や兄弟姉妹が結婚したときは、原則として被扶養者の認定を取り消さなければなりません。", True, "KY§5"),
        ("年収130万円未満（月額108,334円未満）", True, "KY§5"), ("年収180万円未満（月額150,000円未満）", True, "KY§5"),
        ("事業所得等及び老齢・退職・遺族の年金を含みます", True, "KY§5"),
        ("被扶養者の認定基準の収入は、所得税法上の「所得」とは異なります。", True, "KY§5"),
        ("障害年金、遺族年金、児童手当、児童扶養手当などの非課税の給付も含まれます。", True, "KY§5"),
        ("事業所得などは私学事業団が認める必要経費を控除した後の額", True, "KY§5"),
        ("受給日額が3,612円以上の給付を受けている間（配偶者を除く19歳以上23歳未満の場合は受給日額が4,167円以上、60歳以上の場合は受給日額が5,000円以上である間）は、被扶養者になれません。", True, "KY§5"),
        ("令和5年2月1日から、年収130万円未満（月額108,334円未満）から年収180万円未満（月額150,000円未満）に改定されました。", True, "KY§5"),
        ("国の時限的な措置として、人手不足による労働の延長等に伴う一時的な収入増加分は、収入限度額に含めません。", True, "KY§5"),
        ("令和7年10月1日から19歳以上23歳未満の人（配偶者は除く）については、年収130万円未満（月額108,334円未満）から年収150万円（月額125,000円未満）に改定されました。", True, "KY§5"),
        ("被扶養者とすべき子の人数にかかわらず夫婦それぞれの年間収入の多い方の被扶養者", True, "KY§5"),
        ("日本国内に住所を有すること（日本に住民票があること）", True, "KY§5"),
        ("令和 8年04月03日", True, "KY§0.2（ページの日付）")]),
    ("PMAC-03", "https://www.pmac.shigaku.go.jp/annai/shikaku/hifuyosya/hifuyosya_03/index.html", [
        ("要件を備えることとなった日から30日以内に申請がなかったときは、私学事業団でその申請を受理した日（発信年月日が確認できる場合はその日）からの認定となります。", True, "KY§5"),
        ("5日以内", True, "KY§5")]),
    ("PMAC-05", "https://www.pmac.shigaku.go.jp/annai/shikaku/hifuyosya/hifuyosya_05/index.html", [
        ("確定申告書の写し（収受日付及び税務署名の記載があるリーフレットの写し又は電子申告受信通知を添付したもの）など", True, "KY§5"),
        ("満22歳の年度末までの学生で、アルバイト等の収入がない場合は、在学証明書又は有効期限の記載のある学生証の写しを添付することで確認できます。", True, "KY§5・SA2§3"),
        ("ただし、大学院生、夜間部、通信教育課程の学生（18歳以上の人に限ります）は、非課税証明書を添付してください。", True, "SA2§3")]),
    ("PMAC-QA29", "https://www.pmac.shigaku.go.jp/qa/detail/qa_29.html", [
        ("夫婦相互扶助義務に基づき父母の収入合算額が、それぞれに適用される収入限度額の合算額未満であることと、個々の収入限度額未満であることの両方", True, "KY§5")]),
    ("PMAC-QA37", "https://www.pmac.shigaku.go.jp/qa/detail/qa_37.html", [
        ("保保発1001第1号", True, "KY§5"), ("令和7年10月1日", True, "KY§5"), ("135万", True, "KY§5（Q4）"), ("恒久", True, "KY§5")]),
    ("PMAC-DL06", "https://www.pmac.shigaku.go.jp/dl/category/shikaku/shikaku_06.html", []),
    ("K-FAQ", "https://www.kyoukaikenpo.or.jp/faq/dependent_status/", [
        ("世帯分離により住民票が分かれているが、実態としては同居である場合、同居扱いになりますか？", True, "SA2§1.3"),
        ("実態として同居をしていれば同居の扱いとなります。", True, "SA2§1.3"),
        ("同居の場合と異なり、別居の場合は被保険者と被扶養者の生計が同一ではないため、被扶養者の生活が主に被保険者の収入（仕送り）によって成り立っていることを確認する必要があります。", True, "SA2§1.3"),
        ("仕送りをしていない、被扶養者本人の収入よりも仕送り額が少ないなどの場合は", True, "SA2§1.3"),
        ("単身赴任中で被保険者名義の口座を被扶養者と共有しており、仕送り額を確認できる書類がありません。", True, "SA2§1.3"),
        ("給与振込口座の入出金明細を証明書類としてください。", True, "SA2§1.3"),
        ("海外赴任をしている夫（被保険者）がおり、日本に妻・子（被扶養者）が生活している場合、「別居」扱いとなりますか？", True, "SA2§1.3"),
        ("「別居」となります。そのため、仕送り額等の確認が必要です。", True, "SA2§1.3")]),
]
# 追加の確認（版の表示）：web とは別の取得ディレクトリに置く
WEB_EXTRA = [
    ("SOUMU-DAICHO", "https://www.soumu.go.jp/main_sosiki/jichi_gyousei/daityo/gaiyou.html", [
        ("住民基本台帳事務処理要領（令和8年6月14日施行）", True, "SA2§0（YORYO の版）"), ("001094645.pdf", True, "SA2§0（リンク先）")]),
    ("SOUMU-ICHIRAN04", "https://www.soumu.go.jp/main_sosiki/jichi_zeisei/czaisei/czaisei_seido/ichiran04.html", [
        ("001071661.pdf", True, "SA2§0（TORI-S のリンク先）")]),
]
PDFS = [
    ("UNYO-K", "https://www.mof.go.jp/about_mof/act/kokuji_tsuutatsu/tsuutatsu/TU-19591001-2927-11.pdf"),
    ("UNYO-K-R5", "https://www.kyousai.courts.or.jp/files/user/img/houki/1-01.pdf"),
    ("CHIKYO-OSAKA", "https://osaka.chikyosai.or.jp/upload/files/%E3%80%90%E7%B5%84%E5%90%88%E5%93%A1%E3%80%9119%E6%AD%B3%E4%BB%A5%E4%B8%8A23%E6%AD%B3%E6%9C%AA%E6%BA%80%E3%81%AE%E8%A2%AB%E6%89%B6%E9%A4%8A%E8%80%85%E3%81%AE%E5%8F%8E%E5%85%A5%E9%99%90%E5%BA%A6%E9%A1%8D%E5%A4%89%E6%9B%B4%E3%81%AB%E3%81%A4%E3%81%84%E3%81%A6%EF%BC%88%E9%80%9A%E7%9F%A5%EF%BC%89%284%29.pdf"),
    ("CHIKYO-GAIYO", "https://osaka.chikyosai.or.jp/upload/files/%E5%9C%B0%E6%96%B9%E5%85%AC%E5%8B%99%E5%93%A1%E7%AD%89%E5%85%B1%E6%B8%88%E7%B5%84%E5%90%88%E6%B3%95%E9%81%8B%E7%94%A8%E6%96%B9%E9%87%9D%E3%81%AE%E4%B8%80%E9%83%A8%E6%94%B9%E6%AD%A3%E6%A1%88%E3%81%AE%E6%A6%82%E8%A6%81%E3%81%AB%E3%81%A4%E3%81%84%E3%81%A6.pdf"),
    ("KOURITU-480", "https://www.kouritu.or.jp/shizuoka/content/files/tetsuduki/kyosai/hifuyo/hihuyousya_480%20nenkashunyu.pdf"),
    ("OITA-TEBIKI", "https://www.kouritu.or.jp/oita/content/files/181cab2cc9686290fc920ece58333d94.pdf"),
    ("MIYAGI", "https://www.kyosai-miyagi.or.jp/pdf/hihuyousha.pdf"),
    ("YUSEI", "https://www.yuseikyosai.or.jp/shikumi/docs/nintei_shunyu_kijun.pdf"),
    ("TORI-S", "https://www.soumu.go.jp/main_content/001071661.pdf"),
    ("YORYO", "https://www.soumu.go.jp/main_content/001094645.pdf"),
]
# 文書が書いた PDF の版（Last-Modified の日付、バイト数、元の担当の SHA-256 の先頭16桁）
PDF_CLAIMED = {
    "UNYO-K": ("2026-09-30", 443817, "b059e9ae85fa8dfa"), "UNYO-K-R5": ("2023-04-25", 440489, "68e2b40023100521"),
    "CHIKYO-OSAKA": ("2025-09-29", 180920, "b7762ae20115ab6e"), "CHIKYO-GAIYO": ("2023-03-20", 89595, "183381535204ab83"),
    "KOURITU-480": ("2026-03-26", 285759, "d64c364312f9c696"), "OITA-TEBIKI": ("2020-03-16", 505189, "cfde664be4107a0e"),
    "MIYAGI": ("2026-03-19", 684252, "c8b039d1d692617a"), "YUSEI": ("2025-10-01", 204546, "b18c0707921f9eda"),
    "TORI-S": ("2026-05-07", 792394, "107ba94cd6bd4b5e"), "YORYO": ("2026-10-01", 751096, "aee75810dca37cd1"),
}


def lm_date(lm):
    if not lm:
        return None
    try:
        return dt.datetime.strptime(lm, "%a, %d %b %Y %H:%M:%S GMT").date().isoformat()
    except ValueError:
        return lm


def check_html(sid, quotes, body, ctype=""):
    s = decode(body, ctype)
    p = Text()
    p.feed(s)
    text = "".join(p.parts)
    hrefs = re.findall(r"href=[\"']([^\"']+)[\"']", s)
    rec = {"title": " ".join(p.title.split()), "quotes": []}
    for qt, expect, where in quotes:
        found, missing = has_quote(text + chr(10) + chr(10).join(hrefs), qt)
        rec["quotes"].append({"quote": qt[:80], "expect": expect, "found": found, "ok": (expect is None) or (found == expect),
                              "where": where, "first_missing_fragment": missing})
    if sid == "KKR":
        rec["links_with_扶養"] = sorted({" ".join(m.split()) for m in re.findall(r"<a[^>]*>([^<]*扶養[^<]*)</a>", s)})
    if sid == "MOF-R":
        t = norm(text)
        i, rows = 0, []
        while True:
            j = t.find(norm("主計局給与共済課"), i)
            if j < 0:
                break
            rows.append(t[max(0, j - 120):j + 20])
            i = j + 1
        rec["rows_給与共済課"] = rows
    return rec


def run_web(recheck_dir=None):
    """recheck_dir を渡すと、ネットワークに出ず、その取得ディレクトリの HTML で引用の照合だけをやり直す。"""
    if recheck_dir:
        old = json.loads((OUT / "web.json").read_text(encoding="utf-8"))
        dl = ROOT / recheck_dir
        assert dl.resolve() == (ROOT / old["download_dir"]).resolve(), "web.json の取得ディレクトリと違う"
        for rec in old["html"]:
            quotes = next(q for sid, _, q in WEB if sid == rec["id"])
            rec.update(check_html(rec["id"], quotes, (dl / f"{rec['id']}.html").read_bytes()))
            print("recheck", rec["id"], [(q["quote"][:20], q["found"]) for q in rec["quotes"] if not q["ok"]], flush=True)
        old["rechecked_at"] = time.strftime("%Y%m%d-%H%M%S")
        (OUT / "web.json").write_text(json.dumps(old, ensure_ascii=False, indent=1), encoding="utf-8")
        return
    ts, dl = new_dl("web")
    res = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "html": [], "pdf": []}
    for sid, url, quotes in WEB:
        st, final, hdr, body = http_get(url)
        (dl / f"{sid}.html").write_bytes(body)
        rec = {"id": sid, "url": url, "status": st, "final_url": final, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
               "last_modified": hdr.get("Last-Modified")}
        rec.update(check_html(sid, quotes, body, hdr.get("Content-Type", "")))
        res["html"].append(rec)
        print("web", sid, st, rec["last_modified"], [(q["quote"][:20], q["found"]) for q in rec["quotes"] if not q["ok"]], flush=True)
    for sid, url in PDFS:
        st, final, hdr, body = http_get(url)
        (dl / f"{sid}.pdf").write_bytes(body)
        c = PDF_CLAIMED.get(sid)
        sha = hashlib.sha256(body).hexdigest()
        rec = {"id": sid, "url": url, "status": st, "bytes": len(body), "sha256": sha, "last_modified": hdr.get("Last-Modified"),
               "saved": str((dl / f"{sid}.pdf").relative_to(ROOT)),
               "claimed": c, "lm_ok": c is not None and lm_date(hdr.get("Last-Modified")) == c[0],
               "bytes_ok": c is not None and c[1] == len(body), "same_as_prev_sha16": c is not None and sha.startswith(c[2]),
               "n_pages_marker": len(re.findall(rb"/Type\s*/Page[^s]", body))}
        res["pdf"].append(rec)
        print("pdf", sid, st, len(body), rec["last_modified"], rec["same_as_prev_sha16"], flush=True)
    # 元の担当の取得記録（HTML）の Last-Modified と比べる
    prev = {}
    for f in (ROOT / "scripts" / "results" / "R2X_kyosai_fetch").glob("*.json"):
        for r in json.loads(f.read_text(encoding="utf-8")).get("results", []):
            prev[r.get("url")] = r
    for rec in res["html"]:
        p = prev.get(rec["url"])
        if p:
            rec["prev_last_modified"] = p.get("last_modified")
            rec["prev_sha16"] = (p.get("sha256") or "")[:16]
            rec["same_as_prev"] = p.get("sha256") == rec["sha256"]
    (OUT / "web.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


def run_web_extra():
    ts, dl = new_dl("webextra")
    res = {"run_at": ts, "download_dir": str(dl.relative_to(ROOT)), "html": []}
    for sid, url, quotes in WEB_EXTRA:
        st, final, hdr, body = http_get(url)
        (dl / f"{sid}.html").write_bytes(body)
        rec = {"id": sid, "url": url, "status": st, "final_url": final, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
               "last_modified": hdr.get("Last-Modified")}
        rec.update(check_html(sid, quotes, body, hdr.get("Content-Type", "")))
        res["html"].append(rec)
        print("webextra", sid, st, [(q["quote"][:30], q["found"]) for q in rec["quotes"]], flush=True)
    (OUT / "web_extra.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


def compare_checks():
    """元の担当の R2X_kyosai_checks.py の出力を、表示の不具合を直して再実行した前後で比べる（run_at を除く）。
    前：scripts/results/R2X_kyosai_verify/checks_before_fix.json（再実行の前に写したもの）
    後：scripts/results/R2X_kyosai_checks/checks.json"""
    before = json.loads((OUT / "checks_before_fix.json").read_text(encoding="utf-8"))
    after = json.loads((ROOT / "scripts" / "results" / "R2X_kyosai_checks" / "checks.json").read_text(encoding="utf-8"))
    rb, ra = before.pop("run_at", None), after.pop("run_at", None)
    res = {"before_run_at": rb, "after_run_at": ra, "identical_except_run_at": before == after,
           "keys_differ": sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))}
    (OUT / "checks_compare.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(res)


# ---------------------------------------------------------------- 計算のやり直し
def ceil_frac(f):
    return -(-f.numerator // f.denominator)


def age_on(birth, day):
    """年齢計算ニ関スル法律と民法の期間の計算により、誕生日の前日の終わりに1歳加わる（その日に達する）。
    day の時点の年齢 ＝ day の翌日以前に来た誕生日の回数。"""
    nxt = day + dt.timedelta(days=1)
    a = nxt.year - birth.year
    if (nxt.month, nxt.day) < (birth.month, birth.day):
        a -= 1
    return a


def months(y0, m0, n):
    out = []
    y, m = y0, m0
    for _ in range(n):
        out.append((y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def first_day_next(y, m):
    return dt.date(y + (m == 12), 1 if m == 12 else m + 1, 1)


def window_rules(pay, base_month, base_year):
    """pay: {(y,m): 円}。月額基準 base_month、年額基準 base_year。資料ごとの取消の候補日を返す。"""
    keys = sorted(pay)
    out = {}
    # 3か月連続で月額基準以上 → 3か月目の翌月初日（OITA-TEBIKI）
    run = 0
    out["OITA_3連続_翌月初日"] = None
    for k in keys:
        run = run + 1 if pay[k] >= base_month else 0
        if run == 3 and out["OITA_3連続_翌月初日"] is None:
            out["OITA_3連続_翌月初日"] = first_day_next(*k).isoformat()
    # 4か月連続 → 4か月目の初日（KOURITU-HIRO）
    run = 0
    out["HIRO_4連続_4か月目の初日"] = None
    for k in keys:
        run = run + 1 if pay[k] >= base_month else 0
        if run == 4 and out["HIRO_4連続_4か月目の初日"] is None:
            out["HIRO_4連続_4か月目の初日"] = dt.date(k[0], k[1], 1).isoformat()
    # 任意の連続12か月の累計が年額基準を超える → 超えた月の初日（KOURITU-HIRO）
    out["HIRO_12か月累計超_その月の初日"] = None
    out["12か月累計の最大"] = 0
    for i in range(len(keys) - 11):
        w = keys[i:i + 12]
        s = sum(pay[k] for k in w)
        out["12か月累計の最大"] = max(out["12か月累計の最大"], s)
        if s > base_year and out["HIRO_12か月累計超_その月の初日"] is None:
            out["HIRO_12か月累計超_その月の初日"] = dt.date(w[-1][0], w[-1][1], 1).isoformat()
            out["HIRO_最初に超えた窓"] = [f"{w[0][0]}-{w[0][1]:02d}", f"{w[-1][0]}-{w[-1][1]:02d}", s]
    # 連続3か月の平均が月額基準以上（FUKUOKA-KIJUN）→ 取消日の候補（最初の月の翌月初日／最後の月の翌月初日）
    out["FUKUOKA_3か月平均"] = None
    for i in range(len(keys) - 2):
        w = keys[i:i + 3]
        if Fraction(sum(pay[k] for k in w), 3) >= base_month:
            out["FUKUOKA_3か月平均"] = [first_day_next(*w[0]).isoformat(), first_day_next(*w[-1]).isoformat()]
            break
    return out


def run_calc():
    res = {}
    # C3：月額・日額の目安
    rows = []
    for annual in (1_300_000, 1_500_000, 1_800_000):
        m, d = Fraction(annual, 12), Fraction(annual, 360)
        rows.append({"年額": annual, "年額/12": str(m), "切り上げ": ceil_frac(m), "切り捨て": m.numerator // m.denominator,
                     "年額/360": str(d), "日額の切り上げ": ceil_frac(d), "日額の切り捨て": d.numerator // d.denominator,
                     # 整数の月額 x について「x < 年額/12」⇔「x < 切り上げ」⇔「x*12 < 年額」を全探索で確かめる
                     "月額の同値（x<ceil ⇔ 12x<年額）": all((x < ceil_frac(m)) == (12 * x < annual) for x in range(0, 200_001)),
                     "日額の同値（x<ceil ⇔ 360x<年額）": all((x < ceil_frac(d)) == (360 * x < annual) for x in range(0, 10_001)),
                     "機構の『以下』（x<=floor ⇔ 12x<年額）": all((x <= m.numerator // m.denominator) == (12 * x < annual) for x in range(0, 200_001))})
    res["C3"] = rows
    # C4：19歳以上23歳未満の生年月日の範囲（その年の12月31日現在）
    c4 = {}
    for y in (2025, 2026, 2027):
        day = dt.date(y, 12, 31)
        ok = [b for b in (dt.date(y - 30, 1, 1) + dt.timedelta(days=i) for i in range(0, 366 * 30)) if b <= day and 19 <= age_on(b, day) < 23]
        c4[str(y)] = [ok[0].isoformat(), ok[-1].isoformat()]
    res["C4"] = c4
    res["C4_公表（平成15年1月2日〜平成19年1月1日）と一致"] = c4["2025"] == ["2003-01-02", "2007-01-01"]
    res["IKY8"] = {b: age_on(dt.date.fromisoformat(b), dt.date(2025, 12, 31)) for b in ("2007-01-01", "2007-01-02", "2003-01-02", "2003-01-01")}
    # C5：夫婦合算
    res["C5"] = {"130+130": 2_600_000, "130+180": 3_100_000, "180+180": 3_600_000}
    # IKY3：収入に波があるパート
    pay = {k: 90_000 for k in months(2026, 1, 9)}
    pay.update({k: 120_000 for k in months(2026, 10, 3)})
    pay.update({k: 90_000 for k in months(2027, 1, 12)})
    res["IKY3_2026年中の合計"] = sum(v for (y, _), v in pay.items() if y == 2026)
    res["IKY3_配偶者130万"] = window_rules(pay, 108_334, 1_300_000)
    res["IKY3_20歳の子150万"] = window_rules(pay, 125_000, 1_500_000)
    pay2 = {k: 90_000 for k in months(2026, 1, 9)}
    pay2.update({k: 120_000 for k in months(2026, 10, 15)})
    res["IKY3_変形2（10月以降ずっと120,000円）"] = window_rules(pay2, 108_334, 1_300_000)
    # IKY4：事業収入
    sales, cogs, tel, travel, dep, ad, blue = 2_000_000, 500_000, 100_000, 200_000, 150_000, 100_000, 650_000
    res["IKY4"] = {"所得税の事業所得": sales - (cogs + tel + travel + dep + ad) - blue, "経費の合計": cogs + tel + travel + dep + ad,
                   "売上原価と通信費を引く": sales - cogs - tel, "売上原価だけ引く": sales - cogs,
                   "150万以上で不可（売上原価だけ）": sales - cogs >= 1_500_000, "130万以上で不可（売上原価と通信費）": sales - cogs - tel >= 1_300_000}
    # IKY5：別居の母
    inc, send = 80_000 * 12, 50_000 * 12
    r = Fraction(send, inc + send)
    res["IKY5"] = {"年金": inc, "送金": send, "T4 割合": str(r), "T4 ≥ 1/3": r >= Fraction(1, 3), "T3 送金 > 本人収入": send > inc,
                   "T5 月5万以上": 50_000 >= 50_000, "T5 本人収入+送金 ≤ 600万": inc + send <= 6_000_000,
                   "T6 送金 ≥ 本人収入 かつ ≥ 65万": send >= inc and send >= 650_000}
    # IKY6：別居の学生の子
    inc6, send6 = 1_000_000, 30_000 * 12
    r6 = Fraction(send6, inc6 + send6)
    res["IKY6"] = {"T4 割合": str(r6), "近似": float(r6), "T4 ≥ 1/3": r6 >= Fraction(1, 3), "T3 送金 > 本人収入": send6 > inc6}
    # IKY7：30日の数え方
    ev = dt.date(2026, 5, 1)
    res["IKY7"] = {d: {"初日不算入の日目": (dt.date.fromisoformat(d) - ev).days, "初日算入の日目": (dt.date.fromisoformat(d) - ev).days + 1}
                   for d in ("2026-05-30", "2026-05-31", "2026-06-01")}
    (OUT / "calc.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1))


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    what = argv[0] if argv else "all"
    if what in ("egov", "all"):
        run_egov()
    if what in ("egovextra", "all"):
        run_egov_extra()
    if what == "egovcheck":
        recheck_egov()
    if what in ("web", "all"):
        run_web()
    if what in ("webextra", "all"):
        run_web_extra()
    if what == "comparechecks":
        compare_checks()
    if what == "webcheck":  # 例: webcheck .work/downloads/20261109-185318_R2X_kyosai_verify_web
        run_web(argv[1])
    if what in ("calc", "all"):
        run_calc()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

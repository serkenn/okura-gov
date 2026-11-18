"""R3X shibo-shukkoku: 取得済みのテキスト（条文・国税庁のページ・PDF から取り出した文字）だけを使って（ネットワークに出ない）、
仮説の根拠にする条文の構造と文言を検査し、期限・年齢・按分・繰戻し・基礎控除の例を計算する。
scripts/R3X_shibo-shukkoku_calc.py の続き（calc.py の出力は変えない）。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_shibo-shukkoku_checks.py <所得税法の JSON（asof 2026-11-09）> <所得税法の JSON（asof 2027-01-01）>
  例：.work/downloads/20261109-201324_R3X_shibo-shukkoku_laws_articles/shotoku_2026-11-09.json
      .work/downloads/20261109-201324_R3X_shibo-shukkoku_laws_articles/shotoku_2027-01-01.json
  （JSON は e-Gov 法令API v2 から scripts/R3X_shibo-shukkoku_laws.py が取得した信頼できないデータ。パスを受け取って json として読むだけ）

入力（取得済みのテキスト）:
  scripts/results/R3X_shibo-shukkoku_laws/<略称>_<asof>.txt   … 条文（R3X_shibo-shukkoku_laws.py の出力）
  scripts/results/R3X_shibo-shukkoku_asof/<略称>_<asof>.txt   … 2026-11-30・2026-12-01 の条文（R3X_shibo-shukkoku_asof.py の出力）
  scripts/results/R3X_shibo-shukkoku_nta/<組>/<id>.txt        … 国税庁の HTML のテキスト
  scripts/results/R3X_shibo-shukkoku_pdftext/<名前>.txt       … 国税庁の PDF から取り出した文字（R3X_shibo-shukkoku_pdftext.py の出力）
  scripts/results/R3X_shibo-shukkoku_calc/quotes_check.json   … calc.py quotes の結果（見つからなかった引用を PDF の文字で照合し直す）
出力:
  scripts/results/R3X_shibo-shukkoku_checks/checks.json と checks.txt

引用の照合（このトピックの文書すべて。calc.py quotes と同じ方法で、照合先に asof・pdftext の文字を足したもの）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R3X_shibo-shukkoku_checks.py quotes <文書.md> ...
  → scripts/results/R3X_shibo-shukkoku_checks/quotes_all.json（引用ごとに、見つかった照合先の種類：laws / asof / nta / pdftext）

- 期限・年齢・税額の関数は scripts/R3X_shibo-shukkoku_calc.py から写した（import はしない）。休日の判定だけ、1月2日・3日を
  「その他一般の休日（通則法10②）に当たるか未確認」として None（決まらない）を返すように変えた（calc.py は平日とみなしていた）。
- 数字はすべて架空。個人の情報は使わない。途中の値は Fraction（有理数）、丸めは名前つきの関数だけ（D21 R5）。
"""
import calendar
import datetime as dt
import json
import pathlib
import re
import sys
import unicodedata
from fractions import Fraction

ROOT = pathlib.Path(__file__).resolve().parent.parent
RES = ROOT / "scripts" / "results"
LAWS = RES / "R3X_shibo-shukkoku_laws"
ASOF = RES / "R3X_shibo-shukkoku_asof"
NTA = RES / "R3X_shibo-shukkoku_nta"
PDFT = RES / "R3X_shibo-shukkoku_pdftext"
OUT = RES / "R3X_shibo-shukkoku_checks"
D = dt.date
WD = "月火水木金土日"

# ---------------------------------------------------------------- 漢数字（calc.py から写した）
KD = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
KU = {"十": 10, "百": 100, "千": 1000}


def kanji_int(s):
    total, sect, num = 0, 0, 0
    for ch in s:
        if ch in KD:
            num = KD[ch]
        elif ch in KU:
            sect += (num or 1) * KU[ch]
            num = 0
        elif ch == "万":
            total += (sect + num) * 10000
            sect, num = 0, 0
        else:
            raise ValueError(f"unexpected {ch!r} in {s!r}")
    return total + sect + num


# ---------------------------------------------------------------- 条文テキストの読み出し
def sections(path):
    d, cur = {}, None
    for ln in path.read_text(encoding="utf-8").splitlines():
        if ln.startswith("## Num="):
            cur = ln[len("## Num="):]
            d[cur] = []
        elif cur is not None:
            d[cur].append(ln)
    return d


PARA_HEAD = re.compile(r"^(?:（Paragraph(\d+)）|([０-９]+)　)")


def paragraphs(lines):
    """条の行を項ごとに分ける。項の頭は深さ0の「（Paragraph1）」か「２　」。号・細目は前の項に含める。"""
    out, cur = {}, None
    for ln in lines:
        m = PARA_HEAD.match(ln)
        if m:
            cur = int(m.group(1) or unicodedata.normalize("NFKC", m.group(2)))
            out[cur] = [ln]
        elif cur is not None:
            out[cur].append(ln)
    return {k: "\n".join(v) for k, v in out.items()}


def item(lines, name):
    """第1項の号（「  三十七　」のように深さ1で始まる行）の本文と、その下の行。"""
    out, keep = [], False
    for ln in lines:
        if re.match(r"^  \S", ln):
            keep = ln.startswith(f"  {name}　")
        elif not ln.startswith("    "):
            keep = False
        if keep:
            out.append(ln)
    return "\n".join(out)


# ---------------------------------------------------------------- 1. 所得税法の編・章・節・款（JSON から）
def structure(json_path, lo=120, hi=142):
    d = json.loads(pathlib.Path(json_path).read_text(encoding="utf-8"))
    title_tag = {"Part": "PartTitle", "Chapter": "ChapterTitle", "Section": "SectionTitle", "Subsection": "SubsectionTitle", "Division": "DivisionTitle"}
    rows = []

    def inline(n):
        if isinstance(n, str):
            return n
        return "".join(inline(c) for c in n.get("children", []) if not (isinstance(c, dict) and c.get("tag") == "Rt"))

    def walk(n, path):
        if not isinstance(n, dict):
            return
        tag = n.get("tag")
        if tag == "SupplProvision":
            return
        if tag in title_tag:
            t = "".join(inline(c) for c in n.get("children", []) if isinstance(c, dict) and c.get("tag") == title_tag[tag])
            path = path + ((tag, t),)
        if tag == "Article":
            num = n.get("attr", {}).get("Num", "")
            base = re.match(r"\d+", num)
            if base and lo <= int(base.group()) <= hi:
                cap = "".join(inline(c) for c in n.get("children", []) if isinstance(c, dict) and c.get("tag") == "ArticleCaption")
                rows.append({"num": num, "caption": cap, "path": [f"{t}" for _, t in path]})
            return
        for c in n.get("children", []):
            walk(c, path)
    walk(d["law_full_text"], ())
    return {"file": pathlib.Path(json_path).as_posix(), "law_revision_id": (d.get("revision_info") or {}).get("law_revision_id"), "articles": rows}


# ---------------------------------------------------------------- 2. 条文の文言の検査
def law_checks():
    asofs = ["2025-12-31", "2026-11-09", "2026-12-31", "2027-01-01"]
    S = {a: sections(LAWS / f"shotoku_{a}.txt") for a in asofs}
    TR = {a: sections(LAWS / f"tsusoku-rei_{a}.txt") for a in ["2026-11-09", "2027-01-01"]}
    TS = {a: sections(LAWS / f"tsusoku_{a}.txt") for a in ["2026-11-09", "2027-01-01"]}

    def P(sec, num, p):
        return paragraphs(sec.get(num, [])).get(p, "")

    defs = [
        ("T01", "所法2①三十七 確定申告書の定義が第二編第五章第二節第一款及び第二款を引く", "shotoku", lambda s: "第二編第五章第二節第一款及び第二款" in item(s["2"], "三十七")),
        ("T02", "所法2①四十一 確定申告期限に死亡（125①）・出国（127①）の申告書の提出期限を含む", "shotoku",
         lambda s: "第百二十五条第一項" in item(s["2"], "四十一") and "第百二十七条第一項" in item(s["2"], "四十一")),
        ("T03", "所法2①三十イ（２）合計所得金額は第70条・第71条を適用しないで計算", "shotoku",
         lambda s: "第七十条（純損失の繰越控除）及び第七十一条（雑損失の繰越控除）の規定を適用しないで計算した" in item(s["2"], "三十")),
        ("T04", "所法125①・③に「四月を経過した日の前日」、②には「までに」がない", "shotoku",
         lambda s: "四月を経過した日の前日" in P(s, "125", 1) and "四月を経過した日の前日までに" in P(s, "125", 3) and "までに" not in P(s, "125", 2)),
        ("T05", "所法127①・③に「その出国の時までに」、②には「までに」がない", "shotoku",
         lambda s: "その出国の時までに" in P(s, "127", 1) and "その出国の時までに" in P(s, "127", 3) and "までに" not in P(s, "127", 2)),
        ("T06", "所法127①②は「その時の現況により」記載、所法125①②には「現況」の語がない", "shotoku",
         lambda s: "その時の現況により" in P(s, "127", 1) and "その時の現況により" in P(s, "127", 2) and "現況" not in P(s, "125", 1) and "現況" not in P(s, "125", 2)),
        ("T07", "所法85①の括弧に「以下この条において同じ」、②③は「その年十二月三十一日の現況による」", "shotoku",
         lambda s: "以下この条において同じ" in P(s, "85", 1) and "その年十二月三十一日の現況による" in P(s, "85", 2) and "その年十二月三十一日の現況による" in P(s, "85", 3)),
        ("T08", "所法141①は第125条第1項・第3項・第5項の申告書だけを引き、第141条に第127条の語がない。所法140①は「青色申告書を提出する居住者」", "shotoku",
         lambda s: P(s, "141", 1).startswith("（Paragraph1）　第百二十五条第一項、第三項又は第五項") and "第百二十七条" not in "\n".join(s["141"]) and "青色申告書を提出する居住者" in P(s, "140", 1)),
        ("T09", "所法141③ 死亡者の前年分が青色かつ期限内、④ 前年分・前前年分が青色で確定申告期限までに請求", "shotoku",
         lambda s: "その年の前年分の所得税につき青色申告書を提出している場合" in P(s, "141", 3) and "その提出期限までに提出した場合" in P(s, "141", 3)
         and "前年分及び前前年分の所得税につき青色申告書が提出されている場合に限り" in P(s, "141", 4) and "確定申告期限までに" in P(s, "141", 4)),
        ("T10", "所法70①は青色の年に限る、所法71（雑損失の繰越控除）には「青色」の語がない", "shotoku",
         lambda s: "青色申告書を提出している年に限る" in P(s, "70", 1) and "青色" not in "\n".join(s["71"])),
        ("T11", "所法70④・71② 連続して確定申告書を提出している場合に限る", "shotoku",
         lambda s: "連続して確定申告書を提出している場合に限り" in P(s, "70", 4) and "連続して確定申告書を提出している場合に限り" in P(s, "71", 2)),
        ("T12", "所法124① 翌年1月1日から提出期限までの間に死亡、126② 翌年1月1日から2月15日までの間に出国", "shotoku",
         lambda s: "その年の翌年一月一日から当該申告書の提出期限までの間に当該申告書を提出しないで死亡した場合" in P(s, "124", 1)
         and "その年の翌年一月一日から二月十五日までの間に出国をする場合" in P(s, "126", 2)),
        ("T13", "所法120①の第三期（翌年2月16日から3月15日まで）", "shotoku",
         lambda s: "第三期（その年の翌年二月十六日から三月十五日までの期間をいう。" in P(s, "120", 1)),
        ("T14", "所法2①三十四の二イ（居住者 16歳以上）・三十四の三（19歳以上23歳未満）・三十四の四（70歳以上）", "shotoku",
         lambda s: "居住者　年齢十六歳以上の者" in item(s["2"], "三十四の二") and "年齢十九歳以上二十三歳未満" in item(s["2"], "三十四の三") and "年齢七十歳以上" in item(s["2"], "三十四の四")),
    ]
    rows = []
    for cid, desc, law, fn in defs:
        res = {}
        for a in asofs:
            try:
                res[a] = bool(fn(S[a]))
            except KeyError as e:
                res[a] = f"条がない {e}"
        rows.append({"id": cid, "desc": desc, "by_asof": res})
    # 国税通則法・同施行令（2026-11-09・2027-01-01）
    for a in ["2026-11-09", "2027-01-01"]:
        rows.append({"id": f"T15@{a}", "desc": "通則令2①一 出国の時その他の時をもつて定めた期限は通則法10②の繰下げの対象外",
                     "by_asof": {a: "出国" in item(TR[a]["2"], "一") and "の時その他の時をもつて定めた期限" in item(TR[a]["2"], "一")}})
        rows.append({"id": f"T16@{a}", "desc": "通則法10②の括弧「時をもつて定める期限その他の政令で定める期限を除く」",
                     "by_asof": {a: "時をもつて定める期限その他の政令で定める期限を除く" in P(TS[a], "10", 2)}})
    return rows


# ---------------------------------------------------------------- 3. 国税庁のテキストで「見積」を含む行
def nta_mitsumori():
    rows = []
    for p in sorted(NTA.glob("*/*.txt")):
        for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if "見積" in ln:
                rows.append({"file": p.relative_to(ROOT).as_posix(), "line": i, "text": ln.strip()[:400]})
    return rows


# ---------------------------------------------------------------- 4. PDF 目視の引用を PDF から取り出した文字で照合
def pdf_quotes():
    qc = json.loads((RES / "R3X_shibo-shukkoku_calc" / "quotes_check.json").read_text(encoding="utf-8"))
    nf = [r for r in qc if not r["found"]]
    corpus_raw = {p.stem: re.sub(r"\s+", "", p.read_text(encoding="utf-8")) for p in sorted(PDFT.glob("*.txt"))}
    corpus_n = {k: unicodedata.normalize("NFKC", v) for k, v in corpus_raw.items()}
    rows = []
    for r in nf:
        q = re.sub(r"\s+", "", r["quote"].replace("…", "|"))
        pieces = [x for x in q.split("|") if x]
        hit_raw = [k for k, v in corpus_raw.items() if all(x in v for x in pieces)]
        hit_n = [k for k, v in corpus_n.items() if all(unicodedata.normalize("NFKC", x) in v for x in pieces)]
        rows.append({"quote": r["quote"], "found_raw_in": hit_raw, "found_nfkc_in": hit_n})
    return rows


# ---------------------------------------------------------------- 5. 期限（calc.py から写し、1月2日・3日を未確定にした）
def parse_holiday_rules():
    rules = []
    for ln in sections(LAWS / "shukujitsu_2026-11-09.txt")["2"]:
        ln = ln.strip()
        if not ln.startswith("| "):
            continue
        name, spec = [c.strip() for c in ln.strip("|").split("|")][:2]
        m = re.fullmatch(r"([一二三四五六七八九十]+)月([一二三四五六七八九十]+)日", spec)
        n = re.fullmatch(r"([一二三四五六七八九十]+)月の第([一二三四五]+)月曜日", spec)
        if m:
            rules.append((name, "fixed", kanji_int(m.group(1)), kanji_int(m.group(2))))
        elif n:
            rules.append((name, "nth_monday", kanji_int(n.group(1)), kanji_int(n.group(2))))
    return rules


HOLIDAY_RULES = parse_holiday_rules()
UNKNOWN_MONTHS = {"建国記念の日": {2}, "春分の日": {3}, "秋分の日": {9}}  # calc.py と同じ前提（一次情報で確認していない）


def kyujitsu(year):
    s = {}
    for name, kind, mth, x in HOLIDAY_RULES:
        if kind == "fixed":
            s[D(year, mth, x)] = name
        else:
            first = D(year, mth, 1)
            s[first + dt.timedelta(days=(0 - first.weekday()) % 7 + 7 * (x - 1))] = name
    h = dict(s)
    for d0 in sorted(s):
        if d0.weekday() == 6:
            d1 = d0 + dt.timedelta(days=1)
            while d1 in s:
                d1 += dt.timedelta(days=1)
            h[d1] = f"振替休日（{s[d0]}）"
    for d0 in sorted(s):
        if (d0 + dt.timedelta(days=2)) in s and (d0 + dt.timedelta(days=1)) not in s:
            h[d0 + dt.timedelta(days=1)] = "国民の休日（第3条第3項）"
    return h


def holiday_status(d):
    if d.weekday() == 6:
        return True, "日曜日"
    if d.weekday() == 5:
        return True, "土曜日（通則令2②）"
    if d.month == 12 and d.day in (29, 30, 31):
        return True, "12月29日〜31日（通則令2②）"
    h = kyujitsu(d.year)
    if d in h:
        return True, h[d]
    if d.month == 1 and d.day in (2, 3):
        return None, "1月2日・3日が「その他一般の休日」（通則法10②）に当たるかは取得した資料で決まらない"
    for name, months in UNKNOWN_MONTHS.items():
        if d.month in months:
            return None, f"{name}の日付は祝日法の条文だけでは決まらない"
    return False, "平日"


def shift_holiday(d):
    trail = []
    while True:
        st, why = holiday_status(d)
        trail.append(f"{d.isoformat()}({WD[d.weekday()]}) {why}")
        if st is None:
            return None, trail
        if not st:
            return d, trail
        d += dt.timedelta(days=1)


def period_end(kisanbi, months=0):
    y, m = divmod(kisanbi.month - 1 + months, 12)
    y, m = kisanbi.year + y, m + 1
    if kisanbi.day > calendar.monthrange(y, m)[1]:
        return D(y, m, calendar.monthrange(y, m)[1])
    return D(y, m, kisanbi.day) - dt.timedelta(days=1)


def junkaku_deadline_A(knew):
    """所法125①：知った日の翌日を起算日とする4月の期間の満了日（記載要領の例と一致した読みA。実測 calc [2]）。"""
    return period_end(knew + dt.timedelta(days=1), months=4)


def daisanki_end(year_of_income):
    """所法120①の第三期の末日（翌年3月15日）に通則法10②を当てた日。"""
    return shift_holiday(D(year_of_income + 1, 3, 15))


# ---------------------------------------------------------------- 6. 年齢（calc.py から写した）
def age_at(birth, d):
    a = d.year - birth.year
    bday = D(d.year, birth.month, birth.day) if not (birth.month == 2 and birth.day == 29 and not calendar.isleap(d.year)) else D(d.year, 3, 1)
    return a if d >= bday - dt.timedelta(days=1) else a - 1


# ---------------------------------------------------------------- 7. 税率（calc.py から写した）
def parse_rates():
    rates = []
    for r in sections(LAWS / "shotoku_2026-11-09.txt")["89"]:
        r = r.strip()
        if not r.startswith("| "):
            continue
        cells = [c.strip() for c in r.strip("|").split("|")]
        upper = re.search(r"([〇一二三四五六七八九十百千万]+)円以下の金額", cells[0])
        rate = kanji_int(re.fullmatch(r"百分の([〇一二三四五六七八九十]+)", cells[1]).group(1))
        rates.append((kanji_int(upper.group(1)) if upper else None, rate))
    return rates


RATES = parse_rates()


def floor_to(x, unit):
    return (int(x) // unit) * unit if isinstance(x, int) else (x.numerator // (x.denominator * unit)) * unit


def tax_89(kazei):
    t, lo = Fraction(0), 0
    for hi, r in RATES:
        top = kazei if hi is None else min(kazei, hi)
        if top > lo:
            t += Fraction(top - lo) * r / 100
        if hi is None or kazei <= hi:
            break
        lo = hi
    return t


def kurimodoshi(prev_kazei, loss, cap=None):
    a = floor_to(tax_89(floor_to(prev_kazei, 1000)), 100)
    b = floor_to(tax_89(floor_to(max(prev_kazei - loss, 0), 1000)), 100)
    return (a - b if cap is None else min(a - b, cap)), a, b


# ---------------------------------------------------------------- 8. 基礎控除・扶養親族の上限（2026-11-30 と 2026-12-01 の版から読む）
def kiso_tables(asof):
    s = sections(ASOF / f"shotoku_{asof}.txt")
    k = sections(ASOF / f"sochi_{asof}.txt")
    base = []
    for ln in s["86"]:
        m = re.match(r"^  [一二三四]　その居住者の合計所得金額が(?:([〇一二三四五六七八九十百千万]+)円を超え)?([〇一二三四五六七八九十百千万]+)円以下である場合　([〇一二三四五六七八九十百千万]+)円$", ln)
        if m:
            base.append((kanji_int(m.group(2)), kanji_int(m.group(3))))
    add = []
    sub = paragraphs(k["41_16_2"])[1]
    blk = re.search(r"一　令和[七八]年分及び令和[八九]年分　次に掲げる場合の区分に応じそれぞれ次に定める金額\n((?:    .*\n?)+)", sub)
    for ln in blk.group(1).splitlines():
        m = re.search(r"合計所得金額が(?:([〇一二三四五六七八九十百千万]+)円を超え)?(?:([〇一二三四五六七八九十百千万]+)円以下)?(?:を超える)?である場合　([〇一二三四五六七八九十百千万]+)円", ln)
        m2 = re.search(r"合計所得金額が([〇一二三四五六七八九十百千万]+)円を超える場合　([〇一二三四五六七八九十百千万]+)円", ln)
        if m2:
            add.append((None, kanji_int(m2.group(2))))
        elif m:
            add.append((kanji_int(m.group(2)), kanji_int(m.group(3))))
    fuyo = re.search(r"のうち、合計所得金額が([〇一二三四五六七八九十百千万]+)円以下である者をいう。", item(s["2"], "三十四"))
    return {"base_86": base, "add_41_16_2": add, "fuyo_limit_2_34": kanji_int(fuyo.group(1)), "sochi_caption": k["41_16_2"][0]}


def kiso(tbl, gokei):
    b = next(v for hi, v in tbl["base_86"] if gokei <= hi) if gokei <= tbl["base_86"][-1][0] else 0
    a = next(v for hi, v in tbl["add_41_16_2"] if hi is None or gokei <= hi)
    return b, a, b + a


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    res, txt = {}, []

    # 1. 構造
    st = [structure(p) for p in sys.argv[1:3]]
    res["structure"] = st
    txt.append("[1] 所得税法 第120条〜第142条の属する編・章・節・款")
    for s in st:
        txt.append(f"  {s['law_revision_id']}")
        prev = None
        for a in s["articles"]:
            path = " / ".join(a["path"])
            if path != prev:
                txt.append(f"    {path}")
                prev = path
            txt.append(f"      第{a['num']}条 {a['caption']}")
    same = st[0]["articles"] == st[1]["articles"]
    res["structure_same_between_asofs"] = same
    txt.append(f"  2つの版で同じ: {same}")

    # 2. 条文の文言
    lc = law_checks()
    res["law_checks"] = lc
    txt.append("[2] 条文の文言の検査（True＝期待どおり）")
    for r in lc:
        txt.append(f"  {r['id']} {r['desc']}: " + ", ".join(f"{a}={v}" for a, v in r["by_asof"].items()))

    # 3. 国税庁の「見積」
    nm = nta_mitsumori()
    res["nta_mitsumori"] = nm
    txt.append(f"[3] 国税庁の HTML のテキストで「見積」を含む行：{len(nm)} 行")
    for r in nm:
        txt.append(f"  {r['file']}:{r['line']} {r['text'][:160]}")

    # 4. PDF 目視の引用
    pq = pdf_quotes()
    res["pdf_quotes"] = pq
    summ = json.loads((PDFT / "summary.json").read_text(encoding="utf-8"))["files"]
    res["pdftext_summary"] = {k: {kk: v[kk] for kk in ("sha256", "encrypt", "key_ok", "pages", "text_runs", "lines", "replacement_chars")} for k, v in summ.items()}
    n_raw = sum(1 for r in pq if r["found_raw_in"])
    n_n = sum(1 for r in pq if r["found_nfkc_in"])
    txt.append(f"[4] calc.py quotes で見つからなかった引用 {len(pq)} 件を PDF から取り出した文字で照合：そのまま {n_raw} 件、NFKC で {n_n} 件が見つかった")
    for k, v in res["pdftext_summary"].items():
        txt.append(f"  PDF {k}: 暗号 {v['encrypt']} 鍵 {v['key_ok']} 頁 {v['pages']} 文字列 {v['text_runs']} 置換文字 {v['replacement_chars']}")
    for r in pq:
        txt.append(f"  {'○' if r['found_nfkc_in'] else '×'} {r['quote'][:60]}  {r['found_nfkc_in']}")

    # 5. 期限
    dl = {}
    rows = []
    for k in [D(y, 8, 27) + dt.timedelta(days=i) for y in (2025, 2026, 2027) for i in range(8)]:
        raw = junkaku_deadline_A(k)
        sh, trail = shift_holiday(raw)
        rows.append({"knew": k.isoformat(), "raw": f"{raw.isoformat()}({WD[raw.weekday()]})", "deadline": sh.isoformat() if sh else None, "trail": trail})
    dl["year_end"] = rows
    txt.append("[5a] 準確定申告の期限（年末年始にかかる例。1月2日・3日は未確定）")
    for r in rows:
        txt.append(f"  知った日 {r['knew']} → 満了 {r['raw']} → 期限 {r['deadline']}  {r['trail'][-1]}")
    heirs = []
    for name, knew, dep in [("相続人A", D(2026, 6, 20), None), ("相続人B", D(2026, 7, 10), None), ("相続人C", D(2026, 6, 20), D(2026, 9, 12))]:
        raw = junkaku_deadline_A(knew)
        sh, trail = shift_holiday(raw)
        if dep and dep < (sh or raw):
            heirs.append({"heir": name, "knew": knew.isoformat(), "deadline": f"出国の時（{dep.isoformat()}({WD[dep.weekday()]})。通則令2①一で繰り下げない）"})
        else:
            heirs.append({"heir": name, "knew": knew.isoformat(), "deadline": sh.isoformat() if sh else None})
    dl["heirs"] = heirs
    txt.append("[5b] 相続人ごとの期限（知った日が違う・期限の前に出国する。架空の日付）")
    for h in heirs:
        txt.append(f"  {h['heir']} 知った日 {h['knew']} → {h['deadline']}")
    early = []
    for death in [D(2027, 1, 15), D(2027, 3, 10), D(2027, 3, 15), D(2027, 3, 16)]:
        d3, d3trail = daisanki_end(2026)
        raw = junkaku_deadline_A(death)
        sh, trail = shift_holiday(raw)
        # 第三期の末日が決まらない（3月の休日が取得した資料で決まらない）ときは、3月15日以前の死亡だけ「適用あり」と言える
        applies = (death <= d3) if d3 else (True if death <= D(2027, 3, 15) else None)
        early.append({"death_and_knew": death.isoformat(), "daisanki_end_2026": d3.isoformat() if d3 else f"未確定（{d3trail[-1]}）", "124_applies": applies,
                      "deadline_2026_return": ((sh.isoformat() if sh else None) if applies else
                                               ("期限後申告（所基通124・125−2）" if applies is False else "未確定（第三期の末日が決まらない）")),
                      "deadline_2027_return_125": sh.isoformat() if sh else None})
    dl["early_next_year"] = early
    txt.append("[5c] 翌年の初めの死亡（前年分＝2026年分、死亡年分＝2027年分。死亡の日に知った）")
    for e in early:
        txt.append(f"  死亡 {e['death_and_knew']}: 2026年分の第三期の末日 {e['daisanki_end_2026']}、124①の適用 {e['124_applies']}、"
                   f"2026年分の期限 {e['deadline_2026_return']}、2027年分（125①）の期限 {e['deadline_2027_return_125']}")
    res["deadlines"] = dl

    # 6. 判定の時点と年齢（死亡の時と12月31日）
    death = D(2026, 6, 30)
    ages = []
    for label, birth, lo, hi in [("16歳の境（控除対象扶養親族・居住者）", D(2010, 9, 1), 16, None),
                                 ("19歳の境（特定扶養親族）", D(2007, 8, 1), 19, 23),
                                 ("23歳の境（特定扶養親族）", D(2003, 7, 15), 19, 23),
                                 ("70歳の境（老人扶養親族）", D(1956, 10, 1), 70, None)]:
        a1, a2 = age_at(birth, death), age_at(birth, D(2026, 12, 31))
        f = (lambda a: a >= lo and (hi is None or a < hi))
        ages.append({"label": label, "birth": birth.isoformat(), "age_at_death": a1, "age_at_dec31": a2,
                     "meets_at_death": f(a1), "meets_at_dec31": f(a2)})
    res["ages"] = {"death_of_taxpayer": death.isoformat(), "rows": ages}
    txt.append(f"[6] 年齢の境（納税者の死亡 {death}。架空の生年月日）")
    for a in ages:
        txt.append(f"  {a['label']} 生年月日 {a['birth']}: 死亡の時 {a['age_at_death']} 歳（該当 {a['meets_at_death']}）、12月31日 {a['age_at_dec31']} 歳（該当 {a['meets_at_dec31']}）")

    # 7. 相続人の繰戻し還付（141①と141④を同じ年に。架空の金額）
    #   2026年9月に死亡。2026年分（死亡年）の純損失 L1、2025年分（前年）の純損失 L0（2025年分の申告では繰り戻さず繰り越した）、
    #   2024年分（前前年）の課税総所得金額 K2。2025年分は純損失の年なので課税総所得金額は 0。
    L1, L0, K2 = 1_000_000, 600_000, 5_000_000
    used_2026 = 0  # 2026年分は純損失の年で総所得金額が 0 なので、繰越控除（70①）で使う額は 0
    r141_1 = kurimodoshi(0, L1)
    r141_4 = kurimodoshi(K2, L0 - used_2026)
    res["kurimodoshi_combo"] = {"L1_2026": L1, "L0_2025": L0, "K_2024": K2, "141_1_refund": r141_1[0], "141_4_refund": r141_4[0],
                                "141_4_tax_before": r141_4[1], "141_4_tax_after": r141_4[2],
                                "L1_left_after_death": L1, "note": "死亡した者の純損失の残りは相続人が使えない（所基通70−15）"}
    txt.append(f"[7] 相続人の繰戻し：141①（2026年の純損失 {L1} → 2025年分。課税総所得 0）還付 {r141_1[0]}、"
               f"141④（2025年の純損失 {L0} → 2024年分。課税総所得 {K2}）還付 {r141_4[0]}（前 {r141_4[1]} → 後 {r141_4[2]}）、2026年の純損失の残り {L1} は消える")

    # 8. 基礎控除と扶養親族の上限：2026-11-30 に出すか 2026-12-01 に出すか（令和8年分の準確定申告）
    t1, t2 = kiso_tables("2026-11-30"), kiso_tables("2026-12-01")
    res["kiso_tables"] = {"2026-11-30": t1, "2026-12-01": t2}
    rows = []
    for g in [1_000_000, 2_000_000, 4_000_000, 5_000_000]:
        b1, b2 = kiso(t1, g), kiso(t2, g)
        rows.append({"gokei": g, "filed_2026-11-30": b1, "filed_2026-12-01": b2, "diff": b2[2] - b1[2]})
    res["kiso_by_filing_date"] = rows
    est = 600_000
    res["fuyo_by_filing_date"] = {"estimated_gokei_of_relative": est, "limit_2026-11-30": t1["fuyo_limit_2_34"], "limit_2026-12-01": t2["fuyo_limit_2_34"],
                                  "fuyo_2026-11-30": est <= t1["fuyo_limit_2_34"], "fuyo_2026-12-01": est <= t2["fuyo_limit_2_34"]}
    txt.append(f"[8] 令和8年分の準確定申告の基礎控除（所法86①＋措法41の16の2①）：2026-11-30 の版 {t1['base_86'][:1]}+{t1['add_41_16_2']}、2026-12-01 の版 {t2['base_86'][:1]}+{t2['add_41_16_2']}")
    for r in rows:
        txt.append(f"  合計所得金額 {r['gokei']}: 11-30 提出 {r['filed_2026-11-30']}、12-01 提出 {r['filed_2026-12-01']}、差 {r['diff']}")
    f = res["fuyo_by_filing_date"]
    txt.append(f"  扶養親族の上限（所法2①三十四）：11-30 {f['limit_2026-11-30']}、12-01 {f['limit_2026-12-01']}。見積り {est} の親族は 11-30 提出で扶養親族 {f['fuyo_2026-11-30']}、12-01 提出で {f['fuyo_2026-12-01']}")

    # 9. 2026-11-30・2026-12-01 の版と、既存の取得（2026-11-09・2026-12-31）の版の条の本文が同じか
    cross = []
    for short, num, a_new, a_old in [("shotoku", "2", "2026-11-30", "2026-11-09"), ("shotoku", "2", "2026-12-01", "2026-12-31"),
                                     ("sochi", "41_16_2", "2026-11-30", "2026-11-09"), ("sochi", "41_16_2", "2026-12-01", "2026-12-31")]:
        x = "\n".join(sections(ASOF / f"{short}_{a_new}.txt")[num]).strip()
        y = "\n".join(sections(LAWS / f"{short}_{a_old}.txt")[num]).strip()
        cross.append({"law": short, "num": num, "asof_new": a_new, "asof_existing": a_old, "same": x == y})
    res["cross_asof"] = cross
    txt.append("[9] 追加の版と既存の取得の版の比較（条の本文）")
    for c in cross:
        txt.append(f"  {c['law']}:{c['num']} {c['asof_new']} と {c['asof_existing']}: 同じ {c['same']}")

    (OUT / "checks.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (OUT / "checks.txt").write_text("\n".join(txt) + "\n", encoding="utf-8")
    print("\n".join(txt))
    return 0


def quotes_all(md_paths):
    """文書の「」内の引用（8文字以上）が、取得したテキストのどれに含まれるか（空白を除いて比較。… は区切り）。"""
    groups = {"laws": sorted(LAWS.glob("*.txt")), "asof": sorted(ASOF.glob("*.txt")),
              "nta": sorted(NTA.glob("*/*.txt")), "pdftext": sorted(PDFT.glob("*.txt"))}
    corpus = {g: re.sub(r"\s+", "", "".join(p.read_text(encoding="utf-8") for p in ps)) for g, ps in groups.items()}
    rows = []
    for mp in md_paths:
        text = (ROOT / mp).read_text(encoding="utf-8")
        for q in re.findall(r"「([^「」]{8,})」", text):
            pieces = [x for x in re.sub(r"\s+", "", q.replace("…", "|")).split("|") if x]
            rows.append({"doc": mp, "quote": q, "found_in": [g for g, c in corpus.items() if all(x in c for x in pieces)]})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "quotes_all.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    for mp in md_paths:
        rr = [r for r in rows if r["doc"] == mp]
        nf = [r for r in rr if not r["found_in"]]
        print(f"{mp}: 引用 {len(rr)} 件、見つかった {len(rr) - len(nf)} 件、見つからない {len(nf)} 件")
        for r in nf:
            print("  NOT FOUND:", r["quote"][:100])


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "quotes":
        quotes_all(sys.argv[2:])
        sys.exit(0)
    sys.exit(main())

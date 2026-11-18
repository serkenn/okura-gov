r"""R2B_nenkin: 公的年金等の雑所得について、取得した条文と行政の案内を突き合わせる（ネットワークに接続しない）。

実行:
  C:\Users\user\.pyenv\pyenv-win\versions\3.11.9\python.exe -I -X utf8 scripts/R2B_nenkin_verify.py
標準ライブラリのみ。入力は先に実行した次の結果（信頼できないデータとして読むだけ。中のコードは実行しない）：
  scripts/results/R2B_nenkin_egov/articles/*.txt     （scripts/R2B_nenkin_egov.py）
  scripts/results/R2B_nenkin_egov2/articles_*.txt    （scripts/R2B_nenkin_egov2.py）
  .work/text/<ts>_R2B_nenkin_nenkin/nenkin_shotokuzeikojo.txt （scripts/R2B_nenkin_web.py nenkin が HTML から取り出したテキスト）
出力：scripts/results/R2B_nenkin_verify/report.md と report.json

検査（V1〜V6）
  V1 所法35条1〜4項・121条・措法41条の15の3第1項と第4項の文言が、令和7年分（2025-12-31 版）・令和8年分（2026-12-31 版）・
     2027-01-01 版で同じか（所法35条は第5項の有無も）
  V2 所法35条4項と措法41条の15の3第1項から組んだ公的年金等控除額の式（整数・分数で計算）と、
     国税庁 TA No.1600 の「公的年金等に係る雑所得の速算表（令和2年分以後）」（画像。下の NTA_TABLE に目で読んで書き写した）が、
     収入金額のあらゆる点で同じ雑所得の金額を与えるか（1,000円刻み＋境目の前後＋乱数で選んだ整数）
  V3 V2 の式で、円未満の端数が出る収入金額がどれだけあるか（端数処理は条文にない）
  V4 TA No.1600 の計算例（65歳以上・公的年金等以外の合計所得金額 500万円・収入 350万円 → 235万円）
  V5 源泉徴収を要しない公的年金等の額（所法203条の7）を、所令319条の12・措令26条の27・措令26条の27の2第2項の
     読替えの連鎖から年ごとに組み立て、日本年金機構「老齢年金から源泉徴収される所得税の控除を受けるとき」の表と比べる
  V6 「令和8年分で65歳以上 ＝ 昭和37年1月1日以前に生まれた人」（国税庁「暮らしの税情報」令和8年度版の注）を、
     措法41条の15の3第4項（12月31日の年齢）と年齢の数え方の式（docs/measurements/20261109_impl-prep_misc-fetch-and-age-check.md の式A）で確かめる
"""
import datetime
import json
import pathlib
import random
import re
import sys
from fractions import Fraction as F

ROOT = pathlib.Path(__file__).resolve().parent.parent
R1 = ROOT / "scripts" / "results" / "R2B_nenkin_egov" / "articles"
R2 = ROOT / "scripts" / "results" / "R2B_nenkin_egov2"
OUT = ROOT / "scripts" / "results" / "R2B_nenkin_verify"

# ---------------- 漢数字 ----------------
KD = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def kan_small(s):
    """千・百・十を含む4桁以下の漢数字を整数にする。"""
    n, cur = 0, 0
    for ch in s:
        if ch in KD:
            cur = KD[ch]
        elif ch in "千百十":
            m = {"千": 1000, "百": 100, "十": 10}[ch]
            n += (cur or 1) * m
            cur = 0
        else:
            raise ValueError(s)
    return n + cur


def kan_yen(s):
    """「百十八万円」「八十万円」「十四万円」「百五十五万五千円」などを円の整数にする。"""
    s = s.replace("円", "")
    total = 0
    if "億" in s:
        a, s = s.split("億", 1)
        total += kan_small(a) * 10 ** 8
    if "万" in s:
        a, s = s.split("万", 1)
        total += kan_small(a) * 10 ** 4
    if s:
        total += kan_small(s)
    return total


# ---------------- 条文の切り出し ----------------
def section(text, header_re):
    m = re.search(header_re, text, re.M)
    if not m:
        return None
    rest = text[m.end():]
    n = re.search(r"^## ", rest, re.M)
    return rest[: n.start()] if n else rest


def paragraphs(sec):
    """条のテキストを項ごとに分ける（行頭の「（Paragraph1）」「２　」…）。号は直前の項に含める。"""
    out, cur = {}, None
    for line in sec.splitlines():
        m = re.match(r"^（Paragraph1）|^([２-９]|１[０-９])　", line)
        if m:
            cur = "1" if line.startswith("（Paragraph1）") else str(int(m.group(1).translate(str.maketrans("０１２３４５６７８９", "0123456789"))))
            out[cur] = []
        if cur:
            out[cur].append(line)
    return {k: "\n".join(v) for k, v in out.items()}


# ---------------- V2：公的年金等控除の式（条文から組んだもの） ----------------
def kojo_law(A, other, age65):
    """所法35条4項（各号）と措法41条の15の3第1項の読替え。A＝公的年金等の収入金額、other＝公的年金等に係る雑所得以外の合計所得金額。"""
    if other <= 10_000_000:
        i, mn = 400_000, 600_000
    elif other <= 20_000_000:
        i, mn = 300_000, 500_000
    else:
        i, mn = 200_000, 400_000
    if age65:
        mn = {600_000: 1_100_000, 500_000: 1_000_000, 400_000: 900_000}[mn]
    r = max(0, A - 500_000)          # 「収入金額から五十万円を控除した残額」。A<50万 のときは 0 とした（結果に影響しない：最低額が上回る）
    if r <= 3_600_000:
        b = F(r, 4)
    elif r <= 7_200_000:
        b = 900_000 + F(r - 3_600_000) * F(15, 100)
    elif r <= 9_500_000:
        b = 1_440_000 + F(r - 7_200_000) * F(5, 100)
    else:
        b = F(1_555_000)
    k = i + b
    if k < mn:
        k = F(mn)
    return k


def zatsu_law(A, other, age65):
    k = kojo_law(A, other, age65)
    return max(F(0), A - k)


# 国税庁 TA No.1600「公的年金等に係る雑所得の速算表（令和2年分以後）」図1〜図3（目で読んで書き写した）
# 行：(下限, 下限を含むか, 上限, 上限を含むか, 率(分数), 差し引く額)。率 None は「0円」。率 1 は「収入金額の合計額 − 額」。
def _rows(z, a1, a2, minus_75, minus_85, minus_95, minus_top):
    return [
        (0, True, z, True, None, 0),
        (z, False, a1, False, F(1), z),
        (a1, True, 4_100_000, False, F(75, 100), minus_75),
        (4_100_000, True, 7_700_000, False, F(85, 100), minus_85),
        (7_700_000, True, 10_000_000, False, F(95, 100), minus_95),
        (10_000_000, True, None, None, F(1), minus_top),
    ]


NTA_TABLE = {
    # (区分, 65歳以上か)
    (1, False): _rows(600_000, 1_300_000, None, 275_000, 685_000, 1_455_000, 1_955_000),
    (1, True): _rows(1_100_000, 3_300_000, None, 275_000, 685_000, 1_455_000, 1_955_000),
    (2, False): _rows(500_000, 1_300_000, None, 175_000, 585_000, 1_355_000, 1_855_000),
    (2, True): _rows(1_000_000, 3_300_000, None, 175_000, 585_000, 1_355_000, 1_855_000),
    (3, False): _rows(400_000, 1_300_000, None, 75_000, 485_000, 1_255_000, 1_755_000),
    (3, True): _rows(900_000, 3_300_000, None, 75_000, 485_000, 1_255_000, 1_755_000),
}
TIER_OTHER = {1: 5_000_000, 2: 15_000_000, 3: 25_000_000}


def zatsu_nta(A, tier, age65):
    for lo, lo_inc, hi, hi_inc, rate, minus in NTA_TABLE[(tier, age65)]:
        ok_lo = A >= lo if lo_inc else A > lo
        ok_hi = True if hi is None else (A <= hi if hi_inc else A < hi)
        if ok_lo and ok_hi:
            return F(0) if rate is None else A * rate - minus
    raise ValueError(A)


# ---------------- V6：年齢（式A を写した） ----------------
def age_A(birth, year):
    """12月31日の年齢（docs/measurements/20261109_impl-prep_misc-fetch-and-age-check.md の式A）。"""
    return year - birth.year + (1 if (birth.month, birth.day) == (1, 1) else 0)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    rep = {"generated_at": datetime.datetime.now().isoformat(timespec="seconds")}
    md = ["# R2B_nenkin_verify の結果", "", f"- 実行日時：{rep['generated_at']}", "- 入力：scripts/results/R2B_nenkin_egov/、scripts/results/R2B_nenkin_egov2/、.work/text/*_R2B_nenkin_nenkin/", ""]

    # ---- V1 ----
    v1 = {}
    texts = {a: (R1 / f"shotoku_{a}.txt").read_text(encoding="utf-8") for a in ("2025-12-31", "2026-12-31", "2027-01-01")}
    stexts = {a: (R1 / f"sochi_{a}.txt").read_text(encoding="utf-8") for a in ("2025-12-31", "2026-12-31", "2027-01-01")}
    p35 = {a: paragraphs(section(t, r"^## 本則 Num=35$")) for a, t in texts.items()}
    p121 = {a: paragraphs(section(t, r"^## 本則 Num=121$")) for a, t in texts.items()}
    p4115 = {a: paragraphs(section(t, r"^## 本則 Num=41_15_3$")) for a, t in stexts.items()}
    base = "2025-12-31"
    for a in texts:
        v1[a] = {
            "所法35_項": sorted(p35[a].keys()),
            "所法35_1〜4項が令和7年分と同じ": all(p35[a].get(k) == p35[base].get(k) for k in "1234"),
            "所法121_項": sorted(p121[a].keys()),
            "所法121が令和7年分と同じ": p121[a] == p121[base],
            "措法41の15の3_1項が令和7年分と同じ": p4115[a].get("1") == p4115[base].get("1"),
            "措法41の15の3_4項が令和7年分と同じ": p4115[a].get("4") == p4115[base].get("4"),
            "措法41の15の3_2項が令和7年分と同じ": p4115[a].get("2") == p4115[base].get("2"),
        }
    # 式の定数が条文にあることの確認
    t35 = p35["2026-12-31"]["4"]
    consts = ["六十万円に満たない場合には、六十万円", "五十万円に満たない場合には、五十万円", "四十万円に満たない場合には、四十万円",
              "イ　四十万円", "イ　三十万円", "イ　二十万円", "五十万円を控除した残額", "三百六十万円以下", "百分の二十五", "九十万円と",
              "百分の十五", "百四十四万円と", "百分の五", "百五十五万五千円", "千万円以下", "千万円を超え二千万円以下", "二千万円を超える"]
    t4115 = p4115["2026-12-31"]["1"]
    consts_s = ["「六十万円に」とあるのは「百十万円に」", "「六十万円）」とあるのは「百十万円）」", "「五十万円」とあるのは「百万円」", "「四十万円」とあるのは「九十万円」"]
    v1["式の定数が条文にある（2026-12-31 版）"] = {c: (c in t35) for c in consts} | {c: (c in t4115) for c in consts_s}
    v1["措法41の15の3_4項（2026-12-31 版）"] = p4115["2026-12-31"].get("4")
    rep["V1"] = v1
    md += ["## V1 条文の同一性（版の間）", "", "| 版 | 所法35 の項 | 35①〜④が令和7年分と同じ | 所法121 の項 | 121 が同じ | 措法41の15の3①が同じ | ②が同じ | ④が同じ |", "|---|---|---|---|---|---|---|---|"]
    for a in texts:
        x = v1[a]
        md.append(f"| {a} | {','.join(x['所法35_項'])} | {x['所法35_1〜4項が令和7年分と同じ']} | {','.join(x['所法121_項'])} | {x['所法121が令和7年分と同じ']} | "
                  f"{x['措法41の15の3_1項が令和7年分と同じ']} | {x['措法41の15の3_2項が令和7年分と同じ']} | {x['措法41の15の3_4項が令和7年分と同じ']} |")
    miss = [c for c, ok in v1["式の定数が条文にある（2026-12-31 版）"].items() if not ok]
    md += ["", f"- 式に使った定数の文字列が条文にない：{miss if miss else 'なし（すべてある）'}", ""]

    # ---- V2・V3 ----
    pts = set(range(0, 12_000_001, 1000))
    bnd = [400_000, 500_000, 600_000, 900_000, 1_000_000, 1_100_000, 1_300_000, 3_300_000, 4_100_000, 7_700_000, 9_500_000, 10_000_000, 10_000_001]
    for b in bnd:
        for d in range(-5, 6):
            if b + d >= 0:
                pts.add(b + d)
    rng = random.Random(20261109)
    for _ in range(200_000):
        pts.add(rng.randrange(0, 15_000_000))
    pts = sorted(pts)
    v2 = {}
    frac_count = {}
    for tier, other in TIER_OTHER.items():
        for age65 in (False, True):
            mism = []
            nfrac = 0
            for A in pts:
                zl = zatsu_law(A, other, age65)
                zn = zatsu_nta(A, tier, age65)
                if zl != zn:
                    mism.append({"A": A, "law": str(zl), "nta": str(zn)})
                if zl.denominator != 1:
                    nfrac += 1
            key = f"tier{tier}_{'65以上' if age65 else '65未満'}"
            v2[key] = {"points": len(pts), "mismatches": len(mism), "first_mismatches": mism[:5]}
            frac_count[key] = nfrac
    # 公的年金等以外の合計所得金額の境目（1,000万円・2,000万円ちょうど）
    edge = {}
    for other in (10_000_000, 10_000_001, 20_000_000, 20_000_001):
        edge[str(other)] = {"A=2,000,000 65未満の控除額": str(kojo_law(2_000_000, other, False)),
                            "A=2,000,000 65以上の控除額": str(kojo_law(2_000_000, other, True))}
    rep["V2"] = {"by_table": v2, "other_income_edges": edge}
    rep["V3_fractional_points"] = frac_count
    md += ["## V2 条文の式と TA No.1600 速算表の比較", "", "| 区分（公的年金等以外の合計所得金額） | 年齢 | 比べた点 | 不一致 |", "|---|---|---|---|"]
    for k, v in v2.items():
        md.append(f"| {k.split('_')[0]}（{TIER_OTHER[int(k[4])]:,}円で代表） | {k.split('_')[1]} | {v['points']:,} | {v['mismatches']} |")
    md += ["", "公的年金等以外の合計所得金額の境目での控除額（収入 200万円）：", ""]
    for o, v in edge.items():
        md.append(f"- {int(o):,}円：65歳未満 {v['A=2,000,000 65未満の控除額']}、65歳以上 {v['A=2,000,000 65以上の控除額']}")
    md += ["", "## V3 円未満の端数が出る点の数（V2 で比べた点のうち）", ""]
    for k, n in frac_count.items():
        md.append(f"- {k}：{n:,} 点")
    ex = [1_300_001, 1_300_002, 4_100_001, 7_700_001]
    md += ["", "例（区分1・65歳未満）：" + "、".join(f"収入 {a:,} → 雑所得 {zatsu_law(a, 5_000_000, False)}（={float(zatsu_law(a, 5_000_000, False)):,.2f}）" for a in ex), ""]
    rep["V3_examples"] = {str(a): str(zatsu_law(a, 5_000_000, False)) for a in ex}

    # ---- V4 ----
    v4 = zatsu_law(3_500_000, 5_000_000, True)
    rep["V4"] = {"computed": str(v4), "expected": "2350000", "ok": v4 == 2_350_000}
    md += ["## V4 TA No.1600 の計算例", "", f"- 65歳以上・公的年金等以外の合計所得金額 500万円・収入 350万円 → 条文の式で {v4}（TA：2,350,000円）→ 一致：{v4 == 2_350_000}", ""]

    # ---- V5 ----
    def read2(name):
        return (R2 / name).read_text(encoding="utf-8")
    year_asof = {2025: "2025-12-31", 2026: "2026-01-01", 2027: "2027-01-01"}
    reiwa = {"令和七年": 2025, "令和八年": 2026, "令和九年": 2027, "令和十年": 2028}
    v5 = {}
    for y, asof in year_asof.items():
        so = read2(f"articles_shotoku-rei_{asof}.txt")
        sr = read2(f"articles_sochi-rei_{asof}.txt")
        base_amt = kan_yen(re.search(r"第三百十九条の十二\n（Paragraph1）　法第二百三条の七（源泉徴収を要しない公的年金等）に規定する政令で定める金額は、(.+?)円とする", so).group(1))
        s27 = section(sr, r"^## 本則 Num=26_27$")
        m = re.search(r"同条中「(.+?)円」とあるのは、「(.+?)円（同条に規定する公的年金等が.+?場合にあつては、(.+?)円）」とする", s27)
        ref27, amt65, amt_kyosai = kan_yen(m.group(1)), kan_yen(m.group(2)), kan_yen(m.group(3))
        s272 = section(sr, r"^## 本則 Num=26_27_2$")
        p2 = paragraphs(s272).get("2", "")
        m2 = re.search(r"２　(令和.+?年)(以後の各年)?において、", p2)
        cond_year = reiwa[m2.group(1)]
        cond_after = bool(m2.group(2))
        applies = (y >= cond_year) if cond_after else (y == cond_year)
        repl = [(kan_yen(a), kan_yen(b)) for a, b in re.findall(r"「([^「」]+?万円)」とあるのは「([^「」]+?万円)」", p2)]
        # repl[0]：所令319の12 の読替え（基本額）、残り：措令26の27 の中の読替え
        under65, over65, kyosai = base_amt, amt65, amt_kyosai
        steps = [f"所令319の12：{base_amt:,}円", f"措令26の27：「{ref27:,}円」→ 65歳以上 {amt65:,}円（一定の退職共済年金等 {amt_kyosai:,}円）"]
        if ref27 != base_amt:
            steps.append(f"注意：措令26の27 が引用する額 {ref27:,} と所令319の12 の額 {base_amt:,} が一致しない")
        if applies:
            mp = dict(repl[1:])
            under65 = dict(repl[:1]).get(base_amt, base_amt)
            over65 = mp.get(amt65, amt65)
            kyosai = mp.get(amt_kyosai, amt_kyosai)
            steps.append(f"措令26の27の2②（{m2.group(1)}{m2.group(2) or ''}）を適用：{repl}")
        else:
            steps.append(f"措令26の27の2②（{m2.group(1)}{m2.group(2) or ''}）は {y} 年に適用しない")
        v5[y] = {"asof": asof, "under65": under65, "over65": over65, "kyosai": kyosai, "steps": steps}
    # 日本年金機構の表
    tdir = sorted((ROOT / ".work" / "text").glob("*_R2B_nenkin_nenkin"))[-1]
    ntxt = (tdir / "nenkin_shotokuzeikojo.txt").read_text(encoding="utf-8")
    def row(label):
        line = [l for l in ntxt.splitlines() if label in l and "万円" in l][0]
        return [int(x) * 10_000 for x in re.findall(r"(\d+)万円", line)]
    nk = {"under65": row("65歳未満の方"), "over65": row("65歳以上の方"), "kyosai": row("退職共済年金の受給者")}
    cmp5 = {}
    for i, y in enumerate((2025, 2026, 2027)):
        cmp5[y] = {k: {"law_chain": v5[y][k], "nenkin": nk[k][i], "ok": v5[y][k] == nk[k][i]} for k in ("under65", "over65", "kyosai")}
    rep["V5"] = {"law_chain": v5, "nenkin_table": nk, "compare": cmp5, "nenkin_text_file": str((tdir / "nenkin_shotokuzeikojo.txt").relative_to(ROOT))}
    md += ["## V5 源泉徴収を要しない公的年金等の額（所法203の7）の読替えの連鎖と日本年金機構の表", "",
           "| 年 | 版 | 65歳未満（条文の連鎖／機構） | 65歳以上 | 一定の退職共済年金（老齢基礎年金を受ける人） | 一致 |", "|---|---|---|---|---|---|"]
    for y in (2025, 2026, 2027):
        c = cmp5[y]
        md.append(f"| {y} | {v5[y]['asof']} | {c['under65']['law_chain']:,}／{c['under65']['nenkin']:,} | {c['over65']['law_chain']:,}／{c['over65']['nenkin']:,} | "
                  f"{c['kyosai']['law_chain']:,}／{c['kyosai']['nenkin']:,} | {all(v['ok'] for v in c.values())} |")
    md.append("")
    for y in (2025, 2026, 2027):
        md.append(f"- {y}：" + "／".join(v5[y]["steps"]))
    md += ["", "（機構の表は「〜円以上」で源泉徴収の対象、条文は「〜円に満たないとき」源泉徴収を要しない。境目の向きは同じ。）", ""]

    # ---- V6 ----
    cases = [datetime.date(1961, 12, 31), datetime.date(1962, 1, 1), datetime.date(1962, 1, 2)]
    v6 = {str(b): {"age_on_2026-12-31(式A)": age_A(b, 2026), "65以上": age_A(b, 2026) >= 65,
                   "NTA注「昭和37年1月1日以前」": b <= datetime.date(1962, 1, 1)} for b in cases}
    rep["V6"] = v6
    md += ["## V6 令和8年分の「65歳以上」の生年月日", "", "| 生年月日 | 2026-12-31 の年齢（式A） | 65歳以上 | NTA の注（昭和37年1月1日以前） | 一致 |", "|---|---|---|---|---|"]
    for b, v in v6.items():
        md.append(f"| {b} | {v['age_on_2026-12-31(式A)']} | {v['65以上']} | {v['NTA注「昭和37年1月1日以前」']} | {v['65以上'] == v['NTA注「昭和37年1月1日以前」']} |")
    md.append("")

    (OUT / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (OUT / "report.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    sys.exit(main())

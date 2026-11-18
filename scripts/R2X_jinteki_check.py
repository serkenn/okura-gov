"""R2X_jinteki: 取り出した条文（scripts/R2X_jinteki_egov.py の出力）から、障害者控除・寡婦控除・ひとり親控除と
住民税の非課税（障害者・寡婦・ひとり親）の金額・要件を版ごとに機械的に拾い、表にする。あわせて次を確かめる。

  1. 版ごとの金額（所得税：令和7年分・令和8年分・令和9年分の版、住民税：令和8年度分・令和9年度分・令和10年度分の版）
  2. 所得税の「障害者の範囲」（所令10①）と住民税の「障害者の範囲」（地令7）の文言が、法令名の書き方の違いを除いて同じか
     特別障害者（所令10② と 地令7の15の7）、寡婦の範囲（所令11 と 地令46の2）、事実婚の範囲（所規1の3・1の4 と 地規1の9の7・1の9の8）も同じ
  3. 国税庁の「給与の収入金額が 6,777,778円以下なら合計所得金額 500万円以下」（年末調整のしかた）を、
     所得税法第28条第3項（既存の取得 scripts/results/R1_egov_articles/）の式で確かめる（1円未満の扱いで結論が変わるか）

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_jinteki_check.py

- ネットワークに接続しない。ダウンロードしたファイル（.work/downloads）は読まない。読むのは scripts/results/ の抽出済みテキストだけ。
- 出力は scripts/results/R2X_jinteki_check/：checks.md（人が読む表）、checks.json（同じ内容）
標準ライブラリのみ。
"""
import json
import pathlib
import re
import sys
from fractions import Fraction

ROOT = pathlib.Path(__file__).resolve().parent.parent
EG = ROOT / "scripts" / "results" / "R2X_jinteki_egov"
R1 = ROOT / "scripts" / "results" / "R1_egov_articles"
OUT = ROOT / "scripts" / "results" / "R2X_jinteki_check"

KDIG = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def kanji_int(s):
    """漢数字（十・百・千・万を含む）を整数にする。例：百三十五万 → 1350000、二十七万 → 270000。"""
    total, section, num = 0, 0, 0
    for ch in s:
        if ch in KDIG:
            num = KDIG[ch]
        elif ch in "十百千":
            unit = {"十": 10, "百": 100, "千": 1000}[ch]
            section += (num or 1) * unit
            num = 0
        elif ch == "万":
            total += (section + num) * 10000
            section, num = 0, 0
        else:
            raise ValueError(f"unexpected {ch!r} in {s!r}")
    return total + section + num


def read(name):
    p = EG / name
    return p.read_text(encoding="utf-8") if p.exists() else ""


def section(text, start_pat, end_pat=r"^## "):
    """'## Num=...' の見出しから次の見出しまでを返す。"""
    m = re.search(start_pat, text, re.M)
    if not m:
        return ""
    rest = text[m.end():]
    e = re.search(end_pat, rest, re.M)
    return rest[: e.start()] if e else rest


def header_rev(text):
    m = re.search(r"law_revision_id=(\S+)", text)
    return m.group(1) if m else None


def amt(pattern, text):
    m = re.search(pattern, text)
    return kanji_int(m.group(1)) * 10000 if m else None  # AMT は「X万円」の X を取り出すので円にする


AMT = r"([〇一二三四五六七八九十百千万]+)万円"


def amounts():
    rows = []
    for asof in ["2025-12-31", "2026-12-31", "2027-01-01"]:
        t = read(f"shotoku_asof{asof}.txt")
        r = read(f"shotoku-rei_asof{asof}.txt")
        a79 = section(t, r"^## Num=79 ")
        a2 = section(t, r"^## Num=2（")
        rows.append({
            "law": "所得税法・同施行令", "asof": asof, "rev": header_rev(t), "rev_rei": header_rev(r),
            "所法79① 障害者": amt(r"山林所得金額から" + AMT + r"（その者が特別障害者", a79),
            "所法79① 特別障害者": amt(r"特別障害者である場合には、" + AMT, a79),
            "所法79③ 同居特別障害者": amt(r"その特別障害者一人につき" + AMT, a79),
            "所法80 寡婦": amt(r"寡婦である場合には[^。]*?から" + AMT, section(t, r"^## Num=80 ")),
            "所法81 ひとり親": amt(r"ひとり親である場合には[^。]*?から" + AMT, section(t, r"^## Num=81 ")),
            "所法2①30 寡婦 合計所得金額": amt(r"「合計所得金額」という。）が" + AMT + "以下", a2),
            "所法2①31 ひとり親 合計所得金額": amt(r"ロ　合計所得金額が" + AMT + "以下", a2),
            "所令11の2② ひとり親の子 総所得金額等": amt(r"山林所得金額の合計額が" + AMT + "以下の子",
                                                    section(r, r"^## Num=11_2 ")),
            "所法85① 12月31日の現況": "その年十二月三十一日" in section(t, r"^## Num=85 "),
        })
    for asof in ["2026-01-01", "2027-01-01", "2028-01-01"]:
        t = read(f"chiho_asof{asof}.txt")
        r = read(f"chiho-rei_asof{asof}.txt")
        s314 = section(t, r"^## Num=314_2 ")
        s34 = section(t, r"^## Num=34 ")
        s292 = section(t, r"^## Num=292 ")
        s295 = section(t, r"^## Num=295 ")
        row = {"law": "地方税法・同施行令", "asof": asof, "rev": header_rev(t), "rev_rei": header_rev(r)}
        for tag, s in (("314の2", s314), ("34", s34)):
            row[f"地法{tag}①六 障害者"] = amt(r"各障害者につき" + AMT, s)
            row[f"地法{tag}①六 特別障害者"] = amt(r"各障害者につき[^\n]*?である場合には、" + AMT + "）", s)
            row[f"地法{tag}③ 同居特別障害者"] = amt(r"第一項第六号の金額は、" + AMT, s)
            row[f"地法{tag}①八 寡婦"] = amt(r"八　寡婦である所得割の納税義務者　" + AMT, s)
            row[f"地法{tag}①八の二 ひとり親"] = amt(r"八の二　ひとり親である所得割の納税義務者　" + AMT, s)
        row["地法295①二 非課税 合計所得金額"] = amt(r"寡婦又はひとり親（これらの者の前年の合計所得金額が" + AMT, s295)
        row["地法292①十一 寡婦 前年の合計所得金額"] = amt(r"（２）　前年の合計所得金額が" + AMT + "以下", s292)
        row["地法292①十二 ひとり親 前年の合計所得金額"] = amt(r"ロ　前年の合計所得金額が" + AMT + "以下", s292)
        row["地令46の2の2② ひとり親の子"] = amt(r"山林所得金額の合計額が" + AMT + "以下の子", section(r, r"^## Num=46_2_2 "))
        row["地令7の2の2② ひとり親の子（道府県民税）"] = amt(r"山林所得金額の合計額が" + AMT + "以下の子", section(r, r"^## Num=7_2_2 "))
        row["地法314の2⑧ 前年12月31日の現況"] = "前年の十二月三十一日" in s314
        row["地令46 → 第7条"] = "第七条に規定する者とする" in section(r, r"^## Num=46 ")
        row["地令48の7② → 第7条の15の7"] = "同項第六号に規定する政令で定める障害者は第七条の十五の七に規定する者とする" in section(r, r"^## Num=48_7 ")
        rows.append(row)
    return rows


# --- 2. 文言の比較 -------------------------------------------------------------
LAWNUM = re.compile(r"（(?:昭和|平成|令和|大正|明治)[^（）]*?(?:法律|政令|省令)第[^（）]*?号）")
CAPREF = re.compile(r"（[^（）]*?(?:の範囲|の意義|定義|の交付|認定|精神障害の状態|精神保健福祉センター|手帳|福祉の措置の実施者|更生援護の実施者|住民票の記載事項)）")


def normalize(s):
    s = LAWNUM.sub("", s)
    for _ in range(3):
        s = CAPREF.sub("", s)
    s = re.sub(r"（Paragraph1）　", "", s)
    s = re.sub(r"^\s+", "", s, flags=re.M)
    return s


def items_of(sec):
    """条の本文から号（一　…）の行だけを取り出す。"""
    out = []
    for ln in sec.splitlines():
        ln = ln.strip()
        if re.match(r"^[一二三四五六七八九十]+　", ln):
            out.append(ln)
    return out


def compare_items(a_sec, b_sec, extra_norm=None):
    a, b = items_of(a_sec), items_of(b_sec)
    res = []
    for i in range(max(len(a), len(b))):
        x = normalize(a[i]) if i < len(a) else None
        y = normalize(b[i]) if i < len(b) else None
        if extra_norm and x and y:
            x, y = extra_norm(x), extra_norm(y)
        res.append({"item": i + 1, "same": x == y, "a": x, "b": y})
    return res


def wording():
    out = {}
    so = read("shotoku-rei_asof2026-12-31.txt")
    ch = read("chiho-rei_asof2027-01-01.txt")
    so10 = section(so, r"^## Num=10 ")
    so10_1, so10_2 = so10.split("\n２　")[0], "２　" + so10.split("\n２　")[1] if "\n２　" in so10 else ""

    def unify(s):
        # 所令は「市町村長又は特別区の区長」、地令は「市町村長」（地令は特別区を法の規定で市とみなす読替えがある：比較では揃える）
        s = s.replace("市町村長又は特別区の区長", "市町村長")
        s = s.replace("知的障害者更生相談所（知的障害者福祉法第九条第六項に規定する知的障害者更生相談所をいう。次項第一号及び第三十一条の二第十四号において同じ。）",
                      "知的障害者福祉法第九条第六項に規定する知的障害者更生相談所")
        s = s.replace("精神保健福祉センター（精神保健及び精神障害者福祉に関する法律第六条第一項に規定する精神保健福祉センターをいう。次項第一号において同じ。）",
                      "精神保健及び精神障害者福祉に関する法律第六条第一項に規定する精神保健福祉センター")
        s = s.replace("。次項第六号において「市町村長等」という。", "。第七条の十五の七第六号において「市町村長等」という。")
        s = re.sub(r"第七条第[一二三四五六七]号に掲げる者", "前項第X号に掲げる者", s)
        s = re.sub(r"前項第[一二三四五六七]号に掲げる者", "前項第X号に掲げる者", s)
        s = re.sub(r"前項第[一二三四五六七]号又は第[一二三四五六七]号に掲げる者", "前項第X号又は第Y号に掲げる者", s)
        s = re.sub(r"第七条第[一二三四五六七]号又は第[一二三四五六七]号に掲げる者", "前項第X号又は第Y号に掲げる者", s)
        s = s.replace("知的障害者福祉法第九条第六項に規定する知的障害者更生相談所、精神保健及び精神障害者福祉に関する法律第六条第一項に規定する精神保健福祉センター", "知的障害者更生相談所、精神保健福祉センター")
        s = s.replace("法の施行地内", "国内").replace("法の施行地外", "国外")
        s = s.replace("前各号に掲げる者を除くほか", "前各号に掲げる者のほか")
        s = s.replace("滅失し、若しくは", "滅失し若しくは").replace("滅失し、又は", "滅失し又は")
        return s

    out["障害者の範囲 所令10① vs 地令7"] = compare_items(so10_1, section(ch, r"^## Num=7 "), unify)
    out["特別障害者の範囲 所令10② vs 地令7の15の7"] = compare_items(so10_2, section(ch, r"^## Num=7_15_7 "), unify)
    out["寡婦の範囲 所令11 vs 地令46の2"] = compare_items(section(so, r"^## Num=11 "), section(ch, r"^## Num=46_2 "), unify)
    sk = read("shotoku-ki_asof2026-12-31.txt")
    ck = read("chiho-ki_asof2027-01-01.txt")
    out["寡婦の事実婚 所規1の3 vs 地規1の9の7"] = compare_items(section(sk, r"^## Num=1_3 "), section(ck, r"^## Num=1_9_7 "))
    out["ひとり親の事実婚 所規1の4 vs 地規1の9の8"] = compare_items(section(sk, r"^## Num=1_4 "), section(ck, r"^## Num=1_9_8 "))
    return out


# --- 3. 6,777,778円の確認 ------------------------------------------------------
def kyuyo_500man():
    res = []
    pat = "百七十六万円と当該収入金額から六百六十万円を控除した金額の百分の十に相当する金額との合計額"
    for f in ["shotoku_2025-12-31.txt", "shotoku_2026-12-01.txt"]:
        t = (R1 / f).read_text(encoding="utf-8")
        s28 = section(t, r"^## Num=28$")
        has = pat in s28
        has_range = "六百六十万円を超え八百五十万円以下である場合" in s28
        for income in (6_777_777, 6_777_778, 6_777_779):
            ded = Fraction(1_760_000) + Fraction(income - 6_600_000, 10)
            shotoku = Fraction(income) - ded
            res.append({"source": f"scripts/results/R1_egov_articles/{f}", "式が条文にある": has and has_range,
                        "給与収入": income, "給与所得控除額（端数そのまま）": f"{float(ded):.1f}",
                        "給与所得（端数そのまま）": f"{float(shotoku):.1f}",
                        "500万円以下（端数そのまま）": shotoku <= 5_000_000,
                        "500万円以下（1円未満切捨て）": (shotoku.numerator // shotoku.denominator) <= 5_000_000})
    return res


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    rows = amounts()
    wd = wording()
    k5 = kyuyo_500man()
    (OUT / "checks.json").write_text(json.dumps({"amounts": rows, "wording": wd, "kyuyo_500man": k5},
                                                ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# R2X_jinteki_check の結果", "", "入力：scripts/results/R2X_jinteki_egov/*.txt、scripts/results/R1_egov_articles/shotoku_*.txt", ""]
    md.append("## 1. 版ごとの金額・要件（条文から機械的に抽出。金額は円）")
    for law in ("所得税法・同施行令", "地方税法・同施行令"):
        sub = [r for r in rows if r["law"] == law]
        keys = [k for k in sub[0] if k not in ("law", "asof", "rev", "rev_rei")]
        md += ["", f"### {law}", "", "| 項目 | " + " | ".join(r["asof"] for r in sub) + " |",
               "|---|" + "---|" * len(sub)]
        for k in keys:
            md.append(f"| {k} | " + " | ".join(str(r[k]) for r in sub) + " |")
        md.append("| law_revision_id（法） | " + " | ".join(str(r["rev"]) for r in sub) + " |")
        md.append("| law_revision_id（政令） | " + " | ".join(str(r["rev_rei"]) for r in sub) + " |")
    md += ["", "## 2. 所得税と住民税の文言の比較（法令番号の括弧・見出しの参照・自明な書き方の違いを正規化した後）", ""]
    for k, v in wd.items():
        same = all(x["same"] for x in v)
        md.append(f"- {k}：号の数 {len(v)}、すべて同じ = **{same}**")
        for x in v:
            if not x["same"]:
                md.append(f"  - 第{x['item']}号が違う：\n    - A: {x['a']}\n    - B: {x['b']}")
    md += ["", "## 3. 給与収入 6,777,778円と合計所得金額 500万円（所得税法第28条第3項第3号の式）", "",
           "| 版 | 式が条文にある | 給与収入 | 給与所得（端数そのまま） | 500万円以下（端数そのまま） | 500万円以下（1円未満切捨て） |",
           "|---|---|---|---|---|---|"]
    for x in k5:
        md.append(f"| {x['source'].split('/')[-1]} | {x['式が条文にある']} | {x['給与収入']:,} | {x['給与所得（端数そのまま）']} | "
                  f"{x['500万円以下（端数そのまま）']} | {x['500万円以下（1円未満切捨て）']} |")
    (OUT / "checks.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()

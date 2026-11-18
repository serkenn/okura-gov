"""R2X_kyosai: 取得済みの条文（scripts/R2X_kyosai_egov.py の出力）と、公表資料に書かれた値を突き合わせる検査。

実行: python -I -X utf8 scripts/R2X_kyosai_checks.py
- ネットワークにはアクセスしない。読むのは scripts/results/R2X_kyosai_egov/articles/*.txt（自分で作った出力）だけ。
  ダウンロードしたファイル（.work/downloads/）は読まない。
- 公表資料の値（月額・日額の目安、19〜23歳の生年月日の範囲など）は、この調査で読んだ資料から書き写した定数として下に置く。
  出典の ID は docs/public-sources/20261109_round2_kyosai-law-and-criteria.md §0 の表の ID。
- 結果は scripts/results/R2X_kyosai_checks/checks.json と checks.md に書く。
標準ライブラリのみ（Python 3.11）。
"""
import datetime as dt
import json
import pathlib
import re
import sys
from fractions import Fraction

ROOT = pathlib.Path(__file__).resolve().parent.parent
ART = ROOT / "scripts" / "results" / "R2X_kyosai_egov" / "articles"
OUT = ROOT / "scripts" / "results" / "R2X_kyosai_checks"
TODAY = "2026-11-09"


def read(short, asof=TODAY):
    return (ART / f"{short}_{asof}.txt").read_text(encoding="utf-8")


def header_rev(text):
    m = re.search(r"law_revision_id=(\S+)", text)
    return m.group(1) if m else None


def article_block(text, num):
    """`## Num=<num>` から次の `## Num=` までを返す。"""
    m = re.search(rf"^## Num={re.escape(num)}\n(.*?)(?=^## Num=|\Z)", text, re.S | re.M)
    return m.group(1) if m else ""


def line_starting(block, prefix):
    for ln in block.splitlines():
        if ln.strip().startswith(prefix):
            return ln.strip()
    return ""


# ---------------------------------------------------------------- C1 被扶養者の範囲（続柄ごとに同一世帯が要るか）
RELATIVES = ["配偶者", "直系尊属", "父母", "祖父母", "曾祖父母", "子", "孫", "兄弟姉妹", "三親等内の親族",
             "事実婚の配偶者の父母・子", "事実婚の配偶者の死亡後の父母・子"]


def c1_scope():
    res = {}
    # 健康保険法 第3条第7項
    k = article_block(read("kenpo"), "3")
    p7 = k[k.find("[項7]"):k.find("[項8]")]
    items = {n: line_starting(p7, f"{n} ") for n in ["一", "二", "三", "四"]}
    res["健保法3⑦"] = {
        "law_revision_id": header_rev(read("kenpo")),
        "第1号（同一世帯の要件なし）": items["一"],
        "第2号": items["二"], "第3号": items["三"], "第4号": items["四"],
        "第1号に『直系尊属』がある": "直系尊属" in items["一"],
        "第1号に同一世帯の語がない": ("同一の世帯" not in items["一"]),
        "第4号に『引き続き』がある": "引き続き" in items["四"],
        "生計維持の書き方": "主としてその被保険者により生計を維持" if "主としてその被保険者により生計を維持" in p7 else None,
    }
    for short, label in [("kokkyo", "国共済法2①二"), ("chikyo", "地共済法2①二")]:
        t = read(short)
        b = article_block(t, "2")
        main = line_starting(b, "二 被扶養者")
        i = line_starting(b, "イ ")
        ro = line_starting(b, "ロ ")
        ha = line_starting(b, "ハ ")
        res[label] = {
            "law_revision_id": header_rev(t),
            "イ（同一世帯の要件なし）": i, "ロ": ro, "ハ": ha,
            "イに『直系尊属』がある": "直系尊属" in i,
            "イに『父母』『祖父母』がある": ("父母" in i and "祖父母" in i),
            "ロの書き方（同一の世帯／同一世帯）": "同一の世帯" if "同一の世帯" in ro else ("同一世帯" if "同一世帯" in ro else None),
            "ハに『引き続き』がある": "引き続き" in ha,
            "生計維持の書き方": "主として組合員…の収入により生計を維持" if re.search(r"主として組合員.*?の収入により生計を維持", main) else None,
            "認定を政令に委任（第2項）": "政令で定める" in line_starting(b, "[項2]"),
        }
    # 続柄ごとの表（条文の語の有無から機械的に作る。曾祖父母は「直系尊属」に含まれるか「三親等内の親族」に当たるかで分かれる）
    table = []
    kenpo1 = items["一"]
    kk_i = res["国共済法2①二"]["イ（同一世帯の要件なし）"]
    for rel, kenpo_rule, kyosai_rule in [
        ("配偶者（事実婚を含む）", "配偶者" in kenpo1, "配偶者" in kk_i),
        ("父母", "直系尊属" in kenpo1, "父母" in kk_i),
        ("祖父母", "直系尊属" in kenpo1, "祖父母" in kk_i),
        ("曾祖父母（三親等の直系尊属）", "直系尊属" in kenpo1, "曾祖父母" in kk_i),
        ("子", "子" in kenpo1, "子" in kk_i),
        ("孫", "孫" in kenpo1, "孫" in kk_i),
        ("曾孫（三親等の直系卑属）", "曾孫" in kenpo1, "曾孫" in kk_i),
        ("兄弟姉妹", "兄弟姉妹" in kenpo1, "兄弟姉妹" in kk_i),
    ]:
        table.append({"続柄": rel,
                      "健保：同一世帯の要件なしの号に入る": kenpo_rule,
                      "共済（国・地方）：同一世帯の要件なしのイに入る": kyosai_rule})
    res["続柄ごと"] = table
    return res


# ---------------------------------------------------------------- C2 認定の委任先・届出の期限・給付の開始日
def c2_delegation_and_deadlines():
    out = {}
    for short, label in [("kokkyo-rei", "国共済令3"), ("chikyo-rei", "地共済令3"), ("shigaku-rei", "私学令3")]:
        t = read(short)
        p = line_starting(article_block(t, "3"), "[項1]")
        m = re.search(r"(財務大臣|総務大臣|文部科学大臣)", p)
        out[label] = {"law_revision_id": header_rev(t), "定める者": m.group(1) if m else None,
                      "一般職給与法第11条第2項の例を参酌": "第十一条第二項" in p,
                      "健保法の認定の取扱いを参酌": "被扶養者の認定の取扱いを参酌" in p}
    for short, num, label in [("kokkyo", "53", "国共済法53②"), ("chikyo", "55", "地共済法55②")]:
        t = read(short)
        p = line_starting(article_block(t, num), "[項2]")
        out[label] = {"law_revision_id": header_rev(t), "三十日以内": "三十日以内" in p,
                      "届出を受けた日から": "その届出を受けた日から行う" in p}
    for short, num, label in [("kokkyo-ki", "88", "国共済則88①"), ("chikyo-kitei", "94", "地共済規程94①"),
                              ("shigaku-ki", "1_5", "私学則1の5①"), ("kenpo-ki", "38", "健保則38①")]:
        t = read(short)
        p = line_starting(article_block(t, num), "[項1]")
        out[label] = {"law_revision_id": header_rev(t), "五日以内": "五日以内" in p,
                      "年間所得推計額を記載": "年間所得推計額" in article_block(t, num)}
    # 私学法25条が国共済法第4章（第53条を含む）を準用するか：章の範囲（index/*_toc.md）と第25条の除外の列挙
    toc = (ROOT / "scripts" / "results" / "R2X_kyosai_egov" / "index" / "kokkyo_2026-11-09_toc.md").read_text(encoding="utf-8")
    m = re.search(r"\| 第四章　給付 \| (\S+) \| (\S+) \|", toc)
    s25 = line_starting(article_block(read("shigaku"), "25"), "[項1]")
    i4 = s25.find("第四章（")
    exc = s25[i4:s25.find("を除く。）", i4) + len("を除く。）")] if i4 >= 0 else ""
    out["私学法25が国共済法53を準用"] = {
        "国共済法第4章の条の範囲": [m.group(1), m.group(2)] if m else None,
        "第4章の除外の列挙": exc,
        "除外に第53条が含まれない": ("第五十三条" not in exc) and ("第四十九条から第五十一条まで" in exc),
    }
    return out


# ---------------------------------------------------------------- C3 月額・日額の目安の端数
# 公表資料の値（書き写し）。ID は public-sources の §0。
PUBLISHED = [
    ("MIYAGI", 1_300_000, "月額", "108,334円未満"), ("MIYAGI", 1_300_000, "日額", "3,612円未満"),
    ("MIYAGI", 1_500_000, "月額", "125,000円未満"), ("MIYAGI", 1_500_000, "日額", "4,167円未満"),
    ("MIYAGI", 1_800_000, "月額", "150,000円未満"), ("MIYAGI", 1_800_000, "日額", "5,000円未満"),
    ("CHIKYO-OSAKA", 1_500_000, "日額", "4,167円未満"), ("CHIKYO-OSAKA", 1_300_000, "日額", "3,612円未満"),
    ("PMAC-01", 1_300_000, "月額", "108,334円未満"), ("PMAC-01", 1_500_000, "月額", "125,000円未満"),
    ("PMAC-01", 1_800_000, "月額", "150,000円未満"), ("PMAC-01", 1_300_000, "日額", "3,612円以上で不可"),
    ("PMAC-01", 1_500_000, "日額", "4,167円以上で不可"), ("PMAC-01", 1_800_000, "日額", "5,000円以上で不可"),
    ("N-TET（既存の成果）", 1_300_000, "月額", "108,333円以下"), ("N-TET（既存の成果）", 1_300_000, "日額", "3,611円以下"),
]


def c3_monthly_daily():
    rows = []
    for src, annual, kind, text in PUBLISHED:
        exact = Fraction(annual, 12) if kind == "月額" else Fraction(annual, 12 * 30)
        n = int(re.sub(r"[^\d]", "", text.split("円")[0]))
        if "未満" in text or "以上で不可" in text:
            # 「n 円未満」が「年額÷12（÷30）未満」と整数の範囲で一致するには n = ceil(exact) であればよい
            ceil_ = -(-exact.numerator // exact.denominator)
            consistent = (n == ceil_)
            rule = "n円未満 ⇔ 整数の月額（日額）< 年額/12(/30) となる n = 切り上げ"
        else:  # 以下
            floor_ = exact.numerator // exact.denominator
            consistent = (n == floor_) and (exact.denominator != 1)
            rule = "n円以下 ⇔ n = 切り捨て（年額/12(/30) が整数でないとき）"
        rows.append({"出典": src, "年額": annual, "種類": kind, "公表": text,
                     "年額/12(/30) の正確な値": f"{float(exact):.4f}", "整数の範囲で年額基準と一致": consistent, "規則": rule})
    return rows


# ---------------------------------------------------------------- C4 19歳以上23歳未満（その年の12月31日現在、誕生日の前日に加齢）
def age_at_dec31(birth, year):
    """その年の12月31日現在の年齢。年齢は誕生日の前日に加算する（R7QA19 Q4：1月1日生まれは12月31日に加算）。"""
    age = year - birth.year
    if birth.month == 1 and birth.day == 1:
        age += 1
    return age


def c4_age_window():
    out = {}
    for year in (2025, 2026, 2027):
        lo, hi = None, None
        d = dt.date(year - 30, 1, 1)
        while d <= dt.date(year, 12, 31):
            if 19 <= age_at_dec31(d, year) < 23:
                lo = lo or d
                hi = d
            d += dt.timedelta(days=1)
        out[str(year)] = {"生年月日の範囲（両端を含む）": [lo.isoformat(), hi.isoformat()]}
    # 公表資料（KOURITU-19-23）：令和7年中の基準額が150万円未満となるのは、誕生日が平成15年1月2日から平成19年1月1日までの方
    out["公表との一致（令和7年）"] = out["2025"]["生年月日の範囲（両端を含む）"] == ["2003-01-02", "2007-01-01"]
    return out


# ---------------------------------------------------------------- C5 父母の夫婦合算の基準額（保険者の資料）＝ 各人の基準額の和か
def c5_parents_sum():
    limits = {"60歳未満": 1_300_000, "60歳以上": 1_800_000}
    published = {  # FUKUOKA-KIJUN・OITA-TEBIKI の表（書き写し）
        ("60歳未満", "60歳未満"): 2_600_000, ("60歳未満", "60歳以上"): 3_100_000, ("60歳以上", "60歳以上"): 3_600_000}
    return [{"組合せ": list(k), "公表": v, "各人の基準額の和": limits[k[0]] + limits[k[1]],
             "一致": v == limits[k[0]] + limits[k[1]]} for k, v in published.items()]


# ---------------------------------------------------------------- C6 住民税：扶養親族の定義・納税義務者・賦課期日
def c6_juminzei():
    out = {}
    for asof in ("2026-01-01", TODAY, "2027-01-01"):
        t = read("chizei", asof)
        b292 = article_block(t, "292")
        d9 = line_starting(b292, "九 扶養親族")
        m = re.search(r"前年の合計所得金額が(.+?)以下", d9)
        b294 = article_block(t, "294")
        out[asof] = {
            "law_revision_id": header_rev(t),
            "292①九 扶養親族：生計を一にする": "生計を一にするもの" in d9,
            "292①九 扶養親族：住所・同居・市町村の語": [w for w in ("住所", "同居", "市町村内") if w in d9],
            "292①九 合計所得金額の上限": m.group(1) if m else None,
            "294①一": line_starting(b294, "一 "), "294①二": line_starting(b294, "二 "),
            "294②": line_starting(b294, "[項2]"),
            "318": line_starting(article_block(t, "318"), "[項1]"),
            "314の2④ 同居老親等（同居の要件）": "同居を常況" in line_starting(article_block(t, "314_2"), "[項4]"),
        }
    # 第294条（第1項〜第4項）・第318条・第24条第1項第1号・第2号の文言が3つの版で同じか
    def key_texts(asof):
        t = read("chizei", asof)
        b294 = article_block(t, "294")
        b24 = article_block(t, "24")
        return [line_starting(b294, x) for x in ("[項1]", "一 ", "二 ", "[項2]", "[項3]", "[項4]")] +                [line_starting(article_block(t, "318"), "[項1]"), line_starting(b24, "一 "), line_starting(b24, "二 ")]
    base = key_texts("2026-01-01")
    out["294①〜④・318・24①一二の文言が3版で同じ"] = all(key_texts(a) == base for a in (TODAY, "2027-01-01")) and all(base)
    s3 = line_starting(article_block(read("shotoku"), "3"), "[項1]")
    out["所得税法3①（公務員の国内住所のみなし）"] = {"law_revision_id": header_rev(read("shotoku")), "text": s3}
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"run_at": dt.datetime.now().isoformat(timespec="seconds"), "inputs": str(ART.relative_to(ROOT)),
           "C1_被扶養者の範囲": c1_scope(), "C2_委任・期限": c2_delegation_and_deadlines(),
           "C3_月額日額の端数": c3_monthly_daily(), "C4_19-23歳の生年月日": c4_age_window(),
           "C5_父母の合算基準": c5_parents_sum(), "C6_住民税": c6_juminzei()}
    (OUT / "checks.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# R2X_kyosai_checks の結果", "", f"- 実行：{res['run_at']}", f"- 入力：{res['inputs']}", ""]
    for k, v in res.items():
        if k.startswith("C"):
            md += [f"## {k}", "", "```json", json.dumps(v, ensure_ascii=False, indent=1), "```", ""]
    (OUT / "checks.md").write_text("\n".join(md), encoding="utf-8")
    # 要約を標準出力へ
    c1 = res["C1_被扶養者の範囲"]
    print("C1 続柄:", json.dumps(c1["続柄ごと"], ensure_ascii=False))
    print("C1 健保 第4号 引き続き:", c1["健保法3⑦"]["第4号に『引き続き』がある"], "/ 国共済 ハ 引き続き:", c1["国共済法2①二"]["ハに『引き続き』がある"],
          "/ 地共済 ロ:", c1["地共済法2①二"]["ロの書き方（同一の世帯／同一世帯）"], "/ 国共済 ロ:", c1["国共済法2①二"]["ロの書き方（同一の世帯／同一世帯）"])
    print("C2:", json.dumps(res["C2_委任・期限"], ensure_ascii=False)[:1500])
    print("C3:", [(r["出典"], r["年額"], r["種類"], r["公表"], r["整数の範囲で年額基準と一致"]) for r in res["C3_月額日額の端数"]])
    print("C4:", json.dumps(res["C4_19-23歳の生年月日"], ensure_ascii=False))
    print("C5:", [(r["組合せ"], r["一致"]) for r in res["C5_父母の合算基準"]])
    print("C6:", json.dumps({a: {kk: vv for kk, vv in v.items() if kk.startswith("292") or kk.startswith("314")} for a, v in res["C6_住民税"].items() if a[0].isdigit() and isinstance(v, dict)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

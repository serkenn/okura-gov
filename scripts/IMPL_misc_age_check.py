"""IMPL_misc: 所得税の年齢の判定式を、国税庁の資料に書かれた生年月日の範囲（令和7年分・令和8年分）と全日付で照合する。

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_misc_age_check.py

ネットワークには接続しない。標準ライブラリのみ。出力は scripts/results/IMPL_misc_age_check/。

比べる判定式（年分 Y、生年月日 b、「その年十二月三十一日の現況」の年齢）:
  A  Y - b.year + (1 if b が1月1日 else 0)         … 作成コーナーの jsGetAge と同じ式（docs/measurements/20261109_sakusei-corner_client-analysis.md）
  B  Y - b.year                                     … 誕生日の当日に1つ増えるとみなした場合の12月31日の満年齢
  L  法文から組んだ式：年齢は出生の日から起算し（年齢計算ニ関スル法律第1項）、民法第143条を準用する（同第2項）。
     n 歳に達するのは「n 年目の、起算日（生年月日）に応当する日の前日」の終了時。応当する日がないとき（2月29日生まれで
     平年）は、その月の末日の終了時（民法第143条第2項ただし書）。12月31日の終了時までに達した最大の n を年齢とする。
国税庁の範囲は「年齢 n 歳以上 ＝ 生年月日が X 以前」「n 歳以上 m 歳未満 ＝ X から Y まで」の形で書かれているので、
1940-01-01〜2016-12-31 のすべての日付について、各式で求めた年齢区分と国税庁の範囲の内外が一致するかを数える。
範囲の出典は docs/public-sources/20261109_impl-prep_misc-age-kinship-attribution.md §1 に書いた（取得は scripts/IMPL_misc_fetch.py）。
あわせて、判定日が書かれていない区分（源泉徴収票の「未成年者」欄）について、判定日の候補（その年の12月31日の終了時／
翌年1月1日の終了時）ごとに式Lで照合する（RANGES_OTHER_DATE）。
"""
import calendar
import datetime as dt
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "results" / "IMPL_misc_age_check"

ERA = {"明治": 1867, "大正": 1911, "昭和": 1925, "平成": 1988, "令和": 2018}


def wareki(s):
    """「平成22年1月1日」→ date。元号の元年は使わない（範囲の表記に出てこない）。"""
    m = re.fullmatch(r"(明治|大正|昭和|平成|令和)(\d+)年(\d+)月(\d+)日", s)
    if not m:
        raise ValueError(s)
    return dt.date(ERA[m.group(1)] + int(m.group(2)), int(m.group(3)), int(m.group(4)))


# (年分, 区分, 年齢の下限（以上）, 年齢の上限（未満。None は上限なし）, 生年月日の始まり（None は下限なし）, 終わり（None は上限なし）, 出典の略号)
# 生年月日の範囲は資料の表記のまま和暦で書く。
RANGES = [
    (2025, "控除対象扶養親族（居住者）16歳以上", 16, None, None, "平成22年1月1日", "N25-105 p.13, T25-y13, F25"),
    (2025, "非居住者 16歳以上30歳未満", 16, 30, "平成8年1月2日", "平成22年1月1日", "N25-105 p.13, T25-y13"),
    (2025, "70歳以上（老人扶養親族・非居住者）", 70, None, None, "昭和31年1月1日", "N25-105 p.13, T25-y11, T25-y13, F25"),
    (2025, "非居住者 30歳以上70歳未満", 30, 70, "昭和31年1月2日", "平成8年1月1日", "N25-105 p.13, T25-y13"),
    (2025, "特定扶養親族 19歳以上23歳未満", 19, 23, "平成15年1月2日", "平成19年1月1日", "N25-105 p.13, T25-y10, F25"),
    (2025, "特定親族 19歳以上23歳未満", 19, 23, "平成15年1月2日", "平成19年1月1日", "N25-106 p.21"),
    (2025, "16歳未満の扶養親族（年少扶養親族）", 0, 16, "平成22年1月2日", None, "F25（住民税に関する事項）"),
    (2025, "老人控除対象配偶者 70歳以上", 70, None, None, "昭和31年1月1日", "N25-106 p.20"),
    (2026, "控除対象扶養親族（居住者）16歳以上", 16, None, None, "平成23年1月1日", "N26-105 p.11, F26"),
    (2026, "非居住者 16歳以上30歳未満", 16, 30, "平成9年1月2日", "平成23年1月1日", "N26-105 p.11, F26"),
    (2026, "70歳以上（老人扶養親族・非居住者）", 70, None, None, "昭和32年1月1日", "N26-105 p.11, F26"),
    (2026, "非居住者 30歳以上70歳未満", 30, 70, "昭和32年1月2日", "平成9年1月1日", "N26-105 p.11, F26"),
    (2026, "特定扶養親族 19歳以上23歳未満", 19, 23, "平成16年1月2日", "平成20年1月1日", "N26-105 p.11, F26"),
    (2026, "特定親族 19歳以上23歳未満", 19, 23, "平成16年1月2日", "平成20年1月1日", "N26-106 p.19, F26"),
    (2026, "16歳未満の扶養親族（年少扶養親族）", 0, 16, "平成23年1月2日", None, "F26（住民税に関する事項）"),
    (2026, "老人控除対象配偶者 70歳以上", 70, None, None, "昭和32年1月1日", "N26-106 p.18"),
    (2026, "障害者（65歳以上で市町村長等の認定）", 65, None, None, "昭和37年1月1日", "N26-105 p.13"),
    (2026, "16歳未満の扶養親族（源泉徴収票⑪の注）", 0, 16, "平成23年1月2日", None, "H26-02 p.6"),
]
# 判定日が12月31日でない区分：源泉徴収票の「未成年者」欄（年齢18歳未満。成年は民法第4条）。資料は生年月日の範囲だけを示し、
# 判定日を書いていない。ここでは判定日の候補（その年の12月31日の終了時／翌年1月1日の終了時）ごとに式Lで照合する。
RANGES_OTHER_DATE = [
    (2025, "源泉徴収票の未成年者（18歳未満）", 0, 18, "平成20年1月3日", None, "H25-02 p.9（㉕の注）"),
    (2026, "源泉徴収票の未成年者（18歳未満）", 0, 18, "平成21年1月3日", None, "H26-02 p.10（㉖の注）"),
]


def age_A(b, y):
    return y - b.year + (1 if (b.month, b.day) == (1, 1) else 0)


def age_B(b, y):
    return y - b.year


def expiry(b, n):
    """出生の日 b から起算して n 年の期間が満了する日（民法第143条第2項）。"""
    yy = b.year + n
    try:
        anniv = dt.date(yy, b.month, b.day)
    except ValueError:  # 応当する日がない（2月29日生まれで平年）→ その月の末日に満了
        return dt.date(yy, b.month, calendar.monthrange(yy, b.month)[1])
    return anniv - dt.timedelta(days=1)


def age_L_at(b, d):
    """日 d の終了時に達している年齢（式L）。"""
    n = 0
    while expiry(b, n + 1) <= d:
        n += 1
    return n


def age_L(b, y):
    return age_L_at(b, dt.date(y, 12, 31))  # 12月31日の終了時の現況


def in_age(a, lo, hi):
    return a >= lo and (hi is None or a < hi)


def in_birth(b, s, e):
    return (s is None or b >= s) and (e is None or b <= e)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    start, end = dt.date(1940, 1, 1), dt.date(2016, 12, 31)
    days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    res = {"date_range": [start.isoformat(), end.isoformat()], "n_dates": len(days), "formula_A_equals_L": None, "ranges": []}
    # A と L の一致（2つの年分で）
    diffs_AL = [(b.isoformat(), y) for y in (2025, 2026) for b in days if age_A(b, y) != age_L(b, y)]
    res["formula_A_equals_L"] = {"mismatches": len(diffs_AL), "examples": diffs_AL[:10]}
    for (y, name, lo, hi, s, e, src) in RANGES:
        sd = wareki(s) if s else None
        ed = wareki(e) if e else None
        row = {"year": y, "category": name, "age_lo": lo, "age_hi_excl": hi, "birth_from": s, "birth_to": e,
               "birth_from_iso": sd.isoformat() if sd else None, "birth_to_iso": ed.isoformat() if ed else None, "source": src}
        for fname, f in (("A", age_A), ("B", age_B), ("L", age_L)):
            mism = [b for b in days if in_age(f(b, y), lo, hi) != in_birth(b, sd, ed)]
            row[f"mismatch_{fname}"] = len(mism)
            row[f"mismatch_{fname}_examples"] = [b.isoformat() for b in mism[:6]]
        res["ranges"].append(row)
    res["other_date"] = []
    for (y, name, lo, hi, s_, e_, src) in RANGES_OTHER_DATE:
        sd = wareki(s_) if s_ else None
        ed = wareki(e_) if e_ else None
        row = {"year": y, "category": name, "age_lo": lo, "age_hi_excl": hi, "birth_from": s_, "birth_to": e_,
               "birth_from_iso": sd.isoformat() if sd else None, "birth_to_iso": ed.isoformat() if ed else None, "source": src}
        for label, d in (("end_of_dec31", dt.date(y, 12, 31)), ("end_of_next_jan1", dt.date(y + 1, 1, 1))):
            mism = [b for b in days if in_age(age_L_at(b, d), lo, hi) != in_birth(b, sd, ed)]
            row[f"mismatch_L_{label}"] = len(mism)
            row[f"mismatch_L_{label}_examples"] = [b.isoformat() for b in mism[:6]]
        res["other_date"].append(row)
    # 1月1日・12月31日・2月29日生まれの例
    samples = ["2003-01-01", "2003-01-02", "2007-01-01", "2007-01-02", "2006-12-31", "2004-01-01", "2004-01-02",
               "2008-01-01", "2008-01-02", "2010-01-01", "2010-01-02", "2011-01-01", "2011-01-02", "2004-02-29", "1956-01-01", "1957-01-01"]
    res["samples"] = [{"birth": s, **{f"age_{fn}_{y}": f(dt.date.fromisoformat(s), y) for y in (2025, 2026)
                                       for fn, f in (("A", age_A), ("B", age_B), ("L", age_L))}} for s in samples]
    (OUT / "result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# 年齢の判定式と国税庁の生年月日の範囲の照合", "",
          f"- 照合した生年月日：{start}〜{end}（{len(days)} 日）。年分：2025（令和7年分）・2026（令和8年分）",
          f"- 式A（Y−生年＋1月1日生まれは1）と式L（年齢計算ニ関スル法律・民法第143条から組んだ式）の不一致：{len(diffs_AL)} 件", "",
          "| 年分 | 区分 | 年齢 | 生年月日の範囲（資料の表記） | 西暦 | 式Aの不一致 | 式Lの不一致 | 式Bの不一致 | 式Bの不一致の例 | 出典 |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for r in res["ranges"]:
        age = f"{r['age_lo']}以上" + (f"{r['age_hi_excl']}未満" if r["age_hi_excl"] else "")
        rng = f"{r['birth_from'] or ''}〜{r['birth_to'] or ''}"
        iso = f"{r['birth_from_iso'] or ''}〜{r['birth_to_iso'] or ''}"
        md.append(f"| {r['year']} | {r['category']} | {age} | {rng} | {iso} | {r['mismatch_A']} | {r['mismatch_L']} | "
                  f"{r['mismatch_B']} | {', '.join(r['mismatch_B_examples'][:3])} | {r['source']} |")
    md += ["", "## 判定日を変えた照合（源泉徴収票の未成年者欄）", "",
           "| 年分 | 区分 | 年齢 | 生年月日の範囲 | 西暦 | 式L・その年12月31日の終了時の不一致 | 例 | 式L・翌年1月1日の終了時の不一致 | 例 | 出典 |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for r in res["other_date"]:
        md.append(f"| {r['year']} | {r['category']} | {r['age_lo']}以上{r['age_hi_excl']}未満 | {r['birth_from']}〜 | {r['birth_from_iso']}〜 | "
                  f"{r['mismatch_L_end_of_dec31']} | {', '.join(r['mismatch_L_end_of_dec31_examples'][:3])} | "
                  f"{r['mismatch_L_end_of_next_jan1']} | {', '.join(r['mismatch_L_end_of_next_jan1_examples'][:3])} | {r['source']} |")
    md += ["", "## 例", "", "| 生年月日 | A 2025 | L 2025 | B 2025 | A 2026 | L 2026 | B 2026 |", "|---|---|---|---|---|---|---|"]
    for s in res["samples"]:
        md.append(f"| {s['birth']} | {s['age_A_2025']} | {s['age_L_2025']} | {s['age_B_2025']} | {s['age_A_2026']} | {s['age_L_2026']} | {s['age_B_2026']} |")
    (OUT / "result.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()

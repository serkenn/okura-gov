"""IMPL2 tsukin: 取得済みの条文（e-Gov）と国税庁の表・設例を突き合わせる（ネットワークは使わない）。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL2_tsukin_checks.py

入力（先に実行しておくもの）:
  scripts/IMPL2_tsukin_egov.py → scripts/results/IMPL2_tsukin_egov/rei_20_2_<asof>.txt
  scripts/IMPL2_tsukin_nta.py pages pages2 → scripts/results/IMPL2_tsukin_nta/pages/ta_2585.txt、pages2/users_2025tsukin.txt・users_2026tsukin.txt
出力: scripts/results/IMPL2_tsukin_checks/checks.json（検査ごとに ok と中身）

検査
  C1 施行令第20条の2第2号（交通用具）の距離の区分と月額を、3つの版（asof 2025-04-01＝改正前、2025-11-20＝令和7年政令第380号、
     2026-04-01＝令和8年政令第93号）の本文から漢数字を読んで取り出す。
  C2 C1 の表と、国税庁の表（TA2585〔令和8年4月1日現在〕、令和7年・令和8年の改正の案内ページの「改正後」「改正前」）を照合する。
  C3 第1号・第4号（令和8年版は第1号・第4号〜第6号）の「十五万円」と、令和8年版の第3号・第6号の駐車場等の上限「五千円」を本文から確かめる。
  C4 月額の非課税限度額を本文どおりに計算する参照の関数（下の exempt_limit）で、国税庁の令和8年4月の Q&A の設例
     （ケースA〜E、Q4−2）の非課税限度額と課税される額を再計算し、Q&A の数字と照合する（Q&A の数字は PDF を目視で写したもの）。
  C5 版の選び方（政令の附則：「施行日以後に受けるべき通勤手当」、差額の追給は元の通勤手当の日による）を、
     国税庁の令和7年11月の Q&A の Q4〜Q9 の設例に当て、Q&A の答えと照合する。
  C6 令和8年4月の Q&A Q3−3 例2（回数券 1,200円/11枚 × 20日）の値を有理数で計算し、Q&A の「2,182円（1円未満端数切上げ）」と
     比べる（所得税法施行規則第2条の2第2項第3号ロは端数の処理を定めていない）。
"""
import datetime as dt
import json
import pathlib
import re
from fractions import Fraction

ROOT = pathlib.Path(__file__).resolve().parent.parent
EGOV = ROOT / "scripts" / "results" / "IMPL2_tsukin_egov"
NTA = ROOT / "scripts" / "results" / "IMPL2_tsukin_nta"
OUT = ROOT / "scripts" / "results" / "IMPL2_tsukin_checks"

DIG = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
UNIT = {"十": 10, "百": 100, "千": 1000}


def kanji_int(s):
    """万未満の位取り（十・百・千）と万をもつ漢数字を整数にする（例：三万千六百 → 31600、九十五 → 95）。"""
    total, section, digit = 0, 0, None
    for ch in s:
        if ch in DIG:
            digit = DIG[ch]
        elif ch in UNIT:
            section += (digit if digit is not None else 1) * UNIT[ch]
            digit = None
        elif ch == "万":
            section += digit or 0
            total += section * 10000
            section, digit = 0, None
        else:
            raise ValueError(f"漢数字でない文字: {ch!r} in {s!r}")
    return total + section + (digit or 0)


K = "[〇一二三四五六七八九十百千万]+"
RE_ROW = re.compile(rf"^\s*[イロハニホヘトチリヌル]　その通勤の距離が片道({K})キロメートル(?:以上({K})キロメートル)?(未満|以上)である場合　一月当たり({K})円$")


def table_from_rei(asof):
    text = (EGOV / f"rei_20_2_{asof}.txt").read_text(encoding="utf-8")
    rows = []
    for line in text.splitlines():
        m = RE_ROW.match(line)
        if not m:
            continue
        a, b, kind, yen = m.groups()
        if b is None and kind == "未満":      # イ「片道十キロメートル未満」（下限は第2号本文の「二キロメートル未満…を除く」）
            lo, hi = 2, kanji_int(a)
        elif b is None:                        # 最後の行「…以上である場合」
            lo, hi = kanji_int(a), None
        else:
            lo, hi = kanji_int(a), kanji_int(b)
        rows.append({"from_km": lo, "below_km": hi, "yen": kanji_int(yen)})
    return text, rows


def yen(s):
    return int(s.replace(",", "").replace("円", ""))


def table_from_ta2585():
    t = (NTA / "pages" / "ta_2585.txt").read_text(encoding="utf-8")
    seg = t.split("１　マイカーなどで通勤している人", 1)[1].split("２　マイカーなどで通勤している人", 1)[0]
    cells = [c.strip("| ").strip() for c in seg.splitlines() if c.startswith("|")]
    rows = []
    for i in range(2, len(cells) - 1, 2):
        rng, amt = cells[i], cells[i + 1]
        m = re.match(r"(\d+)キロメートル(?:以上(\d+)キロメートル)?(未満|以上)", rng)
        if not m or amt == "(全額課税)":
            continue
        a, b, kind = m.groups()
        lo, hi = (int(a), int(b)) if b else ((int(a), None) if kind == "以上" else (0, int(a)))
        rows.append({"from_km": lo, "below_km": hi, "yen": yen(amt)})
    return rows


def table_from_users(name):
    """改正の案内ページの表（「改正後」「改正前」の2列）。令和8年のページは「同左」と、65km 以上の行の改正前が 38,700円の結合セル。"""
    t = (NTA / "pages2" / f"{name}.txt").read_text(encoding="utf-8")
    seg = t.split("〔alt:2〕", 1)[1].split("〔alt:3〕", 1)[0]
    cells = [c.strip("| ").strip() for c in seg.splitlines() if c.startswith("|")]
    rows = []
    i = 0
    while i < len(cells):
        m = re.search(r"片道\s*([0-9０-９]+)\s*(?:km|㎞)(?:以上\s*([0-9０-９]+)\s*(?:km|㎞))?\s*(未満|以上)", cells[i])
        if not m:
            i += 1
            continue
        tr = str.maketrans("０１２３４５６７８９", "0123456789")
        a = int(m.group(1).translate(tr))
        b = int(m.group(2).translate(tr)) if m.group(2) else None
        kind = m.group(3)
        lo, hi = (a, b) if b else ((a, None) if kind == "以上" else (0, a))
        after = cells[i + 1] if i + 1 < len(cells) else ""
        cand = cells[i + 2] if i + 2 < len(cells) else ""
        before = cand if re.fullmatch(r"[0-9,]+円|同左|（全額課税）", cand) else None
        rows.append({"from_km": lo, "below_km": hi, "after": after, "before": before})
        i += 3 if before is not None else 2
    # 結合セル（令和8年のページの 55km 以上の行の「改正前 38,700円」）：改正前の欄がない行は直前の行の値を引き継ぐ
    prev = None
    for r in rows:
        if r["before"] is None and prev is not None:
            r["before"] = prev
            r["before_from_merged_cell"] = True
        prev = r["before"]
    return rows


def lookup(rows, km):
    for r in rows:
        if km >= r["from_km"] and (r["below_km"] is None or km < r["below_km"]):
            return r["yen"]
    return None


# ---------------------------------------------------------------- 参照の関数（本文どおり）
CAP = 150000
PARKING_CAP = 5000


def exempt_limit(rows, *, transit=None, vehicle_km=None, parking_month=None, parking_allowed=False):
    """1か月当たりの非課税限度額（施行令第20条の2。令和8年版の号立て）。

    transit: 合理的な運賃等の額（月額）。vehicle_km: 交通用具の片道の距離。parking_month: 駐車場等料金相当額（月額、施行規則第2条の2第2項で求めた額）。
    parking_allowed: 駐車場等の規定がある版か（令和8年4月1日以後に受けるべき通勤手当）。
    2km 未満の交通用具は第2号・第3号・第5号・第6号から除かれる（交通機関だけの第1号・第4号は距離を問わない）。
    """
    vehicle = 0
    if vehicle_km is not None and vehicle_km >= 2:
        vehicle = lookup(rows, vehicle_km)
    parking = 0
    if parking_allowed and parking_month is not None and vehicle_km is not None and vehicle_km >= 2:
        parking = min(parking_month, PARKING_CAP)
    if transit is None:                      # 第2号・第3号（上限15万円の定めなし）
        return vehicle + parking
    return min(transit + vehicle + parking, CAP)  # 第1号・第4号・第5号・第6号


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    res = {}

    # C1
    versions = {"2025-04-01": "改正前（令和7年3月31日以前に受けるべき通勤手当）",
                "2025-11-20": "令和7年政令第380号（令和7年4月1日以後に受けるべき通勤手当）",
                "2026-04-01": "令和8年政令第93号（令和8年4月1日以後に受けるべき通勤手当）"}
    tables, texts = {}, {}
    for asof in versions:
        texts[asof], tables[asof] = table_from_rei(asof)
    res["C1_rei_tables"] = {"ok": all(len(v) >= 7 for v in tables.values()), "versions": versions, "tables": tables}

    # C2
    ta = table_from_ta2585()
    u25 = table_from_users("users_2025tsukin")
    u26 = table_from_users("users_2026tsukin")
    c2 = {"ta2585_vs_2026": ta == tables["2026-04-01"], "ta2585": ta}
    mism = []
    for r in u25:
        km = r["from_km"] if r["from_km"] >= 2 else None
        if km is None or r["after"] == "（全額課税）":
            continue
        a = yen(r["after"])
        b = a if r["before"] in ("同左", None) else yen(r["before"])
        if a != lookup(tables["2025-11-20"], km) or b != lookup(tables["2025-04-01"], km):
            mism.append({"page": "2025", "row": r, "rei_after": lookup(tables["2025-11-20"], km), "rei_before": lookup(tables["2025-04-01"], km)})
    for r in u26:
        km = r["from_km"]
        if r["after"] in ("（全額課税）",) or km < 2:
            continue
        a = yen(r["after"])
        if a != lookup(tables["2026-04-01"], km):
            mism.append({"page": "2026", "row": r, "rei": lookup(tables["2026-04-01"], km)})
        if r["before"] not in (None, "同左"):
            b = yen(r["before"])
            if b != lookup(tables["2025-11-20"], km):
                mism.append({"page": "2026-before", "row": r, "rei": lookup(tables["2025-11-20"], km)})
    c2["users_pages_mismatch"] = mism
    c2["users_2025_rows"] = len(u25)
    c2["users_2026_rows"] = len(u26)
    c2["ok"] = c2["ta2585_vs_2026"] and not mism and len(u25) >= 8 and len(u26) >= 12
    res["C2_vs_nta_tables"] = c2

    # C3
    c3 = {}
    for asof, t in texts.items():
        c3[asof] = {"十五万円の上限の数": t.count("十五万円を超えるときは、一月当たり十五万円"),
                    "駐車場等の上限五千円": "五千円を超えるときは、五千円" in t,
                    "二キロメートル未満の除外の数": t.count("二キロメートル未満")}
    c3["ok"] = (c3["2025-04-01"]["十五万円の上限の数"] == 3 and c3["2026-04-01"]["十五万円の上限の数"] == 4
                and not c3["2025-11-20"]["駐車場等の上限五千円"] and c3["2026-04-01"]["駐車場等の上限五千円"])
    res["C3_caps"] = c3

    # C4（令和8年4月 Q&A の設例。期待値は PDF の目視：Q3−1 ケースA〜D、Q3−2 ケースE、Q4−2）
    r8 = tables["2026-04-01"]
    cases = [
        ("A", dict(vehicle_km=50, parking_month=8000), 32300 + 8000, 37300, 3000),
        ("B", dict(vehicle_km=50, parking_month=8000), 28000 + 8000, 37300, 0),
        ("C", dict(vehicle_km=50, parking_month=4400), 33000 + 4400, 36700, 700),
        ("D", dict(vehicle_km=50, parking_month=4400), 35000, 36700, 0),
        ("E", dict(transit=115000, vehicle_km=50, parking_month=4000), 115000 + 32300 + 4000, 150000, 1300),
        ("Q4-2", dict(vehicle_km=50, parking_month=6000), 32300 + 6000, 37300, 1000),
    ]
    out = []
    for name, kw, paid, exp_limit, exp_taxable in cases:
        lim = exempt_limit(r8, parking_allowed=True, **kw)
        taxable = max(paid - lim, 0)
        out.append({"case": name, "inputs": kw, "paid": paid, "limit": lim, "taxable": taxable,
                    "expected_limit": exp_limit, "expected_taxable": exp_taxable,
                    "ok": lim == exp_limit and taxable == exp_taxable})
    # 境目：2km 未満の交通用具は駐車場等を足さない（Q3−4）。片道 1.9km・駐車場 3,000円 → 0
    out.append({"case": "Q3-4", "limit": exempt_limit(r8, vehicle_km=1.9, parking_month=3000, parking_allowed=True), "expected_limit": 0})
    out[-1]["ok"] = out[-1]["limit"] == 0
    res["C4_r8_qa_cases"] = {"ok": all(c["ok"] for c in out), "cases": out}

    # C5（版の選び方。令和7年11月 Q&A Q4〜Q9。「受けるべき日」は 36−9 と同じ読み：Q&A Q3）
    def version_for(due, base_due=None):
        """due：支給日（定めがなければ支給を受けた日）。base_due：差額の追給なら、元の通勤手当の日。"""
        d = dt.date.fromisoformat(base_due or due)
        if d >= dt.date(2026, 4, 1):
            return "R8"
        if d >= dt.date(2025, 4, 1):
            return "R7"
        return "old"
    q = [
        ("Q4", version_for("2025-04-10"), "R7"),
        ("Q5", version_for("2025-03-10"), "old"),
        ("Q6", version_for("2025-12-25", base_due="2025-04-10"), "R7"),
        ("Q7", version_for("2025-12-25", base_due="2025-03-10"), "old"),
        ("Q8", version_for("2025-03-10"), "old"),     # 未払で 4月10日に支給。本来の支給日 3月10日
        ("Q9", version_for("2025-09-25"), "R7"),      # 本来の支給日 9月25日、12月25日に支給
    ]
    res["C5_version_selection"] = {"ok": all(a == b for _, a, b in q), "cases": [{"q": n, "got": a, "expected": b} for n, a, b in q]}

    # C6
    v = Fraction(1200, 11) * 20
    res["C6_rounding_example"] = {"exact": f"{v.numerator}/{v.denominator}", "float": float(v),
                                  "ceil": -(-v.numerator // v.denominator), "floor": v.numerator // v.denominator,
                                  "qa_value": 2182, "ok": -(-v.numerator // v.denominator) == 2182}

    res["all_ok"] = all(v["ok"] for k, v in res.items() if isinstance(v, dict) and "ok" in v)
    (OUT / "checks.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, v in res.items():
        print(k, v["ok"] if isinstance(v, dict) else v)


if __name__ == "__main__":
    main()

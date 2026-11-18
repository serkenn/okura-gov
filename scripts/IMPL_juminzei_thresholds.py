"""IMPL juminzei: 条文の値から、住民税（令和8年度分・令和9年度分）の非課税の境目を計算し、給与収入に直して、
自治体の公表値と照合する。

実行（ネットワーク不要。入力は IMPL_juminzei_laws.py の出力だけ）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_juminzei_thresholds.py

出力: scripts/results/IMPL_juminzei_thresholds/thresholds.{md,json}

やること
 1. 計算に使う値（135万円、35万円・10万円・21万円・32万円、級地の率、措法第29条の4の表）が、取得した条文の
    該当する節に書かれていることを、版（asof）ごとに文字列で確かめる（書かれていなければ止まる）。
 2. 所得税法の別表第五（2025-12-31 版＝令和7年分、2026-12-01 版＝令和8年分）を表として読み、
    隙間や重なりがないことを確かめる。
 3. 給与所得の金額を、令和7年分＝別表第五（2025-12-31 版）、令和8年分＝措法第29条の4第2項（69万1千円以上220万円未満）
    ＋別表第五（2026-12-01 版）で求める。地方税法第313条第2項（所得税法その他の所得税に関する法令の計算の例）と
    第292条第5項（前年の所得について適用されたもの）による。措法第29条の4 が住民税に及ぶことは条文に明記がなく、
    自治体・参議院の資料による（public-sources §7）。
 4. 均等割の非課税（施行令第47条の3 の基準。級地ごと）、所得割の非課税（法附則第3条の3第4項）、
    未成年者等の非課税（法第295条第1項第2号）の境目を、扶養の人数 0〜4 人について計算し、給与収入だけの場合の
    上限を 1 円単位で求める。
 5. 自治体の公表値（江戸川区・柏市・世田谷区・神戸市）と照合する。
"""
import json
import pathlib
import re
import unicodedata

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "scripts" / "results" / "IMPL_juminzei_laws"
OUT = ROOT / "scripts" / "results" / "IMPL_juminzei_thresholds"

# 年度 → (賦課期日の asof, 所得の年分, 別表第五の asof)
YEARS = {
    "令和8年度": ("2026-01-01", "令和7年分", "2025-12-31"),
    "令和9年度": ("2027-01-01", "令和8年分", "2026-12-01"),
}


def section(path, head):
    text = path.read_text(encoding="utf-8")
    m = re.search(r"^## " + re.escape(head) + r"\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    if not m:
        raise SystemExit(f"節がない: {path.name} {head}")
    return m.group(1)


def must(path, head, needles):
    s = section(path, head)
    for n in needles:
        if n not in s:
            raise SystemExit(f"条文に見つからない: {path.name} [{head}] {n}")
    return {"file": str(path.relative_to(ROOT)), "section": head, "found": needles}


def evidence():
    ev = []
    for nendo, (asof, _, _) in YEARS.items():
        ev.append(must(SRC / f"chiho_{asof}.txt", "本則 Num=295", ["未成年者", "百三十五万円を超える場合を除く", "政令で定める基準に従い当該市町村の条例で定める金額以下"]))
        ev.append(must(SRC / f"chiho_{asof}.txt", "原始附則 Num=3_3",
                       ["三十五万円にその者の同一生計配偶者及び扶養親族", "十万円を加算した金額", "三十二万円を加算した金額"]))
        ev.append(must(SRC / f"chiho-rei_{asof}.txt", "本則 Num=47_3",
                       ["三十五万円を超えない範囲内", "十万円を加算した金額", "二十一万円を超えない範囲"]))
        ev.append(must(SRC / f"chiho-ki_{asof}.txt", "本則 Num=9_21", ["一級地　一・〇", "二級地　〇・九", "三級地　〇・八"]))
        ev.append(must(SRC / f"chiho_{asof}.txt", "本則 Num=292", ["所得税法その他の所得税に関する法令を引用する場合", "前年の所得について適用されたもの"]))
        ev.append(must(SRC / f"chiho_{asof}.txt", "本則 Num=313", ["所得税法その他の所得税に関する法令の規定による"]))
    ev.append(must(SRC / "sochi_2026-12-01.txt", "本則 Num=29_4", [
        "令和八年又は令和九年において", "六十九万千円以上七十四万千円未満", "ないものとする",
        "七十四万千円以上二百十九万千円未満", "七十四万円を控除した残額",
        "二百十九万千円以上二百十九万三千円未満", "百四十五万千円とする",
        "二百十九万三千円以上二百十九万六千円未満", "百四十五万三千円とする",
        "二百十九万六千円以上二百二十万円未満", "百四十五万六千円とする"]))
    for a in ("2025-12-31", "2026-12-01"):
        ev.append(must(SRC / f"shotoku_{a}.txt", "本則 Num=28", ["六百六十万円未満である場合", "別表第五"]))
    return ev


def num(s):
    s = unicodedata.normalize("NFKC", s).replace(",", "").strip()
    return int(s) if re.fullmatch(r"\d+", s) else None


def parse_beppyo5(path):
    """別表第五の行（| で区切った行）を、空のセルを飛ばしてトークンの列にし、(下限, 上限, 値) の組に読む。"""
    bins = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [unicodedata.normalize("NFKC", c).strip() for c in line.strip().strip("|").split("|")]
        toks = []
        for c in cells:
            if not c or c in ("円", "以上", "未満", "給与等の金額", "給与所得控除後の給与等の金額"):
                continue
            if num(c) is not None:
                toks.append(("n", num(c)))
            elif m := re.fullmatch(r"([\d,]+)円未満", c):
                toks.append(("lt", int(m.group(1).replace(",", ""))))
            elif m := re.fullmatch(r"給与等の金額から([\d,]+)円を控除した金額", c):
                toks.append(("minus", int(m.group(1).replace(",", ""))))
            elif m := re.fullmatch(r"給与等の金額に(\d+)%を乗じて算出した金額から([\d,]+)円を控除した金額", c):
                toks.append(("pct_minus", (int(m.group(1)), int(m.group(2).replace(",", "")))))
            elif re.fullmatch(r"[\d,]+円", c):
                toks.append(("yen", int(c[:-1].replace(",", ""))))
            else:
                toks.append(("?", c))
        i = 0
        while i < len(toks):
            t = toks[i]
            if t[0] == "lt" and i + 1 < len(toks) and toks[i + 1][0] == "n":
                bins.append((0, t[1], ("fixed", toks[i + 1][1])))
                i += 2
            elif t[0] == "n" and i + 2 < len(toks) and toks[i + 1][0] == "n" and toks[i + 2][0] in ("n", "minus", "pct_minus"):
                kind = toks[i + 2]
                bins.append((t[1], toks[i + 1][1], ("fixed", kind[1]) if kind[0] == "n" else kind))
                i += 3
            elif t[0] == "yen":
                i += 1  # 2,000万円の行（年末調整用。範囲外）
            else:
                raise SystemExit(f"別表第五の読めないトークン: {path.name} {toks[i:i+3]}")
    bins.sort()
    # 隙間・重なりの確認（0 から 6,600,000 まで）
    pos = 0
    for lo, hi, _ in bins:
        if lo >= 6_600_000:
            break
        if lo != pos:
            raise SystemExit(f"別表第五に隙間か重なり: {path.name} {pos} -> {lo}")
        pos = hi
    if pos < 6_600_000:
        raise SystemExit(f"別表第五が 6,600,000 円まで届かない: {path.name} {pos}")
    return bins


def table_lookup(bins, x):
    for lo, hi, (k, v) in bins:
        if lo <= x < hi:
            if k == "fixed":
                return v
            if k == "minus":
                return max(0, x - v)
            if k == "pct_minus":
                return x * v[0] // 100 - v[1]
    raise ValueError(x)


def kyuyo_shotoku(nenbun, x, bins):
    if x >= 6_600_000:
        raise ValueError("660万円以上は対象外（この計算では使わない）")
    if nenbun == "令和8年分" and 691_000 <= x < 2_200_000:  # 措法第29条の4第2項
        if x < 741_000:
            return 0
        if x < 2_191_000:
            return x - 740_000
        if x < 2_193_000:
            return 1_451_000
        if x < 2_196_000:
            return 1_453_000
        return 1_456_000
    return table_lookup(bins, x)


def max_income(limit, nenbun, bins):
    lo, hi = 0, 6_599_999
    if kyuyo_shotoku(nenbun, hi, bins) <= limit:
        return hi
    while lo < hi:  # 給与所得 <= limit となる最大の収入（給与所得は収入について単調非減少）
        mid = (lo + hi + 1) // 2
        if kyuyo_shotoku(nenbun, mid, bins) <= limit:
            lo = mid
        else:
            hi = mid - 1
    return lo


RATE = {1: (10, 10), 2: (9, 10), 3: (8, 10)}  # 施行規則第9条の21第2項（一・〇、〇・九、〇・八）


def kintou_limit(kyuchi, n):
    a, b = RATE[kyuchi]
    base = 350_000 * a // b
    add = 210_000 * a // b
    return base * (n + 1) + 100_000 + (add if n > 0 else 0)


def shotokuwari_limit(n):
    return 350_000 * (n + 1) + 100_000 + (320_000 if n > 0 else 0)


# 自治体の公表値（給与収入だけの場合の上限。公表どおり。出典は docs/public-sources の §5）
PUBLISHED = [
    ("江戸川区", "令和8年度", "均等割（均等割・所得割とも非課税）", 1, [1_100_000, 1_660_000, 2_059_999, 2_559_999, 3_059_999]),
    ("江戸川区", "令和8年度", "所得割", None, [1_100_000, 1_770_000, 2_215_999, 2_715_999, 3_215_999]),
    ("柏市", "令和8年度", "均等割（均等割・所得割とも非課税）", 2, [1_065_000, 1_569_000, 1_884_000, 2_327_999, 2_779_999]),
    ("柏市", "令和8年度", "所得割", None, [1_100_000, 1_770_000, 2_215_999, 2_715_999, 3_215_999]),
    ("柏市", "令和9年度", "均等割（均等割・所得割とも非課税）", 2, [1_155_000, 1_659_000, 1_974_000, 2_210_000, 2_560_000]),
    ("柏市", "令和9年度", "所得割", None, [1_190_000, 1_860_000, 2_214_285, 2_714_285, 3_214_285]),
    ("神戸市（級地は未確認。1級地として比べる）", "令和9年度", "均等割（均等割・所得割とも非課税）", 1, [1_190_000, 1_750_000, None, None, None]),
]
PUBLISHED_135 = [("柏市", "令和8年度", 2_043_999), ("世田谷区（「204万4千円未満」）", "令和8年度", 2_043_999),
                 ("柏市（表の値。本文は「209万円未満」）", "令和9年度", 2_090_000)]


def tokutei_shinzoku(income):
    """地方税法第314条の2第1項第12号（特定親族特別控除）。income は特定親族の前年の合計所得金額。
    対象かどうか（年齢・生計一・控除対象扶養親族でないこと）はここでは見ない。"""
    if income > 1_230_000:
        return 0
    if income <= 950_000:
        return 450_000
    if income <= 1_150_000:
        x = (income - 840_001) * 2  # 「八十四万一円を超える部分の金額に二を乗じた金額」
        if (x + 80_000) % 100_000 != 0:  # 10万円の整数倍から8万円を控除した金額でないとき
            x = max(v for v in range(20_000, x, 100_000) if v < x)  # それに満たないもののうち最も多い金額
        return 630_000 - x
    if income <= 1_200_000:
        return 60_000
    return 30_000


def tokutei_table(asof):
    must(SRC / f"chiho_{asof}.txt", "本則 Num=314_2", [
        "前年の合計所得金額が百二十三万円以下であるものに限る。）で控除対象扶養親族に該当しないもの",
        "前年の合計所得金額が九十五万円以下である特定親族　四十五万円",
        "六十三万円から当該特定親族の前年の合計所得金額のうち八十四万一円を超える部分の金額に二を乗じた金額",
        "十万円の整数倍の金額から八万円を控除した金額で当該乗じた金額に満たないもののうち最も多い金額",
        "百十五万円を超え百二十万円以下である特定親族　六万円", "百二十万円を超える特定親族　三万円"])
    # 区間ごとに値が一定であることを 1 円刻みで確かめ、区間の表にする（58万円超〜123万円）
    rows, start, cur = [], 580_001, tokutei_shinzoku(580_001)
    for inc in range(580_002, 1_230_002):
        v = tokutei_shinzoku(inc)
        if v != cur:
            rows.append((start, inc - 1, cur))
            start, cur = inc, v
    rows.append((start, 1_230_001, cur))  # 最後の区間は 1,230,001 円（123万円超）で 0 円になることを示す
    return rows


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ev = evidence()
    tok = {a: tokutei_table(a) for a in ("2026-01-01", "2027-01-01")}
    if tok["2026-01-01"] != tok["2027-01-01"]:
        raise SystemExit("特定親族特別控除の計算が版で違う（この関数は版によらない前提）")
    bins = {a: parse_beppyo5(SRC / f"shotoku_appdx_{a}.txt") for a in ("2025-12-31", "2026-12-01")}
    res = {"evidence": ev, "beppyo5_bins": {a: len(b) for a, b in bins.items()}, "years": {}, "comparisons": []}
    md = ["# 住民税の非課税の境目（IMPL_juminzei_thresholds.py の出力）", "",
          "- 境目は「以下」（その金額ちょうどは非課税）。給与収入は「給与所得 ≤ 境目」となる最大の収入（1 円単位）。",
          "- 均等割の境目は、施行令第47条の3 の基準（基本額 35万円×級地の率、加算額 21万円×級地の率）どおりに条例が定めた場合の値。"
          "実際の額は市町村の条例による。", ""]
    for nendo, (asof, nenbun, basof) in YEARS.items():
        b = bins[basof]
        y = {"所得の年分": nenbun, "賦課期日の版": asof, "別表第五の版": basof, "rows": []}
        md += [f"## {nendo}（{nenbun}の所得、別表第五 asof={basof}{'、措法第29条の4第2項' if nenbun == '令和8年分' else ''}）", "",
               "| 扶養等の人数 | 均等割 1級地（所得） | 給与収入 | 均等割 2級地 | 給与収入 | 均等割 3級地 | 給与収入 | 所得割（総所得金額等） | 給与収入 |",
               "|---|---|---|---|---|---|---|---|---|"]
        for n in range(5):
            row = {"n": n}
            cells = [str(n)]
            for k in (1, 2, 3):
                lim = kintou_limit(k, n)
                inc = max_income(lim, nenbun, b)
                row[f"kintou_{k}"] = {"limit": lim, "max_kyuyo": inc}
                cells += [f"{lim:,}", f"{inc:,}"]
            lim = shotokuwari_limit(n)
            inc = max_income(lim, nenbun, b)
            row["shotokuwari"] = {"limit": lim, "max_kyuyo": inc}
            cells += [f"{lim:,}", f"{inc:,}"]
            y["rows"].append(row)
            md.append("| " + " | ".join(cells) + " |")
        inc135 = max_income(1_350_000, nenbun, b)
        y["miseinen_135"] = {"limit": 1_350_000, "max_kyuyo": inc135}
        md += ["", f"- 未成年者・障害者・寡婦・ひとり親（法第295条第1項第2号、合計所得金額 1,350,000 円以下）：給与収入 {inc135:,} 円まで", ""]
        res["years"][nendo] = y
    md += ["## 自治体の公表値との照合", "", "| 自治体 | 年度 | 区分 | 人数 | 公表値 | 計算値 | 一致 |", "|---|---|---|---|---|---|---|"]
    for who, nendo, kind, kyuchi, vals in PUBLISHED:
        rows = res["years"][nendo]["rows"]
        for n, v in enumerate(vals):
            if v is None:
                continue
            calc = rows[n][f"kintou_{kyuchi}"]["max_kyuyo"] if kyuchi else rows[n]["shotokuwari"]["max_kyuyo"]
            ok = calc == v
            res["comparisons"].append({"who": who, "nendo": nendo, "kind": kind, "kyuchi": kyuchi, "n": n, "published": v, "calc": calc, "match": ok})
            md.append(f"| {who} | {nendo} | {kind}{'' if not kyuchi else f'（{kyuchi}級地）'} | {n} | {v:,} | {calc:,} | {'○' if ok else '×'} |")
    for who, nendo, v in PUBLISHED_135:
        calc = res["years"][nendo]["miseinen_135"]["max_kyuyo"]
        ok = calc == v
        res["comparisons"].append({"who": who, "nendo": nendo, "kind": "未成年者等135万円", "published": v, "calc": calc, "match": ok})
        md.append(f"| {who} | {nendo} | 未成年者等 135万円 | — | {v:,} | {calc:,} | {'○' if ok else '×'} |")
    md += ["", "## 特定親族特別控除（住民税。法第314条の2第1項第12号）の区間ごとの額", "",
           "条文（asof 2026-01-01 と 2027-01-01 で同じ文字列を確認）の式を 1 円刻みで評価し、額が変わる所で区切った。"
           "下限の 58万円超は令和8年度分（令和9年度分は扶養親族の要件が 62万円以下になるので 62万円超から。第12号の「控除対象扶養親族に該当しないもの」による）。", "",
           "| 特定親族の前年の合計所得金額 | 控除額 |", "|---|---|"]
    for lo, hi, v in tok["2026-01-01"]:
        md.append(f"| {lo:,} 〜 {hi:,} | {v:,} |")
    res["tokutei_shinzoku"] = [{"from": lo, "to": hi, "amount": v} for lo, hi, v in tok["2026-01-01"]]
    md += ["", f"- 別表第五の行数（読み取った区間の数）: {res['beppyo5_bins']}",
           f"- 条文の文字列の確認: {len(ev)} 件すべて見つかった（thresholds.json の evidence）。ほかに特定親族特別控除の条文の文字列を 2 版（2026-01-01、2027-01-01）で確認", ""]
    (OUT / "thresholds.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "thresholds.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()

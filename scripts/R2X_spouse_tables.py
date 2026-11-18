"""R2X_spouse: 配偶者控除・配偶者特別控除の額の表を、e-Gov から取り出した条文の文言（漢数字）から機械的に組み立て、
国税庁・市の公表の表と照合する。

実行（Windows）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/R2X_spouse_tables.py

入力（先に scripts/R2X_spouse_egov.py と scripts/R2X_spouse_fetch.py を実行しておく）:
  - scripts/results/R2X_spouse_egov/shotoku_asof2025-12-31.txt（令和7年分）・shotoku_asof2026-12-31.txt（令和8年分）
  - scripts/results/R2X_spouse_egov/chiho_asof2025-12-31.txt（令和7年度分。第10号の2 の括弧書きの比較用）・
    chiho_asof2026-01-01.txt（令和8年度分）・chiho_asof2027-01-01.txt（令和9年度分）
  - scripts/results/R2X_spouse_fetch/text/*_nta_ta/ta1195.txt（国税庁 No.1195 の表。照合用）
出力: scripts/results/R2X_spouse_tables/
  - params.json   条文から読んだ金額（どの文言から読んだかを含む）
  - bands.json    配偶者の合計所得金額を1円刻みで動かして求めた控除額の区間（本人の合計所得金額の3区分ごと）
  - compare.json  国税庁 No.1195（所得税）・宇都宮市の案内（住民税、令和8年度）の表との照合
  - summary.md    人が読む要約
標準ライブラリのみ。ネットワークには接続しない。
"""
import glob
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
EG = ROOT / "scripts" / "results" / "R2X_spouse_egov"
OUT = ROOT / "scripts" / "results" / "R2X_spouse_tables"

KD = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
KU = {"十": 10, "百": 100, "千": 1000}


def kan2int(s):
    """「九十三万一円」「百三十三万円」「千万円」「九百五十万円」などを整数（円）にする。"""
    s = s.replace("円", "")
    total, section, num = 0, 0, 0
    for ch in s:
        if ch in KD:
            num = KD[ch]
        elif ch in KU:
            section += (num or 1) * KU[ch]
            num = 0
        elif ch == "万":
            section += num
            total += section * 10000
            section, num = 0, 0
        else:
            raise ValueError(f"unknown char {ch!r} in {s!r}")
    return total + section + num


FRAC = {"三分の二": (2, 3), "三分の一": (1, 3)}
N = r"([〇一二三四五六七八九十百千万]+円)"


def article(text, num):
    m = re.search(rf"^## Num={num}\n(.*?)(?=^## Num=|\Z)", text, re.S | re.M)
    return m.group(1) if m else ""


def one(pat, s, what):
    m = re.search(pat, s, re.M)
    if not m:
        raise SystemExit(f"pattern not found: {what}: {pat}")
    return m


def parse_shotoku(path):
    t = path.read_text(encoding="utf-8")
    a83, a83_2 = article(t, "83"), article(t, "83_2")
    item33 = one(r"^三十三　同一生計配偶者.*$", t, "第2条第1項第33号").group(0)
    p = {"source": str(path.relative_to(ROOT)).replace("\\", "/")}
    p["douitsu_max"] = kan2int(one(rf"合計所得金額が{N}以下である者をいう", item33, "33号").group(1))
    p["kojo_honnin_max"] = kan2int(one(rf"三十三の二　控除対象配偶者　同一生計配偶者のうち、合計所得金額が{N}以下", t, "33号の2").group(1))
    # 第83条（配偶者控除）
    k = []
    # 第1号は「合計所得金額（以下この項、…（特定親族特別控除）及び…（基礎控除）において「合計所得金額」という。）が」と入れ子の括弧を含む
    for m in re.finditer(rf"合計所得金額(?:（.*?）)?が(?:{N}を超え)?{N}以下である場合　{N}（その控除対象配偶者が老人控除対象配偶者である場合には、{N}）", a83):
        lo = kan2int(m.group(1)) if m.group(1) else 0
        k.append({"honnin_gt": lo, "honnin_le": kan2int(m.group(2)), "ippan": kan2int(m.group(3)), "rojin": kan2int(m.group(4))})
    p["kojo"] = k
    # 第83条の2（配偶者特別控除）
    h = one(rf"合計所得金額が{N}以下であるものに限る。）で控除対象配偶者に該当しないもの（合計所得金額が{N}以下である", a83_2, "83の2①柱書")
    p["toku_spouse_max"], p["toku_honnin_max"] = kan2int(h.group(1)), kan2int(h.group(2))
    i1 = one(rf"一　その居住者の合計所得金額が{N}以下である場合", a83_2, "83の2①一")
    ia = one(rf"イ　合計所得金額が{N}以下である配偶者　{N}$", a83_2, "イ")
    ib = one(rf"ロ　合計所得金額が{N}を超え{N}以下である配偶者　{N}からその配偶者の合計所得金額のうち{N}を超える部分の金額（当該超える部分の金額が{N}の整数倍の金額から{N}を控除した金額でない", a83_2, "ロ")
    ic = one(rf"ハ　合計所得金額が{N}を超える配偶者　{N}$", a83_2, "ハ")
    p["toku_base"] = {
        "honnin_le": kan2int(i1.group(1)),
        "flat_le": kan2int(ia.group(1)), "flat": kan2int(ia.group(2)),
        "step_gt": kan2int(ib.group(1)), "step_le": kan2int(ib.group(2)), "step_from": kan2int(ib.group(3)),
        "step_over": kan2int(ib.group(4)), "step_unit": kan2int(ib.group(5)), "step_sub": kan2int(ib.group(6)),
        "tail_gt": kan2int(ic.group(1)), "tail": kan2int(ic.group(2)),
    }
    fr = []
    for m in re.finditer(rf"[二三]　その居住者の合計所得金額が{N}を超え{N}以下である場合.*?金額の(三分の[一二])に相当する金額（当該金額に{N}未満の端数がある場合には、これを切り上げた金額）", a83_2):
        fr.append({"honnin_gt": kan2int(m.group(1)), "honnin_le": kan2int(m.group(2)), "frac": FRAC[m.group(3)], "ceil_unit": kan2int(m.group(4))})
    p["toku_frac"] = fr
    return p


def parse_chiho(path, art):
    """地方税法 第314条の2（市町村民税）または第34条（道府県民税）の第1項第10号・第10号の2。"""
    t = path.read_text(encoding="utf-8")
    a = article(t, art)
    p = {"source": str(path.relative_to(ROOT)).replace("\\", "/"), "article": art}
    a292 = article(t, "292")
    item7 = one(r"^  七　同一生計配偶者.*$", a292, "292①七").group(0)
    p["douitsu_max"] = kan2int(one(rf"の合計所得金額が{N}以下である者をいう", item7, "292①七").group(1))
    k = []
    for m in re.finditer(rf"当該納税義務者の前年の合計所得金額が(?:{N}を超え)?{N}以下である場合　{N}（その控除対象配偶者が老人控除対象配偶者(?:（[^）]*）)?である場合には、{N}）", a):
        lo = kan2int(m.group(1)) if m.group(1) else 0
        k.append({"honnin_gt": lo, "honnin_le": kan2int(m.group(2)), "ippan": kan2int(m.group(3)), "rojin": kan2int(m.group(4))})
    p["kojo"] = k
    h = one(rf"十の二　自己と生計を一にする配偶者（.*?前年の合計所得金額が{N}以下であるものに限る。）で控除対象配偶者に該当しないものを有する所得割の納税義務者（(.*?)、前年の合計所得金額が{N}以下であるものに限る。）", a, "十の二柱書")
    p["toku_spouse_max"], p["toku_mutual_exclusion_text"], p["toku_honnin_max"] = kan2int(h.group(1)), h.group(2), kan2int(h.group(3))
    i1 = one(rf"イ　当該納税義務者の前年の合計所得金額が{N}以下である場合　当該配偶者の次に掲げる区分", a, "十の二イ")
    ia = one(rf"（１）　前年の合計所得金額が{N}以下である配偶者　{N}$", a, "十の二イ（１）")
    ib = one(rf"（２）　前年の合計所得金額が{N}を超え{N}以下である配偶者　{N}から当該配偶者の前年の合計所得金額のうち{N}を超える部分の金額（当該超える部分の金額が{N}の整数倍の金額から{N}を控除した金額でない", a, "十の二イ（２）")
    ic = one(rf"（３）　前年の合計所得金額が{N}を超える配偶者　{N}$", a, "十の二イ（３）")
    p["toku_base"] = {
        "honnin_le": kan2int(i1.group(1)),
        "flat_le": kan2int(ia.group(1)), "flat": kan2int(ia.group(2)),
        "step_gt": kan2int(ib.group(1)), "step_le": kan2int(ib.group(2)), "step_from": kan2int(ib.group(3)),
        "step_over": kan2int(ib.group(4)), "step_unit": kan2int(ib.group(5)), "step_sub": kan2int(ib.group(6)),
        "tail_gt": kan2int(ic.group(1)), "tail": kan2int(ic.group(2)),
    }
    fr = []
    for m in re.finditer(rf"[ロハ]　当該納税義務者の前年の合計所得金額が{N}を超え{N}以下である場合　当該配偶者の.*?金額の(三分の[一二])に相当する金額（当該金額に{N}未満の端数がある場合には、これを切り上げた金額）", a):
        fr.append({"honnin_gt": kan2int(m.group(1)), "honnin_le": kan2int(m.group(2)), "frac": FRAC[m.group(3)], "ceil_unit": kan2int(m.group(4))})
    p["toku_frac"] = fr
    return p


def base_amount(b, s):
    """配偶者の合計所得金額 s に対する、本人の合計所得金額が最も低い区分の額（条文の イ・ロ・ハ）。"""
    if s <= b["flat_le"]:
        return b["flat"]
    if b["step_gt"] < s <= b["step_le"]:
        excess = s - b["step_over"]  # 「…を超える部分の金額」
        # 「step_unit の整数倍の金額から step_sub を控除した金額」のうち excess 以下で最大のもの（等しければそれ自体）
        n = (excess + b["step_sub"]) // b["step_unit"]
        v = n * b["step_unit"] - b["step_sub"]
        assert v <= excess and v + b["step_unit"] > excess
        return b["step_from"] - v
    if s > b["tail_gt"]:
        return b["tail"]
    raise AssertionError(s)


def ceil_frac(x, frac, unit):
    num, den = frac
    q = -(-x * num // den)  # 円未満を切り上げ（整数の分数で計算）
    return -(-q // unit) * unit


def toku_amount(p, honnin_band, s):
    b = p["toku_base"]
    x = base_amount(b, s)
    if honnin_band == 0:
        return x
    f = p["toku_frac"][honnin_band - 1]
    return ceil_frac(x, f["frac"], f["ceil_unit"])


def bands(p):
    """配偶者の合計所得金額を（同一生計配偶者の上限＋1円）から特別控除の上限まで1円刻みで動かし、控除額が一定の区間にまとめる。"""
    lo, hi = p["douitsu_max"] + 1, p["toku_spouse_max"]
    out = []
    for hb in range(3):
        cur = None
        rows = []
        for s in range(lo, hi + 1):
            v = toku_amount(p, hb, s)
            if cur is None or v != cur[2]:
                if cur:
                    rows.append(cur)
                cur = [s, s, v]
            else:
                cur[1] = s
        rows.append(cur)
        out.append([{"spouse_from": r[0], "spouse_to": r[1], "amount": r[2]} for r in rows])
    return out


def nta_table(path, header):
    """国税庁 No.1195 の本文から、見出し header の直後の表の行（配偶者の所得の区間と3つの額）を読む。"""
    t = path.read_text(encoding="utf-8")
    t = re.sub(r"[ \t\u3000]*\|[ \t\u3000]*", "|", t)
    t = re.sub(r"\s+", " ", t)
    # 表の見出しは「<header> |」の形（本文中の「令和7年分は…」と区別する）
    i = t.index(header + " |")
    j = t.find("令和", i + len(header))
    seg = t[i:j if j > 0 else None]
    rows = []
    for m in re.finditer(r"(\d+)万円超 ?(\d+)万円以下 ?\|(\d+)万円 ?\|(\d+)万円 ?\|(\d+)万円", seg):
        rows.append({"spouse_gt": int(m.group(1)) * 10000, "spouse_le": int(m.group(2)) * 10000,
                     "amounts": [int(m.group(k)) * 10000 for k in (3, 4, 5)]})
    return rows


def compare(bnds, expected):
    """expected の各行（配偶者の所得が gt 超 le 以下）で、計算した区間の額が3区分とも一致するか。"""
    res = []
    for row in expected:
        got = []
        for hb in range(3):
            vals = {b["amount"] for b in bnds[hb] if not (b["spouse_to"] <= row["spouse_gt"] or b["spouse_from"] > row["spouse_le"])}
            got.append(sorted(vals))
        ok = all(g == [e] for g, e in zip(got, row["amounts"]))
        res.append({**row, "computed": got, "match": ok})
    return res


# 宇都宮市「配偶者控除と配偶者特別控除」（更新日 令和8年8月17日）の「令和8年度から」の表（取得したテキストからの書き写し。照合用、二次的な確認）
UTSUNOMIYA_R8 = [
    (580000, 1000000, [330000, 220000, 110000]),
    (1000000, 1050000, [310000, 210000, 110000]),
    (1050000, 1100000, [260000, 180000, 90000]),
    (1100000, 1150000, [210000, 140000, 70000]),
    (1150000, 1200000, [160000, 110000, 60000]),
    (1200000, 1250000, [110000, 80000, 40000]),
    (1250000, 1300000, [60000, 40000, 20000]),
    (1300000, 1330000, [30000, 20000, 10000]),
]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    params, allb, cmp = {}, {}, {}
    for key, fn in [("shotoku_R7", "shotoku_asof2025-12-31.txt"), ("shotoku_R8", "shotoku_asof2026-12-31.txt")]:
        params[key] = parse_shotoku(EG / fn)
    for key, fn, art in [("shichoson_R7nendo", "chiho_asof2025-12-31.txt", "314_2"),
                         ("shichoson_R8nendo", "chiho_asof2026-01-01.txt", "314_2"), ("shichoson_R9nendo", "chiho_asof2027-01-01.txt", "314_2"),
                         ("dofuken_R8nendo", "chiho_asof2026-01-01.txt", "34"), ("dofuken_R9nendo", "chiho_asof2027-01-01.txt", "34")]:
        params[key] = parse_chiho(EG / fn, art)
    for k, p in params.items():
        allb[k] = bands(p)
    # 国税庁 No.1195
    ta = sorted(glob.glob(str(ROOT / "scripts" / "results" / "R2X_spouse_fetch" / "text" / "*_nta_ta" / "ta1195.txt")))
    if ta:
        tap = pathlib.Path(ta[-1])
        for key, header in [("shotoku_R8", "令和8年分以降"), ("shotoku_R7", "令和7年分")]:
            exp = nta_table(tap, header)
            cmp[f"{key}_vs_TA1195"] = {"source": str(tap.relative_to(ROOT)).replace("\\", "/"), "header": header,
                                       "rows": compare(allb[key], exp)}
    # 国税庁 No.1191（配偶者控除の表）
    ta91 = sorted(glob.glob(str(ROOT / "scripts" / "results" / "R2X_spouse_fetch" / "text" / "*_nta_ta" / "ta1191.txt")))
    if ta91:
        t91 = pathlib.Path(ta91[-1]).read_text(encoding="utf-8")
        t91n = re.sub(r"\s+", " ", re.sub(r"[ \t　]*\|[ \t　]*", "|", t91))
        rows91 = [(m.group(1), int(m.group(2)) * 10000, int(m.group(3)) * 10000)
                  for m in re.finditer(r"\|((?:\d[\d,]*万円超)?[\d,]+万円以下) ?\|(\d+)万円 ?\|(\d+)万円", t91n)]
        got91 = [(r["ippan"], r["rojin"]) for r in params["shotoku_R8"]["kojo"]]
        cmp["shotoku_kojo_vs_TA1191"] = {"source": str(pathlib.Path(ta91[-1]).relative_to(ROOT)).replace("\\", "/"),
                                         "nta_rows": rows91, "computed_R7": [(r["ippan"], r["rojin"]) for r in params["shotoku_R7"]["kojo"]],
                                         "computed_R8": got91, "match": [(a, b) for _, a, b in rows91] == got91}
    exp_u = [{"spouse_gt": a, "spouse_le": b, "amounts": v} for a, b, v in UTSUNOMIYA_R8]
    cmp["shichoson_R8nendo_vs_utsunomiya"] = {"source": "宇都宮市（書き写し。summary.md 参照）", "rows": compare(allb["shichoson_R8nendo"], exp_u)}
    # 道府県民税と市町村民税で控除額が同じか
    for y in ("R8nendo", "R9nendo"):
        cmp[f"dofuken_eq_shichoson_{y}"] = {"kojo_equal": params[f"dofuken_{y}"]["kojo"] == params[f"shichoson_{y}"]["kojo"],
                                           "toku_bands_equal": allb[f"dofuken_{y}"] == allb[f"shichoson_{y}"]}
    (OUT / "params.json").write_text(json.dumps(params, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "bands.json").write_text(json.dumps(allb, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "compare.json").write_text(json.dumps(cmp, ensure_ascii=False, indent=1), encoding="utf-8")

    md = ["# R2X_spouse_tables の結果", "", "条文（e-Gov 法令API v2 から取り出した文言）から組み立てた配偶者特別控除の区間と、公表の表との照合。", ""]
    for k, p in params.items():
        md.append(f"## {k}（{p['source']}）")
        md.append(f"- 同一生計配偶者の上限: {p['douitsu_max']:,} 円 / 特別控除の配偶者の上限: {p['toku_spouse_max']:,} 円 / 本人の上限: {p['toku_honnin_max']:,} 円")
        md.append("- 配偶者控除: " + "、".join(f"本人 {r['honnin_gt']:,}超{r['honnin_le']:,}以下 → 一般 {r['ippan']:,} / 老人 {r['rojin']:,}" for r in p["kojo"]))
        if "toku_mutual_exclusion_text" in p:
            md.append(f"- 第10号の2 の括弧書き（相互適用の除外）: 「{p['toku_mutual_exclusion_text']}」")
        md.append("")
        md.append("| 配偶者の合計所得金額 | 本人 900万円以下 | 900万円超950万円以下 | 950万円超1,000万円以下 |")
        md.append("|---|---|---|---|")
        b0, b1, b2 = allb[k]
        # 3区分の区間の境目は同じ（額の比率の関数なので）か確かめつつ並べる
        edges = sorted({(r["spouse_from"], r["spouse_to"]) for r in b0})
        for (f, t) in edges:
            vals = []
            for bb in (b0, b1, b2):
                vs = {r["amount"] for r in bb if not (r["spouse_to"] < f or r["spouse_from"] > t)}
                vals.append("/".join(f"{v:,}" for v in sorted(vs)))
            md.append(f"| {f:,}〜{t:,} | " + " | ".join(vals) + " |")
        md.append("")
    md.append("## 照合")
    for k, c in cmp.items():
        if "rows" in c:
            n_ok = sum(r["match"] for r in c["rows"])
            md.append(f"- {k}: {n_ok}/{len(c['rows'])} 行一致（出典 {c['source']}）")
        else:
            md.append(f"- {k}: {c}")
    (OUT / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()

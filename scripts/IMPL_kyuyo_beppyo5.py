"""IMPL_kyuyo: 所得税法 別表第五（年末調整等のための給与所得控除後の給与等の金額の表）を機械可読にし、検査する。

実行（ネットワーク不要。先に scripts/IMPL_kyuyo_fetch.py を実行しておく）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL_kyuyo_beppyo5.py

入力：scripts/results/IMPL_kyuyo_fetch/beppyo5_grid_<asof>.json（e-Gov 法令API v2 の本文から取り出した表の格子）
出力：scripts/results/IMPL_kyuyo_beppyo5/
  - beppyo5_<asof>.csv / .json：1行＝1区分（以上・未満・給与所得控除後の給与等の金額、または式）
  - check_<asof>.json：検査の結果（区分が隙間なく続くか、刻み幅の分布、第28条第3項の式との照合）
  - version_diff.json：版の間で表が同じか、違うならどの区分か
  - summary.md：人が読む要約

表の読み方（e-Gov の表の構造）：
- 別表第五は TableStruct（（一）〜）に分かれ、各 TableStruct の各行は「以上・未満・金額」の3列の組を3つ横に並べたもの。
  読む順番は、TableStruct ごとに、左の組を上から下、次に中の組、次に右の組。
- セルの rowspan / colspan を HTML の表と同じ規則で格子に置き直してから読む。
- 「６５１，０００円未満」のように colspan=2 で「以上」「未満」をまたぐセルは、下限 0・上限 651,000 の区分とする。
- 最後の「２０，０００，０００円」（colspan=2）は、給与等の金額がちょうど 20,000,000 円の点の値とする。
- 金額のかわりに「給与等の金額から６５０，０００円を控除した金額」などの式が書かれた区分は、式の種類と定数を取り出す。
"""
import csv
import json
import math
import pathlib
import re
import sys
from collections import Counter
from fractions import Fraction

ROOT = pathlib.Path(__file__).resolve().parent.parent
IN = ROOT / "scripts" / "results" / "IMPL_kyuyo_fetch"
OUT = ROOT / "scripts" / "results" / "IMPL_kyuyo_beppyo5"

Z2H = str.maketrans("０１２３４５６７８９，％", "0123456789,%")


def num(s):
    s = s.translate(Z2H).replace(",", "").replace("円", "").strip()
    return int(s)


def is_num(s):
    return bool(re.fullmatch(r"[0-9,]+円?", s.translate(Z2H).strip()))


def parse_formula(s):
    t = s.translate(Z2H).replace(",", "")
    m = re.fullmatch(r"給与等の金額から(\d+)円を控除した金額", t)
    if m:
        return {"kind": "minus", "c": int(m.group(1))}
    m = re.fullmatch(r"給与等の金額に(\d+)%を乗じて算出した金額から(\d+)円を控除した金額", t)
    if m:
        return {"kind": "rate_minus", "rate_pct": int(m.group(1)), "c": int(m.group(2))}
    return {"kind": "unknown", "text": s}


def place(rows, width=9):
    """rowspan/colspan を展開した格子。grid[r][c] = (origin_r, origin_c, cell)。"""
    grid = [[None] * width for _ in rows]
    for r, cells in enumerate(rows):
        c = 0
        for cell in cells:
            while c < width and grid[r][c] is not None:
                c += 1
            if c >= width:
                raise ValueError(f"row {r}: too many cells")
            for dr in range(cell["rowspan"]):
                for dc in range(cell["colspan"]):
                    if r + dr < len(rows) and c + dc < width:
                        grid[r + dr][c + dc] = (r, c, cell)
            c += cell["colspan"]
    return grid


def records_from(g):
    recs = []
    for si, st in enumerate(g["structs"]):
        rows = st["rows"]
        # 見出し：単位「円」だけの行（式の列の上は空欄のことがある）までを飛ばす
        start = next(i for i, r in enumerate(rows)
                     if r and sum(c["text"] == "円" for c in r) >= 6 and all(c["text"] in ("円", "") for c in r)) + 1
        grid = place(rows)
        for gi, base in enumerate((0, 3, 6)):
            for r in range(start, len(rows)):
                a, b, v = grid[r][base], grid[r][base + 1], grid[r][base + 2]
                if a is None:
                    continue
                if a[0] != r:  # 上の行からの rowspan の続き
                    continue
                ca = a[2]
                if ca["colspan"] == 2 and a[1] == base:
                    txt = ca["text"].translate(Z2H).strip()
                    if not txt:
                        continue
                    vtxt = v[2]["text"] if v else ""
                    if txt.endswith("円未満"):
                        recs.append({"lower": 0, "upper": num(txt.replace("未満", "")), "kind": "fixed", "value": num(vtxt),
                                     "text": f"{ca['text']} | {vtxt}", "struct": si, "group": gi, "row": r})
                    else:
                        recs.append({"lower": num(txt), "upper": None, "kind": "point", "value": num(vtxt),
                                     "text": f"{ca['text']} | {vtxt}", "struct": si, "group": gi, "row": r})
                    continue
                if a[1] != base or not ca["text"].strip():
                    continue
                lo_t = ca["text"]
                up_t = b[2]["text"] if b and b[0] == r else ""
                if not up_t.strip():
                    raise ValueError(f"struct {si} row {r} group {gi}: 以上 があるのに 未満 がない")
                vc = v[2]
                rec = {"lower": num(lo_t), "upper": num(up_t), "struct": si, "group": gi, "row": r,
                       "text": f"{lo_t} | {up_t} | {vc['text']}"}
                if is_num(vc["text"]):
                    rec.update({"kind": "fixed", "value": num(vc["text"])})
                else:
                    f = parse_formula(vc["text"])
                    rec.update(f)
                    rec["formula_text"] = vc["text"]
                    rec["value"] = None
                recs.append(rec)
    recs.sort(key=lambda x: (x["lower"], x["upper"] is None))
    return recs


# ---- 第28条第3項の式（版ごと）。原文は scripts/results/IMPL_kyuyo_fetch/articles_shotoku_<asof>.txt の Num=28 ----
# 第28条には端数処理の定めがないので、控除額は Fraction で正確に持つ（百分の三十などで1円未満が出うる）。
def ded_r6(x):  # asof 2024-12-31 / 2025-11-30 の第28条第3項
    x = Fraction(x)
    if x <= 1_800_000:
        return max(x * Fraction(40, 100) - 100_000, Fraction(550_000))
    if x <= 3_600_000:
        return 620_000 + (x - 1_800_000) * Fraction(30, 100)
    if x <= 6_600_000:
        return 1_160_000 + (x - 3_600_000) * Fraction(20, 100)
    if x <= 8_500_000:
        return 1_760_000 + (x - 6_600_000) * Fraction(10, 100)
    return Fraction(1_950_000)


def ded_r7(x):  # asof 2025-12-31 / 2026-11-09 / 2026-11-30
    if x <= 1_900_000:
        return Fraction(650_000)
    if x <= 3_600_000:
        return 650_000 + (Fraction(x) - 1_900_000) * Fraction(30, 100)
    return ded_r6(x)


def ded_r8(x):  # asof 2026-12-01 / 2027-01-01
    if x <= 3_600_000:
        return max(80_000 + Fraction(x) * Fraction(30, 100), Fraction(690_000))
    return ded_r6(x)


def art28_floor(x, ded):
    """第28条第2項・第3項の残額（1円未満は切り捨てて比べる。切り捨ての根拠は別表第五の備考で、第28条自体には定めがない）。"""
    return math.floor(Fraction(x) - ded(x))


DED = {"2024-12-31": ded_r6, "2025-11-30": ded_r6, "2025-12-31": ded_r7, "2026-11-09": ded_r7, "2026-11-30": ded_r7,
       "2026-12-01": ded_r8, "2027-01-01": ded_r8}


def check(recs, ded):
    res = {"n_records": len(recs), "gaps_or_overlaps": [], "step_histogram": {}, "formula_mismatch": [], "formula_rows": [],
           "first": recs[0], "last": recs[-1]}
    ranged = [r for r in recs if r["kind"] != "point"]
    for p, q in zip(ranged, ranged[1:]):
        if p["upper"] != q["lower"]:
            res["gaps_or_overlaps"].append({"prev": p, "next": q})
    steps = Counter(r["upper"] - r["lower"] for r in ranged if r["kind"] == "fixed" and r["lower"] > 0)
    res["step_histogram"] = {str(k): v for k, v in sorted(steps.items())}
    # 刻み幅ごとの範囲
    runs = []
    for r in ranged:
        w = r["upper"] - r["lower"] if r["kind"] == "fixed" and r["lower"] > 0 else r["kind"]
        if runs and runs[-1]["width"] == w and runs[-1]["upper"] == r["lower"]:
            runs[-1]["upper"] = r["upper"]
            runs[-1]["n"] += 1
        else:
            runs.append({"width": w, "lower": r["lower"], "upper": r["upper"], "n": 1})
    res["runs"] = runs
    # 仮説：表の値 = 第28条第3項の式を区分の下限で評価した「下限 − 給与所得控除額」
    for r in recs:
        if r["kind"] == "fixed" and r["lower"] > 0:
            exp = art28_floor(r["lower"], ded)
            if exp != r["value"]:
                res["formula_mismatch"].append({"lower": r["lower"], "upper": r["upper"], "table": r["value"], "formula_at_lower": exp})
        elif r["kind"] in ("minus", "rate_minus"):
            # 式の区分：式と第28条第3項（1円未満切捨て）が一致するか。
            # 6,600,000 円未満の区分はすべての整数 x で調べる。それ以上の区分は、両端の各 20,000 円と、その間を 997 円おきに調べる。
            bad = []
            if r["upper"] <= 6_600_000:
                xs = range(r["lower"], r["upper"])
            else:
                xs = sorted(set(range(r["lower"], min(r["upper"], r["lower"] + 20_000))) |
                            set(range(max(r["lower"], r["upper"] - 20_000), r["upper"])) |
                            set(range(r["lower"], r["upper"], 997)))
            res.setdefault("formula_rows_checked_points", {})[f"{r['lower']}-{r['upper']}"] = len(xs)
            for x in xs:
                v = x - r["c"] if r["kind"] == "minus" else x * r["rate_pct"] // 100 - r["c"]
                e = art28_floor(x, ded)
                if v != e:
                    bad.append({"x": x, "table_formula": v, "art28": e})
                    if len(bad) > 5:
                        break
            res["formula_rows"].append({k: r[k] for k in ("lower", "upper", "kind", "c")} | {"rate_pct": r.get("rate_pct"), "mismatch_sample": bad})
        elif r["kind"] == "point":
            res["point"] = {"x": r["lower"], "table": r["value"], "art28": art28_floor(r["lower"], ded)}
        elif r["kind"] == "fixed" and r["lower"] == 0:
            res["below_first"] = {"upper": r["upper"], "value": r["value"],
                                  "art28_at_upper_minus_1": max(0, art28_floor(r["upper"] - 1, ded))}
    return res


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    files = sorted(IN.glob("beppyo5_grid_*.json"))
    if not files:
        sys.exit("先に scripts/IMPL_kyuyo_fetch.py を実行する")
    tables, summary = {}, ["# 所得税法 別表第五の抽出と検査（IMPL_kyuyo_beppyo5.py）", ""]
    for f in files:
        g = json.loads(f.read_text(encoding="utf-8"))
        asof = g["asof"]
        recs = records_from(g)
        tables[asof] = recs
        meta = {k: g.get(k) for k in ("law_id", "asof", "law_revision_id", "current_revision_status", "source_url", "source_sha256", "fetched_at",
                                      "title", "related_article_num")}
        remarks = [x for st in g["structs"] for x in st["remarks"]] + g["remarks"]
        (OUT / f"beppyo5_{asof}.json").write_text(json.dumps({"meta": meta, "remarks": remarks, "records": recs}, ensure_ascii=False, indent=1), encoding="utf-8")
        with open(OUT / f"beppyo5_{asof}.csv", "w", encoding="utf-8", newline="") as fp:
            w = csv.writer(fp)
            w.writerow(["lower_incl", "upper_excl", "kind", "value", "formula_c", "formula_rate_pct", "struct", "group", "row", "source_text"])
            for r in recs:
                w.writerow([r["lower"], r["upper"] if r["upper"] is not None else "", r["kind"], r["value"] if r["value"] is not None else "",
                            r.get("c", ""), r.get("rate_pct", ""), r["struct"], r["group"], r["row"], r["text"]])
        ck = check(recs, DED[asof])
        (OUT / f"check_{asof}.json").write_text(json.dumps(ck, ensure_ascii=False, indent=1), encoding="utf-8")
        summary += [f"## asof={asof}（{meta['law_revision_id']}、{meta['current_revision_status']}）", "",
                    f"- 区分の数：{ck['n_records']}（最初：{recs[0]['text']}／最後：{recs[-1]['text']}）",
                    f"- 区分の隙間・重なり：{len(ck['gaps_or_overlaps'])} 件",
                    f"- 金額の区分の刻み幅（円: 個数）：{ck['step_histogram']}",
                    f"- 第28条第3項の式を区分の下限で評価した値と表の値の不一致：{len(ck['formula_mismatch'])} 件",
                    f"- 下限 0 の区分：{ck.get('below_first')}",
                    f"- 点の値：{ck.get('point')}",
                    "- 式の区分：" + "; ".join(f"[{x['lower']:,}, {x['upper']:,}) {x['kind']} c={x['c']:,} rate={x['rate_pct']} 不一致={len(x['mismatch_sample'])}"
                                         for x in ck["formula_rows"]),
                    "- 刻み幅の続く範囲：" + "; ".join(f"[{x['lower']:,}, {x['upper']:,}) 幅={x['width']} ×{x['n']}" for x in ck["runs"]),
                    f"- 備考（原文）：{remarks}", ""]
        print(asof, ck["n_records"], len(ck["gaps_or_overlaps"]), len(ck["formula_mismatch"]), flush=True)
    # 版の比較
    keys = sorted(tables)
    vd = []
    for a, b in zip(keys, keys[1:]):
        ta = {(r["lower"], r["upper"], r["kind"]): (r["value"], r.get("c"), r.get("rate_pct")) for r in tables[a]}
        tb = {(r["lower"], r["upper"], r["kind"]): (r["value"], r.get("c"), r.get("rate_pct")) for r in tables[b]}
        only_a = sorted(set(ta) - set(tb), key=lambda k: k[0])
        only_b = sorted(set(tb) - set(ta), key=lambda k: k[0])
        changed = sorted([k for k in set(ta) & set(tb) if ta[k] != tb[k]], key=lambda k: k[0])
        vd.append({"a": a, "b": b, "identical": not (only_a or only_b or changed), "n_only_a": len(only_a), "n_only_b": len(only_b),
                   "n_changed": len(changed), "only_a_head": only_a[:10], "only_b_head": only_b[:10], "changed_head": [(k, ta[k], tb[k]) for k in changed[:10]],
                   "only_a_range": [only_a[0][0], only_a[-1][1]] if only_a else None,
                   "only_b_range": [only_b[0][0], only_b[-1][1]] if only_b else None})
    (OUT / "version_diff.json").write_text(json.dumps(vd, ensure_ascii=False, indent=1), encoding="utf-8")
    summary += ["## 版の比較（隣り合う asof）", ""] + [
        f"- {x['a']} → {x['b']}：{'同一' if x['identical'] else '相違'}（前だけ {x['n_only_a']}、後だけ {x['n_only_b']}、値の変化 {x['n_changed']}。"
        f"前だけの範囲 {x['only_a_range']}、後だけの範囲 {x['only_b_range']}）" for x in vd]
    # R7 と R8 の表で、同じ給与等の金額に対する値が違う範囲（1,000円刻みで比較）
    def lookup(recs, x):
        for r in recs:
            if r["kind"] == "point":
                if x == r["lower"]:
                    return r["value"]
                continue
            if r["lower"] <= x < r["upper"]:
                if r["kind"] == "fixed":
                    return r["value"]
                if r["kind"] == "minus":
                    return x - r["c"]
                return x * r["rate_pct"] // 100 - r["c"]
        return None
    diffs = []
    pairs = [("2024-12-31", "2025-12-31"), ("2025-12-31", "2026-12-01")]
    for a, b in pairs:
        prev = None
        for x in range(0, 6_600_000, 1000):
            va, vb = lookup(tables[a], x), lookup(tables[b], x)
            d = (va != vb)
            if d and (prev is None or not prev["open"]):
                prev = {"a": a, "b": b, "from": x, "to": None, "open": True, "example": [x, va, vb]}
                diffs.append(prev)
            if not d and prev is not None and prev["open"]:
                prev["to"] = x
                prev["open"] = False
        if prev is not None and prev["open"]:
            prev["to"] = 6_600_000
    (OUT / "value_diff_ranges.json").write_text(json.dumps(diffs, ensure_ascii=False, indent=1), encoding="utf-8")
    summary += ["", "## 値が違う範囲（1,000円刻みで 0〜6,599,000 円を比較）", ""] + [
        f"- {d['a']} と {d['b']}：[{d['from']:,}, {d['to']:,}) で違う（例 {d['example']}）" for d in diffs]
    (OUT / "summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    print("done", OUT)


if __name__ == "__main__":
    main()

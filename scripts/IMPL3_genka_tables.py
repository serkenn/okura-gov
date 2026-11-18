"""IMPL3 genka: 耐用年数省令の別表第七・第八・第九・第十・第十一を、取得済みの e-Gov の本文（構造化した JSON）から数値の表にし、
令和7年分（asof 2025-12-31）と令和8年分（asof 2026-12-31）の版が同じかを確かめ、償却率の作り方（端数の処理）を観察する。

実行（リポジトリのルートで。Python 3.11、標準ライブラリのみ。ネットワークは使わない）:
  C:\\Users\\user\\.pyenv\\pyenv-win\\versions\\3.11.9\\python.exe -I -X utf8 scripts/IMPL3_genka_tables.py

- 入力：scripts/results/R2X_genka_laws/taiyo_tables_2025-12-31.json・taiyo_tables_2026-12-31.json
  （scripts/R2X_genka_laws.py taiyo が e-Gov 法令API v2 の /law_data/340M50000040015 から作ったもの。版は各 JSON の law_revision_id）。
- 出力：scripts/results/IMPL3_genka_tables/
    beppyo<7|8|9|10>_<asof>.csv     耐用年数ごとの率（小数の文字列。法令の表記を算用数字にしたもの）
    beppyo11_<asof>.csv            残存割合（種類・細目・割合）
    summary.json                   版の同一性、行数、端数の処理の観察（式で再現できるか）
- 端数の観察は「表の値がどの式・どの丸めで再現できるか」を数えるだけで、実装では表の値そのものを使う（式は法令に書かれていない）。
"""
import csv
import json
import pathlib
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

ROOT = pathlib.Path(__file__).resolve().parent.parent
IN = ROOT / "scripts" / "results" / "R2X_genka_laws"
OUT = ROOT / "scripts" / "results" / "IMPL3_genka_tables"
ASOFS = ["2025-12-31", "2026-12-31"]
KD = {"〇": "0", "一": "1", "二": "2", "三": "3", "四": "4", "五": "5", "六": "6", "七": "7", "八": "8", "九": "9", "・": "."}


def kanji_decimal(s):
    s = s.strip()
    if not s or set(s) <= set("―ー－-"):
        return None
    if all(ch in KD for ch in s):
        return "".join(KD[ch] for ch in s)
    raise ValueError(s)


def kanji_int(s):
    """耐用年数の欄（二、十、二十五、百 など）を整数にする。"""
    s = s.strip()
    d = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if s == "百":
        return 100
    if s and all(ch in KD and ch != "・" for ch in s):
        return int("".join(KD[ch] for ch in s))  # 位取りの書き方（一〇、一一、一〇〇）。表はこの書き方
    total, cur = 0, 0
    for ch in s:
        if ch in d:
            cur = d[ch]
        elif ch == "十":
            total += (cur or 1) * 10
            cur = 0
        else:
            raise ValueError(s)
    return total + cur


def table(tables, prefix):
    for t in tables:
        if t["title"].split()[0] == prefix if t["title"].split() else False:
            return t
    raise KeyError(prefix)


def rate_rows(t):
    rows = t["structs"][0]["rows"]
    out = []
    for r in rows:
        try:
            n = kanji_int(r[0])
        except ValueError:
            continue  # 見出しの行（耐用年数・年）
        out.append([n] + [kanji_decimal(x) for x in r[1:]])
    return out


def q(x, places, mode):
    return Decimal(x).quantize(Decimal(1).scaleb(-places), rounding=mode)


def observe(name, rows, col, fn, places):
    """表の値 rows[i][col] が fn(N) の丸め（切捨て・四捨五入）で再現できる件数を数える。"""
    res = {"down": 0, "half_up": 0, "neither": [], "n": 0}
    for r in rows:
        v = r[col]
        if v is None:
            continue
        exact = fn(r[0])
        if exact is None:
            continue
        res["n"] += 1
        val = Decimal(v)
        d_ok = q(exact, places, ROUND_DOWN) == val
        h_ok = q(exact, places, ROUND_HALF_UP) == val
        res["down"] += d_ok
        res["half_up"] += h_ok
        if not d_ok and not h_ok:
            res["neither"].append({"耐用年数": r[0], "表": v, "式の値": str(exact)[:12]})
    res["name"] = name
    return res


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {"input": {}, "same_between_versions": {}, "rows": {}, "observations": {}}
    parsed = {}
    for asof in ASOFS:
        p = IN / f"taiyo_tables_{asof}.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        summary["input"][asof] = {"file": str(p.relative_to(ROOT)), "law_revision_id": d.get("law_revision_id"),
                                  "current_revision_status": d.get("current_revision_status"), "url": d.get("url")}
        tabs = d["tables"]
        parsed[asof] = {}
        for k, prefix, header in [(7, "別表第七", ["耐用年数", "旧定額法の償却率", "旧定率法の償却率"]),
                                  (8, "別表第八", ["耐用年数", "定額法の償却率"]),
                                  (9, "別表第九", ["耐用年数", "償却率", "改定償却率", "保証率"]),
                                  (10, "別表第十", ["耐用年数", "償却率", "改定償却率", "保証率"])]:
            t = table(tabs, prefix)
            rows = rate_rows(t)
            parsed[asof][k] = {"title": t["title"], "rows": rows}
            with (OUT / f"beppyo{k}_{asof}.csv").open("w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(header)
                for r in rows:
                    w.writerow([r[0]] + ["" if x is None else x for x in r[1:]])
        t11 = table(tabs, "別表第十一")
        rows11 = [r for r in t11["structs"][0]["rows"] if r and r[0] != "種類"]
        parsed[asof][11] = {"title": t11["title"], "rows": rows11}
        with (OUT / f"beppyo11_{asof}.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["種類", "細目", "残存割合"])
            for r in rows11:
                w.writerow(r)
    for k in (7, 8, 9, 10, 11):
        a, b = parsed[ASOFS[0]][k], parsed[ASOFS[1]][k]
        summary["same_between_versions"][f"別表{k}"] = (a["rows"] == b["rows"] and a["title"] == b["title"])
        summary["rows"][f"別表{k}"] = {"title": b["title"], "rows": len(b["rows"]),
                                      "耐用年数の範囲": [b["rows"][0][0], b["rows"][-1][0]] if k != 11 else None}
    r7 = parsed[ASOFS[1]][7]["rows"]
    r8 = parsed[ASOFS[1]][8]["rows"]
    r9 = parsed[ASOFS[1]][9]["rows"]
    r10 = parsed[ASOFS[1]][10]["rows"]
    obs = summary["observations"]
    obs["別表7 旧定額法 = 1/N"] = observe("旧定額法", r7, 1, lambda n: Decimal(1) / Decimal(n), 3)
    obs["別表7 旧定額法 = 0.9/N（残存価額10%を除く比）"] = observe("旧定額法0.9", r7, 1, lambda n: Decimal("0.9") / Decimal(n), 3)

    def kyuteiritsu(n):
        # 1 - 0.1^(1/N)（残存価額 10% に N 年で達する逓減率）を Decimal で
        from decimal import getcontext
        getcontext().prec = 40
        return Decimal(1) - Decimal("0.1") ** (Decimal(1) / Decimal(n))
    obs["別表7 旧定率法 = 1-0.1^(1/N)"] = observe("旧定率法", r7, 2, kyuteiritsu, 3)
    obs["別表8 定額法 = 1/N"] = observe("定額法", r8, 1, lambda n: Decimal(1) / Decimal(n), 3)
    obs["別表9 定率法 = 2.5/N（1を超えるものを除く）"] = observe("250%定率法", r9, 1, lambda n: (Decimal("2.5") / Decimal(n)) if n > 2 else None, 3)
    obs["別表10 定率法 = 2/N（1を超えるものを除く）"] = observe("200%定率法", r10, 1, lambda n: (Decimal(2) / Decimal(n)) if n > 2 else None, 3)
    # 別表9・10：改定償却率・保証率が「―」の耐用年数
    summary["dash_rows"] = {
        "別表9": [r[0] for r in r9 if any(x is None for x in r[1:])],
        "別表10": [r[0] for r in r10 if any(x is None for x in r[1:])],
    }
    # 抜き出し（文書に写す行）
    pick = [2, 3, 4, 5, 6, 8, 10, 15, 20, 22, 24, 30, 33, 34, 38, 47, 50, 100]
    summary["sample"] = {
        "別表7": {n: r[1:] for r in r7 for n in pick if r[0] == n},
        "別表9": {n: r[1:] for r in r9 for n in pick if r[0] == n},
        "別表10": {n: r[1:] for r in r10 for n in pick if r[0] == n},
        "別表11": parsed[ASOFS[1]][11]["rows"],
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("same_between_versions", "rows", "dash_rows")}, ensure_ascii=False, indent=1))
    for k, v in obs.items():
        print(k, "n=", v["n"], "切捨て=", v["down"], "四捨五入=", v["half_up"], "どちらでもない=", len(v["neither"]), v["neither"][:5])


if __name__ == "__main__":
    main()

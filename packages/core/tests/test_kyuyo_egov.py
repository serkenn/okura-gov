"""給与所得の金額を、e-Gov の別表第五の格子（実測の生の出力）と条文から独立に作った期待値と、全区分の境目で照合する。

data/ の CSV（前の実測のスクリプトで抽出したもの）を経由しない。このテストは自分で格子を展開して区分を作り、
  1. CSV の全区分（下限・上限・種類・値）が、格子から作った区分と一致すること
  2. 全区分の下限・上限の1円手前（＝次の区分の下限の1円手前）・式の区分の中の点で、kyuyo_shotoku と
     evaluate の値が期待値と一致すること
  3. 刻みの区分の金額が、その年分の第28条第3項の式を区分の下限で評価した値と一致すること（表と条文の突き合わせ）
を確かめる。

期待値の出典（どれも docs に記録した一次情報）：
  - 別表第五の格子：scripts/results/IMPL_kyuyo_fetch/beppyo5_grid_<asof>.json
    （docs/measurements/20261109_impl-prep_kyuyo-beppyo5.md §1・§3。e-Gov 法令API v2 の本文の AppdxTable）
  - 第28条第3項・第4項の原文：scripts/results/IMPL_kyuyo_fetch/articles_shotoku_<asof>.txt の Num=28
    （docs/public-sources/20261109_impl-prep_kyuyo-sources.md §1.1）
  - 措置法第29条の4第2項の原文：docs/public-sources/20261109_impl-prep_kyuyo-sources.md §2.1
  - 660万円以上の1円未満の切捨て：別表第五の備考（同 §1.2。法令の読み：rounding.KYUYO_SHOTOKU_660MAN_FLOOR）
"""

from __future__ import annotations

import csv
import json
import math
import re
import unittest
from fractions import Fraction
from pathlib import Path

from okura_core import evaluate
from okura_core.rules.kyuyo.calc import kyuyo_shotoku, rules_from_parameters
from okura_core.rules.kyuyo.tables import DATA_DIR, sources
from okura_core.money import INT32_MAX
from okura_core.result import YenAmount

from .support import REPO, make_query, system, wages_ir

GRID_DIR = REPO / "scripts" / "results" / "IMPL_kyuyo_fetch"
#: 年分 → 別表第五の版（asof）。所得税法の版の対応は docs/public-sources/20261109_impl-prep_kyuyo-sources.md §0。
VERSIONS = {2025: "2025-12-31", 2026: "2026-12-01"}

_ZEN = str.maketrans("０１２３４５６７８９，％", "0123456789,%")
_NUM = re.compile(r"[0-9][0-9,]*")
_MINUS = re.compile(r"給与等の金額から([0-9,]+)円を控除した金額")
_RATE_MINUS = re.compile(r"給与等の金額に([0-9]+)%を乗じて算出した金額から([0-9,]+)円を控除した金額")
_BELOW = re.compile(r"([0-9,]+)円未満")
_POINT = re.compile(r"([0-9,]+)円")

Value = int | tuple  # 金額か ("minus", c) か ("rate_minus", 率%, c)


def _int(s: str) -> int:
    return int(s.replace(",", ""))


def _value(text: str) -> Value:
    t = text.translate(_ZEN).strip()
    if m := _MINUS.fullmatch(t):
        return ("minus", _int(m.group(1)))
    if m := _RATE_MINUS.fullmatch(t):
        return ("rate_minus", int(m.group(1)), _int(m.group(2)))
    t = t.removesuffix("円")
    if _NUM.fullmatch(t):
        return _int(t)
    raise ValueError(f"金額でも式でもないセル: {text!r}")


def parse_grid(path: Path) -> tuple[dict, list[tuple[int, int | None, Value]]]:
    """格子（行ごとのセル・rowspan・colspan）を HTML の表と同じ規則で9列に展開し、区分の並びを作る。"""
    g = json.loads(path.read_text(encoding="utf-8"))
    rows: list[tuple[int, int | None, Value]] = []
    for struct in g["structs"]:
        carry: dict[int, list] = {}  # 列 → [残りの行数, セル]（rowspan で下の行に伸びるセル）
        for raw in struct["rows"]:
            cols: list[tuple[str, dict] | None] = [None] * 9
            for c in sorted(carry):
                cols[c] = ("span", carry[c][1])
                carry[c][0] -= 1
                if carry[c][0] == 0:
                    del carry[c]
            i = 0
            for cell in raw:
                while cols[i] is not None:
                    i += 1
                for k in range(cell["colspan"]):
                    cols[i + k] = ("cell", cell)
                if cell["rowspan"] > 1:
                    carry[i] = [cell["rowspan"] - 1, cell]
                i += cell["colspan"]
            assert all(c is not None for c in cols), f"9列に満たない行: {raw}"
            for grp in range(3):
                a, b, v = cols[3 * grp], cols[3 * grp + 1], cols[3 * grp + 2]
                ta = a[1]["text"].translate(_ZEN).strip()
                tb = b[1]["text"].translate(_ZEN).strip()
                if a[1]["colspan"] == 2:  # 「◯円未満」か最後の「20,000,000円」（2列にまたがる）
                    if m := _BELOW.fullmatch(ta):
                        rows.append((0, _int(m.group(1)), _value(v[1]["text"])))
                    elif m := _POINT.fullmatch(ta):
                        rows.append((_int(m.group(1)), None, _value(v[1]["text"])))
                    elif ta not in ("給与等の金額",):
                        raise ValueError(f"知らない2列のセル: {ta!r}")
                    continue
                if _NUM.fullmatch(ta) and _NUM.fullmatch(tb):
                    rows.append((_int(ta), _int(tb), _value(v[1]["text"])))
                elif ta or tb:
                    assert ta in ("以上", "円") and tb in ("未満", "円"), (ta, tb)
    rows.sort(key=lambda r: r[0])
    return g, rows


def table_value(v: Value, x: int) -> int:
    if isinstance(v, int):
        return v
    if v[0] == "minus":
        return x - v[1]
    return math.floor(Fraction(x * v[1], 100)) - v[2]  # 660万円以上の1円未満は切捨て（別表第五の備考）


def art28_deduction(year: int, x: int) -> Fraction:
    """第28条第3項の給与所得控除額（令和7年分の版・令和8年分の版の原文どおり。丸めない）。"""
    if year == 2025:
        if x <= 1_900_000:
            return Fraction(650_000)
        if x <= 3_600_000:
            return 650_000 + Fraction(x - 1_900_000) * Fraction(30, 100)
    else:
        if x <= 3_600_000:
            return max(80_000 + Fraction(x) * Fraction(30, 100), Fraction(690_000))
    if x <= 6_600_000:
        return 1_160_000 + Fraction(x - 3_600_000) * Fraction(20, 100)
    if x <= 8_500_000:
        return 1_760_000 + Fraction(x - 6_600_000) * Fraction(10, 100)
    return Fraction(1_950_000)


def sochi_29_4_2(x: int) -> int | None:
    """措置法第29条の4第2項（令和8年・令和9年）。範囲の外は None。"""
    if 691_000 <= x < 741_000:
        return 0
    if 741_000 <= x < 2_191_000:
        return x - 740_000
    if 2_191_000 <= x < 2_193_000:
        return 1_451_000
    if 2_193_000 <= x < 2_196_000:
        return 1_453_000
    if 2_196_000 <= x < 2_200_000:
        return 1_456_000
    return None


def expected(year: int, rows: list[tuple[int, int | None, Value]], x: int) -> int:
    if year == 2026 and (s := sochi_29_4_2(x)) is not None:
        return s
    if x < 6_600_000:  # 第28条第4項：別表第五
        for lo, up, v in rows:
            if lo <= x and (up is not None and x < up):
                return table_value(v, x)
        raise AssertionError(f"区分の外: {x}")
    return math.floor(x - art28_deduction(year, x))  # 第28条第2項・第3項（1円未満は切捨て）


def check_points(rows: list[tuple[int, int | None, Value]]) -> list[int]:
    """全区分の下限・上限の1円手前と、式の区分の中の点。"""
    pts: set[int] = set()
    for lo, up, v in rows:
        pts.add(lo)
        if lo > 0:
            pts.add(lo - 1)
        if up is not None:
            pts.add(up - 1)
            if not isinstance(v, int):
                pts.update({lo + 1, (lo + up) // 2, (lo + up) // 2 + 1, up - 2})
    pts.update({20_000_001, 25_450_000, 25_450_001, INT32_MAX})
    return sorted(pts)


def _grid(year: int) -> Path:
    return GRID_DIR / f"beppyo5_grid_{VERSIONS[year]}.json"


class TestAgainstEgovGrid(unittest.TestCase):
    def setUp(self) -> None:
        for year in VERSIONS:
            if not _grid(year).exists():
                self.skipTest(f"e-Gov の格子（実測の出力）がない: {_grid(year)}")

    def test_grid_is_contiguous_and_matches_the_recorded_revision(self) -> None:
        for year, asof in VERSIONS.items():
            g, rows = parse_grid(_grid(year))
            info = sources()["files"][f"beppyo5_{asof}.csv"]
            self.assertEqual(g["law_revision_id"], info["law_revision_id"])
            self.assertEqual(g["source_sha256"], info["egov_source_sha256"])
            self.assertEqual(rows[0][0], 0)
            for (lo1, up1, _), (lo2, _, _) in zip(rows, rows[1:]):
                self.assertEqual(up1, lo2, f"{year}: 区分に隙間・重なり（{lo1}）")
            self.assertEqual(rows[-1], (20_000_000, None, 18_050_000))
            self.assertEqual(len(rows), {2025: 1180, 2026: 1149}[year])  # 実測 §3 の区分の数

    def test_csv_rows_equal_grid_rows(self) -> None:
        for year, asof in VERSIONS.items():
            _, rows = parse_grid(_grid(year))
            with (DATA_DIR / f"beppyo5_{asof}.csv").open(encoding="utf-8", newline="") as f:
                csv_rows = []
                for r in csv.DictReader(f):
                    up = int(r["upper_excl"]) if r["upper_excl"] else None
                    if r["kind"] in ("fixed", "point"):
                        v: Value = int(r["value"])
                    elif r["kind"] == "minus":
                        v = ("minus", int(r["formula_c"]))
                    else:
                        v = ("rate_minus", int(r["formula_rate_pct"]), int(r["formula_c"]))
                    csv_rows.append((int(r["lower_incl"]), up, v))
            self.assertEqual(csv_rows, rows, year)

    def test_fixed_rows_equal_article_28_at_the_lower_end(self) -> None:
        """刻みの区分の金額 ＝ 下限 − 第28条第3項の控除額（下限で評価）。0 の区分は「◯円未満 → 0」で別に確かめる。"""
        for year in VERSIONS:
            _, rows = parse_grid(_grid(year))
            n = 0
            for lo, up, v in rows:
                if isinstance(v, int) and lo > 0 and up is not None:
                    n += 1
                    self.assertEqual(v, math.floor(lo - art28_deduction(year, lo)), (year, lo))
            self.assertGreater(n, 1000)
            zero = rows[0]
            self.assertEqual(zero[2], 0)
            # 0 の区分の上端（651,000・691,000）は、第28条第3項の最低の控除額（65万・69万）＋1,000
            self.assertEqual(zero[1], {2025: 651_000, 2026: 691_000}[year])

    def test_kyuyo_shotoku_at_every_boundary(self) -> None:
        for year in VERSIONS:
            _, rows = parse_grid(_grid(year))
            r = rules_from_parameters(system().get_parameters_at_instant(f"{year}-01-01"))
            pts = check_points(rows)
            bad = [(x, kyuyo_shotoku(x, r).value, expected(year, rows, x)) for x in pts]
            bad = [b for b in bad if b[1] != b[2]]
            self.assertEqual(bad[:10], [], f"{year}: {len(bad)} 点で不一致（{len(pts)} 点中）")

    def test_660man_and_above_equals_the_table_formula_up_to_20m(self) -> None:
        """660万円以上は第28条第2項・第3項の式で計算するが、2,000万円までは別表第五の式の区分とも一致する。"""
        for year in VERSIONS:
            _, rows = parse_grid(_grid(year))
            formula_rows = [(lo, up, v) for lo, up, v in rows if lo >= 6_600_000]
            for lo, up, v in formula_rows:
                xs = (lo,) if up is None else (lo, lo + 1, lo + 3, lo + 7, (lo + up) // 2, up - 1)  # 最後は1点
                for x in xs:
                    with self.subTest(year=year, x=x):
                        self.assertEqual(table_value(v, x), math.floor(x - art28_deduction(year, x)))



if __name__ == "__main__":
    unittest.main()

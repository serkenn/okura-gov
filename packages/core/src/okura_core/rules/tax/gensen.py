"""給与等の源泉徴収税額表（所得税法 別表第二〜第四）の読み込みと引き方（純粋関数）。

一次情報：docs/public-sources/20261111_impl-research3_gensen-laws.md（［PS3-GS］）§1・§2、表の数値化と版の比較は
docs/measurements/20261111_impl-research3_all-fetch-and-checks.md §4（scripts/IMPL3_gensen_tables.py の出力を data/ に写した。SOURCES.json）。

- 版：支払日が令和7年中なら 2025-12-31 の版、令和8年中なら 2026-01-01 の版（［PS3-GS］§2 の最後：版の切替わりの日の観察。改正法の附則は未取得）。
- 別表第二（月額表）・第三（日額表）：「その月（日）の社会保険料等控除後の給与等の金額」の帯（以上・未満）ごとに甲（扶養親族等の数 0〜7人）・乙（日額表は丙も）。
  - 最初の帯より下：甲は0、乙は金額の3％（［PS3-GS］§2）。3％の1円未満の扱いは docs にないので Fraction のまま返す（呼ぶ側が根拠のない端数として扱う）。丙は docs にない（None）。
  - 扶養親族等が7人を超えるとき：7人の税額から超える1人ごとに月額表 1,580円・日額表 50円を控除（備考。SOURCES.json の per_person_over_seven_yen）。
    控除した結果が負になるときの扱いは docs にないので None。
  - 帯の上（月額表 740,000円以上・日額表 24,000円以上）は表が式の行で、数値の表にない（None）。
- 別表第四（賞与の算出率）：前月の社会保険料等控除後の給与等の金額（千円）の帯ごとの率。甲は扶養親族等の数 0〜6人・7人以上、乙は率の段の一部だけに帯がある。

None は「この表の数値からは決まらない」。呼ぶ側は対象外ではなく未確定（何を入力・取得すれば決まるか）にする。
"""

from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import io
import json
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent / "data"

KO = "甲"
OTSU = "乙"
HEI = "丙"


class GensenTableError(ValueError):
    """表のファイルの誤り（SHA-256 の食い違い・帯の隙間など）。"""


def sources() -> dict[str, Any]:
    return json.loads((DATA_DIR / "SOURCES.json").read_text(encoding="utf-8"))


def version_for(paid_on: _dt.date) -> str:
    """支払日から使う表の版（令和7年中は 2025-12-31、令和8年中は 2026-01-01）。それ以外の年は表を持たない（ValueError）。"""
    if paid_on.year == 2025:
        return "2025-12-31"
    if paid_on.year == 2026:
        return "2026-01-01"
    raise ValueError(f"{paid_on.year}年に支払う給与等の源泉徴収税額表を持たない")


def _read(name: str) -> tuple[list[list[str]], dict[str, Any]]:
    info = sources()["files"].get(name)
    if info is None:
        raise GensenTableError(f"知らない表: {name}")
    raw = (DATA_DIR / name).read_bytes()
    if hashlib.sha256(raw).hexdigest() != info["sha256"]:
        raise GensenTableError(f"{name} の SHA-256 が SOURCES.json と違う")
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8"))))
    return rows, info


@dataclass(frozen=True)
class Band:
    lower: int
    upper: int
    ko: tuple[int, ...]  # 甲 0〜7人
    otsu: int
    hei: int | None


@dataclass(frozen=True)
class WageTable:
    table_id: str
    bands: tuple[Band, ...]
    per_person: int

    @property
    def first_lower(self) -> int:
        return self.bands[0].lower

    @property
    def last_upper(self) -> int:
        return self.bands[-1].upper


@lru_cache(maxsize=None)
def load_wage_table(kind: str, version: str) -> WageTable:
    """kind は getsugaku（別表第二）か nichigaku（別表第三）。"""
    name = f"{kind}_{version}.csv"
    rows, info = _read(name)
    header, body = rows[0], rows[1:]
    has_hei = header[-1] == HEI
    bands: list[Band] = []
    for r in body:
        nums = [int(x) for x in r]
        b = Band(nums[0], nums[1], tuple(nums[2:10]), nums[10], nums[11] if has_hei else None)
        if bands and bands[-1].upper != b.lower:
            raise GensenTableError(f"{name}：帯に隙間・重なりがある（{bands[-1].upper} → {b.lower}）")
        if b.lower >= b.upper:
            raise GensenTableError(f"{name}：帯の上下が逆")
        bands.append(b)
    if not bands:
        raise GensenTableError(f"{name}：帯がない")
    return WageTable(name[:-4], tuple(bands), int(info["per_person_over_seven_yen"]))


def wage_tax(kind: str, paid_on: _dt.date, amount: int, column: str, dependents: int = 0) -> Fraction | None:
    """別表第二（kind=getsugaku）・第三（kind=nichigaku）の税額。amount は社会保険料等控除後の給与等の金額（月額・日額）。

    column は甲・乙・丙、dependents は甲の扶養親族等の数（加算の後）。表の数値から決まらなければ None。
    """
    if type(amount) is not int or amount < 0:
        raise ValueError("社会保険料等控除後の給与等の金額は0以上の整数の円")
    if type(dependents) is not int or dependents < 0:
        raise ValueError("扶養親族等の数は0以上の整数")
    if column not in (KO, OTSU, HEI):
        raise ValueError(f"欄は甲・乙・丙のどれか: {column}")
    t = load_wage_table(kind, version_for(paid_on))
    if amount < t.first_lower:
        if column == KO:
            return Fraction(0)
        if column == OTSU:
            return Fraction(amount * 3, 100)
        return None  # 丙の最初の帯より下は docs にない
    if amount >= t.last_upper:
        return None  # 式の行（数値の表にない）
    band = next(b for b in t.bands if b.lower <= amount < b.upper)
    if column == OTSU:
        return Fraction(band.otsu)
    if column == HEI:
        return None if band.hei is None else Fraction(band.hei)
    if dependents <= 7:
        return Fraction(band.ko[dependents])
    v = band.ko[7] - t.per_person * (dependents - 7)
    return Fraction(v) if v >= 0 else None


@dataclass(frozen=True)
class RateRow:
    rate_percent: int
    ko: tuple[tuple[int | None, int | None], ...]  # 甲 0〜6人・7人以上の（以上, 未満）千円。None は端（未満だけ・以上だけ）
    otsu: tuple[int | None, int | None] | None


def _cell(text: str) -> tuple[int | None, str]:
    """「82」→ (82, "")、「82千円未満」→ (82, "未満")、「3495千円以上」→ (3495, "以上")。空は (None, "")。"""
    s = text.strip()
    if not s:
        return None, ""
    for suffix in ("千円未満", "千円以上"):
        if s.endswith(suffix):
            return int(s[: -len(suffix)]), suffix[-2:]
    return int(s), ""


def _range(lo: str, hi: str) -> tuple[int | None, int | None] | None:
    a, ka = _cell(lo)
    b, kb = _cell(hi)
    if a is None and b is None:
        return None
    if ka == "未満":
        return (None, a)
    if ka == "以上":
        return (a, None)
    return (a, b)


@lru_cache(maxsize=None)
def load_bonus_table(version: str) -> tuple[RateRow, ...]:
    name = f"shoyo_{version}.csv"
    rows, _info = _read(name)
    out: list[RateRow] = []
    for r in rows[1:]:
        ko = tuple(_range(r[1 + 2 * i], r[2 + 2 * i]) for i in range(8))
        if any(x is None for x in ko):
            raise GensenTableError(f"{name}：甲の帯がない行がある（率 {r[0]}％）")
        out.append(RateRow(int(r[0]), ko, _range(r[17], r[18])))  # type: ignore[arg-type]
    return tuple(out)


def _within(rng: tuple[int | None, int | None], thousand: Fraction) -> bool:
    lo, hi = rng
    return (lo is None or thousand >= lo) and (hi is None or thousand < hi)


def bonus_rate(paid_on: _dt.date, previous_month_amount: int, column: str, dependents: int = 0) -> Fraction | None:
    """別表第四の率（百分率を Fraction にしたもの）。previous_month_amount は前月の社会保険料等控除後の給与等の金額（円）。

    乙は表に帯のある段（率の一部）だけから引く。どの帯にも当たらなければ None。
    """
    if type(previous_month_amount) is not int or previous_month_amount < 0:
        raise ValueError("前月の社会保険料等控除後の給与等の金額は0以上の整数の円")
    if column not in (KO, OTSU):
        raise ValueError(f"欄は甲・乙のどれか: {column}")
    thousand = Fraction(previous_month_amount, 1000)
    hits: list[int] = []
    for row in load_bonus_table(version_for(paid_on)):
        if column == KO:
            rng = row.ko[min(dependents, 7)]
        else:
            if row.otsu is None:
                continue
            rng = row.otsu
        if _within(rng, thousand):
            hits.append(row.rate_percent)
    if len(hits) != 1:
        return None
    return Fraction(hits[0], 100)


__all__ = [
    "DATA_DIR",
    "GensenTableError",
    "HEI",
    "KO",
    "OTSU",
    "bonus_rate",
    "load_bonus_table",
    "load_wage_table",
    "sources",
    "version_for",
    "wage_tax",
]
